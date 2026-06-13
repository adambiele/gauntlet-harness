import type { AppState } from '../types';

interface Props {
  state: AppState;
}

export function TriagePanel({ state }: Props) {
  const hasEscalations = state.escalations.length > 0;

  return (
    <div className="panel triage-panel">
      <h2 className="panel-title">
        Triage
        {hasEscalations && (
          <span className="triage-count-badge">{state.escalations.length}</span>
        )}
      </h2>

      {state.alarms.length > 0 && (
        <div className="alarms-section">
          <h3 className="section-subtitle">Alarms</h3>
          {state.alarms.map((a, i) => (
            <div key={i} className={`triage-alarm severity-${a.severity}`}>
              <div className="triage-alarm-header">
                <span className="alarm-type-pill">{a.alarm_type}</span>
                <span className="alarm-severity-pill">{a.severity}</span>
                <span className="alarm-symbol">@ {a.symbol}</span>
              </div>
              <p className="alarm-message">{a.message}</p>
              <p className="alarm-action">
                <strong>Action:</strong> {a.recommended_action}
              </p>
              <p className="alarm-timestamp">{a.timestamp}</p>
            </div>
          ))}
        </div>
      )}

      {hasEscalations ? (
        <div className="escalations-section">
          <h3 className="section-subtitle">Escalated Claims (needs human review)</h3>
          {state.escalations.map((e, i) => (
            <div key={i} className="triage-escalation">
              <span className="escalation-symbol">@ {e.symbol}</span>
              <p className="escalation-reason">{e.reason}</p>
            </div>
          ))}
        </div>
      ) : (
        !state.alarms.length && (
          <p className="empty-msg">No alarms or escalations yet.</p>
        )
      )}
    </div>
  );
}
