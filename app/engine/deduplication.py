import re
import math
from difflib import SequenceMatcher
from typing import List, Tuple, Dict, Optional, Set

from app.config import settings
from app.models import Region, DedupDecision
from app.utils.logging import logger


def normalize_for_comparison(text: str) -> str:
    if not text:
        return ""
    # Lowercase
    cleaned = text.lower()
    # Replace linebreaks with spaces
    cleaned = cleaned.replace("\n", " ")
    # Remove non-alphanumeric except spaces
    cleaned = re.sub(r"[^\w\s]", "", cleaned)
    # Collapse repeated whitespace
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned


def calculate_spatial_metrics(r1: Region, r2: Region) -> Tuple[float, float, float, float]:
    """
    Computes (intersection_area, IoU, containment_ratio, center_distance).
    containment_ratio = intersection_area / min(area1, area2)
    """
    b1, b2 = r1.bbox, r2.bbox

    # Bounding box intersection
    ix1 = max(b1.x1, b2.x1)
    iy1 = max(b1.y1, b2.y1)
    ix2 = min(b1.x2, b2.x2)
    iy2 = min(b1.y2, b2.y2)

    iw = max(0, ix2 - ix1)
    ih = max(0, iy2 - iy1)
    intersection = float(iw * ih)

    area1 = float(b1.area)
    area2 = float(b2.area)
    union = area1 + area2 - intersection
    iou = (intersection / union) if union > 0 else 0.0

    min_area = min(area1, area2)
    containment = (intersection / min_area) if min_area > 0 else 0.0

    # Center distance
    c1_x, c1_y = (b1.x1 + b1.x2) / 2.0, (b1.y1 + b1.y2) / 2.0
    c2_x, c2_y = (b2.x1 + b2.x2) / 2.0, (b2.y1 + b2.y2) / 2.0
    center_dist = math.hypot(c1_x - c2_x, c1_y - c2_y)

    return intersection, iou, containment, center_dist


class DeduplicationAnalyzer:
    """
    Page-local presentation deduplication analyzer.
    Determines which regions should be suppressed during Markdown rendering.
    Does NOT mutate canonical Region objects. Returns DedupDecision objects.
    """

    def __init__(
        self,
        enabled: bool = settings.DEDUP_ENABLED,
        text_similarity_threshold: float = settings.DEDUP_TEXT_SIMILARITY,
        geometric_containment_threshold: float = settings.DEDUP_GEOMETRIC_CONTAINMENT,
        iou_threshold: float = settings.DEDUP_IOU_THRESHOLD,
        proximity_px: float = settings.DEDUP_PROXIMITY_PX,
    ):
        self.enabled = enabled
        self.text_similarity_threshold = text_similarity_threshold
        self.geometric_containment_threshold = geometric_containment_threshold
        self.iou_threshold = iou_threshold
        self.proximity_px = proximity_px

    def analyze_page_deduplication(self, regions: List[Region]) -> List[DedupDecision]:
        """
        Analyzes page-local regions and returns a list of DedupDecision objects.
        """
        if not self.enabled or not regions:
            return [DedupDecision(region_id=r.id) for r in regions]

        decisions: Dict[str, DedupDecision] = {
            r.id: DedupDecision(region_id=r.id) for r in regions
        }

        # Filter regions that produced clean content
        valid_regions = [
            r for r in regions
            if r.clean_content and r.processing_status == "success"
        ]

        # Pair-wise comparison
        for i in range(len(valid_regions)):
            r1 = valid_regions[i]
            d1 = decisions[r1.id]
            if d1.render_suppressed:
                continue  # Already suppressed

            text1_norm = normalize_for_comparison(r1.clean_content)
            if not text1_norm:
                continue

            for j in range(i + 1, len(valid_regions)):
                r2 = valid_regions[j]
                d2 = decisions[r2.id]
                if d2.render_suppressed:
                    continue

                text2_norm = normalize_for_comparison(r2.clean_content)
                if not text2_norm:
                    continue

                # Calculate spatial metrics
                _, iou, containment, center_dist = calculate_spatial_metrics(r1, r2)
                has_spatial_proximity = (
                    containment >= self.geometric_containment_threshold
                    or iou >= self.iou_threshold
                    or center_dist <= self.proximity_px
                )

                # ── Rule 1: Table Safety Rule ────────────────────────────────
                if r1.region_type == "table" or r2.region_type == "table":
                    # Only suppress tables if they almost perfectly overlap
                    if iou >= 0.85 and text1_norm == text2_norm:
                        # Suppress r2
                        d2.render_suppressed = True
                        d2.duplicate_of = r1.id
                        d2.reason = "table_exact_duplicate_high_iou"
                        logger.debug(f"[DEDUP] Suppressing table {r2.id} (duplicate of {r1.id})")
                    continue

                # ── Rule 2: Exact Duplicate with Spatial Evidence ────────────
                if text1_norm == text2_norm and has_spatial_proximity:
                    # Prefer higher confidence or earlier reading order
                    conf1 = r1.confidence or 0.5
                    conf2 = r2.confidence or 0.5
                    if conf2 > conf1:
                        d1.render_suppressed = True
                        d1.duplicate_of = r2.id
                        d1.reason = "exact_duplicate_with_spatial_proximity"
                        logger.debug(f"[DEDUP] Suppressing {r1.id} (exact duplicate of {r2.id})")
                        break
                    else:
                        d2.render_suppressed = True
                        d2.duplicate_of = r1.id
                        d2.reason = "exact_duplicate_with_spatial_proximity"
                        logger.debug(f"[DEDUP] Suppressing {r2.id} (exact duplicate of {r1.id})")
                    continue

                # ── Rule 3: Substring Containment with Overlap ───────────────
                if containment >= self.geometric_containment_threshold:
                    if text2_norm in text1_norm and len(text2_norm) < len(text1_norm):
                        d2.render_suppressed = True
                        d2.duplicate_of = r1.id
                        d2.reason = "overlapping_substring"
                        logger.debug(f"[DEDUP] Suppressing {r2.id} (substring inside {r1.id})")
                        continue
                    elif text1_norm in text2_norm and len(text1_norm) < len(text2_norm):
                        d1.render_suppressed = True
                        d1.duplicate_of = r2.id
                        d1.reason = "overlapping_substring"
                        logger.debug(f"[DEDUP] Suppressing {r1.id} (substring inside {r2.id})")
                        break

                # ── Rule 4: Fuzzy Near-Duplicate with Overlap ────────────────
                if has_spatial_proximity:
                    similarity = SequenceMatcher(None, text1_norm, text2_norm).ratio()
                    if similarity >= self.text_similarity_threshold:
                        conf1 = r1.confidence or 0.5
                        conf2 = r2.confidence or 0.5
                        if conf2 > conf1:
                            d1.render_suppressed = True
                            d1.duplicate_of = r2.id
                            d1.reason = f"fuzzy_text_overlap (sim={similarity:.2f})"
                            logger.debug(f"[DEDUP] Suppressing {r1.id} (fuzzy duplicate of {r2.id})")
                            break
                        else:
                            d2.render_suppressed = True
                            d2.duplicate_of = r1.id
                            d2.reason = f"fuzzy_text_overlap (sim={similarity:.2f})"
                            logger.debug(f"[DEDUP] Suppressing {r2.id} (fuzzy duplicate of {r1.id})")

        return [decisions[r.id] for r in regions]
