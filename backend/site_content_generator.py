"""
Site Content Generator — Генерирует тексты для каждой секции сайта.
Работает по blueprint: заголовки, описания, FAQ, отзывы, тарифы.
Выход: site_content.json
"""
import json
import logging
import re
from typing import Optional, Callable

logger = logging.getLogger(__name__)

# ── Шаблоны контента по типам секций ─────────────────────────────
CONTENT_TEMPLATES = {
    "hero": {
        "h1": "Профессиональные решения для вашего бизнеса",
        "subtitle": "Мы помогаем компаниям расти и развиваться с помощью современных технологий",
        "cta": "Получить консультацию",
    },
    "about": {
        "h1": "О нашей компании",
        "subtitle": "Более 10 лет опыта в создании цифровых решений",
        "text": "Мы — команда профессионалов, которая помогает бизнесу достигать новых высот. "
                "Наш подход основан на глубоком понимании потребностей клиентов и использовании "
                "передовых технологий.",
    },
    "services": {
        "h1": "Наши услуги",
        "subtitle": "Полный спектр решений для вашего бизнеса",
        "items": [
            {"title": "Разработка сайтов", "description": "Создание современных и функциональных веб-сайтов"},
            {"title": "Дизайн", "description": "Уникальный дизайн, который выделит вас среди конкурентов"},
            {"title": "Маркетинг", "description": "Комплексное продвижение вашего бизнеса в интернете"},
        ],
    },
    "advantages": {
        "h1": "Почему выбирают нас",
        "subtitle": "Наши ключевые преимущества",
        "items": [
            {"title": "Опыт", "description": "Более 500 успешных проектов", "icon": "🏆"},
            {"title": "Качество", "description": "Гарантия результата на каждом этапе", "icon": "✅"},
            {"title": "Скорость", "description": "Соблюдение сроков без компромиссов", "icon": "⚡"},
            {"title": "Поддержка", "description": "Техническая поддержка 24/7", "icon": "🛡️"},
        ],
    },
    "process": {
        "h1": "Как мы работаем",
        "subtitle": "Простой и прозрачный процесс",
        "steps": [
            {"title": "Анализ", "description": "Изучаем ваш бизнес и определяем цели"},
            {"title": "Проектирование", "description": "Создаём структуру и дизайн"},
            {"title": "Разработка", "description": "Воплощаем проект в жизнь"},
            {"title": "Запуск", "description": "Тестируем и запускаем проект"},
        ],
    },
    "pricing": {
        "h1": "Тарифы",
        "subtitle": "Прозрачные цены без скрытых платежей",
        "plans": [
            {
                "name": "Старт",
                "price": "от 30 000 ₽",
                "features": ["Лендинг", "Адаптивный дизайн", "Форма заявки", "Базовое SEO"],
                "featured": False,
            },
            {
                "name": "Бизнес",
                "price": "от 80 000 ₽",
                "features": ["Корпоративный сайт", "До 10 страниц", "CMS система", "SEO оптимизация", "Аналитика"],
                "featured": True,
            },
            {
                "name": "Премиум",
                "price": "от 150 000 ₽",
                "features": ["Интернет-магазин", "Интеграции", "Личный кабинет", "Полное SEO", "Поддержка 1 год"],
                "featured": False,
            },
        ],
    },
    "reviews": {
        "h1": "Отзывы клиентов",
        "subtitle": "Что говорят о нас наши клиенты",
        "reviews": [
            {"name": "Алексей Петров", "role": "CEO, TechStart", "text": "Отличная работа! Сайт был готов в срок и полностью соответствует нашим ожиданиям."},
            {"name": "Мария Иванова", "role": "Маркетолог, BrandCo", "text": "Профессиональный подход и внимание к деталям. Рекомендую!"},
            {"name": "Дмитрий Козлов", "role": "Директор, LogiTrans", "text": "Благодаря новому сайту мы увеличили количество заявок в 3 раза."},
        ],
    },
    "team": {
        "h1": "Наша команда",
        "subtitle": "Профессионалы, которые работают для вас",
        "members": [
            {"name": "Иван Сидоров", "role": "CEO & Founder", "bio": "15 лет в IT"},
            {"name": "Елена Волкова", "role": "Lead Designer", "bio": "Создаёт красоту"},
            {"name": "Павел Морозов", "role": "Lead Developer", "bio": "Full-stack эксперт"},
            {"name": "Анна Белова", "role": "Project Manager", "bio": "Держит всё под контролем"},
        ],
    },
    "faq": {
        "h1": "Частые вопросы",
        "subtitle": "Ответы на популярные вопросы",
        "items": [
            {"question": "Сколько стоит создание сайта?", "answer": "Стоимость зависит от сложности проекта. Лендинг — от 30 000 ₽, корпоративный сайт — от 80 000 ₽."},
            {"question": "Какие сроки разработки?", "answer": "Лендинг — 1-2 недели, корпоративный сайт — 3-6 недель, интернет-магазин — 4-8 недель."},
            {"question": "Вы делаете SEO?", "answer": "Да, базовое SEO входит во все тарифы. Расширенное SEO-продвижение — отдельная услуга."},
            {"question": "Есть ли гарантия?", "answer": "Да, мы даём гарантию 12 месяцев на все работы и бесплатно исправляем баги."},
            {"question": "Можно ли доработать сайт позже?", "answer": "Конечно! Мы предлагаем пакеты поддержки и доработки на постоянной основе."},
        ],
    },
    "contacts": {
        "h1": "Свяжитесь с нами",
        "subtitle": "Мы всегда на связи",
        "info_html": "<p><strong>Телефон:</strong> +7 (800) 000-00-00</p>"
                     "<p><strong>Email:</strong> info@company.ru</p>"
                     "<p><strong>Адрес:</strong> Москва, ул. Примерная, д. 1</p>"
                     "<p><strong>Режим работы:</strong> Пн-Пт 9:00-18:00</p>",
    },
    "cta": {
        "h1": "Готовы начать?",
        "subtitle": "Оставьте заявку и мы свяжемся с вами в течение часа",
        "cta": "Оставить заявку",
    },
    "gallery": {
        "h1": "Галерея",
        "subtitle": "Наши лучшие работы",
    },
    "partners": {
        "h1": "Наши партнёры",
        "subtitle": "Компании, которые нам доверяют",
    },
    "blog": {
        "h1": "Блог",
        "subtitle": "Полезные статьи и новости",
        "items": [
            {"title": "Тренды веб-дизайна 2026", "description": "Обзор главных трендов в дизайне сайтов"},
            {"title": "Как увеличить конверсию", "description": "5 проверенных способов повысить конверсию"},
            {"title": "SEO для начинающих", "description": "Базовые принципы поисковой оптимизации"},
        ],
    },
}


def generate_content(blueprint: dict, brief: dict, llm_call: Optional[Callable] = None) -> dict:
    """
    Генерирует контент для всех секций сайта.

    Args:
        blueprint: site_blueprint.json
        brief: site_brief.json
        llm_call: Опциональная LLM функция (prompt -> str)

    Returns:
        dict: Контент для каждой секции {section_id: {h1, subtitle, items, ...}}
    """
    content = {}
    sections = blueprint.get("sections", [])

    for section in sections:
        sid = section["id"]
        template = CONTENT_TEMPLATES.get(sid, {"h1": section.get("h1", sid), "subtitle": ""})

        if llm_call:
            try:
                generated = _llm_generate_section(sid, section, brief, llm_call)
                if generated:
                    content[sid] = generated
                    continue
            except Exception as e:
                logger.warning(f"LLM content gen failed for {sid}: {e}")

        # Fallback to templates
        content[sid] = template.copy()
        # Override with blueprint headings if available
        if section.get("h1"):
            content[sid]["h1"] = section["h1"]
        if section.get("subtitle"):
            content[sid]["subtitle"] = section["subtitle"]

    logger.info(f"[ContentGenerator] Generated content for {len(content)} sections")
    return content


def _llm_generate_section(sid: str, section: dict, brief: dict, llm_call) -> dict:
    """Генерирует контент секции через LLM."""
    section_type = section.get("type", "generic")
    audience = brief.get("audience", "бизнес")
    goal = brief.get("goal", "leads")
    tone = brief.get("style_preferences", {}).get("tone", "professional")

    prompt = f"""Сгенерируй контент для секции "{sid}" (тип: {section_type}) сайта.

Аудитория: {audience}
Цель сайта: {goal}
Тон: {tone}
Brief: {json.dumps(brief, ensure_ascii=False)[:800]}

Верни JSON для секции "{sid}":
- h1: заголовок секции
- subtitle: подзаголовок"""

    if sid == "services":
        prompt += '\n- items: [{title, description}] (3-6 штук)'
    elif sid == "advantages":
        prompt += '\n- items: [{title, description, icon}] (4 штуки, icon — emoji)'
    elif sid == "process":
        prompt += '\n- steps: [{title, description}] (3-5 шагов)'
    elif sid == "pricing":
        prompt += '\n- plans: [{name, price, features: [], featured: bool}] (3 тарифа)'
    elif sid == "reviews":
        prompt += '\n- reviews: [{name, role, text}] (3 отзыва)'
    elif sid == "faq":
        prompt += '\n- items: [{question, answer}] (4-6 вопросов)'
    elif sid == "team":
        prompt += '\n- members: [{name, role, bio}] (3-4 человека)'
    elif sid in ("about",):
        prompt += '\n- text: основной текст (2-3 абзаца)'

    prompt += "\n\nОТВЕТЬ ТОЛЬКО JSON, без пояснений."

    response = llm_call(prompt)
    try:
        json_match = re.search(r'\{[\s\S]*\}', response)
        if json_match:
            data = json.loads(json_match.group())
            if "h1" in data:
                return data
    except (json.JSONDecodeError, AttributeError):
        pass
    return None


def save_content(content: dict, path: str = "site_content.json"):
    """Сохраняет контент в JSON файл."""
    with open(path, "w", encoding="utf-8") as f:
        json.dump(content, f, ensure_ascii=False, indent=2)
    logger.info(f"[ContentGenerator] Content saved to {path}")
    return path
