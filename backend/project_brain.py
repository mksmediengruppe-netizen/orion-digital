"""
Project Brain — память проекта целиком.
=======================================
Не просто task_charter на задачу, а полный контекст проекта:
- постоянные цели проекта
- архитектурные решения
- список артефактов проекта
- история версий
- reusable patterns (что работало раньше)
- known constraints
- linked files/repos/servers
- открытые ветки работы

Таблица projects в database.sqlite.
Связь: task_charter → project_brain.
"""
import json
import time
import sqlite3
import logging
import os
from typing import Optional, Dict, List

logger = logging.getLogger("project_brain")

DATA_DIR = os.environ.get("DATA_DIR", "/var/www/orion/backend/data")
DB_PATH = os.path.join(DATA_DIR, "database.sqlite")

try:
    from shared import _USE_SQLITE
    _USE_UNIFIED_DB = _USE_SQLITE
except ImportError:
    _USE_UNIFIED_DB = True


class ProjectBrain:
    """
    Хранилище знаний о проекте.
    Агент знает: "этот проект на Tailwind, сервер 45.67.57.175,
    nginx, последний деплой был вчера, форма не работала."
    """

    def __init__(self, db_path: str = DB_PATH):
        self._db_path = db_path
        self._init_db()

    def _init_db(self):
        os.makedirs(os.path.dirname(self._db_path), exist_ok=True)
        conn = sqlite3.connect(self._db_path)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS projects (
                project_id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                description TEXT DEFAULT '',
                objectives_json TEXT DEFAULT '[]',
                architecture_decisions_json TEXT DEFAULT '[]',
                artifacts_json TEXT DEFAULT '[]',
                patterns_json TEXT DEFAULT '[]',
                constraints_json TEXT DEFAULT '[]',
                linked_resources_json TEXT DEFAULT '[]',
                open_branches_json TEXT DEFAULT '[]',
                version_history_json TEXT DEFAULT '[]',
                tech_stack_json TEXT DEFAULT '{}',
                status TEXT DEFAULT 'active',
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL
            )
        """)
        # Link table: task_charter → project
        conn.execute("""
            CREATE TABLE IF NOT EXISTS project_tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id TEXT NOT NULL,
                task_id TEXT NOT NULL,
                role TEXT DEFAULT 'task',
                created_at REAL NOT NULL,
                UNIQUE(project_id, task_id)
            )
        """)
        conn.commit()
        conn.close()
        logger.info(f"ProjectBrain DB initialized: {self._db_path}")

    def _conn(self):
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def _row_to_dict(self, row) -> Dict:
        if row is None:
            return None
        d = dict(row)
        clean = {}
        for key in list(d.keys()):
            if key.endswith("_json") and isinstance(d[key], str):
                clean_key = key[:-5]  # remove _json suffix
                try:
                    clean[clean_key] = json.loads(d[key])
                except (json.JSONDecodeError, TypeError):
                    clean[clean_key] = [] if clean_key != "tech_stack" else {}
            else:
                clean[key] = d[key]
        return clean

    # ═══════════════════════════════════════════
    # CRUD
    # ═══════════════════════════════════════════
    def create(self, project_id: str, name: str,
               description: str = "",
               objectives: List[str] = None,
               tech_stack: Dict = None,
               constraints: List[str] = None,
               linked_resources: List[Dict] = None) -> Dict:
        """Создать новый проект."""
        now = time.time()
        conn = self._conn()
        try:
            conn.execute("""
                INSERT INTO projects (
                    project_id, name, description,
                    objectives_json, tech_stack_json,
                    constraints_json, linked_resources_json,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                project_id, name, description,
                json.dumps(objectives or [], ensure_ascii=False),
                json.dumps(tech_stack or {}, ensure_ascii=False),
                json.dumps(constraints or [], ensure_ascii=False),
                json.dumps(linked_resources or [], ensure_ascii=False),
                now, now
            ))
            conn.commit()
        finally:
            conn.close()
        logger.info(f"[project_brain] Created project: {project_id} ({name})")
        return self.get(project_id)

    def get(self, project_id: str) -> Optional[Dict]:
        """Получить проект по ID."""
        conn = self._conn()
        row = conn.execute(
            "SELECT * FROM projects WHERE project_id = ?", (project_id,)
        ).fetchone()
        conn.close()
        if not row:
            return None
        return self._row_to_dict(row)

    def list_all(self, status: str = None) -> List[Dict]:
        """Список всех проектов."""
        conn = self._conn()
        if status:
            rows = conn.execute(
                "SELECT * FROM projects WHERE status = ? ORDER BY updated_at DESC",
                (status,)
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM projects ORDER BY updated_at DESC"
            ).fetchall()
        conn.close()
        return [self._row_to_dict(r) for r in rows]

    def update(self, project_id: str, patch: Dict) -> Optional[Dict]:
        """Обновить проект."""
        existing = self.get(project_id)
        if not existing:
            return None

        conn = self._conn()
        now = time.time()

        # JSON fields mapping
        json_fields = {
            "objectives": "objectives_json",
            "architecture_decisions": "architecture_decisions_json",
            "artifacts": "artifacts_json",
            "patterns": "patterns_json",
            "constraints": "constraints_json",
            "linked_resources": "linked_resources_json",
            "open_branches": "open_branches_json",
            "version_history": "version_history_json",
            "tech_stack": "tech_stack_json",
        }

        sets = ["updated_at = ?"]
        vals = [now]

        for key, val in patch.items():
            if key in json_fields:
                sets.append(f"{json_fields[key]} = ?")
                vals.append(json.dumps(val, ensure_ascii=False))
            elif key in ("name", "description", "status"):
                sets.append(f"{key} = ?")
                vals.append(val)

        vals.append(project_id)
        conn.execute(
            f"UPDATE projects SET {', '.join(sets)} WHERE project_id = ?",
            vals
        )
        conn.commit()
        conn.close()
        logger.info(f"[project_brain] Updated project: {project_id}")
        return self.get(project_id)

    def delete(self, project_id: str) -> bool:
        """Удалить проект."""
        conn = self._conn()
        cur = conn.execute("DELETE FROM projects WHERE project_id = ?", (project_id,))
        conn.commit()
        conn.close()
        return cur.rowcount > 0

    # ═══════════════════════════════════════════
    # KNOWLEDGE OPERATIONS
    # ═══════════════════════════════════════════
    def add_architecture_decision(self, project_id: str, decision: str,
                                   rationale: str = "", date: str = "") -> Optional[Dict]:
        """Добавить архитектурное решение."""
        proj = self.get(project_id)
        if not proj:
            return None
        decisions = proj.get("architecture_decisions", [])
        decisions.append({
            "decision": decision,
            "rationale": rationale,
            "date": date or time.strftime("%Y-%m-%d"),
            "added_at": time.time()
        })
        return self.update(project_id, {"architecture_decisions": decisions})

    def add_pattern(self, project_id: str, pattern: str,
                    context: str = "", success: bool = True) -> Optional[Dict]:
        """Добавить reusable pattern."""
        proj = self.get(project_id)
        if not proj:
            return None
        patterns = proj.get("patterns", [])
        patterns.append({
            "pattern": pattern,
            "context": context,
            "success": success,
            "added_at": time.time()
        })
        return self.update(project_id, {"patterns": patterns})

    def add_linked_resource(self, project_id: str, resource_type: str,
                            url: str, description: str = "") -> Optional[Dict]:
        """Добавить связанный ресурс (сервер, репо, файл)."""
        proj = self.get(project_id)
        if not proj:
            return None
        resources = proj.get("linked_resources", [])
        resources.append({
            "type": resource_type,
            "url": url,
            "description": description,
            "added_at": time.time()
        })
        return self.update(project_id, {"linked_resources": resources})

    def add_artifact(self, project_id: str, artifact_id: str,
                     artifact_type: str, path: str = "",
                     version: str = "1.0") -> Optional[Dict]:
        """Зарегистрировать артефакт проекта."""
        proj = self.get(project_id)
        if not proj:
            return None
        artifacts = proj.get("artifacts", [])
        artifacts.append({
            "artifact_id": artifact_id,
            "type": artifact_type,
            "path": path,
            "version": version,
            "added_at": time.time()
        })
        return self.update(project_id, {"artifacts": artifacts})

    # ═══════════════════════════════════════════
    # TASK LINKING
    # ═══════════════════════════════════════════
    def link_task(self, project_id: str, task_id: str, role: str = "task") -> bool:
        """Связать задачу с проектом."""
        conn = self._conn()
        try:
            conn.execute("""
                INSERT OR IGNORE INTO project_tasks (project_id, task_id, role, created_at)
                VALUES (?, ?, ?, ?)
            """, (project_id, task_id, role, time.time()))
            conn.commit()
            return True
        except Exception as e:
            logger.error(f"[project_brain] link_task error: {e}")
            return False
        finally:
            conn.close()

    def get_project_tasks(self, project_id: str) -> List[Dict]:
        """Получить все задачи проекта."""
        conn = self._conn()
        rows = conn.execute(
            "SELECT * FROM project_tasks WHERE project_id = ? ORDER BY created_at DESC",
            (project_id,)
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]

    def get_task_project(self, task_id: str) -> Optional[str]:
        """Получить project_id для задачи."""
        conn = self._conn()
        row = conn.execute(
            "SELECT project_id FROM project_tasks WHERE task_id = ?",
            (task_id,)
        ).fetchone()
        conn.close()
        return row["project_id"] if row else None

    # ═══════════════════════════════════════════
    # CONTEXT FOR AGENT
    # ═══════════════════════════════════════════
    def format_for_prompt(self, project_id: str) -> str:
        """Форматировать контекст проекта для промпта агента."""
        proj = self.get(project_id)
        if not proj:
            return ""

        parts = [f"## Проект: {proj['name']}"]
        if proj.get("description"):
            parts.append(f"Описание: {proj['description']}")

        objectives = proj.get("objectives", [])
        if objectives:
            parts.append("\nЦели проекта:")
            for o in objectives:
                parts.append(f"  - {o}")

        tech = proj.get("tech_stack", {})
        if tech:
            parts.append(f"\nТехнологии: {json.dumps(tech, ensure_ascii=False)}")

        decisions = proj.get("architecture_decisions", [])
        if decisions:
            parts.append("\nАрхитектурные решения:")
            for d in decisions[-5:]:  # last 5
                parts.append(f"  - {d.get('decision', '')} ({d.get('rationale', '')})")

        patterns = proj.get("patterns", [])
        if patterns:
            parts.append("\nPatterns (что работало):")
            for p in patterns[-5:]:
                status = "OK" if p.get("success") else "FAIL"
                parts.append(f"  - [{status}] {p.get('pattern', '')}")

        constraints = proj.get("constraints", [])
        if constraints:
            parts.append("\nОграничения:")
            for c in constraints:
                parts.append(f"  - {c}")

        resources = proj.get("linked_resources", [])
        if resources:
            parts.append("\nСвязанные ресурсы:")
            for r in resources:
                parts.append(f"  - [{r.get('type', '')}] {r.get('url', '')} — {r.get('description', '')}")

        return "\n".join(parts)


# ═══════════════════════════════════════════
# SINGLETON
# ═══════════════════════════════════════════
_project_brain = None

def get_project_brain() -> ProjectBrain:
    global _project_brain
    if _project_brain is None:
        _project_brain = ProjectBrain()
    return _project_brain
