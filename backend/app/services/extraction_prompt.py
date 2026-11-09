"""Extraction prompt templates for invoice PDFs.

Two templates ship:
* INVOICE_EXTRACTION_PROMPT — full, evidence-annotated schema for capable models
  (production OpenRouter / llama.cpp 30B+).
* COMPACT_INVOICE_EXTRACTION_PROMPT — minimal, flat schema WITHOUT the
  per-field evidence block. Required for small quantised models (qwen2.5:1.5b
  class) that systematically drop invoice_number or hallucinate a swapped field
  when the required JSON shape grows beyond a handful of keys.
Prompt selection is driven by provider: llama.cpp → compact, openrouter → full.
"""

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


COMPACT_INVOICE_EXTRACTION_PROMPT = """Extract invoice data from the text below. Return ONLY valid JSON, no markdown fences.

Schema:
{{"invoice_number": string|null, "invoice_date": string|null, "due_date": string|null,
  "currency": string|null, "po_reference": string|null, "vendor_name": string|null,
  "vendor_tax_id": string|null, "subtotal": string|null, "tax_amount": string|null,
  "discount_amount": string|null, "total_amount": string|null,
  "line_items": [{{"description": string, "sku": string|null, "quantity": string|null,
    "unit": string|null, "unit_price": string|null, "line_total": string|null}}],
  "evidence": {{
    "invoice_number": {{"text": string, "page": integer, "confidence": number}},
    "vendor_name":     {{"text": string, "page": integer, "confidence": number}},
    "total_amount":    {{"text": string, "page": integer, "confidence": number}}
  }},
  "extraction_status": "SUCCESS"|"PARTIAL"|"FAILED", "warnings": [string]}}

Rules: use null for genuinely missing fields. Money as plain strings ("50000.00").
Dates in ISO format. Do not invent values.

The evidence object is REQUIRED and must include exactly the three keys shown
(invoice_number, vendor_name, total_amount) — each quoting the invoice line as
"text" (page 1) and a confidence 0.0–1.0. Do not skip it.

Invoice:
{invoice_text}
"""


def build_extraction_prompt(invoice_text: str, model_name: str = "", compact: bool = False) -> dict:
    """Build the system/user messages for an LLM extraction request.

    `compact=True` selects the flat schema for small quantised llama.cpp models;
    `compact=False` (default) keeps the full evidence-annotated schema.
    """
    template = COMPACT_INVOICE_EXTRACTION_PROMPT if compact else INVOICE_EXTRACTION_PROMPT
    prompt = template.format(invoice_text=invoice_text)
    return {
        "system": (
            "You are a precise invoice data extraction assistant. "
            "Extract structured JSON from invoice text. Never invent missing values. "
            f"Use null for any field not present in the document. "
            + (f"Model: {model_name}" if model_name else "")
        ),
        "user": prompt,
    }
