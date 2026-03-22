"""
Bitrix Publish Operator -- publish and finalize Bitrix site.
ULTIMATE PATCH Part I4.
"""

import logging
from typing import Dict

logger = logging.getLogger("bitrix_publish")


class BitrixPublishOperator:

    def __init__(self, ssh_executor=None):
        self._ssh = ssh_executor

    def publish(self, install_path: str, server: dict) -> dict:
        """
        Finalize Bitrix site:
        1. Clear Bitrix cache
        2. Check urlrewrite.php
        3. Remove bitrixsetup.php
        4. Check .htaccess
        5. Set correct permissions
        6. Final verification
        """
        result = {
            "success": False,
            "steps_completed": [],
            "issues": []
        }

        try:
            # 1. Clear cache
            cache_cmd = f"rm -rf {install_path}/bitrix/cache/* {install_path}/bitrix/managed_cache/* 2>/dev/null && echo CLEARED"
            cache_result = self._ssh.execute(cache_cmd, server)
            if cache_result and "CLEARED" in cache_result.get("output", ""):
                result["steps_completed"].append("cache_cleared")

            # 2. Check urlrewrite.php
            url_cmd = f"test -f {install_path}/urlrewrite.php && echo EXISTS"
            url_result = self._ssh.execute(url_cmd, server)
            if url_result and "EXISTS" in url_result.get("output", ""):
                result["steps_completed"].append("urlrewrite_ok")
            else:
                result["issues"].append("urlrewrite.php missing")

            # 3. Remove bitrixsetup.php (security)
            rm_cmd = f"rm -f {install_path}/bitrixsetup.php && echo REMOVED"
            rm_result = self._ssh.execute(rm_cmd, server)
            if rm_result and "REMOVED" in rm_result.get("output", ""):
                result["steps_completed"].append("setup_removed")

            # 4. Check .htaccess
            ht_cmd = f"test -f {install_path}/.htaccess && echo EXISTS"
            ht_result = self._ssh.execute(ht_cmd, server)
            if ht_result and "EXISTS" in ht_result.get("output", ""):
                result["steps_completed"].append("htaccess_ok")

            # 5. Set permissions
            perm_cmd = f"chown -R www-data:www-data {install_path} && chmod -R 755 {install_path} && chmod -R 777 {install_path}/bitrix/cache {install_path}/bitrix/managed_cache {install_path}/upload 2>/dev/null && echo PERMS_SET"
            perm_result = self._ssh.execute(perm_cmd, server)
            if perm_result and "PERMS_SET" in perm_result.get("output", ""):
                result["steps_completed"].append("permissions_set")

            # 6. Final check
            check_cmd = f"curl -sI http://localhost/ | head -1"
            check_result = self._ssh.execute(check_cmd, server)
            if check_result and "200" in check_result.get("output", ""):
                result["steps_completed"].append("site_accessible")

            result["success"] = len(result["steps_completed"]) >= 4

        except Exception as e:
            logger.error(f"Publish failed: {e}")
            result["issues"].append(str(e))

        return result
