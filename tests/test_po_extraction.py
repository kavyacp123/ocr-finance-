from decimal import Decimal
from datetime import date
from app.models import DocumentResult, PageResult, Region, BoundingBox
from app.finance.schemas import ValueOrigin, ClassificationResult, DocumentType
from app.finance.extraction.po_extractor import PurchaseOrderExtractor


def test_purchase_order_extraction_basic():
    regions = [
        Region(id='r1', page_number=1, region_type='header', reading_order=1,
               bbox=BoundingBox(x1=50, y1=50, x2=300, y2=80), clean_content='ACME SUPPLIES LTD.'),
        Region(id='r2', page_number=1, region_type='text', reading_order=2,
               bbox=BoundingBox(x1=50, y1=100, x2=300, y2=130), clean_content='Purchase Order #: PO-2025-9941'),
        Region(id='r3', page_number=1, region_type='text', reading_order=3,
               bbox=BoundingBox(x1=50, y1=140, x2=300, y2=170), clean_content='Order Date: 12/03/2026'),
        Region(id='r4', page_number=1, region_type='text', reading_order=4,
               bbox=BoundingBox(x1=50, y1=180, x2=300, y2=210), clean_content='Expected Delivery: 25/03/2026'),
        Region(id='r5', page_number=1, region_type='text', reading_order=5,
               bbox=BoundingBox(x1=50, y1=220, x2=300, y2=250), clean_content='Vendor: Global Cloud Technologies'),
        Region(id='r6', page_number=1, region_type='text', reading_order=6,
               bbox=BoundingBox(x1=50, y1=260, x2=300, y2=290), clean_content='Terms: Net 30'),
        Region(id='r7', page_number=1, region_type='text', reading_order=7,
               bbox=BoundingBox(x1=50, y1=300, x2=300, y2=330), clean_content='Subtotal: ₹50,000.00'),
        Region(id='r8', page_number=1, region_type='text', reading_order=8,
               bbox=BoundingBox(x1=50, y1=340, x2=300, y2=370), clean_content='Total Tax: ₹9,000.00'),
        Region(id='r9', page_number=1, region_type='text', reading_order=9,
               bbox=BoundingBox(x1=50, y1=380, x2=300, y2=410), clean_content='Total Amount: ₹59,000.00'),
    ]

    p = PageResult(page_number=1, width=800, height=1200, regions=regions)
    doc = DocumentResult(document_id='doc_po_1', filename='po_test.pdf', page_count=1, processing_time_ms=10.0, pages=[p])

    extractor = PurchaseOrderExtractor()
    po = extractor.extract_purchase_order(doc)

    assert po.po_number is not None
    assert po.po_number.value == 'PO-2025-9941'
    assert po.po_date is not None
    assert po.po_date.value == date(2026, 3, 12)
    assert po.expected_delivery_date is not None
    assert po.expected_delivery_date.value == date(2026, 3, 25)

    assert po.vendor_name_raw is not None
    assert 'Global Cloud Technologies' in po.vendor_name_raw.value
    assert po.payment_terms is not None
    assert 'Net 30' in po.payment_terms.value

    assert po.subtotal is not None
    assert po.subtotal.value == Decimal('50000.00')
    assert po.tax_amount is not None
    assert po.tax_amount.value == Decimal('9000.00')
    assert po.total_amount is not None
    assert po.total_amount.value == Decimal('59000.00')

    assert po.validation.is_valid is True


def test_purchase_order_table_parsing_and_math_check():
    tbl_text = (
        "| Description | Qty | Unit Price | Amount |\n"
        "|---|---|---|---|\n"
        "| Cloud Computing Instance | 5 | 10000.00 | 50000.00 |\n"
    )
    regions = [
        Region(id='r1', page_number=1, region_type='text', reading_order=1,
               bbox=BoundingBox(x1=50, y1=50, x2=300, y2=80), clean_content='PO #: PO-TABLE-01'),
        Region(id='tbl_1', page_number=1, region_type='table', reading_order=2,
               bbox=BoundingBox(x1=50, y1=150, x2=700, y2=400), clean_content=tbl_text),
        Region(id='r3', page_number=1, region_type='text', reading_order=3,
               bbox=BoundingBox(x1=50, y1=420, x2=300, y2=450), clean_content='Total Amount: ₹50,000.00'),
    ]

    p = PageResult(page_number=1, width=800, height=1200, regions=regions)
    doc = DocumentResult(document_id='doc_po_tbl', filename='po_tbl.pdf', page_count=1, processing_time_ms=10.0, pages=[p])

    extractor = PurchaseOrderExtractor()
    po = extractor.extract_purchase_order(doc)

    assert len(po.line_items) == 1
    assert po.line_items[0].description == 'Cloud Computing Instance'
    assert po.line_items[0].quantity == Decimal('5.00')
    assert po.line_items[0].total == Decimal('50000.00')
