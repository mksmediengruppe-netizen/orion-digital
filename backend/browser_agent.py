"""
Browser Agent Module — Навигация по сайтам, парсинг, проверка доступности.
Использует requests + BeautifulSoup для headless browsing.
Playwright используется для реальных скриншотов и ИНТЕРАКТИВНОЙ автоматизации.

ПАТЧ ЗАДАЧА-1: Добавлены методы интерактивной автоматизации:
- click(selector)       — кликнуть по элементу
- fill(selector, value) — заполнить поле формы
- submit(selector)      — отправить форму
- select(selector, val) — выбрать из <select>
- detect_login_form()   — обнаружить форму логина и вернуть поля
- ftp_upload()          — загрузить файл на FTP через ftplib
- ftp_download()        — скачать файл с FTP
- ftp_list()            — список файлов на FTP
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

logger = logging.getLogger("browser_agent")

# ── Playwright support ─────────────────────────────────────────────────────
_playwright_available = False
try:
    from playwright.sync_api import sync_playwright, TimeoutError as PWTimeoutError
    _playwright_available = True
except ImportError:
    PWTimeoutError = Exception

_pw_lock = threading.Lock()

# Глобальный persistent браузер для интерактивных операций
_pw_browser = None
_pw_context = None
_pw_page = None
_pw_playwright = None


def _get_pw_page(url: str = None, width: int = 1280, height: int = 800):
    """
    Получить или создать Playwright page.
    Если url задан — навигируем на него.
    Возвращает (playwright, browser, context, page) или None если недоступен.
    """
    global _pw_browser, _pw_context, _pw_page, _pw_playwright
    if not _playwright_available:
        return None, None, None, None
    try:
        if _pw_playwright is None:
            _pw_playwright = sync_playwright().start()
        if _pw_browser is None or not _pw_browser.is_connected():
            _pw_browser = _pw_playwright.chromium.launch(
                headless=True,
                args=["--no-sandbox", "--disable-setuid-sandbox",
                      "--disable-dev-shm-usage", "--disable-gpu"]
            )
        if _pw_context is None:
            _pw_context = _pw_browser.new_context(
                viewport={"width": width, "height": height},
                user_agent="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            )
        if _pw_page is None or _pw_page.is_closed():
            _pw_page = _pw_context.new_page()
        if url:
            _pw_page.goto(url, timeout=25000, wait_until="domcontentloaded")
            _pw_page.wait_for_timeout(1200)
        return _pw_playwright, _pw_browser, _pw_context, _pw_page
    except Exception as e:
        logger.warning(f"[PW] _get_pw_page error: {e}")
        # Сброс при ошибке
        _pw_page = None
        _pw_context = None
        _pw_browser = None
        return None, None, None, None


def _take_playwright_screenshot(url: str, width: int = 1280, height: int = 800) -> str | None:
    """Take a real browser screenshot using Playwright. Returns base64 PNG or None."""
    if not _playwright_available:
        return None
    try:
        with _pw_lock:
            _, _, _, page = _get_pw_page(url, width, height)
            if page is None:
                return None
            png_bytes = page.screenshot(full_page=False)
            return base64.b64encode(png_bytes).decode("utf-8")
    except Exception as e:
        logger.debug(f"[PW] screenshot error: {e}")
        return None


def _screenshot_current_page() -> str | None:
    """Сделать скриншот текущей страницы без навигации."""
    if not _playwright_available or _pw_page is None or _pw_page.is_closed():
        return None
    try:
        png_bytes = _pw_page.screenshot(full_page=False)
        return base64.b64encode(png_bytes).decode("utf-8")
    except Exception:
        return None


class BrowserAgent:
    """Headless browser agent for web navigation, parsing and interactive automation."""

    def __init__(self, timeout=30):
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
        })
        self.history = []
        self._last_screenshot_b64 = None
        self._current_url = None  # Текущий URL в Playwright

    def navigate(self, url):
        """Navigate to a URL and return page content + screenshot."""
        try:
            if not url.startswith(("http://", "https://")):
                url = "https://" + url

            resp = self.session.get(url, timeout=self.timeout, allow_redirects=True, verify=False)
            self.history.append({"url": url, "status": resp.status_code, "time": time.time()})

            # Take real screenshot with Playwright (persistent page)
            screenshot_b64 = None
            if _playwright_available:
                with _pw_lock:
                    try:
                        _, _, _, page = _get_pw_page(resp.url)
                        if page:
                            screenshot_b64 = base64.b64encode(page.screenshot(full_page=False)).decode("utf-8")
                            self._current_url = resp.url
                    except Exception as e:
                        logger.debug(f"[PW] navigate screenshot error: {e}")

            if screenshot_b64:
                self._last_screenshot_b64 = screenshot_b64

            return {
                "success": True,
                "url": resp.url,
                "status_code": resp.status_code,
                "content_type": resp.headers.get("Content-Type", ""),
                "html": resp.text[:100000],
                "headers": dict(resp.headers),
                "elapsed_ms": int(resp.elapsed.total_seconds() * 1000),
                "screenshot": screenshot_b64
            }
        except Exception as e:
            return {"success": False, "url": url, "error": str(e)}

    def check_site(self, url):
        """Check if a website is accessible and return status info + screenshot."""
        try:
            if not url.startswith(("http://", "https://")):
                url = "https://" + url

            start = time.time()
            resp = self.session.get(url, timeout=self.timeout, allow_redirects=True, verify=False)
            elapsed = round((time.time() - start) * 1000)

            title = ""
            title_match = re.search(r"<title[^>]*>(.*?)</title>", resp.text, re.IGNORECASE | re.DOTALL)
            if title_match:
                title = title_match.group(1).strip()

            screenshot_b64 = None
            if _playwright_available:
                with _pw_lock:
                    try:
                        _, _, _, page = _get_pw_page(resp.url)
                        if page:
                            screenshot_b64 = base64.b64encode(page.screenshot(full_page=False)).decode("utf-8")
                    except Exception:
                        pass
            if screenshot_b64:
                self._last_screenshot_b64 = screenshot_b64

            return {
                "success": True,
                "url": resp.url,
                "status_code": resp.status_code,
                "title": title,
                "response_time_ms": elapsed,
                "content_length": len(resp.text),
                "is_https": resp.url.startswith("https://"),
                "server": resp.headers.get("Server", "unknown"),
                "screenshot": screenshot_b64
            }
        except Exception as e:
            return {"success": False, "url": url, "error": str(e)}

    def get_text(self, url):
        """Get clean text content from a webpage."""
        result = self.navigate(url)
        if not result["success"]:
            return result

        html = result["html"]
        html = re.sub(r"<script[^>]*>.*?</script>", "", html, flags=re.DOTALL | re.IGNORECASE)
        html = re.sub(r"<style[^>]*>.*?</style>", "", html, flags=re.DOTALL | re.IGNORECASE)
        html = re.sub(r"<!--.*?-->", "", html, flags=re.DOTALL)
        text = re.sub(r"<[^>]+>", " ", html)
        text = re.sub(r"\s+", " ", text).strip()
        if len(text) > 20000:
            text = text[:20000] + "... [truncated]"

        return {
            "success": True,
            "url": result["url"],
            "text": text,
            "status_code": result["status_code"],
            "screenshot": result.get("screenshot")
        }

    def get_links(self, url):
        """Extract all links from a webpage."""
        result = self.navigate(url)
        if not result["success"]:
            return result

        html = result["html"]
        links = []
        for match in re.finditer(r'<a[^>]+href=["\']([^"\']+)["\']', html, re.IGNORECASE):
            href = match.group(1)
            if href.startswith(("javascript:", "#", "mailto:", "tel:")):
                continue
            absolute = urljoin(result["url"], href)
            links.append(absolute)

        links = list(dict.fromkeys(links))
        return {
            "success": True,
            "url": result["url"],
            "links": links[:200],
            "count": len(links),
            "screenshot": result.get("screenshot")
        }

    def post_data(self, url, data=None, json_data=None, headers=None):
        """Send POST request to a URL."""
        try:
            if not url.startswith(("http://", "https://")):
                url = "https://" + url

            extra_headers = headers or {}
            resp = self.session.post(
                url, data=data, json=json_data,
                headers=extra_headers, timeout=self.timeout, verify=False
            )
            return {
                "success": True,
                "url": resp.url,
                "status_code": resp.status_code,
                "response": resp.text[:50000],
                "headers": dict(resp.headers)
            }
        except Exception as e:
            return {"success": False, "url": url, "error": str(e)}

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
                resp = self.session.get(url, headers=extra_headers, timeout=self.timeout, verify=False)
            elif method.upper() == "POST":
                resp = self.session.post(url, json=data, headers=extra_headers, timeout=self.timeout, verify=False)
            elif method.upper() == "PUT":
                resp = self.session.put(url, json=data, headers=extra_headers, timeout=self.timeout, verify=False)
            elif method.upper() == "DELETE":
                resp = self.session.delete(url, headers=extra_headers, timeout=self.timeout, verify=False)
            else:
                return {"success": False, "error": f"Unsupported method: {method}"}

            elapsed = round((time.time() - start) * 1000)
            try:
                json_response = resp.json()
            except Exception:
                json_response = None

            return {
                "success": True,
                "url": resp.url,
                "method": method.upper(),
                "status_code": resp.status_code,
                "response_time_ms": elapsed,
                "json": json_response,
                "text": resp.text[:20000] if not json_response else None,
                "headers": dict(resp.headers)
            }
        except Exception as e:
            return {"success": False, "url": url, "error": str(e)}

    def screenshot_check(self, url):
        """Check visual aspects of a site (headers, meta, resources) + real screenshot."""
        result = self.navigate(url)
        if not result["success"]:
            return result

        html = result["html"]
        metas = {}
        for match in re.finditer(r'<meta[^>]+>', html, re.IGNORECASE):
            tag = match.group(0)
            name = re.search(r'name=["\']([^"\']+)["\']', tag)
            content = re.search(r'content=["\']([^"\']+)["\']', tag)
            if name and content:
                metas[name.group(1)] = content.group(1)

        scripts = len(re.findall(r'<script', html, re.IGNORECASE))
        styles = len(re.findall(r'<link[^>]+stylesheet', html, re.IGNORECASE))
        images = len(re.findall(r'<img', html, re.IGNORECASE))

        title = ""
        title_match = re.search(r"<title[^>]*>(.*?)</title>", html, re.IGNORECASE | re.DOTALL)
        if title_match:
            title = title_match.group(1).strip()

        return {
            "success": True,
            "url": result["url"],
            "title": title,
            "meta": metas,
            "resources": {"scripts": scripts, "stylesheets": styles, "images": images},
            "html_size": len(html),
            "status_code": result["status_code"],
            "screenshot": result.get("screenshot")
        }

    # ══════════════════════════════════════════════════════════════════
    # ██ ЗАДАЧА-1: ИНТЕРАКТИВНАЯ АВТОМАТИЗАЦИЯ (Playwright) ██
    # ══════════════════════════════════════════════════════════════════

    def click(self, selector: str, timeout: int = 8000) -> dict:
        """
        Кликнуть по элементу на текущей странице.
        selector — CSS-селектор или текст кнопки (text=Войти).
        Для SPA (Vue.js/React) ждёт networkidle после клика.
        """
        if not _playwright_available:
            return {"success": False, "error": "Playwright не установлен. Выполни: pip install playwright && playwright install chromium"}
        try:
            with _pw_lock:
                _, _, _, page = _get_pw_page()
                if page is None:
                    return {"success": False, "error": "Playwright page не инициализирована. Сначала вызови browser_navigate."}

                url_before = page.url

                # Поддержка text=... селекторов
                if selector.startswith("text="):
                    text_val = selector[5:]
                    page.get_by_text(text_val, exact=False).first.click(timeout=timeout)
                elif selector.startswith("[st="):
                    # Beget st-атрибут селектор
                    page.click(selector, timeout=timeout)
                else:
                    page.click(selector, timeout=timeout)

                # Ждём навигацию или SPA-переход (Vue.js/React)
                try:
                    page.wait_for_load_state("networkidle", timeout=8000)
                except Exception:
                    page.wait_for_timeout(3000)

                screenshot = base64.b64encode(page.screenshot(full_page=False)).decode("utf-8")
                self._last_screenshot_b64 = screenshot
                url_after = page.url

                return {
                    "success": True,
                    "clicked": selector,
                    "url_before": url_before,
                    "url_after": url_after,
                    "navigated": url_before != url_after,
                    "screenshot": screenshot
                }
        except Exception as e:
            return {"success": False, "selector": selector, "error": str(e)}

    def fill(self, selector: str, value: str, timeout: int = 8000) -> dict:
        """
        Заполнить поле формы на текущей странице.
        selector — CSS-селектор поля (input[name=login], #password и т.д.)
        value    — значение для ввода
        """
        if not _playwright_available:
            return {"success": False, "error": "Playwright не установлен."}
        try:
            with _pw_lock:
                _, _, _, page = _get_pw_page()
                if page is None:
                    return {"success": False, "error": "Playwright page не инициализирована. Сначала вызови browser_navigate."}

                page.fill(selector, value, timeout=timeout)
                page.wait_for_timeout(300)
                screenshot = base64.b64encode(page.screenshot(full_page=False)).decode("utf-8")
                self._last_screenshot_b64 = screenshot

                return {
                    "success": True,
                    "filled": selector,
                    "value_length": len(value),
                    "screenshot": screenshot
                }
        except Exception as e:
            return {"success": False, "selector": selector, "error": str(e)}

    def submit(self, selector: str = None, timeout: int = 10000) -> dict:
        """
        Отправить форму.
        selector — CSS-селектор кнопки submit или самой формы.
        Если selector=None — нажимает Enter на активном элементе.
        """
        if not _playwright_available:
            return {"success": False, "error": "Playwright не установлен."}
        try:
            with _pw_lock:
                _, _, _, page = _get_pw_page()
                if page is None:
                    return {"success": False, "error": "Playwright page не инициализирована."}

                url_before = page.url

                if selector:
                    # Пробуем click на submit кнопку
                    try:
                        page.click(selector, timeout=timeout)
                    except Exception:
                        # Fallback: submit через форму
                        page.evaluate(f"document.querySelector('{selector}').submit()")
                else:
                    # Enter на активном элементе
                    page.keyboard.press("Enter")

                # Ждём навигации или изменения страницы
                try:
                    page.wait_for_load_state("networkidle", timeout=8000)
                except Exception:
                    page.wait_for_timeout(2000)

                screenshot = base64.b64encode(page.screenshot(full_page=False)).decode("utf-8")
                self._last_screenshot_b64 = screenshot
                url_after = page.url

                return {
                    "success": True,
                    "submitted": selector or "Enter",
                    "url_before": url_before,
                    "url_after": url_after,
                    "navigated": url_before != url_after,
                    "screenshot": screenshot
                }
        except Exception as e:
            return {"success": False, "selector": selector, "error": str(e)}

    def select(self, selector: str, value: str, timeout: int = 8000) -> dict:
        """
        Выбрать значение из <select> элемента.
        selector — CSS-селектор <select>
        value    — значение option (value атрибут или текст)
        """
        if not _playwright_available:
            return {"success": False, "error": "Playwright не установлен."}
        try:
            with _pw_lock:
                _, _, _, page = _get_pw_page()
                if page is None:
                    return {"success": False, "error": "Playwright page не инициализирована."}

                # Пробуем select_option по value, затем по label
                try:
                    page.select_option(selector, value=value, timeout=timeout)
                except Exception:
                    page.select_option(selector, label=value, timeout=timeout)

                page.wait_for_timeout(400)
                screenshot = base64.b64encode(page.screenshot(full_page=False)).decode("utf-8")
                self._last_screenshot_b64 = screenshot

                return {
                    "success": True,
                    "selected": selector,
                    "value": value,
                    "screenshot": screenshot
                }
        except Exception as e:
            return {"success": False, "selector": selector, "error": str(e)}

    def detect_login_form(self, url: str = None) -> dict:
        """
        ПАТЧ ЗАДАЧА-1: browser_ask_auth.
        Обнаружить форму логина на странице.
        Возвращает поля формы + скриншот для показа пользователю.
        """
        if url:
            nav_result = self.navigate(url)
            if not nav_result["success"]:
                return nav_result
            html = nav_result.get("html", "")
        else:
            # Используем текущую страницу
            if not _playwright_available or _pw_page is None or _pw_page.is_closed():
                return {"success": False, "error": "Нет активной страницы"}
            try:
                with _pw_lock:
                    html = _pw_page.content()
            except Exception as e:
                return {"success": False, "error": str(e)}

        # Парсим форму логина из HTML
        fields = []
        login_patterns = [
            r'<input[^>]+type=["\']text["\'][^>]*name=["\']([^"\']+)["\'][^>]*>',
            r'<input[^>]+name=["\']([^"\']+)["\'][^>]*type=["\']text["\'][^>]*>',
            r'<input[^>]+type=["\']email["\'][^>]*name=["\']([^"\']+)["\'][^>]*>',
            r'<input[^>]+name=["\']([^"\']+)["\'][^>]*type=["\']email["\'][^>]*>',
        ]
        password_patterns = [
            r'<input[^>]+type=["\']password["\'][^>]*name=["\']([^"\']+)["\'][^>]*>',
            r'<input[^>]+name=["\']([^"\']+)["\'][^>]*type=["\']password["\'][^>]*>',
        ]

        for pat in login_patterns:
            for m in re.finditer(pat, html, re.IGNORECASE):
                name = m.group(1)
                if name not in [f["name"] for f in fields]:
                    fields.append({"name": name, "type": "text", "selector": f'input[name="{name}"]'})
                    break

        for pat in password_patterns:
            for m in re.finditer(pat, html, re.IGNORECASE):
                name = m.group(1)
                if name not in [f["name"] for f in fields]:
                    fields.append({"name": name, "type": "password", "selector": f'input[name="{name}"]'})
                    break

        # Найти action формы
        form_action = ""
        form_match = re.search(r'<form[^>]+action=["\']([^"\']*)["\']', html, re.IGNORECASE)
        if form_match:
            form_action = form_match.group(1)

        # Найти submit кнопку
        submit_selector = None
        submit_patterns = [
            r'<input[^>]+type=["\']submit["\'][^>]*>',
            r'<button[^>]+type=["\']submit["\'][^>]*>',
            r'<button[^>]*>[^<]*(войти|login|sign in|вход|submit)[^<]*</button>',
        ]
        for pat in submit_patterns:
            if re.search(pat, html, re.IGNORECASE):
                submit_selector = 'input[type="submit"], button[type="submit"], button'
                break

        screenshot = self._last_screenshot_b64 or _screenshot_current_page()
        current_url = url or (self._current_url or "")
        if _pw_page and not _pw_page.is_closed():
            try:
                current_url = _pw_page.url
            except Exception:
                pass

        is_login_page = bool(fields) and any(f["type"] == "password" for f in fields)

        return {
            "success": True,
            "is_login_form": is_login_page,
            "url": current_url,
            "fields": fields,
            "form_action": form_action,
            "submit_selector": submit_selector or 'button[type="submit"]',
            "screenshot": screenshot,
            "fields_count": len(fields)
        }

    # ══════════════════════════════════════════════════════════════════
    # ██ ЗАДАЧА-1: FTP ИНСТРУМЕНТЫ (ftplib) ██
    # ══════════════════════════════════════════════════════════════════

    def ftp_upload(self, host: str, username: str, password: str,
                   remote_path: str, content: str,
                   port: int = 21, encoding: str = "utf-8") -> dict:
        """
        Загрузить файл на FTP сервер через ftplib.
        Работает с паролями содержащими спецсимволы (#, @, ! и т.д.).
        """
        try:
            ftp = ftplib.FTP()
            ftp.connect(host, port, timeout=30)
            ftp.login(username, password)

            # Создать директории если нужно
            remote_dir = "/".join(remote_path.split("/")[:-1])
            if remote_dir and remote_dir != "/":
                self._ftp_makedirs(ftp, remote_dir)

            # Загрузить файл
            content_bytes = content.encode(encoding) if isinstance(content, str) else content
            ftp.storbinary(f"STOR {remote_path}", io.BytesIO(content_bytes))

            size = len(content_bytes)
            ftp.quit()

            return {
                "success": True,
                "host": host,
                "remote_path": remote_path,
                "size_bytes": size,
                "message": f"Файл успешно загружен: {remote_path} ({size} байт)"
            }
        except ftplib.error_perm as e:
            return {"success": False, "error": f"FTP permission error: {e}", "host": host, "path": remote_path}
        except Exception as e:
            return {"success": False, "error": str(e), "host": host, "path": remote_path}

    def ftp_download(self, host: str, username: str, password: str,
                     remote_path: str, port: int = 21) -> dict:
        """
        Скачать файл с FTP сервера.
        Возвращает содержимое файла как строку.
        """
        try:
            ftp = ftplib.FTP()
            ftp.connect(host, port, timeout=30)
            ftp.login(username, password)

            buf = io.BytesIO()
            ftp.retrbinary(f"RETR {remote_path}", buf.write)
            ftp.quit()

            content_bytes = buf.getvalue()
            # Пробуем декодировать как текст
            try:
                content = content_bytes.decode("utf-8")
            except UnicodeDecodeError:
                try:
                    content = content_bytes.decode("cp1251")
                except Exception:
                    content = base64.b64encode(content_bytes).decode("ascii")

            return {
                "success": True,
                "host": host,
                "remote_path": remote_path,
                "size_bytes": len(content_bytes),
                "content": content[:100000]  # Лимит 100KB
            }
        except ftplib.error_perm as e:
            return {"success": False, "error": f"FTP permission error: {e}", "host": host, "path": remote_path}
        except Exception as e:
            return {"success": False, "error": str(e), "host": host, "path": remote_path}

    def ftp_list(self, host: str, username: str, password: str,
                 remote_path: str = "/", port: int = 21) -> dict:
        """
        Список файлов в директории на FTP сервере.
        """
        try:
            ftp = ftplib.FTP()
            ftp.connect(host, port, timeout=30)
            ftp.login(username, password)

            items = []
            ftp.retrlines(f"LIST {remote_path}", items.append)
            ftp.quit()

            # Парсим вывод LIST
            parsed = []
            for line in items:
                parts = line.split(None, 8)
                if len(parts) >= 9:
                    parsed.append({
                        "permissions": parts[0],
                        "size": parts[4],
                        "name": parts[8],
                        "is_dir": parts[0].startswith("d")
                    })
                else:
                    parsed.append({"raw": line, "is_dir": line.startswith("d")})

            return {
                "success": True,
                "host": host,
                "path": remote_path,
                "files": parsed,
                "count": len(parsed)
            }
        except Exception as e:
            return {"success": False, "error": str(e), "host": host, "path": remote_path}

    def ftp_delete(self, host: str, username: str, password: str,
                   remote_path: str, port: int = 21) -> dict:
        """Удалить файл на FTP сервере."""
        try:
            ftp = ftplib.FTP()
            ftp.connect(host, port, timeout=30)
            ftp.login(username, password)
            ftp.delete(remote_path)
            ftp.quit()
            return {"success": True, "deleted": remote_path}
        except Exception as e:
            return {"success": False, "error": str(e), "path": remote_path}

    def _ftp_makedirs(self, ftp: ftplib.FTP, remote_dir: str):
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
                pass  # Директория уже существует
