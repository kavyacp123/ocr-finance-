"""
Investigation Confidence Calculator
===================================

WHY:   Investigation confidence must be calculated from factual completeness,
       not arbitrary LLM estimation.
       Factors:
         - Attribution coverage: (explained_delta / total_delta)
         - Line item matching quality
         - Supporting evidence presence
"""

from decimal import Decimal
from typing import List
from app.investigations.context import InvestigationContext


class InvestigationConfidenceCalculator:
    @staticmethod
    def calculate(context: InvestigationContext) -> float:
        delta = abs(context.spend_delta)
        if delta == Decimal("0.00"):
            return 1.0

        # 1. Coverage factor: how much of the delta is explained by identified drivers?
        explained = sum(
            Decimal(d.impact_amount) for d in context.drivers
            if d.impact_amount and Decimal(d.impact_amount) > 0
        )
        coverage = min(1.0, float(explained / delta)) if delta > 0 else 1.0

        # 2. Evidence factor: do we have backing evidence?
        evidence_factor = 1.0 if len(context.evidence) >= 2 else (0.75 if context.evidence else 0.5)

        # 3. Data availability: were target invoices found?
        data_factor = 1.0 if context.target_invoice_ids else 0.4

        combined = 0.5 * coverage + 0.3 * evidence_factor + 0.2 * data_factor
        return round(max(0.1, min(1.0, combined)), 2)
