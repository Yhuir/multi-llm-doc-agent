from __future__ import annotations

import json
import unittest
from unittest.mock import patch

from backend.agents.requirement_parser import RequirementParserAgent
from backend.agents.toc_generator import TOCGeneratorAgent
from backend.models.schemas import TOCNode
from tests.helpers import (
    cleanup_temp_root,
    create_sample_docx,
    make_temp_root,
    sample_requirement_document,
)


class RequirementParserAndTOCTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_root = make_temp_root("req_toc_test_")

    def tearDown(self) -> None:
        cleanup_temp_root(self.temp_root)

    def _parser_generation_config(self) -> dict[str, str]:
        return {
            "text_provider": "minimax",
            "text_model_name": "MiniMax-M2.5",
            "text_api_key": "fake-key",
        }

    def _solar_parser_response(self, *args, **kwargs) -> str:
        prompt = kwargs["prompt"]
        if "整编 requirement.json 的核心摘要字段" in prompt:
            return json.dumps(
                {
                    "project_name": "太阳能余热回收控制系统",
                    "overview": "围绕太阳能余热综合利用系统开展控制优化、接口联调和验收控制。",
                    "subsystems": [
                        {
                            "name": "太阳能余热回收控制系统",
                            "description": "完成系统开发优化与接口联调。",
                            "source_refs": ["p1#L2", "p1#L3"],
                        },
                        {
                            "name": "太阳能供热子系统",
                            "description": "纳入本次优化范围。",
                            "source_refs": ["p1#L2"],
                        },
                        {
                            "name": "空气源热泵子系统",
                            "description": "纳入本次优化范围。",
                            "source_refs": ["p1#L2"],
                        },
                    ],
                    "standards": ["GB50348"],
                    "acceptance": ["验收应符合GB50348。"],
                },
                ensure_ascii=False,
            )
        return json.dumps(
            {
                "overview_points": ["太阳能余热综合利用系统开发优化与接口联调。"],
                "requirements": [
                    {
                        "type": "technical",
                        "key": "solar_control_upgrade",
                        "value": "优化和完善太阳能余热回收控制系统，对太阳能余热综合利用系统进行开发和优化。",
                        "source_ref": "p1#L2",
                    },
                    {
                        "type": "technical",
                        "key": "logic_and_interface",
                        "value": "优化现有控制逻辑并完成接口联调。",
                        "source_ref": "p1#L3",
                    },
                ],
                "subsystems": [
                    {
                        "name": "太阳能余热回收控制系统",
                        "description": "完成系统开发优化与接口联调。",
                        "source_refs": ["p1#L2", "p1#L3"],
                    },
                    {
                        "name": "太阳能供热子系统",
                        "description": "纳入本次优化范围。",
                        "source_refs": ["p1#L2"],
                    },
                    {
                        "name": "空气源热泵子系统",
                        "description": "纳入本次优化范围。",
                        "source_refs": ["p1#L2"],
                    },
                ],
                "standards": [{"name": "GB50348", "source_ref": "p1#L4"}],
                "acceptance": [{"value": "验收应符合GB50348。", "source_ref": "p1#L4"}],
            },
            ensure_ascii=False,
        )

    def _long_doc_parser_response(self, *args, **kwargs) -> str:
        prompt = kwargs["prompt"]
        if "整编 requirement.json 的核心摘要字段" in prompt:
            return json.dumps(
                {
                    "project_name": "全文解析测试",
                    "overview": "全文已按分段方式完成解析，并保留全部原文索引。",
                    "subsystems": [],
                    "standards": [],
                    "acceptance": [],
                },
                ensure_ascii=False,
            )
        return json.dumps(
            {
                "overview_points": [],
                "requirements": [],
                "subsystems": [],
                "standards": [],
                "acceptance": [],
            },
            ensure_ascii=False,
        )

    def _invalid_consolidation_response(self, *args, **kwargs) -> str:
        prompt = kwargs["prompt"]
        if "整编 requirement.json 的核心摘要字段" in prompt:
            return json.dumps(
                {
                    "project_name": "",
                    "overview": "",
                    "subsystems": [],
                    "standards": [],
                    "acceptance": [],
                },
                ensure_ascii=False,
            )
        return json.dumps(
            {
                "overview_points": ["售后服务实施要求。"],
                "requirements": [
                    {
                        "type": "service",
                        "key": "service_scope",
                        "value": "售后服务需覆盖维保、巡检和应急响应。",
                        "source_ref": "p1#L2",
                    }
                ],
                "subsystems": [],
                "standards": [],
                "acceptance": [],
            },
            ensure_ascii=False,
        )

    def test_parser_is_clause_aware_and_extracts_subsystems(self) -> None:
        docx = create_sample_docx(
            self.temp_root / "sample.docx",
            [
                "第五章 服务要求",
                "3.13.1.1 优化和完善太阳能余热回收控制系统，根据生产管理的要求，对太阳能余热综合利用系统进行开发和优化，包括太阳能供热子系统、空气源热泵子系统。",
                "3.13.1.2 优化和完善太阳能余热回收控制系统，当前的太阳能余热回收控制系统由一期（卷包）和二期（制丝）组成，要求优化现有控制逻辑并完成接口联调。",
                "验收应符合GB50348。",
            ],
        )

        with patch.object(
            RequirementParserAgent,
            "_request_minimax_completion",
            side_effect=self._solar_parser_response,
        ):
            requirement, parse_report = RequirementParserAgent().parse(
                task_id="task_test",
                upload_file_path=docx,
                fallback_title="太阳能余热综合利用项目",
                generation_config=self._parser_generation_config(),
            )

        subsystem_names = [item.name for item in requirement.scope.subsystems]
        self.assertEqual(requirement.project.name, "太阳能余热回收控制系统")
        self.assertIn("太阳能余热回收控制系统", subsystem_names)
        self.assertIn("太阳能供热子系统", subsystem_names)
        self.assertIn("空气源热泵子系统", subsystem_names)
        self.assertNotIn("优化和完善太阳能余热回收控制系统", subsystem_names)
        self.assertIn("GB50348", requirement.constraints.standards)
        self.assertEqual(parse_report["subsystem_count"], 3)
        self.assertGreaterEqual(parse_report["bidding_requirement_count"], 3)
        self.assertGreaterEqual(parse_report["coverage_closure_count"], 0)

    def test_parser_source_index_preserves_full_document(self) -> None:
        docx = create_sample_docx(
            self.temp_root / "long.docx",
            [f"第{i + 1}段内容" for i in range(320)],
        )

        with patch.object(
            RequirementParserAgent,
            "_request_minimax_completion",
            side_effect=self._long_doc_parser_response,
        ):
            requirement, parse_report = RequirementParserAgent().parse(
                task_id="task_long",
                upload_file_path=docx,
                fallback_title="全文解析测试",
                generation_config=self._parser_generation_config(),
            )

        self.assertEqual(parse_report["paragraph_count"], 320)
        self.assertEqual(len(requirement.source_index), 320)
        self.assertEqual(requirement.source_index["p1#L320"].text, "第320段内容")
        self.assertGreaterEqual(parse_report["chunk_count"], 2)

    def test_parser_does_not_fallback_to_rule_based_project_or_overview(self) -> None:
        docx = create_sample_docx(
            self.temp_root / "no_fallback.docx",
            [
                "售后服务项目",
                "售后服务需覆盖维保、巡检和应急响应。",
            ],
        )

        with patch.object(
            RequirementParserAgent,
            "_request_minimax_completion",
            side_effect=self._invalid_consolidation_response,
        ):
            with self.assertRaisesRegex(ValueError, "project_name"):
                RequirementParserAgent().parse(
                    task_id="task_no_fallback",
                    upload_file_path=docx,
                    fallback_title="售后服务项目",
                    generation_config=self._parser_generation_config(),
                )

    def test_toc_generator_requires_llm_configuration(self) -> None:
        requirement = sample_requirement_document()

        with self.assertRaisesRegex(ValueError, "text_api_key"):
            TOCGeneratorAgent().generate(
                requirement=requirement,
                version_no=1,
                generation_config={
                    "text_provider": "minimax",
                    "text_model_name": "MiniMax-M2.5",
                    "text_api_key": "",
                },
            )

    def test_toc_generator_uses_model_output_instead_of_template(self) -> None:
        requirement = sample_requirement_document("智慧园区视频监控系统实施方案")
        model_output = """
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

        with patch.object(TOCGeneratorAgent, "_request_minimax_completion", return_value=model_output) as mocked:
            toc = TOCGeneratorAgent().generate(
                requirement=requirement,
                version_no=1,
                generation_config={
                    "text_provider": "minimax",
                    "text_model_name": "MiniMax-M2.5",
                    "text_api_key": "fake-key",
                },
            )

        mocked.assert_called_once()
        root = toc.tree[0]
        self.assertEqual(root.title, "视频监控系统实施方案")
        self.assertEqual(
            [child.title for child in root.children],
            ["视频监控系统建设范围", "施工与验收要求"],
        )
        self.assertEqual(
            [child.title for child in root.children[0].children],
            ["前端建设要求", "平台接入要求"],
        )
        self.assertTrue(all(not node.is_generation_unit for node in root.children[0].children))
        self.assertEqual(
            [child.title for child in root.children[0].children[0].children],
            ["前端点位部署要求"],
        )
        self.assertNotIn("实施范围与目标", self._flatten_titles(toc.tree))
        self.assertNotIn("联调测试与验收", self._flatten_titles(toc.tree))

    def test_toc_generator_supports_whatai_text_provider(self) -> None:
        requirement = sample_requirement_document("智慧园区视频监控系统实施方案")
        model_output = """
        {
          "root_title": "视频监控系统实施方案",
          "chapters": [
            {
              "title": "建设范围",
              "children": [
                {
                  "title": "实施要求",
                  "children": [
                    {"title": "前端点位部署要求", "children": []}
                  ]
                }
              ]
            }
          ]
        }
        """

        with patch.object(TOCGeneratorAgent, "_request_whatai_completion", return_value=model_output) as mocked:
            toc = TOCGeneratorAgent().generate(
                requirement=requirement,
                version_no=1,
                generation_config={
                    "text_provider": "whatai",
                    "text_model_name": "gemini-3.1-pro-preview",
                    "text_api_key": "fake-whatai-key",
                },
            )

        mocked.assert_called_once()
        self.assertEqual(toc.tree[0].children[0].title, "建设范围")

    def test_toc_generator_does_not_enforce_subsystem_title_coverage(self) -> None:
        requirement = sample_requirement_document("智慧园区视频监控系统实施方案")
        model_output = """
        {
          "root_title": "工程实施方案",
          "chapters": [
            {
              "title": "总体实施安排",
              "children": [
                {
                  "title": "范围与界面",
                  "children": [
                    {"title": "范围边界与职责划分", "children": []}
                  ]
                }
              ]
            },
            {
              "title": "质量与验收",
              "children": [
                {
                  "title": "验收策略",
                  "children": [
                    {"title": "过程留痕与验收签认", "children": []}
                  ]
                }
              ]
            }
          ]
        }
        """

        with patch.object(TOCGeneratorAgent, "_request_minimax_completion", return_value=model_output):
            toc = TOCGeneratorAgent().generate(
                requirement=requirement,
                version_no=1,
                generation_config={
                    "text_provider": "minimax",
                    "text_model_name": "MiniMax-M2.5",
                    "text_api_key": "fake-key",
                },
            )

        self.assertEqual(toc.tree[0].title, "工程实施方案")
        self.assertEqual(
            [child.title for child in toc.tree[0].children],
            ["总体实施安排", "质量与验收"],
        )

    def test_toc_generator_assigns_stable_node_uid_for_same_model_output(self) -> None:
        requirement = sample_requirement_document("智慧园区视频监控系统实施方案")
        model_output = """
        {
          "root_title": "视频监控系统实施方案",
          "chapters": [
            {
              "title": "视频监控系统建设范围",
              "children": [
                {
                  "title": "前端系统实施要求",
                  "children": [
                    {"title": "摄像机与立杆基础施工", "children": []},
                    {"title": "设备安装与连线检查", "children": []}
                  ]
                },
                {
                  "title": "平台接入与联调要求",
                  "children": [
                    {"title": "平台接口联调", "children": []}
                  ]
                }
              ]
            }
          ]
        }
        """

        with patch.object(TOCGeneratorAgent, "_request_minimax_completion", return_value=model_output):
            generator = TOCGeneratorAgent()
            toc_v1 = generator.generate(
                requirement=requirement,
                version_no=1,
                generation_config={
                    "text_provider": "minimax",
                    "text_model_name": "MiniMax-M2.5",
                    "text_api_key": "fake-key",
                },
            )
            toc_v2 = generator.generate(
                requirement=requirement,
                version_no=2,
                generation_config={
                    "text_provider": "minimax",
                    "text_model_name": "MiniMax-M2.5",
                    "text_api_key": "fake-key",
                },
            )

        self.assertEqual(
            self._flatten_node_uids(toc_v1.tree),
            self._flatten_node_uids(toc_v2.tree),
        )

    def test_toc_generator_strips_source_numbering_and_chapter_prefix_from_titles(self) -> None:
        requirement = sample_requirement_document("动力系统升级改造项目")
        model_output = """
        {
          "root_title": "动力系统升级改造项目实施方案",
          "chapters": [
            {
              "title": "1.10 第十章售后服务方案",
              "children": [
                {
                  "title": "2.1 项目范围与总体承包要求",
                  "children": [
                    {"title": "招标工作内容概述", "children": []}
                  ]
                },
                {
                  "title": "2.2 技术标准与规范体系",
                  "children": [
                    {"title": "智能建筑与通信设计标准", "children": []}
                  ]
                }
              ]
            }
          ]
        }
        """

        with patch.object(TOCGeneratorAgent, "_request_minimax_completion", return_value=model_output):
            toc = TOCGeneratorAgent().generate(
                requirement=requirement,
                version_no=1,
                generation_config={
                    "text_provider": "minimax",
                    "text_model_name": "MiniMax-M2.5",
                    "text_api_key": "fake-key",
                },
            )

        root = toc.tree[0]
        self.assertEqual(root.children[0].title, "售后服务方案")
        self.assertEqual(
            [child.title for child in root.children[0].children],
            ["项目范围与总体承包要求", "技术标准与规范体系"],
        )

    def test_toc_generator_strips_clause_number_prefix_from_leaf_titles(self) -> None:
        requirement = sample_requirement_document("动力系统升级改造项目")
        model_output = """
        {
          "root_title": "动力系统升级改造项目实施方案",
          "chapters": [
            {
              "title": "总则",
              "children": [
                {
                  "title": "售后服务组织",
                  "children": [
                    {"title": "1.8.5 售后服务团队", "children": []}
                  ]
                },
                {
                  "title": "售后服务执行",
                  "children": [
                    {"title": "1.8.6 售后服务内容及计划", "children": []}
                  ]
                }
              ]
            }
          ]
        }
        """

        with patch.object(TOCGeneratorAgent, "_request_minimax_completion", return_value=model_output):
            toc = TOCGeneratorAgent().generate(
                requirement=requirement,
                version_no=1,
                generation_config={
                    "text_provider": "minimax",
                    "text_model_name": "MiniMax-M2.5",
                    "text_api_key": "fake-key",
                },
            )

        self.assertEqual(
            [child.title for child in toc.tree[0].children[0].children[0].children],
            ["售后服务团队"],
        )
        self.assertEqual(
            [child.title for child in toc.tree[0].children[0].children[1].children],
            ["售后服务内容及计划"],
        )

    def test_toc_generator_collapses_overdeep_tree_into_level4_leaves(self) -> None:
        requirement = sample_requirement_document("动力系统升级改造项目")
        model_output = """
        {
          "root_title": "动力系统升级改造项目实施方案",
          "chapters": [
            {
              "title": "售后服务方案",
              "children": [
                {
                  "title": "服务响应机制",
                  "children": [
                    {
                      "title": "故障处理流程",
                      "children": [
                        {"title": "远程诊断与现场联动", "children": []},
                        {"title": "闭环整改与回访", "children": []}
                      ]
                    }
                  ]
                }
              ]
            }
          ]
        }
        """

        with patch.object(TOCGeneratorAgent, "_request_minimax_completion", return_value=model_output):
            toc = TOCGeneratorAgent().generate(
                requirement=requirement,
                version_no=1,
                generation_config={
                    "text_provider": "minimax",
                    "text_model_name": "MiniMax-M2.5",
                    "text_api_key": "fake-key",
                },
            )

        leaf_titles = [
            child.title
            for child in toc.tree[0].children[0].children[0].children[0].children
        ]
        self.assertEqual(
            leaf_titles,
            ["远程诊断与现场联动", "闭环整改与回访"],
        )
        self.assertTrue(
            all(
                node.level == 4
                for node in toc.tree[0].children[0].children[0].children[0].children
            )
        )

    def test_toc_generator_repairs_second_level_leaf_with_followup_model_call(self) -> None:
        requirement = sample_requirement_document("动力系统升级改造项目")
        invalid_output = """
        {
          "root_title": "动力系统升级改造项目实施方案",
          "chapters": [
            {"title": "适用范围", "children": []},
            {"title": "技术要求性质", "children": []}
          ]
        }
        """
        repaired_output = """
        {
          "root_title": "动力系统升级改造项目实施方案",
          "chapters": [
            {
              "title": "总则",
              "children": [
                {
                  "title": "基本要求",
                  "children": [
                    {"title": "适用范围", "children": []},
                    {"title": "技术要求性质", "children": []}
                  ]
                }
              ]
            }
          ]
        }
        """

        with patch.object(
            TOCGeneratorAgent,
            "_request_minimax_completion",
            side_effect=[invalid_output, repaired_output],
        ) as mocked:
            toc = TOCGeneratorAgent().generate(
                requirement=requirement,
                version_no=1,
                generation_config={
                    "text_provider": "minimax",
                    "text_model_name": "MiniMax-M2.5",
                    "text_api_key": "fake-key",
                },
            )

        self.assertEqual(mocked.call_count, 2)
        self.assertEqual(toc.tree[0].children[0].title, "总则")
        self.assertEqual(
            [child.title for child in toc.tree[0].children[0].children[0].children],
            ["适用范围", "技术要求性质"],
        )

    def _flatten_node_uids(self, nodes: list[TOCNode]) -> list[str]:
        values: list[str] = []
        for node in nodes:
            values.append(node.node_uid)
            values.extend(self._flatten_node_uids(node.children))
        return values

    def _flatten_titles(self, nodes: list[TOCNode]) -> list[str]:
        values: list[str] = []
        for node in nodes:
            values.append(node.title)
            values.extend(self._flatten_titles(node.children))
        return values


if __name__ == "__main__":
    unittest.main()
