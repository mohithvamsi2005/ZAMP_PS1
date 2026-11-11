# Zamp Invoice Intelligence — Live Demo Teleprompter Script (~4 min 25 sec)

**Target Duration:** `04:15 – 04:40` (comfortably under 5 minutes)
**Spoken Budget:** ~575 words total (~135–140 words/min). Keep reading smoothly *while* the ~15s pipeline runs so there is zero dead air.
**Live Stack:** `http://127.0.0.1:8000` (FastAPI + React SPA) · Ollama `qwen2.5:1.5b` (`11434`) · Tesseract OCR · SQLite `demo.db`

---

## Pre-Recording Setup (Do Before Hitting Record)

1. Open `http://127.0.0.1:8000` in your browser (password if prompted: `ZampPhase9Demo!`).
2. Copy this folder path so File Explorer opens straight to your PDFs:
   ```text
   c:\Users\Gurram Mohith Vamsi\Downloads\Zamp\Zamp\zamp-invoice-intelligence\backend\data\synthetic_invoices
   ```
3. **Warm up Ollama once** if your laptop just woke up: upload `syn_01_clean_approve.pdf` once, wait for it to finish, then click **Reset data → Confirm reset** (now `qwen2.5:1.5b` stays warm in memory at ~13–17s per invoice!).
4. Keep this file open beside your browser window and read only the **`>` spoken lines** while clicking the **`[DO]`** cues.

---

## Scene 1 — Problem, Architecture & Live Reset (`0:00 – 0:40`)

- **`[DO]`** Start on **Overview** (`http://127.0.0.1:8000/`). Hover briefly over the sidebar footer (**Backend: Online — DB connected · LLM provider: llamacpp · qwen2.5:1.5b**).

> "Hi everyone — I'll be walking through **Zamp Invoice Intelligence**, an automated accounts-payable verification system that takes incoming invoice PDFs, extracts structured data, reconciles them against procurement purchase orders, and produces an auditable decision: **APPROVE**, **REVIEW**, or **REJECT**."
>
> "The core design rule here is strict separation of concerns: the LLM *never* makes a financial decision. It only parses unstructured text into schema-validated JSON. Every match, calculation, duplicate check, and policy rule runs in deterministic Python."

- **`[DO]`** Click **`Reset data`** → **`Confirm reset`** in the top-right header. Wait 1s for the green banner (*`Baseline restored — 3 sample invoices, 0 runs.`*).

> "Starting fresh with **Reset data** — this clears runtime invoices and uploaded PDFs, blocks with HTTP 409 if any job is mid-flight, and re-seeds 6 vendors, 8 POs, and zero processing runs."

---

## Scene 2 — Happy Path & Live 11-Stage Pipeline (`0:40 – 2:00`)

- **`[DO]`** Click **`Upload invoice`** → select **`syn_01_clean_approve.pdf`** → click **`Upload and process`**.
- **`[WAIT ~15–17s]`** Keep speaking while the timeline polls every 2 seconds!

> "First, let's upload a clean baseline invoice: `syn_01_clean_approve.pdf` — **60,000 INR** from an active vendor, **ABC Industrial Supplies**, against an open purchase order, **PO-2044**."
>
> "At upload, FastAPI checks the `.pdf` extension, 20 MB cap, and `%PDF-` magic header, computes SHA-256, stores the file under a randomized name, and returns **202 Accepted**."
>
> "Notice this timeline isn't a fake progress bar — each stage persists a `run_events` row to SQLite and the UI polls `/api/runs/{id}` every two seconds. PyMuPDF checks page text density; since pages exceed 50 characters, **OCR is skipped**. Next, the worker commits the DB session *before* calling local Ollama so SQLite never locks during inference, cleans currency symbols into strict Python `Decimal`, and executes matching, three financial validators, and Policy v1.0."

- **`[DO]`** Click **`Open full invoice intelligence`**. Scroll briefly through **Extracted information**, click **`Inspect extraction evidence`**, scroll past **Purchase order comparison** and **Validation results**, and stop at **Final decision**.

> "Opening the detail view — we see both extracted line items totaling **60,000 INR**, exact source snippets with per-field confidence under **extraction evidence**, all six deterministic checks passing against **PO-2044**, and Policy v1.0 outputting **APPROVE** (`APPROVE_001`) alongside the stored PDF and chronological audit history."

- *⚠️ [BACKUP LINE — Read ONLY if the 1.5B model output `REVIEW` instead of `APPROVE` on this take:]*
> "*(Optional backup:)* Notice here it routed to **REVIEW** instead of auto-approving — that's our fail-safe design in action: Policy v1.0 requires `>= 0.80` extraction confidence on critical fields, so when a tiny 1.5B model omits numeric confidence, our engine refuses to guess and escalates safely."

---

## Scene 3 — Edge Case #1: Overbilling & Line-Item Mismatch (`2:00 – 3:10`)

- **`[DO]`** Click **`Overview`** → **`Upload invoice`** → select **`syn_03_overbilling.pdf`** → click **`Upload and process`**.
- **`[WAIT ~15s]`** Keep speaking while it runs!

> "Now for our first edge case: **`syn_03_overbilling.pdf`**."
>
> "Here, a legitimate active vendor — **XYZ Metals and Alloys** — submits a valid digital invoice against open **PO-2045**, whose limit is **1,20,000 INR**. Document structure and tax math are clean, *except* the invoice bills **1,30,500 INR**, inflates *Steel channel 75mm* from **60 pieces on the PO** to **150 pieces**, and drops two other PO lines."

- **`[DO]`** Click **`Open full invoice intelligence`** → scroll directly to **`Validation results`** and **`Final decision`**.

> "Look at the breakdown: vendor match, PO match, duplicate detection, and tax math all **PASS**. Rather than blindly trusting header math or hard-rejecting, the validators pinpoint **`AMOUNT_001`** — exceeding PO balance by **10,500 INR** beyond our `100 INR` tolerance — and **`LINEITEM_001`**, flagging `qty invoice=150 vs po=60` plus 2 unmatched PO lines. Policy v1.0 escalates this cleanly to **REVIEW** with exact numerical proof for the analyst."

---

## Scene 4 — Edge Case #2: Blocked Vendor Compliance Precedence (`3:10 – 4:00`)

- **`[DO]`** Click **`Overview`** → **`Upload invoice`** → select **`syn_02_blocked_vendor.pdf`** → click **`Upload and process`**.
- **`[WAIT ~13s]`** Keep speaking while it runs!

> "For a second edge case, let's test **policy precedence** with **`syn_02_blocked_vendor.pdf`**."
>
> "This invoice from **Sharma Electrical Components** against **PO-2047** for **30,000 INR** reconciles 100% on amount, line items, and tax arithmetic — *but* the vendor is flagged **BLOCKED** in procurement master data. Inside Policy v1.0, precedence is strictly **REJECT > REVIEW > APPROVE**, so no passing check later can ever override a compliance block."

- **`[DO]`** Point cursor at the red **`REJECT`** outcome banner and **`VENDOR_BLOCK_001`** on screen.

> "In 13 seconds, even with clean line-item math, **`VENDOR_BLOCK_001`** triggers an immediate **REJECT**. Note also that we exclude blocked vendors from RapidFuzz fuzzy matching — only an unambiguous Tax ID or exact normalized name can trigger an automatic reject; fuzzy matches fall safely to review."

---

## Scene 5 — Review Queue, History & Wrap-Up (`4:00 – 4:30`)

- **`[DO]`** Click **`Review Queue`** in the sidebar (show `syn_03_overbilling.pdf` queued), then click **`History`** in the sidebar.

> "Wrapping up the loop: **Review Queue** surfaces every flagged case like XYZ Metals so nothing ambiguous pays out silently, and **History** logs every run for auditability."
>
> "Under the hood, two extra reliability guards protect production: if Ollama crashes, runs stop cleanly as **FAILED** with `decision = null` and support a one-click **Retry** without losing history; and Stage 11 takes a SQLite write lock to re-verify PO balance right before committing **APPROVE**, preventing double-spending on concurrent uploads."
>
> "AI reads the document, deterministic code enforces policy, and SQLite persists every rule for full auditability. Thanks for watching!"

**[END RECORDING — ~4m 25s]**

---

## Quick Backup Facts (If Asked in Live Q&A / Extra Time)

- **Scanned Image PDF (`syn_04_scanned_ocr.pdf` → `REVIEW`):** Zero embedded PDF text → Stage 2 invokes **Tesseract OCR**, recovers full text, and flags **`AMOUNT_002`** (`provisional PO balance`) because seeded `INV-2026-1044` sits unapproved on `PO-2046`.
- **Renamed Duplicate PDF (`syn_05_duplicate_copy.pdf` → `REJECT`):** Exact SHA-256 byte match against `syn_01` (with `exclude_invoice_id` preventing self-match) → immediate **`DOC_DUP_001`** rejection.
