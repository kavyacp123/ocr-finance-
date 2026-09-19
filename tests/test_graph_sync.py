import pytest
from decimal import Decimal
from app.database.session import SessionLocal
from app.database.models import (
    DocumentModel,
    VendorModel,
    PurchaseOrderModel,
    InvoiceModel,
    PaymentModel,
    DocumentLinkModel,
)
from app.finance.graph.memory_adapter import NetworkXGraphAdapter
from app.finance.graph.sync_service import GraphSyncService
from scripts.seed_demo_data import seed as seed_data


@pytest.fixture
def db():
    session = SessionLocal()
    org_id = "test_graph_sync_org"
    for m in (DocumentLinkModel, PaymentModel, InvoiceModel, PurchaseOrderModel, VendorModel, DocumentModel):
        session.query(m).filter(m.organization_id == org_id).delete(synchronize_session=False)
    session.commit()
    yield session
    session.close()


def test_graph_sync_service_full_sync(db):
    org_id = "test_graph_sync_org"
    adapter = NetworkXGraphAdapter()
    sync = GraphSyncService(adapter)

    # 1. Seed Vendor
    v = VendorModel(
        id="ven_gs_1",
        organization_id=org_id,
        canonical_name="Alpha Tech Services",
        normalized_name="alpha tech services",
        tax_id="29ALPHA1234F1Z5",
        bank_account="9876543210",
        ifsc_swift="HDFC0001234",
    )
    db.add(v)

    # 2. Seed PO
    doc = DocumentModel(id="doc_gs_1", filename="test.pdf", organization_id=org_id)
    db.add(doc)

    po = PurchaseOrderModel(
        id="po_gs_1",
        document_id="doc_gs_1",
        organization_id=org_id,
        vendor_id="ven_gs_1",
        po_number="PO-ALPHA-01",
        total_amount=Decimal("12000.00"),
    )
    db.add(po)

    # 3. Seed Invoice
    inv = InvoiceModel(
        id="inv_gs_1",
        document_id="doc_gs_1",
        organization_id=org_id,
        vendor_id="ven_gs_1",
        invoice_number="INV-ALPHA-01",
        po_number="PO-ALPHA-01",
        total_amount=Decimal("12000.00"),
        payment_status="paid",
    )
    db.add(inv)

    link = DocumentLinkModel(
        id="link_gs_1",
        organization_id=org_id,
        link_type="INVOICE_TO_PO",
        source_type="INVOICE",
        source_id="inv_gs_1",
        target_type="PURCHASE_ORDER",
        target_id="po_gs_1",
        match_type="EXACT_IDENTIFIER",
        status="LINKED",
    )
    db.add(link)

    # 4. Seed Payment
    pay = PaymentModel(
        id="pay_gs_1",
        organization_id=org_id,
        payment_reference="UTR-ALPHA-99",
        amount=Decimal("12000.00"),
        bank_account="9876543210",
    )
    db.add(pay)

    pay_link = DocumentLinkModel(
        id="link_pay_gs_1",
        organization_id=org_id,
        link_type="PAYMENT_TO_INVOICE",
        source_type="PAYMENT",
        source_id="pay_gs_1",
        target_type="INVOICE",
        target_id="inv_gs_1",
        match_type="EXACT_IDENTIFIER",
        status="LINKED",
    )
    db.add(pay_link)
    db.commit()

    # Perform full sync
    res = sync.sync_all(organization_id=org_id, db=db)
    assert res["synced_vendors"] == 1
    assert res["synced_pos"] == 1
    assert res["synced_invoices"] == 1
    assert res["synced_payments"] == 1

    # Verify Graph nodes and edges
    stats = adapter.get_stats(organization_id=org_id)
    assert stats.total_nodes >= 5  # Vendor, TaxId, BankAccount, PO, Invoice, Payment
    assert "Vendor" in stats.nodes_by_label
    assert "Invoice" in stats.nodes_by_label
    assert "PurchaseOrder" in stats.nodes_by_label
    assert "Payment" in stats.nodes_by_label

    assert "ISSUED" in stats.edges_by_type
    assert "REFERENCES_PO" in stats.edges_by_type
    assert "APPLIED_TO" in stats.edges_by_type
    assert "USES_BANK_ACCOUNT" in stats.edges_by_type


def test_mock_finance_seed_persists_graph_ready_relations(db):
    org_id = "org_default"

    for m in (DocumentLinkModel, PaymentModel, InvoiceModel, PurchaseOrderModel, VendorModel, DocumentModel):
        db.query(m).filter(m.organization_id == org_id).delete(synchronize_session=False)
    db.commit()

    seed_data()

    assert db.query(VendorModel).filter(VendorModel.organization_id == org_id).count() >= 3
    assert db.query(InvoiceModel).filter(
        InvoiceModel.organization_id == org_id,
        InvoiceModel.vendor_id.isnot(None),
    ).count() >= 8
    assert db.query(PurchaseOrderModel).filter(
        PurchaseOrderModel.organization_id == org_id,
        PurchaseOrderModel.vendor_id.isnot(None),
    ).count() >= 4
    assert db.query(DocumentLinkModel).filter(DocumentLinkModel.organization_id == org_id).count() >= 4
