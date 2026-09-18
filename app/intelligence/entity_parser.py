"""
Entity Parser
==============

WHY:   User questions reference vendors ("AWS"), invoices ("INV-902"),
       POs ("PO-100"), payments ("PAY-55") by name or number.
       These must be resolved against the database BEFORE tools execute.
       We never trust raw user strings — we resolve to canonical IDs.

WHERE: Called by the QueryPlanner right after date parsing.

WHAT IT RECEIVES:  Raw question text + DB session + organization_id.

WHAT IT OUTPUTS:   Dict of resolved entities:
                     vendor_id, vendor_name, invoice_number, po_number,
                     payment_reference, document_type

HOW:   Regex extraction → DB lookup.
       Vendor resolution uses fuzzy matching against VendorModel/VendorAliasModel.
"""

import re
from typing import Optional, Dict, Any, List
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.database.models import VendorModel, VendorAliasModel, InvoiceModel, PurchaseOrderModel
from app.finance.normalizer import normalize_vendor_name
from app.utils.logging import logger


class EntityParser:
    """
    Extracts and resolves named entities from user questions.

    Resolution priority:
      1. Invoice/PO/Payment references via regex (exact DB lookup)
      2. Vendor name via fuzzy matching against canonical names + aliases
    """

    # ── Regex patterns ────────────────────────────────────────────────────

    # Invoice numbers: INV-123, INV123, Invoice #123, invoice-2026-001
    _INVOICE_PATTERN = re.compile(
        r'\b(?:INV|invoice)[- #]*(\d[\w-]*)\b', re.IGNORECASE
    )

    # PO numbers: PO-100, PO100, PO #100, purchase order 100
    _PO_PATTERN = re.compile(
        r'\b(?:PO|purchase\s*order)[- #]*(\d[\w-]*)\b', re.IGNORECASE
    )

    # Payment references: PAY-55, payment #55, PMT-100
    _PAYMENT_PATTERN = re.compile(
        r'\b(?:PAY|PMT|payment)[- #]*(\d[\w-]*)\b', re.IGNORECASE
    )

    def parse(
        self,
        text: str,
        db: Session,
        organization_id: str,
    ) -> Dict[str, Any]:
        """
        Extract and resolve all entities from a question.

        Returns dict with resolved keys:
          - vendor_id, vendor_name
          - invoice_number, invoice_id
          - po_number, po_id
          - payment_reference
        """
        entities: Dict[str, Any] = {}

        # ── Extract structured references ─────────────────────────────
        inv_match = self._INVOICE_PATTERN.search(text)
        if inv_match:
            inv_num = inv_match.group(0)  # Keep the full match for lookup
            # Normalize: try with and without prefix
            raw_num = inv_match.group(1)
            resolved = self._resolve_invoice(db, organization_id, inv_num, raw_num)
            entities.update(resolved)

        po_match = self._PO_PATTERN.search(text)
        if po_match:
            po_num = po_match.group(0)
            raw_num = po_match.group(1)
            resolved = self._resolve_po(db, organization_id, po_num, raw_num)
            entities.update(resolved)

        pay_match = self._PAYMENT_PATTERN.search(text)
        if pay_match:
            entities["payment_reference"] = pay_match.group(0).strip()

        # ── Extract vendor name ───────────────────────────────────────
        vendor_info = self._extract_vendor(text, db, organization_id)
        if vendor_info:
            entities.update(vendor_info)

        # ── Extract document type filter ──────────────────────────────
        doc_type = self._extract_document_type(text)
        if doc_type:
            entities["document_type"] = doc_type

        logger.debug(f"ENTITY_PARSER: Extracted entities: {entities}")
        return entities

    # ── Vendor extraction ─────────────────────────────────────────────────

    def _extract_vendor(
        self,
        text: str,
        db: Session,
        organization_id: str,
    ) -> Optional[Dict[str, Any]]:
        """
        Try to find a vendor name in the question and resolve it.

        Strategy:
          1. Check every known vendor canonical_name and alias against the text.
          2. Pick the longest match (to prefer "Amazon Web Services" over "Amazon").
        """
        lower_text = text.lower()

        # Load all vendors + aliases for this org
        vendors = db.query(VendorModel).filter(
            VendorModel.organization_id == organization_id
        ).all()

        best_match: Optional[VendorModel] = None
        best_match_len = 0

        for vendor in vendors:
            # Check canonical name
            if vendor.normalized_name and vendor.normalized_name in lower_text:
                if len(vendor.normalized_name) > best_match_len:
                    best_match = vendor
                    best_match_len = len(vendor.normalized_name)

            # Check canonical_name (case-insensitive)
            if vendor.canonical_name and vendor.canonical_name.lower() in lower_text:
                if len(vendor.canonical_name) > best_match_len:
                    best_match = vendor
                    best_match_len = len(vendor.canonical_name)

            # Check aliases
            for alias in vendor.aliases:
                alias_lower = alias.alias_name.lower() if alias.alias_name else ""
                if alias_lower and alias_lower in lower_text:
                    if len(alias_lower) > best_match_len:
                        best_match = vendor
                        best_match_len = len(alias_lower)
                norm_alias = alias.normalized_alias or ""
                if norm_alias and norm_alias in lower_text:
                    if len(norm_alias) > best_match_len:
                        best_match = vendor
                        best_match_len = len(norm_alias)

        if best_match:
            logger.info(f"ENTITY_PARSER: Resolved vendor '{best_match.canonical_name}' (id={best_match.id})")
            return {
                "vendor_id": best_match.id,
                "vendor_name": best_match.canonical_name,
                "vendor_normalized": best_match.normalized_name,
            }

        # Fallback: try to find capitalized proper nouns that might be vendor names
        # (These won't be resolved to IDs — the planner can note ambiguity)
        vendor_candidates = self._extract_possible_vendor_names(text)
        if vendor_candidates:
            return {"vendor_name_unresolved": vendor_candidates[0]}

        return None

    def _extract_possible_vendor_names(self, text: str) -> List[str]:
        """
        Heuristic: find capitalized words that might be vendor names.
        Used as a fallback when no DB match is found.
        """
        # Common words that are NOT vendor names
        stop_words = {
            "how", "much", "did", "we", "spend", "with", "show", "all",
            "find", "which", "what", "why", "where", "when", "the", "and",
            "for", "from", "invoices", "invoice", "payments", "payment",
            "vendors", "vendor", "last", "this", "next", "quarter", "month",
            "year", "week", "total", "compare", "between", "increase",
            "decrease", "had", "have", "has", "were", "was", "are",
            "connected", "related", "linked", "associated", "about",
            "mentioning", "containing", "unusual", "spending", "cost",
            "amount", "unpaid", "overdue", "mismatch", "mismatches",
            "anomalous", "highest", "lowest", "evidence", "supporting",
            "investigate", "august", "july", "june", "january", "february",
            "march", "april", "may", "september", "october", "november",
            "december", "monday", "tuesday", "gpu", "compute",
        }
        words = re.findall(r'\b([A-Z][A-Za-z0-9]+(?:\s+[A-Z][A-Za-z0-9]+)*)\b', text)
        candidates = [w for w in words if w.lower() not in stop_words and len(w) > 2]
        return candidates

    # ── Invoice resolution ────────────────────────────────────────────────

    def _resolve_invoice(
        self,
        db: Session,
        organization_id: str,
        full_match: str,
        raw_num: str,
    ) -> Dict[str, Any]:
        """Try to find the invoice by number in the database."""
        result: Dict[str, Any] = {"invoice_number": full_match.strip()}

        # Try exact match on invoice_number field
        for candidate in [full_match.strip(), f"INV-{raw_num}", f"INV{raw_num}", raw_num]:
            inv = db.query(InvoiceModel).filter(
                InvoiceModel.organization_id == organization_id,
                func.lower(InvoiceModel.invoice_number) == candidate.lower(),
            ).first()
            if inv:
                result["invoice_id"] = inv.id
                result["invoice_number"] = inv.invoice_number
                logger.info(f"ENTITY_PARSER: Resolved invoice '{inv.invoice_number}' (id={inv.id})")
                break

        return result

    # ── PO resolution ─────────────────────────────────────────────────────

    def _resolve_po(
        self,
        db: Session,
        organization_id: str,
        full_match: str,
        raw_num: str,
    ) -> Dict[str, Any]:
        """Try to find the PO by number in the database."""
        result: Dict[str, Any] = {"po_number": full_match.strip()}

        for candidate in [full_match.strip(), f"PO-{raw_num}", f"PO{raw_num}", raw_num]:
            po = db.query(PurchaseOrderModel).filter(
                PurchaseOrderModel.organization_id == organization_id,
                func.lower(PurchaseOrderModel.po_number) == candidate.lower(),
            ).first()
            if po:
                result["po_id"] = po.id
                result["po_number"] = po.po_number
                logger.info(f"ENTITY_PARSER: Resolved PO '{po.po_number}' (id={po.id})")
                break

        return result

    # ── Document type extraction ──────────────────────────────────────────

    @staticmethod
    def _extract_document_type(text: str) -> Optional[str]:
        """Extract a document type filter from the question."""
        lower = text.lower()
        if "invoice" in lower or "invoices" in lower:
            return "invoice"
        if "purchase order" in lower or "po " in lower or " po" in lower:
            return "purchase_order"
        if "payment" in lower or "payments" in lower:
            return "payment"
        if "receipt" in lower or "receipts" in lower:
            return "receipt"
        if "credit note" in lower or "credit notes" in lower:
            return "credit_note"
        return None
