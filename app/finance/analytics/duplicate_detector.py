import json
from typing import Optional, List
from sqlalchemy.orm import Session

from app.database.models import (
    InvoiceModel,
    PaymentModel,
    DuplicateCandidateModel,
    RuleViolationModel,
)
from app.utils.logging import logger


class DuplicateDetector:
    """
    Deterministic Duplicate Detection (MVP).
    Detects:
      - Exact duplicate invoice: same organization_id + same invoice_number + same vendor_id (or vendor_name_raw).
      - Exact duplicate payment: same organization_id + same payment_reference.
    """

    def check_invoice(self, invoice: InvoiceModel, db: Session) -> Optional[DuplicateCandidateModel]:
        if not invoice.invoice_number:
            return None

        org_id = invoice.organization_id
        inv_id = invoice.id

        # Query existing invoices with identical invoice_number
        query = (
            db.query(InvoiceModel)
            .filter(
                InvoiceModel.organization_id == org_id,
                InvoiceModel.invoice_number == invoice.invoice_number,
                InvoiceModel.id != inv_id,
            )
        )

        candidates = query.all()
        for cand in candidates:
            # Check vendor match (vendor_id or vendor_name_raw)
            vendor_match = False
            if invoice.vendor_id and cand.vendor_id and invoice.vendor_id == cand.vendor_id:
                vendor_match = True
            elif invoice.vendor_name_raw and cand.vendor_name_raw:
                if invoice.vendor_name_raw.strip().lower() == cand.vendor_name_raw.strip().lower():
                    vendor_match = True

            if vendor_match:
                dup = DuplicateCandidateModel(
                    organization_id=org_id,
                    entity_type="INVOICE",
                    primary_entity_id=inv_id,
                    duplicate_of_entity_id=cand.id,
                    match_type="EXACT",
                    similarity_score=1.0,
                    details_json=json.dumps({
                        "invoice_number": invoice.invoice_number,
                        "vendor_id": invoice.vendor_id,
                        "matched_fields": ["invoice_number", "vendor"],
                    }),
                    status="OPEN",
                )
                db.add(dup)

                # Add a RuleViolationModel for duplicate detection
                v = RuleViolationModel(
                    organization_id=org_id,
                    rule_id="DUPLICATE_DETECTED",
                    rule_name="Duplicate Invoice Detected",
                    severity="CRITICAL",
                    entity_type="INVOICE",
                    entity_id=inv_id,
                    details_json=json.dumps({"duplicate_of_invoice_id": cand.id}),
                    status="OPEN",
                )
                db.add(v)

                try:
                    db.commit()
                except Exception as e:
                    db.rollback()
                    logger.error(f"Failed to record duplicate for invoice {inv_id}: {e}")

                return dup

        return None

    def check_payment(self, payment: PaymentModel, db: Session) -> Optional[DuplicateCandidateModel]:
        if not payment.payment_reference:
            return None

        org_id = payment.organization_id
        pay_id = payment.id

        cand = (
            db.query(PaymentModel)
            .filter(
                PaymentModel.organization_id == org_id,
                PaymentModel.payment_reference == payment.payment_reference,
                PaymentModel.id != pay_id,
            )
            .first()
        )

        if cand:
            dup = DuplicateCandidateModel(
                organization_id=org_id,
                entity_type="PAYMENT",
                primary_entity_id=pay_id,
                duplicate_of_entity_id=cand.id,
                match_type="EXACT",
                similarity_score=1.0,
                details_json=json.dumps({
                    "payment_reference": payment.payment_reference,
                    "matched_fields": ["payment_reference"],
                }),
                status="OPEN",
            )
            db.add(dup)

            v = RuleViolationModel(
                organization_id=org_id,
                rule_id="DUPLICATE_DETECTED",
                rule_name="Duplicate Payment Detected",
                severity="CRITICAL",
                entity_type="PAYMENT",
                entity_id=pay_id,
                details_json=json.dumps({"duplicate_of_payment_id": cand.id}),
                status="OPEN",
            )
            db.add(v)

            try:
                db.commit()
            except Exception as e:
                db.rollback()
                logger.error(f"Failed to record duplicate for payment {pay_id}: {e}")

            return dup

        return None
