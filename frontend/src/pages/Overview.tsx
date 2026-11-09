import { useCallback, useEffect, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import {
  Files,
  Gauge,
  CheckCircle,
  UserFocus,
  XCircle,
  WarningCircle,
  ArrowRight,
  ArrowsClockwise,
  UploadSimple,
} from '@phosphor-icons/react';
import { ApiError, getDashboardSummary } from '../api';
import type { DashboardSummary } from '../types';
import { Skeleton, ErrorState, EmptyState } from '../components/ui/primitives';
import { DecisionDonut } from '../components/dashboard/DecisionDonut';
import { ActivityBars } from '../components/dashboard/ActivityBars';
import { RecentRunsTable } from '../components/dashboard/RecentRunsTable';
import { duration } from '../utils/formatting';

export default function Overview() {
  const [summary, setSummary] = useState<DashboardSummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const navigate = useNavigate();

  const load = useCallback(async () => {
    setLoading(true);
    try {
      setSummary(await getDashboardSummary());
      setError(null);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Could not load dashboard metrics.');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  if (loading && !summary) {
    return (
      <div className="grid grid-12">
        {Array.from({ length: 6 }, (_, i) => <div key={i} className="span-4"><Skeleton className="skeleton-tile" /></div>)}
        <div className="span-8"><Skeleton style={{ height: 320 }} /></div>
        <div className="span-4"><Skeleton style={{ height: 320 }} /></div>
        <div className="span-12"><Skeleton style={{ height: 280 }} /></div>
      </div>
    );
  }

  if (error && !summary) {
    return <ErrorState message={error} onRetry={load} />;
  }

  const s = summary as DashboardSummary;
  const t = s.totals;
  const failed = t.failed_runs;
  const processing = t.pending_runs + t.running_runs;

  return (
    <div className="grid grid-12">
      {error && (
        <div className="span-12">
          <ErrorState message={`Showing stale data — refresh failed: ${error}`} onRetry={load} />
        </div>
      )}

      {/* ── Row 1: metric tiles ─────────────────────────────────────────── */}
      <div className="metric span-4">
        <div className="metric-top">
          <div className="metric-label">Total invoices submitted</div>
          <Files className="metric-icon" weight="duotone" aria-hidden="true" />
        </div>
        <div className="metric-value num" data-testid="metric-total">{t.invoices}</div>
        <div className="metric-foot">{t.runs} processing run{t.runs === 1 ? '' : 's'} recorded in total</div>
      </div>

      <div className="metric metric-accent span-4">
        <div className="metric-top">
          <div className="metric-label">Processed to completion</div>
          <Gauge className="metric-icon" weight="duotone" aria-hidden="true" />
        </div>
        <div className="metric-value num" data-testid="metric-completed">{t.completed_runs}</div>
        <div className="metric-foot"><strong>{t.invoices}</strong> submitted → completed via workflow</div>
      </div>

      <div className="metric span-4">
        <div className="metric-top">
          <div className="metric-label">Approved</div>
          <CheckCircle className="metric-icon" weight="duotone" aria-hidden="true" />
        </div>
        <div className="metric-value num" data-testid="metric-approved">{s.decisions.APPROVE}</div>
        <div className="metric-foot">
          {s.approval_rate === null
            ? 'No decisions recorded yet'
            : <><strong>{s.approval_rate}%</strong> approval rate (of decided runs)</>}
        </div>
      </div>

      <Link to="/review" className="metric warn span-4" style={{ textDecoration: 'none', color: 'inherit' }}>
        <div className="metric-top">
          <div className="metric-label">Awaiting human review</div>
          <UserFocus className="metric-icon" weight="duotone" aria-hidden="true" />
        </div>
        <div className="metric-value num" data-testid="metric-review">{s.review_queue}</div>
        <div className="metric-foot" style={{ color: 'var(--amber)', fontWeight: 600 }}>
          Open the review queue <ArrowRight size={11} weight="bold" aria-hidden="true" style={{ verticalAlign: '-2px' }} />
        </div>
      </Link>

      <div className="metric span-4">
        <div className="metric-top">
          <div className="metric-label">Rejected</div>
          <XCircle className="metric-icon" weight="duotone" aria-hidden="true" />
        </div>
        <div className="metric-value num" data-testid="metric-rejected">{s.decisions.REJECT}</div>
        <div className="metric-foot">Business decision — duplicate, blocked vendor, balance exceeded</div>
      </div>

      <div className={`metric span-4${failed > 0 ? ' metric-danger' : ''}`}>
        <div className="metric-top">
          <div className="metric-label">Technical failures</div>
          <WarningCircle className="metric-icon" weight="duotone" aria-hidden="true" />
        </div>
        <div className="metric-value num" data-testid="metric-failed">{failed}</div>
        <div className="metric-foot">
          {failed > 0 ? 'Never a business decision — investigate and retry from History' : 'Clean run history — no technical failures'}
        </div>
      </div>

      {/* ── Row 2: decision distribution + activity ──────────────────────── */}
      <section className="card span-8">
        <div className="card-header">
          <div>
            <h2>Decision distribution</h2>
            <div className="sub">COMPLETED runs only — technical failures excluded from the split</div>
          </div>
          <Link className="card-title-link" to="/runs">Processing history <ArrowRight size={11} weight="bold" aria-hidden="true" /></Link>
        </div>
        <DecisionDonut decisions={s.decisions} failedRuns={failed} />
      </section>

      <section className="card span-4">
        <div className="card-header">
          <div>
            <h2>Ingest — last 14 days</h2>
            <div className="sub">Invoices submitted per day (UTC)</div>
          </div>
          <button className="btn btn-ghost btn-sm" onClick={load} disabled={loading} title="Refresh metrics">
            <ArrowsClockwise size={13} weight="bold" aria-hidden="true" />
            {loading ? 'Refreshing…' : 'Refresh'}
          </button>
        </div>
        <ActivityBars points={s.activity_last_14_days} />
        <div className="metric-foot" style={{ marginTop: 10 }}>
          Average processing: <strong>{duration(s.avg_processing_seconds)}</strong>
          {processing > 0 && <> · <strong style={{ color: 'var(--amber)' }}>{processing} in flight</strong></>}
        </div>
      </section>

      {/* ── Row 3: recent activity ──────────────────────────────────────── */}
      <section className="card span-8">
        <div className="card-header">
          <div>
            <h2>Recent processing activity</h2>
            <div className="sub">Latest {s.recent_runs.length} run{s.recent_runs.length === 1 ? '' : 's'} across all invoices</div>
          </div>
          <button className="btn btn-primary btn-sm" onClick={() => navigate('/upload')}>
            <UploadSimple size={14} weight="bold" aria-hidden="true" />
            Upload invoice
          </button>
        </div>
        <RecentRunsTable runs={s.recent_runs} />
      </section>

      {/* ── Row 3b: failed runs ─────────────────────────────────────────── */}
      <section className="card span-4">
        <div className="card-header">
          <div>
            <h2>Latest technical failures</h2>
            <div className="sub">Never counted as a business decision</div>
          </div>
          <Link className="card-title-link" to="/runs?status=FAILED">All failures <ArrowRight size={11} weight="bold" aria-hidden="true" /></Link>
        </div>
        {s.latest_failed_runs.length === 0 ? (
          <EmptyState title="No failures" sub="Every completed run reached a business decision. Failures will appear here when something breaks." />
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
            {s.latest_failed_runs.map((r) => (
              <div key={r.run_id} style={{ border: '1px solid var(--red-border)', background: 'var(--red-tint)', borderRadius: 'var(--radius-sm)', padding: '10px 12px' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8 }}>
                  <div style={{ fontWeight: 620 }}>{r.invoice_number ?? 'Unnumbered'}</div>
                  <span className="mono" style={{ fontSize: 10.5, color: 'var(--red)' }}>{r.run_id.slice(0, 8)}</span>
                </div>
                <p style={{ fontSize: 11.5, color: '#7a3230', margin: '4px 0 6px', lineHeight: 1.5 }}
                   title={r.error_message ?? ''}>
                  {(r.error_message ?? 'Unknown failure').slice(0, 140)}{(r.error_message ?? '').length > 140 ? '…' : ''}
                </p>
                {r.invoice_id && (
                  <Link to={`/invoices/${r.invoice_id}`} className="card-title-link">
                    Investigate <ArrowRight size={11} weight="bold" aria-hidden="true" />
                  </Link>
                )}
              </div>
            ))}
          </div>
        )}
      </section>
    </div>
  );
}
