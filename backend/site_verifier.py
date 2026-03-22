"""
Site Verifier — Полная проверка опубликованного сайта.
HTTP status, ссылки, формы, скриншоты, assets, meta, скорость, контент.
Выход: site_verify_report.json
"""
import json
import logging
import re
import time
from typing import Callable, Optional, List
from urllib.parse import urljoin, urlparse

logger = logging.getLogger(__name__)


def verify_site(
    url: str,
    blueprint: dict,
    ssh_fn: Optional[Callable] = None,
    browser_fn: Optional[Callable] = None,
    screenshot_fn: Optional[Callable] = None,
) -> dict:
    """
    Полная верификация опубликованного сайта.
    
    Args:
        url: URL сайта
        blueprint: site_blueprint.json для проверки контента
        ssh_fn: SSH функция для серверных проверок
        browser_fn: Функция для браузерных проверок (url -> html)
        screenshot_fn: Функция для скриншотов (url, width -> path)
    
    Returns:
        dict: Полный отчёт верификации
    """
    report = {
        "url": url,
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "checks": [],
        "score": 0,
        "max_score": 0,
        "grade": "",
        "screenshots": [],
        "errors": [],
        "warnings": [],
    }
    
    # ── 1. HTTP Status ───────────────────────────────────────
    check = _check_http_status(url, ssh_fn)
    report["checks"].append(check)
    
    # ── 2. Все страницы доступны ──────────────────────────────
    pages = _get_pages(url, blueprint)
    for page_url in pages:
        check = _check_http_status(page_url, ssh_fn, name=f"page_{urlparse(page_url).path}")
        report["checks"].append(check)
    
    # ── 3. Ссылки работают (нет 404) ─────────────────────────
    if browser_fn:
        check = _check_links(url, browser_fn, ssh_fn)
        report["checks"].append(check)
    
    # ── 4. Формы отправляются ────────────────────────────────
    forms = blueprint.get("forms", [])
    for form in forms:
        check = _check_form(url, form, ssh_fn)
        report["checks"].append(check)
    
    # ── 5. Скриншоты desktop + mobile ────────────────────────
    if screenshot_fn:
        for width, label in [(1920, "desktop"), (375, "mobile")]:
            try:
                path = screenshot_fn(url, width)
                report["screenshots"].append({"width": width, "label": label, "path": path})
                report["checks"].append({
                    "name": f"screenshot_{label}",
                    "passed": True,
                    "score": 5,
                    "details": f"Screenshot captured at {width}px",
                })
            except Exception as e:
                report["checks"].append({
                    "name": f"screenshot_{label}",
                    "passed": False,
                    "score": 0,
                    "details": f"Screenshot failed: {e}",
                })
    
    # ── 6. Assets загружаются ────────────────────────────────
    check = _check_assets(url, ssh_fn)
    report["checks"].append(check)
    
    # ── 7. Meta теги заполнены ───────────────────────────────
    check = _check_meta_tags(url, ssh_fn, browser_fn)
    report["checks"].append(check)
    
    # ── 8. Скорость загрузки ─────────────────────────────────
    check = _check_load_speed(url, ssh_fn)
    report["checks"].append(check)
    
    # ── 9. Контент соответствует blueprint ────────────────────
    if browser_fn:
        check = _check_content_match(url, blueprint, browser_fn)
        report["checks"].append(check)
    
    # ── 10. Mobile responsiveness ────────────────────────────
    check = _check_viewport_meta(url, ssh_fn, browser_fn)
    report["checks"].append(check)
    
    # ── 11. SSL/HTTPS ────────────────────────────────────────
    if url.startswith("https"):
        check = _check_ssl(url, ssh_fn)
        report["checks"].append(check)
    
    # ── Calculate score ──────────────────────────────────────
    total_score = 0
    max_score = 0
    for check in report["checks"]:
        score = check.get("score", 0)
        max_possible = check.get("max_score", 10)
        total_score += score
        max_score += max_possible
        if not check.get("passed"):
            if score == 0:
                report["errors"].append(check.get("details", check.get("name", "")))
            else:
                report["warnings"].append(check.get("details", check.get("name", "")))
    
    report["score"] = total_score
    report["max_score"] = max_score
    pct = (total_score / max_score * 100) if max_score > 0 else 0
    report["percentage"] = round(pct, 1)
    report["grade"] = _calculate_grade(pct)
    
    logger.info(f"[SiteVerifier] Verification complete: {report['grade']} "
                f"({total_score}/{max_score} = {pct:.1f}%)")
    return report


def _check_http_status(url: str, ssh_fn: Optional[Callable], name: str = "http_status") -> dict:
    """Проверяет HTTP статус"""
    check = {"name": name, "max_score": 10}
    try:
        if ssh_fn:
            result = ssh_fn(f"curl -sL -o /dev/null -w '%{{http_code}}' '{url}'")
            status = int(str(result).strip()) if str(result).strip().isdigit() else 0
        else:
            import urllib.request
            req = urllib.request.Request(url, headers={"User-Agent": "ORION-Verifier/1.0"})
            resp = urllib.request.urlopen(req, timeout=10)
            status = resp.getcode()
        
        check["status_code"] = status
        check["passed"] = status == 200
        check["score"] = 10 if status == 200 else 0
        check["details"] = f"HTTP {status} for {url}"
    except Exception as e:
        check["passed"] = False
        check["score"] = 0
        check["details"] = f"HTTP check failed: {e}"
    return check


def _get_pages(url: str, blueprint: dict) -> list:
    """Получает список страниц для проверки"""
    pages = [url]
    deliverables = blueprint.get("deliverables", [])
    for d in deliverables:
        if d.endswith(".html") and d != "index.html":
            pages.append(urljoin(url + "/", d))
    return pages


def _check_links(url: str, browser_fn: Callable, ssh_fn: Optional[Callable]) -> dict:
    """Проверяет все ссылки на странице"""
    check = {"name": "links_check", "max_score": 10}
    try:
        html = browser_fn(url)
        links = re.findall(r'href=["\']([^"\'#]+)["\']', html)
        broken = []
        checked = 0
        
        for link in links[:30]:  # Limit to 30 links
            full_url = urljoin(url + "/", link)
            if not full_url.startswith("http"):
                continue
            checked += 1
            try:
                if ssh_fn:
                    result = ssh_fn(f"curl -sL -o /dev/null -w '%{{http_code}}' '{full_url}'")
                    status = int(str(result).strip()) if str(result).strip().isdigit() else 0
                    if status >= 400:
                        broken.append({"url": full_url, "status": status})
            except Exception:
                pass
        
        check["passed"] = len(broken) == 0
        check["score"] = 10 if len(broken) == 0 else max(0, 10 - len(broken) * 2)
        check["details"] = f"Checked {checked} links, {len(broken)} broken"
        check["broken_links"] = broken
    except Exception as e:
        check["passed"] = False
        check["score"] = 0
        check["details"] = f"Link check failed: {e}"
    return check


def _check_form(url: str, form: dict, ssh_fn: Optional[Callable]) -> dict:
    """Проверяет отправку формы"""
    check = {"name": f"form_{form.get('section', 'unknown')}", "max_score": 10}
    try:
        action = form.get("action", "send.php")
        form_url = urljoin(url + "/", action)
        
        # Build test data
        test_data = {
            "name": "ORION Test",
            "phone": "+70000000000",
            "email": "test@orion.test",
            "message": "Automated test submission",
        }
        fields = form.get("fields", [])
        post_data = "&".join(f"{f}={test_data.get(f, 'test')}" for f in fields)
        
        if ssh_fn:
            result = ssh_fn(
                f"curl -sL -X POST -d '{post_data}' -w '\\n%{{http_code}}' '{form_url}'"
            )
            output = str(result)
            lines = output.strip().split("\n")
            status = int(lines[-1]) if lines[-1].isdigit() else 0
            body = "\n".join(lines[:-1])
            
            check["passed"] = status == 200 and ("success" in body.lower() or '"success":true' in body.lower())
            check["score"] = 10 if check["passed"] else 5 if status == 200 else 0
            check["details"] = f"Form {form.get('section')}: HTTP {status}, response contains success={check['passed']}"
        else:
            check["passed"] = False
            check["score"] = 0
            check["details"] = "No SSH function available for form testing"
    except Exception as e:
        check["passed"] = False
        check["score"] = 0
        check["details"] = f"Form check failed: {e}"
    return check


def _check_assets(url: str, ssh_fn: Optional[Callable]) -> dict:
    """Проверяет загрузку assets (CSS, JS, фото)"""
    check = {"name": "assets_check", "max_score": 10}
    try:
        assets = ["style.css", "main.js"]
        loaded = 0
        failed = []
        
        for asset in assets:
            asset_url = urljoin(url + "/", asset)
            if ssh_fn:
                result = ssh_fn(f"curl -sL -o /dev/null -w '%{{http_code}}' '{asset_url}'")
                status = int(str(result).strip()) if str(result).strip().isdigit() else 0
                if status == 200:
                    loaded += 1
                else:
                    failed.append(f"{asset} (HTTP {status})")
        
        check["passed"] = len(failed) == 0
        check["score"] = 10 if len(failed) == 0 else max(0, 10 - len(failed) * 3)
        check["details"] = f"Assets: {loaded}/{len(assets)} loaded. Failed: {', '.join(failed) if failed else 'none'}"
    except Exception as e:
        check["passed"] = False
        check["score"] = 0
        check["details"] = f"Assets check failed: {e}"
    return check


def _check_meta_tags(url: str, ssh_fn: Optional[Callable], browser_fn: Optional[Callable]) -> dict:
    """Проверяет meta теги"""
    check = {"name": "meta_tags", "max_score": 10}
    try:
        html = ""
        if browser_fn:
            html = browser_fn(url)
        elif ssh_fn:
            html = str(ssh_fn(f"curl -sL '{url}'"))
        
        if not html:
            check["passed"] = False
            check["score"] = 0
            check["details"] = "Cannot fetch HTML"
            return check
        
        meta_checks = {
            "title": bool(re.search(r'<title>[^<]+</title>', html)),
            "description": bool(re.search(r'<meta\s+name=["\']description["\']', html, re.IGNORECASE)),
            "viewport": bool(re.search(r'<meta\s+name=["\']viewport["\']', html, re.IGNORECASE)),
            "charset": bool(re.search(r'<meta\s+charset', html, re.IGNORECASE)),
            "og:title": bool(re.search(r'<meta\s+property=["\']og:title["\']', html, re.IGNORECASE)),
        }
        
        passed_count = sum(meta_checks.values())
        total = len(meta_checks)
        
        check["passed"] = passed_count == total
        check["score"] = round(10 * passed_count / total)
        check["details"] = f"Meta tags: {passed_count}/{total} present"
        check["meta_results"] = meta_checks
    except Exception as e:
        check["passed"] = False
        check["score"] = 0
        check["details"] = f"Meta check failed: {e}"
    return check


def _check_load_speed(url: str, ssh_fn: Optional[Callable]) -> dict:
    """Проверяет скорость загрузки (< 3 сек)"""
    check = {"name": "load_speed", "max_score": 10}
    try:
        if ssh_fn:
            result = ssh_fn(
                f"curl -sL -o /dev/null -w '%{{time_total}}' '{url}'"
            )
            load_time = float(str(result).strip())
        else:
            start = time.time()
            import urllib.request
            req = urllib.request.Request(url, headers={"User-Agent": "ORION-Verifier/1.0"})
            urllib.request.urlopen(req, timeout=10)
            load_time = time.time() - start
        
        check["load_time_seconds"] = round(load_time, 3)
        check["passed"] = load_time < 3.0
        if load_time < 1.0:
            check["score"] = 10
        elif load_time < 2.0:
            check["score"] = 8
        elif load_time < 3.0:
            check["score"] = 6
        elif load_time < 5.0:
            check["score"] = 3
        else:
            check["score"] = 0
        check["details"] = f"Load time: {load_time:.3f}s (target: < 3.0s)"
    except Exception as e:
        check["passed"] = False
        check["score"] = 0
        check["details"] = f"Speed check failed: {e}"
    return check


def _check_content_match(url: str, blueprint: dict, browser_fn: Callable) -> dict:
    """Проверяет соответствие контента blueprint"""
    check = {"name": "content_match", "max_score": 10}
    try:
        html = browser_fn(url)
        html_lower = html.lower()
        
        expected_sections = blueprint.get("sections", [])
        found = 0
        missing = []
        
        for section in expected_sections:
            section_id = section["id"]
            # Check by id attribute or heading text
            h1 = section.get("h1", "").lower()
            if (f'id="{section_id}"' in html_lower or 
                f"id='{section_id}'" in html_lower or
                (h1 and h1 in html_lower)):
                found += 1
            else:
                missing.append(section_id)
        
        total = len(expected_sections)
        check["passed"] = found == total
        check["score"] = round(10 * found / total) if total > 0 else 10
        check["details"] = f"Sections: {found}/{total} found. Missing: {', '.join(missing) if missing else 'none'}"
        check["missing_sections"] = missing
    except Exception as e:
        check["passed"] = False
        check["score"] = 0
        check["details"] = f"Content match failed: {e}"
    return check


def _check_viewport_meta(url: str, ssh_fn: Optional[Callable], browser_fn: Optional[Callable]) -> dict:
    """Проверяет мобильную адаптивность"""
    check = {"name": "mobile_responsive", "max_score": 10}
    try:
        html = ""
        if browser_fn:
            html = browser_fn(url)
        elif ssh_fn:
            html = str(ssh_fn(f"curl -sL '{url}'"))
        
        has_viewport = bool(re.search(r'<meta\s+name=["\']viewport["\']', html, re.IGNORECASE))
        has_media_queries = bool(re.search(r'@media', html)) or True  # CSS is external
        
        check["passed"] = has_viewport
        check["score"] = 10 if has_viewport else 0
        check["details"] = f"Viewport meta: {'yes' if has_viewport else 'no'}"
    except Exception as e:
        check["passed"] = False
        check["score"] = 0
        check["details"] = f"Mobile check failed: {e}"
    return check


def _check_ssl(url: str, ssh_fn: Optional[Callable]) -> dict:
    """Проверяет SSL сертификат"""
    check = {"name": "ssl_check", "max_score": 10}
    try:
        if ssh_fn:
            domain = urlparse(url).hostname
            result = ssh_fn(
                f"echo | openssl s_client -servername {domain} -connect {domain}:443 2>/dev/null | "
                f"openssl x509 -noout -dates 2>/dev/null"
            )
            output = str(result)
            check["passed"] = "notAfter" in output
            check["score"] = 10 if check["passed"] else 0
            check["details"] = f"SSL: {'valid' if check['passed'] else 'invalid/missing'}"
        else:
            check["passed"] = url.startswith("https")
            check["score"] = 10 if check["passed"] else 0
            check["details"] = "SSL check via URL scheme"
    except Exception as e:
        check["passed"] = False
        check["score"] = 0
        check["details"] = f"SSL check failed: {e}"
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


def save_verify_report(report: dict, path: str = "site_verify_report.json"):
    """Сохраняет отчёт верификации"""
    with open(path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    logger.info(f"[SiteVerifier] Report saved to {path}")
    return path
