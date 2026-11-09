import { Check, Clock, X, Minus, Warning as WarnIcon } from '@phosphor-icons/react';
import type { RunEvent } from '../../types';
import { timeOnly } from '../../utils/formatting';
import { stageIcon } from './stageIcons';

const STATUS_META: Record<string, { label: string; cls: string; IconCmp: typeof Check | typeof X | typeof Clock | typeof Minus | typeof WarnIcon }> = {
  COMPLETED: { label: 'done', cls: 'dot-completed', IconCmp: Check },
  RUNNING: { label: 'running', cls: 'dot-running', IconCmp: Clock },
  FAILED: { label: 'failed', cls: 'dot-failed', IconCmp: X },
  SKIPPED: { label: 'skipped', cls: 'dot-skipped', IconCmp: Minus },
  WARNING: { label: 'warning', cls: 'dot-warning', IconCmp: WarnIcon },
  PENDING: { label: 'waiting', cls: 'dot-skipped', IconCmp: Clock },
};

/** The live execution timeline — renders exactly the persisted events, nothing invented. */
export function Timeline({ events }: { events: RunEvent[] }) {
  if (events.length === 0) {
    return (
      <div className="empty" style={{ padding: '26px 16px' }}>
        <div className="empty-title">Waiting for the worker…</div>
        <p className="empty-sub">Events appear here the moment the processing pipeline claims this run.</p>
      </div>
    );
  }

  return (
    <ol className="timeline" aria-label="Processing stages in chronological order">
      {events.map((event) => {
        const meta = STATUS_META[event.status] ?? STATUS_META.PENDING;
        const StageIcon = stageIcon(event.stage);
        const { IconCmp } = meta;
        return (
          <li key={event.id} className={`timeline-item ${event.status === 'COMPLETED' ? 'done' : ''}`}>
            <span className={`timeline-dot ${meta.cls}`} aria-hidden="true">
              {event.status === 'RUNNING'
                ? <IconCmp size={13} weight="bold" className="pulse-dot" />
                : <IconCmp size={13} weight="bold" />}
            </span>
            <div className="timeline-body">
              <div className="timeline-head">
                <span className="timeline-stage" style={{ display: 'inline-flex', gap: 5, alignItems: 'center' }}>
                  <StageIcon size={12} weight="duotone" aria-hidden="true" />
                  {event.stage.replace(/_/g, ' ')}
                </span>
                <span className="timeline-time">{timeOnly(event.created_at)}</span>
                <span className="badge badge-slate" style={{ fontSize: 9.5 }}>{meta.label}</span>
              </div>
              <p className="timeline-msg" title={event.message ?? undefined}>{event.message ?? '—'}</p>
            </div>
          </li>
        );
      })}
    </ol>
  );
}
