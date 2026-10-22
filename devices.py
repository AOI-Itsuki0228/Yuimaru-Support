"""
台(StackChan)ごとの設定。devices.toml を読む。

  default_persona = "listener"        # 登録していない台に使う性格

  [devices.a1b2c3d4e5f6]              # 台のID(StackChan の MAC アドレス)
  label = "リビング"                   # ログに出す名前
  persona = "grandchild"              # personas/ のファイル名(.toml を除く)

台のIDは、StackChan の起動時に画面へ表示される(12桁・小文字・区切りなし)。
サーバーのログにも、未登録の台がつながったときに表示される。
"""
import re
import tomllib
from dataclasses import dataclass
from pathlib import Path

UNKNOWN_ID = "unknown"


def normalize_id(raw: str) -> str:
    """IDを、小文字の英数字と _ だけにそろえる(ファイル名にも安全に使える)"""
    return re.sub(r"[^0-9a-z_]", "", raw.lower())[:32]


@dataclass(frozen=True)
class DeviceConfig:
    id: str
    label: str
    persona: str


class DeviceStore:
    def __init__(self, path: Path, fallback_persona: str):
        self.path = Path(path)
        self.fallback_persona = fallback_persona
        self.default_persona = fallback_persona
        self._devices: dict[str, DeviceConfig] = {}
        self.load()

    def load(self) -> list[str]:
        """ファイルを読み直す。警告メッセージのリストを返す。

        ファイルが壊れているときは、いまの設定を変えない。
        """
        if not self.path.exists():
            self.default_persona = self.fallback_persona
            self._devices = {}
            return [f"{self.path.name} がありません(全台が既定の性格になります)"]

        try:
            with open(self.path, "rb") as f:
                data = tomllib.load(f)
        except (OSError, tomllib.TOMLDecodeError) as e:
            return [f"{self.path.name} を読めません(前の設定のままです): {e}"]

        warnings: list[str] = []
        devices: dict[str, DeviceConfig] = {}
        for raw_id, entry in (data.get("devices") or {}).items():
            dev_id = normalize_id(str(raw_id))
            if not dev_id:
                warnings.append(f"devices.{raw_id}: IDが使えません")
                continue
            if not isinstance(entry, dict) or not entry.get("persona"):
                warnings.append(f"devices.{raw_id}: persona がありません")
                continue
            devices[dev_id] = DeviceConfig(
                id=dev_id,
                label=str(entry.get("label", raw_id)),
                persona=str(entry["persona"]),
            )

        self.default_persona = str(data.get("default_persona", self.fallback_persona))
        self._devices = devices
        return warnings

    def get(self, device_id: str) -> DeviceConfig | None:
        return self._devices.get(device_id)

    def persona_for(self, device_id: str) -> str:
        cfg = self._devices.get(device_id)
        return cfg.persona if cfg else self.default_persona

    def all(self) -> list[DeviceConfig]:
        return list(self._devices.values())
