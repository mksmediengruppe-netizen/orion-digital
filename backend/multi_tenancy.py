"""
ORION Multi-Tenancy Support
============================
Adds organization (org_id) and workspace isolation to ORION.

This module provides:
1. Database migration to add org_id columns
2. Middleware to inject org_id into request context
3. Helper functions for org-scoped queries

Usage:
    from multi_tenancy import init_multi_tenancy, get_org_id
    
    # In app startup:
    init_multi_tenancy(app, db)
    
    # In route handlers:
    org_id = get_org_id()  # from Flask g context
"""

import logging
import sqlite3
from functools import wraps
from flask import g, request, jsonify

logger = logging.getLogger(__name__)


# ── Database Migration ──

def migrate_add_org_id(db):
    """Add org_id column to relevant tables if not exists."""
    tables_to_migrate = [
        ("users", "org_id TEXT DEFAULT 'default'"),
        ("chats", "org_id TEXT DEFAULT 'default'"),
        ("custom_agents", "org_id TEXT DEFAULT 'default'"),
        ("audit_log", "org_id TEXT DEFAULT 'default'"),
        ("analytics", "org_id TEXT DEFAULT 'default'"),
    ]
    
    conn = db.get_connection() if hasattr(db, 'get_connection') else db
    cursor = conn.cursor()
    
    for table, column_def in tables_to_migrate:
        try:
            # Check if column already exists
            cursor.execute(f"PRAGMA table_info({table})")
            columns = [row[1] for row in cursor.fetchall()]
            if "org_id" not in columns:
                cursor.execute(f"ALTER TABLE {table} ADD COLUMN {column_def}")
                logger.info(f"[MULTI_TENANCY] Added org_id to {table}")
        except sqlite3.OperationalError as e:
            logger.debug(f"[MULTI_TENANCY] Skip {table}: {e}")
    
    # Create organizations table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS organizations (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            plan TEXT DEFAULT 'free',
            max_users INTEGER DEFAULT 5,
            max_monthly_budget REAL DEFAULT 10.0,
            settings TEXT DEFAULT '{}',
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            is_active INTEGER DEFAULT 1
        )
    """)
    
    # Create index for org_id lookups
    try:
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_chats_org ON chats(org_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_users_org ON users(org_id)")
    except sqlite3.OperationalError:
        pass
    
    # Insert default organization if not exists
    cursor.execute("""
        INSERT OR IGNORE INTO organizations (id, name, plan, max_users, max_monthly_budget)
        VALUES ('default', 'Default Organization', 'enterprise', 100, 1000.0)
    """)
    
    conn.commit()
    logger.info("[MULTI_TENANCY] Migration complete")


# ── Middleware ──

def get_org_id() -> str:
    """Get current organization ID from request context."""
    return getattr(g, 'org_id', 'default')


def org_middleware():
    """Flask before_request middleware to set org_id in g context."""
    # Extract org_id from:
    # 1. X-Org-Id header (for API clients)
    # 2. User's org_id from session/token
    # 3. Default to 'default'
    
    org_id = request.headers.get('X-Org-Id')
    
    if not org_id:
        # Try to get from authenticated user
        user = getattr(g, 'user', None)
        if user and isinstance(user, dict):
            org_id = user.get('org_id', 'default')
    
    g.org_id = org_id or 'default'


def require_org_access(f):
    """Decorator to ensure user has access to the requested org."""
    @wraps(f)
    def decorated(*args, **kwargs):
        user = getattr(g, 'user', None)
        if not user:
            return jsonify({"error": "Authentication required"}), 401
        
        user_org = user.get('org_id', 'default') if isinstance(user, dict) else 'default'
        request_org = get_org_id()
        
        # Admin can access any org
        user_role = user.get('role', 'user') if isinstance(user, dict) else 'user'
        if user_role == 'admin':
            return f(*args, **kwargs)
        
        # Regular users can only access their own org
        if user_org != request_org:
            return jsonify({"error": "Access denied to this organization"}), 403
        
        return f(*args, **kwargs)
    return decorated


# ── Query Helpers ──

def org_filter(query: str, params: list, org_id: str = None) -> tuple:
    """Add org_id filter to SQL query.
    
    Usage:
        query = "SELECT * FROM chats WHERE user_id = ?"
        params = [user_id]
        query, params = org_filter(query, params)
        # Result: "SELECT * FROM chats WHERE user_id = ? AND org_id = ?"
    """
    org = org_id or get_org_id()
    if "WHERE" in query.upper():
        query += " AND org_id = ?"
    else:
        query += " WHERE org_id = ?"
    params.append(org)
    return query, params


# ── Init ──

def init_multi_tenancy(app, db=None):
    """Initialize multi-tenancy support for the Flask app."""
    app.before_request(org_middleware)
    
    if db:
        try:
            migrate_add_org_id(db)
        except Exception as e:
            logger.warning(f"[MULTI_TENANCY] Migration skipped: {e}")
    
    logger.info("[MULTI_TENANCY] Initialized")
