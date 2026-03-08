"""Task metadata persistence."""

from __future__ import annotations

from typing import Any

from backend.models.enums import TaskStatus
from backend.models.schemas import Task, utc_now_iso
from backend.repositories.db import SQLiteDB


class TaskRepository:
    def __init__(self, db: SQLiteDB) -> None:
        self.db = db

    def create(self, task: Task) -> Task:
        with self.db.connection() as conn:
            conn.execute(
                """
                INSERT INTO task (
                    task_id, parent_task_id, title, status, upload_file_name,
                    upload_file_path, confirmed_toc_version, min_generation_level,
                    text_provider, image_provider, total_nodes, completed_nodes,
                    total_progress, current_stage, current_node_uid, latest_error,
                    created_at, updated_at, last_heartbeat_at, finished_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    task.task_id,
                    task.parent_task_id,
                    task.title,
                    task.status.value,
                    task.upload_file_name,
                    task.upload_file_path,
                    task.confirmed_toc_version,
                    task.min_generation_level,
                    task.text_provider,
                    task.image_provider,
                    task.total_nodes,
                    task.completed_nodes,
                    task.total_progress,
                    task.current_stage,
                    task.current_node_uid,
                    task.latest_error,
                    task.created_at,
                    task.updated_at,
                    task.last_heartbeat_at,
                    task.finished_at,
                ),
            )
        return task

    def get(self, task_id: str) -> Task | None:
        with self.db.connection() as conn:
            row = conn.execute("SELECT * FROM task WHERE task_id = ?", (task_id,)).fetchone()
        return self._row_to_task(row) if row else None

    def list_all(self) -> list[Task]:
        with self.db.connection() as conn:
            rows = conn.execute("SELECT * FROM task ORDER BY created_at DESC").fetchall()
        return [self._row_to_task(row) for row in rows]

    def list_resumable(self, limit: int = 20) -> list[Task]:
        resumable = (
            TaskStatus.NEW.value,
            TaskStatus.PARSED.value,
            TaskStatus.TOC_REVIEW.value,
            TaskStatus.GENERATING.value,
            TaskStatus.LAYOUTING.value,
            TaskStatus.EXPORTING.value,
            TaskStatus.PAUSED.value,
        )
        placeholders = ", ".join(["?"] * len(resumable))
        query = f"""
            SELECT * FROM task
            WHERE status IN ({placeholders})
            ORDER BY updated_at DESC
            LIMIT ?
        """
        with self.db.connection() as conn:
            rows = conn.execute(query, (*resumable, limit)).fetchall()
        return [self._row_to_task(row) for row in rows]

    def update_upload(self, task_id: str, file_name: str, file_path: str) -> None:
        self._update(
            task_id,
            {
                "upload_file_name": file_name,
                "upload_file_path": file_path,
                "updated_at": utc_now_iso(),
            },
        )

    def update_status(
        self,
        task_id: str,
        status: TaskStatus,
        *,
        current_stage: str | None = None,
        current_node_uid: str | None = None,
        latest_error: str | None = None,
        finished_at: str | None = None,
    ) -> None:
        payload: dict[str, Any] = {
            "status": status.value,
            "updated_at": utc_now_iso(),
            "current_stage": current_stage,
            "current_node_uid": current_node_uid,
            "latest_error": latest_error,
            "finished_at": finished_at,
        }
        self._update(task_id, payload)

    def update_progress(
        self,
        task_id: str,
        *,
        total_nodes: int | None = None,
        completed_nodes: int | None = None,
        total_progress: float | None = None,
        current_stage: str | None = None,
        current_node_uid: str | None = None,
    ) -> None:
        payload: dict[str, Any] = {"updated_at": utc_now_iso()}
        if total_nodes is not None:
            payload["total_nodes"] = total_nodes
        if completed_nodes is not None:
            payload["completed_nodes"] = completed_nodes
        if total_progress is not None:
            payload["total_progress"] = total_progress
        if current_stage is not None:
            payload["current_stage"] = current_stage
        if current_node_uid is not None:
            payload["current_node_uid"] = current_node_uid
        self._update(task_id, payload)

    def set_confirmed_toc(
        self,
        task_id: str,
        *,
        version_no: int,
        min_generation_level: int,
    ) -> None:
        self._update(
            task_id,
            {
                "confirmed_toc_version": version_no,
                "min_generation_level": min_generation_level,
                "updated_at": utc_now_iso(),
            },
        )

    def touch_heartbeat(
        self,
        task_id: str,
        *,
        stage: str | None = None,
        node_uid: str | None = None,
    ) -> None:
        payload: dict[str, Any] = {
            "last_heartbeat_at": utc_now_iso(),
            "updated_at": utc_now_iso(),
        }
        if stage is not None:
            payload["current_stage"] = stage
        if node_uid is not None:
            payload["current_node_uid"] = node_uid
        self._update(task_id, payload)

    def _update(self, task_id: str, payload: dict[str, Any]) -> None:
        if not payload:
            return
        keys = list(payload.keys())
        assignments = ", ".join([f"{key} = ?" for key in keys])
        values = [payload[key] for key in keys]
        with self.db.connection() as conn:
            conn.execute(
                f"UPDATE task SET {assignments} WHERE task_id = ?",
                (*values, task_id),
            )

    @staticmethod
    def _row_to_task(row: Any) -> Task:
        return Task(
            task_id=row["task_id"],
            parent_task_id=row["parent_task_id"],
            title=row["title"],
            status=TaskStatus(row["status"]),
            upload_file_name=row["upload_file_name"],
            upload_file_path=row["upload_file_path"],
            confirmed_toc_version=row["confirmed_toc_version"],
            min_generation_level=row["min_generation_level"],
            text_provider=row["text_provider"],
            image_provider=row["image_provider"],
            total_nodes=row["total_nodes"],
            completed_nodes=row["completed_nodes"],
            total_progress=row["total_progress"],
            current_stage=row["current_stage"],
            current_node_uid=row["current_node_uid"],
            latest_error=row["latest_error"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            last_heartbeat_at=row["last_heartbeat_at"],
            finished_at=row["finished_at"],
        )
