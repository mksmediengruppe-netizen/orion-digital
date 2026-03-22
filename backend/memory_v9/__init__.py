"""
Super Agent Memory System v9.0 — Complete Memory Architecture
==============================================================
26 компонентов. 17 модулей. Полное покрытие.

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
  ├── tools.py             ← Tool definitions для agent (scratchpad, store, recall)
  └── engine.py            ← SuperMemoryEngine — объединяет ВСЁ

Установка:
  1. Скопировать папку memory_v9/ в backend/
  2. В agent_loop.py: from memory_v9 import SuperMemoryEngine
  3. Следовать INTEGRATION GUIDE в engine.py

Зависимости (опциональные, работает и без них):
  - sentence-transformers  (L3: нейросетевые эмбеддинги, pip install sentence-transformers)
  - qdrant-client          (уже установлен)
  - Pillow                 (уже установлен, для multimodal)
"""

from .engine import SuperMemoryEngine
from .config import MemoryConfig
from .tools import ALL_MEMORY_TOOLS, SCRATCHPAD_TOOL

__version__ = "9.0.0"
__all__ = ["SuperMemoryEngine", "MemoryConfig", "ALL_MEMORY_TOOLS", "SCRATCHPAD_TOOL"]
