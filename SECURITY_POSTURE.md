# Zamp Invoice Intelligence — Security Posture (honest, and short)

This is a **localhost demo with no authentication**. It is not deployable as-is.
Read this before deploying to any shared network.

## What is true today

**Enforced:**

- PDF uploads validated by extension, empty-body check, 20 MB ceiling, `%PDF-` magic bytes — `validate_pdf`.
- Uploads are stored under generated server-side filenames (token + hash prefix) — user filenames never reach the filesystem.
- `/api/invoices/{id}/document` resolves to an absolute path under `UPLOAD_DIR` only — no arbitrary file read; no traversal.
- Duplicates, FK integrity, NOT-NULL/validators enforced at the DB; connection pool PRAGMA-enforces FK on every new connection.
- Secrets: no credentials in the repo (`.env` untracked and git-ignored; `git grep` finds nothing).
- Write/LLM-burning endpoints guarded by **loopback-or-token** (`app/core/security.py`):
  - 127.0.0.1 / ::1 / localhost (+ `testclient` for tests) always allowed.
  - Or, if `ZAMP_WRITE_TOKEN` is set, `X-Zamp-Token: <value>` header required.
- Rate limit on write/LLM endpoints (sliding window, per client host): 30/min uploads, 10/min diagnostics.
- CORS restricted to `http://localhost:5173` — no wildcard.
- No tracebacks in error responses; 409/422 pass only the message.
- `/health` returns service identifiers + provider/model — never env values, keys, paths.

**Not enforced (by design, documented):**

- No user accounts, sessions, RBAC — the demo serves one operator on one machine.
- No CSRF: no cookies in use, so no CSRF surface exists today (yet). Any future session mechanism must revisit this.
- No TLS — direct localhost HTTP; TLS terminates at the reverse proxy in any real deployment.
- Diagnostic endpoints (`/api/diagnostic/*`) remain privileged — guarded as above, still LLM-burning.

## Before deploying anywhere reachable by others

1. Set `ZAMP_WRITE_TOKEN` in the environment and require the `X-Zamp-Token` header on write endpoints (already wired; just set the env var).
2. Put the service behind a reverse proxy (nginx/Caddy) with TLS and an IP allowlist or an SSO gateway (e.g., oauth2-proxy).
3. Switch SQLite to Postgres with `pool_pre_ping` + proper `SELECT … FOR UPDATE` on the PO row for true balance locking (see `PHASE_4_8_DESIGN_DECISIONS.md` for why the TOCTOU down-grade exists as a belt-and-braces).
4. Rotate LLM provider keys (any key that was ever pasted in a chat should be considered leaked).
5. Add real authentication with role checks for review actions, and submission/review audit logging.
6. Run `pip audit` / `npm audit` on the deployed lockfiles.

## Claims that are *not* made

- This demo is not penetration-tested; the guard is a tripwire.
- Financial integrity is enforced by application logic + SQLite constraints, not by an independent ledger.
- The LLM is treated as an untrusted, fallible annotator; every "fact" it reports is re-checked before it affects money.
