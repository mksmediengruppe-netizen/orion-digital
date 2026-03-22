"""
Bitrix Reverse Engineer -- analyze existing Bitrix site.
ULTIMATE PATCH Part I4.
"""

import logging
from typing import Dict

logger = logging.getLogger("bitrix_reverse_engineer")


class BitrixReverseEngineer:

    def __init__(self, ssh_executor=None):
        self._ssh = ssh_executor

    def analyze(self, site_url: str, install_path: str, server: dict) -> dict:
        """Determine: version, template, components, modules."""
        result = {
            "version": None,
            "template": None,
            "components": [],
            "modules": [],
            "database": None,
            "issues": []
        }

        try:
            # Check Bitrix version
            ver_cmd = f"cat {install_path}/bitrix/modules/main/classes/general/version.php 2>/dev/null | grep SM_VERSION"
            ver_result = self._ssh.execute(ver_cmd, server)
            if ver_result and ver_result.get("output"):
                result["version"] = ver_result["output"].strip()

            # Check active template
            tpl_cmd = f"ls {install_path}/bitrix/templates/ 2>/dev/null"
            tpl_result = self._ssh.execute(tpl_cmd, server)
            if tpl_result and tpl_result.get("output"):
                templates = [t.strip() for t in tpl_result["output"].split() if t.strip() and t.strip() != '.default']
                result["template"] = templates[0] if templates else None

            # Check installed modules
            mod_cmd = f"ls {install_path}/bitrix/modules/ 2>/dev/null | head -20"
            mod_result = self._ssh.execute(mod_cmd, server)
            if mod_result and mod_result.get("output"):
                result["modules"] = [m.strip() for m in mod_result["output"].split() if m.strip()]

            # Check components in use
            comp_cmd = f"grep -r 'IncludeComponent' {install_path}/bitrix/templates/*/header.php {install_path}/bitrix/templates/*/footer.php 2>/dev/null | head -10"
            comp_result = self._ssh.execute(comp_cmd, server)
            if comp_result and comp_result.get("output"):
                result["components"] = comp_result["output"].strip().split("\n")

        except Exception as e:
            logger.error(f"Reverse engineer failed: {e}")
            result["issues"].append(str(e))

        return result
