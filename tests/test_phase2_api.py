import pytest
from decimal import Decimal
from fastapi.testclient import TestClient

from app.main import app
from app.database.session import SessionLocal
from app.database.models import (
    Base,
    DocumentModel,
    InvoiceModel,
    PurchaseOrderModel,
    VendorModel,
    VendorAliasModel,
)


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


def test_phase2_vendor_and_po_and_payment_api(client):
    org_id = 'test_api_p2'
    db = SessionLocal()

    # ── Teardown: remove any stale rows from a previous run so the test is idempotent ──
    from app.database.models import PaymentModel, DocumentLinkModel, PossibleEntityMatchModel
    for model in (
        DocumentLinkModel,
        PaymentModel,
        InvoiceModel,
        PurchaseOrderModel,
        PossibleEntityMatchModel,
        VendorAliasModel,
        VendorModel,
        DocumentModel,
    ):
        db.query(model).filter(model.organization_id == org_id).delete(synchronize_session=False)
    db.commit()

    # ── Seed: Document, Vendor, Alias, PO, Invoice ───────────────────────────────────
    doc = DocumentModel(id='doc_p2_seed', filename='test.pdf', organization_id=org_id)
    db.add(doc)

    vendor = VendorModel(
        id='ven_p2_01',
        organization_id=org_id,
        canonical_name='CloudScale Technologies India Pvt Ltd',
        normalized_name='cloudscale technologies india',
        tax_id='29AABCC1234F1Z1',
    )
    db.add(vendor)

    alias = VendorAliasModel(
        vendor_id='ven_p2_01',
        organization_id=org_id,
        alias_name='CloudScale Inc',
        normalized_alias='cloudscale',
    )
    db.add(alias)

    po = PurchaseOrderModel(
        id='po_p2_01',
        document_id='doc_p2_seed',
        organization_id=org_id,
        vendor_id='ven_p2_01',
        po_number='PO-CLOUD-01',
        total_amount=Decimal('50000.00'),
        vendor_name_raw='CloudScale Technologies India Pvt Ltd',
    )
    db.add(po)

    inv = InvoiceModel(
        id='inv_p2_01',
        document_id='doc_p2_seed',
        organization_id=org_id,
        vendor_id='ven_p2_01',
        invoice_number='INV-CLOUD-01',
        po_number='PO-CLOUD-01',
        total_amount=Decimal('50000.00'),
        vendor_name_raw='CloudScale Technologies India Pvt Ltd',
        payment_status='unpaid',
    )
    db.add(inv)
    db.commit()
    db.close()

    # 1. Test GET /vendors
    res = client.get(f'/vendors?organization_id={org_id}')
    assert res.status_code == 200
    v_data = res.json()
    assert v_data['total_count'] >= 1
    assert any(v['canonical_name'] == 'CloudScale Technologies India Pvt Ltd' for v in v_data['vendors'])

    # 2. Test GET /vendors/{id}
    res_v = client.get(f'/vendors/ven_p2_01?organization_id={org_id}')
    assert res_v.status_code == 200
    assert res_v.json()['canonical_name'] == 'CloudScale Technologies India Pvt Ltd'
    assert 'CloudScale Inc' in res_v.json()['aliases']

    # 3. Test GET /purchase-orders
    res_po = client.get(f'/purchase-orders?organization_id={org_id}')
    assert res_po.status_code == 200
    po_list = res_po.json()
    assert po_list['total_count'] >= 1
    assert any(p['po_number'] == 'PO-CLOUD-01' for p in po_list['purchase_orders'])

    # 4. Test POST /finance/payments
    pay_payload = {
        'payment_reference': 'UTR-API-TEST-001',
        'payment_date': '2026-03-15',
        'amount': 50000.00,
        'currency': 'INR',
        'payment_method': 'NEFT',
        'payer_name': 'Our Company',
        'payee_name': 'CloudScale Technologies',
        'referenced_invoice_numbers': ['INV-CLOUD-01'],
    }
    res_pay = client.post(f'/finance/payments?organization_id={org_id}', json=pay_payload)
    assert res_pay.status_code == 200
    pay_resp = res_pay.json()
    assert pay_resp['payment_reference'] == 'UTR-API-TEST-001'
    assert pay_resp['linked_invoices_count'] == 1

    # 5. Test GET /payments
    res_pays = client.get(f'/payments?organization_id={org_id}')
    assert res_pays.status_code == 200
    assert res_pays.json()['total_count'] >= 1

    # 6. Test GET /invoices/{id}/graph
    res_graph = client.get(f'/invoices/inv_p2_01/graph?organization_id={org_id}')
    assert res_graph.status_code == 200
    graph = res_graph.json()
    assert graph['invoice']['invoice_number'] == 'INV-CLOUD-01'
    assert graph['invoice']['payment_status'] == 'paid'
    assert graph['invoice']['total_paid'] == 50000.00
    assert graph['invoice']['balance_due'] == 0.00
    assert graph['vendor']['canonical_name'] == 'CloudScale Technologies India Pvt Ltd'
    assert len(graph['payments']) == 1
    assert graph['payments'][0]['payment_reference'] == 'UTR-API-TEST-001'
