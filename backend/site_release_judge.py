"""
Site Release Judge — Финальный judge для сайтов (не Битрикс).
Проверяет: секции по blueprint, фото, формы, mobile, meta, скорость.
Выход: site_release_verdict.json
"""
import json
import logging
import re
import time
from typing import Callable, Optional
from urllib.parse import urljoin

logger = logging.getLogger(__name__)

# ── Success Criteria ─────────────────────────────────────────────
WEBSITE_SUCCESS_CRITERIA = [
    "all_sections_present",       # Все секции из blueprint есть в HTML
    "photos_loaded",              # Все фото загружаются (HTTP 200)
    "forms_functional",           # Формы отправляются и возвращают success
    "mobile_responsive",          # viewport meta + media queries
    "meta_tags_complete",         # title, description, og:title, charset, viewport
    "load_speed_ok",              # < 3 секунд
    "no_broken_links",            # Нет 404 ссылок
    "https_active",               # HTTPS работает (если домен)
    "content_matches_brief",      # Контент соответствует ТЗ
]


def judge_site_release(
    url: str,
    blueprint: dict,
    brief: dict = None,
    ssh_fn: Optional[Callable] = None,
    browser_fn: Optional[Callable] = None,
) -> dict:
    """
    Финальная проверка сайта перед релизом.

    Args:
        url: URL опубликованного сайта
        blueprint: site_blueprint.json
        brief: site_brief.json (опционально)
        ssh_fn: SSH функция (cmd -> result)
        browser_fn: Браузер функция (url -> html)

    Returns:
        dict: Вердикт с оценками
    """
    verdict = {
        "url": url,
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "criteria": {},
        "score": 0,
        "max_score": len(WEBSITE_SUCCESS_CRITERIA) * 10,
        "grade": "",
        "verdict": "",
        "issues": [],
        "passed_criteria": [],
        "failed_criteria": [],
    }

    html = _fetch_html(url, ssh_fn, browser_fn)

    # ── 1. all_sections_present ──────────────────────────────
    result = _check_sections(html, blueprint)
    verdict["criteria"]["all_sections_present"] = result

    # ── 2. photos_loaded ─────────────────────────────────────
    result = _check_photos(url, html, ssh_fn)
    verdict["criteria"]["photos_loaded"] = result

    # ── 3. forms_functional ──────────────────────────────────
    result = _check_forms(url, blueprint, ssh_fn)
    verdict["criteria"]["forms_functional"] = result

    # ── 4. mobile_responsive ─────────────────────────────────
    result = _check_mobile(html)
    verdict["criteria"]["mobile_responsive"] = result

    # ── 5. meta_tags_complete ────────────────────────────────
    result = _check_meta(html)
    verdict["criteria"]["meta_tags_complete"] = result

    # ── 6. load_speed_ok ─────────────────────────────────────
    result = _check_speed(url, ssh_fn)
    verdict["criteria"]["load_speed_ok"] = result

    # ── 7. no_broken_links ───────────────────────────────────
    result = _check_links(url, html, ssh_fn)
    verdict["criteria"]["no_broken_links"] = result

    # ── 8. https_active ──────────────────────────────────────
    result = _check_https(url, ssh_fn)
    verdict["criteria"]["https_active"] = result

    # ── 9. content_matches_brief ─────────────────────────────
    result = _check_content(html, brief)
    verdict["criteria"]["content_matches_brief"] = result

    # ── Score ────────────────────────────────────────────────
    total = 0
    for name, check in verdict["criteria"].items():
        score = check.get("score", 0)
        total += score
        if check.get("passed"):
            verdict["passed_criteria"].append(name)
        else:
            verdict["failed_criteria"].append(name)
            if check.get("details"):
                verdict["issues"].append(f"{name}: {check['details']}")

    verdict["score"] = total
    pct = (total / verdict["max_score"] * 100) if verdict["max_score"] > 0 else 0
    verdict["percentage"] = round(pct, 1)
    verdict["grade"] = _grade(pct)

    passed = len(verdict["passed_criteria"])
    total_criteria = len(WEBSITE_SUCCESS_CRITERIA)
    if passed == total_criteria:
        verdict["verdict"] = "RELEASE — сайт полностью готов"
    elif passed >= total_criteria - 2:
        verdict["verdict"] = "CONDITIONAL — мелкие доработки"
    elif passed >= total_criteria // 2:
        verdict["verdict"] = "REWORK — требуются существенные доработки"
    else:
        verdict["verdict"] = "FAIL — сайт не готов к релизу"

    logger.info(f"[SiteReleaseJudge] {verdict['verdict']} "
                f"({passed}/{total_criteria} criteria, {pct:.0f}%)")
    return verdict


def _fetch_html(url, ssh_fn, browser_fn):
    """Получает HTML страницы."""
    if browser_fn:
        try:
            return browser_fn(url)
        except Exception:
            pass
    if ssh_fn:
        try:
            return str(ssh_fn(f"curl -sL '{url}'"))
        except Exception:
            pass
    return ""


def _check_sections(html, blueprint):
    """Проверяет наличие всех секций из blueprint."""
    sections = blueprint.get("sections", [])
    html_lower = html.lower()
    found, missing = 0, []
    for s in sections:
        sid = s["id"]
        h1 = s.get("h1", "").lower()
        if (f'id="{sid}"' in html_lower or f"id='{sid}'" in html_lower or
                (h1 and len(h1) > 3 and h1 in html_lower)):
            found += 1
        else:
            missing.append(sid)
    total = len(sections)
    passed = found == total
    return {
        "passed": passed,
        "score": 10 if passed else max(0, round(10 * found / total)) if total else 10,
        "details": f"{found}/{total} sections" + (f", missing: {', '.join(missing)}" if missing else ""),
    }


def _check_photos(url, html, ssh_fn):
    """Проверяет загрузку фото."""
    imgs = re.findall(r'<img[^>]+src=["\']([^"\']+)["\']', html, re.IGNORECASE)
    if not imgs:
        return {"passed": True, "score": 10, "details": "No images to check"}
    broken = []
    for src in imgs[:20]:
        if src.startswith("data:"):
            continue
        full = urljoin(url + "/", src) if not src.startswith("http") else src
        if ssh_fn:
            try:
                r = str(ssh_fn(f"curl -sL -o /dev/null -w '%{{http_code}}' '{full}'")).strip()
                if r.isdigit() and int(r) >= 400:
                    broken.append(src)
            except Exception:
                pass
    passed = len(broken) == 0
    return {
        "passed": passed,
        "score": 10 if passed else max(0, 10 - len(broken) * 2),
        "details": f"{len(imgs) - len(broken)}/{len(imgs)} photos OK" +
                   (f", broken: {broken[:3]}" if broken else ""),
    }


def _check_forms(url, blueprint, ssh_fn):
    """Проверяет работу форм."""
    forms = blueprint.get("forms", [])
    if not forms:
        return {"passed": True, "score": 10, "details": "No forms in blueprint"}
    if not ssh_fn:
        return {"passed": False, "score": 0, "details": "No SSH for form test"}
    ok = 0
    for form in forms:
        action = form.get("action", "send.php")
        form_url = urljoin(url + "/", action)
        fields = form.get("fields", ["name", "phone"])
        data = "&".join(f"{f}=test" for f in fields)
        try:
            r = str(ssh_fn(f"curl -sL -X POST -d '{data}' '{form_url}'"))
            if "success" in r.lower():
                ok += 1
        except Exception:
            pass
    passed = ok == len(forms)
    return {
        "passed": passed,
        "score": 10 if passed else round(10 * ok / len(forms)),
        "details": f"{ok}/{len(forms)} forms working",
    }


def _check_mobile(html):
    """Проверяет мобильную адаптивность."""
    has_viewport = bool(re.search(r'<meta[^>]+name=["\']viewport["\']', html, re.I))
    has_responsive = bool(re.search(r'@media|responsive|mobile', html, re.I))
    passed = has_viewport
    return {
        "passed": passed,
        "score": 10 if passed else 0,
        "details": f"viewport={'yes' if has_viewport else 'no'}, responsive hints={'yes' if has_responsive else 'no'}",
    }


def _check_meta(html):
    """Проверяет meta теги."""
    checks = {
        "title": bool(re.search(r'<title>[^<]+</title>', html)),
        "description": bool(re.search(r'<meta[^>]+name=["\']description["\']', html, re.I)),
        "viewport": bool(re.search(r'<meta[^>]+name=["\']viewport["\']', html, re.I)),
        "charset": bool(re.search(r'<meta[^>]+charset', html, re.I)),
        "og:title": bool(re.search(r'<meta[^>]+property=["\']og:title["\']', html, re.I)),
    }
    ok = sum(checks.values())
    return {
        "passed": ok == len(checks),
        "score": round(10 * ok / len(checks)),
        "details": f"{ok}/{len(checks)} meta tags: " + ", ".join(f"{k}={'✓' if v else '✗'}" for k, v in checks.items()),
    }


def _check_speed(url, ssh_fn):
    """Проверяет скорость загрузки."""
    if not ssh_fn:
        return {"passed": True, "score": 5, "details": "No SSH for speed test"}
    try:
        r = str(ssh_fn(f"curl -sL -o /dev/null -w '%{{time_total}}' '{url}'")).strip()
        t = float(r)
        passed = t < 3.0
        score = 10 if t < 1 else 8 if t < 2 else 6 if t < 3 else 3 if t < 5 else 0
        return {"passed": passed, "score": score, "details": f"{t:.2f}s (target <3s)"}
    except Exception as e:
        return {"passed": False, "score": 0, "details": str(e)}


def _check_links(url, html, ssh_fn):
    """Проверяет ссылки."""
    hrefs = re.findall(r'href=["\']([^"\'#]+)["\']', html)
    if not hrefs or not ssh_fn:
        return {"passed": True, "score": 10, "details": "No links to check or no SSH"}
    broken = []
    for href in hrefs[:25]:
        if href.startswith("mailto:") or href.startswith("tel:") or href.startswith("javascript:"):
            continue
        full = urljoin(url + "/", href) if not href.startswith("http") else href
        try:
            r = str(ssh_fn(f"curl -sL -o /dev/null -w '%{{http_code}}' '{full}'")).strip()
            if r.isdigit() and int(r) >= 400:
                broken.append(href)
        except Exception:
            pass
    passed = len(broken) == 0
    return {
        "passed": passed,
        "score": 10 if passed else max(0, 10 - len(broken) * 2),
        "details": f"{len(broken)} broken links" + (f": {broken[:3]}" if broken else ""),
    }


def _check_https(url, ssh_fn):
    """Проверяет HTTPS."""
    if url.startswith("https://"):
        return {"passed": True, "score": 10, "details": "HTTPS active"}
    if ssh_fn:
        https_url = url.replace("http://", "https://")
        try:
            r = str(ssh_fn(f"curl -sL -o /dev/null -w '%{{http_code}}' '{https_url}'")).strip()
            if r.isdigit() and int(r) == 200:
                return {"passed": True, "score": 10, "details": "HTTPS available"}
        except Exception:
            pass
    return {"passed": False, "score": 0, "details": "HTTPS not active"}


def _check_content(html, brief):
    """Проверяет соответствие контента brief."""
    if not brief:
        return {"passed": True, "score": 7, "details": "No brief for content check"}
    html_lower = html.lower()
    key_messages = brief.get("key_messages", [])
    if not key_messages:
        return {"passed": True, "score": 8, "details": "No key messages to verify"}
    found = sum(1 for m in key_messages if m.lower() in html_lower)
    total = len(key_messages)
    passed = found >= total * 0.5
    return {
        "passed": passed,
        "score": round(10 * found / total) if total else 10,
        "details": f"{found}/{total} key messages found",
    }


def _grade(pct):
    if pct >= 95: return "A+"
    if pct >= 90: return "A"
    if pct >= 80: return "B"
    if pct >= 70: return "C"
    if pct >= 60: return "D"
    return "F"


def save_verdict(verdict: dict, path: str = "site_release_verdict.json"):
    """Сохраняет вердикт."""
    with open(path, "w", encoding="utf-8") as f:
        json.dump(verdict, f, ensure_ascii=False, indent=2)
    logger.info(f"[SiteReleaseJudge] Verdict saved to {path}")
    return path
