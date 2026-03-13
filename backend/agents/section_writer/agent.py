"""LLM-driven Section Writer for V1."""

from __future__ import annotations

import json
import re
from typing import Any, Iterable
from urllib import error as urlerror
from urllib import request as urlrequest

from backend.models.enums import ManualActionStatus, NodeStatus
from backend.models.schemas import (
    FactCheck,
    HighlightParagraph,
    NodeState,
    NodeText,
    RequirementDocument,
    TOCDocument,
    TOCNode,
    TextParagraph,
    TextSection,
)


class SectionWriterAgent:
    """Generate node text by reading the full parsed requirement with the text model."""

    _MINIMAX_TEXT_ENDPOINT = "https://api.minimaxi.com/v1/text/chatcompletion_v2"
    _WHATAI_TEXT_ENDPOINT = "https://api.whatai.cc/v1/chat/completions"
    _JSON_BLOCK_PATTERN = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", flags=re.S)
    _LINE_NO_PATTERN = re.compile(r"#L(\d+)$")

    def generate(
        self,
        *,
        node: NodeState,
        requirement: RequirementDocument,
        toc_document: TOCDocument | None = None,
        target_words: int | None = None,
        generation_config: dict[str, Any] | None = None,
    ) -> NodeText:
        provider, model_name, api_key = self._resolve_model_config(generation_config)
        desired_words = max(200, int(target_words or 2000))
        prompt = self._build_generation_prompt(
            node=node,
            requirement=requirement,
            toc_document=toc_document,
            target_words=desired_words,
        )
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
        return self._parse_or_repair(
            content=content,
            node=node,
            requirement=requirement,
            version=1,
            provider=provider,
            api_key=api_key,
            model_name=model_name,
            repair_prompt=self._build_repair_prompt(
                node=node,
                requirement=requirement,
                toc_document=toc_document,
                target_words=desired_words,
                invalid_output=content,
                validation_error="初次模型输出无法解析为合法 NodeText JSON。",
            ),
        )

    def revise_text(
        self,
        *,
        node_text: NodeText,
        fact_check: FactCheck,
        requirement: RequirementDocument,
        toc_document: TOCDocument | None = None,
        generation_config: dict[str, Any] | None = None,
    ) -> NodeText:
        provider, model_name, api_key = self._resolve_model_config(generation_config)
        prompt = self._build_revision_prompt(
            node_text=node_text,
            fact_check=fact_check,
            requirement=requirement,
            toc_document=toc_document,
        )
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
        node = NodeState(
            node_state_id=f"state_{node_text.node_uid}",
            task_id="task_revise",
            node_uid=node_text.node_uid,
            node_id=node_text.node_id,
            title=node_text.title,
            level=3,
            status=NodeStatus.PENDING,
            manual_action_status=ManualActionStatus.NONE,
        )
        revised = self._parse_or_repair(
            content=content,
            node=node,
            requirement=requirement,
            version=node_text.version + 1,
            provider=provider,
            api_key=api_key,
            model_name=model_name,
            repair_prompt=self._build_revision_repair_prompt(
                node_text=node_text,
                fact_check=fact_check,
                requirement=requirement,
                toc_document=toc_document,
                invalid_output=content,
                validation_error="修订后的模型输出无法解析为合法 NodeText JSON。",
            ),
        )
        return revised

    def revise_for_length(
        self,
        *,
        node_text: NodeText,
        requirement: RequirementDocument,
        toc_document: TOCDocument | None = None,
        min_words: int,
        max_words: int,
        generation_config: dict[str, Any] | None = None,
    ) -> NodeText:
        provider, model_name, api_key = self._resolve_model_config(generation_config)
        prompt = self._build_length_revision_prompt(
            node_text=node_text,
            requirement=requirement,
            toc_document=toc_document,
            min_words=min_words,
            max_words=max_words,
        )
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
        node = NodeState(
            node_state_id=f"state_{node_text.node_uid}_length",
            task_id="task_length_revise",
            node_uid=node_text.node_uid,
            node_id=node_text.node_id,
            title=node_text.title,
            level=3,
            status=NodeStatus.PENDING,
            manual_action_status=ManualActionStatus.NONE,
        )
        revised = self._parse_or_repair(
            content=content,
            node=node,
            requirement=requirement,
            version=node_text.version + 1,
            provider=provider,
            api_key=api_key,
            model_name=model_name,
            repair_prompt=self._build_length_revision_repair_prompt(
                node_text=node_text,
                requirement=requirement,
                toc_document=toc_document,
                min_words=min_words,
                max_words=max_words,
                invalid_output=content,
                validation_error="长度修订后的模型输出无法解析为合法 NodeText JSON。",
            ),
        )
        return revised

    def _resolve_model_config(self, generation_config: dict[str, Any] | None) -> tuple[str, str, str]:
        config = generation_config or {}
        provider = str(config.get("text_provider") or "").strip().lower()
        model_name = str(config.get("text_model_name") or "MiniMax-M2.5").strip() or "MiniMax-M2.5"
        api_key = str(config.get("text_api_key") or "").strip()
        if provider not in {"minimax", "whatai", "google"}:
            raise ValueError(
                "Section writing requires a supported text model provider. "
                f"Current provider: {provider or 'unset'}."
            )
        if not api_key:
            raise ValueError("Section writing requires `text_api_key`. Please configure the text model first.")
        return provider, model_name, api_key

    def _build_generation_prompt(
        self,
        *,
        node: NodeState,
        requirement: RequirementDocument,
        toc_document: TOCDocument | None,
        target_words: int,
    ) -> str:
        source_lines = self._source_lines(requirement)
        bidding_requirement_lines = self._bidding_requirement_lines(requirement)
        toc_context_lines = self._toc_context_lines(toc_document=toc_document, node_uid=node.node_uid)
        standard_lines = [f"- {item}" for item in requirement.constraints.standards if str(item).strip()]
        acceptance_lines = [f"- {item}" for item in requirement.constraints.acceptance if str(item).strip()]
        return "\n".join(
            [
                "任务：你要为标书正文的一个最小生成单元编写工程实施内容。",
                "必须先通读下方全文解析内容，提炼其中与当前节点直接相关的招标要求、实施范围、技术标准、接口约束、验收条件、交付要求和售后要求，再组织正文。",
                "禁止使用固定模板段落、通用套话章节或与全文无关的经验性扩写。",
                "正文要求：",
                "1. 只输出 JSON，不要输出 Markdown、解释、前言或代码块。",
                "2. 小节标题必须根据当前节点内容动态拟定，不能机械复用固定标题。",
                "3. 正文必须体现招标要求的可执行性、可验收性、留痕要求和实施约束。",
                "4. 不得编造设备型号、数量、标准号、阈值、工期、接口关系或验收结论。",
                "5. 每个段落尽量给出 1-3 个 source_refs，并且 source_refs 只能从下方全文解析内容提供的引用键中选择。",
                "6. 如果全文解析内容没有明确依据，就不要写入正文；禁止使用一般工程知识、行业常识或经验性措施补全内容。",
                "7. 正文中的所有事实、措施、流程、验收要求和服务承诺都必须能够从下方全文解析内容中提炼出来。",
                "8. 必须同时结合全文 requirement 和确认目录树上下文写作，只展开当前节点范围，不得把其他兄弟节点或其他一级章节的内容混入当前正文。",
                "9. 当前节点是确认目录树中的最小生成单元，正文必须与当前节点的祖先链和所属一级章节保持一致，不能写成整章总述。",
                f"10. 目标字数约 {target_words} 字，允许上下浮动 50 字。",
                "",
                "输出 JSON 格式：",
                "{",
                '  "summary": "当前节点摘要",',
                '  "sections": [',
                "    {",
                '      "title": "动态小节标题",',
                '      "paragraphs": [',
                '        {"text": "正文段落", "source_refs": ["p1#L10", "p1#L11"]}',
                "      ]",
                "    }",
                "  ],",
                '  "highlight_paragraphs": ["关键红字提示"]',
                "}",
                "",
                f"项目名称：{requirement.project.name or '未提取'}",
                f"范围概述：{requirement.scope.overview or '未提取'}",
                f"当前节点编号：{node.node_id}",
                f"当前节点标题：{node.title}",
                "",
                "确认目录树上下文（必须与全文 requirement 一起使用）：",
                *toc_context_lines,
                "",
                "已提取招标要求（必须优先作为正文依据，来源于全文分段解析）：",
                *(bidding_requirement_lines or ["- 无明确提取项，需从全文解析内容自行核对。"]),
                "",
                "已识别标准：",
                *(standard_lines or ["- 无"]),
                "",
                "已识别验收要求：",
                *(acceptance_lines or ["- 无"]),
                "",
                "全文解析内容（必须完整阅读）：",
                *source_lines,
            ]
        )

    def _build_revision_prompt(
        self,
        *,
        node_text: NodeText,
        fact_check: FactCheck,
        requirement: RequirementDocument,
        toc_document: TOCDocument | None,
    ) -> str:
        source_lines = self._source_lines(requirement)
        bidding_requirement_lines = self._bidding_requirement_lines(requirement)
        toc_context_lines = self._toc_context_lines(toc_document=toc_document, node_uid=node_text.node_uid)
        current_text = json.dumps(node_text.model_dump(mode="json"), ensure_ascii=False, indent=2)
        unsupported_lines = [f"- {item}" for item in fact_check.unsupported_claims]
        weak_lines = [f"- {item}" for item in fact_check.weak_claims]
        return "\n".join(
            [
                "任务：根据全文 requirement 修订当前节点正文。",
                "必须重新通读全文解析内容，删除或改写缺乏来源支撑的表述，只保留可以从全文提炼出的招标要求和原文可支撑的内容。",
                "只输出 JSON，不要解释。",
                "输出 JSON 结构与原正文相同：summary / sections / highlight_paragraphs。",
                "要求：",
                "1. 必须修正 unsupported claims。",
                "2. 不得保留 general engineering knowledge、行业常识补写或任何未在全文解析内容中出现的要求。",
                "3. 必须同时遵守确认目录树上下文，只围绕当前节点及其祖先链修订，不得引入其他兄弟节点内容。",
                "4. 小节标题仍需与当前节点主题匹配，不能混入其他节点标题。",
                "5. 每个段落尽量附带 source_refs。",
                "",
                "当前正文 JSON：",
                current_text,
                "",
                "确认目录树上下文（修订时也必须遵守）：",
                *toc_context_lines,
                "",
                "已提取招标要求（修订时必须优先对齐）：",
                *(bidding_requirement_lines or ["- 无"]),
                "",
                "需重点修正的 unsupported claims：",
                *(unsupported_lines or ["- 无"]),
                "",
                "需尽量增强支撑的 weak claims：",
                *(weak_lines or ["- 无"]),
                "",
                "全文解析内容（必须完整阅读）：",
                *source_lines,
            ]
        )

    def _build_length_revision_prompt(
        self,
        *,
        node_text: NodeText,
        requirement: RequirementDocument,
        toc_document: TOCDocument | None,
        min_words: int,
        max_words: int,
    ) -> str:
        source_lines = self._source_lines(requirement)
        bidding_requirement_lines = self._bidding_requirement_lines(requirement)
        toc_context_lines = self._toc_context_lines(toc_document=toc_document, node_uid=node_text.node_uid)
        current_text = json.dumps(node_text.model_dump(mode="json"), ensure_ascii=False, indent=2)
        target_words = (min_words + max_words) // 2
        direction = "补充展开" if node_text.word_count < min_words else "压缩精简"
        return "\n".join(
            [
                "任务：根据全文 requirement 和确认目录树上下文，对当前节点正文做长度修订。",
                "你必须重新通读全文解析内容，提炼与当前节点相关的招标要求，仅在这些原文依据范围内改写正文。",
                f"当前正文长度约 {node_text.word_count} 字，目标区间 {min_words}-{max_words} 字，本次应执行：{direction}。",
                "要求：",
                "1. 只输出 JSON，不要输出 Markdown、解释或代码块。",
                "2. 输出结构必须保持为 summary / sections / highlight_paragraphs。",
                "3. 如果需要补长，只能补充全文 requirement 中已经存在、且与当前节点目录路径直接相关的招标要求、实施要求、接口约束、验收条件和交付要求。",
                "4. 如果需要压缩，只能删减重复、空泛或边界外内容，不能删除全文 requirement 中明确出现的关键事实和关键要求。",
                "5. 严禁补入一般工程常识、经验性措施、模板套话或任何全文中没有的内容。",
                "6. 必须同时遵守确认目录树上下文，只围绕当前节点及其祖先链修订，不得混入其他兄弟节点或其他一级章节内容。",
                "7. 每个段落尽量保留或补齐 1-3 个 source_refs，且只能使用全文解析内容中的引用键。",
                f"8. 修订后的正文目标字数约 {target_words} 字，并最终落在 {min_words}-{max_words} 字之间。",
                "",
                "当前正文 JSON：",
                current_text,
                "",
                "确认目录树上下文（长度修订时也必须遵守）：",
                *toc_context_lines,
                "",
                "已提取招标要求（长度修订时必须优先对齐）：",
                *(bidding_requirement_lines or ["- 无"]),
                "",
                "全文解析内容（必须完整阅读）：",
                *source_lines,
            ]
        )

    def _build_repair_prompt(
        self,
        *,
        node: NodeState,
        requirement: RequirementDocument,
        toc_document: TOCDocument | None,
        target_words: int,
        invalid_output: str,
        validation_error: str,
    ) -> str:
        return "\n".join(
            [
                self._build_generation_prompt(
                    node=node,
                    requirement=requirement,
                    toc_document=toc_document,
                    target_words=target_words,
                ),
                "",
                "上一次输出存在问题：",
                validation_error,
                "",
                "请修正并只输出合法 JSON。上一次无效输出如下：",
                invalid_output,
            ]
        )

    def _build_revision_repair_prompt(
        self,
        *,
        node_text: NodeText,
        fact_check: FactCheck,
        requirement: RequirementDocument,
        toc_document: TOCDocument | None,
        invalid_output: str,
        validation_error: str,
    ) -> str:
        return "\n".join(
            [
                self._build_revision_prompt(
                    node_text=node_text,
                    fact_check=fact_check,
                    requirement=requirement,
                    toc_document=toc_document,
                ),
                "",
                "上一次输出存在问题：",
                validation_error,
                "",
                "请修正并只输出合法 JSON。上一次无效输出如下：",
                invalid_output,
            ]
        )

    def _build_length_revision_repair_prompt(
        self,
        *,
        node_text: NodeText,
        requirement: RequirementDocument,
        toc_document: TOCDocument | None,
        min_words: int,
        max_words: int,
        invalid_output: str,
        validation_error: str,
    ) -> str:
        return "\n".join(
            [
                self._build_length_revision_prompt(
                    node_text=node_text,
                    requirement=requirement,
                    toc_document=toc_document,
                    min_words=min_words,
                    max_words=max_words,
                ),
                "",
                "上一次输出存在问题：",
                validation_error,
                "",
                "请修正并只输出合法 JSON。上一次无效输出如下：",
                invalid_output,
            ]
        )

    def _request_minimax_completion(self, *, api_key: str, model_name: str, prompt: str) -> str:
        payload = {
            "model": model_name,
            "messages": [
                {
                    "role": "system",
                    "name": "Section Writer",
                    "content": (
                        "你是工程标书正文编写专家。"
                        "必须基于用户上传文档的全文解析结果，提炼招标要求并生成结构化正文 JSON。"
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
            raise ValueError(f"Section writing model request failed: HTTP {exc.code} {detail}") from exc
        except (urlerror.URLError, TimeoutError) as exc:
            raise ValueError(f"Section writing model request failed: {exc}") from exc

        try:
            data = json.loads(body)
        except json.JSONDecodeError as exc:
            raise ValueError("Section writing model returned invalid JSON payload.") from exc

        base_resp = data.get("base_resp") or {}
        if base_resp.get("status_code") not in (None, 0):
            raise ValueError(
                f"Section writing model returned error: {base_resp.get('status_msg') or base_resp.get('status_code')}"
            )

        content = (
            ((data.get("choices") or [{}])[0].get("message") or {}).get("content")
            if isinstance(data.get("choices"), list)
            else None
        )
        if not isinstance(content, str) or not content.strip():
            raise ValueError("Section writing model returned empty content.")
        return content

    def _request_whatai_completion(self, *, api_key: str, model_name: str, prompt: str) -> str:
        payload = {
            "model": model_name,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "你是工程标书正文编写专家。"
                        "必须基于用户上传文档的全文解析结果，提炼招标要求并生成结构化正文 JSON。"
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
            raise ValueError(f"Section writing model request failed: HTTP {exc.code} {detail}") from exc
        except (urlerror.URLError, TimeoutError) as exc:
            raise ValueError(f"Section writing model request failed: {exc}") from exc

        try:
            data = json.loads(body)
        except json.JSONDecodeError as exc:
            raise ValueError("Section writing model returned invalid JSON payload.") from exc

        if data.get("error"):
            raise ValueError(f"Section writing model returned error: {data['error']}")

        content = (
            ((data.get("choices") or [{}])[0].get("message") or {}).get("content")
            if isinstance(data.get("choices"), list)
            else None
        )
        if not isinstance(content, str) or not content.strip():
            raise ValueError("Section writing model returned empty content.")
        return content

    def _parse_or_repair(
        self,
        *,
        content: str,
        node: NodeState,
        requirement: RequirementDocument,
        version: int,
        provider: str,
        api_key: str,
        model_name: str,
        repair_prompt: str,
    ) -> NodeText:
        last_error: ValueError | None = None
        current = content
        for attempt in range(2):
            try:
                return self._parse_model_output(
                    content=current,
                    node=node,
                    requirement=requirement,
                    version=version,
                )
            except ValueError as exc:
                last_error = exc
                if attempt >= 1:
                    break
                request_fn = (
                    self._request_minimax_completion
                    if provider == "minimax"
                    else self._request_whatai_completion
                )
                current = request_fn(
                    api_key=api_key,
                    model_name=model_name,
                    prompt=repair_prompt.replace(
                        "初次模型输出无法解析为合法 NodeText JSON。",
                        str(exc),
                    ).replace(
                        "修订后的模型输出无法解析为合法 NodeText JSON。",
                        str(exc),
                    ),
                )
        assert last_error is not None
        raise last_error

    def _parse_model_output(
        self,
        *,
        content: str,
        node: NodeState,
        requirement: RequirementDocument,
        version: int,
    ) -> NodeText:
        payload = self._extract_json_payload(content)
        raw_sections = payload.get("sections")
        if not isinstance(raw_sections, list) or not raw_sections:
            raise ValueError("Section writing model did not return any sections.")
        raw_summary = self._normalize_text(
            str(payload.get("summary") or ""),
            add_terminal_punctuation=False,
        )
        if not raw_summary:
            raise ValueError("Section writing model did not return a valid summary.")

        sections: list[TextSection] = []
        claim_seq = 1
        for section_index, raw_section in enumerate(raw_sections, start=1):
            if not isinstance(raw_section, dict):
                continue
            title = self._clean_heading(str(raw_section.get("title") or ""))
            raw_paragraphs = raw_section.get("paragraphs")
            if not title or not isinstance(raw_paragraphs, list) or not raw_paragraphs:
                continue

            paragraphs: list[TextParagraph] = []
            for paragraph_index, raw_paragraph in enumerate(raw_paragraphs, start=1):
                text, source_refs = self._parse_paragraph_payload(
                    raw_paragraph=raw_paragraph,
                    requirement=requirement,
                )
                if not text:
                    continue
                paragraph_id = f"s{section_index:02d}_p{paragraph_index:02d}"
                paragraphs.append(
                    TextParagraph(
                        paragraph_id=paragraph_id,
                        text=text,
                        source_refs=source_refs,
                        claim_ids=[f"claim_{claim_seq:03d}"],
                        anchors=[f"anchor_{node.node_uid}_{paragraph_id}"],
                    )
                )
                claim_seq += 1

            if paragraphs:
                sections.append(
                    TextSection(
                        section_id=f"sec_{section_index:02d}",
                        title=title,
                        paragraphs=paragraphs,
                    )
                )

        if not sections:
            raise ValueError("Section writing model returned no valid text paragraphs.")

        highlight_paragraphs = self._parse_highlights(
            payload.get("highlight_paragraphs"),
            node_title=node.title,
        )
        node_text = NodeText(
            node_uid=node.node_uid,
            node_id=node.node_id,
            title=node.title,
            summary=raw_summary,
            sections=sections,
            highlight_paragraphs=highlight_paragraphs,
            word_count=self.count_text_units(
                paragraph.text
                for section in sections
                for paragraph in section.paragraphs
            ),
            version=version,
        )
        return self._normalize_node_text(node_text)

    def _parse_highlights(self, raw_value: Any, *, node_title: str) -> list[HighlightParagraph]:
        highlights: list[HighlightParagraph] = []
        raw_items = raw_value if isinstance(raw_value, list) else []
        for index, raw_item in enumerate(raw_items[:2], start=1):
            if isinstance(raw_item, str):
                text = self._normalize_text(raw_item, add_terminal_punctuation=True)
                style_hint = "red_bold"
            elif isinstance(raw_item, dict):
                text = self._normalize_text(
                    str(raw_item.get("text") or ""),
                    add_terminal_punctuation=True,
                )
                style_hint = str(raw_item.get("style_hint") or "red_bold").strip() or "red_bold"
            else:
                continue
            if not text:
                continue
            highlights.append(
                HighlightParagraph(
                    paragraph_id=f"key_{index:02d}",
                    text=text,
                    style_hint=style_hint,
                )
            )
        if highlights:
            return highlights
        return [
            HighlightParagraph(
                paragraph_id="key_01",
                text=self._normalize_text(
                    f"{node_title}实施内容必须以招标文件全文提炼出的要求为准，确保过程可执行、结果可验收、资料可追溯。",
                    add_terminal_punctuation=True,
                ),
                style_hint="red_bold",
            )
        ]

    def _parse_paragraph_payload(
        self,
        *,
        raw_paragraph: Any,
        requirement: RequirementDocument,
    ) -> tuple[str, list[str]]:
        if isinstance(raw_paragraph, str):
            text = self._normalize_text(raw_paragraph, add_terminal_punctuation=True)
            return text, self._default_source_refs(requirement)
        if not isinstance(raw_paragraph, dict):
            return "", []
        text = self._normalize_text(
            str(raw_paragraph.get("text") or ""),
            add_terminal_punctuation=True,
        )
        if not text:
            return "", []
        source_refs = self._normalize_source_refs(raw_paragraph.get("source_refs"), requirement)
        if not source_refs:
            source_refs = self._default_source_refs(requirement)
        return text, source_refs

    def _normalize_source_refs(
        self,
        raw_value: Any,
        requirement: RequirementDocument,
    ) -> list[str]:
        if isinstance(raw_value, str):
            raw_items = [raw_value]
        elif isinstance(raw_value, list):
            raw_items = [str(item) for item in raw_value]
        else:
            raw_items = []
        normalized: list[str] = []
        for item in raw_items:
            cleaned = item.strip()
            if cleaned in requirement.source_index and cleaned not in normalized:
                normalized.append(cleaned)
        return normalized[:3]

    def _default_source_refs(self, requirement: RequirementDocument) -> list[str]:
        refs = [
            source_ref
            for source_ref, _item in sorted(
                requirement.source_index.items(),
                key=lambda pair: self._line_no_from_source_ref(pair[0]),
            )
        ]
        return refs[:3]

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
        raise ValueError("Section writing model did not return parsable JSON.")

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

    def _line_no_from_source_ref(self, source_ref: str) -> int:
        match = self._LINE_NO_PATTERN.search(source_ref)
        if match is None:
            return 0
        return int(match.group(1))

    def _clean_heading(self, text: str) -> str:
        cleaned = self._normalize_text(text, add_terminal_punctuation=False)
        original = cleaned
        previous = None
        while cleaned and cleaned != previous:
            previous = cleaned
            cleaned = re.sub(r"^[0-9]+(?:[.．][0-9]+)*(?:[.．、\-])?", "", cleaned)
            cleaned = re.sub(r"^[（(]?[一二三四五六七八九十百千万0-9]+[)）.、]+", "", cleaned)
            cleaned = re.sub(r"^第[一二三四五六七八九十百千万0-9]+[章节篇部分卷编回节]\s*", "", cleaned)
            cleaned = cleaned.strip("，。；：、- ")
        return cleaned or original

    def _normalize_node_text(self, node_text: NodeText) -> NodeText:
        for section in node_text.sections:
            section.title = self._clean_heading(section.title)
            for paragraph in section.paragraphs:
                paragraph.text = self._normalize_text(paragraph.text, add_terminal_punctuation=True)
                paragraph.source_refs = list(dict.fromkeys(paragraph.source_refs))[:3]
        for item in node_text.highlight_paragraphs:
            item.text = self._normalize_text(item.text, add_terminal_punctuation=True)
        node_text.word_count = self.count_text_units(
            paragraph.text
            for section in node_text.sections
            for paragraph in section.paragraphs
        )
        return node_text

    def _toc_context_lines(self, *, toc_document: TOCDocument | None, node_uid: str) -> list[str]:
        if toc_document is None:
            return ["- 未提供确认目录树上下文。"]

        outline_lines = self._toc_outline_lines(toc_document.tree)
        path = self._find_toc_path(toc_document.tree, node_uid)
        lines: list[str] = [
            f"- 确认目录树总标题：{toc_document.tree[0].title if toc_document.tree else '未提供'}",
        ]
        if path:
            visible_path = [item for item in path if item.level > 0]
            if visible_path:
                lines.append(
                    "- 当前节点目录路径：" + " > ".join(f"{item.node_id} {item.title}" for item in visible_path)
                )
                top_chapter = visible_path[0]
                lines.append(f"- 所属一级章节：{top_chapter.node_id} {top_chapter.title}")
                if len(visible_path) >= 2:
                    parent = visible_path[-2]
                    lines.append(f"- 当前节点父级章节：{parent.node_id} {parent.title}")
                    sibling_lines = [
                        f"{item.node_id} {item.title}"
                        for item in parent.children
                        if item.node_uid != node_uid
                    ]
                    lines.append(
                        "- 当前节点同级章节："
                        + ("；".join(sibling_lines) if sibling_lines else "无")
                    )
                lines.append("- 所属一级章节完整目录：")
                lines.extend(self._toc_outline_lines([top_chapter]))
        else:
            lines.append("- 当前节点未在确认目录树中定位到路径，仍需参考完整目录树总览控制边界。")

        lines.append("- 确认目录树总览：")
        lines.extend(outline_lines or ["- 目录树为空"])
        return lines

    def _find_toc_path(self, nodes: list[TOCNode], node_uid: str, path: list[TOCNode] | None = None) -> list[TOCNode] | None:
        current_path = path or []
        for node in nodes:
            next_path = [*current_path, node]
            if node.node_uid == node_uid:
                return next_path
            found = self._find_toc_path(node.children, node_uid, next_path)
            if found is not None:
                return found
        return None

    def _toc_outline_lines(self, nodes: list[TOCNode]) -> list[str]:
        lines: list[str] = []

        def walk(node: TOCNode) -> None:
            if node.level > 0:
                lines.append(f"- {node.node_id} {node.title}")
            for child in node.children:
                walk(child)

        for node in nodes:
            walk(node)
        return lines

    def _normalize_text(self, text: str, *, add_terminal_punctuation: bool = False) -> str:
        cleaned = str(text or "")
        cleaned = cleaned.replace("\n", "").replace("\r", "")
        cleaned = cleaned.replace("**", "").replace("__", "")
        cleaned = re.sub(r"[#>*`]", "", cleaned)
        cleaned = re.sub(r"\s+", "", cleaned)
        cleaned = re.sub(r"(版权属于[^，。；：]*)([，。；：]|$)", "", cleaned)
        cleaned = re.sub(r"(未经[^，。；：]*)([，。；：]|$)", "", cleaned)
        replacements = (
            ("。，", "。"),
            ("，。", "。"),
            ("；。", "。"),
            ("：。", "。"),
            ("。。", "。"),
            ("，，", "，"),
            ("；；", "；"),
            ("::", "："),
        )
        for source, target in replacements:
            while source in cleaned:
                cleaned = cleaned.replace(source, target)
        cleaned = re.sub(r"([，、])([。！？；：])", r"\2", cleaned)
        cleaned = re.sub(r"([。！？；：])([，、])", r"\1", cleaned)
        cleaned = re.sub(r"([。！？；：])\1+", r"\1", cleaned)
        cleaned = re.sub(r"([，、])\1+", r"\1", cleaned)
        cleaned = cleaned.strip("，。；：、 ")
        if add_terminal_punctuation and cleaned and cleaned[-1] not in "。！？":
            cleaned = f"{cleaned}。"
        return cleaned

    @staticmethod
    def count_text_units(paragraphs: Iterable[str]) -> int:
        merged = "".join(part.strip() for part in paragraphs)
        return len(merged)
