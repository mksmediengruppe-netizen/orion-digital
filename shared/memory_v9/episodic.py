"""
ARCANE Memory v9 — Episodic Memory (stub)
L4: Episodic Replay. Core EpisodicReplay is in learning.py.
This file provides the extended EpisodicMemory interface.
"""
from __future__ import annotations
import logging
logger = logging.getLogger("memory.episodic")


class EpisodicMemory:
    """L4: Episodic Memory store. Full implementation pending."""

    def store(self, episode: dict) -> None:
        """Store a task episode."""
        pass  # TODO: Qdrant vector storage

    def recall(self, query: str, top_k: int = 5) -> list[dict]:
        """Recall similar past episodes by semantic similarity."""
        return []

    def get_success_patterns(self, task_type: str) -> list[dict]:
        """Get successful patterns for a task type."""
        return []
