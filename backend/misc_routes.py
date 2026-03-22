"""
ORION Digital — Misc Routes Blueprint
"""
from flask import Blueprint, request, jsonify, Response, stream_with_context
import json
import time
import os
import logging
import threading
from datetime import datetime, timezone

logger = logging.getLogger(__name__)
import requests as http_requests
import re

# Import shared state and helpers
from shared import (
    app, db_read, db_write, require_auth, require_admin,
    _now_iso, _calc_cost, _get_memory, _get_versions, _get_rate_limiter,
    _encrypt_setting, _decrypt_setting, _SECRET_SETTINGS_KEYS,
    _running_tasks, _tasks_lock, _interrupt_lock, _active_agents, _agents_lock,
    OPENROUTER_API_KEY, OPENROUTER_BASE_URL, DATA_DIR, UPLOAD_DIR,
    _lock, _USE_SQLITE,
    CHAT_MODELS, MODEL_CONFIGS,
)

from file_versioning import get_version_store
from rate_limiter import get_rate_limiter, ToolContracts
from model_router import select_model, classify_complexity, get_cost_analytics
from specialized_agents import SPECIALIZED_AGENTS, select_agents_for_task, get_agent_pipeline, get_all_agents
import secrets

try:
    from project_memory import ProjectMemory
except ImportError:
    ProjectMemory = None

misc_bp = Blueprint("misc", __name__)


@misc_bp.route("/api/versions/files", methods=["GET"])
@require_auth
def list_versioned_files():
    """List all versioned files."""
    host = request.args.get("host", None)
    try:
        store = _get_versions()
        files = store.get_all_files(host=host)
        return jsonify({"files": files})
    except Exception as e:
        return jsonify({"error": str(e)}), 500



@misc_bp.route("/api/versions/history", methods=["GET"])
@require_auth
def file_version_history():
    """Get version history for a file."""
    host = request.args.get("host", "")
    path = request.args.get("path", "")
    if not host or not path:
        return jsonify({"error": "host and path required"}), 400

    try:
        store = _get_versions()
        history = store.get_history(host, path)
        return jsonify({"history": history})
    except Exception as e:
        return jsonify({"error": str(e)}), 500



@misc_bp.route("/api/versions/diff", methods=["GET"])
@require_auth
def file_version_diff():
    """Get diff between two versions."""
    host = request.args.get("host", "")
    path = request.args.get("path", "")
    v_from = int(request.args.get("from", 0))
    v_to = int(request.args.get("to", 0))

    if not host or not path or not v_from or not v_to:
        return jsonify({"error": "host, path, from, to required"}), 400

    try:
        store = _get_versions()
        diff = store.get_diff(host, path, v_from, v_to)
        return jsonify({"diff": diff})
    except Exception as e:
        return jsonify({"error": str(e)}), 500



@misc_bp.route("/api/versions/rollback", methods=["POST"])
@require_auth
def file_version_rollback():
    """Rollback a file to a previous version."""
    data = request.get_json() or {}
    host = data.get("host", "")
    path = data.get("path", "")
    version = data.get("version", 0)

    if not host or not path or not version:
        return jsonify({"error": "host, path, version required"}), 400

    try:
        store = _get_versions()
        result = store.rollback(host, path, version)
        if result:
            return jsonify({"ok": True, "result": result})
        return jsonify({"error": "Version not found"}), 404
    except Exception as e:
        return jsonify({"error": str(e)}), 500



@misc_bp.route("/api/versions/stats", methods=["GET"])
@require_auth
def file_version_stats():
    """Get file versioning statistics."""
    try:
        store = _get_versions()
        return jsonify(store.get_stats())
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ── Rate Limiting API ──────────────────────────────────────────────

@misc_bp.route("/api/rate-limit/status", methods=["GET"])
@require_auth
def rate_limit_status():
    """Get current rate limit status for user."""
    rl = _get_rate_limiter()
    ip = request.remote_addr or "unknown"
    usage = rl.get_all_usage(user_id=request.user_id, ip=ip)
    return jsonify(usage)


# ── Generated Files ───────────────────────────────────────────────

@misc_bp.route("/api/health", methods=["GET"])
def health():
    # Get stats from new modules
    mem_stats = {}
    ver_stats = {}
    try:
        mem_stats = _get_memory().get_stats()
    except Exception as _mem_err:
        logging.warning(f"Memory stats error: {_mem_err}")
    try:
        ver_stats = _get_versions().get_stats()
    except Exception as _ver_err:
        logging.warning(f"Version stats error: {_ver_err}")

    return jsonify({
        "status": "ok",
        "version": "1.0",
        "name": "ORION Digital",
        "features": [
            "langgraph_stategraph", "retry_policy", "idempotency",
            "self_healing_2.0", "vector_memory", "file_versioning",
            "rate_limiting", "contracts", "cross_chat_learning",
            "ssh_executor", "file_manager", "browser_agent",
            "agent_loop", "multi_agent",
            "creative_suite", "edit_image", "generate_design",
            "web_search", "web_fetch", "code_interpreter",
            "canvas", "persistent_memory", "custom_agents",
            "drag_drop_upload", "message_actions", "markdown_tables"
        ],
        "memory": mem_stats,
        "versioning": ver_stats,
        "timestamp": datetime.now(timezone.utc).isoformat()
    })



@misc_bp.route("/api/models", methods=["GET"])
def list_models():
    """Public endpoint to list available model configurations."""
    return jsonify({
        "configs": {
            k: {
                "name": v["name"],
                "emoji": v["emoji"],
                "quality": v["quality"],
                "monthly_cost": v["monthly_cost"],
                "coding_model": v["coding"]["name"]
            } for k, v in MODEL_CONFIGS.items()
        },
        "chat_models": {
            k: {"name": v["name"], "lang": v["lang"]}
            for k, v in CHAT_MODELS.items()
        }
    })



@misc_bp.route("/api/agents/custom", methods=["GET"])
def list_custom_agents():
    """List custom agent configurations."""
    try:
        from project_manager import list_custom_agents as pm_list_agents
        user_id = request.args.get("user_id", "default")
        agents = pm_list_agents(user_id)
        return jsonify({"success": True, "agents": agents})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500



@misc_bp.route("/api/agents/custom", methods=["POST"])
def create_custom_agent():
    """Create a custom agent."""
    try:
        from project_manager import create_custom_agent as pm_create_agent
        data = request.get_json()
        name = data.get("name", "")
        user_id = data.get("user_id", "default")
        system_prompt = data.get("system_prompt", "")
        description = data.get("description", "")
        avatar = data.get("avatar", "")
        result = pm_create_agent(name, user_id, system_prompt, description=description, avatar=avatar)
        return jsonify(result)
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500



@misc_bp.route("/api/agents/custom/<agent_id>", methods=["DELETE"])
def delete_custom_agent(agent_id):
    """Delete a custom agent."""
    try:
        from project_manager import delete_custom_agent as pm_delete_agent
        result = pm_delete_agent(agent_id)
        return jsonify(result)
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500



@misc_bp.route("/api/templates", methods=["GET"])
def list_templates():
    """List available prompt templates."""
    templates = [
        {"id": "code_review", "name": "🔍 Code Review", "prompt": "Проанализируй код и найди проблемы, уязвимости и предложи улучшения:", "category": "dev"},
        {"id": "deploy", "name": "🚀 Deploy", "prompt": "Задеплой проект на сервер. Настрой nginx, SSL, systemd сервис:", "category": "dev"},
        {"id": "debug", "name": "🐛 Debug", "prompt": "Найди и исправь ошибку в коде/конфигурации:", "category": "dev"},
        {"id": "analyze_data", "name": "📊 Анализ данных", "prompt": "Проанализируй данные, построй графики и сделай выводы:", "category": "analytics"},
        {"id": "write_report", "name": "📝 Отчёт", "prompt": "Создай профессиональный отчёт с графиками и таблицами на тему:", "category": "analytics"},
        {"id": "research", "name": "🔍 Исследование", "prompt": "Проведи исследование в интернете и подготовь сводку с источниками:", "category": "analytics"},
        {"id": "create_landing", "name": "🌐 Лендинг", "prompt": "Создай красивый лендинг с анимациями для:", "category": "creative"},
        {"id": "create_design", "name": "🎨 Дизайн", "prompt": "Создай профессиональный дизайн (баннер/пост/визитка/лого):", "category": "creative"},
        {"id": "write_article", "name": "✍️ Статья", "prompt": "Напиши профессиональную статью на тему:", "category": "creative"},
        {"id": "server_audit", "name": "🛡️ Аудит сервера", "prompt": "Проведи аудит безопасности сервера и исправь проблемы:", "category": "devops"},
        {"id": "setup_ci_cd", "name": "⚙️ CI/CD", "prompt": "Настрой CI/CD пайплайн для проекта:", "category": "devops"},
        {"id": "monitoring", "name": "📊 Мониторинг", "prompt": "Настрой мониторинг сервера и приложения:", "category": "devops"}
    ]
    category = request.args.get("category")
    if category:
        templates = [t for t in templates if t["category"] == category]
    return jsonify({"success": True, "templates": templates})



@misc_bp.route("/api/connectors", methods=["GET"])
def list_connectors():
    """List available integration connectors."""
    connectors = [
        {
            "id": "github",
            "name": "GitHub",
            "icon": "fab fa-github",
            "description": "Управление репозиториями, PR, issues",
            "status": "available",
            "auth_type": "oauth",
            "scopes": ["repo", "read:user", "read:org"]
        },
        {
            "id": "gmail",
            "name": "Gmail",
            "icon": "fas fa-envelope",
            "description": "Чтение и отправка email",
            "status": "available",
            "auth_type": "oauth",
            "scopes": ["gmail.readonly", "gmail.send"]
        },
        {
            "id": "google_calendar",
            "name": "Google Calendar",
            "icon": "fas fa-calendar",
            "description": "Управление событиями и расписанием",
            "status": "available",
            "auth_type": "oauth",
            "scopes": ["calendar.readonly", "calendar.events"]
        },
        {
            "id": "google_drive",
            "name": "Google Drive",
            "icon": "fab fa-google-drive",
            "description": "Доступ к файлам и документам",
            "status": "available",
            "auth_type": "oauth",
            "scopes": ["drive.readonly", "drive.file"]
        },
        {
            "id": "slack",
            "name": "Slack",
            "icon": "fab fa-slack",
            "description": "Интеграция с каналами и сообщениями",
            "status": "available",
            "auth_type": "oauth",
            "scopes": ["channels:read", "chat:write"]
        },
        {
            "id": "notion",
            "name": "Notion",
            "icon": "fas fa-book",
            "description": "Доступ к базам данных и страницам Notion",
            "status": "available",
            "auth_type": "oauth",
            "scopes": ["read_content", "update_content"]
        },
        {
            "id": "jira",
            "name": "Jira",
            "icon": "fab fa-jira",
            "description": "Управление задачами и проектами",
            "status": "available",
            "auth_type": "oauth",
            "scopes": ["read:jira-work", "write:jira-work"]
        }
    ]
    return jsonify({"success": True, "connectors": connectors})



@misc_bp.route("/api/connectors/<connector_id>/connect", methods=["POST"])
@require_auth
def connect_connector(connector_id):
    """Initiate OAuth connection for a connector."""
    try:
        db = _load_db()
        user_id = request.get_json().get("user_id", "default")
        connections = db.setdefault("connections", {})
        connections[f"{user_id}:{connector_id}"] = {
            "connector_id": connector_id,
            "user_id": user_id,
            "status": "connected",
            "connected_at": datetime.now(timezone.utc).isoformat()
        }
        _save_db(db)
        return jsonify({"success": True, "status": "connected"})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500



@misc_bp.route("/api/connectors/<connector_id>/disconnect", methods=["POST"])
@require_auth
def disconnect_connector(connector_id):
    """Disconnect/revoke a connector."""
    try:
        db = _load_db()
        user_id = request.get_json().get("user_id", "default")
        connections = db.get("connections", {})
        key = f"{user_id}:{connector_id}"
        if key in connections:
            del connections[key]
            _save_db(db)
        return jsonify({"success": True, "status": "disconnected"})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500



@misc_bp.route("/api/connectors/<connector_id>", methods=["POST"])
@require_auth
def toggle_connector(connector_id):
    """Toggle connector enabled/disabled."""
    try:
        data = request.get_json() or {}
        enabled = data.get("enabled", True)
        db = _load_db()
        connector_states = db.setdefault("connector_states", {})
        connector_states[connector_id] = {"enabled": enabled, "updated_at": datetime.now(timezone.utc).isoformat()}
        _save_db(db)
        return jsonify({"success": True, "connector_id": connector_id, "enabled": enabled})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500



@misc_bp.route("/api/agents", methods=["GET"])
@require_auth
def list_agents():
    """List all agents (system + custom)."""
    db = _load_db()
    custom_agents = db.get("custom_agents", [])
    system_agents = [
        {"id": "architect", "name": "Architect", "avatar": "\ud83c\udfd7\ufe0f", "description": "\u041f\u043b\u0430\u043d\u0438\u0440\u043e\u0432\u0430\u043d\u0438\u0435 \u0430\u0440\u0445\u0438\u0442\u0435\u043a\u0442\u0443\u0440\u044b", "system": True, "tools": "Plan, Research, Files"},
        {"id": "coder", "name": "Coder", "avatar": "\ud83d\udcbb", "description": "\u041d\u0430\u043f\u0438\u0441\u0430\u043d\u0438\u0435 \u043a\u043e\u0434\u0430", "system": True, "tools": "Code, SSH, Web"},
        {"id": "reviewer", "name": "Reviewer", "avatar": "\ud83d\udd0d", "description": "\u041f\u0440\u043e\u0432\u0435\u0440\u043a\u0430 \u043a\u043e\u0434\u0430", "system": True, "tools": "Review, Security, Metrics"},
        {"id": "qa", "name": "QA", "avatar": "\u2705", "description": "\u0422\u0435\u0441\u0442\u0438\u0440\u043e\u0432\u0430\u043d\u0438\u0435", "system": True, "tools": "Test, Report, Retry"}
    ]
    return jsonify({"success": True, "agents": system_agents + custom_agents})



@misc_bp.route("/api/agents", methods=["POST"])
@require_auth
def create_agent():
    """Create a custom agent."""
    try:
        data = request.get_json() or {}
        agent = {
            "id": f"custom_{datetime.now().strftime('%Y%m%d%H%M%S')}_{os.urandom(4).hex()}",
            "name": data.get("name", "Custom Agent"),
            "description": data.get("description", ""),
            "system_prompt": data.get("system_prompt", ""),
            "avatar": data.get("avatar", "\ud83e\udd16"),
            "tools": data.get("tools", []),
            "system": False,
            "created_at": datetime.now(timezone.utc).isoformat()
        }
        db = _load_db()
        db.setdefault("custom_agents", []).append(agent)
        _save_db(db)
        return jsonify({"success": True, "agent": agent}), 201
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500



@misc_bp.route("/api/agents/<agent_id>", methods=["DELETE"])
@require_auth
def delete_agent(agent_id):
    """Delete a custom agent."""
    try:
        db = _load_db()
        agents = db.get("custom_agents", [])
        db["custom_agents"] = [a for a in agents if a.get("id") != agent_id]
        _save_db(db)
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500



@misc_bp.route("/api/model-router/classify", methods=["POST"])
@require_auth
def classify_query_complexity():
    """Classify query complexity for debugging/testing."""
    try:
        data = request.get_json() or {}
        query = data.get("query", "")
        result = select_model(query)
        return jsonify({"success": True, "result": result})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500



@misc_bp.route("/api/specialized-agents", methods=["GET"])
@require_auth
def get_specialized_agents_list():
    """Get list of all 6 specialized agents."""
    agents = get_all_agents()
    return jsonify({"success": True, "agents": agents, "count": len(agents)})



@misc_bp.route("/api/specialized-agents/select", methods=["POST"])
@require_auth
def select_agents_api():
    """Select best agents for a task."""
    data = request.get_json() or {}
    query = data.get("query", "")
    mode = data.get("mode", "chat")
    max_agents = data.get("max_agents", 3)
    agents = select_agents_for_task(query, mode, max_agents=max_agents)
    return jsonify({"success": True, "agents": agents})



@misc_bp.route("/api/specialized-agents/pipelines", methods=["GET"])
@require_auth
def get_agent_pipelines():
    """Get predefined agent pipelines."""
    pipelines = {}
    for ptype in ["deploy", "website", "api", "full_project"]:
        pipelines[ptype] = get_agent_pipeline(ptype)
    return jsonify({"success": True, "pipelines": pipelines})



@misc_bp.route("/api/modes", methods=["GET"])
def get_modes():
    """Список режимов работы ORION (fast / premium / ...)."""
    try:
        from model_router import list_modes, list_models
        return jsonify({
            "success": True,
            "modes": list_modes(),
            "models": list_models(),
            "default": "standard"
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500



@misc_bp.route("/api/intent/clarify", methods=["POST"])
@require_auth
def api_clarify_intent():
    """Анализ intent запроса пользователя."""
    try:
        from intent_clarifier import clarify, format_clarification_for_user
        data = request.get_json() or {}
        message = data.get("message", "")
        orion_mode = data.get("mode", "fast")
        history = data.get("history", [])
        result = clarify(message, history=history, orion_mode=orion_mode)
        result["label"] = format_clarification_for_user(result)
        return jsonify({"success": True, "intent": result})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500



@misc_bp.route("/api/cost/session", methods=["GET"])
@require_auth
def get_session_cost():
    """Стоимость текущей сессии."""
    try:
        from model_router import get_cost_analytics, check_cost_limit
        session_id = request.args.get("session_id", request.user_id)
        orion_mode = request.args.get("mode", "fast")
        cost_check = check_cost_limit(session_id, orion_mode)
        analytics = get_cost_analytics(user_id=request.user_id, days=1)
        return jsonify({
            "success": True,
            "session": cost_check,
            "analytics": analytics
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500



@misc_bp.route("/api/agent-zones", methods=["GET"])
def get_agent_zones():
    """Зоны ответственности агентов."""
    try:
        from agent_loop import AGENT_ZONES
        return jsonify({"success": True, "zones": AGENT_ZONES})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500



@misc_bp.route("/api/estimate", methods=["POST"])
def estimate_task():
    """
    Автосмета задачи.
    Принимает: {"task": "Создай лендинг для стоматологии"}
    Возвращает: {"estimate": {...}, "breakdown": [...], "total_hours": N, "total_rub": N}
    """
    data = request.get_json()
    task = data.get("task", "")
    if not task:
        return jsonify({"error": "task required"}), 400

    task_lower = task.lower()

    # Определяем тип задачи по ключевым словам
    detected_types = []

    type_keywords = {
        "landing": ["лендинг", "landing", "одностраничн", "посадочн"],
        "corporate": ["корпоративн", "сайт компании", "многостраничн", "портфолио"],
        "ecommerce": ["магазин", "каталог", "корзин", "товар", "ecommerce", "shop"],
        "integration": ["интеграц", "crm", "битрикс", "bitrix", "amocrm", "webhook", "api подключ"],
        "deploy": ["деплой", "deploy", "сервер", "nginx", "ssl", "домен", "перенес", "миграц"],
        "seo": ["seo", "мета-тег", "sitemap", "robots", "оптимизац", "ключевые слова"],
        "design": ["дизайн", "макет", "ui", "ux", "figma", "баннер"],
        "bot": ["бот", "bot", "telegram", "whatsapp", "чат-бот"],
    }

    for type_key, keywords in type_keywords.items():
        for kw in keywords:
            if kw in task_lower:
                if type_key not in detected_types:
                    detected_types.append(type_key)
                break

    if not detected_types:
        detected_types = ["custom"]

    # Считаем смету
    breakdown = []
    total_hours = 0
    total_rub = 0

    for t in detected_types:
        rate = ESTIMATE_RATES[t]
        item_cost = rate["hours"] * rate["rate_rub"]
        breakdown.append({
            "type": t,
            "description": rate["description"],
            "hours": rate["hours"],
            "rate_per_hour": rate["rate_rub"],
            "cost": item_cost
        })
        total_hours += rate["hours"]
        total_rub += item_cost

    # LLM уточнение (если доступен)
    llm_comment = ""
    try:
        if OPENROUTER_API_KEY:
            resp = http_requests.post(
                OPENROUTER_BASE_URL,
                headers={
                    "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                    "Content-Type": "application/json"
                },
                json={
                    "model": "openai/gpt-5.4-mini",  # PATCH fix2: real model ID
                    "messages": [
                        {"role": "system", "content": (
                            "Ты — менеджер проектов. Оцени задачу клиента и дай краткий комментарий к смете. "
                            "Укажи возможные риски и дополнительные работы. 2-3 предложения. Русский язык."
                        )},
                        {"role": "user", "content": f"Задача: {task}\nПредварительная смета: {total_hours}ч, {total_rub}₽\nСостав: {', '.join(t['description'] for t in breakdown)}"}
                    ],
                    "max_tokens": 200,
                    "temperature": 0.3
                },
                timeout=15
            )
            if resp.status_code == 200:
                llm_comment = resp.json().get("choices", [{}])[0].get("message", {}).get("content", "")
    except Exception:
        pass

    return jsonify({
        "success": True,
        "task": task,
        "detected_types": detected_types,
        "breakdown": breakdown,
        "total_hours": total_hours,
        "total_rub": total_rub,
        "llm_comment": llm_comment,
        "disclaimer": "Предварительная оценка. Точная стоимость зависит от деталей ТЗ."
    })
