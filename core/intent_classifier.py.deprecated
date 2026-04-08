"""
ARCANE Intent Classifier v2.1
------------------------------
Level 1 of the Orchestrator (spec §7).
Fast LLM call → intent type + complexity + capability flags.

Intent types (12 categories):
  web_design     — create a website, landing page, UI, frontend
  cms_management — maintain/edit CMS (Bitrix, WordPress), content changes on existing sites
  devops         — server setup, install software, SSH, Docker, deploy, DNS, SSL
  coding         — write/fix code, scripts, APIs, backend (no visual website)
  code_review    — audit, review, refactor existing code
  data           — analyze data, charts, spreadsheets, dashboards
  research       — find info, compare, write reports, summarize
  text_content   — copywriting, articles, SEO texts, translations, descriptions
  media          — generate/edit images, video, audio
  automation     — n8n, bots, scheduled tasks, integrations, webhooks
  browser_task   — web scraping, form filling, browser-based workflows
  general        — conversation, questions, everything else

Complexity levels:
  simple   — single step, one model, <5 min
  medium   — multi-step but one domain, 5-30 min
  complex  — multi-domain, needs planner (Level 2), speculative execution

Capability flags:
  needs_ssh       — task requires SSH access to a remote server
  needs_browser   — task requires browser automation (Playwright / Manus)
  needs_image_gen — task requires image generation

Usage:
  from core.intent_classifier import classify_intent
  result = await classify_intent(llm_client, user_message)
  # result = {
  #   "intent": "devops",
  #   "complexity": "medium",
  #   "confidence": 0.97,
  #   "reasoning": "...",
  #   "needs_ssh": True,
  #   "needs_browser": False,
  #   "needs_image_gen": False,
  #   "source": "llm",
  # }
"""

import asyncio
import hashlib
import json
import logging
import os
import re
import time
from shared.models.schemas import LLMRequest
from typing import Optional

logger = logging.getLogger(__name__)

# ── Configuration ──────────────────────────────────────────────────────
CLASSIFIER_MODEL = os.getenv("ARCANE_CLASSIFIER_MODEL", "gpt-4.1-nano")
CLASSIFIER_TIMEOUT = int(os.getenv("ARCANE_CLASSIFIER_TIMEOUT", "15"))
CLASSIFIER_MAX_INPUT_CHARS = 600  # total user content cap for cheap classifier

# ── All valid intents ──────────────────────────────────────────────────
VALID_INTENTS = frozenset({
    "web_design", "cms_management", "devops", "coding", "code_review",
    "data", "research", "text_content", "media", "automation",
    "browser_task", "general",
})

VALID_COMPLEXITIES = frozenset({"simple", "medium", "complex"})

# ── Simple in-memory cache (TTL-based) ─────────────────────────────────
_cache: dict[str, tuple[dict, float]] = {}
_CACHE_TTL = 60.0  # seconds
_CACHE_MAX_SIZE = 200


# ── PII patterns to redact from chat history before sending to LLM ─────
_PII_PATTERNS = re.compile(
    r"(?:\d{1,3}\.){3}\d{1,3}"                                        # IPv4
    r"|[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z]{2,}"                 # email
    r"|(?:password|пароль|pass|token|secret|ключ|api.?key)\s*[:=]\s*\S+"  # secrets
    r"|ssh\s+\S+@\S+",                                                 # ssh user@host
    re.IGNORECASE,
)


def _redact_pii(text: str) -> str:
    """Replace PII/secrets with [REDACTED] before passing to classifier."""
    return _PII_PATTERNS.sub("[REDACTED]", text)


# ── Metrics counter (in-process; plug into Prometheus/StatsD externally) ─
_metrics = {
    "classify_total": 0,
    "classify_llm_ok": 0,
    "classify_llm_fail": 0,
    "classify_fallback": 0,
    "classify_cache_hit": 0,
}


def get_classifier_metrics() -> dict:
    """Return a snapshot of classifier metrics for observability."""
    return dict(_metrics)


# ── System prompt for Level 1 Classifier ───────────────────────────────
INTENT_SYSTEM_PROMPT = """You are a task intent classifier for an AI development agency.
Analyze the user's message and determine: intent type, complexity, and required capabilities.

Return ONLY a JSON object (no markdown, no backticks):
{
  "intent": "<type>",
  "complexity": "<simple|medium|complex>",
  "confidence": <0.0-1.0>,
  "reasoning": "<one sentence>",
  "needs_ssh": <true|false>,
  "needs_browser": <true|false>,
  "needs_image_gen": <true|false>
}

═══ INTENT TYPES ═══

web_design — CREATE a new website, landing page, UI, frontend, HTML page, portfolio
cms_management — MAINTAIN/EDIT an existing CMS site (Bitrix, WordPress, Joomla): change content, fix templates, add pages to existing site, update plugins
devops — Server setup, install/configure software ON A SERVER, SSH, Docker, Nginx, databases, Linux admin, deploy, DNS, SSL, monitoring
coding — Write/fix code, scripts, APIs, backend, bots — without creating a visual website or managing a server
code_review — Audit, review, refactor existing code, find bugs in provided code, security analysis
data — Analyze data, create charts, Excel/CSV processing, dashboards, reports from data
research — Find information, compare options, investigate topics, summarize documents
text_content — Copywriting, write articles, product descriptions, SEO texts, translations, emails
media — Generate/edit images, video, audio, design assets
automation — n8n workflows, Telegram bots (deploy+logic), scheduled tasks, API integrations, webhooks
browser_task — Web scraping, fill forms on websites, take screenshots, test websites in browser, register accounts, any task that needs a real browser
general — Conversation, simple questions, help, explanation, everything else

═══ COMPLEXITY RULES ═══

simple — Single clear action, one domain. "Write a function", "Fix this CSS", "What is X?"
medium — Multiple steps in one domain. "Build a landing page", "Set up Nginx + PHP + MySQL", "Write a Telegram bot"
complex — Multiple domains, multiple agents needed, or requires planning + speculative execution. "Build a full web app with backend, frontend, and deploy", "Migrate a site from shared hosting to VPS with DNS change", "Create a corporate site with CMS, custom design, and SEO"

═══ CAPABILITY FLAGS ═══

needs_ssh: true if the task mentions a remote server, VPS, IP address, SSH, or requires executing commands on a remote machine. Installing software on a server = true. Writing code locally = false.
needs_browser: true if the task requires interacting with web pages (scraping, form filling, screenshots, testing in browser, registering accounts, purchasing domains). Creating HTML locally = false.
needs_image_gen: true if the task requires generating new images, photos, illustrations, logos, icons. Using existing images = false. Writing about images = false.

═══ CRITICAL DISTINCTIONS ═══

- "Install Bitrix/WordPress on a server" = devops (installing software), needs_ssh=true
- "Fix a page in our Bitrix/WordPress site" = cms_management, needs_ssh=true
- "Create a landing page" = web_design, needs_ssh=false
- "Deploy a site to VPS" = devops, needs_ssh=true
- "Review my code for bugs" = code_review
- "Write a blog post about AI" = text_content
- "Research AI trends and write a report" = research
- "Make a Telegram bot and deploy it" = automation, complexity=medium, needs_ssh=true
- "Scrape prices from competitors" = browser_task, needs_browser=true
- "Build a full e-commerce site" = web_design, complexity=complex, needs_image_gen=true
- "Create a landing with custom photos" = web_design, needs_image_gen=true

═══ EXAMPLES ═══

User: "установи битрикс на сервер 45.67.57.175"
{"intent":"devops","complexity":"medium","confidence":0.99,"reasoning":"Installing CMS software on a remote server","needs_ssh":true,"needs_browser":false,"needs_image_gen":false}

User: "поправь заголовок на главной странице нашего сайта на битриксе"
{"intent":"cms_management","complexity":"simple","confidence":0.95,"reasoning":"Editing content on existing Bitrix site","needs_ssh":true,"needs_browser":false,"needs_image_gen":false}

User: "сделай лендинг для моей кофейни с красивыми фото"
{"intent":"web_design","complexity":"medium","confidence":0.97,"reasoning":"Creating a landing page with image generation","needs_ssh":false,"needs_browser":false,"needs_image_gen":true}

User: "проверь мой код на баги и уязвимости"
{"intent":"code_review","complexity":"simple","confidence":0.95,"reasoning":"Code audit and security review","needs_ssh":false,"needs_browser":false,"needs_image_gen":false}

User: "напиши статью про тренды в AI на 3000 слов"
{"intent":"text_content","complexity":"simple","confidence":0.93,"reasoning":"Writing a long-form article","needs_ssh":false,"needs_browser":false,"needs_image_gen":false}

User: "спарси цены конкурентов с сайта example.com"
{"intent":"browser_task","complexity":"medium","confidence":0.96,"reasoning":"Web scraping requires browser automation","needs_ssh":false,"needs_browser":true,"needs_image_gen":false}

User: "построй полный сайт с бэкендом, фронтом, деплой на VPS и SEO-тексты"
{"intent":"web_design","complexity":"complex","confidence":0.98,"reasoning":"Full-stack site with deploy and content — multi-domain task","needs_ssh":true,"needs_browser":false,"needs_image_gen":true}
"""


# ── Helpers ────────────────────────────────────────────────────────────

def _coerce_bool(value) -> bool:
    """
    Safely coerce LLM output to bool.
    Handles: True, False, "true", "false", "0", "1", 0, 1, None.
    FIX: bool("false") == True in Python — this function handles it correctly.
    """
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        return value.strip().lower() in ("true", "1", "yes")
    return False


def _safe_float(value, default: float = 0.5) -> float:
    """
    Safely parse confidence from LLM output.
    Handles: 0.97, "0.97", "high", None, missing.
    FIX: float("high") → ValueError is now caught.
    """
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except (ValueError, TypeError):
            # LLM returned "high", "medium", "low" as string
            mapping = {"high": 0.95, "medium": 0.7, "low": 0.3}
            return mapping.get(value.strip().lower(), default)
    return default


def _extract_json(content: str) -> str:
    """
    Extract JSON object from LLM response.
    FIX: Uses regex instead of fragile split('```') that breaks on backticks in text.
    """
    # Try regex for fenced code block first
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", content, re.DOTALL)
    if m:
        return m.group(1)
    # Fallback: find outermost { ... }
    start = content.find("{")
    end = content.rfind("}")
    if start != -1 and end > start:
        return content[start: end + 1]
    return content


def _build_context_hint(chat_id: str) -> str:
    """
    Build context from chat history for better classification.
    FIX: Redacts PII before sending to classifier.
    FIX: Caps total length to prevent input overflow.
    """
    try:
        from api.chat_store import get_messages as _get_msgs
        _prev = _get_msgs(chat_id)
        if not _prev:
            return ""
        hints = []
        for _m in _prev[-4:]:  # 4 messages × 80 chars = ~320 chars max
            role = _m.get("role", "")
            content = _m.get("content", "")[:80]
            if role in ("user", "assistant"):
                hints.append(f"{role.capitalize()}: {_redact_pii(content)}")
        if not hints:
            return ""
        ctx = "\nRecent chat context:\n" + "\n".join(hints) + "\n---\n"
        # Hard cap to prevent context from eating into message budget
        return ctx[:400]
    except Exception:
        return ""


def _cache_key(user_message: str, chat_id: str) -> str:
    """Deterministic cache key for (message, chat) pair."""
    raw = f"{chat_id}:{user_message[:500]}"
    return hashlib.md5(raw.encode()).hexdigest()


def _cache_get(key: str) -> Optional[dict]:
    """Get from cache if not expired."""
    entry = _cache.get(key)
    if entry is None:
        return None
    result, ts = entry
    if time.monotonic() - ts > _CACHE_TTL:
        _cache.pop(key, None)
        return None
    return result


def _cache_set(key: str, result: dict) -> None:
    """Store in cache, evict oldest if full."""
    if len(_cache) >= _CACHE_MAX_SIZE:
        # Evict oldest 25%
        sorted_keys = sorted(_cache, key=lambda k: _cache[k][1])
        for k in sorted_keys[: _CACHE_MAX_SIZE // 4]:
            _cache.pop(k, None)
    _cache[key] = (result, time.monotonic())


def _post_validate(result: dict) -> dict:
    """
    Enforce invariants that must hold regardless of LLM output.
    FIX: browser_task must have needs_browser=True, media should have needs_image_gen=True.
    """
    intent = result["intent"]

    # browser_task ⇒ needs_browser
    if intent == "browser_task":
        result["needs_browser"] = True

    # media ⇒ needs_image_gen (media intent is always about generating visual content)
    if intent == "media":
        result["needs_image_gen"] = True

    return result


# ── Main classifier ────────────────────────────────────────────────────

async def classify_intent(llm_client, user_message: str, chat_id: str = "") -> dict:
    """
    Level 1 Classifier: intent + complexity + capability flags.

    Returns dict with keys: intent, complexity, confidence, reasoning,
    needs_ssh, needs_browser, needs_image_gen, source.

    On LLM failure or timeout, falls back to keyword heuristics.
    The ``source`` field indicates whether the result came from "llm" or "heuristic".
    """
    _metrics["classify_total"] += 1

    # ── Cache check ────────────────────────────────────────────────────
    ck = _cache_key(user_message, chat_id)
    cached = _cache_get(ck)
    if cached is not None:
        _metrics["classify_cache_hit"] += 1
        logger.debug(f"Intent cache hit: {cached['intent']}/{cached['complexity']}")
        return cached

    # ── Try LLM classification with timeout ────────────────────────────
    try:
        result = await asyncio.wait_for(
            _classify_via_llm(llm_client, user_message, chat_id),
            timeout=CLASSIFIER_TIMEOUT,
        )
        _metrics["classify_llm_ok"] += 1
        _cache_set(ck, result)
        return result

    except asyncio.TimeoutError:
        logger.warning(
            f"Intent classifier timed out after {CLASSIFIER_TIMEOUT}s, "
            "using keyword fallback"
        )
        _metrics["classify_llm_fail"] += 1

    except Exception as e:
        logger.warning(f"Intent classification failed: {e}, using keyword fallback")
        _metrics["classify_llm_fail"] += 1

    # ── Keyword fallback ───────────────────────────────────────────────
    _metrics["classify_fallback"] += 1
    result = _keyword_fallback(user_message)
    _cache_set(ck, result)
    return result


async def _classify_via_llm(llm_client, user_message: str, chat_id: str) -> dict:
    """
    Inner LLM call. Separated from classify_intent so asyncio.wait_for
    can wrap it cleanly.
    FIX: sync get_messages runs in asyncio.to_thread to avoid blocking event loop.
    """
    # Build context (sync I/O → run in thread to avoid blocking event loop)
    if chat_id:
        _context_hint = await asyncio.to_thread(_build_context_hint, chat_id)
    else:
        _context_hint = ""

    # Cap total user content to keep classifier input small
    msg_budget = max(100, CLASSIFIER_MAX_INPUT_CHARS - len(_context_hint))
    user_content = _context_hint + user_message[:msg_budget]

    _request = LLMRequest(
        model_id=CLASSIFIER_MODEL,
        messages=[
            {"role": "system", "content": INTENT_SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ],
        temperature=0.0,
        max_tokens=200,
    )
    _resp = await llm_client.complete(_request, role="classifier", worker="intent")
    content = (_resp.content or "").strip()

    # ── Parse JSON from response ───────────────────────────────────────
    json_str = _extract_json(content)
    raw = json.loads(json_str)

    # ── Validate and normalize ─────────────────────────────────────────
    intent = raw.get("intent", "general")
    if intent not in VALID_INTENTS:
        intent = _fuzzy_match_intent(intent)

    complexity = raw.get("complexity", "medium")
    if complexity not in VALID_COMPLEXITIES:
        complexity = "medium"

    confidence = max(0.0, min(1.0, _safe_float(raw.get("confidence"), 0.5)))
    reasoning = str(raw.get("reasoning", ""))[:200]

    result = {
        "intent": intent,
        "complexity": complexity,
        "confidence": confidence,
        "reasoning": reasoning,
        "needs_ssh": _coerce_bool(raw.get("needs_ssh", False)),
        "needs_browser": _coerce_bool(raw.get("needs_browser", False)),
        "needs_image_gen": _coerce_bool(raw.get("needs_image_gen", False)),
        "source": "llm",
    }

    # Post-validate invariants
    result = _post_validate(result)

    logger.info(
        f"Intent classified: {intent}/{complexity} "
        f"(conf={confidence:.2f}, ssh={result['needs_ssh']}, "
        f"browser={result['needs_browser']}, img={result['needs_image_gen']}) "
        f"— {reasoning}"
    )
    return result


# ── Fuzzy matching ─────────────────────────────────────────────────────

def _fuzzy_match_intent(raw_intent: str) -> str:
    """Map common LLM misclassifications to valid intents."""
    aliases = {
        "web": "web_design",
        "website": "web_design",
        "design": "web_design",
        "frontend": "web_design",
        "ui": "web_design",
        "cms": "cms_management",
        "bitrix": "cms_management",
        "wordpress": "cms_management",
        "server": "devops",
        "deploy": "devops",
        "infrastructure": "devops",
        "sysadmin": "devops",
        "code": "coding",
        "backend": "coding",
        "script": "coding",
        "programming": "coding",
        "review": "code_review",
        "audit": "code_review",
        "refactor": "code_review",
        "analysis": "data",
        "analytics": "data",
        "scraping": "browser_task",
        "scrape": "browser_task",
        "browser": "browser_task",
        "text": "text_content",
        "copywriting": "text_content",
        "article": "text_content",
        "image": "media",
        "photo": "media",
        "video": "media",
        "workflow": "automation",
        "n8n": "automation",
        # NOTE: "bot" intentionally omitted — ambiguous between coding and automation.
        # "chart" intentionally omitted — ambiguous between data and web_design.
        # "content" intentionally omitted — ambiguous between text_content and cms.
        # "integration" intentionally omitted — ambiguous between automation and devops.
    }
    normalized = raw_intent.lower().strip().replace("-", "_").replace(" ", "_")
    if normalized in VALID_INTENTS:
        return normalized
    return aliases.get(normalized, "general")


# ── Keyword fallback ───────────────────────────────────────────────────

def _keyword_fallback(user_message: str) -> dict:
    """
    Fallback classifier when LLM call fails or times out.
    Uses multi-word patterns to reduce false positives.

    FIX: per-pattern complexity instead of always "medium".
    FIX: confidence=0.75 so downstream thresholds (>=0.7) still activate.
    FIX: automation can have needs_ssh=True via _mentions_server heuristic.
    FIX: web_design can have needs_image_gen=True via _mentions_images heuristic.
    FIX: CMS patterns include bitrix/wordpress/joomla.
    FIX: Single-word triggers like "python", "javascript", "chart", "function"
         removed — too many false positives in research/discussion context.
    """
    msg = user_message.lower()

    # (keywords, intent, complexity, needs_ssh, needs_browser, needs_image_gen)
    # Order: domain-specific intents BEFORE generic ones (matters for tie-breaks).
    patterns = [
        # browser_task — very specific phrases
        (
            ["спарси", "scrape prices", "web scraping", "скриншот сайта",
             "fill form", "заполни форму на сайте"],
            "browser_task", "medium", False, True, False,
        ),
        # cms_management — CMS-specific + edit-on-site
        (
            ["поправь на сайте", "измени на сайте", "обнови страницу",
             "правки на битрикс", "правки wordpress", "fix on site",
             "edit page on", "битрикс правк", "wordpress правк",
             "обновить шаблон", "joomla правк", "битрикс обнов",
             "wordpress обнов", "правки в cms"],
            "cms_management", "simple", True, False, False,
        ),
        # automation — domain-specific (before devops to win ties like
        # "телеграм бот и задеплой на сервер" where both match 1 keyword)
        (
            ["телеграм бот", "telegram bot", "n8n workflow", "webhook настр",
             "cron задач", "автоматизация процесс", "scheduled task",
             "настрой интеграцию"],
            "automation", "medium", False, False, False,
        ),
        # web_design — creating new sites/pages (before devops to win ties
        # like "создай лендинг и задеплой на сервер")
        (
            ["лендинг", "landing page", "одностранич", "сайт-визитк", "homepage",
             "create website", "сделай сайт", "создай сайт", "build a website",
             "портфолио сайт", "portfolio site", "сверстай страниц"],
            "web_design", "medium", False, False, False,
        ),
        # devops — server/infra keywords (multi-word to avoid "сервер" alone)
        (
            ["установи на сервер", "install on server", "настрой сервер",
             "setup server", "настрой nginx", "настрой docker",
             "deploy на vps", "деплой на", "apt install", "systemctl",
             "certbot", "chmod 777", "ssh root@", "настрой dns",
             "ssl сертификат", "docker compose"],
            "devops", "medium", True, False, False,
        ),
        # code_review — audit/review
        (
            ["review my code", "проверь мой код", "аудит кода", "code audit",
             "найди баги в код", "find bugs in", "code review",
             "рефакторинг код", "security review кода"],
            "code_review", "simple", False, False, False,
        ),
        # coding — writing code (multi-word patterns only)
        (
            ["напиши скрипт", "write script", "напиши код", "write code",
             "напиши функцию", "write function", "api endpoint",
             "write a bot", "напиши бот"],
            "coding", "simple", False, False, False,
        ),
        # text_content
        (
            ["напиши статью", "write article", "копирайтинг", "copywriting",
             "seo текст", "описание товар", "product description",
             "переведи текст", "translate text", "напиши пост"],
            "text_content", "simple", False, False, False,
        ),
        # media — image/video generation
        (
            ["сгенерируй изображ", "generate image", "нарисуй", "create logo",
             "создай логотип", "сделай иконк", "generate icon",
             "сделай фото для", "photo for site"],
            "media", "simple", False, False, True,
        ),
        # data — analysis
        (
            ["анализ данных", "analyze data", "excel файл", "csv файл",
             "построй график", "create chart", "дашборд данных", "dashboard",
             "обработай таблиц"],
            "data", "simple", False, False, False,
        ),
        # research
        (
            ["исследуй тему", "research topic", "сравни варианты",
             "compare options", "найди информацию", "find information",
             "summarize document", "резюмируй", "обзор технологий"],
            "research", "simple", False, False, False,
        ),
    ]

    # Scoring: count keyword hits per intent, pick the highest.
    # On tie (equal hits), first pattern in list wins — that's why
    # domain-specific intents (automation, web_design) are ordered before
    # generic ones (devops) above.
    best = None
    best_hits = 0
    for keywords, intent, complexity, ssh, browser, img in patterns:
        hits = sum(1 for kw in keywords if kw in msg)
        if hits > best_hits:
            best_hits = hits
            best = (intent, complexity, ssh, browser, img)

    if best is not None:
        intent, complexity, ssh, browser, img = best
        result = {
            "intent": intent,
            "complexity": complexity,
            "confidence": 0.75,
            "reasoning": "keyword fallback (LLM unavailable)",
            "needs_ssh": ssh,
            "needs_browser": browser,
            "needs_image_gen": img,
            "source": "heuristic",
        }
        # Extra heuristic: if message mentions server/IP/VPS, set needs_ssh
        if not ssh and _mentions_server(msg):
            result["needs_ssh"] = True
            if intent == "automation":
                result["complexity"] = "medium"
        # Extra heuristic: if web_design and mentions images/photos
        if intent == "web_design" and _mentions_images(msg):
            result["needs_image_gen"] = True

        result = _post_validate(result)
        return result

    return {
        "intent": "general",
        "complexity": "simple",
        "confidence": 0.3,
        "reasoning": "no keywords matched, defaulting to general",
        "needs_ssh": False,
        "needs_browser": False,
        "needs_image_gen": False,
        "source": "heuristic",
    }


def _mentions_server(msg: str) -> bool:
    """Check if message mentions server/VPS/IP address."""
    return bool(
        re.search(r"\b(?:сервер|server|vps|ssh|деплой|deploy)\b", msg)
        or re.search(r"\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}", msg)
    )


def _mentions_images(msg: str) -> bool:
    """Check if message mentions image generation."""
    return bool(re.search(
        r"\b(?:фото|photo|изображ|image|картинк|иллюстрац|illustration|лого|logo)\b", msg
    ))


# ── Backward-compatible helpers (used by agent_runner, agent_loop) ─────

def is_web_design_intent(intent_result: dict) -> bool:
    """Returns True only if the task is genuinely about creating a new website/UI."""
    return (
        intent_result.get("intent") == "web_design"
        and intent_result.get("confidence", 0) >= 0.7
    )


def is_complex_task(intent_result: dict) -> bool:
    """
    Returns True if the task needs Level 2 Planner (spec §7).
    FIX: Requires confidence >= 0.6 to prevent low-confidence complex triggering planner.
    """
    return (
        intent_result.get("complexity") == "complex"
        and intent_result.get("confidence", 0) >= 0.6
    )


def needs_manus(intent_result: dict) -> bool:
    """
    Returns True if the task is best handled by Manus (SSH + browser combo or browser_task).
    FIX: Confidence check on all paths to prevent Manus ($100/mo credits) on uncertain tasks.
    """
    confidence = intent_result.get("confidence", 0)
    if confidence < 0.65:
        return False
    r = intent_result
    # Manus is the only agent with SSH + browser + external services
    if r.get("intent") == "browser_task":
        return True
    if r.get("needs_ssh") and r.get("needs_browser"):
        return True
    return False


def get_execution_flow(intent_result: dict) -> str:
    """
    Determine workspace-first vs SSH-direct vs browser flow (spec §2.5).
    FIX: Added "browser" flow for browser_task intent.
    """
    intent = intent_result.get("intent", "general")
    if intent in ("devops", "cms_management") and intent_result.get("needs_ssh"):
        return "ssh_direct"
    if intent == "browser_task" or intent_result.get("needs_browser"):
        return "browser"
    return "workspace"


def get_strategy_for_intent(intent_result: dict, requested_strategy: str) -> str:
    """
    Determine the best model strategy based on intent.
    Overrides only when necessary — respects user's explicit choice.
    """
    intent = intent_result.get("intent", "general")
    confidence = intent_result.get("confidence", 0.5)

    # Only override if confidence is high enough
    if confidence < 0.7:
        return requested_strategy

    strategy_map = {
        "web_design": "quality",       # needs quality for visual output
        "cms_management": "standard",  # standard for CMS edits
        "devops": "standard",          # standard for server tasks
        "coding": "standard",          # standard for code
        "code_review": "quality",      # quality for thorough review
        "data": "balance",             # balance for data analysis
        "research": "balance",         # balance for research
        "text_content": "balance",     # balance for text tasks
        "media": "quality",            # quality for media generation
        "automation": "standard",      # standard for automation
        "browser_task": "standard",    # standard for browser tasks
        "general": requested_strategy, # keep user's choice
    }

    suggested = strategy_map.get(intent, requested_strategy)

    # Never downgrade from what user explicitly chose
    strategy_rank = {"economy": 0, "balance": 1, "standard": 2, "quality": 3, "maximum": 4}
    if strategy_rank.get(suggested, 2) > strategy_rank.get(requested_strategy, 2):
        return suggested
    return requested_strategy


# ── Dog Racing category mapping (spec §10B.4 / §10B.5) ────────────────
# Categories aligned with spec leaderboard:
#   design  — Дизайн/HTML
#   backend — Backend/API
#   review  — Code review
#   text    — Тексты
#   devops  — DevOps

DOG_RACING_CATEGORIES = {
    "web_design": "design",
    "cms_management": "design",
    "media": "design",
    "coding": "backend",
    "code_review": "review",
    "data": "backend",
    "automation": "backend",
    "devops": "devops",
    "research": "text",
    "text_content": "text",
    "browser_task": "devops",
    "general": "text",
}


def get_dog_racing_category(intent_result: dict) -> str:
    """Map intent to Dog Racing leaderboard category (spec §10B.4)."""
    return DOG_RACING_CATEGORIES.get(intent_result.get("intent", "general"), "text")
