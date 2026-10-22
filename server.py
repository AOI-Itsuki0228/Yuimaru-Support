"""
ゆんたくん 会話サーバー(複数台対応)

  StackChan --WAV + X-Device-Id--> /talk --> Whisper(文字起こし)
                                         --> Ollama(返事の文章)
                                         --> Kokoro(音声合成) --WAV--> StackChan

・台(StackChan)ごとに、性格と会話履歴を分けて持つ
・台ごとの性格は devices.toml で割り当てる
・性格の中身は personas/ フォルダのファイルで定義する
設定は config.py、使い方は README.md を参照。
"""
import io
import re
import threading
import time
from contextlib import asynccontextmanager
from datetime import datetime

import numpy as np
import ollama
import soundfile as sf
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.concurrency import run_in_threadpool
from faster_whisper import WhisperModel
from kokoro import KPipeline

import config
from devices import UNKNOWN_ID, DeviceStore, normalize_id
from personas import Persona, PersonaStore

# ============================================================
#  起動時の準備
# ============================================================
config.RECORD_DIR.mkdir(exist_ok=True)

whisper = WhisperModel(config.WHISPER_MODEL,
                       device=config.WHISPER_DEVICE,
                       compute_type=config.WHISPER_COMPUTE)
tts = KPipeline(lang_code="j")        # "j" = 日本語

store = PersonaStore(config.PERSONA_DIR, config.DEFAULT_VOICE, config.DEFAULT_SPEED)
devices = DeviceStore(config.DEVICES_FILE, config.DEFAULT_PERSONA)

# モデルは1つを全台で共有するので、処理は1件ずつ順番に行う
# (会話履歴・性格の変更も、同じロックの中で行う)
lock = threading.Lock()


# ============================================================
#  テキストの補助関数
# ============================================================
def is_noise(text: str) -> bool:
    """短すぎる、または Whisper の幻聴なら True"""
    t = re.sub(r"[。、！？!?\s\u3000.,]", "", text)
    return len(t) < 2 or t in config.IGNORE_TEXTS


def clean_for_tts(text: str) -> str:
    """読み上げに不要な記号や絵文字を取り除く"""
    text = re.sub(r"[*#`_~>]+", "", text)                              # Markdown記号
    text = re.sub(r"[\U0001F000-\U0001FAFF\u2600-\u27BF]", "", text)   # 絵文字
    return re.sub(r"\s+", " ", text).strip()


def trim_to_sentence(text: str) -> str:
    """num_predict で途中で切れたとき、最後の句点などまでに揃える"""
    idx = max(text.rfind(c) for c in "。！？!?")
    return text[: idx + 1] if idx > 0 else text


# ============================================================
#  会話(1台ぶんの、性格と履歴)
# ============================================================
class Conversation:
    def __init__(self, persona: Persona):
        self.persona = persona
        self.history: list[dict] = []
        self.reset()

    def reset(self) -> None:
        self.history = [{"role": "system",
                         "content": store.system_prompt(self.persona)}]

    def set_persona(self, persona: Persona) -> None:
        """性格を変える(履歴はリセットされる)"""
        self.persona = persona
        self.reset()

    def reply_to(self, user_text: str) -> str:
        options = dict(config.LLM_OPTIONS)
        if self.persona.temperature is not None:
            options["temperature"] = self.persona.temperature

        self.history.append({"role": "user", "content": user_text})
        try:
            res = ollama.chat(model=config.LLM_MODEL, messages=self.history,
                              options=options, keep_alive=config.LLM_KEEP_ALIVE)
        except Exception:
            self.history.pop()        # 失敗した発言を履歴に残さない
            raise

        reply = trim_to_sentence(res["message"]["content"].strip())
        self.history.append({"role": "assistant", "content": reply})

        # 古い往復から削る(先頭の system は残す)
        while len(self.history) > 1 + config.MAX_HISTORY_TURNS * 2:
            del self.history[1:3]
        return reply


# ============================================================
#  台ごとのセッション(台のID -> 会話)
# ============================================================
class Session:
    def __init__(self, device_id: str, label: str, conversation: Conversation):
        self.device_id = device_id
        self.label = label
        self.conversation = conversation
        self.last_seen = time.time()


class Sessions:
    """つながってきた台ごとに、Session を作って覚えておく"""

    def __init__(self):
        self._sessions: dict[str, Session] = {}

    def _persona_for(self, device_id: str) -> Persona:
        persona_id = devices.persona_for(device_id)
        persona = store.get(persona_id)
        if persona is None:
            persona = store.get(config.DEFAULT_PERSONA) or store.first()
            print(f"warning: 性格 '{persona_id}' がありません({device_id})。"
                  f"'{persona.id}' を使います")
        return persona

    def get(self, device_id: str) -> Session:
        session = self._sessions.get(device_id)
        if session is None:
            cfg = devices.get(device_id)
            persona = self._persona_for(device_id)
            session = Session(device_id, cfg.label if cfg else "", Conversation(persona))
            self._sessions[device_id] = session
            if cfg:
                print(f"device: {device_id} ({cfg.label}) -> {persona.id}")
            else:
                print(f"new device: {device_id} (未登録 -> {persona.id})  "
                      f"devices.toml に追加すると、性格を割り当てられます")
        session.last_seen = time.time()
        return session

    def clear(self) -> None:
        self._sessions.clear()

    def all(self) -> list[Session]:
        return list(self._sessions.values())


sessions = Sessions()


# ============================================================
#  3つの処理: 文字起こし → 返事 → 音声合成
# ============================================================
def transcribe(wav_bytes: bytes) -> str:
    segments, _ = whisper.transcribe(
        io.BytesIO(wav_bytes),
        language="ja",
        beam_size=config.BEAM_SIZE,
        vad_filter=True,
        vad_parameters=config.VAD_PARAMS,
        condition_on_previous_text=False,
        initial_prompt=config.WHISPER_INITIAL_PROMPT,
    )
    return "".join(s.text for s in segments).strip()


def synthesize(text: str, persona: Persona) -> bytes:
    chunks = []
    for _, _, audio in tts(text, voice=persona.voice, speed=persona.speed):
        if audio is None:
            continue
        a = audio.detach().cpu().numpy() if hasattr(audio, "detach") else np.asarray(audio)
        chunks.append(a.astype(np.float32).reshape(-1))
    if not chunks:
        return b""

    buf = io.BytesIO()
    sf.write(buf, np.concatenate(chunks), config.KOKORO_RATE,
             format="WAV", subtype="PCM_16")
    return buf.getvalue()


# ============================================================
#  録音ファイルの保存
# ============================================================
def save_recording(name: str, data: bytes) -> None:
    (config.RECORD_DIR / name).write_bytes(data)


def cleanup_recordings() -> None:
    """新しいものから KEEP_FILES 個だけ残して削除する"""
    files = sorted(config.RECORD_DIR.glob("*.wav"),
                   key=lambda p: p.stat().st_mtime, reverse=True)
    for f in files[config.KEEP_FILES:]:
        try:
            f.unlink()
        except OSError as e:
            print("delete failed:", f, e)


# ============================================================
#  1回の会話
# ============================================================
def process(wav_in: bytes, device_id: str) -> bytes | None:
    """録音WAV -> 返事WAV。無視するとき(雑音など)は None"""
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    base = f"{stamp}_{device_id}"                 # 台のIDを入れて、同時刻でも別ファイルに
    save_recording(f"{base}_in.wav", wav_in)      # まず保存(以降で失敗しても残る)

    queued = time.time()
    with lock:
        waited = time.time() - queued
        session = sessions.get(device_id)
        persona = session.conversation.persona
        tag = f"[{session.label or device_id}|{persona.id}]"
        if waited >= 1.0:
            print(f"{tag} 順番待ち {waited:.1f}s")

        t0 = time.time()
        text = transcribe(wav_in)
        t1 = time.time()
        print(f"{tag} User : {text!r}   [Whisper {t1 - t0:.1f}s]")
        if is_noise(text):
            print(f"{tag} ignored (noise / too short)")
            return None

        reply = session.conversation.reply_to(text)
        t2 = time.time()
        print(f"{tag} Reply: {reply}   [LLM {t2 - t1:.1f}s]")

        wav_out = synthesize(clean_for_tts(reply), persona)
        t3 = time.time()
        print(f"{tag} [Kokoro {t3 - t2:.1f}s / total {t3 - t0:.1f}s]")

    if not wav_out:
        return None
    save_recording(f"{base}_out.wav", wav_out)
    cleanup_recordings()
    return wav_out


# ============================================================
#  起動時のウォームアップ(最初の1回が遅くなるのを防ぐ)
# ============================================================
def warmup() -> None:
    t = time.time()
    persona = store.get(devices.default_persona) or store.first()
    try:
        list(whisper.transcribe(np.zeros(16000, dtype=np.float32), language="ja")[0])
    except Exception as e:
        print("whisper warmup failed:", e)
    try:
        ollama.chat(model=config.LLM_MODEL,
                    messages=[{"role": "user", "content": "こんにちは"}],
                    options={"num_predict": 5}, keep_alive=config.LLM_KEEP_ALIVE)
    except Exception as e:
        print("LLM warmup failed:", e)
    try:
        synthesize("こんにちは", persona)
    except Exception as e:
        print("TTS warmup failed:", e)
    print(f"warmup done [{time.time() - t:.1f}s]")


@asynccontextmanager
async def lifespan(app: FastAPI):
    warmup()
    yield


app = FastAPI(title="ゆんたくん会話サーバー", lifespan=lifespan)


# ============================================================
#  API: 会話
# ============================================================
@app.post("/talk")
async def talk(request: Request):
    """StackChan から録音WAVを受け取り、返事のWAVを返す(無視するときは 204)

    ヘッダー X-Device-Id で、どの台からかを見分ける(無いときは "unknown")。
    """
    device_id = normalize_id(request.headers.get("x-device-id", "")) or UNKNOWN_ID
    wav_in = await request.body()
    wav_out = await run_in_threadpool(process, wav_in, device_id)   # サーバーを止めない
    if not wav_out:
        return Response(status_code=204)
    return Response(content=wav_out, media_type="audio/wav")


# ============================================================
#  API: 台と性格の管理
#    ブラウザで http://localhost:8000/docs を開くと、ボタンで操作できる
# ============================================================
@app.get("/personas")
def list_personas():
    """選べる性格の一覧"""
    return {"default_persona": devices.default_persona,
            "personas": [{"id": p.id, "name": p.name, "description": p.description,
                          "voice": p.voice, "speed": p.speed} for p in store.all()]}


@app.get("/devices")
def list_devices():
    """登録済みの台と、これまでにつながった台(いまの性格・最後に話した時刻)"""
    rows: dict[str, dict] = {}
    for d in devices.all():
        rows[d.id] = {"id": d.id, "label": d.label, "assigned_persona": d.persona,
                      "current_persona": None, "last_seen": None}
    for s in sessions.all():
        row = rows.setdefault(s.device_id, {"id": s.device_id, "label": s.label,
                                            "assigned_persona": None,
                                            "current_persona": None, "last_seen": None})
        row["current_persona"] = s.conversation.persona.id
        row["last_seen"] = datetime.fromtimestamp(s.last_seen).strftime("%H:%M:%S")
    return {"default_persona": devices.default_persona, "devices": list(rows.values())}


@app.post("/devices/{device_id}/persona/{persona_id}")
def switch_device_persona(device_id: str, persona_id: str):
    """その台の性格を一時的に切り替える(履歴はリセット)。

    devices.toml は書き換えない。reload や再起動で、割り当てどおりに戻る。
    """
    dev = normalize_id(device_id) or UNKNOWN_ID
    persona = store.get(persona_id)
    if persona is None:
        ids = [p.id for p in store.all()]
        raise HTTPException(404, f"その性格はありません: {persona_id}(選べるもの: {ids})")
    with lock:
        sessions.get(dev).conversation.set_persona(persona)
    print(f"[{dev}] persona -> {persona.id} (一時的)")
    return {"device": dev, "persona": persona.id}


@app.post("/devices/{device_id}/reset")
def reset_device(device_id: str):
    """その台の会話履歴だけをリセットする"""
    dev = normalize_id(device_id) or UNKNOWN_ID
    with lock:
        sessions.get(dev).conversation.reset()
    return {"device": dev, "history": "reset"}


@app.post("/personas/reload")
def reload_all():
    """personas/ と devices.toml を読み直す(再起動せずに、編集を反映)

    全台の会話履歴と、一時的な性格の切り替えはリセットされる。
    """
    with lock:
        try:
            warnings = store.load()
        except ValueError as e:
            raise HTTPException(400, str(e))
        warnings += devices.load()
        sessions.clear()
    for w in warnings:
        print("warning:", w)
    return {"personas": [p.id for p in store.all()],
            "devices": [d.id for d in devices.all()],
            "warnings": warnings}
