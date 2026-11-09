import { apiFetch, apiGet, apiPost } from './client';
import type { Decision, RunDetail, RunEvent, RunStatus, RunsListResponse } from '../types';

export interface RunListParams {
  status?: RunStatus;
  decision?: Decision;
  invoiceId?: number;
  page?: number;
  pageSize?: number;
}

export function listRuns(params: RunListParams = {}): Promise<RunsListResponse> {
  const q = new URLSearchParams();
  if (params.status) q.set('status', params.status);
  if (params.decision) q.set('decision', params.decision);
  if (params.invoiceId !== undefined) q.set('invoice_id', String(params.invoiceId));
  q.set('page', String(params.page ?? 1));
  q.set('page_size', String(params.pageSize ?? 20));
  return apiGet<RunsListResponse>(`/runs?${q.toString()}`);
}

export function getRun(runId: string, signal?: AbortSignal): Promise<RunDetail> {
  return apiFetch<RunDetail>(`/runs/${runId}`, { method: 'GET' }, { signal, timeoutMs: 8000 });
}

export function getRunEvents(runId: string, signal?: AbortSignal): Promise<RunEvent[]> {
  return apiFetch<RunEvent[]>(`/runs/${runId}/events`, { method: 'GET' }, { signal, timeoutMs: 8000 });
}

export type RunResult = RunDetail;

/** GET /api/runs/{id}/result — throws ApiError with code CONFLICT while the run is pending (expected). */
export function getRunResult(runId: string, signal?: AbortSignal): Promise<RunResult> {
  return apiFetch<RunResult>(`/runs/${runId}/result`, { method: 'GET' }, { signal, timeoutMs: 8000 });
}

export function retryFailedRun(runId: string): Promise<{ run_id: string; status: string; message: string }> {
  return apiPost(`/runs/${runId}/retry`, {});
}
