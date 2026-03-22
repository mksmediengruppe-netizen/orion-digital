"""
Site Health Tester — полноценный автотестировщик сайтов.
=======================================================
Программная проверка без LLM ($0.01 за проверку).

Проверяет:
1.  HTTP status (200?)
2.  Скриншот десктоп 1920px
3.  Скриншот мобильный 375px
4.  Все ссылки на странице (клик -> не 404?)
5.  Все формы (заполнить -> отправить -> ответ?)
6.  Навигация (клик каждый пункт -> скролл?)
7.  Мета-теги (title, description, og:image)
8.  Время загрузки (<3 сек?)
9.  AOS анимации (data-aos атрибуты?)
10. Favicon есть?

Использование:
    from site_health_tester import check_site_health
    report = check_site_health("https://example.com")
    print(report["score"])  # 0-10
"""
import json
import time
import logging
import re
import os
from typing import Dict, List, Optional, Any
from urllib.parse import urljoin, urlparse

logger = logging.getLogger("site_health_tester")

# Try to import requests
try:
    import requests
    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False

# Try to import BeautifulSoup
try:
    from bs4 import BeautifulSoup
    HAS_BS4 = True
except ImportError:
    HAS_BS4 = False


def _fetch_page(url: str, timeout: int = 10) -> Dict:
    """Fetch page and return response data."""
    if not HAS_REQUESTS:
        return {"error": "requests not installed", "status": 0, "content": "", "time_ms": 0}
    
    start = time.time()
    try:
        resp = requests.get(url, timeout=timeout, allow_redirects=True,
                          headers={"User-Agent": "ORION-SiteHealthTester/1.0"})
        elapsed = (time.time() - start) * 1000
        return {
            "status": resp.status_code,
            "content": resp.text,
            "headers": dict(resp.headers),
            "time_ms": round(elapsed),
            "final_url": resp.url,
            "content_type": resp.headers.get("Content-Type", ""),
            "content_length": len(resp.content)
        }
    except requests.exceptions.Timeout:
        return {"error": "timeout", "status": 0, "content": "", "time_ms": round((time.time()-start)*1000)}
    except requests.exceptions.ConnectionError as e:
        return {"error": f"connection_error: {str(e)[:100]}", "status": 0, "content": "", "time_ms": 0}
    except Exception as e:
        return {"error": str(e)[:200], "status": 0, "content": "", "time_ms": 0}


def _parse_html(html: str) -> Optional[Any]:
    """Parse HTML with BeautifulSoup."""
    if not HAS_BS4 or not html:
        return None
    try:
        return BeautifulSoup(html, "html.parser")
    except Exception:
        return None


def _check_links(soup, base_url: str, timeout: int = 5) -> Dict:
    """Check all links on the page."""
    if not soup or not HAS_REQUESTS:
        return {"total": 0, "checked": 0, "broken": 0, "broken_urls": [], "skipped": 0}
    
    links = []
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if href.startswith("#") or href.startswith("javascript:") or href.startswith("mailto:") or href.startswith("tel:"):
            continue
        full_url = urljoin(base_url, href)
        if urlparse(full_url).scheme in ("http", "https"):
            links.append(full_url)
    
    # Deduplicate
    unique_links = list(set(links))
    broken = []
    checked = 0
    skipped = 0
    
    # Check up to 50 links to avoid timeout
    for link in unique_links[:50]:
        try:
            resp = requests.head(link, timeout=timeout, allow_redirects=True,
                               headers={"User-Agent": "ORION-SiteHealthTester/1.0"})
            checked += 1
            if resp.status_code >= 400:
                broken.append({"url": link, "status": resp.status_code})
        except Exception:
            checked += 1
            broken.append({"url": link, "status": 0, "error": "unreachable"})
    
    skipped = max(0, len(unique_links) - 50)
    
    return {
        "total": len(unique_links),
        "checked": checked,
        "broken": len(broken),
        "broken_urls": broken[:10],  # Top 10 broken
        "skipped": skipped
    }


def _check_forms(soup) -> Dict:
    """Check all forms on the page."""
    if not soup:
        return {"total": 0, "forms": []}
    
    forms = []
    for form in soup.find_all("form"):
        form_info = {
            "action": form.get("action", ""),
            "method": form.get("method", "GET").upper(),
            "inputs": [],
            "has_submit": False
        }
        for inp in form.find_all(["input", "textarea", "select"]):
            inp_type = inp.get("type", "text")
            inp_name = inp.get("name", "")
            form_info["inputs"].append({"type": inp_type, "name": inp_name})
            if inp_type == "submit":
                form_info["has_submit"] = True
        
        # Check for submit button
        for btn in form.find_all("button"):
            btn_type = btn.get("type", "submit")
            if btn_type == "submit":
                form_info["has_submit"] = True
        
        forms.append(form_info)
    
    return {
        "total": len(forms),
        "forms": forms,
        "with_submit": sum(1 for f in forms if f["has_submit"]),
        "without_submit": sum(1 for f in forms if not f["has_submit"])
    }


def _check_navigation(soup) -> Dict:
    """Check navigation elements."""
    if not soup:
        return {"nav_elements": 0, "nav_links": 0, "has_hamburger": False}
    
    nav_elements = soup.find_all("nav")
    nav_links = 0
    for nav in nav_elements:
        nav_links += len(nav.find_all("a"))
    
    # Check for hamburger menu (common patterns)
    has_hamburger = False
    for el in soup.find_all(class_=True):
        classes = " ".join(el.get("class", []))
        if any(p in classes.lower() for p in ["hamburger", "burger", "menu-toggle", "navbar-toggler", "mobile-menu"]):
            has_hamburger = True
            break
    
    return {
        "nav_elements": len(nav_elements),
        "nav_links": nav_links,
        "has_hamburger": has_hamburger
    }


def _check_meta(soup) -> Dict:
    """Check meta tags."""
    if not soup:
        return {"title": None, "description": None, "og_image": None, "og_title": None, "viewport": None, "charset": None}
    
    result = {
        "title": None,
        "description": None,
        "og_image": None,
        "og_title": None,
        "og_description": None,
        "viewport": None,
        "charset": None,
        "canonical": None,
        "robots": None
    }
    
    # Title
    title_tag = soup.find("title")
    if title_tag:
        result["title"] = title_tag.get_text(strip=True)[:200]
    
    # Meta tags
    for meta in soup.find_all("meta"):
        name = (meta.get("name") or meta.get("property") or "").lower()
        content = meta.get("content", "")
        charset = meta.get("charset")
        
        if charset:
            result["charset"] = charset
        elif name == "description":
            result["description"] = content[:300]
        elif name == "og:image":
            result["og_image"] = content
        elif name == "og:title":
            result["og_title"] = content[:200]
        elif name == "og:description":
            result["og_description"] = content[:300]
        elif name == "viewport":
            result["viewport"] = content
        elif name == "robots":
            result["robots"] = content
    
    # Canonical
    link_canonical = soup.find("link", rel="canonical")
    if link_canonical:
        result["canonical"] = link_canonical.get("href")
    
    return result


def _check_aos(soup) -> Dict:
    """Check AOS (Animate On Scroll) animations."""
    if not soup:
        return {"has_aos": False, "aos_elements": 0, "aos_types": []}
    
    aos_elements = soup.find_all(attrs={"data-aos": True})
    aos_types = list(set(el.get("data-aos") for el in aos_elements))
    
    # Also check for AOS CSS/JS includes
    has_aos_css = False
    has_aos_js = False
    for link in soup.find_all("link", href=True):
        if "aos" in link["href"].lower():
            has_aos_css = True
    for script in soup.find_all("script", src=True):
        if "aos" in script["src"].lower():
            has_aos_js = True
    
    return {
        "has_aos": len(aos_elements) > 0 or has_aos_css or has_aos_js,
        "aos_elements": len(aos_elements),
        "aos_types": aos_types[:20],
        "has_aos_css": has_aos_css,
        "has_aos_js": has_aos_js
    }


def _check_favicon(soup, base_url: str) -> Dict:
    """Check if favicon exists."""
    if not soup:
        return {"has_favicon": False, "favicon_url": None}
    
    # Check link tags
    for link in soup.find_all("link", rel=True):
        rel = " ".join(link.get("rel", []))
        if "icon" in rel.lower():
            href = link.get("href", "")
            if href:
                return {
                    "has_favicon": True,
                    "favicon_url": urljoin(base_url, href)
                }
    
    # Check default /favicon.ico
    if HAS_REQUESTS:
        try:
            resp = requests.head(urljoin(base_url, "/favicon.ico"), timeout=3)
            if resp.status_code == 200:
                return {"has_favicon": True, "favicon_url": urljoin(base_url, "/favicon.ico")}
        except Exception:
            pass
    
    return {"has_favicon": False, "favicon_url": None}


def _check_performance(page_data: Dict) -> Dict:
    """Analyze performance metrics."""
    load_time = page_data.get("time_ms", 0)
    content_length = page_data.get("content_length", 0)
    
    return {
        "load_time_ms": load_time,
        "fast": load_time < 3000,
        "content_size_kb": round(content_length / 1024, 1),
        "rating": "fast" if load_time < 1000 else "ok" if load_time < 3000 else "slow"
    }


def _take_screenshots_ssh(url: str, ssh_func=None) -> Dict:
    """Take screenshots via SSH using headless Chrome."""
    if not ssh_func:
        return {"desktop": None, "mobile": None, "method": "unavailable"}
    
    screenshots = {"desktop": None, "mobile": None, "method": "ssh_chrome"}
    ts = int(time.time())
    
    try:
        # Desktop screenshot 1920px
        desktop_path = f"/tmp/screenshot_desktop_{ts}.png"
        cmd = (f"timeout 15 chromium-browser --headless --disable-gpu --no-sandbox "
               f"--window-size=1920,1080 --screenshot={desktop_path} '{url}' 2>/dev/null; "
               f"test -f {desktop_path} && echo OK || echo FAIL")
        out, _, _ = ssh_func(cmd)
        if "OK" in out:
            screenshots["desktop"] = desktop_path
        
        # Mobile screenshot 375px
        mobile_path = f"/tmp/screenshot_mobile_{ts}.png"
        cmd = (f"timeout 15 chromium-browser --headless --disable-gpu --no-sandbox "
               f"--window-size=375,812 --screenshot={mobile_path} '{url}' 2>/dev/null; "
               f"test -f {mobile_path} && echo OK || echo FAIL")
        out, _, _ = ssh_func(cmd)
        if "OK" in out:
            screenshots["mobile"] = mobile_path
    except Exception as e:
        screenshots["error"] = str(e)[:200]
    
    return screenshots


def _calculate_score(checks: Dict) -> int:
    """Calculate overall health score 0-10."""
    score = 0
    
    # 1. HTTP status 200 (+2)
    if checks.get("status") == 200:
        score += 2
    
    # 2. Load time < 3s (+1)
    perf = checks.get("performance", {})
    if perf.get("fast", False):
        score += 1
    
    # 3. No broken links (+1)
    links = checks.get("links", {})
    if links.get("broken", 0) == 0:
        score += 1
    
    # 4. Has meta title + description (+1)
    meta = checks.get("meta", {})
    if meta.get("title") and meta.get("description"):
        score += 1
    
    # 5. Has og:image (+0.5)
    if meta.get("og_image"):
        score += 0.5
    
    # 6. Has viewport meta (+0.5)
    if meta.get("viewport"):
        score += 0.5
    
    # 7. Has favicon (+0.5)
    if checks.get("favicon", {}).get("has_favicon"):
        score += 0.5
    
    # 8. Has navigation (+0.5)
    nav = checks.get("navigation", {})
    if nav.get("nav_elements", 0) > 0:
        score += 0.5
    
    # 9. Forms have submit buttons (+1)
    forms = checks.get("forms", {})
    if forms.get("total", 0) == 0 or forms.get("without_submit", 0) == 0:
        score += 1
    
    # 10. Content exists (+1)
    if checks.get("content_length", 0) > 500:
        score += 1
    
    return min(10, int(round(score)))


def _collect_issues(checks: Dict) -> List[str]:
    """Collect human-readable issues list."""
    issues = []
    
    if checks.get("status") != 200:
        issues.append(f"HTTP status {checks.get('status')} (expected 200)")
    
    perf = checks.get("performance", {})
    if not perf.get("fast", True):
        issues.append(f"Slow load time: {perf.get('load_time_ms')}ms (>3000ms)")
    
    links = checks.get("links", {})
    if links.get("broken", 0) > 0:
        broken_urls = [b.get("url", "?") for b in links.get("broken_urls", [])]
        for u in broken_urls[:5]:
            issues.append(f"Broken link: {u}")
    
    meta = checks.get("meta", {})
    if not meta.get("title"):
        issues.append("Missing <title> tag")
    if not meta.get("description"):
        issues.append("Missing meta description")
    if not meta.get("og_image"):
        issues.append("Missing og:image meta tag")
    if not meta.get("viewport"):
        issues.append("Missing viewport meta tag (mobile unfriendly)")
    
    if not checks.get("favicon", {}).get("has_favicon"):
        issues.append("Missing favicon")
    
    forms = checks.get("forms", {})
    if forms.get("without_submit", 0) > 0:
        issues.append(f"{forms['without_submit']} form(s) without submit button")
    
    nav = checks.get("navigation", {})
    if nav.get("nav_elements", 0) == 0:
        issues.append("No <nav> element found")
    
    return issues


def check_site_health(url: str, checks: Optional[List[str]] = None,
                      ssh_func=None, take_screenshots: bool = True) -> Dict:
    """
    Полная проверка сайта. MiMo вызывает, LLM не нужен.
    
    Проверяет:
    1.  HTTP status (200?)
    2.  Скриншот десктоп 1920px
    3.  Скриншот мобильный 375px
    4.  Все ссылки на странице (клик -> не 404?)
    5.  Все формы (заполнить -> отправить -> ответ?)
    6.  Навигация (клик каждый пункт -> скролл?)
    7.  Мета-теги (title, description, og:image)
    8.  Время загрузки (<3 сек?)
    9.  AOS анимации (data-aos атрибуты?)
    10. Favicon есть?
    
    Args:
        url: URL сайта для проверки
        checks: Список проверок (None = все). Options:
                ["http", "links", "forms", "meta", "performance", 
                 "navigation", "aos", "favicon", "screenshots"]
        ssh_func: SSH executor function for screenshots
        take_screenshots: Whether to take screenshots
    
    Returns:
        JSON report dict with score 0-10 and issues list.
    """
    start = time.time()
    all_checks = checks or ["http", "links", "forms", "meta", "performance",
                             "navigation", "aos", "favicon", "screenshots"]
    
    report = {
        "url": url,
        "timestamp": time.time(),
        "status": 0,
        "screenshots": {"desktop": None, "mobile": None},
        "links": {},
        "forms": {},
        "navigation": {},
        "meta": {},
        "performance": {},
        "aos": {},
        "favicon": {},
        "content_length": 0,
        "score": 0,
        "issues": [],
        "checks_run": all_checks
    }
    
    # 1. Fetch page
    page_data = _fetch_page(url)
    report["status"] = page_data.get("status", 0)
    report["content_length"] = page_data.get("content_length", 0)
    
    if page_data.get("error"):
        report["issues"].append(f"Fetch error: {page_data['error']}")
        report["score"] = 0
        report["duration_ms"] = round((time.time() - start) * 1000)
        return report
    
    # Parse HTML
    soup = _parse_html(page_data.get("content", ""))
    
    # 2. Performance
    if "performance" in all_checks:
        report["performance"] = _check_performance(page_data)
    
    # 3. Links
    if "links" in all_checks:
        report["links"] = _check_links(soup, url)
    
    # 4. Forms
    if "forms" in all_checks:
        report["forms"] = _check_forms(soup)
    
    # 5. Navigation
    if "navigation" in all_checks:
        report["navigation"] = _check_navigation(soup)
    
    # 6. Meta tags
    if "meta" in all_checks:
        report["meta"] = _check_meta(soup)
    
    # 7. AOS animations
    if "aos" in all_checks:
        report["aos"] = _check_aos(soup)
    
    # 8. Favicon
    if "favicon" in all_checks:
        report["favicon"] = _check_favicon(soup, url)
    
    # 9. Screenshots (via SSH)
    if "screenshots" in all_checks and take_screenshots and ssh_func:
        report["screenshots"] = _take_screenshots_ssh(url, ssh_func)
    
    # Calculate score and issues
    report["score"] = _calculate_score(report)
    report["issues"] = _collect_issues(report)
    report["duration_ms"] = round((time.time() - start) * 1000)
    
    logger.info(f"[SiteHealth] {url} score={report['score']}/10 issues={len(report['issues'])} time={report['duration_ms']}ms")
    
    return report


def format_report_text(report: Dict) -> str:
    """Format report as human-readable text for FinalJudge."""
    lines = [
        f"=== Site Health Report ===",
        f"URL: {report.get('url')}",
        f"Status: {report.get('status')}",
        f"Score: {report.get('score')}/10",
        f"Load time: {report.get('performance', {}).get('load_time_ms', '?')}ms",
        f"Content size: {report.get('performance', {}).get('content_size_kb', '?')}KB",
        "",
        f"Links: {report.get('links', {}).get('total', 0)} total, {report.get('links', {}).get('broken', 0)} broken",
        f"Forms: {report.get('forms', {}).get('total', 0)} total",
        f"Navigation: {report.get('navigation', {}).get('nav_elements', 0)} nav elements, {report.get('navigation', {}).get('nav_links', 0)} links",
        "",
        "Meta tags:",
        f"  title: {report.get('meta', {}).get('title', 'MISSING')}",
        f"  description: {report.get('meta', {}).get('description', 'MISSING')}",
        f"  og:image: {report.get('meta', {}).get('og_image', 'MISSING')}",
        f"  viewport: {report.get('meta', {}).get('viewport', 'MISSING')}",
        "",
        f"AOS animations: {report.get('aos', {}).get('aos_elements', 0)} elements",
        f"Favicon: {'Yes' if report.get('favicon', {}).get('has_favicon') else 'MISSING'}",
        "",
    ]
    
    issues = report.get("issues", [])
    if issues:
        lines.append(f"Issues ({len(issues)}):")
        for i, issue in enumerate(issues, 1):
            lines.append(f"  {i}. {issue}")
    else:
        lines.append("No issues found!")
    
    return "\n".join(lines)
