"""
ゆんたくん会話サーバーの設定。
調整したい値は、基本的にこのファイルだけを書き換える。
"""
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent

# ============================================================
#  実行環境
# ============================================================
USE_GPU = False          # GPUのPCに移したら True にする

# ============================================================
#  音声認識(Whisper)
# ============================================================
if USE_GPU:
    WHISPER_MODEL = "kotoba-tech/kotoba-whisper-v2.0-faster"
    WHISPER_DEVICE, WHISPER_COMPUTE = "cuda", "float16"
    BEAM_SIZE = 5
else:
    WHISPER_MODEL = "small"
    WHISPER_DEVICE, WHISPER_COMPUTE = "cpu", "int8"
    BEAM_SIZE = 1        # 精度を上げたいなら 3 に(少し遅くなる)

WHISPER_INITIAL_PROMPT = "こんにちは、ゆんたくん。"

# 声かどうかの判定(Silero VAD)。雑音に反応するなら threshold を上げる
VAD_PARAMS = {
    "threshold": 0.5,               # 上げると厳しくなる(0.6〜0.7で雑音に強く)
    "min_speech_duration_ms": 250,  # これより短い音は声と見なさない
    "min_silence_duration_ms": 500, # 文の区切りと見なす無音の長さ
    "speech_pad_ms": 200,           # 声の前後に残す余白(語頭・語尾が欠けるなら増やす)
}

# Whisperが無音や雑音で出しやすい幻聴(これに一致したら返事をしない)
IGNORE_TEXTS = {
    "ご視聴ありがとうございました", "ご清聴ありがとうございました",
    "ありがとうございました", "おやすみなさい", "こんにちはゆんたくん",
}

# ============================================================
#  会話(Ollama)
# ============================================================
LLM_MODEL = "qwen2.5:3b"          # 例: "gemma3:4b-it-qat"
LLM_OPTIONS = {"num_predict": 150, "temperature": 0.7}   # 返事の長さの上限など
LLM_KEEP_ALIVE = "30m"            # モデルをメモリに常駐させる時間
MAX_HISTORY_TURNS = 4             # 覚えておく往復の数

# ============================================================
#  音声合成(Kokoro)
# ============================================================
KOKORO_RATE = 24000
DEFAULT_VOICE = "jf_alpha"        # 性格ファイルに voice が無いときに使う声
DEFAULT_SPEED = 1.0

# ============================================================
#  性格(ペルソナ)
# ============================================================
PERSONA_DIR = BASE_DIR / "personas"
DEFAULT_PERSONA = "listener"      # devices.toml が無い・壊れているときの既定の性格
DEVICES_FILE = BASE_DIR / "devices.toml"   # 台(StackChan)ごとの性格の割り当て

# ============================================================
#  録音ファイルの保存
# ============================================================
RECORD_DIR = BASE_DIR / "recordings"
KEEP_FILES = 30                   # 残すWAVの数(in/outで2ファイル/回。台数が多いほど増やす)
