import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ResponsiveContainer,
} from 'recharts';
import type { AppState } from '../types';

interface Props {
  state: AppState;
}

// Compute avg and p95 for an array of values
function stats(values: number[]): { avg: number; p95: number } {
  if (values.length === 0) return { avg: 0, p95: 0 };
  const sorted = [...values].sort((a, b) => a - b);
  const avg = sorted.reduce((s, v) => s + v, 0) / sorted.length;
  const p95Index = Math.max(0, Math.ceil(sorted.length * 0.95) - 1);
  return { avg: Math.round(avg * 10) / 10, p95: Math.round(sorted[p95Index] * 10) / 10 };
}

const LANE_COLORS: Record<string, string> = {
  signature: '#6366f1',
  example: '#22c55e',
  behavioral: '#f59e0b',
  none: '#94a3b8',
};

const LANE_COLOR_DEFAULT = '#64748b';

export function MetricsPanel({ state }: Props) {
  const { metrics, metricNames } = state;

  // ---- Per-lane duration stats ----
  const laneMetrics: Array<{ lane: string; avg: number; p95: number }> = [];
  metricNames
    .filter(n => n.startsWith('verify.') && n.endsWith('.duration_ms'))
    .forEach(n => {
      const lane = n.replace('verify.', '').replace('.duration_ms', '');
      const { avg, p95 } = stats(metrics[n] ?? []);
      laneMetrics.push({ lane, avg, p95 });
    });

  // ---- Cost over time (per-generate_cost event) ----
  const costValues = metrics['generate.cost_usd'] ?? [];
  const totalCost = costValues.reduce((s, v) => s + v, 0);
  const costData = costValues.map((v, i) => ({
    label: `Symbol ${i + 1}`,
    cost_usd: Math.round(v * 1_000_000) / 1_000_000,
  }));

  const hasDuration = laneMetrics.length > 0;
  const hasCost = costData.length > 0;

  return (
    <div className="panel metrics-panel">
      <h2 className="panel-title">Metrics</h2>

      {!hasDuration && !hasCost ? (
        <p className="empty-msg">Metrics will appear as the run progresses.</p>
      ) : (
        <div className="metrics-content">
          {hasDuration && (
            <div className="metric-section">
              <h3 className="section-subtitle">Lane duration (ms) — avg & p95</h3>
              <ResponsiveContainer width="100%" height={220}>
                <BarChart data={laneMetrics} margin={{ top: 4, right: 16, left: 0, bottom: 4 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
                  <XAxis dataKey="lane" tick={{ fill: '#94a3b8', fontSize: 12 }} />
                  <YAxis tick={{ fill: '#94a3b8', fontSize: 12 }} />
                  <Tooltip
                    contentStyle={{ background: '#1e293b', border: '1px solid #334155', borderRadius: 6 }}
                    labelStyle={{ color: '#f1f5f9' }}
                    itemStyle={{ color: '#94a3b8' }}
                  />
                  <Legend wrapperStyle={{ color: '#94a3b8', fontSize: 12 }} />
                  <Bar dataKey="avg" name="Avg (ms)" fill="#6366f1" radius={[3, 3, 0, 0]} />
                  <Bar dataKey="p95" name="p95 (ms)" fill="#22c55e" radius={[3, 3, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
              <div className="lane-swatches">
                {laneMetrics.map(l => (
                  <span key={l.lane} className="lane-swatch">
                    <span
                      className="swatch-dot"
                      style={{ background: LANE_COLORS[l.lane] ?? LANE_COLOR_DEFAULT }}
                    />
                    {l.lane}: avg {l.avg}ms · p95 {l.p95}ms
                  </span>
                ))}
              </div>
            </div>
          )}

          {hasCost && (
            <div className="metric-section">
              <h3 className="section-subtitle">
                Generation cost (USD) — total: ${totalCost.toFixed(6)}
              </h3>
              <ResponsiveContainer width="100%" height={160}>
                <BarChart data={costData} margin={{ top: 4, right: 16, left: 0, bottom: 4 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
                  <XAxis dataKey="label" tick={{ fill: '#94a3b8', fontSize: 12 }} />
                  <YAxis tick={{ fill: '#94a3b8', fontSize: 12 }} tickFormatter={v => `$${v}`} />
                  <Tooltip
                    contentStyle={{ background: '#1e293b', border: '1px solid #334155', borderRadius: 6 }}
                    labelStyle={{ color: '#f1f5f9' }}
                    itemStyle={{ color: '#94a3b8' }}
                    formatter={(v: number) => [`$${v.toFixed(6)}`, 'cost']}
                  />
                  <Bar dataKey="cost_usd" name="Cost (USD)" fill="#f59e0b" radius={[3, 3, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
