"""Central orchestrator for task lifecycle and TOC workflow."""

from __future__ import annotations

import copy
import json
import uuid
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path
from typing import Any

from backend.models.enums import ChatRole, EventStatus, NodeStatus, TaskStatus
from backend.models.schemas import (
    ChatMessage,
    EventLog,
    NodeState,
    RequirementConstraints,
    RequirementDocument,
    RequirementItem,
    RequirementProject,
    RequirementScope,
    RequirementSubsystem,
    SourceIndexItem,
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
    ) -> None:
        self.task_repository = task_repository
        self.toc_repository = toc_repository
        self.node_repository = node_repository
        self.event_repository = event_repository
        self.chat_repository = chat_repository
        self.node_runner = node_runner
        self.artifacts_root = artifacts_root

    def run_parse_and_generate_toc(self, task_id: str) -> TOCVersion:
        task = self._require_task(task_id)
        if not task.upload_file_path:
            raise ValueError("Upload .docx file first.")

        requirement = self._parse_requirement_docx(
            Path(task.upload_file_path),
            fallback_title=task.title,
        )
        requirement_path = self._task_path(task_id, "parsed", "requirement.json")
        self._write_json(requirement_path, requirement.model_dump(mode="json"))
        self._log(
            task_id,
            stage="PARSE",
            message="Generated requirement.json",
            output_artifact_path=str(requirement_path),
        )

        self._transition_task(task_id, TaskStatus.PARSED, current_stage="PARSED")

        latest = self.toc_repository.get_latest_version(task_id)
        version_no = 1 if latest is None else latest.version_no + 1
        toc_doc = self._build_initial_toc(requirement=requirement, version_no=version_no)

        toc_path = self._task_path(task_id, "toc", f"toc_v{version_no}.json")
        self._write_json(toc_path, toc_doc.model_dump(mode="json"))

        diff_summary: dict[str, Any] | None = None
        based_on_version_no: int | None = None
        if latest is not None:
            old_doc = self._load_toc(Path(latest.file_path))
            diff_summary = self._diff_toc(old_doc.tree, toc_doc.tree)
            based_on_version_no = latest.version_no

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
        )
        return toc_version

    def review_toc(self, task_id: str, feedback: str) -> TOCVersion:
        task = self._require_task(task_id)
        if task.status != TaskStatus.TOC_REVIEW:
            raise ValueError("TOC can only be reviewed during TOC_REVIEW stage.")

        latest = self.toc_repository.get_latest_version(task_id)
        if latest is None:
            raise ValueError("No TOC version exists yet.")

        self.chat_repository.create(
            ChatMessage(
                message_id=f"msg_{uuid.uuid4().hex[:12]}",
                task_id=task_id,
                role=ChatRole.USER,
                content=feedback,
                related_toc_version=latest.version_no,
            )
        )

        old_doc = self._load_toc(Path(latest.file_path))
        new_doc = self._apply_feedback(old_doc, feedback)
        new_version_no = latest.version_no + 1
        new_doc.version = new_version_no
        new_doc.based_on_version = latest.version_no
        new_doc.generated_at = utc_now_iso()

        self._renumber_generation_children(new_doc)
        toc_path = self._task_path(task_id, "toc", f"toc_v{new_version_no}.json")
        self._write_json(toc_path, new_doc.model_dump(mode="json"))

        diff_summary = self._diff_toc(old_doc.tree, new_doc.tree)
        toc_version = TOCVersion(
            toc_version_id=f"tocv_{uuid.uuid4().hex[:12]}",
            task_id=task_id,
            version_no=new_version_no,
            file_path=str(toc_path),
            based_on_version_no=latest.version_no,
            is_confirmed=False,
            diff_summary_json=diff_summary,
            created_by="user",
        )
        self.toc_repository.create_version(toc_version)
        self.toc_repository.replace_snapshots(task_id, new_version_no, new_doc.tree)

        summary = f"Created toc_v{new_version_no} from feedback."
        self.chat_repository.create(
            ChatMessage(
                message_id=f"msg_{uuid.uuid4().hex[:12]}",
                task_id=task_id,
                role=ChatRole.ASSISTANT,
                content=summary,
                related_toc_version=new_version_no,
            )
        )

        self._log(task_id, stage="TOC_REVIEW", message=summary, output_artifact_path=str(toc_path))
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
        )
        return len(nodes)

    def start_generation(self, task_id: str) -> None:
        task = self._require_task(task_id)
        if task.status != TaskStatus.GENERATING:
            raise ValueError("Task must be in GENERATING state.")

        self._log(task_id, stage="WORKER", message="Starting node runner.")
        self.node_runner.run_task(task_id)

    def _transition_task(
        self,
        task_id: str,
        new_status: TaskStatus,
        *,
        current_stage: str,
        latest_error: str | None = None,
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

    def _parse_requirement_docx(
        self,
        file_path: Path,
        *,
        fallback_title: str,
    ) -> RequirementDocument:
        if file_path.suffix.lower() != ".docx":
            raise ValueError("Only .docx is supported.")

        texts = self._extract_docx_text(file_path)
        title = texts[0] if texts else fallback_title
        source_index: dict[str, SourceIndexItem] = {}

        for idx, text in enumerate(texts[:30], start=1):
            key = f"p1#L{idx}"
            source_index[key] = SourceIndexItem(
                page=1,
                paragraph_id=f"para_{idx}",
                text=text,
            )

        standards = [
            line for line in texts if "GB" in line.upper() or "ISO" in line.upper()
        ]
        acceptance = [line for line in texts if "验收" in line]

        subsystem_seed = texts[1:4] if len(texts) > 1 else []
        subsystems = []
        if subsystem_seed:
            for idx, seed in enumerate(subsystem_seed, start=1):
                ref = f"p1#L{idx + 1}"
                subsystems.append(
                    RequirementSubsystem(
                        name=f"子系统{idx}",
                        description=seed,
                        requirements=[
                            RequirementItem(
                                type="text",
                                key="概要",
                                value=seed,
                                source_ref=ref,
                            )
                        ],
                        interfaces=[],
                    )
                )
        else:
            subsystems.append(
                RequirementSubsystem(
                    name="子系统1",
                    description="基础实施范围",
                    requirements=[],
                    interfaces=[],
                )
            )

        return RequirementDocument(
            project=RequirementProject(
                name=title,
                customer="",
                location="",
                duration_days=None,
                milestones=[],
            ),
            scope=RequirementScope(
                overview=texts[0] if texts else "",
                subsystems=subsystems,
            ),
            constraints=RequirementConstraints(
                standards=standards[:5],
                acceptance=acceptance[:5],
            ),
            source_index=source_index,
        )

    @staticmethod
    def _extract_docx_text(file_path: Path) -> list[str]:
        try:
            with zipfile.ZipFile(file_path) as archive:
                xml_bytes = archive.read("word/document.xml")
        except (zipfile.BadZipFile, KeyError) as exc:
            raise ValueError(f"Cannot parse docx file: {file_path}") from exc

        root = ET.fromstring(xml_bytes)
        ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
        lines: list[str] = []
        for paragraph in root.findall(".//w:p", ns):
            texts = [t.text for t in paragraph.findall(".//w:t", ns) if t.text]
            merged = "".join(texts).strip()
            if merged:
                lines.append(merged)
        return lines

    def _build_initial_toc(self, *, requirement: RequirementDocument, version_no: int) -> TOCDocument:
        root_uid = "uid_root_001"
        level2_uid = "uid_l2_001"
        children: list[TOCNode] = []

        for idx, subsystem in enumerate(requirement.scope.subsystems, start=1):
            children.append(
                TOCNode(
                    node_uid=f"uid_l3_{idx:03d}",
                    node_id=f"1.1.{idx}",
                    level=3,
                    title=subsystem.name,
                    is_generation_unit=True,
                    source_refs=[],
                    constraints={
                        "min_words": 1800,
                        "recommended_words": [1800, 2200],
                        "images": [2, 3],
                    },
                    children=[],
                )
            )

        tree = [
            TOCNode(
                node_uid=root_uid,
                node_id="1",
                level=1,
                title="工程实施方案",
                is_generation_unit=False,
                source_refs=[],
                constraints=None,
                children=[
                    TOCNode(
                        node_uid=level2_uid,
                        node_id="1.1",
                        level=2,
                        title=requirement.project.name,
                        is_generation_unit=False,
                        source_refs=[],
                        constraints=None,
                        children=children,
                    )
                ],
            )
        ]
        return TOCDocument(version=version_no, based_on_version=None, tree=tree)

    def _apply_feedback(self, toc_doc: TOCDocument, feedback: str) -> TOCDocument:
        updated = copy.deepcopy(toc_doc)
        normalized = feedback.lower().strip()

        level2 = updated.tree[0].children[0] if updated.tree and updated.tree[0].children else None
        if level2 is None:
            return updated

        generation_nodes = [node for node in level2.children if node.level == 3]
        if not generation_nodes:
            return updated

        if "新增" in feedback or "增加" in feedback or "add" in normalized:
            next_index = len(generation_nodes) + 1
            level2.children.append(
                TOCNode(
                    node_uid=f"uid_l3_{uuid.uuid4().hex[:8]}",
                    node_id=f"1.1.{next_index}",
                    level=3,
                    title=f"新增节点{next_index}",
                    is_generation_unit=True,
                    source_refs=[],
                    constraints={
                        "min_words": 1800,
                        "recommended_words": [1800, 2200],
                        "images": [2, 3],
                    },
                    children=[],
                )
            )
        elif ("删除" in feedback or "remove" in normalized) and len(generation_nodes) > 1:
            level2.children = level2.children[:-1]
        else:
            first = generation_nodes[0]
            if "（修订）" not in first.title:
                first.title = f"{first.title}（修订）"

        return updated

    def _renumber_generation_children(self, toc_doc: TOCDocument) -> None:
        if not toc_doc.tree or not toc_doc.tree[0].children:
            return
        level2 = toc_doc.tree[0].children[0]
        for idx, node in enumerate(level2.children, start=1):
            if node.level == 3:
                node.node_id = f"1.1.{idx}"

    @staticmethod
    def _load_toc(path: Path) -> TOCDocument:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return TOCDocument.model_validate(payload)

    def _diff_toc(self, old_tree: list[TOCNode], new_tree: list[TOCNode]) -> dict[str, Any]:
        old_map = self._flatten_toc(old_tree)
        new_map = self._flatten_toc(new_tree)

        old_uids = set(old_map.keys())
        new_uids = set(new_map.keys())

        added_nodes = [new_map[uid] for uid in sorted(new_uids - old_uids)]
        removed_nodes = [old_map[uid] for uid in sorted(old_uids - new_uids)]

        renamed_nodes = []
        moved_nodes = []
        reordered_nodes = []

        for uid in sorted(old_uids & new_uids):
            old_node = old_map[uid]
            new_node = new_map[uid]
            if old_node["title"] != new_node["title"]:
                renamed_nodes.append(
                    {
                        "node_uid": uid,
                        "from": old_node["title"],
                        "to": new_node["title"],
                    }
                )
            if old_node["parent_node_uid"] != new_node["parent_node_uid"]:
                moved_nodes.append(
                    {
                        "node_uid": uid,
                        "from": old_node["parent_node_uid"],
                        "to": new_node["parent_node_uid"],
                    }
                )
            if old_node["node_id"] != new_node["node_id"]:
                reordered_nodes.append(
                    {
                        "node_uid": uid,
                        "from": old_node["node_id"],
                        "to": new_node["node_id"],
                    }
                )

        return {
            "added_nodes": added_nodes,
            "removed_nodes": removed_nodes,
            "renamed_nodes": renamed_nodes,
            "moved_nodes": moved_nodes,
            "reordered_nodes": reordered_nodes,
        }

    def _flatten_toc(self, tree: list[TOCNode]) -> dict[str, dict[str, Any]]:
        flat: dict[str, dict[str, Any]] = {}

        def walk(node: TOCNode, parent_uid: str | None) -> None:
            flat[node.node_uid] = {
                "node_uid": node.node_uid,
                "node_id": node.node_id,
                "title": node.title,
                "level": node.level,
                "parent_node_uid": parent_uid,
            }
            for child in node.children:
                walk(child, node.node_uid)

        for root in tree:
            walk(root, None)
        return flat

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
            )
        )
