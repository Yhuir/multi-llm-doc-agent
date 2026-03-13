from __future__ import annotations

import json
import unittest
from unittest.mock import patch

from backend.agents.length_control import LengthControlAgent
from backend.agents.section_writer import SectionWriterAgent
from backend.models.enums import ManualActionStatus, NodeStatus
from backend.models.schemas import (
    NodeText,
    NodeState,
    RequirementConstraints,
    RequirementDocument,
    RequirementItem,
    RequirementProject,
    RequirementScope,
    SourceIndexItem,
    TOCDocument,
    TOCNode,
    TextParagraph,
    TextSection,
)


class LengthControlAgentTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.agent = LengthControlAgent()
        self.section_writer = SectionWriterAgent()
        self.requirement = RequirementDocument(
            project=RequirementProject(name="动力系统升级项目"),
            scope=RequirementScope(overview="售后服务实施要求"),
            constraints=RequirementConstraints(
                standards=["GB50348", "GB50617"],
                acceptance=["完成试运行", "提交验收资料"],
            ),
            bidding_requirements=[
                RequirementItem(
                    type="service",
                    key="service_close_loop",
                    value="售后服务应形成闭环。",
                    source_ref="p1#L1",
                ),
                RequirementItem(
                    type="acceptance",
                    key="debug_record",
                    value="调试过程应记录。",
                    source_ref="p2#L2",
                ),
            ],
            source_index={
                "p1#L1": SourceIndexItem(page=1, paragraph_id="p1", text="售后服务应形成闭环。"),
                "p2#L2": SourceIndexItem(page=1, paragraph_id="p2", text="调试过程应记录。"),
            },
        )
        self.generation_config = {
            "text_provider": "minimax",
            "text_model_name": "MiniMax-M2.5",
            "text_api_key": "fake-key",
        }

    def _model_output(self, *, heading: str = "实施组织要求", paragraph: str = "售后服务应形成闭环管理并保留过程记录。") -> str:
        return json.dumps(
            {
                "summary": "根据招标要求形成实施正文。",
                "sections": [
                    {
                        "title": heading,
                        "paragraphs": [
                            {"text": paragraph, "source_refs": ["p1#L1"]},
                            {"text": "调试过程应记录并完成交接。", "source_refs": ["p2#L2"]},
                        ],
                    }
                ],
                "highlight_paragraphs": ["关键实施过程必须形成留痕记录。"],
            },
            ensure_ascii=False,
        )

    def _repeat_to_length(self, text: str, target_words: int) -> str:
        repeat = max(1, (target_words // max(1, len(text))) + 2)
        return (text * repeat)[:target_words]

    def _model_output_for_target(self, target_words: int, *, heading: str = "实施组织要求") -> str:
        paragraph_a = self._repeat_to_length(
            "售后服务应形成闭环管理并保留过程记录，确保每项服务动作均可追溯。",
            max(60, target_words // 2),
        )
        paragraph_b = self._repeat_to_length(
            "调试过程应记录并完成交接，验收资料应依据原文要求整理归档。",
            max(60, target_words - len(paragraph_a)),
        )
        return json.dumps(
            {
                "summary": "根据招标要求形成实施正文。",
                "sections": [
                    {
                        "title": heading,
                        "paragraphs": [
                            {"text": paragraph_a, "source_refs": ["p1#L1"]},
                            {"text": paragraph_b, "source_refs": ["p2#L2"]},
                        ],
                    }
                ],
                "highlight_paragraphs": ["关键实施过程必须形成留痕记录。"],
            },
            ensure_ascii=False,
        )

    def _confirmed_toc(self, *, node_uid: str, node_title: str) -> TOCDocument:
        return TOCDocument(
            version=1,
            based_on_version=None,
            tree=[
                TOCNode(
                    node_uid="uid_root_001",
                    node_id="",
                    level=0,
                    title="售后服务实施方案",
                    is_generation_unit=False,
                    children=[
                        TOCNode(
                            node_uid="uid_l1_service",
                            node_id="1",
                            level=1,
                            title="售后服务方案",
                            is_generation_unit=False,
                            children=[
                                TOCNode(
                                    node_uid="uid_l2_service",
                                    node_id="1.1",
                                    level=2,
                                    title="服务内容",
                                    is_generation_unit=False,
                                    children=[
                                        TOCNode(
                                            node_uid=node_uid,
                                            node_id="1.1.1",
                                            level=3,
                                            title=node_title,
                                            is_generation_unit=True,
                                            children=[],
                                        ),
                                        TOCNode(
                                            node_uid="uid_sibling_training",
                                            node_id="1.1.2",
                                            level=3,
                                            title="培训组织要求",
                                            is_generation_unit=True,
                                            children=[],
                                        ),
                                    ],
                                )
                            ],
                        ),
                        TOCNode(
                            node_uid="uid_l1_emergency",
                            node_id="2",
                            level=1,
                            title="应急响应",
                            is_generation_unit=False,
                            children=[
                                TOCNode(
                                    node_uid="uid_l2_emergency",
                                    node_id="2.1",
                                    level=2,
                                    title="响应机制",
                                    is_generation_unit=False,
                                    children=[
                                        TOCNode(
                                            node_uid="uid_l3_emergency",
                                            node_id="2.1.1",
                                            level=3,
                                            title="远程诊断与现场联动",
                                            is_generation_unit=True,
                                            children=[],
                                        )
                                    ],
                                )
                            ],
                        ),
                    ],
                )
            ],
        )

    def test_control_marks_short_text_for_llm_revision_without_local_fill(self) -> None:
        node_text = NodeText(
            node_uid="uid_test_length",
            node_id="1.1.1",
            title="售后服务要求",
            summary="测试节点",
            sections=[
                TextSection(
                    section_id="sec_01",
                    title="实施要求",
                    paragraphs=[
                        TextParagraph(
                            paragraph_id="p_01",
                            text="售后服务应形成闭环管理。",
                            source_refs=["p1#L1"],
                            claim_ids=["claim_01"],
                            anchors=["anchor_01"],
                        )
                    ],
                )
            ],
            word_count=len("售后服务应形成闭环管理。"),
        )

        controlled, details = self.agent.control(
            node_text=node_text,
            requirement=self.requirement,
            min_words=1950,
            max_words=2050,
            max_expand_rounds=0,
        )

        self.assertEqual(details["result"], "FAIL")
        self.assertTrue(details["needs_llm_revision"])
        self.assertEqual(details["action"], "EXPAND_REQUIRED")
        self.assertFalse(details["forced_fill"])
        self.assertEqual(controlled.sections[0].paragraphs[0].text, "售后服务应形成闭环管理")
        self.assertEqual(len(controlled.sections[0].paragraphs), 1)

    def test_control_trims_overlong_text_without_falling_below_minimum(self) -> None:
        long_text = NodeText(
            node_uid="uid_trim_length",
            node_id="1.1.2",
            title="技术要求说明",
            summary="测试节点",
            sections=[
                TextSection(
                    section_id="sec_01",
                    title="实施要求",
                    paragraphs=[
                        TextParagraph(
                            paragraph_id="p_01",
                            text="甲" * 1783,
                            source_refs=["p1#L1"],
                            claim_ids=["claim_01"],
                            anchors=["anchor_01"],
                        ),
                        TextParagraph(
                            paragraph_id="p_02",
                            text="乙" * 781,
                            source_refs=["p1#L1"],
                            claim_ids=["claim_02"],
                            anchors=["anchor_02"],
                        ),
                    ],
                )
            ],
            word_count=2564,
        )

        controlled, details = self.agent.control(
            node_text=long_text,
            requirement=self.requirement,
            min_words=1950,
            max_words=2050,
            max_expand_rounds=2,
        )

        self.assertEqual(details["result"], "PASS")
        self.assertGreaterEqual(controlled.word_count, 1950)
        self.assertLessEqual(controlled.word_count, 2050)
        self.assertEqual(details["action"], "TRIM")

    def test_section_writer_length_revision_hits_requested_target_ranges(self) -> None:
        short_output = self._model_output_for_target(120)
        for target_words in (500, 1000, 10000):
            with self.subTest(target_words=target_words):
                node = NodeState(
                    node_state_id=f"state_{target_words}",
                    task_id="task_test",
                    node_uid=f"uid_{target_words}",
                    node_id="1.1.1",
                    title="售后服务响应要求",
                    level=3,
                    status=NodeStatus.PENDING,
                    manual_action_status=ManualActionStatus.NONE,
                )
                with patch.object(
                    SectionWriterAgent,
                    "_request_minimax_completion",
                    return_value=short_output,
                ):
                    generated = self.section_writer.generate(
                        node=node,
                        requirement=self.requirement,
                        toc_document=self._confirmed_toc(node_uid=node.node_uid, node_title=node.title),
                        target_words=target_words,
                        generation_config=self.generation_config,
                    )

                controlled, details = self.agent.control(
                    node_text=generated,
                    requirement=self.requirement,
                    min_words=max(1, target_words - 50),
                    max_words=target_words + 50,
                    max_expand_rounds=4,
                )
                self.assertEqual(details["result"], "FAIL")
                self.assertTrue(details["needs_llm_revision"])

                with patch.object(
                    SectionWriterAgent,
                    "_request_minimax_completion",
                    return_value=self._model_output_for_target(target_words),
                ):
                    revised = self.section_writer.revise_for_length(
                        node_text=controlled,
                        requirement=self.requirement,
                        toc_document=self._confirmed_toc(node_uid=node.node_uid, node_title=node.title),
                        min_words=max(1, target_words - 50),
                        max_words=target_words + 50,
                        generation_config=self.generation_config,
                    )
                controlled, details = self.agent.control(
                    node_text=revised,
                    requirement=self.requirement,
                    min_words=max(1, target_words - 50),
                    max_words=target_words + 50,
                    max_expand_rounds=4,
                )

                self.assertEqual(details["result"], "PASS")
                self.assertGreaterEqual(controlled.word_count, max(1, target_words - 50))
                self.assertLessEqual(controlled.word_count, target_words + 50)

    def test_section_writer_uses_full_requirement_prompt_and_model_output(self) -> None:
        node = NodeState(
            node_state_id="state_clean",
            task_id="task_test",
            node_uid="uid_clean",
            node_id="1.1.1",
            title="10kV配电监控系统集成所需的设备采购清单（包含但不限于）",
            level=3,
            status=NodeStatus.PENDING,
            manual_action_status=ManualActionStatus.NONE,
        )
        dirty_requirement = self.requirement.model_copy(deep=True)
        dirty_requirement.project.name = "动力项目版权属于烟厂"
        dirty_requirement.source_index["p9#L9"] = SourceIndexItem(
            page=2,
            paragraph_id="p9",
            text="第9段：10kV配电监控系统集成所需的设备采购清单应结合招标范围组织交付。",
        )
        with patch.object(
            SectionWriterAgent,
            "_request_minimax_completion",
            return_value=self._model_output(
                heading="供货边界与交付控制",
                paragraph="版权属于烟厂。，确保交付边界与过程留痕。",
            ),
        ) as mocked:
            generated = self.section_writer.generate(
                node=node,
                requirement=dirty_requirement,
                toc_document=self._confirmed_toc(node_uid=node.node_uid, node_title=node.title),
                target_words=1000,
                generation_config=self.generation_config,
            )

        self.assertEqual([section.title for section in generated.sections], ["供货边界与交付控制"])
        merged = "".join(
            paragraph.text
            for section in generated.sections
            for paragraph in section.paragraphs
        )
        self.assertNotIn("。，", merged)
        self.assertNotIn("版权属于烟厂", merged)
        self.assertEqual(generated.sections[0].paragraphs[0].source_refs, ["p1#L1"])
        prompt = mocked.call_args.kwargs["prompt"]
        self.assertIn("第9段：10kV配电监控系统集成所需的设备采购清单应结合招标范围组织交付。", prompt)
        self.assertIn("全文解析内容（必须完整阅读）", prompt)
        self.assertIn("确认目录树上下文（必须与全文 requirement 一起使用）", prompt)
        self.assertIn("当前节点目录路径：1 售后服务方案 > 1.1 服务内容 > 1.1.1 10kV配电监控系统集成所需的设备采购清单（包含但不限于）", prompt)
        self.assertIn("当前节点同级章节：1.1.2 培训组织要求", prompt)
        self.assertIn("确认目录树总览：", prompt)
        self.assertIn("- 2 应急响应", prompt)
        self.assertIn("如果全文解析内容没有明确依据，就不要写入正文", prompt)
        self.assertNotIn("只能写成一般工程措施", prompt)
        self.assertNotIn("允许保留 general engineering knowledge", prompt)

    def test_section_writer_supports_whatai_text_provider(self) -> None:
        node = NodeState(
            node_state_id="state_whatai",
            task_id="task_test",
            node_uid="uid_whatai",
            node_id="1.1.1",
            title="售后服务响应要求",
            level=3,
            status=NodeStatus.PENDING,
            manual_action_status=ManualActionStatus.NONE,
        )

        with patch.object(
            SectionWriterAgent,
            "_request_whatai_completion",
            return_value=self._model_output(heading="服务响应与闭环控制"),
        ) as mocked:
            generated = self.section_writer.generate(
                node=node,
                requirement=self.requirement,
                toc_document=self._confirmed_toc(node_uid=node.node_uid, node_title=node.title),
                target_words=800,
                generation_config={
                    "text_provider": "whatai",
                    "text_model_name": "gemini-3.1-pro-preview",
                    "text_api_key": "fake-whatai-key",
                },
            )

        mocked.assert_called_once()
        self.assertEqual(generated.sections[0].title, "服务响应与闭环控制")

    def test_section_writer_requires_model_generated_summary(self) -> None:
        node = NodeState(
            node_state_id="state_no_summary",
            task_id="task_test",
            node_uid="uid_no_summary",
            node_id="1.1.1",
            title="售后服务响应要求",
            level=3,
            status=NodeStatus.PENDING,
            manual_action_status=ManualActionStatus.NONE,
        )
        missing_summary_output = json.dumps(
            {
                "sections": [
                    {
                        "title": "服务响应要求",
                        "paragraphs": [
                            {
                                "text": "售后服务应形成闭环管理并保留过程记录。",
                                "source_refs": ["p1#L1"],
                            }
                        ],
                    }
                ],
                "highlight_paragraphs": [],
            },
            ensure_ascii=False,
        )

        with patch.object(
            SectionWriterAgent,
            "_request_minimax_completion",
            return_value=missing_summary_output,
        ):
            with self.assertRaisesRegex(ValueError, "valid summary"):
                self.section_writer.generate(
                    node=node,
                    requirement=self.requirement,
                    toc_document=self._confirmed_toc(node_uid=node.node_uid, node_title=node.title),
                    target_words=800,
                    generation_config=self.generation_config,
                )


if __name__ == "__main__":
    unittest.main()
