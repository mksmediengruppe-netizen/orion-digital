"""
ARCANE 2 — Agent Loop with Run Graph

The autonomous execution engine. Implements the Manus-style agent loop
with external run graph control:

  FREEDOM INSIDE the step:
    Model freely chooses approach, style, structure.
    No hard-wired pipelines (scene_planner → assembler is GONE).

  CONTROL OUTSIDE via Run Graph:
    queued → assigned → running → review → done / failed
    Retry budget. Budget pause. Cancellation. Rollback.

Agent loop iteration:
  1. Analyze context — understand user intent and current state
  2. Think — reason about the next action
  3. Select tool — choose the right tool via function calling
  4. Execute — run the tool in the sandbox
  5. Observe — append result to context
  6. Iterate — repeat until task is complete
  7. Deliver — send results to user

Key principles:
  - MUST always respond with a tool call (never raw text)
  - One tool call per iteration (no parallel calls)
  - Self-healing on errors (retry, escalate tier, try alternative)
  - Budget-aware (stop before exceeding limits)
  - Streaming status updates via WebSocket
  - Run graph: external control of task lifecycle
"""

from __future__ import annotations

import asyncio
import time
import traceback
import uuid
from enum import Enum
from typing import Any, Callable, Optional

from shared.llm.client import BadRequestError, BudgetExceededError, ProviderUnavailableError, UnifiedLLMClient
from shared.prompt_templates import detect_language, get_prompt_section, build_full_prompt
from shared.llm.router import ModelRouter
from shared.llm.usage_tracker import UsageTracker, get_usage_tracker
from shared.models.schemas import (
    AgentState,
    LLMRequest,
    LLMResponse,
    ProjectState,
    TaskPhase,
    Tier,
    ToolCall,
)
from shared.utils.error_analyzer import analyze_error, is_critical, should_escalate_tier
from shared.utils.logger import get_logger, log_with_data
from core.context_manager import Scratchpad, ContextCompactor, GoalAnchor
from core.user_profile import get_user_preferences, preferences_to_prompt, extract_preferences, save_preferences

# Memory v9
try:
    from shared.memory.engine import SuperMemoryEngine
    _memory_available = True
except ImportError:
    _memory_available = False

logger = get_logger("core.agent_loop")


# ─── Run Graph ──────────────────────────────────────────────────────

class RunStatus(str, Enum):
    """Run graph statuses: external lifecycle control for every task."""
    QUEUED = "queued"
    ASSIGNED = "assigned"
    RUNNING = "running"
    REVIEW = "review"
    DONE = "done"
    FAILED = "failed"
    CANCELLED = "cancelled"
    PAUSED = "paused"
    BUDGET_EXCEEDED = "budget_exceeded"
    WAITING_USER = "waiting_user"


class RunGraph:
    """
    External task lifecycle controller.

    Implements: queued → assigned → running → review → done/failed.
    Retry budget. Cancellation. Idempotency keys. Budget pause. Rollback.

    The agent loop is FREE inside each step (model chooses approach).
    The run graph controls OUTSIDE: statuses, retries, budget, cancel.
    """

    # Valid transitions
    _TRANSITIONS: dict[RunStatus, set[RunStatus]] = {
        RunStatus.QUEUED: {RunStatus.ASSIGNED, RunStatus.CANCELLED},
        RunStatus.ASSIGNED: {RunStatus.RUNNING, RunStatus.CANCELLED},
        RunStatus.RUNNING: {
            RunStatus.REVIEW, RunStatus.DONE, RunStatus.FAILED,
            RunStatus.PAUSED, RunStatus.BUDGET_EXCEEDED,
            RunStatus.CANCELLED, RunStatus.WAITING_USER,
        },
        RunStatus.REVIEW: {RunStatus.DONE, RunStatus.FAILED, RunStatus.RUNNING, RunStatus.CANCELLED},
        RunStatus.PAUSED: {RunStatus.RUNNING, RunStatus.CANCELLED},
        RunStatus.WAITING_USER: {RunStatus.RUNNING, RunStatus.CANCELLED},
        RunStatus.BUDGET_EXCEEDED: {RunStatus.CANCELLED},
        RunStatus.DONE: set(),
        RunStatus.FAILED: {RunStatus.QUEUED},  # retry: failed → queued
        RunStatus.CANCELLED: set(),
    }

    def __init__(
        self,
        run_id: str | None = None,
        max_retries: int = 3,
        idempotency_key: str | None = None,
    ):
        self.run_id: str = run_id or uuid.uuid4().hex[:12]
        self.idempotency_key: str | None = idempotency_key
        self.status: RunStatus = RunStatus.QUEUED
        self.retries: int = 0
        self.max_retries: int = max_retries
        self.history: list[dict] = []
        self._cancel_requested: bool = False
        self._created_at: float = time.time()
        self._updated_at: float = self._created_at

        self._record("created", {"run_id": self.run_id, "idempotency_key": idempotency_key})

    def transition(self, new_status: RunStatus, reason: str = "") -> bool:
        """Attempt a status transition. Returns True if valid."""
        allowed = self._TRANSITIONS.get(self.status, set())
        if new_status not in allowed:
            logger.warning(
                f"RunGraph: invalid transition {self.status.value} → {new_status.value} "
                f"(allowed: {[s.value for s in allowed]})"
            )
            return False
        old = self.status
        self.status = new_status
        self._updated_at = time.time()
        self._record("transition", {
            "from": old.value,
            "to": new_status.value,
            "reason": reason,
        })
        logger.info(f"RunGraph [{self.run_id}]: {old.value} → {new_status.value} ({reason})")
        return True

    def request_cancel(self, reason: str = "user_requested") -> bool:
        """Request cancellation. Checked by the agent loop each iteration."""
        if self.status in (RunStatus.DONE, RunStatus.CANCELLED):
            return False
        self._cancel_requested = True
        self._record("cancel_requested", {"reason": reason})
        return True

    @property
    def is_cancelled(self) -> bool:
        return self._cancel_requested

    def can_retry(self) -> bool:
        """Check if retry budget allows another attempt."""
        return self.retries < self.max_retries

    def record_retry(self, error: str = "") -> bool:
        """Record a retry attempt. Returns False if budget exhausted."""
        self.retries += 1
        self._record("retry", {"attempt": self.retries, "max": self.max_retries, "error": error[:200]})
        if self.retries > self.max_retries:
            logger.warning(f"RunGraph [{self.run_id}]: retry budget exhausted ({self.retries}/{self.max_retries})")
            return False
        return True

    def to_dict(self) -> dict:
        return {
            "run_id": self.run_id,
            "idempotency_key": self.idempotency_key,
            "status": self.status.value,
            "retries": self.retries,
            "max_retries": self.max_retries,
            "created_at": self._created_at,
            "updated_at": self._updated_at,
            "history": self.history[-20:],
        }

    def _record(self, event: str, data: dict) -> None:
        self.history.append({
            "event": event,
            "timestamp": time.time(),
            **data,
        })


# ─── Legacy alias ───────────────────────────────────────────────────
LoopStatus = RunStatus


# ─── Intent → Complexity mapping (PATCH-09) ──────────────────────

INTENT_COMPLEXITY: dict[str, dict] = {
    "complex": {
        "markers": [
            "сайт", "лендинг", "landing", "website", "приложение", "application",
            "dashboard", "полный", "full", "complete", "redesign", "migrate",
            "магазин", "shop", "store", "портал", "portal", "платформ", "platform",
            "многостранич", "multi-page", "fullstack", "фулстек",
        ],
        "max_iterations": 60,   # bumped: web_design with images needs 20-30 iterations
    },
    "moderate": {
        "markers": [
            "настрой", "установи", "setup", "configure", "integrate", "deploy",
            "автоматиз", "automat", "workflow", "api", "исправ", "fix", "bug",
            "добав", "add", "feature", "обнов", "update", "refactor",
        ],
        "max_iterations": 30,
    },
    "simple": {
        "markers": [
            "проверь", "check", "status", "покажи", "show", "найди", "find",
            "скажи", "tell", "объясни", "explain", "помоги", "help", "что такое",
            "what is", "как", "how", "список", "list",
        ],
        "max_iterations": 15,
    },
}


class AgentLoop:
    """
    The main autonomous execution engine with Run Graph.

    Receives a user message and iteratively executes tool calls until
    the task is complete or budget is exhausted.

    NO hard-wired pipeline. The model is FREE to choose its approach.
    The Run Graph controls lifecycle EXTERNALLY: status, retries, budget,
    cancellation.
    """

    def __init__(
        self,
        llm_client: UnifiedLLMClient,
        router: ModelRouter,
        tool_executor: Any,
        event_emitter: Optional[Callable] = None,
        project_id: str = "",
        chat_id: str = "",
        user_id: str = "",
        max_iterations: int = 25,
        max_consecutive_errors: int = 5,
        # Run Graph params
        run_id: str | None = None,
        max_retries: int = 3,
        idempotency_key: str | None = None,
        # Project context: tech_stack, design_system, personality, golden_path
        project_context: dict | None = None,
        # ARCANE 3.0: role determines which system prompt the agent uses
        role: str = "developer",
    ):
        self._client = llm_client
        self._router = router
        self._tool_executor = tool_executor
        self._emit = event_emitter or (lambda *a, **kw: None)
        self._project_id = project_id
        self._chat_id = chat_id or project_id  # fallback for backward compat
        self._user_id = user_id
        self._max_iterations = max_iterations
        self._max_consecutive_errors = max_consecutive_errors
        self._tracker = get_usage_tracker()

        # Run Graph — external lifecycle control
        self._run = RunGraph(
            run_id=run_id,
            max_retries=max_retries,
            idempotency_key=idempotency_key,
        )

        # State
        self._messages: list[dict] = []
        self._iteration = 0
        self._detected_lang = "ru"
        self._consecutive_errors = 0
        self._consecutive_info_messages = 0
        self._current_phase: str = "planning"
        self._artifacts: list[str] = []
        self._final_output: str = ""
        self._start_time: float = 0
        # Project context (tech_stack, design_system, personality, golden_path)
        self._project_context: dict = project_context or {}
        # ARCANE 3.0: role-specific prompt
        self._role: str = role or "developer"

        # Context management (v5)
        self._scratchpad = Scratchpad()
        self._compactor = ContextCompactor(
            max_context_tokens=128000,
            threshold_ratio=0.75,
            keep_recent=12,
        )
        self._goal_anchor = GoalAnchor()

        # Memory v9 engine
        if _memory_available:
            try:
                self._memory = SuperMemoryEngine()
            except Exception as e:
                logger.warning(f"Memory v9 init failed: {e}")
                self._memory = None
        else:
            self._memory = None

    # ─── Properties ─────────────────────────────────────────────────

    @property
    def status(self) -> RunStatus:
        return self._run.status

    @property
    def iteration(self) -> int:
        return self._iteration

    @property
    def run_graph(self) -> RunGraph:
        """Access the run graph for external control (cancel, inspect)."""
        return self._run

    # ─── Intent / Complexity ────────────────────────────────────────

    def _adjust_max_iterations(self, user_message: str) -> None:
        """Dynamically adjust max iterations based on task complexity (PATCH-09)."""
        msg_lower = user_message.lower()
        detected = "moderate"
        for level, cfg in INTENT_COMPLEXITY.items():
            if any(m in msg_lower for m in cfg["markers"]):
                detected = level
                break
        self._max_iterations = INTENT_COMPLEXITY[detected]["max_iterations"]
        logger.info(f"Task complexity: {detected}, max_iterations: {self._max_iterations}")

    # ─── Usage Logging ──────────────────────────────────────────────

    async def _log_usage_to_db(self, model: str, tokens_in: int, tokens_out: int, cost: float) -> None:
        """Explicitly log LLM usage to database for cost tracking."""
        try:
            from api.chat_store import update_chat
            current = self._chat_data.get("total_cost", 0.0) if hasattr(self, "_chat_data") else 0.0
            current_tokens = self._chat_data.get("total_tokens", 0) if hasattr(self, "_chat_data") else 0
            update_chat(self._chat_id, {
                "total_cost": current + cost,
                "total_tokens": current_tokens + tokens_in + tokens_out,
                "model_used": model,
            })  # FIX #2: update_chat(chat_id, dict) — sync, not async
            logger.debug(f"Usage logged: model={model}, tokens={tokens_in+tokens_out}, cost=${cost:.4f}")
        except Exception as e:
            logger.warning(f"Failed to log usage: {e}")

    # ─── System Prompt ──────────────────────────────────────────────

    def _build_system_prompt(self, tools_schema: list[dict]) -> str:
        """
        Build the system prompt — Manus-style.
        Role + tool_use rules + agent_loop + context.
        Auto-detects user language.
        """
        if self._detected_lang == "ru" and self._iteration <= 1:
            try:
                from api.chat_store import get_messages
                msgs = get_messages(self._chat_id)
                for m in msgs:
                    if m.get("role") == "user" and m.get("content"):
                        self._detected_lang = detect_language(m["content"])
                        logger.info(f"Detected language: {self._detected_lang}")
                        break
            except Exception:
                pass

        history_block = self._get_chat_history_context()
        lang = self._detected_lang or "ru"
        # ARCANE 3.0: use role-specific prompt if role is set
        try:
            from shared.prompt_templates import get_role_prompt
            _role_prompt = get_role_prompt(self._role, lang)
            base_prompt = _role_prompt if _role_prompt else build_full_prompt(lang)
        except Exception:
            base_prompt = build_full_prompt(lang)

        # Inject project state + golden path from orchestrator context
        try:
            from shared.prompt_templates import build_context_block
            _ctx_block = build_context_block(
                project_state=self._project_context.get("project_state"),
                golden_path=self._project_context.get("golden_path_hint"),
            )
        except Exception:
            _ctx_block = ""

        # L1: Identity Shield
        from core.identity_shield import get_identity_block
        identity_block = get_identity_block()
        return f"""{identity_block}

{base_prompt}
{_ctx_block}
<budget>
Проект: {self._project_id} | Бюджет: ${self._router.budget_remaining:.2f} | Итерация: {self._iteration}/{self._max_iterations}
</budget>
<run>
Run ID: {self._run.run_id} | Статус: {self._run.status.value} | Попытка: {self._run.retries}/{self._run.max_retries}
</run>
{self._goal_anchor.to_prompt_section()}
{self._scratchpad.to_prompt_section()}
{history_block}{self._get_user_preferences_context()}
{self._get_memory_context()}"""

    def _get_user_preferences_context(self) -> str:
        if hasattr(self, "_user_prefs_prompt") and self._user_prefs_prompt:
            return self._user_prefs_prompt
        return ""

    # ─── GSAP auto-injection ────────────────────────────────────────

    async def _inject_gsap_if_missing(self, filepath: str) -> None:
        """Auto-inject GSAP ScrollTrigger animations into HTML files."""
        import os
        if not os.path.exists(filepath):
            return
        with open(filepath, "r", encoding="utf-8") as f:
            html = f.read()
        if "gsap" in html.lower() and "scrolltrigger" in html.lower():
            return
        if len(html) < 3000 or "</body>" not in html:
            return
        if not hasattr(self, '_gsap_cache') or not self._gsap_cache:
            import os as _os
            _tpl_path = _os.path.join(
                _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))),
                "shared", "templates", "gsap_scroll_trigger.html"
            )
            try:
                with open(_tpl_path, "r", encoding="utf-8") as _tf:
                    self._gsap_cache = _tf.read()
            except Exception as _e:
                logger.warning(f"Failed to load GSAP template: {_e}")
                return
        html = html.replace("</body>", self._gsap_cache + "\n</body>")
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(html)
        logger.info(f"GSAP ScrollTrigger injected into {filepath}")

    # ─── Chat history context ───────────────────────────────────────

    def _get_chat_history_context(self) -> str:
        """Load previous messages from chat_store for conversation context."""
        if not self._project_id:
            return ""
        try:
            from api.chat_store import get_messages
            stored_messages = get_messages(self._chat_id)
            if not stored_messages or len(stored_messages) <= 1:
                return ""
            history_lines = []
            recent = stored_messages[-20:-1] if len(stored_messages) > 1 else []
            for msg in recent:
                role = msg.get("role", "")
                content = msg.get("content", "")
                if not content or not role:
                    continue
                if role == "user":
                    if len(content) > 500:
                        content = content[:500] + "..."
                    history_lines.append(f"Пользователь: {content}")
                elif role == "assistant":
                    if len(content) > 500:
                        content = content[:500] + "..."
                    history_lines.append(f"ARCANE: {content}")
            if not history_lines:
                return ""
            return (
                "\n<conversation_history>\n"
                "Предыдущие сообщения в этом чате (используй этот контекст, НЕ переспрашивай то что уже обсуждали):\n"
                + "\n".join(history_lines)
                + "\n</conversation_history>\n"
            )
        except Exception as e:
            logger.debug(f"Failed to load chat history: {e}")
            return ""

    def _get_memory_context(self) -> str:
        """Get memory context to inject into system prompt."""
        if not self._memory:
            return ""
        try:
            last_user_msg = ""
            for msg in reversed(self._messages):
                if msg.get("role") == "user":
                    last_user_msg = msg.get("content", "")
                    break
            context = self._memory.get_context_for_task(last_user_msg)
            if context:
                return f"\n<memory_context>\n{context}\n</memory_context>"
        except Exception as e:
            logger.warning(f"Memory context retrieval failed: {e}")
        return ""

    # ─── Main entry point ───────────────────────────────────────────

    async def run(self, user_message: str, skip_shield: bool = False) -> dict:
        """
        Main entry point. Run the agent loop for a user message.

        Run Graph flow:
          queued → assigned → running → [review] → done / failed

        Returns a summary dict with status, iterations, cost, artifacts, run graph.
        """
        # L2: Identity Shield check (skip when called from orchestrator)
        if not skip_shield:
            from core.identity_shield import check_and_respond
            _shield = check_and_respond(
            message=user_message,
            user_id=getattr(self, "_user_id", ""),
            chat_id=getattr(self, "_chat_id", ""),
        )
            if _shield.blocked:
                return {
                    "status": "done",
                    "run_id": getattr(self._run, "run_id", ""),
                    "output": _shield.response,
                    "actual_cost": 0.0,
                    "artifacts": [],
                    "iterations": 0,
                    "elapsed_seconds": 0,
                    "shielded": True,
                }
        self._start_time = time.monotonic()
        self._iteration = 0
        self._consecutive_errors = 0

        # ═══ Run Graph: queued → assigned ═══
        self._run.transition(RunStatus.ASSIGNED, "task_received")

        # Idempotency check
        if self._run.idempotency_key:
            cached = await self._check_idempotency(self._run.idempotency_key)
            if cached:
                logger.info(f"Idempotency hit: key={self._run.idempotency_key}")
                return cached

        # Add user message to conversation
        self._messages.append({"role": "user", "content": user_message})

        # Set goal anchor
        if not self._goal_anchor.goal:
            self._goal_anchor.set_goal(user_message)

        # Load user preferences
        try:
            prefs = await get_user_preferences(self._user_id)
            self._user_prefs_prompt = preferences_to_prompt(prefs)
        except Exception as e:
            logger.debug(f"Failed to load user preferences: {e}")
            self._user_prefs_prompt = ""

        # Memory v9: initialize task context
        if self._memory:
            try:
                self._memory.init_task(
                    user_message=user_message,
                    user_id=self._user_id,
                    chat_id=self._chat_id,
                )
            except Exception as e:
                logger.warning(f"Memory init_task failed: {e}")

        # ═══ Run Graph: assigned → running ═══
        self._run.transition(RunStatus.RUNNING, "execution_started")

        await self._emit_event("task_started", {
            "message": user_message,
            "project_id": self._project_id,
            "run_id": self._run.run_id,
        })

        # Classify intent and adjust max iterations
        self._adjust_max_iterations(user_message)

        # ═══ Main agent loop ═══
        try:
            while self._run.status == RunStatus.RUNNING:
                # Check cancellation
                if self._run.is_cancelled:
                    self._run.transition(RunStatus.CANCELLED, "cancel_requested")
                    await self._emit_event("task_cancelled", {
                        "run_id": self._run.run_id,
                        "iteration": self._iteration,
                    })
                    break

                self._iteration += 1

                # Hard timeout — dynamic based on role/task type
                # web_design/media tasks include image_generate (~30-60s each) → need more time
                _role = getattr(self, "_role", "developer")
                _pctx_type = (self._project_context or {}).get("task_type", "")
                _heavy_task = _role in ("art_director",) or _pctx_type in ("web_design", "media")
                _hard_limit = 1800 if _heavy_task else 600  # 30 min vs 10 min
                _elapsed = time.monotonic() - self._start_time
                if _elapsed > _hard_limit:
                    logger.warning(f"HARD TIMEOUT: Task exceeded {_hard_limit}s (elapsed={_elapsed:.0f}s, role={_role})")
                    self._run.transition(RunStatus.FAILED, f"hard_timeout_{_elapsed:.0f}s")
                    await self._emit_event("error", {
                        "message": f"Hard timeout: task exceeded {_hard_limit}s ({_elapsed:.0f}s elapsed).",
                    })
                    if self._artifacts:
                        await self._emit_event("info", {
                            "message": f"Timeout. Delivering {len(self._artifacts)} artifact(s) as-is.",
                        })
                    break

                # Iteration limit
                if self._iteration > self._max_iterations:
                    self._run.transition(RunStatus.FAILED, f"max_iterations_{self._max_iterations}")
                    await self._emit_event("error", {
                        "message": f"Max iterations ({self._max_iterations}) exceeded",
                    })
                    break

                # Run one iteration
                should_continue = await self._run_iteration()
                if not should_continue:
                    break

        except BudgetExceededError as e:
            self._run.transition(RunStatus.BUDGET_EXCEEDED, str(e))
            await self._emit_event("budget_exceeded", {"message": str(e)})

        except Exception as e:
            logger.error(f"Agent loop fatal error: {e}\n{traceback.format_exc()}")
            self._run.transition(RunStatus.FAILED, f"fatal: {str(e)[:100]}")
            await self._emit_event("error", {"message": f"Fatal error: {str(e)[:200]}"})

        # ═══ Post-run ═══
        elapsed = time.monotonic() - self._start_time

        # Memory v9: store episode
        if self._memory:
            try:
                self._memory.after_chat(
                    user_message=user_message,
                    full_response=str(self._artifacts),
                    chat_id=self._chat_id,
                    success=(self._run.status == RunStatus.DONE),
                )
            except Exception as e:
                logger.warning(f"Memory after_chat failed: {e}")

        # UserProfile: extract preferences
        if self._run.status == RunStatus.DONE and len(self._messages) >= 4:
            try:
                prefs = await extract_preferences(
                    messages=self._messages,
                    user_id=self._user_id,
                    chat_id=self._chat_id,
                    llm_client=self._client,
                )
                if prefs:
                    await save_preferences(self._user_id, self._project_id, prefs)
            except Exception as e:
                logger.debug(f"Preference extraction failed: {e}")

        # Auto-deliver fallback
        if self._run.status == RunStatus.DONE:
            await self._auto_deliver_if_needed()

        # L3: Filter output text for identity leaks (FIX-7: artifacts are file paths, not dicts)
        try:
            from core.identity_shield import filter_response as _fr
            if hasattr(self, '_run') and self._run.output:
                self._run.output = _fr(self._run.output)
        except Exception:
            pass
        summary = {
            "status": self._run.status.value,
            "run_id": self._run.run_id,
            "iterations": self._iteration,
            "retries": self._run.retries,
            "total_cost": self._router.total_cost,
            "budget_remaining": self._router.budget_remaining,
            "elapsed_seconds": round(elapsed, 1),
            "artifacts": self._artifacts,
            "run_graph": self._run.to_dict(),
            "output": self._final_output,  # CRIT-1: expose real agent output
        }

        # Store result for idempotency
        if self._run.idempotency_key and self._run.status == RunStatus.DONE:
            await self._store_idempotency(self._run.idempotency_key, summary)

        await self._emit_event("task_completed", summary)
        return summary

    # ─── Idempotency ────────────────────────────────────────────────

    async def _check_idempotency(self, key: str) -> dict | None:
        try:
            from api.chat_store import get_run_by_idempotency_key
            return await get_run_by_idempotency_key(key)
        except (ImportError, Exception) as e:
            logger.debug(f"Idempotency check skipped: {e}")
            return None

    async def _store_idempotency(self, key: str, result: dict) -> None:
        try:
            from api.chat_store import store_run_result
            await store_run_result(key, result)
        except (ImportError, Exception) as e:
            logger.debug(f"Idempotency store skipped: {e}")

    # ─── Auto-deliver fallback ──────────────────────────────────────

    async def _auto_deliver_if_needed(self) -> None:
        """If agent completed but never sent message(type='result'), send it."""
        has_result_tool = any(
            m.get("role") == "assistant"
            and any(
                tc.get("function", {}).get("name") == "message"
                and '"result"' in tc.get("function", {}).get("arguments", "")
                for tc in (m.get("tool_calls", []) if isinstance(m.get("tool_calls"), list) else [])
            )
            for m in self._messages
            if isinstance(m, dict)
        )
        if has_result_tool:
            return

        logger.warning("Agent completed without sending result message — auto-delivering")
        artifacts_list = self._artifacts[:5]
        urls = []
        for a in artifacts_list:
            if a.endswith(('.html', '.htm')):
                import os
                fname = os.path.basename(a)
                urls.append(f"https://arcaneai.ru/workspace/{self._project_id}/{fname}")

        result_text = f"Задача выполнена. Создано файлов: {len(self._artifacts)}."
        if urls:
            result_text += f" Результат: {urls[0]}"
        try:
            await self._emit_event("agent_message", {
                "type": "result",
                "text": result_text,
                "attachments": artifacts_list,
            })
        except Exception as e:
            logger.error(f"Auto-deliver failed: {e}")

    # ─── Cancellation ───────────────────────────────────────────────

    def cancel(self, reason: str = "user_requested") -> bool:
        """Request task cancellation (non-blocking flag)."""
        return self._run.request_cancel(reason)

    # ─── Iteration ──────────────────────────────────────────────────

    async def _run_iteration(self) -> bool:
        """Run a single iteration. Returns True to continue, False to stop."""
        tools_schema = self._tool_executor.get_tools_schema()

        # Context compaction
        if self._compactor.needs_compaction(self._messages, self._iteration):
            logger.info(f"Context compaction triggered at iteration {self._iteration}")
            self._messages = self._compactor.compact(self._messages, self._iteration)

        system_prompt = self._build_system_prompt(tools_schema)
        llm_messages = [
            {"role": "system", "content": system_prompt},
            *self._messages,
        ]

        await self._emit_event("thinking", {
            "iteration": self._iteration,
            "phase": self._current_phase,
            "total_cost": round(self._router.total_cost, 6),
            "budget_remaining": round(self._router.budget_remaining, 4),
        })

        # LLM call with iteration-level timeout (180s)
        ITERATION_TIMEOUT = 600  # Increased for large file generation (was 180)
        try:
            response = await asyncio.wait_for(
                self._router.route(
                    messages=llm_messages,
                    role=self._role,   # FIX #1: use actual agent role, not hardcoded "orchestrator"
                    tools=tools_schema,
                    user_id=self._user_id,
                    project_id=self._project_id,
                    worker="agent_loop",
                    # Role-aware max_tokens: developer is forced to chunk files
                    # 8000 tokens ≈ 300 lines HTML — prevents 71KB single-call disasters
                    max_tokens=8000 if getattr(self, "_role", "") == "developer" else 4096,
                ),
                timeout=ITERATION_TIMEOUT,
            )
        except asyncio.TimeoutError:
            logger.error(f"Iteration {self._iteration} timed out after {ITERATION_TIMEOUT}s")
            self._consecutive_errors += 1
            if self._consecutive_errors >= self._max_consecutive_errors:
                self._run.transition(RunStatus.FAILED, f"timeout_consecutive_{self._consecutive_errors}")
                await self._emit_event("error", {
                    "message": f"LLM call timed out ({self._consecutive_errors} consecutive errors)",
                })
                return False
            self._messages.append({
                "role": "system",
                "content": f"[System: LLM call timed out after {ITERATION_TIMEOUT}s. Retrying.]",
            })
            await asyncio.sleep(2)
            return True
        except BadRequestError as e:
            logger.warning(f"BadRequestError: {str(e)[:200]}")
            cleaned = []
            for msg in self._messages:
                if msg.get("role") == "tool":
                    continue
                if msg.get("role") == "assistant" and msg.get("tool_calls"):
                    tc_names = [tc["function"]["name"] for tc in msg.get("tool_calls", []) if "function" in tc]
                    cleaned.append({
                        "role": "assistant",
                        "content": f"[Previously called tools: {', '.join(tc_names)}. Results applied.]",
                    })
                    continue
                cleaned.append(msg)
            self._messages = cleaned
            self._messages.append({
                "role": "user",
                "content": "[System: Message history cleaned due to model switch. Continue.]",
            })
            return True
        except ProviderUnavailableError as e:
            self._consecutive_errors += 1
            if self._consecutive_errors >= self._max_consecutive_errors:
                self._run.transition(RunStatus.FAILED, f"provider_unavailable_{self._consecutive_errors}")
                return False
            self._messages.append({
                "role": "assistant",
                "content": f"[System: LLM provider error — {str(e)[:100]}. Retrying...]",
            })
            await asyncio.sleep(2)
            return True

        # Track usage
        await self._tracker.record(self._build_usage_record(response, "orchestrator"))

        # Emit cost & model info
        await self._emit_event("cost_update", {
            "total_cost": round(self._router.total_cost, 6),
            "budget_remaining": round(self._router.budget_remaining, 4),
            "iteration_cost": round(response.cost_usd, 6),
            "input_tokens": response.input_tokens,
            "output_tokens": response.output_tokens,
        })
        # CRIT-F: log token usage for ALL models (including FREE with cost=0)
        if response.input_tokens or response.output_tokens:
            await self._log_usage_to_db(
                model=response.model_id or "",
                tokens_in=response.input_tokens,
                tokens_out=response.output_tokens,
                cost=response.cost_usd,
            )
        from shared.model_mask import mask_model_id, get_model_tier
        await self._emit_event("model_info", {
            "engine": mask_model_id(response.model_id),
            "tier": get_model_tier(response.model_id),
        })

        # Process response
        if response.tool_calls:
            self._consecutive_errors = 0
            return await self._execute_tool_calls(response)
        elif response.content:
            # Manus-style: text responses are NEVER acceptable
            self._consecutive_errors += 1
            logger.warning(
                f"Agent returned text instead of tool call (attempt {self._consecutive_errors}): "
                f"{response.content[:200]}"
            )
            self._messages.append({"role": "assistant", "content": response.content})
            self._messages.append({
                "role": "system",
                "content": (
                    "Напоминание: используй инструмент message чтобы ответить пользователю. "
                    "Для финального ответа — message(type='result'). "
                    "Для промежуточного обновления — message(type='info')."
                ),
            })
            if self._consecutive_errors >= 3:
                self._run.transition(RunStatus.FAILED, "no_tool_calls")
                await self._emit_event("error", {"message": "Agent failed to use tools after multiple attempts"})
                return False
            return True
        else:
            self._consecutive_errors += 1
            if self._consecutive_errors >= self._max_consecutive_errors:
                self._run.transition(RunStatus.FAILED, f"empty_responses_{self._consecutive_errors}")
                return False
            return True

    # ─── Tool execution ─────────────────────────────────────────────

    async def _execute_tool_calls(self, response: LLMResponse) -> bool:
        """Execute tool calls from the LLM response."""
        assistant_msg = {"role": "assistant", "content": response.content or ""}
        if response.tool_calls:
            assistant_msg["tool_calls"] = [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.name,
                        "arguments": tc.arguments if isinstance(tc.arguments, str) else __import__("json").dumps(tc.arguments),
                    },
                }
                for tc in response.tool_calls
            ]
        self._messages.append(assistant_msg)

        _TOOL_TO_PHASE = {
            "plan": "planning", "web_search": "planning", "get_template": "planning",
            "search_design_inspiration": "planning",
            "file_write": "coding", "file_edit": "coding", "file_create": "coding",
            "image_generate": "coding", "update_scratchpad": "coding",
            "shell_exec": "deploying", "deploy_to_vps": "deploying",
            "create_archive": "deploying", "ssh_exec": "deploying",
            "browser_navigate": "verifying", "browser_view": "verifying",
            "design_judge": "verifying", "browser_click": "verifying",
            "message": "delivering",
        }

        # ПАТЧ 3: обрезать batch image_generate если превысит лимит
        _img_limit = getattr(self._tool_executor, "_IMAGE_GEN_LIMIT", 8)
        _img_used  = getattr(self._tool_executor, "_image_gen_call_count", 0)
        _img_in_batch = sum(1 for tc in response.tool_calls if tc.name == "image_generate")
        _img_allowed  = max(0, _img_limit - _img_used)
        if _img_in_batch > _img_allowed:
            logger.warning(f"Batch trim: {_img_in_batch} image_generate → keeping {_img_allowed}")
            _seen = 0
            _trimmed = []
            for _tc in response.tool_calls:
                if _tc.name == "image_generate":
                    if _seen < _img_allowed: _trimmed.append(_tc); _seen += 1
                else:
                    _trimmed.append(_tc)
            response.tool_calls = _trimmed

        for tool_call in response.tool_calls:
            # Check cancellation between tool calls
            if self._run.is_cancelled:
                self._run.transition(RunStatus.CANCELLED, "cancel_between_tools")
                return False

            # Phase change detection
            new_phase = _TOOL_TO_PHASE.get(tool_call.name, self._current_phase)
            if new_phase != self._current_phase:
                self._current_phase = new_phase
                await self._emit_event("phase_change", {
                    "phase": new_phase,
                    "iteration": self._iteration,
                    "tool": tool_call.name,
                })

            _step_id_container = {}
            _tc_args = tool_call.arguments if isinstance(tool_call.arguments, dict) else {}
            await self._emit_event("tool_executing", {
                "tool": tool_call.name,
                "iteration": self._iteration,
                "_step_id_container": _step_id_container,
                "brief": _tc_args.get("brief", ""),
            })
            _step_id = _step_id_container.get("step_id")

            try:
                result = await self._tool_executor.execute(
                    tool_name=tool_call.name,
                    arguments=tool_call.arguments,
                    project_id=self._project_id,
                    user_id=self._user_id,
                )

                # Vision injection for browser tools
                _BROWSER_VISION_TOOLS = {
                    "browser_navigate", "browser_view", "browser_click",
                    "browser_input", "browser_scroll", "browser_press_key",
                    "browser_select", "browser_find",
                }
                if tool_call.name in _BROWSER_VISION_TOOLS:
                    _b64 = self._extract_screenshot_b64(result)
                    if _b64:
                        self._messages.append({
                            "role": "tool",
                            "tool_call_id": tool_call.id,
                            "content": [
                                {"type": "text", "text": self._truncate_result(result)},
                                {"type": "image_url", "image_url": {
                                    "url": f"data:image/png;base64,{_b64}",
                                    "detail": "high",
                                }},
                            ],
                        })
                    else:
                        self._messages.append({
                            "role": "tool",
                            "tool_call_id": tool_call.id,
                            "content": self._truncate_result(result),
                        })
                else:
                    self._messages.append({
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": self._truncate_result(result),
                    })

                preview_len = 10000 if tool_call.name == "message" else 200
                await self._emit_event("tool_completed", {
                    "tool": tool_call.name,
                    "success": True,
                    "result_preview": str(result)[:preview_len],
                    "step_id": _step_id,
                })

                # Scratchpad update
                if tool_call.name == "update_scratchpad":
                    _args = tool_call.arguments if isinstance(tool_call.arguments, dict) else {}
                    _key = _args.get("key", "")
                    _val = _args.get("value", "")
                    if _key:
                        self._scratchpad.update(_key, _val)

                # Plan tool → emit plan_update
                if tool_call.name == "plan" and isinstance(tool_call.arguments, dict):
                    phases = tool_call.arguments.get("phases", [])
                    if phases:
                        await self._emit_event("plan_update", {
                            "phases": phases,
                            "current_phase_id": tool_call.arguments.get("current_phase_id", 1),
                            "goal": tool_call.arguments.get("goal", ""),
                        })

                # Memory v9: record action
                if self._memory:
                    try:
                        self._memory.record_action(
                            tool_name=tool_call.name,
                            params=tool_call.arguments if isinstance(tool_call.arguments, dict) else {},
                            result=str(result)[:500],
                            success=True,
                        )
                    except Exception:
                        pass

                # Reset consecutive info counter on real work
                if tool_call.name != "message":
                    self._consecutive_info_messages = 0

                # Message tool special types
                if tool_call.name == "message" and isinstance(tool_call.arguments, dict):
                    msg_type = tool_call.arguments.get("type", "")
                    if msg_type == "result":
                        # Quality gate: warn if agent never verified output via file_read
                        _has_file_read = any(
                            m.get("role") == "assistant" and
                            any(tc.get("function", {}).get("name") == "file_read"
                                for tc in (m.get("tool_calls") or []))
                            for m in self._messages
                        )
                        if self._artifacts and not _has_file_read:
                            logger.warning(f"Agent delivering result without file_read verification")
                        _attachments = tool_call.arguments.get("attachments", [])
                        if _attachments:
                            logger.info(f"Message result: {len(_attachments)} attachments")
                        _all_artifacts = list(set(self._artifacts + list(_attachments)))
                        # CRIT-1: schema uses 'content' not 'text'
                        self._final_output = tool_call.arguments.get("content", tool_call.arguments.get("text", ""))
                        self._run.output = self._final_output
                        await self._emit_event("task_completed", {
                            "summary": self._final_output[:200],
                            "artifacts": _all_artifacts,
                            "iterations": self._iteration,
                            "total_cost": round(self._router.total_cost, 6),
                        })
                        self._run.transition(RunStatus.DONE, "result_delivered")
                        return False
                    elif msg_type == "ask":
                        self._run.transition(RunStatus.WAITING_USER, "ask_user")
                        return False
                    elif msg_type == "info":
                        self._consecutive_info_messages = getattr(self, '_consecutive_info_messages', 0) + 1
                        if self._consecutive_info_messages >= 3:
                            logger.warning(f"Agent sent {self._consecutive_info_messages} consecutive info messages — force-completing")
                            self._run.transition(RunStatus.DONE, "info_loop_break")
                            return False

                # Track artifacts + GSAP injection
                if tool_call.name in ("file_write", "file_create", "file_edit"):
                    path = tool_call.arguments.get("path", "")
                    if path:
                        self._artifacts.append(path)
                        if path.endswith(".html"):
                            try:
                                await self._inject_gsap_if_missing(path)
                            except Exception as _gsap_err:
                                logger.debug(f"GSAP injection skipped: {_gsap_err}")

            except Exception as e:
                error_str = str(e)
                error_report = analyze_error(error_str)

                self._messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": (
                        f"ERROR: {error_str[:1000]}\n\n"
                        f"Analysis: {error_report.root_cause}\n"
                        f"Suggested fixes: {', '.join(error_report.suggested_fixes)}"
                    ),
                })

                await self._emit_event("tool_error", {
                    "tool": tool_call.name,
                    "error": error_str[:200],
                    "category": error_report.category.value,
                    "severity": error_report.severity.value,
                    "step_id": _step_id,
                })

                self._consecutive_errors += 1

                if is_critical(error_report):
                    self._run.transition(RunStatus.FAILED, f"critical_error: {error_str[:100]}")
                    return False

                if self._consecutive_errors >= self._max_consecutive_errors:
                    self._run.transition(RunStatus.FAILED, f"consecutive_errors_{self._consecutive_errors}")
                    return False

        return True

    # ─── Helpers ────────────────────────────────────────────────────

    def _is_task_complete(self, content: str) -> bool:
        """Deprecated: completion signaled ONLY by message(type='result')."""
        return False

    def _extract_screenshot_b64(self, result: Any) -> str | None:
        try:
            result_str = str(result)
            marker = "screenshot_b64:"
            idx = result_str.find(marker)
            if idx != -1:
                b64_start = idx + len(marker)
                b64_end = result_str.find("\n", b64_start)
                if b64_end == -1:
                    b64_end = len(result_str)
                return result_str[b64_start:b64_end].strip()
            return None
        except Exception:
            return None

    def _truncate_result(self, result: Any, max_length: int = 4000) -> str:
        text = str(result)
        if len(text) <= max_length:
            return text
        half = max_length // 2
        return text[:half] + f"\n\n... [truncated {len(text) - max_length} chars] ...\n\n" + text[-half:]

    def _build_usage_record(self, response: LLMResponse, role: str):
        from shared.models.schemas import UsageRecord
        return UsageRecord(
            project_id=self._project_id,
            user_id=self._user_id,
            model_id=response.model_id,
            provider=response.provider,
            tier=response.tier,
            worker="agent_loop",
            max_tokens=65536,
            role=role,
            input_tokens=response.input_tokens,
            output_tokens=response.output_tokens,
            cached_tokens=response.cached_tokens,
            cost_usd=response.cost_usd,
            latency_ms=response.latency_ms,
        )

    # ─── Events ─────────────────────────────────────────────────────

    async def _emit_event(self, event_type: str, data: dict) -> None:
        event = {
            "type": event_type,
            "project_id": self._project_id,
            "run_id": self._run.run_id,
            "iteration": self._iteration,
            "max_iterations": self._max_iterations,
            "run_status": self._run.status.value,
            "total_cost": round(self._router.total_cost, 6) if hasattr(self, "_router") else 0,
            "timestamp": time.time(),
            **data,
        }
        try:
            if asyncio.iscoroutinefunction(self._emit):
                await self._emit(event)
            else:
                self._emit(event)
        except Exception as e:
            logger.warning(f"Failed to emit event: {e}")

        log_with_data(
            logger, "INFO",
            f"Event: {event_type}",
            **{k: v for k, v in data.items() if not isinstance(v, (list, dict))},
        )

    # ─── Resume / Continue ──────────────────────────────────────────

    async def resume(self, user_response: str) -> dict:
        """Resume after waiting for user input."""
        if self._run.status != RunStatus.WAITING_USER:
            raise RuntimeError(f"Cannot resume: status is {self._run.status.value}")
        self._messages.append({"role": "user", "content": user_response})
        self._run.transition(RunStatus.RUNNING, "user_responded")
        self._consecutive_errors = 0
        return await self._continue_loop()

    async def _continue_loop(self) -> dict:
        try:
            while self._run.status == RunStatus.RUNNING:
                if self._run.is_cancelled:
                    self._run.transition(RunStatus.CANCELLED, "cancel_in_continue")
                    break
                self._iteration += 1
                if self._iteration > self._max_iterations:
                    self._run.transition(RunStatus.FAILED, "max_iterations_continue")
                    break
                should_continue = await self._run_iteration()
                if not should_continue:
                    break
        except BudgetExceededError as e:
            self._run.transition(RunStatus.BUDGET_EXCEEDED, str(e))
        except Exception as e:
            self._run.transition(RunStatus.FAILED, f"continue_error: {str(e)[:100]}")
            logger.error(f"Agent loop error: {e}")

        elapsed = time.monotonic() - self._start_time
        return {
            "status": self._run.status.value,
            "run_id": self._run.run_id,
            "iterations": self._iteration,
            "total_cost": self._router.total_cost,
            "elapsed_seconds": round(elapsed, 1),
            "artifacts": self._artifacts,
            "run_graph": self._run.to_dict(),
        }

    # ─── State inspection ───────────────────────────────────────────

    def get_state(self) -> dict:
        return {
            "status": self._run.status.value,
            "run_id": self._run.run_id,
            "iteration": self._iteration,
            "consecutive_errors": self._consecutive_errors,
            "message_count": len(self._messages),
            "current_phase": self._current_phase,
            "total_cost": self._router.total_cost,
            "budget_remaining": self._router.budget_remaining,
            "artifacts": self._artifacts,
            "scratchpad": self._scratchpad.to_dict(),
            "goal_anchor": self._goal_anchor.to_dict(),
            "compaction_count": self._compactor.compaction_count,
            "run_graph": self._run.to_dict(),
        }

    def get_serializable_state(self) -> dict:
        return {
            "messages": self._messages,
            "iteration": self._iteration,
            "consecutive_errors": self._consecutive_errors,
            "current_phase": self._current_phase,
            "artifacts": self._artifacts,
            "scratchpad": self._scratchpad.to_dict(),
            "goal_anchor": self._goal_anchor.to_dict(),
            "total_cost": self._router.total_cost,
            "budget_remaining": self._router.budget_remaining,
            "run_graph": self._run.to_dict(),
        }

    def restore_state(self, state: dict) -> None:
        self._messages = state.get("messages", [])
        self._iteration = state.get("iteration", 0)
        self._consecutive_errors = state.get("consecutive_errors", 0)
        self._current_phase = state.get("current_phase")
        self._artifacts = state.get("artifacts", [])
        if "scratchpad" in state:
            self._scratchpad = Scratchpad.from_dict(state["scratchpad"])
        if "goal_anchor" in state:
            self._goal_anchor = GoalAnchor.from_dict(state["goal_anchor"])
        if "run_graph" in state:
            rg = state["run_graph"]
            self._run.run_id = rg.get("run_id", self._run.run_id)
            self._run.retries = rg.get("retries", 0)
            try:
                self._run.status = RunStatus(rg.get("status", "running"))
            except ValueError:
                self._run.status = RunStatus.RUNNING
        logger.info(
            f"Agent state restored: iteration={self._iteration}, "
            f"messages={len(self._messages)}, artifacts={len(self._artifacts)}, "
            f"run_id={self._run.run_id}, run_status={self._run.status.value}"
        )
