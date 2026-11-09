import { useCallback, useEffect, useState } from 'react';
import { Outlet, useLocation } from 'react-router-dom';
import { ArrowsClockwise, WifiHigh } from '@phosphor-icons/react';
import { fetchHealth } from '../../api/health';
import { Sidebar } from './Sidebar';
import type { HealthResponse } from '../../types';

const PAGE_META: Record<string, { title: string; sub: string }> = {
  '/': { title: 'Overview', sub: 'Pipeline health, processing outcomes and backlogs' },
  '/invoices': { title: 'Invoices', sub: 'Every submission, searchable with live outcomes' },
  '/runs': { title: 'Processing history', sub: 'Run-level audit trail for every processed invoice' },
  '/upload': { title: 'Upload invoice', sub: 'Queue a PDF for the processing workflow' },
  '/review': { title: 'Review queue', sub: 'Invoices waiting for a human decision' },
};

export function AppShell() {
  const location = useLocation();
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [healthError, setHealthError] = useState(false);

  const refreshHealth = useCallback(async () => {
    try {
      setHealth(await fetchHealth());
      setHealthError(false);
    } catch {
      setHealthError(true);
    }
  }, []);

  useEffect(() => {
    refreshHealth();
    const t = setInterval(refreshHealth, 15_000);
    return () => clearInterval(t);
  }, [refreshHealth]);

  const meta = PAGE_META[location.pathname]
    ?? (location.pathname.startsWith('/invoices') || location.pathname.startsWith('/processing')
        ? { title: location.pathname.startsWith('/processing') ? 'Processing run' : 'Invoice detail', sub: 'Live data from the processing pipeline' }
        : { title: 'Zamp Invoice Intelligence', sub: '' });

  return (
    <div className="shell">
      <Sidebar health={health} healthError={healthError} />
      <div className="page">
        <header className="header">
          <div>
            <h1>{meta.title}</h1>
            {meta.sub && <div className="page-sub">{meta.sub}</div>}
          </div>
          <div className="header-actions">
            {healthError && (
              <button className="btn btn-ghost btn-sm" onClick={refreshHealth} title="Re-check backend connection">
                <ArrowsClockwise size={14} weight="bold" aria-hidden="true" />
                Retry connection
              </button>
            )}
            <span
              className={`badge ${healthError ? 'badge-red' : 'badge-green'}`}
              title={healthError ? 'Backend unreachable' : 'Backend reachable and database connected'}
            >
              <WifiHigh size={13} weight="bold" aria-hidden="true" />
              {healthError ? 'Offline' : 'Live'}
            </span>
          </div>
        </header>
        <main className="content">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
