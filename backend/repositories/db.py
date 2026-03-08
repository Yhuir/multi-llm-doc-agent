"""Backward-compatible import path for SQLiteDB.

TODO: remove this shim after all imports migrate to `backend.db.sqlite`.
"""

from backend.db.sqlite import SQLiteDB

__all__ = ["SQLiteDB"]
