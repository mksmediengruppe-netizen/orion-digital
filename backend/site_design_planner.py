"""
Site Design Planner — По brief и blueprint определяет визуальный стиль.
Определяет цвета, шрифты, spacing, паттерны секций.
Выход: site_design_spec.json
"""
import json
import logging
import re

logger = logging.getLogger(__name__)

# ── Пресеты стилей ──────────────────────────────────────────────
STYLE_PRESETS = {
    "modern_light": {
        "visual_style": "light",
        "primary_color": "#2563EB",
        "accent_color": "#F59E0B",
        "bg_color": "#FFFFFF",
        "text_color": "#1F2937",
        "text_muted": "#6B7280",
        "font_family": "'Inter', sans-serif",
        "font_heading": "'Inter', sans-serif",
        "border_radius": "12px",
        "shadow": "0 4px 6px -1px rgba(0,0,0,0.1)",
    },
    "modern_dark": {
        "visual_style": "dark",
        "primary_color": "#3B82F6",
        "accent_color": "#F59E0B",
        "bg_color": "#0F172A",
        "text_color": "#F1F5F9",
        "text_muted": "#94A3B8",
        "font_family": "'Inter', sans-serif",
        "font_heading": "'Inter', sans-serif",
        "border_radius": "12px",
        "shadow": "0 4px 6px -1px rgba(0,0,0,0.3)",
    },
    "corporate": {
        "visual_style": "light",
        "primary_color": "#1E40AF",
        "accent_color": "#DC2626",
        "bg_color": "#FFFFFF",
        "text_color": "#111827",
        "text_muted": "#6B7280",
        "font_family": "'Roboto', sans-serif",
        "font_heading": "'Montserrat', sans-serif",
        "border_radius": "8px",
        "shadow": "0 1px 3px rgba(0,0,0,0.12)",
    },
    "luxury": {
        "visual_style": "dark",
        "primary_color": "#D4AF37",
        "accent_color": "#FFFFFF",
        "bg_color": "#1A1A2E",
        "text_color": "#E0E0E0",
        "text_muted": "#A0A0A0",
        "font_family": "'Playfair Display', serif",
        "font_heading": "'Playfair Display', serif",
        "border_radius": "4px",
        "shadow": "0 8px 32px rgba(0,0,0,0.3)",
    },
    "tech": {
        "visual_style": "dark",
        "primary_color": "#06B6D4",
        "accent_color": "#8B5CF6",
        "bg_color": "#0B1120",
        "text_color": "#E2E8F0",
        "text_muted": "#94A3B8",
        "font_family": "'JetBrains Mono', monospace",
        "font_heading": "'Inter', sans-serif",
        "border_radius": "8px",
        "shadow": "0 4px 30px rgba(6,182,212,0.1)",
    },
    "friendly": {
        "visual_style": "light",
        "primary_color": "#7C3AED",
        "accent_color": "#F472B6",
        "bg_color": "#FAFAFA",
        "text_color": "#374151",
        "text_muted": "#9CA3AF",
        "font_family": "'Nunito', sans-serif",
        "font_heading": "'Nunito', sans-serif",
        "border_radius": "16px",
        "shadow": "0 10px 25px rgba(124,58,237,0.1)",
    },
}

# ── Паттерны секций ──────────────────────────────────────────────
SECTION_PATTERNS = {
    "hero_with_image": {"layout": "split", "image_position": "right", "full_width": True},
    "text_with_image": {"layout": "split", "image_position": "left", "full_width": False},
    "cards_grid": {"layout": "grid", "columns": 3, "full_width": False},
    "gallery_grid": {"layout": "masonry", "columns": 3, "full_width": True},
    "pricing_cards": {"layout": "grid", "columns": 3, "full_width": False, "highlighted": 1},
    "testimonials_slider": {"layout": "slider", "full_width": False},
    "team_cards": {"layout": "grid", "columns": 4, "full_width": False},
    "accordion": {"layout": "stack", "full_width": False, "max_width": "800px"},
    "contact_form": {"layout": "split", "form_position": "left", "full_width": False},
    "icons_grid": {"layout": "grid", "columns": 4, "full_width": False},
    "steps_timeline": {"layout": "timeline", "full_width": False},
    "cta_banner": {"layout": "center", "full_width": True, "bg_gradient": True},
    "logo_carousel": {"layout": "carousel", "full_width": True},
    "blog_cards": {"layout": "grid", "columns": 3, "full_width": False},
    "generic_section": {"layout": "stack", "full_width": False},
}


def plan_design(brief: dict, blueprint: dict, llm_call=None) -> dict:
    """
    Планирует визуальный дизайн сайта.
    
    Args:
        brief: Структурированный brief
        blueprint: Blueprint сайта
        llm_call: Опциональная LLM функция
    
    Returns:
        dict: Спецификация дизайна
    """
    # Определяем пресет стиля
    preset_name = _select_preset(brief)
    preset = STYLE_PRESETS[preset_name].copy()
    
    # Переопределяем цвета если указаны в brief
    if "colors_hint" in brief.get("style_preferences", {}):
        _apply_color_hints(preset, brief["style_preferences"]["colors_hint"])
    
    # Spacing system
    spacing = {
        "section_padding": "80px 0",
        "section_padding_mobile": "48px 0",
        "container_max_width": "1200px",
        "container_padding": "0 24px",
        "card_gap": "24px",
        "element_gap": "16px",
    }
    
    # Section-specific design
    sections_design = []
    for section in blueprint.get("sections", []):
        section_type = section.get("type", "generic_section")
        pattern = SECTION_PATTERNS.get(section_type, SECTION_PATTERNS["generic_section"])
        
        section_design = {
            "id": section["id"],
            "type": section_type,
            "pattern": pattern,
            "bg_alternate": _should_alternate_bg(section["id"], blueprint["sections"]),
            "animation": "fade-up" if section.get("has_animation") else None,
            "animation_delay": 100,
        }
        sections_design.append(section_design)
    
    # Visual hierarchy
    hierarchy = {
        "h1_size": "3.5rem",
        "h2_size": "2.5rem",
        "h3_size": "1.5rem",
        "body_size": "1rem",
        "small_size": "0.875rem",
        "h1_weight": "800",
        "h2_weight": "700",
        "h3_weight": "600",
        "line_height": "1.6",
    }
    
    # Breakpoints
    breakpoints = {
        "mobile": "375px",
        "tablet": "768px",
        "desktop": "1024px",
        "wide": "1440px",
    }
    
    # Animations
    animations = {
        "library": "AOS",
        "default_animation": "fade-up",
        "duration": 800,
        "offset": 100,
        "once": True,
    }
    
    design_spec = {
        "preset": preset_name,
        "colors": preset,
        "spacing": spacing,
        "typography": hierarchy,
        "breakpoints": breakpoints,
        "animations": animations,
        "sections_design": sections_design,
        "google_fonts": _get_google_fonts(preset),
        "css_framework": "tailwind_cdn",
        "icon_library": "lucide",
    }
    
    # LLM enrichment
    if llm_call:
        try:
            enriched = _llm_refine_design(design_spec, brief, llm_call)
            if enriched:
                design_spec.update(enriched)
        except Exception as e:
            logger.warning(f"LLM design refinement failed: {e}")
    
    logger.info(f"[DesignPlanner] Design spec: preset={preset_name}, "
                f"sections={len(sections_design)}, fonts={design_spec['google_fonts']}")
    return design_spec


def _select_preset(brief: dict) -> str:
    """Выбирает пресет стиля на основе brief"""
    style = brief.get("style_preferences", {})
    tone = brief.get("tone", "professional")
    site_type = brief.get("site_type", "landing")
    theme = style.get("theme", "light")
    
    if tone == "luxury":
        return "luxury"
    if tone == "tech" or any(w in str(brief).lower() for w in ["tech", "it", "software", "saas"]):
        return "tech"
    if tone == "friendly":
        return "friendly"
    if site_type == "corporate":
        return "corporate"
    if theme == "dark":
        return "modern_dark"
    return "modern_light"


def _apply_color_hints(preset: dict, hints: str):
    """Применяет цветовые подсказки из brief"""
    # Extract hex colors
    hex_colors = re.findall(r'#[0-9A-Fa-f]{6}', hints)
    if len(hex_colors) >= 1:
        preset["primary_color"] = hex_colors[0]
    if len(hex_colors) >= 2:
        preset["accent_color"] = hex_colors[1]
    
    # Named colors
    color_map = {
        "синий": "#2563EB", "голубой": "#06B6D4", "зелёный": "#059669",
        "красный": "#DC2626", "оранжевый": "#EA580C", "фиолетовый": "#7C3AED",
        "розовый": "#EC4899", "жёлтый": "#EAB308", "чёрный": "#111827",
    }
    hints_lower = hints.lower()
    for name, color in color_map.items():
        if name in hints_lower:
            preset["primary_color"] = color
            break


def _should_alternate_bg(section_id: str, all_sections: list) -> bool:
    """Определяет нужен ли альтернативный фон для секции"""
    idx = next((i for i, s in enumerate(all_sections) if s["id"] == section_id), 0)
    return idx % 2 == 1


def _get_google_fonts(preset: dict) -> list:
    """Возвращает список Google Fonts для подключения"""
    fonts = set()
    for key in ("font_family", "font_heading"):
        font = preset.get(key, "")
        match = re.search(r"'([^']+)'", font)
        if match:
            fonts.add(match.group(1))
    return list(fonts)


def _llm_refine_design(design_spec: dict, brief: dict, llm_call) -> dict:
    """Уточняет дизайн через LLM"""
    prompt = f"""Ты — UI/UX дизайнер. Улучши цветовую палитру для сайта.

Brief: {json.dumps(brief, ensure_ascii=False)[:1000]}
Текущие цвета: primary={design_spec['colors']['primary_color']}, accent={design_spec['colors']['accent_color']}

Верни JSON:
{{"primary_color": "#hex", "accent_color": "#hex", "gradient": "linear-gradient(...)"}}

ТОЛЬКО JSON."""
    
    response = llm_call(prompt)
    try:
        json_match = re.search(r'\{[\s\S]*?\}', response)
        if json_match:
            data = json.loads(json_match.group())
            if "primary_color" in data:
                design_spec["colors"]["primary_color"] = data["primary_color"]
            if "accent_color" in data:
                design_spec["colors"]["accent_color"] = data["accent_color"]
            if "gradient" in data:
                design_spec["colors"]["gradient"] = data["gradient"]
    except (json.JSONDecodeError, AttributeError):
        pass
    return {}


def save_design_spec(spec: dict, path: str = "site_design_spec.json"):
    """Сохраняет спецификацию дизайна"""
    with open(path, "w", encoding="utf-8") as f:
        json.dump(spec, f, ensure_ascii=False, indent=2)
    logger.info(f"[DesignPlanner] Design spec saved to {path}")
    return path
