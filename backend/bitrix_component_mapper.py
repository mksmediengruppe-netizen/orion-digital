"""
Bitrix Component Mapper — Маппинг секций сайта на компоненты Битрикс.
Определяет какие bitrix:компоненты использовать для каждой секции.
Выход: component_map.json
"""
import json
import logging
from typing import Optional

logger = logging.getLogger(__name__)

# ── Маппинг секций → компоненты Битрикс ─────────────────────────
SECTION_COMPONENT_MAP = {
    "hero": {
        "component": None,
        "type": "static_html",
        "description": "Главный баннер — статический HTML в шаблоне",
    },
    "about": {
        "component": "bitrix:main.include",
        "type": "include_area",
        "description": "Включаемая область для текста 'О нас'",
        "params": {"AREA_FILE_SHOW": "file", "PATH": "/include/about.php"},
    },
    "services": {
        "component": "bitrix:news.list",
        "type": "iblock_list",
        "description": "Список услуг из инфоблока",
        "params": {"IBLOCK_TYPE": "services", "IBLOCK_ID": "auto", "NEWS_COUNT": "10"},
        "iblock": {"type": "services", "name": "Услуги", "fields": ["NAME", "PREVIEW_TEXT", "PREVIEW_PICTURE", "DETAIL_TEXT"]},
    },
    "advantages": {
        "component": "bitrix:news.list",
        "type": "iblock_list",
        "description": "Преимущества из инфоблока",
        "params": {"IBLOCK_TYPE": "content", "IBLOCK_ID": "auto", "NEWS_COUNT": "10"},
        "iblock": {"type": "content", "name": "Преимущества", "fields": ["NAME", "PREVIEW_TEXT", "PREVIEW_PICTURE"]},
    },
    "process": {
        "component": "bitrix:news.list",
        "type": "iblock_list",
        "description": "Этапы работы из инфоблока",
        "params": {"IBLOCK_TYPE": "content", "IBLOCK_ID": "auto", "NEWS_COUNT": "10", "SORT_BY1": "SORT"},
    },
    "pricing": {
        "component": "bitrix:news.list",
        "type": "iblock_list",
        "description": "Тарифы из инфоблока",
        "params": {"IBLOCK_TYPE": "content", "IBLOCK_ID": "auto"},
        "iblock": {"type": "content", "name": "Тарифы", "fields": ["NAME", "PREVIEW_TEXT", "PROPERTY_PRICE", "PROPERTY_FEATURES"]},
    },
    "reviews": {
        "component": "bitrix:news.list",
        "type": "iblock_list",
        "description": "Отзывы из инфоблока",
        "params": {"IBLOCK_TYPE": "content", "IBLOCK_ID": "auto"},
        "iblock": {"type": "content", "name": "Отзывы", "fields": ["NAME", "PREVIEW_TEXT", "PROPERTY_ROLE", "PREVIEW_PICTURE"]},
    },
    "team": {
        "component": "bitrix:news.list",
        "type": "iblock_list",
        "description": "Команда из инфоблока",
        "params": {"IBLOCK_TYPE": "content", "IBLOCK_ID": "auto"},
        "iblock": {"type": "content", "name": "Команда", "fields": ["NAME", "PREVIEW_TEXT", "PROPERTY_ROLE", "PREVIEW_PICTURE"]},
    },
    "gallery": {
        "component": "bitrix:photo.section",
        "type": "photo_gallery",
        "description": "Фотогалерея",
        "params": {"IBLOCK_TYPE": "content", "IBLOCK_ID": "auto"},
    },
    "faq": {
        "component": "bitrix:news.list",
        "type": "iblock_list",
        "description": "FAQ из инфоблока",
        "params": {"IBLOCK_TYPE": "content", "IBLOCK_ID": "auto"},
        "iblock": {"type": "content", "name": "FAQ", "fields": ["NAME", "PREVIEW_TEXT"]},
    },
    "contacts": {
        "component": "bitrix:main.include",
        "type": "include_area",
        "description": "Контактная информация — включаемая область",
        "params": {"AREA_FILE_SHOW": "file", "PATH": "/include/contacts.php"},
    },
    "form": {
        "component": "bitrix:form.result.new",
        "type": "web_form",
        "description": "Веб-форма обратной связи",
        "params": {"WEB_FORM_ID": "auto", "USE_EXTENDED_ERRORS": "Y"},
        "web_form": {"name": "Обратная связь", "fields": ["NAME", "PHONE", "EMAIL", "MESSAGE"]},
    },
    "cta": {
        "component": "bitrix:form.result.new",
        "type": "web_form",
        "description": "CTA с формой заявки",
        "params": {"WEB_FORM_ID": "auto"},
    },
    "blog": {
        "component": "bitrix:news.list",
        "type": "iblock_list",
        "description": "Блог / Новости",
        "params": {"IBLOCK_TYPE": "news", "IBLOCK_ID": "auto", "NEWS_COUNT": "6"},
    },
    "partners": {
        "component": "bitrix:news.list",
        "type": "iblock_list",
        "description": "Партнёры из инфоблока",
        "params": {"IBLOCK_TYPE": "content", "IBLOCK_ID": "auto"},
    },
    "map": {
        "component": None,
        "type": "static_html",
        "description": "Яндекс/Google карта — iframe в шаблоне",
    },
}


def map_components(blueprint: dict) -> dict:
    """
    Маппит секции blueprint на компоненты Битрикс.

    Args:
        blueprint: site_blueprint.json

    Returns:
        dict: component_map с инструкциями для каждой секции
    """
    sections = blueprint.get("sections", [])
    component_map = {
        "sections": [],
        "iblocks_needed": [],
        "web_forms_needed": [],
        "include_areas_needed": [],
        "static_sections": [],
    }

    for section in sections:
        sid = section["id"]
        mapping = SECTION_COMPONENT_MAP.get(sid, {
            "component": None,
            "type": "static_html",
            "description": f"Секция '{sid}' — статический HTML",
        })

        entry = {
            "section_id": sid,
            "h1": section.get("h1", ""),
            "component": mapping.get("component"),
            "type": mapping["type"],
            "description": mapping["description"],
            "params": mapping.get("params", {}),
        }
        component_map["sections"].append(entry)

        # Collect needed resources
        if mapping["type"] == "iblock_list" and "iblock" in mapping:
            iblock = mapping["iblock"].copy()
            iblock["section_id"] = sid
            component_map["iblocks_needed"].append(iblock)
        elif mapping["type"] == "web_form" and "web_form" in mapping:
            form = mapping["web_form"].copy()
            form["section_id"] = sid
            component_map["web_forms_needed"].append(form)
        elif mapping["type"] == "include_area":
            component_map["include_areas_needed"].append({
                "section_id": sid,
                "path": mapping.get("params", {}).get("PATH", f"/include/{sid}.php"),
            })
        elif mapping["type"] == "static_html":
            component_map["static_sections"].append(sid)

    logger.info(f"[ComponentMapper] Mapped {len(component_map['sections'])} sections: "
                f"{len(component_map['iblocks_needed'])} iblocks, "
                f"{len(component_map['web_forms_needed'])} forms, "
                f"{len(component_map['include_areas_needed'])} includes, "
                f"{len(component_map['static_sections'])} static")
    return component_map


def generate_component_php(section_id: str, mapping: dict) -> str:
    """Генерирует PHP код вызова компонента для секции."""
    component = mapping.get("component")
    if not component:
        return f"<!-- Section: {section_id} — static HTML -->"

    params = mapping.get("params", {})
    params_php = ",\n        ".join(f'"{k}" => "{v}"' for k, v in params.items())

    return f"""<?php $APPLICATION->IncludeComponent(
    "{component}",
    "",
    array(
        {params_php}
    )
); ?>"""


def save_map(component_map: dict, path: str = "component_map.json"):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(component_map, f, ensure_ascii=False, indent=2)
    return path
