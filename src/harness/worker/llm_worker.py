"""LLM worker transports — ClaudeWorker (anthropic) and LocalWorker (openai-compat).

``BaseLLMWorker`` owns prompt construction and JSON→Claim parsing. The two thin
transports each implement only ``_complete(system, user) -> str``.

Design.md §5: only ``_complete`` differs between transports; the harness never knows
which model ran (the model-swap Bonus).

LAZY IMPORTS: ``anthropic`` and ``openai`` are imported INSIDE ``_complete``, not at
module level. This lets the module import cleanly and tests run without those SDKs
installed. Callers that actually invoke a live transport must have the ``[workers]``
extra installed (``pip install .[workers]``).
"""

from __future__ import annotations

import os
import re
from typing import Optional

from harness.alarms.types import Alarm
from harness.contracts import Claim, ClaimParseError, SymbolInfo, parse_claims
from harness.observability import (
    ATTR_COST_USD,
    ATTR_MODEL,
    ATTR_TOKENS_IN,
    ATTR_TOKENS_OUT,
    SPAN_GENERATE,
    span,
)
from harness.worker.base import StubWorker, Worker
from harness.worker.prompts import SYSTEM_PROMPT

__all__ = [
    "BaseLLMWorker",
    "ClaudeWorker",
    "OpenAIWorker",
    "LocalWorker",
    "make_worker",
]

# ---------------------------------------------------------------------------
# Prompt helpers
# ---------------------------------------------------------------------------

def _build_user_prompt(symbol: SymbolInfo, feedback: Optional[list[Alarm]]) -> str:
    """Build the user-turn message: scoped symbol slice + hybrid feedback.

    Hybrid feedback (design.md §6):
    - The *most recent* failure carries its full message/evidence.
    - Earlier failures collapse to a one-liner each: "attempt N: <type> → failed: <msg>"

    This keeps the prompt small for qwen's 8192-token context while keeping the most
    useful signal front and centre.
    """
    lines: list[str] = []

    # ---- symbol slice --------------------------------------------------------
    lines.append(f"Function: {symbol.name}")
    lines.append(f"Signature: {symbol.signature}")

    if symbol.docstring:
        lines.append(f"Docstring: {symbol.docstring}")

    lines.append("")
    lines.append("Source:")
    lines.append("```python")
    lines.append(symbol.source)
    lines.append("```")

    # ---- hybrid feedback -----------------------------------------------------
    if feedback:
        lines.append("")
        lines.append("== Previous attempt feedback ==")
        lines.append(
            "The claims you generated last time had the following issues. "
            "Fix only the failing claims; do not change claims that were already accepted."
        )

        # Most recent alarm gets the full detail; earlier ones get one-liners.
        if len(feedback) == 1:
            a = feedback[0]
            lines.append(f"  [latest] {a.type}: {a.message}")
            if a.recommended_action:
                lines.append(f"  Recommended action: {a.recommended_action}")
        else:
            # Earlier attempts: one-liners for everything except the last.
            for i, a in enumerate(feedback[:-1]):
                lines.append(f"  [attempt {i + 1}] {a.type} → failed: {a.message}")
            # Most recent: full detail.
            latest = feedback[-1]
            lines.append(f"  [latest] {latest.type}: {latest.message}")
            if latest.recommended_action:
                lines.append(f"  Recommended action: {latest.recommended_action}")

    lines.append("")
    lines.append(
        f"Emit a JSON array of claims about `{symbol.name}`. "
        "Remember: behavioral asserts must call the function by name with explicit inputs."
    )

    return "\n".join(lines)


_FENCE_RE = re.compile(r"```[a-zA-Z0-9]*[ \t]*\n?(.*?)```", re.DOTALL)


def _extract_json(raw: str) -> str:
    """Pull the bare JSON array/object out of a model response.

    Models (especially smaller ones like Haiku/GPT-mini) often wrap their claim JSON in a
    markdown code fence (```` ```json … ``` ````) and sometimes add a sentence of prose.
    ``parse_claims`` needs the raw JSON, so strip any fence and, if prose still surrounds
    it, slice to the outermost bracketed value. A clean JSON string passes through
    unchanged; genuinely malformed output still falls through to ``ClaimParseError``.
    """
    s = raw.strip()
    fenced = _FENCE_RE.search(s)
    if fenced:
        s = fenced.group(1).strip()
    if s and s[0] not in "[{":
        starts = [i for i in (s.find("["), s.find("{")) if i != -1]
        if starts:
            s = s[min(starts):]
    if s and s[-1] not in "]}":
        ends = [i for i in (s.rfind("]"), s.rfind("}")) if i != -1]
        if ends:
            s = s[: max(ends) + 1]
    return s.strip()


# ---------------------------------------------------------------------------
# Base worker
# ---------------------------------------------------------------------------

class BaseLLMWorker(Worker):
    """Owns prompt construction + JSON→Claim parsing; delegates _complete to subclasses.

    Subclasses implement only::

        def _complete(self, system: str, user: str) -> str:
            ...  # call the SDK; return raw text response

    The return value is fed to ``parse_claims``; a ``ClaimParseError`` propagates
    directly so the loop can turn it into a ``MALFORMED_CLAIM`` alarm.

    The ``span(SPAN_GENERATE)`` wrapper records model, token counts, and cost for the
    OTel aggregator and dashboard metrics panel (design.md §10).
    """

    # Subclasses set these in __init__.
    model: str = ""

    def generate(
        self, symbol: SymbolInfo, feedback: Optional[list[Alarm]] = None
    ) -> list[Claim]:
        """Build prompts, call _complete, parse claims; wrap in a generate span."""
        system = SYSTEM_PROMPT
        user = _build_user_prompt(symbol, feedback)

        # Token/cost are filled in by the SDK response; default 0 until populated.
        tokens_in: int = 0
        tokens_out: int = 0
        cost_usd: float = 0.0

        with span(
            SPAN_GENERATE,
            **{
                ATTR_MODEL: self.model,
                ATTR_TOKENS_IN: tokens_in,
                ATTR_TOKENS_OUT: tokens_out,
                ATTR_COST_USD: cost_usd,
            },
        ) as otel_span:
            raw, tokens_in, tokens_out, cost_usd = self._complete_with_usage(system, user)

            # Update span attributes now that we have real counts.
            if otel_span is not None:
                otel_span.set_attribute(ATTR_TOKENS_IN, tokens_in)
                otel_span.set_attribute(ATTR_TOKENS_OUT, tokens_out)
                otel_span.set_attribute(ATTR_COST_USD, cost_usd)

        # Strip markdown fences/prose models love to add, then validate. parse_claims
        # raises ClaimParseError on genuinely bad JSON — propagate; the loop handles it.
        return parse_claims(_extract_json(raw))

    def _complete_with_usage(
        self, system: str, user: str
    ) -> tuple[str, int, int, float]:
        """Call _complete and extract token/cost info.

        Returns (raw_text, tokens_in, tokens_out, cost_usd). Subclasses should override
        ``_complete`` for the simple case; override this method if the SDK response
        carries usage directly.
        """
        raw = self._complete(system, user)
        return raw, 0, 0, 0.0

    def _complete(self, system: str, user: str) -> str:  # pragma: no cover
        """Call the LLM and return the raw text response. Override in subclasses."""
        raise NotImplementedError("Subclasses must implement _complete")


# ---------------------------------------------------------------------------
# ClaudeWorker — anthropic SDK (lazy import)
# ---------------------------------------------------------------------------

class ClaudeWorker(BaseLLMWorker):
    """Calls the Anthropic ``messages.create`` API.

    ``anthropic`` is imported lazily inside ``_complete`` so this module is importable
    without the SDK installed. Uses ``claude-sonnet-4-6`` by default; pass a different
    model string for the cloud swap (e.g. ``claude-haiku-4-5``).
    """

    DEFAULT_MODEL = "claude-sonnet-4-6"

    def __init__(self, model: Optional[str] = None) -> None:
        self.model = model or self.DEFAULT_MODEL

    def _complete_with_usage(
        self, system: str, user: str
    ) -> tuple[str, int, int, float]:
        """Call Anthropic messages.create and return (text, tokens_in, tokens_out, cost)."""
        # Lazy import — SDK not required at module load time.
        import anthropic  # noqa: PLC0415

        client = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY from env
        response = client.messages.create(
            model=self.model,
            max_tokens=4096,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        raw = response.content[0].text
        tokens_in = response.usage.input_tokens if response.usage else 0
        tokens_out = response.usage.output_tokens if response.usage else 0
        # Approximate cost (not authoritative — exact pricing changes; good enough for
        # the dashboard metrics panel).
        cost_usd = _estimate_cost_anthropic(self.model, tokens_in, tokens_out)
        return raw, tokens_in, tokens_out, cost_usd


def _estimate_cost_anthropic(model: str, tokens_in: int, tokens_out: int) -> float:
    """Very rough per-token cost estimate for the dashboard metrics panel.

    Prices in USD per million tokens (MTok). These are approximate and may be stale;
    treat as a ballpark, not a bill.
    """
    # Prices: (input_per_mtok, output_per_mtok). Current Anthropic list prices.
    _PRICES: dict[str, tuple[float, float]] = {
        "claude-sonnet-4-6": (3.0,  15.0),
        "claude-haiku-4-5":  (1.0,   5.0),
        "claude-opus-4-8":   (5.0,  25.0),
        # Fallback for unknown claude models (Sonnet-tier).
        "claude":            (3.0,  15.0),
    }
    for prefix, (inp, out) in _PRICES.items():
        if model.startswith(prefix):
            return (tokens_in * inp + tokens_out * out) / 1_000_000
    return 0.0


# ---------------------------------------------------------------------------
# OpenAIWorker — OpenAI cloud API via the official openai SDK (lazy import)
# ---------------------------------------------------------------------------

class OpenAIWorker(BaseLLMWorker):
    """Calls the OpenAI cloud API (``api.openai.com``) via the official ``openai`` SDK.

    A second cloud provider alongside ``ClaudeWorker``, behind the same ``Worker`` seam —
    so the model swap spans providers (Claude ↔ GPT ↔ local Qwen) with no harness change.
    Reads ``OPENAI_API_KEY`` from the env; default model ``gpt-4o`` (pass another for the
    swap). ``openai`` is imported lazily so the module loads without the SDK installed.
    """

    DEFAULT_MODEL = "gpt-4o"

    def __init__(self, model: Optional[str] = None) -> None:
        self.model = model or self.DEFAULT_MODEL

    def _complete_with_usage(
        self, system: str, user: str
    ) -> tuple[str, int, int, float]:
        """Call OpenAI chat.completions and return (text, tokens_in, tokens_out, cost)."""
        # Lazy import — SDK not required at module load time.
        import openai  # noqa: PLC0415

        client = openai.OpenAI()  # reads OPENAI_API_KEY; default base_url = api.openai.com
        response = client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        )
        raw = response.choices[0].message.content or ""
        usage = response.usage
        tokens_in = usage.prompt_tokens if usage else 0
        tokens_out = usage.completion_tokens if usage else 0
        cost_usd = _estimate_cost_openai(self.model, tokens_in, tokens_out)
        return raw, tokens_in, tokens_out, cost_usd


def _estimate_cost_openai(model: str, tokens_in: int, tokens_out: int) -> float:
    """Rough per-token cost estimate (USD/MTok) for the dashboard metrics panel.

    Approximate, possibly stale — a ballpark, not a bill. More specific prefixes (``-mini``)
    are listed first so they win the ``startswith`` match.
    """
    _PRICES: dict[str, tuple[float, float]] = {
        "gpt-4o-mini":  (0.15,  0.60),
        "gpt-4o":       (2.50, 10.00),
        "gpt-4.1-mini": (0.40,  1.60),
        "gpt-4.1":      (2.00,  8.00),
    }
    for prefix, (inp, out) in _PRICES.items():
        if model.startswith(prefix):
            return (tokens_in * inp + tokens_out * out) / 1_000_000
    return 0.0


# ---------------------------------------------------------------------------
# LocalWorker — openai-compatible SDK pointing at LAN LiteLLM proxy (lazy import)
# ---------------------------------------------------------------------------

class LocalWorker(BaseLLMWorker):
    """Calls a LAN-local LiteLLM proxy via the OpenAI-compatible SDK.

    Base URL: ``http://10.10.2.113:4000/v1`` (LAN-only; not reachable from Render).
    Model: ``qwen3-coder`` (8192-ctx — the per-symbol push keeps every prompt small).
    API key: read from the ``OPENAI_API_KEY`` environment variable (can be any string if
    the proxy does not enforce it).

    ``openai`` is imported lazily inside ``_complete_with_usage`` so this module is
    importable without the SDK installed.
    """

    BASE_URL = "http://10.10.2.113:4000/v1"
    DEFAULT_MODEL = "qwen3-coder"

    def __init__(self, model: Optional[str] = None, base_url: Optional[str] = None) -> None:
        self.model = model or self.DEFAULT_MODEL
        self._base_url = base_url or self.BASE_URL

    def _complete_with_usage(
        self, system: str, user: str
    ) -> tuple[str, int, int, float]:
        """Call the OpenAI-compat endpoint and return (text, tokens_in, tokens_out, cost)."""
        # Lazy import — SDK not required at module load time.
        import openai  # noqa: PLC0415

        api_key = os.environ.get("OPENAI_API_KEY", "local")
        client = openai.OpenAI(base_url=self._base_url, api_key=api_key)
        response = client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        )
        raw = response.choices[0].message.content or ""
        usage = response.usage
        tokens_in = usage.prompt_tokens if usage else 0
        tokens_out = usage.completion_tokens if usage else 0
        cost_usd = 0.0  # local model — no cloud cost
        return raw, tokens_in, tokens_out, cost_usd


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def make_worker(name: str) -> Worker:
    """Return a Worker for the given name.

    Supported names:
    - ``"stub"``            → StubWorker (no LLM calls; deterministic)
    - ``"sonnet"`` / ``"claude"`` → ClaudeWorker(claude-sonnet-4-6)
    - ``"haiku"``           → ClaudeWorker(claude-haiku-4-5)
    - ``"openai"`` / ``"gpt"``  → OpenAIWorker(gpt-4o)
    - ``"qwen"`` / ``"local"``  → LocalWorker(qwen3-coder)

    The harness passes this name from the model picker / CLI ``--worker`` arg (design.md
    §9 / adapters/cli.py) so changing the active model is a config-time decision, never
    a code change.
    """
    name = name.strip().lower()

    if name == "stub":
        return StubWorker()

    if name in ("sonnet", "claude"):
        return ClaudeWorker(model="claude-sonnet-4-6")

    if name == "haiku":
        return ClaudeWorker(model="claude-haiku-4-5")

    if name in ("openai", "gpt"):
        return OpenAIWorker()

    if name in ("qwen", "local"):
        return LocalWorker()

    raise ValueError(
        f"Unknown worker name {name!r}. Valid names: 'stub', 'sonnet', 'claude', "
        "'haiku', 'openai', 'gpt', 'qwen', 'local'."
    )
