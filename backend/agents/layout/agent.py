"""Layout agent that converts node artifacts into ordered layout blocks."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from backend.models.schemas import (
    ImagesArtifact,
    NodeText,
    TOCDocument,
    TOCNode,
    TablesArtifact,
    utc_now_iso,
)


class LayoutAgent:
    """Build a stable, template-oriented layout block list for final export."""

    MAX_TABLE_ROWS = 8

    def build(
        self,
        *,
        task_id: str,
        artifacts_root: Path,
        toc_document: TOCDocument,
    ) -> dict[str, Any]:
        warnings: list[str] = []
        blocks: list[dict[str, Any]] = []
        visible_nodes, base_level = self._visible_outline(toc_document.tree)

        for root_index, toc_node in enumerate(visible_nodes):
            if root_index > 0:
                blocks.append({"type": "page_break"})
            self._append_node_blocks(
                task_id=task_id,
                artifacts_root=artifacts_root,
                toc_node=toc_node,
                base_level=base_level,
                blocks=blocks,
                warnings=warnings,
            )

        return {
            "task_id": task_id,
            "generated_at": utc_now_iso(),
            "warnings": warnings,
            "blocks": blocks,
        }

    def _append_node_blocks(
        self,
        *,
        task_id: str,
        artifacts_root: Path,
        toc_node: TOCNode,
        base_level: int,
        blocks: list[dict[str, Any]],
        warnings: list[str],
    ) -> None:
        visible_level = max(1, toc_node.level - base_level)
        blocks.append(
            {
                "type": "heading",
                "node_uid": toc_node.node_uid,
                "text": toc_node.title,
                "style_name": self._heading_style_for_level(visible_level),
            }
        )

        if toc_node.is_generation_unit:
            self._append_generation_content(
                task_id=task_id,
                artifacts_root=artifacts_root,
                toc_node=toc_node,
                visible_level=visible_level,
                blocks=blocks,
                warnings=warnings,
            )

        for child in toc_node.children:
            self._append_node_blocks(
                task_id=task_id,
                artifacts_root=artifacts_root,
                toc_node=child,
                base_level=base_level,
                blocks=blocks,
                warnings=warnings,
            )

    def _append_generation_content(
        self,
        *,
        task_id: str,
        artifacts_root: Path,
        toc_node: TOCNode,
        visible_level: int,
        blocks: list[dict[str, Any]],
        warnings: list[str],
    ) -> None:
        node_dir = artifacts_root / task_id / "nodes" / toc_node.node_uid
        text_path = node_dir / "text.json"
        if not text_path.exists():
            raise FileNotFoundError(f"text.json missing for node {toc_node.node_uid}")

        node_text = NodeText.model_validate(
            json.loads(text_path.read_text(encoding="utf-8"))
        )
        tables = self._filter_tables_for_node(
            node_title=toc_node.title,
            tables=self._load_tables(node_dir).tables,
            node_uid=toc_node.node_uid,
            warnings=warnings,
        )
        images = self._load_images(node_dir)
        pending_tables = list(tables)
        pending_images = list(images.images)

        for section in node_text.sections:
            blocks.append(
                {
                    "type": "section_heading",
                    "node_uid": toc_node.node_uid,
                    "text": section.title,
                    "style_name": "Normal",
                }
            )

            for paragraph in section.paragraphs:
                blocks.append(
                    {
                        "type": "paragraph",
                        "node_uid": toc_node.node_uid,
                        "text": paragraph.text,
                        "style_name": "Normal",
                        "paragraph_id": paragraph.paragraph_id,
                        "source_refs": paragraph.source_refs,
                        "anchors": paragraph.anchors,
                    }
                )
                matched_tables, pending_tables = self._pop_tables_by_anchors(
                    pending_tables,
                    paragraph.anchors,
                )
                matched_images, pending_images = self._pop_images_by_anchors(
                    pending_images,
                    paragraph.anchors,
                    node_dir,
                    warnings,
                )
                blocks.extend(matched_tables)
                blocks.extend(matched_images)

            section_images, pending_images = self._pop_images_by_section(
                pending_images,
                section.title,
                node_dir,
                warnings,
            )
            blocks.extend(section_images)

        for item in node_text.highlight_paragraphs:
            blocks.append(
                {
                    "type": "paragraph",
                    "node_uid": toc_node.node_uid,
                    "text": item.text,
                    "style_name": "Normal",
                    "paragraph_id": item.paragraph_id,
                    "source_refs": [],
                    "anchors": [],
                }
            )

        for table in pending_tables:
            warnings.append(
                f"Table {table.table_id} of node {toc_node.node_uid} missing anchor; appended to node end."
            )
            blocks.append(self._table_block(table, toc_node.node_uid))

        for image in pending_images:
            if getattr(image, "status", None) and str(image.status) != "PASS":
                warnings.append(
                    f"Image {image.image_id} of node {toc_node.node_uid} is {image.status}; skipped."
                )
                continue
            warnings.append(
                f"Image {image.image_id} of node {toc_node.node_uid} missing anchor; appended to node end."
            )
            image_block = self._image_block(image, node_dir)
            if image_block is None:
                warnings.append(
                    f"Image file missing for {image.image_id} of node {toc_node.node_uid}; skipped."
                )
                continue
            blocks.append(image_block)

    def _load_tables(self, node_dir: Path) -> TablesArtifact:
        path = node_dir / "tables.json"
        if not path.exists():
            return TablesArtifact(node_uid=node_dir.name, tables=[])
        return TablesArtifact.model_validate(json.loads(path.read_text(encoding="utf-8")))

    def _load_images(self, node_dir: Path) -> ImagesArtifact:
        path = node_dir / "images.json"
        if not path.exists():
            return ImagesArtifact(node_uid=node_dir.name, images=[])
        return ImagesArtifact.model_validate(json.loads(path.read_text(encoding="utf-8")))

    def _pop_tables_by_anchors(
        self,
        tables: list[Any],
        anchors: list[str],
    ) -> tuple[list[dict[str, Any]], list[Any]]:
        if not anchors:
            return [], tables
        matched: list[dict[str, Any]] = []
        remaining: list[Any] = []
        anchor_set = set(anchors)
        for table in tables:
            if table.bind_anchor and table.bind_anchor in anchor_set:
                matched.append(self._table_block(table, None))
            else:
                remaining.append(table)
        return matched, remaining

    def _pop_images_by_anchors(
        self,
        images: list[Any],
        anchors: list[str],
        node_dir: Path,
        warnings: list[str],
    ) -> tuple[list[dict[str, Any]], list[Any]]:
        if not anchors:
            return [], images
        matched: list[dict[str, Any]] = []
        remaining: list[Any] = []
        anchor_set = set(anchors)
        for image in images:
            if getattr(image, "status", None) and str(image.status) != "PASS":
                warnings.append(
                    f"Image {image.image_id} of node {node_dir.name} is {image.status}; skipped."
                )
                continue
            image_block = self._image_block(image, node_dir)
            if image.bind_anchor and image.bind_anchor in anchor_set:
                if image_block is None:
                    warnings.append(
                        f"Image file missing for {image.image_id} of node {node_dir.name}; skipped."
                    )
                    continue
                matched.append(image_block)
            else:
                remaining.append(image)
        return matched, remaining

    def _pop_images_by_section(
        self,
        images: list[Any],
        section_title: str,
        node_dir: Path,
        warnings: list[str],
    ) -> tuple[list[dict[str, Any]], list[Any]]:
        matched: list[dict[str, Any]] = []
        remaining: list[Any] = []
        for image in images:
            if getattr(image, "status", None) and str(image.status) != "PASS":
                warnings.append(
                    f"Image {image.image_id} of node {node_dir.name} is {image.status}; skipped."
                )
                continue
            image_block = self._image_block(image, node_dir)
            if image.bind_section and image.bind_section == section_title:
                if image_block is None:
                    warnings.append(
                        f"Image file missing for {image.image_id} of node {node_dir.name}; skipped."
                    )
                    continue
                matched.append(image_block)
            else:
                remaining.append(image)
        return matched, remaining

    @staticmethod
    def _table_block(table: Any, node_uid: str | None) -> dict[str, Any]:
        return {
            "type": "table",
            "node_uid": node_uid,
            "table_id": table.table_id,
            "title": table.title,
            "headers": table.headers,
            "rows": table.rows[: LayoutAgent.MAX_TABLE_ROWS],
            "style_name": table.style_name or "BiddingTable",
            "source_refs": table.source_refs,
        }

    @staticmethod
    def _image_block(image: Any, node_dir: Path) -> dict[str, Any] | None:
        image_path = Path(image.file)
        if not image_path.is_absolute():
            image_path = node_dir / image.file
        if not image_path.exists():
            return None
        return {
            "type": "image",
            "image_id": image.image_id,
            "path": str(image_path),
            "caption": image.caption,
            "group_caption": image.group_caption,
            "bind_anchor": image.bind_anchor,
            "bind_section": image.bind_section,
        }

    @staticmethod
    def _heading_style_for_level(level: int) -> str:
        resolved = min(max(level, 1), 9)
        style_map = {
            1: "一级标题",
            2: "二级标题",
            3: "三级标题",
            4: "四级标题",
        }
        return style_map.get(resolved, f"Heading {resolved}")

    def _visible_outline(self, nodes: list[TOCNode]) -> tuple[list[TOCNode], int]:
        if (
            len(nodes) == 1
            and not nodes[0].is_generation_unit
            and nodes[0].title.strip() == "工程实施方案"
            and nodes[0].children
        ):
            return nodes[0].children, nodes[0].level
        min_level = min((node.level for node in nodes), default=1) - 1
        return nodes, max(0, min_level)

    def _filter_tables_for_node(
        self,
        *,
        node_title: str,
        tables: list[Any],
        node_uid: str,
        warnings: list[str],
    ) -> list[Any]:
        if not tables:
            return []

        preferred_kind: str | None = None
        title = node_title.strip()
        if any(token in title for token in ("标准", "验收", "规范", "资质", "合规")):
            preferred_kind = "constraint"
        elif any(token in title for token in ("接口", "联调", "集成", "通讯", "控制", "PLC", "上位系统", "自控")):
            preferred_kind = "interface"
        elif any(
            token in title
            for token in ("热泵", "换热器", "水泵", "阀门", "桥架", "电缆", "装置", "设备", "机组", "参数")
        ):
            if any(
                token in title
                for token in ("配置", "参数", "选型", "品牌", "材质", "工况", "清单", "技术响应", "组成", "档次")
            ) or (
                any(token in title for token in ("热泵", "换热器", "水泵", "阀门", "桥架", "电缆", "装置", "机组"))
                and any(token in title for token in ("技术要求", "技术响应"))
            ):
                preferred_kind = "equipment"
        else:
            warnings.append(f"Tables of node {node_uid} skipped for narrative title: {node_title}")
            return []

        if preferred_kind is None:
            warnings.append(f"Tables of node {node_uid} skipped after relevance filter: {node_title}")
            return []

        selected: list[Any] = []
        for table in tables:
            table_title = str(getattr(table, "title", "") or "")
            if preferred_kind == "constraint" and "标准" not in table_title and "验收" not in table_title:
                continue
            if preferred_kind == "interface" and "接口" not in table_title and "联动" not in table_title:
                continue
            if preferred_kind == "equipment" and "设备" not in table_title and "参数" not in table_title:
                continue
            selected.append(table)
            break

        if not selected:
            return []

        if len(selected[0].rows) > self.MAX_TABLE_ROWS:
            warnings.append(
                f"Table {selected[0].table_id} of node {node_uid} truncated to {self.MAX_TABLE_ROWS} rows."
            )
        return selected
