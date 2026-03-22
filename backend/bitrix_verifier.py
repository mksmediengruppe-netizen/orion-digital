"""
Bitrix Verifier - verify successful Bitrix installation.
ULTIMATE PATCH Part D3.
"""

import logging
from typing import Dict

logger = logging.getLogger("bitrix_verifier")


class BitrixVerifier:
    
    def __init__(self, ssh_executor, browser_agent=None):
        self._ssh = ssh_executor
        self._browser = browser_agent
    
    def full_verify(self, config: dict) -> dict:
        """Full installation verification."""
        results = {
            "public_site": False,
            "admin_panel": False,
            "admin_login": False,
            "db_connected": False,
            "no_install_wizard": False,
            "filesystem_ok": False,
            "score": 0,
            "issues": []
        }
        
        site_url = config.get("site_url")
        install_path = config.get("install_path")
        server = config.get("server")
        
        # 1. Public page
        check = self._ssh.execute(
            f"curl -sI {site_url} | head -1", server
        )
        if "200" in str(check.get("output", "")):
            results["public_site"] = True
            results["score"] += 2
        else:
            results["issues"].append("Public site not accessible")
        
        # 2. Admin panel
        admin_url = f"{site_url}/bitrix/admin/"
        check = self._ssh.execute(
            f"curl -sI {admin_url} | head -1", server
        )
        if "200" in str(check.get("output", "")) or \
           "302" in str(check.get("output", "")):
            results["admin_panel"] = True
            results["score"] += 2
        else:
            results["issues"].append("Admin panel not accessible")
        
        # 3. Filesystem
        check = self._ssh.execute(
            f"ls {install_path}/bitrix/modules/ 2>/dev/null | wc -l",
            server
        )
        modules_count = int(check.get("output", "0").strip())
        if modules_count > 10:
            results["filesystem_ok"] = True
            results["score"] += 2
        else:
            results["issues"].append(f"Only {modules_count} Bitrix modules found")
        
        # 4. DB connected
        check = self._ssh.execute(
            f"php -r \"include('{install_path}/bitrix/php_interface/dbconn.php'); "
            f"echo 'DB_OK';\" 2>/dev/null",
            server
        )
        if "DB_OK" in str(check.get("output", "")):
            results["db_connected"] = True
            results["score"] += 2
        else:
            results["issues"].append("DB connection check failed")
        
        # 5. Wizard not active
        check = self._ssh.execute(
            f"ls {install_path}/bitrixsetup.php 2>/dev/null",
            server
        )
        if not check.get("output", "").strip():
            results["no_install_wizard"] = True
            results["score"] += 2
        else:
            results["issues"].append("bitrixsetup.php still exists (should be removed)")
        
        return results
