import { Link } from 'react-router-dom';
import { ArrowLeft } from '@phosphor-icons/react';

export default function NotFound() {
  return (
    <div className="card" style={{ textAlign: 'center', padding: '48px 20px' }}>
      <div className="mono" style={{ fontSize: 44, fontWeight: 800, color: 'var(--faint)', letterSpacing: '-0.03em' }}>404</div>
      <p style={{ fontWeight: 640, fontSize: 16, margin: '6px 0 4px' }}>Nothing lives at this address</p>
      <p className="empty-sub">The page you were looking for was moved, renamed or never existed.</p>
      <div style={{ marginTop: 16, display: 'flex', gap: 8, justifyContent: 'center' }}>
        <Link to="/" className="btn btn-primary btn-sm"><ArrowLeft size={12} weight="bold" aria-hidden="true" /> Overview</Link>
        <Link to="/invoices" className="btn btn-ghost btn-sm">Invoices</Link>
      </div>
    </div>
  );
}
