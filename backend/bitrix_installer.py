"""
Bitrix Installer - main entry point for autonomous Bitrix installation.
Delegates to bitrix_provisioner and bitrix_wizard_operator.
ULTIMATE PATCH Part D.
"""
import logging
from bitrix_provisioner import BitrixProvisioner
from bitrix_wizard_operator import BitrixWizardOperator

logger = logging.getLogger("bitrix_installer")


class BitrixInstaller:
    def __init__(self, ssh_executor=None):
        self.provisioner = BitrixProvisioner(ssh_executor)
        self.wizard = BitrixWizardOperator(ssh_executor)
        self._ssh = ssh_executor

    def install(self, server: dict, install_path: str, db_config: dict = None) -> dict:
        """Full autonomous Bitrix installation."""
        result = {"success": False, "steps": [], "issues": []}
        try:
            # Step 1: Provision server
            prov = self.provisioner.provision(server, install_path)
            result["steps"].append({"provision": prov})
            if not prov.get("success"):
                result["issues"].append("Provisioning failed")
                return result

            # Step 2: Run wizard
            wiz = self.wizard.run_wizard(server, install_path, db_config or {})
            result["steps"].append({"wizard": wiz})
            if not wiz.get("success"):
                result["issues"].append("Wizard failed")
                return result

            result["success"] = True
        except Exception as e:
            logger.error(f"Install failed: {e}")
            result["issues"].append(str(e))
        return result
