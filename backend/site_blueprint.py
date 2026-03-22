"""
Site Blueprint -- structure of a website from brief.
Created BEFORE coding. All agents work from the blueprint.
ULTIMATE PATCH Part H1.
"""

import json
import logging
from typing import Dict, Optional

logger = logging.getLogger("site_blueprint")


class SiteBlueprint:

    def __init__(self, llm_client=None):
        self._llm = llm_client

    def create_from_brief(self, brief_text: str, mode: str = "standard") -> dict:
        """Parse brief into a structured blueprint."""
        if self._llm:
            return self._create_via_llm(brief_text, mode)
        return self._create_fallback(brief_text)

    def _create_via_llm(self, brief_text: str, mode: str) -> dict:
        """Use LLM to create blueprint from brief."""
        system_prompt = """You are a web architect. Analyze the brief and return a JSON blueprint.
The blueprint MUST contain:
- site_name: short identifier
- site_type: landing|corporate|shop
- design: {style, primary_color, accent_color, font, background}
- sections: [{id, title, content, photo_prompt, has_cta, cta_text}]
- photos_needed: [{section, prompt, style}]
- forms: [{section, fields, action, email}]
- technical: {framework, animations, responsive, php_handler}
- deploy: {server, path, nginx}
Return ONLY valid JSON, no markdown."""

        try:
            response = self._llm.chat(
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": brief_text}
                ],
                model="gpt54_mini" if mode == "fast" else "gpt54"
            )
            return json.loads(response)
        except Exception as e:
            logger.error(f"LLM blueprint failed: {e}")
            return self._create_fallback(brief_text)

    def _create_fallback(self, brief_text: str) -> dict:
        """Fallback blueprint from text analysis."""
        brief_lower = brief_text.lower()

        # Detect site type
        site_type = "landing"
        if any(w in brief_lower for w in ["shop", "store", "ecommerce"]):
            site_type = "shop"
        elif any(w in brief_lower for w in ["corporate", "company"]):
            site_type = "corporate"

        # Default sections for landing
        sections = [
            {"id": "hero", "title": "Hero", "content": "", "photo_prompt": "professional hero image", "has_cta": True, "cta_text": "Get Started"},
            {"id": "advantages", "title": "Advantages", "content": "", "photo_prompt": None, "has_cta": False, "cta_text": None},
            {"id": "services", "title": "Services", "content": "", "photo_prompt": "service illustration", "has_cta": False, "cta_text": None},
            {"id": "portfolio", "title": "Portfolio", "content": "", "photo_prompt": "portfolio showcase", "has_cta": False, "cta_text": None},
            {"id": "reviews", "title": "Reviews", "content": "", "photo_prompt": "customer portrait", "has_cta": False, "cta_text": None},
            {"id": "faq", "title": "FAQ", "content": "", "photo_prompt": None, "has_cta": False, "cta_text": None},
            {"id": "contacts", "title": "Contacts", "content": "", "photo_prompt": None, "has_cta": True, "cta_text": "Send"},
        ]

        photos = [
            {"section": s["id"], "prompt": s["photo_prompt"], "style": "professional"}
            for s in sections if s["photo_prompt"]
        ]

        return {
            "site_name": "site",
            "site_type": site_type,
            "design": {
                "style": "modern",
                "primary_color": "#4361ee",
                "accent_color": "#7209b7",
                "font": "Montserrat",
                "background": "light"
            },
            "sections": sections,
            "photos_needed": photos,
            "forms": [
                {"section": "contacts", "fields": ["name", "phone", "email", "message"],
                 "action": "send.php", "email": "admin@example.com"}
            ],
            "technical": {
                "framework": "tailwind",
                "animations": "aos",
                "responsive": True,
                "php_handler": True
            },
            "deploy": {
                "server": "",
                "path": "/var/www/html/site/",
                "nginx": True
            }
        }

    def validate(self, blueprint: dict) -> dict:
        """Validate blueprint completeness."""
        issues = []
        if not blueprint.get("sections"):
            issues.append("No sections defined")
        if not blueprint.get("photos_needed"):
            issues.append("No photos defined")
        if not blueprint.get("forms"):
            issues.append("No forms defined")
        if not blueprint.get("design"):
            issues.append("No design defined")
        if not blueprint.get("deploy"):
            issues.append("No deploy config")

        for s in blueprint.get("sections", []):
            if not s.get("id"):
                issues.append(f"Section missing id: {s}")

        return {
            "valid": len(issues) == 0,
            "issues": issues,
            "sections_count": len(blueprint.get("sections", [])),
            "photos_count": len(blueprint.get("photos_needed", [])),
            "forms_count": len(blueprint.get("forms", []))
        }
