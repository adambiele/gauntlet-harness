import type { AppState } from '../types';
import { SymbolCard } from './SymbolCard';

interface Props {
  state: AppState;
}

export function LiveLoopView({ state }: Props) {
  if (!state.isRunning && !state.isDone && state.symbolOrder.length === 0) {
    return (
      <div className="panel empty-panel">
        <p className="empty-msg">Start a run or click "Demo" to see the live loop.</p>
      </div>
    );
  }

  return (
    <div className="panel live-loop-panel">
      <h2 className="panel-title">
        Live Loop
        {state.runId && (
          <span className="run-id-badge">{state.runId}</span>
        )}
        {state.isRunning && <span className="running-dot" />}
        {state.isDone && (
          <span className="done-badge">
            ✓ {state.verifiedCount} verified · ↑ {state.escalatedCount} escalated
          </span>
        )}
      </h2>

      <div className="symbol-grid">
        {state.symbolOrder.map(name => (
          <SymbolCard key={name} sym={state.symbols[name]} />
        ))}
      </div>
    </div>
  );
}
