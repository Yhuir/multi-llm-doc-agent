"""Rule-based Table Builder Agent for V1 skeleton."""

from __future__ import annotations

from typing import Any

from backend.models.schemas import (
    NodeText,
    RequirementDocument,
    TableItem,
    TablesArtifact,
    TextParagraph,
)


class TableBuilderAgent:
    """Build minimal tables only when structured expression is beneficial."""

    DEFAULT_MAX_TABLES = 2

    def build(
        self,
        *,
        node_text: NodeText,
        requirement: RequirementDocument,
        table_preferences: dict[str, Any] | None = None,
    ) -> TablesArtifact:
        prefs = table_preferences or {}
        max_tables = int(prefs.get("max_tables_per_node", self.DEFAULT_MAX_TABLES) or self.DEFAULT_MAX_TABLES)
        only_when_structured = bool(prefs.get("only_when_structured", True))

        candidates = self._build_candidates(node_text=node_text, requirement=requirement)
        tables: list[TableItem] = []
        for idx, candidate in enumerate(candidates, start=1):
            if len(tables) >= max(0, max_tables):
                break
            if only_when_structured and not self._should_emit(candidate):
                continue
            table = TableItem(
                table_id=f"table_{idx:02d}",
                title=candidate["title"],
                headers=candidate["headers"],
                rows=candidate["rows"],
                style_name="BiddingTable",
                bind_anchor=candidate["bind_anchor"],
                source_refs=candidate["source_refs"],
            )
            tables.append(table)

        return TablesArtifact(node_uid=node_text.node_uid, tables=tables)

    def _build_candidates(
        self,
        *,
        node_text: NodeText,
        requirement: RequirementDocument,
    ) -> list[dict[str, Any]]:
        candidates: list[dict[str, Any]] = []
        equipment = self._equipment_candidate(node_text=node_text, requirement=requirement)
        if equipment:
            candidates.append(equipment)
        interface = self._interface_candidate(node_text=node_text, requirement=requirement)
        if interface:
            candidates.append(interface)
        standards = self._standards_candidate(node_text=node_text, requirement=requirement)
        if standards:
            candidates.append(standards)
        return candidates

    def _equipment_candidate(
        self,
        *,
        node_text: NodeText,
        requirement: RequirementDocument,
    ) -> dict[str, Any] | None:
        rows: list[list[str]] = []
        refs: list[str] = []
        location_hint = requirement.project.location or "现场指定位置"

        for subsystem in requirement.scope.subsystems:
            for item in subsystem.requirements:
                key = item.key.strip()
                value = item.value.strip()
                if not key and not value:
                    continue
                if not self._is_equipment_requirement(key=key, value=value):
                    continue
                rows.append([subsystem.name or "-", key or "-", value or "-", location_hint])
                if item.source_ref and item.source_ref not in refs:
                    refs.append(item.source_ref)

        if len(rows) < 2:
            return None

        return {
            "title": "主要设备与参数清单",
            "headers": ["子系统", "指标项", "要求值", "位置/说明"],
            "rows": rows,
            "bind_anchor": self._find_anchor(
                node_text=node_text,
                keywords=["设备", "参数", "安装", "型号", "数量"],
            ),
            "source_refs": refs or self._fallback_source_refs(node_text),
            "kind": "equipment_matrix",
        }

    def _interface_candidate(
        self,
        *,
        node_text: NodeText,
        requirement: RequirementDocument,
    ) -> dict[str, Any] | None:
        rows: list[list[str]] = []
        refs = self._collect_requirement_refs(requirement)[:4]

        for subsystem in requirement.scope.subsystems:
            for interface_name in subsystem.interfaces:
                target = interface_name.strip()
                if not target:
                    continue
                rows.append(
                    [
                        subsystem.name or "-",
                        target,
                        "按接口联调计划执行",
                        "完成联通性与记录校核",
                    ]
                )

        if len(rows) < 2:
            return None

        return {
            "title": "子系统接口联动矩阵",
            "headers": ["子系统", "接口对象", "接口说明", "校核要点"],
            "rows": rows,
            "bind_anchor": self._find_anchor(
                node_text=node_text,
                keywords=["接口", "联调", "对接"],
            ),
            "source_refs": refs or self._fallback_source_refs(node_text),
            "kind": "interface_matrix",
        }

    def _standards_candidate(
        self,
        *,
        node_text: NodeText,
        requirement: RequirementDocument,
    ) -> dict[str, Any] | None:
        rows: list[list[str]] = []
        refs = self._collect_requirement_refs(requirement)[:4]

        for item in requirement.constraints.standards:
            standard = item.strip()
            if not standard:
                continue
            rows.append(["标准约束", standard, "执行", "用于实施过程与验收核对"])

        for item in requirement.constraints.acceptance:
            acceptance = item.strip()
            if not acceptance:
                continue
            rows.append(["验收要求", acceptance, "核验", "形成可追溯验收记录"])

        if len(rows) < 3:
            return None

        return {
            "title": "标准与验收约束对应表",
            "headers": ["类别", "约束条款", "执行动作", "留痕要求"],
            "rows": rows,
            "bind_anchor": self._find_anchor(
                node_text=node_text,
                keywords=["标准", "验收", "约束"],
            ),
            "source_refs": refs or self._fallback_source_refs(node_text),
            "kind": "constraint_matrix",
        }

    def _should_emit(self, candidate: dict[str, Any]) -> bool:
        row_count = len(candidate["rows"])
        col_count = len(candidate["headers"])
        structured_kind = candidate["kind"] in {
            "equipment_matrix",
            "interface_matrix",
            "constraint_matrix",
            "parameter_matrix",
            "test_record",
        }
        return row_count >= 3 or col_count >= 4 or structured_kind

    @staticmethod
    def _is_equipment_requirement(*, key: str, value: str) -> bool:
        target = f"{key} {value}"
        tokens = ["设备", "型号", "数量", "安装", "位置", "交换机", "配线", "机柜", "终端"]
        return any(token in target for token in tokens)

    @staticmethod
    def _collect_requirement_refs(requirement: RequirementDocument) -> list[str]:
        refs: list[str] = []
        for subsystem in requirement.scope.subsystems:
            for item in subsystem.requirements:
                if item.source_ref and item.source_ref not in refs:
                    refs.append(item.source_ref)
        if not refs:
            refs.extend(list(requirement.source_index.keys())[:6])
        return refs

    def _find_anchor(self, *, node_text: NodeText, keywords: list[str]) -> str:
        for section in node_text.sections:
            for paragraph in section.paragraphs:
                if not paragraph.anchors:
                    continue
                if any(token in paragraph.text for token in keywords):
                    return paragraph.anchors[0]
        for paragraph in self._iter_paragraphs(node_text):
            if paragraph.anchors:
                return paragraph.anchors[0]
        return f"anchor_{node_text.node_uid}_table"

    def _fallback_source_refs(self, node_text: NodeText) -> list[str]:
        refs: list[str] = []
        for paragraph in self._iter_paragraphs(node_text):
            for ref in paragraph.source_refs:
                if ref not in refs:
                    refs.append(ref)
            if len(refs) >= 4:
                break
        return refs

    @staticmethod
    def _iter_paragraphs(node_text: NodeText) -> list[TextParagraph]:
        return [paragraph for section in node_text.sections for paragraph in section.paragraphs]
