"""Seed realistic mock invoice / PO data into the app database for demo testing.

Usage:
    source venv/bin/activate
    PYTHONPATH=. python samples/mock_finance_seed.py
"""

import os
import sys
from decimal import Decimal
from datetime import datetime, timezone

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.database.session import SessionLocal
from app.database.models import (
    DocumentLinkModel,
    DocumentModel,
    InvoiceModel,
    PaymentModel,
    PurchaseOrderModel,
    VendorAliasModel,
    VendorModel,
)


def make_document(db: Session, filename: str, doc_type: str = "INVOICE") -> DocumentModel:
    doc_id = f"doc_{filename.lower().replace(' ', '_').replace('.', '_')}"
    existing = db.query(DocumentModel).filter(DocumentModel.id == doc_id).first()
    if existing:
        return existing

    doc = DocumentModel(
        id=doc_id,
        organization_id="org_default",
        filename=filename,
        document_type=doc_type,
        processing_status="PROCESSED",
        page_count=1,
    )
    db.add(doc)
    db.flush()
    return doc


def ensure_vendor(db: Session, vendor_name: str, organization_id: str = "org_default") -> VendorModel:
    normalized = (vendor_name or "").strip()
    if not normalized:
        raise ValueError("Vendor name is required")

    vendor = (
        db.query(VendorModel)
        .filter(
            VendorModel.organization_id == organization_id,
            VendorModel.normalized_name == normalized.lower(),
        )
        .first()
    )
    if vendor:
        return vendor

    vendor_id = f"ven_{normalized.lower().replace(' ', '_').replace('.', '_')[:20]}_{abs(hash(normalized)) % 10000}"
    vendor = VendorModel(
        id=vendor_id,
        organization_id=organization_id,
        canonical_name=normalized,
        normalized_name=normalized.lower(),
        tax_id=None,
        bank_account=None,
        ifsc_swift=None,
    )
    db.add(vendor)
    db.flush()

    alias = VendorAliasModel(
        id=f"alias_{vendor.id}",
        vendor_id=vendor.id,
        organization_id=organization_id,
        alias_name=normalized,
        normalized_alias=normalized.lower(),
        source_document_id=None,
    )
    db.add(alias)
    db.flush()
    return vendor


def seed_data(reset: bool = False):
    db: Session = SessionLocal()
    try:
        if reset:
            db.query(DocumentLinkModel).delete(synchronize_session=False)
            db.query(PaymentModel).delete(synchronize_session=False)
            db.query(InvoiceModel).delete(synchronize_session=False)
            db.query(PurchaseOrderModel).delete(synchronize_session=False)
            db.query(VendorAliasModel).delete(synchronize_session=False)
            db.query(VendorModel).delete(synchronize_session=False)
            db.query(DocumentModel).delete(synchronize_session=False)
            db.commit()

        existing_vendor_count = db.query(VendorModel).count()
        if existing_vendor_count == 0:
            db.add_all([
                VendorModel(
                    id="ven_hari_om",
                    organization_id="org_default",
                    canonical_name="HARI OM",
                    normalized_name="hari om",
                    tax_id=None,
                    bank_account=None,
                    ifsc_swift=None,
                ),
                VendorModel(
                    id="ven_abc_supplies",
                    organization_id="org_default",
                    canonical_name="ABC Supplies",
                    normalized_name="abc supplies",
                    tax_id=None,
                    bank_account=None,
                    ifsc_swift=None,
                ),
                VendorModel(
                    id="ven_delta_traders",
                    organization_id="org_default",
                    canonical_name="Delta Traders",
                    normalized_name="delta traders",
                    tax_id=None,
                    bank_account=None,
                    ifsc_swift=None,
                ),
            ])
            db.flush()

            db.add_all([
                VendorAliasModel(id="alias_hari_om", vendor_id="ven_hari_om", organization_id="org_default", alias_name="HARI OM", normalized_alias="hari om"),
                VendorAliasModel(id="alias_abc_supplies", vendor_id="ven_abc_supplies", organization_id="org_default", alias_name="ABC Supplies", normalized_alias="abc supplies"),
                VendorAliasModel(id="alias_delta_traders", vendor_id="ven_delta_traders", organization_id="org_default", alias_name="Delta Traders", normalized_alias="delta traders"),
            ])

        po_rows = [
            ("PO-101", "HARI OM", Decimal("50000"), "po_101"),
            ("PO-102", "HARI OM", Decimal("52000"), "po_102"),
            ("PO-201", "ABC Supplies", Decimal("48000"), "po_201"),
            ("PO-401", "HARI OM", Decimal("70000"), "po_401"),
            ("PO-999", "ABC Supplies", Decimal("45000"), "po_999"),
        ]

        po_map = {}
        for po_number, vendor_name, total, label in po_rows:
            vendor = ensure_vendor(db, vendor_name)
            doc = make_document(db, f"{label}.pdf", "PURCHASE_ORDER")
            po = db.query(PurchaseOrderModel).filter(PurchaseOrderModel.id == f"po_{label}").first()
            if po is None:
                po = PurchaseOrderModel(
                    id=f"po_{label}",
                    document_id=doc.id,
                    organization_id="org_default",
                    vendor_id=vendor.id,
                    po_number=po_number,
                    vendor_name_raw=vendor_name,
                    vendor_name_normalized=vendor_name,
                    total_amount=total,
                    status="OPEN",
                    created_at=datetime.now(timezone.utc),
                )
                db.add(po)
                db.flush()
            else:
                po.vendor_id = vendor.id
                po.po_number = po_number
                po.vendor_name_raw = vendor_name
                po.vendor_name_normalized = vendor_name
                po.total_amount = total
                po.status = "OPEN"
                po.document_id = doc.id
            po_map[po_number] = po

        inv_rows = [
            ("inv_1001", "INV-1001", "HARI OM", "PO-101", Decimal("12000"), "invoice_1001"),
            ("inv_1002", "INV-1002", "HARI OM", "PO-101", Decimal("13200"), "invoice_1002"),
            ("inv_1003", "INV-1003", "HARI OM", "PO-101", Decimal("14100"), "invoice_1003"),
            ("inv_1004", "INV-1004", "HARI OM", "PO-102", Decimal("15000"), "invoice_1004"),
            ("inv_1005", "INV-1005", "HARI OM", "PO-102", Decimal("16800"), "invoice_1005"),
            ("inv_1006", "INV-1006", "HARI OM", "PO-102", Decimal("17650"), "invoice_1006"),
            ("inv_1006_dup", "INV-1006", "HARI OM", "PO-102", Decimal("17650"), "invoice_1006_dup"),
            ("inv_4001", "INV-4001", "HARI OM", "PO-401", Decimal("95000"), "invoice_4001"),
            ("inv_5001", "INV-5001", "HARI OM", "LY", Decimal("12800"), "invoice_5001"),
            ("inv_2001", "INV-2001", "ABC Supplies", "PO-201", Decimal("45000"), "invoice_2001"),
            ("inv_2002", "INV-2002", "ABC Supplies", "PO-201", Decimal("46000"), "invoice_2002"),
            ("inv_2003", "INV-2003", "ABC Supplies", "PO-999", Decimal("70000"), "invoice_2003"),
            ("inv_3001", "INV-3001", "Delta Traders", None, Decimal("0"), "invoice_3001"),
        ]

        for inv_id, invoice_number, vendor_name, po_number, total_amount, label in inv_rows:
            vendor = ensure_vendor(db, vendor_name)
            doc = make_document(db, f"{label}.pdf", "INVOICE")
            inv = db.query(InvoiceModel).filter(InvoiceModel.id == inv_id).first()
            if inv is None:
                inv = InvoiceModel(
                    id=inv_id,
                    document_id=doc.id,
                    organization_id="org_default",
                    vendor_id=vendor.id,
                    invoice_number=invoice_number,
                    vendor_name_raw=vendor_name,
                    vendor_name_normalized=vendor_name,
                    po_number=po_number,
                    total_amount=total_amount,
                    payment_status="PENDING" if total_amount != Decimal("45000") and inv_id not in {"inv_2001", "inv_2002"} else "PAID",
                    is_valid=True,
                    created_at=datetime.now(timezone.utc),
                )
                db.add(inv)
                db.flush()
            else:
                inv.document_id = doc.id
                inv.vendor_id = vendor.id
                inv.invoice_number = invoice_number
                inv.vendor_name_raw = vendor_name
                inv.vendor_name_normalized = vendor_name
                inv.po_number = po_number
                inv.total_amount = total_amount
                inv.payment_status = "PENDING" if total_amount != Decimal("45000") and inv_id not in {"inv_2001", "inv_2002"} else "PAID"
                inv.is_valid = True

            if po_number and po_number in po_map:
                link = (
                    db.query(DocumentLinkModel)
                    .filter(
                        DocumentLinkModel.organization_id == "org_default",
                        DocumentLinkModel.source_type == "INVOICE",
                        DocumentLinkModel.source_id == inv.id,
                        DocumentLinkModel.link_type == "INVOICE_TO_PO",
                    )
                    .first()
                )
                if not link:
                    db.add(
                        DocumentLinkModel(
                            id=f"link_inv_po_{inv.id}",
                            organization_id="org_default",
                            link_type="INVOICE_TO_PO",
                            source_type="INVOICE",
                            source_id=inv.id,
                            target_type="PURCHASE_ORDER",
                            target_id=po_map[po_number].id,
                            match_type="EXACT_IDENTIFIER",
                            status="LINKED",
                        )
                    )

        payment_rows = [
            ("pay_201", "PMT-201", "ABC Supplies", "INV-2001", Decimal("50000"), "payment_201"),
            ("pay_202", "PMT-202", "ABC Supplies", "INV-2002", Decimal("47000"), "payment_202"),
            ("pay_203", "PMT-203", "HARI OM", "INV-1006", Decimal("20000"), "payment_203"),
        ]

        for pay_id, ref, vendor_name, invoice_number, amount, label in payment_rows:
            vendor = ensure_vendor(db, vendor_name)
            doc = make_document(db, f"{label}.pdf", "PAYMENT")
            pay = db.query(PaymentModel).filter(PaymentModel.id == pay_id).first()
            if pay is None:
                pay = PaymentModel(
                    id=pay_id,
                    document_id=doc.id,
                    organization_id="org_default",
                    payment_reference=ref,
                    vendor_id=vendor.id,
                    payee_name=vendor_name,
                    amount=amount,
                    currency="INR",
                    payment_method="NEFT",
                    status="COMPLETED",
                    created_at=datetime.now(timezone.utc),
                )
                db.add(pay)
                db.flush()
            else:
                pay.document_id = doc.id
                pay.vendor_id = vendor.id
                pay.payment_reference = ref
                pay.payee_name = vendor_name
                pay.amount = amount
                pay.currency = "INR"
                pay.payment_method = "NEFT"
                pay.status = "COMPLETED"

            inv = db.query(InvoiceModel).filter(InvoiceModel.organization_id == "org_default", InvoiceModel.invoice_number == invoice_number).first()
            if inv:
                link = (
                    db.query(DocumentLinkModel)
                    .filter(
                        DocumentLinkModel.organization_id == "org_default",
                        DocumentLinkModel.source_type == "PAYMENT",
                        DocumentLinkModel.source_id == pay.id,
                        DocumentLinkModel.link_type == "PAYMENT_TO_INVOICE",
                    )
                    .first()
                )
                if not link:
                    db.add(
                        DocumentLinkModel(
                            id=f"link_pay_inv_{pay.id}",
                            organization_id="org_default",
                            link_type="PAYMENT_TO_INVOICE",
                            source_type="PAYMENT",
                            source_id=pay.id,
                            target_type="INVOICE",
                            target_id=inv.id,
                            match_type="EXACT_IDENTIFIER",
                            status="LINKED",
                        )
                    )

        db.commit()
        print("Seeded mock finance data successfully.")
        print(
            "POs: {} | Invoices: {} | Payments: {} | Vendors: {} | Links: {}".format(
                db.query(PurchaseOrderModel).count(),
                db.query(InvoiceModel).count(),
                db.query(PaymentModel).count(),
                db.query(VendorModel).count(),
                db.query(DocumentLinkModel).count(),
            )
        )
    finally:
        db.close()


if __name__ == "__main__":
    seed_data()
