import pytest
from decimal import Decimal
from fastapi.testclient import TestClient

from app.main import app
from app.database.session import SessionLocal
from app.database.models import (
    DocumentModel,
    InvoiceModel,
    RuleViolationModel,
    DuplicateCandidateModel,
    AnomalyFlagModel,
)


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


def test_analytics_endpoints_and_dashboard(client):
    org_id = "test_analytics_api_org"
    db = SessionLocal()

    # Teardown
    for m in (RuleViolationModel, DuplicateCandidateModel, AnomalyFlagModel, InvoiceModel, DocumentModel):
        db.query(m).filter(m.organization_id == org_id).delete(synchronize_session=False)
    db.commit()

    # Seed data
    doc = DocumentModel(id="doc_an_api_1", filename="test.pdf", organization_id=org_id)
    db.add(doc)

    inv = InvoiceModel(
        id="inv_an_api_1",
        document_id="doc_an_api_1",
        organization_id=org_id,
        invoice_number="INV-AN-100",
        total_amount=Decimal("15000.00"),
        payment_status="unpaid",
    )
    db.add(inv)

    rv = RuleViolationModel(
        id="rv_an_api_1",
        organization_id=org_id,
        rule_id="INVOICE_WITHOUT_PO",
        rule_name="Invoice Without Purchase Order",
        severity="WARNING",
        entity_type="INVOICE",
        entity_id="inv_an_api_1",
        status="OPEN",
    )
    db.add(rv)

    dup = DuplicateCandidateModel(
        id="dup_an_api_1",
        organization_id=org_id,
        entity_type="INVOICE",
        primary_entity_id="inv_an_api_1",
        duplicate_of_entity_id="inv_an_api_old",
        match_type="EXACT",
        status="OPEN",
    )
    db.add(dup)

    anom = AnomalyFlagModel(
        id="anm_an_api_1",
        organization_id=org_id,
        entity_type="INVOICE",
        entity_id="inv_an_api_1",
        anomaly_type="HIGH_AMOUNT",
        observed_value=Decimal("15000.00"),
        status="OPEN",
    )
    db.add(anom)
    db.commit()
    db.close()

    # 1. Test GET /analytics/dashboard
    res_dash = client.get(f"/analytics/dashboard?organization_id={org_id}")
    assert res_dash.status_code == 200
    dash = res_dash.json()
    assert dash["total_invoices"] == 1
    assert dash["open_violations_count"] == 1
    assert dash["open_duplicates_count"] == 1
    assert dash["open_anomalies_count"] == 1
    assert dash["total_invoice_spend"] == 15000.0

    # 2. Test GET /analytics/rule-violations
    res_rv = client.get(f"/analytics/rule-violations?organization_id={org_id}")
    assert res_rv.status_code == 200
    rv_json = res_rv.json()
    assert rv_json["total_count"] == 1
    assert rv_json["violations"][0]["rule_id"] == "INVOICE_WITHOUT_PO"

    # 3. Test GET /analytics/duplicates
    res_dup = client.get(f"/analytics/duplicates?organization_id={org_id}")
    assert res_dup.status_code == 200
    dup_json = res_dup.json()
    assert dup_json["total_count"] == 1
    assert dup_json["duplicates"][0]["entity_type"] == "INVOICE"

    # 4. Test GET /analytics/anomalies
    res_an = client.get(f"/analytics/anomalies?organization_id={org_id}")
    assert res_an.status_code == 200
    an_json = res_an.json()
    assert an_json["total_count"] == 1
    assert an_json["anomalies"][0]["anomaly_type"] == "HIGH_AMOUNT"
