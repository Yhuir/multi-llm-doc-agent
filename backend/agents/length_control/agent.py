"""Length control agent that normalizes and trims text without inventing local filler."""

from __future__ import annotations

import re
from typing import Iterable

from backend.models.schemas import NodeText, RequirementDocument


class LengthControlAgent:
    """Control node text length without injecting any local template text."""

    def control(
        self,
        *,
        node_text: NodeText,
        requirement: RequirementDocument,
        min_words: int = 1950,
        max_words: int = 2050,
        max_expand_rounds: int = 2,
    ) -> tuple[NodeText, dict]:
        del requirement
        updated = node_text.model_copy(deep=True)
        self._normalize_node_text(updated)
        before = self.count_text_units(self._paragraph_texts(updated))
        action = "PASS"

        if before > max_words:
            action = "TRIM"
            self._trim_to_range(updated, max_words)

        self._normalize_node_text(updated)
        updated.word_count = self.count_text_units(self._paragraph_texts(updated))
        needs_expansion = updated.word_count < min_words
        if needs_expansion:
            action = "EXPAND_REQUIRED" if action == "PASS" else "TRIM_EXPAND_REQUIRED"
        result = "PASS" if min_words <= updated.word_count <= max_words else "FAIL"

        return updated, {
            "node_uid": updated.node_uid,
            "before_word_count": before,
            "after_word_count": updated.word_count,
            "action": action,
            "expand_rounds": 0,
            "result": result,
            "forced_fill": False,
            "min_words": min_words,
            "max_words": max_words,
            "missing_words": max(0, min_words - updated.word_count),
            "needs_llm_revision": needs_expansion,
            "max_expand_rounds": max_expand_rounds,
        }

    def _normalize_node_text(self, node_text: NodeText) -> None:
        for section in node_text.sections:
            section.title = self._normalize_text(section.title, add_terminal_punctuation=False)
            for paragraph in section.paragraphs:
                paragraph.text = self._normalize_text(paragraph.text, add_terminal_punctuation=False)

    def _normalize_text(self, text: str, *, add_terminal_punctuation: bool = False) -> str:
        cleaned = str(text or "")
        cleaned = cleaned.replace("\n", "").replace("\r", "")
        cleaned = re.sub(r"\s+", "", cleaned)
        replacements = (
            ("。，", "。"),
            ("，。", "。"),
            ("；。", "。"),
            ("：。", "。"),
            ("。。", "。"),
            ("，，", "，"),
            ("；；", "；"),
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

    def _trim_to_range(self, node_text: NodeText, max_words: int) -> None:
        current = self.count_text_units(self._paragraph_texts(node_text))
        while current > max_words:
            target_section = None
            for section in reversed(node_text.sections):
                if section.paragraphs:
                    target_section = section
                    break
            if target_section is None:
                break

            paragraph = target_section.paragraphs[-1]
            paragraph_len = len(paragraph.text.strip())
            overflow = current - max_words

            if paragraph_len > overflow:
                paragraph.text = paragraph.text[:-overflow]
                current = self.count_text_units(self._paragraph_texts(node_text))
                continue

            target_section.paragraphs.pop()
            current = self.count_text_units(self._paragraph_texts(node_text))

    @staticmethod
    def _paragraph_texts(node_text: NodeText) -> Iterable[str]:
        for section in node_text.sections:
            for paragraph in section.paragraphs:
                yield paragraph.text

    @staticmethod
    def count_text_units(paragraphs: Iterable[str]) -> int:
        merged = "".join(part.strip() for part in paragraphs)
        return len(merged)
