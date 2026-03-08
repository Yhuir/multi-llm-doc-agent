"""SQLite connection and schema bootstrap."""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


class SQLiteDB:
    """Minimal SQLite helper used by repository layer."""

    def __init__(self, db_path: str | Path = "app.db") -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, check_same_thread=False, timeout=30.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA busy_timeout = 30000")
        return conn

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        conn = self._connect()
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def initialize(self) -> None:
        statements = [
            """
            CREATE TABLE IF NOT EXISTS task (
                task_id TEXT PRIMARY KEY,
                parent_task_id TEXT NULL,
                title TEXT NOT NULL,
                status TEXT NOT NULL,
                upload_file_name TEXT NULL,
                upload_file_path TEXT NULL,
                confirmed_toc_version INTEGER NULL,
                min_generation_level INTEGER NULL,
                text_provider TEXT NOT NULL,
                image_provider TEXT NOT NULL,
                total_nodes INTEGER DEFAULT 0,
                completed_nodes INTEGER DEFAULT 0,
                total_progress REAL DEFAULT 0,
                current_stage TEXT NULL,
                current_node_uid TEXT NULL,
                latest_error TEXT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                last_heartbeat_at TEXT NULL,
                finished_at TEXT NULL
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS toc_version (
                toc_version_id TEXT PRIMARY KEY,
                task_id TEXT NOT NULL,
                version_no INTEGER NOT NULL,
                file_path TEXT NOT NULL,
                based_on_version_no INTEGER NULL,
                is_confirmed INTEGER NOT NULL,
                diff_summary_json TEXT NULL,
                created_by TEXT NOT NULL,
                created_at TEXT NOT NULL,
                UNIQUE(task_id, version_no)
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS toc_node_snapshot (
                snapshot_id TEXT PRIMARY KEY,
                task_id TEXT NOT NULL,
                version_no INTEGER NOT NULL,
                node_uid TEXT NOT NULL,
                node_id TEXT NOT NULL,
                parent_node_uid TEXT NULL,
                level INTEGER NOT NULL,
                title TEXT NOT NULL,
                order_index INTEGER NOT NULL,
                is_generation_unit INTEGER NOT NULL,
                source_refs_json TEXT NULL,
                constraints_json TEXT NULL,
                created_at TEXT NOT NULL
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS node_state (
                node_state_id TEXT PRIMARY KEY,
                task_id TEXT NOT NULL,
                node_uid TEXT NOT NULL,
                node_id TEXT NOT NULL,
                title TEXT NOT NULL,
                level INTEGER NOT NULL,
                status TEXT NOT NULL,
                progress REAL NOT NULL,
                retry_text INTEGER DEFAULT 0,
                retry_image INTEGER DEFAULT 0,
                retry_fact INTEGER DEFAULT 0,
                image_manual_required INTEGER DEFAULT 0,
                manual_action_status TEXT NULL,
                current_stage TEXT NULL,
                last_error TEXT NULL,
                input_snapshot_path TEXT NULL,
                output_artifact_path TEXT NULL,
                started_at TEXT NULL,
                updated_at TEXT NOT NULL,
                last_heartbeat_at TEXT NULL,
                finished_at TEXT NULL,
                UNIQUE(task_id, node_uid)
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS event_log (
                event_id TEXT PRIMARY KEY,
                task_id TEXT NOT NULL,
                node_uid TEXT NULL,
                stage TEXT NOT NULL,
                status TEXT NOT NULL,
                message TEXT NOT NULL,
                retry_count INTEGER DEFAULT 0,
                input_snapshot_path TEXT NULL,
                output_artifact_path TEXT NULL,
                duration_ms INTEGER NULL,
                meta_json TEXT NULL,
                created_at TEXT NOT NULL
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS chat_message (
                message_id TEXT PRIMARY KEY,
                task_id TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                related_toc_version INTEGER NULL,
                created_at TEXT NOT NULL
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS task_config (
                task_config_id TEXT PRIMARY KEY,
                task_id TEXT NOT NULL,
                text_provider TEXT NOT NULL,
                image_provider TEXT NOT NULL,
                text_model_name TEXT NOT NULL,
                image_model_name TEXT NOT NULL,
                strict_mode INTEGER DEFAULT 0,
                image_retry_limit INTEGER DEFAULT 3,
                length_expand_limit INTEGER DEFAULT 2,
                length_trim_threshold INTEGER DEFAULT 2200,
                grounded_ratio_threshold REAL DEFAULT 0.70,
                image_score_threshold REAL DEFAULT 0.75,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS manual_action (
                action_id TEXT PRIMARY KEY,
                task_id TEXT NOT NULL,
                node_uid TEXT NOT NULL,
                action_type TEXT NOT NULL,
                action_payload_json TEXT NULL,
                operator_name TEXT NULL,
                result_status TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """,
            "CREATE INDEX IF NOT EXISTS idx_task_status_updated ON task(status, updated_at)",
            "CREATE INDEX IF NOT EXISTS idx_node_state_task_status ON node_state(task_id, status)",
            "CREATE INDEX IF NOT EXISTS idx_event_task_created ON event_log(task_id, created_at)",
            "CREATE INDEX IF NOT EXISTS idx_event_task_node_created ON event_log(task_id, node_uid, created_at)",
            "CREATE INDEX IF NOT EXISTS idx_toc_snapshot_lookup ON toc_node_snapshot(task_id, version_no, node_uid)",
        ]

        with self.connection() as conn:
            for statement in statements:
                conn.execute(statement)
