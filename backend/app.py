"""
ORION Digital v1.0 — Backend API Server
Автономный AI-инженер с мультиагентной системой, SSH executor,
browser agent, долговременной памятью, file versioning, rate limiting,
contracts validation, self-healing 2.0, LangGraph StateGraph.
v6.0: Creative Suite, Web Search, Memory & Projects, Canvas, Multi-Model Routing.
"""

import os
try:
    from dotenv import load_dotenv
    load_dotenv("/var/www/orion/backend/.env")
except ImportError:
    pass
import sys
import json
import time
import uuid
import hashlib
import secrets
import threading
import zipfile
import tarfile
import tempfile
import mimetypes
import re
from datetime import datetime, timezone
from functools import wraps
from flask import Flask, request, jsonify, Response, stream_with_context
import requests as http_requests

# Add backend dir to path for imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from agent_loop import AgentLoop, MultiAgentLoop

# ORION Orchestrator v2 — умный планировщик задач
try:
    from orchestrator_v2 import (
        Orchestrator, get_agent_prompt, get_model_for_agent as orch_get_model,
        get_model_id, format_plan_sse, AGENT_PROMPTS, MODEL_MAP
    )
    _ORCHESTRATOR_AVAILABLE = True
except ImportError as _orch_err:
    logger.warning(f"Orchestrator v2 not available: {_orch_err}")
    _ORCHESTRATOR_AVAILABLE = False
from ssh_executor import SSHExecutor, ssh_pool
from browser_agent import BrowserAgent
from memory import get_memory, MemoryEntry, MemoryType
from file_versioning import get_version_store
from rate_limiter import get_rate_limiter, ToolContracts
from file_generator import (
    generate_file, get_file_info, get_file_path, list_files as list_generated_files,
    cleanup_old_files, GENERATED_DIR
)
from file_reader import read_file as read_any_file, FileReadResult, get_supported_formats
from model_router import select_model, classify_complexity, log_cost, get_cost_analytics, get_fallback_model
from specialized_agents import SPECIALIZED_AGENTS, select_agents_for_task, get_agent_pipeline, get_all_agents
from parallel_agents import ParallelAgentOrchestrator
from project_memory import ProjectMemory
import logging

# ═══ LOGGING: File + Console ═══
logging.basicConfig(
    level=logging.INFO,
    handlers=[
        logging.FileHandler("/var/log/orion-backend.log"),
        logging.StreamHandler()
    ],
    format="%(asctime)s %(levelname)s %(name)s: %(message)s"
)

app = Flask(__name__)
app.secret_key = secrets.token_hex(32)
app.config['MAX_CONTENT_LENGTH'] = 100 * 1024 * 1024  # 100MB max

@app.after_request
def security_headers(response):
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'SAMEORIGIN'
    response.headers['X-XSS-Protection'] = '1; mode=block'
    response.headers['Strict-Transport-Security'] = 'max-age=31536000; includeSubDomains'
    return response

# ── Configuration ──────────────────────────────────────────────
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY", "")
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1/chat/completions"

DATA_DIR = os.environ.get("DATA_DIR", "/var/www/orion/backend/data")
UPLOAD_DIR = os.environ.get("UPLOAD_DIR", "/var/www/orion/backend/uploads")
os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(GENERATED_DIR, exist_ok=True)

# SQLite database (migrated from JSON)
try:
    from database import load_db as _sqlite_load, save_db as _sqlite_save, init_db
    _USE_SQLITE = True
except ImportError:
    _USE_SQLITE = False

DB_FILE = os.path.join(DATA_DIR, "database.json")
_lock = threading.Lock()

# Active agent loops (for stop functionality)
_active_agents = {}
_agents_lock = threading.Lock()

# ══ TASK PERSISTENCE: running tasks buffer for SSE reconnect ══
# Each entry: {chat_id: {"status": "running"|"done", "events": [...], "started_at": float, "user_id": str}}
_running_tasks = {}
_tasks_lock = threading.Lock()

# Singletons for new modules
_vector_memory = None
_version_store = None
_rate_limiter = None

def _get_memory():
    global _vector_memory
    if _vector_memory is None:
        _vector_memory = get_memory()
    return _vector_memory

def _get_versions():
    global _version_store
    if _version_store is None:
        _version_store = get_version_store()
    return _version_store

def _get_rate_limiter():
    global _rate_limiter
    if _rate_limiter is None:
        _rate_limiter = get_rate_limiter()
    return _rate_limiter

# ── Model Configurations ──────────────────────────────────────
MODEL_CONFIGS = {
    "original": {
        "name": "Оригинал",
        "emoji": "🔴",
        "coding": {"model": "openai/gpt-4.1-mini", "name": "Grok Code Fast 1", "input_price": 0.20, "output_price": 1.50},
        "planner": {"model": "anthropic/claude-sonnet-4.6", "name": "Claude Sonnet 4.6", "input_price": 3.00, "output_price": 15.00},
        "tools": {"model": "openai/gpt-4.1-mini", "name": "GPT-4.1 Mini", "input_price": 0.26, "output_price": 0.38},
        "quality": 72.1,
        "monthly_cost": "$2,200"
    },
    "premium": {
        "name": "Премиум",
        "emoji": "🟢",
        "coding": {"model": "openai/gpt-4.1-mini", "name": "MiniMax M2.5", "input_price": 0.27, "output_price": 0.95},
        "planner": {"model": "anthropic/claude-sonnet-4.6", "name": "Claude Sonnet 4.6", "input_price": 3.00, "output_price": 15.00},
        "tools": {"model": "openai/gpt-4.1-mini", "name": "GPT-4.1 Mini", "input_price": 0.26, "output_price": 0.38},
        "quality": 80.2,
        "monthly_cost": "$1,750"
    },
    "budget": {
        "name": "Бюджет",
        "emoji": "🔵",
        "coding": {"model": "openai/gpt-4.1-mini", "name": "GPT-4.1 Mini", "input_price": 0.26, "output_price": 0.38},
        "planner": {"model": "openai/gpt-4.1-mini", "name": "GPT-4.1 Mini", "input_price": 0.40, "output_price": 1.75},
        "tools": {"model": "openai/gpt-4.1-mini", "name": "GPT-4.1 Mini", "input_price": 0.26, "output_price": 0.38},
        "quality": 75.8,
        "monthly_cost": "$750"
    }
}

CHAT_MODELS = {
    "qwen3": {"model": "openai/gpt-4.1-mini", "name": "GPT-4.1 Mini", "lang": "RU ⭐⭐⭐⭐⭐", "input_price": 0.10, "output_price": 0.60},
    "deepseek": {"model": "openai/gpt-4.1-nano", "name": "GPT-4.1 Mini", "lang": "RU ⭐⭐⭐⭐⭐", "input_price": 0.26, "output_price": 0.38},
    "gpt5nano": {"model": "openai/gpt-4.1-nano", "name": "GPT-5 Nano", "lang": "RU ⭐⭐⭐⭐", "input_price": 0.05, "output_price": 0.40},
}

# ── File processing constants ─────────────────────────────────
TEXT_EXTENSIONS = {
    '.py', '.js', '.ts', '.jsx', '.tsx', '.html', '.css', '.scss', '.less',
    '.json', '.xml', '.yaml', '.yml', '.toml', '.ini', '.cfg', '.conf',
    '.md', '.txt', '.rst', '.csv', '.tsv', '.log',
    '.sh', '.bash', '.zsh', '.bat', '.cmd', '.ps1',
    '.sql', '.graphql', '.gql',
    '.java', '.kt', '.scala', '.groovy',
    '.c', '.cpp', '.h', '.hpp', '.cs',
    '.go', '.rs', '.rb', '.php', '.pl', '.pm',
    '.swift', '.m', '.mm', '.r', '.R', '.jl',
    '.lua', '.vim', '.el',
    '.dockerfile', '.dockerignore', '.gitignore', '.env', '.env.example',
    '.vue', '.svelte', '.astro', '.tf', '.hcl',
    '.proto', '.thrift', '.makefile', '.cmake', '.lock', '.sum',
}

SKIP_EXTENSIONS = {
    '.png', '.jpg', '.jpeg', '.gif', '.bmp', '.ico', '.svg', '.webp',
    '.mp3', '.mp4', '.wav', '.avi', '.mov', '.mkv',
    '.pdf', '.doc', '.docx', '.xls', '.xlsx', '.ppt', '.pptx',
    '.exe', '.dll', '.so', '.dylib', '.bin',
    '.woff', '.woff2', '.ttf', '.eot', '.otf',
    '.pyc', '.pyo', '.class', '.o', '.obj',
    '.db', '.sqlite', '.sqlite3',
}

SKIP_DIRS = {
    'node_modules', '.git', '__pycache__', '.venv', 'venv',
    'dist', 'build', '.next', '.nuxt', 'vendor',
    '.idea', '.vscode', '.DS_Store',
}

# ── Database Layer ─────────────────────────────────────────────────────

_DEFAULT_DB = {
    "users": {
        "admin": {
            "id": "admin",
            "email": "ym@mksmedia.ru",
            "password_hash": hashlib.sha256(
                os.environ.get("ORION_ADMIN_PASSWORD", "qwerty1985").encode()
            ).hexdigest(),  # BUG-4 FIX: пароль из env ORION_ADMIN_PASSWORD
            "name": "Администратор",
            "role": "admin",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "is_active": True,
            "monthly_limit": 999999,
            "total_spent": 0.0,
            "settings": {
                "variant": "premium",
                "chat_model": "qwen3",
                "enhanced_mode": False,
                "self_check_level": "none",
                "design_pro": False,
                "language": "ru"
            }
        }
    },
    "sessions": {},
    "chats": {},
    "ssh_servers": {},
    "analytics": {
        "total_requests": 0,
        "total_tokens_in": 0,
        "total_tokens_out": 0,
        "total_cost": 0.0,
        "daily_stats": {}
    },
    "memory": {
        "episodic": [],
        "semantic": {},
        "procedural": {}
    }
}


def _load_db():
    """Load database — SQLite primary, JSON fallback."""
    if _USE_SQLITE:
        try:
            data = _sqlite_load()
            if data and data.get("users"):
                return data
        except Exception as e:
            logging.warning(f"SQLite load failed, falling back to JSON: {e}")
    # JSON fallback
    try:
        with open(DB_FILE, "r") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return _DEFAULT_DB.copy()


def _save_db(db):
    """Save database — SQLite primary, JSON fallback."""
    if _USE_SQLITE:
        try:
            _sqlite_save(db)
            return
        except Exception as e:
            logging.warning(f"SQLite save failed, falling back to JSON: {e}")
    # JSON fallback
    tmp = DB_FILE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(db, f, ensure_ascii=False, indent=2)
    os.replace(tmp, DB_FILE)


def db_read():
    with _lock:
        return _load_db()


def db_write(db):
    with _lock:
        _save_db(db)


# ── Authentication ─────────────────────────────────────────────
def require_auth(f):
    """Decorator to require valid session token."""
    @wraps(f)
    def decorated(*args, **kwargs):
        token = request.headers.get("Authorization", "").replace("Bearer ", "")
        if not token:
            token = request.cookies.get("session_token", "")
        if not token:
            return jsonify({"error": "Unauthorized"}), 401
        db = db_read()
        session = db["sessions"].get(token)
        if not session:
            return jsonify({"error": "Invalid session"}), 401
        if time.time() > session.get("expires_at", 0):
            del db["sessions"][token]
            db_write(db)
            return jsonify({"error": "Session expired"}), 401
        request.user_id = session["user_id"]
        request.user = db["users"].get(session["user_id"], {})
        return f(*args, **kwargs)
    return decorated


def require_admin(f):
    """Decorator to require admin role."""
    @wraps(f)
    def decorated(*args, **kwargs):
        if request.user.get("role") != "admin":
            return jsonify({"error": "Admin access required"}), 403
        return f(*args, **kwargs)
    return decorated



# ── Login Lock (5 попыток = блокировка 15 мин) ────────────────
_LOGIN_LOCKS = {}  # {email: {"attempts": N, "locked_until": timestamp}}
_LOGIN_LOCK_MAX = 5
_LOGIN_LOCK_DURATION = 15 * 60  # 15 минут
_login_lock_mutex = threading.Lock()

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

@app.route("/api/auth/login", methods=["POST"])
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
    password_hash = hashlib.sha256(password.encode()).hexdigest()

    user = None
    user_id = None
    for uid, u in db["users"].items():
        if u["email"].lower() == email and u["password_hash"] == password_hash:
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

    return jsonify({
        "token": token,
        "user": {
            "id": user_id,
            "email": user["email"],
            "name": user["name"],
            # BUG-BACKEND-2 FIX: frontend expects username/full_name
            "username": user["email"],
            "full_name": user["name"],
            "role": user.get("role", "user"),
            "settings": user.get("settings", {})
        }
    })


@app.route("/api/auth/logout", methods=["POST"])
@require_auth
def logout():
    """Invalidate session."""
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    db = db_read()
    db["sessions"].pop(token, None)
    db_write(db)
    return jsonify({"ok": True})


@app.route("/api/auth/me", methods=["GET"])
@require_auth
def get_me():
    """Get current user info."""
    user = request.user
    total_spent = user.get("total_spent", 0.0)
    monthly_limit = user.get("monthly_limit", 999999)
    limit_pct = round(total_spent / max(monthly_limit, 0.01) * 100, 1) if monthly_limit < 999999 else 0
    _name = user.get("name", user.get("email", ""))
    _email = user.get("email", "")
    return jsonify({
        "id": request.user_id,
        "email": _email,
        "name": _name,
        # BUG-BACKEND-1 FIX: frontend expects username/full_name
        "username": _email,
        "full_name": _name,
        "role": user.get("role", "user"),
        "settings": user.get("settings", {}),
        "total_spent": total_spent,
        "total_spent_rub": round(total_spent * 105, 2),
        "monthly_limit": monthly_limit,
        "monthly_limit_rub": round(monthly_limit * 105, 2) if monthly_limit < 999999 else None,
        "limit_used_percent": limit_pct,
        "balance_remaining": round((monthly_limit - total_spent) * 105, 2) if monthly_limit < 999999 else None
    })


# ── Settings ───────────────────────────────────────────────────
@app.route("/api/settings", methods=["GET"])
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


@app.route("/api/settings", methods=["PUT"])
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
            settings[key] = data[key]

    user["settings"] = settings
    db["users"][request.user_id] = user
    db_write(db)

    return jsonify({"ok": True, "settings": settings})


# ── SSH Server Management ──────────────────────────────────────
@app.route("/api/ssh/servers", methods=["GET"])
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


@app.route("/api/ssh/servers", methods=["POST"])
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


@app.route("/api/ssh/servers/<server_id>", methods=["DELETE"])
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


@app.route("/api/ssh/test", methods=["POST"])
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
@app.route("/api/chats", methods=["GET"])
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


@app.route("/api/chats", methods=["POST"])
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
        "agent_actions": []
    }

    db["chats"][chat_id] = chat
    db_write(db)

    return jsonify({"chat": chat}), 201


@app.route("/api/chats/<chat_id>", methods=["GET"])
@require_auth
def get_chat(chat_id):
    """Get chat with all messages."""
    db = db_read()
    chat = db["chats"].get(chat_id)
    if not chat or chat.get("user_id") != request.user_id:
        if request.user.get("role") != "admin":
            return jsonify({"error": "Chat not found"}), 404
    return jsonify({"chat": chat})


@app.route("/api/chats/<chat_id>", methods=["DELETE"])
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


@app.route("/api/chats/<chat_id>/rename", methods=["PUT"])
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
def is_text_file(filename):
    name_lower = filename.lower()
    _, ext = os.path.splitext(name_lower)
    if ext in TEXT_EXTENSIONS:
        return True
    if ext in SKIP_EXTENSIONS:
        return False
    basename = os.path.basename(name_lower)
    text_names = {
        'makefile', 'dockerfile', 'vagrantfile', 'gemfile', 'rakefile',
        'procfile', 'readme', 'license', 'changelog', 'authors',
    }
    return basename in text_names or not ext


def read_file_content(filepath, max_size=100000):
    try:
        size = os.path.getsize(filepath)
        if size > max_size:
            with open(filepath, 'r', errors='replace') as f:
                return f"[File too large: {size} bytes, first {max_size} bytes]\n" + f.read(max_size)
        with open(filepath, 'r', errors='replace') as f:
            content = f.read()
        if '\x00' in content[:1000]:
            return None
        return content
    except Exception:
        return None


def process_directory(dirpath, base_path=""):
    result = []
    file_count = 0
    max_files = 50
    max_total_chars = 200000
    total_chars = 0

    for root, dirs, files in os.walk(dirpath):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        dirs.sort()
        files.sort()

        for fname in files:
            if file_count >= max_files:
                result.append(f"\n... [{file_count}+ files, showing first {max_files}]")
                return result, file_count

            fpath = os.path.join(root, fname)
            rel_path = os.path.relpath(fpath, dirpath)
            if base_path:
                rel_path = os.path.join(base_path, rel_path)

            if is_text_file(fname):
                content = read_file_content(fpath)
                if content is not None:
                    if total_chars + len(content) > max_total_chars:
                        remaining = max_total_chars - total_chars
                        if remaining > 500:
                            content = content[:remaining] + "\n... [truncated]"
                        else:
                            result.append(f"\n... [Content limit reached at {file_count} files]")
                            return result, file_count
                    _, ext = os.path.splitext(fname)
                    lang = ext.lstrip('.') if ext else 'text'
                    result.append(f"\n### File: `{rel_path}`\n```{lang}\n{content}\n```")
                    total_chars += len(content)
                    file_count += 1

    return result, file_count


def process_uploaded_file(file_storage):
    """Process uploaded file using UniversalFileReader for rich content extraction."""
    filename = file_storage.filename or "unknown"
    _, ext = os.path.splitext(filename.lower())

    tmp_dir = tempfile.mkdtemp(dir=UPLOAD_DIR)
    filepath = os.path.join(tmp_dir, filename)
    file_storage.save(filepath)

    # Store filepath for agent tools (read_any_file, analyze_image)
    file_id = str(uuid.uuid4())[:12]
    file_meta = {
        "id": file_id,
        "filename": filename,
        "filepath": filepath,
        "ext": ext,
        "size": os.path.getsize(filepath),
        "uploaded_at": datetime.now(timezone.utc).isoformat()
    }

    # Try UniversalFileReader for rich formats
    rich_formats = ['.pdf', '.docx', '.doc', '.xlsx', '.xls', '.pptx', '.ppt',
                    '.png', '.jpg', '.jpeg', '.gif', '.bmp', '.webp', '.svg',
                    '.csv', '.json', '.xml', '.yaml', '.yml', '.md', '.html']

    if ext in rich_formats:
        try:
            result = read_any_file(filepath)
            if not result.error:
                content = result.text or ''
                tables = result.tables or []
                metadata = result.metadata or {}

                parts = [f"📄 **{filename}** ({result.file_type})"]
                if result.pages_count:
                    parts.append(f"**Страниц:** {result.pages_count}")
                if metadata:
                    meta_str = ", ".join(f"{k}: {v}" for k, v in list(metadata.items())[:5])
                    parts.append(f"**Метаданные:** {meta_str}")
                if tables:
                    parts.append(f"\n**Таблицы ({len(tables)}):**")
                    for i, tbl in enumerate(tables[:3]):
                        if isinstance(tbl, list):
                            # Table is list of rows
                            parts.append(f"\n*Таблица {i+1}:*\n{str(tbl)[:2000]}")
                        elif isinstance(tbl, dict):
                            parts.append(f"\n*Таблица {i+1}:*\n{tbl.get('markdown', tbl.get('text', str(tbl)))}")
                        else:
                            parts.append(f"\n*Таблица {i+1}:*\n{str(tbl)[:2000]}")
                if content:
                    if len(content) > 30000:
                        content = content[:30000] + f"\n... [обрезано, всего {len(content)} символов]"
                    parts.append(f"\n**Содержимое:**\n{content}")

                # Auto-summary: generate brief summary of file content
                summary = ""
                if content and len(content) > 100:
                    # Simple extractive summary: first 2 sentences
                    sentences = content.replace('\n', ' ').split('.')
                    summary = '. '.join(s.strip() for s in sentences[:3] if s.strip())
                    if summary:
                        summary = summary[:300] + ('...' if len(summary) > 300 else '')
                        parts.insert(1, f"**Краткое содержание:** {summary}")

                # Save file_meta for agent access
                file_meta['content_preview'] = content[:500] if content else ''
                file_meta['summary'] = summary
                file_meta['has_tables'] = len(tables) > 0
                _save_uploaded_file_meta(file_meta)

                return "\n".join(parts)
        except Exception as e:
            pass  # Fall through to legacy processing

    # Legacy: archives
    if ext == '.zip':
        extract_dir = os.path.join(tmp_dir, "extracted")
        os.makedirs(extract_dir, exist_ok=True)
        try:
            with zipfile.ZipFile(filepath, 'r') as zf:
                zf.extractall(extract_dir)
            parts, count = process_directory(extract_dir, filename)
            return f"📦 **Архив: {filename}** ({count} файлов)\n" + "\n".join(parts)
        except Exception as e:
            return f"❌ Ошибка при распаковке {filename}: {str(e)}"

    elif ext in ('.tar', '.gz', '.tgz', '.bz2'):
        extract_dir = os.path.join(tmp_dir, "extracted")
        os.makedirs(extract_dir, exist_ok=True)
        try:
            with tarfile.open(filepath, 'r:*') as tf:
                tf.extractall(extract_dir)
            parts, count = process_directory(extract_dir, filename)
            return f"📦 **Архив: {filename}** ({count} файлов)\n" + "\n".join(parts)
        except Exception as e:
            return f"❌ Ошибка при распаковке {filename}: {str(e)}"

    elif is_text_file(filename):
        content = read_file_content(filepath)
        if content:
            lang = ext.lstrip('.') if ext else 'text'
            _save_uploaded_file_meta(file_meta)
            return f"📄 **Файл: {filename}**\n```{lang}\n{content}\n```"
        return f"📄 **Файл: {filename}** [не удалось прочитать]"

    _save_uploaded_file_meta(file_meta)
    return f"📎 **Файл: {filename}** ({ext or 'unknown'} — бинарный файл, сохранён для анализа)\n[Путь: {filepath}]"


# ── Uploaded files metadata store ──
_uploaded_files = {}  # file_id -> file_meta

def _save_uploaded_file_meta(meta):
    """Save uploaded file metadata for agent tool access."""
    _uploaded_files[meta['id']] = meta

def _get_uploaded_file_path(file_id):
    """Get filepath by file_id."""
    meta = _uploaded_files.get(file_id)
    return meta.get('filepath') if meta else None


@app.route("/api/upload", methods=["POST"])
@require_auth
def upload_file():
    """Upload file(s) and return processed content with file paths for agent."""
    if 'file' not in request.files:
        return jsonify({"error": "No file provided"}), 400

    files = request.files.getlist('file')
    results = []
    file_paths = []  # For agent tools
    for f in files:
        if f.filename:
            content = process_uploaded_file(f)
            results.append(content)
            # Find the saved filepath from _uploaded_files
            for fid, meta in sorted(_uploaded_files.items(), key=lambda x: x[1].get('uploaded_at', ''), reverse=True):
                if meta['filename'] == f.filename:
                    file_paths.append({"id": fid, "filename": meta['filename'], "filepath": meta['filepath'], "size": meta['size']})
                    break

    return jsonify({
        "content": "\n\n".join(results),
        "file_count": len(results),
        "files": file_paths
    })


@app.route("/api/uploaded-files", methods=["GET"])
@require_auth
def list_uploaded_files():
    """List all uploaded files with metadata."""
    files = []
    for fid, meta in _uploaded_files.items():
        files.append({
            "id": fid,
            "filename": meta['filename'],
            "size": meta['size'],
            "ext": meta['ext'],
            "uploaded_at": meta['uploaded_at'],
            "has_tables": meta.get('has_tables', False)
        })
    return jsonify({"files": sorted(files, key=lambda x: x['uploaded_at'], reverse=True)})


# ══════════════════════════════════════════════════════════════════
# ██ Parse SSH from message text ██
# ══════════════════════════════════════════════════════════════════

def _parse_ssh_from_message(message):
    """
    Parse SSH credentials from user message text.
    Supports formats:
      - root@192.168.1.1 mypassword ...
      - user@hostname password ...
      - root@10.0.0.1 P@ssw0rd! сходи посмотри ...
    Returns dict with host, username, password or None.
    """
    if not message:
        return None

    # Pattern: user@host password
    # IP: digits and dots, or hostname
    # Password: non-space string (can contain special chars)
    m = re.match(
        r'^\s*([a-zA-Z0-9_.-]+)@([a-zA-Z0-9._-]+)\s+(\S+)\s*(.*)',
        message
    )
    if m:
        username = m.group(1)
        host = m.group(2)
        password = m.group(3)
        # Validate host looks like IP or hostname
        if re.match(r'^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$', host) or '.' in host:
            return {
                "host": host,
                "username": username,
                "password": password
            }

    # Pattern: just IP password (assume root)
    m = re.match(
        r'^\s*(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})\s+(\S+)\s*(.*)',
        message
    )
    if m:
        host = m.group(1)
        password = m.group(2)
        return {
            "host": host,
            "username": "root",
            "password": password
        }

    # Pattern: natural language with IP, username, password anywhere in text
    # e.g. "подключись к серверу 1.2.3.4 root пароль123"
    # e.g. "сходи на сервер 10.0.0.1 логин root пароль mypass"
    ip_match = re.search(r'(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})', message)
    if ip_match:
        host = ip_match.group(1)
        rest = message[ip_match.end():].strip()
        # Try: IP username password
        m2 = re.match(r'^\s*(\S+)\s+(\S+)', rest)
        if m2:
            word1 = m2.group(1)
            word2 = m2.group(2)
            # If word1 looks like a username (root, admin, user, etc.)
            if re.match(r'^[a-zA-Z][a-zA-Z0-9_.-]*$', word1) and len(word1) < 32:
                return {"host": host, "username": word1, "password": word2}
            else:
                # word1 is password, assume root
                return {"host": host, "username": "root", "password": word1}
        elif rest:
            # Just one word after IP — treat as password
            word = rest.split()[0]
            return {"host": host, "username": "root", "password": word}

    return None


# ██ LLM ORCHESTRATOR — Intent Detection via AI (not keywords) ██
# ══════════════════════════════════════════════════════════════════

ORCHESTRATOR_PROMPT = """Ты — умный маршрутизатор задач для AI-ассистента. Твоя работа: понять что хочет пользователь и выбрать правильный режим обработки.
ДОСТУПНЫЕ РЕЖИМЫ:
- "chat" — обычный разговор, вопросы, объяснения, советы, идеи, написание кода, конфигов, скриптов, шаблонов
- "file" — создание документов для скачивания: Word (.docx), PDF, Excel (.xlsx), PowerPoint (.pptx), CSV
- "deploy" — реальные действия на серверах: SSH подключение, деплой, установка ПО, настройка сервисов, бэкапы
- "research" — поиск актуальной информации в интернете, текущие цены/курсы/новости, парсинг сайтов, любые данные которые меняются со временем
- "data" — анализ данных, математические расчёты, построение графиков и диаграмм из данных
ПРАВИЛА ВЫБОРА РЕЖИМА (применяй по порядку, первое совпавшее правило побеждает):
1. Если в сообщении есть IP-адрес (например 1.2.3.4) → "deploy"
2. Если есть слово "сервер/VPS/прод/боевой/сервак/серваке" + действие → "deploy"
3. Если запрос заканчивается созданием файла (Word/PDF/Excel/PowerPoint/таблицу/отчёт в файле) → "file", даже если в начале есть "найди/поищи/проверь/проанализируй"
4. Если просят создать бизнес-документ для скачивания (договор, счёт, резюме, отчёт, презентация, инструкция, ТЗ, КП) → "file"
5. Если запрос касается ЛЮБОЙ информации которая меняется со временем или требует актуальных данных из интернета → "research". Это включает:
   - Курсы криптовалют: биткоин, ethereum, BTC, ETH, любые монеты
   - Курсы валют: доллар, евро, рубль, юань, любые валюты
   - Цены на товары, услуги, акции, нефть, золото
   - Погода сейчас или прогноз
   - Новости, события, что происходит
   - Информация о компаниях, людях, организациях из интернета
   - Расписания, время работы, адреса, контакты
   - Рейтинги, отзывы, топ-листы
   - Любые вопросы начинающиеся с "сколько сейчас", "какой сейчас", "что сейчас"
6. Если просят посчитать, построить график/диаграмму ИЗ ДАННЫХ (чисел, файла CSV/Excel) → "data"
7. Всё остальное → "chat"
ВАЖНО — НЕ ПУТАЙ:
- "как задеплоить" / "как установить" / "как настроить" → "chat" (вопрос-инструкция, не действие)
- "задеплой" / "установи" / "настрой" + сервер/VPS/прод → "deploy" (команда к действию)
- Одиночные слова без объекта: "установи", "обнови", "удали", "запусти", "накидай" → "chat" (нет объекта/сервера)
- Команды БЕЗ указания сервера: "установи docker", "установи nginx", "установи node js", "перезапусти nginx", "задеплой приложение", "задеплой сайт", "запусти сервер", "сделай бэкап базы", "настрой ssl", "задеплой приложение" → "chat" (нет сервера — уточнить)
- "создай шаблон" / "напиши шаблон" / "придумай идею" / "накидай варианты" → "chat"
- "создай Word документ" / "сделай PDF" / "напиши резюме" → "file"
- "напиши объявление" / "напиши пост" / "напиши текст" → "chat" (текст в чате, не файл)
- "создай swagger документацию" / "напиши README" / "напиши документацию" → "chat" (текст в чате)
- "напиши инструкцию" → "chat" (текст), "создай PDF инструкцию" / "сделай Word инструкцию" → "file"
- "настрой X" / "обнови X" БЕЗ слова сервер/VPS/прод → "chat" (инструкция, не действие)
- "настрой X на сервере/VPS/проде" → "deploy" (реальное действие)
- "нужно настроить X" / "хочу настроить X" / "помоги настроить X" БЕЗ слова сервер/VPS/прод → "deploy" (пользователь намерен настраивать)
- "нужно задеплоить" / "хочу задеплоить" / "помоги с деплоем" → "deploy" (намерение деплоить)
- "нужно установить X" / "хочу установить X" → "deploy" (намерение установить)
- "нужно создать базу данных" / "создай базу данных" / "сделай базу данных" / "создай таблицу в postgresql" → "deploy" (действие в БД)
- "запили X" (сленг) → "deploy" если X — серверное ПО (докер, nginx, сервис), "chat" если X — код/функция
- "настрой вебхук" / "настрой webhook" → "deploy" (настройка на сервере)
- "настрой https" / "настрой certbot" → "deploy" (настройка SSL на сервере)
- "настрой github actions" / "настрой gitlab ci" → "deploy" (настройка CI/CD)
- "настрой порт X" → "deploy" (настройка порта на сервере)
- "настрой grafana" / "установи prometheus" → "deploy" (установка мониторинга)
- "найди информацию и сделай PDF/Word/Excel" → "file" (конечный результат важнее)
- "найди X и установи на сервер" → "deploy" (конечное действие — деплой)
- "объясни X и задеплой Y" → "deploy" (конечное действие — деплой)
- "создай excel и отправь на сервер" → "deploy" (конечное действие — деплой)
- "поищи хостинг и зарегистрируй домен" → "deploy" (конечное действие — регистрация)
- "открой сайт и сделай скриншот" → "research" (браузер/парсинг)
- "сколько стоит X" / "какая цена X" / "цены на X" → "research" (нужны актуальные данные)
- "какой курс биткоина" / "курс доллара" / "цена эфира" / "btc сейчас" → "research" (актуальные данные)
- "биткоин" / "bitcoin" / "ethereum" / "крипта" / "btc" / "eth" в любом контексте вопроса → "research"
- "погода" / "прогноз погоды" / "температура" → "research" (актуальные данные)
- "новости" / "что нового" / "что происходит" / "последние события" → "research"
- "какой сейчас" / "что сейчас" / "сколько сейчас" → "research" (актуальные данные)
- "найди решение задачи" / "найди ошибку" / "найди способ" → "chat" (поиск в знаниях, не в интернете)
- "найди альтернативы X" → "chat" (поиск в знаниях, не в интернете)
- "сравни X и Y" → "chat" (сравнение из знаний, не поиск в интернете)
- "сделай диаграмму" / "построй график" БЕЗ данных → "chat", С данными/файлом → "data"
- "построй график продаж" / "построй график X" → "data" (визуализация данных)
- "проанализируй логи" → "deploy" (логи на сервере), "проанализируй данные из файла" → "data"
- "проанализируй конкурентов" → "research" (поиск информации в интернете)
- "проанализируй трафик сайта" → "research" (нужны данные из интернета)
- "проверь статус сервисов" / "проверь статус сервиса" → "deploy" (проверка на сервере)
- "сколько места на диске" / "проверь использование памяти" / "покажи запущенные процессы" → "deploy" (проверка сервера)
- "проверь статус сервиса aws" → "research" (проверка статуса онлайн)
- "автоматизируй парсинг" / "напиши парсер" → "chat" (написание кода)
- "автоматизируй отправку отчётов" → "chat" (написание скрипта/кода)
- "протестируй API" → "deploy" (тест на сервере), "напиши тесты" → "chat" (написание кода)
- "создай n8n workflow" (без сервера) → "chat", "установи n8n на сервер" / "установи n8n" / "запусти n8n" → "deploy"
- "установи n8n" / "запусти n8n" / "установи airflow" / "установи jupyter" → "deploy" (установка ПО)
- Короткие ответы: "окей", "понял", "продолжай", "допиши", "объясни по-простому", "привет", "спасибо" → "chat"
- "нарисуй диаграмму/схему" → "chat", "нарисуй баннер/логотип" → "chat" (медиа-генерация)
- "создай .env файл" / "создай requirements.txt" → "chat" (конфиг = текст в чате)
- "интегрируй stripe" / "подключи telegram api" / "создай webhook" → "chat" (написание кода для интеграции)
- "создай ci/cd pipeline" / "создай github actions workflow" / "напиши github actions workflow" → "chat" (написание конфига)
- "создай локальный сервер" / "сделай сайт" / "сделай приложение" / "сделай бота" / "сделай апи" → "chat" (написание кода)
- "запили функцию на питоне" / "запили код" → "chat" (написание кода)
- "покажи в таблице разницу" / "сравни в таблице" → "chat" (ответ в чате)
- "создай таблицу" / "сделай таблицу" БЕЗ уточнения данных → "file" (таблица = документ)
- "сделай таблицу сравнения тарифов" / "сделай таблицу с расписанием" / "сделай таблицу продаж" → "file" (таблица = документ)
- "напиши коммерческое предложение" / "напиши бизнес-план" / "напиши техническое задание" → "file" (бизнес-документ)
Отвечай ТОЛЬКО JSON: {{"mode": "chat|file|deploy|research|data", "confidence": 0.0-1.0}}
Последние сообщения чата (контекст):
{history}
Сообщение пользователя: {message}
Ответь СТРОГО в формате JSON (только JSON, без пояснений):
{{"mode": "chat", "reason": "краткое объяснение на русском", "confidence": 0.95}}"""


def detect_intent_llm(user_message: str, history: list, api_key: str) -> dict:
    """
    Использует LLM для определения намерения пользователя.
    Возвращает dict: {mode, reason, confidence}
    Режимы: chat | file | deploy | research | data
    """
    # Быстрый pre-check: если есть IP-адрес — точно deploy (без вызова LLM)
    if re.search(r'\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b', user_message):
        return {"mode": "deploy", "reason": "IP-адрес в сообщении", "confidence": 1.0}

    # Pre-check: URL + слова лендинг/сайт/создай → file (запускает lite_agent)
    _msg_lower_pre = user_message.lower()
    _has_url_pre = bool(re.search(r'https?://\S+', user_message))
    _landing_kw = ["лендинг", "landing", "сайт", "создай", "сделай", "сгенерируй", "напиши", "скопируй", "сделай сайт", "сделай лендинг"]
    if _has_url_pre and any(kw in _msg_lower_pre for kw in _landing_kw):
        return {"mode": "file", "reason": "URL + лендинг/сайт/создай → lite_agent", "confidence": 0.95}

    # Формируем контекст из последних 3 сообщений
    recent = history[-3:] if history else []
    history_text = "\n".join([
        f"{m['role']}: {m['content'][:120]}"
        for m in recent
    ]) or "нет истории"

    prompt = ORCHESTRATOR_PROMPT.replace("{message}", user_message[:600]).replace("{history}", history_text)

    try:
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://orion.mksitdev.ru",
            "X-Title": "ORION Digital Orchestrator"
        }
        payload = {
            "model": "meta-llama/llama-3.1-70b-instruct",  # Оркестратор: 100% точность, быстрый
            "messages": [
                {"role": "user", "content": prompt}
            ],
            "temperature": 0.1,
            "max_tokens": 80,
        }
        resp = http_requests.post(
            OPENROUTER_BASE_URL, headers=headers, json=payload, timeout=8
        )
        if resp.status_code == 200:
            data = resp.json()
            content = data["choices"][0]["message"]["content"].strip()
            # Извлекаем JSON даже если модель добавила лишний текст
            json_match = re.search(r'\{[^}]+\}', content, re.DOTALL)
            if json_match:
                result = json.loads(json_match.group())
                mode = result.get("mode", "chat")
                if mode not in ("chat", "file", "deploy", "research", "data"):
                    mode = "chat"
                return {
                    "mode": mode,
                    "reason": result.get("reason", ""),
                    "confidence": float(result.get("confidence", 0.8))
                }
    except Exception:
        # Если LLM недоступен — fallback на keyword matching
        pass

    # ── Fallback: keyword matching (если LLM не ответил) ──
    msg_lower = user_message.lower()
    deploy_kw = ["ssh", "apt ", "apt-get", "pip install", "npm install", "docker", "nginx", "systemd", "деплой", "deploy", "разверни на", "установи на сервер"]
    file_kw = ["word", "docx", ".pdf", " pdf", "pdf ", "pdf-", "сделай pdf", "создай pdf", "excel", "xlsx", "powerpoint", "pptx",
                "скачать файл", "создай файл", "сгенерируй файл",
                "сделай документ", "создай документ", "сделай таблицу", "создай таблицу",
                "сделай отчёт", "создай отчёт", "сделай презентацию", "создай презентацию",
                "картинк", "изображен", "баннер", "постер", "иллюстрац",
                "нарисуй", "сделай лого", "создай лого", "сделай иконк", "создай иконк",
                "сделай фото", "создай фото", "generate image", "create image",
                "напиши парсер", "напиши скрипт", "напиши код", "напиши бот",
                "напиши программ", "создай скрипт", "создай api", "напиши функци"]
    research_kw = [
        # Явные команды поиска
        "найди в интернете", "поищи", "web search", "проверь сайт", "открой сайт",
        "посмотри в интернете", "загугли", "найди актуальн", "найди информацию",
        # Криптовалюты
        "биткоин", "bitcoin", "btc", "ethereum", "eth", "solana", "sol",
        "крипто", "crypto", "крипта", "usdt", "usdc", "bnb", "xrp",
        # Валюты и финансы
        "доллар", "евро", "рубль", "юань", "фунт", "иена",
        "акции", "котировки", "нефть", "золото", "серебро",
        # Цены
        "курс ", "цена ", "стоимость ", "сколько стоит",
        "текущий курс", "актуальный курс", "сегодня курс", "цена сейчас",
        "какой курс", "какая цена", "сколько сейчас", "что сейчас с",
        "сравни цены",
        # Погода
        "погода", "прогноз", "температура", "осадки", "ветер",
        # Новости и события
        "новости", "последние новости", "что происходит", "что нового",
        "последние события", "текущие события",
        # Актуальные вопросы
        "узнай", "проверь",
        # Контакты и расписания
        "расписание", "время работы", "адрес", "телефон", "контакты",
        # Рейтинги и отзывы
        "отзывы", "рейтинг", "топ ", "лучшие",
    ]
    data_kw = ["посчитай", "вычисли", "построй график", "анализ данных", "статистика"]
    if any(kw in msg_lower for kw in deploy_kw):
        return {"mode": "deploy", "reason": "fallback keyword", "confidence": 0.7}
    if any(kw in msg_lower for kw in file_kw):
        return {"mode": "file", "reason": "fallback keyword", "confidence": 0.7}
    if any(kw in msg_lower for kw in research_kw):
        return {"mode": "research", "reason": "fallback keyword", "confidence": 0.7}
    if any(kw in msg_lower for kw in data_kw):
        return {"mode": "data", "reason": "fallback keyword", "confidence": 0.7}
    return {"mode": "chat", "reason": "fallback default", "confidence": 0.6}



# ══════════════════════════════════════════════════════════════════
# ██ AGENT LOOP — CORE: AI plans, executes, verifies autonomously ██
# ══════════════════════════════════════════════════════════════════

@app.route("/api/chats/<chat_id>/send", methods=["POST"])
@require_auth
def send_message(chat_id):
    "Send message and get AI response via SSE streaming with agent loop."
    # Rate limiting check
    rl = _get_rate_limiter()
    allowed, rl_info = rl.check_message(request.user_id)
    if not allowed:
        return jsonify({
            "error": "Rate limit exceeded",
            "retry_after": rl_info.get("retry_after", 60),
            "remaining": 0
        }), 429

    db = db_read()
    chat = db["chats"].get(chat_id)
    if not chat:
        return jsonify({"error": "Chat not found"}), 404
    if chat.get("user_id") != request.user_id and request.user.get("role") != "admin":
        return jsonify({"error": "Access denied"}), 403

    # ── Spending limit check ──
    _user_data = db["users"].get(request.user_id, {})
    _monthly_limit = _user_data.get("monthly_limit", 999999)
    _total_spent = _user_data.get("total_spent", 0.0)
    if _monthly_limit and _monthly_limit < 999999 and _total_spent >= _monthly_limit:
        _spent_rub = round(_total_spent * 105, 2)
        _limit_rub = round(_monthly_limit * 105, 2)
        return jsonify({
            "error": "spending_limit_exceeded",
            "message": f"Лимит исчерпан. Вы потратили ₽{_spent_rub} из ₽{_limit_rub} доступных. Обратитесь к администратору для пополнения баланса.",
            "spent": _total_spent,
            "limit": _monthly_limit,
            "spent_rub": _spent_rub,
            "limit_rub": _limit_rub
        }), 402

    data = request.get_json() or {}
    user_message = data.get("message", "").strip()
    file_content = data.get("file_content", "")
    # ── BUG-1 FIX: Extract and normalize orion_mode ──
    _raw_mode = data.get("mode", "turbo-basic")
    _MODE_NORMALIZE = {
        "turbo-basic": "turbo_standard", "turbo_basic": "turbo_standard", "turbo_standard": "turbo_standard",
        "turbo-premium": "turbo_premium", "turbo_premium": "turbo_premium",
        "pro-basic": "pro_standard", "pro_basic": "pro_standard", "pro_standard": "pro_standard",
        "pro-premium": "pro_premium", "pro_premium": "pro_premium",
        "architect": "architect",
    }
    orion_mode = _MODE_NORMALIZE.get(_raw_mode, "turbo_standard")
    logging.info(f"[send_message] orion_mode={orion_mode} (raw={_raw_mode})")

    if not user_message and not file_content:
        return jsonify({"error": "Message required"}), 400

    # Get user settings
    user_settings = db["users"].get(request.user_id, {}).get("settings", {})
    variant = user_settings.get("variant", "premium")
    enhanced = user_settings.get("enhanced_mode", False)
    self_check_level = user_settings.get("self_check_level", "none")  # none | light | medium | deep
    chat_model = user_settings.get("chat_model", "qwen3")

    # Multi-SSH: поддержка нескольких серверов
    # Фронтенд отправляет активный сервер в data.ssh или берём из settings
    _ssh_from_request = data.get("ssh", {})
    ssh_credentials = {
        "host": _ssh_from_request.get("ssh_host") or user_settings.get("ssh_host", ""),
        "username": _ssh_from_request.get("ssh_user") or user_settings.get("ssh_user", "root"),
        "password": _ssh_from_request.get("ssh_password") or user_settings.get("ssh_password", ""),
        "port": int(_ssh_from_request.get("ssh_port") or user_settings.get("ssh_port", 22)),
    }

    # ── Parse SSH credentials from message text ──
    # Formats: "root@IP password ...", "user@IP password ...", "IP password ..."
    ssh_from_msg = _parse_ssh_from_message(user_message)
    if ssh_from_msg:
        # Merge: message SSH overrides settings SSH
        if ssh_from_msg.get("host"):
            ssh_credentials["host"] = ssh_from_msg["host"]
        if ssh_from_msg.get("username"):
            ssh_credentials["username"] = ssh_from_msg["username"]
        if ssh_from_msg.get("password"):
            ssh_credentials["password"] = ssh_from_msg["password"]

    # Save user message
    now = datetime.now(timezone.utc).isoformat()
    user_msg = {
        "id": str(uuid.uuid4())[:8],
        "role": "user",
        "content": user_message,
        "timestamp": now,
        "file_content": file_content[:500] if file_content else None
    }
    chat["messages"].append(user_msg)
    chat["updated_at"] = now

    # Auto-title from first message — generate smart title via LLM (using orchestrator model)
    if len(chat["messages"]) == 1 and chat["title"] == "Новый чат":
        try:
            _title_config = MODEL_CONFIGS.get(variant, MODEL_CONFIGS["premium"])
            _title_model = _title_config["tools"]["model"]  # Используем модель оркестратора (DeepSeek V3.2)
            _title_resp = http_requests.post(
                OPENROUTER_BASE_URL,
                headers={"Authorization": f"Bearer {OPENROUTER_API_KEY}", "Content-Type": "application/json"},
                json={
                    "model": _title_model,
                    "max_tokens": 20,
                    "temperature": 0.3,
                    "messages": [
                        {"role": "system", "content": "Generate a short chat title (3-6 words, no quotes, no punctuation at end) that captures the essence of the user's request. Reply with ONLY the title, nothing else."},
                        {"role": "user", "content": user_message[:500]}
                    ]
                },
                timeout=5
            )
            _title_data = _title_resp.json()
            _generated_title = _title_data.get("choices", [{}])[0].get("message", {}).get("content", "").strip()
            # Clean up: remove quotes, trim
            _generated_title = _generated_title.strip('"\' ').rstrip('.')
            if _generated_title and 3 <= len(_generated_title) <= 80:
                chat["title"] = _generated_title
            else:
                raise ValueError("bad title")
        except Exception:
            # Fallback: first 50 chars
            chat["title"] = user_message[:50] + ("..." if len(user_message) > 50 else "")

    db["chats"][chat_id] = chat
    db_write(db)

    # Determine which model to use
    config = MODEL_CONFIGS.get(variant, MODEL_CONFIGS["premium"])
    model = config["coding"]["model"]
    model_name = config["coding"]["name"]
    # Separate model for Agent Mode (must support OpenAI tool calling)
    agent_model = config["tools"]["model"]
    agent_model_name = config["tools"]["name"]

    # ── ПАТЧ 5: Sonnet для серверных задач в Pro режимах ──
    _server_kw = ["сервер", "деплой", "ftp", "ssh", "загрузи", "настрой",
                  "админк", "nginx", "битрикс", "bitrix", "на сайт",
                  "создай страниц", "добавь в меню", "перенеси"]
    if variant == "premium" and any(w in user_message.lower() for w in _server_kw):
        agent_model = "anthropic/claude-sonnet-4.6"
        agent_model_name = "Claude Sonnet 4.6"
        logging.info(f"[PATCH5] Server task detected, upgrading to Sonnet")

    # Detect if this is an agent task (needs SSH/files/browser) or simple chat
    # ══ LLM ORCHESTRATOR: определяем намерение через AI, а не ключевые слова ══
    # Build chat history for context (needed for orchestrator too)
    # BUG-4 FIX: limit to last 10 messages for orchestrator to avoid context overflow
    history = []
    for m in chat.get("messages", [])[-10:]:
        history.append({"role": m["role"], "content": m["content"][:200]})

    # Определяем намерение
    # ══ PATCH 3: БЫСТРЫЙ ПУТЬ для простых сообщений ══
    _msg_lower_quick = user_message.lower().strip()
    _is_quick_msg = (
        len(user_message) < 50 and
        not any(w in _msg_lower_quick for w in [
            "сделай", "создай", "напиши", "настрой", "задеплой",
            "подключи", "перенеси", "протестируй", "проанализируй",
            "сгенерируй", "нарисуй", "спроектируй", "разверни",
            "установи", "обнови", "удали", "скачай", "загрузи",
            "картинк", "изображен", "иллюстрац", "баннер", "постер",
            "http://", "https://", "ssh", "docker", "nginx",
            "выполни", "дай", "покажи", "продолжи", "запусти", "открой",
            "найди", "проверь", "сервер", "код", "файл", "лендинг", "сайт",
            "парсер", "бот", "скрипт", "api", "база", "домен",
        ])
    )
    # Pro/Architect: bypass quick checks — model decides everything
    if orion_mode in ("pro_standard", "pro_premium", "architect"):
        _is_quick_msg = False
    
    if ssh_from_msg:
        intent = {"mode": "deploy", "reason": "SSH креденциалы в сообщении", "confidence": 1.0}
    elif _is_quick_msg:
        intent = {"mode": "chat", "reason": "Quick path - simple message", "confidence": 1.0}
        logging.info(f"[send_message] QUICK PATH: '{user_message[:40]}' → chat (skipping orchestrator)")
    else:
        intent = detect_intent_llm(user_message, history, OPENROUTER_API_KEY)

    mode = intent["mode"]  # chat | file | deploy | research | data
    # ══ IMAGE ROUTE FIX: Force image requests to file mode (→ lite_agent → _check_force_tool) ══
    _img_route_triggers = [
        "сделай картинк", "создай картинк", "нарисуй", "сгенерируй изображен",
        "сделай фото", "создай фото", "сделай изображен", "создай изображен",
        "сделай иллюстрац", "создай иллюстрац", "нарисуй мне",
        "сделай баннер", "создай баннер", "сделай постер", "создай постер",
        "сделай лого", "создай лого", "сделай иконк", "создай иконк",
        "make image", "create image", "generate image", "draw me",
    ]
    if any(t in user_message.lower().strip() for t in _img_route_triggers) and mode == "chat":
        mode = "file"  # Route to lite_agent where _check_force_tool handles image gen
        logging.info(f"[send_message] IMAGE ROUTE: Redirected '{user_message[:40]}' from chat → file (lite_agent)")

    # ══ MODEL ROUTER: автовыбор модели по сложности запроса ══
    has_ssh = bool(ssh_credentials.get("host") and ssh_credentials.get("password"))
    routed = select_model(user_message, variant=variant, history=history)
    routed_model_id = routed["model_id"]
    routed_model_name = routed["model_name"]
    routed_tier = routed["tier"]
    routed_complexity = routed["complexity"]
    logging.info(f"[ModelRouter] query='{user_message[:60]}' complexity={routed_complexity} tier={routed_tier} model={routed_model_id}")

    is_agent_task = (mode == "deploy")
    is_file_task = (mode == "file")
    is_browser_task = (mode == "research")
    has_url = bool(re.search(r'https?://\S+', user_message))
    if has_url and mode == "chat":
        is_browser_task = True
    # ── BUG-1 FIX v2: SSH доступен во ВСЕХ режимах (TURBO/PRO/AGENT/ELITE) ──
    # Если есть SSH credentials и запрос содержит SSH-ключевые слова → AgentLoop
    _ssh_kw = ["ssh", "сервер", "server", "uname", "apt ", "apt-get", "pip install",
               "npm install", "docker", "nginx", "systemd", "деплой", "deploy",
               "разверни", "установи на", "выполни", "запусти", "команд",
               "проверь пакет", "ls ", "cat ", "grep ", "cd ", "mkdir",
               "rm ", "cp ", "mv ", "chmod", "chown", "systemctl",
               "journalctl", "curl ", "wget ", "git ", "nano ", "vim "]
    if has_ssh and not is_agent_task and any(kw in user_message.lower() for kw in _ssh_kw):
        is_agent_task = True
        mode = "deploy"
        logging.info(f"[send_message] BUG-1 FIX v2: SSH keywords detected + has_ssh → forced agent mode")
    # URL + лендинг/сайт/создай → file mode → lite_agent (даже если is_browser_task)
    _landing_kw2 = ["лендинг", "landing", "сайт", "создай", "сделай", "сгенерируй", "напиши"]
    if has_url and any(kw in user_message.lower() for kw in _landing_kw2) and mode in ("chat", "research"):
        mode = "file"
        is_browser_task = False
        is_file_task = True

    # ══ CRITICAL FIX: ALL non-quick requests → AgentLoop with tools ══
    # Previously: is_lite_agent only for file/research/data modes
    # Now: ALL non-quick, non-SSH-deploy requests go through lite_agent
    # Agent decides whether to use tools (create_artifact, generate_image, etc.) or just respond
    # Flow:
    #   _is_quick_msg ("привет", short greetings) → plain chat (else branch, no tools)
    #   is_agent_task + has_ssh (deploy with SSH)   → full agent with SSH (elif branch)
    #   everything else                             → lite_agent with tools (if branch)
    if is_agent_task and has_ssh:
        is_lite_agent = False  # Goes to full SSH agent branch
    elif _is_quick_msg:
        is_lite_agent = False  # Goes to plain chat branch (fast, no tools)
    else:
        is_lite_agent = True   # ALL other requests → AgentLoop with TOOLS_SCHEMA
        logging.info(f"[send_message] CRITICAL FIX: mode={mode} → lite_agent=True (agent with tools)")

    # Build chat history for context
    # Context: 50 messages for Pro/Architect, 10 for Turbo
    _ctx_limit_app = 50 if orion_mode in ("pro_standard", "pro_premium", "architect") else 10
    history = [{"role": m["role"], "content": m["content"]} for m in chat["messages"][-_ctx_limit_app:]]

    def generate():
        nonlocal routed_model_name, model_name, agent_model_name
        full_response = ""
        tokens_in = 0  # CRИТ-2 FIX: инициализация до всех веток
        tokens_out = 0  # КРИТ-2 FIX: инициализация до всех веток

        # ══ TASK PERSISTENCE: register running task ══
        with _tasks_lock:
            _running_tasks[chat_id] = {
                "status": "running",
                "events": [],
                "started_at": time.time(),
                "user_id": request.user_id,
                "message": user_message[:100],
            }

        # Send metadata — show routed model info
        if (is_agent_task and has_ssh) or is_lite_agent:
            active_model_name = agent_model_name
        else:
            active_model_name = routed_model_name
        yield f"data: {json.dumps({'type': 'meta', 'variant': variant, 'model': active_model_name, 'enhanced': enhanced, 'self_check_level': self_check_level, 'agent_mode': (is_agent_task and has_ssh) or is_lite_agent, 'tier': routed_tier, 'complexity': routed_complexity})}\n\n"

        # ── Orchestrator v2: определить агентов по плану ──
        logging.info(f'[send_message] Orchestrator available: {_ORCHESTRATOR_AVAILABLE}, mode={mode}')
        _orch_plan_send = None
        if _ORCHESTRATOR_AVAILABLE and not _is_quick_msg:
            try:
                def _orch_llm_send(messages, model=None):
                    import requests as _rq
                    _llm_model = model or "openai/gpt-4.1-nano"
                    logging.info(f"[_orch_llm_send] Calling {_llm_model} with {len(messages)} messages")
                    resp = _rq.post(
                        OPENROUTER_BASE_URL,
                        headers={"Authorization": f"Bearer {OPENROUTER_API_KEY}",
                                 "Content-Type": "application/json"},
                        json={"model": _llm_model, 
                              "messages": messages, "max_tokens": 2000},
                        timeout=30
                    )
                    _resp_json = resp.json()
                    logging.info(f"[_orch_llm_send] Status: {resp.status_code}, keys: {list(_resp_json.keys())}")
                    if "error" in _resp_json:
                        logging.warning(f"[_orch_llm_send] API error: {_resp_json['error']}")
                    _content = _resp_json.get("choices",[{}])[0].get("message",{}).get("content","")
                    logging.info(f"[_orch_llm_send] Content length: {len(_content)}")
                    return _content
                
                _orch_send = Orchestrator(_orch_llm_send, mode)
                _orch_plan_send = _orch_send.plan(user_message, history, 
                                                   has_ssh=bool(ssh_credentials.get("host")))
                logging.info(f'[send_message] Orchestrator plan result: {_orch_plan_send}')
                
                # Отправить план клиенту
                if _orch_plan_send and _orch_plan_send.get("mode") != "chat":
                    logging.info(f"[send_message] Sending SSE task_plan event: {json.dumps(format_plan_sse(_orch_plan_send))[:200]}")
                    yield f"data: {json.dumps(format_plan_sse(_orch_plan_send))}\n\n"
                
                # Переопределить модель если нужно
                _pm = _orch_plan_send.get("primary_model", "")
                if _pm and _pm in MODEL_MAP:
                    agent_model = MODEL_MAP[_pm]
                    
            except Exception as _oe:
                logging.warning(f"Orchestrator in send_message: {_oe}"); import traceback; logging.warning(f"Orchestrator traceback: {traceback.format_exc()}")
        

        if is_lite_agent:
            # ═══ AGENT MODE (with tools): ALL non-quick, non-SSH requests ═══
            if is_browser_task:
                _lite_mode_text = 'Открываю браузер...'
            elif mode in ('file', 'data'):
                _lite_mode_text = 'Генерирую файл...'
            else:
                _lite_mode_text = 'Анализирую запрос...'
            yield f"data: {json.dumps({'type': 'agent_mode', 'text': _lite_mode_text})}\n\n"

            agent = AgentLoop(
                model=agent_model,
                api_key=OPENROUTER_API_KEY,
                api_url=OPENROUTER_BASE_URL,
                ssh_credentials={},  # No SSH needed for file generation
                user_id=request.user_id  # BUG-5 FIX
            )
            agent._chat_id = chat_id  # BUG-5 FIX
            agent._verify_enabled = data.get("verify", False)  # ПАТЧ 7
            # BUG-8 FIX: Pass orchestrator plan to agent
            if _orch_plan_send:
                agent._orchestrator_plan = _orch_plan_send

            with _agents_lock:
                _active_agents[chat_id] = agent

            try:
                for event in agent.run_stream(user_message, history, file_content):
                    yield event
                    try:
                        event_data = json.loads(event.replace("data: ", "").strip())
                        if event_data.get("type") == "content":
                            full_response += event_data.get("text", "")
                    except Exception as _sse_err:
                        logging.warning(f"SSE parse error: {_sse_err}")

                tokens_in = agent.total_tokens_in
                tokens_out = agent.total_tokens_out

            finally:
                with _agents_lock:
                    _active_agents.pop(chat_id, None)

        elif is_agent_task and has_ssh:
            # ═══ AGENT MODE: Real execution with SSH/Browser/Files ═══

            # ── Project Memory: load context from previous sessions ──
            try:
                pm = ProjectMemory(user_id=request.user_id, project_id=chat_id)
                pm.start_session(chat_id, task=user_message[:200])
                memory_context = pm.get_full_context(chat_id)
                if memory_context:
                    yield f"data: {json.dumps({'type': 'memory_loaded', 'text': 'Контекст предыдущих сессий загружен', 'context_length': len(memory_context)})}\n\n"
            except Exception:
                pm = None
                memory_context = ""

            # ── Select agent execution mode ──
            selected_agents = select_agents_for_task(user_message, mode)
            use_parallel = len(selected_agents) >= 2 and enhanced
            agent_names = [a.get('name', '?') for a in selected_agents]

            yield f"data: {json.dumps({'type': 'agent_mode', 'text': 'Запускаю автономный агент...', 'agents': agent_names, 'parallel': use_parallel})}\n\n"

            if use_parallel:
                # ── Parallel multi-agent execution ──
                orchestrator = ParallelAgentOrchestrator(
                    model=agent_model,
                    api_key=OPENROUTER_API_KEY,
                    api_url=OPENROUTER_BASE_URL,
                    ssh_credentials=ssh_credentials,
                    max_workers=min(3, len(selected_agents))
                )
                agent = orchestrator  # For stop functionality

            elif enhanced:
                # Multi-agent pipeline (sequential, 6 specialized agents)
                agent = MultiAgentLoop(
                    model=agent_model,
                    api_key=OPENROUTER_API_KEY,
                    api_url=OPENROUTER_BASE_URL,
                    ssh_credentials=ssh_credentials
                )
            elif _orch_plan_send and _orch_plan_send.get("mode") == "multi_sequential":
                # BUG-8 FIX: Orchestrator requested multi_sequential → use MultiAgentLoop
                agent = MultiAgentLoop(
                    model=agent_model,
                    api_key=OPENROUTER_API_KEY,
                    api_url=OPENROUTER_BASE_URL,
                    ssh_credentials=ssh_credentials
                )
                logging.info(f"[send_message] BUG-8 FIX: Using MultiAgentLoop for multi_sequential plan")
            else:
                # Single agent loop
                # === МАРШРУТИЗАЦИЯ МОДЕЛИ (ПАТЧ A3) ===
                _sm_model_override = None
                _sm_extra_prompt = None
                try:
                    from intent_clarifier import clarify as _sm_clarify
                    _sm_intent = _sm_clarify(user_message)
                    _sm_primary = _sm_intent.get("primary_model", "")
                    if _sm_primary == "gemini":
                        _sm_model_override = "google/gemini-2.5-pro"
                        _sm_extra_prompt = "РЕЖИМ ДИЗАЙНЕРА: Создавай красивые веб-страницы с Google Fonts, градиентами, анимациями. Сохраняй HTML в файл через file_write."
                    elif _sm_primary == "sonnet":
                        _sm_model_override = "anthropic/claude-sonnet-4.6"
                except Exception as _route_err:
                    logging.warning(f"Model routing error: {_route_err}")
                # === КОНЕЦ МАРШРУТИЗАЦИИ ===
                # ── BUG-1 FIX: Premium mode → Sonnet for agent too ──
                if orion_mode in ("turbo_premium", "pro_premium") and not _sm_model_override:
                    _sm_model_override = "anthropic/claude-sonnet-4.6"
                    model_name = "Claude Sonnet 4.6"
                    agent_model_name = "Claude Sonnet 4.6"
                    routed_model_name = "Claude Sonnet 4.6"
                    logging.info(f"[send_message] BUG-1 FIX: Agent premium mode {orion_mode} → Sonnet")
                agent = AgentLoop(
                    model=agent_model,
                    api_key=OPENROUTER_API_KEY,
                    api_url=OPENROUTER_BASE_URL,
                    ssh_credentials=ssh_credentials,
                    user_id=request.user_id,  # BUG-5 FIX
                    model_override=_sm_model_override,
                    system_prompt_override=_sm_extra_prompt
                )
                agent._chat_id = chat_id  # BUG-5 FIX: передаём chat_id

            # BUG-8 FIX 2: Pass orchestrator plan to SSH agent
            if _orch_plan_send:
                agent._orchestrator_plan = _orch_plan_send
                logging.info(f"[send_message] BUG-8: Passed orch plan to SSH agent")
            # Register agent for stop functionality
            with _agents_lock:
                _active_agents[chat_id] = agent

            try:
                # ══ PATCH 4: Multi-agent SSE error handling ══
                if use_parallel:
                    agent_keys = [a.get('key', a.get('role', '')) for a in selected_agents]
                    event_gen = orchestrator.run_parallel(
                        user_message, history, file_content,
                        agent_keys=agent_keys, mode=mode
                    )
                elif enhanced:
                    try:
                        event_gen = agent.run_multi_agent_stream(user_message, history, file_content)
                    except Exception as _multi_init_err:
                        logging.error(f"Multi-agent init error: {_multi_init_err}, falling back to single agent")
                        event_gen = agent.run_stream(user_message, history, file_content)
                else:
                    event_gen = agent.run_stream(user_message, history, file_content)

                for event in event_gen:
                    try:
                        yield event
                    except GeneratorExit:
                        break
                    # Capture text content
                    try:
                        event_data = json.loads(event.replace("data: ", "").strip())
                        if event_data.get("type") == "content":
                            full_response += event_data.get("text", "")
                    except Exception as _sse_err:
                        logging.warning(f"SSE parse error: {_sse_err}")

                 # Get token counts from agent
                if hasattr(agent, 'total_tokens_in'):
                    tokens_in = agent.total_tokens_in
                    tokens_out = agent.total_tokens_out

                # ── Project Memory: save session summary ──
                try:
                    if pm and full_response:
                        summary = full_response[:300] if len(full_response) > 300 else full_response
                        pm.complete_session(chat_id, summary=summary)
                except Exception as _pm_err:
                    logging.warning(f"ProjectManager session error: {_pm_err}")

            finally:
                with _agents_lock:
                    _active_agents.pop(chat_id, None)

        else:
            # ═══ CHAT MODE: Smart model routing by complexity ═══
            code_keywords = ["код", "code", "функци", "class", "function", "html", "css", "js", "python", "api"]
            is_code = any(kw in user_message.lower() for kw in code_keywords)

            if is_code:
                # For code tasks: use routed model (complexity-based) or coding model from variant
                if routed_complexity >= 4:
                    active_model = config["coding"]["model"]  # Complex code → coding model (MiniMax/Grok)
                else:
                    active_model = routed_model_id  # Simple code → routed (cheaper) model
                system_prompt = """Ты — Senior Full-Stack Developer. Ты пишешь production-ready код.
Правила:
- Чистый, читаемый код с комментариями
- Современные паттерны и best practices
- Полная обработка ошибок
- Если задача про лендинг/сайт — создавай красивый дизайн с градиентами, анимациями
Всегда возвращай полный код файлов. Каждый файл оборачивай в ```language filename.ext

Если пользователь хочет чтобы ты ВЫПОЛНИЛ задачу на сервере (создал файлы, запустил команды) — 
скажи ему настроить SSH подключение в настройках (иконка ⚙️), указав хост, логин и пароль сервера.
После этого ты сможешь автоматически выполнять команды на сервере."""
            else:
                # For non-code: use routed model for simple, user's chat model for complex
                if routed_complexity <= 2:
                    active_model = routed_model_id  # Simple → fast/cheap model
                else:
                    active_model = CHAT_MODELS.get(chat_model, CHAT_MODELS["qwen3"])["model"]
                system_prompt = """Ты — полезный AI-ассистент ORION Digital v1.0. Отвечай на русском языке.
Ты умеешь:
- Писать код и создавать приложения
- Подключаться к серверам по SSH и выполнять команды
- Создавать и редактировать файлы на серверах
- Проверять сайты через браузер
- Деплоить приложения автоматически

Если пользователь хочет чтобы ты выполнил задачу на сервере — попроси его настроить SSH в настройках (⚙️).
Отвечай кратко и по делу."""

            # ── BUG-1 FIX: Premium mode → Sonnet override ──
            if orion_mode in ("turbo_premium", "pro_premium"):
                active_model = "anthropic/claude-sonnet-4.6"
                active_model_name = "Claude Sonnet 4.6"
                model_name = "Claude Sonnet 4.6"
                routed_model_name = "Claude Sonnet 4.6"
                logging.info(f"[send_message] BUG-1 FIX: Premium mode {orion_mode} → Sonnet override")
                yield f"data: {json.dumps({'type': 'meta', 'variant': variant, 'model': 'Claude Sonnet 4.6', 'enhanced': enhanced, 'self_check_level': self_check_level, 'agent_mode': False, 'tier': 'sonnet', 'complexity': routed_complexity})}\n\n"
            # ── BUG-5 FIX v4: читаем долгосрочную память и добавляем в system_prompt ──
            try:
                _mem_log = logging.getLogger("memory.engine")

                # Функция вызова LLM для extract_from_chat (нужна memory_v9)
                def _mem_call_llm(msgs):
                    try:
                        _r = http_requests.post(
                            OPENROUTER_BASE_URL,
                            headers={"Authorization": f"Bearer {OPENROUTER_API_KEY}", "Content-Type": "application/json"},
                            json={"model": "openai/gpt-4.1-nano", "messages": msgs, "temperature": 0.1, "max_tokens": 512},
                            timeout=15
                        )
                        return _r.json()["choices"][0]["message"]["content"]
                    except Exception as _e:
                        _mem_log.warning(f"[MEMORY] _mem_call_llm error: {_e}")
                        return ""

                from memory_v9 import SuperMemoryEngine
                # SuperMemoryEngine.__init__ принимает call_llm_func — передаём его
                _mem_v9 = SuperMemoryEngine(call_llm_func=_mem_call_llm)
                _mem_v9.init_task(
                    user_message=user_message,
                    user_id=request.user_id,
                    chat_id=chat_id,
                    api_key=OPENROUTER_API_KEY,
                    api_url=OPENROUTER_BASE_URL
                )
                # build_messages принимает chat_history (не history)
                _mem_context = _mem_v9.build_messages(
                    system_prompt=system_prompt,
                    chat_history=[],
                    user_message=user_message
                )
                # build_messages возвращает список — берём system из первого элемента
                if _mem_context and _mem_context[0].get("role") == "system":
                    _enriched_prompt = _mem_context[0]["content"]
                    if _enriched_prompt != system_prompt:
                        system_prompt = _enriched_prompt
                        _mem_log.info(f"[MEMORY] CHAT MODE READ OK: +{len(_enriched_prompt)-len(system_prompt)} chars injected, user={request.user_id!r}")
                    else:
                        _mem_log.info(f"[MEMORY] CHAT MODE READ: no facts yet for user={request.user_id!r}")
            except Exception as _mem_chat_err:
                logging.getLogger("memory.engine").warning(f"[MEMORY] CHAT MODE memory read failed: {_mem_chat_err}", exc_info=True)

            messages = [{"role": "system", "content": system_prompt}]
            for msg in history:
                messages.append({"role": msg["role"], "content": msg["content"]})

            if file_content:
                # Truncate file content to avoid exceeding API limits
                fc = file_content
                if len(fc) > 30000:
                    fc = fc[:30000] + f"\n... [обрезано, всего {len(file_content)} символов]"
                messages[-1]["content"] = f"{fc}\n\n---\n\nЗадача:\n{user_message}"

            # Stream response
            headers = {
                "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                "Content-Type": "application/json",
                "HTTP-Referer": "https://orion.mksitdev.ru",
                "X-Title": "ORION Digital v4.0"
            }

            payload = {
                "model": active_model,
                "messages": messages,
                "temperature": 0.3,
                "max_tokens": 16000,
                "stream": True
            }

            tokens_in = 0
            tokens_out = 0

            try:
                resp = http_requests.post(
                    OPENROUTER_BASE_URL,
                    headers=headers,
                    json=payload,
                    stream=True,
                    timeout=120
                )
                resp.raise_for_status()

                for line in resp.iter_lines():
                    if not line:
                        continue
                    line_str = line.decode("utf-8", errors="replace")
                    if not line_str.startswith("data: "):
                        continue
                    payload_str = line_str[6:]
                    if payload_str.strip() == "[DONE]":
                        break
                    try:
                        chunk = json.loads(payload_str)
                        choices = chunk.get("choices", [])
                        if choices:
                            delta = choices[0].get("delta", {})
                            text = delta.get("content", "")
                            if text:
                                full_response += text
                                yield f"data: {json.dumps({'type': 'content', 'text': text})}\n\n"

                        usage = chunk.get("usage")
                        if usage:
                            tokens_in += usage.get("prompt_tokens", 0)
                            tokens_out += usage.get("completion_tokens", 0)
                    except json.JSONDecodeError:
                        continue

            except Exception as e:
                error_msg = f"❌ Ошибка API: {str(e)}"
                yield f"data: {json.dumps({'type': 'error', 'text': error_msg})}\n\n"
                full_response = error_msg

            # ═══ SELF-CHECK: проверка ответа вторым AI ═══
            if self_check_level != "none" and full_response and "❌" not in full_response[:10]:
                SELF_CHECK_MODELS = {
                    "light":  {"model": "openai/gpt-4.1-nano", "name": "GPT-4.1 Nano", "input_price": 0.10, "output_price": 0.40},
                    "medium": None,  # same model as main
                    "deep":   {"model": "anthropic/claude-sonnet-4.6", "name": "Claude Sonnet 4", "input_price": 3.00, "output_price": 15.00},
                }
                check_config = SELF_CHECK_MODELS.get(self_check_level)
                if self_check_level == "medium":
                    check_model_id = active_model
                    check_model_name = "Same Model"
                    check_input_price = routed.get("input_price", 0.10)
                    check_output_price = routed.get("output_price", 0.40)
                elif check_config:
                    check_model_id = check_config["model"]
                    check_model_name = check_config["name"]
                    check_input_price = check_config["input_price"]
                    check_output_price = check_config["output_price"]
                else:
                    check_model_id = None

                if check_model_id:
                    yield f"data: {json.dumps({'type': 'self_check', 'status': 'started', 'level': self_check_level, 'checker': check_model_name})}\n\n"

                    check_prompt = f"""Ты — критик и верификатор AI-ответов. Проверь следующий ответ на:
1. Фактические ошибки и галлюцинации
2. Логические противоречия
3. Неполноту ответа
4. Ошибки в коде (если есть код)

Вопрос пользователя: {user_message}

Ответ AI:
{full_response[:8000]}

Если ответ хороший — верни его как есть.
Если нашёл ошибки — верни ИСПРАВЛЕННУЮ версию полного ответа.
Не добавляй комментарии о проверке, верни только финальный ответ."""

                    check_messages = [{"role": "user", "content": check_prompt}]
                    check_payload = {
                        "model": check_model_id,
                        "messages": check_messages,
                        "temperature": 0.1,
                        "max_tokens": 16000,
                        "stream": True
                    }

                    try:
                        check_resp = http_requests.post(
                            OPENROUTER_BASE_URL,
                            headers=headers,
                            json=check_payload,
                            stream=True,
                            timeout=120
                        )
                        check_resp.raise_for_status()

                        checked_response = ""
                        # Signal frontend to clear previous response and show checked version
                        yield f"data: {json.dumps({'type': 'self_check_replace', 'status': 'streaming'})}\n\n"

                        for line in check_resp.iter_lines():
                            if not line:
                                continue
                            line_str = line.decode("utf-8", errors="replace")
                            if not line_str.startswith("data: "):
                                continue
                            payload_str = line_str[6:]
                            if payload_str.strip() == "[DONE]":
                                break
                            try:
                                chunk = json.loads(payload_str)
                                choices = chunk.get("choices", [])
                                if choices:
                                    delta = choices[0].get("delta", {})
                                    text = delta.get("content", "")
                                    if text:
                                        checked_response += text
                                        yield f"data: {json.dumps({'type': 'self_check_content', 'text': text})}\n\n"
                                usage = chunk.get("usage")
                                if usage:
                                    tokens_in += usage.get("prompt_tokens", 0)
                                    tokens_out += usage.get("completion_tokens", 0)
                            except json.JSONDecodeError:
                                continue

                        if checked_response.strip():
                            full_response = checked_response
                            yield f"data: {json.dumps({'type': 'self_check', 'status': 'done', 'level': self_check_level})}\n\n"
                        else:
                            yield f"data: {json.dumps({'type': 'self_check', 'status': 'kept_original', 'level': self_check_level})}\n\n"

                    except Exception as e:
                        logging.warning(f"Self-check failed: {e}")
                        yield f"data: {json.dumps({'type': 'self_check', 'status': 'error', 'error': str(e)[:100]})}\n\n"

        # Calculate cost using routed model prices
        _active_input_price = routed.get("input_price", config["coding"]["input_price"])
        _active_output_price = routed.get("output_price", config["coding"]["output_price"])
        cost_in = (tokens_in / 1_000_000) * _active_input_price
        cost_out = (tokens_out / 1_000_000) * _active_output_price
        total_cost = round(cost_in + cost_out, 6)
        # КРИТ-2 FIX: используем реальную стоимость из расчёта токенов

        # Log cost via model_router for analytics
        try:
            log_cost(
                user_id=request.user_id,
                model_id=routed_model_id,
                tokens_in=tokens_in,
                tokens_out=tokens_out,
                cost_usd=total_cost,
                tier=routed_tier,
                complexity=routed_complexity,
                tool_name=mode,
                success="\u274c" not in full_response[:100]
            )
        except Exception as _nc_err:
            logging.warning(f"Non-critical error: {_nc_err}")

        # Save assistant message
        db2 = db_read()
        chat2 = db2["chats"].get(chat_id, chat)
        assistant_msg = {
            "id": str(uuid.uuid4())[:8],
            "role": "assistant",
            "content": full_response,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "model": model_name,
            "variant": variant,
            "tokens_in": tokens_in,
            "tokens_out": tokens_out,
            "cost": total_cost,
            "enhanced": enhanced,
            "agent_mode": (is_agent_task and has_ssh) or is_lite_agent
        }
        chat2["messages"].append(assistant_msg)
        chat2["total_cost"] = round(chat2.get("total_cost", 0) + total_cost, 4)
        chat2["total_tokens_in"] = chat2.get("total_tokens_in", 0) + tokens_in
        chat2["total_tokens_out"] = chat2.get("total_tokens_out", 0) + tokens_out
        chat2["model_used"] = model_name
        chat2["model"] = model_name  # BUG-ANA-03 FIX: also write to 'model' field (SQLite column)
        chat2["variant"] = variant
        db2["chats"][chat_id] = chat2

        # Update user spending
        user2 = db2["users"].get(request.user_id, {})
        user2["total_spent"] = round(user2.get("total_spent", 0) + total_cost, 4)
        db2["users"][request.user_id] = user2

        # Update global analytics
        analytics = db2.get("analytics", {})
        analytics["total_requests"] = analytics.get("total_requests", 0) + 1
        analytics["total_tokens_in"] = analytics.get("total_tokens_in", 0) + tokens_in
        analytics["total_tokens_out"] = analytics.get("total_tokens_out", 0) + tokens_out
        analytics["total_cost"] = round(analytics.get("total_cost", 0) + total_cost, 4)

        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        daily = analytics.get("daily_stats", {})
        if today not in daily:
            daily[today] = {"requests": 0, "cost": 0.0, "tokens_in": 0, "tokens_out": 0}
        daily[today]["requests"] += 1
        daily[today]["cost"] = round(daily[today]["cost"] + total_cost, 4)
        daily[today]["tokens_in"] += tokens_in
        daily[today]["tokens_out"] += tokens_out
        analytics["daily_stats"] = daily
        db2["analytics"] = analytics

        # Save memory (episodic) — legacy JSON memory
        memory = db2.get("memory", {"episodic": [], "semantic": {}, "procedural": {}})
        memory["episodic"].append({
            "task": user_message[:200],
            "result_preview": full_response[:200],
            "cost": total_cost,
            "variant": variant,
            "enhanced": enhanced,
            "agent_mode": (is_agent_task and has_ssh) or is_lite_agent,
            "timestamp": now,
            "user_id": request.user_id,
            "success": "❌" not in full_response[:100]
        })
        if len(memory["episodic"]) > 1000:
            memory["episodic"] = memory["episodic"][-1000:]
        db2["memory"] = memory

        # Save to vector memory (long-term, cross-chat)
        try:
            vmem = _get_memory()
            vmem.store_from_conversation(
                user_message=user_message,
                assistant_response=full_response[:500],
                chat_id=chat_id,
                user_id=request.user_id
            )
        except Exception as _nc_err:
            logging.warning(f"Non-critical error: {_nc_err}")

        # ── BUG-5 FIX v3: memory_v9 after_chat — сохраняем факты для ВСЕХ режимов ──
        try:
            _mem_logger = logging.getLogger("memory.engine")

            # Сохраняем через agent.memory если агент был создан
            _agent_memory_saved = False
            _agent_ref = locals().get("agent", None)
            if _agent_ref is not None and hasattr(_agent_ref, "memory") and _agent_ref.memory is not None:
                _agent_ref.memory.after_chat(
                    user_message=user_message,
                    full_response=full_response,
                    chat_id=chat_id,
                    success="❌" not in full_response[:100]
                )
                _agent_memory_saved = True
                _mem_logger.info(f"[MEMORY] after_chat via agent.memory: OK, user={request.user_id!r}")

            # Для CHAT MODE (без агента) — сохраняем напрямую через memory_v9
            if not _agent_memory_saved and full_response:
                try:
                    def _mem_call_llm_save(msgs):
                        try:
                            _r = http_requests.post(
                                OPENROUTER_BASE_URL,
                                headers={"Authorization": f"Bearer {OPENROUTER_API_KEY}", "Content-Type": "application/json"},
                                json={"model": "openai/gpt-4.1-nano", "messages": msgs, "temperature": 0.1, "max_tokens": 512},
                                timeout=15
                            )
                            return _r.json()["choices"][0]["message"]["content"]
                        except Exception as _e:
                            return ""

                    from memory_v9 import SuperMemoryEngine
                    # Передаём call_llm_func — без него extract_from_chat не работает!
                    _mem_v9_save = SuperMemoryEngine(call_llm_func=_mem_call_llm_save)
                    _mem_v9_save.init_task(
                        user_message=user_message,
                        user_id=request.user_id,
                        chat_id=chat_id,
                        api_key=OPENROUTER_API_KEY,
                        api_url=OPENROUTER_BASE_URL
                    )
                    _mem_v9_save.after_chat(
                        user_message=user_message,
                        full_response=full_response,
                        chat_id=chat_id,
                        success="❌" not in full_response[:100]
                    )
                    _mem_logger.info(f"[MEMORY] after_chat SAVE OK: user={request.user_id!r}, msg={user_message[:60]!r}")
                except Exception as _direct_err:
                    _mem_logger.warning(f"[MEMORY] direct memory_v9 after_chat failed: {_direct_err}", exc_info=True)
        except Exception as _ac_err:
            logging.getLogger("memory.engine").error(f"[MEMORY] after_chat EXCEPTION: {_ac_err}", exc_info=True)

        db_write(db2)

        # Send completion event with routing info
        # КРИТ-2 FIX: отдельное событие 'cost' для frontend
        yield f"data: {json.dumps({'type': 'cost', 'cost': total_cost, 'tokens_in': tokens_in, 'tokens_out': tokens_out})}\n\n"
        yield f"data: {json.dumps({'type': 'done', 'tokens_in': tokens_in, 'tokens_out': tokens_out, 'cost': total_cost, 'model': routed_model_name, 'tier': routed_tier, 'complexity': routed_complexity})}\n\n"

        # ══ TASK PERSISTENCE: mark task as done ══
        with _tasks_lock:
            task = _running_tasks.get(chat_id)
            if task:
                task["status"] = "done"
                task["finished_at"] = time.time()

    def _buffered_generate():
        """Wrapper that buffers all SSE events for reconnect support."""
        for event in generate():
            # Buffer event for reconnect
            with _tasks_lock:
                task = _running_tasks.get(chat_id)
                if task:
                    task["events"].append(event)
            yield event

    return Response(
        stream_with_context(_buffered_generate()),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"
        }
    )


# ── Stop Agent ─────────────────────────────────────────────────
@app.route("/api/chats/<chat_id>/stop", methods=["POST"])
@require_auth
def stop_agent(chat_id):
    """Stop a running agent loop."""
    with _agents_lock:
        agent = _active_agents.get(chat_id)
        if agent:
            agent.stop()
            return jsonify({"ok": True, "message": "Agent stop requested"})
    return jsonify({"ok": False, "message": "No active agent for this chat"})


# ══ TASK STATUS: check if a task is running for this chat ══
@app.route("/api/chats/<chat_id>/status", methods=["GET"])
@require_auth
def get_chat_task_status(chat_id):
    """Return the current task status for a chat (running/done/none)."""
    with _tasks_lock:
        task = _running_tasks.get(chat_id)
        if not task:
            return jsonify({"status": "none", "events_count": 0})
        return jsonify({
            "status": task["status"],
            "events_count": len(task["events"]),
            "started_at": task.get("started_at", 0),
            "message": task.get("message", ""),
        })


# ══ TASK RECONNECT: replay buffered SSE events + continue streaming ══
@app.route("/api/chats/<chat_id>/reconnect", methods=["GET"])
@require_auth
def reconnect_task_stream(chat_id):
    """Reconnect to a running task: replay buffered events, then wait for new ones."""
    with _tasks_lock:
        task = _running_tasks.get(chat_id)
        if not task:
            return jsonify({"error": "No running task for this chat"}), 404

    def replay_and_follow():
        # Phase 1: replay all buffered events
        sent = 0
        with _tasks_lock:
            task = _running_tasks.get(chat_id)
            if task:
                for event in task["events"]:
                    yield event
                    sent += 1
        
        # Phase 2: if task is still running, poll for new events
        if task and task["status"] == "running":
            import time as _time
            max_wait = 300  # 5 min max
            start = _time.time()
            while _time.time() - start < max_wait:
                _time.sleep(0.3)
                with _tasks_lock:
                    task = _running_tasks.get(chat_id)
                    if not task:
                        break
                    current_len = len(task["events"])
                    if current_len > sent:
                        for event in task["events"][sent:current_len]:
                            yield event
                        sent = current_len
                    if task["status"] == "done":
                        # Send any remaining events
                        for event in task["events"][sent:]:
                            yield event
                        break

    return Response(
        stream_with_context(replay_and_follow()),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"
        }
    )


# ── /api/chat — прямой роут (фронтенд v2.0 шлёт сюда) ────────
@app.route("/api/chat", methods=["POST"])
@app.route("/api/chat/multi-agent", methods=["POST"])
@require_auth
def direct_chat():
    """Direct chat endpoint: auto-creates chat if needed, then streams response."""
    import uuid as _uuid
    data = request.get_json() or {}
    user_message = data.get("message", "").strip()
    file_content = data.get("file_content", "")
    # ── BUG-1 FIX: Extract and normalize orion_mode ──
    _raw_mode = data.get("mode", "turbo-basic")
    _MODE_NORMALIZE = {
        "turbo-basic": "turbo_standard", "turbo_basic": "turbo_standard", "turbo_standard": "turbo_standard",
        "turbo-premium": "turbo_premium", "turbo_premium": "turbo_premium",
        "pro-basic": "pro_standard", "pro_basic": "pro_standard", "pro_standard": "pro_standard",
        "pro-premium": "pro_premium", "pro_premium": "pro_premium",
        "architect": "architect",
    }
    orion_mode = _MODE_NORMALIZE.get(_raw_mode, "turbo_standard")
    logging.info(f"[send_message] orion_mode={orion_mode} (raw={_raw_mode})")
    chat_id = data.get("chat_id")

    if not user_message and not file_content:
        return jsonify({"error": "Message required"}), 400

    db = db_read()

    # Создаём чат если не передан или не существует
    if not chat_id or chat_id not in db["chats"]:
        chat_id = str(_uuid.uuid4())
        title = user_message[:50] if user_message else "Новый чат"
        db["chats"][chat_id] = {
            "id": chat_id,
            "user_id": request.user_id,
            "title": title,
            "messages": [],
            "created_at": time.time(),
            "updated_at": time.time(),
            "total_cost": 0.0,
            "mode": orion_mode,
        }
        db_write(db)

    # Проверяем доступ
    chat = db["chats"].get(chat_id)
    if chat.get("user_id") != request.user_id and request.user.get("role") != "admin":
        return jsonify({"error": "Access denied"}), 403

    # Rate limiting
    rl = _get_rate_limiter()
    allowed, rl_info = rl.check_message(request.user_id)
    if not allowed:
        return jsonify({"error": "Rate limit exceeded", "retry_after": rl_info.get("retry_after", 60)}), 429

    # Spending limit
    _user_data = db["users"].get(request.user_id, {})
    _monthly_limit = _user_data.get("monthly_limit", 999999)
    _total_spent = _user_data.get("total_spent", 0.0)
    if _monthly_limit and _monthly_limit < 999999 and _total_spent >= _monthly_limit:
        return jsonify({"error": "spending_limit_exceeded", "message": "Лимит исчерпан."}), 402

    # Сохраняем сообщение пользователя
    msg_id = str(_uuid.uuid4())
    user_msg = {
        "id": msg_id, "role": "user",
        "content": user_message + (f"\n\n[Файл]:\n{file_content}" if file_content else ""),
        "timestamp": time.time()
    }
    with _lock:
        db2 = _load_db()
        db2["chats"][chat_id]["messages"].append(user_msg)
        db2["chats"][chat_id]["updated_at"] = time.time()
        _save_db(db2)

    # Получаем историю (BUG-4 FIX: ограничиваем до 10 сообщений чтобы не переполнять контекст)
    _ctx_limit_v2 = 50 if orion_mode in ("pro_standard", "pro_premium", "architect") else 10
    history = db2["chats"][chat_id]["messages"][-_ctx_limit_v2:]
    user_settings = request.user.get("settings", {})

    # ── SSH credentials: from request, settings, and message text ──
    _ssh_from_request = data.get("ssh", {})
    ssh_credentials = {
        "host": _ssh_from_request.get("ssh_host") or user_settings.get("ssh_host", ""),
        "username": _ssh_from_request.get("ssh_user") or user_settings.get("ssh_user", "root"),
        "password": _ssh_from_request.get("ssh_password") or user_settings.get("ssh_password", ""),
        "port": int(_ssh_from_request.get("ssh_port") or user_settings.get("ssh_port", 22)),
    }
    # Parse SSH from message text (e.g. "root@1.2.3.4 password123 do something")
    ssh_from_msg = _parse_ssh_from_message(user_message)
    if ssh_from_msg:
        if ssh_from_msg.get("host"):
            ssh_credentials["host"] = ssh_from_msg["host"]
        if ssh_from_msg.get("username"):
            ssh_credentials["username"] = ssh_from_msg["username"]
        if ssh_from_msg.get("password"):
            ssh_credentials["password"] = ssh_from_msg["password"]

    # Выбираем модель по режиму
    from model_router import get_model_for_agent
    _agent_cfg = get_model_for_agent("orchestrator", orion_mode)
    model = _agent_cfg.get("model_id", "openai/gpt-4.1-mini")
    api_key = OPENROUTER_API_KEY

    def generate():
        from agent_loop import AgentLoop, MultiAgentLoop
        import json as _json

        assistant_content = ""
        assistant_msg_id = str(_uuid.uuid4())
        SSE = "\n\n"

        # Отправляем chat_id клиенту сразу
        yield "data: " + _json.dumps({"type": "chat_id", "chat_id": chat_id}) + SSE

        try:
            # ── ORION Orchestrator v2: умная маршрутизация ──
            _orch_model_override = None
            _orch_prompt_extra = ""
            _orch_plan = None
            
            if _ORCHESTRATOR_AVAILABLE:
                try:
                    # Функция для вызова LLM из оркестратора
                    def _orch_call_llm(messages, model=None):
                        import requests as _req
                        _model = model or "openai/gpt-4.1-nano"
                        resp = _req.post(
                            OPENROUTER_BASE_URL,
                            headers={"Authorization": f"Bearer {OPENROUTER_API_KEY}",
                                     "Content-Type": "application/json"},
                            json={"model": _model, "messages": messages, "max_tokens": 2000},
                            timeout=30
                        )
                        data = resp.json()
                        return data.get("choices", [{}])[0].get("message", {}).get("content", "")
                    
                    # Определить SSH (from settings, request, or parsed from message)
                    _has_ssh = bool(ssh_credentials.get("host") and ssh_credentials.get("password"))
                    _ssh_info = f"host={ssh_credentials.get('host','')}" if _has_ssh else ""
                    
                    # Создать оркестратор и получить план
                    _orch = Orchestrator(_orch_call_llm, orion_mode)
                    _orch_plan = _orch.plan(
                        user_message, 
                        chat_history=history,
                        has_ssh=_has_ssh,
                        ssh_info=_ssh_info
                    )
                    
                    # Отправить план клиенту
                    if _orch_plan and _orch_plan.get("mode") != "chat":
                        yield "data: " + _json.dumps(format_plan_sse(_orch_plan)) + SSE
                    
                    # Если оркестратор хочет спросить пользователя
                    if _orch_plan and _orch_plan.get("ask_user"):
                        yield "data: " + _json.dumps({
                            "type": "ask_user",
                            "question": _orch_plan["ask_user"]
                        }) + SSE
                    
                    # Определить модель и промпт из плана
                    if _orch_plan:
                        _pm = _orch_plan.get("primary_model", "")
                        _pa = _orch_plan.get("primary_agent", "")
                        
                        if _pm and _pm in MODEL_MAP:
                            _orch_model_override = MODEL_MAP[_pm]
                        
                        if _pa and _pa in AGENT_PROMPTS:
                            _orch_prompt_extra = AGENT_PROMPTS[_pa]
                        
                        if _orch_plan.get("mode") in ("multi_sequential", "multi_parallel"):
                            multi_agent = True
                    
                    logger.info(f"Orchestrator: mode={_orch_plan.get('mode')}, model={_orch_model_override}, agent={_orch_plan.get('primary_agent')}")
                    
                except Exception as _orch_e:
                    logger.warning(f"Orchestrator failed, using default: {_orch_e}")
            
            # ── Создание AgentLoop с учётом оркестратора ──
            _final_model = _orch_model_override or model
            
            if multi_agent:
                loop = MultiAgentLoop(
                    model=_final_model, api_key=api_key,
                    orion_mode=orion_mode, session_id=chat_id
                )
            else:
                loop = AgentLoop(
                    model=_final_model, api_key=api_key,
                    orion_mode=orion_mode, session_id=chat_id
                )
            
            # Передать промпт агента и план
            if _orch_prompt_extra:
                loop._orchestrator_prompt = _orch_prompt_extra
            if _orch_plan:
                loop._orchestrator_plan = _orch_plan

            with _agents_lock:
                _active_agents[chat_id] = loop

            for raw_event in loop.run_stream(user_message, chat_history=history, file_content=file_content, ssh_credentials=ssh_credentials):
                # BUG-4 FIX: wrap each event in try/except to prevent SSE disconnects
                try:
                    # run_stream() возвращает либо строку SSE ("data: {...}\n\n")
                    # либо dict — нормализуем оба варианта
                    if isinstance(raw_event, str):
                        # Уже готовая SSE строка — парсим для накопления текста
                        yield raw_event
                        # Извлекаем content для сохранения
                        if raw_event.startswith("data: "):
                            try:
                                ev = _json.loads(raw_event[6:].strip())
                                ev_type = ev.get("type", "")
                                if ev_type == "content":
                                    assistant_content += ev.get("text", ev.get("content", ""))
                                elif ev_type in ("text", "text_complete"):
                                    assistant_content += ev.get("content", ev.get("text", ""))
                            except Exception as _ev_err:
                                logging.warning(f"Event parse error: {_ev_err}")
                    else:
                        # dict — нормализуем тип и отправляем
                        ev_type = raw_event.get("type", "")
                        if ev_type == "text_delta":
                            raw_event = {"type": "content", "text": raw_event.get("text", raw_event.get("content", ""))}
                        elif ev_type == "text_complete":
                            raw_event = {"type": "content", "text": raw_event.get("content", "")}
                        yield "data: " + _json.dumps(raw_event) + SSE
                        if ev_type in ("content", "text", "text_complete", "text_delta"):
                            assistant_content += raw_event.get("text", raw_event.get("content", ""))
                except GeneratorExit:
                    break
                except Exception as _ev_err:
                    logging.error(f"SSE event error: {_ev_err}")
                    continue

        except GeneratorExit:
            pass  # Клиент отключился — не делаем yield
        except Exception as e:
            err_msg = "Ошибка агента: " + str(e)
            try:
                yield "data: " + _json.dumps({"type": "error", "content": err_msg}) + SSE
            except GeneratorExit:
                pass
            assistant_content = err_msg
        finally:
            with _agents_lock:
                _active_agents.pop(chat_id, None)

            # Сохраняем ответ ассистента
            if assistant_content:
                asst_msg = {
                    "id": assistant_msg_id, "role": "assistant",
                    "content": assistant_content, "timestamp": time.time()
                }
                with _lock:
                    db3 = _load_db()
                    if chat_id in db3["chats"]:
                        db3["chats"][chat_id]["messages"].append(asst_msg)
                        db3["chats"][chat_id]["updated_at"] = time.time()
                        _save_db(db3)

            # НЕ делаем yield в finally — это вызывает RuntimeError: generator ignored GeneratorExit


    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Access-Control-Allow-Origin": "*",
        }
    )


# ── Quick Chat (non-streaming for simple questions) ────────────
@app.route("/api/chat/quick", methods=["POST"])
@require_auth
def quick_chat():
    """Quick non-streaming chat response."""
    data = request.get_json() or {}
    message = data.get("message", "")
    user_settings = request.user.get("settings", {})
    chat_model_key = user_settings.get("chat_model", "qwen3")
    chat_model = CHAT_MODELS.get(chat_model_key, CHAT_MODELS["qwen3"])

    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
    }

    resp = http_requests.post(OPENROUTER_BASE_URL, headers=headers, json={
        "model": chat_model["model"],
        "messages": [
            {"role": "system", "content": "Ты — полезный AI-ассистент. Отвечай кратко и по делу на русском языке."},
            {"role": "user", "content": message}
        ],
        "temperature": 0.5,
        "max_tokens": 2000
    }, timeout=30)

    result = resp.json()
    choices = result.get("choices", [])
    content = choices[0].get("message", {}).get("content", "Ошибка") if choices else "Ошибка: пустой ответ"
    return jsonify({"response": content})


# ── Analytics ──────────────────────────────────────────────────
@app.route("/api/analytics", methods=["GET"])
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
@app.route("/api/admin/users", methods=["GET"])
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


@app.route("/api/admin/users", methods=["POST"])
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
        "password_hash": hashlib.sha256(password.encode()).hexdigest(),
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


@app.route("/api/admin/users/<user_id>", methods=["PUT"])
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
        user["password_hash"] = hashlib.sha256(data["password"].encode()).hexdigest()

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


@app.route("/api/admin/users/<user_id>", methods=["DELETE"])
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


@app.route("/api/admin/users/<user_id>/toggle", methods=["POST"])
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


@app.route("/api/admin/users/<user_id>/limit", methods=["PUT"])
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


@app.route("/api/admin/users/<user_id>/chats", methods=["GET"])
@require_auth
@require_admin
def admin_user_chats(user_id):
    """View user's chats (admin only)."""
    db = db_read()
    user_chats = [c for c in db["chats"].values() if c.get("user_id") == user_id]
    user_chats.sort(key=lambda x: x.get("updated_at", ""), reverse=True)
    return jsonify({"chats": user_chats})


@app.route("/api/admin/chats", methods=["GET"])
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


@app.route("/api/admin/chats/<chat_id>", methods=["GET"])
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


@app.route("/api/admin/chats/<chat_id>", methods=["DELETE"])
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


@app.route("/api/admin/stats", methods=["GET"])
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
@app.route("/api/memory/search", methods=["POST"])
@require_auth
def search_memory():
    """Search memory — both legacy episodic and vector memory."""
    data = request.get_json() or {}
    query = data.get("query", "").lower()
    limit = data.get("limit", 5)

    # Legacy episodic search
    db = db_read()
    episodes = db.get("memory", {}).get("episodic", [])
    legacy_results = []
    for ep in reversed(episodes):
        task = ep.get("task", "").lower()
        score = sum(1 for word in query.split() if word in task)
        if score > 0:
            legacy_results.append({**ep, "relevance": score, "source": "episodic"})
    legacy_results.sort(key=lambda x: x["relevance"], reverse=True)

    # Vector memory search (cross-chat)
    vector_results = []
    try:
        vmem = _get_memory()
        vector_results = vmem.search(query, limit=limit, user_id=request.user_id)
        for vr in vector_results:
            vr["source"] = "vector"
    except Exception as _vec_err:
        logging.warning(f"Vector search error: {_vec_err}")

    return jsonify({
        "results": legacy_results[:limit],
        "vector_results": vector_results[:limit]
    })


@app.route("/api/memory/context", methods=["POST"])
@require_auth
def get_memory_context():
    """Get relevant memory context for a query (cross-chat learning)."""
    data = request.get_json() or {}
    query = data.get("query", "")
    if not query:
        return jsonify({"context": ""})

    try:
        vmem = _get_memory()
        context = vmem.get_relevant_context(query, user_id=request.user_id)
        return jsonify({"context": context})
    except Exception as e:
        return jsonify({"context": "", "error": str(e)})


@app.route("/api/memory/stats", methods=["GET"])
@require_auth
def memory_stats():
    """Get memory statistics."""
    try:
        vmem = _get_memory()
        return jsonify(vmem.get_stats())
    except Exception as e:
        return jsonify({"error": str(e)})


# ── File Versioning API ─────────────────────────────────────────────
@app.route("/api/versions/files", methods=["GET"])
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


@app.route("/api/versions/history", methods=["GET"])
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


@app.route("/api/versions/diff", methods=["GET"])
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


@app.route("/api/versions/rollback", methods=["POST"])
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


@app.route("/api/versions/stats", methods=["GET"])
@require_auth
def file_version_stats():
    """Get file versioning statistics."""
    try:
        store = _get_versions()
        return jsonify(store.get_stats())
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ── Rate Limiting API ──────────────────────────────────────────────
@app.route("/api/rate-limit/status", methods=["GET"])
@require_auth
def rate_limit_status():
    """Get current rate limit status for user."""
    rl = _get_rate_limiter()
    ip = request.remote_addr or "unknown"
    usage = rl.get_all_usage(user_id=request.user_id, ip=ip)
    return jsonify(usage)


# ── Generated Files ───────────────────────────────────────────────
@app.route("/api/files/<file_id>/download", methods=["GET"])
def download_generated_file(file_id):
    """Download a generated file by ID. No auth required for direct download links."""
    filepath, filename = get_file_path(file_id)
    if not filepath or not os.path.exists(filepath):
        return jsonify({"error": "File not found"}), 404

    mime_type, _ = mimetypes.guess_type(filename)
    if not mime_type:
        mime_type = 'application/octet-stream'

    with open(filepath, 'rb') as f:
        data = f.read()

    return Response(
        data,
        mimetype=mime_type,
        headers={
            'Content-Disposition': f'attachment; filename="{filename}"',
            'Content-Length': str(len(data))
        }
    )


@app.route("/api/files/<file_id>/preview", methods=["GET"])
def preview_generated_file(file_id):
    """Preview a generated file (HTML, images) in browser."""
    filepath, filename = get_file_path(file_id)
    if not filepath or not os.path.exists(filepath):
        return jsonify({"error": "File not found"}), 404

    mime_type, _ = mimetypes.guess_type(filename)
    if not mime_type:
        mime_type = 'text/plain'

    with open(filepath, 'rb') as f:
        data = f.read()

    return Response(
        data,
        mimetype=mime_type,
        headers={'Content-Disposition': f'inline; filename="{filename}"'}
    )


@app.route("/api/files/<file_id>/info", methods=["GET"])
@require_auth
def file_info(file_id):
    """Get info about a generated file."""
    info = get_file_info(file_id)
    if not info:
        return jsonify({"error": "File not found"}), 404
    return jsonify(info)


@app.route("/api/files", methods=["GET"])
@require_auth
def list_files_endpoint():
    """List generated files for current user."""
    chat_id = request.args.get("chat_id")
    limit = int(request.args.get("limit", 50))
    files = list_generated_files(chat_id=chat_id, user_id=request.user_id, limit=limit)
    return jsonify({"files": files, "total": len(files)})


@app.route("/api/files/generate", methods=["POST"])
@require_auth
def generate_file_endpoint():
    """Generate a file on demand (from frontend)."""
    data = request.get_json()
    if not data:
        return jsonify({"error": "No data provided"}), 400

    content = data.get("content", "")
    filename = data.get("filename", "file.txt")
    title = data.get("title")

    if not content:
        return jsonify({"error": "content is required"}), 400

    result = generate_file(
        content=content,
        filename=filename,
        title=title,
        chat_id=data.get("chat_id"),
        user_id=request.user_id
    )
    return jsonify(result)


# ── Export ─────────────────────────────────────────────────────────
@app.route("/api/chats/<chat_id>/export", methods=["GET"])
@require_auth
def export_chat(chat_id):
    """Export chat as ZIP with all generated files."""
    db = db_read()
    chat = db["chats"].get(chat_id)
    if not chat or (chat.get("user_id") != request.user_id and request.user.get("role") != "admin"):
        return jsonify({"error": "Chat not found"}), 404

    files = {}
    for msg in chat.get("messages", []):
        if msg.get("role") == "assistant":
            content = msg.get("content", "")
            pattern = r'```(\w+)\s+([\w\-./]+\.\w+)\n(.*?)```'
            matches = re.findall(pattern, content, re.DOTALL)
            for lang, filename, code in matches:
                files[filename] = code

            if not matches:
                pattern2 = r'```(\w+)\n(.*?)```'
                matches2 = re.findall(pattern2, content, re.DOTALL)
                for i, (lang, code) in enumerate(matches2):
                    ext_map = {'html': '.html', 'css': '.css', 'javascript': '.js', 'js': '.js',
                               'python': '.py', 'py': '.py', 'json': '.json', 'sql': '.sql'}
                    ext = ext_map.get(lang, f'.{lang}')
                    files[f"file_{i+1}{ext}"] = code

    if not files:
        return jsonify({"error": "No code files found in chat"}), 404

    zip_path = os.path.join(UPLOAD_DIR, f"export_{chat_id}.zip")
    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zf:
        for fname, content in files.items():
            zf.writestr(fname, content)

    with open(zip_path, 'rb') as f:
        zip_data = f.read()

    os.remove(zip_path)

    return Response(
        zip_data,
        mimetype='application/zip',
        headers={'Content-Disposition': f'attachment; filename=orion-{chat_id}.zip'}
    )


# ── Health Check ───────────────────────────────────────────────
@app.route("/api/health", methods=["GET"])
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


@app.route("/api/models", methods=["GET"])
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


# ══════════════════════════════════════════════════════════════════
# ██ CANVAS API ██
# ══════════════════════════════════════════════════════════════════

@app.route("/api/canvas", methods=["GET"])
def list_canvases():
    """List all canvas documents for the user."""
    try:
        from project_manager import list_canvases as pm_list_canvases
        user_id = request.args.get("user_id", "default")
        canvases = pm_list_canvases(user_id)
        return jsonify({"success": True, "canvases": canvases})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/canvas/<canvas_id>", methods=["GET"])
def get_canvas(canvas_id):
    """Get a specific canvas document."""
    try:
        from project_manager import get_canvas as pm_get_canvas
        canvas = pm_get_canvas(canvas_id)
        if canvas:
            return jsonify({"success": True, "canvas": canvas})
        return jsonify({"success": False, "error": "Canvas not found"}), 404
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/canvas/<canvas_id>", methods=["PUT"])
def update_canvas(canvas_id):
    """Update a canvas document."""
    try:
        from project_manager import update_canvas as pm_update_canvas
        data = request.get_json()
        content = data.get("content", "")
        title = data.get("title")
        result = pm_update_canvas(canvas_id, content, title)
        return jsonify(result)
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/canvas/<canvas_id>", methods=["DELETE"])
def delete_canvas(canvas_id):
    """Delete a canvas document."""
    try:
        from project_manager import delete_canvas as pm_delete_canvas
        result = pm_delete_canvas(canvas_id)
        return jsonify(result)
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


# ══════════════════════════════════════════════════════════════════
# ██ MEMORY API ██
# ══════════════════════════════════════════════════════════════════

@app.route("/api/memory", methods=["GET"])
def list_memories():
    """List stored memories."""
    try:
        from project_manager import get_memory_items
        user_id = request.args.get("user_id", "default")
        memories = get_memory_items(user_id)
        return jsonify({"success": True, "memories": memories})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/memory", methods=["POST"])
def store_memory_api():
    """Store a new memory."""
    try:
        from project_manager import store_memory
        data = request.get_json()
        key = data.get("key", "")
        value = data.get("value", "")
        user_id = data.get("user_id", "default")
        category = data.get("category", "fact")
        result = store_memory(key, value, user_id, category=category)
        return jsonify(result)
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/memory/<memory_id>", methods=["DELETE"])
def delete_memory(memory_id):
    """Delete a memory entry."""
    try:
        from project_manager import delete_memory as pm_delete_memory
        result = pm_delete_memory(memory_id)
        return jsonify(result)
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


# ══════════════════════════════════════════════════════════════════
# ██ CUSTOM AGENTS API ██
# ══════════════════════════════════════════════════════════════════

@app.route("/api/agents/custom", methods=["GET"])
def list_custom_agents():
    """List custom agent configurations."""
    try:
        from project_manager import list_custom_agents as pm_list_agents
        user_id = request.args.get("user_id", "default")
        agents = pm_list_agents(user_id)
        return jsonify({"success": True, "agents": agents})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/agents/custom", methods=["POST"])
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


@app.route("/api/agents/custom/<agent_id>", methods=["DELETE"])
def delete_custom_agent(agent_id):
    """Delete a custom agent."""
    try:
        from project_manager import delete_custom_agent as pm_delete_agent
        result = pm_delete_agent(agent_id)
        return jsonify(result)
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


# ══════════════════════════════════════════════════════════════════
# ██ TEMPLATES API ██
# ══════════════════════════════════════════════════════════════════

@app.route("/api/templates", methods=["GET"])
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


# ══════════════════════════════════════════════════════════════════
# ██ USAGE ANALYTICS API ██
# ══════════════════════════════════════════════════════════════════

@app.route("/api/analytics/usage", methods=["GET"])
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


# ══════════════════════════════════════════════════════════════════
# ██ FEEDBACK API ██
# ══════════════════════════════════════════════════════════════════

@app.route("/api/feedback", methods=["POST"])
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


@app.route("/api/feedback", methods=["GET"])
@require_auth
def list_feedback():
    """List feedback entries."""
    db = _load_db()
    feedback = db.get("feedback", [])
    return jsonify({"success": True, "feedback": feedback[-100:]})


# ══════════════════════════════════════════════════════════════════
# ██ SECURITY CHECK API ██
# ══════════════════════════════════════════════════════════════════

@app.route("/api/security/check-prompt", methods=["POST"])
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


# ══════════════════════════════════════════════════════════════════
# ██ GDPR COMPLIANCE API ██
# ══════════════════════════════════════════════════════════════════

@app.route("/api/gdpr/export", methods=["GET"])
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


@app.route("/api/gdpr/delete", methods=["DELETE"])
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


# ══════════════════════════════════════════════════════════════════
# ██ CONNECTORS / INTEGRATIONS API ██
# ══════════════════════════════════════════════════════════════════

@app.route("/api/connectors", methods=["GET"])
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


@app.route("/api/connectors/<connector_id>/connect", methods=["POST"])
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


@app.route("/api/connectors/<connector_id>/disconnect", methods=["POST"])
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


# ══════════════════════════════════════════════════════════════════
# ██ AUDIT LOG API ██
# ══════════════════════════════════════════════════════════════════

@app.route("/api/audit-log", methods=["GET"])
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


# ══════════════════════════════════════════════════════════════════
# ██ CONNECTORS TOGGLE API ██
# ══════════════════════════════════════════════════════════════════

@app.route("/api/connectors/<connector_id>", methods=["POST"])
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


# ══════════════════════════════════════════════════════════════════
# ██ CUSTOM AGENTS CRUD API ██
# ══════════════════════════════════════════════════════════════════

@app.route("/api/agents", methods=["GET"])
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


@app.route("/api/agents", methods=["POST"])
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


@app.route("/api/agents/<agent_id>", methods=["DELETE"])
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


# ══════════════════════════════════════════════════════════════════
# ██ AUDIT LOGS API (frontend-compatible) ██
# ══════════════════════════════════════════════════════════════════

@app.route("/api/audit/logs", methods=["GET"])
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


@app.route("/api/audit/export", methods=["GET"])
@require_auth
def export_audit_logs():
    """Export full audit log."""
    try:
        from security import get_audit_log
        entries = get_audit_log(limit=10000)
        return jsonify({"success": True, "logs": entries, "exported_at": datetime.now(timezone.utc).isoformat()})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


# ══════════════════════════════════════════════════════════════════
# ██ MODEL ROUTER ANALYTICS API ██
# ══════════════════════════════════════════════════════════════════

@app.route("/api/analytics/costs", methods=["GET"])
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


@app.route("/api/model-router/classify", methods=["POST"])
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


# ══════════════════════════════════════════════════════════════════
# ██ SPECIALIZED AGENTS API ██
# ══════════════════════════════════════════════════════════════════

@app.route("/api/specialized-agents", methods=["GET"])
@require_auth
def get_specialized_agents_list():
    """Get list of all 6 specialized agents."""
    agents = get_all_agents()
    return jsonify({"success": True, "agents": agents, "count": len(agents)})


@app.route("/api/specialized-agents/select", methods=["POST"])
@require_auth
def select_agents_api():
    """Select best agents for a task."""
    data = request.get_json() or {}
    query = data.get("query", "")
    mode = data.get("mode", "chat")
    max_agents = data.get("max_agents", 3)
    agents = select_agents_for_task(query, mode, max_agents=max_agents)
    return jsonify({"success": True, "agents": agents})


@app.route("/api/specialized-agents/pipelines", methods=["GET"])
@require_auth
def get_agent_pipelines():
    """Get predefined agent pipelines."""
    pipelines = {}
    for ptype in ["deploy", "website", "api", "full_project"]:
        pipelines[ptype] = get_agent_pipeline(ptype)
    return jsonify({"success": True, "pipelines": pipelines})


# ══════════════════════════════════════════════════════════════════
# ██ PROJECT MEMORY API ██
# ══════════════════════════════════════════════════════════════════

@app.route("/api/project-memory/context", methods=["POST"])
@require_auth
def get_project_memory_context():
    """Get full project memory context for a chat."""
    data = request.get_json() or {}
    chat_id = data.get("chat_id", "")
    project_id = data.get("project_id")
    pm = ProjectMemory(user_id=request.user_id, project_id=project_id)
    context = pm.get_full_context(chat_id)
    return jsonify({"success": True, "context": context, "length": len(context)})


@app.route("/api/project-memory/active-tasks", methods=["GET"])
@require_auth
def get_active_tasks_api():
    """Get all active/paused tasks."""
    pm = ProjectMemory(user_id=request.user_id)
    tasks = pm.get_active_tasks()
    return jsonify({"success": True, "tasks": tasks, "count": len(tasks)})


@app.route("/api/project-memory/checkpoint", methods=["POST"])
@require_auth
def save_task_checkpoint():
    """Save a task checkpoint for later resumption."""
    data = request.get_json() or {}
    pm = ProjectMemory(user_id=request.user_id, project_id=data.get("project_id"))
    result = pm.save_checkpoint(
        chat_id=data.get("chat_id", ""),
        task=data.get("task", ""),
        progress=data.get("progress", ""),
        steps_completed=data.get("steps_completed", []),
        steps_remaining=data.get("steps_remaining", []),
        context=data.get("context", {})
    )
    return jsonify({"success": True, "checkpoint": result})


# ══════════════════════════════════════════════════════════════════
# ██ GDPR ANONYMIZE API ██
# ══════════════════════════════════════════════════════════════════

@app.route("/api/gdpr/anonymize", methods=["POST"])
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
@app.route("/api/chats/<chat_id>/subscribe", methods=["GET"])
def subscribe_chat(chat_id):
    """SSE подписка на обновления чата (для совместной работы)."""
    import time as _time
    def stream():
        last_count = 0
        while True:
            db = db_read()
            chat = db["chats"].get(chat_id, {})
            msgs = chat.get("messages", [])
            if len(msgs) > last_count:
                new_msgs = msgs[last_count:]
                for m in new_msgs:
                    yield f"data: {json.dumps({'type': 'new_message', 'message': m}, ensure_ascii=False)}\n\n"
                last_count = len(msgs)
            _time.sleep(2)
    return Response(stream(), mimetype="text/event-stream")


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 3510))
    app.run(host="0.0.0.0", port=port, debug=False)


# ══════════════════════════════════════════════════════════════════
# ██ ORION SPRINT 5 — NEW API ENDPOINTS ██
# ══════════════════════════════════════════════════════════════════

@app.route("/api/modes", methods=["GET"])
def get_modes():
    """Список режимов работы ORION (turbo_standard / pro_premium / ...)."""
    try:
        from model_router import list_modes, list_models
        return jsonify({
            "success": True,
            "modes": list_modes(),
            "models": list_models(),
            "default": "turbo_standard"
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/intent/clarify", methods=["POST"])
@require_auth
def api_clarify_intent():
    """Анализ intent запроса пользователя."""
    try:
        from intent_clarifier import clarify, format_clarification_for_user
        data = request.get_json() or {}
        message = data.get("message", "")
        orion_mode = data.get("mode", "turbo_standard")
        history = data.get("history", [])
        result = clarify(message, history=history, orion_mode=orion_mode)
        result["label"] = format_clarification_for_user(result)
        return jsonify({"success": True, "intent": result})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/cost/session", methods=["GET"])
@require_auth
def get_session_cost():
    """Стоимость текущей сессии."""
    try:
        from model_router import get_cost_analytics, check_cost_limit
        session_id = request.args.get("session_id", request.user_id)
        orion_mode = request.args.get("mode", "turbo_standard")
        cost_check = check_cost_limit(session_id, orion_mode)
        analytics = get_cost_analytics(user_id=request.user_id, days=1)
        return jsonify({
            "success": True,
            "session": cost_check,
            "analytics": analytics
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/cost/analytics", methods=["GET"])
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


@app.route("/api/agent-zones", methods=["GET"])
def get_agent_zones():
    """Зоны ответственности агентов."""
    try:
        from agent_loop import AGENT_ZONES
        return jsonify({"success": True, "zones": AGENT_ZONES})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


# ══════════════════════════════════════════════════════════════════
# ПАТЧ ЗАДАЧА-1: Auth Response — пользователь отправляет данные авторизации
# ══════════════════════════════════════════════════════════════════
_auth_pending = {}  # chat_id -> {auth_data, url, timestamp}

@app.route("/api/auth-response", methods=["POST"])
def auth_response():
    """
    Пользователь отправляет данные авторизации для browser_ask_auth.
    Данные хранятся временно и используются агентом для browser_fill + browser_submit.
    """
    import time as _time
    data = request.get_json()
    chat_id = data.get("chat_id")
    auth_data = data.get("auth_data", {})
    url = data.get("url", "")
    
    if not chat_id:
        return jsonify({"error": "chat_id required"}), 400
    
    _auth_pending[chat_id] = {
        "auth_data": auth_data,
        "url": url,
        "timestamp": _time.time()
    }
    
    # Очистка старых записей (>5 мин)
    expired = [k for k, v in _auth_pending.items() if _time.time() - v["timestamp"] > 300]
    for k in expired:
        del _auth_pending[k]
    
    return jsonify({"success": True, "message": "Данные получены"})


@app.route("/api/auth-pending/<chat_id>", methods=["GET"])
def get_auth_pending(chat_id):
    """Агент получает данные авторизации и удаляет их."""
    pending = _auth_pending.pop(chat_id, None)
    if pending:
        return jsonify({"success": True, "auth_data": pending["auth_data"], "url": pending["url"]})
    return jsonify({"success": False, "message": "Нет ожидающих данных"}), 404


# ══════════════════════════════════════════════════════════════════
# ПАТЧ W2-4: Автосмета — /api/estimate
# ══════════════════════════════════════════════════════════════════

ESTIMATE_RATES = {
    "landing": {"hours": 2, "rate_rub": 3000, "description": "Лендинг / одностраничник"},
    "corporate": {"hours": 6, "rate_rub": 3000, "description": "Корпоративный сайт (5-8 страниц)"},
    "ecommerce": {"hours": 12, "rate_rub": 3000, "description": "Интернет-магазин"},
    "integration": {"hours": 4, "rate_rub": 3500, "description": "Интеграция (CRM, API, бот)"},
    "deploy": {"hours": 2, "rate_rub": 2500, "description": "Деплой / настройка сервера"},
    "seo": {"hours": 3, "rate_rub": 2500, "description": "SEO-оптимизация"},
    "design": {"hours": 3, "rate_rub": 3000, "description": "Дизайн / UI"},
    "bot": {"hours": 5, "rate_rub": 3000, "description": "Telegram/WhatsApp бот"},
    "custom": {"hours": 8, "rate_rub": 3000, "description": "Индивидуальная разработка"},
}

@app.route("/api/estimate", methods=["POST"])
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
                    "model": "openai/gpt-4.1-mini",
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
