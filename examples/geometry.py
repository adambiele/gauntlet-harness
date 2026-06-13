"""2D geometry helpers — a demo target for the Verified Documentation Harness.

The "green run" counterpart to the planted-bug demos: every function here does exactly what
its docstring says, so a faithful worker produces only claims that verify and ship. The one
twist is ``describe_shape``, whose docstring is deliberately informal prose with no fixed
contract — that description routes to triage (INCONCLUSIVE) while its signature still verifies.

The harness reads this file with ``ast`` and never imports it; the functions only ever run
inside the subprocess sandbox.
"""

import math


def circle_area(radius):
    """Return the area of a circle with the given ``radius`` (π·r²)."""
    return math.pi * radius * radius


def rectangle_area(width, height):
    """Return the area of a rectangle: ``width`` × ``height``."""
    return width * height


def hypotenuse(a, b):
    """Return the length of the hypotenuse of a right triangle with legs ``a`` and ``b``."""
    return math.sqrt(a * a + b * b)


def clamp_angle(degrees):
    """Return ``degrees`` wrapped into the half-open range ``[0, 360)``."""
    return degrees % 360


def describe_shape(sides):
    """Return a human-readable name for a polygon with ``sides`` sides.

    This is a convenience labeller for UI display; the exact wording is intentionally
    informal and may change over time, so treat it as descriptive prose rather than a
    contract.
    """
    names = {3: "triangle", 4: "quadrilateral", 5: "pentagon", 6: "hexagon"}
    return names.get(sides, f"{sides}-gon")
