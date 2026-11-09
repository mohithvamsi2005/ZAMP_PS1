"""Tax and arithmetic validation — subtotal + tax − discount === total."""
from decimal import Decimal, InvalidOperation

from app.schemas.matching import TaxValidationResult


# Configurable tolerance for rounding
ARITHMETIC_TOLERANCE = Decimal("0.01")


def _safe_decimal(value) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None


def validate_tax_arithmetic(
    subtotal,
    tax_amount,
    discount_amount,
    total_amount,
) -> TaxValidationResult:
    """Check that subtotal + tax − discount ≈ total within tolerance.

    Returns PASS when the arithmetic reconciles, FAIL otherwise.
    Missing fields (None) are treated as zero for calculation purposes but
    flagged in the result so downstream logic can decide whether to REVIEW.
    """
    sub = _safe_decimal(subtotal)
    tax = _safe_decimal(tax_amount)
    disc = _safe_decimal(discount_amount)
    total = _safe_decimal(total_amount)

    discount = disc if disc is not None else Decimal("0")
    tax_val = tax if tax is not None else Decimal("0")

    # Only compute if we have at least subtotal and total
    if sub is None or total is None:
        return TaxValidationResult(
            check_name="Tax / arithmetic validation",
            status="UNKNOWN",
            subtotal=str(sub) if sub is not None else "null",
            tax_amount=str(tax) if tax is not None else "null",
            discount_amount=str(discount),
            expected_total=None,
            actual_total=str(total) if total is not None else "null",
            difference=None,
            explanation="Missing required field(s) for arithmetic check — cannot validate",
        )

    expected = sub + tax_val - discount

    if abs(expected - total) <= ARITHMETIC_TOLERANCE:
        return TaxValidationResult(
            check_name="Tax / arithmetic validation",
            status="PASS",
            subtotal=str(sub),
            tax_amount=str(tax_val),
            discount_amount=str(discount),
            expected_total=str(expected),
            actual_total=str(total),
            difference="0.00",
            explanation=f"{sub} + {tax_val} − {discount} = {expected} ≈ {total}",
        )

    return TaxValidationResult(
        check_name="Tax / arithmetic validation",
        status="FAIL",
        subtotal=str(sub),
        tax_amount=str(tax_val),
        discount_amount=str(discount),
        expected_total=str(expected),
        actual_total=str(total),
        difference=str(abs(expected - total)),
        explanation=f"Arithmetic mismatch: {sub} + {tax_val} − {discount} = {expected}, but total is {total}",
    )
