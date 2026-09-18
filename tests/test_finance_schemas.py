from decimal import Decimal
from datetime import date
from app.finance.schemas import (
    InvoiceData,
    ExtractedField,
    ValueOrigin,
    SourceReference,
    ExtractionDetails,
    InvoiceLineItem,
    ValidationIssue,
    ValidationResult,
    DocumentType,
)


def test_extracted_field_provenance():
    src = SourceReference(
        document_id="doc_101",
        page_number=1,
        region_id="reg_12",
        bbox=[100, 200, 400, 240],
        polygon=[[100, 200], [400, 200], [400, 240], [100, 240]],
        original_text="Invoice No: INV-9901",
    )
    field = ExtractedField(
        name="invoice_number",
        value="INV-9901",
        raw_value="Invoice No: INV-9901",
        origin=ValueOrigin.EXTRACTED,
        confidence=0.98,
        source=src,
        extraction=ExtractionDetails(method="same_region_regex", confidence=0.98),
    )

    dumped = field.model_dump()
    assert dumped["name"] == "invoice_number"
    assert dumped["value"] == "INV-9901"
    assert dumped["origin"] == "EXTRACTED"
    assert dumped["source"]["bbox"] == [100, 200, 400, 240]


def test_derived_field_provenance():
    field = ExtractedField(
        name="total_amount",
        value=Decimal("118000.00"),
        raw_value="118000.00",
        origin=ValueOrigin.DERIVED,
        confidence=0.92,
        derived_from=["subtotal", "tax_amount"],
        extraction=ExtractionDetails(method="derived_math_sum", confidence=0.92),
    )

    assert field.origin == ValueOrigin.DERIVED
    assert field.derived_from == ["subtotal", "tax_amount"]
    assert field.value == Decimal("118000.00")


def test_invoice_line_item_decimal():
    item = InvoiceLineItem(
        line_number=1,
        description="Cloud Compute Instance",
        quantity=Decimal("10.5"),
        unit_price=Decimal("100.00"),
        total=Decimal("1050.00"),
        confidence=0.95,
    )
    assert item.quantity == Decimal("10.5")
    assert item.unit_price == Decimal("100.00")
    assert item.total == Decimal("1050.00")
    assert isinstance(item.total, Decimal)


def test_canonical_invoice_data():
    inv = InvoiceData(
        document_id="doc_202",
        organization_id="org_test",
        vendor_name_raw=ExtractedField(name="vendor_name_raw", value="AWS India Pvt Ltd"),
        vendor_name_normalized="aws india",
        total_amount=ExtractedField(name="total_amount", value=Decimal("15000.50")),
    )
    assert inv.organization_id == "org_test"
    assert inv.vendor_name_normalized == "aws india"
    assert inv.total_amount.value == Decimal("15000.50")
    assert inv.payment_status == "unpaid"
