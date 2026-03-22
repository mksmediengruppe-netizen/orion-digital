"""
Specialized Agents v7.0 — ORION Digital
========================================
6 агентов: Designer, Developer, DevOps, Tester, Analyst, Integrator.

Модели по MASTER_PROMPT:
  designer   → gemini   (google/gemini-2.5-pro)
  developer  → mimo     (openai/gpt-5.4-nano)   — hands
  devops     → mimo     (openai/gpt-5.4-nano)   — hands
  tester     → minimax  (openai/gpt-5.4-mini)   — brain
  analyst    → gpt54_mini / sonnet в premium   — brain
  integrator → mimo     (openai/gpt-5.4-nano)   — hands

preferred_model берётся из model_router по роли и режиму.
"""

import re
import logging
from typing import Dict, Any, List, Optional

from model_router import get_model_for_agent, DEFAULT_MODE

logger = logging.getLogger("specialized_agents")


# ══════════════════════════════════════════════════════════════
# AGENT DEFINITIONS
# ══════════════════════════════════════════════════════════════

SPECIALIZED_AGENTS = {
    "designer": {
        "name": "Дизайнер",
        "emoji": "🎨",
        "role": "designer",
        # Gemini — визуальное мышление (MASTER_PROMPT)
        "preferred_model": "google/gemini-2.5-pro",
        "model_key": "gemini",
        "priority_tools": [
            "generate_design", "generate_image", "edit_image",
            "create_artifact", "browser_navigate", "browser_get_text"
        ],
        "prompt_suffix": """Ты — Senior UI/UX Designer и Front-End специалист.

ЭКСПЕРТИЗА:
- UI/UX дизайн: wireframes, mockups, прототипы
- CSS/SCSS: адаптивная вёрстка, анимации, градиенты
- Дизайн-системы: компоненты, цветовые палитры, типографика
- Визуальный контент: баннеры, логотипы, инфографика
- Accessibility: WCAG 2.1, семантический HTML

ИНСТРУМЕНТЫ (используй по приоритету):
1. create_artifact — для HTML/CSS макетов и компонентов
2. generate_design — для баннеров, постов, визиток
3. generate_image — для иллюстраций и мокапов
4. edit_image — для редактирования изображений
5. browser_navigate — для анализа существующих сайтов

ПРАВИЛА:
- Всегда создавай ВИЗУАЛЬНЫЙ результат (HTML, изображение, дизайн)
- Используй современные CSS (flexbox, grid, custom properties)
- Адаптивный дизайн по умолчанию (mobile-first)
- Красивые градиенты, тени, анимации
- Профессиональная типографика и spacing"""
    },

    "developer": {
        "name": "Разработчик",
        "emoji": "💻",
        "role": "developer",
        # MiMo — код, SSH, DevOps (hands)
        "preferred_model": "openai/gpt-5.4-nano",  # PATCH fix: mimo hands
        "model_key": "mimo",
        "priority_tools": [
            "ssh_execute", "file_write", "file_read",
            "code_interpreter", "generate_file"
        ],
        "prompt_suffix": """Ты — Senior Full-Stack Developer с 10+ лет опыта.

ЭКСПЕРТИЗА:
- Backend: Python (Flask, FastAPI, Django), Node.js (Express, Nest)
- Frontend: React, Vue, Svelte, Vanilla JS
- Базы данных: PostgreSQL, MySQL, MongoDB, Redis, SQLite
- API: REST, GraphQL, WebSocket, gRPC
- Паттерны: Clean Architecture, SOLID, DDD, Event-Driven

ИНСТРУМЕНТЫ (используй по приоритету):
1. file_write — для создания/изменения кода на сервере
2. ssh_execute — для запуска команд, установки зависимостей
3. file_read — для чтения существующего кода
4. code_interpreter — для тестирования логики в песочнице
5. generate_file — для создания файлов на скачивание

ПРАВИЛА:
- Production-ready код с обработкой ошибок
- Комментарии на русском языке
- Type hints в Python, TypeScript где возможно
- Тесты для критичной логики
- Логирование важных операций
- Безопасность: валидация входных данных, SQL injection protection"""
    },

    "devops": {
        "name": "DevOps",
        "emoji": "🔧",
        "role": "devops",
        # MiMo — серверные операции (hands)
        "preferred_model": "openai/gpt-5.4-nano",  # PATCH fix: mimo hands
        "model_key": "mimo",
        "priority_tools": [
            "ssh_execute", "file_write", "file_read",
            "browser_check_site", "browser_check_api"
        ],
        "prompt_suffix": """Ты — Senior DevOps Engineer / SRE.

ЭКСПЕРТИЗА:
- Linux: Ubuntu, CentOS, systemd, journalctl, cron
- Веб-серверы: Nginx, Apache, Caddy, reverse proxy
- Контейнеры: Docker, Docker Compose, Kubernetes
- CI/CD: GitHub Actions, GitLab CI, Jenkins
- Мониторинг: Prometheus, Grafana, ELK Stack
- Безопасность: UFW, fail2ban, SSL/TLS, SSH hardening
- Базы данных: backup, replication, optimization

ИНСТРУМЕНТЫ (используй по приоритету):
1. ssh_execute — для ВСЕХ серверных операций
2. file_write — для конфигов (nginx, systemd, docker-compose)
3. file_read — для проверки конфигов и логов
4. browser_check_site — для проверки доступности
5. browser_check_api — для тестирования API endpoints

ПРАВИЛА:
- Всегда делай бэкап перед изменениями (cp file file.bak)
- Проверяй конфиги перед применением (nginx -t, systemctl --check)
- Используй systemd для сервисов (не nohup)
- SSL через certbot/Let's Encrypt
- Логируй все действия
- Проверяй результат после каждого действия"""
    },

    "tester": {
        "name": "Тестировщик",
        "emoji": "🧪",
        "role": "tester",
        # MiniMax — быстрые проверки (brain)
        "preferred_model": "openai/gpt-5.4-mini",  # PATCH fix: gpt54_mini worker
        "model_key": "gpt54_mini",
        "priority_tools": [
            "browser_navigate", "browser_get_text", "browser_check_site",
            "browser_check_api", "code_interpreter", "ssh_execute"
        ],
        "prompt_suffix": """Ты — Senior QA Engineer / Test Automation Specialist.

ЭКСПЕРТИЗА:
- E2E тестирование: Selenium, Playwright, Cypress
- API тестирование: Postman, curl, pytest
- Нагрузочное тестирование: k6, JMeter, wrk
- Security тестирование: OWASP Top 10, SQL injection, XSS
- Мониторинг: health checks, uptime, response time

ИНСТРУМЕНТЫ (используй по приоритету):
1. browser_navigate — для E2E тестирования UI
2. browser_get_text — для проверки контента страниц
3. browser_check_api — для тестирования API endpoints
4. browser_check_site — для проверки доступности
5. code_interpreter — для написания и запуска тестов
6. ssh_execute — для проверки логов и процессов

ПРАВИЛА:
- Тестируй ВСЕ основные сценарии (happy path + edge cases)
- Проверяй HTTP статус коды (200, 301, 404, 500)
- Проверяй время ответа (< 2 сек для UI, < 500мс для API)
- Проверяй SSL сертификат
- Проверяй мобильную версию
- Документируй найденные баги: Шаги → Ожидание → Факт
- Создавай отчёт о тестировании"""
    },

    "analyst": {
        "name": "Аналитик",
        "emoji": "📊",
        "role": "analyst",
        # GPT-5.4 Mini / Sonnet в premium (brain)
        "preferred_model": "openai/gpt-5.4-mini",  # PATCH fix: gpt54_mini worker
        "model_key": "gpt54_mini",
        "priority_tools": [
            "web_search", "web_fetch", "code_interpreter",
            "generate_chart", "generate_file", "generate_report",
            "read_any_file"
        ],
        "prompt_suffix": """Ты — Senior Data Analyst / Business Analyst.

ЭКСПЕРТИЗА:
- Анализ данных: pandas, numpy, scipy, sklearn
- Визуализация: matplotlib, plotly, seaborn, Chart.js
- Бизнес-анализ: SWOT, Porter's 5 Forces, BCG Matrix
- Исследования: конкурентный анализ, рыночные тренды
- Отчёты: структурированные документы с графиками

ИНСТРУМЕНТЫ (используй по приоритету):
1. web_search — для поиска актуальной информации
2. web_fetch — для получения данных с веб-страниц
3. read_any_file — для анализа загруженных файлов
4. code_interpreter — для обработки данных и расчётов
5. generate_chart — для визуализации данных
6. generate_report — для создания отчётов
7. generate_file — для создания документов

ПРАВИЛА:
- Всегда указывай источники данных
- Визуализируй ключевые метрики (графики, таблицы)
- Структурируй отчёты: Введение → Методология → Данные → Анализ → Выводы
- Используй числа и факты, не общие фразы
- Сравнивай с бенчмарками и конкурентами
- Давай конкретные рекомендации"""
    },

    "integrator": {
        "name": "Интегратор",
        "emoji": "🔌",
        "role": "integrator",
        # MiMo — интеграции и API (hands)
        "preferred_model": "openai/gpt-5.4-nano",  # PATCH fix: mimo hands
        "model_key": "mimo",
        "priority_tools": [
            "ssh_execute", "file_write", "file_read",
            "browser_check_api", "code_interpreter", "web_fetch"
        ],
        "prompt_suffix": """Ты — Senior Integration Engineer / API Specialist.

ЭКСПЕРТИЗА:
- API интеграции: REST, GraphQL, WebSocket, SOAP
- Вебхуки: настройка, обработка, retry logic
- Очереди: RabbitMQ, Redis Pub/Sub, Kafka
- Аутентификация: OAuth 2.0, JWT, API Keys, HMAC
- Платёжные системы: Stripe, PayPal, Tinkoff, YooKassa
- Мессенджеры: Telegram Bot API, Slack API, Discord
- CRM/ERP: Bitrix24, AmoCRM, 1C

ИНСТРУМЕНТЫ (используй по приоритету):
1. file_write — для создания интеграционного кода
2. ssh_execute — для установки и настройки
3. browser_check_api — для тестирования API
4. code_interpreter — для прототипирования
5. file_read — для чтения конфигов
6. web_fetch — для проверки внешних API

ПРАВИЛА:
- Всегда обрабатывай ошибки API (timeout, rate limit, auth errors)
- Используй retry с exponential backoff
- Логируй все запросы и ответы
- Валидируй входные/выходные данные
- Храни секреты в env variables, не в коде
- Документируй API endpoints и payload formats"""
    },
    # ПАТЧ W2-3: Copywriter + SEO агент
    "copywriter": {
        "name": "Копирайтер",
        "emoji": "✍️",
        "role": "copywriter",
        "preferred_model": "anthropic/claude-sonnet-4.6",
        "model_key": "sonnet",
        "priority_tools": [
            "file_write", "file_read", "browser_get_text",
            "web_search", "generate_file", "ssh_execute"
        ],
        "prompt_suffix": """Ты — SEO-копирайтер и контент-стратег.

ЭКСПЕРТИЗА:
- SEO-оптимизация: мета-теги, title, description, Open Graph
- Контент-стратегия: тексты для лендингов, карточек товаров, блогов
- Технический SEO: sitemap.xml, robots.txt, structured data (JSON-LD)
- Alt-тексты для изображений
- Анализ конкурентов и ключевых слов

ИНСТРУМЕНТЫ:
1. browser_get_text — прочитать текущий контент сайта
2. file_write — создать/обновить файлы на сервере
3. ssh_execute — загрузить файлы, проверить структуру сайта
4. web_search — анализ конкурентов, подбор ключевых слов
5. generate_file — создать документ с текстами

ПРАВИЛА:
- Каждый текст оптимизирован под 2-3 ключевые фразы
- Title: 50-60 символов, ключевое слово в начале
- Description: 150-160 символов, призыв к действию
- Alt: описательный, с ключевым словом, 5-15 слов
- СОЗДАВАЙ файлы через file_write, НЕ ОПИСЫВАЙ что нужно сделать"""
    }
}


# ══════════════════════════════════════════════════════════════
# DYNAMIC MODEL RESOLUTION (из model_router по режиму)
# ══════════════════════════════════════════════════════════════

def get_agent_model(agent_key: str, mode: str = DEFAULT_MODE) -> str:
    """
    Получить model_id для агента с учётом текущего режима.
    Приоритет: model_router → fallback на preferred_model агента.
    """
    try:
        cfg = get_model_for_agent(agent_key, mode)
        return cfg.get("id", SPECIALIZED_AGENTS[agent_key]["preferred_model"])
    except Exception:
        return SPECIALIZED_AGENTS.get(agent_key, {}).get(
            "preferred_model", "openai/gpt-5.4-mini"  # PATCH fix
        )


# ══════════════════════════════════════════════════════════════
# AGENT SELECTION RULES
# ══════════════════════════════════════════════════════════════

AGENT_SELECTION_RULES = {
    "designer": {
        "keywords": [
            "дизайн", "design", "ui", "ux", "макет", "mockup", "wireframe",
            "css", "стиль", "style", "лендинг", "landing", "баннер", "banner",
            "логотип", "logo", "визитка", "card", "инфографика", "infographic",
            "красив", "beautiful", "анимаци", "animation", "адаптив", "responsive",
            "вёрстка", "layout", "компонент", "component", "тема", "theme"
        ],
        "patterns": [
            r"(сделай|создай|нарисуй).*(дизайн|макет|лендинг|баннер|логотип)",
            r"(красив|стильн|современн).*(сайт|страниц|интерфейс)",
        ]
    },
    "developer": {
        "keywords": [
            "код", "code", "функци", "function", "класс", "class", "модуль", "module",
            "api", "endpoint", "backend", "frontend", "react", "vue", "python",
            "javascript", "typescript", "база данных", "database", "sql",
            "приложение", "application", "сервис", "service", "бот", "bot",
            "скрипт", "script", "алгоритм", "algorithm", "рефактор", "refactor"
        ],
        "patterns": [
            r"(напиши|создай|разработай).*(код|функци|класс|api|бот|скрипт)",
            r"(исправь|fix|debug).*(баг|ошибк|bug|error)",
        ]
    },
    "devops": {
        "keywords": [
            "сервер", "server", "деплой", "deploy", "nginx", "docker", "kubernetes",
            "ssl", "https", "certbot", "systemd", "systemctl", "ufw", "firewall",
            "бэкап", "backup", "мониторинг", "monitoring", "ci/cd", "pipeline",
            "github actions", "gitlab", "jenkins", "ansible", "terraform",
            "порт", "port", "домен", "domain", "dns", "vps"
        ],
        "patterns": [
            r"(настрой|установи|задеплой|разверни).*(сервер|nginx|docker|ssl)",
            r"(проверь|перезапусти|обнови).*(сервис|сервер|nginx|процесс)",
            r"\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b",
        ]
    },
    "tester": {
        "keywords": [
            "тест", "test", "проверь", "check", "qa", "баг", "bug",
            "e2e", "selenium", "playwright", "нагрузк", "load",
            "доступност", "accessibility", "скорост", "performance",
            "безопасност", "security", "уязвимост", "vulnerability"
        ],
        "patterns": [
            r"(протестируй|проверь|проведи тест).*(сайт|api|приложение|сервис)",
            r"(найди|проверь).*(баг|ошибк|уязвимост)",
        ]
    },
    "analyst": {
        "keywords": [
            "анализ", "analysis", "исследован", "research", "отчёт", "report",
            "данные", "data", "статистик", "statistics", "график", "chart",
            "конкурент", "competitor", "рынок", "market", "тренд", "trend",
            "метрик", "metric", "kpi", "roi", "swot", "бизнес-план"
        ],
        "patterns": [
            r"(проанализируй|исследуй|изучи).*(данные|рынок|конкурент|тренд)",
            r"(создай|сделай).*(отчёт|анализ|исследование|презентаци)",
        ]
    },
    "integrator": {
        "keywords": [
            "интеграци", "integration", "webhook", "вебхук", "api подключ",
            "oauth", "jwt", "token", "stripe", "telegram bot", "slack",
            "bitrix", "amocrm", "1c", "crm", "erp", "rabbitmq", "kafka",
            "платёж", "payment", "yookassa", "tinkoff"
        ],
        "patterns": [
            r"(подключи|интегрируй|настрой).*(api|webhook|бот|crm|платёж)",
            r"(отправ|получ).*(webhook|api|запрос)",
        ]
    },
    # ПАТЧ W2-3: Copywriter + SEO агент (только keywords + patterns)
    "copywriter": {
        "keywords": [
            "seo", "мета-тег", "meta", "title", "description", "og:",
            "sitemap", "robots.txt", "копирайт", "текст для сайта",
            "alt текст", "ключевые слова", "контент", "open graph"
        ],
        "patterns": [
            r"(напиши|создай|добавь).*(мета|seo|текст|sitemap|robots)",
            r"(оптимизируй|улучши).*(текст|контент|seo)",
        ]
    }
}


# ══════════════════════════════════════════════════════════════
# PUBLIC API
# ══════════════════════════════════════════════════════════════

def select_agents_for_task(user_message: str, mode: str = "chat",
                           max_agents: int = 3,
                           orion_mode: str = DEFAULT_MODE) -> List[Dict[str, Any]]:
    """
    Выбрать лучших агентов для задачи.
    orion_mode — режим ORION (fast / premium / ...)
    """
    msg_lower = user_message.lower()
    scores = {}

    for agent_key, rules in AGENT_SELECTION_RULES.items():
        score = 0
        for kw in rules["keywords"]:
            if kw in msg_lower:
                score += 1
        for pattern in rules.get("patterns", []):
            if re.search(pattern, msg_lower):
                score += 3

        # Mode-based boost
        if mode == "deploy" and agent_key == "devops":
            score += 5
        elif mode == "file" and agent_key in ("developer", "analyst"):
            score += 3
        elif mode == "research" and agent_key == "analyst":
            score += 5
        elif mode == "data" and agent_key == "analyst":
            score += 5

        if score > 0:
            scores[agent_key] = score

    if not scores:
        if mode == "deploy":
            scores = {"devops": 5, "developer": 3}
        elif mode == "file":
            scores = {"developer": 3, "analyst": 2}
        elif mode in ("research", "data"):
            scores = {"analyst": 5}
        else:
            scores = {"developer": 3}

    sorted_agents = sorted(scores.items(), key=lambda x: x[1], reverse=True)[:max_agents]

    result = []
    for agent_key, score in sorted_agents:
        agent_config = SPECIALIZED_AGENTS[agent_key].copy()
        agent_config["score"] = score
        agent_config["key"] = agent_key
        # Динамически подставляем модель из model_router
        agent_config["preferred_model"] = get_agent_model(agent_key, orion_mode)
        result.append(agent_config)

    return result


def get_agent_config(agent_key: str, orion_mode: str = DEFAULT_MODE) -> Optional[Dict[str, Any]]:
    """Получить конфигурацию агента с актуальной моделью."""
    cfg = SPECIALIZED_AGENTS.get(agent_key)
    if cfg:
        cfg = cfg.copy()
        cfg["preferred_model"] = get_agent_model(agent_key, orion_mode)
    return cfg


def get_all_agents(orion_mode: str = DEFAULT_MODE) -> Dict[str, Dict[str, Any]]:
    """Все агенты с актуальными моделями для текущего режима."""
    result = {}
    for key, cfg in SPECIALIZED_AGENTS.items():
        result[key] = cfg.copy()
        result[key]["preferred_model"] = get_agent_model(key, orion_mode)
    return result


def get_agent_pipeline(task_type: str) -> List[str]:
    """Рекомендованный pipeline агентов для типа задачи."""
    pipelines = {
        "deploy":       ["devops", "developer", "tester"],
        "website":      ["designer", "copywriter", "developer", "devops", "tester"],
        "api":          ["developer", "integrator", "tester"],
        "analysis":     ["analyst"],
        "design":       ["designer"],
        "integration":  ["integrator", "developer", "tester"],
        "full_project": ["analyst", "designer", "copywriter", "developer", "devops", "tester", "integrator"],
        "default":      ["developer"],
    }
    return pipelines.get(task_type, pipelines["default"])
