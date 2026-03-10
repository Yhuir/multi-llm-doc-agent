from __future__ import annotations

import unittest

from pydantic import ValidationError

from backend.models.enums import AgentResult, NodeStatus
from backend.models.schemas import ImagePrompts, Metrics, RequirementDocument, TOCDocument


class SchemaValidationTestCase(unittest.TestCase):
    def test_requirement_document_rejects_unknown_root_field(self) -> None:
        payload = {
            "project": {
                "name": "项目A",
                "customer": "客户A",
                "location": "昆明",
                "duration_days": 90,
                "milestones": [],
            },
            "scope": {
                "overview": "范围说明",
                "subsystems": [],
            },
            "constraints": {
                "standards": ["GB50348"],
                "acceptance": ["完成验收签认。"],
            },
            "source_index": {},
            "unexpected": "forbid",
        }
        with self.assertRaises(ValidationError):
            RequirementDocument.model_validate(payload)

    def test_requirement_document_rejects_unknown_nested_field(self) -> None:
        payload = {
            "project": {
                "name": "项目A",
                "customer": "客户A",
                "location": "昆明",
                "duration_days": 90,
                "milestones": [],
                "unexpected": "forbid",
            },
            "scope": {
                "overview": "范围说明",
                "subsystems": [],
            },
            "constraints": {
                "standards": ["GB50348"],
                "acceptance": ["完成验收签认。"],
            },
            "source_index": {},
        }
        with self.assertRaises(ValidationError):
            RequirementDocument.model_validate(payload)

    def test_image_prompts_validate_required_fields(self) -> None:
        payload = {
            "node_uid": "uid_001",
            "prompts": [
                {
                    "prompt_id": "prompt_01",
                    "image_type": "topology",
                    "prompt": "生成网络拓扑图",
                    "style_preset": "engineering_flow_diagram",
                    "style_variant": "hub_diagnosis_map",
                    "aspect_ratio": "2:1",
                    "must_have_elements": ["交换机", "机柜"],
                    "forbidden_elements": ["人物"],
                    "bind_anchor": "anchor_1",
                    "bind_section": "实施步骤",
                }
            ],
        }
        prompts = ImagePrompts.model_validate(payload)
        self.assertEqual(prompts.prompts[0].style_preset, "engineering_flow_diagram")
        self.assertEqual(prompts.prompts[0].style_variant, "hub_diagnosis_map")
        self.assertEqual(prompts.prompts[0].aspect_ratio, "2:1")
        self.assertEqual(prompts.prompts[0].must_have_elements, ["交换机", "机柜"])
        self.assertEqual(prompts.prompts[0].forbidden_elements, ["人物"])

    def test_metrics_and_toc_document_use_enum_backed_values(self) -> None:
        metrics = Metrics(
            node_uid="uid_001",
            word_count=1900,
            grounded_ratio=0.92,
            image_score_avg=0.81,
            image_retry_total=1,
            text_retry_total=0,
            fact_retry_total=0,
            duration_ms=1234,
            final_status=NodeStatus.NODE_DONE,
        )
        toc = TOCDocument.model_validate(
            {
                "version": 1,
                "tree": [
                    {
                        "node_uid": "uid_001",
                        "node_id": "1.1.1",
                        "level": 3,
                        "title": "实施方案",
                        "is_generation_unit": True,
                        "source_refs": [],
                        "constraints": None,
                        "children": [],
                    }
                ],
            }
        )
        self.assertEqual(metrics.final_status, NodeStatus.NODE_DONE)
        self.assertEqual(toc.tree[0].title, "实施方案")
        self.assertEqual(AgentResult.PASS.value, "PASS")


if __name__ == "__main__":
    unittest.main()
