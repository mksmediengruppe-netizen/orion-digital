"""
Dynamic Tool Creation — агент сам создаёт инструменты из повторяющихся паттернов.

Как работает:
1. PatternDetector анализирует EpisodicReplay и tool_skills
2. Находит последовательности которые повторяются 3+ раз
3. LLM генерирует bash/python скрипт из паттерна
4. Скрипт проходит security review (whitelist/blacklist)
5. Регистрируется как новый tool в TOOLS_SCHEMA
6. Агент может вызвать его как обычный инструмент

Пример:
  Агент 5 раз деплоил Flask одинаково:
    apt install python3-venv → python3 -m venv /app/venv → pip install flask gunicorn →
    создал systemd сервис → systemctl enable → nginx конфиг → certbot
  
  Система создаёт tool "deploy_flask" который делает всё это одной командой.
"""

import os, json, re, hashlib, logging, subprocess, sqlite3, threading
from datetime import datetime, timezone
from typing import List, Dict, Optional, Tuple
from .config import MemoryConfig

logger = logging.getLogger("memory.dynamic_tools")
_local = threading.local()

# ── Security ──

COMMAND_BLACKLIST = [
    r"rm\s+-rf\s+/[^a-z]",           # rm -rf / (корень)
    r"rm\s+-rf\s+/home\b",
    r"rm\s+-rf\s+/var\b",
    r"rm\s+-rf\s+/etc\b",
    r"mkfs\b",                         # форматирование дисков
    r"dd\s+if=",                       # dd запись на диск
    r":\(\)\s*\{",                     # fork bomb
    r"chmod\s+777\s+/",               # chmod 777 на корень
    r"curl.*\|\s*bash",               # pipe curl to bash
    r"wget.*\|\s*bash",
    r"eval\s*\(",                      # eval в Python
    r"exec\s*\(",
    r"__import__",
    r"os\.system",
    r"subprocess\.call.*shell=True",
]

COMMAND_WHITELIST_PREFIXES = [
    "apt-get", "apt", "yum", "dnf", "pip", "pip3", "npm", "yarn",
    "systemctl", "service", "nginx", "docker", "docker-compose",
    "python3", "node", "git", "curl", "wget",
    "mkdir", "cp", "mv", "chmod", "chown", "ln",
    "cat", "echo", "tee", "sed", "grep", "awk",
    "certbot", "ufw", "iptables",
]


def _db():
    if not hasattr(_local, "c") or _local.c is None:
        db_path = os.path.join(MemoryConfig.DATA_DIR, "dynamic_tools.db")
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        _local.c = sqlite3.connect(db_path, timeout=15)
        _local.c.execute("PRAGMA journal_mode=WAL")
        _local.c.row_factory = sqlite3.Row
        _local.c.executescript("""
            CREATE TABLE IF NOT EXISTS generated_tools (
                id TEXT PRIMARY KEY,
                name TEXT UNIQUE NOT NULL,
                description TEXT,
                script_type TEXT DEFAULT 'bash',
                script_content TEXT NOT NULL,
                parameters TEXT DEFAULT '{}',
                source_pattern TEXT,
                usage_count INTEGER DEFAULT 0,
                success_count INTEGER DEFAULT 0,
                is_approved INTEGER DEFAULT 0,
                is_active INTEGER DEFAULT 1,
                created_by TEXT,
                created_at TEXT,
                updated_at TEXT
            );
            CREATE TABLE IF NOT EXISTS action_sequences (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT,
                sequence_hash TEXT,
                actions TEXT,
                count INTEGER DEFAULT 1,
                last_seen TEXT
            );
            CREATE UNIQUE INDEX IF NOT EXISTS idx_seq_hash ON action_sequences(sequence_hash, user_id);
        """)
        _local.c.commit()
    return _local.c


class SecurityReview:
    """Проверка безопасности сгенерированных скриптов."""

    @staticmethod
    def check(script: str, script_type: str = "bash") -> Tuple[bool, List[str]]:
        """Проверить скрипт. Возвращает (безопасен, [список_проблем])."""
        issues = []

        for pattern in COMMAND_BLACKLIST:
            if re.search(pattern, script, re.IGNORECASE):
                issues.append(f"Запрещённая команда: {pattern}")

        if script_type == "bash":
            lines = script.split("\n")
            for i, line in enumerate(lines):
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                # Проверить что команда в whitelist
                first_word = line.split()[0] if line.split() else ""
                # Убрать sudo prefix
                if first_word == "sudo" and len(line.split()) > 1:
                    first_word = line.split()[1]
                if first_word and not any(first_word.startswith(w) for w in COMMAND_WHITELIST_PREFIXES):
                    # Допускаем переменные, условия, пути
                    if not first_word.startswith(("$", "if", "then", "else", "fi", "for", "do", "done", "echo", "export", "source", ".", "/")):
                        issues.append(f"Строка {i+1}: неизвестная команда '{first_word}'")

        elif script_type == "python":
            for pattern in [r"import\s+os", r"import\s+subprocess", r"import\s+shutil",
                            r"open\s*\(.*/etc", r"socket\.", r"__import__"]:
                if re.search(pattern, script):
                    issues.append(f"Небезопасный import/операция: {pattern}")

        return len(issues) == 0, issues


class PatternDetector:
    """Находит повторяющиеся последовательности действий."""

    MIN_SEQUENCE_LENGTH = 3
    MIN_OCCURRENCES = 3

    @staticmethod
    def record_sequence(user_id: str, actions: List[Dict]):
        """Записать последовательность действий для анализа."""
        if len(actions) < PatternDetector.MIN_SEQUENCE_LENGTH:
            return

        # Извлечь паттерн: только tool_name + нормализованные аргументы
        pattern = []
        for a in actions:
            tool = a.get("tool", "")
            if tool in ("task_complete", "update_scratchpad", "recall_memory"):
                continue
            pattern.append(tool)

        if len(pattern) < PatternDetector.MIN_SEQUENCE_LENGTH:
            return

        # Скользящее окно по 3-5 действий
        for window_size in range(3, min(6, len(pattern) + 1)):
            for i in range(len(pattern) - window_size + 1):
                seq = pattern[i:i + window_size]
                seq_hash = hashlib.md5("|".join(seq).encode()).hexdigest()[:12]

                try:
                    c = _db()
                    row = c.execute("SELECT * FROM action_sequences WHERE sequence_hash=? AND user_id=?",
                                    (seq_hash, user_id)).fetchone()
                    now = datetime.now(timezone.utc).isoformat()
                    if row:
                        c.execute("UPDATE action_sequences SET count=count+1, last_seen=? WHERE id=?",
                                  (now, row["id"]))
                    else:
                        c.execute("INSERT INTO action_sequences (user_id,sequence_hash,actions,count,last_seen) VALUES (?,?,?,1,?)",
                                  (user_id, seq_hash, json.dumps(seq), now))
                    c.commit()
                except Exception as e:
                    logger.error(f"PatternDetector record: {e}")

    @staticmethod
    def get_frequent_patterns(user_id: str, min_count: int = None) -> List[Dict]:
        """Получить часто повторяющиеся паттерны."""
        min_count = min_count or PatternDetector.MIN_OCCURRENCES
        try:
            c = _db()
            rows = c.execute(
                "SELECT * FROM action_sequences WHERE user_id=? AND count>=? ORDER BY count DESC LIMIT 20",
                (user_id, min_count)
            ).fetchall()
            return [dict(r) for r in rows]
        except:
            return []


class ToolGenerator:
    """Генерирует скрипты из паттернов через LLM."""

    @staticmethod
    def generate(pattern: List[str], examples: List[Dict],
                 call_llm, user_id: str) -> Optional[Dict]:
        """
        Сгенерировать tool из паттерна.
        
        pattern: ["ssh_execute", "file_write", "ssh_execute"]
        examples: конкретные вызовы с аргументами
        """
        if not call_llm:
            return None

        try:
            examples_text = "\n".join(
                f"  {i+1}. {e.get('tool','')}: {json.dumps(e.get('args',{}), ensure_ascii=False)[:200]}"
                for i, e in enumerate(examples[:10])
            )

            resp = call_llm([
                {"role": "system", "content": """Ты генератор инструментов. На основе повторяющихся действий создай bash-скрипт.

Ответь СТРОГО в JSON:
{
  "name": "deploy_flask",
  "description": "Деплой Flask приложения на сервер",
  "script": "#!/bin/bash\\nset -euo pipefail\\n...",
  "parameters": [{"name": "host", "description": "IP сервера", "required": true}]
}

Правила для скрипта:
- Начинай с #!/bin/bash и set -euo pipefail
- Используй переменные для параметров: $1, $2 или named args
- Добавляй проверки ошибок
- Логируй действия через echo
- НЕ используй rm -rf на системные директории"""},
                {"role": "user", "content": f"Паттерн: {' → '.join(pattern)}\n\nПримеры вызовов:\n{examples_text}"}
            ])

            resp = resp.strip()
            if resp.startswith("```"):
                resp = resp.split("\n", 1)[1].rsplit("```", 1)[0]

            data = json.loads(resp)

            # Security review
            script = data.get("script", "")
            is_safe, issues = SecurityReview.check(script, "bash")

            if not is_safe:
                logger.warning(f"Generated tool '{data.get('name','')}' failed security: {issues}")
                return None

            # Сохранить
            tool_id = hashlib.md5(f"{data['name']}:{user_id}".encode()).hexdigest()[:12]
            c = _db()
            now = datetime.now(timezone.utc).isoformat()
            c.execute("""
                INSERT OR REPLACE INTO generated_tools 
                (id, name, description, script_type, script_content, parameters, 
                 source_pattern, is_approved, created_by, created_at, updated_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?)
            """, (tool_id, data["name"], data.get("description", ""),
                  "bash", script,
                  json.dumps(data.get("parameters", []), ensure_ascii=False),
                  json.dumps(pattern), 0, user_id, now, now))
            c.commit()

            logger.info(f"Generated tool: {data['name']} (awaiting approval)")
            return {
                "id": tool_id,
                "name": data["name"],
                "description": data.get("description", ""),
                "script": script,
                "parameters": data.get("parameters", []),
                "approved": False
            }
        except Exception as e:
            logger.error(f"ToolGenerator: {e}")
            return None

    @staticmethod
    def approve(tool_id: str) -> bool:
        """Одобрить сгенерированный tool (админ)."""
        try:
            c = _db()
            c.execute("UPDATE generated_tools SET is_approved=1, updated_at=? WHERE id=?",
                      (datetime.now(timezone.utc).isoformat(), tool_id))
            c.commit()
            return True
        except:
            return False

    @staticmethod
    def get_active_tools(user_id: str = None) -> List[Dict]:
        """Получить все активные (одобренные) кастомные tools."""
        try:
            c = _db()
            sql = "SELECT * FROM generated_tools WHERE is_active=1 AND is_approved=1"
            if user_id:
                sql += f" AND created_by='{user_id}'"
            rows = c.execute(sql).fetchall()
            return [dict(r) for r in rows]
        except:
            return []

    @staticmethod
    def execute(tool_name: str, args: Dict, ssh_executor=None) -> Dict:
        """Выполнить кастомный tool."""
        try:
            c = _db()
            row = c.execute("SELECT * FROM generated_tools WHERE name=? AND is_active=1 AND is_approved=1",
                            (tool_name,)).fetchone()
            if not row:
                return {"success": False, "error": f"Tool '{tool_name}' not found or not approved"}

            script = row["script_content"]
            script_type = row["script_type"]

            # Подставить параметры
            params = json.loads(row["parameters"])
            for p in params:
                pname = p.get("name", "")
                if pname in args:
                    script = script.replace(f"${{{pname}}}", str(args[pname]))
                    script = script.replace(f"${pname}", str(args[pname]))

            # Финальная security check
            is_safe, issues = SecurityReview.check(script, script_type)
            if not is_safe:
                return {"success": False, "error": f"Security check failed: {issues}"}

            # Выполнить
            if ssh_executor and args.get("host"):
                # На удалённом сервере
                result = ssh_executor.execute_command(script, timeout=120)
                success = result.get("success", False)
            else:
                # Локально (с ограничениями)
                try:
                    proc = subprocess.run(
                        ["bash", "-c", script],
                        capture_output=True, text=True, timeout=60,
                        env={**os.environ, "PATH": "/usr/local/bin:/usr/bin:/bin"}
                    )
                    result = {
                        "stdout": proc.stdout[:5000],
                        "stderr": proc.stderr[:2000],
                        "exit_code": proc.returncode
                    }
                    success = proc.returncode == 0
                except subprocess.TimeoutExpired:
                    return {"success": False, "error": "Timeout (60s)"}

            # Обновить статистику
            now = datetime.now(timezone.utc).isoformat()
            if success:
                c.execute("UPDATE generated_tools SET usage_count=usage_count+1, success_count=success_count+1, updated_at=? WHERE name=?",
                          (now, tool_name))
            else:
                c.execute("UPDATE generated_tools SET usage_count=usage_count+1, updated_at=? WHERE name=?",
                          (now, tool_name))
            c.commit()

            return {"success": success, **result, "tool": tool_name}
        except Exception as e:
            return {"success": False, "error": str(e)}

    @staticmethod
    def get_tools_schema(user_id: str = None) -> List[Dict]:
        """Получить TOOLS_SCHEMA для кастомных tools (для добавления в agent)."""
        tools = ToolGenerator.get_active_tools(user_id)
        schema = []
        for t in tools:
            params = json.loads(t.get("parameters", "[]"))
            properties = {}
            required = []
            for p in params:
                properties[p["name"]] = {
                    "type": "string",
                    "description": p.get("description", "")
                }
                if p.get("required"):
                    required.append(p["name"])

            schema.append({
                "type": "function",
                "function": {
                    "name": t["name"],
                    "description": f"[Custom Tool] {t.get('description', '')}",
                    "parameters": {
                        "type": "object",
                        "properties": properties,
                        "required": required
                    }
                }
            })
        return schema


class DynamicToolManager:
    """Верхнеуровневый менеджер: детекция → генерация → регистрация."""

    @staticmethod
    def check_and_generate(user_id: str, actions: List[Dict],
                           call_llm=None) -> Optional[Dict]:
        """
        Проверить есть ли новые паттерны для генерации tools.
        Вызывать после каждого завершённого чата.
        """
        # Записать последовательность
        PatternDetector.record_sequence(user_id, actions)

        # Найти частые паттерны
        patterns = PatternDetector.get_frequent_patterns(user_id)
        if not patterns:
            return None

        # Проверить есть ли уже tool для этого паттерна
        existing = ToolGenerator.get_active_tools(user_id)
        existing_patterns = set()
        for t in existing:
            try:
                sp = json.loads(t.get("source_pattern", "[]"))
                existing_patterns.add("|".join(sp))
            except:
                pass

        # Генерировать для нового паттерна
        for p in patterns:
            try:
                seq = json.loads(p["actions"])
                pattern_key = "|".join(seq)
                if pattern_key in existing_patterns:
                    continue
                if p["count"] >= PatternDetector.MIN_OCCURRENCES and call_llm:
                    tool = ToolGenerator.generate(seq, [], call_llm, user_id)
                    if tool:
                        logger.info(f"New dynamic tool generated: {tool['name']} "
                                    f"(pattern repeated {p['count']}x)")
                        return tool
            except:
                pass

        return None
