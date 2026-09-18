"""
Investigation Finding Engine
============================

WHY:   Synthesizes and ranks drivers and findings by financial impact amount.
       Calculates unexplained_amount = total_delta - sum(explained_drivers).
       Evaluates hypotheses against gathered findings.
"""

from decimal import Decimal
from typing import List
from app.investigations.context import InvestigationContext
from app.investigations.schemas import (
    InvestigationFinding,
    SpendDriver,
    DriverType,
    HypothesisStatus,
)


class FindingEngine:
    @staticmethod
    def synthesize(context: InvestigationContext) -> None:
        # 1. Rank findings by impact amount descending
        context.findings.sort(
            key=lambda f: Decimal(f.impact_amount or "0.00") if f.impact_amount else Decimal("0.00"),
            reverse=True,
        )

        # 2. Build SpendDrivers from top findings with positive impact
        drivers: List[SpendDriver] = []
        total_explained = Decimal("0.00")

        for f in context.findings:
            if f.impact_amount and Decimal(f.impact_amount) > 0:
                dtype = DriverType.UNKNOWN
                try:
                    dtype = DriverType(f.finding_type)
                except ValueError:
                    pass

                amt = Decimal(f.impact_amount)
                total_explained += amt
                drivers.append(
                    SpendDriver(
                        type=dtype,
                        description=f.title,
                        impact_amount=str(amt),
                        evidence=[e for e in context.evidence if e.evidence_id in f.evidence_ids],
                    )
                )

        context.drivers = drivers

        # 3. Calculate unexplained residual
        delta = abs(context.spend_delta)
        unexplained = max(Decimal("0.00"), delta - total_explained)
        context.unexplained_amount = unexplained

        # 4. Evaluate hypotheses
        for hyp in context.hypotheses:
            matched_finding = next((f for f in context.findings if f.impact_amount and Decimal(f.impact_amount) > 0), None)
            if matched_finding:
                hyp.status = HypothesisStatus.SUPPORTED
                hyp.reason = f"Supported by finding '{matched_finding.title}' with impact of ₹{matched_finding.impact_amount}."
            else:
                hyp.status = HypothesisStatus.INCONCLUSIVE
                hyp.reason = "Insufficient evidence to conclusively prove or reject hypothesis."
