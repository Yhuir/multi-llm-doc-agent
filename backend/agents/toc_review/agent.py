"""Rule-based TOC review chat agent for V1 skeleton."""

from __future__ import annotations

import copy
import uuid

from backend.models.schemas import TOCDocument, TOCNode


class TOCReviewChatAgent:
    """Apply user feedback to existing TOC document with stable node_uid."""

    def review(self, *, toc_doc: TOCDocument, feedback: str) -> TOCDocument:
        updated = copy.deepcopy(toc_doc)
        normalized = feedback.lower().strip()

        level2 = updated.tree[0].children[0] if updated.tree and updated.tree[0].children else None
        if level2 is None:
            return updated

        level3_nodes = [node for node in level2.children if node.level == 3]
        if not level3_nodes:
            return updated

        if any(token in normalized for token in ["add", "新增", "增加"]):
            self._add_level3_node(level2, len(level3_nodes) + 1)
        elif any(token in normalized for token in ["remove", "删除", "移除"]) and len(level3_nodes) > 1:
            level2.children.pop()
        elif any(token in normalized for token in ["reorder", "排序", "顺序"]):
            level2.children = list(reversed(level2.children))
        else:
            level3_nodes[0].title = f"{level3_nodes[0].title}（修订）"

        self._renumber(level2)
        return updated

    def _add_level3_node(self, level2: TOCNode, next_index: int) -> None:
        level2.children.append(
            TOCNode(
                node_uid=f"uid_l3_{uuid.uuid4().hex[:8]}",
                node_id=f"1.1.{next_index}",
                level=3,
                title=f"新增节点{next_index}",
                is_generation_unit=True,
                constraints={
                    "min_words": 1800,
                    "recommended_words": [1800, 2200],
                    "images": [2, 3],
                },
                source_refs=[],
                children=[],
            )
        )

    def _renumber(self, level2: TOCNode) -> None:
        for idx, level3 in enumerate(level2.children, start=1):
            level3.node_id = f"1.1.{idx}"
            if level3.children:
                for child_idx, level4 in enumerate(level3.children, start=1):
                    level4.node_id = f"{level3.node_id}.{child_idx}"
