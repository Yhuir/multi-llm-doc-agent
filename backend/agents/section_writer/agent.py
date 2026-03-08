"""Rule-based Section Writer Agent for V1 skeleton."""

from __future__ import annotations

from typing import Iterable

from backend.models.schemas import (
    FactCheck,
    HighlightParagraph,
    NodeState,
    NodeText,
    RequirementDocument,
    TextParagraph,
    TextSection,
)


class SectionWriterAgent:
    """Generate and minimally revise node text with engineering style."""

    def generate(
        self,
        *,
        node: NodeState,
        requirement: RequirementDocument,
    ) -> NodeText:
        source_refs = self._collect_source_refs(requirement)
        standards = requirement.constraints.standards[:3]
        acceptance_items = requirement.constraints.acceptance[:2]
        duration = requirement.project.duration_days

        section_titles = self._dynamic_section_titles(node.title, requirement)
        sections: list[TextSection] = []

        claim_seq = 1
        for sec_idx, sec_title in enumerate(section_titles, start=1):
            paragraphs: list[TextParagraph] = []
            paragraph_texts = self._build_section_paragraphs(
                node_title=node.title,
                section_title=sec_title,
                project_name=requirement.project.name,
                standards=standards,
                acceptance_items=acceptance_items,
                duration=duration,
            )
            for para_idx, text in enumerate(paragraph_texts, start=1):
                selected_refs = source_refs[:1] if source_refs else []
                paragraphs.append(
                    TextParagraph(
                        paragraph_id=f"s{sec_idx:02d}_p{para_idx:02d}",
                        text=text,
                        source_refs=selected_refs,
                        claim_ids=[f"claim_{claim_seq:03d}"],
                        anchors=[f"anchor_{node.node_uid}_{sec_idx:02d}"],
                    )
                )
                claim_seq += 1

            sections.append(
                TextSection(
                    section_id=f"sec_{sec_idx:02d}",
                    title=sec_title,
                    paragraphs=paragraphs,
                )
            )

        highlight = HighlightParagraph(
            paragraph_id="key_01",
            text=(
                f"{node.title}实施阶段的关键重难点在于确保工序衔接、质量留痕与验收证据同步完成，"
                "必须做到过程可检查、结果可复核、问题可追踪。"
            ),
            style_hint="red_bold",
        )

        text = NodeText(
            node_uid=node.node_uid,
            node_id=node.node_id,
            title=node.title,
            summary=f"围绕{node.title}形成可执行、可验收、可追溯的实施正文。",
            sections=sections,
            highlight_paragraphs=[highlight],
            word_count=self.count_text_units(
                item.text for section in sections for item in section.paragraphs
            ),
            version=1,
        )
        return text

    def revise_text(
        self,
        *,
        node_text: NodeText,
        fact_check: FactCheck,
        requirement: RequirementDocument,
    ) -> NodeText:
        """Minimal revise loop: replace unsupported claims with grounded expression."""
        revised = node_text.model_copy(deep=True)
        unsupported = set(fact_check.unsupported_claims)
        fallback_refs = self._collect_source_refs(requirement)
        fallback_ref = fallback_refs[0] if fallback_refs else None

        changed = False
        for section in revised.sections:
            for paragraph in section.paragraphs:
                if paragraph.text in unsupported:
                    paragraph.text = self._grounded_rewrite(paragraph.text, requirement)
                    if fallback_ref and fallback_ref not in paragraph.source_refs:
                        paragraph.source_refs.append(fallback_ref)
                    changed = True

        if not changed:
            extra_text = (
                "根据需求文件与实施边界，本节点执行应以已确认范围为准，"
                "关键参数、标准条款和验收记录均需来源可追溯，避免引入未定义事实。"
            )
            target_section = revised.sections[-1] if revised.sections else None
            if target_section is not None:
                target_section.paragraphs.append(
                    TextParagraph(
                        paragraph_id=f"{target_section.section_id}_revise",
                        text=extra_text,
                        source_refs=[fallback_ref] if fallback_ref else [],
                        claim_ids=["claim_revise_001"],
                        anchors=[f"anchor_{revised.node_uid}_revise"],
                    )
                )

        revised.word_count = self.count_text_units(
            item.text for section in revised.sections for item in section.paragraphs
        )
        return revised

    def _build_section_paragraphs(
        self,
        *,
        node_title: str,
        section_title: str,
        project_name: str,
        standards: list[str],
        acceptance_items: list[str],
        duration: int | None,
    ) -> list[str]:
        standards_text = "、".join(standards) if standards else "已确认实施边界"
        acceptance_text = "；".join(acceptance_items) if acceptance_items else "交付检查项"
        duration_text = f"项目工期按{duration}天执行" if duration else "项目工期按合同约定执行"
        quality_sentence = (
            f"实施过程应严格执行{standards_text}等约束要求，关键工序应形成检查记录，"
            "每项结果必须能够对应到节点责任人与时间戳。"
            if standards
            else "实施过程应严格执行已确认边界要求，关键工序应形成检查记录，"
            "每项结果必须能够对应到节点责任人与时间戳。"
        )
        deliver_sentence = (
            f"针对本节工作内容，{duration_text}，并应同步落实{acceptance_text}，"
            "确保交付时具备可核查的证据链和问题闭环记录。"
            if acceptance_items
            else f"针对本节工作内容，{duration_text}，并应同步落实{acceptance_text}，"
            "确保交付时具备可核查的证据链和问题闭环记录。"
        )
        witness_point = "验收见证点" if acceptance_items else "交付见证点"

        return [
            (
                f"在{project_name}的{node_title}实施中，{section_title}应遵循先准备、后实施、再验证的顺序，"
                "确保现场条件、资源配置和作业窗口满足施工组织要求。"
            ),
            quality_sentence,
            deliver_sentence,
            (
                f"当{node_title}进入现场作业阶段时，应设置质量控制点、风险控制点和{witness_point}，"
                "避免工序返工与接口冲突，保证整体实施的连续性与可维护性。"
            ),
        ]

    def _dynamic_section_titles(self, node_title: str, requirement: RequirementDocument) -> list[str]:
        subsystem_name = requirement.scope.subsystems[0].name if requirement.scope.subsystems else "目标子系统"
        return [
            f"{node_title}实施范围与目标",
            f"{node_title}施工准备与资源配置",
            f"{subsystem_name}实施步骤与质量控制",
            f"{node_title}验收要求与交付条件",
            f"{node_title}风险控制与留痕管理",
        ]

    def _collect_source_refs(self, requirement: RequirementDocument) -> list[str]:
        refs: list[str] = []
        valid_ref_set = set(requirement.source_index.keys())
        for subsystem in requirement.scope.subsystems:
            for item in subsystem.requirements:
                if (
                    item.source_ref
                    and item.source_ref in valid_ref_set
                    and item.source_ref not in refs
                ):
                    refs.append(item.source_ref)
        if not refs:
            refs.extend(list(requirement.source_index.keys())[:5])
        return refs

    def _grounded_rewrite(self, text: str, requirement: RequirementDocument) -> str:
        return (
            "该段内容已按需求来源进行收敛，实施描述以已确认范围为准，"
            "不引入需求文档之外的关键事实，并保持过程性表述。"
        )

    @staticmethod
    def count_text_units(paragraphs: Iterable[str]) -> int:
        merged = "".join(part.strip() for part in paragraphs)
        return len(merged)
