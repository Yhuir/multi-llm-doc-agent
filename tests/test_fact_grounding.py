from __future__ import annotations

import unittest

from backend.agents.fact_grounding import FactGroundingAgent
from backend.models.enums import AgentResult, ManualActionStatus, NodeStatus, SupportStatus
from backend.models.schemas import NodeState, NodeText, TextParagraph, TextSection
from tests.helpers import sample_requirement_document


class FactGroundingAgentTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.agent = FactGroundingAgent()
        self.requirement = sample_requirement_document("视频监控系统项目")

    def _build_node_text(self, *, text: str, source_refs: list[str]) -> NodeText:
        node = NodeState(
            node_state_id="state_fact_001",
            task_id="task_fact",
            node_uid="uid_fact_001",
            node_id="1.1.1",
            title="前端点位部署要求",
            level=3,
            status=NodeStatus.PENDING,
            manual_action_status=ManualActionStatus.NONE,
        )
        return NodeText(
            node_uid=node.node_uid,
            node_id=node.node_id,
            title=node.title,
            summary="事实校验测试",
            sections=[
                TextSection(
                    section_id="sec_01",
                    title="实施要求",
                    paragraphs=[
                        TextParagraph(
                            paragraph_id="p_01",
                            text=text,
                            source_refs=source_refs,
                            claim_ids=["claim_001"],
                            anchors=["anchor_001"],
                        )
                    ],
                )
            ],
            word_count=len(text),
        )

    def test_supported_claim_passes_only_when_grounded_in_document(self) -> None:
        node_text = self._build_node_text(
            text="施工过程应符合GB50348并保留验收记录。",
            source_refs=["p1#L2"],
        )

        result = self.agent.check(node_text=node_text, requirement=self.requirement)

        self.assertEqual(result.result, AgentResult.PASS)
        self.assertEqual(result.grounded_ratio, 1.0)
        self.assertEqual(result.claims[0].support_status, SupportStatus.SUPPORTED)
        self.assertEqual(result.unsupported_claims, [])
        self.assertEqual(result.weak_claims, [])

    def test_mismatched_source_ref_no_longer_auto_passes(self) -> None:
        node_text = self._build_node_text(
            text="应使用双机热备服务器部署。",
            source_refs=["p1#L1"],
        )

        result = self.agent.check(node_text=node_text, requirement=self.requirement)

        self.assertEqual(result.result, AgentResult.FAIL)
        self.assertEqual(result.claims[0].support_status, SupportStatus.UNSUPPORTED)
        self.assertEqual(result.unsupported_claims, ["应使用双机热备服务器部署。"])

    def test_general_engineering_knowledge_is_treated_as_unsupported(self) -> None:
        node_text = self._build_node_text(
            text="应建立周例会制度并设置双机热备演练机制。",
            source_refs=[],
        )

        result = self.agent.check(node_text=node_text, requirement=self.requirement)

        self.assertEqual(result.result, AgentResult.FAIL)
        self.assertEqual(result.claims[0].support_status, SupportStatus.UNSUPPORTED)
        self.assertEqual(result.grounded_ratio, 0.0)
        self.assertEqual(result.weak_claims, [])


if __name__ == "__main__":
    unittest.main()
