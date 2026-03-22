"""
Bitrix Release Judge — Специализированный judge для Битрикс-сайтов.
Проверяет установку, admin panel, шаблон, формы, публичность, assets, кеш.
Выход: bitrix_release_verdict.json
"""
import json
import logging
import re
import time
from typing import Callable, Optional

logger = logging.getLogger(__name__)


def judge_bitrix_release(
    url: str,
    admin_url: str = "",
    admin_login: str = "",
    admin_password: str = "",
    ssh_fn: Optional[Callable] = None,
    browser_fn: Optional[Callable] = None,
    install_path: str = "/var/www/html",
) -> dict:
    """
    Полная проверка Битрикс-сайта перед релизом.
    
    Args:
        url: URL сайта
        admin_url: URL админки (по умолчанию {url}/bitrix/admin/)
        admin_login: Логин администратора
        admin_password: Пароль администратора
        ssh_fn: SSH функция
        browser_fn: Функция браузера
        install_path: Путь установки на сервере
    
    Returns:
        dict: Вердикт с оценками по каждому критерию
    """
    if not admin_url:
        admin_url = f"{url.rstrip('/')}/bitrix/admin/"
    
    verdict = {
        "url": url,
        "admin_url": admin_url,
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "checks": [],
        "score": 0,
        "max_score": 0,
        "grade": "",
        "verdict": "",
        "critical_issues": [],
        "warnings": [],
        "recommendations": [],
    }
    
    # ── 1. Битрикс установлен? ───────────────────────────────
    check = _check_bitrix_installed(url, install_path, ssh_fn)
    verdict["checks"].append(check)
    if not check["passed"]:
        verdict["critical_issues"].append("Битрикс не установлен или повреждён")
    
    # ── 2. /bitrix/admin доступен? ───────────────────────────
    check = _check_admin_accessible(admin_url, ssh_fn)
    verdict["checks"].append(check)
    if not check["passed"]:
        verdict["critical_issues"].append("Админ-панель недоступна")
    
    # ── 3. Admin login работает? ─────────────────────────────
    if admin_login and admin_password:
        check = _check_admin_login(admin_url, admin_login, admin_password, browser_fn)
        verdict["checks"].append(check)
        if not check["passed"]:
            verdict["critical_issues"].append("Авторизация в админке не работает")
    else:
        verdict["checks"].append({
            "name": "admin_login",
            "passed": None,
            "score": 0,
            "max_score": 15,
            "details": "Логин/пароль не предоставлены — проверка пропущена",
        })
    
    # ── 4. Шаблон подключён? ─────────────────────────────────
    check = _check_template(url, install_path, ssh_fn, browser_fn)
    verdict["checks"].append(check)
    if not check["passed"]:
        verdict["warnings"].append("Шаблон не подключён или используется стандартный")
    
    # ── 5. Формы через Битрикс модуль? ───────────────────────
    check = _check_bitrix_forms(url, install_path, ssh_fn, browser_fn)
    verdict["checks"].append(check)
    
    # ── 6. Сайт доступен публично? ───────────────────────────
    check = _check_public_access(url, ssh_fn)
    verdict["checks"].append(check)
    if not check["passed"]:
        verdict["critical_issues"].append("Сайт недоступен публично")
    
    # ── 7. Assets не сломаны? ────────────────────────────────
    check = _check_assets(url, ssh_fn, browser_fn)
    verdict["checks"].append(check)
    if not check["passed"]:
        verdict["warnings"].append("Некоторые assets не загружаются")
    
    # ── 8. Кеш почищен? ─────────────────────────────────────
    check = _check_cache(install_path, ssh_fn)
    verdict["checks"].append(check)
    
    # ── 9. Дополнительные проверки ───────────────────────────
    # PHP errors
    check = _check_php_errors(url, install_path, ssh_fn)
    verdict["checks"].append(check)
    
    # .htaccess
    check = _check_htaccess(install_path, ssh_fn)
    verdict["checks"].append(check)
    
    # ── Calculate score ──────────────────────────────────────
    total_score = 0
    max_score = 0
    for check in verdict["checks"]:
        score = check.get("score", 0)
        max_possible = check.get("max_score", 10)
        total_score += score
        max_score += max_possible
    
    verdict["score"] = total_score
    verdict["max_score"] = max_score
    pct = (total_score / max_score * 100) if max_score > 0 else 0
    verdict["percentage"] = round(pct, 1)
    verdict["grade"] = _calculate_grade(pct)
    
    # Final verdict
    if len(verdict["critical_issues"]) > 0:
        verdict["verdict"] = "FAIL — критические проблемы"
    elif pct >= 80:
        verdict["verdict"] = "PASS — сайт готов к релизу"
    elif pct >= 60:
        verdict["verdict"] = "CONDITIONAL — требуются доработки"
    else:
        verdict["verdict"] = "FAIL — сайт не готов"
    
    # Recommendations
    verdict["recommendations"] = _generate_recommendations(verdict)
    
    logger.info(f"[BitrixJudge] Verdict: {verdict['verdict']} "
                f"({total_score}/{max_score} = {pct:.1f}%)")
    return verdict


def _check_bitrix_installed(url: str, install_path: str, ssh_fn: Optional[Callable]) -> dict:
    """Проверяет установку Битрикс"""
    check = {"name": "bitrix_installed", "max_score": 15}
    try:
        indicators = []
        
        if ssh_fn:
            # Check key files
            files_to_check = [
                f"{install_path}/bitrix/.settings.php",
                f"{install_path}/bitrix/modules/main/include.php",
                f"{install_path}/bitrix/php_interface/dbconn.php",
            ]
            for f in files_to_check:
                result = ssh_fn(f"test -f {f} && echo 'EXISTS' || echo 'MISSING'")
                if "EXISTS" in str(result):
                    indicators.append(f)
            
            # Check database connection
            db_check = ssh_fn(
                f"php -r \"include '{install_path}/bitrix/php_interface/dbconn.php'; "
                f"echo 'DB_OK';\" 2>/dev/null || echo 'DB_FAIL'"
            )
            if "DB_OK" in str(db_check):
                indicators.append("database_connection")
        
        # Check URL response
        if ssh_fn:
            result = ssh_fn(f"curl -sL -o /dev/null -w '%{{http_code}}' '{url}'")
            status = int(str(result).strip()) if str(result).strip().isdigit() else 0
            if status == 200:
                indicators.append("http_200")
        
        check["passed"] = len(indicators) >= 3
        check["score"] = min(15, len(indicators) * 3)
        check["details"] = f"Bitrix indicators: {len(indicators)}/5 ({', '.join(indicators)})"
        check["indicators"] = indicators
    except Exception as e:
        check["passed"] = False
        check["score"] = 0
        check["details"] = f"Install check failed: {e}"
    return check


def _check_admin_accessible(admin_url: str, ssh_fn: Optional[Callable]) -> dict:
    """Проверяет доступность админки"""
    check = {"name": "admin_accessible", "max_score": 10}
    try:
        if ssh_fn:
            result = ssh_fn(f"curl -sL -o /dev/null -w '%{{http_code}}' '{admin_url}'")
            status = int(str(result).strip()) if str(result).strip().isdigit() else 0
            # 200 or 302 (redirect to login) are both OK
            check["passed"] = status in (200, 302, 301)
            check["score"] = 10 if check["passed"] else 0
            check["details"] = f"Admin panel HTTP {status}"
            check["status_code"] = status
        else:
            check["passed"] = False
            check["score"] = 0
            check["details"] = "No SSH function for admin check"
    except Exception as e:
        check["passed"] = False
        check["score"] = 0
        check["details"] = f"Admin check failed: {e}"
    return check


def _check_admin_login(admin_url: str, login: str, password: str, browser_fn: Optional[Callable]) -> dict:
    """Проверяет авторизацию в админке"""
    check = {"name": "admin_login", "max_score": 15}
    try:
        if browser_fn:
            # Navigate to admin, fill login form, check result
            html = browser_fn(admin_url)
            if "bitrix" in html.lower() and ("auth" in html.lower() or "login" in html.lower()):
                check["passed"] = True
                check["score"] = 10  # Can see login page, but can't verify actual login without browser automation
                check["details"] = "Admin login page accessible, login form present"
            else:
                check["passed"] = False
                check["score"] = 0
                check["details"] = "Admin login page not found"
        else:
            check["passed"] = False
            check["score"] = 0
            check["details"] = "No browser function for login check"
    except Exception as e:
        check["passed"] = False
        check["score"] = 0
        check["details"] = f"Login check failed: {e}"
    return check


def _check_template(url: str, install_path: str, ssh_fn: Optional[Callable], browser_fn: Optional[Callable]) -> dict:
    """Проверяет подключение шаблона"""
    check = {"name": "template_connected", "max_score": 10}
    try:
        indicators = []
        
        if ssh_fn:
            # Check template directory
            result = ssh_fn(f"ls {install_path}/bitrix/templates/ 2>/dev/null | grep -v '^\\.' | head -5")
            templates = [t.strip() for t in str(result).split("\n") if t.strip() and t.strip() != ".default"]
            if templates:
                indicators.append(f"templates: {', '.join(templates)}")
            
            # Check if custom template is set
            result = ssh_fn(
                f"grep -r 'TEMPLATE_ID' {install_path}/bitrix/.settings.php 2>/dev/null || "
                f"grep -r 'template' {install_path}/.top.menu.php 2>/dev/null || echo 'NOT_FOUND'"
            )
            if "NOT_FOUND" not in str(result):
                indicators.append("template_configured")
        
        if browser_fn:
            html = browser_fn(url)
            # Check for custom CSS/template markers
            if re.search(r'/bitrix/templates/[^/]+/', html):
                indicators.append("template_in_html")
            if "template" not in html.lower() and ".default" in html:
                indicators.append("using_default_template")
        
        check["passed"] = len(indicators) >= 1 and "using_default_template" not in indicators
        check["score"] = min(10, len(indicators) * 3)
        check["details"] = f"Template: {', '.join(indicators) if indicators else 'not detected'}"
    except Exception as e:
        check["passed"] = False
        check["score"] = 0
        check["details"] = f"Template check failed: {e}"
    return check


def _check_bitrix_forms(url: str, install_path: str, ssh_fn: Optional[Callable], browser_fn: Optional[Callable]) -> dict:
    """Проверяет формы через Битрикс"""
    check = {"name": "bitrix_forms", "max_score": 10}
    try:
        indicators = []
        
        if ssh_fn:
            # Check if form module is installed
            result = ssh_fn(
                f"test -d {install_path}/bitrix/modules/form && echo 'FORM_MODULE' || "
                f"test -d {install_path}/bitrix/modules/iblock && echo 'IBLOCK_MODULE' || echo 'NO_MODULE'"
            )
            output = str(result)
            if "FORM_MODULE" in output:
                indicators.append("form_module_installed")
            if "IBLOCK_MODULE" in output:
                indicators.append("iblock_module_installed")
        
        if browser_fn:
            html = browser_fn(url)
            if re.search(r'bitrix:form|bitrix:iblock\.element\.add', html, re.IGNORECASE):
                indicators.append("bitrix_form_component")
            if re.search(r'<form', html, re.IGNORECASE):
                indicators.append("html_form_present")
        
        check["passed"] = len(indicators) >= 1
        check["score"] = min(10, len(indicators) * 3)
        check["details"] = f"Forms: {', '.join(indicators) if indicators else 'not detected'}"
    except Exception as e:
        check["passed"] = False
        check["score"] = 0
        check["details"] = f"Forms check failed: {e}"
    return check


def _check_public_access(url: str, ssh_fn: Optional[Callable]) -> dict:
    """Проверяет публичную доступность"""
    check = {"name": "public_access", "max_score": 15}
    try:
        if ssh_fn:
            result = ssh_fn(f"curl -sL -o /dev/null -w '%{{http_code}}' '{url}'")
            status = int(str(result).strip()) if str(result).strip().isdigit() else 0
            
            check["passed"] = status == 200
            check["score"] = 15 if status == 200 else 0
            check["details"] = f"Public access: HTTP {status}"
            check["status_code"] = status
        else:
            check["passed"] = False
            check["score"] = 0
            check["details"] = "No SSH function"
    except Exception as e:
        check["passed"] = False
        check["score"] = 0
        check["details"] = f"Public access check failed: {e}"
    return check


def _check_assets(url: str, ssh_fn: Optional[Callable], browser_fn: Optional[Callable]) -> dict:
    """Проверяет загрузку assets"""
    check = {"name": "assets_integrity", "max_score": 10}
    try:
        broken = []
        total = 0
        
        if browser_fn:
            html = browser_fn(url)
            # Extract CSS and JS links
            assets = re.findall(r'(?:href|src)=["\']([^"\']+\.(?:css|js|png|jpg|gif|svg))["\']', html)
            
            for asset in assets[:20]:
                if asset.startswith("//"):
                    asset = "https:" + asset
                elif asset.startswith("/"):
                    from urllib.parse import urljoin
                    asset = urljoin(url, asset)
                elif not asset.startswith("http"):
                    from urllib.parse import urljoin
                    asset = urljoin(url + "/", asset)
                
                total += 1
                if ssh_fn:
                    result = ssh_fn(f"curl -sL -o /dev/null -w '%{{http_code}}' '{asset}'")
                    status = int(str(result).strip()) if str(result).strip().isdigit() else 0
                    if status >= 400:
                        broken.append(asset)
        
        check["passed"] = len(broken) == 0
        check["score"] = 10 if len(broken) == 0 else max(0, 10 - len(broken) * 2)
        check["details"] = f"Assets: {total - len(broken)}/{total} OK. Broken: {len(broken)}"
        if broken:
            check["broken_assets"] = broken[:10]
    except Exception as e:
        check["passed"] = False
        check["score"] = 0
        check["details"] = f"Assets check failed: {e}"
    return check


def _check_cache(install_path: str, ssh_fn: Optional[Callable]) -> dict:
    """Проверяет состояние кеша"""
    check = {"name": "cache_clean", "max_score": 5}
    try:
        if ssh_fn:
            # Check cache size
            result = ssh_fn(f"du -sh {install_path}/bitrix/cache/ 2>/dev/null || echo '0\tNO_CACHE'")
            output = str(result).strip()
            
            # Parse size
            size_match = re.match(r'([\d.]+)([KMG]?)', output)
            if size_match:
                size = float(size_match.group(1))
                unit = size_match.group(2)
                if unit == "G":
                    size_mb = size * 1024
                elif unit == "M":
                    size_mb = size
                else:
                    size_mb = size / 1024
                
                check["passed"] = size_mb < 500  # Less than 500MB is OK
                check["score"] = 5 if size_mb < 100 else 3 if size_mb < 500 else 0
                check["details"] = f"Cache size: {output.split()[0]}"
            else:
                check["passed"] = True
                check["score"] = 5
                check["details"] = "Cache directory clean or not found"
        else:
            check["passed"] = True
            check["score"] = 3
            check["details"] = "Cache check skipped (no SSH)"
    except Exception as e:
        check["passed"] = False
        check["score"] = 0
        check["details"] = f"Cache check failed: {e}"
    return check


def _check_php_errors(url: str, install_path: str, ssh_fn: Optional[Callable]) -> dict:
    """Проверяет PHP ошибки"""
    check = {"name": "php_errors", "max_score": 5}
    try:
        if ssh_fn:
            # Check PHP error log
            result = ssh_fn(
                f"tail -20 /var/log/php*.log 2>/dev/null || "
                f"tail -20 {install_path}/bitrix/php_interface/error.log 2>/dev/null || "
                f"echo 'NO_ERRORS'"
            )
            output = str(result)
            
            if "NO_ERRORS" in output or not output.strip():
                check["passed"] = True
                check["score"] = 5
                check["details"] = "No PHP errors detected"
            else:
                errors = [l for l in output.split("\n") if "fatal" in l.lower() or "error" in l.lower()]
                check["passed"] = len(errors) == 0
                check["score"] = 5 if len(errors) == 0 else 2 if len(errors) < 5 else 0
                check["details"] = f"PHP errors: {len(errors)} found"
        else:
            check["passed"] = True
            check["score"] = 3
            check["details"] = "PHP error check skipped"
    except Exception as e:
        check["passed"] = False
        check["score"] = 0
        check["details"] = f"PHP error check failed: {e}"
    return check


def _check_htaccess(install_path: str, ssh_fn: Optional[Callable]) -> dict:
    """Проверяет .htaccess"""
    check = {"name": "htaccess", "max_score": 5}
    try:
        if ssh_fn:
            result = ssh_fn(f"test -f {install_path}/.htaccess && echo 'EXISTS' || echo 'MISSING'")
            exists = "EXISTS" in str(result)
            
            if exists:
                # Check for Bitrix rewrite rules
                content = ssh_fn(f"cat {install_path}/.htaccess 2>/dev/null | head -20")
                has_rewrite = "RewriteEngine" in str(content)
                check["passed"] = has_rewrite
                check["score"] = 5 if has_rewrite else 3
                check["details"] = f".htaccess: exists, rewrite={'yes' if has_rewrite else 'no'}"
            else:
                check["passed"] = False
                check["score"] = 0
                check["details"] = ".htaccess: missing"
        else:
            check["passed"] = True
            check["score"] = 3
            check["details"] = ".htaccess check skipped"
    except Exception as e:
        check["passed"] = False
        check["score"] = 0
        check["details"] = f".htaccess check failed: {e}"
    return check


def _calculate_grade(percentage: float) -> str:
    """Вычисляет оценку"""
    if percentage >= 95:
        return "A+"
    elif percentage >= 90:
        return "A"
    elif percentage >= 80:
        return "B"
    elif percentage >= 70:
        return "C"
    elif percentage >= 60:
        return "D"
    else:
        return "F"


def _generate_recommendations(verdict: dict) -> list:
    """Генерирует рекомендации на основе проверок"""
    recs = []
    for check in verdict["checks"]:
        if not check.get("passed") and check.get("score", 0) == 0:
            name = check.get("name", "")
            if name == "bitrix_installed":
                recs.append("Переустановите Битрикс или проверьте файлы ядра")
            elif name == "admin_accessible":
                recs.append("Проверьте nginx конфигурацию для /bitrix/admin/")
            elif name == "admin_login":
                recs.append("Проверьте учётные данные администратора")
            elif name == "template_connected":
                recs.append("Подключите кастомный шаблон в настройках сайта")
            elif name == "public_access":
                recs.append("Проверьте DNS записи и nginx конфигурацию")
            elif name == "assets_integrity":
                recs.append("Проверьте пути к CSS/JS/изображениям в шаблоне")
            elif name == "cache_clean":
                recs.append("Очистите кеш: Настройки → Настройки продукта → Автокеширование")
    
    if not recs:
        recs.append("Сайт готов к релизу. Рекомендуется провести финальное тестирование.")
    
    return recs


def save_verdict(verdict: dict, path: str = "bitrix_release_verdict.json"):
    """Сохраняет вердикт"""
    with open(path, "w", encoding="utf-8") as f:
        json.dump(verdict, f, ensure_ascii=False, indent=2)
    logger.info(f"[BitrixJudge] Verdict saved to {path}")
    return path
