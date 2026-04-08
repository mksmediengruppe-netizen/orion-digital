"""
ARCANE Model Router
Intelligent routing of LLM requests based on:
  - Role (coding, qa, browser, ssh, planner, orchestrator, search, classifier)
  - Tier (NANO → FAST → STANDARD → GENIUS → DEEP)
  - Preset mode (AUTO, MANUAL, TOP, OPTIMUM, LITE, FREE) via PresetManager
  - Automatic escalation on failure
  - Fallback chains when a provider is down
  - Tool-calling capability gating (fail-closed)
  - Budget thresholds: 80% warn, 95% pause, 100% stop (spec §8)
"""

from __future__ import annotations

import asyncio
import warnings
from collections import deque
from typing import Any, Awaitable, Callable, Optional

from shared.llm.client import (
    BudgetExceededError,
    ProviderUnavailableError,
    UnifiedLLMClient,
)
from shared.llm.model_registry import (
    MODELS,
    ROLES,
    STRATEGY_TIER_MAP,
    get_fallback_model,
    get_model_for_role,
    get_next_tier,
)
from shared.llm.preset_manager import (
    PresetManager,
    PresetMode,
    ResolvedModel,
    ToolCapability,
    model_supports,
)
from shared.models.schemas import (
    LLMRequest,
    LLMResponse,
    Tier,
    UsageRecord,
)
from shared.utils.logger import get_logger, log_with_data

logger = get_logger("llm.router")

# Maximum usage records kept in memory before oldest are discarded.
_USAGE_LOG_MAX = 2000


# ═════════════════════════════════════════════════════════════════════════════
# Budget event enum — spec §8: 80% warning, 95% pause, 100% stop
# ═════════════════════════════════════════════════════════════════════════════

class BudgetEvent:
    WARNING_80 = "budget_warning_80"
    PAUSE_95 = "budget_pause_95"
    STOP_100 = "budget_stop_100"


# Type alias for the budget callback
BudgetCallback = Callable[[str, float, float, Optional[str]], Awaitable[None] | None]
# signature: (event: str, spent: float, limit: float, project_id: str | None)


class ModelRouter:
    """
    Routes LLM requests through the correct model based on role,
    preset mode, and tier.  Handles automatic escalation when a lower
    tier fails to produce acceptable results.

    Usage (new — with PresetManager):
        pm     = PresetManager(mode=PresetMode.TOP)
        router = ModelRouter(client, preset_manager=pm)
        resp   = await router.route(messages=[...], role="coding")

    Usage (legacy — bare strategy string, still supported but deprecated):
        router = ModelRouter(client, strategy="balance")
        resp   = await router.route(messages=[...], role="coding")
    """

    def __init__(
        self,
        client: UnifiedLLMClient,
        strategy: str = "balance",
        budget_limit: float = 5.0,
        budget_spent: float = 0.0,
        preset_manager: PresetManager | None = None,
        budget_callback: BudgetCallback | None = None,
    ):
        self._client = client
        self._budget_limit = budget_limit
        self._budget_spent = budget_spent
        self._budget_lock = asyncio.Lock()
        self._budget_callback = budget_callback
        # Track which thresholds have already fired to avoid repeats
        self._budget_warned_80 = False
        self._budget_paused_95 = False
        self._usage_log: deque[UsageRecord] = deque(maxlen=_USAGE_LOG_MAX)

        # PresetManager is the new authority for tier/model resolution.
        if preset_manager is not None:
            self._preset = preset_manager
        else:
            if strategy != "balance":
                warnings.warn(
                    "ModelRouter(strategy=...) is deprecated. "
                    "Use preset_manager=PresetManager.from_dict({...}) instead.",
                    DeprecationWarning,
                    stacklevel=2,
                )
            self._preset = PresetManager.from_dict({"strategy": strategy})

        self._strategy = self._preset.strategy_key

    # ── Public properties ─────────────────────────────────────────────────

    @property
    def preset_manager(self) -> PresetManager:
        return self._preset

    @property
    def budget_remaining(self) -> float:
        return max(0.0, self._budget_limit - self._budget_spent)

    @property
    def total_cost(self) -> float:
        return self._budget_spent

    @property
    def usage_log(self) -> list[UsageRecord]:
        return list(self._usage_log)

    # ── Preset hot-swap ───────────────────────────────────────────────────

    def set_preset(self, preset: PresetManager) -> None:
        """Hot-swap the preset manager (e.g. user switches mode mid-session)."""
        self._preset = preset
        self._strategy = preset.strategy_key
        log_with_data(
            logger, "INFO",
            f"Preset changed to {preset.mode.value}",
            mode=preset.mode.value,
            strategy=self._strategy,
        )

    # ── Resolution helpers ────────────────────────────────────────────────

    def _resolve_tier(self, role: str, tier_override: Optional[Tier] = None) -> Tier:
        """Determine the starting tier for a role via PresetManager."""
        return self._preset.resolve_tier(role, tier_override)

    def _resolve_model_id(
        self,
        role: str,
        tier: Tier,
        require_capability: ToolCapability | None = None,
    ) -> ResolvedModel | None:
        """
        Get the resolved model for a role.

        Returns ResolvedModel with provenance, or None.
        PresetManager handles MANUAL/AUTO overrides and capability gating
        (fail-closed).
        """
        resolved = self._preset.resolve_model_full(
            role,
            tier_override=tier,
            require_capability=require_capability,
        )
        if resolved:
            return resolved

        # Fallback: classic registry lookup (no capability gate — last resort)
        spec = get_model_for_role(role, tier)
        if spec:
            return ResolvedModel(model_id=spec.id, tier=tier, source="registry_fallback")
        return None

    # ── Main routing ──────────────────────────────────────────────────────

    async def route(
        self,
        messages: list[dict],
        role: str,
        tools: list[dict] | None = None,
        tier_override: Tier | None = None,
        temperature: float = 0.0,
        max_tokens: int | None = None,
        user_id: str | None = None,
        project_id: str | None = None,
        worker: str = "unknown",
        allow_escalation: bool = True,
        max_escalations: int = 2,
        require_capability: ToolCapability | None = None,
    ) -> LLMResponse:
        """
        Route a request through the model hierarchy.

        Flow:
        1. Atomic budget check (asyncio.Lock)
        2. Resolve starting tier from PresetManager (mode + role)
        3. Get model (MANUAL/AUTO overrides respected, capability fail-closed)
        4. Call UnifiedLLMClient
        5. If provider unavailable → try fallback chain (with capability check)
        6. If still failing → escalate to next tier
        7. Track usage, fire budget callbacks (80%/95%/100%)
        """
        # ── Atomic budget pre-flight ──────────────────────────────────────
        async with self._budget_lock:
            if self._budget_spent >= self._budget_limit:
                raise BudgetExceededError(
                    f"Budget exhausted: ${self._budget_spent:.2f} / ${self._budget_limit:.2f}"
                )

        # Auto-detect: if tools are provided, ensure function calling support
        if require_capability is None and tools:
            require_capability = ToolCapability.FUNCTION_CALLING

        current_tier = self._resolve_tier(role, tier_override)
        escalation_count = 0
        prev_model_id: str | None = None  # detect stuck escalation

        while True:
            resolved = self._resolve_model_id(role, current_tier, require_capability)
            if not resolved:
                # No model for this tier — count as escalation attempt
                escalation_count += 1
                if escalation_count > max_escalations:
                    raise ValueError(
                        f"No model available for role={role}, tier={current_tier}, "
                        f"exhausted {escalation_count} escalation attempts"
                    )
                next_tier = get_next_tier(current_tier)
                if next_tier and allow_escalation:
                    current_tier = next_tier
                    continue
                raise ValueError(
                    f"No model available for role={role}, tier={current_tier}"
                )

            model_id = resolved.model_id

            # Detect stuck escalation: if we escalated but got same model, skip
            if model_id == prev_model_id and escalation_count > 0:
                next_tier = get_next_tier(current_tier)
                if next_tier and allow_escalation and escalation_count < max_escalations:
                    escalation_count += 1
                    current_tier = next_tier
                    continue
                # Can't escalate further, proceed with what we have

            prev_model_id = model_id

            log_with_data(
                logger, "INFO",
                f"Routing request",
                role=role,
                tier=current_tier.value,
                model=model_id,
                mode=self._preset.mode.value,
                source=resolved.source,
                strategy=self._strategy,
                budget_remaining=self.budget_remaining,
                escalation=escalation_count,
            )

            request = LLMRequest(
                messages=messages,
                model_id=model_id,
                role=role,
                tier=current_tier,
                tools=tools,
                temperature=temperature,
                max_tokens=max_tokens,
                stream=False,
                user_id=user_id,
                project_id=project_id,
            )

            try:
                response = await self._client.complete(
                    request, role=role, worker=worker
                )
                response.tier = current_tier

                await self._track_usage(
                    response, role, worker, user_id, project_id,
                    escalated=(escalation_count > 0),
                )

                return response

            except ProviderUnavailableError:
                # STEP 1: Try fallback chain (with capability check)
                fallback_response = await self._try_fallback(
                    role=role,
                    failed_model_id=model_id,
                    messages=messages,
                    tools=tools,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    user_id=user_id,
                    project_id=project_id,
                    worker=worker,
                    require_capability=require_capability,
                )
                if fallback_response:
                    await self._track_usage(
                        fallback_response, role, worker, user_id, project_id,
                        escalated=True,
                    )
                    return fallback_response

                # STEP 2: Fallback failed — escalate tier
                if allow_escalation and escalation_count < max_escalations:
                    next_tier = get_next_tier(current_tier)
                    if next_tier:
                        escalation_count += 1
                        log_with_data(
                            logger, "WARNING",
                            f"Escalating from {current_tier.value} to {next_tier.value}",
                            role=role,
                            from_tier=current_tier.value,
                            to_tier=next_tier.value,
                            escalation=escalation_count,
                        )
                        current_tier = next_tier
                        continue
                raise

    async def _try_fallback(
        self,
        role: str,
        failed_model_id: str,
        messages: list[dict],
        tools: list[dict] | None,
        temperature: float,
        max_tokens: int | None,
        user_id: str | None,
        project_id: str | None,
        worker: str,
        require_capability: ToolCapability | None,
    ) -> LLMResponse | None:
        """
        Try fallback model with capability validation.
        Returns response or None if fallback also fails / is incapable.
        """
        fallback_spec = get_fallback_model(failed_model_id)  # ARCANE 3.0: 1 arg only
        if not fallback_spec:
            return None

        # Capability gate on fallback (fail-closed)
        if require_capability and not model_supports(fallback_spec.id, require_capability):
            log_with_data(
                logger, "WARNING",
                f"Fallback {fallback_spec.id} lacks {require_capability.value}, skipping",
                role=role,
            )
            return None

        log_with_data(
            logger, "INFO",
            f"Trying fallback: {failed_model_id} → {fallback_spec.id}",
            role=role,
            from_model=failed_model_id,
            to_model=fallback_spec.id,
        )

        # Strip tools if fallback doesn't support function calling
        fallback_tools = tools
        if tools and not model_supports(fallback_spec.id, ToolCapability.FUNCTION_CALLING):
            log_with_data(
                logger, "WARNING",
                f"Fallback {fallback_spec.id} lacks function_calling, stripping tools",
                role=role,
            )
            fallback_tools = None

        fallback_request = LLMRequest(
            messages=messages,
            model_id=fallback_spec.id,
            role=role,
            tier=None,  # fallback tier is indeterminate
            tools=fallback_tools,
            temperature=temperature,
            max_tokens=max_tokens,
            stream=False,
            user_id=user_id,
            project_id=project_id,
        )
        try:
            response = await self._client.complete(
                fallback_request, role=role, worker=worker
            )
            # Record ACTUAL model used, not the tier of the failed model
            response.tier = None  # signal: this was a fallback, tier is N/A
            return response
        except ProviderUnavailableError:
            log_with_data(
                logger, "WARNING",
                f"Fallback {fallback_spec.id} also unavailable",
                role=role,
            )
            return None

    # ── Self-healing routing ──────────────────────────────────────────────

    async def route_with_self_healing(
        self,
        messages: list[dict],
        role: str,
        tools: list[dict] | None = None,
        user_id: str | None = None,
        project_id: str | None = None,
        worker: str = "unknown",
        max_heal_iterations: int = 5,
        error_handler: Callable[..., Awaitable[bool]] | None = None,
        require_capability: ToolCapability | None = None,
    ) -> LLMResponse:
        """
        Route with automatic tier escalation on repeated failures.

        Keeps track of last_response so we never make an extra API call
        after exhausting iterations.

        Args:
            error_handler: async callable(response, iteration) -> bool
                Returns True if the response is acceptable, False to retry.
            require_capability: optional capability the model must support.
        """
        current_tier = self._resolve_tier(role)
        total_failures = 0
        failures_at_tier = 0
        max_failures_before_escalation = 2
        last_response: LLMResponse | None = None

        for iteration in range(1, max_heal_iterations + 1):
            try:
                response = await self.route(
                    messages=messages,
                    role=role,
                    tools=tools,
                    tier_override=current_tier,
                    user_id=user_id,
                    project_id=project_id,
                    worker=worker,
                    allow_escalation=False,
                    require_capability=require_capability,
                )
                last_response = response

                if error_handler is None:
                    return response

                is_ok = await error_handler(response, iteration)
                if is_ok:
                    return response

                # Not acceptable — count failure
                total_failures += 1
                failures_at_tier += 1
                if failures_at_tier >= max_failures_before_escalation:
                    next_tier = get_next_tier(current_tier)
                    if next_tier:
                        log_with_data(
                            logger, "WARNING",
                            f"Self-healing escalation after {failures_at_tier} failures",
                            role=role,
                            from_tier=current_tier.value,
                            to_tier=next_tier.value,
                            iteration=iteration,
                            total_failures=total_failures,
                        )
                        current_tier = next_tier
                        failures_at_tier = 0

            except ProviderUnavailableError:
                total_failures += 1
                # Don't reset failures_at_tier — provider failure still
                # counts toward escalation threshold
                failures_at_tier += 1
                if failures_at_tier >= max_failures_before_escalation:
                    next_tier = get_next_tier(current_tier)
                    if next_tier:
                        current_tier = next_tier
                        failures_at_tier = 0
                        continue
                    raise
                continue

        # All iterations exhausted — return last response if we have one
        log_with_data(
            logger, "ERROR",
            f"Self-healing exhausted after {max_heal_iterations} iterations "
            f"({total_failures} total failures)",
            role=role,
            final_tier=current_tier.value,
        )
        if last_response is not None:
            return last_response

        # Never got any response — one final attempt (unavoidable)
        return await self.route(
            messages=messages,
            role=role,
            tools=tools,
            tier_override=current_tier,
            user_id=user_id,
            project_id=project_id,
            worker=worker,
            require_capability=require_capability,
        )

    # ── Usage tracking ────────────────────────────────────────────────────

    async def _track_usage(
        self,
        response: LLMResponse,
        role: str,
        worker: str,
        user_id: str | None,
        project_id: str | None,
        escalated: bool = False,
    ) -> None:
        """Record usage, update budget atomically, fire budget callbacks."""
        async with self._budget_lock:
            self._budget_spent += response.cost_usd
            current_spent = self._budget_spent
            current_limit = self._budget_limit

        record = UsageRecord(
            project_id=project_id or "",
            user_id=user_id or "",
            model_id=response.model_id,
            provider=response.provider,
            tier=response.tier,
            worker=worker,
            role=role,
            input_tokens=response.input_tokens,
            output_tokens=response.output_tokens,
            cached_tokens=response.cached_tokens,
            cost_usd=response.cost_usd,
            latency_ms=response.latency_ms,
            escalated=escalated,
        )
        self._usage_log.append(record)

        # ── Budget thresholds (spec §8) ───────────────────────────────────
        if current_limit <= 0:
            return
        pct = current_spent / current_limit * 100

        if pct >= 100:
            await self._fire_budget_event(
                BudgetEvent.STOP_100, current_spent, current_limit, project_id,
            )
        elif pct >= 95 and not self._budget_paused_95:
            self._budget_paused_95 = True
            await self._fire_budget_event(
                BudgetEvent.PAUSE_95, current_spent, current_limit, project_id,
            )
        elif pct >= 80 and not self._budget_warned_80:
            self._budget_warned_80 = True
            await self._fire_budget_event(
                BudgetEvent.WARNING_80, current_spent, current_limit, project_id,
            )

    async def _fire_budget_event(
        self,
        event: str,
        spent: float,
        limit: float,
        project_id: str | None,
    ) -> None:
        """Log and optionally invoke the budget callback."""
        level = "ERROR" if event == BudgetEvent.STOP_100 else "WARNING"
        log_with_data(
            logger, level,
            f"Budget {event}: ${spent:.2f} / ${limit:.2f} "
            f"({spent / limit * 100:.0f}%)",
            budget_spent=spent,
            budget_limit=limit,
            project_id=project_id,
            event=event,
        )
        if self._budget_callback:
            result = self._budget_callback(event, spent, limit, project_id)
            if asyncio.iscoroutine(result):
                await result

    def update_budget(
        self,
        new_limit: float | None = None,
        new_spent: float | None = None,
    ) -> None:
        """Update budget parameters (e.g., after loading from DB)."""
        if new_limit is not None:
            self._budget_limit = new_limit
        if new_spent is not None:
            self._budget_spent = new_spent
        # Reset threshold flags if budget was replenished
        if new_limit is not None or new_spent is not None:
            pct = (self._budget_spent / self._budget_limit * 100) if self._budget_limit > 0 else 0
            if pct < 80:
                self._budget_warned_80 = False
                self._budget_paused_95 = False
            elif pct < 95:
                self._budget_paused_95 = False
