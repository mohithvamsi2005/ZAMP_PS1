# Demo Guide — the five-minute walkthrough

Audience: the reviewer of the Zamp AI Analyst case study submission.
Duration: **five minutes, no slides** — recorded or live.

## Setup checklist

```bash
# 1. Reset the demo database (idempotent; keeps ./data/app.db — dev evidence — untouched)
cd backend && ./scripts/reset_demo_db.sh --reset

# 2. Build the frontend
cd ../frontend && npm run build

# 3. Start the server
cd ../backend && .venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000

# 4. Open http://127.0.0.1:8000 and sign in with the demo password (see backend/.env → AUTH_PASSWORD)
```

Verify history is empty before you start: **Overview → Total invoices submitted = 3** (the three seeded demo invoices).

---

## Script (verbatim narration)

**0:00–0:30 — The problem.** "Accounts-payable teams process thousands of invoices against purchase orders. Manual approval is slow, error-prone and impossible to audit. Zamp Invoice Intelligence ingests the invoice, matches it to a PO, runs deterministic financial checks, and decides — with a complete audit trail."

**0:30–1:00 — Dashboard.** Show the Overview page: 3 total invoices, 1 approved, decision donut empty, history shows the three seeded demo invoices with zero runs. "Everything is live data — no mock counts."

**1:00–2:00 — Upload + live processing.** "Let's approve a clean invoice." Upload `data/demo_invoices/demo_approve_final.pdf` (full coverage of PO-2044 lines: steel sheets, safety goggles). You watch the timeline light up stage by stage: RECEIVED → DOCUMENT_PROCESSING (288 chars) → LLM_EXTRACTION → VENDOR_MATCHING → PO_MATCHING → DUPLICATE_CHECK → AMOUNT_VALIDATION → LINE_ITEM_VALIDATION → TAX_VALIDATION → DECISION → PERSISTENCE. "This is not a canned progress bar — those are persisted events you can hit GET /api/runs/{id}/events and see immediately."

**2:00–3:00 — The decision.** Click the completed run → detail page. Show:
- the exact decision (APPROVE / REVIEW / REJECT — whichever the run honestly produces),
- the validation cards with real explanations (including `AMOUNT_001` once you upload the overbilling fixture),
- PO comparison with previously-approved balance,
- the evidence snippet and page reference,
- the policy version. "The same engine that decided this would run it identically tomorrow — deterministic by construction."

**3:00–4:00 — The edges.** In the Review Queue, open the overbilling invoice (fixture `demo_overbilling.pdf`, vendor XYZ/PO-2045, previously approved ₹116,820.00, remaining ₹3,180.00, invoice ₹116,820.00). Decision: **REVIEW** via `AMOUNT_001` — explain that we never auto-approve financial discrepancies. Open the blocked-vendor fixture `demo_blocked.pdf` — decision driven by `VENDOR_BLOCK_001`. "Two completely different detectors catch two completely different failures, and the reasons are spelled out for the approver."

**4:00–4:40 — Audit history & retry.** Through Processing History, open any blocked/failed run and show every stage event, in order, with messages like `Invoice uploaded and queued … sha256 …`. Show the retry button on a FAILED run — click it, watch the run get re-queued, previous events intact. "Nothing is hidden, nothing is silently lost."

**4:40–5:00 — The value in one sentence.** "Deterministic validation means you can trust the answer; an audit trail means you can defend it; and the refusal to auto-approve anything uncertain means the one time money can go out the door wrong, it won't."

## Expected outcomes

| Demo invoice | Expected | Why |
|---|---|---|
| `demo_approve_final.pdf` (PO-2044, full coverage) | **APPROVE** | vendor matched EXACT_NAME, PO matched EXACT_PO_NUMBER, no duplicates, amount within balance, line items match, tax arithmetic PASS, extraction SUCCESS |
| `demo_overbilling.pdf` (INV-99-XX-7721, PO-2045, previously approved ₹116,820) | **REVIEW** | `AMOUNT_001` — exceeds remaining ₹3,180 by ₹113,640 |
| `demo_blocked.pdf` (V-004 Sharma, BLOCKED) | **REJECT** | `VENDOR_BLOCK_001` — blocked vendor matched exactly |
| `demo_minimal_approve.pdf` re-upload | **REJECT** | `DOC_DUP_001` — same file bytes re-submitted |
| `scanned_ocr.pdf` | **REVIEW** | OCR runs; tiny local model returns garbage → `PARTIAL` extraction → `HUMAN_REVIEW`, never auto-approved |
| `demo_seller2_approve.pdf` | **APPROVE** (if processed in a fresh demo DB) | clean match to PO-2044 lines (same as `demo_approve_final.pdf`) |

Note (honest modelling): the demo currently runs the llama.cpp local provider. A 1.5B model reliably produces honest REVIEW outcomes but not the rich per-field confidences APPROVE requires. For the APPROVE outcome live, either run when OpenRouter quota is available, or accept REVIEW as the truthful outcome and walk through the extraction → matching → validation → decision → audit chain on any completed run.

## Reset between recordings

```bash
cd backend && ./scripts/reset_demo_db.sh --reset
```

This recreates the three seeded invoices and clears all runs — back to a clean state with one command. `data/app.db` (the development evidence DB) is never touched.

## If the live LLM fails mid-demo

Open `Processing history` (it always shows what happened). A `FAILED` run retries with a single click — "run reset to PENDING after failure — retry requested" appears as an event, followed by the new attempt. The audit trail is preserved. Nothing is hidden from you in the demo.
