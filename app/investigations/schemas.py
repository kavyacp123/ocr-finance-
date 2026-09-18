"""
Phase 7 Investigation Schemas
==============================

WHY:   Investigations require strict data contracts for state machines,
       drivers, hypotheses, findings, and formal reports.
       No unstructured text is allowed to represent findings or impact math.

WHERE: Imported by context, state_machine, analyzers, planner, engine, report.
"""

from enum import Enum
from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field

from app.intelligence.schemas import TimeRange, Evidence


class InvestigationType(str, Enum):
    VENDOR_SPEND_INCREASE = "VENDOR_SPEND_INCREASE"
    VENDOR_SPEND_DECREASE = "VENDOR_SPEND_DECREASE"
    SUSPICIOUS_INVOICE = "SUSPICIOUS_INVOICE"
    DUPLICATE_INVOICE = "DUPLICATE_INVOICE"
    PO_MISMATCH = "PO_MISMATCH"
    PAYMENT_ANOMALY = "PAYMENT_ANOMALY"
    BANK_ACCOUNT_CHANGE = "BANK_ACCOUNT_CHANGE"
    UNUSUAL_VENDOR_ACTIVITY = "UNUSUAL_VENDOR_ACTIVITY"
    PRICE_CHANGE = "PRICE_CHANGE"
    QUANTITY_CHANGE = "QUANTITY_CHANGE"
    MISSING_PO = "MISSING_PO"
    HIGH_VALUE_INVOICE = "HIGH_VALUE_INVOICE"
    LATE_PAYMENT = "LATE_PAYMENT"
    GENERAL_VENDOR_INVESTIGATION = "GENERAL_VENDOR_INVESTIGATION"
    GENERAL_INVOICE_INVESTIGATION = "GENERAL_INVOICE_INVESTIGATION"


class InvestigationState(str, Enum):
    CREATED = "CREATED"
    PLANNING = "PLANNING"
    COLLECTING_BASELINE = "COLLECTING_BASELINE"
    COLLECTING_TARGET_PERIOD = "COLLECTING_TARGET_PERIOD"
    COMPARING = "COMPARING"
    CHECKING_LINE_ITEMS = "CHECKING_LINE_ITEMS"
    CHECKING_PRICE_CHANGE = "CHECKING_PRICE_CHANGE"
    CHECKING_QUANTITY_CHANGE = "CHECKING_QUANTITY_CHANGE"
    CHECKING_DUPLICATES = "CHECKING_DUPLICATES"
    CHECKING_RULES = "CHECKING_RULES"
    CHECKING_ANOMALIES = "CHECKING_ANOMALIES"
    CHECKING_RELATIONSHIPS = "CHECKING_RELATIONSHIPS"
    COLLECTING_EVIDENCE = "COLLECTING_EVIDENCE"
    GENERATING_FINDINGS = "GENERATING_FINDINGS"
    COMPLETED = "COMPLETED"
    PARTIAL = "PARTIAL"
    FAILED = "FAILED"


class DriverType(str, Enum):
    INVOICE_COUNT_CHANGE = "INVOICE_COUNT_CHANGE"
    QUANTITY_CHANGE = "QUANTITY_CHANGE"
    UNIT_PRICE_CHANGE = "UNIT_PRICE_CHANGE"
    NEW_LINE_ITEM = "NEW_LINE_ITEM"
    REMOVED_LINE_ITEM = "REMOVED_LINE_ITEM"
    TAX_CHANGE = "TAX_CHANGE"
    DISCOUNT_CHANGE = "DISCOUNT_CHANGE"
    ONE_TIME_CHARGE = "ONE_TIME_CHARGE"
    CREDIT_NOTE_CHANGE = "CREDIT_NOTE_CHANGE"
    DUPLICATE_INVOICE = "DUPLICATE_INVOICE"
    PO_MISMATCH = "PO_MISMATCH"
    UNKNOWN = "UNKNOWN"


class FindingStatus(str, Enum):
    CONFIRMED = "CONFIRMED"
    SUPPORTED = "SUPPORTED"
    POSSIBLE = "POSSIBLE"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"


class FindingSeverity(str, Enum):
    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    INFO = "INFO"


class HypothesisStatus(str, Enum):
    UNTESTED = "UNTESTED"
    SUPPORTED = "SUPPORTED"
    REJECTED = "REJECTED"
    INCONCLUSIVE = "INCONCLUSIVE"


class Hypothesis(BaseModel):
    hypothesis_id: str
    description: str
    status: HypothesisStatus = HypothesisStatus.UNTESTED
    reason: Optional[str] = None
    supporting_evidence_ids: List[str] = Field(default_factory=list)


class InvestigationFinding(BaseModel):
    finding_id: str
    finding_type: str  # e.g., DriverType or rule violation
    title: str
    description: str
    impact_amount: Optional[str] = None
    impact_percentage: Optional[str] = None
    severity: FindingSeverity = FindingSeverity.INFO
    confidence: float = 1.0
    evidence_ids: List[str] = Field(default_factory=list)
    calculation: Optional[Dict[str, Any]] = None
    status: FindingStatus = FindingStatus.SUPPORTED


class InvestigationStepPlan(BaseModel):
    step_id: str
    state: InvestigationState
    description: str
    required: bool = True


class InvestigationPlan(BaseModel):
    investigation_id: str
    investigation_type: InvestigationType
    objective: str
    subject: Dict[str, Any]  # e.g. {"vendor_id": "...", "vendor_name": "..."}
    time_range: TimeRange
    baseline_period: Optional[TimeRange] = None
    steps: List[InvestigationStepPlan] = Field(default_factory=list)
    hypotheses: List[Hypothesis] = Field(default_factory=list)
    required_evidence: List[str] = Field(default_factory=list)
    status: str = "PLANNED"


class InvestigationPeriodSpend(BaseModel):
    period: str
    spend: str
    invoice_count: int = 0


class InvestigationChangeMetric(BaseModel):
    absolute: str
    percentage: str
    direction: str  # "INCREASE", "DECREASE", "UNCHANGED"


class SpendDriver(BaseModel):
    type: DriverType
    description: str
    impact_amount: str
    evidence: List[Evidence] = Field(default_factory=list)


class InvestigationReport(BaseModel):
    investigation_id: str
    investigation_type: InvestigationType
    title: str
    summary: str
    subject: Dict[str, Any]
    baseline: Optional[InvestigationPeriodSpend] = None
    target: Optional[InvestigationPeriodSpend] = None
    change: Optional[InvestigationChangeMetric] = None
    drivers: List[SpendDriver] = Field(default_factory=list)
    findings: List[InvestigationFinding] = Field(default_factory=list)
    rule_violations: List[Dict[str, Any]] = Field(default_factory=list)
    anomalies: List[Dict[str, Any]] = Field(default_factory=list)
    unexplained_amount: Optional[str] = None
    conclusion: str
    confidence: float
    limitations: List[str] = Field(default_factory=list)
    evidence: List[Evidence] = Field(default_factory=list)
    execution_trace: List[Dict[str, Any]] = Field(default_factory=list)
