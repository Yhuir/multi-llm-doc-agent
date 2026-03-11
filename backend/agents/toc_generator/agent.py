"""LLM-driven TOC generator agent for V1."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from typing import Any
from urllib import error as urlerror
from urllib import request as urlrequest

from backend.models.schemas import RequirementDocument, TOCDocument, TOCNode


@dataclass(slots=True)
class _DraftNode:
    title: str
    children: list["_DraftNode"] = field(default_factory=list)


class TOCGeneratorAgent:
    """Generate a TOC from the parsed requirement by calling the configured text model."""

    _MINIMAX_TEXT_ENDPOINT = "https://api.minimaxi.com/v1/text/chatcompletion_v2"
    _JSON_BLOCK_PATTERN = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", flags=re.S)
    _LINE_NO_PATTERN = re.compile(r"#L(\d+)$")

    def generate(
        self,
        *,
        requirement: RequirementDocument,
        version_no: int,
        generation_config: dict[str, Any] | None = None,
    ) -> TOCDocument:
        config = generation_config or {}
        provider = str(config.get("text_provider") or "").strip().lower()
        model_name = str(config.get("text_model_name") or "MiniMax-M2.5").strip() or "MiniMax-M2.5"
        api_key = str(config.get("text_api_key") or "").strip()

        if provider != "minimax":
            raise ValueError(
                "TOC generation requires a supported text model provider. "
                f"Current provider: {provider or 'unset'}."
            )
        if not api_key:
            raise ValueError("TOC generation requires `text_api_key`. Please configure the text model first.")

        source_lines = self._source_lines(requirement)
        if not source_lines:
            raise ValueError("requirement.json does not contain parsed source text.")

        prompt = self._build_generation_prompt(requirement=requirement, source_lines=source_lines)
        content = self._request_minimax_completion(
            api_key=api_key,
            model_name=model_name,
            prompt=prompt,
        )
        draft_root = self._parse_model_output_with_repair(
            requirement=requirement,
            model_name=model_name,
            api_key=api_key,
            initial_content=content,
        )
        root = self._materialize_tree(draft_root=draft_root, requirement=requirement)
        self._validate_subsystem_coverage(requirement=requirement, tree=[root])
        return TOCDocument(version=version_no, based_on_version=None, tree=[root])

    def _request_minimax_completion(self, *, api_key: str, model_name: str, prompt: str) -> str:
        payload = {
            "model": model_name,
            "messages": [
                {
                    "role": "system",
                    "name": "TOC Generator",
                    "content": (
                        "你是工程实施文档目录生成器。"
                        "必须基于用户上传文档的全文解析结果生成目录，禁止套用任何预设模板。"
                    ),
                },
                {"role": "user", "name": "user", "content": prompt},
            ],
            "temperature": 0.2,
        }
        req = urlrequest.Request(
            self._MINIMAX_TEXT_ENDPOINT,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}",
            },
            method="POST",
        )

        try:
            with urlrequest.urlopen(req, timeout=240) as response:
                body = response.read().decode("utf-8")
        except urlerror.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="ignore")
            raise ValueError(f"TOC generation model request failed: HTTP {exc.code} {detail}") from exc
        except (urlerror.URLError, TimeoutError) as exc:
            raise ValueError(f"TOC generation model request failed: {exc}") from exc

        try:
            data = json.loads(body)
        except json.JSONDecodeError as exc:
            raise ValueError("TOC generation model returned invalid JSON payload.") from exc

        base_resp = data.get("base_resp") or {}
        status_code = base_resp.get("status_code")
        if status_code not in (None, 0):
            raise ValueError(f"TOC generation model returned error: {base_resp.get('status_msg') or status_code}")

        content = (
            ((data.get("choices") or [{}])[0].get("message") or {}).get("content")
            if isinstance(data.get("choices"), list)
            else None
        )
        if not isinstance(content, str) or not content.strip():
            raise ValueError("TOC generation model returned empty content.")
        return content

    def _build_generation_prompt(self, *, requirement: RequirementDocument, source_lines: list[str]) -> str:
        subsystem_lines = [
            f"- {subsystem.name}: {subsystem.description}"
            for subsystem in requirement.scope.subsystems
            if subsystem.name.strip()
        ]
        standard_lines = [f"- {item}" for item in requirement.constraints.standards if str(item).strip()]
        acceptance_lines = [f"- {item}" for item in requirement.constraints.acceptance if str(item).strip()]

        instructions = [
            "任务：根据以下 requirement 解析结果，生成工程实施文档目录树。",
            "硬性要求：",
            "1. 必须分析下方提供的全文解析内容；禁止仅依据项目名称猜测目录。",
            "2. 禁止使用任何预设目录模板、通用套话章节或固定章节骨架。",
            "3. 目录结构必须完全由上传文档的内容决定，可在不改变原意的前提下做工程化重组。",
            "4. 所有已识别的子系统、实施范围、约束、验收要点都必须在目录中得到覆盖。",
            "5. 目录层级优先使用一级、二级、三级；只有当三级主题仍然过宽、无法作为独立生成单元时，才允许拆成四级。",
            "6. 不要输出与原文无关的系统、设备、流程、标准或场景。",
            "7. 根节点标题可以工程化润色，但不能脱离项目实际内容。",
            "8. title 字段只保留章节语义名称，不要包含原文编号、章次、篇次或条次，例如不要写“第一章”“第十章”“1.10”“3.2.1”。",
            "9. 不要把 requirement 原文中的目录号、条款号、附件号复制进 title，例如不要写“1.8.5 售后服务团队”这种标题。",
            "10. 编号由系统生成并写入 node_id，模型不要把编号写进 title。",
            "11. 如果三级节点已经足够明确、可以独立展开写作，就不要继续拆成四级。",
            "12. 只输出 JSON，不要输出解释、前言、Markdown 或注释。",
            "",
            "输出 JSON 格式：",
            '{',
            '  "root_title": "一级标题",',
            '  "chapters": [',
            '    {',
            '      "title": "二级标题",',
            '      "children": [',
            '        {',
            '          "title": "三级标题",',
            '          "children": [',
            '            {"title": "四级标题", "children": []}',
            "          ]",
            "        }",
            "      ]",
            "    }",
            "  ]",
            '}',
            "约束：二级标题不能是叶子节点；叶子节点只能出现在三级或四级；禁止超过四级。",
            "",
            f"项目名称：{requirement.project.name or '未提取'}",
            f"范围概述：{requirement.scope.overview or '未提取'}",
            "",
            "已识别子系统：",
            *(subsystem_lines or ["- 无明确子系统，需从全文自行归纳。"]),
            "",
            "已识别标准约束：",
            *(standard_lines or ["- 无"]),
            "",
            "已识别验收要求：",
            *(acceptance_lines or ["- 无"]),
            "",
            "全文解析内容（必须通读并据此生成目录）：",
            *source_lines,
        ]
        return "\n".join(instructions)

    def _parse_model_output(self, content: str) -> _DraftNode:
        payload = self._extract_json_payload(content)
        root_title = self._clean_title(payload.get("root_title") or payload.get("title") or "")
        chapter_items = payload.get("chapters")
        if chapter_items is None:
            chapter_items = payload.get("children")
        if chapter_items is None and isinstance(payload.get("tree"), list):
            tree = payload["tree"]
            if len(tree) == 1 and isinstance(tree[0], dict):
                root_candidate = tree[0]
                root_title = self._clean_title(root_title or root_candidate.get("title") or "")
                chapter_items = root_candidate.get("children", [])
        if not root_title:
            raise ValueError("TOC generation model did not return a valid root title.")
        if not isinstance(chapter_items, list) or not chapter_items:
            raise ValueError("TOC generation model did not return any TOC chapters.")

        draft_root = _DraftNode(title=root_title, children=self._parse_draft_nodes(chapter_items, depth=2))
        self._validate_draft_tree(draft_root)
        return draft_root

    def _parse_model_output_with_repair(
        self,
        *,
        requirement: RequirementDocument,
        model_name: str,
        api_key: str,
        initial_content: str,
    ) -> _DraftNode:
        content = initial_content
        last_error: ValueError | None = None
        for attempt in range(2):
            try:
                return self._parse_model_output(content)
            except ValueError as exc:
                last_error = exc
                if attempt >= 1:
                    break
                repair_prompt = self._build_repair_prompt(
                    requirement=requirement,
                    invalid_output=content,
                    validation_error=str(exc),
                )
                content = self._request_minimax_completion(
                    api_key=api_key,
                    model_name=model_name,
                    prompt=repair_prompt,
                )
        assert last_error is not None
        raise last_error

    def _extract_json_payload(self, content: str) -> dict[str, Any]:
        candidates = self._JSON_BLOCK_PATTERN.findall(content)
        first = content.find("{")
        last = content.rfind("}")
        if first != -1 and last != -1 and first < last:
            candidates.append(content[first : last + 1])

        for candidate in candidates:
            try:
                payload = json.loads(candidate)
            except json.JSONDecodeError:
                continue
            if isinstance(payload, dict):
                return payload
        raise ValueError("TOC generation model did not return parsable JSON.")

    def _build_repair_prompt(
        self,
        *,
        requirement: RequirementDocument,
        invalid_output: str,
        validation_error: str,
    ) -> str:
        source_lines = self._source_lines(requirement)
        instructions = [
            "任务：修正下面这个不合规的目录树 JSON。",
            "修正原因：",
            validation_error,
            "",
            "修正要求：",
            "1. 保留原目录的业务语义和主题覆盖，不要改成固定模板。",
            "2. 最小生成单元必须是三级或四级标题。",
            "3. 二级标题不能直接作为生成单元，若当前二级标题过浅，必须拆成合适的三级标题。",
            "4. 目录层级优先使用一级、二级、三级；只有三级仍然过宽时，才允许四级。",
            "5. title 只保留语义名称，不要带编号、章次、条款号。",
            "6. 只输出修正后的 JSON，不要输出解释。",
            "",
            "项目名称：",
            requirement.project.name or "未提取",
            "",
            "范围概述：",
            requirement.scope.overview or "未提取",
            "",
            "全文解析内容摘要（用于保持覆盖关系）：",
            *source_lines[:120],
            "",
            "待修正的目录 JSON：",
            invalid_output,
        ]
        return "\n".join(instructions)

    def _parse_draft_nodes(self, items: list[Any], *, depth: int) -> list[_DraftNode]:
        if not items:
            return []

        nodes: list[_DraftNode] = []
        for item in items:
            nodes.extend(self._parse_draft_item(item, depth=depth))
        return nodes

    def _parse_draft_item(self, item: Any, *, depth: int) -> list[_DraftNode]:
        if not isinstance(item, dict):
            raise ValueError("TOC generation model returned invalid node entries.")
        title = self._clean_title(item.get("title") or "")
        if not title:
            raise ValueError("TOC generation model returned an empty title.")

        raw_children = item.get("children")
        if raw_children is None:
            raw_children = item.get("sections")
        if raw_children is None:
            raw_children = item.get("nodes")
        child_items = raw_children or []

        if depth < 4:
            children = self._parse_draft_nodes(child_items, depth=depth + 1)
            return [_DraftNode(title=title, children=children)]

        if not child_items:
            return [_DraftNode(title=title, children=[])]

        collapsed_titles = self._collapse_overdeep_titles(child_items, prefix=title)
        if not collapsed_titles:
            return [_DraftNode(title=title, children=[])]
        return [_DraftNode(title=collapsed_title, children=[]) for collapsed_title in collapsed_titles]

    def _collapse_overdeep_titles(self, items: list[Any], *, prefix: str) -> list[str]:
        collapsed: list[str] = []
        for item in items:
            if not isinstance(item, dict):
                raise ValueError("TOC generation model returned invalid node entries.")
            title = self._clean_title(item.get("title") or "")
            if not title:
                raise ValueError("TOC generation model returned an empty title.")
            merged_title = self._merge_titles(prefix, title)

            raw_children = item.get("children")
            if raw_children is None:
                raw_children = item.get("sections")
            if raw_children is None:
                raw_children = item.get("nodes")
            child_items = raw_children or []

            if child_items:
                collapsed.extend(self._collapse_overdeep_titles(child_items, prefix=merged_title))
            else:
                collapsed.append(merged_title)
        return self._deduplicate_titles(collapsed)

    def _validate_draft_tree(self, root: _DraftNode) -> None:
        generation_unit_count = 0

        def walk(node: _DraftNode, depth: int) -> None:
            nonlocal generation_unit_count
            if depth == 1 and not node.children:
                raise ValueError("TOC root must contain child chapters.")
            if depth == 2 and not node.children:
                raise ValueError("TOC second-level chapters cannot be generation-unit leaves.")
            if depth >= 4 and node.children:
                raise ValueError("TOC cannot contain children below level 4.")
            if not node.children:
                if depth < 3:
                    raise ValueError("TOC leaves must be level 3 or level 4.")
                generation_unit_count += 1
            for child in node.children:
                walk(child, depth + 1)

        walk(root, 1)
        if generation_unit_count == 0:
            raise ValueError("TOC generation model did not return any level 3 or level 4 generation units.")

    def _materialize_tree(self, *, draft_root: _DraftNode, requirement: RequirementDocument) -> TOCNode:
        root_refs = self._match_source_refs(requirement, [draft_root.title], limit=10)
        root = TOCNode(
            node_uid="uid_root_001",
            node_id="1",
            level=1,
            title=draft_root.title,
            is_generation_unit=False,
            source_refs=root_refs,
            children=[],
        )
        root.children = self._materialize_children(
            draft_nodes=draft_root.children,
            parent=root,
            parent_path=[draft_root.title],
            requirement=requirement,
        )
        return root

    def _materialize_children(
        self,
        *,
        draft_nodes: list[_DraftNode],
        parent: TOCNode,
        parent_path: list[str],
        requirement: RequirementDocument,
    ) -> list[TOCNode]:
        siblings: list[TOCNode] = []
        title_counts: dict[str, int] = {}
        for index, draft in enumerate(draft_nodes, start=1):
            normalized = self._normalize_token(draft.title)
            title_counts[normalized] = title_counts.get(normalized, 0) + 1
            level = parent.level + 1
            node_path = [*parent_path, draft.title]
            seed = "::".join(
                [
                    *[self._normalize_token(item) for item in node_path],
                    f"sibling{title_counts[normalized]}",
                ]
            )
            source_refs = self._match_source_refs(
                requirement,
                [draft.title, parent.title],
                fallback=parent.source_refs,
            )
            node = TOCNode(
                node_uid=self._stable_uid(f"l{level}", seed),
                node_id=f"{parent.node_id}.{index}",
                level=level,
                title=draft.title,
                is_generation_unit=not draft.children,
                constraints=self._generation_constraints() if not draft.children else None,
                source_refs=source_refs,
                children=[],
            )
            if draft.children:
                node.is_generation_unit = False
                node.children = self._materialize_children(
                    draft_nodes=draft.children,
                    parent=node,
                    parent_path=node_path,
                    requirement=requirement,
                )
            siblings.append(node)
        return siblings

    def _validate_subsystem_coverage(self, *, requirement: RequirementDocument, tree: list[TOCNode]) -> None:
        subsystem_names = [
            self._coverage_key(subsystem.name)
            for subsystem in requirement.scope.subsystems
            if self._is_meaningful_subsystem_name(subsystem.name)
        ]
        if not subsystem_names:
            return

        toc_text = self._coverage_key("\n".join(self._flatten_titles(tree)))
        missing = [
            name
            for name in subsystem_names
            if name and name not in toc_text
        ]
        max_missing_without_error = 1 if len(subsystem_names) <= 2 else max(1, len(subsystem_names) // 3)
        if len(missing) > max_missing_without_error:
            missing_preview = "、".join(missing[:5])
            raise ValueError(
                "TOC generation omitted parsed subsystem coverage. "
                f"Missing subsystem titles: {missing_preview}"
            )

    def _flatten_titles(self, nodes: list[TOCNode]) -> list[str]:
        titles: list[str] = []
        for node in nodes:
            titles.append(node.title)
            titles.extend(self._flatten_titles(node.children))
        return titles

    def _match_source_refs(
        self,
        requirement: RequirementDocument,
        keywords: list[str],
        *,
        fallback: list[str] | None = None,
        limit: int = 10,
    ) -> list[str]:
        normalized_keywords = [self._clean_title(keyword) for keyword in keywords if self._clean_title(keyword)]
        source_refs: list[str] = []
        for source_ref, item in sorted(
            requirement.source_index.items(),
            key=lambda pair: self._line_no_from_source_ref(pair[0]),
        ):
            text = self._clean_title(item.text)
            if any(keyword and keyword in text for keyword in normalized_keywords):
                source_refs.append(source_ref)
            if len(source_refs) >= limit:
                break
        if source_refs:
            return source_refs
        if fallback:
            return fallback[:limit]
        return list(requirement.source_index.keys())[:limit]

    def _source_lines(self, requirement: RequirementDocument) -> list[str]:
        lines: list[str] = []
        for source_ref, item in sorted(
            requirement.source_index.items(),
            key=lambda pair: self._line_no_from_source_ref(pair[0]),
        ):
            lines.append(f"{source_ref} [{item.paragraph_id}] {item.text}")
        return lines

    def _clean_title(self, title: str) -> str:
        cleaned = re.sub(r"\s+", "", str(title))
        original = cleaned.strip("，。；：- ")
        previous = None
        while cleaned and cleaned != previous:
            previous = cleaned
            cleaned = re.sub(r"^[0-9]+(?:[.．][0-9]+)*(?:[.．、\-])?", "", cleaned)
            cleaned = re.sub(r"^[（(]?[一二三四五六七八九十百千万0-9]+[)）.、]+", "", cleaned)
            cleaned = re.sub(r"^第[一二三四五六七八九十百千万0-9]+[章节篇部分卷编回节]\s*", "", cleaned)
            cleaned = cleaned.strip("，。；：- ")
        return cleaned or original

    def _normalize_token(self, text: str) -> str:
        cleaned = re.sub(r"[^0-9A-Za-z\u4e00-\u9fff]+", "", self._clean_title(text))
        return cleaned.lower()[:96]

    def _merge_titles(self, prefix: str, title: str) -> str:
        left = self._clean_title(prefix)
        right = self._clean_title(title)
        if not left:
            return right
        if not right:
            return left
        if left == right:
            return left
        if right in left:
            return left
        if left in right:
            return right
        return f"{left}：{right}"

    def _deduplicate_titles(self, titles: list[str]) -> list[str]:
        deduplicated: list[str] = []
        seen: set[str] = set()
        for title in titles:
            normalized = self._normalize_token(title)
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            deduplicated.append(title)
        return deduplicated

    def _coverage_key(self, text: str) -> str:
        cleaned = self._normalize_token(text)
        for suffix in ("子系统", "系统", "平台", "模块", "装置"):
            normalized_suffix = self._normalize_token(suffix)
            if cleaned.endswith(normalized_suffix) and len(cleaned) > len(normalized_suffix):
                cleaned = cleaned[: -len(normalized_suffix)]
                break
        return cleaned

    def _is_meaningful_subsystem_name(self, text: str) -> bool:
        cleaned = self._clean_title(text)
        if len(cleaned) < 3:
            return False
        keywords = (
            "系统",
            "子系统",
            "平台",
            "模块",
            "装置",
            "控制",
            "监控",
            "网络",
            "数据库",
            "PLC",
            "SCADA",
            "配电",
            "机柜",
            "交换机",
            "站",
        )
        return any(keyword.lower() in cleaned.lower() for keyword in keywords)

    def _line_no_from_source_ref(self, source_ref: str) -> int:
        match = self._LINE_NO_PATTERN.search(source_ref)
        if match is None:
            return 0
        return int(match.group(1))

    def _stable_uid(self, level: str, seed: str) -> str:
        digest = hashlib.sha1(seed.encode("utf-8")).hexdigest()[:10]
        return f"uid_{level}_{digest}"

    def _generation_constraints(self) -> dict[str, Any]:
        return {
            "min_words": 1800,
            "recommended_words": [1800, 2200],
            "images": [2, 3],
        }
