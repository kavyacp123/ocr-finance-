"""
Finance Anomaly Tool
====================

WHY:   Statistical anomalies (e.g. Z-score spend outliers) must come from
       the Phase 3 AnomalyDetector or DB anomaly flags, NOT LLM speculation.

WHERE: Called by QueryExecutor when step.tool == ToolName.ANOMALY.

WHAT IT RECEIVES: Operation name + arguments + authenticated organization_id.

WHAT IT OUTPUTS:  ToolResult with anomaly flags + ANOMALY_RECORD Evidence.
"""

from typing import Any, Callable, Dict, List, Optional, Set
from sqlalchemy.orm import Session
from sqlalchemy import desc

from app.database.session import SessionLocal
from app.database.models import AnomalyFlagModel
from app.finance.analytics.anomaly_detector import AnomalyDetector
from app.intelligence.schemas import (
    ToolName,
    ToolOperation,
    ToolResult,
    Evidence,
    EvidenceSourceType,
)
from app.intelligence.tools.base import BaseFinanceTool


class FinanceAnomalyTool(BaseFinanceTool):
    """
    Approved Anomaly operations querying AnomalyFlagModel and wrapping AnomalyDetector.
    """

    tool_name = ToolName.ANOMALY
    supported_operations: Set[ToolOperation] = {
        ToolOperation.GET_VENDOR_ANOMALIES,
        ToolOperation.GET_PERIOD_ANOMALIES,
        ToolOperation.GET_INVOICE_ANOMALY_SCORE,
    }

    def __init__(
        self,
        session_factory: Callable[[], Session] = SessionLocal,
        anomaly_detector: Optional[AnomalyDetector] = None,
    ):
        self.session_factory = session_factory
        self.anomaly_detector = anomaly_detector

    async def _execute(
        self,
        step_id: str,
        operation: ToolOperation,
        arguments: dict,
        organization_id: str,
    ) -> ToolResult:
        db: Session = self.session_factory()
        try:
            q = db.query(AnomalyFlagModel).filter(
                AnomalyFlagModel.organization_id == organization_id
            )

            if operation == ToolOperation.GET_VENDOR_ANOMALIES:
                vendor_id = arguments.get("vendor_id")
                if vendor_id:
                    q = q.filter(AnomalyFlagModel.vendor_id == vendor_id)

            elif operation == ToolOperation.GET_INVOICE_ANOMALY_SCORE:
                invoice_id = arguments.get("invoice_id")
                if invoice_id:
                    q = q.filter(AnomalyFlagModel.entity_id == invoice_id)

            limit = arguments.get("limit", 50)
            flags = q.order_by(desc(AnomalyFlagModel.created_at)).limit(limit).all()

            data = [
                {
                    "flag_id": f.id,
                    "vendor_id": f.vendor_id,
                    "entity_id": f.entity_id,
                    "anomaly_type": f.anomaly_type,
                    "observed_value": str(f.observed_value),
                    "expected_mean": str(f.expected_mean) if f.expected_mean else None,
                    "z_score": str(f.z_score) if f.z_score else None,
                    "status": f.status,
                }
                for f in flags
            ]

            evidence = [
                Evidence(
                    evidence_id=self._make_evidence_id(),
                    source_type=EvidenceSourceType.ANOMALY_RECORD,
                    vendor_id=f.vendor_id,
                    invoice_id=f.entity_id if f.entity_type == "INVOICE" else None,
                    database_record={"z_score": str(f.z_score), "type": f.anomaly_type},
                    confidence=1.0,
                    source_operation=operation.value,
                )
                for f in flags
            ]

            return ToolResult(
                step_id=step_id,
                tool=self.tool_name,
                operation=operation,
                success=True,
                data={"anomalies": data, "count": len(data)},
                evidence=evidence,
                record_count=len(data),
                execution_time_ms=0,
            )
        finally:
            db.close()
