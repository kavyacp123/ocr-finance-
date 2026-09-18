from app.models import DocumentResult, PageResult, Region, BoundingBox
from app.finance.classifier import DocumentClassifier
from app.finance.schemas import DocumentType


def test_classify_tax_invoice():
    p = PageResult(
        page_number=1, width=1000, height=1400,
        regions=[
            Region(id="r1", page_number=1, region_type="title", reading_order=1, bbox=BoundingBox(x1=100, y1=50, x2=500, y2=120), clean_content="TAX INVOICE"),
            Region(id="r2", page_number=1, region_type="text", reading_order=2, bbox=BoundingBox(x1=100, y1=150, x2=400, y2=200), clean_content="Invoice Number: INV-991"),
            Region(id="r3", page_number=1, region_type="text", reading_order=3, bbox=BoundingBox(x1=100, y1=220, x2=400, y2=260), clean_content="GSTIN: 29ABCDE1234F1ZW"),
            Region(id="r4", page_number=1, region_type="table", reading_order=4, bbox=BoundingBox(x1=100, y1=300, x2=900, y2=600), clean_content="Item Qty Price Total"),
        ]
    )
    doc = DocumentResult(document_id="doc_c1", filename="invoice.pdf", page_count=1, processing_time_ms=10.0, pages=[p])
    clf = DocumentClassifier()
    res = clf.classify_document(doc)

    assert res.document_type == DocumentType.INVOICE
    assert res.confidence >= 0.85
    assert any("top_title" in k for k in res.matched_keywords)


def test_classify_purchase_order():
    p = PageResult(
        page_number=1, width=1000, height=1400,
        regions=[
            Region(id="r1", page_number=1, region_type="title", reading_order=1, bbox=BoundingBox(x1=100, y1=50, x2=500, y2=120), clean_content="PURCHASE ORDER"),
            Region(id="r2", page_number=1, region_type="text", reading_order=2, bbox=BoundingBox(x1=100, y1=150, x2=400, y2=200), clean_content="PO Number: PO-8821"),
            Region(id="r3", page_number=1, region_type="text", reading_order=3, bbox=BoundingBox(x1=100, y1=220, x2=400, y2=260), clean_content="Ship To: 100 Main St"),
        ]
    )
    doc = DocumentResult(document_id="doc_c2", filename="po.pdf", page_count=1, processing_time_ms=10.0, pages=[p])
    clf = DocumentClassifier()
    res = clf.classify_document(doc)

    assert res.document_type == DocumentType.PURCHASE_ORDER
    assert res.confidence >= 0.80


def test_classify_negative_signals():
    # Document has "Please reference invoice number on PO" but top title is clearly PURCHASE ORDER
    p = PageResult(
        page_number=1, width=1000, height=1400,
        regions=[
            Region(id="r1", page_number=1, region_type="title", reading_order=1, bbox=BoundingBox(x1=100, y1=50, x2=500, y2=120), clean_content="PURCHASE ORDER"),
            Region(id="r2", page_number=1, region_type="text", reading_order=2, bbox=BoundingBox(x1=100, y1=150, x2=400, y2=200), clean_content="PO #: PO-900"),
            Region(id="r3", page_number=1, region_type="text", reading_order=3, bbox=BoundingBox(x1=100, y1=500, x2=500, y2=550), clean_content="Terms: Please submit your invoice number upon delivery."),
        ]
    )
    doc = DocumentResult(document_id="doc_c3", filename="po_with_invoice_word.pdf", page_count=1, processing_time_ms=10.0, pages=[p])
    clf = DocumentClassifier()
    res = clf.classify_document(doc)

    # Must be classified as PURCHASE_ORDER, not INVOICE!
    assert res.document_type == DocumentType.PURCHASE_ORDER


def test_classify_unknown_document():
    p = PageResult(
        page_number=1, width=1000, height=1400,
        regions=[
            Region(id="r1", page_number=1, region_type="text", reading_order=1, bbox=BoundingBox(x1=100, y1=100, x2=500, y2=200), clean_content="This is a general company newsletter about summer vacations."),
        ]
    )
    doc = DocumentResult(document_id="doc_c4", filename="newsletter.pdf", page_count=1, processing_time_ms=5.0, pages=[p])
    clf = DocumentClassifier()
    res = clf.classify_document(doc)

    assert res.document_type == DocumentType.UNKNOWN
    assert res.confidence <= 0.50
