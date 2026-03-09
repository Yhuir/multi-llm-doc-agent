"""Runtime bootstrap helpers for storage initialization."""

from __future__ import annotations

from pathlib import Path

from backend.config.settings import AppSettings
from backend.db import SQLiteDB


def initialize_runtime(settings: AppSettings) -> SQLiteDB:
    """Initialize artifacts root and SQLite schema.

    This is intentionally minimal for Phase A/B bootstrap.
    """
    artifacts_root = Path(settings.artifacts_root)
    artifacts_root.mkdir(parents=True, exist_ok=True)

    db = SQLiteDB(settings.db_path)
    db.initialize()
    return db
