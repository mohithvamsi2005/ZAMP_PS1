import type { Decision, RunStatus, StatusTone } from '../types';
import { RUN_STATUS_META, DECISION_META } from '../utils/formatting';

export type { StatusTone };
export { RUN_STATUS_META, DECISION_META };

/** Map any VALIDATION status (PASS/FAIL/WARNING/UNKNOWN/…) onto the badge palette. */
export function validationTone(status?: string | null): StatusTone {
  const s = (status ?? '').toUpperCase();
  switch (s) {
    case 'PASS':
    case 'MATCHED':
    case 'NO_DUPLICATE_FOUND':
      return 'green';
    case 'WARNING':
    case 'AMBIGUOUS':
    case 'POTENTIAL_DUPLICATE':
    case 'NEEDS_REVIEW':
    case 'PROVISIONAL':
      return 'amber';
    case 'FAIL':
    case 'EXACT_DOCUMENT_DUPLICATE':
    case 'EXACT_INVOICE_DUPLICATE':
    case 'UNMATCHED':
    case 'BLOCKED':
      return 'red';
    case 'UNKNOWN':
    case 'MISSING_PO':
    case 'NOT_RUN':
      return 'slate';
    default:
      return 'slate';
  }
}

export function eventStatusTone(status?: string | null): StatusTone {
  switch ((status ?? '').toUpperCase()) {
    case 'COMPLETED': return 'green';
    case 'RUNNING': return 'amber';
    case 'WARNING': return 'amber';
    case 'FAILED': return 'red';
    case 'SKIPPED':
    case 'PENDING':
    default: return 'slate';
  }
}

/** Badge class suffix for a tone (kept a single source of truth). */
export function toneClass(tone: StatusTone): string {
  return `badge-${tone}`;
}

export const DECISION_LABELS: Record<Decision, string> = {
  APPROVE: 'Approve',
  REVIEW: 'Review',
  REJECT: 'Reject',
};

export const RUN_STATUS_LABELS: Record<RunStatus, string> = {
  PENDING: 'Queued',
  RUNNING: 'Processing',
  COMPLETED: 'Processed',
  FAILED: 'Failed',
};
