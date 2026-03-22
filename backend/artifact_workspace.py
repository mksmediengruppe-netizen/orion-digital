"""
Artifact Workspace — каждый артефакт как first-class объект.
============================================================
- id, type (code/doc/design/config), version
- owner (какой агент создал)
- status (draft/reviewed/approved/deployed)
- parent_task_id
- content_hash (для отслеживания изменений)
- review_notes
- dependencies (зависит от других артефактов)

Таблица artifacts_registry в database.sqlite.
При task_complete — все созданные файлы регистрируются.
FinalJudge проверяет: все deliverables есть в registry?
"""
import json
import time
import sqlite3
import hashlib
import logging
import os
from typing import Optional, Dict, List

logger = logging.getLogger("artifact_workspace")

DATA_DIR = os.environ.get("DATA_DIR", "/var/www/orion/backend/data")
DB_PATH = os.path.join(DATA_DIR, "database.sqlite")


class ArtifactWorkspace:
    """Registry и workspace для артефактов проекта."""

    VALID_TYPES = ("code", "doc", "design", "config", "data", "test", "other")
    VALID_STATUSES = ("draft", "reviewed", "approved", "deployed", "archived")

    def __init__(self, db_path: str = DB_PATH):
        self._db_path = db_path
        self._init_db()

    def _init_db(self):
        os.makedirs(os.path.dirname(self._db_path), exist_ok=True)
        conn = sqlite3.connect(self._db_path)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS artifacts_registry (
                artifact_id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                artifact_type TEXT DEFAULT 'code',
                version TEXT DEFAULT '1.0',
                status TEXT DEFAULT 'draft',
                owner_agent TEXT DEFAULT '',
                parent_task_id TEXT DEFAULT '',
                project_id TEXT DEFAULT '',
                file_path TEXT DEFAULT '',
                content_hash TEXT DEFAULT '',
                size_bytes INTEGER DEFAULT 0,
                review_notes TEXT DEFAULT '',
                dependencies_json TEXT DEFAULT '[]',
                metadata_json TEXT DEFAULT '{}',
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL
            )
        """)
        conn.commit()
        conn.close()
        logger.info(f"ArtifactWorkspace DB initialized: {self._db_path}")

    def _conn(self):
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def _row_to_dict(self, row) -> Optional[Dict]:
        if row is None:
            return None
        d = dict(row)
        clean = {}
        for key in list(d.keys()):
            if key.endswith("_json") and isinstance(d[key], str):
                clean_key = key[:-5]
                try:
                    clean[clean_key] = json.loads(d[key])
                except (json.JSONDecodeError, TypeError):
                    clean[clean_key] = [] if "dependencies" in key else {}
            else:
                clean[key] = d[key]
        return clean

    # ═══════════════════════════════════════════
    # CRUD
    # ═══════════════════════════════════════════
    def register(self, artifact_id: str, name: str,
                 artifact_type: str = "code",
                 version: str = "1.0",
                 owner_agent: str = "",
                 parent_task_id: str = "",
                 project_id: str = "",
                 file_path: str = "",
                 content_hash: str = "",
                 size_bytes: int = 0,
                 dependencies: List[str] = None,
                 metadata: Dict = None) -> Dict:
        """Зарегистрировать артефакт."""
        now = time.time()
        if artifact_type not in self.VALID_TYPES:
            artifact_type = "other"
        conn = self._conn()
        try:
            conn.execute("""
                INSERT OR REPLACE INTO artifacts_registry (
                    artifact_id, name, artifact_type, version, status,
                    owner_agent, parent_task_id, project_id,
                    file_path, content_hash, size_bytes,
                    dependencies_json, metadata_json,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, 'draft', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                artifact_id, name, artifact_type, version,
                owner_agent, parent_task_id, project_id,
                file_path, content_hash, size_bytes,
                json.dumps(dependencies or [], ensure_ascii=False),
                json.dumps(metadata or {}, ensure_ascii=False),
                now, now
            ))
            conn.commit()
        finally:
            conn.close()
        logger.info(f"[artifact_workspace] Registered: {artifact_id} ({name})")
        return self.get(artifact_id)

    def get(self, artifact_id: str) -> Optional[Dict]:
        """Получить артефакт по ID."""
        conn = self._conn()
        row = conn.execute(
            "SELECT * FROM artifacts_registry WHERE artifact_id = ?",
            (artifact_id,)
        ).fetchone()
        conn.close()
        return self._row_to_dict(row)

    def list_by_task(self, task_id: str) -> List[Dict]:
        """Список артефактов задачи."""
        conn = self._conn()
        rows = conn.execute(
            "SELECT * FROM artifacts_registry WHERE parent_task_id = ? ORDER BY created_at",
            (task_id,)
        ).fetchall()
        conn.close()
        return [self._row_to_dict(r) for r in rows]

    def list_by_project(self, project_id: str) -> List[Dict]:
        """Список артефактов проекта."""
        conn = self._conn()
        rows = conn.execute(
            "SELECT * FROM artifacts_registry WHERE project_id = ? ORDER BY created_at",
            (project_id,)
        ).fetchall()
        conn.close()
        return [self._row_to_dict(r) for r in rows]

    def list_by_status(self, status: str) -> List[Dict]:
        """Список артефактов по статусу."""
        conn = self._conn()
        rows = conn.execute(
            "SELECT * FROM artifacts_registry WHERE status = ? ORDER BY updated_at DESC",
            (status,)
        ).fetchall()
        conn.close()
        return [self._row_to_dict(r) for r in rows]

    # ═══════════════════════════════════════════
    # STATUS MANAGEMENT
    # ═══════════════════════════════════════════
    def set_status(self, artifact_id: str, status: str,
                   review_notes: str = "") -> Optional[Dict]:
        """Изменить статус артефакта."""
        if status not in self.VALID_STATUSES:
            return None
        conn = self._conn()
        now = time.time()
        updates = "status = ?, updated_at = ?"
        vals = [status, now]
        if review_notes:
            updates += ", review_notes = ?"
            vals.append(review_notes)
        vals.append(artifact_id)
        conn.execute(
            f"UPDATE artifacts_registry SET {updates} WHERE artifact_id = ?",
            vals
        )
        conn.commit()
        conn.close()
        return self.get(artifact_id)

    def update_version(self, artifact_id: str, new_version: str,
                       content_hash: str = "",
                       size_bytes: int = 0) -> Optional[Dict]:
        """Обновить версию артефакта."""
        conn = self._conn()
        now = time.time()
        conn.execute("""
            UPDATE artifacts_registry 
            SET version = ?, content_hash = ?, size_bytes = ?, updated_at = ?
            WHERE artifact_id = ?
        """, (new_version, content_hash, size_bytes, now, artifact_id))
        conn.commit()
        conn.close()
        return self.get(artifact_id)

    # ═══════════════════════════════════════════
    # HASH & VERIFICATION
    # ═══════════════════════════════════════════
    @staticmethod
    def compute_hash(content: str) -> str:
        """Вычислить SHA256 хеш контента."""
        return hashlib.sha256(content.encode("utf-8")).hexdigest()[:16]

    def verify_deliverables(self, task_id: str,
                            expected_deliverables: List[str]) -> Dict:
        """Проверить: все deliverables из charter есть в registry?"""
        artifacts = self.list_by_task(task_id)
        registered_names = {a["name"] for a in artifacts}
        registered_paths = {a.get("file_path", "") for a in artifacts}

        missing = []
        found = []
        for d in expected_deliverables:
            if d in registered_names or d in registered_paths:
                found.append(d)
            else:
                # Partial match
                matched = any(d in n or d in p 
                            for n in registered_names 
                            for p in registered_paths)
                if matched:
                    found.append(d)
                else:
                    missing.append(d)

        return {
            "total_expected": len(expected_deliverables),
            "found": len(found),
            "missing": missing,
            "found_list": found,
            "complete": len(missing) == 0,
            "artifacts_count": len(artifacts)
        }

    # ═══════════════════════════════════════════
    # PROMPT FORMATTING
    # ═══════════════════════════════════════════
    def format_for_prompt(self, task_id: str = None,
                          project_id: str = None) -> str:
        """Форматировать список артефактов для промпта."""
        if task_id:
            artifacts = self.list_by_task(task_id)
        elif project_id:
            artifacts = self.list_by_project(project_id)
        else:
            return ""

        if not artifacts:
            return "Артефакты: пока нет зарегистрированных."

        lines = ["## Артефакты:"]
        for a in artifacts:
            status_icon = {"draft": "📝", "reviewed": "👀", "approved": "✅", "deployed": "🚀"}.get(a["status"], "❓")
            lines.append(
                f"  {status_icon} {a['name']} (v{a['version']}) "
                f"[{a['artifact_type']}] — {a['status']}"
            )
            if a.get("file_path"):
                lines.append(f"     path: {a['file_path']}")
        return "\n".join(lines)


# ═══════════════════════════════════════════
# SINGLETON
# ═══════════════════════════════════════════
_workspace = None

def get_artifact_workspace() -> ArtifactWorkspace:
    global _workspace
    if _workspace is None:
        _workspace = ArtifactWorkspace()
    return _workspace
