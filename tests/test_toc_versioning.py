from __future__ import annotations

import json
import unittest
from unittest.mock import patch

from backend.agents.requirement_parser import RequirementParserAgent
from backend.agents.toc_generator import TOCGeneratorAgent
from backend.agents.toc_review.agent import TOCReviewChatAgent
from backend.app_service.task_service import TaskService
from backend.models.schemas import GenerationWordPlan, TOCDocument, TOCNode
from tests.helpers import (
    build_settings,
    cleanup_temp_root,
    create_sample_docx,
    make_temp_root,
    sample_requirement_document,
)


class TOCReviewAgentTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.agent = TOCReviewChatAgent()
        self.requirement = sample_requirement_document("目录审阅测试项目")
        self.review_config = {
            "text_provider": "minimax",
            "text_model_name": "MiniMax-M2.5",
            "text_api_key": "fake-key",
        }

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

        planned_actions = [
            {"type": "rename", "target": "建设目标", "new_title": "建设目标与实施目标"},
            {"type": "add_child", "parent": "项目理解与建设目标", "title": "项目风险识别"},
            {"type": "remove", "target": "对招标需求的响应说明"},
            {"type": "move_after", "target": "项目实施边界", "reference": "建设目标与实施目标"},
        ]
        with patch.object(self.agent, "_plan_actions_with_model", return_value=planned_actions):
            reviewed = self.agent.review(
                toc_doc=toc,
                feedback=(
                    "把“建设目标”改成“建设目标与实施目标”；"
                    "在“项目理解与建设目标”下新增“项目风险识别”；"
                    "删除“对招标需求的响应说明”；"
                    "将“项目实施边界”移动到“建设目标与实施目标”后面"
                ),
                requirement=self.requirement,
                review_config=self.review_config,
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
        self.assertFalse(added.is_generation_unit)
        self.assertEqual(len(added.children), 1)
        self.assertTrue(added.children[0].is_generation_unit)

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
                requirement=self.requirement,
                review_config=self.review_config,
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
                requirement=self.requirement,
                review_config=self.review_config,
            )

        root_children = reviewed.tree[0].children
        self.assertEqual(len(root_children), 1)
        self.assertEqual(root_children[0].title, "第二章")
        section_titles = [item.title for item in root_children[0].children]
        self.assertEqual(section_titles, ["新建系统范围"])

    def test_review_strips_clause_number_prefix_from_new_titles(self) -> None:
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
                            title="售后服务方案",
                            children=[
                                TOCNode(
                                    node_uid="uid_l3_a1",
                                    node_id="1.1.1",
                                    level=3,
                                    title="服务内容",
                                    is_generation_unit=True,
                                    constraints={"min_words": 1800},
                                    children=[],
                                )
                            ],
                        )
                    ],
                )
            ],
        )

        planned_actions = [
            {"type": "rename", "target": "服务内容", "new_title": "1.8.5 售后服务团队"}
        ]
        with patch.object(self.agent, "_plan_actions_with_model", return_value=planned_actions):
            reviewed = self.agent.review(
                toc_doc=toc,
                feedback="请将服务内容改成售后服务团队",
                requirement=self.requirement,
                review_config=self.review_config,
            )

        self.assertEqual(reviewed.tree[0].children[0].children[0].title, "售后服务团队")

    def test_review_expands_second_level_leaf_into_level3_generation_unit(self) -> None:
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
                            title="售后服务方案",
                            is_generation_unit=False,
                            children=[],
                        ),
                        TOCNode(
                            node_uid="uid_l2_b",
                            node_id="1.2",
                            level=2,
                            title="技术要求",
                            children=[
                                TOCNode(
                                    node_uid="uid_l3_b1",
                                    node_id="1.2.1",
                                    level=3,
                                    title="总体要求",
                                    is_generation_unit=True,
                                    constraints={"min_words": 1800},
                                    children=[],
                                )
                            ],
                        ),
                    ],
                )
            ],
        )

        planned_actions = [
            {"type": "rename", "target": "技术要求", "new_title": "技术要求总述"}
        ]
        with patch.object(self.agent, "_plan_actions_with_model", return_value=planned_actions):
            reviewed = self.agent.review(
                toc_doc=toc,
                feedback="请调整技术要求标题",
                requirement=self.requirement,
                review_config=self.review_config,
            )

        shallow_node = reviewed.tree[0].children[0]
        self.assertFalse(shallow_node.is_generation_unit)
        self.assertEqual(len(shallow_node.children), 1)
        self.assertEqual(shallow_node.children[0].level, 2)
        self.assertFalse(shallow_node.children[0].is_generation_unit)
        self.assertEqual(len(shallow_node.children[0].children), 1)
        self.assertEqual(shallow_node.children[0].children[0].level, 3)
        self.assertTrue(shallow_node.children[0].children[0].is_generation_unit)
        self.assertEqual(shallow_node.children[0].title, "售后服务方案")

    def test_explicit_keep_only_feedback_is_applied_from_model_planning(self) -> None:
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

        planned_actions = [
            {
                "type": "keep_only",
                "targets": ["新增设备与主要配置", "热泵、换热器与储能装置配置", "循环水泵与阀门仪表配置", "配套电控及线缆桥架配置"],
                "include_descendants": False,
            }
        ]
        with patch.object(self.agent, "_plan_actions_with_model", return_value=planned_actions):
            reviewed = self.agent.review(
                toc_doc=toc,
                feedback=feedback,
                requirement=self.requirement,
                review_config=self.review_config,
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

    def test_review_does_not_infer_keep_only_without_model_action(self) -> None:
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
                            node_uid="uid_l2_scope",
                            node_id="1.1",
                            level=2,
                            title="建设范围",
                            children=[
                                TOCNode(
                                    node_uid="uid_l3_keep",
                                    node_id="1.1.1",
                                    level=3,
                                    title="保留章节",
                                    is_generation_unit=True,
                                    constraints={"min_words": 1800},
                                    children=[],
                                ),
                                TOCNode(
                                    node_uid="uid_l3_drop",
                                    node_id="1.1.2",
                                    level=3,
                                    title="删除章节",
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

        feedback = "仅保留保留章节，删除其他"
        with patch.object(self.agent, "_plan_actions_with_model", return_value=[]):
            with self.assertRaisesRegex(ValueError, "未根据审阅意见应用任何目录修改"):
                self.agent.review(
                    toc_doc=toc,
                    feedback=feedback,
                    requirement=self.requirement,
                    review_config=self.review_config,
                )

    def test_review_model_prompt_includes_full_requirement_document(self) -> None:
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
                            node_uid="uid_l2_001",
                            node_id="1.1",
                            level=2,
                            title="售后服务方案",
                            children=[
                                TOCNode(
                                    node_uid="uid_l3_001",
                                    node_id="1.1.1",
                                    level=3,
                                    title="服务响应要求",
                                    is_generation_unit=True,
                                    children=[],
                                )
                            ],
                        )
                    ],
                )
            ],
        )
        rich_requirement = sample_requirement_document("全文目录审阅项目")
        rich_requirement.source_index["p1#L99"] = rich_requirement.source_index["p1#L2"].model_copy(
            update={"paragraph_id": "para_99", "text": "第99段：售后服务响应时效和质保责任要求。"}
        )

        with patch.object(
            self.agent,
            "_request_minimax_completion",
            return_value='{"actions":[{"type":"rename","target":"服务响应要求","new_title":"服务响应与闭环要求"}]}',
        ) as mocked:
            self.agent.review(
                toc_doc=toc,
                feedback="请优化总标题",
                requirement=rich_requirement,
                review_config=self.review_config,
            )

        prompt = mocked.call_args.kwargs["prompt"]
        self.assertIn("第99段：售后服务响应时效和质保责任要求。", prompt)
        self.assertIn("全文解析内容（必须通读）", prompt)
        self.assertIn("已提取招标要求（必须优先作为目录审阅依据）", prompt)
        self.assertIn("[technical] 完成前端设备部署、链路联调、平台接入与验收留痕。", prompt)


class TOCVersioningTestCase(unittest.TestCase):
    _MODEL_TOC = """
    {
      "root_title": "视频监控系统实施方案",
      "chapters": [
        {
          "title": "视频监控系统建设范围",
          "children": [
            {
              "title": "前端建设要求",
              "children": [
                {"title": "前端点位部署要求", "children": []}
              ]
            },
            {
              "title": "平台接入要求",
              "children": [
                {"title": "平台接入与联调要求", "children": []}
              ]
            }
          ]
        },
        {
          "title": "施工与验收要求",
          "children": [
            {
              "title": "施工管理要求",
              "children": [
                {"title": "施工组织与质量控制", "children": []}
              ]
            },
            {
              "title": "验收交付要求",
              "children": [
                {"title": "验收资料与签认要求", "children": []}
              ]
            }
          ]
        }
      ]
    }
    """

    def setUp(self) -> None:
        self.temp_root = make_temp_root("toc_version_test_")
        self.settings = build_settings(self.temp_root)
        self.service = TaskService(settings=self.settings)
        self.service.update_system_config(
            {
                "text_provider": "minimax",
                "text_model_name": "MiniMax-M2.5",
                "text_api_key": "fake-key",
            }
        )

    def tearDown(self) -> None:
        cleanup_temp_root(self.temp_root)

    @staticmethod
    def _review_model_actions(target_title: str, renamed_title: str) -> str:
        return json.dumps(
            {
                "actions": [
                    {
                        "type": "rename",
                        "target": target_title,
                        "new_title": renamed_title,
                    }
                ]
            },
            ensure_ascii=False,
        )

    @staticmethod
    def _imported_outline_model_toc(*, include_two_targets: bool = True) -> str:
        service_goal_children = (
            [
                {"title": "保障系统安全稳定运行", "children": []},
                {"title": "满足生产不停机与分阶段改造后的运维要求", "children": []},
            ]
            if include_two_targets
            else [{"title": "保障系统安全稳定运行", "children": []}]
        )
        return json.dumps(
            {
                "root_title": "电控系统、监控平台和网络系统售后服务实施方案",
                "chapters": [
                    {
                        "title": "售后服务总体方案",
                        "children": [
                            {
                                "title": "售后服务目标",
                                "children": service_goal_children,
                            }
                        ],
                    },
                    {
                        "title": "应急响应措施",
                        "children": [
                            {
                                "title": "应急响应总体机制",
                                "children": [{"title": "全天候响应机制", "children": []}],
                            }
                        ],
                    },
                ],
            },
            ensure_ascii=False,
        )

    @staticmethod
    def _budget_outline_model_toc() -> str:
        return json.dumps(
            {
                "root_title": "售后服务方案",
                "chapters": [
                    {
                        "title": "售后服务方案",
                        "children": [
                            {
                                "title": "服务团队",
                                "children": [
                                    {"title": "项目经理职责", "children": []},
                                    {"title": "现场工程师职责", "children": []},
                                ],
                            }
                        ],
                    },
                    {
                        "title": "应急响应",
                        "children": [
                            {
                                "title": "响应机制",
                                "children": [{"title": "7×24值守", "children": []}],
                            }
                        ],
                    },
                ],
            },
            ensure_ascii=False,
        )

    @staticmethod
    def _budget_small_outline_model_toc() -> str:
        return json.dumps(
            {
                "root_title": "售后服务方案",
                "chapters": [
                    {
                        "title": "售后服务方案",
                        "children": [
                            {
                                "title": "服务内容",
                                "children": [
                                    {"title": "日常巡检", "children": []},
                                    {"title": "故障响应", "children": []},
                                ],
                            }
                        ],
                    }
                ],
            },
            ensure_ascii=False,
        )

    @staticmethod
    def _parser_model_response(*args, **kwargs) -> str:
        prompt = kwargs["prompt"]
        if "整编 requirement.json 的核心摘要字段" in prompt and "视频监控子系统" in prompt:
            return json.dumps(
                {
                    "project_name": "目录版本化测试项目",
                    "overview": "视频监控子系统实施范围、接口联调、施工标准和验收要求。",
                    "subsystems": [
                        {
                            "name": "视频监控子系统",
                            "description": "完成实施范围、接口联调和验收控制。",
                            "source_refs": ["p1#L2", "p1#L3", "p1#L4"],
                        }
                    ],
                    "standards": ["GB50348"],
                    "acceptance": ["验收阶段应形成记录并完成签认。"],
                },
                ensure_ascii=False,
            )
        if "整编 requirement.json 的核心摘要字段" in prompt:
            return json.dumps(
                {
                    "project_name": "售后服务测试项目",
                    "overview": "售后服务及运维要求需覆盖维保、应急、标准评价和改造窗口约束。",
                    "subsystems": [
                        {
                            "name": "售后服务",
                            "description": "覆盖维保、应急、培训和标准评价。",
                            "source_refs": ["p1#L2", "p1#L3"],
                        }
                    ],
                    "standards": [],
                    "acceptance": [],
                },
                ensure_ascii=False,
            )
        if "视频监控子系统" in prompt:
            return json.dumps(
                {
                    "overview_points": ["视频监控子系统实施要求。"],
                    "requirements": [
                        {
                            "type": "technical",
                            "key": "video_scope",
                            "value": "视频监控子系统实施范围与接口联调要求。",
                            "source_ref": "p1#L2",
                        },
                        {
                            "type": "standard",
                            "key": "gb50348",
                            "value": "GB50348",
                            "source_ref": "p1#L3",
                        },
                        {
                            "type": "acceptance",
                            "key": "acceptance_record",
                            "value": "验收阶段应形成记录并完成签认。",
                            "source_ref": "p1#L4",
                        },
                    ],
                    "subsystems": [
                        {
                            "name": "视频监控子系统",
                            "description": "完成实施范围、接口联调和验收控制。",
                            "source_refs": ["p1#L2"],
                        }
                    ],
                    "standards": [{"name": "GB50348", "source_ref": "p1#L3"}],
                    "acceptance": [{"value": "验收阶段应形成记录并完成签认。", "source_ref": "p1#L4"}],
                },
                ensure_ascii=False,
            )
        return json.dumps(
            {
                "overview_points": ["售后服务和运维约束。"],
                "requirements": [
                    {
                        "type": "service",
                        "key": "service_scope",
                        "value": "售后服务应覆盖电控系统、监控平台和网络系统。",
                        "source_ref": "p1#L2",
                    },
                    {
                        "type": "operation",
                        "key": "maintenance_window",
                        "value": "维保过程应符合既有运维窗口与不停机要求。",
                        "source_ref": "p1#L3",
                    },
                    {
                        "type": "warranty",
                        "key": "warranty_upgrade",
                        "value": "质保期内应提供缺陷整改与免费升级服务。",
                        "source_ref": "p1#L4",
                    },
                ],
                "subsystems": [
                    {
                        "name": "售后服务",
                        "description": "覆盖维保、应急、培训和标准评价。",
                        "source_refs": ["p1#L2", "p1#L3", "p1#L4"],
                    }
                ],
                "standards": [],
                "acceptance": [],
            },
            ensure_ascii=False,
        )

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
        with patch.object(
            RequirementParserAgent,
            "_request_minimax_completion",
            side_effect=self._parser_model_response,
        ):
            self.service.parse_requirement(task.task_id)

        with patch.object(TOCGeneratorAgent, "_request_minimax_completion", return_value=self._MODEL_TOC):
            v1 = self.service.generate_toc(task.task_id)
        toc_v1 = TOCDocument.model_validate(self.service.get_toc_document(task.task_id, 1))
        target_title = toc_v1.tree[0].children[0].title
        renamed_title = f"{target_title}（修订版）"

        with patch.object(
            TOCReviewChatAgent,
            "_request_minimax_completion",
            return_value=self._review_model_actions(target_title, renamed_title),
        ):
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
        with patch.object(
            RequirementParserAgent,
            "_request_minimax_completion",
            side_effect=self._parser_model_response,
        ):
            self.service.parse_requirement(task.task_id)
        with patch.object(TOCGeneratorAgent, "_request_minimax_completion", return_value=self._MODEL_TOC):
            self.service.generate_toc(task.task_id)

        with self.assertRaisesRegex(ValueError, "未根据审阅意见应用任何目录修改"):
            with patch.object(
                TOCReviewChatAgent,
                "_request_minimax_completion",
                return_value='{"actions":[]}',
            ):
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

        with patch.object(
            RequirementParserAgent,
            "_request_minimax_completion",
            side_effect=self._parser_model_response,
        ):
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
        self.assertTrue(all(item.level == 3 for item in generation_units))
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

        with patch.object(
            RequirementParserAgent,
            "_request_minimax_completion",
            side_effect=self._parser_model_response,
        ):
            version = self.service.import_toc_outline(task.task_id, outline)
        imported = TOCDocument.model_validate(self.service.get_toc_document(task.task_id, version.version_no))

        self.assertEqual(version.version_no, 1)
        self.assertEqual(
            [node.title for node in imported.tree[0].children],
            ["售后服务总体方案", "应急响应措施"],
        )
        self.assertEqual(imported.tree[0].children[0].node_id, "1")
        self.assertEqual(imported.tree[0].children[1].node_id, "2")
        self.assertEqual(
            imported.tree[0].children[0].children[0].children[0].title,
            "保障系统安全稳定运行",
        )

    def test_word_budget_can_be_saved_and_confirmed_into_generation_plan(self) -> None:
        task = self.service.create_task("目录页面预算测试")
        sample_docx = create_sample_docx(
            self.temp_root / "input_budget.docx",
            [
                "目录页面预算测试项目",
                "售后服务需要覆盖团队、计划、应急和标准评价。",
                "各系统改造内容应形成分章节正文。",
            ],
        )
        self.service.save_upload(task.task_id, "input_budget.docx", sample_docx.read_bytes())

        outline = "\n".join(
            [
                "1. 售后服务方案",
                "1.1 服务团队",
                "1.1.1 项目经理职责",
                "1.1.2 现场工程师职责",
                "2. 应急响应",
                "2.1 响应机制",
                "2.1.1 7×24值守",
            ]
        )

        with patch.object(
            RequirementParserAgent,
            "_request_minimax_completion",
            side_effect=self._parser_model_response,
        ):
            version = self.service.import_toc_outline(task.task_id, outline)
        budget = self.service.get_toc_word_budget(task.task_id, version.version_no)

        self.assertEqual(
            [item["chapter_title"] for item in budget["chapters"]],
            ["售后服务方案", "应急响应"],
        )
        self.assertEqual(
            [item["default_total_pages"] for item in budget["chapters"]],
            [8, 4],
        )
        self.assertEqual(
            [item["min_total_pages"] for item in budget["chapters"]],
            [2, 2],
        )

        saved = self.service.update_toc_word_budget(
            task.task_id,
            version.version_no,
            {
                budget["chapters"][0]["chapter_node_uid"]: 5,
                budget["chapters"][1]["chapter_node_uid"]: 3,
            },
        )
        self.assertEqual(saved["estimated_total_pages"], 8)
        self.assertEqual(saved["estimated_total_words"], 4000)

        self.service.confirm_toc(task.task_id, version.version_no)
        plan_path = self.temp_root / "artifacts" / task.task_id / "toc" / "generation_word_plan.json"
        plan = GenerationWordPlan.model_validate(
            json.loads(plan_path.read_text(encoding="utf-8"))
        )

        self.assertEqual(plan.version_no, version.version_no)
        self.assertEqual(plan.estimated_total_pages, 8)
        self.assertEqual(plan.estimated_total_words, 4000)
        self.assertEqual(
            [item.target_words for item in plan.node_targets if item.chapter_title == "售后服务方案"],
            [1250, 1250],
        )
        self.assertEqual(
            [item.target_words for item in plan.node_targets if item.chapter_title == "应急响应"],
            [1500],
        )
        self.assertEqual(
            [(item.min_words, item.max_words) for item in plan.node_targets if item.chapter_title == "售后服务方案"],
            [(1250, 1500), (1250, 1500)],
        )
        self.assertEqual(
            [(item.min_words, item.max_words) for item in plan.node_targets if item.chapter_title == "应急响应"],
            [(1500, 2000)],
        )

    def test_word_budget_accepts_small_total_and_distributes_to_generation_units(self) -> None:
        task = self.service.create_task("目录页面预算小页数测试")
        sample_docx = create_sample_docx(
            self.temp_root / "input_budget_min.docx",
            [
                "目录页面预算小页数测试项目",
                "售后服务部分需要拆分成多个生成单元。",
            ],
        )
        self.service.save_upload(task.task_id, "input_budget_min.docx", sample_docx.read_bytes())

        outline = "\n".join(
            [
                "1. 售后服务方案",
                "1.1 服务内容",
                "1.1.1 日常巡检",
                "1.1.2 故障响应",
            ]
        )
        with patch.object(
            RequirementParserAgent,
            "_request_minimax_completion",
            side_effect=self._parser_model_response,
        ):
            version = self.service.import_toc_outline(task.task_id, outline)
        budget = self.service.get_toc_word_budget(task.task_id, version.version_no)
        saved = self.service.update_toc_word_budget(
            task.task_id,
            version.version_no,
            {budget["chapters"][0]["chapter_node_uid"]: 2},
        )
        self.assertEqual(saved["estimated_total_pages"], 2)
        self.assertEqual(saved["estimated_total_words"], 1000)

        self.service.confirm_toc(task.task_id, version.version_no)
        plan_path = self.temp_root / "artifacts" / task.task_id / "toc" / "generation_word_plan.json"
        plan = GenerationWordPlan.model_validate(
            json.loads(plan_path.read_text(encoding="utf-8"))
        )
        self.assertEqual(
            [item.target_words for item in plan.node_targets if item.chapter_title == "售后服务方案"],
            [500, 500],
        )
        self.assertEqual(
            [(item.min_words, item.max_words) for item in plan.node_targets if item.chapter_title == "售后服务方案"],
            [(500, 750), (500, 750)],
        )


if __name__ == "__main__":
    unittest.main()
