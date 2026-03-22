"""
ORION Digital — Task Routes Blueprint
"""
from flask import Blueprint, request, jsonify, Response, stream_with_context
import json
import time
import os
import logging
import threading
from datetime import datetime, timezone

logger = logging.getLogger(__name__)
import uuid

# Import shared state and helpers
from shared import (
    app, db_read, db_write, require_auth, require_admin,
    _now_iso, _calc_cost, _get_memory, _get_versions, _get_rate_limiter,
    _encrypt_setting, _decrypt_setting, _SECRET_SETTINGS_KEYS,
    _running_tasks, _tasks_lock, _interrupt_lock, _active_agents, _agents_lock,
    OPENROUTER_API_KEY, OPENROUTER_BASE_URL, DATA_DIR, UPLOAD_DIR,
    _lock, _USE_SQLITE,
)

task_bp = Blueprint("task", __name__)


@task_bp.route("/api/chats", methods=["GET"])
@require_auth
def list_chats():
    """List all chats for current user."""
    db = db_read()
    is_admin = request.user.get("role") == "admin"
    user_chats = []
    for chat_id, chat in db["chats"].items():
        if is_admin or chat.get("user_id") == request.user_id:
            msg_count = len(chat.get("messages", []))
            # BUG-ARCH-02 FIX: Skip empty chats (no messages) to prevent sidebar clutter.
            # Empty chats are created by the old newChat() bug and should not be shown.
            if msg_count == 0:
                continue
            user_chats.append({
                "id": chat_id,
                "title": chat.get("title", "Новый чат"),
                "created_at": chat.get("created_at", ""),
                "updated_at": chat.get("updated_at", ""),
                "message_count": msg_count,
                "total_cost": chat.get("total_cost", 0.0),
                "model_used": chat.get("model_used", ""),
                "variant": chat.get("variant", "premium"),
                "owner": (db["users"].get(chat.get("user_id",""), {}).get("name") or db["users"].get(chat.get("user_id",""), {}).get("email", chat.get("user_id",""))) if is_admin else ""
            })

    user_chats.sort(key=lambda x: x.get("updated_at", ""), reverse=True)
    return jsonify({"chats": user_chats})



@task_bp.route("/api/chats", methods=["POST"])
@require_auth
def create_chat():
    """Create a new chat."""
    import html as html_module
    data = request.get_json() or {}
    chat_id = str(uuid.uuid4())[:8]
    now = datetime.now(timezone.utc).isoformat()

    db = db_read()
    user_settings = db["users"].get(request.user_id, {}).get("settings", {})

    # XSS sanitization
    raw_title = data.get("title", "Новый чат")
    safe_title = html_module.escape(raw_title)

    chat = {
        "id": chat_id,
        "user_id": request.user_id,
        "title": safe_title,
        "created_at": now,
        "updated_at": now,
        "messages": [],
        "total_cost": 0.0,
        "total_tokens_in": 0,
        "total_tokens_out": 0,
        "variant": user_settings.get("variant", "premium"),
        "model_used": "",
        "files": [],
        "agent_actions": [],
        "orion_mode": data.get("mode", "turbo-basic")
    }

    db["chats"][chat_id] = chat
    db_write(db)

    return jsonify({"chat": chat}), 201



@task_bp.route("/api/chats/<chat_id>", methods=["GET"])
@require_auth
def get_chat(chat_id):
    """Get chat with all messages."""
    db = db_read()
    chat = db["chats"].get(chat_id)
    if not chat or chat.get("user_id") != request.user_id:
        if request.user.get("role") != "admin":
            return jsonify({"error": "Chat not found"}), 404
    return jsonify({"chat": chat})



@task_bp.route("/api/chats/<chat_id>", methods=["DELETE"])
@require_auth
def delete_chat(chat_id):
    """Delete a chat."""
    db = db_read()
    chat = db["chats"].get(chat_id)
    if not chat:
        return jsonify({"error": "Chat not found"}), 404
    if chat.get("user_id") != request.user_id and request.user.get("role") != "admin":
        return jsonify({"error": "Access denied"}), 403

    del db["chats"][chat_id]
    db_write(db)
    return jsonify({"ok": True})



@task_bp.route("/api/chats/<chat_id>/rename", methods=["PUT"])
@require_auth
def rename_chat(chat_id):
    """Rename a chat."""
    data = request.get_json() or {}
    db = db_read()
    chat = db["chats"].get(chat_id)
    if not chat:
        return jsonify({"error": "Chat not found"}), 404
    if chat.get("user_id") != request.user_id and request.user.get("role") != "admin":
        return jsonify({"error": "Access denied"}), 403

    chat["title"] = data.get("title", chat["title"])
    chat["updated_at"] = datetime.now(timezone.utc).isoformat()
    db["chats"][chat_id] = chat
    db_write(db)
    return jsonify({"ok": True})


# ── File Upload ────────────────────────────────────────────────
