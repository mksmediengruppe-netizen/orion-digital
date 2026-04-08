"""
ARCANE 2 — Compatibility shim: shared.llm.client
=================================================
Re-exports SimpleLLMClient as UnifiedLLMClient for backward compat.
Used by: core/agent_loop.py, shared/llm/router.py, workers/browser/worker.py

These modules were written against the v1 UnifiedLLMClient interface.
SimpleLLMClient (llm_client.py) provides the same core method: complete().
This shim bridges the naming gap without touching the consumers.
"""

from shared.llm.llm_client import SimpleLLMClient

# Re-export SimpleLLMClient under the old name
UnifiedLLMClient = SimpleLLMClient


# ── Exceptions that the old client.py defined ─────────────────────────────────

class LLMClientError(Exception):
    """Base exception for LLM client errors."""
    pass


class BadRequestError(LLMClientError):
    """Request was malformed or rejected by the provider (4xx)."""
    def __init__(self, message: str = "Bad request", status_code: int = 400,
                 model: str = "", provider: str = ""):
        self.status_code = status_code
        self.model = model
        self.provider = provider
        super().__init__(message)


class BudgetExceededError(LLMClientError):
    """Budget limit reached — pause or downgrade required."""
    def __init__(self, message: str = "Budget exceeded",
                 spent: float = 0.0, limit: float = 0.0,
                 project_id: str = ""):
        self.spent = spent
        self.limit = limit
        self.project_id = project_id
        super().__init__(message)


class ProviderUnavailableError(LLMClientError):
    """Provider returned 5xx or timed out — eligible for fallback."""
    def __init__(self, message: str = "Provider unavailable",
                 provider: str = "", status_code: int = 503):
        self.provider = provider
        self.status_code = status_code
        super().__init__(message)


class RateLimitError(LLMClientError):
    """Provider rate limit hit (429) — retry after backoff."""
    def __init__(self, message: str = "Rate limited",
                 retry_after: float = 0.0, provider: str = ""):
        self.retry_after = retry_after
        self.provider = provider
        super().__init__(message)


__all__ = [
    "UnifiedLLMClient",
    "LLMClientError",
    "BadRequestError",
    "BudgetExceededError",
    "ProviderUnavailableError",
    "RateLimitError",
]
