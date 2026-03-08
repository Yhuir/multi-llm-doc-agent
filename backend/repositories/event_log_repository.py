"""Event log persistence."""

from __future__ import annotations

import json
from typing import Any

from backend.models.enums import EventStatus
from backend.models.schemas import EventLog
from backend.repositories.db import SQLiteDB


class EventLogRepository:
    def __init__(self, db: SQLiteDB) -> None:
        self.db = db

    def create(self, event: EventLog) -> EventLog:
        with self.db.connection() as conn:
            conn.execute(
                """
                INSERT INTO event_log (
                    event_id, task_id, node_uid, stage, status, message,
                    retry_count, input_snapshot_path, output_artifact_path,
                    duration_ms, meta_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event.event_id,
                    event.task_id,
                    event.node_uid,
                    event.stage,
                    event.status.value,
                    event.message,
                    event.retry_count,
                    event.input_snapshot_path,
                    event.output_artifact_path,
                    event.duration_ms,
                    json.dumps(event.meta_json, ensure_ascii=False)
                    if event.meta_json is not None
                    else None,
                    event.created_at,
                ),
            )
        return event

    def list_recent(
        self,
        task_id: str,
        *,
        limit: int = 100,
        node_uid: str | None = None,
    ) -> list[EventLog]:
        if node_uid:
            query = """
                SELECT * FROM event_log
                WHERE task_id = ? AND node_uid = ?
                ORDER BY created_at DESC
                LIMIT ?
            """
            params = (task_id, node_uid, limit)
        else:
            query = """
                SELECT * FROM event_log
                WHERE task_id = ?
                ORDER BY created_at DESC
                LIMIT ?
            """
            params = (task_id, limit)

        with self.db.connection() as conn:
            rows = conn.execute(query, params).fetchall()
        return [self._row_to_event(row) for row in rows]

    @staticmethod
    def _row_to_event(row: Any) -> EventLog:
        return EventLog(
            event_id=row["event_id"],
            task_id=row["task_id"],
            node_uid=row["node_uid"],
            stage=row["stage"],
            status=EventStatus(row["status"]),
            message=row["message"],
            retry_count=row["retry_count"],
            input_snapshot_path=row["input_snapshot_path"],
            output_artifact_path=row["output_artifact_path"],
            duration_ms=row["duration_ms"],
            meta_json=json.loads(row["meta_json"]) if row["meta_json"] else None,
            created_at=row["created_at"],
        )
