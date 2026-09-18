import pytest
from decimal import Decimal
from app.database.session import SessionLocal
from app.database.models import (
    DocumentModel,
    InvoiceModel,
    VendorModel,
    AnomalyFlagModel,
)
from app.finance.analytics.anomaly_detector import AnomalyDetector


@pytest.fixture
def db():
    session = SessionLocal()
    org_id = "test_anom_org"
    for m in (AnomalyFlagModel, InvoiceModel, VendorModel, DocumentModel):
        session.query(m).filter(m.organization_id == org_id).delete(synchronize_session=False)
    session.commit()
    yield session
    session.close()


def test_insufficient_samples_skips_anomaly(db):
    org_id = "test_anom_org"
    vendor = VendorModel(
        id="ven_anom_1",
        organization_id=org_id,
        canonical_name="Normal Corp",
        normalized_name="normal corp",
    )
    db.add(vendor)

    doc = DocumentModel(id="doc_anom_1", filename="test.pdf", organization_id=org_id)
    db.add(doc)

    # Only 2 previous invoices (threshold is 5)
    for i in range(2):
        inv = InvoiceModel(
            id=f"inv_anom_hist_{i}",
            document_id="doc_anom_1",
            organization_id=org_id,
            vendor_id="ven_anom_1",
            total_amount=Decimal("100.00"),
        )
        db.add(inv)
    db.commit()

    current_inv = InvoiceModel(
        id="inv_anom_current",
        document_id="doc_anom_1",
        organization_id=org_id,
        vendor_id="ven_anom_1",
        total_amount=Decimal("10000.00"),
    )
    db.add(current_inv)
    db.commit()

    detector = AnomalyDetector()
    flag = detector.check_invoice(current_inv, db)
    assert flag is None


def test_high_amount_anomaly_detected(db):
    org_id = "test_anom_org"
    vendor = VendorModel(
        id="ven_anom_2",
        organization_id=org_id,
        canonical_name="Stat Corp",
        normalized_name="stat corp",
    )
    db.add(vendor)

    doc = DocumentModel(id="doc_anom_2", filename="test.pdf", organization_id=org_id)
    db.add(doc)

    # Seed 6 invoices around 100 with small variance
    historical_amounts = [100.0, 102.0, 98.0, 101.0, 99.0, 100.0]
    for i, amt in enumerate(historical_amounts):
        inv = InvoiceModel(
            id=f"inv_anom_hist2_{i}",
            document_id="doc_anom_2",
            organization_id=org_id,
            vendor_id="ven_anom_2",
            total_amount=Decimal(str(amt)),
        )
        db.add(inv)
    db.commit()

    # Outlier invoice: 500.0 (z-score > 2.5)
    outlier_inv = InvoiceModel(
        id="inv_anom_outlier",
        document_id="doc_anom_2",
        organization_id=org_id,
        vendor_id="ven_anom_2",
        total_amount=Decimal("500.00"),
    )
    db.add(outlier_inv)
    db.commit()

    detector = AnomalyDetector()
    flag = detector.check_invoice(outlier_inv, db)
    assert flag is not None
    assert flag.anomaly_type == "HIGH_AMOUNT"
    assert flag.sample_size == 6
    assert float(flag.observed_value) == 500.00
    assert float(flag.z_score) > 2.5


def test_normal_invoice_not_flagged(db):
    org_id = "test_anom_org"
    vendor = VendorModel(
        id="ven_anom_3",
        organization_id=org_id,
        canonical_name="Steady Corp",
        normalized_name="steady corp",
    )
    db.add(vendor)

    doc = DocumentModel(id="doc_anom_3", filename="test.pdf", organization_id=org_id)
    db.add(doc)

    # Seed 6 invoices around 100
    historical_amounts = [100.0, 105.0, 95.0, 102.0, 98.0, 100.0]
    for i, amt in enumerate(historical_amounts):
        inv = InvoiceModel(
            id=f"inv_anom_hist3_{i}",
            document_id="doc_anom_3",
            organization_id=org_id,
            vendor_id="ven_anom_3",
            total_amount=Decimal(str(amt)),
        )
        db.add(inv)
    db.commit()

    normal_inv = InvoiceModel(
        id="inv_anom_normal",
        document_id="doc_anom_3",
        organization_id=org_id,
        vendor_id="ven_anom_3",
        total_amount=Decimal("101.00"),
    )
    db.add(normal_inv)
    db.commit()

    detector = AnomalyDetector()
    flag = detector.check_invoice(normal_inv, db)
    assert flag is None
