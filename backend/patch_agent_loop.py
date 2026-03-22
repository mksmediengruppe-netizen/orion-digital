#!/usr/bin/env python3
"""
Патч agent_loop.py:
1. Добавить новые tool definitions (browser_type, browser_js, browser_press_key, 
   browser_scroll, browser_hover, browser_wait, browser_elements, browser_screenshot,
   smart_login, browser_ask_user, browser_takeover_done)
2. Добавить обработку новых инструментов в _execute_tool
3. Обновить описания существующих инструментов
"""

import re

AGENT_LOOP = "/var/www/orion/backend/agent_loop.py"

with open(AGENT_LOOP, "r") as f:
    content = f.read()

# ═══════════════════════════════════════════════════════════════
# 1. Добавить новые tool definitions ПОСЛЕ browser_ask_auth, ПЕРЕД ftp_upload
# ═══════════════════════════════════════════════════════════════

NEW_TOOLS = '''    },
    # ── НОВЫЕ BROWSER ИНСТРУМЕНТЫ v2 ─────────────────────────────────
    {
        "type": "function",
        "function": {
            "name": "browser_type",
            "description": "Type text character by character into a field (for SPA where browser_fill doesn't work). Clicks the field first, then types. Use when browser_fill fails with Vuetify/Material UI inputs.",
            "parameters": {
                "type": "object",
                "properties": {
                    "selector": {"type": "string", "description": "CSS selector of the input field"},
                    "value": {"type": "string", "description": "Text to type"},
                    "clear": {"type": "boolean", "description": "Clear field before typing (default: true)", "default": true}
                },
                "required": ["selector", "value"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "browser_js",
            "description": "Execute arbitrary JavaScript on the current page. Returns result + screenshot. Use for complex DOM manipulation, reading page state, triggering Vue/React events.",
            "parameters": {
                "type": "object",
                "properties": {
                    "code": {"type": "string", "description": "JavaScript code to execute. Can return a value."}
                },
                "required": ["code"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "browser_press_key",
            "description": "Press a keyboard key on the current page. Use Enter to submit forms, Tab to move focus, Escape to close dialogs, ArrowDown for dropdowns.",
            "parameters": {
                "type": "object",
                "properties": {
                    "key": {"type": "string", "description": "Key name: Enter, Tab, Escape, ArrowDown, ArrowUp, Control+a, etc."}
                },
                "required": ["key"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "browser_scroll",
            "description": "Scroll the current page in a direction. Use to see content below the fold, load lazy content, or navigate long pages.",
            "parameters": {
                "type": "object",
                "properties": {
                    "direction": {"type": "string", "enum": ["up", "down", "left", "right"], "description": "Scroll direction"},
                    "amount": {"type": "integer", "description": "Scroll amount in pixels (default: 500)", "default": 500}
                },
                "required": ["direction"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "browser_hover",
            "description": "Hover mouse over an element to reveal hidden menus, tooltips, or action buttons.",
            "parameters": {
                "type": "object",
                "properties": {
                    "selector": {"type": "string", "description": "CSS selector of the element to hover over"}
                },
                "required": ["selector"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "browser_wait",
            "description": "Wait for an element to appear or URL to change. Use after actions that trigger async loading (AJAX, SPA routing).",
            "parameters": {
                "type": "object",
                "properties": {
                    "selector": {"type": "string", "description": "CSS selector to wait for (optional)"},
                    "url_contains": {"type": "string", "description": "Wait until URL contains this substring (optional)"},
                    "timeout": {"type": "integer", "description": "Max wait time in ms (default: 15000)", "default": 15000}
                },
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "browser_elements",
            "description": "Get a list of elements matching a selector with their text, attributes, and positions. Use to understand page structure before clicking.",
            "parameters": {
                "type": "object",
                "properties": {
                    "selector": {"type": "string", "description": "CSS selector to match elements (e.g. 'button', '.menu-item', '[st]')"},
                    "limit": {"type": "integer", "description": "Max elements to return (default: 50)", "default": 50}
                },
                "required": ["selector"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "browser_screenshot",
            "description": "Take a screenshot of the current page. Returns base64 image + current URL and title.",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "browser_page_info",
            "description": "Get detailed info about current page: URL, title, forms, buttons, links, captcha detection, 2FA detection. Use to understand what's on the page before taking action.",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "smart_login",
            "description": "Automatically log into any website. Tries multiple strategies: find login/password fields, fill them, submit via Enter/button/JS. If login fails or CAPTCHA detected — returns need_user_takeover=true. Use this as the FIRST approach for any login task.",
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "Login page URL"},
                    "login": {"type": "string", "description": "Username/email/login"},
                    "password": {"type": "string", "description": "Password"}
                },
                "required": ["url", "login", "password"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "browser_ask_user",
            "description": "Request user to take over browser control. Use when: CAPTCHA detected, 2FA required, unusual login form, or any situation where automated input fails. Shows screenshot to user with instructions. User can: enter credentials in chat, manually control browser, or skip.",
            "parameters": {
                "type": "object",
                "properties": {
                    "reason": {"type": "string", "enum": ["captcha", "2fa", "login_failed", "unusual_form", "confirmation", "custom"], "description": "Why user takeover is needed"},
                    "instruction": {"type": "string", "description": "What the user should do (shown in chat)"}
                },
                "required": ["reason"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "browser_takeover_done",
            "description": "Call after user has finished manual browser interaction. Takes screenshot and returns current page state so agent can continue.",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": []
            }
        }
    },'''

# Заменяем закрывающую скобку browser_ask_auth + начало FTP
old_marker = """    },
    # ── ЗАДАЧА-1: FTP инструменты (ftplib, без SSH) ───────────────────────────"""

new_marker = NEW_TOOLS + """
    # ── ЗАДАЧА-1: FTP инструменты (ftplib, без SSH) ───────────────────────────"""

if old_marker in content:
    content = content.replace(old_marker, new_marker, 1)
    print("[OK] Added new tool definitions")
else:
    print("[WARN] Could not find FTP marker for tool definitions")

# ═══════════════════════════════════════════════════════════════
# 2. Добавить обработку новых инструментов в _execute_tool
#    Вставляем ПОСЛЕ browser_ask_auth обработки, ПЕРЕД ftp_upload
# ═══════════════════════════════════════════════════════════════

NEW_HANDLERS = '''            # ── НОВЫЕ BROWSER ИНСТРУМЕНТЫ v2 ────────────────────────────────
            elif tool_name == "browser_type":
                selector = args.get("selector", "")
                value = args.get("value", "")
                clear = args.get("clear", True)
                if not selector:
                    return {"success": False, "error": "selector is required"}
                return self.browser.type_text(selector, value, clear=clear)
            elif tool_name == "browser_js":
                code = args.get("code", "")
                if not code:
                    return {"success": False, "error": "code is required"}
                return self.browser.execute_js(code)
            elif tool_name == "browser_press_key":
                key = args.get("key", "Enter")
                return self.browser.press_key(key)
            elif tool_name == "browser_scroll":
                direction = args.get("direction", "down")
                amount = int(args.get("amount", 500))
                return self.browser.scroll(direction, amount)
            elif tool_name == "browser_hover":
                selector = args.get("selector", "")
                if not selector:
                    return {"success": False, "error": "selector is required"}
                return self.browser.hover(selector)
            elif tool_name == "browser_wait":
                selector = args.get("selector")
                url_contains = args.get("url_contains")
                timeout = int(args.get("timeout", 15000))
                return self.browser.wait_for(selector=selector, url_contains=url_contains, timeout=timeout)
            elif tool_name == "browser_elements":
                selector = args.get("selector", "*")
                limit = int(args.get("limit", 50))
                return self.browser.get_elements(selector, limit)
            elif tool_name == "browser_screenshot":
                return self.browser.screenshot()
            elif tool_name == "browser_page_info":
                return self.browser.get_page_info()
            elif tool_name == "smart_login":
                url = args.get("url", "")
                login = args.get("login", "")
                password = args.get("password", "")
                if not all([url, login, password]):
                    return {"success": False, "error": "url, login, password are required"}
                result = self.browser.smart_login(url, login, password)
                # Если нужен takeover — отправляем специальный SSE event
                if result.get("need_user_takeover"):
                    result["_takeover_required"] = True
                return result
            elif tool_name == "browser_ask_user":
                reason = args.get("reason", "custom")
                instruction = args.get("instruction", "")
                result = self.browser.ask_user(reason, instruction)
                result["_takeover_required"] = True
                return result
            elif tool_name == "browser_takeover_done":
                return self.browser.takeover_done()
'''

# Находим место вставки: после browser_ask_auth обработки, перед ftp_upload
old_handler_marker = """            # ── ЗАДАЧА-1: FTP инструменты ────────────────────────────────────────
            elif tool_name == "ftp_upload":"""

new_handler_marker = NEW_HANDLERS + """            # ── ЗАДАЧА-1: FTP инструменты ────────────────────────────────────────
            elif tool_name == "ftp_upload":"""

if old_handler_marker in content:
    content = content.replace(old_handler_marker, new_handler_marker, 1)
    print("[OK] Added new tool handlers in _execute_tool")
else:
    print("[WARN] Could not find FTP handler marker")

# ═══════════════════════════════════════════════════════════════
# 3. Обновить описание browser_click чтобы упомянуть SPA поддержку
# ═══════════════════════════════════════════════════════════════

old_click_desc = '"description": "Click on an element on the current browser page. Use after browser_navigate. Supports CSS selectors (button.submit, #login-btn) and text selectors (text=Войти). Returns screenshot after click."'
new_click_desc = '"description": "Click on an element on the current browser page. Supports CSS selectors (button.submit, #login-btn), text selectors (text=Войти), Beget st-attributes ([st=\\"button-dns-edit-node\\"]), and xpath (xpath=//button). Waits for SPA navigation (Vue.js/React) after click. Returns screenshot."'

if old_click_desc in content:
    content = content.replace(old_click_desc, new_click_desc, 1)
    print("[OK] Updated browser_click description")

# ═══════════════════════════════════════════════════════════════
# 4. Обновить описание browser_fill
# ═══════════════════════════════════════════════════════════════

old_fill_desc = '"description": "Fill a form field on the current browser page. Use after browser_navigate. Selector is CSS (input[name=login], #password, textarea). Returns screenshot after fill."'
new_fill_desc = '"description": "Fill a form field with Vue.js/React event triggers. Tries 3 strategies: Playwright fill, click+type, JavaScript setValue. Works with Vuetify, Material UI, and any SPA framework. Returns screenshot after fill."'

if old_fill_desc in content:
    content = content.replace(old_fill_desc, new_fill_desc, 1)
    print("[OK] Updated browser_fill description")

# ═══════════════════════════════════════════════════════════════
# 5. Добавить упоминание новых инструментов в системный промпт
# ═══════════════════════════════════════════════════════════════

old_tools_list = """- browser_click(selector): кликнуть по элементу (CSS селектор или text=Войти)
- browser_fill(selector, value): заполнить поле формы
- browser_submit(selector): отправить форму (или Enter если без селектора)
- browser_select(selector, value): выбрать из выпадающего списка
- browser_ask_auth(hint): обнаружить форму логина и запросить данные у пользователя через UI"""

new_tools_list = """- browser_click(selector): кликнуть по элементу (CSS, text=Войти, [st="..."], xpath=//...)
- browser_fill(selector, value): заполнить поле с триггером Vue/React events (3 стратегии)
- browser_type(selector, value): посимвольный ввод (когда fill не работает с Vuetify)
- browser_submit(selector): отправить форму (или Enter если без селектора)
- browser_select(selector, value): выбрать из dropdown (нативный и Vuetify)
- browser_js(code): выполнить JavaScript на странице
- browser_press_key(key): нажать клавишу (Enter, Tab, Escape, ArrowDown)
- browser_scroll(direction): прокрутить страницу (up/down/left/right)
- browser_hover(selector): навести курсор (для скрытых меню)
- browser_wait(selector/url_contains): ждать элемент или смену URL
- browser_elements(selector): получить список элементов с текстом и атрибутами
- browser_screenshot(): скриншот текущей страницы
- browser_page_info(): URL, title, формы, кнопки, ссылки, капча, 2FA
- smart_login(url, login, password): автоматический вход в любой ЛК
- browser_ask_user(reason, instruction): передать управление пользователю (капча, 2FA)
- browser_takeover_done(): продолжить после ручного ввода пользователя
- browser_ask_auth(hint): обнаружить форму логина и запросить данные у пользователя"""

if old_tools_list in content:
    content = content.replace(old_tools_list, new_tools_list, 1)
    print("[OK] Updated system prompt tool list")
else:
    print("[WARN] Could not find old tools list in system prompt")

# ═══════════════════════════════════════════════════════════════
# 6. Добавить инструкции по takeover в системный промпт
# ═══════════════════════════════════════════════════════════════

old_auth_instruction = """Когда встречаешь форму логина — ИСПОЛЬЗУЙ browser_ask_auth."""

new_auth_instruction = """Когда встречаешь форму логина:
1. Если логин/пароль уже даны в сообщении — используй smart_login(url, login, password)
2. Если smart_login вернул need_user_takeover — используй browser_ask_user(reason)
3. Если логин/пароль НЕ даны — используй browser_ask_auth(hint)
4. При CAPTCHA или 2FA — ВСЕГДА используй browser_ask_user("captcha") или browser_ask_user("2fa")
5. После ручного ввода пользователя — вызови browser_takeover_done() чтобы продолжить"""

if old_auth_instruction in content:
    content = content.replace(old_auth_instruction, new_auth_instruction, 1)
    print("[OK] Updated auth instructions in system prompt")
else:
    print("[WARN] Could not find old auth instruction")

# ═══════════════════════════════════════════════════════════════
# 7. Добавить обработку _takeover_required в run_stream
#    (рядом с _auth_required)
# ═══════════════════════════════════════════════════════════════

# Ищем обработку _auth_required
old_auth_check = 'if result.get("_auth_required")'
if old_auth_check in content:
    # Добавляем обработку _takeover_required рядом
    takeover_handler = '''
                    # Обработка browser_ask_user / smart_login takeover
                    if result.get("_takeover_required"):
                        yield self._sse("browser_takeover", {
                            "type": result.get("type", "browser_takeover_request"),
                            "reason": result.get("reason", ""),
                            "message": result.get("message", "Требуется ваше участие"),
                            "instruction": result.get("instruction", ""),
                            "url": result.get("url", ""),
                            "screenshot": result.get("screenshot", ""),
                            "screenshot_url": result.get("screenshot_url", ""),
                            "actions": result.get("actions", [])
                        })
'''
    # Вставляем после строки с _auth_required проверкой
    # Находим блок _auth_required и добавляем после его обработки
    auth_block_end = content.find('if result.get("_auth_required")')
    if auth_block_end > 0:
        # Ищем конец этого if блока (следующий elif или else на том же уровне)
        next_block = content.find('\n                    elif ', auth_block_end + 10)
        if next_block == -1:
            next_block = content.find('\n                    else:', auth_block_end + 10)
        if next_block == -1:
            next_block = content.find('\n                    # ', auth_block_end + 100)
        
        if next_block > 0:
            content = content[:next_block] + takeover_handler + content[next_block:]
            print("[OK] Added _takeover_required handler in run_stream")
        else:
            print("[WARN] Could not find end of _auth_required block")
    else:
        print("[WARN] Could not find _auth_required check")
else:
    print("[WARN] No _auth_required found — adding standalone takeover handler")

# ═══════════════════════════════════════════════════════════════
# 8. Добавить обработку новых инструментов во второй run_stream (если есть)
# ═══════════════════════════════════════════════════════════════

# Проверяем есть ли вторая обработка browser_click (в другом run_stream)
second_click = content.find('elif tool_name == "browser_click"', content.find('elif tool_name == "browser_click"') + 10)
if second_click > 0:
    # Находим место после browser_ask_auth во втором блоке
    second_ask_auth = content.find('elif tool_name == "browser_ask_auth"', second_click)
    if second_ask_auth > 0:
        # Ищем конец этого elif блока
        next_elif = content.find('\n            elif tool_name ==', second_ask_auth + 10)
        if next_elif == -1:
            next_elif = content.find('\n            else:', second_ask_auth + 10)
        
        if next_elif > 0:
            second_handlers = '''
            elif tool_name == "browser_type":
                return self.browser.type_text(args.get("selector",""), args.get("value",""), clear=args.get("clear",True))
            elif tool_name == "browser_js":
                return self.browser.execute_js(args.get("code",""))
            elif tool_name == "browser_press_key":
                return self.browser.press_key(args.get("key","Enter"))
            elif tool_name == "browser_scroll":
                return self.browser.scroll(args.get("direction","down"), int(args.get("amount",500)))
            elif tool_name == "browser_hover":
                return self.browser.hover(args.get("selector",""))
            elif tool_name == "browser_wait":
                return self.browser.wait_for(selector=args.get("selector"), url_contains=args.get("url_contains"), timeout=int(args.get("timeout",15000)))
            elif tool_name == "browser_elements":
                return self.browser.get_elements(args.get("selector","*"), int(args.get("limit",50)))
            elif tool_name == "browser_screenshot":
                return self.browser.screenshot()
            elif tool_name == "browser_page_info":
                return self.browser.get_page_info()
            elif tool_name == "smart_login":
                return self.browser.smart_login(args.get("url",""), args.get("login",""), args.get("password",""))
            elif tool_name == "browser_ask_user":
                return self.browser.ask_user(args.get("reason","custom"), args.get("instruction",""))
            elif tool_name == "browser_takeover_done":
                return self.browser.takeover_done()
'''
            content = content[:next_elif] + second_handlers + content[next_elif:]
            print("[OK] Added handlers in second run_stream")
        else:
            print("[WARN] Could not find end of second browser_ask_auth block")
    else:
        print("[WARN] No second browser_ask_auth found")
else:
    print("[INFO] No second browser_click handler found (single run_stream)")

# ═══════════════════════════════════════════════════════════════
# SAVE
# ═══════════════════════════════════════════════════════════════

with open(AGENT_LOOP, "w") as f:
    f.write(content)

print("\n[DONE] agent_loop.py patched successfully")
print(f"[INFO] File size: {len(content)} chars")
