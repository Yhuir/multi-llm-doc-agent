"""Rule-based Fact Grounding Agent for V1 skeleton."""

from __future__ import annotations

import re

from backend.models.enums import AgentResult, ClaimType, SupportStatus
from backend.models.schemas import FactCheck, FactClaim, NodeText, RequirementDocument


class FactGroundingAgent:
    """Validate critical claims against requirement/source_index with minimal rules."""

    _STD_PATTERN = re.compile(r"\b(?:GB|ISO|IEC|DL/T)[\w\-/]*", re.IGNORECASE)

    def check(self, *, node_text: NodeText, requirement: RequirementDocument) -> FactCheck:
        claims: list[FactClaim] = []

        for section in node_text.sections:
            for paragraph in section.paragraphs:
                if not self._is_key_claim(paragraph.text):
                    continue
                claim_type = self._guess_claim_type(paragraph.text)
                support_status = self._judge_support(
                    text=paragraph.text,
                    source_refs=paragraph.source_refs,
                    claim_type=claim_type,
                    requirement=requirement,
                )
                claim_id = (
                    paragraph.claim_ids[0]
                    if paragraph.claim_ids
                    else f"claim_{len(claims) + 1:03d}"
                )
                claims.append(
                    FactClaim(
                        claim_id=claim_id,
                        text=paragraph.text,
                        claim_type=claim_type,
                        support_status=support_status,
                        source_refs=paragraph.source_refs,
                    )
                )

        unsupported_claims = [item.text for item in claims if item.support_status == SupportStatus.UNSUPPORTED]
        weak_claims = [item.text for item in claims if item.support_status == SupportStatus.WEAKLY_SUPPORTED]

        if claims:
            grounded = sum(1 for item in claims if item.support_status != SupportStatus.UNSUPPORTED)
            grounded_ratio = round(grounded / len(claims), 4)
        else:
            grounded_ratio = 1.0

        result = AgentResult.PASS
        if unsupported_claims or grounded_ratio < 0.70:
            result = AgentResult.FAIL

        return FactCheck(
            node_uid=node_text.node_uid,
            grounded_ratio=grounded_ratio,
            result=result,
            claims=claims,
            unsupported_claims=unsupported_claims,
            weak_claims=weak_claims,
        )

    def _is_key_claim(self, text: str) -> bool:
        indicators = [
            "应",
            "应当",
            "必须",
            "标准",
            "验收",
            "工期",
            "接口",
            "参数",
            "阈值",
            "数量",
            "型号",
        ]
        has_number = any(char.isdigit() for char in text)
        has_indicator = any(token in text for token in indicators)
        has_std = bool(self._STD_PATTERN.search(text))
        return has_number or has_indicator or has_std

    def _guess_claim_type(self, text: str) -> ClaimType:
        if "工期" in text or "里程碑" in text:
            return ClaimType.DURATION
        if "标准" in text or self._STD_PATTERN.search(text):
            return ClaimType.STANDARD
        if "验收" in text:
            return ClaimType.ACCEPTANCE
        if "接口" in text:
            return ClaimType.INTERFACE
        if "数量" in text:
            return ClaimType.QUANTITY
        if "阈值" in text or "参数" in text:
            return ClaimType.PARAMETER
        if "设备" in text or "型号" in text:
            return ClaimType.EQUIPMENT
        return ClaimType.PROCESS

    def _judge_support(
        self,
        *,
        text: str,
        source_refs: list[str],
        claim_type: ClaimType,
        requirement: RequirementDocument,
    ) -> SupportStatus:
        if source_refs and all(ref in requirement.source_index for ref in source_refs):
            return SupportStatus.SUPPORTED

        standards = [item.upper() for item in requirement.constraints.standards]
        std_match = self._STD_PATTERN.findall(text)
        if std_match and any(item.upper() in standards for item in std_match):
            return SupportStatus.SUPPORTED

        if any(item in text for item in requirement.constraints.acceptance[:10]):
            return SupportStatus.WEAKLY_SUPPORTED

        if requirement.project.duration_days is not None and str(requirement.project.duration_days) in text:
            return SupportStatus.WEAKLY_SUPPORTED

        subsystem_names = [sub.name for sub in requirement.scope.subsystems]
        if any(name and name in text for name in subsystem_names):
            return SupportStatus.WEAKLY_SUPPORTED

        if claim_type == ClaimType.STANDARD and not standards and not std_match:
            return SupportStatus.GENERAL_ENGINEERING_KNOWLEDGE

        if claim_type == ClaimType.ACCEPTANCE and not requirement.constraints.acceptance:
            return SupportStatus.GENERAL_ENGINEERING_KNOWLEDGE

        if claim_type == ClaimType.PROCESS and not any(char.isdigit() for char in text):
            return SupportStatus.GENERAL_ENGINEERING_KNOWLEDGE

        return SupportStatus.UNSUPPORTED
