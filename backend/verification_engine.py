"""
Verification Engine — замкнутый контур проверки на КАЖДОМ уровне.
================================================================
- before_action: GoalKeeper check
- after_action: result verification (успех? ожидаемый?)
- before_handoff: artifact validation (файл создан? не пустой?)
- before_completion: FinalJudge
- after_failure: replan или rollback

Единая схема verdict:
{"level": "action/handoff/completion",
 "passed": true/false,
 "score": 0-10,
 "issues": [...],
 "action": "continue/retry/replan/abort"}
"""
import json
import time
import logging
from typing import Optional, Dict, List, Any
from dataclasses import dataclass, field, asdict

logger = logging.getLogger("verification_engine")


@dataclass
class Verdict:
    """Единая схема verdict для всех уровней проверки."""
    level: str  # action, handoff, completion, failure
    passed: bool
    score: float = 0.0  # 0-10
    issues: List[str] = field(default_factory=list)
    action: str = "continue"  # continue, retry, replan, abort
    details: Dict = field(default_factory=dict)
    timestamp: float = 0.0

    def __post_init__(self):
        if self.timestamp == 0.0:
            self.timestamp = time.time()

    def to_dict(self) -> Dict:
        return asdict(self)

    @property
    def is_critical(self) -> bool:
        return self.action in ("abort", "replan")


class VerificationEngine:
    """
    Замкнутый контур проверки.
    Вызывается на каждом этапе выполнения задачи.
    """

    def __init__(self, goal_keeper=None, final_judge=None):
        self._goal_keeper = goal_keeper
        self._final_judge = final_judge
        self._verdicts: List[Verdict] = []
        self._retry_counts: Dict[str, int] = {}
        self.max_retries = 3

    @property
    def verdicts(self) -> List[Dict]:
        return [v.to_dict() for v in self._verdicts]

    def get_verdicts_by_level(self, level: str) -> List[Dict]:
        return [v.to_dict() for v in self._verdicts if v.level == level]

    # ═══════════════════════════════════════════
    # LEVEL 1: BEFORE ACTION
    # ═══════════════════════════════════════════
    def before_action(self, charter: Dict, action: Dict,
                      snapshot: Dict = None) -> Verdict:
        """
        Проверка перед выполнением действия.
        GoalKeeper check: безопасность, бюджет, drift.
        """
        issues = []
        score = 10.0
        passed = True
        action_decision = "continue"

        # 1. Check if action has required fields
        tool = action.get("tool", "")
        if not tool:
            issues.append("Action has no tool specified")
            score -= 5
            passed = False
            action_decision = "abort"

        # 2. GoalKeeper check (if available)
        if self._goal_keeper and charter:
            try:
                gk_result = self._goal_keeper.validate_next_action(
                    charter, snapshot, action
                )
                if not gk_result.get("approved", True):
                    issues.extend(gk_result.get("reasons", ["GoalKeeper blocked"]))
                    score -= 5
                    passed = False
                    action_decision = "abort"
                warnings = gk_result.get("warnings", [])
                if warnings:
                    issues.extend(warnings)
                    score -= len(warnings) * 0.5
            except Exception as e:
                issues.append(f"GoalKeeper error: {str(e)}")
                score -= 1

        # 3. Budget check
        if charter:
            cost = charter.get("total_cost_usd", 0)
            limit = charter.get("max_cost_usd", 999)
            if limit > 0 and cost > limit:
                issues.append(f"Budget exceeded: ${cost:.2f} > ${limit:.2f}")
                score -= 3
                action_decision = "abort"
                passed = False

        score = max(0, min(10, score))
        verdict = Verdict(
            level="action",
            passed=passed,
            score=score,
            issues=issues,
            action=action_decision,
            details={"tool": tool, "check": "before_action"}
        )
        self._verdicts.append(verdict)
        return verdict

    # ═══════════════════════════════════════════
    # LEVEL 2: AFTER ACTION
    # ═══════════════════════════════════════════
    def after_action(self, action: Dict, result: Dict) -> Verdict:
        """
        Проверка после выполнения действия.
        Результат успешен? Ожидаемый?
        """
        issues = []
        score = 10.0
        passed = True
        action_decision = "continue"

        tool = action.get("tool", "unknown")
        step_key = f"{tool}_{action.get('step_id', 'default')}"

        # Check result success
        success = result.get("success", result.get("ok", True))
        error = result.get("error", result.get("stderr", ""))

        if not success:
            issues.append(f"Action failed: {tool}")
            score -= 4
            passed = False

            # Check retry count
            self._retry_counts[step_key] = self._retry_counts.get(step_key, 0) + 1
            retries = self._retry_counts[step_key]

            if retries >= self.max_retries:
                action_decision = "replan"
                issues.append(f"Max retries ({self.max_retries}) reached for {tool}")
                score -= 3
            else:
                action_decision = "retry"
                issues.append(f"Retry {retries}/{self.max_retries}")

        if error and isinstance(error, str) and len(error) > 0:
            issues.append(f"Error output: {error[:200]}")
            score -= 1

        # Check for empty result
        output = result.get("output", result.get("stdout", ""))
        if not output and not error and success:
            # Empty but successful — might be OK
            score -= 0.5

        score = max(0, min(10, score))
        verdict = Verdict(
            level="action",
            passed=passed,
            score=score,
            issues=issues,
            action=action_decision,
            details={"tool": tool, "check": "after_action", "success": success}
        )
        self._verdicts.append(verdict)
        return verdict

    # ═══════════════════════════════════════════
    # LEVEL 3: BEFORE HANDOFF
    # ═══════════════════════════════════════════
    def before_handoff(self, artifacts: List[Dict],
                       expected_deliverables: List[str] = None) -> Verdict:
        """
        Проверка перед передачей артефактов.
        Файл создан? Не пустой? Все deliverables есть?
        """
        issues = []
        score = 10.0
        passed = True
        action_decision = "continue"

        if not artifacts:
            issues.append("No artifacts to hand off")
            score -= 3
            # Not necessarily a failure — some tasks don't produce artifacts
            
        # Check each artifact
        for art in artifacts:
            name = art.get("name", art.get("path", "unknown"))
            size = art.get("size_bytes", art.get("size", -1))
            
            if size == 0:
                issues.append(f"Artifact '{name}' is empty (0 bytes)")
                score -= 2
            elif size < 0:
                issues.append(f"Artifact '{name}' size unknown")
                score -= 0.5

        # Check deliverables
        if expected_deliverables:
            artifact_names = {a.get("name", "") for a in artifacts}
            artifact_paths = {a.get("path", "") for a in artifacts}
            all_known = artifact_names | artifact_paths

            for d in expected_deliverables:
                if d not in all_known:
                    # Partial match
                    if not any(d in n for n in all_known):
                        issues.append(f"Missing deliverable: {d}")
                        score -= 2
                        passed = False

            if not passed:
                action_decision = "retry"

        score = max(0, min(10, score))
        verdict = Verdict(
            level="handoff",
            passed=passed,
            score=score,
            issues=issues,
            action=action_decision,
            details={"artifacts_count": len(artifacts), "check": "before_handoff"}
        )
        self._verdicts.append(verdict)
        return verdict

    # ═══════════════════════════════════════════
    # LEVEL 4: BEFORE COMPLETION
    # ═══════════════════════════════════════════
    def before_completion(self, charter: Dict,
                          final_answer: str = "",
                          actions_log: List[Dict] = None) -> Verdict:
        """
        Проверка перед завершением задачи.
        FinalJudge: все критерии выполнены?
        """
        issues = []
        score = 10.0
        passed = True
        action_decision = "continue"

        # Basic checks
        if not final_answer:
            issues.append("No final answer provided")
            score -= 2

        if not charter:
            issues.append("No charter — cannot verify completion")
            score -= 3

        # Check success criteria
        if charter:
            criteria = charter.get("success_criteria", [])
            if criteria and not final_answer:
                issues.append("Success criteria defined but no final answer")
                score -= 2

        # FinalJudge (if available)
        if self._final_judge and charter:
            try:
                judge_result = self._final_judge.judge(charter, final_answer)
                judge_score = getattr(judge_result, 'score', 5.0)
                judge_verdict = getattr(judge_result, 'verdict', 'unknown')
                
                if judge_verdict.upper() in ("REJECTED", "FAIL"):
                    passed = False
                    action_decision = "retry"
                    issues.append(f"FinalJudge rejected: {judge_verdict}")
                    score = min(score, judge_score * 10 if judge_score <= 1 else judge_score)
                
                judge_issues = getattr(judge_result, 'issues', [])
                issues.extend(judge_issues)
            except Exception as e:
                issues.append(f"FinalJudge error: {str(e)}")

        # Actions log analysis
        if actions_log:
            total = len(actions_log)
            failed = sum(1 for a in actions_log if not a.get("success", True))
            if total > 0:
                success_rate = (total - failed) / total
                if success_rate < 0.5:
                    issues.append(f"Low success rate: {success_rate:.0%}")
                    score -= 3
                    if success_rate < 0.3:
                        passed = False
                        action_decision = "replan"

        score = max(0, min(10, score))
        verdict = Verdict(
            level="completion",
            passed=passed,
            score=score,
            issues=issues,
            action=action_decision,
            details={"check": "before_completion"}
        )
        self._verdicts.append(verdict)
        return verdict

    # ═══════════════════════════════════════════
    # LEVEL 5: AFTER FAILURE
    # ═══════════════════════════════════════════
    def after_failure(self, error: str, context: Dict = None) -> Verdict:
        """
        Обработка после сбоя.
        Решение: retry, replan, или abort.
        """
        issues = [f"Failure: {error[:300]}"]
        score = 2.0
        action_decision = "retry"

        # Analyze error type
        error_lower = error.lower()
        
        if any(kw in error_lower for kw in ["timeout", "timed out"]):
            action_decision = "retry"
            issues.append("Timeout — will retry")
        elif any(kw in error_lower for kw in ["permission denied", "access denied"]):
            action_decision = "abort"
            issues.append("Permission denied — cannot proceed")
            score = 0
        elif any(kw in error_lower for kw in ["not found", "404"]):
            action_decision = "replan"
            issues.append("Resource not found — need to replan")
        elif any(kw in error_lower for kw in ["out of memory", "disk full"]):
            action_decision = "abort"
            issues.append("Resource exhaustion — abort")
            score = 0
        elif any(kw in error_lower for kw in ["connection refused", "network"]):
            action_decision = "retry"
            issues.append("Network issue — will retry")

        # Check context for retry count
        if context:
            retries = context.get("retry_count", 0)
            if retries >= self.max_retries:
                action_decision = "abort"
                issues.append(f"Max retries exceeded ({retries})")
                score = 0

        verdict = Verdict(
            level="failure",
            passed=False,
            score=score,
            issues=issues,
            action=action_decision,
            details={"error": error[:500], "check": "after_failure"}
        )
        self._verdicts.append(verdict)
        return verdict

    # ═══════════════════════════════════════════
    # SUMMARY
    # ═══════════════════════════════════════════
    def summary(self) -> Dict:
        """Сводка всех проверок."""
        total = len(self._verdicts)
        passed = sum(1 for v in self._verdicts if v.passed)
        failed = total - passed
        avg_score = sum(v.score for v in self._verdicts) / total if total > 0 else 0

        by_level = {}
        for v in self._verdicts:
            if v.level not in by_level:
                by_level[v.level] = {"total": 0, "passed": 0, "failed": 0}
            by_level[v.level]["total"] += 1
            if v.passed:
                by_level[v.level]["passed"] += 1
            else:
                by_level[v.level]["failed"] += 1

        all_issues = []
        for v in self._verdicts:
            all_issues.extend(v.issues)

        return {
            "total_checks": total,
            "passed": passed,
            "failed": failed,
            "avg_score": round(avg_score, 2),
            "by_level": by_level,
            "critical_issues": [i for i in all_issues if "abort" in i.lower() or "denied" in i.lower()],
            "all_issues_count": len(all_issues)
        }

    def reset(self):
        """Сбросить все вердикты."""
        self._verdicts.clear()
        self._retry_counts.clear()


# ═══════════════════════════════════════════
# SINGLETON
# ═══════════════════════════════════════════
_engine = None

def get_verification_engine(goal_keeper=None, final_judge=None) -> VerificationEngine:
    global _engine
    if _engine is None:
        _engine = VerificationEngine(goal_keeper, final_judge)
    return _engine
