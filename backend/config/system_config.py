"""Local system configuration persistence for frontend settings."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

DEFAULT_SYSTEM_CONFIG: dict[str, Any] = {
    "text_provider": "mock-text",
    "image_provider": "mock-image",
    "text_model_name": "mock-text-v1",
    "image_model_name": "mock-image-v1",
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
        return merged

    def update(self, updates: dict[str, Any]) -> dict[str, Any]:
        config = self.get()
        config.update(updates)
        self.path.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
        return config
