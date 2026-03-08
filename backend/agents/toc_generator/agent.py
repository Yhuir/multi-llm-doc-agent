"""Rule-based TOC generator agent for V1 skeleton."""

from __future__ import annotations

from backend.models.schemas import RequirementDocument, TOCDocument, TOCNode


class TOCGeneratorAgent:
    """Generate toc_v1 using stable node_uid / node_id strategy."""

    def generate(self, *, requirement: RequirementDocument, version_no: int) -> TOCDocument:
        root = TOCNode(
            node_uid="uid_root_001",
            node_id="1",
            level=1,
            title="工程实施方案",
            is_generation_unit=False,
            children=[],
        )
        level2 = TOCNode(
            node_uid="uid_l2_001",
            node_id="1.1",
            level=2,
            title=requirement.project.name or "项目实施方案",
            is_generation_unit=False,
            children=[],
        )
        root.children.append(level2)

        for idx, subsystem in enumerate(requirement.scope.subsystems, start=1):
            l3_uid = f"uid_l3_{idx:03d}"
            l3_node = TOCNode(
                node_uid=l3_uid,
                node_id=f"1.1.{idx}",
                level=3,
                title=subsystem.name,
                is_generation_unit=True,
                constraints={
                    "min_words": 1800,
                    "recommended_words": [1800, 2200],
                    "images": [2, 3],
                },
                source_refs=self._subsystem_source_refs(subsystem),
                children=[],
            )

            if self._need_level4(subsystem):
                l3_node.is_generation_unit = False
                l3_node.children = self._build_level4_nodes(parent=l3_node, index=idx)

            level2.children.append(l3_node)

        return TOCDocument(version=version_no, based_on_version=None, tree=[root])

    def _need_level4(self, subsystem) -> bool:
        title = subsystem.name
        description = subsystem.description or ""

        # Rule 1: likely multi-module expression
        multi_module = any(token in title + description for token in ["及", "与", "、", "模块", "子系统"])

        # Rule 2: title too broad
        broad_title = any(token in title for token in ["总体", "综合", "概述", "其他", "通用"])

        # Rule 3: likely too short for >=1800 words by heuristic
        short_context = len(description.strip()) < 24

        # Rule 4: too many requirements may cause mixing
        too_many_clauses = len(subsystem.requirements) >= 5

        return multi_module or broad_title or short_context or too_many_clauses

    def _build_level4_nodes(self, *, parent: TOCNode, index: int) -> list[TOCNode]:
        prefixes = ["实施准备", "实施与验收"]
        nodes: list[TOCNode] = []
        for child_index, title_suffix in enumerate(prefixes, start=1):
            nodes.append(
                TOCNode(
                    node_uid=f"uid_l4_{index:03d}_{child_index:02d}",
                    node_id=f"{parent.node_id}.{child_index}",
                    level=4,
                    title=f"{parent.title}-{title_suffix}",
                    is_generation_unit=True,
                    constraints={
                        "min_words": 1800,
                        "recommended_words": [1800, 2200],
                        "images": [2, 3],
                    },
                    source_refs=parent.source_refs,
                    children=[],
                )
            )
        return nodes

    def _subsystem_source_refs(self, subsystem) -> list[str]:
        refs = [item.source_ref for item in subsystem.requirements if item.source_ref]
        return refs[:10]
