import type { Decision, RunStatus } from '../types';

const inr = new Intl.NumberFormat('en-IN', {
  style: 'currency',
  currency: 'INR',
  maximumFractionDigits: 2,
});

/** Indian-grouped currency, always via Intl.NumberFormat. Inputs are decimal strings from the API. */
export function money(value?: string | number | null): string {
  if (value === null || value === undefined) return '—';
  const n = typeof value === 'string' ? Number(value) : value;
  if (!Number.isFinite(n)) return '—';
  return inr.format(n);
}

export function moneyRaw(value?: string | number | null): string {
  if (value === null || value === undefined) return '—';
  const n = typeof value === 'string' ? Number(value) : value;
  if (!Number.isFinite(n)) return String(value);
  return `${n.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

export function dateTime(value?: string | null): string {
  if (!value) return '—';
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return '—';
  return d.toLocaleString('en-IN', {
    day: '2-digit', month: 'short', year: 'numeric',
    hour: '2-digit', minute: '2-digit',
  });
}

export function dateShort(value?: string | null): string {
  if (!value) return '—';
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return '—';
  return d.toLocaleDateString('en-IN', { day: '2-digit', month: 'short', year: 'numeric' });
}

export function timeOnly(value?: string | null): string {
  if (!value) return '—';
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return '—';
  return d.toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit', second: '2-digit' });
}

/** Human duration from seconds: "900 ms", "12 s", "3m 40s". */
export function duration(seconds?: number | null): string {
  if (seconds === null || seconds === undefined) return '—';
  if (seconds < 1) return `${Math.round(seconds * 1000)} ms`;
  if (seconds < 60) return `${seconds.toFixed(1)} s`;
  const m = Math.floor(seconds / 60);
  const s = Math.round(seconds % 60);
  return `${m}m ${s}s`;
}

export function relTimeFromNow(value?: string | null): string {
  if (!value) return '';
  const d = new Date(value).getTime();
  if (Number.isNaN(d)) return '';
  const diff = Date.now() - d;
  const s = Math.round(diff / 1000);
  if (s < 60) return `${s}s ago`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}m ago`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h ago`;
  const days = Math.floor(h / 24);
  return `${days}d ago`;
}

export function fileSize(bytes?: number | null): string {
  if (bytes === null || bytes === undefined) return '—';
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(2)} MB`;
}

import type { StatusTone } from '../types';

export type { StatusTone };

export const RUN_STATUS_META: Record<RunStatus, { label: string; tone: StatusTone }> = {
  PENDING: { label: 'Queued', tone: 'slate' },
  RUNNING: { label: 'Processing', tone: 'amber' },
  COMPLETED: { label: 'Processed', tone: 'green' },
  FAILED: { label: 'Failed', tone: 'red' },
};

export const DECISION_META: Record<Decision, { label: string; tone: StatusTone; long: string }> = {
  APPROVE: { label: 'Approve', tone: 'green', long: 'Approved for payment' },
  REVIEW: { label: 'Review', tone: 'amber', long: 'Needs human verification' },
  REJECT: { label: 'Reject', tone: 'red', long: 'Rejected — not payable' },
};

export function isDecision(value?: string | null): value is Decision {
  return value === 'APPROVE' || value === 'REVIEW' || value === 'REJECT';
}

export function isRunStatus(value?: string | null): value is RunStatus {
  return value === 'PENDING' || value === 'RUNNING' || value === 'COMPLETED' || value === 'FAILED';
}
