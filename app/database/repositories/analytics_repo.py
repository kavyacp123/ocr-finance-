from decimal import Decimal
from typing import List, Dict, Any, Optional
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.database.models import (
    InvoiceModel,
    PurchaseOrderModel,
    RuleViolationModel,
    DuplicateCandidateModel,
    AnomalyFlagModel,
)


class AnalyticsRepository:
    """
    Repository for Phase 3 Finance Analytics & Insights.
    Performs pure SQL aggregations for dashboard summary and inspection.
    """

    def __init__(self, db: Session):
        self.db = db

    def get_dashboard_summary(self, organization_id: str) -> Dict[str, Any]:
        total_invoices = (
            self.db.query(func.count(InvoiceModel.id))
            .filter(InvoiceModel.organization_id == organization_id)
            .scalar()
            or 0
        )
        total_pos = (
            self.db.query(func.count(PurchaseOrderModel.id))
            .filter(PurchaseOrderModel.organization_id == organization_id)
            .scalar()
            or 0
        )
        open_violations = (
            self.db.query(func.count(RuleViolationModel.id))
            .filter(
                RuleViolationModel.organization_id == organization_id,
                RuleViolationModel.status == "OPEN",
            )
            .scalar()
            or 0
        )
        open_duplicates = (
            self.db.query(func.count(DuplicateCandidateModel.id))
            .filter(
                DuplicateCandidateModel.organization_id == organization_id,
                DuplicateCandidateModel.status == "OPEN",
            )
            .scalar()
            or 0
        )
        open_anomalies = (
            self.db.query(func.count(AnomalyFlagModel.id))
            .filter(
                AnomalyFlagModel.organization_id == organization_id,
                AnomalyFlagModel.status == "OPEN",
            )
            .scalar()
            or 0
        )
        total_invoice_spend = (
            self.db.query(func.sum(InvoiceModel.total_amount))
            .filter(InvoiceModel.organization_id == organization_id)
            .scalar()
            or Decimal("0.00")
        )

        return {
            "organization_id": organization_id,
            "total_invoices": total_invoices,
            "total_purchase_orders": total_pos,
            "open_violations_count": open_violations,
            "open_duplicates_count": open_duplicates,
            "open_anomalies_count": open_anomalies,
            "total_invoice_spend": float(total_invoice_spend),
        }

    def list_rule_violations(
        self,
        organization_id: str,
        severity: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> List[RuleViolationModel]:
        q = self.db.query(RuleViolationModel).filter(RuleViolationModel.organization_id == organization_id)
        if severity:
            q = q.filter(RuleViolationModel.severity == severity.upper())
        if status:
            q = q.filter(RuleViolationModel.status == status.upper())
        return q.order_by(RuleViolationModel.created_at.desc()).offset(offset).limit(limit).all()

    def list_duplicates(
        self,
        organization_id: str,
        entity_type: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> List[DuplicateCandidateModel]:
        q = self.db.query(DuplicateCandidateModel).filter(DuplicateCandidateModel.organization_id == organization_id)
        if entity_type:
            q = q.filter(DuplicateCandidateModel.entity_type == entity_type.upper())
        if status:
            q = q.filter(DuplicateCandidateModel.status == status.upper())
        return q.order_by(DuplicateCandidateModel.created_at.desc()).offset(offset).limit(limit).all()

    def list_anomalies(
        self,
        organization_id: str,
        status: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> List[AnomalyFlagModel]:
        q = self.db.query(AnomalyFlagModel).filter(AnomalyFlagModel.organization_id == organization_id)
        if status:
            q = q.filter(AnomalyFlagModel.status == status.upper())
        return q.order_by(AnomalyFlagModel.created_at.desc()).offset(offset).limit(limit).all()
