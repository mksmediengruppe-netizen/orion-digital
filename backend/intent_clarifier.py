"""
Intent Clarifier v1.0 — ORION Digital
======================================
Анализирует входящий запрос пользователя и:
1. Определяет intent (тип задачи)
2. Выбирает агентов
3. Оценивает сложность
4. Решает нужно ли уточнение (ask_user)
5. Выбирает режим выполнения

Интегрируется в agent_loop.py как первый узел графа.
"""

import re
import logging
from typing import Dict, Any, List, Optional, Tuple

logger = logging.getLogger("intent_clarifier")


# ══════════════════════════════════════════════════════════════
# INTENT TYPES
# ══════════════════════════════════════════════════════════════

INTENT_TYPES = {
    "chat":     "Общение, вопросы, объяснения",
    "code":     "Написание, исправление, рефакторинг кода",
    "deploy":   "Деплой, настройка серверов, DevOps",
    "design":   "UI/UX дизайн, вёрстка, визуальный контент",
    "research": "Исследование, анализ, поиск информации",
    "data":     "Анализ данных, графики, отчёты",
    "file":     "Работа с файлами, документами",
    "integrate":"Интеграции, API, вебхуки",
    "test":     "Тестирование, QA, проверка",
    "plan":     "Планирование, архитектура, стратегия",
}

# ══════════════════════════════════════════════════════════════
# INTENT DETECTION RULES
# ══════════════════════════════════════════════════════════════

INTENT_RULES = {
    "deploy": {
        "keywords": [
            "деплой", "deploy", "сервер", "server", "nginx", "docker",
            "ssl", "certbot", "systemd", "vps", "хостинг", "hosting",
            "домен", "domain", "dns", "порт", "port", "firewall", "ufw",
            "kubernetes", "k8s", "ansible", "terraform", "ci/cd"
        ],
        "patterns": [
            r"(настрой|установи|задеплой|разверни).*(сервер|nginx|docker|ssl|сайт)",
            r"(запусти|перезапусти|останови).*(сервис|процесс|nginx|gunicorn)",
            r"\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b",
        ],
        "weight": 10
    },
    "design": {
        "keywords": [
            "дизайн", "design", "ui", "ux", "макет", "mockup", "wireframe",
            "css", "html", "лендинг", "landing", "баннер", "banner",
            "логотип", "logo", "инфографика", "infographic", "анимаци",
            "вёрстка", "layout", "компонент", "тема", "theme", "цвет", "color"
        ],
        "patterns": [
            r"(сделай|создай|нарисуй).*(дизайн|макет|лендинг|баннер|логотип|сайт)",
            r"(красив|стильн|современн).*(сайт|страниц|интерфейс)",
        ],
        "weight": 8
    },
    "code": {
        "keywords": [
            "код", "code", "функци", "function", "класс", "class",
            "python", "javascript", "typescript", "react", "vue",
            "api", "endpoint", "backend", "frontend", "скрипт", "script",
            "алгоритм", "algorithm", "рефактор", "refactor", "баг", "bug",
            "ошибк", "error", "fix", "исправь", "напиши"
        ],
        "patterns": [
            r"(напиши|создай|разработай).*(код|функци|класс|api|скрипт|модуль)",
            r"(исправь|fix|debug).*(баг|ошибк|bug|error|проблем)",
            r"(рефактор|оптимизируй|улучши).*(код|функци|класс)",
        ],
        "weight": 7
    },
    "research": {
        "keywords": [
            "найди", "поищи", "исследуй", "research", "изучи", "расскажи",
            "что такое", "как работает", "объясни", "сравни", "compare",
            "конкурент", "competitor", "рынок", "market", "тренд", "trend"
        ],
        "patterns": [
            r"(найди|поищи|исследуй).*(информаци|данные|статьи|материал)",
            r"(расскажи|объясни|опиши).*(как|что|почему|зачем)",
            r"(сравни|compare).*(продукт|сервис|технологи|инструмент)",
        ],
        "weight": 5
    },
    "data": {
        "keywords": [
            "анализ", "analysis", "данные", "data", "статистик", "statistics",
            "график", "chart", "отчёт", "report", "таблиц", "table",
            "csv", "excel", "pandas", "визуализ", "dashboard", "метрик", "kpi"
        ],
        "patterns": [
            r"(проанализируй|обработай).*(данные|файл|таблиц|csv)",
            r"(создай|построй|нарисуй).*(график|диаграмм|отчёт|дашборд)",
        ],
        "weight": 6
    },
    "integrate": {
        "keywords": [
            "интеграци", "integration", "webhook", "вебхук",
            "oauth", "jwt", "stripe", "telegram bot", "slack",
            "bitrix", "amocrm", "crm", "erp", "платёж", "payment",
            "api ключ", "api key", "подключи", "connect"
        ],
        "patterns": [
            r"(подключи|интегрируй|настрой).*(api|webhook|бот|crm|платёж|сервис)",
            r"(отправ|получ).*(webhook|api|запрос|уведомлени)",
        ],
        "weight": 8
    },
    "test": {
        "keywords": [
            "тест", "test", "qa", "проверь", "check", "протестируй",
            "e2e", "selenium", "playwright", "нагрузк", "load test",
            "безопасност", "security", "уязвимост", "vulnerability"
        ],
        "patterns": [
            r"(протестируй|проверь|проведи тест).*(сайт|api|приложение|сервис|функционал)",
            r"(найди|проверь).*(баг|ошибк|уязвимост|проблем)",
        ],
        "weight": 7
    },
    "file": {
        "keywords": [
            "файл", "file", "документ", "document", "pdf", "docx", "xlsx",
            "загрузи", "upload", "скачай", "download", "прочитай", "read",
            "конвертируй", "convert", "архив", "archive", "zip"
        ],
        "patterns": [
            r"(создай|сгенерируй|сохрани).*(файл|документ|pdf|docx|xlsx|csv)",
            r"(прочитай|проанализируй|обработай).*(файл|документ|pdf)",
        ],
        "weight": 5
    },
    "plan": {
        "keywords": [
            "план", "plan", "архитектур", "architecture", "стратеги", "strategy",
            "roadmap", "дорожная карта", "спринт", "sprint", "задач", "task",
            "проект", "project", "структур", "structure", "схем", "diagram"
        ],
        "patterns": [
            r"(составь|создай|разработай).*(план|архитектур|стратеги|roadmap)",
            r"(спланируй|организуй|структурируй).*(проект|работ|задач)",
        ],
        "weight": 6
    },
}


# ══════════════════════════════════════════════════════════════
# PRIMARY MODEL SELECTOR
# ══════════════════════════════════════════════════════════════

def select_primary_model(intent: str, message: str = "") -> str:
    """
    Выбрать основную LLM-модель для задачи.

    Логика:
      design / лендинг / сайт / страница / дизайн / UI / HTML / CSS / вёрстка / макет / баннер
        → gemini
      deploy / деплой / сервер / nginx / docker / SSL / SSH
        → mimo  (hands: SSH, деплой, интеграции)
      code / скрипт / API / бэкенд / парсер / бот / функция
        → mimo  (hands: пишет и деплоит код)
      план / архитектура / стратегия / план / проектирование
        → sonnet
      всё остальное
        → minimax  (brain: думает, анализирует)
    """
    import re as _re
    msg_lower = message.lower()

    DESIGN_KEYWORDS = [
        "лендинг", "сайт", "страница", "дизайн", "ui", "ux",
        "html", "css", "вёрстка", "макет", "баннер", "landing",
        "design", "layout", "wireframe", "mockup", "logo", "логотип",
    ]
    DEPLOY_KEYWORDS = [
        "деплой", "deploy", "сервер", "server", "nginx", "docker",
        "ssl", "ssh", "certbot", "vps", "хостинг", "kubernetes",
        "ansible", "terraform", "ci/cd", "systemd",
    ]
    # Используем точные слова для CODE чтобы избежать подстрок в других словах
    CODE_KEYWORDS_EXACT = [
        "скрипт", "script", "api", "бэкенд", "backend", "парсер",
        "parser", "функци", "function", "алгоритм", "algorithm",
        "endpoint", "рефактор",
    ]
    # Слова требующие word-boundary (бот/bot/код/code могут быть частью других слов)
    CODE_KEYWORDS_BOUNDARY = ["бот", "bot", "код", "code"]
    PLAN_KEYWORDS = [
        "архитектур", "architecture", "стратеги", "strategy",
        "план", "plan", "проектирован", "roadmap", "дорожная карта",
    ]

    def _has_code_kw(text):
        if any(kw in text for kw in CODE_KEYWORDS_EXACT):
            return True
        for kw in CODE_KEYWORDS_BOUNDARY:
            if _re.search(r"\b" + _re.escape(kw) + r"\b", text):
                return True
        return False

    # Порядок важен: design → plan → deploy → code → default
    if intent == "design" or any(kw in msg_lower for kw in DESIGN_KEYWORDS):
        return "gemini"

    if intent == "plan" or any(kw in msg_lower for kw in PLAN_KEYWORDS):
        return "sonnet"

    if intent == "deploy" or any(kw in msg_lower for kw in DEPLOY_KEYWORDS):
        return "mimo"  # PATCH fix: hands for deploy/SSH

    if intent == "code" or _has_code_kw(msg_lower):
        return "mimo"  # PATCH fix: hands for code execution

    return "minimax"  # PATCH fix: minimax as default brain


# ══════════════════════════════════════════════════════════════
# COMPLEXITY LEVELS
# ══════════════════════════════════════════════════════════════

COMPLEXITY_LEVELS = {
    1: "trivial",    # Привет, спасибо, да/нет
    2: "simple",     # Простой вопрос, короткая задача
    3: "medium",     # Средняя задача, несколько шагов
    4: "complex",    # Сложная задача, много компонентов
    5: "expert",     # Экспертная задача, архитектурные решения
}

# ══════════════════════════════════════════════════════════════
# CLARIFICATION TRIGGERS (когда нужно спросить уточнение)
# ══════════════════════════════════════════════════════════════

CLARIFICATION_TRIGGERS = [
    # Неопределённые запросы
    (r"^(сделай|создай|напиши|помоги)\s*$", "Что именно нужно сделать?"),
    (r"^(сайт|приложение|бот|система)\s*$", "Опишите подробнее что нужно создать."),
    # Без указания технологий для сложных задач
    (r"(создай|разработай).*(приложение|система|платформ)", None),  # None = авто-уточнение
    # Без указания сервера для деплоя
    (r"(задеплой|разверни|установи на сервер)", None),
]

# ══════════════════════════════════════════════════════════════
# MAIN FUNCTIONS
# ══════════════════════════════════════════════════════════════

def detect_intent(message: str, history: List[Dict] = None) -> Dict[str, Any]:
    """
    Определить intent запроса.

    Returns:
        {
            "primary": "deploy",
            "secondary": ["code", "test"],
            "scores": {"deploy": 15, "code": 7, ...},
            "confidence": 0.85
        }
    """
    msg_lower = message.lower().strip()
    scores = {}

    for intent_key, rules in INTENT_RULES.items():
        score = 0

        # Keyword matching
        for kw in rules["keywords"]:
            if kw in msg_lower:
                score += 1

        # Pattern matching (higher weight)
        for pattern in rules.get("patterns", []):
            if re.search(pattern, msg_lower):
                score += rules.get("weight", 5)

        if score > 0:
            scores[intent_key] = score

    # Учитываем историю
    if history and len(history) > 0:
        last_intent = history[-1].get("intent", "chat") if isinstance(history[-1], dict) else "chat"
        if last_intent in scores:
            scores[last_intent] = scores.get(last_intent, 0) + 2

    if not scores:
        return {
            "primary": "chat",
            "secondary": [],
            "scores": {"chat": 1},
            "confidence": 0.5
        }

    sorted_intents = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    primary = sorted_intents[0][0]
    primary_score = sorted_intents[0][1]
    total_score = sum(scores.values())
    confidence = min(0.99, primary_score / max(total_score, 1))

    secondary = [k for k, v in sorted_intents[1:3] if v >= primary_score * 0.4]

    return {
        "primary": primary,
        "secondary": secondary,
        "scores": scores,
        "confidence": round(confidence, 2)
    }


def estimate_complexity(message: str, history: List[Dict] = None,
                        intent: str = "chat") -> int:
    """
    Оценить сложность задачи (1-5).
    """
    msg_lower = message.lower()
    word_count = len(message.split())
    score = 2

    # По длине
    if word_count < 5:
        score = max(1, score - 1)
    elif word_count > 30:
        score += 1
    elif word_count > 80:
        score += 2

    # Простые паттерны
    simple_patterns = [
        r"^(привет|hello|hi|hey|здравствуй|добрый)",
        r"^(спасибо|thanks|thank you|благодар)",
        r"^(да|нет|yes|no|ok|ок|хорошо|понял|ясно)$",
        r"^(что такое|расскажи про|объясни)\s+\w+$",
    ]
    for pattern in simple_patterns:
        if re.search(pattern, msg_lower):
            score = max(1, score - 1)
            break

    # Сложные паттерны
    complex_patterns = [
        r"(архитектур|architecture|design pattern|микросервис)",
        r"(полноценн|production|enterprise|масштабируем)",
        r"(с нуля|from scratch|полностью|весь проект|целиком)",
        r"(несколько|multiple|много|various).*(сервис|компонент|модул)",
        r"(интеграци|integration).*(несколько|multiple|много)",
        r"(автоматизируй|автоматизаци).*(весь|полностью|всё)",
    ]
    for pattern in complex_patterns:
        if re.search(pattern, msg_lower):
            score = min(5, max(4, score))
            break

    # По intent
    intent_complexity = {
        "chat": 0, "research": 0, "file": 0,
        "code": 1, "data": 1, "test": 1, "plan": 1,
        "design": 1, "integrate": 2, "deploy": 2,
    }
    score += intent_complexity.get(intent, 0)

    # По истории
    if history and len(history) > 8:
        score = min(5, score + 1)

    return max(1, min(5, score))


def needs_clarification(message: str, intent: str,
                        complexity: int) -> Tuple[bool, Optional[str]]:
    """
    Определить нужно ли уточнение от пользователя.

    Returns:
        (needs_clarification: bool, question: Optional[str])
    """
    msg_lower = message.lower().strip()
    word_count = len(message.split())

    # Слишком короткий запрос для сложного intent
    if word_count < 4 and intent in ("deploy", "integrate", "code", "design"):
        questions = {
            "deploy": "На какой сервер деплоить? Какое приложение? Укажите IP и технологии.",
            "integrate": "Какой сервис интегрировать? Есть ли API ключи?",
            "code": "Что именно написать? На каком языке? Какова цель?",
            "design": "Что именно создать? Для какого проекта? Есть ли референсы?",
        }
        return True, questions.get(intent)

    # Проверяем триггеры
    for pattern, question in CLARIFICATION_TRIGGERS:
        if re.search(pattern, msg_lower):
            if question:
                return True, question
            # Авто-генерация вопроса
            if intent == "deploy" and "сервер" not in msg_lower and not re.search(r"\d+\.\d+", msg_lower):
                return True, "Укажите IP сервера и что именно нужно задеплоить."
            if intent == "code" and word_count < 6:
                return True, "Опишите подробнее что нужно написать: язык, функционал, входные данные."

    return False, None


def clarify(message: str, history: List[Dict] = None,
            orion_mode: str = "fast") -> Dict[str, Any]:
    """
    Главная функция — полный анализ запроса.

    Returns:
        {
            "intent": "deploy",
            "secondary_intents": ["code"],
            "complexity": 4,
            "complexity_label": "complex",
            "needs_clarification": False,
            "clarification_question": None,
            "suggested_agents": ["devops", "developer"],
            "execution_mode": "sequential",  # sequential | parallel
            "confidence": 0.85,
            "orion_mode": "fast",
            "estimated_cost_usd": 0.05,
        }
    """
    from model_router import get_max_cost

    # 1. Detect intent
    intent_result = detect_intent(message, history)
    primary_intent = intent_result["primary"]
    confidence = intent_result["confidence"]

    # 2. Estimate complexity
    complexity = estimate_complexity(message, history, primary_intent)
    complexity_label = COMPLEXITY_LEVELS.get(complexity, "medium")

    # 3. Check clarification
    needs_clarif, clarif_question = needs_clarification(message, primary_intent, complexity)

    # 4. Select agents
    from specialized_agents import select_agents_for_task
    agents = select_agents_for_task(
        message,
        mode=primary_intent,
        max_agents=3 if complexity >= 3 else 1,
        orion_mode=orion_mode
    )
    suggested_agents = [a["key"] for a in agents]

    # 5. Execution mode
    execution_mode = "parallel" if (
        complexity >= 4 and len(suggested_agents) > 1
        and primary_intent in ("deploy", "integrate", "code")
    ) else "sequential"

    # 6. Select primary model
    primary_model = select_primary_model(primary_intent, message)

    # 7. Estimate cost
    cost_per_complexity = {1: 0.001, 2: 0.005, 3: 0.02, 4: 0.08, 5: 0.25}
    estimated_cost = cost_per_complexity.get(complexity, 0.02)
    max_cost = get_max_cost(orion_mode)

    result = {
        "intent": primary_intent,
        "secondary_intents": intent_result.get("secondary", []),
        "intent_scores": intent_result.get("scores", {}),
        "complexity": complexity,
        "complexity_label": complexity_label,
        "needs_clarification": needs_clarif,
        "clarification_question": clarif_question,
        "suggested_agents": suggested_agents,
        "execution_mode": execution_mode,
        "confidence": confidence,
        "orion_mode": orion_mode,
        "estimated_cost_usd": estimated_cost,
        "max_cost_usd": max_cost,
        "within_budget": estimated_cost <= max_cost,
        "primary_model": primary_model,
    }

    logger.debug(f"Intent clarified: intent={primary_intent}, complexity={complexity}, "
                 f"agents={suggested_agents}, mode={orion_mode}")

    return result


def format_clarification_for_user(clarify_result: Dict[str, Any]) -> str:
    """
    Форматировать результат анализа для отображения пользователю
    (используется в UI как подсказка).
    """
    intent = clarify_result.get("intent", "chat")
    complexity = clarify_result.get("complexity", 2)
    agents = clarify_result.get("suggested_agents", [])
    cost = clarify_result.get("estimated_cost_usd", 0)

    intent_labels = {
        "chat": "💬 Общение",
        "code": "💻 Разработка",
        "deploy": "🔧 DevOps",
        "design": "🎨 Дизайн",
        "research": "🔍 Исследование",
        "data": "📊 Анализ данных",
        "file": "📁 Файлы",
        "integrate": "🔌 Интеграция",
        "test": "🧪 Тестирование",
        "plan": "📋 Планирование",
    }

    complexity_labels = {
        1: "⚡ Быстро",
        2: "🟢 Просто",
        3: "🟡 Средне",
        4: "🟠 Сложно",
        5: "🔴 Экспертно",
    }

    agent_emojis = {
        "designer": "🎨", "developer": "💻", "devops": "🔧",
        "tester": "🧪", "analyst": "📊", "integrator": "🔌"
    }

    agents_str = " ".join([f"{agent_emojis.get(a, '🤖')}{a}" for a in agents])

    lines = [
        f"{intent_labels.get(intent, '🤖 Задача')} · {complexity_labels.get(complexity, '🟡')}",
    ]
    if agents:
        lines.append(f"Агенты: {agents_str}")
    if cost > 0.001:
        lines.append(f"~${cost:.3f}")

    return " | ".join(lines)
