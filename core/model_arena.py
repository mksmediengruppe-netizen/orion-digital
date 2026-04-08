"""
ARCANE 3.0 — Model Arena
==========================
"Dog Racing" — competitive model evaluation + passive learning.

Two modes:
  1. Dog Racing (initial): run 10 tasks × 4 models, score, build leaderboard
  2. Passive Learning: record metrics after every real task, update leaderboard

Scoring uses PROXY METRICS (no LLM judge — that would negate savings):
  - lint_errors = 0         (20% weight)
  - validate_html = PASS    (15% weight)
  - retry_count = 0         (15% weight)
  - cost_usd               (25% weight) — lower is better
  - duration_seconds        (10% weight) — lower is better
  - files_not_empty         (15% weight)

After 50+ real tasks, AUTO mode picks models from leaderboard data.

Usage:
    arena = ModelArena(db_path="/workspace/.arcane_arena.db")
    
    # Record after every task
    arena.record(task_type="web_design", role="developer", model_id="claude-sonnet-4.6",
                 lint_errors=0, html_valid=True, retry_count=0,
                 cost_usd=0.12, duration_seconds=45, files_created=3)
    
    # Get best model for a role
    best = arena.get_best("web_design", "developer")
    # → "claude-sonnet-4.6" (score 92.5)
    
    # Run dog racing
    results = await arena.run_dog_race(tasks=[...], models=[...])
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger("arcane.model_arena")


# ═══════════════════════════════════════════════════════════════════════════════
# SCORING WEIGHTS — proxy metrics, no LLM judge
# ═══════════════════════════════════════════════════════════════════════════════

SCORE_WEIGHTS = {
    "lint_clean":       0.20,   # lint_errors == 0
    "html_valid":       0.15,   # validate_html == PASS
    "no_retries":       0.15,   # retry_count == 0
    "cost_efficiency":  0.25,   # lower cost = higher score
    "speed":            0.10,   # lower duration = higher score
    "files_created":    0.15,   # files > 0 and not empty
}


@dataclass
class ArenaRecord:
    """Single task execution record for scoring."""
    task_type: str
    role: str
    model_id: str
    
    # Proxy metrics
    lint_errors: int = 0
    html_valid: bool = True
    retry_count: int = 0
    cost_usd: float = 0.0
    duration_seconds: float = 0.0
    files_created: int = 0
    
    # Metadata
    timestamp: float = field(default_factory=time.time)
    project_id: str = ""
    run_id: str = ""
    
    @property
    def score(self) -> float:
        """Calculate weighted score (0-100)."""
        s = 0.0
        s += SCORE_WEIGHTS["lint_clean"] * (100 if self.lint_errors == 0 else max(0, 50 - self.lint_errors * 10))
        s += SCORE_WEIGHTS["html_valid"] * (100 if self.html_valid else 0)
        s += SCORE_WEIGHTS["no_retries"] * (100 if self.retry_count == 0 else max(0, 100 - self.retry_count * 30))
        
        # Cost: $0 = 100, $1+ = 0, linear between
        cost_score = max(0, 100 - self.cost_usd * 100)
        s += SCORE_WEIGHTS["cost_efficiency"] * cost_score
        
        # Speed: <10s = 100, >120s = 0, linear
        speed_score = max(0, 100 - (self.duration_seconds - 10) * (100 / 110))
        s += SCORE_WEIGHTS["speed"] * max(0, min(100, speed_score))
        
        # Files: >0 = 100, 0 = 0
        s += SCORE_WEIGHTS["files_created"] * (100 if self.files_created > 0 else 0)
        
        return round(s, 1)


class ModelArena:
    """
    Model evaluation and selection system.
    
    Records performance metrics after every task.
    Builds leaderboard for AUTO mode model selection.
    """

    def __init__(self, db_path: str | None = None):
        workspace = os.environ.get("ARCANE_WORKSPACE", "/root/workspace")
        self.db_path = db_path or os.path.join(workspace, ".arcane_arena.db")
        self._init_db()

    def _init_db(self):
        """Initialize SQLite database for arena records."""
        db_dir = os.path.dirname(self.db_path)
        if db_dir:  # BUG-4 FIX: os.makedirs("") crashes
            os.makedirs(db_dir, exist_ok=True)
        conn = sqlite3.connect(self.db_path)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS arena_records (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_type TEXT NOT NULL,
                role TEXT NOT NULL,
                model_id TEXT NOT NULL,
                lint_errors INTEGER DEFAULT 0,
                html_valid INTEGER DEFAULT 1,
                retry_count INTEGER DEFAULT 0,
                cost_usd REAL DEFAULT 0,
                duration_seconds REAL DEFAULT 0,
                files_created INTEGER DEFAULT 0,
                score REAL DEFAULT 0,
                timestamp REAL DEFAULT 0,
                project_id TEXT DEFAULT '',
                run_id TEXT DEFAULT ''
            )
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_arena_task_role 
            ON arena_records(task_type, role, model_id)
        """)
        conn.commit()
        conn.close()

    def record(
        self,
        task_type: str,
        role: str,
        model_id: str,
        lint_errors: int = 0,
        html_valid: bool = True,
        retry_count: int = 0,
        cost_usd: float = 0.0,
        duration_seconds: float = 0.0,
        files_created: int = 0,
        project_id: str = "",
        run_id: str = "",
    ) -> float:
        """Record a task execution result. Returns calculated score."""
        rec = ArenaRecord(
            task_type=task_type, role=role, model_id=model_id,
            lint_errors=lint_errors, html_valid=html_valid,
            retry_count=retry_count, cost_usd=cost_usd,
            duration_seconds=duration_seconds, files_created=files_created,
            project_id=project_id, run_id=run_id,
        )
        score = rec.score
        
        conn = sqlite3.connect(self.db_path)
        conn.execute(
            """INSERT INTO arena_records 
               (task_type, role, model_id, lint_errors, html_valid, retry_count,
                cost_usd, duration_seconds, files_created, score, timestamp,
                project_id, run_id)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (task_type, role, model_id, lint_errors, int(html_valid),
             retry_count, cost_usd, duration_seconds, files_created,
             score, time.time(), project_id, run_id)
        )
        conn.commit()
        conn.close()
        
        logger.info(
            f"Arena: {model_id} [{role}/{task_type}] score={score:.1f} "
            f"(lint={lint_errors}, valid={html_valid}, retry={retry_count}, "
            f"${cost_usd:.3f}, {duration_seconds:.0f}s)"
        )
        return score

    def get_best(
        self,
        task_type: str,
        role: str,
        min_records: int = 3,
    ) -> tuple[str, float] | None:
        """Get best model for a task_type + role combination.
        
        Returns (model_id, avg_score) or None if not enough data.
        Requires at least min_records entries for statistical significance.
        """
        conn = sqlite3.connect(self.db_path)
        rows = conn.execute(
            """SELECT model_id, AVG(score) as avg_score, COUNT(*) as cnt
               FROM arena_records
               WHERE task_type = ? AND role = ?
               GROUP BY model_id
               HAVING cnt >= ?
               ORDER BY avg_score DESC
               LIMIT 1""",
            (task_type, role, min_records)
        ).fetchall()
        conn.close()
        
        if rows:
            return (rows[0][0], round(rows[0][1], 1))
        return None

    def get_leaderboard(
        self,
        task_type: str | None = None,
        role: str | None = None,
        limit: int = 10,
    ) -> list[dict]:
        """Get leaderboard: models ranked by average score.
        
        Can filter by task_type and/or role.
        """
        conn = sqlite3.connect(self.db_path)
        
        where_parts = []
        params = []
        if task_type:
            where_parts.append("task_type = ?")
            params.append(task_type)
        if role:
            where_parts.append("role = ?")
            params.append(role)
        
        where = f"WHERE {' AND '.join(where_parts)}" if where_parts else ""
        
        rows = conn.execute(
            f"""SELECT model_id, AVG(score) as avg_score, COUNT(*) as cnt,
                       AVG(cost_usd) as avg_cost, AVG(duration_seconds) as avg_time
                FROM arena_records
                {where}
                GROUP BY model_id
                ORDER BY avg_score DESC
                LIMIT ?""",
            (*params, limit)
        ).fetchall()
        conn.close()
        
        return [
            {
                "model_id": r[0],
                "avg_score": round(r[1], 1),
                "tasks_completed": r[2],
                "avg_cost_usd": round(r[3], 4),
                "avg_duration_s": round(r[4], 1),
            }
            for r in rows
        ]

    def get_leaderboard_for_preset(self) -> dict[str, list[tuple[str, float]]]:
        """Get leaderboard in format expected by PresetManager.
        
        Returns: {category: [(model_id, score), ...]}
        """
        conn = sqlite3.connect(self.db_path)
        rows = conn.execute(
            """SELECT role, model_id, AVG(score) as avg_score, COUNT(*) as cnt
               FROM arena_records
               GROUP BY role, model_id
               HAVING cnt >= 3
               ORDER BY role, avg_score DESC"""
        ).fetchall()
        conn.close()
        
        # Map roles to leaderboard categories
        _role_to_category = {
            "director": "planning",
            "art_director": "design",
            "developer": "code",
            "writer": "content",
            "researcher": "research",
            "qa": "code_review",
            "image_agent": "image",    # BUG-5 FIX: was missing
        }
        
        # Backward compat: canonicalize old role names
        _role_aliases = {
            "classifier": "director", "planner": "director", "orchestrator": "director",
            "coding": "developer", "coder": "developer", "designer": "art_director",
            "ssh": "developer", "browser": "developer", "search": "researcher",
        }
        
        result: dict[str, list[tuple[str, float]]] = {}
        for role, model_id, avg_score, cnt in rows:
            # Canonicalize old role names
            role = _role_aliases.get(role, role)
            cat = _role_to_category.get(role, role)
            if cat not in result:
                result[cat] = []
            result[cat].append((model_id, round(avg_score, 1)))
        
        return result

    def get_stats(self) -> dict:
        """Get overall arena statistics."""
        conn = sqlite3.connect(self.db_path)
        total = conn.execute("SELECT COUNT(*) FROM arena_records").fetchone()[0]
        models = conn.execute("SELECT COUNT(DISTINCT model_id) FROM arena_records").fetchone()[0]
        avg_score = conn.execute("SELECT AVG(score) FROM arena_records").fetchone()[0]
        conn.close()
        
        return {
            "total_records": total,
            "unique_models": models,
            "avg_score": round(avg_score, 1) if avg_score else 0,
            "auto_mode_ready": total >= 50,
        }
