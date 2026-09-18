"""
Quantity Change Analyzer
========================

WHY:   Detects usage and volume spikes (e.g. GPU compute hours jumped by 150%)
       as well as newly introduced products.
       Calculates exact volume impact = (target_qty - base_qty) * base_unit_price.
"""

from decimal import Decimal
from typing import Any, Dict, List, Tuple
from app.investigations.schemas import (
    InvestigationFinding,
    FindingStatus,
    FindingSeverity,
    DriverType,
)


class QuantityChangeAnalyzer:
    @staticmethod
    def analyze(
        matched_pairs: List[Tuple[Dict[str, Any], Dict[str, Any]]],
        new_items: List[Dict[str, Any]],
    ) -> List[InvestigationFinding]:
        findings: List[InvestigationFinding] = []

        # 1. Quantity surges on matched items
        for b_item, t_item in matched_pairs:
            b_qty = Decimal(str(b_item.get("quantity") or "1"))
            t_qty = Decimal(str(t_item.get("quantity") or "1"))
            b_price = Decimal(str(b_item.get("unit_price") or "0.00"))

            if b_qty > 0 and t_qty != b_qty:
                qty_diff = t_qty - b_qty
                pct = ((qty_diff / b_qty) * 100).quantize(Decimal("0.01"))
                impact = (qty_diff * b_price).quantize(Decimal("0.01"))
                desc_name = t_item.get("description") or t_item.get("product_code") or "Product"

                if qty_diff > 0:
                    title = f"Consumption volume for '{desc_name}' increased by {pct}%"
                    description = (
                        f"Quantity increased from {b_qty} to {t_qty} (+{pct}%). "
                        f"At baseline unit price of ₹{b_price}, this drove ₹{impact} of additional spend."
                    )
                    severity = FindingSeverity.HIGH if impact > Decimal("10000.00") else FindingSeverity.MEDIUM
                else:
                    title = f"Consumption volume for '{desc_name}' decreased by {abs(pct)}%"
                    description = f"Quantity decreased from {b_qty} to {t_qty} ({pct}%)."
                    severity = FindingSeverity.INFO

                findings.append(
                    InvestigationFinding(
                        finding_id=f"f_qty_{len(findings)+1}",
                        finding_type=DriverType.QUANTITY_CHANGE.value,
                        title=title,
                        description=description,
                        impact_amount=str(impact),
                        impact_percentage=f"{pct}%",
                        severity=severity,
                        confidence=1.0,
                        calculation={
                            "baseline_quantity": str(b_qty),
                            "target_quantity": str(t_qty),
                            "baseline_unit_price": str(b_price),
                            "impact_formula": "(target_qty - base_qty) * base_price",
                        },
                        status=FindingStatus.CONFIRMED,
                    )
                )

        # 2. Newly introduced items
        for n_item in new_items:
            total = Decimal(str(n_item.get("total") or "0.00"))
            qty = Decimal(str(n_item.get("quantity") or "1"))
            price = Decimal(str(n_item.get("unit_price") or "0.00"))
            desc_name = n_item.get("description") or n_item.get("product_code") or "New Item"

            findings.append(
                InvestigationFinding(
                    finding_id=f"f_new_{len(findings)+1}",
                    finding_type=DriverType.NEW_LINE_ITEM.value,
                    title=f"New line item '{desc_name}' introduced",
                    description=(
                        f"New product/service '{desc_name}' was billed in the target period with no baseline equivalent "
                        f"(qty={qty}, unit price=₹{price}, total impact=₹{total})."
                    ),
                    impact_amount=str(total),
                    severity=FindingSeverity.HIGH if total > Decimal("20000.00") else FindingSeverity.MEDIUM,
                    confidence=1.0,
                    calculation={
                        "quantity": str(qty),
                        "unit_price": str(price),
                        "total_amount": str(total),
                    },
                    status=FindingStatus.CONFIRMED,
                )
            )

        return findings
