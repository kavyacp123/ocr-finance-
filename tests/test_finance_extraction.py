from decimal import Decimal
from datetime import date
from app.models import DocumentResult, PageResult, Region, BoundingBox, FullPageOCRResult, PipelineDecision
from app.finance.schemas import ValueOrigin
from app.finance.extraction.same_region_extractor import SameRegionExtractor
from app.finance.extraction.spatial_matcher import SpatialFieldMatcher
from app.finance.extraction.table_parser import TableParser
from app.finance.extraction.extractor import FinanceExtractor


def test_same_region_extractor():
    regions = [
        Region(id="r1", page_number=1, region_type="text", reading_order=1, bbox=BoundingBox(x1=10, y1=10, x2=200, y2=40), clean_content="Invoice No: INV-4491"),
        Region(id="r2", page_number=1, region_type="text", reading_order=2, bbox=BoundingBox(x1=10, y1=50, x2=200, y2=80), clean_content="Date: 25/12/2025"),
        Region(id="r3", page_number=1, region_type="text", reading_order=3, bbox=BoundingBox(x1=10, y1=90, x2=200, y2=120), clean_content="Total Amount: ₹45,000.00"),
    ]
    extractor = SameRegionExtractor()
    res = extractor.extract_from_regions("doc_sr", regions)

    assert "invoice_number" in res
    assert res["invoice_number"][0] == "INV-4491"
    assert res["invoice_number"][1].bbox == [10, 10, 200, 40]

    assert "invoice_date" in res
    assert res["invoice_date"][0] == "25/12/2025"

    assert "total_amount" in res
    assert "45,000.00" in res["total_amount"][0]


def test_spatial_matcher_right_neighbor():
    # Anchor on the left, value on the right in same horizontal band
    regions = [
        Region(id="anchor_1", page_number=1, region_type="text", reading_order=1, bbox=BoundingBox(x1=50, y1=100, x2=150, y2=130), clean_content="Invoice Number:"),
        Region(id="val_1", page_number=1, region_type="text", reading_order=2, bbox=BoundingBox(x1=160, y1=100, x2=300, y2=130), clean_content="INV-SPATIAL-01"),
        Region(id="anchor_2", page_number=1, region_type="text", reading_order=3, bbox=BoundingBox(x1=50, y1=150, x2=150, y2=180), clean_content="Total:"),
        Region(id="val_2", page_number=1, region_type="text", reading_order=4, bbox=BoundingBox(x1=160, y1=150, x2=300, y2=180), clean_content="₹99,999.00"),
    ]
    matcher = SpatialFieldMatcher()
    matched = matcher.match_fields("doc_sp", regions)

    assert "invoice_number" in matched
    assert matched["invoice_number"][0] == "INV-SPATIAL-01"
    assert matched["invoice_number"][1].region_id == "val_1"

    assert "total_amount" in matched
    assert matched["total_amount"][0] == "₹99,999.00"


def test_spatial_matcher_below_neighbor():
    # Anchor on top, value directly underneath
    regions = [
        Region(id="anchor_po", page_number=1, region_type="text", reading_order=1, bbox=BoundingBox(x1=100, y1=100, x2=200, y2=130), clean_content="PO Number"),
        Region(id="val_po", page_number=1, region_type="text", reading_order=2, bbox=BoundingBox(x1=100, y1=140, x2=200, y2=170), clean_content="PO-9921"),
    ]
    matcher = SpatialFieldMatcher()
    matched = matcher.match_fields("doc_sp_below", regions)

    assert "po_number" in matched
    assert matched["po_number"][0] == "PO-9921"
    assert matched["po_number"][1].region_id == "val_po"


def test_table_parser_markdown():
    tbl_text = (
        "| Description | Qty | Rate | Amount |\n"
        "|---|---|---|---|\n"
        "| Server Maintenance | 2 | 5000.00 | 10000.00 |\n"
        "| Database Hosting | 1 | 2500.00 | 2500.00 |"
    )
    reg = Region(id="tbl_1", page_number=1, region_type="table", reading_order=5, bbox=BoundingBox(x1=50, y1=300, x2=800, y2=600), clean_content=tbl_text)
    parser = TableParser()
    items = parser.parse_line_items("doc_tbl", [reg])

    assert len(items) == 2
    assert items[0].description == "Server Maintenance"
    assert items[0].quantity == Decimal("2.00")
    assert items[0].unit_price == Decimal("5000.00")
    assert items[0].total == Decimal("10000.00")

    assert items[1].description == "Database Hosting"
    assert items[1].total == Decimal("2500.00")


def test_table_parser_fragmented_easyocr_row():
    text = (
        "Order No. HSN /SAC Quantity Unit Rate Amount\n"
        "Sr Description Code 3.75 18832.50\n"
        "No 5022.00 No\n"
        "MS BUSH 12MM*13MM*11 ID\n"
        "Total 18,832.50"
    )
    region = Region(
        id="p1_fullpage",
        page_number=1,
        region_type="text",
        reading_order=0,
        bbox=BoundingBox(x1=0, y1=0, x2=1653, y2=2339),
        clean_content=text,
        confidence=0.8,
    )

    items = TableParser().parse_line_items("doc_fragmented", [region])

    assert len(items) == 1
    assert items[0].description == "MS BUSH 12MM*13MM*11 ID"
    assert items[0].quantity == Decimal("5022.00")
    assert items[0].unit_price == Decimal("3.75")
    assert items[0].total == Decimal("18832.50")


def test_extractor_derived_total():
    # Total is missing, but subtotal and tax exist -> extractor derives total
    regions = [
        Region(id="r1", page_number=1, region_type="text", reading_order=1, bbox=BoundingBox(x1=50, y1=50, x2=300, y2=80), clean_content="Invoice No: INV-DERIVE"),
        Region(id="r2", page_number=1, region_type="text", reading_order=2, bbox=BoundingBox(x1=50, y1=90, x2=300, y2=120), clean_content="Subtotal: ₹10,000.00"),
        Region(id="r3", page_number=1, region_type="text", reading_order=3, bbox=BoundingBox(x1=50, y1=130, x2=300, y2=160), clean_content="Tax: ₹1,800.00"),
    ]
    p = PageResult(page_number=1, width=800, height=1200, regions=regions)
    doc = DocumentResult(document_id="doc_der", filename="test.pdf", page_count=1, processing_time_ms=5.0, pages=[p])

    extractor = FinanceExtractor()
    inv = extractor.extract_invoice(doc)

    assert inv.total_amount is not None
    assert inv.total_amount.value == Decimal("11800.00")
    assert inv.total_amount.origin == ValueOrigin.DERIVED
    assert inv.total_amount.derived_from == ["subtotal", "tax_amount"]


def test_extractor_full_page_mode():
    """
    When OCR routes to full_page mode, regions exist but have clean_content=None.
    The actual text is in page.full_page_ocr.text. The extractor must synthesize
    a virtual region from the full-page text and still extract fields.
    """
    full_page_text = (
        "SONAL ENTERPRISES\n"
        "Tax Invoice\n"
        "Invoice No: SE-2025-0481\n"
        "Date: 15/08/2025\n"
        "GSTIN: 24AAACS1234F1Z5\n"
        "Bill To: MANGALAM POLY PACK INDUSTRIES\n"
        "Grand Total: ₹22,222.00\n"
        "Bank Account No: 2631201000857\n"
        "IFSC Code: CNRB0002631\n"
    )

    # Regions exist from layout detection, but have NO text (full_page mode)
    regions = [
        Region(id="r1", page_number=1, region_type="text", reading_order=1,
               bbox=BoundingBox(x1=50, y1=30, x2=400, y2=80), clean_content=None),
        Region(id="r2", page_number=1, region_type="text", reading_order=2,
               bbox=BoundingBox(x1=50, y1=100, x2=400, y2=500), clean_content=None),
    ]

    pipeline_decision = PipelineDecision(
        requested_mode="auto",
        selected_mode="full_page",
        reason="content_coverage=0.714 < 0.80",
        region_count=2,
        layout_coverage_ratio=0.75,
        content_coverage_ratio=0.714,
        largest_region_ratio=0.50,
    )

    full_page_ocr = FullPageOCRResult(
        status="success",
        text=full_page_text,
        processing_time_ms=120.0,
    )

    page = PageResult(
        page_number=1,
        width=800,
        height=1200,
        pipeline_decision=pipeline_decision,
        full_page_ocr=full_page_ocr,
        regions=regions,
    )

    doc = DocumentResult(
        document_id="doc_fullpage",
        filename="full_page_invoice.pdf",
        page_count=1,
        processing_time_ms=150.0,
        pages=[page],
    )

    extractor = FinanceExtractor()
    inv = extractor.extract_invoice(doc)

    # Invoice number extracted from full-page text
    assert inv.invoice_number is not None
    assert inv.invoice_number.value == "SE-2025-0481"

    # Total amount extracted
    assert inv.total_amount is not None
    assert inv.total_amount.value == Decimal("22222.00")

    # GSTIN extracted via same-region or regex
    assert inv.vendor_tax_id is not None
    assert inv.vendor_tax_id.value == "24AAACS1234F1Z5"

    # Bank details extracted
    assert inv.bank_account is not None
    assert inv.ifsc_swift is not None
    assert inv.ifsc_swift.value == "CNRB0002631"

    # Vendor name from entity heuristic (first line of full-page text)
    assert inv.vendor_name_raw is not None
    assert "SONAL" in inv.vendor_name_raw.value.upper()


def test_extractor_easyocr_row_ordered_invoice():
    full_page_text = (
        "HARI OM\n"
        "SONAL ENTERPRISES Mobile : 78784 72486\n"
        "A2/204, PALMERA BUILDING, VADODARA, GUJARAT\n"
        "TAX INVOICE ORIGINAL FOR RECIPIENT\n"
        "Bill To Party Invoice No. 107 Date 28-08-2025\n"
        "MANGALAM POLY PACK INDUSTRIES Challan No. Date\n"
        "GSTIN 24EBDPP2639N1Z9 State Code 24\n"
        "Sr No Description HSN/SAC Code Quantity Unit Rate Amount\n"
        "1 MS BUSH 12MM*13MM*11 ID 5022.00 No 3.75 18832.50\n"
        "Total 18,832.50\n"
        "CGST 9.00% 1,694.93\n"
        "SGST 9.00% 1,694.93\n"
        "Rupees Twenty Two Thousand Two Hundred Twenty Two Only\n"
        "Grand Total 22,222.00\n"
    )
    page = PageResult(
        page_number=1,
        width=1653,
        height=2339,
        pipeline_decision=PipelineDecision(
            requested_mode="auto",
            selected_mode="full_page",
            reason="test",
            region_count=1,
            layout_coverage_ratio=0.6,
            content_coverage_ratio=0.7,
            largest_region_ratio=0.6,
        ),
        full_page_ocr=FullPageOCRResult(status="success", text=full_page_text),
        regions=[
            Region(
                id="r1",
                page_number=1,
                region_type="table",
                reading_order=1,
                bbox=BoundingBox(x1=0, y1=0, x2=1653, y2=2339),
            )
        ],
    )
    doc = DocumentResult(
        document_id="doc_easyocr_invoice",
        filename="sales-page.pdf",
        page_count=1,
        processing_time_ms=1.0,
        pages=[page],
    )

    inv = FinanceExtractor().extract_invoice(doc)

    assert inv.invoice_number.value == "107"
    assert inv.po_number is None
    assert str(inv.invoice_date.value) == "2025-08-28"
    assert inv.vendor_name_raw.value == "SONAL ENTERPRISES"
    assert inv.buyer_name_raw.value == "MANGALAM POLY PACK INDUSTRIES"
    assert inv.currency.value == "INR"
    assert inv.subtotal.value == Decimal("18832.50")
    assert inv.tax_amount.value == Decimal("3389.86")
    assert inv.total_amount.value == Decimal("22222.00")
    assert len(inv.line_items) == 1
    assert inv.line_items[0].quantity == Decimal("5022.00")
    assert inv.line_items[0].unit_price == Decimal("3.75")
    assert inv.line_items[0].total == Decimal("18832.50")
