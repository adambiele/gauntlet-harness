import { useHarnessRun } from './hooks/useHarnessRun';
import { InputPanel } from './components/InputPanel';
import { LiveLoopView } from './components/LiveLoopView';
import { DocPanel } from './components/DocPanel';
import { TriagePanel } from './components/TriagePanel';
import { MetricsPanel } from './components/MetricsPanel';

export default function App() {
  const { state, startRun, runMockDemo } = useHarnessRun();

  return (
    <div className="app">
      <header className="app-header">
        <div className="header-left">
          <span className="logo">⬡</span>
          <div>
            <h1 className="app-title">Verified Documentation Harness</h1>
            <p className="app-subtitle">No unverified claim ships — by construction.</p>
          </div>
        </div>
        {state.runId && (
          <div className="header-right">
            <span className="header-run-info">
              {state.module} · {state.model}
            </span>
          </div>
        )}
      </header>

      <main className="app-main">
        {/* Top row: input + metrics */}
        <div className="row row-top">
          <InputPanel
            onRun={(module, model) => startRun({ module, model })}
            onDemo={runMockDemo}
            isRunning={state.isRunning}
          />
          <MetricsPanel state={state} />
        </div>

        {/* Middle row: live loop (full width) */}
        <div className="row row-mid">
          <LiveLoopView state={state} />
        </div>

        {/* Bottom row: doc + triage */}
        <div className="row row-bottom">
          <DocPanel state={state} />
          <TriagePanel state={state} />
        </div>
      </main>

      <footer className="app-footer">
        Gauntlet Harness — Hackathon Build — SSE contract frozen at{' '}
        <code>src/harness/adapters/events.py</code>
      </footer>
    </div>
  );
}
