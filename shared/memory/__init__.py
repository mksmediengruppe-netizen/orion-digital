"""
ARCANE 2 — Compatibility shim: shared.memory → shared.memory_v9
================================================================
agent_loop.py imports from shared.memory.engine but the actual module
lives at shared/memory_v9/engine.py. This package shim bridges the gap.
"""

# Re-export everything from memory_v9
from shared.memory_v9 import *  # noqa: F401,F403
