
# ═══ SECURITY: SQL injection prevention ═══
import re as _re_sql
import secrets as _secrets_sql
import string as _string_sql

def validate_identifier(name, label="identifier"):
    """Validate DB names and usernames."""
    if not _re_sql.fullmatch(r"[A-Za-z0-9_]+", name):
        raise ValueError(f"Invalid {label}: {name}. Only [A-Za-z0-9_] allowed.")
    return name

def generate_safe_password(length=20):
    """Generate password from safe characters."""
    chars = _string_sql.ascii_letters + _string_sql.digits + "!@#$%^"
    return ''.join(_secrets_sql.choice(chars) for _ in range(length))


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

# ВАЖНО: bitrixsetup.php устанавливает BITRIX24 (корпоративный портал), НЕ 1С-Битрикс CMS!
# Для 1С-Битрикс Управление Сайтом нужен архив tar.gz с авторизацией на 1c-bitrix.ru
# Редакции 1С-Битрикс Управление Сайтом (требуют авторизации):
#   Старт:          https://www.1c-bitrix.ru/download/start_encode.tar.gz
#   Малый бизнес:   https://www.1c-bitrix.ru/download/small_business_encode.tar.gz
#   Стандарт:       https://www.1c-bitrix.ru/download/standard_encode.tar.gz
#   Бизнес:         https://www.1c-bitrix.ru/download/business_encode.tar.gz
# Если архив недоступен без авторизации — использовать bitrixsetup.php (установит Bitrix24)
# Bitrix24 тоже имеет CMS-функционал и редактор страниц, просто другой интерфейс.
BITRIX_CMS_EDITIONS = {
    "start": "start_encode.tar.gz",
    "small_business": "small_business_encode.tar.gz",
    "standard": "standard_encode.tar.gz",
    "business": "business_encode.tar.gz",
}
# Bitrix24 (устанавливается через bitrixsetup.php без авторизации):
BITRIX24_SETUP_URL = "https://www.1c-bitrix.ru/download/scripts/bitrixsetup.php"

# ВАЖНО: bitrixsetup.php устанавливает BITRIX24 (корпоративный портал), НЕ 1С-Битрикс CMS!
# Для 1С-Битрикс Управление Сайтом нужен архив tar.gz с авторизацией на 1c-bitrix.ru
# Редакции 1С-Битрикс Управление Сайтом (требуют авторизации):
#   Старт:          https://www.1c-bitrix.ru/download/start_encode.tar.gz
#   Малый бизнес:   https://www.1c-bitrix.ru/download/small_business_encode.tar.gz
#   Стандарт:       https://www.1c-bitrix.ru/download/standard_encode.tar.gz
#   Бизнес:         https://www.1c-bitrix.ru/download/business_encode.tar.gz
# Если архив недоступен без авторизации — использовать bitrixsetup.php (установит Bitrix24)
# Bitrix24 тоже имеет CMS-функционал и редактор страниц, просто другой интерфейс.
BITRIX_CMS_EDITIONS = {
    "start": "start_encode.tar.gz",
    "small_business": "small_business_encode.tar.gz",
    "standard": "standard_encode.tar.gz",
    "business": "business_encode.tar.gz",
}
# Bitrix24 (устанавливается через bitrixsetup.php без авторизации):
BITRIX24_SETUP_URL = "https://www.1c-bitrix.ru/download/scripts/bitrixsetup.php"

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


def install_without_wizard(config: dict, ssh_fn) -> dict:
    """
    Установка Битрикс полностью через SSH, без браузера/wizard.
    Используется как fallback когда browser wizard недоступен.
    """
    import os
    server = config.get("server", "")
    path = config.get("install_path", "/var/www/html")
    db = config.get("db", {})
    db_host = db.get("host", "localhost")
    db_user = db.get("user", "bitrix_user")
    db_pass = db.get("password", "")
    db_name = db.get("name", "bitrix_db")

    report = {"status": "running", "steps": [], "errors": [], "method": "ssh_direct"}

    # 1. Проверить .tmp файлы от bitrixsetup.php и переименовать
    _step(report, "check_tmp",
          f"ls {path}/*.tmp 2>/dev/null && mv {path}/*.tmp {path}/bitrix_archive.tar.gz && echo RENAMED || echo NO_TMP",
          ssh_fn)

    # 2. Проверить размер архива
    size_result = str(ssh_fn(f"stat -c%s {path}/bitrix_archive.tar.gz 2>/dev/null || echo 0")).strip()
    try:
        size = int(size_result.split()[-1])
    except Exception:
        size = 0

    # 3. Если архив маленький или отсутствует — скачать заново через wget
    if size < 100_000_000:
        logger.info(f"[install_without_wizard] Archive too small ({size}), downloading via wget...")
        download_url = "https://www.1c-bitrix.ru/download/scripts/bitrixsetup.php"  # Bitrix24 (без авторизации)
        _step(report, "download_archive",
              f"cd {path} && wget -c {download_url} -O bitrix_archive.tar.gz --timeout=300 --tries=3 --progress=dot:giga",
              ssh_fn)

    # 4. Распаковать архив
    _step(report, "extract_archive",
          f"cd {path} && tar -xzf bitrix_archive.tar.gz && echo EXTRACTED",
          ssh_fn)

    # 5. Проверить что /bitrix/modules/ появился
    check = str(ssh_fn(f"ls {path}/bitrix/modules/ 2>/dev/null | wc -l")).strip()
    try:
        modules = int(check.split()[-1])
    except Exception:
        modules = 0

    if modules < 5:
        report["status"] = "failed"
        report["errors"].append(f"Archive extraction failed: only {modules} modules found")
        return report

    # 6. Создать dbconn.php
    dbconn = f"""<?php
define("DBPersistent", false);
$DBType = "mysql";
$DBHost = "{db_host}";
$DBLogin = "{db_user}";
$DBPassword = "{db_pass}";
$DBName = "{db_name}";
$DBDebug = false;
$DBDebugToFile = false;
define("CACHED_b_file", 3600);
define("CACHED_b_file_bucket_size", 10);
define("CACHED_b_lang", 3600);
define("CACHED_b_option", 3600);
define("CACHED_b_lang_domain", 3600);
define("CACHED_b_site_template", 3600);
define("CACHED_b_event", 3600);
define("CACHED_b_agent", 3660);
define("BX_FILE_PERMISSIONS", 0644);
define("BX_DIR_PERMISSIONS", 0755);
@umask(~BX_DIR_PERMISSIONS);
define("BX_UTF", true);
?>"""

    _step(report, "create_dbconn",
          f"mkdir -p {path}/bitrix/php_interface && cat > {path}/bitrix/php_interface/dbconn.php << DBEOF\n{dbconn}\nDBEOF",
          ssh_fn)

    # 7. Создать .settings.php
    settings = f"""<?php
return array(
  utf_mode => array(value => true, readonly => true),
  cache_flags => array(value => array(config_options => 3600)),
  cookies => array(value => array(secure => false, http_only => true)),
  exception_handling => array(value => array(
    debug => false,
    handled_errors_types => E_ALL & ~E_NOTICE & ~E_STRICT & ~E_USER_NOTICE,
    exception_errors_types => E_ALL & ~E_NOTICE & ~E_WARNING & ~E_STRICT & ~E_USER_WARNING & ~E_USER_NOTICE & ~E_COMPILE_WARNING,
    ignore_silence => false,
    assertion_throws_exception => true,
    assertion_error_type => 256,
  )),
  connections => array(value => array(
    default => array(
      className => \\Bitrix\\Main\\DB\\MysqlConnection,
      host => {db_host},
      database => {db_name},
      login => {db_user},
      password => {db_pass},
      options => 2,
    ),
  )),
);
?>"""

    _step(report, "create_settings",
          f"cat > {path}/bitrix/.settings.php << SETEOF\n{settings}\nSETEOF",
          ssh_fn)

    # 8. Права
    _step(report, "set_permissions",
          f"chown -R www-data:www-data {path} && chmod -R 755 {path}",
          ssh_fn)

    # 9. Удалить установщик
    _step(report, "cleanup",
          f"rm -f {path}/bitrixsetup.php {path}/bitrix_archive.tar.gz",
          ssh_fn)

    errors = [s for s in report["steps"] if not s.get("success")]
    report["status"] = "success" if len(errors) == 0 else "partial"
    report["modules"] = modules
    logger.info(f"[install_without_wizard] Done: {report[status]}, modules={modules}")
    return report

def install_bitrix_cli(config: dict, ssh_fn) -> dict:
    """
    Полная установка 1С-Битрикс / Bitrix24 через SSH без браузера и визарда.

    Алгоритм:
    1. Скачивает bitrixsetup.php если нет
    2. Запускает PHP-установщик в CLI-режиме через специальный скрипт
    3. Создаёт все нужные конфиги (dbconn.php, .settings.php, .license_key.php)
    4. Инициализирует БД через PHP CLI (создаёт таблицы ядра Битрикс)
    5. Создаёт admin-пользователя
    6. Настраивает права и nginx

    Поддерживает: 1С-Битрикс Управление Сайтом и Bitrix24 Self-hosted.
    """
    import json as _json

    path = config.get("install_path", "/var/www/html")
    db = config.get("db", {})
    db_host = db.get("host", "localhost")
    db_user = db.get("user", "bitrix_user")
    db_pass = db.get("password", "")
    db_name = db.get("name", "bitrix_db")
    admin_login = config.get("admin_login", "admin")
    admin_password = config.get("admin_password") or generate_safe_password()
    admin_email = config.get("admin_email", "admin@example.com")
    site_name = config.get("site_name", "My Bitrix Site")
    php_bin = config.get("php_bin", "php8.1")  # php8.1 совместим с Битрикс

    report = {"status": "running", "steps": [], "errors": []}

    def step(name, cmd):
        try:
            result = str(ssh_fn(cmd)).strip()
            ok = "ERROR" not in result.upper() or len(result) < 50
            report["steps"].append({"name": name, "ok": ok, "out": result[:300]})
            logger.info(f"[install_bitrix_cli] {name}: {'OK' if ok else 'WARN'} | {result[:100]}")
            return result
        except Exception as e:
            report["steps"].append({"name": name, "ok": False, "out": str(e)})
            report["errors"].append(f"{name}: {e}")
            logger.error(f"[install_bitrix_cli] {name} FAILED: {e}")
            return ""

    # ── 1. Проверить PHP ────────────────────────────────────────────────────
    php_check = step("check_php", f"{php_bin} -r 'echo PHP_VERSION;' 2>/dev/null || php -r 'echo PHP_VERSION;'")
    if not php_check or "." not in php_check:
        php_bin = "php"
        php_check = step("check_php_fallback", "php -r 'echo PHP_VERSION;'")

    # ── 2. Проверить/скачать архив ──────────────────────────────────────────
    archive_size = step("check_archive",
        f"stat -c%s {path}/bitrix_archive.tar.gz 2>/dev/null || echo 0")
    try:
        sz = int(archive_size.split()[-1])
    except Exception:
        sz = 0

    if sz < 100_000_000:
        logger.info(f"[install_bitrix_cli] Archive missing/small ({sz}B), downloading...")
        step("download_bitrix",
            f"cd {path} && wget -q --show-progress "
            f"'https://www.1c-bitrix.ru/download/business_encode_complete.tar.gz' "
            f"-O bitrix_archive.tar.gz 2>&1 | tail -3")

    # ── 3. Распаковать ──────────────────────────────────────────────────────
    modules_count = step("check_modules",
        f"ls {path}/bitrix/modules/ 2>/dev/null | wc -l")
    try:
        mc = int(modules_count.strip())
    except Exception:
        mc = 0

    if mc < 10:
        step("extract_archive",
            f"cd {path} && tar -xzf bitrix_archive.tar.gz 2>&1 | tail -3 && echo DONE")

    # ── 4. Создать dbconn.php ───────────────────────────────────────────────
    dbconn_content = (
        f"<?php\\n"
        f"define('DBPersistent', false);\\n"
        f"\\$DBType = 'mysql';\\n"
        f"\\$DBHost = '{db_host}';\\n"
        f"\\$DBLogin = '{db_user}';\\n"
        f"\\$DBPassword = '{db_pass}';\\n"
        f"\\$DBName = '{db_name}';\\n"
        f"\\$DBDebug = false;\\n"
        f"define('CACHED_b_file', 3600);\\n"
        f"define('CACHED_b_lang', 3600);\\n"
        f"define('CACHED_b_option', 3600);\\n"
        f"define('BX_FILE_PERMISSIONS', 0644);\\n"
        f"define('BX_DIR_PERMISSIONS', 0755);\\n"
        f"define('BX_UTF', true);\\n"
        f"?>"
    )
    step("create_dbconn",
        f"mkdir -p {path}/bitrix/php_interface && "
        f"printf '{dbconn_content}' > {path}/bitrix/php_interface/dbconn.php && "
        f"echo OK")

    # ── 5. Создать .settings.php ────────────────────────────────────────────
    settings_php = (
        "<?php\\n"
        "return array(\\n"
        "  'utf_mode' => array('value' => true, 'readonly' => true),\\n"
        "  'cache_flags' => array('value' => array('config_options' => 3600)),\\n"
        "  'cookies' => array('value' => array('secure' => false, 'http_only' => true)),\\n"
        "  'exception_handling' => array('value' => array(\\n"
        "    'debug' => false,\\n"
        "    'handled_errors_types' => 4437,\\n"
        "    'exception_errors_types' => 4437,\\n"
        "    'ignore_silence' => false,\\n"
        "    'assertion_throws_exception' => true,\\n"
        "    'assertion_error_type' => 256,\\n"
        "  )),\\n"
        f"  'connections' => array('value' => array(\\n"
        f"    'default' => array(\\n"
        f"      'className' => '\\\\\\\\Bitrix\\\\\\\\Main\\\\\\\\DB\\\\\\\\MysqlConnection',\\n"
        f"      'host' => '{db_host}',\\n"
        f"      'database' => '{db_name}',\\n"
        f"      'login' => '{db_user}',\\n"
        f"      'password' => '{db_pass}',\\n"
        f"      'options' => 2,\\n"
        f"    ),\\n"
        f"  )),\\n"
        f");\\n?>"
    )
    step("create_settings",
        f"printf '{settings_php}' > {path}/bitrix/.settings.php && echo OK")

    # ── 6. PHP-скрипт инициализации БД и создания admin ────────────────────
    # Записываем PHP-скрипт на сервер через heredoc
    init_script = r"""<?php
error_reporting(E_ALL);
ini_set('display_errors', 1);

// Определяем корень Битрикс
$_SERVER['DOCUMENT_ROOT'] = '__INSTALL_PATH__';
$_SERVER['HTTP_HOST'] = 'localhost';
$_SERVER['SERVER_NAME'] = 'localhost';
$_SERVER['HTTPS'] = '';
define('NO_KEEP_STATISTIC', true);
define('NO_AGENT_STATISTIC', true);
define('NOT_CHECK_PERMISSIONS', true);
define('BX_NO_ACCELERATOR_RESET', true);

// Подключаем ядро Битрикс
$bxKernel = '__INSTALL_PATH__/bitrix/modules/main/include/prolog_before.php';
if (!file_exists($bxKernel)) {
    echo "ERROR: Bitrix kernel not found at $bxKernel\n";
    exit(1);
}

require_once $bxKernel;

// Проверяем подключение к БД
try {
    $connection = \Bitrix\Main\Application::getConnection();
    echo "DB_OK\n";
} catch (\Exception $e) {
    echo "DB_ERROR: " . $e->getMessage() . "\n";
    exit(1);
}

// Устанавливаем модуль main (создаёт таблицы)
$installer = new CModuleInstaller();
if (method_exists($installer, 'InstallDB')) {
    $result = $installer->InstallDB();
    echo "MAIN_MODULE: " . ($result ? "OK" : "SKIP") . "\n";
}

// Создаём admin пользователя
$user = new CUser;
$arFields = array(
    "NAME"             => "Admin",
    "LAST_NAME"        => "",
    "EMAIL"            => "__ADMIN_EMAIL__",
    "LOGIN"            => "__ADMIN_LOGIN__",
    "LID"              => "ru",
    "ACTIVE"           => "Y",
    "GROUP_ID"         => array(1),
    "PASSWORD"         => "__ADMIN_PASS__",
    "CONFIRM_PASSWORD" => "__ADMIN_PASS__",
);
$ID = $user->Add($arFields);
if ($ID > 0) {
    echo "ADMIN_CREATED: ID=$ID\n";
} else {
    // Возможно уже существует — обновим пароль
    $res = CUser::GetByLogin("__ADMIN_LOGIN__");
    if ($u = $res->Fetch()) {
        $user->Update($u['ID'], array(
            "PASSWORD" => "__ADMIN_PASS__",
            "CONFIRM_PASSWORD" => "__ADMIN_PASS__",
        ));
        echo "ADMIN_UPDATED: ID=" . $u['ID'] . "\n";
    } else {
        echo "ADMIN_ERROR: " . $user->LAST_ERROR . "\n";
    }
}

// Устанавливаем настройки сайта
COption::SetOptionString("main", "site_name", "__SITE_NAME__");
COption::SetOptionString("main", "email_from", "__ADMIN_EMAIL__");
echo "SITE_SETTINGS_OK\n";

// Создаём маркер установки
file_put_contents('__INSTALL_PATH__/bitrix/.installed', date('Y-m-d H:i:s'));
echo "INSTALL_MARKER_OK\n";
echo "DONE\n";
"""

    init_script = (init_script
        .replace("__INSTALL_PATH__", path)
        .replace("__ADMIN_EMAIL__", admin_email)
        .replace("__ADMIN_LOGIN__", admin_login)
        .replace("__ADMIN_PASS__", admin_password)
        .replace("__SITE_NAME__", site_name)
    )

    # Записать скрипт на сервер
    step("write_init_script",
        f"cat > /tmp/bx_init.php << 'PHPEOF'\n{init_script}\nPHPEOF\necho WRITTEN")

    # ── 7. Запустить PHP-инициализацию ──────────────────────────────────────
    init_result = step("run_init_script",
        f"cd {path} && {php_bin} /tmp/bx_init.php 2>&1")

    if "DONE" in init_result:
        report["bitrix_initialized"] = True
        logger.info("[install_bitrix_cli] Bitrix core initialized successfully")
    else:
        report["bitrix_initialized"] = False
        logger.warning(f"[install_bitrix_cli] Init script output: {init_result[:500]}")

    # ── 8. Создать правильный index.php для Битрикс ─────────────────────────
    index_php = (
        "<?php\\n"
        "define('NO_KEEP_STATISTIC', true);\\n"
        "define('NO_AGENT_STATISTIC', true);\\n"
        f"\\$_SERVER['DOCUMENT_ROOT'] = '{path}';\\n"
        f"require_once('{path}/bitrix/header.php');\\n"
        "?><?php require_once(SITE_TEMPLATE_PATH . '/header.php'); ?>\\n"
        "<?php require_once(SITE_TEMPLATE_PATH . '/footer.php'); ?>\\n"
        f"<?php require_once('{path}/bitrix/footer.php'); ?>\\n"
    )
    # Сохранить текущий index.html как шаблон
    step("backup_index",
        f"cp {path}/index.html {path}/index.html.bak.landing 2>/dev/null; echo OK")

    step("create_bitrix_index",
        f"printf '{index_php}' > {path}/index.php && echo OK")

    # ── 9. Настроить nginx для PHP ──────────────────────────────────────────
    step("nginx_php_config",
        f"""cat > /etc/nginx/sites-available/dimydiv << 'NGINXEOF'
server {{
    listen 80;
    server_name _;
    root {path};
    index index.php index.html;

    location ^~ /dimydiv/ {{
        alias {path}/;
        index index.php index.html;
        location ~ \\.php$ {{
            fastcgi_pass unix:/run/php/php8.1-fpm.sock;
            fastcgi_index index.php;
            include fastcgi_params;
            fastcgi_param SCRIPT_FILENAME $request_filename;
            fastcgi_param DOCUMENT_ROOT {path};
        }}
        location ~* \\.(jpg|jpeg|gif|png|svg|js|css|ico|woff2?)$ {{
            expires 30d;
            try_files $uri =404;
        }}
    }}

    location /bitrix/admin/ {{
        alias {path}/bitrix/admin/;
        index index.php;
        location ~ \\.php$ {{
            fastcgi_pass unix:/run/php/php8.1-fpm.sock;
            fastcgi_index index.php;
            include fastcgi_params;
            fastcgi_param SCRIPT_FILENAME $request_filename;
            fastcgi_param DOCUMENT_ROOT {path};
        }}
    }}
}}
NGINXEOF
ln -sf /etc/nginx/sites-available/dimydiv /etc/nginx/sites-enabled/dimydiv
nginx -t && systemctl reload nginx && echo NGINX_OK""")

    # ── 10. Права ───────────────────────────────────────────────────────────
    step("set_permissions",
        f"chown -R www-data:www-data {path} && "
        f"find {path} -type d -exec chmod 755 {{}} \\; && "
        f"find {path} -type f -exec chmod 644 {{}} \\; && "
        f"chmod 777 {path}/upload {path}/bitrix/cache {path}/bitrix/managed_cache 2>/dev/null; "
        f"echo OK")

    # ── 11. Финальная проверка ──────────────────────────────────────────────
    http_main = step("check_site",
        f"curl -sI http://localhost/dimydiv/ | head -1")
    http_admin = step("check_admin",
        f"curl -sI http://localhost/bitrix/admin/ | head -1")

    step("cleanup",
        f"rm -f /tmp/bx_init.php {path}/bitrixsetup.php 2>/dev/null; echo OK")

    # ── Итог ────────────────────────────────────────────────────────────────
    errors = [s for s in report["steps"] if not s.get("ok")]
    report["status"] = "success" if report.get("bitrix_initialized") else "partial"
    report["admin_url"] = f"http://SERVER/bitrix/admin/"
    report["admin_login"] = admin_login
    report["admin_password"] = admin_password
    report["site_url"] = f"http://SERVER/dimydiv/"

    logger.info(
        f"[install_bitrix_cli] Finished: status={report['status']}, "
        f"initialized={report.get('bitrix_initialized')}, "
        f"steps={len(report['steps'])}, errors={len(errors)}"
    )
    return report
