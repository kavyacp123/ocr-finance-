"""
Investigation Planner
=====================

WHY:   Converts a complex financial investigation question into a structured,
       reproducible InvestigationPlan with explicit baseline and target periods,
       resolved vendor entities, initial hypotheses, and planned state machine steps.

WHERE: Called by the InvestigationEngine as the first step of an investigation.
"""

import uuid
from datetime import date, timedelta
import calendar
from typing import Any, Dict, List, Optional
from sqlalchemy.orm import Session

from app.intelligence.date_parser import DateParser
from app.intelligence.entity_parser import EntityParser
from app.intelligence.schemas import TimeRange
from app.investigations.schemas import (
    InvestigationPlan,
    InvestigationStepPlan,
    InvestigationType,
    InvestigationState,
    Hypothesis,
    HypothesisStatus,
)


class InvestigationPlanner:
    """
    Creates an InvestigationPlan from a user question and optional scope constraints.
    """

    def __init__(self):
        self.date_parser = DateParser()
        self.entity_parser = EntityParser()

    def plan(
        self,
        question: str,
        db: Session,
        organization_id: str,
        scope: Optional[Dict[str, Any]] = None,
    ) -> InvestigationPlan:
        investigation_id = f"inv_{uuid.uuid4().hex[:12]}"
        scope = scope or {}

        # 1. Resolve Entity (Vendor)
        vendor_input = scope.get("vendor") or question
        entities = self.entity_parser.parse(vendor_input, db, organization_id)
        vendor_id = entities.get("vendor_id")
        vendor_name = entities.get("vendor_name") or entities.get("vendor_name_unresolved") or "Unknown Vendor"

        # 2. Resolve Target Period
        period_input = scope.get("period") or question
        target_range = self.date_parser.parse(period_input)
        if not target_range:
            # Default to current or previous month
            today = date.today()
            first_this = today.replace(day=1)
            last_prev = first_this - timedelta(days=1)
            target_range = TimeRange(
                start_date=last_prev.replace(day=1).isoformat(),
                end_date=last_prev.isoformat(),
            )

        # 3. Derive Baseline Period (Preceding period of equal length)
        baseline_range = self._derive_baseline_period(target_range)

        # 4. Determine Investigation Type
        inv_type = self._determine_type(question)

        # 5. Build Ordered State Steps
        steps = [
            InvestigationStepPlan(step_id="step_1", state=InvestigationState.COLLECTING_BASELINE, description="Collect baseline period spend and invoices"),
            InvestigationStepPlan(step_id="step_2", state=InvestigationState.COLLECTING_TARGET_PERIOD, description="Collect target period spend, invoices, and line items"),
            InvestigationStepPlan(step_id="step_3", state=InvestigationState.COMPARING, description="Calculate absolute and percentage spend delta"),
            InvestigationStepPlan(step_id="step_4", state=InvestigationState.CHECKING_LINE_ITEMS, description="Match line items between baseline and target periods"),
            InvestigationStepPlan(step_id="step_5", state=InvestigationState.CHECKING_PRICE_CHANGE, description="Analyze unit price changes on matched items"),
            InvestigationStepPlan(step_id="step_6", state=InvestigationState.CHECKING_QUANTITY_CHANGE, description="Analyze volume/quantity spikes and new items"),
            InvestigationStepPlan(step_id="step_7", state=InvestigationState.CHECKING_DUPLICATES, description="Check for duplicate candidate invoices in target period"),
            InvestigationStepPlan(step_id="step_8", state=InvestigationState.CHECKING_RULES, description="Check for business rule violations and PO mismatches"),
            InvestigationStepPlan(step_id="step_9", state=InvestigationState.CHECKING_ANOMALIES, description="Check statistical spend outliers (Z-scores)"),
            InvestigationStepPlan(step_id="step_10", state=InvestigationState.CHECKING_RELATIONSHIPS, description="Verify PO-Invoice-Payment relationship continuity"),
            InvestigationStepPlan(step_id="step_11", state=InvestigationState.COLLECTING_EVIDENCE, description="Collect document OCR visual provenance"),
            InvestigationStepPlan(step_id="step_12", state=InvestigationState.GENERATING_FINDINGS, description="Synthesize findings, attribute drivers, and build final report"),
        ]

        # 6. Formulate Initial Hypotheses
        hypotheses = [
            Hypothesis(
                hypothesis_id="hyp_1",
                description=f"Spending change with {vendor_name} was driven by increased service consumption volume.",
                status=HypothesisStatus.UNTESTED,
            ),
            Hypothesis(
                hypothesis_id="hyp_2",
                description=f"Spending change with {vendor_name} was driven by vendor unit price inflation.",
                status=HypothesisStatus.UNTESTED,
            ),
            Hypothesis(
                hypothesis_id="hyp_3",
                description=f"Spending change with {vendor_name} was driven by newly introduced products or services.",
                status=HypothesisStatus.UNTESTED,
            ),
        ]

        return InvestigationPlan(
            investigation_id=investigation_id,
            investigation_type=inv_type,
            objective=f"Determine supported drivers of {vendor_name} spending variation in {target_range.start_date} to {target_range.end_date}.",
            subject={"vendor_id": vendor_id, "vendor_name": vendor_name},
            time_range=target_range,
            baseline_period=baseline_range,
            steps=steps,
            hypotheses=hypotheses,
            required_evidence=["DATABASE_RECORD", "DATABASE_AGGREGATION", "OCR_REGION"],
            status="PLANNED",
        )

    @staticmethod
    def _derive_baseline_period(target: TimeRange) -> TimeRange:
        s_date = date.fromisoformat(target.start_date)
        e_date = date.fromisoformat(target.end_date)
        duration_days = (e_date - s_date).days + 1

        # Check if target is a clean single calendar month
        if s_date.day == 1 and e_date.day == calendar.monthrange(e_date.year, e_date.month)[1]:
            # Baseline is previous month
            last_day_prev = s_date - timedelta(days=1)
            first_day_prev = last_day_prev.replace(day=1)
            return TimeRange(
                start_date=first_day_prev.isoformat(),
                end_date=last_day_prev.isoformat(),
            )

        # General N-day shift
        base_end = s_date - timedelta(days=1)
        base_start = base_end - timedelta(days=duration_days - 1)
        return TimeRange(
            start_date=base_start.isoformat(),
            end_date=base_end.isoformat(),
        )

    @staticmethod
    def _determine_type(question: str) -> InvestigationType:
        lower = question.lower()
        if "decrease" in lower or "drop" in lower or "reduced" in lower:
            return InvestigationType.VENDOR_SPEND_DECREASE
        if "duplicate" in lower:
            return InvestigationType.DUPLICATE_INVOICE
        if "mismatch" in lower:
            return InvestigationType.PO_MISMATCH
        if "anomaly" in lower or "unusual" in lower:
            return InvestigationType.UNUSUAL_VENDOR_ACTIVITY
        if "price" in lower or "rate" in lower:
            return InvestigationType.PRICE_CHANGE
        return InvestigationType.VENDOR_SPEND_INCREASE
