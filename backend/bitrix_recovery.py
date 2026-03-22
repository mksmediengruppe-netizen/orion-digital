"""
Bitrix Recovery - recover from failed Bitrix installation.
ULTIMATE PATCH Part D4.
"""

import logging
from typing import Dict

logger = logging.getLogger("bitrix_recovery")


class BitrixRecovery:
    
    def __init__(self, ssh_executor, wizard_operator, snapshot_store=None):
        self._ssh = ssh_executor
        self._wizard = wizard_operator
        self._snapshots = snapshot_store
    
    def detect_install_state(self, config: dict) -> dict:
        """Detect current installation state."""
        server = config.get("server")
        path = config.get("install_path")
        
        state = {
            "installer_exists": False,
            "bitrix_files_exist": False,
            "db_configured": False,
            "admin_accessible": False,
            "wizard_step": "unknown",
            "recommendation": "full_install"
        }
        
        # Check installer
        check = self._ssh.execute(
            f"ls {path}/bitrixsetup.php 2>/dev/null && echo EXISTS",
            server
        )
        state["installer_exists"] = "EXISTS" in str(check.get("output", ""))
        
        # Check Bitrix files
        check = self._ssh.execute(
            f"ls {path}/bitrix/modules/ 2>/dev/null | wc -l",
            server
        )
        modules = int(check.get("output", "0").strip())
        state["bitrix_files_exist"] = modules > 0
        
        # Check dbconn.php
        check = self._ssh.execute(
            f"ls {path}/bitrix/php_interface/dbconn.php 2>/dev/null && echo EXISTS",
            server
        )
        state["db_configured"] = "EXISTS" in str(check.get("output", ""))
        
        # Determine recommendation
        if state["admin_accessible"]:
            state["recommendation"] = "already_installed"
        elif state["db_configured"] and state["bitrix_files_exist"]:
            state["recommendation"] = "resume_wizard"
        elif state["installer_exists"]:
            state["recommendation"] = "run_wizard"
        else:
            state["recommendation"] = "full_install"
        
        return state
    
    def recover(self, config: dict) -> dict:
        """Recover installation."""
        state = self.detect_install_state(config)
        
        if state["recommendation"] == "already_installed":
            return {"action": "skip", "reason": "Already installed"}
        
        if state["recommendation"] == "resume_wizard":
            step = self._wizard.detect_current_step()
            return {
                "action": "resume_wizard",
                "from_step": step.get("step"),
                "state": state
            }
        
        return {"action": "full_install", "state": state}
