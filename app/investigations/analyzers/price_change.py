"""
Price Change Analyzer
=====================

WHY:   Detects unit price inflation or discounts between baseline and target periods.
       Calculates exact dollar impact = (target_price - base_price) * target_qty.
"""

from decimal import Decimal
from typing import Any, Dict, List, Tuple
from app.investigations.schemas import (
    InvestigationFinding,
    FindingStatus,
    FindingSeverity,
    DriverType,
)


class PriceChangeAnalyzer:
    @staticmethod
    def analyze(matched_pairs: List[Tuple[Dict[str, Any], Dict[str, Any]]]) -> List[InvestigationFinding]:
        findings: List[InvestigationFinding] = []

        for b_item, t_item in matched_pairs:
            b_price = Decimal(str(b_item.get("unit_price") or "0.00"))
            t_price = Decimal(str(t_item.get("unit_price") or "0.00"))
            t_qty = Decimal(str(t_item.get("quantity") or "1"))

            if b_price > 0 and t_price != b_price:
                price_diff = t_price - b_price
                pct = ((price_diff / b_price) * 100).quantize(Decimal("0.01"))
                impact = (price_diff * t_qty).quantize(Decimal("0.01"))
                desc_name = t_item.get("description") or t_item.get("product_code") or "Product"

                if price_diff > 0:
                    title = f"Unit price for '{desc_name}' increased by {pct}%"
                    description = (
                        f"Unit price rose from ₹{b_price} to ₹{t_price} (+{pct}%). "
                        f"At target volume of {t_qty} units, this contributed ₹{impact} to the spend increase."
                    )
                    severity = FindingSeverity.HIGH if impact > Decimal("10000.00") else FindingSeverity.MEDIUM
                else:
                    title = f"Unit price for '{desc_name}' decreased by {abs(pct)}%"
                    description = (
                        f"Unit price dropped from ₹{b_price} to ₹{t_price} ({pct}%). "
                        f"Saved ₹{abs(impact)}."
                    )
                    severity = FindingSeverity.INFO

                findings.append(
                    InvestigationFinding(
                        finding_id=f"f_price_{len(findings)+1}",
                        finding_type=DriverType.UNIT_PRICE_CHANGE.value,
                        title=title,
                        description=description,
                        impact_amount=str(impact),
                        impact_percentage=f"{pct}%",
                        severity=severity,
                        confidence=1.0,
                        calculation={
                            "baseline_unit_price": str(b_price),
                            "target_unit_price": str(t_price),
                            "target_quantity": str(t_qty),
                            "impact_formula": "(target_price - base_price) * target_qty",
                        },
                        status=FindingStatus.CONFIRMED,
                    )
                )

        return findings
