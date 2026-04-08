"""
api/chat_store.py — Thin adapter to SQLite persistence.
Routes agent_loop usage writes to the same SQLite store as compat_all.
"""
import logging
logger = logging.getLogger("arcane2.chat_store")

_chats = {}
_messages = {}


def _get_store():
    """Lazy import to avoid circular deps."""
    try:
        from core.persistence import get_store
        return get_store()
    except Exception:
        return None


def get_messages(chat_id: str) -> list:
    store = _get_store()
    if store:
        return store.messages.get(chat_id, [])
    return _messages.get(chat_id, [])


def update_chat(chat_id: str, data: dict):
    store = _get_store()
    if store:
        existing = dict(store.chats.get(chat_id) or {})
        existing.update(data)
        store.chats.set(chat_id, existing)
    else:
        _chats.setdefault(chat_id, {}).update(data)


def add_message(chat_id: str, message: dict):
    store = _get_store()
    if store:
        store.messages.append(chat_id, message)
    else:
        _messages.setdefault(chat_id, []).append(message)


def get_chat(chat_id: str) -> dict:
    store = _get_store()
    if store:
        return dict(store.chats.get(chat_id) or {})
    return _chats.get(chat_id, {})
