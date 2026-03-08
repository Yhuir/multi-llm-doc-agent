"""Word export agent that renders layout blocks into output.docx."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Any
from zipfile import ZIP_DEFLATED, ZipFile

from docx import Document
from docx.document import Document as DocumentObject
from docx.enum.table import WD_CELL_VERTICAL_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn
from docx.shared import Emu, Pt, RGBColor
from lxml import etree
from PIL import Image


class WordExportAgent:
    """Render layout blocks into a docx based on the standard template."""

    def export(
        self,
        *,
        template_path: Path,
        layout_blocks_path: Path,
        output_path: Path,
    ) -> tuple[Path, list[str]]:
        if not template_path.exists():
            raise FileNotFoundError(f"Template missing: {template_path}")

        try:
            document = Document(template_path)
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(f"Failed to open template: {template_path}") from exc

        _remove_initial_empty_paragraph(document)
        payload = json.loads(layout_blocks_path.read_text(encoding="utf-8"))
        blocks = payload.get("blocks") or []
        warnings = list(payload.get("warnings") or [])
        writer = _DocumentWriter(document)

        for block in blocks:
            block_type = block.get("type")
            if block_type == "page_break":
                document.add_page_break()
                continue
            if block_type == "heading":
                writer.add_paragraph(
                    text=str(block.get("text") or ""),
                    style_name=str(block.get("style_name") or "Normal"),
                    warnings=warnings,
                )
                continue
            if block_type == "paragraph":
                writer.add_body_paragraph(
                    text=str(block.get("text") or ""),
                    style_name=str(block.get("style_name") or "Normal"),
                    warnings=warnings,
                )
                continue
            if block_type == "section_heading":
                writer.add_section_heading(
                    text=str(block.get("text") or ""),
                    style_name=str(block.get("style_name") or "Normal"),
                    warnings=warnings,
                )
                continue
            if block_type == "table":
                writer.add_table(block=block, warnings=warnings)
                continue
            if block_type == "image":
                writer.add_image(block=block, warnings=warnings)
                continue
            warnings.append(f"Unsupported layout block type: {block_type}")

        output_path.parent.mkdir(parents=True, exist_ok=True)
        document.save(output_path)
        numbering_warnings = _normalize_docx_numbering(output_path)
        warnings.extend(numbering_warnings)
        return output_path, warnings


class _DocumentWriter:
    """Append content to a docx while preserving template styles."""

    IMAGE_WIDTH_RATIO = 0.96
    IMAGE_HEIGHT_RATIO = 0.72
    IMAGE_CANVAS_SCALE = 0.9

    def __init__(self, document: DocumentObject) -> None:
        self.document = document

    def add_paragraph(
        self,
        *,
        text: str,
        style_name: str,
        warnings: list[str],
    ) -> None:
        paragraph = self._next_paragraph()
        paragraph.text = text
        paragraph.style = self._resolve_style(
            style_name=style_name,
            fallback="Normal",
            warnings=warnings,
        )
        _disable_list_numbering(paragraph)
        paragraph.paragraph_format.keep_with_next = True

    def add_section_heading(
        self,
        *,
        text: str,
        style_name: str,
        warnings: list[str],
    ) -> None:
        paragraph = self._next_paragraph()
        paragraph.style = self._resolve_style(
            style_name=style_name,
            fallback="Normal",
            warnings=warnings,
        )
        _disable_list_numbering(paragraph)
        paragraph.paragraph_format.keep_with_next = True
        paragraph.paragraph_format.first_line_indent = Pt(0)
        paragraph.paragraph_format.space_before = Pt(8)
        paragraph.paragraph_format.space_after = Pt(4)
        paragraph.paragraph_format.line_spacing = 1.5
        run = paragraph.add_run(text)
        run.bold = True
        run.font.color.rgb = RGBColor(0x00, 0x70, 0xC0)

    def add_body_paragraph(
        self,
        *,
        text: str,
        style_name: str,
        warnings: list[str],
    ) -> None:
        paragraph = self._next_paragraph()
        paragraph.text = text
        paragraph.style = self._resolve_style(
            style_name=style_name,
            fallback="Normal",
            warnings=warnings,
        )
        _disable_list_numbering(paragraph)
        paragraph.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
        paragraph.paragraph_format.first_line_indent = Pt(24)
        paragraph.paragraph_format.line_spacing = 1.5
        paragraph.paragraph_format.space_before = Pt(0)
        paragraph.paragraph_format.space_after = Pt(0)

    def add_table(self, *, block: dict[str, Any], warnings: list[str]) -> None:
        headers = [str(item) for item in (block.get("headers") or [])]
        rows = block.get("rows") or []
        if not headers:
            warnings.append(f"Table {block.get('table_id')} has no headers; skipped.")
            return

        title = str(block.get("title") or "").strip()
        if title:
            self.add_paragraph(text=title, style_name="Normal", warnings=warnings)

        table = self.document.add_table(rows=1, cols=len(headers))
        style_name = str(block.get("style_name") or "BiddingTable")
        if style_name in {style.name for style in self.document.styles}:
            table.style = style_name
        else:
            warnings.append(f"Table style {style_name} missing in template; using default table style.")

        header_cells = table.rows[0].cells
        for idx, header in enumerate(headers):
            header_cells[idx].text = header
            self._center_table_cell(header_cells[idx])

        for row in rows:
            cells = table.add_row().cells
            values = [str(item) for item in row]
            for idx in range(len(headers)):
                cells[idx].text = values[idx] if idx < len(values) else ""
                self._center_table_cell(cells[idx])

    def add_image(self, *, block: dict[str, Any], warnings: list[str]) -> None:
        image_path = Path(str(block.get("path") or ""))
        if not image_path.exists():
            warnings.append(f"Image file missing: {image_path}")
            return

        render_path, cleanup_path = self._prepare_image_for_layout(
            image_path=image_path,
            warnings=warnings,
        )
        width, height = self._fit_image_size(image_path=render_path, warnings=warnings)
        paragraph = self._next_paragraph()
        paragraph.style = self._resolve_style(
            style_name="Normal",
            fallback="Normal",
            warnings=warnings,
        )
        _disable_list_numbering(paragraph)
        paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
        paragraph.paragraph_format.keep_with_next = True
        paragraph.paragraph_format.space_before = Pt(6)
        paragraph.paragraph_format.space_after = Pt(6)
        paragraph.paragraph_format.first_line_indent = Pt(0)
        paragraph.paragraph_format.line_spacing = 1.0
        run = paragraph.add_run()
        try:
            run.add_picture(str(render_path), width=width, height=height)
        finally:
            if cleanup_path is not None and cleanup_path.exists():
                cleanup_path.unlink()

    def _next_paragraph(self):
        return self.document.add_paragraph()

    def _resolve_style(
        self,
        *,
        style_name: str,
        fallback: str,
        warnings: list[str],
    ) -> str | None:
        style_names = {style.name for style in self.document.styles}
        if style_name in style_names:
            return style_name
        if style_name.startswith("Heading "):
            try:
                level = int(style_name.split()[-1])
            except ValueError:
                level = 1
            while level >= 1:
                candidate = f"Heading {level}"
                if candidate in style_names:
                    warnings.append(
                        f"Style {style_name} missing in template; fallback to {candidate}."
                    )
                    return candidate
                level -= 1
        if fallback in style_names:
            warnings.append(f"Style {style_name} missing in template; fallback to {fallback}.")
            return fallback
        warnings.append(f"Style {style_name} missing and no fallback found; document default used.")
        return None

    def _fit_image_size(self, *, image_path: Path, warnings: list[str]) -> tuple[Emu, Emu]:
        section = self.document.sections[-1]
        available_width = int(section.page_width - section.left_margin - section.right_margin)
        available_height = int(section.page_height - section.top_margin - section.bottom_margin)

        try:
            with Image.open(image_path) as image:
                pixel_width, pixel_height = image.size
        except Exception as exc:  # noqa: BLE001
            warnings.append(f"Failed to inspect image size for {image_path}: {exc}")
            fallback_side = min(
                int(available_width * self.IMAGE_WIDTH_RATIO),
                int(available_height * self.IMAGE_HEIGHT_RATIO),
            )
            return Emu(fallback_side), Emu(fallback_side)

        aspect_ratio = pixel_width / max(pixel_height, 1)
        max_width = max(
            int(available_width * self.IMAGE_WIDTH_RATIO),
            int(available_width * 0.75),
        )
        max_height = max(
            int(available_height * self.IMAGE_HEIGHT_RATIO),
            int(available_height * 0.4),
        )
        target_width = max_width
        target_height = int(target_width / max(aspect_ratio, 0.01))
        if target_height > max_height:
            target_height = max_height
            target_width = int(target_height * aspect_ratio)

        return Emu(target_width), Emu(target_height)

    def _prepare_image_for_layout(
        self,
        *,
        image_path: Path,
        warnings: list[str],
    ) -> tuple[Path, Path | None]:
        try:
            with Image.open(image_path) as source:
                source_rgb = source.convert("RGB")
                side = max(source_rgb.width, source_rgb.height)
                canvas = Image.new("RGB", (side, side), (255, 255, 255))
                max_inner = int(side * self.IMAGE_CANVAS_SCALE)
                resized = source_rgb.copy()
                resized.thumbnail((max_inner, max_inner))
                offset = (
                    (side - resized.width) // 2,
                    (side - resized.height) // 2,
                )
                canvas.paste(resized, offset)
        except Exception as exc:  # noqa: BLE001
            warnings.append(f"Failed to square image for {image_path}: {exc}")
            return image_path, None

        handle = tempfile.NamedTemporaryFile(delete=False, suffix=".png")
        temp_path = Path(handle.name)
        handle.close()
        canvas.save(temp_path)
        return temp_path, temp_path

    @staticmethod
    def _center_table_cell(cell) -> None:
        cell.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
        for paragraph in cell.paragraphs:
            paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
            paragraph.paragraph_format.first_line_indent = Pt(0)
            paragraph.paragraph_format.space_before = Pt(0)
            paragraph.paragraph_format.space_after = Pt(0)


def _remove_initial_empty_paragraph(document: DocumentObject) -> None:
    if len(document.paragraphs) != 1:
        return
    paragraph = document.paragraphs[0]
    if paragraph.text.strip():
        return
    if paragraph.style and paragraph.style.name != "Normal":
        return
    element = paragraph._element
    parent = element.getparent()
    if parent is not None:
        parent.remove(element)


def _disable_list_numbering(paragraph) -> None:
    ppr = paragraph._p.get_or_add_pPr()
    for child in list(ppr):
        if child.tag == qn("w:numPr"):
            ppr.remove(child)


def _normalize_docx_numbering(docx_path: Path) -> list[str]:
    namespace = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
    heading_levels = {
        "一级标题": 0,
        "二级标题": 1,
        "三级标题": 2,
    }
    warnings: list[str] = []

    with ZipFile(docx_path, "r") as source_zip:
        styles_xml = source_zip.read("word/styles.xml")
        document_xml = source_zip.read("word/document.xml")
        other_files = {
            info.filename: source_zip.read(info.filename)
            for info in source_zip.infolist()
            if info.filename not in {"word/styles.xml", "word/document.xml"}
        }

    styles_root = etree.fromstring(styles_xml)
    document_root = etree.fromstring(document_xml)

    heading_style_ids: set[str] = set()
    normal_style_id: str | None = None
    for style_name, _level in heading_levels.items():
        style_nodes = styles_root.xpath(
            f"//w:style[w:name[@w:val='{style_name}']]",
            namespaces=namespace,
        )
        if not style_nodes:
            warnings.append(f"Heading style {style_name} missing in template styles.xml.")
            continue
        style_node = style_nodes[0]
        style_id = style_node.get(qn("w:styleId"))
        if not style_id:
            warnings.append(f"Heading style {style_name} missing styleId.")
            continue
        heading_style_ids.add(style_id)

    normal_style_nodes = styles_root.xpath(
        "//w:style[w:name[@w:val='Normal']]",
        namespaces=namespace,
    )
    if normal_style_nodes:
        normal_style_id = normal_style_nodes[0].get(qn("w:styleId"))

    for paragraph in document_root.xpath("//w:p", namespaces=namespace):
        ppr_nodes = paragraph.xpath("./w:pPr", namespaces=namespace)
        if ppr_nodes:
            ppr = ppr_nodes[0]
        else:
            ppr = etree.Element(qn("w:pPr"))
            paragraph.insert(0, ppr)
        style_nodes = ppr.xpath("./w:pStyle", namespaces=namespace)
        style_id = style_nodes[0].get(qn("w:val")) if style_nodes else None
        for numpr in ppr.xpath("./w:numPr", namespaces=namespace):
            ppr.remove(numpr)
        if style_id in heading_style_ids:
            continue
        if (
            normal_style_id
            and style_id is None
            and not paragraph.xpath("ancestor::w:tc", namespaces=namespace)
        ):
            pstyle = etree.Element(qn("w:pStyle"))
            pstyle.set(qn("w:val"), normal_style_id)
            ppr.insert(0, pstyle)

    normalized_xml = etree.tostring(
        document_root,
        encoding="UTF-8",
        xml_declaration=True,
        standalone="yes",
    )
    residual_numid_zero = normalized_xml.count(b'w:numId w:val="0"')
    if residual_numid_zero:
        warnings.append(f"Residual numId=0 found after normalization: {residual_numid_zero}")

    temp_output = docx_path.with_suffix(".tmp.docx")
    with ZipFile(temp_output, "w", compression=ZIP_DEFLATED) as target_zip:
        target_zip.writestr("word/styles.xml", styles_xml)
        target_zip.writestr("word/document.xml", normalized_xml)
        for filename, content in other_files.items():
            target_zip.writestr(filename, content)

    temp_output.replace(docx_path)
    return warnings
