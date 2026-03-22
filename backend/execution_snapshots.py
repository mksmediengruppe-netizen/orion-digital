"""
Execution Snapshots — снимки состояния после каждого шага.
=========================================================

После каждого завершённого шага, retry, tool action или
перед финальным ответом — пишем snapshot.

При крэше агент восстанавливается не по диалогу,
а по последнему snapshot.

Таблица: execution_snapshots (SQLite)
"""

import json
import time
import sqlite3
import logging
import os
from typing import Optional, Dict, List

logger = logging.getLogger("execution_snapshots")

DB_PATH = os.path.join(
    os.environ.get("DATA_DIR", "/var/www/orion/backend/data"),
    "execution_snapshots.db"
)


class SnapshotStore:
    """
    Хранилище снимков состояния выполнения задачи.
    """

    def __init__(self, db_path: str = DB_PATH):
        self._db_path = db_path
        self._init_db()

    def _init_db(self):
        os.makedirs(os.path.dirname(self._db_path), exist_ok=True)
        conn = sqlite3.connect(self._db_path)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS execution_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id TEXT NOT NULL,
                step_id TEXT DEFAULT '',
                snapshot_type TEXT DEFAULT 'step_complete',
                
                -- Состояние
                iteration INTEGER DEFAULT 0,
                phase TEXT DEFAULT '',
                agent_role TEXT DEFAULT '',
                
                -- Что сделано
                completed_actions_json TEXT DEFAULT '[]',
                artifacts_created_json TEXT DEFAULT '[]',
                
                -- Что не сделано
                pending_actions_json TEXT DEFAULT '[]',
                blockers_json TEXT DEFAULT '[]',
                
                -- Контекст
                active_constraints_json TEXT DEFAULT '[]',
                last_user_amendment TEXT DEFAULT '',
                next_expected_step TEXT DEFAULT '',
                
                -- Метрики
                cost_so_far REAL DEFAULT 0.0,
                tokens_used INTEGER DEFAULT 0,
                
                -- Время
                created_at REAL
            )
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_snapshot_task 
            ON execution_snapshots(task_id, created_at DESC)
        """)
        conn.commit()
        conn.close()
        logger.info(f"SnapshotStore initialized: {self._db_path}")

    def _conn(self):
        return sqlite3.connect(self._db_path)

    # ═══════════════════════════════════════════
    # CREATE
    # ═══════════════════════════════════════════

    def create(self, task_id: str, step_id: str,
               snapshot_type: str = "step_complete",
               iteration: int = 0,
               phase: str = "",
               agent_role: str = "",
               completed_actions: List[Dict] = None,
               artifacts_created: List[str] = None,
               pending_actions: List[str] = None,
               blockers: List[str] = None,
               active_constraints: List[str] = None,
               last_user_amendment: str = "",
               next_expected_step: str = "",
               cost_so_far: float = 0.0,
               tokens_used: int = 0) -> Dict:
        """
        Создать snapshot.
        
        snapshot_type: 
            "step_complete" — шаг завершён
            "step_failed" — шаг провалился
            "tool_action" — после tool call
            "before_final" — перед финальным ответом
            "crash_recovery" — восстановление после крэша
            "user_interrupt" — пользователь прервал
            "phase_transition" — переход между фазами pipeline
        """
        now = time.time()
        snapshot = {
            "task_id": task_id,
            "step_id": step_id,
            "snapshot_type": snapshot_type,
            "iteration": iteration,
            "phase": phase,
            "agent_role": agent_role,
            "completed_actions": completed_actions or [],
            "artifacts_created": artifacts_created or [],
            "pending_actions": pending_actions or [],
            "blockers": blockers or [],
            "active_constraints": active_constraints or [],
            "last_user_amendment": last_user_amendment,
            "next_expected_step": next_expected_step,
            "cost_so_far": cost_so_far,
            "tokens_used": tokens_used,
            "created_at": now
        }

        conn = self._conn()
        conn.execute("""
            INSERT INTO execution_snapshots (
                task_id, step_id, snapshot_type,
                iteration, phase, agent_role,
                completed_actions_json, artifacts_created_json,
                pending_actions_json, blockers_json,
                active_constraints_json, last_user_amendment,
                next_expected_step,
                cost_so_far, tokens_used,
                created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            task_id, step_id, snapshot_type,
            iteration, phase, agent_role,
            json.dumps(completed_actions or [], ensure_ascii=False),
            json.dumps(artifacts_created or [], ensure_ascii=False),
            json.dumps(pending_actions or [], ensure_ascii=False),
            json.dumps(blockers or [], ensure_ascii=False),
            json.dumps(active_constraints or [], ensure_ascii=False),
            last_user_amendment,
            next_expected_step,
            cost_so_far, tokens_used,
            now
        ))
        conn.commit()
        conn.close()

        logger.debug(f"Snapshot created: {task_id}/{step_id} [{snapshot_type}]")
        return snapshot

    # ═══════════════════════════════════════════
    # READ
    # ═══════════════════════════════════════════

    def latest(self, task_id: str) -> Optional[Dict]:
        """Получить последний snapshot для задачи."""
        conn = self._conn()
        row = conn.execute(
            "SELECT * FROM execution_snapshots WHERE task_id = ? "
            "ORDER BY created_at DESC LIMIT 1", (task_id,)
        ).fetchone()
        conn.close()

        if not row:
            return None
        return self._row_to_dict(row)

    def list(self, task_id: str, limit: int = 20) -> List[Dict]:
        """Получить последние N snapshots для задачи."""
        conn = self._conn()
        rows = conn.execute(
            "SELECT * FROM execution_snapshots WHERE task_id = ? "
            "ORDER BY created_at DESC LIMIT ?", (task_id, limit)
        ).fetchall()
        conn.close()

        return [self._row_to_dict(row) for row in rows]

    def list_by_type(self, task_id: str, snapshot_type: str, 
                      limit: int = 10) -> List[Dict]:
        """Получить snapshots определённого типа."""
        conn = self._conn()
        rows = conn.execute(
            "SELECT * FROM execution_snapshots WHERE task_id = ? "
            "AND snapshot_type = ? ORDER BY created_at DESC LIMIT ?",
            (task_id, snapshot_type, limit)
        ).fetchall()
        conn.close()

        return [self._row_to_dict(row) for row in rows]

    # ═══════════════════════════════════════════
    # FORMAT FOR PROMPT
    # ═══════════════════════════════════════════

    def format_for_prompt(self, task_id: str) -> str:
        """
        Форматирует последний snapshot для промпта.
        Идёт ПОСЛЕ Task Charter в контексте.
        """
        snap = self.latest(task_id)
        if not snap:
            return ""

        parts = []
        parts.append("═══ EXECUTION SNAPSHOT (текущее состояние) ═══")
        parts.append(f"Итерация: {snap['iteration']} | "
                     f"Фаза: {snap['phase'] or 'основная'} | "
                     f"Стоимость: ${snap['cost_so_far']:.4f}")

        if snap.get("completed_actions"):
            actions = snap["completed_actions"][-5:]
            parts.append(f"Выполнено ({len(snap['completed_actions'])} действий):")
            for a in actions:
                tool = a.get("tool", "unknown")
                result_preview = str(a.get("result", ""))[:60]
                status = "✅" if a.get("success") else "❌"
                parts.append(f"  {status} {tool}: {result_preview}")

        if snap.get("artifacts_created"):
            parts.append(f"Создано файлов: {', '.join(snap['artifacts_created'][-5:])}")

        if snap.get("blockers"):
            parts.append(f"⛔ Блокеры: {'; '.join(snap['blockers'])}")

        if snap.get("pending_actions"):
            parts.append(f"Осталось: {'; '.join(snap['pending_actions'][:3])}")

        if snap.get("last_user_amendment"):
            parts.append(f"⚠️ Последняя поправка: {snap['last_user_amendment']}")

        if snap.get("next_expected_step"):
            parts.append(f"Следующий шаг: {snap['next_expected_step']}")

        parts.append("═══ КОНЕЦ SNAPSHOT ═══")
        return "\n".join(parts)

    # ═══════════════════════════════════════════
    # CLEANUP
    # ═══════════════════════════════════════════

    def cleanup(self, task_id: str, keep_last: int = 50):
        """Удалить старые snapshots, оставить последние N."""
        conn = self._conn()
        conn.execute("""
            DELETE FROM execution_snapshots 
            WHERE task_id = ? AND id NOT IN (
                SELECT id FROM execution_snapshots 
                WHERE task_id = ? 
                ORDER BY created_at DESC LIMIT ?
            )
        """, (task_id, task_id, keep_last))
        conn.commit()
        conn.close()

    def cleanup_old(self, days: int = 30):
        """Удалить snapshots старше N дней."""
        cutoff = time.time() - days * 86400
        conn = self._conn()
        result = conn.execute(
            "DELETE FROM execution_snapshots WHERE created_at < ?", (cutoff,)
        )
        conn.commit()
        deleted = result.rowcount
        conn.close()
        if deleted:
            logger.info(f"Cleaned up {deleted} old snapshots")

    # ═══════════════════════════════════════════
    # INTERNAL
    # ═══════════════════════════════════════════

    def _row_to_dict(self, row) -> Dict:
        return {
            "id": row[0],
            "task_id": row[1],
            "step_id": row[2],
            "snapshot_type": row[3],
            "iteration": row[4],
            "phase": row[5],
            "agent_role": row[6],
            "completed_actions": json.loads(row[7]) if row[7] else [],
            "artifacts_created": json.loads(row[8]) if row[8] else [],
            "pending_actions": json.loads(row[9]) if row[9] else [],
            "blockers": json.loads(row[10]) if row[10] else [],
            "active_constraints": json.loads(row[11]) if row[11] else [],
            "last_user_amendment": row[12],
            "next_expected_step": row[13],
            "cost_so_far": row[14],
            "tokens_used": row[15],
            "created_at": row[16]
        }
