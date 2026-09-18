import pytest
from datetime import date
from decimal import Decimal
from fastapi.testclient import TestClient

from app.main import app
from app.database.session import SessionLocal
from app.database.models import InvoiceModel, VendorModel, VendorAliasModel, DocumentModel


@pytest.fixture
def copilot_api_client():
    with TestClient(app) as client:
        db = SessionLocal()
        org_id = "org_copilot_api_test"

    # Clean up
    db.query(VendorAliasModel).filter(VendorAliasModel.organization_id == org_id).delete()
    db.query(InvoiceModel).filter(InvoiceModel.organization_id == org_id).delete()
    db.query(DocumentModel).filter(DocumentModel.organization_id == org_id).delete()
    db.query(VendorModel).filter(VendorModel.organization_id == org_id).delete()
    db.commit()

    doc1 = DocumentModel(id="doc_api1", organization_id=org_id, filename="doc1.pdf")
    doc2 = DocumentModel(id="doc_api2", organization_id=org_id, filename="doc2.pdf")
    db.add_all([doc1, doc2])
    db.commit()

    v = VendorModel(
        organization_id=org_id,
        canonical_name="Amazon Web Services Inc",
        normalized_name="amazon web services inc",
    )
    db.add(v)
    db.commit()
    db.refresh(v)

    alias = VendorAliasModel(
        organization_id=org_id,
        vendor_id=v.id,
        alias_name="AWS",
        normalized_alias="aws",
    )
    db.add(alias)

    inv1 = InvoiceModel(
        organization_id=org_id,
        document_id=doc1.id,
        vendor_id=v.id,
        invoice_number="INV-AWS-001",
        invoice_date=date(2026, 4, 15),
        total_amount=Decimal("25000.00"),
        amount_due=Decimal("0.00"),
        payment_status="PAID",
    )
    inv2 = InvoiceModel(
        organization_id=org_id,
        document_id=doc2.id,
        vendor_id=v.id,
        invoice_number="INV-AWS-002",
        invoice_date=date(2026, 5, 20),
        total_amount=Decimal("35000.00"),
        amount_due=Decimal("35000.00"),
        payment_status="UNPAID",
    )
    db.add_all([inv1, inv2])
    db.commit()

    yield client, org_id, v

    db.query(VendorAliasModel).filter(VendorAliasModel.organization_id == org_id).delete()
    db.query(InvoiceModel).filter(InvoiceModel.organization_id == org_id).delete()
    db.query(DocumentModel).filter(DocumentModel.organization_id == org_id).delete()
    db.query(VendorModel).filter(VendorModel.organization_id == org_id).delete()
    db.commit()
    db.close()


def test_copilot_ask_vendor_spend(copilot_api_client):
    client, org_id, _ = copilot_api_client

    response = client.post(
        "/copilot/ask",
        json={
            "question": "How much did we spend with AWS in Q2 2026?",
            "organization_id": org_id,
            "include_query_plan": True,
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert data["intent"] == "VENDOR_SPEND"
    assert "60000.00" in data["answer"]
    assert data["confidence"] > 0.5
    assert len(data["evidence"]) >= 1
    assert data["query_plan"]["intent"] == "VENDOR_SPEND"
    # Context returned
    assert "context" in data
    assert data["context"]["last_intent"] == "VENDOR_SPEND"


def test_copilot_ask_unpaid_invoices(copilot_api_client):
    client, org_id, _ = copilot_api_client

    response = client.post(
        "/ask",
        json={
            "question": "Show all unpaid invoices",
            "organization_id": org_id,
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert data["intent"] == "UNPAID_INVOICES"
    assert "INV-AWS-002" in data["answer"]
    assert len(data["metrics"]) >= 1


def test_copilot_ask_conversational_follow_up(copilot_api_client):
    client, org_id, _ = copilot_api_client

    # First question
    res1 = client.post(
        "/copilot/ask",
        json={
            "question": "How much did we spend with AWS in Q2 2026?",
            "organization_id": org_id,
        },
    )
    assert res1.status_code == 200
    ctx = res1.json()["context"]

    # Follow-up referencing "their unpaid invoices"
    res2 = client.post(
        "/copilot/ask",
        json={
            "question": "Show their unpaid invoices",
            "organization_id": org_id,
            "context": ctx,
        },
    )
    assert res2.status_code == 200
    data2 = res2.json()
    assert "INV-AWS-002" in data2["answer"]
