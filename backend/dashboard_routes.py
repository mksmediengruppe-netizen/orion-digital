"""Dashboard routes blueprint."""
from flask import Blueprint, jsonify, request

dashboard_bp = Blueprint("dashboard", __name__)

# Lazy import to avoid circular imports
_dashboard = None

def _get_dashboard():
    global _dashboard
    if _dashboard is None:
        from dashboard_api import DashboardAPI
        _dashboard = DashboardAPI()
    return _dashboard


@dashboard_bp.route("/api/dashboard/overview", methods=["GET"])
def dashboard_overview():
    return jsonify(_get_dashboard().overview())

@dashboard_bp.route("/api/dashboard/modules", methods=["GET"])
def dashboard_modules():
    return jsonify(_get_dashboard().modules_status())

@dashboard_bp.route("/api/dashboard/agents", methods=["GET"])
def dashboard_agents():
    return jsonify(_get_dashboard().agents_metrics())

@dashboard_bp.route("/api/dashboard/tasks", methods=["GET"])
def dashboard_tasks():
    limit = request.args.get("limit", 20, type=int)
    return jsonify(_get_dashboard().tasks_list(limit))

@dashboard_bp.route("/api/dashboard/artifacts", methods=["GET"])
def dashboard_artifacts():
    return jsonify(_get_dashboard().artifacts_list())

@dashboard_bp.route("/api/dashboard/operators", methods=["GET"])
def dashboard_operators():
    limit = request.args.get("limit", 10, type=int)
    return jsonify(_get_dashboard().operators_history(limit))

@dashboard_bp.route("/api/dashboard/verification", methods=["GET"])
def dashboard_verification():
    return jsonify(_get_dashboard().verification_summary())

@dashboard_bp.route("/api/dashboard/prompts", methods=["GET"])
def dashboard_prompts():
    return jsonify(_get_dashboard().prompts_stats())

@dashboard_bp.route("/api/dashboard/projects", methods=["GET"])
def dashboard_projects():
    return jsonify(_get_dashboard().projects_list())

@dashboard_bp.route("/api/dashboard/health_full", methods=["GET"])
def dashboard_health():
    return jsonify(_get_dashboard().health_check())
