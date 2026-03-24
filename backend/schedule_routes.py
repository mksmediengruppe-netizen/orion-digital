"""
ORION Schedule Routes
=====================
REST API for scheduled tasks management.
Endpoints:
  GET    /api/schedule          — list all scheduled tasks (for current user)
  POST   /api/schedule          — create a new scheduled task
  GET    /api/schedule/<id>     — get task details + run history
  PUT    /api/schedule/<id>     — update task (cron, prompt, status)
  DELETE /api/schedule/<id>     — delete task
  POST   /api/schedule/<id>/run — trigger immediate run
  POST   /api/schedule/<id>/toggle — pause/resume task
"""

import logging
import secrets

from flask import Blueprint, request, jsonify

from shared import (
    require_auth, require_admin, db_read, db_write, _now_iso
)

logger = logging.getLogger(__name__)

schedule_bp = Blueprint("schedule", __name__)

# ─── DB helpers ───────────────────────────────────────────────────────────────

def _ensure_schedule_tables():
    """Ensure scheduled_tasks table exists in the DB dict."""
    db = db_read()
    if "scheduled_tasks" not in db:
        db["scheduled_tasks"] = {}
        db_write(db)



def _new_id():
    return "st_" + secrets.token_hex(8)


# ─── List ─────────────────────────────────────────────────────────────────────

@schedule_bp.route("/api/schedule", methods=["GET"])
@require_auth
def list_schedule():
    """Return all scheduled tasks for the current user (admins see all)."""
    _ensure_schedule_tables()
    db = db_read()
    tasks = db.get("scheduled_tasks", {})
    user = request.user
    is_admin = user.get("role") == "admin"

    result = []
    for task in tasks.values():
        if not is_admin and task.get("user_id") != request.user_id:
            continue
        result.append(_task_summary(task))

    # Sort by created_at desc
    result.sort(key=lambda t: t.get("created_at", ""), reverse=True)
    return jsonify({"tasks": result})


# ─── Create ───────────────────────────────────────────────────────────────────

@schedule_bp.route("/api/schedule", methods=["POST"])
@require_auth
def create_schedule():
    """Create a new scheduled task."""
    _ensure_schedule_tables()
    data = request.get_json(force=True) or {}

    title = (data.get("title") or "").strip()
    prompt = (data.get("prompt") or "").strip()
    cron = (data.get("cron") or "").strip()
    category = (data.get("category") or "Общее").strip()

    if not title:
        return jsonify({"error": "title is required"}), 400
    if not prompt:
        return jsonify({"error": "prompt is required"}), 400
    if not cron:
        return jsonify({"error": "cron expression is required"}), 400

    task_id = _new_id()
    now = _now_iso()
    task = {
        "id": task_id,
        "user_id": request.user_id,
        "title": title,
        "prompt": prompt,
        "cron": cron,
        "category": category,
        "status": "active",
        "total_runs": 0,
        "total_cost": 0.0,
        "avg_cost": 0.0,
        "last_run_at": None,
        "last_run_status": None,
        "next_run_at": None,
        "run_history": [],
        "created_at": now,
        "updated_at": now,
    }

    db = db_read()
    if "scheduled_tasks" not in db:
        db["scheduled_tasks"] = {}
    db["scheduled_tasks"][task_id] = task
    db_write(db)

    logger.info(f"[schedule] Created task {task_id} by user {request.user_id}")
    return jsonify({"ok": True, "task": _task_summary(task)}), 201


# ─── Get detail ───────────────────────────────────────────────────────────────

@schedule_bp.route("/api/schedule/<task_id>", methods=["GET"])
@require_auth
def get_schedule(task_id):
    """Get full task details including run history."""
    _ensure_schedule_tables()
    db = db_read()
    task = db.get("scheduled_tasks", {}).get(task_id)
    if not task:
        return jsonify({"error": "Task not found"}), 404

    user = request.user
    is_admin = user.get("role") == "admin"
    if not is_admin and task.get("user_id") != request.user_id:
        return jsonify({"error": "Forbidden"}), 403

    return jsonify({"task": _task_detail(task)})


# ─── Update ───────────────────────────────────────────────────────────────────

@schedule_bp.route("/api/schedule/<task_id>", methods=["PUT"])
@require_auth
def update_schedule(task_id):
    """Update task fields (title, prompt, cron, category, status)."""
    _ensure_schedule_tables()
    db = db_read()
    tasks = db.get("scheduled_tasks", {})
    task = tasks.get(task_id)
    if not task:
        return jsonify({"error": "Task not found"}), 404

    user = request.user
    is_admin = user.get("role") == "admin"
    if not is_admin and task.get("user_id") != request.user_id:
        return jsonify({"error": "Forbidden"}), 403

    data = request.get_json(force=True) or {}
    allowed = ["title", "prompt", "cron", "category", "status"]
    for field in allowed:
        if field in data:
            task[field] = data[field]
    task["updated_at"] = _now_iso()

    db["scheduled_tasks"][task_id] = task
    db_write(db)

    logger.info(f"[schedule] Updated task {task_id}")
    return jsonify({"ok": True, "task": _task_summary(task)})


# ─── Delete ───────────────────────────────────────────────────────────────────

@schedule_bp.route("/api/schedule/<task_id>", methods=["DELETE"])
@require_auth
def delete_schedule(task_id):
    """Delete a scheduled task."""
    _ensure_schedule_tables()
    db = db_read()
    tasks = db.get("scheduled_tasks", {})
    task = tasks.get(task_id)
    if not task:
        return jsonify({"error": "Task not found"}), 404

    user = request.user
    is_admin = user.get("role") == "admin"
    if not is_admin and task.get("user_id") != request.user_id:
        return jsonify({"error": "Forbidden"}), 403

    del db["scheduled_tasks"][task_id]
    db_write(db)

    logger.info(f"[schedule] Deleted task {task_id}")
    return jsonify({"ok": True})


# ─── Toggle (pause / resume) ──────────────────────────────────────────────────

@schedule_bp.route("/api/schedule/<task_id>/toggle", methods=["POST"])
@require_auth
def toggle_schedule(task_id):
    """Pause or resume a scheduled task."""
    _ensure_schedule_tables()
    db = db_read()
    tasks = db.get("scheduled_tasks", {})
    task = tasks.get(task_id)
    if not task:
        return jsonify({"error": "Task not found"}), 404

    user = request.user
    is_admin = user.get("role") == "admin"
    if not is_admin and task.get("user_id") != request.user_id:
        return jsonify({"error": "Forbidden"}), 403

    current = task.get("status", "active")
    if current in ("active", "running"):
        task["status"] = "paused"
    else:
        task["status"] = "active"
    task["updated_at"] = _now_iso()

    db["scheduled_tasks"][task_id] = task
    db_write(db)

    return jsonify({"ok": True, "status": task["status"]})


# ─── Run now ──────────────────────────────────────────────────────────────────

@schedule_bp.route("/api/schedule/<task_id>/run", methods=["POST"])
@require_auth
def run_schedule_now(task_id):
    """Trigger an immediate run of a scheduled task (creates a chat)."""
    _ensure_schedule_tables()
    db = db_read()
    tasks = db.get("scheduled_tasks", {})
    task = tasks.get(task_id)
    if not task:
        return jsonify({"error": "Task not found"}), 404

    user = request.user
    is_admin = user.get("role") == "admin"
    if not is_admin and task.get("user_id") != request.user_id:
        return jsonify({"error": "Forbidden"}), 403

    # Create a run record
    run_id = "run_" + secrets.token_hex(6)
    now = _now_iso()
    run_record = {
        "id": run_id,
        "started_at": now,
        "status": "running",
        "cost": 0.0,
        "chat_id": None,
        "duration_s": None,
    }

    task["status"] = "running"
    task["last_run_at"] = now
    task["last_run_status"] = "running"
    task["updated_at"] = now

    history = task.get("run_history", [])
    history.insert(0, run_record)
    task["run_history"] = history[:50]  # keep last 50

    db["scheduled_tasks"][task_id] = task
    db_write(db)

    logger.info(f"[schedule] Manual run triggered for task {task_id}, run {run_id}")
    return jsonify({"ok": True, "run_id": run_id, "task": _task_summary(task)})


# ─── Admin: all tasks ─────────────────────────────────────────────────────────

@schedule_bp.route("/api/admin/schedule", methods=["GET"])
@require_auth
@require_admin
def admin_list_schedule():
    """Admin: list all scheduled tasks across all users."""
    _ensure_schedule_tables()
    db = db_read()
    tasks = db.get("scheduled_tasks", {})
    result = [_task_detail(t) for t in tasks.values()]
    result.sort(key=lambda t: t.get("created_at", ""), reverse=True)
    return jsonify({"tasks": result, "total": len(result)})


# ─── Serializers ──────────────────────────────────────────────────────────────

def _task_summary(task: dict) -> dict:
    """Light summary for list view."""
    return {
        "id": task["id"],
        "title": task["title"],
        "category": task.get("category", "Общее"),
        "cron": task["cron"],
        "status": task.get("status", "active"),
        "total_runs": task.get("total_runs", 0),
        "total_cost": task.get("total_cost", 0.0),
        "avg_cost": task.get("avg_cost", 0.0),
        "last_run_at": task.get("last_run_at"),
        "last_run_status": task.get("last_run_status"),
        "next_run_at": task.get("next_run_at"),
        "created_at": task.get("created_at"),
        "updated_at": task.get("updated_at"),
    }


def _task_detail(task: dict) -> dict:
    """Full detail including prompt and run history."""
    summary = _task_summary(task)
    summary["prompt"] = task.get("prompt", "")
    summary["run_history"] = task.get("run_history", [])
    summary["user_id"] = task.get("user_id", "")
    return summary
