import pytest
from app.database.session import SessionLocal
from app.database.models import VendorModel, VendorAliasModel, InvoiceModel, PurchaseOrderModel, DocumentModel
from app.intelligence.entity_parser import EntityParser


@pytest.fixture
def db_session():
    db = SessionLocal()
    org_id = "org_test_parser"
    # Clean up
    db.query(VendorAliasModel).filter(VendorAliasModel.organization_id == org_id).delete()
    db.query(InvoiceModel).filter(InvoiceModel.organization_id == org_id).delete()
    db.query(PurchaseOrderModel).filter(PurchaseOrderModel.organization_id == org_id).delete()
    db.query(DocumentModel).filter(DocumentModel.organization_id == org_id).delete()
    db.query(VendorModel).filter(VendorModel.organization_id == org_id).delete()
    db.commit()

    doc1 = DocumentModel(id="doc_ep1", organization_id=org_id, filename="doc1.pdf")
    doc2 = DocumentModel(id="doc_ep2", organization_id=org_id, filename="doc2.pdf")
    db.add_all([doc1, doc2])
    db.commit()

    # Create dummy vendor and alias
    v = VendorModel(
        organization_id=org_id,
        canonical_name="Amazon Web Services India Pvt Ltd",
        normalized_name="amazon web services india pvt ltd",
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

    # Add an invoice and a PO
    inv = InvoiceModel(
        organization_id=org_id,
        document_id=doc1.id,
        invoice_number="INV-992",
        vendor_id=v.id,
        total_amount=15000.0,
    )
    db.add(inv)

    po = PurchaseOrderModel(
        organization_id=org_id,
        document_id=doc2.id,
        po_number="PO-100",
        vendor_id=v.id,
        total_amount=20000.0,
    )
    db.add(po)
    db.commit()

    yield db, org_id, v

    db.query(VendorAliasModel).filter(VendorAliasModel.organization_id == org_id).delete()
    db.query(InvoiceModel).filter(InvoiceModel.organization_id == org_id).delete()
    db.query(PurchaseOrderModel).filter(PurchaseOrderModel.organization_id == org_id).delete()
    db.query(DocumentModel).filter(DocumentModel.organization_id == org_id).delete()
    db.query(VendorModel).filter(VendorModel.organization_id == org_id).delete()
    db.commit()
    db.close()


def test_entity_parser_vendor_resolution(db_session):
    db, org_id, vendor = db_session
    parser = EntityParser()

    # Query with alias "AWS"
    res = parser.parse("How much did we spend with AWS?", db, org_id)
    assert res.get("vendor_id") == vendor.id
    assert res.get("vendor_name") == vendor.canonical_name


def test_entity_parser_invoice_po_lookup(db_session):
    db, org_id, _ = db_session
    parser = EntityParser()

    res = parser.parse("Show me details for invoice INV-992 and PO-100", db, org_id)
    assert res.get("invoice_number") == "INV-992"
    assert "invoice_id" in res
    assert res.get("po_number") == "PO-100"
    assert "po_id" in res


def test_entity_parser_unknown_vendor(db_session):
    db, org_id, _ = db_session
    parser = EntityParser()

    res = parser.parse("How much did we spend with UnknownCo?", db, org_id)
    assert "vendor_id" not in res
    assert res.get("vendor_name_unresolved") == "UnknownCo"
