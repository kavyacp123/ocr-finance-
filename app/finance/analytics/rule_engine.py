import json
from decimal import Decimal
from typing import List, Optional
from sqlalchemy.orm import Session

from app.database.models import (
    InvoiceModel,
    PaymentModel,
    DocumentLinkModel,
    RuleViolationModel,
)
from app.utils.logging import logger


class RuleEngine:
    """
    Deterministic Finance Rule Engine (MVP).
    Evaluates 5 critical business rules:
      1. INVOICE_WITHOUT_PO (WARNING)
      2. INVOICE_PO_LINK_UNRESOLVED (WARNING)
      3. INVOICE_PO_AMOUNT_MISMATCH (CRITICAL)
      4. PAYMENT_EXCEEDS_INVOICE (CRITICAL)
      5. ZERO_OR_NEGATIVE_AMOUNT (CRITICAL)
    """

    def evaluate_invoice(self, invoice: InvoiceModel, db: Session) -> List[RuleViolationModel]:
        violations: List[RuleViolationModel] = []
        org_id = invoice.organization_id
        inv_id = invoice.id

        # Rule 1: INVOICE_WITHOUT_PO
        if not invoice.po_number or not str(invoice.po_number).strip():
            v = RuleViolationModel(
                organization_id=org_id,
                rule_id="INVOICE_WITHOUT_PO",
                rule_name="Invoice Without Purchase Order",
                severity="WARNING",
                entity_type="INVOICE",
                entity_id=inv_id,
                details_json=json.dumps({"reason": "No po_number provided on invoice"}),
            )
            violations.append(v)

        # Rule 2: INVOICE_PO_LINK_UNRESOLVED & Rule 3: INVOICE_PO_AMOUNT_MISMATCH
        # Look up document links for this invoice
        links = (
            db.query(DocumentLinkModel)
            .filter(
                DocumentLinkModel.organization_id == org_id,
                DocumentLinkModel.source_type == "INVOICE",
                DocumentLinkModel.source_id == inv_id,
                DocumentLinkModel.link_type == "INVOICE_TO_PO",
            )
            .all()
        )
        for link in links:
            if link.status == "UNRESOLVED":
                v = RuleViolationModel(
                    organization_id=org_id,
                    rule_id="INVOICE_PO_LINK_UNRESOLVED",
                    rule_name="PO Link Unresolved",
                    severity="WARNING",
                    entity_type="INVOICE",
                    entity_id=inv_id,
                    details_json=json.dumps({"po_number": invoice.po_number}),
                )
                violations.append(v)
            elif link.status == "DISCREPANCY":
                v = RuleViolationModel(
                    organization_id=org_id,
                    rule_id="INVOICE_PO_AMOUNT_MISMATCH",
                    rule_name="PO Amount Discrepancy",
                    severity="CRITICAL",
                    entity_type="INVOICE",
                    entity_id=inv_id,
                    details_json=link.discrepancy_details,
                )
                violations.append(v)

        # Rule 4: PAYMENT_EXCEEDS_INVOICE
        if invoice.payment_status == "overpaid":
            v = RuleViolationModel(
                organization_id=org_id,
                rule_id="PAYMENT_EXCEEDS_INVOICE",
                rule_name="Invoice Overpaid",
                severity="CRITICAL",
                entity_type="INVOICE",
                entity_id=inv_id,
                details_json=json.dumps({
                    "total_amount": float(invoice.total_amount) if invoice.total_amount else 0.0,
                    "payment_status": invoice.payment_status,
                }),
            )
            violations.append(v)

        # Rule 5: ZERO_OR_NEGATIVE_AMOUNT
        if invoice.total_amount is None or invoice.total_amount <= Decimal("0.00"):
            v = RuleViolationModel(
                organization_id=org_id,
                rule_id="ZERO_OR_NEGATIVE_AMOUNT",
                rule_name="Zero or Negative Amount",
                severity="CRITICAL",
                entity_type="INVOICE",
                entity_id=inv_id,
                details_json=json.dumps({"total_amount": float(invoice.total_amount) if invoice.total_amount else None}),
            )
            violations.append(v)

        # Persist violations
        for v in violations:
            db.add(v)
        if violations:
            try:
                db.commit()
            except Exception as e:
                db.rollback()
                logger.error(f"Failed to persist rule violations for invoice {inv_id}: {e}")

        return violations

    def evaluate_payment(self, payment: PaymentModel, db: Session) -> List[RuleViolationModel]:
        violations: List[RuleViolationModel] = []
        org_id = payment.organization_id
        pay_id = payment.id

        # Rule 5: ZERO_OR_NEGATIVE_AMOUNT for payment
        if payment.amount is None or payment.amount <= Decimal("0.00"):
            v = RuleViolationModel(
                organization_id=org_id,
                rule_id="ZERO_OR_NEGATIVE_AMOUNT",
                rule_name="Zero or Negative Amount",
                severity="CRITICAL",
                entity_type="PAYMENT",
                entity_id=pay_id,
                details_json=json.dumps({"amount": float(payment.amount) if payment.amount else None}),
            )
            violations.append(v)

        for v in violations:
            db.add(v)
        if violations:
            try:
                db.commit()
            except Exception as e:
                db.rollback()
                logger.error(f"Failed to persist rule violations for payment {pay_id}: {e}")

        return violations
