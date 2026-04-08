"""
ARCANE 2 — Usage Tracker (stub)
================================
Minimal implementation to satisfy agent_loop.py imports.
Records LLM usage for cost tracking and observability.
Replace with full implementation backed by budget_controller.

Used by: core/agent_loop.py
"""

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Optional

logger = logging.getLogger("arcane2.usage_tracker")

# ── Singleton ────────────────────────────────────────────────────────────────

_instance: Optional["UsageTracker"] = None


def get_usage_tracker() -> "UsageTracker":
    """Get or create the global UsageTracker singleton."""
    global _instance
    if _instance is None:
        _instance = UsageTracker()
    return _instance


# ── Usage record ─────────────────────────────────────────────────────────────

@dataclass
class UsageRecord:
    model_id: str = ""
    provider: str = "openrouter"
    role: str = ""                 # classifier, coder, qa, etc.
    worker: str = ""               # intent, agent_loop, etc.
    input_tokens: int = 0
    output_tokens: int = 0
    cached_tokens: int = 0
    cost_usd: float = 0.0
    latency_ms: int = 0
    project_id: str = ""
    chat_id: str = ""
    run_id: str = ""
    timestamp: float = field(default_factory=time.time)
    metadata: dict[str, Any] = field(default_factory=dict)


# ── Tracker ──────────────────────────────────────────────────────────────────

class UsageTracker:
    """
    Accumulates LLM usage records in memory.
    
    In production, this should flush to budget_controller and/or a database.
    For now, it's an in-memory accumulator with a capped buffer.
    """

    def __init__(self, max_records: int = 10_000):
        self._records: list[UsageRecord] = []
        self._max_records = max_records
        self._total_cost: float = 0.0
        self._total_input_tokens: int = 0
        self._total_output_tokens: int = 0

    async def record(self, data: dict[str, Any] | UsageRecord) -> None:
        """Record a usage entry. Accepts dict or UsageRecord."""
        if isinstance(data, dict):
            rec = UsageRecord(**{k: v for k, v in data.items()
                                 if k in UsageRecord.__dataclass_fields__})
        else:
            rec = data

        self._total_cost += rec.cost_usd
        self._total_input_tokens += rec.input_tokens
        self._total_output_tokens += rec.output_tokens

        self._records.append(rec)

        # Cap buffer
        if len(self._records) > self._max_records:
            self._records = self._records[-self._max_records // 2:]

        logger.debug(
            f"Usage: {rec.model_id} | {rec.input_tokens}→{rec.output_tokens} tok | "
            f"${rec.cost_usd:.4f} | {rec.role}/{rec.worker}"
        )

    def get_total_cost(self, project_id: str = "") -> float:
        """Get total cost, optionally filtered by project."""
        if not project_id:
            return self._total_cost
        return sum(r.cost_usd for r in self._records if r.project_id == project_id)

    def get_records(self, limit: int = 100) -> list[UsageRecord]:
        """Get recent usage records."""
        return self._records[-limit:]

    def get_summary(self) -> dict[str, Any]:
        """Get usage summary."""
        return {
            "total_cost_usd": round(self._total_cost, 6),
            "total_input_tokens": self._total_input_tokens,
            "total_output_tokens": self._total_output_tokens,
            "total_records": len(self._records),
        }


__all__ = ["UsageTracker", "UsageRecord", "get_usage_tracker"]
