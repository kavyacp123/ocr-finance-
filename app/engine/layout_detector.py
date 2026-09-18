import os
import numpy as np
from pathlib import Path
from PIL import Image
from typing import List, Dict, Any

from app.config import settings
from app.models import Region, BoundingBox
from app.utils.logging import logger

# ── Env config for paddlex ────────────────────────────────────────────────────
# Redirect model-cache and lock files into the project workspace to avoid
# macOS sandbox PermissionError on ~/. paths.
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_PADDLEX_HOME = str(_PROJECT_ROOT / ".paddlex")
os.environ.setdefault("PADDLE_PDX_CACHE_HOME", _PADDLEX_HOME)
# Skip the slow connectivity pre-check each time (model is already downloaded).
os.environ.setdefault("PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK", "True")

# ── Label normalisation table ─────────────────────────────────────────────────
LABEL_MAP: Dict[str, str] = {
    # PP-DocLayoutV3 native labels (verified from live inference output)
    "title": "title",
    "text": "text",
    "figure": "figure",
    "figure_caption": "caption",
    "table": "table",
    "table_caption": "caption",
    "table_footnote": "text",
    "header": "header",
    "footer": "footer",
    "page_number": "page_number",
    "abandon": "other",
    "seal": "other",
    "chart": "chart",
    "chart_title": "caption",
    # Legacy / alternative label names
    "paragraph": "paragraph",
    "doc_title": "title",
    "section_header": "title",
    "figure_title": "caption",
    "image": "figure",
    "picture": "figure",
    "equation": "equation",
    "formula": "equation",
    "math": "equation",
    "list": "list",
    "item": "list",
    "caption": "caption",
    "page-header": "header",
    "page-footer": "footer",
    "reference": "text",
    "footnote": "text",
}


def _normalize_label(native_label: str) -> str:
    cleaned = str(native_label).strip().lower().replace("-", "_")
    return LABEL_MAP.get(cleaned, "other")


class LayoutDetector:
    """
    Thin adapter around PP-DocLayoutV3 (ONNX variant via paddlex).

    The predictor is created once on first use (lazy init).  Every call to
    ``detect()`` runs real model inference and returns Region objects whose
    bboxes, polygons, labels, and confidences all come directly from the model.

    There is NO synthetic / percentage-based fallback.  If the model returns
    zero boxes the method returns an empty list so the caller can decide what
    to do (e.g. full-page OCR fallback in pipeline.py).
    """

    def __init__(
        self,
        model_name: str = settings.LAYOUT_MODEL,
        device: str = settings.LAYOUT_DEVICE,
    ):
        self.model_name = model_name
        self.device = device
        self._predictor = None
        self._initialized = False

    # ── Initialisation ────────────────────────────────────────────────────────

    def initialize(self) -> None:
        if self._initialized:
            return

        logger.info(
            f"LAYOUT_INIT: Loading '{self.model_name}' via paddlex "
            f"(engine=onnxruntime, device={self.device}, "
            f"cache={os.environ['PADDLE_PDX_CACHE_HOME']})"
        )
        try:
            from paddlex.inference.models import create_predictor  # type: ignore

            # Use the ONNX variant so we don't need the paddlepaddle package.
            # paddlex auto-selects PP-DocLayoutV3_onnx when engine='onnxruntime'.
            self._predictor = create_predictor(
                model_name=self.model_name,
                device="cpu",  # onnxruntime on macOS ARM64 – CPU only
                engine="onnxruntime",
            )
            logger.info(
                f"LAYOUT_READY: {self.model_name} predictor loaded "
                f"({type(self._predictor).__name__})"
            )
        except Exception as exc:
            logger.error(
                f"LAYOUT_INIT_FAILED: Could not load '{self.model_name}': {exc}. "
                "Layout detection will return empty regions (no fake boxes)."
            )
            self._predictor = None

        self._initialized = True

    # ── Public API ────────────────────────────────────────────────────────────

    def detect(self, page_num: int, image: Image.Image) -> List[Region]:
        """
        Run PP-DocLayoutV3 on *image* and return model-predicted Region objects.

        Returns an empty list if the model is unavailable or detects nothing
        – there is intentionally NO synthetic/geometric fallback.
        """
        if not self._initialized:
            self.initialize()

        width, height = image.size
        logger.info(
            f"LAYOUT_DETECT: page {page_num} ({width}x{height})"
        )

        if self._predictor is None:
            logger.warning(
                f"LAYOUT_DETECT: predictor unavailable for page {page_num}, "
                "returning empty region list."
            )
            return []

        # ── Run inference ─────────────────────────────────────────────────────
        img_np = np.array(image.convert("RGB"))
        try:
            raw_results: List[Dict[str, Any]] = list(self._predictor(img_np))
        except Exception as exc:
            logger.error(
                f"LAYOUT_DETECT: inference failed on page {page_num}: {exc}"
            )
            return []

        if not raw_results:
            logger.warning(f"LAYOUT_DETECT: model returned no results for page {page_num}")
            return []

        # PP-DocLayoutV3 returns a list with one dict per input image.
        # dict keys: 'input_img', 'boxes', 'input_path', 'page_index'
        result_dict = raw_results[0]
        boxes: List[Dict[str, Any]] = result_dict.get("boxes", [])

        logger.info(
            f"LAYOUT_DETECT: model returned {len(boxes)} raw box(es) for page {page_num}"
        )

        # ── Parse boxes into Region objects ───────────────────────────────────
        regions: List[Region] = []
        for idx, box in enumerate(boxes):
            native_label: str = box.get("label", "text")
            score: float = float(box.get("score", 1.0))
            coordinate = box.get("coordinate")  # [x1, y1, x2, y2]
            poly_pts = box.get("polygon_points")  # np.ndarray shape (N, 2)
            order = box.get("order")  # int or None

            if coordinate is None:
                logger.debug(f"LAYOUT_DETECT: box {idx} has no coordinate – skipping")
                continue

            x1, y1, x2, y2 = [int(v) for v in coordinate[:4]]

            # Clamp to page boundaries
            x1 = max(0, min(width, x1))
            y1 = max(0, min(height, y1))
            x2 = max(0, min(width, x2))
            y2 = max(0, min(height, y2))

            if x2 <= x1 or y2 <= y1:
                logger.debug(f"LAYOUT_DETECT: box {idx} degenerate after clamping – skipping")
                continue

            # Convert polygon numpy array → list[list[int]]
            polygon: List[List[int]] = []
            if poly_pts is not None:
                try:
                    polygon = [[int(pt[0]), int(pt[1])] for pt in poly_pts]
                except Exception:
                    polygon = []

            reading_order: int = int(order) if order is not None else (idx + 1)

            region = Region(
                id=f"p{page_num}_r{idx + 1}",
                page_number=page_num,
                region_type=_normalize_label(native_label),
                native_label=native_label,
                confidence=round(score, 4),
                reading_order=reading_order,
                bbox=BoundingBox(x1=x1, y1=y1, x2=x2, y2=y2),
                polygon=polygon,
                processing_status="pending",
            )
            regions.append(region)

        # ── Sort by reading order ─────────────────────────────────────────────
        regions = self._sort_reading_order(regions)

        logger.info(
            f"LAYOUT_COMPLETE: page {page_num} → {len(regions)} region(s) "
            f"(all from model, none synthetic)"
        )
        return regions

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _sort_reading_order(self, regions: List[Region]) -> List[Region]:
        """
        Sort regions into natural reading order.

        Prefer the model's own ``reading_order`` values if they are unique and
        non-zero; otherwise fall back to geometric top→bottom / left→right
        sorting (handles two-column layouts via 40-pixel band quantisation).
        """
        if not regions:
            return regions

        orders = [r.reading_order for r in regions]
        if len(set(orders)) == len(regions) and min(orders) >= 1:
            sorted_regions = sorted(regions, key=lambda r: r.reading_order)
        else:
            sorted_regions = sorted(
                regions, key=lambda r: (r.bbox.y1 // 40, r.bbox.x1)
            )

        for i, r in enumerate(sorted_regions):
            r.reading_order = i + 1

        return sorted_regions
