import re
from typing import List, Dict, Any, Tuple, Optional
from app.models import DocumentResult, PageResult, Region
from app.finance.schemas import DocumentType, ClassificationResult
from app.utils.logging import logger

# Anchor definitions: (regex pattern, weight)
TITLE_ANCHORS: Dict[DocumentType, List[Tuple[re.Pattern, int]]] = {
    DocumentType.INVOICE: [
        (re.compile(r"\b(tax\s*invoice|commercial\s*invoice|bill\s*of\s*supply|sales\s*invoice)\b", re.I), 6),
        (re.compile(r"\b(invoice|bill)\b", re.I), 4),
    ],
    DocumentType.PURCHASE_ORDER: [
        (re.compile(r"\b(purchase\s*order|purchase\s*requisition)\b", re.I), 6),
        (re.compile(r"\b(p\.?o\.?\s*order|po\s*#)\b", re.I), 4),
    ],
    DocumentType.CREDIT_NOTE: [
        (re.compile(r"\b(credit\s*note|credit\s*memo)\b", re.I), 7),
    ],
    DocumentType.RECEIPT: [
        (re.compile(r"\b(receipt|cash\s*receipt|payment\s*receipt|acknowledgement\s*receipt)\b", re.I), 6),
    ],
    DocumentType.PAYMENT_ADVICE: [
        (re.compile(r"\b(payment\s*advice|remittance\s*advice|direct\s*deposit\s*advice)\b", re.I), 7),
    ],
    DocumentType.CONTRACT: [
        (re.compile(r"\b(service\s*agreement|master\s*services\s*agreement|contract\s*agreement|non-disclosure\s*agreement)\b", re.I), 7),
    ],
    DocumentType.BANK_STATEMENT: [
        (re.compile(r"\b(bank\s*statement|account\s*statement|statement\s*of\s*account)\b", re.I), 7),
    ],
    DocumentType.EXPENSE_REPORT: [
        (re.compile(r"\b(expense\s*report|expense\s*claim|travel\s*expense)\b", re.I), 7),
    ],
}

DOMAIN_FIELDS: Dict[DocumentType, List[Tuple[re.Pattern, int]]] = {
    DocumentType.INVOICE: [
        (re.compile(r"\b(invoice\s*(no|number|num|#))\b", re.I), 3),
        (re.compile(r"\b(invoice\s*date|date\s*of\s*invoice)\b", re.I), 2),
        (re.compile(r"\b(bill\s*to|billed\s*to)\b", re.I), 2),
        (re.compile(r"\b(total\s*due|amount\s*due|balance\s*due)\b", re.I), 2),
        (re.compile(r"\b(gstin|gst\s*no|pan\s*no)\b", re.I), 2),
        (re.compile(r"\b(due\s*date|payment\s*terms)\b", re.I), 1),
    ],
    DocumentType.PURCHASE_ORDER: [
        (re.compile(r"\b(po\s*(number|no|#)|purchase\s*order\s*no)\b", re.I), 4),
        (re.compile(r"\b(ship\s*to|vendor\s*code)\b", re.I), 2),
        (re.compile(r"\b(requisition(er)?|buyer|delivery\s*date)\b", re.I), 2),
        (re.compile(r"\b(order\s*date)\b", re.I), 1),
    ],
    DocumentType.CREDIT_NOTE: [
        (re.compile(r"\b(original\s*invoice(\s*no)?)\b", re.I), 3),
        (re.compile(r"\b(reason\s*for\s*credit|adjustment)\b", re.I), 3),
        (re.compile(r"\b(credit\s*amount)\b", re.I), 2),
    ],
    DocumentType.RECEIPT: [
        (re.compile(r"\b(received\s*from|paid\s*by)\b", re.I), 3),
        (re.compile(r"\b(payment\s*method|cash|cheque|credit\s*card)\b", re.I), 2),
        (re.compile(r"\b(amount\s*received)\b", re.I), 3),
    ],
    DocumentType.PAYMENT_ADVICE: [
        (re.compile(r"\b(payment\s*reference|remittance\s*reference)\b", re.I), 3),
        (re.compile(r"\b(beneficiary|utr\s*(no|number)|value\s*date)\b", re.I), 3),
    ],
    DocumentType.CONTRACT: [
        (re.compile(r"\b(party\s*of\s*the\s*first\s*part|terms\s*and\s*conditions|indemnity|governing\s*law)\b", re.I), 3),
    ],
    DocumentType.BANK_STATEMENT: [
        (re.compile(r"\b(opening\s*balance|closing\s*balance|withdrawal|deposit|cheque\s*no)\b", re.I), 3),
    ],
    DocumentType.EXPENSE_REPORT: [
        (re.compile(r"\b(employee\s*(name|id)|expense\s*category|mileage|per\s*diem)\b", re.I), 3),
    ],
}

# Negative signals: if a candidate document type has counter-evidence, apply penalties
NEGATIVE_SIGNALS: Dict[DocumentType, List[Tuple[re.Pattern, int, str]]] = {
    DocumentType.INVOICE: [
        (re.compile(r"\b(purchase\s*order)\b", re.I), -4, "Found 'Purchase Order' title anchor"),
        (re.compile(r"\b(credit\s*note)\b", re.I), -5, "Found 'Credit Note' title anchor"),
        (re.compile(r"\b(remittance\s*advice|payment\s*advice)\b", re.I), -5, "Found 'Payment Advice' title anchor"),
    ],
    DocumentType.PURCHASE_ORDER: [
        (re.compile(r"\b(tax\s*invoice|bill\s*of\s*supply)\b", re.I), -6, "Found 'Tax Invoice' title anchor"),
        (re.compile(r"\b(credit\s*note)\b", re.I), -5, "Found 'Credit Note' title anchor"),
    ],
    DocumentType.RECEIPT: [
        (re.compile(r"\b(purchase\s*order)\b", re.I), -4, "Found 'Purchase Order' title anchor"),
    ],
}


class DocumentClassifier:
    """
    Financial document classifier using weighted title anchors, domain fields,
    layout positioning (top 30% of page 1), table presence, and negative signals.
    """

    def classify_document(self, document_result: DocumentResult) -> ClassificationResult:
        """
        Classifies an OCR DocumentResult into a DocumentType.
        """
        if not document_result.pages:
            return ClassificationResult(
                document_type=DocumentType.UNKNOWN,
                confidence=0.0,
                reason="Document contains no pages"
            )

        # Extract regions from first page (for title anchors) and all pages (for full context)
        first_page = document_result.pages[0]
        first_page_height = first_page.height or 1
        top_cutoff = first_page_height * 0.35  # top 35% of page 1

        top_regions: List[Region] = [
            r for r in first_page.regions
            if r.bbox.y1 <= top_cutoff and r.clean_content
        ]
        top_text = " ".join([r.clean_content for r in top_regions])

        # Full document text
        all_text = " ".join([
            r.clean_content for p in document_result.pages for r in p.regions if r.clean_content
        ])

        # Fallback to document markdown if regions were sparse
        if len(all_text.strip()) == 0 and document_result.markdown:
            all_text = document_result.markdown
            top_text = "\n".join(document_result.markdown.split("\n")[:10])

        scores: Dict[DocumentType, int] = {dt: 0 for dt in DocumentType if dt != DocumentType.UNKNOWN}
        matched_kw: Dict[DocumentType, List[str]] = {dt: [] for dt in scores}
        negative_sig: Dict[DocumentType, List[str]] = {dt: [] for dt in scores}
        signals: Dict[DocumentType, Dict[str, Any]] = {dt: {} for dt in scores}

        # 1. Evaluate Title Anchors (heavily weighted if in top of page 1)
        for dt, anchors in TITLE_ANCHORS.items():
            for pat, weight in anchors:
                m_top = pat.search(top_text)
                if m_top:
                    scores[dt] += weight * 2  # Double weight for top-of-page prominence
                    matched_kw[dt].append(f"top_title:{m_top.group(0)}")
                elif pat.search(all_text):
                    scores[dt] += weight
                    matched_kw[dt].append(f"body_title:{pat.pattern}")

        # 2. Evaluate Domain-Specific Fields
        for dt, fields in DOMAIN_FIELDS.items():
            for pat, weight in fields:
                m = pat.search(all_text)
                if m:
                    scores[dt] += weight
                    matched_kw[dt].append(f"field:{m.group(0)}")

        # 3. Evaluate Negative Signals
        for dt, neg_list in NEGATIVE_SIGNALS.items():
            for pat, penalty, reason in neg_list:
                # If negative anchor found in top text of page 1
                if pat.search(top_text):
                    scores[dt] += penalty
                    negative_sig[dt].append(reason)

        # 4. Evaluate Layout Signals: table presence boosts INVOICE and PURCHASE_ORDER
        has_table = any(r.region_type == "table" for p in document_result.pages for r in p.regions)
        if has_table:
            scores[DocumentType.INVOICE] += 2
            scores[DocumentType.PURCHASE_ORDER] += 2
            signals[DocumentType.INVOICE]["has_table"] = True
            signals[DocumentType.PURCHASE_ORDER]["has_table"] = True

        # Find best candidate
        best_type = DocumentType.UNKNOWN
        best_score = 0

        for dt, score in scores.items():
            signals[dt]["score"] = score
            if score > best_score:
                best_score = score
                best_type = dt

        # Minimum score threshold to consider classification valid
        if best_score < 4:
            return ClassificationResult(
                document_type=DocumentType.UNKNOWN,
                confidence=round(max(0.1, best_score / 20.0), 2),
                matched_keywords=[],
                negative_signals=[],
                signals={"candidate_scores": {dt.value: s for dt, s in scores.items()}},
                reason="Insufficient matching signals for supported financial document types",
            )

        # Calculate confidence: normalized sigmoid-like curve
        # Score of 10+ is ~0.95 confidence; score of 4 is ~0.60
        confidence = min(0.99, max(0.50, round(1.0 / (1.0 + (2.71828 ** (-(best_score - 5) / 2.5))), 2)))

        matched = matched_kw[best_type]
        negatives = negative_sig[best_type]
        reason_str = f"Classified as {best_type.value} based on {len(matched)} matching signals (score={best_score})"
        if negatives:
            reason_str += f" with {len(negatives)} negative signal(s) evaluated"

        result = ClassificationResult(
            document_type=best_type,
            confidence=confidence,
            matched_keywords=matched,
            negative_signals=negatives,
            signals={"scores": {dt.value: s for dt, s in scores.items()}},
            reason=reason_str,
        )

        logger.info(f"CLASSIFIER: {best_type.value} (score={best_score}, conf={confidence:.2f}) -> {reason_str}")
        return result
