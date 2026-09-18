from decimal import Decimal
from typing import Optional, List
from sqlalchemy.orm import Session

from app.finance.graph.base import BaseGraphAdapter
from app.database.models import (
    InvoiceModel,
    PurchaseOrderModel,
    PaymentModel,
    VendorModel,
    VendorAliasModel,
    DocumentLinkModel,
)
from app.utils.logging import logger


class GraphSyncService:
    """
    Synchronizes relational models (Invoice, PO, Payment, Vendor, Bank, Tax)
    into the financial knowledge graph.
    """

    def __init__(self, adapter: BaseGraphAdapter):
        self.adapter = adapter

    def sync_vendor(self, vendor: VendorModel, db: Optional[Session] = None) -> None:
        org_id = vendor.organization_id
        # 1. Upsert Vendor node
        self.adapter.upsert_node(
            node_id=vendor.id,
            label="Vendor",
            properties={
                "canonical_name": vendor.canonical_name,
                "normalized_name": vendor.normalized_name,
                "tax_id": vendor.tax_id,
                "organization_id": org_id,
            },
        )

        # 2. Tax ID Node & Edge
        if vendor.tax_id:
            tax_node_id = f"tax_{vendor.tax_id.strip().upper()}"
            self.adapter.upsert_node(
                node_id=tax_node_id,
                label="TaxIdentifier",
                properties={"tax_id": vendor.tax_id, "organization_id": org_id},
            )
            self.adapter.upsert_edge(
                source_id=vendor.id,
                target_id=tax_node_id,
                relation_type="HAS_TAX_ID",
                properties={"organization_id": org_id},
            )

        # 3. Bank Account Node & Edge
        if vendor.bank_account:
            bank_node_id = f"bank_{vendor.bank_account.strip()}"
            self.adapter.upsert_node(
                node_id=bank_node_id,
                label="BankAccount",
                properties={
                    "account_number": vendor.bank_account,
                    "ifsc_swift": vendor.ifsc_swift,
                    "organization_id": org_id,
                },
            )
            self.adapter.upsert_edge(
                source_id=vendor.id,
                target_id=bank_node_id,
                relation_type="USES_BANK_ACCOUNT",
                properties={"organization_id": org_id},
            )

        # 4. Vendor Aliases
        if db:
            aliases = db.query(VendorAliasModel).filter(VendorAliasModel.vendor_id == vendor.id).all()
            for al in aliases:
                al_node_id = al.id
                self.adapter.upsert_node(
                    node_id=al_node_id,
                    label="VendorAlias",
                    properties={"alias_name": al.alias_name, "organization_id": org_id},
                )
                self.adapter.upsert_edge(
                    source_id=vendor.id,
                    target_id=al_node_id,
                    relation_type="HAS_ALIAS",
                    properties={"organization_id": org_id},
                )

    def sync_invoice(self, invoice: InvoiceModel, db: Optional[Session] = None) -> None:
        org_id = invoice.organization_id

        # 1. Upsert Invoice node
        self.adapter.upsert_node(
            node_id=invoice.id,
            label="Invoice",
            properties={
                "invoice_number": invoice.invoice_number,
                "invoice_date": str(invoice.invoice_date) if invoice.invoice_date else None,
                "total_amount": float(invoice.total_amount) if invoice.total_amount else 0.0,
                "currency": invoice.currency,
                "payment_status": invoice.payment_status,
                "organization_id": org_id,
            },
        )

        # 2. Vendor edge
        if invoice.vendor_id:
            if db:
                v = db.query(VendorModel).filter(VendorModel.id == invoice.vendor_id).first()
                if v:
                    self.sync_vendor(v, db)
            self.adapter.upsert_edge(
                source_id=invoice.vendor_id,
                target_id=invoice.id,
                relation_type="ISSUED",
                properties={"organization_id": org_id},
            )

        # 3. PO link edge (if resolved)
        if db:
            links = (
                db.query(DocumentLinkModel)
                .filter(
                    DocumentLinkModel.organization_id == org_id,
                    DocumentLinkModel.source_type == "INVOICE",
                    DocumentLinkModel.source_id == invoice.id,
                    DocumentLinkModel.link_type == "INVOICE_TO_PO",
                )
                .all()
            )
            for l in links:
                if l.target_id:
                    self.adapter.upsert_edge(
                        source_id=invoice.id,
                        target_id=l.target_id,
                        relation_type="REFERENCES_PO",
                        properties={
                            "status": l.status,
                            "match_type": l.match_type,
                            "organization_id": org_id,
                        },
                    )

    def sync_purchase_order(self, po: PurchaseOrderModel, db: Optional[Session] = None) -> None:
        org_id = po.organization_id

        # 1. Upsert PurchaseOrder node
        self.adapter.upsert_node(
            node_id=po.id,
            label="PurchaseOrder",
            properties={
                "po_number": po.po_number,
                "po_date": str(po.po_date) if po.po_date else None,
                "total_amount": float(po.total_amount) if po.total_amount else 0.0,
                "currency": po.currency,
                "status": po.status,
                "organization_id": org_id,
            },
        )

        # 2. Vendor edge
        if po.vendor_id:
            if db:
                v = db.query(VendorModel).filter(VendorModel.id == po.vendor_id).first()
                if v:
                    self.sync_vendor(v, db)
            self.adapter.upsert_edge(
                source_id=po.vendor_id,
                target_id=po.id,
                relation_type="RECEIVED_PO",
                properties={"organization_id": org_id},
            )

    def sync_payment(self, payment: PaymentModel, db: Optional[Session] = None) -> None:
        org_id = payment.organization_id

        # 1. Upsert Payment node
        self.adapter.upsert_node(
            node_id=payment.id,
            label="Payment",
            properties={
                "payment_reference": payment.payment_reference,
                "payment_date": str(payment.payment_date) if payment.payment_date else None,
                "amount": float(payment.amount) if payment.amount else 0.0,
                "currency": payment.currency,
                "payment_method": payment.payment_method,
                "status": payment.status,
                "organization_id": org_id,
            },
        )

        # 2. Bank Account Node & Edge for payment
        if payment.bank_account:
            bank_node_id = f"bank_{payment.bank_account.strip()}"
            self.adapter.upsert_node(
                node_id=bank_node_id,
                label="BankAccount",
                properties={
                    "account_number": payment.bank_account,
                    "ifsc_swift": payment.ifsc_swift,
                    "organization_id": org_id,
                },
            )
            self.adapter.upsert_edge(
                source_id=payment.id,
                target_id=bank_node_id,
                relation_type="ROUTED_THROUGH_BANK",
                properties={"organization_id": org_id},
            )

        # 3. Applied to Invoice edges
        if db:
            links = (
                db.query(DocumentLinkModel)
                .filter(
                    DocumentLinkModel.organization_id == org_id,
                    DocumentLinkModel.source_type == "PAYMENT",
                    DocumentLinkModel.source_id == payment.id,
                    DocumentLinkModel.link_type == "PAYMENT_TO_INVOICE",
                )
                .all()
            )
            for l in links:
                if l.target_id:
                    self.adapter.upsert_edge(
                        source_id=payment.id,
                        target_id=l.target_id,
                        relation_type="APPLIED_TO",
                        properties={"status": l.status, "organization_id": org_id},
                    )

    def sync_all(self, organization_id: str, db: Session) -> dict:
        """
        One-click hydration of entire database into the graph.
        """
        vendors = db.query(VendorModel).filter(VendorModel.organization_id == organization_id).all()
        for v in vendors:
            self.sync_vendor(v, db)

        pos = db.query(PurchaseOrderModel).filter(PurchaseOrderModel.organization_id == organization_id).all()
        for po in pos:
            self.sync_purchase_order(po, db)

        invoices = db.query(InvoiceModel).filter(InvoiceModel.organization_id == organization_id).all()
        for inv in invoices:
            self.sync_invoice(inv, db)

        payments = db.query(PaymentModel).filter(PaymentModel.organization_id == organization_id).all()
        for pay in payments:
            self.sync_payment(pay, db)

        stats = self.adapter.get_stats(organization_id=organization_id)
        return {
            "synced_vendors": len(vendors),
            "synced_pos": len(pos),
            "synced_invoices": len(invoices),
            "synced_payments": len(payments),
            "graph_stats": stats.model_dump(),
        }
