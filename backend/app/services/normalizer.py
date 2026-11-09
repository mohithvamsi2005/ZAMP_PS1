"""Normalization utilities for matching — names, invoice numbers, PO references."""
import re
from decimal import Decimal, InvalidOperation
from typing import Optional


# ── Business-suffix handling ──────────────────────────────────────────────────

_BUSINESS_SUFFIXES = [
    "pvt ltd", "pvt. ltd", "private limited", "p-limited",
    "ltd", "limited", "llc", "llp", "inc", " incorporated",
    "corporation", "corp", "co.", " co ", " company",
]


def normalize_vendor_name(name: Optional[str]) -> str:
    """Lowercase, strip whitespace, collapse spaces, remove common business suffixes."""
    if not name:
        return ""
    s = name.lower().strip()
    # Collapse whitespace and punctuation runs (including em-dash/en-dash)
    s = re.sub(r"[\s\u2014\u2013\.\-]+", " ", s)
    s = re.sub(r" +", " ", s).strip()
    # Remove known business suffixes (only at end-of-string)
    for suffix in _BUSINESS_SUFFIXES:
        pattern = r"\b" + re.escape(suffix) + r"$"
        s = re.sub(pattern, "", s).strip()
    return s


def normalize_tax_id(tax_id: Optional[str]) -> str:
    """Uppercase and strip — Indian GSTIN is case-insensitive in practice."""
    if not tax_id:
        return ""
    return str(tax_id).strip().upper()


def normalize_invoice_number(number: Optional[str]) -> str:
    """Trim whitespace, collapse separators, lowercase for comparison."""
    if not number:
        return ""
    s = str(number).strip().lower()
    s = re.sub(r"[\s\-/]+", "", s)
    return s


def normalize_po_reference(ref: Optional[str]) -> str:
    """Trim whitespace and collapse separators for PO matching."""
    if not ref:
        return ""
    s = str(ref).strip().upper()
    s = re.sub(r"[\s\-/]+", "", s)
    return s


def safe_decimal(value, default=None):
    """Parse a Decimal from various input types; return None on failure."""
    if value is None:
        return default
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return default
