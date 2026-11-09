/** Backend reachability probe (GET /health — lives outside /api). */
import { ApiError, backendRootUrl } from './client';
import type { HealthResponse } from '../types';

export async function fetchHealth(signal?: AbortSignal): Promise<HealthResponse> {
  const controller = new AbortController();
  const onOuterAbort = () => controller.abort();
  signal?.addEventListener('abort', onOuterAbort, { once: true });
  const timeoutId = setTimeout(() => controller.abort(), 5000);
  try {
    const resp = await fetch(backendRootUrl('/health'), { signal: controller.signal });
    if (!resp.ok) throw new ApiError('SERVER', resp.status, `Health check failed (${resp.status}).`);
    return (await resp.json()) as HealthResponse;
  } catch (err) {
    if (err instanceof ApiError) throw err;
    throw new ApiError('NETWORK', null, 'Cannot reach the backend.');
  } finally {
    clearTimeout(timeoutId);
    signal?.removeEventListener('abort', onOuterAbort);
  }
}
