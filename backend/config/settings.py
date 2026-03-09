"""Runtime settings loader for backend services and worker."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class AppSettings:
    db_path: str = "app.db"
    artifacts_root: str = "artifacts"
    template_path: str = "templates/standard_template.docx"
    system_config_path: str = "artifacts/system_config.json"
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    worker_poll_interval_sec: float = 2.0


def _read_dotenv(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def load_settings(env_file: str | Path = ".env") -> AppSettings:
    env_values = _read_dotenv(Path(env_file))

    def get(key: str, default: str) -> str:
        return os.getenv(key, env_values.get(key, default))

    return AppSettings(
        db_path=get("APP_DB_PATH", "app.db"),
        artifacts_root=get("APP_ARTIFACTS_ROOT", "artifacts"),
        template_path=get("APP_TEMPLATE_PATH", "templates/standard_template.docx"),
        system_config_path=get("APP_SYSTEM_CONFIG_PATH", "artifacts/system_config.json"),
        api_host=get("APP_API_HOST", "0.0.0.0"),
        api_port=int(get("APP_API_PORT", "8000")),
        worker_poll_interval_sec=float(get("APP_WORKER_POLL_INTERVAL_SEC", "2.0")),
    )
