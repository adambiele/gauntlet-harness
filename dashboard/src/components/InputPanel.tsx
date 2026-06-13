import { useEffect, useState } from 'react';

interface Props {
  onRun: (module: string, model: string) => void;
  onDemo: () => void;
  isRunning: boolean;
}

const API_URL = import.meta.env.VITE_API_URL as string | undefined;

interface Example {
  name: string;
  path: string;
  title: string;
}

// Used offline (no VITE_API_URL) or if GET /examples fails — keeps the picker populated.
// Mirrors what ships in the repo's examples/ folder.
const FALLBACK_EXAMPLES: Example[] = [
  { name: 'planted_bug.py', path: 'examples/planted_bug.py', title: 'The planted-bug demo — a sort that secretly reverses.' },
  { name: 'math_utils.py', path: 'examples/math_utils.py', title: 'Integer and numeric utilities (planted is_prime bug).' },
  { name: 'string_utils.py', path: 'examples/string_utils.py', title: 'String and text helpers (planted truncate bug).' },
  { name: 'geometry.py', path: 'examples/geometry.py', title: '2D geometry helpers — an all-honest green run.' },
];

// Cloud models run on the deployed backend. The local Qwen transport is shown (to
// demonstrate the swap spans self-hosted models too) but disabled on the hosted demo —
// Render can't reach a LAN model. It still works for local CLI runs (--worker qwen).
const MODELS = [
  { value: 'sonnet', label: 'Claude Sonnet 4.6 (cloud)', disabled: false },
  { value: 'haiku', label: 'Claude Haiku 4.5 (cloud, faster)', disabled: false },
  { value: 'openai', label: 'OpenAI GPT-4o (cloud)', disabled: false },
  { value: 'qwen', label: 'Qwen3-Coder — local only', disabled: true },
] as const;

export function InputPanel({ onRun, onDemo, isRunning }: Props) {
  const [examples, setExamples] = useState<Example[]>(FALLBACK_EXAMPLES);
  const [module, setModule] = useState('examples/planted_bug.py');
  const [model, setModel] = useState<string>('haiku');

  // Fetch the live example list from the backend so the picker reflects whatever is
  // actually bundled on the server. Falls back to the static list on any failure.
  useEffect(() => {
    if (!API_URL) return;
    let cancelled = false;
    (async () => {
      try {
        const res = await fetch(`${API_URL}/examples`);
        if (!res.ok) return;
        const data = (await res.json()) as Example[];
        if (!cancelled && data.length > 0) setExamples(data);
      } catch {
        // keep FALLBACK_EXAMPLES
      }
    })();
    return () => { cancelled = true; };
  }, []);

  // Whether the current module value matches a known example (drives the select).
  const selectedExample = examples.some(e => e.path === module) ? module : '__custom__';

  return (
    <div className="panel input-panel">
      <h2 className="panel-title">Run Harness</h2>

      <div className="field-group">
        <label htmlFor="example-select">Example module</label>
        <select
          id="example-select"
          value={selectedExample}
          onChange={e => {
            if (e.target.value !== '__custom__') setModule(e.target.value);
          }}
          disabled={isRunning}
        >
          {examples.map(ex => (
            <option key={ex.path} value={ex.path} title={ex.title}>
              {ex.name}{ex.title ? ` — ${ex.title}` : ''}
            </option>
          ))}
          <option value="__custom__">Custom path / pasted source…</option>
        </select>
      </div>

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
            <option
              key={m.value}
              value={m.value}
              disabled={m.disabled}
              title={
                m.disabled
                  ? 'Local model — only available when self-hosting the backend on your LAN'
                  : undefined
              }
            >
              {m.label}
            </option>
          ))}
        </select>
        <small
          style={{ display: 'block', marginTop: 4, opacity: 0.6, fontSize: '0.75rem' }}
        >
          Qwen runs locally only — self-host the backend on your LAN to use it.
        </small>
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
