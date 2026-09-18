import pytest
from datetime import date
from decimal import Decimal
from fastapi.testclient import TestClient

from app.main import app
from app.database.session import SessionLocal
from app.database.models import (
    InvoiceModel,
    InvoiceLineItemModel,
    VendorModel,
    VendorAliasModel,
    DocumentModel,
)


@pytest.fixture
def investigate_client():
    with TestClient(app) as client:
        db = SessionLocal()
        org_id = "org_inv_api_test"

        db.query(InvoiceLineItemModel).filter(InvoiceLineItemModel.organization_id == org_id).delete()
        db.query(InvoiceModel).filter(InvoiceModel.organization_id == org_id).delete()
        db.query(DocumentModel).filter(DocumentModel.organization_id == org_id).delete()
        db.query(VendorAliasModel).filter(VendorAliasModel.organization_id == org_id).delete()
        db.query(VendorModel).filter(VendorModel.organization_id == org_id).delete()
        db.commit()

        v = VendorModel(
            organization_id=org_id,
            canonical_name="AWS Cloud Services",
            normalized_name="aws cloud services",
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

        doc1 = DocumentModel(id="doc_inv_1", organization_id=org_id, filename="july.pdf")
        doc2 = DocumentModel(id="doc_inv_2", organization_id=org_id, filename="aug.pdf")
        db.add_all([doc1, doc2])
        db.commit()

        inv1 = InvoiceModel(
            organization_id=org_id,
            document_id=doc1.id,
            vendor_id=v.id,
            invoice_number="INV-J-01",
            invoice_date=date(2026, 7, 10),
            total_amount=Decimal("5000.00"),
            payment_status="PAID",
        )
        inv2 = InvoiceModel(
            organization_id=org_id,
            document_id=doc2.id,
            vendor_id=v.id,
            invoice_number="INV-A-01",
            invoice_date=date(2026, 8, 10),
            total_amount=Decimal("9000.00"),
            payment_status="UNPAID",
        )
        db.add_all([inv1, inv2])
        db.flush()

        line1 = InvoiceLineItemModel(
            organization_id=org_id,
            invoice_id=inv1.id,
            line_number=1,
            description="Cloud Hosting",
            quantity=Decimal("10"),
            unit_price=Decimal("500.00"),
            total=Decimal("5000.00"),
        )
        line2 = InvoiceLineItemModel(
            organization_id=org_id,
            invoice_id=inv2.id,
            line_number=1,
            description="Cloud Hosting",
            quantity=Decimal("18"),
            unit_price=Decimal("500.00"),
            total=Decimal("9000.00"),
        )
        db.add_all([line1, line2])
        db.commit()

        yield client, org_id, v

        db.query(InvoiceLineItemModel).filter(InvoiceLineItemModel.organization_id == org_id).delete()
        db.query(InvoiceModel).filter(InvoiceModel.organization_id == org_id).delete()
        db.query(DocumentModel).filter(DocumentModel.organization_id == org_id).delete()
        db.query(VendorAliasModel).filter(VendorAliasModel.organization_id == org_id).delete()
        db.query(VendorModel).filter(VendorModel.organization_id == org_id).delete()
        db.commit()
        db.close()


def test_investigate_endpoint(investigate_client):
    client, org_id, _ = investigate_client

    response = client.post(
        "/investigate",
        json={
            "question": "Investigate why AWS spending increased in August 2026",
            "organization_id": org_id,
            "include_trace": True,
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert data["investigation_type"] == "VENDOR_SPEND_INCREASE"
    assert data["baseline"]["spend"] == "5000.00"
    assert data["target"]["spend"] == "9000.00"
    assert data["change"]["absolute"] == "4000.00"
    assert len(data["drivers"]) >= 1
    assert data["drivers"][0]["type"] == "QUANTITY_CHANGE"
    assert data["drivers"][0]["impact_amount"] == "4000.00"
    assert data["confidence"] >= 0.7
    assert "execution_trace" in data
