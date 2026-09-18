import json
from typing import List, Optional, Tuple, Dict, Any
from decimal import Decimal
from sqlalchemy.orm import Session

from app.config import settings
from app.database.models import (
    InvoiceModel,
    PurchaseOrderModel,
    PaymentModel,
    DocumentLinkModel,
    ValidationIssueModel,
)
from app.database.repositories.link_repo import DocumentLinkRepository
from app.utils.logging import logger


class DocumentLinker:
    """
    Deterministic Document Linking Engine.
    Connects Invoices <-> Purchase Orders <-> Payments.
    Enforces 3-way balance checks, variance detection, and retroactive linking.
    """

    def __init__(self, tolerance: Optional[Decimal] = None):
        self.tolerance = tolerance or settings.finance_validation_tolerance_decimal

    def link_invoice_to_po(
        self,
        db: Session,
        invoice_id: str,
        po_number: Optional[str],
        invoice_total: Optional[Decimal],
        organization_id: str = settings.DEFAULT_ORGANIZATION_ID,
        vendor_id: Optional[str] = None,
    ) -> Optional[DocumentLinkModel]:
        """
        Links an invoice to its referenced purchase order.
        Evaluates amount balance, flags discrepancies, or logs an unresolved link.
        """
        if not po_number or not po_number.strip():
            return None

        clean_po_no = po_number.strip()
        link_repo = DocumentLinkRepository(db)

        # 1. Search for matching PO in DB
        po = db.query(PurchaseOrderModel).filter(
            PurchaseOrderModel.organization_id == organization_id,
            PurchaseOrderModel.po_number == clean_po_no,
        ).first()

        if po:
            # Check for amount mismatch
            status = "LINKED"
            discrepancy_dict = {}

            if invoice_total is not None and po.total_amount is not None:
                diff = abs(invoice_total - po.total_amount)
                if diff > self.tolerance:
                    status = "DISCREPANCY"
                    discrepancy_dict["issue"] = "PO_AMOUNT_MISMATCH"
                    discrepancy_dict["expected"] = str(po.total_amount)
                    discrepancy_dict["actual"] = str(invoice_total)
                    discrepancy_dict["difference"] = str(diff)
                    logger.warning(
                        f"LINKER: PO amount mismatch for invoice {invoice_id} vs PO {po.po_number}: "
                        f"invoice={invoice_total}, po={po.total_amount}, diff={diff}"
                    )

            if vendor_id and po.vendor_id and vendor_id != po.vendor_id:
                discrepancy_dict["vendor_mismatch"] = True
                logger.warning(f"LINKER: Vendor mismatch between invoice {invoice_id} and PO {po.id}")

            disc_json = json.dumps(discrepancy_dict) if discrepancy_dict else None
            link = link_repo.create_or_update_link(
                link_type="INVOICE_TO_PO",
                source_type="INVOICE",
                source_id=invoice_id,
                target_type="PURCHASE_ORDER",
                target_id=po.id,
                match_type="EXACT_IDENTIFIER",
                confidence=1.0,
                status=status,
                discrepancy_details=disc_json,
                organization_id=organization_id,
            )
            return link
        else:
            # Record unresolved reference without hallucination
            logger.info(f"LINKER: PO '{clean_po_no}' referenced by invoice {invoice_id} not yet in database. Storing UNRESOLVED link.")
            unresolved_dict = {"issue": "MISSING_PURCHASE_ORDER", "po_number": clean_po_no}
            link = link_repo.create_or_update_link(
                link_type="INVOICE_TO_PO",
                source_type="INVOICE",
                source_id=invoice_id,
                target_type="PURCHASE_ORDER",
                target_id=None,
                match_type="UNRESOLVED_REFERENCE",
                confidence=0.0,
                status="UNRESOLVED",
                discrepancy_details=json.dumps(unresolved_dict),
                organization_id=organization_id,
            )
            return link

    def link_po_retroactively(
        self,
        db: Session,
        po_id: str,
        po_number: str,
        po_total: Optional[Decimal],
        organization_id: str = settings.DEFAULT_ORGANIZATION_ID,
        vendor_id: Optional[str] = None,
    ) -> List[DocumentLinkModel]:
        """
        Called when a new Purchase Order is ingested.
        Finds previously ingested invoices that referenced this PO number, and retroactively resolves their links!
        """
        if not po_number:
            return []

        clean_po_no = po_number.strip()
        link_repo = DocumentLinkRepository(db)

        # Find invoices with matching po_number
        invoices = db.query(InvoiceModel).filter(
            InvoiceModel.organization_id == organization_id,
            InvoiceModel.po_number == clean_po_no,
        ).all()

        resolved_links: List[DocumentLinkModel] = []
        for inv in invoices:
            status = "LINKED"
            discrepancy_dict = {}

            if inv.total_amount is not None and po_total is not None:
                diff = abs(inv.total_amount - po_total)
                if diff > self.tolerance:
                    status = "DISCREPANCY"
                    discrepancy_dict["issue"] = "PO_AMOUNT_MISMATCH"
                    discrepancy_dict["expected"] = str(po_total)
                    discrepancy_dict["actual"] = str(inv.total_amount)
                    discrepancy_dict["difference"] = str(diff)

            disc_json = json.dumps(discrepancy_dict) if discrepancy_dict else None
            link = link_repo.create_or_update_link(
                link_type="INVOICE_TO_PO",
                source_type="INVOICE",
                source_id=inv.id,
                target_type="PURCHASE_ORDER",
                target_id=po_id,
                match_type="EXACT_IDENTIFIER",
                confidence=1.0,
                status=status,
                discrepancy_details=disc_json,
                organization_id=organization_id,
            )
            resolved_links.append(link)
            logger.info(f"LINKER: Retroactively linked invoice {inv.invoice_number} to PO {clean_po_no} (status={status})")

        return resolved_links

    def link_payment_to_invoices(
        self,
        db: Session,
        payment_id: str,
        referenced_invoice_numbers: List[str],
        payment_amount: Decimal,
        organization_id: str = settings.DEFAULT_ORGANIZATION_ID,
    ) -> List[DocumentLinkModel]:
        """
        Links a payment to referenced invoices and updates invoice payment statuses.
        """
        link_repo = DocumentLinkRepository(db)
        created_links: List[DocumentLinkModel] = []

        for inv_no in referenced_invoice_numbers:
            clean_no = inv_no.strip()
            inv = db.query(InvoiceModel).filter(
                InvoiceModel.organization_id == organization_id,
                InvoiceModel.invoice_number == clean_no,
            ).first()

            if not inv:
                logger.info(f"LINKER: Payment {payment_id} references unknown invoice '{clean_no}'")
                continue

            # Create payment to invoice link
            link = link_repo.create_or_update_link(
                link_type="PAYMENT_TO_INVOICE",
                source_type="PAYMENT",
                source_id=payment_id,
                target_type="INVOICE",
                target_id=inv.id,
                match_type="EXACT_IDENTIFIER",
                confidence=1.0,
                status="LINKED",
                organization_id=organization_id,
            )
            created_links.append(link)

            # Recalculate invoice payment status
            self._update_invoice_payment_status(db, inv, organization_id)

        return created_links

    def _update_invoice_payment_status(
        self,
        db: Session,
        invoice: InvoiceModel,
        organization_id: str,
    ) -> None:
        """
        Sums all completed payments linked to this invoice and updates its payment_status.
        Handles: unpaid, partially_paid, paid, overpaid.
        """
        # Query all links where target is this invoice
        pay_links = db.query(DocumentLinkModel).filter(
            DocumentLinkModel.organization_id == organization_id,
            DocumentLinkModel.target_type == "INVOICE",
            DocumentLinkModel.target_id == invoice.id,
            DocumentLinkModel.link_type == "PAYMENT_TO_INVOICE",
            DocumentLinkModel.status == "LINKED",
        ).all()

        payment_ids = [l.source_id for l in pay_links]
        if not payment_ids:
            invoice.payment_status = "unpaid"
            db.commit()
            return

        payments = db.query(PaymentModel).filter(
            PaymentModel.id.in_(payment_ids),
            PaymentModel.status == "COMPLETED",
        ).all()

        total_paid = sum((p.amount for p in payments if p.amount), Decimal("0.00"))
        inv_total = invoice.total_amount or Decimal("0.00")

        if total_paid == Decimal("0.00"):
            invoice.payment_status = "unpaid"
        elif total_paid < inv_total - self.tolerance:
            invoice.payment_status = "partially_paid"
        elif abs(total_paid - inv_total) <= self.tolerance:
            invoice.payment_status = "paid"
        else:  # total_paid > inv_total + tolerance
            invoice.payment_status = "overpaid"
            logger.warning(f"LINKER: Invoice {invoice.invoice_number} is OVERPAID: paid={total_paid}, total={inv_total}")

        db.commit()
        logger.info(f"LINKER: Updated invoice {invoice.invoice_number} payment_status='{invoice.payment_status}' (paid={total_paid}/{inv_total})")
