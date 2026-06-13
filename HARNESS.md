# Verified Documentation Harness

**A harness that an AI documentation agent runs inside — so that no unverified claim ever ships.**

An AI writes documentation for a Python module. But instead of emitting prose we hope is
true, the agent emits **structured claims, each carrying its own falsifiable check**. The
harness runs every check against the *real* code in a sandbox, keeps only the claims that
survive, and renders documentation from those. "The docs are true" stops being a hope and
becomes a property of the system — **true by construction**.

The agent (the "worker") is a swappable component *inside* the harness. The harness itself —
the part that makes the guarantee — is separate, deterministic, and has no AI in its
verification path. **Reality is the adjudicator, not a model.**

---

## The four pillars (and why they're separate from the worker)

The challenge is to build a *harness*, not an agent. The harness is everything that wraps,
constrains, and checks the worker. Each pillar lives in its own package and is exercised by
the loop — none of them call a model:

| Pillar | Package | What it does | Separate because… |
|---|---|---|---|
| **Material handling** | `material/` | Reads the target module by **static AST analysis** — never imports it — into typed `SymbolInfo`s; renders verified claims to markdown | The worker sees a curated, safe view of the code; it never decides what is loaded |
| **Guardrails** | `guardrails/` | A declared, printable rule set applied to claims *before* any code runs: target must exist, snippets are AST-vetted, no secrets | Policy is fixed and inspectable; the worker can't weaken it |
| **Checkpoints** | `checkpoints/` | Runs each claim's check against the real symbol in a subprocess sandbox; returns PASS/FAIL/INCONCLUSIVE with evidence | The pass/fail verdict comes from executing real code, not from the model's confidence |
| **Alarms** | `alarms/` + `escalation/` | Structured, severity-ranked alarms on every violation; unresolved claims escalate to a human triage queue | The harness decides what is wrong and what a human must see — independently of the worker |

The **worker** (`worker/`) is the only model-backed part, and it sits behind a one-method
interface (`Worker.generate(symbol, feedback) -> list[Claim]`). Swap Claude for GPT-4o
for a local Qwen and **nothing else in the harness changes** — the same guardrails gate it,
the same checkpoints judge it, the same alarms catch it. That swappability is the proof that
the pillars are genuinely separate from the agent.

---

## How it works — the loop

For each public function in the target module, sequentially:

```
            ┌────────── worker (swappable: sonnet | haiku | gpt | qwen | stub) ──────────┐
            │                                                                        │
  symbol ──▶ generate ──▶ gate ──▶ verify ──▶ decide ─┬─ PASS  → lock → render ✓     │
            │ (claims)   (guard-   (sandbox)          ├─ FAIL  → alarm → retry ◀─────┘ (≤3, hybrid feedback)
            │            rails)                        └─ INCONCLUSIVE → escalate → triage
            └────────────────────────────────────────────────────────────────────────┘
```

1. **generate** — the worker returns a list of `Claim`s about the symbol. On a retry it also
   gets the previous failures as feedback (the full traceback for the latest attempt, one-line
   summaries for earlier ones).
2. **gate** — `guardrails.enforce` drops/​downgrades unsafe or malformed claims and emits an
   `Alarm` for each. Nothing has executed yet.
3. **verify** — `checkpoints.runner.verify` runs each surviving claim's check against the real
   code in a subprocess and returns a `CheckpointResult` (verdict + evidence + `code_hash`).
4. **decide** — partition: **PASS** → locked (will render); **FAIL** → retry pool; **INCONCLUSIVE**
   → escalate to triage.
5. **retry** — regenerate the failed claims with hybrid feedback, re-gate, re-verify, up to 3
   attempts per symbol. Still failing → escalate.
6. **render** — only locked (PASS) claims become documentation, each with a ✓ receipt citing
   the lane, the `code_hash`, and a timestamp. Everything — claims, receipts, alarms,
   escalations, the rendered doc — is persisted to an immutable `runs/<id>/` audit tree.

The money demo: a function `sort_items` whose docstring says "sorts ascending" but which
secretly reverses. The worker confidently claims `sort_items([3,1,2]) == [1,2,3]`. The example
lane **executes it**, gets `[3,2,1]`, FAILs with the real counterexample, retries, and finally
escalates the false claim to triage — while the function's *true* signature claim still ships.
The lie cannot reach the docs.

---

## The claim model — checks, not prose

A claim is a Pydantic discriminated union (`contracts.py`). Each variant carries a different
*kind* of falsifiable evidence, so verification is a different mechanical lane per type:

| Claim type | Carries | Verified by | Lane |
|---|---|---|---|
| `SignatureClaim` | a claimed signature string | **structural AST diff** vs the real signature — no execution | `signature` |
| `ExampleClaim` | structured `(args, kwargs, expected)` cases | harness **builds the call** and runs it in the sandbox, compares results | `example` |
| `BehavioralClaim` | `assert` snippets | snippet **executed** in the sandbox; any exception → FAIL | `behavioral` |
| `DescriptionClaim` | free prose | not mechanically checkable → marked **"unverified"**, routed to triage | — |

Crucially the agent emits *structured* checks (args/kwargs/asserts), not free-text we have to
trust or parse. The single validation gate is `parse_claims()`: malformed model output raises
`ClaimParseError` → a `MALFORMED_CLAIM` alarm. **This Pydantic validation is itself a guardrail**
— it's what catches a weak model's mistakes, which is why we deliberately do *not* rely on
provider-enforced JSON.

---

## Static analysis & threat model

The target module is **untrusted input**. It is never imported on the read path — importing
would execute its top-level code. Instead:

- **`material/loader.py` uses stdlib `ast` only.** It extracts public top-level functions,
  builds each `SymbolInfo` from source text, and computes `code_hash = sha256(ast.unparse(node))`
  — a normalized hash that's stable across comments/whitespace and is the replay cache key.
- **The target's code runs in exactly one place: the subprocess sandbox** (`checkpoints/sandbox.py`),
  which re-execs the module source in a fresh interpreter, runs one call or one assert with a
  timeout, and returns results over stdout. A hang or crash is contained to that subprocess.
- **Behavioral snippets are vetted twice.** First an AST-walk allowlist (`guardrails/`) fast-rejects
  imports, `eval`/`exec`/`open`/`__import__`, and dunder access, and requires the snippet to
  reference the target. This is a *declared guardrail and fast-reject — not the security boundary.*
  The real boundary is the subprocess sandbox.
- **Secret/path scanning** rejects key-like strings and absolute paths in any claim text.

---

## Observability

OpenTelemetry is the single source of truth. Every step opens a span in a fixed tree —
`run → symbol → {generate, gate, verify.<lane>, decide}` — stamped with model, token, cost,
verdict, lane, and duration attributes. Two consumers read the same spans:

1. An **in-process `Aggregator`** feeds the dashboard's live metrics (per-lane avg + p95,
   cost) via `metric_update` events — no external dependency required.
2. An **optional OTLP exporter → Langfuse Cloud**, which is **opt-in only** (`HARNESS_LANGFUSE=1`
   plus keys). Ambient `LANGFUSE_*` credentials never trigger export — a deliberate safety choice.

The `runs/<id>/` store is the durable audit log; the rendered docs are a *projection* of it,
never the source of truth. Re-running an unchanged module replays cached PASS receipts
(keyed by `code_hash`) instead of re-executing.

---

## The model swap (bonus)

`worker/llm_worker.py` ships four transports behind the `Worker` interface, chosen by name
(`make_worker`): `ClaudeWorker` (Anthropic SDK, `claude-sonnet-4-6` / `claude-haiku-4-5`),
`OpenAIWorker` (OpenAI SDK → `gpt-4o`), `LocalWorker` (OpenAI-compatible SDK → a LAN
`qwen3-coder`), and the LLM-free `StubWorker`. The dashboard's model picker and the CLI's
`--worker` flag select among them at runtime — so the swap spans **two cloud providers plus a
self-hosted local model**, with no change to the harness. The output still ships only verified
claims regardless of which model produced them — and a weaker model simply trips more guardrails
and alarms, visibly (we saw Haiku's first `sort_items` claim get caught and corrected on retry).

**The `demo` worker (deterministic catch-and-recover).** A capable model writes *accurate*
claims, so there's nothing to catch — great for real docs, undramatic for a demo. `SeededWorker`
(name `demo`, or `demo:<model>`) fixes that: on the first attempt it injects **one guaranteed-false
claim** (a wrong `expected` derived from the symbol's own `>>>` doctest, or a phantom-parameter
signature if there's no doctest), so the FAIL → alarm → retry path *always* fires; on retry it
delegates to a live model that, handed the harness's counterexample, regenerates true claims that
verify and ship. The whole loop — *confident lie → caught with a real counterexample → corrected by
a live model → only the truth ships* — runs deterministically on any model and any target.

> **Known limitation (replay cache).** The PASS-replay cache is keyed by `(symbol, lane, code_hash)`,
> not by claim content, so a PASS cached from an earlier run can mask a *different* claim in the same
> lane on the same code. `SeededWorker` sets `bypass_replay_cache` to opt out (otherwise a prior
> honest run would hide its injected lie). The general fix — fold claim identity into the cache key —
> is noted but unbuilt.

---

## Scope (what's built vs designed-for)

**Built:** the full vertical slice — static loader, the three verification lanes + sandbox,
guardrails, alarms, escalation, persistence + replay, the loop with retry/feedback, the worker
swap, the FastAPI SSE backend, and the React dashboard. Functions only; classes/async are out
of sprint scope.

**Designed-for, not built:** verifying *effectful* / LLM-calling functions (the sandbox snippet
would carry its own mocks — additive, no architecture change; for now such functions escalate to
triage), durable persistence backends, and an interactive (blocking) escalation handler.

---

## Run it

```bash
pip install -e '.[http,workers]'

# CLI — watch the loop catch the planted bug (LLM-free):
python -m harness.adapters.cli examples/planted_bug.py --worker stub

# Local server (SSE) for the dashboard:
HARNESS_RUNS_DIR=runs uvicorn harness.adapters.http:app --reload
#   POST /run {module_path|module_source, model}  → {run_id}
#   GET  /run/{run_id}/stream                      → text/event-stream

# Dashboard (separate terminal):
cd dashboard && npm install && VITE_API_URL=http://127.0.0.1:8000 npm run dev

# Tests:
pytest -q
```

## Deploy

- **Backend → Render** (Docker, `Dockerfile` + `render.yaml`): binds `$PORT`, set
  `ANTHROPIC_API_KEY`; optional Langfuse via `HARNESS_LANGFUSE=1` + a **dedicated** project's keys.
  Free tier is ephemeral and idle-spins-down — warm it before a demo.
- **Frontend → Vercel** (static SPA, `dashboard/vercel.json`): set `VITE_API_URL` to the Render URL.

## Repo map

```
src/harness/
  contracts.py          # Claim union, Verdict, SymbolInfo, CheckpointResult — the seams
  material/             # loader (ast, no-import) + renderer (✓ receipts)
  guardrails/           # declared rules + enforce (the gate)
  checkpoints/          # sandbox + signature/example/behavioral lanes + runner
  alarms/               # types (registry) + emit
  escalation/           # BatchHandler → triage queue
  worker/               # Worker ABC + StubWorker + Claude/Local transports
  observability/        # OTel init, span helper, in-process Aggregator, Langfuse opt-in
  persistence/          # immutable runs/<id>/ store + replay
  harness.py            # THE LOOP — wires every pillar
  adapters/             # cli.py, http.py (FastAPI SSE + GET /examples), events.py (SSE contract)
dashboard/              # Vite + React SPA (live loop, doc, triage, metrics, example picker)
examples/               # demo targets — pick any from the dashboard or pass as a CLI arg
  planted_bug.py        #   a sort that secretly reverses (the money demo)
  math_utils.py         #   numeric utils with a planted off-by-one is_prime bug
  string_utils.py       #   text helpers with a planted truncate-overflow bug
  geometry.py           #   all-honest "green run" + one prose-only triage case
```

The dashboard's **example picker** lists whatever is in `examples/` live: the SPA fetches
`GET /examples` (path + one-line title parsed from each module docstring via `ast`, never
imported) and falls back to a static list offline. Selecting one fills the module path;
the box still accepts a custom path or pasted source. Add a new `examples/*.py` and it
shows up in the picker automatically — no dashboard change needed.
