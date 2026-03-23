from tool_sandbox import is_url_safe
"""
Browser Agent Module v2 — Универсальная автоматизация любых веб-панелей.
Playwright для реального браузера + механизм передачи управления пользователю.

КЛЮЧЕВЫЕ ВОЗМОЖНОСТИ:
- navigate(url)           — открыть страницу, получить скриншот + DOM
- fill(selector, value)   — заполнить поле с триггером Vue/React events
- type_text(selector, v)  — посимвольный ввод (для SPA где fill не работает)
- click(selector)         — кликнуть с умным ожиданием навигации
- press_key(key)          — нажать клавишу (Enter, Tab, Escape)
- select_option(sel, val) — выбрать из dropdown (native <select> и Vuetify)
- execute_js(code)        — выполнить произвольный JavaScript
- wait_for(selector/url)  — ждать появления элемента или смены URL
- get_elements(selector)  — получить список элементов с текстом и атрибутами
- screenshot()            — скриншот текущей страницы
- get_page_info()         — URL, title, DOM-структура, формы
- smart_login(url,l,p)    — автоматический логин в любой ЛК
- ask_user(reason)        — передать управление пользователю (капча, 2FA)
- scroll(direction)       — прокрутка страницы
- hover(selector)         — навести курсор

FTP ИНСТРУМЕНТЫ (ftplib):
- ftp_upload, ftp_download, ftp_list, ftp_delete
"""

import requests
from urllib.parse import urljoin, urlparse
import re
import json
import time
import base64
import threading
import ftplib
import io
import logging
import os
import uuid


# ═══════ PARALLEL CHAT BROWSER CONTEXTS ═══════
import threading as _pw_threading
import time as _pw_time

_pw_contexts = {}  # {chat_id: {"context": ctx, "page": page, "last_used": float}}
_pw_lock = _pw_threading.Lock()
_MAX_BROWSER_CONTEXTS = 5


import threading as _threading_watchdog

class BrowserWatchdog:
    """C3: Kill hung Playwright contexts after timeout."""
    
    def __init__(self, timeout=300):
        self._timeout = timeout
        self._timer = None
    
    def start(self, chat_id):
        self.cancel()
        self._timer = _threading_watchdog.Timer(
            self._timeout, 
            self._kill, 
            args=[chat_id]
        )
        self._timer.daemon = True
        self._timer.start()
    
    def cancel(self):
        if self._timer:
            self._timer.cancel()
            self._timer = None
    
    def _kill(self, chat_id):
        logger.warning(f"Browser watchdog: killing context for {chat_id}")
        try:
            close_browser_context(chat_id)
        except Exception as e:
            logger.error(f"Watchdog kill failed: {e}")


def get_browser_page(chat_id, pw_browser=None):
    """Get or create a Playwright page for a specific chat."""
    with _pw_lock:
        if chat_id in _pw_contexts:
            _pw_contexts[chat_id]["last_used"] = _pw_time.time()
            return _pw_contexts[chat_id]["page"]
        
        # Evict oldest if at limit
        if len(_pw_contexts) >= _MAX_BROWSER_CONTEXTS:
            oldest = min(_pw_contexts, key=lambda k: _pw_contexts[k].get("last_used", 0))
            _close_browser_context_unsafe(oldest)
        
        if pw_browser is None:
            return None
        
        try:
            context = pw_browser.new_context(
                viewport={"width": 1920, "height": 1080},
                user_agent="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            )
            page = context.new_page()
            _pw_contexts[chat_id] = {
                "context": context,
                "page": page,
                "last_used": _pw_time.time()
            }
            return page
        except Exception as e:
            logging.getLogger("browser_agent").error(f"Failed to create browser context for {chat_id}: {e}")
            return None

def close_browser_context(chat_id):
    """Close browser context for a specific chat (call on task_complete)."""
    with _pw_lock:
        _close_browser_context_unsafe(chat_id)

def _close_browser_context_unsafe(chat_id):
    """Close without lock - must be called with _pw_lock held."""
    if chat_id in _pw_contexts:
        try:
            _pw_contexts[chat_id]["page"].close()
        except:
            pass
        try:
            _pw_contexts[chat_id]["context"].close()
        except:
            pass
        del _pw_contexts[chat_id]

logger = logging.getLogger("browser_agent")

# ── Playwright support ─────────────────────────────────────────────────────
_playwright_available = False
try:
    from playwright.sync_api import sync_playwright, TimeoutError as PWTimeoutError
    _playwright_available = True  # PATCH: enabled
except ImportError:
    PWTimeoutError = Exception

_pw_lock = threading.Lock()

# ── FIX GREENLET: Use threading.local() so each thread gets its own Playwright instance ──
# This prevents "Cannot switch to a different thread" greenlet errors when
# gunicorn workers recycle threads or new requests arrive in different threads.
_pw_local = threading.local()

# Keep legacy globals for backward compatibility (used in get_text etc.)
_pw_browser = None
_pw_context = None
_pw_page = None
_pw_playwright = None

# Флаг ожидания пользователя (для takeover)
_user_takeover_active = False
_user_takeover_event = threading.Event()

# ── FIX: Dedicated thread for Playwright (asyncio loop conflict) ──
import concurrent.futures

# MEGA PATCH Bug 3.1: Smart timeout for heavy pages
_HEAVY_URL_PATTERNS = ["install", "setup", "wizard", "bitrix", "bitrixsetup", "wp-admin"]

def _get_page_timeout(url: str) -> int:
    """Return timeout in ms based on URL pattern"""
    url_lower = url.lower() if url else ""
    for pattern in _HEAVY_URL_PATTERNS:
        if pattern in url_lower:
            return 180000  # 180 seconds for heavy pages
    return 90000  # 90 seconds default (was 30s)

def _get_nav_timeout(url: str) -> int:
    """Return navigation timeout based on URL"""
    url_lower = url.lower() if url else ""
    for pattern in _HEAVY_URL_PATTERNS:
        if pattern in url_lower:
            return 180000
    return 90000

PLAYWRIGHT_MAX_WORKERS = int(os.environ.get("PLAYWRIGHT_MAX_WORKERS", "1"))
# FIX: Use single dedicated thread for Playwright to prevent greenlet.error
# Playwright's sync API uses greenlets which cannot switch between threads
_pw_thread_pool = concurrent.futures.ThreadPoolExecutor(max_workers=1, thread_name_prefix="pw")


# ══ SECURITY FIX 4: SSL verification with exceptions ══
_SSL_VERIFY_EXCEPTIONS = {"cp.beget.com", "api.beget.com"}

def _ssl_verify(url: str) -> bool:
    """Return False only for known hosts with SSL issues."""
    try:
        from urllib.parse import urlparse
        host = urlparse(url).hostname or ""
        return host not in _SSL_VERIFY_EXCEPTIONS
    except Exception:
        return True


def _run_in_pw_thread(fn, *args, **kwargs):
    """Run a function in the dedicated Playwright thread (no asyncio loop)."""
    try:
        future = _pw_thread_pool.submit(fn, *args, **kwargs)
        return future.result(timeout=180)
    except concurrent.futures.TimeoutError:
        logger.error("[PW] Playwright operation timed out (180s)")
        return None
    except Exception as e:
        logger.error(f"[PW] Thread pool error: {e}")
        raise


def _get_pw_page_impl(url: str = None, width: int = 1280, height: int = 800):
    """
    Получить или создать Playwright page.
    Если url задан — навигируем на него.
    Uses threading.local() to avoid greenlet cross-thread errors.
    """
    global _pw_browser, _pw_context, _pw_page, _pw_playwright
    if not _playwright_available:
        return None, None, None, None
    # Use per-thread state to avoid greenlet errors
    _t_playwright = getattr(_pw_local, 'playwright', None)
    _t_browser = getattr(_pw_local, 'browser', None)
    _t_context = getattr(_pw_local, 'context', None)
    _t_page = getattr(_pw_local, 'page', None)
    try:
        if _t_playwright is None:
            _t_playwright = sync_playwright().start()
            _pw_local.playwright = _t_playwright
        if _t_browser is None or not _t_browser.is_connected():
            _t_browser = _t_playwright.chromium.launch(
                headless=True,
                args=["--no-sandbox", "--disable-setuid-sandbox",
                      "--disable-dev-shm-usage", "--disable-gpu",
                      "--disable-web-security", "--allow-running-insecure-content"]
            )
            _pw_local.browser = _t_browser
            _t_context = None
            _pw_local.context = None
        if _t_context is None:
            _t_context = _t_browser.new_context(
                viewport={"width": width, "height": height},
                user_agent="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                           "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
                locale="ru-RU",
                timezone_id="Europe/Moscow",
            )
            # Включаем cookies persistence
            _t_context.set_default_timeout(30000)
            _pw_local.context = _t_context
            _t_page = None
            _pw_local.page = None
        if _t_page is None or _t_page.is_closed():
            _t_page = _t_context.new_page()
            _pw_local.page = _t_page
        # Update legacy globals for backward compat
        _pw_browser = _t_browser
        _pw_context = _t_context
        _pw_page = _t_page
        _pw_playwright = _t_playwright
        if url:
            _t_page.goto(url, timeout=_get_timeout(url), wait_until="domcontentloaded")
            # Ждём загрузки SPA-фреймворков
            try:
                _t_page.wait_for_load_state("networkidle", timeout=90000)
            except Exception:
                _t_page.wait_for_timeout(2000)
        return _t_playwright, _t_browser, _t_context, _t_page
    except Exception as e:
        err_str = str(e)
        logger.warning(f"[PW] _get_pw_page error: {e}")
        # При greenlet/thread ошибке — пересоздаём весь Playwright instance
        if "greenlet" in err_str.lower() or "thread" in err_str.lower() or "switch" in err_str.lower():
            logger.warning(f"[PW] Greenlet/thread error detected, recreating Playwright (threading.local)")
            # Clear per-thread state
            _old_pw = getattr(_pw_local, 'playwright', None)
            try:
                if _old_pw is not None:
                    _old_pw.stop()
            except Exception:
                pass
            _pw_local.playwright = None
            _pw_local.browser = None
            _pw_local.context = None
            _pw_local.page = None
            # Retry once with fresh instance in this thread
            try:
                _new_pw = sync_playwright().start()
                _new_br = _new_pw.chromium.launch(
                    headless=True,
                    args=["--no-sandbox", "--disable-setuid-sandbox",
                          "--disable-dev-shm-usage", "--disable-gpu",
                          "--disable-web-security", "--allow-running-insecure-content"]
                )
                _new_ctx = _new_br.new_context(
                    viewport={"width": width, "height": height},
                    user_agent="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                               "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
                    locale="ru-RU",
                    timezone_id="Europe/Moscow",
                )
                _new_ctx.set_default_timeout(30000)
                _new_pg = _new_ctx.new_page()
                _pw_local.playwright = _new_pw
                _pw_local.browser = _new_br
                _pw_local.context = _new_ctx
                _pw_local.page = _new_pg
                if url:
                    _new_pg.goto(url, timeout=_get_timeout(url), wait_until="domcontentloaded")
                    try:
                        _new_pg.wait_for_load_state("networkidle", timeout=90000)
                    except Exception:
                        _new_pg.wait_for_timeout(2000)
                logger.info(f"[PW] Playwright recreated successfully after greenlet error")
                return _new_pw, _new_br, _new_ctx, _new_pg
            except Exception as e2:
                logger.error(f"[PW] Failed to recreate Playwright: {e2}")
                _pw_local.page = None
                _pw_local.context = None
                _pw_local.browser = None
                _pw_local.playwright = None
                return None, None, None, None
        _pw_local.page = None
        _pw_local.context = None
        _pw_local.browser = None
        return None, None, None, None


def _take_screenshot_safe(page) -> str:
    """Безопасно сделать скриншот, вернуть base64 или пустую строку."""
    try:
        png_bytes = page.screenshot(full_page=False)
        return base64.b64encode(png_bytes).decode("utf-8")
    except Exception:
        return ""


def _trigger_input_events(page, selector: str):
    """
    Триггерить input/change/blur events для Vue.js/React/Angular.
    Это критически важно — без этого SPA-фреймворки не видят изменения.
    """
    try:
        page.evaluate(f"""(() => {{
            const el = document.querySelector('{selector}');
            if (!el) return;
            el.dispatchEvent(new Event('input', {{ bubbles: true }}));
            el.dispatchEvent(new Event('change', {{ bubbles: true }}));
            el.dispatchEvent(new Event('blur', {{ bubbles: true }}));
            // Vue.js 2 specific
            if (el.__vue__) {{
                el.__vue__.$emit('input', el.value);
                el.__vue__.$emit('change', el.value);
            }}
            // Vue.js 3 / Vuetify
            const vueEvent = new Event('input', {{ bubbles: true }});
            Object.defineProperty(vueEvent, 'target', {{ value: el }});
            el.dispatchEvent(vueEvent);
        }})()""")
    except Exception:
        pass



def _pw_navigate(url, width=1280, height=800):
    """Navigate to URL in the dedicated Playwright thread. Returns dict."""
    def _do():
        global _pw_browser, _pw_context, _pw_page, _pw_playwright
        if not _playwright_available:
            return None
        def _op():
            with _pw_lock:
                pw, br, ctx, page = _get_pw_page_impl(url, width, height)
                if page is None:
                    return None
                title = ""
                try:
                    title = page.title()
                except Exception:
                    pass
                screenshot = _take_screenshot_safe(page)
                # Extract page info
                page_info = {}
                try:
                    # Wait for page to settle before evaluating JS (prevents 'Execution context was destroyed')
                    try:
                        page.wait_for_load_state("domcontentloaded", timeout=5000)
                    except Exception:
                        pass
                    page_info = {
                        "url": page.url,
                        "title": title,
                        "forms": [],
                        "links": [],
                        "buttons": [],
                        "inputs": [],
                    }
                    # Get visible text
                    try:
                        page_info["text"] = page.evaluate("() => document.body?.innerText?.substring(0, 5000) || ''")
                    except Exception as _eval_err:
                        if "context was destroyed" in str(_eval_err).lower() or "navigation" in str(_eval_err).lower():
                            # Page navigated during evaluate - wait and retry once
                            try:
                                page.wait_for_load_state("domcontentloaded", timeout=5000)
                                page_info["text"] = page.evaluate("() => document.body?.innerText?.substring(0, 5000) || ''")
                            except Exception:
                                page_info["text"] = ""
                        else:
                            page_info["text"] = ""
                    # Get forms
                    try:
                        page_info["forms"] = page.evaluate("""() => {
                            return Array.from(document.querySelectorAll('form')).slice(0, 5).map(f => ({
                                action: f.action, method: f.method, id: f.id,
                                inputs: Array.from(f.querySelectorAll('input,select,textarea')).map(i => ({
                                    type: i.type, name: i.name, id: i.id, placeholder: i.placeholder, value: i.value?.substring(0,50)
                                }))
                            }))
                        }""")
                    except Exception:
                        pass
                    # Get links
                    try:
                        page_info["links"] = page.evaluate("""() => {
                            return Array.from(document.querySelectorAll('a[href]')).slice(0, 30).map(a => ({
                                text: a.innerText?.trim()?.substring(0, 80), href: a.href
                            })).filter(a => a.text)
                        }""")
                    except Exception:
                        pass
                    # Get buttons
                    try:
                        page_info["buttons"] = page.evaluate("""() => {
                            return Array.from(document.querySelectorAll('button, input[type=submit], [role=button]')).slice(0, 20).map(b => ({
                                text: b.innerText?.trim()?.substring(0, 80) || b.value || '', type: b.type, id: b.id
                            })).filter(b => b.text)
                        }""")
                    except Exception:
                        pass
                except Exception as e:
                    logger.warning(f"[PW] page_info extraction error: {e}")
                return {
                    "success": True,
                    "url": page.url,
                    "title": title,
                    "status_code": 200,
                    "page_info": page_info,
                    "screenshot": screenshot
                }
        result = _run_in_pw_thread(_op)
        if result is not None:
            return result
        return {"success": False, "error": "Playwright thread failed"}
    try:
        result = _run_in_pw_thread(_do)
        return result
    except Exception as e:
        logger.error(f"[PW] _pw_navigate error: {e}")
        return None

def _pw_click(selector):
    """Click element in the dedicated Playwright thread."""
    def _op():
        with _pw_lock:
            pw, br, ctx, page = _get_pw_page_impl()
            if page is None:
                return {"success": False, "error": "No page"}
            try:
                page.click(selector, timeout=10000)
                page.wait_for_timeout(1000)
                screenshot = _take_screenshot_safe(page)
                return {"success": True, "url": page.url, "screenshot": screenshot}
            except Exception as e:
                return {"success": False, "error": str(e)}
    result = _run_in_pw_thread(_op)
    if result is not None:
        return result
    return {"success": False, "error": "Playwright thread failed"}

def _pw_fill(selector, value):
    """Fill input in the dedicated Playwright thread."""
    def _op():
        with _pw_lock:
            pw, br, ctx, page = _get_pw_page_impl()
            if page is None:
                return {"success": False, "error": "No page"}
            try:
                page.fill(selector, value, timeout=10000)
                return {"success": True}
            except Exception as e:
                return {"success": False, "error": str(e)}
    result = _run_in_pw_thread(_op)
    if result is not None:
        return result
    return {"success": False, "error": "Playwright thread failed"}

def _pw_type_text(selector, value):
    """Type text in the dedicated Playwright thread."""
    def _op():
        with _pw_lock:
            pw, br, ctx, page = _get_pw_page_impl()
            if page is None:
                return {"success": False, "error": "No page"}
            try:
                page.click(selector, timeout=5000)
                page.keyboard.type(value, delay=50)
                return {"success": True}
            except Exception as e:
                return {"success": False, "error": str(e)}
    result = _run_in_pw_thread(_op)
    if result is not None:
        return result
    return {"success": False, "error": "Playwright thread failed"}

def _pw_press_key(key):
    """Press key in the dedicated Playwright thread."""
    def _op():
        with _pw_lock:
            pw, br, ctx, page = _get_pw_page_impl()
            if page is None:
                return {"success": False, "error": "No page"}
            try:
                page.keyboard.press(key)
                page.wait_for_timeout(500)
                return {"success": True, "url": page.url}
            except Exception as e:
                return {"success": False, "error": str(e)}
    result = _run_in_pw_thread(_op)
    if result is not None:
        return result
    return {"success": False, "error": "Playwright thread failed"}

def _pw_screenshot():
    """Take screenshot in the dedicated Playwright thread."""
    def _op():
        with _pw_lock:
            pw, br, ctx, page = _get_pw_page_impl()
            if page is None:
                return None
            return _take_screenshot_safe(page)
    result = _run_in_pw_thread(_op)
    if result is not None:
        return result
    return {"success": False, "error": "Playwright thread failed"}

def _pw_execute_js(code_str):
    """Execute JS in the dedicated Playwright thread."""
    def _op():
        with _pw_lock:
            pw, br, ctx, page = _get_pw_page_impl()
            if page is None:
                return {"success": False, "error": "No page"}
            try:
                result = page.evaluate(code_str)
                return {"success": True, "result": result}
            except Exception as e:
                return {"success": False, "error": str(e)}
    result = _run_in_pw_thread(_op)
    if result is not None:
        return result
    return {"success": False, "error": "Playwright thread failed"}

def _pw_select_option(selector, value):
    """Select option in the dedicated Playwright thread."""
    def _op():
        with _pw_lock:
            pw, br, ctx, page = _get_pw_page_impl()
            if page is None:
                return {"success": False, "error": "No page"}
            try:
                page.select_option(selector, value, timeout=10000)
                return {"success": True}
            except Exception as e:
                return {"success": False, "error": str(e)}
    result = _run_in_pw_thread(_op)
    if result is not None:
        return result
    return {"success": False, "error": "Playwright thread failed"}

def _pw_wait_for(selector=None, url_pattern=None, timeout=15000):
    """Wait for element or URL in the dedicated Playwright thread."""
    def _op():
        with _pw_lock:
            pw, br, ctx, page = _get_pw_page_impl()
            if page is None:
                return {"success": False, "error": "No page"}
            try:
                if selector:
                    page.wait_for_selector(selector, timeout=timeout)
                if url_pattern:
                    page.wait_for_url(url_pattern, timeout=timeout)
                return {"success": True, "url": page.url}
            except Exception as e:
                return {"success": False, "error": str(e)}
    result = _run_in_pw_thread(_op)
    if result is not None:
        return result
    return {"success": False, "error": "Playwright thread failed"}

def _pw_get_page_text():
    """Get page text content in the dedicated Playwright thread."""
    def _op():
        with _pw_lock:
            pw, br, ctx, page = _get_pw_page_impl()
            if page is None:
                return ""
            try:
                return page.evaluate("() => document.body?.innerText || ''")
            except Exception:
                return ""
    result = _run_in_pw_thread(_op)
    if result is not None:
        return result
    return {"success": False, "error": "Playwright thread failed"}

def _pw_scroll(direction="down", amount=500):
    """Scroll page in the dedicated Playwright thread."""
    def _op():
        with _pw_lock:
            pw, br, ctx, page = _get_pw_page_impl()
            if page is None:
                return {"success": False, "error": "No page"}
            try:
                if direction == "down":
                    page.evaluate(f"window.scrollBy(0, {amount})")
                elif direction == "up":
                    page.evaluate(f"window.scrollBy(0, -{amount})")
                page.wait_for_timeout(500)
                screenshot = _take_screenshot_safe(page)
                return {"success": True, "screenshot": screenshot}
            except Exception as e:
                return {"success": False, "error": str(e)}
    result = _run_in_pw_thread(_op)
    if result is not None:
        return result
    return {"success": False, "error": "Playwright thread failed"}

def _pw_hover(selector):
    """Hover over element in the dedicated Playwright thread."""
    def _op():
        with _pw_lock:
            pw, br, ctx, page = _get_pw_page_impl()
            if page is None:
                return {"success": False, "error": "No page"}
            try:
                page.hover(selector, timeout=10000)
                return {"success": True}
            except Exception as e:
                return {"success": False, "error": str(e)}
    result = _run_in_pw_thread(_op)
    if result is not None:
        return result
    return {"success": False, "error": "Playwright thread failed"}

def _pw_get_elements(selector):
    """Get elements in the dedicated Playwright thread."""
    def _op():
        with _pw_lock:
            pw, br, ctx, page = _get_pw_page_impl()
            if page is None:
                return []
            try:
                return page.evaluate(f"""() => {{
                    return Array.from(document.querySelectorAll('{selector}')).slice(0, 50).map((el, i) => ({{
                        index: i,
                        tag: el.tagName.toLowerCase(),
                        text: el.innerText?.trim()?.substring(0, 200) || '',
                        href: el.href || '',
                        value: el.value || '',
                        id: el.id || '',
                        className: el.className || '',
                        type: el.type || '',
                        name: el.name || ''
                    }}))
                }}""")
            except Exception:
                return []
    result = _run_in_pw_thread(_op)
    if result is not None:
        return result
    return {"success": False, "error": "Playwright thread failed"}


def _get_pw_page(url: str = None, width: int = 1280, height: int = 800):
    """Wrapper that runs _get_pw_page_impl in a dedicated thread to avoid asyncio conflicts."""
    try:
        return _run_in_pw_thread(_get_pw_page_impl, url, width, height)
    except Exception as e:
        logger.error(f"[PW] _get_pw_page thread wrapper error: {e}")
        return None, None, None, None


# B2: Heavy page timeout patterns
HEAVY_PAGE_PATTERNS = [
    "install", "setup", "wizard", "bitrix", "bitrixsetup",
    "wp-admin/install", "phpmyadmin"
]

def _get_timeout(url):
    url_lower = url.lower()
    for pattern in HEAVY_PAGE_PATTERNS:
        if pattern in url_lower:
            return 300000  # 5 minutes
    return 90000  # 90 seconds default


class BrowserAgent:
    """Universal browser agent for web automation with user takeover support."""

    def __init__(self, timeout=30):
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                          "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
        })
        self.history = []
        self._last_screenshot_b64 = None
        self._current_url = None
        # Директория для скриншотов takeover
        self._screenshot_dir = "/var/www/orion/backend/static/screenshots"
        os.makedirs(self._screenshot_dir, exist_ok=True)
    def _run_pw(self, fn):
        """Run a function that uses Playwright page in the dedicated thread."""
        try:
            return _run_in_pw_thread(fn)
        except Exception as e:
            logger.error(f"[PW] _run_pw error: {e}")
            return None



    # ══════════════════════════════════════════════════════════════════
    # ██ НАВИГАЦИЯ ██
    # ══════════════════════════════════════════════════════════════════

    def navigate(self, url: str) -> dict:
        """Перейти по URL и вернуть результат."""
        if not _playwright_available:
            return {"success": False, "error": "Playwright не установлен."}
            
        def _do_navigate():
            try:
                _, _, _, page = _get_pw_page_impl(url)
                if page is None:
                    return {"success": False, "error": "Не удалось создать страницу."}
                
                # Ждем загрузки
                try:
                    page.wait_for_load_state("networkidle", timeout=10000)
                except Exception:
                    pass
                    
                screenshot = _take_screenshot_safe(page)
                title = ""
                try:
                    title = page.title()
                except Exception:
                    pass
                    
                return {
                    "success": True,
                    "url": page.url,
                    "title": title,
                    "screenshot": screenshot
                }
            except Exception as e:
                return {"success": False, "error": str(e)}
                
        try:
            res = _run_in_pw_thread(_do_navigate)
            if res and res.get("success"):
                self._last_screenshot_b64 = res.get("screenshot")
            return res or {"success": False, "error": "Timeout"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def click(self, selector: str, timeout: int = 8000) -> dict:
        """Кликнуть по элементу по CSS-селектору."""
        if not _playwright_available:
            return {"success": False, "error": "Playwright не установлен."}
        def _do():
            _, _, _, page = _get_pw_page()
            if page is None:
                return {"success": False, "error": "Нет активной страницы."}
            page.click(selector, timeout=timeout)
            page.wait_for_timeout(600)
            screenshot = _take_screenshot_safe(page)
            self._last_screenshot_b64 = screenshot
            return {"success": True, "clicked": selector, "screenshot": screenshot}
        try:
            return _run_in_pw_thread(_do)
        except Exception as e:
            return {"success": False, "selector": selector, "error": str(e)}

    def fill(self, selector: str, value: str, timeout: int = 8000) -> dict:
        """Заполнить поле ввода по CSS-селектору."""
        if not _playwright_available:
            return {"success": False, "error": "Playwright не установлен."}
        def _do():
            _, _, _, page = _get_pw_page()
            if page is None:
                return {"success": False, "error": "Нет активной страницы."}
            page.fill(selector, value, timeout=timeout)
            page.wait_for_timeout(300)
            screenshot = _take_screenshot_safe(page)
            self._last_screenshot_b64 = screenshot
            return {"success": True, "filled": selector, "value": value, "screenshot": screenshot}
        try:
            return _run_in_pw_thread(_do)
        except Exception as e:
            return {"success": False, "selector": selector, "error": str(e)}

    def hover(self, selector: str) -> dict:
        """Навести курсор на элемент (для показа скрытых меню)."""
        if not _playwright_available:
            return {"success": False, "error": "Playwright не установлен."}
        try:
            res = _pw_hover(selector)
            if res and res.get("success"):
                self._last_screenshot_b64 = res.get("screenshot")
            return res or {"success": False, "error": "hover failed"}
        except Exception as e:
            return {"success": False, "selector": selector, "error": str(e)}

    # ══════════════════════════════════════════════════════════════════
    # ██ JAVASCRIPT И ОЖИДАНИЕ ██
    # ══════════════════════════════════════════════════════════════════

    def execute_js(self, code: str) -> dict:
        """Выполнить произвольный JavaScript на текущей странице."""
        if not _playwright_available:
            return {"success": False, "error": "Playwright не установлен."}
        try:
            res = _pw_execute_js(code)
            if res and res.get("success"):
                self._last_screenshot_b64 = res.get("screenshot")
            return res or {"success": False, "error": "execute_js failed"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def wait_for(self, selector: str = None, url_contains: str = None,
                 timeout: int = 15000) -> dict:
        """
        Ждать появления элемента или смены URL.
        selector — CSS-селектор элемента
        url_contains — подстрока в URL
        """
        if not _playwright_available:
            return {"success": False, "error": "Playwright не установлен."}
        try:
            url_pattern = f"**{url_contains}**" if url_contains else None
            res = _pw_wait_for(selector=selector, url_pattern=url_pattern, timeout=timeout)
            if res and res.get("success"):
                self._last_screenshot_b64 = res.get("screenshot")
            return res or {"success": False, "error": "wait_for failed"}
        except Exception as e:
            return {"success": False, "error": str(e),
                    "url": _pw_page.url if _pw_page and not _pw_page.is_closed() else ""}

    def get_elements(self, selector: str, limit: int = 50) -> dict:
        """Получить список элементов с текстом и атрибутами."""
        if not _playwright_available:
            return {"success": False, "error": "Playwright не установлен."}
        try:
            with _pw_lock:
                _, _, _, page = _get_pw_page()
                if page is None:
                    return {"success": False, "error": "Нет активной страницы."}

                elements = page.evaluate(f"""(() => {{
                    const els = document.querySelectorAll('{selector}');
                    const result = [];
                    for (let i = 0; i < Math.min(els.length, {limit}); i++) {{
                        const el = els[i];
                        result.push({{
                            tag: el.tagName.toLowerCase(),
                            text: (el.textContent || '').trim().substring(0, 100),
                            id: el.id || '',
                            class: (el.className || '').substring(0, 80),
                            href: el.getAttribute('href') || '',
                            value: el.value || '',
                            type: el.type || '',
                            name: el.name || '',
                            st: el.getAttribute('st') || '',
                            visible: el.offsetParent !== null,
                            rect: el.getBoundingClientRect()
                        }});
                    }}
                    return result;
                }})()""")

                return {
                    "success": True,
                    "selector": selector,
                    "count": len(elements),
                    "elements": elements
                }
        except Exception as e:
            return {"success": False, "selector": selector, "error": str(e)}

    def screenshot(self) -> dict:
        """Сделать скриншот текущей страницы."""
        if not _playwright_available:
            return {"success": False, "error": "Playwright не установлен."}
        
        def _do_screenshot():
            _, _, _, page = _get_pw_page_impl()
            if page is None:
                return {"success": False, "error": "Нет активной страницы."}
            screenshot = _take_screenshot_safe(page)
            url = page.url
            title = ""
            try:
                title = page.title()
            except Exception:
                pass
            return {
                "success": True,
                "url": url,
                "title": title,
                "screenshot": screenshot
            }
            
        try:
            with _pw_lock:
                res = _run_in_pw_thread(_do_screenshot)
                if res and res.get("success"):
                    self._last_screenshot_b64 = res.get("screenshot")
                return res or {"success": False, "error": "Timeout"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def get_page_info(self) -> dict:
        """Получить полную информацию о текущей странице."""
        if not _playwright_available:
            return {"success": False, "error": "Playwright не установлен."}
            
        def _do_get_page_info():
            _, _, _, page = _get_pw_page_impl()
            if page is None:
                return {"success": False, "error": "Нет активной страницы."}
                
            url = page.url
            title = ""
            try:
                title = page.title()
            except Exception:
                pass
                
            html = ""
            try:
                html = page.content()
            except Exception:
                pass
                
            screenshot = _take_screenshot_safe(page)
            
            return {
                "success": True,
                "url": url,
                "title": title,
                "html": html,
                "screenshot": screenshot
            }
            
        try:
            with _pw_lock:
                res = _run_in_pw_thread(_do_get_page_info)
                if res and res.get("success"):
                    self._last_screenshot_b64 = res.get("screenshot")
                return res or {"success": False, "error": "Timeout"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    # ══════════════════════════════════════════════════════════════════
    # ██ SMART LOGIN — автоматический вход в любой ЛК ██
    # ══════════════════════════════════════════════════════════════════

    def smart_login(self, url: str, login: str, password: str) -> dict:
        """
        Автоматический вход в любой личный кабинет.
        Пробует несколько стратегий:
        1. Найти поля по id/name/type и заполнить
        2. Отправить форму через Enter
        3. Кликнуть кнопку submit
        4. JavaScript submit
        Если не удалось — вернёт ask_user с причиной.
        """
        if not _playwright_available:
            return {"success": False, "error": "Playwright не установлен."}

        try:
            # Шаг 1: Открыть страницу
            nav = self.navigate(url)
            if not nav.get("success"):
                return nav

            with _pw_lock:
                _, _, _, page = _get_pw_page()
                if page is None:
                    return {"success": False, "error": "Нет активной страницы."}

                url_before = page.url

                # Шаг 2: Найти поле логина (пробуем разные селекторы)
                login_selectors = [
                    '#login', '#username', '#email', '#user',
                    'input[name="login"]', 'input[name="username"]',
                    'input[name="email"]', 'input[name="user"]',
                    'input[type="text"]', 'input[type="email"]',
                    'input[autocomplete="username"]',
                ]
                login_filled = False
                login_selector_used = ""
                for sel in login_selectors:
                    try:
                        el = page.query_selector(sel)
                        if el and el.is_visible():
                            page.fill(sel, login, timeout=3000)
                            _trigger_input_events(page, sel)
                            login_filled = True
                            login_selector_used = sel
                            break
                    except Exception:
                        continue

                if not login_filled:
                    return {
                        "success": False,
                        "error": "Не удалось найти поле логина",
                        "need_user_takeover": True,
                        "reason": "captcha_or_unusual_form",
                        "screenshot": _take_screenshot_safe(page),
                        "url": page.url
                    }

                page.wait_for_timeout(300)

                # Шаг 3: Найти поле пароля
                password_selectors = [
                    '#password', '#pass', '#passwd',
                    'input[name="password"]', 'input[name="pass"]',
                    'input[name="passwd"]',
                    'input[type="password"]',
                ]
                password_filled = False
                password_selector_used = ""
                for sel in password_selectors:
                    try:
                        el = page.query_selector(sel)
                        if el and el.is_visible():
                            page.fill(sel, password, timeout=3000)
                            _trigger_input_events(page, sel)
                            password_filled = True
                            password_selector_used = sel
                            break
                    except Exception:
                        continue

                if not password_filled:
                    return {
                        "success": False,
                        "error": "Не удалось найти поле пароля",
                        "need_user_takeover": True,
                        "reason": "password_field_not_found",
                        "screenshot": _take_screenshot_safe(page),
                        "url": page.url
                    }

                page.wait_for_timeout(300)

                # Шаг 4: Отправить форму (несколько стратегий)
                submitted = False

                # 4a: Нажать Enter в поле пароля
                try:
                    page.click(password_selector_used, timeout=2000)
                    page.keyboard.press("Enter")
                    try:
                        page.wait_for_load_state("networkidle", timeout=12000)
                    except Exception:
                        page.wait_for_timeout(5000)
                    if page.url != url_before:
                        submitted = True
                except Exception:
                    pass

                # 4b: Кликнуть submit кнопку
                if not submitted:
                    submit_selectors = [
                        'button[type="submit"]', 'input[type="submit"]',
                        'button:has-text("Войти")', 'button:has-text("Login")',
                        'button:has-text("Sign in")', 'button:has-text("Вход")',
                        '.login-btn', '.submit-btn', '#login-btn',
                    ]
                    for sel in submit_selectors:
                        try:
                            el = page.query_selector(sel)
                            if el and el.is_visible():
                                el.click()
                                try:
                                    page.wait_for_load_state("networkidle", timeout=12000)
                                except Exception:
                                    page.wait_for_timeout(5000)
                                if page.url != url_before:
                                    submitted = True
                                    break
                        except Exception:
                            continue

                # 4c: JavaScript submit
                if not submitted:
                    try:
                        page.evaluate("document.querySelector('form').submit()")
                        try:
                            page.wait_for_load_state("networkidle", timeout=12000)
                        except Exception:
                            page.wait_for_timeout(5000)
                        if page.url != url_before:
                            submitted = True
                    except Exception:
                        pass

                page.wait_for_timeout(1000)
                screenshot = _take_screenshot_safe(page)
                self._last_screenshot_b64 = screenshot
                url_after = page.url

                # Проверяем результат
                login_success = url_after != url_before
                # Дополнительная проверка: ищем признаки успешного входа
                if not login_success:
                    try:
                        body_text = page.evaluate("document.body.innerText.substring(0, 1000)")
                        # Если на странице есть ошибка авторизации
                        error_patterns = ["неверн", "invalid", "incorrect", "wrong", "ошибк", "error"]
                        has_error = any(p in body_text.lower() for p in error_patterns)
                        # Проверяем наличие капчи
                        has_captcha = page.evaluate("""!!document.querySelector(
                            '[class*="captcha"], [id*="captcha"], iframe[src*="recaptcha"], iframe[src*="hcaptcha"]'
                        )""")
                        if has_captcha:
                            # PATCH 7: Try auto-solve captcha before asking user
                            logger.info('[Captcha] Captcha detected in smart_login, attempting auto-solve')
                            captcha_result = self.solve_captcha(page)
                            if captcha_result.get('solved'):
                                logger.info(f'[Captcha] Auto-solved: {captcha_result}')
                                # Re-submit form after solving
                                try:
                                    page.keyboard.press('Enter')
                                    try:
                                        page.wait_for_load_state('networkidle', timeout=10000)
                                    except Exception:
                                        page.wait_for_timeout(4000)
                                    url_after = page.url
                                    login_success = url_after != url_before
                                    screenshot = _take_screenshot_safe(page)
                                except Exception:
                                    pass
                            if not captcha_result.get('solved') or not login_success:
                                return {
                                    "success": False,
                                    "error": "Обнаружена CAPTCHA. Автоматическое решение не удалось.",
                                    "need_user_takeover": True,
                                    "reason": "captcha",
                                    "captcha_solve_result": captcha_result,
                                    "screenshot": screenshot,
                                    "url": url_after
                                }
                        if has_error:
                            return {
                                "success": False,
                                "error": "Неверный логин или пароль",
                                "screenshot": screenshot,
                                "url": url_after
                            }
                    except Exception:
                        pass

                return {
                    "success": login_success,
                    "url_before": url_before,
                    "url_after": url_after,
                    "navigated": login_success,
                    "login_selector": login_selector_used,
                    "password_selector": password_selector_used,
                    "screenshot": screenshot,
                    "need_user_takeover": not login_success,
                    "reason": "login_failed" if not login_success else None
                }

        except Exception as e:
            return {"success": False, "error": str(e)}

    # ══════════════════════════════════════════════════════════════════
    # ██ PATCH 7: RUCAPTCHA — автоматическое решение капчи ██
    # ══════════════════════════════════════════════════════════════════

    def solve_captcha(self, page) -> dict:
        """
        PATCH 7: Автоматически определить и решить капчу на странице.
        Поддерживает: reCAPTCHA v2/v3, hCaptcha, ImageCaptcha.
        API ключ берётся через get_setting('rucaptcha_api_key').
        """
        try:
            # Получить API ключ из настроек
            try:
                from app import get_setting as _get_setting
                api_key = _get_setting('rucaptcha_api_key')
            except Exception:
                api_key = os.environ.get('RUCAPTCHA_API_KEY', '')

            if not api_key:
                logger.warning('[Captcha] rucaptcha_api_key not set, skipping captcha solve')
                return {'solved': False, 'reason': 'no_api_key'}

            page_url = page.url

            # 1. Проверить reCAPTCHA v2/v3
            try:
                sitekey = page.evaluate(
                    "document.querySelector('[data-sitekey]')?.getAttribute('data-sitekey')"
                )
            except Exception:
                sitekey = None

            if sitekey:
                logger.info(f'[Captcha] reCAPTCHA detected, sitekey={sitekey[:20]}...')
                try:
                    from python_rucaptcha.re_captcha import ReCaptcha
                    result = ReCaptcha(
                        rucaptcha_key=api_key,
                        websiteURL=page_url,
                        websiteKey=sitekey,
                        method='userrecaptcha'
                    ).captcha_handler()
                    if result.get('error'):
                        return {'solved': False, 'reason': result['error']}
                    token = result.get('captchaSolve', '')
                    if token:
                        page.evaluate(f"""
                            var el = document.querySelector('#g-recaptcha-response');
                            if (el) el.value = '{token}';
                            if (typeof ___grecaptcha_cfg !== 'undefined') {{
                                Object.keys(___grecaptcha_cfg.clients).forEach(k => {{
                                    var client = ___grecaptcha_cfg.clients[k];
                                    Object.keys(client).forEach(k2 => {{
                                        if (client[k2] && client[k2].callback) client[k2].callback('{token}');
                                    }});
                                }});
                            }}
                        """)
                        logger.info('[Captcha] reCAPTCHA solved and token injected')
                        return {'solved': True, 'type': 'recaptcha', 'token': token[:20] + '...'}
                except ImportError:
                    logger.warning('[Captcha] python_rucaptcha not installed')
                    return {'solved': False, 'reason': 'python_rucaptcha not installed'}
                except Exception as e:
                    return {'solved': False, 'reason': str(e)}

            # 2. Проверить hCaptcha
            try:
                hcaptcha_sitekey = page.evaluate(
                    "document.querySelector('[data-hcaptcha-sitekey], .h-captcha[data-sitekey]')?.getAttribute('data-sitekey')"
                )
            except Exception:
                hcaptcha_sitekey = None

            if hcaptcha_sitekey:
                logger.info(f'[Captcha] hCaptcha detected, sitekey={hcaptcha_sitekey[:20]}...')
                try:
                    from python_rucaptcha.h_captcha import HCaptcha
                    result = HCaptcha(
                        rucaptcha_key=api_key,
                        websiteURL=page_url,
                        websiteKey=hcaptcha_sitekey
                    ).captcha_handler()
                    if result.get('error'):
                        return {'solved': False, 'reason': result['error']}
                    token = result.get('captchaSolve', '')
                    if token:
                        page.evaluate(f"""
                            var el = document.querySelector('[name="h-captcha-response"]');
                            if (el) el.value = '{token}';
                        """)
                        logger.info('[Captcha] hCaptcha solved and token injected')
                        return {'solved': True, 'type': 'hcaptcha', 'token': token[:20] + '...'}
                except ImportError:
                    return {'solved': False, 'reason': 'python_rucaptcha not installed'}
                except Exception as e:
                    return {'solved': False, 'reason': str(e)}

            # 3. Проверить обычную картинку-капчу (img с captcha в src/class/id)
            try:
                captcha_img_src = page.evaluate("""
                    (function() {
                        var imgs = document.querySelectorAll('img');
                        for (var i = 0; i < imgs.length; i++) {
                            var src = imgs[i].src || '';
                            var cls = imgs[i].className || '';
                            var id = imgs[i].id || '';
                            if (src.includes('captcha') || cls.includes('captcha') || id.includes('captcha')) {
                                return src;
                            }
                        }
                        return null;
                    })()
                """)
            except Exception:
                captcha_img_src = None

            if captcha_img_src:
                logger.info(f'[Captcha] Image captcha detected: {captcha_img_src[:50]}')
                try:
                    from python_rucaptcha.image_captcha import ImageCaptcha
                    result = ImageCaptcha(
                        rucaptcha_key=api_key
                    ).captcha_handler(captcha_link=captcha_img_src)
                    if result.get('error'):
                        return {'solved': False, 'reason': result['error']}
                    text = result.get('captchaSolve', '')
                    if text:
                        # Попытаться найти поле ввода капчи
                        for sel in ['input[name*="captcha"]', 'input[id*="captcha"]', '#captcha', '.captcha-input']:
                            try:
                                el = page.query_selector(sel)
                                if el and el.is_visible():
                                    page.fill(sel, text)
                                    break
                            except Exception:
                                continue
                        logger.info(f'[Captcha] Image captcha solved: {text}')
                        return {'solved': True, 'type': 'image', 'text': text}
                except ImportError:
                    return {'solved': False, 'reason': 'python_rucaptcha not installed'}
                except Exception as e:
                    return {'solved': False, 'reason': str(e)}

            return {'solved': False, 'reason': 'no_captcha_detected'}

        except Exception as e:
            logger.error(f'[Captcha] solve_captcha error: {e}')
            return {'solved': False, 'reason': str(e)}

    # ══════════════════════════════════════════════════════════════════
    # ██ ПЕРЕДАЧА УПРАВЛЕНИЯ ПОЛЬЗОВАТЕЛЮ (TAKEOVER) ██
    # ══════════════════════════════════════════════════════════════════

    def ask_user(self, reason: str, instruction: str = "") -> dict:
        """
        Передать управление браузером пользователю.

        Механизм работы:
        1. Делает скриншот текущей страницы
        2. Сохраняет скриншот как файл (для показа в чате)
        3. Возвращает специальный event type="browser_takeover_request"
        4. Фронтенд показывает скриншот + инструкцию + кнопку "Готово"
        5. Пользователь может:
           a) Ввести логин/пароль прямо в чат → агент заполнит
           b) Нажать "Открыть браузер" → noVNC iframe → сам вводит
           c) Просто нажать "Готово" когда закончил

        reason: причина запроса (captcha, 2fa, login_failed, unusual_form)
        instruction: что пользователь должен сделать
        """
        screenshot = ""
        url = ""
        page_title = ""

        if _playwright_available and _pw_page and not _pw_page.is_closed():
            try:
                with _pw_lock:
                    screenshot = _take_screenshot_safe(_pw_page)
                    url = _pw_page.url
                    page_title = _pw_page.title()
            except Exception:
                pass

        # Сохраняем скриншот как файл для показа в чате
        screenshot_url = ""
        if screenshot:
            try:
                filename = f"takeover_{uuid.uuid4().hex[:8]}.png"
                filepath = os.path.join(self._screenshot_dir, filename)
                with open(filepath, "wb") as f:
                    f.write(base64.b64decode(screenshot))
                screenshot_url = f"/static/screenshots/{filename}"
            except Exception:
                pass

        # Формируем сообщения в зависимости от причины
        messages = {
            "captcha": "🔒 Обнаружена CAPTCHA. Пожалуйста, решите её и нажмите 'Готово'.",
            "2fa": "🔐 Требуется двухфакторная аутентификация. Введите код и нажмите 'Готово'.",
            "login_failed": "🔑 Не удалось войти автоматически. Пожалуйста, войдите вручную и нажмите 'Готово'.",
            "unusual_form": "⚠️ Необычная форма входа. Пожалуйста, заполните её и нажмите 'Готово'.",
            "confirmation": "✅ Требуется подтверждение действия. Проверьте и нажмите 'Готово'.",
            "custom": instruction or "Требуется ваше участие. Выполните действие и нажмите 'Готово'."
        }

        message = messages.get(reason, messages["custom"])
        if instruction and reason != "custom":
            message += f"\n\n📋 {instruction}"

        self._last_screenshot_b64 = screenshot

        return {
            "success": True,
            "type": "browser_takeover_request",
            "reason": reason,
            "message": message,
            "instruction": instruction,
            "url": url,
            "page_title": page_title,
            "screenshot": screenshot,
            "screenshot_url": screenshot_url,
            "actions": [
                {"id": "credentials", "label": "🔑 Ввести логин/пароль", "type": "input"},
                {"id": "manual", "label": "🖥️ Открыть браузер", "type": "vnc"},
                {"id": "done", "label": "✅ Готово", "type": "confirm"},
                {"id": "skip", "label": "⏭️ Пропустить", "type": "skip"}
            ]
        }

    def takeover_done(self) -> dict:
        """
        Вызывается после того как пользователь закончил ручной ввод.
        Делает скриншот и возвращает текущее состояние страницы.
        """
        if not _playwright_available:
            return {"success": False, "error": "Playwright не установлен."}
        try:
            with _pw_lock:
                _, _, _, page = _get_pw_page()
                if page is None:
                    return {"success": False, "error": "Нет активной страницы."}

                # Ждём стабилизации после действий пользователя
                try:
                    page.wait_for_load_state("networkidle", timeout=5000)
                except Exception:
                    page.wait_for_timeout(2000)

                screenshot = _take_screenshot_safe(page)
                self._last_screenshot_b64 = screenshot
                info = self._extract_page_info(page)

                return {
                    "success": True,
                    "url": page.url,
                    "title": page.title(),
                    "page_info": info,
                    "screenshot": screenshot
                }
        except Exception as e:
            return {"success": False, "error": str(e)}

    # ══════════════════════════════════════════════════════════════════
    # ██ SELECT / DROPDOWN ██
    # ══════════════════════════════════════════════════════════════════

    def select_option(self, selector: str, value: str, timeout: int = 8000) -> dict:
        """
        Выбрать значение из dropdown.
        Работает с нативным <select> и Vuetify/Material UI dropdowns.
        """
        if not _playwright_available:
            return {"success": False, "error": "Playwright не установлен."}
        try:
            with _pw_lock:
                _, _, _, page = _get_pw_page()
                if page is None:
                    return {"success": False, "error": "Нет активной страницы."}

                selected = False
                error_msg = ""

                # Стратегия 1: Нативный <select>
                try:
                    tag = page.evaluate(f"document.querySelector('{selector}')?.tagName?.toLowerCase()")
                    if tag == "select":
                        try:
                            page.select_option(selector, value=value, timeout=timeout)
                            selected = True
                        except Exception:
                            page.select_option(selector, label=value, timeout=timeout)
                            selected = True
                except Exception as e1:
                    error_msg = str(e1)

                # Стратегия 2: Vuetify/Material dropdown (click + выбор из списка)
                if not selected:
                    try:
                        page.click(selector, timeout=3000)
                        page.wait_for_timeout(500)
                        # Ищем опцию в открытом dropdown
                        option_selectors = [
                            f'.v-list-item:has-text("{value}")',
                            f'.v-menu__content .v-list-item:has-text("{value}")',
                            f'[role="option"]:has-text("{value}")',
                            f'.dropdown-item:has-text("{value}")',
                            f'li:has-text("{value}")',
                        ]
                        for opt_sel in option_selectors:
                            try:
                                el = page.query_selector(opt_sel)
                                if el and el.is_visible():
                                    el.click()
                                    selected = True
                                    break
                            except Exception:
                                continue
                    except Exception as e2:
                        error_msg += f" | vuetify: {e2}"

                page.wait_for_timeout(400)
                screenshot = _take_screenshot_safe(page)
                self._last_screenshot_b64 = screenshot

                return {
                    "success": selected,
                    "selector": selector,
                    "value": value,
                    "screenshot": screenshot,
                    "error": error_msg if not selected else None
                }
        except Exception as e:
            return {"success": False, "selector": selector, "error": str(e)}

    # ══════════════════════════════════════════════════════════════════
    # ██ LEGACY МЕТОДЫ (совместимость) ██
    # ══════════════════════════════════════════════════════════════════

    def check_site(self, url):
        """Check if a website is accessible."""
        result = self.navigate(url)
        if not result.get("success"):
            return result
        return {
            "success": True,
            "url": result.get("url", url),
            "status_code": result.get("status_code", 200),
            "title": result.get("title", ""),
            "screenshot": result.get("screenshot")
        }

    def check_api(self, url, method="GET", data=None, headers=None):
        """Check an API endpoint."""
        try:
            if not url.startswith(("http://", "https://")):
                url = "https://" + url
            extra_headers = {"Content-Type": "application/json"}
            if headers:
                extra_headers.update(headers)
            start = time.time()
            if method.upper() == "GET":
                resp = self.session.get(url, headers=extra_headers, timeout=self.timeout, verify=_ssl_verify(url))
            elif method.upper() == "POST":
                resp = self.session.post(url, json=data, headers=extra_headers, timeout=self.timeout, verify=_ssl_verify(url))
            elif method.upper() == "PUT":
                resp = self.session.put(url, json=data, headers=extra_headers, timeout=self.timeout, verify=_ssl_verify(url))
            elif method.upper() == "DELETE":
                resp = self.session.delete(url, headers=extra_headers, timeout=self.timeout, verify=_ssl_verify(url))
            else:
                return {"success": False, "error": f"Unsupported method: {method}"}
            elapsed = round((time.time() - start) * 1000)
            try:
                json_response = resp.json()
            except Exception:
                json_response = None
            return {
                "success": True, "url": resp.url, "method": method.upper(),
                "status_code": resp.status_code, "response_time_ms": elapsed,
                "json": json_response,
                "text": resp.text[:20000] if not json_response else None,
                "headers": dict(resp.headers)
            }
        except Exception as e:
            return {"success": False, "url": url, "error": str(e)}

    def get_text(self, url):
        """Get clean text content from a webpage."""
        result = self.navigate(url)
        if not result or not result.get("success"):
            return result or {"success": False, "error": "navigate returned None"}
        try:
            with _pw_lock:
                _cur_page = getattr(_pw_local, 'page', None) or _pw_page
                if _cur_page and not _cur_page.is_closed():
                    text = _cur_page.evaluate("document.body.innerText")
                    if len(text) > 20000:
                        text = text[:20000] + "... [truncated]"
                    return {
                        "success": True, "url": result.get("url", url),
                        "text": text, "screenshot": result.get("screenshot")
                    }
        except Exception:
            pass
        return result

    def get_links(self, url):
        """Extract all links from a webpage."""
        result = self.navigate(url)
        if not result.get("success"):
            return result
        try:
            with _pw_lock:
                if _pw_page and not _pw_page.is_closed():
                    links = _pw_page.evaluate("""() => {
                        return Array.from(document.querySelectorAll('a[href]'))
                            .map(a => ({text: a.textContent.trim().substring(0, 50), href: a.href}))
                            .filter(l => l.href && !l.href.startsWith('javascript:'))
                            .slice(0, 200);
                    }""")
                    return {
                        "success": True, "url": result.get("url", url),
                        "links": links, "count": len(links),
                        "screenshot": result.get("screenshot")
                    }
        except Exception:
            pass
        return result

    def post_data(self, url, data=None, json_data=None, headers=None):
        """Send POST request."""
        try:
            if not url.startswith(("http://", "https://")):
                url = "https://" + url
            resp = self.session.post(
                url, data=data, json=json_data,
                headers=headers or {}, timeout=self.timeout, verify=_ssl_verify(url)
            )
            return {
                "success": True, "url": resp.url,
                "status_code": resp.status_code,
                "response": resp.text[:50000]
            }
        except Exception as e:
            return {"success": False, "url": url, "error": str(e)}

    def screenshot_check(self, url):
        """Check visual aspects of a site + screenshot."""
        return self.navigate(url)

    def detect_login_form(self, url=None):
        """Detect login form on page."""
        if url:
            self.navigate(url)
        return self.get_page_info()

    def submit(self, selector=None, timeout=10000):
        """Submit a form."""
        if selector:
            return self.click(selector, timeout)
        else:
            return self.press_key("Enter")

    def select(self, selector, value, timeout=8000):
        """Legacy select method."""
        return self.select_option(selector, value, timeout)

    # ══════════════════════════════════════════════════════════════════
    # ██ FTP ИНСТРУМЕНТЫ ██
    # ══════════════════════════════════════════════════════════════════

    def ftp_upload(self, host, username, password, remote_path, content,
                   port=21, encoding="utf-8"):
        """Загрузить файл на FTP сервер."""
        try:
            ftp = ftplib.FTP()
            ftp.connect(host, port, timeout=30)
            ftp.login(username, password)
            remote_dir = "/".join(remote_path.split("/")[:-1])
            if remote_dir and remote_dir != "/":
                self._ftp_makedirs(ftp, remote_dir)
            content_bytes = content.encode(encoding) if isinstance(content, str) else content
            ftp.storbinary(f"STOR {remote_path}", io.BytesIO(content_bytes))
            size = len(content_bytes)
            ftp.quit()
            return {"success": True, "host": host, "remote_path": remote_path,
                    "size_bytes": size, "message": f"Файл загружен: {remote_path} ({size} байт)"}
        except Exception as e:
            return {"success": False, "error": str(e), "host": host, "path": remote_path}

    def ftp_download(self, host, username, password, remote_path, port=21):
        """Скачать файл с FTP сервера."""
        try:
            ftp = ftplib.FTP()
            ftp.connect(host, port, timeout=30)
            ftp.login(username, password)
            buf = io.BytesIO()
            ftp.retrbinary(f"RETR {remote_path}", buf.write)
            ftp.quit()
            content_bytes = buf.getvalue()
            try:
                content = content_bytes.decode("utf-8")
            except UnicodeDecodeError:
                try:
                    content = content_bytes.decode("cp1251")
                except Exception:
                    content = base64.b64encode(content_bytes).decode("ascii")
            return {"success": True, "host": host, "remote_path": remote_path,
                    "size_bytes": len(content_bytes), "content": content[:100000]}
        except Exception as e:
            return {"success": False, "error": str(e), "host": host, "path": remote_path}

    def ftp_list(self, host, username, password, remote_path="/", port=21):
        """Список файлов на FTP."""
        try:
            ftp = ftplib.FTP()
            ftp.connect(host, port, timeout=30)
            ftp.login(username, password)
            items = []
            ftp.retrlines(f"LIST {remote_path}", items.append)
            ftp.quit()
            parsed = []
            for line in items:
                parts = line.split(None, 8)
                if len(parts) >= 9:
                    parsed.append({"permissions": parts[0], "size": parts[4],
                                   "name": parts[8], "is_dir": parts[0].startswith("d")})
                else:
                    parsed.append({"raw": line})
            return {"success": True, "host": host, "path": remote_path,
                    "files": parsed, "count": len(parsed)}
        except Exception as e:
            return {"success": False, "error": str(e), "host": host, "path": remote_path}

    def ftp_delete(self, host, username, password, remote_path, port=21):
        """Удалить файл на FTP."""
        try:
            ftp = ftplib.FTP()
            ftp.connect(host, port, timeout=30)
            ftp.login(username, password)
            ftp.delete(remote_path)
            ftp.quit()
            return {"success": True, "deleted": remote_path}
        except Exception as e:
            return {"success": False, "error": str(e), "path": remote_path}

    def _ftp_makedirs(self, ftp, remote_dir):
        """Рекурсивно создать директории на FTP."""
        dirs = remote_dir.strip("/").split("/")
        current = ""
        for d in dirs:
            if not d:
                continue
            current += "/" + d
            try:
                ftp.mkd(current)
            except ftplib.error_perm:
                pass
