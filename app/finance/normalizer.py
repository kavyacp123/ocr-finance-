import re
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Optional, Tuple
from dateutil import parser as date_parser

from app.utils.logging import logger

# Currency symbols & prefixes mapping to ISO codes
CURRENCY_MAP = {
    "₹": "INR",
    "rs.": "INR",
    "rs": "INR",
    "inr": "INR",
    "$": "USD",
    "usd": "USD",
    "€": "EUR",
    "eur": "EUR",
    "£": "GBP",
    "gbp": "GBP",
}

# Corporate legal suffixes to strip for search/matching normalisation
CORPORATE_SUFFIX_PATTERN = re.compile(
    r"\b(pvt\.?\s*ltd\.?|private\s+limited|limited|ltd\.?|inc\.?|incorporated|"
    r"corp\.?|corporation|llc|l\.l\.c\.?|llp|l\.l\.p\.?|gmbh|co\.?|company)\b",
    re.IGNORECASE,
)


def normalize_date(raw_str: Optional[str]) -> Optional[date]:
    """
    Parses ambiguous date formats into a standard datetime.date.
    Prioritizes ISO (YYYY-MM-DD) and dayfirst=True for Indian and international documents (DD/MM/YYYY).
    """
    if not raw_str:
        return None

    cleaned = raw_str.strip()
    # Strip common leading noise words
    cleaned = re.sub(r"^(date|dated|dt\.?|invoice\s*date)\s*[:\-]?\s*", "", cleaned, flags=re.IGNORECASE).strip()

    # 1. Check explicit ISO format (YYYY-MM-DD or YYYY/MM/DD)
    iso_match = re.match(r"^(\d{4})[/\-](\d{1,2})[/\-](\d{1,2})", cleaned)
    if iso_match:
        try:
            return date(int(iso_match.group(1)), int(iso_match.group(2)), int(iso_match.group(3)))
        except ValueError:
            pass

    # 2. Match standard dates like DD/MM/YYYY, DD-Mon-YYYY
    try:
        dt = date_parser.parse(cleaned, dayfirst=True)
        return dt.date()
    except (ValueError, OverflowError):
        # Fallback to regex for tricky formats like 12.03.2026
        dot_match = re.search(r"(\d{1,2})\.(\d{1,2})\.(\d{2,4})", cleaned)
        if dot_match:
            try:
                day, month, year = int(dot_match.group(1)), int(dot_match.group(2)), int(dot_match.group(3))
                if year < 100:
                    year += 2000
                return date(year, month, day)
            except ValueError:
                pass

    logger.debug(f"NORMALIZER: Could not parse date string: '{raw_str}'")
    return None


def normalize_amount(raw_str: Optional[str]) -> Optional[Decimal]:
    """
    Converts currency and numerical strings to a strict Decimal.
    Supports Indian notation (1,25,000.00), European (1.250,00), and word forms ('1.5 lakh').
    Never uses float!
    """
    if not raw_str:
        return None

    cleaned = raw_str.strip()

    # 1. Check for word forms like '1.5 lakh', '2 crore'
    lakh_match = re.search(r"([\d\.]+)\s*(lakh|lac)s?", cleaned, re.IGNORECASE)
    if lakh_match:
        try:
            val = Decimal(lakh_match.group(1)) * Decimal("100000")
            return val.quantize(Decimal("0.01"))
        except (InvalidOperation, ValueError):
            pass

    crore_match = re.search(r"([\d\.]+)\s*crore?s?", cleaned, re.IGNORECASE)
    if crore_match:
        try:
            val = Decimal(crore_match.group(1)) * Decimal("10000000")
            return val.quantize(Decimal("0.01"))
        except (InvalidOperation, ValueError):
            pass

    # 2. Strip currency symbols and text noise
    # Remove things like 'Total:', 'Amount:', '/-', 'INR', 'Rs.', '$', '₹'
    cleaned = re.sub(r"^(total|subtotal|amount|amt|grand\s*total|net\s*amount)\s*[:\-]?\s*", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"[₹$€£]", "", cleaned)
    cleaned = re.sub(r"\b(inr|usd|eur|gbp|rs\.?|only)\b", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"/\-", "", cleaned)
    cleaned = cleaned.strip()

    # 3. Extract the numeric portion (digits, commas, dots)
    num_match = re.search(r"[-+]?[0-9][0-9.,]*[0-9]|[0-9]", cleaned)
    if not num_match:
        return None

    num_str = num_match.group(0)

    # 4. Disambiguate European vs standard decimal notation:
    # If string has both '.' and ',' and the last separator is ',': e.g. "1.250,50" -> European
    if "." in num_str and "," in num_str:
        last_dot = num_str.rfind(".")
        last_comma = num_str.rfind(",")
        if last_comma > last_dot:
            # European format: replace thousands dots with nothing, comma with dot
            num_str = num_str.replace(".", "").replace(",", ".")
        else:
            # Standard/Indian format: remove commas
            num_str = num_str.replace(",", "")
    elif "," in num_str:
        # Check if comma is decimal (e.g. "1250,50" where comma is followed by 2 digits at end)
        parts = num_str.split(",")
        if len(parts) == 2 and len(parts[1]) == 2:
            num_str = num_str.replace(",", ".")
        else:
            num_str = num_str.replace(",", "")

    try:
        dec = Decimal(num_str)
        return dec.quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError):
        logger.debug(f"NORMALIZER: Could not parse Decimal from: '{raw_str}' (cleaned: '{num_str}')")
        return None


def normalize_currency(raw_str: Optional[str]) -> str:
    """
    Detects ISO 4217 currency code from text, defaulting to 'INR' for Indian context.
    """
    if not raw_str:
        return "INR"

    lowered = raw_str.lower()
    for symbol, code in CURRENCY_MAP.items():
        if symbol in lowered:
            return code

    return "INR"


def normalize_vendor_name(raw_name: Optional[str]) -> Tuple[Optional[str], Optional[str]]:
    """
    Dual vendor identity normalization.
    Preserves raw legal identity while generating normalized matching key.
    Returns: (raw_legal_name, normalized_matching_name)
    """
    if not raw_name:
        return None, None

    # Clean raw string
    raw_cleaned = re.sub(r"\s+", " ", raw_name).strip()

    # Normalized key for entity resolution: lowercase, strip punctuation, strip corporate suffixes
    norm = raw_cleaned.lower()
    norm = CORPORATE_SUFFIX_PATTERN.sub("", norm)
    norm = re.sub(r"[^\w\s]", " ", norm)
    norm = re.sub(r"\s+", " ", norm).strip()

    return raw_cleaned, norm


def normalize_tax_id(raw_str: Optional[str]) -> Optional[str]:
    """
    Normalizes tax identifiers (GSTIN, PAN, VAT, TIN).
    Cleans whitespace, hyphens, and standardizes casing.
    """
    if not raw_str:
        return None

    # Remove labels like "GSTIN:", "GST No:", "GST-No-"
    cleaned = re.sub(r"^(gstin|gst[\s\-_]*no\.?|tax[\s\-_]*id|pan|tin)\s*[:\-_]?\s*", "", raw_str, flags=re.IGNORECASE)
    cleaned = re.sub(r"[\s\-\.]", "", cleaned).strip().upper()

    return cleaned if cleaned else None
