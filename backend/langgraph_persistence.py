"""
langgraph_persistence.py — Task 13: Unified LangGraph state persistence
Manages agent conversation state in SQLite for crash recovery and session resume.
"""
import sqlite3
import json
import time
import logging
import os

logger = logging.getLogger("orion.langgraph_persistence")

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "database.sqlite")

_instance = None

class LanggraphStatePersistence:
    """
    Persists LangGraph-compatible agent state to SQLite.
    Stores conversation messages, tool call history, and iteration state
    so agents can resume after crashes or service restarts.
    """

    def __init__(self, db_path=None):
        self.db_path = db_path or DB_PATH
        self._init_db()

    def _get_conn(self):
        """Thread-safe connection."""
        conn = sqlite3.connect(self.db_path, check_same_thread=False, timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def _init_db(self):
        """Create langgraph_states table if not exists."""
        conn = self._get_conn()
        try:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS langgraph_states (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    chat_id TEXT NOT NULL,
                    thread_id TEXT NOT NULL,
                    checkpoint_ns TEXT DEFAULT '',
                    channel_name TEXT DEFAULT 'messages',
                    state_data TEXT NOT NULL,
                    metadata TEXT DEFAULT '{}',
                    parent_id INTEGER DEFAULT NULL,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    UNIQUE(chat_id, thread_id, checkpoint_ns)
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_lg_chat_thread
                ON langgraph_states(chat_id, thread_id)
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS langgraph_writes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    state_id INTEGER NOT NULL,
                    channel TEXT NOT NULL,
                    value TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    FOREIGN KEY (state_id) REFERENCES langgraph_states(id)
                )
            """)
            conn.commit()
            logger.info("[TASK13] langgraph_states + langgraph_writes tables ready")
        finally:
            conn.close()

    def save_state(self, chat_id, thread_id, messages, metadata=None,
                   checkpoint_ns="", iteration=0, tool_history=None):
        """
        Save or update agent state for a given chat/thread.
        messages: list of message dicts (role, content, tool_calls, etc.)
        """
        now = time.time()
        state_data = {
            "messages": messages[-50:] if len(messages) > 50 else messages,  # Keep last 50
            "iteration": iteration,
            "tool_history": (tool_history or [])[-30:],  # Keep last 30 tool calls
        }
        meta = json.dumps(metadata or {})
        state_json = json.dumps(state_data, ensure_ascii=False, default=str)

        conn = self._get_conn()
        try:
            existing = conn.execute(
                "SELECT id FROM langgraph_states WHERE chat_id=? AND thread_id=? AND checkpoint_ns=?",
                (chat_id, thread_id, checkpoint_ns)
            ).fetchone()

            if existing:
                conn.execute(
                    "UPDATE langgraph_states SET state_data=?, metadata=?, updated_at=? WHERE id=?",
                    (state_json, meta, now, existing['id'])
                )
                state_id = existing['id']
            else:
                cur = conn.execute(
                    "INSERT INTO langgraph_states (chat_id, thread_id, checkpoint_ns, state_data, metadata, created_at, updated_at) VALUES (?,?,?,?,?,?,?)",
                    (chat_id, thread_id, checkpoint_ns, state_json, meta, now, now)
                )
                state_id = cur.lastrowid

            conn.commit()
            return state_id
        except Exception as e:
            logger.error(f"[TASK13] save_state error: {e}")
            return None
        finally:
            conn.close()

    def load_state(self, chat_id, thread_id, checkpoint_ns=""):
        """
        Load the latest state for a chat/thread.
        Returns dict with messages, iteration, tool_history or None.
        """
        conn = self._get_conn()
        try:
            row = conn.execute(
                "SELECT state_data, metadata, updated_at FROM langgraph_states WHERE chat_id=? AND thread_id=? AND checkpoint_ns=? ORDER BY updated_at DESC LIMIT 1",
                (chat_id, thread_id, checkpoint_ns)
            ).fetchone()
            if row:
                state = json.loads(row['state_data'])
                state['_metadata'] = json.loads(row['metadata'])
                state['_updated_at'] = row['updated_at']
                return state
            return None
        except Exception as e:
            logger.error(f"[TASK13] load_state error: {e}")
            return None
        finally:
            conn.close()

    def delete_state(self, chat_id, thread_id=None):
        """Delete state(s) for a chat (and optionally specific thread)."""
        conn = self._get_conn()
        try:
            if thread_id:
                conn.execute(
                    "DELETE FROM langgraph_states WHERE chat_id=? AND thread_id=?",
                    (chat_id, thread_id)
                )
            else:
                conn.execute(
                    "DELETE FROM langgraph_states WHERE chat_id=?",
                    (chat_id,)
                )
            conn.commit()
        except Exception as e:
            logger.error(f"[TASK13] delete_state error: {e}")
        finally:
            conn.close()

    def list_threads(self, chat_id):
        """List all thread IDs for a given chat."""
        conn = self._get_conn()
        try:
            rows = conn.execute(
                "SELECT DISTINCT thread_id, MAX(updated_at) as last_update FROM langgraph_states WHERE chat_id=? GROUP BY thread_id ORDER BY last_update DESC",
                (chat_id,)
            ).fetchall()
            return [{"thread_id": r['thread_id'], "last_update": r['last_update']} for r in rows]
        except Exception as e:
            logger.error(f"[TASK13] list_threads error: {e}")
            return []
        finally:
            conn.close()

    def cleanup_old(self, max_age_hours=72):
        """Remove states older than max_age_hours."""
        cutoff = time.time() - (max_age_hours * 3600)
        conn = self._get_conn()
        try:
            # Delete writes for old states
            conn.execute(
                "DELETE FROM langgraph_writes WHERE state_id IN (SELECT id FROM langgraph_states WHERE updated_at < ?)",
                (cutoff,)
            )
            result = conn.execute(
                "DELETE FROM langgraph_states WHERE updated_at < ?",
                (cutoff,)
            )
            conn.commit()
            count = result.rowcount
            if count > 0:
                logger.info(f"[TASK13] Cleaned up {count} old langgraph states")
            return count
        except Exception as e:
            logger.error(f"[TASK13] cleanup_old error: {e}")
            return 0
        finally:
            conn.close()

    def get_stats(self):
        """Get persistence statistics."""
        conn = self._get_conn()
        try:
            total = conn.execute("SELECT COUNT(*) FROM langgraph_states").fetchone()[0]
            chats = conn.execute("SELECT COUNT(DISTINCT chat_id) FROM langgraph_states").fetchone()[0]
            threads = conn.execute("SELECT COUNT(DISTINCT thread_id) FROM langgraph_states").fetchone()[0]
            return {"total_states": total, "unique_chats": chats, "unique_threads": threads}
        except Exception:
            return {"total_states": 0, "unique_chats": 0, "unique_threads": 0}
        finally:
            conn.close()


def get_langgraph_persistence(db_path=None):
    """Singleton accessor."""
    global _instance
    if _instance is None:
        _instance = LanggraphStatePersistence(db_path)
    return _instance
