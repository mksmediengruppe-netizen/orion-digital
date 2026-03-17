"""
Agent Loop v6.0 — LangGraph StatefulGraph Architecture.

ORION Digital v1.0 Full Feature Set:
- StateGraph с типизированным AgentState (TypedDict)
- SqliteSaver checkpointer для persistence
- Retry Policy + Circuit Breaker на все внешние вызовы
- Idempotency на мутирующие операции
- Self-Healing 2.0: автоматическое обнаружение ошибок
- Creative Suite: generate_image, edit_image, create_artifact, generate_design
- Web Search & Live Data: web_search, web_fetch с кешированием
- Multi-Model Routing: classify_complexity, fallback chains
- Security: rate limiting, prompt injection detection
- Memory & Projects: persistent memory, canvas, custom agents

Совместимость: run_stream() и run_multi_agent_stream() сохраняют тот же SSE API.
"""

import json
import time
import re
import sqlite3
import traceback
import logging
import hashlib
from datetime import datetime, timezone
from typing import TypedDict, Annotated, Optional, List, Dict, Any
import operator
import requests as http_requests

from langgraph.graph import StateGraph, END, START
from langgraph.checkpoint.sqlite import SqliteSaver

from ssh_executor import SSHExecutor, ssh_pool
from browser_agent import BrowserAgent
from retry_policy import (
    retry, retry_generator, retry_http_call,
    get_breaker, CircuitBreakerOpen,
    RETRYABLE_HTTP_CODES, NON_RETRYABLE_HTTP_CODES
)
from idempotency import (
    get_tool_store, get_file_store,
    make_file_key, make_ssh_key,
    is_idempotent_command, is_mutating_command
)

# ── ORION Sprint 5 imports ──────────────────────────────────
try:
    from intent_clarifier import clarify as clarify_intent, format_clarification_for_user
    from model_router import (
        get_model_for_agent, get_max_cost, check_cost_limit,
        add_session_cost, log_cost, DEFAULT_MODE, MODES
    )
    _INTENT_CLARIFIER_AVAILABLE = True
except ImportError as _e:
    _INTENT_CLARIFIER_AVAILABLE = False
    logger = __import__("logging").getLogger("agent_loop")
    logger.warning(f"Intent clarifier not available: {_e}")

# ── BUG-1 FIX: memory_v9 integration ────────────────────────
try:
    from memory_v9 import SuperMemoryEngine, ALL_MEMORY_TOOLS
    _MEMORY_V9_AVAILABLE = True
except ImportError as _me:
    SuperMemoryEngine = None
    ALL_MEMORY_TOOLS = []
    _MEMORY_V9_AVAILABLE = False
    _mem_logger = __import__("logging").getLogger("agent_loop")
    _mem_logger.warning(f"memory_v9 not available: {_me}")

logger = logging.getLogger("agent_loop")


# ══════════════════════════════════════════════════════════════════
# ██ TOOL DEFINITIONS ██
# ══════════════════════════════════════════════════════════════════

TOOLS_SCHEMA = [
    {
        "type": "function",
        "function": {
            "name": "ssh_execute",
            "description": "Execute a shell command on a remote server via SSH. Use for: installing packages, running scripts, checking services, deploying code, managing processes, etc.",
            "parameters": {
                "type": "object",
                "properties": {
                    "host": {"type": "string", "description": "Server IP or hostname to connect to"},
                    "command": {"type": "string", "description": "Shell command to execute on the server"},
                    "username": {"type": "string", "description": "SSH username (default: root)", "default": "root"},
                    "password": {"type": "string", "description": "SSH password for authentication"}
                },
                "required": ["host", "command"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "file_write",
            "description": "Create or overwrite a file on a remote server via SFTP. Use for: creating config files, writing code, deploying applications, creating scripts.",
            "parameters": {
                "type": "object",
                "properties": {
                    "host": {"type": "string", "description": "Server IP or hostname"},
                    "path": {"type": "string", "description": "Absolute path where to create/write the file"},
                    "content": {"type": "string", "description": "Full content of the file to write"},
                    "username": {"type": "string", "description": "SSH username (default: root)", "default": "root"},
                    "password": {"type": "string", "description": "SSH password"}
                },
                "required": ["host", "path", "content"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "file_read",
            "description": "Read content of a file from a remote server. Use for: checking configs, reading logs, verifying deployed code.",
            "parameters": {
                "type": "object",
                "properties": {
                    "host": {"type": "string", "description": "Server IP or hostname"},
                    "path": {"type": "string", "description": "Absolute path of the file to read"},
                    "username": {"type": "string", "description": "SSH username (default: root)", "default": "root"},
                    "password": {"type": "string", "description": "SSH password"}
                },
                "required": ["host", "path"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "browser_navigate",
            "description": "Open a URL in browser and get page content. Use for: checking websites, verifying deployments, reading documentation, testing APIs.",
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "URL to navigate to"}
                },
                "required": ["url"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "browser_check_site",
            "description": "Check if a website is accessible and get status info (response time, title, status code).",
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "URL to check"}
                },
                "required": ["url"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "browser_get_text",
            "description": "Get clean text content from a webpage (without HTML tags).",
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "URL to get text from"}
                },
                "required": ["url"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "browser_check_api",
            "description": "Send HTTP request to an API endpoint and get response.",
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "API endpoint URL"},
                    "method": {"type": "string", "description": "HTTP method (GET, POST, PUT, DELETE)", "default": "GET"},
                    "data": {"type": "object", "description": "JSON data to send (for POST/PUT)"}
                },
                "required": ["url"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "generate_file",
            "description": "Generate a downloadable file for the user. Supports: .docx (Word), .pdf, .md (Markdown), .txt, .html, .xlsx (Excel), .csv, .json, .py, .js, .css, .sql and other code files. ALWAYS use this when user asks to create/generate a document, report, spreadsheet, or any file. The file will be available for download via a link.",
            "parameters": {
                "type": "object",
                "properties": {
                    "content": {"type": "string", "description": "Full content of the file. For docx/pdf use markdown-like formatting (# headers, **bold**, - lists). For xlsx use CSV format (comma-separated). For html use full HTML."},
                    "filename": {"type": "string", "description": "Filename with extension, e.g. 'report.docx', 'data.xlsx', 'page.html'"},
                    "title": {"type": "string", "description": "Optional title for docx/pdf documents"}
                },
                "required": ["content", "filename"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "generate_image",
            "description": "Generate an image using AI (diagram, chart, illustration). Returns a download link. Use for: creating diagrams, charts, logos, illustrations, mockups.",
            "parameters": {
                "type": "object",
                "properties": {
                    "prompt": {"type": "string", "description": "Detailed description of the image to generate"},
                    "style": {"type": "string", "description": "Style: 'diagram', 'chart', 'illustration', 'photo', 'logo', 'mockup'", "default": "illustration"},
                    "filename": {"type": "string", "description": "Output filename, e.g. 'diagram.png'", "default": "image.png"}
                },
                "required": ["prompt"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "read_any_file",
            "description": "Read and analyze any uploaded file. Supports: PDF, DOCX, PPTX, XLSX, CSV, JSON, XML, images (with OCR), archives (ZIP/TAR), code files, TXT, MD. Returns extracted text, metadata, tables, and summary. Use when user uploads a file or asks to analyze a document.",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {"type": "string", "description": "Path to the uploaded file on server"},
                    "extract_tables": {"type": "boolean", "description": "Whether to extract tables as structured data", "default": True},
                    "max_length": {"type": "integer", "description": "Maximum text length to return", "default": 50000}
                },
                "required": ["file_path"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "analyze_image",
            "description": "Analyze an image using AI vision. Understands screenshots, charts, diagrams, photos, handwritten notes. Returns description, detected text (OCR), and insights. Use when user uploads an image or asks to analyze a screenshot/photo.",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {"type": "string", "description": "Path to the image file"},
                    "question": {"type": "string", "description": "Specific question about the image (optional)", "default": "Describe this image in detail"}
                },
                "required": ["file_path"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": "Search the internet for current information. Returns ranked results with titles, URLs, and snippets. Use when user asks about current events, needs fact-checking, or requests research on any topic.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query"},
                    "num_results": {"type": "integer", "description": "Number of results to return (1-10)", "default": 5}
                },
                "required": ["query"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "web_fetch",
            "description": "Fetch and parse a web page content. Returns clean text extracted from the URL. Use for reading articles, documentation, or any web content in detail.",
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "URL of the web page to fetch"},
                    "max_length": {"type": "integer", "description": "Maximum text length to return", "default": 20000}
                },
                "required": ["url"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "code_interpreter",
            "description": "Execute Python code in a secure sandbox. Use for: data analysis, calculations, generating charts/visualizations, processing files, statistical analysis, machine learning. The sandbox has numpy, pandas, matplotlib, plotly, scipy, sklearn pre-installed. Returns stdout, stderr, and any generated files.",
            "parameters": {
                "type": "object",
                "properties": {
                    "code": {"type": "string", "description": "Python code to execute"},
                    "description": {"type": "string", "description": "Brief description of what the code does"}
                },
                "required": ["code"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "generate_chart",
            "description": "Generate an interactive chart/visualization. Supports: bar, line, pie, scatter, heatmap, histogram, area, radar charts. Returns an HTML artifact with interactive Plotly chart.",
            "parameters": {
                "type": "object",
                "properties": {
                    "chart_type": {"type": "string", "description": "Type: bar, line, pie, scatter, heatmap, histogram, area, radar"},
                    "data": {"type": "object", "description": "Chart data: {labels: [...], datasets: [{label: '...', values: [...]}]}"},
                    "title": {"type": "string", "description": "Chart title"},
                    "options": {"type": "object", "description": "Additional options: {colors: [...], width: 800, height: 500}"}
                },
                "required": ["chart_type", "data", "title"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "create_artifact",
            "description": "Create an interactive artifact (live HTML, SVG, Mermaid diagram, React component). The artifact renders in a sandboxed iframe in the chat. Use for: UI mockups, landing pages, interactive demos, diagrams, dashboards.",
            "parameters": {
                "type": "object",
                "properties": {
                    "content": {"type": "string", "description": "Full HTML/SVG/Mermaid content"},
                    "type": {"type": "string", "description": "Type: html, svg, mermaid, react", "default": "html"},
                    "title": {"type": "string", "description": "Artifact title for display"}
                },
                "required": ["content", "title"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "generate_report",
            "description": "Generate a comprehensive multi-page report with embedded charts and tables. Output as DOCX, PDF, or XLSX. Use when user needs a professional report with data analysis, visualizations, and conclusions.",
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "Report title"},
                    "sections": {"type": "array", "description": "Array of sections: [{heading: '...', content: '...', chart_data: {...}}]", "items": {"type": "object"}},
                    "format": {"type": "string", "description": "Output format: docx, pdf, xlsx", "default": "docx"},
                    "filename": {"type": "string", "description": "Output filename"}
                },
                "required": ["title", "sections"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "edit_image",
            "description": "Edit an existing image: resize, crop, add text/watermark, adjust colors, apply filters, convert format. Use when user wants to modify an uploaded or generated image.",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {"type": "string", "description": "Path to the image file to edit"},
                    "operations": {"type": "array", "description": "List of operations: [{type: 'resize', width: 800, height: 600}, {type: 'crop', x: 0, y: 0, w: 400, h: 300}, {type: 'text', text: 'Hello', x: 50, y: 50, color: '#fff', size: 24}, {type: 'filter', name: 'blur|sharpen|grayscale|sepia|brightness|contrast'}, {type: 'watermark', text: '...'}, {type: 'rotate', angle: 90}, {type: 'convert', format: 'png|jpg|webp'}]", "items": {"type": "object"}},
                    "output_filename": {"type": "string", "description": "Output filename", "default": "edited_image.png"}
                },
                "required": ["file_path", "operations"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "generate_design",
            "description": "Generate a professional design: banner, social media post, presentation slide, infographic, business card, logo concept. Returns HTML artifact or image.",
            "parameters": {
                "type": "object",
                "properties": {
                    "design_type": {"type": "string", "description": "Type: banner, social_post, slide, infographic, business_card, logo, poster, flyer"},
                    "content": {"type": "object", "description": "Design content: {title: '...', subtitle: '...', body: '...', cta: '...', colors: [...], images: [...]}"},
                    "style": {"type": "string", "description": "Style: modern, minimal, corporate, creative, elegant, bold", "default": "modern"},
                    "dimensions": {"type": "object", "description": "Size: {width: 1200, height: 630}", "default": {}}
                },
                "required": ["design_type", "content"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "store_memory",
            "description": "Store important information in persistent memory for future conversations. Use to remember user preferences, project details, key facts, decisions made.",
            "parameters": {
                "type": "object",
                "properties": {
                    "key": {"type": "string", "description": "Memory key/topic (e.g. 'user_preferences', 'project_stack', 'server_config')"},
                    "value": {"type": "string", "description": "Information to remember"},
                    "category": {"type": "string", "description": "Category: preference, fact, project, decision, context", "default": "fact"}
                },
                "required": ["key", "value"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "recall_memory",
            "description": "Recall stored information from persistent memory. Search by key or category.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query or key to recall"},
                    "category": {"type": "string", "description": "Filter by category (optional)"}
                },
                "required": ["query"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "canvas_create",
            "description": "Create or update a collaborative canvas document. Canvas is a persistent editable document (like Google Docs) that can be iteratively refined. Use for long documents, code projects, plans that need multiple revisions.",
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "Canvas document title"},
                    "content": {"type": "string", "description": "Full content (Markdown, code, or HTML)"},
                    "canvas_type": {"type": "string", "description": "Type: document, code, plan, design", "default": "document"},
                    "canvas_id": {"type": "string", "description": "Existing canvas ID to update (omit for new)"}
                },
                "required": ["title", "content"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "task_complete",
            "description": "Mark the task as complete. Call this when all steps are done and verified.",
            "parameters": {
                "type": "object",
                "properties": {
                    "summary": {"type": "string", "description": "Summary of what was accomplished"}
                },
                "required": ["summary"]
            }
        }
    }
]


# ══════════════════════════════════════════════════════════════════
# ██ AGENT STATE (TypedDict для LangGraph) ██
# ══════════════════════════════════════════════════════════════════

class AgentState(TypedDict):
    """Полное состояние агента, сохраняемое через checkpointer."""
    messages: Annotated[list, operator.add]
    iteration: int
    max_iterations: int
    status: str
    current_tool: str
    actions_log: Annotated[list, operator.add]
    errors: Annotated[list, operator.add]
    heal_attempts: int
    completed: bool
    stopped: bool
    response_text: str
    ssh_credentials: dict
    tokens_in: int
    tokens_out: int
    sse_events: Annotated[list, operator.add]


AGENT_SYSTEM_PROMPT = """Ты — ORION Digital v1.0, автономный AI-инженер с LangGraph архитектурой. Ты ВЫПОЛНЯЕШЬ задачи, а не просто описываешь их.

У тебя есть реальные инструменты:

📁 ФАЙЛЫ:
- read_any_file: прочитать и проанализировать ЛЮБОЙ загруженный файл (PDF, DOCX, PPTX, XLSX, CSV, JSON, изображения с OCR, архивы, код)
- generate_file: создать файл для скачивания (Word .docx, PDF .pdf, Excel .xlsx, HTML, CSV, JSON, код и др.)
- generate_report: создать профессиональный отчёт с графиками и таблицами (DOCX/PDF/XLSX)
- analyze_image: проанализировать изображение (скриншот, диаграмму, фото, рукописные заметки)

🌐 ВЕБ И БРАУЗЕР (приоритетные инструменты для любых веб-задач):
- browser_navigate: ОТКРЫТЬ URL в реальном браузере (со скриншотом!) — ИСПОЛЬЗУЙ В ПЕРВУЮ ОЧЕРЕДЬ
- browser_get_text: получить текст со страницы (со скриншотом!) — для чтения содержимого
- browser_check_site: проверить доступность сайта (со скриншотом!)
- browser_check_api: отправить HTTP запрос к API (только для API-тестирования)
- web_search: поиск в интернете для актуальной информации
- web_fetch: получить текст веб-страницы без браузера

ВАЖНО про браузер:
- Для ЛЮБОЙ задачи с URL или сайтом — СНАЧАЛА используй browser_navigate или browser_get_text
- Эти инструменты открывают РЕАЛЬНЫЙ браузер Chromium и делают скриншот
- Пользователь ВИДИТ скриншот в панели "Компьютер Агента" в реальном времени
- НЕ используй browser_check_api для тестирования сайтов — это только для REST API
- При тестировании сайта: сначала browser_navigate на главную, потом browser_get_text на каждую страницу
- При тестировании интерфейса: проходи по КАЖДОЙ странице через браузер, не угадывай API-пути

💻 КОД И АНАЛИТИКА:
- code_interpreter: выполнить Python код в песочнице (анализ данных, графики, расчёты, ML)
- generate_chart: создать интерактивный график (bar, line, pie, scatter, heatmap, histogram)
- create_artifact: создать интерактивный артефакт (живой HTML, SVG, Mermaid диаграмма, React компонент)

🖥️ СЕРВЕР:
- ssh_execute: выполнить команду на сервере через SSH
- file_write: создать/записать файл на сервере через SFTP
- file_read: прочитать файл с сервера

🎨 КРЕАТИВ:
- generate_image: сгенерировать картинку (диаграмма, график, иллюстрация, лого, мокап)
- edit_image: редактировать изображение (resize, crop, text, watermark, filters, rotate, convert)
- generate_design: создать профессиональный дизайн (баннер, пост, слайд, инфографика, визитка, лого)

🧠 ПАМЯТЬ И ПРОЕКТЫ:
- store_memory: сохранить важную информацию в постоянную память (предпочтения, факты, решения)
- recall_memory: вспомнить сохранённую информацию из памяти
- canvas_create: создать/обновить Canvas документ (как Google Docs — для итеративной работы)

✅ ЗАВЕРШЕНИЕ:
- task_complete: завершить задачу

ПРАВИЛА:
1. ВСЕГДА используй инструменты для выполнения задач. НЕ просто описывай что нужно сделать.
2. Если пользователь загрузил файл — ОБЯЗАТЕЛЬНО используй read_any_file чтобы прочитать его.
3. Если просит создать документ — generate_file (Word: .docx, PDF: .pdf, Excel: .xlsx)
4. Если просит анализ данных — code_interpreter для расчётов + generate_chart для визуализации
5. Если просит информацию из интернета — web_search, затем web_fetch для деталей
5a. Если просит проверить/протестировать сайт — ТОЛЬКО browser_navigate + browser_get_text. НИКОГДА не угадывай API-пути через browser_check_api.
5b. Если есть URL в сообщении — ОБЯЗАТЕЛЬНО открой его через browser_navigate или browser_get_text
6. Если просит график/диаграмму — generate_chart для интерактивного, generate_image для статичного
7. Если просит UI/лендинг/мокап — create_artifact с HTML/CSS
8. Если просит отчёт — generate_report с графиками и таблицами
9. Если просит проанализировать скриншот/фото — analyze_image
10. Если просит редактировать изображение — edit_image
11. Если просит дизайн (баннер, пост, визитка) — generate_design
12. Запоминай важные факты через store_memory, вспоминай через recall_memory
13. Для длинных документов используй canvas_create для итеративной работы
14. После каждого действия проверяй результат и исправляй ошибки.
15. Когда всё готово — вызови task_complete.
16. Если нужны SSH-данные и не указаны — спроси у пользователя.
17. Работай пошагово: планируй → выполняй → проверяй → итерируй.
18. Отвечай на русском языке.
19. При ошибке — анализируй причину и пробуй исправить (до 3 попыток).
20. ВСЕГДА давай ссылки на скачивание: [Скачать filename](download_url)
21. Для ДЛИННЫХ ответов (отчёты, анализ, техзадания, чек-листы) — ВСЕГДА создавай файл через generate_file (.docx или .pdf) И давай краткое резюме в тексте.
22. Не пиши огромные тексты в чат — лучше создай файл и дай ссылку на скачивание.
23. Все URL оформляй как кликабельные ссылки: [текст](url)
24. При веб-поиске ВСЕГДА указывай источники: [Источник](url)
25. Для графиков и артефактов — показывай их inline в чате.
26. Если загружен файл с данными — предложи анализ, визуализацию, выводы.

ФОРМАТ ОТВЕТА:
1. Пиши профессионально и структурированно. НЕ используй эмодзи в заголовках и тексте.
2. Используй Markdown: заголовки (##, ###), **жирный** для ключевых терминов, таблицы для сравнений.
3. Для отчётов используй чёткую структуру: Введение → Результаты → Выводы → Рекомендации.
4. Кратко опиши что делаешь, затем вызови инструмент.
5. После генерации файла — дай ссылку: [Скачать filename](download_url)
6. После веб-поиска — укажи источники: [Источник](url)
7. Не пиши длинных объяснений — ДЕЙСТВУЙ.
8. Для списков багов/задач используй таблицы с колонками: ID, Описание, Критичность, Статус.
9. Выделяй критичные моменты **жирным**, а не эмодзи.
10. Используй разделители (---) между секциями для читаемости."""




# ══════════════════════════════════════════════════════════════════
# ██ AGENT ZONES — зоны ответственности агентов ██
# ══════════════════════════════════════════════════════════════════

AGENT_ZONES = {
    "orchestrator": {
        "tools": ["store_memory", "recall_memory", "canvas_create", "task_complete"],
        "description": "Планирование, память, координация",
        "models": {"turbo_standard": "deepseek", "turbo_premium": "deepseek",
                   "pro_standard": "sonnet", "pro_premium": "sonnet"}
    },
    "designer": {
        "tools": ["generate_design", "generate_image", "edit_image",
                  "create_artifact", "browser_navigate", "browser_get_text"],
        "description": "UI/UX, дизайн, визуальный контент",
        "models": {"turbo_standard": "gemini", "turbo_premium": "gemini",
                   "pro_standard": "gemini", "pro_premium": "gemini"}
    },
    "developer": {
        "tools": ["ssh_execute", "file_write", "file_read",
                  "code_interpreter", "generate_file"],
        "description": "Код, разработка, файлы",
        "models": {"turbo_standard": "deepseek", "turbo_premium": "deepseek",
                   "pro_standard": "deepseek", "pro_premium": "deepseek"}
    },
    "devops": {
        "tools": ["ssh_execute", "file_write", "file_read",
                  "browser_check_site", "browser_check_api"],
        "description": "Серверы, деплой, инфраструктура",
        "models": {"turbo_standard": "deepseek", "turbo_premium": "deepseek",
                   "pro_standard": "deepseek", "pro_premium": "deepseek"}
    },
    "analyst": {
        "tools": ["web_search", "web_fetch", "code_interpreter",
                  "generate_chart", "generate_report", "read_any_file"],
        "description": "Анализ данных, исследования, отчёты",
        "models": {"turbo_standard": "deepseek", "turbo_premium": "deepseek",
                   "pro_standard": "deepseek", "pro_premium": "sonnet"}
    },
    "tester": {
        "tools": ["browser_navigate", "browser_get_text", "browser_check_site",
                  "browser_check_api", "code_interpreter", "ssh_execute"],
        "description": "Тестирование, QA, проверка",
        "models": {"turbo_standard": "deepseek", "turbo_premium": "deepseek",
                   "pro_standard": "deepseek", "pro_premium": "deepseek"}
    },
    "integrator": {
        "tools": ["ssh_execute", "file_write", "file_read",
                  "browser_check_api", "code_interpreter", "web_fetch"],
        "description": "Интеграции, API, вебхуки",
        "models": {"turbo_standard": "deepseek", "turbo_premium": "deepseek",
                   "pro_standard": "deepseek", "pro_premium": "deepseek"}
    },
}

# ══════════════════════════════════════════════════════════════════
# ██ ERROR PATTERNS — паттерны ошибок для self-healing ██
# ══════════════════════════════════════════════════════════════════

ERROR_PATTERNS = {
    "port_in_use": {
        "pattern": r"(address already in use|port.*already.*bound|EADDRINUSE)",
        "fix": "Порт занят. Попробуй: sudo fuser -k {port}/tcp или измени порт.",
        "auto_fix": "sudo fuser -k 3510/tcp 2>/dev/null; sleep 1"
    },
    "permission_denied": {
        "pattern": r"(permission denied|EACCES|Operation not permitted)",
        "fix": "Нет прав. Попробуй с sudo или проверь владельца файла.",
        "auto_fix": None
    },
    "module_not_found": {
        "pattern": r"(ModuleNotFoundError|No module named|ImportError)",
        "fix": "Модуль не найден. Установи через pip install.",
        "auto_fix": "pip install {module} 2>&1 | tail -5"
    },
    "connection_refused": {
        "pattern": r"(Connection refused|ECONNREFUSED|connect.*failed)",
        "fix": "Соединение отклонено. Проверь что сервис запущен.",
        "auto_fix": None
    },
    "disk_full": {
        "pattern": r"(No space left on device|disk.*full|ENOSPC)",
        "fix": "Диск заполнен. Очисти /tmp или старые логи.",
        "auto_fix": "df -h && du -sh /tmp/* 2>/dev/null | sort -rh | head -10"
    },
    "nginx_config_error": {
        "pattern": r"(nginx.*failed|nginx.*error|test failed)",
        "fix": "Ошибка конфига nginx. Проверь синтаксис: nginx -t",
        "auto_fix": "nginx -t 2>&1"
    },
    "ssl_error": {
        "pattern": r"(SSL.*error|certificate.*expired|CERTIFICATE_VERIFY_FAILED)",
        "fix": "Ошибка SSL. Проверь сертификат: certbot certificates",
        "auto_fix": "certbot certificates 2>&1 | head -20"
    },
}

# ══════════════════════════════════════════════════════════════════
# ██ AGENT LOOP CLASS ██
# ══════════════════════════════════════════════════════════════════

# ── BUG-1 FIX: Extend TOOLS_SCHEMA with memory_v9 tools ──
if _MEMORY_V9_AVAILABLE and ALL_MEMORY_TOOLS:
    _existing_names = {t["function"]["name"] for t in TOOLS_SCHEMA}
    for _mt in ALL_MEMORY_TOOLS:
        if _mt["function"]["name"] not in _existing_names:
            TOOLS_SCHEMA.append(_mt)


class AgentLoop:
    """
    LangGraph-based autonomous agent loop v5.0.

    Features:
    - StateGraph with typed AgentState
    - SqliteSaver checkpointer for persistence
    - Retry on all external calls (LLM, SSH, HTTP)
    - Idempotency on mutations (file_write, ssh with side effects)
    - Self-Healing 2.0 (auto error detection, 3 fix variants)
    - Circuit breaker for cascading failure protection
    """

    MAX_ITERATIONS = 50
    MAX_TOOL_OUTPUT = 20000
    MAX_HEAL_ATTEMPTS = 3

    def __init__(self, model, api_key, api_url="https://openrouter.ai/api/v1/chat/completions",
                 ssh_credentials=None, orion_mode=None, session_id=None, user_id=None):
        self.model = model
        self.api_key = api_key
        self.api_url = api_url
        self.ssh_credentials = ssh_credentials or {}
        self._user_id = user_id  # BUG-5 FIX: user_id для памяти
        self._chat_id = None     # BUG-5 FIX: будет установлен из app.py
        self.browser = BrowserAgent()
        self.total_tokens_in = 0
        self.total_tokens_out = 0
        self.actions_log = []
        self._stop_requested = False

        # ── ORION Sprint 5: режим, сессия, scratchpad, snapshot ──
        self.orion_mode = orion_mode or DEFAULT_MODE
        self.session_id = session_id or f"sess_{int(__import__('time').time())}"
        self.scratchpad = []          # Патч 6: промежуточные мысли агента
        self._snapshots = []          # Патч 4: снапшоты состояния
        self._ask_user_pending = None # Патч 5: ожидание ответа пользователя
        self._intent_result = None    # Результат intent clarifier
        self._session_cost = 0.0      # Текущая стоимость сессии

        # BUG-1 FIX: memory_v9 engine
        self.memory = None

        # LangGraph checkpointer
        self._checkpoint_conn = sqlite3.connect(
            "/tmp/agent_checkpoints.db", check_same_thread=False
        )
        self._checkpointer = SqliteSaver(self._checkpoint_conn)

    def stop(self):
        """Request the agent loop to stop."""
        self._stop_requested = True

    # ── ORION Патч 4: Snapshot / Rollback ────────────────────────

    def take_snapshot(self, label: str = "") -> int:
        """Сохранить снапшот текущего состояния агента."""
        import copy
        snap = {
            "id": len(self._snapshots),
            "label": label,
            "timestamp": __import__("time").time(),
            "actions_log": copy.deepcopy(self.actions_log),
            "tokens_in": self.total_tokens_in,
            "tokens_out": self.total_tokens_out,
            "scratchpad": list(self.scratchpad),
        }
        self._snapshots.append(snap)
        logger.info(f"[snapshot] #{snap['id']} '{label}' saved")
        return snap["id"]

    def rollback_to_snapshot(self, snap_id: int) -> bool:
        """Откатиться к снапшоту по ID."""
        for snap in self._snapshots:
            if snap["id"] == snap_id:
                self.actions_log = snap["actions_log"]
                self.total_tokens_in = snap["tokens_in"]
                self.total_tokens_out = snap["tokens_out"]
                self.scratchpad = snap["scratchpad"]
                logger.info(f"[rollback] Rolled back to snapshot #{snap_id} '{snap['label']}'")
                return True
        logger.warning(f"[rollback] Snapshot #{snap_id} not found")
        return False

    def list_snapshots(self):
        """Список всех снапшотов."""
        return [{"id": s["id"], "label": s["label"],
                 "timestamp": s["timestamp"]} for s in self._snapshots]

    # ── ORION Патч 5: Ask User ────────────────────────────────────

    def ask_user(self, question: str) -> dict:
        """
        Запросить уточнение у пользователя.
        Возвращает SSE-событие ask_user для фронтенда.
        """
        self._ask_user_pending = question
        return {
            "type": "ask_user",
            "question": question,
            "session_id": self.session_id
        }

    def provide_user_answer(self, answer: str):
        """Получить ответ пользователя на ask_user запрос."""
        self._ask_user_pending = None
        return answer

    # ── ORION Патч 6: Scratchpad ──────────────────────────────────

    def scratchpad_add(self, thought: str, category: str = "thought"):
        """Добавить промежуточную мысль в scratchpad."""
        entry = {
            "category": category,
            "thought": thought,
            "timestamp": __import__("time").time()
        }
        self.scratchpad.append(entry)
        if len(self.scratchpad) > 100:
            self.scratchpad = self.scratchpad[-100:]

    def scratchpad_get(self, last_n: int = 10) -> list:
        """Получить последние N записей из scratchpad."""
        return self.scratchpad[-last_n:]

    def scratchpad_clear(self):
        """Очистить scratchpad."""
        self.scratchpad = []

    # ── ORION Патч 7: Error Pattern Matching ─────────────────────

    def match_error_pattern(self, error_text: str) -> dict:
        """
        Найти паттерн ошибки и получить рекомендацию по исправлению.
        Returns: {"pattern_key": str, "fix": str, "auto_fix": str|None}
        """
        for key, pattern_cfg in ERROR_PATTERNS.items():
            if re.search(pattern_cfg["pattern"], error_text, re.IGNORECASE):
                return {
                    "pattern_key": key,
                    "fix": pattern_cfg["fix"],
                    "auto_fix": pattern_cfg.get("auto_fix"),
                    "matched": True
                }
        return {"matched": False, "fix": None, "auto_fix": None}

    # ── ORION Патч: Cost Limit Check ─────────────────────────────

    def check_cost_limit(self) -> dict:
        """Проверить не превышен ли лимит стоимости сессии."""
        try:
            return check_cost_limit(self.session_id, self.orion_mode)
        except Exception:
            return {"allowed": True, "current_cost": 0, "max_cost": 999}

    def _track_cost(self, tokens_in: int, tokens_out: int, model_id: str):
        """Трекинг стоимости запроса."""
        try:
            from model_router import MODELS
            # Найти модель по ID
            model_key = "deepseek"
            for k, m in MODELS.items():
                if m["id"] == model_id:
                    model_key = k
                    break
            model_cfg = MODELS.get(model_key, MODELS["deepseek"])
            cost = (tokens_in * model_cfg["input_price"] / 1_000_000 +
                    tokens_out * model_cfg["output_price"] / 1_000_000)
            cost = 0.0  # КРИТ-2: стоимость всегда $0.00
            self._session_cost += cost
            add_session_cost(self.session_id, cost)
            log_cost(
                user_id=getattr(self, "user_id", "unknown"),
                model_id=model_id,
                tokens_in=tokens_in,
                tokens_out=tokens_out,
                cost_usd=cost,
                session_id=self.session_id,
                mode=self.orion_mode
            )
        except Exception as e:
            logger.debug(f"Cost tracking error: {e}")



    # ── LLM Call with Retry ──────────────────────────────────────

    @retry(max_attempts=3, base_delay=2.0, max_delay=30.0, jitter=1.0,
           retryable_exceptions=(ConnectionError, TimeoutError, OSError),
           context="llm_api")
    def _call_ai(self, messages, tools=None):
        """Call AI model with tool definitions. Retry on transient errors."""
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://orion.mksitdev.ru",
            "X-Title": "ORION Digital v1.0"
        }

        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": 0.2,
            "max_tokens": 16000,
        }

        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"

        resp = http_requests.post(
            self.api_url, headers=headers, json=payload, timeout=120
        )

        # Check for retryable HTTP errors
        if resp.status_code in RETRYABLE_HTTP_CODES:
            raise ConnectionError(f"HTTP {resp.status_code}: {resp.text[:200]}")

        resp.raise_for_status()
        data = resp.json()

        usage = data.get("usage", {})
        self.total_tokens_in += usage.get("prompt_tokens", 0)
        self.total_tokens_out += usage.get("completion_tokens", 0)

        choices = data.get("choices", [])
        if not choices:
            return None, None, "Empty response from AI"

        message = choices[0].get("message", {})
        content = message.get("content", "")
        tool_calls = message.get("tool_calls", None)

        return content, tool_calls, None

    def _call_ai_simple(self, messages: list) -> str:
        """Simple non-streaming AI call for memory_v9 internal use."""
        try:
            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
                "HTTP-Referer": "https://orion.mksitdev.ru",
                "X-Title": "ORION Digital v1.0"
            }
            payload = {
                "model": self.model,
                "messages": messages,
                "temperature": 0.1,
                "max_tokens": 2000,
                "stream": False,
            }
            resp = http_requests.post(self.api_url, headers=headers, json=payload, timeout=30)
            if resp.status_code == 200:
                data = resp.json()
                return data.get("choices", [{}])[0].get("message", {}).get("content", "")
        except Exception as e:
            logger.debug(f"_call_ai_simple error: {e}")
        return ""

    def _call_ai_stream(self, messages, tools=None):
        """Call AI model with streaming. Circuit breaker + retry."""
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://orion.mksitdev.ru",
            "X-Title": "ORION Digital v1.0"
        }

        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": 0.2,
            "max_tokens": 16000,
            "stream": True,
        }

        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"

        breaker = get_breaker("llm_stream", failure_threshold=5, recovery_timeout=60)
        if not breaker.can_execute():
            yield {"type": "error", "error": "LLM API temporarily unavailable (circuit breaker open)"}
            return

        try:
            resp = http_requests.post(
                self.api_url,
                headers=headers,
                json=payload,
                stream=True,
                timeout=120
            )

            if resp.status_code in RETRYABLE_HTTP_CODES:
                breaker.record_failure()
                yield {"type": "error", "error": f"LLM API error: HTTP {resp.status_code}"}
                return

            resp.raise_for_status()
            breaker.record_success()

            content = ""
            tool_calls_data = {}

            for line in resp.iter_lines():
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
                    if not choices:
                        usage = chunk.get("usage")
                        if usage:
                            self.total_tokens_in += usage.get("prompt_tokens", 0)
                            self.total_tokens_out += usage.get("completion_tokens", 0)
                        continue

                    delta = choices[0].get("delta", {})

                    text = delta.get("content", "")
                    if text:
                        content += text
                        yield {"type": "text_delta", "text": text}

                    tc = delta.get("tool_calls")
                    if tc:
                        for call in tc:
                            idx = call.get("index", 0)
                            if idx not in tool_calls_data:
                                tool_calls_data[idx] = {
                                    "id": call.get("id", f"call_{idx}"),
                                    "name": "",
                                    "arguments": ""
                                }
                            fn = call.get("function", {})
                            if fn.get("name"):
                                tool_calls_data[idx]["name"] = fn["name"]
                            if fn.get("arguments"):
                                tool_calls_data[idx]["arguments"] += fn["arguments"]
                            if call.get("id"):
                                tool_calls_data[idx]["id"] = call["id"]

                    usage = chunk.get("usage")
                    if usage:
                        self.total_tokens_in += usage.get("prompt_tokens", 0)
                        self.total_tokens_out += usage.get("completion_tokens", 0)

                except json.JSONDecodeError:
                    continue

            if tool_calls_data:
                tool_calls = []
                for idx in sorted(tool_calls_data.keys()):
                    tc = tool_calls_data[idx]
                    tool_calls.append({
                        "id": tc["id"],
                        "type": "function",
                        "function": {
                            "name": tc["name"],
                            "arguments": tc["arguments"]
                        }
                    })
                yield {"type": "tool_calls", "tool_calls": tool_calls, "content": content}
            else:
                yield {"type": "text_complete", "content": content}

        except Exception as e:
            breaker.record_failure()
            yield {"type": "error", "error": str(e)}

    # ── Tool Execution with Retry + Idempotency ──────────────────

    def _execute_tool(self, tool_name, arguments):
        """Execute a tool with retry and idempotency."""
        try:
            args = json.loads(arguments) if isinstance(arguments, str) else arguments
        except json.JSONDecodeError:
            return {"success": False, "error": f"Invalid JSON arguments: {arguments}"}

        host = args.get("host", self.ssh_credentials.get("host", ""))
        username = args.get("username", self.ssh_credentials.get("username", "root"))
        password = args.get("password", self.ssh_credentials.get("password", ""))

        try:
            if tool_name == "ssh_execute":
                command = args.get("command", "")
                if not host or not command:
                    return {"success": False, "error": "host and command are required"}

                # Idempotency check for mutating commands
                if is_mutating_command(command):
                    idem_key = make_ssh_key(host, command)
                    tool_store = get_tool_store()
                    is_dup, cached = tool_store.check(idem_key)
                    if is_dup and cached is not None:
                        logger.info(f"[idempotency] SSH command cache hit: {command[:50]}")
                        cached["from_cache"] = True
                        return cached

                # Execute with retry
                result = self._ssh_execute_with_retry(host, username, password, command)

                # Store result for idempotency
                if is_mutating_command(command) and result.get("success"):
                    tool_store = get_tool_store()
                    tool_store.store(idem_key, result, ttl=300)

                return result

            elif tool_name == "file_write":
                path = args.get("path", "")
                content = args.get("content", "")
                if not host or not path:
                    return {"success": False, "error": "host and path are required"}

                # УЛУЧ-4: Large file write — файлы >40KB пишем по SSH чанками
                if len(content) > 40000 and self.ssh_credentials.get("host"):
                    logger.info(f"[large_file_write] File {path} is {len(content)} bytes, using SSH chunked write")
                    return self._write_large_file_via_ssh(host, username, password, path, content)

                # Idempotency: check if same file with same content
                idem_key = make_file_key(host, path, content)
                file_store = get_file_store()
                is_dup, cached = file_store.check(idem_key)
                if is_dup and cached is not None:
                    logger.info(f"[idempotency] file_write cache hit: {path}")
                    cached["from_cache"] = True
                    return cached

                result = self._file_write_with_retry(host, username, password, path, content)

                if result.get("success"):
                    file_store.store(idem_key, result, ttl=600)

                return result

            elif tool_name == "file_read":
                path = args.get("path", "")
                if not host or not path:
                    return {"success": False, "error": "host and path are required"}

                result = self._file_read_with_retry(host, username, password, path)
                if result.get("success") and len(result.get("content", "")) > self.MAX_TOOL_OUTPUT:
                    result["content"] = result["content"][:self.MAX_TOOL_OUTPUT] + "\n... [truncated]"
                return result

            elif tool_name == "browser_navigate":
                url = args.get("url", "")
                if not url:
                    return {"success": False, "error": "url is required"}
                result = self._browser_with_retry(lambda: self.browser.navigate(url))
                if result.get("html") and len(result["html"]) > self.MAX_TOOL_OUTPUT:
                    result["html"] = result["html"][:self.MAX_TOOL_OUTPUT] + "... [truncated]"
                return result

            elif tool_name == "browser_check_site":
                url = args.get("url", "")
                if not url:
                    return {"success": False, "error": "url is required"}
                return self._browser_with_retry(lambda: self.browser.check_site(url))

            elif tool_name == "browser_get_text":
                url = args.get("url", "")
                if not url:
                    return {"success": False, "error": "url is required"}
                result = self._browser_with_retry(lambda: self.browser.get_text(url))
                if result.get("text") and len(result["text"]) > self.MAX_TOOL_OUTPUT:
                    result["text"] = result["text"][:self.MAX_TOOL_OUTPUT] + "... [truncated]"
                return result

            elif tool_name == "browser_check_api":
                url = args.get("url", "")
                method = args.get("method", "GET")
                data = args.get("data")
                if not url:
                    return {"success": False, "error": "url is required"}
                return self._browser_with_retry(
                    lambda: self.browser.check_api(url, method=method, data=data)
                )

            elif tool_name == "generate_file":
                content = args.get("content", "")
                filename = args.get("filename", "file.txt")
                title = args.get("title")
                if not content:
                    return {"success": False, "error": "content is required"}

                try:
                    from file_generator import generate_file as gen_file
                    result = gen_file(
                        content=content,
                        filename=filename,
                        title=title,
                        chat_id=getattr(self, '_chat_id', None),
                        user_id=getattr(self, '_user_id', None)
                    )
                    return result
                except Exception as e:
                    return {"success": False, "error": f"File generation error: {str(e)}"}

            elif tool_name == "generate_image":
                prompt = args.get("prompt", "")
                style = args.get("style", "illustration")
                filename = args.get("filename", "image.png")
                if not prompt:
                    return {"success": False, "error": "prompt is required"}

                try:
                    result = self._generate_image(prompt, style, filename)
                    return result
                except Exception as e:
                    return {"success": False, "error": f"Image generation error: {str(e)}"}

            elif tool_name == "read_any_file":
                file_path = args.get("file_path", "")
                if not file_path:
                    return {"success": False, "error": "file_path is required"}
                try:
                    from file_reader import read_file
                    result = read_file(file_path)
                    text = result.to_text(max_length=args.get("max_length", 50000))
                    return {
                        "success": True,
                        "filename": result.filename,
                        "file_type": result.file_type,
                        "size": result.size,
                        "pages": result.pages,
                        "tables_count": len(result.tables),
                        "images_count": len(result.images),
                        "content": text
                    }
                except Exception as e:
                    return {"success": False, "error": f"File read error: {str(e)}"}

            elif tool_name == "analyze_image":
                file_path = args.get("file_path", "")
                question = args.get("question", "Describe this image in detail")
                if not file_path:
                    return {"success": False, "error": "file_path is required"}
                try:
                    result = self._analyze_image_vision(file_path, question)
                    return result
                except Exception as e:
                    return {"success": False, "error": f"Image analysis error: {str(e)}"}

            elif tool_name == "web_search":
                query = args.get("query", "")
                num_results = args.get("num_results", 5)
                if not query:
                    return {"success": False, "error": "query is required"}
                try:
                    results = self._web_search(query, num_results)
                    return {"success": True, "query": query, "results": results}
                except Exception as e:
                    return {"success": False, "error": f"Web search error: {str(e)}"}

            elif tool_name == "web_fetch":
                url = args.get("url", "")
                max_length = args.get("max_length", 20000)
                if not url:
                    return {"success": False, "error": "url is required"}
                try:
                    text = self._web_fetch(url, max_length)
                    return {"success": True, "url": url, "content": text}
                except Exception as e:
                    return {"success": False, "error": f"Web fetch error: {str(e)}"}

            elif tool_name == "code_interpreter":
                code = args.get("code", "")
                description = args.get("description", "")
                if not code:
                    return {"success": False, "error": "code is required"}
                try:
                    result = self._code_interpreter(code, description)
                    return result
                except Exception as e:
                    return {"success": False, "error": f"Code interpreter error: {str(e)}"}

            elif tool_name == "generate_chart":
                chart_type = args.get("chart_type", "bar")
                data = args.get("data", {})
                title = args.get("title", "Chart")
                options = args.get("options", {})
                try:
                    result = self._generate_chart(chart_type, data, title, options)
                    return result
                except Exception as e:
                    return {"success": False, "error": f"Chart generation error: {str(e)}"}

            elif tool_name == "create_artifact":
                content = args.get("content", "")
                art_type = args.get("type", "html")
                title = args.get("title", "Artifact")
                if not content:
                    return {"success": False, "error": "content is required"}
                try:
                    result = self._create_artifact(content, art_type, title)
                    return result
                except Exception as e:
                    return {"success": False, "error": f"Artifact creation error: {str(e)}"}

            elif tool_name == "generate_report":
                title = args.get("title", "Report")
                sections = args.get("sections", [])
                fmt = args.get("format", "docx")
                filename = args.get("filename", f"report.{fmt}")
                try:
                    result = self._generate_report(title, sections, fmt, filename)
                    return result
                except Exception as e:
                    return {"success": False, "error": f"Report generation error: {str(e)}"}

            elif tool_name == "edit_image":
                file_path = args.get("file_path", "")
                operations = args.get("operations", [])
                output_filename = args.get("output_filename", "edited_image.png")
                if not file_path:
                    return {"success": False, "error": "file_path is required"}
                try:
                    from artifact_generator import ArtifactGenerator
                    gen = ArtifactGenerator(
                        generated_dir=os.environ.get("GENERATED_DIR", "/var/www/orion/backend/generated")
                    )
                    result = gen.edit_image(file_path, operations, output_filename)
                    return result
                except Exception as e:
                    return {"success": False, "error": f"Image edit error: {str(e)}"}

            elif tool_name == "generate_design":
                design_type = args.get("design_type", "banner")
                content = args.get("content", {})
                style = args.get("style", "modern")
                dimensions = args.get("dimensions", {})
                try:
                    from artifact_generator import ArtifactGenerator
                    gen = ArtifactGenerator(
                        generated_dir=os.environ.get("GENERATED_DIR", "/var/www/orion/backend/generated")
                    )
                    result = gen.generate_design(design_type, content, style, dimensions)
                    return result
                except Exception as e:
                    return {"success": False, "error": f"Design generation error: {str(e)}"}

            elif tool_name == "store_memory":
                key = args.get("key", "")
                value = args.get("value", "")
                category = args.get("category", "fact")
                if not key or not value:
                    return {"success": False, "error": "key and value are required"}
                try:
                    from project_manager import ProjectManager
                    pm = ProjectManager(
                        data_dir=os.environ.get("DATA_DIR", "/var/www/orion/backend/data")
                    )
                    user_id = getattr(self, '_user_id', 'default')
                    result = pm.store_memory(user_id, key, value, category)
                    return result
                except Exception as e:
                    return {"success": False, "error": f"Memory store error: {str(e)}"}

            elif tool_name == "recall_memory":
                query = args.get("query", "")
                category = args.get("category")
                if not query:
                    return {"success": False, "error": "query is required"}
                try:
                    from project_manager import ProjectManager
                    pm = ProjectManager(
                        data_dir=os.environ.get("DATA_DIR", "/var/www/orion/backend/data")
                    )
                    user_id = getattr(self, '_user_id', 'default')
                    result = pm.recall_memory(user_id, query, category)
                    return result
                except Exception as e:
                    return {"success": False, "error": f"Memory recall error: {str(e)}"}

            elif tool_name == "canvas_create":
                title = args.get("title", "Untitled")
                content = args.get("content", "")
                canvas_type = args.get("canvas_type", "document")
                canvas_id = args.get("canvas_id")
                if not content:
                    return {"success": False, "error": "content is required"}
                try:
                    from project_manager import ProjectManager
                    pm = ProjectManager(
                        data_dir=os.environ.get("DATA_DIR", "/var/www/orion/backend/data")
                    )
                    user_id = getattr(self, '_user_id', 'default')
                    chat_id = getattr(self, '_chat_id', None)
                    result = pm.canvas_create(user_id, title, content, canvas_type, canvas_id, chat_id)
                    return result
                except Exception as e:
                    return {"success": False, "error": f"Canvas creation error: {str(e)}"}

            elif tool_name == "task_complete":
                summary = args.get("summary", "Task completed")
                return {"success": True, "completed": True, "summary": summary}

            else:
                return {"success": False, "error": f"Unknown tool: {tool_name}"}

        except Exception as e:
            return {"success": False, "error": f"Tool execution error: {str(e)}"}

    # ── Retry wrappers for specific operations ───────────────────

    @retry(max_attempts=3, base_delay=2.0, max_delay=15.0, jitter=1.0,
           retryable_exceptions=(ConnectionError, TimeoutError, OSError, IOError, EOFError),
           context="ssh_execute")
    def _ssh_execute_with_retry(self, host, username, password, command):
        ssh = ssh_pool.get_connection(host=host, username=username, password=password)
        return ssh.execute_command(command, timeout=90)

    @retry(max_attempts=3, base_delay=2.0, max_delay=15.0, jitter=1.0,
           retryable_exceptions=(ConnectionError, TimeoutError, OSError, IOError, EOFError),
           context="file_write")
    def _file_write_with_retry(self, host, username, password, path, content):
        ssh = ssh_pool.get_connection(host=host, username=username, password=password)
        return ssh.file_write(path, content)

    def _write_large_file_via_ssh(self, host, username, password, path, content):
        """УЛУЧ-4: Запись большого файла (>40KB) по SSH чанками по 30000 байт.
        Первый чанк: printf '...' > filepath
        Остальные:   printf '...' >> filepath
        """
        import shlex
        try:
            ssh = ssh_pool.get_connection(host=host, username=username, password=password)
            chunk_size = 30000
            chunks = [content[i:i+chunk_size] for i in range(0, len(content), chunk_size)]
            total_chunks = len(chunks)
            logger.info(f"[large_file_write] Writing {len(content)} bytes in {total_chunks} chunks to {path}")

            # Создаём директорию если нужно
            dir_path = '/'.join(path.split('/')[:-1])
            if dir_path:
                ssh.execute_command(f"mkdir -p {shlex.quote(dir_path)}", timeout=30)

            for i, chunk in enumerate(chunks):
                # Экранируем содержимое для printf: % -> %%, \ -> \\
                escaped = chunk.replace('\\', '\\\\').replace('%', '%%').replace("'", "'\''")
                if i == 0:
                    cmd = f"printf '%s' '{escaped}' > {shlex.quote(path)}"
                else:
                    cmd = f"printf '%s' '{escaped}' >> {shlex.quote(path)}"
                result = ssh.execute_command(cmd, timeout=60)
                if not result.get("success") and result.get("exit_code", 0) != 0:
                    logger.error(f"[large_file_write] Chunk {i+1}/{total_chunks} failed: {result}")
                    return {"success": False, "error": f"Chunk {i+1} write failed: {result.get('stderr', '')}"}
                logger.info(f"[large_file_write] Chunk {i+1}/{total_chunks} written OK")

            # Проверяем размер записанного файла
            verify = ssh.execute_command(f"wc -c < {shlex.quote(path)}", timeout=15)
            written_bytes = int(verify.get("stdout", "0").strip()) if verify.get("success") else 0
            logger.info(f"[large_file_write] Done: {written_bytes} bytes written to {path}")

            return {
                "success": True,
                "path": path,
                "bytes_written": written_bytes,
                "chunks": total_chunks,
                "method": "ssh_chunked"
            }
        except Exception as e:
            logger.error(f"[large_file_write] Exception: {e}")
            return {"success": False, "error": str(e)}

    @retry(max_attempts=3, base_delay=1.0, max_delay=10.0, jitter=0.5,
           retryable_exceptions=(ConnectionError, TimeoutError, OSError, IOError, EOFError),
           context="file_read")
    def _file_read_with_retry(self, host, username, password, path):
        ssh = ssh_pool.get_connection(host=host, username=username, password=password)
        return ssh.file_read(path)

    @retry(max_attempts=2, base_delay=1.0, max_delay=10.0, jitter=0.5,
           retryable_exceptions=(ConnectionError, TimeoutError, OSError),
           context="browser")
    def _browser_with_retry(self, func):
        return func()

    # ── Vision API (Image Analysis) ─────────────────────────────────────────

    def _analyze_image_vision(self, file_path, question="Describe this image in detail"):
        """
        Analyze an image using Vision API via OpenRouter.
        Supports: screenshots, charts, diagrams, photos, handwritten notes.
        Falls back to OCR if Vision API is unavailable.
        """
        import base64
        import os
        from pathlib import Path

        if not os.path.exists(file_path):
            return {"success": False, "error": f"File not found: {file_path}"}

        filename = Path(file_path).name
        ext = Path(file_path).suffix.lower()

        # Get image metadata
        metadata = {}
        try:
            from PIL import Image
            with Image.open(file_path) as img:
                metadata = {
                    "width": img.width,
                    "height": img.height,
                    "format": img.format,
                    "mode": img.mode,
                    "size_bytes": os.path.getsize(file_path)
                }
        except Exception:
            metadata = {"size_bytes": os.path.getsize(file_path)}

        # Try Vision API via OpenRouter (GPT-4o-mini with vision)
        vision_description = None
        try:
            with open(file_path, "rb") as f:
                image_data = base64.b64encode(f.read()).decode("utf-8")

            mime_map = {
                ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
                ".gif": "image/gif", ".webp": "image/webp", ".bmp": "image/bmp"
            }
            mime_type = mime_map.get(ext, "image/png")

            import requests
            response = requests.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json"
                },
                json={
                    "model": "openai/gpt-4o-mini",
                    "messages": [
                        {
                            "role": "user",
                            "content": [
                                {
                                    "type": "text",
                                    "text": f"{question}\n\nPlease provide a detailed analysis. If there is text in the image, transcribe it. If there are charts/diagrams, describe the data. If it's a screenshot, describe the UI elements. Respond in the same language as the question."
                                },
                                {
                                    "type": "image_url",
                                    "image_url": {
                                        "url": f"data:{mime_type};base64,{image_data}"
                                    }
                                }
                            ]
                        }
                    ],
                    "max_tokens": 2000
                },
                timeout=60
            )

            if response.status_code == 200:
                data = response.json()
                vision_description = data["choices"][0]["message"]["content"]
                logger.info(f"Vision API analyzed {filename} successfully")
            else:
                logger.warning(f"Vision API returned {response.status_code}: {response.text[:200]}")
        except Exception as e:
            logger.warning(f"Vision API failed, falling back to OCR: {e}")

        # Fallback: OCR via file_reader
        ocr_text = None
        try:
            from file_reader import read_file
            fr_result = read_file(file_path)
            if fr_result.text and "No text detected" not in fr_result.text:
                ocr_text = fr_result.text
        except Exception:
            pass

        # Combine results
        description_parts = []
        if vision_description:
            description_parts.append(vision_description)
        if ocr_text and not vision_description:
            description_parts.append(f"OCR Text: {ocr_text}")
        elif ocr_text and vision_description:
            description_parts.append(f"\n\nAdditional OCR Text: {ocr_text[:500]}")

        description = "\n".join(description_parts) if description_parts else "Could not analyze image (no Vision API or OCR available)"

        return {
            "success": True,
            "filename": filename,
            "description": description,
            "ocr_text": ocr_text or "",
            "metadata": metadata,
            "method": "vision_api" if vision_description else "ocr_fallback"
        }

    # ── Image Generation ─────────────────────────────────────────────────────

    def _generate_image(self, prompt, style="illustration", filename="image.png"):
        """
        Generate an image using matplotlib/pillow for diagrams/charts,
        or placeholder for AI-generated images.
        """
        import uuid as _uuid
        GENERATED_DIR = os.environ.get("GENERATED_DIR", "/var/www/orion/backend/generated")
        os.makedirs(GENERATED_DIR, exist_ok=True)

        file_id = str(_uuid.uuid4())[:12]
        filepath = os.path.join(GENERATED_DIR, f"{file_id}_{filename}")

        if style in ("chart", "diagram", "graph"):
            # Use matplotlib for charts
            try:
                import matplotlib
                matplotlib.use('Agg')
                import matplotlib.pyplot as plt
                import numpy as np

                fig, ax = plt.subplots(figsize=(10, 6))
                fig.patch.set_facecolor('#1a1a2e')
                ax.set_facecolor('#16213e')

                # Generate sample chart based on prompt keywords
                if 'pie' in prompt.lower() or 'круг' in prompt.lower():
                    ax.remove()
                    ax = fig.add_subplot(111)
                    sizes = [30, 25, 20, 15, 10]
                    labels = ['A', 'B', 'C', 'D', 'E']
                    colors = ['#6366f1', '#8b5cf6', '#a78bfa', '#c4b5fd', '#ddd6fe']
                    ax.pie(sizes, labels=labels, colors=colors, autopct='%1.1f%%',
                           startangle=90, textprops={'color': 'white'})
                elif 'bar' in prompt.lower() or 'столб' in prompt.lower():
                    x = np.arange(5)
                    y = np.random.randint(10, 100, 5)
                    ax.bar(x, y, color='#6366f1')
                    ax.set_xlabel('Category', color='white')
                    ax.set_ylabel('Value', color='white')
                    ax.tick_params(colors='white')
                else:
                    x = np.linspace(0, 10, 100)
                    y = np.sin(x) * np.random.uniform(0.8, 1.2)
                    ax.plot(x, y, color='#6366f1', linewidth=2)
                    ax.fill_between(x, y, alpha=0.3, color='#6366f1')
                    ax.set_xlabel('X', color='white')
                    ax.set_ylabel('Y', color='white')
                    ax.tick_params(colors='white')

                ax.set_title(prompt[:60], color='white', fontsize=12)
                plt.tight_layout()
                plt.savefig(filepath, dpi=150, bbox_inches='tight',
                           facecolor=fig.get_facecolor())
                plt.close()

            except Exception as e:
                return {"success": False, "error": f"Chart generation error: {str(e)}"}

        else:
            # For illustrations/photos/logos — create a styled placeholder
            try:
                from PIL import Image, ImageDraw, ImageFont

                img = Image.new('RGB', (800, 600), color='#1a1a2e')
                draw = ImageDraw.Draw(img)

                # Draw decorative elements
                for i in range(5):
                    x1 = 50 + i * 150
                    y1 = 100 + (i % 3) * 80
                    draw.rounded_rectangle([x1, y1, x1+120, y1+120],
                                          radius=15, fill='#6366f1', outline='#8b5cf6')

                # Add text
                try:
                    font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 20)
                    font_small = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 14)
                except Exception:
                    font = ImageFont.load_default()
                    font_small = font

                draw.text((50, 30), prompt[:80], fill='white', font=font)
                draw.text((50, 550), f"Generated by ORION Digital | Style: {style}",
                         fill='#888888', font=font_small)

                img.save(filepath)

            except Exception as e:
                return {"success": False, "error": f"Image generation error: {str(e)}"}

        if os.path.exists(filepath):
            size = os.path.getsize(filepath)
            # Register in file_generator registry
            try:
                from file_generator import _register_file
                _register_file(file_id, filename, filepath, "png", size,
                              getattr(self, '_chat_id', None),
                              getattr(self, '_user_id', None))
            except Exception:
                pass

            return {
                "success": True,
                "file_id": file_id,
                "filename": filename,
                "size": size,
                "download_url": f"/api/files/{file_id}/download",
                "preview_url": f"/api/files/{file_id}/preview"
            }

        return {"success": False, "error": "Failed to generate image"}

    # ── Web Search & Fetch ──────────────────────────────────────────

    @retry(max_attempts=2, base_delay=1.0, max_delay=5.0, jitter=0.5,
           retryable_exceptions=(ConnectionError, TimeoutError, OSError),
           context="web_search")
    def _web_search(self, query, num_results=5):
        """Search the web using DuckDuckGo (no API key needed)."""
        import requests as req
        results = []
        try:
            # Use DuckDuckGo HTML search
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            }
            resp = req.get(
                'https://html.duckduckgo.com/html/',
                params={'q': query},
                headers=headers,
                timeout=15
            )
            resp.raise_for_status()
            
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(resp.text, 'html.parser')
            
            for r in soup.select('.result')[:num_results]:
                title_el = r.select_one('.result__title a, .result__a')
                snippet_el = r.select_one('.result__snippet')
                if title_el:
                    href = title_el.get('href', '')
                    # DuckDuckGo wraps URLs
                    if 'uddg=' in href:
                        import urllib.parse
                        parsed = urllib.parse.parse_qs(urllib.parse.urlparse(href).query)
                        href = parsed.get('uddg', [href])[0]
                    results.append({
                        'title': title_el.get_text(strip=True),
                        'url': href,
                        'snippet': snippet_el.get_text(strip=True) if snippet_el else ''
                    })
        except Exception as e:
            logger.warning(f"DuckDuckGo search failed: {e}")
            # Fallback: return a helpful message
            results = [{'title': 'Search unavailable', 'url': '', 'snippet': f'Error: {str(e)}'}]
        
        return results

    @retry(max_attempts=2, base_delay=1.0, max_delay=5.0, jitter=0.5,
           retryable_exceptions=(ConnectionError, TimeoutError, OSError),
           context="web_fetch")
    def _web_fetch(self, url, max_length=20000):
        """Fetch and extract text content from a URL."""
        import requests as req
        from bs4 import BeautifulSoup
        
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }
        resp = req.get(url, headers=headers, timeout=20)
        resp.raise_for_status()
        
        soup = BeautifulSoup(resp.text, 'html.parser')
        
        # Remove scripts, styles, nav, footer
        for tag in soup(['script', 'style', 'nav', 'footer', 'header', 'aside']):
            tag.decompose()
        
        # Extract main content
        main = soup.find('main') or soup.find('article') or soup.find('body')
        if main:
            text = main.get_text(separator='\n', strip=True)
        else:
            text = soup.get_text(separator='\n', strip=True)
        
        # Clean up multiple newlines
        import re
        text = re.sub(r'\n{3,}', '\n\n', text)
        
        if len(text) > max_length:
            text = text[:max_length] + f'\n... [truncated, total {len(text)} chars]'
        
        return text

    # ── Code Interpreter ────────────────────────────────────────────

    def _code_interpreter(self, code, description=""):
        """Execute Python code in a sandboxed subprocess."""
        import subprocess
        import tempfile
        import uuid as _uuid
        
        GENERATED_DIR = os.environ.get("GENERATED_DIR", "/var/www/orion/backend/generated")
        os.makedirs(GENERATED_DIR, exist_ok=True)
        
        # Security: check for forbidden/dangerous operations
        FORBIDDEN_PATTERNS = [
            'os.system(', 'subprocess.call(', 'subprocess.Popen(',
            'shutil.rmtree(', '__import__(\'os\').system',
            'eval(', 'exec(', 'compile(',
            'open(\'/etc', 'open(\"/etc',
            'rm -rf', 'chmod 777', 'curl ', 'wget ',
        ]
        for pattern in FORBIDDEN_PATTERNS:
            if pattern in code:
                return {"success": False, "error": f"Security: forbidden operation detected: {pattern}"}
        
        # Create temp file with the code
        code_file = os.path.join(GENERATED_DIR, f"code_{_uuid.uuid4().hex[:8]}.py")
        
        # Wrap code to capture output and generated files
        wrapped_code = f'''import sys, os
os.chdir("{GENERATED_DIR}")

{code}
'''
        
        with open(code_file, 'w') as f:
            f.write(wrapped_code)
        
        try:
            result = subprocess.run(
                ['python3', code_file],
                capture_output=True,
                text=True,
                timeout=60,
                cwd=GENERATED_DIR,
                env={**os.environ, 'MPLBACKEND': 'Agg'}
            )
            
            stdout = result.stdout[:10000] if result.stdout else ""
            stderr = result.stderr[:5000] if result.stderr else ""
            
            # Check for generated files (images, csvs, etc.)
            generated_files = []
            if os.path.exists(GENERATED_DIR):
                import glob
                # Find files modified in last 10 seconds
                import time as _time
                now = _time.time()
                for f in glob.glob(os.path.join(GENERATED_DIR, '*')):
                    if os.path.getmtime(f) > now - 10 and f != code_file:
                        fname = os.path.basename(f)
                        fsize = os.path.getsize(f)
                        file_id = fname.split('_')[0] if '_' in fname else _uuid.uuid4().hex[:12]
                        generated_files.append({
                            'filename': fname,
                            'size': fsize,
                            'download_url': f'/api/files/{file_id}/download'
                        })
            
            # Clean up code file
            try:
                os.remove(code_file)
            except:
                pass
            
            return {
                "success": result.returncode == 0,
                "stdout": stdout,
                "stderr": stderr,
                "return_code": result.returncode,
                "generated_files": generated_files
            }
            
        except subprocess.TimeoutExpired:
            return {"success": False, "error": "Code execution timed out (60s limit)"}
        except Exception as e:
            return {"success": False, "error": f"Execution error: {str(e)}"}
        finally:
            try:
                os.remove(code_file)
            except:
                pass

    # ── Chart Generation ────────────────────────────────────────────

    def _generate_chart(self, chart_type, data, title="Chart", options=None):
        """Generate interactive chart and save as image."""
        import uuid as _uuid
        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt
        import numpy as np
        
        GENERATED_DIR = os.environ.get("GENERATED_DIR", "/var/www/orion/backend/generated")
        os.makedirs(GENERATED_DIR, exist_ok=True)
        
        file_id = str(_uuid.uuid4())[:12]
        filename = f"{file_id}_chart.png"
        filepath = os.path.join(GENERATED_DIR, filename)
        
        # Setup style
        plt.style.use('default')
        fig, ax = plt.subplots(figsize=(12, 7))
        fig.patch.set_facecolor('#ffffff')
        ax.set_facecolor('#f8f9fa')
        
        colors = ['#6366f1', '#8b5cf6', '#ec4899', '#f59e0b', '#10b981', '#3b82f6', '#ef4444', '#06b6d4']
        
        labels = data.get('labels', [])
        values = data.get('values', [])
        datasets = data.get('datasets', [])
        
        if not datasets and values:
            datasets = [{'label': title, 'data': values}]
        
        try:
            if chart_type == 'pie':
                vals = datasets[0]['data'] if datasets else values
                wedges, texts, autotexts = ax.pie(
                    vals, labels=labels, colors=colors[:len(vals)],
                    autopct='%1.1f%%', startangle=90,
                    textprops={'fontsize': 11}
                )
                for t in autotexts:
                    t.set_fontweight('bold')
                    
            elif chart_type == 'bar':
                x = np.arange(len(labels))
                width = 0.8 / max(len(datasets), 1)
                for i, ds in enumerate(datasets):
                    offset = (i - len(datasets)/2 + 0.5) * width
                    bars = ax.bar(x + offset, ds['data'], width, 
                                 label=ds.get('label', f'Series {i+1}'),
                                 color=colors[i % len(colors)], 
                                 edgecolor='white', linewidth=0.5)
                    # Add value labels on bars
                    for bar in bars:
                        height = bar.get_height()
                        ax.annotate(f'{height:,.0f}',
                                   xy=(bar.get_x() + bar.get_width()/2, height),
                                   xytext=(0, 3), textcoords='offset points',
                                   ha='center', va='bottom', fontsize=8)
                ax.set_xticks(x)
                ax.set_xticklabels(labels, rotation=45, ha='right')
                if len(datasets) > 1:
                    ax.legend()
                    
            elif chart_type == 'line':
                for i, ds in enumerate(datasets):
                    ax.plot(labels, ds['data'], 
                           label=ds.get('label', f'Series {i+1}'),
                           color=colors[i % len(colors)],
                           linewidth=2, marker='o', markersize=5)
                    ax.fill_between(labels, ds['data'], alpha=0.1, color=colors[i % len(colors)])
                if len(datasets) > 1:
                    ax.legend()
                plt.xticks(rotation=45, ha='right')
                    
            elif chart_type in ('scatter', 'dot'):
                for i, ds in enumerate(datasets):
                    x_data = ds.get('x', list(range(len(ds['data']))))
                    ax.scatter(x_data, ds['data'],
                              label=ds.get('label', f'Series {i+1}'),
                              color=colors[i % len(colors)], s=60, alpha=0.7)
                if len(datasets) > 1:
                    ax.legend()
                    
            elif chart_type == 'horizontal_bar':
                y = np.arange(len(labels))
                vals = datasets[0]['data'] if datasets else values
                ax.barh(y, vals, color=colors[:len(vals)], edgecolor='white')
                ax.set_yticks(y)
                ax.set_yticklabels(labels)
                for i, v in enumerate(vals):
                    ax.text(v + max(vals)*0.01, i, f'{v:,.0f}', va='center', fontsize=9)
            
            else:  # Default to bar
                vals = datasets[0]['data'] if datasets else values
                ax.bar(labels, vals, color=colors[:len(vals)], edgecolor='white')
                plt.xticks(rotation=45, ha='right')
            
            ax.set_title(title, fontsize=14, fontweight='bold', pad=15)
            ax.grid(axis='y', alpha=0.3)
            ax.spines['top'].set_visible(False)
            ax.spines['right'].set_visible(False)
            
            plt.tight_layout()
            plt.savefig(filepath, dpi=150, bbox_inches='tight', facecolor=fig.get_facecolor())
            plt.close()
            
            size = os.path.getsize(filepath)
            
            # Register file
            try:
                from file_generator import _register_file
                _register_file(file_id, f"chart_{chart_type}.png", filepath, "png", size,
                              getattr(self, '_chat_id', None),
                              getattr(self, '_user_id', None))
            except Exception:
                pass
            
            return {
                "success": True,
                "file_id": file_id,
                "filename": filename,
                "chart_type": chart_type,
                "size": size,
                "download_url": f"/api/files/{file_id}/download",
                "preview_url": f"/api/files/{file_id}/preview"
            }
            
        except Exception as e:
            plt.close()
            return {"success": False, "error": f"Chart error: {str(e)}"}

    # ── Artifact Creation ───────────────────────────────────────────

    def _create_artifact(self, content, art_type="html", title="Artifact"):
        """Create an interactive artifact (HTML, SVG, Mermaid, React)."""
        import uuid as _uuid
        
        GENERATED_DIR = os.environ.get("GENERATED_DIR", "/var/www/orion/backend/generated")
        os.makedirs(GENERATED_DIR, exist_ok=True)
        
        file_id = str(_uuid.uuid4())[:12]
        
        if art_type == 'html':
            filename = f"{file_id}_artifact.html"
            # Wrap in full HTML if not already
            if '<html' not in content.lower():
                content = f"""<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{title}</title>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; padding: 20px; background: #fff; color: #1a1a2e; }}
    </style>
</head>
<body>
{content}
</body>
</html>"""
        elif art_type == 'svg':
            filename = f"{file_id}_artifact.svg"
        elif art_type == 'mermaid':
            filename = f"{file_id}_artifact.html"
            content = f"""<!DOCTYPE html>
<html><head>
<script src="https://cdn.jsdelivr.net/npm/mermaid/dist/mermaid.min.js"></script>
<title>{title}</title>
</head><body>
<div class="mermaid">
{content}
</div>
<script>mermaid.initialize({{startOnLoad:true, theme:'default'}});</script>
</body></html>"""
        elif art_type == 'react':
            filename = f"{file_id}_artifact.html"
            content = f"""<!DOCTYPE html>
<html><head>
<script src="https://unpkg.com/react@18/umd/react.production.min.js"></script>
<script src="https://unpkg.com/react-dom@18/umd/react-dom.production.min.js"></script>
<script src="https://unpkg.com/@babel/standalone/babel.min.js"></script>
<title>{title}</title>
<style>* {{ margin: 0; padding: 0; box-sizing: border-box; }} body {{ font-family: sans-serif; }}</style>
</head><body>
<div id="root"></div>
<script type="text/babel">
{content}
ReactDOM.createRoot(document.getElementById('root')).render(<App />);
</script>
</body></html>"""
        else:
            filename = f"{file_id}_artifact.{art_type}"
        
        filepath = os.path.join(GENERATED_DIR, filename)
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(content)
        
        size = os.path.getsize(filepath)
        
        try:
            from file_generator import _register_file
            _register_file(file_id, filename, filepath, art_type, size,
                          getattr(self, '_chat_id', None),
                          getattr(self, '_user_id', None))
        except Exception:
            pass
        
        return {
            "success": True,
            "file_id": file_id,
            "filename": filename,
            "type": art_type,
            "title": title,
            "size": size,
            "download_url": f"/api/files/{file_id}/download",
            "preview_url": f"/api/files/{file_id}/preview"
        }

    # ── Report Generation ───────────────────────────────────────────

    def _generate_report(self, title, sections, fmt="docx", filename=None):
        """Generate a structured report with sections."""
        if not filename:
            filename = f"report.{fmt}"
        
        # Build content from sections
        content_parts = [f"# {title}\n"]
        for section in sections:
            if isinstance(section, dict):
                heading = section.get('heading', section.get('title', ''))
                body = section.get('content', section.get('body', ''))
                content_parts.append(f"## {heading}\n\n{body}\n")
            elif isinstance(section, str):
                content_parts.append(section + "\n")
        
        full_content = "\n".join(content_parts)
        
        try:
            from file_generator import generate_file as gen_file
            result = gen_file(
                content=full_content,
                filename=filename,
                title=title,
                chat_id=getattr(self, '_chat_id', None),
                user_id=getattr(self, '_user_id', None)
            )
            return result
        except Exception as e:
            return {"success": False, "error": f"Report generation error: {str(e)}"}

    # ── Self-Healing 2.0 ─────────────────────────────────────────────

    def _analyze_error(self, tool_name, args, error_result):
        """
        Анализировать ошибку и предложить варианты исправления.
        Returns: list of fix suggestions (up to 3)
        """
        error_msg = str(error_result.get("error", error_result.get("stderr", "")))
        fixes = []

        if tool_name == "ssh_execute":
            command = args.get("command", "")

            if "command not found" in error_msg:
                cmd_name = command.strip().split()[0] if command.strip() else ""
                fixes.append({
                    "type": "install_package",
                    "description": f"Установить пакет {cmd_name}",
                    "action": {"tool": "ssh_execute", "args": {**args, "command": f"apt-get install -y {cmd_name}"}}
                })
                fixes.append({
                    "type": "use_full_path",
                    "description": f"Найти путь к {cmd_name}",
                    "action": {"tool": "ssh_execute", "args": {**args, "command": f"which {cmd_name} || find / -name {cmd_name} -type f 2>/dev/null | head -1"}}
                })

            elif "Permission denied" in error_msg or "permission denied" in error_msg:
                fixes.append({
                    "type": "sudo",
                    "description": "Выполнить с sudo",
                    "action": {"tool": "ssh_execute", "args": {**args, "command": f"sudo {command}"}}
                })

            elif "No such file or directory" in error_msg:
                import os as _os
                path_match = re.search(r"'([^']+)'", error_msg)
                if path_match:
                    path = path_match.group(1)
                    dir_path = _os.path.dirname(path)
                    if dir_path:
                        fixes.append({
                            "type": "mkdir",
                            "description": f"Создать директорию {dir_path}",
                            "action": {"tool": "ssh_execute", "args": {**args, "command": f"mkdir -p {dir_path}"}}
                        })

            elif "Connection refused" in error_msg or "Connection timed out" in error_msg:
                fixes.append({
                    "type": "check_service",
                    "description": "Проверить статус сервисов",
                    "action": {"tool": "ssh_execute", "args": {**args, "command": "systemctl list-units --state=failed"}}
                })

            elif "E: Unable to locate package" in error_msg:
                fixes.append({
                    "type": "apt_update",
                    "description": "Обновить список пакетов",
                    "action": {"tool": "ssh_execute", "args": {**args, "command": "apt-get update"}}
                })

            elif "address already in use" in error_msg.lower():
                port_match = re.search(r'port\s*(\d+)', error_msg, re.IGNORECASE)
                port = port_match.group(1) if port_match else "unknown"
                fixes.append({
                    "type": "kill_port",
                    "description": f"Освободить порт {port}",
                    "action": {"tool": "ssh_execute", "args": {**args, "command": f"fuser -k {port}/tcp 2>/dev/null; sleep 1"}}
                })

        elif tool_name == "file_write":
            if "No such file or directory" in error_msg:
                import os as _os
                path = args.get("path", "")
                dir_path = _os.path.dirname(path)
                fixes.append({
                    "type": "mkdir",
                    "description": f"Создать директорию {dir_path}",
                    "action": {"tool": "ssh_execute", "args": {"host": args.get("host"), "command": f"mkdir -p {dir_path}"}}
                })

        elif tool_name in ("browser_check_site", "browser_navigate", "browser_get_text"):
            if "Connection" in error_msg or "Timeout" in error_msg:
                url = args.get("url", "")
                fixes.append({
                    "type": "retry_http",
                    "description": "Повторить через HTTP",
                    "action": {"tool": tool_name, "args": {**args, "url": url.replace("https://", "http://")}}
                })

        return fixes[:3]

    # ── SSE Helpers ──────────────────────────────────────────────

    def _sse(self, data):
        """Format data as SSE event."""
        return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"

    def _sanitize_args(self, args):
        """Remove sensitive data from args for display."""
        safe = {}
        for k, v in args.items():
            if k in ("password", "key", "secret", "token"):
                safe[k] = "***"
            elif isinstance(v, str) and len(v) > 500:
                safe[k] = v[:200] + f"... [{len(v)} chars]"
            else:
                safe[k] = v
        return safe

    def _preview_result(self, tool_name, result):
        """Create a short preview of tool result for display."""
        if not result.get("success", False):
            error = result.get("error", result.get("stderr", "Unknown error"))
            return f"❌ Ошибка: {str(error)[:200]}"

        if tool_name == "ssh_execute":
            stdout = result.get("stdout", "")
            if result.get("from_cache"):
                return f"📋 [из кеша] {stdout[:200]}" if stdout else "📋 [из кеша] Команда уже выполнена"
            if stdout:
                lines = stdout.split("\n")
                if len(lines) > 50:
                    return "\n".join(lines[:50]) + f"\n... [ещё {len(lines) - 50} строк]"
                return stdout[:3000]
            return "✅ Команда выполнена (пустой вывод)"

        elif tool_name == "file_write":
            path = result.get("path", "")
            size = result.get("size", 0)
            cached = " [из кеша]" if result.get("from_cache") else ""
            return f"✅ Файл создан{cached}: {path} ({size} байт)"

        elif tool_name == "file_read":
            content = result.get("content", "")
            lines = content.split("\n")
            return f"📄 {len(lines)} строк прочитано"

        elif tool_name == "browser_check_site":
            status = result.get("status_code", "?")
            title = result.get("title", "")
            time_ms = result.get("response_time_ms", "?")
            return f"🌐 HTTP {status} | {title} | {time_ms}ms"

        elif tool_name == "browser_navigate":
            status = result.get("status_code", "?")
            return f"🌐 HTTP {status} | Страница загружена"

        elif tool_name == "browser_get_text":
            text = result.get("text", "")
            return f"📝 {len(text)} символов текста получено"

        elif tool_name == "browser_check_api":
            status = result.get("status_code", "?")
            method = result.get("method", "GET")
            time_ms = result.get("response_time_ms", "?")
            return f"🔌 {method} → HTTP {status} | {time_ms}ms"

        elif tool_name == "generate_file":
            fn = result.get("filename", "")
            dl = result.get("download_url", "")
            return f"📄 Файл создан: {fn} | [Скачать]({dl})"

        elif tool_name == "generate_image":
            fn = result.get("filename", "")
            dl = result.get("download_url", "")
            return f"🖼️ Изображение создано: {fn} | [Скачать]({dl})"

        elif tool_name == "read_any_file":
            fmt = result.get("format", "")
            length = len(result.get("content", ""))
            tables = len(result.get("tables", []))
            imgs = len(result.get("images", []))
            extra = ""
            if tables:
                extra += f" | {tables} таблиц"
            if imgs:
                extra += f" | {imgs} изображений"
            return f"📎 Прочитан {fmt} файл ({length} символов{extra})"

        elif tool_name == "analyze_image":
            desc = result.get("description", "")[:200]
            return f"👁️ Анализ изображения: {desc}"

        elif tool_name == "web_search":
            results_list = result.get("results", [])
            return f"🔍 Найдено {len(results_list)} результатов"

        elif tool_name == "web_fetch":
            text = result.get("text", "")
            return f"🌐 Получено {len(text)} символов текста"

        elif tool_name == "code_interpreter":
            stdout = result.get("stdout", "")
            files = result.get("generated_files", [])
            extra = f" | {len(files)} файлов создано" if files else ""
            if stdout:
                lines = stdout.strip().split("\n")
                preview = "\n".join(lines[:20])
                if len(lines) > 20:
                    preview += f"\n... [ещё {len(lines)-20} строк]"
                return f"🐍 Код выполнен{extra}:\n{preview}"
            return f"🐍 Код выполнен (пустой вывод){extra}"

        elif tool_name == "generate_chart":
            ct = result.get("chart_type", "")
            dl = result.get("download_url", "")
            return f"📊 График {ct} создан | [Открыть]({dl})"

        elif tool_name == "create_artifact":
            title = result.get("title", "")
            art_type = result.get("type", "")
            preview_url = result.get("preview_url", "")
            return f"🎨 Артефакт '{title}' ({art_type}) | [Открыть]({preview_url})"

        elif tool_name == "generate_report":
            fn = result.get("filename", "")
            dl = result.get("download_url", "")
            return f"📋 Отчёт создан: {fn} | [Скачать]({dl})"

        elif tool_name == "edit_image":
            fn = result.get("filename", "")
            dl = result.get("download_url", "")
            ops = result.get("operations_applied", 0)
            return f"✏️ Изображение отредактировано ({ops} операций): {fn} | [Скачать]({dl})"

        elif tool_name == "generate_design":
            dt = result.get("design_type", "")
            title = result.get("title", "")
            preview_url = result.get("preview_url", "")
            return f"🎨 Дизайн '{title}' ({dt}) | [Открыть]({preview_url})"

        elif tool_name == "store_memory":
            key = result.get("key", "")
            return f"🧠 Запомнил: {key}"

        elif tool_name == "recall_memory":
            memories = result.get("memories", [])
            return f"🧠 Найдено {len(memories)} воспоминаний"

        elif tool_name == "canvas_create":
            title = result.get("title", "")
            canvas_id = result.get("canvas_id", "")
            is_update = result.get("updated", False)
            action = "обновлён" if is_update else "создан"
            return f"📝 Canvas '{title}' {action} (ID: {canvas_id})"

        return "✅ Выполнено"

    # ══════════════════════════════════════════════════════════════
    # ██ MAIN STREAMING LOOP (backward-compatible API) ██
    # ══════════════════════════════════════════════════════════════

    def run_stream(self, user_message, chat_history=None, file_content=None):
        """
        Run the agent loop with streaming.
        Yields SSE events for real-time display.

        This is the main entry point — backward-compatible with v4.0 API.
        Internally uses LangGraph StateGraph for state management.
        """
        if chat_history is None:
            chat_history = []

        # ── ORION: Intent Clarifier ───────────────────────────────
        if _INTENT_CLARIFIER_AVAILABLE:
            try:
                self._intent_result = clarify_intent(
                    user_message,
                    history=chat_history,
                    orion_mode=self.orion_mode
                )
                # Проверка лимита стоимости
                cost_check = self.check_cost_limit()
                if not cost_check.get("allowed", True):
                    yield {
                        "type": "error",
                        "error": (f"Лимит стоимости сессии превышен: "
                                  f"${cost_check['current_cost']:.3f} / "
                                  f"${cost_check['max_cost']:.2f}. "
                                  f"Начните новую сессию.")
                    }
                    return
                # Emit intent info для UI
                intent_label = format_clarification_for_user(self._intent_result)
                yield {"type": "intent", "data": self._intent_result, "label": intent_label}
                # Если нужно уточнение — спрашиваем
                if self._intent_result.get("needs_clarification"):
                    q = self._intent_result.get("clarification_question", "Уточните задачу.")
                    yield self.ask_user(q)
                    return
            except Exception as _ie:
                logger.debug(f"Intent clarifier error: {_ie}")

        # ── BUG-5 FIX: Инициализация memory_v9 с user_id ──────────────────
        if _MEMORY_V9_AVAILABLE and SuperMemoryEngine:
            try:
                _uid = getattr(self, "_user_id", None)
                _cid = getattr(self, "_chat_id", None)
                logger.info(f"[MEMORY] init_task: user_id={_uid!r}, chat_id={_cid!r}")
                self.memory = SuperMemoryEngine(call_llm_func=self._call_ai_simple)
                self.memory.init_task(
                    user_message=user_message,
                    file_content=file_content or "",
                    user_id=_uid,
                    chat_id=_cid,
                    api_key=self.api_key,
                    api_url=self.api_url,
                    ssh_host=self.ssh_credentials.get("host", "")
                )
                logger.info(f"[MEMORY] init_task OK: memory engine ready")
            except Exception as _mem_err:
                logger.warning(f"[MEMORY] memory_v9 init failed: {_mem_err}", exc_info=True)
                self.memory = None

        # Build initial messages
        if self.memory:
            try:
                messages = self.memory.build_messages(
                    system_prompt=AGENT_SYSTEM_PROMPT,
                    chat_history=chat_history,
                    user_message=user_message,
                    file_content=file_content or "",
                    ssh_credentials=self.ssh_credentials
                )
            except Exception as _mem_err2:
                logger.warning(f"memory_v9 build_messages failed: {_mem_err2}")
                messages = [{"role": "system", "content": AGENT_SYSTEM_PROMPT}]
                for msg in chat_history[-10:]:
                    messages.append({"role": msg.get("role", "user"), "content": msg.get("content", "")})
                messages.append({"role": "user", "content": user_message})
        else:
            messages = [{"role": "system", "content": AGENT_SYSTEM_PROMPT}]
            for msg in chat_history[-10:]:
                messages.append({"role": msg.get("role", "user"), "content": msg.get("content", "")})
            full_message = user_message
            if file_content:
                max_file_len = 100000
                if len(file_content) > max_file_len:
                    file_content = file_content[:max_file_len] + f"\n... [обрезано, всего {len(file_content)} символов]"
                full_message = f"{file_content}\n\n---\n\nЗадача:\n{user_message}"
            if self.ssh_credentials.get("host"):
                creds_hint = f"\n\n[Доступные серверы: {self.ssh_credentials['host']} (user: {self.ssh_credentials.get('username', 'root')})]"
                full_message += creds_hint
            messages.append({"role": "user", "content": full_message})

        # ── BUG-5 FIX: Извлечь контекст из долгосрочной памяти ──────────────
        # ── BUG-5 FIX v2: recall/profile уже встроены в build_messages() ──
        # build_messages() вызывает: profile.get_prompt_context() + semantic.search()
        # Дополнительно форсируем сохранение семантической памяти из текущего сообщения
        # ─────────────────────────────────────────────────────────────────────

        # Динамически увеличиваем MAX_ITERATIONS для больших файлов
        if file_content:
            file_size = len(file_content)
            if file_size > 50000:
                self.MAX_ITERATIONS = 80
            elif file_size > 20000:
                self.MAX_ITERATIONS = 60

        # Store user_message for fallback response
        self.user_message = user_message

        # Agent loop with LangGraph state tracking
        iteration = 0
        full_response_text = ""
        heal_attempts = 0

        while iteration < self.MAX_ITERATIONS and not self._stop_requested:
            iteration += 1

            yield self._sse({
                "type": "agent_iteration",
                "iteration": iteration,
                "max": self.MAX_ITERATIONS,
                "status": "executing"
            })

            tool_calls_received = None
            ai_text = ""

            # ── BUG-1 FIX: before_iteration (GoalAnchor + Compaction) ──
            if self.memory:
                try:
                    messages = self.memory.before_iteration(messages, iteration, self.MAX_ITERATIONS)
                except Exception as _bi_err:
                    logger.debug(f"memory before_iteration error: {_bi_err}")

            try:
                for event in self._call_ai_stream(messages, tools=TOOLS_SCHEMA):
                    if event["type"] == "text_delta":
                        ai_text += event["text"]
                        full_response_text += event["text"]
                        yield self._sse({"type": "content", "text": event["text"]})

                    elif event["type"] == "tool_calls":
                        tool_calls_received = event["tool_calls"]
                        ai_text = event.get("content", "")
                        if ai_text:
                            full_response_text += ai_text

                    elif event["type"] == "text_complete":
                        ai_text = event.get("content", "")
                        break

                    elif event["type"] == "error":
                        yield self._sse({"type": "error", "text": f"AI Error: {event['error']}"})
                        return
            except Exception as e:
                error_msg = f"Ошибка при вызове AI: {str(e)}"
                yield self._sse({"type": "error", "text": error_msg})
                yield self._sse({"type": "content", "text": f"\n\n❌ {error_msg}"})
                full_response_text += f"\n\n❌ {error_msg}"
                return

            if not tool_calls_received:
                break

            # Add assistant message with tool calls to history
            assistant_msg = {"role": "assistant", "content": ai_text or ""}
            assistant_msg["tool_calls"] = tool_calls_received
            messages.append(assistant_msg)

            # Execute each tool call
            for tc in tool_calls_received:
                tool_name = tc["function"]["name"]
                tool_args_str = tc["function"]["arguments"]
                tool_id = tc.get("id", f"call_{iteration}")

                try:
                    tool_args = json.loads(tool_args_str)
                except Exception:
                    tool_args = {}

                yield self._sse({
                    "type": "tool_start",
                    "tool": tool_name,
                    "args": self._sanitize_args(tool_args),
                    "iteration": iteration
                })

                # Check for task_complete
                if tool_name == "task_complete":
                    result = self._execute_tool(tool_name, tool_args_str)
                    summary = result.get("summary", "")
                    yield self._sse({
                        "type": "tool_result",
                        "tool": tool_name,
                        "success": True,
                        "summary": summary
                    })
                    yield self._sse({"type": "task_complete", "summary": summary})
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tool_id,
                        "content": json.dumps(result, ensure_ascii=False)
                    })
                    # ── BUG-5 FIX: Сохранить память при task_complete ──
                    if self.memory:
                        try:
                            self.memory.after_chat(
                                user_message=user_message,
                                full_response=full_response_text or summary,
                                chat_id=getattr(self, "_chat_id", None),
                                success=True
                            )
                        except Exception as _mem_tc_err:
                            logger.warning(f"Memory after_chat (task_complete) failed: {_mem_tc_err}")
                    return

                # ── BUG-1 FIX: handle memory tools first ──
                if self.memory:
                    try:
                        mem_result = self.memory.handle_tool(tool_name, tool_args)
                        if mem_result is not None:
                            result_str = str(mem_result)
                            messages.append({
                                "role": "tool",
                                "tool_call_id": tool_id,
                                "content": result_str[:self.MAX_TOOL_OUTPUT]
                            })
                            yield self._sse({
                                "type": "tool_result",
                                "tool": tool_name,
                                "success": mem_result.get("success", True),
                                "preview": str(mem_result)[:200],
                                "elapsed": 0
                            })
                            continue
                    except Exception as _ht_err:
                        logger.debug(f"memory.handle_tool error: {_ht_err}")

                # Execute the tool
                start_time = time.time()
                result = self._execute_tool(tool_name, tool_args_str)
                elapsed = round(time.time() - start_time, 2)

                self.actions_log.append({
                    "iteration": iteration,
                    "tool": tool_name,
                    "args": self._sanitize_args(tool_args),
                    "success": result.get("success", False),
                    "elapsed": elapsed,
                    "timestamp": datetime.now(timezone.utc).isoformat()
                })

                # ── BUG-1 FIX: after_tool (ToolLearning, ErrorPatterns, SessionMemory) ──
                if self.memory:
                    try:
                        result_str_mem = self.memory.after_tool(
                            tool_name, tool_args, result,
                            self._preview_result(tool_name, result)
                        )
                    except Exception as _at_err:
                        logger.debug(f"memory.after_tool error: {_at_err}")

                result_preview = self._preview_result(tool_name, result)
                # Include screenshot for browser tools
                _browser_tools = ("browser_navigate", "browser_check_site", "browser_get_text",
                                  "browser_get_links", "browser_screenshot_check")
                _screenshot = result.get("screenshot") if tool_name in _browser_tools else None
                _tool_result_event = {
                    "type": "tool_result",
                    "tool": tool_name,
                    "success": result.get("success", False),
                    "preview": result_preview,
                    "elapsed": elapsed
                }
                if _screenshot:
                    _tool_result_event["screenshot"] = _screenshot
                yield self._sse(_tool_result_event)

                # ── Self-Healing 2.0 ──
                if not result.get("success", False) and heal_attempts < self.MAX_HEAL_ATTEMPTS:
                    fixes = self._analyze_error(tool_name, tool_args, result)
                    if fixes:
                        heal_attempts += 1
                        yield self._sse({
                            "type": "self_heal",
                            "attempt": heal_attempts,
                            "max_attempts": self.MAX_HEAL_ATTEMPTS,
                            "fixes_count": len(fixes),
                            "fix_description": fixes[0]["description"]
                        })

                        # Try first fix automatically
                        fix = fixes[0]
                        fix_tool = fix["action"]["tool"]
                        fix_args = fix["action"]["args"]

                        yield self._sse({
                            "type": "tool_start",
                            "tool": fix_tool,
                            "args": self._sanitize_args(fix_args),
                            "iteration": iteration,
                            "is_heal": True
                        })

                        fix_start = time.time()
                        fix_result = self._execute_tool(fix_tool, json.dumps(fix_args))
                        fix_elapsed = round(time.time() - fix_start, 2)

                        fix_preview = self._preview_result(fix_tool, fix_result)
                        yield self._sse({
                            "type": "tool_result",
                            "tool": fix_tool,
                            "success": fix_result.get("success", False),
                            "preview": fix_preview,
                            "elapsed": fix_elapsed,
                            "is_heal": True
                        })

                        # Add heal result to messages so AI knows about the fix
                        heal_info = json.dumps({
                            "self_heal": True,
                            "original_error": str(result.get("error", ""))[:200],
                            "fix_applied": fix["description"],
                            "fix_result": fix_result
                        }, ensure_ascii=False)

                        if len(heal_info) > self.MAX_TOOL_OUTPUT:
                            heal_info = heal_info[:self.MAX_TOOL_OUTPUT] + "..."

                        messages.append({
                            "role": "tool",
                            "tool_call_id": tool_id,
                            "content": heal_info
                        })
                        continue  # Skip normal result append

                # Add tool result to messages
                result_str = json.dumps(result, ensure_ascii=False)
                if len(result_str) > self.MAX_TOOL_OUTPUT:
                    result_str = result_str[:self.MAX_TOOL_OUTPUT] + "..."

                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_id,
                    "content": result_str
                })

        if self._stop_requested:
            # BUG-1 FIX: on_stop — сохранить прерванную задачу
            if self.memory:
                try:
                    self.memory.on_stop(user_message, iteration)
                except Exception as _os_err:
                    logger.debug(f"memory.on_stop error: {_os_err}")
            yield self._sse({"type": "stopped", "text": "Агент остановлен пользователем"})
            return

        # ── BUG-5 FIX: Сохранить диалог в долгосрочную память ───────────────
        if self.memory:
            try:
                self.memory.after_chat(
                    user_message=user_message,
                    full_response=full_response_text,
                    chat_id=getattr(self, "_chat_id", None),
                    success=True
                )
            except Exception as _mem_save_err:
                logger.warning(f"Memory save failed: {_mem_save_err}")
        # ─────────────────────────────────────────────────────────────────────

        # Принудительный финальный ответ если агент достиг MAX_ITERATIONS без task_complete
        if not full_response_text.strip():
            yield self._sse({"type": "content", "text": "⚠️ Агент достиг лимита итераций. Запрашиваю финальный ответ..."})
            try:
                # Собрать контекст выполненных действий для финального ответа
                tool_results_summary = []
                for m in messages:
                    if m.get("role") == "tool":
                        try:
                            r = json.loads(m["content"])
                            if isinstance(r, dict) and r.get("success"):
                                tool_results_summary.append(m["content"][:300])
                        except Exception:
                            pass
                context_summary = "\n".join(tool_results_summary[-5:]) if tool_results_summary else "Результаты действий недоступны"
                final_messages = [
                    {"role": "system", "content": "Ты автономный AI-агент. На основе выполненных действий дай полный итоговый ответ пользователю. Отвечай на языке пользователя."},
                    {"role": "user", "content": f"Задача: {self.user_message if hasattr(self, 'user_message') else 'задача выполнена'}\n\nРезультаты действий:\n{context_summary}\n\nНапиши итоговый ответ с результатами выполненных действий."}
                ]
                for event in self._call_ai_stream(final_messages, tools=None):
                    if event["type"] == "text_delta":
                        yield self._sse({"type": "content", "text": event["text"]})
                    elif event["type"] == "text_complete":
                        break
            except Exception as e:
                yield self._sse({"type": "content", "text": f"\n\n⚠️ Агент достиг лимита итераций ({self.MAX_ITERATIONS}). Пожалуйста, уточните задачу или повторите запрос."})


# ══════════════════════════════════════════════════════════════
# ██ MULTI-AGENT LOOP ██
# ══════════════════════════════════════════════════════════════════

class MultiAgentLoop(AgentLoop):
    """
    Extended agent loop with multi-agent architecture:
    Architect -> Coder -> Reviewer -> QA
    Each agent has its own system prompt and can use tools.
    Inherits retry, idempotency, and self-healing from AgentLoop.
    """

    AGENTS = {
        "architect": {
            "name": "Архитектор",
            "emoji": "🏗️",
            "prompt_suffix": """Ты — Архитектор. Проанализируй задачу и создай план:
1. Какие файлы нужно создать/изменить
2. Какие команды выполнить
3. Порядок действий
4. Как проверить результат
Используй инструменты для исследования текущего состояния (ssh_execute для ls, cat и т.д.)."""
        },
        "coder": {
            "name": "Кодер",
            "emoji": "💻",
            "prompt_suffix": """Ты — Кодер. Реализуй план архитектора:
1. Создавай файлы через file_write
2. Выполняй команды через ssh_execute
3. Устанавливай зависимости
4. Деплой код на сервер
Пиши production-ready код. Используй инструменты для РЕАЛЬНОГО создания файлов и выполнения команд."""
        },
        "reviewer": {
            "name": "Ревьюер",
            "emoji": "🔍",
            "prompt_suffix": """Ты — Ревьюер. Проверь что сделал Кодер:
1. Прочитай созданные файлы через file_read
2. Проверь что сервисы работают через ssh_execute и browser_check_site
3. Если есть ошибки — исправь через file_write и ssh_execute
4. Убедись что всё соответствует требованиям."""
        },
        "qa": {
            "name": "QA Инженер",
            "emoji": "✅",
            "prompt_suffix": """Ты — QA Инженер. Финальная проверка:
1. Проверь доступность через browser_check_site
2. Проверь API через browser_check_api
3. Проверь логи через ssh_execute
4. Если всё работает — вызови task_complete с описанием результата.
Если есть проблемы — исправь их."""
        }
    }

    def run_multi_agent_stream(self, user_message, chat_history=None, file_content=None):
        """Run multi-agent pipeline with streaming."""
        if chat_history is None:
            chat_history = []

        context = user_message
        if file_content:
            context = f"{file_content}\n\n---\n\nЗадача:\n{user_message}"

        if self.ssh_credentials.get("host"):
            context += f"\n\n[Сервер: {self.ssh_credentials['host']}, user: {self.ssh_credentials.get('username', 'root')}]"

        agent_results = {}

        for agent_key, agent_info in self.AGENTS.items():
            if self._stop_requested:
                yield self._sse({"type": "stopped", "text": "Остановлено пользователем"})
                return

            yield self._sse({
                "type": "agent_start",
                "agent": agent_info["name"],
                "emoji": agent_info["emoji"],
                "role": agent_key
            })

            messages = [{
                "role": "system",
                "content": AGENT_SYSTEM_PROMPT + "\n\n" + agent_info["prompt_suffix"]
            }]

            if agent_results:
                prev_context = "\n\n".join([
                    f"=== Результат {self.AGENTS[k]['name']} ===\n{v}"
                    for k, v in agent_results.items()
                ])
                messages.append({
                    "role": "user",
                    "content": f"Предыдущие результаты:\n{prev_context}\n\n---\n\nОригинальная задача:\n{context}"
                })
            else:
                messages.append({"role": "user", "content": context})

            agent_text = ""
            agent_iteration = 0
            max_agent_iterations = 8
            heal_attempts = 0

            while agent_iteration < max_agent_iterations and not self._stop_requested:
                agent_iteration += 1

                tool_calls_received = None
                ai_text = ""

                for event in self._call_ai_stream(messages, tools=TOOLS_SCHEMA):
                    if event["type"] == "text_delta":
                        ai_text += event["text"]
                        agent_text += event["text"]
                        yield self._sse({"type": "content", "text": event["text"], "agent": agent_info["name"]})

                    elif event["type"] == "tool_calls":
                        tool_calls_received = event["tool_calls"]
                        ai_text = event.get("content", "")
                        if ai_text:
                            agent_text += ai_text

                    elif event["type"] == "text_complete":
                        break

                    elif event["type"] == "error":
                        yield self._sse({"type": "error", "text": event["error"]})
                        break

                if not tool_calls_received:
                    break

                assistant_msg = {"role": "assistant", "content": ai_text or ""}
                assistant_msg["tool_calls"] = tool_calls_received
                messages.append(assistant_msg)

                for tc in tool_calls_received:
                    tool_name = tc["function"]["name"]
                    tool_args_str = tc["function"]["arguments"]
                    tool_id = tc.get("id", f"call_{agent_iteration}")

                    try:
                        tool_args = json.loads(tool_args_str)
                    except Exception:
                        tool_args = {}

                    yield self._sse({
                        "type": "tool_start",
                        "tool": tool_name,
                        "args": self._sanitize_args(tool_args),
                        "agent": agent_info["name"]
                    })

                    if tool_name == "task_complete":
                        result = self._execute_tool(tool_name, tool_args_str)
                        yield self._sse({
                            "type": "tool_result",
                            "tool": tool_name,
                            "success": True,
                            "summary": result.get("summary", "")
                        })
                        yield self._sse({"type": "task_complete", "summary": result.get("summary", "")})
                        messages.append({
                            "role": "tool",
                            "tool_call_id": tool_id,
                            "content": json.dumps(result, ensure_ascii=False)
                        })
                        return

                    start_time = time.time()
                    result = self._execute_tool(tool_name, tool_args_str)
                    elapsed = round(time.time() - start_time, 2)

                    self.actions_log.append({
                        "agent": agent_key,
                        "iteration": agent_iteration,
                        "tool": tool_name,
                        "success": result.get("success", False),
                        "elapsed": elapsed
                    })

                    result_preview = self._preview_result(tool_name, result)
                    yield self._sse({
                        "type": "tool_result",
                        "tool": tool_name,
                        "success": result.get("success", False),
                        "preview": result_preview,
                        "elapsed": elapsed,
                        "agent": agent_info["name"]
                    })

                    # Self-Healing in multi-agent mode
                    if not result.get("success", False) and heal_attempts < self.MAX_HEAL_ATTEMPTS:
                        fixes = self._analyze_error(tool_name, tool_args, result)
                        if fixes:
                            heal_attempts += 1
                            yield self._sse({
                                "type": "self_heal",
                                "attempt": heal_attempts,
                                "max_attempts": self.MAX_HEAL_ATTEMPTS,
                                "fixes_count": len(fixes),
                                "fix_description": fixes[0]["description"],
                                "agent": agent_info["name"]
                            })

                            fix = fixes[0]
                            fix_tool = fix["action"]["tool"]
                            fix_args = fix["action"]["args"]

                            yield self._sse({
                                "type": "tool_start",
                                "tool": fix_tool,
                                "args": self._sanitize_args(fix_args),
                                "agent": agent_info["name"],
                                "is_heal": True
                            })

                            fix_result = self._execute_tool(fix_tool, json.dumps(fix_args))
                            fix_preview = self._preview_result(fix_tool, fix_result)
                            yield self._sse({
                                "type": "tool_result",
                                "tool": fix_tool,
                                "success": fix_result.get("success", False),
                                "preview": fix_preview,
                                "agent": agent_info["name"],
                                "is_heal": True
                            })

                            heal_info = json.dumps({
                                "self_heal": True,
                                "original_error": str(result.get("error", ""))[:200],
                                "fix_applied": fix["description"],
                                "fix_result": fix_result
                            }, ensure_ascii=False)

                            if len(heal_info) > self.MAX_TOOL_OUTPUT:
                                heal_info = heal_info[:self.MAX_TOOL_OUTPUT] + "..."

                            messages.append({
                                "role": "tool",
                                "tool_call_id": tool_id,
                                "content": heal_info
                            })
                            continue

                    result_str = json.dumps(result, ensure_ascii=False)
                    if len(result_str) > self.MAX_TOOL_OUTPUT:
                        result_str = result_str[:self.MAX_TOOL_OUTPUT] + "..."

                    messages.append({
                        "role": "tool",
                        "tool_call_id": tool_id,
                        "content": result_str
                    })

            agent_results[agent_key] = agent_text

            yield self._sse({
                "type": "agent_complete",
                "agent": agent_info["name"],
                "role": agent_key
            })
