from app.intelligence.confidence import ConfidenceCalculator
from app.intelligence.schemas import (
    QueryPlan,
    QueryIntent,
    ToolResult,
    ToolName,
    ToolOperation,
    Evidence,
    EvidenceSourceType,
)


def test_confidence_calculator_high_quality():
    plan = QueryPlan(
        query_id="q1",
        original_question="How much spend?",
        normalized_question="How much spend?",
        intent=QueryIntent.TOTAL_SPEND,
        entities={},
        planner_confidence=1.0,
    )
    results = [
        ToolResult(
            step_id="s1",
            tool=ToolName.SQL,
            operation=ToolOperation.GET_VENDOR_TOTAL_SPEND,
            success=True,
            record_count=5,
            execution_time_ms=10,
        )
    ]
    evidence = [
        Evidence(
            evidence_id="e1",
            source_type=EvidenceSourceType.DATABASE_AGGREGATION,
            confidence=1.0,
        )
    ]

    conf = ConfidenceCalculator.calculate(plan, results, evidence)
    assert conf >= 0.9


def test_confidence_calculator_penalties():
    # Ambiguous planner + failed tool
    plan = QueryPlan(
        query_id="q2",
        original_question="Who is unknown vendor?",
        normalized_question="Who is unknown vendor?",
        intent=QueryIntent.VENDOR_SPEND,
        entities={},
        ambiguities=["Unknown vendor"],
        planner_confidence=0.7,
    )
    results = [
        ToolResult(
            step_id="s1",
            tool=ToolName.SQL,
            operation=ToolOperation.GET_VENDOR_TOTAL_SPEND,
            success=False,
            error="Not found",
            record_count=0,
            execution_time_ms=10,
        )
    ]

    conf = ConfidenceCalculator.calculate(plan, results, [])
    assert conf < 0.5
