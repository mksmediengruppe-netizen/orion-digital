"""
budget_controller.py — Arcane 2 Budget Controller

Спецификация v1.4, секция 8 + 14:
- Лимит per project / per month / per task
- Real-time трекинг расходов
- Manus: кредиты → доллары ($0.00125/кредит)
- 80% = предупреждение, 95% = пауза, 100% = стоп
- Приоритет даунгрейда: Тексты → Фото → Review → Дизайн → Код (последний)
- Dashboard: по месяцу, проекту, задаче, агенту

Audit fixes (v2):
- Per-project BudgetLimits (не shared mutable)
- Atomic save (write + os.replace)
- Auto-save в record()
- Дедупликация в load_project() (clear before append)
- _stopped set для дедупликации STOP callback
- Отдельный image_model параметр
- pre_check() проверяет все 3 лимита (task + project + global)
- auto_downgrade() итерирует до fit или исчерпания
- auto_downgrade() учитывает images и manus
- Fail-closed на unknown models (raise, не $0)
- Валидация inputs (no negative tokens/credits)
- entries_count заполняется в _make_snapshot()
- DOWNGRADE_MAP[CODE] — порядок по убыванию стоимости
- "flux-schnell" → "flux-2-schnell"
- dashboard() — single pass
- TTL / max entries в памяти
- Thread lock на _entries
- effective_status() показывает КАКОЙ лимит сработал
- Global budget persistence
- Path traversal protection на project_id
- Схема budget.json совместима с project_manager.py
"""

from __future__ import annotations

import json
import os
import re
import logging
import tempfile
import threading
from enum import Enum
from pathlib import Path
from dataclasses import dataclass, field, asdict
from typing import Optional, Callable
from datetime import datetime, timezone

logger = logging.getLogger("arcane.budget")


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MANUS_CREDIT_COST_USD = 0.00125  # $0.00125 per Manus credit

# Thresholds (fraction of limit)
THRESHOLD_WARNING = 0.80
THRESHOLD_PAUSE = 0.95
THRESHOLD_STOP = 1.00

# Memory management
MAX_ENTRIES_IN_MEMORY = 10_000
ENTRIES_TRIM_TO = 8_000  # keep this many after trim

# Safe project_id pattern
_SAFE_PROJECT_ID = re.compile(r"^[a-zA-Z0-9_\-]{1,128}$")


class BudgetStatus(str, Enum):
    """Current budget state."""
    OK = "ok"
    WARNING = "warning"      # ≥80%
    PAUSED = "paused"        # ≥95%
    STOPPED = "stopped"      # ≥100%
    UNLIMITED = "unlimited"  # No limit set


class LimitScope(str, Enum):
    """Which limit triggered the status."""
    TASK = "task"
    PROJECT = "project"
    GLOBAL = "global"
    NONE = "none"


class TaskCategory(str, Enum):
    """Task categories — order defines downgrade priority (first = downgrade first)."""
    TEXT = "text"
    PHOTO = "photo"
    REVIEW = "review"
    DESIGN = "design"
    CODE = "code"


# Downgrade priority: texts first, code last
DOWNGRADE_PRIORITY: list[TaskCategory] = [
    TaskCategory.TEXT,
    TaskCategory.PHOTO,
    TaskCategory.REVIEW,
    TaskCategory.DESIGN,
    TaskCategory.CODE,
]


# ---------------------------------------------------------------------------
# Model pricing ($/M tokens) — from spec section 3.1
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ModelPricing:
    """Price per 1M tokens (input/output) in USD."""
    input_per_m: float
    output_per_m: float

    def cost(self, input_tokens: int, output_tokens: int) -> float:
        return (
            self.input_per_m * input_tokens / 1_000_000
            + self.output_per_m * output_tokens / 1_000_000
        )


MODEL_PRICES: dict[str, ModelPricing] = {
    # Claude
    "claude-opus-4.6":   ModelPricing(5.0, 25.0),
    "claude-sonnet-4.6": ModelPricing(3.0, 15.0),
    "claude-haiku-4.5":  ModelPricing(1.0, 5.0),
    # OpenAI
    "gpt-5.4":           ModelPricing(2.50, 15.0),
    "gpt-5.4-mini":      ModelPricing(0.75, 4.50),
    "gpt-5.4-nano":      ModelPricing(0.20, 1.25),
    # Google
    "gemini-3.1-pro":    ModelPricing(2.0, 12.0),
    "gemini-2.5-flash":  ModelPricing(0.30, 2.50),
    # Others
    "deepseek-v3.2":     ModelPricing(0.28, 0.42),
    "minimax-m2.5":      ModelPricing(0.30, 1.20),
    "kimi-k2.5":         ModelPricing(0.0, 0.0),   # Free*
    "step-3.5-flash":    ModelPricing(0.0, 0.0),   # Free
    "nemotron-3-super":  ModelPricing(0.0, 0.0),   # Free
}

# Image generation pricing ($/image) — spec section 3.2
IMAGE_PRICES: dict[str, float] = {
    "flux-2-pro":     0.055,
    "midjourney-v8":  0.10,
    "ideogram-v3":    0.04,
    "recraft-v4":     0.04,
    "flux-2-schnell": 0.015,
    "pexels":         0.0,
}


# ---------------------------------------------------------------------------
# Downgrade tiers — cheaper alternatives per category
# Ordered strictly by descending cost (output_per_m as primary key)
# ---------------------------------------------------------------------------

DOWNGRADE_MAP: dict[TaskCategory, list[str]] = {
    TaskCategory.TEXT: [
        "claude-sonnet-4.6",   # $3/$15
        "gpt-5.4-mini",        # $0.75/$4.50
        "deepseek-v3.2",       # $0.28/$0.42
        "step-3.5-flash",      # free
    ],
    TaskCategory.PHOTO: [
        "flux-2-pro",          # $0.055
        "ideogram-v3",         # $0.04
        "recraft-v4",          # $0.04
        "flux-2-schnell",      # $0.015
        "pexels",              # free
    ],
    TaskCategory.REVIEW: [
        "gpt-5.4",             # $2.50/$15
        "claude-sonnet-4.6",   # $3/$15
        "gemini-2.5-flash",    # $0.30/$2.50
        "deepseek-v3.2",       # $0.28/$0.42
    ],
    TaskCategory.DESIGN: [
        "claude-sonnet-4.6",   # $3/$15
        "gemini-3.1-pro",      # $2/$12
        "deepseek-v3.2",       # $0.28/$0.42
        "kimi-k2.5",           # free
    ],
    TaskCategory.CODE: [
        "claude-opus-4.6",     # $5/$25
        "gpt-5.4",             # $2.50/$15
        "claude-sonnet-4.6",   # $3/$15
        "gemini-3.1-pro",      # $2/$12
        "deepseek-v3.2",       # $0.28/$0.42
    ],
}


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

@dataclass
class UsageEntry:
    """Single spend event."""
    timestamp: str
    project_id: str
    task_id: str
    model: str
    category: str
    input_tokens: int = 0
    output_tokens: int = 0
    image_model: str = ""
    images: int = 0
    manus_credits: int = 0
    cost_usd: float = 0.0

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class BudgetLimits:
    """Configurable budget limits in USD. One instance per project."""
    per_task: Optional[float] = None
    per_project_month: Optional[float] = None


@dataclass
class BudgetSnapshot:
    """Aggregated spend snapshot."""
    spent_usd: float = 0.0
    limit_usd: Optional[float] = None
    fraction: float = 0.0
    status: BudgetStatus = BudgetStatus.UNLIMITED
    scope: LimitScope = LimitScope.NONE
    entries_count: int = 0


@dataclass
class DowngradeResult:
    """Result of a downgrade attempt."""
    original_model: str
    downgraded_model: str
    category: TaskCategory
    reason: str
    estimated_savings_pct: float = 0.0


@dataclass
class PreRunEstimate:
    """Cost estimate before running a task."""
    model: str
    category: TaskCategory
    estimated_cost_usd: float
    budget_after_usd: float
    would_exceed: bool
    blocking_scope: LimitScope = LimitScope.NONE
    suggested_downgrade: Optional[DowngradeResult] = None


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class BudgetError(Exception):
    """Base for budget errors."""


class UnknownModelError(BudgetError):
    """Model ID not found in registry — fail-closed, don't assume $0."""


class BudgetExceededError(BudgetError):
    """Task cannot run — budget hard stop."""


class InvalidProjectIdError(BudgetError):
    """Project ID contains unsafe characters."""


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------

def _validate_project_id(project_id: str) -> None:
    """Guard against path traversal via project_id."""
    if not _SAFE_PROJECT_ID.match(project_id):
        raise InvalidProjectIdError(
            f"Invalid project_id {project_id!r}: must match {_SAFE_PROJECT_ID.pattern}"
        )


def _validate_non_negative(**kwargs: int | float) -> None:
    """Ensure all numeric args are >= 0."""
    for name, value in kwargs.items():
        if value < 0:
            raise ValueError(f"{name} must be >= 0, got {value}")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _atomic_write_json(path: Path, data: dict) -> None:
    """Write JSON atomically: tmp file + os.replace."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(
        dir=str(path.parent), suffix=".tmp", prefix=".budget_"
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, str(path))
    except BaseException:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


# ---------------------------------------------------------------------------
# BudgetController
# ---------------------------------------------------------------------------

class BudgetController:
    """
    Manages budget tracking, enforcement, and downgrade logic for Arcane 2.

    Design decisions (v2):
    - Per-project limits stored in _project_limits dict, never shared/overwritten.
    - record() auto-saves to disk (atomic write).
    - load_project() clears existing entries for that project before loading.
    - Thread lock protects _entries and _project_limits.
    - Unknown models raise UnknownModelError (fail-closed).
    - Negative values rejected.
    - pre_check() tests all 3 scopes: task, project, global.
    - auto_downgrade() loops until fit or exhaustion.
    - effective_status() reports which scope triggered the status.

    Lifecycle:
        1. pre_check()      — estimate cost, check ALL limits, suggest downgrade
        2. auto_downgrade()  — iteratively pick cheapest viable model
        3. record()          — log actual spend, auto-save, fire callbacks
        4. status()          — query current budget state
        5. dashboard()       — aggregated analytics (single-pass)
    """

    def __init__(
        self,
        global_month_limit: float | None = None,
        workspace_root: str = "/root/workspace",
        on_warning: Callable[[str, BudgetSnapshot], None] | None = None,
        on_pause: Callable[[str, BudgetSnapshot], None] | None = None,
        on_stop: Callable[[str, BudgetSnapshot], None] | None = None,
        auto_save: bool = True,
    ):
        self._global_month_limit = global_month_limit
        self._workspace_root = Path(workspace_root)
        self._auto_save = auto_save

        # Per-project limits — isolated, not shared
        self._project_limits: dict[str, BudgetLimits] = {}

        # All entries across projects
        self._entries: list[UsageEntry] = []

        # Callbacks for threshold events
        self._on_warning = on_warning
        self._on_pause = on_pause
        self._on_stop = on_stop

        # Dedup sets for ALL threshold levels (including STOPPED)
        self._warned: set[str] = set()
        self._paused: set[str] = set()
        self._stopped: set[str] = set()

        # Thread safety
        self._lock = threading.Lock()

    # -----------------------------------------------------------------------
    # Path helpers
    # -----------------------------------------------------------------------

    def _budget_path(self, project_id: str) -> Path:
        _validate_project_id(project_id)
        return (
            self._workspace_root / "projects" / project_id / ".arcane" / "budget.json"
        )

    def _global_budget_path(self) -> Path:
        return self._workspace_root / ".arcane" / "global_budget.json"

    # -----------------------------------------------------------------------
    # Per-project limits
    # -----------------------------------------------------------------------

    def get_limits(self, project_id: str) -> BudgetLimits:
        """Get limits for a specific project (creates default if absent)."""
        with self._lock:
            if project_id not in self._project_limits:
                self._project_limits[project_id] = BudgetLimits()
            return self._project_limits[project_id]

    def set_limits(
        self,
        project_id: str,
        per_task: float | None = None,
        per_project_month: float | None = None,
    ) -> None:
        """Set budget limits for a specific project."""
        with self._lock:
            limits = self._project_limits.setdefault(project_id, BudgetLimits())
            if per_task is not None:
                limits.per_task = per_task
            if per_project_month is not None:
                limits.per_project_month = per_project_month

    def set_global_limit(self, per_month_global: float | None) -> None:
        """Set global monthly budget limit across all projects."""
        with self._lock:
            self._global_month_limit = per_month_global

    # -----------------------------------------------------------------------
    # Persistence
    # -----------------------------------------------------------------------

    def load_project(self, project_id: str) -> None:
        """
        Load existing budget entries for a project from disk.
        Clears any in-memory entries for this project first (no duplicates).
        """
        _validate_project_id(project_id)
        path = self._budget_path(project_id)

        with self._lock:
            # Remove existing entries for this project to avoid duplication
            self._entries = [
                e for e in self._entries if e.project_id != project_id
            ]

            if not path.exists():
                return

            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError) as exc:
                logger.error("Failed to load budget for %s: %s", project_id, exc)
                return

            # Load entries
            for entry_dict in data.get("entries", []):
                try:
                    entry = UsageEntry(**entry_dict)
                    if entry.project_id == project_id:
                        self._entries.append(entry)
                except (TypeError, KeyError) as exc:
                    logger.warning("Skipping malformed entry in %s: %s", project_id, exc)

            # Load per-project limits (isolated — does NOT overwrite other projects)
            lim_data = data.get("limits", {})
            limits = self._project_limits.setdefault(project_id, BudgetLimits())
            if lim_data.get("per_task") is not None:
                limits.per_task = lim_data["per_task"]
            if lim_data.get("per_project_month") is not None:
                limits.per_project_month = lim_data["per_project_month"]

    def save_project(self, project_id: str) -> None:
        """Persist budget entries and limits for a project (atomic write)."""
        _validate_project_id(project_id)
        path = self._budget_path(project_id)

        with self._lock:
            project_entries = [
                e.to_dict() for e in self._entries if e.project_id == project_id
            ]
            limits = self._project_limits.get(project_id, BudgetLimits())

            # Aggregates compatible with project_manager.py schema
            by_agent: dict[str, float] = {}
            total_spent = 0.0
            for e in self._entries:
                if e.project_id == project_id:
                    by_agent[e.model] = by_agent.get(e.model, 0.0) + e.cost_usd
                    total_spent += e.cost_usd

            data = {
                "updated_at": _now_iso(),
                "total_spent_usd": round(total_spent, 6),
                "by_agent": {k: round(v, 6) for k, v in by_agent.items()},
                "limits": {
                    "per_task": limits.per_task,
                    "per_project_month": limits.per_project_month,
                    "monthly_usd": limits.per_project_month,
                    "per_call_usd": limits.per_task,
                },
                "entries": project_entries,
            }

        _atomic_write_json(path, data)

    def save_global(self) -> None:
        """Persist global budget state (atomic write)."""
        path = self._global_budget_path()
        month = self._current_month_key()

        with self._lock:
            total = sum(
                e.cost_usd for e in self._entries if e.timestamp[:7] == month
            )
            count = sum(1 for e in self._entries if e.timestamp[:7] == month)

            data = {
                "updated_at": _now_iso(),
                "month": month,
                "total_spent_usd": round(total, 6),
                "per_month_global": self._global_month_limit,
                "entries_count": count,
            }

        _atomic_write_json(path, data)

    def load_global(self) -> None:
        """Load global budget limit from disk."""
        path = self._global_budget_path()
        if not path.exists():
            return
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            with self._lock:
                if data.get("per_month_global") is not None:
                    self._global_month_limit = data["per_month_global"]
        except (json.JSONDecodeError, OSError) as exc:
            logger.error("Failed to load global budget: %s", exc)

    # -----------------------------------------------------------------------
    # Cost calculation — fail-closed on unknown models
    # -----------------------------------------------------------------------

    @staticmethod
    def calc_llm_cost(
        model: str,
        input_tokens: int,
        output_tokens: int,
        *,
        strict: bool = True,
    ) -> float:
        """
        Calculate LLM cost in USD.
        strict=True (default): raises UnknownModelError if model not in registry.
        strict=False: returns 0.0 with warning (for backward compat).
        """
        _validate_non_negative(input_tokens=input_tokens, output_tokens=output_tokens)

        pricing = MODEL_PRICES.get(model)
        if pricing is None:
            if strict:
                raise UnknownModelError(
                    f"Unknown LLM model {model!r}. Register it in MODEL_PRICES "
                    f"before recording spend. Available: {sorted(MODEL_PRICES.keys())}"
                )
            logger.warning("Unknown model %r — assuming $0 cost", model)
            return 0.0
        return pricing.cost(input_tokens, output_tokens)

    @staticmethod
    def calc_image_cost(
        image_model: str,
        count: int = 1,
        *,
        strict: bool = True,
    ) -> float:
        """Calculate image generation cost in USD using image_model (not LLM model)."""
        _validate_non_negative(count=count)

        if not image_model:
            return 0.0

        price = IMAGE_PRICES.get(image_model)
        if price is None:
            if strict:
                raise UnknownModelError(
                    f"Unknown image model {image_model!r}. Register it in IMAGE_PRICES. "
                    f"Available: {sorted(IMAGE_PRICES.keys())}"
                )
            logger.warning("Unknown image model %r — assuming $0", image_model)
            return 0.0
        return price * count

    @staticmethod
    def calc_manus_cost(credits: int) -> float:
        """Convert Manus credits to USD."""
        _validate_non_negative(credits=credits)
        return credits * MANUS_CREDIT_COST_USD

    # -----------------------------------------------------------------------
    # Aggregation (thread-safe)
    # -----------------------------------------------------------------------

    def _current_month_key(self) -> str:
        return datetime.now(timezone.utc).strftime("%Y-%m")

    def spent_on_task(self, project_id: str, task_id: str) -> float:
        with self._lock:
            return sum(
                e.cost_usd
                for e in self._entries
                if e.project_id == project_id and e.task_id == task_id
            )

    def spent_on_project_month(self, project_id: str) -> float:
        month = self._current_month_key()
        with self._lock:
            return sum(
                e.cost_usd
                for e in self._entries
                if e.project_id == project_id and e.timestamp[:7] == month
            )

    def spent_global_month(self) -> float:
        month = self._current_month_key()
        with self._lock:
            return sum(e.cost_usd for e in self._entries if e.timestamp[:7] == month)

    def get_remaining(self, project_id: str) -> float | None:
        """Get remaining budget for a project this month (USD).
        Called by orchestrator._get_budget_remaining().
        Returns None if no limit is set (unlimited)."""
        limits = self.get_limits(project_id)
        if limits.per_project_month is None:
            return None  # unlimited
        spent = self.spent_on_project_month(project_id)
        val = max(0.0, limits.per_project_month - spent)
        if val != val or val in (float('inf'), float('-inf')):  # nan/inf guard
            return None
        return round(val, 6)

    def _count_entries_unlocked(
        self,
        project_id: str | None = None,
        task_id: str | None = None,
    ) -> int:
        """Count matching entries for current month. Caller must hold _lock."""
        month = self._current_month_key()
        count = 0
        for e in self._entries:
            if e.timestamp[:7] != month:
                continue
            if project_id and e.project_id != project_id:
                continue
            if task_id and e.task_id != task_id:
                continue
            count += 1
        return count

    # -----------------------------------------------------------------------
    # Status checks
    # -----------------------------------------------------------------------

    def _make_snapshot(
        self,
        spent: float,
        limit: float | None,
        scope: LimitScope,
        entries_count: int = 0,
    ) -> BudgetSnapshot:
        if limit is None or limit <= 0:
            return BudgetSnapshot(
                spent_usd=spent,
                status=BudgetStatus.UNLIMITED,
                scope=scope,
                entries_count=entries_count,
            )
        fraction = spent / limit
        if fraction >= THRESHOLD_STOP:
            status = BudgetStatus.STOPPED
        elif fraction >= THRESHOLD_PAUSE:
            status = BudgetStatus.PAUSED
        elif fraction >= THRESHOLD_WARNING:
            status = BudgetStatus.WARNING
        else:
            status = BudgetStatus.OK
        return BudgetSnapshot(
            spent_usd=round(spent, 6),
            limit_usd=limit,
            fraction=round(fraction, 4),
            status=status,
            scope=scope,
            entries_count=entries_count,
        )

    def status_task(self, project_id: str, task_id: str) -> BudgetSnapshot:
        limits = self.get_limits(project_id)
        with self._lock:
            count = self._count_entries_unlocked(project_id, task_id)
        return self._make_snapshot(
            self.spent_on_task(project_id, task_id),
            limits.per_task,
            LimitScope.TASK,
            count,
        )

    def status_project(self, project_id: str) -> BudgetSnapshot:
        limits = self.get_limits(project_id)
        with self._lock:
            count = self._count_entries_unlocked(project_id)
        return self._make_snapshot(
            self.spent_on_project_month(project_id),
            limits.per_project_month,
            LimitScope.PROJECT,
            count,
        )

    def status_global(self) -> BudgetSnapshot:
        with self._lock:
            count = self._count_entries_unlocked()
        return self._make_snapshot(
            self.spent_global_month(),
            self._global_month_limit,
            LimitScope.GLOBAL,
            count,
        )

    def effective_status(self, project_id: str, task_id: str) -> BudgetSnapshot:
        """
        Return the most restrictive status across task / project / global.
        The returned snapshot's .scope tells WHICH limit triggered it.
        """
        snapshots = [
            self.status_task(project_id, task_id),
            self.status_project(project_id),
            self.status_global(),
        ]
        severity = {
            BudgetStatus.UNLIMITED: 0,
            BudgetStatus.OK: 1,
            BudgetStatus.WARNING: 2,
            BudgetStatus.PAUSED: 3,
            BudgetStatus.STOPPED: 4,
        }
        return max(snapshots, key=lambda s: severity[s.status])

    def can_run(self, project_id: str, task_id: str) -> bool:
        """Check if a task is allowed to run (not paused or stopped)."""
        s = self.effective_status(project_id, task_id)
        return s.status not in (BudgetStatus.PAUSED, BudgetStatus.STOPPED)

    # -----------------------------------------------------------------------
    # Pre-run estimate & enforcement — checks ALL 3 limits
    # -----------------------------------------------------------------------

    def _check_would_exceed(
        self,
        project_id: str,
        task_id: str,
        est_cost: float,
    ) -> tuple[bool, LimitScope]:
        """
        Check if est_cost would push any of the 3 scopes past THRESHOLD_STOP.
        Returns (would_exceed, first_blocking_scope).
        """
        limits = self.get_limits(project_id)

        # 1. Task limit
        if limits.per_task is not None and limits.per_task > 0:
            task_after = self.spent_on_task(project_id, task_id) + est_cost
            if task_after / limits.per_task >= THRESHOLD_STOP:
                return True, LimitScope.TASK

        # 2. Project monthly limit
        if limits.per_project_month is not None and limits.per_project_month > 0:
            proj_after = self.spent_on_project_month(project_id) + est_cost
            if proj_after / limits.per_project_month >= THRESHOLD_STOP:
                return True, LimitScope.PROJECT

        # 3. Global monthly limit
        if self._global_month_limit is not None and self._global_month_limit > 0:
            global_after = self.spent_global_month() + est_cost
            if global_after / self._global_month_limit >= THRESHOLD_STOP:
                return True, LimitScope.GLOBAL

        return False, LimitScope.NONE

    def estimate_cost(
        self,
        model: str,
        est_input_tokens: int = 0,
        est_output_tokens: int = 0,
        image_model: str = "",
        est_images: int = 0,
        est_manus_credits: int = 0,
    ) -> float:
        """
        Estimate total cost for a planned run.
        LLM cost from `model`, image cost from `image_model` — never cross-looked-up.
        """
        cost = 0.0

        # LLM cost — skip for manus-only tasks
        if model and model != "manus" and (est_input_tokens or est_output_tokens):
            cost += self.calc_llm_cost(model, est_input_tokens, est_output_tokens)

        # Image cost — separate model namespace
        if image_model and est_images:
            cost += self.calc_image_cost(image_model, est_images)

        # Manus cost
        if est_manus_credits:
            cost += self.calc_manus_cost(est_manus_credits)

        return cost

    def pre_check(
        self,
        project_id: str,
        task_id: str,
        model: str,
        category: TaskCategory,
        est_input_tokens: int = 0,
        est_output_tokens: int = 0,
        image_model: str = "",
        est_images: int = 0,
        est_manus_credits: int = 0,
    ) -> PreRunEstimate:
        """
        Before launching a task: estimate cost, check ALL 3 limits, suggest downgrade.

        Spec §8: "До запуска: Оценка. Если > лимит → даунгрейд."
        Checks: per_task + per_project_month + per_month_global.
        """
        est_cost = self.estimate_cost(
            model, est_input_tokens, est_output_tokens,
            image_model, est_images, est_manus_credits,
        )

        would_exceed, blocking_scope = self._check_would_exceed(
            project_id, task_id, est_cost,
        )

        current_spent = self.spent_on_project_month(project_id)

        downgrade = None
        if would_exceed:
            downgrade = self.suggest_downgrade(model, category)

        return PreRunEstimate(
            model=model,
            category=category,
            estimated_cost_usd=round(est_cost, 6),
            budget_after_usd=round(current_spent + est_cost, 6),
            would_exceed=would_exceed,
            blocking_scope=blocking_scope,
            suggested_downgrade=downgrade,
        )

    # -----------------------------------------------------------------------
    # Downgrade logic
    # -----------------------------------------------------------------------

    def suggest_downgrade(
        self,
        model: str,
        category: TaskCategory,
    ) -> DowngradeResult | None:
        """
        Find the next cheaper model in the tier list for the given category.
        If model is not in tier, finds the first model cheaper than current
        (by combined input+output cost), not the absolute cheapest.
        """
        tier_list = DOWNGRADE_MAP.get(category, [])
        if not tier_list:
            return None

        if model in tier_list:
            idx = tier_list.index(model)
            if idx >= len(tier_list) - 1:
                return None  # already cheapest
            downgraded = tier_list[idx + 1]
        else:
            # Model not in tier — find first model that is cheaper
            current_pricing = MODEL_PRICES.get(model)
            current_total = (
                (current_pricing.input_per_m + current_pricing.output_per_m)
                if current_pricing
                else float("inf")
            )

            downgraded = None
            for candidate in tier_list:
                cand_pricing = MODEL_PRICES.get(candidate)
                cand_total = (
                    (cand_pricing.input_per_m + cand_pricing.output_per_m)
                    if cand_pricing
                    else 0.0
                )
                if cand_total < current_total:
                    downgraded = candidate
                    break

            if downgraded is None:
                return None

        # Savings estimate using combined input + output cost
        orig = MODEL_PRICES.get(model)
        new = MODEL_PRICES.get(downgraded)
        savings = 0.0
        if orig and new:
            orig_total = orig.input_per_m + orig.output_per_m
            new_total = new.input_per_m + new.output_per_m
            if orig_total > 0:
                savings = round((1 - new_total / orig_total) * 100, 1)

        return DowngradeResult(
            original_model=model,
            downgraded_model=downgraded,
            category=category,
            reason=f"Budget pressure: downgrade {model} → {downgraded} for {category.value}",
            estimated_savings_pct=max(savings, 0.0),
        )

    def auto_downgrade(
        self,
        project_id: str,
        task_id: str,
        model: str,
        category: TaskCategory,
        est_input_tokens: int = 0,
        est_output_tokens: int = 0,
        image_model: str = "",
        est_images: int = 0,
        est_manus_credits: int = 0,
    ) -> str:
        """
        Iteratively pick a cheaper model until the task fits in budget
        or no further downgrade is possible.

        Returns the model to use (original or downgraded).
        Raises BudgetExceededError if no model fits.
        """
        current_model = model
        visited: set[str] = {model}

        while True:
            est_cost = self.estimate_cost(
                current_model, est_input_tokens, est_output_tokens,
                image_model, est_images, est_manus_credits,
            )

            would_exceed, scope = self._check_would_exceed(
                project_id, task_id, est_cost,
            )

            if not would_exceed:
                if current_model != model:
                    logger.info(
                        "Budget auto-downgrade: %s → %s (project=%s, category=%s, scope=%s)",
                        model, current_model, project_id, category.value, scope.value,
                    )
                return current_model

            result = self.suggest_downgrade(current_model, category)
            if result is None or result.downgraded_model in visited:
                raise BudgetExceededError(
                    f"Cannot fit task in budget: model={current_model}, "
                    f"category={category.value}, project={project_id}, "
                    f"est_cost=${est_cost:.4f}, blocking_scope={scope.value}. "
                    f"No cheaper model available in {category.value} tier."
                )

            visited.add(result.downgraded_model)
            current_model = result.downgraded_model

    # -----------------------------------------------------------------------
    # Recording spend
    # -----------------------------------------------------------------------

    def record(
        self,
        project_id: str,
        task_id: str,
        model: str,
        category: TaskCategory | str,
        input_tokens: int = 0,
        output_tokens: int = 0,
        image_model: str = "",
        images: int = 0,
        manus_credits: int = 0,
        cost_usd_override: float | None = None,
    ) -> UsageEntry:
        """
        Record actual spend after a task step completes.
        Auto-saves to disk (atomic). Triggers threshold callbacks.

        LLM cost from `model`, image cost from `image_model` — no cross-lookup.
        For Manus: set model="manus" and pass manus_credits.
        """
        _validate_project_id(project_id)
        _validate_non_negative(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            images=images,
            manus_credits=manus_credits,
        )

        cat = category.value if isinstance(category, TaskCategory) else category

        # Calculate cost — CRIT-3: use override if provided (actual_cost from router)
        if cost_usd_override is not None:
            cost = float(cost_usd_override)
        else:
            cost = 0.0
            if model and model != "manus" and (input_tokens or output_tokens):
                cost += self.calc_llm_cost(model, input_tokens, output_tokens)
            if image_model and images:
                cost += self.calc_image_cost(image_model, images)
            if manus_credits:
                cost += self.calc_manus_cost(manus_credits)
        if manus_credits:
            cost += self.calc_manus_cost(manus_credits)

        entry = UsageEntry(
            timestamp=_now_iso(),
            project_id=project_id,
            task_id=task_id,
            model=model,
            category=cat,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            image_model=image_model,
            images=images,
            manus_credits=manus_credits,
            cost_usd=round(cost, 6),
        )

        with self._lock:
            self._entries.append(entry)
            self._maybe_trim_entries()

        # Auto-save to disk
        if self._auto_save:
            try:
                self.save_project(project_id)
            except OSError as exc:
                logger.error("Failed to auto-save budget for %s: %s", project_id, exc)

        # Check thresholds and fire callbacks
        self._check_thresholds(project_id, task_id)

        return entry

    def _maybe_trim_entries(self) -> None:
        """Trim old entries if memory limit exceeded. Caller must hold _lock."""
        if len(self._entries) > MAX_ENTRIES_IN_MEMORY:
            self._entries = self._entries[-ENTRIES_TRIM_TO:]
            logger.info(
                "Trimmed budget entries: kept last %d of %d",
                ENTRIES_TRIM_TO, MAX_ENTRIES_IN_MEMORY,
            )

    def _check_thresholds(self, project_id: str, task_id: str) -> None:
        """Fire callbacks when budget thresholds are crossed. All levels deduplicated."""
        snapshot = self.effective_status(project_id, task_id)
        key = f"{project_id}:{task_id}"

        if snapshot.status == BudgetStatus.STOPPED:
            if key not in self._stopped:
                self._stopped.add(key)
                if self._on_stop:
                    self._on_stop(project_id, snapshot)
                logger.error(
                    "BUDGET STOP (100%%): project=%s scope=%s spent=$%.4f limit=%s",
                    project_id, snapshot.scope.value, snapshot.spent_usd, snapshot.limit_usd,
                )

        elif snapshot.status == BudgetStatus.PAUSED:
            if key not in self._paused:
                self._paused.add(key)
                if self._on_pause:
                    self._on_pause(project_id, snapshot)
                logger.warning(
                    "BUDGET PAUSE (95%%): project=%s scope=%s spent=$%.4f limit=%s",
                    project_id, snapshot.scope.value, snapshot.spent_usd, snapshot.limit_usd,
                )

        elif snapshot.status == BudgetStatus.WARNING:
            if key not in self._warned:
                self._warned.add(key)
                if self._on_warning:
                    self._on_warning(project_id, snapshot)
                logger.warning(
                    "BUDGET WARNING (80%%): project=%s scope=%s spent=$%.4f limit=%s",
                    project_id, snapshot.scope.value, snapshot.spent_usd, snapshot.limit_usd,
                )

    # -----------------------------------------------------------------------
    # Dashboard — single-pass aggregation
    # -----------------------------------------------------------------------

    def dashboard(self, project_id: str | None = None) -> dict:
        """
        Aggregated dashboard data — spec §8: "по месяцу, проекту, задаче, агенту."
        Single-pass O(n) aggregation.
        """
        month = self._current_month_key()

        by_project: dict[str, float] = {}
        by_model: dict[str, float] = {}
        by_task: dict[str, float] = {}
        by_category: dict[str, float] = {}
        total = 0.0
        count = 0

        with self._lock:
            for e in self._entries:
                if e.timestamp[:7] != month:
                    continue
                if project_id is not None and e.project_id != project_id:
                    continue

                cost = e.cost_usd
                total += cost
                count += 1
                by_project[e.project_id] = by_project.get(e.project_id, 0.0) + cost
                by_model[e.model] = by_model.get(e.model, 0.0) + cost
                task_key = f"{e.project_id}:{e.task_id}"
                by_task[task_key] = by_task.get(task_key, 0.0) + cost
                by_category[e.category] = by_category.get(e.category, 0.0) + cost

        top_tasks = dict(sorted(by_task.items(), key=lambda x: -x[1])[:20])

        return {
            "month": month,
            "total_usd": round(total, 4),
            "global_limit_usd": self._global_month_limit,
            "global_status": asdict(self.status_global()),
            "by_project": {k: round(v, 4) for k, v in by_project.items()},
            "by_model": {
                k: round(v, 4)
                for k, v in sorted(by_model.items(), key=lambda x: -x[1])
            },
            "by_task": {k: round(v, 4) for k, v in top_tasks.items()},
            "by_category": {k: round(v, 4) for k, v in by_category.items()},
            "entries_count": count,
        }

    # -----------------------------------------------------------------------
    # Admin
    # -----------------------------------------------------------------------

    def reset_warnings(self, project_id: str | None = None) -> None:
        """Clear warning/pause/stop flags to allow re-notification."""
        with self._lock:
            if project_id:
                prefix = f"{project_id}:"
                self._warned = {k for k in self._warned if not k.startswith(prefix)}
                self._paused = {k for k in self._paused if not k.startswith(prefix)}
                self._stopped = {k for k in self._stopped if not k.startswith(prefix)}
            else:
                self._warned.clear()
                self._paused.clear()
                self._stopped.clear()
