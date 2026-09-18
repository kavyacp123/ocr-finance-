"""
Finance Analytics Tool
======================

WHY:   High-level business aggregations (dashboard KPIs, overall spend trends,
       outstanding amount, vendor rankings) should be fetched from the
       existing analytics repository, not re-computed or hallucinated.

WHERE: Called by QueryExecutor when step.tool == ToolName.ANALYTICS.

WHAT IT RECEIVES: Operation name + arguments + authenticated organization_id.

WHAT IT OUTPUTS:  ToolResult containing KPI data + DATABASE_AGGREGATION Evidence.
"""

from datetime import date
from decimal import Decimal
from typing import Any, Callable, Dict, List, Optional, Set
from sqlalchemy.orm import Session
from sqlalchemy import func, desc

from app.database.session import SessionLocal
from app.database.models import InvoiceModel, PurchaseOrderModel
from app.database.repositories.analytics_repo import AnalyticsRepository
from app.intelligence.schemas import (
    ToolName,
    ToolOperation,
    ToolResult,
    Evidence,
    EvidenceSourceType,
)
from app.intelligence.tools.base import BaseFinanceTool


class FinanceAnalyticsTool(BaseFinanceTool):
    """
    Approved Analytics operations wrapping the AnalyticsRepository and SQL aggregate queries.
    """

    tool_name = ToolName.ANALYTICS
    supported_operations: Set[ToolOperation] = {
        ToolOperation.ANALYTICS_TOTAL_SPEND,
        ToolOperation.ANALYTICS_MONTHLY_SPEND,
        ToolOperation.ANALYTICS_SPEND_BY_VENDOR,
        ToolOperation.ANALYTICS_VENDOR_TREND,
        ToolOperation.ANALYTICS_SPEND_COMPARISON,
        ToolOperation.ANALYTICS_TOP_VENDOR_SPEND,
        ToolOperation.ANALYTICS_OUTSTANDING_AMOUNT,
    }

    def __init__(self, session_factory: Callable[[], Session] = SessionLocal):
        self.session_factory = session_factory

    async def _execute(
        self,
        step_id: str,
        operation: ToolOperation,
        arguments: dict,
        organization_id: str,
    ) -> ToolResult:
        db: Session = self.session_factory()
        repo = AnalyticsRepository(db)
        try:
            if operation == ToolOperation.ANALYTICS_TOTAL_SPEND:
                summary = repo.get_dashboard_summary(organization_id)
                evidence = [
                    Evidence(
                        evidence_id=self._make_evidence_id(),
                        source_type=EvidenceSourceType.DATABASE_AGGREGATION,
                        metric={"name": "total_invoice_spend", "value": summary["total_invoice_spend"]},
                        confidence=1.0,
                        source_operation=ToolOperation.ANALYTICS_TOTAL_SPEND.value,
                    )
                ]
                return ToolResult(
                    step_id=step_id,
                    tool=self.tool_name,
                    operation=operation,
                    success=True,
                    data=summary,
                    evidence=evidence,
                    record_count=1,
                    execution_time_ms=0,
                )

            elif operation == ToolOperation.ANALYTICS_OUTSTANDING_AMOUNT:
                unpaid_sum = (
                    db.query(func.sum(InvoiceModel.amount_due))
                    .filter(
                        InvoiceModel.organization_id == organization_id,
                        func.lower(InvoiceModel.payment_status).in_(["unpaid", "pending", "partially_paid"]),
                    )
                    .scalar()
                    or Decimal("0.00")
                )
                evidence = [
                    Evidence(
                        evidence_id=self._make_evidence_id(),
                        source_type=EvidenceSourceType.DATABASE_AGGREGATION,
                        metric={"name": "outstanding_amount", "value": str(unpaid_sum)},
                        confidence=1.0,
                        source_operation=ToolOperation.ANALYTICS_OUTSTANDING_AMOUNT.value,
                    )
                ]
                return ToolResult(
                    step_id=step_id,
                    tool=self.tool_name,
                    operation=operation,
                    success=True,
                    data={"outstanding_amount": str(unpaid_sum), "currency": "INR"},
                    evidence=evidence,
                    record_count=1,
                    execution_time_ms=0,
                )

            elif operation in (
                ToolOperation.ANALYTICS_MONTHLY_SPEND,
                ToolOperation.ANALYTICS_SPEND_BY_VENDOR,
                ToolOperation.ANALYTICS_TOP_VENDOR_SPEND,
                ToolOperation.ANALYTICS_VENDOR_TREND,
                ToolOperation.ANALYTICS_SPEND_COMPARISON,
            ):
                # Aggregate directly on invoices
                q = db.query(
                    InvoiceModel.vendor_name_normalized,
                    func.sum(InvoiceModel.total_amount).label("spend"),
                    func.count(InvoiceModel.id).label("invoices"),
                ).filter(InvoiceModel.organization_id == organization_id)

                results = (
                    q.group_by(InvoiceModel.vendor_name_normalized)
                    .order_by(desc("spend"))
                    .limit(arguments.get("limit", 10))
                    .all()
                )
                rows = [
                    {"vendor": r.vendor_name_normalized or "Unknown", "spend": str(r.spend), "invoices": r.invoices}
                    for r in results
                ]
                return ToolResult(
                    step_id=step_id,
                    tool=self.tool_name,
                    operation=operation,
                    success=True,
                    data={"summary": rows},
                    evidence=[
                        Evidence(
                            evidence_id=self._make_evidence_id(),
                            source_type=EvidenceSourceType.DATABASE_AGGREGATION,
                            metric={"name": operation.value, "rows": rows},
                            confidence=1.0,
                            source_operation=operation.value,
                        )
                    ],
                    record_count=len(rows),
                    execution_time_ms=0,
                )

            else:
                return ToolResult(
                    step_id=step_id,
                    tool=self.tool_name,
                    operation=operation,
                    success=False,
                    error=f"Unhandled Analytics operation: {operation.value}",
                    execution_time_ms=0,
                )
        finally:
            db.close()
