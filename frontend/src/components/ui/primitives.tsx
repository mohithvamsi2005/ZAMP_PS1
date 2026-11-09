import type { ReactNode } from 'react';
import { toneClass } from '../../utils/status';
import type { StatusTone } from '../../types';

interface BadgeProps {
  tone: StatusTone;
  children: ReactNode;
  dot?: boolean;
  title?: string;
}

export function Badge({ tone, children, dot = true, title }: BadgeProps) {
  return (
    <span className={`badge ${toneClass(tone)}`} title={title}>
      {dot && <span className="badge-dot" aria-hidden="true" />}
      {children}
    </span>
  );
}

export function Skeleton({ className = '', style }: { className?: string; style?: React.CSSProperties }) {
  return <div className={`skeleton ${className}`} style={style} aria-hidden="true" />;
}

export function EmptyState({ title, sub, action }: { title: string; sub?: string; action?: ReactNode }) {
  return (
    <div className="empty" role="status">
      <div className="empty-title">{title}</div>
      {sub && <p className="empty-sub">{sub}</p>}
      {action && <div style={{ marginTop: 14 }}>{action}</div>}
    </div>
  );
}

export function ErrorState({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <div className="error-box" role="alert">
      <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" style={{ flex: 'none', marginTop: 1 }}>
        <path d="M12 9v4m0 4h.01M10.3 3.86 1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.7 3.86a2 2 0 0 0-3.4 0Z" />
      </svg>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
        <span>{message}</span>
        {onRetry && (
          <button className="btn btn-ghost btn-sm" style={{ alignSelf: 'flex-start' }} onClick={onRetry}>
            Try again
          </button>
        )}
      </div>
    </div>
  );
}

export function Inline({ children }: { children: ReactNode }) {
  return <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>{children}</div>;
}

export function SmallSpinner() {
  return (
    <svg className="spinner" viewBox="0 0 24 24" width="16" height="16" aria-hidden="true">
      <circle cx="12" cy="12" r="9" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeDasharray="42" strokeDashoffset="16" />
      <style>{`.spinner{animation:rot 0.9s linear infinite}@keyframes rot{to{transform:rotate(360deg)}}`}</style>
    </svg>
  );
}
