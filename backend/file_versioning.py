"""
File Versioning v1.0 — Версионирование файлов для ORION Digital.

Функции:
- Автоматическое сохранение версий при каждом file_write
- Diff между версиями (unified diff)
- Rollback к любой предыдущей версии
- История изменений с метаданными
- Ограничение по количеству версий (max 20 на файл)
"""

import json
import time
import hashlib
import difflib
import sqlite3
import logging
from datetime import datetime, timezone
from typing import List, Dict, Optional, Tuple

logger = logging.getLogger("file_versioning")


class FileVersionStore:
    """
    SQLite-based file version store.
    Хранит версии файлов с содержимым, diff, метаданными.
    """

    MAX_VERSIONS_PER_FILE = 20
    DB_PATH = "/tmp/file_versions.db"

    def __init__(self, db_path: str = None):
        self._db_path = db_path or self.DB_PATH
        self._conn = sqlite3.connect(self._db_path, check_same_thread=False)
        self._init_db()

    def _init_db(self):
        """Initialize database schema."""
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS file_versions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                host TEXT NOT NULL,
                path TEXT NOT NULL,
                content TEXT NOT NULL,
                content_hash TEXT NOT NULL,
                version INTEGER NOT NULL,
                diff_from_prev TEXT,
                size INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                created_by TEXT DEFAULT 'agent',
                chat_id TEXT,
                metadata TEXT DEFAULT '{}'
            )
        """)
        self._conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_file_versions_host_path
            ON file_versions (host, path)
        """)
        self._conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_file_versions_hash
            ON file_versions (content_hash)
        """)
        self._conn.commit()

    def save_version(self, host: str, path: str, content: str,
                     chat_id: str = None, created_by: str = "agent",
                     metadata: dict = None) -> Dict:
        """
        Сохранить новую версию файла.

        Returns: dict с информацией о версии
        """
        content_hash = hashlib.sha256(content.encode()).hexdigest()[:16]

        # Check if content is same as latest version
        latest = self.get_latest_version(host, path)
        if latest and latest["content_hash"] == content_hash:
            return {
                "saved": False,
                "reason": "content_unchanged",
                "version": latest["version"],
                "content_hash": content_hash
            }

        # Get next version number
        version = 1
        if latest:
            version = latest["version"] + 1

        # Calculate diff from previous version
        diff_text = None
        if latest:
            diff_text = self._make_diff(
                latest["content"], content,
                f"v{latest['version']}", f"v{version}",
                path
            )

        now = datetime.now(timezone.utc).isoformat()

        self._conn.execute("""
            INSERT INTO file_versions
            (host, path, content, content_hash, version, diff_from_prev, size, created_at, created_by, chat_id, metadata)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            host, path, content, content_hash, version,
            diff_text, len(content), now, created_by,
            chat_id, json.dumps(metadata or {}, ensure_ascii=False)
        ))
        self._conn.commit()

        # Cleanup old versions
        self._cleanup_old_versions(host, path)

        return {
            "saved": True,
            "version": version,
            "content_hash": content_hash,
            "size": len(content),
            "has_diff": diff_text is not None,
            "diff_lines": len(diff_text.split("\n")) if diff_text else 0
        }

    def get_latest_version(self, host: str, path: str) -> Optional[Dict]:
        """Получить последнюю версию файла."""
        cursor = self._conn.execute("""
            SELECT id, host, path, content, content_hash, version, diff_from_prev,
                   size, created_at, created_by, chat_id, metadata
            FROM file_versions
            WHERE host = ? AND path = ?
            ORDER BY version DESC
            LIMIT 1
        """, (host, path))

        row = cursor.fetchone()
        if not row:
            return None

        return self._row_to_dict(row)

    def get_version(self, host: str, path: str, version: int) -> Optional[Dict]:
        """Получить конкретную версию файла."""
        cursor = self._conn.execute("""
            SELECT id, host, path, content, content_hash, version, diff_from_prev,
                   size, created_at, created_by, chat_id, metadata
            FROM file_versions
            WHERE host = ? AND path = ? AND version = ?
        """, (host, path, version))

        row = cursor.fetchone()
        if not row:
            return None

        return self._row_to_dict(row)

    def get_history(self, host: str, path: str, limit: int = 20) -> List[Dict]:
        """Получить историю версий файла (без содержимого)."""
        cursor = self._conn.execute("""
            SELECT id, host, path, '', content_hash, version, '',
                   size, created_at, created_by, chat_id, metadata
            FROM file_versions
            WHERE host = ? AND path = ?
            ORDER BY version DESC
            LIMIT ?
        """, (host, path, limit))

        return [self._row_to_dict(row, include_content=False) for row in cursor.fetchall()]

    def get_diff(self, host: str, path: str,
                 version_from: int, version_to: int) -> Optional[str]:
        """Получить diff между двумя версиями."""
        v_from = self.get_version(host, path, version_from)
        v_to = self.get_version(host, path, version_to)

        if not v_from or not v_to:
            return None

        return self._make_diff(
            v_from["content"], v_to["content"],
            f"v{version_from}", f"v{version_to}",
            path
        )

    def rollback(self, host: str, path: str, version: int) -> Optional[Dict]:
        """
        Rollback к указанной версии.
        Создаёт новую версию с содержимым старой.

        Returns: dict с информацией о новой версии
        """
        target = self.get_version(host, path, version)
        if not target:
            return None

        return self.save_version(
            host=host,
            path=path,
            content=target["content"],
            metadata={"rollback_from": version, "type": "rollback"}
        )

    def get_all_files(self, host: str = None, limit: int = 100) -> List[Dict]:
        """Получить список всех файлов с версиями."""
        if host:
            cursor = self._conn.execute("""
                SELECT host, path, MAX(version) as latest_version,
                       COUNT(*) as total_versions, MAX(created_at) as last_modified
                FROM file_versions
                WHERE host = ?
                GROUP BY host, path
                ORDER BY last_modified DESC
                LIMIT ?
            """, (host, limit))
        else:
            cursor = self._conn.execute("""
                SELECT host, path, MAX(version) as latest_version,
                       COUNT(*) as total_versions, MAX(created_at) as last_modified
                FROM file_versions
                GROUP BY host, path
                ORDER BY last_modified DESC
                LIMIT ?
            """, (limit,))

        return [
            {
                "host": row[0],
                "path": row[1],
                "latest_version": row[2],
                "total_versions": row[3],
                "last_modified": row[4]
            }
            for row in cursor.fetchall()
        ]

    def get_stats(self) -> Dict:
        """Get versioning statistics."""
        cursor = self._conn.execute("""
            SELECT
                COUNT(*) as total_versions,
                COUNT(DISTINCT host || path) as total_files,
                SUM(size) as total_size
            FROM file_versions
        """)
        row = cursor.fetchone()
        return {
            "total_versions": row[0] or 0,
            "total_files": row[1] or 0,
            "total_size_bytes": row[2] or 0
        }

    # ── Internal helpers ─────────────────────────────────────────

    def _make_diff(self, old_content: str, new_content: str,
                   old_label: str, new_label: str, filename: str) -> str:
        """Create unified diff between two contents."""
        old_lines = old_content.splitlines(keepends=True)
        new_lines = new_content.splitlines(keepends=True)

        diff = difflib.unified_diff(
            old_lines, new_lines,
            fromfile=f"{filename} ({old_label})",
            tofile=f"{filename} ({new_label})"
        )
        return "".join(diff)

    def _row_to_dict(self, row, include_content: bool = True) -> Dict:
        """Convert DB row to dict."""
        result = {
            "id": row[0],
            "host": row[1],
            "path": row[2],
            "content_hash": row[4],
            "version": row[5],
            "size": row[7],
            "created_at": row[8],
            "created_by": row[9],
            "chat_id": row[10],
        }
        if include_content:
            result["content"] = row[3]
            result["diff_from_prev"] = row[6]

        try:
            result["metadata"] = json.loads(row[11]) if row[11] else {}
        except Exception:
            result["metadata"] = {}

        return result

    def _cleanup_old_versions(self, host: str, path: str):
        """Remove old versions beyond MAX_VERSIONS_PER_FILE."""
        cursor = self._conn.execute("""
            SELECT id FROM file_versions
            WHERE host = ? AND path = ?
            ORDER BY version DESC
            LIMIT -1 OFFSET ?
        """, (host, path, self.MAX_VERSIONS_PER_FILE))

        old_ids = [row[0] for row in cursor.fetchall()]
        if old_ids:
            placeholders = ",".join("?" * len(old_ids))
            self._conn.execute(
                f"DELETE FROM file_versions WHERE id IN ({placeholders})",
                old_ids
            )
            self._conn.commit()
            logger.info(f"Cleaned up {len(old_ids)} old versions for {host}:{path}")


# ══════════════════════════════════════════════════════════════════
# ██ SINGLETON ██
# ══════════════════════════════════════════════════════════════════

_store_instance: Optional[FileVersionStore] = None


def get_version_store() -> FileVersionStore:
    """Get singleton FileVersionStore instance."""
    global _store_instance
    if _store_instance is None:
        _store_instance = FileVersionStore()
    return _store_instance
