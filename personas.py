"""
性格(ペルソナ)の読み込み。

personas/ フォルダの次のファイルを読む。
  common.txt     … どの性格でも共通のルール(出力形式・安全面など)
  <id>.toml      … 性格ごとの設定(ファイル名が性格のID)

システムプロンプト = common.txt + 性格ごとの prompt
"""
import tomllib
from dataclasses import dataclass
from pathlib import Path

COMMON_FILE = "common.txt"


@dataclass(frozen=True)
class Persona:
    id: str                       # ファイル名(拡張子なし)
    name: str                     # 表示名
    description: str              # 一言の説明
    prompt: str                   # 性格ごとのプロンプト
    voice: str                    # Kokoro の声
    speed: float                  # 話す速さ
    temperature: float | None     # LLM の temperature(None なら config.py の値)


class PersonaStore:
    def __init__(self, directory: Path, default_voice: str, default_speed: float):
        self.directory = Path(directory)
        self.default_voice = default_voice
        self.default_speed = default_speed
        self.common = ""
        self._personas: dict[str, Persona] = {}
        self.load()

    # ---------- 読み込み ----------
    def load(self) -> list[str]:
        """ファイルを読み直す。読めなかったファイルの警告メッセージを返す。

        有効な性格が1つもないときは例外にして、いまの状態は変えない。
        """
        warnings: list[str] = []

        common_path = self.directory / COMMON_FILE
        common = common_path.read_text(encoding="utf-8").strip() if common_path.exists() else ""
        if not common:
            warnings.append(f"{COMMON_FILE} が無い、または空です(共通ルールなしで動きます)")

        personas: dict[str, Persona] = {}
        for path in sorted(self.directory.glob("*.toml")):
            try:
                personas[path.stem] = self._parse(path)
            except (OSError, tomllib.TOMLDecodeError, ValueError, TypeError) as e:
                warnings.append(f"{path.name}: {e}")

        if not personas:
            raise ValueError(f"{self.directory} に有効な性格ファイル(*.toml)がありません")

        self.common, self._personas = common, personas
        return warnings

    def _parse(self, path: Path) -> Persona:
        with open(path, "rb") as f:
            data = tomllib.load(f)

        name = str(data.get("name", "")).strip()
        prompt = str(data.get("prompt", "")).strip()
        if not name or not prompt:
            raise ValueError("name と prompt は必須です")

        temperature = data.get("temperature")
        return Persona(
            id=path.stem,
            name=name,
            description=str(data.get("description", "")).strip(),
            prompt=prompt,
            voice=str(data.get("voice", self.default_voice)),
            speed=float(data.get("speed", self.default_speed)),
            temperature=float(temperature) if temperature is not None else None,
        )

    # ---------- 取得 ----------
    def get(self, persona_id: str) -> Persona | None:
        return self._personas.get(persona_id)

    def first(self) -> Persona:
        return self._personas[sorted(self._personas)[0]]

    def all(self) -> list[Persona]:
        return [self._personas[k] for k in sorted(self._personas)]

    def system_prompt(self, persona: Persona) -> str:
        parts = [self.common, "【この会話でのキャラクター】\n" + persona.prompt]
        return "\n\n".join(p for p in parts if p)
