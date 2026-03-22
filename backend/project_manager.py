"""
Project Manager — ORION Digital v1.0 Memory & Projects
=====================================================
Persistent memory, project workspaces, canvas, cross-project learning.
"""

import os
import json
import time
import uuid
import logging
import hashlib
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional

logger = logging.getLogger("project_manager")

DATA_DIR = os.environ.get("DATA_DIR", "/var/www/orion/backend/data")
PROJECTS_DIR = os.path.join(DATA_DIR, "projects")
os.makedirs(PROJECTS_DIR, exist_ok=True)

# ══════════════════════════════════════════════════════════════
# PROJECT WORKSPACE
# ══════════════════════════════════════════════════════════════

_projects_path = os.path.join(DATA_DIR, "projects.json")
_projects = {}


def _load_projects():
    global _projects
    try:
        if os.path.exists(_projects_path):
            with open(_projects_path, "r") as f:
                _projects = json.load(f)
    except Exception:
        _projects = {}


def _save_projects():
    try:
        with open(_projects_path, "w") as f:
            json.dump(_projects, f, indent=2, ensure_ascii=False)
    except Exception as e:
        logger.error(f"Failed to save projects: {e}")


def create_project(name: str, user_id: str, system_prompt: str = "",
                   description: str = "", tags: List[str] = None) -> Dict[str, Any]:
    """Create a new project workspace."""
    _load_projects()

    project_id = str(uuid.uuid4())[:12]
    project = {
        "id": project_id,
        "name": name,
        "description": description,
        "user_id": user_id,
        "system_prompt": system_prompt,
        "tags": tags or [],
        "threads": [],
        "files": [],
        "memory": [],
        "canvas": None,
        "settings": {
            "model_preference": None,
            "auto_memory": True,
            "memory_confidence_threshold": 0.7
        },
        "created_at": datetime.now(timezone.utc).isoformat(),
        "updated_at": datetime.now(timezone.utc).isoformat()
    }

    _projects[project_id] = project
    _save_projects()

    return {"success": True, "project": project}


def get_project(project_id: str) -> Optional[Dict]:
    _load_projects()
    return _projects.get(project_id)


def list_projects(user_id: str) -> List[Dict]:
    _load_projects()
    projects = [p for p in _projects.values() if p.get("user_id") == user_id]
    projects.sort(key=lambda x: x.get("updated_at", ""), reverse=True)
    return projects


def update_project(project_id: str, updates: Dict) -> Dict[str, Any]:
    _load_projects()
    if project_id not in _projects:
        return {"success": False, "error": "Project not found"}

    allowed = {"name", "description", "system_prompt", "tags", "settings"}
    for key in allowed:
        if key in updates:
            _projects[project_id][key] = updates[key]

    _projects[project_id]["updated_at"] = datetime.now(timezone.utc).isoformat()
    _save_projects()
    return {"success": True, "project": _projects[project_id]}


def delete_project(project_id: str) -> Dict[str, Any]:
    _load_projects()
    if project_id in _projects:
        del _projects[project_id]
        _save_projects()
        return {"success": True}
    return {"success": False, "error": "Project not found"}


def add_thread_to_project(project_id: str, chat_id: str) -> Dict[str, Any]:
    _load_projects()
    if project_id not in _projects:
        return {"success": False, "error": "Project not found"}

    if chat_id not in _projects[project_id]["threads"]:
        _projects[project_id]["threads"].append(chat_id)
        _projects[project_id]["updated_at"] = datetime.now(timezone.utc).isoformat()
        _save_projects()

    return {"success": True}


# ══════════════════════════════════════════════════════════════
# PERSISTENT MEMORY
# ══════════════════════════════════════════════════════════════

_memory_path = os.path.join(DATA_DIR, "persistent_memory.json")
_memory_items = {}


def _load_memory():
    global _memory_items
    try:
        if os.path.exists(_memory_path):
            with open(_memory_path, "r") as f:
                _memory_items = json.load(f)
    except Exception:
        _memory_items = {}


def _save_memory():
    try:
        with open(_memory_path, "w") as f:
            json.dump(_memory_items, f, indent=2, ensure_ascii=False)
    except Exception as e:
        logger.error(f"Failed to save memory: {e}")


def store_memory(key: str, value: str, user_id: str,
                 project_id: str = None, source: str = "auto",
                 confidence: float = 0.8, pinned: bool = False) -> Dict[str, Any]:
    """Store a memory item."""
    _load_memory()

    memory_id = hashlib.md5(f"{user_id}:{project_id or 'global'}:{key}".encode()).hexdigest()[:12]

    item = {
        "id": memory_id,
        "key": key,
        "value": value,
        "user_id": user_id,
        "project_id": project_id,
        "source": source,
        "confidence": confidence,
        "pinned": pinned,
        "access_count": 0,
        "last_accessed": None,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "updated_at": datetime.now(timezone.utc).isoformat()
    }

    _memory_items[memory_id] = item
    _save_memory()

    return {"success": True, "item": item}


def get_memory_items(user_id: str, project_id: str = None,
                     limit: int = 50) -> List[Dict]:
    """Get memory items for a user, optionally filtered by project."""
    _load_memory()

    items = [m for m in _memory_items.values() if m.get("user_id") == user_id]

    if project_id:
        # Include project-specific and global (no project_id) items
        items = [m for m in items
                 if m.get("project_id") == project_id or m.get("project_id") is None]
    else:
        # Only global items
        items = [m for m in items if m.get("project_id") is None]

    items.sort(key=lambda x: x.get("confidence", 0), reverse=True)
    return items[:limit]


def get_memory_for_prompt(user_id: str, project_id: str = None) -> str:
    """Get formatted memory for injection into system prompt."""
    items = get_memory_items(user_id, project_id, limit=20)

    if not items:
        return ""

    # Separate global and project memory
    global_items = [m for m in items if m.get("project_id") is None]
    project_items = [m for m in items if m.get("project_id") is not None]

    parts = []

    if global_items:
        parts.append("## Известно о пользователе")
        for item in global_items[:10]:
            parts.append(f"- {item['key']}: {item['value']}")

    if project_items:
        parts.append("\n## Контекст проекта")
        for item in project_items[:10]:
            parts.append(f"- {item['key']}: {item['value']}")

    return "\n".join(parts)


def update_memory(memory_id: str, value: str = None,
                  pinned: bool = None) -> Dict[str, Any]:
    """Update a memory item."""
    _load_memory()

    if memory_id not in _memory_items:
        return {"success": False, "error": "Memory item not found"}

    if value is not None:
        _memory_items[memory_id]["value"] = value
    if pinned is not None:
        _memory_items[memory_id]["pinned"] = pinned

    _memory_items[memory_id]["updated_at"] = datetime.now(timezone.utc).isoformat()
    _save_memory()

    return {"success": True, "item": _memory_items[memory_id]}


def delete_memory(memory_id: str) -> Dict[str, Any]:
    """Delete a memory item."""
    _load_memory()
    if memory_id in _memory_items:
        del _memory_items[memory_id]
        _save_memory()
        return {"success": True}
    return {"success": False, "error": "Memory item not found"}


def extract_memory_from_conversation(user_message: str, assistant_response: str,
                                     user_id: str, project_id: str = None,
                                     api_key: str = "", api_url: str = "") -> List[Dict]:
    """
    Extract key facts from conversation using LLM.
    Called after each assistant turn.
    """
    if not api_key:
        return []

    import requests as req

    try:
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

        extraction_prompt = """Extract key facts worth remembering about the user from this conversation.
Return a JSON array of objects: [{"key": "user_name", "value": "Alex", "confidence": 0.95}]

Rules:
- Only extract FACTS, not opinions or transient info
- Confidence 0.0-1.0 (only save >= 0.7)
- Valid keys: user_name, language, timezone, role, company, project_context, preference_language, preference_style, tool_preference, tech_stack, current_task
- Do NOT extract: full messages, secrets, passwords, file contents, temporary data
- Return empty array [] if nothing worth remembering

Conversation:
User: {user_msg}
Assistant: {assistant_msg}"""

        resp = req.post(
            api_url or "https://openrouter.ai/api/v1/chat/completions",
            headers=headers,
            json={
                "model": "openai/gpt-5.4-mini",  # PATCH fix: real model ID
                "messages": [
                    {"role": "user", "content": extraction_prompt.format(
                        user_msg=user_message[:500],
                        assistant_msg=assistant_response[:500]
                    )}
                ],
                "temperature": 0.1,
                "max_tokens": 500
            },
            timeout=15
        )

        if resp.status_code == 200:
            content = resp.json().get("choices", [{}])[0].get("message", {}).get("content", "")
            # Parse JSON from response - handle malformed LLM output
            import re
            # Strip markdown code fences if present
            content_clean = re.sub(r'```(?:json)?\s*', '', content).strip()
            # Try to find a JSON array
            json_match = re.search(r'\[.*?\]', content_clean, re.DOTALL)
            if not json_match:
                # LLM returned something other than array (e.g. just "key") - skip silently
                return []
            try:
                items = json.loads(json_match.group(0))
            except (json.JSONDecodeError, ValueError):
                # Fallback: try to extract JSON array from LLM response
                import re as _re
                _json_match = _re.search(r'\[\s*\{.*?\}\s*\]', raw_text, _re.DOTALL)
                if _json_match:
                    try:
                        items = json.loads(_json_match.group())
                    except (json.JSONDecodeError, ValueError):
                        logger.debug(f"Memory extraction: JSON fallback also failed")
                        return []
                else:
                    logger.debug(f"Memory extraction: no JSON array found in LLM response")
                    return []
            if not isinstance(items, list):
                return []
            stored = []
            for item in items:
                if not isinstance(item, dict) or "key" not in item or "value" not in item:
                    continue
                if item.get("confidence", 0) >= 0.7:
                    result = store_memory(
                        key=item["key"],
                        value=item["value"],
                        user_id=user_id,
                        project_id=project_id,
                        source="auto",
                        confidence=item.get("confidence", 0.8)
                    )
                    if result.get("success"):
                        stored.append(result["item"])
            return stored

    except Exception as e:
        logger.warning(f"Memory extraction failed: {e}")

    return []


def decay_old_memories(days_threshold: int = 30, decay_rate: float = 0.05):
    """Decay confidence of old, unused memory items."""
    _load_memory()
    now = time.time()
    changed = False

    for mid, item in list(_memory_items.items()):
        if item.get("pinned"):
            continue

        last_access = item.get("last_accessed")
        if last_access:
            try:
                last_ts = datetime.fromisoformat(last_access).timestamp()
                if now - last_ts > days_threshold * 86400:
                    item["confidence"] = max(0, item.get("confidence", 0.5) - decay_rate)
                    changed = True
            except Exception:
                pass

        # Delete if confidence too low
        if item.get("confidence", 0) < 0.2:
            del _memory_items[mid]
            changed = True

    if changed:
        _save_memory()


# ══════════════════════════════════════════════════════════════
# CANVAS
# ══════════════════════════════════════════════════════════════

_canvas_path = os.path.join(DATA_DIR, "canvas.json")
_canvases = {}


def _load_canvases():
    global _canvases
    try:
        if os.path.exists(_canvas_path):
            with open(_canvas_path, "r") as f:
                _canvases = json.load(f)
    except Exception:
        _canvases = {}


def _save_canvases():
    try:
        with open(_canvas_path, "w") as f:
            json.dump(_canvases, f, indent=2, ensure_ascii=False)
    except Exception as e:
        logger.error(f"Failed to save canvases: {e}")


def create_canvas(user_id: str, project_id: str = None,
                  title: str = "Untitled", content: str = "",
                  canvas_type: str = "text") -> Dict[str, Any]:
    """Create a new canvas (persistent editing panel)."""
    _load_canvases()

    canvas_id = str(uuid.uuid4())[:12]
    canvas = {
        "id": canvas_id,
        "user_id": user_id,
        "project_id": project_id,
        "title": title,
        "content": content,
        "type": canvas_type,  # text, code, html, markdown
        "versions": [{"content": content, "timestamp": datetime.now(timezone.utc).isoformat()}],
        "created_at": datetime.now(timezone.utc).isoformat(),
        "updated_at": datetime.now(timezone.utc).isoformat()
    }

    _canvases[canvas_id] = canvas
    _save_canvases()

    return {"success": True, "canvas": canvas}


def update_canvas(canvas_id: str, content: str, title: str = None) -> Dict[str, Any]:
    """Update canvas content with version history."""
    _load_canvases()

    if canvas_id not in _canvases:
        return {"success": False, "error": "Canvas not found"}

    canvas = _canvases[canvas_id]
    canvas["content"] = content
    if title:
        canvas["title"] = title

    # Add version
    canvas["versions"].append({
        "content": content,
        "timestamp": datetime.now(timezone.utc).isoformat()
    })
    # Keep only last 50 versions
    if len(canvas["versions"]) > 50:
        canvas["versions"] = canvas["versions"][-50:]

    canvas["updated_at"] = datetime.now(timezone.utc).isoformat()
    _save_canvases()

    return {"success": True, "canvas": canvas}


def get_canvas(canvas_id: str) -> Optional[Dict]:
    _load_canvases()
    return _canvases.get(canvas_id)


def list_canvases(user_id: str, project_id: str = None) -> List[Dict]:
    _load_canvases()
    canvases = [c for c in _canvases.values() if c.get("user_id") == user_id]
    if project_id:
        canvases = [c for c in canvases if c.get("project_id") == project_id]
    canvases.sort(key=lambda x: x.get("updated_at", ""), reverse=True)
    return canvases


def delete_canvas(canvas_id: str) -> Dict[str, Any]:
    _load_canvases()
    if canvas_id in _canvases:
        del _canvases[canvas_id]
        _save_canvases()
        return {"success": True}
    return {"success": False, "error": "Canvas not found"}


# ══════════════════════════════════════════════════════════════
# CUSTOM AGENTS (Phase 6)
# ══════════════════════════════════════════════════════════════

_agents_path = os.path.join(DATA_DIR, "custom_agents.json")
_custom_agents = {}


def _load_agents():
    global _custom_agents
    try:
        if os.path.exists(_agents_path):
            with open(_agents_path, "r") as f:
                _custom_agents = json.load(f)
    except Exception:
        _custom_agents = {}


def _save_agents():
    try:
        with open(_agents_path, "w") as f:
            json.dump(_custom_agents, f, indent=2, ensure_ascii=False)
    except Exception as e:
        logger.error(f"Failed to save agents: {e}")


def create_custom_agent(name: str, user_id: str, system_prompt: str,
                        description: str = "", avatar: str = "🤖",
                        tools: List[str] = None,
                        knowledge_files: List[str] = None) -> Dict[str, Any]:
    """Create a custom agent with specific instructions and tools."""
    _load_agents()

    agent_id = str(uuid.uuid4())[:12]
    agent = {
        "id": agent_id,
        "name": name,
        "description": description,
        "avatar": avatar,
        "user_id": user_id,
        "system_prompt": system_prompt,
        "tools": tools or [],
        "knowledge_files": knowledge_files or [],
        "usage_count": 0,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "updated_at": datetime.now(timezone.utc).isoformat()
    }

    _custom_agents[agent_id] = agent
    _save_agents()

    return {"success": True, "agent": agent}


def list_custom_agents(user_id: str) -> List[Dict]:
    _load_agents()
    agents = [a for a in _custom_agents.values() if a.get("user_id") == user_id]
    agents.sort(key=lambda x: x.get("usage_count", 0), reverse=True)
    return agents


def get_custom_agent(agent_id: str) -> Optional[Dict]:
    _load_agents()
    return _custom_agents.get(agent_id)


def delete_custom_agent(agent_id: str) -> Dict[str, Any]:
    _load_agents()
    if agent_id in _custom_agents:
        del _custom_agents[agent_id]
        _save_agents()
        return {"success": True}
    return {"success": False, "error": "Agent not found"}


# ══════════════════════════════════════════════════════════════
# TEMPLATES (Phase 6)
# ══════════════════════════════════════════════════════════════

PROMPT_TEMPLATES = [
    {
        "id": "data_analyst",
        "name": "📊 Аналитик данных",
        "description": "Анализ данных, визуализация, статистика",
        "system_prompt": "Ты — опытный аналитик данных. Анализируй данные, создавай визуализации, находи инсайты. Используй pandas, matplotlib, plotly. Всегда показывай код и результаты.",
        "tools": ["code_interpreter", "generate_chart", "generate_report"],
        "category": "analytics"
    },
    {
        "id": "code_reviewer",
        "name": "🔍 Code Reviewer",
        "description": "Ревью кода, поиск багов, оптимизация",
        "system_prompt": "Ты — Senior Code Reviewer. Проверяй код на: баги, уязвимости, производительность, читаемость, best practices. Давай конкретные рекомендации с примерами исправлений.",
        "tools": ["code_interpreter"],
        "category": "development"
    },
    {
        "id": "writer",
        "name": "✍️ Писатель",
        "description": "Статьи, документация, копирайтинг",
        "system_prompt": "Ты — профессиональный писатель и редактор. Пиши чистым, ясным языком. Структурируй тексты. Адаптируй стиль под задачу: техническая документация, маркетинговый текст, статья.",
        "tools": ["generate_report", "web_search"],
        "category": "writing"
    },
    {
        "id": "designer",
        "name": "🎨 Дизайнер",
        "description": "UI/UX, лендинги, визуальный контент",
        "system_prompt": "Ты — UI/UX дизайнер и frontend разработчик. Создавай красивые, современные интерфейсы. Используй градиенты, анимации, responsive дизайн. Генерируй HTML/CSS артефакты.",
        "tools": ["create_artifact", "generate_image", "generate_design"],
        "category": "design"
    },
    {
        "id": "devops",
        "name": "🔧 DevOps Engineer",
        "description": "Серверы, деплой, CI/CD, мониторинг",
        "system_prompt": "Ты — Senior DevOps Engineer. Настраивай серверы, деплой, CI/CD, мониторинг. Используй Docker, Nginx, systemd, GitHub Actions. Всегда думай о безопасности и отказоустойчивости.",
        "tools": ["ssh_execute", "code_interpreter"],
        "category": "infrastructure"
    },
    {
        "id": "researcher",
        "name": "🔬 Исследователь",
        "description": "Поиск информации, анализ, отчёты",
        "system_prompt": "Ты — исследователь-аналитик. Ищи информацию в интернете, анализируй источники, составляй структурированные отчёты с цитатами. Всегда указывай источники.",
        "tools": ["web_search", "web_fetch", "generate_report"],
        "category": "research"
    }
]


def get_templates(category: str = None) -> List[Dict]:
    """Get available prompt templates."""
    templates = PROMPT_TEMPLATES
    if category:
        templates = [t for t in templates if t.get("category") == category]
    return templates


# ══════════════════════════════════════════════════════════════
# OOP WRAPPERS (for compatibility with spec)
# ══════════════════════════════════════════════════════════════

class MemoryStore:
    """OOP wrapper around memory functions."""

    def store(self, user_id: str, key: str, value: str, category: str = "general",
              project_id: str = None) -> Dict[str, Any]:
        return store_memory(key, value, user_id, project_id, source=category)

    def recall(self, user_id: str, query: str = "", project_id: str = None) -> List[Dict]:
        items = get_memory_items(user_id, project_id)
        if query:
            q = query.lower()
            items = [i for i in items if q in i.get("key", "").lower() or q in i.get("value", "").lower()]
        return items

    def get_prompt_context(self, user_id: str, project_id: str = None) -> str:
        return get_memory_for_prompt(user_id, project_id)

    def delete(self, memory_id: str) -> Dict[str, Any]:
        return delete_memory(memory_id)


class CanvasManager:
    """OOP wrapper around canvas functions."""

    def create(self, user_id: str, title: str = "Untitled",
               canvas_type: str = "markdown", content: str = "",
               project_id: str = None) -> Dict[str, Any]:
        result = create_canvas(user_id, project_id, title, content, canvas_type)
        if result.get("success") and result.get("canvas"):
            result["canvas_id"] = result["canvas"]["id"]
        return result

    def get(self, canvas_id: str) -> Optional[Dict]:
        return get_canvas(canvas_id)

    def update(self, canvas_id: str, content: str, title: str = None) -> Dict[str, Any]:
        return update_canvas(canvas_id, content, title)

    def list(self, user_id: str, project_id: str = None) -> List[Dict]:
        return list_canvases(user_id, project_id)

    def delete(self, canvas_id: str) -> Dict[str, Any]:
        return delete_canvas(canvas_id)


class CustomAgentManager:
    """OOP wrapper around custom agent functions."""

    def create(self, user_id: str, name: str, system_prompt: str,
               category: str = "general", icon: str = "🤖",
               tools: List[str] = None) -> Dict[str, Any]:
        result = create_custom_agent(name, user_id, system_prompt, category, icon, tools)
        if result.get("success") and result.get("agent"):
            result["agent_id"] = result["agent"]["id"]
        return result

    def list(self, user_id: str) -> List[Dict]:
        return list_custom_agents(user_id)

    def get(self, agent_id: str) -> Optional[Dict]:
        return get_custom_agent(agent_id)

    def delete(self, agent_id: str) -> Dict[str, Any]:
        return delete_custom_agent(agent_id)


class TemplateManager:
    """OOP wrapper around template functions."""

    def list_templates(self, category: str = None) -> List[Dict]:
        return get_templates(category)

    def get_template(self, template_id: str) -> Optional[Dict]:
        templates = get_templates()
        for t in templates:
            if t.get("id") == template_id:
                return t
        return None
