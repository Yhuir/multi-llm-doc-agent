"""Rule-based Length Control Agent for V1 skeleton."""

from __future__ import annotations

from typing import Iterable

from backend.models.schemas import NodeText, RequirementDocument, TextParagraph


class LengthControlAgent:
    """Control node text length into 1800-2200 range with minimal revise rounds."""

    def control(
        self,
        *,
        node_text: NodeText,
        requirement: RequirementDocument,
        min_words: int = 1800,
        max_words: int = 2200,
        max_expand_rounds: int = 2,
    ) -> tuple[NodeText, dict]:
        updated = node_text.model_copy(deep=True)
        before = self.count_text_units(self._paragraph_texts(updated))
        rounds = 0
        action = "PASS"

        while before < min_words and rounds < max_expand_rounds:
            rounds += 1
            action = "EXPAND"
            self._expand_once(updated, requirement, round_no=rounds)
            before = self.count_text_units(self._paragraph_texts(updated))

        if before > max_words:
            action = "TRIM"
            self._trim_to_range(updated, max_words)
            before = self.count_text_units(self._paragraph_texts(updated))

        updated.word_count = before
        result = "PASS" if min_words <= before <= max_words else "FAIL"

        return updated, {
            "node_uid": updated.node_uid,
            "before_word_count": node_text.word_count,
            "after_word_count": updated.word_count,
            "action": action,
            "expand_rounds": rounds,
            "result": result,
            "min_words": min_words,
            "max_words": max_words,
        }

    def _expand_once(self, node_text: NodeText, requirement: RequirementDocument, *, round_no: int) -> None:
        refs = list(requirement.source_index.keys())[:2]
        section = node_text.sections[-1] if node_text.sections else None
        if section is None:
            return

        extra_paragraphs = [
            (
                "为满足实施深度要求，本轮补写重点增加测试组织、过程留痕和交付复核要求，"
                "明确作业前检查、作业中监测、作业后复盘三个闭环动作。现场执行人员应逐项记录"
                "输入条件、执行动作、输出结果和异常处置，确保每个作业点均可追踪到责任人、执行时间"
                "与复核结论。"
            ),
            (
                "补写内容同时明确风险应对机制，包括异常发现、逐级上报、临时处置、复工确认、"
                "结果复核与文档归档。各角色应按照统一沟通链路处理问题，形成从问题登记、影响评估、"
                "处置执行到关闭确认的完整证据链，保证实施活动在受控边界内持续推进。"
            ),
            (
                "在质量控制方面，应建立节点级检查清单和阶段性评审机制，重点覆盖输入资料完整性、"
                "关键工序执行一致性、参数记录准确性、接口联动稳定性和交付资料可复核性。每次评审后"
                "需输出整改项、责任分配、完成时限和复核结果，确保整改闭环及时完成。"
            ),
            (
                "在交付与运维衔接方面，建议同步整理操作指引、配置留档、故障应对卡片和常见问题清单，"
                "并通过现场演示与签认机制完成知识移交。该补写内容用于提升节点文本的可执行性与可验收性，"
                "避免只描述原则而缺乏落地步骤。"
            ),
        ]

        for idx, text in enumerate(extra_paragraphs, start=1):
            section.paragraphs.append(
                TextParagraph(
                    paragraph_id=f"{section.section_id}_expand_{round_no}_{idx}",
                    text=text,
                    source_refs=refs,
                    claim_ids=[f"claim_expand_{round_no}_{idx}"],
                    anchors=[f"anchor_{node_text.node_uid}_expand_{round_no}_{idx}"],
                )
            )

    def _trim_to_range(self, node_text: NodeText, max_words: int) -> None:
        while self.count_text_units(self._paragraph_texts(node_text)) > max_words:
            last_section = None
            for section in reversed(node_text.sections):
                if len(section.paragraphs) > 1:
                    last_section = section
                    break
            if last_section is None:
                break
            last_section.paragraphs.pop()

        current = self.count_text_units(self._paragraph_texts(node_text))
        if current <= max_words:
            return

        for section in reversed(node_text.sections):
            if not section.paragraphs:
                continue
            paragraph = section.paragraphs[-1]
            overflow = current - max_words
            if overflow >= len(paragraph.text):
                paragraph.text = paragraph.text[: max(1, len(paragraph.text) // 2)]
            else:
                paragraph.text = paragraph.text[:-overflow]
            break

    @staticmethod
    def _paragraph_texts(node_text: NodeText) -> Iterable[str]:
        for section in node_text.sections:
            for paragraph in section.paragraphs:
                yield paragraph.text

    @staticmethod
    def count_text_units(paragraphs: Iterable[str]) -> int:
        merged = "".join(part.strip() for part in paragraphs)
        return len(merged)
