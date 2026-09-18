import re
from typing import Dict, List, Optional, Tuple
from app.models import Region
from app.finance.schemas import SourceReference

# Patterns for extracting label and value from within the SAME region text
SAME_REGION_PATTERNS = {
    "invoice_number": [
        re.compile(r"\b(?:invoice\s*(?:no|number|num|#)|inv\s*#|bill\s*(?:no|number|#))\s*[:\-#]?\s*([A-Za-z0-9\-_/]+)", re.I),
    ],
    "invoice_date": [
        re.compile(r"\b(?:invoice\s*date|bill\s*date|dated|date)\s*[:\-]?\s*([0-9]{1,4}[/\-\.][0-9]{1,2}[/\-\.][0-9]{1,4}|[0-9]{1,2}[\s\-]+[A-Za-z]{3,9}[\s\-]+[0-9]{2,4}|[A-Za-z]{3,9}[\s\-]+[0-9]{1,2},?[\s\-]+[0-9]{2,4})", re.I),
    ],
    "due_date": [
        re.compile(r"\b(?:due\s*date|payment\s*due)\s*[:\-]?\s*([0-9]{1,4}[/\-\.][0-9]{1,2}[/\-\.][0-9]{1,4}|[0-9]{1,2}[\s\-]+[A-Za-z]{3,9}[\s\-]+[0-9]{2,4}|[A-Za-z]{3,9}[\s\-]+[0-9]{1,2},?[\s\-]+[0-9]{2,4})", re.I),
    ],
    "po_number": [
        re.compile(r"\b(?:po\s*(?:number|no|#)|p\.?o\.?\s*#?|purchase\s*order\s*(?:no|number|#))\s*[:\-#]?\s*([A-Za-z0-9\-_/]+)", re.I),
    ],
    "vendor_tax_id": [
        re.compile(r"\b(?:vendor\s*gstin|seller\s*gstin|gstin|gst\s*no\.?|gst\s*in)\s*[:\-]?\s*([0-9]{2}[A-Z]{5}[0-9]{4}[A-Z]{1}[1-9A-Z]{1}Z[0-9A-Z]{1})", re.I),
    ],
    "buyer_tax_id": [
        re.compile(r"\b(?:buyer\s*gstin|customer\s*gstin|bill\s*to\s*gstin|consignee\s*gstin)\s*[:\-]?\s*([0-9]{2}[A-Z]{5}[0-9]{4}[A-Z]{1}[1-9A-Z]{1}Z[0-9A-Z]{1})", re.I),
    ],
    "subtotal": [
        re.compile(r"\b(?:sub\s*total|subtotal|taxable\s*(?:value|amount)|net\s*amount)\s*[:\-]?\s*([₹$€£]?\s*[-+]?[0-9][0-9.,]*[0-9]|[0-9]+)", re.I),
    ],
    "tax_amount": [
        re.compile(r"\b(?:total\s*tax|tax\s*amount|gst\s*amount|igst|cgst\s*\+\s*sgst|tax)\s*[:\-]?\s*([₹$€£]?\s*[-+]?[0-9][0-9.,]*[0-9]|[0-9]+)", re.I),
    ],
    "discount_amount": [
        re.compile(r"\b(?:discount|trade\s*discount)\s*[:\-]?\s*([₹$€£]?\s*[-+]?[0-9][0-9.,]*[0-9]|[0-9]+)", re.I),
    ],
    "shipping_amount": [
        re.compile(r"\b(?:shipping|freight|handling)\s*[:\-]?\s*([₹$€£]?\s*[-+]?[0-9][0-9.,]*[0-9]|[0-9]+)", re.I),
    ],
    "total_amount": [
        re.compile(r"\b(?:grand\s*total|total\s*amount|invoice\s*total|net\s*payable|total)\s*[:\-]?\s*([₹$€£]?\s*[-+]?[0-9][0-9.,]*[0-9]|[0-9]+)", re.I),
    ],
    "amount_due": [
        re.compile(r"\b(?:amount\s*due|balance\s*due|total\s*due)\s*[:\-]?\s*([₹$€£]?\s*[-+]?[0-9][0-9.,]*[0-9]|[0-9]+)", re.I),
    ],
    "bank_account": [
        re.compile(r"\b(?:account\s*(?:number|no|#)|a/c\s*(?:no|number))\s*[:\-]?\s*([0-9]{9,18})", re.I),
    ],
    "ifsc_swift": [
        re.compile(r"\b(?:ifsc(?:\s*code)?|swift(?:\s*code)?)\s*[:\-]?\s*([A-Z]{4}0[A-Z0-9]{6}|[A-Z]{6}[A-Z0-9]{2,5})", re.I),
    ],
}


class SameRegionExtractor:
    """
    Extracts financial fields when the label and value appear together in the same OCR text block.
    Example: 'Invoice No: INV-1028' or 'Total: ₹1,18,000.00'
    """

    def extract_from_regions(
        self, document_id: str, regions: List[Region]
    ) -> Dict[str, Tuple[str, SourceReference]]:
        """
        Scans regions and returns a mapping: field_name -> (raw_value, SourceReference)
        """
        extracted: Dict[str, Tuple[str, SourceReference]] = {}

        for region in regions:
            text = (region.clean_content or "").strip()
            if not text:
                continue

            for field_name, patterns in SAME_REGION_PATTERNS.items():
                if field_name in extracted:
                    continue  # Keep first confident match in reading order

                for pat in patterns:
                    m = pat.search(text)
                    if m:
                        raw_val = m.group(1).strip()
                        source = SourceReference(
                            document_id=document_id,
                            page_number=region.page_number,
                            region_id=region.id,
                            bbox=[region.bbox.x1, region.bbox.y1, region.bbox.x2, region.bbox.y2],
                            polygon=region.polygon or [],
                            original_text=text,
                        )
                        extracted[field_name] = (raw_val, source)
                        break

        return extracted
