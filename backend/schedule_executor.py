"""
ORION Schedule Executor
=======================
Background scheduler that runs scheduled tasks using APScheduler.
Integrates with schedule_routes.py CRUD API.

Usage:
    from schedule_executor import init_scheduler
    init_scheduler(app)  # call once during app startup
"""

import os
import time
import logging
import secrets
import threading
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)

# APScheduler import with graceful fallback
try:
    from apscheduler.schedulers.background import BackgroundScheduler
    from apscheduler.triggers.cron import CronTrigger
    HAS_APSCHEDULER = True
except ImportError:
    HAS_APSCHEDULER = False
    logger.warning("[SCHEDULER] APScheduler not installed. Run: pip install apscheduler")

# ── Globals ──
_scheduler: Optional['BackgroundScheduler'] = None
_scheduler_lock = threading.Lock()


def _parse_cron_6field(cron_expr: str) -> dict:
    """Parse 6-field cron expression (sec min hour dom month dow) into APScheduler kwargs."""
    parts = cron_expr.strip().split()
    if len(parts) == 5:
        # Standard 5-field: min hour dom month dow
        return {
            "minute": parts[0],
            "hour": parts[1],
            "day": parts[2],
            "month": parts[3],
            "day_of_week": parts[4],
        }
    elif len(parts) == 6:
        # 6-field: sec min hour dom month dow
        return {
            "second": parts[0],
            "minute": parts[1],
            "hour": parts[2],
            "day": parts[3],
            "month": parts[4],
            "day_of_week": parts[5],
        }
    else:
        raise ValueError(f"Invalid cron expression: {cron_expr}")


def _execute_scheduled_task(task_id: str):
    """Execute a scheduled task by creating a chat and sending the prompt."""
    try:
        from shared import db_read, db_write, _now_iso

        db = db_read()
        tasks = db.get("scheduled_tasks", {})
        task = tasks.get(task_id)
        if not task:
            logger.warning(f"[SCHEDULER] Task {task_id} not found")
            return
        if task.get("status") == "paused":
            logger.info(f"[SCHEDULER] Task {task_id} is paused, skipping")
            return

        prompt = task.get("prompt", "")
        user_id = task.get("user_id", "")
        now = _now_iso()

        # Create run record
        run_id = "run_" + secrets.token_hex(6)
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
        task["total_runs"] = task.get("total_runs", 0) + 1

        history = task.get("run_history", [])
        history.insert(0, run_record)
        task["run_history"] = history[:50]

        db["scheduled_tasks"][task_id] = task
        db_write(db)

        logger.info(f"[SCHEDULER] Executing task {task_id}: {prompt[:80]}...")

        # Create a chat for this run
        chat_id = "sched_" + secrets.token_hex(8)
        chats = db.get("chats", {})
        chat = {
            "id": chat_id,
            "user_id": user_id,
            "title": f"[Scheduled] {task.get('title', 'Task')}",
            "messages": [
                {
                    "role": "user",
                    "content": prompt,
                    "timestamp": time.time(),
                }
            ],
            "created_at": now,
            "updated_at": now,
            "mode": "fast",
            "scheduled_task_id": task_id,
            "scheduled_run_id": run_id,
        }
        chats[chat_id] = chat
        db["chats"] = chats
        db_write(db)

        # Try to run the agent
        start_time = time.time()
        try:
            from agent_loop import AgentLoop
            agent = AgentLoop(
                chat_id=chat_id,
                user_id=user_id,
                model="openai/gpt-5.4-mini",
                mode="fast",
            )
            # Run synchronously (blocking) — in background thread
            for event in agent.run_stream(prompt):
                pass  # consume events

            duration = time.time() - start_time
            run_record["status"] = "success"
            run_record["duration_s"] = round(duration, 1)
            run_record["chat_id"] = chat_id
            task["last_run_status"] = "success"
            task["status"] = "active"
            logger.info(f"[SCHEDULER] Task {task_id} completed in {duration:.1f}s")

        except Exception as e:
            duration = time.time() - start_time
            run_record["status"] = "error"
            run_record["duration_s"] = round(duration, 1)
            run_record["error"] = str(e)[:500]
            task["last_run_status"] = "error"
            task["status"] = "active"
            logger.error(f"[SCHEDULER] Task {task_id} failed: {e}")

        # Update DB with results
        db = db_read()
        if task_id in db.get("scheduled_tasks", {}):
            db["scheduled_tasks"][task_id] = task
            db_write(db)

    except Exception as e:
        logger.error(f"[SCHEDULER] Fatal error executing task {task_id}: {e}")


def _sync_tasks_from_db():
    """Sync scheduled tasks from DB to APScheduler."""
    if not _scheduler:
        return

    try:
        from shared import db_read

        db = db_read()
        tasks = db.get("scheduled_tasks", {})

        # Get current APScheduler job IDs
        existing_jobs = {job.id for job in _scheduler.get_jobs()}

        for task_id, task in tasks.items():
            job_id = f"orion_sched_{task_id}"
            status = task.get("status", "active")
            cron_expr = task.get("cron", "")

            if status == "paused" or not cron_expr:
                # Remove job if paused
                if job_id in existing_jobs:
                    _scheduler.remove_job(job_id)
                    logger.info(f"[SCHEDULER] Removed paused job {job_id}")
                continue

            if job_id not in existing_jobs:
                try:
                    cron_kwargs = _parse_cron_6field(cron_expr)
                    _scheduler.add_job(
                        _execute_scheduled_task,
                        CronTrigger(**cron_kwargs),
                        id=job_id,
                        args=[task_id],
                        replace_existing=True,
                        misfire_grace_time=300,
                    )
                    logger.info(f"[SCHEDULER] Added job {job_id} with cron: {cron_expr}")
                except Exception as e:
                    logger.error(f"[SCHEDULER] Failed to add job {job_id}: {e}")

    except Exception as e:
        logger.error(f"[SCHEDULER] Sync failed: {e}")


def init_scheduler(app=None):
    """Initialize the background scheduler. Call once during app startup."""
    global _scheduler

    if not HAS_APSCHEDULER:
        logger.warning("[SCHEDULER] APScheduler not available, scheduled tasks disabled")
        return None

    with _scheduler_lock:
        if _scheduler is not None:
            return _scheduler

        _scheduler = BackgroundScheduler(
            daemon=True,
            job_defaults={
                'coalesce': True,
                'max_instances': 1,
                'misfire_grace_time': 300,
            }
        )

        # Add a periodic job to sync tasks from DB every 60 seconds
        _scheduler.add_job(
            _sync_tasks_from_db,
            'interval',
            seconds=60,
            id='orion_sync_tasks',
            replace_existing=True,
        )

        _scheduler.start()
        logger.info("[SCHEDULER] Background scheduler started")

        # Initial sync
        _sync_tasks_from_db()

        return _scheduler


def shutdown_scheduler():
    """Gracefully shutdown the scheduler."""
    global _scheduler
    if _scheduler:
        _scheduler.shutdown(wait=False)
        _scheduler = None
        logger.info("[SCHEDULER] Scheduler shutdown")
"""
Schedule Executor — ORION Digital
"""
