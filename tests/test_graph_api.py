import pytest
from decimal import Decimal
from fastapi.testclient import TestClient

from app.main import app
from app.database.session import SessionLocal
from app.database.models import (
    DocumentModel,
    VendorModel,
    PurchaseOrderModel,
    InvoiceModel,
    PaymentModel,
    DocumentLinkModel,
)


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


def test_graph_api_endpoints(client):
    org_id = "test_graph_api_org"
    db = SessionLocal()

    # Teardown
    for m in (DocumentLinkModel, PaymentModel, InvoiceModel, PurchaseOrderModel, VendorModel, DocumentModel):
        db.query(m).filter(m.organization_id == org_id).delete(synchronize_session=False)
    db.commit()

    # Seed Vendor 1 & 2 sharing bank account "BANK-SHARED-999"
    v1 = VendorModel(
        id="ven_gapi_1",
        organization_id=org_id,
        canonical_name="First Vendor Corp",
        normalized_name="first vendor corp",
        bank_account="BANK-SHARED-999",
    )
    db.add(v1)

    v2 = VendorModel(
        id="ven_gapi_2",
        organization_id=org_id,
        canonical_name="Second Vendor Corp",
        normalized_name="second vendor corp",
        bank_account="BANK-SHARED-999",
    )
    db.add(v2)

    doc = DocumentModel(id="doc_gapi_1", filename="test.pdf", organization_id=org_id)
    db.add(doc)

    po = PurchaseOrderModel(
        id="po_gapi_1",
        document_id="doc_gapi_1",
        organization_id=org_id,
        vendor_id="ven_gapi_1",
        po_number="PO-GAPI-01",
        total_amount=Decimal("5000.00"),
    )
    db.add(po)

    inv = InvoiceModel(
        id="inv_gapi_1",
        document_id="doc_gapi_1",
        organization_id=org_id,
        vendor_id="ven_gapi_1",
        invoice_number="INV-GAPI-01",
        po_number="PO-GAPI-01",
        total_amount=Decimal("5000.00"),
    )
    db.add(inv)

    link = DocumentLinkModel(
        id="link_gapi_1",
        organization_id=org_id,
        link_type="INVOICE_TO_PO",
        source_type="INVOICE",
        source_id="inv_gapi_1",
        target_type="PURCHASE_ORDER",
        target_id="po_gapi_1",
        match_type="EXACT_IDENTIFIER",
        status="LINKED",
    )
    db.add(link)
    db.commit()
    db.close()

    # 1. POST /graph/sync
    res_sync = client.post(f"/graph/sync?organization_id={org_id}")
    assert res_sync.status_code == 200
    sync_data = res_sync.json()
    assert sync_data["status"] == "SUCCESS"
    assert sync_data["synced_vendors"] == 2
    assert sync_data["synced_pos"] == 1
    assert sync_data["synced_invoices"] == 1

    # 2. GET /graph/stats
    res_stats = client.get(f"/graph/stats?organization_id={org_id}")
    assert res_stats.status_code == 200
    stats = res_stats.json()
    assert stats["total_nodes"] >= 4
    assert stats["total_edges"] >= 3

    # 3. GET /graph/trace/{invoice_id}
    res_trace = client.get(f"/graph/trace/inv_gapi_1?depth=2")
    assert res_trace.status_code == 200
    trace = res_trace.json()
    node_ids = {n["id"] for n in trace["nodes"]}
    assert "inv_gapi_1" in node_ids
    assert "po_gapi_1" in node_ids
    assert "ven_gapi_1" in node_ids

    # 4. GET /graph/vendor/{vendor_id}/network
    res_vnet = client.get(f"/graph/vendor/ven_gapi_1/network?depth=2")
    assert res_vnet.status_code == 200
    vnet = res_vnet.json()
    vnet_node_ids = {n["id"] for n in vnet["nodes"]}
    assert "ven_gapi_1" in vnet_node_ids
    assert "inv_gapi_1" in vnet_node_ids

    # 5. GET /graph/shared-entities
    res_shared = client.get("/graph/shared-entities?target_type=BankAccount&min_connections=2")
    assert res_shared.status_code == 200
    shared = res_shared.json()
    assert shared["total_shared_entities"] >= 1
    shared_bank = next((s for s in shared["results"] if s["shared_node_id"] == "bank_BANK-SHARED-999"), None)
    assert shared_bank is not None
    assert set(shared_bank["connected_entity_ids"]) == {"ven_gapi_1", "ven_gapi_2"}
