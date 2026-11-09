interface ActivityBarsProps {
  points: Array<{ date: string; submitted: number }>;
}

/** Daily submissions, last 14 days. Bars are real counts; labels are sparse and every bar has a title. */
export function ActivityBars({ points }: ActivityBarsProps) {
  const max = Math.max(...points.map((p) => p.submitted), 1);
  const total = points.reduce((a, p) => a + p.submitted, 0);

  if (total === 0) {
    return <p className="empty-sub" style={{ textAlign: 'left' }}>No invoices submitted in the last 14 days.</p>;
  }

  return (
    <div>
      <div
        className="activity-bars"
        role="img"
        aria-label={`Invoices submitted per day across the last 14 days. Total ${total}. Peak ${max} in a single day.`}
      >
        {points.map((p) => {
          const h = Math.max((p.submitted / max) * 100, p.submitted > 0 ? 7 : 0);
          const d = new Date(`${p.date}T00:00:00Z`);
          const label = d.toLocaleDateString('en-IN', { day: '2-digit', month: 'short', timeZone: 'UTC' });
          return (
            <div
              key={p.date}
              className="activity-bar"
              style={{ height: `${h}%`, minHeight: 4 }}
              title={`${label} — ${p.submitted} invoice${p.submitted === 1 ? '' : 's'}`}
            />
          );
        })}
      </div>
      <div className="activity-scale" aria-hidden="true">
        <span>{new Date(`${points[0]?.date}T00:00:00Z`).toLocaleDateString('en-IN', { day: '2-digit', month: 'short', timeZone: 'UTC' })}</span>
        <span>{new Date(`${points[points.length - 1]?.date}T00:00:00Z`).toLocaleDateString('en-IN', { day: '2-digit', month: 'short', timeZone: 'UTC' })}</span>
      </div>
    </div>
  );
}
