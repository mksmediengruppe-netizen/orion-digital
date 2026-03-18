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
import os
import time
import re
from typing import Dict, List, Any, Optional

logger = logging.getLogger("orchestrator")

AGENTS_CAPABILITIES = """
Доступные агенты:
1. DESIGNER (Gemini) — HTML/CSS, лендинги, UI/UX, вёрстка, баннеры
2. DEVELOPER (DeepSeek) — Python, Node.js, PHP, API, базы данных, боты, скрипты
3. DEVOPS (DeepSeek) — SSH, nginx, Docker, SSL, DNS, деплой, миграция серверов
4. INTEGRATOR (DeepSeek) — Битрикс24, Telegram, платежи, n8n, вебхуки, CRM
5. TESTER (DeepSeek) — тестирование сайтов, форм, SSL, мобильной версии
6. ANALYST (DeepSeek/Sonnet) — архитектура, анализ, отчёты, code review
7. ARCHITECT (Claude Opus 4) — сложная архитектура, глубокий анализ, аудит кода, проектирование систем. Вызывается ТОЛЬКО для задач максимальной сложности.
8. COPYWRITER (Sonnet) — SEO-тексты, мета-теги, title/description, Open Graph, alt для картинок, sitemap.xml, robots.txt. Вызывается ПОСЛЕ дизайнера при создании сайтов.

Все агенты имеют доступ к: SSH, браузер, файлы, поиск, код.
"""

PLANNER_SYSTEM_PROMPT = """Ты — проджект-менеджер AI-компании ORION Digital.
Составь ПЛАН ВЫПОЛНЕНИЯ задачи.
Пользователь может быть непрофессионалом. Он говорит простым языком.

{agents_capabilities}

ПРАВИЛА:
1. Разбивай на фазы. Если агенты независимы — parallel: true.
2. Designer ВСЕГДА для дизайна (model: gemini).
3. После деплоя ВСЕГДА ставь Tester.
4. Если нужны доступы — укажи в ask_user.
5. Простая задача → mode: "single". Сложная → "multi_sequential" или "multi_parallel".

КОНТЕКСТ: {project_context}

ОТВЕТ — строго JSON:
{{"understanding":"что понял","mode":"single|multi_sequential|multi_parallel","ask_user":null,"phases":[{{"name":"Фаза","agents":["designer"],"parallel":false,"description":"Что делать","model":"gemini|deepseek|sonnet","requires_ssh":false,"expected_output":"html_file|code_file|deployed_site|report"}}],"primary_model":"gemini","primary_agent":"designer","requires_ssh":false,"requires_api_keys":[],"estimated_time":"2-5 мин","warnings":[]}}"""

AGENT_PROMPTS = {
    "designer": """Ты — ведущий веб-дизайнер ORION Digital.

ТЫ СОЗДАЁШЬ, А НЕ ОПИСЫВАЕШЬ. Сохрани через create_artifact/file_write.
НЕ ПИШИ код в чат. Google Fonts, адаптив, градиенты, анимации, минимум 5 секций.
Стиль: как Stripe/Linear/Vercel.
Если дан URL — открой через browser_navigate, изучи и сделай на основе.""",

    "developer": """Ты — senior full-stack разработчик ORION Digital.

ПИШЕШЬ КОД И СОХРАНЯЕШЬ, НЕ ОПИСЫВАЕШЬ.
Сохраняй через file_write. Если есть SSH — выполняй на сервере.
НИКОГДА не говори "скопируйте код". СОХРАНЯЙ в файл.""",

    "devops": """Ты — DevOps инженер ORION Digital.

ВЫПОЛНЯЕШЬ ЧЕРЕЗ SSH, НЕ ОПИСЫВАЕШЬ.
Деплой: проверить сервер → загрузить файлы → nginx → SSL → проверить.
Миграция: скачать со старого → загрузить на новый → DNS → проверить.
Если нужны доступы к серверу — спроси через ask_user.
НИКОГДА не говори "выполните команду". ВЫПОЛНЯЙ через ssh_execute.""",

    "integrator": """Ты — специалист по интеграциям ORION Digital.

ПОДКЛЮЧАЕШЬ API, НЕ ОПИСЫВАЕШЬ.
Если нужны API ключи/токены — спроси через ask_user.
Тестируй интеграцию после подключения. Сохраняй код в файл.""",

    "tester": """Ты — QA инженер ORION Digital.

ТЕСТИРУЕШЬ РЕАЛЬНО ЧЕРЕЗ БРАУЗЕР И SSH.
Чеклист: HTTP 200, все страницы, формы, мобильная, SSL, скорость, логи.
Формат: ✅ OK / ❌ Баг с описанием.""",

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
    "gemini": "google/gemini-2.5-pro",
    "deepseek": "openai/gpt-4.1-mini",
    "sonnet": "anthropic/claude-sonnet-4.6",
    "opus": "anthropic/claude-opus-4"
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
            {"name": "Дизайн", "agents": ["designer"], "model": "gemini", "description": "HTML/CSS магазина"},
            {"name": "Бэкенд", "agents": ["developer"], "model": "deepseek", "description": "API, корзина, заказы"},
            {"name": "Деплой", "agents": ["devops"], "model": "deepseek", "description": "Деплой на сервер"},
            {"name": "SEO", "agents": ["copywriter"], "model": "sonnet", "description": "Мета-теги, тексты, sitemap"},
            {"name": "Тест", "agents": ["tester"], "model": "deepseek", "description": "Проверка работы"}
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
            {"name": "Дизайн", "agents": ["designer"], "model": "gemini", "description": "HTML/CSS сайта"},
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
            {"name": "Лендинг", "agents": ["designer"], "model": "gemini", "description": "HTML лендинг с формой"},
            {"name": "Интеграция", "agents": ["integrator"], "model": "deepseek", "description": "Битрикс24 вебхук"}
        ]
    },
    {
        "id": "telegram_bot",
        "name": "Telegram бот",
        "icon": "🤖",
        "prompt": "Создай Telegram бота для приёма заявок с уведомлениями менеджеру",
        "primary_agent": "developer",
        "primary_model": "deepseek",
        "mode": "single",
        "phases": [
            {"name": "Разработка", "agents": ["developer"], "model": "deepseek", "description": "Python Telegram bot"}
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
            {"name": "Дизайн", "agents": ["designer"], "model": "gemini", "description": "UI дашборда с Chart.js"},
            {"name": "Данные", "agents": ["developer"], "model": "deepseek", "description": "Парсинг CSV/Excel"}
        ]
    },
    {
        "id": "n8n_automation",
        "name": "n8n Автоматизация",
        "icon": "⚡",
        "prompt": "Настрой автоматизацию: форма на сайте → лид в Б24 → задача менеджеру → уведомление в Telegram",
        "primary_agent": "integrator",
        "primary_model": "deepseek",
        "mode": "multi_sequential",
        "phases": [
            {"name": "Форма", "agents": ["designer"], "model": "gemini", "description": "HTML форма заявки"},
            {"name": "Автоматизация", "agents": ["integrator"], "model": "deepseek", "description": "n8n workflow"}
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

    def plan(self, message, chat_history=None, has_ssh=False, ssh_info=""):
        msg = message.lower().strip()

        if self._is_simple_chat(msg):
            return {"mode":"chat","phases":[{"name":"Ответ","agents":["developer"],"model":"deepseek"}],
                    "primary_model":"deepseek","primary_agent":"developer","understanding":"Чат","ask_user":None}

        # Фича 8: распознаём шаблонные запросы и возвращаем готовый план
        template_plan = self._match_template(msg, message)
        if template_plan:
            return template_plan

        if self._is_obvious_design(msg):
            return {"mode":"single","phases":[{"name":"Дизайн","agents":["designer"],"model":"gemini",
                    "description":"Создать HTML/CSS","expected_output":"html_file"}],
                    "primary_model":"gemini","primary_agent":"designer","understanding":"Создание веб-страницы","ask_user":None}

        if self._is_image_request(msg):
            return {"mode":"single","phases":[{"name":"Генерация","agents":["designer"],
                    "model":"gemini","description":"Создать изображение"}],
                    "primary_model":"gemini","primary_agent":"designer",
                    "understanding":"Генерация изображения","ask_user":None}

        if self._is_obvious_code(msg):
            return {"mode":"single","phases":[{"name":"Разработка","agents":["developer"],"model":"deepseek",
                    "description":"Написать код","expected_output":"code_file"}],
                    "primary_model":"deepseek","primary_agent":"developer","understanding":"Написание кода","ask_user":None}

        # Opus для сверхсложных задач
        if self._needs_opus(msg):
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
        _cache_key = self._get_cache_key(message)
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
            response = self.call_llm(messages, model="openai/gpt-4.1-mini")
            logger.info(f"[Orchestrator] LLM raw response: {response[:3000] if response else 'EMPTY'}")
            plan = self._parse_json(response)
            logger.info(f"[Orchestrator] Parsed plan: {plan}")
            if plan:
                self.project_context += f"\n[{time.strftime('%H:%M')}] {message[:100]}\n"
                # Cache the plan
            if plan.get('mode') != 'chat':
                _plan_cache[self._get_cache_key(message)] = {'plan': plan, 'time': time.time()}
            return plan
        except Exception as e:
            import traceback
            logger.warning(f"LLM planning failed: {e}")
            logger.warning(f"Orchestrator traceback: {traceback.format_exc()}")

        return {"mode":"single","phases":[{"name":"Выполнение","agents":["developer"],"model":"deepseek"}],
                "primary_model":"deepseek","primary_agent":"developer","understanding":"Fallback","ask_user":None}

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
            plan.setdefault("phases",[{"name":"Выполнение","agents":["developer"],"model":"deepseek"}])
            plan.setdefault("mode","single" if len(plan["phases"])==1 else "multi_sequential")
            plan.setdefault("primary_model",plan["phases"][0].get("model","deepseek"))
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
                    plan.setdefault("phases",[{"name":"Выполнение","agents":["developer"],"model":"deepseek"}])
                    plan.setdefault("mode","single" if len(plan["phases"])==1 else "multi_sequential")
                    plan.setdefault("primary_model",plan["phases"][0].get("model","deepseek"))
                    plan.setdefault("primary_agent",plan["phases"][0].get("agents",["developer"])[0])
                    plan.setdefault("ask_user",None)
                    return plan
                except Exception as e2:
                    logging.warning(f"[Orchestrator._parse_json] Regex parse also failed: {e2}")
            return None

    def update_context(self, result_summary):
        self.project_context += f"\nРезультат: {result_summary[:200]}\n"


def get_model_id(key):
    return MODEL_MAP.get(key, MODEL_MAP["deepseek"])

def get_agent_prompt(key):
    return AGENT_PROMPTS.get(key, AGENT_PROMPTS["developer"])

def get_model_for_agent(agent_key, orion_mode="turbo_standard", task_hint=""):
    if agent_key=="designer": return MODEL_MAP["gemini"]
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
    return MODEL_MAP["deepseek"]

def format_plan_sse(plan):
    return {"type":"task_plan","understanding":plan.get("understanding",""),"mode":plan.get("mode","single"),
            "steps":[{"name":p.get("name",""),"agents":p.get("agents",[]),"parallel":p.get("parallel",False),
            "status":"pending","model":p.get("model","deepseek")} for p in plan.get("phases",[])],
            "total_phases":len(plan.get("phases",[])),"primary_model":plan.get("primary_model","deepseek"),
            "requires_ssh":plan.get("requires_ssh",False),"ask_user":plan.get("ask_user"),
            "warnings":plan.get("warnings",[])}
