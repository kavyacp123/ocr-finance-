from typing import List, Optional, Dict, Any
from app.models import DocumentResult, PageResult
from app.finance.schemas import InvoiceData, PurchaseOrderData, InvoiceLineItem, PurchaseOrderLineItem
from app.finance.vector.schemas import VectorChunk


class DocumentChunker:
    """
    Layout-aware chunking engine for financial documents and line items.
    Preserves exact page numbers, region IDs, and visual bounding boxes.
    """

    def chunk_ocr_result(
        self,
        doc_id: str,
        organization_id: str,
        ocr_result: DocumentResult,
    ) -> List[VectorChunk]:
        chunks: List[VectorChunk] = []

        for page in ocr_result.pages:
            # 1. Full page text chunk (if full page mode was used)
            if page.full_page_ocr and page.full_page_ocr.text:
                full_text = page.full_page_ocr.text.strip()
                if full_text:
                    chunks.append(
                        VectorChunk(
                            chunk_id=f"{doc_id}_p{page.page_number}_fullpage",
                            document_id=doc_id,
                            organization_id=organization_id,
                            chunk_type="DOCUMENT_TEXT",
                            text=full_text,
                            page_number=page.page_number,
                            region_id=f"p{page.page_number}_fullpage",
                            bbox=[0, 0, page.width, page.height],
                            metadata={"is_full_page": True},
                        )
                    )

            # 2. Individual layout region chunks
            for region in page.regions:
                text = (region.clean_content or region.raw_ocr_output or "").strip()
                if not text:
                    continue

                bbox = [region.bbox.x1, region.bbox.y1, region.bbox.x2, region.bbox.y2] if region.bbox else None
                chunks.append(
                    VectorChunk(
                        chunk_id=f"{doc_id}_{region.id}",
                        document_id=doc_id,
                        organization_id=organization_id,
                        chunk_type="DOCUMENT_TEXT",
                        text=text,
                        page_number=page.page_number,
                        region_id=region.id,
                        bbox=bbox,
                        metadata={
                            "region_type": region.region_type,
                            "reading_order": region.reading_order,
                        },
                    )
                )

        return chunks

    def chunk_invoice_line_items(
        self,
        doc_id: str,
        organization_id: str,
        invoice_data: InvoiceData,
    ) -> List[VectorChunk]:
        chunks: List[VectorChunk] = []

        for idx, item in enumerate(invoice_data.line_items):
            desc = item.description or "Line Item"
            qty_str = f"Qty: {item.quantity}" if item.quantity is not None else ""
            price_str = f"Unit Price: {item.unit_price}" if item.unit_price is not None else ""
            tot_str = f"Total: {item.total}" if item.total is not None else ""

            parts = [desc, qty_str, price_str, tot_str]
            semantic_text = " | ".join(p for p in parts if p)

            bbox = item.source.bbox if (item.source and item.source.bbox) else None
            page = item.source.page_number if (item.source and item.source.page_number) else 1
            region_id = item.source.region_id if (item.source and item.source.region_id) else f"item_{idx+1}"

            vendor_val = invoice_data.vendor_name_raw.value if invoice_data.vendor_name_raw else None
            inv_num_val = invoice_data.invoice_number.value if invoice_data.invoice_number else None

            chunks.append(
                VectorChunk(
                    chunk_id=f"{doc_id}_item_{idx+1}",
                    document_id=doc_id,
                    organization_id=organization_id,
                    chunk_type="LINE_ITEM",
                    text=semantic_text,
                    page_number=page,
                    region_id=region_id,
                    bbox=bbox,
                    metadata={
                        "item_index": idx + 1,
                        "description": desc,
                        "line_total": float(item.total) if item.total is not None else None,
                        "vendor_name": vendor_val,
                        "invoice_number": inv_num_val,
                    },
                )
            )

        return chunks

    def chunk_po_line_items(
        self,
        doc_id: str,
        organization_id: str,
        po_data: PurchaseOrderData,
    ) -> List[VectorChunk]:
        chunks: List[VectorChunk] = []

        for idx, item in enumerate(po_data.line_items):
            desc = item.description or "Line Item"
            qty_str = f"Qty: {item.quantity}" if item.quantity is not None else ""
            price_str = f"Unit Price: {item.unit_price}" if item.unit_price is not None else ""
            tot_str = f"Total: {item.total}" if item.total is not None else ""

            parts = [desc, qty_str, price_str, tot_str]
            semantic_text = " | ".join(p for p in parts if p)

            bbox = item.source.bbox if (item.source and item.source.bbox) else None
            page = item.source.page_number if (item.source and item.source.page_number) else 1
            region_id = item.source.region_id if (item.source and item.source.region_id) else f"po_item_{idx+1}"

            chunks.append(
                VectorChunk(
                    chunk_id=f"{doc_id}_po_item_{idx+1}",
                    document_id=doc_id,
                    organization_id=organization_id,
                    chunk_type="LINE_ITEM",
                    text=semantic_text,
                    page_number=page,
                    region_id=region_id,
                    bbox=bbox,
                    metadata={
                        "item_index": idx + 1,
                        "description": desc,
                        "line_total": float(item.total) if item.total is not None else None,
                        "po_number": po_data.po_number,
                    },
                )
            )

        return chunks
