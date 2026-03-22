"""
ORION Digital — Persistent Runtime State (TASK 12)
Stores running task state in SQLite so it survives process restarts.
In-memory dict (_running_tasks) is the primary fast store;
SQLite is the persistent backup that syncs on key events.
"""
import sqlite3, json, logging, threading, os, time
from datetime import datetime

logger = logging.getLogger("orion.runtime_state")

class RuntimeStateStore:
    """Persistent store for task runtime state."""

    def __init__(self, db_path=None):
        if db_path is None:
            db_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "database.sqlite")
        self._db_path = db_path
        self._lock = threading.Lock()
        self._init_table()

    def _get_conn(self):
        try:
            from database import _get_conn
            return _get_conn()
        except Exception:
            conn = sqlite3.connect(self._db_path, check_same_thread=False, timeout=10)
            conn.execute("PRAGMA journal_mode=WAL")
            return conn

    def _init_table(self):
        conn = self._get_conn()
        try:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS runtime_tasks (
                    chat_id TEXT PRIMARY KEY,
                    task_id TEXT DEFAULT '',
                    user_id TEXT DEFAULT '',
                    orion_mode TEXT DEFAULT 'turbo',
                    status TEXT DEFAULT 'running',
                    iteration INTEGER DEFAULT 0,
                    last_tool TEXT DEFAULT '',
                    task_cost REAL DEFAULT 0.0,
                    user_message TEXT DEFAULT '',
                    started_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    metadata TEXT DEFAULT '{}'
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_rt_status ON runtime_tasks(status)
            """)
            conn.commit()
        finally:
            conn.close()

    def register_task(self, chat_id: str, task_id: str = "", user_id: str = "",
                      orion_mode: str = "turbo", user_message: str = ""):
        """Register a new running task."""
        now = datetime.utcnow().isoformat()
        conn = self._get_conn()
        try:
            conn.execute("""
                INSERT OR REPLACE INTO runtime_tasks
                (chat_id, task_id, user_id, orion_mode, status, iteration,
                 user_message, started_at, updated_at)
                VALUES (?, ?, ?, ?, 'running', 0, ?, ?, ?)
            """, (chat_id, task_id, user_id, orion_mode, user_message[:500], now, now))
            conn.commit()
            logger.debug(f"[RuntimeState] Registered task: chat={chat_id}")
        except Exception as e:
            logger.debug(f"[RuntimeState] register error: {e}")
        finally:
            conn.close()

    def update_task(self, chat_id: str, iteration: int = None,
                    last_tool: str = None, task_cost: float = None,
                    status: str = None, metadata: dict = None):
        """Update running task state."""
        now = datetime.utcnow().isoformat()
        conn = self._get_conn()
        try:
            updates = ["updated_at = ?"]
            params = [now]
            if iteration is not None:
                updates.append("iteration = ?")
                params.append(iteration)
            if last_tool is not None:
                updates.append("last_tool = ?")
                params.append(last_tool)
            if task_cost is not None:
                updates.append("task_cost = ?")
                params.append(task_cost)
            if status is not None:
                updates.append("status = ?")
                params.append(status)
            if metadata is not None:
                updates.append("metadata = ?")
                params.append(json.dumps(metadata, ensure_ascii=False))
            params.append(chat_id)
            conn.execute(
                f"UPDATE runtime_tasks SET {', '.join(updates)} WHERE chat_id = ?",
                params
            )
            conn.commit()
        except Exception as e:
            logger.debug(f"[RuntimeState] update error: {e}")
        finally:
            conn.close()

    def complete_task(self, chat_id: str):
        """Mark task as completed."""
        self.update_task(chat_id, status="completed")
        logger.debug(f"[RuntimeState] Task completed: chat={chat_id}")

    def fail_task(self, chat_id: str, reason: str = ""):
        """Mark task as failed."""
        self.update_task(chat_id, status="failed", metadata={"fail_reason": reason})
        logger.debug(f"[RuntimeState] Task failed: chat={chat_id}: {reason}")

    def get_task(self, chat_id: str) -> dict:
        """Get task state."""
        conn = self._get_conn()
        try:
            row = conn.execute(
                "SELECT * FROM runtime_tasks WHERE chat_id = ?", (chat_id,)
            ).fetchone()
            if row:
                cols = [d[0] for d in conn.execute("SELECT * FROM runtime_tasks LIMIT 0").description]
                return dict(zip(cols, row))
        except Exception as e:
            logger.debug(f"[RuntimeState] get error: {e}")
        finally:
            conn.close()
        return {}

    def get_running_tasks(self) -> list:
        """Get all currently running tasks."""
        conn = self._get_conn()
        try:
            rows = conn.execute(
                "SELECT * FROM runtime_tasks WHERE status = 'running' ORDER BY updated_at DESC"
            ).fetchall()
            if rows:
                cols = [d[0] for d in conn.execute("SELECT * FROM runtime_tasks LIMIT 0").description]
                return [dict(zip(cols, r)) for r in rows]
        except Exception as e:
            logger.debug(f"[RuntimeState] get_running error: {e}")
        finally:
            conn.close()
        return []

    def cleanup_stale(self, max_age_hours: int = 24):
        """Mark old running tasks as stale (probably crashed)."""
        from datetime import timedelta
        cutoff = (datetime.utcnow() - timedelta(hours=max_age_hours)).isoformat()
        conn = self._get_conn()
        try:
            cursor = conn.execute(
                "UPDATE runtime_tasks SET status = 'stale' WHERE status = 'running' AND updated_at < ?",
                (cutoff,)
            )
            if cursor.rowcount > 0:
                logger.warning(f"[RuntimeState] Marked {cursor.rowcount} stale tasks")
            conn.commit()
        except Exception as e:
            logger.debug(f"[RuntimeState] cleanup error: {e}")
        finally:
            conn.close()

    def get_stats(self) -> dict:
        """Get runtime statistics."""
        conn = self._get_conn()
        try:
            stats = {}
            for status in ['running', 'completed', 'failed', 'stale']:
                row = conn.execute(
                    "SELECT COUNT(*) FROM runtime_tasks WHERE status = ?", (status,)
                ).fetchone()
                stats[status] = row[0] if row else 0
            return stats
        except Exception as e:
            logger.debug(f"[RuntimeState] stats error: {e}")
        finally:
            conn.close()
        return {}


# ── Singleton ──
_instance = None
_instance_lock = threading.Lock()

def get_runtime_state(**kwargs) -> RuntimeStateStore:
    global _instance
    if _instance is None:
        with _instance_lock:
            if _instance is None:
                _instance = RuntimeStateStore(**kwargs)
    return _instance
