import { Link, useNavigate } from 'react-router-dom';
import { ArrowRight } from '@phosphor-icons/react';
import { DecisionBadge, RunStatusBadge } from '../ui/StatusPill';
import { dateTime, duration } from '../../utils/formatting';
import type { RecentRun } from '../../types';

interface RecentRunsTableProps {
  runs: RecentRun[];
}

export function RecentRunsTable({ runs }: RecentRunsTableProps) {
  const navigate = useNavigate();
  if (runs.length === 0) {
    return (
      <div className="empty" style={{ borderStyle: 'solid' }}>
        <div className="empty-title">No processing runs yet</div>
        <p className="empty-sub">Upload your first invoice and watch the pipeline process it here, run by run.</p>
      </div>
    );
  }
  return (
    <div className="table-wrap">
      <table className="table">
        <thead>
          <tr>
            <th>Invoice</th>
            <th className="col-hide">Vendor</th>
            <th className="col-hide">Submitted</th>
            <th>Status</th>
            <th>Decision</th>
            <th className="col-hide num">Duration</th>
            <th className="col-hide"><span className="sr-only">Open</span></th>
          </tr>
        </thead>
        <tbody>
          {runs.map((r) => (
            <tr
              key={r.run_id}
              className="rowbtn"
              tabIndex={0}
              role="button"
              aria-label={`Open invoice ${r.invoice_number ?? 'unnumbered'}`}
              onClick={() => r.invoice_id && navigate(`/invoices/${r.invoice_id}`)}
              onKeyDown={(e) => {
                if ((e.key === 'Enter' || e.key === ' ') && r.invoice_id) {
                  e.preventDefault();
                  navigate(`/invoices/${r.invoice_id}`);
                }
              }}
            >
              <td>
                <div style={{ fontWeight: 620 }}>{r.invoice_number ?? 'Unnumbered'}</div>
                <div className="mono col-hide" style={{ color: 'var(--faint)', fontSize: 10.5 }}>{r.run_id.slice(0, 8)}</div>
              </td>
              <td className="col-hide" style={{ maxWidth: 220 }}>{r.vendor_name ?? '—'}</td>
              <td className="col-hide" style={{ color: 'var(--muted)' }}>{dateTime(r.created_at)}</td>
              <td><RunStatusBadge status={r.status ?? null} /></td>
              <td><DecisionBadge decision={r.decision ?? null} /></td>
              <td className="col-hide num" style={{ color: 'var(--muted)' }}>{duration(r.duration_seconds)}</td>
              <td className="col-hide">
                <Link className="card-title-link" to={r.invoice_id ? `/invoices/${r.invoice_id}` : '#'} onClick={(e) => e.stopPropagation()}>
                  Open <ArrowRight size={11} weight="bold" aria-hidden="true" />
                </Link>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
