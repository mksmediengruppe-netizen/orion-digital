"""
Goal Keeper — проверяет каждое действие перед выполнением.
============================================================

Перед каждым tool call, replanning и final answer
Goal Keeper проверяет:
1. Это действие ведёт к цели?
2. Не нарушены ли ограничения?
3. Не забыта ли поправка пользователя?
4. Есть ли rollback?
5. Нет ли более безопасной альтернативы?

Это "умный тормоз" — самый полезный слой контроля.
"""

import json
import logging
import re
from typing import Dict, Optional, List, Callable

logger = logging.getLogger("goal_keeper")


# ═══════════════════════════════════════════
# RISK LEVELS
# ═══════════════════════════════════════════

TOOL_RISK_LEVELS = {
    # SAFE — чтение, инспекция
    "web_search": "safe",
    "file_read": "safe",
    "browser_check_site": "safe",
    "browser_screenshot": "safe",
    "search_knowledge": "safe",
    "get_weather": "safe",
    "task_complete": "safe",
    "update_scratchpad": "safe",
    "update_task_charter": "safe",
    
    # GUARDED — создание контента, ограниченные действия
    "file_write": "guarded",
    "generate_image": "guarded",
    "generate_file": "guarded",
    "browser_navigate": "guarded",
    "browser_fill": "guarded",
    "browser_click": "guarded",
    "code_execute": "guarded",
    
    # PRIVILEGED — деплой, удаление, SSH write
    "ssh_execute": "privileged",
    "ftp_upload": "privileged",
    "browser_execute_js": "privileged",
    "deploy_site": "privileged",
}

# Опасные SSH команды
DANGEROUS_SSH_PATTERNS = [
    r"rm\s+-rf\s+/",
    r"dd\s+if=",
    r"mkfs\.",
    r"fdisk",
    r"chmod\s+-R\s+777\s+/",
    r"chown\s+-R\s+.*\s+/(?!var|tmp|home)",
    r"systemctl\s+(stop|disable)\s+(nginx|apache|mysql|postgresql|sshd)",
    r"iptables\s+-F",
    r"DROP\s+DATABASE",
    r"DROP\s+TABLE",
    r"TRUNCATE\s+TABLE",
    r">\s*/etc/",
    r"curl\s+.*\|\s*(bash|sh)",
    r"wget\s+.*\|\s*(bash|sh)",
]

# Максимальная длина файла для file_write (500KB)
MAX_FILE_WRITE_SIZE = 500_000


class GoalKeeper:
    """
    Валидирует каждое действие перед выполнением.
    
    Уровни проверки:
    1. SAFETY — действие безопасно?
    2. ALIGNMENT — действие ведёт к цели?
    3. CONSTRAINTS — не нарушены ограничения?
    4. AMENDMENTS — учтены поправки пользователя?
    """

    def __init__(self, call_ai_fn: Callable = None):
        """
        Args:
            call_ai_fn: функция для вызова LLM (для alignment check).
                        Если None — проверяет только правила.
        """
        self._call_ai = call_ai_fn
        self._action_log: List[Dict] = []  # История проверок

    def validate_next_action(
        self,
        task_charter: Optional[Dict],
        latest_snapshot: Optional[Dict],
        proposed_action: Dict
    ) -> Dict:
        """
        Главная точка входа. Проверяет действие перед выполнением.
        
        Args:
            task_charter: текущий Charter задачи
            latest_snapshot: последний snapshot
            proposed_action: {"tool": "ssh_execute", "args": {...}}
        
        Returns:
            {
                "approved": True/False,
                "risk_level": "safe"/"guarded"/"privileged",
                "warnings": ["..."],
                "blocked_reason": "..." (если approved=False),
                "suggestions": ["..."]
            }
        """
        tool = proposed_action.get("tool", "unknown")
        args = proposed_action.get("args", {})
        
        result = {
            "approved": True,
            "risk_level": TOOL_RISK_LEVELS.get(tool, "guarded"),
            "warnings": [],
            "blocked_reason": "",
            "suggestions": []
        }

        # ─── SAFETY CHECK ────────────────────────
        safety = self._check_safety(tool, args)
        if not safety["safe"]:
            result["approved"] = False
            result["blocked_reason"] = safety["reason"]
            self._log_check(tool, "BLOCKED", safety["reason"])
            return result
        result["warnings"].extend(safety.get("warnings", []))

        # ─── CONSTRAINT CHECK ────────────────────
        if task_charter:
            constraint_check = self._check_constraints(
                tool, args, task_charter
            )
            if not constraint_check["ok"]:
                result["approved"] = False
                result["blocked_reason"] = constraint_check["reason"]
                self._log_check(tool, "BLOCKED", constraint_check["reason"])
                return result
            result["warnings"].extend(constraint_check.get("warnings", []))

        # ─── AMENDMENT CHECK ─────────────────────
        if task_charter:
            amendment_check = self._check_amendments(
                tool, args, task_charter
            )
            result["warnings"].extend(amendment_check.get("warnings", []))

        # ─── DRIFT CHECK ────────────────────────
        if task_charter and latest_snapshot:
            drift_check = self._check_drift(
                tool, args, task_charter, latest_snapshot
            )
            result["warnings"].extend(drift_check.get("warnings", []))
            if drift_check.get("suggestions"):
                result["suggestions"].extend(drift_check["suggestions"])

        # ─── LOG ─────────────────────────────────
        status = "APPROVED" if result["approved"] else "BLOCKED"
        warnings_str = "; ".join(result["warnings"]) if result["warnings"] else "none"
        self._log_check(tool, status, warnings_str)

        return result

    # ═══════════════════════════════════════════
    # SAFETY CHECK
    # ═══════════════════════════════════════════

    def _check_safety(self, tool: str, args: Dict) -> Dict:
        """Проверка безопасности действия."""
        warnings = []

        # SSH команды
        if tool == "ssh_execute":
            command = args.get("command", "")
            
            # Проверить опасные паттерны
            for pattern in DANGEROUS_SSH_PATTERNS:
                if re.search(pattern, command, re.IGNORECASE):
                    return {
                        "safe": False,
                        "reason": f"Опасная SSH команда заблокирована: {pattern}"
                    }

            # Предупреждения для потенциально опасных
            if "rm " in command and "-r" in command:
                warnings.append(f"rm -r команда: {command[:80]}")
            if "chmod" in command or "chown" in command:
                warnings.append(f"Изменение прав: {command[:80]}")
            if "systemctl restart" in command:
                warnings.append(f"Перезапуск сервиса: {command[:80]}")

        # File write — проверить размер
        if tool == "file_write":
            content = args.get("content", "")
            if len(content) > MAX_FILE_WRITE_SIZE:
                return {
                    "safe": False,
                    "reason": f"Файл слишком большой: {len(content)} символов "
                              f"(макс {MAX_FILE_WRITE_SIZE})"
                }
            path = args.get("path", "")
            # Запретить запись в системные директории
            dangerous_paths = ["/etc/", "/usr/", "/bin/", "/sbin/", 
                             "/boot/", "/root/.ssh/"]
            for dp in dangerous_paths:
                if path.startswith(dp):
                    return {
                        "safe": False,
                        "reason": f"Запись в системную директорию запрещена: {path}"
                    }

        # Browser JS execution
        if tool == "browser_execute_js":
            code = args.get("code", "")
            if "document.cookie" in code or "localStorage" in code:
                warnings.append("JS код обращается к cookie/localStorage")

        # Code execute
        if tool == "code_execute":
            code = args.get("code", "")
            dangerous = ["__import__", "subprocess", "os.system", 
                        "shutil.rmtree", "eval(", "exec("]
            for d in dangerous:
                if d in code:
                    return {
                        "safe": False,
                        "reason": f"Опасный код заблокирован: {d}"
                    }

        return {"safe": True, "warnings": warnings}

    # ═══════════════════════════════════════════
    # CONSTRAINT CHECK
    # ═══════════════════════════════════════════

    def _check_constraints(self, tool: str, args: Dict, 
                            charter: Dict) -> Dict:
        """Проверка ограничений из Charter."""
        warnings = []
        constraints = charter.get("constraints", [])
        
        # Проверить бюджет
        cost = charter.get("total_cost", 0)
        for c in constraints:
            if "бюджет" in c.lower() or "budget" in c.lower() or "$" in c:
                # Извлечь лимит из текста
                import re
                match = re.search(r'\$?([\d.]+)', c)
                if match:
                    limit = float(match.group(1))
                    if cost >= limit * 0.8:
                        warnings.append(
                            f"Бюджет почти исчерпан: ${cost:.2f} из ${limit:.2f}"
                        )
                    if cost >= limit:
                        return {
                            "ok": False,
                            "reason": f"Бюджет исчерпан: ${cost:.2f} >= ${limit:.2f}"
                        }

        return {"ok": True, "warnings": warnings}

    # ═══════════════════════════════════════════
    # AMENDMENT CHECK
    # ═══════════════════════════════════════════

    def _check_amendments(self, tool: str, args: Dict,
                           charter: Dict) -> Dict:
        """Проверка что поправки пользователя не забыты."""
        warnings = []
        amendments = charter.get("amendments", [])
        
        if not amendments:
            return {"warnings": []}

        # Последняя поправка — самая важная
        last = amendments[-1]
        last_text = last.get("text", "").lower()
        
        # Если поправка содержит "стоп" или "отмени" — предупредить
        if any(w in last_text for w in ["стоп", "отмен", "не делай", "прекрати"]):
            warnings.append(
                f"⚠️ Пользователь просил остановиться: {last['text'][:100]}"
            )

        # Если поправка была недавно (<60 сек) — напомнить
        import time
        if time.time() - last.get("timestamp", 0) < 60:
            warnings.append(
                f"⚠️ Свежая поправка (< 1 мин назад): {last['text'][:100]}"
            )

        return {"warnings": warnings}

    # ═══════════════════════════════════════════
    # DRIFT CHECK
    # ═══════════════════════════════════════════

    def _check_drift(self, tool: str, args: Dict,
                      charter: Dict, snapshot: Dict) -> Dict:
        """Проверка отклонения от цели."""
        warnings = []
        suggestions = []

        # Если много итераций без прогресса
        iteration = snapshot.get("iteration", 0)
        completed = len(snapshot.get("completed_actions", []))
        
        if iteration > 20 and completed < 3:
            warnings.append(
                f"Возможный drift: {iteration} итераций, "
                f"только {completed} успешных действий"
            )
            suggestions.append(
                "Перечитай Task Charter и сфокусируйся на цели"
            )

        # Если есть blockers
        blockers = snapshot.get("blockers", [])
        if blockers:
            warnings.append(
                f"Активные блокеры: {'; '.join(blockers[:3])}"
            )

        # Если повторяются одни и те же tool calls
        actions = snapshot.get("completed_actions", [])
        if len(actions) >= 5:
            last_5_tools = [a.get("tool", "") for a in actions[-5:]]
            if len(set(last_5_tools)) == 1:
                warnings.append(
                    f"Зацикливание: последние 5 действий — {last_5_tools[0]}"
                )
                suggestions.append(
                    "Попробуй другой подход, текущий не работает"
                )

        return {"warnings": warnings, "suggestions": suggestions}

    # ═══════════════════════════════════════════
    # FORMAT FOR PROMPT
    # ═══════════════════════════════════════════

    def format_warnings_for_prompt(self, validation: Dict) -> str:
        """Форматирует результат проверки для промпта."""
        if not validation.get("warnings") and not validation.get("suggestions"):
            return ""

        parts = []
        
        if validation.get("warnings"):
            parts.append("⚠️ GOAL KEEPER ПРЕДУПРЕЖДЕНИЯ:")
            for w in validation["warnings"]:
                parts.append(f"  - {w}")

        if validation.get("suggestions"):
            parts.append("💡 РЕКОМЕНДАЦИИ:")
            for s in validation["suggestions"]:
                parts.append(f"  - {s}")

        return "\n".join(parts)

    # ═══════════════════════════════════════════
    # ACTION CONTRACT
    # ═══════════════════════════════════════════

    def create_action_contract(self, tool: str, args: Dict,
                                reason: str = "",
                                expected_outcome: str = "") -> Dict:
        """
        Создаёт Action Contract для действия.
        
        Контракт описывает: что делаем, зачем, что ожидаем,
        какой уровень риска, можно ли откатить.
        """
        risk = TOOL_RISK_LEVELS.get(tool, "guarded")
        
        # Определить rollback возможность
        rollback_possible = tool in [
            "file_write",  # можно перезаписать
            "ssh_execute",  # зависит от команды
            "browser_navigate",  # можно вернуться
        ]

        return {
            "tool": tool,
            "args_preview": str(args)[:200],
            "reason": reason or "не указана",
            "expected_outcome": expected_outcome or "не указан",
            "risk_level": risk,
            "rollback_possible": rollback_possible,
            "timestamp": __import__("time").time()
        }

    # ═══════════════════════════════════════════
    # INTERNAL
    # ═══════════════════════════════════════════


    # ═══════════════════════════════════════════
    # SEMANTIC ALIGNMENT CHECK (LLM-based)
    # ═══════════════════════════════════════════
    def _check_alignment(self, tool: str, args: Dict,
                          charter: Dict) -> Dict:
        """
        Semantic check: does this action align with the task goal?
        Uses LLM for privileged/guarded actions only.
        Falls back to rule-based if no LLM available.
        """
        risk = TOOL_RISK_LEVELS.get(tool, "guarded")
        
        # Only check privileged and guarded actions
        if risk == "safe":
            return {"aligned": True, "warnings": []}
        
        # If no LLM function — skip semantic check
        if not self._call_ai:
            return {"aligned": True, "warnings": []}
        
        objective = charter.get("primary_objective", charter.get("objective", ""))
        constraints = charter.get("constraints", [])
        
        if not objective:
            return {"aligned": True, "warnings": []}
        
        # Build compact prompt for fast LLM check
        args_preview = str(args)[:300]
        prompt = (
            f"Task objective: {objective}\n"
            f"Constraints: {', '.join(constraints[:5]) if constraints else 'none'}\n"
            f"Proposed action: {tool}({args_preview})\n\n"
            f"Does this action align with the task objective? "
            f"Reply ONLY with JSON: "
            f'{{"aligned": true/false, "reason": "brief explanation"}}'
        )
        
        try:
            response = self._call_ai([
                {"role": "system", "content": "You are a goal alignment checker. Reply ONLY with valid JSON."},
                {"role": "user", "content": prompt}
            ])
            
            # Parse response
            if isinstance(response, str):
                # Try to extract JSON from response
                import re as _re
                json_match = _re.search(r'\{[^}]+\}', response)
                if json_match:
                    result = json.loads(json_match.group())
                    if not result.get("aligned", True):
                        logger.warning(f"[GK] Alignment FAIL for {tool}: {result.get('reason', '?')}")
                        return {
                            "aligned": False,
                            "warnings": [f"Goal misalignment: {result.get('reason', 'action does not align with objective')}"]
                        }
                    return {"aligned": True, "warnings": []}
            
            return {"aligned": True, "warnings": []}
            
        except Exception as e:
            logger.debug(f"[GK] Alignment check failed (non-critical): {e}")
            return {"aligned": True, "warnings": []}

    def _log_check(self, tool: str, status: str, detail: str):
        """Логировать проверку."""
        self._action_log.append({
            "tool": tool,
            "status": status,
            "detail": detail[:200],
            "timestamp": __import__("time").time()
        })
        # Ротация — держать последние 100 проверок
        if len(self._action_log) > 100:
            self._action_log = self._action_log[-100:]

        logger.debug(f"GoalKeeper [{status}] {tool}: {detail[:80]}")

    def get_stats(self) -> Dict:
        """Статистика проверок."""
        total = len(self._action_log)
        approved = sum(1 for a in self._action_log if a["status"] == "APPROVED")
        blocked = sum(1 for a in self._action_log if a["status"] == "BLOCKED")

        return {
            "total_checks": total,
            "approved": approved,
            "blocked": blocked,
            "block_rate": round(blocked / max(total, 1) * 100, 1)
        }
