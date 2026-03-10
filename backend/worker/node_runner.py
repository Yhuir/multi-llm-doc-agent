"""Backend worker execution engine with node state machine, checkpoint and resume."""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from backend.agents import (
    ConsistencyCheckAgent,
    EntityExtractorAgent,
    FactGroundingAgent,
    ImageGenerationAgent,
    ImagePromptAgent,
    ImageRelevanceAgent,
    LayoutAgent,
    LengthControlAgent,
    SectionWriterAgent,
    TableBuilderAgent,
    WordExportAgent,
)
from backend.models.enums import (
    AgentResult,
    EventStatus,
    ImageStatus,
    ManualActionStatus,
    NodeStatus,
)
from backend.models.schemas import (
    EntityExtraction,
    EventLog,
    FactCheck,
    ImagePrompts,
    ImageRelevanceReport,
    ImageScoreItem,
    ImagesArtifact,
    Metrics,
    NodeState,
    NodeText,
    RequirementDocument,
    TOCDocument,
    utc_now_iso,
)
from backend.repositories.event_log_repository import EventLogRepository
from backend.repositories.node_state_repository import NodeStateRepository
from backend.repositories.task_repository import TaskRepository


@dataclass
class GenerationSummary:
    total_nodes: int
    completed_nodes: int
    failed_nodes: int
    manual_nodes: int


@dataclass(frozen=True)
class StageConfig:
    key: str
    start_status: NodeStatus
    done_status: NodeStatus
    progress_start: float
    progress_done: float
    retry_field: str | None
    retry_limit: int
    manual_on_fail: bool


class NodeRunner:
    """Runs generation-unit nodes sequentially for one task with resume support."""

    _UNSET = object()

    _STAGE_ORDER = [
        "text",
        "fact",
        "image_generate",
        "length",
        "consistency",
        "layout",
        "finalize",
    ]

    _IN_PROGRESS_TO_STAGE: dict[NodeStatus, str] = {
        NodeStatus.TEXT_GENERATING: "text",
        NodeStatus.FACT_CHECKING: "fact",
        NodeStatus.IMAGE_GENERATING: "image_generate",
        NodeStatus.IMAGE_VERIFYING: "length",
        NodeStatus.LENGTH_CHECKING: "length",
        NodeStatus.CONSISTENCY_CHECKING: "consistency",
    }

    _STABLE_TO_NEXT_STAGE: dict[NodeStatus, str] = {
        NodeStatus.PENDING: "text",
        NodeStatus.TEXT_DONE: "fact",
        NodeStatus.FACT_PASSED: "image_generate",
        NodeStatus.IMAGE_DONE: "length",
        NodeStatus.IMAGE_VERIFIED: "length",
        NodeStatus.LENGTH_PASSED: "consistency",
        NodeStatus.READY_FOR_LAYOUT: "layout",
        NodeStatus.LAYOUTED: "finalize",
    }

    _ALLOWED_NODE_TRANSITIONS: dict[NodeStatus, set[NodeStatus]] = {
        NodeStatus.PENDING: {NodeStatus.TEXT_GENERATING, NodeStatus.NODE_FAILED},
        NodeStatus.TEXT_GENERATING: {NodeStatus.TEXT_DONE, NodeStatus.NODE_FAILED},
        NodeStatus.TEXT_DONE: {NodeStatus.FACT_CHECKING, NodeStatus.NODE_FAILED},
        NodeStatus.FACT_CHECKING: {
            NodeStatus.FACT_PASSED,
            NodeStatus.TEXT_GENERATING,
            NodeStatus.WAITING_MANUAL,
            NodeStatus.NODE_FAILED,
        },
        NodeStatus.FACT_PASSED: {NodeStatus.IMAGE_GENERATING, NodeStatus.NODE_FAILED},
        NodeStatus.IMAGE_GENERATING: {
            NodeStatus.IMAGE_DONE,
            NodeStatus.WAITING_MANUAL,
            NodeStatus.NODE_FAILED,
        },
        NodeStatus.IMAGE_DONE: {NodeStatus.LENGTH_CHECKING, NodeStatus.NODE_FAILED},
        NodeStatus.IMAGE_VERIFYING: {
            NodeStatus.IMAGE_VERIFIED,
            NodeStatus.IMAGE_GENERATING,
            NodeStatus.LENGTH_CHECKING,
            NodeStatus.WAITING_MANUAL,
            NodeStatus.NODE_FAILED,
        },
        NodeStatus.IMAGE_VERIFIED: {NodeStatus.LENGTH_CHECKING, NodeStatus.NODE_FAILED},
        NodeStatus.LENGTH_CHECKING: {
            NodeStatus.LENGTH_PASSED,
            NodeStatus.TEXT_GENERATING,
            NodeStatus.NODE_FAILED,
        },
        NodeStatus.LENGTH_PASSED: {NodeStatus.CONSISTENCY_CHECKING, NodeStatus.NODE_FAILED},
        NodeStatus.CONSISTENCY_CHECKING: {
            NodeStatus.READY_FOR_LAYOUT,
            NodeStatus.WAITING_MANUAL,
            NodeStatus.NODE_FAILED,
        },
        NodeStatus.READY_FOR_LAYOUT: {NodeStatus.LAYOUTED, NodeStatus.NODE_FAILED},
        NodeStatus.LAYOUTED: {NodeStatus.NODE_DONE, NodeStatus.NODE_FAILED},
        NodeStatus.WAITING_MANUAL: {NodeStatus.NODE_DONE, NodeStatus.NODE_FAILED},
        NodeStatus.NODE_DONE: set(),
        NodeStatus.NODE_FAILED: set(),
    }

    _STAGE_CONFIGS: dict[str, StageConfig] = {
        "text": StageConfig(
            key="text",
            start_status=NodeStatus.TEXT_GENERATING,
            done_status=NodeStatus.TEXT_DONE,
            progress_start=0.08,
            progress_done=0.20,
            retry_field="retry_text",
            retry_limit=1,
            manual_on_fail=False,
        ),
        "fact": StageConfig(
            key="fact",
            start_status=NodeStatus.FACT_CHECKING,
            done_status=NodeStatus.FACT_PASSED,
            progress_start=0.24,
            progress_done=0.35,
            retry_field="retry_fact",
            retry_limit=1,
            manual_on_fail=True,
        ),
        "image_generate": StageConfig(
            key="image_generate",
            start_status=NodeStatus.IMAGE_GENERATING,
            done_status=NodeStatus.IMAGE_DONE,
            progress_start=0.40,
            progress_done=0.55,
            retry_field="retry_image",
            retry_limit=2,
            manual_on_fail=True,
        ),
        "length": StageConfig(
            key="length",
            start_status=NodeStatus.LENGTH_CHECKING,
            done_status=NodeStatus.LENGTH_PASSED,
            progress_start=0.76,
            progress_done=0.84,
            retry_field="retry_text",
            retry_limit=1,
            manual_on_fail=False,
        ),
        "consistency": StageConfig(
            key="consistency",
            start_status=NodeStatus.CONSISTENCY_CHECKING,
            done_status=NodeStatus.READY_FOR_LAYOUT,
            progress_start=0.88,
            progress_done=0.94,
            retry_field="retry_fact",
            retry_limit=0,
            manual_on_fail=True,
        ),
        "layout": StageConfig(
            key="layout",
            start_status=NodeStatus.READY_FOR_LAYOUT,
            done_status=NodeStatus.LAYOUTED,
            progress_start=0.97,
            progress_done=0.99,
            retry_field=None,
            retry_limit=0,
            manual_on_fail=False,
        ),
        "finalize": StageConfig(
            key="finalize",
            start_status=NodeStatus.LAYOUTED,
            done_status=NodeStatus.NODE_DONE,
            progress_start=0.995,
            progress_done=1.0,
            retry_field=None,
            retry_limit=0,
            manual_on_fail=False,
        ),
    }

    def __init__(
        self,
        *,
        node_repository: NodeStateRepository,
        task_repository: TaskRepository,
        event_repository: EventLogRepository,
        artifacts_root: Path,
        template_path: Path,
        section_writer: SectionWriterAgent | None = None,
        fact_grounding: FactGroundingAgent | None = None,
        length_control: LengthControlAgent | None = None,
        consistency_check: ConsistencyCheckAgent | None = None,
        table_builder: TableBuilderAgent | None = None,
        layout_agent: LayoutAgent | None = None,
        word_export_agent: WordExportAgent | None = None,
        entity_extractor: EntityExtractorAgent | None = None,
        image_prompt: ImagePromptAgent | None = None,
        image_generation: ImageGenerationAgent | None = None,
        image_relevance: ImageRelevanceAgent | None = None,
        image_retry_limit: int = 3,
        image_score_threshold: float = 0.75,
        system_config_getter: Callable[[], dict[str, Any]] | None = None,
    ) -> None:
        self.node_repository = node_repository
        self.task_repository = task_repository
        self.event_repository = event_repository
        self.artifacts_root = artifacts_root
        self.template_path = template_path
        self.section_writer = section_writer or SectionWriterAgent()
        self.fact_grounding = fact_grounding or FactGroundingAgent()
        self.length_control = length_control or LengthControlAgent()
        self.consistency_check = consistency_check or ConsistencyCheckAgent()
        self.table_builder = table_builder or TableBuilderAgent()
        self.layout_agent = layout_agent or LayoutAgent()
        self.word_export_agent = word_export_agent or WordExportAgent()
        self.entity_extractor = entity_extractor or EntityExtractorAgent()
        self.image_prompt = image_prompt or ImagePromptAgent()
        self.image_generation = image_generation or ImageGenerationAgent()
        self.image_relevance = image_relevance or ImageRelevanceAgent(
            score_threshold=image_score_threshold
        )
        self.image_retry_limit = image_retry_limit
        self.image_score_threshold = image_score_threshold
        self.system_config_getter = system_config_getter or (lambda: {})

    def run_generation(self, task_id: str) -> GenerationSummary:
        """Run unfinished nodes and resume from the latest stable node stage."""
        nodes = self.node_repository.list_by_task(task_id)
        if not nodes:
            self._log(
                task_id,
                stage="GENERATING",
                status=EventStatus.WARNING,
                message="No generation nodes found.",
            )
            return GenerationSummary(total_nodes=0, completed_nodes=0, failed_nodes=0, manual_nodes=0)

        total_nodes = len(nodes)
        self.task_repository.update_progress(
            task_id,
            total_nodes=total_nodes,
            current_stage="GENERATING",
        )

        for item in nodes:
            node = self.node_repository.get(task_id, item.node_uid)
            if node is None:
                continue
            if node.status in {NodeStatus.NODE_DONE, NodeStatus.NODE_FAILED}:
                continue

            self.task_repository.touch_heartbeat(
                task_id,
                stage="GENERATING",
                node_uid=node.node_uid,
            )
            self._run_single_node(node)

            completed = self.node_repository.count_completed(task_id)
            task_progress = 0.2 + 0.6 * (completed / max(total_nodes, 1))
            self.task_repository.update_progress(
                task_id,
                completed_nodes=completed,
                total_progress=round(task_progress, 4),
                current_stage="GENERATING",
                current_node_uid=node.node_uid,
            )

        latest = self.node_repository.list_by_task(task_id)
        completed_nodes = sum(1 for node in latest if node.status == NodeStatus.NODE_DONE)
        failed_nodes = sum(1 for node in latest if node.status == NodeStatus.NODE_FAILED)
        manual_nodes = sum(1 for node in latest if node.image_manual_required)

        self.task_repository.touch_heartbeat(task_id, stage="GENERATING")
        return GenerationSummary(
            total_nodes=total_nodes,
            completed_nodes=completed_nodes,
            failed_nodes=failed_nodes,
            manual_nodes=manual_nodes,
        )

    def run_layout(self, task_id: str) -> Path:
        started = time.perf_counter()
        self.task_repository.touch_heartbeat(task_id, stage="LAYOUTING", node_uid=None)

        toc_document = self._load_confirmed_toc(task_id)
        image_config = self._image_provider_config(task_id)
        payload = self.layout_agent.build(
            task_id=task_id,
            artifacts_root=self.artifacts_root,
            toc_document=toc_document,
            include_images=not self._image_generation_disabled(image_config),
        )
        layout_path = self.artifacts_root / task_id / "final" / "layout_blocks.json"
        self._write_json(layout_path, payload)

        duration_ms = int((time.perf_counter() - started) * 1000)
        self._log(
            task_id,
            stage="LAYOUTING",
            status=EventStatus.SUCCESS,
            message=(
                f"Layout blocks generated with {len(payload.get('blocks') or [])} blocks."
            ),
            output_artifact_path=str(layout_path),
            duration_ms=duration_ms,
            meta_json={"warning_count": len(payload.get("warnings") or [])},
        )
        return layout_path

    def run_export(self, task_id: str) -> Path:
        started = time.perf_counter()
        self.task_repository.touch_heartbeat(task_id, stage="EXPORTING", node_uid=None)

        output_dir = self.artifacts_root / task_id / "final"
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path, warnings = self.word_export_agent.export(
            template_path=self.template_path,
            layout_blocks_path=output_dir / "layout_blocks.json",
            output_path=output_dir / "output.docx",
        )
        duration_ms = int((time.perf_counter() - started) * 1000)

        self._log(
            task_id,
            stage="EXPORTING",
            status=EventStatus.SUCCESS,
            message="Exported output.docx from layout blocks.",
            output_artifact_path=str(output_path),
            duration_ms=duration_ms,
            meta_json={"warning_count": len(warnings)},
        )
        return output_path

    # Backward-compatible wrapper.
    def run_task(self, task_id: str) -> None:
        summary = self.run_generation(task_id)
        if summary.failed_nodes > 0:
            raise RuntimeError("At least one node failed during generation.")
        self.run_layout(task_id)
        self.run_export(task_id)

    def _run_single_node(self, node: NodeState) -> None:
        node_dir = self.artifacts_root / node.task_id / "nodes" / node.node_uid
        (node_dir / "checkpoints").mkdir(parents=True, exist_ok=True)
        (node_dir / "snapshots").mkdir(parents=True, exist_ok=True)

        if node.started_at is None:
            started_at = utc_now_iso()
            self.node_repository.update_status(
                node.task_id,
                node.node_uid,
                status=node.status,
                progress=node.progress,
                current_stage=node.current_stage or node.status.value,
                started_at=started_at,
            )
            node.started_at = started_at

        stages = self._plan_stages(node.status)
        if not stages:
            return

        self._log(
            node.task_id,
            node_uid=node.node_uid,
            stage="NODE_RESUME",
            status=EventStatus.INFO,
            message=f"Resume node from {node.status.value} with stages: {', '.join(stages)}",
        )

        for stage_key in stages:
            if stage_key == "manual_finalize":
                self._finalize_waiting_manual(node, node_dir, reason="resume_waiting_manual")
                return
            if node.status in {NodeStatus.NODE_DONE, NodeStatus.NODE_FAILED}:
                return

            ok = self._execute_stage(node=node, node_dir=node_dir, stage_key=stage_key)
            if not ok:
                return

    def _plan_stages(self, current_status: NodeStatus) -> list[str]:
        if current_status == NodeStatus.WAITING_MANUAL:
            return ["manual_finalize"]
        if current_status in {NodeStatus.NODE_DONE, NodeStatus.NODE_FAILED}:
            return []

        start_stage: str | None = None
        if current_status in self._IN_PROGRESS_TO_STAGE:
            start_stage = self._IN_PROGRESS_TO_STAGE[current_status]
        elif current_status in self._STABLE_TO_NEXT_STAGE:
            start_stage = self._STABLE_TO_NEXT_STAGE[current_status]

        if start_stage is None:
            return ["text"]

        start_idx = self._STAGE_ORDER.index(start_stage)
        return self._STAGE_ORDER[start_idx:]

    def _execute_stage(self, *, node: NodeState, node_dir: Path, stage_key: str) -> bool:
        config = self._STAGE_CONFIGS[stage_key]
        writer = self._stage_writer(stage_key)

        while True:
            input_snapshot_path = self._write_input_snapshot(
                node=node,
                node_dir=node_dir,
                stage_key=stage_key,
            )
            self._transition_node(
                node,
                config.start_status,
                config.progress_start,
                input_snapshot_path=input_snapshot_path,
                last_error=None,
            )
            started = time.perf_counter()

            try:
                output_path = writer(node, node_dir)
            except Exception as exc:  # noqa: BLE001
                duration_ms = int((time.perf_counter() - started) * 1000)
                should_retry = self._handle_stage_error(
                    node=node,
                    node_dir=node_dir,
                    config=config,
                    stage_key=stage_key,
                    input_snapshot_path=input_snapshot_path,
                    error=exc,
                    duration_ms=duration_ms,
                )
                if should_retry:
                    continue
                return False

            duration_ms = int((time.perf_counter() - started) * 1000)
            finished_at = utc_now_iso() if config.done_status == NodeStatus.NODE_DONE else self._UNSET
            self._transition_node(
                node,
                config.done_status,
                config.progress_done,
                input_snapshot_path=input_snapshot_path,
                output_artifact_path=str(output_path),
                last_error=None,
                manual_action_status=node.manual_action_status,
                image_manual_required=node.image_manual_required,
                finished_at=finished_at,
            )
            self._write_checkpoint(
                node=node,
                node_dir=node_dir,
                checkpoint_name=config.done_status.value,
                input_snapshot_path=input_snapshot_path,
                output_artifact_path=str(output_path),
                status=config.done_status,
                last_error=None,
                duration_ms=duration_ms,
                metrics=self._stage_metrics(node=node, node_dir=node_dir, stage_key=stage_key),
            )
            self._log(
                node.task_id,
                node_uid=node.node_uid,
                stage=config.done_status.value,
                status=EventStatus.SUCCESS,
                message=f"Node {node.node_id} -> {config.done_status.value}",
                input_snapshot_path=input_snapshot_path,
                output_artifact_path=str(output_path),
                duration_ms=duration_ms,
                retry_count=self._retry_count(node, config.retry_field),
            )
            return True

    def _handle_stage_error(
        self,
        *,
        node: NodeState,
        node_dir: Path,
        config: StageConfig,
        stage_key: str,
        input_snapshot_path: str,
        error: Exception,
        duration_ms: int,
    ) -> bool:
        retry_count = self._retry_count(node, config.retry_field)
        if config.retry_field is not None:
            self._increment_retry(node, config.retry_field)
            retry_count = self._retry_count(node, config.retry_field)

        self._log(
            node.task_id,
            node_uid=node.node_uid,
            stage=config.start_status.value,
            status=EventStatus.ERROR,
            message=f"Stage {stage_key} failed: {error}",
            input_snapshot_path=input_snapshot_path,
            duration_ms=duration_ms,
            retry_count=retry_count,
        )

        if config.retry_field is not None and retry_count <= config.retry_limit:
            self._log(
                node.task_id,
                node_uid=node.node_uid,
                stage=config.start_status.value,
                status=EventStatus.WARNING,
                message=(
                    f"Stage {stage_key} retry {retry_count}/{config.retry_limit} "
                    f"for node {node.node_id}"
                ),
                input_snapshot_path=input_snapshot_path,
                retry_count=retry_count,
            )
            return True

        if config.manual_on_fail:
            self._enter_waiting_manual(
                node=node,
                node_dir=node_dir,
                stage_key=stage_key,
                input_snapshot_path=input_snapshot_path,
                error_message=str(error),
                duration_ms=duration_ms,
            )
            self._finalize_waiting_manual(
                node,
                node_dir,
                reason=f"lenient_{stage_key}_failure",
            )
            return False

        self._mark_node_failed(
            node=node,
            node_dir=node_dir,
            input_snapshot_path=input_snapshot_path,
            error_message=str(error),
            duration_ms=duration_ms,
        )
        return False

    def _enter_waiting_manual(
        self,
        *,
        node: NodeState,
        node_dir: Path,
        stage_key: str,
        input_snapshot_path: str,
        error_message: str,
        duration_ms: int,
    ) -> None:
        requires_image_manual = stage_key.startswith("image")
        self._transition_node(
            node,
            NodeStatus.WAITING_MANUAL,
            0.995,
            input_snapshot_path=input_snapshot_path,
            last_error=error_message,
            manual_action_status=ManualActionStatus.PENDING,
            image_manual_required=requires_image_manual,
        )
        self._write_checkpoint(
            node=node,
            node_dir=node_dir,
            checkpoint_name=NodeStatus.WAITING_MANUAL.value,
            input_snapshot_path=input_snapshot_path,
            output_artifact_path=node.output_artifact_path,
            status=NodeStatus.WAITING_MANUAL,
            last_error=error_message,
            duration_ms=duration_ms,
            metrics=self._stage_metrics(node=node, node_dir=node_dir, stage_key=stage_key),
        )
        self._log(
            node.task_id,
            node_uid=node.node_uid,
            stage=NodeStatus.WAITING_MANUAL.value,
            status=EventStatus.WARNING,
            message=f"Node moved to WAITING_MANUAL due to {stage_key} failure.",
            input_snapshot_path=input_snapshot_path,
            output_artifact_path=node.output_artifact_path,
            duration_ms=duration_ms,
            retry_count=max(node.retry_text, node.retry_fact, node.retry_image),
        )

    def _finalize_waiting_manual(self, node: NodeState, node_dir: Path, *, reason: str) -> None:
        input_snapshot_path = self._write_input_snapshot(
            node=node,
            node_dir=node_dir,
            stage_key="manual_finalize",
        )
        metrics_path = self._write_metrics_artifact(node, node_dir)
        self._transition_node(
            node,
            NodeStatus.NODE_DONE,
            1.0,
            input_snapshot_path=input_snapshot_path,
            output_artifact_path=str(metrics_path),
            manual_action_status=ManualActionStatus.PENDING,
            image_manual_required=node.image_manual_required,
            finished_at=utc_now_iso(),
        )
        self._write_checkpoint(
            node=node,
            node_dir=node_dir,
            checkpoint_name=NodeStatus.NODE_DONE.value,
            input_snapshot_path=input_snapshot_path,
            output_artifact_path=str(metrics_path),
            status=NodeStatus.NODE_DONE,
            last_error=node.last_error,
            duration_ms=0,
            metrics={
                **self._stage_metrics(node=node, node_dir=node_dir, stage_key="manual_finalize"),
                "manual_required": True,
                "reason": reason,
            },
        )
        self._log(
            node.task_id,
            node_uid=node.node_uid,
            stage=NodeStatus.NODE_DONE.value,
            status=EventStatus.WARNING,
            message=f"Node finished in lenient mode (manual pending): {reason}",
            input_snapshot_path=input_snapshot_path,
            output_artifact_path=str(metrics_path),
        )

    def _mark_node_failed(
        self,
        *,
        node: NodeState,
        node_dir: Path,
        input_snapshot_path: str,
        error_message: str,
        duration_ms: int,
    ) -> None:
        self._transition_node(
            node,
            NodeStatus.NODE_FAILED,
            node.progress,
            input_snapshot_path=input_snapshot_path,
            last_error=error_message,
            finished_at=utc_now_iso(),
        )
        self._write_checkpoint(
            node=node,
            node_dir=node_dir,
            checkpoint_name=NodeStatus.NODE_FAILED.value,
            input_snapshot_path=input_snapshot_path,
            output_artifact_path=node.output_artifact_path,
            status=NodeStatus.NODE_FAILED,
            last_error=error_message,
            duration_ms=duration_ms,
            metrics=self._stage_metrics(node=node, node_dir=node_dir, stage_key="failed"),
        )
        self._log(
            node.task_id,
            node_uid=node.node_uid,
            stage=NodeStatus.NODE_FAILED.value,
            status=EventStatus.ERROR,
            message=f"Node failed: {error_message}",
            input_snapshot_path=input_snapshot_path,
            output_artifact_path=node.output_artifact_path,
            duration_ms=duration_ms,
        )

    def _stage_writer(self, stage_key: str) -> Callable[[NodeState, Path], Path]:
        writers: dict[str, Callable[[NodeState, Path], Path]] = {
            "text": self._write_text_artifact,
            "fact": self._write_fact_check_artifact,
            "image_generate": self._write_image_generate_artifact,
            "image_verify": self._write_image_verify_artifact,
            "length": self._write_length_artifact,
            "consistency": self._write_consistency_artifact,
            "layout": self._write_layout_artifact,
            "finalize": self._write_metrics_artifact,
        }
        return writers[stage_key]

    def _transition_node(
        self,
        node: NodeState,
        new_status: NodeStatus,
        progress: float,
        *,
        input_snapshot_path: str | None | object = _UNSET,
        output_artifact_path: str | None | object = _UNSET,
        last_error: str | None | object = _UNSET,
        manual_action_status: ManualActionStatus | None = None,
        image_manual_required: bool | None = None,
        finished_at: str | None | object = _UNSET,
    ) -> None:
        if new_status != node.status:
            allowed = self._ALLOWED_NODE_TRANSITIONS.get(node.status, set())
            if new_status not in allowed:
                raise ValueError(
                    f"Illegal node transition: {node.status.value} -> {new_status.value}"
                )

        kwargs: dict[str, Any] = {}
        if input_snapshot_path is not self._UNSET:
            kwargs["input_snapshot_path"] = input_snapshot_path
        if output_artifact_path is not self._UNSET:
            kwargs["output_artifact_path"] = output_artifact_path
        if last_error is not self._UNSET:
            kwargs["last_error"] = last_error
        if finished_at is not self._UNSET:
            kwargs["finished_at"] = finished_at
        if manual_action_status is not None:
            kwargs["manual_action_status"] = manual_action_status
        if image_manual_required is not None:
            kwargs["image_manual_required"] = image_manual_required

        self.node_repository.update_status(
            node.task_id,
            node.node_uid,
            status=new_status,
            progress=progress,
            current_stage=new_status.value,
            **kwargs,
        )

        node.status = new_status
        node.progress = progress
        node.current_stage = new_status.value
        if input_snapshot_path is not self._UNSET:
            node.input_snapshot_path = input_snapshot_path
        if output_artifact_path is not self._UNSET:
            node.output_artifact_path = output_artifact_path
        if last_error is not self._UNSET:
            node.last_error = last_error
        if finished_at is not self._UNSET:
            node.finished_at = finished_at
        if manual_action_status is not None:
            node.manual_action_status = manual_action_status
        if image_manual_required is not None:
            node.image_manual_required = image_manual_required
        node.updated_at = utc_now_iso()
        node.last_heartbeat_at = utc_now_iso()

        self.node_repository.touch_heartbeat(
            node.task_id,
            node.node_uid,
            current_stage=new_status.value,
        )

    def _retry_count(self, node: NodeState, retry_field: str | None) -> int:
        if retry_field is None:
            return 0
        return int(getattr(node, retry_field))

    def _increment_retry(self, node: NodeState, retry_field: str) -> None:
        self.node_repository.increment_retry(node.task_id, node.node_uid, retry_field)
        current = int(getattr(node, retry_field))
        setattr(node, retry_field, current + 1)

    def _write_input_snapshot(self, *, node: NodeState, node_dir: Path, stage_key: str) -> str:
        snapshot_path = node_dir / "snapshots" / f"{stage_key}_input.json"
        payload = {
            "task_id": node.task_id,
            "node_uid": node.node_uid,
            "node_id": node.node_id,
            "stage": stage_key,
            "current_status": node.status.value,
            "current_stage": node.current_stage,
            "last_output_artifact": node.output_artifact_path,
            "generated_at": utc_now_iso(),
        }
        self._write_json(snapshot_path, payload)
        return str(snapshot_path)

    def _write_checkpoint(
        self,
        *,
        node: NodeState,
        node_dir: Path,
        checkpoint_name: str,
        input_snapshot_path: str | None,
        output_artifact_path: str | None,
        status: NodeStatus,
        last_error: str | None,
        duration_ms: int,
        metrics: dict[str, Any],
    ) -> str:
        path = node_dir / "checkpoints" / f"{checkpoint_name.lower()}.json"
        payload = {
            "task_id": node.task_id,
            "node_uid": node.node_uid,
            "node_id": node.node_id,
            "status": status.value,
            "current_stage": node.current_stage,
            "input_snapshot_path": input_snapshot_path,
            "output_artifact_path": output_artifact_path,
            "last_error": last_error,
            "retry_text": node.retry_text,
            "retry_image": node.retry_image,
            "retry_fact": node.retry_fact,
            "duration_ms": duration_ms,
            "metrics": metrics,
            "created_at": utc_now_iso(),
        }
        self._write_json(path, payload)
        return str(path)

    def _stage_metrics(self, *, node: NodeState, node_dir: Path, stage_key: str) -> dict[str, Any]:
        text_path = node_dir / "text.json"
        word_count = 0
        grounded_ratio = 0.0
        image_score_avg = 0.0
        manual_image_count = 0
        table_count = 0
        consistency_issue_count = 0
        if text_path.exists():
            try:
                payload = json.loads(text_path.read_text(encoding="utf-8"))
                word_count = int(payload.get("word_count") or 0)
            except Exception:  # noqa: BLE001
                word_count = 0
        fact_path = node_dir / "fact_check.json"
        if fact_path.exists():
            try:
                payload = json.loads(fact_path.read_text(encoding="utf-8"))
                grounded_ratio = float(payload.get("grounded_ratio") or 0.0)
            except Exception:  # noqa: BLE001
                grounded_ratio = 0.0
        relevance_path = node_dir / "image_relevance.json"
        if relevance_path.exists():
            try:
                payload = json.loads(relevance_path.read_text(encoding="utf-8"))
                image_scores = payload.get("image_scores") or []
                if image_scores:
                    image_score_avg = round(
                        sum(float(item.get("score") or 0.0) for item in image_scores)
                        / len(image_scores),
                        4,
                    )
                    manual_image_count = sum(
                        1 for item in image_scores if item.get("result") != AgentResult.PASS.value
                    )
            except Exception:  # noqa: BLE001
                image_score_avg = 0.0
                manual_image_count = 0
        tables_path = node_dir / "tables.json"
        if tables_path.exists():
            try:
                payload = json.loads(tables_path.read_text(encoding="utf-8"))
                table_count = len(payload.get("tables") or [])
            except Exception:  # noqa: BLE001
                table_count = 0
        consistency_path = node_dir / "consistency.json"
        if consistency_path.exists():
            try:
                payload = json.loads(consistency_path.read_text(encoding="utf-8"))
                checks = payload.get("checks") or {}
                consistency_issue_count = sum(
                    len((checks.get(key) or {}).get("issues") or [])
                    for key in (
                        "entity_consistency",
                        "term_consistency",
                        "constraint_consistency",
                        "reference_consistency",
                    )
                )
            except Exception:  # noqa: BLE001
                consistency_issue_count = 0
        return {
            "stage": stage_key,
            "progress": node.progress,
            "word_count": word_count,
            "grounded_ratio": grounded_ratio,
            "image_score_avg": image_score_avg,
            "manual_image_count": manual_image_count,
            "table_count": table_count,
            "consistency_issue_count": consistency_issue_count,
            "image_manual_required": node.image_manual_required,
        }

    def _requirement_path(self, task_id: str) -> Path:
        return self.artifacts_root / task_id / "parsed" / "requirement.json"

    def _style_profile_path(self, task_id: str) -> Path:
        return self.artifacts_root / task_id / "parsed" / "style_profile.json"

    def _load_requirement(self, task_id: str) -> RequirementDocument:
        path = self._requirement_path(task_id)
        if not path.exists():
            raise RuntimeError("requirement.json missing before node generation")
        payload = json.loads(path.read_text(encoding="utf-8"))
        return RequirementDocument.model_validate(payload)

    def _load_style_profile(self, task_id: str) -> dict[str, Any]:
        path = self._style_profile_path(task_id)
        if not path.exists():
            return {}
        payload = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(payload, dict):
            return payload
        return {}

    @staticmethod
    def _load_fact_check(node_dir: Path) -> FactCheck | None:
        path = node_dir / "fact_check.json"
        if not path.exists():
            return None
        return FactCheck.model_validate(json.loads(path.read_text(encoding="utf-8")))

    @staticmethod
    def _load_node_text(node_dir: Path) -> NodeText:
        path = node_dir / "text.json"
        if not path.exists():
            raise RuntimeError("text.json missing")
        return NodeText.model_validate(json.loads(path.read_text(encoding="utf-8")))

    @staticmethod
    def _load_entity_extraction(node_dir: Path) -> EntityExtraction:
        path = node_dir / "entities.json"
        if not path.exists():
            raise RuntimeError("entities.json missing before image verification")
        return EntityExtraction.model_validate(json.loads(path.read_text(encoding="utf-8")))

    @staticmethod
    def _load_image_prompts(node_dir: Path) -> ImagePrompts:
        path = node_dir / "image_prompts.json"
        if not path.exists():
            raise RuntimeError("image_prompts.json missing before image verification")
        return ImagePrompts.model_validate(json.loads(path.read_text(encoding="utf-8")))

    @staticmethod
    def _load_images_artifact(node_dir: Path) -> ImagesArtifact:
        path = node_dir / "images.json"
        if not path.exists():
            raise RuntimeError("images.json missing before image verification")
        return ImagesArtifact.model_validate(json.loads(path.read_text(encoding="utf-8")))

    @staticmethod
    def _load_json_if_exists(path: Path) -> dict[str, Any] | None:
        if not path.exists():
            return None
        payload = json.loads(path.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else None

    def _write_text_artifact(self, node: NodeState, node_dir: Path) -> Path:
        requirement = self._load_requirement(node.task_id)
        artifact = self.section_writer.generate(node=node, requirement=requirement)
        path = node_dir / "text.json"
        self._write_json(path, artifact.model_dump(mode="json"))
        return path

    def _write_fact_check_artifact(self, node: NodeState, node_dir: Path) -> Path:
        requirement = self._load_requirement(node.task_id)
        text_path = node_dir / "text.json"
        if not text_path.exists():
            raise RuntimeError("text.json missing before fact grounding")

        node_text = NodeText.model_validate(
            json.loads(text_path.read_text(encoding="utf-8"))
        )
        artifact = self.fact_grounding.check(node_text=node_text, requirement=requirement)
        path = node_dir / "fact_check.json"
        self._write_json(path, artifact.model_dump(mode="json"))

        if artifact.result != AgentResult.PASS:
            if node.retry_fact == 0:
                revised = self.section_writer.revise_text(
                    node_text=node_text,
                    fact_check=artifact,
                    requirement=requirement,
                )
                self._write_json(text_path, revised.model_dump(mode="json"))
                self._log(
                    node.task_id,
                    node_uid=node.node_uid,
                    stage="FACT_REVISE",
                    status=EventStatus.WARNING,
                    message="Fact grounding failed once; revised text and retry.",
                    output_artifact_path=str(text_path),
                    meta_json={
                        "grounded_ratio": artifact.grounded_ratio,
                        "unsupported_count": len(artifact.unsupported_claims),
                    },
                )
            raise RuntimeError(
                f"Fact grounding failed: grounded_ratio={artifact.grounded_ratio}"
            )
        return path

    def _write_image_generate_artifact(self, node: NodeState, node_dir: Path) -> Path:
        text_path = node_dir / "text.json"
        if not text_path.exists():
            raise RuntimeError("text.json missing before entity extraction")

        fact_check = self._load_fact_check(node_dir)
        if fact_check is None or fact_check.result != AgentResult.PASS:
            raise RuntimeError("fact_check.json missing or failed before image generation")

        provider_config = self._image_provider_config(node.task_id)
        if self._image_generation_disabled(provider_config):
            entities = EntityExtraction(node_uid=node.node_uid, entities=[])
            prompts = ImagePrompts(node_uid=node.node_uid, prompts=[])
            images = ImagesArtifact(node_uid=node.node_uid, images=[])
            self._write_json(
                node_dir / "entities.json",
                entities.model_dump(mode="json"),
            )
            self._write_json(
                node_dir / "image_prompts.json",
                prompts.model_dump(mode="json"),
            )
            path = node_dir / "images.json"
            self._write_json(path, images.model_dump(mode="json"))
            self._log(
                node.task_id,
                node_uid=node.node_uid,
                stage="IMAGE_PROVIDER",
                status=EventStatus.INFO,
                message="Image generation disabled by system config; wrote empty image artifacts.",
                output_artifact_path=str(path),
                meta_json={
                    "provider": provider_config.get("image_provider") or "disabled",
                    "model": provider_config.get("image_model_name") or "关闭图像生成",
                    "disabled": True,
                },
            )
            node.image_manual_required = False
            node.manual_action_status = ManualActionStatus.NONE
            return path

        node_text = self._load_node_text(node_dir)
        entities = self.entity_extractor.extract(node_text=node_text, fact_check=fact_check)
        prompts = self.image_prompt.build(entities=entities, node_text=node_text)
        images = ImagesArtifact(node_uid=node.node_uid, images=[])

        for prompt in prompts.prompts:
            generated = self.image_generation.generate(
                prompt_item=prompt,
                node_dir=node_dir,
                retry_count=0,
                provider_config=provider_config,
            )
            images.images.append(generated)
            resolved_model = (
                provider_config.get("_resolved_image_model_name")
                or provider_config.get("image_model_name")
                or "placeholder"
            )
            fallback_from = provider_config.get("_image_model_fallback_from")
            if fallback_from and fallback_from != resolved_model:
                self._log(
                    node.task_id,
                    node_uid=node.node_uid,
                    stage="IMAGE_MODEL_FALLBACK",
                    status=EventStatus.WARNING,
                    message=f"Switched image model from {fallback_from} to {resolved_model} after provider error.",
                    meta_json={
                        "image_id": generated.image_id,
                        "provider": provider_config.get("image_provider") or "mock",
                        "fallback_from": fallback_from,
                        "fallback_to": resolved_model,
                        "attempted_models": provider_config.get("_image_model_attempts") or [],
                    },
                )
            self._log(
                node.task_id,
                node_uid=node.node_uid,
                stage="IMAGE_PROVIDER",
                status=EventStatus.INFO,
                message=(
                    f"Generated {generated.image_id} with "
                    f"{provider_config.get('image_provider') or 'mock'}:"
                    f"{resolved_model}"
                ),
                output_artifact_path=str(node_dir / generated.file),
                meta_json={
                    "image_id": generated.image_id,
                    "provider": provider_config.get("image_provider") or "mock",
                    "model": resolved_model,
                    "selected_model": provider_config.get("image_model_name") or "placeholder",
                    "attempted_models": provider_config.get("_image_model_attempts") or [],
                    "fallback_from": provider_config.get("_image_model_fallback_from"),
                },
            )

        self._write_json(
            node_dir / "entities.json",
            entities.model_dump(mode="json"),
        )
        self._write_json(
            node_dir / "image_prompts.json",
            prompts.model_dump(mode="json"),
        )
        path = node_dir / "images.json"
        self._write_json(path, images.model_dump(mode="json"))

        node.image_manual_required = False
        node.manual_action_status = ManualActionStatus.NONE
        return path

    def _write_image_verify_artifact(self, node: NodeState, node_dir: Path) -> Path:
        node_text = self._load_node_text(node_dir)
        entities = self._load_entity_extraction(node_dir)
        prompts = self._load_image_prompts(node_dir)
        images = self._load_images_artifact(node_dir)
        provider_config = self._image_provider_config(node.task_id)

        node.image_manual_required = False
        node.manual_action_status = ManualActionStatus.NONE

        prompt_index = {item.prompt_id: item for item in prompts.prompts}
        score_items: list[ImageScoreItem] = []

        for image_index, image in enumerate(images.images):
            current_image = image
            current_prompt = prompt_index.get(current_image.prompt_id or "")

            while True:
                single_report = self.image_relevance.evaluate(
                    node_text=node_text,
                    entities=entities,
                    images=ImagesArtifact(node_uid=node.node_uid, images=[current_image]),
                )
                score_item = single_report.image_scores[0]

                if score_item.result == AgentResult.PASS:
                    current_image.status = ImageStatus.PASS
                    images.images[image_index] = current_image
                    score_items.append(score_item)
                    break

                if current_image.retry_count < self.image_retry_limit and current_prompt is not None:
                    retry_no = current_image.retry_count + 1
                    self._increment_retry(node, "retry_image")
                    current_prompt = self.image_prompt.strengthen_prompt(
                        current_prompt,
                        missing_elements=score_item.missing_elements,
                        retry_no=retry_no,
                    )
                    prompt_index[current_prompt.prompt_id] = current_prompt
                    current_image = self.image_generation.generate(
                        prompt_item=current_prompt,
                        node_dir=node_dir,
                        retry_count=retry_no,
                        provider_config=provider_config,
                    )
                    current_image.status = ImageStatus.RETRYING
                    images.images[image_index] = current_image
                    self._write_json(
                        node_dir / "image_prompts.json",
                        ImagePrompts(
                            node_uid=node.node_uid,
                            prompts=[
                                prompt_index[item.prompt_id]
                                for item in prompts.prompts
                                if item.prompt_id in prompt_index
                            ],
                        ).model_dump(mode="json"),
                    )
                    self._write_json(
                        node_dir / "images.json",
                        images.model_dump(mode="json"),
                    )
                    self._log(
                        node.task_id,
                        node_uid=node.node_uid,
                        stage="IMAGE_RETRY",
                        status=EventStatus.WARNING,
                        message=(
                            f"Retry image {current_image.image_id} "
                            f"{retry_no}/{self.image_retry_limit}"
                        ),
                        output_artifact_path=str(node_dir / current_image.file),
                        retry_count=node.retry_image,
                        meta_json={
                            "image_id": current_image.image_id,
                            "missing_elements": score_item.missing_elements,
                            "score": score_item.score,
                            "score_threshold": self.image_score_threshold,
                        },
                    )
                    continue

                current_image.status = ImageStatus.NEED_MANUAL_CONFIRM
                images.images[image_index] = current_image
                node.image_manual_required = True
                node.manual_action_status = ManualActionStatus.PENDING
                score_items.append(
                    ImageScoreItem(
                        image_id=current_image.image_id,
                        score=score_item.score,
                        missing_elements=score_item.missing_elements,
                        result=AgentResult.FAIL,
                    )
                )
                self._log(
                    node.task_id,
                    node_uid=node.node_uid,
                    stage="IMAGE_MANUAL",
                    status=EventStatus.WARNING,
                    message=(
                        f"Image {current_image.image_id} exceeded retry limit and needs manual confirm."
                    ),
                    output_artifact_path=str(node_dir / current_image.file),
                    retry_count=node.retry_image,
                    meta_json={
                        "image_id": current_image.image_id,
                        "missing_elements": score_item.missing_elements,
                        "score": score_item.score,
                        "score_threshold": self.image_score_threshold,
                    },
                )
                break

        updated_prompts = ImagePrompts(
            node_uid=node.node_uid,
            prompts=[
                prompt_index[item.prompt_id]
                for item in prompts.prompts
                if item.prompt_id in prompt_index
            ],
        )
        relevance_report = ImageRelevanceReport(
            node_uid=node.node_uid,
            image_scores=score_items,
            overall_result=(
                AgentResult.PASS
                if all(item.result == AgentResult.PASS for item in score_items)
                else AgentResult.FAIL
            ),
        )

        self._write_json(
            node_dir / "image_prompts.json",
            updated_prompts.model_dump(mode="json"),
        )
        self._write_json(
            node_dir / "images.json",
            images.model_dump(mode="json"),
        )
        path = node_dir / "image_relevance.json"
        self._write_json(path, relevance_report.model_dump(mode="json"))

        if node.image_manual_required:
            self._log(
                node.task_id,
                node_uid=node.node_uid,
                stage="IMAGE_LENIENT",
                status=EventStatus.WARNING,
                message="Image pipeline finished in lenient mode; manual confirm required.",
                output_artifact_path=str(path),
                retry_count=node.retry_image,
                meta_json={"score_threshold": self.image_score_threshold},
            )
        return path

    def _image_provider_config(self, task_id: str) -> dict[str, Any]:
        config = dict(self.system_config_getter() or {})
        task = self.task_repository.get(task_id)
        if task is not None:
            if str(task.image_provider or "").strip().lower() == "disabled":
                config["image_provider"] = "disabled"
                config["image_model_name"] = "关闭图像生成"
            else:
                config.setdefault("image_provider", task.image_provider)
            config.setdefault("text_provider", task.text_provider)
        return config

    @staticmethod
    def _image_generation_disabled(provider_config: dict[str, Any] | None) -> bool:
        if not provider_config:
            return False
        provider = str(provider_config.get("image_provider") or "").strip().lower()
        model_name = str(provider_config.get("image_model_name") or "").strip()
        return provider in {"disabled", "none", "off"} or model_name == "关闭图像生成"

    def _write_length_artifact(self, node: NodeState, node_dir: Path) -> Path:
        text_path = node_dir / "text.json"
        if not text_path.exists():
            raise RuntimeError("text.json missing before length control")

        requirement = self._load_requirement(node.task_id)
        node_text = NodeText.model_validate(
            json.loads(text_path.read_text(encoding="utf-8"))
        )
        controlled, details = self.length_control.control(
            node_text=node_text,
            requirement=requirement,
        )
        if details["result"] != "PASS":
            raise RuntimeError(
                f"Length control failed: after_word_count={details['after_word_count']}"
            )
        self._write_json(text_path, controlled.model_dump(mode="json"))

        path = node_dir / "length_control.json"
        details["generated_at"] = utc_now_iso()
        self._write_json(path, details)
        return path

    def _write_consistency_artifact(self, node: NodeState, node_dir: Path) -> Path:
        text_path = node_dir / "text.json"
        if not text_path.exists():
            raise RuntimeError("text.json missing before consistency check")

        requirement = self._load_requirement(node.task_id)
        style_profile = self._load_style_profile(node.task_id)
        node_text = NodeText.model_validate(json.loads(text_path.read_text(encoding="utf-8")))

        tables_path = node_dir / "tables.json"
        table_preferences = style_profile.get("table_preferences")
        tables_artifact = self.table_builder.build(
            node_text=node_text,
            requirement=requirement,
            table_preferences=table_preferences if isinstance(table_preferences, dict) else None,
        )
        self._write_json(tables_path, tables_artifact.model_dump(mode="json"))

        fact_check = self._load_fact_check(node_dir)
        images = self._load_json_if_exists(node_dir / "images.json")
        toc_confirmed = self._load_json_if_exists(
            self.artifacts_root / node.task_id / "toc" / "toc_confirmed.json"
        )
        report, revised_text, revised_tables = self.consistency_check.check_and_fix(
            node_text=node_text,
            requirement=requirement,
            tables=tables_artifact,
            fact_check=fact_check,
            images=images,
            toc_confirmed=toc_confirmed,
        )

        revised_text.word_count = self.section_writer.count_text_units(
            item.text for section in revised_text.sections for item in section.paragraphs
        )
        self._write_json(text_path, revised_text.model_dump(mode="json"))
        self._write_json(tables_path, revised_tables.model_dump(mode="json"))

        path = node_dir / "consistency.json"
        self._write_json(path, report.model_dump(mode="json"))

        issue_total = sum(
            len(check.issues)
            for check in [
                report.checks.entity_consistency,
                report.checks.term_consistency,
                report.checks.constraint_consistency,
                report.checks.reference_consistency,
            ]
        )
        unresolved_total = sum(
            1
            for check in [
                report.checks.entity_consistency,
                report.checks.term_consistency,
                report.checks.constraint_consistency,
                report.checks.reference_consistency,
            ]
            for issue in check.issues
            if not issue.fixed
        )
        if issue_total > 0:
            self._log(
                node.task_id,
                node_uid=node.node_uid,
                stage="CONSISTENCY_FIX",
                status=EventStatus.WARNING if unresolved_total else EventStatus.INFO,
                message=(
                    f"Consistency issues={issue_total}, unresolved={unresolved_total}, "
                    f"tables={len(revised_tables.tables)}"
                ),
                output_artifact_path=str(path),
            )

        if report.result != AgentResult.PASS:
            raise RuntimeError(
                f"Consistency check failed: unresolved_issues={unresolved_total}"
            )
        return path

    def _write_layout_artifact(self, node: NodeState, node_dir: Path) -> Path:
        path = node_dir / "layout_ready.json"
        self._write_json(
            path,
            {
                "node_uid": node.node_uid,
                "node_id": node.node_id,
                "layout_status": "READY_FOR_TASK_LAYOUT",
                "generated_at": utc_now_iso(),
            },
        )
        return path

    def _write_metrics_artifact(self, node: NodeState, node_dir: Path) -> Path:
        word_count = 0
        text_path = node_dir / "text.json"
        if text_path.exists():
            payload = json.loads(text_path.read_text(encoding="utf-8"))
            word_count = int(payload.get("word_count") or 0)
        grounded_ratio = 0.0
        fact_path = node_dir / "fact_check.json"
        if fact_path.exists():
            payload = json.loads(fact_path.read_text(encoding="utf-8"))
            grounded_ratio = float(payload.get("grounded_ratio") or 0.0)
        image_score_avg = 0.0
        relevance_path = node_dir / "image_relevance.json"
        if relevance_path.exists():
            payload = json.loads(relevance_path.read_text(encoding="utf-8"))
            image_scores = payload.get("image_scores") or []
            if image_scores:
                image_score_avg = round(
                    sum(float(item.get("score") or 0.0) for item in image_scores)
                    / len(image_scores),
                    4,
                )

        artifact = Metrics(
            node_uid=node.node_uid,
            word_count=word_count,
            grounded_ratio=grounded_ratio,
            image_score_avg=image_score_avg,
            image_retry_total=node.retry_image,
            text_retry_total=node.retry_text,
            fact_retry_total=node.retry_fact,
            duration_ms=0,
            final_status=NodeStatus.NODE_DONE,
        )
        path = node_dir / "metrics.json"
        self._write_json(path, artifact.model_dump(mode="json"))
        return path

    def _load_confirmed_toc(self, task_id: str) -> TOCDocument:
        path = self.artifacts_root / task_id / "toc" / "toc_confirmed.json"
        if not path.exists():
            raise RuntimeError(f"toc_confirmed.json missing for task {task_id}")
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
        status: EventStatus,
        message: str,
        node_uid: str | None = None,
        retry_count: int = 0,
        input_snapshot_path: str | None = None,
        output_artifact_path: str | None = None,
        duration_ms: int | None = None,
        meta_json: dict[str, Any] | None = None,
    ) -> None:
        self.event_repository.create(
            EventLog(
                event_id=f"evt_{uuid.uuid4().hex[:12]}",
                task_id=task_id,
                node_uid=node_uid,
                stage=stage,
                status=status,
                message=message,
                retry_count=retry_count,
                input_snapshot_path=input_snapshot_path,
                output_artifact_path=output_artifact_path,
                duration_ms=duration_ms,
                meta_json=meta_json,
            )
        )
