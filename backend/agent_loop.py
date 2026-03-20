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

import os
import json
import time
import re
import sqlite3
from solution_cache import SolutionCache, SolutionExtractor  # ПАТЧ 9
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
except ImportError:
    pass

# ══════════════════════════════════════════════════════════════
# TURBO DUAL-BRAIN: BRAIN (MiniMax) vs HANDS (MiMo)
# ══════════════════════════════════════════════════════════════

# Инструменты для HANDS (MiMo-V2-Flash) — действия на сервере
HANDS_TOOLS = frozenset([
    "ssh_execute", "ftp_upload", "ftp_download", "ftp_list",
    "browser_navigate", "browser_check_site", "browser_get_text",
    "browser_check_api", "browser_click", "browser_fill",
    "browser_submit", "browser_select", "browser_ask_auth",
    "browser_type", "browser_js", "browser_press_key",
    "browser_scroll", "browser_hover", "browser_wait",
    "browser_elements", "browser_screenshot", "browser_page_info",
    "browser_ask_user", "browser_takeover_done",
])

# Инструменты для BRAIN (MiniMax M2.5) — думает, пишет код
BRAIN_TOOLS = frozenset([
    "create_artifact", "file_write", "generate_image",
    "search_web", "read_url", "python_exec",
])

TURBO_BRAIN_MODEL = "minimax/minimax-m2.5"
TURBO_HANDS_MODEL = "xiaomi/mimo-v2-flash"
TURBO_FALLBACK_MODEL = "openai/gpt-4.1-nano"


def _get_dual_brain_model(tool_name: str, orion_mode: str, base_model: str) -> str:
    """
    Для Turbo режима выбирает модель по типу инструмента:
    - HANDS tools (SSH, FTP, браузер) → MiMo-V2-Flash
    - BRAIN tools (код, дизайн, генерация) → MiniMax M2.5
    - Остальные → MiniMax M2.5 (по умолчанию думает)
    Для Pro/Architect — возвращает base_model без изменений.
    """
    if orion_mode not in ("turbo_standard", "turbo_premium"):
        return base_model
    if tool_name in HANDS_TOOLS:
        return TURBO_HANDS_MODEL
    # BRAIN или неизвестный инструмент → MiniMax
    return TURBO_BRAIN_MODEL


_INTENT_CLARIFIER_AVAILABLE = True
try:
    pass
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
    },
    # ── ЗАДАЧА-1: Интерактивная браузерная автоматизация ──────────────────────
    {
        "type": "function",
        "function": {
            "name": "browser_click",
            "description": "Click on an element on the current browser page. Supports CSS selectors (button.submit, #login-btn), text selectors (text=Войти), Beget st-attributes ([st=\"button-dns-edit-node\"]), and xpath (xpath=//button). Waits for SPA navigation (Vue.js/React) after click. Returns screenshot.",
            "parameters": {
                "type": "object",
                "properties": {
                    "selector": {"type": "string", "description": "CSS selector or text=... selector of the element to click"}
                },
                "required": ["selector"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "update_scratchpad",
            "description": "Update your internal scratchpad with thoughts, plans, and progress notes. Use this to organize your thinking and track progress on complex tasks."
            }
        },
        {
            "type": "function",
            "function": {
                "name": "update_task_charter",
                "description": "Update the structured Task Charter with project goals, pages, style, tech stack, and status. Use this at the start of complex tasks to define the project plan. All agents can see this charter.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "field": {
                            "type": "string",
                            "description": "Which field to update: goal, pages, style, tech_stack, status, current_phase, quality_score, notes",
                            "enum": ["goal", "pages", "style", "tech_stack", "status", "current_phase", "quality_score", "notes"]
                        },
                        "value": {
                            "type": "string",
                            "description": "JSON string of the new value for the field"
                        }
                    },
                    "required": ["field", "value"]
                },
            "parameters": {
                "type": "object",
                "properties": {
                    "content": {
                        "type": "string",
                        "description": "The thought, plan, or progress note to add to scratchpad"
                    },
                    "category": {
                        "type": "string",
                        "enum": ["plan", "thought", "progress", "error", "decision"],
                        "description": "Category of the scratchpad entry"
                    }
                },
                "required": ["content"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "browser_fill",
            "description": "Fill a form field with Vue.js/React event triggers. Tries 3 strategies: Playwright fill, click+type, JavaScript setValue. Works with Vuetify, Material UI, and any SPA framework. Returns screenshot after fill.",
            "parameters": {
                "type": "object",
                "properties": {
                    "selector": {"type": "string", "description": "CSS selector of the input field"},
                    "value": {"type": "string", "description": "Value to type into the field"}
                },
                "required": ["selector", "value"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "browser_submit",
            "description": "Submit a form on the current browser page. Optionally specify submit button selector. If no selector — presses Enter. Returns screenshot and URL after submit.",
            "parameters": {
                "type": "object",
                "properties": {
                    "selector": {"type": "string", "description": "CSS selector of submit button or form (optional). If omitted — presses Enter."}
                },
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "browser_select",
            "description": "Select an option from a <select> dropdown on the current browser page. Returns screenshot after selection.",
            "parameters": {
                "type": "object",
                "properties": {
                    "selector": {"type": "string", "description": "CSS selector of the <select> element"},
                    "value": {"type": "string", "description": "Option value or label text to select"}
                },
                "required": ["selector", "value"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "browser_ask_auth",
            "description": "Detect login form on current page and request credentials from user via ORION chat UI. Shows screenshot + form fields to user. User enters credentials → agent fills and submits the form. USE THIS when encountering login/auth pages instead of hardcoding passwords.",
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "URL of the login page (optional, uses current page if omitted)"},
                    "hint": {"type": "string", "description": "Hint for user about what system requires login (e.g. 'Bitrix admin panel', 'FTP server')"}
                },
                "required": []
            }
        }
    },
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
                    "clear": {"type": "boolean", "description": "Clear field before typing (default: true)", "default": True}
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
    },
    # ── ЗАДАЧА-1: FTP инструменты (ftplib, без SSH) ───────────────────────────
    {
        "type": "function",
        "function": {
            "name": "ftp_upload",
            "description": "Upload a file to FTP server using ftplib (works even when SSH is disabled). Supports passwords with special characters (#, @, ! etc). Use for deploying files to shared hosting, Bitrix sites, etc.",
            "parameters": {
                "type": "object",
                "properties": {
                    "host": {"type": "string", "description": "FTP server hostname or IP"},
                    "username": {"type": "string", "description": "FTP username"},
                    "password": {"type": "string", "description": "FTP password (special chars supported)"},
                    "remote_path": {"type": "string", "description": "Full remote path including filename, e.g. /www/site.ru/index.php"},
                    "content": {"type": "string", "description": "File content to upload"},
                    "port": {"type": "integer", "description": "FTP port (default: 21)", "default": 21}
                },
                "required": ["host", "username", "password", "remote_path", "content"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "ftp_download",
            "description": "Download a file from FTP server. Returns file content as text. Use to read existing files before modifying them.",
            "parameters": {
                "type": "object",
                "properties": {
                    "host": {"type": "string", "description": "FTP server hostname or IP"},
                    "username": {"type": "string", "description": "FTP username"},
                    "password": {"type": "string", "description": "FTP password"},
                    "remote_path": {"type": "string", "description": "Full remote path of the file to download"},
                    "port": {"type": "integer", "description": "FTP port (default: 21)", "default": 21}
                },
                "required": ["host", "username", "password", "remote_path"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "ftp_list",
            "description": "List files and directories on FTP server. Use to explore site structure before uploading.",
            "parameters": {
                "type": "object",
                "properties": {
                    "host": {"type": "string", "description": "FTP server hostname or IP"},
                    "username": {"type": "string", "description": "FTP username"},
                    "password": {"type": "string", "description": "FTP password"},
                    "remote_path": {"type": "string", "description": "Remote directory path to list", "default": "/"},
                    "port": {"type": "integer", "description": "FTP port (default: 21)", "default": 21}
                },
                "required": ["host", "username", "password"]
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
10. Используй разделители (---) между секциями для читаемости.

ПРАВИЛО АВТОНОМНОСТИ (КРИТИЧЕСКИ ВАЖНО):
НИКОГДА не давай пользователю инструкции типа "загрузите файл", "выполните команду", "скопируйте код".
НИКОГДА не говори "вот что нужно сделать" — ДЕЛАЙ ЭТО САМ через инструменты.
НИКОГДА не предлагай "скачайте и загрузите через FTP-клиент" — загружай сам через ssh_execute или file_write.
Ты АВТОНОМНЫЙ агент. Пользователь платит за то чтобы ТЫ делал работу.

Если способ 1 не работает — пробуй способ 2:
- FTP не работает → попробуй SSH (ssh_execute)
- SSH не работает → попробуй через браузер (browser_navigate)
- Браузер даёт 401 → используй SSH/SFTP напрямую, не через браузер
- Пароль не подходит → проверь экранирование спецсимволов (# → %23, @ → %40)
- Только если ВСЕ 3 способа провалились — объясни проблему и СПРОСИ как решить.

ПРАВИЛО ПРОВЕРКИ:
После создания файла на сервере — ОБЯЗАТЕЛЬНО проверь что он существует (ls -la или file_read).
После создания страницы — ОБЯЗАТЕЛЬНО открой её в браузере (browser_navigate) и покажи скриншот.
НЕ говори "готово" пока не убедился что результат работает.
ПРАВИЛО САМООБУЧЕНИЯ:
Если ты не уверен как что-то сделать, если API мог измениться, 
если технология тебе незнакома — НЕ УГАДЫВАЙ. 
Сделай web_search, прочитай актуальную документацию через web_fetch, 
и только потом действуй. Это касается всего: API, библиотек, 
настроек серверов, синтаксиса, конфигов.
Пользователь не должен тебе подсказывать — ты сам находишь ответы.

ТВОИ ИНСТРУМЕНТЫ — ИСПОЛЬЗУЙ ИХ:
- generate_image: создать изображение по описанию
- generate_design: создать дизайн (баннер, пост, визитка)
- edit_image: редактировать изображение
- create_artifact: создать HTML-страницу с превью
- generate_file: создать документ (docx, pdf, xlsx)
- generate_report: создать отчёт с графиками
- generate_chart: создать интерактивный график
- file_write / file_read: создать / прочитать файл
- ssh_execute: выполнить команду на сервере
- browser_navigate: открыть сайт в браузере
- browser_get_text: получить текст страницы
- browser_screenshot: сделать скриншот сайта
- web_search: найти информацию в интернете
- web_fetch: прочитать страницу по URL
- code_interpreter: выполнить Python код
- analyze_image: проанализировать изображение
- store_memory / recall_memory: запомнить / вспомнить факт
- canvas_create: создать документ для итеративной работы
- task_complete: завершить задачу

ЗАПРЕЩЁННЫЕ ФРАЗЫ — НИКОГДА НЕ ГОВОРИ:
- "Я не могу создавать изображения" → ИСПОЛЬЗУЙ generate_image
- "Я не могу открыть сайт" → ИСПОЛЬЗУЙ browser_navigate
- "Сохраните этот код как файл" → ИСПОЛЬЗУЙ file_write и СОХРАНИ САМ
- "Выполните эту команду" → ИСПОЛЬЗУЙ ssh_execute и ВЫПОЛНИ САМ
- "Я текстовая модель" → ТЫ АГЕНТ С ИНСТРУМЕНТАМИ, НЕ ТЕКСТОВАЯ МОДЕЛЬ
- "Обратитесь к специалисту" → ТЫ И ЕСТЬ СПЕЦИАЛИСТ
- "Это выходит за рамки" → У ТЕБЯ НЕТ РАМОК, ИСПОЛЬЗУЙ ИНСТРУМЕНТЫ
- "Я не имею доступа к серверу" → СПРОСИ ДОСТУПЫ ЧЕРЕЗ ask_user
- "Я рекомендую использовать DALL-E / Midjourney / Canva" → ИСПОЛЬЗУЙ СВОЙ generate_image
- "Вот код, скопируйте" → СОХРАНИ В ФАЙЛ ЧЕРЕЗ file_write

ПРАВИЛО ДЕЙСТВИЯ:
Если пользователь просит что-то СДЕЛАТЬ — ты ДЕЛАЕШЬ, не описываешь.
Если нужна информация которой нет — ищешь через web_search.
Если нужны доступы (SSH, API ключи) — спрашиваешь через ask_user.
Если ошибка — анализируешь и пробуешь другой подход (до 3 попыток).
Если 3 попытки не помогли — объясняешь проблему и предлагаешь решение.

ПРАВИЛО КОНТЕКСТА:
Всегда помни исходную задачу пользователя. Не теряй цель.
Если выполняешь много шагов — периодически проверяй: "я всё ещё решаю исходную задачу?"


ПРАВИЛО ЯЗЫКА ПРОГРАММИРОВАНИЯ:
Если пользователь НЕ указал язык/фреймворк — используй Python.
НЕ используй язык из памяти пользователя автоматически.
Используй язык из памяти ТОЛЬКО если пользователь явно попросил "на моём стеке" или "как обычно".
По умолчанию: Python + FastAPI для бэкенда, HTML/CSS/JS для фронтенда.

ПРАВИЛО ДЛИНЫ ОТВЕТА:
- Для кода: НЕ ПИШИ более 100 строк в чат. Если код длиннее — ОБЯЗАТЕЛЬНО сохрани в файл через file_write.
- Для текста: максимум 2000 символов в чат. Если длиннее — создай документ через generate_file.
- Если нужно показать структуру проекта — покажи дерево файлов и краткое описание каждого, а не весь код.

ПРАВИЛО ПАМЯТИ:
Когда пользователь обновляет факт (новое имя, новый стек, новый сервер) — используй store_memory с тем же ключом чтобы ПЕРЕЗАПИСАТЬ старый факт.
Не создавай дубликаты: store_memory(key="user_name", value="Новое имя").

🔧 ИНТЕРАКТИВНЫЙ БРАУЗЕР (новые инструменты):
- browser_click(selector): кликнуть по элементу (CSS, text=Войти, [st="..."], xpath=//...)
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
- browser_ask_auth(hint): обнаружить форму логина и запросить данные у пользователя

ИСПОЛЬЗУЙ ИНТЕРАКТИВНЫЙ БРАУЗЕР для:
- Входа в админки CMS (Битрикс, WordPress)
- Заполнения форм на сайтах
- Навигации по меню и кнопкам
- Тестирования UI интерфейсов
ПРАВИЛО АВТОРИЗАЦИИ:
Когда встречаешь форму логина:
1. Если логин/пароль уже даны в сообщении — используй smart_login(url, login, password)
2. Если smart_login вернул need_user_takeover — используй browser_ask_user(reason)
3. Если логин/пароль НЕ даны — используй browser_ask_auth(hint)
4. При CAPTCHA или 2FA — ВСЕГДА используй browser_ask_user("captcha") или browser_ask_user("2fa")
5. После ручного ввода пользователя — вызови browser_takeover_done() чтобы продолжить
НИКОГДА не хардкодь пароли в тексте ответа.
Пользователь вводит данные в безопасную форму в UI ORION.
После получения данных — используй browser_fill + browser_submit.

📦 FTP ИНСТРУМЕНТЫ (работают без SSH):
- ftp_upload: загрузить файл на FTP-сервер (для хостингов без SSH)
- ftp_download: скачать файл с FTP-сервера
- ftp_list: посмотреть список файлов на FTP
ИСПОЛЬЗУЙ FTP когда:
- SSH недоступен на сервере
- Хостинг поддерживает только FTP
- Пароль содержит спецсимволы (#, @, !) — FTP работает без проблем

ПРАВИЛА ПРОФЕССИОНАЛЬНОГО РАЗРАБОТЧИКА:

СЕРВЕРЫ:
- Перед любой работой: проверь ОС (cat /etc/os-release), свободное место (df -h), установленные пакеты
- После загрузки файлов: проверь права (chmod 644 для файлов, 755 для папок)
- После деплоя: проверь что сайт отвечает (curl -I https://domain)
- Всегда делай бэкап перед изменениями

CMS (Битрикс/WordPress):
- После любых изменений: очисти кэш (rm -rf /bitrix/cache/* или wp cache flush)
- Проверь что urlrewrite.php / .htaccess не сломан
- Проверь права на upload/ папку (должна быть 755)

КОНТЕНТ:
- Изображения: конвертируй в webp и сожми перед загрузкой
- Проверь что все ссылки на странице работают
- Проверь мобильную версию (browser_navigate с viewport 375px)

КАЧЕСТВО:
- HTML: проверь валидность (нет незакрытых тегов)
- CSS/JS: минифицируй перед деплоем если возможно
- После деплоя: открой страницу, сделай скриншот, покажи клиенту

КЛИЕНТ:
- Если задача неоднозначная — спроси уточнение через ask_user
- Показывай промежуточные результаты: "Вот дизайн, продолжаем?"
- Предлагай 2-3 варианта если это дизайн/палитра/структура

БЕЗОПАСНОСТЬ:
- НИКОГДА не показывай пароли в ответах пользователю
- Храни credentials только в SSH/FTP подключении, не в тексте
- Проверь SSL после деплоя (curl -I https://)

ДЕПЛОЙ И ПРОИЗВОДИТЕЛЬНОСТЬ:
- nginx: включи gzip (gzip on; gzip_types text/css application/javascript)
- nginx: кэширование статики (expires 30d для css/js/img)
- Изображения: lazy loading (loading="lazy")
- Шрифты: preload и font-display: swap
- Редирект: www → без www (или наоборот)
- SSL: проверь certbot и дату сертификата

ПОСЛЕ ЗАВЕРШЕНИЯ ЗАДАЧИ:
- Напиши краткий отчёт: что сделано, какие файлы изменены, URL
- Покажи скриншот результата на десктопе и мобильном
- Предложи следующие шаги: "Что дальше? 1)... 2)... 3)..."
- Сохрани решение в solution_cache для будущих задач

РАБОТА С НЕСКОЛЬКИМИ ПРОЕКТАМИ:
- Каждый проект — отдельный контекст в памяти
- Не путай доступы между проектами
- Называй проект по домену: "проект test.blacks-art.ru"

ПРАВИЛО НЕЗНАКОМОГО ХОСТИНГА:
Если встретил хостинг которого нет в базе знаний:
1. web_search '[название хостинга] API DNS documentation'
2. Прочитай документацию через web_fetch [URL]
3. Попробуй API запрос на изменение A-записи
4. Если API не работает — зайди в панель через browser_navigate
5. НИКОГДА не говори пользователю 'измените DNS сами' или 'не могу'
6. Используй файл /var/www/orion/backend/data/knowledge_base/hosting_universal.md
   как справочник по популярным хостингам (Beget, Timeweb, REG.RU, Selectel, Hetzner, DigitalOcean, Cloudflare)
7. Используй файл /var/www/orion/backend/data/knowledge_base/beget_browser_steps.md
   как точную инструкцию по автоматизации панели Beget через браузер (селекторы, кнопки, алгоритмы).

ПРАВИЛО НЕЗНАКОМОГО ИНТЕРФЕЙСА:
Если зашёл на незнакомый сайт или панель управления:
1. browser_screenshot — посмотри что на странице
2. Проанализируй скриншот: 'Что на этой странице? Где находится [то что ищу]? Какую кнопку нажать?'
3. browser_click на нужный элемент
4. Повтори: скриншот → анализ → клик
5. Максимум 10 шагов навигации
Ты ВИДИШЬ страницу через скриншоты. Используй это.
Не нужна документация если можешь просто посмотреть и кликнуть.

## ЗАПРЕЩЁННЫЕ ОПЕРАЦИИ В SANDBOX
- НЕ используй subprocess.Popen, os.system, subprocess.call — они ЗАБЛОКИРОВАНЫ sandbox-ом.
- Для выполнения команд на сервере используй ТОЛЬКО ssh_execute.
- Для выполнения Python кода используй ТОЛЬКО code_interpreter.
- Перед деплоем ВСЕГДА проверяй nginx конфиг: ssh_execute('cat /etc/nginx/sites-enabled/* | grep root') чтобы узнать правильный webroot.
- При записи файлов через echo/printf ЭКРАНИРУЙ спецсимволы (!, $, `, \). Лучше используй file_write вместо echo.
- Для записи больших файлов используй file_write — он работает через SFTP и не зависит от shell-экранирования.
- ВАЖНО: file_write имеет ограничение на размер контента в одном вызове (~8000 символов). Если HTML/CSS файл больше — ОБЯЗАТЕЛЬНО используй ssh_execute с Python heredoc: ssh_execute('python3 -c "import base64,os; open(path,\'wb\').write(base64.b64decode(encoded))"') или записывай файл частями через несколько ssh_execute с >> оператором.
- НИКОГДА не пытайся передать весь большой HTML (>200 строк) в одном вызове file_write — он будет обрезан и вернёт ошибку.
"""

# AGENT_SYSTEM_PROMPT_PRO - minimal prompt for smart models (Sonnet, Opus)
AGENT_SYSTEM_PROMPT_PRO = """Ты — автономный AI агент ORION Digital.

Инструменты: ssh_execute, file_write, file_read, 
browser_navigate, browser_click, browser_fill, browser_submit,
browser_check_site, browser_get_text, generate_image, create_artifact, 
generate_file, web_search, web_fetch, ftp_upload, ftp_download,
ftp_list, store_memory, recall_memory, update_scratchpad, task_complete.

Правила:
1. Получил задачу — сделай её от начала до конца.
2. Сначала подумай и составь план.
3. Действуй — не описывай. Не давай инструкции пользователю.
4. Если способ не работает — попробуй другой. Минимум 3 попытки.
5. Проверь результат: открой сайт, сделай скриншот, убедись.
6. Для фото на сайтах — генерируй через generate_image.
7. Завершай только когда ВСЁ сделано. Не пропускай шаги.
8. НЕ ПЕРЕДЕЛЫВАЙ рабочий результат. Сначала выполни ВСЕ пункты ТЗ (DNS, SSL, фото, скриншоты), потом улучшай если остались итерации.

Для дизайна сайтов:
Используй Tailwind CSS (cdn.tailwindcss.com), Google Fonts Inter
(https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800;900).
ОБЯЗАТЕЛЬНО подключи AOS анимации:
  <link href="https://unpkg.com/aos@2.3.1/dist/aos.css" rel="stylesheet">
  <script src="https://unpkg.com/aos@2.3.1/dist/aos.js"></script>
  <script>AOS.init({duration: 800, once: true});</script>
  Добавь data-aos="fade-up" на каждую секцию и карточку.
ОБЯЗАТЕЛЬНО подключи Lucide иконки:
  <script src="https://unpkg.com/lucide@latest"></script>
  <script>lucide.createIcons();</script>
  Используй <i data-lucide="building-2"></i> вместо SVG.
Стиль: градиенты, тени shadow-2xl, hover эффекты, 
скругления rounded-2xl, анимации, backdrop-blur.
Минимум 500 строк HTML. Мобильная версия обязательна.
## PREMIUM DESIGN MODE
Если включён Premium Design:
1. ПЕРЕД созданием HTML — найди 3 сайта конкурентов:
   - web_search "[ниша клиента] лучший сайт дизайн 2025"
   - browser_navigate на 3 лучших результата → скриншоты
   - Проанализируй: что делает их дизайн отличным?
   - "Создай ЛУЧШЕ чем эти 3 сайта"
2. Создай 2 варианта hero секции → выбери лучший
3. Для КАЖДОГО изображения — generate_image с детальным промптом на английском (20-30 слов)
4. После деплоя — 3 цикла самокритики через Opus (автоматически)
Цель: уровень Dribbble/Awwwards.


Для изображений на сайте:
1. Сначала создай полный HTML с placeholder: 
   https://placehold.co/800x600/1a365d/ffffff?text=Photo
2. После деплоя HTML — сгенерируй AI фото через generate_image 
   для каждого placeholder. Промпт на английском, детальный:
   стиль, объект, освещение, настроение, 8k quality.
3. Загрузи сгенерированные фото на сервер через ssh_execute
   (используй curl/wget чтобы скачать с ORION на целевой сервер)
4. Замени placeholder на реальные пути к фото
5. Если generate_image не сработал — оставь placeholder, не ломай сайт

После деплоя:
1. Проверь DNS: ssh_execute('dig +short домен'). 
   Если IP неправильный — зайди в панель хостинга через 
   browser_navigate и измени A-запись. Или используй API хостинга.
   Для Beget: browser_navigate('https://cp.beget.com'), войди, 
   найди DNS и измени A-запись на IP сервера.
2. Настрой SSL: ssh_execute('certbot --nginx -d домен --non-interactive --agree-tos -m admin@домен || certbot certonly --standalone -d домен --non-interactive --agree-tos -m admin@домен')
3. Сделай скриншот сайта на десктопе и мобильном и оцени дизайн.
4. Если оценка < 8/10 — улучши конкретные проблемы (НЕ переделывай с нуля).

## ЗАПРЕЩЁННЫЕ ОПЕРАЦИИ В SANDBOX
- НЕ используй subprocess.Popen, os.system, subprocess.call — они ЗАБЛОКИРОВАНЫ sandbox-ом.
- Для выполнения команд на сервере используй ТОЛЬКО ssh_execute.
- Для выполнения Python кода используй ТОЛЬКО code_interpreter.
- Перед деплоем ВСЕГДА проверяй nginx конфиг: ssh_execute('cat /etc/nginx/sites-enabled/* | grep root') чтобы узнать правильный webroot.
- При записи файлов через echo/printf ЭКРАНИРУЙ спецсимволы (!, $, `, \). Лучше используй file_write вместо echo.
- Для записи больших файлов используй file_write — он работает через SFTP и не зависит от shell-экранирования.
- ВАЖНО: file_write имеет ограничение на размер контента в одном вызове (~8000 символов). Если HTML/CSS файл больше — ОБЯЗАТЕЛЬНО используй ssh_execute с Python heredoc: ssh_execute('python3 -c "import base64,os; open(path,\'wb\').write(base64.b64decode(encoded))"') или записывай файл частями через несколько ssh_execute с >> оператором.
- НИКОГДА не пытайся передать весь большой HTML (>200 строк) в одном вызове file_write — он будет обрезан и вернёт ошибку.
"""

# Pro modes use minimal prompt
PRO_MODES = {"pro_standard", "pro_premium", "architect"}

def get_system_prompt(orion_mode):
    if orion_mode in PRO_MODES:
        return AGENT_SYSTEM_PROMPT_PRO
    return AGENT_SYSTEM_PROMPT






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
                  "browser_check_site", "browser_check_api",
                  "ftp_upload", "ftp_download", "ftp_list"],
        "description": "Серверы, деплой, инфраструктура, FTP",
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
                  "browser_check_api", "browser_click", "browser_fill",
                  "browser_submit", "browser_select", "browser_ask_auth",
                  "code_interpreter", "ssh_execute"],
        "description": "Тестирование, QA, проверка, браузерная автоматизация",
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



def _escape_shell_arg(s):
    """Escape special characters in shell arguments (passwords, etc.)."""
    import shlex
    return shlex.quote(s)

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
                 ssh_credentials=None, orion_mode=None, session_id=None, user_id=None, **kwargs):
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
        self._extra_credentials = {}  # ПАТЧ 1: FTP, админка и др.
        self._solution_cache = None  # ПАТЧ 9: Solution Cache
        self._stop_requested = False

        # ── ORION Sprint 5: режим, сессия, scratchpad, snapshot ──
        self.orion_mode = orion_mode
        self.premium_design = kwargs.get('premium_design', False) or DEFAULT_MODE
        self.session_id = session_id or f"sess_{int(__import__('time').time())}"
        self.scratchpad = []          # Патч 6: промежуточные мысли агента
        self.task_charter = {           # ПАТЧ 24: Task Charter
            "goal": "",
            "pages": [],
            "style": {"colors": [], "fonts": [], "framework": ""},
            "tech_stack": [],
            "status": "planning",
            "phases_completed": [],
            "current_phase": "",
            "quality_score": 0,
            "notes": []
        }
        self._snapshots = []          # Патч 4: снапшоты состояния
        self._ask_user_pending = None # Патч 5: ожидание ответа пользователя
        self._intent_result = None    # Результат intent clarifier
        self._session_cost = 0.0      # Текущая стоимость сессии

        # ПАТЧ A2: model_override и system_prompt_override
        self.model_override = kwargs.get('model_override', None)
        self.custom_system_prompt = kwargs.get('system_prompt_override', None)

        # Artifact tracking for iterative editing
        self._current_artifact_id = None

        # Orchestrator v2 может переопределить модель и промпт
        self._orchestrator_prompt = ""
        self._orchestrator_plan = None

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
            "task_charter": dict(self.task_charter) if hasattr(self, "task_charter") else {},
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
                self.task_charter = snap.get("task_charter", self.task_charter)
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

    def _check_quality_gate(self, phase_name, actions_log):
        """PATCH 25: Quality Gate - check if phase completed successfully."""
        if not actions_log:
            return {"passed": False, "reason": "No actions performed"}
        last_actions = actions_log[-5:]
        errors = [a for a in last_actions if not a.get("success", False)]
        successes = [a for a in last_actions if a.get("success", False)]
        if len(errors) > len(successes):
            return {
                "passed": False,
                "reason": f"Phase '{phase_name}': {len(errors)} errors vs {len(successes)} successes",
                "errors": [str(e.get("tool", "")) for e in errors]
            }
        return {"passed": True, "reason": f"Phase '{phase_name}' passed quality gate"}

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
            # cost = 0.0  # КРИТ-2: REMOVED — now tracking real cost
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
           retryable_exceptions=(ConnectionError, TimeoutError, OSError, Exception),
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
            self.api_url, headers=headers, json=payload, timeout=300
        )

        # Check for retryable HTTP errors
        if resp.status_code in RETRYABLE_HTTP_CODES:
            raise ConnectionError(f"HTTP {resp.status_code}: {resp.text[:200]}")

        if resp.status_code == 400:
            # Log the error body and try to clean messages
            _err_body = resp.text[:500] if resp.text else "empty"
            logger.warning(f"[_call_ai] 400 Bad Request: {_err_body}")
            # Try with cleaned messages
            _cleaned = self._strip_large_content(messages)
            if _cleaned != messages:
                logger.info("[_call_ai] Retrying with cleaned messages")
                payload["messages"] = _cleaned
                resp = http_requests.post(self.api_url, headers=headers, json=payload, timeout=300)
                if resp.status_code != 200:
                    raise ConnectionError(f"HTTP {resp.status_code} even after cleaning: {resp.text[:200]}")
            else:
                raise ConnectionError(f"HTTP 400: {_err_body}")
        else:
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

    def _call_ai_simple(self, messages: list, model: str = None) -> str:
        """Simple non-streaming AI call for memory_v9 internal use."""
        try:
            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
                "HTTP-Referer": "https://orion.mksitdev.ru",
                "X-Title": "ORION Digital v1.0"
            }
            payload = {
                "model": model or self.model,
                "messages": messages,
                "temperature": 0.1,
                "max_tokens": 2000,
                "stream": False,
            }
            resp = http_requests.post(self.api_url, headers=headers, json=payload, timeout=(30, 600))
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

        # ПАТЧ A2: model_override — использовать переопределённую модель если задана
        _model = self.model_override if self.model_override else self.model
        # DUAL-BRAIN: для Turbo режима выбираем модель по следующему tool call
        _orion_mode = getattr(self, 'orion_mode', 'turbo_standard')
        if _orion_mode in ("turbo_standard", "turbo_premium") and not self.model_override:
            # Определяем следующий tool call из последнего assistant сообщения
            _next_tool = None
            for _msg in reversed(messages):
                if _msg.get("role") == "assistant":
                    for _tc in (_msg.get("tool_calls") or []):
                        _next_tool = _tc.get("function", {}).get("name")
                        break
                    break
            if _next_tool:
                _model = _get_dual_brain_model(_next_tool, _orion_mode, _model)
                logging.debug(f"[DUAL-BRAIN] tool={_next_tool} → model={_model}")
            else:
                # Нет tool call → думаем → MiniMax
                if _orion_mode in ("turbo_standard", "turbo_premium"):
                    _model = TURBO_BRAIN_MODEL

        payload = {
            "model": _model,
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
                timeout=(30, 600)
            )

            if resp.status_code in RETRYABLE_HTTP_CODES:
                breaker.record_failure()
                yield {"type": "error", "error": f"LLM API error: HTTP {resp.status_code}"}
                return

            resp.raise_for_status()
            breaker.record_success()

            content = ""
            tool_calls_data = {}

            # PATCH-STREAM-V2: Use threading.Timer to force-close hung streams
            import time as _time
            import threading as _threading
            _stream_deadline = _time.monotonic() + 600  # 10 min max per LLM call
            _stream_timed_out = _threading.Event()

            def _kill_stream():
                _stream_timed_out.set()
                try:
                    resp.close()
                except Exception:
                    pass
                logger.warning("[PATCH-STREAM-V2] Force-closed hung stream after 600s")

            _stream_timer = _threading.Timer(600, _kill_stream)
            _stream_timer.daemon = True
            _stream_timer.start()

            # Also set socket timeout as backup
            try:
                _raw = resp.raw
                if hasattr(_raw, '_fp') and hasattr(_raw._fp, 'fp'):
                    _inner = _raw._fp.fp
                    if hasattr(_inner, 'raw') and hasattr(_inner.raw, '_sock'):
                        _inner.raw._sock.settimeout(300)
                    elif hasattr(_inner, '_sock'):
                        _inner._sock.settimeout(300)
            except Exception:
                pass

            try:
              for line in resp.iter_lines():
                if _stream_timed_out.is_set() or _time.monotonic() > _stream_deadline:
                    logger.warning("[PATCH-STREAM-V2] Stream deadline exceeded, breaking")
                    break
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
            finally:
              _stream_timer.cancel()
              try:
                  resp.close()
              except Exception:
                  pass

            # Fallback: estimate tokens if API didn't return usage
            if self.total_tokens_in == 0 and self.total_tokens_out == 0:
                _est_in = sum(len(str(m.get("content", ""))) // 4 for m in messages)
                _est_out = len(content) // 4
                self.total_tokens_in += _est_in
                self.total_tokens_out += _est_out
                logger.info(f"[TOKEN-EST] Estimated tokens: in={_est_in}, out={_est_out}")

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
            import logging as _log
            # ── Log response body for debugging ──
            _err_body = ""
            if hasattr(e, 'response') and e.response is not None:
                try:
                    _err_body = e.response.text[:500]
                except Exception:
                    pass
            _log.warning(f"[agent_loop] LLM stream error on {self.model}: {e}. Response: {_err_body}")
            
            # ── FALLBACK 1: Strip base64/large content from messages and retry same model ──
            _cleaned_messages = self._strip_large_content(messages)
            if _cleaned_messages != messages:
                _log.info(f"[agent_loop] Retrying with cleaned messages (stripped base64/large content)")
                try:
                    _cl_payload = {"model": self.model, "messages": _cleaned_messages,
                                   "temperature": 0.2, "max_tokens": 16000, "stream": True}
                    if tools:
                        _cl_payload["tools"] = tools
                        _cl_payload["tool_choice"] = "auto"
                    _cl_resp = http_requests.post(self.api_url, headers=headers,
                                                  json=_cl_payload, stream=True, timeout=(30, 600))
                    _cl_resp.raise_for_status()
                    _cl_content = ""
                    _cl_tool_calls_data = {}
                    for _cl_line in _cl_resp.iter_lines():
                        if not _cl_line:
                            continue
                        _cl_ls = _cl_line.decode("utf-8", errors="replace")
                        if not _cl_ls.startswith("data: "):
                            continue
                        _cl_ps = _cl_ls[6:]
                        if _cl_ps.strip() == "[DONE]":
                            break
                        try:
                            _cl_chunk = json.loads(_cl_ps)
                            _cl_choices = _cl_chunk.get("choices", [])
                            if _cl_choices:
                                _cl_delta = _cl_choices[0].get("delta", {})
                                _cl_text = _cl_delta.get("content", "")
                                if _cl_text:
                                    _cl_content += _cl_text
                                    yield {"type": "text_delta", "text": _cl_text}
                                _cl_tc = _cl_delta.get("tool_calls")
                                if _cl_tc:
                                    for _cl_call in _cl_tc:
                                        _cl_idx = _cl_call.get("index", 0)
                                        if _cl_idx not in _cl_tool_calls_data:
                                            _cl_tool_calls_data[_cl_idx] = {"id": _cl_call.get("id", f"call_{_cl_idx}"), "name": "", "arguments": ""}
                                        _cl_fn = _cl_call.get("function", {})
                                        if _cl_fn.get("name"):
                                            _cl_tool_calls_data[_cl_idx]["name"] = _cl_fn["name"]
                                        if _cl_fn.get("arguments"):
                                            _cl_tool_calls_data[_cl_idx]["arguments"] += _cl_fn["arguments"]
                                        if _cl_call.get("id"):
                                            _cl_tool_calls_data[_cl_idx]["id"] = _cl_call["id"]
                        except json.JSONDecodeError:
                            continue
                    if _cl_tool_calls_data:
                        _cl_tool_calls = []
                        for _cl_idx in sorted(_cl_tool_calls_data.keys()):
                            _cl_tc = _cl_tool_calls_data[_cl_idx]
                            _cl_tool_calls.append({"id": _cl_tc["id"], "type": "function", "function": {"name": _cl_tc["name"], "arguments": _cl_tc["arguments"]}})
                        yield {"type": "tool_calls", "tool_calls": _cl_tool_calls, "content": _cl_content}
                        return
                    elif _cl_content:
                        yield {"type": "text_complete", "content": _cl_content}
                        return
                except Exception as _cl_e:
                    _log.warning(f"[agent_loop] Retry with cleaned messages also failed: {_cl_e}")
            
            # ── FALLBACK 2: try different model ──
            _orion_mode_fb = getattr(self, 'orion_mode', 'turbo_standard')
            if _orion_mode_fb in ("turbo_standard", "turbo_premium"):
                # Dual-brain fallback: если HANDS упал → BRAIN, если BRAIN упал → FALLBACK
                if _model == TURBO_HANDS_MODEL:
                    _fallback_model_id = TURBO_BRAIN_MODEL
                elif _model == TURBO_BRAIN_MODEL:
                    _fallback_model_id = TURBO_FALLBACK_MODEL
                else:
                    _fallback_model_id = TURBO_FALLBACK_MODEL
            else:
                _fallback_model_id = "openai/gpt-4.1-nano"
            if self.model != _fallback_model_id and _model != _fallback_model_id:
                _log.warning(f"[agent_loop] Trying fallback model {_fallback_model_id}")
                try:
                    _fb_payload = {"model": _fallback_model_id, "messages": _cleaned_messages or messages,
                                   "temperature": 0.2, "max_tokens": 16000, "stream": True}
                    if tools:
                        _fb_payload["tools"] = tools
                        _fb_payload["tool_choice"] = "auto"
                    _fb_resp = http_requests.post(self.api_url, headers=headers,
                                                  json=_fb_payload, stream=True, timeout=(30, 600))
                    _fb_resp.raise_for_status()
                    _fb_content = ""
                    for _fb_line in _fb_resp.iter_lines():
                        if not _fb_line:
                            continue
                        _fb_ls = _fb_line.decode("utf-8", errors="replace")
                        if not _fb_ls.startswith("data: "):
                            continue
                        _fb_ps = _fb_ls[6:]
                        if _fb_ps.strip() == "[DONE]":
                            break
                        try:
                            _fb_chunk = json.loads(_fb_ps)
                            _fb_choices = _fb_chunk.get("choices", [])
                            if _fb_choices:
                                _fb_text = _fb_choices[0].get("delta", {}).get("content", "")
                                if _fb_text:
                                    _fb_content += _fb_text
                                    yield {"type": "text_delta", "text": _fb_text}
                        except json.JSONDecodeError:
                            continue
                    if _fb_content:
                        yield {"type": "text_complete", "content": _fb_content}
                        return
                except Exception as _fb_e:
                    _log.warning(f"[agent_loop] Fallback model also failed: {_fb_e}")
            yield {"type": "error", "error": str(e)}

    # ── Tool Execution with Retry + Idempotency ──────────────────

    # ── MANUS FEATURE 2: FILE SYSTEM AS CONTEXT ──

    def _strip_large_content(self, messages):
        """Strip base64 images and large content from messages to avoid 400 errors."""
        import copy
        cleaned = []
        changed = False
        for msg in messages:
            new_msg = copy.copy(msg)
            content = msg.get("content", "")
            if isinstance(content, str):
                # Strip base64 data URIs
                if "data:image/" in content and ";base64," in content:
                    new_content = re.sub(r'data:image/[^;]+;base64,[A-Za-z0-9+/=]+', '[IMAGE_REMOVED]', content)
                    if new_content != content:
                        new_msg["content"] = new_content
                        changed = True
                # Strip very long tool results (>10000 chars)
                if len(content) > 10000:
                    new_msg["content"] = content[:5000] + "\n... [TRUNCATED] ...\n" + content[-2000:]
                    changed = True
            elif isinstance(content, list):
                # Handle multimodal content (list of text/image blocks)
                new_parts = []
                for part in content:
                    if isinstance(part, dict):
                        if part.get("type") == "image_url":
                            new_parts.append({"type": "text", "text": "[IMAGE_REMOVED - too large for context]"})
                            changed = True
                        else:
                            new_parts.append(part)
                    else:
                        new_parts.append(part)
                if changed:
                    new_msg["content"] = new_parts
            cleaned.append(new_msg)
        return cleaned if changed else messages

    def _execute_tool(self, tool_name, arguments):
        """Wrapper: выполняет tool и сохраняет большие результаты в файлы."""
        result = self._execute_tool_raw(tool_name, arguments)
        # Пост-обработка: сохраняем большие результаты в файл
        _fs_context_tools = ("ssh_execute", "browser_navigate", "browser_get_text", "web_fetch", "browser_check_site")
        if tool_name in _fs_context_tools and isinstance(result, dict) and result.get("success"):
            try:
                _result_text = json.dumps(result, ensure_ascii=False, default=str)
                if len(_result_text) > 500:
                    _save_path = f"/tmp/orion_result_{tool_name}_{int(time.time())}.txt"
                    with open(_save_path, 'w') as _rf:
                        _rf.write(_result_text)
                    result["_saved_to"] = _save_path
                    result["_original_length"] = len(_result_text)
                    # Обрезать для контекста
                    if "stdout" in result and len(str(result["stdout"])) > 2000:
                        result["stdout"] = str(result["stdout"])[:2000] + "\n... [вывод обрезан до 2000 символов]"
                    if "html" in result and len(str(result["html"])) > 1000:
                        result["html"] = str(result["html"])[:1000] + "\n... [HTML обрезан до 1000 символов]"
                    if "text" in result and len(str(result["text"])) > 2000:
                        result["text"] = str(result["text"])[:2000] + "\n... [текст обрезан до 2000 символов]"
                    if "content" in result and len(str(result["content"])) > 2000:
                        result["content"] = str(result["content"])[:2000] + "\n... [контент обрезан до 2000 символов]"
                    logger.info(f"[FS-CONTEXT] Saved {len(_result_text)} chars to {_save_path}")
            except Exception as _fs_err:
                logger.debug(f"[FS-CONTEXT] Error saving result: {_fs_err}")
        return result

    def _execute_tool_raw(self, tool_name, arguments):
        """Execute a tool with retry and idempotency."""
        try:
            args = json.loads(arguments) if isinstance(arguments, str) and arguments.strip() else (arguments if isinstance(arguments, dict) else {})
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

                # ── ПАТЧ W1-3: Автобэкап перед деструктивными командами ──
                _destructive_patterns = ["rm ", "rm -", "mv ", "> /", "truncate", "dd if="]
                if any(p in command for p in _destructive_patterns):
                    import re as _re
                    _file_paths = _re.findall(r'(/[a-zA-Z0-9_./-]+\.[a-zA-Z0-9]+)', command)
                    for _fp in _file_paths[:3]:
                        try:
                            # BUG-FIX: не делать бэкап .bak файлов (иначе цепочка .bak.bak.bak)
                            if '.bak' in _fp:
                                continue
                            _bak_cmd = f"[ -f {_fp} ] && cp {_fp} {_fp}.bak.$(date +%s) 2>/dev/null || true"
                            self._ssh_execute_with_retry(host, username, password, _bak_cmd)
                            logger.info(f"[PATCH-W1-3] Auto-backup: {_fp}")
                        except Exception:
                            pass

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

                # ── ПАТЧ W1-3: Автобэкап перед перезаписью ──
                try:
                    # BUG-FIX: не делать бэкап .bak файлов (иначе цепочка .bak.bak.bak)
                    if '.bak' not in path:
                        _bak_cmd = f"[ -f {path} ] && cp {path} {path}.bak.$(date +%s) 2>/dev/null || true"
                        self._ssh_execute_with_retry(host, username, password, _bak_cmd)
                        logger.info(f"[PATCH-W1-3] Auto-backup before write: {path}")
                except Exception:
                    pass

                # BUG-13 FIX: Detect broken binary writes
                if content in ('<binary content>', '[binary data]', '') or (len(content) < 100 and 'binary' in content.lower()):
                    return {
                        "success": False, 
                        "error": "Cannot write binary files via file_write. Use ssh_execute with curl/wget to download the image directly to the server. Example: ssh_execute('curl -sL -o /path/to/image.jpg URL')"
                    }
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
                if not path:
                    return {"success": False, "error": "path is required"}

                # If path is a local ORION temp file, read locally
                if path.startswith("/tmp/orion_result_") or path.startswith("/tmp/orion_todo_"):
                    try:
                        with open(path, 'r') as _lf:
                            _local_content = _lf.read()
                        result = {"success": True, "content": _local_content, "path": path}
                    except FileNotFoundError:
                        result = {"success": False, "error": f"Local file not found: {path}"}
                    except Exception as _lfe:
                        result = {"success": False, "error": f"Error reading local file: {_lfe}"}
                elif not host:
                    return {"success": False, "error": "host is required for remote file_read"}
                else:
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

            # ── ЗАДАЧА-1: Интерактивная браузерная автоматизация ─────────────────────────

            elif tool_name == "browser_click":
                selector = args.get("selector", "")
                if not selector:
                    return {"success": False, "error": "selector is required"}
                result = self.browser.click(selector)
                # Добавить скриншот в browser_tools для SSE
                return result

            elif tool_name == "browser_fill":
                selector = args.get("selector", "")
                value = args.get("value", "")
                if not selector:
                    return {"success": False, "error": "selector is required"}
                return self.browser.fill(selector, value)

            elif tool_name == "browser_submit":
                selector = args.get("selector")  # Может быть None
                return self.browser.submit(selector)

            elif tool_name == "browser_select":
                selector = args.get("selector", "")
                value = args.get("value", "")
                if not selector or not value:
                    return {"success": False, "error": "selector and value are required"}
                return self.browser.select(selector, value)

            elif tool_name == "browser_ask_auth":
                # ЗАДАЧА-1: browser_ask_auth — обнаружить форму логина и запросить данные у пользователя
                url = args.get("url")
                hint = args.get("hint", "")
                detect_result = self.browser.detect_login_form(url)
                if not detect_result.get("success"):
                    return detect_result
                # Возвращаем специальный результат с type=auth_required для SSE
                return {
                    "success": True,
                    "_auth_required": True,  # Сигнал для run_stream чтобы отправить SSE
                    "url": detect_result.get("url", url or ""),
                    "screenshot": detect_result.get("screenshot"),
                    "fields": detect_result.get("fields", []),
                    "hint": hint,
                    "submit_selector": detect_result.get("submit_selector"),
                    "is_login_form": detect_result.get("is_login_form", False)
                }

            # ── Новые browser инструменты v2 ──────────────────────────
            elif tool_name == "browser_type":
                selector = args.get("selector", "")
                value = args.get("value", "")
                clear = args.get("clear", True)
                if isinstance(clear, str):
                    clear = clear.lower() in ("true", "1", "yes")
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
                if not url or not login or not password:
                    return {"success": False, "error": "url, login, and password are required"}
                return self.browser.smart_login(url, login, password)
            elif tool_name == "browser_ask_user":
                reason = args.get("reason", "custom")
                instruction = args.get("instruction", "")
                return self.browser.ask_user(reason, instruction)
            elif tool_name == "browser_takeover_done":
                return self.browser.takeover_done()
            # ── ЗАДАЧА-1: FTP инструменты ────────────────────────────────────────

            elif tool_name == "ftp_upload":
                host = args.get("host", "")
                username = args.get("username", "")
                password = args.get("password", "")
                remote_path = args.get("remote_path", "")
                content = args.get("content", "")
                port = int(args.get("port", 21))
                if not all([host, username, password, remote_path]):
                    return {"success": False, "error": "host, username, password, remote_path are required"}
                return self.browser.ftp_upload(host, username, password, remote_path, content, port)

            elif tool_name == "ftp_download":
                host = args.get("host", "")
                username = args.get("username", "")
                password = args.get("password", "")
                remote_path = args.get("remote_path", "")
                port = int(args.get("port", 21))
                if not all([host, username, password, remote_path]):
                    return {"success": False, "error": "host, username, password, remote_path are required"}
                result = self.browser.ftp_download(host, username, password, remote_path, port)
                if result.get("content") and len(result["content"]) > self.MAX_TOOL_OUTPUT:
                    result["content"] = result["content"][:self.MAX_TOOL_OUTPUT] + "... [truncated]"
                return result

            elif tool_name == "ftp_list":
                host = args.get("host", "")
                username = args.get("username", "")
                password = args.get("password", "")
                remote_path = args.get("remote_path", "/")
                port = int(args.get("port", 21))
                if not all([host, username, password]):
                    return {"success": False, "error": "host, username, password are required"}
                return self.browser.ftp_list(host, username, password, remote_path, port)

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
                    # BUG-13 FIX: Add deploy instructions for remote servers
                    if result.get("success") and result.get("file_id"):
                        fid = result["file_id"]
                        orion_url = "https://orion.mksitdev.ru"
                        result["deploy_hint"] = (
                            f"Файл сохранён локально. Для деплоя на удалённый сервер используй "
                            f"ssh_execute: curl -sL -o /путь/к/{filename} "
                            f"\'{orion_url}/api/files/{fid}/download\'"
                        )
                        result["download_command"] = (
                            f"curl -sL -o /path/to/{filename} "
                            f"\'{orion_url}/api/files/{fid}/download\'"
                        )
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

            elif tool_name == "update_scratchpad":
                content = args.get("content", "")
                category = args.get("category", "thought")
                if hasattr(self, 'scratchpad_add'):
                    self.scratchpad_add(content, category)
                return {"success": True, "message": f"Scratchpad updated: [{category}] {content[:100]}"}
            elif tool_name == "update_task_charter":
                field = args.get("field", "")
                value_str = args.get("value", "")
                try:
                    import json as _json24
                    value = _json24.loads(value_str)
                except:
                    value = value_str
                if hasattr(self, 'task_charter') and field in self.task_charter:
                    if isinstance(self.task_charter[field], list) and isinstance(value, str):
                        self.task_charter[field].append(value)
                    else:
                        self.task_charter[field] = value
                    return {"success": True, "field": field, "updated": True, "charter": self.task_charter}
                else:
                    return {"success": False, "error": f"Unknown charter field: {field}"}
            elif tool_name == "update_scratchpad":
                content = args.get("content", "")
                category = args.get("category", "thought")
                if hasattr(self, 'scratchpad_add'):
                    self.scratchpad_add(content, category)
                return {"success": True, "message": f"Scratchpad updated: [{category}] {content[:100]}"}
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
           retryable_exceptions=(ConnectionError, TimeoutError, OSError, Exception),
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
        except Exception as _ocr_err:
            logging.warning(f"OCR/file_reader error: {_ocr_err}")

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
        """Generate image using AI via OpenRouter (chat/completions + modalities)."""
        import uuid as _uuid
        import requests as _img_req
        import base64

        GENERATED_DIR = os.environ.get("GENERATED_DIR", "/var/www/orion/backend/generated")
        os.makedirs(GENERATED_DIR, exist_ok=True)

        file_id = str(_uuid.uuid4())[:12]
        filepath = os.path.join(GENERATED_DIR, f"{file_id}_{filename}")

        api_key = os.environ.get("OPENROUTER_API_KEY", "")
        _api_url = "https://openrouter.ai/api/v1/chat/completions"
        _headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://orion.mksitdev.ru",
            "X-Title": "ORION Digital",
        }
        image_data = None

        def _extract_image_from_response(data):
            """Extract base64 image bytes from OpenRouter chat/completions response."""
            choices = data.get("choices", [])
            if not choices:
                return None
            msg = choices[0].get("message", {})
            images = msg.get("images", [])
            if not images:
                return None
            url = images[0].get("image_url", {}).get("url", "")
            if not url:
                return None
            if ";base64," in url:
                b64_str = url.split(";base64,", 1)[1]
            else:
                b64_str = url
            return base64.b64decode(b64_str)

        # ── Способ 1: Flux через OpenRouter ──
        if api_key and not image_data:
            try:
                resp = _img_req.post(
                    _api_url,
                    headers=_headers,
                    json={
                        "model": "black-forest-labs/flux.2-pro",
                        "messages": [{"role": "user", "content": prompt}],
                        "modalities": ["image"],
                    },
                    timeout=90,
                )
                if resp.status_code == 200:
                    data = resp.json()
                    if "error" in data:
                        logging.warning(f"[ImageGen] Flux API error: {data['error']}")
                    else:
                        image_data = _extract_image_from_response(data)
                        if image_data:
                            logging.info(f"[ImageGen] Flux OK: {len(image_data)} bytes")
                        else:
                            logging.warning("[ImageGen] Flux: no image in response")
                else:
                    logging.warning(f"[ImageGen] Flux returned {resp.status_code}: {resp.text[:200]}")
            except Exception as e:
                logging.warning(f"[ImageGen] Flux failed: {e}")

        # ── Способ 2: DALL-E 3 через OpenRouter ──
        if api_key and not image_data:
            try:
                resp = _img_req.post(
                    _api_url,
                    headers=_headers,
                    json={
                        "model": "openai/dall-e-3",
                        "messages": [{"role": "user", "content": prompt}],
                        "modalities": ["image"],
                    },
                    timeout=120,
                )
                if resp.status_code == 200:
                    data = resp.json()
                    if "error" in data:
                        logging.warning(f"[ImageGen] DALL-E API error: {data['error']}")
                    else:
                        image_data = _extract_image_from_response(data)
                        if image_data:
                            logging.info(f"[ImageGen] DALL-E OK: {len(image_data)} bytes")
                        else:
                            logging.warning("[ImageGen] DALL-E: no image in response")
                else:
                    logging.warning(f"[ImageGen] DALL-E returned {resp.status_code}: {resp.text[:200]}")
            except Exception as e:
                logging.warning(f"[ImageGen] DALL-E failed: {e}")

        # ── Способ 3: Flux Klein (дешёвый fallback $0.003) ──
        if api_key and not image_data:
            try:
                resp = _img_req.post(
                    _api_url,
                    headers=_headers,
                    json={
                        "model": "black-forest-labs/flux.2-klein-4b",
                        "messages": [{"role": "user", "content": prompt}],
                        "modalities": ["image"],
                    },
                    timeout=90,
                )
                if resp.status_code == 200:
                    data = resp.json()
                    if "error" not in data:
                        image_data = _extract_image_from_response(data)
                        if image_data:
                            logging.info(f"[ImageGen] Flux Klein OK: {len(image_data)} bytes")
                        else:
                            logging.warning("[ImageGen] Flux Klein: no image in response")
                else:
                    logging.warning(f"[ImageGen] Flux Klein returned {resp.status_code}")
            except Exception as e:
                logging.warning(f"[ImageGen] Flux Klein failed: {e}")

        # ── Способ 4: Fallback — улучшенный placeholder ──
        if not image_data:
            logging.warning("[ImageGen] All AI APIs failed, using placeholder")
            try:
                from PIL import Image, ImageDraw, ImageFont
                import random

                img = Image.new('RGB', (1024, 768), color='#1a1a2e')
                draw = ImageDraw.Draw(img)

                for y in range(768):
                    r = int(26 + (y / 768) * 40)
                    g = int(26 + (y / 768) * 20)
                    b = int(46 + (y / 768) * 60)
                    draw.line([(0, y), (1024, y)], fill=(r, g, b))

                for _ in range(20):
                    x = random.randint(50, 974)
                    y = random.randint(50, 718)
                    rad = random.randint(15, 60)
                    color = random.choice([
                        (99, 102, 241), (139, 92, 246), (167, 139, 250),
                        (196, 181, 253), (16, 185, 129), (245, 158, 11)
                    ])
                    draw.ellipse([x - rad, y - rad, x + rad, y + rad], fill=(*color, 60))

                try:
                    font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 22)
                    font_sm = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 13)
                except Exception:
                    font = ImageFont.load_default()
                    font_sm = font

                lines_text = []
                words = prompt.split()
                line = ""
                for w in words:
                    if len(line + " " + w) > 45:
                        lines_text.append(line)
                        line = w
                    else:
                        line = (line + " " + w).strip()
                if line:
                    lines_text.append(line)

                y_pos = 320
                for ln in lines_text[:4]:
                    draw.text((50, y_pos), ln, fill='white', font=font)
                    y_pos += 32

                draw.text((50, 730), "ORION Digital | Placeholder (AI API unavailable)",
                          fill='#666666', font=font_sm)

                import io
                buf = io.BytesIO()
                img.save(buf, format='PNG')
                image_data = buf.getvalue()
            except Exception as e:
                return {"success": False, "error": f"All methods failed: {e}"}

        # ── Сохранить файл ──
        with open(filepath, 'wb') as f:
            f.write(image_data)

        size = os.path.getsize(filepath)

        try:
            from file_generator import _register_file
            _register_file(file_id, filename, filepath, "png", size,
                          getattr(self, '_chat_id', None),
                          getattr(self, '_user_id', None))
        except Exception as _mem_err:
            logging.warning(f"Memory save error: {_mem_err}")

        return {
            "success": True,
            "file_id": file_id,
            "filename": filename,
            "size": size,
            "download_url": f"/api/files/{file_id}/download",
            "preview_url": f"/api/files/{file_id}/preview"
        }

    # ── Web Search & Fetch ──────────────────────────────────────────

    @retry(max_attempts=2, base_delay=1.0, max_delay=5.0, jitter=0.5,
           retryable_exceptions=(ConnectionError, TimeoutError, OSError, Exception),
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
           retryable_exceptions=(ConnectionError, TimeoutError, OSError, Exception),
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
            except Exception as _rm_err:
                logging.warning(f"File cleanup error: {_rm_err}")
            
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
            except Exception as _rm_err:
                logging.warning(f"File cleanup error: {_rm_err}")

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
            except Exception as _mem_err:
                logging.warning(f"Memory save error: {_mem_err}")
            
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
        except Exception as _mem_err:
            logging.warning(f"Memory save error: {_mem_err}")
        
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

    def _verify_with_second_llm(self, task: str, result_text: str, actions: list) -> dict:
        """
        ПАТЧ 7: Проверка результата вторым LLM (Mixture-of-Agents).
        Вызывается только если verify=True и режим Pro+.
        """
        try:
            actions_summary = "\n".join(
                f"{'✅' if a.get('success') else '❌'} {a.get('tool','')}: {str(a.get('args',{}))[:100]}"
                for a in actions[-15:]
            )
            verify_messages = [
                {"role": "system", "content": (
                    "Ты — QA-ревьюер. Проверь результат работы агента. "
                    "Ответь СТРОГО JSON: {\"verified\": true/false, \"issues\": [\"проблема1\", ...], \"summary\": \"краткий вывод\"}. "
                    "Без markdown, без пояснений, только JSON."
                )},
                {"role": "user", "content": (
                    f"Задача: {task[:500]}\n\n"
                    f"Действия агента:\n{actions_summary}\n\n"
                    f"Результат: {result_text[:1000]}\n\n"
                    "Проверь: всё ли сделано? Есть ли ошибки? Файлы созданы? Результат корректный?"
                )}
            ]
            resp = self._call_ai_simple(verify_messages, model="anthropic/claude-sonnet-4.6")
            if resp:
                resp = resp.strip()
                if resp.startswith("```"):
                    resp = resp.split("\n", 1)[1].rsplit("```", 1)[0]
                return json.loads(resp)
        except Exception as _v7_err:
            logger.warning(f"PATCH7 verification error: {_v7_err}")
        return {"verified": True, "issues": [], "summary": "Проверка не удалась, считаем ОК"}

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

    def _analyze_screenshot_auto(self, screenshot_base64: str, url: str = "") -> str:
        """
        ПАТЧ W1-5: Автоматический анализ скриншота страницы.
        Использует vision model для понимания что на странице.
        """
        try:
            if not screenshot_base64:
                return ""
            _b64 = screenshot_base64
            if "base64," in _b64:
                _b64 = _b64.split("base64,")[1]

            _messages = [
                {"role": "system", "content": (
                    "Ты анализируешь скриншот веб-страницы. Кратко опиши (2-4 предложения): "
                    "1) Что это за страница, 2) Основные элементы (шапка, контент, формы, кнопки), "
                    "3) Есть ли ошибки (404, 500, пустая страница, сломанная вёрстка). "
                    "Отвечай на русском, кратко."
                )},
                {"role": "user", "content": [
                    {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{_b64}"}},
                    {"type": "text", "text": f"Что на этом скриншоте? URL: {url}"}
                ]}
            ]

            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
                "HTTP-Referer": "https://orion.mksitdev.ru",
                "X-Title": "ORION Digital v1.0"
            }
            payload = {
                "model": "anthropic/claude-sonnet-4.6",
                "messages": _messages,
                "temperature": 0.1,
                "max_tokens": 500,
                "stream": False,
            }
            resp = http_requests.post(self.api_url, headers=headers, json=payload, timeout=15)
            if resp.status_code == 200:
                data = resp.json()
                return data.get("choices", [{}])[0].get("message", {}).get("content", "")
        except Exception as e:
            logger.debug(f"[PATCH-W1-5] Vision analysis error: {e}")
        return ""

    # ── SSE Helpers ──────────────────────────────────────────────────────


    def _check_force_tool(self, user_message, file_content=""):
        """Проверить нужен ли принудительный вызов инструмента.
        Если запрос ОЧЕВИДНО требует инструмент — вызвать напрямую,
        не спрашивая LLM (DeepSeek может отказаться).
        """
        msg = user_message.lower().strip()
        events = []

        # ── Генерация изображения ──
        _image_triggers = [
            "сделай картинк", "создай картинк", "нарисуй", "сгенерируй изображен",
            "сделай фото", "создай фото", "сделай изображен", "создай изображен",
            "сделай иллюстрац", "создай иллюстрац", "нарисуй мне",
            "сделай баннер", "создай баннер", "сделай постер", "создай постер",
            "сделай лого", "создай лого", "сделай иконк", "создай иконк",
            "make image", "create image", "generate image", "draw",
        ]

        if any(t in msg for t in _image_triggers):
            prompt = user_message
            try:
                result = self._generate_image(prompt, style="illustration")
                if result and result.get("success"):
                    events.append(self._sse({
                        "type": "tool_start",
                        "tool": "generate_image",
                        "args": {"prompt": prompt[:100]}
                    }))
                    dl_url = result.get("download_url", result.get("preview_url", ""))
                    events.append(self._sse({
                        "type": "tool_result",
                        "tool": "generate_image",
                        "success": True,
                        "preview": "Изображение создано: " + result.get("filename", "image.png")
                    }))
                    if dl_url:
                        events.append(self._sse({
                            "type": "file",
                            "filename": result.get("filename", "image.png"),
                            "url": dl_url,
                            "size": result.get("size", 0)
                        }))
                    events.append(self._sse({
                        "type": "content",
                        "text": "Изображение создано!\n\n![" + prompt[:50] + "](" + dl_url + ")"
                    }))
                    return events
            except Exception as e:
                logger.warning(f"Force generate_image failed: {e}")
                return None

        # ── Дизайн (баннер для Instagram и т.д.) ──
        # Skip force_tool if message contains SSH/deploy instructions
        _skip_force_kw = ["ssh", "deploy", "деплой", "сервер", "nginx", "root@", "задеплой"]
        if any(kw in msg for kw in _skip_force_kw):
            return None
        _design_triggers = [
            "баннер для instagram", "баннер для инстаграм", "пост для instagram",
            "пост для инстаграм", "обложк", "флаер", "плакат",
        ]

        if any(t in msg for t in _design_triggers):
            try:
                from artifact_generator import ArtifactGenerator
                gen = ArtifactGenerator()
                result = gen.design(design_type="banner", description=user_message)
                if result and result.get("success"):
                    events.append(self._sse({"type": "tool_start", "tool": "generate_design", "args": {"description": user_message[:100]}}))
                    dl_url = result.get("download_url", result.get("preview_url", ""))
                    events.append(self._sse({
                        "type": "tool_result",
                        "tool": "generate_design",
                        "success": True,
                        "preview": "Дизайн создан: " + result.get("filename", "design.html")
                    }))
                    if dl_url:
                        events.append(self._sse({
                            "type": "file",
                            "filename": result.get("filename", "design.html"),
                            "url": dl_url,
                            "size": result.get("size", 0)
                        }))
                    events.append(self._sse({
                        "type": "content",
                        "text": "Дизайн создан!\n\n[Открыть дизайн](" + dl_url + ")"
                    }))
                    return events
            except Exception as e:
                logger.warning(f"Force generate_design failed: {e}")
                return None

        # ── Код → файл (НЕ в чат) ──
        _code_triggers = [
            "напиши скрипт", "напиши код", "создай скрипт", "напиши программ",
            "напиши парсер", "напиши бот", "создай api", "напиши функци",
        ]

        if any(t in msg for t in _code_triggers):
            self._force_file_save = True
            return None

        return None

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

        # ── ЗАДАЧА-1: Превью для новых инструментов ──
        elif tool_name == "browser_click":
            selector = result.get("clicked", "")
            url_after = result.get("url_after", "")
            return f"💌 Клик по '{selector}' | URL: {url_after}"

        elif tool_name == "browser_fill":
            selector = result.get("filled", "")
            val_len = result.get("value_length", 0)
            return f"✏️ Поле '{selector}' заполнено ({val_len} символов)"

        elif tool_name == "browser_submit":
            url_before = result.get("url_before", "")
            url_after = result.get("url_after", "")
            navigated = result.get("navigated", False)
            nav_str = f" → {url_after}" if navigated else " (страница не изменилась)"
            return f"🚀 Форма отправлена{nav_str}"

        elif tool_name == "browser_select":
            selector = result.get("selected", "")
            value = result.get("value", "")
            return f"📋 Выбрано '{value}' в '{selector}'"

        elif tool_name == "browser_ask_auth":
            fields = result.get("fields", [])
            hint = result.get("hint", "")
            return f"🔐 Форма авторизации обнаружена ({len(fields)} полей) {hint}"

        elif tool_name == "browser_type":
            selector = result.get("selector", "")
            chars = result.get("chars_typed", 0)
            return f"⌨️ Ввод в '{selector}' ({chars} символов)"
        elif tool_name == "browser_js":
            ret = str(result.get("return_value", ""))[:100]
            return f"🔧 JS выполнен: {ret}"
        elif tool_name == "browser_press_key":
            key = result.get("key", "")
            return f"⌨️ Нажата клавиша: {key}"
        elif tool_name == "browser_scroll":
            direction = result.get("direction", "")
            return f"📜 Прокрутка: {direction}"
        elif tool_name == "browser_hover":
            selector = result.get("selector", "")
            return f"🖱️ Наведение на '{selector}'"
        elif tool_name == "browser_wait":
            waited = result.get("waited_ms", 0)
            return f"⏳ Ожидание: {waited}ms"
        elif tool_name == "browser_elements":
            count = result.get("count", 0)
            return f"📋 Найдено {count} элементов"
        elif tool_name == "browser_screenshot":
            url = result.get("url", "")
            has_img = "📸" if result.get("screenshot") else "❌"
            return f"{has_img} Скриншот: {url}"
        elif tool_name == "browser_page_info":
            title = result.get("title", "")
            url = result.get("url", "")
            return f"📄 Страница: {title} | {url}"
        elif tool_name == "smart_login":
            logged = result.get("logged_in", False)
            url = result.get("url_after", "")
            status = "✅ Вход выполнен" if logged else "❌ Вход не удался"
            return f"🔐 {status} | {url}"
        elif tool_name == "browser_ask_user":
            reason = result.get("reason", "")
            return f"👤 Запрос пользователю: {reason}"
        elif tool_name == "browser_takeover_done":
            return "✅ Управление возвращено агенту"
        elif tool_name == "ftp_upload":
            path = result.get("remote_path", "")
            size = result.get("size_bytes", 0)
            return f"📤 FTP загрузка: {path} ({size} байт)"

        elif tool_name == "ftp_download":
            path = result.get("remote_path", "")
            size = result.get("size_bytes", 0)
            return f"📥 FTP скачано: {path} ({size} байт)"

        elif tool_name == "ftp_list":
            count = result.get("count", 0)
            path = result.get("path", "/")
            return f"📂 FTP список: {path} — {count} элементов"

        return "✅ Выполнено"

    # ══════════════════════════════════════════════════════════════
    # ██ MAIN STREAMING LOOP (backward-compatible API) ██
    # ══════════════════════════════════════════════════════════════


    def _search_knowledge_base(self, query: str, top_k: int = 3) -> str:
        """Search local knowledge base for relevant information."""
        import os
        KB_DIR = "/var/www/orion/backend/data/knowledge_base"
        if not os.path.isdir(KB_DIR):
            return ""
        query_lower = query.lower()
        results = []
        for filename in os.listdir(KB_DIR):
            if not filename.endswith('.md'):
                continue
            filepath = os.path.join(KB_DIR, filename)
            try:
                with open(filepath, 'r') as f:
                    file_content = f.read()
                content_lower = file_content.lower()
                score = 0
                for word in query_lower.split():
                    if len(word) > 3 and word in content_lower:
                        score += content_lower.count(word)
                if score > 0:
                    sections = file_content.split('\n## ')
                    best_section = ""
                    best_score = 0
                    for section in sections:
                        s_score = sum(1 for w in query_lower.split() if len(w) > 3 and w in section.lower())
                        if s_score > best_score:
                            best_score = s_score
                            best_section = section[:1000]
                    if best_section:
                        results.append((score, filename, best_section))
            except Exception:
                continue
        if not results:
            return ""
        results.sort(reverse=True)
        kb_context = "\nИНФОРМАЦИЯ ИЗ БАЗЫ ЗНАНИЙ:\n\n"
        for score, fname, section in results[:top_k]:
            kb_context += f"--- {fname} ---\n{section}\n\n"
        return kb_context


    def _extract_project_decisions(self, messages, response):
        """Извлечь ключевые решения из чата для project memory."""
        decisions = []
        files = []
        urls = []
        techs = []
        text = response.lower()
        import re as _re
        file_matches = _re.findall(r'(?:создал|записал|сохранил).*?(/\S+\.\w+)', text)
        files.extend(file_matches)
        url_matches = _re.findall(r'https?://\S+', response)
        urls.extend(url_matches[:5])
        tech_keywords = ['python', 'fastapi', 'flask', 'django', 'react', 'vue', 'nginx',
                         'docker', 'postgresql', 'mysql', 'redis', 'bitrix', 'wordpress',
                         'node.js', 'express', 'laravel', 'php']
        for tech in tech_keywords:
            if tech in text:
                techs.append(tech)
        return decisions, files, urls, techs

    def _get_thinking_text(self, tool_name: str, tool_args: dict) -> str:
        try:
            if tool_name == 'ssh_execute':
                cmd = tool_args.get('command', '')
                if cmd:
                    return 'Выполняю: ' + cmd[:80] + ('...' if len(cmd) > 80 else '')
                return 'SSH подключение'
            elif tool_name == 'file_write':
                return 'Создаю файл: ' + tool_args.get('path', '')
            elif tool_name == 'file_read':
                return 'Читаю файл: ' + tool_args.get('path', '')
            elif tool_name in ('browser_navigate', 'browser_check_site'):
                url = tool_args.get('url', '')
                return 'Открываю: ' + url[:60]
            elif tool_name == 'browser_screenshot':
                return 'Делаю скриншот страницы'
            elif tool_name == 'browser_click':
                return 'Кликаю: ' + str(tool_args.get('selector', tool_args.get('text', '')))
            elif tool_name == 'browser_fill':
                return 'Заполняю поле: ' + str(tool_args.get('selector', ''))
            elif tool_name == 'generate_image':
                return 'Генерирую изображение: ' + str(tool_args.get('prompt', ''))[:60]
            elif tool_name == 'task_complete':
                return 'Завершаю задачу...'
            elif tool_name == 'update_scratchpad':
                return 'Обновляю план задачи'
            elif tool_name == 'search_web':
                return 'Ищу: ' + str(tool_args.get('query', ''))[:60]
            elif tool_name == 'read_url':
                return 'Читаю страницу: ' + str(tool_args.get('url', ''))[:60]
            else:
                return ''
        except Exception:
            return ''
    def run_stream(self, user_message, chat_history=None, file_content=None, ssh_credentials=None):
        """
        Run the agent loop with streaming.
        Yields SSE events for real-time display.

        This is the main entry point — backward-compatible with v4.0 API.
        Internally uses LangGraph StateGraph for state management.
        """
        if chat_history is None:
            chat_history = []

        # Override SSH credentials if passed from caller
        if ssh_credentials:
            self.ssh_credentials = ssh_credentials

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
                    yield self._sse({
                        "type": "error",
                        "error": (f"Лимит стоимости сессии превышен: "
                                  f"${cost_check['current_cost']:.3f} / "
                                  f"${cost_check['max_cost']:.2f}. "
                                  f"Начните новую сессию.")
                    })
                    return
                # Emit intent info для UI
                intent_label = format_clarification_for_user(self._intent_result)
                yield self._sse({"type": "intent", "data": self._intent_result, "label": intent_label})
                # Если нужно уточнение — спрашиваем
                if self._intent_result.get("needs_clarification"):
                    q = self._intent_result.get("clarification_question", "Уточните задачу.")
                    yield self._sse(self.ask_user(q))
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

        # ПАТЧ A2 + Orchestrator v2: custom_system_prompt и _orchestrator_prompt
        # ══ PRE-CHECK: set _force_file_save flag before prompt building ══
        _msg_lower_pre = user_message.lower().strip()
        _code_triggers_pre = [
            "напиши скрипт", "напиши код", "создай скрипт", "напиши программ",
            "напиши парсер", "напиши бот", "создай api", "напиши функци",
        ]
        if any(t in _msg_lower_pre for t in _code_triggers_pre):
            self._force_file_save = True

        _effective_system_prompt = get_system_prompt(self.orion_mode)
        # BUG-4 FIX: Search Knowledge Base
        try:
            _kb_context = self._search_knowledge_base(user_message if isinstance(user_message, str) else str(user_message))
            if _kb_context:
                _effective_system_prompt += _kb_context
                logging.info(f"[KB] Found relevant knowledge base content ({len(_kb_context)} chars)")
        except Exception as _kb_err:
            logging.warning(f"[KB] Error searching knowledge base: {_kb_err}")
        # Добавить промпт от оркестратора (специфичный для агента)
        if hasattr(self, '_orchestrator_prompt') and self._orchestrator_prompt:
            _effective_system_prompt = self._orchestrator_prompt + "\n\n" + AGENT_SYSTEM_PROMPT
        # Добавить custom_system_prompt (от старого ПАТЧ A2)
        if self.custom_system_prompt:
            _effective_system_prompt = _effective_system_prompt + "\n\n" + self.custom_system_prompt
        # ══ PATCH 2: Force file save — усиленный промпт для кода ══
        if hasattr(self, '_force_file_save') and self._force_file_save:
            _effective_system_prompt += """

КРИТИЧНО: Пользователь просит написать код.
1. НЕ ПИШИ весь код в чат — это неудобно
2. СОХРАНИ код в файл через file_write
3. ДАЙ ссылку на скачивание
4. В чат напиши только краткое описание что сделал

Порядок: file_write → краткое описание → ссылка на скачивание.
"""
            self._force_file_save = False


        # ── AutoSummary: загрузить ВСЕ резюме прошлых чатов (без фильтра по query) ──
        _project_summaries = ""
        if self.memory:
            try:
                # Загружаем ВСЕ summary без семантического фильтра (recall_all)
                _all_summaries = []
                if hasattr(self.memory, 'recall_all'):
                    _all_summaries = self.memory.recall_all(
                        category="project_summary",
                        limit=100
                    )
                if not _all_summaries:
                    # Fallback: семантический поиск с увеличенным top_k
                    _all_summaries = self.memory.recall(
                        query=user_message,
                        category="project_summary",
                        top_k=50
                    )
                if _all_summaries:
                    _project_summaries = "ИСТОРИЯ ПРОЕКТА (резюме прошлых чатов):\n"
                    if isinstance(_all_summaries, list):
                        for s in _all_summaries:
                            _project_summaries += f"- {s}\n"
                    elif isinstance(_all_summaries, str):
                        _project_summaries += _all_summaries
                # Загружаем ВСЕ решения без фильтра
                _all_decisions = []
                if hasattr(self.memory, 'recall_all'):
                    _all_decisions = self.memory.recall_all(
                        category="project_decisions",
                        limit=50
                    )
                if not _all_decisions:
                    _all_decisions = self.memory.recall(
                        query=user_message,
                        category="project_decisions",
                        top_k=30
                    )
                if _all_decisions:
                    _project_summaries += "\nКЛЮЧЕВЫЕ РЕШЕНИЯ:\n"
                    if isinstance(_all_decisions, list):
                        for d in _all_decisions:
                            _project_summaries += f"- {d}\n"
                    elif isinstance(_all_decisions, str):
                        _project_summaries += _all_decisions
                if _all_summaries or _all_decisions:
                    logging.info(f"[ProjectSummary] Loaded {len(_all_summaries) if isinstance(_all_summaries, list) else 1} summaries, {len(_all_decisions) if isinstance(_all_decisions, list) else 0} decisions")
            except Exception as _psum_err:
                logging.warning(f"[ProjectSummary] Load failed: {_psum_err}")
        if _project_summaries:
            _effective_system_prompt += "\n\n" + _project_summaries
            # LTM INDICATOR: отправить SSE event с тем что вспомнили
            try:
                _mem_lines = [l.strip() for l in _project_summaries.split("\n") if l.strip() and not l.startswith("ИСТОРИЯ") and not l.startswith("КЛЮЧЕВЫЕ")]
                _mem_preview = _mem_lines[:5] if _mem_lines else []
                if _mem_preview:
                    yield self._sse({"type": "memory_context", "items": _mem_preview, "total": len(_mem_lines)})
            except Exception as _ltm_sse_err:
                pass


        # ── Extended Thinking: анализ перед выполнением сложных задач ──
        if hasattr(self, '_orchestrator_plan') and self._orchestrator_plan and self._orchestrator_plan.get("mode") != "chat":
            try:
                thinking_prompt = f"""Перед выполнением задачи, подумай:
1. Какой лучший подход?
2. Какие могут быть проблемы?
3. Какие технологии использовать?
4. В каком порядке действовать?

Задача: {user_message}

Думай вслух, коротко (3-5 пунктов)."""
                yield self._sse({"type": "thinking_start"})
                thinking_messages = [
                    {"role": "system", "content": "Ты архитектор. Кратко проанализируй задачу."},
                    {"role": "user", "content": thinking_prompt}
                ]
                thinking_result = self._call_ai_simple(thinking_messages)
                if thinking_result:
                    yield self._sse({"type": "thinking", "content": thinking_result})
                    _effective_system_prompt += f"\n\nТВОЙ АНАЛИЗ ЗАДАЧИ:\n{thinking_result}\n\nТеперь ВЫПОЛНЯЙ по этому плану."
                yield self._sse({"type": "thinking_end"})
            except Exception as _think_err:
                logging.warning(f"[Thinking] Failed: {_think_err}")

        # Build initial messages
        if self.memory:
            try:
                messages = self.memory.build_messages(
                    system_prompt=_effective_system_prompt,
                    chat_history=chat_history,
                    user_message=user_message,
                    file_content=file_content or "",
                    ssh_credentials=self.ssh_credentials
                )
            except Exception as _mem_err2:
                logger.warning(f"memory_v9 build_messages failed: {_mem_err2}")
                messages = [{"role": "system", "content": _effective_system_prompt}]
                _ctx_limit = 50 if self.orion_mode in PRO_MODES else 10
                for msg in chat_history[-_ctx_limit:]:
                    messages.append({"role": msg.get("role", "user"), "content": msg.get("content", "")})
                messages.append({"role": "user", "content": user_message})
        else:
            messages = [{"role": "system", "content": _effective_system_prompt}]
            _ctx_limit = 50 if self.orion_mode in PRO_MODES else 10
            for msg in chat_history[-_ctx_limit:]:
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

        # ── ПАТЧ 1: Парсинг FTP/админки из сообщения ──
        _msg_lower = user_message.lower()
        if "ftp" in _msg_lower:
            import re as _re
            _ftp_match = _re.search(r'ftp[:\s]+(\S+)\s+логин[:\s]+(\S+)\s+пароль[:\s]+(\S+)', user_message, _re.IGNORECASE)
            if _ftp_match:
                self._extra_credentials["FTP"] = f"{_ftp_match.group(1)} логин: {_ftp_match.group(2)} пароль: {_ftp_match.group(3)}"
        if "админк" in _msg_lower or "bitrix" in _msg_lower:
            import re as _re
            _admin_match = _re.search(r'(https?://\S+/bitrix/?\S*)\s+логин[:\s]+(\S+)\s+пароль[:\s]+(\S+)', user_message, _re.IGNORECASE)
            if _admin_match:
                self._extra_credentials["Админка"] = f"{_admin_match.group(1)} логин: {_admin_match.group(2)} пароль: {_admin_match.group(3)}"

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

        # ── ПАТЧ 9: Solution Cache — recall похожих решений ──
        try:
            if not self._solution_cache:
                self._solution_cache = SolutionCache(call_ai_simple_fn=self._call_ai_simple)
            _cached_solutions = self._solution_cache.recall(user_message, threshold=0.55, top_k=2)
            logger.info(f"[PATCH9] recall result: {len(_cached_solutions) if _cached_solutions else 0} solutions found")
            if _cached_solutions:
                _cache_hint = self._solution_cache.format_for_prompt(_cached_solutions)
                if messages and messages[0].get("role") == "system":
                    messages[0]["content"] += _cache_hint
                logger.info(f"[PATCH9] Injected {len(_cached_solutions)} cached solutions")
                yield self._sse({"type": "info", "message": f"Найдено {len(_cached_solutions)} похожих решений в кеше"})
                # Increment use count
                for _sol in _cached_solutions:
                    self._solution_cache.increment_use(_sol["id"])
        except Exception as _p9_err:
            logger.warning(f"[PATCH9] recall error: {_p9_err}", exc_info=True)


        # ══ FORCE TOOL — принудительный вызов инструмента ══
        logger.info("[DEBUG] Starting force_tool check")
        _force_tool_result = self._check_force_tool(user_message, file_content or "")
        if _force_tool_result:
            for _ft_event in _force_tool_result:
                yield _ft_event
            return

        # ── ПАТЧ W1-2: Составить план перед выполнением ──
        _task_plan_steps = []
        try:
            _plan_prompt = [
                {"role": "system", "content": (
                    "Составь план выполнения задачи из 3-8 шагов. "
                    "Каждый шаг — конкретное действие с инструментом (ssh_execute, browser_navigate, file_write и т.д.). "
                    "Ответь СТРОГО JSON массивом строк: [\"\u0448\u0430\u0433 1\", \"\u0448\u0430\u0433 2\", ...]. "
                    "Без markdown, без пояснений, только JSON массив."
                )},
                {"role": "user", "content": f"Задача: {user_message[:1000]}"}
            ]
            logger.info("[PATCH-W1-2] Calling AI for plan..."); _plan_raw = self._call_ai_simple(_plan_prompt)
            if _plan_raw:
                _plan_raw = _plan_raw.strip()
                if _plan_raw.startswith("```"):
                    _plan_raw = _plan_raw.split("\n", 1)[1].rsplit("```", 1)[0].strip()
                _task_plan_steps = json.loads(_plan_raw)
                if isinstance(_task_plan_steps, list) and _task_plan_steps:
                    yield self._sse({
                        "type": "task_steps",
                        "steps": [{"name": s, "status": "pending"} for s in _task_plan_steps[:10]]
                    })
                    _plan_text = "ПЛАН ВЫПОЛНЕНИЯ (следуй ему пошагово):\n" + "\n".join(
                        f"{i+1}. {s}" for i, s in enumerate(_task_plan_steps[:10])
                    )
                    if messages and messages[0].get("role") == "system":
                        messages[0]["content"] += f"\n\n{_plan_text}"
                    logger.info(f"[PATCH-W1-2] Plan generated: {len(_task_plan_steps)} steps")
        except Exception as _plan_err:
            logger.debug(f"[PATCH-W1-2] Plan generation failed: {_plan_err}")

        # Agent loop with LangGraph state tracking
        logger.info("[DEBUG] Starting iteration loop"); iteration = 0
        full_response_text = ""
        heal_attempts = 0
        # ── ANTI-LOOP: track repeated tool calls ──
        _tool_call_history = {}  # {hash: count}
        _consecutive_loops = 0
        _loop_model_escalation = 0  # 0=original, 1=sonnet, 2=opus
        _original_model = self.model

        while iteration < self.MAX_ITERATIONS and not self._stop_requested:
            yield self._sse({"type": "heartbeat", "message": "agent_thinking"})
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
            logger.info(f"[DEBUG-IT] iteration={iteration}, about to call before_iteration")
            if self.memory:
                try:
                    messages = self.memory.before_iteration(messages, iteration, self.MAX_ITERATIONS)
                except Exception as _bi_err:
                    logger.debug(f"memory before_iteration error: {_bi_err}")

            # ── MANUS FEATURE 1: TODO.MD — план в файле ──
            _todo_path = f"/tmp/orion_todo_{getattr(self, '_chat_id', 'default')}.md"
            if os.path.exists(_todo_path):
                try:
                    with open(_todo_path, 'r') as _tf:
                        _todo = _tf.read()
                    if _todo.strip():
                        # Удаляем предыдущий TODO из messages (чтобы не дублировать)
                        messages = [m for m in messages if not (m.get('role') == 'system' and '[ТЕКУЩИЙ ПЛАН' in str(m.get('content', '')))]
                        messages.append({"role": "system",
                            "content": f"[ТЕКУЩИЙ ПЛАН — обнови через file_write в {_todo_path}]\n{_todo}"})
                        logger.info(f"[TODO.MD] Injected plan from {_todo_path} ({len(_todo)} chars)")
                except Exception as _todo_err:
                    logger.debug(f"[TODO.MD] Error reading plan: {_todo_err}")
            # ── ПАТЧ 1: Инжекция доступов в system prompt КАЖДОЙ итерации ──
            if self.ssh_credentials and self.ssh_credentials.get("host"):
                _creds_block = (
                    f"\n\nДОСТУПЫ К СЕРВЕРУ (используй их, НЕ спрашивай повторно):\n"
                    f"SSH: {self.ssh_credentials.get('host')} "
                    f"логин: {self.ssh_credentials.get('username', 'root')} "
                    f"пароль: {self.ssh_credentials.get('password', '')} "
                    f"порт: {self.ssh_credentials.get('port', 22)}"
                )
                if hasattr(self, '_extra_credentials') and self._extra_credentials:
                    for _ck, _cv in self._extra_credentials.items():
                        _creds_block += f"\n{_ck}: {_cv}"
                if messages and messages[0].get("role") == "system":
                    _sys = messages[0]["content"]
                    if "ДОСТУПЫ К СЕРВЕРУ" in _sys:
                        _sys = _sys[:_sys.index("\n\nДОСТУПЫ К СЕРВЕРУ")]
                    messages[0]["content"] = _sys + _creds_block

            logger.info(f"[DEBUG-IT] iteration={iteration}, credentials injected, about to call AI stream")
            try:
                logger.info(f"[DEBUG] Calling AI stream, iteration {iteration}, messages: {len(messages)}")
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
                        _error_text = f"AI Error: {event['error']}"
                        yield self._sse({"type": "error", "text": _error_text})
                        # Don't return — try to continue with next iteration
                        logger.warning(f"[run_stream] AI error at iteration {iteration}, will retry: {_error_text}")
                        heal_attempts += 1
                        if heal_attempts >= 3:
                            yield self._sse({"type": "content", "text": f"\n\n❌ Агент не смог продолжить после {heal_attempts} ошибок AI."})
                            full_response_text += f"\n\n❌ Агент не смог продолжить после {heal_attempts} ошибок AI."
                            break  # break instead of return — so done event is sent
                        continue  # retry next iteration
            except GeneratorExit:
                logger.warning(f"[run_stream] GeneratorExit at iteration {iteration}, cleaning up")
                return
            except Exception as e:
                error_msg = f"Ошибка при вызове AI: {str(e)}"
                yield self._sse({"type": "error", "text": error_msg})
                yield self._sse({"type": "content", "text": f"\n\n❌ {error_msg}"})
                full_response_text += f"\n\n❌ {error_msg}"
                heal_attempts += 1
                if heal_attempts >= 3:
                    break  # break instead of return — so done event is sent
                continue  # retry next iteration

            logger.info(f"[DEBUG-IT] iteration={iteration} completed, tool_calls={'yes' if tool_calls_received else 'no'}")
            if not tool_calls_received:
                break

            # Add assistant message with tool calls to history
            assistant_msg = {"role": "assistant", "content": ai_text or ""}
            assistant_msg["tool_calls"] = tool_calls_received
            messages.append(assistant_msg)

            # ── ПАТЧ 10: Валидация JSON аргументов tool_call перед выполнением ──
            # Streaming от OpenRouter может обрезать большие аргументы → невалидный JSON
            # Если аргументы пустые или невалидный JSON — не выполнять, вернуть ошибку модели
            _invalid_tool_calls = []
            for _tc_check in tool_calls_received:
                _tc_args_str = _tc_check["function"].get("arguments", "")
                _tc_name = _tc_check["function"].get("name", "")
                _is_valid = True
                _parse_error = None
                # Инструменты, которые требуют непустой контент
                _content_tools = ("file_write", "ssh_execute", "browser_navigate",
                                  "browser_input", "browser_fill_form", "generate_file")
                if not _tc_args_str or _tc_args_str.strip() in ("", "{}", "null"):
                    if _tc_name in _content_tools:
                        _is_valid = False
                        _parse_error = (f"Empty arguments for tool '{_tc_name}' — "
                                        f"streaming likely truncated the content")
                else:
                    try:
                        _parsed_check = json.loads(_tc_args_str)
                        # Для file_write проверяем что content и path не пустые
                        if _tc_name == "file_write":
                            if not _parsed_check.get("content") and not _parsed_check.get("path"):
                                _is_valid = False
                                _parse_error = (f"file_write called with empty content/path — "
                                                f"streaming truncated arguments")
                            elif not _parsed_check.get("content"):
                                _is_valid = False
                                _parse_error = (f"file_write called with empty content — "
                                                f"streaming truncated the file body")
                    except json.JSONDecodeError as _je:
                        _is_valid = False
                        _parse_error = (f"Invalid JSON in tool '{_tc_name}' arguments — "
                                        f"streaming truncated the response. "
                                        f"Error: {_je}. Raw (first 200 chars): {_tc_args_str[:200]!r}")
                if not _is_valid:
                    _invalid_tool_calls.append((_tc_check, _parse_error))
                    logger.warning(f"[PATCH10] Invalid/truncated tool call: {_parse_error}")

            if _invalid_tool_calls:
                # assistant_msg уже добавлен выше (строка 4390), не дублируем
                # Для каждого невалидного tool_call добавляем ошибку как tool result
                for _inv_tc, _inv_err in _invalid_tool_calls:
                    _inv_id = _inv_tc.get("id", f"call_{iteration}")
                    _inv_name = _inv_tc["function"].get("name", "unknown")
                    _retry_hint = (
                        "IMPORTANT: Your previous tool call arguments were truncated during streaming "
                        "because the content was too large. Please retry with SMALLER content:\n"
                        "- For file_write: split into multiple calls, max 6000 chars per call, "
                        "use append=true for subsequent parts\n"
                        "- For ssh_execute: use heredoc with shorter content\n"
                        "- For generate_file: reduce content size or split into sections\n"
                        f"Original error: {_inv_err}"
                    )
                    messages.append({
                        "role": "tool",
                        "tool_call_id": _inv_id,
                        "name": _inv_name,
                        "content": _retry_hint
                    })
                    yield self._sse({
                        "type": "tool_result",
                        "tool": _inv_name,
                        "success": False,
                        "error": "[PATCH10] Arguments truncated by streaming — model asked to retry with smaller content",
                        "iteration": iteration
                    })
                    logger.warning(f"[PATCH10] Retry requested for tool '{_inv_name}'")
                # Продолжаем цикл — модель получит ошибку и повторит с меньшим контентом
                continue

            # Execute each tool call
            for tc in tool_calls_received:
                tool_name = tc["function"]["name"]
                tool_args_str = tc["function"]["arguments"]
                tool_id = tc.get("id", f"call_{iteration}")

                try:
                    tool_args = json.loads(tool_args_str)
                except Exception:
                    tool_args = {}

                # ── ПАТЧ 3: Автоэкранирование спецсимволов в URL/FTP ──
                if tool_name in ("browser_navigate", "browser_check_site", "browser_get_text"):
                    _url = tool_args.get("url", "")
                    if "@" in _url and "://" in _url:
                        try:
                            from urllib.parse import urlparse, quote, urlunparse
                            _parsed = urlparse(_url)
                            if _parsed.password and any(c in _parsed.password for c in '#@!$& '):
                                _safe_pass = quote(_parsed.password, safe='')
                                _new_netloc = f"{_parsed.username}:{_safe_pass}@{_parsed.hostname}"
                                if _parsed.port:
                                    _new_netloc += f":{_parsed.port}"
                                tool_args["url"] = urlunparse(_parsed._replace(netloc=_new_netloc))
                                tool_args_str = json.dumps(tool_args, ensure_ascii=False)
                                logger.info(f"[PATCH3] Escaped special chars in URL password")
                        except Exception as _esc_err:
                            logger.debug(f"URL escape error: {_esc_err}")

                # THINKING STEP: показать что агент собирается делать
                _thinking_text = self._get_thinking_text(tool_name, tool_args)
                if _thinking_text:
                    yield self._sse({"type": "thinking_step", "text": _thinking_text})
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
                    yield self._sse({"type": "usage", "prompt_tokens": self.total_tokens_in, "completion_tokens": self.total_tokens_out})

                    # ── ПАТЧ 6: Автопроверка после task_complete ──
                    try:
                        _files_in_log = []
                        for _act in self.actions_log:
                            _a_args = _act.get("args", {})
                            if _act.get("tool") in ("file_write", "ssh_execute"):
                                _path = _a_args.get("path", "")
                                if _path:
                                    _files_in_log.append(_path)
                        if _files_in_log and self.ssh_credentials and self.ssh_credentials.get("host"):
                            _last_file = _files_in_log[-1]
                            _verify_result = self._execute_tool("ssh_execute",
                                json.dumps({"command": f"ls -la {_last_file} 2>/dev/null && echo FILE_EXISTS || echo FILE_MISSING"}))
                            _verify_out = _verify_result.get("stdout", "")
                            if "FILE_MISSING" in _verify_out:
                                yield self._sse({"type": "verification", "status": "warning",
                                    "message": f"Файл {_last_file} не найден на сервере!"})
                            else:
                                yield self._sse({"type": "verification", "status": "ok",
                                    "message": f"Файл {_last_file} существует"})
                    except Exception as _v6_err:
                        logger.debug(f"PATCH6 auto-verify error: {_v6_err}")

                    # ── ПАТЧ 9: Solution Cache — сохранить решение ──
                    try:
                        if not self._solution_cache:
                            self._solution_cache = SolutionCache(call_ai_simple_fn=self._call_ai_simple)
                        _extracted = SolutionExtractor.extract(
                            self.actions_log, user_message, summary
                        )
                        self._solution_cache.save(user_message, _extracted,
                            agent_key=getattr(self, '_agent_key', ''))
                        logger.info(f"[PATCH9] Solution saved: {len(_extracted.get('commands', []))} cmds, "
                                    f"{len(_extracted.get('files_created', []))} files")
                    except Exception as _p9_save_err:
                        logger.debug(f"PATCH9 save error: {_p9_save_err}")

                    # ── ПАТЧ 7: Mixture-of-Agents верификация ──
                    if getattr(self, '_verify_enabled', False):
                        try:
                            yield self._sse({"type": "verification", "status": "checking", "model": "Claude Sonnet 4.6"})
                            _v7 = self._verify_with_second_llm(
                                user_message, full_response_text, self.actions_log
                            )
                            if _v7.get("verified"):
                                yield self._sse({"type": "verification", "status": "verified",
                                    "issues": 0, "summary": _v7.get("summary", "OK")})
                            else:
                                _issues = _v7.get("issues", [])
                                yield self._sse({"type": "verification", "status": "issues_found",
                                    "issues": len(_issues), "details": "; ".join(_issues[:3])})
                        except Exception as _v7_err2:
                            logger.debug(f"PATCH7 verify SSE error: {_v7_err2}")

                    messages.append({
                        "role": "tool",
                        "tool_call_id": tool_id,
                        "content": json.dumps({k: ("[screenshot sent to user]" if k == "screenshot" else v) for k, v in result.items()}, ensure_ascii=False)
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

                # ═══ ANTI-LOOP DETECTION ═══
                _last_tools = [(a["tool"], str(a.get("args", "")))
                               for a in self.actions_log[-3:]]
                if len(_last_tools) == 3 and len(set(_last_tools)) == 1:
                    # Three identical tool calls in a row — loop detected
                    _loop_mode = getattr(self, 'orion_mode', 'turbo_standard')
                    if _loop_mode in PRO_MODES:
                        # Pro/Architect: warn the model to try different approach
                        messages.append({"role": "system", "content":
                            "СТОП. Ты зацикливаешься — вызвал один и тот же инструмент "
                            "3 раза с тем же результатом. Попробуй ДРУГОЙ подход."})
                        logging.warning(f"[ANTI-LOOP] Pro mode loop detected: {_last_tools[0][0]}")
                    else:
                        # Turbo: escalate to Sonnet
                        self.model = "anthropic/claude-sonnet-4"
                        messages.append({"role": "system", "content":
                            "Предыдущий подход не сработал. Ты переключен на более "
                            "умную модель. Проанализируй что пошло не так и "
                            "попробуй другой способ."})
                        logging.warning(f"[ANTI-LOOP] Turbo mode loop → escalated to Sonnet")

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

                # ── FIX-4: Auto step_update — match tool calls to plan steps ──
                if _task_plan_steps and result.get("success", False):
                    _tool_desc = f"{tool_name} {json.dumps(self._sanitize_args(tool_args), ensure_ascii=False)[:100]}"
                    for _si, _step_name in enumerate(_task_plan_steps):
                        _step_lower = _step_name.lower()
                        _tool_lower = tool_name.lower()
                        # Match tool to step by keywords
                        _matched = False
                        if _tool_lower == "ssh_execute" and any(kw in _step_lower for kw in ["ssh", "команд", "установ", "настро", "серв", "deploy", "деплой", "nginx", "ssl", "certbot", "dns"]):
                            _matched = True
                        elif _tool_lower == "file_write" and any(kw in _step_lower for kw in ["файл", "html", "css", "код", "напис", "созда", "file"]):
                            _matched = True
                        elif _tool_lower in ("browser_navigate", "browser_check_site") and any(kw in _step_lower for kw in ["провер", "сайт", "браузер", "скриншот", "откр", "check"]):
                            _matched = True
                        elif _tool_lower == "generate_image" and any(kw in _step_lower for kw in ["фото", "изображ", "картин", "генер", "image"]):
                            _matched = True
                        
                        if _matched:
                            # Check if this step was already marked done
                            if not hasattr(self, '_completed_steps'):
                                self._completed_steps = set()
                            if _si not in self._completed_steps:
                                self._completed_steps.add(_si)
                                yield self._sse({
                                    "type": "step_update",
                                    "step_index": _si,
                                    "status": "done",
                                    "name": _step_name
                                })
                            break

                # ── BUG-1 FIX: after_tool (ToolLearning, ErrorPatterns, SessionMemory) ──
                if self.memory:
                    try:
                        result_str_mem = self.memory.after_tool(
                            tool_name, tool_args, result,
                            self._preview_result(tool_name, result)
                        )
                    except Exception as _at_err:
                        logger.debug(f"memory.after_tool error: {_at_err}")

                # ── ПАТЧ 2: Автоматическая подсказка для самопроверки ──
                _selfcheck_hint = ""
                if result.get("success", False):
                    if tool_name == "file_write":
                        _written_path = tool_args.get("path", "")
                        if _written_path:
                            _selfcheck_hint = f" [ПРОВЕРЬ: выполни file_read или ssh_execute 'ls -la {_written_path}' чтобы убедиться что файл создан]"
                    elif tool_name == "ssh_execute" and ("cp " in tool_args.get("command", "") or "mv " in tool_args.get("command", "")):
                        _selfcheck_hint = " [ПРОВЕРЬ: выполни ls -la чтобы убедиться что файл на месте]"
                    elif tool_name in ("browser_navigate", "browser_check_site"):
                        _status = result.get("status_code", 0)
                        if _status in (401, 403):
                            _selfcheck_hint = " [HTTP AUTH: страница требует авторизацию. Попробуй SSH/FTP доступ напрямую, не через браузер]"
                        elif _status == 404:
                            _selfcheck_hint = " [404: страница не найдена. Проверь URL и путь к файлу на сервере]"
                if _selfcheck_hint:
                    if isinstance(result, dict):
                        result["_selfcheck"] = _selfcheck_hint

                # ── ЗАДАЧА-1: browser_ask_auth — отправить SSE auth_required и подождать ответа у пользователя ──
                if result.get("_auth_required"):
                    # Отправляем SSE событие auth_required — frontend покажет форму логина
                    yield self._sse({
                        "type": "auth_required",
                        "url": result.get("url", ""),
                        "screenshot": result.get("screenshot"),
                        "fields": result.get("fields", []),
                        "hint": result.get("hint", ""),
                        "submit_selector": result.get("submit_selector", 'button[type="submit"]'),
                        "tool_call_id": tool_id
                    })
                    # Добавляем в messages инфо что ждём авторизацию
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tool_id,
                        "content": json.dumps({
                            "success": True,
                            "status": "auth_required",
                            "message": f"Пользователь видит форму логина. Ожидаем ввод данных ({result.get('hint', '')}). После ввода пользователя используй browser_fill и browser_submit.",
                            "fields": result.get("fields", []),
                            "url": result.get("url", "")
                        }, ensure_ascii=False)
                    })
                    continue

                result_preview = self._preview_result(tool_name, result)
                # Include screenshot for browser tools (ЗАДАЧА-1: расширен список)
                _browser_tools = ("browser_navigate", "browser_check_site", "browser_get_text", "browser_screenshot",
                                  "browser_get_links", "browser_screenshot_check",
                                  "browser_click", "browser_fill", "browser_submit", "browser_select")
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
                    _tool_result_event["url"] = result.get("url", "")
                yield self._sse(_tool_result_event)

                # ── ПАТЧ W1-5: Автоанализ скриншота после browser_navigate ──
                if tool_name == "browser_navigate" and _screenshot and result.get("success"):
                    try:
                        _analysis = self._analyze_screenshot_auto(_screenshot, tool_args.get("url", ""))
                        if _analysis:
                            messages.append({
                                "role": "tool",
                                "tool_call_id": tool_id,
                                "content": json.dumps({
                                    "success": True,
                                    "screenshot_analysis": _analysis,
                                    "note": "Автоанализ скриншота страницы"
                                }, ensure_ascii=False)[:self.MAX_TOOL_OUTPUT]
                            })
                            yield self._sse({
                                "type": "tool_result",
                                "tool": "analyze_screenshot",
                                "success": True,
                                "preview": f"👁️ Анализ страницы: {_analysis[:200]}",
                                "elapsed": 0
                            })
                            result["_screenshot_analyzed"] = True
                    except Exception as _sa_err:
                        logger.debug(f"[PATCH-W1-5] Screenshot analysis error: {_sa_err}")

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
                # ПАТЧ W1-5: пропускаем если скриншот уже проанализирован и добавлен
                if not result.get("_screenshot_analyzed"):
                    # FIX: strip screenshot base64 from AI messages to prevent raw text output
                    _result_for_ai = result.copy()
                    if "screenshot" in _result_for_ai:
                        _result_for_ai["screenshot"] = "[screenshot sent to user as image]"
                    result_str = json.dumps(_result_for_ai, ensure_ascii=False)
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
            yield self._sse({"type": "usage", "prompt_tokens": self.total_tokens_in, "completion_tokens": self.total_tokens_out})
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


        # ── AutoSummary: резюме разговора для Project Memory ──
        if self.memory and hasattr(self, '_chat_id') and full_response_text:
            try:
                _summary_messages = [
                    {"role": "system", "content": """Напиши подробное резюме этого разговора в 5-10 предложений.
Включи ОБЯЗАТЕЛЬНО:
- Что просил пользователь и что было сделано
- ВСЕ технические решения (фреймворки, библиотеки, языки)
- Названия ВСЕХ созданных файлов и пути к ним
- URL, домены, IP-адреса серверов
- Цвета, шрифты, дизайн-решения
- Структуру проекта и архитектуру
- Конфигурации, порты, настройки сервера
Отвечай ТОЛЬКО резюме, без пояснений."""},
                    {"role": "user", "content": f"Запрос пользователя: {user_message[:1000]}\n\nОтвет агента: {full_response_text[:4000]}"}
                ]
                _summary_text = self._call_ai_simple(_summary_messages)
                if _summary_text and len(_summary_text) > 10:
                    self.memory.store_fact(
                        key=f"chat_summary:{self._chat_id}",
                        value=_summary_text,
                        category="project_summary",
                        metadata={
                            "chat_id": self._chat_id,
                            "user_message": user_message[:200],
                            "timestamp": __import__('time').time()
                        }
                    )
                    _decisions = []
                    for keyword in ["решили", "выбрали", "используем", "будем", "настроили", "создали", "задеплоили"]:
                        if keyword in full_response_text.lower():
                            for sentence in full_response_text.split('.'):
                                if keyword in sentence.lower() and len(sentence) > 15:
                                    _decisions.append(sentence.strip()[:200])
                                    break
                    if _decisions:
                        self.memory.store_fact(
                            key=f"decisions:{self._chat_id}",
                            value="; ".join(_decisions),
                            category="project_decisions"
                        )
                    logging.info(f"[AutoSummary] Saved summary for chat {self._chat_id}: {_summary_text[:100]}...")
            except Exception as _sum_err:
                logging.warning(f"[AutoSummary] Failed: {_sum_err}")

        # Принудительный финальный ответ если агент достиг MAX_ITERATIONS без task_complete
        if not full_response_text.strip():
            yield self._sse({"type": "content", "text": "⚠️ Агент достиг лимита итераций. Запрашиваю финальный ответ..."})
            # PATCH 26: Save failure to Solution Cache
            try:
                if not self._solution_cache:
                    self._solution_cache = SolutionCache(call_ai_simple_fn=self._call_ai_simple)
                _fail_extracted = SolutionExtractor.extract(self.actions_log, user_message, "FAILED: max iterations reached without task_complete")
                _fail_extracted["confidence"] = 0.2  # Low confidence — this is a failure
                _fail_extracted["status"] = "failed"
                _fail_extracted["failure_reason"] = "max_iterations_reached"
                self._solution_cache.save(user_message, _fail_extracted, agent_key=getattr(self, '_agent_key', ''))
                logger.info(f"[PATCH26] Failure saved to solution cache: {len(_fail_extracted.get('errors_and_fixes', []))} errors")
            except Exception as _p26_err:
                logger.debug(f"PATCH26 save failure error: {_p26_err}")
            try:
                # Собрать контекст выполненных действий для финального ответа
                tool_results_summary = []
                for m in messages:
                    if m.get("role") == "tool":
                        try:
                            r = json.loads(m["content"])
                            if isinstance(r, dict) and r.get("success"):
                                tool_results_summary.append(m["content"][:300])
                        except Exception as _parse_err:
                            logging.warning(f"Tool result parse error: {_parse_err}")
                context_summary = "\n".join(tool_results_summary[-5:]) if tool_results_summary else "Результаты действий недоступны"
                final_messages = [
                    {"role": "system", "content": "Ты автономный AI-агент. На основе выполненных действий дай полный итоговый ответ пользователю. Отвечай на языке пользователя."},
                    {"role": "user", "content": f"Задача: {self.user_message if hasattr(self, 'user_message') else 'задача выполнена'}\n\nРезультаты действий:\n{context_summary}\n\nНапиши итоговый ответ с результатами выполненных действий."}
                ]
                for event in self._call_ai_stream(final_messages, tools=None):
                    if event["type"] == "text_delta":
                        yield self._sse({"type": "content", "text": event["text"]})
                    # Обработка browser_ask_user / smart_login takeover
                    if result.get("_takeover_required"):
                        yield self._sse({"type": "browser_takeover",
                            "subtype": result.get("type", "browser_takeover_request"),
                            "reason": result.get("reason", ""),
                            "message": result.get("message", "Требуется ваше участие"),
                            "instruction": result.get("instruction", ""),
                            "url": result.get("url", ""),
                            "screenshot": result.get("screenshot", ""),
                            "screenshot_url": result.get("screenshot_url", ""),
                            "actions": result.get("actions", [])
                        })

                    elif event["type"] == "text_complete":
                        break
            except Exception as e:
                yield self._sse({"type": "content", "text": f"\n\n⚠️ Агент достиг лимита итераций ({self.MAX_ITERATIONS}). Пожалуйста, уточните задачу или повторите запрос."})
        # ── USAGE: отправляем токены обратно в app.py ──
        yield self._sse({"type": "usage", "prompt_tokens": self.total_tokens_in, "completion_tokens": self.total_tokens_out})


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

    def run_stream(self, user_message, chat_history=None, file_content=None, ssh_credentials=None):
        """Override run_stream to handle orchestrator sequential pipeline."""
        import logging
        _mlog = logging.getLogger('agent_loop')
        _mlog.info(f'[MULTI] run_stream CALLED, class={self.__class__.__name__}')
        if ssh_credentials:
            self.ssh_credentials = ssh_credentials
        
        plan = getattr(self, '_orchestrator_plan', None)
        _mlog.info(f'[MULTI] plan exists={plan is not None}, mode={plan.get("mode") if plan else None}, phases={len(plan.get("phases",[])) if plan else 0}')
        if plan and plan.get('mode') == 'multi_sequential' and plan.get('phases'):
            _mlog.info(f'[MULTI] STARTING sequential pipeline with {len(plan["phases"])} phases')
            yield from self._run_sequential_pipeline(user_message, chat_history, file_content, plan)
        else:
            # Fallback to parent AgentLoop.run_stream
            yield from super().run_stream(user_message, chat_history, file_content, ssh_credentials)

    def _run_sequential_pipeline(self, user_message, chat_history, file_content, plan):
        """Execute orchestrator phases sequentially, each as a separate agent loop."""
        import json as _json
        import logging as _plog
        _plog.info(f"[Pipeline] _run_sequential_pipeline ENTERED with {len(plan.get('phases', []))} phases")
        phases = plan.get('phases', [])
        total_phases = len(phases)
        
        # Send plan to frontend
        yield self._sse({
            "type": "task_steps",
            "steps": [{"name": p["name"], "agent": p.get("agents", ["developer"])[0], "status": "pending"} for p in phases],
            "total": total_phases
        })
        
        context = user_message
        if file_content:
            context = f"{file_content}\n\n---\n\nЗадача:\n{user_message}"
        if self.ssh_credentials.get('host'):
            context += f"\n\n[Сервер: {self.ssh_credentials['host']}, user: {self.ssh_credentials.get('username', 'root')}]"
        
        phase_results = {}
        
        for idx, phase in enumerate(phases):
            if self._stop_requested:
                yield self._sse({"type": "stopped", "text": "Остановлено пользователем"})
                return
            
            phase_name = phase.get('name', f'Phase {idx+1}')
            phase_agents = phase.get('agents', ['developer'])
            phase_desc = phase.get('description', '')
            agent_key = phase_agents[0] if phase_agents else 'developer'
            _plog.info(f"[Pipeline] Starting phase {idx+1}/{total_phases}: {phase_name} (agent: {agent_key})")
            
            # Notify frontend
            yield self._sse({
                "type": "step_update",
                "step_index": idx,
                "status": "running",
                "name": phase_name
            })
            yield self._sse({
                "type": "agent_start",
                "agent": phase_name,
                "emoji": self._agent_emoji(agent_key),
                "role": agent_key
            })
            
            # Switch model for this phase agent
            # For Pro/Architect: keep ONE model for entire pipeline (no switching)
            _current_orion_mode = getattr(self, 'orion_mode', getattr(self, '_orion_mode', 'turbo_standard'))
            if _current_orion_mode in PRO_MODES:
                _plog.info(f"[Pipeline] Pro/Architect mode: keeping model {self.model} (no switch)")
            else:
                try:
                    from orchestrator_v2 import get_model_for_agent
                    _phase_model = get_model_for_agent(agent_key, _current_orion_mode)
                    _old_model = self.model
                    self.model = _phase_model
                    _plog.info(f"[Pipeline] Phase model: {agent_key} → {_phase_model}")
                except Exception as _me:
                    _plog.warning(f"[Pipeline] Could not switch model for {agent_key}: {_me}")
            
            # Build phase prompt
            phase_prompt = f"""ТЕКУЩАЯ ФАЗА ({idx+1}/{total_phases}): {phase_name}

ОПИСАНИЕ ФАЗЫ: {phase_desc}

ОРИГИНАЛЬНАЯ ЗАДАЧА: {context}"""
            
            if phase_results:
                prev = "\n\n".join([f"=== {k} ===\n{v[:2000]}" for k, v in phase_results.items()])
                phase_prompt += f"\n\nРЕЗУЛЬТАТЫ ПРЕДЫДУЩИХ ФАЗ:\n{prev}"
            
            phase_prompt += f"""\n\nВАЖНО:
- Ты выполняешь ТОЛЬКО эту фазу: {phase_name}
- Используй инструменты (ssh_execute, file_write, browser_navigate и т.д.) для РЕАЛЬНОГО выполнения
- Не просто описывай что нужно сделать — ДЕЛАЙ
- Когда фаза выполнена — вызови task_complete"""
            
            # Get agent-specific prompt
            agent_prompt_extra = ""
            try:
                from orchestrator_v2 import AGENT_PROMPTS
                agent_prompt_extra = AGENT_PROMPTS.get(agent_key, "")
            except:
                pass
            
            # Build messages for this phase
            system_prompt = get_system_prompt(getattr(self, "orion_mode", "turbo_standard"))
            if agent_prompt_extra:
                system_prompt += "\n\n" + agent_prompt_extra
            if hasattr(self, '_orchestrator_prompt') and self._orchestrator_prompt:
                system_prompt += "\n\n" + self._orchestrator_prompt
            
            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": phase_prompt}
            ]
            
            # Run agent loop for this phase
            phase_text = ""
            iteration = 0
            max_iterations = 20
            
            while iteration < max_iterations and not self._stop_requested:
                iteration += 1
                yield self._sse({"type": "heartbeat", "message": "agent_thinking"})
                tool_calls_received = None
                ai_text = ""
                import logging as _pipe_log
                _pipe_log.info(f"[Pipeline] Phase {phase_name} iteration {iteration}/{max_iterations}")
                
                try:
                    for event in self._call_ai_stream(messages, tools=TOOLS_SCHEMA):
                        if event["type"] == "text_delta":
                            ai_text += event["text"]
                            phase_text += event["text"]
                            yield self._sse({"type": "content", "text": event["text"], "agent": phase_name})
                        elif event["type"] == "tool_calls":
                            tool_calls_received = event["tool_calls"]
                except Exception as e:
                    logging.error(f"[Pipeline] Phase {phase_name} AI call error: {e}")
                    yield self._sse({"type": "error", "text": f"Ошибка в фазе {phase_name}: {str(e)}"})
                    break
                
                if ai_text:
                    messages.append({"role": "assistant", "content": ai_text})
                
                if not tool_calls_received:
                    break
                
                # Process tool calls — BUG-9 FIX: tool_calls from _call_ai_stream already have OpenAI format
                # Format: {"id": ..., "type": "function", "function": {"name": ..., "arguments": "..."}}
                messages.append({"role": "assistant", "content": ai_text, "tool_calls": tool_calls_received})
                
                for tc in tool_calls_received:
                    tool_name = tc["function"]["name"]
                    tool_args_str = tc["function"].get("arguments", "{}")
                    try:
                        tool_args = _json.loads(tool_args_str) if isinstance(tool_args_str, str) else tool_args_str
                    except _json.JSONDecodeError:
                        tool_args = {}
                    tool_id = tc["id"]
                    
                    # Check for task_complete
                    if tool_name == "task_complete":
                        phase_text += "\n[ФАЗА ЗАВЕРШЕНА]"
                        yield self._sse({"type": "tool_start", "tool": "task_complete", "args": tool_args})
                        messages.append({"role": "tool", "tool_call_id": tool_id, "content": "Phase completed"})
                        # PATCH 25: Quality Gate after pipeline phase
                        if hasattr(self, '_check_quality_gate'):
                            _qg = self._check_quality_gate(phase_name, self.actions_log)
                            if _qg["passed"]:
                                logging.info(f"[QualityGate] Phase '{phase_name}' PASSED")
                                yield self._sse({"type": "quality_gate", "phase": phase_name, "passed": True})
                            else:
                                logging.warning(f"[QualityGate] Phase '{phase_name}' FAILED: {_qg['reason']}")
                                yield self._sse({"type": "quality_gate", "phase": phase_name, "passed": False, "reason": _qg["reason"]})
                        tool_calls_received = None
                        break
                    
                    _display_args = {k: str(v)[:100] for k, v in tool_args.items()} if isinstance(tool_args, dict) else {}
                    yield self._sse({"type": "tool_start", "tool": tool_name, "args": _display_args})
                    
                    try:
                        result = self._execute_tool(tool_name, tool_args)
                    except Exception as e:
                        result = {"error": str(e)}
                    
                    result_preview = self._preview_result(tool_name, result)
                    yield self._sse({"type": "tool_result", "tool": tool_name, "result": result_preview})
                    
                    _result_clean = {k: ("[screenshot sent to user]" if k == "screenshot" else v) for k, v in result.items()}
                    result_str = _json.dumps(_result_clean, ensure_ascii=False)
                    if len(result_str) > self.MAX_TOOL_OUTPUT:
                        result_str = result_str[:self.MAX_TOOL_OUTPUT] + "..."
                    
                    messages.append({"role": "tool", "tool_call_id": tool_id, "content": result_str})
                
                if tool_calls_received is None:
                    break  # task_complete was called
            
            phase_results[phase_name] = phase_text[:3000]
            
            yield self._sse({
                "type": "step_update",
                "step_index": idx,
                "status": "done",
                "name": phase_name
            })
            yield self._sse({
                "type": "agent_complete",
                "agent": phase_name,
                "role": agent_key
            })


            # ── PREMIUM DESIGN QUALITY CHECK (uses Opus + 3 cycles + mobile) ──────────
            if _is_deploy_phase and _qc_host and getattr(self, 'premium_design', False):
                import logging as _pqc_log
                _pqc_log.info("[PremiumQC] Starting PREMIUM quality check with Opus")
                yield self._sse({"type": "content", "text": "\n\n✨ **Premium Quality Check**: Opus проверяет дизайн (3 цикла)...\n", "agent": "Premium QC"})
                _pqc_opus_model = "anthropic/claude-opus-4"
                _pqc_max = 3
                _pqc_viewports = [
                    {"name": "Desktop", "width": 1920, "height": 1080, "emoji": "🖥️"},
                    {"name": "Mobile", "width": 375, "height": 812, "emoji": "📱"},
                ]
                _pqc_html_content = _qc_html_content if '_qc_html_content' in dir() else None
                
                for _pqc_iter in range(_pqc_max):
                    _pqc_log.info(f"[PremiumQC] Cycle {_pqc_iter+1}/{_pqc_max}")
                    yield self._sse({"type": "content", "text": f"\n🔄 Цикл {_pqc_iter+1}/{_pqc_max}:\n", "agent": "Premium QC"})
                    
                    _all_good = True
                    for _vp in _pqc_viewports:
                        yield self._sse({"type": "content", "text": f"  {_vp['emoji']} Скриншот {_vp['name']}...\n", "agent": "Premium QC"})
                        try:
                            # Set viewport size
                            self._execute_tool('browser_navigate', {'url': f"http://{_qc_host}"})
                            import time; time.sleep(2)
                            _ss = self._execute_tool('browser_screenshot', {})
                            _ss_b64 = _ss.get('screenshot', '')
                            if not _ss_b64:
                                continue
                            if 'base64,' in _ss_b64:
                                _ss_b64 = _ss_b64.split('base64,')[1]
                            
                            # Opus reviews
                            import requests as _pqc_req
                            _pqc_headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
                            _pqc_review = _pqc_req.post(self.api_url, headers=_pqc_headers, json={
                                "model": _pqc_opus_model,
                                "messages": [{"role": "user", "content": [
                                    {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{_ss_b64}"}},
                                    {"type": "text", "text": (
                                        f"Rate this website design ({_vp['name']} view) on a scale 1-10. "
                                        "Be critical. Check: visual hierarchy, typography, spacing, colors, "
                                        "responsiveness, modern feel (gradients, shadows, animations). "
                                        "If score < 9, describe EXACTLY what to fix. "
                                        "Format: SCORE: X/10\nISSUES: ...\nFIX: ..."
                                    )}
                                ]}],
                                "temperature": 0.3,
                                "max_tokens": 2000,
                                "stream": False,
                            }, timeout=60)
                            
                            _review = _pqc_review.json().get("choices", [{}])[0].get("message", {}).get("content", "")
                            yield self._sse({"type": "content", "text": f"  📋 Opus ({_vp['name']}): {_review[:200]}\n", "agent": "Premium QC"})
                            
                            # Check score
                            import re as _pqc_re
                            _score_match = _pqc_re.search(r'SCORE:\s*(\d+)', _review)
                            _score = int(_score_match.group(1)) if _score_match else 5
                            
                            if _score < 9:
                                _all_good = False
                                yield self._sse({"type": "content", "text": f"  ⚠️ Оценка {_score}/10 — исправляю...\n", "agent": "Premium QC"})
                                
                                # Opus fixes HTML
                                _fix_resp = _pqc_req.post(self.api_url, headers=_pqc_headers, json={
                                    "model": _pqc_opus_model,
                                    "messages": [{"role": "user", "content": [
                                        {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{_ss_b64}"}},
                                        {"type": "text", "text": (
                                            f"Fix this HTML to get 10/10 design score. Issues: {_review}\n\n"
                                            "Return ONLY the complete fixed HTML. Start with <!DOCTYPE html>. "
                                            "Use Tailwind CSS, modern gradients, shadows, animations. "
                                            "Make it Dribbble/Awwwards quality."
                                            + (f"\n\nCurrent HTML:\n{_pqc_html_content[:12000]}" if _pqc_html_content else "")
                                        )}
                                    ]}],
                                    "temperature": 0.3,
                                    "max_tokens": 16000,
                                    "stream": False,
                                }, timeout=90)
                                
                                _fixed = _fix_resp.json().get("choices", [{}])[0].get("message", {}).get("content", "")
                                if '```html' in _fixed:
                                    _fixed = _fixed.split('```html')[1].split('```')[0].strip()
                                elif '```' in _fixed:
                                    _fixed = _fixed.split('```')[1].split('```')[0].strip()
                                
                                if _fixed and _fixed.strip().startswith('<'):
                                    self._execute_tool('file_write', {
                                        'host': _qc_host,
                                        'username': self.ssh_credentials.get('username', 'root'),
                                        'password': self.ssh_credentials.get('password', ''),
                                        'path': '/var/www/html/index.html',
                                        'content': _fixed
                                    })
                                    _pqc_html_content = _fixed
                                    yield self._sse({"type": "content", "text": f"  ✅ HTML исправлен Opus\n", "agent": "Premium QC"})
                        except Exception as _pqc_e:
                            _pqc_log.warning(f"[PremiumQC] Error: {_pqc_e}")
                    
                    if _all_good:
                        yield self._sse({"type": "content", "text": f"\n🏆 Дизайн одобрен Opus — оценка 9+/10!\n", "agent": "Premium QC"})
                        break
                
                _pqc_log.info("[PremiumQC] Premium quality check completed")
            # ── END PREMIUM DESIGN QUALITY CHECK ──────────────────────────────────

            # ── QUALITY CHECK CYCLE: after deploy phases (PATCH-13: + mobile screenshot) ──
            # Detect if this was a deploy phase by agent key or phase name
            _is_deploy_phase = (
                agent_key.lower() in ('devops', 'deployer', 'deploy') or
                any(kw in phase_name.lower() for kw in ('деплой', 'deploy', 'настройк', 'сервер', 'nginx'))
            )
            # Only run quality check if there's a server URL available
            _qc_host = self.ssh_credentials.get('host', '')
            if _is_deploy_phase and _qc_host and _current_orion_mode not in PRO_MODES:
                import logging as _qc_log
                _qc_log.info(f"[QualityCheck] Starting post-deploy quality check for phase: {phase_name}")
                yield self._sse({"type": "content", "text": "\n\n🔍 **Quality Check**: Проверяю результат деплоя...\n", "agent": "Quality Check"})

                _qc_url = f"http://{_qc_host}"
                _qc_max_iterations = 2
                _qc_iteration = 0
                _qc_html_content = None  # Will store current HTML from phase_results

                # Extract HTML content from phase results (designer/developer phases)
                for _prev_phase_name, _prev_phase_text in phase_results.items():
                    if any(kw in _prev_phase_name.lower() for kw in ('дизайн', 'верстк', 'разработк', 'design', 'develop')):
                        _qc_html_content = _prev_phase_text
                        break

                while _qc_iteration < _qc_max_iterations:
                    _qc_iteration += 1
                    _qc_log.info(f"[QualityCheck] Iteration {_qc_iteration}/{_qc_max_iterations}")

                    # Step 1: MiMo (current model = hands model) takes screenshot
                    yield self._sse({"type": "content", "text": f"🌐 Открываю {_qc_url} для проверки...\n", "agent": "Quality Check"})
                    try:
                        _nav_result = self._execute_tool('browser_navigate', {'url': _qc_url})
                        _screenshot_b64 = _nav_result.get('screenshot', '')
                        if not _screenshot_b64:
                            # Try explicit screenshot
                            _ss_result = self._execute_tool('browser_screenshot', {})
                            _screenshot_b64 = _ss_result.get('screenshot', '')
                    except Exception as _qc_e:
                        _qc_log.warning(f"[QualityCheck] Browser error: {_qc_e}")
                        break

                    if not _screenshot_b64:
                        _qc_log.warning("[QualityCheck] No screenshot obtained, skipping quality check")
                        break

                    # Step 2: Send screenshot to MiniMax for design review
                    yield self._sse({"type": "content", "text": "🧠 MiniMax проверяет дизайн...\n", "agent": "Quality Check"})
                    _b64_clean = _screenshot_b64
                    if 'base64,' in _b64_clean:
                        _b64_clean = _b64_clean.split('base64,')[1]

                    _review_messages = [
                        {"role": "user", "content": [
                            {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{_b64_clean}"}},
                            {"type": "text", "text": (
                                "Посмотри на этот скриншот сайта. "
                                "CSS работает? Дизайн выглядит правильно? "
                                "Если нет — опиши конкретно что не так и напиши ИСПРАВИТЬ. "
                                "Если всё хорошо — напиши ХОРОШО. "
                                "Отвечай кратко."
                            )}
                        ]}
                    ]

                    try:
                        _review_headers = {
                            "Authorization": f"Bearer {self.api_key}",
                            "Content-Type": "application/json",
                            "HTTP-Referer": "https://orion.mksitdev.ru",
                            "X-Title": "ORION Digital v1.0"
                        }
                        _review_payload = {
                            "model": "minimax/minimax-m2.5",
                            "messages": _review_messages,
                            "temperature": 0.1,
                            "max_tokens": 800,
                            "stream": False,
                        }
                        import requests as _qc_requests
                        _review_resp = _qc_requests.post(
                            self.api_url, headers=_review_headers,
                            json=_review_payload, timeout=30
                        )
                        _review_text = ""
                        if _review_resp.status_code == 200:
                            _review_text = _review_resp.json().get("choices", [{}])[0].get("message", {}).get("content", "")
                    except Exception as _rv_e:
                        _qc_log.warning(f"[QualityCheck] MiniMax review error: {_rv_e}")
                        break

                    _qc_log.info(f"[QualityCheck] MiniMax review: {_review_text[:200]}")
                    yield self._sse({"type": "content", "text": f"💬 MiniMax: {_review_text[:300]}\n", "agent": "Quality Check"})

                    # Step 3: Check if MiniMax says there's a problem
                    _needs_fix = 'ИСПРАВИТЬ' in _review_text.upper() or 'FIX' in _review_text.upper() or 'ИСПРАВЬ' in _review_text.upper()
                    if not _needs_fix:
                        _qc_log.info("[QualityCheck] MiniMax approved the design, no fix needed")
                        yield self._sse({"type": "content", "text": "✅ Дизайн одобрен MiniMax\n", "agent": "Quality Check"})
                        break

                    # Step 4: MiniMax fixes the HTML
                    yield self._sse({"type": "content", "text": "🔧 MiniMax исправляет HTML...\n", "agent": "Quality Check"})
                    _fix_messages = [
                        {"role": "user", "content": [
                            {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{_b64_clean}"}},
                            {"type": "text", "text": (
                                f"Проблема: {_review_text}\n\n"
                                "Исправь HTML/CSS. Верни ТОЛЬКО полный исправленный HTML файл, без объяснений. "
                                "Начни с <!DOCTYPE html> и заверши </html>."
                                + (f"\n\nТекущий HTML:\n{_qc_html_content[:8000]}" if _qc_html_content else "")
                            )}
                        ]}
                    ]

                    try:
                        _fix_payload = {
                            "model": "minimax/minimax-m2.5",
                            "messages": _fix_messages,
                            "temperature": 0.3,
                            "max_tokens": 16000,
                            "stream": False,
                        }
                        _fix_resp = _qc_requests.post(
                            self.api_url, headers=_review_headers,
                            json=_fix_payload, timeout=60
                        )
                        _fixed_html = ""
                        if _fix_resp.status_code == 200:
                            _fixed_html = _fix_resp.json().get("choices", [{}])[0].get("message", {}).get("content", "")
                            # Extract HTML if wrapped in markdown code block
                            if '```html' in _fixed_html:
                                _fixed_html = _fixed_html.split('```html')[1].split('```')[0].strip()
                            elif '```' in _fixed_html:
                                _fixed_html = _fixed_html.split('```')[1].split('```')[0].strip()
                    except Exception as _fx_e:
                        _qc_log.warning(f"[QualityCheck] MiniMax fix error: {_fx_e}")
                        break

                    if not _fixed_html or not _fixed_html.strip().startswith('<'):
                        _qc_log.warning("[QualityCheck] MiniMax did not return valid HTML")
                        break

                    # Step 5: MiMo redeploys the fixed HTML
                    yield self._sse({"type": "content", "text": "🚀 Деплою исправленный HTML...\n", "agent": "Quality Check"})

                    # Find the deployed path from phase_results or use default
                    _deploy_path = "/var/www/html/index.html"
                    for _pr_name, _pr_text in phase_results.items():
                        import re as _qc_re
                        _path_match = _qc_re.search(r'/var/www/[\w./\-]+\.html', _pr_text)
                        if _path_match:
                            _deploy_path = _path_match.group(0)
                            break

                    # Switch to MiMo (hands model) for deployment
                    _saved_model = self.model
                    try:
                        from orchestrator_v2 import get_model_for_agent
                        self.model = get_model_for_agent('devops', _current_orion_mode)
                    except Exception:
                        pass

                    _deploy_result = self._execute_tool('file_write', {
                        'host': _qc_host,
                        'username': self.ssh_credentials.get('username', 'root'),
                        'password': self.ssh_credentials.get('password', ''),
                        'path': _deploy_path,
                        'content': _fixed_html
                    })
                    self.model = _saved_model

                    if _deploy_result.get('success'):
                        _qc_html_content = _fixed_html  # Update for next iteration
                        yield self._sse({"type": "content", "text": f"✅ Исправленный HTML задеплоен в {_deploy_path}\n", "agent": "Quality Check"})
                    else:
                        _qc_log.warning(f"[QualityCheck] Redeploy failed: {_deploy_result}")
                        break

                _qc_log.info(f"[QualityCheck] Completed after {_qc_iteration} iteration(s)")
            # ── END QUALITY CHECK CYCLE ──────────────────────────────────────────────
            # ── AUTO-PHOTO CHECK (PATCH-14): find missing images and generate ──────────
            if _is_deploy_phase and _qc_host:
                import logging as _ap_log
                _ap_log.info("[AutoPhoto] Starting auto-photo check")
                yield self._sse({"type": "content", "text": "\n🖼️ **Auto-Photo**: Проверяю изображения на сайте...\n", "agent": "Auto Photo"})
                try:
                    # Get HTML content from server
                    _ap_html_result = self._execute_tool('ssh_execute', {
                        'host': _qc_host,
                        'username': self.ssh_credentials.get('username', 'root'),
                        'password': self.ssh_credentials.get('password', ''),
                        'command': 'cat /var/www/html/index.html 2>/dev/null || cat /var/www/*/index.html 2>/dev/null | head -500'
                    })
                    _ap_html = _ap_html_result.get('output', '') if _ap_html_result.get('success') else ''
                    
                    # Find all img src with placeholder or missing images
                    import re as _ap_re
                    # Fixed: use compiled pattern to avoid quote escaping issues
                    _ap_pattern = re.compile(r'<img[^>]+src=[\x22\x27]([^\x22\x27]*(?:placehold|placeholder|photo\d|image\d|hero|about|team|service)[^\x22\x27]*)[\x22\x27]', re.IGNORECASE)
                    _placeholder_imgs = _ap_pattern.findall(_ap_html)
                    
                    if _placeholder_imgs:
                        _ap_log.info(f"[AutoPhoto] Found {len(_placeholder_imgs)} placeholder images")
                        yield self._sse({"type": "content", "text": f"📸 Найдено {len(_placeholder_imgs)} placeholder изображений. Генерирую AI фото...\n", "agent": "Auto Photo"})
                        
                        _generated_count = 0
                        for _img_idx, _img_src in enumerate(_placeholder_imgs[:6]):  # Max 6 images
                            # Generate descriptive prompt based on image context
                            _img_context = _img_src.lower()
                            _prompts = {
                                'hero': 'Professional modern office interior with natural lighting, minimalist design, 8k quality, photorealistic',
                                'about': 'Professional team meeting in modern conference room, diverse people collaborating, warm lighting, 8k quality',
                                'team': 'Professional portrait of business person in modern office, confident smile, soft lighting, 8k quality',
                                'service': 'Abstract technology concept with glowing blue connections and data visualization, dark background, 8k quality',
                            }
                            _prompt = 'Professional high quality business photo, modern clean aesthetic, 8k quality photorealistic'
                            for _key, _val in _prompts.items():
                                if _key in _img_context:
                                    _prompt = _val
                                    break
                            
                            try:
                                _gen_result = self._execute_tool('generate_image', {
                                    'prompt': _prompt,
                                    'width': 800,
                                    'height': 600
                                })
                                if _gen_result.get('success') and _gen_result.get('url'):
                                    _generated_count += 1
                                    yield self._sse({"type": "content", "text": f"  ✅ Фото {_generated_count} сгенерировано\n", "agent": "Auto Photo"})
                            except Exception as _gen_e:
                                _ap_log.warning(f"[AutoPhoto] generate_image failed: {_gen_e}")
                        
                        if _generated_count > 0:
                            yield self._sse({"type": "content", "text": f"🖼️ Сгенерировано {_generated_count} AI фото\n", "agent": "Auto Photo"})
                    else:
                        yield self._sse({"type": "content", "text": "✅ Placeholder изображений не найдено\n", "agent": "Auto Photo"})
                except Exception as _ap_e:
                    _ap_log.warning(f"[AutoPhoto] Error: {_ap_e}")
            # ── END AUTO-PHOTO CHECK ──────────────────────────────────────────────
            # ── TAILWIND CDN CHECK (PATCH-15) ──────────────────────────────
            if _is_deploy_phase and _qc_host:
                import logging as _tw_log
                try:
                    _tw_result = self._execute_tool('ssh_execute', {
                        'host': _qc_host,
                        'username': self.ssh_credentials.get('username', 'root'),
                        'password': self.ssh_credentials.get('password', ''),
                        'command': 'grep -l "cdn.tailwindcss" /var/www/html/index.html /var/www/*/index.html 2>/dev/null || echo "NO_TAILWIND"'
                    })
                    _tw_output = _tw_result.get('output', '') if _tw_result.get('success') else 'NO_TAILWIND'
                    if 'NO_TAILWIND' in _tw_output:
                        _tw_log.info("[TailwindCheck] Tailwind CDN not found, adding...")
                        yield self._sse({"type": "content", "text": "⚠️ Tailwind CDN не найден — добавляю...\n", "agent": "Tailwind Check"})
                        # Add Tailwind CDN to head
                        self._execute_tool('ssh_execute', {
                            'host': _qc_host,
                            'username': self.ssh_credentials.get('username', 'root'),
                            'password': self.ssh_credentials.get('password', ''),
                            'command': 'sed -i \'s|</head>|<script src="https://cdn.tailwindcss.com"></script>\n</head>|\' /var/www/html/index.html 2>/dev/null'
                        })
                        yield self._sse({"type": "content", "text": "✅ Tailwind CDN добавлен\n", "agent": "Tailwind Check"})
                    else:
                        yield self._sse({"type": "content", "text": "✅ Tailwind CDN подключён\n", "agent": "Tailwind Check"})
                except Exception as _tw_e:
                    _tw_log.warning(f"[TailwindCheck] Error: {_tw_e}")
            # ── END TAILWIND CDN CHECK ──────────────────────────────────────



        # All phases complete
        yield self._sse({
            "type": "task_complete",
            "text": f"Все {total_phases} фаз выполнены.",
            "phases_completed": total_phases
        })
    
    def _agent_emoji(self, agent_key):
        """Get emoji for agent type."""
        emojis = {
            'devops': '🔧', 'designer': '🎨', 'developer': '💻',
            'tester': '🧪', 'analyst': '📊', 'copywriter': '✍️',
            'architect': '🏗️'
        }
        return emojis.get(agent_key, '🤖')

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
                yield self._sse({"type": "heartbeat", "message": "agent_thinking"})
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
                            "content": json.dumps({k: ("[screenshot sent to user]" if k == "screenshot" else v) for k, v in result.items()}, ensure_ascii=False)
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
                    # BUG-11 FIX: Anti-loop detection
                    import hashlib as _hl
                    _tc_key = tool_name + ":" + str(sorted(tool_args.items()) if isinstance(tool_args, dict) else str(tool_args))
                    _tc_hash = _hl.md5(_tc_key.encode()).hexdigest()[:8]
                    if not hasattr(self, "_loop_counter"):
                        self._loop_counter = {}
                    self._loop_counter[_tc_hash] = self._loop_counter.get(_tc_hash, 0) + 1
                    _repeat_count = self._loop_counter[_tc_hash]
                    if _repeat_count >= 3:
                        _current_model = self.model
                        _fallback = ["anthropic/claude-sonnet-4-5", "anthropic/claude-opus-4-5", "openai/gpt-4o"]
                        _new_model = next((m for m in _fallback if m != _current_model), _fallback[0])
                        logging.warning("[AntiLoop] " + tool_name + " repeated " + str(_repeat_count) + "x! Switching model " + _current_model + " -> " + _new_model)
                        self.model = _new_model
                        messages.append({"role": "system", "content": "ВНИМАНИЕ: Ты уже вызывал инструмент '" + tool_name + "' с теми же аргументами " + str(_repeat_count) + " раз. ОБЯЗАТЕЛЬНО попробуй ДРУГОЙ инструмент или ДРУГОЙ подход."})
                    elif _repeat_count >= 2:
                        logging.warning("[AntiLoop] " + tool_name + " repeated " + str(_repeat_count) + "x - warning injected")
                        messages.append({"role": "system", "content": "ПРЕДУПРЕЖДЕНИЕ: Ты уже вызывал '" + tool_name + "' с похожими аргументами. Если результат тот же - попробуй другой подход."})

                    # ── ANTI-LOOP for pipeline ──
                    _ph_hash = hashlib.md5(f"{tool_name}:{tool_args_str[:200]}".encode()).hexdigest()
                    _phase_tool_history[_ph_hash] = _phase_tool_history.get(_ph_hash, 0) + 1
                    _ph_count = _phase_tool_history[_ph_hash]
                    if _ph_count >= 2:
                        _phase_consecutive_loops += 1
                        logger.warning(f"[ANTI-LOOP-PIPELINE] Phase {phase_idx+1} agent {agent_key}: {tool_name} called {_ph_count}x. Loop: {_phase_consecutive_loops}")
                        if _phase_consecutive_loops >= 3 and _phase_model_escalation == 0:
                            _phase_model_escalation = 1
                            self.model = "anthropic/claude-sonnet-4-5"
                            logger.warning(f"[ANTI-LOOP-PIPELINE] Escalating to Sonnet")
                            yield self._sse({"type": "info", "message": f"🔄 Переключаю на Sonnet для выхода из цикла в фазе {phase_idx+1}..."})
                            messages.append({"role": "system", "content": (
                                f"КРИТИЧЕСКОЕ: Ты вызвал {tool_name} {_ph_count} раз с теми же аргументами. "
                                f"Это цикл. Немедленно используй ДРУГОЙ инструмент или вызови task_complete."
                            )})
                        elif _phase_consecutive_loops >= 5 and _phase_model_escalation == 1:
                            _phase_model_escalation = 2
                            self.model = "anthropic/claude-opus-4-5"
                            logger.warning(f"[ANTI-LOOP-PIPELINE] Escalating to Opus")
                            yield self._sse({"type": "info", "message": f"🔄 Переключаю на Claude Opus для выхода из цикла..."})
                        elif _phase_consecutive_loops >= 7:
                            _ask_result = self._execute_tool("ask_user", json.dumps({
                                "question": f"Агент застрял в фазе '{phase.get('name', phase_idx+1)}' на действии '{tool_name}' ({_ph_count} повторений). Как продолжить?",
                                "context": "Pipeline застрял в цикле"
                            }, ensure_ascii=False))
                            yield self._sse({"type": "info", "message": "⚠️ Pipeline застрял — запрашиваю помощь пользователя"})
                            messages.append({"role": "tool", "tool_call_id": tool_id, "content": json.dumps(_ask_result, ensure_ascii=False)})
                            _phase_consecutive_loops = 0
                            _phase_tool_history.clear()
                    else:
                        _phase_consecutive_loops = max(0, _phase_consecutive_loops - 1)
                        if _phase_model_escalation > 0:
                            self.model = _phase_original_model
                            _phase_model_escalation = 0

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

                    _result_clean = {k: ("[screenshot sent to user]" if k == "screenshot" else v) for k, v in result.items()}
                    result_str = json.dumps(_result_clean, ensure_ascii=False)
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
