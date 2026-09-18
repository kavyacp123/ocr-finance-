import re
from typing import List, Optional, Dict, Any, Tuple
from decimal import Decimal

from app.config import settings
from app.models import DocumentResult, Region, BoundingBox
from app.finance.schemas import (
    InvoiceData,
    ExtractedField,
    ValueOrigin,
    SourceReference,
    ExtractionDetails,
    ClassificationResult,
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
from app.finance.validators import validate_invoice
from app.utils.logging import logger


class FinanceExtractor:
    """
    Finance extraction orchestrator.
    Executes a multi-strategy extraction waterfall:
    1. Same-region label-value extraction
    2. Spatial neighbor matching (right & below alignment)
    3. Standalone regex fallbacks
    4. Table line-item parsing
    5. Vendor and Buyer entity heuristics
    6. Value derivation & strict normalization
    7. Validation rule execution
    """

    def __init__(
        self,
        same_region_extractor: Optional[SameRegionExtractor] = None,
        spatial_matcher: Optional[SpatialFieldMatcher] = None,
        regex_extractor: Optional[RegexExtractor] = None,
        table_parser: Optional[TableParser] = None,
    ):
        self.same_region = same_region_extractor or SameRegionExtractor()
        self.spatial = spatial_matcher or SpatialFieldMatcher()
        self.regex = regex_extractor or RegexExtractor()
        self.table_parser = table_parser or TableParser()

    def extract_invoice(
        self,
        document_result: DocumentResult,
        classification: Optional[ClassificationResult] = None,
        organization_id: str = settings.DEFAULT_ORGANIZATION_ID,
    ) -> InvoiceData:
        doc_id = document_result.document_id
        all_regions: List[Region] = [
            r for p in document_result.pages for r in p.regions
        ]

        # ── Handle full_page OCR mode ────────────────────────────────────
        # When the pipeline routes a page to full_page mode (content coverage
        # < 80%), the detected layout regions still exist but their
        # clean_content is None/empty. The actual OCR text lives in
        # page.full_page_ocr.text. We synthesize a virtual region wrapping
        # the full-page text so all downstream extractors work unchanged.
        for page in document_result.pages:
            if (
                page.pipeline_decision
                and page.pipeline_decision.selected_mode == "full_page"
                and page.full_page_ocr
                and page.full_page_ocr.text
            ):
                # Only synthesize if the existing regions lack text
                page_regions_have_text = any(
                    r.clean_content and r.clean_content.strip()
                    for r in page.regions
                )
                if not page_regions_have_text:
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
                    logger.info(
                        f"FULL_PAGE_SYNTH: Created synthetic region for page {page.page_number} "
                        f"({len(page.full_page_ocr.text)} chars)"
                    )

        logger.info(f"FINANCE_EXTRACT_START: Processing document {doc_id} ({len(all_regions)} regions)")

        invoice = InvoiceData(
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

        # ── Step 1: Same-Region Extraction ───────────────────────────────────
        same_extracted = self.same_region.extract_from_regions(doc_id, all_regions)
        self._apply_full_page_overrides(doc_id, all_regions, same_extracted)

        # ── Step 2: Spatial Neighbor Extraction ──────────────────────────────
        # Search for any fields not yet extracted in Step 1
        already_found = list(same_extracted.keys())
        spatial_extracted = self.spatial.match_fields(
            doc_id, all_regions, exclude_fields=already_found
        )

        # ── Step 3: Standalone Regex Fallback ────────────────────────────────
        regex_extracted = self.regex.extract_fallback_identifiers(doc_id, all_regions)

        # Helper to retrieve best raw value and source
        def get_field_candidate(field_name: str) -> Tuple[Optional[str], Optional[SourceReference], str, float]:
            if field_name in same_extracted:
                val, src = same_extracted[field_name]
                return val, src, "same_region_regex", 0.95
            elif field_name in spatial_extracted:
                val, src, score = spatial_extracted[field_name]
                return val, src, "spatial_proximity", round(score, 2)
            elif field_name in regex_extracted:
                val, src = regex_extracted[field_name]
                return val, src, "regex_fallback", 0.85
            return None, None, "none", 0.0

        # ── Step 4: Populate Identification Fields ───────────────────────────
        # Invoice Number
        inv_num_raw, inv_num_src, method, conf = get_field_candidate("invoice_number")
        if inv_num_raw:
            invoice.invoice_number = ExtractedField(
                name="invoice_number",
                value=inv_num_raw.strip(),
                raw_value=inv_num_raw,
                origin=ValueOrigin.EXTRACTED,
                confidence=conf,
                source=inv_num_src,
                extraction=ExtractionDetails(method=method, confidence=conf),
            )

        # Invoice Date
        date_raw, date_src, method, conf = get_field_candidate("invoice_date")
        if date_raw:
            d_val = normalize_date(date_raw)
            invoice.invoice_date = ExtractedField(
                name="invoice_date",
                value=d_val,
                raw_value=date_raw,
                origin=ValueOrigin.EXTRACTED,
                confidence=conf if d_val else 0.4,
                source=date_src,
                extraction=ExtractionDetails(method=method, confidence=conf),
            )

        # Due Date
        due_raw, due_src, method, conf = get_field_candidate("due_date")
        if due_raw:
            due_val = normalize_date(due_raw)
            invoice.due_date = ExtractedField(
                name="due_date",
                value=due_val,
                raw_value=due_raw,
                origin=ValueOrigin.EXTRACTED,
                confidence=conf if due_val else 0.4,
                source=due_src,
                extraction=ExtractionDetails(method=method, confidence=conf),
            )

        # PO Number
        po_raw, po_src, method, conf = get_field_candidate("po_number")
        if po_raw:
            invoice.po_number = ExtractedField(
                name="po_number",
                value=po_raw.strip(),
                raw_value=po_raw,
                origin=ValueOrigin.EXTRACTED,
                confidence=conf,
                source=po_src,
                extraction=ExtractionDetails(method=method, confidence=conf),
            )

        # ── Step 5: Vendor and Buyer Details ─────────────────────────────────
        v_tax_raw, v_tax_src, method, conf = get_field_candidate("vendor_tax_id")
        if v_tax_raw:
            v_norm_tax = normalize_tax_id(v_tax_raw)
            invoice.vendor_tax_id = ExtractedField(
                name="vendor_tax_id",
                value=v_norm_tax,
                raw_value=v_tax_raw,
                origin=ValueOrigin.EXTRACTED,
                confidence=conf,
                source=v_tax_src,
                extraction=ExtractionDetails(method=method, confidence=conf),
            )

        b_tax_raw, b_tax_src, method, conf = get_field_candidate("buyer_tax_id")
        if b_tax_raw:
            b_norm_tax = normalize_tax_id(b_tax_raw)
            invoice.buyer_tax_id = ExtractedField(
                name="buyer_tax_id",
                value=b_norm_tax,
                raw_value=b_tax_raw,
                origin=ValueOrigin.EXTRACTED,
                confidence=conf,
                source=b_tax_src,
                extraction=ExtractionDetails(method=method, confidence=conf),
            )

        # Vendor Name Heuristics (prominently at top of page 1 before invoice details)
        self._extract_entity_names(doc_id, document_result, invoice)

        # ── Step 6: Populate Financial Amounts ────────────────────────────────
        # Subtotal
        sub_raw, sub_src, method, conf = get_field_candidate("subtotal")
        if sub_raw:
            sub_val = normalize_amount(sub_raw)
            invoice.subtotal = ExtractedField(
                name="subtotal",
                value=sub_val,
                raw_value=sub_raw,
                origin=ValueOrigin.EXTRACTED,
                confidence=conf if sub_val else 0.4,
                source=sub_src,
                extraction=ExtractionDetails(method=method, confidence=conf),
            )

        # Tax Amount
        tax_raw, tax_src, method, conf = get_field_candidate("tax_amount")
        if tax_raw:
            tax_val = normalize_amount(tax_raw)
            invoice.tax_amount = ExtractedField(
                name="tax_amount",
                value=tax_val,
                raw_value=tax_raw,
                origin=ValueOrigin.EXTRACTED,
                confidence=conf if tax_val else 0.4,
                source=tax_src,
                extraction=ExtractionDetails(method=method, confidence=conf),
            )

        # Discount
        disc_raw, disc_src, method, conf = get_field_candidate("discount_amount")
        if disc_raw:
            disc_val = normalize_amount(disc_raw)
            invoice.discount_amount = ExtractedField(
                name="discount_amount",
                value=disc_val,
                raw_value=disc_raw,
                origin=ValueOrigin.EXTRACTED,
                confidence=conf if disc_val else 0.4,
                source=disc_src,
                extraction=ExtractionDetails(method=method, confidence=conf),
            )

        # Shipping
        ship_raw, ship_src, method, conf = get_field_candidate("shipping_amount")
        if ship_raw:
            ship_val = normalize_amount(ship_raw)
            invoice.shipping_amount = ExtractedField(
                name="shipping_amount",
                value=ship_val,
                raw_value=ship_raw,
                origin=ValueOrigin.EXTRACTED,
                confidence=conf if ship_val else 0.4,
                source=ship_src,
                extraction=ExtractionDetails(method=method, confidence=conf),
            )

        # Total Amount
        tot_raw, tot_src, method, conf = get_field_candidate("total_amount")
        if tot_raw:
            tot_val = normalize_amount(tot_raw)
            invoice.total_amount = ExtractedField(
                name="total_amount",
                value=tot_val,
                raw_value=tot_raw,
                origin=ValueOrigin.EXTRACTED,
                confidence=conf if tot_val else 0.4,
                source=tot_src,
                extraction=ExtractionDetails(method=method, confidence=conf),
            )

        # Currency detection from text
        all_doc_text = " ".join([r.clean_content for r in all_regions if r.clean_content])
        invoice.currency = ExtractedField(
            name="currency",
            value=normalize_currency(all_doc_text),
            raw_value="",
            origin=ValueOrigin.EXTRACTED,
            confidence=0.95,
        )

        # Banking
        bank_raw, bank_src, method, conf = get_field_candidate("bank_account")
        if bank_raw:
            invoice.bank_account = ExtractedField(
                name="bank_account",
                value=re.sub(r"\D", "", bank_raw),
                raw_value=bank_raw,
                origin=ValueOrigin.EXTRACTED,
                confidence=conf,
                source=bank_src,
                extraction=ExtractionDetails(method=method, confidence=conf),
            )

        ifsc_raw, ifsc_src, method, conf = get_field_candidate("ifsc_swift")
        if ifsc_raw:
            invoice.ifsc_swift = ExtractedField(
                name="ifsc_swift",
                value=ifsc_raw.strip().upper(),
                raw_value=ifsc_raw,
                origin=ValueOrigin.EXTRACTED,
                confidence=conf,
                source=ifsc_src,
                extraction=ExtractionDetails(method=method, confidence=conf),
            )

        # ── Step 7: Line-Items Table Extraction ──────────────────────────────
        line_items = self.table_parser.parse_line_items(doc_id, all_regions)
        invoice.line_items = line_items

        # ── Step 8: Value Derivations ────────────────────────────────────────
        # If total_amount was missing, but subtotal and tax_amount were extracted:
        if (invoice.total_amount is None or invoice.total_amount.value is None) and (
            invoice.subtotal and invoice.subtotal.value is not None
        ):
            sub = invoice.subtotal.value
            tax = invoice.tax_amount.value if invoice.tax_amount and invoice.tax_amount.value is not None else Decimal("0.00")
            disc = invoice.discount_amount.value if invoice.discount_amount and invoice.discount_amount.value is not None else Decimal("0.00")
            derived_tot = (sub + tax - disc).quantize(Decimal("0.01"))

            invoice.total_amount = ExtractedField(
                name="total_amount",
                value=derived_tot,
                raw_value=str(derived_tot),
                origin=ValueOrigin.DERIVED,
                confidence=0.88,
                derived_from=["subtotal", "tax_amount"],
                extraction=ExtractionDetails(
                    method="derived_math_sum",
                    confidence=0.88,
                ),
            )
            logger.info(f"DERIVATION: Derived total_amount={derived_tot} from subtotal + tax - discount")

        # ── Step 9: Execute Non-Blocking Validations ─────────────────────────
        validate_invoice(invoice)

        logger.info(
            f"FINANCE_EXTRACT_COMPLETE: doc={doc_id} -> "
            f"invoice_no='{invoice.invoice_number.value if invoice.invoice_number else None}', "
            f"vendor='{invoice.vendor_name_raw.value if invoice.vendor_name_raw else None}', "
            f"total={invoice.total_amount.value if invoice.total_amount else None}, "
            f"line_items={len(invoice.line_items)}, valid={invoice.validation.is_valid}"
        )

        return invoice

    def _extract_entity_names(
        self, doc_id: str, document_result: DocumentResult, invoice: InvoiceData
    ) -> None:
        """
        Extracts vendor name and buyer name using top-of-page and 'Bill To' heuristics.
        """
        if not document_result.pages:
            return

        first_page = document_result.pages[0]

        # Build working regions list — handle full_page OCR mode
        working_regions = list(first_page.regions)
        if (
            first_page.pipeline_decision
            and first_page.pipeline_decision.selected_mode == "full_page"
            and first_page.full_page_ocr
            and first_page.full_page_ocr.text
        ):
            # If existing regions lack text, add synthetic full-page region
            has_text = any(r.clean_content and r.clean_content.strip() for r in working_regions)
            if not has_text:
                synthetic_fp = Region(
                    id=f"p{first_page.page_number}_fullpage",
                    page_number=first_page.page_number,
                    region_type="text",
                    reading_order=0,
                    bbox=BoundingBox(x1=0, y1=0, x2=first_page.width, y2=first_page.height),
                    clean_content=first_page.full_page_ocr.text,
                    confidence=0.80,
                    processing_status="success",
                )
                working_regions = [synthetic_fp]

        # Look for vendor name in the top 35% of page 1
        top_cutoff = (first_page.height or 1000) * 0.35

        # Title/header patterns to skip when searching for vendor name
        _title_skip = re.compile(
            r"^\s*(?:tax\s*invoice|invoice|bill\s*of\s*supply|page\s*\d|"
            r"original|duplicate|copy|proforma|delivery\s*challan)\s*$",
            re.I,
        )

        vendor_found = False

        # Strategy 1: For synthetic full-page regions, score header lines.
        for r in working_regions:
            if r.id.endswith("_fullpage") and r.clean_content:
                lines = [l.strip() for l in r.clean_content.split("\n") if l.strip()]
                invoice_heading = next(
                    (index for index, line in enumerate(lines) if re.search(r"\btax\s+invoice\b", line, re.I)),
                    min(len(lines), 12),
                )
                header_lines = lines[:invoice_heading]
                ranked = sorted(
                    (
                        (self._vendor_line_score(self._party_name_prefix(line), _title_skip), self._party_name_prefix(line))
                        for line in header_lines
                    ),
                    reverse=True,
                )
                if ranked and ranked[0][0] > 0:
                    line = ranked[0][1]
                    raw_legal, norm_name = normalize_vendor_name(line)
                    invoice.vendor_name_raw = ExtractedField(
                        name="vendor_name_raw",
                        value=raw_legal,
                        raw_value=line,
                        origin=ValueOrigin.EXTRACTED,
                        confidence=max(r.confidence or 0.75, 0.85),
                        source=self._source_for_region(doc_id, r, line),
                        extraction=ExtractionDetails(
                            method="full_page_header_name_scoring",
                            confidence=max(r.confidence or 0.75, 0.85),
                        ),
                    )
                    invoice.vendor_name_normalized = norm_name
                    vendor_found = True
                if vendor_found:
                    break

        # Strategy 2: Standard multi-region heuristic (top of page header)
        if not vendor_found:
            candidate_vendor_regions = [
                r for r in working_regions
                if r.bbox.y1 <= top_cutoff
                and r.clean_content
                and r.region_type in ("title", "header", "text", "paragraph")
                and not re.search(r"\b(tax\s*invoice|invoice|bill\s*of\s*supply|page\s*\d)\b", r.clean_content, re.I)
            ]

            if candidate_vendor_regions:
                # First prominent text region near the top is typically vendor header/logo text
                v_reg = candidate_vendor_regions[0]
                v_raw = v_reg.clean_content.split("\n")[0].strip()
                raw_legal, norm_name = normalize_vendor_name(v_raw)

                invoice.vendor_name_raw = ExtractedField(
                    name="vendor_name_raw",
                    value=raw_legal,
                    raw_value=v_raw,
                    origin=ValueOrigin.EXTRACTED,
                    confidence=v_reg.confidence or 0.85,
                    source=SourceReference(
                        document_id=doc_id,
                        page_number=v_reg.page_number,
                        region_id=v_reg.id,
                        bbox=[v_reg.bbox.x1, v_reg.bbox.y1, v_reg.bbox.x2, v_reg.bbox.y2],
                        polygon=v_reg.polygon or [],
                        original_text=v_reg.clean_content or "",
                    ),
                    extraction=ExtractionDetails(
                        method="top_of_page_header_heuristic",
                        confidence=v_reg.confidence or 0.85,
                    ),
                )
                invoice.vendor_name_normalized = norm_name

        # Look for buyer under "Bill To" or "Billed To"
        for i, reg in enumerate(working_regions):
            text = (reg.clean_content or "").strip()
            if re.search(r"\b(bill\s*to|billed\s*to|customer|buyer)\b", text, re.I):
                lines = [l.strip() for l in text.split("\n") if l.strip()]
                buyer_raw = None
                label_index = next(
                    (idx for idx, line in enumerate(lines) if re.search(r"\b(bill\s*to|billed\s*to|customer|buyer)\b", line, re.I)),
                    None,
                )
                if label_index is not None:
                    candidates = lines[label_index + 1 : label_index + 10]
                    buyer_raw = next(
                        (
                            candidate
                            for line in candidates
                            if (candidate := self._party_name_prefix(line))
                            and self._is_plausible_party_name(candidate)
                        ),
                        None,
                    )
                elif i + 1 < len(working_regions):
                    # Check next adjacent region
                    next_reg = working_regions[i + 1]
                    if next_reg.clean_content and abs(next_reg.bbox.y1 - reg.bbox.y2) <= 60:
                        buyer_raw = next_reg.clean_content.split("\n")[0].strip()

                if buyer_raw:
                    b_legal, b_norm = normalize_vendor_name(buyer_raw)
                    invoice.buyer_name_raw = ExtractedField(
                        name="buyer_name_raw",
                        value=b_legal,
                        raw_value=buyer_raw,
                        origin=ValueOrigin.EXTRACTED,
                        confidence=0.85,
                        source=SourceReference(
                            document_id=doc_id,
                            page_number=reg.page_number,
                            region_id=reg.id,
                            bbox=[reg.bbox.x1, reg.bbox.y1, reg.bbox.x2, reg.bbox.y2],
                            polygon=reg.polygon or [],
                            original_text=reg.clean_content or "",
                        ),
                        extraction=ExtractionDetails(
                            method="bill_to_proximity_heuristic",
                            confidence=0.85,
                        ),
                    )
                    invoice.buyer_name_normalized = b_norm
                break

    def _apply_full_page_overrides(
        self,
        document_id: str,
        regions: List[Region],
        extracted: Dict[str, Tuple[str, SourceReference]],
    ) -> None:
        """Prefer explicit full-page labels when OCR provides row-ordered text."""
        full_page = next((region for region in regions if region.id.endswith("_fullpage")), None)
        if not full_page or not full_page.clean_content:
            return

        text = full_page.clean_content
        source = self._source_for_region(document_id, full_page, text)

        grand_total = re.search(
            r"\bgrand\s+total\b[^0-9₹$€£]{0,15}([₹$€£]?\s*[0-9][0-9,]*(?:\.[0-9]{1,2})?)",
            text,
            re.I,
        )
        if grand_total:
            extracted["total_amount"] = (grand_total.group(1).strip(), source)

        subtotal_match = re.search(
            r"(?m)^total\b[^0-9₹$€£]{0,15}([₹$€£]?\s*[0-9][0-9,]*(?:\.[0-9]{1,2})?)",
            text,
            re.I,
        )
        if grand_total and subtotal_match:
            extracted["subtotal"] = (subtotal_match.group(1).strip(), source)

        tax_values = []
        for line in text.splitlines():
            if re.search(r"\b(?:cgst|sgst|igst)\b", line, re.I):
                amounts = re.findall(r"[0-9][0-9,]*\.\d{2}", line)
                if amounts:
                    amount = normalize_amount(amounts[-1])
                    if amount is not None:
                        tax_values.append(amount)
        if tax_values:
            extracted["tax_amount"] = (str(sum(tax_values).quantize(Decimal("0.01"))), source)

        if "invoice_date" not in extracted:
            date_match = re.search(r"\b(\d{1,2}[-/.]\d{1,2}[-/.]\d{2,4})\b", text)
            if date_match:
                extracted["invoice_date"] = (date_match.group(1), source)

        invoice_match = re.search(
            r"\binvoice\s*(?:no|number|#)\.?\s*[:#-]?\s*([A-Z0-9][A-Z0-9/_-]{0,30})\b",
            text,
            re.I,
        )
        if invoice_match and invoice_match.group(1).lower() not in {
            "bill", "date", "challan", "original", "tax"
        }:
            extracted["invoice_number"] = (invoice_match.group(1), source)

    @staticmethod
    def _source_for_region(document_id: str, region: Region, original_text: str) -> SourceReference:
        return SourceReference(
            document_id=document_id,
            page_number=region.page_number,
            region_id=region.id,
            bbox=[region.bbox.x1, region.bbox.y1, region.bbox.x2, region.bbox.y2],
            polygon=region.polygon or [],
            original_text=original_text,
        )

    @staticmethod
    def _vendor_line_score(line: str, title_skip: re.Pattern) -> float:
        cleaned = line.strip()
        lower = cleaned.lower()
        if len(cleaned) < 4 or title_skip.match(cleaned):
            return -10.0
        if re.search(r"@|\b(?:mobile|phone|email|e-mail|gstin|date|recipient)\b", lower):
            return -10.0
        if re.fullmatch(r"(?:hari\s+om|shree\s+ganesh|om|original\s+for\s+recipient)", lower):
            return -10.0
        if re.search(r"\d{4,}|[/,:]", cleaned):
            return -5.0

        words = re.findall(r"[A-Za-z]+", cleaned)
        score = min(len(words), 5)
        if len(words) >= 2:
            score += 2.0
        if cleaned.upper() == cleaned:
            score += 2.0
        if re.search(r"\b(?:enterprises|industries|limited|ltd|company|corp|services|solutions)\b", lower):
            score += 4.0
        return score

    @staticmethod
    def _is_plausible_party_name(line: str) -> bool:
        cleaned = line.strip()
        lower = cleaned.lower()
        if len(cleaned) < 4 or not re.search(r"[A-Za-z]", cleaned):
            return False
        if re.search(
            r"\b(?:invoice|date|challan|l\.?r\.?|dispatch|gstin|state\s+code|order\s+no|bill\s+to)\b",
            lower,
        ):
            return False
        if re.search(r"@|\bmobile\b|\bphone\b", lower):
            return False
        return cleaned.upper() == cleaned or bool(
            re.search(r"\b(?:enterprises|industries|limited|ltd|company|corp|services|solutions)\b", lower)
        )

    @staticmethod
    def _party_name_prefix(line: str) -> str:
        prefix = re.split(
            r"\b(?:mobile|phone|invoice\s*(?:no|number|#)|challan\s*no|date|gstin|state\s+code)\b",
            line,
            maxsplit=1,
            flags=re.I,
        )[0].strip(" :-|,")
        legal_name = re.match(
            r"^(.+?\b(?:enterprises|industries|limited|ltd\.?|company|corp\.?|services|solutions))\b",
            prefix,
            re.I,
        )
        return legal_name.group(1).strip() if legal_name else prefix
