from app.intelligence.answer_generator import AnswerGenerator
from app.intelligence.schemas import (
    QueryPlan,
    QueryIntent,
    ToolResult,
    ToolName,
    ToolOperation,
    Evidence,
    EvidenceSourceType,
)


def test_answer_generator_vendor_spend():
    plan = QueryPlan(
        query_id="q1",
        original_question="How much did we spend with AWS?",
        normalized_question="How much did we spend with AWS?",
        intent=QueryIntent.VENDOR_SPEND,
        entities={"vendor_name": "AWS"},
    )
    results = [
        ToolResult(
            step_id="s1",
            tool=ToolName.SQL,
            operation=ToolOperation.GET_VENDOR_TOTAL_SPEND,
            success=True,
            data={"vendor_name": "AWS", "total_spend": "4820000.00", "invoice_count": 12, "currency": "INR"},
            record_count=12,
            execution_time_ms=15,
        )
    ]
    evidence = [
        Evidence(
            evidence_id="e1",
            source_type=EvidenceSourceType.DATABASE_AGGREGATION,
            confidence=1.0,
        )
    ]

    answer = AnswerGenerator.generate("How much did we spend with AWS?", plan, results, evidence)
    assert answer.intent == QueryIntent.VENDOR_SPEND
    assert "4820000.00" in answer.answer
    assert "AWS" in answer.answer
    assert len(answer.metrics) == 1
    assert answer.confidence >= 0.8


def test_answer_generator_unpaid_invoices():
    plan = QueryPlan(
        query_id="q2",
        original_question="Show all unpaid invoices",
        normalized_question="Show all unpaid invoices",
        intent=QueryIntent.UNPAID_INVOICES,
        entities={},
    )
    results = [
        ToolResult(
            step_id="s1",
            tool=ToolName.SQL,
            operation=ToolOperation.GET_UNPAID_INVOICES,
            success=True,
            data={
                "unpaid_invoices": [
                    {"invoice_number": "INV-100", "vendor_name": "Vendor A", "total_amount": "5000.00", "due_date": "2026-09-01"}
                ],
                "count": 1,
            },
            record_count=1,
            execution_time_ms=10,
        )
    ]

    answer = AnswerGenerator.generate("Show all unpaid invoices", plan, results, [])
    assert "INV-100" in answer.answer
    assert "5000.00" in answer.answer


def test_answer_generator_unpaid_invoices_with_unknown_total():
    plan = QueryPlan(
        query_id="q2b",
        original_question="Show all unpaid invoices",
        normalized_question="Show all unpaid invoices",
        intent=QueryIntent.UNPAID_INVOICES,
        entities={},
    )
    results = [
        ToolResult(
            step_id="s1",
            tool=ToolName.SQL,
            operation=ToolOperation.GET_UNPAID_INVOICES,
            success=True,
            data={
                "unpaid_invoices": [
                    {
                        "invoice_id": "inv_missing_total",
                        "invoice_number": None,
                        "vendor_name": None,
                        "total_amount": None,
                        "due_date": None,
                    }
                ],
                "count": 1,
            },
            record_count=1,
            execution_time_ms=10,
        )
    ]

    answer = AnswerGenerator.generate("Show all unpaid invoices", plan, results, [])
    assert "inv_missing_total" in answer.answer
    assert "N/A" in answer.answer
