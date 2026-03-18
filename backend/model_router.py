"""
Model Router — ORION Digital v2.0
==================================
3 модели × 4 режима (Turbo/Pro × Обычное/Премиум).

Модели:
  deepseek → worker  (код, SSH, DevOps, интеграции)
  gemini   → designer (HTML/CSS, UI/UX, SVG)
  sonnet   → brain   (общение, планирование, code review)

Режимы:
  turbo_standard  — DeepSeek везде, Gemini для дизайна
  turbo_premium   — Sonnet для общения, DeepSeek для работы
  pro_standard    — Sonnet для оркестрации + code review
  pro_premium     — Sonnet везде где нужен мозг
"""

import os
import re
import json
import time
import logging
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional

logger = logging.getLogger("model_router")

# ══════════════════════════════════════════════════════════════
# 3 МОДЕЛИ
# ══════════════════════════════════════════════════════════════

MODELS = {
    "deepseek": {
        "id": "openai/gpt-4.1-nano",
        "name": "DeepSeek V3.2",
        "input_price": 0.27,
        "output_price": 0.38,
        "role": "worker",
        "description": "Код, SSH, DevOps, интеграции — быстро и дёшево",
        "max_tokens": 32000
    },
    "gemini": {
        "id": "google/gemini-2.5-pro",
        "name": "Gemini 2.5 Pro",
        "input_price": 1.25,
        "output_price": 10.00,
        "role": "designer",
        "description": "HTML/CSS, UI/UX, SVG, дизайн — визуальное мышление",
        "max_tokens": 65536
    },
    "sonnet": {
        "id": "anthropic/claude-sonnet-4.6",
        "name": "Claude Sonnet 4.6",
        "input_price": 3.00,
        "output_price": 15.00,
        "role": "brain",
        "description": "Общение, планирование, code review — стратегическое мышление",
        "max_tokens": 64000
    },
    "opus": {
        "id": "anthropic/claude-opus-4",
        "name": "Claude Opus 4",
        "input_price": 15.00,
        "output_price": 75.00,
        "role": "architect",
        "description": "Архитектура, глубокий анализ, аудит кода — для самых сложных задач",
        "max_tokens": 32000
    }
}

# ══════════════════════════════════════════════════════════════
# 4 РЕЖИМА
# ══════════════════════════════════════════════════════════════

MODES = {
    "turbo_standard": {
        "label": "Turbo Обычный",
        "description": "Быстро и дёшево. DeepSeek везде, Gemini для дизайна.",
        "max_cost_usd": 2.0,
        "agents": {
            "intent_clarifier": "deepseek",
            "orchestrator":     "deepseek",
            "designer":         "gemini",    # ВСЕГДА Gemini
            "developer":        "deepseek",
            "devops":           "deepseek",
            "integrator":       "deepseek",
            "tester":           "deepseek",
            "analyst":          "deepseek",
            "code_reviewer":    None          # нет в Turbo
        }
    },
    "turbo_premium": {
        "label": "Turbo Премиум",
        "description": "Быстро с умным общением. Sonnet для диалога, DeepSeek для работы.",
        "max_cost_usd": 2.0,
        "agents": {
            "intent_clarifier": "sonnet",    # Премиум общение
            "orchestrator":     "deepseek",
            "designer":         "gemini",
            "developer":        "deepseek",
            "devops":           "deepseek",
            "integrator":       "deepseek",
            "tester":           "deepseek",
            "analyst":          "deepseek",
            "code_reviewer":    None
        }
    },
    "pro_standard": {
        "label": "Pro Обычный",
        "description": "Профессиональное планирование. Sonnet для оркестрации и code review.",
        "max_cost_usd": 10.0,
        "agents": {
            "intent_clarifier": "deepseek",
            "orchestrator":     "sonnet",    # Pro планирование
            "designer":         "gemini",
            "developer":        "deepseek",
            "devops":           "deepseek",
            "integrator":       "deepseek",
            "tester":           "deepseek",
            "analyst":          "deepseek",
            "code_reviewer":    "sonnet"     # Pro code review
        }
    },
    "pro_premium": {
        "label": "Pro Премиум",
        "description": "Максимальное качество. Sonnet везде где нужен мозг.",
        "max_cost_usd": 10.0,
        "agents": {
            "intent_clarifier": "sonnet",
            "orchestrator":     "sonnet",
            "designer":         "gemini",
            "developer":        "deepseek",
            "devops":           "deepseek",
            "integrator":       "deepseek",
            "tester":           "deepseek",
            "analyst":          "sonnet",    # Глубокий анализ
            "code_reviewer":    "sonnet"
        }
    },
    "architect": {
        "label": "Architect",
        "description": "Claude Opus для сложных задач. Архитектура, аудит, ТЗ.",
        "max_cost_usd": 20.0,
        "agents": {
            "intent_clarifier": "opus",
            "orchestrator":     "opus",
            "designer":         "gemini",
            "developer":        "deepseek",
            "devops":           "deepseek",
            "integrator":       "deepseek",
            "tester":           "deepseek",
            "analyst":          "opus",
            "code_reviewer":    "opus"
        }
    }
}

# Режим по умолчанию
DEFAULT_MODE = "turbo_standard"

# ══════════════════════════════════════════════════════════════
# COST TRACKING
# ══════════════════════════════════════════════════════════════

_data_dir = os.environ.get("DATA_DIR", "/var/www/orion/backend/data")
_cost_log_path = os.path.join(_data_dir, "cost_log.json")
_cost_log: List[Dict] = []

# Сессионные счётчики стоимости: {session_id: float}
_session_costs: Dict[str, float] = {}


# ══════════════════════════════════════════════════════════════
# ОСНОВНЫЕ ФУНКЦИИ
# ══════════════════════════════════════════════════════════════

def get_model_for_agent(agent_role: str, mode: str = DEFAULT_MODE) -> Dict[str, Any]:
    """
    Получить конфигурацию модели для агента в заданном режиме.

    Args:
        agent_role: Роль агента (orchestrator, designer, developer, ...)
        mode: Режим работы (turbo_standard, turbo_premium, pro_standard, pro_premium)

    Returns:
        Dict с полями: model_key, model_id, model_name, input_price, output_price, max_tokens
    """
    mode_config = MODES.get(mode, MODES[DEFAULT_MODE])
    agents_map = mode_config["agents"]

    model_key = agents_map.get(agent_role)

    # Если агент не назначен в этом режиме (например code_reviewer в Turbo)
    if model_key is None:
        logger.debug(f"Agent '{agent_role}' not active in mode '{mode}', using deepseek fallback")
        model_key = "deepseek"

    model_cfg = MODELS[model_key].copy()
    model_cfg["model_key"] = model_key
    model_cfg["model_id"] = model_cfg["id"]
    model_cfg["model_name"] = model_cfg["name"]
    model_cfg["mode"] = mode
    model_cfg["agent_role"] = agent_role

    return model_cfg


def get_model_id(agent_role: str, mode: str = DEFAULT_MODE) -> str:
    """Быстро получить model_id для агента."""
    return get_model_for_agent(agent_role, mode)["id"]


def get_mode_config(mode: str = DEFAULT_MODE) -> Dict[str, Any]:
    """Получить полную конфигурацию режима."""
    return MODES.get(mode, MODES[DEFAULT_MODE])


def get_max_cost(mode: str = DEFAULT_MODE) -> float:
    """Получить лимит стоимости для режима."""
    return MODES.get(mode, MODES[DEFAULT_MODE]).get("max_cost_usd", 2.0)


def list_modes() -> List[Dict[str, Any]]:
    """Список всех режимов для UI."""
    result = []
    for mode_key, mode_cfg in MODES.items():
        result.append({
            "key": mode_key,
            "label": mode_cfg["label"],
            "description": mode_cfg["description"],
            "max_cost_usd": mode_cfg["max_cost_usd"],
            "agents": {
                role: (MODELS[m]["name"] if m else "—")
                for role, m in mode_cfg["agents"].items()
            }
        })
    return result


def list_models() -> List[Dict[str, Any]]:
    """Список всех моделей для UI."""
    return [
        {
            "key": k,
            "id": v["id"],
            "name": v["name"],
            "role": v["role"],
            "description": v["description"],
            "input_price": v["input_price"],
            "output_price": v["output_price"]
        }
        for k, v in MODELS.items()
    ]


# ══════════════════════════════════════════════════════════════
# COMPLEXITY CLASSIFIER (упрощённый, для совместимости)
# ══════════════════════════════════════════════════════════════

def classify_complexity(query: str, history: List[Dict] = None) -> int:
    """
    Классифицировать сложность запроса (1-5).
    Используется для логирования и аналитики.
    """
    query_lower = query.lower()
    word_count = len(query.split())
    score = 2

    if word_count < 5:
        score -= 1
    elif word_count > 50:
        score += 1
    elif word_count > 150:
        score += 2

    simple_patterns = [
        r"^(привет|hello|hi|hey|здравствуй|добрый)",
        r"^(спасибо|thanks|thank you|благодар)",
        r"^(да|нет|yes|no|ok|ок|хорошо)$",
    ]
    for pattern in simple_patterns:
        if re.search(pattern, query_lower):
            score = max(1, score - 1)

    complex_patterns = [
        r"(архитектур|architecture|design pattern)",
        r"(проект|project|приложение|application|систем|system)",
        r"(анализ|analyze|исследу|research|оптимиз|optimize)",
        r"(план|plan|стратеги|strategy|roadmap)",
        r"(рефактор|refactor|переписа|rewrite)",
        r"(деплой|deploy|настрой сервер|configure server)",
    ]
    for pattern in complex_patterns:
        if re.search(pattern, query_lower):
            score = max(4, score)

    if history and len(history) > 5:
        score = min(5, score + 1)

    return max(1, min(5, score))


def select_model(query: str, variant: str = "standard",
                 history: List[Dict] = None,
                 preferred_model: str = None,
                 mode: str = DEFAULT_MODE) -> Dict[str, Any]:
    """
    Обратная совместимость с agent_loop.py.
    Возвращает модель для оркестратора в заданном режиме.
    """
    agent_role = "orchestrator"
    if preferred_model:
        # Найти ключ модели по ID
        for key, cfg in MODELS.items():
            if cfg["id"] == preferred_model or key == preferred_model:
                m = MODELS[key].copy()
                m["model_id"] = m["id"]
                m["model_name"] = m["name"]
                m["model_key"] = key
                m["tier"] = key
                m["complexity"] = classify_complexity(query, history)
                m["fallback_chain"] = _get_fallback_chain(key)
                return m

    result = get_model_for_agent(agent_role, mode)
    result["tier"] = result.get("model_key", "deepseek")
    result["complexity"] = classify_complexity(query, history)
    result["fallback_chain"] = _get_fallback_chain(result.get("model_key", "deepseek"))
    return result


def _get_fallback_chain(model_key: str) -> List[str]:
    """Цепочка fallback моделей."""
    chains = {
        "sonnet":   ["anthropic/claude-sonnet-4.6", "google/gemini-2.5-pro", "openai/gpt-4.1-mini"],
        "gemini":   ["google/gemini-2.5-pro", "anthropic/claude-sonnet-4.6", "openai/gpt-4.1-mini"],
        "deepseek": ["openai/gpt-4.1-mini", "google/gemini-2.5-pro", "anthropic/claude-sonnet-4.6"],
    }
    return chains.get(model_key, chains["deepseek"])


def get_fallback_model(current_model: str, tier: str = "deepseek") -> Optional[str]:
    """Получить следующую fallback модель."""
    chain = _get_fallback_chain(tier)
    try:
        idx = chain.index(current_model)
        if idx + 1 < len(chain):
            return chain[idx + 1]
    except ValueError:
        pass
    return MODELS["deepseek"]["id"]


# ══════════════════════════════════════════════════════════════
# COST TRACKING
# ══════════════════════════════════════════════════════════════

def check_cost_limit(session_id: str, mode: str = DEFAULT_MODE) -> Dict[str, Any]:
    """
    Проверить не превышен ли лимит стоимости сессии.

    Returns:
        {"allowed": bool, "current_cost": float, "max_cost": float, "remaining": float}
    """
    current = _session_costs.get(session_id, 0.0)
    max_cost = get_max_cost(mode)
    remaining = max(0.0, max_cost - current)
    allowed = current < max_cost

    return {
        "allowed": allowed,
        "current_cost": round(current, 4),
        "max_cost": max_cost,
        "remaining": round(remaining, 4),
        "mode": mode
    }


def add_session_cost(session_id: str, cost_usd: float):
    """Добавить стоимость к сессии."""
    _session_costs[session_id] = _session_costs.get(session_id, 0.0) + cost_usd


def reset_session_cost(session_id: str):
    """Сбросить счётчик стоимости сессии."""
    _session_costs.pop(session_id, None)


def log_cost(user_id: str, model_id: str, tokens_in: int, tokens_out: int,
             cost_usd: float, tier: str = "deepseek", complexity: int = 2,
             tool_name: str = None, success: bool = True,
             session_id: str = None, mode: str = DEFAULT_MODE,
             agent_role: str = None):
    """Логировать стоимость запроса."""
    global _cost_log

    entry = {
        "user_id": user_id,
        "session_id": session_id,
        "model_id": model_id,
        "tokens_in": tokens_in,
        "tokens_out": tokens_out,
        "cost_usd": cost_usd,
        "tier": tier,
        "complexity": complexity,
        "tool_name": tool_name,
        "success": success,
        "mode": mode,
        "agent_role": agent_role,
        "timestamp": datetime.now(timezone.utc).isoformat()
    }

    _cost_log.append(entry)

    # Обновить сессионный счётчик
    if session_id:
        add_session_cost(session_id, cost_usd)

    # Сохранять каждые 10 записей
    if len(_cost_log) % 10 == 0:
        _save_cost_log()


def get_cost_analytics(user_id: str = None, days: int = 30) -> Dict[str, Any]:
    """Аналитика стоимости для дашборда."""
    _load_cost_log()

    entries = _cost_log
    if user_id:
        entries = [e for e in entries if e.get("user_id") == user_id]

    cutoff = datetime.now(timezone.utc).timestamp() - days * 86400
    entries = [e for e in entries if _parse_ts(e.get("timestamp", "")) > cutoff]

    if not entries:
        return {
            "total_cost": 0, "total_requests": 0,
            "by_model": {}, "by_mode": {}, "by_agent": {}
        }

    total_cost = sum(e.get("cost_usd", 0) for e in entries)
    total_requests = len(entries)

    by_model = {}
    for e in entries:
        m = e.get("model_id", "unknown")
        if m not in by_model:
            by_model[m] = {"cost": 0, "requests": 0}
        by_model[m]["cost"] += e.get("cost_usd", 0)
        by_model[m]["requests"] += 1

    by_mode = {}
    for e in entries:
        mode = e.get("mode", "unknown")
        if mode not in by_mode:
            by_mode[mode] = {"cost": 0, "requests": 0}
        by_mode[mode]["cost"] += e.get("cost_usd", 0)
        by_mode[mode]["requests"] += 1

    by_agent = {}
    for e in entries:
        role = e.get("agent_role", "unknown")
        if role not in by_agent:
            by_agent[role] = {"cost": 0, "requests": 0}
        by_agent[role]["cost"] += e.get("cost_usd", 0)
        by_agent[role]["requests"] += 1

    success_count = sum(1 for e in entries if e.get("success", True))

    return {
        "total_cost": round(total_cost, 4),
        "total_requests": total_requests,
        "avg_cost_per_request": round(total_cost / max(total_requests, 1), 6),
        "success_rate": round(success_count / max(total_requests, 1) * 100, 1),
        "by_model": {k: {"cost": round(v["cost"], 4), "requests": v["requests"]}
                     for k, v in by_model.items()},
        "by_mode": {k: {"cost": round(v["cost"], 4), "requests": v["requests"]}
                    for k, v in by_mode.items()},
        "by_agent": {k: {"cost": round(v["cost"], 4), "requests": v["requests"]}
                     for k, v in by_agent.items()},
        "period_days": days
    }


def _parse_ts(ts_str: str) -> float:
    try:
        return datetime.fromisoformat(ts_str).timestamp()
    except Exception:
        return 0


def _load_cost_log():
    global _cost_log
    try:
        if os.path.exists(_cost_log_path):
            with open(_cost_log_path, "r") as f:
                _cost_log = json.load(f)
    except Exception:
        _cost_log = []


def _save_cost_log():
    try:
        os.makedirs(os.path.dirname(_cost_log_path), exist_ok=True)
        data = _cost_log[-10000:]
        with open(_cost_log_path, "w") as f:
            json.dump(data, f, ensure_ascii=False)
    except Exception as e:
        logger.error(f"Failed to save cost log: {e}")
