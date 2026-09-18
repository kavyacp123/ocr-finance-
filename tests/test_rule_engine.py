import pytest
from decimal import Decimal
from app.database.session import SessionLocal
from app.database.models import (
    DocumentModel,
    InvoiceModel,
    DocumentLinkModel,
    RuleViolationModel,
)
from app.finance.analytics.rule_engine import RuleEngine


@pytest.fixture
def db():
    session = SessionLocal()
    org_id = "test_rule_engine_org"
    # Cleanup
    for m in (RuleViolationModel, DocumentLinkModel, InvoiceModel, DocumentModel):
        session.query(m).filter(m.organization_id == org_id).delete(synchronize_session=False)
    session.commit()
    yield session
    session.close()


def test_rule_invoice_without_po(db):
    org_id = "test_rule_engine_org"
    doc = DocumentModel(id="doc_re_1", filename="test.pdf", organization_id=org_id)
    db.add(doc)
    inv = InvoiceModel(
        id="inv_re_1",
        document_id="doc_re_1",
        organization_id=org_id,
        invoice_number="INV-NO-PO",
        po_number=None,
        total_amount=Decimal("100.00"),
        payment_status="unpaid",
    )
    db.add(inv)
    db.commit()

    engine = RuleEngine()
    violations = engine.evaluate_invoice(inv, db)
    rule_ids = [v.rule_id for v in violations]
    assert "INVOICE_WITHOUT_PO" in rule_ids


def test_rule_po_link_unresolved(db):
    org_id = "test_rule_engine_org"
    doc = DocumentModel(id="doc_re_2", filename="test.pdf", organization_id=org_id)
    db.add(doc)
    inv = InvoiceModel(
        id="inv_re_2",
        document_id="doc_re_2",
        organization_id=org_id,
        invoice_number="INV-WITH-PO",
        po_number="PO-9999",
        total_amount=Decimal("100.00"),
        payment_status="unpaid",
    )
    db.add(inv)
    link = DocumentLinkModel(
        id="link_re_2",
        organization_id=org_id,
        link_type="INVOICE_TO_PO",
        source_type="INVOICE",
        source_id="inv_re_2",
        target_type="PURCHASE_ORDER",
        target_id=None,
        match_type="UNRESOLVED_REFERENCE",
        status="UNRESOLVED",
    )
    db.add(link)
    db.commit()

    engine = RuleEngine()
    violations = engine.evaluate_invoice(inv, db)
    rule_ids = [v.rule_id for v in violations]
    assert "INVOICE_PO_LINK_UNRESOLVED" in rule_ids


def test_rule_po_amount_mismatch(db):
    org_id = "test_rule_engine_org"
    doc = DocumentModel(id="doc_re_3", filename="test.pdf", organization_id=org_id)
    db.add(doc)
    inv = InvoiceModel(
        id="inv_re_3",
        document_id="doc_re_3",
        organization_id=org_id,
        invoice_number="INV-MISMATCH",
        po_number="PO-1234",
        total_amount=Decimal("2000.00"),
        payment_status="unpaid",
    )
    db.add(inv)
    link = DocumentLinkModel(
        id="link_re_3",
        organization_id=org_id,
        link_type="INVOICE_TO_PO",
        source_type="INVOICE",
        source_id="inv_re_3",
        target_type="PURCHASE_ORDER",
        target_id="po_re_3",
        match_type="EXACT_IDENTIFIER",
        status="DISCREPANCY",
        discrepancy_details='{"reason": "PO_AMOUNT_MISMATCH"}',
    )
    db.add(link)
    db.commit()

    engine = RuleEngine()
    violations = engine.evaluate_invoice(inv, db)
    rule_ids = [v.rule_id for v in violations]
    assert "INVOICE_PO_AMOUNT_MISMATCH" in rule_ids


def test_rule_invoice_overpaid(db):
    org_id = "test_rule_engine_org"
    doc = DocumentModel(id="doc_re_4", filename="test.pdf", organization_id=org_id)
    db.add(doc)
    inv = InvoiceModel(
        id="inv_re_4",
        document_id="doc_re_4",
        organization_id=org_id,
        invoice_number="INV-OVERPAID",
        po_number="PO-1234",
        total_amount=Decimal("100.00"),
        payment_status="overpaid",
    )
    db.add(inv)
    db.commit()

    engine = RuleEngine()
    violations = engine.evaluate_invoice(inv, db)
    rule_ids = [v.rule_id for v in violations]
    assert "PAYMENT_EXCEEDS_INVOICE" in rule_ids


def test_rule_zero_or_negative_amount(db):
    org_id = "test_rule_engine_org"
    doc = DocumentModel(id="doc_re_5", filename="test.pdf", organization_id=org_id)
    db.add(doc)
    inv = InvoiceModel(
        id="inv_re_5",
        document_id="doc_re_5",
        organization_id=org_id,
        invoice_number="INV-ZERO",
        po_number="PO-1234",
        total_amount=Decimal("0.00"),
        payment_status="unpaid",
    )
    db.add(inv)
    db.commit()

    engine = RuleEngine()
    violations = engine.evaluate_invoice(inv, db)
    rule_ids = [v.rule_id for v in violations]
    assert "ZERO_OR_NEGATIVE_AMOUNT" in rule_ids
