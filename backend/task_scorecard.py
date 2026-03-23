"""
Task Scorecard — метрики каждой задачи.
=======================================

Собирает и хранит метрики выполнения задачи:
- Время выполнения
- Количество итераций
- Стоимость (токены / деньги)
- Количество tool calls по типам
- Количество ошибок и ретраев
- Финальный вердикт (от FinalJudge)
- Оценка качества

Используется для:
1. Аналитики (какие задачи дорогие/медленные)
2. Улучшения (где агент застревает)
3. Биллинга (точный подсчёт стоимости)
4. Отчётов пользователю

Таблица: task_scorecards (SQLite)
"""

import json
import time
import sqlite3
import logging
import os
from typing import Optional, Dict, List, Any
from datetime import datetime, timezone

logger = logging.getLogger("task_scorecard")

# Use unified database
try:
    from database import _get_conn as _unified_conn
    _USE_UNIFIED_DB = True
except ImportError:
    _USE_UNIFIED_DB = False

DB_PATH = os.path.join(
    os.environ.get("DATA_DIR", "/var/www/orion/backend/data"),
    "task_scorecards.db"
)


class TaskScorecard:
    """
    Хранит и обновляет метрики задачи в реальном времени.
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
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS task_scorecards (
                task_id          TEXT PRIMARY KEY,
                chat_id          TEXT DEFAULT '',
                user_id          TEXT DEFAULT '',
                orion_mode       TEXT DEFAULT 'default',
                
                -- Время
                started_at       REAL,
                finished_at      REAL,
                duration_seconds REAL DEFAULT 0,
                
                -- Итерации
                total_iterations INTEGER DEFAULT 0,
                max_iterations   INTEGER DEFAULT 0,
                
                -- Стоимость
                total_cost_usd   REAL DEFAULT 0.0,
                input_tokens     INTEGER DEFAULT 0,
                output_tokens    INTEGER DEFAULT 0,
                
                -- Tool calls
                tool_calls_json  TEXT DEFAULT '{}',
                total_tool_calls INTEGER DEFAULT 0,
                
                -- Ошибки
                error_count      INTEGER DEFAULT 0,
                retry_count      INTEGER DEFAULT 0,
                errors_json      TEXT DEFAULT '[]',
                
                -- Результат
                verdict          TEXT DEFAULT '',
                quality_score    REAL DEFAULT 0.0,
                final_answer_len INTEGER DEFAULT 0,
                
                -- E7: Agent behavior metrics
                search_fallback_used INTEGER DEFAULT 0,
                approaches_tried     INTEGER DEFAULT 0,
                repeated_failures    INTEGER DEFAULT 0,
                
                -- Метаданные
                objective        TEXT DEFAULT '',
                status           TEXT DEFAULT 'running',
                created_at       REAL,
                updated_at       REAL
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_sc_chat ON task_scorecards(chat_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_sc_user ON task_scorecards(user_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_sc_status ON task_scorecards(status)")
        conn.commit()
        if not _USE_UNIFIED_DB:
            conn.close()
        logger.info(f"TaskScorecard DB initialized: {self._db_path}")

    def _conn(self):
        if _USE_UNIFIED_DB:
            conn = _unified_conn()
            conn.row_factory = sqlite3.Row
            return conn
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        return conn

    # ═══════════════════════════════════════════
    # CREATE
    # ═══════════════════════════════════════════

    def start(
        self,
        task_id: str,
        chat_id: str = "",
        user_id: str = "",
        orion_mode: str = "default",
        objective: str = "",
        max_iterations: int = 30
    ) -> Dict:
        """Начать отслеживание задачи."""
        now = time.time()
        conn = self._conn()
        try:
            conn.execute("""
                INSERT OR REPLACE INTO task_scorecards
                (task_id, chat_id, user_id, orion_mode, started_at,
                 max_iterations, objective, status, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, 'running', ?, ?)
            """, (task_id, chat_id, user_id, orion_mode, now,
                  max_iterations, objective[:500], now, now))
            conn.commit()
        finally:

            # E7: Add new columns if missing
            for col, default in [
                ('search_fallback_used', '0'),
                ('approaches_tried', '0'),
                ('repeated_failures', '0'),
            ]:
                try:
                    conn.execute(f'ALTER TABLE task_scorecards ADD COLUMN {col} INTEGER DEFAULT {default}')
                except Exception:
                    pass  # Column already exists
            if not _USE_UNIFIED_DB:
                conn.close()

        logger.info(f"[scorecard] Started: {task_id[:8]} | {objective[:60]}")
        return self.get(task_id)

    # ═══════════════════════════════════════════
    # UPDATE (real-time)
    # ═══════════════════════════════════════════

    def record_iteration(self, task_id: str, cost: float = 0.0,
                          input_tokens: int = 0, output_tokens: int = 0):
        """Записать одну итерацию агента."""
        conn = self._conn()
        conn.execute("""
            UPDATE task_scorecards SET
                total_iterations = total_iterations + 1,
                total_cost_usd = total_cost_usd + ?,
                input_tokens = input_tokens + ?,
                output_tokens = output_tokens + ?,
                updated_at = ?
            WHERE task_id = ?
        """, (cost, input_tokens, output_tokens, time.time(), task_id))
        conn.commit()
        if not _USE_UNIFIED_DB:
            conn.close()

    def record_tool_call(self, task_id: str, tool_name: str):
        """Записать вызов инструмента."""
        conn = self._conn()
        row = conn.execute(
            "SELECT tool_calls_json, total_tool_calls FROM task_scorecards WHERE task_id = ?",
            (task_id,)
        ).fetchone()

        if not row:
            if not _USE_UNIFIED_DB:
                conn.close()
            return

        tool_calls = json.loads(row[0]) if row[0] else {}
        tool_calls[tool_name] = tool_calls.get(tool_name, 0) + 1
        total = row[1] + 1

        conn.execute("""
            UPDATE task_scorecards SET
                tool_calls_json = ?,
                total_tool_calls = ?,
                updated_at = ?
            WHERE task_id = ?
        """, (json.dumps(tool_calls), total, time.time(), task_id))
        conn.commit()
        if not _USE_UNIFIED_DB:
            conn.close()

    def record_error(self, task_id: str, error: str, is_retry: bool = False):
        """Записать ошибку."""
        conn = self._conn()
        row = conn.execute(
            "SELECT errors_json FROM task_scorecards WHERE task_id = ?",
            (task_id,)
        ).fetchone()

        if not row:
            if not _USE_UNIFIED_DB:
                conn.close()
            return

        errors = json.loads(row[0]) if row[0] else []
        errors.append({
            "error": error[:200],
            "timestamp": time.time(),
            "is_retry": is_retry
        })
        # Хранить только последние 20 ошибок
        errors = errors[-20:]

        retry_inc = 1 if is_retry else 0
        conn.execute("""
            UPDATE task_scorecards SET
                errors_json = ?,
                error_count = error_count + 1,
                retry_count = retry_count + ?,
                updated_at = ?
            WHERE task_id = ?
        """, (json.dumps(errors), retry_inc, time.time(), task_id))
        conn.commit()
        if not _USE_UNIFIED_DB:
            conn.close()

    def finish(
        self,
        task_id: str,
        verdict: str = "",
        quality_score: float = 0.0,
        final_answer_len: int = 0,
        status: str = "done"
    ) -> Optional[Dict]:
        """Завершить отслеживание задачи."""
        now = time.time()
        conn = self._conn()
        row = conn.execute(
            "SELECT started_at FROM task_scorecards WHERE task_id = ?",
            (task_id,)
        ).fetchone()

        duration = now - row[0] if row else 0

        conn.execute("""
            UPDATE task_scorecards SET
                finished_at = ?,
                duration_seconds = ?,
                verdict = ?,
                quality_score = ?,
                final_answer_len = ?,
                status = ?,
                updated_at = ?
            WHERE task_id = ?
        """, (now, duration, verdict, quality_score, final_answer_len,
              status, now, task_id))
        conn.commit()
        if not _USE_UNIFIED_DB:
            conn.close()

        sc = self.get(task_id)
        if sc:
            logger.info(
                f"[scorecard] Finished: {task_id[:8]} | "
                f"verdict={verdict} score={quality_score:.2f} "
                f"dur={duration:.0f}s cost=${sc.get('total_cost_usd', 0):.4f} "
                f"iter={sc.get('total_iterations', 0)}"
            )
        return sc

    # ═══════════════════════════════════════════
    # GET
    # ═══════════════════════════════════════════

    def get(self, task_id: str) -> Optional[Dict]:
        """Получить scorecard по task_id."""
        conn = self._conn()
        row = conn.execute(
            "SELECT * FROM task_scorecards WHERE task_id = ?",
            (task_id,)
        ).fetchone()
        if not _USE_UNIFIED_DB:
            conn.close()
        return self._row_to_dict(row) if row else None

    def get_by_chat(self, chat_id: str, limit: int = 10) -> List[Dict]:
        """Scorecards для чата."""
        conn = self._conn()
        rows = conn.execute(
            "SELECT * FROM task_scorecards WHERE chat_id = ? ORDER BY created_at DESC LIMIT ?",
            (chat_id, limit)
        ).fetchall()
        if not _USE_UNIFIED_DB:
            conn.close()
        return [self._row_to_dict(r) for r in rows]

    def get_analytics(self, user_id: str = "", days: int = 30) -> Dict:
        """Агрегированная аналитика."""
        since = time.time() - days * 86400
        conn = self._conn()

        where = "WHERE created_at > ?"
        params = [since]
        if user_id:
            where += " AND user_id = ?"
            params.append(user_id)

        row = conn.execute(f"""
            SELECT
                COUNT(*) as total_tasks,
                SUM(total_cost_usd) as total_cost,
                AVG(duration_seconds) as avg_duration,
                AVG(total_iterations) as avg_iterations,
                AVG(quality_score) as avg_quality,
                SUM(error_count) as total_errors,
                SUM(total_tool_calls) as total_tool_calls
            FROM task_scorecards {where}
        """, params).fetchone()

        verdicts = conn.execute(f"""
            SELECT verdict, COUNT(*) FROM task_scorecards {where}
            GROUP BY verdict
        """, params).fetchall()

        modes = conn.execute(f"""
            SELECT orion_mode, COUNT(*), AVG(total_cost_usd)
            FROM task_scorecards {where}
            GROUP BY orion_mode
        """, params).fetchall()

        if not _USE_UNIFIED_DB:
            conn.close()

        return {
            "period_days": days,
            "total_tasks": row[0] or 0,
            "total_cost_usd": round(row[1] or 0, 4),
            "avg_duration_seconds": round(row[2] or 0, 1),
            "avg_iterations": round(row[3] or 0, 1),
            "avg_quality_score": round(row[4] or 0, 2),
            "total_errors": row[5] or 0,
            "total_tool_calls": row[6] or 0,
            "verdicts": {v[0]: v[1] for v in verdicts if v[0]},
            "by_mode": {
                m[0]: {"count": m[1], "avg_cost": round(m[2] or 0, 4)}
                for m in modes if m[0]
            }
        }

    def format_for_user(self, task_id: str) -> str:
        """Форматирует scorecard для показа пользователю."""
        sc = self.get(task_id)
        if not sc:
            return ""

        dur = sc.get("duration_seconds", 0)
        dur_str = f"{dur:.0f}с" if dur < 60 else f"{dur/60:.1f}мин"

        lines = [
            f"📊 **Метрики задачи**",
            f"⏱ Время: {dur_str}",
            f"🔄 Итераций: {sc.get('total_iterations', 0)}",
            f"💰 Стоимость: ${sc.get('total_cost_usd', 0):.4f}",
            f"🔧 Tool calls: {sc.get('total_tool_calls', 0)}",
        ]

        if sc.get("error_count", 0) > 0:
            lines.append(f"⚠️ Ошибок: {sc['error_count']}")

        if sc.get("verdict"):
            emoji = {"PASS": "✅", "PARTIAL": "⚠️", "FAIL": "❌"}.get(sc["verdict"], "")
            lines.append(f"{emoji} Вердикт: {sc['verdict']}")

        # Top tools
        tool_calls = sc.get("tool_calls", {})
        if tool_calls:
            top = sorted(tool_calls.items(), key=lambda x: x[1], reverse=True)[:3]
            top_str = ", ".join(f"{t}({c})" for t, c in top)
            lines.append(f"🛠 Топ инструменты: {top_str}")

        return "\n".join(lines)

    # ═══════════════════════════════════════════
    # INTERNAL
    # ═══════════════════════════════════════════

    def _row_to_dict(self, row) -> Dict:
        """Convert sqlite3.Row or tuple to dict."""
        if row is None:
            return {}
        if isinstance(row, sqlite3.Row):
            d = dict(row)
            # Parse JSON fields for convenience
            import json as _json
            for jf in ("tool_calls_json", "errors_json"):
                if jf in d and isinstance(d[jf], str):
                    try:
                        parsed = _json.loads(d[jf])
                        # Add without _json suffix
                        key = jf.replace("_json", "")
                        d[key] = parsed
                    except (ValueError, TypeError):
                        pass
            return d
        # Fallback for tuple rows
        cols = [
            "task_id", "chat_id", "user_id", "orion_mode",
            "started_at", "finished_at", "duration_seconds",
            "total_iterations", "max_iterations",
            "total_cost_usd", "input_tokens", "output_tokens",
            "tool_calls_json", "total_tool_calls",
            "error_count", "retry_count", "errors_json",
            "verdict", "quality_score", "final_answer_len",
            "objective", "status", "created_at", "updated_at"
        ]
        d = {}
        for i, c in enumerate(cols):
            if i < len(row):
                d[c] = row[i]
        return d


# ── Singleton factory ──
_singleton_store = None

def get_scorecard_store() -> TaskScorecard:
    """Return singleton TaskScorecard instance."""
    global _singleton_store
    if _singleton_store is None:
        _singleton_store = TaskScorecard()
    return _singleton_store


# ═══ A6: PASS/FAIL Classification ═══
HARD_FAIL_PATTERNS = [
    "402 Payment Required",
    "500 Internal Server Error",
    "Response ended prematurely",
]

def classify_task_result(status_code=None, task_status=None, tokens_in=0, tokens_out=0, elapsed=0, is_final=True):
    """Classify task result with context awareness."""
    # Hard FAIL
    if task_status and task_status != "SUCCESS":
        return "FAIL", "task_status != SUCCESS"
    if status_code and status_code >= 500:
        return "FAIL", f"HTTP {status_code}"
    if status_code == 402:
        return "FAIL", "HTTP 402 Payment Required"
    if tokens_in == 0 and tokens_out == 0 and elapsed > 30:
        return "FAIL", "zero tokens after 30s"
    # Contextual
    if status_code == 404 and not is_final:
        return "OK", "404 as intermediate check"
    if status_code == 404 and is_final:
        return "FAIL", "404 on final result"
    if status_code == 401 and not is_final:
        return "OK", "401 as auth flow check"
    return "PASS", "all checks passed"
