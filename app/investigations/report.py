"""
Investigation Report Builder
============================

WHY:   Builds the final structured, auditable InvestigationReport.
       Ensures that every conclusion is grounded in quantitative metrics and evidence.
"""

from decimal import Decimal
from typing import List
from app.investigations.context import InvestigationContext
from app.investigations.schemas import (
    InvestigationPlan,
    InvestigationReport,
    InvestigationPeriodSpend,
    InvestigationChangeMetric,
)
from app.investigations.confidence import InvestigationConfidenceCalculator


class InvestigationReportBuilder:
    @staticmethod
    def build(plan: InvestigationPlan, context: InvestigationContext) -> InvestigationReport:
        conf = InvestigationConfidenceCalculator.calculate(context)

        # Baseline & Target summaries
        baseline_model = None
        if context.baseline_period:
            baseline_model = InvestigationPeriodSpend(
                period=f"{context.baseline_period.start_date} to {context.baseline_period.end_date}",
                spend=str(context.baseline_spend),
                invoice_count=context.baseline_invoice_count,
            )

        target_model = None
        if context.target_period:
            target_model = InvestigationPeriodSpend(
                period=f"{context.target_period.start_date} to {context.target_period.end_date}",
                spend=str(context.target_spend),
                invoice_count=context.target_invoice_count,
            )

        direction = "INCREASE" if context.spend_delta > 0 else ("DECREASE" if context.spend_delta < 0 else "UNCHANGED")
        change_model = InvestigationChangeMetric(
            absolute=str(abs(context.spend_delta)),
            percentage=f"{abs(context.spend_delta_percentage)}%",
            direction=direction,
        )

        # Generate summary
        v_name = context.vendor_name or "the vendor"
        if direction == "INCREASE":
            summary = (
                f"{v_name} spending increased by ₹{abs(context.spend_delta)} ({abs(context.spend_delta_percentage)}%) "
                f"from ₹{context.baseline_spend} in the baseline period to ₹{context.target_spend} in the target period."
            )
        elif direction == "DECREASE":
            summary = (
                f"{v_name} spending decreased by ₹{abs(context.spend_delta)} ({abs(context.spend_delta_percentage)}%) "
                f"from ₹{context.baseline_spend} to ₹{context.target_spend}."
            )
        else:
            summary = f"{v_name} spending remained unchanged at ₹{context.target_spend}."

        # Generate conclusion
        if context.drivers:
            top_d = context.drivers[0]
            conclusion = f"The primary driver of the spend change is: {top_d.description} (impact: ₹{top_d.impact_amount})."
            if len(context.drivers) > 1:
                conclusion += f" Followed by {len(context.drivers) - 1} other contributing factor(s)."
        else:
            conclusion = "No specific line-item price or volume driver was definitively identified from the available data."

        limitations = list(context.limitations)
        if context.unexplained_amount > Decimal("0.00"):
            limitations.append(f"₹{context.unexplained_amount} of the spend delta could not be attributed to specific line items.")

        return InvestigationReport(
            investigation_id=context.investigation_id,
            investigation_type=plan.investigation_type,
            title=f"Financial Investigation: {v_name} Spending Analysis",
            summary=summary,
            subject=plan.subject,
            baseline=baseline_model,
            target=target_model,
            change=change_model,
            drivers=context.drivers,
            findings=context.findings,
            rule_violations=context.rule_violations,
            anomalies=context.anomalies,
            unexplained_amount=str(context.unexplained_amount) if context.unexplained_amount > 0 else None,
            conclusion=conclusion,
            confidence=conf,
            limitations=limitations,
            evidence=context.evidence,
            execution_trace=context.execution_trace,
        )
