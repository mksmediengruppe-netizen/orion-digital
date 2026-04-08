"""
Super Agent Memory System v9.1 — Complete Memory Architecture + Structured State
==================================================================================
26 компонентов. 18 модулей. Structured State интеграция.

Структура:
  memory_v9/
  ├── __init__.py          ← ТЫ ЗДЕСЬ. Единая точка входа.
  ├── config.py            ← Все настройки
  ├── working.py           ← L1: GoalAnchor, TaskPlanner, Scratchpad, Compaction
  ├── session.py           ← L2: Полная история в SQLite
  ├── semantic.py          ← L3: Нейросетевые эмбеддинги + Qdrant persistent
  ├── episodic.py          ← L4: Episodic Replay + Success Replay
  ├── profile.py           ← L5: User Profile + Adaptive Prompting
  ├── knowledge.py         ← L6: RAG Knowledge Base + Auto-Indexer
  ├── graph.py             ← Knowledge Graph (сущности + связи)
  ├── learning.py          ← Tool Learning + Error Patterns + Self-Reflection
  ├── temporal.py          ← Temporal Diff + State Snapshots
  ├── collaborative.py     ← Shared Memory + Privacy Layers
  ├── predictive.py        ← Predictive Pre-load + Context Budget
  ├── multimodal.py        ← Multi-modal Memory (скриншоты, images)
  ├── lifecycle.py         ← Decay, Consolidation, Conflict Resolution, Versioning
  ├── continuity.py        ← Conversation Continuity (прерванные задачи)
  ├── tools.py             ← Tool definitions для agent (scratchpad, store, recall, state)
  ├── structured_state.py  ← NEW: Structured State — JSON source of truth (§2.2)
  └── engine.py            ← SuperMemoryEngine — объединяет ВСЁ

v9.1 Changelog:
  - StructuredState: .arcane/state.json как source of truth
  - PROJECT.md генерируется автоматически из state.json
  - Релевантный срез state подаётся в каждый LLM-запрос
  - Новые tools: read_project_state, update_project_state, add_decision
  - LLM-extraction: решения/стек/personality извлекаются из разговоров
  - Запись runs в state при after_chat
"""

from .engine import SuperMemoryEngine
from .config import MemoryConfig
from .tools import ALL_MEMORY_TOOLS, SCRATCHPAD_TOOL, CORE_MEMORY_TOOLS, STATE_TOOLS
from .structured_state import StructuredState

__version__ = "9.1.0"
__all__ = [
    "SuperMemoryEngine", "MemoryConfig", "StructuredState",
    "ALL_MEMORY_TOOLS", "SCRATCHPAD_TOOL", "CORE_MEMORY_TOOLS", "STATE_TOOLS",
]
