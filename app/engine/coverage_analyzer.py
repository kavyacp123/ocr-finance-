import numpy as np
import cv2
from PIL import Image
from typing import List, Tuple, Optional
from app.config import settings, PipelineMode
from app.models import Region, PipelineDecision
from app.utils.logging import logger


class CoverageAnalyzer:
    """
    Computes geometric layout coverage and content-aware coverage to make
    deterministic routing decisions (hybrid vs full_page).
    """

    def __init__(
        self,
        min_layout_coverage: float = settings.AUTO_MIN_LAYOUT_COVERAGE,
        min_content_coverage: float = settings.AUTO_MIN_CONTENT_COVERAGE,
        weak_content_coverage: float = settings.AUTO_WEAK_CONTENT_COVERAGE,
        large_region_ratio: float = settings.AUTO_LARGE_REGION_RATIO,
        large_region_min_content: float = settings.AUTO_LARGE_REGION_MIN_CONTENT_COVERAGE,
        dilation_px: int = settings.AUTO_LAYOUT_DILATION_PX,
        enable_content_analysis: bool = settings.AUTO_ENABLE_CONTENT_ANALYSIS,
    ):
        self.min_layout_coverage = min_layout_coverage
        self.min_content_coverage = min_content_coverage
        self.weak_content_coverage = weak_content_coverage
        self.large_region_ratio = large_region_ratio
        self.large_region_min_content = large_region_min_content
        self.dilation_px = dilation_px
        self.enable_content_analysis = enable_content_analysis

    def analyze_page(
        self,
        page_num: int,
        image: Image.Image,
        regions: List[Region],
        requested_mode: PipelineMode = settings.OCR_PIPELINE_MODE,
    ) -> PipelineDecision:
        width, height = image.size
        page_area = float(width * height)

        if page_area <= 0:
            return PipelineDecision(
                requested_mode=requested_mode,
                selected_mode="full_page",
                reason="invalid_page_dimensions",
                region_count=len(regions),
                layout_coverage_ratio=0.0,
                content_coverage_ratio=0.0,
                largest_region_ratio=0.0,
                fallback_used=True,
            )

        # ── 1. Calculate Geometric Layout Coverage ────────────────────────────
        layout_mask, layout_cov, largest_ratio = self.calculate_layout_coverage(
            width, height, regions
        )

        # ── 2. Calculate Content-Aware Coverage ──────────────────────────────
        content_cov: Optional[float] = None
        if self.enable_content_analysis:
            content_cov = self.calculate_content_coverage(image, layout_mask)

        # ── 3. Make Routing Decision ──────────────────────────────────────────
        selected_mode: PipelineMode = "hybrid"
        reason = "sufficient_layout_coverage"
        fallback_used = False

        if requested_mode == "full_page":
            selected_mode = "full_page"
            reason = "forced_full_page_mode"
        elif requested_mode == "hybrid":
            selected_mode = "hybrid"
            reason = "forced_hybrid_mode"
        elif len(regions) == 0:
            selected_mode = "full_page"
            reason = "no_layout_regions"
            fallback_used = True
        elif (
            self.enable_content_analysis
            and content_cov is not None
            and content_cov < self.min_content_coverage
        ):
            selected_mode = "full_page"
            reason = "significant_uncovered_content"
        elif (
            largest_ratio >= self.large_region_ratio
            and content_cov is not None
            and content_cov < self.large_region_min_content
        ):
            selected_mode = "full_page"
            reason = "large_region_plus_uncovered_content"
        elif layout_cov < self.min_layout_coverage and (
            content_cov is None or content_cov < self.weak_content_coverage
        ):
            selected_mode = "full_page"
            reason = "low_layout_coverage"

        decision = PipelineDecision(
            requested_mode=requested_mode,
            selected_mode=selected_mode,
            reason=reason,
            region_count=len(regions),
            layout_coverage_ratio=round(layout_cov, 4),
            content_coverage_ratio=round(content_cov, 4) if content_cov is not None else None,
            largest_region_ratio=round(largest_ratio, 4),
            fallback_used=fallback_used,
        )

        content_str = f"{content_cov:.1%}" if content_cov is not None else "N/A"
        logger.info(
            f"[AUTO] Page {page_num} → mode={selected_mode.upper()} "
            f"(regions={len(regions)}, layout_cov={layout_cov:.1%}, "
            f"largest_region={largest_ratio:.1%}, "
            f"content_cov={content_str}, "
            f"reason='{reason}')"
        )

        return decision

    def calculate_layout_coverage(
        self, width: int, height: int, regions: List[Region]
    ) -> Tuple[np.ndarray, float, float]:
        """
        Calculates the raster union coverage of all layout regions
        and the largest individual region coverage ratio.
        """
        mask = np.zeros((height, width), dtype=np.uint8)
        largest_area = 0.0

        for r in regions:
            area = float(r.bbox.area)
            if area > largest_area:
                largest_area = area

            if r.polygon and len(r.polygon) >= 3:
                pts = np.array(r.polygon, dtype=np.int32)
                cv2.fillPoly(mask, [pts], 1)
            else:
                b = r.bbox
                cv2.rectangle(mask, (b.x1, b.y1), (b.x2, b.y2), 1, -1)

        total_pixels = float(width * height)
        layout_union_pixels = float(mask.sum())
        layout_coverage_ratio = layout_union_pixels / total_pixels
        largest_region_ratio = largest_area / total_pixels

        return mask, layout_coverage_ratio, largest_region_ratio

    def calculate_content_coverage(
        self, image: Image.Image, layout_mask: np.ndarray
    ) -> float:
        """
        Determines visually meaningful content pixels (text/ink) outside
        detected regions using thresholding, connected components, and
        layout mask dilation.
        """
        gray = np.array(image.convert("L"))
        h, w = gray.shape

        # 1. Threshold: Ink pixels are dark (< 220)
        _, binary = cv2.threshold(gray, 220, 255, cv2.THRESH_BINARY_INV)

        # 2. Suppress margin edge scan artifacts (10px border around page)
        border = 10
        if h > 2 * border and w > 2 * border:
            binary[:border, :] = 0
            binary[-border:, :] = 0
            binary[:, :border] = 0
            binary[:, -border:] = 0

        # 3. Connected components noise filtering: drop tiny dots (< 15 px area)
        num_labels, labels, stats, _ = cv2.connectedComponentsWithStats(binary, connectivity=8)
        content_mask = np.zeros((h, w), dtype=np.uint8)
        for i in range(1, num_labels):
            area = stats[i, cv2.CC_STAT_AREA]
            if area >= 15:
                content_mask[labels == i] = 1

        total_content_pixels = float(content_mask.sum())
        if total_content_pixels <= 0:
            return 1.0  # Empty or blank document page is fully covered by definition

        # 4. Dilate layout mask to allow anti-aliasing / slight bounding box boundary tolerance
        if self.dilation_px > 0:
            kernel_size = 2 * self.dilation_px + 1
            kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (kernel_size, kernel_size))
            dilated_layout_mask = cv2.dilate(layout_mask, kernel)
        else:
            dilated_layout_mask = layout_mask

        # 5. Compute content coverage ratio
        covered_pixels = float((content_mask & dilated_layout_mask).sum())
        return covered_pixels / total_content_pixels
