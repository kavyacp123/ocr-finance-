from decimal import Decimal
from datetime import date, timedelta
from app.finance.schemas import InvoiceData, ExtractedField, InvoiceLineItem
from app.finance.validators import (
    validate_invoice,
    validate_gstin,
    validate_math_balance,
    validate_line_items_sum,
    validate_date_chronology,
)


def test_validate_math_balance_exact():
    inv = InvoiceData(
        document_id="doc_v1",
        invoice_number=ExtractedField(name="invoice_number", value="INV-101"),
        invoice_date=ExtractedField(name="invoice_date", value=date(2026, 3, 1)),
        vendor_name_raw=ExtractedField(name="vendor_name_raw", value="Vendor Corp"),
        subtotal=ExtractedField(name="subtotal", value=Decimal("100.00")),
        tax_amount=ExtractedField(name="tax_amount", value=Decimal("18.00")),
        total_amount=ExtractedField(name="total_amount", value=Decimal("118.00")),
    )
    res = validate_invoice(inv)
    assert res.is_valid is True
    assert not any(i.issue_type == "MATH_TOTAL_MISMATCH" for i in res.issues)


def test_validate_math_balance_tolerance():
    # 0.50 delta is within 1.00 tolerance
    inv = InvoiceData(
        document_id="doc_v2",
        invoice_number=ExtractedField(name="invoice_number", value="INV-102"),
        invoice_date=ExtractedField(name="invoice_date", value=date(2026, 3, 1)),
        vendor_name_raw=ExtractedField(name="vendor_name_raw", value="Vendor Corp"),
        subtotal=ExtractedField(name="subtotal", value=Decimal("100.00")),
        tax_amount=ExtractedField(name="tax_amount", value=Decimal("18.00")),
        total_amount=ExtractedField(name="total_amount", value=Decimal("118.50")),
    )
    res = validate_invoice(inv)
    assert not any(i.issue_type == "MATH_TOTAL_MISMATCH" for i in res.issues)


def test_validate_math_balance_mismatch():
    # Significant mismatch > 1.00 tolerance
    inv = InvoiceData(
        document_id="doc_v3",
        invoice_number=ExtractedField(name="invoice_number", value="INV-103"),
        invoice_date=ExtractedField(name="invoice_date", value=date(2026, 3, 1)),
        vendor_name_raw=ExtractedField(name="vendor_name_raw", value="Vendor Corp"),
        subtotal=ExtractedField(name="subtotal", value=Decimal("100.00")),
        tax_amount=ExtractedField(name="tax_amount", value=Decimal("18.00")),
        total_amount=ExtractedField(name="total_amount", value=Decimal("150.00")),
    )
    res = validate_invoice(inv)
    mismatches = [i for i in res.issues if i.issue_type == "MATH_TOTAL_MISMATCH"]
    assert len(mismatches) == 1
    assert mismatches[0].expected == "118.00"
    assert mismatches[0].actual == "150.00"


def test_validate_line_items_sum():
    inv = InvoiceData(
        document_id="doc_v4",
        subtotal=ExtractedField(name="subtotal", value=Decimal("300.00")),
        line_items=[
            InvoiceLineItem(line_number=1, total=Decimal("100.00")),
            InvoiceLineItem(line_number=2, total=Decimal("100.00")),
        ],
    )
    issues = []
    validate_line_items_sum(inv, issues)
    assert len(issues) == 1
    assert issues[0].issue_type == "LINE_ITEMS_SUM_MISMATCH"
    assert issues[0].actual == "200.00"
    assert issues[0].expected == "300.00"


def test_validate_date_chronology():
    issues = []
    inv = InvoiceData(
        document_id="doc_v5",
        invoice_date=ExtractedField(name="invoice_date", value=date(2026, 3, 20)),
        due_date=ExtractedField(name="due_date", value=date(2026, 3, 10)),
    )
    validate_date_chronology(inv, issues)
    assert any(i.issue_type == "DUE_DATE_BEFORE_INVOICE_DATE" for i in issues)

    # Future date warning
    future_issues = []
    inv_future = InvoiceData(
        document_id="doc_v6",
        invoice_date=ExtractedField(name="invoice_date", value=date.today() + timedelta(days=60)),
    )
    validate_date_chronology(inv_future, future_issues)
    assert any(i.issue_type == "FUTURE_INVOICE_DATE" for i in future_issues)


def test_3_level_gstin_validation():
    # Valid GSTIN: 29ABCDE1234F1ZW
    issues_valid = []
    res_valid = validate_gstin("29ABCDE1234F1ZW", issues=issues_valid)
    assert res_valid is True
    assert len(issues_valid) == 0

    # Level 1: Bad Format
    issues_fmt = []
    validate_gstin("INVALID-GSTIN", issues=issues_fmt)
    assert issues_fmt[0].issue_type == "GSTIN_INVALID_FORMAT"

    # Level 2: Bad State Code (95 is not a valid state code)
    issues_state = []
    validate_gstin("95ABCDE1234F1ZW", issues=issues_state)
    assert issues_state[0].issue_type == "GSTIN_INVALID_STATE_CODE"

    # Level 3: Bad Checksum
    issues_chk = []
    validate_gstin("29ABCDE1234F1Z0", issues=issues_chk)
    assert issues_chk[0].issue_type == "GSTIN_INVALID_CHECKSUM"
