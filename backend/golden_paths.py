"""
Golden Paths — Память проверенных решений ORION.

Сохраняет успешные пути решения задач.
При новой задаче ищет похожий путь и предлагает как runbook.
Хранит anti-patterns (ложные успехи) чтобы не повторять ошибки.

Безопасность:
- Секреты (пароли, токены, email, IP) заменяются на плейсхолдеры
- Сохранение только при полном SUCCESS + FinalJudge APPROVED
- Деактивация при 3 провалах подряд
"""

import os
import re
import json
import time
import hashlib
import logging
import sqlite3
import threading
from typing import Dict, List, Optional, Any, NamedTuple
from datetime import datetime, timezone

logger = logging.getLogger("golden_paths")


class GoldenPathMatch(NamedTuple):
    """Результат поиска golden path."""
    path: Dict[str, Any]
    match_score: int  # 0-6, сколько полей fingerprint совпало


class GoldenPathStore:
    """Хранилище проверенных путей решения задач."""

    def __init__(self, db_path=None):
        if db_path is None:
            data_dir = os.environ.get("DATA_DIR", "/var/www/orion/backend/data")
            db_path = os.path.join(data_dir, "golden_paths.db")
        self._db_path = str(db_path)
        os.makedirs(os.path.dirname(self._db_path), exist_ok=True)
        self._init_db()

    # ══════════════════════════════════════════════════════════
    # ИНИЦИАЛИЗАЦИЯ БД
    # ══════════════════════════════════════════════════════════

    def _init_db(self):
        conn = sqlite3.connect(self._db_path)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS golden_paths (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_type TEXT NOT NULL,
                task_signature TEXT,
                task_signature_hash TEXT,
                keywords TEXT,
                environment_fingerprint TEXT,
                steps_json TEXT NOT NULL,
                success_criteria_json TEXT,
                anti_patterns_json TEXT,
                avg_cost REAL DEFAULT 0,
                avg_time REAL DEFAULT 0,
                success_count INTEGER DEFAULT 1,
                fail_count INTEGER DEFAULT 0,
                partial_success_count INTEGER DEFAULT 0,
                used_count INTEGER DEFAULT 0,
                recent_fail_streak INTEGER DEFAULT 0,
                active INTEGER DEFAULT 1,
                last_success_at TEXT,
                last_fail_at TEXT,
                created_at TEXT,
                updated_at TEXT
            );

            CREATE TABLE IF NOT EXISTS anti_patterns (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_type TEXT NOT NULL,
                pattern TEXT NOT NULL,
                description TEXT,
                severity TEXT DEFAULT 'high',
                environment_fingerprint TEXT,
                detected_count INTEGER DEFAULT 1,
                created_at TEXT,
                updated_at TEXT
            );

            CREATE INDEX IF NOT EXISTS idx_gp_task_type ON golden_paths(task_type);
            CREATE INDEX IF NOT EXISTS idx_gp_active ON golden_paths(active);
            CREATE INDEX IF NOT EXISTS idx_gp_hash ON golden_paths(task_signature_hash);
            CREATE INDEX IF NOT EXISTS idx_gp_updated ON golden_paths(updated_at);
            CREATE INDEX IF NOT EXISTS idx_ap_task_type ON anti_patterns(task_type);
        """)
        conn.close()

    def _conn(self):
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        return conn

    # ══════════════════════════════════════════════════════════
    # SANITIZATION — удаление секретов
    # ══════════════════════════════════════════════════════════

    _SECRET_PATTERNS = [
        (r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b', '{{EMAIL}}'),
        (r'\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b', '{{SERVER_IP}}'),
        (r'(?i)(password|pass|pwd|token|key|secret|api_key)\s*[=:]\s*\S+', '{{SECRET}}'),
        (r'-p\S+', '-p{{DB_PASSWORD}}'),
        (r'[0-9a-f]{16,}', '{{TOKEN}}'),
    ]

    def _sanitize_text(self, text: str) -> str:
        """Заменить секреты на плейсхолдеры в любом тексте."""
        if not text:
            return text
        result = str(text)
        for pattern, replacement in self._SECRET_PATTERNS:
            result = re.sub(pattern, replacement, result)
        return result

    def _sanitize_args(self, args: dict) -> dict:
        """Заменить секреты в аргументах на плейсхолдеры."""
        if not args:
            return {}
        sanitized = {}
        for key, value in args.items():
            key_lower = key.lower()
            if any(s in key_lower for s in
                   ["password", "pass", "token", "key", "secret", "api_key", "credential"]):
                sanitized[key] = "{{" + key.upper() + "}}"
            else:
                sanitized[key] = self._sanitize_text(str(value))
        return sanitized

    # ══════════════════════════════════════════════════════════
    # ENVIRONMENT FINGERPRINT
    # ══════════════════════════════════════════════════════════

    def collect_environment_fingerprint(
        self,
        runtime_facts: Dict[str, str] = None,
        ssh_exec=None
    ) -> Dict[str, str]:
        """Собрать fingerprint среды."""
        fp = {
            "platform": "",
            "os_family": "",
            "web_server": "",
            "php_major": "",
            "db": "",
            "install_mode": "",
        }

        # Сначала из runtime facts
        if runtime_facts:
            for k, v in runtime_facts.items():
                if v and k in fp:
                    fp[k] = str(v)

        # Потом дозапросить через SSH если есть
        if ssh_exec:
            def _ssh_with_timeout(cmd, timeout=10):
                """SSH с timeout чтобы не зависнуть."""
                try:
                    result = [None]
                    error = [None]

                    def run():
                        try:
                            result[0] = ssh_exec(cmd)
                        except Exception as e:
                            error[0] = e

                    t = threading.Thread(target=run, daemon=True)
                    t.start()
                    t.join(timeout=timeout)

                    if t.is_alive():
                        logger.warning(f"[GOLDEN_PATHS] SSH timeout for: {cmd[:50]}")
                        return ""
                    if error[0]:
                        return ""
                    return result[0] or ""
                except Exception:
                    return ""

            try:
                if not fp["os_family"]:
                    os_info = _ssh_with_timeout("cat /etc/os-release 2>/dev/null | head -5")
                    if "ubuntu" in os_info.lower():
                        fp["os_family"] = "ubuntu"
                    elif "debian" in os_info.lower():
                        fp["os_family"] = "debian"
                    elif "centos" in os_info.lower() or "rhel" in os_info.lower():
                        fp["os_family"] = "centos"

                if not fp["php_major"]:
                    php_info = _ssh_with_timeout("php -v 2>/dev/null | head -1")
                    match = re.search(r'PHP\s+(\d+\.\d+)', php_info)
                    if match:
                        fp["php_major"] = match.group(1)

                if not fp["web_server"]:
                    nginx = _ssh_with_timeout("nginx -v 2>&1 | head -1")
                    if "nginx" in nginx.lower():
                        fp["web_server"] = "nginx"
                    else:
                        apache = _ssh_with_timeout("apache2 -v 2>/dev/null | head -1")
                        if "apache" in apache.lower():
                            fp["web_server"] = "apache"

                if not fp["db"]:
                    mysql = _ssh_with_timeout("mysql --version 2>/dev/null | head -1")
                    if "mysql" in mysql.lower() or "maria" in mysql.lower():
                        fp["db"] = "mysql"
                    else:
                        pg = _ssh_with_timeout("psql --version 2>/dev/null | head -1")
                        if "psql" in pg.lower():
                            fp["db"] = "postgres"
            except Exception as e:
                logger.warning(f"[GOLDEN_PATHS] SSH fingerprint collection error: {e}")

        return fp

    # ══════════════════════════════════════════════════════════
    # TASK SIGNATURE HASH — для дедупликации
    # ══════════════════════════════════════════════════════════

    def _make_signature_hash(self, task_type: str, env_fp: dict) -> str:
        """Создать нормализованный хэш для дедупликации."""
        sig = json.dumps({
            "task_type": task_type,
            "platform": env_fp.get("platform", ""),
            "os_family": env_fp.get("os_family", ""),
            "web_server": env_fp.get("web_server", ""),
            "php_major": env_fp.get("php_major", ""),
            "db": env_fp.get("db", ""),
            "install_mode": env_fp.get("install_mode", ""),
        }, sort_keys=True)
        return hashlib.sha256(sig.encode()).hexdigest()[:32]

    # ══════════════════════════════════════════════════════════
    # СОХРАНЕНИЕ GOLDEN PATH
    # ══════════════════════════════════════════════════════════

    def save_golden_path(
        self,
        task_type: str,
        task_description: str,
        actions_log: List[Dict],
        environment_fingerprint: Dict = None,
        success_criteria: List[str] = None,
        anti_patterns: List[str] = None,
        total_cost: float = 0,
        total_time: float = 0,
        critical_warnings: List[str] = None,
        final_judge_verdict: str = "",
        task_status: str = "",
        all_success_criteria_passed: bool = False,
    ) -> Optional[int]:
        """Сохранить проверенный путь. Только при полном успехе."""

        # Проверка: сохранять ТОЛЬКО при полном успехе
        if task_status != "SUCCESS":
            logger.info(f"[GOLDEN_PATHS] Skip save: task_status={task_status} (need SUCCESS)")
            return None
        if final_judge_verdict.upper() not in ("APPROVED", "PASSED", "SUCCESS"):
            logger.info(f"[GOLDEN_PATHS] Skip save: judge={final_judge_verdict} (need APPROVED)")
            return None
        if not all_success_criteria_passed:
            logger.info("[GOLDEN_PATHS] Skip save: not all success criteria passed")
            return None
        if critical_warnings:
            logger.info(f"[GOLDEN_PATHS] Skip save: critical warnings: {critical_warnings}")
            return None

        env_fp = environment_fingerprint or {}
        sig_hash = self._make_signature_hash(task_type, env_fp)

        # Дедупликация: если такой же hash уже есть — обновить, не создавать новый
        conn = self._conn()
        try:
            existing = conn.execute(
                "SELECT id, success_count, avg_cost, avg_time FROM golden_paths "
                "WHERE task_signature_hash=? AND active=1",
                (sig_hash,)
            ).fetchone()

            if existing:
                # Обновить существующий
                new_count = existing["success_count"] + 1
                new_avg_cost = (existing["avg_cost"] * existing["success_count"] + total_cost) / new_count
                new_avg_time = (existing["avg_time"] * existing["success_count"] + total_time) / new_count
                conn.execute(
                    "UPDATE golden_paths SET success_count=?, avg_cost=?, avg_time=?, "
                    "recent_fail_streak=0, last_success_at=?, updated_at=? WHERE id=?",
                    (new_count, round(new_avg_cost, 4), round(new_avg_time, 1),
                     datetime.now(timezone.utc).isoformat(),
                     datetime.now(timezone.utc).isoformat(),
                     existing["id"])
                )
                conn.commit()
                logger.info(f"[GOLDEN_PATHS] Updated existing path id={existing['id']} count={new_count}")
                return existing["id"]

            # Создать новый
            # Извлечь шаги из actions_log
            steps = []
            for action in actions_log:
                if action.get("success"):
                    step = {
                        "order": len(steps) + 1,
                        "tool": action.get("tool", "unknown"),
                        "action_template": self._sanitize_args(action.get("args", {})),
                        "description": self._sanitize_text(action.get("description", "")),
                        "expected_outcome": self._sanitize_text(action.get("expected_outcome", "")),
                        "risk_level": self._classify_risk(action.get("tool", "")),
                    }
                    steps.append(step)

            if not steps:
                logger.info("[GOLDEN_PATHS] Skip save: no successful steps")
                return None

            # Извлечь keywords
            keywords = self._extract_keywords(task_description)

            now = datetime.now(timezone.utc).isoformat()
            cursor = conn.execute(
                "INSERT INTO golden_paths "
                "(task_type, task_signature, task_signature_hash, keywords, "
                "environment_fingerprint, steps_json, success_criteria_json, "
                "avg_cost, avg_time, last_success_at, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    task_type,
                    self._sanitize_text(task_description[:500]),
                    sig_hash,
                    json.dumps(keywords, ensure_ascii=False),
                    json.dumps(env_fp, ensure_ascii=False),
                    json.dumps(steps, ensure_ascii=False),
                    json.dumps(success_criteria or [], ensure_ascii=False),
                    round(total_cost, 4),
                    round(total_time, 1),
                    now, now, now,
                )
            )
            conn.commit()
            path_id = cursor.lastrowid
            logger.info(f"[GOLDEN_PATHS] Saved new path id={path_id} type={task_type}")
            return path_id

        finally:
            conn.close()

    def _classify_risk(self, tool_name: str) -> str:
        """Определить уровень риска инструмента."""
        safe = {"web_search", "generate_image", "code_execute", "read_file"}
        guarded = {"file_write", "browser_navigate", "browser_fill", "browser_screenshot"}
        privileged = {"ssh_execute", "browser_js", "deploy_site", "install_bitrix"}
        if tool_name in safe:
            return "safe"
        elif tool_name in guarded:
            return "guarded"
        elif tool_name in privileged:
            return "privileged"
        return "guarded"

    def _extract_keywords(self, text: str) -> List[str]:
        """Извлечь ключевые слова из описания."""
        text = text.lower()
        keywords = set()
        kw_map = {
            "битрикс": "bitrix", "bitrix": "bitrix", "1с-битрикс": "bitrix",
            "лендинг": "landing", "landing": "landing",
            "сайт": "website", "site": "website",
            "деплой": "deploy", "deploy": "deploy",
            "ssh": "ssh", "сервер": "server",
            "nginx": "nginx", "php": "php", "mysql": "mysql",
            "форма": "form", "дизайн": "design",
            "установ": "install", "install": "install",
        }
        for trigger, keyword in kw_map.items():
            if trigger in text:
                keywords.add(keyword)
        return sorted(keywords)

    # ══════════════════════════════════════════════════════════
    # ПОИСК GOLDEN PATH
    # ══════════════════════════════════════════════════════════

    def find_golden_path(
        self,
        task_type: str,
        task_description: str,
        environment: Dict[str, str] = None,
        min_match_score: int = 2,
    ) -> Optional[GoldenPathMatch]:
        """Найти подходящий golden path."""
        conn = self._conn()
        try:
            rows = conn.execute(
                "SELECT * FROM golden_paths WHERE task_type=? AND active=1 "
                "ORDER BY success_count DESC",
                (task_type,)
            ).fetchall()

            if not rows:
                return None

            env = environment or {}
            best_match = None
            best_score = -1

            for row in rows:
                row_dict = dict(row)
                row_dict["steps"] = json.loads(row_dict.get("steps_json", "[]"))
                stored_env = json.loads(row_dict.get("environment_fingerprint", "{}"))

                # Считать match score
                score = 0
                fp_fields = ["os_family", "web_server", "php_major", "db", "install_mode", "platform"]
                for field in fp_fields:
                    if env.get(field) and stored_env.get(field):
                        if env[field] == stored_env[field]:
                            score += 1

                if score >= min_match_score and score > best_score:
                    best_score = score
                    best_match = GoldenPathMatch(path=row_dict, match_score=score)

            return best_match

        finally:
            conn.close()

    # ══════════════════════════════════════════════════════════
    # ANTI-PATTERNS
    # ══════════════════════════════════════════════════════════

    def save_anti_pattern(
        self,
        task_type: str,
        pattern: str,
        description: str,
        severity: str = "high",
        environment_fingerprint: Dict = None,
    ) -> Optional[int]:
        """Сохранить известный ложный/плохой паттерн."""
        conn = self._conn()
        try:
            # Дедупликация
            existing = conn.execute(
                "SELECT id, detected_count FROM anti_patterns "
                "WHERE task_type=? AND pattern=?",
                (task_type, pattern)
            ).fetchone()

            if existing:
                conn.execute(
                    "UPDATE anti_patterns SET detected_count=?, updated_at=? WHERE id=?",
                    (existing["detected_count"] + 1,
                     datetime.now(timezone.utc).isoformat(),
                     existing["id"])
                )
                conn.commit()
                return existing["id"]

            now = datetime.now(timezone.utc).isoformat()
            cursor = conn.execute(
                "INSERT INTO anti_patterns "
                "(task_type, pattern, description, severity, environment_fingerprint, "
                "created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (task_type, pattern, self._sanitize_text(description), severity,
                 json.dumps(environment_fingerprint or {}, ensure_ascii=False),
                 now, now)
            )
            conn.commit()
            return cursor.lastrowid

        finally:
            conn.close()

    # ══════════════════════════════════════════════════════════
    # ЗАПИСЬ ИСХОДА
    # ══════════════════════════════════════════════════════════

    def record_path_outcome(
        self,
        path_id: int,
        success: bool = False,
        partial_success: bool = False,
    ):
        """Записать исход использования golden path."""
        conn = self._conn()
        try:
            now = datetime.now(timezone.utc).isoformat()

            if success:
                conn.execute(
                    "UPDATE golden_paths SET "
                    "success_count = success_count + 1, "
                    "used_count = used_count + 1, "
                    "recent_fail_streak = 0, "
                    "last_success_at = ?, "
                    "updated_at = ? "
                    "WHERE id = ?",
                    (now, now, path_id)
                )
            elif partial_success:
                conn.execute(
                    "UPDATE golden_paths SET "
                    "partial_success_count = partial_success_count + 1, "
                    "used_count = used_count + 1, "
                    "updated_at = ? "
                    "WHERE id = ?",
                    (now, path_id)
                )
            else:
                # Fail
                conn.execute(
                    "UPDATE golden_paths SET "
                    "fail_count = fail_count + 1, "
                    "used_count = used_count + 1, "
                    "recent_fail_streak = recent_fail_streak + 1, "
                    "last_fail_at = ?, "
                    "updated_at = ? "
                    "WHERE id = ?",
                    (now, now, path_id)
                )

                # Проверить деактивацию
                row = conn.execute(
                    "SELECT success_count, fail_count, recent_fail_streak "
                    "FROM golden_paths WHERE id=?",
                    (path_id,)
                ).fetchone()

                if row and self._should_deactivate(dict(row)):
                    conn.execute(
                        "UPDATE golden_paths SET active=0, updated_at=? WHERE id=?",
                        (now, path_id)
                    )
                    logger.warning(f"[GOLDEN_PATHS] Deactivated path id={path_id}")

            conn.commit()

        finally:
            conn.close()

    def _should_deactivate(self, path: dict) -> bool:
        """Определить нужно ли деактивировать path."""
        total = path.get("success_count", 0) + path.get("fail_count", 0)
        if total == 0:
            return False

        success_rate = path.get("success_count", 0) / total

        # Деактивировать если:
        # 1. Success rate < 30%
        if success_rate < 0.3 and total >= 3:
            return True

        # 2. 3+ провала подряд
        if path.get("recent_fail_streak", 0) >= 3:
            return True

        return False

    # ══════════════════════════════════════════════════════════
    # COUNT PATHS
    # ══════════════════════════════════════════════════════════

    def count_paths(self, task_type: str = None) -> int:
        """Подсчитать количество путей в БД."""
        conn = self._conn()
        try:
            if task_type:
                row = conn.execute(
                    "SELECT COUNT(*) as cnt FROM golden_paths WHERE task_type=?",
                    (task_type,)
                ).fetchone()
            else:
                row = conn.execute(
                    "SELECT COUNT(*) as cnt FROM golden_paths"
                ).fetchone()
            return row["cnt"] if row else 0
        finally:
            conn.close()

    # ══════════════════════════════════════════════════════════
    # ФОРМАТИРОВАНИЕ ДЛЯ ПРОМПТА
    # ══════════════════════════════════════════════════════════

    def format_runbook_prompt(self, match: GoldenPathMatch) -> str:
        """Сформировать промпт с runbook как рекомендацию."""
        path = match.path
        steps = path.get("steps", [])

        steps_text = ""
        for s in steps:
            tpl = s.get("action_template", {})
            desc = s.get("description", "")
            risk = s.get("risk_level", "guarded")
            steps_text += f"\nШаг {s['order']}: [{s['tool']}] {desc}"
            if tpl:
                steps_text += f"\n  Шаблон: {json.dumps(tpl, ensure_ascii=False)[:200]}"
            steps_text += f"\n  Риск: {risk}"

        return f"""НАЙДЕН РАНЕЕ УСПЕШНЫЙ RUNBOOK для похожей задачи.
Совпадение среды: {match.match_score}/6.
Успешных выполнений: {path.get('success_count', 0)}.
Средняя стоимость: ${path.get('avg_cost', 0):.2f}.
Среднее время: {path.get('avg_time', 0):.0f} сек.

Используй этот runbook как предпочтительный путь:
{steps_text}

Перед каждым шагом проверь:
- применим ли шаг к текущей среде,
- не конфликтует ли он с текущим Task Charter,
- не нарушает ли success criteria.

Если шаг не применим — адаптируй, но не нарушай success criteria.
Не пропускай критичные verification steps."""

    def format_anti_patterns_prompt(self, task_type: str) -> str:
        """Сформировать промпт с известными ложными успехами."""
        conn = self._conn()
        try:
            rows = conn.execute(
                "SELECT pattern, description, severity FROM anti_patterns "
                "WHERE task_type=? ORDER BY severity DESC, detected_count DESC",
                (task_type,)
            ).fetchall()

            if not rows:
                return ""

            patterns_text = ""
            for row in rows:
                patterns_text += f"\n- [{row['severity'].upper()}] {row['pattern']}: {row['description']}"

            return f"""ИЗВЕСТНЫЕ ЛОЖНЫЕ УСПЕХИ для задач типа '{task_type}':
НЕ считай задачу выполненной если:
{patterns_text}

Перед завершением задачи проверь каждый пункт."""

        finally:
            conn.close()
