import pytest
import asyncio
from typing import Set
from app.intelligence.schemas import (
    QueryPlan,
    QueryStep,
    QueryIntent,
    ToolName,
    ToolOperation,
    ToolResult,
)
from app.intelligence.tools.base import BaseFinanceTool
from app.intelligence.executor import QueryExecutor


class DummyTool(BaseFinanceTool):
    tool_name = ToolName.SQL
    supported_operations: Set[ToolOperation] = {
        ToolOperation.GET_VENDOR_TOTAL_SPEND,
        ToolOperation.GET_INVOICES_FOR_PERIOD,
    }

    def __init__(self, should_fail: bool = False, delay: float = 0.0):
        self.should_fail = should_fail
        self.delay = delay

    async def _execute(self, step_id, operation, arguments, organization_id) -> ToolResult:
        if self.delay > 0:
            await asyncio.sleep(self.delay)
        if self.should_fail:
            raise RuntimeError("Intentional tool failure")
        return ToolResult(
            step_id=step_id,
            tool=self.tool_name,
            operation=operation,
            success=True,
            data={"echo": arguments},
            record_count=1,
            execution_time_ms=0,
        )


@pytest.mark.asyncio
async def test_executor_concurrent_steps():
    tool = DummyTool(delay=0.05)
    executor = QueryExecutor(tools={ToolName.SQL: tool})

    plan = QueryPlan(
        query_id="q1",
        original_question="test concurrent",
        normalized_question="test concurrent",
        intent=QueryIntent.TOTAL_SPEND,
        entities={},
        steps=[
            QueryStep(
                step_id="step_1",
                tool=ToolName.SQL,
                operation=ToolOperation.GET_VENDOR_TOTAL_SPEND,
                arguments={"v": 1},
                description="Step 1",
            ),
            QueryStep(
                step_id="step_2",
                tool=ToolName.SQL,
                operation=ToolOperation.GET_INVOICES_FOR_PERIOD,
                arguments={"v": 2},
                description="Step 2",
            ),
        ],
    )

    results = await executor.execute(plan, organization_id="org_test")
    assert len(results) == 2
    assert results[0].success is True
    assert results[1].success is True


@pytest.mark.asyncio
async def test_executor_dependency_chain():
    tool = DummyTool()
    executor = QueryExecutor(tools={ToolName.SQL: tool})

    plan = QueryPlan(
        query_id="q2",
        original_question="test dependent",
        normalized_question="test dependent",
        intent=QueryIntent.TOTAL_SPEND,
        entities={},
        steps=[
            QueryStep(
                step_id="step_1",
                tool=ToolName.SQL,
                operation=ToolOperation.GET_VENDOR_TOTAL_SPEND,
                arguments={"v": 1},
                description="Step 1",
            ),
            QueryStep(
                step_id="step_2",
                tool=ToolName.SQL,
                operation=ToolOperation.GET_INVOICES_FOR_PERIOD,
                arguments={},
                depends_on=["step_1"],
                description="Step 2 depends on 1",
            ),
        ],
    )

    results = await executor.execute(plan, organization_id="org_test")
    assert len(results) == 2
    assert results[0].step_id == "step_1"
    assert results[1].step_id == "step_2"


@pytest.mark.asyncio
async def test_executor_partial_failure():
    tool = DummyTool(should_fail=True)
    executor = QueryExecutor(tools={ToolName.SQL: tool})

    plan = QueryPlan(
        query_id="q3",
        original_question="test fail",
        normalized_question="test fail",
        intent=QueryIntent.TOTAL_SPEND,
        entities={},
        steps=[
            QueryStep(
                step_id="step_1",
                tool=ToolName.SQL,
                operation=ToolOperation.GET_VENDOR_TOTAL_SPEND,
                arguments={},
                description="Failing step",
            )
        ],
    )

    results = await executor.execute(plan, organization_id="org_test")
    assert len(results) == 1
    assert results[0].success is False
    assert "Intentional tool failure" in results[0].error
