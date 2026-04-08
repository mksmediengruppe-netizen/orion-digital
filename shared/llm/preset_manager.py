"""
ARCANE Preset Manager
Manages 6 operational modes (AUTO → FREE), custom per-role model overrides,
tool-calling capability checks, and speculative execution planning.

Spec ref: §6.1 (Шесть режимов), §14 (preset_manager.py)

Modes:
  AUTO     — system picks the best model per role using leaderboard data
  MANUAL   — user overrides any role→model mapping
  TOP      — best model for each role, optimized cost
  OPTIMUM  — 90% of TOP quality at 50% price (default)
  LITE     — acceptable quality, minimum cost
  FREE     — $0 AI spend, cheapest/free-tier models only
"""

from __future__ import annotations

import json
import threading
import warnings
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Optional

from shared.llm.model_registry import (
    MODELS,
    ROLES,
    STRATEGY_TIER_MAP,
    TIER_ESCALATION_ORDER,
    resolve_role,
)
from shared.models.schemas import Tier
from shared.utils.logger import get_logger, log_with_data

logger = get_logger("llm.preset_manager")


# ═════════════════════════════════════════════════════════════════════════════
# Preset Mode enum — the 6 user-facing modes from the spec
# ═════════════════════════════════════════════════════════════════════════════

class PresetMode(str, Enum):
    AUTO = "auto"
    MANUAL = "manual"
    TOP = "top"
    ARCANE4 = "arcane4"      # ARCANE 4.0: Opus Director + Sonnet Engineer
    OPTIMUM = "optimum"      # default
    LITE = "lite"
    FREE = "free"


# ═════════════════════════════════════════════════════════════════════════════
# Mode → internal strategy mapping
# ═════════════════════════════════════════════════════════════════════════════

_MODE_TO_STRATEGY: dict[PresetMode, str] = {
    PresetMode.FREE: "free",
    PresetMode.LITE: "economy",
    PresetMode.OPTIMUM: "balance",
    PresetMode.TOP: "quality",
    PresetMode.ARCANE4: "arcane4",
    # AUTO and MANUAL are resolved dynamically
}

# FREE tier map — used locally; injected into global map lazily via
# ensure_free_strategy(), NOT at import time.
_FREE_TIER_MAP: dict[str, Tier] = {
    # ARCANE 3.0: 7 production roles
    "director":     Tier.FREE,
    "art_director": Tier.FREE,
    "writer":       Tier.FREE,
    "developer":    Tier.FREE,
    "researcher":   Tier.FREE,
    "qa":           Tier.FREE,
    "image_agent":  Tier.FREE,
}

_free_strategy_lock = threading.Lock()
_free_strategy_registered = False


def ensure_free_strategy() -> None:
    """Register the 'free' strategy in STRATEGY_TIER_MAP (thread-safe, once)."""
    global _free_strategy_registered
    if _free_strategy_registered:
        return
    with _free_strategy_lock:
        if _free_strategy_registered:
            return
        STRATEGY_TIER_MAP.setdefault("free", _FREE_TIER_MAP)
        _free_strategy_registered = True


# ═════════════════════════════════════════════════════════════════════════════
# Tier index helpers — ordinal comparison, NOT string comparison
# ═════════════════════════════════════════════════════════════════════════════

def _tier_index(tier: Tier) -> int:
    """Return the ordinal position of a tier (0=FREE … 5=DEEP)."""
    try:
        return TIER_ESCALATION_ORDER.index(tier)
    except ValueError:
        return -1


# ═════════════════════════════════════════════════════════════════════════════
# Tool-calling capability registry
# ═════════════════════════════════════════════════════════════════════════════

class ToolCapability(str, Enum):
    FUNCTION_CALLING = "function_calling"
    VISION = "vision"
    EXTENDED_THINKING = "extended_thinking"
    STREAMING = "streaming"
    JSON_MODE = "json_mode"


# Models known to support extended thinking / chain-of-thought.
# Kept as a set for O(1) lookup — update when adding reasoning models
# to model_registry.py.
_EXTENDED_THINKING_MODELS: set[str] = {
    "o3", "o4-mini", "deepseek-r1",
    # Anthropic native extended thinking
    "claude-opus-4",
}


def get_model_capabilities(model_id: str) -> set[ToolCapability]:
    """Return the set of capabilities for a given model."""
    spec = MODELS.get(model_id)
    if not spec:
        return set()
    caps: set[ToolCapability] = set()
    if spec.supports_function_calling:
        caps.add(ToolCapability.FUNCTION_CALLING)
    if spec.supports_vision:
        caps.add(ToolCapability.VISION)
    if getattr(spec, "supports_streaming", True):
        caps.add(ToolCapability.STREAMING)
    if model_id in _EXTENDED_THINKING_MODELS:
        caps.add(ToolCapability.EXTENDED_THINKING)
    return caps


def model_supports(model_id: str, capability: ToolCapability) -> bool:
    """Check if a specific model supports a given capability."""
    return capability in get_model_capabilities(model_id)


# ═════════════════════════════════════════════════════════════════════════════
# Resolution result — carries metadata about HOW a model was chosen
# ═════════════════════════════════════════════════════════════════════════════

@dataclass
class ResolvedModel:
    """Result of model resolution with provenance metadata."""
    model_id: str
    tier: Tier
    source: str                   # "tier", "manual_override", "auto_leaderboard"
    override_bypassed: bool = False  # True if manual override was skipped due to capability
    auto_degraded: bool = False     # True if AUTO fell back to tier-based resolution


# ═════════════════════════════════════════════════════════════════════════════
# Speculative Execution hints
# ═════════════════════════════════════════════════════════════════════════════

@dataclass
class SpeculativeHint:
    """Hint for the orchestrator about parallel execution."""
    role: str
    tier: Tier
    model_id: str
    is_speculative: bool = False   # True = cheap speculative branch
    depends_on: list[str] = field(default_factory=list)  # role names


# ═════════════════════════════════════════════════════════════════════════════
# Preset Manager
# ═════════════════════════════════════════════════════════════════════════════

@dataclass
class PresetManager:
    """
    Central authority for model selection policy.

    The router delegates tier/model resolution here instead of
    reading STRATEGY_TIER_MAP directly.

    Usage:
        pm = PresetManager(mode=PresetMode.OPTIMUM)
        pm = PresetManager.from_project_settings("/path/to/settings.json")

        resolved = pm.resolve_model_full("developer")
        tier     = pm.resolve_tier("developer")
        ok       = pm.check_capability("developer", ToolCapability.VISION)
    """

    mode: PresetMode = PresetMode.OPTIMUM

    # MANUAL mode: per-role model overrides  {role: model_id}
    role_overrides: dict[str, str] = field(default_factory=dict)

    # MANUAL/any mode: per-role tier overrides  {role: Tier}
    tier_overrides: dict[str, Tier] = field(default_factory=dict)

    # AUTO mode: leaderboard scores  {category: [(model_id, score)]}
    # Populated by dog_racing / external calibration
    leaderboard: dict[str, list[tuple[str, float]]] = field(default_factory=dict)

    # Validation errors collected during from_dict (non-fatal)
    _validation_warnings: list[str] = field(default_factory=list, repr=False)

    def __post_init__(self) -> None:
        # Ensure free strategy is available when any PresetManager is created
        ensure_free_strategy()

    # ── Construction helpers ──────────────────────────────────────────────

    @classmethod
    def from_project_settings(cls, settings_path: str | Path) -> PresetManager:
        """Load preset config from a project's .arcane/settings.json."""
        path = Path(settings_path)
        if not path.exists():
            log_with_data(
                logger, "WARNING",
                "Settings file not found, using defaults",
                path=str(path),
            )
            return cls()

        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            log_with_data(
                logger, "WARNING",
                f"Failed to read settings: {exc}",
                path=str(path),
            )
            return cls()

        return cls.from_dict(data)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PresetManager:
        """
        Build from a plain dict (e.g. API payload or JSON).

        Validates model_ids, tiers, and leaderboard scores.
        Non-fatal errors are collected in _validation_warnings and logged.
        """
        validation_warnings: list[str] = []

        # ── Mode ──────────────────────────────────────────────────────────
        mode_str = data.get("mode", data.get("strategy", "optimum"))
        try:
            mode = PresetMode(mode_str.lower())
        except ValueError:
            _compat = {
                "economy": PresetMode.LITE,
                "balance": PresetMode.OPTIMUM,
                "quality": PresetMode.TOP,
                "maximum": PresetMode.TOP,
                "arcane4": PresetMode.ARCANE4,
            }
            mode = _compat.get(mode_str.lower(), PresetMode.OPTIMUM)
            if mode_str.lower() not in _compat:
                validation_warnings.append(
                    f"Unknown mode/strategy '{mode_str}', defaulting to OPTIMUM"
                )

        # ── Role & tier overrides ─────────────────────────────────────────
        role_overrides: dict[str, str] = {}
        tier_overrides: dict[str, Tier] = {}
        for role, spec in data.get("role_overrides", {}).items():
            if isinstance(spec, str):
                if spec in MODELS:
                    role_overrides[role] = spec
                else:
                    validation_warnings.append(
                        f"role_overrides[{role}]: unknown model_id '{spec}', skipped"
                    )
            elif isinstance(spec, dict):
                if "model_id" in spec:
                    mid = spec["model_id"]
                    if mid in MODELS:
                        role_overrides[role] = mid
                    else:
                        validation_warnings.append(
                            f"role_overrides[{role}].model_id: unknown '{mid}', skipped"
                        )
                if "tier" in spec:
                    try:
                        tier_overrides[role] = Tier(spec["tier"])
                    except ValueError:
                        validation_warnings.append(
                            f"role_overrides[{role}].tier: invalid '{spec['tier']}', skipped"
                        )

        # ── Standalone tier overrides (without role_overrides) ────────────
        for role, tier_str in data.get("tier_overrides", {}).items():
            if role not in tier_overrides:  # don't overwrite inline ones
                try:
                    tier_overrides[role] = Tier(tier_str) if isinstance(tier_str, str) else Tier(tier_str)
                except (ValueError, KeyError):
                    validation_warnings.append(
                        f"tier_overrides[{role}]: invalid '{tier_str}', skipped"
                    )

        # ── Leaderboard ───────────────────────────────────────────────────
        leaderboard: dict[str, list[tuple[str, float]]] = {}
        for cat, entries in data.get("leaderboard", {}).items():
            valid_entries: list[tuple[str, float]] = []
            for e in entries:
                if not isinstance(e, dict) or "model_id" not in e or "score" not in e:
                    continue
                try:
                    score = float(e["score"])
                except (ValueError, TypeError):
                    validation_warnings.append(
                        f"leaderboard[{cat}]: invalid score for '{e.get('model_id')}', skipped"
                    )
                    continue
                valid_entries.append((e["model_id"], score))
            if valid_entries:
                leaderboard[cat] = valid_entries

        # ── Log warnings ──────────────────────────────────────────────────
        for w in validation_warnings:
            log_with_data(logger, "WARNING", f"PresetManager validation: {w}")

        return cls(
            mode=mode,
            role_overrides=role_overrides,
            tier_overrides=tier_overrides,
            leaderboard=leaderboard,
            _validation_warnings=validation_warnings,
        )

    # ── Core resolution ───────────────────────────────────────────────────

    @property
    def strategy_key(self) -> str:
        """The internal strategy key for STRATEGY_TIER_MAP lookup."""
        if self.mode in _MODE_TO_STRATEGY:
            return _MODE_TO_STRATEGY[self.mode]
        # AUTO and MANUAL fall back to "balance"
        return "balance"

    def resolve_tier(self, role: str, tier_override: Optional[Tier] = None) -> Tier:
        """
        Determine starting tier for a role.
        Canonicalizes old role names (coding→developer) via resolve_role().
        """
        role = resolve_role(role)  # ARCANE 3.0: canonicalize old names
        if tier_override:
            return tier_override

        if self.mode == PresetMode.MANUAL and role in self.tier_overrides:
            return self.tier_overrides[role]

        strategy_map = STRATEGY_TIER_MAP.get(self.strategy_key, STRATEGY_TIER_MAP["balance"])
        tier = strategy_map.get(role)
        if tier:
            return tier

        # Use role's registered default_tier from model_registry
        role_def = ROLES.get(role)
        if role_def:
            return role_def.default_tier

        return Tier.FAST

    def resolve_model(
        self,
        role: str,
        tier_override: Optional[Tier] = None,
        require_capability: Optional[ToolCapability] = None,
    ) -> str | None:
        """
        Resolve the model_id for a role, respecting mode, overrides,
        and optional capability requirements.

        Capability gating is FAIL-CLOSED: if require_capability is set
        and no model satisfies it, returns None (never returns an
        incapable model).

        Returns None if no suitable model is found.
        """
        resolved = self.resolve_model_full(role, tier_override, require_capability)
        return resolved.model_id if resolved else None

    def resolve_model_full(
        self,
        role: str,
        tier_override: Optional[Tier] = None,
        require_capability: Optional[ToolCapability] = None,
    ) -> ResolvedModel | None:
        """
        Full resolution with provenance metadata.
        Canonicalizes old role names via resolve_role().
        """
        role = resolve_role(role)  # ARCANE 3.0: canonicalize old names
        # ── MANUAL mode: direct model override ────────────────────────────
        if self.mode == PresetMode.MANUAL and role in self.role_overrides:
            model_id = self.role_overrides[role]
            if require_capability and not model_supports(model_id, require_capability):
                log_with_data(
                    logger, "WARNING",
                    f"Manual override {model_id} lacks {require_capability.value}, "
                    f"falling back to tier resolution",
                    role=role,
                )
                # Fall through to tier-based resolution, but flag it
                result = self._resolve_from_tiers(role, tier_override, require_capability)
                if result:
                    result.override_bypassed = True
                return result
            tier = self.resolve_tier(role, tier_override)
            return ResolvedModel(
                model_id=model_id,
                tier=tier,
                source="manual_override",
            )

        # ── AUTO mode: consult leaderboard ────────────────────────────────
        if self.mode == PresetMode.AUTO:
            auto_model = self._resolve_auto(role, require_capability)
            if auto_model:
                tier = self.resolve_tier(role, tier_override)
                return ResolvedModel(
                    model_id=auto_model,
                    tier=tier,
                    source="auto_leaderboard",
                )
            # Leaderboard empty/no match → degrade to tier-based
            log_with_data(
                logger, "INFO",
                f"AUTO mode: no leaderboard data for role={role}, "
                f"degrading to tier-based resolution",
                role=role,
            )
            result = self._resolve_from_tiers(role, tier_override, require_capability)
            if result:
                result.auto_degraded = True
            return result

        # ── Standard tier-based resolution ────────────────────────────────
        return self._resolve_from_tiers(role, tier_override, require_capability)

    def _resolve_from_tiers(
        self,
        role: str,
        tier_override: Optional[Tier] = None,
        require_capability: Optional[ToolCapability] = None,
    ) -> ResolvedModel | None:
        """
        Tier-based model resolution.  Capability gating is FAIL-CLOSED.

        If require_capability is set and the resolved model doesn't have it,
        tries higher tiers.  If no tier has a capable model, returns None.
        """
        tier = self.resolve_tier(role, tier_override)
        role_def = ROLES.get(role)
        if not role_def:
            return None

        model_id = role_def.tiers.get(tier)
        if not model_id:
            # Find nearest LOWER tier by ordinal index, not string comparison
            target_idx = _tier_index(tier)
            for t in reversed(TIER_ESCALATION_ORDER):
                if _tier_index(t) <= target_idx and t in role_def.tiers:
                    model_id = role_def.tiers[t]
                    tier = t
                    break

        if not model_id:
            return None

        # ── Capability gate (fail-closed) ─────────────────────────────────
        if require_capability and not model_supports(model_id, require_capability):
            start_idx = _tier_index(tier)
            for t in TIER_ESCALATION_ORDER[start_idx + 1:]:
                alt = role_def.tiers.get(t)
                if alt and model_supports(alt, require_capability):
                    log_with_data(
                        logger, "INFO",
                        f"Upgraded {model_id}→{alt} for {require_capability.value}",
                        role=role,
                    )
                    return ResolvedModel(model_id=alt, tier=t, source="tier")

            # FAIL-CLOSED: no capable model found → return None
            log_with_data(
                logger, "WARNING",
                f"No model for role={role} with {require_capability.value} "
                f"(fail-closed, returning None)",
                role=role,
            )
            return None

        return ResolvedModel(model_id=model_id, tier=tier, source="tier")

    def _resolve_auto(
        self,
        role: str,
        require_capability: Optional[ToolCapability] = None,
    ) -> str | None:
        """
        AUTO mode: pick model from leaderboard data.

        Maps role → leaderboard category, then picks the highest-scored
        model that exists in MODELS and satisfies capability requirements.
        """
        _role_to_category: dict[str, str] = {
            "director":     "planning",
            "art_director": "design",
            "developer":    "code",
            "writer":       "content",
            "researcher":   "research",
            "qa":           "code_review",
            "image_agent":  "image",
        }
        category = _role_to_category.get(role, role)

        candidates = self.leaderboard.get(category, [])
        if not candidates:
            return None

        for model_id, _score in sorted(candidates, key=lambda x: x[1], reverse=True):
            if model_id not in MODELS:
                continue
            if require_capability and not model_supports(model_id, require_capability):
                continue
            return model_id

        return None

    # ── Capability queries ────────────────────────────────────────────────

    def check_capability(self, role: str, capability: ToolCapability) -> bool:
        """Check if the currently-resolved model for a role has a capability."""
        model_id = self.resolve_model(role)
        if not model_id:
            return False
        return model_supports(model_id, capability)

    def get_capabilities(self, role: str) -> set[ToolCapability]:
        """Return all capabilities for the currently-resolved model."""
        model_id = self.resolve_model(role)
        if not model_id:
            return set()
        return get_model_capabilities(model_id)

    # ── Speculative Execution planning ────────────────────────────────────

    def plan_speculative(
        self,
        primary_roles: list[str],
        speculative_roles: list[str] | None = None,
        require_capability: ToolCapability | None = None,
    ) -> list[SpeculativeHint]:
        """
        Build a speculative execution plan.

        Primary roles run at full tier via resolve_model (respects mode,
        overrides, capabilities).  Speculative roles run at NANO/FAST
        (cheap) in parallel.

        Spec ref: §5.1 — "Дешёвые модели спекулируют, дорогие решают."
        """
        hints: list[SpeculativeHint] = []

        for role in primary_roles:
            resolved = self.resolve_model_full(role, require_capability=require_capability)
            if resolved:
                hints.append(SpeculativeHint(
                    role=role,
                    tier=resolved.tier,
                    model_id=resolved.model_id,
                    is_speculative=False,
                ))

        for role in (speculative_roles or []):
            # Force cheap tier for speculative branches, but still respect capabilities
            resolved = self.resolve_model_full(
                role,
                tier_override=Tier.NANO,
                require_capability=require_capability,
            )
            if not resolved:
                # NANO failed capability check, try FAST
                resolved = self.resolve_model_full(
                    role,
                    tier_override=Tier.FAST,
                    require_capability=require_capability,
                )
            if resolved:
                hints.append(SpeculativeHint(
                    role=role,
                    tier=resolved.tier,
                    model_id=resolved.model_id,
                    is_speculative=True,
                    depends_on=list(primary_roles),
                ))

        return hints

    # ── Serialization ─────────────────────────────────────────────────────

    def to_dict(self) -> dict[str, Any]:
        """Serialize for storage in settings.json or API responses."""
        result: dict[str, Any] = {"mode": self.mode.value}

        # Role overrides with inline tier
        if self.role_overrides:
            ro: dict[str, Any] = {}
            for role, model_id in self.role_overrides.items():
                entry: dict[str, str] = {"model_id": model_id}
                if role in self.tier_overrides:
                    entry["tier"] = self.tier_overrides[role].value
                ro[role] = entry
            result["role_overrides"] = ro

        # Standalone tier overrides (roles NOT in role_overrides)
        standalone_tiers = {
            role: tier.value
            for role, tier in self.tier_overrides.items()
            if role not in self.role_overrides
        }
        if standalone_tiers:
            result["tier_overrides"] = standalone_tiers

        if self.leaderboard:
            result["leaderboard"] = {
                cat: [{"model_id": m, "score": s} for m, s in entries]
                for cat, entries in self.leaderboard.items()
            }
        return result

    def save_project_settings(self, settings_path: str | Path) -> None:
        """Persist current preset to a project's .arcane/settings.json."""
        path = Path(settings_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(self.to_dict(), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    def __repr__(self) -> str:
        overrides = f", overrides={list(self.role_overrides)}" if self.role_overrides else ""
        return f"PresetManager(mode={self.mode.value}{overrides})"
