"""Task and node progress service skeleton."""

from __future__ import annotations

from backend.repositories.event_log_repository import EventLogRepository
from backend.repositories.node_state_repository import NodeStateRepository
from backend.repositories.task_repository import TaskRepository


class ProgressService:
    """Provides minimal progress snapshots for UI polling.

    TODO: align weights with architecture.md section 8 when full pipeline lands.
    """

    def __init__(
        self,
        *,
        task_repository: TaskRepository,
        node_repository: NodeStateRepository,
        event_repository: EventLogRepository,
    ) -> None:
        self.task_repository = task_repository
        self.node_repository = node_repository
        self.event_repository = event_repository

    def get_task_progress(self, task_id: str) -> dict:
        task = self.task_repository.get(task_id)
        if task is None:
            raise ValueError(f"Task not found: {task_id}")

        return {
            "task_id": task.task_id,
            "status": task.status.value,
            "total_progress": task.total_progress,
            "current_stage": task.current_stage,
            "current_node_uid": task.current_node_uid,
            "completed_nodes": task.completed_nodes,
            "total_nodes": task.total_nodes,
            "latest_error": task.latest_error,
        }

    def get_node_progress(self, task_id: str) -> list[dict]:
        nodes = self.node_repository.list_by_task(task_id)
        return [
            {
                "node_uid": node.node_uid,
                "node_id": node.node_id,
                "title": node.title,
                "status": node.status.value,
                "progress": node.progress,
                "current_stage": node.current_stage,
                "updated_at": node.updated_at,
            }
            for node in nodes
        ]

    def get_recent_logs(self, task_id: str, limit: int = 50) -> list[dict]:
        logs = self.event_repository.list_recent(task_id=task_id, limit=limit)
        return [log.model_dump(mode="json") for log in logs]
