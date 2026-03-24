"""
ORION Digital v1.0 — Backend API Server
Автономный AI-инженер с мультиагентной системой, SSH executor,
browser agent, долговременной памятью, file versioning, rate limiting,
contracts validation, self-healing 2.0, LangGraph StateGraph.
v6.0: Creative Suite, Web Search, Memory & Projects, Canvas, Multi-Model Routing.
"""

import logging
logger = logging.getLogger(__name__)

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
import bcrypt
# ══ SECURITY FIX 7: Fernet encryption for secrets in DB ══
from cryptography.fernet import Fernet

def _get_fernet():
    """Get Fernet cipher from ORION_ENCRYPT_KEY env var."""
    key = os.environ.get("ORION_ENCRYPT_KEY", "")
    if not key:
        raise RuntimeError(
            "ORION_ENCRYPT_KEY not set! Generate:\n"
            "python3 -c 'from cryptography.fernet import Fernet; "
            "print(Fernet.generate_key().decode())'"
        )
    return Fernet(key.encode() if isinstance(key, str) else key)

_SECRET_SETTINGS_KEYS = {"ssh_password", "github_token", "n8n_api_key"}

def _encrypt_setting(value: str) -> str:
    """Encrypt a secret setting value."""
    if not value or value.startswith("gAAAAA"):
        return value  # Already encrypted or empty
    try:
        return _get_fernet().encrypt(value.encode()).decode()
    except Exception as e:
        logger.error(f"[SECURITY] Encryption failed: {e}")
        return value

def _decrypt_setting(value: str) -> str:
    """Decrypt a secret setting value."""
    if not value or not value.startswith("gAAAAA"):
        return value  # Not encrypted
    try:
        return _get_fernet().decrypt(value.encode()).decode()
    except Exception as e:
        logger.error(f"[SECURITY] Decryption failed: {e}")
        return value

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

# ── PATCH: Preload SentenceTransformer encoder at startup (background thread) ──
def _preload_sentence_encoder():
    try:
        from solution_cache import _get_global_encoder
        enc = _get_global_encoder()
        if enc:
            logging.info('[STARTUP] SentenceTransformer encoder preloaded OK')
        else:
            logging.warning('[STARTUP] SentenceTransformer encoder preload failed (fallback will be used)')
    except Exception as e:
        logging.warning(f'[STARTUP] SentenceTransformer preload error: {e}')

import threading as _preload_thread
_preload_thread.Thread(target=_preload_sentence_encoder, daemon=True, name='encoder-preload').start()
_preload_encoder_done = True
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

# SQLite database (mandatory — JSON fallback removed in TASK 5)
from database import load_db as _sqlite_load, save_db as _sqlite_save, init_db
init_db()

# DB_FILE removed in TASK 5 — SQLite is the only storage
# DB_FILE = os.path.join(DATA_DIR, "database.json")  # LEGACY
_lock = threading.Lock()
_USE_SQLITE = True  # All storage is SQLite (TASK 5)

# Active agent loops (for stop functionality)
_active_agents = {}
_agents_lock = threading.Lock()

# ══ TASK PERSISTENCE: running tasks buffer for SSE reconnect ══
_running_tasks = {}

import threading as _task_threading



def _cleanup_running_task(chat_id, delay=30):
    """Remove a completed task from _running_tasks after a delay."""
    def _do_cleanup():
        with _tasks_lock:
            task = _running_tasks.get(chat_id)
            if task and task.get("status") == "done":
                _running_tasks.pop(chat_id, None)
                print(f"[TaskCleanup] Removed completed task for chat {chat_id}")
    timer = _task_threading.Timer(delay, _do_cleanup)
    timer.daemon = True
    timer.start()

_tasks_lock = threading.Lock()

# ══ PATCH 14: Manus-style task interruption / queue / append ══
# _paused_tasks: {chat_id: {"messages": [...], "iteration": int, "charter": str,
#                           "actions_log": [...], "user_id": str, "task": str}}
_paused_tasks = {}
# _message_queue: {chat_id: [{"message": str, "mode": str, "user_id": str, "file_content": str}]}
_message_queue = {}
_interrupt_lock = threading.Lock()

# ══ PATCH 14 FIX: Priority order: interrupt > append > queue ══
# Keywords that INTERRUPT current task (highest priority — always wins)
_INTERRUPT_KEYWORDS = [
    "стоп", "stop", "срочно", "прекрати", "отмени", "отмена",
    "измени", "переделай", "переключись", "брось", "хватит",
    "не то", "не так", "заново", "сначала", "cancel", "abort"
]
# Keywords that APPEND to current task (agent sees on next iteration)
_APPEND_KEYWORDS = [
    "добавь к текущей", "также", "ещё", "и ещё", "плюс к этому",
    "дополнительно", "заодно", "и также", "а ещё", "к этому добавь",
    "добавь"
]
# Keywords that put message INTO QUEUE (agent finishes current first)
_QUEUE_KEYWORDS = [
    "после текущей", "потом", "когда закончишь", "после того как",
    "когда освободишься", "после завершения", "после этого", "затем",
    "следующей задачей", "следующая задача"
]


def _classify_interrupt_message(text: str) -> str:
    """Classify incoming message during active task.
    Priority: interrupt > append > queue > default(interrupt)
    Examples:
      'Стоп, ещё добавь секцию' -> interrupt (стоп wins)
      'Ещё добавь footer' -> append
      'Потом сделай сайт' -> queue
    """
    lower = text.lower().strip()
    # 1) INTERRUPT keywords have highest priority
    for kw in _INTERRUPT_KEYWORDS:
        if kw in lower:
            return "interrupt"
    # 2) APPEND keywords (modify current task)
    for kw in _APPEND_KEYWORDS:
        if kw in lower:
            return "append"
    # 3) QUEUE keywords (do after current task)
    for kw in _QUEUE_KEYWORDS:
        if kw in lower:
            return "queue"
    # 4) Default: treat as interrupt (new task replaces current)
    return "interrupt"

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
# MODEL_CONFIGS: реальные ID моделей из model_router.py (PATCH 12 fix2)
MODEL_CONFIGS = {
    "original": {
        "name": "Оригинал",
        "emoji": "🔴",
        "coding": {"model": "openai/gpt-5.4-nano", "name": "MiMo-V2-Flash", "input_price": 0.09, "output_price": 0.29},
        "planner": {"model": "anthropic/claude-sonnet-4.6", "name": "Claude Sonnet 4.6", "input_price": 3.00, "output_price": 15.00},
        "tools": {"model": "openai/gpt-5.4-nano", "name": "MiMo-V2-Flash", "input_price": 0.09, "output_price": 0.29},
        "quality": 72.1,
        "monthly_cost": "$2,200"
    },
    "premium": {
        "name": "Премиум",
        "emoji": "🟢",
        "coding": {"model": "openai/gpt-5.4-mini", "name": "MiniMax M2.5", "input_price": 0.20, "output_price": 1.10},
        "planner": {"model": "anthropic/claude-sonnet-4.6", "name": "Claude Sonnet 4.6", "input_price": 3.00, "output_price": 15.00},
        "tools": {"model": "openai/gpt-5.4-nano", "name": "MiMo-V2-Flash", "input_price": 0.09, "output_price": 0.29},
        "quality": 80.2,
        "monthly_cost": "$1,750"
    },
    "budget": {
        "name": "Бюджет",
        "emoji": "🔵",
        "coding": {"model": "openai/gpt-5.4-nano", "name": "MiMo-V2-Flash", "input_price": 0.09, "output_price": 0.29},
        "planner": {"model": "openai/gpt-5.4-mini", "name": "MiniMax M2.5", "input_price": 0.20, "output_price": 1.10},
        "tools": {"model": "openai/gpt-5.4-nano", "name": "MiMo-V2-Flash", "input_price": 0.09, "output_price": 0.29},
        "quality": 75.8,
        "monthly_cost": "$750"
    }
}  # PATCH fix: replaced deepseek with mimo/minimax

# CHAT_MODELS: реальные ID моделей (PATCH 12 fix2)
CHAT_MODELS = {
    "qwen3":    {"model": "openai/gpt-5.4-mini",   "name": "MiniMax M2.5",    "lang": "RU ⭐⭐⭐⭐⭐", "input_price": 0.20, "output_price": 1.10},
    "mimo":     {"model": "openai/gpt-5.4-nano",   "name": "MiMo-V2-Flash",  "lang": "RU ⭐⭐⭐⭐",  "input_price": 0.09, "output_price": 0.29},
    "gpt5nano": {"model": "openai/gpt-5.4-mini",   "name": "MiniMax M2.5",   "lang": "RU ⭐⭐⭐⭐",  "input_price": 0.20, "output_price": 1.10},
}  # PATCH fix: replaced deepseek with mimo

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

# Helper: ISO timestamp

def _now_iso():
    return datetime.now(timezone.utc).isoformat()

# Helper: calculate cost for Pro/Architect models

def _calc_cost(tokens_in, tokens_out, model_name):
    """Calculate cost based on model pricing."""
    PRICING = {
        'anthropic/claude-sonnet-4.6': (3.00, 15.00),
        'anthropic/claude-opus-4': (15.00, 75.00),
        'anthropic/claude-sonnet-4.6': (3.00, 15.00),
        'anthropic/claude-sonnet-4': (3.00, 15.00),
        'openai/gpt-5.4-mini': (0.20, 1.10),
        'minimax/minimax-m2.7': (0.20, 1.10),
        'openai/gpt-5.4-nano': (0.09, 0.29),
        'xiaomi/mimo-v2-omni':  (0.15, 0.75),
        # deepseek kept as fallback for cost calculation
        'openai/gpt-5.4-mini': (0.27, 1.10),  # fallback 3rd level
    }
    in_price, out_price = PRICING.get(model_name, (3.00, 15.00))
    return round((tokens_in / 1_000_000) * in_price + (tokens_out / 1_000_000) * out_price, 6)

# ── Database Layer ─────────────────────────────────────────────────────

_DEFAULT_DB = {
    "users": {
        "admin": {
            "id": "admin",
            "email": "ym@mksmedia.ru",
            "password_hash": bcrypt.hashpw(
                os.environ.get("ORION_ADMIN_PASSWORD", secrets.token_hex(16)).encode(), bcrypt.gensalt()
            ).decode(),  # PATCH 12 fix3: random fallback if env not set (no hardcoded default)
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
    """Load database from SQLite (TASK 5: JSON fallback removed)."""
    try:
        data = _sqlite_load()
        if data and data.get("users"):
            return data
        return _DEFAULT_DB.copy()
    except Exception as e:
        logging.error(f"SQLite load failed: {e}")
        return _DEFAULT_DB.copy()



def _save_db(db):
    """Save database to SQLite (TASK 5: JSON fallback removed)."""
    try:
        _sqlite_save(db)
    except Exception as e:
        logging.error(f"SQLite save failed: {e}")
        raise



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
        # ══ SECURITY FIX 2: Check HttpOnly cookie first, then Authorization header ══
        token = request.cookies.get("orion_token", "")
        if not token:
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
_LOGIN_LOCK_MAX = 20
_LOGIN_LOCK_DURATION = 5 * 60  # 15 минут
_login_lock_mutex = threading.Lock()

