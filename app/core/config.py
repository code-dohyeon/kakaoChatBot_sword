import json
from pathlib import Path
from typing import Dict, Any

CONFIG_FILE_PATH = Path(__file__).resolve().parent.parent.parent / "game_config.json"

class GameConfig:
    def __init__(self, config_data: Dict[str, Any]):
        self.raw = config_data
        self.rules = config_data.get("game_rules", {})
        self.enhance_weights = config_data.get("enhance_base_weights", {})
        self.sword_types = config_data.get("sword_types", {})
        self.relics = {r["id"]: r for r in config_data.get("relics", [])}
        self.shop_items = {item["id"]: item for item in config_data.get("shop_items", [])}
        self.sword_ranks = config_data.get("sword_ranks", [])
        self.round_events = {e["id"]: e for e in config_data.get("round_events", [])}
        self.achievements = {a["id"]: a for a in config_data.get("achievements", [])}

    @classmethod
    def load(cls, path: Path = CONFIG_FILE_PATH) -> "GameConfig":
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return cls(data)

config = GameConfig.load()
