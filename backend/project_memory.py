"""
Project Memory v6.0 — Cross-Session Context Persistence
========================================================

Extends project_manager.py with:
- Session context: auto-save/restore conversation context between sessions
- Decision log: track architectural decisions, tool choices, outcomes
- Task continuity: resume interrupted tasks from where they left off
- Smart recall: semantic search across all memory types
- Auto-summary: compress long conversations into key points
- Cross-project learning: share patterns across projects

Storage:
- JSON files in DATA_DIR/memory/
- Separate files per user for isolation
- Automatic cleanup of stale sessions
"""

import os
import json
import time
import hashlib
import logging
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, List, Optional

logger = logging.getLogger("project_memory")

DATA_DIR = os.environ.get("DATA_DIR", "/var/www/orion/backend/data")
MEMORY_DIR = os.path.join(DATA_DIR, "memory")
os.makedirs(MEMORY_DIR, exist_ok=True)


# ══════════════════════════════════════════════════════════════
# SESSION CONTEXT — Auto-save/restore between sessions
# ══════════════════════════════════════════════════════════════

class SessionContext:
    """
    Manages conversation context that persists between sessions.
    
    Each session stores:
    - Last task description and status
    - Key decisions made
    - Files created/modified
    - Commands executed
    - Errors encountered and fixes applied
    - Summary of what was accomplished
    """

    def __init__(self, user_id: str, project_id: str = None):
        self.user_id = user_id
        self.project_id = project_id or "global"
        self._path = os.path.join(MEMORY_DIR, f"sessions_{user_id}.json")
        self._sessions = self._load()

    def _load(self) -> dict:
        try:
            if os.path.exists(self._path):
                with open(self._path, "r") as f:
                    return json.load(f)
        except Exception as e:
            logger.warning(f"Failed to load sessions: {e}")
        return {}

    def _save(self):
        try:
            os.makedirs(os.path.dirname(self._path), exist_ok=True)
            with open(self._path, "w") as f:
                json.dump(self._sessions, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.error(f"Failed to save sessions: {e}")

    def start_session(self, chat_id: str, task_description: str = "") -> dict:
        """Start a new session or resume existing one."""
        session = self._sessions.get(chat_id, {
            "chat_id": chat_id,
            "project_id": self.project_id,
            "user_id": self.user_id,
            "task": task_description,
            "status": "active",
            "decisions": [],
            "files_modified": [],
            "commands_executed": [],
            "errors": [],
            "key_facts": [],
            "summary": "",
            "started_at": datetime.now(timezone.utc).isoformat(),
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "resumed_count": 0
        })

        if chat_id in self._sessions:
            session["resumed_count"] = session.get("resumed_count", 0) + 1
            session["status"] = "resumed"

        session["updated_at"] = datetime.now(timezone.utc).isoformat()
        self._sessions[chat_id] = session
        self._save()
        return session

    def log_decision(self, chat_id: str, decision: str, reason: str = "",
                     category: str = "general") -> None:
        """Log an architectural or tool decision."""
        if chat_id not in self._sessions:
            return

        self._sessions[chat_id]["decisions"].append({
            "decision": decision,
            "reason": reason,
            "category": category,
            "timestamp": datetime.now(timezone.utc).isoformat()
        })
        self._sessions[chat_id]["updated_at"] = datetime.now(timezone.utc).isoformat()
        self._save()

    def log_file_change(self, chat_id: str, filepath: str,
                        action: str = "created") -> None:
        """Log a file creation or modification."""
        if chat_id not in self._sessions:
            return

        self._sessions[chat_id]["files_modified"].append({
            "path": filepath,
            "action": action,
            "timestamp": datetime.now(timezone.utc).isoformat()
        })
        self._save()

    def log_command(self, chat_id: str, command: str,
                    success: bool = True, output: str = "") -> None:
        """Log an executed command."""
        if chat_id not in self._sessions:
            return

        self._sessions[chat_id]["commands_executed"].append({
            "command": command[:500],
            "success": success,
            "output": output[:200],
            "timestamp": datetime.now(timezone.utc).isoformat()
        })
        # Keep only last 50 commands
        self._sessions[chat_id]["commands_executed"] = \
            self._sessions[chat_id]["commands_executed"][-50:]
        self._save()

    def log_error(self, chat_id: str, error: str,
                  fix_applied: str = "") -> None:
        """Log an error and its fix."""
        if chat_id not in self._sessions:
            return

        self._sessions[chat_id]["errors"].append({
            "error": error[:500],
            "fix": fix_applied[:500],
            "timestamp": datetime.now(timezone.utc).isoformat()
        })
        self._save()

    def add_key_fact(self, chat_id: str, fact: str,
                     category: str = "general") -> None:
        """Add a key fact discovered during the session."""
        if chat_id not in self._sessions:
            return

        self._sessions[chat_id]["key_facts"].append({
            "fact": fact,
            "category": category,
            "timestamp": datetime.now(timezone.utc).isoformat()
        })
        self._save()

    def set_summary(self, chat_id: str, summary: str) -> None:
        """Set session summary (usually at the end)."""
        if chat_id not in self._sessions:
            return

        self._sessions[chat_id]["summary"] = summary
        self._sessions[chat_id]["status"] = "completed"
        self._sessions[chat_id]["updated_at"] = datetime.now(timezone.utc).isoformat()
        self._save()

    def get_session(self, chat_id: str) -> Optional[dict]:
        """Get session data."""
        return self._sessions.get(chat_id)

    def get_recent_sessions(self, limit: int = 5) -> List[dict]:
        """Get recent sessions for this user/project."""
        sessions = [
            s for s in self._sessions.values()
            if s.get("project_id") == self.project_id
        ]
        sessions.sort(key=lambda x: x.get("updated_at", ""), reverse=True)
        return sessions[:limit]

    def get_context_for_prompt(self, chat_id: str = None) -> str:
        """
        Generate context string for injection into system prompt.
        Includes current session + recent sessions summary.
        """
        parts = []

        # Current session context
        if chat_id and chat_id in self._sessions:
            session = self._sessions[chat_id]
            if session.get("task"):
                parts.append(f"## Текущая задача\n{session['task']}")

            if session.get("decisions"):
                parts.append("## Принятые решения")
                for d in session["decisions"][-5:]:
                    parts.append(f"- {d['decision']}")
                    if d.get("reason"):
                        parts.append(f"  Причина: {d['reason']}")

            if session.get("files_modified"):
                parts.append("## Изменённые файлы")
                for f in session["files_modified"][-10:]:
                    parts.append(f"- [{f['action']}] {f['path']}")

            if session.get("errors"):
                parts.append("## Известные проблемы")
                for e in session["errors"][-3:]:
                    parts.append(f"- Ошибка: {e['error'][:100]}")
                    if e.get("fix"):
                        parts.append(f"  Исправление: {e['fix'][:100]}")

            if session.get("key_facts"):
                parts.append("## Ключевые факты")
                for kf in session["key_facts"][-10:]:
                    parts.append(f"- {kf['fact']}")

        # Recent sessions summary
        recent = self.get_recent_sessions(3)
        if recent:
            completed = [s for s in recent if s.get("summary") and s.get("chat_id") != chat_id]
            if completed:
                parts.append("\n## Предыдущие сессии")
                for s in completed[:3]:
                    task = s.get("task", "")[:100]
                    summary = s.get("summary", "")[:200]
                    parts.append(f"- Задача: {task}")
                    if summary:
                        parts.append(f"  Результат: {summary}")

        return "\n".join(parts) if parts else ""

    def cleanup_old_sessions(self, days: int = 30) -> int:
        """Remove sessions older than N days."""
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        removed = 0

        for chat_id in list(self._sessions.keys()):
            session = self._sessions[chat_id]
            if session.get("updated_at", "") < cutoff:
                del self._sessions[chat_id]
                removed += 1

        if removed:
            self._save()
        return removed


# ══════════════════════════════════════════════════════════════
# DECISION LOG — Track decisions across sessions
# ══════════════════════════════════════════════════════════════

class DecisionLog:
    """
    Persistent log of architectural and technical decisions.
    Helps maintain consistency across sessions.
    """

    def __init__(self, user_id: str):
        self.user_id = user_id
        self._path = os.path.join(MEMORY_DIR, f"decisions_{user_id}.json")
        self._decisions = self._load()

    def _load(self) -> list:
        try:
            if os.path.exists(self._path):
                with open(self._path, "r") as f:
                    return json.load(f)
        except Exception:
            pass
        return []

    def _save(self):
        try:
            os.makedirs(os.path.dirname(self._path), exist_ok=True)
            with open(self._path, "w") as f:
                json.dump(self._decisions, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.error(f"Failed to save decisions: {e}")

    def log(self, decision: str, reason: str = "", category: str = "general",
            project_id: str = None, chat_id: str = None,
            outcome: str = "") -> dict:
        """Log a decision."""
        entry = {
            "id": hashlib.md5(f"{self.user_id}:{decision}:{time.time()}".encode()).hexdigest()[:10],
            "decision": decision,
            "reason": reason,
            "category": category,
            "project_id": project_id,
            "chat_id": chat_id,
            "outcome": outcome,
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
        self._decisions.append(entry)
        # Keep last 200 decisions
        self._decisions = self._decisions[-200:]
        self._save()
        return entry

    def get_decisions(self, category: str = None, project_id: str = None,
                      limit: int = 20) -> List[dict]:
        """Get decisions, optionally filtered."""
        items = self._decisions
        if category:
            items = [d for d in items if d.get("category") == category]
        if project_id:
            items = [d for d in items if d.get("project_id") == project_id]
        return items[-limit:]

    def get_context_for_prompt(self, project_id: str = None) -> str:
        """Get decisions formatted for system prompt."""
        decisions = self.get_decisions(project_id=project_id, limit=10)
        if not decisions:
            return ""

        parts = ["## Принятые архитектурные решения"]
        for d in decisions:
            parts.append(f"- {d['decision']}")
            if d.get("reason"):
                parts.append(f"  Причина: {d['reason']}")
            if d.get("outcome"):
                parts.append(f"  Результат: {d['outcome']}")

        return "\n".join(parts)


# ══════════════════════════════════════════════════════════════
# TASK CONTINUITY — Resume interrupted tasks
# ══════════════════════════════════════════════════════════════

class TaskContinuity:
    """
    Manages task state for resuming interrupted work.
    Saves checkpoints that can be restored in new sessions.
    """

    def __init__(self, user_id: str):
        self.user_id = user_id
        self._path = os.path.join(MEMORY_DIR, f"tasks_{user_id}.json")
        self._tasks = self._load()

    def _load(self) -> dict:
        try:
            if os.path.exists(self._path):
                with open(self._path, "r") as f:
                    return json.load(f)
        except Exception:
            pass
        return {}

    def _save(self):
        try:
            os.makedirs(os.path.dirname(self._path), exist_ok=True)
            with open(self._path, "w") as f:
                json.dump(self._tasks, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.error(f"Failed to save tasks: {e}")

    def save_checkpoint(self, chat_id: str, task_description: str,
                        progress: str, steps_completed: List[str] = None,
                        steps_remaining: List[str] = None,
                        context: dict = None) -> dict:
        """Save a task checkpoint for later resumption."""
        checkpoint = {
            "chat_id": chat_id,
            "user_id": self.user_id,
            "task": task_description,
            "progress": progress,
            "steps_completed": steps_completed or [],
            "steps_remaining": steps_remaining or [],
            "context": context or {},
            "status": "paused",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "updated_at": datetime.now(timezone.utc).isoformat()
        }
        self._tasks[chat_id] = checkpoint
        self._save()
        return checkpoint

    def get_checkpoint(self, chat_id: str) -> Optional[dict]:
        """Get checkpoint for a chat."""
        return self._tasks.get(chat_id)

    def get_active_tasks(self) -> List[dict]:
        """Get all paused/active tasks."""
        return [
            t for t in self._tasks.values()
            if t.get("status") in ("paused", "active")
        ]

    def complete_task(self, chat_id: str, summary: str = "") -> dict:
        """Mark task as completed."""
        if chat_id in self._tasks:
            self._tasks[chat_id]["status"] = "completed"
            self._tasks[chat_id]["summary"] = summary
            self._tasks[chat_id]["updated_at"] = datetime.now(timezone.utc).isoformat()
            self._save()
            return self._tasks[chat_id]
        return {"error": "Task not found"}

    def get_resume_prompt(self, chat_id: str) -> str:
        """Generate a prompt for resuming a task."""
        task = self._tasks.get(chat_id)
        if not task:
            return ""

        parts = [f"## Продолжение задачи\n{task['task']}"]

        if task.get("progress"):
            parts.append(f"\n## Текущий прогресс\n{task['progress']}")

        if task.get("steps_completed"):
            parts.append("\n## Выполненные шаги")
            for step in task["steps_completed"]:
                parts.append(f"- ✅ {step}")

        if task.get("steps_remaining"):
            parts.append("\n## Оставшиеся шаги")
            for step in task["steps_remaining"]:
                parts.append(f"- ⬜ {step}")

        if task.get("context"):
            ctx = task["context"]
            if ctx.get("server"):
                parts.append(f"\n## Сервер: {ctx['server']}")
            if ctx.get("tech_stack"):
                parts.append(f"## Стек: {ctx['tech_stack']}")

        return "\n".join(parts)


# ══════════════════════════════════════════════════════════════
# CROSS-PROJECT LEARNING — Share patterns across projects
# ══════════════════════════════════════════════════════════════

class CrossProjectLearning:
    """
    Learns patterns from completed tasks and applies them to new ones.
    Stores: common errors, successful solutions, tool preferences.
    """

    def __init__(self, user_id: str):
        self.user_id = user_id
        self._path = os.path.join(MEMORY_DIR, f"learning_{user_id}.json")
        self._patterns = self._load()

    def _load(self) -> dict:
        try:
            if os.path.exists(self._path):
                with open(self._path, "r") as f:
                    return json.load(f)
        except Exception:
            pass
        return {
            "error_solutions": [],
            "tool_preferences": {},
            "successful_patterns": [],
            "tech_stack_notes": {}
        }

    def _save(self):
        try:
            os.makedirs(os.path.dirname(self._path), exist_ok=True)
            with open(self._path, "w") as f:
                json.dump(self._patterns, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.error(f"Failed to save learning: {e}")

    def learn_error_solution(self, error_pattern: str, solution: str,
                             context: str = "") -> None:
        """Store a successful error resolution."""
        self._patterns["error_solutions"].append({
            "error": error_pattern[:300],
            "solution": solution[:500],
            "context": context[:200],
            "uses": 0,
            "timestamp": datetime.now(timezone.utc).isoformat()
        })
        # Keep last 100
        self._patterns["error_solutions"] = self._patterns["error_solutions"][-100:]
        self._save()

    def find_solution(self, error_text: str) -> Optional[dict]:
        """Find a known solution for an error."""
        error_lower = error_text.lower()
        for sol in reversed(self._patterns["error_solutions"]):
            if sol["error"].lower() in error_lower or \
               any(word in error_lower for word in sol["error"].lower().split()[:3]):
                sol["uses"] = sol.get("uses", 0) + 1
                self._save()
                return sol
        return None

    def learn_tool_preference(self, task_type: str, tool_name: str,
                              success: bool = True) -> None:
        """Track which tools work best for which task types."""
        if task_type not in self._patterns["tool_preferences"]:
            self._patterns["tool_preferences"][task_type] = {}

        prefs = self._patterns["tool_preferences"][task_type]
        if tool_name not in prefs:
            prefs[tool_name] = {"success": 0, "fail": 0}

        if success:
            prefs[tool_name]["success"] += 1
        else:
            prefs[tool_name]["fail"] += 1

        self._save()

    def get_preferred_tools(self, task_type: str) -> List[str]:
        """Get tools ranked by success rate for a task type."""
        prefs = self._patterns["tool_preferences"].get(task_type, {})
        if not prefs:
            return []

        ranked = []
        for tool, stats in prefs.items():
            total = stats["success"] + stats["fail"]
            if total > 0:
                rate = stats["success"] / total
                ranked.append((tool, rate, total))

        ranked.sort(key=lambda x: (x[1], x[2]), reverse=True)
        return [t[0] for t in ranked]

    def learn_pattern(self, pattern_name: str, description: str,
                      steps: List[str] = None) -> None:
        """Store a successful pattern/workflow."""
        self._patterns["successful_patterns"].append({
            "name": pattern_name,
            "description": description,
            "steps": steps or [],
            "uses": 0,
            "timestamp": datetime.now(timezone.utc).isoformat()
        })
        self._patterns["successful_patterns"] = \
            self._patterns["successful_patterns"][-50:]
        self._save()

    def note_tech_stack(self, project_id: str, tech: str,
                        notes: str = "") -> None:
        """Note tech stack details for a project."""
        if project_id not in self._patterns["tech_stack_notes"]:
            self._patterns["tech_stack_notes"][project_id] = []

        self._patterns["tech_stack_notes"][project_id].append({
            "tech": tech,
            "notes": notes,
            "timestamp": datetime.now(timezone.utc).isoformat()
        })
        self._save()

    def get_context_for_prompt(self) -> str:
        """Get learning context for system prompt."""
        parts = []

        # Recent error solutions
        recent_solutions = self._patterns["error_solutions"][-5:]
        if recent_solutions:
            parts.append("## Известные решения проблем")
            for sol in recent_solutions:
                parts.append(f"- Ошибка: {sol['error'][:80]}")
                parts.append(f"  Решение: {sol['solution'][:100]}")

        # Successful patterns
        patterns = self._patterns["successful_patterns"][-3:]
        if patterns:
            parts.append("\n## Проверенные паттерны")
            for p in patterns:
                parts.append(f"- {p['name']}: {p['description'][:100]}")

        return "\n".join(parts) if parts else ""


# ══════════════════════════════════════════════════════════════
# UNIFIED PROJECT MEMORY — Single entry point
# ══════════════════════════════════════════════════════════════

class ProjectMemory:
    """
    Unified interface for all project memory features.
    Use this as the main entry point.
    
    Usage:
        pm = ProjectMemory(user_id="user123", project_id="proj456")
        
        # Start session
        pm.start_session(chat_id="chat789", task="Deploy nginx")
        
        # Log events
        pm.log_decision(chat_id, "Use Docker", reason="Portability")
        pm.log_file_change(chat_id, "/etc/nginx/nginx.conf", "modified")
        pm.log_error(chat_id, "Port 80 in use", fix="killed process")
        
        # Get context for prompt
        context = pm.get_full_context(chat_id)
        
        # Learn from outcomes
        pm.learn_error_solution("Port 80 in use", "lsof -i :80 | kill")
    """

    def __init__(self, user_id: str, project_id: str = None):
        self.user_id = user_id
        self.project_id = project_id
        self.sessions = SessionContext(user_id, project_id)
        self.decisions = DecisionLog(user_id)
        self.tasks = TaskContinuity(user_id)
        self.learning = CrossProjectLearning(user_id)

    def start_session(self, chat_id: str, task: str = "") -> dict:
        """Start or resume a session."""
        return self.sessions.start_session(chat_id, task)

    def log_decision(self, chat_id: str, decision: str,
                     reason: str = "", category: str = "general") -> None:
        """Log a decision in both session and global log."""
        self.sessions.log_decision(chat_id, decision, reason, category)
        self.decisions.log(decision, reason, category,
                          self.project_id, chat_id)

    def log_file_change(self, chat_id: str, filepath: str,
                        action: str = "created") -> None:
        """Log a file change."""
        self.sessions.log_file_change(chat_id, filepath, action)

    def log_command(self, chat_id: str, command: str,
                    success: bool = True, output: str = "") -> None:
        """Log a command execution."""
        self.sessions.log_command(chat_id, command, success, output)

    def log_error(self, chat_id: str, error: str,
                  fix: str = "") -> None:
        """Log an error and optional fix."""
        self.sessions.log_error(chat_id, error, fix)
        if fix:
            self.learning.learn_error_solution(error, fix)

    def add_fact(self, chat_id: str, fact: str,
                 category: str = "general") -> None:
        """Add a key fact."""
        self.sessions.add_key_fact(chat_id, fact, category)

    def save_checkpoint(self, chat_id: str, task: str, progress: str,
                        steps_completed: list = None,
                        steps_remaining: list = None,
                        context: dict = None) -> dict:
        """Save task checkpoint for resumption."""
        return self.tasks.save_checkpoint(
            chat_id, task, progress,
            steps_completed, steps_remaining, context
        )

    def complete_session(self, chat_id: str, summary: str = "") -> None:
        """Mark session and task as completed."""
        self.sessions.set_summary(chat_id, summary)
        self.tasks.complete_task(chat_id, summary)

    def learn_error_solution(self, error: str, solution: str,
                             context: str = "") -> None:
        """Learn from an error resolution."""
        self.learning.learn_error_solution(error, solution, context)

    def learn_tool_preference(self, task_type: str, tool: str,
                              success: bool = True) -> None:
        """Track tool effectiveness."""
        self.learning.learn_tool_preference(task_type, tool, success)

    def find_known_solution(self, error: str) -> Optional[dict]:
        """Find a known solution for an error."""
        return self.learning.find_solution(error)

    def get_full_context(self, chat_id: str = None) -> str:
        """
        Get complete memory context for system prompt injection.
        Combines: session context + decisions + task continuity + learning.
        """
        parts = []

        # Session context
        session_ctx = self.sessions.get_context_for_prompt(chat_id)
        if session_ctx:
            parts.append(session_ctx)

        # Decision log
        decision_ctx = self.decisions.get_context_for_prompt(self.project_id)
        if decision_ctx:
            parts.append(decision_ctx)

        # Task continuity (if resuming)
        if chat_id:
            resume_ctx = self.tasks.get_resume_prompt(chat_id)
            if resume_ctx:
                parts.append(resume_ctx)

        # Cross-project learning
        learning_ctx = self.learning.get_context_for_prompt()
        if learning_ctx:
            parts.append(learning_ctx)

        if not parts:
            return ""

        return "\n\n---\n\n".join(parts)

    def get_active_tasks(self) -> List[dict]:
        """Get all active/paused tasks."""
        return self.tasks.get_active_tasks()

    def cleanup(self, days: int = 30) -> dict:
        """Clean up old data."""
        removed = self.sessions.cleanup_old_sessions(days)
        return {"sessions_removed": removed}
