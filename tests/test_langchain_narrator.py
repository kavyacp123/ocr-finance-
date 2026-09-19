import pytest

from app.intelligence.langchain_narrator import (
    CopilotNarration,
    InvestigationNarration,
    LangChainNarrator,
)
from app.intelligence.schemas import (
    Evidence,
    EvidenceSourceType,
    FinanceAnswer,
    QueryIntent,
    QueryPlan,
    ToolName,
    ToolOperation,
    ToolResult,
)
from app.investigations.schemas import InvestigationReport, InvestigationType


class FakeStructuredRunnable:
    def __init__(self, result):
        self.result = result

    async def ainvoke(self, prompt):
        assert "VERIFIED" in prompt
        return self.result


class FakeModel:
    def __init__(self, result):
        self.result = result

    def with_structured_output(self, schema):
        return FakeStructuredRunnable(self.result)


def build_plan():
    return QueryPlan(
        query_id="qry_test",
        original_question="How much did we spend?",
        normalized_question="How much did we spend?",
        intent=QueryIntent.TOTAL_SPEND,
        steps=[],
    )


def build_evidence():
    return [
        Evidence(
            evidence_id="ev_test",
            source_type=EvidenceSourceType.DATABASE_AGGREGATION,
            document_id="doc_test",
            source_text="Total spend: 100.00",
            confidence=1.0,
        )
    ]


@pytest.mark.asyncio
async def test_copilot_narration_uses_verified_result():
    narrator = LangChainNarrator(model=FakeModel(CopilotNarration(answer="Verified spend is 100.00.")))
    narrator.enabled = True
    answer = FinanceAnswer(
        query_id="qry_test",
        question="How much did we spend?",
        answer="Total spend is 100.00.",
        intent=QueryIntent.TOTAL_SPEND,
        evidence=build_evidence(),
    )
    result = await narrator.narrate_copilot(
        question=answer.question,
        plan=build_plan(),
        answer=answer,
        tool_results=[
            ToolResult(
                step_id="step_test",
                tool=ToolName.SQL,
                operation=ToolOperation.ANALYTICS_TOTAL_SPEND,
                success=True,
                data={"total_spend": "100.00"},
            )
        ],
        evidence=build_evidence(),
    )
    assert result == "Verified spend is 100.00."


@pytest.mark.asyncio
async def test_investigation_narration_requires_evidence():
    narrator = LangChainNarrator(model=FakeModel(InvestigationNarration(summary="summary", conclusion="conclusion")))
    narrator.enabled = True
    report = InvestigationReport(
        investigation_id="inv_test",
        investigation_type=InvestigationType.VENDOR_SPEND_INCREASE,
        title="Test",
        summary="deterministic summary",
        subject={},
        conclusion="deterministic conclusion",
        confidence=1.0,
        evidence=[],
    )
    assert await narrator.narrate_investigation("Why?", report) is None
