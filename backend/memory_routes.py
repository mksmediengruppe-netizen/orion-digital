"""
ORION Digital — Memory Routes Blueprint
"""
from flask import Blueprint, request, jsonify, Response, stream_with_context
import json
import time
import os
import logging
import threading
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

# Import shared state and helpers
from shared import (
    app, db_read, db_write, require_auth, require_admin,
    _now_iso, _calc_cost, _get_memory, _get_versions, _get_rate_limiter,
    _encrypt_setting, _decrypt_setting, _SECRET_SETTINGS_KEYS,
    _running_tasks, _tasks_lock, _interrupt_lock, _active_agents, _agents_lock,
    OPENROUTER_API_KEY, OPENROUTER_BASE_URL, DATA_DIR, UPLOAD_DIR,
    _lock, _USE_SQLITE,
)

from memory import get_memory, MemoryEntry, MemoryType

try:
    from project_memory import ProjectMemory
except ImportError:
    ProjectMemory = None

memory_bp = Blueprint("memory", __name__)


@memory_bp.route("/api/memory/search", methods=["POST"])
@require_auth
def search_memory():
    """Search memory — both legacy episodic and vector memory."""
    data = request.get_json() or {}
    query = data.get("query", "").lower()
    limit = data.get("limit", 5)

    # Legacy episodic search
    db = db_read()
    episodes = db.get("memory", {}).get("episodic", [])
    legacy_results = []
    for ep in reversed(episodes):
        task = ep.get("task", "").lower()
        score = sum(1 for word in query.split() if word in task)
        if score > 0:
            legacy_results.append({**ep, "relevance": score, "source": "episodic"})
    legacy_results.sort(key=lambda x: x["relevance"], reverse=True)

    # Vector memory search (cross-chat)
    vector_results = []
    try:
        vmem = _get_memory()
        vector_results = vmem.search(query, limit=limit, user_id=request.user_id)
        for vr in vector_results:
            vr["source"] = "vector"
    except Exception as _vec_err:
        logging.warning(f"Vector search error: {_vec_err}")

    return jsonify({
        "results": legacy_results[:limit],
        "vector_results": vector_results[:limit]
    })



@memory_bp.route("/api/memory/context", methods=["POST"])
@require_auth
def get_memory_context():
    """Get relevant memory context for a query (cross-chat learning)."""
    data = request.get_json() or {}
    query = data.get("query", "")
    if not query:
        return jsonify({"context": ""})

    try:
        vmem = _get_memory()
        context = vmem.get_relevant_context(query, user_id=request.user_id)
        return jsonify({"context": context})
    except Exception as e:
        return jsonify({"context": "", "error": str(e)})



@memory_bp.route("/api/memory/stats", methods=["GET"])
@require_auth
def memory_stats():
    """Get memory statistics."""
    try:
        vmem = _get_memory()
        return jsonify(vmem.get_stats())
    except Exception as e:
        return jsonify({"error": str(e)})


# ── File Versioning API ─────────────────────────────────────────────

@memory_bp.route("/api/memory", methods=["GET"])
def list_memories():
    """List stored memories."""
    try:
        from project_manager import get_memory_items
        user_id = request.args.get("user_id", "default")
        memories = get_memory_items(user_id)
        return jsonify({"success": True, "memories": memories})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500



@memory_bp.route("/api/memory", methods=["POST"])
def store_memory_api():
    """Store a new memory."""
    try:
        from project_manager import store_memory
        data = request.get_json()
        key = data.get("key", "")
        value = data.get("value", "")
        user_id = data.get("user_id", "default")
        category = data.get("category", "fact")
        result = store_memory(key, value, user_id, category=category)
        return jsonify(result)
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500



@memory_bp.route("/api/memory/<memory_id>", methods=["DELETE"])
def delete_memory(memory_id):
    """Delete a memory entry."""
    try:
        from project_manager import delete_memory as pm_delete_memory
        result = pm_delete_memory(memory_id)
        return jsonify(result)
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@memory_bp.route("/api/admin/memory", methods=["GET"])
@require_auth
@require_admin
def admin_list_memory():
    """List all memory entries across all users (admin only)."""
    try:
        # Collect from multiple sources
        all_memories = []
        
        # Source 1: Session memory (sessions_admin.json)
        session_file = os.path.join(DATA_DIR, "memory", "sessions_admin.json")
        if os.path.exists(session_file):
            try:
                with open(session_file, "r") as f:
                    sessions = json.load(f)
                for sid, sess in sessions.items():
                    all_memories.append({
                        "id": f"session_{sid}",
                        "type": "session",
                        "user_id": sess.get("user_id", "unknown"),
                        "key": sess.get("task", "")[:80] or f"Session {sid}",
                        "value": json.dumps({
                            "status": sess.get("status"),
                            "decisions": len(sess.get("decisions", [])),
                            "files_modified": len(sess.get("files_modified", [])),
                            "commands": len(sess.get("commands_executed", [])),
                            "errors": len(sess.get("errors", [])),
                            "key_facts": len(sess.get("key_facts", []))
                        }, ensure_ascii=False),
                        "category": "session",
                        "source": "session_memory",
                        "created_at": sess.get("created_at", ""),
                        "chat_id": sess.get("chat_id", "")
                    })
            except Exception as e:
                logging.warning(f"Failed to load session memory: {e}")
        
        # Source 2: Persistent memory (project_manager)
        try:
            from project_manager import get_memory_items
            db = _load_db()
            for uid in db.get("users", {}):
                items = get_memory_items(uid, limit=100)
                for item in items:
                    all_memories.append({
                        "id": item.get("id", ""),
                        "type": "persistent",
                        "user_id": item.get("user_id", uid),
                        "key": item.get("key", ""),
                        "value": item.get("value", ""),
                        "category": item.get("category", "fact"),
                        "source": "persistent",
                        "confidence": item.get("confidence", 0),
                        "pinned": item.get("pinned", False),
                        "created_at": item.get("created_at", ""),
                        "updated_at": item.get("updated_at", "")
                    })
        except Exception as e:
            logging.warning(f"Failed to load persistent memory: {e}")
        
        # Source 3: Solution cache (memory_v9)
        solution_cache_db = os.path.join(DATA_DIR, "..", "memory_v9", "data", "solution_cache.db")
        if os.path.exists(solution_cache_db):
            try:
                import sqlite3
                conn = sqlite3.connect(solution_cache_db)
                c = conn.cursor()
                tables = [t[0] for t in c.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
                for table in tables:
                    try:
                        c.execute(f"SELECT COUNT(*) FROM [{table}]")
                        count = c.fetchone()[0]
                        if count > 0:
                            all_memories.append({
                                "id": f"cache_{table}",
                                "type": "cache",
                                "user_id": "system",
                                "key": f"Solution Cache: {table}",
                                "value": f"{count} cached entries",
                                "category": "cache",
                                "source": "solution_cache"
                            })
                    except:
                        pass
                conn.close()
            except Exception as e:
                logging.warning(f"Failed to load solution cache: {e}")
        
        # Sort by created_at descending
        all_memories.sort(key=lambda x: x.get("created_at", ""), reverse=True)
        
        return jsonify({
            "success": True,
            "memories": all_memories,
            "total": len(all_memories),
            "sources": {
                "sessions": sum(1 for m in all_memories if m["type"] == "session"),
                "persistent": sum(1 for m in all_memories if m["type"] == "persistent"),
                "cache": sum(1 for m in all_memories if m["type"] == "cache")
            }
        })
    except Exception as e:
        logging.error(f"Admin memory list error: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@memory_bp.route("/api/admin/memory/<memory_id>", methods=["DELETE"])
@require_auth
@require_admin
def admin_delete_memory(memory_id):
    """Delete a memory entry (admin only)."""
    try:
        if memory_id.startswith("session_"):
            # Delete from session memory
            sid = memory_id[8:]  # Remove "session_" prefix
            session_file = os.path.join(DATA_DIR, "memory", "sessions_admin.json")
            if os.path.exists(session_file):
                with open(session_file, "r") as f:
                    sessions = json.load(f)
                if sid in sessions:
                    del sessions[sid]
                    with open(session_file, "w") as f:
                        json.dump(sessions, f, ensure_ascii=False, indent=2)
                    return jsonify({"success": True, "deleted": memory_id})
            return jsonify({"success": False, "error": "Session not found"}), 404
        else:
            # Delete from persistent memory
            from project_manager import delete_memory as pm_delete
            result = pm_delete(memory_id)
            return jsonify(result)
    except Exception as e:
        logging.error(f"Admin memory delete error: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@memory_bp.route("/api/admin/memory", methods=["POST"])
@require_auth
@require_admin
def admin_add_memory():
    """Add a memory entry manually (admin only)."""
    try:
        from project_manager import store_memory
        data = request.get_json()
        key = data.get("key", "")
        value = data.get("value", "")
        user_id = data.get("user_id", "admin")
        category = data.get("category", "fact")
        if not key or not value:
            return jsonify({"success": False, "error": "Key and value required"}), 400
        result = store_memory(key, value, user_id, source="admin_manual", category=category)
        return jsonify(result)
    except Exception as e:
        logging.error(f"Admin memory add error: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@memory_bp.route("/api/admin/memory/clear-sessions", methods=["POST"])
@require_auth
@require_admin
def admin_clear_session_memory():
    """Clear all session memory entries (admin only)."""
    try:
        session_file = os.path.join(DATA_DIR, "memory", "sessions_admin.json")
        if os.path.exists(session_file):
            with open(session_file, "r") as f:
                sessions = json.load(f)
            count = len(sessions)
            with open(session_file, "w") as f:
                json.dump({}, f)
            return jsonify({"success": True, "cleared": count})
        return jsonify({"success": True, "cleared": 0})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500




@memory_bp.route("/api/project-memory/context", methods=["POST"])
@require_auth
def get_project_memory_context():
    """Get full project memory context for a chat."""
    data = request.get_json() or {}
    chat_id = data.get("chat_id", "")
    project_id = data.get("project_id")
    pm = ProjectMemory(user_id=request.user_id, project_id=project_id)
    context = pm.get_full_context(chat_id)
    return jsonify({"success": True, "context": context, "length": len(context)})



@memory_bp.route("/api/project-memory/active-tasks", methods=["GET"])
@require_auth
def get_active_tasks_api():
    """Get all active/paused tasks."""
    pm = ProjectMemory(user_id=request.user_id)
    tasks = pm.get_active_tasks()
    return jsonify({"success": True, "tasks": tasks, "count": len(tasks)})



@memory_bp.route("/api/project-memory/checkpoint", methods=["POST"])
@require_auth
def save_task_checkpoint():
    """Save a task checkpoint for later resumption."""
    data = request.get_json() or {}
    pm = ProjectMemory(user_id=request.user_id, project_id=data.get("project_id"))
    result = pm.save_checkpoint(
        chat_id=data.get("chat_id", ""),
        task=data.get("task", ""),
        progress=data.get("progress", ""),
        steps_completed=data.get("steps_completed", []),
        steps_remaining=data.get("steps_remaining", []),
        context=data.get("context", {})
    )
    return jsonify({"success": True, "checkpoint": result})


