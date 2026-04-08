"""
task_history_db.py — Persistent SQLite storage for Arcane task run history.
Stores completed/failed runs so they survive service restarts.
"""
import sqlite3
import json
import time
import os
import threading
from pathlib import Path
from typing import Optional


class TaskHistoryDB:
    """Thread-safe SQLite-backed task history store."""

    def __init__(self, db_path: str = "/root/workspace/.arcane_history.db"):
        self.db_path = db_path
        self._lock = threading.Lock()
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        return conn

    def _init_db(self):
        """Create tables if they don't exist."""
        with self._lock:
            with self._connect() as conn:
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS task_runs (
                        run_id       TEXT PRIMARY KEY,
                        project_id   TEXT NOT NULL,
                        project_name TEXT,
                        task         TEXT,
                        status       TEXT,
                        task_type    TEXT,
                        complexity   TEXT,
                        mode         TEXT,
                        model        TEXT,
                        output       TEXT,
                        actual_cost  REAL DEFAULT 0.0,
                        duration_sec REAL DEFAULT 0.0,
                        started_at   REAL,
                        finished_at  REAL,
                        errors       TEXT,
                        artifacts    TEXT,
                        full_json    TEXT,
                        created_at   REAL DEFAULT (unixepoch())
                    )
                """)
                conn.execute("""
                    CREATE INDEX IF NOT EXISTS idx_project_id ON task_runs(project_id)
                """)
                conn.execute("""
                    CREATE INDEX IF NOT EXISTS idx_status ON task_runs(status)
                """)
                conn.execute("""
                    CREATE INDEX IF NOT EXISTS idx_started_at ON task_runs(started_at DESC)
                """)
                conn.commit()

    def save_run(self, run_dict: dict, project_name: str = ""):
        """Persist a completed run to SQLite. Upserts on run_id."""
        run_id = run_dict.get("run_id", "")
        if not run_id:
            return

        # Extract primary model from team dict
        team = run_dict.get("team", {})
        model = ""
        if isinstance(team, dict):
            model = team.get("coder") or team.get("orchestrator") or next(iter(team.values()), "")

        with self._lock:
            try:
                with self._connect() as conn:
                    conn.execute("""
                        INSERT OR REPLACE INTO task_runs
                            (run_id, project_id, project_name, task, status, task_type,
                             complexity, mode, model, output, actual_cost, duration_sec,
                             started_at, finished_at, errors, artifacts, full_json, created_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        run_id,
                        run_dict.get("project_id", ""),
                        project_name,
                        run_dict.get("task", "")[:500],
                        run_dict.get("status", ""),
                        run_dict.get("task_type", ""),
                        run_dict.get("complexity", ""),
                        run_dict.get("mode", ""),
                        model,
                        run_dict.get("output", "")[:2000],
                        float(run_dict.get("actual_cost", 0.0)),
                        float(run_dict.get("duration_seconds", 0.0)),
                        float(run_dict.get("started_at", 0.0)),
                        float(run_dict.get("finished_at", 0.0)),
                        json.dumps(run_dict.get("errors", [])),
                        json.dumps(run_dict.get("artifacts", [])),
                        json.dumps(run_dict),
                        float(run_dict.get("started_at", time.time())),
                    ))
                    conn.commit()
            except Exception as e:
                import logging
                logging.getLogger(__name__).error(f"TaskHistoryDB.save_run error: {e}")

    def get_all(self, limit: int = 500, project_id: Optional[str] = None) -> list[dict]:
        """Return runs sorted by started_at desc."""
        with self._lock:
            try:
                with self._connect() as conn:
                    if project_id:
                        rows = conn.execute(
                            "SELECT full_json, project_name FROM task_runs WHERE project_id = ? ORDER BY started_at DESC LIMIT ?",
                            (project_id, limit)
                        ).fetchall()
                    else:
                        rows = conn.execute(
                            "SELECT full_json, project_name FROM task_runs ORDER BY started_at DESC LIMIT ?",
                            (limit,)
                        ).fetchall()

                    results = []
                    for row in rows:
                        try:
                            d = json.loads(row["full_json"])
                            d["project_name"] = row["project_name"] or d.get("project_id", "")
                            results.append(d)
                        except Exception:
                            pass
                    return results
            except Exception as e:
                import logging
                logging.getLogger(__name__).error(f"TaskHistoryDB.get_all error: {e}")
                return []

    def get_stats(self) -> dict:
        """Return aggregate stats for admin dashboard."""
        with self._lock:
            try:
                with self._connect() as conn:
                    row = conn.execute("""
                        SELECT
                            COUNT(*) as total,
                            SUM(CASE WHEN status='done' THEN 1 ELSE 0 END) as done,
                            SUM(CASE WHEN status='failed' THEN 1 ELSE 0 END) as failed,
                            SUM(actual_cost) as total_cost,
                            AVG(duration_sec) as avg_duration
                        FROM task_runs
                    """).fetchone()
                    return dict(row) if row else {}
            except Exception:
                return {}
