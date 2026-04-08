"""
ARCANE Memory v9 — Conversation Continuity
Saves checkpoints so interrupted tasks can resume.
"""
from __future__ import annotations
import json
import logging
import os
logger = logging.getLogger("memory.continuity")

_CHECKPOINT_DIR = os.path.join(
    os.environ.get("ARCANE_WORKSPACE", "/root/workspace"),
    ".checkpoints"
)


class ContinuityManager:
    """Saves/restores task state across interruptions."""

    def save_checkpoint(self, task_id: str, state: dict) -> None:
        try:
            os.makedirs(_CHECKPOINT_DIR, exist_ok=True)
            with open(os.path.join(_CHECKPOINT_DIR, f"{task_id}.json"), "w") as f:
                json.dump(state, f)
        except Exception as e:
            logger.debug(f"Checkpoint save failed for {task_id}: {e}")

    def restore_checkpoint(self, task_id: str) -> dict | None:
        try:
            path = os.path.join(_CHECKPOINT_DIR, f"{task_id}.json")
            if os.path.exists(path):
                with open(path) as f:
                    return json.load(f)
        except Exception as e:
            logger.debug(f"Checkpoint restore failed for {task_id}: {e}")
        return None

    def clear_checkpoint(self, task_id: str) -> None:
        try:
            path = os.path.join(_CHECKPOINT_DIR, f"{task_id}.json")
            if os.path.exists(path):
                os.remove(path)
        except Exception:
            pass

    def get_project_resume(self, project_id: str):
        """Return saved resume pointer for a project (last failed run)."""
        import os, json
        path = os.path.join(_CHECKPOINT_DIR, f"resume_{project_id}.json")
        if not os.path.exists(path):
            return None
        try:
            with open(path, "r") as f:
                return json.load(f)
        except Exception:
            return None

    def save_project_resume(self, project_id: str, data: dict):
        """Save resume pointer so next run can continue from last stage."""
        import os, json
        os.makedirs(_CHECKPOINT_DIR, exist_ok=True)
        path = os.path.join(_CHECKPOINT_DIR, f"resume_{project_id}.json")
        with open(path, "w") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def clear_project_resume(self, project_id: str):
        """Clear resume pointer after successful completion."""
        import os
        path = os.path.join(_CHECKPOINT_DIR, f"resume_{project_id}.json")
        if os.path.exists(path):
            os.remove(path)

