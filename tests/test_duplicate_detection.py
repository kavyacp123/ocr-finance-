import pytest
from decimal import Decimal
from app.database.session import SessionLocal
from app.database.models import (
    DocumentModel,
    InvoiceModel,
    PaymentModel,
    DuplicateCandidateModel,
    RuleViolationModel,
)
from app.finance.analytics.duplicate_detector import DuplicateDetector


@pytest.fixture
def db():
    session = SessionLocal()
    org_id = "test_dup_org"
    for m in (RuleViolationModel, DuplicateCandidateModel, InvoiceModel, PaymentModel, DocumentModel):
        session.query(m).filter(m.organization_id == org_id).delete(synchronize_session=False)
    session.commit()
    yield session
    session.close()


def test_duplicate_invoice_detection(db):
    org_id = "test_dup_org"
    doc = DocumentModel(id="doc_dup_1", filename="test.pdf", organization_id=org_id)
    db.add(doc)

    # First invoice
    inv1 = InvoiceModel(
        id="inv_dup_1",
        document_id="doc_dup_1",
        organization_id=org_id,
        invoice_number="INV-DUP-100",
        vendor_name_raw="Acme Corp",
        total_amount=Decimal("500.00"),
    )
    db.add(inv1)
    db.commit()

    # Second invoice with same invoice_number and same vendor
    inv2 = InvoiceModel(
        id="inv_dup_2",
        document_id="doc_dup_1",
        organization_id=org_id,
        invoice_number="INV-DUP-100",
        vendor_name_raw="Acme Corp",
        total_amount=Decimal("500.00"),
    )
    db.add(inv2)
    db.commit()

    detector = DuplicateDetector()
    dup = detector.check_invoice(inv2, db)

    assert dup is not None
    assert dup.entity_type == "INVOICE"
    assert dup.primary_entity_id == "inv_dup_2"
    assert dup.duplicate_of_entity_id == "inv_dup_1"
    assert dup.match_type == "EXACT"

    # Also verify rule violation was created
    rv = (
        db.query(RuleViolationModel)
        .filter(
            RuleViolationModel.organization_id == org_id,
            RuleViolationModel.entity_id == "inv_dup_2",
            RuleViolationModel.rule_id == "DUPLICATE_DETECTED",
        )
        .first()
    )
    assert rv is not None


def test_duplicate_payment_detection(db):
    org_id = "test_dup_org"

    pay1 = PaymentModel(
        id="pay_dup_1",
        organization_id=org_id,
        payment_reference="UTR-DUP-999",
        amount=Decimal("1500.00"),
    )
    db.add(pay1)
    db.commit()

    pay2 = PaymentModel(
        id="pay_dup_2",
        organization_id=org_id,
        payment_reference="UTR-DUP-999",
        amount=Decimal("1500.00"),
    )
    db.add(pay2)
    db.commit()

    detector = DuplicateDetector()
    dup = detector.check_payment(pay2, db)

    assert dup is not None
    assert dup.entity_type == "PAYMENT"
    assert dup.primary_entity_id == "pay_dup_2"
    assert dup.duplicate_of_entity_id == "pay_dup_1"
    assert dup.match_type == "EXACT"


def test_non_duplicate_invoice(db):
    org_id = "test_dup_org"
    doc = DocumentModel(id="doc_dup_unique", filename="test.pdf", organization_id=org_id)
    db.add(doc)

    inv = InvoiceModel(
        id="inv_unique_1",
        document_id="doc_dup_unique",
        organization_id=org_id,
        invoice_number="INV-UNIQUE-1",
        vendor_name_raw="Unique Vendor",
        total_amount=Decimal("300.00"),
    )
    db.add(inv)
    db.commit()

    detector = DuplicateDetector()
    dup = detector.check_invoice(inv, db)
    assert dup is None
