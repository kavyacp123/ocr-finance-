"""
Investigation Context
=====================

WHY:   Multi-step investigations require an accumulating, auditable scratchpad
       that holds baseline facts, target period invoices, line items,
       delta calculations, violations, and evidence across steps.

WHERE: Maintained by the InvestigationEngine during execution.
"""

from decimal import Decimal
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

from app.intelligence.schemas import TimeRange, Evidence
from app.investigations.schemas import (
    InvestigationState,
    InvestigationFinding,
    Hypothesis,
    SpendDriver,
)


class InvestigationContext(BaseModel):
    investigation_id: str
    organization_id: str
    current_state: InvestigationState = InvestigationState.CREATED

    # Target & Baseline entities
    vendor_id: Optional[str] = None
    vendor_name: Optional[str] = None
    target_period: Optional[TimeRange] = None
    baseline_period: Optional[TimeRange] = None

    # Quantitative metrics
    baseline_spend: Decimal = Decimal("0.00")
    baseline_invoice_count: int = 0
    target_spend: Decimal = Decimal("0.00")
    target_invoice_count: int = 0
    spend_delta: Decimal = Decimal("0.00")
    spend_delta_percentage: Decimal = Decimal("0.00")

    # Invoices & Items
    baseline_invoice_ids: List[str] = Field(default_factory=list)
    target_invoice_ids: List[str] = Field(default_factory=list)
    baseline_line_items: List[Dict[str, Any]] = Field(default_factory=list)
    target_line_items: List[Dict[str, Any]] = Field(default_factory=list)

    # Analyzed outcomes
    drivers: List[SpendDriver] = Field(default_factory=list)
    findings: List[InvestigationFinding] = Field(default_factory=list)
    hypotheses: List[Hypothesis] = Field(default_factory=list)
    rule_violations: List[Dict[str, Any]] = Field(default_factory=list)
    anomalies: List[Dict[str, Any]] = Field(default_factory=list)
    evidence: List[Evidence] = Field(default_factory=list)
    unexplained_amount: Decimal = Decimal("0.00")

    # Audit & trace
    limitations: List[str] = Field(default_factory=list)
    execution_trace: List[Dict[str, Any]] = Field(default_factory=list)
    step_count: int = 0

    def record_step(self, state: InvestigationState, details: Dict[str, Any]) -> None:
        self.step_count += 1
        self.current_state = state
        self.execution_trace.append({
            "step_index": self.step_count,
            "state": state.value,
            "details": details,
        })
