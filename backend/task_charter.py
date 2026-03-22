"""
Task Charter — единый источник истины для задачи.
=================================================

Каждая задача имеет Charter: цель, ограничения, deliverables,
критерии done, текущий шаг, версия, поправки пользователя.

Charter подгружается в КАЖДЫЙ значимый LLM-вызов первым.
Агенты читают Charter, а не историю чата.

Таблица: task_charters (SQLite)
"""

import json
import time
import sqlite3
import logging
import os
from typing import Optional, Dict, List, Any

logger = logging.getLogger("task_charter")

# Use unified database
try:
    from database import _get_conn as _unified_conn
    _USE_UNIFIED_DB = True
except ImportError:
    _USE_UNIFIED_DB = False

DB_PATH = os.path.join(
    os.environ.get("DATA_DIR", "/var/www/orion/backend/data"),
    "task_charters.db"
)


class TaskCharterStore:
    """
    CRUD для Task Charter с версионированием и amendments.
    """

    def __init__(self, db_path: str = DB_PATH):
        self._db_path = db_path
        if not _USE_UNIFIED_DB:
            self._init_db()
        else:
            logger.info(f"{self.__class__.__name__} using unified database.sqlite")

    def _init_db(self):
        os.makedirs(os.path.dirname(self._db_path), exist_ok=True)
        conn = sqlite3.connect(self._db_path)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS task_charters (
                task_id TEXT PRIMARY KEY,
                chat_id TEXT NOT NULL,
                project_id TEXT DEFAULT '',
                version INTEGER DEFAULT 1,
                status TEXT DEFAULT 'active',
                
                -- Цель
                primary_objective TEXT NOT NULL,
                current_objective TEXT NOT NULL,
                
                -- Что нужно сделать
                success_criteria_json TEXT DEFAULT '[]',
                constraints_json TEXT DEFAULT '[]',
                deliverables_json TEXT DEFAULT '[]',
                done_definition TEXT DEFAULT '',
                
                -- План и прогресс
                current_plan_json TEXT DEFAULT '[]',
                current_step_id TEXT DEFAULT '',
                completed_steps_json TEXT DEFAULT '[]',
                failed_steps_json TEXT DEFAULT '[]',
                
                -- Поправки пользователя
                amendments_json TEXT DEFAULT '[]',
                
                -- Метаданные
                total_iterations INTEGER DEFAULT 0,
                total_cost REAL DEFAULT 0.0,
                task_type TEXT DEFAULT 'general',
                site_type TEXT DEFAULT '',
                created_at REAL,
                updated_at REAL
            )
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_charter_chat 
            ON task_charters(chat_id)
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_charter_status
            ON task_charters(status)
        """)
        conn.commit()
        if not _USE_UNIFIED_DB:
            conn.close()
        logger.info(f"TaskCharterStore initialized: {self._db_path}")

    def _conn(self):
        if _USE_UNIFIED_DB:
            return _unified_conn()
        return sqlite3.connect(self._db_path)

    # ═══════════════════════════════════════════
    # CREATE
    # ═══════════════════════════════════════════

    def create(self, task_id: str, chat_id: str, 
               objective: str, 
               success_criteria: List[str] = None,
               constraints: List[str] = None,
               deliverables: List[str] = None,
               done_definition: str = "",
               project_id: str = "",
               task_type: str = "general",
               site_type: str = "") -> Dict:
        """
        Создать новый Charter для задачи.
        
        Args:
            task_id: уникальный ID задачи
            chat_id: ID чата
            objective: главная цель задачи
            success_criteria: критерии успеха ["сайт открывается", "форма работает"]
            constraints: ограничения ["бюджет $5", "только MiniMax"]
            deliverables: что должно быть создано ["index.html", "style.css"]
            done_definition: когда считать задачу выполненной
            project_id: ID проекта (опционально)
        """
        now = time.time()
        charter = {
            "task_id": task_id,
            "chat_id": chat_id,
            "project_id": project_id,
            "version": 1,
            "status": "active",
            "primary_objective": objective,
            "current_objective": objective,
            "success_criteria": success_criteria or [],
            "constraints": constraints or [],
            "deliverables": deliverables or [],
            "done_definition": done_definition,
            "current_plan": [],
            "current_step_id": "",
            "completed_steps": [],
            "failed_steps": [],
            "amendments": [],
            "total_iterations": 0,
            "total_cost": 0.0,
            "task_type": task_type,
            "site_type": site_type,
            "created_at": now,
            "updated_at": now
        }

        conn = self._conn()
        try:
            conn.execute("""
                INSERT INTO task_charters (
                    task_id, chat_id, project_id, version, status,
                    primary_objective, current_objective,
                    success_criteria_json, constraints_json, 
                    deliverables_json, done_definition,
                    current_plan_json, current_step_id,
                    completed_steps_json, failed_steps_json,
                    amendments_json,
                    total_iterations, total_cost,
                    task_type, site_type,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                task_id, chat_id, project_id, 1, "active",
                objective, objective,
                json.dumps(success_criteria or [], ensure_ascii=False),
                json.dumps(constraints or [], ensure_ascii=False),
                json.dumps(deliverables or [], ensure_ascii=False),
                done_definition,
                "[]", "", "[]", "[]", "[]",
                0, 0.0, task_type, site_type, now, now
            ))
            conn.commit()
            logger.info(f"Charter created: {task_id} | {objective[:80]}")
        except sqlite3.IntegrityError:
            logger.warning(f"Charter already exists: {task_id}, updating")
            self.update(task_id, {
                "current_objective": objective,
                "status": "active"
            })
            charter = self.get(task_id)
        finally:
            if not _USE_UNIFIED_DB:
                conn.close()

        return charter

    # ═══════════════════════════════════════════
    # GET
    # ═══════════════════════════════════════════

    def get(self, task_id: str) -> Optional[Dict]:
        """Получить Charter по task_id."""
        conn = self._conn()
        row = conn.execute(
            "SELECT * FROM task_charters WHERE task_id = ?", (task_id,)
        ).fetchone()
        if not _USE_UNIFIED_DB:
            conn.close()

        if not row:
            return None
        return self._row_to_dict(row)

    def get_by_chat(self, chat_id: str) -> Optional[Dict]:
        """Получить активный Charter для чата."""
        conn = self._conn()
        row = conn.execute(
            "SELECT * FROM task_charters WHERE chat_id = ? AND status = 'active' "
            "ORDER BY updated_at DESC LIMIT 1", (chat_id,)
        ).fetchone()
        if not _USE_UNIFIED_DB:
            conn.close()

        if not row:
            return None
        return self._row_to_dict(row)

    # ═══════════════════════════════════════════
    # UPDATE
    # ═══════════════════════════════════════════

    def update(self, task_id: str, patch: Dict) -> Optional[Dict]:
        """
        Обновить Charter. Инкрементирует версию.
        
        patch может содержать:
        - current_objective, done_definition, status
        - current_step_id
        - total_iterations, total_cost
        """
        conn = self._conn()
        now = time.time()

        # Получить текущую версию
        row = conn.execute(
            "SELECT version FROM task_charters WHERE task_id = ?", (task_id,)
        ).fetchone()
        if not row:
            if not _USE_UNIFIED_DB:
                conn.close()
            return None

        new_version = row[0] + 1
        sets = ["version = ?", "updated_at = ?"]
        vals = [new_version, now]

        # Простые текстовые поля
        for field in ["current_objective", "done_definition", "status",
                       "current_step_id", "project_id",
                       "task_type", "site_type"]:
            if field in patch:
                sets.append(f"{field} = ?")
                vals.append(patch[field])

        # Числовые поля
        for field in ["total_iterations", "total_cost"]:
            if field in patch:
                sets.append(f"{field} = ?")
                vals.append(patch[field])

        # JSON поля
        json_fields = {
            "success_criteria": "success_criteria_json",
            "constraints": "constraints_json",
            "deliverables": "deliverables_json",
            "current_plan": "current_plan_json",
            "completed_steps": "completed_steps_json",
            "failed_steps": "failed_steps_json",
        }
        for key, col in json_fields.items():
            if key in patch:
                sets.append(f"{col} = ?")
                vals.append(json.dumps(patch[key], ensure_ascii=False))

        vals.append(task_id)
        conn.execute(
            f"UPDATE task_charters SET {', '.join(sets)} WHERE task_id = ?",
            vals
        )
        conn.commit()
        if not _USE_UNIFIED_DB:
            conn.close()

        return self.get(task_id)

    # ═══════════════════════════════════════════
    # AMENDMENTS (поправки пользователя)
    # ═══════════════════════════════════════════

    def add_amendment(self, task_id: str, text: str, 
                       amendment_type: str = "user_input") -> Optional[Dict]:
        """
        Добавить поправку пользователя к задаче.
        
        amendment_type: "user_input", "scope_change", "priority_change",
                        "constraint_add", "constraint_remove"
        """
        conn = self._conn()
        row = conn.execute(
            "SELECT amendments_json, version FROM task_charters WHERE task_id = ?",
            (task_id,)
        ).fetchone()

        if not row:
            if not _USE_UNIFIED_DB:
                conn.close()
            return None

        amendments = json.loads(row[0]) if row[0] else []
        amendments.append({
            "text": text,
            "type": amendment_type,
            "version": row[1],
            "timestamp": time.time()
        })

        conn.execute(
            "UPDATE task_charters SET amendments_json = ?, version = version + 1, "
            "updated_at = ? WHERE task_id = ?",
            (json.dumps(amendments, ensure_ascii=False), time.time(), task_id)
        )
        conn.commit()
        if not _USE_UNIFIED_DB:
            conn.close()

        logger.info(f"Amendment added to {task_id}: {text[:80]}")
        return self.get(task_id)

    # ═══════════════════════════════════════════
    # STEP MANAGEMENT
    # ═══════════════════════════════════════════

    def set_current_step(self, task_id: str, step_id: str) -> Optional[Dict]:
        """Установить текущий шаг."""
        return self.update(task_id, {"current_step_id": step_id})

    def complete_step(self, task_id: str, step_id: str, 
                       result: str = "") -> Optional[Dict]:
        """Отметить шаг как выполненный."""
        charter = self.get(task_id)
        if not charter:
            return None

        completed = charter.get("completed_steps", [])
        completed.append({
            "step_id": step_id,
            "result": result[:500],
            "completed_at": time.time()
        })

        return self.update(task_id, {"completed_steps": completed})

    def fail_step(self, task_id: str, step_id: str, 
                   error: str = "") -> Optional[Dict]:
        """Отметить шаг как проваленный."""
        charter = self.get(task_id)
        if not charter:
            return None

        failed = charter.get("failed_steps", [])
        failed.append({
            "step_id": step_id,
            "error": error[:500],
            "failed_at": time.time()
        })

        return self.update(task_id, {"failed_steps": failed})

    def set_plan(self, task_id: str, steps: List[Dict]) -> Optional[Dict]:
        """
        Установить план выполнения.
        
        steps: [{"id": "1", "name": "Установить nginx", "status": "pending"}, ...]
        """
        return self.update(task_id, {"current_plan": steps})

    # ═══════════════════════════════════════════
    # COMPLETE / CANCEL
    # ═══════════════════════════════════════════

    def complete(self, task_id: str) -> Optional[Dict]:
        """Отметить задачу как выполненную."""
        return self.update(task_id, {"status": "completed"})

    def cancel(self, task_id: str) -> Optional[Dict]:
        """Отменить задачу."""
        return self.update(task_id, {"status": "cancelled"})

    def pause(self, task_id: str) -> Optional[Dict]:
        """Поставить задачу на паузу."""
        return self.update(task_id, {"status": "paused"})

    def resume(self, task_id: str) -> Optional[Dict]:
        """Возобновить задачу."""
        return self.update(task_id, {"status": "active"})

    # ═══════════════════════════════════════════
    # FORMAT FOR PROMPT
    # ═══════════════════════════════════════════

    def format_for_prompt(self, task_id: str) -> str:
        """
        Форматирует Charter для инжекции в LLM промпт.
        Это ПЕРВОЕ что видит агент перед каждым действием.
        """
        charter = self.get(task_id)
        if not charter:
            return ""

        parts = []
        parts.append("═══ TASK CHARTER (источник истины) ═══")
        parts.append(f"Цель: {charter['current_objective']}")

        # Pipeline type
        task_type = charter.get("task_type", "general")
        if task_type != "general":
            parts.append(f"Тип задачи: {task_type.upper()}")
        site_type = charter.get("site_type", "")
        if site_type:
            parts.append(f"Тип сайта: {site_type}")

        if charter.get("primary_objective") != charter.get("current_objective"):
            parts.append(f"Исходная цель: {charter['primary_objective']}")

        if charter.get("success_criteria"):
            criteria = charter["success_criteria"]
            parts.append(f"Критерии успеха: {'; '.join(criteria)}")

        if charter.get("constraints"):
            parts.append(f"Ограничения: {'; '.join(charter['constraints'])}")

        if charter.get("deliverables"):
            parts.append(f"Deliverables: {'; '.join(charter['deliverables'])}")

        if charter.get("done_definition"):
            parts.append(f"Когда готово: {charter['done_definition']}")

        # Прогресс
        completed = charter.get("completed_steps", [])
        failed = charter.get("failed_steps", [])
        plan = charter.get("current_plan", [])

        if plan:
            total = len(plan)
            done = len(completed)
            parts.append(f"Прогресс: {done}/{total} шагов")

        if completed:
            last_3 = completed[-3:]
            parts.append("Последние выполненные:")
            for s in last_3:
                parts.append(f"  ✅ {s.get('step_id', '')}: {s.get('result', '')[:80]}")

        if failed:
            last_2 = failed[-2:]
            parts.append("Последние неудачи:")
            for s in last_2:
                parts.append(f"  ❌ {s.get('step_id', '')}: {s.get('error', '')[:80]}")

        # Поправки пользователя — КРИТИЧНО
        amendments = charter.get("amendments", [])
        if amendments:
            parts.append("⚠️ ПОПРАВКИ ПОЛЬЗОВАТЕЛЯ (обязательно учесть):")
            for a in amendments[-5:]:
                parts.append(f"  → {a['text'][:200]}")

        if charter.get("current_step_id"):
            parts.append(f"Текущий шаг: {charter['current_step_id']}")

        parts.append(f"Версия: {charter.get('version', 1)} | "
                     f"Итераций: {charter.get('total_iterations', 0)} | "
                     f"Стоимость: ${charter.get('total_cost', 0):.4f}")
        parts.append("═══ КОНЕЦ CHARTER ═══")

        return "\n".join(parts)

    # ═══════════════════════════════════════════
    # RECONSTRUCTION AFTER CRASH
    # ═══════════════════════════════════════════

    def reconstruct_state(self, task_id: str) -> Dict:
        """
        Восстановить состояние после крэша.
        Отвечает на 5 вопросов:
        1. Какая задача была активна?
        2. На каком шаге остановились?
        3. Что уже сделано?
        4. Что нельзя забыть?
        5. Какой следующий шаг?
        """
        charter = self.get(task_id)
        if not charter:
            return {"error": "Charter not found"}

        completed = charter.get("completed_steps", [])
        failed = charter.get("failed_steps", [])
        plan = charter.get("current_plan", [])
        amendments = charter.get("amendments", [])

        # Определить следующий шаг
        completed_ids = {s.get("step_id") for s in completed}
        next_step = None
        for step in plan:
            if step.get("id") not in completed_ids:
                next_step = step
                break

        return {
            "active_task": charter["current_objective"],
            "current_step": charter.get("current_step_id", "неизвестно"),
            "completed": [s.get("step_id", "") for s in completed],
            "must_not_forget": [a["text"] for a in amendments[-5:]],
            "next_safe_step": next_step.get("name", "определить план") if next_step else "задача завершена",
            "total_iterations": charter.get("total_iterations", 0),
            "total_cost": charter.get("total_cost", 0),
            "failed_steps": [f"{s.get('step_id')}: {s.get('error', '')[:50]}" for s in failed[-3:]]
        }

    # ═══════════════════════════════════════════
    # INTERNAL
    # ═══════════════════════════════════════════

    def _row_to_dict(self, row) -> Dict:
        """Конвертировать строку SQLite в dict."""
        d = {
            "task_id": row[0],
            "chat_id": row[1],
            "project_id": row[2],
            "version": row[3],
            "status": row[4],
            "primary_objective": row[5],
            "current_objective": row[6],
            "success_criteria": json.loads(row[7]) if row[7] else [],
            "constraints": json.loads(row[8]) if row[8] else [],
            "deliverables": json.loads(row[9]) if row[9] else [],
            "done_definition": row[10],
            "current_plan": json.loads(row[11]) if row[11] else [],
            "current_step_id": row[12],
            "completed_steps": json.loads(row[13]) if row[13] else [],
            "failed_steps": json.loads(row[14]) if row[14] else [],
            "amendments": json.loads(row[15]) if row[15] else [],
            "total_iterations": row[16],
            "total_cost": row[17],
        }
        # New fields (task_type, site_type) — handle both old and new schema
        if len(row) > 20:
            d["task_type"] = row[18] or "general"
            d["site_type"] = row[19] or ""
            d["created_at"] = row[20]
            d["updated_at"] = row[21]
        else:
            d["task_type"] = "general"
            d["site_type"] = ""
            d["created_at"] = row[18]
            d["updated_at"] = row[19]
        return d
