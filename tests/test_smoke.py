"""Smoke test — the keystone round-trips end to end (sessions.md Session 0 DoD).

Builds a Signature + Example + Behavioral claim, serializes them to a JSON list, parses
them back through ``parse_claims`` (the single validation gate), and runs one passing and
one failing ``run_assert`` against a real symbol.
"""

import json

import pytest

from harness.contracts import (
    BehavioralClaim,
    ClaimParseError,
    ExampleCase,
    ExampleClaim,
    SignatureClaim,
    parse_claims,
)
from harness.checkpoints.sandbox import run_assert

ADD_SRC = "def add(a, b):\n    return a + b\n"


def test_claims_round_trip_through_parse_helper():
    claims = [
        SignatureClaim(
            type="signature",
            target="add",
            prose="add takes two numbers and returns their sum.",
            claimed_signature="(a, b)",
        ),
        ExampleClaim(
            type="example",
            target="add",
            prose="add(2, 3) == 5",
            cases=[ExampleCase(args=[2, 3], kwargs={}, expected=5)],
        ),
        BehavioralClaim(
            type="behavioral",
            target="add",
            prose="add is commutative.",
            asserts=["assert add(1, 2) == add(2, 1)"],
        ),
    ]

    # Serialize to a JSON list (what a worker would emit) and parse it back.
    as_json = json.dumps([c.model_dump() for c in claims])
    parsed = parse_claims(as_json)

    assert len(parsed) == 3
    assert isinstance(parsed[0], SignatureClaim)
    assert isinstance(parsed[1], ExampleClaim)
    assert isinstance(parsed[2], BehavioralClaim)
    assert parsed[1].cases[0].expected == 5


def test_malformed_claim_raises_claim_parse_error():
    # Unknown discriminator value -> MALFORMED_CLAIM territory.
    with pytest.raises(ClaimParseError):
        parse_claims('[{"type": "wat", "target": "x", "prose": "y"}]')
    # Not even a list.
    with pytest.raises(ClaimParseError):
        parse_claims('{"type": "signature"}')


def test_one_assert_passes_one_fails():
    ok = run_assert(ADD_SRC, "add", "assert add(2, 3) == 5")
    assert ok.ok is True

    bad = run_assert(ADD_SRC, "add", "assert add(2, 3) == 6")
    assert bad.ok is False
    assert "AssertionError" in bad.error
