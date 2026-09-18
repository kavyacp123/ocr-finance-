"""
Base Tool Interface
====================

WHY:   Every tool (SQL, Graph, Vector, Rules, Anomaly, Analytics) must return
       the same ToolResult envelope so the executor and answer generator can
       process them uniformly.  This base class enforces the contract.

WHERE: Subclassed by sql_tool, graph_tool, vector_tool, analytics_tool,
       rules_tool, anomaly_tool.

WHAT IT DOES:
  - Defines the execute() contract.
  - Wraps execution with timing and error handling.
  - Validates that the requested operation is in the tool's allowlist.
"""

import time
import uuid
from abc import ABC, abstractmethod
from typing import Set

from app.intelligence.schemas import (
    ToolName, ToolOperation, ToolResult, Evidence
)
from app.utils.logging import logger


class BaseFinanceTool(ABC):
    """
    Abstract base for all Finance Copilot tools.

    Subclasses must:
      1. Set `tool_name` (ToolName enum).
      2. Set `supported_operations` (set of ToolOperation enums).
      3. Implement `_execute()` with the actual logic.
    """

    tool_name: ToolName
    supported_operations: Set[ToolOperation]

    async def execute(
        self,
        step_id: str,
        operation: ToolOperation,
        arguments: dict,
        organization_id: str,
    ) -> ToolResult:
        """
        Public entry point. Validates the operation, measures timing,
        catches errors, and returns a standardised ToolResult.
        """
        start = time.monotonic()

        # ── Guard: operation must be in allowlist ─────────────────────
        if operation not in self.supported_operations:
            return ToolResult(
                step_id=step_id,
                tool=self.tool_name,
                operation=operation,
                success=False,
                error=f"Operation '{operation.value}' is not supported by {self.tool_name.value} tool. "
                      f"Allowed: {[op.value for op in self.supported_operations]}",
                execution_time_ms=self._elapsed(start),
            )

        # ── Execute ───────────────────────────────────────────────────
        try:
            result = await self._execute(step_id, operation, arguments, organization_id)
            result.execution_time_ms = self._elapsed(start)
            return result
        except Exception as e:
            logger.error(f"TOOL {self.tool_name.value}: {operation.value} failed — {e}")
            return ToolResult(
                step_id=step_id,
                tool=self.tool_name,
                operation=operation,
                success=False,
                error=str(e),
                execution_time_ms=self._elapsed(start),
            )

    @abstractmethod
    async def _execute(
        self,
        step_id: str,
        operation: ToolOperation,
        arguments: dict,
        organization_id: str,
    ) -> ToolResult:
        """Subclass implementation. Must return a ToolResult."""
        ...

    @staticmethod
    def _elapsed(start: float) -> float:
        return round((time.monotonic() - start) * 1000, 2)

    @staticmethod
    def _make_evidence_id() -> str:
        return f"ev_{uuid.uuid4().hex[:12]}"
