"""Rule-based Table Builder Agent for V1 skeleton."""

from __future__ import annotations

import re
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

    DEFAULT_MAX_TABLES = 1
    MAX_ROWS_PER_TABLE = 8
    GENERIC_TOPIC_TOKENS = {
        "项目",
        "系统",
        "方案",
        "实施",
        "要求",
        "技术",
        "总体",
        "内容",
        "目标",
        "范围",
        "条件",
        "控制",
        "验收",
        "安装",
        "配置",
        "设计",
        "说明",
        "响应",
        "支持",
        "其他",
    }

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
        topic_keywords = self._node_topic_keywords(node_text)

        candidates = self._build_candidates(
            node_text=node_text,
            requirement=requirement,
            topic_keywords=topic_keywords,
        )
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
        topic_keywords: list[str],
    ) -> list[dict[str, Any]]:
        candidates: list[dict[str, Any]] = []
        equipment = self._equipment_candidate(
            node_text=node_text,
            requirement=requirement,
            topic_keywords=topic_keywords,
        )
        if equipment:
            candidates.append(equipment)
        interface = self._interface_candidate(
            node_text=node_text,
            requirement=requirement,
            topic_keywords=topic_keywords,
        )
        if interface:
            candidates.append(interface)
        standards = self._standards_candidate(
            node_text=node_text,
            requirement=requirement,
            topic_keywords=topic_keywords,
        )
        if standards:
            candidates.append(standards)
        return candidates

    def _equipment_candidate(
        self,
        *,
        node_text: NodeText,
        requirement: RequirementDocument,
        topic_keywords: list[str],
    ) -> dict[str, Any] | None:
        if not self._topic_supports_equipment_table(node_text.title, topic_keywords):
            return None
        rows: list[list[str]] = []
        refs: list[str] = []
        location_hint = requirement.project.location or "现场指定位置"
        seen_rows: set[tuple[str, str, str, str]] = set()

        for subsystem in requirement.scope.subsystems:
            subsystem_topic = f"{subsystem.name} {subsystem.description}"
            subsystem_related = self._matches_topic(subsystem_topic, topic_keywords)
            for item in subsystem.requirements:
                key = item.key.strip()
                value = item.value.strip()
                if not key and not value:
                    continue
                if not self._is_equipment_requirement(key=key, value=value):
                    continue
                combined = f"{subsystem.name} {key} {value}"
                if not subsystem_related and not self._matches_topic(combined, topic_keywords):
                    continue
                row = (subsystem.name or "-", key or "-", value or "-", location_hint)
                if row in seen_rows:
                    continue
                seen_rows.add(row)
                rows.append(list(row))
                if item.source_ref and item.source_ref not in refs:
                    refs.append(item.source_ref)
                if len(rows) >= self.MAX_ROWS_PER_TABLE:
                    break
            if len(rows) >= self.MAX_ROWS_PER_TABLE:
                break

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
        topic_keywords: list[str],
    ) -> dict[str, Any] | None:
        if not self._topic_supports_interface_table(node_text.title, topic_keywords):
            return None
        rows: list[list[str]] = []
        refs = self._collect_requirement_refs(requirement)[:4]

        for subsystem in requirement.scope.subsystems:
            subsystem_related = self._matches_topic(
                f"{subsystem.name} {subsystem.description}",
                topic_keywords,
            )
            for interface_name in subsystem.interfaces:
                target = interface_name.strip()
                if not target:
                    continue
                if not subsystem_related and not self._matches_topic(target, topic_keywords):
                    continue
                rows.append(
                    [
                        subsystem.name or "-",
                        target,
                        "按接口联调计划执行",
                        "完成联通性与记录校核",
                    ]
                )
                if len(rows) >= min(6, self.MAX_ROWS_PER_TABLE):
                    break
            if len(rows) >= min(6, self.MAX_ROWS_PER_TABLE):
                break

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
        topic_keywords: list[str],
    ) -> dict[str, Any] | None:
        if not self._topic_supports_constraint_table(node_text.title, topic_keywords):
            return None
        rows: list[list[str]] = []
        refs = self._collect_requirement_refs(requirement)[:4]

        for item in requirement.constraints.standards:
            standard = item.strip()
            if not standard:
                continue
            rows.append(["标准约束", standard, "执行", "用于实施过程与验收核对"])
            if len(rows) >= self.MAX_ROWS_PER_TABLE:
                break

        for item in requirement.constraints.acceptance:
            if len(rows) >= self.MAX_ROWS_PER_TABLE:
                break
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
        if row_count == 0:
            return False
        return (2 <= row_count <= self.MAX_ROWS_PER_TABLE and col_count >= 3) and structured_kind

    @staticmethod
    def _is_equipment_requirement(*, key: str, value: str) -> bool:
        target = f"{key} {value}"
        tokens = [
            "设备",
            "型号",
            "数量",
            "安装",
            "位置",
            "交换机",
            "配线",
            "机柜",
            "终端",
            "热泵",
            "换热器",
            "水泵",
            "阀门",
            "桥架",
            "电缆",
            "装置",
            "机组",
        ]
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

    def _matches_topic(self, text: str, topic_keywords: list[str]) -> bool:
        normalized = text.strip()
        if not normalized:
            return False
        return any(keyword in normalized for keyword in topic_keywords)

    def _node_topic_keywords(self, node_text: NodeText) -> list[str]:
        raw_phrases = [node_text.title] + [section.title for section in node_text.sections]
        keywords: list[str] = []
        for phrase in raw_phrases:
            normalized = phrase.strip()
            if not normalized:
                continue
            for suffix in (
                "技术要求",
                "系统方案",
                "实施范围与目标",
                "施工准备与资源配置",
                "实施步骤与质量控制",
                "验收要求与交付条件",
                "风险控制与留痕管理",
                "配置与选型要求",
                "性能与控制要求",
                "安装与验收要求",
                "接口与边界要求",
                "数据接入与联调要求",
                "测试与交付要求",
            ):
                if normalized.endswith(suffix):
                    normalized = normalized[: -len(suffix)].strip()
            parts = [normalized]
            parts.extend(
                item.strip()
                for item in re.split(r"[、，,及与和/\\s]+", normalized)
                if item.strip()
            )
            for item in parts:
                if len(item) < 2:
                    continue
                if item in self.GENERIC_TOPIC_TOKENS:
                    continue
                if item not in keywords:
                    keywords.append(item)
        return keywords

    @staticmethod
    def _topic_supports_equipment_table(node_title: str, topic_keywords: list[str]) -> bool:
        title = node_title.strip()
        if any(token in title for token in ("背景", "目标", "原则", "响应说明", "培训", "服务", "其他")):
            return False
        return any(
            token in title or any(token in keyword for keyword in topic_keywords)
            for token in ("设备", "热泵", "换热器", "水泵", "阀门", "桥架", "电缆", "机组", "装置", "柜")
        )

    @staticmethod
    def _topic_supports_interface_table(node_title: str, topic_keywords: list[str]) -> bool:
        title = node_title.strip()
        return any(
            token in title or any(token in keyword for keyword in topic_keywords)
            for token in ("接口", "联调", "集成", "通讯", "控制", "PLC", "上位系统", "自控")
        )

    @staticmethod
    def _topic_supports_constraint_table(node_title: str, topic_keywords: list[str]) -> bool:
        title = node_title.strip()
        return any(
            token in title or any(token in keyword for keyword in topic_keywords)
            for token in ("标准", "验收", "规范", "安全", "环保", "消防", "安装", "设计")
        )
