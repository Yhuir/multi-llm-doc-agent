"""Engineering-practical relevance check for V1 images."""

from __future__ import annotations

from backend.models.enums import AgentResult
from backend.models.schemas import (
    EntityExtraction,
    ImageItem,
    ImageRelevanceReport,
    ImageScoreItem,
    ImagesArtifact,
    NodeText,
)


class ImageRelevanceAgent:
    """Rule-based image relevance scoring with retry-friendly outputs."""

    def __init__(self, *, score_threshold: float = 0.75) -> None:
        self.score_threshold = score_threshold

    def evaluate(
        self,
        *,
        node_text: NodeText,
        entities: EntityExtraction,
        images: ImagesArtifact,
    ) -> ImageRelevanceReport:
        scores = [
            self._evaluate_image(node_text=node_text, entities=entities, image=image)
            for image in images.images
        ]
        overall = (
            AgentResult.PASS
            if all(item.result == AgentResult.PASS for item in scores)
            else AgentResult.FAIL
        )
        if not scores:
            overall = AgentResult.PASS
        return ImageRelevanceReport(
            node_uid=node_text.node_uid,
            image_scores=scores,
            overall_result=overall,
        )

    def _evaluate_image(
        self,
        *,
        node_text: NodeText,
        entities: EntityExtraction,
        image: ImageItem,
    ) -> ImageScoreItem:
        context = " ".join(
            [
                node_text.title,
                node_text.summary,
                *[section.title for section in node_text.sections],
                *[entity.name for entity in entities.entities],
            ]
        )
        missing_elements = self._missing_elements(image)
        score = self._score_image(image=image, context=context, missing_elements=missing_elements)
        result = (
            AgentResult.PASS
            if score >= self.score_threshold and not missing_elements
            else AgentResult.FAIL
        )
        return ImageScoreItem(
            image_id=image.image_id,
            score=score,
            missing_elements=missing_elements,
            result=result,
        )

    def _score_image(
        self,
        *,
        image: ImageItem,
        context: str,
        missing_elements: list[str],
    ) -> float:
        base = {
            "topology": 0.86,
            "process": 0.63,
            "layout": 0.60,
            "acceptance": 0.46,
        }.get(image.type, 0.60)
        if image.bind_section and image.bind_section in context:
            base += 0.04
        if image.bind_anchor and image.bind_anchor != "anchor_default":
            base += 0.03
        base += min(image.retry_count, 3) * 0.08
        base -= len(missing_elements) * 0.12
        return round(max(0.0, min(base, 0.99)), 2)

    @staticmethod
    def _missing_elements(image: ImageItem) -> list[str]:
        if image.type == "topology":
            return []
        if image.type in {"process", "layout"} and image.retry_count == 0:
            return image.must_have_elements[-1:] if image.must_have_elements else []
        if image.type == "acceptance":
            return image.must_have_elements[-1:] if image.must_have_elements else ["验收标注"]
        return []
