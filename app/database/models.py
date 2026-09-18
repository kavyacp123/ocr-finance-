import uuid
from datetime import datetime, date
from decimal import Decimal
from typing import List, Optional
from sqlalchemy import (
    Column,
    String,
    Integer,
    Numeric,
    DateTime,
    Date,
    Text,
    ForeignKey,
    Boolean,
    Index,
)
from sqlalchemy.orm import declarative_base, relationship

from app.config import settings

Base = declarative_base()


class DocumentModel(Base):
    """
    Tracks uploaded documents, file metadata, multi-tenancy, and processing lifecycle.
    """
    __tablename__ = "documents"

    id = Column(String(64), primary_key=True)
    organization_id = Column(String(64), nullable=False, index=True, default=settings.DEFAULT_ORGANIZATION_ID)
    filename = Column(String(255), nullable=False)
    storage_uri = Column(String(512), nullable=True)
    file_hash = Column(String(64), nullable=True, index=True)
    document_type = Column(String(32), nullable=True, index=True, default="UNKNOWN")
    page_count = Column(Integer, default=1)
    processing_status = Column(String(32), nullable=False, index=True, default="UPLOADED")

    # Versioning
    ocr_engine_version = Column(String(32), default="vLLM/Unlimited-OCR")
    extractor_version = Column(String(32), default=settings.FINANCE_EXTRACTOR_VERSION)
    schema_version = Column(String(32), default=settings.FINANCE_SCHEMA_VERSION)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    # Relationships
    invoices = relationship("InvoiceModel", back_populates="document", cascade="all, delete-orphan")
    purchase_orders = relationship("PurchaseOrderModel", back_populates="document", cascade="all, delete-orphan")
    extracted_fields = relationship("ExtractedFieldModel", back_populates="document", cascade="all, delete-orphan")
    validation_issues = relationship("ValidationIssueModel", back_populates="document", cascade="all, delete-orphan")


class VendorModel(Base):
    """
    Canonical vendor entity repository.
    Enforces multi-tenancy and preserves legal display name vs search keys.
    """
    __tablename__ = "vendors"

    id = Column(String(64), primary_key=True, default=lambda: f"ven_{uuid.uuid4().hex[:12]}")
    organization_id = Column(String(64), nullable=False, index=True, default=settings.DEFAULT_ORGANIZATION_ID)

    canonical_name = Column(String(255), nullable=False, index=True)
    normalized_name = Column(String(255), nullable=False, index=True)
    tax_id = Column(String(32), nullable=True, index=True)  # GSTIN, TIN, PAN, VAT
    bank_account = Column(String(64), nullable=True)
    ifsc_swift = Column(String(32), nullable=True)
    email_domain = Column(String(128), nullable=True, index=True)
    phone = Column(String(32), nullable=True)
    address = Column(Text, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    # Relationships
    aliases = relationship("VendorAliasModel", back_populates="vendor", cascade="all, delete-orphan")
    invoices = relationship("InvoiceModel", back_populates="vendor")
    purchase_orders = relationship("PurchaseOrderModel", back_populates="vendor")
    possible_matches = relationship("PossibleEntityMatchModel", back_populates="vendor")

    __table_args__ = (
        Index("ix_vendors_org_norm", "organization_id", "normalized_name"),
        Index("ix_vendors_org_tax", "organization_id", "tax_id"),
    )


class VendorAliasModel(Base):
    """
    Known aliases, alternative spellings, or brand names for canonical vendors.
    """
    __tablename__ = "vendor_aliases"

    id = Column(String(64), primary_key=True, default=lambda: f"alias_{uuid.uuid4().hex[:12]}")
    vendor_id = Column(String(64), ForeignKey("vendors.id", ondelete="CASCADE"), nullable=False, index=True)
    organization_id = Column(String(64), nullable=False, index=True, default=settings.DEFAULT_ORGANIZATION_ID)

    alias_name = Column(String(255), nullable=False)
    normalized_alias = Column(String(255), nullable=False, index=True)
    source_document_id = Column(String(64), nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    vendor = relationship("VendorModel", back_populates="aliases")

    __table_args__ = (
        Index("ix_aliases_org_norm", "organization_id", "normalized_alias"),
    )


class PossibleEntityMatchModel(Base):
    """
    Queue for ambiguous vendor entity matches (fuzzy score 0.65-0.87).
    Never auto-merges; stores candidates for human review.
    """
    __tablename__ = "possible_entity_matches"

    id = Column(String(64), primary_key=True, default=lambda: f"pem_{uuid.uuid4().hex[:12]}")
    organization_id = Column(String(64), nullable=False, index=True, default=settings.DEFAULT_ORGANIZATION_ID)
    matched_vendor_id = Column(String(64), ForeignKey("vendors.id", ondelete="CASCADE"), nullable=False, index=True)

    candidate_name = Column(String(255), nullable=False)
    match_score = Column(Numeric(4, 3), nullable=False)
    match_reason = Column(String(255), nullable=False)
    status = Column(String(32), default="PENDING_REVIEW", index=True)  # PENDING_REVIEW, APPROVED, REJECTED
    source_document_id = Column(String(64), nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    vendor = relationship("VendorModel", back_populates="possible_matches")


class InvoiceModel(Base):
    """
    Primary relational store for canonical invoice data.
    Uses Numeric(15, 2) for all financial currency amounts. Never float!
    """
    __tablename__ = "invoices"

    id = Column(String(64), primary_key=True, default=lambda: f"inv_{uuid.uuid4().hex[:12]}")
    document_id = Column(String(64), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True)
    organization_id = Column(String(64), nullable=False, index=True, default=settings.DEFAULT_ORGANIZATION_ID)
    vendor_id = Column(String(64), ForeignKey("vendors.id", ondelete="SET NULL"), nullable=True, index=True)

    # Identification
    invoice_number = Column(String(100), nullable=True, index=True)
    invoice_date = Column(Date, nullable=True, index=True)
    due_date = Column(Date, nullable=True, index=True)
    po_number = Column(String(100), nullable=True, index=True)

    # Dual Vendor Identity
    vendor_name_raw = Column(String(255), nullable=True, index=True)
    vendor_name_normalized = Column(String(255), nullable=True, index=True)
    vendor_tax_id = Column(String(32), nullable=True, index=True)  # GSTIN, TIN, VAT

    # Buyer Identity
    buyer_name_raw = Column(String(255), nullable=True)
    buyer_name_normalized = Column(String(255), nullable=True)
    buyer_tax_id = Column(String(32), nullable=True)

    # Monetary amounts (strict Decimal representation)
    currency = Column(String(8), default="INR", nullable=False)
    subtotal = Column(Numeric(15, 2), nullable=True)
    tax_amount = Column(Numeric(15, 2), nullable=True)
    discount_amount = Column(Numeric(15, 2), nullable=True)
    shipping_amount = Column(Numeric(15, 2), nullable=True)
    total_amount = Column(Numeric(15, 2), nullable=True, index=True)
    amount_due = Column(Numeric(15, 2), nullable=True)

    # Status and terms
    payment_status = Column(String(32), default="unpaid", index=True)
    payment_terms = Column(String(100), nullable=True)
    bank_account = Column(String(64), nullable=True)
    ifsc_swift = Column(String(32), nullable=True)

    # Validation and confidence
    confidence = Column(Numeric(4, 3), default=1.0)
    is_valid = Column(Boolean, default=True, index=True)

    # Immutable full snapshot for debugging & future reprocessing
    raw_data_json = Column(Text, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    # Relationships
    document = relationship("DocumentModel", back_populates="invoices")
    vendor = relationship("VendorModel", back_populates="invoices")
    line_items = relationship("InvoiceLineItemModel", back_populates="invoice", cascade="all, delete-orphan")
    validation_issues = relationship("ValidationIssueModel", back_populates="invoice", cascade="all, delete-orphan")

    __table_args__ = (
        Index("ix_invoices_org_vendor", "organization_id", "vendor_name_normalized"),
        Index("ix_invoices_org_date", "organization_id", "invoice_date"),
    )


class InvoiceLineItemModel(Base):
    """
    Relational line item records with Numeric fields for price, qty, and total.
    """
    __tablename__ = "invoice_line_items"

    id = Column(String(64), primary_key=True, default=lambda: f"item_{uuid.uuid4().hex[:12]}")
    invoice_id = Column(String(64), ForeignKey("invoices.id", ondelete="CASCADE"), nullable=False, index=True)
    organization_id = Column(String(64), nullable=False, index=True, default=settings.DEFAULT_ORGANIZATION_ID)

    line_number = Column(Integer, nullable=False)
    description = Column(Text, nullable=True)
    product_code = Column(String(64), nullable=True)
    quantity = Column(Numeric(15, 4), nullable=True)
    unit = Column(String(32), nullable=True)
    unit_price = Column(Numeric(15, 2), nullable=True)
    discount = Column(Numeric(15, 2), nullable=True)
    tax_rate = Column(Numeric(5, 2), nullable=True)
    tax_amount = Column(Numeric(15, 2), nullable=True)
    total = Column(Numeric(15, 2), nullable=True)
    category = Column(String(64), nullable=True)

    # Source bounding box metadata
    source_bbox_json = Column(Text, nullable=True)

    invoice = relationship("InvoiceModel", back_populates="line_items")


class ExtractedFieldModel(Base):
    """
    Field-level provenance and auditability table.
    Stores bounding box coordinates, page number, region ID, and extraction method for every extracted field.
    """
    __tablename__ = "extracted_fields"

    id = Column(String(64), primary_key=True, default=lambda: f"field_{uuid.uuid4().hex[:12]}")
    document_id = Column(String(64), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True)
    organization_id = Column(String(64), nullable=False, index=True, default=settings.DEFAULT_ORGANIZATION_ID)

    field_name = Column(String(64), nullable=False, index=True)
    field_value = Column(Text, nullable=True)
    raw_value = Column(Text, nullable=True)
    value_origin = Column(String(32), default="EXTRACTED")  # EXTRACTED, DERIVED, USER_CORRECTED
    confidence = Column(Numeric(4, 3), default=1.0)

    # Source Provenance
    page_number = Column(Integer, default=1)
    region_id = Column(String(64), nullable=True)
    bbox_json = Column(Text, nullable=True)  # JSON array [x1, y1, x2, y2]
    original_text = Column(Text, nullable=True)
    extraction_method = Column(String(64), nullable=True)
    extractor_version = Column(String(32), default=settings.FINANCE_EXTRACTOR_VERSION)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    document = relationship("DocumentModel", back_populates="extracted_fields")


class ValidationIssueModel(Base):
    """
    Tracks validation findings and audit discrepancies.
    """
    __tablename__ = "validation_issues"

    id = Column(String(64), primary_key=True, default=lambda: f"issue_{uuid.uuid4().hex[:12]}")
    document_id = Column(String(64), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True)
    invoice_id = Column(String(64), ForeignKey("invoices.id", ondelete="CASCADE"), nullable=True, index=True)
    organization_id = Column(String(64), nullable=False, index=True, default=settings.DEFAULT_ORGANIZATION_ID)

    issue_type = Column(String(64), nullable=False, index=True)
    severity = Column(String(16), nullable=False, index=True)  # info, low, medium, high, critical
    message = Column(Text, nullable=False)
    expected = Column(String(128), nullable=True)
    actual = Column(String(128), nullable=True)
    field_name = Column(String(64), nullable=True)

    # Multi-source evidence JSON
    evidence_json = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    document = relationship("DocumentModel", back_populates="validation_issues")
    invoice = relationship("InvoiceModel", back_populates="validation_issues")


# ── PHASE 2 MODELS: PURCHASE ORDERS, PAYMENTS, DOCUMENT LINKS ─────────────────

class PurchaseOrderModel(Base):
    """
    Relational store for Purchase Orders.
    """
    __tablename__ = "purchase_orders"

    id = Column(String(64), primary_key=True, default=lambda: f"po_{uuid.uuid4().hex[:12]}")
    document_id = Column(String(64), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True)
    organization_id = Column(String(64), nullable=False, index=True, default=settings.DEFAULT_ORGANIZATION_ID)
    vendor_id = Column(String(64), ForeignKey("vendors.id", ondelete="SET NULL"), nullable=True, index=True)

    po_number = Column(String(100), nullable=False, index=True)
    po_date = Column(Date, nullable=True, index=True)
    expected_delivery_date = Column(Date, nullable=True)

    # Vendor Identity
    vendor_name_raw = Column(String(255), nullable=True)
    vendor_name_normalized = Column(String(255), nullable=True, index=True)
    vendor_tax_id = Column(String(32), nullable=True)

    # Buyer Identity
    buyer_name_raw = Column(String(255), nullable=True)
    buyer_name_normalized = Column(String(255), nullable=True)
    buyer_tax_id = Column(String(32), nullable=True)

    # Monetary amounts (strict Decimal representation)
    currency = Column(String(8), default="INR", nullable=False)
    subtotal = Column(Numeric(15, 2), nullable=True)
    tax_amount = Column(Numeric(15, 2), nullable=True)
    total_amount = Column(Numeric(15, 2), nullable=True, index=True)

    status = Column(String(32), default="OPEN", index=True)  # OPEN, PARTIALLY_FULFILLED, FULFILLED, CANCELLED
    payment_terms = Column(String(100), nullable=True)
    shipping_address = Column(Text, nullable=True)
    billing_address = Column(Text, nullable=True)

    confidence = Column(Numeric(4, 3), default=1.0)
    is_valid = Column(Boolean, default=True, index=True)
    raw_data_json = Column(Text, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    # Relationships
    document = relationship("DocumentModel", back_populates="purchase_orders")
    vendor = relationship("VendorModel", back_populates="purchase_orders")
    line_items = relationship("PurchaseOrderLineItemModel", back_populates="purchase_order", cascade="all, delete-orphan")

    __table_args__ = (
        Index("ix_po_org_num", "organization_id", "po_number"),
    )


class PurchaseOrderLineItemModel(Base):
    """
    Relational line item records for Purchase Orders.
    """
    __tablename__ = "purchase_order_line_items"

    id = Column(String(64), primary_key=True, default=lambda: f"po_item_{uuid.uuid4().hex[:12]}")
    purchase_order_id = Column(String(64), ForeignKey("purchase_orders.id", ondelete="CASCADE"), nullable=False, index=True)
    organization_id = Column(String(64), nullable=False, index=True, default=settings.DEFAULT_ORGANIZATION_ID)

    line_number = Column(Integer, nullable=False)
    description = Column(Text, nullable=True)
    product_code = Column(String(64), nullable=True)
    quantity = Column(Numeric(15, 4), nullable=True)
    unit = Column(String(32), nullable=True)
    unit_price = Column(Numeric(15, 2), nullable=True)
    tax_rate = Column(Numeric(5, 2), nullable=True)
    tax_amount = Column(Numeric(15, 2), nullable=True)
    total = Column(Numeric(15, 2), nullable=True)
    source_bbox_json = Column(Text, nullable=True)

    purchase_order = relationship("PurchaseOrderModel", back_populates="line_items")


class PaymentModel(Base):
    """
    Relational records for payments (checks, wires, UTRs, ACH).
    """
    __tablename__ = "payments"

    id = Column(String(64), primary_key=True, default=lambda: f"pay_{uuid.uuid4().hex[:12]}")
    document_id = Column(String(64), ForeignKey("documents.id", ondelete="SET NULL"), nullable=True, index=True)
    organization_id = Column(String(64), nullable=False, index=True, default=settings.DEFAULT_ORGANIZATION_ID)
    vendor_id = Column(String(64), ForeignKey("vendors.id", ondelete="SET NULL"), nullable=True, index=True)

    payment_reference = Column(String(100), nullable=False, index=True)
    payment_date = Column(Date, nullable=True, index=True)
    amount = Column(Numeric(15, 2), nullable=False)
    currency = Column(String(8), default="INR", nullable=False)
    payment_method = Column(String(32), default="NEFT")  # NEFT, RTGS, CHEQUE, ACH, WIRE, CARD
    payer_name = Column(String(255), nullable=True)
    payee_name = Column(String(255), nullable=True)
    bank_account = Column(String(64), nullable=True)
    ifsc_swift = Column(String(32), nullable=True)
    status = Column(String(32), default="COMPLETED", index=True)  # COMPLETED, PENDING, BOUNCED

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    vendor = relationship("VendorModel")

    __table_args__ = (
        Index("ix_payments_org_ref", "organization_id", "payment_reference"),
    )


class DocumentLinkModel(Base):
    """
    Deterministic relationship store connecting Invoices, Purchase Orders, Payments, etc.
    Tracks match types, variance, and status (LINKED, UNRESOLVED, DISCREPANCY).
    """
    __tablename__ = "document_links"

    id = Column(String(64), primary_key=True, default=lambda: f"link_{uuid.uuid4().hex[:12]}")
    organization_id = Column(String(64), nullable=False, index=True, default=settings.DEFAULT_ORGANIZATION_ID)

    link_type = Column(String(64), nullable=False, index=True)  # INVOICE_TO_PO, PAYMENT_TO_INVOICE
    source_type = Column(String(32), nullable=False)  # INVOICE, PAYMENT
    source_id = Column(String(64), nullable=False, index=True)
    target_type = Column(String(32), nullable=False)  # PURCHASE_ORDER, INVOICE
    target_id = Column(String(64), nullable=True, index=True)  # Nullable for UNRESOLVED

    match_type = Column(String(64), nullable=False)  # EXACT_IDENTIFIER, FUZZY_MATCH, UNRESOLVED_REFERENCE
    confidence = Column(Numeric(4, 3), default=1.0)
    status = Column(String(32), nullable=False, default="LINKED", index=True)  # LINKED, UNRESOLVED, DISCREPANCY

    discrepancy_details = Column(Text, nullable=True)  # JSON details of variance

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    __table_args__ = (
        Index("ix_doc_links_source", "organization_id", "source_type", "source_id"),
        Index("ix_doc_links_target", "organization_id", "target_type", "target_id"),
    )


class RuleViolationModel(Base):
    """
    Records deterministic policy/rule violations for an entity (Invoice, Payment, PO).
    """
    __tablename__ = "rule_violations"

    id = Column(String(64), primary_key=True, default=lambda: f"rv_{uuid.uuid4().hex[:12]}")
    organization_id = Column(String(64), nullable=False, index=True, default=settings.DEFAULT_ORGANIZATION_ID)

    rule_id = Column(String(64), nullable=False, index=True)
    rule_name = Column(String(128), nullable=False)
    severity = Column(String(16), nullable=False, default="WARNING", index=True)  # INFO, WARNING, CRITICAL
    entity_type = Column(String(32), nullable=False, index=True)  # INVOICE, PAYMENT, PURCHASE_ORDER
    entity_id = Column(String(64), nullable=False, index=True)

    details_json = Column(Text, nullable=True)
    status = Column(String(32), nullable=False, default="OPEN", index=True)  # OPEN, ACKNOWLEDGED, RESOLVED

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)


class DuplicateCandidateModel(Base):
    """
    Records detected duplicate invoices or payments.
    """
    __tablename__ = "duplicate_candidates"

    id = Column(String(64), primary_key=True, default=lambda: f"dup_{uuid.uuid4().hex[:12]}")
    organization_id = Column(String(64), nullable=False, index=True, default=settings.DEFAULT_ORGANIZATION_ID)

    entity_type = Column(String(32), nullable=False, index=True)  # INVOICE, PAYMENT
    primary_entity_id = Column(String(64), nullable=False, index=True)  # New / suspect record
    duplicate_of_entity_id = Column(String(64), nullable=False, index=True)  # Existing original record

    match_type = Column(String(32), nullable=False, default="EXACT")  # EXACT, PROBABLE
    similarity_score = Column(Numeric(4, 3), default=1.0)
    details_json = Column(Text, nullable=True)
    status = Column(String(32), nullable=False, default="OPEN", index=True)  # OPEN, CONFIRMED, CLEARED

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class AnomalyFlagModel(Base):
    """
    Records statistical anomalies (e.g. invoice amount outlier for a vendor).
    """
    __tablename__ = "anomaly_flags"

    id = Column(String(64), primary_key=True, default=lambda: f"anm_{uuid.uuid4().hex[:12]}")
    organization_id = Column(String(64), nullable=False, index=True, default=settings.DEFAULT_ORGANIZATION_ID)

    entity_type = Column(String(32), nullable=False, default="INVOICE", index=True)
    entity_id = Column(String(64), nullable=False, index=True)
    vendor_id = Column(String(64), ForeignKey("vendors.id", ondelete="SET NULL"), nullable=True, index=True)

    anomaly_type = Column(String(32), nullable=False, default="HIGH_AMOUNT")  # HIGH_AMOUNT, LOW_AMOUNT
    observed_value = Column(Numeric(15, 2), nullable=False)
    expected_mean = Column(Numeric(15, 2), nullable=True)
    expected_std = Column(Numeric(15, 2), nullable=True)
    z_score = Column(Numeric(6, 2), nullable=True)
    sample_size = Column(Integer, nullable=False, default=0)
    status = Column(String(32), nullable=False, default="OPEN", index=True)  # OPEN, REVIEWED, CLEARED

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

