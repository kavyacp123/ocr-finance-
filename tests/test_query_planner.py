import pytest
from app.database.session import SessionLocal
from app.database.models import VendorModel, VendorAliasModel
from app.intelligence.planner import QueryPlanner
from app.intelligence.schemas import QueryIntent, ToolName, ToolOperation


@pytest.fixture
def test_db():
    db = SessionLocal()
    org_id = "org_test_planner"
    db.query(VendorAliasModel).filter(VendorAliasModel.organization_id == org_id).delete()
    db.query(VendorModel).filter(VendorModel.organization_id == org_id).delete()
    db.commit()

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
    db.commit()

    yield db, org_id, v

    db.query(VendorAliasModel).filter(VendorAliasModel.organization_id == org_id).delete()
    db.query(VendorModel).filter(VendorModel.organization_id == org_id).delete()
    db.commit()
    db.close()


def test_plan_vendor_spend(test_db):
    db, org_id, vendor = test_db
    planner = QueryPlanner()

    plan = planner.plan("How much did we spend with AWS last quarter?", db, org_id)
    assert plan.intent == QueryIntent.VENDOR_SPEND
    assert plan.entities.get("vendor_id") == vendor.id
    assert plan.time_range is not None
    assert len(plan.steps) == 1
    assert plan.steps[0].tool == ToolName.SQL
    assert plan.steps[0].operation == ToolOperation.GET_VENDOR_TOTAL_SPEND


def test_plan_semantic_search(test_db):
    db, org_id, _ = test_db
    planner = QueryPlanner()

    plan = planner.plan("Find invoices mentioning GPU compute", db, org_id)
    assert plan.intent == QueryIntent.SEMANTIC_DOCUMENT_SEARCH
    assert len(plan.steps) == 1
    assert plan.steps[0].tool == ToolName.VECTOR
    assert plan.steps[0].operation == ToolOperation.SEMANTIC_SEARCH
    assert "GPU compute" in plan.steps[0].arguments["query"]


def test_plan_entity_relationship(test_db):
    db, org_id, vendor = test_db
    planner = QueryPlanner()

    plan = planner.plan("Which payments are connected to invoices from AWS?", db, org_id)
    assert plan.intent == QueryIntent.ENTITY_RELATIONSHIP
    assert len(plan.steps) == 1
    assert plan.steps[0].tool == ToolName.GRAPH
    assert plan.steps[0].arguments["vendor_id"] == vendor.id


def test_plan_rule_violations(test_db):
    db, org_id, _ = test_db
    planner = QueryPlanner()

    plan = planner.plan("Which AWS invoices have PO mismatches?", db, org_id)
    assert plan.intent == QueryIntent.RULE_VIOLATIONS
    assert len(plan.steps) == 1
    assert plan.steps[0].tool == ToolName.RULES
    assert plan.steps[0].operation == ToolOperation.GET_PO_MISMATCHES


def test_plan_hybrid_investigation(test_db):
    db, org_id, vendor = test_db
    planner = QueryPlanner()

    plan = planner.plan("Why did AWS spending increase in August?", db, org_id)
    assert plan.intent == QueryIntent.INVESTIGATION_REQUEST
    assert plan.requires_reasoning is True
    # Hybrid steps include SQL, Anomaly, Rules, Vector
    tools_in_steps = {s.tool for s in plan.steps}
    assert ToolName.SQL in tools_in_steps
    assert ToolName.ANOMALY in tools_in_steps
    assert ToolName.RULES in tools_in_steps
    assert ToolName.VECTOR in tools_in_steps
