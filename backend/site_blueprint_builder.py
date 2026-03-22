"""
Site Blueprint Builder — Строит полную структуру сайта по brief.
Определяет секции, навигацию, фото, формы, deliverables.
Выход: site_blueprint.json
"""
import json
import logging
import re

logger = logging.getLogger(__name__)

# ── Шаблоны секций ──────────────────────────────────────────────
SECTION_TEMPLATES = {
    "hero": {
        "type": "hero_with_image",
        "photo_needed": True,
        "has_cta": True,
        "default_cta": "Получить консультацию",
    },
    "about": {
        "type": "text_with_image",
        "photo_needed": True,
        "has_cta": False,
    },
    "services": {
        "type": "cards_grid",
        "photo_needed": True,
        "has_cta": True,
        "default_cta": "Подробнее",
    },
    "portfolio": {
        "type": "gallery_grid",
        "photo_needed": True,
        "has_cta": False,
    },
    "pricing": {
        "type": "pricing_cards",
        "photo_needed": False,
        "has_cta": True,
        "default_cta": "Выбрать тариф",
    },
    "reviews": {
        "type": "testimonials_slider",
        "photo_needed": True,
        "has_cta": False,
    },
    "team": {
        "type": "team_cards",
        "photo_needed": True,
        "has_cta": False,
    },
    "faq": {
        "type": "accordion",
        "photo_needed": False,
        "has_cta": False,
    },
    "contacts": {
        "type": "contact_form",
        "photo_needed": False,
        "has_cta": True,
        "default_cta": "Отправить",
    },
    "advantages": {
        "type": "icons_grid",
        "photo_needed": False,
        "has_cta": False,
    },
    "process": {
        "type": "steps_timeline",
        "photo_needed": False,
        "has_cta": False,
    },
    "gallery": {
        "type": "masonry_gallery",
        "photo_needed": True,
        "has_cta": False,
    },
    "cta": {
        "type": "cta_banner",
        "photo_needed": False,
        "has_cta": True,
        "default_cta": "Начать сейчас",
    },
    "partners": {
        "type": "logo_carousel",
        "photo_needed": True,
        "has_cta": False,
    },
    "blog": {
        "type": "blog_cards",
        "photo_needed": True,
        "has_cta": True,
        "default_cta": "Читать далее",
    },
}

# ── Стандартные формы ────────────────────────────────────────────
DEFAULT_FORMS = {
    "contacts": {
        "fields": ["name", "phone", "email", "message"],
        "submit_text": "Отправить",
        "action": "send.php",
    },
    "hero": {
        "fields": ["name", "phone"],
        "submit_text": "Получить консультацию",
        "action": "send.php",
    },
    "cta": {
        "fields": ["name", "phone"],
        "submit_text": "Заказать",
        "action": "send.php",
    },
}


def build_blueprint(brief: dict, llm_call=None) -> dict:
    """
    Строит полную структуру сайта по brief.
    
    Args:
        brief: Структурированный brief из site_brief_parser
        llm_call: Опциональная функция LLM для генерации контента
    
    Returns:
        dict: Полный blueprint сайта
    """
    site_name = brief.get("domain", "").split(".")[0] if brief.get("domain") else "site"
    site_type = brief.get("site_type", "landing")
    required_sections = brief.get("required_sections", ["hero", "about", "services", "contacts"])
    goal = brief.get("goal", "leads")
    audience = brief.get("audience", "")
    
    # ── Строим секции ────────────────────────────────────────
    sections = []
    photos_total = 0
    photo_prompts = []
    forms = []
    navigation = []
    
    for section_id in required_sections:
        template = SECTION_TEMPLATES.get(section_id, {
            "type": "generic_section",
            "photo_needed": False,
            "has_cta": False,
        })
        
        section = {
            "id": section_id,
            "type": template["type"],
            "h1": _generate_heading(section_id, brief),
            "subtitle": _generate_subtitle(section_id, brief),
            "photo_needed": template.get("photo_needed", False),
            "has_cta": template.get("has_cta", False),
            "has_animation": section_id not in ("hero",),  # AOS for all except hero
        }
        
        # Фото
        if section["photo_needed"]:
            prompt = _generate_photo_prompt(section_id, brief)
            section["photo_prompt"] = prompt
            photo_prompts.append({"section": section_id, "prompt": prompt})
            
            # Некоторые секции требуют несколько фото
            if section_id in ("reviews", "team"):
                extra_count = 3
                for i in range(extra_count):
                    extra_prompt = _generate_photo_prompt(section_id, brief, variant=i + 1)
                    photo_prompts.append({"section": section_id, "prompt": extra_prompt, "variant": i + 1})
                photos_total += extra_count + 1
            elif section_id in ("portfolio", "gallery"):
                extra_count = 4
                for i in range(extra_count):
                    extra_prompt = _generate_photo_prompt(section_id, brief, variant=i + 1)
                    photo_prompts.append({"section": section_id, "prompt": extra_prompt, "variant": i + 1})
                photos_total += extra_count + 1
            else:
                photos_total += 1
        
        # CTA
        if section["has_cta"]:
            section["cta_text"] = template.get("default_cta", "Подробнее")
        
        # Формы
        if section_id in DEFAULT_FORMS:
            form = DEFAULT_FORMS[section_id].copy()
            form["section"] = section_id
            forms.append(form)
            section["has_form"] = True
        
        # Навигация (не все секции в меню)
        nav_name = _section_nav_name(section_id)
        if nav_name and section_id not in ("hero", "cta"):
            navigation.append(nav_name)
        
        sections.append(section)
    
    # ── Добавляем CTA секцию если goal=leads и нет CTA ──────
    if goal == "leads" and "cta" not in required_sections:
        cta_section = {
            "id": "cta",
            "type": "cta_banner",
            "h1": "Готовы начать?",
            "subtitle": "Оставьте заявку и мы свяжемся с вами",
            "photo_needed": False,
            "has_cta": True,
            "cta_text": "Оставить заявку",
            "has_animation": True,
        }
        # Insert before contacts
        contacts_idx = next((i for i, s in enumerate(sections) if s["id"] == "contacts"), len(sections))
        sections.insert(contacts_idx, cta_section)
    
    # ── Footer ───────────────────────────────────────────────
    footer = {
        "has_logo": True,
        "has_social": True,
        "has_copyright": True,
        "has_privacy_link": True,
        "has_nav": True,
        "social_links": ["telegram", "whatsapp", "vk"],
    }
    
    # ── Deliverables ─────────────────────────────────────────
    deliverables = ["index.html", "style.css", "main.js", "send.php", "privacy.html"]
    deliverables.append(f"{photos_total} AI photos")
    if brief.get("bitrix_mode", "none") != "none":
        deliverables.extend(["bitrixsetup.php", "bitrix_template/"])
    
    # ── Собираем blueprint ───────────────────────────────────
    blueprint = {
        "name": site_name,
        "type": site_type,
        "goal": goal,
        "audience": audience,
        "sections": sections,
        "navigation": navigation,
        "footer": footer,
        "photos_total": photos_total,
        "photo_prompts": photo_prompts,
        "forms": forms,
        "deliverables": deliverables,
        "meta": {
            "title": _generate_meta_title(brief),
            "description": _generate_meta_description(brief),
            "favicon": True,
            "og_tags": True,
        },
    }
    
    # LLM enrichment
    if llm_call:
        try:
            enriched = _llm_enrich_blueprint(blueprint, brief, llm_call)
            if enriched:
                blueprint.update(enriched)
        except Exception as e:
            logger.warning(f"LLM blueprint enrichment failed: {e}")
    
    logger.info(f"[BlueprintBuilder] Built blueprint: {len(sections)} sections, "
                f"{photos_total} photos, {len(forms)} forms, {len(navigation)} nav items")
    return blueprint


def _generate_heading(section_id: str, brief: dict) -> str:
    """Генерирует заголовок секции"""
    headings = {
        "hero": brief.get("key_messages", [""])[0] if brief.get("key_messages") else "Ваш надёжный партнёр",
        "about": "О нас",
        "services": "Наши услуги",
        "portfolio": "Портфолио",
        "pricing": "Тарифы",
        "reviews": "Отзывы клиентов",
        "team": "Наша команда",
        "faq": "Частые вопросы",
        "contacts": "Свяжитесь с нами",
        "advantages": "Наши преимущества",
        "process": "Как мы работаем",
        "gallery": "Галерея",
        "cta": "Готовы начать?",
        "partners": "Наши партнёры",
        "blog": "Блог",
    }
    return headings.get(section_id, section_id.replace("_", " ").title())


def _generate_subtitle(section_id: str, brief: dict) -> str:
    """Генерирует подзаголовок секции"""
    subtitles = {
        "hero": "Профессиональные решения для вашего бизнеса",
        "about": "Узнайте больше о нашей компании и ценностях",
        "services": "Полный спектр услуг для достижения ваших целей",
        "portfolio": "Примеры наших лучших работ",
        "pricing": "Прозрачные цены без скрытых платежей",
        "reviews": "Что говорят о нас наши клиенты",
        "team": "Профессионалы, которые работают для вас",
        "faq": "Ответы на популярные вопросы",
        "contacts": "Мы всегда на связи",
        "advantages": "Почему клиенты выбирают нас",
        "process": "Простой и прозрачный процесс работы",
    }
    return subtitles.get(section_id, "")


def _generate_photo_prompt(section_id: str, brief: dict, variant: int = 0) -> str:
    """Генерирует промпт для AI-фото"""
    audience = brief.get("audience", "бизнес")
    
    prompts = {
        "hero": f"Professional hero image, modern office or workspace, bright and clean, {audience} theme",
        "about": f"Team working together in modern office, professional atmosphere, {audience}",
        "services": f"Professional service illustration, modern and clean, {audience} industry",
        "portfolio": f"Portfolio showcase, professional project result, variant {variant}",
        "reviews": f"Professional headshot portrait, business person, confident smile, variant {variant}",
        "team": f"Professional team member portrait, friendly and approachable, variant {variant}",
        "gallery": f"High quality professional photo, {audience} industry, variant {variant}",
        "partners": f"Professional company logo placeholder, clean design",
        "blog": f"Blog article illustration, modern and engaging, variant {variant}",
    }
    return prompts.get(section_id, f"Professional photo for {section_id} section")


def _section_nav_name(section_id: str) -> str:
    """Возвращает название секции для навигации"""
    nav_names = {
        "about": "О нас",
        "services": "Услуги",
        "portfolio": "Портфолио",
        "pricing": "Тарифы",
        "reviews": "Отзывы",
        "team": "Команда",
        "faq": "FAQ",
        "contacts": "Контакты",
        "advantages": "Преимущества",
        "process": "Как мы работаем",
        "gallery": "Галерея",
        "partners": "Партнёры",
        "blog": "Блог",
    }
    return nav_names.get(section_id, "")


def _generate_meta_title(brief: dict) -> str:
    """Генерирует meta title"""
    domain = brief.get("domain", "")
    site_type = brief.get("site_type", "сайт")
    return f"{domain} — {site_type}" if domain else "Профессиональный сайт"


def _generate_meta_description(brief: dict) -> str:
    """Генерирует meta description"""
    goal = brief.get("goal", "info")
    audience = brief.get("audience", "клиентов")
    return f"Профессиональный сайт для {audience}. Оставьте заявку и получите консультацию."


def _llm_enrich_blueprint(blueprint: dict, brief: dict, llm_call) -> dict:
    """Обогащает blueprint через LLM"""
    prompt = f"""Улучши blueprint сайта. Верни JSON с улучшенными заголовками и подзаголовками для каждой секции.

Brief: {json.dumps(brief, ensure_ascii=False)[:1500]}

Текущие секции:
{json.dumps([{"id": s["id"], "h1": s["h1"], "subtitle": s["subtitle"]} for s in blueprint["sections"]], ensure_ascii=False)}

Верни JSON:
{{"sections_update": [{{"id": "hero", "h1": "улучшенный заголовок", "subtitle": "улучшенный подзаголовок"}}, ...]}}

ТОЛЬКО JSON, без пояснений."""
    
    response = llm_call(prompt)
    try:
        json_match = re.search(r'\{[\s\S]*\}', response)
        if json_match:
            data = json.loads(json_match.group())
            if "sections_update" in data:
                updates = {s["id"]: s for s in data["sections_update"]}
                for section in blueprint["sections"]:
                    if section["id"] in updates:
                        upd = updates[section["id"]]
                        if "h1" in upd:
                            section["h1"] = upd["h1"]
                        if "subtitle" in upd:
                            section["subtitle"] = upd["subtitle"]
            return {}
    except (json.JSONDecodeError, AttributeError, KeyError):
        pass
    return {}


def save_blueprint(blueprint: dict, path: str = "site_blueprint.json"):
    """Сохраняет blueprint в JSON файл"""
    with open(path, "w", encoding="utf-8") as f:
        json.dump(blueprint, f, ensure_ascii=False, indent=2)
    logger.info(f"[BlueprintBuilder] Blueprint saved to {path}")
    return path
