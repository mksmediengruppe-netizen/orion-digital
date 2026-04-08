"""
L2: Session Memory — полная история каждого чата в SQLite.
Ничего не обрезается. Агент может запросить любое сообщение из прошлого.
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
        _local.c.execute("PRAGMA synchronous=NORMAL")
        _local.c.row_factory = sqlite3.Row
        _local.c.executescript("""
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id TEXT NOT NULL, user_id TEXT, role TEXT NOT NULL,
                content TEXT, tool_name TEXT, tool_args TEXT, tool_result TEXT,
                tokens INTEGER DEFAULT 0, cost REAL DEFAULT 0,
                iteration INTEGER, agent_name TEXT,
                timestamp TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_msg_chat ON messages(chat_id);
            CREATE INDEX IF NOT EXISTS idx_msg_user ON messages(user_id);
            CREATE INDEX IF NOT EXISTS idx_msg_tool ON messages(tool_name);
            CREATE TABLE IF NOT EXISTS interrupted_tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id TEXT NOT NULL, user_id TEXT,
                task TEXT, plan TEXT, progress TEXT,
                scratchpad TEXT, iteration INTEGER,
                reason TEXT, timestamp TEXT NOT NULL
            );
        """)
        _local.c.commit()
    return _local.c

class SessionMemory:
    """Полная история без потерь."""

    @staticmethod
    def store_message(chat_id: str, role: str, content: str,
                      user_id: str = None, tool_name: str = None,
                      tool_args: str = None, tool_result: str = None,
                      tokens: int = 0, cost: float = 0,
                      iteration: int = None, agent_name: str = None):
        try:
            c = _conn()
            c.execute(
                "INSERT INTO messages (chat_id,user_id,role,content,tool_name,tool_args,tool_result,tokens,cost,iteration,agent_name,timestamp) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (chat_id, user_id, role, content, tool_name, tool_args, tool_result, tokens, cost, iteration, agent_name, datetime.now(timezone.utc).isoformat())
            )
            c.commit()
        except Exception as e:
            logger.error(f"SessionMemory store failed: {e}")

    @staticmethod
    def get_full_history(chat_id: str, limit: int = 1000) -> List[Dict]:
        try:
            c = _conn()
            rows = c.execute("SELECT * FROM messages WHERE chat_id=? ORDER BY id LIMIT ?", (chat_id, limit)).fetchall()
            return [dict(r) for r in rows]
        except: return []

    @staticmethod
    def get_message_at(chat_id: str, iteration: int) -> Optional[Dict]:
        """Получить сообщение по номеру итерации (для recall)."""
        try:
            c = _conn()
            row = c.execute("SELECT * FROM messages WHERE chat_id=? AND iteration=? LIMIT 1", (chat_id, iteration)).fetchone()
            return dict(row) if row else None
        except: return None

    @staticmethod
    def search_in_chat(chat_id: str, query: str, limit: int = 10) -> List[Dict]:
        """Полнотекстовый поиск внутри чата."""
        try:
            c = _conn()
            rows = c.execute("SELECT * FROM messages WHERE chat_id=? AND content LIKE ? ORDER BY id DESC LIMIT ?",
                             (chat_id, f"%{query}%", limit)).fetchall()
            return [dict(r) for r in rows]
        except: return []

    @staticmethod
    def get_tool_history(user_id: str, tool_name: str, limit: int = 20) -> List[Dict]:
        """История вызовов конкретного инструмента."""
        try:
            c = _conn()
            rows = c.execute("SELECT * FROM messages WHERE user_id=? AND tool_name=? ORDER BY id DESC LIMIT ?",
                             (user_id, tool_name, limit)).fetchall()
            return [dict(r) for r in rows]
        except: return []

    # ── Conversation Continuity ──

    @staticmethod
    def save_interrupted(chat_id: str, user_id: str, task: str,
                         plan: str, progress: str, scratchpad: str,
                         iteration: int, reason: str = "user_stop"):
        """Сохранить прерванную задачу для продолжения."""
        try:
            c = _conn()
            c.execute(
                "INSERT INTO interrupted_tasks (chat_id,user_id,task,plan,progress,scratchpad,iteration,reason,timestamp) VALUES (?,?,?,?,?,?,?,?,?)",
                (chat_id, user_id, task, plan, progress, scratchpad, iteration, reason, datetime.now(timezone.utc).isoformat())
            )
            c.commit()
        except Exception as e:
            logger.error(f"Save interrupted failed: {e}")

    @staticmethod
    def get_interrupted(user_id: str) -> Optional[Dict]:
        """Получить последнюю прерванную задачу."""
        try:
            c = _conn()
            row = c.execute("SELECT * FROM interrupted_tasks WHERE user_id=? ORDER BY id DESC LIMIT 1", (user_id,)).fetchone()
            return dict(row) if row else None
        except: return None

    @staticmethod
    def clear_interrupted(user_id: str):
        try:
            c = _conn()
            c.execute("DELETE FROM interrupted_tasks WHERE user_id=?", (user_id,))
            c.commit()
        except: pass
