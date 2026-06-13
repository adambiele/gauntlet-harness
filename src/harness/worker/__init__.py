"""Worker layer — the swappable model seam.

Session 0 ships the ``Worker`` ABC + a deterministic ``StubWorker``. Session A5 adds the
real LLM transports (``ClaudeWorker``, ``LocalWorker``) and the ``make_worker`` factory.
"""

from harness.worker.base import StubWorker, Worker
from harness.worker.llm_worker import BaseLLMWorker, ClaudeWorker, LocalWorker, make_worker

__all__ = [
    "Worker",
    "StubWorker",
    "BaseLLMWorker",
    "ClaudeWorker",
    "LocalWorker",
    "make_worker",
]
