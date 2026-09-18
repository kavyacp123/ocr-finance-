import pytest
from datetime import date
from decimal import Decimal

from app.database.session import SessionLocal
from app.database.models import (
    InvoiceModel,
    InvoiceLineItemModel,
    VendorModel,
    VendorAliasModel,
    DocumentModel,
    RuleViolationModel,
    AnomalyFlagModel,
)
from app.investigations.engine import FinanceInvestigationEngine
from app.investigations.schemas import DriverType, InvestigationType


@pytest.fixture
def engine_db():
    db = SessionLocal()
    org_id = "org_engine_test"

    # Clean up
    db.query(AnomalyFlagModel).filter(AnomalyFlagModel.organization_id == org_id).delete()
    db.query(RuleViolationModel).filter(RuleViolationModel.organization_id == org_id).delete()
    db.query(InvoiceLineItemModel).filter(InvoiceLineItemModel.organization_id == org_id).delete()
    db.query(InvoiceModel).filter(InvoiceModel.organization_id == org_id).delete()
    db.query(DocumentModel).filter(DocumentModel.organization_id == org_id).delete()
    db.query(VendorAliasModel).filter(VendorAliasModel.organization_id == org_id).delete()
    db.query(VendorModel).filter(VendorModel.organization_id == org_id).delete()
    db.commit()

    # Create vendor
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

    # Documents
    doc_july = DocumentModel(id="doc_july", organization_id=org_id, filename="july.pdf")
    doc_aug = DocumentModel(id="doc_aug", organization_id=org_id, filename="august.pdf")
    db.add_all([doc_july, doc_aug])
    db.commit()

    # July invoice (Baseline): Qty 20, Price 100 -> Total 2000
    inv_july = InvoiceModel(
        organization_id=org_id,
        document_id=doc_july.id,
        vendor_id=v.id,
        invoice_number="INV-JUL-01",
        invoice_date=date(2026, 7, 15),
        total_amount=Decimal("2000.00"),
        amount_due=Decimal("0.00"),
        payment_status="PAID",
    )
    db.add(inv_july)
    db.flush()

    line_july = InvoiceLineItemModel(
        organization_id=org_id,
        invoice_id=inv_july.id,
        line_number=1,
        description="EC2 GPU Compute Instance",
        product_code="SKU-EC2-GPU",
        quantity=Decimal("20.0000"),
        unit_price=Decimal("100.00"),
        total=Decimal("2000.00"),
    )
    db.add(line_july)

    # August invoice (Target): Qty 50, Price 100 -> 5000 + Support 1500 -> Total 6500
    inv_aug = InvoiceModel(
        organization_id=org_id,
        document_id=doc_aug.id,
        vendor_id=v.id,
        invoice_number="INV-AUG-01",
        invoice_date=date(2026, 8, 20),
        total_amount=Decimal("6500.00"),
        amount_due=Decimal("6500.00"),
        payment_status="UNPAID",
    )
    db.add(inv_aug)
    db.flush()

    line_aug_1 = InvoiceLineItemModel(
        organization_id=org_id,
        invoice_id=inv_aug.id,
        line_number=1,
        description="EC2 GPU Compute Instance",
        product_code="SKU-EC2-GPU",
        quantity=Decimal("50.0000"),
        unit_price=Decimal("100.00"),
        total=Decimal("5000.00"),
    )
    line_aug_2 = InvoiceLineItemModel(
        organization_id=org_id,
        invoice_id=inv_aug.id,
        line_number=2,
        description="Enterprise Cloud Support",
        product_code="SKU-SUPP-ENT",
        quantity=Decimal("1.0000"),
        unit_price=Decimal("1500.00"),
        total=Decimal("1500.00"),
    )
    db.add_all([line_aug_1, line_aug_2])

    # Anomaly flag for August
    anom = AnomalyFlagModel(
        organization_id=org_id,
        entity_type="INVOICE",
        entity_id=inv_aug.id,
        vendor_id=v.id,
        anomaly_type="HIGH_AMOUNT",
        observed_value=Decimal("6500.00"),
        z_score=Decimal("2.80"),
        status="OPEN",
    )
    db.add(anom)
    db.commit()

    yield db, org_id, v

    db.query(AnomalyFlagModel).filter(AnomalyFlagModel.organization_id == org_id).delete()
    db.query(RuleViolationModel).filter(RuleViolationModel.organization_id == org_id).delete()
    db.query(InvoiceLineItemModel).filter(InvoiceLineItemModel.organization_id == org_id).delete()
    db.query(InvoiceModel).filter(InvoiceModel.organization_id == org_id).delete()
    db.query(DocumentModel).filter(DocumentModel.organization_id == org_id).delete()
    db.query(VendorAliasModel).filter(VendorAliasModel.organization_id == org_id).delete()
    db.query(VendorModel).filter(VendorModel.organization_id == org_id).delete()
    db.commit()
    db.close()


@pytest.mark.asyncio
async def test_investigation_engine_end_to_end(engine_db):
    _, org_id, _ = engine_db
    engine = FinanceInvestigationEngine()

    report = await engine.investigate(
        question="Why did AWS spending increase in August 2026?",
        organization_id=org_id,
    )

    assert report.investigation_type == InvestigationType.VENDOR_SPEND_INCREASE
    assert report.baseline.spend == "2000.00"
    assert report.target.spend == "6500.00"
    assert report.change.absolute == "4500.00"
    assert "225.00%" in report.change.percentage

    # Verify Drivers:
    # 1. Quantity surged on EC2 GPU: (50 - 20) * 100 = 3000.00
    # 2. New line item: Enterprise Cloud Support = 1500.00
    driver_types = [d.type for d in report.drivers]
    assert DriverType.QUANTITY_CHANGE in driver_types
    assert DriverType.NEW_LINE_ITEM in driver_types

    # Unexplained residual should be 0.00 since 3000 + 1500 = 4500
    assert report.unexplained_amount is None or report.unexplained_amount == "0.00"

    # Verify statistical anomaly detected
    assert len(report.anomalies) >= 1
    assert report.anomalies[0]["z_score"] == "2.80"

    # Confidence should be high
    assert report.confidence >= 0.8
    assert len(report.findings) >= 2


@pytest.mark.asyncio
async def test_investigation_reports_missing_period_data(engine_db):
    _, org_id, _ = engine_db
    report = await FinanceInvestigationEngine().investigate(
        question="Why did AWS spending increase in August 2025?",
        organization_id=org_id,
    )

    assert report.target.invoice_count == 0
    assert report.confidence == 0.25
    assert any("none could be included in the target period" in item for item in report.limitations)
