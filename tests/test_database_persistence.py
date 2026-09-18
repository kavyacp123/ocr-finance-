import pytest
from decimal import Decimal
from datetime import date
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database.models import Base
from app.database.repositories.invoice_repo import InvoiceRepository
from app.finance.schemas import (
    InvoiceData,
    ExtractedField,
    SourceReference,
    ExtractionDetails,
    InvoiceLineItem,
    ValidationResult,
    ValidationIssue,
)


@pytest.fixture
def test_db():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)


def test_document_lifecycle_and_persistence(test_db):
    repo = InvoiceRepository(test_db)

    # 1. Create document record
    doc = repo.create_document_record(
        document_id="doc_db_1",
        filename="invoice_alpha.pdf",
        file_hash="hash_123",
        organization_id="org_alpha",
    )
    assert doc.id == "doc_db_1"
    assert doc.processing_status == "UPLOADED"

    # 2. Build invoice with line items, provenance, and validation issue
    src = SourceReference(
        document_id="doc_db_1",
        page_number=1,
        region_id="r1",
        bbox=[10, 20, 200, 50],
        original_text="Invoice: INV-991",
    )
    inv_data = InvoiceData(
        document_id="doc_db_1",
        organization_id="org_alpha",
        invoice_number=ExtractedField(name="invoice_number", value="INV-991", raw_value="INV-991", source=src),
        invoice_date=ExtractedField(name="invoice_date", value=date(2026, 3, 12), source=src),
        vendor_name_raw=ExtractedField(name="vendor_name_raw", value="AWS India Pvt Ltd", source=src),
        vendor_name_normalized="aws india",
        total_amount=ExtractedField(name="total_amount", value=Decimal("1180.00"), source=src),
        line_items=[
            InvoiceLineItem(line_number=1, description="Cloud compute", total=Decimal("1180.00"), source=src),
        ],
        validation=ValidationResult(
            is_valid=True,
            issues=[
                ValidationIssue(
                    issue_type="LOW_CONFIDENCE_WARNING",
                    severity="low",
                    message="Minor visual blur in header",
                    evidence=[src],
                )
            ],
        ),
    )

    # 3. Persist invoice
    saved_inv = repo.persist_invoice(inv_data, organization_id="org_alpha")
    assert saved_inv.id is not None
    assert saved_inv.invoice_number == "INV-991"
    assert saved_inv.total_amount == Decimal("1180.00")

    # Verify document status updated to PERSISTED
    updated_doc = repo.get_document_by_id("doc_db_1", organization_id="org_alpha")
    assert updated_doc.processing_status == "PERSISTED"

    # 4. Fetch invoice and verify relationships
    fetched = repo.get_invoice_by_id(saved_inv.id, organization_id="org_alpha")
    assert fetched is not None
    assert len(fetched.line_items) == 1
    assert fetched.line_items[0].description == "Cloud compute"
    assert len(fetched.validation_issues) == 1
    assert fetched.validation_issues[0].issue_type == "LOW_CONFIDENCE_WARNING"


def test_multi_tenant_isolation(test_db):
    repo = InvoiceRepository(test_db)

    # Tenant A
    repo.create_document_record(document_id="doc_org_a", filename="a.pdf", organization_id="tenant_a")
    inv_a = InvoiceData(
        document_id="doc_org_a",
        organization_id="tenant_a",
        invoice_number=ExtractedField(name="invoice_number", value="INV-A"),
        vendor_name_raw=ExtractedField(name="vendor_name_raw", value="Vendor A"),
        vendor_name_normalized="vendor a",
        total_amount=ExtractedField(name="total_amount", value=Decimal("500.00")),
    )
    repo.persist_invoice(inv_a, organization_id="tenant_a")

    # Tenant B
    repo.create_document_record(document_id="doc_org_b", filename="b.pdf", organization_id="tenant_b")
    inv_b = InvoiceData(
        document_id="doc_org_b",
        organization_id="tenant_b",
        invoice_number=ExtractedField(name="invoice_number", value="INV-B"),
        vendor_name_raw=ExtractedField(name="vendor_name_raw", value="Vendor B"),
        vendor_name_normalized="vendor b",
        total_amount=ExtractedField(name="total_amount", value=Decimal("900.00")),
    )
    repo.persist_invoice(inv_b, organization_id="tenant_b")

    # Tenant A must only see its own invoices!
    invoices_a, count_a = repo.list_invoices(organization_id="tenant_a")
    assert count_a == 1
    assert invoices_a[0].invoice_number == "INV-A"

    # Tenant B must only see its own invoices!
    invoices_b, count_b = repo.list_invoices(organization_id="tenant_b")
    assert count_b == 1
    assert invoices_b[0].invoice_number == "INV-B"

    # Cross-tenant direct query must return None
    cross_check = repo.get_invoice_by_id(invoices_a[0].id, organization_id="tenant_b")
    assert cross_check is None
