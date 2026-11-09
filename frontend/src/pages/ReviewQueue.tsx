import { useCallback, useEffect, useState } from 'react';
import { useNavigate, Link } from 'react-router-dom';
import { ListChecks, ArrowRight, Buildings } from '@phosphor-icons/react';
import { ApiError, listInvoices } from '../api';
import type { InvoiceListResponse } from '../types';
import { Skeleton, ErrorState, EmptyState } from '../components/ui/primitives';
import { DecisionBadge } from '../components/ui/StatusPill';
import { dateShort, money } from '../utils/formatting';

export default function ReviewQueue() {
  const navigate = useNavigate();
  const [data, setData] = useState<InvoiceListResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      setData(await listInvoices({ decision: 'REVIEW', page_size: 50, sort_by: 'submission', sort_dir: 'desc' }));
      setError(null);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Could not load the review queue.');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  if (loading && !data) {
    return <div className="card">{Array.from({ length: 5 }, (_, i) => <Skeleton key={i} className="skeleton-line" />)}</div>;
  }
  if (error && !data) return <ErrorState message={error} onRetry={load} />;

  const rows = data?.invoices ?? [];

  return (
    <div className="grid grid-12">
      <div className="span-12" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 12 }}>
        <div className="card" style={{ padding: '10px 14px', display: 'flex', gap: 12, alignItems: 'center', flex: 1 }}>
          <ListChecks size={22} weight="duotone" aria-hidden="true" style={{ color: 'var(--amber)' }} />
          <div>
            <div style={{ fontWeight: 650, fontSize: 15 }}>{rows.length} invoice{rows.length === 1 ? '' : 's'} waiting for review</div>
            <div style={{ fontSize: 11.5, color: 'var(--muted)' }}>Every case below reached a completed deterministic REVIEW — the invoice stays here until a human inspects it. Nothing here auto-approves.</div>
          </div>
        </div>
        <Link to="/invoices" className="btn btn-ghost">All invoices <ArrowRight size={13} weight="bold" aria-hidden="true" /></Link>
      </div>

      <div className="span-12">
        {rows.length === 0 ? (
          <EmptyState
            title="Review queue is empty"
            sub="Every processed invoice reached a terminal business decision. New REVIEW cases will appear here automatically as the pipeline runs."
            action={<button className="btn btn-primary btn-sm" onClick={() => navigate('/upload')}>Upload an invoice</button>}
          />
        ) : (
          <div className="card">
            <div className="table-wrap">
              <table className="table" aria-label="Invoices awaiting review">
                <thead>
                  <tr>
                    <th>Invoice</th>
                    <th>Vendor</th>
                    <th className="col-hide">PO</th>
                    <th className="num">Total</th>
                    <th className="col-hide">Submitted</th>
                    <th>Status</th>
                    <th><span className="sr-only">Investigate</span></th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((inv) => (
                    <tr key={inv.id} className="rowbtn" tabIndex={0} role="button"
                        aria-label={`Investigate invoice ${inv.invoice_number ?? inv.id}`}
                        onClick={() => navigate(`/invoices/${inv.id}`)}
                        onKeyDown={(e) => {
                          if (e.key === 'Enter' || e.key === ' ') {
                            e.preventDefault();
                            navigate(`/invoices/${inv.id}`);
                          }
                        }}>
                      <td>
                        <div style={{ fontWeight: 620 }}>{inv.invoice_number ?? 'Unnumbered'}</div>
                        <div className="mono" style={{ fontSize: 10.5, color: 'var(--faint)' }}>{inv.original_filename}</div>
                      </td>
                      <td style={{ maxWidth: 230 }}>
                        <span style={{ display: 'inline-flex', gap: 6, alignItems: 'center' }}>
                          <Buildings size={13} weight="duotone" aria-hidden="true" style={{ color: 'var(--faint)', flex: 'none' }} />
                          {inv.vendor_name ?? '—'}
                        </span>
                      </td>
                      <td className="col-hide mono">{inv.po_reference ?? '—'}</td>
                      <td className="num">{money(inv.total_amount)}</td>
                      <td className="col-hide" style={{ color: 'var(--muted)', fontSize: 11.5 }}>{dateShort(inv.created_at)}</td>
                      <td><DecisionBadge decision={inv.last_run_decision ?? 'REVIEW'} /></td>
                      <td>
                        <button className="btn btn-ghost btn-sm" onClick={(e) => { e.stopPropagation(); navigate(`/invoices/${inv.id}`); }}>
                          Investigate <ArrowRight size={11} weight="bold" aria-hidden="true" />
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <p style={{ fontSize: 11.5, color: 'var(--muted)', marginTop: 12, lineHeight: 1.6 }}>
              Open any case to inspect the extraction with per-field evidence, the duplicate signals, the
              provisional balance warning, or the specific rule that forced human attention — the decision is
              advisory input for a human, never an automatic action.
            </p>
          </div>
        )}
      </div>
    </div>
  );
}
