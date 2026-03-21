"""
ORION Digital — Canvas Routes Blueprint
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

canvas_bp = Blueprint("canvas", __name__)


@canvas_bp.route("/api/canvas", methods=["GET"])
def list_canvases():
    """List all canvas documents for the user."""
    try:
        from project_manager import list_canvases as pm_list_canvases
        user_id = request.args.get("user_id", "default")
        canvases = pm_list_canvases(user_id)
        return jsonify({"success": True, "canvases": canvases})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500



@canvas_bp.route("/api/canvas/<canvas_id>", methods=["GET"])
def get_canvas(canvas_id):
    """Get a specific canvas document."""
    try:
        from project_manager import get_canvas as pm_get_canvas
        canvas = pm_get_canvas(canvas_id)
        if canvas:
            return jsonify({"success": True, "canvas": canvas})
        return jsonify({"success": False, "error": "Canvas not found"}), 404
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500



@canvas_bp.route("/api/canvas/<canvas_id>", methods=["PUT"])
def update_canvas(canvas_id):
    """Update a canvas document."""
    try:
        from project_manager import update_canvas as pm_update_canvas
        data = request.get_json()
        content = data.get("content", "")
        title = data.get("title")
        result = pm_update_canvas(canvas_id, content, title)
        return jsonify(result)
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500



@canvas_bp.route("/api/canvas/<canvas_id>", methods=["DELETE"])
def delete_canvas(canvas_id):
    """Delete a canvas document."""
    try:
        from project_manager import delete_canvas as pm_delete_canvas
        result = pm_delete_canvas(canvas_id)
        return jsonify(result)
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


