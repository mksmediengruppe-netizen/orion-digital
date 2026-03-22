"""
ORION Digital v1.0 — SQLite Database Layer
=========================================
Drop-in replacement for JSON-based storage.
Provides _load_db() / _save_db() compatible interface
while storing data in SQLite for production reliability.

Features:
- Automatic migration from existing database.json
- Thread-safe with WAL mode
- Atomic writes
- Backward-compatible dict-like interface
"""

import json
import os
import sqlite3
import threading
import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

DATA_DIR = os.environ.get("DATA_DIR", "/var/www/orion/backend/data")
DB_SQLITE = os.path.join(DATA_DIR, "database.sqlite")
DB_JSON_LEGACY = os.path.join(DATA_DIR, "database.json")

_local = threading.local()
_write_lock = threading.Lock()


def _get_conn():
    """Get thread-local SQLite connection."""
    if not hasattr(_local, "conn") or _local.conn is None:
        _local.conn = sqlite3.connect(DB_SQLITE, timeout=30)
        _local.conn.execute("PRAGMA journal_mode=WAL")
        _local.conn.execute("PRAGMA synchronous=NORMAL")
        _local.conn.execute("PRAGMA foreign_keys=ON")
        _local.conn.row_factory = sqlite3.Row
    return _local.conn


def init_db():
    """Initialize SQLite schema and migrate from JSON if needed."""
    os.makedirs(DATA_DIR, exist_ok=True)
    conn = _get_conn()

    conn.executescript("""
        CREATE TABLE IF NOT EXISTS kv_store (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS users (
            id TEXT PRIMARY KEY,
            email TEXT UNIQUE,
            password_hash TEXT NOT NULL,
            name TEXT DEFAULT '',
            role TEXT DEFAULT 'user',
            created_at TEXT NOT NULL,
            is_active INTEGER DEFAULT 1,
            monthly_limit REAL DEFAULT 2.0,
            total_spent REAL DEFAULT 0.0,
            settings TEXT DEFAULT '{}'
        );

        CREATE TABLE IF NOT EXISTS chats (
            id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            title TEXT DEFAULT 'New Chat',
            messages TEXT DEFAULT '[]',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            model TEXT DEFAULT '',
            variant TEXT DEFAULT 'premium',
            total_cost REAL DEFAULT 0.0,
            pinned INTEGER DEFAULT 0,
            archived INTEGER DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS sessions (
            token TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            created_at TEXT NOT NULL,
            expires_at TEXT,
            ip TEXT DEFAULT '',
            user_agent TEXT DEFAULT ''
        );

        CREATE TABLE IF NOT EXISTS analytics (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            key TEXT NOT NULL,
            value TEXT NOT NULL,
            date TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS audit_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT,
            action TEXT NOT NULL,
            details TEXT DEFAULT '',
            ip TEXT DEFAULT '',
            timestamp TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS custom_agents (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            description TEXT DEFAULT '',
            system_prompt TEXT DEFAULT '',
            avatar TEXT DEFAULT '🤖',
            tools TEXT DEFAULT '[]',
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS connector_states (
            id TEXT PRIMARY KEY,
            enabled INTEGER DEFAULT 1,
            config TEXT DEFAULT '{}',
            updated_at TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_chats_user ON chats(user_id);
        CREATE INDEX IF NOT EXISTS idx_audit_timestamp ON audit_log(timestamp);
        CREATE INDEX IF NOT EXISTS idx_audit_user ON audit_log(user_id);
        CREATE TABLE IF NOT EXISTS task_charters (
            task_id TEXT PRIMARY KEY,
            chat_id TEXT NOT NULL,
            project_id TEXT DEFAULT '',
            version INTEGER DEFAULT 1,
            status TEXT DEFAULT 'active',
            primary_objective TEXT NOT NULL,
            current_objective TEXT NOT NULL,
            success_criteria_json TEXT DEFAULT '[]',
            constraints_json TEXT DEFAULT '[]',
            deliverables_json TEXT DEFAULT '[]',
            done_definition TEXT DEFAULT '',
            current_plan_json TEXT DEFAULT '[]',
            current_step_id TEXT DEFAULT '',
            completed_steps_json TEXT DEFAULT '[]',
            failed_steps_json TEXT DEFAULT '[]',
            amendments_json TEXT DEFAULT '[]',
            total_iterations INTEGER DEFAULT 0,
            total_cost REAL DEFAULT 0.0,
            created_at REAL,
            updated_at REAL
        );

        CREATE TABLE IF NOT EXISTS execution_snapshots (
            id TEXT PRIMARY KEY,
            task_id TEXT NOT NULL,
            step_id TEXT DEFAULT '',
            snapshot_type TEXT DEFAULT 'iteration',
            iteration INTEGER DEFAULT 0,
            phase TEXT DEFAULT '',
            agent_role TEXT DEFAULT '',
            completed_actions_json TEXT DEFAULT '[]',
            artifacts_created_json TEXT DEFAULT '[]',
            pending_actions_json TEXT DEFAULT '[]',
            blockers_json TEXT DEFAULT '[]',
            active_constraints_json TEXT DEFAULT '[]',
            last_user_amendment TEXT DEFAULT '',
            next_expected_step TEXT DEFAULT '',
            cost_so_far REAL DEFAULT 0.0,
            tokens_used INTEGER DEFAULT 0,
            created_at REAL
        );

        CREATE TABLE IF NOT EXISTS task_scorecards (
            task_id          TEXT PRIMARY KEY,
            chat_id          TEXT DEFAULT '',
            user_id          TEXT DEFAULT '',
            orion_mode       TEXT DEFAULT 'default',
            started_at       REAL,
            finished_at      REAL,
            duration_seconds REAL DEFAULT 0,
            total_iterations INTEGER DEFAULT 0,
            max_iterations   INTEGER DEFAULT 0,
            total_cost_usd   REAL DEFAULT 0.0,
            input_tokens     INTEGER DEFAULT 0,
            output_tokens    INTEGER DEFAULT 0,
            tool_calls_json  TEXT DEFAULT '{}',
            total_tool_calls INTEGER DEFAULT 0,
            error_count      INTEGER DEFAULT 0,
            retry_count      INTEGER DEFAULT 0,
            errors_json      TEXT DEFAULT '[]',
            verdict          TEXT DEFAULT '',
            quality_score    REAL DEFAULT 0.0,
            final_answer_len INTEGER DEFAULT 0,
            objective        TEXT DEFAULT '',
            status           TEXT DEFAULT 'running',
            final_verdict    TEXT DEFAULT '',
            final_score      REAL DEFAULT 0.0,
            quality_notes    TEXT DEFAULT '',
            score            REAL DEFAULT 0.0,
            created_at       REAL,
            updated_at       REAL
        );

        CREATE TABLE IF NOT EXISTS artifact_handoffs (
            artifact_id TEXT PRIMARY KEY,
            task_id TEXT NOT NULL,
            chat_id TEXT DEFAULT '',
            from_agent TEXT DEFAULT '',
            to_agent TEXT DEFAULT '',
            artifact_type TEXT DEFAULT 'data',
            content TEXT DEFAULT '',
            metadata_json TEXT DEFAULT '{}',
            status TEXT DEFAULT 'pending',
            created_at REAL,
            received_at REAL,
            processed_at REAL,
            error_msg TEXT DEFAULT ''
        );

        CREATE INDEX IF NOT EXISTS idx_charter_chat ON task_charters(chat_id);
        CREATE INDEX IF NOT EXISTS idx_charter_status ON task_charters(status);
        CREATE INDEX IF NOT EXISTS idx_snapshot_task ON execution_snapshots(task_id, created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_scorecard_chat ON task_scorecards(chat_id);
        CREATE INDEX IF NOT EXISTS idx_scorecard_user ON task_scorecards(user_id);
        CREATE INDEX IF NOT EXISTS idx_scorecard_status ON task_scorecards(status);
        CREATE INDEX IF NOT EXISTS idx_artifact_task ON artifact_handoffs(task_id);
        CREATE INDEX IF NOT EXISTS idx_artifact_chat ON artifact_handoffs(chat_id);
        CREATE INDEX IF NOT EXISTS idx_artifact_status ON artifact_handoffs(status);
    """)
    conn.commit()

    # Migrate from JSON if exists and SQLite is empty
    _migrate_from_json(conn)
    
    # Migrate from separate .db files into unified database
    _migrate_separate_dbs()


def _migrate_from_json(conn):
    """One-time migration from database.json to SQLite."""
    if not os.path.exists(DB_JSON_LEGACY):
        return

    # Check if already migrated
    cursor = conn.execute("SELECT COUNT(*) FROM users")
    if cursor.fetchone()[0] > 0:
        return

    logger.info("Migrating from database.json to SQLite...")
    try:
        with open(DB_JSON_LEGACY, "r") as f:
            data = json.load(f)

        now = datetime.now(timezone.utc).isoformat()

        # Migrate users
        for uid, user in data.get("users", {}).items():
            conn.execute(
                "INSERT OR IGNORE INTO users (id, email, password_hash, name, role, created_at, is_active, monthly_limit, total_spent, settings) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (uid, user.get("email", ""), user.get("password_hash", ""),
                 user.get("name", ""), user.get("role", "user"),
                 user.get("created_at", now), 1 if user.get("is_active", True) else 0,
                 user.get("monthly_limit", 2.0), user.get("total_spent", 0.0),
                 json.dumps(user.get("settings", {}), ensure_ascii=False))
            )

        # Migrate chats
        for cid, chat in data.get("chats", {}).items():
            if isinstance(chat, dict):
                conn.execute(
                    "INSERT OR IGNORE INTO chats (id, user_id, title, messages, created_at, updated_at, model, variant, total_cost, pinned, archived) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (cid, chat.get("user_id", "admin"), chat.get("title", "Chat"),
                     json.dumps(chat.get("messages", []), ensure_ascii=False),
                     chat.get("created_at", now), chat.get("updated_at", now),
                     chat.get("model", ""), chat.get("variant", "premium"),
                     chat.get("total_cost", 0.0),
                     1 if chat.get("pinned") else 0,
                     1 if chat.get("archived") else 0)
                )

        # Migrate sessions
        for token, session in data.get("sessions", {}).items():
            if isinstance(session, dict):
                conn.execute(
                    "INSERT OR IGNORE INTO sessions (token, user_id, created_at, expires_at, ip, user_agent) VALUES (?, ?, ?, ?, ?, ?)",
                    (token, session.get("user_id", ""), session.get("created_at", now),
                     session.get("expires_at", ""),
                     session.get("ip", ""), session.get("user_agent", ""))
                )

        # Store remaining data as KV
        for key in ["analytics", "memory", "ssh_servers", "connections", "connector_states"]:
            if key in data:
                conn.execute(
                    "INSERT OR REPLACE INTO kv_store (key, value, updated_at) VALUES (?, ?, ?)",
                    (key, json.dumps(data[key], ensure_ascii=False), now)
                )

        conn.commit()
        logger.info("Migration from JSON to SQLite completed successfully")

        # Rename old JSON file as backup
        backup = DB_JSON_LEGACY + ".migrated.bak"
        os.rename(DB_JSON_LEGACY, backup)
        logger.info(f"Old database.json renamed to {backup}")

    except Exception as e:
        logger.error(f"Migration failed: {e}")
        conn.rollback()


def load_db():
    """
    Load entire database as a dict (backward-compatible).
    This allows existing code to work without changes.
    """
    conn = _get_conn()
    db = {}

    # Users
    users = {}
    for row in conn.execute("SELECT * FROM users"):
        users[row["id"]] = {
            "id": row["id"],
            "email": row["email"],
            "password_hash": row["password_hash"],
            "name": row["name"],
            "role": row["role"],
            "created_at": row["created_at"],
            "is_active": bool(row["is_active"]),
            "monthly_limit": row["monthly_limit"],
            "total_spent": row["total_spent"],
            "settings": json.loads(row["settings"] or "{}")
        }
    db["users"] = users

    # Chats
    chats = {}
    for row in conn.execute("SELECT * FROM chats ORDER BY updated_at DESC"):
        chats[row["id"]] = {
            "id": row["id"],
            "user_id": row["user_id"],
            "title": row["title"],
            "messages": json.loads(row["messages"] or "[]"),
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "model": row["model"],
            "variant": row["variant"],
            "total_cost": row["total_cost"],
            "pinned": bool(row["pinned"]),
            "archived": bool(row["archived"]),
            "orion_mode": row["orion_mode"] if "orion_mode" in row.keys() else "turbo-basic"
        }
    db["chats"] = chats

    # Sessions
    sessions = {}
    for row in conn.execute("SELECT * FROM sessions"):
        # Parse expires_at — could be ISO string, numeric string, or None
        expires_at = row["expires_at"]
        if expires_at:
            try:
                expires_at = float(expires_at)
            except (ValueError, TypeError):
                try:
                    from datetime import datetime as _dt
                    expires_at = _dt.fromisoformat(expires_at).timestamp()
                except:
                    expires_at = 0
        else:
            expires_at = 0
        # Parse created_at similarly
        created_at = row["created_at"]
        try:
            created_at = float(created_at)
        except (ValueError, TypeError):
            pass
        sessions[row["token"]] = {
            "user_id": row["user_id"],
            "created_at": created_at,
            "expires_at": expires_at,
            "ip": row["ip"] or "",
            "user_agent": row["user_agent"] or ""
        }
    db["sessions"] = sessions

    # Custom agents
    custom_agents = []
    for row in conn.execute("SELECT * FROM custom_agents"):
        custom_agents.append({
            "id": row["id"],
            "name": row["name"],
            "description": row["description"],
            "system_prompt": row["system_prompt"],
            "avatar": row["avatar"],
            "tools": json.loads(row["tools"] or "[]"),
            "system": False,
            "created_at": row["created_at"]
        })
    db["custom_agents"] = custom_agents

    # Connector states
    connector_states = {}
    for row in conn.execute("SELECT * FROM connector_states"):
        connector_states[row["id"]] = {
            "enabled": bool(row["enabled"]),
            "config": json.loads(row["config"] or "{}"),
            "updated_at": row["updated_at"]
        }
    db["connector_states"] = connector_states

    # KV store for remaining data
    for row in conn.execute("SELECT key, value FROM kv_store"):
        try:
            db[row["key"]] = json.loads(row["value"])
        except json.JSONDecodeError:
            db[row["key"]] = row["value"]

    return db


def save_db(db):
    """
    Save entire database dict back to SQLite (backward-compatible).
    This allows existing code to work without changes.
    """
    with _write_lock:
        conn = _get_conn()
        now = datetime.now(timezone.utc).isoformat()

        try:
            # Users
            for uid, user in db.get("users", {}).items():
                conn.execute(
                    """INSERT OR REPLACE INTO users
                    (id, email, password_hash, name, role, created_at, is_active, monthly_limit, total_spent, settings)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (uid, user.get("email", ""), user.get("password_hash", ""),
                     user.get("name", ""), user.get("role", "user"),
                     user.get("created_at", now), 1 if user.get("is_active", True) else 0,
                     user.get("monthly_limit", 2.0), user.get("total_spent", 0.0),
                     json.dumps(user.get("settings", {}), ensure_ascii=False))
                )

            # Chats
            for cid, chat in db.get("chats", {}).items():
                if isinstance(chat, dict):
                    conn.execute(
                        """INSERT OR REPLACE INTO chats
                        (id, user_id, title, messages, created_at, updated_at, model, variant, total_cost, pinned, archived, orion_mode)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        (cid, chat.get("user_id", "admin"), chat.get("title", "Chat"),
                         json.dumps(chat.get("messages", []), ensure_ascii=False),
                         chat.get("created_at", now), chat.get("updated_at", now),
                         chat.get("model", ""), chat.get("variant", "premium"),
                         chat.get("total_cost", 0.0),
                         1 if chat.get("pinned") else 0,
                         1 if chat.get("archived") else 0,
                         chat.get("orion_mode", "turbo-basic"))
                    )

            # Sessions
            for token, session in db.get("sessions", {}).items():
                if isinstance(session, dict):
                    conn.execute(
                        "INSERT OR REPLACE INTO sessions (token, user_id, created_at, expires_at, ip, user_agent) VALUES (?, ?, ?, ?, ?, ?)",
                        (token, session.get("user_id", ""), session.get("created_at", now),
                         session.get("expires_at", ""),
                         session.get("ip", ""), session.get("user_agent", ""))
                    )

            # Custom agents
            for agent in db.get("custom_agents", []):
                if isinstance(agent, dict):
                    conn.execute(
                        """INSERT OR REPLACE INTO custom_agents
                        (id, name, description, system_prompt, avatar, tools, created_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?)""",
                        (agent.get("id", ""), agent.get("name", ""),
                         agent.get("description", ""), agent.get("system_prompt", ""),
                         agent.get("avatar", ""), json.dumps(agent.get("tools", []), ensure_ascii=False),
                         agent.get("created_at", now))
                    )

            # Connector states
            for cid, state in db.get("connector_states", {}).items():
                if isinstance(state, dict):
                    conn.execute(
                        "INSERT OR REPLACE INTO connector_states (id, enabled, config, updated_at) VALUES (?, ?, ?, ?)",
                        (cid, 1 if state.get("enabled", True) else 0,
                         json.dumps(state.get("config", {}), ensure_ascii=False),
                         state.get("updated_at", now))
                    )

            # KV store for remaining data
            for key in ["analytics", "memory", "ssh_servers", "connections"]:
                if key in db:
                    conn.execute(
                        "INSERT OR REPLACE INTO kv_store (key, value, updated_at) VALUES (?, ?, ?)",
                        (key, json.dumps(db[key], ensure_ascii=False), now)
                    )

            conn.commit()
        except Exception as e:
            conn.rollback()
            logger.error(f"save_db failed: {e}")
            raise




def _migrate_separate_dbs():
    """One-time migration from separate .db files into unified database.sqlite."""
    import glob
    conn = _get_conn()
    
    migrations = {
        "task_charters.db": ("task_charters", "task_charters"),
        "execution_snapshots.db": ("execution_snapshots", "execution_snapshots"),
        "task_scorecards.db": ("task_scorecards", "task_scorecards"),
        "artifact_handoffs.db": ("artifact_handoffs", "artifact_handoffs"),
    }
    
    for db_file, (table_name, source_table) in migrations.items():
        db_path = os.path.join(DATA_DIR, db_file)
        if not os.path.exists(db_path):
            continue
        
        # Check if already migrated (data exists in unified DB)
        count = conn.execute(f"SELECT COUNT(*) FROM {table_name}").fetchone()[0]
        if count > 0:
            logger.info(f"Skipping migration of {db_file}: {count} rows already in unified DB")
            continue
        
        try:
            src = sqlite3.connect(db_path)
            src.row_factory = sqlite3.Row
            rows = src.execute(f"SELECT * FROM {source_table}").fetchall()
            
            if not rows:
                src.close()
                logger.info(f"Skipping {db_file}: empty")
                continue
            
            # Get column names from source
            cols = [desc[0] for desc in src.execute(f"SELECT * FROM {source_table} LIMIT 1").description]
            placeholders = ", ".join(["?"] * len(cols))
            col_names = ", ".join(cols)
            
            for row in rows:
                values = [row[c] for c in cols]
                try:
                    conn.execute(
                        f"INSERT OR IGNORE INTO {table_name} ({col_names}) VALUES ({placeholders})",
                        values
                    )
                except Exception as e:
                    logger.warning(f"Row migration error in {db_file}: {e}")
            
            conn.commit()
            src.close()
            
            # Rename old file as backup
            backup_path = db_path + ".migrated.bak"
            os.rename(db_path, backup_path)
            logger.info(f"Migrated {len(rows)} rows from {db_file} → database.sqlite, old file renamed to .bak")
            
        except Exception as e:
            logger.error(f"Migration of {db_file} failed: {e}")
            conn.rollback()

def close_db():
    """Close thread-local connection."""
    if hasattr(_local, "conn") and _local.conn:
        _local.conn.close()
        _local.conn = None


# Initialize on import
init_db()


# ═══ C4: Point CRUD functions ═══

def get_user(user_id):
    conn = _get_conn()
    try:
        row = conn.execute("SELECT data FROM users WHERE id=?", (user_id,)).fetchone()
        return json.loads(row[0]) if row else None
    finally:
        conn.close()

def update_user(user_id, patch):
    conn = _get_conn()
    try:
        row = conn.execute("SELECT data FROM users WHERE id=?", (user_id,)).fetchone()
        if row:
            user = json.loads(row[0])
            user.update(patch)
            conn.execute("UPDATE users SET data=? WHERE id=?", (json.dumps(user), user_id))
            conn.commit()
            return True
        return False
    finally:
        conn.close()

def get_chat(chat_id):
    conn = _get_conn()
    try:
        row = conn.execute("SELECT data FROM chats WHERE id=?", (chat_id,)).fetchone()
        return json.loads(row[0]) if row else None
    finally:
        conn.close()

def update_chat(chat_id, patch):
    conn = _get_conn()
    try:
        row = conn.execute("SELECT data FROM chats WHERE id=?", (chat_id,)).fetchone()
        if row:
            chat = json.loads(row[0])
            chat.update(patch)
            conn.execute("UPDATE chats SET data=? WHERE id=?", (json.dumps(chat), chat_id))
            conn.commit()
            return True
        return False
    finally:
        conn.close()

def get_setting(key):
    conn = _get_conn()
    try:
        row = conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        return row[0] if row else None
    finally:
        conn.close()

def set_setting(key, value):
    import time as _time
    conn = _get_conn()
    try:
        conn.execute(
            "INSERT OR REPLACE INTO settings (key, value, updated_at) VALUES (?, ?, ?)",
            (key, value, _time.time())
        )
        conn.commit()
    finally:
        conn.close()
