"""Node execution state persistence."""

from __future__ import annotations

from typing import Any

from backend.models.enums import ManualActionStatus, NodeStatus
from backend.models.schemas import NodeState, utc_now_iso
from backend.repositories.db import SQLiteDB


class NodeStateRepository:
    _UNSET = object()
    _UPSERT_SQL = """
        INSERT INTO node_state (
            node_state_id, task_id, node_uid, node_id, title, level, status,
            progress, retry_text, retry_image, retry_fact, image_manual_required,
            manual_action_status, current_stage, last_error, input_snapshot_path,
            output_artifact_path, started_at, updated_at, last_heartbeat_at, finished_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(task_id, node_uid) DO UPDATE SET
            node_id = excluded.node_id,
            title = excluded.title,
            level = excluded.level,
            status = excluded.status,
            progress = excluded.progress,
            retry_text = excluded.retry_text,
            retry_image = excluded.retry_image,
            retry_fact = excluded.retry_fact,
            image_manual_required = excluded.image_manual_required,
            manual_action_status = excluded.manual_action_status,
            current_stage = excluded.current_stage,
            last_error = excluded.last_error,
            input_snapshot_path = excluded.input_snapshot_path,
            output_artifact_path = excluded.output_artifact_path,
            started_at = excluded.started_at,
            updated_at = excluded.updated_at,
            last_heartbeat_at = excluded.last_heartbeat_at,
            finished_at = excluded.finished_at
    """

    def __init__(self, db: SQLiteDB) -> None:
        self.db = db

    def upsert(self, node_state: NodeState) -> NodeState:
        with self.db.connection() as conn:
            conn.execute(self._UPSERT_SQL, self._to_upsert_params(node_state))
        return node_state

    def create_many(self, node_states: list[NodeState]) -> None:
        if not node_states:
            return
        with self.db.connection() as conn:
            conn.executemany(
                self._UPSERT_SQL,
                [self._to_upsert_params(node_state) for node_state in node_states],
            )

    def get(self, task_id: str, node_uid: str) -> NodeState | None:
        with self.db.connection() as conn:
            row = conn.execute(
                "SELECT * FROM node_state WHERE task_id = ? AND node_uid = ?",
                (task_id, node_uid),
            ).fetchone()
        return self._row_to_node_state(row) if row else None

    def list_by_task(self, task_id: str) -> list[NodeState]:
        with self.db.connection() as conn:
            rows = conn.execute(
                "SELECT * FROM node_state WHERE task_id = ? ORDER BY node_id ASC",
                (task_id,),
            ).fetchall()
        return [self._row_to_node_state(row) for row in rows]

    def list_unfinished(self, task_id: str) -> list[NodeState]:
        with self.db.connection() as conn:
            rows = conn.execute(
                """
                SELECT * FROM node_state
                WHERE task_id = ?
                  AND status NOT IN (?, ?)
                ORDER BY node_id ASC
                """,
                (task_id, NodeStatus.NODE_DONE.value, NodeStatus.NODE_FAILED.value),
            ).fetchall()
        return [self._row_to_node_state(row) for row in rows]

    def update_status(
        self,
        task_id: str,
        node_uid: str,
        *,
        status: NodeStatus,
        progress: float,
        current_stage: str,
        last_error: str | None | object = _UNSET,
        input_snapshot_path: str | None | object = _UNSET,
        output_artifact_path: str | None | object = _UNSET,
        manual_action_status: ManualActionStatus | None = None,
        image_manual_required: bool | None = None,
        started_at: str | None | object = _UNSET,
        finished_at: str | None | object = _UNSET,
    ) -> None:
        payload: dict[str, Any] = {
            "status": status.value,
            "progress": progress,
            "current_stage": current_stage,
            "updated_at": utc_now_iso(),
            "last_heartbeat_at": utc_now_iso(),
        }
        if last_error is not self._UNSET:
            payload["last_error"] = last_error
        if input_snapshot_path is not self._UNSET:
            payload["input_snapshot_path"] = input_snapshot_path
        if output_artifact_path is not self._UNSET:
            payload["output_artifact_path"] = output_artifact_path
        if started_at is not self._UNSET:
            payload["started_at"] = started_at
        if finished_at is not self._UNSET:
            payload["finished_at"] = finished_at
        if manual_action_status is not None:
            payload["manual_action_status"] = manual_action_status.value
        if image_manual_required is not None:
            payload["image_manual_required"] = int(image_manual_required)
        self._update(task_id, node_uid, payload)

    def touch_heartbeat(
        self,
        task_id: str,
        node_uid: str,
        *,
        current_stage: str | None = None,
    ) -> None:
        payload: dict[str, Any] = {
            "updated_at": utc_now_iso(),
            "last_heartbeat_at": utc_now_iso(),
        }
        if current_stage is not None:
            payload["current_stage"] = current_stage
        self._update(task_id, node_uid, payload)

    def increment_retry(
        self,
        task_id: str,
        node_uid: str,
        retry_field: str,
    ) -> None:
        if retry_field not in {"retry_text", "retry_image", "retry_fact"}:
            raise ValueError(f"Unsupported retry field: {retry_field}")
        with self.db.connection() as conn:
            conn.execute(
                f"""
                UPDATE node_state
                SET {retry_field} = {retry_field} + 1,
                    updated_at = ?,
                    last_heartbeat_at = ?
                WHERE task_id = ? AND node_uid = ?
                """,
                (utc_now_iso(), utc_now_iso(), task_id, node_uid),
            )

    def count_total(self, task_id: str) -> int:
        with self.db.connection() as conn:
            row = conn.execute(
                "SELECT COUNT(1) AS c FROM node_state WHERE task_id = ?",
                (task_id,),
            ).fetchone()
        return int(row["c"]) if row else 0

    def count_completed(self, task_id: str) -> int:
        with self.db.connection() as conn:
            row = conn.execute(
                """
                SELECT COUNT(1) AS c
                FROM node_state
                WHERE task_id = ? AND status = ?
                """,
                (task_id, NodeStatus.NODE_DONE.value),
            ).fetchone()
        return int(row["c"]) if row else 0

    def _update(self, task_id: str, node_uid: str, payload: dict[str, Any]) -> None:
        if not payload:
            return
        keys = list(payload.keys())
        assignments = ", ".join([f"{key} = ?" for key in keys])
        values = [payload[key] for key in keys]
        with self.db.connection() as conn:
            conn.execute(
                f"UPDATE node_state SET {assignments} WHERE task_id = ? AND node_uid = ?",
                (*values, task_id, node_uid),
            )

    @staticmethod
    def _row_to_node_state(row: Any) -> NodeState:
        return NodeState(
            node_state_id=row["node_state_id"],
            task_id=row["task_id"],
            node_uid=row["node_uid"],
            node_id=row["node_id"],
            title=row["title"],
            level=row["level"],
            status=NodeStatus(row["status"]),
            progress=row["progress"],
            retry_text=row["retry_text"],
            retry_image=row["retry_image"],
            retry_fact=row["retry_fact"],
            image_manual_required=bool(row["image_manual_required"]),
            manual_action_status=ManualActionStatus(
                row["manual_action_status"] or ManualActionStatus.NONE.value
            ),
            current_stage=row["current_stage"],
            last_error=row["last_error"],
            input_snapshot_path=row["input_snapshot_path"],
            output_artifact_path=row["output_artifact_path"],
            started_at=row["started_at"],
            updated_at=row["updated_at"],
            last_heartbeat_at=row["last_heartbeat_at"],
            finished_at=row["finished_at"],
        )

    @staticmethod
    def _to_upsert_params(node_state: NodeState) -> tuple[Any, ...]:
        return (
            node_state.node_state_id,
            node_state.task_id,
            node_state.node_uid,
            node_state.node_id,
            node_state.title,
            node_state.level,
            node_state.status.value,
            node_state.progress,
            node_state.retry_text,
            node_state.retry_image,
            node_state.retry_fact,
            int(node_state.image_manual_required),
            node_state.manual_action_status.value,
            node_state.current_stage,
            node_state.last_error,
            node_state.input_snapshot_path,
            node_state.output_artifact_path,
            node_state.started_at,
            node_state.updated_at,
            node_state.last_heartbeat_at,
            node_state.finished_at,
        )
