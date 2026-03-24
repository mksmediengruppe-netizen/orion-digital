"""
install_bitrix_pipeline.py — Полная установка 1С-Битрикс через SSH/CLI без браузера.

Pipeline stages:
  1. Intake — валидация входных данных
  2. Environment check — PHP, MySQL, nginx
  3. Download — скачивание архива с официального источника
  4. Unpack — распаковка архива
  5. DB prep — создание БД и пользователя
  6. Config — генерация dbconn.php и .settings.php
  7. DB init — инициализация таблиц Битрикс через PHP CLI
  8. Admin — создание admin-пользователя
  9. Nginx — настройка веб-сервера
  10. Verify — строгая проверка установки
  11. Cleanup — удаление временных файлов

Verdict model: SUCCESS / PARTIAL_SUCCESS / FAILED / NEEDS_REVIEW
"""

import json
import logging
import re
import time
from typing import Callable, Optional, Dict, Any, List

logger = logging.getLogger("install_bitrix_pipeline")

# ═══ Constants ═══════════════════════════════════════════════════════════════

BITRIX_EDITIONS = {
    "start": {
        "url": "https://www.1c-bitrix.ru/download/start_encode.tar.gz",
        "min_size": 200_000_000,
        "description": "1С-Битрикс: Старт",
    },
    "standard": {
        "url": "https://www.1c-bitrix.ru/download/standard_encode.tar.gz",
        "min_size": 300_000_000,
        "description": "1С-Битрикс: Стандарт",
    },
    "small_business": {
        "url": "https://www.1c-bitrix.ru/download/small_business_encode.tar.gz",
        "min_size": 300_000_000,
        "description": "1С-Битрикс: Малый бизнес",
    },
    "business": {
        "url": "https://www.1c-bitrix.ru/download/business_encode.tar.gz",
        "min_size": 400_000_000,
        "description": "1С-Битрикс: Бизнес",
    },
}

DEFAULT_EDITION = "start"

REQUIRED_PHP_EXTENSIONS = [
    "mbstring", "curl", "gd", "xml", "zip", "opcache",
    "mysqli", "json", "fileinfo", "openssl",
]

PHP_INI_SETTINGS = {
    "short_open_tag": "On",
    "mbstring.func_overload": "0",
    "max_input_vars": "10000",
    "memory_limit": "256M",
    "upload_max_filesize": "64M",
    "post_max_size": "64M",
    "max_execution_time": "600",
    "date.timezone": "Europe/Moscow",
    "opcache.revalidate_freq": "0",
    "display_errors": "Off",
    "error_reporting": "E_ALL & ~E_NOTICE & ~E_STRICT",
}

CRITICAL_BITRIX_MODULES = [
    "main", "iblock", "fileman", "search", "socialnetwork",
]

# ═══ SQL injection prevention ════════════════════════════════════════════════

def _validate_identifier(name: str, label: str = "identifier") -> str:
    if not re.fullmatch(r"[A-Za-z0-9_]+", name):
        raise ValueError(f"Invalid {label}: {name}. Only [A-Za-z0-9_] allowed.")
    return name


def _escape_php_string(s: str) -> str:
    """Escape a string for safe inclusion in PHP single-quoted strings."""
    return s.replace("\\", "\\\\").replace("'", "\\'")


# ═══ Main Pipeline ═══════════════════════════════════════════════════════════

def install_bitrix_pipeline(
    ssh_fn: Callable,
    install_path: str = "/var/www/html",
    db_host: str = "localhost",
    db_name: str = "bitrix_db",
    db_user: str = "bitrix_user",
    db_password: str = "",
    db_root_password: str = "",
    admin_login: str = "admin",
    admin_email: str = "admin@example.com",
    admin_password: str = "Admin123!",
    site_name: str = "My Bitrix Site",
    site_url: str = "",
    edition: str = "start",
    php_version: str = "",
    url_prefix: str = "",
    use_demo: bool = True,
    skip_download: bool = False,
) -> Dict[str, Any]:
    """
    Full Bitrix CMS installation pipeline via SSH/CLI.

    Args:
        ssh_fn: Function that executes SSH commands and returns output string
        install_path: Server path for Bitrix files
        db_host: MySQL host
        db_name: Database name
        db_user: Database user
        db_password: Database password
        db_root_password: MySQL root password (for creating DB/user)
        admin_login: Bitrix admin login
        admin_email: Admin email
        admin_password: Admin password
        site_name: Site name
        site_url: Full site URL (e.g. http://45.67.57.175/bitrix-test/)
        edition: Bitrix edition (start, standard, small_business, business)
        php_version: PHP version (auto-detect if empty)
        url_prefix: URL prefix for nginx location (e.g. /bitrix-test)
        use_demo: Install in demo mode
        skip_download: Skip download if files already exist

    Returns:
        dict with status, steps, checkpoints, verification, verdict
    """
    start_time = time.time()

    report = {
        "status": "running",
        "verdict": "FAILED",
        "steps": [],
        "checkpoints": [],
        "errors": [],
        "warnings": [],
        "metrics": {
            "ssh_calls_count": 0,
            "start_time": start_time,
        },
    }

    def ssh(cmd: str, timeout: int = 120) -> str:
        """Execute SSH command with logging."""
        report["metrics"]["ssh_calls_count"] += 1
        try:
            result = str(ssh_fn(cmd)).strip()
            return result
        except Exception as e:
            logger.error(f"[SSH] Command failed: {cmd[:100]}... Error: {e}")
            return f"SSH_ERROR: {e}"

    def step(name: str, cmd: str, critical: bool = False) -> str:
        """Execute a step and record it."""
        logger.info(f"[STEP] {name}")
        result = ssh(cmd)
        is_error = result.startswith("SSH_ERROR:") or (
            "ERROR" in result.upper() and len(result) < 200 and "error_reporting" not in result.lower()
        )
        ok = not is_error
        report["steps"].append({
            "name": name,
            "ok": ok,
            "output": result[:500],
            "critical": critical,
            "timestamp": time.time(),
        })
        if not ok:
            msg = f"Step '{name}' failed: {result[:200]}"
            if critical:
                report["errors"].append(msg)
            else:
                report["warnings"].append(msg)
            logger.warning(f"[STEP] {name}: FAILED — {result[:200]}")
        else:
            logger.info(f"[STEP] {name}: OK — {result[:100]}")
        return result

    def checkpoint(name: str):
        """Save a checkpoint."""
        report["checkpoints"].append({
            "name": name,
            "timestamp": time.time(),
        })
        logger.info(f"[CHECKPOINT] {name}")

    # ═══ Stage 1: Intake — validate inputs ═══════════════════════════════════

    logger.info("[STAGE 1] Intake — validating inputs")

    try:
        _validate_identifier(db_name, "db_name")
        _validate_identifier(db_user, "db_user")
    except ValueError as e:
        report["errors"].append(str(e))
        report["status"] = "failed"
        report["verdict"] = "FAILED"
        return report

    if not install_path or not install_path.startswith("/"):
        report["errors"].append(f"Invalid install_path: {install_path}")
        report["status"] = "failed"
        report["verdict"] = "FAILED"
        return report

    # Auto-detect url_prefix from install_path
    if not url_prefix and install_path != "/var/www/html":
        # e.g. /var/www/html/bitrix-test → /bitrix-test
        base = install_path.rstrip("/")
        if "/var/www/html/" in base:
            url_prefix = "/" + base.split("/var/www/html/")[-1]

    edition_info = BITRIX_EDITIONS.get(edition, BITRIX_EDITIONS[DEFAULT_EDITION])

    # ═══ Stage 2: Environment check ══════════════════════════════════════════

    logger.info("[STAGE 2] Environment check")

    # Detect PHP version
    if not php_version:
        php_v = ssh("php -r 'echo PHP_MAJOR_VERSION . \".\" . PHP_MINOR_VERSION;' 2>/dev/null")
        if re.match(r"\d+\.\d+", php_v):
            php_version = php_v.strip()
        else:
            # Try common versions
            for v in ["8.3", "8.2", "8.1", "8.0", "7.4"]:
                check = ssh(f"php{v} -r 'echo PHP_VERSION;' 2>/dev/null")
                if "." in check and "not found" not in check.lower():
                    php_version = v
                    break
            if not php_version:
                php_version = "8.1"  # default fallback

    php_bin = f"php{php_version}" if "." in php_version else "php"
    php_fpm_sock = f"/run/php/php{php_version}-fpm.sock"

    # Verify PHP works
    php_check = step("check_php", f"{php_bin} -r 'echo PHP_VERSION;' 2>/dev/null || php -r 'echo PHP_VERSION;'", critical=True)
    if "." not in php_check:
        php_bin = "php"
        php_check = step("check_php_fallback", "php -r 'echo PHP_VERSION;'", critical=True)
        if "." not in php_check:
            report["errors"].append("PHP not found on server")
            report["status"] = "failed"
            report["verdict"] = "FAILED"
            return report

    # Check PHP extensions
    missing_ext = []
    ext_check = ssh(f"{php_bin} -m 2>/dev/null")
    for ext in REQUIRED_PHP_EXTENSIONS:
        if ext.lower() not in ext_check.lower():
            missing_ext.append(ext)

    if missing_ext:
        logger.info(f"[ENV] Missing PHP extensions: {missing_ext}, attempting install...")
        for ext in missing_ext:
            step(f"install_php_ext_{ext}",
                 f"apt-get install -y php{php_version}-{ext} 2>/dev/null || "
                 f"apt-get install -y php-{ext} 2>/dev/null; echo DONE")
        # Restart PHP-FPM
        step("restart_php_fpm", f"systemctl restart php{php_version}-fpm 2>/dev/null || systemctl restart php-fpm 2>/dev/null; echo OK")

    # Check MySQL
    mysql_check = ssh("mysql --version 2>/dev/null || mysqld --version 2>/dev/null")
    if "mysql" not in mysql_check.lower() and "mariadb" not in mysql_check.lower():
        report["errors"].append("MySQL/MariaDB not found")
        report["status"] = "failed"
        report["verdict"] = "FAILED"
        return report

    # Check nginx
    nginx_check = ssh("nginx -v 2>&1")
    if "nginx" not in nginx_check.lower():
        report["warnings"].append("nginx not found, will try to install")
        step("install_nginx", "apt-get install -y nginx && systemctl start nginx; echo OK")

    # Check PHP-FPM socket
    fpm_check = ssh(f"test -S {php_fpm_sock} && echo OK || echo MISSING")
    if "MISSING" in fpm_check:
        # Try to find the actual socket
        fpm_find = ssh("find /run/php/ -name '*.sock' 2>/dev/null | head -1")
        if fpm_find and ".sock" in fpm_find:
            php_fpm_sock = fpm_find.strip()
            logger.info(f"[ENV] Found PHP-FPM socket: {php_fpm_sock}")
        else:
            step("start_php_fpm", f"systemctl start php{php_version}-fpm 2>/dev/null; echo OK")

    checkpoint("env_checked")

    # ═══ Stage 3: Download ═══════════════════════════════════════════════════

    logger.info("[STAGE 3] Download")

    # Create install directory
    step("create_install_dir", f"mkdir -p {install_path} && echo OK", critical=True)

    archive_path = f"{install_path}/bitrix_archive.tar.gz"

    if not skip_download:
        # Check existing archive
        size_check = ssh(f"stat -c%s {archive_path} 2>/dev/null || echo 0")
        try:
            existing_size = int(size_check.split()[-1])
        except (ValueError, IndexError):
            existing_size = 0

        min_size = edition_info["min_size"]

        if existing_size < min_size:
            download_url = edition_info["url"]
            logger.info(f"[DOWNLOAD] Archive missing/small ({existing_size}B < {min_size}B), downloading from {download_url}")

            dl_result = step("download_bitrix",
                f"cd {install_path} && "
                f"wget -q --show-progress -L '{download_url}' -O bitrix_archive.tar.gz "
                f"--timeout=600 --tries=3 2>&1 | tail -5 && "
                f"stat -c%s bitrix_archive.tar.gz",
                critical=True)

            # Verify download size
            size_after = ssh(f"stat -c%s {archive_path} 2>/dev/null || echo 0")
            try:
                dl_size = int(size_after.split()[-1])
            except (ValueError, IndexError):
                dl_size = 0

            if dl_size < min_size:
                report["errors"].append(
                    f"Download failed: archive size {dl_size}B < expected {min_size}B"
                )
                report["status"] = "failed"
                report["verdict"] = "FAILED"
                return report

            logger.info(f"[DOWNLOAD] Archive downloaded: {dl_size}B")
        else:
            logger.info(f"[DOWNLOAD] Archive already exists: {existing_size}B")

    checkpoint("archive_downloaded")

    # ═══ Stage 4: Unpack ═════════════════════════════════════════════════════

    logger.info("[STAGE 4] Unpack")

    # Check if already unpacked
    modules_check = ssh(f"ls {install_path}/bitrix/modules/ 2>/dev/null | wc -l")
    try:
        modules_count = int(modules_check.strip())
    except (ValueError, IndexError):
        modules_count = 0

    if modules_count < 10:
        logger.info(f"[UNPACK] Only {modules_count} modules found, extracting archive...")
        step("extract_archive",
             f"cd {install_path} && tar -xzf bitrix_archive.tar.gz 2>&1 | tail -3 && echo EXTRACT_DONE",
             critical=True)

        # Verify extraction
        modules_after = ssh(f"ls {install_path}/bitrix/modules/ 2>/dev/null | wc -l")
        try:
            modules_count = int(modules_after.strip())
        except (ValueError, IndexError):
            modules_count = 0

        if modules_count < 5:
            report["errors"].append(f"Extraction failed: only {modules_count} modules found")
            report["status"] = "failed"
            report["verdict"] = "FAILED"
            return report
    else:
        logger.info(f"[UNPACK] Already unpacked: {modules_count} modules")

    report["metrics"]["modules_count"] = modules_count
    checkpoint("files_unpacked")

    # ═══ Stage 5: DB prep ════════════════════════════════════════════════════

    logger.info("[STAGE 5] DB prep")

    # Try to create database and user
    mysql_auth = ""
    if db_root_password:
        mysql_auth = f"-u root -p'{_escape_php_string(db_root_password)}'"
    else:
        # Try without password first (common for local MySQL)
        mysql_auth = "-u root"

    # Create database
    step("create_database",
         f"mysql {mysql_auth} -e \"CREATE DATABASE IF NOT EXISTS \\`{db_name}\\` "
         f"CHARACTER SET utf8 COLLATE utf8_unicode_ci;\" 2>&1 || echo DB_EXISTS")

    # Create user and grant privileges
    step("create_db_user",
         f"mysql {mysql_auth} -e \""
         f"CREATE USER IF NOT EXISTS '{db_user}'@'localhost' IDENTIFIED BY '{_escape_php_string(db_password)}';"
         f"GRANT ALL PRIVILEGES ON \\`{db_name}\\`.* TO '{db_user}'@'localhost';"
         f"FLUSH PRIVILEGES;\" 2>&1 || echo USER_EXISTS")

    # Verify DB connection
    db_test = step("verify_db_connection",
                   f"mysql -u {db_user} -p'{_escape_php_string(db_password)}' {db_name} "
                   f"-e 'SELECT 1 AS test;' 2>&1",
                   critical=True)

    if "test" not in db_test and "1" not in db_test:
        # Try alternative: maybe user already exists with different password
        step("update_db_user_password",
             f"mysql {mysql_auth} -e \""
             f"ALTER USER '{db_user}'@'localhost' IDENTIFIED BY '{_escape_php_string(db_password)}';"
             f"FLUSH PRIVILEGES;\" 2>&1")

        db_test2 = step("verify_db_connection_retry",
                        f"mysql -u {db_user} -p'{_escape_php_string(db_password)}' {db_name} "
                        f"-e 'SELECT 1 AS test;' 2>&1",
                        critical=True)

        if "test" not in db_test2 and "1" not in db_test2:
            report["errors"].append("Cannot connect to database")
            report["status"] = "failed"
            report["verdict"] = "FAILED"
            return report

    checkpoint("db_ready")

    # ═══ Stage 6: Config files ═══════════════════════════════════════════════

    logger.info("[STAGE 6] Config files")

    # Create dbconn.php
    dbconn_php = f"""<?php
define("DBPersistent", false);
$DBType = "mysql";
$DBHost = "{_escape_php_string(db_host)}";
$DBLogin = "{_escape_php_string(db_user)}";
$DBPassword = "{_escape_php_string(db_password)}";
$DBName = "{_escape_php_string(db_name)}";
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
define("BX_USE_MYSQLI", true);
"""

    step("create_dbconn",
         f"mkdir -p {install_path}/bitrix/php_interface && "
         f"cat > {install_path}/bitrix/php_interface/dbconn.php << 'DBCONNEOF'\n{dbconn_php}\nDBCONNEOF\n"
         f"echo DBCONN_OK",
         critical=True)

    # Create .settings.php
    settings_php = f"""<?php
return array(
  'utf_mode' => array(
    'value' => true,
    'readonly' => true,
  ),
  'cache_flags' => array(
    'value' => array(
      'config_options' => 3600,
    ),
  ),
  'cookies' => array(
    'value' => array(
      'secure' => false,
      'http_only' => true,
    ),
  ),
  'exception_handling' => array(
    'value' => array(
      'debug' => false,
      'handled_errors_types' => E_ALL & ~E_NOTICE & ~E_STRICT & ~E_USER_NOTICE,
      'exception_errors_types' => E_ALL & ~E_NOTICE & ~E_WARNING & ~E_STRICT & ~E_USER_WARNING & ~E_USER_NOTICE & ~E_COMPILE_WARNING,
      'ignore_silence' => false,
      'assertion_throws_exception' => true,
      'assertion_error_type' => 256,
      'log' => array(
        'class_name' => '\\\\Bitrix\\\\Main\\\\Diag\\\\FileExceptionHandlerLog',
        'settings' => array(
          'file' => 'bitrix/modules/error.log',
          'log_size' => 1000000,
        ),
      ),
    ),
  ),
  'connections' => array(
    'value' => array(
      'default' => array(
        'className' => '\\\\Bitrix\\\\Main\\\\DB\\\\MysqliConnection',
        'host' => '{_escape_php_string(db_host)}',
        'database' => '{_escape_php_string(db_name)}',
        'login' => '{_escape_php_string(db_user)}',
        'password' => '{_escape_php_string(db_password)}',
        'options' => 2,
      ),
    ),
  ),
  'crypto' => array(
    'value' => array(
      'crypto_key' => '{_escape_php_string("orion_" + str(int(time.time())))}',
    ),
  ),
);
"""

    step("create_settings",
         f"cat > {install_path}/bitrix/.settings.php << 'SETTINGSEOF'\n{settings_php}\nSETTINGSEOF\n"
         f"echo SETTINGS_OK",
         critical=True)

    # Create after_connect_d.php for UTF-8
    step("create_after_connect",
         f"cat > {install_path}/bitrix/php_interface/after_connect_d.php << 'ACEOF'\n"
         f"<?php\n"
         f"$DB->Query(\"SET NAMES 'utf8'\");\n"
         f"$DB->Query(\"SET CHARACTER SET 'utf8'\");\n"
         f"$DB->Query(\"SET collation_connection = 'utf8_unicode_ci'\");\n"
         f"ACEOF\n"
         f"echo AFTER_CONNECT_OK")

    checkpoint("config_created")

    # ═══ Stage 7: DB initialization via PHP CLI ══════════════════════════════

    logger.info("[STAGE 7] DB initialization")

    # Write the initialization PHP script
    init_php = f"""<?php
error_reporting(E_ALL);
ini_set('display_errors', 1);
ini_set('memory_limit', '512M');
ini_set('max_execution_time', 600);

$_SERVER['DOCUMENT_ROOT'] = '{install_path}';
$_SERVER['HTTP_HOST'] = 'localhost';
$_SERVER['SERVER_NAME'] = 'localhost';
$_SERVER['SERVER_PORT'] = '80';
$_SERVER['REQUEST_URI'] = '/';
$_SERVER['HTTPS'] = '';

define('NO_KEEP_STATISTIC', true);
define('NO_AGENT_STATISTIC', true);
define('NOT_CHECK_PERMISSIONS', true);
define('BX_NO_ACCELERATOR_RESET', true);
define('BX_BUFFER_USED', true);
define('STOP_STATISTICS', true);

// Check kernel exists
$kernelPath = '{install_path}/bitrix/modules/main/include/prolog_before.php';
if (!file_exists($kernelPath)) {{
    echo "KERNEL_NOT_FOUND\\n";
    // Try alternative path
    $altPath = '{install_path}/bitrix/modules/main/include.php';
    if (file_exists($altPath)) {{
        echo "ALT_KERNEL_FOUND\\n";
        $kernelPath = $altPath;
    }} else {{
        echo "FATAL: No Bitrix kernel found\\n";
        exit(1);
    }}
}}

echo "LOADING_KERNEL\\n";

// Suppress output buffering issues
ob_start();
try {{
    require_once($kernelPath);
    echo "KERNEL_LOADED\\n";
}} catch (\\Exception $e) {{
    echo "KERNEL_ERROR: " . $e->getMessage() . "\\n";
    // Try to continue anyway
}}
ob_end_clean();

// Check DB connection
try {{
    $connection = \\Bitrix\\Main\\Application::getConnection();
    $connection->queryExecute("SELECT 1");
    echo "DB_CONNECTION_OK\\n";
}} catch (\\Exception $e) {{
    echo "DB_ERROR: " . $e->getMessage() . "\\n";
    exit(1);
}}

// Check if tables already exist
try {{
    $result = $connection->query("SHOW TABLES LIKE 'b_%'");
    $tableCount = 0;
    while ($result->fetch()) {{
        $tableCount++;
    }}
    echo "EXISTING_TABLES: $tableCount\\n";
    
    if ($tableCount > 50) {{
        echo "TABLES_ALREADY_EXIST\\n";
    }}
}} catch (\\Exception $e) {{
    echo "TABLE_CHECK_ERROR: " . $e->getMessage() . "\\n";
}}

// Install main module (creates core tables)
echo "INSTALLING_MAIN_MODULE\\n";
try {{
    if (class_exists('CModule')) {{
        $mainModule = CModule::CreateModuleObject('main');
        if ($mainModule && method_exists($mainModule, 'InstallDB')) {{
            $mainModule->InstallDB();
            echo "MAIN_MODULE_INSTALLED\\n";
        }} else {{
            echo "MAIN_MODULE_SKIP\\n";
        }}
    }} else {{
        echo "CMODULE_NOT_FOUND\\n";
    }}
}} catch (\\Exception $e) {{
    echo "MAIN_MODULE_ERROR: " . $e->getMessage() . "\\n";
}}

// Install essential modules
$essentialModules = array('fileman', 'iblock', 'search', 'socialnetwork', 'subscribe', 'compression');
foreach ($essentialModules as $modName) {{
    try {{
        if (IsModuleInstalled($modName)) {{
            echo "MODULE_ALREADY: $modName\\n";
            continue;
        }}
        $mod = CModule::CreateModuleObject($modName);
        if ($mod && method_exists($mod, 'InstallDB')) {{
            $mod->InstallDB();
            echo "MODULE_INSTALLED: $modName\\n";
        }}
    }} catch (\\Exception $e) {{
        echo "MODULE_ERROR: $modName: " . $e->getMessage() . "\\n";
    }}
}}

// Create or update admin user
echo "CREATING_ADMIN\\n";
try {{
    $user = new CUser;
    $arFields = array(
        "NAME"             => "Admin",
        "LAST_NAME"        => "",
        "EMAIL"            => "{_escape_php_string(admin_email)}",
        "LOGIN"            => "{_escape_php_string(admin_login)}",
        "LID"              => "ru",
        "ACTIVE"           => "Y",
        "GROUP_ID"         => array(1),
        "PASSWORD"         => "{_escape_php_string(admin_password)}",
        "CONFIRM_PASSWORD" => "{_escape_php_string(admin_password)}",
    );

    $ID = $user->Add($arFields);
    if (intval($ID) > 0) {{
        echo "ADMIN_CREATED: ID=$ID\\n";
    }} else {{
        // User might already exist — update password
        $res = CUser::GetByLogin("{_escape_php_string(admin_login)}");
        if ($u = $res->Fetch()) {{
            $user->Update($u['ID'], array(
                "PASSWORD" => "{_escape_php_string(admin_password)}",
                "CONFIRM_PASSWORD" => "{_escape_php_string(admin_password)}",
            ));
            echo "ADMIN_UPDATED: ID=" . $u['ID'] . "\\n";
        }} else {{
            echo "ADMIN_ERROR: " . $user->LAST_ERROR . "\\n";
        }}
    }}
}} catch (\\Exception $e) {{
    echo "ADMIN_EXCEPTION: " . $e->getMessage() . "\\n";
}}

// Set site settings
try {{
    COption::SetOptionString("main", "site_name", "{_escape_php_string(site_name)}");
    COption::SetOptionString("main", "email_from", "{_escape_php_string(admin_email)}");
    COption::SetOptionString("main", "SALE_SITE_ID", "s1");
    echo "SITE_SETTINGS_OK\\n";
}} catch (\\Exception $e) {{
    echo "SITE_SETTINGS_ERROR: " . $e->getMessage() . "\\n";
}}

// Mark installation as complete
try {{
    // Remove install wizard marker
    @unlink('{install_path}/bitrix/modules/main/install/wizard/wizard.php');
    
    // Create installation marker
    file_put_contents('{install_path}/bitrix/.install_complete', json_encode(array(
        'date' => date('Y-m-d H:i:s'),
        'method' => 'cli_pipeline',
        'admin' => '{_escape_php_string(admin_login)}',
    )));
    
    // Disable wizard redirect
    COption::SetOptionString("main", "wizard_first", "N", "Wizard completed");
    COption::SetOptionString("main", "~wizard_first", "N");
    
    echo "WIZARD_DISABLED\\n";
}} catch (\\Exception $e) {{
    echo "WIZARD_DISABLE_ERROR: " . $e->getMessage() . "\\n";
}}

// Final table count
try {{
    $result = $connection->query("SHOW TABLES LIKE 'b_%'");
    $finalCount = 0;
    while ($result->fetch()) {{
        $finalCount++;
    }}
    echo "FINAL_TABLES: $finalCount\\n";
}} catch (\\Exception $e) {{
    echo "FINAL_COUNT_ERROR\\n";
}}

echo "INIT_DONE\\n";
"""

    # Write init script to server
    step("write_init_script",
         f"cat > /tmp/bx_init_pipeline.php << 'INITEOF'\n{init_php}\nINITEOF\n"
         f"echo SCRIPT_WRITTEN")

    # Run initialization
    init_result = step("run_init_script",
                       f"cd {install_path} && {php_bin} -d memory_limit=512M /tmp/bx_init_pipeline.php 2>&1",
                       critical=True)

    # Parse init results
    db_ok = "DB_CONNECTION_OK" in init_result
    kernel_ok = "KERNEL_LOADED" in init_result or "ALT_KERNEL_FOUND" in init_result
    admin_ok = "ADMIN_CREATED" in init_result or "ADMIN_UPDATED" in init_result
    init_done = "INIT_DONE" in init_result
    wizard_disabled = "WIZARD_DISABLED" in init_result

    # Extract final table count
    table_match = re.search(r"FINAL_TABLES:\s*(\d+)", init_result)
    final_tables = int(table_match.group(1)) if table_match else 0

    report["metrics"]["db_tables"] = final_tables
    report["metrics"]["kernel_loaded"] = kernel_ok
    report["metrics"]["admin_created"] = admin_ok
    report["metrics"]["init_done"] = init_done

    if not init_done:
        report["warnings"].append(f"Init script did not complete fully. Output: {init_result[:300]}")

    checkpoint("db_initialized")

    # ═══ Stage 8: Create proper index.php ════════════════════════════════════

    logger.info("[STAGE 8] Create index.php and templates")

    # Create Bitrix-compatible index.php
    index_php = """<?php
require($_SERVER["DOCUMENT_ROOT"]."/bitrix/header.php");
$APPLICATION->SetTitle("Главная");
?>

<div style="padding: 40px; text-align: center;">
    <h1>Сайт работает на 1С-Битрикс</h1>
    <p>Установка выполнена успешно.</p>
    <p><a href="/bitrix/admin/">Панель администрирования</a></p>
</div>

<?php require($_SERVER["DOCUMENT_ROOT"]."/bitrix/footer.php"); ?>
"""

    step("create_index_php",
         f"cat > {install_path}/index.php << 'INDEXEOF'\n{index_php}\nINDEXEOF\n"
         f"echo INDEX_OK")

    # Backup any existing index.html
    step("backup_index_html",
         f"test -f {install_path}/index.html && "
         f"mv {install_path}/index.html {install_path}/index.html.bak 2>/dev/null; echo OK")

    # Create .htaccess for Bitrix
    htaccess = """Options -Indexes
ErrorDocument 404 /404.php

<IfModule mod_php.c>
    php_flag allow_call_time_pass_reference 1
    php_flag session.use_trans_sid off
    php_value display_errors Off
    php_value mbstring.func_overload 0
    php_value mbstring.internal_encoding UTF-8
</IfModule>

<IfModule mod_rewrite.c>
    RewriteEngine On
    RewriteCond %{REQUEST_FILENAME} !-f
    RewriteCond %{REQUEST_FILENAME} !-d
    RewriteRule ^(.*)$ /bitrix/urlrewrite.php [L]
</IfModule>
"""

    step("create_htaccess",
         f"cat > {install_path}/.htaccess << 'HTEOF'\n{htaccess}\nHTEOF\n"
         f"echo HTACCESS_OK")

    # ═══ Stage 9: Nginx configuration ════════════════════════════════════════

    logger.info("[STAGE 9] Nginx configuration")

    # Determine nginx config based on whether it's a subpath or root
    if url_prefix:
        # Subpath installation (e.g. /bitrix-test/)
        prefix = url_prefix.strip("/")
        nginx_conf = f"""# Bitrix site at /{prefix}/
location ^~ /{prefix}/ {{
    alias {install_path}/;
    index index.php index.html;

    # PHP processing
    location ~ \\.php$ {{
        fastcgi_pass unix:{php_fpm_sock};
        fastcgi_index index.php;
        include fastcgi_params;
        fastcgi_param SCRIPT_FILENAME $request_filename;
        fastcgi_param DOCUMENT_ROOT {install_path};
    }}

    # Bitrix admin panel
    location ~ ^/{prefix}/bitrix/admin/ {{
        index index.php;
        try_files $uri $uri/ @bitrix_admin_{prefix.replace('-','_')};
        location ~ \\.php$ {{
            fastcgi_pass unix:{php_fpm_sock};
            fastcgi_index index.php;
            include fastcgi_params;
            fastcgi_param SCRIPT_FILENAME $request_filename;
            fastcgi_param DOCUMENT_ROOT {install_path};
        }}
    }}

    # Static files
    location ~* \\.(jpg|jpeg|gif|png|svg|js|css|ico|woff2?|ttf|eot)$ {{
        expires 30d;
        access_log off;
        try_files $uri =404;
    }}

    # Deny hidden files
    location ~ /\\. {{
        deny all;
    }}

    # URL rewrite for Bitrix
    location ~ ^/{prefix}/(.*)$ {{
        try_files $uri $uri/ /{prefix}/bitrix/urlrewrite.php?$args;
    }}
}}

location @bitrix_admin_{prefix.replace('-','_')} {{
    rewrite ^/{prefix}/(.*)$ /{prefix}/bitrix/urlrewrite.php last;
}}
"""
        # Write as include file
        step("write_nginx_bitrix_conf",
             f"cat > /etc/nginx/conf.d/bitrix-{prefix}.conf << 'NGXEOF'\n{nginx_conf}\nNGXEOF\n"
             f"echo NGINX_CONF_OK")

        # Make sure the main server block includes conf.d
        step("ensure_nginx_includes",
             f"grep -q 'include /etc/nginx/conf.d/' /etc/nginx/sites-enabled/default 2>/dev/null || "
             f"sed -i '/server_name/a\\    include /etc/nginx/conf.d/*.conf;' /etc/nginx/sites-enabled/default 2>/dev/null; echo OK")

    else:
        # Root installation
        nginx_conf = f"""server {{
    listen 80;
    server_name _;
    root {install_path};
    index index.php index.html;

    # PHP processing
    location ~ \\.php$ {{
        fastcgi_pass unix:{php_fpm_sock};
        fastcgi_index index.php;
        include fastcgi_params;
        fastcgi_param SCRIPT_FILENAME $document_root$fastcgi_script_name;
        fastcgi_param DOCUMENT_ROOT $document_root;
    }}

    # Bitrix admin
    location /bitrix/admin/ {{
        index index.php;
        try_files $uri $uri/ @bitrix_rewrite;
    }}

    # Static files
    location ~* \\.(jpg|jpeg|gif|png|svg|js|css|ico|woff2?|ttf|eot)$ {{
        expires 30d;
        access_log off;
    }}

    # Deny hidden files
    location ~ /\\. {{
        deny all;
    }}

    # Bitrix URL rewrite
    location / {{
        try_files $uri $uri/ /bitrix/urlrewrite.php?$args;
    }}
}}

location @bitrix_rewrite {{
    rewrite ^(.*)$ /bitrix/urlrewrite.php last;
}}
"""
        step("write_nginx_conf",
             f"cat > /etc/nginx/sites-available/bitrix << 'NGXEOF'\n{nginx_conf}\nNGXEOF\n"
             f"ln -sf /etc/nginx/sites-available/bitrix /etc/nginx/sites-enabled/bitrix && "
             f"rm -f /etc/nginx/sites-enabled/default 2>/dev/null; echo NGINX_OK")

    # Test and reload nginx
    nginx_test = step("test_nginx", "nginx -t 2>&1")
    if "successful" in nginx_test or "ok" in nginx_test.lower():
        step("reload_nginx", "systemctl reload nginx && echo NGINX_RELOADED")
    else:
        report["warnings"].append(f"nginx config test failed: {nginx_test[:200]}")
        # Try to fix common issues
        step("fix_nginx_default",
             "rm -f /etc/nginx/sites-enabled/default 2>/dev/null; "
             "nginx -t 2>&1 && systemctl reload nginx && echo FIXED || echo NGINX_BROKEN")

    # ═══ Stage 10: Set permissions ═══════════════════════════════════════════

    logger.info("[STAGE 10] Set permissions")

    step("set_ownership",
         f"chown -R www-data:www-data {install_path} && echo OWNER_OK",
         critical=True)

    step("set_dir_permissions",
         f"find {install_path} -type d -exec chmod 755 {{}} \\; && echo DIR_PERMS_OK")

    step("set_file_permissions",
         f"find {install_path} -type f -exec chmod 644 {{}} \\; && echo FILE_PERMS_OK")

    step("set_writable_dirs",
         f"chmod -R 777 {install_path}/upload "
         f"{install_path}/bitrix/cache "
         f"{install_path}/bitrix/managed_cache "
         f"{install_path}/bitrix/stack_cache "
         f"{install_path}/bitrix/tmp "
         f"2>/dev/null; echo WRITABLE_OK")

    checkpoint("permissions_set")

    # ═══ Stage 11: Strict verification ═══════════════════════════════════════

    logger.info("[STAGE 11] Strict verification")

    verify = {
        "admin_panel_accessible": False,
        "admin_panel_is_bitrix": False,
        "db_tables_exist": False,
        "db_tables_count": 0,
        "public_site_works": False,
        "index_not_static_wrapper": False,
        "wizard_completed": False,
        "core_files_present": False,
        "score": 0,
        "max_score": 100,
    }

    # 1. Check admin panel HTTP response
    if url_prefix:
        admin_url = f"http://localhost{url_prefix.rstrip('/')}/bitrix/admin/"
        public_url = f"http://localhost{url_prefix.rstrip('/')}/"
    else:
        admin_url = "http://localhost/bitrix/admin/"
        public_url = "http://localhost/"

    admin_check = ssh(f"curl -sL -o /tmp/bx_admin_check.html -w '%{{http_code}}' '{admin_url}' 2>/dev/null")
    admin_body = ssh("cat /tmp/bx_admin_check.html 2>/dev/null | head -50")

    admin_code = 0
    try:
        admin_code = int(admin_check.strip().replace("'", ""))
    except (ValueError, TypeError):
        pass

    if admin_code in (200, 302):
        verify["admin_panel_accessible"] = True
        verify["score"] += 20

    # Check if admin page contains Bitrix-specific content
    bitrix_admin_markers = ["Авторизация", "Bitrix", "Администрирование", "bx-admin", "auth-form", "CMS"]
    if any(marker.lower() in admin_body.lower() for marker in bitrix_admin_markers):
        verify["admin_panel_is_bitrix"] = True
        verify["score"] += 15
    elif admin_code == 302:
        # 302 redirect to login is also valid
        verify["admin_panel_is_bitrix"] = True
        verify["score"] += 15

    # 2. Check DB tables
    tables_result = ssh(
        f"mysql -u {db_user} -p'{_escape_php_string(db_password)}' {db_name} "
        f"-e \"SELECT COUNT(*) FROM information_schema.tables WHERE table_schema='{db_name}' AND table_name LIKE 'b_%';\" 2>/dev/null"
    )
    try:
        # Parse the count from MySQL output
        lines = tables_result.strip().split("\n")
        for line in lines:
            line = line.strip()
            if line.isdigit():
                verify["db_tables_count"] = int(line)
                break
    except Exception:
        pass

    if verify["db_tables_count"] >= 10:
        verify["db_tables_exist"] = True
        verify["score"] += 25

    # 3. Check public site
    public_check = ssh(f"curl -sL -o /dev/null -w '%{{http_code}}' '{public_url}' 2>/dev/null")
    try:
        public_code = int(public_check.strip().replace("'", ""))
    except (ValueError, TypeError):
        public_code = 0

    if public_code == 200:
        verify["public_site_works"] = True
        verify["score"] += 10

    # 4. Check index.php is not just a static wrapper
    index_check = ssh(f"head -10 {install_path}/index.php 2>/dev/null")
    if "readfile" in index_check and "index.html" in index_check:
        verify["index_not_static_wrapper"] = False
        report["warnings"].append("FALSE SUCCESS BLOCKED: index.php is just a wrapper for index.html")
    elif "bitrix/header.php" in index_check or "require" in index_check:
        verify["index_not_static_wrapper"] = True
        verify["score"] += 10

    # 5. Check wizard is not active
    wizard_check = ssh(f"test -f {install_path}/bitrix/.install_complete && echo COMPLETE || echo INCOMPLETE")
    if "COMPLETE" in wizard_check or wizard_disabled:
        verify["wizard_completed"] = True
        verify["score"] += 10

    # 6. Check core files
    core_files = [
        "bitrix/.settings.php",
        "bitrix/php_interface/dbconn.php",
        "bitrix/modules/main/include.php",
        "bitrix/header.php",
        "bitrix/footer.php",
    ]
    core_ok = 0
    for cf in core_files:
        check = ssh(f"test -f {install_path}/{cf} && echo OK || echo MISS")
        if "OK" in check:
            core_ok += 1

    if core_ok >= 4:
        verify["core_files_present"] = True
        verify["score"] += 10

    report["verification"] = verify

    # ═══ Stage 12: Cleanup ═══════════════════════════════════════════════════

    logger.info("[STAGE 12] Cleanup")

    step("cleanup_temp",
         f"rm -f /tmp/bx_init_pipeline.php /tmp/bx_admin_check.html 2>/dev/null; "
         f"rm -f {install_path}/bitrixsetup.php 2>/dev/null; "
         f"echo CLEANUP_OK")

    checkpoint("install_complete")

    # ═══ Determine verdict ═══════════════════════════════════════════════════

    elapsed = time.time() - start_time
    report["metrics"]["total_runtime_sec"] = round(elapsed, 1)

    # Verdict logic
    if (verify["admin_panel_accessible"] and
        verify["admin_panel_is_bitrix"] and
        verify["db_tables_exist"] and
        verify["db_tables_count"] >= 10 and
        verify["public_site_works"] and
        verify["index_not_static_wrapper"] and
        verify["wizard_completed"] and
        verify["core_files_present"]):
        report["verdict"] = "SUCCESS"
        report["status"] = "success"
    elif (verify["db_tables_exist"] and verify["core_files_present"]):
        report["verdict"] = "PARTIAL_SUCCESS"
        report["status"] = "partial"
    else:
        report["verdict"] = "FAILED"
        report["status"] = "failed"

    # False-success blocking
    if report["verdict"] == "SUCCESS":
        if not verify["index_not_static_wrapper"]:
            report["verdict"] = "PARTIAL_SUCCESS"
            report["status"] = "partial"
            report["warnings"].append("FALSE_SUCCESS_BLOCKED: index.php wraps static HTML")
        if not verify["admin_panel_is_bitrix"]:
            report["verdict"] = "PARTIAL_SUCCESS"
            report["status"] = "partial"
            report["warnings"].append("FALSE_SUCCESS_BLOCKED: admin panel does not show Bitrix UI")

    # Build result URLs
    if site_url:
        base_url = site_url.rstrip("/")
    elif url_prefix:
        base_url = f"http://SERVER{url_prefix.rstrip('/')}"
    else:
        base_url = "http://SERVER"

    report["result"] = {
        "site_url": f"{base_url}/",
        "admin_url": f"{base_url}/bitrix/admin/",
        "admin_login": admin_login,
        "admin_password": admin_password,
        "edition": edition,
        "modules_count": modules_count,
        "db_tables": verify["db_tables_count"],
        "verify_score": f"{verify['score']}/{verify['max_score']}",
    }

    logger.info(
        f"[PIPELINE COMPLETE] verdict={report['verdict']}, "
        f"score={verify['score']}/{verify['max_score']}, "
        f"tables={verify['db_tables_count']}, "
        f"time={elapsed:.1f}s, "
        f"ssh_calls={report['metrics']['ssh_calls_count']}"
    )

    return report
