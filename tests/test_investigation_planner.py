import pytest
from app.database.session import SessionLocal
from app.database.models import VendorModel, VendorAliasModel
from app.investigations.planner import InvestigationPlanner
from app.investigations.schemas import InvestigationType


@pytest.fixture
def inv_db():
    db = SessionLocal()
    org_id = "org_inv_planner_test"
    db.query(VendorAliasModel).filter(VendorAliasModel.organization_id == org_id).delete()
    db.query(VendorModel).filter(VendorModel.organization_id == org_id).delete()
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
    db.commit()

    yield db, org_id, v

    db.query(VendorAliasModel).filter(VendorAliasModel.organization_id == org_id).delete()
    db.query(VendorModel).filter(VendorModel.organization_id == org_id).delete()
    db.commit()
    db.close()


def test_investigation_planner_spend_increase(inv_db):
    db, org_id, v = inv_db
    planner = InvestigationPlanner()

    plan = planner.plan(
        question="Why did AWS spending increase in August 2026?",
        db=db,
        organization_id=org_id,
    )

    assert plan.investigation_type == InvestigationType.VENDOR_SPEND_INCREASE
    assert plan.subject["vendor_id"] == v.id
    assert plan.time_range.start_date == "2026-08-01"
    assert plan.time_range.end_date == "2026-08-31"
    # Preceding month is July 2026
    assert plan.baseline_period.start_date == "2026-07-01"
    assert plan.baseline_period.end_date == "2026-07-31"
    assert len(plan.steps) >= 10
    assert len(plan.hypotheses) == 3
