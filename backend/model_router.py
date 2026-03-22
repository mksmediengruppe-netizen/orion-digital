"""
Model Router — ORION Digital v3.0
==================================
3 режима: Быстрый, Стандарт, Премиум.
Opus — emergency fallback.

Все модели умеют function calling через OpenRouter.
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
# МОДЕЛИ
# ══════════════════════════════════════════════════════════════

MODELS = {
    "gpt54": {
        "id": "openai/gpt-5.4",
        "name": "GPT-5.4",
        "input_price": 2.50,
        "output_price": 15.00,
        "role": "director",
        "description": "Главный мозг: планирование, стратегия, сложные решения",
        "max_tokens": 128000
    },
    "gpt54_mini": {
        "id": "openai/gpt-5.4-mini",
        "name": "GPT-5.4 Mini",
        "input_price": 0.75,
        "output_price": 4.50,
        "role": "worker",
        "description": "Основной worker: код, тексты, задачи",
        "max_tokens": 65536
    },
    "gpt54_nano": {
        "id": "openai/gpt-5.4-nano",
        "name": "GPT-5.4 Nano",
        "input_price": 0.20,
        "output_price": 1.25,
        "role": "utility",
        "description": "Утилитарный: классификация, роутинг, извлечение данных",
        "max_tokens": 32768
    },
    "gemini_flash": {
        "id": "google/gemini-2.5-flash",
        "name": "Gemini 2.5 Flash",
        "input_price": 0.30,
        "output_price": 2.50,
        "role": "designer",
        "description": "Дизайнер: HTML/CSS/JS, вёрстка, UI",
        "max_tokens": 65536
    },
    "gemini_pro": {
        "id": "google/gemini-2.5-pro",
        "name": "Gemini 2.5 Pro",
        "input_price": 1.25,
        "output_price": 10.00,
        "role": "premium_designer",
        "description": "Премиум дизайн: сложный UI/UX, визуальное качество",
        "max_tokens": 65536
    },
    "sonnet": {
        "id": "anthropic/claude-sonnet-4.6",
        "name": "Claude Sonnet 4.6",
        "input_price": 3.00,
        "output_price": 15.00,
        "role": "critic",
        "description": "Критик: code review, judge, независимая проверка",
        "max_tokens": 64000
    },
    "opus": {
        "id": "anthropic/claude-opus-4",
        "name": "Claude Opus 4",
        "input_price": 15.00,
        "output_price": 75.00,
        "role": "emergency",
        "description": "Emergency: только при 2+ rejected от FinalJudge",
        "max_tokens": 32000
    },
    "mimo": {
        "id": "xiaomi/mimo-v2-flash",
        "name": "MiMo V2 Flash",
        "input_price": 0.09,
        "output_price": 0.29,
        "role": "hands",
        "description": "Руки: SSH, FTP, деплой, серверные команды",
        "max_tokens": 32768
    }
}

# ══════════════════════════════════════════════════════════════
# 3 РЕЖИМА
# ══════════════════════════════════════════════════════════════

MODES = {
    "fast": {
        "label": "Быстрый",
        "emoji": "⚡",
        "description": "Быстро и дёшево. GPT-5.4 Mini думает и кодит, Gemini Flash дизайнит.",
        "max_cost_usd": 2.0,
        "agents": {
            "orchestrator":     "gpt54_mini",
            "intent_clarifier": "gpt54_nano",
            "designer":         "gemini_flash",
            "developer":        "gpt54_mini",
            "devops":           "mimo",
            "integrator":       "mimo",
            "tester":           "mimo",
            "analyst":          "gpt54_mini",
            "copywriter":       "gpt54_mini",
            "code_reviewer":    None,
            "judge":            "gpt54_mini"
        }
    },
    "standard": {
        "label": "Стандарт",
        "emoji": "⭐",
        "description": "Оптимальное качество. GPT-5.4 планирует, Mini кодит, Sonnet проверяет.",
        "max_cost_usd": 5.0,
        "agents": {
            "orchestrator":     "gpt54",
            "intent_clarifier": "gpt54_nano",
            "designer":         "gemini_flash",
            "developer":        "gpt54_mini",
            "devops":           "mimo",
            "integrator":       "mimo",
            "tester":           "mimo",
            "analyst":          "gpt54_mini",
            "copywriter":       "gpt54_mini",
            "code_reviewer":    None,
            "judge":            "sonnet"
        }
    },
    "premium": {
        "label": "Премиум",
        "emoji": "💎",
        "description": "Максимум качества. GPT-5.4 план, Sonnet review, Gemini Pro дизайн.",
        "max_cost_usd": 15.0,
        "agents": {
            "orchestrator":     "gpt54",
            "intent_clarifier": "gpt54_nano",
            "designer":         "gemini_pro",
            "developer":        "gpt54_mini",
            "devops":           "mimo",
            "integrator":       "mimo",
            "tester":           "mimo",
            "analyst":          "gpt54",
            "copywriter":       "sonnet",
            "code_reviewer":    "sonnet",
            "judge":            "sonnet"
        }
    }
}

DEFAULT_MODE = "standard"

# ══════════════════════════════════════════════════════════════
# FALLBACK CHAINS
# ══════════════════════════════════════════════════════════════

FALLBACK_CHAINS = {
    "gpt54":       ["openai/gpt-5.4", "anthropic/claude-sonnet-4.6", "google/gemini-2.5-pro"],
    "gpt54_mini":  ["openai/gpt-5.4-mini", "google/gemini-2.5-flash", "openai/gpt-5.4-nano"],
    "gpt54_nano":  ["openai/gpt-5.4-nano", "openai/gpt-5.4-mini"],
    "gemini_flash": ["google/gemini-2.5-flash", "openai/gpt-5.4-mini"],
    "gemini_pro":  ["google/gemini-2.5-pro", "anthropic/claude-sonnet-4.6"],
    "sonnet":      ["anthropic/claude-sonnet-4.6", "openai/gpt-5.4"],
    "opus":        ["anthropic/claude-opus-4", "openai/gpt-5.4", "anthropic/claude-sonnet-4.6"],
    "mimo":        ["xiaomi/mimo-v2-flash", "openai/gpt-5.4-nano"],
}

# ══════════════════════════════════════════════════════════════
# PRICING (для расчёта стоимости любой модели)
# ══════════════════════════════════════════════════════════════

PRICING = {
    "openai/gpt-5.4":              (2.50, 15.00),
    "openai/gpt-5.4-mini":         (0.75, 4.50),
    "openai/gpt-5.4-nano":         (0.20, 1.25),
    "google/gemini-2.5-flash":     (0.30, 2.50),
    "google/gemini-2.5-pro":       (1.25, 10.00),
    "anthropic/claude-sonnet-4.6": (3.00, 15.00),
    "anthropic/claude-opus-4":     (15.00, 75.00),
    "xiaomi/mimo-v2-flash":        (0.09, 0.29),
}

# ══════════════════════════════════════════════════════════════
# ОСНОВНЫЕ ФУНКЦИИ
# ══════════════════════════════════════════════════════════════

def get_model_for_agent(agent_role: str, mode: str = DEFAULT_MODE) -> Dict[str, Any]:
    mode_config = MODES.get(mode, MODES[DEFAULT_MODE])
    agents_map = mode_config["agents"]
    model_key = agents_map.get(agent_role)
    
    if model_key is None:
        model_key = "gpt54_mini"  # default fallback
    
    model_cfg = MODELS[model_key].copy()
    model_cfg["model_key"] = model_key
    model_cfg["model_id"] = model_cfg["id"]
    model_cfg["model_name"] = model_cfg["name"]
    model_cfg["mode"] = mode
    model_cfg["agent_role"] = agent_role
    return model_cfg


def get_model_id(agent_role: str, mode: str = DEFAULT_MODE) -> str:
    return get_model_for_agent(agent_role, mode)["id"]


def get_mode_config(mode: str = DEFAULT_MODE) -> Dict[str, Any]:
    return MODES.get(mode, MODES[DEFAULT_MODE])


def get_max_cost(mode: str = DEFAULT_MODE) -> float:
    return MODES.get(mode, MODES[DEFAULT_MODE]).get("max_cost_usd", 2.0)


def list_modes() -> List[Dict[str, Any]]:
    result = []
    for mode_key, mode_cfg in MODES.items():
        result.append({
            "key": mode_key,
            "label": mode_cfg["label"],
            "emoji": mode_cfg["emoji"],
            "description": mode_cfg["description"],
            "max_cost_usd": mode_cfg["max_cost_usd"],
            "agents": {
                role: (MODELS[m]["name"] if m else "—")
                for role, m in mode_cfg["agents"].items()
            }
        })
    return result


def list_models() -> List[Dict[str, Any]]:
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


def _get_fallback_chain(model_key: str) -> List[str]:
    return FALLBACK_CHAINS.get(model_key, FALLBACK_CHAINS["gpt54_mini"])


def get_fallback_model(current_model: str, tier: str = "gpt54_mini") -> Optional[str]:
    chain = _get_fallback_chain(tier)
    try:
        idx = chain.index(current_model)
        if idx + 1 < len(chain):
            return chain[idx + 1]
    except ValueError:
        pass
    return MODELS["gpt54_mini"]["id"]


def calc_cost(tokens_in: int, tokens_out: int, model_id: str) -> float:
    in_price, out_price = PRICING.get(model_id, (0.75, 4.50))
    return round((tokens_in / 1_000_000) * in_price + (tokens_out / 1_000_000) * out_price, 6)


def classify_complexity(query: str, history: List[Dict] = None) -> int:
    query_lower = query.lower()
    word_count = len(query.split())
    score = 2
    if word_count < 5:
        score -= 1
    elif word_count > 50:
        score += 1
    elif word_count > 150:
        score += 2
    complex_patterns = [
        r"(архитектур|architecture|design pattern)",
        r"(проект|project|приложение|application|систем|system)",
        r"(деплой|deploy|настрой сервер|configure server)",
    ]
    for pattern in complex_patterns:
        if re.search(pattern, query_lower):
            score = max(4, score)
    return max(1, min(5, score))


def select_model(query: str, variant: str = "standard",
                 history: List[Dict] = None,
                 preferred_model: str = None,
                 mode: str = DEFAULT_MODE) -> Dict[str, Any]:
    if preferred_model:
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
    result = get_model_for_agent("orchestrator", mode)
    result["tier"] = result.get("model_key", "gpt54_mini")
    result["complexity"] = classify_complexity(query, history)
    result["fallback_chain"] = _get_fallback_chain(result.get("model_key", "gpt54_mini"))
    return result


# ══════════════════════════════════════════════════════════════
# COST TRACKING (оставляем как есть)
# ══════════════════════════════════════════════════════════════

_data_dir = os.environ.get("DATA_DIR", "/var/www/orion/backend/data")
_cost_log_path = os.path.join(_data_dir, "cost_log.json")
_cost_log: List[Dict] = []
_session_costs: Dict[str, float] = {}


def check_cost_limit(session_id: str, mode: str = DEFAULT_MODE) -> Dict[str, Any]:
    current = _session_costs.get(session_id, 0.0)
    max_cost = get_max_cost(mode)
    remaining = max(0.0, max_cost - current)
    return {
        "allowed": current < max_cost,
        "current_cost": round(current, 4),
        "max_cost": max_cost,
        "remaining": round(remaining, 4),
        "mode": mode
    }


def add_session_cost(session_id: str, cost_usd: float):
    _session_costs[session_id] = _session_costs.get(session_id, 0.0) + cost_usd


def reset_session_cost(session_id: str):
    _session_costs.pop(session_id, None)


def log_cost(user_id: str, model_id: str, tokens_in: int, tokens_out: int,
             cost_usd: float, tier: str = "gpt54_mini", complexity: int = 2,
             tool_name: str = None, success: bool = True,
             session_id: str = None, mode: str = DEFAULT_MODE,
             agent_role: str = None):
    global _cost_log
    entry = {
        "user_id": user_id, "session_id": session_id,
        "model_id": model_id, "tokens_in": tokens_in,
        "tokens_out": tokens_out, "cost_usd": cost_usd,
        "tier": tier, "complexity": complexity,
        "tool_name": tool_name, "success": success,
        "mode": mode, "agent_role": agent_role,
        "timestamp": datetime.now(timezone.utc).isoformat()
    }
    _cost_log.append(entry)
    if session_id:
        add_session_cost(session_id, cost_usd)
    if len(_cost_log) % 10 == 0:
        _save_cost_log()


def get_cost_analytics(user_id: str = None, days: int = 30) -> Dict[str, Any]:
    _load_cost_log()
    entries = _cost_log
    if user_id:
        entries = [e for e in entries if e.get("user_id") == user_id]
    if not entries:
        return {"total_cost": 0, "total_requests": 0, "by_model": {}, "by_mode": {}}
    total_cost = sum(e.get("cost_usd", 0) for e in entries)
    return {
        "total_cost": round(total_cost, 4),
        "total_requests": len(entries),
        "avg_cost": round(total_cost / len(entries), 6),
    }


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
        with open(_cost_log_path, "w") as f:
            json.dump(_cost_log[-10000:], f, ensure_ascii=False)
    except Exception as e:
        logger.error(f"Failed to save cost log: {e}")
