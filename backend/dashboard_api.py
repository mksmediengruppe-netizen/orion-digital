"""
Dashboard API — REST endpoints для мониторинга всех модулей ORION.
==================================================================
Endpoints:
  GET /api/dashboard/overview     — общая сводка
  GET /api/dashboard/modules      — статус всех модулей
  GET /api/dashboard/agents       — метрики агентов
  GET /api/dashboard/tasks        — список задач
  GET /api/dashboard/artifacts    — реестр артефактов
  GET /api/dashboard/operators    — история операторов
  GET /api/dashboard/verification — вердикты проверок
  GET /api/dashboard/prompts      — статистика промптов
  GET /api/dashboard/projects     — список проектов
  GET /api/dashboard/health       — health check всех подсистем

Все endpoints возвращают JSON.
Аутентификация через X-API-Key header.
"""
import json
import time
import logging
import importlib
import os
from typing import Dict, List, Any

logger = logging.getLogger("dashboard_api")

# Module registry for health checks
DASHBOARD_MODULES = [
    "model_router",
    "task_charter",
    "execution_snapshots",
    "goal_keeper",
    "tool_sandbox",
    "final_judge",
    "task_scorecard",
    "autonomy_modes",
    "artifact_handoff",
    "amendment_extractor",
    "crash_recovery",
    "runtime_state",
    "langgraph_persistence",
    "project_brain",
    "artifact_workspace",
    "high_level_operators",
    "verification_engine",
    "subagent_runtime",
    "prompt_compiler",
    "database",
    "prompts",
    "shared",
    "message_queue",
    "solution_cache",
]


class DashboardAPI:
    """Dashboard API для мониторинга ORION."""

    def __init__(self):
        self._start_time = time.time()

    def overview(self) -> Dict:
        """Общая сводка системы."""
        uptime = time.time() - self._start_time
        
        # Count available modules
        available = 0
        failed = 0
        for mod_name in DASHBOARD_MODULES:
            try:
                importlib.import_module(mod_name)
                available += 1
            except Exception:
                failed += 1

        return {
            "system": "ORION AI Agent",
            "version": "2.0",
            "uptime_seconds": round(uptime, 1),
            "modules_total": len(DASHBOARD_MODULES),
            "modules_available": available,
            "modules_failed": failed,
            "status": "healthy" if failed == 0 else "degraded",
            "timestamp": time.time()
        }

    def modules_status(self) -> List[Dict]:
        """Статус всех модулей."""
        results = []
        for mod_name in DASHBOARD_MODULES:
            entry = {"module": mod_name, "status": "unknown"}
            try:
                mod = importlib.import_module(mod_name)
                entry["status"] = "ok"
                # Check for version or description
                entry["doc"] = (getattr(mod, '__doc__', '') or '')[:100]
                # Check for key classes/functions
                attrs = [a for a in dir(mod) if not a.startswith('_')]
                entry["exports"] = len(attrs)
            except ImportError as e:
                entry["status"] = "import_error"
                entry["error"] = str(e)[:200]
            except Exception as e:
                entry["status"] = "error"
                entry["error"] = str(e)[:200]
            results.append(entry)
        return results

    def agents_metrics(self) -> Dict:
        """Метрики агентов из SubagentRuntime."""
        try:
            from subagent_runtime import get_subagent_runtime
            sr = get_subagent_runtime()
            return sr.get_team_summary()
        except Exception as e:
            return {"error": str(e), "available": False}

    def tasks_list(self, limit: int = 20) -> Dict:
        """Список задач из TaskScorecard."""
        try:
            from task_scorecard import get_scorecard_store
            store = get_scorecard_store()
            # Get recent tasks
            recent = store.recent(limit=limit)
            return {
                "count": len(recent),
                "tasks": recent
            }
        except Exception as e:
            return {"error": str(e), "available": False}

    def artifacts_list(self) -> Dict:
        """Реестр артефактов."""
        try:
            from artifact_workspace import get_artifact_workspace
            aw = get_artifact_workspace()
            # Get all by status
            result = {}
            for status in ["draft", "reviewed", "approved", "deployed"]:
                items = aw.list_by_status(status)
                result[status] = len(items)
            result["total"] = sum(result.values())
            return result
        except Exception as e:
            return {"error": str(e), "available": False}

    def operators_history(self, limit: int = 10) -> Dict:
        """История операторов."""
        try:
            from high_level_operators import get_operators
            ops = get_operators()
            history = ops.get_history(limit=limit)
            return {
                "count": len(history),
                "history": history
            }
        except Exception as e:
            return {"error": str(e), "available": False}

    def verification_summary(self) -> Dict:
        """Сводка проверок."""
        try:
            from verification_engine import get_verification_engine
            ve = get_verification_engine()
            return ve.summary()
        except Exception as e:
            return {"error": str(e), "available": False}

    def prompts_stats(self) -> Dict:
        """Статистика промптов."""
        try:
            from prompt_compiler import get_prompt_compiler
            pc = get_prompt_compiler()
            return pc.stats()
        except Exception as e:
            return {"error": str(e), "available": False}

    def projects_list(self) -> Dict:
        """Список проектов."""
        try:
            from project_brain import get_project_brain
            pb = get_project_brain()
            projects = pb.list_all()
            return {
                "count": len(projects),
                "projects": projects
            }
        except Exception as e:
            return {"error": str(e), "available": False}

    def health_check(self) -> Dict:
        """Health check всех подсистем."""
        checks = {}
        
        # Database
        try:
            from database import get_connection
            conn = get_connection()
            conn.execute("SELECT 1")
            checks["database"] = "ok"
        except Exception as e:
            checks["database"] = f"error: {str(e)[:100]}"

        # Modules
        module_ok = 0
        module_fail = 0
        for mod_name in DASHBOARD_MODULES:
            try:
                importlib.import_module(mod_name)
                module_ok += 1
            except Exception:
                module_fail += 1
        checks["modules"] = f"{module_ok}/{len(DASHBOARD_MODULES)} ok"

        # Disk
        try:
            import shutil
            usage = shutil.disk_usage("/var/www/orion")
            checks["disk_free_gb"] = round(usage.free / (1024**3), 1)
            checks["disk_used_percent"] = round(usage.used / usage.total * 100, 1)
        except Exception:
            checks["disk"] = "unknown"

        checks["status"] = "healthy" if module_fail == 0 else "degraded"
        checks["timestamp"] = time.time()
        return checks


# ═══════════════════════════════════════════
# FLASK ROUTES (blueprint)
# ═══════════════════════════════════════════
def register_dashboard_routes(app):
    """Register dashboard routes on Flask app."""
    from flask import jsonify, request
    
    dashboard = DashboardAPI()

    @app.route("/api/dashboard/overview", methods=["GET"])
    def dashboard_overview():
        return jsonify(dashboard.overview())

    @app.route("/api/dashboard/modules", methods=["GET"])
    def dashboard_modules():
        return jsonify(dashboard.modules_status())

    @app.route("/api/dashboard/agents", methods=["GET"])
    def dashboard_agents():
        return jsonify(dashboard.agents_metrics())

    @app.route("/api/dashboard/tasks", methods=["GET"])
    def dashboard_tasks():
        limit = request.args.get("limit", 20, type=int)
        return jsonify(dashboard.tasks_list(limit))

    @app.route("/api/dashboard/artifacts", methods=["GET"])
    def dashboard_artifacts():
        return jsonify(dashboard.artifacts_list())

    @app.route("/api/dashboard/operators", methods=["GET"])
    def dashboard_operators():
        limit = request.args.get("limit", 10, type=int)
        return jsonify(dashboard.operators_history(limit))

    @app.route("/api/dashboard/verification", methods=["GET"])
    def dashboard_verification():
        return jsonify(dashboard.verification_summary())

    @app.route("/api/dashboard/prompts", methods=["GET"])
    def dashboard_prompts():
        return jsonify(dashboard.prompts_stats())

    @app.route("/api/dashboard/projects", methods=["GET"])
    def dashboard_projects():
        return jsonify(dashboard.projects_list())

    @app.route("/api/dashboard/health", methods=["GET"])
    def dashboard_health():
        return jsonify(dashboard.health_check())


# ═══════════════════════════════════════════
# SINGLETON
# ═══════════════════════════════════════════
_dashboard = None

def get_dashboard_api() -> DashboardAPI:
    global _dashboard
    if _dashboard is None:
        _dashboard = DashboardAPI()
    return _dashboard
