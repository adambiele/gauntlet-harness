"""Material pillar — deterministic, no-AI code context extraction and doc rendering.

``loader.py``  — target .py file → CodeContext via stdlib ast (never imports the target).
``renderer.py`` — passing claims + CheckpointResults → verified markdown with ✓ receipts.
"""

from harness.material.loader import load_module
from harness.material.renderer import render_doc, render_index

__all__ = ["load_module", "render_doc", "render_index"]
