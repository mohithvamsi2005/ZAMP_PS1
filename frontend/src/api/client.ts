/**
 * Central typed HTTP client.
 *
 * Behaviour contract (unit-tested):
 *   OK            → parsed JSON
 *   HTTP error    → ApiError { status, code, detail } with a human message built from the FastAPI `detail`
 *   network drop  → ApiError { code: 'NETWORK' }
 *   timeout       → ApiError { code: 'TIMEOUT' } after `timeoutMs` (default 10s)
 *   abort         → ApiError { code: 'ABORTED' } (never surfaces as user-facing error UI)
 *
 * The API base:
 *   VITE_API_URL (build-time) e.g. "http://127.0.0.1:8000" or "" for same-origin.
 *   Defaults to same-origin relative paths (`/api/...`) which the vite dev proxy (→ localhost:8000)
 *   satisfies in development and a same-origin reverse proxy satisfies in production.
 */

export type ApiErrorCode =
  | 'BAD_REQUEST'
  | 'NOT_FOUND'
  | 'CONFLICT'
  | 'VALIDATION'
  | 'SERVER'
  | 'NETWORK'
  | 'TIMEOUT'
  | 'ABORTED';

export class ApiError extends Error {
  readonly status: number | null;
  readonly code: ApiErrorCode;
  readonly detail: string | null;

  constructor(code: ApiErrorCode, status: number | null, message: string, detail?: string | null) {
    super(message);
    this.name = 'ApiError';
    this.code = code;
    this.status = status;
    this.detail = detail ?? null;
  }
}

const API_ROOT = (import.meta.env.VITE_API_URL ?? '').replace(/\/$/, '');

export function apiUrl(path: string): string {
  return `${API_ROOT}/api${path}`;
}

export function backendRootUrl(path: string): string {
  return `${API_ROOT}${path}`;
}

function codeForStatus(status: number): ApiErrorCode {
  if (status === 400) return 'BAD_REQUEST';
  if (status === 404) return 'NOT_FOUND';
  if (status === 409) return 'CONFLICT';
  if (status === 422) return 'VALIDATION';
  return 'SERVER';
}

function messageForStatus(status: number, detail: string | null): string {
  const d = detail?.trim();
  switch (status) {
    case 400: return d ? `Upload rejected: ${d}` : 'The request was rejected as invalid.';
    case 404: return d ?? 'The requested resource was not found.';
    case 409: return d ?? 'That action is not possible in the current state.';
    case 422: return d ?? 'A parameter failed validation.';
    case 500:
    case 502:
    case 503:
    case 504:
      return d ? `Backend error: ${d}` : 'The backend returned an error. Try again shortly.';
    default: return d ?? `Request failed (${status}).`;
  }
}

export interface RequestOptions {
  signal?: AbortSignal;
  timeoutMs?: number;
}

export async function apiFetch<T>(path: string, init: RequestInit = {}, opts: RequestOptions = {}): Promise<T> {
  const timeoutMs = opts.timeoutMs ?? 10_000;
  const controller = new AbortController();
  const outerSignal = opts.signal;
  const onOuterAbort = () => controller.abort();
  if (outerSignal) {
    if (outerSignal.aborted) controller.abort();
    else outerSignal.addEventListener('abort', onOuterAbort, { once: true });
  }
  const timeoutId = setTimeout(() => controller.abort(), timeoutMs);

  const headers = new Headers(init.headers ?? {});
  const isFormData = typeof FormData !== 'undefined' && init.body instanceof FormData;
  if (!isFormData && init.body !== undefined && !headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json');
  }

  try {
    const resp = await fetch(apiUrl(path), { ...init, headers, signal: controller.signal });
    clearTimeout(timeoutId);

    if (!resp.ok) {
      // Any 401 flips the app back to the login gate (single-tenant console)
      if (resp.status === 401 && typeof window !== 'undefined') {
        window.dispatchEvent(new CustomEvent('zamp:unauthenticated'));
      }
      const detail = await tryParseDetail(resp);
      throw new ApiError(codeForStatus(resp.status), resp.status, messageForStatus(resp.status, detail), detail);
    }
    if (resp.status === 204) return undefined as T;
    return (await resp.json()) as T;
  } catch (err) {
    clearTimeout(timeoutId);
    if (err instanceof ApiError) throw err;
    if (isAbortError(err)) {
      throw controller.signal.aborted && outerSignal?.aborted
        ? new ApiError('ABORTED', null, 'The request was cancelled.')
        : new ApiError('TIMEOUT', null, 'The request timed out. The backend may be busy or unreachable.');
    }
    // Network-level failure (DNS, connection refused, TLS, CORS)
    throw new ApiError('NETWORK', null, 'Cannot reach the backend. Check that the API server is running and try again.');
  } finally {
    if (outerSignal) outerSignal.removeEventListener('abort', onOuterAbort);
  }
}

async function tryParseDetail(resp: Response): Promise<string | null> {
  try {
    const body = await resp.json();
    if (typeof body === 'string') return body;
    const detail = (body as { detail?: unknown }).detail;
    if (typeof detail === 'string') return detail;
    if (Array.isArray(detail)) return detail.map((d) => (d as { msg?: string }).msg ?? String(d)).join('; ');
    return JSON.stringify(body);
  } catch {
    try {
      return (await resp.text()) || null;
    } catch {
      return null;
    }
  }
}

function isAbortError(err: unknown): boolean {
  return (
    (typeof DOMException !== 'undefined' && err instanceof DOMException && err.name === 'AbortError') ||
    (err instanceof Error && err.name === 'AbortError')
  );
}

export function apiPost<T>(path: string, body?: unknown, opts?: RequestOptions): Promise<T> {
  return apiFetch<T>(path, { method: 'POST', body: body === undefined ? undefined : JSON.stringify(body) }, opts);
}

export function apiGet<T>(path: string, opts?: RequestOptions): Promise<T> {
  return apiFetch<T>(path, { method: 'GET' }, opts);
}
