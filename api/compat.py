"""
api/compat.py — Frontend API compatibility layer for Arcane 2
Provides the ~20 endpoints the frontend expects that are not in api.py.

Mounted at /api by main app (api.py).
All data stored in-memory (MVP) — Phase 5 will add PostgreSQL.
"""
from __future__ import annotations

import json
import os
import time
import uuid
import asyncio
from typing import Optional, List, Any
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

# ─── In-memory stores (MVP) ───────────────────────────────────────────────────
_users: dict[str, dict] = {}          # user_id → user dict
_sessions: dict[str, str] = {}        # token → user_id
_chats: dict[str, dict] = {}          # chat_id → chat dict
_messages: dict[str, list] = {}       # chat_id → [message, ...]
_schedule_tasks: dict[str, dict] = {} # task_id → task dict

# Default admin user
_DEFAULT_ADMIN = {
    "id": "admin",
    "email": "admin@arcane.local",
    "name": "Admin",
    "role": "admin",
    "is_active": True,
    "created_at": "2026-01-01T00:00:00Z",
}
_users["admin"] = _DEFAULT_ADMIN
_sessions["arcane-admin-token"] = "admin"

# ─── Pydantic models ──────────────────────────────────────────────────────────
class LoginRequest(BaseModel):
    login_id: str
    password: str

class CreateChatRequest(BaseModel):
    title: str = "New Chat"
    model: str = "claude-sonnet-4.6"
    mode: str = "balanced"

class RenameChatRequest(BaseModel):
    title: str

class SendMessageRequest(BaseModel):
    content: Optional[str] = None
    message: Optional[str] = None  # alias for content (frontend compatibility)
    model: Optional[str] = None
    mode: Optional[str] = None
    variant: Optional[str] = None
    file_content: Optional[str] = None
    options: Optional[dict] = None
    
    @property
    def text(self) -> str:
        return self.content or self.message or ''
    
    def model_post_init(self, __context):
        # Normalize: if only message is provided, copy to content
        if not self.content and self.message:
            object.__setattr__(self, 'content', self.message)

class CreateScheduleTask(BaseModel):
    name: str
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

# ─── Helper ───────────────────────────────────────────────────────────────────
def _get_current_user(request: Request) -> dict:
    """Extract user from Authorization header or return None."""
    auth = request.headers.get("Authorization", "")
    token = auth.replace("Bearer ", "").strip()
    if not token:
        # Also check cookie
        token = request.cookies.get("session_token", "")
    user_id = _sessions.get(token)
    if not user_id or user_id not in _users:
        return _DEFAULT_ADMIN  # MVP: always return admin
    return _users[user_id]

def _ts() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

# ─── App factory ──────────────────────────────────────────────────────────────
def create_compat_app() -> FastAPI:
    app = FastAPI(title="Arcane 2 Compat API", docs_url=None, redoc_url=None)

    # ── Auth ──────────────────────────────────────────────────────────────────
    @app.post("/auth/login")
    async def login(req: LoginRequest):
        # MVP: accept any credentials, return admin token
        token = f"tok_{uuid.uuid4().hex}"
        _sessions[token] = "admin"
        return {
            "ok": True,
            "token": token,
            "user": _DEFAULT_ADMIN,
        }

    @app.post("/auth/logout")
    async def logout(request: Request):
        auth = request.headers.get("Authorization", "")
        token = auth.replace("Bearer ", "").strip()
        _sessions.pop(token, None)
        return {"ok": True}

    @app.get("/auth/me")
    async def me(request: Request):
        user = _get_current_user(request)
        return {"user": user}

    # ── Chats ─────────────────────────────────────────────────────────────────
    @app.get("/chats")
    async def list_chats(request: Request):
        user = _get_current_user(request)
        chats = [
            {k: v for k, v in c.items() if k != "_messages"}
            for c in _chats.values()
            if c.get("user_id") == user["id"]
        ]
        chats.sort(key=lambda c: c.get("updated_at", ""), reverse=True)
        return {"chats": chats}

    @app.post("/chats")
    async def create_chat(req: CreateChatRequest, request: Request):
        user = _get_current_user(request)
        chat_id = f"chat_{uuid.uuid4().hex[:12]}"
        chat = {
            "id": chat_id,
            "title": req.title,
            "model": req.model,
            "mode": req.mode,
            "user_id": user["id"],
            "created_at": _ts(),
            "updated_at": _ts(),
            "message_count": 0,
            "last_message": None,
            "status": "idle",
            "total_cost": 0.0,
        }
        _chats[chat_id] = chat
        _messages[chat_id] = []
        return {"chat": chat}

    @app.get("/chats/{chat_id}")
    async def get_chat(chat_id: str, request: Request):
        if chat_id not in _chats:
            raise HTTPException(404, "Chat not found")
        chat = dict(_chats[chat_id])
        chat["messages"] = _messages.get(chat_id, [])
        return {"chat": chat}

    @app.delete("/chats/{chat_id}")
    async def delete_chat(chat_id: str):
        _chats.pop(chat_id, None)
        _messages.pop(chat_id, None)
        return {"ok": True}

    @app.put("/chats/{chat_id}/rename")
    async def rename_chat(chat_id: str, req: RenameChatRequest):
        if chat_id not in _chats:
            raise HTTPException(404, "Chat not found")
        _chats[chat_id]["title"] = req.title
        _chats[chat_id]["updated_at"] = _ts()
        return {"ok": True}

    @app.post("/chats/{chat_id}/stop")
    async def stop_chat(chat_id: str):
        if chat_id in _chats:
            _chats[chat_id]["status"] = "idle"
        return {"ok": True}

    @app.get("/chats/{chat_id}/status")
    async def chat_status(chat_id: str):
        if chat_id not in _chats:
            raise HTTPException(404, "Chat not found")
        c = _chats[chat_id]
        msgs = _messages.get(chat_id, [])
        last = msgs[-1]["content"][:100] if msgs else None
        return {
            "chat_id": chat_id,
            "status": c.get("status", "idle"),
            "total_cost": c.get("total_cost", 0.0),
            "title": c.get("title", ""),
            "last_message": last,
            "message_count": len(msgs),
        }

    @app.post("/chats/{chat_id}/send")
    async def send_message(chat_id: str, req: SendMessageRequest, request: Request):
        if chat_id not in _chats:
            raise HTTPException(404, "Chat not found")

        # Store user message
        user_msg = {
            "id": f"msg_{uuid.uuid4().hex[:8]}",
            "role": "user",
            "content": (req.content or req.message or ''),
            "created_at": _ts(),
        }
        _messages.setdefault(chat_id, []).append(user_msg)
        _chats[chat_id]["updated_at"] = _ts()
        _chats[chat_id]["message_count"] = len(_messages[chat_id])
        _chats[chat_id]["last_message"] = (req.content or req.message or '')[:100]

        # Call LLM via orchestrator
        model = req.model or _chats[chat_id].get("model", "claude-sonnet-4.6")
        api_key = os.environ.get("OPENROUTER_API_KEY", "")
        
        assistant_content = ""
        cost = 0.0
        
        if api_key:
            try:
                from shared.llm.llm_client import SimpleLLMClient
                client = SimpleLLMClient(api_key=api_key)
                
                # Build message history
                history = [
                    {"role": m["role"], "content": m["content"]}
                    for m in _messages.get(chat_id, [])
                ]
                
                resp = await client.chat(
                    model=model,
                    messages=history,
                    max_tokens=4096,
                )
                assistant_content = resp.get("content", "")
                cost = resp.get("cost_usd", 0.0)
                
                if hasattr(client, "close"):
                    await client.close()
            except Exception as e:
                assistant_content = f"[Error: {e}]"
        else:
            assistant_content = "[OpenRouter API key not configured]"

        # Store assistant message
        asst_msg = {
            "id": f"msg_{uuid.uuid4().hex[:8]}",
            "role": "assistant",
            "content": assistant_content,
            "model": model,
            "cost_usd": cost,
            "created_at": _ts(),
        }
        _messages[chat_id].append(asst_msg)
        _chats[chat_id]["total_cost"] = _chats[chat_id].get("total_cost", 0.0) + cost
        _chats[chat_id]["last_message"] = assistant_content[:100]
        _chats[chat_id]["message_count"] = len(_messages[chat_id])

        return {
            "ok": True,
            "message": asst_msg,
            "total_cost": _chats[chat_id]["total_cost"],
        }

    @app.get("/chats/{chat_id}/subscribe")
    async def subscribe_chat(chat_id: str):
        """SSE endpoint for real-time chat updates."""
        async def event_generator():
            yield f"data: {json.dumps({'type': 'connected', 'chat_id': chat_id})}\n\n"
            # Keep connection alive
            for _ in range(30):
                await asyncio.sleep(1)
                yield f"data: {json.dumps({'type': 'ping'})}\n\n"

        return StreamingResponse(
            event_generator(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
            },
        )

    @app.post("/chats/{chat_id}/model")
    async def update_chat_model(chat_id: str, request: Request):
        body = await request.json()
        if chat_id in _chats:
            _chats[chat_id]["model"] = body.get("model", _chats[chat_id]["model"])
        return {"ok": True}

    # ── Schedule ──────────────────────────────────────────────────────────────
    @app.get("/schedule")
    async def list_schedule():
        tasks = list(_schedule_tasks.values())
        return {"tasks": tasks}

    @app.post("/schedule")
    async def create_schedule(req: CreateScheduleTask):
        task_id = f"sched_{uuid.uuid4().hex[:12]}"
        task = {
            "id": task_id,
            "name": req.name,
            "cron": req.cron,
            "task": req.task,
            "model": req.model,
            "project_id": req.project_id,
            "enabled": req.enabled,
            "created_at": _ts(),
            "last_run": None,
            "next_run": None,
            "run_count": 0,
        }
        _schedule_tasks[task_id] = task
        return {"ok": True, "task": task}

    @app.get("/schedule/{task_id}")
    async def get_schedule(task_id: str):
        if task_id not in _schedule_tasks:
            raise HTTPException(404, "Task not found")
        return {"task": _schedule_tasks[task_id]}

    @app.put("/schedule/{task_id}")
    async def update_schedule(task_id: str, req: UpdateScheduleTask):
        if task_id not in _schedule_tasks:
            raise HTTPException(404, "Task not found")
        task = _schedule_tasks[task_id]
        for field, val in req.model_dump(exclude_none=True).items():
            task[field] = val
        return {"ok": True, "task": task}

    @app.delete("/schedule/{task_id}")
    async def delete_schedule(task_id: str):
        _schedule_tasks.pop(task_id, None)
        return {"ok": True}

    @app.post("/schedule/{task_id}/toggle")
    async def toggle_schedule(task_id: str):
        if task_id not in _schedule_tasks:
            raise HTTPException(404, "Task not found")
        _schedule_tasks[task_id]["enabled"] = not _schedule_tasks[task_id]["enabled"]
        return {"ok": True, "status": "enabled" if _schedule_tasks[task_id]["enabled"] else "disabled"}

    @app.post("/schedule/{task_id}/run")
    async def run_schedule_now(task_id: str):
        if task_id not in _schedule_tasks:
            raise HTTPException(404, "Task not found")
        task = _schedule_tasks[task_id]
        task["last_run"] = _ts()
        task["run_count"] = task.get("run_count", 0) + 1
        return {"ok": True, "status": "triggered", "task_id": task_id}

    # ── Admin ─────────────────────────────────────────────────────────────────
    @app.get("/admin/stats")
    async def admin_stats():
        return {
            "total_users": len(_users),
            "total_chats": len(_chats),
            "total_messages": sum(len(v) for v in _messages.values()),
            "total_schedule_tasks": len(_schedule_tasks),
            "active_users": sum(1 for u in _users.values() if u.get("is_active")),
            "total_cost_usd": sum(c.get("total_cost", 0) for c in _chats.values()),
        }

    @app.get("/admin/users")
    async def admin_users():
        return {"users": list(_users.values())}

    @app.post("/admin/users")
    async def admin_create_user(req: CreateUserRequest):
        user_id = f"user_{uuid.uuid4().hex[:8]}"
        user = {
            "id": user_id,
            "email": req.email,
            "name": req.name,
            "role": req.role,
            "is_active": True,
            "created_at": _ts(),
        }
        _users[user_id] = user
        return {"ok": True, "user": user}

    @app.put("/admin/users/{user_id}")
    async def admin_update_user(user_id: str, req: UpdateUserRequest):
        if user_id not in _users:
            raise HTTPException(404, "User not found")
        for field, val in req.model_dump(exclude_none=True).items():
            _users[user_id][field] = val
        return {"ok": True}

    @app.delete("/admin/users/{user_id}")
    async def admin_delete_user(user_id: str):
        _users.pop(user_id, None)
        return {"ok": True}

    @app.post("/admin/users/{user_id}/toggle")
    async def admin_toggle_user(user_id: str):
        if user_id not in _users:
            raise HTTPException(404, "User not found")
        _users[user_id]["is_active"] = not _users[user_id].get("is_active", True)
        return {"ok": True}

    @app.get("/admin/chats")
    async def admin_all_chats():
        chats = [
            {k: v for k, v in c.items() if k != "_messages"}
            for c in _chats.values()
        ]
        return {"chats": chats}

    # ── OAuth callback ────────────────────────────────────────────────────────
    @app.get("/oauth/callback")
    async def oauth_callback(code: Optional[str] = None, state: Optional[str] = None):
        # MVP: redirect to frontend
        return Response(
            content='<html><script>window.location="/"</script></html>',
            media_type="text/html"
        )

    return app
