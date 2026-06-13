"""Verified Documentation Harness — frozen foundations (Session 0).

The agent emits structured ``Claim`` objects carrying their own falsifiable checks; the
harness verifies each against the real code and renders docs only from survivors. This
package's foundation layer (contracts, sandbox, persistence interface, alarms, OTel,
SSE events, worker ABC + stub) is the keystone every later session imports.
"""

from harness.contracts import (
    BehavioralClaim,
    CheckpointResult,
    Claim,
    ClaimParseError,
    CodeContext,
    DescriptionClaim,
    ExampleCase,
    ExampleClaim,
    SignatureClaim,
    SymbolInfo,
    Verdict,
    parse_claims,
)

__all__ = [
    "Verdict",
    "SignatureClaim",
    "ExampleCase",
    "ExampleClaim",
    "BehavioralClaim",
    "DescriptionClaim",
    "Claim",
    "parse_claims",
    "ClaimParseError",
    "SymbolInfo",
    "CodeContext",
    "CheckpointResult",
]
