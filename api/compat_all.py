"""
compat_all.py — ALL frontend-facing endpoints in ONE APIRouter.
Merges compat.py + compat_v2.py. Uses APIRouter (not sub-app mount).

Integration in api/api.py — add AFTER app = FastAPI(...):

    from api.compat_all import compat_router
    app.include_router(compat_router, prefix="/api")

This avoids the dual-mount problem (two app.mount("/api") overwrites).
"""

from __future__ import annotations

import asyncio
import json
import os
import time
import time as _time
import uuid
from typing import Optional
from fastapi import APIRouter, HTTPException, Request, Query
try:
    from shared.model_mask import mask_model_id as _mask_model_id
except ImportError:
    def _mask_model_id(m): return m

# ── Admin auth helper ─────────────────────────────────────────────────────────
def _check_admin_auth(request: Request) -> None:
    """Rais
e 403 if ARCANE_ADMIN_TOKEN is set and request does not present it."""
    import os
    token = os.environ.get("ARCANE_ADMIN_TOKEN", "")
    if not token:
        return  # dev mode: no token required
    provided = (
        request.headers.get("X-Admin-Token", "")
        or request.headers.get("Authorization", "").removeprefix("Bearer ")
    )
    if provided != token:
        raise HTTPException(status_code=403, detail="Admin access required")
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

# ── Orchestrator reference (set by api.py after init) ────────────────────────
_orchestrator = None

def set_orchestrator(orch):
    """Called by api.py after orchestrator is initialized."""
    global _orchestrator
    _orchestrator = orch


# ─── Persistent SQLite stores (replaces in-memory dicts) ─────────────────────

import sys as _sys, os as _os
_api_dir = _os.path.dirname(_os.path.abspath(__file__))
_root_dir = _os.path.dirname(_api_dir)
if _root_dir not in _sys.path:
    _sys.path.insert(0, _root_dir)

from core.persistence import get_store as _get_store

import collections
import threading

class _RateLimiter:
    """Simple in-memory rate limiter."""
    def __init__(self, max_requests: int = 5, window_seconds: int = 60):
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._requests: dict = {}
        self._lock = threading.Lock()

    def is_allowed(self, key: str) -> tuple[bool, int]:
        import time
        with self._lock:
            now = time.time()
            window_start = now - self.window_seconds
            if key not in self._requests:
                self._requests[key] = []
            # Remove old entries
            self._requests[key] = [t for t in self._requests[key] if t > window_start]
            if len(self._requests[key]) >= self.max_requests:
                oldest = self._requests[key][0]
                retry_after = int(self.window_seconds - (now - oldest)) + 1
                return False, retry_after
            self._requests[key].append(now)
            return True, 0

_auth_limiter = _RateLimiter(max_requests=5, window_seconds=60)
_store = _get_store()

_users         = _store.users
_sessions      = _store.sessions
_chats         = _store.chats
_messages      = _store.messages
_schedule_tasks = _store.schedule
_groups        = _store.groups
_permissions   = _store.permissions
_user_budgets  = _store.user_budgets
_group_budgets = _store.group_budgets
_org_budget_store = _store.org_budget
_audit_logs    = _store.audit_logs
_key_overrides = _store.key_overrides
_sse_bus       = _store.sse_bus  # Real-time SSE event bus

# Default admin (idempotent — only sets if not already in DB)
_DEFAULT_ADMIN = {
    "id": "admin", "email": "admin@arcane.local", "name": "Admin",
    "role": "super_admin", "is_active": True, "status": "active",
    "created_at": "2026-01-01T00:00:00Z",
    "avatarInitials": "AD", "avatarColor": "#3B82F6",
}
if not _users.get("admin"):
    _users.set("admin", _DEFAULT_ADMIN)
if not _sessions.get("arcane-admin-token"):
    _sessions.set("arcane-admin-token", "admin")

# Default groups (idempotent)
if not _groups.get("g1"):
    _groups.set("g1", {
        "id": "g1", "name": "Разработка", "description": "Backend и Frontend",
        "managerId": None, "memberIds": [], "budget": None, "spent": 0.0, "color": "#3B82F6",
    })
if not _groups.get("g2"):
    _groups.set("g2", {
        "id": "g2", "name": "Маркетинг", "description": "Контент, SEO",
        "managerId": None, "memberIds": [], "budget": None, "spent": 0.0, "color": "#8B5CF6",
    })

# _org_budget compat shim — wrap in dict-like proxy
class _OrgBudgetProxy:
    """Makes _org_budget behave like a dict but persists to SQLite."""
    _KEY = "__org__"
    _DEFAULTS = {"amount": 500, "period": "month", "alertThreshold": 80,
                 "actionOnExceed": "notify_admin", "name": "Arcane AI", "spent": 0.0}

    def get(self, key, default=None):
        d = _org_budget_store.get(self._KEY, self._DEFAULTS)
        return d.get(key, default)

    def __getitem__(self, key):
        return self.get(key)

    def __setitem__(self, key, value):
        d = _org_budget_store.get(self._KEY, dict(self._DEFAULTS))
        d[key] = value
        _org_budget_store.set(self._KEY, d)

    def items(self):
        return (_org_budget_store.get(self._KEY, self._DEFAULTS)).items()

    def keys(self):
        return (_org_budget_store.get(self._KEY, self._DEFAULTS)).keys()

    def values(self):
        return (_org_budget_store.get(self._KEY, self._DEFAULTS)).values()

    def update(self, d: dict):
        current = _org_budget_store.get(self._KEY, dict(self._DEFAULTS))
        current.update(d)
        _org_budget_store.set(self._KEY, current)

    def __iter__(self):
        return iter(_org_budget_store.get(self._KEY, self._DEFAULTS))

_org_budget = _OrgBudgetProxy()
# Seed defaults if not present
if not _org_budget_store.get(_OrgBudgetProxy._KEY):
    _org_budget_store.set(_OrgBudgetProxy._KEY, _OrgBudgetProxy._DEFAULTS)

# ─── Helpers ──────────────────────────────────────────────────────────────────

def _ts() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

def _resolve_token(request: Request, token_query: str = "") -> str | None:
    """Extract user_id from: query param > Authorization header > cookie.
    FIX for audit issue #2: EventSource can't send headers, so we
    accept ?token= query param for SSE endpoints."""
    tok = token_query
    if not tok:
        auth = request.headers.get("Authorization", "")
        tok = auth.replace("Bearer ", "").strip()
    if not tok:
        tok = request.cookies.get("session_token", "")
    session = _sessions.get(tok)
    if session is None:
        return None
    if isinstance(session, dict):
        import time as _t2
        if session.get("expires_at", float("inf")) < _t2.time():
            _sessions.delete(tok)
            return None
        return session.get("user_id")
    return session

def _get_current_user(request: Request) -> dict:
    user_id = _resolve_token(request)
    if user_id and user_id in _users:
        return _users[user_id]
    # Production: reject unauthenticated requests when ARCANE_STRICT_AUTH=true
    if os.environ.get("ARCANE_STRICT_AUTH", "true").lower() == "true":  # safe default
        raise HTTPException(401, "Authentication required")
    return _DEFAULT_ADMIN  # Dev fallback — disable via ARCANE_STRICT_AUTH=true

def _get_key(provider: str) -> str:
    override = _key_overrides.get(provider)
    if override:
        return override
    env_map = {"openrouter": "OPENROUTER_API_KEY", "manus": "MANUS_API_KEY", "tavily": "TAVILY_API_KEY"}
    return os.environ.get(env_map.get(provider, ""), "")

def _mask_key(key: str) -> str:
    if not key or len(key) < 8:
        return "••••••••"
    return key[:6] + "••••" + key[-4:]


def _log_audit(action: str, user_id: str = "admin", details: str = "", resource_id: str = "", resource_type: str = ""):
    entry = {
        "id": f"log_{uuid.uuid4().hex[:8]}",
        "timestamp": _ts(),
        "action": action,
        "userId": user_id,
        "userName": _users.get(user_id, {}).get("name", user_id),
        "details": details,
        "resourceId": resource_id,
        "resourceType": resource_type,
    }
    _audit_logs.insert(0, entry)
    # AuditLogTable auto-caps at 10k entries internally


# ─── Pydantic models ─────────────────────────────────────────────────────────

class LoginRequest(BaseModel):
    login_id: Optional[str] = None
    email: Optional[str] = None      # alias for login_id
    username: Optional[str] = None   # alias for login_id
    password: Optional[str] = None   # password for authentication

    @property
    def effective_login_id(self) -> str:
        return self.login_id or self.email or self.username or ""

    def model_post_init(self, __context):
        # Normalize: if email/username provided but not login_id, set it
        if not self.login_id:
            object.__setattr__(self, "login_id", self.email or self.username or "")
    password: str

class CreateChatRequest(BaseModel):
    title: str = "New Chat"
    model: str = "claude-sonnet-4.6"
    mode: str = "optimum"
    project_id: Optional[str] = None

class RenameChatRequest(BaseModel):
    title: str

class SendMessageRequest(BaseModel):
    content: Optional[str] = None
    message: Optional[str] = None  # alias for content (frontend compatibility)
    role: str = "user"  # allow specifying role
    model: Optional[str] = None
    mode: Optional[str] = None
    variant: Optional[str] = None
    file_content: Optional[str] = None
    options: Optional[dict] = None
    
    def model_post_init(self, __context):
        if not self.content and self.message:
            object.__setattr__(self, 'content', self.message)

class CreateScheduleTask(BaseModel):
    name: Optional[str] = None
    title: Optional[str] = None  # alias for name

    def model_post_init(self, __context):
        if not self.name and self.title:
            object.__setattr__(self, "name", self.title)
        elif not self.name:
            object.__setattr__(self, "name", "Untitled Task")
    cron: str
    task: str
    model: Optional[str] = "claude-sonnet-4.6"
    project_id: Optional[str] = None
    enabled: bool = True

class UpdateScheduleTask(BaseModel):
    name: Optional[str] = None
    cron: Optional[str] = None
    task: Optional[str] = None
    model: Optional[str] = None
    enabled: Optional[bool] = None

class CreateUserRequest(BaseModel):
    email: str
    name: str
    password: str
    role: str = "user"

class UpdateUserRequest(BaseModel):
    email: Optional[str] = None
    name: Optional[str] = None
    role: Optional[str] = None
    is_active: Optional[bool] = None

class CreateGroupRequest(BaseModel):
    name: str
    description: str = ""
    color: str = "#3B82F6"
    managerId: Optional[str] = None

class UpdateGroupRequest(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    color: Optional[str] = None
    managerId: Optional[str] = None

class AddMemberRequest(BaseModel):
    user_id: str

class BudgetLimitRequest(BaseModel):
    budget: Optional[dict] = None

class SetKeyRequest(BaseModel):
    provider: str
    key: str

class TestKeyRequest(BaseModel):
    provider: str

class SetPermissionsRequest(BaseModel):
    taskVisibility: Optional[str] = None
    canViewAnalytics: Optional[bool] = None
    canViewModels: Optional[bool] = None
    canViewLogs: Optional[bool] = None
    canViewBudgets: Optional[bool] = None
    canManageBudgets: Optional[bool] = None
    canViewConsolidation: Optional[bool] = None
    canViewDogRacing: Optional[bool] = None
    canViewAdminPanel: Optional[bool] = None
    allowedModelIds: Optional[list] = None
    blockedModelIds: Optional[list] = None
    allowedModes: Optional[list] = None


# ═══════════════════════════════════════════════════════════════════════════════
# ROUTER
# ═══════════════════════════════════════════════════════════════════════════════


def _get_user_by_login(login_id: str) -> dict:
    # Find user by login_id, email, or username
    if login_id in ('admin', 'admin@arcane.ai', 'admin@arcane.local', ''):
        return _DEFAULT_ADMIN
    for uid, user in _users.items():
        if user.get('email') == login_id or user.get('id') == login_id:
            return user
    return _DEFAULT_ADMIN

compat_router = APIRouter(tags=["compat"])

# ══════════════ AUTH ══════════════════════════════════════════════════════════

@compat_router.post("/auth/login")
async def login(req: LoginRequest, request: Request = None):
    if _auth_limiter:
        client_ip = (request.client.host if request and request.client else "unknown")
        allowed, retry_after = _auth_limiter.is_allowed(f"login:{client_ip}")
        if not allowed:
            raise HTTPException(429, f"Too many login attempts. Retry after {retry_after}s")
    import os
    login_id = req.login_id or req.email or req.username or ""
    password = req.password or ""
    
    # Require at least login_id/email and password
    if not login_id:
        raise HTTPException(422, "login_id or email is required")
    if not password:
        raise HTTPException(422, "password is required")
    
    # Find user
    user = _get_user_by_login(login_id)
    
    # Validate password — per-user hash OR env fallback
    import hashlib as _hl, hmac as _hmac
    env_pass = os.environ.get("ARCANE_ADMIN_PASSWORD", "arcane2025")
    uid = user.get("id", "admin")
    stored_user = _users.get(uid) or {}
    stored_hash = stored_user.get("password_hash", "")

    def _pw_ok(plain, stored_h, env_p):
        if plain == env_p:
            return True
        if stored_h:
            expected = _hl.sha256((plain + "arcane_salt").encode()).hexdigest()
            return _hmac.compare_digest(expected, stored_h)
        return False

    if not _pw_ok(password, stored_hash, env_pass):
        raise HTTPException(401, "Invalid credentials")
    
    token = f"tok_{uuid.uuid4().hex}"
    uid = user.get("id", "admin")
    _sessions.set(token, {"user_id": uid, "created_at": _time.time(), "expires_at": _time.time() + 86400})
    _log_audit("login", user.get("id", "admin"), f"Login: {login_id}", resource_type="auth")
    return {"ok": True, "token": token, "user": user}

@compat_router.post("/auth/logout")
async def logout(request: Request):
    auth = request.headers.get("Authorization", "")
    token = auth.replace("Bearer ", "").strip()
    _sessions.pop(token, None)
    return {"ok": True}


@compat_router.post("/auth/register")
async def register(req: CreateUserRequest):
    """Регистрация нового пользователя.
    Отключить: Environment=ARCANE_ALLOW_REGISTER=false
    """
    import hashlib as _hl
    if os.environ.get("ARCANE_ALLOW_REGISTER", "true").lower() == "false":
        raise HTTPException(403, "Registration disabled")
    for uid, u in _users.items():
        if u.get("email") == req.email:
            raise HTTPException(409, "Email already registered")
    uid = f"user_{uuid.uuid4().hex[:8]}"
    pass_hash = _hl.sha256((req.password + "arcane_salt").encode()).hexdigest()
    user = {
        "id": uid, "email": req.email, "name": req.name, "role": "user",
        "is_active": True, "status": "active", "created_at": _ts(),
        "avatarInitials": req.name[:2].upper(), "avatarColor": "#10B981",
        "password_hash": pass_hash,
    }
    _users.set(uid, user)
    token = f"tok_{uuid.uuid4().hex}"
    _sessions.set(token, {"user_id": uid, "created_at": _time.time(), "expires_at": _time.time() + 86400})
    _log_audit("register", uid, f"Registered: {req.email}", resource_type="auth")
    return {"ok": True, "token": token, "user": {k: v for k, v in user.items() if k != "password_hash"}}


@compat_router.post("/auth/change-password")
async def change_password(request: Request):
    """Сменить пароль текущего пользователя."""
    import hashlib as _hl, hmac as _hmac
    body = await request.json()
    old_pass = body.get("old_password", "")
    new_pass = body.get("new_password", "")
    if not old_pass or not new_pass:
        raise HTTPException(400, "old_password and new_password required")
    if len(new_pass) < 6:
        raise HTTPException(400, "Password must be >= 6 chars")
    user = _get_current_user(request)
    uid = user.get("id", "admin")
    stored = dict(_users.get(uid) or {})
    env_pass = os.environ.get("ARCANE_ADMIN_PASSWORD", "arcane2025")
    stored_hash = stored.get("password_hash", "")
    old_expected = _hl.sha256((old_pass + "arcane_salt").encode()).hexdigest()
    if old_pass != env_pass and (not stored_hash or not _hmac.compare_digest(old_expected, stored_hash)):
        raise HTTPException(401, "Current password incorrect")
    stored["password_hash"] = _hl.sha256((new_pass + "arcane_salt").encode()).hexdigest()
    _users.set(uid, stored)
    _log_audit("password.change", uid, "Password changed", resource_type="auth")
    return {"ok": True}


@compat_router.post("/admin/users/{user_id}/reset-password")
async def admin_reset_password(user_id: str, request: Request):
    """Admin: принудительно сменить пароль пользователя."""
    import hashlib as _hl
    _check_admin_auth(request)
    body = await request.json()
    new_pass = body.get("new_password", "")
    if not new_pass:
        raise HTTPException(400, "new_password required")
    user = _users.get(user_id)
    if not user:
        raise HTTPException(404, "User not found")
    updated = dict(user)
    updated["password_hash"] = _hl.sha256((new_pass + "arcane_salt").encode()).hexdigest()
    _users.set(user_id, updated)
    _log_audit("password.reset", user_id, "Password reset by admin", resource_type="auth")
    return {"ok": True}

@compat_router.get("/auth/me")
async def me(request: Request):
    # P0-2: Always require token for /auth/me regardless of STRICT_AUTH
    user_id = _resolve_token(request)
    if not user_id:
        raise HTTPException(401, "Not authenticated")
    user = _users.get(user_id)
    if not user:
        raise HTTPException(401, "User not found")
    return {"user": {k: v for k, v in user.items() if k != "password_hash"}}

# ══════════════ CHATS ═════════════════════════════════════════════════════════

@compat_router.get("/chats")
async def list_chats(request: Request):
    user = _get_current_user(request)
    chats = [
        {k: v for k, v in c.items() if k != "_messages"}
        for c in _chats.values()
        if c.get("user_id") == user["id"]
    ]
    chats.sort(key=lambda c: c.get("updated_at", ""), reverse=True)
    return {"chats": chats}

@compat_router.post("/chats")
async def create_chat(req: CreateChatRequest, request: Request):
    user = _get_current_user(request)
    chat_id = f"chat_{uuid.uuid4().hex[:12]}"
    chat = {
        "id": chat_id, "title": req.title, "model": req.model,
        "mode": req.mode, "user_id": user["id"], "project_id": req.project_id,
        "created_at": _ts(), "updated_at": _ts(),
        "message_count": 0, "last_message": None, "status": "idle", "total_cost": 0.0,
    }
    _chats[chat_id] = chat
    # messages stored per-message in SQLite (no init needed)
    return {"chat": chat}

@compat_router.get("/chats/{chat_id}")
async def get_chat(chat_id: str):
    if chat_id not in _chats:
        raise HTTPException(404, "Chat not found")
    chat = dict(_chats[chat_id])
    chat["messages"] = _messages.get(chat_id, [])
    return {"chat": chat}

@compat_router.delete("/chats/{chat_id}")
async def delete_chat(chat_id: str):
    _chats.pop(chat_id, None)
    _messages.pop(chat_id, None)
    return {"ok": True}

@compat_router.put("/chats/{chat_id}/rename")
async def rename_chat(chat_id: str, req: RenameChatRequest):
    if chat_id not in _chats:
        raise HTTPException(404, "Chat not found")
    _cd = dict(_chats.get(chat_id) or {})
    _cd["title"] = req.title
    _cd["updated_at"] = _ts()
    _chats.set(chat_id, _cd)
    return {"ok": True}

@compat_router.post("/chats/{chat_id}/stop")
async def stop_chat(chat_id: str):
    if chat_id in _chats:
        _cd = dict(_chats.get(chat_id) or {})
        _cd["status"] = "idle"
        _chats.set(chat_id, _cd)
    return {"ok": True}

@compat_router.get("/chats/{chat_id}/messages")
async def get_chat_messages(chat_id: str, limit: int = 100, offset: int = 0):
    """Get messages for a chat."""
    if chat_id not in _chats:
        raise HTTPException(404, "Chat not found")
    msgs = _messages.get(chat_id, [])
    paginated = msgs[offset:offset + limit]
    return {"messages": paginated, "total": len(msgs), "chat_id": chat_id}

@compat_router.post("/chats/{chat_id}/messages")
async def add_chat_message(chat_id: str, req: SendMessageRequest, request: Request):
    """Add a message to a chat without triggering LLM."""
    if chat_id not in _chats:
        raise HTTPException(404, "Chat not found")
    msg = {
        "id": f"msg_{__import__('uuid').uuid4().hex[:8]}",
        "role": req.role if hasattr(req, 'role') else "user",
        "content": (req.content or req.message or ''),
        "created_at": _ts(),
    }
    _messages.append(chat_id, msg)  # P0-4: direct SQLite append
    _cd = dict(_chats.get(chat_id) or {})
    _cd["message_count"] = len(_messages.get(chat_id, []))
    _cd["updated_at"] = _ts()
    _chats.set(chat_id, _cd)
    return {"message": msg, "ok": True}

@compat_router.get("/chats/{chat_id}/status")
async def chat_status(chat_id: str):
    if chat_id not in _chats:
        raise HTTPException(404, "Chat not found")
    c = _chats[chat_id]
    msgs = _messages.get(chat_id, [])
    return {
        "chat_id": chat_id, "status": c.get("status", "idle"),
        "total_cost": c.get("total_cost", 0.0), "title": c.get("title", ""),
        "last_message": msgs[-1]["content"][:100] if msgs else None,
        "message_count": len(msgs),
    }

@compat_router.post("/chats/{chat_id}/send")
async def send_message(chat_id: str, req: SendMessageRequest, request: Request):
    """Send a message and stream the response as SSE events."""
    if chat_id not in _chats:
        raise HTTPException(404, "Chat not found")
    user_text = req.content or req.message or ''
    user_msg = {"id": f"msg_{uuid.uuid4().hex[:8]}", "role": "user",
                "content": user_text, "created_at": _ts()}
    _messages.append(chat_id, user_msg)
    _cd = dict(_chats.get(chat_id) or {})
    _cd["updated_at"] = _ts()
    _cd["message_count"] = len(_messages[chat_id])
    _cd["last_message"] = user_text[:100]
    _cd["status"] = "running"
    _chats.set(chat_id, _cd)
    model = req.model or _chats[chat_id].get("model", "claude-sonnet-4.6")
    cur_user = _get_current_user(request)

    async def _sse_stream():
        yield f"data: {json.dumps({'type': 'thinking'})}\n\n"
        _fr = None
        try:
            import sys as _sys2
            from pathlib import Path as _Path2
            _root2 = str(_Path2(__file__).resolve().parent.parent)
            if _root2 not in _sys2.path:
                _sys2.path.insert(0, _root2)
            from core.identity_shield import check_and_respond as _car, filter_response as _fr2
            _fr = _fr2
            _shield = _car(message=user_text, user_id='', chat_id=chat_id)
            if _shield.blocked:
                import uuid as _uuid2
                _blocked_msg = {'id': f'msg_{_uuid2.uuid4().hex[:8]}', 'role': 'assistant',
                                'content': _shield.response, 'model': 'Arcane Core',
                                'cost_usd': 0.0, 'created_at': _ts()}
                _messages[chat_id].append(_blocked_msg)
                _chats[chat_id]['last_message'] = _shield.response[:100]
                _chats[chat_id]['message_count'] = len(_messages[chat_id])
                _chats[chat_id]['status'] = 'idle'
                yield f"data: {json.dumps({'type': 'text_complete', 'content': _shield.response})}\n\n"
                yield f"data: {json.dumps({'type': 'done', 'total_cost': _chats[chat_id].get('total_cost', 0.0)})}\n\n"
                return
        except Exception:
            pass
        api_key = os.environ.get("OPENROUTER_API_KEY", "")
        assistant_content = ""
        cost = 0.0
        if api_key:
            try:
                import sys
                from pathlib import Path
                _root = str(Path(__file__).resolve().parent.parent)
                if _root not in sys.path:
                    sys.path.insert(0, _root)
                from shared.llm.llm_client import SimpleLLMClient
                client = SimpleLLMClient(api_key=api_key)
                history = [{"role": m["role"], "content": m["content"]} for m in _messages.get(chat_id, [])]
                resp = await client.chat(model=model, messages=history, max_tokens=4096)
                assistant_content = resp.get("content", "")
                cost = resp.get("cost_usd", 0.0)
                try:
                    if _fr:
                        assistant_content = _fr(assistant_content)
                except Exception:
                    pass
                if hasattr(client, "close"):
                    await client.close()
            except Exception as e:
                assistant_content = f"[Error: {e}]"
        else:
            assistant_content = "[OpenRouter API key not configured. Set OPENROUTER_API_KEY env var or add via Settings → API Keys.]"
        _is_admin = cur_user.get("role") == "super_admin"
        asst_msg = {"id": f"msg_{uuid.uuid4().hex[:8]}", "role": "assistant",
                    "content": assistant_content, "model": model if _is_admin else _mask_model_id(model),
                    "cost_usd": cost, "created_at": _ts()}
        _messages.append(chat_id, asst_msg)
        _cd2 = dict(_chats.get(chat_id) or {})
        _cd2["total_cost"] = _cd2.get("total_cost", 0.0) + cost
        _cd2["last_message"] = assistant_content[:100]
        _cd2["message_count"] = len(_messages[chat_id])
        _cd2["status"] = "idle"
        _chats.set(chat_id, _cd2)
        _audit_logs.insert(0, {
            "id": f"log_{uuid.uuid4().hex[:8]}", "userId": cur_user.get("id"),
            "userName": cur_user.get("name"), "model": model,
            "cost": cost, "status": "done", "timestamp": _ts(),
        })
        await _sse_bus.publish(chat_id, {
            "type": "message", "message": asst_msg,
            "total_cost": _cd2.get("total_cost", 0.0),
        })
        yield f"data: {json.dumps({'type': 'text_complete', 'content': assistant_content, 'cost': cost})}\n\n"
        yield f"data: {json.dumps({'type': 'done', 'total_cost': _cd2.get('total_cost', 0.0)})}\n\n"

    return StreamingResponse(
        _sse_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )

@compat_router.get("/chats/{chat_id}/subscribe")
async def subscribe_chat(
    chat_id: str,
    request: Request,
    token: str = Query("", description="JWT token for SSE auth (EventSource can't send headers)"),
):
    """
    Real-time SSE endpoint.
    Streams agent events (thinking, tool_executing, cost_update, phase_change, etc.)
    to the frontend via Server-Sent Events.

    Events come from two sources:
      1. _sse_bus (compat_all internal — send_message flow)
      2. WebSocket broadcast from api.py (orchestrator task flow)
    """
    _resolve_token(request, token)  # Auth check (MVP: allows fallback to admin)

    # Subscribe to real-time event bus for this chat
    queue = _sse_bus.subscribe(chat_id)

    async def event_generator():
        # Send connected confirmation
        yield f"data: {json.dumps({'type': 'connected', 'chat_id': chat_id})}\n\n"
        try:
            ping_counter = 0
            while True:
                # Check if client disconnected
                if await request.is_disconnected():
                    break

                try:
                    # Wait for event with timeout for keepalive pings
                    event = await asyncio.wait_for(queue.get(), timeout=15.0)
                    yield f"data: {json.dumps(event, default=str)}\n\n"
                except asyncio.TimeoutError:
                    # Keepalive ping every 15s
                    ping_counter += 1
                    yield f"data: {json.dumps({'type': 'ping', 'n': ping_counter})}\n\n"

        except asyncio.CancelledError:
            pass
        finally:
            _sse_bus.unsubscribe(chat_id, queue)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )

@compat_router.post("/chats/{chat_id}/model")
async def update_chat_model(chat_id: str, request: Request):
    body = await request.json()
    if chat_id in _chats:
        _cd = dict(_chats.get(chat_id) or {})
        _cd["model"] = body.get("model", _cd["model"])
        _chats.set(chat_id, _cd)
    return {"ok": True}

# ══════════════ OAUTH ═════════════════════════════════════════════════════════

@compat_router.get("/oauth/callback")
async def oauth_callback(
    request: Request,
    code: str = Query(""),
    state: str = Query(""),
    error: str = Query(""),
):
    """
    OAuth 2.0 callback handler.
    Exchanges authorization code for access token, creates session.

    Configure via environment:
      OAUTH_SERVER_URL  — base URL of OAuth provider (e.g. https://oauth.example.com)
      OAUTH_CLIENT_ID   — OAuth client ID
      OAUTH_CLIENT_SECRET — OAuth client secret

    Flow:
      1. User clicks "Login with OAuth" → redirected to provider
      2. Provider redirects back to /api/oauth/callback?code=...&state=...
      3. We exchange code for token, fetch user profile
      4. Create/update user, create session, redirect to /
    """
    import httpx
    from fastapi.responses import RedirectResponse

    if error:
        return RedirectResponse(url=f"/?oauth_error={error}")

    if not code:
        raise HTTPException(400, "OAuth callback: missing code parameter")

    oauth_url = os.environ.get("OAUTH_SERVER_URL", "")
    client_id = os.environ.get("OAUTH_CLIENT_ID", "")
    client_secret = os.environ.get("OAUTH_CLIENT_SECRET", "")

    if not oauth_url:
        # OAuth not configured — redirect to home with info
        return RedirectResponse(url="/?oauth_error=not_configured")

    base_url = str(request.base_url).rstrip("/")
    redirect_uri = f"{base_url}/api/oauth/callback"

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            # Exchange code for token
            token_resp = await client.post(
                f"{oauth_url}/token",
                data={
                    "grant_type": "authorization_code",
                    "code": code,
                    "redirect_uri": redirect_uri,
                    "client_id": client_id,
                    "client_secret": client_secret,
                },
                headers={"Accept": "application/json"},
            )
            if token_resp.status_code != 200:
                return RedirectResponse(url=f"/?oauth_error=token_exchange_failed")

            token_data = token_resp.json()
            access_token = token_data.get("access_token", "")

            if not access_token:
                return RedirectResponse(url="/?oauth_error=no_access_token")

            # Fetch user profile
            userinfo_resp = await client.get(
                f"{oauth_url}/userinfo",
                headers={"Authorization": f"Bearer {access_token}"},
            )
            if userinfo_resp.status_code != 200:
                return RedirectResponse(url="/?oauth_error=userinfo_failed")

            userinfo = userinfo_resp.json()

    except Exception as e:
        logger_ca.warning(f"OAuth callback error: {e}")
        return RedirectResponse(url=f"/?oauth_error=network_error")

    # Create or update user
    sub = userinfo.get("sub") or userinfo.get("id") or f"oauth_{uuid.uuid4().hex[:8]}"
    email = userinfo.get("email", f"{sub}@oauth")
    name = userinfo.get("name") or userinfo.get("preferred_username") or email.split("@")[0]

    existing = _users.get(sub)
    if existing:
        # Update last login
        _eud = dict(existing)
        _eud["last_login"] = _ts()
        _eud["email"] = email
        _users.set(sub, _eud)
    else:
        user = {
            "id": sub,
            "email": email,
            "name": name,
            "role": "user",
            "is_active": True,
            "status": "active",
            "created_at": _ts(),
            "last_login": _ts(),
            "avatarInitials": name[:2].upper(),
            "avatarColor": "#10B981",
            "auth_provider": "oauth",
        }
        _users.set(sub, user)

    # Create session
    session_token = f"tok_{uuid.uuid4().hex}"
    _sessions.set(session_token, sub)
    _log_audit("oauth.login", sub, f"OAuth login: {email}", resource_type="auth")

    # Redirect to frontend with session token in cookie
    response = RedirectResponse(url="/")
    response.set_cookie(
        "session_token",
        session_token,
        httponly=True,
        samesite="lax",
        max_age=86400 * 30,  # 30 days
    )
    return response


@compat_router.get("/oauth/login")
async def oauth_login_redirect(request: Request, provider: str = "default"):
    """
    Start OAuth flow — redirect user to provider's authorization URL.
    Configure OAUTH_SERVER_URL, OAUTH_CLIENT_ID in environment.
    """
    from fastapi.responses import RedirectResponse

    oauth_url = os.environ.get("OAUTH_SERVER_URL", "")
    client_id = os.environ.get("OAUTH_CLIENT_ID", "")

    if not oauth_url or not client_id:
        raise HTTPException(503, "OAuth not configured. Set OAUTH_SERVER_URL and OAUTH_CLIENT_ID.")

    import secrets
    state = secrets.token_urlsafe(16)
    base_url = str(request.base_url).rstrip("/")
    redirect_uri = f"{base_url}/api/oauth/callback"

    auth_url = (
        f"{oauth_url}/authorize"
        f"?response_type=code"
        f"&client_id={client_id}"
        f"&redirect_uri={redirect_uri}"
        f"&scope=openid+email+profile"
        f"&state={state}"
    )
    return RedirectResponse(url=auth_url)


# ══════════════ SCHEDULE ══════════════════════════════════════════════════════

@compat_router.get("/schedule")
async def list_schedule():
    return {"tasks": list(_schedule_tasks.values())}

@compat_router.post("/schedule")
async def create_schedule(req: CreateScheduleTask):
    tid = f"sched_{uuid.uuid4().hex[:12]}"
    task = {"id": tid, "name": req.name, "cron": req.cron, "task": req.task,
            "model": req.model, "project_id": req.project_id, "enabled": req.enabled,
            "created_at": _ts(), "last_run": None, "next_run": None, "run_count": 0}
    _schedule_tasks[tid] = task
    return {"ok": True, "task": task}

@compat_router.get("/schedule/{task_id}")
async def get_schedule(task_id: str):
    if task_id not in _schedule_tasks:
        raise HTTPException(404, "Task not found")
    return {"task": _schedule_tasks[task_id]}

@compat_router.put("/schedule/{task_id}")
async def update_schedule(task_id: str, req: UpdateScheduleTask):
    if task_id not in _schedule_tasks:
        raise HTTPException(404, "Task not found")
    for field, val in req.model_dump(exclude_none=True).items():
        _schedule_tasks[task_id][field] = val
    return {"ok": True, "task": _schedule_tasks[task_id]}

@compat_router.delete("/schedule/{task_id}")
async def delete_schedule(task_id: str):
    _schedule_tasks.pop(task_id, None)
    return {"ok": True}

@compat_router.post("/schedule/{task_id}/toggle")
async def toggle_schedule(task_id: str):
    if task_id not in _schedule_tasks:
        raise HTTPException(404, "Task not found")
    _schedule_tasks[task_id]["enabled"] = not _schedule_tasks[task_id]["enabled"]
    return {"ok": True, "status": "enabled" if _schedule_tasks[task_id]["enabled"] else "disabled"}

@compat_router.post("/schedule/{task_id}/run")
async def run_schedule_now(task_id: str):
    if task_id not in _schedule_tasks:
        raise HTTPException(404, "Task not found")
    task = dict(_schedule_tasks.get(task_id))
    if _orchestrator and task.get("task"):
        pid = task.get("project_id", "default")
        asyncio.create_task(
            _orchestrator.run(project_id=pid, task=task["task"], mode=task.get("mode", "optimum"))
        )
    task["last_run"] = _ts()
    task["run_count"] = task.get("run_count", 0) + 1
    _schedule_tasks.set(task_id, task)
    _log_audit("schedule.run", resource_id=task_id, details=task.get("task", "")[:100])
    return {"ok": True, "status": "triggered"}
# ══════════════ ADMIN — STATS ═════════════════════════════════════════════════

@compat_router.get("/admin/stats")
async def admin_stats(request: Request):
    _check_admin_auth(request)
    # Base stats from SQLite stores
    all_chats = _chats.all()
    all_users = _users.all()
    
    total_cost = sum(c.get("total_cost", 0) for c in all_chats.values())
    
    # Task stats from orchestrator history_db
    task_stats = {"total": 0, "done": 0, "failed": 0, "total_cost": 0.0, "avg_duration": 0.0}
    if _orchestrator and getattr(_orchestrator, "history_db", None):
        try:
            task_stats = _orchestrator.history_db.get_stats() or task_stats
        except Exception:
            pass
    
    # Also count in-memory running tasks
    running_tasks = 0
    if _orchestrator and hasattr(_orchestrator, "_runs"):
        running_tasks = sum(
            1 for r in _orchestrator._runs.values()
            if getattr(r, "status", None) and r.status.value in ("running", "classifying")
        )
    
    return {
        "total_users": len(all_users),
        "active_users": sum(1 for u in all_users.values() if u.get("is_active")),
        "total_chats": len(all_chats),
        "total_messages": sum(
            len(_messages.get(cid) or []) for cid in list(all_chats.keys())[:100]
        ),
        "total_schedule_tasks": len(_schedule_tasks.all()),
        "total_cost_usd": round(total_cost, 4),
        "tasks_total": task_stats.get("total", 0),
        "tasks_done": task_stats.get("done", 0),
        "tasks_failed": task_stats.get("failed", 0),
        "tasks_running": running_tasks,
        "tasks_cost_usd": round(float(task_stats.get("total_cost") or 0), 4),
        "avg_task_duration_s": round(float(task_stats.get("avg_duration") or 0), 1),
    }

# ══════════════ ADMIN — USERS ═════════════════════════════════════════════════

@compat_router.get("/admin/users")
async def admin_users(request: Request):
    _check_admin_auth(request)
    return {"users": list(_users.values())}

@compat_router.post("/admin/users")
async def admin_create_user(req: CreateUserRequest, request: Request):

    _check_admin_auth(request)
    import hashlib as _hl
    uid = f"user_{uuid.uuid4().hex[:8]}"
    pass_hash = _hl.sha256((req.password + "arcane_salt").encode()).hexdigest() if req.password else ""
    user = {"id": uid, "email": req.email, "name": req.name, "role": req.role,
            "is_active": True, "status": "active", "created_at": _ts(),
            "avatarInitials": req.name[:2].upper(), "avatarColor": "#10B981",
            "password_hash": pass_hash}
    _users.set(uid, user)
    return {"ok": True, "user": {k: v for k, v in user.items() if k != "password_hash"}}

@compat_router.put("/admin/users/{user_id}")
async def admin_update_user(user_id: str, req: UpdateUserRequest, request: Request):

    _check_admin_auth(request)
    if user_id not in _users:
        raise HTTPException(404, "User not found")
    for field, val in req.model_dump(exclude_none=True).items():
        _users[user_id][field] = val
    return {"ok": True}

@compat_router.delete("/admin/users/{user_id}")
async def admin_delete_user(user_id: str, request: Request):

    _check_admin_auth(request)
    name = _users.get(user_id, {}).get("name", user_id)
    _users.pop(user_id, None)
    _log_audit("user.delete", "admin", f"Удалён пользователь: {name}", resource_id=user_id, resource_type="user")
    return {"ok": True}

@compat_router.post("/admin/users/{user_id}/toggle")
async def admin_toggle_user(user_id: str, request: Request):

    _check_admin_auth(request)
    if user_id not in _users:
        raise HTTPException(404, "User not found")
    _usd = dict(_users.get(user_id) or {})
    _usd["is_active"] = not _usd.get("is_active", True)
    _usd["status"] = "active" if _usd["is_active"] else "blocked"
    _users.set(user_id, _usd)
    action_str = "user.unblock" if _users[user_id]["is_active"] else "user.block"
    _log_audit(action_str, "admin", f"Статус изменён: {_users[user_id].get('name', user_id)}", resource_id=user_id, resource_type="user")
    return {"ok": True}

@compat_router.get("/admin/chats")
async def admin_all_chats(request: Request):
    """Return all chats across all users (admin only)."""
    _check_admin_auth(request)
    result = []
    for chat_id, chat in _chats.items():
        msgs = _messages.get(chat_id, [])
        result.append({
            **{k: v for k, v in chat.items() if k != "_messages"},
            "message_count": len(msgs),
            "last_message_preview": msgs[-1]["content"][:100] if msgs else None,
        })
    return {"chats": sorted(result, key=lambda x: x.get("updated_at", ""), reverse=True)}

# ══════════════ ADMIN — GROUPS ════════════════════════════════════════════════

@compat_router.get("/admin/groups")
async def list_groups(request: Request):

    _check_admin_auth(request)
    return {"groups": list(_groups.values())}

@compat_router.post("/admin/groups")
async def create_group(req: CreateGroupRequest, request: Request):

    _check_admin_auth(request)
    gid = f"g_{uuid.uuid4().hex[:8]}"
    group = {"id": gid, "name": req.name, "description": req.description,
             "managerId": req.managerId, "memberIds": [], "budget": None,
             "spent": 0.0, "color": req.color}
    _groups[gid] = group
    _log_audit("group.create", "admin", f"Создана группа: {req.name}", resource_id=gid, resource_type="group")
    return {"ok": True, "group": group}

@compat_router.put("/admin/groups/{group_id}")
async def update_group(group_id: str, req: UpdateGroupRequest, request: Request):

    _check_admin_auth(request)
    if group_id not in _groups:
        raise HTTPException(404, "Group not found")
    for field, val in req.model_dump(exclude_none=True).items():
        _groups[group_id][field] = val
    _log_audit("group.update", "admin", f"Изменена группа: {_groups[group_id].get(chr(39)+chr(110)+chr(97)+chr(109)+chr(101)+chr(39), group_id)}", resource_id=group_id, resource_type="group")
    return {"ok": True}

@compat_router.delete("/admin/groups/{group_id}")
async def delete_group(group_id: str, request: Request):

    _check_admin_auth(request)
    name = _groups.get(group_id, {}).get("name", group_id)
    _groups.pop(group_id, None)
    _log_audit("group.delete", "admin", f"Удалена группа: {name}", resource_id=group_id, resource_type="group")
    return {"ok": True}

@compat_router.post("/admin/groups/{group_id}/members")
async def add_group_member(group_id: str, req: AddMemberRequest, request: Request):

    _check_admin_auth(request)
    if group_id not in _groups:
        raise HTTPException(404, "Group not found")
    if req.user_id not in _groups[group_id]["memberIds"]:
        _groups[group_id]["memberIds"].append(req.user_id)
    return {"ok": True}

@compat_router.delete("/admin/groups/{group_id}/members/{user_id}")
async def remove_group_member(group_id: str, user_id: str, request: Request):

    _check_admin_auth(request)
    if group_id not in _groups:
        raise HTTPException(404, "Group not found")
    members = _groups[group_id]["memberIds"]
    if user_id in members:
        members.remove(user_id)
    return {"ok": True}

# ══════════════ ADMIN — PERMISSIONS ═══════════════════════════════════════════

@compat_router.get("/admin/users/{user_id}/permissions")
async def get_user_permissions(user_id: str, request: Request):

    _check_admin_auth(request)
    return {"permissions": _permissions.get(user_id, {})}

@compat_router.put("/admin/users/{user_id}/permissions")
async def set_user_permissions(user_id: str, req: SetPermissionsRequest, request: Request):

    _check_admin_auth(request)
    if user_id not in _permissions:
        _permissions[user_id] = {}
    for field, val in req.model_dump(exclude_none=True).items():
        _permissions[user_id][field] = val
    _log_audit("permission.update", "admin", f"Права изменены: {_users.get(user_id, {}).get('name', user_id)}", resource_id=user_id, resource_type="permission")
    return {"ok": True}

# ══════════════ ADMIN — BUDGETS ═══════════════════════════════════════════════

@compat_router.get("/admin/budgets/org")
async def get_org_budget():
    _check_admin_auth(request)
    return {"budget": _org_budget}

@compat_router.put("/admin/budgets/org")
async def set_org_budget(request: Request):
    _check_admin_auth(request)
    body = await request.json()
    for k, v in body.items():
        if k in ("amount", "period", "alertThreshold", "actionOnExceed"):
            _org_budget[k] = v
    _log_audit("budget.update", "admin", f"Бюджет организации: {_org_budget.get('amount')} {_org_budget.get('period')}", resource_type="budget")
    return {"ok": True}

@compat_router.get("/admin/budgets/users/{user_id}")
async def get_user_budget(user_id: str, request: Request):

    _check_admin_auth(request)
    return {"budget": _user_budgets.get(user_id), "spent": 0.0}

@compat_router.put("/admin/budgets/users/{user_id}")
async def set_user_budget(user_id: str, req: BudgetLimitRequest, request: Request):

    _check_admin_auth(request)
    if req.budget is None:
        _user_budgets.pop(user_id, None)
    else:
        _user_budgets[user_id] = req.budget
    _log_audit("budget.update", "admin", f"Бюджет пользователя: {user_id}", resource_id=user_id, resource_type="budget")
    return {"ok": True}

@compat_router.get("/admin/budgets/groups/{group_id}")
async def get_group_budget(group_id: str, request: Request):

    _check_admin_auth(request)
    return {"budget": _group_budgets.get(group_id), "spent": _groups.get(group_id, {}).get("spent", 0.0)}

@compat_router.put("/admin/budgets/groups/{group_id}")
async def set_group_budget(group_id: str, req: BudgetLimitRequest, request: Request):

    _check_admin_auth(request)
    if req.budget is None:
        _group_budgets.pop(group_id, None)
    else:
        _group_budgets[group_id] = req.budget
    if group_id in _groups:
        _grd = dict(_groups.get(group_id) or {})
        _grd["budget"] = req.budget
        _groups.set(group_id, _grd)
    return {"ok": True}

# ══════════════ ADMIN — AUDIT LOGS ════════════════════════════════════════════

@compat_router.get("/admin/logs")
async def list_audit_logs(limit: int = 50, offset: int = 0,
                          userId: Optional[str] = None, projectId: Optional[str] = None,
                          action: Optional[str] = None, request: Request = None):
    _check_admin_auth(request)
    # AuditLogTable.get_recent returns (entries, total)
    entries, total = _audit_logs.get_recent(
        limit=limit, offset=offset,
        user_id=userId, project_id=projectId,
        action_prefix=action,
    )
    return {"logs": entries, "total": total}

@compat_router.post("/admin/logs")
async def add_audit_log(request: Request):
    _check_admin_auth(request)
    body = await request.json()
    entry = {"id": f"log_{uuid.uuid4().hex[:8]}", "timestamp": _ts(), **body}
    _audit_logs.insert(0, entry)  # AuditLogTable.insert(0, entry) → append
    return {"ok": True, "id": entry["id"]}

# ══════════════ ADMIN — SPENDING ══════════════════════════════════════════════

@compat_router.get("/admin/spending")
async def spending_overview(request: Request):
    """Spending overview — uses budget_controller if available, falls back to audit logs."""
    _check_admin_auth(request)

    # Try to get real data from budget_controller
    if _orchestrator and hasattr(_orchestrator, "budget") and _orchestrator.budget:
        try:
            from shared.model_mask import mask_model_id as _mmid
            dash = _orchestrator.budget.dashboard()
            return {
                "total": dash.get("total_usd", 0.0),
                "month": dash.get("month", ""),
                "by_user": [],  # budget_controller tracks by project, not user
                "by_model": [
                    {"modelId": _mmid(k), "name": _mmid(k), "spent": v, "calls": 0}
                    for k, v in dash.get("by_model", {}).items()
                ],
                "by_project": [
                    {"projectId": k, "name": k, "spent": v}
                    for k, v in dash.get("by_project", {}).items()
                ],
                "by_category": dash.get("by_category", {}),
                "daily": [],
            }
        except Exception:
            pass

    # Fallback: aggregate from audit logs
    user_spend: dict[str, float] = {}
    model_spend: dict[str, float] = {}
    project_spend: dict[str, float] = {}
    daily_spend: dict[str, dict] = {}
    total = 0.0

    for log in _audit_logs:
        cost = log.get("cost", 0.0)
        total += cost
        uid = log.get("userId", "unknown")
        user_spend[uid] = user_spend.get(uid, 0.0) + cost
        mid = log.get("model", "unknown")
        model_spend[mid] = model_spend.get(mid, 0.0) + cost
        pid = log.get("projectId", "unknown")
        project_spend[pid] = project_spend.get(pid, 0.0) + cost
        ts = log.get("timestamp", "")[:10]
        if ts:
            if ts not in daily_spend:
                daily_spend[ts] = {"cost": 0.0, "tasks": 0}
            daily_spend[ts]["cost"] += cost
            daily_spend[ts]["tasks"] += 1

    return {
        "total": total,
        "by_user": [{"userId": k, "name": k, "spent": v} for k, v in user_spend.items()],
        "by_model": [{"modelId": k, "name": k, "spent": v, "calls": 0} for k, v in model_spend.items()],
        "by_project": [{"projectId": k, "name": k, "spent": v} for k, v in project_spend.items()],
        "daily": [{"date": k, **v} for k, v in sorted(daily_spend.items())],
    }

# ══════════════ ADMIN — SETTINGS (API KEYS) ══════════════════════════════════

@compat_router.get("/admin/settings/keys")
async def get_api_keys(request: Request):

    _check_admin_auth(request)
    return {
        "openrouter": {"set": bool(_get_key("openrouter")), "masked": _mask_key(_get_key("openrouter"))},
        "manus": {"set": bool(_get_key("manus")), "masked": _mask_key(_get_key("manus"))},
        "tavily": {"set": bool(_get_key("tavily")), "masked": _mask_key(_get_key("tavily"))},
    }

@compat_router.post("/admin/settings/keys")
async def set_api_key(req: SetKeyRequest, request: Request):

    _check_admin_auth(request)
    env_map = {"openrouter": "OPENROUTER_API_KEY", "manus": "MANUS_API_KEY", "tavily": "TAVILY_API_KEY"}
    if req.provider not in env_map:
        raise HTTPException(400, f"Unknown provider: {req.provider}")
    _key_overrides[req.provider] = req.key
    os.environ[env_map[req.provider]] = req.key
    return {"ok": True}

@compat_router.post("/admin/settings/keys/test")
async def test_api_key(req: TestKeyRequest, request: Request):

    _check_admin_auth(request)
    key = _get_key(req.provider)
    if not key:
        return {"ok": False, "valid": False, "error": "Key not set"}
    try:
        if req.provider == "openrouter":
            import httpx
            async with httpx.AsyncClient() as client:
                resp = await client.get("https://openrouter.ai/api/v1/models",
                                        headers={"Authorization": f"Bearer {key}"}, timeout=10)
                valid = resp.status_code == 200
                return {"ok": True, "valid": valid, "error": None if valid else f"HTTP {resp.status_code}"}
        elif req.provider == "tavily":
            import httpx
            async with httpx.AsyncClient() as client:
                resp = await client.post("https://api.tavily.com/search",
                                         json={"api_key": key, "query": "test", "max_results": 1}, timeout=10)
                valid = resp.status_code == 200
                return {"ok": True, "valid": valid, "error": None if valid else f"HTTP {resp.status_code}"}
        else:
            return {"ok": True, "valid": len(key) > 10, "error": None if len(key) > 10 else "Key too short"}
    except Exception as e:
        return {"ok": False, "valid": False, "error": str(e)}

# ══════════════ PROJECT CRUD extensions ═══════════════════════════════════════


@compat_router.get("/projects/{project_id}/tasks")
async def list_project_tasks(project_id: str, request: Request):
    """List runs/tasks for a project from the orchestrator's in-memory store."""
    _get_current_user(request)  # auth check
    tasks = []
    if _orchestrator is not None:
        # Get all runs for this project from orchestrator
        runs = [r for r in _orchestrator._runs.values() if r.project_id == project_id]
        for r in sorted(runs, key=lambda x: x.started_at, reverse=True):
            tasks.append({
                "id": r.run_id,
                "run_id": r.run_id,
                "name": r.task[:80] if r.task else "Задача",
                "status": r.status.value if hasattr(r.status, "value") else str(r.status),
                "cost": r.actual_cost,
                "duration": f"{r.duration_seconds:.0f}s" if r.duration_seconds else "—",
                "model": (list(r.team.values())[0] if _get_current_user(request).get("role") == "super_admin" else _mask_model_id(list(r.team.values())[0])) if r.team else "—",
                "createdAt": r.started_at,
                "output": r.output,
                "artifacts": r.artifacts,
            })
    return {"tasks": tasks}

@compat_router.put("/projects/{project_id}")
async def update_project(project_id: str, request: Request):
    body = await request.json()
    try:
        from api.api import project_manager
        if project_manager:
            state = project_manager.get_state(project_id)
            if state and isinstance(state, dict):
                # FIX audit #6: use `in` for dict, not hasattr
                for k, v in body.items():
                    if k in state:
                        state[k] = v
                return {"ok": True}
    except Exception:
        pass
    return {"ok": True}

@compat_router.delete("/projects/{project_id}")
async def delete_project(project_id: str):
    try:
        from api.api import project_manager
        if project_manager:
            state = project_manager.get_state(project_id)
            if state and isinstance(state, dict):
                state["status"] = "archived"
    except Exception:
        pass
    return {"ok": True}

# ══════════════ MISSING COMPAT ROUTES ═══════════════════════════════════════

@compat_router.get("/playbooks")
async def list_playbooks(request: Request):
    """List playbooks (golden paths / templates)."""
    return {"playbooks": [
        {"id": "web-app", "name": "Web Application", "description": "Full-stack web app development"},
        {"id": "data-analysis", "name": "Data Analysis", "description": "Data processing and visualization"},
        {"id": "api-integration", "name": "API Integration", "description": "Third-party API integration"},
        {"id": "automation", "name": "Automation Script", "description": "Task automation workflow"},
    ]}

@compat_router.get("/notifications")
async def list_notifications(request: Request):
    """List user notifications."""
    return {"notifications": [], "unread_count": 0}

@compat_router.post("/notifications/read")
async def mark_notifications_read(request: Request):
    """Mark all notifications as read."""
    return {"ok": True}

@compat_router.get("/user/settings")
async def get_user_settings(request: Request):
    """Get current user settings."""
    user = _get_current_user(request)
    return {
        "user_id": user.get("id"),
        "theme": "dark",
        "language": "ru",
        "notifications_enabled": True,
        "default_model": "claude-sonnet-4.6",
        "default_mode": "optimum",
    }

@compat_router.put("/user/settings")
async def update_user_settings(request: Request):
    """Update current user settings."""
    return {"ok": True}

@compat_router.get("/servers")
async def list_servers(request: Request):
    """List configured SSH servers."""
    import os, json
    servers_file = "/root/arcane2/config/servers.json"
    if os.path.exists(servers_file):
        try:
            with open(servers_file) as f:
                data = json.load(f)
            return {"servers": data.get("servers", [])}
        except Exception:
            pass
    return {"servers": []}

@compat_router.get("/spending")
async def get_user_spending(request: Request):
    """Get spending data for current user."""
    import os, json, glob
    total = 0.0
    by_model = {}
    log_dir = "/root/arcane2/logs/budget"
    if os.path.exists(log_dir):
        for f in glob.glob(f"{log_dir}/*.json")[:50]:
            try:
                with open(f) as fh:
                    entry = json.load(fh)
                cost = entry.get("cost_usd", 0)
                model = entry.get("model", "unknown")
                total += cost
                by_model[model] = by_model.get(model, 0) + cost
            except Exception:
                pass
    return {
        "total_usd": round(total, 6),
        "by_model": by_model,
        "month": __import__('datetime').datetime.utcnow().strftime("%Y-%m"),
    }

@compat_router.get("/tasks")
async def list_user_tasks(request: Request, limit: int = 50):
    """List tasks/runs for current user (proxies to orchestrator state)."""
    import os, json, glob
    tasks = []
    # Read from task history directory
    history_dir = "/root/arcane2/data/task_history"
    if os.path.exists(history_dir):
        for f in sorted(glob.glob(f"{history_dir}/*.json"), reverse=True)[:limit]:
            try:
                with open(f) as fh:
                    tasks.append(json.load(fh))
            except Exception:
                pass
    return {"tasks": tasks[:limit], "total": len(tasks)}

@compat_router.post("/run")
async def submit_run(request: Request):
    """Submit a task run (proxies to /api/projects/{id}/tasks)."""
    import json
    try:
        body = await request.json()
    except Exception:
        body = {}
    task_text = body.get("task", "")
    project_id = body.get("project_id", "default")
    model = body.get("model", "claude-sonnet-4.6")
    mode = body.get("mode", "optimum")
    if not task_text:
        raise HTTPException(400, "task is required")
    # Forward to the main api.py submit_task endpoint
    import httpx
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"http://localhost:8900/api/projects/{project_id}/tasks",
                json={"task": task_text, "model": model, "mode": mode},
                timeout=10.0
            )
            return resp.json()
    except Exception as e:
        raise HTTPException(500, f"Failed to submit task: {e}")


# ══════════════ MEMORY API ════════════════════════════════════════════════════

@compat_router.get("/memory")
async def list_memories(request: Request, chat_id: str = None):
    """List memory entries for current user from memory_v9."""
    user = _get_current_user(request)
    memories = []
    try:
        if _orchestrator and hasattr(_orchestrator, "agent_loop_factory"):
            # Try to get from memory engine via agent context
            pass
        # Return semantic memory stats if available
        try:
            from shared.memory_v9.semantic import get_semantic
            sem = get_semantic()
            # Return empty list - full implementation would query Qdrant
        except Exception:
            pass
    except Exception:
        pass
    return {"memories": memories, "total": len(memories)}


@compat_router.post("/memory/search")
async def search_memory(request: Request):
    """Semantic search in memory."""
    body = await request.json()
    query = body.get("query", "")
    chat_id = body.get("chat_id")
    results = []
    try:
        from shared.memory_v9.semantic import get_semantic
        sem = get_semantic()
        raw = sem.search(query, top_k=5)
        results = [{"id": str(i), "content": r, "score": 0.9} for i, r in enumerate(raw)]
    except Exception:
        pass
    return {"memories": results}


@compat_router.post("/memory")
async def add_memory(request: Request):
    """Add a memory entry."""
    body = await request.json()
    content = body.get("content", "")
    mem_id = f"mem_{uuid.uuid4().hex[:8]}"
    try:
        from shared.memory_v9.semantic import get_semantic
        get_semantic().store(content, memory_type="user")
    except Exception:
        pass
    return {
        "ok": True,
        "memory": {"id": mem_id, "content": content, "source": body.get("source", "manual")},
    }


@compat_router.delete("/memory/{memory_id}")
async def delete_memory(memory_id: str, request: Request):
    """Delete a memory entry."""
    return {"ok": True}


@compat_router.get("/memory/stats")
async def memory_stats(request: Request):
    """Memory system stats."""
    stats = {
        "total": 0, "sessions": 0, "size_kb": 0,
        "initialized": False, "vector_dim": 0, "collection": "",
    }
    try:
        from shared.memory_v9.semantic import get_semantic
        sem = get_semantic()
        stats["initialized"] = sem._client is not None
        stats["collection"] = "arcane_memory"
        stats["vector_dim"] = 1536
    except Exception:
        pass
    return stats


@compat_router.get("/admin/memory")
async def admin_list_memory(request: Request, user_id: str = None):
    """Admin: list all memory entries."""
    _check_admin_auth(request)
    return {"memories": []}


@compat_router.delete("/admin/memory/{memory_id}")
async def admin_delete_memory(memory_id: str, request: Request):
    _check_admin_auth(request)
    return {"ok": True}


@compat_router.post("/admin/memory/clear-sessions")
async def admin_clear_sessions(request: Request):
    _check_admin_auth(request)
    cleared = 0
    try:
        from shared.memory_v9.session import SessionMemory
        SessionMemory.clear_all()
        cleared = 1
    except Exception:
        pass
    return {"ok": True, "cleared": cleared}


# ══════════════ ANALYTICS ═════════════════════════════════════════════════════

@compat_router.get("/analytics")
async def get_analytics(request: Request, period: str = "month"):
    """
    Usage analytics — aggregated from budget_controller + task history.
    period: "day" | "week" | "month" | "year"
    """
    result = {
        "period": period,
        "tasks": {"total": 0, "done": 0, "failed": 0, "running": 0},
        "cost": {"total_usd": 0.0, "by_model": {}, "by_day": []},
        "chats": {"total": len(_chats.all()), "messages": 0},
        "models_used": [],
    }

    # Task stats from orchestrator
    if _orchestrator and getattr(_orchestrator, "history_db", None):
        try:
            db_stats = _orchestrator.history_db.get_stats() or {}
            result["tasks"]["total"] = int(db_stats.get("total", 0))
            result["tasks"]["done"] = int(db_stats.get("done", 0))
            result["tasks"]["failed"] = int(db_stats.get("failed", 0))
            result["cost"]["total_usd"] = round(float(db_stats.get("total_cost") or 0), 4)
        except Exception:
            pass

    # Budget data from budget_controller
    if _orchestrator and hasattr(_orchestrator, "budget") and _orchestrator.budget:
        try:
            from shared.model_mask import mask_model_id as _mmid
            dash = _orchestrator.budget.dashboard()
            result["cost"]["total_usd"] = round(dash.get("total_usd", 0.0), 4)
            result["cost"]["by_model"] = {
                _mmid(k): round(v, 4)
                for k, v in dash.get("by_model", {}).items()
            }
            result["models_used"] = list(result["cost"]["by_model"].keys())
        except Exception:
            pass

    return result


@compat_router.get("/admin/schedule")
async def admin_schedule(request: Request):
    """Admin view of all scheduled tasks."""
    _check_admin_auth(request)
    return {"tasks": list(_schedule_tasks.all().values())}


# ══════════════ TEMPLATES ═════════════════════════════════════════════════════

# Default task templates
_DEFAULT_TEMPLATES = [
    {"id": "t1", "name": "Лендинг", "description": "Создать одностраничный сайт",
     "task": "Создай красивый лендинг для компании. Используй современный дизайн, адаптивную верстку.",
     "category": "web_design", "icon": "🌐"},
    {"id": "t2", "name": "REST API", "description": "Создать REST API на FastAPI",
     "task": "Создай REST API на Python/FastAPI с CRUD операциями, документацией и тестами.",
     "category": "coding", "icon": "⚙️"},
    {"id": "t3", "name": "Код-ревью", "description": "Проверить код на ошибки",
     "task": "Проведи код-ревью. Найди баги, проблемы безопасности, предложи улучшения.",
     "category": "code_review", "icon": "🔍"},
    {"id": "t4", "name": "SEO статья", "description": "Написать SEO-оптимизированную статью",
     "task": "Напиши SEO-оптимизированную статью 2000+ слов. Добавь заголовки H1-H3, ключевые слова.",
     "category": "content", "icon": "✍️"},
    {"id": "t5", "name": "Диагностика сервера", "description": "Проверить состояние сервера",
     "task": "Проведи диагностику сервера: проверь CPU, RAM, диск, nginx, запущенные сервисы.",
     "category": "devops", "icon": "🖥️"},
    {"id": "t6", "name": "React компонент", "description": "Создать React компонент",
     "task": "Создай React компонент с TypeScript. Включи props, states, адаптивные стили.",
     "category": "coding", "icon": "⚛️"},
]

@compat_router.get("/templates")
async def list_templates(request: Request):
    return {"templates": _DEFAULT_TEMPLATES}


@compat_router.get("/templates/{template_id}")
async def get_template(template_id: str, request: Request):
    tpl = next((t for t in _DEFAULT_TEMPLATES if t["id"] == template_id), None)
    if not tpl:
        raise HTTPException(404, "Template not found")
    return {"template": tpl}


# ══════════════ CONNECTORS ════════════════════════════════════════════════════

# Available integrations
_CONNECTORS = [
    {"id": "openrouter", "name": "OpenRouter", "type": "llm",
     "description": "LLM routing через OpenRouter API",
     "icon": "🤖", "connected": bool(os.environ.get("OPENROUTER_API_KEY")),
     "status": "connected" if os.environ.get("OPENROUTER_API_KEY") else "disconnected"},
    {"id": "tavily", "name": "Tavily Search", "type": "search",
     "description": "Веб-поиск через Tavily API",
     "icon": "🔍", "connected": bool(os.environ.get("TAVILY_API_KEY")),
     "status": "connected" if os.environ.get("TAVILY_API_KEY") else "disconnected"},
    {"id": "github", "name": "GitHub", "type": "vcs",
     "description": "Git репозитории и CI/CD",
     "icon": "🐙", "connected": False, "status": "not_configured"},
    {"id": "telegram", "name": "Telegram Bot", "type": "messaging",
     "description": "Уведомления через Telegram",
     "icon": "✈️", "connected": bool(os.environ.get("TELEGRAM_BOT_TOKEN")),
     "status": "connected" if os.environ.get("TELEGRAM_BOT_TOKEN") else "disconnected"},
    {"id": "manus", "name": "Manus AI", "type": "agent",
     "description": "Браузерный агент + SSH",
     "icon": "🦾", "connected": bool(os.environ.get("MANUS_API_KEY")),
     "status": "connected" if os.environ.get("MANUS_API_KEY") else "disconnected"},
]


@compat_router.get("/connectors")
async def list_connectors(request: Request):
    """List available integrations and their connection status."""
    # Refresh dynamic statuses
    conns = []
    for c in _CONNECTORS:
        cc = dict(c)
        if c["id"] == "openrouter":
            cc["connected"] = bool(os.environ.get("OPENROUTER_API_KEY") or _key_overrides.get("openrouter"))
        elif c["id"] == "tavily":
            cc["connected"] = bool(os.environ.get("TAVILY_API_KEY") or _key_overrides.get("tavily"))
        cc["status"] = "connected" if cc["connected"] else "disconnected"
        conns.append(cc)
    return {"connectors": conns}


@compat_router.post("/connectors/{connector_id}/connect")
async def connect_connector(connector_id: str, request: Request):
    """Connect an integration (store API key)."""
    body = await request.json()
    api_key = body.get("api_key") or body.get("token", "")
    env_map = {"openrouter": "OPENROUTER_API_KEY", "tavily": "TAVILY_API_KEY",
               "telegram": "TELEGRAM_BOT_TOKEN", "manus": "MANUS_API_KEY"}
    if connector_id in env_map and api_key:
        _key_overrides[connector_id] = api_key
        os.environ[env_map[connector_id]] = api_key
        return {"ok": True, "status": "connected"}
    return {"ok": False, "error": "Unknown connector or missing api_key"}


@compat_router.post("/connectors/{connector_id}/disconnect")
async def disconnect_connector(connector_id: str, request: Request):
    """Disconnect an integration."""
    _key_overrides.delete(connector_id)
    return {"ok": True, "status": "disconnected"}


# ══════════════ FILES API ═════════════════════════════════════════════════════

@compat_router.get("/files")
async def list_files(request: Request, chat_id: str = None):
    """List uploaded files (proxies to project workspace files)."""
    import os, mimetypes, time as _time
    workspace = os.environ.get("ARCANE_WORKSPACE", "/root/workspace")
    files = []
    if chat_id:
        # Try to find project files for this chat
        pass
    # List recent files from all projects
    projects_dir = os.path.join(workspace, "projects")
    if os.path.exists(projects_dir):
        for proj in sorted(os.listdir(projects_dir))[:10]:
            src_dir = os.path.join(projects_dir, proj, "src")
            if os.path.isdir(src_dir):
                for root, dirs, fnames in os.walk(src_dir):
                    dirs[:] = [d for d in dirs if not d.startswith(".")]
                    for fname in fnames[:5]:
                        fpath = os.path.join(root, fname)
                        rel = os.path.relpath(fpath, src_dir)
                        mime, _ = mimetypes.guess_type(fpath)
                        files.append({
                            "id": f"f_{proj}_{rel.replace('/', '_')}",
                            "name": fname,
                            "path": rel,
                            "project_id": proj,
                            "size": os.path.getsize(fpath),
                            "mime_type": mime or "application/octet-stream",
                            "created_at": os.path.getmtime(fpath),
                        })
    files.sort(key=lambda x: x["created_at"], reverse=True)
    return {"files": files[:100]}


@compat_router.post("/upload")
async def upload_file(request: Request):
    """Upload a file to the workspace."""
    from fastapi import UploadFile, File
    import shutil
    workspace = os.environ.get("ARCANE_WORKSPACE", "/root/workspace")
    upload_dir = os.path.join(workspace, "uploads")
    os.makedirs(upload_dir, exist_ok=True)

    content_type = request.headers.get("content-type", "")
    if "multipart" not in content_type:
        raise HTTPException(400, "Expected multipart/form-data")

    form = await request.form()
    file_field = form.get("file")
    if not file_field:
        raise HTTPException(400, "No file field in form")

    filename = getattr(file_field, "filename", "upload.bin") or "upload.bin"
    file_id = f"f_{uuid.uuid4().hex[:8]}"
    dest_path = os.path.join(upload_dir, f"{file_id}_{filename}")

    try:
        content = await file_field.read()
        with open(dest_path, "wb") as f:
            f.write(content)
        return {
            "ok": True,
            "file": {
                "id": file_id,
                "name": filename,
                "path": dest_path,
                "size": len(content),
                "url": f"/api/files/{file_id}/download",
            },
        }
    except Exception as e:
        raise HTTPException(500, f"Upload failed: {e}")


@compat_router.get("/files/{file_id}/download")
async def download_file(file_id: str, request: Request):
    """Download a file by ID."""
    from fastapi.responses import FileResponse
    workspace = os.environ.get("ARCANE_WORKSPACE", "/root/workspace")
    upload_dir = os.path.join(workspace, "uploads")
    # Find file by ID prefix
    import glob
    matches = glob.glob(os.path.join(upload_dir, f"{file_id}_*"))
    if matches:
        return FileResponse(matches[0])
    raise HTTPException(404, "File not found")


@compat_router.get("/files/{file_id}/preview")
async def preview_file(file_id: str, request: Request):
    """Preview file content (text files only)."""
    workspace = os.environ.get("ARCANE_WORKSPACE", "/root/workspace")
    import glob, mimetypes
    upload_dir = os.path.join(workspace, "uploads")
    matches = glob.glob(os.path.join(upload_dir, f"{file_id}_*"))
    if not matches:
        raise HTTPException(404, "File not found")
    fpath = matches[0]
    mime, _ = mimetypes.guess_type(fpath)
    mime = mime or "application/octet-stream"
    if mime.startswith("text/") or mime in ("application/json", "application/xml"):
        with open(fpath, encoding="utf-8", errors="replace") as f:
            content = f.read(50_000)  # 50KB preview max
        return {"content": content, "mime_type": mime}
    return {"content": None, "mime_type": mime, "message": "Binary file — download to view"}


# ══════════════ SETTINGS (user) ═══════════════════════════════════════════════

@compat_router.get("/settings")
async def get_user_settings(request: Request):
    """Get current user settings."""
    user = _get_current_user(request)
    uid = user.get("id", "admin")
    stored = _permissions.get(f"settings:{uid}", {})
    return {
        "settings": {
            "language": stored.get("language", "ru"),
            "theme": stored.get("theme", "dark"),
            "notifications_enabled": stored.get("notifications_enabled", True),
            "default_mode": stored.get("default_mode", "optimum"),
            "timezone": stored.get("timezone", "Europe/Moscow"),
            "model_preferences": stored.get("model_preferences", {}),
        }
    }


@compat_router.put("/settings")
async def update_user_settings(request: Request):
    """Update current user settings."""
    body = await request.json()
    user = _get_current_user(request)
    uid = user.get("id", "admin")
    key = f"settings:{uid}"
    current = dict(_permissions.get(key) or {})
    current.update(body)
    _permissions.set(key, current)
    return {"ok": True, "settings": current}


# ══════════════ AGENTS (custom) ═══════════════════════════════════════════════

_custom_agents_store = None  # lazy init from persistence


def _get_agents_store():
    global _custom_agents_store
    if _custom_agents_store is None:
        from core.persistence import get_store
        _custom_agents_store = get_store().key_overrides  # reuse KV for simplicity
    return _custom_agents_store


@compat_router.get("/agents/custom")
async def list_custom_agents(request: Request):
    """List custom agent configurations."""
    # Store in a separate namespace
    all_kv = _store.key_overrides.all()
    agents = {k.replace("agent:", ""): v for k, v in all_kv.items() if k.startswith("agent:")}
    return {"agents": list(agents.values())}


@compat_router.post("/agents/custom")
async def create_custom_agent(request: Request):
    """Create a custom agent."""
    body = await request.json()
    agent_id = f"agent_{uuid.uuid4().hex[:8]}"
    agent = {
        "id": agent_id,
        "name": body.get("name", "Custom Agent"),
        "description": body.get("description", ""),
        "model": body.get("model", "gpt-5.4-nano"),
        "system_prompt": body.get("system_prompt", ""),
        "mode": body.get("mode", "optimum"),
        "created_at": _ts(),
    }
    _store.key_overrides.set(f"agent:{agent_id}", agent)
    return {"ok": True, "agent": agent}


@compat_router.delete("/agents/custom/{agent_id}")
async def delete_custom_agent(agent_id: str, request: Request):
    """Delete a custom agent."""
    _store.key_overrides.delete(f"agent:{agent_id}")
    return {"ok": True}


@compat_router.get("/preview/{project_id}/")
@compat_router.get("/preview/{project_id}/{path:path}")
async def preview_project(project_id: str, path: str = "index.html", request: Request = None):
    """Serve project preview files."""
    import os
    from fastapi.responses import FileResponse, HTMLResponse
    workspace = os.environ.get("ARCANE_WORKSPACE", "/root/workspace")
    file_path = os.path.join(workspace, "projects", project_id, "src", path)
    if os.path.isdir(file_path):
        file_path = os.path.join(file_path, "index.html")
    if os.path.exists(file_path):
        return FileResponse(file_path)
    # Return simple directory listing if index.html missing
    src_dir = os.path.join(workspace, "projects", project_id, "src")
    if os.path.isdir(src_dir):
        files = os.listdir(src_dir)
        links = "".join(f'<li><a href="/preview/{project_id}/{f}">{f}</a></li>' for f in sorted(files))
        return HTMLResponse(f"<h2>Project: {project_id}</h2><ul>{links}</ul>")
    raise HTTPException(404, f"Project {project_id} not found")

