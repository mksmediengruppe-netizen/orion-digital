"""
ARCANE 2 — Persistence Layer (SQLite)
=====================================
Replaces in-memory dicts in compat_all.py with SQLite-backed stores.
Survives service restarts. Thread-safe via threading.Lock.

Tables:
  - users       — user accounts
  - sessions    — auth tokens → user_id
  - chats       — chat metadata
  - messages    — chat messages
  - groups      — user groups
  - permissions — per-user permission overrides
  - budgets     — org / user / group budget limits
  - audit_logs  — security audit trail
  - schedule    — scheduled tasks
  - key_overrides — runtime API key overrides

Usage:
    from core.persistence import get_store
    store = get_store()

    store.users.get("admin")
    store.sessions.set("tok_xxx", "user_123")
    store.chats.upsert(chat_id, chat_dict)
"""
from __future__ import annotations

import json
import logging
import os
import sqlite3
import threading
import time
from typing import Any, Optional

logger = logging.getLogger("arcane.persistence")

_DB_PATH = os.environ.get(
    "ARCANE_PERSIST_DB",
    "/root/workspace/.arcane_app.db"
)


def _connect(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(path, timeout=15, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


# ── Generic KV table ──────────────────────────────────────────────────────────

class _KVTable:
    """
    Generic key → JSON value table.
    Thread-safe. Values serialised as JSON.
    """

    def __init__(self, conn: sqlite3.Connection, lock: threading.Lock, table: str):
        self._conn = conn
        self._lock = lock
        self._table = table
        self._ensure_table()

    def _ensure_table(self):
        with self._lock:
            self._conn.execute(
                f"""CREATE TABLE IF NOT EXISTS {self._table} (
                    key   TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    ts    REAL DEFAULT (unixepoch())
                )"""
            )
            self._conn.commit()

    def get(self, key: str, default=None):
        with self._lock:
            row = self._conn.execute(
                f"SELECT value FROM {self._table} WHERE key=?", (key,)
            ).fetchone()
            if row:
                try:
                    return json.loads(row["value"])
                except Exception:
                    return row["value"]
            return default

    def set(self, key: str, value: Any) -> None:
        with self._lock:
            self._conn.execute(
                f"INSERT OR REPLACE INTO {self._table} (key, value, ts) VALUES (?,?,?)",
                (key, json.dumps(value, default=str), time.time())
            )
            self._conn.commit()

    def delete(self, key: str) -> None:
        with self._lock:
            self._conn.execute(f"DELETE FROM {self._table} WHERE key=?", (key,))
            self._conn.commit()

    def all(self) -> dict:
        with self._lock:
            rows = self._conn.execute(f"SELECT key, value FROM {self._table}").fetchall()
            result = {}
            for row in rows:
                try:
                    result[row["key"]] = json.loads(row["value"])
                except Exception:
                    result[row["key"]] = row["value"]
            return result

    def values(self) -> list:
        return list(self.all().values())

    def keys(self) -> list:
        with self._lock:
            rows = self._conn.execute(f"SELECT key FROM {self._table}").fetchall()
            return [r["key"] for r in rows]

    def __contains__(self, key: str) -> bool:
        return self.get(key) is not None

    def pop(self, key: str, default=None):
        val = self.get(key, default)
        self.delete(key)
        return val

    def setdefault(self, key: str, default: Any) -> Any:
        existing = self.get(key)
        if existing is None:
            self.set(key, default)
            return default
        return existing

    def update(self, d: dict) -> None:
        for k, v in d.items():
            self.set(k, v)

    # dict-like iteration
    def items(self):
        return self.all().items()

    def __getitem__(self, key: str):
        v = self.get(key)
        if v is None:
            raise KeyError(key)
        return v

    def __setitem__(self, key: str, value: Any):
        self.set(key, value)


# ── Messages table (list per chat_id) ────────────────────────────────────────

class _MessagesTable:
    """chat_id → list of message dicts, stored as JSON array."""

    def __init__(self, conn: sqlite3.Connection, lock: threading.Lock):
        self._conn = conn
        self._lock = lock
        with self._lock:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS messages (
                    chat_id  TEXT NOT NULL,
                    msg_id   TEXT NOT NULL,
                    role     TEXT,
                    content  TEXT,
                    data     TEXT NOT NULL,
                    ts       REAL DEFAULT (unixepoch()),
                    PRIMARY KEY (chat_id, msg_id)
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_msg_chat ON messages(chat_id)")
            conn.commit()

    def get(self, chat_id: str, default=None) -> list:
        with self._lock:
            rows = self._conn.execute(
                "SELECT data FROM messages WHERE chat_id=? ORDER BY ts ASC",
                (chat_id,)
            ).fetchall()
            if not rows:
                return default if default is not None else []
            result = []
            for row in rows:
                try:
                    result.append(json.loads(row["data"]))
                except Exception:
                    pass
            return result

    def append(self, chat_id: str, message: dict) -> None:
        msg_id = message.get("id", f"msg_{int(time.time()*1000)}")
        with self._lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO messages (chat_id, msg_id, role, content, data, ts) "
                "VALUES (?,?,?,?,?,?)",
                (
                    chat_id,
                    msg_id,
                    message.get("role", ""),
                    str(message.get("content", ""))[:500],
                    json.dumps(message, default=str),
                    time.time(),
                )
            )
            self._conn.commit()

    def setdefault(self, chat_id: str, default: list) -> list:
        existing = self.get(chat_id)
        if not existing and default is not None:
            return default
        return existing

    def delete_chat(self, chat_id: str) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM messages WHERE chat_id=?", (chat_id,))
            self._conn.commit()

    def __getitem__(self, chat_id: str) -> list:
        return self.get(chat_id, [])

    def __setitem__(self, chat_id: str, messages: list) -> None:
        """Replace all messages for a chat."""
        with self._lock:
            self._conn.execute("DELETE FROM messages WHERE chat_id=?", (chat_id,))
            for msg in messages:
                msg_id = msg.get("id", f"msg_{int(time.time()*1000)}")
                self._conn.execute(
                    "INSERT OR REPLACE INTO messages (chat_id, msg_id, role, content, data, ts) "
                    "VALUES (?,?,?,?,?,?)",
                    (chat_id, msg_id, msg.get("role",""), str(msg.get("content",""))[:500],
                     json.dumps(msg, default=str), time.time())
                )
            self._conn.commit()


# ── Audit log (append-only list with size cap) ────────────────────────────────

class _AuditLogTable:
    """Append-only audit log, newest first, capped at 10k entries."""

    MAX_ENTRIES = 10_000

    def __init__(self, conn: sqlite3.Connection, lock: threading.Lock):
        self._conn = conn
        self._lock = lock
        with self._lock:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS audit_logs (
                    id    TEXT PRIMARY KEY,
                    data  TEXT NOT NULL,
                    ts    REAL DEFAULT (unixepoch())
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_audit_ts ON audit_logs(ts DESC)")
            conn.commit()

    def insert(self, index: int, entry: dict) -> None:
        """insert(0, entry) — prepend. We ignore index, just append."""
        self._append(entry)

    def append(self, entry: dict) -> None:
        self._append(entry)

    def _append(self, entry: dict) -> None:
        entry_id = entry.get("id", f"log_{int(time.time()*1000)}")
        with self._lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO audit_logs (id, data, ts) VALUES (?,?,?)",
                (entry_id, json.dumps(entry, default=str), time.time())
            )
            # Cap at MAX_ENTRIES
            count = self._conn.execute("SELECT COUNT(*) FROM audit_logs").fetchone()[0]
            if count > self.MAX_ENTRIES:
                self._conn.execute(
                    "DELETE FROM audit_logs WHERE id IN "
                    "(SELECT id FROM audit_logs ORDER BY ts ASC LIMIT ?)",
                    (count - self.MAX_ENTRIES,)
                )
            self._conn.commit()

    def get_recent(self, limit: int = 50, offset: int = 0,
                   user_id: str = None, project_id: str = None,
                   action_prefix: str = None) -> tuple[list, int]:
        """Return (entries, total) newest first."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT data FROM audit_logs ORDER BY ts DESC"
            ).fetchall()
        entries = []
        for row in rows:
            try:
                e = json.loads(row["data"])
                if user_id and e.get("userId") != user_id:
                    continue
                if project_id and e.get("projectId") != project_id:
                    continue
                if action_prefix and not e.get("action", "").startswith(action_prefix):
                    continue
                entries.append(e)
            except Exception:
                pass
        total = len(entries)
        return entries[offset:offset + limit], total

    # Legacy list-like interface
    def __iter__(self):
        rows = self._conn.execute(
            "SELECT data FROM audit_logs ORDER BY ts DESC"
        ).fetchall()
        for row in rows:
            try:
                yield json.loads(row["data"])
            except Exception:
                pass

    def __len__(self) -> int:
        with self._lock:
            return self._conn.execute("SELECT COUNT(*) FROM audit_logs").fetchone()[0]

    def __getitem__(self, key):
        if isinstance(key, slice):
            all_entries = list(self.__iter__())
            return all_entries[key]
        raise TypeError("audit_logs only supports slicing")

    def __setitem__(self, key, value):
        if isinstance(key, slice) and key == slice(None):
            # _audit_logs[:] = _audit_logs[:N] — trim
            if isinstance(value, list):
                # Re-insert
                with self._lock:
                    self._conn.execute("DELETE FROM audit_logs")
                    for e in value:
                        eid = e.get("id", f"log_{int(time.time()*1000)}")
                        self._conn.execute(
                            "INSERT OR REPLACE INTO audit_logs (id, data, ts) VALUES (?,?,?)",
                            (eid, json.dumps(e, default=str), time.time())
                        )
                    self._conn.commit()


# ── SSE event bus (in-memory — only for real-time delivery) ───────────────────

class _SSEBus:
    """
    In-memory event bus for SSE streaming.
    Subscribers register an asyncio.Queue; publisher puts events.
    Max 50 concurrent SSE connections.
    """
    def __init__(self):
        self._subscribers: dict[str, list] = {}  # chat_id → [asyncio.Queue]
        self._lock = threading.Lock()

    def subscribe(self, chat_id: str) -> "asyncio.Queue":
        import asyncio
        q = asyncio.Queue(maxsize=100)
        with self._lock:
            self._subscribers.setdefault(chat_id, []).append(q)
        return q

    def unsubscribe(self, chat_id: str, q) -> None:
        with self._lock:
            subs = self._subscribers.get(chat_id, [])
            if q in subs:
                subs.remove(q)

    async def publish(self, chat_id: str, event: dict) -> None:
        with self._lock:
            subs = list(self._subscribers.get(chat_id, []))
        for q in subs:
            try:
                q.put_nowait(event)
            except Exception:
                pass

    def publish_sync(self, chat_id: str, event: dict) -> None:
        import asyncio
        with self._lock:
            subs = list(self._subscribers.get(chat_id, []))
        for q in subs:
            try:
                q.put_nowait(event)
            except Exception:
                pass


# ── Main store ────────────────────────────────────────────────────────────────

class PersistentStore:
    """
    Single store object. All tables share one SQLite connection.
    Usage: from core.persistence import get_store; store = get_store()
    """

    def __init__(self, db_path: str = _DB_PATH):
        os.makedirs(os.path.dirname(db_path) if os.path.dirname(db_path) else ".", exist_ok=True)
        self._conn = _connect(db_path)
        self._lock = threading.Lock()

        self.users         = _KVTable(self._conn, self._lock, "users")
        self.sessions      = _KVTable(self._conn, self._lock, "sessions")
        self.chats         = _KVTable(self._conn, self._lock, "chats")
        self.messages      = _MessagesTable(self._conn, self._lock)
        self.groups        = _KVTable(self._conn, self._lock, "groups")
        self.permissions   = _KVTable(self._conn, self._lock, "permissions")
        self.user_budgets  = _KVTable(self._conn, self._lock, "user_budgets")
        self.group_budgets = _KVTable(self._conn, self._lock, "group_budgets")
        self.org_budget    = _KVTable(self._conn, self._lock, "org_budget")
        self.schedule      = _KVTable(self._conn, self._lock, "schedule")
        self.key_overrides = _KVTable(self._conn, self._lock, "key_overrides")
        self.audit_logs    = _AuditLogTable(self._conn, self._lock)
        self.sse_bus       = _SSEBus()

        logger.info(f"PersistentStore initialised: {db_path}")

    def close(self) -> None:
        try:
            self._conn.close()
        except Exception:
            pass


# ── Singleton ─────────────────────────────────────────────────────────────────

_store: Optional[PersistentStore] = None
_store_lock = threading.Lock()


def get_store(db_path: str = _DB_PATH) -> PersistentStore:
    """Return (or create) the global store singleton."""
    global _store
    if _store is None:
        with _store_lock:
            if _store is None:
                _store = PersistentStore(db_path)
    return _store
