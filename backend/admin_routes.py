"""
ORION Digital — Admin Routes Blueprint
"""
from flask import Blueprint, request, jsonify, Response, stream_with_context
import json
import hashlib
import time
import os
import logging
import threading
from datetime import datetime, timezone

logger = logging.getLogger(__name__)
import re
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

import bcrypt
import secrets
from model_router import get_cost_analytics

admin_bp = Blueprint("admin", __name__)


def _read_env_file():
    """Read .env file as dict."""
    env = {}
    if os.path.exists(_ENV_FILE):
        with open(_ENV_FILE, "r") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, _, v = line.partition("=")
                    env[k.strip()] = v.strip().strip('"').strip("'")
    return env


def _write_env_file(env: dict):
    """Write dict back to .env file."""
    lines = []
    existing = {}
    if os.path.exists(_ENV_FILE):
        with open(_ENV_FILE, "r") as f:
            raw_lines = f.readlines()
        for line in raw_lines:
            stripped = line.strip()
            if stripped and not stripped.startswith("#") and "=" in stripped:
                k, _, _ = stripped.partition("=")
                existing[k.strip()] = line
            else:
                lines.append(line)
    # Update or add keys
    for k, v in env.items():
        existing[k] = f"{k}={v}\n"
    # Rebuild file: comments first, then key=value lines
    result = lines + list(existing.values())
    with open(_ENV_FILE, "w") as f:
        f.writelines(result)


def _mask_key(val: str) -> str:
    """Return masked key showing only first 8 chars."""
    if not val:
        return ""
    if len(val) <= 8:
        return "*" * len(val)
    return val[:8] + "*" * (len(val) - 8)



@admin_bp.route("/api/analytics", methods=["GET"])
@require_auth
def get_analytics():
    """Get analytics for current user."""
    db = db_read()
    user = db["users"].get(request.user_id, {})

    user_chats = [c for c in db["chats"].values() if c.get("user_id") == request.user_id]
    user_cost = sum(c.get("total_cost", 0) for c in user_chats)
    user_messages = sum(len(c.get("messages", [])) for c in user_chats)

    # BUG-ANA-02 FIX: Compute tokens from individual messages (SQLite chats table
    # does not have total_tokens_in/out columns; tokens are stored per-message).
    user_tokens_in = 0
    user_tokens_out = 0
    for c in user_chats:
        for msg in c.get("messages", []):
            user_tokens_in += msg.get("tokens_in", 0)
            user_tokens_out += msg.get("tokens_out", 0)
        # Fallback: use stored totals if per-message tokens are missing
        if user_tokens_in == 0 and user_tokens_out == 0:
            user_tokens_in += c.get("total_tokens_in", 0)
            user_tokens_out += c.get("total_tokens_out", 0)

    chat_stats = []
    for c in user_chats:
        # BUG-ANA-03 FIX: model_used is stored in messages, not in chat root.
        # Extract model from last assistant message.
        chat_model = c.get("model_used", "") or c.get("model", "")
        if not chat_model:
            for msg in reversed(c.get("messages", [])):
                if msg.get("role") == "assistant" and msg.get("model"):
                    chat_model = msg["model"]
                    break
        chat_stats.append({
            "id": c["id"],
            "title": c.get("title", ""),
            "cost": c.get("total_cost", 0),
            "messages": len(c.get("messages", [])),
            "variant": c.get("variant", ""),
            "model": chat_model,
            "created_at": c.get("created_at", "")
        })

    daily_data = {}
    for c in user_chats:
        for msg in c.get("messages", []):
            if msg.get("role") == "assistant":
                day = msg.get("timestamp", "")[:10]
                if day:
                    if day not in daily_data:
                        daily_data[day] = {"cost": 0, "requests": 0}
                    daily_data[day]["cost"] += msg.get("cost", 0)
                    daily_data[day]["requests"] += 1

    avg_task_cost = user_cost / max(len([m for c in user_chats for m in c.get("messages", []) if m.get("role") == "assistant"]), 1)
    programmer_hourly = 50
    programmer_task_time = 2
    programmer_cost = programmer_hourly * programmer_task_time
    savings_percent = round((1 - avg_task_cost / programmer_cost) * 100, 1) if programmer_cost > 0 else 0

    return jsonify({
        "user": {
            "total_cost": round(user_cost, 4),
            "total_cost_rub": round(user_cost * 105, 2),
            "total_chats": len(user_chats),
            "total_messages": user_messages,
            "tokens_in": user_tokens_in,
            "tokens_out": user_tokens_out,
            "monthly_limit": user.get("monthly_limit", 999999),
            "monthly_limit_rub": round(user.get("monthly_limit", 999999) * 105, 2),
            "limit_used_percent": round(user_cost / max(user.get("monthly_limit", 999999), 1) * 100, 1),
            # BUG-BACKEND-3 FIX: frontend expects username/full_name
            "username": user.get("email", uid),
            "full_name": user.get("name", ""),
            "total_spent": user_cost,
            "is_blocked": user.get("is_blocked", False)
        },
        "chats": chat_stats,
        "daily": daily_data,
        "comparison": {
            "agent_avg_cost": round(avg_task_cost, 4),
            "programmer_avg_cost": programmer_cost,
            "savings_percent": max(savings_percent, 0),
            "savings_text": f"Экономия {max(savings_percent, 0)}% по сравнению с программистом"
        }
    })


# ── Admin Panel ────────────────────────────────────────────────

@admin_bp.route("/api/admin/users", methods=["GET"])
@require_auth
@require_admin
def admin_list_users():
    """List all users (admin only)."""
    db = db_read()
    users = []
    for uid, u in db["users"].items():
        user_chats = [c for c in db["chats"].values() if c.get("user_id") == uid]
        total_cost = sum(c.get("total_cost", 0) for c in user_chats)
        total_chats = len(user_chats)
        total_messages = sum(len(c.get("messages", [])) for c in user_chats)

        users.append({
            "id": uid,
            "email": u["email"],
            "name": u["name"],
            "role": u.get("role", "user"),
            "is_active": u.get("is_active", True),
            "created_at": u.get("created_at", ""),
            "total_spent": round(total_cost, 4),
            "total_spent_rub": round(total_cost * 105, 2),
            "total_chats": total_chats,
            "total_messages": total_messages,
            "monthly_limit": u.get("monthly_limit", 999999),
            "monthly_limit_rub": round(u.get("monthly_limit", 999999) * 105, 2),
            "budget_used_percent": round(total_cost / max(u.get("monthly_limit", 999999), 0.01) * 100, 1),
            "permissions": u.get("permissions", {
                "can_use_ssh": True,
                "can_use_browser": True,
                "can_use_enhanced": u.get("role") == "admin",
                "can_export": True,
                "can_upload_files": True,
                "max_chats": 100,
                "max_messages_per_day": 500
            }),
            "settings": u.get("settings", {})
        })

    return jsonify({"users": users})



@admin_bp.route("/api/admin/users", methods=["POST"])
@require_auth
@require_admin
def admin_create_user():
    """Create a new user (admin only)."""
    data = request.get_json() or {}
    email = data.get("email", "").strip().lower()
    password = data.get("password", "")
    name = data.get("name", email.split("@")[0])
    role = data.get("role", "user")  # admin, user, viewer
    monthly_limit = data.get("monthly_limit", 100)
    permissions = data.get("permissions", {})

    if not email or not password:
        return jsonify({"error": "Email and password required"}), 400

    db = db_read()

    for u in db["users"].values():
        if u["email"].lower() == email:
            return jsonify({"error": "Email already exists"}), 409

    user_id = str(uuid.uuid4())[:8]
    db["users"][user_id] = {
        "id": user_id,
        "email": email,
        "password_hash": bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode(),
        "name": name,
        "role": role,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "is_active": True,
        "monthly_limit": monthly_limit,
        "total_spent": 0.0,
        "permissions": {
            "can_use_ssh": permissions.get("can_use_ssh", role in ("admin", "user")),
            "can_use_browser": permissions.get("can_use_browser", role in ("admin", "user")),
            "can_use_enhanced": permissions.get("can_use_enhanced", role == "admin"),
            "can_export": permissions.get("can_export", True),
            "can_upload_files": permissions.get("can_upload_files", True),
            "max_chats": permissions.get("max_chats", 100),
            "max_messages_per_day": permissions.get("max_messages_per_day", 500),
        },
        "settings": {
            "variant": "premium",
            "chat_model": "qwen3",
            "enhanced_mode": False,
            "design_pro": False,
            "language": "ru"
        }
    }
    db_write(db)
    return jsonify({"ok": True, "user_id": user_id}), 201



@admin_bp.route("/api/admin/users/<user_id>", methods=["PUT"])
@require_auth
@require_admin
def admin_update_user(user_id):
    """Update user details — role, name, limit, permissions (admin only)."""
    data = request.get_json() or {}
    db = db_read()
    user = db["users"].get(user_id)
    if not user:
        return jsonify({"error": "User not found"}), 404

    # Update allowed fields
    # BUG-BACKEND-4 FIX: accept both name/email and username/full_name from frontend
    if "name" in data:
        user["name"] = data["name"]
    if "full_name" in data:
        user["name"] = data["full_name"]
    if "username" in data:
        user["email"] = data["username"]
    if "email" in data:
        user["email"] = data["email"]
    if "role" in data:
        user["role"] = data["role"]
    if "monthly_limit" in data:
        user["monthly_limit"] = data["monthly_limit"]
    if "is_active" in data:
        user["is_active"] = data["is_active"]
    if "is_blocked" in data:
        user["is_blocked"] = data["is_blocked"]
    if "password" in data and data["password"]:
        user["password_hash"] = bcrypt.hashpw(data["password"].encode(), bcrypt.gensalt()).decode()  # PATCH 16: bcrypt instead of sha256

    # Update permissions
    if "permissions" in data:
        perms = user.get("permissions", {})
        for key in ("can_use_ssh", "can_use_browser", "can_use_enhanced",
                     "can_export", "can_upload_files", "max_chats", "max_messages_per_day"):
            if key in data["permissions"]:
                perms[key] = data["permissions"][key]
        user["permissions"] = perms

    db["users"][user_id] = user
    db_write(db)
    return jsonify({"ok": True})



@admin_bp.route("/api/admin/users/<user_id>", methods=["DELETE"])
@require_auth
@require_admin
def admin_delete_user(user_id):
    """Delete a user and all their chats (admin only)."""
    db = db_read()
    if user_id not in db["users"]:
        return jsonify({"error": "User not found"}), 404
    if user_id == request.user_id:
        return jsonify({"error": "Cannot delete yourself"}), 400

    # Delete user's chats
    chats_to_delete = [cid for cid, c in db["chats"].items() if c.get("user_id") == user_id]
    for cid in chats_to_delete:
        del db["chats"][cid]

    # Delete user's sessions
    sessions_to_delete = [sid for sid, s in db["sessions"].items() if s.get("user_id") == user_id]
    for sid in sessions_to_delete:
        del db["sessions"][sid]

    del db["users"][user_id]
    db_write(db)
    return jsonify({"ok": True})



@admin_bp.route("/api/admin/users/<user_id>/toggle", methods=["POST"])
@require_auth
@require_admin
def admin_toggle_user(user_id):
    """Block/unblock user (admin only)."""
    db = db_read()
    user = db["users"].get(user_id)
    if not user:
        return jsonify({"error": "User not found"}), 404

    user["is_active"] = not user.get("is_active", True)
    db["users"][user_id] = user
    db_write(db)
    return jsonify({"ok": True, "is_active": user["is_active"]})



@admin_bp.route("/api/admin/users/<user_id>/limit", methods=["PUT"])
@require_auth
@require_admin
def admin_set_limit(user_id):
    """Set user monthly limit (admin only)."""
    data = request.get_json() or {}
    db = db_read()
    user = db["users"].get(user_id)
    if not user:
        return jsonify({"error": "User not found"}), 404

    user["monthly_limit"] = data.get("limit", 100)
    db["users"][user_id] = user
    db_write(db)
    return jsonify({"ok": True})



@admin_bp.route("/api/admin/users/<user_id>/chats", methods=["GET"])
@require_auth
@require_admin
def admin_user_chats(user_id):
    """View user's chats (admin only)."""
    db = db_read()
    user_chats = [c for c in db["chats"].values() if c.get("user_id") == user_id]
    user_chats.sort(key=lambda x: x.get("updated_at", ""), reverse=True)
    return jsonify({"chats": user_chats})



@admin_bp.route("/api/admin/chats", methods=["GET"])
@require_auth
@require_admin
def admin_all_chats():
    """View ALL chats from all users with full messages (admin only)."""
    db = db_read()
    all_chats = []
    for chat_id, chat in db["chats"].items():
        user = db["users"].get(chat.get("user_id", ""), {})
        all_chats.append({
            "id": chat_id,
            "title": chat.get("title", "Untitled"),
            "user_id": chat.get("user_id", ""),
            "user_email": user.get("email", "unknown"),
            "user_name": user.get("name", "unknown"),
            "variant": chat.get("variant", ""),
            "model": chat.get("model", ""),
            "total_cost": chat.get("total_cost", 0),
            "messages": chat.get("messages", []),
            "message_count": len(chat.get("messages", [])),
            "created_at": chat.get("created_at", ""),
            "updated_at": chat.get("updated_at", "")
        })
    all_chats.sort(key=lambda x: x.get("updated_at", ""), reverse=True)
    return jsonify({"chats": all_chats})



@admin_bp.route("/api/admin/chats/<chat_id>", methods=["GET"])
@require_auth
@require_admin
def admin_get_chat(chat_id):
    """View a specific chat with full messages (admin only)."""
    db = db_read()
    chat = db["chats"].get(chat_id)
    if not chat:
        return jsonify({"error": "Chat not found"}), 404
    user = db["users"].get(chat.get("user_id", ""), {})
    chat["user_email"] = user.get("email", "unknown")
    chat["user_name"] = user.get("name", "unknown")
    return jsonify({"chat": chat})



@admin_bp.route("/api/admin/chats/<chat_id>", methods=["DELETE"])
@require_auth
@require_admin
def admin_delete_chat(chat_id):
    """Delete a chat (admin only)."""
    db = db_read()
    if chat_id in db["chats"]:
        del db["chats"][chat_id]
        db_write(db)
        return jsonify({"ok": True})
    return jsonify({"error": "Chat not found"}), 404



@admin_bp.route("/api/admin/stats", methods=["GET"])
@require_auth
@require_admin
def admin_stats():
    """Get system-wide statistics (admin only)."""
    db = db_read()
    analytics = db.get("analytics", {})

    total_users = len(db["users"])
    total_chats = len(db["chats"])
    total_messages = sum(len(c.get("messages", [])) for c in db["chats"].values())
    active_users = len(set(c.get("user_id") for c in db["chats"].values()))

    total_cost = analytics.get("total_cost", 0)
    return jsonify({
        "total_users": total_users,
        "active_users": active_users,
        "total_chats": total_chats,
        "total_messages": total_messages,
        "total_cost": total_cost,
        "total_cost_rub": round(total_cost * 105, 2),
        "total_requests": analytics.get("total_requests", 0),
        "total_tokens_in": analytics.get("total_tokens_in", 0),
        "total_tokens_out": analytics.get("total_tokens_out", 0),
        "daily_stats": analytics.get("daily_stats", {}),
        "memory_episodes": len(db.get("memory", {}).get("episodic", []))
    })


# ── Memory API ─────────────────────────────────────────────────

@admin_bp.route("/api/admin/apikeys", methods=["GET"])
@require_auth
@require_admin
def admin_get_apikeys():
    """Get current API keys (masked) for admin panel."""
    try:
        env = _read_env_file()
        result = {}
        for short_name, env_var in _API_KEY_MAP.items():
            val = env.get(env_var, os.environ.get(env_var, ""))
            result[short_name] = _mask_key(val)
        return jsonify({"success": True, "keys": result})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500



@admin_bp.route("/api/admin/apikeys", methods=["PUT"])
@require_auth
@require_admin
def admin_set_apikeys():
    """Update API keys — write to .env and reload into os.environ."""
    try:
        data = request.get_json() or {}
        env = _read_env_file()
        updated = []
        for short_name, env_var in _API_KEY_MAP.items():
            val = data.get(short_name, "").strip()
            if val and not set(val) <= {"*"}:  # skip masked placeholders
                env[env_var] = val
                os.environ[env_var] = val  # hot-reload without restart
                updated.append(short_name)
        _write_env_file(env)
        logger.info(f"[AdminAPIKeys] Updated keys: {updated} by {request.user_id}")
        return jsonify({"success": True, "updated": updated})
    except Exception as e:
        logger.error(f"[AdminAPIKeys] Error: {e}")
        return jsonify({"success": False, "error": str(e)}), 500



@admin_bp.route("/api/analytics/usage", methods=["GET"])
def get_usage_analytics():
    """Get usage analytics for the current user."""
    try:
        db = _load_db()
        user_id = request.args.get("user_id", "default")
        chats = db.get("chats", {})
        
        total_messages = 0
        total_chats = 0
        tool_usage = {}
        daily_messages = {}
        
        for chat_id, chat in chats.items():
            if chat.get("user_id", "default") == user_id or user_id == "default":
                total_chats += 1
                messages = chat.get("messages", [])
                total_messages += len(messages)
                
                for msg in messages:
                    # Track daily messages
                    ts = msg.get("timestamp", "")
                    if ts:
                        day = ts[:10]
                        daily_messages[day] = daily_messages.get(day, 0) + 1
                    
                    # Track tool usage from agent actions
                    if msg.get("role") == "assistant":
                        content = msg.get("content", "")
                        for tool_name in ["ssh_execute", "file_write", "file_read", "browser_navigate",
                                         "web_search", "code_interpreter", "generate_file", "generate_image",
                                         "generate_chart", "create_artifact", "edit_image", "generate_design"]:
                            if tool_name in content:
                                tool_usage[tool_name] = tool_usage.get(tool_name, 0) + 1
        
        return jsonify({
            "success": True,
            "analytics": {
                "total_chats": total_chats,
                "total_messages": total_messages,
                "tool_usage": tool_usage,
                "daily_messages": daily_messages
            }
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500



@admin_bp.route("/api/feedback", methods=["POST"])
@require_auth
def submit_feedback():
    """Submit message feedback (thumbs up/down)."""
    try:
        data = request.get_json()
        chat_id = data.get("chat_id", "")
        message_index = data.get("message_index", 0)
        feedback_type = data.get("type", "thumbs_up")  # thumbs_up, thumbs_down
        comment = data.get("comment", "")
        user_id = data.get("user_id", "default")

        db = _load_db()
        feedback_store = db.setdefault("feedback", [])
        entry = {
            "id": str(uuid.uuid4())[:12],
            "chat_id": chat_id,
            "message_index": message_index,
            "type": feedback_type,
            "comment": comment,
            "user_id": user_id,
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
        feedback_store.append(entry)
        db["feedback"] = feedback_store[-10000:]  # Keep last 10k
        _save_db(db)

        # Audit log
        try:
            from security import audit_log
            audit_log(user_id, "feedback", chat_id, {"type": feedback_type})
        except Exception as _audit_err:
            logging.warning(f"Audit log error: {_audit_err}")

        return jsonify({"success": True, "feedback_id": entry["id"]})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500



@admin_bp.route("/api/feedback", methods=["GET"])
@require_auth
def list_feedback():
    """List feedback entries."""
    db = _load_db()
    feedback = db.get("feedback", [])
    return jsonify({"success": True, "feedback": feedback[-100:]})



@admin_bp.route("/api/security/check-prompt", methods=["POST"])
@require_auth
def check_prompt_injection():
    """Check text for prompt injection patterns."""
    try:
        from security import detect_prompt_injection
        data = request.get_json() or {}
        text = data.get("text", "")
        result = detect_prompt_injection(text)
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 500



@admin_bp.route("/api/gdpr/export", methods=["GET"])
@require_auth
def gdpr_export():
    """Export all user data (GDPR Article 20 - Right to Data Portability)."""
    try:
        from security import export_user_data
        user_id = request.args.get("user_id", "default")
        data = export_user_data(user_id, _load_db)
        return jsonify({"success": True, "data": data})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500



@admin_bp.route("/api/gdpr/delete", methods=["DELETE"])
@require_auth
def gdpr_delete():
    """Delete all user data (GDPR Article 17 - Right to Erasure)."""
    try:
        from security import delete_user_data
        user_id = request.args.get("user_id", "default")
        result = delete_user_data(user_id, _load_db, _save_db)
        return jsonify(result)
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500



@admin_bp.route("/api/audit-log", methods=["GET"])
@require_auth
def get_audit_log_api():
    """Get audit log entries."""
    try:
        from security import get_audit_log
        user_id = request.args.get("user_id")
        action = request.args.get("action")
        limit = int(request.args.get("limit", 100))
        entries = get_audit_log(user_id, action, limit)
        return jsonify({"success": True, "entries": entries})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500



@admin_bp.route("/api/audit/logs", methods=["GET"])
@require_auth
def get_audit_logs():
    """Get audit logs with filtering."""
    try:
        from security import get_audit_log
        filter_type = request.args.get("filter", "all")
        limit = int(request.args.get("limit", 100))
        action_filter = None if filter_type == "all" else filter_type
        entries = get_audit_log(action=action_filter, limit=limit)
        logs = [{"type": e.get("action", "system"), "action": e.get("action", ""), "event": e.get("event", ""), "details": e.get("details", ""), "ip": e.get("ip", ""), "timestamp": e.get("timestamp", "")} for e in entries]
        return jsonify({"success": True, "logs": logs})
    except Exception as e:
        return jsonify({"success": True, "logs": []})



@admin_bp.route("/api/audit/export", methods=["GET"])
@require_auth
def export_audit_logs():
    """Export full audit log."""
    try:
        from security import get_audit_log
        entries = get_audit_log(limit=10000)
        return jsonify({"success": True, "logs": entries, "exported_at": datetime.now(timezone.utc).isoformat()})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500



@admin_bp.route("/api/analytics/costs", methods=["GET"])
@require_auth
def get_model_cost_analytics():
    """Get model routing cost analytics."""
    try:
        days = int(request.args.get("days", 30))
        user_id = request.args.get("user_id", request.user_id)
        analytics = get_cost_analytics(user_id=user_id, days=days)
        return jsonify({"success": True, "analytics": analytics})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500



@admin_bp.route("/api/gdpr/anonymize", methods=["POST"])
@require_auth
def gdpr_anonymize_data():
    """GDPR: Anonymize user data."""
    try:
        db = _load_db()
        for chat in db.get("chats", []):
            for msg in chat.get("messages", []):
                if msg.get("role") == "user":
                    msg["content"] = "[ANONYMIZED]"
        users = db.get("users", {})
        for uid, user in users.items():
            user["name"] = "Anonymous"
            user["email"] = f"anon_{uid[:8]}@anonymized.local"
        _save_db(db)
        return jsonify({"success": True, "message": "Data anonymized"})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500



# ── ФИЧА 10: SSE подписка на обновления чата ──

@admin_bp.route("/api/cost/analytics", methods=["GET"])
@require_auth
def get_cost_analytics_api():
    """Аналитика стоимости за период."""
    try:
        from model_router import get_cost_analytics
        days = int(request.args.get("days", 30))
        analytics = get_cost_analytics(user_id=request.user_id, days=days)
        return jsonify({"success": True, "analytics": analytics})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


