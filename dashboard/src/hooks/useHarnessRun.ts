// Orchestrates either the mock replay or a real backend SSE connection.
// Real backend seam: VITE_API_URL env var → POST /run + EventSource /run/{id}/stream

import { useReducer, useCallback, useRef } from 'react';
import type { AppState, HarnessEvent } from '../types';
import { applyEvent, initialState } from './useHarnessState';
import { MOCK_EVENTS, replayMockStream } from '../data/mockEvents';

function reducer(state: AppState, event: HarnessEvent): AppState {
  return applyEvent(state, event);
}

const API_URL = import.meta.env.VITE_API_URL as string | undefined;

export interface RunConfig {
  module: string;
  model: string;
}

export function useHarnessRun() {
  const [state, dispatch] = useReducer(reducer, undefined, initialState);
  const cancelRef = useRef<(() => void) | null>(null);

  const startRun = useCallback(
    (config: RunConfig) => {
      // Cancel any in-flight run
      cancelRef.current?.();
      cancelRef.current = null;

      if (API_URL) {
        // ---- Live backend path ----
        // POST /run, then EventSource /run/{id}/stream
        (async () => {
          try {
            const res = await fetch(`${API_URL}/run`, {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({
                module_path: config.module,
                model: config.model,
              }),
            });
            if (!res.ok) {
              console.error('POST /run failed', res.status);
              return;
            }
            const { run_id } = (await res.json()) as { run_id: string };
            const es = new EventSource(`${API_URL}/run/${run_id}/stream`);

            const eventNames = [
              'run_started', 'symbol_started', 'generated', 'gate_result',
              'verify_result', 'claim_locked', 'claim_retry', 'claim_escalated',
              'alarm', 'symbol_done', 'metric_update', 'run_done',
            ];

            eventNames.forEach(name => {
              es.addEventListener(name, (e: MessageEvent) => {
                try {
                  const event = JSON.parse(e.data) as HarnessEvent;
                  dispatch(event);
                } catch {
                  console.error('Failed to parse SSE event', e.data);
                }
              });
            });

            es.onerror = (err) => {
              console.error('SSE error', err);
              es.close();
            };

            cancelRef.current = () => es.close();
          } catch (err) {
            console.error('Failed to start run', err);
          }
        })();
      } else {
        // ---- Mock replay path (no live backend) ----
        // Inject a custom run_started first, then replay the rest of the mock stream
        dispatch({
          type: 'run_started',
          run_id: `mock-${Date.now()}`,
          module: config.module || 'examples/math_utils.py',
          model: config.model || 'stub',
        });

        // Skip the run_started already in MOCK_EVENTS; dispatch the rest
        const rest = MOCK_EVENTS.slice(1);
        let index = 0;
        let cancelled = false;

        function step() {
          if (cancelled || index >= rest.length) return;
          dispatch(rest[index]);
          index++;
          setTimeout(step, 180);
        }
        step();

        cancelRef.current = () => { cancelled = true; };
      }
    },
    [],
  );

  // runMockDemo replays the full canonical MOCK_EVENTS stream as-is
  const runMockDemo = useCallback(() => {
    cancelRef.current?.();
    const cancel = replayMockStream(dispatch, undefined, 180);
    cancelRef.current = cancel;
  }, []);

  return { state, startRun, runMockDemo };
}
