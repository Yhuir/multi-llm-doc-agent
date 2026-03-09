"""Application service for task lifecycle operations."""

from __future__ import annotations

import json
import uuid
from pathlib import Path

from backend.config.runtime import initialize_runtime
from backend.config.settings import AppSettings
from backend.config.system_config import SystemConfigStore
from backend.models.enums import EventStatus, TaskStatus
from backend.models.schemas import EventLog, Task, utc_now_iso
from backend.orchestrator.orchestrator import Orchestrator
from backend.repositories.chat_message_repository import ChatMessageRepository
from backend.repositories.event_log_repository import EventLogRepository
from backend.repositories.manual_action_repository import ManualActionRepository
from backend.repositories.node_state_repository import NodeStateRepository
from backend.repositories.task_repository import TaskRepository
from backend.repositories.toc_repository import TOCRepository
from backend.worker.node_runner import NodeRunner


class TaskService:
    """Coordinates repositories and orchestrator for API/UI callers."""

    def __init__(
        self,
        *,
        settings: AppSettings | None = None,
        db_path: str | Path = "app.db",
        artifacts_root: str | Path = "artifacts",
        template_path: str | Path = "templates/standard_template.docx",
        system_config_path: str | Path = "artifacts/system_config.json",
    ) -> None:
        self.settings = settings or AppSettings(
            db_path=str(db_path),
            artifacts_root=str(artifacts_root),
            template_path=str(template_path),
            system_config_path=str(system_config_path),
        )

        self.artifacts_root = Path(self.settings.artifacts_root)
        self.artifacts_root.mkdir(parents=True, exist_ok=True)
        self.system_config_store = SystemConfigStore(self.settings.system_config_path)

        self.db = initialize_runtime(self.settings)

        self.task_repository = TaskRepository(self.db)
        self.toc_repository = TOCRepository(self.db)
        self.node_repository = NodeStateRepository(self.db)
        self.event_repository = EventLogRepository(self.db)
        self.chat_repository = ChatMessageRepository(self.db)
        self.manual_action_repository = ManualActionRepository(self.db)

        self.node_runner = NodeRunner(
            node_repository=self.node_repository,
            task_repository=self.task_repository,
            event_repository=self.event_repository,
            artifacts_root=self.artifacts_root,
            template_path=Path(self.settings.template_path),
            system_config_getter=self.system_config_store.get,
        )

        self.orchestrator = Orchestrator(
            task_repository=self.task_repository,
            toc_repository=self.toc_repository,
            node_repository=self.node_repository,
            event_repository=self.event_repository,
            chat_repository=self.chat_repository,
            node_runner=self.node_runner,
            artifacts_root=self.artifacts_root,
        )

    def create_task(
        self,
        title: str,
        *,
        parent_task_id: str | None = None,
        text_provider: str | None = None,
        image_provider: str | None = None,
    ) -> Task:
        config = self.get_system_config()
        resolved_text_provider = text_provider or config["text_provider"]
        resolved_image_provider = image_provider or config["image_provider"]
        now = utc_now_iso()
        task = Task(
            task_id=f"task_{uuid.uuid4().hex[:10]}",
            parent_task_id=parent_task_id,
            title=title.strip() or "Untitled Task",
            status=TaskStatus.NEW,
            text_provider=resolved_text_provider,
            image_provider=resolved_image_provider,
            created_at=now,
            updated_at=now,
        )
        self._ensure_artifact_dirs(task.task_id)
        self.task_repository.create(task)
        self._log(task.task_id, stage="TASK", message="Task created.")
        return task

    def list_tasks(self) -> list[Task]:
        return self.task_repository.list_all()

    def list_resumable_tasks(self) -> list[Task]:
        return self.task_repository.list_resumable()

    def get_task(self, task_id: str) -> Task | None:
        return self.task_repository.get(task_id)

    def save_upload(self, task_id: str, file_name: str, file_content: bytes) -> Path:
        if not file_name.lower().endswith(".docx"):
            raise ValueError("Only .docx is supported.")

        task = self.task_repository.get(task_id)
        if task is None:
            raise ValueError(f"Task not found: {task_id}")

        safe_name = Path(file_name).name
        upload_path = self.artifacts_root / task_id / "input" / safe_name
        upload_path.parent.mkdir(parents=True, exist_ok=True)
        upload_path.write_bytes(file_content)

        self.task_repository.update_upload(task_id, safe_name, str(upload_path))
        self._log(
            task_id,
            stage="UPLOAD",
            message=f"Uploaded {safe_name}",
            output_artifact_path=str(upload_path),
        )
        return upload_path

    def parse_requirement(self, task_id: str) -> dict:
        return self.orchestrator.run_parse_requirement(task_id)

    def generate_toc(self, task_id: str):
        return self.orchestrator.run_generate_toc(task_id)

    def review_toc(
        self,
        task_id: str,
        feedback: str,
        *,
        based_on_version_no: int | None = None,
    ):
        if not feedback.strip():
            raise ValueError("Feedback cannot be empty.")
        review_config = self.get_system_config()
        return self.orchestrator.review_toc(
            task_id,
            feedback,
            based_on_version_no=based_on_version_no,
            review_config=review_config,
        )

    def import_toc_outline(
        self,
        task_id: str,
        outline_text: str,
        *,
        based_on_version_no: int | None = None,
    ):
        if not outline_text.strip():
            raise ValueError("Outline text cannot be empty.")
        return self.orchestrator.import_toc_outline(
            task_id,
            outline_text,
            based_on_version_no=based_on_version_no,
        )

    def confirm_toc(self, task_id: str, version_no: int) -> int:
        return self.orchestrator.confirm_toc(task_id, version_no)

    def confirm_and_start_generation(self, task_id: str, version_no: int) -> dict:
        result = self.orchestrator.confirm_and_start_generation(task_id, version_no)
        task = result["task"]
        return {
            "seeded_nodes": result["seeded_nodes"],
            "already_confirmed": result["already_confirmed"],
            "task": task.model_dump(mode="json"),
        }

    def start_generation(self, task_id: str) -> None:
        self.orchestrator.start_generation(task_id)

    def list_toc_versions(self, task_id: str):
        return self.toc_repository.list_versions(task_id)

    def get_toc_document(self, task_id: str, version_no: int) -> dict:
        version = self.toc_repository.get_version(task_id, version_no)
        if version is None:
            raise ValueError(f"TOC version {version_no} not found.")
        return json.loads(Path(version.file_path).read_text(encoding="utf-8"))

    def get_confirmed_toc(self, task_id: str) -> dict | None:
        path = self.artifacts_root / task_id / "toc" / "toc_confirmed.json"
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    def get_requirement_document(self, task_id: str) -> dict | None:
        path = self.artifacts_root / task_id / "parsed" / "requirement.json"
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    def get_parse_report(self, task_id: str) -> dict | None:
        path = self.artifacts_root / task_id / "parsed" / "parse_report.json"
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    def get_chat_messages(self, task_id: str):
        return self.chat_repository.list_by_task(task_id)

    def get_event_logs(self, task_id: str, limit: int = 100):
        return self.event_repository.list_recent(task_id, limit=limit)

    def get_node_states(self, task_id: str):
        return self.node_repository.list_by_task(task_id)

    def get_output_path(self, task_id: str) -> Path | None:
        output_path = self.artifacts_root / task_id / "final" / "output.docx"
        return output_path if output_path.exists() else None

    def get_system_config(self) -> dict:
        return self.system_config_store.get()

    def update_system_config(self, updates: dict) -> dict:
        return self.system_config_store.update(updates)

    def _ensure_artifact_dirs(self, task_id: str) -> None:
        for relative in ["input", "parsed", "toc", "nodes", "final"]:
            (self.artifacts_root / task_id / relative).mkdir(parents=True, exist_ok=True)

    def _log(
        self,
        task_id: str,
        *,
        stage: str,
        message: str,
        output_artifact_path: str | None = None,
    ) -> None:
        self.event_repository.create(
            EventLog(
                event_id=f"evt_{uuid.uuid4().hex[:12]}",
                task_id=task_id,
                stage=stage,
                status=EventStatus.INFO,
                message=message,
                output_artifact_path=output_artifact_path,
            )
        )
