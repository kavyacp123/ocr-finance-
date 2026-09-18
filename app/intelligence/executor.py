"""
Query Execution Engine
======================

WHY:   Plans contain single or multiple steps (a DAG). Steps with no dependencies
       should run concurrently using asyncio.gather; steps with dependencies must wait.
       Partial tool failures must be captured cleanly without crashing the overall query.
       Tenant isolation (organization_id) is strictly enforced here.

WHERE: Called by FinanceCopilotService to execute the QueryPlan.

WHAT IT RECEIVES: QueryPlan + registered tools dict + authenticated organization_id.

WHAT IT OUTPUTS:  List[ToolResult] representing execution traces and data.
"""

import asyncio
import time
from typing import Dict, List, Optional, Set
from app.intelligence.schemas import (
    QueryPlan,
    QueryStep,
    ToolName,
    ToolResult,
)
from app.intelligence.tools.base import BaseFinanceTool
from app.utils.logging import logger

MAX_QUERY_STEPS = 10
TOOL_TIMEOUT_SECONDS = 15.0


class QueryExecutor:
    """
    Executes a QueryPlan DAG safely with timeouts, concurrency, and tenant isolation.
    """

    def __init__(self, tools: Dict[ToolName, BaseFinanceTool]):
        self.tools = tools

    async def execute(
        self,
        plan: QueryPlan,
        organization_id: str,
    ) -> List[ToolResult]:
        if len(plan.steps) > MAX_QUERY_STEPS:
            raise ValueError(f"Plan exceeds maximum allowed steps ({len(plan.steps)} > {MAX_QUERY_STEPS})")

        completed_results: Dict[str, ToolResult] = {}
        pending_steps = list(plan.steps)

        # Iteratively execute steps whose dependencies are resolved
        while pending_steps:
            # Find steps that are ready to run
            ready_steps = [
                step for step in pending_steps
                if all(dep in completed_results for dep in step.depends_on)
            ]

            if not ready_steps:
                # Deadlock or cyclic dependency
                logger.error(f"EXECUTOR: Cyclic or unresolvable dependency in plan {plan.query_id}")
                for step in pending_steps:
                    completed_results[step.step_id] = ToolResult(
                        step_id=step.step_id,
                        tool=step.tool,
                        operation=step.operation,
                        success=False,
                        error=f"Dependency unresolvable: {step.depends_on}",
                        execution_time_ms=0,
                    )
                break

            # Execute ready steps concurrently
            tasks = [
                self._execute_single_step(step, organization_id, completed_results)
                for step in ready_steps
            ]
            batch_results = await asyncio.gather(*tasks, return_exceptions=False)

            for step, res in zip(ready_steps, batch_results):
                completed_results[step.step_id] = res
                pending_steps.remove(step)

        # Return results in the original step order
        return [completed_results[s.step_id] for s in plan.steps if s.step_id in completed_results]

    async def _execute_single_step(
        self,
        step: QueryStep,
        organization_id: str,
        prior_results: Dict[str, ToolResult],
    ) -> ToolResult:
        tool = self.tools.get(step.tool)
        if not tool:
            return ToolResult(
                step_id=step.step_id,
                tool=step.tool,
                operation=step.operation,
                success=False,
                error=f"Tool '{step.tool.value}' is not registered or unavailable",
                execution_time_ms=0,
            )

        # If step depends on prior results, inject or resolve dynamic arguments
        resolved_args = dict(step.arguments)
        for dep_id in step.depends_on:
            dep_res = prior_results.get(dep_id)
            if dep_res and dep_res.success and isinstance(dep_res.data, dict):
                # E.g., pass invoice_ids forward if available
                if "invoice_id" in dep_res.data and "invoice_id" not in resolved_args:
                    resolved_args["invoice_id"] = dep_res.data["invoice_id"]
                if "invoices" in dep_res.data and "invoice_ids" not in resolved_args:
                    resolved_args["invoice_ids"] = [
                        inv["invoice_id"] for inv in dep_res.data["invoices"] if "invoice_id" in inv
                    ]

        try:
            return await asyncio.wait_for(
                tool.execute(
                    step_id=step.step_id,
                    operation=step.operation,
                    arguments=resolved_args,
                    organization_id=organization_id,
                ),
                timeout=TOOL_TIMEOUT_SECONDS,
            )
        except asyncio.TimeoutError:
            logger.error(f"EXECUTOR: Step {step.step_id} ({step.operation.value}) timed out after {TOOL_TIMEOUT_SECONDS}s")
            return ToolResult(
                step_id=step.step_id,
                tool=step.tool,
                operation=step.operation,
                success=False,
                error=f"Operation timed out after {TOOL_TIMEOUT_SECONDS}s",
                execution_time_ms=TOOL_TIMEOUT_SECONDS * 1000,
            )
        except Exception as e:
            logger.error(f"EXECUTOR: Step {step.step_id} crashed: {e}")
            return ToolResult(
                step_id=step.step_id,
                tool=step.tool,
                operation=step.operation,
                success=False,
                error=str(e),
                execution_time_ms=0,
            )
