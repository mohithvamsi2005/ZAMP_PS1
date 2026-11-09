import { useCallback, useEffect, useMemo, useState } from 'react';
import { useNavigate, useSearchParams, Link } from 'react-router-dom';
import { ArrowsClockwise, CaretLeft, CaretRight, CheckCircle } from '@phosphor-icons/react';
import { ApiError, listRuns, retryFailedRun } from '../api';
import type { Decision, RunsListResponse, RunStatus } from '../types';
import { Skeleton, ErrorState, EmptyState, SmallSpinner } from '../components/ui/primitives';
import { DecisionBadge, RunStatusBadge } from '../components/ui/StatusPill';
import { dateTime, duration } from '../utils/formatting';

type StatusFilter = '' | RunStatus;
type DecisionFilter = '' | Decision;

const PAGE_SIZE = 20;

export default function History() {
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const [status, setStatus] = useState<StatusFilter>((searchParams.get('status') as StatusFilter) || '');
  const [decision, setDecision] = useState<DecisionFilter>((searchParams.get('decision') as DecisionFilter) || '');
  const [page, setPage] = useState(1);

  const [data, setData] = useState<RunsListResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [fetching, setFetching] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [retryingId, setRetryingId] = useState<string | null>(null);

  const syncParams = useCallback((s: StatusFilter, d: DecisionFilter) => {
    const next = new URLSearchParams();
    if (s) next.set('status', s);
    if (d) next.set('decision', d);
    setSearchParams(next, { replace: true });
  }, [setSearchParams]);

  const load = useCallback(async () => {
    const first = data === null;
    if (first) setLoading(true); else setFetching(true);
    try {
      setData(await listRuns({
        status: status || undefined,
        decision: decision || undefined,
        page,
        pageSize: PAGE_SIZE,
      }));
      setError(null);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Could not load processing history.');
    } finally {
      setLoading(false);
      setFetching(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [status, decision, page]);

  useEffect(() => {
    load();
  }, [load]);

  const retry = useCallback(async (runId: string) => {
    setRetryingId(runId);
    try {
      await retryFailedRun(runId);
      // Best-effort local flip: after F→P the worker re-claims; navigate to live view
      navigate(`/processing/${runId}`);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Retry rejected.');
    } finally {
      setRetryingId(null);
    }
  }, [navigate]);

  const totalPages = useMemo(() => (data ? Math.max(1, Math.ceil(data.total / data.page_size)) : 1), [data]);

  if (loading && !data) {
    return <div className="card">{Array.from({ length: 6 }, (_, i) => <Skeleton key={i} className="skeleton-line" />)}</div>;
  }
  if (error && !data) return <ErrorState message={error} onRetry={load} />;

  const runs = data?.runs ?? [];
  const from = (data?.total ?? 0) === 0 ? 0 : (page - 1) * PAGE_SIZE + 1;
  const to = Math.min(page * PAGE_SIZE, data?.total ?? 0);

  return (
    <div className="card">
      <div style={{ display: 'flex', gap: 10, alignItems: 'center', marginBottom: 12, flexWrap: 'wrap' }}>
        <label className="field" style={{ flexDirection: 'row', gap: 8, alignItems: 'center' }}>
          <span style={{ fontSize: 11.5, fontWeight: 600, color: 'var(--muted)' }}>Status</span>
          <select className="select" style={{ width: 'auto' }} aria-label="Filter by run status"
                  value={status} onChange={(e) => { const v = e.target.value as StatusFilter; setStatus(v); syncParams(v, decision); setPage(1); }}>
            <option value="">All</option>
            <option value="COMPLETED">Processed</option>
            <option value="PENDING">Queued</option>
            <option value="RUNNING">Processing</option>
            <option value="FAILED">Failed</option>
          </select>
        </label>
        <label className="field" style={{ flexDirection: 'row', gap: 8, alignItems: 'center' }}>
          <span style={{ fontSize: 11.5, fontWeight: 600, color: 'var(--muted)' }}>Decision</span>
          <select className="select" style={{ width: 'auto' }} aria-label="Filter by decision"
                  value={decision} onChange={(e) => { const v = e.target.value as DecisionFilter; setDecision(v); syncParams(status, v); setPage(1); }}>
            <option value="">All</option>
            <option value="APPROVE">Approved</option>
            <option value="REVIEW">Review</option>
            <option value="REJECT">Rejected</option>
          </select>
        </label>
        {fetching && <span className="num" style={{ color: 'var(--faint)', display: 'inline-flex', gap: 6, alignItems: 'center' }}><SmallSpinner /> updating…</span>}
        <Link to="/invoices" className="btn btn-ghost btn-sm" style={{ marginLeft: 'auto' }}>Invoice-centric view</Link>
      </div>

      {error && <div style={{ marginBottom: 10 }}><ErrorState message={error} onRetry={load} /></div>}

      {runs.length === 0 ? (
        <EmptyState title="No runs match these filters" sub="Widen the status or decision filters — run history accrues one row per processing attempt." />
      ) : (
        <>
          <div className="table-wrap">
            <table className="table" aria-label="Processing run history">
              <thead>
                <tr>
                  <th>Run</th><th>Invoice</th><th>Started</th><th>Duration</th>
                  <th>Status</th><th>Decision</th><th><span className="sr-only">Actions</span></th>
                </tr>
              </thead>
              <tbody>
                {runs.map((r) => (
                  <tr key={r.run_id} className="rowbtn" tabIndex={0} role="button"
                      aria-label={`Open run ${r.run_id}`}
                      onClick={() => navigate(`/processing/${r.run_id}`)}
                      onKeyDown={(e) => {
                        if (e.key === 'Enter' || e.key === ' ') {
                          e.preventDefault();
                          navigate(`/processing/${r.run_id}`);
                        }
                      }}>
                    <td><code className="key">{r.run_id.slice(0, 13)}…</code></td>
                    <td>{r.invoice_id ? `#${r.invoice_id}` : '—'}</td>
                    <td className="col-hide" style={{ color: 'var(--muted)', fontSize: 11.5 }}>{dateTime(r.started_at)}</td>
                    <td className="col-hide" style={{ color: 'var(--muted)' }}>{duration(r.started_at && r.completed_at ? (new Date(r.completed_at).getTime() - new Date(r.started_at).getTime()) / 1000 : null)}</td>
                    <td><RunStatusBadge status={r.status} /></td>
                    <td><DecisionBadge decision={r.decision ?? null} /></td>
                    <td>
                      {r.status === 'FAILED' ? (
                        <button
                          className="btn btn-danger btn-sm"
                          disabled={retryingId === r.run_id}
                          onClick={(e) => { e.stopPropagation(); retry(r.run_id); }}
                        >
                          {retryingId === r.run_id ? <><SmallSpinner /> Re-queueing…</> : <><ArrowsClockwise size={12} weight="bold" aria-hidden="true" /> Retry</>}
                        </button>
                      ) : r.status === 'COMPLETED' ? (
                        <span className="num" style={{ color: 'var(--green)', fontSize: 11.5, display: 'inline-flex', gap: 5, alignItems: 'center' }}><CheckCircle size={12} weight="fill" aria-hidden="true" /> finished</span>
                      ) : (
                        <span className="num" style={{ color: 'var(--faint)', fontSize: 11.5 }}>—</span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="table-footer">
            <span className="num">{from}–{to} of {data?.total ?? 0} run{(data?.total ?? 0) === 1 ? '' : 's'}</span>
            <div className="pager">
              <button className="btn btn-ghost btn-sm" aria-label="Previous page" disabled={page <= 1} onClick={() => setPage((p) => Math.max(1, p - 1))}>
                <CaretLeft size={13} weight="bold" aria-hidden="true" /> Prev
              </button>
              <span className="num" style={{ minWidth: 64, textAlign: 'center' }}>Page {page} / {totalPages}</span>
              <button className="btn btn-ghost btn-sm" aria-label="Next page" disabled={page >= totalPages} onClick={() => setPage((p) => p + 1)}>
                Next <CaretRight size={13} weight="bold" aria-hidden="true" />
              </button>
            </div>
          </div>
        </>
      )}
    </div>
  );
}
