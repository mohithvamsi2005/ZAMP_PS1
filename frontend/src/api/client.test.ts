import { describe, it, expect, vi } from 'vitest';
import { apiFetch, apiGet, ApiError } from './client';

const asApiError = (e: unknown): ApiError => e as ApiError;

function mockResponse(status: number, body: unknown, contentType = 'application/json') {
  const text = typeof body === 'string' ? body : JSON.stringify(body);
  return new Response(text, {
    status,
    headers: { 'content-type': contentType },
  });
}

describe('apiFetch', () => {
  it('parses JSON on success', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => mockResponse(200, { hello: 'world' })));
    await expect(apiGet<{ hello: string }>('/health-check')).resolves.toEqual({ hello: 'world' });
  });

  it('throws ApiError with server detail on 400', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => mockResponse(400, { detail: 'Invalid PDF: missing %PDF header' })));
    const err = asApiError(await apiGet('/invoices/upload').catch((e) => e));
    expect(err).toBeInstanceOf(ApiError);
    expect(err.status).toBe(400);
    expect(err.code).toBe('BAD_REQUEST');
    expect(err.message).toContain('Invalid PDF');
  });

  it('maps 404 to NOT_FOUND', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => mockResponse(404, { detail: 'Processing run nope not found' })));
    const err = asApiError(await apiGet('/runs/nope').catch((e) => e));
    expect(err.code).toBe('NOT_FOUND');
    expect(err.message).toContain('not found');
  });

  it('maps 409 to CONFLICT', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => mockResponse(409, { detail: 'Run is still RUNNING; result not yet available' })));
    const err = asApiError(await apiGet('/runs/abc/result').catch((e) => e));
    expect(err.status).toBe(409);
    expect(err.code).toBe('CONFLICT');
  });

  it('maps 422 validation arrays into a readable message', async () => {
    vi.stubGlobal('fetch', vi.fn(async () =>
      mockResponse(422, { detail: [{ msg: 'field required' }, { msg: 'bad enum' }] })));
    const err = asApiError(await apiFetch('/runs', { method: 'GET' }).catch((e) => e));
    expect(err.code).toBe('VALIDATION');
    expect(err.message).toContain('field required');
  });

  it('maps 500 to SERVER with generic message when no detail is present', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => mockResponse(500, '<html>boom</html>', 'text/html')));
    const err = asApiError(await apiFetch('/runs', { method: 'GET' }).catch((e) => e));
    expect(err.code).toBe('SERVER');
  });

  it('maps connection failure to NETWORK', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => {
      throw new TypeError('fetch failed');
    }));
    const err = asApiError(await apiFetch('/runs', { method: 'GET' }).catch((e) => e));
    expect(err.code).toBe('NETWORK');
    expect(err.message).toMatch(/backend/i);
  });

  it('maps timeout to TIMEOUT without hanging forever', async () => {
    vi.stubGlobal('fetch', vi.fn((_input: RequestInfo | URL, init?: RequestInit) =>
      new Promise<Response>((_resolve, reject) => {
        const signal = init?.signal;
        signal?.addEventListener('abort', () => {
          reject(new DOMException('The operation was aborted.', 'AbortError'));
        });
      }),
    ));
    const err = asApiError(await apiFetch('/runs', { method: 'GET' }, { timeoutMs: 30 }).catch((e) => e));
    expect(err.code).toBe('TIMEOUT');
  });
});
