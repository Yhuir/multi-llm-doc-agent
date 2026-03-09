"""Rule-based requirement parser agent for V1 skeleton."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from docx import Document

from backend.models.enums import AgentResult
from backend.models.schemas import (
    RequirementConstraints,
    RequirementDocument,
    RequirementItem,
    RequirementProject,
    RequirementScope,
    RequirementSubsystem,
    SourceIndexItem,
    utc_now_iso,
)


@dataclass
class _ClauseCandidate:
    source_ref: str
    line_no: int
    raw_text: str
    clause_code: str
    title: str
    normalized_key: str


@dataclass
class _SubsystemBucket:
    name: str
    description_lines: list[str] = field(default_factory=list)
    requirements: list[RequirementItem] = field(default_factory=list)
    interfaces: list[str] = field(default_factory=list)


@dataclass
class _ParagraphEntry:
    line_no: int
    text: str
    paragraph_id: str
    heading_level: int | None = None


class RequirementParserAgent:
    """Parse docx into requirement.json with clause/heading awareness."""

    _CLAUSE_PATTERN = re.compile(r"^(?P<code>\d+(?:\.\d+){1,5})[\s.、-]*(?P<body>.+)$")
    _NUMBERED_HEADING_PATTERN = re.compile(r"^(?P<code>\d+(?:\.\d+){0,3})[\s、.．]+(?P<body>.+)$")
    _CHAPTER_PATTERN = re.compile(r"^第[一二三四五六七八九十百千0-9]+[章节篇部分]\s*(?P<title>.*)$")
    _LIST_PATTERN = re.compile(r"^[（(]?[一二三四五六七八九十0-9]+[)）.、]\s*(?P<body>.+)$")
    _SUBSYSTEM_PATTERN = re.compile(
        r"([A-Za-z0-9\u4e00-\u9fff（）()\-]{2,32}?"
        r"(?:控制系统|回收系统|管理系统|供热系统|热泵系统|子系统|平台|模块|装置|系统))"
    )
    _SYSTEM_KEYWORDS = ("系统", "平台", "子系统", "模块", "控制", "装置", "网络", "中心")
    _GENERIC_HEADINGS = (
        "服务要求",
        "技术要求",
        "技术规范",
        "技术方案",
        "建设内容",
        "功能要求",
        "项目概述",
        "总体要求",
    )
    _NOISE_PREFIXES = (
        "根据生产管理的要求，",
        "根据要求，",
        "根据生产管理要求，",
        "针对",
        "要求对",
        "对",
    )
    _ACTION_PREFIXES = (
        "优化和完善",
        "优化完善",
        "优化升级",
        "升级改造",
        "优化",
        "完善",
        "改造",
        "升级",
        "开发",
        "建设",
        "实施",
        "新建",
        "扩建",
        "调整",
        "提升",
    )
    _CONTEXT_PREFIXES = ("当前的", "当前", "现有的", "现有", "原有的", "原有", "本次", "针对")

    def parse(
        self,
        *,
        task_id: str,
        upload_file_path: Path,
        fallback_title: str,
    ) -> tuple[RequirementDocument, dict]:
        if upload_file_path.suffix.lower() != ".docx":
            raise ValueError("Only .docx is supported.")

        paragraphs = self._extract_docx_paragraphs(upload_file_path)
        lines = [paragraph.text for paragraph in paragraphs]
        has_original_content = bool(lines)
        if not lines:
            lines = [fallback_title.strip() or "项目需求说明"]
            paragraphs = [
                _ParagraphEntry(
                    line_no=1,
                    text=lines[0],
                    paragraph_id="para_1",
                    heading_level=None,
                )
            ]

        source_index = self._build_source_index(paragraphs)
        subsystems = self._extract_subsystems(paragraphs)
        standards = self._extract_standards(lines)
        acceptance = self._extract_acceptance(lines)
        project_name = self._extract_project_name(paragraphs, subsystems, fallback_title)
        overview = self._extract_overview(paragraphs)

        requirement = RequirementDocument(
            project=RequirementProject(
                name=project_name,
                customer="",
                location="",
                duration_days=None,
                milestones=[],
            ),
            scope=RequirementScope(
                overview=overview,
                subsystems=subsystems,
            ),
            constraints=RequirementConstraints(
                standards=standards,
                acceptance=acceptance,
            ),
            source_index=source_index,
        )

        missing_fields: list[str] = []
        warnings: list[str] = []
        if not has_original_content:
            missing_fields.extend(["project.name", "scope.overview", "scope.subsystems"])
        if not standards:
            missing_fields.append("constraints.standards")
        if not acceptance:
            missing_fields.append("constraints.acceptance")
        if not subsystems:
            warnings.append("No clause-like subsystem detected; fallback headings used.")
        warnings.append("TODO: replace rule-based parser with richer extraction in later rounds")

        parse_report = {
            "task_id": task_id,
            "source_file": str(upload_file_path),
            "result": AgentResult.PASS.value,
            "paragraph_count": len(lines),
            "subsystem_count": len(subsystems),
            "missing_fields": missing_fields,
            "warnings": warnings,
            "generated_at": utc_now_iso(),
        }
        return requirement, parse_report

    def _extract_docx_paragraphs(self, file_path: Path) -> list[_ParagraphEntry]:
        try:
            document = Document(file_path)
        except Exception as exc:
            raise ValueError(f"Cannot parse docx file: {file_path}") from exc

        entries: list[_ParagraphEntry] = []
        for paragraph in document.paragraphs:
            text = self._normalize_text(paragraph.text)
            if not text:
                continue
            style_name = self._normalize_text(getattr(getattr(paragraph, "style", None), "name", ""))
            heading_level = self._detect_heading_level(text=text, style_name=style_name)
            line_no = len(entries) + 1
            paragraph_id = (
                f"heading_l{heading_level}_{line_no}"
                if heading_level is not None
                else f"para_{line_no}"
            )
            entries.append(
                _ParagraphEntry(
                    line_no=line_no,
                    text=text,
                    paragraph_id=paragraph_id,
                    heading_level=heading_level,
                )
            )
        return entries

    def _build_source_index(self, paragraphs: list[_ParagraphEntry]) -> dict[str, SourceIndexItem]:
        source_index: dict[str, SourceIndexItem] = {}
        for paragraph in paragraphs[:300]:
            ref = f"p1#L{paragraph.line_no}"
            source_index[ref] = SourceIndexItem(
                page=1,
                paragraph_id=paragraph.paragraph_id,
                text=paragraph.text,
            )
        return source_index

    def _extract_subsystems(self, paragraphs: list[_ParagraphEntry]) -> list[RequirementSubsystem]:
        outline_subsystems = self._extract_outline_subsystems(paragraphs)
        if outline_subsystems:
            return outline_subsystems

        buckets: dict[str, _SubsystemBucket] = {}

        for paragraph in paragraphs:
            line = paragraph.text
            if not line:
                continue
            if paragraph.heading_level is not None:
                continue
            if self._is_generic_heading(line):
                continue

            candidate = self._build_clause_candidate(line=line, line_no=paragraph.line_no)
            if candidate is None:
                continue

            for expanded_title in self._expand_candidate_titles(candidate.raw_text, candidate.title):
                normalized_key = self._normalize_topic_key(expanded_title)
                bucket = buckets.setdefault(
                    normalized_key,
                    _SubsystemBucket(name=expanded_title),
                )
                if candidate.raw_text not in bucket.description_lines:
                    bucket.description_lines.append(candidate.raw_text)
                bucket.requirements.append(
                    RequirementItem(
                        type="clause" if candidate.clause_code else "heading",
                        key=candidate.clause_code or f"line_{candidate.line_no}",
                        value=candidate.raw_text,
                        source_ref=candidate.source_ref,
                    )
                )
                if "接口" in candidate.raw_text and candidate.raw_text not in bucket.interfaces:
                    bucket.interfaces.append(candidate.raw_text)

        if not buckets:
            return self._fallback_subsystems([paragraph.text for paragraph in paragraphs])

        subsystems: list[RequirementSubsystem] = []
        for bucket in buckets.values():
            subsystems.append(
                RequirementSubsystem(
                    name=bucket.name,
                    description="；".join(bucket.description_lines[:3]),
                    requirements=bucket.requirements,
                    interfaces=bucket.interfaces,
                )
            )
        return subsystems

    def _build_clause_candidate(self, *, line: str, line_no: int) -> _ClauseCandidate | None:
        clause_code = ""
        body = line

        while True:
            matched_clause = self._CLAUSE_PATTERN.match(body)
            if matched_clause is None:
                break
            clause_code = matched_clause.group("code")
            body = self._normalize_text(matched_clause.group("body"))

        chapter_match = self._CHAPTER_PATTERN.match(body)
        if chapter_match is not None:
            chapter_title = self._normalize_text(chapter_match.group("title"))
            body = chapter_title or body

        list_match = self._LIST_PATTERN.match(body)
        if list_match is not None:
            body = self._normalize_text(list_match.group("body"))

        title = self._derive_topic_title(body)
        if not self._looks_like_requirement_topic(title, body, clause_code):
            return None

        source_ref = f"p1#L{line_no}"
        return _ClauseCandidate(
            source_ref=source_ref,
            line_no=line_no,
            raw_text=line,
            clause_code=clause_code,
            title=title,
            normalized_key=self._normalize_topic_key(title),
        )

    def _fallback_subsystems(self, lines: list[str]) -> list[RequirementSubsystem]:
        fallback_lines = [
            self._normalize_text(item)
            for item in lines[1:8]
            if self._normalize_text(item) and not self._is_generic_heading(item)
        ]
        if not fallback_lines:
            fallback_lines = ["基础实施范围"]

        subsystems: list[RequirementSubsystem] = []
        for idx, line in enumerate(fallback_lines[:4], start=1):
            ref = f"p1#L{min(idx + 1, max(len(lines), 1))}"
            title = self._derive_topic_title(line)
            subsystems.append(
                RequirementSubsystem(
                    name=title or f"实施专题{idx}",
                    description=line,
                    requirements=[
                        RequirementItem(
                            type="fallback",
                            key=f"fallback_{idx}",
                            value=line,
                            source_ref=ref,
                        )
                    ],
                    interfaces=[line] if "接口" in line else [],
                )
            )
        return subsystems

    def _extract_outline_subsystems(self, paragraphs: list[_ParagraphEntry]) -> list[RequirementSubsystem]:
        headings = [entry for entry in paragraphs if entry.heading_level is not None and entry.heading_level <= 4]
        if not headings:
            return []

        if any(entry.heading_level == 2 for entry in headings):
            primary_level = 2
        elif any(entry.heading_level == 1 for entry in headings):
            primary_level = 1
        else:
            primary_level = min(entry.heading_level for entry in headings)

        primary_headings = [entry for entry in headings if entry.heading_level == primary_level]
        if primary_level == 1 and len(primary_headings) == 1 and any(entry.heading_level > 1 for entry in headings):
            primary_level = 2
            primary_headings = [entry for entry in headings if entry.heading_level == 2]

        if not primary_headings:
            return []

        subsystems: list[RequirementSubsystem] = []
        for index, heading in enumerate(primary_headings):
            next_line_no = (
                primary_headings[index + 1].line_no
                if index + 1 < len(primary_headings)
                else paragraphs[-1].line_no + 1
            )
            segment = [
                entry
                for entry in paragraphs
                if heading.line_no <= entry.line_no < next_line_no
            ]
            title = self._clean_heading_title(heading.text)
            if not title or self._is_generic_heading(title):
                continue

            requirements: list[RequirementItem] = [
                RequirementItem(
                    type=f"heading_l{heading.heading_level}",
                    key=heading.paragraph_id,
                    value=heading.text,
                    source_ref=f"p1#L{heading.line_no}",
                )
            ]
            description_parts: list[str] = []
            interfaces: list[str] = []

            for entry in segment[1:]:
                source_ref = f"p1#L{entry.line_no}"
                if entry.heading_level is not None and entry.heading_level > heading.heading_level:
                    requirements.append(
                        RequirementItem(
                            type=f"heading_l{entry.heading_level}",
                            key=entry.paragraph_id,
                            value=entry.text,
                            source_ref=source_ref,
                        )
                    )
                    description_parts.append(self._clean_heading_title(entry.text))
                    continue

                if entry.heading_level is None and len(entry.text) <= 120:
                    requirements.append(
                        RequirementItem(
                            type="text",
                            key=f"para_{entry.line_no}",
                            value=entry.text,
                            source_ref=source_ref,
                        )
                    )
                    if len(description_parts) < 3:
                        description_parts.append(entry.text)
                    if "接口" in entry.text and entry.text not in interfaces:
                        interfaces.append(entry.text)

                if len(requirements) >= 8:
                    break

            subsystems.append(
                RequirementSubsystem(
                    name=title,
                    description="；".join(description_parts[:3]) or title,
                    requirements=requirements,
                    interfaces=interfaces,
                )
            )

        return subsystems

    def _extract_project_name(
        self,
        paragraphs: list[_ParagraphEntry],
        subsystems: list[RequirementSubsystem],
        fallback_title: str,
    ) -> str:
        heading_level1 = [entry for entry in paragraphs if entry.heading_level == 1]
        if len(heading_level1) == 1:
            title = self._clean_heading_title(heading_level1[0].text)
            if title and not self._is_generic_heading(title):
                return title

        for entry in paragraphs[:20]:
            cleaned = self._normalize_text(entry.text)
            if not cleaned or self._is_generic_heading(cleaned):
                continue
            body = self._strip_leading_codes(cleaned)
            title = self._derive_topic_title(body)
            if 6 <= len(title) <= 28 and self._contains_topic_keyword(title):
                return title

        if subsystems:
            return subsystems[0].name

        fallback = self._normalize_text(fallback_title)
        if fallback:
            return fallback
        return "工程实施项目"

    def _extract_overview(self, paragraphs: list[_ParagraphEntry]) -> str:
        fragments: list[str] = []
        for entry in paragraphs[:16]:
            if entry.heading_level is not None:
                continue
            cleaned = self._normalize_text(entry.text)
            if not cleaned or self._is_generic_heading(cleaned):
                continue
            body = self._strip_leading_codes(cleaned)
            fragments.append(body)
            if len("；".join(fragments)) >= 80:
                break
        if fragments:
            return "；".join(fragments[:3])
        return "基于需求文件提取实施范围、约束条件和关键建设内容。"

    def _derive_topic_title(self, text: str) -> str:
        body = self._prepare_topic_body(text)
        body = re.split(r"[，。；：]", body, maxsplit=1)[0].strip(" -、:：;；")
        if "包括" in body and len(body) > 22:
            body = body.split("包括", 1)[0].strip()
        if "要求" in body and len(body) > 18 and not body.endswith("要求"):
            body = body.split("要求", 1)[0].strip()

        match = self._SUBSYSTEM_PATTERN.search(body)
        if match is not None:
            body = self._normalize_subsystem_title(match.group(1))

        body = body.strip(" -、:：;；")
        if len(body) > 32:
            body = body[:32].rstrip(" -、")
        return body or "实施专题"

    def _detect_heading_level(self, *, text: str, style_name: str) -> int | None:
        level_from_style = self._detect_heading_level_from_style(style_name)
        if level_from_style is not None:
            return level_from_style

        if self._CHAPTER_PATTERN.match(text):
            return 1

        numbered_match = self._NUMBERED_HEADING_PATTERN.match(text)
        if numbered_match is not None:
            code = numbered_match.group("code")
            body = self._normalize_text(numbered_match.group("body"))
            if self._looks_like_numbered_heading_body(body):
                return min(code.count(".") + 1, 4)

        return None

    def _detect_heading_level_from_style(self, style_name: str) -> int | None:
        normalized = style_name.lower().replace(" ", "")
        match = re.search(r"heading([1-4])", normalized)
        if match is not None:
            return int(match.group(1))
        match = re.search(r"标题([1-4])", style_name)
        if match is not None:
            return int(match.group(1))
        return None

    def _looks_like_numbered_heading_body(self, body: str) -> bool:
        cleaned = self._clean_heading_title(body)
        if not cleaned or len(cleaned) > 38:
            return False
        if body.endswith(("。", "；", ";")):
            return False
        punctuation_count = sum(body.count(token) for token in ("，", "。", "；", "：", ":", ",", ";"))
        if punctuation_count > 1:
            return False
        return True

    def _clean_heading_title(self, text: str) -> str:
        cleaned = self._normalize_text(text)
        chapter_match = self._CHAPTER_PATTERN.match(cleaned)
        if chapter_match is not None:
            cleaned = self._normalize_text(chapter_match.group("title")) or cleaned
        numbered_match = self._NUMBERED_HEADING_PATTERN.match(cleaned)
        if numbered_match is not None:
            cleaned = self._normalize_text(numbered_match.group("body"))
        cleaned = re.sub(r"^[（(]?[一二三四五六七八九十0-9]+[)）.、]\s*", "", cleaned)
        cleaned = cleaned.strip(" -、:：;；，。")
        return cleaned

    def _looks_like_requirement_topic(self, title: str, body: str, clause_code: str) -> bool:
        if not title:
            return False
        if self._is_generic_heading(title):
            return False
        if clause_code:
            return True
        if len(title) <= 4:
            return False
        if self._contains_topic_keyword(title):
            return True
        return any(token in body for token in ("优化", "改造", "升级", "开发", "建设", "实施"))

    def _contains_topic_keyword(self, text: str) -> bool:
        return any(keyword in text for keyword in self._SYSTEM_KEYWORDS)

    def _normalize_topic_key(self, title: str) -> str:
        normalized = re.sub(r"[^0-9A-Za-z\u4e00-\u9fff]+", "", title)
        return normalized[:48] or "topic"

    def _expand_candidate_titles(self, raw_text: str, primary_title: str) -> list[str]:
        titles = [primary_title]
        for title in self._extract_mentioned_subsystems(raw_text):
            if self._normalize_topic_key(title) != self._normalize_topic_key(primary_title):
                titles.append(title)
        return titles[:6]

    def _extract_mentioned_subsystems(self, text: str) -> list[str]:
        body = self._prepare_topic_body(text)
        search_zone = body
        for marker in ("包括", "包含", "涵盖", "涉及", "由", "含"):
            if marker in search_zone:
                search_zone = search_zone.split(marker, 1)[1]
                break

        matches = self._SUBSYSTEM_PATTERN.findall(search_zone)
        results: list[str] = []
        for match in matches:
            title = self._normalize_subsystem_title(match)
            if not self._looks_like_subsystem_name(title):
                continue
            if title not in results:
                results.append(title)
        return results

    def _looks_like_subsystem_name(self, title: str) -> bool:
        if len(title) < 4:
            return False
        if title in {"系统", "控制系统", "子系统", "平台", "模块", "装置"}:
            return False
        return self._contains_topic_keyword(title)

    def _prepare_topic_body(self, text: str) -> str:
        body = self._strip_leading_codes(self._normalize_text(text))
        for prefix in self._NOISE_PREFIXES:
            if body.startswith(prefix):
                body = body[len(prefix) :]
                break
        body = self._normalize_subsystem_title(body)
        return body

    def _normalize_subsystem_title(self, text: str) -> str:
        body = self._strip_leading_codes(self._normalize_text(text))
        for prefix in self._CONTEXT_PREFIXES:
            if body.startswith(prefix):
                body = body[len(prefix) :]
                break
        trimmed = True
        while trimmed:
            trimmed = False
            for prefix in self._ACTION_PREFIXES:
                if body.startswith(prefix) and len(body) > len(prefix) + 3:
                    body = body[len(prefix) :].lstrip("的")
                    trimmed = True
                    break
        body = body.strip(" -、:：;；，。")
        return body

    def _strip_leading_codes(self, text: str) -> str:
        body = self._normalize_text(text)
        while True:
            matched_clause = self._CLAUSE_PATTERN.match(body)
            if matched_clause is None:
                break
            body = self._normalize_text(matched_clause.group("body"))
        return body

    def _is_generic_heading(self, text: str) -> bool:
        chapter_match = self._CHAPTER_PATTERN.match(self._normalize_text(text))
        if chapter_match is not None:
            title = self._normalize_text(chapter_match.group("title"))
            if not title:
                return True
            text = title
        return text in self._GENERIC_HEADINGS or len(text) <= 3

    def _normalize_text(self, text: str) -> str:
        return re.sub(r"\s+", " ", text.replace("\u3000", " ")).strip()

    def _extract_standards(self, lines: list[str]) -> list[str]:
        pattern = re.compile(r"(?<![A-Za-z0-9])(?:GB|ISO|IEC|DL/T)[A-Za-z0-9\-/]*(?![A-Za-z0-9])", re.IGNORECASE)
        standards: list[str] = []
        for line in lines:
            found = pattern.findall(line)
            for item in found:
                normalized = item.upper()
                if normalized not in standards:
                    standards.append(normalized)
            if len(standards) >= 20:
                break
        return standards

    def _extract_acceptance(self, lines: list[str]) -> list[str]:
        acceptance = [line for line in lines if "验收" in line][:20]
        return acceptance
