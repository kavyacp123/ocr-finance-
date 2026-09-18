import tempfile
from pathlib import Path
from fastapi import APIRouter, File, UploadFile, Query, HTTPException, Request, Body
from fastapi.responses import JSONResponse

from app.config import settings
from app.models import DocumentResult
from app.engine.pipeline import OCREngine
from app.utils.files import SUPPORTED_EXTENSIONS, UnsupportedDocumentError, DocumentRenderError
from app.utils.logging import logger
from typing import Optional, Dict, Any, List
from pydantic import BaseModel
from app.finance.schemas import PaymentCreateRequest  # needed at module level for Body() annotation
from app.finance.vector.schemas import SemanticSearchRequest  # needed at module level for Body() annotation
from app.intelligence.schemas import ConversationContext


class CopilotAskRequest(BaseModel):
    question: str
    organization_id: Optional[str] = None
    context: Optional[ConversationContext] = None
    include_query_plan: bool = False


class InvestigationRequest(BaseModel):
    question: str
    organization_id: Optional[str] = None
    scope: Optional[Dict[str, Any]] = None
    include_trace: bool = False


router = APIRouter()


@router.get("/health")
async def health_check(request: Request):
    """
    Health check endpoint verifying engine readiness and vLLM inference server reachability.
    """
    engine: OCREngine = request.app.state.ocr_engine
    vllm_reachable = await engine.vlm_client.check_health()

    status = "ok" if vllm_reachable or settings.OCR_MOCK_MODE else "degraded"

    return {
        "status": status,
        "layout_engine": settings.LAYOUT_MODEL,
        "ocr_model": settings.VLLM_MODEL,
        "inference_engine": "vLLM",
        "vllm_reachable": vllm_reachable,
        "mock_mode": settings.OCR_MOCK_MODE
    }


@router.get("/config")
async def get_config():
    """
    Returns sanitized runtime configuration.
    """
    return {
        "app_env": settings.APP_ENV,
        "pdf_dpi": settings.PDF_DPI,
        "max_pages": settings.MAX_PAGES,
        "crop_padding": settings.CROP_PADDING,
        "layout_model": settings.LAYOUT_MODEL,
        "layout_device": settings.LAYOUT_DEVICE,
        "vllm_base_url": settings.VLLM_BASE_URL,
        "vllm_model": settings.VLLM_MODEL,
        "ocr_concurrency": settings.OCR_CONCURRENCY,
        "ngram_size": settings.OCR_NGRAM_SIZE,
        "window_size": settings.OCR_WINDOW_SIZE,
        "mock_mode": settings.OCR_MOCK_MODE,
        "save_debug_artifacts": settings.SAVE_DEBUG_ARTIFACTS
    }


@router.post("/ocr", response_model=DocumentResult)
async def process_document_endpoint(
    request: Request,
    file: UploadFile = File(...),
    save_debug: bool = Query(True, description="Save layout overlays, crops, and document outputs")
):
    """
    Upload a PDF or image file (PNG/JPG) for two-stage layout-preserving OCR processing.
    """
    ext = Path(file.filename).suffix.lower()
    if ext not in SUPPORTED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file format '{ext}'. Allowed extensions: {', '.join(SUPPORTED_EXTENSIONS)}"
        )

    # Save uploaded file to isolated temporary file
    with tempfile.NamedTemporaryFile(delete=False, suffix=ext) as tmp:
        content = await file.read()
        tmp.write(content)
        tmp_path = tmp.name

    try:
        engine: OCREngine = request.app.state.ocr_engine
        result = await engine.process_document(
            file_path=tmp_path,
            output_dir=settings.OUTPUT_DIR,
            save_debug=save_debug
        )
        # Update filename in result to reflect original upload filename
        result.filename = file.filename
        return result
    except UnsupportedDocumentError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except DocumentRenderError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Error processing upload '{file.filename}': {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Internal OCR processing error: {str(e)}")
    finally:
        # Clean up temporary upload file
        p = Path(tmp_path)
        if p.exists():
            p.unlink()


# ── FINANCE PLATFORM ENDPOINTS ───────────────────────────────────────────────

@router.post("/finance/process")
async def process_finance_document_endpoint(
    request: Request,
    file: UploadFile = File(...),
    organization_id: str = Query(settings.DEFAULT_ORGANIZATION_ID, description="Tenant organization identifier"),
    save_debug: bool = Query(True, description="Save visual debug artifacts"),
):
    """
    End-to-end Finance Document Intelligence Pipeline:
    1. Upload & Register Document in short DB transaction
    2. Execute Layout-Preserving Two-Stage OCR asynchronously outside DB locks
    3. Run Document Classification (anchors, domain fields, layout, negative signals)
    4. Run Multi-Strategy Extraction (same-region, spatial neighbor, regex, table parser)
    5. Run Decimal Validation (math balance, 3-level GSTIN, date chronology)
    6. Persist Canonical Invoice, Line Items, and Provenance Evidence in short DB transaction
    """
    import hashlib
    import json
    from app.database.session import SessionLocal
    from app.database.repositories.invoice_repo import InvoiceRepository
    from app.database.repositories.po_repo import PurchaseOrderRepository
    from app.finance.classifier import DocumentClassifier
    from app.finance.extraction.extractor import FinanceExtractor
    from app.finance.extraction.po_extractor import PurchaseOrderExtractor
    from app.finance.entity_resolution.resolver import EntityResolver
    from app.finance.linking.document_linker import DocumentLinker
    from app.finance.schemas import ProcessingStatus, DocumentType

    ext = Path(file.filename).suffix.lower()
    if ext not in SUPPORTED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file format '{ext}'. Allowed extensions: {', '.join(SUPPORTED_EXTENSIONS)}"
        )

    # Save uploaded file to isolated temporary file and compute SHA256 hash
    with tempfile.NamedTemporaryFile(delete=False, suffix=ext) as tmp:
        content = await file.read()
        tmp.write(content)
        tmp_path = tmp.name

    file_hash = hashlib.sha256(content).hexdigest()

    # Step 1: Register document record in short DB transaction
    db = SessionLocal()
    repo = InvoiceRepository(db)
    from app.utils.files import generate_document_id
    doc_id = generate_document_id()
    try:
        repo.create_document_record(
            document_id=doc_id,
            filename=file.filename,
            file_hash=file_hash,
            organization_id=organization_id,
        )
    finally:
        db.close()

    # Step 2: Run OCR outside database locks
    try:
        engine: OCREngine = request.app.state.ocr_engine
        ocr_result: DocumentResult = await engine.process_document(
            file_path=tmp_path,
            output_dir=settings.OUTPUT_DIR,
            save_debug=save_debug,
        )
        # Update document_id to match registered record
        ocr_result.document_id = doc_id
        ocr_result.filename = file.filename

        # Step 3: Classify document
        classifier: DocumentClassifier = request.app.state.classifier
        classification = classifier.classify_document(ocr_result)

        db = SessionLocal()
        try:
            entity_resolver: EntityResolver = request.app.state.entity_resolver
            document_linker: DocumentLinker = request.app.state.document_linker

            if classification.document_type == DocumentType.PURCHASE_ORDER:
                po_extractor: PurchaseOrderExtractor = request.app.state.po_extractor
                po_data = po_extractor.extract_purchase_order(
                    ocr_result, classification=classification, organization_id=organization_id
                )

                # Entity resolution for PO vendor
                if po_data.vendor_name_raw and po_data.vendor_name_raw.value:
                    match_res = entity_resolver.resolve_or_create_vendor(
                        db=db,
                        organization_id=organization_id,
                        vendor_name_raw=po_data.vendor_name_raw.value,
                        vendor_tax_id=po_data.vendor_tax_id.value if po_data.vendor_tax_id else None,
                        document_id=doc_id,
                    )
                    po_data.vendor_id = match_res.canonical_vendor_id

                po_repo = PurchaseOrderRepository(db)
                inv_repo = InvoiceRepository(db)
                inv_repo.update_document_status(
                    document_id=doc_id,
                    status=ProcessingStatus.VALIDATION_COMPLETED,
                    document_type=classification.document_type.value,
                    organization_id=organization_id,
                )
                po_model = po_repo.persist_purchase_order(po_data, organization_id=organization_id)

                # Retroactive PO linking: bind any previously ingested invoices referencing this PO
                document_linker.link_po_retroactively(
                    db=db,
                    po_id=po_model.id,
                    po_number=po_model.po_number,
                    po_total=po_model.total_amount,
                    organization_id=organization_id,
                    vendor_id=po_model.vendor_id,
                )

                # Phase 4: Knowledge graph synchronization (non-blocking)
                try:
                    if hasattr(request.app.state, "graph_sync"):
                        request.app.state.graph_sync.sync_purchase_order(po_model, db)
                except Exception as ex:
                    logger.warning(f"Phase 4 graph sync failed for PO {po_model.id}: {ex}")

                # Phase 5: Vector indexing (non-blocking)
                try:
                    if hasattr(request.app.state, "vector_store") and hasattr(request.app.state, "chunker"):
                        chunker = request.app.state.chunker
                        v_store = request.app.state.vector_store
                        doc_chunks = chunker.chunk_ocr_result(doc_id, organization_id, ocr_result)
                        po_chunks = chunker.chunk_po_line_items(doc_id, organization_id, po_data)
                        v_store.add_chunks(doc_chunks + po_chunks)
                except Exception as ex:
                    logger.warning(f"Phase 5 vector indexing failed for PO {po_model.id}: {ex}")

                return po_data

            else:
                # Default to Invoice extraction
                extractor: FinanceExtractor = request.app.state.finance_extractor
                invoice_data = extractor.extract_invoice(
                    ocr_result, classification=classification, organization_id=organization_id
                )

                # Entity resolution for Invoice vendor
                if invoice_data.vendor_name_raw and invoice_data.vendor_name_raw.value:
                    match_res = entity_resolver.resolve_or_create_vendor(
                        db=db,
                        organization_id=organization_id,
                        vendor_name_raw=invoice_data.vendor_name_raw.value,
                        vendor_tax_id=invoice_data.vendor_tax_id.value if invoice_data.vendor_tax_id else None,
                        bank_account=invoice_data.bank_account.value if invoice_data.bank_account else None,
                        ifsc_swift=invoice_data.ifsc_swift.value if invoice_data.ifsc_swift else None,
                        document_id=doc_id,
                    )
                    invoice_data.vendor_id = match_res.canonical_vendor_id

                repo = InvoiceRepository(db)
                repo.update_document_status(
                    document_id=doc_id,
                    status=ProcessingStatus.VALIDATION_COMPLETED,
                    document_type=classification.document_type.value,
                    organization_id=organization_id,
                )
                inv_model = repo.persist_invoice(invoice_data, organization_id=organization_id)

                # Link invoice to PO if po_number present
                if invoice_data.po_number and invoice_data.po_number.value:
                    document_linker.link_invoice_to_po(
                        db=db,
                        invoice_id=inv_model.id,
                        po_number=invoice_data.po_number.value,
                        invoice_total=invoice_data.total_amount.value if invoice_data.total_amount else None,
                        organization_id=organization_id,
                        vendor_id=inv_model.vendor_id,
                    )

                # Phase 3: Analytics triggers (non-blocking)
                try:
                    if hasattr(request.app.state, "duplicate_detector"):
                        request.app.state.duplicate_detector.check_invoice(inv_model, db)
                    if hasattr(request.app.state, "anomaly_detector"):
                        request.app.state.anomaly_detector.check_invoice(inv_model, db)
                    if hasattr(request.app.state, "rule_engine"):
                        request.app.state.rule_engine.evaluate_invoice(inv_model, db)
                except Exception as ex:
                    logger.warning(f"Phase 3 analytics trigger failed for invoice {inv_model.id}: {ex}")

                # Phase 4: Knowledge graph synchronization (non-blocking)
                try:
                    if hasattr(request.app.state, "graph_sync"):
                        request.app.state.graph_sync.sync_invoice(inv_model, db)
                except Exception as ex:
                    logger.warning(f"Phase 4 graph sync failed for invoice {inv_model.id}: {ex}")

                # Phase 5: Vector indexing (non-blocking)
                try:
                    if hasattr(request.app.state, "vector_store") and hasattr(request.app.state, "chunker"):
                        chunker = request.app.state.chunker
                        v_store = request.app.state.vector_store
                        doc_chunks = chunker.chunk_ocr_result(doc_id, organization_id, ocr_result)
                        inv_chunks = chunker.chunk_invoice_line_items(doc_id, organization_id, invoice_data)
                        v_store.add_chunks(doc_chunks + inv_chunks)
                except Exception as ex:
                    logger.warning(f"Phase 5 vector indexing failed for invoice {inv_model.id}: {ex}")

                return invoice_data
        finally:
            db.close()

    except Exception as e:
        logger.error(f"Error in finance pipeline for '{file.filename}': {e}", exc_info=True)
        # Mark document as FAILED in short DB transaction
        db = SessionLocal()
        try:
            repo = InvoiceRepository(db)
            repo.update_document_status(
                document_id=doc_id,
                status=ProcessingStatus.FAILED,
                organization_id=organization_id,
            )
        finally:
            db.close()
        raise HTTPException(status_code=500, detail=f"Finance processing error: {str(e)}")
    finally:
        p = Path(tmp_path)
        if p.exists():
            p.unlink()


@router.post("/finance/extract/{document_id}")
async def extract_existing_document_endpoint(
    document_id: str,
    request: Request,
    organization_id: str = Query(settings.DEFAULT_ORGANIZATION_ID),
):
    """
    Re-extracts structured financial data from a previously OCR-processed document.
    Reads canonical outputs/<document_id>/document.json and re-runs extraction and persistence.
    """
    import json
    from app.database.session import SessionLocal
    from app.database.repositories.invoice_repo import InvoiceRepository
    from app.database.repositories.po_repo import PurchaseOrderRepository
    from app.finance.classifier import DocumentClassifier
    from app.finance.extraction.extractor import FinanceExtractor
    from app.finance.extraction.po_extractor import PurchaseOrderExtractor
    from app.finance.entity_resolution.resolver import EntityResolver
    from app.finance.linking.document_linker import DocumentLinker
    from app.finance.schemas import DocumentType

    json_path = Path(settings.OUTPUT_DIR) / document_id / "document.json"
    if not json_path.exists():
        raise HTTPException(status_code=404, detail=f"OCR artifacts for document '{document_id}' not found.")

    with open(json_path, "r", encoding="utf-8") as f:
        doc_dict = json.load(f)

    doc_result = DocumentResult.model_validate(doc_dict)

    classifier: DocumentClassifier = request.app.state.classifier
    classification = classifier.classify_document(doc_result)

    db = SessionLocal()
    try:
        entity_resolver: EntityResolver = request.app.state.entity_resolver
        document_linker: DocumentLinker = request.app.state.document_linker

        if classification.document_type == DocumentType.PURCHASE_ORDER:
            po_extractor: PurchaseOrderExtractor = request.app.state.po_extractor
            po_data = po_extractor.extract_purchase_order(
                doc_result, classification=classification, organization_id=organization_id
            )
            if po_data.vendor_name_raw and po_data.vendor_name_raw.value:
                match_res = entity_resolver.resolve_or_create_vendor(
                    db=db,
                    organization_id=organization_id,
                    vendor_name_raw=po_data.vendor_name_raw.value,
                    vendor_tax_id=po_data.vendor_tax_id.value if po_data.vendor_tax_id else None,
                    document_id=document_id,
                )
                po_data.vendor_id = match_res.canonical_vendor_id

            po_repo = PurchaseOrderRepository(db)
            po_model = po_repo.persist_purchase_order(po_data, organization_id=organization_id)
            document_linker.link_po_retroactively(
                db=db,
                po_id=po_model.id,
                po_number=po_model.po_number,
                po_total=po_model.total_amount,
                organization_id=organization_id,
                vendor_id=po_model.vendor_id,
            )
            return po_data

        else:
            extractor: FinanceExtractor = request.app.state.finance_extractor
            invoice_data = extractor.extract_invoice(
                doc_result, classification=classification, organization_id=organization_id
            )
            if invoice_data.vendor_name_raw and invoice_data.vendor_name_raw.value:
                match_res = entity_resolver.resolve_or_create_vendor(
                    db=db,
                    organization_id=organization_id,
                    vendor_name_raw=invoice_data.vendor_name_raw.value,
                    vendor_tax_id=invoice_data.vendor_tax_id.value if invoice_data.vendor_tax_id else None,
                    bank_account=invoice_data.bank_account.value if invoice_data.bank_account else None,
                    ifsc_swift=invoice_data.ifsc_swift.value if invoice_data.ifsc_swift else None,
                    document_id=document_id,
                )
                invoice_data.vendor_id = match_res.canonical_vendor_id

            repo = InvoiceRepository(db)
            inv_model = repo.persist_invoice(invoice_data, organization_id=organization_id)
            if invoice_data.po_number and invoice_data.po_number.value:
                document_linker.link_invoice_to_po(
                    db=db,
                    invoice_id=inv_model.id,
                    po_number=invoice_data.po_number.value,
                    invoice_total=invoice_data.total_amount.value if invoice_data.total_amount else None,
                    organization_id=organization_id,
                    vendor_id=inv_model.vendor_id,
                )
            return invoice_data
    finally:
        db.close()


@router.get("/invoices")
async def list_invoices_endpoint(
    vendor: Optional[str] = Query(None, description="Filter by vendor name (fuzzy match)"),
    status: Optional[str] = Query(None, description="Filter by payment status (paid, unpaid, overdue)"),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    organization_id: str = Query(settings.DEFAULT_ORGANIZATION_ID),
):
    """
    Retrieves paginated list of canonical invoices filtered by tenant and vendor.
    """
    from app.database.session import SessionLocal
    from app.database.repositories.invoice_repo import InvoiceRepository

    db = SessionLocal()
    try:
        repo = InvoiceRepository(db)
        invoices, total_count = repo.list_invoices(
            organization_id=organization_id,
            vendor_name=vendor,
            status=status,
            limit=limit,
            offset=offset,
        )
        return {
            "total_count": total_count,
            "limit": limit,
            "offset": offset,
            "invoices": [
                {
                    "id": inv.id,
                    "document_id": inv.document_id,
                    "invoice_number": inv.invoice_number,
                    "invoice_date": str(inv.invoice_date) if inv.invoice_date else None,
                    "due_date": str(inv.due_date) if inv.due_date else None,
                    "vendor_name": inv.vendor_name_raw,
                    "vendor_tax_id": inv.vendor_tax_id,
                    "total_amount": float(inv.total_amount) if inv.total_amount else None,
                    "currency": inv.currency,
                    "payment_status": inv.payment_status,
                    "is_valid": inv.is_valid,
                    "line_items_count": len(inv.line_items),
                    "created_at": inv.created_at.isoformat() if inv.created_at else None,
                }
                for inv in invoices
            ],
        }
    finally:
        db.close()


@router.get("/invoices/{invoice_id}")
async def get_invoice_detail_endpoint(
    invoice_id: str,
    organization_id: str = Query(settings.DEFAULT_ORGANIZATION_ID),
):
    """
    Retrieves complete invoice record including line items, validation findings,
    and field-level source provenance evidence.
    """
    import json
    from app.database.session import SessionLocal
    from app.database.repositories.invoice_repo import InvoiceRepository

    db = SessionLocal()
    try:
        repo = InvoiceRepository(db)
        inv = repo.get_invoice_by_id(invoice_id, organization_id=organization_id)
        if not inv:
            raise HTTPException(status_code=404, detail=f"Invoice '{invoice_id}' not found.")

        # Parse raw snapshot if present
        snapshot = json.loads(inv.raw_data_json) if inv.raw_data_json else None

        return {
            "id": inv.id,
            "document_id": inv.document_id,
            "invoice_number": inv.invoice_number,
            "invoice_date": str(inv.invoice_date) if inv.invoice_date else None,
            "due_date": str(inv.due_date) if inv.due_date else None,
            "po_number": inv.po_number,
            "vendor_name_raw": inv.vendor_name_raw,
            "vendor_name_normalized": inv.vendor_name_normalized,
            "vendor_tax_id": inv.vendor_tax_id,
            "buyer_name_raw": inv.buyer_name_raw,
            "buyer_tax_id": inv.buyer_tax_id,
            "currency": inv.currency,
            "subtotal": float(inv.subtotal) if inv.subtotal else None,
            "tax_amount": float(inv.tax_amount) if inv.tax_amount else None,
            "discount_amount": float(inv.discount_amount) if inv.discount_amount else None,
            "total_amount": float(inv.total_amount) if inv.total_amount else None,
            "amount_due": float(inv.amount_due) if inv.amount_due else None,
            "payment_status": inv.payment_status,
            "bank_account": inv.bank_account,
            "ifsc_swift": inv.ifsc_swift,
            "is_valid": inv.is_valid,
            "line_items": [
                {
                    "line_number": itm.line_number,
                    "description": itm.description,
                    "quantity": float(itm.quantity) if itm.quantity else None,
                    "unit_price": float(itm.unit_price) if itm.unit_price else None,
                    "total": float(itm.total) if itm.total else None,
                    "bbox": json.loads(itm.source_bbox_json) if itm.source_bbox_json else None,
                }
                for itm in inv.line_items
            ],
            "validation_issues": [
                {
                    "issue_type": iss.issue_type,
                    "severity": iss.severity,
                    "message": iss.message,
                    "field_name": iss.field_name,
                    "expected": iss.expected,
                    "actual": iss.actual,
                    "evidence": json.loads(iss.evidence_json) if iss.evidence_json else [],
                }
                for iss in inv.validation_issues
            ],
            "raw_snapshot": snapshot,
        }
    finally:
        db.close()


# ── PHASE 2 ENDPOINTS: PAYMENTS, VENDORS, PURCHASE ORDERS, GRAPH ────────────

@router.post("/finance/payments")
async def record_payment_endpoint(
    request: Request,
    payload: PaymentCreateRequest = Body(...),
    organization_id: str = Query(settings.DEFAULT_ORGANIZATION_ID),
):
    """
    Ingests payment data, creates links to referenced invoices,
    and updates invoice payment statuses (unpaid -> partially_paid -> paid -> overpaid).
    """
    from app.database.session import SessionLocal
    from app.database.repositories.payment_repo import PaymentRepository
    from app.finance.linking.document_linker import DocumentLinker
    from app.finance.schemas import PaymentRecord

    db = SessionLocal()
    try:
        pay_repo = PaymentRepository(db)
        linker: DocumentLinker = request.app.state.document_linker

        rec = PaymentRecord(
            payment_reference=payload.payment_reference,
            payment_date=payload.payment_date,
            amount=payload.amount,
            currency=payload.currency,
            payment_method=payload.payment_method,
            payer_name=payload.payer_name,
            payee_name=payload.payee_name,
            bank_account=payload.bank_account,
            ifsc_swift=payload.ifsc_swift,
            referenced_invoice_numbers=payload.referenced_invoice_numbers,
        )
        pay_model = pay_repo.create_payment(rec, organization_id=organization_id)

        # Link to invoices
        links = linker.link_payment_to_invoices(
            db=db,
            payment_id=pay_model.id,
            referenced_invoice_numbers=payload.referenced_invoice_numbers,
            payment_amount=payload.amount,
            organization_id=organization_id,
        )

        # Phase 3: Payment analytics triggers (non-blocking)
        try:
            if hasattr(request.app.state, "duplicate_detector"):
                request.app.state.duplicate_detector.check_payment(pay_model, db)
            if hasattr(request.app.state, "rule_engine"):
                request.app.state.rule_engine.evaluate_payment(pay_model, db)
        except Exception as ex:
            logger.warning(f"Phase 3 analytics trigger failed for payment {pay_model.id}: {ex}")

        # Phase 4: Knowledge graph synchronization (non-blocking)
        try:
            if hasattr(request.app.state, "graph_sync"):
                request.app.state.graph_sync.sync_payment(pay_model, db)
        except Exception as ex:
            logger.warning(f"Phase 4 graph sync failed for payment {pay_model.id}: {ex}")

        return {
            "payment_id": pay_model.id,
            "payment_reference": pay_model.payment_reference,
            "amount": float(pay_model.amount),
            "currency": pay_model.currency,
            "linked_invoices_count": len(links),
            "links": [
                {
                    "link_id": l.id,
                    "invoice_id": l.target_id,
                    "status": l.status,
                }
                for l in links
            ],
        }
    finally:
        db.close()


@router.get("/vendors")
async def list_vendors_endpoint(
    search: Optional[str] = Query(None, description="Search by name or tax ID"),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    organization_id: str = Query(settings.DEFAULT_ORGANIZATION_ID),
):
    from app.database.session import SessionLocal
    from app.database.repositories.vendor_repo import VendorRepository

    db = SessionLocal()
    try:
        repo = VendorRepository(db)
        vendors, total_count = repo.list_vendors(
            organization_id=organization_id, search=search, limit=limit, offset=offset
        )
        return {
            "total_count": total_count,
            "limit": limit,
            "offset": offset,
            "vendors": [
                {
                    "id": v.id,
                    "canonical_name": v.canonical_name,
                    "normalized_name": v.normalized_name,
                    "tax_id": v.tax_id,
                    "bank_account": v.bank_account,
                    "ifsc_swift": v.ifsc_swift,
                    "aliases_count": len(v.aliases),
                    "invoices_count": len(v.invoices),
                    "purchase_orders_count": len(v.purchase_orders),
                }
                for v in vendors
            ],
        }
    finally:
        db.close()


@router.get("/vendors/{vendor_id}")
async def get_vendor_detail_endpoint(
    vendor_id: str,
    organization_id: str = Query(settings.DEFAULT_ORGANIZATION_ID),
):
    from app.database.session import SessionLocal
    from app.database.repositories.vendor_repo import VendorRepository

    db = SessionLocal()
    try:
        repo = VendorRepository(db)
        vendor = repo.get_vendor_by_id(vendor_id, organization_id=organization_id)
        if not vendor:
            raise HTTPException(status_code=404, detail=f"Vendor '{vendor_id}' not found.")

        return {
            "id": vendor.id,
            "canonical_name": vendor.canonical_name,
            "normalized_name": vendor.normalized_name,
            "tax_id": vendor.tax_id,
            "bank_account": vendor.bank_account,
            "ifsc_swift": vendor.ifsc_swift,
            "email_domain": vendor.email_domain,
            "phone": vendor.phone,
            "address": vendor.address,
            "aliases": [a.alias_name for a in vendor.aliases],
            "invoices": [
                {
                    "id": inv.id,
                    "invoice_number": inv.invoice_number,
                    "total_amount": float(inv.total_amount) if inv.total_amount else None,
                    "payment_status": inv.payment_status,
                }
                for inv in vendor.invoices
            ],
            "purchase_orders": [
                {
                    "id": po.id,
                    "po_number": po.po_number,
                    "total_amount": float(po.total_amount) if po.total_amount else None,
                    "status": po.status,
                }
                for po in vendor.purchase_orders
            ],
        }
    finally:
        db.close()


@router.get("/purchase-orders")
async def list_purchase_orders_endpoint(
    vendor_id: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    organization_id: str = Query(settings.DEFAULT_ORGANIZATION_ID),
):
    from app.database.session import SessionLocal
    from app.database.repositories.po_repo import PurchaseOrderRepository

    db = SessionLocal()
    try:
        repo = PurchaseOrderRepository(db)
        pos, total = repo.list_purchase_orders(
            organization_id=organization_id, vendor_id=vendor_id, status=status, limit=limit, offset=offset
        )
        return {
            "total_count": total,
            "limit": limit,
            "offset": offset,
            "purchase_orders": [
                {
                    "id": p.id,
                    "po_number": p.po_number,
                    "po_date": str(p.po_date) if p.po_date else None,
                    "vendor_name": p.vendor_name_raw,
                    "vendor_id": p.vendor_id,
                    "total_amount": float(p.total_amount) if p.total_amount else None,
                    "currency": p.currency,
                    "status": p.status,
                    "line_items_count": len(p.line_items),
                }
                for p in pos
            ],
        }
    finally:
        db.close()


@router.get("/purchase-orders/{po_id}")
async def get_purchase_order_detail_endpoint(
    po_id: str,
    organization_id: str = Query(settings.DEFAULT_ORGANIZATION_ID),
):
    import json
    from app.database.session import SessionLocal
    from app.database.repositories.po_repo import PurchaseOrderRepository
    from app.database.repositories.link_repo import DocumentLinkRepository

    db = SessionLocal()
    try:
        repo = PurchaseOrderRepository(db)
        po = repo.get_po_by_id(po_id, organization_id=organization_id)
        if not po:
            raise HTTPException(status_code=404, detail=f"Purchase Order '{po_id}' not found.")

        link_repo = DocumentLinkRepository(db)
        links = link_repo.get_links_for_target("PURCHASE_ORDER", po.id, organization_id=organization_id)

        return {
            "id": po.id,
            "po_number": po.po_number,
            "po_date": str(po.po_date) if po.po_date else None,
            "expected_delivery_date": str(po.expected_delivery_date) if po.expected_delivery_date else None,
            "vendor_id": po.vendor_id,
            "vendor_name": po.vendor_name_raw,
            "vendor_tax_id": po.vendor_tax_id,
            "buyer_name": po.buyer_name_raw,
            "total_amount": float(po.total_amount) if po.total_amount else None,
            "subtotal": float(po.subtotal) if po.subtotal else None,
            "tax_amount": float(po.tax_amount) if po.tax_amount else None,
            "currency": po.currency,
            "status": po.status,
            "payment_terms": po.payment_terms,
            "line_items": [
                {
                    "line_number": itm.line_number,
                    "description": itm.description,
                    "quantity": float(itm.quantity) if itm.quantity else None,
                    "unit_price": float(itm.unit_price) if itm.unit_price else None,
                    "total": float(itm.total) if itm.total else None,
                }
                for itm in po.line_items
            ],
            "linked_invoices": [
                {
                    "link_id": l.id,
                    "invoice_id": l.source_id,
                    "status": l.status,
                    "discrepancy": json.loads(l.discrepancy_details) if l.discrepancy_details else None,
                }
                for l in links
            ],
        }
    finally:
        db.close()


@router.get("/payments")
async def list_payments_endpoint(
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    organization_id: str = Query(settings.DEFAULT_ORGANIZATION_ID),
):
    from app.database.session import SessionLocal
    from app.database.repositories.payment_repo import PaymentRepository

    db = SessionLocal()
    try:
        repo = PaymentRepository(db)
        pays, total = repo.list_payments(organization_id=organization_id, limit=limit, offset=offset)
        return {
            "total_count": total,
            "limit": limit,
            "offset": offset,
            "payments": [
                {
                    "id": p.id,
                    "payment_reference": p.payment_reference,
                    "payment_date": str(p.payment_date) if p.payment_date else None,
                    "amount": float(p.amount),
                    "currency": p.currency,
                    "payment_method": p.payment_method,
                    "payee_name": p.payee_name,
                    "status": p.status,
                }
                for p in pays
            ],
        }
    finally:
        db.close()


@router.get("/invoices/{invoice_id}/graph")
async def get_invoice_relationship_graph_endpoint(
    invoice_id: str,
    organization_id: str = Query(settings.DEFAULT_ORGANIZATION_ID),
):
    """
    Returns the complete 360-degree relationship graph for an invoice:
    Invoice <-> Canonical Vendor <-> Purchase Order <-> Payments.
    """
    import json
    from app.database.session import SessionLocal
    from app.database.repositories.invoice_repo import InvoiceRepository
    from app.database.repositories.vendor_repo import VendorRepository
    from app.database.repositories.po_repo import PurchaseOrderRepository
    from app.database.repositories.payment_repo import PaymentRepository
    from app.database.repositories.link_repo import DocumentLinkRepository

    db = SessionLocal()
    try:
        inv_repo = InvoiceRepository(db)
        inv = inv_repo.get_invoice_by_id(invoice_id, organization_id=organization_id)
        if not inv:
            raise HTTPException(status_code=404, detail=f"Invoice '{invoice_id}' not found.")

        # 1. Vendor node
        vendor_data = None
        if inv.vendor:
            vendor_data = {
                "id": inv.vendor.id,
                "canonical_name": inv.vendor.canonical_name,
                "normalized_name": inv.vendor.normalized_name,
                "tax_id": inv.vendor.tax_id,
                "bank_account": inv.vendor.bank_account,
                "ifsc_swift": inv.vendor.ifsc_swift,
                "aliases": [a.alias_name for a in inv.vendor.aliases],
            }

        # 2. Document Links for this invoice
        link_repo = DocumentLinkRepository(db)
        source_links = link_repo.get_links_for_source("INVOICE", inv.id, organization_id=organization_id)
        target_links = link_repo.get_links_for_target("INVOICE", inv.id, organization_id=organization_id)

        # 3. Linked PO details
        po_data = None
        po_link = next((l for l in source_links if l.link_type == "INVOICE_TO_PO"), None)
        if po_link:
            po_model = None
            if po_link.target_id:
                po_repo = PurchaseOrderRepository(db)
                po_model = po_repo.get_po_by_id(po_link.target_id, organization_id=organization_id)

            po_data = {
                "link_id": po_link.id,
                "status": po_link.status,
                "match_type": po_link.match_type,
                "po_number": po_model.po_number if po_model else inv.po_number,
                "po_id": po_model.id if po_model else None,
                "po_total": float(po_model.total_amount) if po_model and po_model.total_amount else None,
                "discrepancy": json.loads(po_link.discrepancy_details) if po_link.discrepancy_details else None,
            }

        # 4. Linked Payments details
        payment_links = [l for l in target_links if l.link_type == "PAYMENT_TO_INVOICE"]
        payment_repo = PaymentRepository(db)
        payments_data = []
        for pl in payment_links:
            pm = payment_repo.get_payment_by_id(pl.source_id, organization_id=organization_id)
            if pm:
                payments_data.append({
                    "link_id": pl.id,
                    "payment_id": pm.id,
                    "payment_reference": pm.payment_reference,
                    "payment_date": str(pm.payment_date) if pm.payment_date else None,
                    "amount": float(pm.amount),
                    "currency": pm.currency,
                    "payment_method": pm.payment_method,
                    "status": pm.status,
                })

        total_paid = sum((p["amount"] for p in payments_data), 0.0)

        return {
            "invoice": {
                "id": inv.id,
                "invoice_number": inv.invoice_number,
                "invoice_date": str(inv.invoice_date) if inv.invoice_date else None,
                "total_amount": float(inv.total_amount) if inv.total_amount else None,
                "currency": inv.currency,
                "payment_status": inv.payment_status,
                "total_paid": total_paid,
                "balance_due": float(inv.total_amount) - total_paid if inv.total_amount else 0.0,
            },
            "vendor": vendor_data,
            "purchase_order": po_data,
            "payments": payments_data,
            "links_summary": {
                "total_links": len(source_links) + len(target_links),
                "has_discrepancies": any(l.status == "DISCREPANCY" for l in source_links + target_links),
                "is_unresolved": any(l.status == "UNRESOLVED" for l in source_links + target_links),
            },
        }
    finally:
        db.close()


# ── PHASE 3 ENDPOINTS: ANALYTICS, VIOLATIONS, DUPLICATES, ANOMALIES ──────────

@router.get("/analytics/dashboard")
async def analytics_dashboard_endpoint(
    organization_id: str = Query(settings.DEFAULT_ORGANIZATION_ID),
):
    """
    Returns high-level financial risk and operational KPI summary for an organization.
    """
    from app.database.session import SessionLocal
    from app.database.repositories.analytics_repo import AnalyticsRepository

    db = SessionLocal()
    try:
        repo = AnalyticsRepository(db)
        return repo.get_dashboard_summary(organization_id=organization_id)
    finally:
        db.close()


@router.get("/analytics/rule-violations")
async def list_rule_violations_endpoint(
    severity: Optional[str] = Query(None, description="INFO, WARNING, or CRITICAL"),
    status: Optional[str] = Query(None, description="OPEN, ACKNOWLEDGED, or RESOLVED"),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    organization_id: str = Query(settings.DEFAULT_ORGANIZATION_ID),
):
    """
    Lists policy and business rule violations with optional severity and status filters.
    """
    from app.database.session import SessionLocal
    from app.database.repositories.analytics_repo import AnalyticsRepository

    db = SessionLocal()
    try:
        repo = AnalyticsRepository(db)
        violations = repo.list_rule_violations(
            organization_id=organization_id,
            severity=severity,
            status=status,
            limit=limit,
            offset=offset,
        )
        return {
            "total_count": len(violations),
            "violations": [
                {
                    "id": v.id,
                    "rule_id": v.rule_id,
                    "rule_name": v.rule_name,
                    "severity": v.severity,
                    "entity_type": v.entity_type,
                    "entity_id": v.entity_id,
                    "details_json": v.details_json,
                    "status": v.status,
                    "created_at": str(v.created_at),
                }
                for v in violations
            ],
        }
    finally:
        db.close()


@router.get("/analytics/duplicates")
async def list_duplicates_endpoint(
    entity_type: Optional[str] = Query(None, description="INVOICE or PAYMENT"),
    status: Optional[str] = Query(None, description="OPEN, CONFIRMED, or CLEARED"),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    organization_id: str = Query(settings.DEFAULT_ORGANIZATION_ID),
):
    """
    Lists detected duplicate candidates (invoices or payments).
    """
    from app.database.session import SessionLocal
    from app.database.repositories.analytics_repo import AnalyticsRepository

    db = SessionLocal()
    try:
        repo = AnalyticsRepository(db)
        dups = repo.list_duplicates(
            organization_id=organization_id,
            entity_type=entity_type,
            status=status,
            limit=limit,
            offset=offset,
        )
        return {
            "total_count": len(dups),
            "duplicates": [
                {
                    "id": d.id,
                    "entity_type": d.entity_type,
                    "primary_entity_id": d.primary_entity_id,
                    "duplicate_of_entity_id": d.duplicate_of_entity_id,
                    "match_type": d.match_type,
                    "similarity_score": float(d.similarity_score) if d.similarity_score else 1.0,
                    "details_json": d.details_json,
                    "status": d.status,
                    "created_at": str(d.created_at),
                }
                for d in dups
            ],
        }
    finally:
        db.close()


@router.get("/analytics/anomalies")
async def list_anomalies_endpoint(
    status: Optional[str] = Query(None, description="OPEN, REVIEWED, or CLEARED"),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    organization_id: str = Query(settings.DEFAULT_ORGANIZATION_ID),
):
    """
    Lists statistical outlier anomaly flags for invoices.
    """
    from app.database.session import SessionLocal
    from app.database.repositories.analytics_repo import AnalyticsRepository

    db = SessionLocal()
    try:
        repo = AnalyticsRepository(db)
        anomalies = repo.list_anomalies(
            organization_id=organization_id,
            status=status,
            limit=limit,
            offset=offset,
        )
        return {
            "total_count": len(anomalies),
            "anomalies": [
                {
                    "id": a.id,
                    "entity_type": a.entity_type,
                    "entity_id": a.entity_id,
                    "vendor_id": a.vendor_id,
                    "anomaly_type": a.anomaly_type,
                    "observed_value": float(a.observed_value),
                    "expected_mean": float(a.expected_mean) if a.expected_mean else None,
                    "expected_std": float(a.expected_std) if a.expected_std else None,
                    "z_score": float(a.z_score) if a.z_score else None,
                    "sample_size": a.sample_size,
                    "status": a.status,
                    "created_at": str(a.created_at),
                }
                for a in anomalies
            ],
        }
    finally:
        db.close()


# ── PHASE 4 ENDPOINTS: FINANCIAL KNOWLEDGE GRAPH & TRAVERSALS ───────────────

@router.get("/graph/stats")
async def graph_stats_endpoint(
    request: Request,
    organization_id: str = Query(settings.DEFAULT_ORGANIZATION_ID),
):
    """
    Returns high-level graph topology metrics (total nodes, total edges, labels, relationship types).
    """
    if not hasattr(request.app.state, "graph_adapter"):
        raise HTTPException(status_code=503, detail="Graph engine is not initialized.")
    adapter = request.app.state.graph_adapter
    stats = adapter.get_stats(organization_id=organization_id)
    return stats.model_dump()


@router.get("/graph/trace/{invoice_id}")
async def graph_trace_invoice_endpoint(
    invoice_id: str,
    request: Request,
    depth: int = Query(2, ge=1, le=5),
):
    """
    Extracts the connected sub-graph ego network surrounding an invoice up to `depth` hops.
    """
    if not hasattr(request.app.state, "graph_adapter"):
        raise HTTPException(status_code=503, detail="Graph engine is not initialized.")
    adapter = request.app.state.graph_adapter
    subgraph = adapter.get_subgraph(root_node_id=invoice_id, max_depth=depth)
    return subgraph.model_dump()


@router.get("/graph/vendor/{vendor_id}/network")
async def graph_vendor_network_endpoint(
    vendor_id: str,
    request: Request,
    depth: int = Query(2, ge=1, le=4),
):
    """
    Extracts all connected invoices, purchase orders, aliases, and banking nodes for a vendor.
    """
    if not hasattr(request.app.state, "graph_adapter"):
        raise HTTPException(status_code=503, detail="Graph engine is not initialized.")
    adapter = request.app.state.graph_adapter
    subgraph = adapter.get_subgraph(root_node_id=vendor_id, max_depth=depth)
    return subgraph.model_dump()


@router.get("/graph/shared-entities")
async def graph_shared_entities_endpoint(
    request: Request,
    target_type: str = Query("BankAccount", description="BankAccount or TaxIdentifier"),
    min_connections: int = Query(2, ge=2, description="Minimum number of vendors sharing this entity"),
):
    """
    Risk & Fraud analysis: detects multiple vendors sharing an identical bank account or tax ID.
    """
    if not hasattr(request.app.state, "graph_adapter"):
        raise HTTPException(status_code=503, detail="Graph engine is not initialized.")
    adapter = request.app.state.graph_adapter
    shared = adapter.find_shared_entities(
        entity_label="Vendor",
        shared_target_label=target_type,
        min_connections=min_connections,
    )
    return {
        "target_type": target_type,
        "total_shared_entities": len(shared),
        "results": [s.model_dump() for s in shared],
    }


@router.post("/graph/sync")
async def graph_sync_all_endpoint(
    request: Request,
    organization_id: str = Query(settings.DEFAULT_ORGANIZATION_ID),
):
    """
    Hydrates and rebuilds the knowledge graph from relational database tables for an organization.
    """
    if not hasattr(request.app.state, "graph_sync"):
        raise HTTPException(status_code=503, detail="Graph synchronization service is not initialized.")
    from app.database.session import SessionLocal

    db = SessionLocal()
    try:
        sync_service = request.app.state.graph_sync
        res = sync_service.sync_all(organization_id=organization_id, db=db)
        return {"status": "SUCCESS", **res}
    finally:
        db.close()


# ── PHASE 5 ENDPOINTS: SEMANTIC VECTOR SEARCH & EVIDENCE RETRIEVAL ──────────

@router.post("/search/semantic")
async def semantic_search_endpoint(
    request: Request,
    payload: SemanticSearchRequest = Body(...),
    organization_id: str = Query(settings.DEFAULT_ORGANIZATION_ID),
):
    """
    Performs semantic nearest-neighbor retrieval over documents, paragraphs, and line items.
    Returns ranked items with similarity scores and visual bounding boxes.
    """
    if not hasattr(request.app.state, "vector_store"):
        raise HTTPException(status_code=503, detail="Vector search engine is not initialized.")

    v_store = request.app.state.vector_store
    org = payload.organization_id or organization_id
    results = v_store.search(
        query=payload.query,
        organization_id=org,
        top_k=payload.top_k,
        filters=payload.filters,
    )

    return {
        "query": payload.query,
        "total_results": len(results),
        "results": [r.model_dump() for r in results],
    }


@router.get("/search/evidence/{document_id}")
async def get_document_evidence_endpoint(
    document_id: str,
    query: str = Query(..., description="Fact or phrase to prove on document"),
    top_k: int = Query(5, ge=1, le=20),
    request: Request = None,
):
    """
    Visual Provenance API: Returns bounding boxes and text snippets proving query facts on the document.
    """
    if not hasattr(request.app.state, "vector_store"):
        raise HTTPException(status_code=503, detail="Vector search engine is not initialized.")

    v_store = request.app.state.vector_store
    evidence_items = v_store.get_evidence(document_id=document_id, query=query, top_k=top_k)

    return {
        "document_id": document_id,
        "query": query,
        "evidence_count": len(evidence_items),
        "evidence": [e.model_dump() for e in evidence_items],
    }


@router.get("/search/stats")
async def search_stats_endpoint(
    request: Request,
):
    """
    Returns vector index sizing, chunk counts, and dimension metrics.
    """
    if not hasattr(request.app.state, "vector_store"):
        raise HTTPException(status_code=503, detail="Vector search engine is not initialized.")

    v_store = request.app.state.vector_store
    return v_store.get_stats()


@router.post("/copilot/ask")
@router.post("/ask")
async def copilot_ask_endpoint(
    request: Request,
    payload: CopilotAskRequest = Body(...),
    organization_id: Optional[str] = Query(None),
):
    """
    Finance Copilot Natural Language Question Answering (Phase 6).
    Routes queries deterministically to SQL, Graph, Vector, Rules, or Analytics tools,
    returning structured answers backed by provenance, metrics, and confidence.
    """
    if not hasattr(request.app.state, "copilot"):
        raise HTTPException(status_code=503, detail="Finance Copilot service is not initialized.")

    org_id = payload.organization_id or organization_id or settings.DEFAULT_ORGANIZATION_ID
    copilot_service = request.app.state.copilot

    try:
        answer, new_ctx = await copilot_service.ask(
            question=payload.question,
            organization_id=org_id,
            context=payload.context,
        )
    except Exception as e:
        logger.error(f"COPILOT_ENDPOINT_ERROR: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Copilot failed to process question: {str(e)}")

    resp = answer.model_dump()
    if not payload.include_query_plan:
        resp.pop("query_plan", None)
    resp["context"] = new_ctx.model_dump()
    return resp


@router.post("/investigate")
async def investigate_endpoint(
    request: Request,
    payload: InvestigationRequest = Body(...),
    organization_id: Optional[str] = Query(None),
):
    """
    Multi-Step Financial Investigation Engine (Phase 7).
    Executes a constrained multi-step investigation DAG:
    - Analyzes period-over-period spend deltas
    - Matches line items and computes unit price & quantity inflation
    - Cross-references duplicate candidates, rule violations, and statistical anomalies
    - Returns an auditable InvestigationReport with ranked drivers and evidence.
    """
    if not hasattr(request.app.state, "investigation_engine"):
        raise HTTPException(status_code=503, detail="Investigation engine is not initialized.")

    org_id = payload.organization_id or organization_id or settings.DEFAULT_ORGANIZATION_ID
    engine = request.app.state.investigation_engine

    try:
        report = await engine.investigate(
            question=payload.question,
            organization_id=org_id,
            scope=payload.scope,
        )
    except Exception as e:
        logger.error(f"INVESTIGATION_ENDPOINT_ERROR: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Investigation failed: {str(e)}")

    resp = report.model_dump()
    if not payload.include_trace:
        resp.pop("execution_trace", None)
    return resp



