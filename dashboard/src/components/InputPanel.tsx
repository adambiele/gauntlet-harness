import { useState } from 'react';

interface Props {
  onRun: (module: string, model: string) => void;
  onDemo: () => void;
  isRunning: boolean;
}

// Cloud models only — these run on the deployed backend. (StubWorker and the local
// Qwen transport still exist for tests + local CLI runs, but the LAN model is
// unreachable from Render, so it's not offered in the hosted picker.)
const MODELS = [
  { value: 'opus', label: 'Claude Opus 4.8 (cloud)' },
  { value: 'haiku', label: 'Claude Haiku 4.5 (cloud, faster)' },
  { value: 'openai', label: 'OpenAI GPT-4o (cloud)' },
] as const;

export function InputPanel({ onRun, onDemo, isRunning }: Props) {
  const [module, setModule] = useState('examples/planted_bug.py');
  const [model, setModel] = useState<string>('haiku');

  return (
    <div className="panel input-panel">
      <h2 className="panel-title">Run Harness</h2>

      <div className="field-group">
        <label htmlFor="module-input">Module path or paste source</label>
        <input
          id="module-input"
          type="text"
          value={module}
          onChange={e => setModule(e.target.value)}
          placeholder="examples/planted_bug.py"
          disabled={isRunning}
        />
      </div>

      <div className="field-group">
        <label htmlFor="model-select">Model</label>
        <select
          id="model-select"
          value={model}
          onChange={e => setModel(e.target.value)}
          disabled={isRunning}
        >
          {MODELS.map(m => (
            <option key={m.value} value={m.value}>
              {m.label}
            </option>
          ))}
        </select>
      </div>

      <div className="btn-row">
        <button
          className="btn btn-primary"
          onClick={() => onRun(module, model)}
          disabled={isRunning || !module.trim()}
        >
          {isRunning ? 'Running…' : 'Run'}
        </button>
        <button
          className="btn btn-secondary"
          onClick={onDemo}
          disabled={isRunning}
        >
          Demo (offline replay)
        </button>
      </div>
    </div>
  );
}
