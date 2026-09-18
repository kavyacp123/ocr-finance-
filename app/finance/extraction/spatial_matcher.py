import re
import math
from typing import Dict, List, Optional, Tuple, Any
from decimal import Decimal
from app.models import Region
from app.finance.schemas import SourceReference
from app.finance.normalizer import normalize_amount, normalize_date, normalize_tax_id
from app.utils.logging import logger

ANCHOR_LABELS: Dict[str, List[re.Pattern]] = {
    "invoice_number": [
        re.compile(r"^(invoice\s*(?:no|number|num|#)|inv\s*#|bill\s*(?:no|number|#))\s*[:\-]?$", re.I),
    ],
    "invoice_date": [
        re.compile(r"^(invoice\s*date|bill\s*date|dated|date)\s*[:\-]?$", re.I),
    ],
    "due_date": [
        re.compile(r"^(due\s*date|payment\s*due|pay\s*by)\s*[:\-]?$", re.I),
    ],
    "po_number": [
        re.compile(r"^(po\s*(?:number|no|#)|p\.?\s*o\.?\s*(?:number|no|#)|purchase\s*order\s*(?:no|number|#))\s*[:\-]?$", re.I),
    ],
    "vendor_tax_id": [
        re.compile(r"^(gstin|gst\s*no\.?|vendor\s*gstin|tin|tax\s*id)\s*[:\-]?$", re.I),
    ],
    "subtotal": [
        re.compile(r"^(sub\s*total|subtotal|taxable\s*(?:value|amount)|net\s*amount)\s*[:\-]?$", re.I),
    ],
    "tax_amount": [
        re.compile(r"^(total\s*tax|tax\s*amount|gst\s*amount|igst|cgst\s*\+\s*sgst)\s*[:\-]?$", re.I),
    ],
    "discount_amount": [
        re.compile(r"^(discount|trade\s*discount)\s*[:\-]?$", re.I),
    ],
    "shipping_amount": [
        re.compile(r"^(shipping|freight|handling)\s*[:\-]?$", re.I),
    ],
    "total_amount": [
        re.compile(r"^(grand\s*total|total\s*amount|invoice\s*total|net\s*payable|total)\s*[:\-]?$", re.I),
    ],
    "amount_due": [
        re.compile(r"^(amount\s*due|balance\s*due|total\s*due)\s*[:\-]?$", re.I),
    ],
    "bank_account": [
        re.compile(r"^(account\s*(?:number|no|#)|a/c\s*(?:no|number))\s*[:\-]?$", re.I),
    ],
    "ifsc_swift": [
        re.compile(r"^(ifsc(?:\s*code)?|swift(?:\s*code)?)\s*[:\-]?$", re.I),
    ],
}


class CandidateScorer:
    """
    Scores candidate value regions relative to an anchor label region.
    """

    @staticmethod
    def evaluate_datatype(field_name: str, candidate_text: str) -> float:
        text = candidate_text.strip()
        if not text:
            return 0.0

        if field_name in ("subtotal", "tax_amount", "discount_amount", "shipping_amount", "total_amount", "amount_due"):
            dec = normalize_amount(text)
            return 1.0 if dec is not None else 0.1

        elif field_name in ("invoice_date", "due_date"):
            d = normalize_date(text)
            return 1.0 if d is not None else 0.1

        elif field_name == "vendor_tax_id":
            tax_id = normalize_tax_id(text)
            if tax_id and len(tax_id) == 15:
                return 1.0
            return 0.4 if tax_id and len(tax_id) >= 10 else 0.1

        elif field_name in ("invoice_number", "po_number"):
            # Avoid multiline sentences or long paragraphs as invoice number
            if len(text) <= 35 and re.match(r"^[A-Za-z0-9\-_/]+$", text):
                return 1.0
            elif len(text) <= 50 and "\n" not in text:
                return 0.7
            return 0.2

        elif field_name == "bank_account":
            digits_only = re.sub(r"\D", "", text)
            if 9 <= len(digits_only) <= 18:
                return 1.0
            return 0.2

        return 0.6


class SpatialFieldMatcher:
    """
    Finds anchor label regions and evaluates right-neighbor and below-neighbor candidates
    using geometric alignment, distance penalties, and data type validity.
    """

    def __init__(self, max_horizontal_dist: float = 350.0, max_vertical_dist: float = 80.0):
        self.max_h_dist = max_horizontal_dist
        self.max_v_dist = max_vertical_dist
        self.scorer = CandidateScorer()

    def match_fields(
        self, document_id: str, regions: List[Region], exclude_fields: Optional[List[str]] = None
    ) -> Dict[str, Tuple[str, SourceReference, float]]:
        """
        Returns: field_name -> (raw_value, SourceReference, match_score)
        """
        exclude = set(exclude_fields or [])
        matched: Dict[str, Tuple[str, SourceReference, float]] = {}

        # 1. Identify Anchor Regions
        for anchor_candidate in regions:
            anchor_text = (anchor_candidate.clean_content or "").strip()
            if not anchor_text or len(anchor_text) > 40:
                continue

            for field_name, patterns in ANCHOR_LABELS.items():
                if field_name in exclude or field_name in matched:
                    continue

                is_anchor = any(pat.search(anchor_text) for pat in patterns)
                if not is_anchor:
                    continue

                # 2. Find best neighbor candidate for this anchor
                best_cand, best_score = self._find_best_candidate(anchor_candidate, regions, field_name)
                if best_cand and best_score >= 0.55:
                    source = SourceReference(
                        document_id=document_id,
                        page_number=best_cand.page_number,
                        region_id=best_cand.id,
                        bbox=[best_cand.bbox.x1, best_cand.bbox.y1, best_cand.bbox.x2, best_cand.bbox.y2],
                        polygon=best_cand.polygon or [],
                        original_text=best_cand.clean_content or "",
                    )
                    matched[field_name] = (best_cand.clean_content.strip(), source, best_score)
                    logger.debug(f"[SPATIAL] Matched '{field_name}' to region {best_cand.id} (score={best_score:.2f})")

        return matched

    def _find_best_candidate(
        self, anchor: Region, all_regions: List[Region], field_name: str
    ) -> Tuple[Optional[Region], float]:
        ab = anchor.bbox
        anchor_cy = (ab.y1 + ab.y2) / 2.0
        anchor_cx = (ab.x1 + ab.x2) / 2.0

        best_region: Optional[Region] = None
        best_score = 0.0

        for cand in all_regions:
            if cand.id == anchor.id or cand.page_number != anchor.page_number:
                continue
            cand_text = (cand.clean_content or "").strip()
            if not cand_text:
                continue

            cb = cand.bbox
            cand_cy = (cb.y1 + cb.y2) / 2.0
            cand_cx = (cb.x1 + cb.x2) / 2.0

            # ── Check Case A: Right Neighbor ──────────────────────────────
            is_right = (
                cb.x1 >= ab.x1
                and abs(cand_cy - anchor_cy) <= 30.0
                and (cb.x1 - ab.x2) <= self.max_h_dist
                and (cb.x1 - ab.x2) >= -10.0  # slight overlap allowed
            )

            # ── Check Case B: Below Neighbor ─────────────────────────────
            is_below = (
                cb.y1 >= ab.y1
                and (cb.y1 - ab.y2) <= self.max_v_dist
                and (cb.y1 - ab.y2) >= -5.0
                and abs(cb.x1 - ab.x1) <= 70.0
            )

            if not (is_right or is_below):
                continue

            # Calculate spatial alignment score
            alignment_score = 1.0 if is_right else 0.85

            # Distance penalty
            dist = math.hypot(cb.x1 - ab.x2, cand_cy - anchor_cy) if is_right else math.hypot(cb.x1 - ab.x1, cb.y1 - ab.y2)
            max_d = self.max_h_dist if is_right else self.max_v_dist
            distance_score = max(0.0, 1.0 - (dist / max_d))

            # Datatype validity score
            datatype_score = self.scorer.evaluate_datatype(field_name, cand_text)

            # Confidence of OCR
            ocr_conf = cand.confidence or 0.80

            # Composite Score: weighted combination
            composite = (
                0.40 * datatype_score
                + 0.25 * alignment_score
                + 0.20 * distance_score
                + 0.15 * ocr_conf
            )

            if composite > best_score:
                best_score = composite
                best_region = cand

        return best_region, best_score
