"""
ORION Digital — Agent Routes Blueprint
"""
from flask import Blueprint, request, jsonify, Response, stream_with_context
import json
import uuid
import re
import time
import os
import logging
import threading
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

# Import shared state and helpers
from shared import (
    app, db_read, db_write, require_auth, require_admin,
    _now_iso, _calc_cost, _get_memory, _get_versions, _get_rate_limiter,
    _encrypt_setting, _decrypt_setting, _SECRET_SETTINGS_KEYS,
    _running_tasks, _tasks_lock, _interrupt_lock, _active_agents, _agents_lock,
    OPENROUTER_API_KEY, OPENROUTER_BASE_URL, DATA_DIR, UPLOAD_DIR,
    _lock, _USE_SQLITE,
    CHAT_MODELS, MODEL_CONFIGS,
    _message_queue, _paused_tasks,
)

from agent_loop import AgentLoop, MultiAgentLoop, _iter_lines_with_timeout
from ssh_executor import SSHExecutor, ssh_pool
from browser_agent import BrowserAgent
from shared import _classify_interrupt_message, _cleanup_running_task
from amendment_extractor import get_amendment_extractor
import requests as http_requests
import copy
import secrets

try:
    from orchestrator_v2 import (
        Orchestrator, get_agent_prompt, get_model_for_agent as orch_get_model,
        get_model_id, format_plan_sse, AGENT_PROMPTS, MODEL_MAP
    )
    _ORCHESTRATOR_AVAILABLE = True
except ImportError:
    _ORCHESTRATOR_AVAILABLE = False

try:
    from parallel_agents import ParallelAgentOrchestrator
except ImportError:
    ParallelAgentOrchestrator = None

try:
    from project_memory import ProjectMemory
except ImportError:
    ProjectMemory = None

from model_router import select_model, classify_complexity, log_cost, get_fallback_model
from specialized_agents import SPECIALIZED_AGENTS, select_agents_for_task, get_agent_pipeline, get_all_agents

agent_bp = Blueprint("agent", __name__)


def _parse_ssh_from_message(message):
    """
    Parse SSH credentials from user message text.
    Supports formats:
      - root@192.168.1.1 mypassword ...
      - user@hostname password ...
      - root@10.0.0.1 P@ssw0rd! сходи посмотри ...
    Returns dict with host, username, password or None.
    """
    if not message:
        return None

    # Pattern: user@host password
    # IP: digits and dots, or hostname
    # Password: non-space string (can contain special chars)
    m = re.match(
        r'^\s*([a-zA-Z0-9_.-]+)@([a-zA-Z0-9._-]+)\s+(\S+)\s*(.*)',
        message
    )
    if m:
        username = m.group(1)
        host = m.group(2)
        password = m.group(3)
        # Validate host looks like IP or hostname
        if re.match(r'^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$', host) or '.' in host:
            return {
                "host": host,
                "username": username,
                "password": password
            }

    # Pattern: just IP password (assume root)
    m = re.match(
        r'^\s*(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})\s+(\S+)\s*(.*)',
        message
    )
    if m:
        host = m.group(1)
        password = m.group(2)
        return {
            "host": host,
            "username": "root",
            "password": password
        }

    # Pattern: natural language with IP, username, password anywhere in text
    # e.g. "подключись к серверу 1.2.3.4 root пароль123"
    # e.g. "сходи на сервер 10.0.0.1 логин root пароль mypass"
    ip_match = re.search(r'(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})', message)
    if ip_match:
        host = ip_match.group(1)
        rest = message[ip_match.end():].strip()
        # Try: IP username password
        m2 = re.match(r'^\s*(\S+)\s+(\S+)', rest)
        if m2:
            word1 = m2.group(1)
            word2 = m2.group(2)
            # If word1 looks like a username (root, admin, user, etc.)
            if re.match(r'^[a-zA-Z][a-zA-Z0-9_.-]*$', word1) and len(word1) < 32:
                return {"host": host, "username": word1, "password": word2}
            else:
                # word1 is password, assume root
                return {"host": host, "username": "root", "password": word1}
        elif rest:
            # Just one word after IP — treat as password
            word = rest.split()[0]
            # Skip path-like tokens (путь, /, etc.)
            if not word.startswith('/') and word.lower() not in ('путь', 'path', 'в', 'на', 'по', 'dir'):
                return {"host": host, "username": "root", "password": word}

    # SSH_HOST_ONLY: if IP found anywhere in message but no password, return host for memory fallback
    _ip_anywhere = re.search(r'(\\d{1,3}\\.\\d{1,3}\\.\\d{1,3}\\.\\d{1,3})', message)
    if _ip_anywhere:
        return {"host": _ip_anywhere.group(1), "username": "root", "password": None}
    return None


# ██ LLM ORCHESTRATOR — Intent Detection via AI (not keywords) ██
# ══════════════════════════════════════════════════════════════════

ORCHESTRATOR_PROMPT = """Ты — умный маршрутизатор задач для AI-ассистента. Твоя работа: понять что хочет пользователь и выбрать правильный режим обработки.
ДОСТУПНЫЕ РЕЖИМЫ:
- "chat" — обычный разговор, вопросы, объяснения, советы, идеи, написание кода, конфигов, скриптов, шаблонов
- "file" — создание документов для скачивания: Word (.docx), PDF, Excel (.xlsx), PowerPoint (.pptx), CSV
- "deploy" — реальные действия на серверах: SSH подключение, деплой, установка ПО, настройка сервисов, бэкапы
- "research" — поиск актуальной информации в интернете, текущие цены/курсы/новости, парсинг сайтов, любые данные которые меняются со временем
- "data" — анализ данных, математические расчёты, построение графиков и диаграмм из данных
ПРАВИЛА ВЫБОРА РЕЖИМА (применяй по порядку, первое совпавшее правило побеждает):
1. Если в сообщении есть IP-адрес (например 1.2.3.4) → "deploy"
2. Если есть слово "сервер/VPS/прод/боевой/сервак/серваке" + действие → "deploy"
3. Если запрос заканчивается созданием файла (Word/PDF/Excel/PowerPoint/таблицу/отчёт в файле) → "file", даже если в начале есть "найди/поищи/проверь/проанализируй"
4. Если просят создать бизнес-документ для скачивания (договор, счёт, резюме, отчёт, презентация, инструкция, ТЗ, КП) → "file"
5. Если запрос касается ЛЮБОЙ информации которая меняется со временем или требует актуальных данных из интернета → "research". Это включает:
   - Курсы криптовалют: биткоин, ethereum, BTC, ETH, любые монеты
   - Курсы валют: доллар, евро, рубль, юань, любые валюты
   - Цены на товары, услуги, акции, нефть, золото
   - Погода сейчас или прогноз
   - Новости, события, что происходит
   - Информация о компаниях, людях, организациях из интернета
   - Расписания, время работы, адреса, контакты
   - Рейтинги, отзывы, топ-листы
   - Любые вопросы начинающиеся с "сколько сейчас", "какой сейчас", "что сейчас"
6. Если просят посчитать, построить график/диаграмму ИЗ ДАННЫХ (чисел, файла CSV/Excel) → "data"
7. Всё остальное → "chat"
ВАЖНО — НЕ ПУТАЙ:
- "как задеплоить" / "как установить" / "как настроить" → "chat" (вопрос-инструкция, не действие)
- "задеплой" / "установи" / "настрой" + сервер/VPS/прод → "deploy" (команда к действию)
- Одиночные слова без объекта: "установи", "обнови", "удали", "запусти", "накидай" → "chat" (нет объекта/сервера)
- Команды БЕЗ указания сервера: "установи docker", "установи nginx", "установи node js", "перезапусти nginx", "задеплой приложение", "задеплой сайт", "запусти сервер", "сделай бэкап базы", "настрой ssl", "задеплой приложение" → "chat" (нет сервера — уточнить)
- "создай шаблон" / "напиши шаблон" / "придумай идею" / "накидай варианты" → "chat"
- "создай Word документ" / "сделай PDF" / "напиши резюме" → "file"
- "напиши объявление" / "напиши пост" / "напиши текст" → "chat" (текст в чате, не файл)
- "создай swagger документацию" / "напиши README" / "напиши документацию" → "chat" (текст в чате)
- "напиши инструкцию" → "chat" (текст), "создай PDF инструкцию" / "сделай Word инструкцию" → "file"
- "настрой X" / "обнови X" БЕЗ слова сервер/VPS/прод → "chat" (инструкция, не действие)
- "настрой X на сервере/VPS/проде" → "deploy" (реальное действие)
- "нужно настроить X" / "хочу настроить X" / "помоги настроить X" БЕЗ слова сервер/VPS/прод → "deploy" (пользователь намерен настраивать)
- "нужно задеплоить" / "хочу задеплоить" / "помоги с деплоем" → "deploy" (намерение деплоить)
- "нужно установить X" / "хочу установить X" → "deploy" (намерение установить)
- "нужно создать базу данных" / "создай базу данных" / "сделай базу данных" / "создай таблицу в postgresql" → "deploy" (действие в БД)
- "запили X" (сленг) → "deploy" если X — серверное ПО (докер, nginx, сервис), "chat" если X — код/функция
- "настрой вебхук" / "настрой webhook" → "deploy" (настройка на сервере)
- "настрой https" / "настрой certbot" → "deploy" (настройка SSL на сервере)
- "настрой github actions" / "настрой gitlab ci" → "deploy" (настройка CI/CD)
- "настрой порт X" → "deploy" (настройка порта на сервере)
- "настрой grafana" / "установи prometheus" → "deploy" (установка мониторинга)
- "найди информацию и сделай PDF/Word/Excel" → "file" (конечный результат важнее)
- "найди X и установи на сервер" → "deploy" (конечное действие — деплой)
- "объясни X и задеплой Y" → "deploy" (конечное действие — деплой)
- "создай excel и отправь на сервер" → "deploy" (конечное действие — деплой)
- "поищи хостинг и зарегистрируй домен" → "deploy" (конечное действие — регистрация)
- "открой сайт и сделай скриншот" → "research" (браузер/парсинг)
- "сколько стоит X" / "какая цена X" / "цены на X" → "research" (нужны актуальные данные)
- "какой курс биткоина" / "курс доллара" / "цена эфира" / "btc сейчас" → "research" (актуальные данные)
- "биткоин" / "bitcoin" / "ethereum" / "крипта" / "btc" / "eth" в любом контексте вопроса → "research"
- "погода" / "прогноз погоды" / "температура" → "research" (актуальные данные)
- "новости" / "что нового" / "что происходит" / "последние события" → "research"
- "какой сейчас" / "что сейчас" / "сколько сейчас" → "research" (актуальные данные)
- "найди решение задачи" / "найди ошибку" / "найди способ" → "chat" (поиск в знаниях, не в интернете)
- "найди альтернативы X" → "chat" (поиск в знаниях, не в интернете)
- "сравни X и Y" → "chat" (сравнение из знаний, не поиск в интернете)
- "сделай диаграмму" / "построй график" БЕЗ данных → "chat", С данными/файлом → "data"
- "построй график продаж" / "построй график X" → "data" (визуализация данных)
- "проанализируй логи" → "deploy" (логи на сервере), "проанализируй данные из файла" → "data"
- "проанализируй конкурентов" → "research" (поиск информации в интернете)
- "проанализируй трафик сайта" → "research" (нужны данные из интернета)
- "проверь статус сервисов" / "проверь статус сервиса" → "deploy" (проверка на сервере)
- "сколько места на диске" / "проверь использование памяти" / "покажи запущенные процессы" → "deploy" (проверка сервера)
- "проверь статус сервиса aws" → "research" (проверка статуса онлайн)
- "автоматизируй парсинг" / "напиши парсер" → "chat" (написание кода)
- "автоматизируй отправку отчётов" → "chat" (написание скрипта/кода)
- "протестируй API" → "deploy" (тест на сервере), "напиши тесты" → "chat" (написание кода)
- "создай n8n workflow" (без сервера) → "chat", "установи n8n на сервер" / "установи n8n" / "запусти n8n" → "deploy"
- "установи n8n" / "запусти n8n" / "установи airflow" / "установи jupyter" → "deploy" (установка ПО)
- Короткие ответы: "окей", "понял", "продолжай", "допиши", "объясни по-простому", "привет", "спасибо" → "chat"
- "нарисуй диаграмму/схему" → "chat", "нарисуй баннер/логотип" → "chat" (медиа-генерация)
- "создай .env файл" / "создай requirements.txt" → "chat" (конфиг = текст в чате)
- "интегрируй stripe" / "подключи telegram api" / "создай webhook" → "chat" (написание кода для интеграции)
- "создай ci/cd pipeline" / "создай github actions workflow" / "напиши github actions workflow" → "chat" (написание конфига)
- "создай локальный сервер" / "сделай сайт" / "сделай приложение" / "сделай бота" / "сделай апи" → "chat" (написание кода)
- "запили функцию на питоне" / "запили код" → "chat" (написание кода)
- "покажи в таблице разницу" / "сравни в таблице" → "chat" (ответ в чате)
- "создай таблицу" / "сделай таблицу" БЕЗ уточнения данных → "file" (таблица = документ)
- "сделай таблицу сравнения тарифов" / "сделай таблицу с расписанием" / "сделай таблицу продаж" → "file" (таблица = документ)
- "напиши коммерческое предложение" / "напиши бизнес-план" / "напиши техническое задание" → "file" (бизнес-документ)
Отвечай ТОЛЬКО JSON: {{"mode": "chat|file|deploy|research|data", "confidence": 0.0-1.0}}
Последние сообщения чата (контекст):
{history}
Сообщение пользователя: {message}
Ответь СТРОГО в формате JSON (только JSON, без пояснений):
{{"mode": "chat", "reason": "краткое объяснение на русском", "confidence": 0.95}}"""



def detect_intent_llm(user_message: str, history: list, api_key: str) -> dict:
    """
    Использует LLM для определения намерения пользователя.
    Возвращает dict: {mode, reason, confidence}
    Режимы: chat | file | deploy | research | data
    """
    # Быстрый pre-check: если есть IP-адрес — точно deploy (без вызова LLM)
    if re.search(r'\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b', user_message):
        return {"mode": "deploy", "reason": "IP-адрес в сообщении", "confidence": 1.0}

    # Pre-check: URL + слова лендинг/сайт/создай → file (запускает lite_agent)
    _msg_lower_pre = user_message.lower()
    _has_url_pre = bool(re.search(r'https?://\S+', user_message))
    _landing_kw = ["лендинг", "landing", "сайт", "создай", "сделай", "сгенерируй", "напиши", "скопируй", "сделай сайт", "сделай лендинг"]
    if _has_url_pre and any(kw in _msg_lower_pre for kw in _landing_kw):
        return {"mode": "file", "reason": "URL + лендинг/сайт/создай → lite_agent", "confidence": 0.95}

    # Формируем контекст из последних 3 сообщений
    recent = history[-3:] if history else []
    history_text = "\n".join([
        f"{m['role']}: {m['content'][:120]}"
        for m in recent
    ]) or "нет истории"

    prompt = ORCHESTRATOR_PROMPT.replace("{message}", user_message[:600]).replace("{history}", history_text)

    try:
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://orion.mksitdev.ru",
            "X-Title": "ORION Digital Orchestrator"
        }
        payload = {
            "model": "meta-llama/llama-3.1-70b-instruct",  # Оркестратор: 100% точность, быстрый
            "messages": [
                {"role": "user", "content": prompt}
            ],
            "temperature": 0.1,
            "max_tokens": 80,
        }
        resp = http_requests.post(
            OPENROUTER_BASE_URL, headers=headers, json=payload, timeout=8
        )
        if resp.status_code == 200:
            data = resp.json()
            content = data["choices"][0]["message"]["content"].strip()
            # Извлекаем JSON даже если модель добавила лишний текст
            json_match = re.search(r'\{[^}]+\}', content, re.DOTALL)
            if json_match:
                result = json.loads(json_match.group())
                mode = result.get("mode", "chat")
                if mode not in ("chat", "file", "deploy", "research", "data"):
                    mode = "chat"
                return {
                    "mode": mode,
                    "reason": result.get("reason", ""),
                    "confidence": float(result.get("confidence", 0.8))
                }
    except Exception:
        # Если LLM недоступен — fallback на keyword matching
        pass

    # ── Fallback: keyword matching (если LLM не ответил) ──
    msg_lower = user_message.lower()
    deploy_kw = ["ssh", "apt ", "apt-get", "pip install", "npm install", "docker", "nginx", "systemd", "деплой", "deploy", "разверни на", "установи на сервер"]
    file_kw = ["word", "docx", ".pdf", " pdf", "pdf ", "pdf-", "сделай pdf", "создай pdf", "excel", "xlsx", "powerpoint", "pptx",
                "скачать файл", "создай файл", "сгенерируй файл",
                "сделай документ", "создай документ", "сделай таблицу", "создай таблицу",
                "сделай отчёт", "создай отчёт", "сделай презентацию", "создай презентацию",
                "картинк", "изображен", "баннер", "постер", "иллюстрац",
                "нарисуй", "сделай лого", "создай лого", "сделай иконк", "создай иконк",
                "сделай фото", "создай фото", "generate image", "create image",
                "напиши парсер", "напиши скрипт", "напиши код", "напиши бот",
                "напиши программ", "создай скрипт", "создай api", "напиши функци"]
    research_kw = [
        # Явные команды поиска
        "найди в интернете", "поищи", "web search", "проверь сайт", "открой сайт",
        "посмотри в интернете", "загугли", "найди актуальн", "найди информацию",
        # Криптовалюты
        "биткоин", "bitcoin", "btc", "ethereum", "eth", "solana", "sol",
        "крипто", "crypto", "крипта", "usdt", "usdc", "bnb", "xrp",
        # Валюты и финансы
        "доллар", "евро", "рубль", "юань", "фунт", "иена",
        "акции", "котировки", "нефть", "золото", "серебро",
        # Цены
        "курс ", "цена ", "стоимость ", "сколько стоит",
        "текущий курс", "актуальный курс", "сегодня курс", "цена сейчас",
        "какой курс", "какая цена", "сколько сейчас", "что сейчас с",
        "сравни цены",
        # Погода
        "погода", "прогноз", "температура", "осадки", "ветер",
        # Новости и события
        "новости", "последние новости", "что происходит", "что нового",
        "последние события", "текущие события",
        # Актуальные вопросы
        "узнай", "проверь",
        # Контакты и расписания
        "расписание", "время работы", "адрес", "телефон", "контакты",
        # Рейтинги и отзывы
        "отзывы", "рейтинг", "топ ", "лучшие",
    ]
    data_kw = ["посчитай", "вычисли", "построй график", "анализ данных", "статистика"]
    if any(kw in msg_lower for kw in deploy_kw):
        return {"mode": "deploy", "reason": "fallback keyword", "confidence": 0.7}
    if any(kw in msg_lower for kw in file_kw):
        return {"mode": "file", "reason": "fallback keyword", "confidence": 0.7}
    if any(kw in msg_lower for kw in research_kw):
        return {"mode": "research", "reason": "fallback keyword", "confidence": 0.7}
    if any(kw in msg_lower for kw in data_kw):
        return {"mode": "data", "reason": "fallback keyword", "confidence": 0.7}
    return {"mode": "chat", "reason": "fallback default", "confidence": 0.6}



# ══════════════════════════════════════════════════════════════════
# ██ AGENT LOOP — CORE: AI plans, executes, verifies autonomously ██
# ══════════════════════════════════════════════════════════════════


def _process_message_queue(chat_id: str, user_id: str):
    """Called after a task finishes. Processes next queued message if any."""
    with _interrupt_lock:
        queue = _message_queue.get(chat_id, [])
        if not queue:
            # Also check if there's a paused task to resume
            paused = _paused_tasks.pop(chat_id, None)
            if paused:
                logging.info(f"[PATCH14] Resuming paused task for chat {chat_id}: {paused.get('task', '')[:60]}")
                # Inject resume message into queue
                _message_queue[chat_id] = [{
                    "message": f"Продолжи прерванную задачу: {paused.get('task', '')}",
                    "mode": paused.get("mode", "fast"),
                    "user_id": user_id,
                    "file_content": ""
                }]
                queue = _message_queue[chat_id]
            else:
                return
        next_msg = queue.pop(0)
        if not queue:
            _message_queue.pop(chat_id, None)

    logging.info(f"[PATCH14] Processing queued message for chat {chat_id}: {next_msg.get('message', '')[:60]}")
    try:
        import requests as _req
        _req.post(
            f"http://127.0.0.1:{os.environ.get('PORT', 3510)}/api/chat",
            json={
                "chat_id": chat_id,
                "message": next_msg["message"],
                "mode": next_msg.get("mode", "fast"),
                "file_content": next_msg.get("file_content", ""),
            },
            headers={"X-Internal-Queue": "1", "X-User-Id": next_msg.get("user_id", user_id)},
            timeout=5
        )
    except Exception as _qe:
        logging.warning(f"[PATCH14] Queue processing failed: {_qe}")


# ── Stop Agent ──────────────────────────────────────────────

@agent_bp.route("/api/chats/<chat_id>/send", methods=["POST"])
@require_auth
def send_message(chat_id):
    "Send message and get AI response via SSE streaming with agent loop."
    # Rate limiting check
    rl = _get_rate_limiter()
    allowed, rl_info = rl.check_message(request.user_id)
    if not allowed:
        return jsonify({
            "error": "Rate limit exceeded",
            "retry_after": rl_info.get("retry_after", 60),
            "remaining": 0
        }), 429

    db = db_read()
    chat = db["chats"].get(chat_id)
    if not chat:
        return jsonify({"error": "Chat not found"}), 404
    if chat.get("user_id") != request.user_id and request.user.get("role") != "admin":
        return jsonify({"error": "Access denied"}), 403

    # ── Spending limit check ──
    _user_data = db["users"].get(request.user_id, {})
    _monthly_limit = _user_data.get("monthly_limit", 999999)
    _total_spent = _user_data.get("total_spent", 0.0)
    if _monthly_limit and _monthly_limit < 999999 and _total_spent >= _monthly_limit:
        _spent_rub = round(_total_spent * 105, 2)
        _limit_rub = round(_monthly_limit * 105, 2)
        return jsonify({
            "error": "spending_limit_exceeded",
            "message": f"Лимит исчерпан. Вы потратили ₽{_spent_rub} из ₽{_limit_rub} доступных. Обратитесь к администратору для пополнения баланса.",
            "spent": _total_spent,
            "limit": _monthly_limit,
            "spent_rub": _spent_rub,
            "limit_rub": _limit_rub
        }), 402

    data = request.get_json() or {}
    user_message = data.get("message", "").strip()
    file_content = data.get("file_content", "")
    # ── BUG-1 FIX: Extract and normalize orion_mode ──
    # FIX: Load mode from chat if not in send payload
    _raw_mode = data.get("mode") or (chat.get("orion_mode") if chat else None) or "turbo-basic"
    _MODE_NORMALIZE = {
        "turbo-basic": "fast", "turbo_basic": "fast", "fast": "fast",
        "turbo-premium": "fast", "fast": "fast",
        "pro-basic": "standard", "pro_basic": "standard", "standard": "standard",
        "pro-premium": "premium", "premium": "premium",
        "premium": "premium",
        "standard": "standard",
        "fast": "fast", "standard": "standard", "premium": "premium",
    }
    orion_mode = _MODE_NORMALIZE.get(_raw_mode, "fast")
    
    # ══ PATCH 14 FIX: Interrupt / Queue / Append for send_message route ══
    with _tasks_lock:
        _existing_task = _running_tasks.get(chat_id)
        _task_is_running = _existing_task and _existing_task.get("status") == "running"
    if _task_is_running:
        _msg_type = _classify_interrupt_message(user_message)
        # ── TASK 9: Detect amendments in interrupt messages ──
        try:
            _amend_ext = get_amendment_extractor()
            _amend_result = _amend_ext.classify(user_message)
            if _amend_result.get("type") == "amendment":
                logging.info(f"[AMENDMENT] Detected in interrupt: {_amend_result.get('amendment', {}).get('summary', '')[:100]}")
        except Exception as _amend_err:
            logging.debug(f"[AMENDMENT] Detection error: {_amend_err}")

        if _msg_type == "queue":
            with _interrupt_lock:
                if chat_id not in _message_queue:
                    _message_queue[chat_id] = []
                _message_queue[chat_id].append({
                    "message": user_message, "mode": orion_mode,
                    "user_id": request.user_id, "file_content": file_content
                })
            logging.info(f"[PATCH14-SEND] chat={chat_id} → QUEUED: {user_message[:60]}")
            return Response(
                f"data: {json.dumps({'type': 'queued', 'text': '🕐 В очереди — возьму после текущей задачи'})}\n\n"
                f"data: {json.dumps({'type': 'done'})}\n\n",
                mimetype="text/event-stream",
                headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
            )
        elif _msg_type == "append":
            with _tasks_lock:
                task_entry = _running_tasks.get(chat_id, {})
                if "_append_msgs" not in task_entry:
                    task_entry["_append_msgs"] = []
                task_entry["_append_msgs"].append(user_message)
            logging.info(f"[PATCH14-SEND] chat={chat_id} → APPENDED: {user_message[:60]}")
            return Response(
                f"data: {json.dumps({'type': 'appended', 'text': '📩 Добавлено к текущей задаче'})}\n\n"
                f"data: {json.dumps({'type': 'done'})}\n\n",
                mimetype="text/event-stream",
                headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
            )
        else:  # interrupt
            with _tasks_lock:
                if _existing_task:
                    _existing_task["_interrupt_requested"] = True
                    _existing_task["_interrupt_msg"] = user_message
            logging.info(f"[PATCH14-SEND] chat={chat_id} → INTERRUPT: {user_message[:60]}")
            # Fall through to normal processing — will start new task
    # ═══ АВТОРЕЖИМ: определяем модель по сложности сообщения ═══
    _auto_resolved_mode = None
    if orion_mode == "auto":
        _msg_lower = user_message.lower()
        _msg_len = len(user_message)
        # Opus keywords — очень сложные задачи
        _opus_kw = ["архитектур", "аудит", "спроектируй", "crm с нуля", "erp", 
                     "микросервис", "рефакторинг всего", "code review всего проекта",
                     "проанализируй весь код", "спроектируй систему"]
        # Sonnet keywords — сложные задачи с деплоем/сайтами
        _sonnet_kw = ["сделай сайт", "создай сайт", "лендинг", "деплой", "deploy",
                      "сервер", "ssh", "ftp", "nginx", "docker", "создай приложение",
                      "сделай приложение", "разверни", "настрой ssl", "certbot",
                      "создай api", "rest api", "fullstack", "бэкенд", "backend",
                      "dns", "домен", "хостинг", "beget", "vps", "сайт-визитк",
                      "интернет-магазин", "портал", "дашборд", "dashboard"]
        if any(kw in _msg_lower for kw in _opus_kw):
            orion_mode = "premium"
            _auto_resolved_mode = "premium"
            logging.info(f"[AUTO MODE] → architect (Opus keywords detected)")
        elif any(kw in _msg_lower for kw in _sonnet_kw) or _msg_len > 200:
            orion_mode = "standard"
            _auto_resolved_mode = "standard"
            logging.info(f"[AUTO MODE] → standard (Sonnet keywords or long message)")
        else:
            orion_mode = "fast"
            _auto_resolved_mode = "fast"
            logging.info(f"[AUTO MODE] → fast (simple message)")
    logging.info(f"[send_message] orion_mode={orion_mode} (raw={_raw_mode})")

    if not user_message and not file_content:
        return jsonify({"error": "Message required"}), 400

    # Get user settings
    user_settings = db["users"].get(request.user_id, {}).get("settings", {})
    variant = orion_mode  # FIX: orion_mode is single source of truth
    enhanced = user_settings.get("enhanced_mode", False)
    self_check_level = user_settings.get("self_check_level", "none")  # none | light | medium | deep
    chat_model = user_settings.get("chat_model", "qwen3")

    # Multi-SSH: поддержка нескольких серверов
    # Фронтенд отправляет активный сервер в data.ssh или берём из settings
    _ssh_from_request = data.get("ssh", {})
    ssh_credentials = {
        "host": _ssh_from_request.get("ssh_host") or user_settings.get("ssh_host", ""),
        "username": _ssh_from_request.get("ssh_user") or user_settings.get("ssh_user", "root"),
        "password": _ssh_from_request.get("ssh_password") or _decrypt_setting(user_settings.get("ssh_password", "")),
        "port": int(_ssh_from_request.get("ssh_port") or user_settings.get("ssh_port", 22)),
    }
    logger.info(f"[SSH_CRED_DEBUG] host={ssh_credentials.get('host','?')} pwd_len={len(ssh_credentials.get('password',''))} pwd_repr={repr(ssh_credentials.get('password',''))}")

    # ── Parse SSH credentials from message text ──
    # Formats: "root@IP password ...", "user@IP password ...", "IP password ..."
    ssh_from_msg = _parse_ssh_from_message(user_message)
    if ssh_from_msg:
        # Merge: message SSH overrides settings SSH
        if ssh_from_msg.get("host"):
            ssh_credentials["host"] = ssh_from_msg["host"]
        if ssh_from_msg.get("username"):
            ssh_credentials["username"] = ssh_from_msg["username"]
        if ssh_from_msg.get("password"):
            ssh_credentials["password"] = ssh_from_msg["password"]


    # ── SSH MEMORY FALLBACK: if host found but password missing, check user memory ──
    # BUG FIX: handles "Создай лендинг... Сервер: 45.67.57.175 путь: /var/www/"
    # where IP is in the message but password was given in a previous chat
    if ssh_credentials.get("host") and not ssh_credentials.get("password"):
        try:
            from memory import get_user_profile as _get_mem_profile
            _mem_profile = _get_mem_profile(request.user_id)
            _mem_prefs = _mem_profile.get("prefs", {}) if _mem_profile else {}
            _mem_facts = _mem_profile.get("facts", []) if _mem_profile else []
            # Check prefs for stored SSH password
            _mem_ssh_pass = (_mem_prefs.get("ssh_password") or
                             _mem_prefs.get("server_password") or
                             _mem_prefs.get("ssh_pass"))
            _mem_ssh_user = (_mem_prefs.get("ssh_user") or
                             _mem_prefs.get("server_user") or
                             _mem_prefs.get("ssh_username"))
            if _mem_ssh_pass:
                ssh_credentials["password"] = _mem_ssh_pass
                if _mem_ssh_user and not ssh_credentials.get("username"):
                    ssh_credentials["username"] = _mem_ssh_user
                logging.info(f"[SSH_MEMORY_FALLBACK] Restored SSH password from user memory prefs")
            else:
                # Search facts for SSH password patterns like "пароль: X" or "password: X"
                for _fact in _mem_facts:
                    _pw_m = re.search(r'(?:пароль|password|passwd)[:\s]+([\S]+)', _fact, re.IGNORECASE)
                    if _pw_m:
                        ssh_credentials["password"] = _pw_m.group(1)
                        logging.info(f"[SSH_MEMORY_FALLBACK] Restored SSH password from user memory facts")
                        break
        except Exception as _mem_err:
            logging.debug(f"[SSH_MEMORY_FALLBACK] Could not load memory: {_mem_err}")
    # Save user message
    now = datetime.now(timezone.utc).isoformat()
    user_msg = {
        "id": str(uuid.uuid4())[:8],
        "role": "user",
        "content": user_message,
        "timestamp": now,
        "file_content": file_content[:500] if file_content else None
    }
    chat["messages"].append(user_msg)
    chat["updated_at"] = now

    # Auto-title from first message — generate smart title via LLM (using orchestrator model)
    if len(chat["messages"]) == 1 and chat["title"] == "Новый чат":
        try:
            _title_config = MODEL_CONFIGS.get(orion_mode, MODEL_CONFIGS.get("standard", list(MODEL_CONFIGS.values())[0]))  # FIX: use orion_mode
            _title_model = _title_config["tools"]["model"]  # Используем модель оркестратора (DeepSeek V3.2)
            _title_resp = http_requests.post(
                OPENROUTER_BASE_URL,
                headers={"Authorization": f"Bearer {OPENROUTER_API_KEY}", "Content-Type": "application/json"},
                json={
                    "model": _title_model,
                    "max_tokens": 20,
                    "temperature": 0.3,
                    "messages": [
                        {"role": "system", "content": "Generate a short chat title (3-6 words, no quotes, no punctuation at end) that captures the essence of the user's request. Reply with ONLY the title, nothing else."},
                        {"role": "user", "content": user_message[:500]}
                    ]
                },
                timeout=5
            )
            _title_data = _title_resp.json()
            _generated_title = _title_data.get("choices", [{}])[0].get("message", {}).get("content", "").strip()
            # Clean up: remove quotes, trim
            _generated_title = _generated_title.strip('"\' ').rstrip('.')
            if _generated_title and 3 <= len(_generated_title) <= 80:
                chat["title"] = _generated_title
            else:
                raise ValueError("bad title")
        except Exception:
            # Fallback: first 50 chars
            chat["title"] = user_message[:50] + ("..." if len(user_message) > 50 else "")

    db["chats"][chat_id] = chat
    db_write(db)

    # Determine which model to use
    config = MODEL_CONFIGS.get(orion_mode, MODEL_CONFIGS.get("standard", list(MODEL_CONFIGS.values())[0]))  # FIX: use orion_mode
    model = config["coding"]["model"]
    model_name = config["coding"]["name"]
    # Separate model for Agent Mode (must support OpenAI tool calling)
    agent_model = config["tools"]["model"]
    agent_model_name = config["tools"]["name"]

    # ── PATCH 4: Single model selection path via model_router ──
    # Model is selected ONLY by orion_mode via model_router, no keyword overrides
    _TURBO_MODES = ("fast", "fast", "standard")
    try:
        from model_router import MODELS as _MR_MODELS
        _mode_to_model = {
            # FIX: no duplicate keys - each mode maps to exactly one model
            "fast":     (_MR_MODELS.get("gpt54_mini", {}).get("id", "openai/gpt-4o-mini"), _MR_MODELS.get("gpt54_mini", {}).get("name", "GPT-5.4 Mini")),
            "standard": (_MR_MODELS.get("gpt54", {}).get("id", "openai/gpt-4o"),           _MR_MODELS.get("gpt54", {}).get("name", "GPT-5.4")),
            "premium":  (_MR_MODELS.get("gpt54", {}).get("id", "openai/gpt-5.4"),  _MR_MODELS.get("gpt54", {}).get("name", "GPT-5.4")),  # PATCHED: was opus, now gpt54
        }
        if orion_mode in _mode_to_model:
            agent_model, agent_model_name = _mode_to_model[orion_mode]
            logging.info(f"[MODEL_ROUTER] orion_mode={orion_mode} -> model={agent_model}")
    except Exception as _mr_err:
        logging.warning(f"[MODEL_ROUTER] Fallback to config model: {_mr_err}")

    # Detect if this is an agent task (needs SSH/files/browser) or simple chat
    # ══ LLM ORCHESTRATOR: определяем намерение через AI, а не ключевые слова ══
    # Build chat history for context (needed for orchestrator too)
    # BUG-4 FIX: limit to last 10 messages for orchestrator to avoid context overflow
    history = []
    for m in chat.get("messages", [])[-10:]:
        history.append({"role": m["role"], "content": m["content"][:200]})

    # Определяем намерение
    # ══ QUICK PATH REMOVED: ALL messages go through full agent ══
    _is_quick_msg = False  # Never skip — all messages use agent with tools
    
    if ssh_from_msg:
        intent = {"mode": "deploy", "reason": "SSH креденциалы в сообщении", "confidence": 1.0}
    else:
        intent = detect_intent_llm(user_message, history, OPENROUTER_API_KEY)

    mode = intent["mode"]  # chat | file | deploy | research | data
    # ══ IMAGE ROUTE FIX: Force image requests to file mode (→ lite_agent → _check_force_tool) ══
    _img_route_triggers = [
        "сделай картинк", "создай картинк", "нарисуй", "сгенерируй изображен",
        "сделай фото", "создай фото", "сделай изображен", "создай изображен",
        "сделай иллюстрац", "создай иллюстрац", "нарисуй мне",
        "сделай баннер", "создай баннер", "сделай постер", "создай постер",
        "сделай лого", "создай лого", "сделай иконк", "создай иконк",
        "make image", "create image", "generate image", "draw me",
    ]
    if any(t in user_message.lower().strip() for t in _img_route_triggers) and mode == "chat":
        mode = "file"  # Route to lite_agent where _check_force_tool handles image gen
        logging.info(f"[send_message] IMAGE ROUTE: Redirected '{user_message[:40]}' from chat → file (lite_agent)")

    # ══ MODEL ROUTER: автовыбор модели по сложности запроса ══
    has_ssh = bool(ssh_credentials.get("host") and ssh_credentials.get("password"))
    routed = select_model(user_message, variant=variant, history=history)
    routed_model_id = routed["model_id"]
    routed_model_name = routed["model_name"]
    routed_tier = routed["tier"]
    routed_complexity = routed["complexity"]
    logging.info(f"[ModelRouter] query='{user_message[:60]}' complexity={routed_complexity} tier={routed_tier} model={routed_model_id}")

    is_agent_task = (mode == "deploy")
    is_file_task = (mode == "file")
    is_browser_task = (mode == "research")
    has_url = bool(re.search(r'https?://\S+', user_message))
    if has_url and mode == "chat":
        is_browser_task = True
    # ── BUG-1 FIX v2: SSH доступен во ВСЕХ режимах (TURBO/PRO/AGENT/ELITE) ──
    # Если есть SSH credentials и запрос содержит SSH-ключевые слова → AgentLoop
    _ssh_kw = ["ssh", "сервер", "server", "uname", "apt ", "apt-get", "pip install",
               "npm install", "docker", "nginx", "systemd", "деплой", "deploy",
               "разверни", "установи на", "выполни", "запусти", "команд",
               "проверь пакет", "ls ", "cat ", "grep ", "cd ", "mkdir",
               "rm ", "cp ", "mv ", "chmod", "chown", "systemctl",
               "journalctl", "curl ", "wget ", "git ", "nano ", "vim "]
    if has_ssh and not is_agent_task and any(kw in user_message.lower() for kw in _ssh_kw):
        is_agent_task = True
        mode = "deploy"
        logging.info(f"[send_message] BUG-1 FIX v2: SSH keywords detected + has_ssh → forced agent mode")
    # ═══ BROWSER FIX: Browser/screenshot requests → force lite_agent with tools ═══
    _browser_kw = ["скриншот", "screenshot", "открой сайт", "открой страниц",
                   "покажи сайт", "покажи страниц", "зайди на", "перейди на",
                   "browser", "браузер", "веб-страниц", "webpage"]
    if not is_agent_task and any(kw in user_message.lower() for kw in _browser_kw):
        mode = "file"  # Forces lite_agent path
        logging.info(f"[send_message] BROWSER FIX: browser/screenshot keywords → forced file mode (lite_agent)")
    # URL + лендинг/сайт/создай → file mode → lite_agent (даже если is_browser_task)
    _landing_kw2 = ["лендинг", "landing", "сайт", "создай", "сделай", "сгенерируй", "напиши"]
    if has_url and any(kw in user_message.lower() for kw in _landing_kw2) and mode in ("chat", "research"):
        mode = "file"
        is_browser_task = False
        is_file_task = True

    # ══ ALL requests → AgentLoop with tools (quick path removed) ══
    if is_agent_task and has_ssh:
        is_lite_agent = False  # Goes to full SSH agent branch
    else:
        is_lite_agent = True   # ALL other requests → AgentLoop with TOOLS_SCHEMA
        logging.info(f"[send_message] CRITICAL FIX: mode={mode} → lite_agent=True (agent with tools)")

    # Build chat history for context
    # Context: 50 messages for Pro/Architect, 10 for Turbo
    _ctx_limit_app = 50 if orion_mode in ("standard", "premium") else 10
    history = [{"role": m["role"], "content": m["content"]} for m in chat["messages"][-_ctx_limit_app:]]

    # ═══ ФИНАЛЬНАЯ АРХИТЕКТУРА: Pro/Architect bypass — один агент, без pipeline ═══
    if orion_mode in ("standard", "premium"):
        if orion_mode == "premium":
            _pro_agent_model = "openai/gpt-5.4"  # PATCHED: was opus, now gpt54
            _pro_model_name = "GPT-5.4"
        elif orion_mode == "standard":
            _pro_agent_model = "openai/gpt-5.4"
            _pro_model_name = "GPT-5.4"
        else:
            _pro_agent_model = "openai/gpt-5.4"
            _pro_model_name = "GPT-5.4"
        
        _pro_auto_prefix = ""
        if _auto_resolved_mode:
            _pro_auto_prefix = "Авто · "
        
        logging.info(f"[PRO BYPASS] mode={orion_mode} model={_pro_agent_model} — skipping pipeline/orchestrator")
        
        _pro_loop = AgentLoop(
            model=_pro_agent_model,
            api_key=OPENROUTER_API_KEY,
            api_url=OPENROUTER_BASE_URL,
            ssh_credentials=ssh_credentials,
            user_id=request.user_id,
        )
        _pro_loop._chat_id = chat_id
        _pro_loop._verify_enabled = data.get("verify", False)
        _pro_loop.MAX_ITERATIONS = 30
        _pro_loop.orion_mode = orion_mode
        
        # Register agent for stop functionality
        with _agents_lock:
            _active_agents[chat_id] = _pro_loop
        
        # ══ PRO BACKGROUND THREAD: agent runs in background, SSE reads from queue ══
        # This ensures GeneratorExit (client disconnect) does NOT kill the agent
        import queue as _queue_module
        _saved_user_id_pro = request.user_id
        _saved_db_pro = db
        
        # Register task in _running_tasks with event queue
        with _tasks_lock:
            _running_tasks[chat_id] = {
                "status": "running",
                "events": [],
                "started_at": time.time(),
                "user_id": _saved_user_id_pro,
                "message": user_message[:100],
                    "events": [],
                "_queue": _queue_module.Queue(),
            }
        
        def _pro_background_worker():
            """Runs agent in background thread, puts events into queue."""
            full_response = ""
            tokens_in = 0
            tokens_out = 0
            _q = None
            with _tasks_lock:
                task = _running_tasks.get(chat_id)
                if task:
                    _q = task["_queue"]
            
            def _put(event):
                """Put event into queue and buffer."""
                if isinstance(event, dict):
                    event = "data: " + json.dumps(event, ensure_ascii=False) + "\n\n"
                with _tasks_lock:
                    task = _running_tasks.get(chat_id)
                    if task:
                        task["events"].append(event)
                if _q:
                    _q.put(event)
            
            # Send meta event
            _put(f"data: {json.dumps({'type': 'meta', 'variant': variant, 'model': _pro_auto_prefix + _pro_model_name, 'enhanced': False, 'self_check_level': 'none', 'agent_mode': True, 'tier': 'pro', 'complexity': 'high'})}\n\n")
            
            try:
                for event in _pro_loop.run_stream(user_message, history, file_content):
                    if isinstance(event, dict):
                        event = "data: " + json.dumps(event, ensure_ascii=False) + "\n\n"
                    _put(event)
                    try:
                        event_data = json.loads(event.replace("data: ", "").strip())
                        if event_data.get("type") == "content":
                            full_response += event_data.get("text", "")
                        if event_data.get("type") == "usage":
                            tokens_in += event_data.get("prompt_tokens", 0)
                            tokens_out += event_data.get("completion_tokens", 0)
                    except:
                        pass
            except Exception as e:
                logging.error(f"[PRO BG] Error: {e}")
                _put(f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n")
            finally:
                with _agents_lock:
                    _active_agents.pop(chat_id, None)
                    # ══ PATCH14-FIX: Cleanup _running_tasks ══
                    with _tasks_lock:
                        _running_tasks.pop(chat_id, None)
                # Save response
                if full_response:
                    with _tasks_lock:
                        pass  # db access outside lock
                    chat["messages"].append({"role": "assistant", "content": full_response, "created_at": _now_iso()})
                    db_write(_saved_db_pro)
                # Cost tracking — use AgentLoop's own _session_cost for accuracy
                _loop_cost = getattr(_pro_loop, '_session_cost', 0.0)
                _loop_tokens_in = getattr(_pro_loop, 'total_tokens_in', tokens_in)
                _loop_tokens_out = getattr(_pro_loop, 'total_tokens_out', tokens_out)
                # Use loop cost if available (more accurate), else fallback to calc
                _cost = _loop_cost if _loop_cost > 0 else _calc_cost(tokens_in, tokens_out, _pro_agent_model)
                _final_tokens_in = _loop_tokens_in if _loop_tokens_in > 0 else tokens_in
                _final_tokens_out = _loop_tokens_out if _loop_tokens_out > 0 else tokens_out
                chat["total_cost"] = chat.get("total_cost", 0) + _cost
                _user = _saved_db_pro["users"].get(_saved_user_id_pro, {})
                if _user:
                    _user["total_spent"] = _user.get("total_spent", 0) + _cost
                _analytics = _saved_db_pro.get("analytics", {})
                _analytics["total_tokens_in"] = _analytics.get("total_tokens_in", 0) + _final_tokens_in
                _analytics["total_tokens_out"] = _analytics.get("total_tokens_out", 0) + _final_tokens_out
                _analytics["total_cost"] = _analytics.get("total_cost", 0) + _cost
                _analytics["total_requests"] = _analytics.get("total_requests", 0) + 1
                db_write(_saved_db_pro)
                try:
                    log_cost(
                        user_id=_saved_user_id_pro,
                        model_id=_pro_agent_model,
                        tokens_in=_final_tokens_in,
                        tokens_out=_final_tokens_out,
                        cost_usd=_cost,
                        tier="pro",
                        complexity=5,
                        tool_name="agent_pro",
                        mode=orion_mode,
                    )
                except Exception as _lc_err:
                    logging.warning(f"log_cost error: {_lc_err}")
                # Send done event with accurate cost from AgentLoop
                _put(f"data: {json.dumps({'type': 'done', 'cost': _cost, 'tokens_in': _final_tokens_in, 'tokens_out': _final_tokens_out, 'model': _pro_model_name})}\n\n")
                # Mark task done and signal queue
                with _tasks_lock:
                    task = _running_tasks.get(chat_id)
                    if task:
                        task["status"] = "done"
                        _cleanup_running_task(chat_id)
                        task["finished_at"] = time.time()
                if _q:
                    _q.put(None)  # Sentinel: stream ended
                logging.info(f"[PRO BG] Worker finished for chat {chat_id}")
        
        # Start background thread
        _bg_thread = threading.Thread(target=_pro_background_worker, daemon=True, name=f"pro-agent-{chat_id[:8]}")
        _bg_thread.start()
        
        def _pro_sse_stream():
            """SSE stream that reads from queue. Survives client reconnects."""
            with _tasks_lock:
                task = _running_tasks.get(chat_id)
                _q = task["_queue"] if task else None
            
            if not _q:
                return
            
            try:
                while True:
                    try:
                        event = _q.get(timeout=30)  # 30s timeout per event
                        if event is None:  # Sentinel: stream ended
                            break
                        yield event
                    except _queue_module.Empty:
                        # Check if task is still running
                        with _tasks_lock:
                            task = _running_tasks.get(chat_id)
                        if not task or task.get("status") == "done":
                            break
                        # Send keepalive
                        yield ": keepalive\n\n"
            except GeneratorExit:
                logging.info(f"[PRO SSE] Client disconnected from chat {chat_id}, agent continues in background")
                # Do NOT stop the agent - it continues in background thread
        
        return Response(stream_with_context(_pro_sse_stream()), mimetype='text/event-stream',
                       headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'})
    
    # ═══ TURBO: оркестратор + pipeline как раньше ═══
    _saved_user_id = request.user_id  # PATCH: save before generator loses request context
    def generate():
        nonlocal routed_model_name, model_name, agent_model_name
        full_response = ""
        tokens_in = 0  # CRИТ-2 FIX: инициализация до всех веток
        tokens_out = 0  # КРИТ-2 FIX: инициализация до всех веток

        # ══ TASK PERSISTENCE: register running task ══
        with _tasks_lock:
            _running_tasks[chat_id] = {
                "status": "running",
                "events": [],
                "started_at": time.time(),
                "user_id": _saved_user_id,
                "message": user_message[:100],
                    "events": [],
            }

        # Send metadata — show routed model info
        if (is_agent_task and has_ssh) or is_lite_agent:
            active_model_name = agent_model_name
        else:
            active_model_name = routed_model_name
        yield f"data: {json.dumps({'type': 'meta', 'variant': variant, 'model': active_model_name, 'enhanced': enhanced, 'self_check_level': self_check_level, 'agent_mode': (is_agent_task and has_ssh) or is_lite_agent, 'tier': routed_tier, 'complexity': routed_complexity})}\n\n"

        # ── Send auto-title to frontend ──
        try:
            _db_t = db_read()
            _chat_t = _db_t.get('chats', {}).get(chat_id, {})
            _title_t = _chat_t.get('title', '')
            if _title_t and _title_t != 'Новый чат':
                yield "data: " + json.dumps({"type": "title", "title": _title_t}) + "\n\n"
        except Exception:
            pass
        # ── Orchestrator v2: определить агентов по плану ──
        logging.info(f'[send_message] Orchestrator available: {_ORCHESTRATOR_AVAILABLE}, mode={mode}')
        _orch_plan_send = None
        if _ORCHESTRATOR_AVAILABLE :
            try:
                def _orch_llm_send(messages, model=None):
                    import requests as _rq
                    _llm_model = model or "openai/gpt-5.4-mini"  # PATCH fix2: real model ID
                    logging.info(f"[_orch_llm_send] Calling {_llm_model} with {len(messages)} messages")
                    resp = _rq.post(
                        OPENROUTER_BASE_URL,
                        headers={"Authorization": f"Bearer {OPENROUTER_API_KEY}",
                                 "Content-Type": "application/json"},
                        json={"model": _llm_model, 
                              "messages": messages, "max_tokens": 2000},
                        timeout=30
                    )
                    _resp_json = resp.json()
                    logging.info(f"[_orch_llm_send] Status: {resp.status_code}, keys: {list(_resp_json.keys())}")
                    if "error" in _resp_json:
                        logging.warning(f"[_orch_llm_send] API error: {_resp_json['error']}")
                    _content = _resp_json.get("choices",[{}])[0].get("message",{}).get("content","")
                    logging.info(f"[_orch_llm_send] Content length: {len(_content)}")
                    return _content
                
                _orch_send = Orchestrator(_orch_llm_send, orion_mode)  # FIX: pass orion_mode not intent mode
                _has_ssh_send = bool(ssh_credentials.get("host") and ssh_credentials.get("password"))
                _ssh_info_send = f"host={ssh_credentials.get('host','')}, user={ssh_credentials.get('username','root')}, password=PROVIDED" if _has_ssh_send else ""
                _orch_plan_send = _orch_send.plan(user_message, history, 
                                                   has_ssh=_has_ssh_send,
                                                   ssh_info=_ssh_info_send)
                logging.info(f'[send_message] Orchestrator plan result: {_orch_plan_send}')
                
                # Отправить план клиенту
                if _orch_plan_send and _orch_plan_send.get("mode") != "chat":
                    logging.info(f"[send_message] Sending SSE task_plan event: {json.dumps(format_plan_sse(_orch_plan_send))[:200]}")
                    yield f"data: {json.dumps(format_plan_sse(_orch_plan_send))}\n\n"
                
                # Переопределить модель если нужно
                _pm = _orch_plan_send.get("primary_model", "")
                # PATCHED: Do NOT override agent_model from orchestrator primary_model
                # The model is already correctly set by _mode_to_model based on orion_mode
                # Orchestrator primary_model was causing wrong models (deepseek, opus) to be used
                if _pm:
                    logging.info(f"[ORCH] primary_model={_pm} (ignored, using mode-based model)")
                    
            except Exception as _oe:
                logging.warning(f"Orchestrator in send_message: {_oe}"); import traceback; logging.warning(f"Orchestrator traceback: {traceback.format_exc()}")
        

        if is_lite_agent:
            # ═══ AGENT MODE (with tools): ALL non-quick, non-SSH requests ═══
            if is_browser_task:
                _lite_mode_text = 'Открываю браузер...'
            elif mode in ('file', 'data'):
                _lite_mode_text = 'Генерирую файл...'
            else:
                _lite_mode_text = 'Анализирую запрос...'
            yield f"data: {json.dumps({'type': 'agent_mode', 'text': _lite_mode_text})}\n\n"

            agent = AgentLoop(
                model=agent_model,
                api_key=OPENROUTER_API_KEY,
                api_url=OPENROUTER_BASE_URL,
                ssh_credentials={},  # No SSH needed for file generation
                user_id=_saved_user_id,  # BUG-5 FIX
                orion_mode=orion_mode,  # FIX: pass orion_mode for correct model selection
            )
            agent._chat_id = chat_id  # BUG-5 FIX
            agent._verify_enabled = data.get("verify", False)  # ПАТЧ 7
            # BUG-8 FIX: Pass orchestrator plan to agent
            if _orch_plan_send:
                agent._orchestrator_plan = _orch_plan_send

            with _agents_lock:
                _active_agents[chat_id] = agent

            # ══ PATCH14-FIX: Register in _running_tasks for lite_agent ══
            with _tasks_lock:
                _running_tasks[chat_id] = {
                    "status": "running",
                    "started_at": time.time(),
                    "user_id": _saved_user_id,
                    "message": user_message[:100],
                    "events": [],
                }
            try:
                for event in agent.run_stream(user_message, history, file_content):
                    # Safety: convert dict events to SSE string format
                    if isinstance(event, dict):
                        import json as _j
                        event = "data: " + _j.dumps(event, ensure_ascii=False) + chr(10) + chr(10)
                    yield event
                    try:
                        event_data = json.loads(event.replace("data: ", "").strip())
                        if event_data.get("type") == "content":
                            full_response += event_data.get("text", "")
                    except Exception as _sse_err:
                        logging.warning(f"SSE parse error: {_sse_err}")

                tokens_in = agent.total_tokens_in
                tokens_out = agent.total_tokens_out

            finally:
                with _agents_lock:
                    _active_agents.pop(chat_id, None)
                    # ══ PATCH14-FIX: Cleanup _running_tasks ══
                    with _tasks_lock:
                        _running_tasks.pop(chat_id, None)

        elif is_agent_task and has_ssh:
            # ═══ AGENT MODE: Real execution with SSH/Browser/Files ═══

            # ── Project Memory: load context from previous sessions ──
            try:
                pm = ProjectMemory(user_id=_saved_user_id, project_id=chat_id)
                pm.start_session(chat_id, task=user_message[:200])
                memory_context = pm.get_full_context(chat_id)
                if memory_context:
                    yield f"data: {json.dumps({'type': 'memory_loaded', 'text': 'Контекст предыдущих сессий загружен', 'context_length': len(memory_context)})}\n\n"
            except Exception:
                pm = None
                memory_context = ""

            # ── Select agent execution mode ──
            selected_agents = select_agents_for_task(user_message, mode)
            use_parallel = len(selected_agents) >= 2 and enhanced
            agent_names = [a.get('name', '?') for a in selected_agents]

            yield f"data: {json.dumps({'type': 'agent_mode', 'text': 'Запускаю автономный агент...', 'agents': agent_names, 'parallel': use_parallel})}\n\n"

            if use_parallel:
                # ── Parallel multi-agent execution ──
                orchestrator = ParallelAgentOrchestrator(
                    model=agent_model,
                    api_key=OPENROUTER_API_KEY,
                    api_url=OPENROUTER_BASE_URL,
                    ssh_credentials=ssh_credentials,
                    max_workers=min(3, len(selected_agents))
                )
                agent = orchestrator  # For stop functionality

            elif enhanced:
                # Multi-agent pipeline (sequential, 6 specialized agents)
                agent = MultiAgentLoop(
                    model=agent_model,
                    api_key=OPENROUTER_API_KEY,
                    api_url=OPENROUTER_BASE_URL,
                    ssh_credentials=ssh_credentials,
                    orion_mode=orion_mode,
                    session_id=chat_id
                )
            elif _orch_plan_send and _orch_plan_send.get("mode") == "multi_sequential":
                # BUG-8 FIX: Orchestrator requested multi_sequential → use MultiAgentLoop
                agent = MultiAgentLoop(
                    model=agent_model,
                    api_key=OPENROUTER_API_KEY,
                    api_url=OPENROUTER_BASE_URL,
                    ssh_credentials=ssh_credentials,
                    orion_mode=orion_mode,
                    session_id=chat_id
                )
                logging.info(f"[send_message] BUG-8 FIX: Using MultiAgentLoop for multi_sequential plan")
            else:
                # Single agent loop
                # === МАРШРУТИЗАЦИЯ МОДЕЛИ (ПАТЧ A3) ===
                _sm_model_override = None
                _sm_extra_prompt = None
                try:
                    from intent_clarifier import clarify as _sm_clarify
                    _sm_intent = _sm_clarify(user_message)
                    _sm_primary = _sm_intent.get("primary_model", "")
                    if _sm_primary == "gemini":
                        _sm_model_override = "google/gemini-2.5-pro"
                        _sm_extra_prompt = "РЕЖИМ ДИЗАЙНЕРА: Создавай красивые веб-страницы с Google Fonts, градиентами, анимациями. Сохраняй HTML в файл через file_write."
                    elif _sm_primary == "sonnet":
                        _sm_model_override = "anthropic/claude-sonnet-4.6"
                except Exception as _route_err:
                    logging.warning(f"Model routing error: {_route_err}")
                # === КОНЕЦ МАРШРУТИЗАЦИИ ===
                # ── BUG-1 FIX: Premium mode → Sonnet for agent too ──
                if orion_mode == "premium" and not _sm_model_override:
                    _sm_model_override = "anthropic/claude-sonnet-4.6"
                    model_name = "Claude Sonnet 4.6"
                    agent_model_name = "Claude Sonnet 4.6"
                    routed_model_name = "Claude Sonnet 4.6"
                    logging.info(f"[send_message] BUG-1 FIX: Agent premium mode {orion_mode} → Sonnet")
                agent = AgentLoop(
                    model=agent_model,
                    api_key=OPENROUTER_API_KEY,
                    api_url=OPENROUTER_BASE_URL,
                    ssh_credentials=ssh_credentials,
                    user_id=_saved_user_id,  # BUG-5 FIX
                    orion_mode=orion_mode,  # FIX: pass orion_mode for correct model selection
                    model_override=_sm_model_override,
                    system_prompt_override=_sm_extra_prompt
                )
                agent._chat_id = chat_id  # BUG-5 FIX: передаём chat_id
                # CAP MAX_ITERATIONS for fast mode to prevent runaway loops
                if orion_mode == "fast":
                    agent.MAX_ITERATIONS = 15
                elif orion_mode == "standard":
                    agent.MAX_ITERATIONS = 25

            # BUG-8 FIX 2: Pass orchestrator plan to SSH agent
            if _orch_plan_send:
                agent._orchestrator_plan = _orch_plan_send
                logging.info(f"[send_message] BUG-8: Passed orch plan to SSH agent")
            # Register agent for stop functionality
            with _agents_lock:
                _active_agents[chat_id] = agent

            # ══ PATCH14-FIX: Register in _running_tasks so queue/append/interrupt works ══
            with _tasks_lock:
                _running_tasks[chat_id] = {
                    "status": "running",
                    "started_at": time.time(),
                    "user_id": _saved_user_id,
                    "message": user_message[:100],
                    "events": [],
                }
            try:
                # ══ PATCH 4: Multi-agent SSE error handling ══
                if use_parallel:
                    agent_keys = [a.get('key', a.get('role', '')) for a in selected_agents]
                    event_gen = orchestrator.run_parallel(
                        user_message, history, file_content,
                        agent_keys=agent_keys, mode=mode
                    )
                elif enhanced:
                    try:
                        event_gen = agent.run_multi_agent_stream(user_message, history, file_content)
                    except Exception as _multi_init_err:
                        logging.error(f"Multi-agent init error: {_multi_init_err}, falling back to single agent")
                        event_gen = agent.run_stream(user_message, history, file_content)
                else:
                    event_gen = agent.run_stream(user_message, history, file_content)

                for event in event_gen:
                    try:
                        yield event
                    except GeneratorExit:
                        logging.warning(f"[PRO] GeneratorExit - client disconnected")
                        return
                    # Capture text content
                    try:
                        event_data = json.loads(event.replace("data: ", "").strip())
                        if event_data.get("type") == "content":
                            full_response += event_data.get("text", "")
                    except Exception as _sse_err:
                        logging.warning(f"SSE parse error: {_sse_err}")
                # Send done event after loop finishes
                try:
                    yield "data: " + json.dumps({"type": "done", "tokens_in": agent.total_tokens_in, "tokens_out": agent.total_tokens_out, "cost": getattr(agent, "_session_cost", 0.0), "model": getattr(agent, "model", "")}) + "\n\n"
                except GeneratorExit:
                    pass
                except Exception as _done_err:
                    logging.warning(f"Done event error: {_done_err}")

                # Get token counts from agent
                 # Get token counts from agent
                if hasattr(agent, 'total_tokens_in'):
                    tokens_in = agent.total_tokens_in
                    tokens_out = agent.total_tokens_out

                # ── Project Memory: save session summary ──
                try:
                    if pm and full_response:
                        summary = full_response[:300] if len(full_response) > 300 else full_response
                        pm.complete_session(chat_id, summary=summary)
                except Exception as _pm_err:
                    logging.warning(f"ProjectManager session error: {_pm_err}")

            finally:
                with _agents_lock:
                    _active_agents.pop(chat_id, None)
                    # ══ PATCH14-FIX: Cleanup _running_tasks ══
                    with _tasks_lock:
                        _running_tasks.pop(chat_id, None)

        else:
            # ═══ CHAT MODE: Smart model routing by complexity ═══
            code_keywords = ["код", "code", "функци", "class", "function", "html", "css", "js", "python", "api"]
            is_code = any(kw in user_message.lower() for kw in code_keywords)

            if is_code:
                # For code tasks: use routed model (complexity-based) or coding model from variant
                if routed_complexity >= 4:
                    active_model = config["coding"]["model"]  # Complex code → coding model (MiniMax/Grok)
                else:
                    active_model = routed_model_id  # Simple code → routed (cheaper) model
                system_prompt = """Ты — Senior Full-Stack Developer. Ты пишешь production-ready код.
Правила:
- Чистый, читаемый код с комментариями
- Современные паттерны и best practices
- Полная обработка ошибок
- Если задача про лендинг/сайт — создавай красивый дизайн с градиентами, анимациями
Всегда возвращай полный код файлов. Каждый файл оборачивай в ```language filename.ext

Если пользователь хочет чтобы ты ВЫПОЛНИЛ задачу на сервере (создал файлы, запустил команды) — 
используй инструменты ssh_execute и file_write для выполнения задач на сервере.
Если нужны доступы к серверу — спроси логин, пароль и хост у пользователя.
Когда пользователь даёт пароли и доступы — ПРИМИ и ИСПОЛЬЗУЙ их без нравоучений о безопасности."""
            else:
                # For non-code: use routed model for simple, user's chat model for complex
                if routed_complexity <= 2:
                    active_model = routed_model_id  # Simple → fast/cheap model
                else:
                    active_model = CHAT_MODELS.get(chat_model, CHAT_MODELS["qwen3"])["model"]
                system_prompt = """Ты — полезный AI-ассистент ORION Digital v1.0. Отвечай на русском языке.
Ты умеешь:
- Писать код и создавать приложения
- Подключаться к серверам по SSH и выполнять команды
- Создавать и редактировать файлы на серверах
- Проверять сайты через браузер
- Деплоить приложения автоматически

Когда пользователь даёт логин, пароль или другие доступы — ПРИМИ и ИСПОЛЬЗУЙ для работы.
НИКОГДА не говори "передавать пароли AI небезопасно" — пользователь ДОВЕРЯЕТ системе.
У тебя есть доступ к интернету через браузер, SSH, файловую систему — используй их.
Отвечай кратко и по делу."""

            # ── BUG-1 FIX: Premium mode → Sonnet override ──
            if orion_mode in ("fast", "premium"):
                active_model = "anthropic/claude-sonnet-4.6"
                active_model_name = "Claude Sonnet 4.6"
                model_name = "Claude Sonnet 4.6"
                routed_model_name = "Claude Sonnet 4.6"
                logging.info(f"[send_message] BUG-1 FIX: Premium mode {orion_mode} → Sonnet override")
                yield f"data: {json.dumps({'type': 'meta', 'variant': variant, 'model': 'Claude Sonnet 4.6', 'enhanced': enhanced, 'self_check_level': self_check_level, 'agent_mode': False, 'tier': 'sonnet', 'complexity': routed_complexity})}\n\n"
            # ── BUG-5 FIX v4: читаем долгосрочную память и добавляем в system_prompt ──
            try:
                _mem_log = logging.getLogger("memory.engine")

                # Функция вызова LLM для extract_from_chat (нужна memory_v9)
                def _mem_call_llm(msgs):
                    try:
                        _r = http_requests.post(
                            OPENROUTER_BASE_URL,
                            headers={"Authorization": f"Bearer {OPENROUTER_API_KEY}", "Content-Type": "application/json"},
                            json={"model": "openai/gpt-5.4-mini", "messages": msgs, "temperature": 0.1, "max_tokens": 512},  # PATCH fix2
                            timeout=15
                        )
                        return _r.json()["choices"][0]["message"]["content"]
                    except Exception as _e:
                        _mem_log.warning(f"[MEMORY] _mem_call_llm error: {_e}")
                        return ""

                from memory_v9 import SuperMemoryEngine
                # SuperMemoryEngine.__init__ принимает call_llm_func — передаём его
                _mem_v9 = SuperMemoryEngine(call_llm_func=_mem_call_llm)
                _mem_v9.init_task(
                    user_message=user_message,
                    user_id=_saved_user_id,
                    chat_id=chat_id,
                    api_key=OPENROUTER_API_KEY,
                    api_url=OPENROUTER_BASE_URL
                )
                # build_messages принимает chat_history (не history)
                _mem_context = _mem_v9.build_messages(
                    system_prompt=system_prompt,
                    chat_history=[],
                    user_message=user_message
                )
                # build_messages возвращает список — берём system из первого элемента
                if _mem_context and _mem_context[0].get("role") == "system":
                    _enriched_prompt = _mem_context[0]["content"]
                    if _enriched_prompt != system_prompt:
                        system_prompt = _enriched_prompt
                        _mem_log.info(f"[MEMORY] CHAT MODE READ OK: +{len(_enriched_prompt)-len(system_prompt)} chars injected, user={_saved_user_id!r}")
                    else:
                        _mem_log.info(f"[MEMORY] CHAT MODE READ: no facts yet for user={_saved_user_id!r}")
            except Exception as _mem_chat_err:
                logging.getLogger("memory.engine").warning(f"[MEMORY] CHAT MODE memory read failed: {_mem_chat_err}", exc_info=True)

            messages = [{"role": "system", "content": system_prompt}]
            for msg in history:
                messages.append({"role": msg["role"], "content": msg["content"]})

            if file_content:
                # Truncate file content to avoid exceeding API limits
                fc = file_content
                if len(fc) > 30000:
                    fc = fc[:30000] + f"\n... [обрезано, всего {len(file_content)} символов]"
                messages[-1]["content"] = f"{fc}\n\n---\n\nЗадача:\n{user_message}"

            # Stream response
            headers = {
                "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                "Content-Type": "application/json",
                "HTTP-Referer": "https://orion.mksitdev.ru",
                "X-Title": "ORION Digital v4.0"
            }

            payload = {
                "model": active_model,
                "messages": messages,
                "temperature": 0.3,
                "max_tokens": 16000,
                "stream": True
            }

            tokens_in = 0
            tokens_out = 0

            try:
                resp = http_requests.post(
                    OPENROUTER_BASE_URL,
                    headers=headers,
                    json=payload,
                    stream=True,
                    timeout=120
                )
                resp.raise_for_status()

                for line in _iter_lines_with_timeout(resp, timeout_per_chunk=90):
                    if not line:
                        continue
                    line_str = line.decode("utf-8", errors="replace")
                    if not line_str.startswith("data: "):
                        continue
                    payload_str = line_str[6:]
                    if payload_str.strip() == "[DONE]":
                        break
                    try:
                        chunk = json.loads(payload_str)
                        choices = chunk.get("choices", [])
                        if choices:
                            delta = choices[0].get("delta", {})
                            text = delta.get("content", "")
                            if text:
                                full_response += text
                                yield f"data: {json.dumps({'type': 'content', 'text': text})}\n\n"

                        usage = chunk.get("usage")
                        if usage:
                            tokens_in += usage.get("prompt_tokens", 0)
                            tokens_out += usage.get("completion_tokens", 0)
                    except json.JSONDecodeError:
                        continue

            except Exception as e:
                error_msg = f"❌ Ошибка API: {str(e)}"
                yield f"data: {json.dumps({'type': 'error', 'text': error_msg})}\n\n"
                full_response = error_msg

            # ═══ SELF-CHECK: проверка ответа вторым AI ═══
            if self_check_level != "none" and full_response and "❌" not in full_response[:10]:
                SELF_CHECK_MODELS = {
                    "light":  {"model": "openai/gpt-5.4-mini", "name": "GPT-5.4 Mini", "input_price": 0.27, "output_price": 0.95},  # PATCH fix2
                    "medium": None,  # same model as main
                    "deep":   {"model": "anthropic/claude-sonnet-4.6", "name": "Claude Sonnet 4", "input_price": 3.00, "output_price": 15.00},
                }
                check_config = SELF_CHECK_MODELS.get(self_check_level)
                if self_check_level == "medium":
                    check_model_id = active_model
                    check_model_name = "Same Model"
                    check_input_price = routed.get("input_price", 0.10)
                    check_output_price = routed.get("output_price", 0.40)
                elif check_config:
                    check_model_id = check_config["model"]
                    check_model_name = check_config["name"]
                    check_input_price = check_config["input_price"]
                    check_output_price = check_config["output_price"]
                else:
                    check_model_id = None

                if check_model_id:
                    yield f"data: {json.dumps({'type': 'self_check', 'status': 'started', 'level': self_check_level, 'checker': check_model_name})}\n\n"

                    check_prompt = f"""Ты — критик и верификатор AI-ответов. Проверь следующий ответ на:
1. Фактические ошибки и галлюцинации
2. Логические противоречия
3. Неполноту ответа
4. Ошибки в коде (если есть код)

Вопрос пользователя: {user_message}

Ответ AI:
{full_response[:8000]}

Если ответ хороший — верни его как есть.
Если нашёл ошибки — верни ИСПРАВЛЕННУЮ версию полного ответа.
Не добавляй комментарии о проверке, верни только финальный ответ."""

                    check_messages = [{"role": "user", "content": check_prompt}]
                    check_payload = {
                        "model": check_model_id,
                        "messages": check_messages,
                        "temperature": 0.1,
                        "max_tokens": 16000,
                        "stream": True
                    }

                    try:
                        check_resp = http_requests.post(
                            OPENROUTER_BASE_URL,
                            headers=headers,
                            json=check_payload,
                            stream=True,
                            timeout=120
                        )
                        check_resp.raise_for_status()

                        checked_response = ""
                        # Signal frontend to clear previous response and show checked version
                        yield f"data: {json.dumps({'type': 'self_check_replace', 'status': 'streaming'})}\n\n"

                        for line in _iter_lines_with_timeout(check_resp, timeout_per_chunk=60):
                            if not line:
                                continue
                            line_str = line.decode("utf-8", errors="replace")
                            if not line_str.startswith("data: "):
                                continue
                            payload_str = line_str[6:]
                            if payload_str.strip() == "[DONE]":
                                break
                            try:
                                chunk = json.loads(payload_str)
                                choices = chunk.get("choices", [])
                                if choices:
                                    delta = choices[0].get("delta", {})
                                    text = delta.get("content", "")
                                    if text:
                                        checked_response += text
                                        yield f"data: {json.dumps({'type': 'self_check_content', 'text': text})}\n\n"
                                usage = chunk.get("usage")
                                if usage:
                                    tokens_in += usage.get("prompt_tokens", 0)
                                    tokens_out += usage.get("completion_tokens", 0)
                            except json.JSONDecodeError:
                                continue

                        if checked_response.strip():
                            full_response = checked_response
                            yield f"data: {json.dumps({'type': 'self_check', 'status': 'done', 'level': self_check_level})}\n\n"
                        else:
                            yield f"data: {json.dumps({'type': 'self_check', 'status': 'kept_original', 'level': self_check_level})}\n\n"

                    except Exception as e:
                        logging.warning(f"Self-check failed: {e}")
                        yield f"data: {json.dumps({'type': 'self_check', 'status': 'error', 'error': str(e)[:100]})}\n\n"

        # Calculate cost using AGENT model prices (not routed model)
        # For fast mode: agent_model=gpt-5.4-mini, routed_model=gpt-5.4 (wrong if using routed)
        from model_router import MODELS as _MODELS
        _agent_model_key = None
        for _k, _m in _MODELS.items():
            if _m["id"] == agent_model:
                _agent_model_key = _k
                break
        if _agent_model_key:
            _active_input_price = _MODELS[_agent_model_key]["input_price"]
            _active_output_price = _MODELS[_agent_model_key]["output_price"]
        else:
            _active_input_price = routed.get("input_price", config["coding"]["input_price"])
            _active_output_price = routed.get("output_price", config["coding"]["output_price"])
        cost_in = (tokens_in / 1_000_000) * _active_input_price
        cost_out = (tokens_out / 1_000_000) * _active_output_price
        total_cost = round(cost_in + cost_out, 6)
        # КРИТ-2 FIX: используем реальную стоимость из расчёта токенов

        # Log cost via model_router for analytics
        try:
            log_cost(
                user_id=_saved_user_id,
                model_id=routed_model_id,
                tokens_in=tokens_in,
                tokens_out=tokens_out,
                cost_usd=total_cost,
                tier=routed_tier,
                complexity=routed_complexity,
                tool_name=mode,
                success="\u274c" not in full_response[:100]
            )
        except Exception as _nc_err:
            logging.warning(f"Non-critical error: {_nc_err}")

        # Save assistant message
        db2 = db_read()
        chat2 = db2["chats"].get(chat_id, chat)
        assistant_msg = {
            "id": str(uuid.uuid4())[:8],
            "role": "assistant",
            "content": full_response,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "model": model_name,
            "variant": variant,
            "tokens_in": tokens_in,
            "tokens_out": tokens_out,
            "cost": total_cost,
            "enhanced": enhanced,
            "agent_mode": (is_agent_task and has_ssh) or is_lite_agent
        }
        chat2["messages"].append(assistant_msg)
        chat2["total_cost"] = round(chat2.get("total_cost", 0) + total_cost, 4)
        chat2["total_tokens_in"] = chat2.get("total_tokens_in", 0) + tokens_in
        chat2["total_tokens_out"] = chat2.get("total_tokens_out", 0) + tokens_out
        chat2["model_used"] = model_name
        chat2["model"] = model_name  # BUG-ANA-03 FIX: also write to 'model' field (SQLite column)
        chat2["variant"] = variant
        db2["chats"][chat_id] = chat2

        # Update user spending
        user2 = db2["users"].get(_saved_user_id, {})
        user2["total_spent"] = round(user2.get("total_spent", 0) + total_cost, 4)
        db2["users"][_saved_user_id] = user2

        # Update global analytics
        analytics = db2.get("analytics", {})
        analytics["total_requests"] = analytics.get("total_requests", 0) + 1
        analytics["total_tokens_in"] = analytics.get("total_tokens_in", 0) + tokens_in
        analytics["total_tokens_out"] = analytics.get("total_tokens_out", 0) + tokens_out
        analytics["total_cost"] = round(analytics.get("total_cost", 0) + total_cost, 4)

        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        daily = analytics.get("daily_stats", {})
        if today not in daily:
            daily[today] = {"requests": 0, "cost": 0.0, "tokens_in": 0, "tokens_out": 0}
        daily[today]["requests"] += 1
        daily[today]["cost"] = round(daily[today]["cost"] + total_cost, 4)
        daily[today]["tokens_in"] += tokens_in
        daily[today]["tokens_out"] += tokens_out
        analytics["daily_stats"] = daily
        db2["analytics"] = analytics

        # Save memory (episodic) — legacy JSON memory
        memory = db2.get("memory", {"episodic": [], "semantic": {}, "procedural": {}})
        memory["episodic"].append({
            "task": user_message[:200],
            "result_preview": full_response[:200],
            "cost": total_cost,
            "variant": variant,
            "enhanced": enhanced,
            "agent_mode": (is_agent_task and has_ssh) or is_lite_agent,
            "timestamp": now,
            "user_id": _saved_user_id,
            "success": "❌" not in full_response[:100]
        })
        if len(memory["episodic"]) > 1000:
            memory["episodic"] = memory["episodic"][-1000:]
        db2["memory"] = memory

        # Save to vector memory (long-term, cross-chat)
        try:
            vmem = _get_memory()
            vmem.store_from_conversation(
                user_message=user_message,
                assistant_response=full_response[:500],
                chat_id=chat_id,
                user_id=_saved_user_id
            )
        except Exception as _nc_err:
            logging.warning(f"Non-critical error: {_nc_err}")

        # ── BUG-5 FIX v3: memory_v9 after_chat — сохраняем факты для ВСЕХ режимов ──
        try:
            _mem_logger = logging.getLogger("memory.engine")

            # Сохраняем через agent.memory если агент был создан
            _agent_memory_saved = False
            _agent_ref = locals().get("agent", None)
            if _agent_ref is not None and hasattr(_agent_ref, "memory") and _agent_ref.memory is not None:
                _agent_ref.memory.after_chat(
                    user_message=user_message,
                    full_response=full_response,
                    chat_id=chat_id,
                    success="❌" not in full_response[:100]
                )
                _agent_memory_saved = True
                _mem_logger.info(f"[MEMORY] after_chat via agent.memory: OK, user={_saved_user_id!r}")

            # Для CHAT MODE (без агента) — сохраняем напрямую через memory_v9
            if not _agent_memory_saved and full_response:
                try:
                    def _mem_call_llm_save(msgs):
                        try:
                            _r = http_requests.post(
                                OPENROUTER_BASE_URL,
                                headers={"Authorization": f"Bearer {OPENROUTER_API_KEY}", "Content-Type": "application/json"},
                                json={"model": "openai/gpt-5.4-mini", "messages": msgs, "temperature": 0.1, "max_tokens": 512},  # PATCH fix2
                                timeout=15
                            )
                            return _r.json()["choices"][0]["message"]["content"]
                        except Exception as _e:
                            return ""

                    from memory_v9 import SuperMemoryEngine
                    # Передаём call_llm_func — без него extract_from_chat не работает!
                    _mem_v9_save = SuperMemoryEngine(call_llm_func=_mem_call_llm_save)
                    _mem_v9_save.init_task(
                        user_message=user_message,
                        user_id=_saved_user_id,
                        chat_id=chat_id,
                        api_key=OPENROUTER_API_KEY,
                        api_url=OPENROUTER_BASE_URL
                    )
                    _mem_v9_save.after_chat(
                        user_message=user_message,
                        full_response=full_response,
                        chat_id=chat_id,
                        success="❌" not in full_response[:100]
                    )
                    _mem_logger.info(f"[MEMORY] after_chat SAVE OK: user={_saved_user_id!r}, msg={user_message[:60]!r}")
                except Exception as _direct_err:
                    _mem_logger.warning(f"[MEMORY] direct memory_v9 after_chat failed: {_direct_err}", exc_info=True)
        except Exception as _ac_err:
            logging.getLogger("memory.engine").error(f"[MEMORY] after_chat EXCEPTION: {_ac_err}", exc_info=True)

        db_write(db2)

        # Send completion event with routing info
        # КРИТ-2 FIX: отдельное событие 'cost' для frontend
        yield f"data: {json.dumps({'type': 'cost', 'cost': total_cost, 'tokens_in': tokens_in, 'tokens_out': tokens_out})}\n\n"
        yield f"data: {json.dumps({'type': 'done', 'tokens_in': tokens_in, 'tokens_out': tokens_out, 'cost': total_cost, 'model': agent_model_name, 'tier': routed_tier, 'complexity': routed_complexity})}\n\n"

        # ══ TASK PERSISTENCE: mark task as done ══
        with _tasks_lock:
            task = _running_tasks.get(chat_id)
            if task:
                task["status"] = "done"
                _cleanup_running_task(chat_id)
                task["finished_at"] = time.time()

    # ══ TURBO BACKGROUND THREAD: agent runs in background, SSE reads from queue ══
    # This ensures GeneratorExit (client disconnect) does NOT kill the Turbo agent
    import queue as _turbo_queue_module

    # Pre-create task entry with queue BEFORE generate() runs
    _turbo_q = _turbo_queue_module.Queue()
    with _tasks_lock:
        task = _running_tasks.get(chat_id)
        if task:
            task["_queue"] = _turbo_q
        else:
            _running_tasks[chat_id] = {
                "status": "running",
                "events": [],
                "started_at": time.time(),
                "user_id": _saved_user_id,
                "message": user_message[:100],
                    "events": [],
                "_queue": _turbo_q,
            }

    def _turbo_background_worker():
        """Runs Turbo generate() in background thread, puts events into queue."""
        _q = _turbo_q  # Use pre-created queue directly
        if not _q:
            logging.error(f"[TURBO BG] No queue for chat {chat_id}")
            return
        logging.info(f"[TURBO BG] Worker started for chat {chat_id}")
        try:
            for event in generate():
                # PATCH 14: Check if interrupt was requested
                with _interrupt_lock:
                    task_entry = _running_tasks.get(chat_id, {})
                    if task_entry.get("_interrupt_requested"):
                        logging.info(f"[PATCH14] Interrupt detected for chat {chat_id}, stopping agent")
                        _intr_evt = json.dumps({'type': 'interrupted', 'text': '⚡ Прервано — переключаюсь на новую задачу'})
                        _q.put("data: " + _intr_evt + "\n\n")
                        break
                    # PATCH 14: Inject appended messages into next iteration
                    _appended = task_entry.pop("_append_msgs", [])
                    if _appended:
                        for _amsg in _appended:
                            _append_evt = json.dumps({'type': 'content', 'text': '📩 Добавлено: ' + _amsg[:80]})
                            _q.put("data: " + _append_evt + "\n\n")
                # Buffer event for reconnect
                with _tasks_lock:
                    task = _running_tasks.get(chat_id)
                    if task:
                        task["events"].append(event)
                _q.put(event)
        except Exception as e:
            logging.error(f"[TURBO BG] Error: {e}")
            _q.put(f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n")
        finally:
            if _q:
                _q.put(None)  # Sentinel: stream ended
            logging.info(f"[TURBO BG] Worker finished for chat {chat_id}")
            # PATCH 14: After task done, process queue
            _process_message_queue(chat_id, _saved_user_id)

    _turbo_bg_thread = threading.Thread(target=_turbo_background_worker, daemon=True, name=f"turbo-agent-{chat_id[:8]}")
    _turbo_bg_thread.start()

    def _turbo_sse_stream():
        """SSE stream that reads from queue. Survives client reconnects."""
        _q = _turbo_q  # Use pre-created queue directly
        if not _q:
            return
        try:
            while True:
                try:
                    event = _q.get(timeout=30)  # 30s timeout per event
                    if event is None:  # Sentinel: stream ended
                        break
                    yield event
                except _turbo_queue_module.Empty:
                    # Check if task is still running
                    with _tasks_lock:
                        task = _running_tasks.get(chat_id)
                    if not task or task.get("status") == "done":
                        break
                    # Send keepalive
                    yield ": keepalive\n\n"
        except GeneratorExit:
            logging.info(f"[TURBO SSE] Client disconnected from chat {chat_id}, agent continues in background")
            # Do NOT stop the agent - it continues in background thread

    return Response(
        stream_with_context(_turbo_sse_stream()),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"
        }
    )



@agent_bp.route("/api/chats/<chat_id>/stop", methods=["POST"])
@require_auth
def stop_agent(chat_id):
    """Stop a running agent loop."""
    with _agents_lock:
        agent = _active_agents.get(chat_id)
        if agent:
            agent.stop()
            return jsonify({"ok": True, "message": "Agent stop requested"})
    return jsonify({"ok": False, "message": "No active agent for this chat"})



@agent_bp.route("/api/chats/<chat_id>/status", methods=["GET"])
@require_auth
def get_chat_task_status(chat_id):
    """Return the current task status for a chat (running/done/none)."""
    with _tasks_lock:
        task = _running_tasks.get(chat_id)
        if not task:
            return jsonify({"status": "none", "events_count": 0})
        return jsonify({
            "status": task["status"],
            "events_count": len(task["events"]),
            "started_at": task.get("started_at", 0),
            "message": task.get("message", ""),
        })



@agent_bp.route("/api/chats/<chat_id>/reconnect", methods=["GET"])
@require_auth
def reconnect_task_stream(chat_id):
    """Reconnect to a running task: replay buffered events, then wait for new ones."""
    with _tasks_lock:
        task = _running_tasks.get(chat_id)
        if not task:
            return jsonify({"error": "No running task for this chat"}), 404

    def replay_and_follow():
        # Phase 1: replay all buffered events
        sent = 0
        with _tasks_lock:
            task = _running_tasks.get(chat_id)
            if task:
                for event in task["events"]:
                    yield event
                    sent += 1
        
        # Phase 2: if task is still running, poll for new events
        if task and task["status"] == "running":
            import time as _time
            max_wait = 300  # 5 min max
            start = _time.time()
            while _time.time() - start < max_wait:
                _time.sleep(0.3)
                with _tasks_lock:
                    task = _running_tasks.get(chat_id)
                    if not task:
                        break
                    current_len = len(task["events"])
                    if current_len > sent:
                        for event in task["events"][sent:current_len]:
                            yield event
                        sent = current_len
                    if task["status"] == "done":
                        # Send any remaining events
                        for event in task["events"][sent:]:
                            yield event
                        break

    return Response(
        stream_with_context(replay_and_follow()),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"
        }
    )


# ── /api/chat — прямой роут (фронтенд v2.0 шлёт сюда) ────────

@agent_bp.route("/api/chat", methods=["POST"])
@agent_bp.route("/api/chat/multi-agent", methods=["POST"])
@require_auth
def direct_chat():
    """Direct chat endpoint: auto-creates chat if needed, then streams response."""
    import uuid as _uuid
    data = request.get_json() or {}
    user_message = data.get("message", "").strip()
    file_content = data.get("file_content", "")
    # ── Extract chat_id early (needed for interrupt check) ──
    chat_id = data.get("chat_id")
    # ── BUG-1 FIX: Extract and normalize orion_mode ──
    _raw_mode = data.get("mode") or "fast"
    _MODE_NORMALIZE = {
        "auto": "auto", 
        "turbo-basic": "fast", "turbo_basic": "fast", "fast": "fast",
        "turbo-premium": "fast",
        "pro-basic": "standard", "pro_basic": "standard", "standard": "standard",
        "pro-premium": "premium", "premium": "premium",
    }
    orion_mode = _MODE_NORMALIZE.get(_raw_mode, "fast")
    
    # ══ PATCH 14 FIX: Interrupt / Queue / Append for send_message route ══
    with _tasks_lock:
        _existing_task = _running_tasks.get(chat_id) if chat_id else None
        _task_is_running = _existing_task and _existing_task.get("status") == "running"
    if _task_is_running:
        _msg_type = _classify_interrupt_message(user_message)
        if _msg_type == "queue":
            with _interrupt_lock:
                if chat_id not in _message_queue:
                    _message_queue[chat_id] = []
                _message_queue[chat_id].append({
                    "message": user_message, "mode": orion_mode,
                    "user_id": request.user_id, "file_content": file_content
                })
            logging.info(f"[PATCH14-SEND] chat={chat_id} → QUEUED: {user_message[:60]}")
            return Response(
                f"data: {json.dumps({'type': 'queued', 'text': '🕐 В очереди — возьму после текущей задачи'})}\n\n"
                f"data: {json.dumps({'type': 'done'})}\n\n",
                mimetype="text/event-stream",
                headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
            )
        elif _msg_type == "append":
            with _tasks_lock:
                task_entry = _running_tasks.get(chat_id, {})
                if "_append_msgs" not in task_entry:
                    task_entry["_append_msgs"] = []
                task_entry["_append_msgs"].append(user_message)
            logging.info(f"[PATCH14-SEND] chat={chat_id} → APPENDED: {user_message[:60]}")
            return Response(
                f"data: {json.dumps({'type': 'appended', 'text': '📩 Добавлено к текущей задаче'})}\n\n"
                f"data: {json.dumps({'type': 'done'})}\n\n",
                mimetype="text/event-stream",
                headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
            )
        else:  # interrupt
            with _tasks_lock:
                if _existing_task:
                    _existing_task["_interrupt_requested"] = True
                    _existing_task["_interrupt_msg"] = user_message
            logging.info(f"[PATCH14-SEND] chat={chat_id} → INTERRUPT: {user_message[:60]}")
            # Fall through to normal processing — will start new task
    # ═══ АВТОРЕЖИМ: определяем модель по сложности сообщения ═══
    _auto_resolved_mode = None
    if orion_mode == "auto":
        _msg_lower = user_message.lower()
        _msg_len = len(user_message)
        # Opus keywords — очень сложные задачи
        _opus_kw = ["архитектур", "аудит", "спроектируй", "crm с нуля", "erp", 
                     "микросервис", "рефакторинг всего", "code review всего проекта",
                     "проанализируй весь код", "спроектируй систему"]
        # Sonnet keywords — сложные задачи с деплоем/сайтами
        _sonnet_kw = ["сделай сайт", "создай сайт", "лендинг", "деплой", "deploy",
                      "сервер", "ssh", "ftp", "nginx", "docker", "создай приложение",
                      "сделай приложение", "разверни", "настрой ssl", "certbot",
                      "создай api", "rest api", "fullstack", "бэкенд", "backend",
                      "dns", "домен", "хостинг", "beget", "vps", "сайт-визитк",
                      "интернет-магазин", "портал", "дашборд", "dashboard"]
        if any(kw in _msg_lower for kw in _opus_kw):
            orion_mode = "premium"
            _auto_resolved_mode = "premium"
            logging.info(f"[AUTO MODE] → architect (Opus keywords detected)")
        elif any(kw in _msg_lower for kw in _sonnet_kw) or _msg_len > 200:
            orion_mode = "standard"
            _auto_resolved_mode = "standard"
            logging.info(f"[AUTO MODE] → standard (Sonnet keywords or long message)")
        else:
            orion_mode = "fast"
            _auto_resolved_mode = "fast"
            logging.info(f"[AUTO MODE] → fast (simple message)")
    logging.info(f"[send_message] orion_mode={orion_mode} (raw={_raw_mode})")
    chat_id = data.get("chat_id")

    if not user_message and not file_content:
        return jsonify({"error": "Message required"}), 400

    db = db_read()

    # Создаём чат если не передан или не существует
    if not chat_id or chat_id not in db["chats"]:
        chat_id = str(_uuid.uuid4())
        title = user_message[:50] if user_message else "Новый чат"
        db["chats"][chat_id] = {
            "id": chat_id,
            "user_id": request.user_id,
            "title": title,
            "messages": [],
            "created_at": time.time(),
            "updated_at": time.time(),
            "total_cost": 0.0,
            "mode": orion_mode,
        }
        db_write(db)

    # Проверяем доступ
    chat = db["chats"].get(chat_id)
    if chat.get("user_id") != request.user_id and request.user.get("role") != "admin":
        return jsonify({"error": "Access denied"}), 403

    # Rate limiting
    rl = _get_rate_limiter()
    allowed, rl_info = rl.check_message(request.user_id)
    if not allowed:
        return jsonify({"error": "Rate limit exceeded", "retry_after": rl_info.get("retry_after", 60)}), 429

    # Spending limit
    _user_data = db["users"].get(request.user_id, {})
    _monthly_limit = _user_data.get("monthly_limit", 999999)
    _total_spent = _user_data.get("total_spent", 0.0)
    if _monthly_limit and _monthly_limit < 999999 and _total_spent >= _monthly_limit:
        return jsonify({"error": "spending_limit_exceeded", "message": "Лимит исчерпан."}), 402

    # ══ PATCH 14: Interrupt / Queue / Append logic ══
    with _interrupt_lock:
        _existing_task = _running_tasks.get(chat_id)
        _task_is_running = _existing_task and _existing_task.get("status") == "running"

    if _task_is_running:
        _msg_type = _classify_interrupt_message(user_message)

        if _msg_type == "queue":
            # Add to queue — agent will process after current task
            with _interrupt_lock:
                if chat_id not in _message_queue:
                    _message_queue[chat_id] = []
                _message_queue[chat_id].append({
                    "message": user_message, "mode": orion_mode,
                    "user_id": request.user_id, "file_content": file_content
                })
            logging.info(f"[PATCH14] chat={chat_id} → QUEUED: {user_message[:60]}")
            return Response(
                f"data: {json.dumps({'type': 'queued', 'text': '🕐 В очереди — возьму после текущей задачи'})}\n\n"
                f"data: {json.dumps({'type': 'done'})}\n\n",
                mimetype="text/event-stream",
                headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
            )

        elif _msg_type == "append":
            # Append to current task — inject into running agent's next iteration
            with _interrupt_lock:
                task_entry = _running_tasks.get(chat_id, {})
                if "_append_msgs" not in task_entry:
                    task_entry["_append_msgs"] = []
                task_entry["_append_msgs"].append(user_message)
            logging.info(f"[PATCH14] chat={chat_id} → APPENDED: {user_message[:60]}")
            return Response(
                f"data: {json.dumps({'type': 'appended', 'text': '📩 Добавлено к текущей задаче'})}\n\n"
                f"data: {json.dumps({'type': 'done'})}\n\n",
                mimetype="text/event-stream",
                headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
            )

        else:  # interrupt
            # Pause current task, save state, start new task
            logging.info(f"[PATCH14] chat={chat_id} → INTERRUPT: pausing current task")
            with _interrupt_lock:
                task_entry = _running_tasks.get(chat_id, {})
                # Signal the running agent to stop
                task_entry["_interrupt_requested"] = True
                # Also call agent.stop() to set _stop_requested flag in AgentLoop
                with _agents_lock:
                    _agent_to_stop = _active_agents.get(chat_id)
                    if _agent_to_stop:
                        try:
                            _agent_to_stop.stop()
                        except Exception:
                            pass
                # Save paused state
                _paused_tasks[chat_id] = {
                    "user_id": request.user_id,
                    "task": task_entry.get("message", ""),
                    "mode": task_entry.get("mode", orion_mode),
                    "paused_at": time.time(),
                    "events_count": len(task_entry.get("events", [])),
                }
            # Save to persistent storage
            try:
                from memory_v9.session import SessionMemory
                SessionMemory.save_interrupted(
                    chat_id=chat_id,
                    user_id=request.user_id,
                    task=task_entry.get("message", ""),
                    progress=f"Прервано пользователем на итерации {task_entry.get('iteration', 0)}",
                    reason="user_interrupt"
                )
            except Exception as _si_err:
                logging.warning(f"[PATCH14] save_interrupted failed: {_si_err}")
            # Notify frontend about interrupt
            # (new task will start below in the normal flow)
            logging.info(f"[PATCH14] chat={chat_id} → starting new task: {user_message[:60]}")

    # Сохраняем сообщение пользователя
    msg_id = str(_uuid.uuid4())
    user_msg = {
        "id": msg_id, "role": "user",
        "content": user_message + (f"\n\n[Файл]:\n{file_content}" if file_content else ""),
        "timestamp": time.time()
    }
    db2 = db_read()
    db2["chats"][chat_id]["messages"].append(user_msg)
    db2["chats"][chat_id]["updated_at"] = time.time()
    db_write(db2)

    # Получаем историю (BUG-4 FIX: ограничиваем до 10 сообщений чтобы не переполнять контекст)
    _ctx_limit_v2 = 50 if orion_mode in ("standard", "premium", "premium") else 10
    history = db2["chats"][chat_id]["messages"][-_ctx_limit_v2:]
    user_settings = request.user.get("settings", {})

    # ── SSH credentials: from request, settings, and message text ──
    _ssh_from_request = data.get("ssh", {})
    ssh_credentials = {
        "host": _ssh_from_request.get("ssh_host") or user_settings.get("ssh_host", ""),
        "username": _ssh_from_request.get("ssh_user") or user_settings.get("ssh_user", "root"),
        "password": _ssh_from_request.get("ssh_password") or _decrypt_setting(user_settings.get("ssh_password", "")),
        "port": int(_ssh_from_request.get("ssh_port") or user_settings.get("ssh_port", 22)),
    }
    logger.info(f"[SSH_CRED_DEBUG] host={ssh_credentials.get('host','?')} pwd_len={len(ssh_credentials.get('password',''))} pwd_repr={repr(ssh_credentials.get('password',''))}")
    # Parse SSH from message text (e.g. "root@1.2.3.4 password123 do something")
    ssh_from_msg = _parse_ssh_from_message(user_message)
    if ssh_from_msg:
        if ssh_from_msg.get("host"):
            ssh_credentials["host"] = ssh_from_msg["host"]
        if ssh_from_msg.get("username"):
            ssh_credentials["username"] = ssh_from_msg["username"]
        if ssh_from_msg.get("password"):
            ssh_credentials["password"] = ssh_from_msg["password"]

    # Выбираем модель по режиму
    from model_router import get_model_for_agent
    _agent_cfg = get_model_for_agent("orchestrator", orion_mode)
    model = _agent_cfg.get("model_id", "openai/gpt-5.4-mini")  # PATCH fix2: real model ID
    api_key = OPENROUTER_API_KEY

    def generate():
        from agent_loop import AgentLoop, MultiAgentLoop, _iter_lines_with_timeout
        import json as _json

        assistant_content = ""
        assistant_msg_id = str(_uuid.uuid4())
        SSE = "\n\n"

        # Отправляем chat_id клиенту сразу
        yield "data: " + _json.dumps({"type": "chat_id", "chat_id": chat_id}) + SSE
        # Send auto-generated title to frontend
        try:
            _db = db_read()
            _chat = _db.get("chats", {}).get(chat_id, {})
            _chat_title = _chat.get("title", "")
            if _chat_title and _chat_title != "Новый чат":
                yield "data: " + _json.dumps({"type": "title", "title": _chat_title}) + SSE
        except Exception:
            pass

        try:
            # ── ORION Orchestrator v2: умная маршрутизация ──
            _orch_model_override = None
            _orch_prompt_extra = ""
            _orch_plan = None
            multi_agent = False
            premium_design = (orion_mode == "premium")
            
            # ══ QUICK PATH REMOVED: ALL messages go through orchestrator + agent ══

            if _ORCHESTRATOR_AVAILABLE:
                try:
                    # Функция для вызова LLM из оркестратора
                    def _orch_call_llm(messages, model=None):
                        import requests as _req
                        _model = model or "openai/gpt-5.4-mini"  # PATCH fix2: real model ID
                        resp = _req.post(
                            OPENROUTER_BASE_URL,
                            headers={"Authorization": f"Bearer {OPENROUTER_API_KEY}",
                                     "Content-Type": "application/json"},
                            json={"model": _model, "messages": messages, "max_tokens": 2000},
                            timeout=30
                        )
                        data = resp.json()
                        return data.get("choices", [{}])[0].get("message", {}).get("content", "")
                    
                    # Определить SSH (from settings, request, or parsed from message)
                    _has_ssh = bool(ssh_credentials.get("host") and ssh_credentials.get("password"))
                    _ssh_info = f"host={ssh_credentials.get('host','')}" if _has_ssh else ""
                    
                    # Создать оркестратор и получить план
                    _orch = Orchestrator(_orch_call_llm, orion_mode)
                    _orch_plan = _orch.plan(
                        user_message, 
                        chat_history=history,
                        has_ssh=_has_ssh,
                        ssh_info=_ssh_info
                    )
                    
                    # Отправить план клиенту
                    if _orch_plan and _orch_plan.get("mode") != "chat":
                        yield "data: " + _json.dumps(format_plan_sse(_orch_plan)) + SSE
                    
                    # Если оркестратор хочет спросить пользователя — остановить выполнение
                    if _orch_plan and _orch_plan.get("ask_user"):
                        _question = _orch_plan["ask_user"]
                        # Отправить вопрос как контент сообщения (видно в чате)
                        yield "data: " + _json.dumps({
                            "type": "content",
                            "text": "❓ " + _question
                        }) + SSE
                        # Также отправить ask_user для фронтенда
                        yield "data: " + _json.dumps({
                            "type": "ask_user",
                            "question": _question
                        }) + SSE
                        # Сохранить вопрос как ответ ассистента и завершить стрим
                        assistant_content = "❓ " + _question
                        yield "data: " + _json.dumps({"type": "done", "content": assistant_content}) + SSE
                        return
                    
                    # Определить модель и промпт из плана
                    if _orch_plan:
                        _pm = _orch_plan.get("primary_model", "")
                        _pa = _orch_plan.get("primary_agent", "")
                        
                        # PATCHED: Do NOT override model from orchestrator primary_model
                        if _pm:
                            logging.info(f"[ORCH] primary_model={_pm} (ignored, using mode-based model)")
                            _orch_model_override = None
                        
                        if _pa and _pa in AGENT_PROMPTS:
                            _orch_prompt_extra = AGENT_PROMPTS[_pa]
                        
                        if _orch_plan.get("mode") in ("multi_sequential", "multi_parallel"):
                            multi_agent = True
                    
                    logger.info(f"Orchestrator: mode={_orch_plan.get('mode')}, model={_orch_model_override}, agent={_orch_plan.get('primary_agent')}")
                    
                except Exception as _orch_e:
                    logger.warning(f"Orchestrator failed, using default: {_orch_e}")
            
            # ── Создание AgentLoop с учётом оркестратора ──
            _final_model = _orch_model_override or model
            
            if multi_agent:
                loop = MultiAgentLoop(
                    model=_final_model, api_key=api_key,
                    orion_mode=orion_mode,
                premium_design=premium_design, session_id=chat_id
                )
            else:
                loop = AgentLoop(
                    model=_final_model, api_key=api_key,
                    orion_mode=orion_mode, session_id=chat_id
                )
            
            # Передать промпт агента и план
            if _orch_prompt_extra:
                loop._orchestrator_prompt = _orch_prompt_extra
            if _orch_plan:
                loop._orchestrator_plan = _orch_plan

            with _agents_lock:
                _active_agents[chat_id] = loop

            for raw_event in loop.run_stream(user_message, chat_history=history, file_content=file_content, ssh_credentials=ssh_credentials):
                # BUG-4 FIX: wrap each event in try/except to prevent SSE disconnects
                try:
                    # run_stream() возвращает либо строку SSE ("data: {...}\n\n")
                    # либо dict — нормализуем оба варианта
                    if isinstance(raw_event, str):
                        # Уже готовая SSE строка — парсим для накопления текста
                        yield raw_event
                        # Извлекаем content для сохранения
                        if raw_event.startswith("data: "):
                            try:
                                ev = _json.loads(raw_event[6:].strip())
                                ev_type = ev.get("type", "")
                                if ev_type == "content":
                                    assistant_content += ev.get("text", ev.get("content", ""))
                                elif ev_type in ("text", "text_complete"):
                                    assistant_content += ev.get("content", ev.get("text", ""))
                            except Exception as _ev_err:
                                logging.warning(f"Event parse error: {_ev_err}")
                    else:
                        # dict — нормализуем тип и отправляем
                        ev_type = raw_event.get("type", "")
                        if ev_type == "text_delta":
                            raw_event = {"type": "content", "text": raw_event.get("text", raw_event.get("content", ""))}
                        elif ev_type == "text_complete":
                            raw_event = {"type": "content", "text": raw_event.get("content", "")}
                        yield "data: " + _json.dumps(raw_event) + SSE
                        if ev_type in ("content", "text", "text_complete", "text_delta"):
                            assistant_content += raw_event.get("text", raw_event.get("content", ""))
                except GeneratorExit:
                    break
                except Exception as _ev_err:
                    logging.error(f"SSE event error: {_ev_err}")
                    continue
            # Send done event after loop finishes
            try:
                yield "data: " + _json.dumps({"type": "done", "tokens_in": loop.total_tokens_in, "tokens_out": loop.total_tokens_out, "cost": getattr(loop, "_session_cost", 0.0), "model": getattr(loop, "model", "")}) + SSE
            except GeneratorExit:
                pass
            except Exception as _done_err:
                logging.warning(f"Done event error: {_done_err}")

        except GeneratorExit:
            pass  # Клиент отключился — не делаем yield
        except Exception as e:
            import traceback as _tb
            _full_err = _tb.format_exc()
            logging.error("[turbo_worker] CRASH: " + str(e))
            err_msg = "Ошибка агента: " + str(e)
            try:
                yield "data: " + _json.dumps({"type": "error", "content": err_msg}) + SSE
            except GeneratorExit:
                pass
            assistant_content = err_msg
        finally:
            with _agents_lock:
                _active_agents.pop(chat_id, None)
                # ══ PATCH14-FIX: Cleanup _running_tasks ══
                with _tasks_lock:
                    _running_tasks.pop(chat_id, None)

            # Сохраняем ответ ассистента
            if assistant_content:
                asst_msg = {
                    "id": assistant_msg_id, "role": "assistant",
                    "content": assistant_content, "timestamp": time.time()
                }
                db3 = db_read()
                if chat_id in db3["chats"]:
                    db3["chats"][chat_id]["messages"].append(asst_msg)
                    db3["chats"][chat_id]["updated_at"] = time.time()
                    db_write(db3)

            # НЕ делаем yield в finally — это вызывает RuntimeError: generator ignored GeneratorExit


    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Access-Control-Allow-Origin": "*",
        }
    )


# ── Quick Chat (non-streaming for simple questions) ────────────

@agent_bp.route("/api/chat/quick", methods=["POST"])
@require_auth
def quick_chat():
    """Quick non-streaming chat response."""
    data = request.get_json() or {}
    message = data.get("message", "")
    user_settings = request.user.get("settings", {})
    chat_model_key = user_settings.get("chat_model", "qwen3")
    chat_model = CHAT_MODELS.get(chat_model_key, CHAT_MODELS["qwen3"])

    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
    }

    resp = http_requests.post(OPENROUTER_BASE_URL, headers=headers, json={
        "model": chat_model["model"],
        "messages": [
            {"role": "system", "content": "Ты — полезный AI-ассистент. Отвечай кратко и по делу на русском языке."},
            {"role": "user", "content": message}
        ],
        "temperature": 0.5,
        "max_tokens": 2000
    }, timeout=30)

    result = resp.json()
    choices = result.get("choices", [])
    content = choices[0].get("message", {}).get("content", "Ошибка") if choices else "Ошибка: пустой ответ"
    return jsonify({"response": content})


# ── Analytics ──────────────────────────────────────────────────

@agent_bp.route("/api/chats/<chat_id>/subscribe", methods=["GET"])
def subscribe_chat(chat_id):
    """SSE подписка на обновления чата (для совместной работы)."""
    import time as _time
    def stream():
        last_count = 0
        while True:
            db = db_read()
            chat = db["chats"].get(chat_id, {})
            msgs = chat.get("messages", [])
            if len(msgs) > last_count:
                new_msgs = msgs[last_count:]
                for m in new_msgs:
                    yield f"data: {json.dumps({'type': 'new_message', 'message': m}, ensure_ascii=False)}\n\n"
                last_count = len(msgs)
            _time.sleep(2)
    return Response(stream(), mimetype="text/event-stream")



@agent_bp.route("/api/auth-response", methods=["POST"])
def auth_response():
    """
    Пользователь отправляет данные авторизации для browser_ask_auth.
    Данные хранятся временно и используются агентом для browser_fill + browser_submit.
    """
    import time as _time
    data = request.get_json()
    chat_id = data.get("chat_id")
    auth_data = data.get("auth_data", {})
    url = data.get("url", "")
    
    if not chat_id:
        return jsonify({"error": "chat_id required"}), 400
    
    _auth_pending[chat_id] = {
        "auth_data": auth_data,
        "url": url,
        "timestamp": _time.time()
    }
    
    # Очистка старых записей (>5 мин)
    expired = [k for k, v in _auth_pending.items() if _time.time() - v["timestamp"] > 300]
    for k in expired:
        del _auth_pending[k]
    
    return jsonify({"success": True, "message": "Данные получены"})



@agent_bp.route("/api/auth-pending/<chat_id>", methods=["GET"])
def get_auth_pending(chat_id):
    """Агент получает данные авторизации и удаляет их."""
    pending = _auth_pending.pop(chat_id, None)
    if pending:
        return jsonify({"success": True, "auth_data": pending["auth_data"], "url": pending["url"]})
    return jsonify({"success": False, "message": "Нет ожидающих данных"}), 404


