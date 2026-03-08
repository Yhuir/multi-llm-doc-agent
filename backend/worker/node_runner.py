"""Backend worker skeleton for node-level execution."""

from __future__ import annotations

import json
import shutil
import uuid
from pathlib import Path

from backend.models.enums import AgentResult, EventStatus, NodeStatus, TaskStatus
from backend.models.schemas import (
    CheckResult,
    ConsistencyChecks,
    ConsistencyReport,
    EventLog,
    FactCheck,
    Metrics,
    NodeState,
    NodeText,
    TextParagraph,
    TextSection,
    utc_now_iso,
)
from backend.repositories.event_log_repository import EventLogRepository
from backend.repositories.node_state_repository import NodeStateRepository
from backend.repositories.task_repository import TaskRepository


class NodeRunner:
    """Runs generation-unit nodes sequentially for one task."""

    def __init__(
        self,
        *,
        node_repository: NodeStateRepository,
        task_repository: TaskRepository,
        event_repository: EventLogRepository,
        artifacts_root: Path,
        template_path: Path,
    ) -> None:
        self.node_repository = node_repository
        self.task_repository = task_repository
        self.event_repository = event_repository
        self.artifacts_root = artifacts_root
        self.template_path = template_path

    def run_task(self, task_id: str) -> None:
        nodes = self.node_repository.list_by_task(task_id)
        if not nodes:
            self._log(task_id, stage="GENERATING", message="No generation nodes found.")
            return

        total_nodes = len(nodes)
        self.task_repository.update_progress(task_id, total_nodes=total_nodes, completed_nodes=0)

        for node in nodes:
            if node.status in {NodeStatus.NODE_DONE, NodeStatus.NODE_FAILED}:
                continue
            self._run_single_node(node)
            completed = self.node_repository.count_completed(task_id)
            task_progress = 0.2 + 0.7 * (completed / total_nodes)
            self.task_repository.update_progress(
                task_id,
                completed_nodes=completed,
                total_progress=round(task_progress, 4),
                current_stage="GENERATING",
                current_node_uid=node.node_uid,
            )
            self.task_repository.touch_heartbeat(
                task_id,
                stage="GENERATING",
                node_uid=node.node_uid,
            )

        completed_nodes = self.node_repository.count_completed(task_id)
        if completed_nodes != total_nodes:
            self.task_repository.update_status(
                task_id,
                TaskStatus.FAILED,
                current_stage="GENERATING",
                latest_error="At least one node did not finish.",
            )
            return

        self.task_repository.update_status(
            task_id,
            TaskStatus.LAYOUTING,
            current_stage="LAYOUTING",
        )
        self._log(task_id, stage="LAYOUTING", message="Layout skeleton finished.")

        output_path = self._export_output(task_id)
        self.task_repository.update_status(
            task_id,
            TaskStatus.EXPORTING,
            current_stage="EXPORTING",
        )
        self._log(
            task_id,
            stage="EXPORTING",
            message="Exported skeleton output file.",
            output_artifact_path=str(output_path),
        )

        self.task_repository.update_progress(
            task_id,
            completed_nodes=completed_nodes,
            total_progress=1.0,
            current_stage="DONE",
            current_node_uid=None,
        )
        self.task_repository.update_status(
            task_id,
            TaskStatus.DONE,
            current_stage="DONE",
            finished_at=utc_now_iso(),
        )
        self._log(task_id, stage="DONE", message="Task completed by skeleton worker.")

    def _run_single_node(self, node: NodeState) -> None:
        node_dir = self.artifacts_root / node.task_id / "nodes" / node.node_uid
        node_dir.mkdir(parents=True, exist_ok=True)

        self._set_node_stage(node, NodeStatus.TEXT_GENERATING, 0.10)
        text_artifact = self._write_text_artifact(node, node_dir)
        self._set_node_stage(
            node,
            NodeStatus.TEXT_DONE,
            0.20,
            output_artifact_path=str(text_artifact),
        )

        self._set_node_stage(node, NodeStatus.FACT_CHECKING, 0.25)
        fact_artifact = self._write_fact_check_artifact(node, node_dir)
        self._set_node_stage(
            node,
            NodeStatus.FACT_PASSED,
            0.30,
            output_artifact_path=str(fact_artifact),
        )

        # Image pipeline remains a stub in this skeleton.
        self._set_node_stage(node, NodeStatus.IMAGE_GENERATING, 0.45)
        images_artifact = self._write_stub_images_artifact(node, node_dir)
        self._set_node_stage(
            node,
            NodeStatus.IMAGE_DONE,
            0.55,
            output_artifact_path=str(images_artifact),
        )

        self._set_node_stage(node, NodeStatus.IMAGE_VERIFYING, 0.65)
        image_verify_artifact = self._write_stub_image_verify_artifact(node, node_dir)
        self._set_node_stage(
            node,
            NodeStatus.IMAGE_VERIFIED,
            0.75,
            output_artifact_path=str(image_verify_artifact),
        )

        self._set_node_stage(node, NodeStatus.LENGTH_CHECKING, 0.82)
        self._set_node_stage(node, NodeStatus.LENGTH_PASSED, 0.88)

        self._set_node_stage(node, NodeStatus.CONSISTENCY_CHECKING, 0.94)
        consistency_artifact = self._write_consistency_artifact(node, node_dir)
        self._set_node_stage(
            node,
            NodeStatus.READY_FOR_LAYOUT,
            0.97,
            output_artifact_path=str(consistency_artifact),
        )

        metrics_artifact = self._write_metrics_artifact(node, node_dir)
        self._set_node_stage(
            node,
            NodeStatus.LAYOUTED,
            0.99,
            output_artifact_path=str(metrics_artifact),
        )
        self._set_node_stage(
            node,
            NodeStatus.NODE_DONE,
            1.0,
            output_artifact_path=str(metrics_artifact),
            finished_at=utc_now_iso(),
        )

    def _set_node_stage(
        self,
        node: NodeState,
        status: NodeStatus,
        progress: float,
        *,
        output_artifact_path: str | None = None,
        finished_at: str | None = None,
    ) -> None:
        node.current_stage = status.value
        node.status = status
        node.progress = progress
        node.output_artifact_path = output_artifact_path
        node.finished_at = finished_at
        node.updated_at = utc_now_iso()
        node.last_heartbeat_at = utc_now_iso()

        self.node_repository.update_status(
            node.task_id,
            node.node_uid,
            status=status,
            progress=progress,
            current_stage=status.value,
            output_artifact_path=output_artifact_path,
            finished_at=finished_at,
        )
        self._log(
            node.task_id,
            node_uid=node.node_uid,
            stage=status.value,
            message=f"Node {node.node_id} -> {status.value}",
            output_artifact_path=output_artifact_path,
        )

    def _write_text_artifact(self, node: NodeState, node_dir: Path) -> Path:
        paragraph = (
            "This skeleton paragraph describes implementation steps, quality control, "
            "acceptance checks, and traceability records for this generation unit."
        )
        paragraphs = [
            TextParagraph(
                paragraph_id=f"p_{idx:02d}",
                text=paragraph,
                source_refs=[],
                claim_ids=[],
                anchors=["anchor_default"],
            )
            for idx in range(1, 8)
        ]
        artifact = NodeText(
            node_uid=node.node_uid,
            node_id=node.node_id,
            title=node.title,
            summary="Skeleton section generated by NodeRunner.",
            sections=[
                TextSection(
                    section_id="sec_01",
                    title="Implementation Skeleton",
                    paragraphs=paragraphs,
                )
            ],
            highlight_paragraphs=[],
            word_count=sum(len(item.text.split()) for item in paragraphs),
            version=1,
        )
        path = node_dir / "text.json"
        self._write_json(path, artifact.model_dump(mode="json"))
        return path

    def _write_fact_check_artifact(self, node: NodeState, node_dir: Path) -> Path:
        artifact = FactCheck(
            node_uid=node.node_uid,
            grounded_ratio=1.0,
            result=AgentResult.PASS,
            claims=[],
            unsupported_claims=[],
            weak_claims=[],
        )
        path = node_dir / "fact_check.json"
        self._write_json(path, artifact.model_dump(mode="json"))
        return path

    def _write_stub_images_artifact(self, node: NodeState, node_dir: Path) -> Path:
        path = node_dir / "images.json"
        self._write_json(path, {"node_uid": node.node_uid, "images": []})
        return path

    def _write_stub_image_verify_artifact(self, node: NodeState, node_dir: Path) -> Path:
        path = node_dir / "image_relevance.json"
        self._write_json(
            path,
            {
                "node_uid": node.node_uid,
                "image_scores": [],
                "overall_result": "PASS",
            },
        )
        return path

    def _write_consistency_artifact(self, node: NodeState, node_dir: Path) -> Path:
        artifact = ConsistencyReport(
            node_uid=node.node_uid,
            result=AgentResult.PASS,
            checks=ConsistencyChecks(
                entity_consistency=CheckResult(result=AgentResult.PASS, issues=[]),
                term_consistency=CheckResult(result=AgentResult.PASS, issues=[]),
                constraint_consistency=CheckResult(result=AgentResult.PASS, issues=[]),
                reference_consistency=CheckResult(result=AgentResult.PASS, issues=[]),
            ),
        )
        path = node_dir / "consistency.json"
        self._write_json(path, artifact.model_dump(mode="json"))
        return path

    def _write_metrics_artifact(self, node: NodeState, node_dir: Path) -> Path:
        artifact = Metrics(
            node_uid=node.node_uid,
            word_count=0,
            grounded_ratio=1.0,
            image_score_avg=1.0,
            image_retry_total=0,
            text_retry_total=0,
            fact_retry_total=0,
            duration_ms=0,
            final_status=NodeStatus.NODE_DONE,
        )
        path = node_dir / "metrics.json"
        self._write_json(path, artifact.model_dump(mode="json"))
        return path

    def _export_output(self, task_id: str) -> Path:
        output_dir = self.artifacts_root / task_id / "final"
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / "output.docx"
        if self.template_path.exists():
            shutil.copyfile(self.template_path, output_path)
        else:
            output_path.write_bytes(b"")
        return output_path

    @staticmethod
    def _write_json(path: Path, payload: dict) -> None:
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
