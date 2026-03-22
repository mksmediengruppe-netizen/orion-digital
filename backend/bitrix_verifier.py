"""
Bitrix Verifier — Проверка здоровья установки Битрикс.
Проверяет: ядро, модули, БД, PHP, права, cron, .settings.php.
Выход: bitrix_health.json
"""
import json
import logging
import re
import time
from typing import Callable, Optional

logger = logging.getLogger(__name__)

CRITICAL_FILES = [
    "bitrix/.settings.php",
    "bitrix/php_interface/dbconn.php",
    "bitrix/modules/main/include.php",
    "bitrix/header.php",
    "bitrix/footer.php",
    ".htaccess",
]

CRITICAL_MODULES = [
    "main", "iblock", "catalog", "sale", "search", "form",
    "fileman", "socialnetwork", "blog", "subscribe",
]

REQUIRED_PHP_MODULES = [
    "mbstring", "curl", "gd", "xml", "zip", "json", "mysql",
]

WRITABLE_DIRS = [
    "bitrix/cache", "bitrix/managed_cache", "bitrix/stack_cache",
    "bitrix/tmp", "upload",
]


def verify_bitrix(
    ssh_fn: Callable,
    install_path: str = "/var/www/html",
    url: str = "",
) -> dict:
    """
    Полная проверка здоровья Битрикс.

    Args:
        ssh_fn: SSH функция
        install_path: Путь установки
        url: URL сайта (опционально)

    Returns:
        dict: Отчёт о здоровье
    """
    health = {
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "install_path": install_path,
        "url": url,
        "checks": {},
        "score": 0,
        "max_score": 0,
        "status": "",
        "critical_issues": [],
        "warnings": [],
    }

    # 1. Core files
    health["checks"]["core_files"] = _check_core_files(ssh_fn, install_path)

    # 2. Database connection
    health["checks"]["database"] = _check_database(ssh_fn, install_path)

    # 3. PHP configuration
    health["checks"]["php_config"] = _check_php(ssh_fn)

    # 4. Installed modules
    health["checks"]["modules"] = _check_modules(ssh_fn, install_path)

    # 5. File permissions
    health["checks"]["permissions"] = _check_permissions(ssh_fn, install_path)

    # 6. Cron agent
    health["checks"]["cron"] = _check_cron(ssh_fn, install_path)

    # 7. .settings.php validity
    health["checks"]["settings"] = _check_settings(ssh_fn, install_path)

    # 8. Disk space
    health["checks"]["disk"] = _check_disk(ssh_fn, install_path)

    # 9. Web server
    health["checks"]["web_server"] = _check_web_server(ssh_fn)

    # 10. Site accessible
    if url:
        health["checks"]["site_access"] = _check_site_access(ssh_fn, url)

    # Calculate score
    total = 0
    max_total = 0
    for name, check in health["checks"].items():
        s = check.get("score", 0)
        m = check.get("max_score", 10)
        total += s
        max_total += m
        if not check.get("ok") and check.get("severity") == "critical":
            health["critical_issues"].append(f"{name}: {check.get('details', '')}")
        elif not check.get("ok"):
            health["warnings"].append(f"{name}: {check.get('details', '')}")

    health["score"] = total
    health["max_score"] = max_total
    pct = (total / max_total * 100) if max_total > 0 else 0
    health["percentage"] = round(pct, 1)

    if len(health["critical_issues"]) > 0:
        health["status"] = "CRITICAL"
    elif pct >= 80:
        health["status"] = "HEALTHY"
    elif pct >= 60:
        health["status"] = "WARNING"
    else:
        health["status"] = "UNHEALTHY"

    logger.info(f"[BitrixVerifier] Status: {health['status']} ({pct:.0f}%)")
    return health


def _check_core_files(ssh_fn, path):
    found = 0
    missing = []
    for f in CRITICAL_FILES:
        r = str(ssh_fn(f"test -f {path}/{f} && echo 'OK' || echo 'MISS'"))
        if "OK" in r:
            found += 1
        else:
            missing.append(f)
    total = len(CRITICAL_FILES)
    return {
        "ok": found == total,
        "score": round(15 * found / total),
        "max_score": 15,
        "severity": "critical" if missing else "ok",
        "details": f"{found}/{total} files" + (f", missing: {', '.join(missing)}" if missing else ""),
    }


def _check_database(ssh_fn, path):
    try:
        r = str(ssh_fn(
            f"php -r \"require_once '{path}/bitrix/php_interface/dbconn.php'; "
            f"\\$c = new mysqli(\\$DBHost, \\$DBLogin, \\$DBPassword, \\$DBName); "
            f"echo \\$c->connect_error ? 'FAIL:'.\\$c->connect_error : 'OK';\" 2>/dev/null"
        ))
        ok = "OK" in r
        return {
            "ok": ok,
            "score": 15 if ok else 0,
            "max_score": 15,
            "severity": "critical" if not ok else "ok",
            "details": "DB connection OK" if ok else f"DB connection failed: {r[:100]}",
        }
    except Exception as e:
        return {"ok": False, "score": 0, "max_score": 15, "severity": "critical", "details": str(e)}


def _check_php(ssh_fn):
    found = []
    missing = []
    for mod in REQUIRED_PHP_MODULES:
        r = str(ssh_fn(f"php -m 2>/dev/null | grep -i {mod}"))
        if mod.lower() in r.lower():
            found.append(mod)
        else:
            missing.append(mod)
    total = len(REQUIRED_PHP_MODULES)
    return {
        "ok": len(missing) == 0,
        "score": round(10 * len(found) / total),
        "max_score": 10,
        "severity": "critical" if len(missing) > 2 else "warning",
        "details": f"{len(found)}/{total} PHP modules" + (f", missing: {', '.join(missing)}" if missing else ""),
    }


def _check_modules(ssh_fn, path):
    found = []
    missing = []
    for mod in CRITICAL_MODULES:
        r = str(ssh_fn(f"test -d {path}/bitrix/modules/{mod} && echo 'OK' || echo 'MISS'"))
        if "OK" in r:
            found.append(mod)
        else:
            missing.append(mod)
    total = len(CRITICAL_MODULES)
    return {
        "ok": len(missing) <= 2,
        "score": round(10 * len(found) / total),
        "max_score": 10,
        "severity": "warning",
        "details": f"{len(found)}/{total} modules installed" + (f", missing: {', '.join(missing)}" if missing else ""),
    }


def _check_permissions(ssh_fn, path):
    ok_dirs = 0
    problems = []
    for d in WRITABLE_DIRS:
        r = str(ssh_fn(f"test -w {path}/{d} && echo 'OK' || echo 'FAIL'"))
        if "OK" in r:
            ok_dirs += 1
        else:
            problems.append(d)
    total = len(WRITABLE_DIRS)
    return {
        "ok": ok_dirs == total,
        "score": round(10 * ok_dirs / total),
        "max_score": 10,
        "severity": "warning",
        "details": f"{ok_dirs}/{total} writable" + (f", problems: {', '.join(problems)}" if problems else ""),
    }


def _check_cron(ssh_fn, path):
    r = str(ssh_fn("crontab -l 2>/dev/null | grep -i bitrix"))
    has_cron = "bitrix" in r.lower() or "cron_events" in r.lower()
    return {
        "ok": has_cron,
        "score": 5 if has_cron else 0,
        "max_score": 5,
        "severity": "warning",
        "details": "Bitrix cron configured" if has_cron else "Bitrix cron NOT configured",
    }


def _check_settings(ssh_fn, path):
    r = str(ssh_fn(f"php -r \"var_export(include '{path}/bitrix/.settings.php');\" 2>/dev/null"))
    ok = "array" in r.lower() and "connections" in r.lower()
    return {
        "ok": ok,
        "score": 10 if ok else 0,
        "max_score": 10,
        "severity": "critical" if not ok else "ok",
        "details": ".settings.php valid" if ok else ".settings.php invalid or missing",
    }


def _check_disk(ssh_fn, path):
    r = str(ssh_fn(f"df -h {path} | tail -1"))
    match = re.search(r'(\d+)%', r)
    if match:
        usage = int(match.group(1))
        ok = usage < 90
        return {
            "ok": ok,
            "score": 5 if usage < 80 else 3 if usage < 90 else 0,
            "max_score": 5,
            "severity": "critical" if usage >= 95 else "warning" if usage >= 90 else "ok",
            "details": f"Disk usage: {usage}%",
        }
    return {"ok": True, "score": 3, "max_score": 5, "severity": "ok", "details": "Could not determine disk usage"}


def _check_web_server(ssh_fn):
    r_apache = str(ssh_fn("systemctl is-active apache2 2>/dev/null"))
    r_nginx = str(ssh_fn("systemctl is-active nginx 2>/dev/null"))
    apache_ok = "active" in r_apache
    nginx_ok = "active" in r_nginx
    ok = apache_ok or nginx_ok
    server = "apache" if apache_ok else "nginx" if nginx_ok else "none"
    return {
        "ok": ok,
        "score": 10 if ok else 0,
        "max_score": 10,
        "severity": "critical" if not ok else "ok",
        "details": f"Web server: {server} ({'running' if ok else 'not running'})",
    }


def _check_site_access(ssh_fn, url):
    try:
        r = str(ssh_fn(f"curl -sL -o /dev/null -w '%{{http_code}}' '{url}'")).strip()
        code = int(r) if r.isdigit() else 0
        ok = code == 200
        return {
            "ok": ok,
            "score": 10 if ok else 0,
            "max_score": 10,
            "severity": "critical" if not ok else "ok",
            "details": f"Site HTTP {code}",
        }
    except Exception as e:
        return {"ok": False, "score": 0, "max_score": 10, "severity": "critical", "details": str(e)}


def save_health(health: dict, path: str = "bitrix_health.json"):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(health, f, ensure_ascii=False, indent=2)
    return path
