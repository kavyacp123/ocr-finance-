"""
Phase 6 Intelligence Schemas
=============================

WHY:   Every component in the Finance Copilot pipeline communicates through
       strongly-typed models.  Free-form dicts are never passed between layers.
       This prevents the LLM or any tool from injecting unexpected fields and
       ensures every answer is auditable.

WHERE: Imported by planner, executor, tools, answer_generator, copilot.

WHAT IT DEFINES:
  - QueryIntent        — business-level meaning of a question
  - ToolName           — which subsystem to call
  - ToolOperation      — the specific approved operation within a tool
  - EvidenceSourceType — provenance category for every fact
  - TimeRange          — explicit date boundaries (never ambiguous)
  - QueryStep          — one node in the execution DAG
  - QueryPlan          — the full execution plan emitted by the planner
  - Evidence           — a single provenance record
  - ToolResult         — the standardised envelope every tool returns
  - FinanceAnswer      — the structured response sent to the user
"""

from enum import Enum
from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field


# ─── Enums ────────────────────────────────────────────────────────────────────

class QueryIntent(str, Enum):
    """Business-level intent of a user question."""
    TOTAL_SPEND = "TOTAL_SPEND"
    VENDOR_SPEND = "VENDOR_SPEND"
    MONTHLY_SPEND = "MONTHLY_SPEND"
    SPEND_COMPARISON = "SPEND_COMPARISON"
    TOP_VENDORS = "TOP_VENDORS"
    UNPAID_INVOICES = "UNPAID_INVOICES"
    OVERDUE_INVOICES = "OVERDUE_INVOICES"
    INVOICE_LOOKUP = "INVOICE_LOOKUP"
    PO_LOOKUP = "PO_LOOKUP"
    PAYMENT_LOOKUP = "PAYMENT_LOOKUP"
    ENTITY_RELATIONSHIP = "ENTITY_RELATIONSHIP"
    SEMANTIC_DOCUMENT_SEARCH = "SEMANTIC_DOCUMENT_SEARCH"
    LINE_ITEM_SEARCH = "LINE_ITEM_SEARCH"
    RULE_VIOLATIONS = "RULE_VIOLATIONS"
    ANOMALIES = "ANOMALIES"
    SPEND_CHANGE_EXPLANATION = "SPEND_CHANGE_EXPLANATION"
    DOCUMENT_EVIDENCE = "DOCUMENT_EVIDENCE"
    GENERAL_FINANCE_QUERY = "GENERAL_FINANCE_QUERY"
    INVESTIGATION_REQUEST = "INVESTIGATION_REQUEST"
    UNKNOWN = "UNKNOWN"


class ToolName(str, Enum):
    """Approved subsystems that the query executor may invoke."""
    SQL = "SQL"
    GRAPH = "GRAPH"
    VECTOR = "VECTOR"
    RULES = "RULES"
    ANALYTICS = "ANALYTICS"
    ANOMALY = "ANOMALY"
    DOCUMENT = "DOCUMENT"


class ToolOperation(str, Enum):
    """
    Approved operations within each tool.
    The query planner produces these — the executor maps them to trusted
    Python methods.  No arbitrary SQL is ever generated.
    """

    # ── SQL / Data-access operations ──────────────────────────────────────
    GET_VENDOR_TOTAL_SPEND = "GET_VENDOR_TOTAL_SPEND"
    GET_MONTHLY_VENDOR_SPEND = "GET_MONTHLY_VENDOR_SPEND"
    GET_VENDOR_INVOICE_COUNT = "GET_VENDOR_INVOICE_COUNT"
    GET_UNPAID_INVOICES = "GET_UNPAID_INVOICES"
    GET_OVERDUE_INVOICES = "GET_OVERDUE_INVOICES"
    GET_INVOICE_BY_NUMBER = "GET_INVOICE_BY_NUMBER"
    GET_PURCHASE_ORDER = "GET_PURCHASE_ORDER"
    GET_PAYMENTS_FOR_INVOICE = "GET_PAYMENTS_FOR_INVOICE"
    GET_TOP_VENDORS = "GET_TOP_VENDORS"
    GET_INVOICES_FOR_PERIOD = "GET_INVOICES_FOR_PERIOD"
    GET_INVOICE_LINE_ITEMS = "GET_INVOICE_LINE_ITEMS"
    COMPARE_VENDOR_SPEND = "COMPARE_VENDOR_SPEND"

    # ── Graph operations ──────────────────────────────────────────────────
    GET_INVOICE_RELATIONSHIPS = "GET_INVOICE_RELATIONSHIPS"
    GET_VENDOR_NETWORK = "GET_VENDOR_NETWORK"
    GET_INVOICE_PO = "GET_INVOICE_PO"
    GET_INVOICE_PAYMENTS = "GET_INVOICE_PAYMENTS"
    GET_VENDOR_BANK_ACCOUNTS = "GET_VENDOR_BANK_ACCOUNTS"
    GET_CONNECTED_DOCUMENTS = "GET_CONNECTED_DOCUMENTS"
    GET_ENTITY_NEIGHBORHOOD = "GET_ENTITY_NEIGHBORHOOD"
    FIND_PATH = "FIND_PATH"

    # ── Vector / Semantic operations ──────────────────────────────────────
    SEMANTIC_SEARCH = "SEMANTIC_SEARCH"
    LINE_ITEM_SEARCH = "LINE_ITEM_SEARCH"
    DOCUMENT_SEARCH = "DOCUMENT_SEARCH"
    EVIDENCE_SEARCH = "EVIDENCE_SEARCH"

    # ── Rules operations ──────────────────────────────────────────────────
    GET_DOCUMENT_RULE_VIOLATIONS = "GET_DOCUMENT_RULE_VIOLATIONS"
    GET_VENDOR_RULE_VIOLATIONS = "GET_VENDOR_RULE_VIOLATIONS"
    GET_PERIOD_RULE_VIOLATIONS = "GET_PERIOD_RULE_VIOLATIONS"
    GET_PO_MISMATCHES = "GET_PO_MISMATCHES"
    GET_MISSING_PO_INVOICES = "GET_MISSING_PO_INVOICES"

    # ── Analytics / Aggregation operations ────────────────────────────────
    ANALYTICS_TOTAL_SPEND = "ANALYTICS_TOTAL_SPEND"
    ANALYTICS_MONTHLY_SPEND = "ANALYTICS_MONTHLY_SPEND"
    ANALYTICS_SPEND_BY_VENDOR = "ANALYTICS_SPEND_BY_VENDOR"
    ANALYTICS_VENDOR_TREND = "ANALYTICS_VENDOR_TREND"
    ANALYTICS_SPEND_COMPARISON = "ANALYTICS_SPEND_COMPARISON"
    ANALYTICS_TOP_VENDOR_SPEND = "ANALYTICS_TOP_VENDOR_SPEND"
    ANALYTICS_OUTSTANDING_AMOUNT = "ANALYTICS_OUTSTANDING_AMOUNT"

    # ── Anomaly operations ────────────────────────────────────────────────
    GET_VENDOR_ANOMALIES = "GET_VENDOR_ANOMALIES"
    GET_PERIOD_ANOMALIES = "GET_PERIOD_ANOMALIES"
    GET_INVOICE_ANOMALY_SCORE = "GET_INVOICE_ANOMALY_SCORE"


class EvidenceSourceType(str, Enum):
    """Provenance category — tells the user WHERE a fact came from."""
    OCR_REGION = "OCR_REGION"
    DATABASE_RECORD = "DATABASE_RECORD"
    DATABASE_AGGREGATION = "DATABASE_AGGREGATION"
    GRAPH_PATH = "GRAPH_PATH"
    VECTOR_CHUNK = "VECTOR_CHUNK"
    RULE_VIOLATION = "RULE_VIOLATION"
    ANOMALY_RECORD = "ANOMALY_RECORD"
    SYSTEM_CALCULATION = "SYSTEM_CALCULATION"


# ─── Core Models ──────────────────────────────────────────────────────────────

class TimeRange(BaseModel):
    """Explicit, unambiguous date boundaries."""
    start_date: str  # ISO format YYYY-MM-DD
    end_date: str    # ISO format YYYY-MM-DD


class QueryStep(BaseModel):
    """
    One node in the execution DAG.
    `depends_on` lists step_ids whose ToolResult must be available
    before this step executes.
    """
    step_id: str
    tool: ToolName
    operation: ToolOperation
    arguments: Dict[str, Any] = Field(default_factory=dict)
    depends_on: List[str] = Field(default_factory=list)
    optional: bool = False
    description: str = ""


class QueryPlan(BaseModel):
    """
    The full execution plan emitted by the planner.
    Captures the original question, extracted entities, resolved dates,
    and an ordered list of steps (a DAG) to execute.
    """
    query_id: str
    original_question: str
    normalized_question: str
    intent: QueryIntent
    entities: Dict[str, Any] = Field(default_factory=dict)
    time_range: Optional[TimeRange] = None
    steps: List[QueryStep] = Field(default_factory=list)
    requires_reasoning: bool = False
    requires_evidence: bool = True
    ambiguities: List[str] = Field(default_factory=list)
    planner_confidence: float = 1.0


class Evidence(BaseModel):
    """
    A single provenance record.
    Not every field is populated — depends on `source_type`.
    """
    evidence_id: str
    source_type: EvidenceSourceType
    document_id: Optional[str] = None
    invoice_id: Optional[str] = None
    po_id: Optional[str] = None
    payment_id: Optional[str] = None
    vendor_id: Optional[str] = None
    page_number: Optional[int] = None
    region_id: Optional[str] = None
    bbox: Optional[List[float]] = None
    source_text: Optional[str] = None
    database_record: Optional[Dict[str, Any]] = None
    graph_path: Optional[Dict[str, Any]] = None
    metric: Optional[Dict[str, Any]] = None
    confidence: float = 1.0
    source_operation: Optional[str] = None


class ToolResult(BaseModel):
    """
    Standardised envelope that every tool returns.
    The executor collects these and passes them to the answer generator.
    """
    step_id: str
    tool: ToolName
    operation: ToolOperation
    success: bool
    data: Any = None
    evidence: List[Evidence] = Field(default_factory=list)
    error: Optional[str] = None
    execution_time_ms: float = 0.0
    record_count: int = 0
    metadata: Dict[str, Any] = Field(default_factory=dict)


class FinanceAnswer(BaseModel):
    """
    The structured response sent to the user.
    Every field in `metrics` and `findings` is backed by `evidence`.
    The `limitations` field explicitly states what could NOT be determined.
    """
    query_id: str
    question: str
    answer: str
    intent: QueryIntent
    metrics: List[Dict[str, Any]] = Field(default_factory=list)
    findings: List[Dict[str, Any]] = Field(default_factory=list)
    evidence: List[Evidence] = Field(default_factory=list)
    confidence: float = 1.0
    limitations: List[str] = Field(default_factory=list)
    query_plan: Optional[QueryPlan] = None


class ConversationContext(BaseModel):
    """
    Lightweight structured state for follow-up questions.
    We store resolved entities — never raw chat history.
    """
    last_vendor_id: Optional[str] = None
    last_vendor_name: Optional[str] = None
    last_date_range: Optional[TimeRange] = None
    last_intent: Optional[QueryIntent] = None
    last_invoice_id: Optional[str] = None
    last_po_id: Optional[str] = None
    last_query_id: Optional[str] = None
