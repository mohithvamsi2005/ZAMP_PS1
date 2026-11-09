import { useCallback, useState } from 'react';
import { useNavigate, useParams, Link } from 'react-router-dom';
import {
  ArrowLeft,
  ArrowRight,
  ArrowsClockwise,
  WifiSlash,
  CheckCircle,
  XCircle,
  CircleNotch,
  Robot,
  WarningCircle,
} from '@phosphor-icons/react';
import { useProcessingRun } from '../hooks/useProcessingRun';
import { retryFailedRun, ApiError } from '../api';
import { Timeline } from '../components/processing/Timeline';
import { ErrorState, Skeleton, EmptyState } from '../components/ui/primitives';
import { DecisionBadge, RunStatusBadge } from '../components/ui/StatusPill';
import { dateTime, duration, money } from '../utils/formatting';

export default function ProcessingRun() {
  const { runId = '' } = useParams<{ runId: string }>();
  const navigate = useNavigate();
  const { run, events, loading, polling, degraded, error, consecutiveFailures, retryNow } = useProcessingRun(runId);

  const [retrying, setRetrying] = useState(false);
  const [retryError, setRetryError] = useState<string | null>(null);

  const retry = useCallback(async () => {
    setRetrying(true);
    setRetryError(null);
    try {
      await retryFailedRun(runId);
      retryNow();
    } catch (err) {
      setRetryError(err instanceof ApiError ? err.message : 'Retry was rejected.');
    } finally {
      setRetrying(false);
    }
  }, [runId, retryNow]);

  if (loading) {
    return (
      <div className="grid grid-12">
        <div className="span-7"><div className="card">{Array.from({ length: 9 }, (_, i) => <Skeleton key={i} className="skeleton-line" />)}</div></div>
        <div className="span-5"><Skeleton style={{ height: 380 }} /></div>
      </div>
    );
  }

  if (error) {
    return <ErrorState message={error} onRetry={() => navigate('/runs')} />;
  }

  const status = run?.status ?? 'PENDING';
  const decision = run?.decision ?? null;
  const isFailed = status === 'FAILED';
  const isComplete = status === 'COMPLETED';

  return (
    <div className="grid grid-12">
      {/* ── Left: live timeline ─────────────────────────────────────────── */}
      <section className="card span-7" aria-labelledby="timeline-heading">
        <div className="card-header">
          <div>
            <h2 id="timeline-heading">Live processing timeline</h2>
            <div className="sub" style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
              {polling ? (
                <><CircleNotch size={12} className="spinner" weight="bold" aria-hidden="true" style={{ color: 'var(--amber)' }} /> Polling every ~2s — {events.length} events recorded</>
              ) : (
                <>Run finished — {events.length} events persisted</>
              )}
            </div>
          </div>
          <Link to="/runs" className="card-title-link">
            <ArrowLeft size={12} weight="bold" aria-hidden="true" /> All runs
          </Link>
        </div>

        {degraded && (
          <div className="error-box" role="status" style={{ marginBottom: 12, borderColor: 'var(--amber-border)', background: 'var(--amber-tint)', color: 'var(--amber)' }}>
            <WifiSlash size={16} weight="fill" aria-hidden="true" style={{ flex: 'none', marginTop: 1 }} />
            <div>
              <strong>Connection interrupted{consecutiveFailures > 1 ? ` (attempt ${consecutiveFailures})` : ''}.</strong><br />
              Showing the last known state — retrying automatically.
              <div style={{ marginTop: 8 }}>
                <button className="btn btn-ghost btn-sm" onClick={retryNow}><ArrowsClockwise size={12} weight="bold" aria-hidden="true" /> Retry now</button>
              </div>
            </div>
          </div>
        )}

        <Timeline events={events} />
      </section>

      {/* ── Right: run summary / outcome ────────────────────────────────── */}
      <div className="span-5" style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
        <section className="card" aria-labelledby="summary-heading">
          <div className="card-header">
            <div>
              <h2 id="summary-heading">Run summary</h2>
              <div className="sub">Identifiers and engine configuration</div>
            </div>
            <RunStatusBadge status={status} />
          </div>
          <dl className="kv">
            <dt>Run ID</dt><dd><code className="key">{runId}</code></dd>
            <dt>Invoice</dt><dd>{run?.invoice?.invoice_number ?? `Invoice #${run?.invoice_id ?? '—'}`}</dd>
            <dt>Submitted</dt><dd>{dateTime(run?.started_at ?? run?.created_at)}</dd>
            <dt>Completed</dt><dd>{dateTime(run?.completed_at)}</dd>
            <dt>Duration</dt><dd>{duration(run && run.started_at && run.completed_at ? (new Date(run.completed_at).getTime() - new Date(run.started_at).getTime()) / 1000 : null)}</dd>
            <dt>LLM</dt>
            <dd>
              {run?.llm_provider
                ? <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}><Robot size={13} weight="fill" aria-hidden="true" style={{ color: 'var(--accent)' }} /><code className="key">{run.llm_provider} · {run.llm_model}</code></span>
                : <span style={{ color: 'var(--faint)' }}>—</span>}
            </dd>
          </dl>
        </section>

        {isFailed && (
          <section className="card" style={{ borderColor: 'var(--red-border)' }} role="alert">
            <div className="card-header" style={{ marginBottom: 8 }}>
              <h2 style={{ color: 'var(--red)', display: 'inline-flex', alignItems: 'center', gap: 8 }}>
                <XCircle size={18} weight="fill" aria-hidden="true" /> Processing failed
              </h2>
            </div>
            <p style={{ fontSize: 12.5, lineHeight: 1.55, color: 'var(--text)' }}>{run?.error_message ?? 'Unknown failure.'}</p>
            <p style={{ fontSize: 11.5, color: 'var(--muted)', margin: '10px 0 12px', lineHeight: 1.55 }}>
              This is a technical failure and will <strong>never</strong> be reported as a business decision. Fix the input (or the provider configuration) and retry — the failed attempt is kept in the audit history.
            </p>
            <button className="btn btn-danger" onClick={retry} disabled={retrying}>
              {retrying ? <><CircleNotch size={14} className="spinner" aria-hidden="true" /> Re-queueing…</> : <><ArrowsClockwise size={14} weight="bold" aria-hidden="true" /> Retry this run</>}
            </button>
            {retryError && <p className="field error" style={{ marginTop: 8 }}>{retryError}</p>}
          </section>
        )}

        {isComplete && (
          <section className="card" aria-labelledby="outcome-heading">
            <div className="card-header" style={{ marginBottom: 8 }}>
              <h2 id="outcome-heading">Outcome</h2>
              <DecisionBadge decision={decision} />
            </div>
            <div className={`decision-banner ${decision ?? 'FAILED'}`}>
              <span aria-hidden="true" style={{ marginTop: 2 }}>
                {decision === 'APPROVE' ? <CheckCircle size={20} weight="fill" color="var(--green)" />
                  : decision === 'REJECT' ? <XCircle size={20} weight="fill" color="var(--red)" />
                  : <WarningCircle size={20} weight="fill" color="var(--amber)" />}
              </span>
              <div>
                <div className="db-title">{decision ?? 'No decision'}</div>
                <div className="db-sub">{run?.decision_result?.summary ?? 'Decision recorded — see invoice detail for the full breakdown.'}</div>
              </div>
            </div>
            <dl className="kv" style={{ marginTop: 12 }}>
              <dt>Total</dt><dd className="num">{money(run?.invoice?.total_amount ?? run?.extraction?.total_amount ?? null)}</dd>
              <dt>Vendor</dt><dd>{run?.extraction?.vendor_name ?? '—'}</dd>
              <dt>PO reference</dt><dd><code className="key">{run?.extraction?.po_reference ?? '—'}</code></dd>
              <dt>Rules evaluated</dt><dd>{run?.decision_result?.rules_evaluated?.length ?? 0} rule(s)</dd>
            </dl>
            {run?.invoice_id && (
              <div style={{ marginTop: 12 }}>
                <button className="btn btn-primary" onClick={() => navigate(`/invoices/${run.invoice_id}`)}>
                  Open full invoice intelligence <ArrowRight size={14} weight="bold" aria-hidden="true" />
                </button>
              </div>
            )}
          </section>
        )}

        {!isComplete && !isFailed && (
          <EmptyState
            title={status === 'RUNNING' ? 'Pipeline in flight' : 'Waiting in queue'}
            sub={status === 'RUNNING'
              ? 'The worker is walking the document through every stage. This page updates live — no refresh needed.'
              : 'The upload was accepted and queued. The worker claims the run momentarily.'}
          />
        )}
      </div>
    </div>
  );
}
