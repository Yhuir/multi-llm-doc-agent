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
    _WHATAI_TEXT_ENDPOINT = "https://api.whatai.cc/v1/chat/completions"
    _JSON_BLOCK_PATTERN = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", flags=re.S)
    _LINE_NO_PATTERN = re.compile(r"#L(\d+)$")

    def generate(
        self,
        *,
        requirement: RequirementDocument,
        version_no: int,
        generation_config: dict[str, Any] | None = None,
    ) -> TOCDocument:
        source_lines = self._source_lines(requirement)
        if not source_lines:
            raise ValueError("requirement.json does not contain parsed source text.")

        prompt = self._build_generation_prompt(requirement=requirement, source_lines=source_lines)
        return self._generate_from_prompt(
            requirement=requirement,
            version_no=version_no,
            based_on_version=None,
            generation_config=generation_config,
            prompt=prompt,
            outline_guidance=None,
        )

    def generate_from_outline(
        self,
        *,
        requirement: RequirementDocument,
        outline_guidance: TOCDocument,
        version_no: int,
        based_on_version: int | None = None,
        generation_config: dict[str, Any] | None = None,
    ) -> TOCDocument:
        source_lines = self._source_lines(requirement)
        if not source_lines:
            raise ValueError("requirement.json does not contain parsed source text.")

        prompt = self._build_outline_guided_prompt(
            requirement=requirement,
            source_lines=source_lines,
            outline_guidance=outline_guidance,
        )
        return self._generate_from_prompt(
            requirement=requirement,
            version_no=version_no,
            based_on_version=based_on_version,
            generation_config=generation_config,
            prompt=prompt,
            outline_guidance=outline_guidance,
        )

    def _generate_from_prompt(
        self,
        *,
        requirement: RequirementDocument,
        version_no: int,
        based_on_version: int | None,
        generation_config: dict[str, Any] | None,
        prompt: str,
        outline_guidance: TOCDocument | None,
    ) -> TOCDocument:
        provider, model_name, api_key = self._resolve_generation_config(generation_config)
        request_fn = (
            self._request_minimax_completion
            if provider == "minimax"
            else self._request_whatai_completion
        )
        content = request_fn(
            api_key=api_key,
            model_name=model_name,
            prompt=prompt,
        )
        draft_root = self._parse_model_output_with_repair(
            requirement=requirement,
            provider=provider,
            model_name=model_name,
            api_key=api_key,
            initial_content=content,
            outline_guidance=outline_guidance,
        )
        root = self._materialize_tree(draft_root=draft_root, requirement=requirement)
        return TOCDocument(version=version_no, based_on_version=based_on_version, tree=[root])

    def _resolve_generation_config(self, generation_config: dict[str, Any] | None) -> tuple[str, str, str]:
        config = generation_config or {}
        provider = str(config.get("text_provider") or "").strip().lower()
        model_name = str(config.get("text_model_name") or "MiniMax-M2.5").strip() or "MiniMax-M2.5"
        api_key = str(config.get("text_api_key") or "").strip()

        if provider not in {"minimax", "whatai", "google"}:
            raise ValueError(
                "TOC generation requires a supported text model provider. "
                f"Current provider: {provider or 'unset'}."
            )
        if not api_key:
            raise ValueError("TOC generation requires `text_api_key`. Please configure the text model first.")
        return provider, model_name, api_key

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

    def _request_whatai_completion(self, *, api_key: str, model_name: str, prompt: str) -> str:
        payload = {
            "model": model_name,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "你是工程实施文档目录生成器。"
                        "必须基于用户上传文档的全文解析结果生成目录，禁止套用任何预设模板。"
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.2,
        }
        req = urlrequest.Request(
            self._WHATAI_TEXT_ENDPOINT,
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

        if data.get("error"):
            raise ValueError(f"TOC generation model returned error: {data['error']}")

        content = (
            ((data.get("choices") or [{}])[0].get("message") or {}).get("content")
            if isinstance(data.get("choices"), list)
            else None
        )
        if not isinstance(content, str) or not content.strip():
            raise ValueError("TOC generation model returned empty content.")
        return content

    def _build_generation_prompt(self, *, requirement: RequirementDocument, source_lines: list[str]) -> str:
        bidding_requirement_lines = self._bidding_requirement_lines(requirement)
        standard_lines = [f"- {item}" for item in requirement.constraints.standards if str(item).strip()]
        acceptance_lines = [f"- {item}" for item in requirement.constraints.acceptance if str(item).strip()]

        instructions = [
            "任务：通读以下 requirement 全文解析内容，提炼其中的招标要求、实施范围、技术约束、验收要求和服务要求，生成工程实施文档目录树。",
            "硬性要求：",
            "1. 必须分析下方提供的全文解析内容，并从全文中提炼招标要求后再组织目录；禁止仅依据项目名称猜测目录。",
            "2. 禁止使用任何预设目录模板、通用套话章节或固定章节骨架。",
            "3. 目录结构必须完全由上传文档的内容决定，可在不改变原意的前提下做工程化重组。",
            "4. 用户可见目录层级优先使用一级、二级、三级；只有当三级主题仍然过宽、无法作为独立生成单元时，才允许拆成四级。",
            "5. 不要输出与原文无关的系统、设备、流程、标准或场景。",
            "6. root_title 是整份文档的总标题，不参与用户可见章节编号；chapters 数组中的节点才是用户可见一级目录。",
            "7. title 字段只保留章节语义名称，不要包含原文编号、章次、篇次或条次，例如不要写“第一章”“第十章”“1.10”“3.2.1”。",
            "8. 不要把 requirement 原文中的目录号、条款号、附件号复制进 title，例如不要写“1.8.5 售后服务团队”这种标题。",
            "9. 编号由系统生成并写入 node_id，模型不要把编号写进 title。",
            "10. 最小生成单元只能落在用户可见三级或四级标题，禁止用户可见一、二级标题直接作为生成单元。",
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
            '          "title": "二级标题下的三级标题",',
            '          "children": [',
            '            {',
            '              "title": "生成单元三级标题",',
            '              "children": [',
            '                {"title": "生成单元四级标题", "children": []}',
            "              ]",
            "            }",
            "          ]",
            "        }",
            "      ]",
            "    }",
            "  ]",
            '}',
            "约束：用户可见一级、二级标题都不能是生成叶子；叶子节点只能出现在用户可见三级或四级；禁止超过用户可见四级。",
            "",
            f"项目名称：{requirement.project.name or '未提取'}",
            f"范围概述：{requirement.scope.overview or '未提取'}",
            "",
            "已提取招标要求（必须优先覆盖，来源于全文分段解析）：",
            *(bidding_requirement_lines or ["- 无明确提取项，需从全文解析内容自行核对。"]),
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

    def _build_outline_guided_prompt(
        self,
        *,
        requirement: RequirementDocument,
        source_lines: list[str],
        outline_guidance: TOCDocument,
    ) -> str:
        bidding_requirement_lines = self._bidding_requirement_lines(requirement)
        outline_lines = self._outline_guidance_lines(outline_guidance)
        instructions = [
            "任务：通读以下 requirement 全文解析内容，提炼其中所有招标要求，并结合用户上传的目录树意图，重新生成一份最终目录树。",
            "硬性要求：",
            "1. 必须先通读全文 requirement 内容，提炼其中所有与招标范围、技术要求、实施要求、验收要求、培训与售后要求相关的章节主题。",
            "2. 用户上传的目录树只能作为结构意图和组织偏好参考，不能直接照抄成最终输出；必须经过全文 requirement 校核、重组和补全。",
            "3. 如果用户目录树遗漏了全文中的关键招标要求，必须补齐；如果用户目录树包含与全文不符或缺乏依据的标题，必须删除、合并或改写。",
            "4. 禁止使用任何预设目录模板、固定章节骨架或通用套话目录。",
            "5. 最终目录必须同时满足：来源于全文 requirement、尽量尊重用户目录树的组织意图、覆盖全文所有关键招标要求。",
            "6. 用户可见目录层级优先使用一级、二级、三级；只有当三级主题仍然过宽、无法作为独立生成单元时，才允许拆成四级。",
            "7. title 字段只保留章节语义名称，不要包含原文编号、章次、篇次或条次，例如不要写“第一章”“第十章”“1.10”“3.2.1”。",
            "8. 不要把用户上传目录树中的编号、原文条款号、附件号复制进 title，例如不要写“1.8.5 售后服务团队”。",
            "9. 编号由系统生成并写入 node_id，模型不要把编号写进 title。",
            "10. 最小生成单元只能落在用户可见三级或四级标题，禁止用户可见一、二级标题直接作为生成单元。",
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
            '          "title": "二级标题下的三级标题",',
            '          "children": [',
            '            {',
            '              "title": "生成单元三级标题",',
            '              "children": [',
            '                {"title": "生成单元四级标题", "children": []}',
            "              ]",
            "            }",
            "          ]",
            "        }",
            "      ]",
            "    }",
            "  ]",
            '}',
            "约束：用户可见一级、二级标题都不能是生成叶子；叶子节点只能出现在用户可见三级或四级；禁止超过用户可见四级。",
            "",
            f"项目名称：{requirement.project.name or '未提取'}",
            f"范围概述：{requirement.scope.overview or '未提取'}",
            "",
            "已提取招标要求（必须优先覆盖，来源于全文分段解析）：",
            *(bidding_requirement_lines or ["- 无明确提取项，需从全文 requirement 自行提炼。"]),
            "",
            "用户上传目录树（仅作为结构意图参考，最终输出必须由全文 requirement 决定）：",
            *(outline_lines or ["- 未提供有效的目录树结构。"]),
            "",
            "全文解析内容（必须通读并据此重建目录）：",
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
        provider: str,
        model_name: str,
        api_key: str,
        initial_content: str,
        outline_guidance: TOCDocument | None = None,
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
                    outline_guidance=outline_guidance,
                )
                request_fn = (
                    self._request_minimax_completion
                    if provider == "minimax"
                    else self._request_whatai_completion
                )
                content = request_fn(
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
        outline_guidance: TOCDocument | None = None,
    ) -> str:
        source_lines = self._source_lines(requirement)
        bidding_requirement_lines = self._bidding_requirement_lines(requirement)
        outline_lines = self._outline_guidance_lines(outline_guidance) if outline_guidance is not None else []
        instructions = [
            "任务：修正下面这个不合规的目录树 JSON。",
            "修正原因：",
            validation_error,
            "",
            "修正要求：",
            "1. 保留原目录的业务语义和主题覆盖，不要改成固定模板。",
            "1.1 如果存在用户上传目录树，需在全文 requirement 约束下尽量保留其有效结构意图，但不能照抄无依据标题。",
            "2. root_title 只是整份文档标题，不参与用户可见层级编号。",
            "3. 最小生成单元必须是用户可见三级或四级标题。",
            "4. 用户可见一级、二级标题不能直接作为生成单元，若当前层级过浅，必须继续拆成合适的三级标题。",
            "5. 目录层级优先使用一级、二级、三级；只有三级仍然过宽时，才允许四级。",
            "6. title 只保留语义名称，不要带编号、章次、条款号。",
            "7. 只输出修正后的 JSON，不要输出解释。",
            "",
            "项目名称：",
            requirement.project.name or "未提取",
            "",
            "范围概述：",
            requirement.scope.overview or "未提取",
            "",
            "已提取招标要求摘要：",
            *(bidding_requirement_lines[:160] or ["- 无"]),
            "",
            "用户上传目录树参考：",
            *(outline_lines or ["- 无"]),
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

        if depth < 5:
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
            if depth in {2, 3} and not node.children:
                raise ValueError("TOC leaves must be visible level 3 or level 4.")
            if depth >= 5 and node.children:
                raise ValueError("TOC cannot contain visible children below level 4.")
            if not node.children:
                if depth < 4:
                    raise ValueError("TOC leaves must be visible level 3 or level 4.")
                generation_unit_count += 1
            for child in node.children:
                walk(child, depth + 1)

        walk(root, 1)
        if generation_unit_count == 0:
            raise ValueError("TOC generation model did not return any visible level 3 or level 4 generation units.")

    def _materialize_tree(self, *, draft_root: _DraftNode, requirement: RequirementDocument) -> TOCNode:
        root_refs = self._match_source_refs(requirement, [draft_root.title], limit=10)
        root = TOCNode(
            node_uid="uid_root_001",
            node_id="",
            level=0,
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
                node_id=str(index) if not parent.node_id else f"{parent.node_id}.{index}",
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

    def _bidding_requirement_lines(self, requirement: RequirementDocument) -> list[str]:
        return [
            f"- {item.source_ref or 'unknown'} [{item.type}] {item.value}"
            for item in requirement.bidding_requirements
            if item.value.strip()
        ]

    def _outline_guidance_lines(self, outline_guidance: TOCDocument | None) -> list[str]:
        if outline_guidance is None:
            return []

        lines: list[str] = []

        def walk(node: TOCNode) -> None:
            if node.level > 0:
                prefix = node.node_id or f"L{node.level}"
                lines.append(f"- {prefix} {node.title}")
            for child in node.children:
                walk(child)

        for root in outline_guidance.tree:
            walk(root)
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
            "min_words": 1,
            "recommended_words": [],
            "images": [2, 3],
        }
