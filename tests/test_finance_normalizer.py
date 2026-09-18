from decimal import Decimal
from datetime import date
from app.finance.normalizer import (
    normalize_date,
    normalize_amount,
    normalize_currency,
    normalize_vendor_name,
    normalize_tax_id,
)


def test_normalize_date_formats():
    assert normalize_date("12/03/2026") == date(2026, 3, 12)
    assert normalize_date("12-Mar-2026") == date(2026, 3, 12)
    assert normalize_date("March 12, 2026") == date(2026, 3, 12)
    assert normalize_date("2026-03-12") == date(2026, 3, 12)
    assert normalize_date("12.03.2026") == date(2026, 3, 12)
    assert normalize_date("Date: 15/08/2025") == date(2025, 8, 15)
    assert normalize_date("Invalid date text") is None


def test_normalize_amount_strict_decimal():
    # Indian number formatting
    amt1 = normalize_amount("₹1,25,000.50")
    assert amt1 == Decimal("125000.50")
    assert isinstance(amt1, Decimal)

    # Simple amount with noise
    amt2 = normalize_amount("Total Amount: $ 1,500.00 /-")
    assert amt2 == Decimal("1500.00")

    # Word form: Lakhs and Crores
    amt3 = normalize_amount("Rs. 2.5 lakh")
    assert amt3 == Decimal("250000.00")

    amt4 = normalize_amount("1 crore")
    assert amt4 == Decimal("10000000.00")

    # European format (dot for thousands, comma for decimals)
    amt5 = normalize_amount("€ 1.250,75")
    assert amt5 == Decimal("1250.75")

    assert normalize_amount("No numbers here") is None


def test_normalize_currency():
    assert normalize_currency("Total ₹1500") == "INR"
    assert normalize_currency("Price Rs. 500") == "INR"
    assert normalize_currency("Price $100") == "USD"
    assert normalize_currency("Price €200") == "EUR"
    assert normalize_currency("Default text") == "INR"


def test_normalize_vendor_name_dual_identity():
    raw, norm = normalize_vendor_name("Amazon Web Services India Pvt Ltd")
    # Preserves legal name
    assert raw == "Amazon Web Services India Pvt Ltd"
    # Strips corporate suffixes for matching
    assert norm == "amazon web services india"

    raw2, norm2 = normalize_vendor_name("ABC Technologies LLP")
    assert raw2 == "ABC Technologies LLP"
    assert norm2 == "abc technologies"

    raw3, norm3 = normalize_vendor_name("Google Cloud Inc.")
    assert raw3 == "Google Cloud Inc."
    assert norm3 == "google cloud"


def test_normalize_tax_id():
    assert normalize_tax_id("GSTIN: 29ABCDE1234F1ZW") == "29ABCDE1234F1ZW"
    assert normalize_tax_id("gst-no- 27abcde1234f1zw ") == "27ABCDE1234F1ZW"
    assert normalize_tax_id("") is None
