import re
from typing import Dict, List, Optional, Tuple
from app.models import Region
from app.finance.schemas import SourceReference

GSTIN_PATTERN = re.compile(r"\b([0-9]{2}[A-Z]{5}[0-9]{4}[A-Z]{1}[1-9A-Z]{1}Z[0-9A-Z]{1})\b")
PAN_PATTERN = re.compile(r"\b([A-Z]{5}[0-9]{4}[A-Z]{1})\b")
EMAIL_PATTERN = re.compile(r"\b([A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,})\b")
PHONE_PATTERN = re.compile(r"\b((?:\+91[\-\s]?)?[6-9]\d{9})\b")
IFSC_PATTERN = re.compile(r"\b([A-Z]{4}0[A-Z0-9]{6})\b")


class RegexExtractor:
    """
    Fallback regex extractor for standalone identifiers across document regions.
    """

    def extract_fallback_identifiers(
        self, document_id: str, regions: List[Region]
    ) -> Dict[str, Tuple[str, SourceReference]]:
        results: Dict[str, Tuple[str, SourceReference]] = {}

        gstin_matches: List[Tuple[str, Region]] = []
        email_matches: List[Tuple[str, Region]] = []
        phone_matches: List[Tuple[str, Region]] = []
        ifsc_matches: List[Tuple[str, Region]] = []

        for region in regions:
            text = (region.clean_content or "").strip()
            if not text:
                continue

            # Check GSTIN
            m_gst = GSTIN_PATTERN.search(text)
            if m_gst:
                gstin_matches.append((m_gst.group(1), region))

            # Check Email
            m_mail = EMAIL_PATTERN.search(text)
            if m_mail:
                email_matches.append((m_mail.group(1), region))

            # Check Phone
            m_phone = PHONE_PATTERN.search(text)
            if m_phone:
                phone_matches.append((m_phone.group(1), region))

            # Check IFSC
            m_ifsc = IFSC_PATTERN.search(text)
            if m_ifsc:
                ifsc_matches.append((m_ifsc.group(1), region))

        # First GSTIN found in document is typically the vendor/seller tax ID
        if gstin_matches:
            val, reg = gstin_matches[0]
            results["vendor_tax_id"] = (
                val,
                SourceReference(
                    document_id=document_id,
                    page_number=reg.page_number,
                    region_id=reg.id,
                    bbox=[reg.bbox.x1, reg.bbox.y1, reg.bbox.x2, reg.bbox.y2],
                    polygon=reg.polygon or [],
                    original_text=reg.clean_content or "",
                ),
            )
            # Second distinct GSTIN (if present) is typically the buyer tax ID
            if len(gstin_matches) > 1 and gstin_matches[1][0] != val:
                b_val, b_reg = gstin_matches[1]
                results["buyer_tax_id"] = (
                    b_val,
                    SourceReference(
                        document_id=document_id,
                        page_number=b_reg.page_number,
                        region_id=b_reg.id,
                        bbox=[b_reg.bbox.x1, b_reg.bbox.y1, b_reg.bbox.x2, b_reg.bbox.y2],
                        polygon=b_reg.polygon or [],
                        original_text=b_reg.clean_content or "",
                    ),
                )

        if ifsc_matches:
            val, reg = ifsc_matches[0]
            results["ifsc_swift"] = (
                val,
                SourceReference(
                    document_id=document_id,
                    page_number=reg.page_number,
                    region_id=reg.id,
                    bbox=[reg.bbox.x1, reg.bbox.y1, reg.bbox.x2, reg.bbox.y2],
                    polygon=reg.polygon or [],
                    original_text=reg.clean_content or "",
                ),
            )

        return results
