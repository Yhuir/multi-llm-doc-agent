"""Rule-based Consistency Check Agent for V1 skeleton."""

from __future__ import annotations

import re
from typing import Any, Iterable

from backend.models.enums import AgentResult
from backend.models.schemas import (
    CheckResult,
    ConsistencyChecks,
    ConsistencyIssue,
    ConsistencyReport,
    FactCheck,
    NodeText,
    RequirementDocument,
    TablesArtifact,
    TextParagraph,
)


class ConsistencyCheckAgent:
    """Run four-category consistency checks and apply minimal auto-fixes."""

    _STD_PATTERN = re.compile(r"(?:GB|ISO|IEC|DL/T)[A-Za-z0-9\-/.]*", re.IGNORECASE)
    _MODEL_PATTERN = re.compile(r"[A-Za-z]{1,6}\d[A-Za-z0-9\-/.]*")
    _DURATION_PATTERN = re.compile(r"(工期[^0-9]{0,8})(\d{1,4})(天)")
    _KEY_FACT_TOKENS = ["应", "应当", "必须", "标准", "验收", "接口", "参数", "阈值", "数量", "型号", "工期"]
    _TERM_NORMALIZATION = {
        "应当": "应",
        "必须要": "必须",
        "需": "应",
    }

    def check_and_fix(
        self,
        *,
        node_text: NodeText,
        requirement: RequirementDocument,
        tables: TablesArtifact,
        fact_check: FactCheck | None = None,
        images: dict[str, Any] | None = None,
        toc_confirmed: dict[str, Any] | None = None,
    ) -> tuple[ConsistencyReport, NodeText, TablesArtifact]:
        _ = images, toc_confirmed
        revised_text = node_text.model_copy(deep=True)
        revised_tables = tables.model_copy(deep=True)

        entity_result = self._check_entity_consistency(
            node_text=revised_text,
            requirement=requirement,
        )
        term_result = self._check_term_consistency(node_text=revised_text)
        constraint_result = self._check_constraint_consistency(
            node_text=revised_text,
            requirement=requirement,
        )
        reference_result = self._check_reference_consistency(
            node_text=revised_text,
            requirement=requirement,
            tables=revised_tables,
            fact_check=fact_check,
        )

        checks = ConsistencyChecks(
            entity_consistency=entity_result,
            term_consistency=term_result,
            constraint_consistency=constraint_result,
            reference_consistency=reference_result,
        )
        all_issues = (
            checks.entity_consistency.issues
            + checks.term_consistency.issues
            + checks.constraint_consistency.issues
            + checks.reference_consistency.issues
        )
        unresolved = [issue for issue in all_issues if not issue.fixed]
        overall = AgentResult.PASS if not unresolved else AgentResult.FAIL

        report = ConsistencyReport(
            node_uid=node_text.node_uid,
            result=overall,
            checks=checks,
        )
        return report, revised_text, revised_tables

    def _check_entity_consistency(
        self,
        *,
        node_text: NodeText,
        requirement: RequirementDocument,
    ) -> CheckResult:
        issues: list[ConsistencyIssue] = []
        expected_models = self._extract_models_from_requirement(requirement)
        if not expected_models:
            return CheckResult(result=AgentResult.PASS, issues=issues)

        canonical = next(iter(expected_models.values()))
        for paragraph in self._iter_paragraphs(node_text):
            models = self._extract_models(paragraph.text)
            unexpected = [item for item in models if item.upper() not in expected_models]
            if not unexpected:
                continue

            fixed = False
            if len(expected_models) == 1:
                for token in unexpected:
                    paragraph.text = paragraph.text.replace(token, canonical)
                fixed = True

            issues.append(
                ConsistencyIssue(
                    issue_type="ENTITY_MODEL_MISMATCH",
                    location=self._paragraph_location(paragraph),
                    detail=f"发现未在需求中声明的型号: {', '.join(unexpected)}",
                    suggestion="型号应与 requirement 约束保持一致。",
                    fix_action=f"替换为 {canonical}" if fixed else None,
                    fixable=len(expected_models) == 1,
                    fixed=fixed,
                )
            )

        return CheckResult(
            result=self._result_from_issues(issues),
            issues=issues,
        )

    def _check_term_consistency(self, *, node_text: NodeText) -> CheckResult:
        issues: list[ConsistencyIssue] = []
        for paragraph in self._iter_paragraphs(node_text):
            for raw, normalized in self._TERM_NORMALIZATION.items():
                if raw not in paragraph.text:
                    continue
                paragraph.text = paragraph.text.replace(raw, normalized)
                issues.append(
                    ConsistencyIssue(
                        issue_type="TERM_VARIANT",
                        location=self._paragraph_location(paragraph),
                        detail=f"术语表达 `{raw}` 与规范表达不一致。",
                        suggestion=f"统一为 `{normalized}`。",
                        fix_action=f"`{raw}` -> `{normalized}`",
                        fixable=True,
                        fixed=True,
                    )
                )

        return CheckResult(
            result=self._result_from_issues(issues),
            issues=issues,
        )

    def _check_constraint_consistency(
        self,
        *,
        node_text: NodeText,
        requirement: RequirementDocument,
    ) -> CheckResult:
        issues: list[ConsistencyIssue] = []

        expected_standards = {item.upper() for item in requirement.constraints.standards if item.strip()}
        for paragraph in self._iter_paragraphs(node_text):
            standards = self._STD_PATTERN.findall(paragraph.text)
            for standard in standards:
                if not expected_standards:
                    continue
                if standard.upper() in expected_standards:
                    continue
                fixed = False
                replacement = None
                if len(expected_standards) == 1:
                    replacement = next(iter(expected_standards))
                    paragraph.text = paragraph.text.replace(standard, replacement)
                    fixed = True
                issues.append(
                    ConsistencyIssue(
                        issue_type="CONSTRAINT_STANDARD_MISMATCH",
                        location=self._paragraph_location(paragraph),
                        detail=f"标准号 `{standard}` 与 requirement 不一致。",
                        suggestion="标准号应使用 requirement 中已确认条款。",
                        fix_action=f"`{standard}` -> `{replacement}`" if fixed else None,
                        fixable=len(expected_standards) == 1,
                        fixed=fixed,
                    )
                )

        expected_duration = requirement.project.duration_days
        if expected_duration is not None:
            for paragraph in self._iter_paragraphs(node_text):
                changed = False
                found_mismatch: str | None = None

                def _replace_duration(match: re.Match[str]) -> str:
                    nonlocal changed, found_mismatch
                    current = int(match.group(2))
                    if current == expected_duration:
                        return match.group(0)
                    changed = True
                    found_mismatch = match.group(2)
                    return f"{match.group(1)}{expected_duration}{match.group(3)}"

                new_text = self._DURATION_PATTERN.sub(_replace_duration, paragraph.text, count=1)
                if changed:
                    paragraph.text = new_text
                    issues.append(
                        ConsistencyIssue(
                            issue_type="CONSTRAINT_DURATION_MISMATCH",
                            location=self._paragraph_location(paragraph),
                            detail=f"工期值 `{found_mismatch}` 天与 requirement 不一致。",
                            suggestion=f"统一工期为 {expected_duration} 天。",
                            fix_action=f"{found_mismatch} -> {expected_duration}",
                            fixable=True,
                            fixed=True,
                        )
                    )

        return CheckResult(
            result=self._result_from_issues(issues),
            issues=issues,
        )

    def _check_reference_consistency(
        self,
        *,
        node_text: NodeText,
        requirement: RequirementDocument,
        tables: TablesArtifact,
        fact_check: FactCheck | None,
    ) -> CheckResult:
        issues: list[ConsistencyIssue] = []
        valid_refs = list(requirement.source_index.keys())
        valid_ref_set = set(valid_refs)
        fallback_ref = valid_refs[0] if valid_refs else None

        claim_ref_map: dict[str, list[str]] = {}
        if fact_check is not None:
            for claim in fact_check.claims:
                refs = [ref for ref in claim.source_refs if ref in valid_ref_set]
                if refs:
                    claim_ref_map[claim.text] = refs

        for paragraph in self._iter_paragraphs(node_text):
            invalid_refs = [ref for ref in paragraph.source_refs if ref not in valid_ref_set]
            if invalid_refs:
                paragraph.source_refs = [ref for ref in paragraph.source_refs if ref in valid_ref_set]
                fixed = bool(paragraph.source_refs)
                if not paragraph.source_refs and fallback_ref:
                    paragraph.source_refs = [fallback_ref]
                    fixed = True
                issues.append(
                    ConsistencyIssue(
                        issue_type="REFERENCE_INVALID",
                        location=self._paragraph_location(paragraph),
                        detail=f"存在无效 source_ref: {', '.join(invalid_refs)}",
                        suggestion="引用应来自 requirement.source_index。",
                        fix_action="移除无效引用并补齐可用引用" if fixed else None,
                        fixable=fallback_ref is not None,
                        fixed=fixed,
                    )
                )

            if self._is_key_fact(paragraph.text) and not paragraph.source_refs:
                candidate_refs = claim_ref_map.get(paragraph.text, [])
                if not candidate_refs and fallback_ref:
                    candidate_refs = [fallback_ref]
                fixed = bool(candidate_refs)
                if fixed:
                    paragraph.source_refs = candidate_refs
                issues.append(
                    ConsistencyIssue(
                        issue_type="REFERENCE_MISSING",
                        location=self._paragraph_location(paragraph),
                        detail="关键事实段缺少 source_refs。",
                        suggestion="关键事实应绑定 requirement 来源引用。",
                        fix_action=f"补齐引用: {', '.join(candidate_refs)}" if fixed else None,
                        fixable=fallback_ref is not None,
                        fixed=fixed,
                    )
                )

        default_anchor = self._first_anchor(node_text)
        for table in tables.tables:
            table_invalid_refs = [ref for ref in table.source_refs if ref not in valid_ref_set]
            if table_invalid_refs:
                table.source_refs = [ref for ref in table.source_refs if ref in valid_ref_set]
                fixed = bool(table.source_refs)
                if not table.source_refs and fallback_ref:
                    table.source_refs = [fallback_ref]
                    fixed = True
                issues.append(
                    ConsistencyIssue(
                        issue_type="TABLE_REFERENCE_INVALID",
                        location=f"table:{table.table_id}",
                        detail=f"表格引用包含无效 source_ref: {', '.join(table_invalid_refs)}",
                        suggestion="表格 source_refs 应来自 requirement.source_index。",
                        fix_action="清理无效引用并补齐可用引用" if fixed else None,
                        fixable=fallback_ref is not None,
                        fixed=fixed,
                    )
                )
            if not table.source_refs and fallback_ref:
                table.source_refs = [fallback_ref]
                issues.append(
                    ConsistencyIssue(
                        issue_type="TABLE_REFERENCE_MISSING",
                        location=f"table:{table.table_id}",
                        detail="表格缺少 source_refs。",
                        suggestion="表格应保留可追溯来源。",
                        fix_action=f"补齐引用: {fallback_ref}",
                        fixable=True,
                        fixed=True,
                    )
                )
            if not table.bind_anchor:
                fixed = default_anchor is not None
                if default_anchor:
                    table.bind_anchor = default_anchor
                issues.append(
                    ConsistencyIssue(
                        issue_type="TABLE_BIND_ANCHOR_MISSING",
                        location=f"table:{table.table_id}",
                        detail="表格缺少 bind_anchor。",
                        suggestion="表格应绑定到正文锚点，便于后续 Layout 插入。",
                        fix_action=f"绑定为 {default_anchor}" if fixed else None,
                        fixable=default_anchor is not None,
                        fixed=fixed,
                    )
                )

        return CheckResult(
            result=self._result_from_issues(issues),
            issues=issues,
        )

    def _extract_models_from_requirement(self, requirement: RequirementDocument) -> dict[str, str]:
        models: dict[str, str] = {}
        for subsystem in requirement.scope.subsystems:
            for item in subsystem.requirements:
                for token in self._extract_models(item.value):
                    upper = token.upper()
                    models.setdefault(upper, token)
        return models

    def _extract_models(self, text: str) -> list[str]:
        tokens = self._MODEL_PATTERN.findall(text)
        filtered = [token for token in tokens if not self._STD_PATTERN.fullmatch(token)]
        return list(dict.fromkeys(filtered))

    def _is_key_fact(self, text: str) -> bool:
        has_keyword = any(token in text for token in self._KEY_FACT_TOKENS)
        has_number = any(char.isdigit() for char in text)
        return has_keyword or has_number

    @staticmethod
    def _paragraph_location(paragraph: TextParagraph) -> str:
        return f"paragraph:{paragraph.paragraph_id}"

    @staticmethod
    def _first_anchor(node_text: NodeText) -> str | None:
        for paragraph in [item for section in node_text.sections for item in section.paragraphs]:
            if paragraph.anchors:
                return paragraph.anchors[0]
        return None

    @staticmethod
    def _iter_paragraphs(node_text: NodeText) -> Iterable[TextParagraph]:
        for section in node_text.sections:
            for paragraph in section.paragraphs:
                yield paragraph

    @staticmethod
    def _result_from_issues(issues: list[ConsistencyIssue]) -> AgentResult:
        unresolved = [item for item in issues if not item.fixed]
        return AgentResult.PASS if not unresolved else AgentResult.FAIL
