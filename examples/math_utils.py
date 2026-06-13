"""Integer and numeric utilities — a demo target for the Verified Documentation Harness.

A small numeric toolkit. Most functions are honest — their docstrings (and the worked
examples in them) match their code, so every claim the worker writes verifies and ships.
One function, ``is_prime``, hides a subtle off-by-one bug: its docstring documents the
correct answer for 9 (``False``), but the implementation stops one divisor short and
returns ``True``. A faithful worker copies that documented example into an ``ExampleClaim``,
the example lane *executes* it against the real code, gets the counterexample, FAILs, and
escalates the false claim to triage — while the honest claims still ship.

The harness reads this file with ``ast`` and never imports it; the functions only ever run
inside the subprocess sandbox.
"""


def add(a: int, b: int) -> int:
    """Return the sum of ``a`` and ``b``.

    >>> add(2, 3)
    5
    """
    return a + b


def clamp(value: int, low: int, high: int) -> int:
    """Return ``value`` constrained to the inclusive range ``[low, high]``.

    Values below ``low`` come back as ``low``; values above ``high`` come back as
    ``high``; anything in between is returned unchanged.

    >>> clamp(12, 0, 10)
    10
    >>> clamp(5, 0, 10)
    5
    """
    return max(low, min(value, high))


def gcd(a: int, b: int) -> int:
    """Return the greatest common divisor of two integers via Euclid's algorithm.

    >>> gcd(12, 18)
    6
    """
    while b:
        a, b = b, a % b
    return abs(a)


def is_prime(n: int) -> bool:
    """Return ``True`` if ``n`` is a prime number, ``False`` otherwise.

    A prime has no positive divisors other than 1 and itself.

    >>> is_prime(7)
    True
    >>> is_prime(9)
    False
    >>> is_prime(1)
    False
    """
    if n < 2:
        return False
    # BUG: the range stops at int(sqrt(n)) *exclusive*, so it never tests a divisor
    # equal to sqrt(n). Composites whose smallest factor reaches sqrt(n) — 9, 25, 49 …
    # — slip through and are wrongly reported prime. The harness will catch is_prime(9).
    for d in range(2, int(n ** 0.5)):
        if n % d == 0:
            return False
    return True


def factorial(n: int) -> int:
    """Return ``n!`` — the product of all positive integers up to ``n`` (with ``0! == 1``).

    >>> factorial(5)
    120
    >>> factorial(0)
    1
    """
    result = 1
    for k in range(2, n + 1):
        result *= k
    return result
