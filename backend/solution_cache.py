"""
ПАТЧ 9: Solution Cache — агент учится на своём опыте.

После каждого task_complete агент сохраняет: какая была задача, какие действия сработали,
какие ошибки встретил и как обошёл. При новой похожей задаче — находит решение и инжектирует в промпт.

Использует: SQLite для хранения, paraphrase-multilingual-MiniLM-L12-v2 для эмбеддингов (из memory_v9).
"""

import json
import sqlite3
import logging
import os
import time
import numpy as np
from typing import Optional, Dict, List

logger = logging.getLogger("solution_cache")

# SQLite DB path
SOLUTION_DB_PATH = os.path.join(os.path.dirname(__file__), "memory_v9", "data", "solution_cache.db")


class SolutionExtractor:
    """
    Извлекает структурированное решение из actions_log после task_complete.
    Суммаризирует через LLM в 3-5 строк.
    """

    @staticmethod
    def extract(actions_log: list, task_text: str, summary: str) -> Dict:
        """
        Извлекает ключевые данные из лога действий:
        - SSH команды которые сработали
        - Файлы которые создал
        - Ошибки и как обошёл
        """
        commands = []
        files_created = []
        errors_and_fixes = []
        failed_approaches = []
        tools_used = set()

        for i, action in enumerate(actions_log):
            tool = action.get("tool", "")
            args = action.get("args", {})
            success = action.get("success", False)
            result = action.get("result", "")
            tools_used.add(tool)

            # Track failed approaches
            if not success and tool:
                failed_approaches.append({
                    "tool": tool,
                    "args_preview": str(args)[:200],
                    "error": str(result)[:300] if result else "unknown",
                    "iteration": i
                })

            # SSH commands
            if tool == "ssh_execute":
                cmd = args.get("command", "")
                if success and cmd:
                    commands.append(cmd)
                elif not success and cmd:
                    # Look for fix in next actions
                    fix_cmd = ""
                    for j in range(i + 1, min(i + 5, len(actions_log))):
                        next_act = actions_log[j]
                        if next_act.get("tool") == "ssh_execute" and next_act.get("success"):
                            fix_cmd = next_act.get("args", {}).get("command", "")
                            break
                    error_text = str(result)[:200] if result else "unknown error"
                    errors_and_fixes.append({
                        "error": f"SSH '{cmd[:100]}' failed: {error_text}",
                        "fix": fix_cmd or "no fix found"
                    })

            # File operations
            elif tool == "file_write" and success:
                path = args.get("path", "")
                if path:
                    files_created.append(path)

            # Browser errors
            elif tool in ("browser_navigate", "browser_check_site"):
                status = 0
                if isinstance(result, dict):
                    status = result.get("status_code", 0)
                if status in (401, 403, 404, 500):
                    url = args.get("url", "")
                    errors_and_fixes.append({
                        "error": f"HTTP {status} on {url[:100]}",
                        "fix": "see subsequent actions"
                    })

            # FTP errors
            elif tool == "ftp_upload" or (tool == "ssh_execute" and "ftp" in str(args).lower()):
                if not success:
                    errors_and_fixes.append({
                        "error": f"FTP error: {str(result)[:200]}",
                        "fix": "check password escaping (# → %23)"
                    })

        return {
            "task_text": task_text[:500],
            "summary": summary[:500],
            "commands": commands[-20:],  # Last 20 successful commands
            "files_created": files_created,
            "errors_and_fixes": errors_and_fixes[:10],
            "failed_approaches": failed_approaches[:15],
            "failure_patterns": _extract_failure_patterns(failed_approaches),
            "tools_used": list(tools_used),
            "total_actions": len(actions_log),
            "success_rate": sum(1 for a in actions_log if a.get("success", False)) / max(len(actions_log), 1)
        }


def _extract_failure_patterns(failed_approaches: list) -> list:
    """Выделяет паттерны из неудачных подходов."""
    patterns = []
    error_types = {}
    for fa in failed_approaches:
        error_key = fa["error"][:50]
        if error_key not in error_types:
            error_types[error_key] = {"count": 0, "tools": set(), "first_error": fa["error"]}
        error_types[error_key]["count"] += 1
        error_types[error_key]["tools"].add(fa["tool"])

    for key, data in error_types.items():
        if data["count"] >= 2:  # Повторяющаяся ошибка
            patterns.append({
                "pattern": key,
                "count": data["count"],
                "tools": list(data["tools"]),
                "recommendation": f"НЕ используй этот подход — ошибка повторялась {data['count']} раз"
            })
    return patterns


# ── PATCH: Global singleton encoder to avoid reloading on every SolutionCache() ──
_GLOBAL_ENCODER = None
_GLOBAL_ENCODER_LOCK = None

def _get_global_encoder():
    global _GLOBAL_ENCODER, _GLOBAL_ENCODER_LOCK
    import threading
    if _GLOBAL_ENCODER_LOCK is None:
        _GLOBAL_ENCODER_LOCK = threading.Lock()
    with _GLOBAL_ENCODER_LOCK:
        if _GLOBAL_ENCODER is None:
            try:
                from sentence_transformers import SentenceTransformer
                _GLOBAL_ENCODER = SentenceTransformer("paraphrase-multilingual-MiniLM-L12-v2")
                logger.info("Solution cache: global neural encoder loaded")
            except Exception as e:
                logger.warning(f"Solution cache: encoder not available ({e}), using fallback")
                _GLOBAL_ENCODER = False  # Mark as failed so we don't retry
    return _GLOBAL_ENCODER if _GLOBAL_ENCODER is not False else None

class SolutionCache:
    """
    Кеш решений с семантическим поиском.
    SQLite таблица solutions: task_embedding, task_text, solution_summary, agent_key,
    commands, files_created, errors_and_fixes, confidence, created_at.
    """

    def __init__(self, call_ai_simple_fn=None):
        """
        Args:
            call_ai_simple_fn: функция для вызова LLM (self._call_ai_simple из AgentLoop)
        """
        self._call_ai = call_ai_simple_fn
        self._encoder = None
        self._db_path = SOLUTION_DB_PATH
        self._init_db()
        self._init_encoder()

    def _init_db(self):
        """Создаёт таблицу solutions если не существует."""
        os.makedirs(os.path.dirname(self._db_path), exist_ok=True)
        conn = sqlite3.connect(self._db_path)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS solutions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_embedding BLOB,
                task_text TEXT NOT NULL,
                solution_summary TEXT NOT NULL,
                agent_key TEXT DEFAULT '',
                commands TEXT DEFAULT '[]',
                files_created TEXT DEFAULT '[]',
                errors_and_fixes TEXT DEFAULT '[]',
                failed_approaches TEXT DEFAULT '[]',
                failure_patterns TEXT DEFAULT '[]',
                confidence REAL DEFAULT 0.5,
                use_count INTEGER DEFAULT 0,
                created_at REAL,
                updated_at REAL
            )
        """)
        # Add columns for existing DBs (migration)
        try:
            conn.execute("ALTER TABLE solutions ADD COLUMN failed_approaches TEXT DEFAULT '[]'")
        except Exception:
            pass
        try:
            conn.execute("ALTER TABLE solutions ADD COLUMN failure_patterns TEXT DEFAULT '[]'")
        except Exception:
            pass
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_solutions_created
            ON solutions(created_at DESC)
        """)
        conn.commit()
        conn.close()
        logger.info(f"Solution cache DB initialized: {self._db_path}")

    def _init_encoder(self):
        """Инициализирует sentence-transformers encoder (singleton)."""
        self._encoder = _get_global_encoder()

    def _embed(self, text: str) -> np.ndarray:
        """Создаёт эмбеддинг текста."""
        if self._encoder:
            return self._encoder.encode(text)
        # Fallback: hash-based embedding (384 dims to match MiniLM)
        import hashlib
        dim = 384
        vec = np.zeros(dim)
        words = text.lower().split()
        for i, word in enumerate(words):
            h = int(hashlib.md5(word.encode()).hexdigest(), 16)
            idx = h % dim
            vec[idx] += 1.0 / (i + 1)
        norm = np.linalg.norm(vec)
        if norm > 0:
            vec = vec / norm
        return vec

    def _cosine_sim(self, a: np.ndarray, b: np.ndarray) -> float:
        """Косинусное сходство между двумя векторами."""
        norm_a = np.linalg.norm(a)
        norm_b = np.linalg.norm(b)
        if norm_a == 0 or norm_b == 0:
            return 0.0
        return float(np.dot(a, b) / (norm_a * norm_b))

    def recall(self, task_text: str, threshold: float = 0.65, top_k: int = 3) -> List[Dict]:
        """
        Ищет похожие решения в кеше.
        Возвращает список решений с similarity >= threshold.
        """
        try:
            query_emb = self._embed(task_text)
            conn = sqlite3.connect(self._db_path)
            rows = conn.execute(
                "SELECT id, task_embedding, task_text, solution_summary, commands, "
                "files_created, errors_and_fixes, failed_approaches, failure_patterns, "
                "confidence, use_count FROM solutions "
                "ORDER BY created_at DESC LIMIT 100"
            ).fetchall()
            conn.close()

            results = []
            for row in rows:
                row_id, emb_blob, t_text, summary, cmds, files, errors, failed, patterns, conf, use_count = row
                if emb_blob:
                    stored_emb = np.frombuffer(emb_blob, dtype=np.float32)
                    sim = self._cosine_sim(query_emb, stored_emb)
                    if sim >= threshold:
                        results.append({
                            "id": row_id,
                            "similarity": sim,
                            "task_text": t_text,
                            "solution_summary": summary,
                            "commands": json.loads(cmds) if cmds else [],
                            "files_created": json.loads(files) if files else [],
                            "errors_and_fixes": json.loads(errors) if errors else [],
                            "failed_approaches": json.loads(failed) if failed else [],
                            "failure_patterns": json.loads(patterns) if patterns else [],
                            "confidence": conf,
                            "use_count": use_count
                        })

            # Sort by similarity * confidence
            results.sort(key=lambda x: x["similarity"] * x["confidence"], reverse=True)
            return results[:top_k]

        except Exception as e:
            logger.warning(f"Solution cache recall error: {e}")
            return []

    def save(self, task_text: str, extracted: Dict, agent_key: str = "") -> bool:
        """
        Сохраняет решение в кеш.
        Если очень похожее решение уже есть — обновляет confidence.
        """
        try:
            emb = self._embed(task_text)
            emb_blob = emb.astype(np.float32).tobytes()

            # Суммаризация через LLM
            solution_summary = self._summarize(task_text, extracted)

            conn = sqlite3.connect(self._db_path)
            now = time.time()

            # Проверяем дубликат
            existing = self.recall(task_text, threshold=0.85, top_k=1)
            if existing:
                # Обновляем confidence существующего
                old_id = existing[0]["id"]
                old_conf = existing[0]["confidence"]
                new_conf = min(old_conf + 0.1, 1.0)
                conn.execute(
                    "UPDATE solutions SET confidence=?, use_count=use_count+1, "
                    "updated_at=?, solution_summary=? WHERE id=?",
                    (new_conf, now, solution_summary, old_id)
                )
                logger.info(f"Solution cache: updated existing #{old_id}, confidence {old_conf:.2f} → {new_conf:.2f}")
            else:
                # Новая запись
                conn.execute(
                    "INSERT INTO solutions (task_embedding, task_text, solution_summary, "
                    "agent_key, commands, files_created, errors_and_fixes, "
                    "failed_approaches, failure_patterns, confidence, "
                    "use_count, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        emb_blob,
                        task_text[:500],
                        solution_summary,
                        agent_key,
                        json.dumps(extracted.get("commands", []), ensure_ascii=False),
                        json.dumps(extracted.get("files_created", []), ensure_ascii=False),
                        json.dumps(extracted.get("errors_and_fixes", []), ensure_ascii=False),
                        json.dumps(extracted.get("failed_approaches", []), ensure_ascii=False),
                        json.dumps(extracted.get("failure_patterns", []), ensure_ascii=False),
                        0.5,  # initial confidence
                        0,
                        now,
                        now
                    )
                )
                logger.info(f"Solution cache: saved new solution for '{task_text[:80]}...'")

            conn.commit()
            conn.close()
            return True

        except Exception as e:
            logger.error(f"Solution cache save error: {e}")
            return False

    def _summarize(self, task_text: str, extracted: Dict) -> str:
        """Суммаризирует решение через LLM или формирует шаблон."""
        # Попробуем через LLM
        if self._call_ai:
            try:
                cmds = extracted.get("commands", [])[-10:]
                files = extracted.get("files_created", [])
                errors = extracted.get("errors_and_fixes", [])[:5]

                prompt = (
                    f"Задача: {task_text[:300]}\n\n"
                    f"Успешные команды: {json.dumps(cmds[:5], ensure_ascii=False)}\n"
                    f"Созданные файлы: {json.dumps(files, ensure_ascii=False)}\n"
                    f"Ошибки и исправления: {json.dumps(errors, ensure_ascii=False)}\n\n"
                    "Суммаризируй решение в 3-5 строк. Формат:\n"
                    "Что работало: [конкретные шаги]\n"
                    "Ошибки: [что пошло не так и как обошли]\n"
                    "Ключевые файлы: [пути]\n"
                    "Используй это как основу для повторного выполнения."
                )
                messages = [
                    {"role": "system", "content": "Ты суммаризатор решений. Кратко, конкретно, без воды."},
                    {"role": "user", "content": prompt}
                ]
                result = self._call_ai(messages)
                if result and len(result) > 20:
                    return result[:1000]
            except Exception as e:
                logger.debug(f"LLM summarize failed: {e}")

        # Fallback: шаблонная суммаризация
        cmds = extracted.get("commands", [])
        files = extracted.get("files_created", [])
        errors = extracted.get("errors_and_fixes", [])

        summary_parts = [f"Задача: {task_text[:200]}"]
        if cmds:
            summary_parts.append(f"Команды: {'; '.join(cmds[-5:])}")
        if files:
            summary_parts.append(f"Файлы: {', '.join(files[-5:])}")
        if errors:
            for e in errors[:3]:
                summary_parts.append(f"Ошибка: {e['error'][:100]} → Исправление: {e['fix'][:100]}")

        return "\n".join(summary_parts)

    def format_for_prompt(self, solutions: List[Dict]) -> str:
        """Форматирует найденные решения для инжекции в промпт агента."""
        if not solutions:
            return ""

        parts = ["\n\n📋 ОПЫТ ИЗ ПРЕДЫДУЩИХ ЗАДАЧ (Solution Cache):"]
        for i, sol in enumerate(solutions, 1):
            sim = sol.get("similarity", 0)
            conf = sol.get("confidence", 0)
            parts.append(f"\n--- Решение #{i} (сходство: {sim:.0%}, уверенность: {conf:.0%}) ---")
            parts.append(sol.get("solution_summary", ""))

            errors = sol.get("errors_and_fixes", [])
            failed = sol.get("failed_approaches", [])
            patterns = sol.get("failure_patterns", [])

            if patterns:
                parts.append("🚫 ИЗБЕГАЙ (повторяющиеся ошибки):")
                for p in patterns[:3]:
                    parts.append(f"  - {p['pattern'][:100]} (повторялось {p['count']} раз)")

            if errors:
                parts.append("⚠️ Ошибки и как обошли:")
                for e in errors[:3]:
                    parts.append(f"  - {e.get('error', '')[:80]} → {e.get('fix', '')[:80]}")

            if failed:
                parts.append(f"❌ Неудачных попыток: {len(failed)} — не повторяй их")

        parts.append("\nИспользуй этот опыт. Не повторяй ошибки. Что работало — используй как основу.")
        return "\n".join(parts)

    def increment_use(self, solution_id: int):
        """Увеличивает счётчик использования и confidence."""
        try:
            conn = sqlite3.connect(self._db_path)
            conn.execute(
                "UPDATE solutions SET use_count = use_count + 1, "
                "confidence = MIN(confidence + 0.05, 1.0), "
                "updated_at = ? WHERE id = ?",
                (time.time(), solution_id)
            )
            conn.commit()
            conn.close()
        except Exception as e:
            logger.debug(f"Solution cache increment error: {e}")
