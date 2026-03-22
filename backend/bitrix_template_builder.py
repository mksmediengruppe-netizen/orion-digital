"""
Bitrix Template Builder -- build Bitrix template from HTML.
ULTIMATE PATCH Part I4.
"""

import logging
from typing import Dict

logger = logging.getLogger("bitrix_template_builder")


class BitrixTemplateBuilder:

    def __init__(self, ssh_executor=None):
        self._ssh = ssh_executor

    def build(self, html_path: str, install_path: str, server: dict) -> dict:
        """
        Split HTML into Bitrix template structure:
        - header.php (head + opening body + header)
        - footer.php (footer + closing body)
        - template_styles.css
        - .description.php (template metadata)
        - Register template in Bitrix
        """
        result = {
            "success": False,
            "template_name": None,
            "files_created": [],
            "issues": []
        }

        try:
            template_name = "custom_landing"
            tpl_path = f"{install_path}/bitrix/templates/{template_name}"

            # Create template directory
            self._ssh.execute(f"mkdir -p {tpl_path}", server)

            # Read source HTML
            read_result = self._ssh.execute(f"cat {html_path}", server)
            if not read_result or not read_result.get("output"):
                result["issues"].append("Cannot read source HTML")
                return result

            html = read_result["output"]

            # Split HTML into header and footer
            body_split = html.split("</header>") if "</header>" in html else html.split("<main")
            if len(body_split) >= 2:
                header_html = body_split[0] + ("</header>" if "</header>" in html else "")
                rest = body_split[1] if "</header>" in html else "<main" + body_split[1]
            else:
                # Simple split at body
                header_html = html[:html.find("</body>")] if "</body>" in html else html[:len(html)//2]
                rest = html[html.find("</body>"):] if "</body>" in html else html[len(html)//2:]

            footer_split = rest.split("<footer") if "<footer" in rest else [rest[:len(rest)//2], rest[len(rest)//2:]]
            main_content = footer_split[0]
            footer_html = ("<footer" + footer_split[1]) if len(footer_split) > 1 and "<footer" in rest else footer_split[-1]

            # Create header.php
            header_php = '<?php if(!defined("B_PROLOG_INCLUDED") || B_PROLOG_INCLUDED !== true) die();?>\n'
            header_php += header_html
            header_php += '\n<?php $APPLICATION->ShowHead();?>\n'
            self._ssh.execute(f"cat > {tpl_path}/header.php << 'HEOF'\n{header_php}\nHEOF", server)
            result["files_created"].append("header.php")

            # Create footer.php
            footer_php = footer_html + '\n</body>\n</html>'
            self._ssh.execute(f"cat > {tpl_path}/footer.php << 'FEOF'\n{footer_php}\nFEOF", server)
            result["files_created"].append("footer.php")

            # Create .description.php
            desc_php = """<?php
if(!defined("B_PROLOG_INCLUDED") || B_PROLOG_INCLUDED !== true) die();
$arTemplate = array(
    "NAME" => "Custom Landing",
    "DESCRIPTION" => "Auto-generated landing page template",
    "SORT" => 100,
    "TYPE" => "D"
);
?>"""
            self._ssh.execute(f"cat > {tpl_path}/.description.php << 'DEOF'\n{desc_php}\nDEOF", server)
            result["files_created"].append(".description.php")

            # Extract and create template_styles.css
            import re
            style_match = re.findall(r'<style[^>]*>(.*?)</style>', html, re.DOTALL)
            if style_match:
                css = '\n'.join(style_match)
                self._ssh.execute(f"cat > {tpl_path}/template_styles.css << 'CSSEOF'\n{css}\nCSSEOF", server)
                result["files_created"].append("template_styles.css")

            # Set permissions
            self._ssh.execute(f"chown -R www-data:www-data {tpl_path}", server)

            result["success"] = True
            result["template_name"] = template_name

        except Exception as e:
            logger.error(f"Template build failed: {e}")
            result["issues"].append(str(e))

        return result
