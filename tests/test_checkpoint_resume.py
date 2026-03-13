from __future__ import annotations

import json
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

from backend.models.enums import NodeStatus, TaskStatus
from backend.models.schemas import NodeState, NodeText, TOCDocument, TOCNode, Task, TextParagraph, TextSection
from backend.repositories.db import SQLiteDB
from backend.repositories.event_log_repository import EventLogRepository
from backend.repositories.node_state_repository import NodeStateRepository
from backend.repositories.task_repository import TaskRepository
from backend.worker.node_runner import NodeRunner
from tests.helpers import (
    cleanup_temp_root,
    make_temp_root,
    write_requirement_artifact,
    write_style_profile_artifact,
)


class CheckpointResumeTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_root = make_temp_root("checkpoint_resume_test_")
        self.db = SQLiteDB(self.temp_root / "app.db")
        self.db.initialize()
        self.artifacts_root = self.temp_root / "artifacts"

        self.task_repository = TaskRepository(self.db)
        self.node_repository = NodeStateRepository(self.db)
        self.event_repository = EventLogRepository(self.db)
        self.runner = NodeRunner(
            node_repository=self.node_repository,
            task_repository=self.task_repository,
            event_repository=self.event_repository,
            artifacts_root=self.artifacts_root,
            template_path=Path("templates/standard_template.docx"),
            system_config_getter=lambda: {
                "text_provider": "minimax",
                "text_model_name": "MiniMax-M2.5",
                "text_api_key": "fake-key",
            },
        )

        self.task_id = "task_resume"
        self.node_uid = "uid_resume_001"
        self.task_repository.create(
            Task(
                task_id=self.task_id,
                title="恢复测试任务",
                status=TaskStatus.GENERATING,
                current_stage="GENERATING",
                text_provider="minimax",
            )
        )
        self.node_repository.upsert(
            NodeState(
                node_state_id=f"node_{uuid.uuid4().hex[:12]}",
                task_id=self.task_id,
                node_uid=self.node_uid,
                node_id="1.1.1",
                title="视频监控子系统",
                level=3,
                status=NodeStatus.PENDING,
                progress=0.0,
                current_stage=NodeStatus.PENDING.value,
            )
        )
        write_requirement_artifact(self.artifacts_root, self.task_id)
        write_style_profile_artifact(self.artifacts_root, self.task_id)
        confirmed_toc = TOCDocument(
            version=1,
            based_on_version=None,
            tree=[
                TOCNode(
                    node_uid="uid_root_001",
                    node_id="",
                    level=0,
                    title="视频监控实施方案",
                    is_generation_unit=False,
                    children=[
                        TOCNode(
                            node_uid="uid_l1_scope",
                            node_id="1",
                            level=1,
                            title="建设范围",
                            is_generation_unit=False,
                            children=[
                                TOCNode(
                                    node_uid="uid_l2_scope",
                                    node_id="1.1",
                                    level=2,
                                    title="前端部署",
                                    is_generation_unit=False,
                                    children=[
                                        TOCNode(
                                            node_uid=self.node_uid,
                                            node_id="1.1.1",
                                            level=3,
                                            title="视频监控子系统",
                                            is_generation_unit=True,
                                            children=[],
                                        )
                                    ],
                                )
                            ],
                        )
                    ],
                )
            ],
        )
        toc_path = self.artifacts_root / self.task_id / "toc" / "toc_confirmed.json"
        toc_path.parent.mkdir(parents=True, exist_ok=True)
        toc_path.write_text(
            json.dumps(confirmed_toc.model_dump(mode="json"), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        self.node_dir = self.artifacts_root / self.task_id / "nodes" / self.node_uid
        (self.node_dir / "checkpoints").mkdir(parents=True, exist_ok=True)
        (self.node_dir / "snapshots").mkdir(parents=True, exist_ok=True)

    def tearDown(self) -> None:
        cleanup_temp_root(self.temp_root)

    def test_resume_continues_from_latest_stable_stage(self) -> None:
        node = self.node_repository.get(self.task_id, self.node_uid)
        self.assertIsNotNone(node)
        assert node is not None

        with patch.object(
            self.runner.section_writer,
            "generate",
            return_value=NodeText(
                node_uid=node.node_uid,
                node_id=node.node_id,
                title=node.title,
                summary="测试摘要",
                sections=[
                    TextSection(
                        section_id="sec_01",
                        title="实施要求",
                        paragraphs=[
                            TextParagraph(
                                paragraph_id="p_01",
                                text="视频监控子系统应完成部署与联调。",
                                source_refs=["p1#L1"],
                            )
                        ],
                    )
                ],
                word_count=16,
            ),
        ):
            first_stage_ok = self.runner._execute_stage(node=node, node_dir=self.node_dir, stage_key="text")
        self.assertTrue(first_stage_ok)
        self.assertTrue((self.node_dir / "checkpoints" / "text_done.json").exists())

        resumed_runner = NodeRunner(
            node_repository=self.node_repository,
            task_repository=self.task_repository,
            event_repository=self.event_repository,
            artifacts_root=self.artifacts_root,
            template_path=Path("templates/standard_template.docx"),
            system_config_getter=lambda: {
                "text_provider": "minimax",
                "text_model_name": "MiniMax-M2.5",
                "text_api_key": "fake-key",
            },
        )
        stored = self.node_repository.get(self.task_id, self.node_uid)
        self.assertEqual(stored.status, NodeStatus.TEXT_DONE)
        self.assertEqual(resumed_runner._plan_stages(stored.status)[0], "fact")

        resumed_runner._run_single_node(stored)

        finished = self.node_repository.get(self.task_id, self.node_uid)
        self.assertEqual(finished.status, NodeStatus.NODE_DONE)
        self.assertTrue((self.node_dir / "checkpoints" / "node_done.json").exists())

        logs = self.event_repository.list_recent(self.task_id, limit=200, node_uid=self.node_uid)
        text_done_logs = [item for item in logs if item.stage == NodeStatus.TEXT_DONE.value]
        resume_logs = [item for item in logs if item.stage == "NODE_RESUME"]
        self.assertEqual(len(text_done_logs), 1)
        self.assertTrue(any("TEXT_DONE" in item.message for item in resume_logs))

    def test_write_text_artifact_passes_confirmed_toc_to_section_writer(self) -> None:
        node = self.node_repository.get(self.task_id, self.node_uid)
        self.assertIsNotNone(node)
        assert node is not None
        captured: dict[str, object] = {}

        def _fake_generate(*, toc_document, **kwargs):
            captured["toc_document"] = toc_document
            return NodeText(
                node_uid=node.node_uid,
                node_id=node.node_id,
                title=node.title,
                summary="测试摘要",
                sections=[
                    TextSection(
                        section_id="sec_01",
                        title="实施要求",
                        paragraphs=[
                            TextParagraph(
                                paragraph_id="p_01",
                                text="视频监控子系统应完成部署与联调。",
                                source_refs=["p1#L1"],
                            )
                        ],
                    )
                ],
                word_count=16,
            )

        with patch.object(self.runner.section_writer, "generate", side_effect=_fake_generate):
            self.runner._write_text_artifact(node, self.node_dir)

        toc_document = captured.get("toc_document")
        self.assertIsNotNone(toc_document)
        assert isinstance(toc_document, TOCDocument)
        self.assertEqual(toc_document.tree[0].children[0].title, "建设范围")
        self.assertEqual(
            toc_document.tree[0].children[0].children[0].children[0].node_uid,
            self.node_uid,
        )

    def test_write_length_artifact_uses_section_writer_revision_for_short_text(self) -> None:
        node = self.node_repository.get(self.task_id, self.node_uid)
        self.assertIsNotNone(node)
        assert node is not None

        short_text = NodeText(
            node_uid=node.node_uid,
            node_id=node.node_id,
            title=node.title,
            summary="测试摘要",
            sections=[
                TextSection(
                    section_id="sec_01",
                    title="实施要求",
                    paragraphs=[
                        TextParagraph(
                            paragraph_id="p_01",
                            text="视频监控子系统应完成部署与联调。",
                            source_refs=["p1#L1"],
                        )
                    ],
                )
            ],
            word_count=16,
        )
        (self.node_dir / "text.json").write_text(
            json.dumps(short_text.model_dump(mode="json"), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        revised_text = NodeText(
            node_uid=node.node_uid,
            node_id=node.node_id,
            title=node.title,
            summary="测试摘要",
            sections=[
                TextSection(
                    section_id="sec_01",
                    title="实施要求",
                    paragraphs=[
                        TextParagraph(
                            paragraph_id="p_01",
                            text="视频监控子系统应完成前端部署、链路联调和平台接入，并依据招标文件要求组织实施和复核。" * 30,
                            source_refs=["p1#L1"],
                        ),
                        TextParagraph(
                            paragraph_id="p_02",
                            text="施工过程应符合GB50348，验收阶段应形成记录并完成签认，相关资料应按原文要求整理归档。" * 22,
                            source_refs=["p1#L2", "p1#L3"],
                        ),
                    ],
                )
            ],
            word_count=0,
        )

        with patch.object(self.runner.section_writer, "revise_for_length", return_value=revised_text) as mocked:
            artifact_path = self.runner._write_length_artifact(node, self.node_dir)

        mocked.assert_called_once()
        self.assertTrue(artifact_path.exists())
        updated = NodeText.model_validate(
            json.loads((self.node_dir / "text.json").read_text(encoding="utf-8"))
        )
        self.assertGreaterEqual(updated.word_count, 1950)
        self.assertLessEqual(updated.word_count, 2050)

    def test_write_length_artifact_continues_with_risk_when_text_stays_short(self) -> None:
        node = self.node_repository.get(self.task_id, self.node_uid)
        self.assertIsNotNone(node)
        assert node is not None

        short_text = NodeText(
            node_uid=node.node_uid,
            node_id=node.node_id,
            title=node.title,
            summary="测试摘要",
            sections=[
                TextSection(
                    section_id="sec_01",
                    title="实施要求",
                    paragraphs=[
                        TextParagraph(
                            paragraph_id="p_01",
                            text="视频监控子系统应完成部署与联调。",
                            source_refs=["p1#L1"],
                        )
                    ],
                )
            ],
            word_count=16,
        )
        (self.node_dir / "text.json").write_text(
            json.dumps(short_text.model_dump(mode="json"), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        with patch.object(self.runner.section_writer, "revise_for_length", return_value=short_text):
            artifact_path = self.runner._write_length_artifact(node, self.node_dir)

        self.assertTrue(artifact_path.exists())
        payload = json.loads(artifact_path.read_text(encoding="utf-8"))
        self.assertEqual(payload["result"], "FAIL")
        self.assertTrue(payload["lenient_pass"])

        logs = self.event_repository.list_recent(self.task_id, limit=20, node_uid=self.node_uid)
        self.assertTrue(any(item.stage == "LENGTH_RISK" for item in logs))

    def test_run_generation_recovers_previous_length_failed_node(self) -> None:
        node = self.node_repository.get(self.task_id, self.node_uid)
        self.assertIsNotNone(node)
        assert node is not None

        self.node_repository.update_status(
            self.task_id,
            self.node_uid,
            status=NodeStatus.NODE_FAILED,
            progress=0.76,
            current_stage=NodeStatus.NODE_FAILED.value,
            last_error="Length control failed: after_word_count=1664",
            finished_at="2026-03-13T00:00:00+00:00",
        )
        (self.node_dir / "text.json").write_text(
            json.dumps(
                NodeText(
                    node_uid=node.node_uid,
                    node_id=node.node_id,
                    title=node.title,
                    summary="测试摘要",
                    sections=[
                        TextSection(
                            section_id="sec_01",
                            title="实施要求",
                            paragraphs=[
                                TextParagraph(
                                    paragraph_id="p_01",
                                    text="视频监控子系统应完成前端部署、链路联调和平台接入，并依据招标文件要求组织实施和复核。" * 28,
                                    source_refs=["p1#L1"],
                                )
                            ],
                        )
                    ],
                    word_count=0,
                ).model_dump(mode="json"),
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        (self.node_dir / "images.json").write_text(
            json.dumps({"node_uid": node.node_uid, "images": []}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        summary = self.runner.run_generation(self.task_id)

        self.assertEqual(summary.failed_nodes, 0)
        recovered = self.node_repository.get(self.task_id, self.node_uid)
        self.assertIsNotNone(recovered)
        assert recovered is not None
        self.assertEqual(recovered.status, NodeStatus.NODE_DONE)

        logs = self.event_repository.list_recent(self.task_id, limit=50, node_uid=self.node_uid)
        self.assertTrue(any(item.stage == "LENGTH_RECOVER" for item in logs))


if __name__ == "__main__":
    unittest.main()
