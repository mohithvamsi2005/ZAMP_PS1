"""Duplicate invoice detection — document hash, exact invoice number, and potential duplicates.

All queries accept `exclude_invoice_id` so that the invoice currently being
processed can never be identified as its own duplicate. The service is
read-only: it never modifies or deletes records.
"""
from hashlib import sha256
from pathlib import Path
from typing import Optional

from rapidfuzz import fuzz

from app.db.models import Invoice
from app.db.session import SessionLocal
from app.schemas.matching import DuplicateResult
from app.services.normalizer import normalize_invoice_number


# Threshold for considering invoice numbers "similar"
INVOICE_NUMBER_SIMILARITY_THRESHOLD: int = 85


def _exact_document_duplicate(
    file_path: Optional[Path],
    db_session,
    exclude_invoice_id: Optional[int] = None,
) -> Optional[Invoice]:
    """Return an existing invoice with the same SHA-256 document hash, or None."""
    if not file_path or not file_path.exists():
        return None
    h = sha256(file_path.read_bytes()).hexdigest()
    query = db_session.query(Invoice).filter(Invoice.file_sha256 == h)
    if exclude_invoice_id is not None:
        query = query.filter(Invoice.id != exclude_invoice_id)
    return query.first()


def _exact_invoice_duplicate(
    vendor_id: Optional[int],
    invoice_number: Optional[str],
    db_session,
    exclude_invoice_id: Optional[int] = None,
) -> Optional[Invoice]:
    """Return an existing invoice with the same (vendor_id, normalized_invoice_number), or None."""
    if not vendor_id or not invoice_number:
        return None
    norm = normalize_invoice_number(invoice_number)
    query = db_session.query(Invoice).filter(Invoice.vendor_id == vendor_id)
    if exclude_invoice_id is not None:
        query = query.filter(Invoice.id != exclude_invoice_id)
    invoices = query.all()
    for inv in invoices:
        if normalize_invoice_number(inv.invoice_number) == norm:
            return inv
    return None


def _potential_duplicate(
    vendor_id: Optional[int],
    invoice_number: Optional[str],
    total_amount,
    currency: Optional[str],
    db_session,
    exclude_invoice_id: Optional[int] = None,
) -> Optional[dict]:
    """Look for suspiciously similar existing invoices when no exact match exists."""
    if not vendor_id or not invoice_number:
        return None

    norm = normalize_invoice_number(invoice_number)
    query = db_session.query(Invoice).filter(Invoice.vendor_id == vendor_id)
    if exclude_invoice_id is not None:
        query = query.filter(Invoice.id != exclude_invoice_id)
    candidates = query.all()
    for inv in candidates:
        other_norm = normalize_invoice_number(inv.invoice_number)
        if not other_norm or norm == other_norm:
            continue  # exact dup handled above
        num_score = fuzz.ratio(norm, other_norm)
        amount_match = (total_amount is not None and inv.total_amount is not None
                        and total_amount == inv.total_amount)
        currency_match = (currency and inv.currency and currency == inv.currency)

        if num_score >= INVOICE_NUMBER_SIMILARITY_THRESHOLD and (amount_match or currency_match):
            return {
                "existing_invoice_id": inv.id,
                "invoice_number": inv.invoice_number,
                "total_amount": str(inv.total_amount),
                "currency": inv.currency,
                "number_similarity": num_score,
                "same_total": amount_match,
                "same_currency": currency_match,
            }
    return None


def detect_duplicates(
    file_path: Optional[Path] = None,
    vendor_id: Optional[int] = None,
    invoice_number: Optional[str] = None,
    total_amount=None,
    currency: Optional[str] = None,
    exclude_invoice_id: Optional[int] = None,
) -> DuplicateResult:
    """Run duplicate detection across all three signal types.

    Returns EXACT_DOCUMENT_DUPLICATE, EXACT_INVOICE_DUPLICATE, POTENTIAL_DUPLICATE,
    or NO_DUPLICATE_FOUND. Never modifies existing records.

    `exclude_invoice_id` MUST be the invoice row created for the current upload;
    the current invoice is excluded from every query so it can never match
    against itself during processing.
    """
    db = SessionLocal()
    try:
        # A — exact document hash
        dup_doc = _exact_document_duplicate(file_path, db, exclude_invoice_id)
        if dup_doc:
            document_hash = sha256(file_path.read_bytes()).hexdigest() if file_path else None
            return DuplicateResult(
                check_name="Duplicate detection",
                status="EXACT_DOCUMENT_DUPLICATE",
                existing_invoice_id=dup_doc.id,
                explanation=(
                    f"Document hash matches previously stored invoice "
                    f"{dup_doc.invoice_number or 'unnumbered'} (id={dup_doc.id})"
                ),
                evidence={
                    "document_hash": document_hash,
                    "matched_invoice_id": dup_doc.id,
                    "existing_invoice_id": dup_doc.id,  # same key the decision engine reads
                    "matched_invoice_number": dup_doc.invoice_number,
                },
            )

        # B — exact invoice number + vendor
        dup_inv = _exact_invoice_duplicate(vendor_id, invoice_number, db, exclude_invoice_id)
        if dup_inv:
            same_total = (total_amount is not None and dup_inv.total_amount is not None
                          and total_amount == dup_inv.total_amount)
            same_currency = (currency and dup_inv.currency and currency == dup_inv.currency)
            return DuplicateResult(
                check_name="Duplicate detection",
                status="EXACT_INVOICE_DUPLICATE",
                existing_invoice_id=dup_inv.id,
                explanation=(
                    f"Vendor {vendor_id} already has invoice number {invoice_number} "
                    f"(existing invoice id={dup_inv.id})"
                ),
                evidence={
                    "existing_invoice_id": dup_inv.id,
                    "existing_invoice_number": dup_inv.invoice_number,
                    "same_total": same_total,
                    "same_currency": bool(same_currency),
                },
            )

        # C — potential duplicate
        potential = _potential_duplicate(
            vendor_id, invoice_number, total_amount, currency, db, exclude_invoice_id,
        )
        if potential:
            return DuplicateResult(
                check_name="Duplicate detection",
                status="POTENTIAL_DUPLICATE",
                existing_invoice_id=potential["existing_invoice_id"],
                explanation=(
                    f"Suspicious similarity with existing invoice {potential['invoice_number']} "
                    f"(number_similarity={potential['number_similarity']}, "
                    f"same_total={potential['same_total']})"
                ),
                evidence=potential,
            )

        return DuplicateResult(
            check_name="Duplicate detection",
            status="NO_DUPLICATE_FOUND",
            evidence={"excluded_invoice_id": exclude_invoice_id},
        )
    finally:
        db.close()
