import { NavLink } from 'react-router-dom';
import {
  House,
  FileText,
  ClockCounterClockwise,
  ListChecks,
  UploadSimple,
} from '@phosphor-icons/react';
import type { HealthResponse } from '../../types';

export const NAV_ITEMS = [
  { to: '/', label: 'Overview', icon: House, end: true },
  { to: '/invoices', label: 'Invoices', icon: FileText },
  { to: '/review', label: 'Review Queue', icon: ListChecks },
  { to: '/runs', label: 'History', icon: ClockCounterClockwise },
] as const;

/** Hidden but routable upload destination reached via CTA/button, not nav. */
export const UPLOAD_NAV = { to: '/upload', label: 'Upload invoice', icon: UploadSimple } as const;

interface SidebarProps {
  health: HealthResponse | null;
  healthError: boolean;
}

export function Sidebar({ health, healthError }: SidebarProps) {
  const provider = health?.llm_provider || 'not configured';
  const model = health?.llm_model || '';
  return (
    <aside className="sidebar" aria-label="Application navigation">
      <div className="brand">
        <div className="brand-mark" aria-hidden="true">
          <svg viewBox="0 0 24 24" width="19" height="19" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M7 3h7l5 5v13a1 1 0 0 1-1 1H7a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1z" />
            <path d="M14 3v5h5" />
          </svg>
        </div>
        <div>
          <div className="brand-name">Zamp</div>
          <div className="brand-sub">Invoice Intelligence</div>
        </div>
      </div>

      <div className="nav-section-label">Workspace</div>
      <nav style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
        {NAV_ITEMS.map(({ to, label, icon: Icon, ...rest }) => (
          <NavLink
            key={to}
            to={to}
            end={'end' in rest ? rest.end : false}
            className={({ isActive }) => `nav-link${isActive ? ' active' : ''}`}
          >
            <Icon size={17} weight="duotone" aria-hidden="true" />
            <span className="nav-label">{label}</span>
          </NavLink>
        ))}
      </nav>

      <div className="sidebar-footer">
        <div className="caption">Backend</div>
        <div className={`health-row ${healthError ? 'down' : health ? 'ok' : ''}`}>
          <span className="health-dot" aria-hidden="true" />
          <span>{healthError ? 'Unreachable' : health ? 'Online — DB connected' : 'Checking…'}</span>
        </div>
        {health && (
          <>
            <div className="caption" style={{ marginTop: 4 }}>LLM provider</div>
            <div className="detail" title={model ? `Model: ${model}` : undefined}>
              {provider}
              {model ? ` · ${model}` : ''}
            </div>
          </>
        )}
      </div>
    </aside>
  );
}
