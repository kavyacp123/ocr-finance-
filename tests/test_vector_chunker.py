from decimal import Decimal
from app.models import DocumentResult, PageResult, Region, BoundingBox, PipelineDecision
from app.finance.schemas import InvoiceData, InvoiceLineItem, ExtractedField, SourceReference
from app.finance.vector.chunker import DocumentChunker


def test_chunker_ocr_result():
    chunker = DocumentChunker()

    doc = DocumentResult(
        document_id="doc_chunk_1",
        filename="test.pdf",
        page_count=1,
        processing_time_ms=50.0,
        pages=[
            PageResult(
                page_number=1,
                width=1000,
                height=1400,
                decision=PipelineDecision(
                    requested_mode="auto",
                    selected_mode="hybrid",
                    reason="test",
                    region_count=2,
                    layout_coverage_ratio=0.9,
                    largest_region_ratio=0.5,
                ),
                regions=[
                    Region(
                        id="r1",
                        page_number=1,
                        reading_order=1,
                        region_type="header",
                        bbox=BoundingBox(x1=50, y1=50, x2=500, y2=150),
                        clean_content="INVOICE TAX RECEIPT",
                    ),
                    Region(
                        id="r2",
                        page_number=1,
                        reading_order=2,
                        region_type="text",
                        bbox=BoundingBox(x1=50, y1=200, x2=800, y2=400),
                        clean_content="Billed to: Acme Enterprise Solutions",
                    ),
                ],
            )
        ],
    )

    chunks = chunker.chunk_ocr_result(
        doc_id="doc_chunk_1",
        organization_id="test_org",
        ocr_result=doc,
    )

    assert len(chunks) == 2
    assert chunks[0].chunk_id == "doc_chunk_1_r1"
    assert chunks[0].bbox == [50, 50, 500, 150]
    assert chunks[0].page_number == 1
    assert "INVOICE" in chunks[0].text


def test_chunker_line_items():
    chunker = DocumentChunker()

    inv = InvoiceData(
        document_id="doc_gpu_1",
        invoice_number=ExtractedField(name="invoice_number", value="INV-999"),
        vendor_name_raw=ExtractedField(name="vendor_name_raw", value="NVIDIA Cloud"),
        line_items=[
            InvoiceLineItem(
                line_number=1,
                description="8x H100 SXM5 GPU Node 1 Month",
                quantity=Decimal("1"),
                unit_price=Decimal("25000.00"),
                total=Decimal("25000.00"),
                source=SourceReference(
                    document_id="doc_gpu_1",
                    page_number=2,
                    region_id="reg_item_1",
                    bbox=[100, 500, 900, 550],
                    original_text="8x H100 SXM5 GPU Node 1 Month | Qty: 1 | 25000.00",
                ),
            )
        ],
    )

    chunks = chunker.chunk_invoice_line_items(
        doc_id="doc_gpu_1",
        organization_id="test_org",
        invoice_data=inv,
    )

    assert len(chunks) == 1
    item_chunk = chunks[0]
    assert item_chunk.chunk_type == "LINE_ITEM"
    assert item_chunk.page_number == 2
    assert item_chunk.bbox == [100, 500, 900, 550]
    assert "H100" in item_chunk.text
    assert item_chunk.metadata["vendor_name"] == "NVIDIA Cloud"
