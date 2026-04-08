"""
ARCANE 4.0 — Model Registry v4
Verified against OpenRouter API: April 2026
All model IDs, prices and capabilities confirmed via live API call.
ARCANE 4.0: Director=Claude Opus 4.6, Engineer=Claude Sonnet 4.6, Manus=Executor
"""

from __future__ import annotations

from shared.models.arcane2_schemas import (
    ModelSpec, ImageModelSpec, ManusSpec,
    ToolCallReliability, ModelCategory, Provider,
)


# ═══════════════════════════════════════════════════════════════════════════════
# LLM MODELS — verified via OpenRouter API 2026-04-02
# ═══════════════════════════════════════════════════════════════════════════════

MODELS: dict[str, ModelSpec] = {

    # ── Anthropic ─────────────────────────────────────────────────────────────

    "claude-opus-4.6": ModelSpec(
        id="claude-opus-4.6",
        display_name="Claude Opus 4.6",
        input_price=5.00, output_price=25.00, cached_input_price=0.50,
        max_context=200_000, max_output=128_000,
        supports_vision=True,
        tool_calling=ToolCallReliability.RELIABLE,
        categories=[ModelCategory.REASONING, ModelCategory.CODE],
        swe_bench=80.8, speed="slow",
        openrouter_id="anthropic/claude-opus-4.6",
        native_id="claude-opus-4-6", native_provider=Provider.ANTHROPIC_NATIVE,
        is_reasoning=True,
    ),

    "claude-sonnet-4.6": ModelSpec(
        id="claude-sonnet-4.6",
        display_name="Claude Sonnet 4.6",
        input_price=3.00, output_price=15.00, cached_input_price=0.30,
        max_context=200_000, max_output=64_000,
        supports_vision=True,
        tool_calling=ToolCallReliability.RELIABLE,
        categories=[ModelCategory.DESIGN, ModelCategory.CODE],
        swe_bench=79.6, speed="medium",
        openrouter_id="anthropic/claude-sonnet-4.6",
        native_id="claude-sonnet-4-6", native_provider=Provider.ANTHROPIC_NATIVE,
    ),

    "claude-haiku-4.5": ModelSpec(
        id="claude-haiku-4.5",
        display_name="Claude Haiku 4.5",
        input_price=1.00, output_price=5.00, cached_input_price=0.10,
        max_context=200_000, max_output=8_000,
        supports_vision=True,
        tool_calling=ToolCallReliability.RELIABLE,
        categories=[ModelCategory.FAST],
        speed="fast",
        openrouter_id="anthropic/claude-haiku-4.5",
        native_id="claude-haiku-4-5-20251001", native_provider=Provider.ANTHROPIC_NATIVE,
    ),

    # ── OpenAI ────────────────────────────────────────────────────────────────

    "gpt-5.4": ModelSpec(
        id="gpt-5.4",
        display_name="GPT-5.4",
        input_price=2.50, output_price=15.00, cached_input_price=0.625,
        max_context=1_047_576, max_output=128_000,
        supports_vision=True,
        tool_calling=ToolCallReliability.RELIABLE,
        categories=[ModelCategory.CODE],
        swe_bench=80.0, speed="medium",
        openrouter_id="openai/gpt-5.4",
        native_id="gpt-5.4", native_provider=Provider.OPENAI_NATIVE,
    ),

    "gpt-5.4-mini": ModelSpec(
        id="gpt-5.4-mini",
        display_name="GPT-5.4 Mini",
        input_price=0.75, output_price=4.50, cached_input_price=0.1875,
        max_context=400_000, max_output=128_000,
        supports_vision=True,
        tool_calling=ToolCallReliability.RELIABLE,
        categories=[ModelCategory.FAST, ModelCategory.CODE],
        speed="fast",
        openrouter_id="openai/gpt-5.4-mini",
        native_id="gpt-5.4-mini", native_provider=Provider.OPENAI_NATIVE,
    ),

    "gpt-5.4-nano": ModelSpec(
        id="gpt-5.4-nano",
        display_name="GPT-5.4 Nano",
        input_price=0.20, output_price=1.25, cached_input_price=0.05,
        max_context=400_000, max_output=128_000,
        supports_vision=True,
        tool_calling=ToolCallReliability.RELIABLE,
        categories=[ModelCategory.FAST, ModelCategory.CHEAP],
        speed="fast",
        openrouter_id="openai/gpt-5.4-nano",
        native_id="gpt-5.4-nano", native_provider=Provider.OPENAI_NATIVE,
    ),

    "o3": ModelSpec(
        id="o3",
        display_name="o3 (Deep Reasoning)",
        input_price=2.00, output_price=8.00, cached_input_price=0.50,
        max_context=200_000, max_output=100_000,
        supports_vision=True,
        tool_calling=ToolCallReliability.RELIABLE,
        categories=[ModelCategory.REASONING],
        speed="slow", is_reasoning=True,
        openrouter_id="openai/o3",
        native_id="o3", native_provider=Provider.OPENAI_NATIVE,
    ),

    "o4-mini": ModelSpec(
        id="o4-mini",
        display_name="o4-mini (Reasoning)",
        input_price=1.10, output_price=4.40, cached_input_price=0.275,
        max_context=200_000, max_output=100_000,
        supports_vision=True,
        tool_calling=ToolCallReliability.RELIABLE,
        categories=[ModelCategory.REASONING, ModelCategory.CHEAP],
        speed="medium", is_reasoning=True,
        openrouter_id="openai/o4-mini",
        native_id="o4-mini", native_provider=Provider.OPENAI_NATIVE,
    ),

    # ── Google ────────────────────────────────────────────────────────────────

    "gemini-3.1-pro": ModelSpec(
        id="gemini-3.1-pro",
        display_name="Gemini 3.1 Pro",
        input_price=2.00, output_price=12.00, cached_input_price=0.50,
        max_context=1_048_576, max_output=32_000,
        supports_vision=True,
        tool_calling=ToolCallReliability.RELIABLE,
        categories=[ModelCategory.CODE],
        swe_bench=80.6, speed="medium",
        openrouter_id="google/gemini-3.1-pro-preview",
        native_id="gemini-3.1-pro-preview", native_provider=Provider.GOOGLE_NATIVE,
    ),

    "gemini-2.5-flash": ModelSpec(
        id="gemini-2.5-flash",
        display_name="Gemini 2.5 Flash",
        input_price=0.30, output_price=2.50, cached_input_price=0.075,
        max_context=1_048_576, max_output=16_000,
        supports_vision=True,
        tool_calling=ToolCallReliability.RELIABLE,
        categories=[ModelCategory.FAST],
        speed="fast",
        openrouter_id="google/gemini-2.5-flash",
    ),

    "gemini-2.5-flash-lite": ModelSpec(
        id="gemini-2.5-flash-lite",
        display_name="Gemini 2.5 Flash Lite",
        input_price=0.10, output_price=0.40, cached_input_price=0.025,
        max_context=1_048_576, max_output=8_000,
        supports_vision=True,
        tool_calling=ToolCallReliability.OK,
        categories=[ModelCategory.FAST, ModelCategory.CHEAP],
        speed="fast",
        openrouter_id="google/gemini-2.5-flash-lite",
    ),

    # ── DeepSeek ──────────────────────────────────────────────────────────────

    "deepseek-v3.2": ModelSpec(
        id="deepseek-v3.2",
        display_name="DeepSeek V3.2",
        input_price=0.26, output_price=0.38, cached_input_price=0.07,
        max_context=128_000, max_output=16_000,
        supports_vision=False,
        tool_calling=ToolCallReliability.UNSTABLE,
        categories=[ModelCategory.CHEAP, ModelCategory.CODE],
        swe_bench=73.0, speed="medium",
        openrouter_id="deepseek/deepseek-chat-v3-0324",
    ),

    "deepseek-v3.1": ModelSpec(
        id="deepseek-v3.1",
        display_name="DeepSeek V3.1",
        input_price=0.15, output_price=0.75,
        max_context=128_000, max_output=16_000,
        supports_vision=False,
        tool_calling=ToolCallReliability.UNSTABLE,
        categories=[ModelCategory.CHEAP, ModelCategory.CODE],
        speed="medium",
        openrouter_id="deepseek/deepseek-chat-v3.1",
    ),

    "deepseek-r1": ModelSpec(
        id="deepseek-r1",
        display_name="DeepSeek R1",
        input_price=0.70, output_price=2.50, cached_input_price=0.18,
        max_context=128_000, max_output=64_000,
        supports_vision=False,
        tool_calling=ToolCallReliability.UNSTABLE,
        categories=[ModelCategory.REASONING, ModelCategory.CHEAP],
        speed="slow", is_reasoning=True,
        openrouter_id="deepseek/deepseek-r1",
    ),

    # ── MiniMax ───────────────────────────────────────────────────────────────

    "minimax-m2.5": ModelSpec(
        id="minimax-m2.5",
        display_name="MiniMax M2.5",
        input_price=0.12, output_price=1.00,
        max_context=204_800, max_output=16_000,
        supports_vision=False,
        tool_calling=ToolCallReliability.UNSTABLE,
        categories=[ModelCategory.CODE, ModelCategory.CHEAP],
        swe_bench=80.2, speed="fast",
        openrouter_id="minimax/minimax-m2.5",
    ),

    # ── xAI (Grok) ────────────────────────────────────────────────────────────

    "grok-4": ModelSpec(
        id="grok-4",
        display_name="Grok 4",
        input_price=3.00, output_price=15.00,
        max_context=1_000_000, max_output=32_000,
        supports_vision=True,
        tool_calling=ToolCallReliability.RELIABLE,
        categories=[ModelCategory.GENERAL, ModelCategory.CODE],
        speed="medium",
        openrouter_id="x-ai/grok-4",
    ),

    "grok-4-fast": ModelSpec(
        id="grok-4-fast",
        display_name="Grok 4 Fast",
        input_price=0.20, output_price=0.50,
        max_context=1_000_000, max_output=16_000,
        supports_vision=False,
        tool_calling=ToolCallReliability.RELIABLE,
        categories=[ModelCategory.FAST, ModelCategory.CHEAP],
        speed="fast",
        openrouter_id="x-ai/grok-4-fast",
    ),

    # ── Free Models (verified via OpenRouter API 2026-04-02) ─────────────────

    "qwen3-coder-free": ModelSpec(
        id="qwen3-coder-free",
        display_name="Qwen3 Coder (Free)",
        input_price=0.0, output_price=0.0,
        max_context=262_000, max_output=16_000,
        supports_vision=False,
        tool_calling=ToolCallReliability.OK,
        categories=[ModelCategory.FREE, ModelCategory.CODE],
        speed="medium", is_free=True,
        openrouter_id="qwen/qwen3-coder:free",
    ),

    "minimax-m2.5-free": ModelSpec(
        id="minimax-m2.5-free",
        display_name="MiniMax M2.5 (Free)",
        input_price=0.0, output_price=0.0,
        max_context=196_000, max_output=16_000,
        supports_vision=False,
        tool_calling=ToolCallReliability.RELIABLE,
        categories=[ModelCategory.FREE, ModelCategory.CODE],
        swe_bench=80.2, speed="fast", is_free=True,
        openrouter_id="minimax/minimax-m2.5:free",
    ),

    "qwen3.6-plus-free": ModelSpec(
        id="qwen3.6-plus-free",
        display_name="Qwen 3.6 Plus (Free)",
        input_price=0.0, output_price=0.0,
        max_context=1_000_000, max_output=16_000,
        supports_vision=False,
        tool_calling=ToolCallReliability.OK,
        categories=[ModelCategory.FREE, ModelCategory.GENERAL],
        speed="medium", is_free=True,
        openrouter_id="qwen/qwen3.6-plus:free",
    ),

    "nemotron-3-super-free": ModelSpec(
        id="nemotron-3-super-free",
        display_name="Nemotron 3 Super 120B (Free)",
        input_price=0.0, output_price=0.0,
        max_context=262_000, max_output=16_000,
        supports_vision=False,
        tool_calling=ToolCallReliability.OK,
        categories=[ModelCategory.FREE, ModelCategory.CODE],
        speed="medium", is_free=True,
        openrouter_id="nvidia/nemotron-3-super-120b-a12b:free",
    ),

    "step-3.5-flash-free": ModelSpec(
        id="step-3.5-flash-free",
        display_name="Step 3.5 Flash (Free)",
        input_price=0.0, output_price=0.0,
        max_context=256_000, max_output=16_000,
        supports_vision=False,
        tool_calling=ToolCallReliability.OK,
        categories=[ModelCategory.FREE, ModelCategory.CODE],
        swe_bench=74.4, speed="fast", is_free=True,
        openrouter_id="stepfun/step-3.5-flash:free",
    ),

    "step-3.5-flash": ModelSpec(
        id="step-3.5-flash",
        display_name="Step 3.5 Flash",
        input_price=0.10, output_price=0.30,
        max_context=128_000, max_output=16_000,
        supports_vision=False,
        tool_calling=ToolCallReliability.OK,
        categories=[ModelCategory.CHEAP, ModelCategory.CODE],
        swe_bench=74.4, speed="fast",
        openrouter_id="stepfun/step-3.5-flash",
    ),

    "kimi-k2.5": ModelSpec(
        id="kimi-k2.5",
        display_name="Kimi K2.5",
        input_price=0.38, output_price=1.91,
        max_context=128_000, max_output=16_000,
        supports_vision=False,
        tool_calling=ToolCallReliability.OK,
        categories=[ModelCategory.CODE],
        swe_bench=76.8, speed="medium",
        openrouter_id="moonshotai/kimi-k2.5",
    ),
    "llama-3.3-70b-free": ModelSpec(
        id="llama-3.3-70b-free",
        display_name="Llama 3.3 70B (Free)",
        openrouter_id="meta-llama/llama-3.3-70b-instruct:free",
        max_context=131072,
        input_price=0.0,
        output_price=0.0,
        is_free=True,
        tool_calling=ToolCallReliability.RELIABLE,
    ),
    "gpt-oss-120b-free": ModelSpec(
        id="gpt-oss-120b-free",
        display_name="GPT OSS 120B (Free)",
        openrouter_id="openai/gpt-oss-120b:free",
        max_context=32768,
        input_price=0.0,
        output_price=0.0,
        is_free=True,
        tool_calling=ToolCallReliability.RELIABLE,
    ),
    "qwen3-next-80b-free": ModelSpec(
        id="qwen3-next-80b-free",
        display_name="Qwen3 Next 80B (Free)",
        openrouter_id="qwen/qwen3-next-80b-a3b-instruct:free",
        max_context=32768,
        input_price=0.0,
        output_price=0.0,
        is_free=True,
        tool_calling=ToolCallReliability.RELIABLE,
    ),
}


# ═══════════════════════════════════════════════════════════════════════════════
# IMAGE GENERATION MODELS
# ═══════════════════════════════════════════════════════════════════════════════

IMAGE_MODELS: dict[str, ImageModelSpec] = {

    "flux-2-pro": ImageModelSpec(
        id="flux-2-pro", provider=Provider.FAL_AI,
        display_name="Flux 2 Pro", price_per_image=0.055,
        max_resolution="2048x2048",
        best_for=["photorealism", "portraits", "products", "hero"], speed="fast",
    ),
    "flux-2-schnell": ImageModelSpec(
        id="flux-2-schnell", provider=Provider.FAL_AI,
        display_name="Flux 2 Schnell", price_per_image=0.015,
        max_resolution="1024x1024",
        best_for=["drafts", "bulk", "previews"], speed="fast",
    ),
    "midjourney-v8": ImageModelSpec(
        id="midjourney-v8", provider=Provider.MIDJOURNEY,
        display_name="Midjourney V8", price_per_image=0.10,
        max_resolution="2048x2048",
        best_for=["art", "aesthetics", "premium", "concepts"], speed="medium",
    ),
    "ideogram-v3": ImageModelSpec(
        id="ideogram-v3", provider=Provider.IDEOGRAM,
        display_name="Ideogram V3", price_per_image=0.04,
        supports_text=True,
        best_for=["logos_with_text", "posters", "signage", "typography"], speed="medium",
    ),
    "recraft-v4": ImageModelSpec(
        id="recraft-v4", provider=Provider.FAL_AI,
        display_name="Recraft V4", price_per_image=0.04,
        max_resolution="2048x2048", supports_svg=True,
        best_for=["logos", "icons", "svg", "brand", "vector"], speed="fast",
    ),
    "imagen-4-fast": ImageModelSpec(
        id="imagen-4-fast", provider=Provider.GOOGLE_NATIVE,
        display_name="Imagen 4 Fast", price_per_image=0.02,
        max_resolution="2048x2048",
        best_for=["faces", "portraits", "avatars"], speed="fast",
    ),
    "pexels": ImageModelSpec(
        id="pexels", provider=Provider.PEXELS,
        display_name="Pexels (Free Stock)", price_per_image=0.0,
        best_for=["stock_photos", "backgrounds", "textures"], is_free=True,
    ),
}


# ═══════════════════════════════════════════════════════════════════════════════
# MANUS AGENT
# ═══════════════════════════════════════════════════════════════════════════════

MANUS = ManusSpec()


# ═══════════════════════════════════════════════════════════════════════════════
# HELPER FUNCTIONS
# ═══════════════════════════════════════════════════════════════════════════════

def get_model(model_id: str) -> ModelSpec | None:
    return MODELS.get(model_id)

def get_model_or_raise(model_id: str) -> ModelSpec:
    model = MODELS.get(model_id)
    if not model:
        raise ValueError(f"Unknown model: '{model_id}'. Available: {list(MODELS.keys())}")
    return model

def get_image_model(model_id: str) -> ImageModelSpec | None:
    return IMAGE_MODELS.get(model_id)

def get_models_by_category(category: ModelCategory) -> list[ModelSpec]:
    return [m for m in MODELS.values() if category in m.categories]

def get_free_models() -> list[ModelSpec]:
    return [m for m in MODELS.values() if m.is_free]

def get_models_with_tool_calling(
    min_reliability: ToolCallReliability = ToolCallReliability.RELIABLE,
) -> list[ModelSpec]:
    return [m for m in MODELS.values() if m.tool_calling.is_at_least(min_reliability)]

def get_cheapest_model(
    min_tool_calling: ToolCallReliability = ToolCallReliability.RELIABLE,
    needs_vision: bool = False,
) -> ModelSpec | None:
    candidates = [
        m for m in MODELS.values()
        if not m.is_deprecated
        and m.tool_calling.is_at_least(min_tool_calling)
        and (not needs_vision or m.supports_vision)
    ]
    if not candidates:
        return None
    return min(candidates, key=lambda m: m.input_price + m.output_price)

def estimate_task_cost(model_id: str, input_tokens: int = 5000,
                       output_tokens: int = 2000, use_cache: bool = False) -> float | None:
    model = get_model(model_id)
    if not model:
        return None
    return model.cost_estimate(input_tokens, output_tokens, use_cache=use_cache)


# ═══════════════════════════════════════════════════════════════════════════════
# FALLBACK CHAINS — verified model IDs
# ═══════════════════════════════════════════════════════════════════════════════

FALLBACK_CHAINS: dict[str, list[str]] = {
    "claude-opus-4.6":      ["gpt-5.4", "gemini-3.1-pro", "claude-sonnet-4.6"],
    "claude-sonnet-4.6":    ["gemini-3.1-pro", "gpt-5.4-mini", "claude-haiku-4.5"],
    "claude-haiku-4.5":     ["gpt-5.4-nano", "gemini-2.5-flash"],
    "gpt-5.4":              ["claude-sonnet-4.6", "gemini-3.1-pro"],
    "gpt-5.4-mini":         ["gemini-2.5-flash", "claude-haiku-4.5", "gpt-5.4-nano"],
    "gpt-5.4-nano":         ["gemini-2.5-flash-lite", "grok-4-fast"],
    "o3":                   ["gpt-5.4", "claude-opus-4.6", "o4-mini"],
    "o4-mini":              ["gpt-5.4-mini", "gemini-2.5-flash"],
    "gemini-3.1-pro":       ["gpt-5.4", "claude-sonnet-4.6"],
    "gemini-2.5-flash":     ["gemini-2.5-flash-lite", "gpt-5.4-nano"],
    "gemini-2.5-flash-lite": ["gpt-5.4-nano", "grok-4-fast"],
    "grok-4":               ["gpt-5.4", "claude-sonnet-4.6"],
    "grok-4-fast":          ["gpt-5.4-nano", "gemini-2.5-flash-lite"],
    "deepseek-v3.2":        ["grok-4-fast", "gpt-5.4-nano", "gemini-2.5-flash"],
    "deepseek-v3.1":        ["deepseek-v3.2", "grok-4-fast", "gpt-5.4-nano"],
    "deepseek-r1":          ["o4-mini", "gpt-5.4-mini"],
    "minimax-m2.5":         ["grok-4-fast", "gpt-5.4-nano", "gemini-2.5-flash"],
    "step-3.5-flash-free":  ["minimax-m2.5-free", "qwen3-coder-free", "nemotron-3-super-free"],
    "qwen3-coder-free":     ["minimax-m2.5-free", "step-3.5-flash-free", "nemotron-3-super-free"],
    "minimax-m2.5-free":    ["qwen3-coder-free", "step-3.5-flash-free", "nemotron-3-super-free"],
    "qwen3.6-plus-free":    ["minimax-m2.5-free", "qwen3-coder-free", "step-3.5-flash-free"],
    "nemotron-3-super-free": ["qwen3-coder-free", "step-3.5-flash-free", "minimax-m2.5-free"],
    "llama-3.3-70b-free":   ["qwen3-coder-free", "minimax-m2.5-free", "step-3.5-flash-free"],
    "gpt-oss-120b-free":    ["llama-3.3-70b-free", "qwen3-coder-free", "minimax-m2.5-free"],
    "qwen3-next-80b-free":  ["qwen3.6-plus-free", "minimax-m2.5-free", "step-3.5-flash-free"],
    "step-3.5-flash":       ["kimi-k2.5", "deepseek-v3.1", "gpt-5.4-nano"],
    "kimi-k2.5":            ["step-3.5-flash", "deepseek-v3.2", "gpt-5.4-nano"],
}


def get_fallback(model_id: str, _visited: set | None = None) -> ModelSpec | None:
    if _visited is None:
        _visited = set()
    _visited.add(model_id)
    chain = FALLBACK_CHAINS.get(model_id, [])
    for fb_id in chain:
        if fb_id in _visited:
            continue
        fb = get_model(fb_id)
        if fb and not fb.is_deprecated:
            return fb
    return None


# ═══════════════════════════════════════════════════════════════════════════════
# IMAGE ROUTING HINTS
# ═══════════════════════════════════════════════════════════════════════════════

IMAGE_ROUTING_HINTS: dict[str, str] = {
    "photo_people": "flux-2-pro", "photo_product": "flux-2-pro",
    "art_premium": "midjourney-v8", "art_concept": "midjourney-v8",
    "logo_with_text": "ideogram-v3", "logo_vector": "recraft-v4",
    "icon_svg": "recraft-v4", "draft_preview": "flux-2-schnell",
    "bulk_generation": "flux-2-schnell", "portrait_avatar": "imagen-4-fast",
    "stock_photo": "pexels",
}


# ═══════════════════════════════════════════════════════════════════════════════
# VALIDATION
# ═══════════════════════════════════════════════════════════════════════════════

def validate_registry() -> list[str]:
    issues = []
    for model_id, chain in FALLBACK_CHAINS.items():
        if model_id not in MODELS:
            issues.append(f"FALLBACK_SOURCE: '{model_id}' not in MODELS")
        if model_id in chain:
            issues.append(f"SELF_LOOP: '{model_id}'")
        for fb_id in chain:
            if fb_id not in MODELS:
                issues.append(f"FALLBACK_TARGET: '{model_id}' → '{fb_id}' missing")
    for model_id in MODELS:
        if model_id not in FALLBACK_CHAINS:
            issues.append(f"NO_FALLBACK: '{model_id}'")
    for model_id, m in MODELS.items():
        if m.id != model_id:
            issues.append(f"ID_MISMATCH: key='{model_id}' id='{m.id}'")
    return issues


def print_registry_summary():
    print(f"\n{'='*70}")
    print(f"ARCANE 2 MODEL REGISTRY (verified 2026-04-02)")
    print(f"{'='*70}")
    print(f"\nLLM Models ({len(MODELS)}):")
    for m in sorted(MODELS.values(), key=lambda x: x.input_price + x.output_price):
        tc = m.tool_calling.value[:3].upper()
        free = " [FREE]" if m.is_free else ""
        swe = f" SWE:{m.swe_bench:.1f}%" if m.swe_bench else ""
        print(f"  {m.display_name:<30} ${m.input_price:>5.2f}/${m.output_price:>5.2f}  "
              f"ctx:{m.max_context//1000}K  tc:{tc}{swe}{free}")
    print(f"\nImage Models ({len(IMAGE_MODELS)}):")
    for m in sorted(IMAGE_MODELS.values(), key=lambda x: x.price_per_image):
        print(f"  {m.display_name:<25} ${m.price_per_image:.3f}/img  best: {', '.join(m.best_for[:3])}")
    print(f"\nManus: ${MANUS.monthly_cost}/mo = {MANUS.monthly_credits:,} credits")
    tc_r = len(get_models_with_tool_calling())
    free = len(get_free_models())
    print(f"Reliable tool calling: {tc_r} | Free: {free}")
    issues = validate_registry()
    print(f"Validation: {'ALL CLEAN' if not issues else f'{len(issues)} issues'}")
    if issues:
        for i in issues: print(f"  ⚠ {i}")
    print(f"{'='*70}\n")


if __name__ == "__main__":
    print_registry_summary()


# ═══════════════════════════════════════════════════════════════════════════════
# ROLES / STRATEGY / TIERS — used by preset_manager.py and router.py
# ═══════════════════════════════════════════════════════════════════════════════

from shared.models.schemas import Tier, ModelRole

# Tier escalation: NANO (cheapest) → DEEP (most powerful)
TIER_ESCALATION_ORDER: list[Tier] = [
    Tier.FREE, Tier.NANO, Tier.FAST, Tier.STANDARD, Tier.GENIUS, Tier.DEEP,
]

# ─── ARCANE 3.0 ROLE DEFINITIONS ─────────────────────────────────────────────
#
# 7 production roles (down from 12):
#   director      — classify + plan + delegate + control (ALWAYS top-tier)
#   art_director  — design_spec.json: palette, typography, layout
#   writer        — texts, SEO, content (Claude family for best Russian)
#   developer     — code: HTML/CSS/JS, APIs, integrations
#   researcher    — analysis (Manus collects + LLM analyzes)
#   qa            — code review, lint, validate (NO browser — different model from developer)
#   image_agent   — image generation routing (not LLM, but needs tier for budget)
#
# Removed roles (absorbed):
#   classifier + planner + orchestrator → director
#   coding + coder → developer
#   designer → art_director
#   ssh + browser → Manus capabilities (not LLM roles)
#   search → researcher
#
# Key principle: Director ALWAYS top-tier. Even in LITE = gpt-5.4, not mini.
# Economy is on executors, never on planning.
#
# SSH and browser access: EXCLUSIVELY Manus. No other agent touches servers or browsers.

ROLES: dict[str, ModelRole] = {

    # ── DIRECTOR: always top-tier, never cheap ────────────────────────────────
    "director": ModelRole(
        name="director",
        tiers={
            Tier.FREE:     "gpt-5.4-mini",        # HONEST: NOT free ($0.75/$4.50), but no free model is good enough for Director
                                                    # Alternative: nemotron-3-super-free (truly free, but unreliable planning)
                                                    # Decision: bad plan = wasted money on all executors. $0.02 per plan is cheap insurance.
            Tier.NANO:     "gpt-5.4",              # NEVER below gpt-5.4 except FREE
            Tier.FAST:     "gpt-5.4",              # same: director doesn't downgrade
            Tier.STANDARD: "gpt-5.4",              # OPTIMUM: gpt-5.4 is top-tier enough
            Tier.GENIUS:   "claude-opus-4.6",      # TOP: best reasoning for planning
            Tier.DEEP:     "claude-opus-4.6",       # maximum: same as GENIUS
        },
        fallback_chain={"gpt-5.4": "claude-opus-4.6", "claude-opus-4.6": "gemini-3.1-pro"},
        default_tier=Tier.STANDARD,
    ),

    # ── ART DIRECTOR: design_spec.json ────────────────────────────────────────
    "art_director": ModelRole(
        name="art_director",
        tiers={
            Tier.FREE:     "qwen3.6-plus-free",    # large context, decent design sense
            Tier.NANO:     "gemini-2.5-flash",      # cheap, good structured output
            Tier.FAST:     "gemini-2.5-flash",      # LITE: flash handles basic palettes
            Tier.STANDARD: "claude-sonnet-4.6",     # OPTIMUM: excellent design thinking
            Tier.GENIUS:   "claude-opus-4.6",       # TOP: deep aesthetic reasoning
            Tier.DEEP:     "claude-opus-4.6",
        },
        fallback_chain={"claude-sonnet-4.6": "gemini-2.5-flash", "claude-opus-4.6": "claude-sonnet-4.6"},
        default_tier=Tier.STANDARD,
    ),

    # ── WRITER: Claude family for best Russian text ───────────────────────────
    "writer": ModelRole(
        name="writer",
        tiers={
            Tier.FREE:     "qwen3.6-plus-free",    # decent Russian text
            Tier.NANO:     "claude-haiku-4.5",      # cheapest Claude, still good Russian
            Tier.FAST:     "claude-haiku-4.5",      # LITE: haiku writes acceptable SEO
            Tier.STANDARD: "claude-sonnet-4.6",     # OPTIMUM: excellent Russian prose
            Tier.GENIUS:   "claude-opus-4.6",       # TOP: best Russian text quality
            Tier.DEEP:     "claude-opus-4.6",
        },
        fallback_chain={"claude-opus-4.6": "claude-sonnet-4.6", "claude-sonnet-4.6": "claude-haiku-4.5"},
        default_tier=Tier.STANDARD,
    ),

    # ── DEVELOPER: code (author — paired with QA as reviewer) ─────────────────
    "developer": ModelRole(
        name="developer",
        tiers={
            Tier.FREE:     "minimax-m2.5-free",     # SWE-bench 80.2, free, tool-capable
            Tier.NANO:     "deepseek-v3.2",          # $0.26/$0.38, SWE-bench 73
            Tier.FAST:     "deepseek-v3.2",          # LITE: deepseek does good code cheap
            Tier.STANDARD: "claude-sonnet-4.6",      # OPTIMUM: SWE-bench 79.6, reliable tools
            Tier.GENIUS:   "claude-sonnet-4.6",      # TOP: sonnet is best code model
            Tier.DEEP:     "claude-opus-4.6",        # maximum: opus for complex architecture
        },
        fallback_chain={"claude-sonnet-4.6": "deepseek-v3.2", "deepseek-v3.2": "grok-4-fast"},
        default_tier=Tier.STANDARD,
    ),

    # ── RESEARCHER: Manus collects sites + LLM analyzes ───────────────────────
    "researcher": ModelRole(
        name="researcher",
        tiers={
            Tier.FREE:     "qwen3.6-plus-free",     # 1M context free
            Tier.NANO:     "gemini-2.5-flash",       # 1M context, $0.30/$2.50
            Tier.FAST:     "grok-4-fast",            # LITE: 1M context, $0.20/$0.50
            Tier.STANDARD: "gemini-2.5-flash",       # OPTIMUM: 1M context, cheap, fast
            Tier.GENIUS:   "gemini-3.1-pro",         # TOP: 1M context, best analysis
            Tier.DEEP:     "gemini-3.1-pro",
        },
        fallback_chain={"gemini-3.1-pro": "gpt-5.4", "gemini-2.5-flash": "grok-4-fast"},
        default_tier=Tier.STANDARD,
    ),

    # ── QA: code review (DIFFERENT model from developer — different "eyes") ───
    "qa": ModelRole(
        name="qa",
        tiers={
            Tier.FREE:     "minimax-m2.5-free",      # free, tool-capable, SWE-bench 80.2
            Tier.NANO:     "gpt-5.4-nano",            # cheap GPT for basic lint review
            Tier.FAST:     "grok-4-fast",              # LITE: different family from developer
            Tier.STANDARD: "gpt-5.4-mini",             # OPTIMUM: GPT reviews Claude's code
            Tier.GENIUS:   "gpt-5.4",                  # TOP: full GPT-5.4 for thorough review
            Tier.DEEP:     "gpt-5.4",
        },
        fallback_chain={"gpt-5.4": "grok-4", "gpt-5.4-mini": "grok-4-fast"},
        default_tier=Tier.FAST,
    ),

    # ── IMAGE AGENT: routing to image generation models ───────────────────────
    # NOTE: These IDs reference IMAGE_MODELS, not MODELS (LLM).
    # image_agent is not a real LLM role — it routes to image generation APIs.
    # The IDs below are from IMAGE_MODELS dict, resolved separately from LLM tiers.
    "image_agent": ModelRole(
        name="image_agent",
        tiers={
            Tier.FREE:     "pexels",                  # free stock photos
            Tier.NANO:     "flux-2-schnell",           # $0.015/img, fast drafts
            Tier.FAST:     "imagen-4-fast",             # LITE: $0.02/img, Google Imagen
            Tier.STANDARD: "flux-2-pro",               # OPTIMUM: $0.055/img, photorealism
            Tier.GENIUS:   "midjourney-v8",             # TOP: $0.10/img, premium aesthetics
            Tier.DEEP:     "midjourney-v8",
        },
        default_tier=Tier.STANDARD,
    ),
    # ── MARKETER: positioning, audience, brand strategy ──────────────────────
    "marketer": ModelRole(
        name="marketer",
        tiers={
            Tier.FREE:     "qwen3.6-plus-free",    # decent marketing thinking
            Tier.NANO:     "claude-haiku-4.5",      # fast, cheap marketing copy
            Tier.FAST:     "claude-haiku-4.5",      # LITE: haiku handles basic briefs
            Tier.STANDARD: "claude-sonnet-4.6",     # OPTIMUM: excellent brand strategy
            Tier.GENIUS:   "claude-opus-4.6",       # TOP: deep positioning, audience insight
            Tier.DEEP:     "claude-opus-4.6",
        },
        fallback_chain={"claude-opus-4.6": "claude-sonnet-4.6", "claude-sonnet-4.6": "claude-haiku-4.5"},
        default_tier=Tier.STANDARD,
    ),

    # ── SEO WRITER: content architecture, LSI, copy ──────────────────────────
    "seo_writer": ModelRole(
        name="seo_writer",
        tiers={
            Tier.FREE:     "qwen3.6-plus-free",    # decent Russian SEO
            Tier.NANO:     "claude-haiku-4.5",      # cheapest Claude, still good Russian
            Tier.FAST:     "claude-haiku-4.5",      # LITE: haiku writes acceptable SEO
            Tier.STANDARD: "claude-sonnet-4.6",     # OPTIMUM: excellent Russian SEO prose
            Tier.GENIUS:   "claude-sonnet-4.6",     # TOP: sonnet is best for structured content
            Tier.DEEP:     "claude-opus-4.6",       # maximum: opus for premium copy
        },
        fallback_chain={"claude-sonnet-4.6": "claude-haiku-4.5", "claude-opus-4.6": "claude-sonnet-4.6"},
        default_tier=Tier.STANDARD,
    ),
    # ── OBSERVER: mediator, dispatcher, watchdog (Haiku — fast & cheap) ────────
    "observer": ModelRole(
        name="observer",
        tiers={
            Tier.FREE:     "qwen3.6-plus-free",    # free fallback
            Tier.NANO:     "claude-haiku-4.5",      # primary — fast routing
            Tier.FAST:     "claude-haiku-4.5",      # always Haiku for observer
            Tier.STANDARD: "claude-haiku-4.5",      # Haiku is optimal for dispatch
            Tier.GENIUS:   "claude-haiku-4.5",      # even in top mode, Haiku mediates
            Tier.DEEP:     "claude-sonnet-4.6",     # deep analysis only if needed
        },
        fallback_chain={"claude-haiku-4.5": "gpt-5.4-nano"},
        default_tier=Tier.FAST,
    ),
    # ── MOTION DEV: GSAP, Three.js, CSS animations, Lottie, WebGL ────────────
    "motion_dev": ModelRole(
        name="motion_dev",
        tiers={
            Tier.FREE:     "qwen3-coder-free",      # basic CSS animations
            Tier.NANO:     "claude-haiku-4.5",      # simple transitions
            Tier.FAST:     "deepseek-v3.2",         # LITE: good GSAP code
            Tier.STANDARD: "claude-sonnet-4.6",     # OPTIMUM: excellent motion code
            Tier.GENIUS:   "claude-sonnet-4.6",     # TOP: Sonnet > Opus for animation code
            Tier.DEEP:     "claude-sonnet-4.6",     # Sonnet is best for complex Three.js
        },
        fallback_chain={"claude-sonnet-4.6": "claude-haiku-4.5"},
        default_tier=Tier.STANDARD,
    ),
}


# ═══════════════════════════════════════════════════════════════════════════════
# BACKWARD-COMPAT ALIASES (transitional — old role names → new role names)
# Remove these after all callers are updated.
# ═══════════════════════════════════════════════════════════════════════════════

_ROLE_ALIASES: dict[str, str] = {
    "classifier":   "director",
    "planner":      "director",
    "orchestrator": "director",
    "coding":       "developer",
    "coder":        "developer",
    "designer":     "art_director",
    "ssh":          "developer",      # SSH is Manus capability, fallback to developer
    "browser":      "developer",      # browser is Manus capability, fallback to developer
    "search":       "researcher",
    "creative_director": "marketer",
    "brand":        "marketer",
    "copywriter":   "seo_writer",
    "content":      "seo_writer",
    # ARCANE 4.0 new roles
    "watcher":       "observer",
    "mediator":      "observer",
    "dispatcher":    "observer",
    "watchdog":      "observer",
    "animator":      "motion_dev",
    "gsap":          "motion_dev",
    "threejs":       "motion_dev",
    "frontend_anim": "motion_dev",
}

def resolve_role(role_name: str) -> str:
    """Resolve old role names to new ones. Returns canonical role name."""
    return _ROLE_ALIASES.get(role_name, role_name)

# Inject aliases as SEPARATE lookup, not into ROLES dict itself.
# Old code injected into ROLES making len(ROLES) = 16 instead of 7.
# Now: ROLES has 7 entries. Use resolve_role() to handle old names.
# Legacy code doing ROLES["coder"] will still work via __getitem__ override.

class _RolesWithAliases(dict):
    """ROLES dict that transparently resolves old role names via aliases."""
    def __getitem__(self, key):
        resolved = _ROLE_ALIASES.get(key, key)
        return super().__getitem__(resolved)
    
    def __contains__(self, key):
        resolved = _ROLE_ALIASES.get(key, key)
        return super().__contains__(resolved)
    
    def get(self, key, default=None):
        resolved = _ROLE_ALIASES.get(key, key)
        return super().get(resolved, default)

# Convert ROLES to alias-aware dict (keeps 7 canonical entries)
ROLES = _RolesWithAliases(ROLES)

# Strategy → per-role tier mapping.
# PresetManager._MODE_TO_STRATEGY maps user mode → strategy key.
#   FREE → "free"    LITE → "economy"    OPTIMUM → "balance"    TOP → "quality"
#
# KEY PRINCIPLE: Director NEVER downgrades below STANDARD (= gpt-5.4).
# Economy is on executors, never on planning.

STRATEGY_TIER_MAP: dict[str, dict[str, Tier]] = {

    "economy": {    # LITE mode — Director stays top, executors go cheap
        "observer":     Tier.NANO,       # haiku — always cheap
        "motion_dev":   Tier.FAST,       # deepseek for basic animations
        "director":     Tier.STANDARD,   # gpt-5.4 — NEVER below this
        "art_director": Tier.FAST,       # gemini-2.5-flash
        "writer":       Tier.FAST,       # claude-haiku-4.5
        "developer":    Tier.FAST,       # deepseek-v3.2
        "researcher":   Tier.FAST,       # grok-4-fast
        "qa":           Tier.FAST,       # grok-4-fast
        "image_agent":  Tier.FAST,       # imagen-4-fast
    },

    "balance": {    # OPTIMUM mode (default) — 90% quality at 50% price
        "observer":     Tier.FAST,       # haiku — routing
        "motion_dev":   Tier.STANDARD,   # sonnet — good animations
        "director":     Tier.STANDARD,   # gpt-5.4
        "art_director": Tier.STANDARD,   # claude-sonnet-4.6
        "writer":       Tier.STANDARD,   # claude-sonnet-4.6
        "developer":    Tier.STANDARD,   # claude-sonnet-4.6
        "researcher":   Tier.STANDARD,   # gemini-2.5-flash
        "qa":           Tier.STANDARD,   # gpt-5.4-mini
        "image_agent":  Tier.STANDARD,   # flux-2-pro
    },

    "quality": {    # TOP mode — best model per role
        "observer":     Tier.FAST,       # haiku even in top mode
        "motion_dev":   Tier.GENIUS,     # sonnet — best motion code
        "director":     Tier.GENIUS,     # claude-opus-4.6
        "art_director": Tier.GENIUS,     # claude-opus-4.6
        "writer":       Tier.GENIUS,     # claude-opus-4.6
        "developer":    Tier.GENIUS,     # claude-sonnet-4.6 (sonnet > opus for code)
        "researcher":   Tier.GENIUS,     # gemini-3.1-pro
        "qa":           Tier.GENIUS,     # gpt-5.4
        "image_agent":  Tier.GENIUS,     # midjourney-v8
    },

    # "free" strategy is registered dynamically by preset_manager.ensure_free_strategy()

    "arcane4": {    # ARCANE 4.0 — Opus Director + Sonnet Engineer + Manus Executor
        # ── Nervous System ──────────────────────────────────────────────────
        "observer":     Tier.FAST,       # claude-haiku-4.5 — dispatcher, watchdog, budget guard
        # ── Brain: Strategy (Opus) ──────────────────────────────────────────
        "director":     Tier.GENIUS,     # claude-opus-4.6 — planning, delegation
        "art_director": Tier.GENIUS,     # claude-opus-4.6 — design_spec.json, visual QA
        "marketer":     Tier.GENIUS,     # claude-opus-4.6 — positioning.json, brand strategy
        "writer":       Tier.GENIUS,     # claude-opus-4.6 — premium copy, tone of voice
        # ── Brain: Engineering (Sonnet) ─────────────────────────────────────
        "developer":    Tier.GENIUS,     # claude-sonnet-4.6 — React/Next.js, backend API
        "motion_dev":   Tier.GENIUS,     # claude-sonnet-4.6 — GSAP, Three.js, animations
        "seo_writer":   Tier.STANDARD,   # claude-sonnet-4.6 — semantic core, H1-H3 structure
        # ── Brain: Research & QA ────────────────────────────────────────────
        "researcher":   Tier.GENIUS,     # gemini-3.1-pro — 1M context, market analysis
        "qa":           Tier.GENIUS,     # gpt-5.4 — cross-family code review
        # ── Assets ──────────────────────────────────────────────────────────
        "image_agent":  Tier.GENIUS,     # midjourney-v8 — premium visuals, icons
    },
}

# Backward compat: inject old role names into strategy maps
for _strategy_name, _strategy_map in STRATEGY_TIER_MAP.items():
    for _old_role, _new_role in _ROLE_ALIASES.items():
        if _old_role not in _strategy_map and _new_role in _strategy_map:
            _strategy_map[_old_role] = _strategy_map[_new_role]


# ═══════════════════════════════════════════════════════════════════════════════
# BACKWARD-COMPAT HELPERS — keep old-style callers working
# ═══════════════════════════════════════════════════════════════════════════════

# Simple role→model_id dict for code that does ROLES_SIMPLE["coder"]
ROLES_SIMPLE: dict[str, str] = {
    role_name: role_def.tiers.get(role_def.default_tier, "claude-sonnet-4.6")
    for role_name, role_def in ROLES.items()
}


def get_fallback_model(model_id: str) -> "ModelSpec | None":
    """Alias for get_fallback — backward compat."""
    return get_fallback(model_id)


def get_model_for_role(role: str, tier: str = "standard") -> "ModelSpec | None":
    """Return best model for a given role and tier (backward compat)."""
    role_def = ROLES.get(role)
    if role_def:
        # Try to map string tier to Tier enum
        _tier_map = {"budget": Tier.NANO, "standard": Tier.STANDARD,
                     "premium": Tier.GENIUS, "max": Tier.DEEP}
        t = _tier_map.get(tier, Tier.STANDARD)
        model_id = role_def.tiers.get(t)
        if model_id:
            return MODELS.get(model_id)
        # Fallback to default tier
        model_id = role_def.tiers.get(role_def.default_tier)
        if model_id:
            return MODELS.get(model_id)
    return get_cheapest_model()


def get_next_tier(current_tier: str) -> str:
    """Return the next escalation tier (backward compat, returns string)."""
    _order = ["budget", "standard", "premium", "max"]
    try:
        idx = _order.index(current_tier)
        return _order[min(idx + 1, len(_order) - 1)]
    except ValueError:
        return "standard"

# ═══════════════════════════════════════════════════════════════════════════════
# MODEL ID CANONICALIZATION — Fix #4
# ═══════════════════════════════════════════════════════════════════════════════

# Alias mapping: all variants → canonical id
_MODEL_ALIASES: dict[str, str] = {}

def _build_aliases():
    """Build alias map from all known model IDs."""
    for model_id, spec in MODELS.items():
        canonical = model_id  # e.g. "claude-opus-4.6"
        _MODEL_ALIASES[canonical] = canonical
        # Dashed variant: "claude-opus-4-6"
        dashed = canonical.replace(".", "-")
        _MODEL_ALIASES[dashed] = canonical
        # With provider prefix from openrouter_id: "anthropic/claude-opus-4.6"
        if hasattr(spec, 'openrouter_id') and spec.openrouter_id:
            _MODEL_ALIASES[spec.openrouter_id] = canonical
        # Native id variant
        if hasattr(spec, 'native_id') and spec.native_id:
            _MODEL_ALIASES[spec.native_id] = canonical

_build_aliases()

def canonicalize_model_id(model_id: str) -> str:
    """Convert any model ID variant to canonical format.
    
    Handles:
    - "claude-opus-4.6"          (canonical)
    - "claude-opus-4-6"          (dashed variant)
    - "anthropic/claude-opus-4.6" (provider-prefixed)
    """
    return _MODEL_ALIASES.get(model_id, model_id)

def get_model_price(model_id: str) -> tuple[float, float]:
    """Get (input_price, output_price) per 1M tokens for any model ID format.
    
    Returns safe fallback (0.01, 0.01) instead of $0 for unknown models.
    """
    canonical = canonicalize_model_id(model_id)
    spec = MODELS.get(canonical)
    if spec:
        return (spec.input_price, spec.output_price)
    return (0.01, 0.01)  # safe fallback, not $0
