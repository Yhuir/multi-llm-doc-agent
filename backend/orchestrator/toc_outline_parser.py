"""Parse pasted outline text into an internal TOC document."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

from backend.models.schemas import TOCDocument, TOCNode

_CHINESE_CHAPTER_RE = re.compile(r"^\s*([一二三四五六七八九十百千]+)[、.．]\s*(.+?)\s*$")
_CHAPTER_TITLE_RE = re.compile(r"^\s*第([一二三四五六七八九十百千0-9]+)章\s+(.+?)\s*$")
_ARABIC_RE = re.compile(r"^\s*(\d+(?:\.\d+){0,3})[、.．\s]+\s*(.+?)\s*$")


@dataclass(frozen=True)
class ParsedOutlineLine:
    visible_level: int
    raw_number: str
    title: str


def build_toc_document_from_outline(
    outline_text: str,
    *,
    version_no: int,
    based_on_version: int | None = None,
    root_title: str = "工程实施方案",
) -> TOCDocument:
    parsed_lines = _parse_outline_lines(outline_text)
    root = TOCNode(
        node_uid="uid_root_001",
        node_id="1",
        level=1,
        title=root_title,
        is_generation_unit=False,
        children=[],
    )

    stack: list[TOCNode] = [root]
    for item in parsed_lines:
        internal_level = item.visible_level + 1
        if internal_level > 4:
            raise ValueError("目录树最多支持到四级，请将最小生成单元控制在三级或四级。")

        while len(stack) >= internal_level:
            stack.pop()

        if len(stack) != internal_level - 1:
            raise ValueError(f"目录层级缺少父节点，请检查这一行前后的层级关系：{item.raw_number} {item.title}")

        parent = stack[-1]
        node = TOCNode(
            node_uid=_stable_uid(internal_level, f"{parent.node_uid}::{item.raw_number}::{_normalize_title(item.title)}"),
            node_id="",
            level=internal_level,
            title=item.title,
            is_generation_unit=False,
            children=[],
        )
        parent.children.append(node)
        stack.append(node)

    generation_units = _mark_generation_units(root)
    if generation_units == 0:
        raise ValueError("导入的目录树没有可生成的三级或四级叶子节点。")

    _renumber_node_ids([root])
    return TOCDocument(
        version=version_no,
        based_on_version=based_on_version,
        tree=[root],
    )


def _parse_outline_lines(outline_text: str) -> list[ParsedOutlineLine]:
    lines = [line.strip() for line in outline_text.splitlines() if line.strip()]
    if not lines:
        raise ValueError("目录树不能为空。")

    parsed: list[ParsedOutlineLine] = []
    for line in lines:
        chinese_chapter = _CHINESE_CHAPTER_RE.match(line)
        if chinese_chapter is not None:
            parsed.append(
                ParsedOutlineLine(
                    visible_level=1,
                    raw_number=chinese_chapter.group(1),
                    title=chinese_chapter.group(2).strip(),
                )
            )
            continue

        chapter_title = _CHAPTER_TITLE_RE.match(line)
        if chapter_title is not None:
            parsed.append(
                ParsedOutlineLine(
                    visible_level=1,
                    raw_number=chapter_title.group(1),
                    title=chapter_title.group(2).strip(),
                )
            )
            continue

        arabic = _ARABIC_RE.match(line)
        if arabic is not None:
            numbering = arabic.group(1).strip().rstrip(".")
            title = arabic.group(2).strip()
            parsed.append(
                ParsedOutlineLine(
                    visible_level=numbering.count(".") + 1,
                    raw_number=numbering,
                    title=title,
                )
            )
            continue

        raise ValueError(f"无法识别目录行格式：{line}")

    if parsed[0].visible_level != 1:
        raise ValueError("目录树必须从一级章节开始，例如“一、xxx”或“第一章 xxx”。")

    return parsed


def _mark_generation_units(root: TOCNode) -> int:
    count = 0

    def walk(node: TOCNode) -> None:
        nonlocal count
        if node.children:
            node.is_generation_unit = False
            node.constraints = None
            for child in node.children:
                walk(child)
            return

        if node.level < 3:
            raise ValueError(f"叶子节点层级不足，无法作为生成单元：{node.title}")

        node.is_generation_unit = True
        node.constraints = _generation_constraints()
        count += 1

    walk(root)
    return count


def _renumber_node_ids(tree: list[TOCNode]) -> None:
    for root_index, root in enumerate(tree, start=1):
        root.node_id = str(root_index)
        _renumber_children(root)


def _renumber_children(parent: TOCNode) -> None:
    for idx, child in enumerate(parent.children, start=1):
        child.node_id = f"{parent.node_id}.{idx}"
        _renumber_children(child)


def _generation_constraints() -> dict[str, object]:
    return {
        "min_words": 1800,
        "recommended_words": [1800, 2200],
        "images": [2, 3],
    }


def _stable_uid(level: int, seed: str) -> str:
    digest = hashlib.sha1(seed.encode("utf-8")).hexdigest()[:10]
    return f"uid_l{level}_{digest}"


def _normalize_title(text: str) -> str:
    cleaned = re.sub(r"^[0-9]+(?:\.[0-9]+)*", "", text)
    cleaned = re.sub(r"^[（(]?[一二三四五六七八九十百千0-9]+[)）.、]+", "", cleaned)
    cleaned = re.sub(r"[\s，。；：:、,.!！?？()（）【】\[\]<>《》“”\"'‘’\-_]+", "", cleaned)
    return cleaned.lower()
