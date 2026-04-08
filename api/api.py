"""
ARCANE 2 — API Server
======================
FastAPI HTTP + WebSocket server. The interface to Arcane 2.

Endpoints:
  POST /api/projects                  — Create project
  GET  /api/projects                  — List projects
  GET  /api/projects/{id}             — Get project state
  
  POST /api/projects/{id}/tasks       — Submit task (main entry point)
  GET  /api/projects/{id}/tasks       — List tasks/runs
  GET  /api/runs/{run_id}             — Get run status
  POST /api/runs/{run_id}/cancel      — Cancel run
  POST /api/runs/{run_id}/approve     — Approve recommendation
  
  GET  /api/budget                    — Global budget overview
  GET  /api/budget/{project_id}       — Project budget
  
  POST /api/consolidation             — Multi-LLM consolidation
  POST /api/dog-racing                — Start a dog race
  GET  /api/leaderboard               — Model leaderboard
  
  GET  /api/models                    — Available models + prices
  GET  /api/health                    — Health check
  
  WS   /ws/{project_id}              — Real-time updates

Spec refs: §14 (api.py), §7 (orchestrator), §8 (budget)
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from contextlib import asynccontextmanager
from typing import Any, Optional

logger = logging.getLogger("arcane2.api")

# ═══════════════════════════════════════════════════════════════════════════════
# FastAPI app
# ═══════════════════════════════════════════════════════════════════════════════

try:
    from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect, Query, Body, Request
    from fastapi.middleware.cors import CORSMiddleware
    from pydantic import BaseModel, Field
except ImportError:
    raise ImportError("FastAPI not installed. Run: pip install fastapi uvicorn")


# ─── Request/Response models ─────────────────────────────────────────────────

class CreateProjectRequest(BaseModel):
    name: str
    description: str = ""
    client: str = ""
    mode: str = "optimum"   # auto/manual/top/optimum/lite/free
    budget_limit: float = 5.0

class SubmitTaskRequest(BaseModel):
    task: str
    mode: Optional[str] = None          # Override project mode
    budget_limit: Optional[float] = None # Override project budget
    auto_approve: bool = True            # Skip approval step
    consolidation: bool = False          # Enable multi-LLM
    consolidation_models: list[str] = Field(default_factory=list)

class ConsolidationRequest(BaseModel):
    task: str
    models: list[str] = Field(default_factory=lambda: [
        "claude-sonnet-4.6", "gpt-5.4", "deepseek-v3.2"
    ])
    consolidator: str = "gemini-2.5-flash"
    project_id: Optional[str] = None

class DogRaceRequest(BaseModel):
    task: str
    models: list[str]       # 2-5 model IDs
    category: str = "general"  # design/backend/review/text/devops
    project_id: Optional[str] = None

class ApproveRequest(BaseModel):
    approved: bool = True
    team_overrides: dict[str, str] = Field(default_factory=dict)  # role → model_id


# ─── Global state ────────────────────────────────────────────────────────────

# These get initialized in lifespan
orchestrator = None
project_manager = None
budget_controller = None
ws_connections: dict[str, list[WebSocket]] = {}  # project_id → [websockets]


# ─── Lifespan ────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize all Arcane 2 subsystems on startup."""
    global orchestrator, project_manager, budget_controller

    # ── Configure logging so all arcane2.* loggers reach journalctl ──
    import logging as _log
    _root = _log.getLogger()  # root logger
    if not _root.handlers:
        _sh = _log.StreamHandler()
        _sh.setFormatter(_log.Formatter("%(asctime)s %(name)s %(levelname)s %(message)s"))
        _root.addHandler(_sh)
    _root.setLevel(_log.INFO)
    # Make arcane2.orchestrator propagate to root so journalctl sees it
    for _ln in ("arcane2.orchestrator", "arcane2.agent_loop",
                "arcane2.tool_executor", "arcane.orchestrator"):
        _lg = _log.getLogger(_ln)
        _lg.propagate = True
        _lg.setLevel(_log.INFO)

    logger.info("Starting Arcane 2...")
    
    # Add arcane2 paths (relative to this file, not hardcoded)
    import sys
    from pathlib import Path
    _arcane_root = str(Path(__file__).resolve().parent.parent)
    for suffix in ['', 'core', 'shared/llm', 'shared', 'shared/models', 'workers']:
        p = str(Path(_arcane_root) / suffix) if suffix else _arcane_root
        if p not in sys.path:
            sys.path.insert(0, p)
    
    # ── LLM Client ──
    llm_client = None
    try:
        from llm_client import SimpleLLMClient
        llm_client = SimpleLLMClient()
        logger.info("LLM Client: OK")
    except Exception as e:
        logger.warning(f"LLM Client failed: {e}")
    
    # ── Intent Classifier — REMOVED in ARCANE 3.0 ──
    # Director handles classification via keyword heuristics + prompt.
    # classify_fn is no longer needed.
    classify_fn = None  # kept for backward compat with Orchestrator signature
    
    # ── Preset Manager ──
    pm = None
    try:
        from preset_manager import PresetManager
        pm = PresetManager.from_dict({"strategy": "balance"})
        logger.info(f"Preset Manager: OK (mode={pm.mode.value})")
    except Exception as e:
        logger.warning(f"Preset Manager failed: {e}")
    
    # ── Budget Controller ──
    bc = None
    try:
        from budget_controller import BudgetController
        try:
            from core.task_history_db import TaskHistoryDB as _TaskHistoryDB
        except ImportError:
            try:
                from task_history_db import TaskHistoryDB as _TaskHistoryDB
            except ImportError:
                _TaskHistoryDB = None
        workspace = os.environ.get("ARCANE_WORKSPACE", "/root/workspace")
        bc = BudgetController(workspace_root=workspace)
        budget_controller = bc
        logger.info("Budget Controller: OK")
    except Exception as e:
        logger.warning(f"Budget Controller failed: {e}")
    
    # ── Project Manager ──
    pm_proj = None
    try:
        from project_manager import ProjectManager
        workspace = os.environ.get("ARCANE_WORKSPACE", "/root/workspace")
        pm_proj = ProjectManager(workspace_root=os.path.join(workspace, "projects"))
        project_manager = pm_proj
        logger.info("Project Manager: OK")
    except Exception as e:
        logger.warning(f"Project Manager failed: {e}")
    
    # ── Security ──
    security = None
    try:
        from security import SecurityContext
        security = SecurityContext
        logger.info("Security: OK")
    except Exception as e:
        logger.warning(f"Security failed: {e}")
    
    # ── Orchestrator ──
    try:
        from orchestrator import Orchestrator
        orchestrator = Orchestrator(
            llm_client=llm_client,
            intent_classifier=classify_fn,
            preset_manager=pm,
            budget_controller=bc,
            project_manager=pm_proj,
            security=security,
            config={"auto_approve": True},
        )
        logger.info("Orchestrator: OK (all modules wired)")
    except Exception as e:
        logger.warning(f"Orchestrator full init failed: {e}. Trying minimal.")
        try:
            from orchestrator import Orchestrator
            orchestrator = Orchestrator(
                llm_client=llm_client,
                config={"auto_approve": True},
            )
            logger.info("Orchestrator: OK (minimal, LLM only)")
        except Exception as e2:
            logger.error(f"Orchestrator completely failed: {e2}")
    
    # Share orchestrator with compat layer for GET /projects/{id}/tasks
    try:
        from compat_all import set_orchestrator as _set_orch
        if orchestrator:
            _set_orch(orchestrator)
            logger.info("compat_all: orchestrator linked")
    except Exception as _e:
        logger.warning(f"compat_all set_orchestrator failed: {_e}")
    logger.info("Arcane 2 API ready.")

    # P1-3: Schedule background loop — checks every 60s

    async def _schedule_catchup():
        """Run overdue scheduled tasks on startup (Package 4)."""
        await asyncio.sleep(5)
        try:
            from api.compat_all import _schedule_tasks
            import time as _tc
            for task_id in list(_schedule_tasks.keys()):
                task = _schedule_tasks.get(task_id)
                if not task or not task.get("enabled"):
                    continue
                last_ts = task.get("last_run_ts", 0)
                interval = task.get("interval_sec", 3600)
                if _tc.time() - last_ts >= interval and orchestrator:
                    asyncio.create_task(orchestrator.run(
                        project_id=task.get("project_id", "default"),
                        task=task.get("task", ""),
                        mode=task.get("mode", "optimum"),
                    ))
                    logger.info(f"Schedule catch-up: ran overdue task {task_id}")
        except Exception as _e:
            logger.debug(f"Schedule catch-up: {_e}")
    asyncio.create_task(_schedule_catchup())
    logger.info("Schedule catch-up task started")
    async def _schedule_loop():
        """Check scheduled tasks every 60 seconds."""
        while True:
            await asyncio.sleep(60)
            try:
                from api.compat_all import _schedule_tasks
                import time as _time
                for task_id in list(_schedule_tasks.keys()):
                    task = _schedule_tasks.get(task_id)
                    if not task or not task.get("enabled"):
                        continue
                    last_ts = task.get("last_run_ts", 0)
                    interval = task.get("interval_sec", 3600)
                    if _time.time() - last_ts >= interval and orchestrator:
                        pid = task.get("project_id", "default")
                        asyncio.create_task(
                            orchestrator.run(
                                project_id=pid,
                                task=task.get("task", ""),
                                mode=task.get("mode", "optimum"),
                            )
                        )
                        updated = dict(task)
                        updated["last_run"] = _time.strftime("%Y-%m-%dT%H:%M:%SZ")
                        updated["last_run_ts"] = _time.time()
                        updated["run_count"] = updated.get("run_count", 0) + 1
                        _schedule_tasks.set(task_id, updated)
            except Exception as _e:
                logger.debug(f"Schedule loop: {_e}")
    asyncio.create_task(_schedule_loop())
    logger.info("Schedule background loop started")


    async def _cleanup_sessions():
        """Remove expired sessions every hour."""
        import time as _t_cleanup
        while True:
            await asyncio.sleep(3600)
            try:
                from api.compat_all import _sessions
                for token in list(_sessions.keys()):
                    s = _sessions.get(token)
                    if isinstance(s, dict) and s.get("expires_at", float("inf")) < _t_cleanup.time():
                        _sessions.delete(token)
            except Exception as _ce:
                logger.debug(f"Session cleanup: {_ce}")
    asyncio.create_task(_cleanup_sessions())
    logger.info("Session cleanup task started")
    yield
    logger.info("Arcane 2 shutting down.")


# ─── App ──────────────────────────────────────────────────────────────────────
# Add parent dir to path so shared/ is importable
import sys as _sys, os as _os
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
try:
    from shared.model_mask import mask_model_id
except ImportError:
    def mask_model_id(model_id: str) -> str:
        return model_id  # fallback: no masking


app = FastAPI(
    title="API",
    version="2.0.0",
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv("CORS_ORIGINS", "https://arcaneai.ru").split(","),
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["Authorization", "Content-Type"],
)

# Identity Middleware — masks server headers
from starlette.middleware.base import BaseHTTPMiddleware

class IdentityMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        response = await call_next(request)
        response.headers["server"] = "ARCANE/2.0"
        for h in ["x-powered-by", "x-framework", "x-runtime"]:
            if h in response.headers:
                del response.headers[h]
        return response

app.add_middleware(IdentityMiddleware)
# ── Compat router (frontend API layer) ────────────────────────────────────────
import sys as _sys, os as _os
_api_dir = _os.path.dirname(_os.path.abspath(__file__))
if _api_dir not in _sys.path:
    _sys.path.insert(0, _api_dir)
from compat_all import compat_router

# ─── Pipeline supported types (must be before compat_router include) ──────────
@app.get("/api/pipeline/supported")
async def pipeline_supported_types():
    """List task types that support multi-agent pipeline execution."""
    try:
        from core.pipeline import PIPELINES
        types = list(PIPELINES.keys())
    except Exception:
        types = ["web_design", "coding", "automation"]
    return {
        "types": types,
        "description": "These task types use specialized models for planning, building, QA and fixing.",
    }

app.include_router(compat_router, prefix="/api")



# ═══════════════════════════════════════════════════════════════════════════════
# HEALTH
# ═══════════════════════════════════════════════════════════════════════════════



def _check_admin_auth(request: Request) -> None:
    """Simple admin auth check - validates X-Admin-Token or Authorization header."""
    import os
    admin_token = os.environ.get("ARCANE_ADMIN_TOKEN", "")
    if not admin_token:
        return  # No token configured = open access (dev mode)
    auth = request.headers.get("X-Admin-Token") or request.headers.get("Authorization", "").replace("Bearer ", "")
    if auth != admin_token:
        from fastapi import HTTPException
        raise HTTPException(status_code=401, detail="Admin authentication required")

def _budget_remaining_safe(project_id: str | None = None) -> float | None:
    """Safe budget remaining helper - returns None if unlimited or error."""
    if not budget_controller:
        return None
    try:
        if project_id:
            snap = budget_controller.status_project(project_id)
        else:
            snap = budget_controller.status_global()
        if hasattr(snap, "limit_usd") and snap.limit_usd:
            return round(snap.limit_usd - snap.spent_usd, 4)
        return None
    except Exception:
        return None

# ── Rate Limiting (simple in-memory, per-IP + per-project) ───────────────────
import collections
import threading as _threading

class _RateLimiter:
    """
    Simple sliding window rate limiter.
    Default: 10 requests per minute per key.
    """
    def __init__(self, max_calls: int = 10, window_sec: float = 60.0):
        self._max = max_calls
        self._window = window_sec
        self._calls: dict[str, collections.deque] = {}
        self._lock = _threading.Lock()

    def is_allowed(self, key: str) -> tuple[bool, int]:
        """Returns (allowed, retry_after_seconds)."""
        now = time.time()
        with self._lock:
            dq = self._calls.setdefault(key, collections.deque())
            # Remove expired
            while dq and now - dq[0] > self._window:
                dq.popleft()
            if len(dq) >= self._max:
                oldest = dq[0]
                retry_after = int(self._window - (now - oldest)) + 1
                return False, retry_after
            dq.append(now)
            return True, 0

    def cleanup(self):
        """Remove stale keys (call periodically)."""
        now = time.time()
        with self._lock:
            stale = [k for k, dq in self._calls.items()
                     if not dq or now - dq[-1] > self._window * 2]
            for k in stale:
                del self._calls[k]

_task_rate_limiter = _RateLimiter(
    max_calls=int(os.environ.get("ARCANE_TASK_RATE_LIMIT", "10")),
    window_sec=60.0,
)


@app.get("/api/health")
async def health():
    return {"status": "ok", "version": "4.0.0"}

# ── Shield stats for admin panel ──────────────────────────────────────────────
@app.get("/api/admin/shield-stats")
async def shield_stats(request: Request):
    _check_admin_auth(request)
    from core.identity_shield import get_probe_stats
    return get_probe_stats()


# ═══════════════════════════════════════════════════════════════════════════════
# MODELS
# ═══════════════════════════════════════════════════════════════════════════════


@app.get("/api/admin/tasks")
async def admin_all_tasks(request: Request, limit: int = 500):
    _check_admin_auth(request)
    """Return all tasks across all projects (in-memory + persistent SQLite history)."""
    seen_ids: set = set()
    all_tasks: list = []
    workspace = os.environ.get("ARCANE_WORKSPACE", "/root/workspace")

    # 1. In-memory runs (includes currently running tasks)
    if orchestrator and hasattr(orchestrator, "_runs"):
        for run in orchestrator._runs.values():
            rd = run.to_dict() if hasattr(run, "to_dict") else vars(run)
            run_id = rd.get("run_id", "")
            seen_ids.add(run_id)
            proj_name = rd.get("project_id", "")
            try:
                state_path = os.path.join(workspace, "projects", proj_name, ".arcane", "state.json")
                if os.path.exists(state_path):
                    with open(state_path) as _f:
                        st = json.load(_f)
                        proj_name = st.get("name", proj_name)
            except Exception:
                pass
            rd["project_name"] = proj_name
            all_tasks.append(rd)

    # 2. Persistent history from SQLite (older runs not in memory)
    if orchestrator and getattr(orchestrator, "history_db", None):
        for rd in orchestrator.history_db.get_all(limit=limit):
            run_id = rd.get("run_id", "")
            if run_id not in seen_ids:
                seen_ids.add(run_id)
                all_tasks.append(rd)

    # Sort by started_at desc
    all_tasks.sort(key=lambda x: x.get("started_at", x.get("createdAt", 0)), reverse=True)
    return {"tasks": all_tasks[:limit], "total": len(all_tasks)}


@app.get("/api/admin/tasks/stats")
async def admin_tasks_stats(request: Request):
    """Aggregate stats for admin dashboard."""
    _check_admin_auth(request)
    if orchestrator and getattr(orchestrator, "history_db", None):
        return orchestrator.history_db.get_stats()
    return {"total": 0, "done": 0, "failed": 0, "total_cost": 0.0, "avg_duration": 0.0}


@app.get("/api/models")
async def list_models():
    """List all available LLM and image models with prices."""
    try:
        from shared.llm.model_registry import MODELS, IMAGE_MODELS, MANUS
        
        llm = [
            {
                "id": m.id,
                "name": m.display_name,
                "input_price": m.input_price,
                "output_price": m.output_price,
                "max_context": m.max_context,
                "tool_calling": m.tool_calling.value,
                "categories": [c.value for c in m.categories],
                "is_free": m.is_free,
                "swe_bench": m.swe_bench,
            }
            for m in sorted(MODELS.values(), key=lambda x: x.input_price + x.output_price)
        ]
        
        images = [
            {
                "id": m.id,
                "name": m.display_name,
                "price_per_image": m.price_per_image,
                "best_for": m.best_for,
                "is_free": m.is_free,
            }
            for m in sorted(IMAGE_MODELS.values(), key=lambda x: x.price_per_image)
        ]
        
        return {
            "llm_models": llm,
            "llm": llm,
            "models": llm,
            "image_models": images,
            "image": images,
            "manus": {
                "monthly_cost": MANUS.monthly_cost,
                "monthly_credits": MANUS.monthly_credits,
                "credit_price": MANUS.credit_price,
            },
            "total_llm": len(llm),
            "total_image": len(images),
            "total_free": sum(1 for m in llm if m["is_free"]),
        }
    except ImportError:
        raise HTTPException(500, "Model registry not available")


# ═══════════════════════════════════════════════════════════════════════════════
# PROJECTS
# ═══════════════════════════════════════════════════════════════════════════════

@app.post("/api/projects")
async def create_project(req: CreateProjectRequest):
    """Create a new project via ProjectManager (CRIT-4: proper initialization)."""
    from core.project_manager import ProjectManager
    pm = ProjectManager()
    from core.project_manager import ProjectMode as _PM
    _mode_str = (req.mode or "optimum").lower()
    # ProjectMode is str enum - values are the strings themselves
    try:
        _mode = _PM(_mode_str)
    except ValueError:
        _mode = _PM("optimum")
    create_result = pm.create(
        name=req.name,
        goal=req.description or "",
        client=req.client or "",
        mode=_mode,
    )
    # pm.create returns dict (project state) - extract project_id from it
    if isinstance(create_result, dict):
        project_id = create_result.get("project_id") or create_result.get("id") or create_result.get("pid")
        state = create_result
    else:
        project_id = str(create_result)
        state = pm.get_state(project_id)
    if req.budget_limit:
        try:
            pm.update_settings(project_id, {"budget_limit_usd": req.budget_limit})
            # P0-3: Sync limit to BudgetController so it's enforced at runtime
            if budget_controller:
                try:
                    budget_controller.set_limits(
                        project_id=project_id,
                        per_project_month=req.budget_limit
                    )
                except Exception as be:
                    logger.debug(f"Budget sync skipped: {be}")
        except Exception:
            pass
    workspace = os.environ.get("ARCANE_WORKSPACE", "/root/workspace")
    project_dir = os.path.join(workspace, "projects", project_id)
    return {"project": state, "path": project_dir}


@app.get("/api/projects")
async def list_projects():
    """List all projects."""
    workspace = os.environ.get("ARCANE_WORKSPACE", "/root/workspace")
    projects_dir = os.path.join(workspace, "projects")
    
    if not os.path.exists(projects_dir):
        return {"projects": []}
    
    projects = []
    for name in sorted(os.listdir(projects_dir)):
        state_path = os.path.join(projects_dir, name, ".arcane", "state.json")
        if os.path.exists(state_path):
            with open(state_path) as f:
                projects.append(json.load(f))
        else:
            projects.append({"id": name, "name": name, "status": "unknown"})
    
    return {"projects": projects, "total": len(projects)}


@app.get("/api/projects/{project_id}")
async def get_project(project_id: str):
    """Get project state."""
    workspace = os.environ.get("ARCANE_WORKSPACE", "/root/workspace")
    state_path = os.path.join(workspace, "projects", project_id, ".arcane", "state.json")
    
    if not os.path.exists(state_path):
        raise HTTPException(404, f"Project '{project_id}' not found")
    
    with open(state_path) as f:
        state = json.load(f)
    
    return {"project": state}


# ═══════════════════════════════════════════════════════════════════════════════
# TASKS
# ═══════════════════════════════════════════════════════════════════════════════

@app.get("/api/projects/{project_id}/tasks")
async def list_project_tasks(project_id: str):
    """List all tasks/runs for a project."""
    workspace = os.environ.get("ARCANE_WORKSPACE", "/root/workspace")
    runs_dir = os.path.join(workspace, "projects", project_id, ".arcane", "runs")
    
    tasks = []
    if os.path.exists(runs_dir):
        for fname in sorted(os.listdir(runs_dir)):
            fpath = os.path.join(runs_dir, fname)
            if fname.endswith(".json") and os.path.isfile(fpath):
                try:
                    with open(fpath) as f:
                        tasks.append(json.load(f))
                except Exception:
                    pass
    
    # Also check orchestrator in-memory runs
    if orchestrator and hasattr(orchestrator, 'get_project_runs'):
        mem_runs = orchestrator.get_project_runs(project_id)
        mem_ids = {t.get("run_id", t.get("id")) for t in tasks}
        for r in mem_runs:
            rd = r.to_dict() if hasattr(r, 'to_dict') else r
            if rd.get("run_id") not in mem_ids:
                tasks.append(rd)
    
    return {"tasks": tasks}

@app.post("/api/projects/{project_id}/tasks")
async def submit_task(project_id: str, req: SubmitTaskRequest, request: Request):
    """Submit a task to the orchestrator. Main entry point.
    Rate limited: 10 tasks/min per IP (configurable via ARCANE_TASK_RATE_LIMIT).
    """
    if not orchestrator:
        raise HTTPException(503, "Orchestrator not initialized")

    # Rate limiting: per IP + per project
    client_ip = request.client.host if request.client else "unknown"
    rl_key = f"{client_ip}:{project_id}"
    allowed, retry_after = _task_rate_limiter.is_allowed(rl_key)
    if not allowed:
        raise HTTPException(
            status_code=429,
            detail=f"Rate limit exceeded. Try again in {retry_after}s.",
            headers={"Retry-After": str(retry_after)},
        )

    # Input validation
    if not req.task or not req.task.strip():
        raise HTTPException(400, "Task description cannot be empty")
    if len(req.task) > 50_000:
        raise HTTPException(400, f"Task too long: {len(req.task)} chars (max 50000)")

    # Run orchestrator (async)
    result = await orchestrator.run(
        project_id=project_id,
        task=req.task,
        mode=req.mode or "auto",
        budget_limit=req.budget_limit,
        auto_approve=req.auto_approve,
        on_status_change=_broadcast_status,
    )
    
    from shared.model_mask import mask_run_result
    return {"run": mask_run_result(result.to_dict())}


@app.get("/api/runs/{run_id}")
async def get_run(run_id: str):
    """Get status of a running/completed task."""
    if not orchestrator:
        raise HTTPException(503, "Orchestrator not initialized")
    
    run = orchestrator.get_run(run_id)
    if not run:
        raise HTTPException(404, f"Run '{run_id}' not found")
    
    from shared.model_mask import mask_run_result
    return {"run": mask_run_result(run.to_dict())}


@app.post("/api/runs/{run_id}/cancel")
async def cancel_run(run_id: str):
    """Cancel a running task."""
    if not orchestrator:
        raise HTTPException(503, "Orchestrator not initialized")
    
    success = orchestrator.cancel_run(run_id)
    if not success:
        raise HTTPException(400, f"Cannot cancel run '{run_id}'")
    
    return {"cancelled": True, "run_id": run_id}



# ═══════════════════════════════════════════════════════════════════════════════
# PROJECT FILES
# ═══════════════════════════════════════════════════════════════════════════════
@app.get("/api/projects/{project_id}/files")
async def list_project_files(project_id: str):
    """List all files in the project workspace (src/ directory). FIX-12: async I/O."""
    import os, mimetypes, asyncio
    workspace = os.environ.get("ARCANE_WORKSPACE", "/root/workspace")
    src_dir = os.path.join(workspace, "projects", project_id, "src")

    def _scan() -> list:
        if not os.path.isdir(src_dir):
            return []
        files = []
        for root, dirs, filenames in os.walk(src_dir):
            dirs[:] = [d for d in dirs if not d.startswith('.')]
            for fname in filenames:
                if fname.startswith('.'):
                    continue
                fpath = os.path.join(root, fname)
                rel_path = os.path.relpath(fpath, src_dir)
                size = os.path.getsize(fpath)
                mime, _ = mimetypes.guess_type(fpath)
                files.append({
                    "name": fname,
                    "path": rel_path,
                    "size": size,
                    "mime": mime or "application/octet-stream",
                    "modified": os.path.getmtime(fpath),
                })
        files.sort(key=lambda x: x["modified"], reverse=True)
        return files

    files = await asyncio.to_thread(_scan)
    return {"files": files, "project_id": project_id}

@app.get("/api/projects/{project_id}/files/archive")
async def download_project_archive(project_id: str):
    """Download all project files as a ZIP archive."""
    import os, io, zipfile, mimetypes
    from fastapi.responses import StreamingResponse

    workspace = os.environ.get("ARCANE_WORKSPACE", "/root/workspace")
    src_dir = os.path.join(workspace, "projects", project_id, "src")

    if not os.path.isdir(src_dir):
        raise HTTPException(404, "No files found for this project")

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for root, dirs, filenames in os.walk(src_dir):
            dirs[:] = [d for d in dirs if not d.startswith(".")]
            for fname in filenames:
                if fname.startswith("."):
                    continue
                fpath = os.path.join(root, fname)
                arcname = os.path.relpath(fpath, src_dir)
                zf.write(fpath, arcname)
    buf.seek(0)

    return StreamingResponse(
        buf,
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="{project_id}.zip"',
            "Access-Control-Allow-Origin": "*",
        }
    )

@app.get("/api/projects/{project_id}/files/{file_path:path}")
async def download_project_file(project_id: str, file_path: str):
    """Download a specific file from the project workspace."""
    import os
    from fastapi.responses import FileResponse
    
    workspace = os.environ.get("ARCANE_WORKSPACE", "/root/workspace")
    src_dir = os.path.join(workspace, "projects", project_id, "src")
    
    # Security: prevent path traversal
    full_path = os.path.normpath(os.path.join(src_dir, file_path))
    if not full_path.startswith(os.path.normpath(src_dir)):
        raise HTTPException(403, "Access denied")
    
    if not os.path.isfile(full_path):
        raise HTTPException(404, f"File '{file_path}' not found")
    
    return FileResponse(
        full_path,
        filename=os.path.basename(full_path),
        headers={"Access-Control-Allow-Origin": "*"}
    )



# ═══════════════════════════════════════════════════════════════════════════════
# BUDGET
# ═══════════════════════════════════════════════════════════════════════════════

@app.get("/api/budget")
async def global_budget():
    """Global budget overview across all projects."""
    if budget_controller:
        try:
            dash = budget_controller.dashboard()
            from shared.model_mask import mask_model_id
            return {
                "month": dash.get("month"),
                "spent": dash.get("total_usd", 0.0), "total_spent_usd": dash.get("total_usd", 0.0),
                "global_limit_usd": dash.get("global_limit_usd"),
                "global_status": dash.get("global_status", {}),
                "by_project": dash.get("by_project", {}),
                "by_model": {mask_model_id(k): v for k, v in dash.get("by_model", {}).items()},
                "by_category": dash.get("by_category", {}),
                "entries_count": dash.get("entries_count", 0),
            }
        except Exception as e:
            pass
    return {
        "spent": 0.0, "total_spent_usd": 0.0,
        "by_project": {},
        "by_model": {},
    }


@app.get("/api/budget/{project_id}")
async def project_budget(project_id: str):
    """Budget for a specific project."""
    if budget_controller:
        try:
            dash = budget_controller.dashboard(project_id=project_id)
            snap = budget_controller.status_project(project_id)
            from shared.model_mask import mask_model_id
            return {
                "project_id": project_id,
                "month": dash.get("month"),
                "spent_usd": dash.get("total_usd", 0.0),
                "limit_usd": snap.limit_usd if hasattr(snap, "limit_usd") else None,
                "remaining_usd": round(snap.limit_usd - snap.spent_usd, 4) if snap.limit_usd else None,
                "status": snap.status.value if hasattr(snap.status, "value") else str(snap.status),
                "by_model": {mask_model_id(k): v for k, v in dash.get("by_model", {}).items()},
                "by_task": dash.get("by_task", {}),
                "by_category": dash.get("by_category", {}),
                "entries_count": dash.get("entries_count", 0),
            }
        except Exception as e:
            pass
    return {
        "project_id": project_id,
        "spent_usd": 0.0,
        "by_model": {},
    }


# ═══════════════════════════════════════════════════════════════════════════════
# DOG RACING
# ═══════════════════════════════════════════════════════════════════════════════

@app.post("/api/dog-racing")
async def start_dog_race(req: DogRaceRequest):
    """Start a dog race: same task → multiple models → compare results. Spec §10B."""
    if len(req.models) < 2 or len(req.models) > 5:
        raise HTTPException(400, "Need 2-5 models for a race")
    
    api_key = os.environ.get("OPENROUTER_API_KEY", "")
    if not api_key:
        raise HTTPException(503, "OPENROUTER_API_KEY not set")
    
    from shared.llm.llm_client import SimpleLLMClient
    
    client = SimpleLLMClient(api_key=api_key)
    race_id = f"race_{int(time.time())}"
    
    async def call_model(model_id: str) -> dict:
        t0 = time.time()
        try:
            resp = await client.chat(
                model=model_id,
                messages=[{"role": "user", "content": req.task}],
                max_tokens=4096,
            )
            return {
                "engine": mask_model_id(model_id),
                "status": "done",
                "output": resp.get("content", "")[:5000],
                "tokens_in": resp.get("tokens_in", 0),
                "tokens_out": resp.get("tokens_out", 0),
                "cost_usd": resp.get("cost_usd", 0.0),
                "time_seconds": round(time.time() - t0, 2),
            }
        except Exception as e:
            return {
                "engine": mask_model_id(model_id),
                "status": "failed",
                "output": str(e)[:500],
                "tokens_in": 0, "tokens_out": 0,
                "cost_usd": 0.0,
                "time_seconds": round(time.time() - t0, 2),
            }
    
    # Parallel calls to all models
    results = await asyncio.gather(*[call_model(m) for m in req.models])
    await client.close()
    
    total_cost = sum(r["cost_usd"] for r in results)
    
    race_result = {
        "race_id": race_id,
        "task": req.task,
        "category": req.category or "general",
        "results": list(results),
        "status": "done",
        "total_cost_usd": round(total_cost, 6),
        "timestamp": time.time(),
    }
    # Persist race result for leaderboard aggregation
    try:
        import json as _json
        _races_dir = os.path.join(os.environ.get("ARCANE_WORKSPACE", "/root/workspace"), "races")
        os.makedirs(_races_dir, exist_ok=True)
        _races_file = os.path.join(_races_dir, "races.jsonl")
        with open(_races_file, "a", encoding="utf-8") as _f:
            _f.write(_json.dumps(race_result, ensure_ascii=False) + "\n")
    except Exception:
        pass
    return race_result


@app.get("/api/leaderboard")
async def leaderboard(category: Optional[str] = None):
    """Model leaderboard aggregated from stored dog-racing results."""
    import json as _json
    from shared.model_mask import mask_model_id
    _races_file = os.path.join(os.environ.get("ARCANE_WORKSPACE", "/root/workspace"), "races", "races.jsonl")
    stats: dict[str, dict] = {}
    total_races = 0
    try:
        with open(_races_file, encoding="utf-8") as _f:
            for line in _f:
                line = line.strip()
                if not line:
                    continue
                try:
                    race = _json.loads(line)
                except Exception:
                    continue
                cat = race.get("category", "general")
                if category and cat != category:
                    continue
                total_races += 1
                results = race.get("results", [])
                if not results:
                    continue
                # Rank by time (fastest = winner)
                done = [r for r in results if r.get("status") == "done"]
                done.sort(key=lambda r: r.get("time_seconds", 9999))
                for rank, r in enumerate(done):
                    mid = mask_model_id(r.get("model_id", "unknown"))
                    if mid not in stats:
                        stats[mid] = {"model": mid, "races": 0, "wins": 0,
                                      "total_time": 0.0, "total_cost": 0.0,
                                      "total_tokens_out": 0, "failures": 0}
                    s = stats[mid]
                    s["races"] += 1
                    if rank == 0:
                        s["wins"] += 1
                    s["total_time"] += r.get("time_seconds", 0)
                    s["total_cost"] += r.get("cost_usd", 0)
                    s["total_tokens_out"] += r.get("tokens_out", 0)
                for r in results:
                    if r.get("status") != "done":
                        mid = mask_model_id(r.get("model_id", "unknown"))
                        if mid in stats:
                            stats[mid]["failures"] += 1
    except FileNotFoundError:
        pass
    # Compute derived metrics
    board = []
    for s in stats.values():
        n = s["races"]
        board.append({
            "model": s["model"],
            "races": n,
            "wins": s["wins"],
            "win_rate": round(s["wins"] / n, 3) if n else 0,
            "avg_time_s": round(s["total_time"] / n, 2) if n else 0,
            "avg_cost_usd": round(s["total_cost"] / n, 6) if n else 0,
            "avg_tokens_out": round(s["total_tokens_out"] / n) if n else 0,
            "failures": s["failures"],
        })
    board.sort(key=lambda x: (-x["win_rate"], x["avg_time_s"]))
    return {
        "leaderboard": board,
        "category": category or "all",
        "total_races": total_races,
    }


# ═══════════════════════════════════════════════════════════════════════════════
# CONSOLIDATION
# ═══════════════════════════════════════════════════════════════════════════════

@app.post("/api/consolidation")
@app.post("/api/consolidate")  # alias
async def run_consolidation(req: ConsolidationRequest):
    """Send same prompt to multiple models, consolidate results. Spec §10.5."""
    if len(req.models) < 1:
        raise HTTPException(400, "Need at least 1 model")
    if len(req.models) == 1:
        req.models = req.models * 2  # duplicate single model for comparison
    
    api_key = os.environ.get("OPENROUTER_API_KEY", "")
    if not api_key:
        raise HTTPException(503, "OPENROUTER_API_KEY not set")
    
    try:
        from core.consolidation import consolidate as run_consolidate, ConsolidationConfig
        from shared.llm.llm_client import MODEL_MAP
        
        # Convert internal model IDs → OpenRouter IDs (consolidation expects provider/model format)
        openrouter_models = []
        for m in req.models:
            or_id = MODEL_MAP.get(m, m)
            # Ensure provider/model format
            if "/" not in or_id:
                or_id = f"openrouter/{or_id}"
            openrouter_models.append(or_id)
        
        config = ConsolidationConfig(
            models=tuple(openrouter_models),
            consolidator_override=MODEL_MAP.get(req.consolidator, req.consolidator),
        )
        
        report = await run_consolidate(
            prompt=req.task,
            config=config,
            api_key=api_key,
        )
        
        return {
            "status": "done",
            "consensus": report.consensus,
            "unique_insights": list(report.unique_insights),
            "contradictions": list(report.contradictions),
            "recommendation": report.recommendation,
            "responses": [{**r, "model": mask_model_id(r.get("model", "")), "model_id": ""} if isinstance(r, dict) else r for r in (report.raw_responses or [])],
            "consolidator_model": mask_model_id(report.consolidator_model),
            "total_cost_usd": round(report.total_cost_usd, 6),
            "total_latency_s": round(report.total_latency_s, 1),
        }
    except ImportError as e:
        raise HTTPException(503, f"Consolidation module not available: {e}")
    except Exception as e:
        logger.error(f"Consolidation failed: {e}", exc_info=True)
        raise HTTPException(500, f"Consolidation failed: {str(e)[:300]}")


# ═══════════════════════════════════════════════════════════════════════════════
# COLLECTIVE MIND (multi-round debate)
# ═══════════════════════════════════════════════════════════════════════════════

class CollectiveMindRequest(BaseModel):
    prompt: str
    models: list[str] = Field(default_factory=lambda: [
        "gpt-5.4-nano", "gemini-2.5-flash", "deepseek-v3.2"
    ])
    rounds: int = 2               # 1-3 critique+revision rounds
    judge: str = "gemini-2.5-flash"
    project_id: Optional[str] = None


@app.post("/api/collective-mind")
async def collective_mind(req: CollectiveMindRequest):
    from shared.model_mask import mask_model_id
    """Multi-round debate: models discuss, critique, revise → judge synthesizes. Spec §10.5+."""
    if len(req.models) < 2 or len(req.models) > 5:
        raise HTTPException(400, "Need 2-5 models")

    api_key = os.environ.get("OPENROUTER_API_KEY", "")
    if not api_key:
        raise HTTPException(503, "OPENROUTER_API_KEY not set")

    try:
        from core.collective_reasoning import deliberate, DeliberationConfig
        from shared.llm.llm_client import MODEL_MAP

        or_models = tuple(MODEL_MAP.get(m, m) for m in req.models)
        judge_model = MODEL_MAP.get(req.judge, req.judge)

        config = DeliberationConfig(
            models=or_models,
            judge=judge_model,
            rounds=max(1, min(3, req.rounds)),
        )

        # FIX-8: budget remaining via safe helper (never returns inf/None from dashboard)
        budget_remaining = _budget_remaining_safe()
        report = await deliberate(
            prompt=req.prompt, config=config, api_key=api_key,
            budget_remaining_usd=budget_remaining,
        )

        return {
            "status": "done",
            "final_answer": report.final_answer,
            "consensus": report.consensus,
            "disagreements": report.disagreements,
            "contributions": report.contributions,
            "confidence": report.confidence,
            "models_used": [mask_model_id(m) for m in report.models_used],
            "judge_model": mask_model_id(report.judge_model),
            "num_rounds": len(report.rounds),
            "total_cost_usd": round(report.total_cost_usd, 6),
            "total_latency_s": round(report.total_latency_s, 1),
        }
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        logger.error(f"Collective Mind failed: {e}", exc_info=True)
        raise HTTPException(500, f"Collective Mind failed: {str(e)[:300]}")



# ═══════════════════════════════════════════════════════════════════════════════
# DEBATE MODE (adversarial multi-round debate with judge)
# ═══════════════════════════════════════════════════════════════════════════════
class DebateRequest(BaseModel):
    topic: str
    models: list[str] = Field(default_factory=lambda: [
        "gpt-5.4-nano", "gemini-2.5-flash", "deepseek-v3.2"
    ])
    rounds: int = 2               # 1-3 rebuttal rounds
    judge: str = "gemini-2.5-flash"
    project_id: Optional[str] = None

@app.post("/api/debate")
async def run_debate_endpoint(req: DebateRequest):
    from shared.model_mask import mask_model_id
    """Adversarial debate: models argue directly with each other, judge synthesizes winner."""
    if len(req.models) < 2 or len(req.models) > 4:
        raise HTTPException(400, "Need 2-4 models for debate")
    api_key = os.environ.get("OPENROUTER_API_KEY", "")
    if not api_key:
        raise HTTPException(503, "OPENROUTER_API_KEY not set")
    try:
        from core.debate_mode import run_debate, DebateConfig
        from shared.llm.llm_client import MODEL_MAP
        or_models = tuple(MODEL_MAP.get(m, m) for m in req.models)
        judge_model = MODEL_MAP.get(req.judge, req.judge)
        config = DebateConfig(
            models=or_models,
            judge=judge_model,
            rounds=max(1, min(3, req.rounds)),
        )
        budget_remaining = _budget_remaining_safe()
        report = await run_debate(
            topic=req.topic, config=config, api_key=api_key,
            budget_remaining_usd=budget_remaining,
        )
        return {
            "status": "done",
            "topic": report.topic,
            "winner": report.winner,
            "winner_reason": report.winner_reason,
            "final_answer": report.final_answer,
            "key_agreements": report.key_agreements,
            "key_disagreements": report.key_disagreements,
            "strongest_argument": report.strongest_argument,
            "weakest_argument": report.weakest_argument,
            "confidence": report.confidence,
            "all_statements": [[{**s, "model_id": mask_model_id(s.get("model_id", ""))} if isinstance(s, dict) else s for s in rnd] if isinstance(rnd, list) else rnd for rnd in (report.all_statements or [])],
            "models_used": [mask_model_id(m) for m in report.models_used],
            "judge_model": mask_model_id(report.judge_model),
            "num_rounds": report.num_rounds,
            "total_cost_usd": round(report.total_cost_usd, 6),
            "total_latency_s": round(report.total_latency_s, 1),
        }
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        logger.error(f"Debate failed: {e}", exc_info=True)
        raise HTTPException(500, f"Debate failed: {str(e)[:300]}")

# ═══════════════════════════════════════════════════════════════════════════════
# COUNCIL MODE (parallel opinions + synthesizer)
# ═══════════════════════════════════════════════════════════════════════════════
class CouncilRequest(BaseModel):
    question: Optional[str] = None
    task: Optional[str] = None  # alias for question

    def model_post_init(self, __context):
        if not self.question and self.task:
            object.__setattr__(self, "question", self.task)
        elif not self.question:
            object.__setattr__(self, "question", "")
    models: list[str] = Field(default_factory=lambda: [
        "gpt-5.4-nano", "gemini-2.5-flash", "deepseek-v3.2", "claude-sonnet-4.6"
    ])
    synthesizer: str = "gemini-2.5-flash"
    project_id: Optional[str] = None

@app.post("/api/council")
async def run_council_endpoint(req: CouncilRequest):
    from shared.model_mask import mask_model_id
    """Council: models give independent opinions in parallel, synthesizer draws conclusions."""
    if len(req.models) < 2 or len(req.models) > 5:
        raise HTTPException(400, "Need 2-5 models for council")
    api_key = os.environ.get("OPENROUTER_API_KEY", "")
    if not api_key:
        raise HTTPException(503, "OPENROUTER_API_KEY not set")
    try:
        from core.council_mode import run_council, CouncilConfig
        from shared.llm.llm_client import MODEL_MAP
        or_models = tuple(MODEL_MAP.get(m, m) for m in req.models)
        synth_model = MODEL_MAP.get(req.synthesizer, req.synthesizer)
        config = CouncilConfig(
            models=or_models,
            synthesizer=synth_model,
        )
        budget_remaining = _budget_remaining_safe()
        report = await run_council(
            question=req.question, config=config, api_key=api_key,
            budget_remaining_usd=budget_remaining,
        )
        return {
            "status": "done",
            "question": report.question,
            "final_answer": report.final_answer,
            "consensus": report.consensus,
            "unique_insights": report.unique_insights,
            "contradictions": report.contradictions,
            "most_insightful": report.most_insightful,
            "recommendation": report.recommendation,
            "confidence": report.confidence,
            "opinions": [{**op, "model_id": mask_model_id(op.get("model_id", ""))} if isinstance(op, dict) else op for op in (report.opinions if isinstance(report.opinions, list) else [])],
            "models_used": [mask_model_id(m) for m in report.models_used],
            "synthesizer_model": mask_model_id(report.synthesizer_model),
            "total_cost_usd": round(report.total_cost_usd, 6),
            "total_latency_s": round(report.total_latency_s, 1),
        }
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        logger.error(f"Council failed: {e}", exc_info=True)
        raise HTTPException(500, f"Council failed: {str(e)[:300]}")

# ═══════════════════════════════════════════════════════════════════════════════
# WEBSOCKET (real-time updates)
# ═══════════════════════════════════════════════════════════════════════════════

@app.get("/api/rate-limit/status")
async def rate_limit_status(request: Request):
    """Current rate limit info for the requesting IP."""
    client_ip = request.client.host if request.client else "unknown"
    # Show usage for a generic key
    rl_key = f"{client_ip}:status"
    allowed, retry_after = _task_rate_limiter.is_allowed(rl_key)
    # Don't actually consume a slot for status check — just report
    _task_rate_limiter._calls.get(rl_key, [None]).pop() if not allowed else None
    return {
        "limit": _task_rate_limiter._max,
        "window_sec": _task_rate_limiter._window,
        "ip": client_ip,
    }


# ══════════════ PROJECT GALLERY ═══════════════════════════════════════════════




@app.get("/api/projects/{project_id}/preview/html")
async def project_preview_html(project_id: str):
    """
    Serve the main HTML file of a project for inline iframe preview.
    Finds index.html or the largest .html file in the project.
    Returns the HTML content with a base tag so relative assets work.
    """
    from fastapi.responses import HTMLResponse
    workspace = os.environ.get("ARCANE_WORKSPACE", "/root/workspace")
    src_dir = os.path.join(workspace, "projects", project_id, "src")
    if not os.path.isdir(src_dir):
        return HTMLResponse("<h2>Project not found</h2>", status_code=404)

    # Find main HTML: prefer index.html, then largest .html file
    html_files = []
    for root, dirs, fnames in os.walk(src_dir):
        dirs[:] = [d for d in dirs if not d.startswith(".")]
        for fname in fnames:
            if fname.endswith((".html", ".htm")):
                fpath = os.path.join(root, fname)
                html_files.append((fname, fpath, os.path.getsize(fpath)))

    if not html_files:
        return HTMLResponse("<h2>No HTML files in project</h2>")

    # index.html first, then by size
    html_files.sort(key=lambda x: (0 if x[0].lower() == "index.html" else 1, -x[2]))
    main_html_path = html_files[0][1]

    try:
        with open(main_html_path, encoding="utf-8", errors="replace") as f:
            content = f.read()

        # Inject base tag so relative assets (CSS, JS, images) resolve correctly
        base_path = os.path.dirname(main_html_path) + "/"
        if "<head>" in content.lower() and "<base" not in content.lower():
            # Use data: URL for sandbox iframe — assets won't load but HTML is visible
            pass  # Keep as-is, frontend handles with srcdoc

        return HTMLResponse(content=content, media_type="text/html; charset=utf-8")
    except Exception as e:
        return HTMLResponse(f"<h2>Error reading file: {e}</h2>", status_code=500)


@app.get("/api/projects/{project_id}/preview/file/{filepath:path}")
async def project_serve_asset(project_id: str, filepath: str):
    """Serve a specific asset (CSS, JS, image) from project workspace."""
    from fastapi.responses import FileResponse
    import mimetypes
    workspace = os.environ.get("ARCANE_WORKSPACE", "/root/workspace")
    # Security: resolve path and ensure it stays in project dir
    base = os.path.realpath(os.path.join(workspace, "projects", project_id, "src"))
    full = os.path.realpath(os.path.join(base, filepath))
    if not full.startswith(base):
        from fastapi import Response
        return Response("Forbidden", status_code=403)
    if not os.path.exists(full):
        from fastapi import Response
        return Response("Not found", status_code=404)
    mime, _ = mimetypes.guess_type(full)
    return FileResponse(full, media_type=mime or "application/octet-stream")


@app.get("/api/projects/{project_id}/stats")
async def project_stats(project_id: str):
    """
    Aggregated stats for a project: tasks, cost, models used, timeline.
    Combines in-memory runs + SQLite task history.
    """
    stats = {
        "project_id": project_id,
        "tasks_total": 0, "tasks_done": 0, "tasks_failed": 0,
        "total_cost_usd": 0.0, "total_duration_s": 0.0,
        "models_used": [], "artifacts": [], "last_run_at": None,
    }

    try:
        # From in-memory runs
        if orchestrator and hasattr(orchestrator, "_runs"):
            for run in orchestrator._runs.values():
                rd = run.to_dict() if hasattr(run, "to_dict") else {}
                if rd.get("project_id") != project_id:
                    continue
                stats["tasks_total"] += 1
                if rd.get("status") == "done":
                    stats["tasks_done"] += 1
                elif rd.get("status") == "failed":
                    stats["tasks_failed"] += 1
                stats["total_cost_usd"] += float(rd.get("actual_cost", 0))
                stats["total_duration_s"] += float(rd.get("duration_seconds", 0))
                for art in rd.get("artifacts", []):
                    if art not in stats["artifacts"]:
                        stats["artifacts"].append(art)
                if rd.get("finished_at"):
                    stats["last_run_at"] = rd["finished_at"]

        # From SQLite task history
        if orchestrator and getattr(orchestrator, "history_db", None):
            db_runs = orchestrator.history_db.get_all(limit=200, project_id=project_id)
            for rd in db_runs:
                stats["tasks_total"] += 1
                if rd.get("status") == "done":
                    stats["tasks_done"] += 1
                    stats["total_cost_usd"] += float(rd.get("actual_cost", 0))
                    stats["total_duration_s"] += float(rd.get("duration_seconds", 0))
                # Collect models
                team = rd.get("team", {})
                if isinstance(team, dict):
                    for m in team.values():
                        if m and m not in stats["models_used"]:
                            stats["models_used"].append(m)

        # Mask model names
        from shared.model_mask import mask_model_id
        stats["models_used"] = [mask_model_id(m) for m in stats["models_used"]]
        stats["total_cost_usd"] = round(stats["total_cost_usd"], 4)
        stats["total_duration_s"] = round(stats["total_duration_s"], 1)

    except Exception as e:
        logger.warning(f"project_stats error: {e}")

    return stats


@app.websocket("/ws/{project_id}")
async def websocket_endpoint(websocket: WebSocket, project_id: str):
    """Real-time updates for a project."""
    await websocket.accept()
    
    if project_id not in ws_connections:
        ws_connections[project_id] = []
    ws_connections[project_id].append(websocket)
    
    try:
        while True:
            # Keep connection alive, receive any client messages
            data = await websocket.receive_text()
            # Could handle client commands here (cancel, approve, etc.)
    except WebSocketDisconnect:
        ws_connections[project_id].remove(websocket)


async def _broadcast_status(run_id: str, status: str, data: dict):
    """
    Broadcast run status to:
      1. WebSocket clients (project-level, for project dashboard)
      2. SSE subscribers (chat-level, for chat UI real-time updates)
    """
    from shared.model_mask import mask_event_payload
    project_id = data.get("project_id", "")
    clean_data = mask_event_payload(data)

    event_payload = {
        "type": "run_status",
        "run_id": run_id,
        "status": status,
        "data": clean_data,
    }
    message = json.dumps(event_payload)

    # 1. WebSocket broadcast (project dashboard)
    clients = ws_connections.get(project_id, [])
    for ws in clients[:]:
        try:
            await ws.send_text(message)
        except Exception:
            clients.remove(ws)

    # 2. SSE bus broadcast (chat UI real-time)
    # Find chat_id from run data or use project_id as fallback key
    chat_id = data.get("chat_id") or data.get("run_id") or project_id
    try:
        from compat_all import _store as _ca_store
        await _ca_store.sse_bus.publish(chat_id, event_payload)
        # Also publish to project_id channel in case frontend subscribes by project
        if chat_id != project_id:
            await _ca_store.sse_bus.publish(project_id, event_payload)
    except Exception:
        pass


# ═══════════════════════════════════════════════════════════════════════════════
# ENTRYPOINT
# ═══════════════════════════════════════════════════════════════════════════════


# ─── PDF EXPORT ENDPOINTS ────────────────────────────────────────────────────

@app.post("/api/export/council-pdf")
async def export_council_pdf(payload: dict = Body(...)):
    """
    Generate a PDF report from a Council session result.
    Expects the full council result dict (same shape as /api/council response).
    Returns a PDF file for download.
    """
    import io
    from fpdf import FPDF
    from fastapi.responses import StreamingResponse
    import datetime

    question = payload.get("question", "Вопрос не указан")
    opinions = payload.get("opinions", [])
    final_answer = payload.get("final_answer", "")
    consensus = payload.get("consensus", "")
    unique_insights = payload.get("unique_insights", [])
    contradictions = payload.get("contradictions", [])
    recommendation = payload.get("recommendation", "")
    confidence = payload.get("confidence", 0.0)
    total_cost = payload.get("total_cost_usd", 0.0)
    total_time = payload.get("total_time_s", 0.0)

    class PDF(FPDF):
        def header(self):
            self.set_font("Helvetica", "B", 10)
            self.set_text_color(100, 100, 100)
            self.cell(0, 8, "ARCANE — Council Report", align="R", new_x="LMARGIN", new_y="NEXT")
            self.ln(2)

        def footer(self):
            self.set_y(-15)
            self.set_font("Helvetica", "", 8)
            self.set_text_color(150, 150, 150)
            self.cell(0, 10, f"Page {self.page_no()}", align="C")

    pdf = PDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()

    # Title
    pdf.set_font("Helvetica", "B", 18)
    pdf.set_text_color(30, 30, 30)
    pdf.cell(0, 12, "Council Report", new_x="LMARGIN", new_y="NEXT")

    pdf.set_font("Helvetica", "", 9)
    pdf.set_text_color(120, 120, 120)
    pdf.cell(0, 6, datetime.datetime.now().strftime("%d.%m.%Y %H:%M"), new_x="LMARGIN", new_y="NEXT")
    pdf.ln(4)

    # Question
    pdf.set_font("Helvetica", "B", 11)
    pdf.set_text_color(60, 60, 60)
    pdf.cell(0, 8, "Question", new_x="LMARGIN", new_y="NEXT")
    pdf.set_draw_color(200, 200, 200)
    pdf.set_line_width(0.3)
    pdf.line(pdf.get_x(), pdf.get_y(), pdf.get_x() + 170, pdf.get_y())
    pdf.ln(3)
    pdf.set_font("Helvetica", "", 11)
    pdf.set_text_color(30, 30, 30)
    pdf.multi_cell(0, 7, question)
    pdf.ln(6)

    # Stats bar
    pdf.set_font("Helvetica", "", 9)
    pdf.set_text_color(100, 100, 100)
    pdf.cell(0, 6, f"Models: {len(opinions)}   |   Confidence: {int(confidence*100)}%   |   Cost: ${total_cost:.4f}   |   Time: {total_time:.1f}s", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(6)

    # Individual opinions
    pdf.set_font("Helvetica", "B", 11)
    pdf.set_text_color(60, 60, 60)
    pdf.cell(0, 8, "Individual Opinions", new_x="LMARGIN", new_y="NEXT")
    pdf.line(pdf.get_x(), pdf.get_y(), pdf.get_x() + 170, pdf.get_y())
    pdf.ln(4)

    for i, op in enumerate(opinions):
        model_label = op.get("model_label", op.get("model_id", f"Model {i+1}"))
        content = op.get("content", "")
        cost = op.get("cost_usd", 0)
        time_s = op.get("time_s", 0)

        pdf.set_font("Helvetica", "B", 10)
        pdf.set_text_color(50, 100, 180)
        pdf.cell(0, 7, f"{i+1}. {model_label}", new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("Helvetica", "", 9)
        pdf.set_text_color(140, 140, 140)
        pdf.cell(0, 5, f"${cost:.4f}  |  {time_s:.1f}s", new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("Helvetica", "", 10)
        pdf.set_text_color(40, 40, 40)
        # Truncate very long opinions
        display_content = content[:1500] + ("..." if len(content) > 1500 else "")
        pdf.multi_cell(0, 6, display_content)
        pdf.ln(4)

    # Synthesis section
    pdf.add_page()
    pdf.set_font("Helvetica", "B", 11)
    pdf.set_text_color(60, 60, 60)
    pdf.cell(0, 8, "Synthesis", new_x="LMARGIN", new_y="NEXT")
    pdf.line(pdf.get_x(), pdf.get_y(), pdf.get_x() + 170, pdf.get_y())
    pdf.ln(4)

    sections = [
        ("Final Answer", final_answer),
        ("Consensus", consensus),
        ("Recommendation", recommendation),
    ]
    for title, body in sections:
        if body:
            pdf.set_font("Helvetica", "B", 10)
            pdf.set_text_color(80, 80, 80)
            pdf.cell(0, 7, title, new_x="LMARGIN", new_y="NEXT")
            pdf.set_font("Helvetica", "", 10)
            pdf.set_text_color(30, 30, 30)
            pdf.multi_cell(0, 6, body[:2000])
            pdf.ln(4)

    if unique_insights:
        pdf.set_font("Helvetica", "B", 10)
        pdf.set_text_color(80, 80, 80)
        pdf.cell(0, 7, "Unique Insights", new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("Helvetica", "", 10)
        pdf.set_text_color(30, 30, 30)
        for ins in unique_insights[:5]:
            pdf.multi_cell(0, 6, f"• {ins}")
        pdf.ln(4)

    if contradictions:
        pdf.set_font("Helvetica", "B", 10)
        pdf.set_text_color(80, 80, 80)
        pdf.cell(0, 7, "Contradictions", new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("Helvetica", "", 10)
        pdf.set_text_color(30, 30, 30)
        for con in contradictions[:5]:
            pdf.multi_cell(0, 6, f"• {con}")

    buf = io.BytesIO(pdf.output())
    filename = f"council_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
    return StreamingResponse(
        buf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'}
    )


@app.post("/api/export/debate-pdf")
async def export_debate_pdf(payload: dict = Body(...)):
    """
    Generate a PDF report from a Debate session result.
    Expects the full debate result dict (same shape as /api/debate response).
    """
    import io
    from fpdf import FPDF
    from fastapi.responses import StreamingResponse
    import datetime

    question = payload.get("question", "Вопрос не указан")
    all_statements = payload.get("all_statements", [])
    winner = payload.get("winner", "")
    winner_reason = payload.get("winner_reason", "")
    final_answer = payload.get("final_answer", "")
    confidence = payload.get("confidence", 0.0)
    total_cost = payload.get("total_cost_usd", 0.0)
    total_time = payload.get("total_time_s", 0.0)
    num_rounds = payload.get("num_rounds", len(all_statements))

    class PDF(FPDF):
        def header(self):
            self.set_font("Helvetica", "B", 10)
            self.set_text_color(100, 100, 100)
            self.cell(0, 8, "ARCANE — Debate Report", align="R", new_x="LMARGIN", new_y="NEXT")
            self.ln(2)

        def footer(self):
            self.set_y(-15)
            self.set_font("Helvetica", "", 8)
            self.set_text_color(150, 150, 150)
            self.cell(0, 10, f"Page {self.page_no()}", align="C")

    pdf = PDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()

    # Title
    pdf.set_font("Helvetica", "B", 18)
    pdf.set_text_color(30, 30, 30)
    pdf.cell(0, 12, "Debate Report", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 9)
    pdf.set_text_color(120, 120, 120)
    pdf.cell(0, 6, datetime.datetime.now().strftime("%d.%m.%Y %H:%M"), new_x="LMARGIN", new_y="NEXT")
    pdf.ln(4)

    # Question
    pdf.set_font("Helvetica", "B", 11)
    pdf.set_text_color(60, 60, 60)
    pdf.cell(0, 8, "Motion", new_x="LMARGIN", new_y="NEXT")
    pdf.set_draw_color(200, 200, 200)
    pdf.set_line_width(0.3)
    pdf.line(pdf.get_x(), pdf.get_y(), pdf.get_x() + 170, pdf.get_y())
    pdf.ln(3)
    pdf.set_font("Helvetica", "I", 12)
    pdf.set_text_color(30, 30, 30)
    pdf.multi_cell(0, 7, question)
    pdf.ln(4)

    # Stats
    pdf.set_font("Helvetica", "", 9)
    pdf.set_text_color(100, 100, 100)
    pdf.cell(0, 6, f"Rounds: {num_rounds}   |   Confidence: {int(confidence*100)}%   |   Cost: ${total_cost:.4f}   |   Time: {total_time:.1f}s", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(6)

    # Winner banner
    if winner:
        pdf.set_fill_color(240, 248, 240)
        pdf.set_draw_color(100, 180, 100)
        pdf.set_line_width(0.5)
        pdf.rect(pdf.get_x(), pdf.get_y(), 170, 18, style="FD")
        pdf.set_font("Helvetica", "B", 11)
        pdf.set_text_color(40, 120, 40)
        pdf.cell(0, 9, f"  Winner: {winner}", new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("Helvetica", "", 9)
        pdf.set_text_color(60, 100, 60)
        pdf.cell(0, 9, f"  {winner_reason[:120]}", new_x="LMARGIN", new_y="NEXT")
        pdf.ln(6)

    # Rounds
    round_labels = ["Opening Statements", "Rebuttal Round 1", "Rebuttal Round 2", "Rebuttal Round 3"]
    for r_idx, round_stmts in enumerate(all_statements):
        label = round_labels[r_idx] if r_idx < len(round_labels) else f"Round {r_idx+1}"
        pdf.set_font("Helvetica", "B", 11)
        pdf.set_text_color(60, 60, 60)
        pdf.cell(0, 8, label, new_x="LMARGIN", new_y="NEXT")
        pdf.set_draw_color(200, 200, 200)
        pdf.line(pdf.get_x(), pdf.get_y(), pdf.get_x() + 170, pdf.get_y())
        pdf.ln(4)

        for stmt in round_stmts:
            model_label = stmt.get("model_label", stmt.get("model_id", "Model"))
            content = stmt.get("content", "")
            cost = stmt.get("cost_usd", 0)
            time_s = stmt.get("time_s", 0)

            pdf.set_font("Helvetica", "B", 10)
            pdf.set_text_color(50, 100, 180)
            pdf.cell(0, 7, model_label, new_x="LMARGIN", new_y="NEXT")
            pdf.set_font("Helvetica", "", 9)
            pdf.set_text_color(140, 140, 140)
            pdf.cell(0, 5, f"${cost:.4f}  |  {time_s:.1f}s", new_x="LMARGIN", new_y="NEXT")
            pdf.set_font("Helvetica", "", 10)
            pdf.set_text_color(40, 40, 40)
            display_content = content[:1200] + ("..." if len(content) > 1200 else "")
            pdf.multi_cell(0, 6, display_content)
            pdf.ln(4)

        pdf.ln(2)

    # Final answer
    if final_answer:
        pdf.add_page()
        pdf.set_font("Helvetica", "B", 11)
        pdf.set_text_color(60, 60, 60)
        pdf.cell(0, 8, "Final Answer", new_x="LMARGIN", new_y="NEXT")
        pdf.line(pdf.get_x(), pdf.get_y(), pdf.get_x() + 170, pdf.get_y())
        pdf.ln(4)
        pdf.set_font("Helvetica", "", 10)
        pdf.set_text_color(30, 30, 30)
        pdf.multi_cell(0, 6, final_answer[:3000])

    buf = io.BytesIO(pdf.output())
    filename = f"debate_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
    return StreamingResponse(
        buf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'}
    )


if __name__ == "__main__":
    import uvicorn
    
    host = os.environ.get("ARCANE_HOST", "0.0.0.0")
    port = int(os.environ.get("ARCANE_PORT", "8900"))
    debug = os.environ.get("ARCANE_DEBUG", "false").lower() == "true"
    
    print(f"\n{'='*50}")
    print(f"  ARCANE 2 API Server")
    print(f"  http://{host}:{port}")
    print(f"  Docs: http://{host}:{port}/docs")
    print(f"{'='*50}\n")
    
    uvicorn.run(app,
        host=host,
        port=port,
        reload=debug,
        log_level="info",
    )





# ─── Package 4.3: Simple preview endpoint ─────────────────────────────────────
from fastapi.responses import FileResponse as _FileResponse

@app.get("/preview/{project_id}/{path:path}")
async def preview_file(project_id: str, path: str):
    """Serve project files for browser preview. Path traversal protected."""
    workspace = os.environ.get("ARCANE_WORKSPACE", "/root/workspace")
    base = os.path.realpath(os.path.join(workspace, "projects", project_id, "src"))
    full = os.path.realpath(os.path.join(base, path))
    if not full.startswith(base + os.sep) and full != base:
        raise HTTPException(404, "Not found")
    if not os.path.isfile(full):
        raise HTTPException(404, f"File not found: {path}")
    return _FileResponse(full)
