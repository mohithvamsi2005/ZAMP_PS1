import { useCallback, useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { MagnifyingGlass, CaretLeft, CaretRight, ArrowsDownUp } from '@phosphor-icons/react';
import { ApiError, listInvoices } from '../api';
import type { Decision, InvoiceListItem, InvoiceListResponse, RunStatus } from '../types';
import { Skeleton, ErrorState, EmptyState, SmallSpinner } from '../components/ui/primitives';
import { DecisionBadge, RunStatusBadge } from '../components/ui/StatusPill';
import { dateShort, money } from '../utils/formatting';

const DECISION_FILTERS: Array<{ value: '' | Decision; label: string }> = [
  { value: '', label: 'All decisions' },
  { value: 'APPROVE', label: 'Approved' },
  { value: 'REVIEW', label: 'Review' },
  { value: 'REJECT', label: 'Rejected' },
];

const STATUS_FILTERS: Array<{ value: '' | RunStatus; label: string }> = [
  { value: '', label: 'All statuses' },
  { value: 'COMPLETED', label: 'Processed' },
  { value: 'PENDING', label: 'Queued' },
  { value: 'RUNNING', label: 'Processing' },
  { value: 'FAILED', label: 'Failed' },
];

type SortKey = 'submission' | 'total_amount';

export default function Invoices() {
  const navigate = useNavigate();
  const [search, setSearch] = useState('');
  const [debouncedSearch, setDebouncedSearch] = useState('');
  const [decision, setDecision] = useState<'' | Decision>('');
  const [status, setStatus] = useState<'' | RunStatus>('');
  const [sortBy, setSortBy] = useState<SortKey>('submission');
  const [sortDir, setSortDir] = useState<'asc' | 'desc'>('desc');
  const [page, setPage] = useState(1);
  const pageSize = 20;

  const [data, setData] = useState<InvoiceListResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [fetching, setFetching] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Debounce search input → server round-trips
  useEffect(() => {
    const t = setTimeout(() => {
      setDebouncedSearch(search.trim());
      setPage(1);
    }, 250);
    return () => clearTimeout(t);
  }, [search]);

  const load = useCallback(async () => {
    const first = data === null;
    if (first) setLoading(true); else setFetching(true);
    try {
      const resp = await listInvoices({
        search: debouncedSearch || undefined,
        decision: decision || undefined,
        status: status || undefined,
        sort_by: sortBy,
        sort_dir: sortDir,
        page,
        page_size: pageSize,
      });
      setData(resp);
      setError(null);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Could not load invoices.');
    } finally {
      setLoading(false);
      setFetching(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [debouncedSearch, decision, status, sortBy, sortDir, page]);

  useEffect(() => {
    load();
  }, [load]);

  const totalPages = useMemo(() => (data ? Math.max(1, Math.ceil(data.total / data.page_size)) : 1), [data]);

  const toggleSort = (key: SortKey) => {
    if (sortBy === key) {
      setSortDir((d) => (d === 'desc' ? 'asc' : 'desc'));
    } else {
      setSortBy(key);
      setSortDir('desc');
    }
    setPage(1);
  };

  if (loading && !data) {
    return (
      <div className="card">
        {Array.from({ length: 8 }, (_, i) => <Skeleton key={i} className="skeleton-line" />)}
      </div>
    );
  }

  if (error && !data) {
    return <ErrorState message={error} onRetry={load} />;
  }

  const rows = data?.invoices ?? [];
  const total = data?.total ?? 0;
  const from = total === 0 ? 0 : (page - 1) * pageSize + 1;
  const to = Math.min(page * pageSize, total);

  const sortIndicator = (key: SortKey) =>
    sortBy === key ? (sortDir === 'asc' ? ' ↑' : ' ↓') : <span className="sort-arrow"><ArrowsDownUp size={10} aria-hidden="true" /></span>;

  return (
    <div className="card">
      {/* ── Toolbar ─────────────────────────────────────────────────── */}
      <div className="invoice-toolbar" style={{ display: 'flex', gap: 10, flexWrap: 'wrap', alignItems: 'center', marginBottom: 12 }}>
        <div style={{ position: 'relative', flex: '1 1 240px', minWidth: 200 }}>
          <MagnifyingGlass
            size={16}
            weight="bold"
            aria-hidden="true"
            style={{ position: 'absolute', left: 10, top: '50%', transform: 'translateY(-50%)', color: 'var(--faint)' }}
          />
          <input
            className="input"
            style={{ paddingLeft: 34 }}
            placeholder="Search invoice number…"
            aria-label="Search by invoice number"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
        </div>

        <select className="select" style={{ width: 'auto' }} aria-label="Filter by decision"
                value={decision} onChange={(e) => { setDecision(e.target.value as Decision | ''); setPage(1); }}>
          {DECISION_FILTERS.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
        </select>

        <select className="select" style={{ width: 'auto' }} aria-label="Filter by processing status"
                value={status} onChange={(e) => { setStatus(e.target.value as RunStatus | ''); setPage(1); }}>
          {STATUS_FILTERS.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
        </select>

        {fetching && <span className="num" style={{ color: 'var(--faint)', display: 'inline-flex', alignItems: 'center', gap: 6 }}><SmallSpinner /> updating…</span>}
      </div>

      {error && <div style={{ marginBottom: 10 }}><ErrorState message={error} onRetry={load} /></div>}

      {/* ── Table ───────────────────────────────────────────────────── */}
      {rows.length === 0 ? (
        <EmptyState
          title={debouncedSearch ? `No invoices match “${debouncedSearch}”` : 'No invoices yet'}
          sub={debouncedSearch || decision || status
            ? 'Try clearing the filters — search matches the invoice number exactly as extracted.'
            : 'Uploads appear here as soon as processing runs are recorded against them.'}
          action={<button className="btn btn-primary btn-sm" onClick={() => navigate('/upload')}>Upload an invoice</button>}
        />
      ) : (
        <>
          <div className="table-wrap">
            <table className="table" aria-label="Invoice history">
              <thead>
                <tr>
                  <th>Invoice</th>
                  <th>Vendor</th>
                  <th className="col-hide">PO</th>
                  <th className="sortable num" aria-sort={sortBy === 'total_amount' ? (sortDir === 'asc' ? 'ascending' : 'descending') : 'none'} onClick={() => toggleSort('total_amount')}>
                    Total {sortIndicator('total_amount')}
                  </th>
                  <th className="sortable col-hide" style={{ paddingLeft: 10 }} aria-sort={sortBy === 'submission' ? (sortDir === 'asc' ? 'ascending' : 'descending') : 'none'} onClick={() => toggleSort('submission')}>
                    Submitted {sortIndicator('submission')}
                  </th>
                  <th>Status</th>
                  <th>Decision</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((inv: InvoiceListItem) => (
                  <tr key={inv.id} className="rowbtn" tabIndex={0} role="button"
                      aria-label={`Open invoice ${inv.invoice_number ?? inv.id}`}
                      onClick={() => navigate(`/invoices/${inv.id}`)}
                      onKeyDown={(e) => {
                        if (e.key === 'Enter' || e.key === ' ') {
                          e.preventDefault();
                          navigate(`/invoices/${inv.id}`);
                        }
                      }}>
                    <td>
                      <div style={{ fontWeight: 620 }}>{inv.invoice_number ?? <span style={{ color: 'var(--faint)' }}>Unnumbered</span>}</div>
                      <div className="mono" style={{ fontSize: 10, color: 'var(--faint)' }} title={inv.original_filename ?? ''}>
                        {inv.original_filename}
                      </div>
                    </td>
                    <td style={{ maxWidth: 200 }}>{inv.vendor_name ?? <span style={{ color: 'var(--faint)' }}>—</span>}</td>
                    <td className="col-hide mono">{inv.po_reference ?? '—'}</td>
                    <td className="num">{money(inv.total_amount)}</td>
                    <td className="col-hide" style={{ color: 'var(--muted)', fontSize: 11.5 }}>{dateShort(inv.created_at)}</td>
                    <td><RunStatusBadge status={inv.last_run_status ?? null} /></td>
                    <td><DecisionBadge decision={inv.last_run_decision ?? null} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <div className="table-footer">
            <span className="num">{from}–{to} of {total} invoice{total === 1 ? '' : 's'}</span>
            <div className="pager">
              <button className="btn btn-ghost btn-sm" aria-label="Previous page"
                      disabled={page <= 1} onClick={() => setPage((p) => Math.max(1, p - 1))}>
                <CaretLeft size={13} weight="bold" aria-hidden="true" /> Prev
              </button>
              <span className="num" style={{ minWidth: 64, textAlign: 'center' }}>Page {page} / {totalPages}</span>
              <button className="btn btn-ghost btn-sm" aria-label="Next page"
                      disabled={page >= totalPages} onClick={() => setPage((p) => p + 1)}>
                Next <CaretRight size={13} weight="bold" aria-hidden="true" />
              </button>
            </div>
          </div>
        </>
      )}
    </div>
  );
}
