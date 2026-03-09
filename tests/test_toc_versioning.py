from __future__ import annotations

import unittest
from unittest.mock import patch

from backend.agents.toc_review.agent import TOCReviewChatAgent
from backend.app_service.task_service import TaskService
from backend.models.schemas import TOCDocument, TOCNode
from tests.helpers import build_settings, cleanup_temp_root, create_sample_docx, make_temp_root


class TOCReviewAgentTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.agent = TOCReviewChatAgent()

    def test_review_applies_rename_add_remove_and_move(self) -> None:
        toc = TOCDocument(
            version=1,
            tree=[
                TOCNode(
                    node_uid="uid_root_001",
                    node_id="1",
                    level=1,
                    title="工程实施方案",
                    children=[
                        TOCNode(
                            node_uid="uid_l2_a",
                            node_id="1.1",
                            level=2,
                            title="项目理解与建设目标",
                            children=[
                                TOCNode(
                                    node_uid="uid_l3_a1",
                                    node_id="1.1.1",
                                    level=3,
                                    title="项目背景与建设范围",
                                    is_generation_unit=True,
                                    constraints={"min_words": 1800},
                                    children=[],
                                ),
                                TOCNode(
                                    node_uid="uid_l3_a2",
                                    node_id="1.1.2",
                                    level=3,
                                    title="建设目标",
                                    is_generation_unit=True,
                                    constraints={"min_words": 1800},
                                    children=[],
                                ),
                                TOCNode(
                                    node_uid="uid_l3_a3",
                                    node_id="1.1.3",
                                    level=3,
                                    title="项目实施边界",
                                    is_generation_unit=True,
                                    constraints={"min_words": 1800},
                                    children=[],
                                ),
                                TOCNode(
                                    node_uid="uid_l3_a4",
                                    node_id="1.1.4",
                                    level=3,
                                    title="对招标需求的响应说明",
                                    is_generation_unit=True,
                                    constraints={"min_words": 1800},
                                    children=[],
                                ),
                            ],
                        )
                    ],
                )
            ],
        )

        reviewed = self.agent.review(
            toc_doc=toc,
            feedback=(
                "把“建设目标”改成“建设目标与实施目标”；"
                "在“项目理解与建设目标”下新增“项目风险识别”；"
                "删除“对招标需求的响应说明”；"
                "将“项目实施边界”移动到“建设目标与实施目标”后面"
            ),
        )

        chapter = reviewed.tree[0].children[0]
        titles = [item.title for item in chapter.children]
        self.assertEqual(
            titles,
            [
                "项目背景与建设范围",
                "建设目标与实施目标",
                "项目实施边界",
                "项目风险识别",
            ],
        )
        renamed = chapter.children[1]
        added = chapter.children[-1]
        self.assertEqual(renamed.node_uid, "uid_l3_a2")
        self.assertTrue(added.node_uid.startswith("uid_l3_"))
        self.assertTrue(added.is_generation_unit)

    def test_review_can_apply_model_planned_actions(self) -> None:
        toc = TOCDocument(
            version=1,
            tree=[
                TOCNode(
                    node_uid="uid_root_001",
                    node_id="1",
                    level=1,
                    title="工程实施方案",
                    children=[
                        TOCNode(
                            node_uid="uid_l2_a",
                            node_id="1.1",
                            level=2,
                            title="项目理解与建设目标",
                            children=[
                                TOCNode(
                                    node_uid="uid_l3_a1",
                                    node_id="1.1.1",
                                    level=3,
                                    title="项目背景与建设范围",
                                    is_generation_unit=True,
                                    constraints={"min_words": 1800},
                                    children=[],
                                ),
                                TOCNode(
                                    node_uid="uid_l3_a2",
                                    node_id="1.1.2",
                                    level=3,
                                    title="建设目标",
                                    is_generation_unit=True,
                                    constraints={"min_words": 1800},
                                    children=[],
                                ),
                            ],
                        )
                    ],
                )
            ],
        )

        planned_actions = [
            {"type": "rename", "target": "建设目标", "new_title": "建设目标与成效指标"},
            {"type": "add_after", "reference": "建设目标与成效指标", "title": "项目风险识别"},
        ]
        with patch.object(self.agent, "_plan_actions_with_model", return_value=planned_actions):
            reviewed = self.agent.review(
                toc_doc=toc,
                feedback="请按建议修订目录",
                review_config={
                    "text_provider": "minimax",
                    "text_model_name": "MiniMax-M2.5",
                    "text_api_key": "fake-key",
                },
            )

        titles = [item.title for item in reviewed.tree[0].children[0].children]
        self.assertEqual(
            titles,
            ["项目背景与建设范围", "建设目标与成效指标", "项目风险识别"],
        )

    def test_review_can_keep_only_selected_branch(self) -> None:
        toc = TOCDocument(
            version=1,
            tree=[
                TOCNode(
                    node_uid="uid_root_001",
                    node_id="1",
                    level=1,
                    title="工程实施方案",
                    children=[
                        TOCNode(
                            node_uid="uid_l2_1",
                            node_id="1.1",
                            level=2,
                            title="第一章",
                            children=[
                                TOCNode(
                                    node_uid="uid_l3_1",
                                    node_id="1.1.1",
                                    level=3,
                                    title="甲",
                                    is_generation_unit=True,
                                    constraints={"min_words": 1800},
                                    children=[],
                                ),
                            ],
                        ),
                        TOCNode(
                            node_uid="uid_l2_2",
                            node_id="1.2",
                            level=2,
                            title="第二章",
                            children=[
                                TOCNode(
                                    node_uid="uid_l3_21",
                                    node_id="1.2.1",
                                    level=3,
                                    title="新建系统范围",
                                    children=[
                                        TOCNode(
                                            node_uid="uid_l4_211",
                                            node_id="1.2.1.1",
                                            level=4,
                                            title="空压机余热回收系统",
                                            is_generation_unit=True,
                                            constraints={"min_words": 1800},
                                            children=[],
                                        ),
                                        TOCNode(
                                            node_uid="uid_l4_212",
                                            node_id="1.2.1.2",
                                            level=4,
                                            title="乏汽余热回收系统",
                                            is_generation_unit=True,
                                            constraints={"min_words": 1800},
                                            children=[],
                                        ),
                                    ],
                                ),
                                TOCNode(
                                    node_uid="uid_l3_22",
                                    node_id="1.2.2",
                                    level=3,
                                    title="更新改造范围",
                                    is_generation_unit=True,
                                    constraints={"min_words": 1800},
                                    children=[],
                                ),
                            ],
                        ),
                    ],
                )
            ],
        )

        planned_actions = [
            {
                "type": "keep_only",
                "targets": ["1.2.1", "1.2.1.1", "1.2.1.2"],
                "include_descendants": False,
            }
        ]
        with patch.object(self.agent, "_plan_actions_with_model", return_value=planned_actions):
            reviewed = self.agent.review(
                toc_doc=toc,
                feedback="仅保留新建系统范围及其两个子项，删除其他",
                review_config={
                    "text_provider": "minimax",
                    "text_model_name": "MiniMax-M2.5",
                    "text_api_key": "fake-key",
                },
            )

        root_children = reviewed.tree[0].children
        self.assertEqual(len(root_children), 1)
        self.assertEqual(root_children[0].title, "第二章")
        section_titles = [item.title for item in root_children[0].children]
        self.assertEqual(section_titles, ["新建系统范围"])
        leaf_titles = [item.title for item in root_children[0].children[0].children]
        self.assertEqual(leaf_titles, ["空压机余热回收系统", "乏汽余热回收系统"])

    def test_explicit_keep_only_feedback_skips_model_planning(self) -> None:
        toc = TOCDocument(
            version=1,
            tree=[
                TOCNode(
                    node_uid="uid_root_001",
                    node_id="1",
                    level=1,
                    title="工程实施方案",
                    children=[
                        TOCNode(
                            node_uid="uid_l2_2",
                            node_id="1.2",
                            level=2,
                            title="项目建设内容总述",
                            children=[
                                TOCNode(
                                    node_uid="uid_l3_23",
                                    node_id="1.2.3",
                                    level=3,
                                    title="新增设备与主要配置",
                                    children=[
                                        TOCNode(
                                            node_uid="uid_l4_231",
                                            node_id="1.2.3.1",
                                            level=4,
                                            title="热泵、换热器与储能装置配置",
                                            is_generation_unit=True,
                                            constraints={"min_words": 1800},
                                            children=[],
                                        ),
                                        TOCNode(
                                            node_uid="uid_l4_232",
                                            node_id="1.2.3.2",
                                            level=4,
                                            title="循环水泵与阀门仪表配置",
                                            is_generation_unit=True,
                                            constraints={"min_words": 1800},
                                            children=[],
                                        ),
                                        TOCNode(
                                            node_uid="uid_l4_233",
                                            node_id="1.2.3.3",
                                            level=4,
                                            title="配套电控及线缆桥架配置",
                                            is_generation_unit=True,
                                            constraints={"min_words": 1800},
                                            children=[],
                                        ),
                                    ],
                                ),
                                TOCNode(
                                    node_uid="uid_l3_22",
                                    node_id="1.2.2",
                                    level=3,
                                    title="更新改造范围",
                                    is_generation_unit=True,
                                    constraints={"min_words": 1800},
                                    children=[],
                                ),
                            ],
                        )
                    ],
                )
            ],
        )

        feedback = (
            "2.3 新增设备与主要配置\n"
            "2.3.1 热泵、换热器与储能装置配置 生成单元\n"
            "2.3.2 循环水泵与阀门仪表配置 生成单元\n"
            "2.3.3 配套电控及线缆桥架配置 生成单元\n"
            "仅保留以上目录， 删除其他"
        )

        with patch.object(
            self.agent,
            "_plan_actions_with_model",
            side_effect=AssertionError("explicit keep_only should bypass model planning"),
        ):
            reviewed = self.agent.review(
                toc_doc=toc,
                feedback=feedback,
                review_config={
                    "text_provider": "minimax",
                    "text_model_name": "MiniMax-M2.5",
                    "text_api_key": "fake-key",
                },
            )

        root_children = reviewed.tree[0].children
        self.assertEqual(len(root_children), 1)
        self.assertEqual(root_children[0].title, "项目建设内容总述")
        branch = root_children[0].children
        self.assertEqual(len(branch), 1)
        self.assertEqual(branch[0].title, "新增设备与主要配置")
        self.assertEqual(
            [item.title for item in branch[0].children],
            ["热泵、换热器与储能装置配置", "循环水泵与阀门仪表配置", "配套电控及线缆桥架配置"],
        )


class TOCVersioningTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_root = make_temp_root("toc_version_test_")
        self.settings = build_settings(self.temp_root)
        self.service = TaskService(settings=self.settings)

    def tearDown(self) -> None:
        cleanup_temp_root(self.temp_root)

    def test_review_creates_new_version_and_preserves_old_version(self) -> None:
        task = self.service.create_task("目录版本化测试")
        sample_docx = create_sample_docx(
            self.temp_root / "input.docx",
            [
                "目录版本化测试项目",
                "视频监控子系统实施范围与接口联调要求。",
                "实施过程应符合GB50348。",
                "验收阶段应形成记录并完成签认。",
            ],
        )
        self.service.save_upload(task.task_id, "input.docx", sample_docx.read_bytes())
        self.service.parse_requirement(task.task_id)

        v1 = self.service.generate_toc(task.task_id)
        toc_v1 = TOCDocument.model_validate(self.service.get_toc_document(task.task_id, 1))
        target_title = toc_v1.tree[0].children[0].title
        renamed_title = f"{target_title}（修订版）"

        v2 = self.service.review_toc(
            task.task_id,
            f'把“{target_title}”改成“{renamed_title}”',
        )
        versions = self.service.list_toc_versions(task.task_id)

        self.assertEqual(v1.version_no, 1)
        self.assertEqual(v2.version_no, 2)
        self.assertEqual(v2.based_on_version_no, 1)
        self.assertEqual([item.version_no for item in versions], [2, 1])
        self.assertGreaterEqual(v2.diff_summary_json["summary"]["title_change_count"], 1)

        toc_v2 = TOCDocument.model_validate(self.service.get_toc_document(task.task_id, 2))
        level2_v1 = toc_v1.tree[0].children[0]
        level2_v2 = toc_v2.tree[0].children[0]
        self.assertEqual(level2_v1.node_uid, level2_v2.node_uid)
        self.assertEqual(level2_v2.title, renamed_title)

    def test_review_rejects_noop_feedback(self) -> None:
        task = self.service.create_task("目录无变更测试")
        sample_docx = create_sample_docx(
            self.temp_root / "input_noop.docx",
            [
                "目录无变更测试项目",
                "视频监控子系统实施范围与接口联调要求。",
                "实施过程应符合GB50348。",
            ],
        )
        self.service.save_upload(task.task_id, "input_noop.docx", sample_docx.read_bytes())
        self.service.parse_requirement(task.task_id)
        self.service.generate_toc(task.task_id)

        with self.assertRaisesRegex(ValueError, "未根据审阅意见应用任何目录修改"):
            self.service.review_toc(task.task_id, "整体再优化一下")

        versions = self.service.list_toc_versions(task.task_id)
        self.assertEqual([item.version_no for item in versions], [1])

    def test_import_outline_creates_toc_version_and_generation_units(self) -> None:
        task = self.service.create_task("完整目录树导入测试")
        sample_docx = create_sample_docx(
            self.temp_root / "input_outline.docx",
            [
                "完整目录树导入测试项目",
                "售后服务应覆盖电控系统、监控平台和网络系统。",
                "维保过程应符合既有运维窗口与不停机要求。",
                "质保期内应提供缺陷整改与免费升级服务。",
            ],
        )
        self.service.save_upload(task.task_id, "input_outline.docx", sample_docx.read_bytes())

        outline = "\n".join(
            [
                "一、售后服务总体方案",
                "1.1 售后服务目标",
                "1.1.1 保障系统安全稳定运行",
                "1.1.2 满足生产不停机与分阶段改造后的运维要求",
                "二、应急响应措施",
                "2.1 应急响应总体机制",
                "2.1.1 7×24小时响应机制",
            ]
        )

        version = self.service.import_toc_outline(task.task_id, outline)

        task_after = self.service.get_task(task.task_id)
        imported = TOCDocument.model_validate(self.service.get_toc_document(task.task_id, version.version_no))
        generation_units = self.service.toc_repository.list_generation_units(task.task_id, version.version_no)
        parse_report = self.service.get_parse_report(task.task_id)

        self.assertEqual(version.version_no, 1)
        self.assertIsNotNone(task_after)
        assert task_after is not None
        self.assertEqual(task_after.status.value, "TOC_REVIEW")
        self.assertIsNotNone(parse_report)
        self.assertEqual([node.title for node in imported.tree[0].children], ["售后服务总体方案", "应急响应措施"])
        self.assertEqual(imported.tree[0].children[0].children[0].title, "售后服务目标")
        self.assertEqual(
            [node.title for node in imported.tree[0].children[0].children[0].children],
            ["保障系统安全稳定运行", "满足生产不停机与分阶段改造后的运维要求"],
        )
        self.assertTrue(all(item.level == 4 for item in generation_units))
        self.assertEqual(
            [item.title for item in generation_units],
            [
                "保障系统安全稳定运行",
                "满足生产不停机与分阶段改造后的运维要求",
                "7×24小时响应机制",
            ],
        )

    def test_import_outline_accepts_arabic_top_level_numbering(self) -> None:
        task = self.service.create_task("阿拉伯数字一级目录导入测试")
        sample_docx = create_sample_docx(
            self.temp_root / "input_outline_arabic.docx",
            [
                "阿拉伯数字一级目录导入测试项目",
                "售后服务应覆盖维保、巡检、培训和应急响应。",
                "系统运维应兼顾不停机生产和分阶段改造要求。",
            ],
        )
        self.service.save_upload(task.task_id, "input_outline_arabic.docx", sample_docx.read_bytes())

        outline = "\n".join(
            [
                "1. 售后服务总体方案",
                "1.1 售后服务目标",
                "1.1.1 保障系统安全稳定运行",
                "2. 应急响应措施",
                "2.1 应急响应总体机制",
                "2.1.1 7×24小时响应机制",
            ]
        )

        version = self.service.import_toc_outline(task.task_id, outline)
        imported = TOCDocument.model_validate(self.service.get_toc_document(task.task_id, version.version_no))

        self.assertEqual(version.version_no, 1)
        self.assertEqual(
            [node.title for node in imported.tree[0].children],
            ["售后服务总体方案", "应急响应措施"],
        )
        self.assertEqual(imported.tree[0].children[0].node_id, "1.1")
        self.assertEqual(imported.tree[0].children[1].node_id, "1.2")
        self.assertEqual(
            imported.tree[0].children[0].children[0].children[0].title,
            "保障系统安全稳定运行",
        )


if __name__ == "__main__":
    unittest.main()
