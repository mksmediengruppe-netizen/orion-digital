"""
Bitrix Provisioner — Подготовка сервера для установки 1С-Битрикс.
Устанавливает Apache/Nginx, PHP, MySQL, создаёт БД, скачивает bitrixsetup.php.
Выход: provision_report.json
"""
import json
import logging
import time
from typing import Callable, Optional

logger = logging.getLogger(__name__)

REQUIRED_PHP_MODULES = [
    "mbstring", "curl", "gd", "xml", "zip", "opcache",
    "mysql", "json", "fileinfo", "openssl", "intl",
]

BITRIX_SETUP_URL = "https://www.1c-bitrix.ru/download/scripts/bitrixsetup.php"

PHP_INI_OVERRIDES = {
    "short_open_tag": "On",
    "mbstring.func_overload": "0",
    "max_input_vars": "10000",
    "memory_limit": "256M",
    "upload_max_filesize": "64M",
    "post_max_size": "64M",
    "max_execution_time": "300",
    "date.timezone": "Europe/Moscow",
    "opcache.revalidate_freq": "0",
}


def provision_server(
    ssh_fn: Callable,
    install_path: str = "/var/www/html",
    db_name: str = "bitrix_db",
    db_user: str = "bitrix_user",
    db_password: str = "",
    php_version: str = "8.1",
    web_server: str = "apache",
) -> dict:
    """
    Подготавливает сервер для установки Битрикс.

    Args:
        ssh_fn: SSH функция (cmd -> result)
        install_path: Путь установки
        db_name: Имя базы данных
        db_user: Пользователь БД
        db_password: Пароль БД
        php_version: Версия PHP
        web_server: apache или nginx

    Returns:
        dict: Отчёт о подготовке
    """
    report = {"status": "provisioning", "steps": [], "errors": [], "warnings": []}

    if not db_password:
        import secrets
        db_password = secrets.token_urlsafe(16)
        report["generated_db_password"] = db_password

    # 1. Update system
    _step(report, "update_system", "apt-get update -y && apt-get upgrade -y", ssh_fn)

    # 2. Install web server
    if web_server == "apache":
        _step(report, "install_apache",
              f"apt-get install -y apache2 libapache2-mod-php{php_version} && "
              "a2enmod rewrite && a2enmod headers", ssh_fn)
    else:
        _step(report, "install_nginx",
              f"apt-get install -y nginx php{php_version}-fpm", ssh_fn)

    # 3. Install PHP + modules
    modules_str = " ".join(f"php{php_version}-{m}" for m in REQUIRED_PHP_MODULES)
    _step(report, "install_php",
          f"apt-get install -y php{php_version} php{php_version}-cli {modules_str}", ssh_fn)

    # 4. Install MySQL
    _step(report, "install_mysql",
          "apt-get install -y mysql-server mysql-client", ssh_fn)
    _step(report, "start_mysql", "systemctl enable mysql && systemctl start mysql", ssh_fn)

    # 5. Create database
    sql = (
        f"CREATE DATABASE IF NOT EXISTS `{db_name}` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci; "
        f"CREATE USER IF NOT EXISTS '{db_user}'@'localhost' IDENTIFIED BY '{db_password}'; "
        f"GRANT ALL PRIVILEGES ON `{db_name}`.* TO '{db_user}'@'localhost'; "
        f"FLUSH PRIVILEGES;"
    )
    _step(report, "create_database", f'mysql -e "{sql}"', ssh_fn)

    # 6. Configure PHP
    ini_lines = "\n".join(f"{k} = {v}" for k, v in PHP_INI_OVERRIDES.items())
    _step(report, "configure_php",
          f"echo '{ini_lines}' > /etc/php/{php_version}/mods-available/bitrix.ini && "
          f"phpenmod bitrix", ssh_fn)

    # 7. Create install directory
    _step(report, "create_directory",
          f"mkdir -p {install_path} && chown -R www-data:www-data {install_path}", ssh_fn)

    # 8. Download bitrixsetup.php
    _step(report, "download_bitrixsetup",
          f"wget -q -O {install_path}/bitrixsetup.php {BITRIX_SETUP_URL} && "
          f"chown www-data:www-data {install_path}/bitrixsetup.php", ssh_fn)

    # 9. Configure web server for Bitrix
    if web_server == "apache":
        _step(report, "configure_apache", _apache_vhost(install_path), ssh_fn)
    else:
        _step(report, "configure_nginx", _nginx_vhost(install_path, php_version), ssh_fn)

    # 10. Restart services
    svc = "apache2" if web_server == "apache" else "nginx"
    _step(report, "restart_services",
          f"systemctl restart {svc} && systemctl restart php{php_version}-fpm 2>/dev/null; "
          f"systemctl restart mysql", ssh_fn)

    # 11. Verify
    _step(report, "verify_setup",
          f"test -f {install_path}/bitrixsetup.php && echo 'SETUP_OK' || echo 'SETUP_FAIL'",
          ssh_fn)

    errors = [s for s in report["steps"] if not s.get("success")]
    report["status"] = "ready" if len(errors) <= 1 else "failed"
    report["db_credentials"] = {"name": db_name, "user": db_user, "password": db_password}
    report["install_path"] = install_path
    report["web_server"] = web_server

    logger.info(f"[BitrixProvisioner] Provisioning {'complete' if report['status'] == 'ready' else 'failed'}: "
                f"{len(report['steps'])} steps, {len(errors)} errors")
    return report


def _step(report, name, cmd, ssh_fn):
    """Выполняет шаг и добавляет в отчёт."""
    try:
        result = str(ssh_fn(cmd))
        success = not any(e in result.lower() for e in ["error", "fatal", "failed"])
        report["steps"].append({"name": name, "success": success, "output": result[:300]})
    except Exception as e:
        report["steps"].append({"name": name, "success": False, "output": str(e)[:300]})
        report["errors"].append(f"{name}: {e}")


def _apache_vhost(install_path):
    conf = f"""cat > /etc/apache2/sites-available/bitrix.conf << 'VHOST'
<VirtualHost *:80>
    DocumentRoot {install_path}
    <Directory {install_path}>
        AllowOverride All
        Require all granted
    </Directory>
</VirtualHost>
VHOST
a2ensite bitrix.conf && a2dissite 000-default.conf 2>/dev/null"""
    return conf


def _nginx_vhost(install_path, php_version):
    conf = f"""cat > /etc/nginx/sites-available/bitrix << 'VHOST'
server {{
    listen 80 default_server;
    root {install_path};
    index index.php index.html;
    client_max_body_size 64m;
    location / {{ try_files $uri $uri/ /index.php?$args; }}
    location ~ \\.php$ {{
        include snippets/fastcgi-php.conf;
        fastcgi_pass unix:/var/run/php/php{php_version}-fpm.sock;
    }}
    location ~* \\.(jpg|jpeg|gif|png|svg|js|css|ico|woff2?)$ {{ expires 30d; }}
    location ~ /\\. {{ deny all; }}
}}
VHOST
ln -sf /etc/nginx/sites-available/bitrix /etc/nginx/sites-enabled/bitrix
rm -f /etc/nginx/sites-enabled/default 2>/dev/null"""
    return conf


def save_report(report: dict, path: str = "provision_report.json"):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    return path
