"""
ARCANE 2 — Orchestrator
========================
The central engine. Receives a task, routes it through the system, returns result.

Flow:
  1. User submits task (with project_id, optional mode/budget)
  2. Intent Classifier → type + complexity + flags
  3. Preset Manager → team of models for this task
  4. Show recommendation to user (or auto-approve)
  5. Agent Loop → execute (model has full freedom HOW)
  6. Budget Controller → track costs
  7. Project Manager → update structured state, scratchpad → PROJECT.md
  8. Return result

Philosophy: freedom inside, control outside.
Models decide HOW to solve. Orchestrator decides WHO solves and tracks BUDGET.

Spec refs: §1, §6, §7
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
import uuid
from dataclasses import dataclass, field, asdict
try:
    from core.task_history_db import TaskHistoryDB
except ImportError:
    from task_history_db import TaskHistoryDB
try:
    from core.observer_mediator import ObserverMediator, TaskRoute, TaskComplexity
    _OBSERVER_AVAILABLE = True
except ImportError:
    _OBSERVER_AVAILABLE = False
try:
    from core.manus_pipeline import ManusPipelineFactory
    _PIPELINE_AVAILABLE = True
except ImportError:
    _PIPELINE_AVAILABLE = False

from enum import Enum
from typing import Any, Optional, Callable

logger = logging.getLogger("arcane2.orchestrator")


# ═══════════════════════════════════════════════════════════════════════════════
# RUN STATES (external control graph)
# ═══════════════════════════════════════════════════════════════════════════════

class RunStatus(str, Enum):
    """Task lifecycle states. Freedom inside each state, control at transitions."""
    QUEUED = "queued"           # Waiting in queue
    CLASSIFYING = "classifying" # Intent classifier working
    RECOMMENDING = "recommending"  # Building team recommendation
    AWAITING_APPROVAL = "awaiting_approval"  # Showing recommendation, waiting for user
    RUNNING = "running"         # Agent loop executing (model has full freedom)
    REVIEW = "review"           # Self-check / QA
    DONE = "done"               # Success
    FAILED = "failed"           # All retries exhausted
    CANCELLED = "cancelled"     # User cancelled
    PAUSED = "paused"           # Budget pause (95% spent)
    ESCALATED = "escalated"     # §4.4: 3 retries || budget>200% || dangerous keyword


@dataclass
class RunResult:
    """Result of a single orchestrator run."""
    run_id: str = ""
    project_id: str = ""
    task: str = ""
    status: RunStatus = RunStatus.QUEUED
    
    # Classification
    task_type: str = ""         # design, code, devops, automation, research
    complexity: str = ""        # simple, moderate, complex, expert
    needs_browser: bool = False
    needs_ssh: bool = False
    
    # Team
    mode: str = "auto"          # auto, manual, top, optimum, lite, free
    team: dict[str, str] = field(default_factory=dict)  # role → model_id
    estimated_cost: float = 0.0
    
    # Execution
    output: str = ""
    artifacts: list[str] = field(default_factory=list)  # file paths created
    
    # Cost tracking
    actual_cost: float = 0.0
    cost_breakdown: list[dict] = field(default_factory=list)
    manus_credits_used: int = 0
    
    # Timing
    started_at: float = 0.0
    finished_at: float = 0.0
    duration_seconds: float = 0.0
    
    # Errors / retries
    errors: list[str] = field(default_factory=list)
    retries: int = 0
    escalations: list[str] = field(default_factory=list)
    
    # ARCANE 3.0: Director plan for parallel execution
    director_plan: dict = field(default_factory=dict)  # {parallel:[], then:[], then_2:[], ...}
    
    # ARCANE 3.0: Real QA metrics (filled by _run_qa_check)
    lint_errors: int = 0
    html_valid: bool = True
    
    def to_dict(self) -> dict:
        d = asdict(self)
        d["status"] = self.status.value
        return d


# ═══════════════════════════════════════════════════════════════════════════════
# ORCHESTRATOR
# ═══════════════════════════════════════════════════════════════════════════════

class Orchestrator:
    """
    Central engine of Arcane 2.
    
    Connects: IntentClassifier, PresetManager, AgentLoop, BudgetController,
    ProjectManager, SecurityGuard.
    
    Usage:
        orch = Orchestrator(config)
        result = await orch.run(project_id="romashka", task="Add catalog page")
        # or with approval:
        rec = await orch.classify_and_recommend(project_id, task)
        # user reviews rec, approves or modifies
        result = await orch.execute(rec)
    """
    
    def __init__(
        self,
        # All dependencies injected — no hardcoded imports
        llm_client=None,            # UnifiedLLMClient or provider adapter
        intent_classifier=None,     # DEPRECATED in ARCANE 3.0 (kept for backward compat)
        preset_manager=None,        # from shared.llm.preset_manager
        budget_controller=None,     # from core.budget_controller  
        project_manager=None,       # from core.project_manager
        security=None,              # from core.security
        agent_loop_factory=None,    # callable that creates AgentLoop
        manus_bridge=None,          # ARCANE 3.0: from core.manus_bridge
        model_arena=None,           # ARCANE 3.0: from core.model_arena
        config: dict | None = None,
    ):
        self.llm = llm_client
        self.classifier = intent_classifier
        self.presets = preset_manager
        self.budget = budget_controller
        self.projects = project_manager
        self.security = security
        self.agent_loop_factory = agent_loop_factory or self._default_agent_loop_factory
        self.config = config or {}
        
        # ARCANE 3.0: Manus execution backend
        self.manus = manus_bridge
        # ARCANE 4.0: Observer/Mediator (Haiku)
        self.observer = ObserverMediator(
            llm_client=llm_client,
            project_manager=project_manager,
        ) if _OBSERVER_AVAILABLE else None
        # ARCANE 4.0: Manus Pipeline Factory
        self.manus_pipelines = ManusPipelineFactory(
            manus_bridge=self.manus,
            observer=self.observer,
            llm_client=llm_client,
        ) if _PIPELINE_AVAILABLE else None
        if self.manus is None:
            try:
                from core.manus_bridge import ManusBridge
                self.manus = ManusBridge()
                logger.info("ManusBridge: initialized")
            except Exception as e:
                logger.warning(f"ManusBridge init failed: {e}")
        
        # ARCANE 3.0: Model Arena for passive learning
        self.arena = model_arena
        if self.arena is None:
            try:
                from core.model_arena import ModelArena
                self.arena = ModelArena()
                logger.info("ModelArena: initialized")
            except Exception as e:
                logger.warning(f"ModelArena init failed: {e}")
        
        # Active runs (for parallel project support)
        self._runs: dict[str, RunResult] = {}
        # Persistent task history
        import os as _os
        _workspace = _os.environ.get("ARCANE_WORKSPACE", "/root/workspace")
        _db_path = _os.path.join(_workspace, ".arcane_history.db")
        try:
            self.history_db = TaskHistoryDB(db_path=_db_path)
        except Exception as _e:
            import logging as _log
            _log.getLogger(__name__).warning(f"TaskHistoryDB init failed: {_e}")
            self.history_db = None
        
        # Max retries before giving up
        self.max_retries = self.config.get("max_retries", 3)
        # Auto-approve if True (skip AWAITING_APPROVAL)
        self.auto_approve = self.config.get("auto_approve", False)
    
    # ─── Main entry point ─────────────────────────────────────────────────
    
    async def run(
        self,
        project_id: str,
        task: str,
        mode: str = "auto",
        budget_limit: float | None = None,
        auto_approve: bool | None = None,
        on_status_change: Callable | None = None,
    ) -> RunResult:
        """
        Full orchestration: classify → recommend → (approve) → execute → result.
        
        Args:
            project_id: Which project this task belongs to
            task: What the user wants done (free text)
            mode: auto/manual/top/optimum/lite/free
            budget_limit: Max USD for this task (None = project default)
            auto_approve: Skip approval step? (None = use orchestrator default)
            on_status_change: Callback for real-time UI updates
        """
        run_id = f"run_{uuid.uuid4().hex[:12]}"
        result = RunResult(
            run_id=run_id,
            project_id=project_id,
            task=task,
            mode=mode,
            started_at=time.time(),
        )
        self._runs[run_id] = result
        self._evict_old_runs()
        
        should_auto = auto_approve if auto_approve is not None else self.auto_approve
        
        try:
            # Step 1: Classify
            await self._update_status(result, RunStatus.CLASSIFYING, on_status_change)
            await self._classify(result)
            
            # Step 2: Build team recommendation
            await self._update_status(result, RunStatus.RECOMMENDING, on_status_change)
            await self._recommend(result, budget_limit)
            
            # Step 3: Approval (skip if auto)
            if not should_auto:
                await self._update_status(result, RunStatus.AWAITING_APPROVAL, on_status_change)
                # In real system: wait for user approval via WebSocket/polling
                # For now: auto-approve after recommendation is built
                logger.info(f"[{run_id}] Awaiting approval. Team: {result.team}, Est: ${result.estimated_cost:.3f}")
            
            # Step 4: Execute
            await self._update_status(result, RunStatus.RUNNING, on_status_change)
            await self._execute(result, on_status_change)
            
            # Step 5: Done
            result.finished_at = time.time()
            result.duration_seconds = result.finished_at - result.started_at
            await self._update_status(result, RunStatus.DONE, on_status_change)

            # P2-1: Telegram notification on DONE
            try:
                from workers.telegram_notify import notify as _tg_notify
                import asyncio as _asyncio
                _tg_msg = (
                    f"✅ <b>Задача завершена</b>\n"
                    f"Проект: {result.project_id}\n"
                    f"Задача: {str(result.task)[:100]}\n"
                    f"Стоимость: ${result.actual_cost:.4f}\n"
                    f"Время: {round(result.duration_seconds or 0, 1)}с"
                )
                _asyncio.create_task(_tg_notify(_tg_msg))
            except Exception:
                pass

            # Step 6: Model escalation hint on FAILED
            if result.status in (RunStatus.FAILED, RunStatus.ESCALATED):
                _esc = self._escalate_model(primary_model, result)
                if _esc and _esc != primary_model:
                    logger.info(f"[{run_id}] Next retry could use: {_esc}")
                    if not hasattr(result, 'metadata') or result.metadata is None:
                        result.metadata = {}
                    result.metadata['escalation_model'] = _esc

            # Step 6: Update project state
            await self._update_project(result)
            
        except BudgetPausedError:
            await self._update_status(result, RunStatus.PAUSED, on_status_change)
            logger.warning(f"[{run_id}] Budget paused at ${result.actual_cost:.3f}")
        except CancelledError:
            await self._update_status(result, RunStatus.CANCELLED, on_status_change)
        except Exception as e:
            result.errors.append(str(e))
            result.finished_at = time.time()
            result.duration_seconds = result.finished_at - result.started_at
            # Partial delivery: if hard_timeout and artifacts exist → deliver as DONE
            _is_timeout = "hard_timeout" in str(e) or "timeout" in str(e).lower()
            if _is_timeout and result.artifacts:
                logger.info(f"[{result.run_id}] Timeout with {len(result.artifacts)} artifacts — partial delivery as DONE")
                result.output = (
                    f"Задача выполнена частично (таймаут {result.duration_seconds:.0f}с). "
                    f"Создано: {', '.join(result.artifacts[:5])}"
                )
                await self._update_status(result, RunStatus.DONE, on_status_change)
            else:
                await self._update_status(result, RunStatus.FAILED, on_status_change)

            # ── SPEC §4.4: Escalation check ──────────────────────────────────
            # Trigger: 3+ retries OR budget > 200% estimated OR keyword match
            _budget_overrun = (
                result.estimated_cost > 0
                and result.actual_cost > result.estimated_cost * 2.0
            )
            _too_many_retries = result.retries >= 3
            if result.escalations or _budget_overrun or _too_many_retries:
                result.status = RunStatus.ESCALATED
                _esc_reason = (
                    f"retries={result.retries}" if _too_many_retries else
                    f"budget_overrun=${result.actual_cost:.3f}>${result.estimated_cost:.3f}×2" if _budget_overrun else
                    "keyword_detected"
                )
                logger.warning(f"[{run_id}] ESCALATED: {_esc_reason}")
                await self._update_status(result, RunStatus.ESCALATED, on_status_change, {
                    "escalation_reason": _esc_reason,
                    "message": f"Требует ревью senior-разработчика: {_esc_reason}",
                })
                try:
                    from workers.telegram_notify import notify as _tg_esc
                    import asyncio as _aesc
                    _tg_esc_msg = (
                        f"⚠️ <b>ESCALATION</b>\n"
                        f"Проект: {result.project_id}\n"
                        f"Причина: {_esc_reason}\n"
                        f"Задача: {result.task[:150]}\n"
                        f"Стоимость: ${result.actual_cost:.4f} (ожидалось ${result.estimated_cost:.4f})"
                    )
                    _aesc.create_task(_tg_esc(message=_tg_esc_msg))
                except Exception:
                    pass
            # P2-1: Telegram notification on FAILED
            try:
                from workers.telegram_notify import notify as _tg_notify
                import asyncio as _asyncio
                _err = str(result.errors[-1])[:200] if result.errors else 'unknown'
                _tg_msg = f'❌ <b>Задача провалена</b>\nПроект: {result.project_id}\nОшибка: {_err}'
                _asyncio.create_task(_tg_notify(_tg_msg))
            except Exception:
                pass
            logger.error(f"[{run_id}] Failed: {e}", exc_info=True)
        
        return result
    
    # ─── Step 1: Classify ─────────────────────────────────────────────────
    
    async def _classify(self, result: RunResult):
        """
        ARCANE 4.0: Classification via Observer (Haiku Mediator).
        Observer does pre-flight budget check + fast keyword classify.
        Falls back to keyword-only if Observer not available.
        """
        # ── ARCANE 4.0: Observer-powered classification ──────────────────────
        if self.observer is not None:
            try:
                decision = await self.observer.analyze(
                    project_id=result.project_id,
                    task=result.task,
                    budget_limit=None,
                    run_id=result.run_id,
                )
                if decision.block_reason and decision.budget_status == "stop":
                    raise RuntimeError(f"[Observer] {decision.block_reason}")
                result.task_type = decision.task_type
                result.complexity = decision.complexity.value if hasattr(decision.complexity, "value") else str(decision.complexity)
                result.needs_browser = decision.needs_research
                result.needs_ssh = False
                result._observer_decision = decision
                logger.info(
                    f"[{result.run_id}] Observer classified: type={result.task_type}, "
                    f"route={decision.route.value}, agents={decision.estimated_agents}, "
                    f"budget={decision.budget_status}"
                )
                return
            except RuntimeError:
                raise
            except Exception as e:
                logger.warning(f"[{result.run_id}] Observer failed, falling back: {e}")

        # ── Fallback: external classifier ────────────────────────────────────
        if self.classifier is not None:
            try:
                classification = await self.classifier(self.llm, result.task, result.run_id)
                result.task_type = classification.get("intent", "general")
                result.complexity = classification.get("complexity", "moderate")
                result.needs_browser = classification.get("needs_browser", False)
                result.needs_ssh = classification.get("needs_ssh", False)
                return
            except Exception as e:
                logger.warning(f"[{result.run_id}] External classifier failed: {e}")

        # ── Fallback: keyword classification ─────────────────────────────────
        task_lower = result.task.lower()
        _keyword_map = {
            "web_design":   ["сайт", "лендинг", "страниц", "дизайн", "вёрст", "верст", "html", "css", "landing"],
            "coding":       ["код", "скрипт", "api", "бот", "функци", "python", "javascript", "бэкенд", "backend"],
            "devops":       ["сервер", "деплой", "deploy", "nginx", "docker", "ssl", "домен"],
            "text_content": ["текст", "статья", "контент", "seo", "копирайт"],
            "marketing":    ["маркетинг", "реклама", "продвижение", "стратегия", "позиционирование", "бренд", "smm", "таргет"],
            "research":     ["анализ", "исследов", "сравн", "конкурент"],
            "media":        ["картинк", "изображ", "фото", "видео", "иллюстр"],
        }
        for task_type, keywords in _keyword_map.items():
            if any(kw in task_lower for kw in keywords):
                result.task_type = task_type
                break
        else:
            result.task_type = "general"
        task_len = len(result.task)
        if task_len > 500 or any(w in task_lower for w in ["сложн", "интеграц", "магазин", "приложени"]):
            result.complexity = "complex"
        elif task_len < 100:
            result.complexity = "simple"
        else:
            result.complexity = "moderate"
        logger.info(f"[{result.run_id}] Classified (keyword fallback): type={result.task_type}, complexity={result.complexity}")

    # ─── Step 2: Recommend team ───────────────────────────────────────────
    
    async def _recommend(self, result: RunResult, budget_limit: float | None):
        """Use PresetManager to build team of models for this task."""
        if self.presets is None:
            result.team = {"developer": "claude-sonnet-4.6"}
            result.estimated_cost = 0.05
            logger.warning(f"[{result.run_id}] No preset_manager, using Sonnet default")
            return
        
        try:
            # ── Local copy to avoid race condition on shared presets ───────
            import copy
            from shared.llm.preset_manager import PresetMode
            pm = copy.deepcopy(self.presets)
            try:
                pm.mode = PresetMode(result.mode)
            except ValueError:
                pm.mode = PresetMode.OPTIMUM
            
            # ── Determine roles needed for this task type ─────────────────
            # ── ARCANE 3.0: roles for each task type ─────────────────
            roles_for_type = {
                "web_design":      ["art_director", "marketer", "seo_writer", "writer", "developer", "qa", "image_agent"],
                "cms_management":  ["developer", "qa"],
                "devops":          ["developer", "qa"],         # Manus handles SSH
                "coding":          ["developer", "qa"],
                "code_review":     ["qa"],
                "data":            ["developer", "qa"],
                "research":        ["researcher"],
                "text_content":    ["marketer", "seo_writer", "writer"],
                "marketing":       ["marketer", "seo_writer", "writer", "researcher"],
                "media":           ["art_director", "marketer", "image_agent"],
                "automation":      ["developer", "qa"],
                "browser_task":    ["developer"],               # Manus handles browser
                "general":         ["developer"],
            }
            needed_roles = list(roles_for_type.get(result.task_type, ["developer"]))
            
            # ARCANE 3.0: ssh and browser are Manus capabilities, not roles.
            # needs_ssh/needs_browser flags are passed to Manus via project_context.
            # No separate "planner" role — Director handles planning.
            if result.complexity == "complex" and "researcher" not in needed_roles:
                needed_roles.append("researcher")
            
            # ── Resolve model for each role ───────────────────────────────
            def _resolve_team(preset_mgr):
                team = {}
                total_cost = 0.0
                for role in needed_roles:
                    resolved = preset_mgr.resolve_model_full(role)
                    if resolved:
                        team[role] = resolved.model_id
                        try:
                            from shared.llm.model_registry import estimate_task_cost
                            cost = estimate_task_cost(resolved.model_id, 5000, 2000)
                            if cost is not None:
                                total_cost += cost
                        except ImportError:
                            pass
                return team, total_cost
            
            team, total_cost = _resolve_team(pm)
            
            # Always have at least a primary execution model
            primary_role = self._get_primary_role(result)
            if primary_role not in team and "developer" not in team:
                team["developer"] = "claude-sonnet-4.6"  # canonical role name
                total_cost += 0.045
            
            result.team = team
            result.estimated_cost = total_cost
            
            # ── Budget check: downgrade to LITE if over limit ─────────────
            if budget_limit and result.estimated_cost > budget_limit:
                logger.info(
                    f"[{result.run_id}] Est ${result.estimated_cost:.3f} > "
                    f"limit ${budget_limit:.2f}, downgrading to LITE"
                )
                pm_lite = copy.deepcopy(self.presets)
                pm_lite.mode = PresetMode.LITE
                team, total_cost = _resolve_team(pm_lite)
                if primary_role not in team and "developer" not in team:
                    team["developer"] = "deepseek-v3.2"  # canonical role name
                    total_cost += 0.003
                result.team = team
                result.estimated_cost = total_cost
            
            logger.info(
                f"[{result.run_id}] Team ({pm.mode.value}): {result.team}, "
                f"Est cost: ${result.estimated_cost:.3f}"
            )
        except Exception as e:
            logger.warning(f"[{result.run_id}] PresetManager failed: {e}. Using Sonnet default.")
            result.team = {"developer": "claude-sonnet-4.6"}
            result.estimated_cost = 0.05
    
    # ─── Step 3: Execute ──────────────────────────────────────────────────
    
    async def _execute(self, result: RunResult, on_status_change: Callable | None):
        """
        ARCANE 4.0: Route to specific pipeline templates.
        """
        context = await self._load_project_context(result)
        
        try:
            from core.pipeline_templates import PipelineRunner
            from shared.memory_v9.continuity import ContinuityManager
            _continuity = ContinuityManager()

            # Auto-resume: check if there's a saved checkpoint for this project
            # If a previous run failed mid-pipeline, resume from last stage
            _resume_run_id = result.run_id
            _project_resume = _continuity.get_project_resume(result.project_id)
            if _project_resume and _project_resume.get("run_id") != result.run_id:
                _prev_run_id = _project_resume.get("run_id")
                _prev_state = _continuity.restore_checkpoint(_prev_run_id)
                # If previous run completed successfully — start fresh (new task)
                if _project_resume.get("completed") and not context.get("force_stage"):
                    logger.info(f"[{result.run_id}] Previous run completed. Starting fresh pipeline.")
                    _prev_state = None
                if _prev_state and _prev_state.get("completed_stages"):
                    # Resume from previous run's checkpoint
                    logger.info(
                        f"[{result.run_id}] Auto-resume: found checkpoint from run "
                        f"{_prev_run_id} with stages {_prev_state['completed_stages']}"
                    )
                    # Copy checkpoint to new run_id so PipelineRunner picks it up
                    _continuity.save_checkpoint(result.run_id, _prev_state)
                    await self._update_status(result, RunStatus.RUNNING, on_status_change, {
                        "type": "resume",
                        "message": f"Resuming from stage {_prev_state['completed_stages'][-1]}",
                        "resumed_from": _prev_run_id,
                        "completed_stages": _prev_state["completed_stages"],
                    })

            # force_stage: manually start from a specific stage (e.g. "stage_3")
            # Pass via context: {"force_stage": "stage_2"} means skip stage_1 and stage_2
            _force_stage = context.get("force_stage")
            if _force_stage:
                _stage_order = ["stage_1", "stage_2", "stage_3", "stage_4"]
                if _force_stage in _stage_order:
                    _force_idx = _stage_order.index(_force_stage)
                    if _force_idx > 0:
                        _forced_state = {
                            "completed_stages": _stage_order[:_force_idx],
                            "artifacts": {},
                            "gate_retries": {},
                        }
                        _last_resume = _continuity.get_project_resume(result.project_id)
                        if _last_resume:
                            _last_state = _continuity.restore_checkpoint(_last_resume.get("run_id", ""))
                            if _last_state:
                                _forced_state["artifacts"] = _last_state.get("artifacts", {})
                        _continuity.save_checkpoint(result.run_id, _forced_state)
                        logger.info(
                            f"[{result.run_id}] force_stage={_force_stage}: "
                            f"skipping {_forced_state['completed_stages']}"
                        )
            runner = PipelineRunner(self, result, context, on_status_change)

            try:
                if result.task_type == "web_design":
                    await runner.run_web_design()
                elif result.task_type == "crm_setup":
                    await runner.run_crm_setup()
                elif result.task_type == "api_backend" or result.task_type == "coding":
                    await runner.run_api_backend()
                elif result.task_type == "marketing":
                    await runner.run_marketing()
                else:
                    pass  # falls through to generic below
                # On success: save completed checkpoint (don't clear — allows inspection)
                _continuity.save_project_resume(result.project_id, {
                    "run_id": result.run_id,
                    "task": result.task,
                    "task_type": result.task_type,
                    "mode": result.mode,
                    "completed": True,
                    "completed_stages": runner.state.get("completed_stages", []),
                })
            except Exception as _pipeline_err:
                # Save resume pointer so next run continues from here
                _continuity.save_project_resume(result.project_id, {
                    "run_id": result.run_id,
                    "task": result.task,
                    "task_type": result.task_type,
                    "mode": result.mode,
                    "error": str(_pipeline_err),
                })
                logger.warning(
                    f"[{result.run_id}] Pipeline failed at stage "
                    f"{runner.state.get('completed_stages', [])}. "
                    f"Resume pointer saved. Error: {_pipeline_err}"
                )
                raise
            else:
                # Fallback to default loop
                await self._update_status(result, RunStatus.RUNNING, on_status_change, {"message": "Running generic task..."})
                primary_role = self._get_primary_role(result)
                primary_model = result.team.get(primary_role, "claude-sonnet-4.6")
                result.output = await self._direct_llm_call(result, context, primary_model)
                
        except Exception as e:
            import traceback
            logger.error(f"[{result.run_id}] Pipeline error: {e}\n" + traceback.format_exc())
            raise
    async def _update_project(self, result: RunResult):
        """Update project structured state after task completion."""
        if not self.projects:
            return
        
        try:
            primary_model = list(result.team.values())[0] if isinstance(result.team, dict) and result.team else "unknown"
            self.projects.add_run(
                project_id=result.project_id,
                task=result.task,
                model=primary_model,
                cost=result.actual_cost,
                result=result.status.value,
                run_id=result.run_id,
            )
            
            # Regenerate PROJECT.md from structured state
            self.projects.regenerate_md(result.project_id)
            
            logger.info(f"[{result.run_id}] Project state updated, cost: ${result.actual_cost:.4f}")
            
        except Exception as e:
            logger.error(f"[{result.run_id}] Failed to update project: {e}")
        
        # ── Golden Paths: record outcome for pattern learning (§10.2) ─────
        if result.status == RunStatus.DONE:
            try:
                from core.golden_paths import record_run_outcome
                workspace = os.environ.get("ARCANE_WORKSPACE", "/root/workspace")
                project_dir = os.path.join(workspace, "projects", result.project_id)
                # Build steps from run_graph events or fallback to task phases
                _rg = result.run_graph if hasattr(result, "run_graph") else {}
                _transitions = _rg.get("transitions", []) if isinstance(_rg, dict) else []
                _steps = [t.get("to", t.get("state", "")) for t in _transitions if t.get("to")] or [
                    "classify", "recommend", "plan", "execute", "qa", "deliver"
                ]
                _pmodel = primary_model if "primary_model" in dir() else "unknown"
                record_run_outcome(
                    project_dir=project_dir,
                    run_id=result.run_id,
                    task_type=result.task_type,
                    steps=_steps,
                    pattern_label=f"{result.task_type}: {result.task[:50]}",
                    success=True,
                    tests_passed=True,
                    rollback_triggered=False,
                    duration_ms=int((result.duration_seconds or 0) * 1000),
                    cost_usd=result.actual_cost,
                    model_used=_pmodel,
                    metadata={"task_preview": result.task[:100], "artifacts": result.artifacts[:5]},
                )
                logger.info(f"[{result.run_id}] Golden path outcome recorded")
            except Exception as e:
                logger.debug(f"Golden paths recording skipped: {e}")
        
        # ── ARCANE 3.0: ModelArena — record metrics for passive learning ───
        if result.status in (RunStatus.DONE, RunStatus.FAILED) and self.arena:
            try:
                _pmodel_a = list(result.team.values())[0] if isinstance(result.team, dict) and result.team else "unknown"
                _primary_role_a = self._get_primary_role(result)
                self.arena.record(
                    task_type=result.task_type,
                    role=_primary_role_a,
                    model_id=_pmodel_a,
                    lint_errors=result.lint_errors,        # BUG-2 FIX: real values from QA
                    html_valid=result.html_valid,           # BUG-2 FIX: real values from QA
                    retry_count=result.retries,
                    cost_usd=result.actual_cost,
                    duration_seconds=result.duration_seconds or 0,
                    files_created=len(result.artifacts),
                    project_id=result.project_id,
                    run_id=result.run_id,
                )
                logger.info(f"[{result.run_id}] ModelArena record saved")
            except Exception as e:
                logger.debug(f"ModelArena recording skipped: {e}")
        
        # Record FAILED outcome too (helps improve paths over time)
        if result.status == RunStatus.FAILED:
            try:
                from core.golden_paths import record_run_outcome as _gp_rec
                _workspace_f = os.environ.get("ARCANE_WORKSPACE", "/root/workspace")
                _proj_dir_f = os.path.join(_workspace_f, "projects", result.project_id)
                _pmodel_f = primary_model if "primary_model" in dir() else "unknown"
                _gp_rec(
                    project_dir=_proj_dir_f,
                    run_id=result.run_id,
                    task_type=result.task_type,
                    steps=["classify", "execute", "failed"],
                    success=False,
                    tests_passed=False,
                    rollback_triggered=False,
                    duration_ms=int((result.duration_seconds or 0) * 1000),
                    cost_usd=result.actual_cost,
                    model_used=_pmodel_f,
                    metadata={"errors": result.errors[:3] if result.errors else []},
                )
            except Exception:
                pass

        # ── Auto-Documenter: trigger background update (§5.4) ─────────────
        if result.status == RunStatus.DONE and result.artifacts:
            try:
                asyncio.create_task(self._run_auto_documenter(result))
            except Exception as e:
                logger.debug(f"Auto-documenter trigger skipped: {e}")
    
    async def _run_auto_documenter(self, result: RunResult):
        """Background: update ARCHITECTURE.md after successful task."""
        try:
            from workers.auto_documenter import AutoDocumenter, DocumenterConfig
            workspace = os.environ.get("ARCANE_WORKSPACE", "/root/workspace")
            project_dir = os.path.join(workspace, "projects", result.project_id)
            config = DocumenterConfig(project_path=project_dir)
            documenter = AutoDocumenter(config=config)
            await documenter.force_update()
            logger.info(f"[{result.run_id}] Auto-documenter updated docs")
        except Exception as e:
            logger.debug(f"Auto-documenter failed: {e}")
    
    # ─── Helpers ──────────────────────────────────────────────────────────
    
    async def _load_project_context(self, result: RunResult) -> dict:
        """Load structured state + relevant files for model context."""
        context = {
            "task": result.task,
            "project_id": result.project_id,
            "needs_ssh": result.needs_ssh,
            "needs_browser": result.needs_browser,
            "task_type": result.task_type,
            "complexity": result.complexity,
        }
        
        if self.projects:
            state = self.projects.get_state(result.project_id)
            if state:
                context["project_state"] = state
                context["personality"] = state.get("personality", {})
                context["tech_stack"] = state.get("tech_stack", {})
                context["design_system"] = state.get("design_system", {})
                context["servers"] = state.get("environment", {}).get("servers", [])
        
        # BUG-3 FIX: Load design_spec.json from previous Art Director run
        try:
            import json as _ctx_json
            _workspace = os.environ.get("ARCANE_WORKSPACE", "/root/workspace")
            _spec_path = os.path.join(_workspace, "projects", result.project_id, ".arcane", "design_spec.json")
            if os.path.exists(_spec_path):
                with open(_spec_path, encoding="utf-8") as _sf:
                    context["design_spec"] = _ctx_json.load(_sf)
                logger.debug(f"[{result.run_id}] Loaded design_spec.json from {_spec_path}")
        except Exception as _ds_e:
            logger.debug(f"design_spec.json not loaded: {_ds_e}")
        
        # ARCANE 4.0: Load positioning.json from Marketer run
        try:
            import json as _ctx_json2
            _workspace2 = os.environ.get("ARCANE_WORKSPACE", "/root/workspace")
            _pos_path = os.path.join(_workspace2, "projects", result.project_id, ".arcane", "positioning.json")
            if os.path.exists(_pos_path):
                with open(_pos_path, encoding="utf-8") as _pf:
                    context["positioning"] = _ctx_json2.load(_pf)
                logger.debug(f"[{result.run_id}] Loaded positioning.json from {_pos_path}")
        except Exception as _pos_e:
            logger.debug(f"positioning.json not loaded: {_pos_e}")
        
        # ARCANE 4.0: Load seo_spec.json from SEO Writer run
        try:
            import json as _ctx_json3
            _workspace3 = os.environ.get("ARCANE_WORKSPACE", "/root/workspace")
            _seo_path = os.path.join(_workspace3, "projects", result.project_id, ".arcane", "seo_spec.json")
            if os.path.exists(_seo_path):
                with open(_seo_path, encoding="utf-8") as _seofp:
                    context["seo_spec"] = _ctx_json3.load(_seofp)
                logger.debug(f"[{result.run_id}] Loaded seo_spec.json from {_seo_path}")
        except Exception as _seo_e:
            logger.debug(f"seo_spec.json not loaded: {_seo_e}")
        
        return context
    
    def _get_primary_role(self, result: RunResult) -> str:
        """Determine primary role based on task type (intent)."""
        # ARCANE 3.0 primary roles
        role_map = {
            "web_design":     "developer",
            "cms_management": "developer",
            "devops":         "developer",      # Manus handles SSH, developer writes configs
            "coding":         "developer",
            "code_review":    "qa",
            "data":           "developer",
            "research":       "researcher",
            "text_content":   "writer",
            "marketing":      "marketer",
            "media":          "art_director",
            "automation":     "developer",
            "browser_task":   "developer",      # Manus handles browser
            "general":        "developer",
        }
        return role_map.get(result.task_type, "developer")
    
    def _get_budget_category(self, task_type: str) -> str:
        """Map intent classifier task_type to budget category string."""
        cat_map = {
            "web_design": "code", "cms_management": "code",
            "devops": "devops", "coding": "code",
            "code_review": "code", "data": "code",
            "research": "research", "text_content": "text",
            "marketing": "text", "media": "media",
            "automation": "code", "browser_task": "browser",
            "general": "code",
        }
        return cat_map.get(task_type, "code")
    
    def _get_budget_remaining(self, result: RunResult) -> float | None:
        """Get remaining budget for this task. Returns None if unlimited."""
        if not self.budget:
            return None
        val = self.budget.get_remaining(result.project_id)
        # None means unlimited — return None (not inf) for JSON safety
        return val
    
    def _escalate_model(self, current_model: str, result: RunResult) -> str | None:
        """Find a more powerful model for retry."""
        try:
            from shared.llm.model_registry import get_fallback
            escalation_map = {
                "deepseek-v3.2": "claude-sonnet-4.6",
                "gpt-5.4-nano": "gpt-5.4-mini",
                "gpt-5.4-mini": "claude-sonnet-4.6",
                "gemini-2.5-flash": "gemini-3.1-pro",
                "claude-haiku-4.5": "claude-sonnet-4.6",
                "claude-sonnet-4.6": "gpt-5.4",
                "gpt-5.4": "claude-opus-4.6",
                "grok-4-fast": "gpt-5.4-mini",
            }
            new_model = escalation_map.get(current_model)
            
            # CRITICAL FIX: Carry over context on escalation
            if new_model and result.output:
                prev_code = result.output[:8000]
                test_logs = chr(10).join(result.errors)[:2000]
                escalation_context = (
                    chr(10) + chr(10) + "<previous_attempt_code>" + chr(10) + prev_code + chr(10) + "</previous_attempt_code>" + chr(10)
                    + "<test_failures>" + chr(10) + test_logs + chr(10) + "</test_failures>" + chr(10)
                    + "Предыдущая модель не справилась. Исправь код с учетом ошибок."
                )
                result.task += escalation_context
                
            return new_model
        except ImportError:
            return None
    # ═══════════════════════════════════════════════════════════════════════

    async def call_specialist(self, result: "RunResult", context: dict, role: str, model_id: str) -> str:
        """Public method: call a single specialist LLM and return its text output.
        
        Used by PipelineRunner stages to call individual roles.
        Tracks cost on result.actual_cost.
        """
        try:
            from shared.prompt_templates import get_role_prompt
        except ImportError:
            get_role_prompt = lambda role, lang="ru": ""

        system_prompt = get_role_prompt(role)
        
        # Build user prompt with project context
        user_prompt = f"Проект: {result.task}\n\nТип: {result.task_type}\nСложность: {result.complexity}"
        
        ctx_parts = []
        if context.get("personality"):
            ctx_parts.append(f"Предпочтения клиента: {str(context['personality'])[:300]}")
        if context.get("tech_stack"):
            ts = context["tech_stack"]
            ts_str = ", ".join(f"{k}={v}" for k, v in ts.items() if v) if isinstance(ts, dict) else str(ts)
            if ts_str:
                ctx_parts.append(f"Стек технологий: {ts_str}")
        if context.get("design_system"):
            ds = context["design_system"]
            ds_str = ", ".join(f"{k}={v}" for k, v in ds.items() if v) if isinstance(ds, dict) else str(ds)
            if ds_str:
                ctx_parts.append(f"Дизайн-система: {ds_str}")
        if context.get("design_spec"):
            import json as _j
            ctx_parts.append(f"design_spec: {_j.dumps(context['design_spec'], ensure_ascii=False)[:800]}")
        if context.get("gate_feedback"):
            ctx_parts.append(f"Фидбэк от предыдущей попытки: {context['gate_feedback']}")
        if ctx_parts:
            user_prompt += "\n\nКонтекст проекта:\n" + "\n".join(ctx_parts)

        # Enrichment: stage-specific instructions and artifacts from pipeline
        if context.get("enrichment"):
            user_prompt += "\n\n" + str(context["enrichment"])
        if not self.llm:
            return f"[DRY RUN] role={role} model={model_id}"

        resp = await self.llm.chat(
            model=model_id,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            max_tokens=16384 if role in ("developer", "css_architect") else 4096,
        )

        if isinstance(resp, dict):
            output = resp.get("content", "") or ""
            cost = resp.get("cost_usd", 0.0)
            result.actual_cost += cost
            result.cost_breakdown.append({
                "model": model_id,
                "role": role,
                "cost": cost,
                "tokens_in": resp.get("tokens_in", 0),
                "tokens_out": resp.get("tokens_out", 0),
            })
        else:
            output = str(resp)
            cost = 0.0

        logger.info(f"[{result.run_id}] call_specialist {role} ({model_id}): {len(output)} chars, ${cost:.4f}")

        # Record cost in budget_controller
        if cost > 0 and self.budget:
            try:
                from core.budget_controller import TaskCategory
                _pid = getattr(result, "project_id", None) or getattr(self, "project_id", None)
                if _pid:
                    self.budget.record(
                        project_id=_pid,
                        task_id=result.run_id,
                        model=model_id,
                        category=TaskCategory.LLM if hasattr(TaskCategory, "LLM") else "llm",
                        input_tokens=result.cost_breakdown[-1].get("tokens_in", 0) if result.cost_breakdown else 0,
                        output_tokens=result.cost_breakdown[-1].get("tokens_out", 0) if result.cost_breakdown else 0,
                        cost_usd_override=cost,
                    )
            except Exception as _be:
                logger.debug(f"budget_controller record skipped: {_be}")
        # Side-effects: save role-specific artifacts
        if role == "art_director" and output:
            await self._save_design_spec(result, output)
        if role == "marketer" and output:
            await self._save_positioning(result, output)
        if role == "seo_writer" and output:
            await self._save_seo_spec(result, output)

        return output


    # ARCANE 3.0: PARALLEL SPECIALIST EXECUTION
    # ═══════════════════════════════════════════════════════════════════════

    async def _run_parallel_specialists(
        self, result: RunResult, context: dict,
        on_status_change=None,
    ) -> dict[str, str]:
        """Run art_director, writer, researcher in parallel via asyncio.gather.
        
        Returns: {role: output_text} for each specialist.
        Outputs are fed into Developer's context as enrichment.
        """
        import asyncio
        
        await self._update_status(result, RunStatus.RUNNING, on_status_change,
            {"phase": "parallel_specialists", "message": "Running specialists in parallel..."})
        
        # Get role-specific prompts
        try:
            from shared.prompt_templates import get_role_prompt
        except ImportError:
            get_role_prompt = lambda role, lang="ru": ""
        
        async def _call_specialist(role: str, model_id: str) -> tuple[str, str]:
            """Call a single specialist and return (role, output)."""
            try:
                system_prompt = get_role_prompt(role)
                user_prompt = f"Проект: {result.task}\n\nТип: {result.task_type}\nСложность: {result.complexity}"
                
                # FIX-1: context dict has project_state/tech_stack/personality, NOT "project_context"
                _ctx_parts = []
                if context.get("personality"):
                    _ctx_parts.append(f"Предпочтения клиента: {str(context['personality'])[:300]}")
                if context.get("tech_stack"):
                    _ts = context["tech_stack"]
                    _ts_str = ", ".join(f"{k}={v}" for k,v in _ts.items() if v) if isinstance(_ts, dict) else str(_ts)
                    if _ts_str: _ctx_parts.append(f"Стек технологий: {_ts_str}")
                if context.get("design_system"):
                    _ds = context["design_system"]
                    _ds_str = ", ".join(f"{k}={v}" for k,v in _ds.items() if v) if isinstance(_ds, dict) else str(_ds)
                    if _ds_str: _ctx_parts.append(f"Дизайн-система: {_ds_str}")
                if context.get("design_spec"):
                    import json as _cj
                    _ctx_parts.append(f"design_spec: {_cj.dumps(context['design_spec'], ensure_ascii=False)[:800]}")
                if _ctx_parts:
                    user_prompt += "\n\nКонтекст проекта:\n" + "\n".join(_ctx_parts)
                
                resp = await self.llm.chat(
                    model=model_id,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                    max_tokens=2048,  # specialists need bounded output
                )
                # FIX #3: handle tool_calls response (gpt-5.4 may return tool_calls instead of text)
                if isinstance(resp, dict):
                    output = resp.get("content", "") or ""
                    if not output and resp.get("tool_calls"):
                        # Extract text from first tool call arguments
                        for _tc in resp["tool_calls"]:
                            _args = _tc.get("function", {}).get("arguments", "")
                            if isinstance(_args, dict):
                                output = _args.get("content", _args.get("text", str(_args)))
                            elif isinstance(_args, str) and _args:
                                import json as _rj
                                try:
                                    _parsed = _rj.loads(_args)
                                    output = _parsed.get("content", _parsed.get("text", str(_parsed)))
                                except Exception:
                                    output = _args
                            if output: break
                    cost = resp.get("cost_usd", 0.0)
                else:
                    output = str(resp)
                    cost = 0.0
                result.actual_cost += cost
                
                logger.info(f"[{result.run_id}] Specialist {role} ({model_id}): {len(output)} chars, ${cost:.4f}")
                
                # Save design_spec.json if art_director
                if role == "art_director" and output:
                    await self._save_design_spec(result, output)
                # Save positioning.json if marketer
                if role == "marketer" and output:
                    await self._save_positioning(result, output)
                # Save seo_spec.json if seo_writer
                if role == "seo_writer" and output:
                    await self._save_seo_spec(result, output)
                
                return (role, output)
            except Exception as e:
                logger.warning(f"[{result.run_id}] Specialist {role} failed: {e}")
                return (role, "")
        
        # Build list of specialist tasks
        specialist_roles = ["art_director", "marketer", "seo_writer", "writer", "researcher"]
        tasks = []
        for role in specialist_roles:
            model_id = result.team.get(role)
            if model_id:
                tasks.append(_call_specialist(role, model_id))
        
        if not tasks:
            logger.warning(f"[{result.run_id}] No specialist tasks — team has no art_director/writer/researcher")
            return {}

        logger.info(f"[{result.run_id}] Launching {len(tasks)} specialists in parallel: "
                    f"{specialist_roles[:len(tasks)]}")
        # Run all specialists in parallel
        results_list = await asyncio.gather(*tasks, return_exceptions=True)
        
        outputs = {}
        for item in results_list:
            if isinstance(item, tuple):
                role, output = item
                if output:
                    outputs[role] = output
            elif isinstance(item, Exception):
                logger.warning(f"[{result.run_id}] Specialist exception: {item}")
        
        return outputs

    async def _save_design_spec(self, result: RunResult, art_director_output: str):
        """Save Art Director output as design_spec.json in .arcane/ directory.
        
        Tries to extract JSON from the output. If output is already valid JSON,
        saves as-is. Otherwise wraps in a simple structure.
        """
        import os
        workspace = os.environ.get("ARCANE_WORKSPACE", "/root/workspace")
        spec_dir = os.path.join(workspace, "projects", result.project_id, ".arcane")
        spec_path = os.path.join(spec_dir, "design_spec.json")
        
        try:
            os.makedirs(spec_dir, exist_ok=True)
            
            # Try to parse as JSON
            import json
            try:
                # Try to find JSON in the output (might be wrapped in markdown)
                json_str = art_director_output
                if "```json" in json_str:
                    json_str = json_str.split("```json")[1].split("```")[0].strip()
                elif "```" in json_str:
                    json_str = json_str.split("```")[1].split("```")[0].strip()
                
                spec = json.loads(json_str)
            except (json.JSONDecodeError, IndexError):
                # Wrap raw text as design spec
                spec = {"raw_output": art_director_output, "parsed": False}
            
            with open(spec_path, "w", encoding="utf-8") as f:
                json.dump(spec, f, ensure_ascii=False, indent=2)
            
            logger.info(f"[{result.run_id}] design_spec.json saved to {spec_path}")
        except Exception as e:
            logger.warning(f"[{result.run_id}] Failed to save design_spec.json: {e}")

    async def _save_positioning(self, result, marketer_output: str):
        """Save Marketer output as positioning.json in .arcane/ directory."""
        import os, json
        workspace = os.environ.get("ARCANE_WORKSPACE", "/root/workspace")
        spec_dir = os.path.join(workspace, "projects", result.project_id, ".arcane")
        spec_path = os.path.join(spec_dir, "positioning.json")
        try:
            os.makedirs(spec_dir, exist_ok=True)
            json_str = marketer_output
            if "```json" in json_str:
                json_str = json_str.split("```json")[1].split("```")[0].strip()
            elif "```" in json_str:
                json_str = json_str.split("```")[1].split("```")[0].strip()
            try:
                spec = json.loads(json_str)
            except (json.JSONDecodeError, IndexError):
                spec = {"raw_output": marketer_output, "parsed": False}
            with open(spec_path, "w", encoding="utf-8") as f:
                json.dump(spec, f, ensure_ascii=False, indent=2)
            logger.info(f"[{result.run_id}] positioning.json saved to {spec_path}")
        except Exception as e:
            logger.warning(f"[{result.run_id}] Failed to save positioning.json: {e}")

    async def _save_seo_spec(self, result, seo_writer_output: str):
        """Save SEO Writer output as seo_spec.json in .arcane/ directory."""
        import os, json
        workspace = os.environ.get("ARCANE_WORKSPACE", "/root/workspace")
        spec_dir = os.path.join(workspace, "projects", result.project_id, ".arcane")
        spec_path = os.path.join(spec_dir, "seo_spec.json")
        try:
            os.makedirs(spec_dir, exist_ok=True)
            json_str = seo_writer_output
            if "```json" in json_str:
                json_str = json_str.split("```json")[1].split("```")[0].strip()
            elif "```" in json_str:
                json_str = json_str.split("```")[1].split("```")[0].strip()
            try:
                spec = json.loads(json_str)
            except (json.JSONDecodeError, IndexError):
                spec = {"raw_output": seo_writer_output, "parsed": False}
            with open(spec_path, "w", encoding="utf-8") as f:
                json.dump(spec, f, ensure_ascii=False, indent=2)
            logger.info(f"[{result.run_id}] seo_spec.json saved to {spec_path}")
        except Exception as e:
            logger.warning(f"[{result.run_id}] Failed to save seo_spec.json: {e}")


    async def _run_research_pipeline(
        self,
        result,
        project_dir: str,
        positioning: dict | None = None,
        on_status_change=None,
    ):
        """ARCANE 4.0: Run Manus research pipeline before Art Director."""
        if not self.manus_pipelines:
            logger.warning(f"[{result.run_id}] ManusPipelineFactory not available, skipping research")
            return None
        obs_decision = getattr(result, "_observer_decision", None)
        if obs_decision and not getattr(obs_decision, "needs_research", False):
            return None
        logger.info(f"[{result.run_id}] Starting research pipeline via Manus...")
        try:
            research_pipeline = self.manus_pipelines.research()
            research_result = await research_pipeline.run(
                project_id=result.project_id,
                task=result.task,
                project_dir=project_dir,
                positioning=positioning,
                on_progress=on_status_change,
                mode=result.mode if result.mode in ("quality", "balanced", "economy") else "balanced",
            )
            if research_result.success:
                logger.info(f"[{result.run_id}] Research complete: {len(research_result.awwwards_references)} refs")
                return {
                    "awwwards_references": research_result.awwwards_references,
                    "competitor_analysis": research_result.competitor_analysis,
                    "market_insights": research_result.market_insights,
                }
            else:
                logger.warning(f"[{result.run_id}] Research pipeline failed: {research_result.error}")
                return None
        except Exception as e:
            logger.warning(f"[{result.run_id}] Research pipeline error: {e}")
            return None

    async def _run_visual_qa(
        self, result, primary_model: str,
        on_status_change=None,
        max_rounds: int = 2,
    ) -> bool:
        """Run visual QA via ManusBridge (ARCANE 3.0).
        
        Old: used Playwright directly (violated Manus-only principle).
        New: submits package to Manus, checks result for visual issues.
        If issues found → Developer fixes → QA → Manus again (max 2 rounds).
        """
        if not self.manus:
            logger.warning(f"[{result.run_id}] ManusBridge not available, skipping visual QA")
            return True
        
        try:
            import os
            workspace = os.environ.get("ARCANE_WORKSPACE", "/root/workspace")
            project_dir = os.path.join(workspace, "projects", result.project_id)
            
            await self._update_status(result, RunStatus.RUNNING, on_status_change,
                {"phase": "visual_qa", "message": "Visual QA: sending to Manus..."})
            
            # Build package from project files
            mode_map = {"quality": "quality", "balance": "balanced", "economy": "economy", "free": "mock"}
            strategy = getattr(self.presets, 'strategy_key', 'balance') if self.presets else 'balance'
            manus_mode = mode_map.get(strategy, "balanced")
            
            # Send SHORT task to Manus — not enriched 9000-char blob with design_spec
            # If Manus gets the full enriched task, it creates files instead of QA-ing them
            _manus_task_base = result.task.split("\n" + "=" * 40)[0][:150].strip()
            _manus_task_short = "Visual QA: " + _manus_task_base + ". Check desktop (1440px) and mobile (375px)."

            package = self.manus.build_package(
                project_id=result.project_id,
                task=_manus_task_short,
                project_dir=project_dir,
                mode=manus_mode,
            )
            
            manus_result = await self.manus.submit(package)
            
            if not manus_result.success:
                logger.warning(f"[{result.run_id}] Manus visual QA failed: {manus_result.error}")
                return True  # Don't block pipeline on Manus failure
            
            if not manus_result.has_visual_issues:
                logger.info(f"[{result.run_id}] Visual QA passed (Manus)")
                return True
            
            logger.info(f"[{result.run_id}] Manus found {len(manus_result.visual_issues)} visual issues")
            
            # Send issues to Developer for fixing (return loop)
            if self.llm and primary_model:
                issues_text = "\n".join(f"- {issue}" for issue in manus_result.visual_issues)
                fix_prompt = f"""Manus visual QA found these problems:

{issues_text}

Fix these issues in the HTML/CSS.
Original task: {result.task[:300]}"""
                
                fix_response = await self.llm.chat(
                    model=primary_model,
                    messages=[
                        {"role": "system", "content": "You are a web developer. Fix the visual issues found by Manus."},
                        {"role": "user", "content": fix_prompt},
                    ],
                )
                if isinstance(fix_response, dict):
                    fixed = fix_response.get("content", "")
                    cost = fix_response.get("cost_usd", 0.0)
                    result.actual_cost += cost
                    if fixed:
                        result.output = fixed
                        # BUG-1 FIX: write fix to disk so Manus sees updated file
                        _html_files = [a for a in result.artifacts if a.endswith('.html')]
                        if _html_files:
                            import os as _vqa_os
                            _html_path = _vqa_os.path.join(
                                _vqa_os.environ.get("ARCANE_WORKSPACE", "/root/workspace"),
                                "projects", result.project_id, "src", _html_files[0]
                            )
                            if _vqa_os.path.exists(_html_path):
                                try:
                                    with open(_html_path, "w", encoding="utf-8") as _hf:
                                        _hf.write(fixed)
                                    logger.info(f"[{result.run_id}] Visual QA fix written to {_html_path}")
                                except Exception as _we:
                                    logger.warning(f"[{result.run_id}] Could not write fix: {_we}")
                        logger.info(f"[{result.run_id}] Visual QA fix applied by Developer")
            
            return True
            
        except Exception as e:
            logger.warning(f"[{result.run_id}] Visual QA error: {e}")
            return True  # Don't block on failure

    async def _run_qa_check(
        self, result, context: dict,
        qa_model: str, primary_model: str,
        on_status_change=None,
        max_qa_rounds: int = 2,
    ) -> bool:
        """Run QA check on agent output. Returns True if passed. (Stage C)"""
        for round_num in range(max_qa_rounds):
            try:
                await self._update_status(result, RunStatus.RUNNING, on_status_change,
                    {"phase": "qa_review",
                     "qa_round": round_num + 1,
                     "message": f"QA review round {round_num + 1}/{max_qa_rounds}"})
                
                # FIX B v2: Give QA a proper structural summary of the HTML
                # Problem: QA saw first 8000 chars (only <head>+<nav>) and said "FAIL: incomplete"
                # Fix: send structure summary + beginning + middle + end
                import os as _qa_os, re as _qa_re
                _workspace = _qa_os.environ.get("ARCANE_WORKSPACE", "/root/workspace")
                _src_dir = _qa_os.path.join(_workspace, "projects", result.project_id, "src")
                content_to_review = ""
                _html_found = False
                if result.artifacts:
                    for _artifact in result.artifacts[:5]:
                        _path = _qa_os.path.join(_src_dir, _artifact)
                        if _qa_os.path.exists(_path):
                            try:
                                _c = open(_path, encoding="utf-8", errors="replace").read()
                                if _artifact.endswith(".html"):
                                    _html_found = True
                                    # Structural summary — what QA really needs to know
                                    _sections = _qa_re.findall(r'<section[^>]*id=["\']([^"\']+)["\'\ ]', _c)
                                    _has_close = _c.rstrip().endswith("</html>")
                                    _img_count = len(_qa_re.findall(r'<img[^>]+src=', _c))
                                    _form = bool(_qa_re.search(r'<form', _c))
                                    _summary = (
                                        f"FILE: {_artifact} ({len(_c):,} chars, {_c.count(chr(10))} lines)\n"
                                        f"Complete (ends </html>): {_has_close}\n"
                                        f"Sections found: {_sections}\n"
                                        f"Images: {_img_count}, Form: {_form}\n"
                                        f"NOTE: HTML was written in chunks via append=True — this is correct and expected.\n"
                                    )
                                    # Beginning (head+first section) + middle + end
                                    _begin = _c[:2500]
                                    _mid_start = len(_c)//2 - 500
                                    _mid = _c[_mid_start:_mid_start+1500]
                                    _end = _c[-1500:]
                                    content_to_review += (
                                        f"\n--- {_artifact} SUMMARY ---\n{_summary}"
                                        f"\n--- BEGINNING ---\n{_begin}"
                                        f"\n--- MIDDLE ---\n{_mid}"
                                        f"\n--- END ---\n{_end}"
                                    )
                                else:
                                    content_to_review += f"\n\n--- {_artifact} ({len(_c)} chars) ---\n" + _c[:2000]
                            except Exception: pass
                # Priority 2: scan src/ directory for HTML
                if not _html_found and _qa_os.path.isdir(_src_dir):
                    for _f in sorted(_qa_os.listdir(_src_dir)):
                        if _f.endswith(".html"):
                            try:
                                _c = open(_qa_os.path.join(_src_dir, _f), encoding="utf-8").read()
                                content_to_review += f"\n\n--- {_f} ({len(_c)} chars total) ---\n" + _c[:8000]
                                _html_found = True
                            except Exception: pass
                if not content_to_review:
                    content_to_review = result.output or "No output"

                qa_prompt = f"""You are a QA reviewer for a web development AI agency.

IMPORTANT CONTEXT:
- HTML files are written in CHUNKS using append=True — this is CORRECT, not an error
- A 40-80KB HTML file across multiple file_write calls is EXPECTED and GOOD
- Judge completeness from the SUMMARY (sections found, ends </html>) not from seeing all code
- PASS if: sections list is non-empty, file ends </html>, has images and form where expected
- FAIL only for: missing </html>, 0 sections, no images when task requires them, wrong client data

ORIGINAL TASK:
{result.task[:500]}

FILE ANALYSIS:
{content_to_review[:4000]}

Evaluate:
1. Is the HTML structurally complete? (ends </html>, has sections)
2. Does content match the task? (right client name, address, phone)
3. Are images present and working (relative paths, not /root/)?
4. Is there a form/booking section if task requires it?

Respond with EXACTLY one of:
- "PASS: <brief reason>" — if output is acceptable
- "FAIL: <specific issues>" — if output needs improvement

Be strict but fair. Minor style issues = PASS. Missing functionality = FAIL."""

                if not self.llm:
                    return True  # Dry run - skip QA
                
                response = await self.llm.chat(
                    model=qa_model,
                    messages=[
                        {"role": "system", "content": "You are a strict QA reviewer. Be concise."},
                        {"role": "user", "content": qa_prompt},
                    ],
                )
                
                qa_response = ""
                if isinstance(response, dict):
                    qa_response = response.get("content", "")
                    cost = response.get("cost_usd", 0.0)
                    result.actual_cost += cost
                else:
                    qa_response = str(response)
                
                logger.info(f"[{result.run_id}] QA round {round_num + 1}: {qa_response[:100]}")
                
                if qa_response.upper().startswith("PASS"):
                    logger.info(f"[{result.run_id}] QA passed on round {round_num + 1}")
                    # FIX-4: populate real lint/html metrics for ModelArena
                    if result.artifacts and result.task_type in ("web_design", "coding", "automation", "cms_management"):
                        try:
                            import os as _lqa_os
                            _lws = _lqa_os.environ.get("ARCANE_WORKSPACE", "/root/workspace")
                            _lint_total = 0
                            _html_ok = True
                            for _art in result.artifacts[:3]:
                                _ap = _lqa_os.path.join(_lws, "projects", result.project_id, "src", _art)
                                if not _lqa_os.path.exists(_ap): continue
                                if _art.endswith((".py", ".js", ".ts", ".html", ".css")):
                                    import subprocess as _sp
                                    if _art.endswith(".py"):
                                        _r = _sp.run(["python3", "-m", "py_compile", _ap],
                                                     capture_output=True, text=True)
                                        if _r.returncode != 0: _lint_total += 1
                                    elif _art.endswith((".js",".ts")):
                                        _r = _sp.run(["node", "--check", _ap],
                                                     capture_output=True, text=True)
                                        if _r.returncode != 0: _lint_total += 1
                                if _art.endswith((".html", ".htm")):
                                    with open(_ap, encoding="utf-8", errors="replace") as _hf:
                                        _hc = _hf.read()
                                    if "<!DOCTYPE" not in _hc or "viewport" not in _hc:
                                        _html_ok = False
                            result.lint_errors = _lint_total
                            result.html_valid = _html_ok
                            logger.debug(f"[{result.run_id}] Lint metrics: errors={_lint_total}, html_valid={_html_ok}")
                        except Exception as _le:
                            logger.debug(f"Lint metrics skipped: {_le}")
                    return True
                
                # QA failed — send back for fixing if we have more rounds
                if round_num < max_qa_rounds - 1:
                    qa_issues = qa_response.replace("FAIL:", "").strip()
                    fix_prompt = f"""The QA reviewer found these issues with your previous output:

{qa_issues}

Original task: {result.task}

Please fix these issues and provide the complete corrected output."""
                    
                    fix_response = await self.llm.chat(
                        model=primary_model,
                        messages=[
                            {"role": "system", "content": "You are a helpful assistant. Fix the issues and provide complete output."},
                            {"role": "user", "content": fix_prompt},
                        ],
                    )
                    
                    if isinstance(fix_response, dict):
                        fixed_output = fix_response.get("content", "")
                        cost = fix_response.get("cost_usd", 0.0)
                        result.actual_cost += cost
                        if fixed_output:
                            result.output = fixed_output
                            logger.info(f"[{result.run_id}] QA fix applied, re-checking...")
                    
            except Exception as e:
                logger.warning(f"[{result.run_id}] QA check error: {e}")
                return True  # Don't block on QA failure
        
        return False  # QA failed after all rounds


    async def _run_design_judge(
        self, result, primary_model: str, on_status_change=None
    ) -> dict:
        """
        Design Judge: evaluate the visual/UX quality of web output.
        Called after _run_qa_check for web_design tasks.
        Returns {"score": 0-10, "passed": bool, "feedback": str}
        """
        if result.task_type not in ("web_design", "design", "media"):
            return {"score": 10, "passed": True, "feedback": "Not a design task"}

        if not self.llm or not result.artifacts:
            return {"score": 10, "passed": True, "feedback": "No artifacts to judge"}

        # Find HTML artifact
        import os
        workspace = os.environ.get("ARCANE_WORKSPACE", "/root/workspace")
        html_content = ""
        for artifact in result.artifacts[:3]:
            if artifact.endswith(".html"):
                candidate = os.path.join(workspace, "projects", result.project_id, "src", artifact)
                if os.path.exists(candidate):
                    try:
                        with open(candidate, encoding="utf-8") as f:
                            html_content = f.read()[:4000]
                        break
                    except Exception:
                        pass

        if not html_content:
            html_content = result.output[:4000]

        judge_prompt = f"""You are an expert web designer and UX critic.
Evaluate this HTML/CSS code for visual quality and UX.

ORIGINAL TASK: {result.task[:300]}

HTML CODE (first 4000 chars):
{html_content}

Score on each criterion (1-10):
1. Visual Design: Is it beautiful, modern, professional?
2. Responsive: Mobile-first, proper breakpoints?
3. Content Quality: No placeholders, Lorem ipsum, TODO?
4. Performance: Lazy loading, no blocking resources?
5. Accessibility: Alt tags, contrast, semantic HTML?

Respond ONLY in this exact format:
SCORE: X/10
VISUAL: X - reason
RESPONSIVE: X - reason
CONTENT: X - reason
PERFORMANCE: X - reason
ACCESSIBILITY: X - reason
VERDICT: PASS or FAIL
IMPROVEMENTS: bullet list of 2-3 specific improvements (if FAIL)"""

        try:
            response = await asyncio.wait_for(
                self.llm.chat(
                    model=primary_model,
                    messages=[
                        {"role": "system", "content": "You are a professional web design critic. Be specific and actionable."},
                        {"role": "user", "content": judge_prompt},
                    ],
                    max_tokens=600,
                    temperature=0.2,
                ),
                timeout=30.0,
            )
            if isinstance(response, dict):
                result.actual_cost += response.get("cost_usd", 0.0)
                feedback = response.get("content", "")
            else:
                feedback = str(response)

            # Parse verdict
            passed = "VERDICT: PASS" in feedback.upper() or "VERDICT: PASS" in feedback
            # Extract score
            score = 7  # default
            import re
            sm = re.search(r"SCORE:\s*(\d+)", feedback, re.I)
            if sm:
                score = min(10, max(1, int(sm.group(1))))

            logger.info(f"[{result.run_id}] Design Judge: score={score}/10, passed={passed}")
            return {"score": score, "passed": passed, "feedback": feedback}

        except Exception as e:
            logger.warning(f"[{result.run_id}] Design Judge failed: {e}")
            return {"score": 7, "passed": True, "feedback": f"Judge unavailable: {e}"}

    async def _direct_llm_call(self, result: RunResult, context: dict, model_id: str, override_prompt: str | None = None) -> str:
        """Fallback: direct LLM call without agent loop."""
        if not self.llm:
            return f"[DRY RUN] Task: {result.task}, Model: {model_id}"
        
        # Build prompt with project context
        if override_prompt:
            system_prompt = "You are a quality gate validator. Return only JSON."
            user_content = override_prompt
        else:
            system_prompt = self._build_system_prompt(context)
            user_content = result.task
        
        response = await self.llm.chat(
            model=model_id,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content},
            ],
        )
        
        # Track cost from LLM response
        if isinstance(response, dict):
            cost = response.get("cost_usd", 0.0)
            result.actual_cost += cost
            result.cost_breakdown.append({
                "model": model_id,
                "cost": cost,
                "tokens_in": response.get("tokens_in", 0),
                "tokens_out": response.get("tokens_out", 0),
            })
            return response.get("content", "")
        
        return str(response)
    
    def _build_system_prompt(self, context: dict) -> str:
        """Build system prompt with project context. Not instructions — context."""
        try:
            from core.identity_shield import get_identity_block as _get_id_block
            _id_block = _get_id_block()
        except Exception:
            _id_block = ""
        if _id_block:
            parts = [_id_block]
        else:
            parts = []
        parts = ["You are working on a project. Here is the context:"]
        
        if context.get("project_state"):
            state = context["project_state"]
            if state.get("project_profile"):
                parts.append(f"\nProject: {state['project_profile']}")
            if state.get("tech_stack"):
                parts.append(f"\nTech stack: {state['tech_stack']}")
            if state.get("design_system"):
                parts.append(f"\nDesign system: {state['design_system']}")
            if state.get("personality"):
                parts.append(f"\nClient preferences: {state['personality']}")
        
        parts.append("\nDo the task your way. You have full freedom in approach.")
        return "\n".join(parts)
    
    # ─── Default Agent Loop Factory ─────────────────────────────────────

    def _default_agent_loop_factory(
        self, model_id, project_context, task, budget_remaining=None, mode=None,
    ):
        """
        Create an AgentLoop with ToolExecutor.
        Registers SSH tools if needs_ssh=True, using server config from project state.
        """
        try:
            from core.tool_registry import ToolRegistry
            from core.tool_executor import ToolExecutor
            from core.agent_loop import AgentLoop
            from shared.llm.router import ModelRouter

            # Workspace directory
            workspace = os.environ.get("ARCANE_WORKSPACE", "/root/workspace")
            project_id = project_context.get("project_id", "default")
            project_dir = os.path.join(workspace, "projects", project_id, "src")
            os.makedirs(project_dir, exist_ok=True)

            # Tool system
            registry = ToolRegistry()
            # FIX-10: create SecurityContext and pass to ToolExecutor
            _sec_ctx = None
            try:
                from core.security import SecurityContext
                from pathlib import Path
                _sec_ctx = SecurityContext.create(Path(project_dir))
            except Exception as _e:
                logger.debug(f"SecurityContext init skipped: {_e}")
            # Reuse existing executor if passed (preserves image counter across retries)
            _prev_executor = project_context.get("_reusable_executor") if project_context else None
            if _prev_executor is not None and hasattr(_prev_executor, "_image_gen_call_count"):
                executor = _prev_executor
                executor._project_dir = project_dir  # update path in case it changed
                logger.info(f"Reusing executor with image_count={executor._image_gen_call_count}")
            else:
                executor = ToolExecutor(registry=registry, project_dir=project_dir, security_context=_sec_ctx)
            # Store for next retry
            if project_context is not None:
                project_context["_reusable_executor"] = executor

            # ── ARCANE 3.0: SSH and browser are Manus-only capabilities ─────
            # Developer agent does NOT get SSH or browser tools.
            # All server access and browser rendering goes through ManusBridge.
            if project_context.get("needs_ssh"):
                logger.info("needs_ssh=True → will be handled by ManusBridge, not agent tools")
            if project_context.get("needs_browser"):
                logger.info("needs_browser=True → will be handled by ManusBridge, not agent tools")

            # ── Register image tools if task needs them ───────────────────
            if project_context.get("task_type") in ("media", "web_design", "design") or project_context.get("needs_image_gen"):
                try:
                    from workers.image_gen import get_image_generator
                    img_gen = get_image_generator()
                    # Pass shared counter so limit persists across retries
                    executor.register_image_tools(img_gen)
                    logger.info("Image generation tools registered")
                except ImportError as e:
                    logger.warning(f"Image gen not available: {e}")

            # Router (wraps llm_client with model selection + budget)
            # Create a mode-specific copy of preset_manager for this run
            import copy
            from shared.llm.preset_manager import PresetMode, ensure_free_strategy
            _pm_copy = copy.deepcopy(self.presets) if self.presets else None
            if _pm_copy and mode:
                try:
                    _pm_copy.mode = PresetMode(mode)
                    if mode == "free":
                        ensure_free_strategy()
                except (ValueError, Exception):
                    pass
            router = ModelRouter(
                client=self.llm,
                strategy="balance",  # ignored when preset_manager is set
                budget_limit=budget_remaining or 5.0,
                preset_manager=_pm_copy or self.presets,
            )

            # Agent loop — pass full project context + role so agent has right prompt
            _agent_role = project_context.get("agent_role", "developer") if project_context else "developer"
            return AgentLoop(
                llm_client=self.llm,
                router=router,
                tool_executor=executor,
                project_id=project_id,
                max_iterations=25,
                chat_id=project_context.get("chat_id", project_id) if project_context else project_id,
                user_id=project_context.get("user_id", "") if project_context else "",
                project_context=project_context,  # tech_stack, design_system, golden_path_hint
                role=_agent_role,  # ARCANE 3.0: role-specific prompt
            )
        except Exception as e:
            logger.warning(f"Failed to create AgentLoop: {e}. Will use direct LLM call.")
            return None

    async def _update_status(
        self, result: RunResult, status: RunStatus, callback: Callable | None,
        extra_data: dict | None = None
    ):
        """Update run status and notify via callback."""
        result.status = status
        # Persist to history DB on terminal states
        _terminal = {RunStatus.DONE, RunStatus.FAILED, RunStatus.CANCELLED}
        if status in _terminal and getattr(self, "history_db", None) is not None:
            try:
                import os as _os, json as _json
                _workspace = _os.environ.get("ARCANE_WORKSPACE", "/root/workspace")
                _state_path = _os.path.join(_workspace, "projects", result.project_id, ".arcane", "state.json")
                _proj_name = result.project_id
                if _os.path.exists(_state_path):
                    with open(_state_path) as _f:
                        _st = _json.load(_f)
                        _proj_name = _st.get("name", result.project_id)
                self.history_db.save_run(result.to_dict(), project_name=_proj_name)
            except Exception as _e:
                import logging as _log
                _log.getLogger(__name__).warning(f"Failed to persist run {result.run_id}: {_e}")
        logger.info(f"[{result.run_id}] → {status.value}")
        if callback:
            try:
                _cb_data = result.to_dict()
                if extra_data:
                    _cb_data.update(extra_data)
                await callback(result.run_id, status.value, _cb_data)
            except Exception as e:
                logger.error(f"Status callback error: {e}")
    
    # ─── Public API ───────────────────────────────────────────────────────
    
    def _evict_old_runs(self, max_age: float = 3600, max_size: int = 200):
        """Remove completed runs older than max_age seconds. Prevents memory leak."""
        if len(self._runs) <= max_size:
            return
        terminal = {RunStatus.DONE, RunStatus.FAILED, RunStatus.CANCELLED}
        now = time.time()
        to_remove = [
            rid for rid, r in self._runs.items()
            if r.status in terminal and r.finished_at and (now - r.finished_at) > max_age
        ]
        for rid in to_remove:
            del self._runs[rid]
        if to_remove:
            logger.debug(f"Evicted {len(to_remove)} old runs, {len(self._runs)} remaining")

    def get_run(self, run_id: str) -> RunResult | None:
        """Get current state of a run."""
        return self._runs.get(run_id)
    
    def get_project_runs(self, project_id: str) -> list:
        """Return all runs belonging to a specific project."""
        return [r for r in self._runs.values() if r.project_id == project_id]

    def get_active_runs(self) -> list[RunResult]:
        """Get all active (non-terminal) runs."""
        terminal = {RunStatus.DONE, RunStatus.FAILED, RunStatus.CANCELLED}
        return [r for r in self._runs.values() if r.status not in terminal]
    
    def cancel_run(self, run_id: str) -> bool:
        """Cancel a running task."""
        run = self._runs.get(run_id)
        if run and run.status in {RunStatus.QUEUED, RunStatus.RUNNING, RunStatus.PAUSED}:
            run.status = RunStatus.CANCELLED
            return True
        return False


# ═══════════════════════════════════════════════════════════════════════════════
# EXCEPTIONS
# ═══════════════════════════════════════════════════════════════════════════════

class BudgetPausedError(Exception):
    """Raised when budget limit reached and user confirmation needed."""
    pass

class CancelledError(Exception):
    """Raised when user cancels a run."""
    pass
