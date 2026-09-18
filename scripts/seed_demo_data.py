#!/usr/bin/env python3
"""
scripts/seed_demo_data.py
─────────────────────────
Populates the SQLite database with realistic demo data to exercise every
backend feature in the MVP:

  ✓ Vendors & aliases            → Entity Resolution, Copilot vendor queries
  ✓ 7 months of invoice history  → Analytics, Copilot "total spend" queries
  ✓ Line items with product codes → Investigation Engine line-item diffing
  ✓ August spend spike           → Investigation Engine (quantity surge + new item)
  ✓ POs linked to invoices       → Document Linking
  ✓ 3 invoices WITHOUT a PO      → Rule Engine (INVOICE_WITHOUT_PO violations)
  ✓ 2 duplicate invoice pairs    → Duplicate Detector
  ✓ 3 anomaly flags              → Anomaly Detector, Investigation Engine
  ✓ Payments                     → Payment history queries, Graph

Run:
    ./venv/bin/python3 scripts/seed_demo_data.py
"""

import sys
import os
import uuid
import json
from datetime import date, datetime
from decimal import Decimal

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from app.database.session import SessionLocal, engine
from app.database.models import (
    Base,
    DocumentModel,
    VendorModel,
    VendorAliasModel,
    InvoiceModel,
    InvoiceLineItemModel,
    PurchaseOrderModel,
    PurchaseOrderLineItemModel,
    PaymentModel,
    DocumentLinkModel,
    RuleViolationModel,
    DuplicateCandidateModel,
    AnomalyFlagModel,
)

ORG = "org_default"
BUYER = "Acme Corp Pvt Ltd"
BUYER_NORM = "acme corp pvt ltd"


def uid(prefix):
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def make_doc(db, filename, doc_type="INVOICE"):
    doc = DocumentModel(
        id=uid("doc"),
        organization_id=ORG,
        filename=filename,
        document_type=doc_type,
        processing_status="PROCESSED",
        page_count=2,
    )
    db.add(doc)
    db.flush()
    return doc


def normalize(name):
    return name.lower().strip()


VENDORS = [
    {
        "canonical_name": "Amazon Web Services",
        "normalized_name": "amazon web services",
        "email_domain": "aws.amazon.com",
        "tax_id": "GSTIN27AMZN0001F",
        "aliases": ["AWS", "Amazon AWS", "AWS India", "Amazon Cloud"],
        "code": "AWS",
    },
    {
        "canonical_name": "Microsoft Azure",
        "normalized_name": "microsoft azure",
        "email_domain": "microsoft.com",
        "tax_id": "GSTIN27MSFT0002F",
        "aliases": ["Azure", "MS Azure", "Microsoft Cloud", "MSFT Azure"],
        "code": "AZR",
    },
    {
        "canonical_name": "Google Cloud Platform",
        "normalized_name": "google cloud platform",
        "email_domain": "google.com",
        "tax_id": "GSTIN27GOOG0003F",
        "aliases": ["GCP", "Google Cloud", "GCP India", "Google GCP"],
        "code": "GCP",
    },
]

AWS_ITEMS = [
    ("EC2-COMPUTE", "EC2 Compute Instances (m5.large)", Decimal("8500.00"), "instance-month"),
    ("S3-STORAGE",  "S3 Standard Storage (TB)",         Decimal("2300.00"), "TB-month"),
    ("RDS-DB",      "RDS MySQL Multi-AZ (db.t3.medium)", Decimal("6200.00"), "instance-month"),
    ("CF-CDN",      "CloudFront CDN Data Transfer (TB)", Decimal("1800.00"), "TB"),
]
AZR_ITEMS = [
    ("AZR-VM-STD",  "Azure VM Standard_D2s_v3",         Decimal("7800.00"), "instance-month"),
    ("AZR-BLOB",    "Azure Blob Storage (TB)",           Decimal("2100.00"), "TB-month"),
    ("AZR-SQL",     "Azure SQL Database (S2 tier)",      Decimal("5500.00"), "instance-month"),
    ("AZR-CDN",     "Azure CDN Data Transfer (TB)",      Decimal("1600.00"), "TB"),
]
GCP_ITEMS = [
    ("GCE-N1STD",   "Compute Engine n1-standard-4",     Decimal("7200.00"), "instance-month"),
    ("GCS-STD",     "Cloud Storage Standard (TB)",       Decimal("1950.00"), "TB-month"),
    ("CSQL-MYSQL",  "Cloud SQL MySQL (db-n1-standard-2)", Decimal("5800.00"), "instance-month"),
    ("GCE-LB",      "Cloud Load Balancing (rule-month)", Decimal("1200.00"), "rule-month"),
]
VENDOR_ITEMS = {"AWS": AWS_ITEMS, "AZR": AZR_ITEMS, "GCP": GCP_ITEMS}

MONTHLY_QTYS = {
    "AWS": [
        [4, 10, 3, 8],
        [4, 10, 3, 8],
        [5, 12, 3, 9],
        [5, 12, 3, 9],
        [5, 13, 4, 10],
        [5, 13, 4, 10],
        [12, 25, 4, 18],
    ],
    "AZR": [
        [3, 8, 2, 6],
        [3, 8, 2, 6],
        [3, 9, 2, 7],
        [4, 9, 2, 7],
        [4, 10, 3, 8],
        [4, 10, 3, 8],
        [4, 10, 3, 8],
    ],
    "GCP": [
        [2, 6, 2, 4],
        [2, 6, 2, 4],
        [3, 7, 2, 5],
        [3, 7, 2, 5],
        [3, 8, 2, 6],
        [3, 8, 2, 6],
        [8, 20, 5, 15],
    ],
}

MONTHS = [
    (2025, 2), (2025, 3), (2025, 4), (2025, 5),
    (2025, 6), (2025, 7), (2025, 8),
]


def compute_totals(items_data):
    subtotal = sum(Decimal(str(qty)) * price for code, desc, price, unit, qty in items_data)
    tax = (subtotal * Decimal("0.18")).quantize(Decimal("0.01"))
    return subtotal, tax, subtotal + tax


def make_raw_json(vendor, inv_num, month_label, items_data, total):
    lines_text = "; ".join(
        f"{desc} ({code}): {qty} x {price}"
        for code, desc, price, unit, qty in items_data
    )
    return json.dumps({
        "vendor": vendor,
        "invoice_number": inv_num,
        "period": month_label,
        "line_items": lines_text,
        "total_inr": str(total),
        "buyer": BUYER,
    })


def seed():
    print("=" * 70)
    print("  Finance Platform Demo Data Seed")
    print("=" * 70)

    Base.metadata.create_all(bind=engine)
    db = SessionLocal()

    try:
        print("\n[1/8] Clearing existing demo data ...")
        for Model in [
            AnomalyFlagModel, DuplicateCandidateModel, RuleViolationModel,
            DocumentLinkModel, PaymentModel,
            InvoiceLineItemModel, InvoiceModel,
            PurchaseOrderLineItemModel, PurchaseOrderModel,
            VendorAliasModel, VendorModel, DocumentModel,
        ]:
            deleted = db.query(Model).filter_by(organization_id=ORG).delete(synchronize_session="fetch")
            if deleted:
                print(f"   Deleted {deleted} rows from {Model.__tablename__}")
        db.commit()

        print("\n[2/8] Creating vendors & aliases ...")
        vendor_objs = {}
        for vdef in VENDORS:
            v = VendorModel(
                id=uid("ven"),
                organization_id=ORG,
                canonical_name=vdef["canonical_name"],
                normalized_name=vdef["normalized_name"],
                email_domain=vdef["email_domain"],
                tax_id=vdef["tax_id"],
            )
            db.add(v)
            db.flush()
            vendor_objs[vdef["code"]] = v
            print(f"   + Vendor: {vdef['canonical_name']} ({v.id})")
            for alias in vdef["aliases"]:
                db.add(VendorAliasModel(
                    id=uid("alias"),
                    vendor_id=v.id,
                    organization_id=ORG,
                    alias_name=alias,
                    normalized_alias=normalize(alias),
                ))
        db.commit()

        print("\n[3/8] Creating 7 months of invoices (Feb-Aug 2025) ...")
        all_invoices = {}
        po_linked = []
        no_po = []

        for mi, (yr, mo) in enumerate(MONTHS):
            inv_date = date(yr, mo, 5)
            next_mo = mo + 1 if mo < 12 else 1
            next_yr = yr if mo < 12 else yr + 1
            due_date = date(next_yr, next_mo, 5)
            month_label = inv_date.strftime("%B %Y")
            is_aug = (mo == 8)

            for vcode, vendor in vendor_objs.items():
                items_tmpl = VENDOR_ITEMS[vcode]
                qtys = MONTHLY_QTYS[vcode][mi]
                inv_num = f"{vcode}-{yr}-{mo:02d}-001"
                doc = make_doc(db, f"{inv_num}.pdf", "INVOICE")

                items_data = [
                    (code, desc, price, unit, qty)
                    for (code, desc, price, unit), qty in zip(items_tmpl, qtys)
                ]

                if is_aug and vcode == "AWS":
                    items_data.append(("ENT-SUPPORT", "AWS Enterprise Support (Annual)", Decimal("45000.00"), "subscription", 1))

                subtotal, tax, total = compute_totals(items_data)

                inv = InvoiceModel(
                    id=uid("inv"),
                    document_id=doc.id,
                    organization_id=ORG,
                    vendor_id=vendor.id,
                    invoice_number=inv_num,
                    invoice_date=inv_date,
                    due_date=due_date,
                    vendor_name_raw=vendor.canonical_name,
                    vendor_name_normalized=vendor.normalized_name,
                    vendor_tax_id=vendor.tax_id,
                    buyer_name_raw=BUYER,
                    buyer_name_normalized=BUYER_NORM,
                    currency="INR",
                    subtotal=subtotal,
                    tax_amount=tax,
                    total_amount=total,
                    amount_due=total,
                    payment_status="paid" if mi < 6 else "unpaid",
                    payment_terms="Net 30",
                    confidence=Decimal("0.97"),
                    is_valid=True,
                    raw_data_json=make_raw_json(vendor.canonical_name, inv_num, month_label, items_data, total),
                )
                db.add(inv)
                db.flush()

                for ln, (code, desc, price, unit, qty) in enumerate(items_data, 1):
                    line_total = (Decimal(str(qty)) * price).quantize(Decimal("0.01"))
                    db.add(InvoiceLineItemModel(
                        id=uid("item"),
                        invoice_id=inv.id,
                        organization_id=ORG,
                        line_number=ln,
                        description=desc,
                        product_code=code,
                        quantity=Decimal(str(qty)),
                        unit=unit,
                        unit_price=price,
                        tax_rate=Decimal("18.00"),
                        tax_amount=(line_total * Decimal("0.18")).quantize(Decimal("0.01")),
                        total=line_total,
                        category="Cloud Infrastructure",
                    ))

                all_invoices[(vcode, mi)] = inv

                if is_aug and vcode in ("AWS", "GCP"):
                    no_po.append(inv)
                    print(f"   ! {inv_num}  total=INR {total:,.2f}  [NO PO - rule violation]")
                else:
                    po_linked.append((inv, f"PO-{vcode}-{yr}-{mo:02d}"))
                    print(f"   + {inv_num}  total=INR {total:,.2f}")

        db.commit()

        print("\n[4/8] Creating Purchase Orders & links ...")
        for inv, po_number in po_linked:
            po_doc = make_doc(db, f"{po_number}.pdf", "PURCHASE_ORDER")
            po = PurchaseOrderModel(
                id=uid("po"),
                document_id=po_doc.id,
                organization_id=ORG,
                vendor_id=inv.vendor_id,
                po_number=po_number,
                po_date=inv.invoice_date,
                vendor_name_raw=inv.vendor_name_raw,
                vendor_name_normalized=inv.vendor_name_normalized,
                vendor_tax_id=inv.vendor_tax_id,
                buyer_name_raw=BUYER,
                buyer_name_normalized=BUYER_NORM,
                currency="INR",
                subtotal=inv.subtotal,
                tax_amount=inv.tax_amount,
                total_amount=inv.total_amount,
                status="FULFILLED",
                payment_terms="Net 30",
                confidence=Decimal("0.99"),
                is_valid=True,
            )
            db.add(po)
            db.flush()
            db.add(DocumentLinkModel(
                id=uid("link"),
                organization_id=ORG,
                link_type="INVOICE_TO_PO",
                source_type="INVOICE",
                source_id=inv.id,
                target_type="PURCHASE_ORDER",
                target_id=po.id,
                match_type="EXACT_IDENTIFIER",
                confidence=Decimal("1.0"),
                status="LINKED",
            ))
            print(f"   + {po_number} linked to {inv.invoice_number}")
        db.commit()

        print("\n[5/8] Creating Rule Violations (INVOICE_WITHOUT_PO) ...")
        for inv in no_po:
            db.add(RuleViolationModel(
                id=uid("rv"),
                organization_id=ORG,
                rule_id="RULE_INVOICE_WITHOUT_PO",
                rule_name="Invoice Without Matching Purchase Order",
                severity="CRITICAL",
                entity_type="INVOICE",
                entity_id=inv.id,
                details_json=json.dumps({
                    "invoice_number": inv.invoice_number,
                    "vendor": inv.vendor_name_raw,
                    "total_amount": str(inv.total_amount),
                    "message": "No matching Purchase Order found for this invoice.",
                }),
                status="OPEN",
            ))
            print(f"   + Rule violation: {inv.invoice_number}")
        db.commit()

        print("\n[6/8] Creating Duplicate Invoice Candidates ...")
        azr_mar = all_invoices[("AZR", 1)]
        dup_doc1 = make_doc(db, "AZR-2025-03-001-DUPLICATE.pdf", "INVOICE")
        dup1 = InvoiceModel(
            id=uid("inv"),
            document_id=dup_doc1.id,
            organization_id=ORG,
            vendor_id=vendor_objs["AZR"].id,
            invoice_number="AZR-2025-03-001",
            invoice_date=date(2025, 3, 5),
            vendor_name_raw="MS Azure",
            vendor_name_normalized="microsoft azure",
            currency="INR",
            subtotal=azr_mar.subtotal,
            tax_amount=azr_mar.tax_amount,
            total_amount=azr_mar.total_amount,
            amount_due=azr_mar.amount_due,
            payment_status="unpaid",
            confidence=Decimal("0.94"),
            is_valid=True,
        )
        db.add(dup1)
        db.flush()
        db.add(DuplicateCandidateModel(
            id=uid("dup"),
            organization_id=ORG,
            entity_type="INVOICE",
            primary_entity_id=dup1.id,
            duplicate_of_entity_id=azr_mar.id,
            match_type="EXACT",
            similarity_score=Decimal("1.000"),
            details_json=json.dumps({"match_fields": ["invoice_number", "vendor_normalized", "total_amount"]}),
            status="OPEN",
        ))
        print("   + Duplicate 1: Azure March (exact match)")

        gcp_jun = all_invoices[("GCP", 4)]
        dup_doc2 = make_doc(db, "GCP-2025-06-001-RESUBMIT.pdf", "INVOICE")
        dup2 = InvoiceModel(
            id=uid("inv"),
            document_id=dup_doc2.id,
            organization_id=ORG,
            vendor_id=vendor_objs["GCP"].id,
            invoice_number="GCP-2025-06-001-R",
            invoice_date=date(2025, 6, 5),
            vendor_name_raw="Google Cloud",
            vendor_name_normalized="google cloud platform",
            currency="INR",
            subtotal=gcp_jun.subtotal + Decimal("500.00"),
            tax_amount=gcp_jun.tax_amount,
            total_amount=gcp_jun.total_amount + Decimal("500.00"),
            amount_due=gcp_jun.amount_due + Decimal("500.00"),
            payment_status="unpaid",
            confidence=Decimal("0.89"),
            is_valid=True,
        )
        db.add(dup2)
        db.flush()
        db.add(DuplicateCandidateModel(
            id=uid("dup"),
            organization_id=ORG,
            entity_type="INVOICE",
            primary_entity_id=dup2.id,
            duplicate_of_entity_id=gcp_jun.id,
            match_type="PROBABLE",
            similarity_score=Decimal("0.960"),
            details_json=json.dumps({"amount_variance_inr": "500.00", "match_fields": ["vendor_normalized", "invoice_date"]}),
            status="OPEN",
        ))
        print("   + Duplicate 2: GCP June (probable, INR 500 variance)")
        db.commit()

        print("\n[7/8] Creating Anomaly Flags ...")
        aws_aug = all_invoices[("AWS", 6)]
        aws_baseline = [all_invoices[("AWS", i)].total_amount for i in range(6)]
        aws_mean = sum(float(x) for x in aws_baseline) / 6
        db.add(AnomalyFlagModel(
            id=uid("anm"),
            organization_id=ORG,
            entity_type="INVOICE",
            entity_id=aws_aug.id,
            vendor_id=vendor_objs["AWS"].id,
            anomaly_type="HIGH_AMOUNT",
            observed_value=aws_aug.total_amount,
            expected_mean=Decimal(str(round(aws_mean, 2))),
            expected_std=Decimal("15000.00"),
            z_score=Decimal("4.87"),
            sample_size=6,
            status="OPEN",
        ))
        print(f"   + AWS August anomaly (z=4.87, total=INR {aws_aug.total_amount:,.2f})")

        gcp_aug = all_invoices[("GCP", 6)]
        gcp_baseline = [all_invoices[("GCP", i)].total_amount for i in range(6)]
        gcp_mean = sum(float(x) for x in gcp_baseline) / 6
        db.add(AnomalyFlagModel(
            id=uid("anm"),
            organization_id=ORG,
            entity_type="INVOICE",
            entity_id=gcp_aug.id,
            vendor_id=vendor_objs["GCP"].id,
            anomaly_type="HIGH_AMOUNT",
            observed_value=gcp_aug.total_amount,
            expected_mean=Decimal(str(round(gcp_mean, 2))),
            expected_std=Decimal("12000.00"),
            z_score=Decimal("3.92"),
            sample_size=6,
            status="OPEN",
        ))
        print(f"   + GCP August anomaly (z=3.92, total=INR {gcp_aug.total_amount:,.2f})")

        azr_apr = all_invoices[("AZR", 2)]
        db.add(AnomalyFlagModel(
            id=uid("anm"),
            organization_id=ORG,
            entity_type="INVOICE",
            entity_id=azr_apr.id,
            vendor_id=vendor_objs["AZR"].id,
            anomaly_type="LOW_AMOUNT",
            observed_value=azr_apr.total_amount,
            expected_mean=Decimal("95000.00"),
            expected_std=Decimal("8000.00"),
            z_score=Decimal("-2.45"),
            sample_size=3,
            status="REVIEWED",
        ))
        print(f"   + Azure April low-amount anomaly (z=-2.45, status=REVIEWED)")
        db.commit()

        print("\n[8/8] Creating Payment records (Feb-Jul) ...")
        for mi in range(6):
            yr, mo = MONTHS[mi]
            next_mo = mo + 1 if mo < 12 else 1
            next_yr = yr if mo < 12 else yr + 1
            pay_date = date(next_yr, next_mo, 10)
            for vcode, vendor in vendor_objs.items():
                inv = all_invoices[(vcode, mi)]
                pay_ref = f"NEFT-{vcode}-{yr}-{mo:02d}"
                pay = PaymentModel(
                    id=uid("pay"),
                    organization_id=ORG,
                    vendor_id=vendor.id,
                    payment_reference=pay_ref,
                    payment_date=pay_date,
                    amount=inv.total_amount,
                    currency="INR",
                    payment_method="NEFT",
                    payer_name=BUYER,
                    payee_name=vendor.canonical_name,
                    status="COMPLETED",
                )
                db.add(pay)
                db.flush()
                db.add(DocumentLinkModel(
                    id=uid("link"),
                    organization_id=ORG,
                    link_type="PAYMENT_TO_INVOICE",
                    source_type="PAYMENT",
                    source_id=pay.id,
                    target_type="INVOICE",
                    target_id=inv.id,
                    match_type="EXACT_IDENTIFIER",
                    confidence=Decimal("1.0"),
                    status="LINKED",
                ))
                print(f"   + Payment {pay_ref} -> {inv.invoice_number}")
        db.commit()

        print("\n" + "=" * 70)
        print("  SEED COMPLETE")
        print("=" * 70)
        counts = {
            "Vendors": db.query(VendorModel).filter_by(organization_id=ORG).count(),
            "Vendor Aliases": db.query(VendorAliasModel).filter_by(organization_id=ORG).count(),
            "Documents": db.query(DocumentModel).filter_by(organization_id=ORG).count(),
            "Invoices": db.query(InvoiceModel).filter_by(organization_id=ORG).count(),
            "Invoice Line Items": db.query(InvoiceLineItemModel).filter_by(organization_id=ORG).count(),
            "Purchase Orders": db.query(PurchaseOrderModel).filter_by(organization_id=ORG).count(),
            "Payments": db.query(PaymentModel).filter_by(organization_id=ORG).count(),
            "Document Links": db.query(DocumentLinkModel).filter_by(organization_id=ORG).count(),
            "Rule Violations": db.query(RuleViolationModel).filter_by(organization_id=ORG).count(),
            "Duplicate Candidates": db.query(DuplicateCandidateModel).filter_by(organization_id=ORG).count(),
            "Anomaly Flags": db.query(AnomalyFlagModel).filter_by(organization_id=ORG).count(),
        }
        for label, count in counts.items():
            print(f"  {label:<25} {count}")
        print()
        print("  Start the server:  ./venv/bin/uvicorn app.main:app --reload")
        print("  Open UI:           http://localhost:8000/ui")
        print()
        print("  Copilot queries to try:")
        print('    "What did we spend on AWS in August 2025?"')
        print('    "Show me all invoices without a purchase order"')
        print('    "Are there any duplicate invoices?"')
        print('    "Which vendor had the biggest spend increase in August?"')
        print()
        print("  Investigation: Vendor=Amazon Web Services, Baseline=July 2025, Target=August 2025")
        print("=" * 70)

    except Exception as e:
        db.rollback()
        print(f"\n  ERROR: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
    finally:
        db.close()


if __name__ == "__main__":
    seed()
