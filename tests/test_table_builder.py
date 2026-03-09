from __future__ import annotations

import unittest

from backend.agents.table_builder import TableBuilderAgent
from backend.models.schemas import (
    NodeText,
    RequirementConstraints,
    RequirementDocument,
    RequirementItem,
    RequirementProject,
    RequirementScope,
    RequirementSubsystem,
    TextParagraph,
    TextSection,
)


class TableBuilderTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.requirement = RequirementDocument(
            project=RequirementProject(name="余热综合利用项目", location="厂区内"),
            scope=RequirementScope(
                overview="用于验证表格生成范围。",
                subsystems=[
                    RequirementSubsystem(
                        name="水源热泵系统",
                        description="包含热泵机组、换热器和接口联调要求。",
                        requirements=[
                            RequirementItem(
                                type="requirement",
                                key="设备型号",
                                value="水源热泵机组 1 台",
                                source_ref="p1#L10",
                            ),
                            RequirementItem(
                                type="requirement",
                                key="安装位置",
                                value="厂区热力站内平台安装",
                                source_ref="p1#L10A",
                            ),
                            RequirementItem(
                                type="requirement",
                                key="通讯接口",
                                value="支持 PLC 和上位系统对接",
                                source_ref="p1#L11",
                            ),
                        ],
                        interfaces=["PLC 控制系统", "上位监控平台"],
                    ),
                    RequirementSubsystem(
                        name="拆除内容",
                        description="包含拆除和搬迁要求。",
                        requirements=[
                            RequirementItem(
                                type="requirement",
                                key="施工范围",
                                value="拆除原有设备并恢复现场",
                                source_ref="p1#L12",
                            )
                        ],
                        interfaces=[],
                    ),
                ],
            ),
            constraints=RequirementConstraints(
                standards=["GB50016-2014", "GB50231-2009"],
                acceptance=["按验收标准完成资料签认"],
            ),
            source_index={},
        )

    def test_general_background_node_does_not_repeat_global_tables(self) -> None:
        node_text = NodeText(
            node_uid="uid_bg",
            node_id="1.1.1",
            title="项目建设背景",
            summary="背景章节不应重复生成全局设备表。",
            sections=[
                TextSection(
                    section_id="sec_01",
                    title="项目建设背景实施范围与目标",
                    paragraphs=[
                        TextParagraph(
                            paragraph_id="p_01",
                            text="说明项目背景、建设必要性和边界。",
                            anchors=["anchor_bg"],
                        )
                    ],
                )
            ],
            word_count=32,
        )

        artifact = TableBuilderAgent().build(
            node_text=node_text,
            requirement=self.requirement,
        )
        self.assertEqual(len(artifact.tables), 0)

    def test_topic_specific_node_generates_single_relevant_table(self) -> None:
        node_text = NodeText(
            node_uid="uid_heat_pump",
            node_id="6.2.1",
            title="水源热泵技术要求",
            summary="技术要求章节应生成与当前节点相关的小表。",
            sections=[
                TextSection(
                    section_id="sec_01",
                    title="水源热泵配置与选型要求",
                    paragraphs=[
                        TextParagraph(
                            paragraph_id="p_01",
                            text="明确机组配置、接口和安装位置。",
                            anchors=["anchor_hp"],
                        )
                    ],
                )
            ],
            word_count=48,
        )

        artifact = TableBuilderAgent().build(
            node_text=node_text,
            requirement=self.requirement,
        )
        self.assertLessEqual(len(artifact.tables), 1)
        self.assertTrue(artifact.tables)
        self.assertLessEqual(len(artifact.tables[0].rows), TableBuilderAgent.MAX_ROWS_PER_TABLE)
        self.assertIn("水源热泵", artifact.tables[0].rows[0][0])


if __name__ == "__main__":
    unittest.main()
