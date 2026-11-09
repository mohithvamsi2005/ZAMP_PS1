import { Badge } from './primitives';
import { RUN_STATUS_META, isDecision, isRunStatus } from '../../utils/formatting';
import { DECISION_META } from '../../utils/formatting';
import type { Decision, RunStatus } from '../../types';

export function RunStatusBadge({ status }: { status?: RunStatus | null }) {
  if (!isRunStatus(status)) return <Badge tone="slate">No run</Badge>;
  const meta = RUN_STATUS_META[status];
  return <Badge tone={meta.tone}>{meta.label}</Badge>;
}

export function DecisionBadge({ decision }: { decision?: Decision | null }) {
  if (!isDecision(decision)) return <Badge tone="slate">No decision</Badge>;
  const meta = DECISION_META[decision];
  return (
    <Badge tone={meta.tone} title={meta.long}>
      {decision}
    </Badge>
  );
}

export function ValidationStatusBadge({ status }: { status?: string | null }) {
  const s = (status ?? '').toUpperCase();
  if (!s) return <Badge tone="slate">UNKNOWN</Badge>;
  switch (s) {
    case 'PASS':
    case 'MATCHED':
    case 'NO_DUPLICATE_FOUND':
      return <Badge tone="green">{s}</Badge>;
    case 'WARNING':
    case 'AMBIGUOUS':
    case 'POTENTIAL_DUPLICATE':
    case 'NEEDS_REVIEW':
      return <Badge tone="amber">{s}</Badge>;
    case 'FAIL':
    case 'UNMATCHED':
    case 'BLOCKED':
    case 'EXACT_DOCUMENT_DUPLICATE':
    case 'EXACT_INVOICE_DUPLICATE':
      return <Badge tone="red">{s}</Badge>;
    default:
      return <Badge tone="slate">{s}</Badge>;
  }
}
