"""
L2: Session Memory — полная история в SQLite.
"""
import sqlite3, json, os, threading, logging
from datetime import datetime, timezone
from typing import List, Dict, Optional
from .config import MemoryConfig

logger = logging.getLogger("memory.session")
_local = threading.local()


def _conn():
    if not hasattr(_local, "c") or _local.c is None:
        os.makedirs(os.path.dirname(MemoryConfig.SESSION_DB), exist_ok=True)
        _local.c = sqlite3.connect(MemoryConfig.SESSION_DB, timeout=15)
        _local.c.execute("PRAGMA journal_mode=WAL")
        _local.c.row_factory = sqlite3.Row
        _local.c.executescript("""
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id TEXT, user_id TEXT, role TEXT,
                content TEXT, tool_name TEXT, tool_args TEXT,
                tool_result TEXT, timestamp TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_msg_chat ON messages(chat_id);
            CREATE INDEX IF NOT EXISTS idx_msg_user ON messages(user_id);
            CREATE TABLE IF NOT EXISTS interrupted_tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id TEXT, user_id TEXT UNIQUE,
                task TEXT, plan TEXT, progress TEXT,
                scratchpad TEXT, iteration INTEGER,
                reason TEXT, timestamp TEXT
            );
        """)
        _local.c.commit()
    return _local.c


class SessionMemory:
    """Полная история сессии в SQLite."""

    @staticmethod
    def store_message(chat_id: str, role: str, content: str,
                      user_id: str = None, tool_name: str = None,
                      tool_args: str = None, tool_result: str = None):
        try:
            c = _conn()
            c.execute(
                "INSERT INTO messages (chat_id,user_id,role,content,tool_name,tool_args,tool_result,timestamp) VALUES (?,?,?,?,?,?,?,?)",
                (chat_id, user_id, role, content[:5000], tool_name, tool_args, tool_result,
                 datetime.now(timezone.utc).isoformat())
            )
            c.commit()
        except Exception as e:
            logger.error(f"SessionMemory store: {e}")

    @staticmethod
    def get_history(chat_id: str, limit: int = 50) -> List[Dict]:
        try:
            c = _conn()
            rows = c.execute(
                "SELECT * FROM messages WHERE chat_id=? ORDER BY id DESC LIMIT ?",
                (chat_id, limit)
            ).fetchall()
            return [dict(r) for r in reversed(rows)]
        except:
            return []

    @staticmethod
    def save_interrupted(chat_id: str, user_id: str, task: str,
                         plan: str = "", progress: str = "",
                         scratchpad: str = "", iteration: int = 0,
                         reason: str = "user_stop"):
        try:
            c = _conn()
            c.execute("""
                INSERT OR REPLACE INTO interrupted_tasks
                (chat_id,user_id,task,plan,progress,scratchpad,iteration,reason,timestamp)
                VALUES (?,?,?,?,?,?,?,?,?)
            """, (chat_id, user_id, task[:2000], plan[:2000], progress[:1000],
                  scratchpad[:1000], iteration, reason,
                  datetime.now(timezone.utc).isoformat()))
            c.commit()
        except Exception as e:
            logger.error(f"SessionMemory save_interrupted: {e}")

    @staticmethod
    def get_interrupted(user_id: str) -> Optional[Dict]:
        try:
            c = _conn()
            row = c.execute(
                "SELECT * FROM interrupted_tasks WHERE user_id=? ORDER BY id DESC LIMIT 1",
                (user_id,)
            ).fetchone()
            return dict(row) if row else None
        except:
            return None

    @staticmethod
    def clear_interrupted(user_id: str):
        try:
            c = _conn()
            c.execute("DELETE FROM interrupted_tasks WHERE user_id=?", (user_id,))
            c.commit()
        except:
            pass
