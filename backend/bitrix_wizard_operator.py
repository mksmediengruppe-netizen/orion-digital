"""
Bitrix Wizard Operator — Автоматизация веб-установщика Битрикс.
Проходит шаги bitrixsetup.php через HTTP запросы / browser.
Выход: wizard_report.json
"""
import json
import logging
import re
import time
from typing import Callable, Optional

logger = logging.getLogger(__name__)

WIZARD_STEPS = [
    "license_agreement",
    "environment_check",
    "database_setup",
    "site_settings",
    "module_selection",
    "installation",
    "admin_creation",
    "finish",
]


def run_wizard(
    url: str,
    db_name: str,
    db_user: str,
    db_password: str,
    admin_login: str = "admin",
    admin_password: str = "",
    admin_email: str = "admin@example.com",
    site_name: str = "Новый сайт",
    ssh_fn: Optional[Callable] = None,
    browser_fn: Optional[Callable] = None,
    edition: str = "start",
) -> dict:
    """
    Проходит установщик Битрикс.

    Args:
        url: URL сервера (http://domain.com)
        db_name: Имя БД
        db_user: Пользователь БД
        db_password: Пароль БД
        admin_login: Логин администратора
        admin_password: Пароль администратора
        admin_email: Email администратора
        site_name: Название сайта
        ssh_fn: SSH функция
        browser_fn: Браузер функция
        edition: Редакция (start, standard, business)

    Returns:
        dict: Отчёт о прохождении визарда
    """
    if not admin_password:
        import secrets
        admin_password = secrets.token_urlsafe(12)

    report = {
        "status": "running",
        "url": url,
        "edition": edition,
        "steps_completed": [],
        "steps_failed": [],
        "admin_credentials": {
            "login": admin_login,
            "password": admin_password,
            "email": admin_email,
        },
        "errors": [],
    }

    setup_url = f"{url.rstrip('/')}/bitrixsetup.php"

    # Step 1: Check setup page accessible
    if ssh_fn:
        result = str(ssh_fn(f"curl -sL -o /dev/null -w '%{{http_code}}' '{setup_url}'")).strip()
        if result != "200":
            report["status"] = "failed"
            report["errors"].append(f"bitrixsetup.php not accessible: HTTP {result}")
            return report

    # Step 2: Accept license
    _wizard_step(report, "license_agreement",
                 f"curl -sL -X POST -d 'license_agreement=Y&step=2' '{setup_url}'", ssh_fn)

    # Step 3: Environment check (auto-pass)
    _wizard_step(report, "environment_check",
                 f"curl -sL -X POST -d 'step=3' '{setup_url}'", ssh_fn)

    # Step 4: Database setup
    db_data = (
        f"step=4&dbType=mysql&dbHost=localhost&dbName={db_name}"
        f"&dbLogin={db_user}&dbPassword={db_password}"
        f"&create_db=N&create_user=N"
    )
    _wizard_step(report, "database_setup",
                 f"curl -sL -X POST -d '{db_data}' '{setup_url}'", ssh_fn)

    # Step 5: Site settings
    site_data = (
        f"step=5&siteName={site_name}&email={admin_email}"
        f"&edition={edition}"
    )
    _wizard_step(report, "site_settings",
                 f"curl -sL -X POST -d '{site_data}' '{setup_url}'", ssh_fn)

    # Step 6: Module selection (install all default)
    _wizard_step(report, "module_selection",
                 f"curl -sL -X POST -d 'step=6&install_modules=Y' '{setup_url}'", ssh_fn)

    # Step 7: Wait for installation
    logger.info("[BitrixWizard] Waiting for installation (this may take several minutes)...")
    for attempt in range(30):
        time.sleep(10)
        if ssh_fn:
            check = str(ssh_fn(f"test -f {_install_path(url)}/bitrix/modules/main/include.php && echo 'INSTALLED' || echo 'WAITING'"))
            if "INSTALLED" in check:
                report["steps_completed"].append("installation")
                break
    else:
        report["steps_failed"].append("installation")
        report["errors"].append("Installation timeout after 5 minutes")

    # Step 8: Create admin
    admin_data = (
        f"step=8&admin_login={admin_login}&admin_password={admin_password}"
        f"&admin_password_confirm={admin_password}&admin_email={admin_email}"
    )
    _wizard_step(report, "admin_creation",
                 f"curl -sL -X POST -d '{admin_data}' '{setup_url}'", ssh_fn)

    # Step 9: Cleanup
    if ssh_fn:
        ssh_fn(f"rm -f {_install_path(url)}/bitrixsetup.php")
        report["steps_completed"].append("cleanup")

    # Final check
    if ssh_fn:
        check = str(ssh_fn(f"curl -sL -o /dev/null -w '%{{http_code}}' '{url}'")).strip()
        if check == "200":
            report["steps_completed"].append("finish")
            report["status"] = "success"
        else:
            report["status"] = "partial"
            report["errors"].append(f"Site returns HTTP {check} after install")
    else:
        report["status"] = "partial"

    logger.info(f"[BitrixWizard] Wizard {report['status']}: "
                f"{len(report['steps_completed'])} completed, {len(report['steps_failed'])} failed")
    return report


def _wizard_step(report, name, cmd, ssh_fn):
    """Выполняет шаг визарда."""
    if not ssh_fn:
        report["steps_failed"].append(name)
        return
    try:
        result = str(ssh_fn(cmd))
        if "error" in result.lower() and "fatal" in result.lower():
            report["steps_failed"].append(name)
            report["errors"].append(f"{name}: {result[:200]}")
        else:
            report["steps_completed"].append(name)
    except Exception as e:
        report["steps_failed"].append(name)
        report["errors"].append(f"{name}: {e}")


def _install_path(url):
    """Определяет путь установки по URL."""
    return "/var/www/html"


def save_report(report: dict, path: str = "wizard_report.json"):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    return path
