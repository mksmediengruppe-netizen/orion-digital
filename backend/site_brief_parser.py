"""
Site Brief Parser — Разбирает ТЗ клиента в структурированный JSON.
Определяет тип сайта, аудиторию, цели, секции, стиль и ограничения.
Выход: site_brief.json
"""
import json
import logging
import re

logger = logging.getLogger(__name__)


def parse_site_brief(tz_text: str, llm_call=None) -> dict:
    """
    Парсит текстовое ТЗ и возвращает структурированный brief.
    
    Args:
        tz_text: Полный текст ТЗ
        llm_call: Опциональная функция для LLM-анализа (signature: llm_call(prompt) -> str)
    
    Returns:
        dict: Структурированный brief
    """
    brief = {
        "site_type": _detect_site_type(tz_text),
        "audience": _detect_audience(tz_text),
        "goal": _detect_goal(tz_text),
        "required_sections": _detect_sections(tz_text),
        "style_preferences": _detect_style(tz_text),
        "constraints": _detect_constraints(tz_text),
        "domain": _extract_domain(tz_text),
        "server": _extract_server(tz_text),
        "install_path": _extract_install_path(tz_text),
        "bitrix_mode": _detect_bitrix(tz_text),
        "raw_tz": tz_text[:5000],
    }

    # If LLM is available, enrich with AI analysis
    if llm_call:
        try:
            enriched = _llm_enrich_brief(tz_text, llm_call)
            if enriched:
                brief.update(enriched)
        except Exception as e:
            logger.warning(f"LLM enrichment failed: {e}")

    logger.info(f"[SiteBriefParser] Parsed brief: type={brief['site_type']}, "
                f"goal={brief['goal']}, sections={len(brief['required_sections'])}, "
                f"bitrix={brief['bitrix_mode']}")
    return brief


def _detect_site_type(text: str) -> str:
    """Определяет тип сайта: landing, corporate, shop, portal"""
    text_lower = text.lower()
    if any(w in text_lower for w in ["лендинг", "landing", "одностраничн", "посадочн"]):
        return "landing"
    if any(w in text_lower for w in ["магазин", "shop", "e-commerce", "ecommerce", "каталог товар", "корзин"]):
        return "shop"
    if any(w in text_lower for w in ["портал", "portal", "личный кабинет", "dashboard"]):
        return "portal"
    if any(w in text_lower for w in ["корпоративн", "corporate", "компани"]):
        return "corporate"
    return "landing"


def _detect_audience(text: str) -> str:
    """Извлекает целевую аудиторию"""
    patterns = [
        r"(?:целевая\s+аудитория|ЦА|аудитория|target\s+audience)[:\s—–-]+([^\n.]{10,100})",
        r"(?:для\s+)([\w\s,]{10,80}?)(?:\.|,\s*(?:которые|кто))",
    ]
    for pat in patterns:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            return m.group(1).strip()
    return "не указана"


def _detect_goal(text: str) -> str:
    """Определяет цель сайта: leads, sales, info, branding"""
    text_lower = text.lower()
    if any(w in text_lower for w in ["заявк", "лид", "lead", "форма обратн", "обратный звонок", "заказать"]):
        return "leads"
    if any(w in text_lower for w in ["продаж", "купить", "оплат", "корзин", "sale"]):
        return "sales"
    if any(w in text_lower for w in ["бренд", "brand", "имидж", "узнаваем"]):
        return "branding"
    return "info"


def _detect_sections(text: str) -> list:
    """Извлекает требуемые секции из ТЗ"""
    section_keywords = {
        "hero": ["hero", "главный экран", "первый экран", "шапка", "баннер"],
        "about": ["о нас", "о компании", "about", "кто мы"],
        "services": ["услуги", "services", "что мы делаем", "направления"],
        "portfolio": ["портфолио", "portfolio", "наши работы", "кейсы", "проекты"],
        "pricing": ["цены", "тарифы", "pricing", "стоимость", "прайс"],
        "reviews": ["отзывы", "reviews", "testimonials", "клиенты говорят"],
        "team": ["команда", "team", "наши специалисты"],
        "faq": ["faq", "вопросы", "частые вопросы", "вопрос-ответ"],
        "contacts": ["контакты", "contacts", "связаться", "обратная связь"],
        "cta": ["cta", "призыв", "call to action", "получить", "заказать"],
        "advantages": ["преимущества", "advantages", "почему мы", "выгоды"],
        "process": ["процесс", "этапы", "как мы работаем", "шаги"],
        "gallery": ["галерея", "gallery", "фото"],
        "blog": ["блог", "blog", "статьи", "новости"],
        "partners": ["партнёры", "partners", "клиенты"],
    }
    text_lower = text.lower()
    found = []
    for section_id, keywords in section_keywords.items():
        if any(kw in text_lower for kw in keywords):
            found.append(section_id)
    # Always include hero and contacts for landing
    if "hero" not in found:
        found.insert(0, "hero")
    if "contacts" not in found:
        found.append("contacts")
    return found


def _detect_style(text: str) -> dict:
    """Определяет стилевые предпочтения"""
    text_lower = text.lower()
    style = {
        "theme": "light",
        "modern": True,
        "animations": True,
        "mobile_first": True,
    }
    if any(w in text_lower for w in ["тёмн", "dark", "чёрн"]):
        style["theme"] = "dark"
    if any(w in text_lower for w in ["минимализм", "minimal", "простой"]):
        style["modern"] = True
        style["animations"] = False
    # Extract colors if mentioned
    color_match = re.search(r"(?:цвет|color)[:\s]+([#\w\s,]+?)(?:\.|;|\n)", text, re.IGNORECASE)
    if color_match:
        style["colors_hint"] = color_match.group(1).strip()
    return style


def _detect_constraints(text: str) -> list:
    """Извлекает ограничения и требования"""
    constraints = []
    text_lower = text.lower()
    if any(w in text_lower for w in ["mobile", "мобильн", "адаптив", "responsive"]):
        constraints.append("mobile-first")
    if any(w in text_lower for w in ["быстр", "скорость", "fast", "performance"]):
        constraints.append("fast-load")
    if any(w in text_lower for w in ["seo", "поисков", "индексац"]):
        constraints.append("seo-optimized")
    if any(w in text_lower for w in ["https", "ssl", "безопасн"]):
        constraints.append("https-required")
    if any(w in text_lower for w in ["битрикс", "bitrix", "1с"]):
        constraints.append("bitrix-integration")
    return constraints


def _extract_domain(text: str) -> str:
    """Извлекает домен из ТЗ"""
    patterns = [
        r"(?:домен|domain|сайт|url)[:\s]+(?:https?://)?([a-zA-Z0-9][-a-zA-Z0-9]*\.[a-zA-Z]{2,}(?:\.[a-zA-Z]{2,})?)",
        r"(?:https?://)?([a-zA-Z0-9][-a-zA-Z0-9]*\.(?:ru|com|net|org|io|dev)(?:\.[a-zA-Z]{2,})?)",
    ]
    for pat in patterns:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            return m.group(1)
    return ""


def _extract_server(text: str) -> dict:
    """Извлекает данные сервера"""
    server = {"host": "", "user": "", "password": "", "port": 22}
    # IP address
    ip_match = re.search(r"(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})", text)
    if ip_match:
        server["host"] = ip_match.group(1)
    # User
    user_match = re.search(r"(?:user|пользователь|логин)[:\s]+(\w+)", text, re.IGNORECASE)
    if user_match:
        server["user"] = user_match.group(1)
    elif "root@" in text:
        server["user"] = "root"
    # Password
    pwd_match = re.search(r"(?:password|пароль|pass)[:\s]+(\S+)", text, re.IGNORECASE)
    if pwd_match:
        server["password"] = pwd_match.group(1)
    return server


def _extract_install_path(text: str) -> str:
    """Извлекает путь установки"""
    path_match = re.search(r"(/var/www/[\w/.-]+|/home/[\w/.-]+)", text)
    if path_match:
        return path_match.group(1)
    # Check for subdirectory
    subdir_match = re.search(r"(?:папк|директори|каталог|path|subdirectory)[:\s]+/?(\w+)", text, re.IGNORECASE)
    if subdir_match:
        return f"/var/www/html/{subdir_match.group(1)}"
    return "/var/www/html"


def _detect_bitrix(text: str) -> str:
    """Определяет режим Битрикс: none, install, template, full"""
    text_lower = text.lower()
    if not any(w in text_lower for w in ["битрикс", "bitrix", "1с-битрикс", "1c-bitrix"]):
        return "none"
    if any(w in text_lower for w in ["установи", "install", "развернуть", "поставить"]):
        return "install"
    if any(w in text_lower for w in ["шаблон", "template", "тема"]):
        return "template"
    return "full"


def _llm_enrich_brief(tz_text: str, llm_call) -> dict:
    """Обогащает brief через LLM-анализ"""
    prompt = f"""Проанализируй ТЗ на создание сайта и верни JSON:
{{
  "site_type": "landing|corporate|shop",
  "audience": "описание ЦА",
  "goal": "leads|sales|info|branding",
  "tone": "professional|friendly|luxury|tech",
  "key_messages": ["сообщение 1", "сообщение 2"],
  "competitors_mentioned": ["конкурент 1"],
  "unique_selling_points": ["УТП 1", "УТП 2"]
}}

ТЗ:
{tz_text[:3000]}

Ответь ТОЛЬКО JSON, без пояснений."""
    
    response = llm_call(prompt)
    # Extract JSON from response
    try:
        json_match = re.search(r'\{[\s\S]*\}', response)
        if json_match:
            return json.loads(json_match.group())
    except (json.JSONDecodeError, AttributeError):
        pass
    return {}


def save_brief(brief: dict, path: str = "site_brief.json"):
    """Сохраняет brief в JSON файл"""
    with open(path, "w", encoding="utf-8") as f:
        json.dump(brief, f, ensure_ascii=False, indent=2)
    logger.info(f"[SiteBriefParser] Brief saved to {path}")
    return path
