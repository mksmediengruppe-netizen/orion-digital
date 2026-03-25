"""
ORION Task Scheduler
=====================
Cron-like task scheduling system for recurring and one-time tasks.
Uses APScheduler with SQLite job store for persistence across restarts.
Supports: cron expressions, interval-based, one-time delayed execution.
"""

import logging
import os
import json
import time
import uuid
import threading
from datetime import datetime, timezone
from typing import Dict, List, Optional, Any
from flask import Flask, request, jsonify

logger = logging.getLogger("task_scheduler")

DATA_DIR = os.environ.get("DATA_DIR", "/var/www/orion/backend/data")
SCHEDULER_DB = os.path.join(DATA_DIR, "scheduler.db")

# ── Task Store ──

class TaskStore:
    """SQLite-backed task store for scheduled tasks."""

    def __init__(self, db_path: str = None):
        import sqlite3
        self.db_path = db_path or SCHEDULER_DB
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        self._init_db()

    def _init_db(self):
        import sqlite3
        conn = sqlite3.connect(self.db_path)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS scheduled_tasks (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                description TEXT,
                schedule_type TEXT NOT NULL,
                cron_expr TEXT,
                interval_seconds INTEGER,
                prompt TEXT NOT NULL,
                user_id TEXT,
                chat_id TEXT,
                is_active INTEGER DEFAULT 1,
                repeat INTEGER DEFAULT 1,
                last_run TEXT,
                next_run TEXT,
                run_count INTEGER DEFAULT 0,
                max_runs INTEGER DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                metadata TEXT DEFAULT '{}'
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS task_runs (
                id TEXT PRIMARY KEY,
                task_id TEXT NOT NULL,
                started_at TEXT NOT NULL,
                finished_at TEXT,
                status TEXT DEFAULT 'running',
                result TEXT,
                error TEXT,
                FOREIGN KEY (task_id) REFERENCES scheduled_tasks(id)
            )
        """)
        conn.commit()
        conn.close()

    def _conn(self):
        import sqlite3
        return sqlite3.connect(self.db_path)

    def create_task(self, task: Dict) -> Dict:
        """Create a new scheduled task."""
        task_id = task.get("id", f"task-{uuid.uuid4().hex[:8]}")
        now = datetime.now(timezone.utc).isoformat()
        conn = self._conn()
        conn.execute("""
            INSERT INTO scheduled_tasks
            (id, name, description, schedule_type, cron_expr, interval_seconds,
             prompt, user_id, chat_id, is_active, repeat, created_at, updated_at, metadata)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            task_id, task.get("name", "Unnamed"),
            task.get("description", ""),
            task.get("schedule_type", "cron"),
            task.get("cron_expr"),
            task.get("interval_seconds"),
            task.get("prompt", ""),
            task.get("user_id"),
            task.get("chat_id"),
            1 if task.get("is_active", True) else 0,
            1 if task.get("repeat", True) else 0,
            now, now,
            json.dumps(task.get("metadata", {})),
        ))
        conn.commit()
        conn.close()
        return {"id": task_id, "created": True}

    def get_task(self, task_id: str) -> Optional[Dict]:
        conn = self._conn()
        cur = conn.execute("SELECT * FROM scheduled_tasks WHERE id = ?", (task_id,))
        row = cur.fetchone()
        conn.close()
        if not row:
            return None
        cols = [d[0] for d in cur.description]
        return dict(zip(cols, row))

    def list_tasks(self, user_id: str = None, active_only: bool = True) -> List[Dict]:
        conn = self._conn()
        query = "SELECT * FROM scheduled_tasks"
        params = []
        conditions = []
        if active_only:
            conditions.append("is_active = 1")
        if user_id:
            conditions.append("user_id = ?")
            params.append(user_id)
        if conditions:
            query += " WHERE " + " AND ".join(conditions)
        query += " ORDER BY created_at DESC"
        cur = conn.execute(query, params)
        cols = [d[0] for d in cur.description]
        rows = [dict(zip(cols, r)) for r in cur.fetchall()]
        conn.close()
        return rows

    def update_task(self, task_id: str, updates: Dict) -> bool:
        conn = self._conn()
        sets = []
        params = []
        for key, val in updates.items():
            if key in ("name", "description", "cron_expr", "interval_seconds",
                       "prompt", "is_active", "repeat", "last_run", "next_run",
                       "run_count", "max_runs", "metadata"):
                sets.append(f"{key} = ?")
                params.append(val)
        if not sets:
            return False
        sets.append("updated_at = ?")
        params.append(datetime.now(timezone.utc).isoformat())
        params.append(task_id)
        conn.execute(f"UPDATE scheduled_tasks SET {', '.join(sets)} WHERE id = ?", params)
        conn.commit()
        conn.close()
        return True

    def delete_task(self, task_id: str) -> bool:
        conn = self._conn()
        conn.execute("DELETE FROM scheduled_tasks WHERE id = ?", (task_id,))
        conn.execute("DELETE FROM task_runs WHERE task_id = ?", (task_id,))
        conn.commit()
        conn.close()
        return True

    def record_run(self, task_id: str, status: str = "running", result: str = None, error: str = None) -> str:
        run_id = f"run-{uuid.uuid4().hex[:8]}"
        now = datetime.now(timezone.utc).isoformat()
        conn = self._conn()
        conn.execute("""
            INSERT INTO task_runs (id, task_id, started_at, status, result, error)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (run_id, task_id, now, status, result, error))
        conn.commit()
        conn.close()
        return run_id

    def finish_run(self, run_id: str, status: str, result: str = None, error: str = None):
        now = datetime.now(timezone.utc).isoformat()
        conn = self._conn()
        conn.execute("""
            UPDATE task_runs SET finished_at = ?, status = ?, result = ?, error = ?
            WHERE id = ?
        """, (now, status, result, error, run_id))
        conn.commit()
        conn.close()

    def get_runs(self, task_id: str, limit: int = 20) -> List[Dict]:
        conn = self._conn()
        cur = conn.execute(
            "SELECT * FROM task_runs WHERE task_id = ? ORDER BY started_at DESC LIMIT ?",
            (task_id, limit)
        )
        cols = [d[0] for d in cur.description]
        rows = [dict(zip(cols, r)) for r in cur.fetchall()]
        conn.close()
        return rows


# ── Scheduler Engine ──

class TaskSchedulerEngine:
    """APScheduler-based task execution engine."""

    def __init__(self, store: TaskStore):
        self.store = store
        self._scheduler = None
        self._running = False
        self._task_executor = None  # Callback to execute a task prompt

    def set_executor(self, executor_fn):
        """Set the function that executes task prompts."""
        self._task_executor = executor_fn

    def start(self):
        """Start the scheduler."""
        try:
            from apscheduler.schedulers.background import BackgroundScheduler
            from apscheduler.triggers.cron import CronTrigger
            from apscheduler.triggers.interval import IntervalTrigger

            self._scheduler = BackgroundScheduler(
                timezone="UTC",
                job_defaults={"coalesce": True, "max_instances": 3},
            )
            self._scheduler.start()
            self._running = True

            # Load existing tasks
            tasks = self.store.list_tasks(active_only=True)
            for task in tasks:
                self._add_job(task)

            logger.info(f"[SCHEDULER] Started with {len(tasks)} active tasks")
        except Exception as e:
            logger.error(f"[SCHEDULER] Start failed: {e}")

    def stop(self):
        if self._scheduler:
            self._scheduler.shutdown(wait=False)
        self._running = False

    def _add_job(self, task: Dict):
        """Add a task to APScheduler."""
        if not self._scheduler:
            return

        try:
            from apscheduler.triggers.cron import CronTrigger
            from apscheduler.triggers.interval import IntervalTrigger

            task_id = task["id"]

            if task.get("schedule_type") == "cron" and task.get("cron_expr"):
                # Parse 6-field cron: sec min hour dom month dow
                fields = task["cron_expr"].split()
                if len(fields) == 6:
                    trigger = CronTrigger(
                        second=fields[0], minute=fields[1], hour=fields[2],
                        day=fields[3], month=fields[4], day_of_week=fields[5],
                    )
                elif len(fields) == 5:
                    trigger = CronTrigger(
                        minute=fields[0], hour=fields[1],
                        day=fields[2], month=fields[3], day_of_week=fields[4],
                    )
                else:
                    logger.warning(f"[SCHEDULER] Invalid cron: {task['cron_expr']}")
                    return

            elif task.get("schedule_type") == "interval" and task.get("interval_seconds"):
                trigger = IntervalTrigger(seconds=int(task["interval_seconds"]))
            else:
                logger.warning(f"[SCHEDULER] Unknown schedule type for {task_id}")
                return

            self._scheduler.add_job(
                self._execute_task,
                trigger=trigger,
                id=task_id,
                args=[task_id],
                replace_existing=True,
                name=task.get("name", task_id),
            )
            logger.info(f"[SCHEDULER] Added job {task_id}: {task.get('name')}")

        except Exception as e:
            logger.error(f"[SCHEDULER] Failed to add job {task.get('id')}: {e}")

    def _execute_task(self, task_id: str):
        """Execute a scheduled task."""
        task = self.store.get_task(task_id)
        if not task or not task.get("is_active"):
            return

        run_id = self.store.record_run(task_id, "running")
        logger.info(f"[SCHEDULER] Executing task {task_id}: {task.get('name')}")

        try:
            if self._task_executor:
                result = self._task_executor(task.get("prompt", ""), task)
                self.store.finish_run(run_id, "completed", result=str(result)[:5000])
            else:
                self.store.finish_run(run_id, "skipped", result="No executor configured")

            # Update task stats
            self.store.update_task(task_id, {
                "last_run": datetime.now(timezone.utc).isoformat(),
                "run_count": (task.get("run_count", 0) or 0) + 1,
            })

            # Check max_runs
            max_runs = task.get("max_runs", 0) or 0
            if max_runs > 0 and (task.get("run_count", 0) or 0) + 1 >= max_runs:
                self.store.update_task(task_id, {"is_active": 0})
                if self._scheduler:
                    self._scheduler.remove_job(task_id)

            # If not repeat, deactivate
            if not task.get("repeat"):
                self.store.update_task(task_id, {"is_active": 0})
                if self._scheduler:
                    try:
                        self._scheduler.remove_job(task_id)
                    except:
                        pass

        except Exception as e:
            logger.error(f"[SCHEDULER] Task {task_id} failed: {e}")
            self.store.finish_run(run_id, "failed", error=str(e))

    def schedule_task(self, task_data: Dict) -> Dict:
        """Create and schedule a new task."""
        result = self.store.create_task(task_data)
        task = self.store.get_task(result["id"])
        if task:
            self._add_job(task)
        return result

    def pause_task(self, task_id: str) -> bool:
        self.store.update_task(task_id, {"is_active": 0})
        if self._scheduler:
            try:
                self._scheduler.pause_job(task_id)
            except:
                pass
        return True

    def resume_task(self, task_id: str) -> bool:
        self.store.update_task(task_id, {"is_active": 1})
        task = self.store.get_task(task_id)
        if task and self._scheduler:
            self._add_job(task)
        return True


# ── Singleton ──
_store: Optional[TaskStore] = None
_engine: Optional[TaskSchedulerEngine] = None

def get_scheduler() -> TaskSchedulerEngine:
    global _store, _engine
    if _engine is None:
        _store = TaskStore()
        _engine = TaskSchedulerEngine(_store)
        _engine.start()
    return _engine

def get_task_store() -> TaskStore:
    global _store
    if _store is None:
        _store = TaskStore()
    return _store


# ── Flask Routes ──

def register_scheduler_routes(app: Flask):
    """Register task scheduler API routes."""
    from functools import wraps

    def require_auth(f):
        @wraps(f)
        def decorated(*args, **kwargs):
            if not getattr(request, "user_id", None):
                return jsonify({"error": "Unauthorized"}), 401
            return f(*args, **kwargs)
        return decorated

    @app.route("/api/scheduler/tasks", methods=["GET"])
    def list_scheduled_tasks():
        store = get_task_store()
        tasks = store.list_tasks(user_id=getattr(request, "user_id", "system"))
        return jsonify({"tasks": tasks, "count": len(tasks)})

    @app.route("/api/scheduler/tasks", methods=["POST"])
    def create_scheduled_task():
        data = request.get_json() or {}
        data["user_id"] = getattr(request, "user_id", "system")
        engine = get_scheduler()
        result = engine.schedule_task(data)
        return jsonify(result), 201

    @app.route("/api/scheduler/tasks/<task_id>", methods=["GET"])
    def get_scheduled_task(task_id):
        store = get_task_store()
        task = store.get_task(task_id)
        if not task:
            return jsonify({"error": "Not found"}), 404
        return jsonify(task)

    @app.route("/api/scheduler/tasks/<task_id>", methods=["PUT"])
    def update_scheduled_task(task_id):
        data = request.get_json() or {}
        store = get_task_store()
        store.update_task(task_id, data)
        return jsonify({"updated": True})

    @app.route("/api/scheduler/tasks/<task_id>", methods=["DELETE"])
    def delete_scheduled_task(task_id):
        store = get_task_store()
        store.delete_task(task_id)
        return jsonify({"deleted": True})

    @app.route("/api/scheduler/tasks/<task_id>/pause", methods=["POST"])
    def pause_scheduled_task(task_id):
        engine = get_scheduler()
        engine.pause_task(task_id)
        return jsonify({"paused": True})

    @app.route("/api/scheduler/tasks/<task_id>/resume", methods=["POST"])
    def resume_scheduled_task(task_id):
        engine = get_scheduler()
        engine.resume_task(task_id)
        return jsonify({"resumed": True})

    @app.route("/api/scheduler/tasks/<task_id>/runs", methods=["GET"])
    def get_task_runs(task_id):
        store = get_task_store()
        runs = store.get_runs(task_id)
        return jsonify({"runs": runs, "count": len(runs)})

    logger.info("[SCHEDULER] Routes registered")
