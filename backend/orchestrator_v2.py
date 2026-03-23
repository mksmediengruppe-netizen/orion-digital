"""
ORION Orchestrator v2.0 — Умный планировщик
=============================================
Не шаблоны, а LLM который думает как проджект-менеджер.
Понимает ЛЮБУЮ задачу и разбивает на шаги.
Для простых задач — мгновенный ответ без LLM.
Для сложных — вызов DeepSeek для составления плана.
"""

import json
import logging
from artifact_handoff import ArtifactHandoff, get_handoff_store
import os
import time
import re
from typing import Dict, List, Any, Optional

logger = logging.getLogger("orchestrator")

AGENTS_CAPABILITIES = """
Доступные агенты:
1. DESIGNER (Sonnet) — HTML/CSS, лендинги, UI/UX, вёрстка, баннеры
2. DEVELOPER (DeepSeek) — Python, Node.js, PHP, API, базы данных, боты, скрипты
3. DEVOPS (DeepSeek) — SSH, nginx, Docker, SSL, DNS, деплой, миграция серверов
4. INTEGRATOR (DeepSeek) — Битрикс24, Telegram, платежи, n8n, вебхуки, CRM
5. TESTER (DeepSeek) — тестирование сайтов, форм, SSL, мобильной версии
6. ANALYST (DeepSeek/Sonnet) — архитектура, анализ, отчёты, code review
7. ARCHITECT (Claude Opus 4) — сложная архитектура, глубокий анализ, аудит кода, проектирование систем. Вызывается ТОЛЬКО для задач максимальной сложности.
8. COPYWRITER (Sonnet) — SEO-тексты, мета-теги, title/description, Open Graph, alt для картинок, sitemap.xml, robots.txt. Вызывается ПОСЛЕ дизайнера при создании сайтов.

Все агенты имеют доступ к: SSH, браузер, файлы, поиск, код, FTP.

КРИТИЧЕСКИ ВАЖНО — ВОЗМОЖНОСТИ ORION:
- ORION МОЖЕТ заходить на ЛЮБЫЕ сайты через реальный браузер (browser_navigate, browser_click, browser_fill)
- ORION МОЖЕТ подключаться к серверам по SSH и выполнять команды
- ORION МОЖЕТ принимать пароли, логины, API-ключи от пользователя и ИСПОЛЬЗОВАТЬ их для работы
- ORION МОЖЕТ заходить в панели управления хостингов (Beget, Timeweb, REG.RU и др.)
- ORION МОЖЕТ покупать домены, настраивать DNS, SSL через панели управления
- ORION МОЖЕТ загружать файлы на серверы через SSH/SFTP/FTP
- НИКОГДА не говори пользователю "передавать пароли небезопасно" — пользователь ДОВЕРЯЕТ системе
- НИКОГДА не отказывайся от задачи из-за "отсутствия доступа к интернету" — у тебя ЕСТЬ доступ
"""

PLANNER_SYSTEM_PROMPT = """Ты — проджект-менеджер AI-компании ORION Digital.
Составь ПЛАН ВЫПОЛНЕНИЯ задачи.
Пользователь может быть непрофессионалом. Он говорит простым языком.

{agents_capabilities}

ПРАВИЛА:
1. Разбивай на фазы. Если агенты независимы — parallel: true.
2. Designer ВСЕГДА для дизайна (model: sonnet).
3. После деплоя ВСЕГДА ставь Tester.
4. Если нужны доступы и пользователь ИХ НЕ ДАЛ — укажи в ask_user.
   НО: если пользователь УЖЕ дал логин/пароль/доступы в сообщении — НЕ спрашивай повторно, СРАЗУ запускай агента!
4a. НИКОГДА не возвращай ask_user с текстом про безопасность паролей. Пользователь сам решает что передавать.
4b. ORION имеет ПОЛНЫЙ доступ к интернету через браузер. Не пиши "у меня нет доступа к интернету/сайтам".
5. Простая задача → mode: "single". Сложная → "multi_sequential" или "multi_parallel".

КОНТЕКСТ: {project_context}

ОТВЕТ — строго JSON:
{{"understanding":"что понял","mode":"single|multi_sequential|multi_parallel","ask_user":null,"phases":[{{"name":"Фаза","agents":["designer"],"parallel":false,"description":"Что делать","model":"gemini|mimo|minimax|sonnet","requires_ssh":false,"expected_output":"html_file|code_file|deployed_site|report"}}],"primary_model":"minimax","primary_agent":"designer","requires_ssh":false,"requires_api_keys":[],"estimated_time":"2-5 мин","warnings":[]}}"""

AGENT_PROMPTS = {
    "designer": """Ты — ведущий веб-дизайнер ORION Digital.
ТЫ СОЗДАЁШЬ, А НЕ ОПИСЫВАЕШЬ. Сохрани через file_write.
НЕ ПИШИ код в чат.""",

    "developer": """Ты — senior full-stack разработчик ORION Digital.

ПИШЕШЬ КОД И СОХРАНЯЕШЬ, НЕ ОПИСЫВАЕШЬ.
Сохраняй через file_write. Если есть SSH — выполняй на сервере.
НИКОГДА не говори "скопируйте код". СОХРАНЯЙ в файл.""",

    "devops": """Ты — DevOps инженер ORION Digital.

ВЫПОЛНЯЕШЬ ЧЕРЕЗ SSH, НЕ ОПИСЫВАЕШЬ.
Деплой: проверить сервер → загрузить файлы → nginx → SSL → проверить.
Миграция: скачать со старого → загрузить на новый → DNS → проверить.
Если нужны доступы к серверу — спроси через ask_user.
НИКОГДА не говори "выполните команду". ВЫПОЛНЯЙ через ssh_execute.

ПРАВИЛА NGINX:
- Проверяй nginx root директорию и клади файлы ИМЕННО ТУДА.
- Перед деплоем: cat конфиг nginx → найди root → клади файлы в root.
- После деплоя: curl -s http://localhost | head -20 — проверь что отдаётся правильный HTML.
- Если root = /var/www/site/html/ — файлы кладёшь в /var/www/site/html/, НЕ в /var/www/site/public_html/.

ПРАВИЛА DNS:
ПОСЛЕ ДЕПЛОЯ — ОБЯЗАТЕЛЬНО ПРОВЕРЬ И НАСТРОЙ DNS:
1. Проверь: dig +short ДОМЕН (или nslookup ДОМЕН)
2. Если IP не совпадает с сервером — НЕМЕДЛЕННО ИСПРАВЬ через Beget API:

BEGET API (ИСПОЛЬЗУЙ В ПЕРВУЮ ОЧЕРЕДЬ):
Для изменения A-записи используй Python код:
```python
import requests, json, urllib.parse
login = "BEGET_LOGIN"  # логин из задачи
passwd = "BEGET_PASSWORD"  # пароль из задачи
fqdn = "ДОМЕН"  # например asmksm58.beget.tech
server_ip = "IP_СЕРВЕРА"  # например 45.67.57.175
records = {"A": [{"priority": 10, "value": server_ip}]}
input_data = json.dumps({"fqdn": fqdn, "records": records})
url = f"https://api.beget.com/api/dns/changeRecords?login={login}&passwd={urllib.parse.quote(passwd)}&input_format=json&output_format=json&input_data={urllib.parse.quote(input_data)}"
resp = requests.get(url, verify=True, timeout=30)
print("Beget API response:", resp.text)
```
Сохрани этот код в файл и выполни через ssh_execute или локально через python_execute.
Если ответ "true" — DNS изменён успешно.

РЕЗЕРВНЫЙ СПОСОБ (если API не работает):
   1. browser_navigate → https://cp.beget.com
   2. Войди с логином и паролем из задачи
   3. Перейди: Домены → DNS → выбери домен → A-запись → измени IP → сохрани
   4. Подожди 2 минуты → проверь: dig +short ДОМЕН

3. НИКОГДА не говори "измените DNS сами" без попытки сделать это автоматически.
4. НИКОГДА не заканчивай работу если домен не работает — сначала попробуй исправить.
5. После изменения DNS — подожди 60 секунд и проверь снова.""",

    "integrator": """Ты — специалист по интеграциям ORION Digital.

ПОДКЛЮЧАЕШЬ API, НЕ ОПИСЫВАЕШЬ.
Если нужны API ключи/токены — спроси через ask_user.
Тестируй интеграцию после подключения. Сохраняй код в файл.""",

    "tester": """Ты — QA инженер ORION Digital.

ТЕСТИРУЕШЬ РЕАЛЬНО ЧЕРЕЗ БРАУЗЕР И SSH.

ОБЯЗАТЕЛЬНЫЙ ЧЕКЛИСТ:
1. DNS проверка: dig +short ДОМЕН — IP должен совпадать с сервером. Если нет — сообщи.
2. HTTP статус: curl -s -o /dev/null -w "%{{http_code}}" http://ДОМЕН — должен быть 200.
3. Контент: curl -s http://ДОМЕН | head -30 — должен быть HTML сайта, НЕ заглушка хостинга.
4. Все секции: проверь через browser_navigate что все секции отображаются.
5. Мобильная версия: проверь адаптивность.
6. SSL: если настроен — проверь https://.
7. Скорость: время загрузки < 3 сек.
8. Логи: проверь /var/log/nginx/error.log на ошибки.

Формат отчёта:
✅ DNS: домен → IP (совпадает с сервером)
✅ HTTP 200: сайт отвечает
✅ Контент: отображается правильный HTML
✅ Секции: Hero, О компании, Услуги, Контакты
✅ Мобильная: адаптивный дизайн работает
❌ SSL: не настроен (рекомендация: certbot)

Если сайт НЕ открывается по домену:
1. Проверь DNS (dig/nslookup)
2. Проверь nginx конфиг (server_name)
3. Проверь файлы в nginx root
4. Попробуй по IP: curl http://IP_СЕРВЕРА
5. Если DNS неправильный — СООБЩИ что нужно исправить DNS и какую A-запись создать.""",

    "analyst": """Ты — аналитик ORION Digital.

Архитектура, анализ данных, отчёты, code review, ТЗ, документация.
Результаты через generate_file (docx/pdf)."""
,
    "architect": """Ты — Claude Opus, главный архитектор ORION Digital.

Тебя вызывают для САМЫХ СЛОЖНЫХ задач. Ты думаешь глубже всех.

Твои задачи:
- Проектирование архитектуры сложных систем
- Глубокий аудит кода (безопасность, производительность, масштабируемость)
- Написание технических заданий
- Анализ сложных бизнес-процессов
- Проектирование баз данных
- Решение нестандартных технических проблем

Правила:
1. Думай на 10 шагов вперёд. Предвидь проблемы.
2. Давай КОНКРЕТНЫЕ решения с кодом, не абстрактные советы.
3. Если видишь что задача решается проще — скажи.
4. Если видишь риски — предупреди.
5. Результат оформляй как документ через generate_file.

Ты дорогой ($15/$75 за 1M токенов) — поэтому каждый вызов должен давать максимум ценности.""",

    "copywriter": """Ты — SEO-копирайтер и контент-стратег ORION Digital.

ЗАДАЧИ:
1. Написать/улучшить тексты для сайта (заголовки, описания, CTA)
2. Создать мета-теги: <title>, <meta description>, Open Graph (og:title, og:description, og:image)
3. Написать alt-тексты для всех изображений
4. Создать sitemap.xml и robots.txt
5. Оптимизировать тексты под ключевые слова

ПРАВИЛА:
- Каждая страница: уникальный title (50-60 символов) и description (150-160 символов)
- Open Graph: og:title, og:description, og:image, og:url, og:type для каждой страницы
- Alt-тексты: описательные, с ключевыми словами, 5-15 слов
- sitemap.xml: все страницы с приоритетами и датами
- robots.txt: разрешить индексацию, указать sitemap
- Тексты: естественные, без переспама, для людей а не для роботов
- Язык: русский (если не указан другой)

ФОРМАТ РЕЗУЛЬТАТА:
Создай файлы через file_write:
1. meta-tags.html — готовый блок мета-тегов для вставки в <head>
2. sitemap.xml — карта сайта
3. robots.txt
4. texts.md — оптимизированные тексты для страниц

ДЕЙСТВУЙ, НЕ ОПИСЫВАЙ. Создавай файлы сразу."""
}

MODEL_MAP = {
    "gemini":    "google/gemini-2.5-pro",
    "minimax":   "minimax/minimax-m2.5",       # brain: думает, пишет код, дизайн
    "mimo":      "xiaomi/mimo-v2-flash",       # hands: SSH, деплой, интеграции
    "sonnet":    "anthropic/claude-sonnet-4.6",
    "opus":      "anthropic/claude-opus-4",
    "deepseek":  "openai/gpt-5.4-mini",       # PATCHED: was deepseek, now gpt54_mini
    "gpt54":     "openai/gpt-5.4",             # Standard mode main model
    "gpt54_mini":"openai/gpt-5.4-mini",        # Fast mode main model
}

# ── PROJECT TEMPLATES (Фича 8) ────────────────────────────────
# Шаблоны проектов для быстрого старта. Используются в:
# 1. Frontend UI (Templates.open() в app.js)
# 2. Orchestrator — распознаёт шаблонные запросы и сразу назначает правильного агента
PROJECT_TEMPLATES = [
    {
        "id": "ecommerce",
        "name": "Интернет-магазин",
        "icon": "🏪",
        "prompt": "Создай интернет-магазин с каталогом товаров, корзиной, оформлением заказа и интеграцией платёжной системы",
        "primary_agent": "designer",
        "primary_model": "gemini",
        "mode": "multi_sequential",
        "phases": [
            {"name": "Дизайн", "agents": ["designer"], "model": "sonnet", "description": "HTML/CSS магазина"},
            {"name": "Бэкенд", "agents": ["developer"], "model": "mimo", "description": "API, корзина, заказы"},
            {"name": "Деплой", "agents": ["devops"], "model": "mimo", "description": "Деплой на сервер"},
            {"name": "SEO", "agents": ["copywriter"], "model": "sonnet", "description": "Мета-теги, тексты, sitemap"},
            {"name": "Тест", "agents": ["tester"], "model": "minimax", "description": "Проверка работы"}
        ]
    },
    {
        "id": "corporate",
        "name": "Корпоративный сайт",
        "icon": "🏢",
        "prompt": "Создай корпоративный сайт компании: главная, о компании, услуги, портфолио, контакты, блог",
        "primary_agent": "designer",
        "primary_model": "gemini",
        "mode": "multi_sequential",
        "phases": [
            {"name": "Дизайн", "agents": ["designer"], "model": "sonnet", "description": "HTML/CSS сайта"},
            {"name": "SEO", "agents": ["copywriter"], "model": "sonnet", "description": "Мета-теги, тексты, sitemap"}
        ]
    },
    {
        "id": "landing_crm",
        "name": "Лендинг + CRM",
        "icon": "📱",
        "prompt": "Создай лендинг с формой заявки и интеграцией Битрикс24 для приёма лидов",
        "primary_agent": "designer",
        "primary_model": "gemini",
        "mode": "multi_sequential",
        "phases": [
            {"name": "Лендинг", "agents": ["designer"], "model": "sonnet", "description": "HTML лендинг с формой"},            {"name": "Интеграция", "agents": ["integrator"], "model": "mimo", "description": "Битрикс244 вебхук"}
        ]
    },
    {
        "id": "telegram_bot",
        "name": "Telegram бот",
        "icon": "🤖",
        "prompt": "Создай Telegram бота для приёма заявок с уведомлениями менеджеру",
        "primary_agent": "developer",
        "primary_model": "mimo",
        "mode": "single",
        "phases": [
            {"name": "Разработка", "agents": ["developer"], "model": "mimo", "description": "Python Telegram bot"}
        ]
    },
    {
        "id": "analytics_dashboard",
        "name": "Дашборд аналитики",
        "icon": "📊",
        "prompt": "Создай дашборд для визуализации данных из CSV/Excel с графиками и фильтрами",
        "primary_agent": "designer",
        "primary_model": "gemini",
        "mode": "multi_sequential",
        "phases": [
            {"name": "Дизайн", "agents": ["designer"], "model": "sonnet", "description": "UI дашборда с Chart.js"},
            {"name": "Данные", "agents": ["developer"], "model": "mimo", "description": "Парсинг CSV/Excel"}
        ]
    },
    {
        "id": "n8n_automation",
        "name": "n8n Автоматизация",
        "icon": "⚡",
        "prompt": "Настрой автоматизацию: форма на сайте → лид в Б24 → задача менеджеру → уведомление в Telegram",
        "primary_agent": "integrator",
        "primary_model": "mimo",
        "mode": "multi_sequential",
        "phases": [
            {"name": "Форма", "agents": ["designer"], "model": "sonnet", "description": "HTML форма заявки"},
            {"name": "Автоматизация", "agents": ["integrator"], "model": "mimo", "description": "n8n workflow"}
        ]
    }
]


# Improvement 4: Plan cache for repeated request types
_plan_cache = {}

class Orchestrator:
    def __init__(self, call_llm_func, orion_mode="turbo_standard"):
        self.call_llm = call_llm_func
        self.orion_mode = orion_mode
        self.project_context = ""

    def _chat_model_for_mode(self):
        """Return the correct primary_model key based on orion_mode."""
        if self.orion_mode == "premium":
            return "gpt54"  # PATCHED: was opus, now gpt54 (opus only as emergency fallback)
        elif self.orion_mode == "standard":
            return "gpt54"
        else:
            return "minimax"  # fast mode

    def plan(self, message, chat_history=None, has_ssh=False, ssh_info=""):
        msg = message.lower().strip()

        if self._is_simple_chat(msg):
            _chat_model = self._chat_model_for_mode()
            return {"mode":"chat","phases":[{"name":"Ответ","agents":["developer"],"model":_chat_model}],
                    "primary_model":_chat_model,"primary_agent":"developer","understanding":"Чат","ask_user":None}

        # Фича 8: распознаём шаблонные запросы и возвращаем готовый план
        template_plan = self._match_template(msg, message)
        if template_plan:
            return template_plan

        # BUGFIX: Серверные задачи (деплой, SSH, FTP, сайт-визитка) — всегда через LLM planner
        if self._needs_sonnet(msg) or self._is_full_site_task(msg):
            return self._llm_plan(message, chat_history, has_ssh, ssh_info)

        if self._is_obvious_design(msg):
            return {"mode":"single","phases":[{"name":"Дизайн","agents":["designer"],"model":"gemini",
                    "description":"Создать HTML/CSS","expected_output":"html_file"}],
                    "primary_model":"sonnet","primary_agent":"designer","understanding":"Создание веб-страницы","ask_user":None}

        if self._is_image_request(msg):
            return {"mode":"single","phases":[{"name":"Генерация","agents":["designer"],
                    "model":"gemini","description":"Создать изображение"}],
                    "primary_model":"sonnet","primary_agent":"designer",
                    "understanding":"Генерация изображения","ask_user":None}

        if self._is_obvious_code(msg):
            return {"mode":"single","phases":[{"name":"Разработка","agents":["developer"],"model":"mimo",
                    "description":"Написать код","expected_output":"code_file"}],
                    "primary_model":"mimo","primary_agent":"developer","understanding":"Написание кода","ask_user":None}

        # Opus для сверхсложных задач
        if False and self._needs_opus(msg):  # PATCHED: opus disabled, only emergency fallback
            return {
                "mode": "single",
                "phases": [{"name": "Архитектура", "agents": ["analyst"], "model": "opus",
                           "description": "Глубокий анализ и проектирование"}],
                "primary_model": "opus",
                "primary_agent": "analyst",
                "understanding": "Сложная задача — подключаю Opus",
                "ask_user": None
            }

        return self._llm_plan(message, chat_history, has_ssh, ssh_info)


    def _match_template(self, msg, original_message):
        """Фича 8: распознаём шаблонные запросы и возвращаем готовый план"""
        # Ключевые слова для каждого шаблона
        template_keywords = {
            "ecommerce": ["интернет-магазин", "интернет магазин", "онлайн магазин", "магазин с корзиной", "интернет магазин"],
            "corporate": ["корпоративный сайт", "сайт компании", "бизнес сайт"],
            "landing_crm": ["лендинг с формой", "лендинг и crm", "лендинг битрикс"],
            "telegram_bot": ["telegram бот", "телеграм бот", "bot telegram", "бот для telegram"],
            "analytics_dashboard": ["дашборд аналитики", "дашборд данных", "dashboard аналитика"],
            "n8n_automation": ["n8n автоматизация", "автоматизация n8n", "n8n workflow"]
        }
        for tmpl in PROJECT_TEMPLATES:
            tid = tmpl["id"]
            keywords = template_keywords.get(tid, [])
            if any(kw in msg for kw in keywords):
                logger.info(f"[Orchestrator] Template match: {tid}")
                return {
                    "mode": tmpl["mode"],
                    "phases": tmpl["phases"],
                    "primary_model": tmpl["primary_model"],
                    "primary_agent": tmpl["primary_agent"],
                    "understanding": f"Шаблон: {tmpl['name']}",
                    "ask_user": None,
                    "template_id": tid
                }
        return None

    def _needs_sonnet(self, msg):
        """Задача требует надёжного tool calling (серверы, деплой, FTP)?"""
        server_words = [
            "сервер", "деплой", "deploy", "ftp", "ssh", "загрузи на",
            "настрой", "админк", "nginx", "ssl", "certbot", "домен",
            "dns", "перенеси", "миграц", "хостинг", "битрикс", "bitrix",
            "на сайт", "на сервер", "создай страниц", "добавь в меню"
        ]
        return any(w in msg.lower() for w in server_words)

    def _needs_opus(self, msg):
        """Задача достаточно сложная для Opus?"""
        opus_triggers = [
            "спроектируй архитектуру", "архитектура системы",
            "проанализируй весь код", "полный аудит",
            "спроектируй базу данных", "микросервис",
            "масштабируемая система", "high load",
            "напиши техническое задание", "сложная интеграция",
            "проанализируй и предложи решение",
            "реструктуризация", "рефакторинг всего",
            "стратегия развития", "бизнес-анализ"
        ]
        return any(t in msg for t in opus_triggers)

    def _is_simple_chat(self, msg):
        patterns = [r"^привет",r"^здравствуй",r"^хай",r"^hello",r"^как дела",r"^что ты умеешь",
                    r"^кто ты",r"^расскажи\s+(про|о)",r"^объясни",r"^что такое",r"^почему",
                    r"^спасибо",r"^ок\b",r"^понял",r"^да\b",r"^нет\b"]
        if any(re.search(p, msg) for p in patterns):
            return True
        if len(msg)<30 and not any(w in msg for w in ["сделай","создай","напиши","настрой","подключи","задеплой","перенеси"]):
            return True
        return False

    def _is_obvious_design(self, msg):
        design = any(re.search(w,msg) for w in ["лендинг","landing","страниц.*сайт","баннер","макет","промо","вёрстк","верстк"])
        action = any(re.search(w,msg) for w in ["сделай","создай","нарисуй","сверстай"])
        complex_ = any(w in msg for w in ["битрикс","интеграц","деплой","сервер","api","магазин","корзин","оплат","n8n"])
        return design and action and not complex_

    def _is_image_request(self, msg):
        return any(w in msg for w in ["картинк","изображен","нарисуй","фото ",
                   "баннер","иллюстрац","иконк","лого","постер"])

    def _is_full_site_task(self, msg):
        """Задача на создание полноценного сайта (не просто дизайн)?"""
        site_words = ["сайт-визитк", "сайт визитк", "сайт под ключ", "создай сайт",
                      "сделай сайт", "нужен сайт", "разработай сайт",
                      "многостраничный", "корпоративный", "портфолио сайт"]
        has_site = any(w in msg for w in site_words)
        has_server = any(w in msg for w in ["ssh", "ftp", "ip ", "сервер", "домен",
                                             "beget", "хостинг", "nginx", "ssl"])
        has_structure = any(w in msg for w in ["структур", "секци", "страниц",
                                               "контакт", "услуг", "портфолио"])
        # Если есть упоминание сайта + (сервер ИЛИ структура) → это полная задача
        return has_site and (has_server or has_structure)

    def _is_obvious_code(self, msg):
        code = any(re.search(w,msg) for w in ["скрипт","функци","парсер","бот.*telegram","cli","утилит"])
        action = any(re.search(w,msg) for w in ["напиши","создай","сделай"])
        complex_ = any(w in msg for w in ["деплой","сервер","интеграц","битрикс"])
        return code and action and not complex_

    def _get_cache_key(self, msg):
        words = sorted(set(msg.lower().split()))
        key_words = [w for w in words if len(w) > 3 and w not in ['этот','этого','этих','нужно','можно','пожалуйста','сделай','создай','напиши']]
        return hash(tuple(key_words[:5]))

    def _llm_plan(self, message, chat_history=None, has_ssh=False, ssh_info=""):
        _cache_key = (self._get_cache_key(message), bool(has_ssh))
        if _cache_key in _plan_cache:
            cached = _plan_cache[_cache_key]
            if time.time() - cached['time'] < 3600:
                logger.info(f"[Orchestrator] Cache hit for plan (key={_cache_key})")
                return cached['plan']
        ctx_parts = []
        if self.project_context:
            ctx_parts.append(f"История проекта:\n{self.project_context}")
        ctx_parts.append(f"SSH: {'ДА. '+ssh_info if has_ssh else 'НЕТ'}")
        if chat_history:
            recent = chat_history[-10:]
            ctx_parts.append("Последние сообщения:\n"+"\n".join(f"{m.get('role','?')}: {m.get('content','')[:200]}" for m in recent))
        project_context = "\n\n".join(ctx_parts) or "Новый проект."

        system = PLANNER_SYSTEM_PROMPT.format(agents_capabilities=AGENTS_CAPABILITIES, project_context=project_context)
        messages = [{"role":"system","content":system},{"role":"user","content":f"Задача: {message}"}]

        try:
            response = self.call_llm(messages, model="minimax/minimax-m2.5")  # PATCH fix: real model ID
            logger.info(f"[Orchestrator] LLM raw response: {response[:3000] if response else 'EMPTY'}")
            plan = self._parse_json(response)
            logger.info(f"[Orchestrator] Parsed plan: {plan}")
            if plan:
                self.project_context += f"\n[{time.strftime('%H:%M')}] {message[:100]}\n"
                # Cache the plan
            if plan.get('mode') != 'chat' and not plan.get('ask_user'):
                _plan_cache[(self._get_cache_key(message), bool(has_ssh))] = {'plan': plan, 'time': time.time()}
            return plan
        except Exception as e:
            import traceback
            logger.warning(f"LLM planning failed: {e}")
            logger.warning(f"Orchestrator traceback: {traceback.format_exc()}")

        return {"mode":"single","phases":[{"name":"Выполнение","agents":["developer"],"model":"mimo"}],
                "primary_model":"mimo","primary_agent":"developer","understanding":"Fallback","ask_user":None}

    def _parse_json(self, response):
        text = response.strip()
        text = re.sub(r'^```json\s*','',text)
        text = re.sub(r'\s*```$','',text)
        text = re.sub(r'^```\s*','',text)
        # Also handle ``` in middle of text
        text = re.sub(r'```', '', text).strip()
        logging.info(f"[Orchestrator._parse_json] Text after cleanup (first 200): {text[:200]}")
        logging.info(f"[Orchestrator._parse_json] Text after cleanup (last 100): {text[-100:]}")
        try:
            plan = json.loads(text)
            logging.info(f"[Orchestrator._parse_json] json.loads OK, mode={plan.get('mode')}")
            plan.setdefault("phases",[{"name":"Выполнение","agents":["developer"],"model":"mimo"}])  # PATCH fix
            if not plan["phases"]:
                plan["phases"] = [{"name":"Выполнение","agents":["developer"],"model":"mimo"}]  # PATCH fix
            plan.setdefault("mode","single" if len(plan["phases"])==1 else "multi_sequential")
            plan.setdefault("primary_model",plan["phases"][0].get("model","mimo"))  # PATCH fix
            plan.setdefault("primary_agent",plan["phases"][0].get("agents",["developer"])[0])
            plan.setdefault("ask_user",None)
            # Normalize ask_user: convert objects to strings
            if isinstance(plan.get("ask_user"), list):
                normalized = []
                for item in plan["ask_user"]:
                    if isinstance(item, dict):
                        normalized.append(item.get("question", str(item)))
                    else:
                        normalized.append(str(item))
                plan["ask_user"] = normalized
            return plan
        except json.JSONDecodeError as e:
            logging.warning(f"[Orchestrator._parse_json] JSONDecodeError: {e}")
            logging.warning(f"[Orchestrator._parse_json] Problematic text around error: {text[max(0,e.pos-50):e.pos+50]}")
            match = re.search(r'\{[\s\S]*\}', text)
            if match:
                logging.info(f"[Orchestrator._parse_json] Trying regex match ({len(match.group())} chars)")
                try:
                    plan = json.loads(match.group())
                    logging.info(f"[Orchestrator._parse_json] Regex parse OK")
                    plan.setdefault("phases",[{"name":"Выполнение","agents":["developer"],"model":"mimo"}])  # PATCH fix
                    if not plan["phases"]:
                        plan["phases"] = [{"name":"Выполнение","agents":["developer"],"model":"mimo"}]  # PATCH fix
                    plan.setdefault("mode","single" if len(plan["phases"])==1 else "multi_sequential")
                    plan.setdefault("primary_model",plan["phases"][0].get("model","mimo"))  # PATCH fix
                    plan.setdefault("primary_agent",plan["phases"][0].get("agents",["developer"])[0])
                    plan.setdefault("ask_user",None)
                    return plan
                except Exception as e2:
                    logging.warning(f"[Orchestrator._parse_json] Regex parse also failed: {e2}")
            return None

    def update_context(self, result_summary):
        self.project_context += f"\nРезультат: {result_summary[:200]}\n"


    def save_phase_artifacts(self, task_id, chat_id, phase_name, agent_key, artifacts):
        """Save artifacts produced by an agent at end of a phase."""
        store = get_handoff_store()
        store.save(
            task_id=task_id,
            chat_id=chat_id,
            from_agent=agent_key,
            to_agent="next",
            artifact_type="phase_output",
            payload=artifacts,
            metadata={"phase": phase_name}
        )
        logger.info(f"[Orchestrator] Saved artifacts for phase '{phase_name}' from {agent_key}")

    def load_phase_artifacts(self, task_id, chat_id, phase_name=None):
        """Load artifacts from previous phases for context."""
        store = get_handoff_store()
        all_artifacts = store.get_all_for_task(task_id)
        if phase_name:
            return [a for a in all_artifacts if a.get("metadata", {}).get("phase") == phase_name]
        return all_artifacts

    def build_handoff_context(self, task_id, chat_id):
        """Build a context string from all previous phase artifacts."""
        artifacts = self.load_phase_artifacts(task_id, chat_id)
        if not artifacts:
            return ""
        parts = []
        for a in artifacts:
            phase = a.get("metadata", {}).get("phase", "unknown")
            from_agent = a.get("from_agent", "unknown")
            payload = a.get("payload", {})
            summary = payload.get("summary", "") if isinstance(payload, dict) else str(payload)[:500]
            parts.append(f"[Phase: {phase}, Agent: {from_agent}] {summary}")
        return "\n--- Previous Phase Artifacts ---\n" + "\n".join(parts)


def get_model_id(key):
    return MODEL_MAP.get(key, MODEL_MAP["minimax"])  # PATCH fix: minimax as default

def get_agent_prompt(key):
    return AGENT_PROMPTS.get(key, AGENT_PROMPTS["developer"])

def get_model_for_agent(agent_key, orion_mode="turbo_standard", task_hint=""):
    # ── DUAL-BRAIN: Turbo режимы используют MiniMax + MiMo ──
    if orion_mode in ("turbo_standard", "turbo_premium"):
        _ak = agent_key.lower().strip()  # normalize to lowercase
        # HANDS agents (SSH, FTP, деплой) → MiMo-V2-Flash
        _hands_agents = {"devops", "developer", "integrator"}
        # BRAIN agents (дизайн, анализ, тексты) → MiniMax M2.5
        if _ak in _hands_agents:
            return "xiaomi/mimo-v2-flash"  # MiMo для операций
        else:
            return "minimax/minimax-m2.5"  # MiniMax для мышления
    if agent_key=="designer": return MODEL_MAP["sonnet"]  # Sonnet делает красивый HTML/CSS
    if agent_key=="copywriter": return MODEL_MAP["sonnet"]  # ПАТЧ W2-3
    if agent_key=="analyst" and "pro" in orion_mode and "premium" in orion_mode: return MODEL_MAP["sonnet"]
    if agent_key=="architect" or (agent_key=="analyst" and orion_mode=="architect"): return MODEL_MAP["opus"]
    if orion_mode=="architect" and agent_key in ("code_reviewer","intent_clarifier","orchestrator"): return MODEL_MAP["opus"]
    # ── ПАТЧ 5: Sonnet для серверных задач (Pro режимы) ──
    if "pro" in orion_mode and task_hint:
        _server_words = ["сервер", "деплой", "ftp", "ssh", "загрузи", "настрой",
                         "админк", "nginx", "битрикс", "bitrix", "на сайт",
                         "создай страниц", "добавь в меню", "перенеси"]
        if any(w in task_hint.lower() for w in _server_words):
            return MODEL_MAP["sonnet"]
    return MODEL_MAP.get("minimax", "minimax/minimax-m2.5")  # PATCH fix: minimax as default for pro modes

def format_plan_sse(plan):
    return {"type":"task_plan","understanding":plan.get("understanding",""),"mode":plan.get("mode","single"),
            "steps":[{"name":p.get("name",""),"agents":p.get("agents",[]),"parallel":p.get("parallel",False),
            "status":"pending","model":p.get("model","mimo")} for p in plan.get("phases",[])],
            "total_phases":len(plan.get("phases",[])),"primary_model":plan.get("primary_model","minimax"),
            "requires_ssh":plan.get("requires_ssh",False),"ask_user":plan.get("ask_user"),
            "warnings":plan.get("warnings",[])}

