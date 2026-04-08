"""
Arcane 2 — Schema extensions for model registry.
Uses dataclasses (stdlib). On production server with pydantic — trivial migration.

Fixes applied after Sonnet 4.6 code review:
- __post_init__ validation (negative prices, max_output > max_context)
- cost_estimate uses cached_input_price when use_cache=True
- is_free auto-synced with price in __post_init__
- ManusSpec.estimate_cost logs warning for unknown operations
- ops_costs typed as dict[str, tuple[int, int]]
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

logger = logging.getLogger("arcane2.schemas")


# ═══════════════════════════════════════════════════════════════════════════════
# ENUMS
# ═══════════════════════════════════════════════════════════════════════════════

class ToolCallReliability(str, Enum):
    """Ordered from most to least reliable. Index 0 = best."""
    RELIABLE = "reliable"       # Always works: Sonnet, Opus, GPT-5.4, Gemini
    OK = "ok"                   # Usually works: Kimi, Step Flash
    UNSTABLE = "unstable"       # Often fails: DeepSeek, MiniMax
    NONE = "none"               # No support

    def is_at_least(self, minimum: ToolCallReliability) -> bool:
        """Check if this reliability meets the minimum requirement.
        RELIABLE.is_at_least(OK) → True (reliable is better than ok)
        UNSTABLE.is_at_least(RELIABLE) → False
        """
        order = [ToolCallReliability.RELIABLE, ToolCallReliability.OK,
                 ToolCallReliability.UNSTABLE, ToolCallReliability.NONE]
        return order.index(self) <= order.index(minimum)


class ModelCategory(str, Enum):
    GENERAL = "general"
    CODE = "code"
    DESIGN = "design"
    REASONING = "reasoning"
    FAST = "fast"
    CHEAP = "cheap"
    FREE = "free"


class Provider(str, Enum):
    OPENROUTER = "openrouter"
    OPENAI_NATIVE = "openai_native"
    ANTHROPIC_NATIVE = "anthropic_native"
    GOOGLE_NATIVE = "google_native"
    MANUS = "manus"
    FAL_AI = "fal_ai"
    MIDJOURNEY = "midjourney"
    IDEOGRAM = "ideogram"
    PEXELS = "pexels"


class Preset(str, Enum):
    AUTO = "auto"
    MANUAL = "manual"
    TOP = "top"
    OPTIMUM = "optimum"
    LITE = "lite"
    FREE = "free"


# ═══════════════════════════════════════════════════════════════════════════════
# MODEL SPECS
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class ModelSpec:
    """Specification of an LLM model."""
    id: str
    provider: Provider = Provider.OPENROUTER
    display_name: str = ""
    input_price: float = 0.0                        # USD per 1M input tokens
    output_price: float = 0.0                       # USD per 1M output tokens
    cached_input_price: Optional[float] = None      # USD per 1M cached input tokens
    max_context: int = 128_000
    max_output: int = 16_000
    supports_vision: bool = False
    supports_streaming: bool = True
    tool_calling: ToolCallReliability = ToolCallReliability.RELIABLE
    categories: list[ModelCategory] = field(default_factory=lambda: [ModelCategory.GENERAL])
    swe_bench: Optional[float] = None
    speed: str = "medium"                           # fast / medium / slow
    openrouter_id: Optional[str] = None
    native_id: Optional[str] = None
    native_provider: Optional[Provider] = None
    is_free: bool = False
    is_reasoning: bool = False
    is_deprecated: bool = False

    def __post_init__(self):
        if self.input_price < 0 or self.output_price < 0:
            raise ValueError(f"Model {self.id}: prices cannot be negative")
        if self.max_output > self.max_context:
            raise ValueError(f"Model {self.id}: max_output ({self.max_output}) > max_context ({self.max_context})")
        if not self.id:
            raise ValueError("Model id cannot be empty")
        # Auto-sync is_free with price
        if self.input_price == 0.0 and self.output_price == 0.0:
            self.is_free = True

    # Backward compat with v1
    @property
    def input_price_per_mtok(self) -> float:
        return self.input_price

    @property
    def output_price_per_mtok(self) -> float:
        return self.output_price

    @property
    def supports_function_calling(self) -> bool:
        """True if tool calling is at least OK (reliable or ok)."""
        return self.tool_calling.is_at_least(ToolCallReliability.OK)

    def cost_estimate(self, input_tokens: int, output_tokens: int,
                      use_cache: bool = False) -> float:
        """Estimate cost in USD. If use_cache=True and cached price exists, use it for input."""
        if input_tokens < 0 or output_tokens < 0:
            raise ValueError(f"Token counts cannot be negative: in={input_tokens}, out={output_tokens}")
        if use_cache and self.cached_input_price is not None:
            in_price = self.cached_input_price
        else:
            in_price = self.input_price
        return (input_tokens * in_price + output_tokens * self.output_price) / 1_000_000


@dataclass
class ImageModelSpec:
    """Specification of an image generation model."""
    id: str
    provider: Provider = Provider.FAL_AI
    display_name: str = ""
    price_per_image: float = 0.0
    max_resolution: str = "1024x1024"
    supports_text: bool = False
    supports_svg: bool = False
    best_for: list[str] = field(default_factory=list)
    speed: str = "medium"
    is_free: bool = False

    def __post_init__(self):
        if self.price_per_image == 0.0 and not self.is_free:
            self.is_free = True


@dataclass
class ManusSpec:
    """Manus agent specification. $100/mo = 80K credits."""
    id: str = "manus"
    provider: Provider = Provider.MANUS
    display_name: str = "Manus Agent"
    monthly_cost: float = 100.0
    monthly_credits: int = 80_000
    daily_bonus_credits: int = 300
    credit_price: float = 0.00125                   # USD per credit

    ops_costs: dict[str, tuple[int, int]] = field(default_factory=lambda: {
        "ssh_command": (20, 50),
        "deploy_cycle": (80, 150),
        "browser_quick": (50, 100),
        "browser_full_qa": (150, 300),
        "server_setup": (200, 500),
        "wide_research": (300, 900),
        "cms_install": (500, 900),
    })

    def credits_to_usd(self, credits: int) -> float:
        return credits * self.credit_price

    def estimate_cost(self, operation: str) -> tuple[float, float]:
        """Return (min_usd, max_usd). Warns if operation unknown."""
        if operation in self.ops_costs:
            lo, hi = self.ops_costs[operation]
            return (self.credits_to_usd(lo), self.credits_to_usd(hi))
        logger.warning(f"Unknown Manus operation: '{operation}'. Returning (0, 0). "
                       f"Known operations: {list(self.ops_costs.keys())}")
        return (0.0, 0.0)
