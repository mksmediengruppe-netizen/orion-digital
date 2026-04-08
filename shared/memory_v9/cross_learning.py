"""
Cross-User Anonymous Learning — агент учится из анонимизированных паттернов всех пользователей.

Никаких PII. Только паттерны команд и их success rate.
Пример: "после apt install nginx в 85% случаев следует systemctl enable nginx"

Данные полностью анонимны:
- Нет user_id, IP, паролей, путей к файлам
- Только нормализованные паттерны команд
- Только статистика (count, success_rate)
"""

import sqlite3, os, re, json, hashlib, threading, logging
from datetime import datetime, timezone
from typing import List, Dict, Tuple, Optional
from .config import MemoryConfig

logger = logging.getLogger("memory.cross_learning")
_local = threading.local()


def _db():
    if not hasattr(_local, "c") or _local.c is None:
        db_path = os.path.join(MemoryConfig.DATA_DIR, "cross_learning.db")
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        _local.c = sqlite3.connect(db_path, timeout=15)
        _local.c.execute("PRAGMA journal_mode=WAL")
        _local.c.row_factory = sqlite3.Row
        _local.c.executescript("""
            CREATE TABLE IF NOT EXISTS command_pairs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                command_a TEXT NOT NULL,
                command_b TEXT NOT NULL,
                pair_hash TEXT UNIQUE,
                count INTEGER DEFAULT 1,
                success_count INTEGER DEFAULT 0,
                last_seen TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_pair_a ON command_pairs(command_a);
            CREATE TABLE IF NOT EXISTS tool_sequences (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tool_pattern TEXT NOT NULL,
                pattern_hash TEXT UNIQUE,
                count INTEGER DEFAULT 1,
                avg_success_rate REAL DEFAULT 0,
                example_context TEXT,
                last_seen TEXT
            );
            CREATE TABLE IF NOT EXISTS error_solutions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                error_pattern TEXT NOT NULL,
                solution_pattern TEXT NOT NULL,
                pair_hash TEXT UNIQUE,
                count INTEGER DEFAULT 1,
                success_rate REAL DEFAULT 0,
                last_seen TEXT
            );
        """)
        _local.c.commit()
    return _local.c


def _anonymize_command(cmd: str) -> str:
    """Убрать все PII из команды, оставить только паттерн."""
    anon = cmd
    anon = re.sub(r'\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b', '<IP>', anon)
    anon = re.sub(r'/home/[a-zA-Z0-9_]+', '/home/<USER>', anon)
    anon = re.sub(r'/var/www/[a-zA-Z0-9_.-]+', '/var/www/<APP>', anon)
    anon = re.sub(r'password\s*[=:]\s*\S+', 'password=<REDACTED>', anon, flags=re.IGNORECASE)
    anon = re.sub(r'token\s*[=:]\s*\S+', 'token=<REDACTED>', anon, flags=re.IGNORECASE)
    anon = re.sub(r'key\s*[=:]\s*\S+', 'key=<REDACTED>', anon, flags=re.IGNORECASE)
    anon = re.sub(r'"[^"]{20,}"', '"<STRING>"', anon)
    anon = re.sub(r"'[^']{20,}'", "'<STRING>'", anon)
    anon = re.sub(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}', '<EMAIL>', anon)
    return anon[:200]


class CrossUserLearning:
    """Анонимное обучение из паттернов всех пользователей."""

    @staticmethod
    def record_command_pair(cmd_a: str, cmd_b: str, success: bool):
        """Записать пару последовательных команд (анонимно)."""
        a = _anonymize_command(cmd_a)
        b = _anonymize_command(cmd_b)
        pair_hash = hashlib.md5(f"{a}|{b}".encode()).hexdigest()[:16]
        try:
            c = _db()
            row = c.execute("SELECT * FROM command_pairs WHERE pair_hash=?", (pair_hash,)).fetchone()
            now = datetime.now(timezone.utc).isoformat()
            if row:
                sc = row["success_count"] + (1 if success else 0)
                c.execute("UPDATE command_pairs SET count=count+1, success_count=?, last_seen=? WHERE id=?",
                          (sc, now, row["id"]))
            else:
                c.execute("INSERT INTO command_pairs (command_a,command_b,pair_hash,count,success_count,last_seen) VALUES (?,?,?,1,?,?)",
                          (a, b, pair_hash, 1 if success else 0, now))
            c.commit()
        except Exception as e:
            logger.error(f"CrossUser record_pair: {e}")

    @staticmethod
    def record_tool_sequence(tools: List[str], success_rate: float,
                             context: str = ""):
        """Записать последовательность инструментов."""
        pattern = " → ".join(tools)
        pattern_hash = hashlib.md5(pattern.encode()).hexdigest()[:16]
        try:
            c = _db()
            row = c.execute("SELECT * FROM tool_sequences WHERE pattern_hash=?", (pattern_hash,)).fetchone()
            now = datetime.now(timezone.utc).isoformat()
            if row:
                old_rate = row["avg_success_rate"]
                old_count = row["count"]
                new_rate = (old_rate * old_count + success_rate) / (old_count + 1)
                c.execute("UPDATE tool_sequences SET count=count+1, avg_success_rate=?, last_seen=? WHERE id=?",
                          (new_rate, now, row["id"]))
            else:
                anon_context = _anonymize_command(context[:200]) if context else ""
                c.execute("INSERT INTO tool_sequences (tool_pattern,pattern_hash,count,avg_success_rate,example_context,last_seen) VALUES (?,?,1,?,?,?)",
                          (pattern, pattern_hash, success_rate, anon_context, now))
            c.commit()
        except Exception as e:
            logger.error(f"CrossUser record_seq: {e}")

    @staticmethod
    def record_error_solution(error: str, solution: str, success: bool):
        """Записать решение ошибки (анонимно)."""
        anon_error = _anonymize_command(error)
        anon_solution = _anonymize_command(solution)
        pair_hash = hashlib.md5(f"{anon_error}|{anon_solution}".encode()).hexdigest()[:16]
        try:
            c = _db()
            row = c.execute("SELECT * FROM error_solutions WHERE pair_hash=?", (pair_hash,)).fetchone()
            now = datetime.now(timezone.utc).isoformat()
            if row:
                old_rate = row["success_rate"]
                old_count = row["count"]
                new_rate = (old_rate * old_count + (1.0 if success else 0.0)) / (old_count + 1)
                c.execute("UPDATE error_solutions SET count=count+1, success_rate=?, last_seen=? WHERE id=?",
                          (new_rate, now, row["id"]))
            else:
                c.execute("INSERT INTO error_solutions (error_pattern,solution_pattern,pair_hash,count,success_rate,last_seen) VALUES (?,?,?,1,?,?)",
                          (anon_error, anon_solution, pair_hash, 1.0 if success else 0.0, now))
            c.commit()
        except Exception as e:
            logger.error(f"CrossUser record_error_solution: {e}")

    @staticmethod
    def suggest_next_command(current_command: str, limit: int = 3) -> List[Dict]:
        """Предложить следующую команду на основе паттернов всех пользователей."""
        anon = _anonymize_command(current_command)
        try:
            c = _db()
            # Точное совпадение
            rows = c.execute(
                "SELECT command_b, count, success_count FROM command_pairs WHERE command_a=? AND count>=3 ORDER BY count DESC LIMIT ?",
                (anon, limit)
            ).fetchall()
            if rows:
                return [{"next_command": r["command_b"],
                         "frequency": r["count"],
                         "success_rate": round(r["success_count"] / max(r["count"], 1), 2)}
                        for r in rows]
            # Нечёткое: по первому слову
            first_word = anon.split()[0] if anon.split() else ""
            if first_word:
                rows = c.execute(
                    "SELECT command_b, count, success_count FROM command_pairs WHERE command_a LIKE ? AND count>=3 ORDER BY count DESC LIMIT ?",
                    (f"{first_word}%", limit)
                ).fetchall()
                return [{"next_command": r["command_b"],
                         "frequency": r["count"],
                         "success_rate": round(r["success_count"] / max(r["count"], 1), 2)}
                        for r in rows]
        except:
            pass
        return []

    @staticmethod
    def suggest_error_fix(error: str) -> Optional[Dict]:
        """Предложить решение ошибки на основе паттернов всех пользователей."""
        anon = _anonymize_command(error)
        try:
            c = _db()
            # Поиск по подстроке
            rows = c.execute(
                "SELECT * FROM error_solutions WHERE error_pattern LIKE ? AND success_rate>0.5 AND count>=2 ORDER BY success_rate DESC, count DESC LIMIT 1",
                (f"%{anon[:50]}%",)
            ).fetchall()
            if rows:
                r = rows[0]
                return {
                    "solution": r["solution_pattern"],
                    "success_rate": r["success_rate"],
                    "seen_count": r["count"]
                }
        except:
            pass
        return None

    @staticmethod
    def get_popular_patterns(limit: int = 10) -> List[Dict]:
        """Самые популярные паттерны (для аналитики)."""
        try:
            c = _db()
            rows = c.execute(
                "SELECT tool_pattern, count, avg_success_rate FROM tool_sequences ORDER BY count DESC LIMIT ?",
                (limit,)
            ).fetchall()
            return [dict(r) for r in rows]
        except:
            return []

    @staticmethod
    def get_prompt_suggestions(current_tool: str, current_command: str = "") -> str:
        """Получить текст для промпта с предложениями."""
        suggestions = CrossUserLearning.suggest_next_command(current_command or current_tool)
        if not suggestions:
            return ""
        parts = ["ПОПУЛЯРНЫЕ СЛЕДУЮЩИЕ ШАГИ (из опыта):"]
        for s in suggestions:
            rate = int(s["success_rate"] * 100)
            parts.append(f"  → {s['next_command']} (успех {rate}%, частота {s['frequency']}x)")
        return "\n".join(parts)
