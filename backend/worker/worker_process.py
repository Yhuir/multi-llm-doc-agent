"""Standalone worker loop for serial task execution and resume."""

from __future__ import annotations

import time
import uuid
from pathlib import Path

from backend.config import AppSettings, load_settings
from backend.models.enums import EventStatus, TaskStatus
from backend.models.schemas import EventLog, utc_now_iso
from backend.orchestrator.orchestrator import Orchestrator
from backend.repositories import (
    ChatMessageRepository,
    EventLogRepository,
    NodeStateRepository,
    SQLiteDB,
    TaskRepository,
    TOCRepository,
)
from backend.worker.node_runner import NodeRunner


class WorkerProcess:
    """Poll runnable tasks and execute one task at a time (V1 serial mode)."""

    def __init__(self, settings: AppSettings) -> None:
        self.settings = settings
        self.db = SQLiteDB(settings.db_path)
        self.db.initialize()

        self.task_repository = TaskRepository(self.db)
        self.toc_repository = TOCRepository(self.db)
        self.node_repository = NodeStateRepository(self.db)
        self.event_repository = EventLogRepository(self.db)
        self.chat_repository = ChatMessageRepository(self.db)

        self.node_runner = NodeRunner(
            node_repository=self.node_repository,
            task_repository=self.task_repository,
            event_repository=self.event_repository,
            artifacts_root=Path(settings.artifacts_root),
            template_path=Path(settings.template_path),
        )
        self.orchestrator = Orchestrator(
            task_repository=self.task_repository,
            toc_repository=self.toc_repository,
            node_repository=self.node_repository,
            event_repository=self.event_repository,
            chat_repository=self.chat_repository,
            node_runner=self.node_runner,
            artifacts_root=Path(settings.artifacts_root),
        )

    def run_once(self) -> int:
        tasks = self.task_repository.list_worker_runnable(limit=1)
        if not tasks:
            return 0

        task = tasks[0]
        self._log(task.task_id, "WORKER", f"Worker picked task at {task.status.value} stage.")
        self.task_repository.touch_heartbeat(task.task_id, stage=f"WORKER_{task.status.value}")

        try:
            self.orchestrator.run_worker_task(task.task_id)
        except Exception as exc:  # noqa: BLE001
            self.task_repository.update_status(
                task.task_id,
                TaskStatus.FAILED,
                current_stage="WORKER",
                latest_error=str(exc),
                finished_at=utc_now_iso(),
            )
            self._log(task.task_id, "WORKER", f"Worker failed task: {exc}")

        return 1

    def run_forever(self) -> None:
        while True:
            processed = self.run_once()
            if processed == 0:
                time.sleep(self.settings.worker_poll_interval_sec)

    def _log(self, task_id: str, stage: str, message: str) -> None:
        self.event_repository.create(
            EventLog(
                event_id=f"evt_{uuid.uuid4().hex[:12]}",
                task_id=task_id,
                stage=stage,
                status=EventStatus.INFO,
                message=message,
            )
        )


if __name__ == "__main__":
    WorkerProcess(load_settings()).run_forever()
