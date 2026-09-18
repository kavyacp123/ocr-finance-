import pytest
from datetime import date
from decimal import Decimal
from app.database.session import SessionLocal
from app.database.models import InvoiceModel, VendorModel, RuleViolationModel, AnomalyFlagModel, DocumentModel
from app.intelligence.tools.sql_tool import FinanceSQLTool
from app.intelligence.tools.graph_tool import FinanceGraphTool
from app.intelligence.tools.vector_tool import FinanceVectorTool
from app.intelligence.tools.analytics_tool import FinanceAnalyticsTool
from app.intelligence.tools.rules_tool import FinanceRulesTool
from app.intelligence.tools.anomaly_tool import FinanceAnomalyTool
from app.intelligence.schemas import ToolOperation, ToolName
from app.finance.graph.memory_adapter import NetworkXGraphAdapter
from app.finance.vector.store import VectorStore
from app.finance.vector.schemas import VectorChunk


@pytest.fixture
def tool_db():
    db = SessionLocal()
    org_id = "org_tool_test"
    db.query(AnomalyFlagModel).filter(AnomalyFlagModel.organization_id == org_id).delete()
    db.query(RuleViolationModel).filter(RuleViolationModel.organization_id == org_id).delete()
    db.query(InvoiceModel).filter(InvoiceModel.organization_id == org_id).delete()
    db.query(DocumentModel).filter(DocumentModel.organization_id == org_id).delete()
    db.query(VendorModel).filter(VendorModel.organization_id == org_id).delete()
    db.commit()

    v = VendorModel(
        organization_id=org_id,
        canonical_name="AWS Cloud",
        normalized_name="aws cloud",
    )
    db.add(v)
    db.commit()
    db.refresh(v)

    doc1 = DocumentModel(id="doc_t1", organization_id=org_id, filename="doc1.pdf")
    doc2 = DocumentModel(id="doc_t2", organization_id=org_id, filename="doc2.pdf")
    db.add_all([doc1, doc2])
    db.commit()

    inv1 = InvoiceModel(
        organization_id=org_id,
        document_id=doc1.id,
        vendor_id=v.id,
        invoice_number="INV-101",
        invoice_date=date(2026, 7, 10),
        total_amount=Decimal("10000.00"),
        amount_due=Decimal("0.00"),
        payment_status="PAID",
    )
    inv2 = InvoiceModel(
        organization_id=org_id,
        document_id=doc2.id,
        vendor_id=v.id,
        invoice_number="INV-102",
        invoice_date=date(2026, 8, 15),
        total_amount=Decimal("15000.00"),
        amount_due=Decimal("15000.00"),
        payment_status="UNPAID",
    )
    db.add_all([inv1, inv2])
    db.flush()

    rule_vio = RuleViolationModel(
        organization_id=org_id,
        rule_id="INVOICE_WITHOUT_PO",
        rule_name="Invoice Without PO",
        severity="WARNING",
        entity_type="INVOICE",
        entity_id=inv2.id,
        status="OPEN",
    )
    db.add(rule_vio)

    anom = AnomalyFlagModel(
        organization_id=org_id,
        entity_type="INVOICE",
        entity_id=inv2.id,
        vendor_id=v.id,
        anomaly_type="HIGH_AMOUNT",
        observed_value=Decimal("15000.00"),
        z_score=Decimal("2.45"),
        status="OPEN",
    )
    db.add(anom)
    db.commit()

    yield db, org_id, v, inv1, inv2

    db.query(AnomalyFlagModel).filter(AnomalyFlagModel.organization_id == org_id).delete()
    db.query(RuleViolationModel).filter(RuleViolationModel.organization_id == org_id).delete()
    db.query(InvoiceModel).filter(InvoiceModel.organization_id == org_id).delete()
    db.query(DocumentModel).filter(DocumentModel.organization_id == org_id).delete()
    db.query(VendorModel).filter(VendorModel.organization_id == org_id).delete()
    db.commit()
    db.close()


@pytest.mark.asyncio
async def test_sql_tool_spend(tool_db):
    _, org_id, v, _, _ = tool_db
    sql_tool = FinanceSQLTool()
    res = await sql_tool.execute(
        step_id="s1",
        operation=ToolOperation.GET_VENDOR_TOTAL_SPEND,
        arguments={"vendor_id": v.id},
        organization_id=org_id,
    )
    assert res.success is True
    assert res.data["total_spend"] == "25000.00"
    assert res.data["invoice_count"] == 2
    assert len(res.evidence) == 1


@pytest.mark.asyncio
async def test_sql_tool_unpaid(tool_db):
    _, org_id, _, _, inv2 = tool_db
    sql_tool = FinanceSQLTool()
    res = await sql_tool.execute(
        step_id="s2",
        operation=ToolOperation.GET_UNPAID_INVOICES,
        arguments={},
        organization_id=org_id,
    )
    assert res.success is True
    assert res.data["count"] == 1
    assert res.data["unpaid_invoices"][0]["invoice_number"] == inv2.invoice_number


@pytest.mark.asyncio
async def test_graph_tool():
    adapter = NetworkXGraphAdapter()
    adapter.upsert_node("vendor_1", "Vendor", {"name": "AWS"})
    adapter.upsert_node("inv_1", "Invoice", {"number": "INV-1"})
    adapter.upsert_edge("vendor_1", "inv_1", "ISSUED", {})

    graph_tool = FinanceGraphTool(graph_adapter=adapter)
    res = await graph_tool.execute(
        step_id="s3",
        operation=ToolOperation.GET_VENDOR_NETWORK,
        arguments={"vendor_id": "vendor_1"},
        organization_id="org_default",
    )
    assert res.success is True
    assert len(res.data["nodes"]) == 2
    assert len(res.data["edges"]) == 1


@pytest.mark.asyncio
async def test_vector_tool():
    vstore = VectorStore()
    vstore.add_chunks([
        VectorChunk(
            chunk_id="chk_1",
            document_id="doc_1",
            text="AWS EC2 GPU compute cluster instance usage",
            organization_id="org_v",
            chunk_type="LINE_ITEM",
            page_number=1,
            bbox=[10, 20, 30, 40],
        )
    ])
    vec_tool = FinanceVectorTool(vector_store=vstore)
    res = await vec_tool.execute(
        step_id="s4",
        operation=ToolOperation.SEMANTIC_SEARCH,
        arguments={"query": "GPU compute"},
        organization_id="org_v",
    )
    assert res.success is True
    assert len(res.data) >= 1
    assert res.evidence[0].bbox == [10.0, 20.0, 30.0, 40.0]


@pytest.mark.asyncio
async def test_rules_and_anomaly_tools(tool_db):
    _, org_id, v, _, _ = tool_db
    r_tool = FinanceRulesTool()
    res_r = await r_tool.execute(
        step_id="s5",
        operation=ToolOperation.GET_VENDOR_RULE_VIOLATIONS,
        arguments={"vendor_id": v.id},
        organization_id=org_id,
    )
    assert res_r.success is True
    assert res_r.data["count"] == 1

    a_tool = FinanceAnomalyTool()
    res_a = await a_tool.execute(
        step_id="s6",
        operation=ToolOperation.GET_VENDOR_ANOMALIES,
        arguments={"vendor_id": v.id},
        organization_id=org_id,
    )
    assert res_a.success is True
    assert res_a.data["count"] == 1
    assert res_a.data["anomalies"][0]["z_score"] == "2.45"
