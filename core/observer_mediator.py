"""
observer_mediator.py — ARCANE 4.0 Haiku Observer / Mediator

Роль: Нервная система агентства.
- Быстрая классификация задач (дешевле чем Opus/Sonnet)
- Pre-flight бюджетный контроль (проверяет budget.json ДО запуска дорогих моделей)
- Watchdog: мониторит итерации Manus, блокирует зависание
- JSON-валидация спецификаций (design_spec, positioning, seo_spec)
- Роутинг: определяет нужен ли Opus, Sonnet или достаточно Haiku

Модель: claude-haiku-4.5 ($1/$5 per 1M) — в 5-25x дешевле Opus/Sonnet.
"""
from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger("arcane.observer")

# ─── Constants ────────────────────────────────────────────────────────────────
OBSERVER_MODEL = "claude-haiku-4.5"
OBSERVER_OPENROUTER_ID = "anthropic/claude-haiku-4.5"

# Budget thresholds
BUDGET_WARNING_RATIO = 0.80   # 80% → warn user
BUDGET_PAUSE_RATIO   = 0.95   # 95% → pause, ask user
BUDGET_STOP_RATIO    = 1.00   # 100% → hard stop

# Watchdog
MAX_MANUS_ITERATIONS = 15     # max steps before Manus is considered stuck
MAX_QA_ROUNDS        = 3      # max visual QA rounds before forced acceptance

# Task complexity thresholds
SIMPLE_TASK_MAX_LEN  = 100
COMPLEX_TASK_MIN_LEN = 400


class TaskComplexity(str, Enum):
    SIMPLE   = "simple"    # Haiku can handle alone
    MODERATE = "moderate"  # Sonnet needed
    COMPLEX  = "complex"   # Opus + Sonnet needed


class TaskRoute(str, Enum):
    """Which pipeline to activate."""
    QUICK       = "quick"       # Observer → Haiku direct (simple edits, status checks)
    STANDARD    = "standard"    # Observer → Sonnet (code fixes, content edits)
    FULL        = "full"        # Observer → Opus → Sonnet → Manus (new projects)
    RESEARCH    = "research"    # Observer → Manus (browse) → Opus → Sonnet → Manus (build)
    MARKETING   = "marketing"   # Observer → Manus (research) → Opus (strategy) → Sonnet (SEO)


@dataclass
class ObserverDecision:
    """Result of Observer's analysis."""
    route: TaskRoute
    complexity: TaskComplexity
    task_type: str
    needs_research: bool = False      # Manus should browse first
    needs_motion_dev: bool = False    # GSAP/Three.js needed
    needs_seo: bool = False           # SEO Writer needed
    needs_marketing: bool = False     # Marketer needed
    budget_status: str = "ok"         # ok / warning / pause / stop
    budget_remaining: float | None = None
    block_reason: str | None = None   # if not None, execution is blocked
    estimated_agents: list[str] = field(default_factory=list)
    confidence: float = 1.0


@dataclass
class WatchdogState:
    """Tracks Manus execution to detect infinite loops."""
    project_id: str
    run_id: str
    manus_iterations: int = 0
    qa_rounds: int = 0
    last_progress_at: float = field(default_factory=time.time)
    stuck: bool = False


class ObserverMediator:
    """
    Haiku-powered Observer that mediates the entire ARCANE 4.0 pipeline.

    Usage:
        observer = ObserverMediator(llm_client, project_manager)
        decision = await observer.analyze(project_id, task, budget_limit)
        if decision.block_reason:
            return error_to_user(decision.block_reason)
        # proceed with pipeline based on decision.route
    """

    def __init__(self, llm_client=None, project_manager=None):
        self._llm = llm_client
        self._pm = project_manager
        self._watchdogs: dict[str, WatchdogState] = {}

    # ─── Main entry point ─────────────────────────────────────────────────────

    async def analyze(
        self,
        project_id: str,
        task: str,
        budget_limit: float | None = None,
        run_id: str | None = None,
    ) -> ObserverDecision:
        """
        Full pre-flight analysis. Called BEFORE any expensive model.
        Returns ObserverDecision with route, complexity, and budget status.
        """
        # 1. Budget pre-flight check (free — reads JSON, no LLM call)
        budget_status, budget_remaining = self._check_budget(project_id, budget_limit)

        if budget_status == "stop":
            return ObserverDecision(
                route=TaskRoute.QUICK,
                complexity=TaskComplexity.SIMPLE,
                task_type="blocked",
                budget_status="stop",
                budget_remaining=budget_remaining,
                block_reason=(
                    f"Бюджет исчерпан (потрачено 100%+). "
                    f"Осталось: ${budget_remaining:.4f}. "
                    f"Пополните лимит проекта для продолжения."
                ),
            )

        # 2. Fast keyword classification (no LLM call — instant)
        decision = self._keyword_classify(task)
        decision.budget_status = budget_status
        decision.budget_remaining = budget_remaining

        # 3. Budget warning injection
        if budget_status == "pause":
            decision.block_reason = (
                f"Бюджет на паузе (95%+ израсходовано). "
                f"Осталось: ${budget_remaining:.4f}. "
                f"Подтвердите продолжение или пополните лимит."
            )
        elif budget_status == "warning":
            logger.warning(
                "[Observer] Budget WARNING for project=%s: remaining=$%.4f",
                project_id, budget_remaining or 0
            )

        # 4. LLM-enhanced classification for complex tasks (uses Haiku — cheap)
        if decision.complexity == TaskComplexity.COMPLEX and self._llm:
            try:
                decision = await self._llm_classify(task, decision)
            except Exception as e:
                logger.warning("[Observer] LLM classify failed, using keyword result: %s", e)

        logger.info(
            "[Observer] Decision: route=%s complexity=%s type=%s "
            "budget=%s remaining=$%.4f agents=%s",
            decision.route.value, decision.complexity.value, decision.task_type,
            decision.budget_status, decision.budget_remaining or 0,
            decision.estimated_agents,
        )
        return decision

    # ─── Budget check ─────────────────────────────────────────────────────────

    def _check_budget(
        self, project_id: str, budget_limit: float | None
    ) -> tuple[str, float | None]:
        """
        Read budget.json from project folder and check thresholds.
        Returns (status, remaining_usd).
        Status: 'ok' | 'warning' | 'pause' | 'stop'
        """
        if not self._pm or not project_id:
            return "ok", None

        try:
            budget = self._pm.get_budget(project_id)
            spent = budget.get("total_spent_usd", 0.0)

            # Determine effective limit
            limit = budget_limit
            if limit is None:
                limit = budget.get("limits", {}).get("per_project_month")
            if not limit or limit <= 0:
                return "ok", None  # No limit set → unlimited

            remaining = max(0.0, limit - spent)
            ratio = spent / limit

            if ratio >= BUDGET_STOP_RATIO:
                return "stop", remaining
            elif ratio >= BUDGET_PAUSE_RATIO:
                return "pause", remaining
            elif ratio >= BUDGET_WARNING_RATIO:
                return "warning", remaining
            else:
                return "ok", remaining

        except Exception as e:
            logger.debug("[Observer] Budget check failed (non-critical): %s", e)
            return "ok", None

    # ─── Keyword classification ────────────────────────────────────────────────

    def _keyword_classify(self, task: str) -> ObserverDecision:
        """
        Fast keyword-based classification. No LLM call. ~0ms.
        Determines route, agents needed, and complexity.
        """
        t = task.lower()
        task_len = len(task)

        # ── Task type detection ──────────────────────────────────────────────
        is_web_design = any(w in t for w in [
            "сайт", "лендинг", "страниц", "landing", "html", "css",
            "дизайн", "вёрст", "верст", "awwwards", "ui", "ux"
        ])
        is_coding = any(w in t for w in [
            "код", "скрипт", "api", "бот", "функци", "python",
            "javascript", "typescript", "react", "next.js", "бэкенд", "backend"
        ])
        is_motion = any(w in t for w in [
            "анимац", "gsap", "three.js", "motion", "parallax",
            "lottie", "scroll", "transition", "webgl", "canvas"
        ])
        is_marketing = any(w in t for w in [
            "маркетинг", "реклама", "продвижение", "стратегия",
            "позиционирование", "бренд", "smm", "таргет", "аудитор"
        ])
        is_seo = any(w in t for w in [
            "seo", "семантика", "ключевые слова", "мета", "h1", "h2",
            "контент-план", "статья", "копирайт"
        ])
        is_research = any(w in t for w in [
            "анализ", "исследов", "конкурент", "awwwards", "референс",
            "обзор", "сравн", "рынок"
        ])
        is_devops = any(w in t for w in [
            "сервер", "деплой", "deploy", "nginx", "docker", "ssl",
            "домен", "ssh", "настрой"
        ])
        is_simple_edit = any(w in t for w in [
            "исправь", "поправь", "измени", "обнови", "fix", "update",
            "замени", "добавь строк", "удали строк"
        ])

        # ── Complexity ───────────────────────────────────────────────────────
        if is_simple_edit and task_len < SIMPLE_TASK_MAX_LEN:
            complexity = TaskComplexity.SIMPLE
        elif task_len > COMPLEX_TASK_MIN_LEN or (is_web_design and is_marketing):
            complexity = TaskComplexity.COMPLEX
        else:
            complexity = TaskComplexity.MODERATE

        # ── Route selection ──────────────────────────────────────────────────
        if complexity == TaskComplexity.SIMPLE:
            route = TaskRoute.QUICK
            agents = ["observer"]
        elif is_marketing:
            route = TaskRoute.MARKETING
            agents = ["observer", "researcher_manus", "marketer", "seo_writer"]
        elif is_web_design and is_research:
            route = TaskRoute.RESEARCH
            agents = ["observer", "researcher_manus", "art_director", "developer", "assembler_manus"]
        elif is_web_design:
            route = TaskRoute.FULL
            agents = ["observer", "art_director", "developer", "assembler_manus"]
        elif is_coding or is_devops:
            route = TaskRoute.STANDARD
            agents = ["observer", "developer"]
        else:
            route = TaskRoute.STANDARD
            agents = ["observer", "director", "developer"]

        # ── Detect specialist needs ──────────────────────────────────────────
        if is_motion:
            agents.append("motion_dev")
        if is_seo and "seo_writer" not in agents:
            agents.append("seo_writer")
        if is_research and "researcher_manus" not in agents:
            agents.insert(1, "researcher_manus")

        # ── Task type string ─────────────────────────────────────────────────
        if is_web_design:
            task_type = "web_design"
        elif is_marketing:
            task_type = "marketing"
        elif is_coding:
            task_type = "coding"
        elif is_devops:
            task_type = "devops"
        elif is_seo:
            task_type = "text_content"
        elif is_research:
            task_type = "research"
        else:
            task_type = "general"

        return ObserverDecision(
            route=route,
            complexity=complexity,
            task_type=task_type,
            needs_research=is_research or (is_web_design and complexity == TaskComplexity.COMPLEX),
            needs_motion_dev=is_motion,
            needs_seo=is_seo,
            needs_marketing=is_marketing,
            estimated_agents=agents,
        )

    # ─── LLM-enhanced classification (Haiku) ──────────────────────────────────

    async def _llm_classify(self, task: str, base: ObserverDecision) -> ObserverDecision:
        """
        Use Haiku to refine classification for complex tasks.
        Only called when keyword classification returns COMPLEX.
        """
        prompt = f"""You are ARCANE Observer. Analyze this task and respond with JSON only.

Task: {task[:800]}

Respond with this exact JSON:
{{
  "task_type": "web_design|coding|marketing|devops|research|text_content|general",
  "complexity": "simple|moderate|complex",
  "needs_research": true/false,
  "needs_motion_dev": true/false,
  "needs_seo": true/false,
  "needs_marketing": true/false,
  "route": "quick|standard|full|research|marketing",
  "reasoning": "one sentence"
}}"""

        try:
            response = await self._llm.complete(
                model=OBSERVER_MODEL,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=200,
                temperature=0.0,
            )
            text = response.get("content", "").strip()
            # Extract JSON
            if "```" in text:
                text = text.split("```")[1].replace("json", "").strip()
            data = json.loads(text)

            # Merge LLM result with base
            base.task_type = data.get("task_type", base.task_type)
            base.needs_research = data.get("needs_research", base.needs_research)
            base.needs_motion_dev = data.get("needs_motion_dev", base.needs_motion_dev)
            base.needs_seo = data.get("needs_seo", base.needs_seo)
            base.needs_marketing = data.get("needs_marketing", base.needs_marketing)
            base.confidence = 0.95  # LLM-enhanced

            route_str = data.get("route", base.route.value)
            try:
                base.route = TaskRoute(route_str)
            except ValueError:
                pass

            logger.info("[Observer] LLM enhanced: %s", data.get("reasoning", ""))

        except Exception as e:
            logger.warning("[Observer] LLM classify parse error: %s", e)

        return base

    # ─── Watchdog ─────────────────────────────────────────────────────────────

    def watchdog_tick(self, run_id: str, project_id: str, agent: str = "manus") -> bool:
        """
        Called after each Manus iteration.
        Returns True if execution should continue, False if stuck (abort).
        """
        key = f"{project_id}:{run_id}"
        if key not in self._watchdogs:
            self._watchdogs[key] = WatchdogState(project_id=project_id, run_id=run_id)

        wd = self._watchdogs[key]

        if agent == "manus":
            wd.manus_iterations += 1
            if wd.manus_iterations >= MAX_MANUS_ITERATIONS:
                wd.stuck = True
                logger.error(
                    "[Observer/Watchdog] Manus STUCK: project=%s run=%s iterations=%d",
                    project_id, run_id, wd.manus_iterations
                )
                return False  # abort

        elif agent == "qa":
            wd.qa_rounds += 1
            if wd.qa_rounds >= MAX_QA_ROUNDS:
                logger.warning(
                    "[Observer/Watchdog] QA rounds limit reached: project=%s run=%s rounds=%d",
                    project_id, run_id, wd.qa_rounds
                )
                return False  # stop QA, accept result

        wd.last_progress_at = time.time()
        return True  # continue

    def watchdog_reset(self, run_id: str, project_id: str):
        """Reset watchdog state for a new run."""
        key = f"{project_id}:{run_id}"
        self._watchdogs.pop(key, None)

    def watchdog_get(self, run_id: str, project_id: str) -> WatchdogState | None:
        return self._watchdogs.get(f"{project_id}:{run_id}")

    # ─── JSON spec validation ─────────────────────────────────────────────────

    def validate_spec(self, spec_type: str, data: dict) -> tuple[bool, list[str]]:
        """
        Validate that a spec JSON has all required fields before passing to next agent.
        Returns (is_valid, missing_fields).
        """
        REQUIRED_FIELDS = {
            "design_spec": [
                "color_palette", "typography", "spacing", "layout_grid",
                "motion_spec", "tone"
            ],
            "positioning": [
                "target_audience", "usp", "tone_of_voice", "competitors",
                "key_messages"
            ],
            "seo_spec": [
                "primary_keywords", "lsi_keywords", "h1", "meta_description",
                "content_structure"
            ],
            "tech_spec": [
                "stack", "architecture", "api_endpoints", "database_schema"
            ],
            "motion_spec": [
                "scroll_animations", "page_transitions", "micro_interactions",
                "timing_defaults"
            ],
        }

        required = REQUIRED_FIELDS.get(spec_type, [])
        missing = [f for f in required if f not in data or not data[f]]

        if missing:
            logger.warning(
                "[Observer] Spec validation FAILED: type=%s missing=%s",
                spec_type, missing
            )
            return False, missing

        return True, []

    # ─── Budget enforcement ────────────────────────────────────────────────────

    def should_allow_expensive_agent(
        self,
        project_id: str,
        agent_role: str,
        estimated_cost: float,
        budget_limit: float | None = None,
    ) -> tuple[bool, str | None]:
        """
        Pre-flight check before launching an expensive agent (Opus/Sonnet).
        Returns (allowed, reason_if_blocked).
        """
        EXPENSIVE_ROLES = {"director", "art_director", "marketer", "writer", "developer", "motion_dev"}
        if agent_role not in EXPENSIVE_ROLES:
            return True, None  # cheap agents always allowed

        status, remaining = self._check_budget(project_id, budget_limit)

        if status == "stop":
            return False, (
                f"Бюджет исчерпан. Агент '{agent_role}' не запущен. "
                f"Пополните лимит проекта."
            )
        if status == "pause":
            return False, (
                f"Бюджет на паузе (95%+). Агент '{agent_role}' заблокирован. "
                f"Осталось: ${remaining:.4f}. Подтвердите продолжение."
            )
        if remaining is not None and estimated_cost > remaining:
            return False, (
                f"Недостаточно бюджета для '{agent_role}'. "
                f"Нужно: ~${estimated_cost:.4f}, осталось: ${remaining:.4f}."
            )

        return True, None
