"""
Final Judge — независимая проверка результата задачи.
======================================================

После завершения задачи Final Judge проверяет:
1. Все ли deliverables выполнены?
2. Соответствует ли результат success_criteria?
3. Нет ли явных ошибок (сайт не открывается, код не работает)?
4. Выставляет итоговый вердикт: PASS / PARTIAL / FAIL

Вызывается ОДИН РАЗ в конце задачи, перед отправкой ответа пользователю.
"""

import json
import time
import logging
import re
from typing import Dict, List, Optional, Callable, Any

logger = logging.getLogger("final_judge")


# ═══════════════════════════════════════════
# VERDICT LEVELS
# ═══════════════════════════════════════════

VERDICT_PASS    = "PASS"     # Всё выполнено
VERDICT_PARTIAL = "PARTIAL"  # Частично выполнено
VERDICT_FAIL    = "FAIL"     # Задача провалена
VERDICT_SKIP    = "SKIP"     # Проверка пропущена (нет критериев)


class JudgeResult:
    """Результат проверки Final Judge."""

    def __init__(
        self,
        verdict: str,
        score: float,          # 0.0 - 1.0
        passed_criteria: List[str],
        failed_criteria: List[str],
        warnings: List[str],
        summary: str,
        details: Dict = None
    ):
        self.verdict = verdict
        self.score = score
        self.passed_criteria = passed_criteria
        self.failed_criteria = failed_criteria
        self.warnings = warnings
        self.summary = summary
        self.details = details or {}
        self.timestamp = time.time()

    def to_dict(self) -> Dict:
        return {
            "verdict": self.verdict,
            "score": round(self.score, 2),
            "passed_criteria": self.passed_criteria,
            "failed_criteria": self.failed_criteria,
            "warnings": self.warnings,
            "summary": self.summary,
            "details": self.details,
            "timestamp": self.timestamp
        }

    def format_for_user(self) -> str:
        """Форматирует результат для показа пользователю."""
        emoji = {"PASS": "✅", "PARTIAL": "⚠️", "FAIL": "❌", "SKIP": "⏭️"}.get(self.verdict, "?")
        lines = [f"{emoji} **Итог: {self.verdict}** (оценка: {self.score*100:.0f}%)"]
        lines.append(self.summary)

        if self.passed_criteria:
            lines.append("\n**Выполнено:**")
            for c in self.passed_criteria:
                lines.append(f"  ✓ {c}")

        if self.failed_criteria:
            lines.append("\n**Не выполнено:**")
            for c in self.failed_criteria:
                lines.append(f"  ✗ {c}")

        if self.warnings:
            lines.append("\n**Предупреждения:**")
            for w in self.warnings:
                lines.append(f"  ⚠ {w}")

        return "\n".join(lines)

    def format_for_prompt(self) -> str:
        """Форматирует для вставки в промпт агента."""
        return (
            f"[FINAL_JUDGE] Verdict: {self.verdict} | Score: {self.score:.2f}\n"
            f"Passed: {', '.join(self.passed_criteria) or 'none'}\n"
            f"Failed: {', '.join(self.failed_criteria) or 'none'}\n"
            f"Summary: {self.summary}"
        )


class FinalJudge:
    """
    Независимый судья результата задачи.
    
    Работает в двух режимах:
    1. Rule-based: проверяет по keywords, паттернам, наличию файлов
    2. AI-based: вызывает LLM для семантической проверки (если передана call_ai_fn)
    """

    def __init__(self, call_ai_fn: Callable = None):
        """
        Args:
            call_ai_fn: функция вызова LLM для AI-проверки.
                        Сигнатура: call_ai_fn(messages: list) -> str
        """
        self._call_ai = call_ai_fn

    def judge(
        self,
        task_charter: Optional[Dict],
        agent_final_answer: str,
        artifacts: List[Dict] = None,
        ssh_results: List[Dict] = None
    ) -> JudgeResult:
        """
        Главная точка входа. Проверяет результат задачи.

        Args:
            task_charter: Charter задачи (цель, критерии, deliverables)
            agent_final_answer: финальный ответ агента пользователю
            artifacts: список созданных артефактов (из ArtifactHandoff)
            ssh_results: список результатов SSH команд

        Returns:
            JudgeResult с вердиктом
        """
        if not task_charter:
            return JudgeResult(
                verdict=VERDICT_SKIP,
                score=1.0,
                passed_criteria=[],
                failed_criteria=[],
                warnings=[],
                summary="Нет Charter — проверка пропущена"
            )

        passed = []
        failed = []
        warnings = []

        success_criteria = task_charter.get("success_criteria", [])
        deliverables = task_charter.get("deliverables", [])
        objective = task_charter.get("current_objective", task_charter.get("primary_objective", ""))

        # ─── 1. Проверить deliverables ───────────────────────
        deliverable_results = self._check_deliverables(
            deliverables, agent_final_answer, artifacts, ssh_results
        )
        passed.extend(deliverable_results["passed"])
        failed.extend(deliverable_results["failed"])
        warnings.extend(deliverable_results["warnings"])

        # ─── 2. Проверить success criteria ───────────────────
        criteria_results = self._check_success_criteria(
            success_criteria, agent_final_answer, artifacts
        )
        passed.extend(criteria_results["passed"])
        failed.extend(criteria_results["failed"])

        # ─── 3. Проверить явные ошибки в ответе ──────────────
        error_check = self._check_for_errors(agent_final_answer)
        warnings.extend(error_check["warnings"])
        failed.extend(error_check["failed"])

        # ─── 4. AI-проверка (если доступна) ──────────────────
        if self._call_ai and (success_criteria or objective):
            ai_result = self._ai_check(
                objective, success_criteria, agent_final_answer
            )
            if ai_result:
                passed.extend(ai_result.get("passed", []))
                failed.extend(ai_result.get("failed", []))
                warnings.extend(ai_result.get("warnings", []))

        # ─── 5. Вычислить score и вердикт ────────────────────
        total = len(passed) + len(failed)
        if total == 0:
            # Нет критериев — смотрим на наличие ошибок
            if failed:
                score = 0.3
                verdict = VERDICT_FAIL
            else:
                score = 0.8
                verdict = VERDICT_PASS
        else:
            score = len(passed) / total
            if score >= 0.9:
                verdict = VERDICT_PASS
            elif score >= 0.5:
                verdict = VERDICT_PARTIAL
            else:
                verdict = VERDICT_FAIL

        # Снизить оценку если есть критические ошибки
        if any("ошибка" in w.lower() or "error" in w.lower() for w in warnings):
            score = max(0.0, score - 0.2)

        summary = self._generate_summary(verdict, score, objective, passed, failed)

        result = JudgeResult(
            verdict=verdict,
            score=score,
            passed_criteria=passed,
            failed_criteria=failed,
            warnings=warnings,
            summary=summary,
            details={
                "objective": objective,
                "total_criteria": total,
                "artifacts_count": len(artifacts or []),
            }
        )

        logger.info(
            f"[final_judge] {verdict} | score={score:.2f} | "
            f"passed={len(passed)} failed={len(failed)} warn={len(warnings)}"
        )
        return result

    # ═══════════════════════════════════════════
    # DELIVERABLES CHECK
    # ═══════════════════════════════════════════

    def _check_deliverables(
        self,
        deliverables: List[str],
        answer: str,
        artifacts: List[Dict],
        ssh_results: List[Dict]
    ) -> Dict:
        passed = []
        failed = []
        warnings = []

        if not deliverables:
            return {"passed": passed, "failed": failed, "warnings": warnings}

        answer_lower = answer.lower()
        artifact_contents = " ".join([
            a.get("content", "") for a in (artifacts or [])
        ]).lower()

        for deliverable in deliverables:
            d_lower = deliverable.lower()

            # Проверить упоминание в ответе или артефактах
            found = False

            # Файловые deliverables (index.html, style.css, ...)
            if any(ext in d_lower for ext in [".html", ".css", ".js", ".py", ".json", ".md"]):
                filename = d_lower.split("/")[-1]
                if filename in answer_lower or filename in artifact_contents:
                    found = True
                # Проверить SSH результаты
                for ssh_r in (ssh_results or []):
                    if filename in str(ssh_r).lower():
                        found = True
                        break

            # URL deliverables
            elif "http" in d_lower or "сайт" in d_lower or "url" in d_lower:
                if "http" in answer_lower or "://".lower() in answer_lower:
                    found = True

            # Общие deliverables — проверить ключевые слова
            else:
                keywords = d_lower.split()[:3]  # первые 3 слова
                if all(kw in answer_lower for kw in keywords if len(kw) > 3):
                    found = True

            if found:
                passed.append(f"Deliverable: {deliverable}")
            else:
                failed.append(f"Deliverable не найден: {deliverable}")

        return {"passed": passed, "failed": failed, "warnings": warnings}

    # ═══════════════════════════════════════════
    # SUCCESS CRITERIA CHECK
    # ═══════════════════════════════════════════

    def _check_success_criteria(
        self,
        criteria: List[str],
        answer: str,
        artifacts: List[Dict]
    ) -> Dict:
        passed = []
        failed = []
        answer_lower = answer.lower()

        for criterion in criteria:
            c_lower = criterion.lower()

            # Проверить негативные критерии
            if any(neg in c_lower for neg in ["нет ошибок", "без ошибок", "no error"]):
                if any(err in answer_lower for err in ["traceback", "error:", "exception:", "failed:"]):
                    failed.append(f"Критерий нарушен: {criterion}")
                else:
                    passed.append(f"Критерий: {criterion}")
                continue

            # Проверить URL/сайт критерии
            if any(kw in c_lower for kw in ["открывается", "доступен", "работает", "online"]):
                if "http" in answer_lower:
                    passed.append(f"Критерий: {criterion}")
                else:
                    failed.append(f"Критерий не подтверждён: {criterion}")
                continue

            # Общая проверка по ключевым словам
            keywords = [w for w in c_lower.split() if len(w) > 4][:4]
            if keywords and sum(1 for kw in keywords if kw in answer_lower) >= len(keywords) * 0.6:
                passed.append(f"Критерий: {criterion}")
            else:
                # Не можем подтвердить — не считаем провалом, только предупреждение
                passed.append(f"Критерий (не проверен): {criterion}")

        return {"passed": passed, "failed": failed}

    # ═══════════════════════════════════════════
    # ERROR CHECK
    # ═══════════════════════════════════════════

    def _check_for_errors(self, answer: str) -> Dict:
        """Проверить явные ошибки в финальном ответе агента."""
        warnings = []
        failed = []
        answer_lower = answer.lower()

        error_patterns = [
            (r"traceback \(most recent call last\)", "Python traceback в ответе"),
            (r"error:\s+\w+", "Ошибка в ответе"),
            (r"connection refused", "Соединение отклонено"),
            (r"permission denied", "Отказано в доступе"),
            (r"no such file or directory", "Файл не найден"),
            (r"command not found", "Команда не найдена"),
            (r"не удалось", "Не удалось выполнить"),
            (r"failed to", "Провал операции"),
        ]

        for pattern, description in error_patterns:
            if re.search(pattern, answer_lower):
                warnings.append(f"⚠️ {description}")

        # Критические провалы
        critical_patterns = [
            (r"задача не выполнена", "Агент сообщил о провале"),
            (r"не могу выполнить", "Агент отказался от задачи"),
            (r"невозможно", "Агент сообщил о невозможности"),
        ]
        for pattern, description in critical_patterns:
            if re.search(pattern, answer_lower):
                failed.append(description)

        return {"warnings": warnings, "failed": failed}

    # ═══════════════════════════════════════════
    # AI CHECK
    # ═══════════════════════════════════════════

    def _ai_check(
        self,
        objective: str,
        criteria: List[str],
        answer: str
    ) -> Optional[Dict]:
        """AI-проверка через LLM."""
        if not self._call_ai:
            return None

        criteria_str = "\n".join(f"- {c}" for c in criteria) if criteria else "Нет явных критериев"
        prompt = f"""Ты — независимый судья результата задачи. Оцени выполнение.

ЗАДАЧА: {objective[:500]}

КРИТЕРИИ УСПЕХА:
{criteria_str}

ОТВЕТ АГЕНТА (первые 1500 символов):
{answer[:1500]}

Ответь СТРОГО в JSON:
{{
  "passed": ["критерий 1", "критерий 2"],
  "failed": ["критерий 3"],
  "warnings": ["предупреждение"]
}}

Только JSON, без пояснений."""

        try:
            response = self._call_ai([{"role": "user", "content": prompt}])
            # Извлечь JSON из ответа
            match = re.search(r'\{.*\}', response, re.DOTALL)
            if match:
                return json.loads(match.group())
        except Exception as e:
            logger.warning(f"[final_judge] AI check failed: {e}")

        return None

    # ═══════════════════════════════════════════
    # SUMMARY
    # ═══════════════════════════════════════════

    def _generate_summary(
        self,
        verdict: str,
        score: float,
        objective: str,
        passed: List[str],
        failed: List[str]
    ) -> str:
        obj_short = objective[:100] if objective else "задача"

        if verdict == VERDICT_PASS:
            return f"Задача «{obj_short}» выполнена успешно."
        elif verdict == VERDICT_PARTIAL:
            return (
                f"Задача «{obj_short}» выполнена частично ({score*100:.0f}%). "
                f"Не выполнено: {len(failed)} из {len(passed)+len(failed)} критериев."
            )
        elif verdict == VERDICT_FAIL:
            reasons = "; ".join(failed[:3]) if failed else "неизвестная причина"
            return f"Задача «{obj_short}» не выполнена. Причины: {reasons}"
        else:
            return f"Проверка пропущена для задачи «{obj_short}»"


# ═══════════════════════════════════════════
# SINGLETON
# ═══════════════════════════════════════════

_final_judge: Optional[FinalJudge] = None

def get_final_judge(call_ai_fn: Callable = None) -> FinalJudge:
    global _final_judge
    if _final_judge is None:
        _final_judge = FinalJudge(call_ai_fn=call_ai_fn)
    elif call_ai_fn and _final_judge._call_ai is None:
        _final_judge._call_ai = call_ai_fn
    return _final_judge
