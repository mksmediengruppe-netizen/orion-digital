"""
Bitrix Wizard Operator - automated wizard installation via browser.
ULTIMATE PATCH Part D2.
"""

import logging
import time
from typing import Dict, Optional

logger = logging.getLogger("bitrix_wizard")

WIZARD_STEPS = [
    "open_installer",
    "accept_license", 
    "environment_check",
    "database_settings",
    "admin_settings",
    "install_package",
    "finish"
]


class BitrixWizardOperator:
    
    def __init__(self, browser_agent, snapshot_store=None):
        self._browser = browser_agent
        self._snapshots = snapshot_store
        self._current_step = 0
    
    def run_installation(self, install_url: str, config: dict) -> dict:
        """Full wizard walkthrough."""
        result = {
            "success": False,
            "steps_completed": [],
            "steps_failed": [],
            "current_step": None,
            "error": None
        }
        
        for step_name in WIZARD_STEPS:
            self._current_step = step_name
            result["current_step"] = step_name
            
            logger.info(f"Bitrix wizard step: {step_name}")
            
            step_ok = False
            for retry in range(3):
                try:
                    step_result = self._execute_step(
                        step_name, install_url, config
                    )
                    if step_result.get("success"):
                        step_ok = True
                        result["steps_completed"].append(step_name)
                        
                        if self._snapshots:
                            self._capture_snapshot(step_name, step_result)
                        break
                    else:
                        logger.warning(
                            f"Step {step_name} failed (retry {retry+1}/3): "
                            f"{step_result.get('error')}"
                        )
                        time.sleep(5)
                except Exception as e:
                    logger.error(f"Step {step_name} exception: {e}")
                    time.sleep(5)
            
            if not step_ok:
                result["steps_failed"].append(step_name)
                result["error"] = f"Step {step_name} failed after 3 retries"
                return result
        
        result["success"] = True
        return result
    
    def _execute_step(self, step_name, url, config) -> dict:
        """Execute one wizard step."""
        
        if step_name == "open_installer":
            page = self._browser.navigate(url, timeout=300000,
                                          wait_until="domcontentloaded")
            return {"success": page is not None}
        
        elif step_name == "accept_license":
            self._browser.click('input[type="checkbox"]')
            time.sleep(1)
            self._browser.click('input[type="submit"], button[type="submit"], .inst-btn')
            time.sleep(3)
            return {"success": True}
        
        elif step_name == "environment_check":
            time.sleep(10)
            self._browser.click('input[type="submit"], .inst-btn, [value="Next"]')
            time.sleep(3)
            return {"success": True}
        
        elif step_name == "database_settings":
            db = config.get("db", {})
            self._browser.fill('[name="db_host"], #db_host', 
                             db.get("host", "localhost"))
            self._browser.fill('[name="db_name"], #db_name',
                             db.get("name", "bitrix_db"))
            self._browser.fill('[name="db_login"], #db_login',
                             db.get("user", "bitrix_user"))
            self._browser.fill('[name="db_password"], #db_password',
                             db.get("password", ""))
            
            self._browser.click('input[type="submit"], .inst-btn')
            time.sleep(5)
            return {"success": True}
        
        elif step_name == "admin_settings":
            admin = config.get("admin", {})
            self._browser.fill('[name="admin_login"], #admin_login',
                             admin.get("login", "admin"))
            self._browser.fill('[name="admin_email"], #admin_email',
                             admin.get("email", "admin@example.com"))
            self._browser.fill('[name="admin_password"], #admin_password',
                             admin.get("password", ""))
            self._browser.fill('[name="admin_password_confirm"]',
                             admin.get("password", ""))
            
            self._browser.click('input[type="submit"], .inst-btn')
            time.sleep(5)
            return {"success": True}
        
        elif step_name == "install_package":
            for _ in range(60):
                time.sleep(10)
                page_text = self._browser.get_text()
                if any(w in page_text.lower() for w in ["completed", "finish"]):
                    return {"success": True}
                if any(w in page_text.lower() for w in ["error"]):
                    return {"success": False, "error": "Install error detected"}
            
            return {"success": False, "error": "Install timeout (10 min)"}
        
        elif step_name == "finish":
            self._browser.click('input[type="submit"], .inst-btn, a.inst-btn')
            time.sleep(3)
            return {"success": True}
        
        return {"success": False, "error": f"Unknown step: {step_name}"}
    
    def _capture_snapshot(self, step_name, step_result):
        screenshot = self._browser.screenshot()
        self._snapshots.create(
            task_id="bitrix_install",
            step_id=step_name,
            snapshot_type="wizard_step",
            completed_actions=[{
                "step": step_name,
                "success": step_result.get("success"),
                "screenshot": screenshot
            }]
        )
    
    def detect_current_step(self) -> dict:
        page_text = self._browser.get_text()
        
        keywords = {
            "accept_license": ["license", "agreement"],
            "database_settings": ["database", "db_host"],
            "admin_settings": ["admin", "administrator"],
            "install_package": ["download", "install"],
            "finish": ["completed", "finish"]
        }
        
        for step, words in keywords.items():
            if any(w in page_text.lower() for w in words):
                return {"step": step}
        
        return {"step": "unknown", "page_text": page_text[:200]}
