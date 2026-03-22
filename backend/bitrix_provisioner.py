"""
Bitrix Provisioner - server preparation for 1C-Bitrix installation.
ULTIMATE PATCH Part D1.
"""

import logging
import time
from typing import Dict, Optional

logger = logging.getLogger("bitrix_provisioner")

REQUIRED_PHP_MODULES = [
    "mbstring", "curl", "gd", "xml", "json", 
    "opcache", "zip", "fileinfo", "openssl", "mysqli"
]

BITRIX_SETUP_URL = "https://www.1c-bitrix.ru/download/scripts/bitrixsetup.php"


class BitrixProvisioner:
    
    def __init__(self, ssh_executor):
        self._ssh = ssh_executor
    
    def prepare_server(self, config: dict) -> dict:
        """Full server preparation."""
        results = {
            "os": None,
            "php": None,
            "mysql": None,
            "web_server": None,
            "db_created": False,
            "installer_deployed": False,
            "install_url": None,
            "ready": False,
            "errors": [],
            "warnings": []
        }
        
        server = config.get("server")
        path = config.get("install_path", "/var/www/html/bitrix")
        
        # 1. Detect OS
        os_result = self._ssh.execute("cat /etc/os-release | head -2", server)
        results["os"] = os_result.get("output", "unknown")
        
        # 2. Check PHP
        php_result = self._ssh.execute("php -v 2>/dev/null | head -1", server)
        results["php"] = php_result.get("output", "not installed")
        
        if "not installed" in str(results["php"]) or not php_result.get("success"):
            results["errors"].append("PHP not installed")
            self._install_php(server, config.get("php_version", "8.2"))
        
        # 3. Check PHP modules
        missing = self._check_php_modules(server)
        if missing:
            self._install_php_modules(server, missing, config.get("php_version", "8.2"))
            results["warnings"].append(f"Installed missing PHP modules: {missing}")
        
        # 4. Check MySQL
        mysql_result = self._ssh.execute("mysql --version 2>/dev/null", server)
        results["mysql"] = mysql_result.get("output", "not installed")
        
        if not mysql_result.get("success"):
            results["errors"].append("MySQL not installed")
            return results
        
        # 5. Create DB
        db_ok = self._setup_database(server, config)
        results["db_created"] = db_ok
        
        # 6. Create directory
        self._ssh.execute(f"mkdir -p {path}", server)
        self._ssh.execute(f"chown -R www-data:www-data {path}", server)
        
        # 7. Download installer
        installer_ok = self._deploy_installer(server, path)
        results["installer_deployed"] = installer_ok
        
        # 8. Setup nginx
        self._setup_nginx(server, path, config)
        
        # 9. Check URL
        site_url = config.get("site_url", f"http://{server.get('host')}")
        install_url = f"{site_url}/bitrixsetup.php"
        results["install_url"] = install_url
        
        check = self._ssh.execute(f"curl -sI {install_url} | head -1", server)
        if "200" in str(check.get("output", "")):
            results["ready"] = True
        else:
            results["errors"].append(f"Installer not accessible: {install_url}")
        
        return results
    
    def _check_php_modules(self, server) -> list:
        result = self._ssh.execute("php -m 2>/dev/null", server)
        installed = result.get("output", "").lower().split()
        missing = [m for m in REQUIRED_PHP_MODULES if m.lower() not in installed]
        return missing
    
    def _install_php(self, server, version="8.2"):
        self._ssh.execute(
            f"apt update && apt install -y php{version}-fpm php{version}-cli",
            server
        )
    
    def _install_php_modules(self, server, modules, version="8.2"):
        pkgs = " ".join([f"php{version}-{m}" for m in modules])
        self._ssh.execute(f"apt install -y {pkgs}", server)
        self._ssh.execute(f"systemctl restart php{version}-fpm", server)
    
    def _setup_database(self, server, config) -> bool:
        db_name = config.get("db_name", "bitrix_db")
        db_user = config.get("db_user", "bitrix_user")
        db_pass = config.get("db_password", "BitrixPass2026!")
        
        commands = [
            f'mysql -e "CREATE DATABASE IF NOT EXISTS {db_name} CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"',
            f"mysql -e \"CREATE USER IF NOT EXISTS '{db_user}'@'localhost' IDENTIFIED BY '{db_pass}'\"",
            f"mysql -e \"GRANT ALL ON {db_name}.* TO '{db_user}'@'localhost'\"",
            f'mysql -e "FLUSH PRIVILEGES"'
        ]
        
        for cmd in commands:
            result = self._ssh.execute(cmd, server)
            if not result.get("success"):
                logger.error(f"DB setup failed: {cmd}")
                return False
        return True
    
    def _deploy_installer(self, server, path) -> bool:
        result = self._ssh.execute(
            f"wget -q {BITRIX_SETUP_URL} -O {path}/bitrixsetup.php",
            server
        )
        
        size_result = self._ssh.execute(
            f"stat -c%s {path}/bitrixsetup.php 2>/dev/null || echo 0",
            server
        )
        size = int(size_result.get("output", "0").strip())
        
        if size < 10000:
            logger.error(f"bitrixsetup.php too small: {size} bytes")
            return False
        
        self._ssh.execute(f"chown www-data:www-data {path}/bitrixsetup.php", server)
        return True
    
    def _setup_nginx(self, server, path, config):
        php_version = config.get("php_version", "8.2")
        site_name = path.rstrip("/").split("/")[-1]
        
        nginx_conf = f"""
location /{site_name}/ {{
    alias {path}/;
    index index.php index.html;
    
    location ~ \\.php$ {{
        fastcgi_pass unix:/run/php/php{php_version}-fpm.sock;
        fastcgi_param SCRIPT_FILENAME $request_filename;
        include fastcgi_params;
        fastcgi_read_timeout 300;
    }}
}}
"""
        self._ssh.execute(
            f"cat > /etc/nginx/conf.d/{site_name}.conf << 'NGINX_EOF'\n{nginx_conf}\nNGINX_EOF",
            server
        )
        self._ssh.execute("nginx -t && systemctl reload nginx", server)
