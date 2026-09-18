"""
Spend Delta Analyzer
====================

WHY:   Calculates exact absolute and percentage spend variations between
       baseline and target periods using Python Decimal arithmetic.
       Never permits LLM calculations.
"""

from decimal import Decimal
from typing import Dict, Any
from app.investigations.context import InvestigationContext


class SpendDeltaAnalyzer:
    @staticmethod
    def analyze(context: InvestigationContext) -> Dict[str, Any]:
        base = context.baseline_spend
        target = context.target_spend
        delta = target - base

        if base > 0:
            pct = ((delta / base) * 100).quantize(Decimal("0.01"))
        else:
            pct = Decimal("100.00") if target > 0 else Decimal("0.00")

        direction = "UNCHANGED"
        if delta > 0:
            direction = "INCREASE"
        elif delta < 0:
            direction = "DECREASE"

        context.spend_delta = delta
        context.spend_delta_percentage = pct

        return {
            "baseline_spend": str(base),
            "target_spend": str(target),
            "absolute_change": str(delta),
            "percentage_change": str(pct),
            "direction": direction,
        }
