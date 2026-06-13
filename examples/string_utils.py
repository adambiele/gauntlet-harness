"""String and text helpers — a demo target for the Verified Documentation Harness.

Everyday text utilities. ``slugify``, ``word_count`` and ``reverse_words`` do exactly what
their docstrings (and worked examples) say. ``title_case`` is the planted bug — and a real
one: it delegates to ``str.title()``, which mishandles apostrophes, turning ``"don't"`` into
``"Don'T"``. The docstring documents the intuitive correct output (``"Don't Stop"``), so a
faithful worker copies that into an ``ExampleClaim``; the example lane runs it against the
real code, gets ``"Don'T Stop"``, FAILs, and routes the false claim to triage while the
honest claims ship. The bug is invisible at a glance — you have to know the ``str.title()``
quirk — so the worker trusts the documented example rather than "correcting" it.

The harness reads this file with ``ast`` and never imports it; the functions only ever run
inside the subprocess sandbox.
"""


def slugify(text: str) -> str:
    """Return a URL-friendly slug: lowercase, with runs of whitespace joined by hyphens.

    Leading and trailing whitespace is stripped first.

    >>> slugify("  Hello World ")
    'hello-world'
    """
    return "-".join(text.split()).lower()


def word_count(text: str) -> int:
    """Return the number of whitespace-separated words in ``text``.

    >>> word_count("the quick brown fox")
    4
    """
    return len(text.split())


def title_case(text: str) -> str:
    """Return ``text`` with the first letter of each word capitalised.

    Apostrophes inside a word do not start a new word, so a contraction keeps its tail
    lowercase.

    >>> title_case("the lazy dog")
    'The Lazy Dog'
    >>> title_case("don't stop believing")
    "Don't Stop Believing"
    """
    # BUG: str.title() treats the apostrophe as a word boundary, so "don't" becomes
    # "Don'T" — the letter after the apostrophe is wrongly capitalised. The honest version
    # would capitalise per whitespace-separated word. The harness will catch the contraction.
    return text.title()


def reverse_words(text: str) -> str:
    """Return ``text`` with its whitespace-separated words in reverse order.

    >>> reverse_words("a b c")
    'c b a'
    """
    return " ".join(reversed(text.split()))
