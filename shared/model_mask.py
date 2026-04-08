"""
shared/model_mask.py — Public-facing model name masking
========================================================
Replaces internal model IDs with ARCANE-branded tier names
in all user-facing contexts (events, budget, PROJECT.md, UI).

Internal audit/admin logs keep real model IDs.
Only public-facing outputs are masked.

Usage:
    from shared.model_mask import mask_model_id, mask_event_payload
    
    # Single model ID:
    mask_model_id("claude-sonnet-4.6")  → "Arcane Standard"
    mask_model_id("gpt-5.4")           → "Arcane Pro"
    
    # Event payload before sending to frontend:
    clean = mask_event_payload({"model_id": "claude-opus-4.6", "provider": "anthropic"})
    # → {"engine": "Arcane Expert", "tier": "expert"}
"""

from __future__ import annotations

# ═══════════════════════════════════════════════════════════════════════════════
# MODEL → PUBLIC TIER MAPPING
# ═══════════════════════════════════════════════════════════════════════════════

# Flagship models → "Arcane Expert"
# Standard models → "Arcane Standard"  
# Fast/cheap models → "Arcane Fast"
# Free models → "Arcane Lite"
# Reasoning models → "Arcane Deep"

_MODEL_TO_TIER: dict[str, str] = {
    "deepseek-v3.1": "fast",
    "deepseek-r1": "expert",
    "grok-4": "expert",
    "grok-4-fast": "fast",
    "qwen3-coder-free": "lite",
    "qwen3.6-plus-free": "lite",
    "gemini-2.5-flash-free": "lite",
    "minimax-m2.5-free": "lite",
    "nemotron-3-super-free": "lite",
    "step-3.5-flash-free": "lite",
    "nemotron-3-nano-free": "lite",
    "nemotron-nano-12b-vl-free": "lite",
    "llama-3.3-70b-free": "lite",

    # Expert tier
    "claude-opus-4.6": "expert",
    "gpt-5.4": "expert",
    "o3": "expert",
    
    # Standard tier
    "claude-sonnet-4.6": "standard",
    "gemini-3.1-pro": "standard",
    "minimax-m2.5": "standard",
    "gpt-5.4-mini": "standard",
    
    # Fast tier
    "claude-haiku-4.5": "fast",
    "gemini-2.5-flash": "fast",
    "gpt-5.4-nano": "fast",
    "deepseek-v3.2": "fast",
    "o4-mini": "fast",
    
    # Lite tier (free models)
    "kimi-k2.5": "lite",
    "step-3.5-flash": "lite",
    "nemotron-3-super": "lite",
}

_TIER_TO_PUBLIC_NAME: dict[str, str] = {
    "expert": "Arcane Expert",
    "standard": "Arcane Standard",
    "fast": "Arcane Fast",
    "lite": "Arcane Lite",
    "deep": "Arcane Deep",
    "unknown": "Arcane Core",
}


def get_model_tier(model_id: str) -> str:
    """Get internal tier for a model ID. Returns 'unknown' if not found."""
    # Try exact match
    tier = _MODEL_TO_TIER.get(model_id)
    if tier:
        return tier
    
    # Try without dots/dashes normalization
    normalized = model_id.replace("-", ".").lower()
    for mid, t in _MODEL_TO_TIER.items():
        if mid.replace("-", ".").lower() == normalized:
            return t
    
    # Try prefix match (for versioned models like "claude-sonnet-4.6-20260301")
    for mid, t in _MODEL_TO_TIER.items():
        if model_id.startswith(mid):
            return t
    
    return "unknown"


def mask_model_id(model_id: str) -> str:
    """Replace internal model ID with public ARCANE tier name."""
    tier = get_model_tier(model_id)
    return _TIER_TO_PUBLIC_NAME.get(tier, "Arcane Core")


def mask_provider(provider: str) -> str:
    """Replace provider name with generic label."""
    return "Arcane"


# ═══════════════════════════════════════════════════════════════════════════════
# EVENT / PAYLOAD MASKING
# ═══════════════════════════════════════════════════════════════════════════════

# Fields that leak internal details
_FIELDS_TO_MASK = {"model_id", "model", "model_used", "provider", "openrouter_id", "native_id"}
_FIELDS_TO_REMOVE = {"provider", "openrouter_id", "native_id", "api_key"}


def mask_event_payload(payload: dict, keep_internal: bool = False) -> dict:
    """
    Sanitize an event payload before sending to the frontend.
    
    Args:
        payload: raw event dict (e.g. from WebSocket broadcast)
        keep_internal: if True, skip masking (for admin/audit views)
    
    Returns:
        Cleaned dict safe for public display.
    """
    if keep_internal:
        return payload
    
    clean = {}
    for key, value in payload.items():
        if key in _FIELDS_TO_REMOVE:
            continue
        
        if key in _FIELDS_TO_MASK and isinstance(value, str):
            tier = get_model_tier(value)
            clean["engine"] = _TIER_TO_PUBLIC_NAME.get(tier, "Arcane Core")
            clean["tier"] = tier
            continue
        
        # Recursively mask nested dicts
        if isinstance(value, dict):
            clean[key] = mask_event_payload(value, keep_internal)
        elif isinstance(value, list):
            clean[key] = [
                mask_event_payload(item, keep_internal) if isinstance(item, dict) else item
                for item in value
            ]
        else:
            clean[key] = value
    
    return clean


def mask_run_result(run_dict: dict, keep_internal: bool = False) -> dict:
    """Mask a RunResult dict before sending to frontend."""
    if keep_internal:
        return run_dict
    
    clean = dict(run_dict)
    
    # Mask team roles → tiers (team: {"coding": "claude-sonnet-4.6"} → {"coding": "Arcane Standard"})
    if "team" in clean and isinstance(clean["team"], dict):
        clean["team"] = {role: mask_model_id(mid) for role, mid in clean["team"].items()}
    
    # Mask model references in cost breakdown
    if "cost_breakdown" in clean and isinstance(clean["cost_breakdown"], list):
        for entry in clean["cost_breakdown"]:
            if isinstance(entry, dict) and "model" in entry:
                entry["engine"] = mask_model_id(entry.pop("model"))
    
    # Mask escalation model names
    if "escalations" in clean:
        clean["escalations"] = [mask_model_id(e) if "/" in e or "-" in e else e for e in clean.get("escalations", [])]
    
    return clean


# ═══════════════════════════════════════════════════════════════════════════════
# PUBLIC IDENTITY CONFIG (for state.json)
# ═══════════════════════════════════════════════════════════════════════════════

DEFAULT_PUBLIC_IDENTITY = {
    "name": "Arcane",
    "creator_display": "Аналитик и Архитектор Юрий Мороз",
    "origin_statement_ru": "Arcane — интеллектуальная система, спроектированная Юрием Морозом.",
    "origin_statement_en": "Arcane — an intelligent system designed by Yuri Moroz.",
    "role_statement": "Arcane помогает анализировать, проектировать и исполнять сложные задачи.",
    "disclosure_policy": "private",
    "forbidden_topics": [
        "model_ids", "providers", "routing", "system_prompts",
        "repo_structure", "internal_tools", "source_files", "vendor_names",
    ],
    "fallback_reply_ru": "Я не раскрываю внутреннюю архитектуру и конфигурацию. Для вас важны результат, безопасность и качество исполнения.",
    "fallback_reply_en": "I don't disclose internal architecture and configuration. What matters to you is the result, security, and quality of execution.",
}
