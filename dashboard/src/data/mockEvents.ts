// Hand-authored mock event stream — matches events.py field shapes exactly.
// Used for offline replay / demo. Every field name is frozen to the Python contract.
// Module: a simple math utilities fixture with add(), sort_items(), normalize().

import type { HarnessEvent } from '../types';

export const MOCK_EVENTS: HarnessEvent[] = [
  // ---- run starts ----
  {
    type: 'run_started',
    run_id: 'run-demo-001',
    module: 'examples/math_utils.py',
    model: 'stub',
  },

  // ======== symbol: add ========
  { type: 'symbol_started', symbol: 'add' },
  { type: 'generated', symbol: 'add', claim_count: 3 },
  { type: 'gate_result', symbol: 'add', violations: [] },

  // verify signature → pass
  {
    type: 'verify_result',
    symbol: 'add',
    claim_type: 'signature',
    lane: 'signature',
    verdict: 'pass',
    evidence: 'Signature matches: (x: int, y: int) -> int',
  },
  // verify example → pass
  {
    type: 'verify_result',
    symbol: 'add',
    claim_type: 'example',
    lane: 'example',
    verdict: 'pass',
    evidence: 'add(2, 3) == 5 ✓',
  },
  // verify behavioral → pass
  {
    type: 'verify_result',
    symbol: 'add',
    claim_type: 'behavioral',
    lane: 'behavioral',
    verdict: 'pass',
    evidence: 'assert add(0, 0) == 0 passed',
  },

  // lock all three
  {
    type: 'claim_locked',
    symbol: 'add',
    claim_type: 'signature',
    prose: 'Takes two integers and returns their sum.',
  },
  {
    type: 'claim_locked',
    symbol: 'add',
    claim_type: 'example',
    prose: 'add(2, 3) returns 5.',
  },
  {
    type: 'claim_locked',
    symbol: 'add',
    claim_type: 'behavioral',
    prose: 'Returns 0 when both inputs are 0.',
  },

  {
    type: 'metric_update',
    name: 'verify.signature.duration_ms',
    value: 12.3,
  },
  {
    type: 'metric_update',
    name: 'verify.example.duration_ms',
    value: 34.7,
  },
  {
    type: 'metric_update',
    name: 'verify.behavioral.duration_ms',
    value: 28.1,
  },
  {
    type: 'metric_update',
    name: 'generate.cost_usd',
    value: 0.000082,
  },

  { type: 'symbol_done', symbol: 'add' },

  // ======== symbol: sort_items (planted bug: reverses instead of sorts) ========
  { type: 'symbol_started', symbol: 'sort_items' },
  { type: 'generated', symbol: 'sort_items', claim_count: 2 },

  // gate fires an alarm: behavioral snippet references os module (planted guardrail hit)
  {
    type: 'alarm',
    alarm_type: 'MALFORMED_CLAIM',
    severity: 'high',
    symbol: 'sort_items',
    claim_ref: null,
    message: "Behavioral snippet contains disallowed import: 'import os'",
    recommended_action: 'Remove import statements from behavioral assert snippets.',
    timestamp: '2026-06-13T10:00:01.000Z',
  },
  {
    type: 'gate_result',
    symbol: 'sort_items',
    violations: [
      { rule: 'behavioral-snippet-vetting', reason: "disallowed import 'import os'" },
    ],
  },

  // signature claim passes gate, verify → pass
  {
    type: 'verify_result',
    symbol: 'sort_items',
    claim_type: 'signature',
    lane: 'signature',
    verdict: 'pass',
    evidence: 'Signature matches: (items: list) -> list',
  },
  {
    type: 'claim_locked',
    symbol: 'sort_items',
    claim_type: 'signature',
    prose: 'Accepts a list and returns a sorted list.',
  },

  // example claim: agent claims [3,1,2] → [1,2,3] but sort_items reverses → [2,1,3]
  {
    type: 'verify_result',
    symbol: 'sort_items',
    claim_type: 'example',
    lane: 'example',
    verdict: 'fail',
    evidence: "expected [1, 2, 3], got [2, 1, 3]",
  },

  // retry attempt 1
  {
    type: 'claim_retry',
    symbol: 'sort_items',
    attempt: 1,
    reason: "example lane FAIL: expected [1, 2, 3], got [2, 1, 3]",
  },
  // agent adjusts claim to match the reversed output — still wrong
  {
    type: 'verify_result',
    symbol: 'sort_items',
    claim_type: 'example',
    lane: 'example',
    verdict: 'fail',
    evidence: "expected [3, 2, 1], got [2, 1, 3]",
  },

  // retry attempt 2
  {
    type: 'claim_retry',
    symbol: 'sort_items',
    attempt: 2,
    reason: "example lane FAIL: expected [3, 2, 1], got [2, 1, 3]",
  },
  {
    type: 'verify_result',
    symbol: 'sort_items',
    claim_type: 'example',
    lane: 'example',
    verdict: 'fail',
    evidence: "expected [1, 2, 3], got [2, 1, 3]",
  },

  // retry attempt 3 (max)
  {
    type: 'claim_retry',
    symbol: 'sort_items',
    attempt: 3,
    reason: "example lane FAIL (attempt 3/3): expected [1, 2, 3], got [2, 1, 3]",
  },
  {
    type: 'verify_result',
    symbol: 'sort_items',
    claim_type: 'example',
    lane: 'example',
    verdict: 'fail',
    evidence: "expected [1, 2, 3], got [2, 1, 3]",
  },

  // escalated after 3 failed retries
  {
    type: 'alarm',
    alarm_type: 'EXAMPLE_FAILED',
    severity: 'high',
    symbol: 'sort_items',
    claim_ref: 'example:0',
    message: 'Example claim failed after 3 attempts. sort_items([3,1,2]) expected [1,2,3] but got [2,1,3]. Possible bug in implementation.',
    recommended_action: 'Regenerate with real counterexample or escalate for human review.',
    timestamp: '2026-06-13T10:00:03.500Z',
  },
  {
    type: 'claim_escalated',
    symbol: 'sort_items',
    reason: 'Failed after 3 retry attempts. Expected [1,2,3] got [2,1,3] — implementation appears to reverse rather than sort.',
  },

  {
    type: 'metric_update',
    name: 'verify.signature.duration_ms',
    value: 9.8,
  },
  {
    type: 'metric_update',
    name: 'verify.example.duration_ms',
    value: 41.2,
  },
  {
    type: 'metric_update',
    name: 'generate.cost_usd',
    value: 0.000124,
  },

  { type: 'symbol_done', symbol: 'sort_items' },

  // ======== symbol: normalize ========
  { type: 'symbol_started', symbol: 'normalize' },
  { type: 'generated', symbol: 'normalize', claim_count: 4 },
  { type: 'gate_result', symbol: 'normalize', violations: [] },

  {
    type: 'verify_result',
    symbol: 'normalize',
    claim_type: 'signature',
    lane: 'signature',
    verdict: 'pass',
    evidence: 'Signature matches: (text: str) -> str',
  },
  {
    type: 'verify_result',
    symbol: 'normalize',
    claim_type: 'example',
    lane: 'example',
    verdict: 'pass',
    evidence: "normalize('  Hello World  ') == 'hello world' ✓",
  },
  {
    type: 'verify_result',
    symbol: 'normalize',
    claim_type: 'behavioral',
    lane: 'behavioral',
    verdict: 'pass',
    evidence: "assert normalize('') == '' passed",
  },
  // description claim — always inconclusive
  {
    type: 'verify_result',
    symbol: 'normalize',
    claim_type: 'description',
    lane: 'none',
    verdict: 'inconclusive',
    evidence: 'DescriptionClaim: no mechanical check available.',
  },
  {
    type: 'claim_escalated',
    symbol: 'normalize',
    reason: 'INCONCLUSIVE: DescriptionClaim has no mechanically verifiable check.',
  },

  {
    type: 'claim_locked',
    symbol: 'normalize',
    claim_type: 'signature',
    prose: 'Accepts a string and returns a normalized (lowercased, stripped) string.',
  },
  {
    type: 'claim_locked',
    symbol: 'normalize',
    claim_type: 'example',
    prose: "normalize('  Hello World  ') returns 'hello world'.",
  },
  {
    type: 'claim_locked',
    symbol: 'normalize',
    claim_type: 'behavioral',
    prose: 'Empty string input returns empty string.',
  },

  {
    type: 'metric_update',
    name: 'verify.signature.duration_ms',
    value: 11.1,
  },
  {
    type: 'metric_update',
    name: 'verify.example.duration_ms',
    value: 29.5,
  },
  {
    type: 'metric_update',
    name: 'verify.behavioral.duration_ms',
    value: 25.3,
  },
  {
    type: 'metric_update',
    name: 'generate.cost_usd',
    value: 0.000093,
  },

  { type: 'symbol_done', symbol: 'normalize' },

  // ---- run done ----
  {
    type: 'run_done',
    run_id: 'run-demo-001',
    verified_count: 7,   // 3 (add) + 1 sig (sort_items) + 3 (normalize)
    escalated_count: 2,  // sort_items example + normalize description
  },
];

// Replay the mock stream into a callback, simulating SSE timing.
export function replayMockStream(
  onEvent: (event: HarnessEvent) => void,
  onDone?: () => void,
  intervalMs = 200,
): () => void {
  let index = 0;
  let cancelled = false;

  function step() {
    if (cancelled) return;
    if (index >= MOCK_EVENTS.length) {
      onDone?.();
      return;
    }
    onEvent(MOCK_EVENTS[index]);
    index++;
    setTimeout(step, intervalMs);
  }

  step();

  return () => {
    cancelled = true;
  };
}
