import React from 'react'; // needed for React.Fragment
import type { SymbolState } from '../types';

const STAGE_LABELS: Record<string, string> = {
  pending: 'Pending',
  generating: 'Generating…',
  gating: 'Gate check…',
  verifying: 'Verifying…',
  deciding: 'Deciding…',
  done: 'Done',
};

const STAGE_CLASSES: Record<string, string> = {
  pending: 'stage-pending',
  generating: 'stage-active',
  gating: 'stage-active',
  verifying: 'stage-active',
  deciding: 'stage-active',
  done: 'stage-done',
};

const VERDICT_ICON: Record<string, string> = {
  pass: '✓',
  fail: '✗',
  inconclusive: '?',
};

const VERDICT_CLASS: Record<string, string> = {
  pass: 'verdict-pass',
  fail: 'verdict-fail',
  inconclusive: 'verdict-inconclusive',
};

function PipelineSteps({ stage }: { stage: string }) {
  const steps = ['generating', 'gating', 'verifying', 'deciding'];
  const order = ['generating', 'gating', 'verifying', 'deciding', 'done'];
  const currentIndex = order.indexOf(stage);

  return (
    <div className="pipeline-steps">
      {steps.map((step, i) => {
        const stepIndex = order.indexOf(step);
        const isActive = stage === step;
        const isDone = currentIndex > stepIndex || stage === 'done';
        return (
          <React.Fragment key={step}>
            <span
              className={`step ${isActive ? 'step-active' : isDone ? 'step-done' : 'step-waiting'}`}
            >
              {step.replace('generating', 'Generate')
                .replace('gating', 'Gate')
                .replace('verifying', 'Verify')
                .replace('deciding', 'Decide')}
            </span>
            {i < steps.length - 1 && <span className="step-arrow">→</span>}
          </React.Fragment>
        );
      })}
    </div>
  );
}

interface Props {
  sym: SymbolState;
}

export function SymbolCard({ sym }: Props) {
  const hasAlarms = sym.alarms.length > 0;
  const hasEscalations = sym.escalations.length > 0;

  return (
    <div className={`symbol-card ${STAGE_CLASSES[sym.stage]} ${sym.done ? 'card-done' : ''}`}>
      <div className="card-header">
        <span className="symbol-name">{sym.name}</span>
        <span className={`stage-badge ${STAGE_CLASSES[sym.stage]}`}>
          {STAGE_LABELS[sym.stage]}
        </span>
      </div>

      <PipelineSteps stage={sym.stage} />

      {sym.claimCount > 0 && (
        <div className="card-meta">
          {sym.claimCount} claims generated
          {sym.violations.length > 0 && (
            <span className="violations-badge">
              {' '}{sym.violations.length} gate violation{sym.violations.length > 1 ? 's' : ''}
            </span>
          )}
        </div>
      )}

      {/* Verify results */}
      {sym.verifyResults.length > 0 && (
        <div className="verify-results">
          {sym.verifyResults.map((v, i) => (
            <div key={i} className={`verify-row ${VERDICT_CLASS[v.verdict]}`}>
              <span className="verdict-icon">{VERDICT_ICON[v.verdict] ?? '?'}</span>
              <span className="verify-lane">{v.lane}</span>
              <span className="verify-evidence">{v.evidence}</span>
            </div>
          ))}
        </div>
      )}

      {/* Retry badges */}
      {sym.retries.length > 0 && (
        <div className="retry-list">
          {sym.retries.map((r, i) => (
            <div key={i} className="retry-badge">
              ↻ Retry {r.attempt}/3 — {r.reason}
            </div>
          ))}
        </div>
      )}

      {/* Locked claims */}
      {sym.lockedClaims.length > 0 && (
        <div className="locked-claims">
          <span className="locked-label">Locked claims:</span>
          {sym.lockedClaims.map((c, i) => (
            <div key={i} className="locked-claim">
              <span className="lock-icon">✓</span>
              <span className="claim-type-badge">{c.claim_type}</span>
              <span className="claim-prose">{c.prose}</span>
            </div>
          ))}
        </div>
      )}

      {/* Alarms */}
      {hasAlarms && (
        <div className="alarm-list">
          {sym.alarms.map((a, i) => (
            <div key={i} className={`alarm-row severity-${a.severity}`}>
              <span className="alarm-icon">⚠</span>
              <span className="alarm-type">{a.alarm_type}</span>
              <span className="alarm-msg">{a.message}</span>
            </div>
          ))}
        </div>
      )}

      {/* Escalations */}
      {hasEscalations && (
        <div className="escalation-list">
          {sym.escalations.map((e, i) => (
            <div key={i} className="escalation-row">
              <span className="escalation-icon">↑</span>
              <span className="escalation-reason">{e.reason}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
