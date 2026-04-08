"""
ARCANE UserProfile — User preference learning from conversations.

Extracts implicit/explicit preferences from chats (language, frameworks,
design style, communication style) and injects them into future prompts.

Storage: SQLite via core.persistence (PersistentStore) — same DB as the rest of the app.
Fallback: in-memory dict if persistence not available.

Fix: replaced broken PostgreSQL/SQLAlchemy with core.persistence KVTable.
"""
from __future__ import annotations

import json
import logging
from typing import Optional

from shared.utils.logger import get_logger

logger = get_logger("core.user_profile")

# ── In-memory fallback (used only if SQLite unavailable) ─────────────────────
_prefs_mem: dict[str, list[dict]] = {}

PREFERENCE_CATEGORIES = {
    "language":      "Preferred spoken/written language",
    "coding_style":  "Coding conventions and style",
    "framework":     "Preferred frameworks and libraries",
    "design":        "Design preferences (minimal, colorful, dark, etc.)",
    "communication": "Communication style (formal, casual, brief, verbose)",
    "tools":         "Preferred tools and services",
    "deployment":    "Deployment preferences (VPS, Docker, Vercel, etc.)",
}

EXTRACTION_PROMPT = """Analyze this conversation and extract user preferences.

Return a JSON array. Each item:
  "category": one of {categories}
  "key": short snake_case key (e.g. "preferred_language", "css_framework")
  "value": the value (e.g. "Russian", "TailwindCSS")
  "confidence": 0.0–1.0 (1.0=explicit, 0.5=implied, 0.3=guessed)

Only include confidence >= 0.3. Return [] if nothing found.
Return ONLY the JSON array, nothing else.

Conversation:
{conversation}"""


async def extract_preferences(
    messages: list[dict],
    user_id: str,
    chat_id: str,
    llm_client=None,
) -> list[dict]:
    """Extract preferences from conversation using a cheap LLM call."""
    if not messages or not llm_client:
        return []

    parts = []
    for msg in messages:
        role = msg.get("role", "")
        content = str(msg.get("content", "") or "")
        if role == "user" and content:
            parts.append(f"User: {content[:400]}")
        elif role == "assistant" and content and not msg.get("tool_calls"):
            parts.append(f"Agent: {content[:250]}")

    if len(parts) < 2:
        return []

    conversation_text = "\n".join(parts[-20:])
    categories_str = ", ".join(PREFERENCE_CATEGORIES.keys())

    try:
        response = await llm_client.chat(
            model="gpt-5.4-nano",
            messages=[{"role": "user", "content": EXTRACTION_PROMPT.format(
                categories=categories_str,
                conversation=conversation_text,
            )}],
            max_tokens=500,
            temperature=0.1,
        )

        content = (response.get("content", "") if isinstance(response, dict) else str(response)).strip()

        # Parse JSON
        if content.startswith("["):
            raw = json.loads(content)
        else:
            start, end = content.find("["), content.rfind("]") + 1
            if start >= 0 and end > start:
                raw = json.loads(content[start:end])
            else:
                return []

        valid = []
        for pref in raw:
            if not isinstance(pref, dict):
                continue
            cat = pref.get("category", "")
            key = pref.get("key", "")
            value = pref.get("value", "")
            conf = float(pref.get("confidence", 0.3))
            if cat in PREFERENCE_CATEGORIES and key and value and conf >= 0.3:
                valid.append({
                    "category": cat,
                    "key": key[:100],
                    "value": str(value)[:500],
                    "confidence": round(min(max(conf, 0.0), 1.0), 3),
                })

        logger.info(f"Extracted {len(valid)} preferences for user {user_id}")
        return valid

    except Exception as e:
        logger.debug(f"Preference extraction failed for {user_id}: {e}")
        return []


def _get_store_key(user_id: str) -> str:
    return f"prefs:{user_id}"


async def save_preferences(
    user_id: str,
    chat_id: str,
    preferences: list[dict],
) -> int:
    """
    Save preferences using UPSERT logic.
    Uses core.persistence SQLite store — same DB as app data.
    Falls back to in-memory dict if persistence unavailable.
    """
    if not preferences:
        return 0

    # Try SQLite via persistence
    try:
        from core.persistence import get_store
        store = get_store()
        key = _get_store_key(user_id)
        existing_list: list[dict] = store.permissions.get(key) or []

        saved = 0
        for pref in preferences:
            found = False
            for ex in existing_list:
                if ex.get("category") == pref["category"] and ex.get("key") == pref["key"]:
                    # UPSERT: update value, increase confidence
                    ex["value"] = pref["value"]
                    ex["confidence"] = round(min(1.0, ex["confidence"] + pref["confidence"] * 0.2), 3)
                    ex["times_confirmed"] = ex.get("times_confirmed", 1) + 1
                    ex["last_chat"] = chat_id
                    found = True
                    break
            if not found:
                existing_list.append({
                    **pref,
                    "times_confirmed": 1,
                    "last_chat": chat_id,
                })
            saved += 1

        store.permissions.set(key, existing_list)
        logger.info(f"Saved {saved} preferences for user {user_id} (SQLite)")
        return saved

    except Exception as e:
        logger.debug(f"SQLite preferences failed, using memory: {e}")

    # Fallback: in-memory
    existing = _prefs_mem.setdefault(user_id, [])
    saved = 0
    for pref in preferences:
        found = False
        for ex in existing:
            if ex.get("category") == pref["category"] and ex.get("key") == pref["key"]:
                ex["value"] = pref["value"]
                ex["confidence"] = round(min(1.0, ex["confidence"] + pref["confidence"] * 0.2), 3)
                ex["times_confirmed"] = ex.get("times_confirmed", 1) + 1
                found = True
                break
        if not found:
            existing.append({**pref, "times_confirmed": 1})
        saved += 1

    logger.info(f"Saved {saved} preferences for user {user_id} (memory)")
    return saved


async def get_user_preferences(user_id: str) -> list[dict]:
    """Load preferences, sorted by confidence desc."""
    try:
        from core.persistence import get_store
        store = get_store()
        prefs = store.permissions.get(_get_store_key(user_id)) or []
        return sorted(prefs, key=lambda p: p.get("confidence", 0), reverse=True)
    except Exception:
        pass
    return sorted(_prefs_mem.get(user_id, []), key=lambda p: p.get("confidence", 0), reverse=True)


def preferences_to_prompt(preferences: list[dict]) -> str:
    """Format top preferences for system prompt injection."""
    if not preferences:
        return ""

    strong = [p for p in preferences if p.get("confidence", 0) >= 0.5]
    if not strong:
        return ""

    by_cat: dict[str, list[str]] = {}
    for p in strong:
        cat = p["category"]
        by_cat.setdefault(cat, []).append(f"{p['key']}: {p['value']}")

    lines = []
    for cat, items in by_cat.items():
        lines.append(f"  {cat}:")
        for item in items[:4]:
            lines.append(f"    - {item}")

    return "<user_preferences>\n" + "\n".join(lines) + "\n</user_preferences>"
