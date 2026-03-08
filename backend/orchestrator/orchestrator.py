"""Central orchestrator for task lifecycle and TOC workflow."""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any

from backend.agents import (
    RequirementParserAgent,
    TOCGeneratorAgent,
    TOCReviewChatAgent,
)
from backend.models.enums import ChatRole, EventStatus, NodeStatus, TaskStatus
from backend.models.schemas import (
    ChatMessage,
    EventLog,
    NodeState,
    ParseReport,
    RequirementDocument,
    TOCDocument,
    TOCNode,
    TOCVersion,
    utc_now_iso,
)
from backend.repositories.chat_message_repository import ChatMessageRepository
from backend.repositories.event_log_repository import EventLogRepository
from backend.repositories.node_state_repository import NodeStateRepository
from backend.repositories.task_repository import TaskRepository
from backend.repositories.toc_repository import TOCRepository
from backend.worker.node_runner import NodeRunner


class Orchestrator:
    """Coordinates phase-level transitions between UI requests and worker execution."""

    _ALLOWED_TASK_TRANSITIONS: dict[TaskStatus, set[TaskStatus]] = {
        TaskStatus.NEW: {TaskStatus.PARSED, TaskStatus.PAUSED, TaskStatus.FAILED},
        TaskStatus.PARSED: {TaskStatus.TOC_REVIEW, TaskStatus.PAUSED, TaskStatus.FAILED},
        TaskStatus.TOC_REVIEW: {TaskStatus.GENERATING, TaskStatus.PAUSED, TaskStatus.FAILED},
        TaskStatus.GENERATING: {TaskStatus.LAYOUTING, TaskStatus.PAUSED, TaskStatus.FAILED},
        TaskStatus.LAYOUTING: {TaskStatus.EXPORTING, TaskStatus.PAUSED, TaskStatus.FAILED},
        TaskStatus.EXPORTING: {TaskStatus.DONE, TaskStatus.PAUSED, TaskStatus.FAILED},
        TaskStatus.PAUSED: {TaskStatus.GENERATING, TaskStatus.TOC_REVIEW, TaskStatus.FAILED},
        TaskStatus.DONE: set(),
        TaskStatus.FAILED: set(),
    }

    def __init__(
        self,
        *,
        task_repository: TaskRepository,
        toc_repository: TOCRepository,
        node_repository: NodeStateRepository,
        event_repository: EventLogRepository,
        chat_repository: ChatMessageRepository,
        node_runner: NodeRunner,
        artifacts_root: Path,
        requirement_parser: RequirementParserAgent | None = None,
        toc_generator: TOCGeneratorAgent | None = None,
        toc_review_agent: TOCReviewChatAgent | None = None,
    ) -> None:
        self.task_repository = task_repository
        self.toc_repository = toc_repository
        self.node_repository = node_repository
        self.event_repository = event_repository
        self.chat_repository = chat_repository
        self.node_runner = node_runner
        self.artifacts_root = artifacts_root
        self.requirement_parser = requirement_parser or RequirementParserAgent()
        self.toc_generator = toc_generator or TOCGeneratorAgent()
        self.toc_review_agent = toc_review_agent or TOCReviewChatAgent()

    def run_parse_requirement(self, task_id: str) -> dict[str, Any]:
        task = self._require_task(task_id)
        if task.status != TaskStatus.NEW:
            raise ValueError("Requirement parse can only run when task status is NEW.")
        if not task.upload_file_path:
            raise ValueError("Upload .docx file first.")

        self._log(task_id, stage="PARSE", message="Requirement parse started.")
        requirement, parse_report_payload = self.requirement_parser.parse(
            task_id=task_id,
            upload_file_path=Path(task.upload_file_path),
            fallback_title=task.title,
        )
        parse_report = ParseReport.model_validate(parse_report_payload)

        requirement_path = self._task_path(task_id, "parsed", "requirement.json")
        parse_report_path = self._task_path(task_id, "parsed", "parse_report.json")
        self._write_json(requirement_path, requirement.model_dump(mode="json"))
        self._write_json(parse_report_path, parse_report.model_dump(mode="json"))

        self._transition_task(task_id, TaskStatus.PARSED, current_stage="PARSED")
        self.task_repository.update_progress(
            task_id,
            total_progress=0.1,
            current_stage="PARSED",
        )
        self._log(
            task_id,
            stage="PARSE",
            message="Generated requirement.json and parse_report.json",
            output_artifact_path=str(requirement_path),
        )
        self._log(
            task_id,
            stage="PARSE",
            message="Generated parse_report.json",
            output_artifact_path=str(parse_report_path),
        )
        return {
            "task_id": task_id,
            "requirement_path": str(requirement_path),
            "parse_report_path": str(parse_report_path),
            "parse_report": parse_report.model_dump(mode="json"),
        }

    def run_generate_toc(self, task_id: str) -> TOCVersion:
        task = self._require_task(task_id)
        if task.status == TaskStatus.NEW:
            self.run_parse_requirement(task_id)
            task = self._require_task(task_id)
        if task.status != TaskStatus.PARSED:
            raise ValueError("TOC generation requires task status PARSED.")

        requirement_path = self._task_path(task_id, "parsed", "requirement.json")
        if not requirement_path.exists():
            raise ValueError("requirement.json missing. Parse requirement first.")

        requirement = RequirementDocument.model_validate(
            json.loads(requirement_path.read_text(encoding="utf-8"))
        )
        latest = self.toc_repository.get_latest_version(task_id)
        version_no = 1 if latest is None else latest.version_no + 1

        toc_doc = self.toc_generator.generate(requirement=requirement, version_no=version_no)
        self._renumber_node_ids(toc_doc.tree)
        toc_doc.version = version_no
        toc_doc.generated_at = utc_now_iso()
        toc_doc.based_on_version = latest.version_no if latest else None

        toc_path = self._task_path(task_id, "toc", f"toc_v{version_no}.json")
        self._write_json(toc_path, toc_doc.model_dump(mode="json"))

        diff_summary: dict[str, Any] | None = None
        based_on_version_no: int | None = None
        if latest is not None:
            based_on_version_no = latest.version_no
            old_doc = self._load_toc(Path(latest.file_path))
            diff_summary = self._diff_toc(old_doc.tree, toc_doc.tree)

        toc_version = TOCVersion(
            toc_version_id=f"tocv_{uuid.uuid4().hex[:12]}",
            task_id=task_id,
            version_no=version_no,
            file_path=str(toc_path),
            based_on_version_no=based_on_version_no,
            is_confirmed=False,
            diff_summary_json=diff_summary,
            created_by="system",
        )
        self.toc_repository.create_version(toc_version)
        self.toc_repository.replace_snapshots(task_id, version_no, toc_doc.tree)

        self._transition_task(task_id, TaskStatus.TOC_REVIEW, current_stage="TOC_REVIEW")
        self.task_repository.update_progress(
            task_id,
            total_progress=0.2,
            current_stage="TOC_REVIEW",
        )
        self._log(
            task_id,
            stage="TOC_GENERATE",
            message=f"Generated toc_v{version_no}.json",
            output_artifact_path=str(toc_path),
            meta_json={"version_no": version_no},
        )
        return toc_version

    # Backward-compatible method name used by earlier rounds.
    def run_parse_and_generate_toc(self, task_id: str) -> TOCVersion:
        return self.run_generate_toc(task_id)

    def review_toc(
        self,
        task_id: str,
        feedback: str,
        *,
        based_on_version_no: int | None = None,
    ) -> TOCVersion:
        task = self._require_task(task_id)
        if task.status != TaskStatus.TOC_REVIEW:
            raise ValueError("TOC can only be reviewed during TOC_REVIEW stage.")
        if task.confirmed_toc_version is not None:
            raise ValueError("TOC already confirmed for this task. Create a derived task to modify.")

        latest = self.toc_repository.get_latest_version(task_id)
        if latest is None:
            raise ValueError("No TOC version exists yet.")

        base_version_no = based_on_version_no or latest.version_no
        base_version = self.toc_repository.get_version(task_id, base_version_no)
        if base_version is None:
            raise ValueError(f"TOC version {base_version_no} does not exist.")

        self.chat_repository.create(
            ChatMessage(
                message_id=f"msg_{uuid.uuid4().hex[:12]}",
                task_id=task_id,
                role=ChatRole.USER,
                content=feedback,
                related_toc_version=base_version_no,
            )
        )

        old_doc = self._load_toc(Path(base_version.file_path))
        new_doc = self.toc_review_agent.review(toc_doc=old_doc, feedback=feedback)

        new_version_no = latest.version_no + 1
        new_doc.version = new_version_no
        new_doc.based_on_version = base_version_no
        new_doc.generated_at = utc_now_iso()
        self._renumber_node_ids(new_doc.tree)

        toc_path = self._task_path(task_id, "toc", f"toc_v{new_version_no}.json")
        self._write_json(toc_path, new_doc.model_dump(mode="json"))

        diff_summary = self._diff_toc(old_doc.tree, new_doc.tree)
        toc_version = TOCVersion(
            toc_version_id=f"tocv_{uuid.uuid4().hex[:12]}",
            task_id=task_id,
            version_no=new_version_no,
            file_path=str(toc_path),
            based_on_version_no=base_version_no,
            is_confirmed=False,
            diff_summary_json=diff_summary,
            created_by="user",
        )
        self.toc_repository.create_version(toc_version)
        self.toc_repository.replace_snapshots(task_id, new_version_no, new_doc.tree)

        summary = f"Created toc_v{new_version_no} based on toc_v{base_version_no}."
        self.chat_repository.create(
            ChatMessage(
                message_id=f"msg_{uuid.uuid4().hex[:12]}",
                task_id=task_id,
                role=ChatRole.ASSISTANT,
                content=summary,
                related_toc_version=new_version_no,
            )
        )

        self._log(
            task_id,
            stage="TOC_REVIEW",
            message=summary,
            output_artifact_path=str(toc_path),
            meta_json={
                "based_on_version_no": base_version_no,
                "new_version_no": new_version_no,
                "diff_summary": diff_summary,
            },
        )
        return toc_version

    def confirm_toc(self, task_id: str, version_no: int) -> int:
        task = self._require_task(task_id)
        if task.status != TaskStatus.TOC_REVIEW:
            raise ValueError("TOC can only be confirmed during TOC_REVIEW stage.")

        toc_version = self.toc_repository.get_version(task_id, version_no)
        if toc_version is None:
            raise ValueError(f"TOC version {version_no} does not exist.")

        toc_doc = self._load_toc(Path(toc_version.file_path))
        confirmed_path = self._task_path(task_id, "toc", "toc_confirmed.json")
        self._write_json(confirmed_path, toc_doc.model_dump(mode="json"))

        snapshots = self.toc_repository.list_generation_units(task_id, version_no)
        if not snapshots:
            raise ValueError("No generation units in TOC; cannot start generation.")

        nodes = [
            NodeState(
                node_state_id=f"node_{uuid.uuid4().hex[:12]}",
                task_id=task_id,
                node_uid=item.node_uid,
                node_id=item.node_id,
                title=item.title,
                level=item.level,
                status=NodeStatus.PENDING,
                progress=0.0,
                current_stage=NodeStatus.PENDING.value,
                started_at=None,
            )
            for item in snapshots
        ]
        self.node_repository.create_many(nodes)

        min_generation_level = min(item.level for item in snapshots)
        self.toc_repository.mark_confirmed(task_id, version_no)
        self.task_repository.set_confirmed_toc(
            task_id,
            version_no=version_no,
            min_generation_level=min_generation_level,
        )
        self.task_repository.update_progress(
            task_id,
            total_nodes=len(nodes),
            completed_nodes=0,
            total_progress=0.2,
            current_stage="GENERATING",
        )

        self._transition_task(task_id, TaskStatus.GENERATING, current_stage="GENERATING")
        self._log(
            task_id,
            stage="TOC_CONFIRM",
            message=f"Confirmed toc_v{version_no} and created {len(nodes)} node states.",
            output_artifact_path=str(confirmed_path),
            meta_json={"confirmed_version_no": version_no, "seeded_nodes": len(nodes)},
        )
        return len(nodes)

    def start_generation(self, task_id: str) -> None:
        task = self._require_task(task_id)
        if task.status != TaskStatus.GENERATING:
            raise ValueError("Task must be in GENERATING state.")
        if task.confirmed_toc_version is None:
            raise ValueError("TOC must be confirmed before generation.")

        self.task_repository.touch_heartbeat(task_id, stage="GENERATING", node_uid=None)
        self._log(
            task_id,
            stage="WORKER_QUEUE",
            message="Generation queued. Worker will pick this task.",
        )

    def run_worker_task(self, task_id: str) -> None:
        """Run one worker cycle for a task and advance task-level state machine."""
        task = self._require_task(task_id)
        if task.status not in {TaskStatus.GENERATING, TaskStatus.LAYOUTING, TaskStatus.EXPORTING}:
            raise ValueError(f"Task {task_id} is not runnable by worker: {task.status.value}")

        if task.status == TaskStatus.GENERATING:
            summary = self.node_runner.run_generation(task_id)
            if summary.total_nodes == 0:
                self._transition_task(
                    task_id,
                    TaskStatus.FAILED,
                    current_stage="GENERATING",
                    latest_error="No node_state found for generation.",
                    finished_at=utc_now_iso(),
                )
                self._log(
                    task_id,
                    stage="GENERATING",
                    message="Task failed: no node_state found.",
                    meta_json={"summary": summary.__dict__},
                )
                return

            if summary.failed_nodes > 0:
                self._transition_task(
                    task_id,
                    TaskStatus.FAILED,
                    current_stage="GENERATING",
                    latest_error=f"{summary.failed_nodes} node(s) failed.",
                    finished_at=utc_now_iso(),
                )
                self._log(
                    task_id,
                    stage="GENERATING",
                    message="Task failed due to node failures.",
                    meta_json={"summary": summary.__dict__},
                )
                return

            self._transition_task(task_id, TaskStatus.LAYOUTING, current_stage="LAYOUTING")
            self.task_repository.update_progress(
                task_id,
                total_progress=0.85,
                current_stage="LAYOUTING",
                current_node_uid=None,
            )
            self._log(
                task_id,
                stage="GENERATING",
                message="All nodes finished. Entering LAYOUTING stage.",
                meta_json={"summary": summary.__dict__},
            )
            task = self._require_task(task_id)

        if task.status == TaskStatus.LAYOUTING:
            layout_path = self.node_runner.run_layout(task_id)
            self._transition_task(task_id, TaskStatus.EXPORTING, current_stage="EXPORTING")
            self.task_repository.update_progress(
                task_id,
                total_progress=0.93,
                current_stage="EXPORTING",
                current_node_uid=None,
            )
            self._log(
                task_id,
                stage="LAYOUTING",
                message="Layout stage completed.",
                output_artifact_path=str(layout_path),
            )
            task = self._require_task(task_id)

        if task.status == TaskStatus.EXPORTING:
            output_path = self.node_runner.run_export(task_id)
            completed_nodes = self.node_repository.count_completed(task_id)
            self.task_repository.update_progress(
                task_id,
                completed_nodes=completed_nodes,
                total_progress=1.0,
                current_stage="DONE",
                current_node_uid=None,
            )
            self._transition_task(
                task_id,
                TaskStatus.DONE,
                current_stage="DONE",
                finished_at=utc_now_iso(),
            )
            self._log(
                task_id,
                stage="DONE",
                message="Task completed by worker.",
                output_artifact_path=str(output_path),
            )

    def _transition_task(
        self,
        task_id: str,
        new_status: TaskStatus,
        *,
        current_stage: str,
        latest_error: str | None = None,
        finished_at: str | None = None,
    ) -> None:
        task = self._require_task(task_id)
        allowed = self._ALLOWED_TASK_TRANSITIONS.get(task.status, set())
        if new_status == task.status:
            return
        if new_status not in allowed:
            raise ValueError(
                f"Illegal task transition: {task.status.value} -> {new_status.value}"
            )
        self.task_repository.update_status(
            task_id,
            new_status,
            current_stage=current_stage,
            latest_error=latest_error,
            finished_at=finished_at,
        )

    def _require_task(self, task_id: str):
        task = self.task_repository.get(task_id)
        if task is None:
            raise ValueError(f"Task not found: {task_id}")
        return task

    def _task_path(self, task_id: str, *parts: str) -> Path:
        path = self.artifacts_root / task_id
        for part in parts:
            path = path / part
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    def _diff_toc(self, old_tree: list[TOCNode], new_tree: list[TOCNode]) -> dict[str, Any]:
        """Minimal tree diff for V1 UI: add/remove/reorder/title change.

        TODO: keep move info for future use; rename is represented as title_change.
        """

        old_map = self._flatten_toc(old_tree)
        new_map = self._flatten_toc(new_tree)

        old_uids = set(old_map)
        new_uids = set(new_map)

        added = [new_map[uid] for uid in sorted(new_uids - old_uids)]
        removed = [old_map[uid] for uid in sorted(old_uids - new_uids)]

        title_change: list[dict[str, Any]] = []
        reorder: list[dict[str, Any]] = []
        move: list[dict[str, Any]] = []

        for uid in sorted(old_uids & new_uids):
            old_item = old_map[uid]
            new_item = new_map[uid]

            if old_item["title"] != new_item["title"]:
                title_change.append(
                    {
                        "node_uid": uid,
                        "from": old_item["title"],
                        "to": new_item["title"],
                        "node_id": new_item["node_id"],
                    }
                )

            if old_item["parent_node_uid"] != new_item["parent_node_uid"]:
                move.append(
                    {
                        "node_uid": uid,
                        "from_parent": old_item["parent_node_uid"],
                        "to_parent": new_item["parent_node_uid"],
                        "node_id": new_item["node_id"],
                    }
                )

            if (
                old_item["parent_node_uid"] == new_item["parent_node_uid"]
                and old_item["order_in_parent"] != new_item["order_in_parent"]
            ):
                reorder.append(
                    {
                        "node_uid": uid,
                        "node_id": new_item["node_id"],
                        "from": old_item["order_in_parent"],
                        "to": new_item["order_in_parent"],
                    }
                )

        return {
            "summary": {
                "add_count": len(added),
                "remove_count": len(removed),
                "title_change_count": len(title_change),
                "reorder_count": len(reorder),
                "move_count": len(move),
            },
            "add": added,
            "remove": removed,
            "title_change": title_change,
            "reorder": reorder,
            "move": move,
        }

    def _flatten_toc(self, tree: list[TOCNode]) -> dict[str, dict[str, Any]]:
        flat: dict[str, dict[str, Any]] = {}

        def walk(node: TOCNode, parent_uid: str | None, order_in_parent: int) -> None:
            flat[node.node_uid] = {
                "node_uid": node.node_uid,
                "node_id": node.node_id,
                "title": node.title,
                "level": node.level,
                "parent_node_uid": parent_uid,
                "order_in_parent": order_in_parent,
            }
            for idx, child in enumerate(node.children, start=1):
                walk(child, node.node_uid, idx)

        for root_idx, root in enumerate(tree, start=1):
            walk(root, None, root_idx)
        return flat

    def _renumber_node_ids(self, tree: list[TOCNode]) -> None:
        for root_idx, root in enumerate(tree, start=1):
            root.node_id = str(root_idx)
            self._renumber_children(root)

    def _renumber_children(self, parent: TOCNode) -> None:
        for idx, child in enumerate(parent.children, start=1):
            child.node_id = f"{parent.node_id}.{idx}"
            self._renumber_children(child)

    @staticmethod
    def _load_toc(path: Path) -> TOCDocument:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return TOCDocument.model_validate(payload)

    @staticmethod
    def _write_json(path: Path, payload: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def _log(
        self,
        task_id: str,
        *,
        stage: str,
        message: str,
        node_uid: str | None = None,
        output_artifact_path: str | None = None,
        meta_json: dict[str, Any] | None = None,
    ) -> None:
        self.event_repository.create(
            EventLog(
                event_id=f"evt_{uuid.uuid4().hex[:12]}",
                task_id=task_id,
                node_uid=node_uid,
                stage=stage,
                status=EventStatus.INFO,
                message=message,
                output_artifact_path=output_artifact_path,
                meta_json=meta_json,
            )
        )
