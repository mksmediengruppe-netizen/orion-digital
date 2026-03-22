"""
ORION Digital v1.0 — Backend API Server (Modular)
Split into Flask Blueprints for maintainability.
"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Import the Flask app and shared state
from shared import app

# Import all blueprints
from auth_routes import auth_bp
from file_routes import file_bp
from memory_routes import memory_bp
from admin_routes import admin_bp
from agent_routes import agent_bp
from task_routes import task_bp
from canvas_routes import canvas_bp
from misc_routes import misc_bp
from dashboard_routes import dashboard_bp

# Register blueprints
app.register_blueprint(auth_bp)
app.register_blueprint(file_bp)
app.register_blueprint(memory_bp)
app.register_blueprint(admin_bp)
app.register_blueprint(agent_bp)
app.register_blueprint(task_bp)
app.register_blueprint(canvas_bp)
app.register_blueprint(misc_bp)
app.register_blueprint(dashboard_bp)


# ── TASK 10: Start crash recovery watchdog ──
from crash_recovery import get_crash_recovery
_crash_recovery = get_crash_recovery()
_crash_recovery.start_watchdog()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 3510))
    app.run(host="0.0.0.0", port=port, debug=False)
