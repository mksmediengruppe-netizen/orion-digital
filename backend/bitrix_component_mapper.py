"""
Bitrix Component Mapper -- map HTML sections to Bitrix components.
ULTIMATE PATCH Part I4.
"""

import logging
from typing import Dict, List

logger = logging.getLogger("bitrix_component_mapper")


class BitrixComponentMapper:

    # Mapping of section types to Bitrix components
    COMPONENT_MAP = {
        "form": "bitrix:form.result.new",
        "slider": "bitrix:catalog.section",
        "faq": "bitrix:iblock.element.list",
        "map": "bitrix:map.yandex.view",
        "news": "bitrix:news.list",
        "catalog": "bitrix:catalog.section",
        "gallery": "bitrix:photo.section",
        "search": "bitrix:search.page",
        "menu": "bitrix:menu",
        "breadcrumb": "bitrix:breadcrumb",
    }

    def __init__(self, ssh_executor=None):
        self._ssh = ssh_executor

    def map(self, blueprint: dict, install_path: str, server: dict) -> dict:
        """
        Map HTML sections to Bitrix components:
        Forms -> bitrix:form.result.new
        Sliders -> bitrix:catalog.section
        FAQ -> custom component
        Map -> Yandex Maps integration
        """
        result = {
            "success": False,
            "mappings": [],
            "components_installed": [],
            "issues": []
        }

        try:
            sections = blueprint.get("sections", [])
            for section in sections:
                sid = section.get("id", "")
                section_type = self._detect_section_type(section)
                component = self.COMPONENT_MAP.get(section_type)

                mapping = {
                    "section_id": sid,
                    "section_type": section_type,
                    "component": component,
                    "installed": False
                }

                if component:
                    # Check if component exists
                    check = self._ssh.execute(
                        f"ls {install_path}/bitrix/components/{component.replace(':', '/')}/ 2>/dev/null && echo EXISTS",
                        server
                    )
                    if check and "EXISTS" in check.get("output", ""):
                        mapping["installed"] = True
                        result["components_installed"].append(component)

                result["mappings"].append(mapping)

            result["success"] = True

        except Exception as e:
            logger.error(f"Component mapping failed: {e}")
            result["issues"].append(str(e))

        return result

    def _detect_section_type(self, section: dict) -> str:
        """Detect section type from blueprint section data."""
        sid = section.get("id", "").lower()
        title = section.get("title", "").lower()

        if any(w in sid for w in ["form", "contact", "callback"]):
            return "form"
        if any(w in sid for w in ["faq", "question"]):
            return "faq"
        if any(w in sid for w in ["slider", "carousel", "hero"]):
            return "slider"
        if any(w in sid for w in ["map", "location"]):
            return "map"
        if any(w in sid for w in ["news", "blog"]):
            return "news"
        if any(w in sid for w in ["gallery", "portfolio"]):
            return "gallery"
        if any(w in sid for w in ["catalog", "products"]):
            return "catalog"

        return "static"
