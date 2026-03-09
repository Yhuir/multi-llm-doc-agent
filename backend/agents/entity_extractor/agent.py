"""Rule-based entity extraction for the lenient image pipeline."""

from __future__ import annotations

import re

from backend.models.schemas import EntityExtraction, EntityItem, FactCheck, NodeText


class EntityExtractorAgent:
    """Extract a small set of image-critical entities from grounded text."""

    _KEYWORD_CATALOG: tuple[tuple[str, str], ...] = (
        ("交换机", "device"),
        ("路由器", "device"),
        ("服务器", "device"),
        ("机柜", "device"),
        ("终端", "device"),
        ("传感器", "device"),
        ("摄像机", "device"),
        ("拓扑", "topology"),
        ("星型", "topology"),
        ("环形", "topology"),
        ("链路", "topology"),
        ("施工", "process"),
        ("安装", "process"),
        ("部署", "process"),
        ("调试", "process"),
        ("验收", "acceptance"),
        ("测试", "acceptance"),
        ("检查", "acceptance"),
        ("现场", "scene"),
        ("机房", "scene"),
        ("弱电间", "scene"),
    )

    def extract(self, *, node_text: NodeText, fact_check: FactCheck) -> EntityExtraction:
        unsupported_fragments = {
            self._normalize_text(item)
            for item in fact_check.unsupported_claims + fact_check.weak_claims
            if item
        }

        candidates: list[tuple[str, str]] = []
        self._append_candidate(
            candidates,
            phrase=node_text.title,
            category="scene",
            unsupported_fragments=unsupported_fragments,
        )

        for section in node_text.sections:
            self._append_candidate(
                candidates,
                phrase=section.title,
                category="process",
                unsupported_fragments=unsupported_fragments,
            )
            for paragraph in section.paragraphs[:2]:
                for keyword, category in self._KEYWORD_CATALOG:
                    if keyword in paragraph.text:
                        self._append_candidate(
                            candidates,
                            phrase=keyword,
                            category=category,
                            unsupported_fragments=unsupported_fragments,
                        )

        if not candidates:
            for fallback, category in (
                ("施工步骤", "process"),
                ("质量检查点", "acceptance"),
                ("实施场景", "scene"),
            ):
                self._append_candidate(
                    candidates,
                    phrase=fallback,
                    category=category,
                    unsupported_fragments=unsupported_fragments,
                )

        entities = [
            EntityItem(
                entity_id=f"ent_{index:03d}",
                name=name,
                category=category,
                must_have=True,
            )
            for index, (name, category) in enumerate(candidates[:6], start=1)
        ]
        return EntityExtraction(node_uid=node_text.node_uid, entities=entities)

    def _append_candidate(
        self,
        bucket: list[tuple[str, str]],
        *,
        phrase: str,
        category: str,
        unsupported_fragments: set[str],
    ) -> None:
        normalized = self._normalize_phrase(phrase)
        if not normalized:
            return
        collapsed = self._normalize_text(normalized)
        if any(item[0] == normalized for item in bucket):
            return
        if any(fragment and fragment in collapsed for fragment in unsupported_fragments):
            return
        bucket.append((normalized, category))

    @staticmethod
    def _normalize_phrase(phrase: str) -> str:
        compact = re.sub(r"\s+", " ", phrase or "").strip(" -_:.，。；、")
        if not compact:
            return ""
        if len(compact) <= 18:
            return compact
        parts = re.split(r"[，。；、,:/()（）\\-]", compact)
        for part in parts:
            part = part.strip()
            if 2 <= len(part) <= 18:
                return part
        return compact[:18].strip()

    @staticmethod
    def _normalize_text(text: str) -> str:
        return re.sub(r"\s+", "", text or "").lower()
