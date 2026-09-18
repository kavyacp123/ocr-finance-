"""
Finance Rules Tool
==================

WHY:   Business rule violations (missing PO, PO amount mismatch, negative amounts)
       are strictly deterministic. The LLM must NEVER decide whether a rule
       was violated — it must query this tool.

WHERE: Called by QueryExecutor when step.tool == ToolName.RULES.

WHAT IT RECEIVES: Operation name + arguments + authenticated organization_id.

WHAT IT OUTPUTS:  ToolResult with rule violation records + RULE_VIOLATION Evidence.
"""

from typing import Any, Callable, Dict, List, Optional, Set
from sqlalchemy.orm import Session
from sqlalchemy import desc

from app.database.session import SessionLocal
from app.database.models import RuleViolationModel, InvoiceModel
from app.finance.analytics.rule_engine import RuleEngine
from app.intelligence.schemas import (
    ToolName,
    ToolOperation,
    ToolResult,
    Evidence,
    EvidenceSourceType,
)
from app.intelligence.tools.base import BaseFinanceTool


class FinanceRulesTool(BaseFinanceTool):
    """
    Approved Rules operations wrapping RuleViolationModel queries and RuleEngine.
    """

    tool_name = ToolName.RULES
    supported_operations: Set[ToolOperation] = {
        ToolOperation.GET_DOCUMENT_RULE_VIOLATIONS,
        ToolOperation.GET_VENDOR_RULE_VIOLATIONS,
        ToolOperation.GET_PERIOD_RULE_VIOLATIONS,
        ToolOperation.GET_PO_MISMATCHES,
        ToolOperation.GET_MISSING_PO_INVOICES,
    }

    def __init__(
        self,
        session_factory: Callable[[], Session] = SessionLocal,
        rule_engine: Optional[RuleEngine] = None,
    ):
        self.session_factory = session_factory
        self.rule_engine = rule_engine

    async def _execute(
        self,
        step_id: str,
        operation: ToolOperation,
        arguments: dict,
        organization_id: str,
    ) -> ToolResult:
        db: Session = self.session_factory()
        try:
            q = db.query(RuleViolationModel).filter(
                RuleViolationModel.organization_id == organization_id
            )

            if operation == ToolOperation.GET_DOCUMENT_RULE_VIOLATIONS:
                entity_id = arguments.get("entity_id") or arguments.get("invoice_id")
                if entity_id:
                    q = q.filter(RuleViolationModel.entity_id == entity_id)

            elif operation == ToolOperation.GET_VENDOR_RULE_VIOLATIONS:
                vendor_id = arguments.get("vendor_id")
                if vendor_id:
                    # Invoices for this vendor
                    inv_ids = [
                        inv.id
                        for inv in db.query(InvoiceModel.id)
                        .filter(
                            InvoiceModel.organization_id == organization_id,
                            InvoiceModel.vendor_id == vendor_id,
                        )
                        .all()
                    ]
                    q = q.filter(RuleViolationModel.entity_id.in_(inv_ids))

            elif operation == ToolOperation.GET_PO_MISMATCHES:
                q = q.filter(RuleViolationModel.rule_id == "INVOICE_PO_AMOUNT_MISMATCH")

            elif operation == ToolOperation.GET_MISSING_PO_INVOICES:
                q = q.filter(RuleViolationModel.rule_id == "INVOICE_WITHOUT_PO")

            limit = arguments.get("limit", 50)
            violations = q.order_by(desc(RuleViolationModel.created_at)).limit(limit).all()

            data = [
                {
                    "violation_id": v.id,
                    "rule_id": v.rule_id,
                    "rule_name": v.rule_name,
                    "severity": v.severity,
                    "entity_type": v.entity_type,
                    "entity_id": v.entity_id,
                    "status": v.status,
                    "details": v.details_json,
                }
                for v in violations
            ]

            evidence = [
                Evidence(
                    evidence_id=self._make_evidence_id(),
                    source_type=EvidenceSourceType.RULE_VIOLATION,
                    invoice_id=v.entity_id if v.entity_type == "INVOICE" else None,
                    database_record={"rule_id": v.rule_id, "severity": v.severity},
                    confidence=1.0,
                    source_operation=operation.value,
                )
                for v in violations
            ]

            return ToolResult(
                step_id=step_id,
                tool=self.tool_name,
                operation=operation,
                success=True,
                data={"violations": data, "count": len(data)},
                evidence=evidence,
                record_count=len(data),
                execution_time_ms=0,
            )
        finally:
            db.close()
