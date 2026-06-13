"""Demo target module for the Verified Documentation Harness.

Three public functions with different verification fates under the StubWorker:

* ``add``        — honest. Every claim (signature, examples, commutativity) verifies.
* ``sort_items`` — the **planted bug**. The docstring/claim says it sorts ascending,
  but it secretly reverses. The example lane *executes* it and catches the lie → the
  false claim is escalated to triage while the (true) signature claim still ships.
* ``normalize``  — only a signature + an unverifiable prose description; the description
  routes to triage (INCONCLUSIVE), the signature verifies.

The harness reads this file with ``ast`` and never imports it; the functions only ever
run inside the subprocess sandbox.
"""


def add(a, b):
    """Return the sum of two numbers."""
    return a + b


def sort_items(items):
    """Return ``items`` sorted in ascending order."""
    # BUG: this reverses instead of sorting ascending. The harness will catch it.
    return sorted(items, reverse=True)


def normalize(text):
    """Trim surrounding whitespace and lowercase the text."""
    return text.strip().lower()
