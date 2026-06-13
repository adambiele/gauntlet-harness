// Rendered doc panel — shows verified claims as a simulated markdown doc with ✓ receipts.
import type { AppState, SymbolState } from '../types';

interface Props {
  state: AppState;
}

function SymbolDoc({ sym }: { sym: SymbolState }) {
  if (!sym.done && sym.lockedClaims.length === 0) return null;

  return (
    <div className="symbol-doc">
      <h3 className="doc-symbol-name">
        <code>{sym.name}()</code>
      </h3>

      {sym.lockedClaims.length === 0 ? (
        <p className="doc-no-claims">No claims locked (all escalated or pending).</p>
      ) : (
        <div className="doc-claims">
          {sym.lockedClaims.map((c, i) => (
            <div key={i} className="doc-claim">
              <span className="doc-check">✓</span>
              <div className="doc-claim-body">
                <span className="doc-claim-type">[{c.claim_type}]</span>
                <span className="doc-claim-prose">{c.prose}</span>
                {c.verifications.map((v, vi) => (
                  <div key={vi} className="doc-receipt">
                    <code className="receipt-badge">
                      receipt: lane={v.lane} · verdict={v.verdict}
                    </code>
                  </div>
                ))}
              </div>
            </div>
          ))}
        </div>
      )}

      {sym.escalations.length > 0 && (
        <div className="doc-escalations">
          {sym.escalations.map((e, i) => (
            <div key={i} className="doc-escalated-claim">
              <span className="doc-unverified">↑ escalated</span>
              <span className="doc-escalation-reason">{e.reason}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

export function DocPanel({ state }: Props) {
  const hasContent = state.symbolOrder.some(
    n => state.symbols[n].lockedClaims.length > 0 || state.symbols[n].done,
  );

  return (
    <div className="panel doc-panel">
      <h2 className="panel-title">Verified Documentation</h2>
      {!hasContent ? (
        <p className="empty-msg">Verified claims will appear here as the run progresses.</p>
      ) : (
        <div className="doc-content">
          <div className="doc-module-header">
            <code>{state.module}</code>
            <span className="doc-model-badge">model: {state.model}</span>
          </div>
          {state.symbolOrder.map(name => (
            <SymbolDoc key={name} sym={state.symbols[name]} />
          ))}
        </div>
      )}
    </div>
  );
}
