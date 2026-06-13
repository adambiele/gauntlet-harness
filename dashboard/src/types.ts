// TypeScript mirror of src/harness/adapters/events.py — field-for-field match.
// DO NOT alter field names; they are frozen contract.

export type Severity = 'block' | 'high' | 'low';

export interface RunStarted {
  type: 'run_started';
  run_id: string;
  module: string;
  model: string;
}

export interface SymbolStarted {
  type: 'symbol_started';
  symbol: string;
}

export interface Generated {
  type: 'generated';
  symbol: string;
  claim_count: number;
}

export interface GateResult {
  type: 'gate_result';
  symbol: string;
  violations: unknown[];
}

export interface VerifyResult {
  type: 'verify_result';
  symbol: string;
  claim_type: string;
  lane: string;
  verdict: string;  // 'pass' | 'fail' | 'inconclusive'
  evidence: string;
}

export interface ClaimLocked {
  type: 'claim_locked';
  symbol: string;
  claim_type: string;
  prose: string;
}

export interface ClaimRetry {
  type: 'claim_retry';
  symbol: string;
  attempt: number;
  reason: string;
}

export interface ClaimEscalated {
  type: 'claim_escalated';
  symbol: string;
  reason: string;
}

export interface AlarmEvent {
  type: 'alarm';
  alarm_type: string;
  severity: Severity;
  symbol: string;
  claim_ref: string | null;
  message: string;
  recommended_action: string;
  timestamp: string;
}

export interface SymbolDone {
  type: 'symbol_done';
  symbol: string;
}

export interface MetricUpdate {
  type: 'metric_update';
  name: string;
  value: number;
}

export interface RunDone {
  type: 'run_done';
  run_id: string;
  verified_count: number;
  escalated_count: number;
}

export type HarnessEvent =
  | RunStarted
  | SymbolStarted
  | Generated
  | GateResult
  | VerifyResult
  | ClaimLocked
  | ClaimRetry
  | ClaimEscalated
  | AlarmEvent
  | SymbolDone
  | MetricUpdate
  | RunDone;

// ---- UI State types ----

export type SymbolStage = 'pending' | 'generating' | 'gating' | 'verifying' | 'deciding' | 'done';

export interface LockedClaim {
  claim_type: string;
  prose: string;
  verifications: VerifyResult[];
}

export interface SymbolState {
  name: string;
  stage: SymbolStage;
  claimCount: number;
  violations: unknown[];
  verifyResults: VerifyResult[];
  lockedClaims: LockedClaim[];
  retries: ClaimRetry[];
  escalations: ClaimEscalated[];
  alarms: AlarmEvent[];
  done: boolean;
}

export interface MetricSeries {
  name: string;
  values: number[];
}

export interface AppState {
  runId: string | null;
  module: string;
  model: string;
  symbols: Record<string, SymbolState>;
  symbolOrder: string[];
  alarms: AlarmEvent[];
  escalations: ClaimEscalated[];
  metrics: Record<string, number[]>;
  metricNames: string[];
  verifiedCount: number;
  escalatedCount: number;
  isDone: boolean;
  isRunning: boolean;
}
