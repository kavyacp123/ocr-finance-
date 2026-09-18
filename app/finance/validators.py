import re
from datetime import date, timedelta
from decimal import Decimal
from typing import List, Optional, Set

from app.config import settings
from app.finance.schemas import InvoiceData, ValidationIssue, ValidationResult, SourceReference
from app.utils.logging import logger

CHARS_GSTIN = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"
VALID_STATE_CODES: Set[str] = {
    f"{i:02d}" for i in range(1, 39)
} | {"97", "99"}

GSTIN_REGEX = re.compile(r"^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z]{1}[1-9A-Z]{1}Z[0-9A-Z]{1}$")


def validate_gstin(
    gstin_str: Optional[str],
    field_name: str = "vendor_tax_id",
    source: Optional[SourceReference] = None,
    issues: Optional[List[ValidationIssue]] = None,
) -> bool:
    """
    3-Level Indian GSTIN validation:
    1. Regex format check
    2. State code verification (01-38, 97, 99)
    3. Modulo-36 checksum verification
    """
    if issues is None:
        issues = []

    if not gstin_str:
        return True

    gstin = gstin_str.strip().upper()
    evidence = [source] if source else []

    # Level 1: Syntax format check
    if not GSTIN_REGEX.match(gstin):
        issues.append(
            ValidationIssue(
                issue_type="GSTIN_INVALID_FORMAT",
                severity="medium",
                message=f"GSTIN '{gstin}' does not match standard 15-character format.",
                expected="15-character alphanumeric format (e.g. 29ABCDE1234F1ZW)",
                actual=gstin,
                field_name=field_name,
                evidence=evidence,
            )
        )
        return False

    # Level 2: State code check
    state_code = gstin[:2]
    if state_code not in VALID_STATE_CODES:
        issues.append(
            ValidationIssue(
                issue_type="GSTIN_INVALID_STATE_CODE",
                severity="medium",
                message=f"GSTIN '{gstin}' contains invalid state code '{state_code}'.",
                expected="Valid Indian State/UT code (01-38, 97, 99)",
                actual=state_code,
                field_name=field_name,
                evidence=evidence,
            )
        )
        return False

    # Level 3: Modulo-36 Checksum check
    try:
        calc_sum = 0
        for i in range(14):
            val = CHARS_GSTIN.index(gstin[i])
            factor = 1 if (i % 2 == 0) else 2
            product = val * factor
            calc_sum += (product // 36) + (product % 36)
        check_val = (36 - (calc_sum % 36)) % 36
        expected_char = CHARS_GSTIN[check_val]

        if expected_char != gstin[14]:
            issues.append(
                ValidationIssue(
                    issue_type="GSTIN_INVALID_CHECKSUM",
                    severity="low",
                    message=f"GSTIN '{gstin}' has invalid checksum character '{gstin[14]}' (expected '{expected_char}').",
                    expected=expected_char,
                    actual=gstin[14],
                    field_name=field_name,
                    evidence=evidence,
                )
            )
            return False
    except Exception as e:
        logger.debug(f"GSTIN checksum check skipped: {e}")

    return True


def validate_math_balance(invoice: InvoiceData, issues: List[ValidationIssue]) -> None:
    """
    Verifies that: subtotal + tax_amount - discount_amount == total_amount
    Uses strict Decimal calculations and configurable tolerance.
    """
    subtotal = invoice.subtotal.value if invoice.subtotal and invoice.subtotal.value is not None else None
    total = invoice.total_amount.value if invoice.total_amount and invoice.total_amount.value is not None else None
    tax = invoice.tax_amount.value if invoice.tax_amount and invoice.tax_amount.value is not None else Decimal("0.00")
    discount = invoice.discount_amount.value if invoice.discount_amount and invoice.discount_amount.value is not None else Decimal("0.00")
    shipping = invoice.shipping_amount.value if invoice.shipping_amount and invoice.shipping_amount.value is not None else Decimal("0.00")

    if subtotal is not None and total is not None:
        expected_total = (subtotal + tax - discount + shipping).quantize(Decimal("0.01"))
        delta = abs(expected_total - total)
        tolerance = settings.finance_validation_tolerance_decimal

        if delta > tolerance:
            evidence: List[SourceReference] = []
            for f in [invoice.subtotal, invoice.tax_amount, invoice.discount_amount, invoice.total_amount]:
                if f and f.source:
                    evidence.append(f.source)

            issues.append(
                ValidationIssue(
                    issue_type="MATH_TOTAL_MISMATCH",
                    severity="medium",
                    message=f"Calculated total ({expected_total}) differs from extracted total ({total}) by {delta}.",
                    expected=str(expected_total),
                    actual=str(total),
                    field_name="total_amount",
                    evidence=evidence,
                )
            )


def validate_line_items_sum(invoice: InvoiceData, issues: List[ValidationIssue]) -> None:
    """
    Verifies that the sum of line items equals the subtotal (or total if subtotal is missing).
    """
    if not invoice.line_items:
        return

    item_totals = [item.total for item in invoice.line_items if item.total is not None]
    if not item_totals:
        return

    calculated_items_sum = sum(item_totals).quantize(Decimal("0.01"))
    subtotal = invoice.subtotal.value if invoice.subtotal and invoice.subtotal.value is not None else None
    total = invoice.total_amount.value if invoice.total_amount and invoice.total_amount.value is not None else None

    target = subtotal if subtotal is not None else total
    target_name = "subtotal" if subtotal is not None else "total_amount"

    if target is not None:
        delta = abs(calculated_items_sum - target)
        tolerance = settings.finance_validation_tolerance_decimal
        if delta > tolerance:
            evidence = [item.source for item in invoice.line_items if item.source]
            issues.append(
                ValidationIssue(
                    issue_type="LINE_ITEMS_SUM_MISMATCH",
                    severity="medium",
                    message=f"Sum of {len(item_totals)} line items ({calculated_items_sum}) does not match {target_name} ({target}).",
                    expected=str(target),
                    actual=str(calculated_items_sum),
                    field_name=target_name,
                    evidence=evidence[:5],  # capped for readability
                )
            )


def validate_date_chronology(invoice: InvoiceData, issues: List[ValidationIssue]) -> None:
    """
    Verifies date sanity:
    - invoice_date <= due_date
    - Warns if invoice_date is in the future (non-blocking warning, low/medium severity)
    """
    inv_date = invoice.invoice_date.value if invoice.invoice_date and invoice.invoice_date.value else None
    due_date = invoice.due_date.value if invoice.due_date and invoice.due_date.value else None

    evidence: List[SourceReference] = []
    if invoice.invoice_date and invoice.invoice_date.source:
        evidence.append(invoice.invoice_date.source)
    if invoice.due_date and invoice.due_date.source:
        evidence.append(invoice.due_date.source)

    if inv_date and due_date:
        if due_date < inv_date:
            issues.append(
                ValidationIssue(
                    issue_type="DUE_DATE_BEFORE_INVOICE_DATE",
                    severity="low",
                    message=f"Due date ({due_date}) occurs before invoice date ({inv_date}).",
                    expected=f">= {inv_date}",
                    actual=str(due_date),
                    field_name="due_date",
                    evidence=evidence,
                )
            )

    if inv_date:
        today = date.today()
        # Non-blocking warning for future invoices (workflows, templates, pro-forma)
        if inv_date > (today + timedelta(days=30)):
            issues.append(
                ValidationIssue(
                    issue_type="FUTURE_INVOICE_DATE",
                    severity="low",
                    message=f"Invoice date ({inv_date}) is significantly in the future compared to today ({today}).",
                    expected=f"<= {today}",
                    actual=str(inv_date),
                    field_name="invoice_date",
                    evidence=evidence,
                )
            )


def validate_required_fields(invoice: InvoiceData, issues: List[ValidationIssue]) -> None:
    """
    Checks for essential invoice fields. Missing core fields generate validation issues
    without aborting the extraction result.
    """
    required_checks = [
        ("invoice_number", invoice.invoice_number, "high"),
        ("invoice_date", invoice.invoice_date, "medium"),
        ("total_amount", invoice.total_amount, "high"),
        ("vendor_name_raw", invoice.vendor_name_raw, "medium"),
    ]

    for name, field, severity in required_checks:
        if field is None or field.value is None:
            issues.append(
                ValidationIssue(
                    issue_type="MISSING_REQUIRED_FIELD",
                    severity=severity,
                    message=f"Essential finance field '{name}' could not be extracted.",
                    field_name=name,
                )
            )


def validate_invoice(invoice: InvoiceData) -> ValidationResult:
    """
    Master validation pipeline. Runs all business and mathematical checks.
    Produces non-blocking ValidationResult preserving all issues.
    """
    issues: List[ValidationIssue] = []

    # 1. Math balance validation
    validate_math_balance(invoice, issues)

    # 2. Line item sum validation
    validate_line_items_sum(invoice, issues)

    # 3. Date chronology validation
    validate_date_chronology(invoice, issues)

    # 4. GSTIN validations
    if invoice.vendor_tax_id and invoice.vendor_tax_id.value:
        validate_gstin(
            invoice.vendor_tax_id.value,
            field_name="vendor_tax_id",
            source=invoice.vendor_tax_id.source,
            issues=issues,
        )
    if invoice.buyer_tax_id and invoice.buyer_tax_id.value:
        validate_gstin(
            invoice.buyer_tax_id.value,
            field_name="buyer_tax_id",
            source=invoice.buyer_tax_id.source,
            issues=issues,
        )

    # 5. Required fields validation
    validate_required_fields(invoice, issues)

    # An invoice is considered logically valid if it has no critical or high severity issues
    has_blocking_issue = any(i.severity in ("critical", "high") for i in issues)
    is_valid = not has_blocking_issue

    result = ValidationResult(is_valid=is_valid, issues=issues)
    invoice.validation = result
    return result
