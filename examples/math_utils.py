"""Integer and numeric utilities — a demo target for the Verified Documentation Harness.

A small numeric toolkit. Most functions are honest — their docstrings match their code,
so every claim the worker writes about them verifies and ships. One function, ``is_prime``,
hides a subtle off-by-one bug: its docstring promises correct primality, but the loop stops
one divisor short, so it wrongly calls 9, 15, 25 … prime. The example lane *executes* it,
catches the lie with a real counterexample, and escalates the false claim to triage — while
the honest signature claim still ships.

The harness reads this file with ``ast`` and never imports it; the functions only ever run
inside the subprocess sandbox.
"""


def add(a, b):
    """Return the sum of ``a`` and ``b``."""
    return a + b


def clamp(value, low, high):
    """Return ``value`` constrained to the inclusive range ``[low, high]``.

    Values below ``low`` come back as ``low``; values above ``high`` come back as
    ``high``; anything in between is returned unchanged.
    """
    return max(low, min(value, high))


def gcd(a, b):
    """Return the greatest common divisor of two integers via Euclid's algorithm."""
    while b:
        a, b = b, a % b
    return abs(a)


def is_prime(n):
    """Return ``True`` if ``n`` is a prime number, ``False`` otherwise.

    A prime has no positive divisors other than 1 and itself, so 2 and 3 are prime
    while 1, 4 and 9 are not.
    """
    if n < 2:
        return False
    # BUG: the range stops at int(sqrt(n)) *exclusive*, so it never tests a divisor
    # equal to sqrt(n). Composites whose smallest factor reaches sqrt(n) — 9, 15, 25,
    # 49 … — slip through and are wrongly reported prime. The harness will catch it.
    for d in range(2, int(n ** 0.5)):
        if n % d == 0:
            return False
    return True


def factorial(n):
    """Return ``n!`` — the product of all positive integers up to ``n`` (with ``0! == 1``)."""
    result = 1
    for k in range(2, n + 1):
        result *= k
    return result
