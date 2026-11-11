import { Fragment, useCallback, useEffect, useState } from 'react';
import { Outlet, useLocation, useNavigate } from 'react-router-dom';
import {
  ArrowCounterClockwise,
  ArrowsClockwise,
  CheckCircle,
  WarningCircle,
  WifiHigh,
  X,
} from '@phosphor-icons/react';
import { ApiError, resetDemoData } from '../../api';
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
  const navigate = useNavigate();
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [healthError, setHealthError] = useState(false);
  const [confirmReset, setConfirmReset] = useState(false);
  const [resetting, setResetting] = useState(false);
  const [resetError, setResetError] = useState<string | null>(null);
  const [resetNotice, setResetNotice] = useState<string | null>(null);
  const [resetVersion, setResetVersion] = useState(0);

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

  useEffect(() => {
    if (!resetNotice) return;
    const t = setTimeout(() => setResetNotice(null), 5_000);
    return () => clearTimeout(t);
  }, [resetNotice]);

  useEffect(() => {
    setConfirmReset(false);
  }, [location.pathname]);

  const handleConfirmReset = useCallback(async () => {
    setResetting(true);
    setResetError(null);
    try {
      const res = await resetDemoData();
      setConfirmReset(false);
      setResetNotice(
        `Baseline restored — ${res.invoices} sample invoice${res.invoices === 1 ? '' : 's'}, ${res.runs} run${res.runs === 1 ? '' : 's'}.`,
      );
      if (
        location.pathname.startsWith('/invoices/') ||
        location.pathname.startsWith('/processing/')
      ) {
        navigate('/');
      }
      setResetVersion((v) => v + 1);
      refreshHealth();
    } catch (err) {
      setConfirmReset(false);
      setResetError(err instanceof ApiError ? err.message : 'Could not reset workspace data.');
    } finally {
      setResetting(false);
    }
  }, [location.pathname, navigate, refreshHealth]);

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
          <div className="header-actions" style={{ flexWrap: 'wrap', justifyContent: 'flex-end' }}>
            {healthError && (
              <button className="btn btn-ghost btn-sm" onClick={refreshHealth} title="Re-check backend connection">
                <ArrowsClockwise size={14} weight="bold" aria-hidden="true" />
                Retry connection
              </button>
            )}
            {!confirmReset ? (
              <button
                type="button"
                className="btn btn-ghost btn-sm"
                onClick={() => {
                  setResetError(null);
                  setResetNotice(null);
                  setConfirmReset(true);
                }}
                disabled={resetting}
                title="Reset workspace back to initial seeded baseline (3 sample invoices, 0 runs)"
              >
                <ArrowCounterClockwise size={14} weight="bold" aria-hidden="true" />
                Reset data
              </button>
            ) : (
              <div role="group" aria-label="Confirm data reset" style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
                <span style={{ fontSize: 12, color: 'var(--muted)', fontWeight: 550 }}>Reset to baseline?</span>
                <button
                  type="button"
                  className="btn btn-danger btn-sm"
                  onClick={handleConfirmReset}
                  disabled={resetting}
                >
                  {resetting ? 'Resetting…' : 'Confirm reset'}
                </button>
                <button
                  type="button"
                  className="btn btn-ghost btn-sm"
                  onClick={() => setConfirmReset(false)}
                  disabled={resetting}
                >
                  Cancel
                </button>
              </div>
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
          {resetError && (
            <div
              className="error-box"
              role="alert"
              style={{ marginBottom: 14, justifyContent: 'space-between', alignItems: 'center' }}
            >
              <span style={{ display: 'inline-flex', alignItems: 'center', gap: 8 }}>
                <WarningCircle size={15} weight="bold" aria-hidden="true" style={{ flex: 'none' }} />
                {resetError}
              </span>
              <button
                type="button"
                className="btn btn-ghost btn-sm"
                onClick={() => setResetError(null)}
                aria-label="Dismiss reset error"
              >
                <X size={12} weight="bold" aria-hidden="true" />
              </button>
            </div>
          )}
          {resetNotice && (
            <div
              role="status"
              style={{
                marginBottom: 14,
                padding: '10px 14px',
                borderRadius: 'var(--radius-sm)',
                border: '1px solid var(--green-border)',
                background: 'var(--green-tint)',
                color: 'var(--green)',
                fontSize: 12.5,
                fontWeight: 600,
                display: 'flex',
                justifyContent: 'space-between',
                alignItems: 'center',
                gap: 10,
              }}
            >
              <span style={{ display: 'inline-flex', alignItems: 'center', gap: 8 }}>
                <CheckCircle size={15} weight="bold" aria-hidden="true" style={{ flex: 'none' }} />
                {resetNotice}
              </span>
              <button
                type="button"
                className="btn btn-ghost btn-sm"
                onClick={() => setResetNotice(null)}
                aria-label="Dismiss reset notice"
              >
                <X size={12} weight="bold" aria-hidden="true" />
              </button>
            </div>
          )}
          <Fragment key={resetVersion}>
            <Outlet />
          </Fragment>
        </main>
      </div>
    </div>
  );
}
