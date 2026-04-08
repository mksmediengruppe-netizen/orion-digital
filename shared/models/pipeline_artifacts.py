"""
ARCANE 4.0 - Pipeline Artifacts Schemas
========================================
Pydantic models for artifacts produced and consumed by WEB_DESIGN v2 pipeline.

Used by pipeline_templates.py to validate structured outputs from LLM specialists.
If a phase returns invalid JSON, validate_artifact() fails the gate and the
phase retries with validation errors as feedback.

This replaces the soft text-based Haiku gates with hard Pydantic validation.
"""
from __future__ import annotations
from typing import Optional
from pydantic import BaseModel, Field, field_validator


# ═══════════════════════════════════════════════════════════════════════════
# Phase 2: RESEARCH
# ═══════════════════════════════════════════════════════════════════════════

class AwwwardsReference(BaseModel):
    """One Awwwards reference collected by Manus."""
    url: str
    title: str
    why_relevant: str = Field(..., min_length=20)
    key_elements_to_borrow: list[str] = Field(default_factory=list)
    colors: list[str] = Field(default_factory=list)
    typography: str = ""
    animation_style: str = "subtle"


class Competitor(BaseModel):
    name: str
    url: str
    headline: str = ""
    usp: str = ""
    pricing: str = ""
    strengths: list[str] = Field(default_factory=list)
    weaknesses: list[str] = Field(default_factory=list)


class MarketInsights(BaseModel):
    common_patterns: list[str] = Field(default_factory=list)
    differentiators: list[str] = Field(default_factory=list)
    typical_price_range: str = ""
    target_audience_hints: list[str] = Field(default_factory=list)


class ResearchReport(BaseModel):
    """Phase 2 RESEARCH output. Main input for Phase 3 STRATEGY."""
    niche: str = Field(..., min_length=3)
    awwwards_references: list[AwwwardsReference] = Field(..., min_length=1)
    competitors: list[Competitor] = Field(default_factory=list)
    market_insights: MarketInsights
    gaps: list[str] = Field(default_factory=list)
    confidence: float = Field(..., ge=0.0, le=1.0)

    @field_validator("awwwards_references")
    @classmethod
    def min_references(cls, v):
        if len(v) < 1:
            raise ValueError("Need at least 1 Awwwards reference")
        return v


# ═══════════════════════════════════════════════════════════════════════════
# Phase 3: STRATEGY
# ═══════════════════════════════════════════════════════════════════════════

class Positioning(BaseModel):
    """Phase 3 STRATEGY output from Opus-Marketer."""
    brand_name: str
    target_audience: str = Field(..., min_length=20)
    pain_points: list[str] = Field(..., min_length=1)
    unique_value_proposition: str = Field(..., min_length=10)
    offers: list[str] = Field(..., min_length=1)
    tone_of_voice: str
    key_messages: list[str] = Field(..., min_length=2)
    competitors_considered: list[str] = Field(default_factory=list)


# ═══════════════════════════════════════════════════════════════════════════
# Phase 4: CREATIVE DIRECTION
# ═══════════════════════════════════════════════════════════════════════════

class ColorPalette(BaseModel):
    primary: str = Field(..., pattern=r"^#[0-9a-fA-F]{6}$")
    secondary: str = Field(..., pattern=r"^#[0-9a-fA-F]{6}$")
    accent: str = Field(..., pattern=r"^#[0-9a-fA-F]{6}$")
    background: str = Field(..., pattern=r"^#[0-9a-fA-F]{6}$")
    text: str = Field(..., pattern=r"^#[0-9a-fA-F]{6}$")
    text_muted: Optional[str] = None
    border: Optional[str] = None
    surface: Optional[str] = None


class Typography(BaseModel):
    headings_family: str
    body_family: str
    headings_weight: int = 500
    body_weight: int = 400
    headings_tracking: str = "normal"
    base_size_px: int = 16


class Spacing(BaseModel):
    unit_px: int = 4
    scale: list[int] = Field(default_factory=lambda: [0, 1, 2, 3, 4, 6, 8, 12, 16, 24, 32])

    @field_validator('scale', mode='before')
    @classmethod
    def parse_scale(cls, v):
        if isinstance(v, list):
            result = []
            for item in v:
                if isinstance(item, int):
                    result.append(item)
                elif isinstance(item, str):
                    # Extract number from strings like '4px', '8rem', '16'
                    import re
                    m = re.match(r'^(\d+)', item.strip())
                    result.append(int(m.group(1)) if m else 0)
                else:
                    result.append(int(item))
            return result
        return v


class DesignTokens(BaseModel):
    """Phase 4 CREATIVE DIRECTION output from Opus-Creative Director."""
    mood: str
    palette: ColorPalette
    typography: Typography
    spacing: Spacing
    border_radius_px: int = 8
    shadow_style: str = "none"
    layout_concept: str = Field(..., min_length=30)
    image_prompts: list[str] = Field(default_factory=list)


# ═══════════════════════════════════════════════════════════════════════════
# Phase 5: CONTENT + ASSETS
# ═══════════════════════════════════════════════════════════════════════════

class MetaTags(BaseModel):
    title: str = Field(..., max_length=60)
    description: str = Field(..., min_length=140, max_length=170)
    og_title: str
    og_description: str


class HeroContent(BaseModel):
    h1: str = Field(..., min_length=5, max_length=80)
    subheading: str = Field(..., min_length=20, max_length=200)
    cta_primary: str
    cta_secondary: Optional[str] = None


class SectionContent(BaseModel):
    id: str
    h2: str
    body: str = Field(..., min_length=50)
    highlights: list[str] = Field(default_factory=list)


class FeatureItem(BaseModel):
    h3: str
    description: str
    benefit: str


class CTABlock(BaseModel):
    h2: str
    subtext: str
    button_text: str
    disclaimer: Optional[str] = None


class ContentSpec(BaseModel):
    """SEO Copywriter output - all page copy."""
    meta: MetaTags
    hero: HeroContent
    sections: list[SectionContent] = Field(..., min_length=2)
    features: list[FeatureItem] = Field(default_factory=list)
    cta_block: CTABlock
    footer_tagline: str = ""


class IconSlot(BaseModel):
    location: str
    icon_name: str
    size_px: int = Field(..., ge=12, le=96)
    color_token: str
    reasoning: str = ""


class IconsSpec(BaseModel):
    """Icons Specialist output - Lucide icons selection."""
    slots: list[IconSlot] = Field(..., min_length=1)
    total_icons: int
    style_notes: str = ""
    lucide_version: str = "0.400+"


class MotionAnimation(BaseModel):
    trigger: str
    target: str
    library: str
    description: str
    duration_ms: int = 300
    easing: str = "ease-out"


class MotionSpec(BaseModel):
    """Motion Dev output - site animations."""
    animations: list[MotionAnimation] = Field(default_factory=list)
    page_load_sequence: str = ""
    scroll_behavior: str = "default"
    reduced_motion_respected: bool = True


# ═══════════════════════════════════════════════════════════════════════════
# Phase 6: DESIGN BRIEF
# ═══════════════════════════════════════════════════════════════════════════

class ManusBrief(BaseModel):
    """Main pipeline artifact - the brief for Manus in markdown format.

    Not validated by structure (it is free markdown), but enforces minimum
    length to catch undercooked briefs.
    """
    markdown: str = Field(..., min_length=2000)
    word_count: int
    sections_covered: list[str] = Field(..., min_length=5)
    references_included: int = Field(..., ge=1)
    estimated_quality_score: float = Field(..., ge=0.0, le=1.0)


# ═══════════════════════════════════════════════════════════════════════════
# Phase 8: QA
# ═══════════════════════════════════════════════════════════════════════════

class QAIssue(BaseModel):
    severity: str
    category: str
    location: str = ""
    problem: str
    fix: str = ""


class QAReport(BaseModel):
    """Gemini Visual QA output."""
    verdict: str
    visual_score: float = Field(..., ge=0.0, le=10.0)
    matches_references: bool
    issues: list[QAIssue] = Field(default_factory=list)
    instructions_for_fixer: str = ""


class A11yReport(BaseModel):
    """A11y Controller output."""
    verdict: str
    wcag_level: str
    score: int = Field(..., ge=0, le=100)
    issues: list[QAIssue] = Field(default_factory=list)
    summary: str
    must_fix_count: int = 0
    should_fix_count: int = 0


# ═══════════════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════════════

def extract_json(text: str) -> dict:
    """Extract JSON object from LLM output (handles markdown code blocks)."""
    import json
    import re

    text = text.strip()
    if text.startswith("{"):
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(1))
        except json.JSONDecodeError:
            pass

    if "{" in text and "}" in text:
        start = text.find("{")
        end = text.rfind("}") + 1
        try:
            return json.loads(text[start:end])
        except json.JSONDecodeError:
            pass

    raise ValueError(f"No valid JSON found in text (first 200 chars): {text[:200]}")


def validate_artifact(model_cls, raw_text: str) -> tuple[bool, object, str]:
    """Validate LLM output against a Pydantic model.

    Returns:
        (ok, parsed_model_or_none, error_message)
    """
    from pydantic import ValidationError

    try:
        raw_json = extract_json(raw_text)
    except ValueError as e:
        return False, None, f"Not valid JSON: {e}"

    try:
        model = model_cls.model_validate(raw_json)
        return True, model, ""
    except ValidationError as e:
        errors = []
        for err in e.errors():
            loc = ".".join(str(x) for x in err["loc"])
            errors.append(f"{loc}: {err['msg']}")
        return False, None, "Validation errors: " + "; ".join(errors)
