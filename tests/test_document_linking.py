import json
from decimal import Decimal
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database.models import (
    Base,
    DocumentModel,
    InvoiceModel,
    PurchaseOrderModel,
    PaymentModel,
    DocumentLinkModel,
)
from app.finance.linking.document_linker import DocumentLinker
from app.database.repositories.payment_repo import PaymentRepository
from app.finance.schemas import PaymentRecord


@pytest.fixture
def db():
    engine = create_engine('sqlite:///:memory:')
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()

    # Create dummy document record
    doc = DocumentModel(id='doc_link_test', filename='test.pdf', processing_status='COMPLETED')
    session.add(doc)
    session.commit()

    yield session
    session.close()


def test_link_invoice_to_po_exact_match(db):
    linker = DocumentLinker(tolerance=Decimal('1.00'))
    org_id = 'org_test'

    # Create PO: PO-1001 with total 10000.00
    po = PurchaseOrderModel(
        id='po_1001',
        document_id='doc_link_test',
        organization_id=org_id,
        po_number='PO-1001',
        total_amount=Decimal('10000.00'),
    )
    db.add(po)
    db.commit()

    # Link Invoice with same amount
    link = linker.link_invoice_to_po(
        db=db,
        invoice_id='inv_01',
        po_number='PO-1001',
        invoice_total=Decimal('10000.00'),
        organization_id=org_id,
    )

    assert link is not None
    assert link.status == 'LINKED'
    assert link.target_id == 'po_1001'
    assert link.match_type == 'EXACT_IDENTIFIER'
    assert link.discrepancy_details is None


def test_link_invoice_to_po_amount_discrepancy(db):
    linker = DocumentLinker(tolerance=Decimal('1.00'))
    org_id = 'org_test'

    po = PurchaseOrderModel(
        id='po_1002',
        document_id='doc_link_test',
        organization_id=org_id,
        po_number='PO-1002',
        total_amount=Decimal('10000.00'),
    )
    db.add(po)
    db.commit()

    # Invoice has total 12000.00 (variance of 2000.00)
    link = linker.link_invoice_to_po(
        db=db,
        invoice_id='inv_02',
        po_number='PO-1002',
        invoice_total=Decimal('12000.00'),
        organization_id=org_id,
    )

    assert link is not None
    assert link.status == 'DISCREPANCY'
    assert link.target_id == 'po_1002'

    disc = json.loads(link.discrepancy_details)
    assert disc['issue'] == 'PO_AMOUNT_MISMATCH'
    assert disc['difference'] == '2000.00'
    assert disc['expected'] == '10000.00'
    assert disc['actual'] == '12000.00'


def test_link_invoice_to_po_unresolved(db):
    linker = DocumentLinker()
    org_id = 'org_test'

    # PO-NOT-EXIST does not exist yet in DB
    link = linker.link_invoice_to_po(
        db=db,
        invoice_id='inv_unresolved',
        po_number='PO-NOT-EXIST',
        invoice_total=Decimal('5000.00'),
        organization_id=org_id,
    )

    assert link is not None
    assert link.status == 'UNRESOLVED'
    assert link.target_id is None
    assert link.match_type == 'UNRESOLVED_REFERENCE'
    disc = json.loads(link.discrepancy_details)
    assert disc['issue'] == 'MISSING_PURCHASE_ORDER'


def test_retroactive_po_linking(db):
    linker = DocumentLinker(tolerance=Decimal('1.00'))
    org_id = 'org_test'

    # 1. Invoice arrives first referencing PO-FUTURE
    inv = InvoiceModel(
        id='inv_early',
        document_id='doc_link_test',
        organization_id=org_id,
        invoice_number='INV-EARLY-01',
        po_number='PO-FUTURE',
        total_amount=Decimal('25000.00'),
    )
    db.add(inv)
    db.commit()

    # Link created before PO exists
    linker.link_invoice_to_po(
        db=db,
        invoice_id=inv.id,
        po_number='PO-FUTURE',
        invoice_total=inv.total_amount,
        organization_id=org_id,
    )

    # 2. Later, PO-FUTURE is uploaded
    po = PurchaseOrderModel(
        id='po_future',
        document_id='doc_link_test',
        organization_id=org_id,
        po_number='PO-FUTURE',
        total_amount=Decimal('25000.00'),
    )
    db.add(po)
    db.commit()

    # Trigger retroactive linking
    resolved = linker.link_po_retroactively(
        db=db,
        po_id=po.id,
        po_number='PO-FUTURE',
        po_total=po.total_amount,
        organization_id=org_id,
    )

    assert len(resolved) == 1
    assert resolved[0].status == 'LINKED'
    assert resolved[0].target_id == po.id


def test_payment_to_invoice_linking_and_status_progression(db):
    linker = DocumentLinker(tolerance=Decimal('1.00'))
    pay_repo = PaymentRepository(db)
    org_id = 'org_test'

    # Create invoice for 10000.00
    inv = InvoiceModel(
        id='inv_pay_test',
        document_id='doc_link_test',
        organization_id=org_id,
        invoice_number='INV-PAY-01',
        total_amount=Decimal('10000.00'),
        payment_status='unpaid',
    )
    db.add(inv)
    db.commit()

    # 1. Partial payment: 4000.00
    p1 = pay_repo.create_payment(
        payment_data=PaymentRecord(
            payment_reference='UTR-001',
            amount=Decimal('4000.00'),
            referenced_invoice_numbers=['INV-PAY-01'],
        ),
        organization_id=org_id,
    )
    linker.link_payment_to_invoices(
        db=db,
        payment_id=p1.id,
        referenced_invoice_numbers=['INV-PAY-01'],
        payment_amount=Decimal('4000.00'),
        organization_id=org_id,
    )

    db.refresh(inv)
    assert inv.payment_status == 'partially_paid'

    # 2. Remaining payment: 6000.00 (Total 10000.00)
    p2 = pay_repo.create_payment(
        payment_data=PaymentRecord(
            payment_reference='UTR-002',
            amount=Decimal('6000.00'),
            referenced_invoice_numbers=['INV-PAY-01'],
        ),
        organization_id=org_id,
    )
    linker.link_payment_to_invoices(
        db=db,
        payment_id=p2.id,
        referenced_invoice_numbers=['INV-PAY-01'],
        payment_amount=Decimal('6000.00'),
        organization_id=org_id,
    )

    db.refresh(inv)
    assert inv.payment_status == 'paid'

    # 3. Excess payment: 500.00 (Total 10500.00 -> overpaid)
    p3 = pay_repo.create_payment(
        payment_data=PaymentRecord(
            payment_reference='UTR-003',
            amount=Decimal('500.00'),
            referenced_invoice_numbers=['INV-PAY-01'],
        ),
        organization_id=org_id,
    )
    linker.link_payment_to_invoices(
        db=db,
        payment_id=p3.id,
        referenced_invoice_numbers=['INV-PAY-01'],
        payment_amount=Decimal('500.00'),
        organization_id=org_id,
    )

    db.refresh(inv)
    assert inv.payment_status == 'overpaid'
