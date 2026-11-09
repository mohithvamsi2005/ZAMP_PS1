import type { Decision } from '../../types';

interface DonutProps {
  decisions: { APPROVE: number; REVIEW: number; REJECT: number };
  failedRuns: number;
}

const SLICES: Array<{ key: Decision; label: string; color: string }> = [
  { key: 'APPROVE', label: 'Approve', color: '#1d8a55' },
  { key: 'REVIEW', label: 'Review', color: '#d98e1f' },
  { key: 'REJECT', label: 'Reject', color: '#c2402f' },
];

/** Donut of APPROVE / REVIEW / REJECT on COMPLETED runs. Failures are shown separately, never mixed in. */
export function DecisionDonut({ decisions, failedRuns }: DonutProps) {
  const counts = SLICES.map((s) => decisions[s.key]);
  const total = counts.reduce((a, b) => a + b, 0);

  if (total === 0 && failedRuns === 0) {
    return (
      <div className="empty" style={{ padding: '26px 16px' }}>
        <div className="empty-title">No decisions yet</div>
        <p className="empty-sub">Upload an invoice and its decision will appear here once processing completes.</p>
      </div>
    );
  }

  const R = 52;
  const C = 2 * Math.PI * R;
  let offset = 0;
  const ariaLabel = SLICES.map((s) => `${s.label}: ${decisions[s.key]}`).join(', ') + `, plus ${failedRuns} failed technical runs`;

  return (
    <div className="donut-wrap">
      <svg
        className="donut"
        width="136" height="136" viewBox="0 0 136 136"
        role="img" aria-labelledby="donut-title donut-desc"
      >
        <title id="donut-title">Decision distribution</title>
        <desc id="donut-desc">{ariaLabel}</desc>
        <circle cx="68" cy="68" r={R} fill="none" stroke="var(--surface-sunken)" strokeWidth="20" />
        {total > 0 && SLICES.map((slice) => {
          const frac = decisions[slice.key] / total;
          if (frac <= 0) return null;
          const dash = frac * C;
          const el = (
            <circle
              key={slice.key}
              cx="68" cy="68" r={R}
              fill="none"
              stroke={slice.color}
              strokeWidth="20"
              strokeLinecap="butt"
              strokeDasharray={`${Math.max(dash - 1.2, 0.2)} ${C - Math.max(dash - 1.2, 0.2)}`}
              strokeDashoffset={-offset}
              transform="rotate(-90 68 68)"
            />
          );
          offset += dash;
          return el;
        })}
        <text x="68" y="64" textAnchor="middle" fontSize="23" fontWeight="700" fill="var(--text)">{total}</text>
        <text x="68" y="83" textAnchor="middle" fontSize="9.5" fill="var(--muted)" letterSpacing="0.06em">DECIDED</text>
      </svg>

      <div className="legend" aria-hidden="true">
        {SLICES.map((slice) => (
          <div className="legend-row" key={slice.key}>
            <span className="legend-swatch" style={{ background: slice.color }} />
            <span>{slice.label}</span>
            <span className="num" style={{ fontFamily: 'var(--mono)', fontSize: 11.5 }}>
              {decisions[slice.key]}
              <span style={{ color: 'var(--faint)' }}>&nbsp;({total ? Math.round((decisions[slice.key] / total) * 100) : 0}%)</span>
            </span>
          </div>
        ))}
        <div className="legend-row" style={{ borderTop: '1px solid var(--border)', paddingTop: 8 }}>
          <span className="legend-swatch" style={{ background: 'var(--slate)' }} />
          <span>Failed (technical)</span>
          <span className="num" style={{ fontFamily: 'var(--mono)', fontSize: 11.5 }}>{failedRuns}</span>
        </div>
      </div>
    </div>
  );
}
