"""Local system configuration persistence for frontend settings."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

DEFAULT_SYSTEM_CONFIG: dict[str, Any] = {
    "text_provider": "minimax",
    "image_provider": "minimax",
    "text_model_name": "MiniMax-M2.5",
    "image_model_name": "MiniMax-M2.5",
    "text_api_key": "",
    "image_api_key": "",
    "api_key": "",
}


class SystemConfigStore:
    def __init__(self, path: str | Path = "artifacts/system_config.json") -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def get(self) -> dict[str, Any]:
        if not self.path.exists():
            return dict(DEFAULT_SYSTEM_CONFIG)
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        merged = dict(DEFAULT_SYSTEM_CONFIG)
        merged.update(payload)
        legacy_api_key = str(merged.get("api_key") or "")
        if not merged.get("text_api_key"):
            merged["text_api_key"] = legacy_api_key
        if not merged.get("image_api_key"):
            merged["image_api_key"] = legacy_api_key
        return merged

    def update(self, updates: dict[str, Any]) -> dict[str, Any]:
        config = self.get()
        if "api_key" in updates:
            if "text_api_key" not in updates:
                updates["text_api_key"] = updates["api_key"]
            if "image_api_key" not in updates:
                updates["image_api_key"] = updates["api_key"]
        config.update(updates)
        if "text_api_key" in updates or "image_api_key" in updates:
            config.pop("api_key", None)
        self.path.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
        return config
