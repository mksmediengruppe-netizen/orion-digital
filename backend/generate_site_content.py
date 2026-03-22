"""
Site Content Generator -- generates all text content for a website.
Separate from HTML generation for clean architecture.
ULTIMATE PATCH Part I2.
"""

import json
import logging
from typing import Dict

logger = logging.getLogger("site_content")


class SiteContentGenerator:

    def __init__(self, llm_client=None):
        self._llm = llm_client

    def generate(self, blueprint: dict) -> dict:
        """Generate ALL text content for the site based on blueprint."""
        if self._llm:
            return self._generate_via_llm(blueprint)
        return self._generate_fallback(blueprint)

    def _generate_via_llm(self, blueprint: dict) -> dict:
        """Use LLM to generate all site content."""
        system_prompt = """You are a professional copywriter for websites.
Generate ALL text content for a website based on the blueprint.
Return JSON with:
- sections: {section_id: {h1, subtitle, text, cta, items[]}}
- meta: {title, description, keywords}
- privacy: full privacy policy text in Russian
- faq: [{question, answer}]
- reviews: [{name, role, text, rating}]
All content must be in Russian, professional, persuasive.
Return ONLY valid JSON."""

        try:
            response = self._llm.chat(
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": json.dumps(blueprint, ensure_ascii=False)}
                ],
                model="gpt54_mini"
            )
            return json.loads(response)
        except Exception as e:
            logger.error(f"LLM content generation failed: {e}")
            return self._generate_fallback(blueprint)

    def _generate_fallback(self, blueprint: dict) -> dict:
        """Fallback content generation from blueprint."""
        sections = {}
        for section in blueprint.get("sections", []):
            sid = section.get("id", "unknown")
            sections[sid] = {
                "h1": section.get("title", "Section"),
                "subtitle": section.get("content", ""),
                "text": "",
                "cta": section.get("cta_text", ""),
                "items": []
            }

        return {
            "sections": sections,
            "meta": {
                "title": blueprint.get("site_name", "Site"),
                "description": f"Website {blueprint.get('site_name', '')}",
                "keywords": ""
            },
            "privacy": "Standard privacy policy.",
            "faq": [],
            "reviews": []
        }

    def validate_content(self, content: dict) -> dict:
        """Validate generated content completeness."""
        issues = []
        if not content.get("sections"):
            issues.append("No sections content")
        if not content.get("meta", {}).get("title"):
            issues.append("Missing meta title")
        if not content.get("meta", {}).get("description"):
            issues.append("Missing meta description")
        if not content.get("privacy"):
            issues.append("Missing privacy policy")

        return {
            "valid": len(issues) == 0,
            "issues": issues,
            "sections_count": len(content.get("sections", {}))
        }
