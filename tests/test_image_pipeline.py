from __future__ import annotations

import json
import shutil
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

from backend.agents.image_generation import ImageGenerationAgent
from backend.agents.image_prompt import ImagePromptAgent
from backend.models.enums import AgentResult, NodeStatus, TaskStatus
from backend.models.schemas import (
    EntityExtraction,
    EntityItem,
    FactCheck,
    ImagePromptItem,
    NodeState,
    NodeText,
    Task,
    TextParagraph,
    TextSection,
)
from backend.repositories.db import SQLiteDB
from backend.repositories.event_log_repository import EventLogRepository
from backend.repositories.node_state_repository import NodeStateRepository
from backend.repositories.task_repository import TaskRepository
from backend.worker.node_runner import NodeRunner


class ImagePipelineTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_root = Path(tempfile.mkdtemp(prefix="image_pipeline_test_", dir="/tmp"))
        self.db_path = self.temp_root / "app.db"
        self.artifacts_root = self.temp_root / "artifacts"
        self.db = SQLiteDB(self.db_path)
        self.db.initialize()

        self.task_repository = TaskRepository(self.db)
        self.node_repository = NodeStateRepository(self.db)
        self.event_repository = EventLogRepository(self.db)
        self.runner = NodeRunner(
            node_repository=self.node_repository,
            task_repository=self.task_repository,
            event_repository=self.event_repository,
            artifacts_root=self.artifacts_root,
            template_path=Path("templates/standard_template.docx"),
        )

        self.task_id = "task_image"
        self.node_uid = "uid_image_001"
        self.node_dir = self.artifacts_root / self.task_id / "nodes" / self.node_uid
        (self.node_dir / "checkpoints").mkdir(parents=True, exist_ok=True)
        (self.node_dir / "snapshots").mkdir(parents=True, exist_ok=True)

        self.task_repository.create(
            Task(
                task_id=self.task_id,
                title="图片流程测试",
                status=TaskStatus.GENERATING,
                current_stage="GENERATING",
            )
        )
        self.node_repository.upsert(
            NodeState(
                node_state_id=f"node_{uuid.uuid4().hex[:12]}",
                task_id=self.task_id,
                node_uid=self.node_uid,
                node_id="3.2.1",
                title="设备安装与验收",
                level=3,
                status=NodeStatus.FACT_PASSED,
                progress=0.35,
                current_stage=NodeStatus.FACT_PASSED.value,
            )
        )

        node_text = NodeText(
            node_uid=self.node_uid,
            node_id="3.2.1",
            title="设备安装与验收",
            summary="包含施工、设备和验收说明。",
            sections=[
                TextSection(
                    section_id="sec_01",
                    title="设备安装实施",
                    paragraphs=[
                        TextParagraph(
                            paragraph_id="p_01",
                            text="现场完成交换机和机柜安装部署，形成施工步骤和位置标注。",
                            anchors=["anchor_install"],
                        )
                    ],
                ),
                TextSection(
                    section_id="sec_02",
                    title="验收测试",
                    paragraphs=[
                        TextParagraph(
                            paragraph_id="p_02",
                            text="验收阶段需要保留测试记录、检查动作和结果确认。",
                            anchors=["anchor_acceptance"],
                        )
                    ],
                ),
            ],
            word_count=64,
        )
        (self.node_dir / "text.json").write_text(
            node_text.model_dump_json(indent=2),
            encoding="utf-8",
        )

        fact_check = FactCheck(
            node_uid=self.node_uid,
            grounded_ratio=1.0,
            result=AgentResult.PASS,
            claims=[],
            unsupported_claims=[],
            weak_claims=[],
        )
        (self.node_dir / "fact_check.json").write_text(
            fact_check.model_dump_json(indent=2),
            encoding="utf-8",
        )

    def tearDown(self) -> None:
        shutil.rmtree(self.temp_root)

    def test_image_pipeline_skips_image_relevance_stage(self) -> None:
        node = self.node_repository.get(self.task_id, self.node_uid)
        self.assertIsNotNone(node)
        assert node is not None

        generated = self.runner._execute_stage(
            node=node,
            node_dir=self.node_dir,
            stage_key="image_generate",
        )
        self.assertTrue(generated)

        self.assertTrue((self.node_dir / "entities.json").exists())
        self.assertTrue((self.node_dir / "image_prompts.json").exists())
        self.assertTrue((self.node_dir / "images.json").exists())
        self.assertFalse((self.node_dir / "image_relevance.json").exists())

        relevance_payload = json.loads(
            (self.node_dir / "images.json").read_text(encoding="utf-8")
        )
        self.assertGreaterEqual(len(relevance_payload["images"]), 1)

        stored = self.node_repository.get(self.task_id, self.node_uid)
        self.assertIsNotNone(stored)
        assert stored is not None
        self.assertEqual(stored.status, NodeStatus.IMAGE_DONE)
        self.assertFalse(stored.image_manual_required)
        self.assertEqual(stored.retry_image, 0)

        logs = self.event_repository.list_recent(self.task_id, limit=20, node_uid=self.node_uid)
        stages = {item.stage for item in logs}
        self.assertIn(NodeStatus.IMAGE_DONE.value, stages)
        self.assertNotIn("IMAGE_RETRY", stages)

    def test_image_pipeline_writes_empty_artifacts_when_generation_is_disabled(self) -> None:
        self.runner.system_config_getter = lambda: {
            "image_provider": "disabled",
            "image_model_name": "关闭图像生成",
            "image_api_key": "should-not-be-used",
        }
        node = self.node_repository.get(self.task_id, self.node_uid)
        self.assertIsNotNone(node)
        assert node is not None

        generated = self.runner._execute_stage(
            node=node,
            node_dir=self.node_dir,
            stage_key="image_generate",
        )
        self.assertTrue(generated)

        entities_payload = json.loads((self.node_dir / "entities.json").read_text(encoding="utf-8"))
        prompts_payload = json.loads((self.node_dir / "image_prompts.json").read_text(encoding="utf-8"))
        images_payload = json.loads((self.node_dir / "images.json").read_text(encoding="utf-8"))

        self.assertEqual(entities_payload["entities"], [])
        self.assertEqual(prompts_payload["prompts"], [])
        self.assertEqual(images_payload["images"], [])

        stored = self.node_repository.get(self.task_id, self.node_uid)
        self.assertIsNotNone(stored)
        assert stored is not None
        self.assertEqual(stored.status, NodeStatus.IMAGE_DONE)
        self.assertFalse(stored.image_manual_required)

        logs = self.event_repository.list_recent(self.task_id, limit=20, node_uid=self.node_uid)
        disabled_logs = [item for item in logs if item.stage == "IMAGE_PROVIDER"]
        self.assertTrue(disabled_logs)
        self.assertIn("disabled", json.dumps(disabled_logs[0].meta_json, ensure_ascii=False).lower())

    def test_legacy_image_verifying_status_resumes_from_length(self) -> None:
        self.assertEqual(
            self.runner._plan_stages(NodeStatus.IMAGE_VERIFYING),
            ["length", "consistency", "layout", "finalize"],
        )

    def test_image_generation_agent_uses_doubao_provider_when_selected(self) -> None:
        agent = ImageGenerationAgent()
        prompt = ImagePromptItem(
            prompt_id="prompt_001",
            image_type="process",
            prompt="生成一张工程流程示意图。",
            must_have_elements=["热泵机组", "控制柜"],
            forbidden_elements=["抽象科技光效"],
            bind_anchor="anchor_install",
            bind_section="设备安装实施",
        )
        node_dir = self.node_dir
        provider_config = {
            "image_provider": "doubao",
            "image_model_name": "Doubao-Seedream-4.5",
            "image_api_key": "test-ark-key",
        }

        def fake_generate(
            _self: ImageGenerationAgent,
            *,
            output_stem: Path,
            prompt_item: ImagePromptItem,
            provider_config: dict,
        ) -> Path:
            path = output_stem.with_suffix(".jpg")
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"fake-image-content")
            return path

        with patch.object(
            ImageGenerationAgent,
            "_generate_via_doubao",
            autospec=True,
            side_effect=fake_generate,
        ) as doubao_mock:
            item = agent.generate(
                prompt_item=prompt,
                node_dir=node_dir,
                retry_count=0,
                provider_config=provider_config,
            )

        generated_path = node_dir / item.file
        self.assertTrue(generated_path.exists())
        self.assertEqual(generated_path.read_bytes(), b"fake-image-content")
        doubao_mock.assert_called_once()

    def test_image_generation_agent_uses_minimax_provider_when_key_is_configured(self) -> None:
        agent = ImageGenerationAgent()
        prompt = ImagePromptItem(
            prompt_id="prompt_001",
            image_type="process",
            prompt="生成一张售后服务流程示意图。",
            style_preset="engineering_flow_diagram",
            style_variant="linear_operation_chain",
            aspect_ratio="2:1",
            must_have_elements=["控制柜", "监控平台"],
            forbidden_elements=["海报式大标题"],
            bind_anchor="anchor_install",
            bind_section="设备安装实施",
        )
        provider_config = {
            "image_provider": "minimax",
            "image_model_name": "MiniMax-M2.5",
            "image_api_key": "test-minimax-key",
        }

        def fake_request(_self: ImageGenerationAgent, *, api_key: str, payload: dict) -> str:
            self.assertEqual(api_key, "test-minimax-key")
            self.assertEqual(payload["model"], "image-01")
            self.assertEqual(payload["response_format"], "url")
            self.assertEqual(payload["aspect_ratio"], "16:9")
            self.assertEqual(payload["n"], 1)
            self.assertTrue(payload["prompt_optimizer"])
            return "https://example.com/minimax-generated.png"

        def fake_download(_self: ImageGenerationAgent, *, image_url: str, output_stem: Path) -> Path:
            self.assertEqual(image_url, "https://example.com/minimax-generated.png")
            path = output_stem.with_suffix(".png")
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"minimax-image-content")
            return path

        with patch.object(
            ImageGenerationAgent,
            "_request_minimax_image_url",
            autospec=True,
            side_effect=fake_request,
        ) as minimax_mock, patch.object(
            ImageGenerationAgent,
            "_download_image_url",
            autospec=True,
            side_effect=fake_download,
        ) as download_mock:
            item = agent.generate(
                prompt_item=prompt,
                node_dir=self.node_dir,
                retry_count=0,
                provider_config=provider_config,
            )

        generated_path = self.node_dir / item.file
        self.assertTrue(generated_path.exists())
        self.assertEqual(generated_path.read_bytes(), b"minimax-image-content")
        self.assertEqual(provider_config.get("_resolved_image_model_name"), "MiniMax-M2.5")
        self.assertEqual(provider_config.get("_resolved_image_model_id"), "image-01")
        self.assertEqual(provider_config.get("_image_model_attempts"), ["MiniMax-M2.5"])
        self.assertEqual(item.aspect_ratio, "2:1")
        self.assertEqual(item.style_preset, "engineering_flow_diagram")
        self.assertEqual(item.style_variant, "linear_operation_chain")
        minimax_mock.assert_called_once()
        download_mock.assert_called_once()

    def test_image_generation_agent_uses_placeholder_when_minimax_key_is_missing(self) -> None:
        agent = ImageGenerationAgent()
        prompt = ImagePromptItem(
            prompt_id="prompt_001",
            image_type="process",
            prompt="生成一张售后服务流程示意图。",
            must_have_elements=["控制柜", "监控平台"],
            forbidden_elements=["海报式大标题"],
            bind_anchor="anchor_install",
            bind_section="设备安装实施",
        )
        provider_config = {
            "image_provider": "minimax",
            "image_model_name": "MiniMax-M2.5",
            "image_api_key": "",
        }

        with patch.object(
            ImageGenerationAgent,
            "_generate_via_minimax",
            autospec=True,
            side_effect=AssertionError("minimax API should not run without key"),
        ):
            item = agent.generate(
                prompt_item=prompt,
                node_dir=self.node_dir,
                retry_count=0,
                provider_config=provider_config,
            )

        generated_path = self.node_dir / item.file
        self.assertTrue(generated_path.exists())
        self.assertEqual(generated_path.suffix, ".png")

    def test_image_generation_agent_auto_switches_doubao_model_after_error(self) -> None:
        agent = ImageGenerationAgent()
        prompt = ImagePromptItem(
            prompt_id="prompt_001",
            image_type="process",
            prompt="生成一张工程流程示意图。",
            must_have_elements=["热泵机组", "控制柜"],
            forbidden_elements=["抽象科技光效"],
            bind_anchor="anchor_install",
            bind_section="设备安装实施",
        )
        provider_config = {
            "image_provider": "doubao",
            "image_model_name": "Doubao-Seedream-5.0-lite",
            "image_api_key": "test-ark-key",
        }

        attempted_models: list[str] = []

        def fake_request(_self: ImageGenerationAgent, *, api_key: str, payload: dict) -> str:
            attempted_models.append(payload["model"])
            if payload["model"] == "doubao-seedream-5-0-lite":
                raise RuntimeError("model unavailable")
            return "https://example.com/generated.jpg"

        def fake_download(_self: ImageGenerationAgent, *, image_url: str, output_stem: Path) -> Path:
            path = output_stem.with_suffix(".jpg")
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"fallback-image-content")
            return path

        with patch.object(
            ImageGenerationAgent,
            "_request_doubao_image_url",
            autospec=True,
            side_effect=fake_request,
        ), patch.object(
            ImageGenerationAgent,
            "_download_image_url",
            autospec=True,
            side_effect=fake_download,
        ):
            item = agent.generate(
                prompt_item=prompt,
                node_dir=self.node_dir,
                retry_count=0,
                provider_config=provider_config,
            )

        self.assertEqual(
            attempted_models[:2],
            ["doubao-seedream-5-0-lite", "doubao-seedream-4-5-251128"],
        )
        self.assertEqual(
            provider_config.get("_resolved_image_model_name"),
            "Doubao-Seedream-4.5",
        )
        self.assertEqual(
            provider_config.get("_image_model_attempts"),
            ["Doubao-Seedream-5.0-lite", "Doubao-Seedream-4.5"],
        )
        self.assertTrue((self.node_dir / item.file).exists())

    def test_image_prompt_prefers_professional_engineering_visuals(self) -> None:
        agent = ImagePromptAgent()
        prompts = agent.build(
            entities=EntityExtraction(
                node_uid=self.node_uid,
                entities=[
                    EntityItem(
                        entity_id="ent_001",
                        name="热泵机组",
                        category="device",
                        must_have=True,
                    ),
                    EntityItem(
                        entity_id="ent_002",
                        name="循环水泵",
                        category="device",
                        must_have=True,
                    ),
                    EntityItem(
                        entity_id="ent_003",
                        name="管线连接关系",
                        category="topology",
                        must_have=True,
                    ),
                ],
            ),
            node_text=NodeText.model_validate_json((self.node_dir / "text.json").read_text(encoding="utf-8")),
        )

        first_prompt = prompts.prompts[0]
        prompt_text = first_prompt.prompt
        self.assertEqual(first_prompt.style_preset, "engineering_simulation_detail")
        self.assertIn(first_prompt.style_variant, {"system_overview", "equipment_cluster_focus", "control_loop_detail"})
        self.assertEqual(first_prompt.aspect_ratio, "2:1")
        self.assertIn("同组图片去相似化要求", prompt_text)
        self.assertIn("工程模拟细节动画图", prompt_text)
        self.assertIn("最终画幅必须是2:1横向长图", prompt_text)
        self.assertIn("视角与机位", prompt_text)
        self.assertIn("工程细节", prompt_text)
        self.assertIn("禁止任何大号标题字", prompt_text)
        self.assertIn("海报式排版", prompt_text)
        self.assertIn("No poster layout", prompt_text)
        self.assertIn("No large Chinese or English words", prompt_text)
        self.assertTrue(any(item.style_preset == "engineering_site_photo" for item in prompts.prompts))
        self.assertTrue(any(item.aspect_ratio == "3:2" for item in prompts.prompts))
        self.assertEqual(len({item.style_variant for item in prompts.prompts}), len(prompts.prompts))

    def test_image_prompt_chooses_network_diagnosis_style_for_network_context(self) -> None:
        agent = ImagePromptAgent()
        prompts = agent.build(
            entities=EntityExtraction(
                node_uid="uid_network",
                entities=[
                    EntityItem(
                        entity_id="ent_101",
                        name="工业交换机",
                        category="device",
                        must_have=True,
                    ),
                    EntityItem(
                        entity_id="ent_102",
                        name="光纤环网",
                        category="topology",
                        must_have=True,
                    ),
                    EntityItem(
                        entity_id="ent_103",
                        name="SCADA服务器",
                        category="device",
                        must_have=True,
                    ),
                ],
            ),
            node_text=NodeText(
                node_uid="uid_network",
                node_id="4.2.1",
                title="通信网络故障诊断与恢复",
                summary="覆盖交换机、光纤链路和网络节点状态诊断。",
                sections=[
                    TextSection(
                        section_id="sec_01",
                        title="网络节点状态诊断",
                        paragraphs=[
                            TextParagraph(
                                paragraph_id="p_01",
                                text="需要识别链路中断、交换机异常和通信延时，并给出定位建议。",
                                anchors=["anchor_network"],
                            )
                        ],
                    )
                ],
                word_count=36,
            ),
        )

        self.assertEqual(prompts.prompts[0].style_preset, "engineering_flow_diagram")
        self.assertEqual(prompts.prompts[0].style_variant, "hub_diagnosis_map")
        self.assertEqual(prompts.prompts[0].aspect_ratio, "2:1")
        self.assertIn("中心节点诊断图", prompts.prompts[0].prompt)
        self.assertIn("中心核心卡片加四周四个功能模块", prompts.prompts[0].prompt)

    def test_image_prompt_diversifies_site_photo_variants_within_same_node(self) -> None:
        agent = ImagePromptAgent()
        prompts = agent.build(
            entities=EntityExtraction(
                node_uid="uid_site",
                entities=[
                    EntityItem(
                        entity_id="ent_201",
                        name="控制柜",
                        category="device",
                        must_have=True,
                    ),
                    EntityItem(
                        entity_id="ent_202",
                        name="配电柜",
                        category="device",
                        must_have=True,
                    ),
                ],
            ),
            node_text=NodeText(
                node_uid="uid_site",
                node_id="5.1.2",
                title="机房控制柜安装调试与验收",
                summary="覆盖机房现场安装、调试、巡检和验收确认。",
                sections=[
                    TextSection(
                        section_id="sec_01",
                        title="现场安装",
                        paragraphs=[
                            TextParagraph(
                                paragraph_id="p_01",
                                text="机房现场完成成排控制柜就位和通道布置。",
                                anchors=["anchor_install"],
                            )
                        ],
                    ),
                    TextSection(
                        section_id="sec_02",
                        title="调试巡检",
                        paragraphs=[
                            TextParagraph(
                                paragraph_id="p_02",
                                text="调试期间对控制柜进行巡检、读表和确认。",
                                anchors=["anchor_inspect"],
                            )
                        ],
                    ),
                    TextSection(
                        section_id="sec_03",
                        title="验收确认",
                        paragraphs=[
                            TextParagraph(
                                paragraph_id="p_03",
                                text="验收阶段检查柜门、面板和铭牌区域。",
                                anchors=["anchor_accept"],
                            )
                        ],
                    ),
                ],
                word_count=42,
            ),
        )

        site_prompts = [item for item in prompts.prompts if item.style_preset == "engineering_site_photo"]
        self.assertGreaterEqual(len(site_prompts), 2)
        self.assertEqual(len({item.style_variant for item in site_prompts}), len(site_prompts))
        prompt_texts = "\n".join(item.prompt for item in site_prompts)
        self.assertIn("空旷通道广角", prompt_texts)
        self.assertIn("单人巡检斜角", prompt_texts)


if __name__ == "__main__":
    unittest.main()
