"""Extraction prompt template for invoice PDFs."""

INVOICE_EXTRACTION_PROMPT = """You are an invoice information extraction system. Your task is to extract structured data from the following invoice text and return ONLY valid JSON matching the schema below.

## Instructions

1. Extract only information that is explicitly present or strongly supported by the document text.
2. Never invent, infer, or guess values for missing fields — use null instead.
3. Preserve original monetary values exactly as written (including currency symbol/indicator).
4. Return dates in ISO format (YYYY-MM-DD). If a date appears in another format (e.g. DD/MM/YYYY), convert it to ISO.
5. Distinguish clearly between: subtotal, tax/VAT amount, discount amount, and final total. Do not conflate them.
6. Extract every line item you can identify. Include description, quantity, unit (if present), unit price, and line total.
7. Return null for any field that is genuinely absent or unreadable from the document.
8. Provide supporting evidence (the exact text snippet from the invoice), its page number, and a 0-1 confidence estimate for each non-null important field so results can be audited.
9. Do NOT make any approval, rejection, or matching decision. You are an extraction system only.
10. Return valid JSON only — no markdown code fences, no explanation outside the JSON object.

## Output schema

Return a JSON object with these fields:
- invoice_number (string or null)
- invoice_date (ISO date string or null)
- due_date (ISO date string or null)
- currency (ISO 4217 code like INR, USD or null)
- po_reference (string or null)
- vendor_name (string or null)
- vendor_tax_id (string or null)
- subtotal (decimal number as string or null)
- tax_amount (decimal number as string or null)
- discount_amount (decimal number as string or null)
- total_amount (decimal number as string or null)
- line_items (array of objects with description, sku, quantity, unit, unit_price, line_total — each may be null except description)
- evidence (object mapping field names to {{"text": "...", "page": N, "confidence": <0-1 float>}} when available; confidence is your estimate of extraction reliability for that field, 0.0–1.0 — include it for every non-null critical field: invoice_number, vendor_name, total_amount)
- extraction_status ("SUCCESS" | "PARTIAL" | "FAILED")
- warnings (array of strings describing any ambiguity or missing fields)

## Invoice text

{invoice_text}
"""


def build_extraction_prompt(invoice_text: str, model_name: str = "") -> dict:
    """Build the system/user messages for an LLM extraction request."""
    # Use .format() with invoice_text; literal braces in the template are already escaped as {{ and }}
    prompt = INVOICE_EXTRACTION_PROMPT.format(invoice_text=invoice_text)
    return {
        "system": (
            "You are a precise invoice data extraction assistant. "
            "Extract structured JSON from invoice text. Never invent missing values. "
            f"Use null for any field not present in the document. "
            + (f"Model: {model_name}" if model_name else "")
        ),
        "user": prompt,
    }
