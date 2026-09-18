import json
from typing import List, Optional, Tuple, Dict, Any
from datetime import date
from decimal import Decimal
from sqlalchemy.orm import Session
from sqlalchemy import desc, func

from app.config import settings
from app.finance.schemas import InvoiceData, ExtractedField, ProcessingStatus
from app.database.models import (
    DocumentModel,
    InvoiceModel,
    InvoiceLineItemModel,
    ExtractedFieldModel,
    ValidationIssueModel,
)
from app.utils.logging import logger


class InvoiceRepository:
    """
    Data access repository for documents, invoices, line items, and audit provenance.
    Strictly scopes every query to organization_id for multi-tenant isolation.
    Uses short, atomic transactions.
    """

    def __init__(self, db: Session):
        self.db = db

    def create_document_record(
        self,
        document_id: str,
        filename: str,
        file_hash: Optional[str] = None,
        page_count: int = 1,
        organization_id: str = settings.DEFAULT_ORGANIZATION_ID,
        storage_uri: Optional[str] = None,
    ) -> DocumentModel:
        """
        Registers an uploaded document before compute-heavy OCR runs.
        Short transaction.
        """
        doc = DocumentModel(
            id=document_id,
            organization_id=organization_id,
            filename=filename,
            file_hash=file_hash,
            page_count=page_count,
            storage_uri=storage_uri,
            processing_status=ProcessingStatus.UPLOADED.value,
        )
        self.db.add(doc)
        self.db.commit()
        self.db.refresh(doc)
        logger.info(f"REPO: Created document record {document_id} (status=UPLOADED)")
        return doc

    def update_document_status(
        self,
        document_id: str,
        status: ProcessingStatus,
        document_type: Optional[str] = None,
        organization_id: str = settings.DEFAULT_ORGANIZATION_ID,
    ) -> None:
        """
        Updates document processing lifecycle state in a short transaction.
        """
        doc = self.db.query(DocumentModel).filter(
            DocumentModel.id == document_id,
            DocumentModel.organization_id == organization_id,
        ).first()
        if doc:
            doc.processing_status = status.value
            if document_type:
                doc.document_type = document_type
            self.db.commit()
            logger.debug(f"REPO: Document {document_id} status updated to {status.value}")

    def persist_invoice(
        self,
        invoice: InvoiceData,
        organization_id: str = settings.DEFAULT_ORGANIZATION_ID,
    ) -> InvoiceModel:
        """
        Persists canonical invoice, line items, field provenance, and validation issues
        in a single short database transaction after OCR and extraction finish.
        """
        doc_id = invoice.document_id

        # 1. Create InvoiceModel
        inv_record = InvoiceModel(
            document_id=doc_id,
            organization_id=organization_id,
            vendor_id=invoice.vendor_id,
            invoice_number=invoice.invoice_number.value if invoice.invoice_number else None,
            invoice_date=invoice.invoice_date.value if invoice.invoice_date else None,
            due_date=invoice.due_date.value if invoice.due_date else None,
            po_number=invoice.po_number.value if invoice.po_number else None,
            vendor_name_raw=invoice.vendor_name_raw.value if invoice.vendor_name_raw else None,
            vendor_name_normalized=invoice.vendor_name_normalized,
            vendor_tax_id=invoice.vendor_tax_id.value if invoice.vendor_tax_id else None,
            buyer_name_raw=invoice.buyer_name_raw.value if invoice.buyer_name_raw else None,
            buyer_name_normalized=invoice.buyer_name_normalized,
            buyer_tax_id=invoice.buyer_tax_id.value if invoice.buyer_tax_id else None,
            currency=invoice.currency.value if invoice.currency else "INR",
            subtotal=invoice.subtotal.value if invoice.subtotal else None,
            tax_amount=invoice.tax_amount.value if invoice.tax_amount else None,
            discount_amount=invoice.discount_amount.value if invoice.discount_amount else None,
            shipping_amount=invoice.shipping_amount.value if invoice.shipping_amount else None,
            total_amount=invoice.total_amount.value if invoice.total_amount else None,
            amount_due=invoice.amount_due.value if invoice.amount_due else None,
            payment_status=invoice.payment_status or "unpaid",
            payment_terms=invoice.payment_terms.value if invoice.payment_terms else None,
            bank_account=invoice.bank_account.value if invoice.bank_account else None,
            ifsc_swift=invoice.ifsc_swift.value if invoice.ifsc_swift else None,
            confidence=Decimal(str(round(invoice.confidence, 3))),
            is_valid=invoice.validation.is_valid,
            # Immutable snapshot for audit/reprocessing
            raw_data_json=invoice.model_dump_json(),
        )
        self.db.add(inv_record)
        self.db.flush()  # Populates inv_record.id

        # 2. Persist Line Items
        for itm in invoice.line_items:
            bbox_json = json.dumps(itm.source.bbox) if itm.source and itm.source.bbox else None
            line_record = InvoiceLineItemModel(
                invoice_id=inv_record.id,
                organization_id=organization_id,
                line_number=itm.line_number,
                description=itm.description,
                product_code=itm.product_code,
                quantity=itm.quantity,
                unit=itm.unit,
                unit_price=itm.unit_price,
                discount=itm.discount,
                tax_rate=itm.tax_rate,
                tax_amount=itm.tax_amount,
                total=itm.total,
                category=itm.category,
                source_bbox_json=bbox_json,
            )
            self.db.add(line_record)

        # 3. Persist Extracted Fields with Provenance
        fields_to_record = [
            invoice.invoice_number,
            invoice.invoice_date,
            invoice.due_date,
            invoice.po_number,
            invoice.vendor_name_raw,
            invoice.vendor_tax_id,
            invoice.buyer_name_raw,
            invoice.buyer_tax_id,
            invoice.subtotal,
            invoice.tax_amount,
            invoice.discount_amount,
            invoice.shipping_amount,
            invoice.total_amount,
            invoice.bank_account,
            invoice.ifsc_swift,
        ]

        for fld in fields_to_record:
            if fld and fld.value is not None:
                src = fld.source
                field_model = ExtractedFieldModel(
                    document_id=doc_id,
                    organization_id=organization_id,
                    field_name=fld.name,
                    field_value=str(fld.value),
                    raw_value=fld.raw_value or str(fld.value),
                    value_origin=fld.origin.value,
                    confidence=Decimal(str(round(fld.confidence, 3))),
                    page_number=src.page_number if src else 1,
                    region_id=src.region_id if src else None,
                    bbox_json=json.dumps(src.bbox) if src and src.bbox else None,
                    original_text=src.original_text if src else None,
                    extraction_method=fld.extraction.method if fld.extraction else None,
                )
                self.db.add(field_model)

        # 4. Persist Validation Issues
        for issue in invoice.validation.issues:
            evidence_json = (
                json.dumps([e.model_dump() for e in issue.evidence])
                if issue.evidence
                else None
            )
            issue_model = ValidationIssueModel(
                document_id=doc_id,
                invoice_id=inv_record.id,
                organization_id=organization_id,
                issue_type=issue.issue_type,
                severity=issue.severity,
                message=issue.message,
                expected=issue.expected,
                actual=issue.actual,
                field_name=issue.field_name,
                evidence_json=evidence_json,
            )
            self.db.add(issue_model)

        # 5. Update document status to PERSISTED
        doc = self.db.query(DocumentModel).filter(
            DocumentModel.id == doc_id,
            DocumentModel.organization_id == organization_id,
        ).first()
        if doc:
            doc.processing_status = ProcessingStatus.PERSISTED.value
            if invoice.classification:
                doc.document_type = invoice.classification.document_type.value

        self.db.commit()
        self.db.refresh(inv_record)
        logger.info(f"REPO: Successfully persisted invoice {inv_record.id} for document {doc_id}")
        return inv_record

    def get_invoice_by_id(
        self, invoice_id: str, organization_id: str = settings.DEFAULT_ORGANIZATION_ID
    ) -> Optional[InvoiceModel]:
        return (
            self.db.query(InvoiceModel)
            .filter(
                InvoiceModel.id == invoice_id,
                InvoiceModel.organization_id == organization_id,
            )
            .first()
        )

    def list_invoices(
        self,
        organization_id: str = settings.DEFAULT_ORGANIZATION_ID,
        vendor_name: Optional[str] = None,
        date_from: Optional[date] = None,
        date_to: Optional[date] = None,
        status: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> Tuple[List[InvoiceModel], int]:
        query = self.db.query(InvoiceModel).filter(
            InvoiceModel.organization_id == organization_id
        )

        if vendor_name:
            norm_vendor = vendor_name.lower().strip()
            query = query.filter(InvoiceModel.vendor_name_normalized.contains(norm_vendor))
        if date_from:
            query = query.filter(InvoiceModel.invoice_date >= date_from)
        if date_to:
            query = query.filter(InvoiceModel.invoice_date <= date_to)
        if status:
            query = query.filter(InvoiceModel.payment_status == status)

        total_count = query.count()
        invoices = (
            query.order_by(desc(InvoiceModel.created_at))
            .offset(offset)
            .limit(limit)
            .all()
        )
        return invoices, total_count

    def get_document_by_id(
        self, document_id: str, organization_id: str = settings.DEFAULT_ORGANIZATION_ID
    ) -> Optional[DocumentModel]:
        return (
            self.db.query(DocumentModel)
            .filter(
                DocumentModel.id == document_id,
                DocumentModel.organization_id == organization_id,
            )
            .first()
        )
