"""TOC-related application service skeleton."""

from __future__ import annotations

import json
from pathlib import Path

from backend.models.schemas import TOCVersion
from backend.repositories.task_repository import TaskRepository
from backend.repositories.toc_repository import TOCRepository


class TOCService:
    """Minimal TOC service wrapper over repositories.

    TODO: add rollback API and tree-level diff helpers for later rounds.
    """

    def __init__(
        self,
        *,
        toc_repository: TOCRepository,
        task_repository: TaskRepository,
        artifacts_root: str | Path = "artifacts",
    ) -> None:
        self.toc_repository = toc_repository
        self.task_repository = task_repository
        self.artifacts_root = Path(artifacts_root)

    def list_versions(self, task_id: str) -> list[TOCVersion]:
        return self.toc_repository.list_versions(task_id)

    def get_latest_version(self, task_id: str) -> TOCVersion | None:
        return self.toc_repository.get_latest_version(task_id)

    def get_version_document(self, task_id: str, version_no: int) -> dict:
        version = self.toc_repository.get_version(task_id, version_no)
        if version is None:
            raise ValueError(f"TOC version {version_no} not found for task {task_id}")
        return json.loads(Path(version.file_path).read_text(encoding="utf-8"))

    def get_confirmed_toc_document(self, task_id: str) -> dict | None:
        path = self.artifacts_root / task_id / "toc" / "toc_confirmed.json"
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))
