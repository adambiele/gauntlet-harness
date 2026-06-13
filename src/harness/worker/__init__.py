"""Worker layer — the swappable model seam.

Session 0 ships the ``Worker`` ABC + a deterministic ``StubWorker``. The real LLM
transports (ClaudeWorker/LocalWorker) are Session A5.
"""

from harness.worker.base import StubWorker, Worker

__all__ = ["Worker", "StubWorker"]
