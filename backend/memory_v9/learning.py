"""
Tool Learning + Error Patterns + Self-Reflection + Success Replay (Episodic).
"""
import sqlite3, json, os, threading, logging, re, hashlib
from datetime import datetime, timezone
from typing import List, Dict, Optional
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
        try:
            c = _conn()
            rows = c.execute(
                "SELECT * FROM tool_skills WHERE host=? AND success_count>=? ORDER BY success_count DESC LIMIT ?",
                (host, MemoryConfig.TOOL_LEARN_MIN_USES, limit)
            ).fetchall()
            return [dict(r) for r in rows]
        except:
            return []

    @staticmethod
    def get_server_profile(host: str) -> str:
        skills = ToolLearning.get_skills(host)
        if not skills:
            return ""
        parts = [f"НАВЫКИ ДЛЯ СЕРВЕРА {host}:"]
        for s in skills[:8]:
            parts.append(f"  ✅ {s['command_pattern']} (успешно {s['success_count']}x)")
        return "\n".join(parts)

    @staticmethod
    def _normalize_command(cmd: str) -> str:
        cmd = re.sub(r'/[a-zA-Z0-9/._-]+', '<PATH>', cmd)
        cmd = re.sub(r'"[^"]*"', '<STR>', cmd)
        cmd = re.sub(r"'[^']*'", '<STR>', cmd)
        return cmd[:200]


class ErrorPatterns:
    @staticmethod
    def record_error(error_msg: str, tool_name: str = ""):
        try:
            sig = hashlib.md5(error_msg[:100].encode()).hexdigest()[:12]
            c = _conn()
            row = c.execute("SELECT * FROM error_patterns WHERE error_signature=?", (sig,)).fetchone()
            now = datetime.now(timezone.utc).isoformat()
            if row:
                c.execute("UPDATE error_patterns SET occurrences=occurrences+1, last_seen=? WHERE id=?",
                          (now, row["id"]))
            else:
                c.execute("INSERT INTO error_patterns (error_signature,error_message,tool_name,last_seen) VALUES (?,?,?,?)",
                          (sig, error_msg[:500], tool_name, now))
            c.commit()
        except Exception as e:
            logger.error(f"ErrorPatterns record: {e}")

    @staticmethod
    def find_fix(error_msg: str) -> Optional[Dict]:
        try:
            c = _conn()
            rows = c.execute(
                "SELECT * FROM error_patterns WHERE fix_command IS NOT NULL AND success_rate>0.5 ORDER BY success_rate DESC LIMIT 5"
            ).fetchall()
            error_lower = error_msg.lower()
            for row in rows:
                if any(w in error_lower for w in row["error_message"].lower().split()[:5]):
                    return dict(row)
        except:
            pass
        return None


class EpisodicReplay:
    @staticmethod
    def store(user_id: str, chat_id: str, task: str, plan: str,
              actions: List[Dict], result: str, success: bool,
              duration: float = 0):
        try:
            task_hash = hashlib.md5(task[:200].encode()).hexdigest()[:12]
            c = _conn()
            c.execute("""
                INSERT INTO episodes (user_id,chat_id,task,task_hash,plan,actions,result,success,duration_sec,timestamp)
                VALUES (?,?,?,?,?,?,?,?,?,?)
            """, (user_id, chat_id, task[:2000], task_hash,
                  plan[:2000], json.dumps(actions, ensure_ascii=False)[:3000],
                  result[:2000], 1 if success else 0, duration,
                  datetime.now(timezone.utc).isoformat()))
            c.commit()
        except Exception as e:
            logger.error(f"EpisodicReplay store: {e}")

    @staticmethod
    def get_success_replay_prompt(task: str, user_id: str = None) -> str:
        try:
            c = _conn()
            task_words = task.lower().split()[:10]
            rows = c.execute(
                "SELECT * FROM episodes WHERE success=1 ORDER BY id DESC LIMIT 50"
            ).fetchall()
            best = None
            best_score = 0
            for row in rows:
                if user_id and row["user_id"] != user_id:
                    continue
                row_words = set(row["task"].lower().split())
                score = sum(1 for w in task_words if w in row_words)
                if score > best_score:
                    best_score = score
                    best = row
            if best and best_score >= 2:
                actions = json.loads(best["actions"] or "[]")
                actions_text = ", ".join(a.get("tool", "") for a in actions[:5])
                return f"ПОХОЖАЯ УСПЕШНАЯ ЗАДАЧА:\n  Задача: {best['task'][:200]}\n  Действия: {actions_text}\n  Результат: {best['result'][:200]}"
        except:
            pass
        return ""


class SelfReflection:
    @staticmethod
    def reflect(chat_id: str, user_id: str, call_llm,
                actions: List[Dict], task: str, result: str) -> Optional[Dict]:
        if not call_llm or not actions:
            return None
        try:
            actions_text = "\n".join(
                f"{'✅' if a.get('ok') else '❌'} {a.get('tool','')}: {a.get('s','')[:100]}"
                for a in actions
            )
            resp = call_llm([
                {"role": "system", "content": "Проанализируй выполнение задачи. JSON: {\"worked\":\"что сработало\",\"failed\":\"что не сработало\",\"improve\":\"как улучшить\"}. Без markdown."},
                {"role": "user", "content": f"Задача: {task[:500]}\nДействия:\n{actions_text}\nРезультат: {result[:500]}"}
            ])
            resp = resp.strip()
            if resp.startswith("```"):
                resp = resp.split("\n", 1)[1].rsplit("```", 1)[0]
            reflection = json.loads(resp)
            c = _conn()
            c.execute("INSERT INTO reflections (chat_id,user_id,what_worked,what_failed,improvements,timestamp) VALUES (?,?,?,?,?,?)",
                      (chat_id, user_id, reflection.get("worked","")[:500],
                       reflection.get("failed","")[:500], reflection.get("improve","")[:500],
                       datetime.now(timezone.utc).isoformat()))
            c.commit()
            return reflection
        except:
            return None
