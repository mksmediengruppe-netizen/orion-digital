"""
ORION Digital — Crash Recovery Module (TASK 10)
Watchdog for stale tasks + persistent checkpoints in SQLite + auto-restart.
"""
import threading, time, logging, json, sqlite3, os
from datetime import datetime, timedelta

logger = logging.getLogger("orion.crash_recovery")

_STALE_TIMEOUT_SECONDS = 600  # 10 min without heartbeat = stale
_WATCHDOG_INTERVAL = 30       # check every 30s
_MAX_AUTO_RESTARTS = 2        # max restarts per task

class CrashRecovery:
    """Manages crash detection, persistent checkpoints, and auto-restart."""

    def __init__(self, db_path=None):
        if db_path is None:
            db_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "database.sqlite")
        self._db_path = db_path
        self._init_tables()
        self._watchdog_thread = None
        self._running = False
        self._on_stale_callback = None  # set externally
        self._lock = threading.Lock()

    def _get_conn(self):
        try:
            from database import _get_conn
            return _get_conn()
        except Exception:
            conn = sqlite3.connect(self._db_path, check_same_thread=False, timeout=10)
            conn.execute("PRAGMA journal_mode=WAL")
            return conn

    def _init_tables(self):
        conn = self._get_conn()
        try:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS task_checkpoints (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_id TEXT NOT NULL,
                    chat_id TEXT NOT NULL,
                    iteration INTEGER DEFAULT 0,
                    last_tool TEXT DEFAULT '',
                    actions_count INTEGER DEFAULT 0,
                    task_cost REAL DEFAULT 0.0,
                    messages_snapshot TEXT DEFAULT '[]',
                    user_message TEXT DEFAULT '',
                    orion_mode TEXT DEFAULT 'turbo',
                    heartbeat_at TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    status TEXT DEFAULT 'active',
                    restart_count INTEGER DEFAULT 0
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_cp_chat ON task_checkpoints(chat_id)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_cp_status ON task_checkpoints(status)
            """)
            conn.commit()
        finally:
            conn.close()

    # ── Checkpoint CRUD ──

    def save_checkpoint(self, task_id: str, chat_id: str, iteration: int,
                        last_tool: str, actions_count: int, task_cost: float,
                        user_message: str = "", orion_mode: str = "turbo",
                        messages_snapshot: str = "[]"):
        """Save or update checkpoint for a running task."""
        now = datetime.utcnow().isoformat()
        conn = self._get_conn()
        try:
            existing = conn.execute(
                "SELECT id FROM task_checkpoints WHERE chat_id = ? AND status = 'active'",
                (chat_id,)
            ).fetchone()
            if existing:
                conn.execute("""
                    UPDATE task_checkpoints
                    SET iteration = ?, last_tool = ?, actions_count = ?,
                        task_cost = ?, heartbeat_at = ?, messages_snapshot = ?
                    WHERE id = ?
                """, (iteration, last_tool, actions_count, task_cost, now,
                      messages_snapshot, existing[0]))
            else:
                conn.execute("""
                    INSERT INTO task_checkpoints
                    (task_id, chat_id, iteration, last_tool, actions_count,
                     task_cost, user_message, orion_mode, heartbeat_at, created_at, status)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'active')
                """, (task_id, chat_id, iteration, last_tool, actions_count,
                      task_cost, user_message, orion_mode, now, now))
            conn.commit()
        except Exception as e:
            logger.debug(f"[CrashRecovery] save_checkpoint error: {e}")
        finally:
            conn.close()

    def heartbeat(self, chat_id: str):
        """Update heartbeat timestamp for active task."""
        now = datetime.utcnow().isoformat()
        conn = self._get_conn()
        try:
            conn.execute(
                "UPDATE task_checkpoints SET heartbeat_at = ? WHERE chat_id = ? AND status = 'active'",
                (now, chat_id)
            )
            conn.commit()
        except Exception as e:
            logger.debug(f"[CrashRecovery] heartbeat error: {e}")
        finally:
            conn.close()

    def load_checkpoint(self, chat_id: str) -> dict:
        """Load latest active checkpoint for a chat."""
        conn = self._get_conn()
        try:
            row = conn.execute(
                "SELECT * FROM task_checkpoints WHERE chat_id = ? AND status = 'active' ORDER BY id DESC LIMIT 1",
                (chat_id,)
            ).fetchone()
            if row:
                cols = [d[0] for d in conn.execute("SELECT * FROM task_checkpoints LIMIT 0").description]
                return dict(zip(cols, row))
        except Exception as e:
            logger.debug(f"[CrashRecovery] load_checkpoint error: {e}")
        finally:
            conn.close()
        return {}

    def complete_checkpoint(self, chat_id: str):
        """Mark checkpoint as completed (task finished successfully)."""
        conn = self._get_conn()
        try:
            conn.execute(
                "UPDATE task_checkpoints SET status = 'completed' WHERE chat_id = ? AND status = 'active'",
                (chat_id,)
            )
            conn.commit()
            logger.info(f"[CrashRecovery] Checkpoint completed for chat {chat_id}")
        except Exception as e:
            logger.debug(f"[CrashRecovery] complete error: {e}")
        finally:
            conn.close()

    def fail_checkpoint(self, chat_id: str, reason: str = ""):
        """Mark checkpoint as failed."""
        conn = self._get_conn()
        try:
            conn.execute(
                "UPDATE task_checkpoints SET status = 'failed' WHERE chat_id = ? AND status = 'active'",
                (chat_id,)
            )
            conn.commit()
            logger.info(f"[CrashRecovery] Checkpoint failed for chat {chat_id}: {reason}")
        except Exception as e:
            logger.debug(f"[CrashRecovery] fail error: {e}")
        finally:
            conn.close()

    # ── Stale task detection ──

    def find_stale_tasks(self) -> list:
        """Find tasks whose heartbeat is older than threshold."""
        cutoff = (datetime.utcnow() - timedelta(seconds=_STALE_TIMEOUT_SECONDS)).isoformat()
        conn = self._get_conn()
        try:
            rows = conn.execute(
                "SELECT * FROM task_checkpoints WHERE status = 'active' AND heartbeat_at < ?",
                (cutoff,)
            ).fetchall()
            if rows:
                cols = [d[0] for d in conn.execute("SELECT * FROM task_checkpoints LIMIT 0").description]
                return [dict(zip(cols, r)) for r in rows]
        except Exception as e:
            logger.debug(f"[CrashRecovery] find_stale error: {e}")
        finally:
            conn.close()
        return []

    def can_auto_restart(self, chat_id: str) -> bool:
        """Check if task can be auto-restarted (under max restart limit)."""
        cp = self.load_checkpoint(chat_id)
        return cp.get('restart_count', 0) < _MAX_AUTO_RESTARTS

    def increment_restart(self, chat_id: str):
        """Increment restart counter for a task."""
        conn = self._get_conn()
        try:
            conn.execute(
                "UPDATE task_checkpoints SET restart_count = restart_count + 1, heartbeat_at = ? WHERE chat_id = ? AND status = 'active'",
                (datetime.utcnow().isoformat(), chat_id)
            )
            conn.commit()
        except Exception as e:
            logger.debug(f"[CrashRecovery] increment_restart error: {e}")
        finally:
            conn.close()

    # ── Watchdog ──

    def start_watchdog(self, on_stale_callback=None):
        """Start background watchdog thread."""
        if self._running:
            return
        self._on_stale_callback = on_stale_callback
        self._running = True
        self._watchdog_thread = threading.Thread(target=self._watchdog_loop, daemon=True)
        self._watchdog_thread.start()
        logger.info("[CrashRecovery] Watchdog started")

    def stop_watchdog(self):
        """Stop watchdog thread."""
        self._running = False
        if self._watchdog_thread:
            self._watchdog_thread.join(timeout=5)
        logger.info("[CrashRecovery] Watchdog stopped")

    def _watchdog_loop(self):
        """Main watchdog loop — checks for stale tasks periodically."""
        while self._running:
            try:
                stale = self.find_stale_tasks()
                for task in stale:
                    chat_id = task.get('chat_id', '')
                    task_id = task.get('task_id', '')
                    restart_count = task.get('restart_count', 0)
                    logger.warning(
                        f"[WATCHDOG] Stale task detected: chat={chat_id}, "
                        f"task={task_id}, restarts={restart_count}"
                    )
                    if restart_count < _MAX_AUTO_RESTARTS and self._on_stale_callback:
                        try:
                            self.increment_restart(chat_id)
                            self._on_stale_callback(task)
                            logger.info(f"[WATCHDOG] Auto-restart triggered for chat {chat_id}")
                        except Exception as restart_err:
                            logger.error(f"[WATCHDOG] Auto-restart failed: {restart_err}")
                            self.fail_checkpoint(chat_id, str(restart_err))
                    elif restart_count >= _MAX_AUTO_RESTARTS:
                        self.fail_checkpoint(chat_id, "max restarts exceeded")
                        logger.error(f"[WATCHDOG] Max restarts exceeded for chat {chat_id}")
            except Exception as e:
                logger.debug(f"[WATCHDOG] Loop error: {e}")
            time.sleep(_WATCHDOG_INTERVAL)


# ── Singleton ──
_instance = None
_instance_lock = threading.Lock()

def get_crash_recovery(**kwargs) -> CrashRecovery:
    global _instance
    if _instance is None:
        with _instance_lock:
            if _instance is None:
                _instance = CrashRecovery(**kwargs)
    return _instance
