"""
ORION Digital — Auth Routes Blueprint
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
import uuid

# Import shared state and helpers
from shared import (
    app, db_read, db_write, require_auth, require_admin,
    _now_iso, _calc_cost, _get_memory, _get_versions, _get_rate_limiter,
    _encrypt_setting, _decrypt_setting, _SECRET_SETTINGS_KEYS,
    _running_tasks, _tasks_lock, _interrupt_lock, _active_agents, _agents_lock,
    OPENROUTER_API_KEY, OPENROUTER_BASE_URL, DATA_DIR, UPLOAD_DIR,
    _lock, _USE_SQLITE,
    _LOGIN_LOCKS, _LOGIN_LOCK_MAX, _LOGIN_LOCK_DURATION, _login_lock_mutex,
    CHAT_MODELS, MODEL_CONFIGS,
)

import bcrypt
import secrets
from ssh_executor import SSHExecutor

auth_bp = Blueprint("auth", __name__)


def _check_login_lock(email: str):
    """Проверяет блокировку логина. Возвращает (ok, message)."""
    with _login_lock_mutex:
        info = _LOGIN_LOCKS.get(email, {})
        locked_until = info.get("locked_until", 0)
        if locked_until and time.time() < locked_until:
            remaining = int(locked_until - time.time())
            return False, f"Аккаунт заблокирован на {remaining // 60} мин {remaining % 60} сек из-за множества неудачных попыток"
        return True, ""


def _record_failed_login(email: str):
    """Записывает неудачную попытку входа."""
    with _login_lock_mutex:
        info = _LOGIN_LOCKS.get(email, {"attempts": 0, "locked_until": 0})
        # Сбрасываем если блокировка истекла
        if info.get("locked_until", 0) and time.time() >= info["locked_until"]:
            info = {"attempts": 0, "locked_until": 0}
        info["attempts"] = info.get("attempts", 0) + 1
        if info["attempts"] >= _LOGIN_LOCK_MAX:
            info["locked_until"] = time.time() + _LOGIN_LOCK_DURATION
            logging.warning(f"[LoginLock] {email} заблокирован на {_LOGIN_LOCK_DURATION // 60} мин после {info['attempts']} попыток")
        _LOGIN_LOCKS[email] = info


def _reset_login_lock(email: str):
    """Сбрасывает счётчик неудачных попыток после успешного входа."""
    with _login_lock_mutex:
        _LOGIN_LOCKS.pop(email, None)


@auth_bp.route("/api/auth/login", methods=["POST"])
def login():
    """Authenticate user and return session token."""
    data = request.get_json() or {}
    email = (data.get("email") or data.get("username") or "").strip().lower()
    password = data.get("password", "")

    if not email or not password:
        return jsonify({"error": "Email and password required"}), 400

    # Check login lock
    ok, lock_msg = _check_login_lock(email)
    if not ok:
        return jsonify({"error": lock_msg}), 429

    db = db_read()
    # ══ SECURITY FIX 1: bcrypt with SHA256 migration ══
    user = None
    user_id = None
    for uid, u in db["users"].items():
        if u["email"].lower() == email:
            stored_hash = u.get("password_hash", "")
            if stored_hash.startswith("$2b$") or stored_hash.startswith("$2a$"):
                # Already bcrypt — use checkpw
                if bcrypt.checkpw(password.encode(), stored_hash.encode()):
                    user = u
                    user_id = uid
            else:
                # Legacy SHA256 — check and migrate to bcrypt
                sha_hash = hashlib.sha256(password.encode()).hexdigest()
                if stored_hash == sha_hash:
                    new_hash = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
                    u["password_hash"] = new_hash
                    db_write(db)
                    logger.info(f"[SECURITY] Migrated password for {email} from SHA256 to bcrypt")
                    user = u
                    user_id = uid
            break
    if not user:
        _record_failed_login(email)
        return jsonify({"error": "Invalid credentials"}), 401

    if not user.get("is_active", True):
        return jsonify({"error": "Account is blocked"}), 403

    _reset_login_lock(email)
    token = secrets.token_hex(32)
    db["sessions"][token] = {
        "user_id": user_id,
        "created_at": time.time(),
        "expires_at": time.time() + 86400 * 7  # 7 days
    }
    db_write(db)

    # ══ SECURITY FIX 2: HttpOnly cookie ══
    from flask import make_response as _make_resp
    resp_data = {
        "token": token,
        "user": {
            "id": user_id,
            "email": user["email"],
            "name": user["name"],
            # BUG-BACKEND-2 FIX: frontend expects username/full_name
            "username": user["email"],
            "full_name": user["name"],
            "role": user.get("role", "user"),
            "settings": {k: ("***" if k in _SECRET_SETTINGS_KEYS and v else v) for k, v in user.get("settings", {}).items()}
        }
    }
    resp = _make_resp(jsonify(resp_data))
    resp.set_cookie("orion_token", token,
        httponly=True, secure=True, samesite="Lax",
        max_age=86400 * 7, path="/")
    return resp



@auth_bp.route("/api/auth/logout", methods=["POST"])
@require_auth
def logout():
    """Invalidate session."""
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    db = db_read()
    db["sessions"].pop(token, None)
    db_write(db)
    # ══ SECURITY FIX 2: Clear HttpOnly cookie on logout ══
    from flask import make_response as _make_resp_logout
    resp = _make_resp_logout(jsonify({"ok": True}))
    resp.delete_cookie("orion_token", path="/")
    return resp



@auth_bp.route("/api/auth/me", methods=["GET"])
@require_auth
def get_me():
    """Get current user info."""
    user = request.user
    total_spent = user.get("total_spent", 0.0)
    monthly_limit = user.get("monthly_limit", 999999)
    limit_pct = round(total_spent / max(monthly_limit, 0.01) * 100, 1) if monthly_limit < 999999 else 0
    _name = user.get("name", user.get("email", ""))
    _email = user.get("email", "")
    # FIX: wrap in {user: {...}} to match frontend contract (api.ts expects { user: User })
    return jsonify({"user": {
        "id": request.user_id,
        "email": _email,
        "name": _name,
        "username": _email,
        "full_name": _name,
        "role": user.get("role", "user"),
        "settings": {k: ("***" if k in _SECRET_SETTINGS_KEYS and v else v) for k, v in user.get("settings", {}).items()},
        "total_spent": total_spent,
        "total_spent_rub": round(total_spent * 105, 2),
        "monthly_limit": monthly_limit,
        "monthly_limit_rub": round(monthly_limit * 105, 2) if monthly_limit < 999999 else None,
        "limit_used_percent": limit_pct,
        "balance_remaining": round((monthly_limit - total_spent) * 105, 2) if monthly_limit < 999999 else None
    }})


# ── Settings ───────────────────────────────────────────────────

@auth_bp.route("/api/settings", methods=["GET"])
@require_auth
def get_settings():
    """Get user settings and available configurations."""
    user = request.user
    return jsonify({
        "settings": user.get("settings", {}),
        "model_configs": {
            k: {
                "name": v["name"],
                "emoji": v["emoji"],
                "coding_model": v["coding"]["name"],
                "quality": v["quality"],
                "monthly_cost": v["monthly_cost"]
            } for k, v in MODEL_CONFIGS.items()
        },
        "chat_models": {
            k: {
                "name": v["name"],
                "lang": v["lang"]
            } for k, v in CHAT_MODELS.items()
        }
    })



@auth_bp.route("/api/settings", methods=["PUT"])
@require_auth
def update_settings():
    """Update user settings."""
    data = request.get_json() or {}
    db = db_read()
    user = db["users"].get(request.user_id, {})

    allowed_keys = {"variant", "chat_model", "enhanced_mode", "self_check_level", "design_pro", "language",
                    "ssh_host", "ssh_user", "ssh_password", "github_token", "n8n_url", "n8n_api_key"}

    settings = user.get("settings", {})
    for key in allowed_keys:
        if key in data:
            # ══ SECURITY FIX 7: Encrypt secret settings ══
            if key in _SECRET_SETTINGS_KEYS and data[key]:
                settings[key] = _encrypt_setting(data[key])
            else:
                settings[key] = data[key]

    user["settings"] = settings
    db["users"][request.user_id] = user
    db_write(db)

    return jsonify({"ok": True, "settings": settings})


# ── SSH Server Management ──────────────────────────────────────

@auth_bp.route("/api/ssh/servers", methods=["GET"])
@require_auth
def list_ssh_servers():
    """List saved SSH servers for current user."""
    db = db_read()
    servers = db.get("ssh_servers", {})
    user_servers = {k: v for k, v in servers.items() if v.get("user_id") == request.user_id}
    # Hide passwords in response
    safe_servers = {}
    for k, v in user_servers.items():
        safe_servers[k] = {**v, "password": "***" if v.get("password") else None}
    return jsonify({"servers": safe_servers})



@auth_bp.route("/api/ssh/servers", methods=["POST"])
@require_auth
def add_ssh_server():
    """Add a new SSH server."""
    data = request.get_json() or {}
    server_id = str(uuid.uuid4())[:8]

    db = db_read()
    if "ssh_servers" not in db:
        db["ssh_servers"] = {}

    db["ssh_servers"][server_id] = {
        "id": server_id,
        "user_id": request.user_id,
        "name": data.get("name", data.get("host", "Server")),
        "host": data.get("host", ""),
        "port": data.get("port", 22),
        "username": data.get("username", "root"),
        "password": data.get("password", ""),
        "created_at": datetime.now(timezone.utc).isoformat()
    }
    db_write(db)
    return jsonify({"ok": True, "server_id": server_id}), 201



@auth_bp.route("/api/ssh/servers/<server_id>", methods=["DELETE"])
@require_auth
def delete_ssh_server(server_id):
    """Delete an SSH server."""
    db = db_read()
    servers = db.get("ssh_servers", {})
    if server_id in servers and servers[server_id].get("user_id") == request.user_id:
        del servers[server_id]
        db["ssh_servers"] = servers
        db_write(db)
        return jsonify({"ok": True})
    return jsonify({"error": "Server not found"}), 404



@auth_bp.route("/api/ssh/test", methods=["POST"])
@require_auth
def test_ssh_connection():
    """Test SSH connection to a server."""
    data = request.get_json() or {}
    host = data.get("host", "")
    username = data.get("username", "root")
    password = data.get("password", "")
    port = data.get("port", 22)

    if not host:
        return jsonify({"error": "Host is required"}), 400

    try:
        ssh = SSHExecutor(host=host, username=username, password=password, port=port, timeout=10)
        result = ssh.connect()
        if result["success"]:
            # Get server info
            info = ssh.execute_command("uname -a && hostname && uptime")
            ssh.disconnect()
            return jsonify({
                "success": True,
                "message": f"Connected to {host}",
                "server_info": info.get("stdout", "")
            })
        else:
            return jsonify({"success": False, "error": result.get("error", "Connection failed")})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})


# ── Chats ──────────────────────────────────────────────────────
