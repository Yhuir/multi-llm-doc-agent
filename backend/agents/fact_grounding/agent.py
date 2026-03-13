"""Rule-based Fact Grounding Agent for V1 skeleton."""

from __future__ import annotations

import re

from backend.models.enums import AgentResult, ClaimType, SupportStatus
from backend.models.schemas import FactCheck, FactClaim, NodeText, RequirementDocument


class FactGroundingAgent:
    """Validate critical claims against requirement/source_index with minimal rules."""

    _STD_PATTERN = re.compile(r"\b(?:GB|ISO|IEC|DL/T)[\w\-/]*", re.IGNORECASE)
    _NORMALIZE_PATTERN = re.compile(r"[^0-9A-Za-z\u4e00-\u9fff]+")
    _STRONG_SCORE = 0.62
    _WEAK_SCORE = 0.35

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
            grounded = sum(1 for item in claims if item.support_status == SupportStatus.SUPPORTED)
            grounded_ratio = round(grounded / len(claims), 4)
        else:
            grounded_ratio = 1.0

        result = AgentResult.PASS
        if unsupported_claims or weak_claims or grounded_ratio < 1.0:
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
        if source_refs:
            if not all(ref in requirement.source_index for ref in source_refs):
                return SupportStatus.UNSUPPORTED
            cited_evidence = [requirement.source_index[ref].text for ref in source_refs]
            cited_status = self._classify_against_evidence(text=text, evidence_texts=cited_evidence)
            if cited_status is not None:
                return cited_status

        if self._matches_document_constraints(text=text, claim_type=claim_type, requirement=requirement):
            return SupportStatus.SUPPORTED

        requirement_status = self._classify_against_evidence(
            text=text,
            evidence_texts=self._document_evidence_texts(requirement),
        )
        if requirement_status is not None:
            return requirement_status

        return SupportStatus.UNSUPPORTED

    def _matches_document_constraints(
        self,
        *,
        text: str,
        claim_type: ClaimType,
        requirement: RequirementDocument,
    ) -> bool:
        normalized_text = self._normalize_text(text)
        standards = [item.upper() for item in requirement.constraints.standards]
        std_match = self._STD_PATTERN.findall(text)
        if std_match and all(item.upper() in standards for item in std_match):
            return True

        acceptance_items = [self._normalize_text(item) for item in requirement.constraints.acceptance if item]
        if any(item and item in normalized_text for item in acceptance_items):
            return True

        overview = self._normalize_text(requirement.scope.overview)
        if overview and len(overview) >= 6 and overview in normalized_text:
            return True

        if claim_type == ClaimType.DURATION and requirement.project.duration_days is not None:
            if "工期" in text and str(requirement.project.duration_days) in text:
                return True

        return False

    def _classify_against_evidence(
        self,
        *,
        text: str,
        evidence_texts: list[str],
    ) -> SupportStatus | None:
        if not evidence_texts:
            return None
        best_score = max((self._match_score(text, item) for item in evidence_texts if item), default=0.0)
        if best_score >= self._STRONG_SCORE:
            return SupportStatus.SUPPORTED
        if best_score >= self._WEAK_SCORE:
            return SupportStatus.WEAKLY_SUPPORTED
        return None

    def _document_evidence_texts(self, requirement: RequirementDocument) -> list[str]:
        evidence: list[str] = [item.text for item in requirement.source_index.values() if item.text]
        evidence.extend(item for item in requirement.constraints.acceptance if item)
        evidence.extend(item for item in requirement.constraints.standards if item)
        if requirement.scope.overview:
            evidence.append(requirement.scope.overview)
        for subsystem in requirement.scope.subsystems:
            if subsystem.name:
                evidence.append(subsystem.name)
            if subsystem.description:
                evidence.append(subsystem.description)
            evidence.extend(item.value for item in subsystem.requirements if item.value)
        return evidence

    def _match_score(self, claim_text: str, evidence_text: str) -> float:
        normalized_claim = self._normalize_text(claim_text)
        normalized_evidence = self._normalize_text(evidence_text)
        if not normalized_claim or not normalized_evidence:
            return 0.0
        if len(normalized_claim) >= 6 and normalized_claim in normalized_evidence:
            return 1.0
        if len(normalized_evidence) >= 6 and normalized_evidence in normalized_claim:
            return len(normalized_evidence) / max(len(normalized_claim), 1)

        claim_bigrams = self._bigrams(normalized_claim)
        evidence_bigrams = self._bigrams(normalized_evidence)
        if not claim_bigrams or not evidence_bigrams:
            return 0.0
        overlap = len(claim_bigrams & evidence_bigrams)
        return round(overlap / len(claim_bigrams), 4)

    def _bigrams(self, text: str) -> set[str]:
        if len(text) < 2:
            return {text} if text else set()
        return {text[index : index + 2] for index in range(len(text) - 1)}

    def _normalize_text(self, text: str) -> str:
        return self._NORMALIZE_PATTERN.sub("", text or "").lower()
