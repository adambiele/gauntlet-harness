"""String and text helpers — a demo target for the Verified Documentation Harness.

Everyday text utilities. ``slugify``, ``word_count`` and ``reverse_words`` do exactly what
their docstrings say. ``truncate`` is the planted bug: its docstring promises the result is
*never* longer than ``length`` characters (the ellipsis counts against the budget), but the
implementation appends the ellipsis *after* slicing to the full length, so a truncated string
comes back one character too long. The example lane runs it, sees the overflow, and routes
the false claim to triage while the honest claims ship.

The harness reads this file with ``ast`` and never imports it; the functions only ever run
inside the subprocess sandbox.
"""


def slugify(text):
    """Return a URL-friendly slug: lowercase, with runs of whitespace joined by hyphens.

    Leading and trailing whitespace is stripped first, so ``"  Hello World "`` becomes
    ``"hello-world"``.
    """
    return "-".join(text.split()).lower()


def word_count(text):
    """Return the number of whitespace-separated words in ``text``."""
    return len(text.split())


def truncate(text, length):
    """Return ``text`` shortened to at most ``length`` characters.

    If ``text`` is longer than ``length`` it is cut and an ellipsis ``"…"`` is appended,
    and the returned string is *still at most* ``length`` characters long — the ellipsis is
    counted against the budget. Text already within the budget is returned unchanged.
    """
    if len(text) <= length:
        return text
    # BUG: slices to the full length and THEN appends the ellipsis, so the result is
    # length + 1 characters — one over the promised budget. The honest version would
    # slice to ``length - 1`` before appending.
    return text[:length] + "…"


def reverse_words(text):
    """Return ``text`` with its whitespace-separated words in reverse order."""
    return " ".join(reversed(text.split()))
