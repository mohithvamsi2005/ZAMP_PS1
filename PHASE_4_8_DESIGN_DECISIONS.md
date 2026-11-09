# Phases 4–8 — Design Decision Record

Consolidated rationale for the non-obvious decisions later reviewers cannot reconstruct from code alone. This is not marketing; it is *why*, plus the rejected alternatives.

## Phase 4 — Matching, validation, duplicate detection

**Vendor fuzzy threshold = 90 (token_sort_ratio), not token_set.** Token_sort tolerates word re-ordering (address segments move), rejected the min-80 experiments that over-fired on near-identical short names. Below 90 → no candidate, never a silent pick. `score_cutoff=90` AND `len(high_candidates)>1` → `AMBIGUOUS` → `REVIEW`. Never "best guess wins".

**PO match: exact reference → candidates only when vendor is known.** A PO candidate is only surfaced when vendor match exists; no vendor → `MISSING_PO`, never a name-guess. Single-candidate from vendor candidacy → `MATCHED` at 0.5 confidence → Phase-8 `PO_008` forces `REVIEW` unless the PO was evidenced on the invoice (exact/normalized reference).

**Duplicate detection is three-signal.** (1) SHA-256 of the document bytes — same file renamed is still caught. (2) vendor + normalized invoice number — `same_total=false`/`same_currency=false` → `EXACT_INVOICE_DUPLICATE` with conflicting financials → routes to **REVIEW** (`INV_DUP_002`), never silently as REJECT. (3) similarity score with total/currency agreement → `POTENTIAL_DUPLICATE` → **REVIEW**. Confirmed duplicates are REJECT-class rules. The **current invoice is excluded from all three signals** — a run can never self-reject on its own persisted hash/number.

**Amounts validated against APPROVE-committed balances only.** REVIEW/REJECT/FAILED invoices never consume PO balance. When no APPROVE history exists but other invoice rows do, the balance basis falls back to those rows' sum and the result is flagged `provisional=true`, `status=WARNING` — and the policy maps `WARNING` → **REVIEW** (`AMOUNT_002`). This is deliberate: a fresh PO with an invoice in flight must never silently approve over an unknown commitment.

**Line-vs-PO comparison tolerates 0.01 % quantity and price (≈1 basis point), not the misleading comment's "1%".** Effective tolerance pinned by `test_financial_accuracy.py`. Relaxing a financial gate silently was impossible; documenting beats drifting.

**Tax reconciliation is Decimal arithmetic, never float.** tolerance = 0.01 (one paise); FAIL beyond.

## Phase 5 — Deterministic decision engine

**Rules as data, not a config file.** Frozen `RuleEvaluation` schema with stable `rule_id`s; policy is a frozen dataclass `DecisionPolicy` (not editable YAML at runtime). Why: the decision must be replayable months later — a YAML file is a mutable liability, a git-tagged schema is not. Every policy field defaults to the conservative setting.

**Priority ordering is REJECT > REVIEW > APPROVE.** Hard failures evaluated first; a REVIEW reason can never override a hard failure. Minimum critical-field confidence (0.80) is enforced over model-reported evidence, never over the model's self-evaluation.

**UNKNOWN is always REVIEW.** Any validation returning UNKNOWN (missing fields, could-not-run) is surfaced via `unknown_checks` and blocks auto-APPROVE — no silent pass-through.

**Blocked vendor = hard REJECT rule** (`VENDOR_BLOCK_001`) — only on an unambiguous match; ambiguous vendor + blocked-name → REVIEW, never REJECT (protects against fuzzy collisions hitting the wrong vendor).

**Fuzzy-only vendor match ⇒ REVIEW** (`VENDOR_005`) — fuzzy is a *lead*, never an auto-authorization.

## Phase 6 — Orchestration

**FastAPI BackgroundTasks, not Celery/Redis.** Single-node demo; the run ledger is the source of truth, not the queue. Trade-off accepted: a crash mid-run strands the row in PENDING/RUNNING (retry endpoint exists). Production would swap the executor without changing the state machine.

**Atomic claim via `UPDATE ... WHERE status='PENDING'`.** `rowcount == 1` proves this worker owns the run; everything after the claim runs in that one worker's control flow. No distributed locks; SQLite serializes writers anyway.

**Per-stage transactions + immediate event commits.** Each stage persists its event with its own commit so the API can show partial progress live; a failure in stage N leaves stage N-1's history intact and sets run → FAILED with the stage's error message. **Technical failures never become business decisions** (the LLM doesn't get to vote FAILED→REVIEW).

**Decision is the last gate.** Validation stages are non-fatal-by-design for info stages (a failed duplication check feeds UNKNOWN → REVIEW), but a technical crash anywhere marks the run FAILED and persists whatever evidence survived.

**Pydantic as strict-schema boundary.** LLM output is advisory until it parses; the extractor cleans only mechanically-recoverable junk (currency glyphs, thousands separators) — it never synthesizes a missing field.

## Phase 7 — Frontend

**No component library.** Goal: a trustworthy AP console with a single, small, correct design system — 599 lines of CSS beat 200 KB of opinionated components. Zero design fragmentation, full control of a11y semantics.

**Live polling, not WebSockets.** GET `/api/runs/{id}` + `/events` on a 1.75 s interval; stop on terminal state; exponential backoff on consecutive failures with visible degraded banner. Simpler failure semantics beat socket recovery logic in a demo backend.

**Server-side pagination + filtering everywhere.** The client never loads the full table; search is debounced → server query; sorting uses `aria-sort`; tables drop low-value columns responsively.

**Document preview in-app.** The PDF is served inline from `/document` with strict content-disposition and server-side path sanitization — never a client-supplied path.

## Phase 8 — Reliability fixes (post-hoc hardening)

**Provider layer made share-safe.** Both OpenAI-compatible providers now go through `parse_llm_json()` (fence stripping + envelope slice); a markdown-fenced LLM response previously failed every call. 429s keep their honest message.

**Claim-failure no longer strands runs.** A `_claim_run` exception now marks the run FAILED with a receipt event.

**Balance re-verified at persistence time (TOCTOU close).** An APPROVE that passed validation can be downgraded by `AMOUNT_003` at commit time if the committed PO balance moved underneath it (another worker consumed it). Downgraded, never silently persisted.

**Read-only GET surface kept open deliberately.** Write/LLM-burning endpoints guarded by loopback-or-token; the guard is a tripwire, not auth (see SECURITY_POSTURE.md).
