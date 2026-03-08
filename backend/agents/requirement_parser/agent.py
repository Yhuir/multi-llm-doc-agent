"""Rule-based requirement parser agent for V1 skeleton."""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

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


class RequirementParserAgent:
    """Parses .docx into requirement.json and parse_report-compatible payload."""

    def parse(
        self,
        *,
        task_id: str,
        upload_file_path: Path,
        fallback_title: str,
    ) -> tuple[RequirementDocument, dict]:
        if upload_file_path.suffix.lower() != ".docx":
            raise ValueError("Only .docx is supported.")

        lines = self._extract_docx_text(upload_file_path)
        has_original_content = bool(lines)
        if not lines:
            lines = [fallback_title.strip() or "项目需求说明"]
        source_index = self._build_source_index(lines)
        subsystems = self._extract_subsystems(lines)
        standards = self._extract_standards(lines)
        acceptance = self._extract_acceptance(lines)

        requirement = RequirementDocument(
            project=RequirementProject(
                name=lines[0] if lines else fallback_title,
                customer="",
                location="",
                duration_days=None,
                milestones=[],
            ),
            scope=RequirementScope(
                overview=lines[0] if lines else "",
                subsystems=subsystems,
            ),
            constraints=RequirementConstraints(
                standards=standards,
                acceptance=acceptance,
            ),
            source_index=source_index,
        )

        missing_fields: list[str] = []
        if not has_original_content:
            missing_fields.extend(["project.name", "scope.overview", "scope.subsystems"])
        if not standards:
            missing_fields.append("constraints.standards")
        if not acceptance:
            missing_fields.append("constraints.acceptance")

        parse_report = {
            "task_id": task_id,
            "source_file": str(upload_file_path),
            "result": AgentResult.PASS.value,
            "paragraph_count": len(lines),
            "subsystem_count": len(subsystems),
            "missing_fields": missing_fields,
            "warnings": [
                "TODO: replace rule-based parser with richer extraction in later rounds"
            ],
            "generated_at": utc_now_iso(),
        }
        return requirement, parse_report

    def _extract_docx_text(self, file_path: Path) -> list[str]:
        try:
            with zipfile.ZipFile(file_path) as archive:
                xml_bytes = archive.read("word/document.xml")
        except (zipfile.BadZipFile, KeyError) as exc:
            raise ValueError(f"Cannot parse docx file: {file_path}") from exc

        root = ET.fromstring(xml_bytes)
        ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
        lines: list[str] = []
        for paragraph in root.findall(".//w:p", ns):
            texts = [t.text for t in paragraph.findall(".//w:t", ns) if t.text]
            merged = "".join(texts).strip()
            if merged:
                lines.append(merged)
        return lines

    def _build_source_index(self, lines: list[str]) -> dict[str, SourceIndexItem]:
        source_index: dict[str, SourceIndexItem] = {}
        for idx, text in enumerate(lines[:300], start=1):
            ref = f"p1#L{idx}"
            source_index[ref] = SourceIndexItem(
                page=1,
                paragraph_id=f"para_{idx}",
                text=text,
            )
        return source_index

    def _extract_subsystems(self, lines: list[str]) -> list[RequirementSubsystem]:
        named = [line for line in lines if "子系统" in line][:6]
        subsystems: list[RequirementSubsystem] = []

        if named:
            for idx, line in enumerate(named, start=1):
                ref = f"p1#L{idx}"
                subsystems.append(
                    RequirementSubsystem(
                        name=line[:60],
                        description=line,
                        requirements=[
                            RequirementItem(
                                type="text",
                                key="scope",
                                value=line,
                                source_ref=ref,
                            )
                        ],
                        interfaces=[],
                    )
                )
            return subsystems

        fallback = lines[1:4] if len(lines) > 1 else ["基础实施范围"]
        for idx, line in enumerate(fallback, start=1):
            line_no = idx + 1
            if line_no > max(len(lines), 1):
                line_no = 1
            ref = f"p1#L{line_no}"
            subsystems.append(
                RequirementSubsystem(
                    name=f"子系统{idx}",
                    description=line,
                    requirements=[
                        RequirementItem(
                            type="text",
                            key="scope",
                            value=line,
                            source_ref=ref,
                        )
                    ],
                    interfaces=[],
                )
            )
        return subsystems

    def _extract_standards(self, lines: list[str]) -> list[str]:
        pattern = re.compile(r"\b(?:GB|ISO|IEC|DL/T)[\w\-/]*", re.IGNORECASE)
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
