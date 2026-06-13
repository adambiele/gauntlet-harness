// Processes HarnessEvents into AppState — the central state machine.
// Used by both the mock replay and the live SSE connection.

import type {
  AppState,
  HarnessEvent,
  SymbolState,
} from '../types';

export function initialState(): AppState {
  return {
    runId: null,
    module: '',
    model: '',
    symbols: {},
    symbolOrder: [],
    alarms: [],
    escalations: [],
    metrics: {},
    metricNames: [],
    verifiedCount: 0,
    escalatedCount: 0,
    isDone: false,
    isRunning: false,
  };
}

function ensureSymbol(state: AppState, name: string): AppState {
  if (state.symbols[name]) return state;
  const sym: SymbolState = {
    name,
    stage: 'pending',
    claimCount: 0,
    violations: [],
    verifyResults: [],
    lockedClaims: [],
    retries: [],
    escalations: [],
    alarms: [],
    done: false,
  };
  return {
    ...state,
    symbols: { ...state.symbols, [name]: sym },
    symbolOrder: [...state.symbolOrder, name],
  };
}

function updateSymbol(
  state: AppState,
  name: string,
  updater: (s: SymbolState) => SymbolState,
): AppState {
  const sym = state.symbols[name];
  if (!sym) return state;
  return {
    ...state,
    symbols: { ...state.symbols, [name]: updater(sym) },
  };
}

export function applyEvent(state: AppState, event: HarnessEvent): AppState {
  switch (event.type) {
    case 'run_started':
      return {
        ...initialState(),
        runId: event.run_id,
        module: event.module,
        model: event.model,
        isRunning: true,
      };

    case 'symbol_started': {
      let s = ensureSymbol(state, event.symbol);
      return updateSymbol(s, event.symbol, sym => ({ ...sym, stage: 'generating' }));
    }

    case 'generated': {
      let s = ensureSymbol(state, event.symbol);
      return updateSymbol(s, event.symbol, sym => ({
        ...sym,
        stage: 'gating',
        claimCount: event.claim_count,
      }));
    }

    case 'gate_result': {
      let s = ensureSymbol(state, event.symbol);
      return updateSymbol(s, event.symbol, sym => ({
        ...sym,
        stage: 'verifying',
        violations: event.violations,
      }));
    }

    case 'verify_result': {
      let s = ensureSymbol(state, event.symbol);
      return updateSymbol(s, event.symbol, sym => ({
        ...sym,
        stage: 'deciding',
        verifyResults: [...sym.verifyResults, event],
      }));
    }

    case 'claim_locked': {
      let s = ensureSymbol(state, event.symbol);
      return updateSymbol(s, event.symbol, sym => {
        // Associate verify results for this claim type
        const verifications = sym.verifyResults.filter(
          v => v.claim_type === event.claim_type,
        );
        return {
          ...sym,
          lockedClaims: [
            ...sym.lockedClaims,
            { claim_type: event.claim_type, prose: event.prose, verifications },
          ],
        };
      });
    }

    case 'claim_retry': {
      let s = ensureSymbol(state, event.symbol);
      return updateSymbol(s, event.symbol, sym => ({
        ...sym,
        retries: [...sym.retries, event],
      }));
    }

    case 'claim_escalated': {
      let s = ensureSymbol(state, event.symbol);
      s = updateSymbol(s, event.symbol, sym => ({
        ...sym,
        escalations: [...sym.escalations, event],
      }));
      return {
        ...s,
        escalations: [...s.escalations, event],
      };
    }

    case 'alarm': {
      let s = ensureSymbol(state, event.symbol);
      s = updateSymbol(s, event.symbol, sym => ({
        ...sym,
        alarms: [...sym.alarms, event],
      }));
      return {
        ...s,
        alarms: [...s.alarms, event],
      };
    }

    case 'symbol_done': {
      let s = ensureSymbol(state, event.symbol);
      return updateSymbol(s, event.symbol, sym => ({
        ...sym,
        stage: 'done',
        done: true,
      }));
    }

    case 'metric_update': {
      const existing = state.metrics[event.name] ?? [];
      const isNew = existing.length === 0;
      return {
        ...state,
        metrics: { ...state.metrics, [event.name]: [...existing, event.value] },
        metricNames: isNew
          ? [...state.metricNames, event.name]
          : state.metricNames,
      };
    }

    case 'run_done':
      return {
        ...state,
        verifiedCount: event.verified_count,
        escalatedCount: event.escalated_count,
        isDone: true,
        isRunning: false,
      };

    default:
      return state;
  }
}
