"""Manual intervention records persistence."""

from __future__ import annotations

import json
from typing import Any

from backend.models.enums import ActionType
from backend.models.schemas import ManualAction
from backend.repositories.db import SQLiteDB


class ManualActionRepository:
    def __init__(self, db: SQLiteDB) -> None:
        self.db = db

    def create(self, action: ManualAction) -> ManualAction:
        with self.db.connection() as conn:
            conn.execute(
                """
                INSERT INTO manual_action (
                    action_id, task_id, node_uid, action_type, action_payload_json,
                    operator_name, result_status, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    action.action_id,
                    action.task_id,
                    action.node_uid,
                    action.action_type.value,
                    json.dumps(action.action_payload_json, ensure_ascii=False)
                    if action.action_payload_json is not None
                    else None,
                    action.operator_name,
                    action.result_status,
                    action.created_at,
                ),
            )
        return action

    def list_by_task(self, task_id: str) -> list[ManualAction]:
        with self.db.connection() as conn:
            rows = conn.execute(
                "SELECT * FROM manual_action WHERE task_id = ? ORDER BY created_at DESC",
                (task_id,),
            ).fetchall()
        return [self._row_to_action(row) for row in rows]

    @staticmethod
    def _row_to_action(row: Any) -> ManualAction:
        return ManualAction(
            action_id=row["action_id"],
            task_id=row["task_id"],
            node_uid=row["node_uid"],
            action_type=ActionType(row["action_type"]),
            action_payload_json=json.loads(row["action_payload_json"])
            if row["action_payload_json"]
            else None,
            operator_name=row["operator_name"],
            result_status=row["result_status"],
            created_at=row["created_at"],
        )
