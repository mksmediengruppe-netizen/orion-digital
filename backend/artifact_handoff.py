"""
Artifact Handoff — JSON-передача артефактов между агентами.
============================================================

Когда один агент создаёт файл/код/результат, он упаковывает его
в ArtifactHandoff и передаёт следующему агенту.

Это решает проблему "телефонного испорченного" — каждый агент
получает точные данные, а не пересказ предыдущего.

Таблица: artifact_handoffs (SQLite)
"""

import json
import time
import uuid
import sqlite3
import logging
import os
from typing import Optional, Dict, List, Any

logger = logging.getLogger("artifact_handoff")

DB_PATH = os.path.join(
    os.environ.get("DATA_DIR", "/var/www/orion/backend/data"),
    "artifact_handoffs.db"
)

# Типы артефактов
ARTIFACT_TYPES = {
    "code":        "Исходный код (py, js, html, css, ...)",
    "file":        "Файл на сервере (путь + содержимое)",
    "url":         "URL (задеплоенный сайт, API endpoint)",
    "data":        "Структурированные данные (JSON, CSV)",
    "report":      "Текстовый отчёт / markdown",
    "image":       "Изображение (URL или base64)",
    "config":      "Конфигурационный файл",
    "credentials": "Данные доступа (зашифрованные)",
    "plan":        "План / список шагов",
    "error":       "Ошибка / исключение для обработки",
}


class ArtifactHandoff:
    """
    Единица передачи данных между агентами.
    
    Содержит:
    - artifact_id: уникальный ID
    - task_id: к какой задаче относится
    - from_agent: кто создал
    - to_agent: кому предназначен (или "any")
    - artifact_type: тип артефакта
    - content: само содержимое
    - metadata: доп. информация (путь, URL, размер, ...)
    - status: pending / received / processed / failed
    """

    def __init__(self, db_path: str = DB_PATH):
        self._db_path = db_path
        self._init_db()

    def _init_db(self):
        os.makedirs(os.path.dirname(self._db_path), exist_ok=True)
        conn = sqlite3.connect(self._db_path)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS artifact_handoffs (
                artifact_id  TEXT PRIMARY KEY,
                task_id      TEXT NOT NULL,
                chat_id      TEXT DEFAULT '',
                from_agent   TEXT NOT NULL,
                to_agent     TEXT DEFAULT 'any',
                artifact_type TEXT NOT NULL,
                content      TEXT NOT NULL,
                metadata_json TEXT DEFAULT '{}',
                status       TEXT DEFAULT 'pending',
                created_at   REAL,
                received_at  REAL,
                processed_at REAL,
                error_msg    TEXT DEFAULT ''
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_handoff_task ON artifact_handoffs(task_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_handoff_chat ON artifact_handoffs(chat_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_handoff_status ON artifact_handoffs(status)")
        conn.commit()
        conn.close()
        logger.info(f"ArtifactHandoff DB initialized: {self._db_path}")

    def _conn(self):
        return sqlite3.connect(self._db_path)

    # ═══════════════════════════════════════════
    # CREATE
    # ═══════════════════════════════════════════

    def create(
        self,
        task_id: str,
        from_agent: str,
        artifact_type: str,
        content: Any,
        to_agent: str = "any",
        chat_id: str = "",
        metadata: Dict = None
    ) -> Dict:
        """
        Создать новый артефакт для передачи.

        Args:
            task_id: ID задачи
            from_agent: имя агента-отправителя ("planner", "coder", "ssh_agent", ...)
            artifact_type: тип из ARTIFACT_TYPES
            content: содержимое (строка, dict, list — будет сериализовано)
            to_agent: имя агента-получателя или "any"
            chat_id: ID чата
            metadata: доп. данные {"path": "/var/www/...", "url": "https://..."}
        """
        artifact_id = str(uuid.uuid4())
        now = time.time()

        # Сериализовать content если нужно
        if not isinstance(content, str):
            content_str = json.dumps(content, ensure_ascii=False)
        else:
            content_str = content

        conn = self._conn()
        conn.execute("""
            INSERT INTO artifact_handoffs
            (artifact_id, task_id, chat_id, from_agent, to_agent,
             artifact_type, content, metadata_json, status, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?)
        """, (
            artifact_id, task_id, chat_id, from_agent, to_agent,
            artifact_type, content_str,
            json.dumps(metadata or {}, ensure_ascii=False),
            now
        ))
        conn.commit()
        conn.close()

        logger.info(f"[handoff] Created {artifact_id[:8]} | {from_agent} → {to_agent} | {artifact_type}")
        return self.get(artifact_id)

    # ═══════════════════════════════════════════
    # GET
    # ═══════════════════════════════════════════

    def get(self, artifact_id: str) -> Optional[Dict]:
        """Получить артефакт по ID."""
        conn = self._conn()
        row = conn.execute(
            "SELECT * FROM artifact_handoffs WHERE artifact_id = ?",
            (artifact_id,)
        ).fetchone()
        conn.close()
        return self._row_to_dict(row) if row else None

    def get_pending_for_agent(self, task_id: str, agent_name: str) -> List[Dict]:
        """Получить все pending артефакты для агента."""
        conn = self._conn()
        rows = conn.execute(
            """SELECT * FROM artifact_handoffs
               WHERE task_id = ? AND status = 'pending'
               AND (to_agent = ? OR to_agent = 'any')
               ORDER BY created_at ASC""",
            (task_id, agent_name)
        ).fetchall()
        conn.close()
        return [self._row_to_dict(r) for r in rows]

    def get_all_for_task(self, task_id: str) -> List[Dict]:
        """Все артефакты задачи."""
        conn = self._conn()
        rows = conn.execute(
            "SELECT * FROM artifact_handoffs WHERE task_id = ? ORDER BY created_at ASC",
            (task_id,)
        ).fetchall()
        conn.close()
        return [self._row_to_dict(r) for r in rows]

    def get_latest_by_type(self, task_id: str, artifact_type: str) -> Optional[Dict]:
        """Последний артефакт нужного типа для задачи."""
        conn = self._conn()
        row = conn.execute(
            """SELECT * FROM artifact_handoffs
               WHERE task_id = ? AND artifact_type = ?
               ORDER BY created_at DESC LIMIT 1""",
            (task_id, artifact_type)
        ).fetchone()
        conn.close()
        return self._row_to_dict(row) if row else None

    # ═══════════════════════════════════════════
    # STATUS UPDATES
    # ═══════════════════════════════════════════

    def mark_received(self, artifact_id: str) -> bool:
        """Отметить что артефакт получен агентом."""
        conn = self._conn()
        conn.execute(
            "UPDATE artifact_handoffs SET status='received', received_at=? WHERE artifact_id=?",
            (time.time(), artifact_id)
        )
        conn.commit()
        conn.close()
        logger.debug(f"[handoff] Received: {artifact_id[:8]}")
        return True

    def mark_processed(self, artifact_id: str) -> bool:
        """Отметить что артефакт обработан."""
        conn = self._conn()
        conn.execute(
            "UPDATE artifact_handoffs SET status='processed', processed_at=? WHERE artifact_id=?",
            (time.time(), artifact_id)
        )
        conn.commit()
        conn.close()
        logger.debug(f"[handoff] Processed: {artifact_id[:8]}")
        return True

    def mark_failed(self, artifact_id: str, error: str) -> bool:
        """Отметить что обработка артефакта провалилась."""
        conn = self._conn()
        conn.execute(
            "UPDATE artifact_handoffs SET status='failed', error_msg=? WHERE artifact_id=?",
            (error[:500], artifact_id)
        )
        conn.commit()
        conn.close()
        logger.warning(f"[handoff] Failed: {artifact_id[:8]} | {error[:100]}")
        return True

    # ═══════════════════════════════════════════
    # SUMMARY (для промпта агента)
    # ═══════════════════════════════════════════

    def format_for_prompt(self, task_id: str, agent_name: str) -> str:
        """
        Форматирует pending артефакты для вставки в промпт агента.
        
        Returns:
            Строка для вставки в системный промпт.
        """
        artifacts = self.get_pending_for_agent(task_id, agent_name)
        if not artifacts:
            return ""

        lines = ["## Артефакты от предыдущих агентов:\n"]
        for a in artifacts:
            lines.append(f"### [{a['artifact_type'].upper()}] от {a['from_agent']}")
            # Контент — первые 2000 символов
            content = a["content"]
            if len(content) > 2000:
                content = content[:2000] + "\n... (обрезано)"
            lines.append(content)
            if a.get("metadata"):
                meta = a["metadata"]
                if meta.get("path"):
                    lines.append(f"*Путь: {meta['path']}*")
                if meta.get("url"):
                    lines.append(f"*URL: {meta['url']}*")
            lines.append("")

        return "\n".join(lines)

    # ═══════════════════════════════════════════
    # INTERNAL
    # ═══════════════════════════════════════════

    def _row_to_dict(self, row) -> Dict:
        cols = [
            "artifact_id", "task_id", "chat_id", "from_agent", "to_agent",
            "artifact_type", "content", "metadata_json", "status",
            "created_at", "received_at", "processed_at", "error_msg"
        ]
        d = dict(zip(cols, row))
        # Десериализовать metadata
        try:
            d["metadata"] = json.loads(d.pop("metadata_json", "{}"))
        except Exception:
            d["metadata"] = {}
        # Попытаться десериализовать content если JSON
        try:
            d["content_parsed"] = json.loads(d["content"])
        except Exception:
            d["content_parsed"] = None
        return d


# ═══════════════════════════════════════════
# SINGLETON
# ═══════════════════════════════════════════

_handoff_store: Optional[ArtifactHandoff] = None

def get_handoff_store() -> ArtifactHandoff:
    global _handoff_store
    if _handoff_store is None:
        _handoff_store = ArtifactHandoff()
    return _handoff_store
