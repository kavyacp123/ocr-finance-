from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Generic, TypeVar, Optional, List, Dict, Any
from pydantic import BaseModel, Field

from app.config import settings

T = TypeVar("T")


class DocumentType(str, Enum):
    INVOICE = "INVOICE"
    PURCHASE_ORDER = "PURCHASE_ORDER"
    CREDIT_NOTE = "CREDIT_NOTE"
    RECEIPT = "RECEIPT"
    PAYMENT_ADVICE = "PAYMENT_ADVICE"
    CONTRACT = "CONTRACT"
    BANK_STATEMENT = "BANK_STATEMENT"
    EXPENSE_REPORT = "EXPENSE_REPORT"
    UNKNOWN = "UNKNOWN"


class ProcessingStatus(str, Enum):
    UPLOADED = "UPLOADED"
    OCR_PROCESSING = "OCR_PROCESSING"
    OCR_COMPLETED = "OCR_COMPLETED"
    CLASSIFICATION_COMPLETED = "CLASSIFICATION_COMPLETED"
    EXTRACTION_COMPLETED = "EXTRACTION_COMPLETED"
    VALIDATION_COMPLETED = "VALIDATION_COMPLETED"
    PERSISTED = "PERSISTED"
    FAILED = "FAILED"


class ValueOrigin(str, Enum):
    EXTRACTED = "EXTRACTED"
    DERIVED = "DERIVED"
    USER_CORRECTED = "USER_CORRECTED"


class SourceReference(BaseModel):
    """
    Field-level provenance pointing back to the visual evidence in the document.
    """
    document_id: str
    page_number: int
    region_id: str
    bbox: List[int] = Field(..., description="[x1, y1, x2, y2] bounding box coordinates")
    polygon: List[List[int]] = Field(default_factory=list, description="Polygon boundary vertices if available")
    original_text: str = Field(..., description="Original OCR text extracted from this region")


class ExtractionDetails(BaseModel):
    method: str = Field(..., description="Extraction strategy, e.g., 'same_region', 'spatial_proximity', 'table_row', 'regex_fallback'")
    extractor_version: str = Field(default_factory=lambda: settings.FINANCE_EXTRACTOR_VERSION)
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)


class ExtractedField(BaseModel, Generic[T]):
    """
    Generic wrapper for every extracted financial field.
    Preserves value, raw unparsed text, explicit origin, confidence, and source provenance.
    """
    name: str
    value: Optional[T] = None
    raw_value: Optional[str] = None
    origin: ValueOrigin = ValueOrigin.EXTRACTED
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    source: Optional[SourceReference] = None
    extraction: Optional[ExtractionDetails] = None
    derived_from: List[str] = Field(default_factory=list, description="List of field names this value was derived from if origin==DERIVED")


class InvoiceLineItem(BaseModel):
    """
    Individual line item extracted from an invoice table.
    Uses Decimal for all monetary amounts and rates.
    """
    line_number: int
    description: Optional[str] = None
    product_code: Optional[str] = None
    quantity: Optional[Decimal] = None
    unit: Optional[str] = None
    unit_price: Optional[Decimal] = None
    discount: Optional[Decimal] = None
    tax_rate: Optional[Decimal] = None
    tax_amount: Optional[Decimal] = None
    total: Optional[Decimal] = None
    category: Optional[str] = None
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    source: Optional[SourceReference] = None


class ValidationIssue(BaseModel):
    """
    Validation finding or audit discrepancy.
    Non-blocking: extraction succeeds while issues are flagged for human review or analytics.
    """
    issue_type: str = Field(..., description="E.g. MATH_TOTAL_MISMATCH, GSTIN_INVALID_CHECKSUM, FUTURE_INVOICE_DATE")
    severity: str = Field(..., description="'info', 'low', 'medium', 'high', 'critical'")
    message: str
    expected: Optional[str] = None
    actual: Optional[str] = None
    field_name: Optional[str] = None
    evidence: List[SourceReference] = Field(default_factory=list, description="Multi-region evidence supporting this finding")


class ValidationResult(BaseModel):
    is_valid: bool = True
    issues: List[ValidationIssue] = Field(default_factory=list)


class ClassificationResult(BaseModel):
    document_type: DocumentType = DocumentType.UNKNOWN
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    matched_keywords: List[str] = Field(default_factory=list)
    negative_signals: List[str] = Field(default_factory=list)
    signals: Dict[str, Any] = Field(default_factory=dict)
    reason: str = ""


class InvoiceData(BaseModel):
    """
    Canonical strongly-typed invoice representation.
    Preserves both raw legal names and normalized search keys.
    """
    document_id: str
    organization_id: str = Field(default_factory=lambda: settings.DEFAULT_ORGANIZATION_ID)

    # Core identification
    invoice_number: Optional[ExtractedField[str]] = None
    invoice_date: Optional[ExtractedField[date]] = None
    due_date: Optional[ExtractedField[date]] = None
    po_number: Optional[ExtractedField[str]] = None

    # Vendor Identity (dual representation: raw legal name vs normalized matching key)
    vendor_id: Optional[str] = None  # Resolved Canonical Vendor ID
    vendor_name_raw: Optional[ExtractedField[str]] = None
    vendor_name_normalized: Optional[str] = None
    vendor_tax_id: Optional[ExtractedField[str]] = None  # GSTIN, TIN, VAT ID

    # Buyer Identity
    buyer_name_raw: Optional[ExtractedField[str]] = None
    buyer_name_normalized: Optional[str] = None
    buyer_tax_id: Optional[ExtractedField[str]] = None

    # Financial Totals (all Decimal)
    currency: Optional[ExtractedField[str]] = None
    subtotal: Optional[ExtractedField[Decimal]] = None
    tax_amount: Optional[ExtractedField[Decimal]] = None
    discount_amount: Optional[ExtractedField[Decimal]] = None
    shipping_amount: Optional[ExtractedField[Decimal]] = None
    total_amount: Optional[ExtractedField[Decimal]] = None
    amount_due: Optional[ExtractedField[Decimal]] = None

    # Payment & Banking
    payment_status: str = "unpaid"
    payment_terms: Optional[ExtractedField[str]] = None
    bank_account: Optional[ExtractedField[str]] = None
    ifsc_swift: Optional[ExtractedField[str]] = None

    # Addresses
    billing_address: Optional[ExtractedField[str]] = None
    shipping_address: Optional[ExtractedField[str]] = None

    # Line Items
    line_items: List[InvoiceLineItem] = Field(default_factory=list)

    # Audit, Classification & Validation Metadata
    classification: Optional[ClassificationResult] = None
    validation: ValidationResult = Field(default_factory=ValidationResult)
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    schema_version: str = Field(default_factory=lambda: settings.FINANCE_SCHEMA_VERSION)
    extractor_version: str = Field(default_factory=lambda: settings.FINANCE_EXTRACTOR_VERSION)
    processed_at: datetime = Field(default_factory=datetime.utcnow)


# ── PHASE 2 SCHEMAS ─────────────────────────────────────────────────────────

class PurchaseOrderLineItem(BaseModel):
    """
    Individual line item extracted from a Purchase Order table.
    Strict Decimal representation for all rates and amounts.
    """
    line_number: int
    description: Optional[str] = None
    product_code: Optional[str] = None
    quantity: Optional[Decimal] = None
    unit: Optional[str] = None
    unit_price: Optional[Decimal] = None
    tax_rate: Optional[Decimal] = None
    tax_amount: Optional[Decimal] = None
    total: Optional[Decimal] = None
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    source: Optional[SourceReference] = None


class PurchaseOrderData(BaseModel):
    """
    Canonical strongly-typed Purchase Order representation.
    """
    document_id: str
    organization_id: str = Field(default_factory=lambda: settings.DEFAULT_ORGANIZATION_ID)

    # Core identification
    po_number: Optional[ExtractedField[str]] = None
    po_date: Optional[ExtractedField[date]] = None
    expected_delivery_date: Optional[ExtractedField[date]] = None

    # Vendor Identity
    vendor_id: Optional[str] = None  # Resolved Canonical Vendor ID
    vendor_name_raw: Optional[ExtractedField[str]] = None
    vendor_name_normalized: Optional[str] = None
    vendor_tax_id: Optional[ExtractedField[str]] = None

    # Buyer Identity
    buyer_name_raw: Optional[ExtractedField[str]] = None
    buyer_name_normalized: Optional[str] = None
    buyer_tax_id: Optional[ExtractedField[str]] = None

    # Addresses & Terms
    shipping_address: Optional[ExtractedField[str]] = None
    billing_address: Optional[ExtractedField[str]] = None
    payment_terms: Optional[ExtractedField[str]] = None

    # Financial Totals (Decimal)
    currency: Optional[ExtractedField[str]] = None
    subtotal: Optional[ExtractedField[Decimal]] = None
    tax_amount: Optional[ExtractedField[Decimal]] = None
    total_amount: Optional[ExtractedField[Decimal]] = None

    # Status
    status: str = "OPEN"

    # Line Items
    line_items: List[PurchaseOrderLineItem] = Field(default_factory=list)

    # Audit & Validation Metadata
    classification: Optional[ClassificationResult] = None
    validation: ValidationResult = Field(default_factory=ValidationResult)
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    schema_version: str = Field(default_factory=lambda: settings.FINANCE_SCHEMA_VERSION)
    extractor_version: str = Field(default_factory=lambda: settings.FINANCE_EXTRACTOR_VERSION)
    processed_at: datetime = Field(default_factory=datetime.utcnow)


class PaymentRecord(BaseModel):
    """
    Canonical record for payments (checks, wires, UTRs, ACH).
    """
    payment_reference: str
    payment_date: Optional[date] = None
    amount: Decimal
    currency: str = "INR"
    payment_method: str = "NEFT"
    payer_name: Optional[str] = None
    payee_name: Optional[str] = None
    vendor_id: Optional[str] = None
    bank_account: Optional[str] = None
    ifsc_swift: Optional[str] = None
    referenced_invoice_numbers: List[str] = Field(default_factory=list)
    status: str = "COMPLETED"


class PaymentCreateRequest(BaseModel):
    """
    API request payload for recording a payment.
    """
    payment_reference: str
    payment_date: Optional[date] = None
    amount: Decimal
    currency: str = "INR"
    payment_method: str = "NEFT"
    payer_name: Optional[str] = None
    payee_name: Optional[str] = None
    bank_account: Optional[str] = None
    ifsc_swift: Optional[str] = None
    referenced_invoice_numbers: List[str] = Field(default_factory=list)


class EntityMatchResult(BaseModel):
    """
    Result of vendor entity resolution.
    """
    canonical_vendor_id: str
    canonical_name: str
    normalized_name: str
    match_type: str  # TAX_ID, BANK_ACCOUNT, NORMALIZED_NAME, ALIAS, FUZZY_SIMILARITY, NEW_VENDOR
    confidence: float
    is_new_vendor: bool = False
    needs_review: bool = False
    matched_alias: Optional[str] = None


class DocumentLinkInfo(BaseModel):
    """
    Relationship representation between financial documents.
    """
    id: str
    link_type: str  # INVOICE_TO_PO, PAYMENT_TO_INVOICE, CREDIT_NOTE_TO_INVOICE
    source_type: str
    source_id: str
    target_type: str
    target_id: Optional[str] = None
    match_type: str
    confidence: float
    status: str  # LINKED, UNRESOLVED, DISCREPANCY
    discrepancy_details: Optional[Dict[str, Any]] = None
    created_at: Optional[datetime] = None
