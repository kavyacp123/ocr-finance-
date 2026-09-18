import re
from typing import List, Optional, Dict, Any, Tuple
from decimal import Decimal
from datetime import date

from app.config import settings
from app.models import DocumentResult, Region, BoundingBox
from app.finance.schemas import (
    PurchaseOrderData,
    PurchaseOrderLineItem,
    ExtractedField,
    ValueOrigin,
    SourceReference,
    ExtractionDetails,
    ClassificationResult,
    ValidationResult,
    ValidationIssue,
)
from app.finance.extraction.same_region_extractor import SameRegionExtractor
from app.finance.extraction.spatial_matcher import SpatialFieldMatcher
from app.finance.extraction.regex_extractor import RegexExtractor
from app.finance.extraction.table_parser import TableParser
from app.finance.normalizer import (
    normalize_amount,
    normalize_date,
    normalize_currency,
    normalize_vendor_name,
    normalize_tax_id,
)
from app.utils.logging import logger

# PO-specific same-region regex patterns
PO_SAME_REGION_PATTERNS = {
    "po_number": [
        re.compile(r"\b(?:purchase\s*order\s*(?:no|number|num|#)|po\s*(?:no|number|num|#)|p\.?o\.?\s*#?)\s*[:\-#]?\s*([A-Za-z0-9\-_/]+)", re.I),
    ],
    "po_date": [
        re.compile(r"\b(?:po\s*date|order\s*date|purchase\s*order\s*date|date)\s*[:\-]?\s*([0-9]{1,4}[/\-\.][0-9]{1,2}[/\-\.][0-9]{1,4}|[0-9]{1,2}[\s\-]+[A-Za-z]{3,9}[\s\-]+[0-9]{2,4}|[A-Za-z]{3,9}[\s\-]+[0-9]{1,2},?[\s\-]+[0-9]{2,4})", re.I),
    ],
    "delivery_date": [
        re.compile(r"\b(?:delivery\s*date|expected\s*(?:delivery|date)|ship\s*date|due\s*date)\s*[:\-]?\s*([0-9]{1,4}[/\-\.][0-9]{1,2}[/\-\.][0-9]{1,4}|[0-9]{1,2}[\s\-]+[A-Za-z]{3,9}[\s\-]+[0-9]{2,4}|[A-Za-z]{3,9}[\s\-]+[0-9]{1,2},?[\s\-]+[0-9]{2,4})", re.I),
    ],
    "vendor_tax_id": [
        re.compile(r"\b(?:vendor\s*gstin|seller\s*gstin|supplier\s*gstin|gstin|gst\s*no\.?)\s*[:\-]?\s*([0-9]{2}[A-Z]{5}[0-9]{4}[A-Z]{1}[1-9A-Z]{1}Z[0-9A-Z]{1})", re.I),
    ],
    "subtotal": [
        re.compile(r"\b(?:sub\s*total|subtotal|taxable\s*(?:value|amount)|net\s*amount)\s*[:\-]?\s*([₹$€£]?\s*[-+]?[0-9][0-9.,]*[0-9]|[0-9]+)", re.I),
    ],
    "tax_amount": [
        re.compile(r"\b(?:total\s*tax|tax\s*amount|gst\s*amount|igst|cgst\s*\+\s*sgst|tax)\s*[:\-]?\s*([₹$€£]?\s*[-+]?[0-9][0-9.,]*[0-9]|[0-9]+)", re.I),
    ],
    "total_amount": [
        re.compile(r"\b(?:total\s*(?:amount|order|po)|grand\s*total|order\s*total|net\s*payable|total)\s*[:\-]?\s*([₹$€£]?\s*[-+]?[0-9][0-9.,]*[0-9]|[0-9]+)", re.I),
    ],
    "payment_terms": [
        re.compile(r"\b(?:payment\s*terms|terms)\s*[:\-]?\s*(net\s*\d+|immediate|due\s*on\s*receipt|advance)", re.I),
    ],
}


class PurchaseOrderExtractor:
    """
    Purchase Order extraction orchestrator.
    Extracts structured PO numbers, dates, vendor/buyer identities, line items, and totals.
    """

    def __init__(
        self,
        table_parser: Optional[TableParser] = None,
    ):
        self.table_parser = table_parser or TableParser()

    def extract_purchase_order(
        self,
        document_result: DocumentResult,
        classification: Optional[ClassificationResult] = None,
        organization_id: str = settings.DEFAULT_ORGANIZATION_ID,
    ) -> PurchaseOrderData:
        doc_id = document_result.document_id
        all_regions: List[Region] = [
            r for p in document_result.pages for r in p.regions
        ]

        # Handle full_page OCR mode
        for page in document_result.pages:
            if (
                page.pipeline_decision
                and page.pipeline_decision.selected_mode == "full_page"
                and page.full_page_ocr
                and page.full_page_ocr.text
            ):
                has_text = any(r.clean_content and r.clean_content.strip() for r in page.regions)
                if not has_text:
                    synthetic = Region(
                        id=f"p{page.page_number}_fullpage",
                        page_number=page.page_number,
                        region_type="text",
                        reading_order=0,
                        bbox=BoundingBox(x1=0, y1=0, x2=page.width, y2=page.height),
                        clean_content=page.full_page_ocr.text,
                        confidence=0.80,
                        processing_status="success",
                    )
                    all_regions.append(synthetic)

        logger.info(f"PO_EXTRACT_START: Processing document {doc_id} ({len(all_regions)} regions)")

        po = PurchaseOrderData(
            document_id=doc_id,
            organization_id=organization_id,
            classification=classification,
            currency=ExtractedField(
                name="currency",
                value="INR",
                raw_value="INR",
                origin=ValueOrigin.EXTRACTED,
                confidence=1.0,
            ),
        )

        # ── Step 1: Scan Regions with PO Patterns ────────────────────────────
        extracted_fields: Dict[str, Tuple[str, SourceReference]] = {}
        for region in all_regions:
            text = (region.clean_content or "").strip()
            if not text:
                continue
            for field_name, patterns in PO_SAME_REGION_PATTERNS.items():
                if field_name in extracted_fields:
                    continue
                for pat in patterns:
                    m = pat.search(text)
                    if m:
                        raw_val = m.group(1).strip()
                        src = SourceReference(
                            document_id=doc_id,
                            page_number=region.page_number,
                            region_id=region.id,
                            bbox=[region.bbox.x1, region.bbox.y1, region.bbox.x2, region.bbox.y2],
                            polygon=region.polygon or [],
                            original_text=text,
                        )
                        extracted_fields[field_name] = (raw_val, src)
                        break

        # ── Step 2: Populate Core Fields ─────────────────────────────────────
        # PO Number
        if "po_number" in extracted_fields:
            val, src = extracted_fields["po_number"]
            po.po_number = ExtractedField(
                name="po_number",
                value=val.strip(),
                raw_value=val,
                origin=ValueOrigin.EXTRACTED,
                confidence=0.95,
                source=src,
                extraction=ExtractionDetails(method="same_region_regex", confidence=0.95),
            )

        # PO Date
        if "po_date" in extracted_fields:
            val, src = extracted_fields["po_date"]
            d_val = normalize_date(val)
            po.po_date = ExtractedField(
                name="po_date",
                value=d_val,
                raw_value=val,
                origin=ValueOrigin.EXTRACTED,
                confidence=0.95 if d_val else 0.5,
                source=src,
                extraction=ExtractionDetails(method="same_region_regex", confidence=0.95),
            )

        # Delivery Date
        if "delivery_date" in extracted_fields:
            val, src = extracted_fields["delivery_date"]
            d_val = normalize_date(val)
            po.expected_delivery_date = ExtractedField(
                name="expected_delivery_date",
                value=d_val,
                raw_value=val,
                origin=ValueOrigin.EXTRACTED,
                confidence=0.90 if d_val else 0.5,
                source=src,
                extraction=ExtractionDetails(method="same_region_regex", confidence=0.90),
            )

        # Vendor Tax ID
        if "vendor_tax_id" in extracted_fields:
            val, src = extracted_fields["vendor_tax_id"]
            po.vendor_tax_id = ExtractedField(
                name="vendor_tax_id",
                value=normalize_tax_id(val),
                raw_value=val,
                origin=ValueOrigin.EXTRACTED,
                confidence=0.95,
                source=src,
                extraction=ExtractionDetails(method="same_region_regex", confidence=0.95),
            )

        # Payment Terms
        if "payment_terms" in extracted_fields:
            val, src = extracted_fields["payment_terms"]
            po.payment_terms = ExtractedField(
                name="payment_terms",
                value=val.strip(),
                raw_value=val,
                origin=ValueOrigin.EXTRACTED,
                confidence=0.85,
                source=src,
                extraction=ExtractionDetails(method="same_region_regex", confidence=0.85),
            )

        # ── Step 3: Extract Entities (Vendor & Buyer) ─────────────────────────
        self._extract_po_entities(doc_id, document_result, all_regions, po)

        # ── Step 4: Populate Financial Totals ─────────────────────────────────
        if "subtotal" in extracted_fields:
            val, src = extracted_fields["subtotal"]
            sub_val = normalize_amount(val)
            po.subtotal = ExtractedField(
                name="subtotal",
                value=sub_val,
                raw_value=val,
                origin=ValueOrigin.EXTRACTED,
                confidence=0.90 if sub_val else 0.4,
                source=src,
                extraction=ExtractionDetails(method="same_region_regex", confidence=0.90),
            )

        if "tax_amount" in extracted_fields:
            val, src = extracted_fields["tax_amount"]
            tax_val = normalize_amount(val)
            po.tax_amount = ExtractedField(
                name="tax_amount",
                value=tax_val,
                raw_value=val,
                origin=ValueOrigin.EXTRACTED,
                confidence=0.90 if tax_val else 0.4,
                source=src,
                extraction=ExtractionDetails(method="same_region_regex", confidence=0.90),
            )

        if "total_amount" in extracted_fields:
            val, src = extracted_fields["total_amount"]
            tot_val = normalize_amount(val)
            po.total_amount = ExtractedField(
                name="total_amount",
                value=tot_val,
                raw_value=val,
                origin=ValueOrigin.EXTRACTED,
                confidence=0.90 if tot_val else 0.4,
                source=src,
                extraction=ExtractionDetails(method="same_region_regex", confidence=0.90),
            )

        # Currency
        all_text = " ".join([r.clean_content for r in all_regions if r.clean_content])
        po.currency = ExtractedField(
            name="currency",
            value=normalize_currency(all_text),
            raw_value="",
            origin=ValueOrigin.EXTRACTED,
            confidence=0.95,
        )

        # ── Step 5: Extract Line Items ────────────────────────────────────────
        raw_items = self.table_parser.parse_line_items(doc_id, all_regions)
        po.line_items = [
            PurchaseOrderLineItem(
                line_number=itm.line_number,
                description=itm.description,
                product_code=itm.product_code,
                quantity=itm.quantity,
                unit=itm.unit,
                unit_price=itm.unit_price,
                tax_rate=itm.tax_rate,
                tax_amount=itm.tax_amount,
                total=itm.total,
                confidence=itm.confidence,
                source=itm.source,
            )
            for itm in raw_items
        ]

        # ── Step 6: Derive Total if missing ───────────────────────────────────
        if (po.total_amount is None or po.total_amount.value is None) and (
            po.subtotal and po.subtotal.value is not None
        ):
            sub = po.subtotal.value
            tax = po.tax_amount.value if po.tax_amount and po.tax_amount.value is not None else Decimal("0.00")
            derived_tot = (sub + tax).quantize(Decimal("0.01"))
            po.total_amount = ExtractedField(
                name="total_amount",
                value=derived_tot,
                raw_value=str(derived_tot),
                origin=ValueOrigin.DERIVED,
                confidence=0.88,
                derived_from=["subtotal", "tax_amount"],
                extraction=ExtractionDetails(method="derived_math_sum", confidence=0.88),
            )

        # ── Step 7: PO Validation ─────────────────────────────────────────────
        self._validate_po(po)

        logger.info(
            f"PO_EXTRACT_COMPLETE: doc={doc_id} -> po_no='{po.po_number.value if po.po_number else None}', "
            f"vendor='{po.vendor_name_raw.value if po.vendor_name_raw else None}', "
            f"total={po.total_amount.value if po.total_amount else None}, items={len(po.line_items)}"
        )

        return po

    def _extract_po_entities(
        self,
        doc_id: str,
        document_result: DocumentResult,
        regions: List[Region],
        po: PurchaseOrderData,
    ) -> None:
        """
        Identifies Vendor (supplier) and Buyer on the Purchase Order.
        In a PO, the Buyer is typically the company logo/header issuing the PO,
        while the Vendor is under 'Vendor:', 'To:', or 'Supplier:'.
        """
        # Search for 'Vendor:' or 'Supplier:' or 'To:' label
        for reg in regions:
            text = (reg.clean_content or "").strip()
            if not text:
                continue

            # Look for vendor label
            v_match = re.search(r"\b(?:vendor|supplier|issue\s*to|to)\s*[:\-]?\s*([A-Za-z0-9\s,.&'-]+)", text, re.I)
            if v_match and not po.vendor_name_raw:
                lines = [l.strip() for l in text.split("\n") if l.strip()]
                cand = None
                for i, l in enumerate(lines):
                    if re.match(r"^(vendor|supplier|issue\s*to|to)\s*[:\-]?", l, re.I):
                        # Extract rest of line or next line
                        rest = re.sub(r"^(vendor|supplier|issue\s*to|to)\s*[:\-]?\s*", "", l, flags=re.I).strip()
                        if rest:
                            cand = rest
                        elif i + 1 < len(lines):
                            cand = lines[i + 1]
                        break

                if cand and len(cand) >= 3:
                    raw_legal, norm_name = normalize_vendor_name(cand)
                    po.vendor_name_raw = ExtractedField(
                        name="vendor_name_raw",
                        value=raw_legal,
                        raw_value=cand,
                        origin=ValueOrigin.EXTRACTED,
                        confidence=0.85,
                        source=SourceReference(
                            document_id=doc_id,
                            page_number=reg.page_number,
                            region_id=reg.id,
                            bbox=[reg.bbox.x1, reg.bbox.y1, reg.bbox.x2, reg.bbox.y2],
                            polygon=reg.polygon or [],
                            original_text=cand,
                        ),
                        extraction=ExtractionDetails(method="po_vendor_label_heuristic", confidence=0.85),
                    )
                    po.vendor_name_normalized = norm_name

            # Look for buyer header (first non-title line near top)
            if not po.buyer_name_raw and reg.bbox.y1 <= 200 and reg.region_type in ("title", "header", "text"):
                cand_line = text.split("\n")[0].strip()
                if not re.search(r"\b(purchase\s*order|po\s*#|date)\b", cand_line, re.I) and len(cand_line) >= 3:
                    b_legal, b_norm = normalize_vendor_name(cand_line)
                    po.buyer_name_raw = ExtractedField(
                        name="buyer_name_raw",
                        value=b_legal,
                        raw_value=cand_line,
                        origin=ValueOrigin.EXTRACTED,
                        confidence=0.80,
                        source=SourceReference(
                            document_id=doc_id,
                            page_number=reg.page_number,
                            region_id=reg.id,
                            bbox=[reg.bbox.x1, reg.bbox.y1, reg.bbox.x2, reg.bbox.y2],
                            polygon=reg.polygon or [],
                            original_text=cand_line,
                        ),
                        extraction=ExtractionDetails(method="po_buyer_header_heuristic", confidence=0.80),
                    )
                    po.buyer_name_normalized = b_norm

    def _validate_po(self, po: PurchaseOrderData) -> None:
        """Non-blocking validation for Purchase Orders."""
        tolerance = settings.finance_validation_tolerance_decimal

        # Check math balance
        if po.subtotal and po.subtotal.value is not None and po.total_amount and po.total_amount.value is not None:
            sub = po.subtotal.value
            tax = po.tax_amount.value if po.tax_amount and po.tax_amount.value is not None else Decimal("0.00")
            expected = sub + tax
            diff = abs(expected - po.total_amount.value)
            if diff > tolerance:
                po.validation.is_valid = False
                po.validation.issues.append(
                    ValidationIssue(
                        issue_type="MATH_TOTAL_MISMATCH",
                        severity="high",
                        message=f"PO total ({po.total_amount.value}) does not match subtotal + tax ({expected}). Difference: {diff}",
                        expected=str(expected),
                        actual=str(po.total_amount.value),
                        field_name="total_amount",
                    )
                )

        # Check line items sum
        if po.line_items and po.total_amount and po.total_amount.value is not None:
            item_sum = sum((itm.total for itm in po.line_items if itm.total is not None), Decimal("0.00"))
            if item_sum > Decimal("0.00"):
                diff = abs(item_sum - po.total_amount.value)
                if diff > tolerance and (po.subtotal is None or abs(item_sum - po.subtotal.value) > tolerance):
                    po.validation.issues.append(
                        ValidationIssue(
                            issue_type="LINE_ITEMS_SUM_MISMATCH",
                            severity="medium",
                            message=f"Sum of {len(po.line_items)} PO line items ({item_sum}) does not match total amount ({po.total_amount.value}).",
                            expected=str(po.total_amount.value),
                            actual=str(item_sum),
                            field_name="line_items",
                        )
                    )

        # Required fields check
        if not po.po_number or not po.po_number.value:
            po.validation.is_valid = False
            po.validation.issues.append(
                ValidationIssue(
                    issue_type="MISSING_REQUIRED_FIELD",
                    severity="high",
                    message="Essential PO field 'po_number' could not be extracted.",
                    field_name="po_number",
                )
            )
