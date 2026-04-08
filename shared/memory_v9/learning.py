"""
Tool Learning + Error Patterns + Self-Reflection + Success Replay.
Агент учится из своего опыта: запоминает рабочие команды, решения ошибок,
и повторяет успешные эпизоды при похожих задачах.
"""
import sqlite3, json, os, threading, logging, re, hashlib
from datetime import datetime, timezone
from typing import List, Dict, Optional, Tuple
from .config import MemoryConfig

logger = logging.getLogger("memory.learning")
_local = threading.local()

def _conn():
    if not hasattr(_local, "c") or _local.c is None:
        os.makedirs(os.path.dirname(MemoryConfig.PATTERNS_DB), exist_ok=True)
        _local.c = sqlite3.connect(MemoryConfig.PATTERNS_DB, timeout=15)
        _local.c.execute("PRAGMA journal_mode=WAL")
        _local.c.row_factory = sqlite3.Row
        _local.c.executescript("""
            CREATE TABLE IF NOT EXISTS tool_skills (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                host TEXT, os_type TEXT, tool_name TEXT,
                command_pattern TEXT, success_count INTEGER DEFAULT 0,
                fail_count INTEGER DEFAULT 0, last_used TEXT,
                notes TEXT DEFAULT ''
            );
            CREATE INDEX IF NOT EXISTS idx_skill_host ON tool_skills(host);
            CREATE TABLE IF NOT EXISTS error_patterns (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                error_signature TEXT UNIQUE, error_message TEXT,
                tool_name TEXT, fix_tool TEXT, fix_command TEXT,
                fix_description TEXT, occurrences INTEGER DEFAULT 1,
                success_rate REAL DEFAULT 0, last_seen TEXT
            );
            CREATE TABLE IF NOT EXISTS episodes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT, chat_id TEXT,
                task TEXT, task_hash TEXT,
                plan TEXT, actions TEXT, result TEXT,
                success INTEGER, duration_sec REAL,
                error_summary TEXT, lessons TEXT,
                timestamp TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_ep_user ON episodes(user_id);
            CREATE INDEX IF NOT EXISTS idx_ep_hash ON episodes(task_hash);
            CREATE TABLE IF NOT EXISTS reflections (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id TEXT, user_id TEXT,
                what_worked TEXT, what_failed TEXT,
                improvements TEXT, timestamp TEXT
            );
        """)
        _local.c.commit()
    return _local.c


class ToolLearning:
    """Запоминает какие команды работают на каких серверах."""

    @staticmethod
    def record(host: str, tool_name: str, command: str, success: bool,
               os_type: str = "", notes: str = ""):
        try:
            c = _conn()
            pattern = ToolLearning._normalize_command(command)
            row = c.execute("SELECT * FROM tool_skills WHERE host=? AND command_pattern=?",
                            (host, pattern)).fetchone()
            now = datetime.now(timezone.utc).isoformat()
            if row:
                if success:
                    c.execute("UPDATE tool_skills SET success_count=success_count+1, last_used=? WHERE id=?",
                              (now, row["id"]))
                else:
                    c.execute("UPDATE tool_skills SET fail_count=fail_count+1, last_used=? WHERE id=?",
                              (now, row["id"]))
            else:
                c.execute("INSERT INTO tool_skills (host,os_type,tool_name,command_pattern,success_count,fail_count,last_used,notes) VALUES (?,?,?,?,?,?,?,?)",
                          (host, os_type, tool_name, pattern, 1 if success else 0, 0 if success else 1, now, notes))
            c.commit()
        except Exception as e:
            logger.error(f"ToolLearning record: {e}")

    @staticmethod
    def get_skills(host: str, limit: int = 10) -> List[Dict]:
        """Получить навыки для сервера (для инъекции в промпт)."""
        try:
            c = _conn()
            rows = c.execute(
                "SELECT * FROM tool_skills WHERE host=? AND success_count>=? ORDER BY success_count DESC LIMIT ?",
                (host, MemoryConfig.TOOL_LEARN_MIN_USES, limit)
            ).fetchall()
            return [dict(r) for r in rows]
        except: return []

    @staticmethod
    def get_server_profile(host: str) -> str:
        """Текст для промпта: что мы знаем об этом сервере."""
        skills = ToolLearning.get_skills(host)
        if not skills: return ""
        parts = [f"НАВЫКИ ДЛЯ СЕРВЕРА {host}:"]
        os_type = skills[0].get("os_type", "") if skills else ""
        if os_type: parts.append(f"  ОС: {os_type}")
        for s in skills[:8]:
            parts.append(f"  ✅ {s['command_pattern']} (успешно {s['success_count']}x)")
        return "\n".join(parts)

    @staticmethod
    def _normalize_command(cmd: str) -> str:
        """Нормализовать команду для группировки (убрать пути, переменные)."""
        cmd = re.sub(r'/[a-zA-Z0-9/._-]+', '<PATH>', cmd)
        cmd = re.sub(r'"[^"]*"', '<STR>', cmd)
        cmd = re.sub(r"'[^']*'", '<STR>', cmd)
        return cmd[:200]


class ErrorPatterns:
    """База ошибок и их решений. Растёт из опыта."""

    @staticmethod
    def record_error(error_msg: str, tool_name: str):
        """Записать ошибку (без решения пока)."""
        try:
            sig = ErrorPatterns._signature(error_msg)
            c = _conn()
            row = c.execute("SELECT * FROM error_patterns WHERE error_signature=?", (sig,)).fetchone()
            now = datetime.now(timezone.utc).isoformat()
            if row:
                c.execute("UPDATE error_patterns SET occurrences=occurrences+1, last_seen=? WHERE id=?", (now, row["id"]))
            else:
                c.execute("INSERT INTO error_patterns (error_signature,error_message,tool_name,last_seen) VALUES (?,?,?,?)",
                          (sig, error_msg[:500], tool_name, now))
            c.commit()
        except Exception as e:
            logger.error(f"ErrorPatterns record: {e}")

    @staticmethod
    def record_fix(error_msg: str, fix_tool: str, fix_command: str,
                   fix_description: str, success: bool):
        """Записать решение ошибки."""
        try:
            sig = ErrorPatterns._signature(error_msg)
            c = _conn()
            now = datetime.now(timezone.utc).isoformat()
            row = c.execute("SELECT * FROM error_patterns WHERE error_signature=?", (sig,)).fetchone()
            if row:
                old_rate = row["success_rate"] or 0
                new_rate = (old_rate * row["occurrences"] + (1 if success else 0)) / (row["occurrences"] + 1)
                c.execute("UPDATE error_patterns SET fix_tool=?,fix_command=?,fix_description=?,success_rate=?,last_seen=? WHERE id=?",
                          (fix_tool, fix_command[:500], fix_description[:200], new_rate, now, row["id"]))
            else:
                c.execute("INSERT INTO error_patterns (error_signature,error_message,tool_name,fix_tool,fix_command,fix_description,success_rate,last_seen) VALUES (?,?,?,?,?,?,?,?)",
                          (sig, error_msg[:500], "", fix_tool, fix_command[:500], fix_description[:200], 1.0 if success else 0.0, now))
            c.commit()
        except Exception as e:
            logger.error(f"ErrorPatterns record_fix: {e}")

    @staticmethod
    def find_fix(error_msg: str) -> Optional[Dict]:
        """Найти известное решение ошибки."""
        try:
            sig = ErrorPatterns._signature(error_msg)
            c = _conn()
            row = c.execute("SELECT * FROM error_patterns WHERE error_signature=? AND fix_command IS NOT NULL AND success_rate>0.3",
                            (sig,)).fetchone()
            return dict(row) if row else None
        except: return None

    @staticmethod
    def get_common_errors(limit: int = 10) -> List[Dict]:
        try:
            c = _conn()
            rows = c.execute("SELECT * FROM error_patterns WHERE occurrences>=? ORDER BY occurrences DESC LIMIT ?",
                             (MemoryConfig.ERROR_PATTERN_MIN_OCCURRENCES, limit)).fetchall()
            return [dict(r) for r in rows]
        except: return []

    @staticmethod
    def _signature(error_msg: str) -> str:
        normalized = re.sub(r'[0-9]+', 'N', error_msg[:200])
        normalized = re.sub(r'/[a-zA-Z0-9/._-]+', '<PATH>', normalized)
        return hashlib.md5(normalized.encode()).hexdigest()[:16]


class EpisodicReplay:
    """Полные записи задач: задача → план → действия → результат."""

    @staticmethod
    def store(user_id: str, chat_id: str, task: str, plan: str,
              actions: List[Dict], result: str, success: bool,
              duration: float = 0, errors: str = "", lessons: str = ""):
        try:
            c = _conn()
            task_hash = hashlib.md5(task[:200].lower().encode()).hexdigest()[:12]
            c.execute(
                "INSERT INTO episodes (user_id,chat_id,task,task_hash,plan,actions,result,success,duration_sec,error_summary,lessons,timestamp) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (user_id, chat_id, task[:2000], task_hash, plan[:2000],
                 json.dumps(actions[:50], ensure_ascii=False), result[:2000],
                 1 if success else 0, duration, errors[:1000], lessons[:1000],
                 datetime.now(timezone.utc).isoformat())
            )
            c.commit()
        except Exception as e:
            logger.error(f"EpisodicReplay store: {e}")

    @staticmethod
    def find_similar(task: str, user_id: str = None, limit: int = 3) -> List[Dict]:
        """Найти похожие прошлые задачи (для Success Replay)."""
        try:
            c = _conn()
            keywords = [w for w in task.lower().split() if len(w) > 3][:5]
            if not keywords: return []
            conditions = " OR ".join(f"task LIKE '%{kw}%'" for kw in keywords)
            sql = f"SELECT * FROM episodes WHERE ({conditions}) AND success=1"
            if user_id: sql += f" AND user_id='{user_id}'"
            sql += f" ORDER BY timestamp DESC LIMIT {limit}"
            rows = c.execute(sql).fetchall()
            return [dict(r) for r in rows]
        except: return []

    @staticmethod
    def get_success_replay_prompt(task: str, user_id: str = None) -> str:
        """Получить текст для промпта из успешных эпизодов."""
        episodes = EpisodicReplay.find_similar(task, user_id, limit=2)
        if not episodes: return ""
        parts = ["УСПЕШНЫЕ ЭПИЗОДЫ (повтори подход):"]
        for ep in episodes:
            parts.append(f"  Задача: {ep['task'][:200]}")
            try:
                actions = json.loads(ep.get("actions", "[]"))
                steps = [f"    {a.get('tool','')}: {'✅' if a.get('ok') else '❌'}" for a in actions[:8]]
                parts.extend(steps)
            except: pass
            if ep.get("lessons"): parts.append(f"  Урок: {ep['lessons'][:200]}")
        return "\n".join(parts)


class SelfReflection:
    """После задачи: что получилось, что нет, что улучшить."""

    @staticmethod
    def reflect(chat_id: str, user_id: str, call_llm, actions: List[Dict],
                task: str, result: str) -> Optional[Dict]:
        """Провести self-reflection через LLM."""
        if not call_llm: return None
        try:
            actions_text = "\n".join(
                f"{'✅' if a.get('ok') else '❌'} {a.get('tool','')}: {a.get('s','')[:80]}"
                for a in actions[-15:]
            )
            resp = call_llm([
                {"role": "system", "content": "Проведи краткий анализ выполненной задачи. Ответь JSON: {\"worked\":\"что сработало\",\"failed\":\"что нет\",\"improve\":\"что улучшить в следующий раз\"}"},
                {"role": "user", "content": f"Задача: {task[:500]}\nДействия:\n{actions_text}\nРезультат: {result[:300]}"}
            ])
            resp = resp.strip()
            if resp.startswith("```"): resp = resp.split("\n",1)[1].rsplit("```",1)[0]
            data = json.loads(resp)
            c = _conn()
            c.execute("INSERT INTO reflections (chat_id,user_id,what_worked,what_failed,improvements,timestamp) VALUES (?,?,?,?,?,?)",
                      (chat_id, user_id, data.get("worked","")[:500], data.get("failed","")[:500],
                       data.get("improve","")[:500], datetime.now(timezone.utc).isoformat()))
            c.commit()
            return data
        except Exception as e:
            logger.warning(f"SelfReflection: {e}"); return None

    @staticmethod
    def get_lessons(user_id: str, limit: int = 5) -> List[Dict]:
        try:
            c = _conn()
            rows = c.execute("SELECT * FROM reflections WHERE user_id=? ORDER BY id DESC LIMIT ?",
                             (user_id, limit)).fetchall()
            return [dict(r) for r in rows]
        except: return []
