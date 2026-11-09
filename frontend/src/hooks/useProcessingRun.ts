import { useCallback, useEffect, useRef, useState } from 'react';
import { ApiError, getRun, getRunEvents } from '../api';
import type { RunDetail, RunEvent } from '../types';

export interface ProcessingRunState {
  run: RunDetail | null;
  events: RunEvent[];
  loading: boolean;       // first load only
  polling: boolean;       // actively polling between ticks
  degraded: boolean;      // last poll failed — showing stale data + retry banner
  error: string | null;   // fatal (run genuinely missing)
  consecutiveFailures: number;
}

const TERMINAL = new Set(['COMPLETED', 'FAILED']);
const POLL_MS = 1750;
const RETRY_AFTER_FAILURE_MS = 4000;
const MAX_BACKOFF_MS = 8000;

/**
 * Poll a processing run + its events until it reaches COMPLETED or FAILED.
 *
 * Guarantees:
 *  - never polls again once terminal
 *  - stale responses from an earlier poll generation are discarded
 *  - polling is aborted on unmount and on runId change
 *  - consecutive network failures back off exponentially (cap 8s) and set degraded=true
 *    while keeping the last good data on screen
 */
export function useProcessingRun(runId: string): ProcessingRunState & { retryNow: () => void } {
  const [state, setState] = useState<ProcessingRunState>({
    run: null,
    events: [],
    loading: true,
    polling: true,
    degraded: false,
    error: null,
    consecutiveFailures: 0,
  });

  const generationRef = useRef(0);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const backoffRef = useRef(POLL_MS);
  const failuresRef = useRef(0);
  const activeRef = useRef(true);

  const load = useCallback(async (gen: number) => {
    const abort = new AbortController();
    try {
      const [run, events] = await Promise.all([
        getRun(runId, abort.signal),
        getRunEvents(runId, abort.signal),
      ]);
      if (!activeRef.current || gen !== generationRef.current) return;
      const terminal = TERMINAL.has(run.status);
      failuresRef.current = 0;
      setState({
        run,
        events,
        loading: false,
        polling: !terminal,
        degraded: false,
        error: null,
        consecutiveFailures: 0,
      });
      if (!terminal) {
        backoffRef.current = POLL_MS;
        timerRef.current = setTimeout(() => load(gen), POLL_MS);
      } else if (timerRef.current) {
        clearTimeout(timerRef.current);
        timerRef.current = null;
      }
    } catch (err) {
      if (!activeRef.current || gen !== generationRef.current) return;
      const apErr = err instanceof ApiError ? err : null;
      if (apErr?.code === 'ABORTED') return;

      if (apErr?.code === 'NOT_FOUND') {
        setState((s) => ({
          ...s,
          loading: false,
          polling: false,
          degraded: false,
          error: 'This processing run does not exist. It may have been removed.',
        }));
        return;
      }

      failuresRef.current += 1;
      const failures = failuresRef.current;
      setState((s) => ({ ...s, loading: false, degraded: true, consecutiveFailures: failures }));
      backoffRef.current = Math.min(backoffRef.current * 1.8, MAX_BACKOFF_MS);
      timerRef.current = setTimeout(
        () => load(gen),
        Math.max(backoffRef.current, RETRY_AFTER_FAILURE_MS),
      );
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [runId]);

  useEffect(() => {
    activeRef.current = true;
    generationRef.current += 1;
    const gen = generationRef.current;
    backoffRef.current = POLL_MS;
    failuresRef.current = 0;
    setState({
      run: null,
      events: [],
      loading: true,
      polling: true,
      degraded: false,
      error: null,
      consecutiveFailures: 0,
    });
    load(gen);

    return () => {
      activeRef.current = false;
      generationRef.current += 1;
      if (timerRef.current) {
        clearTimeout(timerRef.current);
        timerRef.current = null;
      }
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [runId]);

  const retryNow = useCallback(() => {
    if (timerRef.current) clearTimeout(timerRef.current);
    backoffRef.current = POLL_MS;
    failuresRef.current = 0;
    generationRef.current += 1;
    load(generationRef.current);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [load]);

  return { ...state, retryNow };
}
