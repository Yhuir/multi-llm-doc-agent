"""Image generation agent with provider-specific API integrations."""

from __future__ import annotations

import json
import struct
import zlib
from pathlib import Path
from typing import Any
from urllib import error as urllib_error
from urllib import parse as urllib_parse
from urllib import request as urllib_request

from backend.models.schemas import ImageItem, ImagePromptItem

try:
    from PIL import Image, ImageDraw
except Exception:  # noqa: BLE001
    Image = None
    ImageDraw = None


class ImageGenerationAgent:
    """Generate images via configured provider or deterministic placeholders."""

    DEFAULT_ASPECT_RATIO = "3:2"
    ASPECT_RATIO_VALUES = {
        "2:1": 2.0,
        "3:2": 1.5,
    }
    MINIMAX_ASPECT_RATIO_MAP = {
        "2:1": "16:9",
        "3:2": "3:2",
    }
    PLACEHOLDER_WIDTH = 1440
    MINIMAX_ENDPOINT = "https://api.minimaxi.com/v1/image_generation"
    MINIMAX_MODEL_MAP = {
        "MiniMax-M2.5": "image-01",
        "image-01": "image-01",
        "image-01-live": "image-01-live",
    }
    WHATAI_ENDPOINT = "https://api.whatai.cc/v1/images/generations"
    WHATAI_MODEL_MAP = {
        "nano-banana": "nano-banana",
    }
    WHATAI_SIZE_MAP = {
        "2:1": "1536x768",
        "3:2": "1536x1024",
    }
    DOUBAO_ENDPOINT = "https://ark.cn-beijing.volces.com/api/v3/images/generations"
    DOUBAO_MODEL_ORDER = [
        "Doubao-Seedream-5.0-lite",
        "Doubao-Seedream-4.5",
        "Doubao-Seed3D-1.0",
        "Doubao-Seedream-4.0",
        "Doubao-Seedream-3.0-t2i",
    ]
    DOUBAO_MODEL_MAP = {
        "Doubao-Seedream-5.0-lite": "doubao-seedream-5-0-lite",
        "doubao-seedream-5-0-lite": "doubao-seedream-5-0-lite",
        "Doubao-Seedream-4.5": "doubao-seedream-4-5-251128",
        "doubao-seedream-4-5-251128": "doubao-seedream-4-5-251128",
        "Doubao-Seed3D-1.0": "doubao-seed3d-1-0",
        "doubao-seed3d-1-0": "doubao-seed3d-1-0",
        "Doubao-Seedream-4.0": "doubao-seedream-4-0-250828",
        "doubao-seedream-4-0-250828": "doubao-seedream-4-0-250828",
        "Doubao-Seedream-3.0-t2i": "doubao-seedream-3-0-t2i-250415",
        "doubao-seedream-3-0-t2i-250415": "doubao-seedream-3-0-t2i-250415",
    }

    def generate(
        self,
        *,
        prompt_item: ImagePromptItem,
        node_dir: Path,
        retry_count: int,
        provider_config: dict[str, Any] | None = None,
    ) -> ImageItem:
        image_id = prompt_item.prompt_id.replace("prompt", "img")
        relative_stem = Path("images") / image_id
        absolute_stem = node_dir / relative_stem
        absolute_stem.parent.mkdir(parents=True, exist_ok=True)
        if self._use_doubao(provider_config):
            absolute_path = self._generate_via_doubao(
                output_stem=absolute_stem,
                prompt_item=prompt_item,
                provider_config=provider_config or {},
            )
        elif self._use_whatai(provider_config):
            absolute_path = self._generate_via_whatai(
                output_stem=absolute_stem,
                prompt_item=prompt_item,
                provider_config=provider_config or {},
            )
        elif self._use_minimax(provider_config):
            absolute_path = self._generate_via_minimax(
                output_stem=absolute_stem,
                prompt_item=prompt_item,
                provider_config=provider_config or {},
            )
        else:
            absolute_path = absolute_stem.with_suffix(".png")
            self._write_placeholder_png(
                absolute_path,
                prompt_item=prompt_item,
                color_seed=f"{prompt_item.prompt_id}:{prompt_item.image_type}:{retry_count}",
            )
        relative_path = absolute_path.relative_to(node_dir)
        return ImageItem(
            image_id=image_id,
            type=prompt_item.image_type,
            file=str(relative_path),
            caption=self._build_caption(prompt_item, image_id),
            style_preset=prompt_item.style_preset,
            style_variant=prompt_item.style_variant,
            aspect_ratio=self._normalize_aspect_ratio(prompt_item.aspect_ratio),
            group_caption=None,
            prompt_id=prompt_item.prompt_id,
            must_have_elements=list(prompt_item.must_have_elements),
            bind_anchor=prompt_item.bind_anchor,
            bind_section=prompt_item.bind_section,
            retry_count=retry_count,
        )

    def _generate_via_minimax(
        self,
        *,
        output_stem: Path,
        prompt_item: ImagePromptItem,
        provider_config: dict[str, Any],
    ) -> Path:
        api_key = str(provider_config.get("image_api_key") or "").strip()
        if not api_key:
            raise RuntimeError("MiniMax image provider selected but image_api_key is empty.")

        selected_model = str(provider_config.get("image_model_name") or "MiniMax-M2.5").strip() or "MiniMax-M2.5"
        model_name = self._resolve_minimax_model(selected_model)
        payload = {
            "model": model_name,
            "prompt": prompt_item.prompt,
            "aspect_ratio": self._provider_aspect_ratio(
                prompt_item.aspect_ratio,
                provider="minimax",
            ),
            "response_format": "url",
            "n": 1,
            "prompt_optimizer": True,
        }
        image_url = self._request_minimax_image_url(api_key=api_key, payload=payload)
        provider_config["_resolved_image_model_name"] = selected_model
        provider_config["_resolved_image_model_id"] = model_name
        provider_config["_image_model_attempts"] = [selected_model]
        provider_config.pop("_image_model_fallback_from", None)
        return self._download_image_url(image_url=image_url, output_stem=output_stem)

    def _generate_via_doubao(
        self,
        *,
        output_stem: Path,
        prompt_item: ImagePromptItem,
        provider_config: dict[str, Any],
    ) -> Path:
        api_key = str(provider_config.get("image_api_key") or "").strip()
        if not api_key:
            raise RuntimeError("Doubao image provider selected but image_api_key is empty.")

        selected_model = str(provider_config.get("image_model_name") or "").strip()
        provider_config.pop("_resolved_image_model_name", None)
        provider_config.pop("_resolved_image_model_id", None)
        provider_config.pop("_image_model_attempts", None)
        provider_config.pop("_image_model_fallback_from", None)
        model_attempts: list[str] = []
        errors: list[str] = []

        for model_label in self._doubao_model_candidates(selected_model):
            model_attempts.append(model_label)
            model_name = self._resolve_doubao_model(model_label)
            payload = {
                "model": model_name,
                "prompt": prompt_item.prompt,
                "sequential_image_generation": "disabled",
                "response_format": "url",
                "size": "2K",
                "stream": False,
                "watermark": True,
            }
            try:
                image_url = self._request_doubao_image_url(api_key=api_key, payload=payload)
                provider_config["_resolved_image_model_name"] = model_label
                provider_config["_resolved_image_model_id"] = model_name
                provider_config["_image_model_attempts"] = list(model_attempts)
                if selected_model and model_label != selected_model:
                    provider_config["_image_model_fallback_from"] = selected_model
                return self._download_image_url(image_url=image_url, output_stem=output_stem)
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{model_label}: {exc}")
                continue

        raise RuntimeError(
            "Doubao image generation failed after automatic model fallback: "
            + " | ".join(errors)
        )

    def _generate_via_whatai(
        self,
        *,
        output_stem: Path,
        prompt_item: ImagePromptItem,
        provider_config: dict[str, Any],
    ) -> Path:
        api_key = str(provider_config.get("image_api_key") or "").strip()
        if not api_key:
            raise RuntimeError("nano-banana image provider selected but image_api_key is empty.")

        selected_model = str(provider_config.get("image_model_name") or "nano-banana").strip() or "nano-banana"
        model_name = self._resolve_whatai_model(selected_model)
        payload = {
            "model": model_name,
            "prompt": prompt_item.prompt,
            "n": 1,
            "response_format": "url",
            "aspect_ratio": self._normalize_aspect_ratio(prompt_item.aspect_ratio),
            "size": self._whatai_size(prompt_item.aspect_ratio),
        }
        image_url = self._request_whatai_image_url(api_key=api_key, payload=payload)
        provider_config["_resolved_image_model_name"] = selected_model
        provider_config["_resolved_image_model_id"] = model_name
        provider_config["_image_model_attempts"] = [selected_model]
        provider_config.pop("_image_model_fallback_from", None)
        return self._download_image_url(image_url=image_url, output_stem=output_stem)

    @classmethod
    def _resolve_minimax_model(cls, model_name: str) -> str:
        normalized = model_name.strip()
        if normalized in cls.MINIMAX_MODEL_MAP:
            return cls.MINIMAX_MODEL_MAP[normalized]
        return cls.MINIMAX_MODEL_MAP["MiniMax-M2.5"]

    @classmethod
    def _resolve_whatai_model(cls, model_name: str) -> str:
        normalized = model_name.strip()
        if normalized in cls.WHATAI_MODEL_MAP:
            return cls.WHATAI_MODEL_MAP[normalized]
        return cls.WHATAI_MODEL_MAP["nano-banana"]

    @classmethod
    def _resolve_doubao_model(cls, model_name: str) -> str:
        normalized = model_name.strip()
        if normalized in cls.DOUBAO_MODEL_MAP:
            return cls.DOUBAO_MODEL_MAP[normalized]
        if normalized.startswith("doubao-seedream-"):
            return normalized
        if normalized.startswith("doubao-seed3d-"):
            return normalized
        return cls.DOUBAO_MODEL_MAP["Doubao-Seedream-4.5"]

    @classmethod
    def _doubao_model_candidates(cls, selected_model: str) -> list[str]:
        normalized = selected_model.strip()
        if not normalized:
            return list(cls.DOUBAO_MODEL_ORDER)
        ordered = [normalized]
        for item in cls.DOUBAO_MODEL_ORDER:
            if item != normalized:
                ordered.append(item)
        return ordered

    @staticmethod
    def _use_doubao(provider_config: dict[str, Any] | None) -> bool:
        if not provider_config:
            return False
        provider = str(provider_config.get("image_provider") or "").strip().lower()
        return provider == "doubao"

    @staticmethod
    def _use_whatai(provider_config: dict[str, Any] | None) -> bool:
        if not provider_config:
            return False
        provider = str(provider_config.get("image_provider") or "").strip().lower()
        api_key = str(provider_config.get("image_api_key") or "").strip()
        return provider in {"whatai", "google"} and bool(api_key)

    @staticmethod
    def _use_minimax(provider_config: dict[str, Any] | None) -> bool:
        if not provider_config:
            return False
        provider = str(provider_config.get("image_provider") or "").strip().lower()
        api_key = str(provider_config.get("image_api_key") or "").strip()
        return provider == "minimax" and bool(api_key)

    @classmethod
    def _normalize_aspect_ratio(cls, aspect_ratio: str | None) -> str:
        normalized = str(aspect_ratio or "").strip()
        if normalized in cls.ASPECT_RATIO_VALUES:
            return normalized
        return cls.DEFAULT_ASPECT_RATIO

    @classmethod
    def _provider_aspect_ratio(cls, aspect_ratio: str | None, *, provider: str) -> str:
        normalized = cls._normalize_aspect_ratio(aspect_ratio)
        if provider == "minimax":
            return cls.MINIMAX_ASPECT_RATIO_MAP.get(
                normalized,
                cls.MINIMAX_ASPECT_RATIO_MAP[cls.DEFAULT_ASPECT_RATIO],
            )
        return normalized

    @classmethod
    def _whatai_size(cls, aspect_ratio: str | None) -> str:
        normalized = cls._normalize_aspect_ratio(aspect_ratio)
        return cls.WHATAI_SIZE_MAP.get(normalized, cls.WHATAI_SIZE_MAP[cls.DEFAULT_ASPECT_RATIO])

    def _request_minimax_image_url(self, *, api_key: str, payload: dict[str, Any]) -> str:
        request = urllib_request.Request(
            self.MINIMAX_ENDPOINT,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}",
            },
            method="POST",
        )
        try:
            with urllib_request.urlopen(request, timeout=90) as response:
                response_payload = json.loads(response.read().decode("utf-8"))
        except urllib_error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="ignore")
            raise RuntimeError(
                f"MiniMax image API HTTP {exc.code}: {detail[:400]}"
            ) from exc
        except urllib_error.URLError as exc:
            raise RuntimeError(f"MiniMax image API request failed: {exc.reason}") from exc

        base_resp = response_payload.get("base_resp") or {}
        if base_resp.get("status_code") not in (None, 0):
            raise RuntimeError(
                "MiniMax image API returned failure: "
                f"{base_resp.get('status_code')} {base_resp.get('status_msg') or ''}".strip()
            )

        data = response_payload.get("data") or {}
        image_urls = data.get("image_urls") or []
        if not image_urls or not isinstance(image_urls, list):
            raise RuntimeError(f"MiniMax image API returned no image urls: {response_payload}")
        image_url = str(image_urls[0] or "").strip()
        if not image_url:
            raise RuntimeError(f"MiniMax image API returned empty image url: {response_payload}")
        return image_url

    def _request_doubao_image_url(self, *, api_key: str, payload: dict[str, Any]) -> str:
        request = urllib_request.Request(
            self.DOUBAO_ENDPOINT,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}",
            },
            method="POST",
        )
        try:
            with urllib_request.urlopen(request, timeout=90) as response:
                response_payload = json.loads(response.read().decode("utf-8"))
        except urllib_error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="ignore")
            raise RuntimeError(
                f"Doubao image API HTTP {exc.code}: {detail[:400]}"
            ) from exc
        except urllib_error.URLError as exc:
            raise RuntimeError(f"Doubao image API request failed: {exc.reason}") from exc

        data_items = response_payload.get("data") or []
        if not data_items or not isinstance(data_items, list):
            raise RuntimeError(f"Doubao image API returned no data: {response_payload}")
        image_url = str((data_items[0] or {}).get("url") or "").strip()
        if not image_url:
            raise RuntimeError(f"Doubao image API returned no image url: {response_payload}")
        return image_url

    def _request_whatai_image_url(self, *, api_key: str, payload: dict[str, Any]) -> str:
        request = urllib_request.Request(
            self.WHATAI_ENDPOINT,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}",
            },
            method="POST",
        )
        try:
            with urllib_request.urlopen(request, timeout=90) as response:
                response_payload = json.loads(response.read().decode("utf-8"))
        except urllib_error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="ignore")
            raise RuntimeError(
                f"nano-banana image API HTTP {exc.code}: {detail[:400]}"
            ) from exc
        except urllib_error.URLError as exc:
            raise RuntimeError(f"nano-banana image API request failed: {exc.reason}") from exc

        if response_payload.get("error"):
            raise RuntimeError(f"nano-banana image API returned error: {response_payload['error']}")

        data_items = response_payload.get("data") or []
        if not data_items or not isinstance(data_items, list):
            raise RuntimeError(f"nano-banana image API returned no data: {response_payload}")
        image_url = str((data_items[0] or {}).get("url") or "").strip()
        if not image_url:
            raise RuntimeError(f"nano-banana image API returned no image url: {response_payload}")
        return image_url

    def _download_image_url(self, *, image_url: str, output_stem: Path) -> Path:
        request = urllib_request.Request(
            image_url,
            headers={
                "User-Agent": "multi-llm-doc-agent/0.1",
            },
            method="GET",
        )
        try:
            with urllib_request.urlopen(request, timeout=120) as response:
                content_type = response.headers.get("Content-Type", "")
                suffix = self._output_suffix(image_url=image_url, content_type=content_type)
                output_path = output_stem.with_suffix(suffix)
                output_path.write_bytes(response.read())
                return output_path
        except urllib_error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="ignore")
            raise RuntimeError(
                f"Failed to download generated image HTTP {exc.code}: {detail[:400]}"
            ) from exc
        except urllib_error.URLError as exc:
            raise RuntimeError(f"Failed to download generated image: {exc.reason}") from exc

    @staticmethod
    def _output_suffix(*, image_url: str, content_type: str) -> str:
        url_suffix = Path(urllib_parse.urlparse(image_url).path).suffix.lower()
        if url_suffix in {".jpg", ".jpeg", ".png", ".webp"}:
            return ".jpg" if url_suffix == ".jpeg" else url_suffix
        normalized = content_type.lower()
        if "jpeg" in normalized or "jpg" in normalized:
            return ".jpg"
        if "png" in normalized:
            return ".png"
        if "webp" in normalized:
            return ".webp"
        return ".jpg"

    @staticmethod
    def _build_caption(prompt_item: ImagePromptItem, image_id: str) -> str:
        section = prompt_item.bind_section or "当前小节"
        suffix = image_id.split("_")[-1]
        return f"图{suffix} {section}{prompt_item.image_type}示意"

    def _write_placeholder_png(
        self,
        path: Path,
        *,
        prompt_item: ImagePromptItem,
        color_seed: str,
    ) -> None:
        if Image is not None and ImageDraw is not None:
            self._write_schematic_placeholder(
                path=path,
                prompt_item=prompt_item,
                color_seed=color_seed,
            )
            return

        color = self._color_from_seed(color_seed)
        width, height = self._placeholder_dimensions(
            prompt_item.aspect_ratio,
            width=960,
        )
        pixel = bytes(color)
        rows = []
        for row_index in range(height):
            row_color = pixel
            if row_index % 72 < 8:
                row_color = bytes(max(channel - 24, 0) for channel in color)
            rows.append(bytes([0]) + row_color * width)
        payload = b"".join(rows)
        path.write_bytes(
            b"".join(
                [
                    b"\x89PNG\r\n\x1a\n",
                    self._chunk(
                        b"IHDR",
                        struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0),
                    ),
                    self._chunk(b"IDAT", zlib.compress(payload, level=9)),
                    self._chunk(b"IEND", b""),
                ]
            )
        )

    def _write_schematic_placeholder(
        self,
        *,
        path: Path,
        prompt_item: ImagePromptItem,
        color_seed: str,
    ) -> None:
        color = self._color_from_seed(color_seed)
        canvas_width, canvas_height = self._placeholder_dimensions(
            prompt_item.aspect_ratio,
            width=self.PLACEHOLDER_WIDTH,
        )
        canvas = Image.new(
            "RGB",
            (canvas_width, canvas_height),
            (248, 249, 251),
        )
        draw = ImageDraw.Draw(canvas)

        accent = color
        border = tuple(max(channel - 40, 0) for channel in color)
        title_bar = (accent[0], accent[1], min(accent[2] + 20, 255))

        margin_x = int(canvas_width * 0.03)
        margin_y = int(canvas_height * 0.04)
        title_left = margin_x + int(canvas_width * 0.015)
        title_top = margin_y + int(canvas_height * 0.02)
        title_right = canvas_width - title_left
        title_bottom = title_top + int(canvas_height * 0.10)
        draw.rounded_rectangle(
            (margin_x, margin_y, canvas_width - margin_x, canvas_height - margin_y),
            radius=24,
            outline=border,
            width=4,
            fill=(255, 255, 255),
        )
        draw.rounded_rectangle((title_left, title_top, title_right, title_bottom), radius=18, fill=title_bar)
        draw.text(
            (title_left + 24, title_top + 18),
            self._safe_ascii(prompt_item.bind_section, "Engineering Diagram"),
            fill=(255, 255, 255),
        )
        draw.text(
            (title_left + 24, title_top + 48),
            f"Type: {self._safe_ascii(prompt_item.image_type, 'process')}",
            fill=(245, 245, 245),
        )

        content_left = margin_x + int(canvas_width * 0.05)
        content_right = canvas_width - content_left
        box_gap = int(canvas_width * 0.05)
        box_top = int(canvas_height * 0.28)
        box_bottom = int(canvas_height * 0.58)
        box_width = int((content_right - content_left - box_gap * 2) / 3)
        box_specs = []
        current_left = content_left
        for _ in range(3):
            box_specs.append((current_left, box_top, current_left + box_width, box_bottom))
            current_left += box_width + box_gap

        labels = self._placeholder_labels(prompt_item)
        for idx, box in enumerate(box_specs):
            draw.rounded_rectangle(box, radius=20, outline=accent, width=4, fill=(247, 250, 253))
            draw.text((box[0] + 24, box[1] + 24), labels[idx], fill=(38, 57, 77))
            draw.text((box[0] + 24, box[1] + 72), f"Element: {labels[idx]}", fill=(83, 101, 122))

        arrow_y = int((box_top + box_bottom) / 2)
        for left_box, right_box in zip(box_specs, box_specs[1:]):
            line_start = left_box[2]
            line_end = right_box[0]
            draw.line((line_start, arrow_y, line_end, arrow_y), fill=accent, width=6)
            draw.polygon(
                [
                    (line_end - 15, arrow_y - 12),
                    (line_end, arrow_y),
                    (line_end - 15, arrow_y + 12),
                ],
                fill=accent,
            )

        must_have_text = " / ".join(
            self._safe_ascii(item, f"Item {idx}")
            for idx, item in enumerate(prompt_item.must_have_elements[:3], start=1)
        ) or "Item 1 / Item 2 / Item 3"
        draw.text(
            (title_left + 24, int(canvas_height * 0.72)),
            f"Must-have: {must_have_text}",
            fill=(48, 70, 92),
        )
        if prompt_item.forbidden_elements:
            forbidden_text = " / ".join(
                self._safe_ascii(item, f"Forbidden {idx}")
                for idx, item in enumerate(prompt_item.forbidden_elements[:2], start=1)
            )
            draw.text(
                (title_left + 24, int(canvas_height * 0.79)),
                f"Forbidden: {forbidden_text}",
                fill=(120, 78, 78),
            )

        canvas.save(path, format="PNG")

    @classmethod
    def _placeholder_dimensions(cls, aspect_ratio: str | None, *, width: int) -> tuple[int, int]:
        ratio_value = cls.ASPECT_RATIO_VALUES[cls._normalize_aspect_ratio(aspect_ratio)]
        return width, int(round(width / ratio_value))

    @staticmethod
    def _placeholder_labels(prompt_item: ImagePromptItem) -> list[str]:
        base = [
            ImageGenerationAgent._safe_ascii(item, f"Topic {idx}")
            for idx, item in enumerate(prompt_item.must_have_elements[:3], start=1)
            if item
        ]
        defaults_ascii = {
            "process": ["Input", "Process", "Output"],
            "architecture": ["Device", "Control", "Integration"],
            "acceptance": ["Check", "Action", "Record"],
            "equipment": ["Unit", "Interface", "Location"],
        }
        labels = base + defaults_ascii.get(prompt_item.image_type, ["Input", "Process", "Output"])
        return labels[:3]

    @staticmethod
    def _safe_ascii(text: str | None, fallback: str) -> str:
        candidate = (text or "").strip()
        if not candidate:
            return fallback
        safe = candidate.encode("ascii", "ignore").decode("ascii").strip()
        return safe or fallback

    @staticmethod
    def _chunk(chunk_type: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + chunk_type
            + data
            + struct.pack(">I", zlib.crc32(chunk_type + data) & 0xFFFFFFFF)
        )

    @staticmethod
    def _color_from_seed(seed: str) -> tuple[int, int, int]:
        digest = zlib.crc32(seed.encode("utf-8")) & 0xFFFFFFFF
        return (
            80 + digest % 120,
            80 + (digest >> 8) % 120,
            80 + (digest >> 16) % 120,
        )
