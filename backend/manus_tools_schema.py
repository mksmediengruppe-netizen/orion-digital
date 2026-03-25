"""
Manus Tools Schema — Схемы 10 новых инструментов для tools_schema.py
Добавляется в конец TOOLS_SCHEMA списка.
"""

MANUS_TOOLS_SCHEMA = [
    # ─── 1. WEB SCRAPE ───────────────────────────────────────────────
    {
        "type": "function",
        "function": {
            "name": "web_scrape",
            "description": "Deep web scraping: extract structured data from web pages. Use for: extracting tables, contacts, links, images, full text from any website. Supports CSS selectors, pagination, and contact extraction (emails, phones).",
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {
                        "type": "string",
                        "description": "URL of the page to scrape"
                    },
                    "extract": {
                        "type": "string",
                        "enum": ["all", "text", "tables", "links", "images", "contacts"],
                        "description": "What to extract: all, text, tables, links, images, or contacts (emails/phones)",
                        "default": "all"
                    },
                    "selector": {
                        "type": "string",
                        "description": "CSS selector to focus on specific element (e.g. 'article', '.content', '#main')"
                    },
                    "follow_links": {
                        "type": "boolean",
                        "description": "Follow pagination links",
                        "default": False
                    },
                    "max_pages": {
                        "type": "integer",
                        "description": "Maximum pages to scrape when follow_links=true",
                        "default": 1
                    }
                },
                "required": ["url"]
            }
        }
    },

    # ─── 2. PDF READ ─────────────────────────────────────────────────
    {
        "type": "function",
        "function": {
            "name": "pdf_read",
            "description": "Read and analyze PDF files. Extracts text, tables, metadata from PDF. Works with local files or URLs. Use for: reading contracts, reports, documentation, research papers.",
            "parameters": {
                "type": "object",
                "properties": {
                    "source": {
                        "type": "string",
                        "description": "File path or URL to PDF"
                    },
                    "pages": {
                        "type": "string",
                        "description": "Pages to read: 'all', '1-5', '1,3,5', or single page number",
                        "default": "all"
                    },
                    "extract": {
                        "type": "string",
                        "enum": ["text", "tables", "metadata", "all"],
                        "description": "What to extract from PDF",
                        "default": "text"
                    },
                    "question": {
                        "type": "string",
                        "description": "Specific question to find answer for in the document"
                    }
                },
                "required": ["source"]
            }
        }
    },

    # ─── 3. EXCEL CREATE ─────────────────────────────────────────────
    {
        "type": "function",
        "function": {
            "name": "excel_create",
            "description": "Create Excel (.xlsx) files with data, formulas, styles, and charts. Use for: reports, data tables, financial models, dashboards. Supports multiple sheets, auto-filter, freeze panes, alternating row colors.",
            "parameters": {
                "type": "object",
                "properties": {
                    "filename": {
                        "type": "string",
                        "description": "Output filename without .xlsx extension"
                    },
                    "sheets": {
                        "type": "array",
                        "description": "List of sheets to create",
                        "items": {
                            "type": "object",
                            "properties": {
                                "name": {"type": "string", "description": "Sheet name"},
                                "headers": {
                                    "type": "array",
                                    "items": {"type": "string"},
                                    "description": "Column headers"
                                },
                                "data": {
                                    "type": "array",
                                    "items": {"type": "array"},
                                    "description": "2D array of data rows"
                                },
                                "formulas": {
                                    "type": "object",
                                    "description": "Cell formulas dict, e.g. {\"D2\": \"=B2*C2\", \"D3\": \"=B3*C3\"}"
                                }
                            }
                        }
                    },
                    "title": {
                        "type": "string",
                        "description": "Document title"
                    },
                    "add_charts": {
                        "type": "boolean",
                        "description": "Automatically add bar charts for numeric data",
                        "default": False
                    }
                },
                "required": ["filename", "sheets"]
            }
        }
    },

    # ─── 4. SLIDES CREATE ────────────────────────────────────────────
    {
        "type": "function",
        "function": {
            "name": "slides_create",
            "description": "Create professional PowerPoint (.pptx) presentations with design themes. Use for: reports, pitches, demos, training materials. Supports title slides, content slides, two-column layouts, and table slides.",
            "parameters": {
                "type": "object",
                "properties": {
                    "filename": {
                        "type": "string",
                        "description": "Output filename without .pptx extension"
                    },
                    "slides": {
                        "type": "array",
                        "description": "List of slides",
                        "items": {
                            "type": "object",
                            "properties": {
                                "type": {
                                    "type": "string",
                                    "enum": ["title", "content", "two_col", "table"],
                                    "description": "Slide layout type"
                                },
                                "title": {"type": "string", "description": "Slide title"},
                                "content": {"type": "string", "description": "Main content text (use \\n for bullet points starting with - or •)"},
                                "subtitle": {"type": "string", "description": "Subtitle for title slides"},
                                "left": {"type": "string", "description": "Left column content for two_col type"},
                                "right": {"type": "string", "description": "Right column content for two_col type"},
                                "table_data": {
                                    "type": "array",
                                    "items": {"type": "array"},
                                    "description": "2D array for table slides (first row = headers)"
                                }
                            }
                        }
                    },
                    "theme": {
                        "type": "string",
                        "enum": ["modern", "dark", "clean"],
                        "description": "Visual theme: modern (dark blue), dark (black/purple), clean (white/blue)",
                        "default": "modern"
                    },
                    "title": {
                        "type": "string",
                        "description": "Presentation overall title"
                    }
                },
                "required": ["filename", "slides"]
            }
        }
    },

    # ─── 5. TRANSCRIBE AUDIO ─────────────────────────────────────────
    {
        "type": "function",
        "function": {
            "name": "transcribe_audio",
            "description": "Transcribe audio/video files to text using Whisper AI. Supports MP3, WAV, MP4, WebM, M4A, OGG, FLAC. Can output plain text, SRT subtitles, VTT, or JSON with timestamps. Auto-detects language.",
            "parameters": {
                "type": "object",
                "properties": {
                    "source": {
                        "type": "string",
                        "description": "File path or URL to audio/video file"
                    },
                    "language": {
                        "type": "string",
                        "description": "Language code for transcription (e.g. 'ru', 'en'). Leave empty for auto-detection."
                    },
                    "output_format": {
                        "type": "string",
                        "enum": ["text", "srt", "vtt", "json"],
                        "description": "Output format: text (plain), srt (subtitles), vtt (web subtitles), json (with timestamps)",
                        "default": "text"
                    }
                },
                "required": ["source"]
            }
        }
    },

    # ─── 6. GIT EXECUTE ──────────────────────────────────────────────
    {
        "type": "function",
        "function": {
            "name": "git_execute",
            "description": "Execute Git operations: clone, status, add, commit, push, pull, branch, log, diff, create PR. Use for: version control, code management, GitHub automation.",
            "parameters": {
                "type": "object",
                "properties": {
                    "operation": {
                        "type": "string",
                        "enum": ["clone", "status", "add", "commit", "push", "pull", "branch", "log", "diff", "pr"],
                        "description": "Git operation to perform"
                    },
                    "repo_url": {
                        "type": "string",
                        "description": "Repository URL (required for clone)"
                    },
                    "repo_path": {
                        "type": "string",
                        "description": "Local path to repository (required for most operations)"
                    },
                    "branch": {
                        "type": "string",
                        "description": "Branch name (for branch/checkout operations)"
                    },
                    "message": {
                        "type": "string",
                        "description": "Commit message"
                    },
                    "files": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Specific files to add (empty = add all)"
                    },
                    "pr_title": {
                        "type": "string",
                        "description": "Pull Request title"
                    },
                    "pr_body": {
                        "type": "string",
                        "description": "Pull Request description"
                    }
                },
                "required": ["operation"]
            }
        }
    },

    # ─── 7. HTTP REQUEST ─────────────────────────────────────────────
    {
        "type": "function",
        "function": {
            "name": "http_request",
            "description": "Make HTTP API calls to external services. Supports GET, POST, PUT, PATCH, DELETE with JSON body, query params, and authentication (Bearer token, API key, Basic auth). Use for: calling REST APIs, webhooks, integrations.",
            "parameters": {
                "type": "object",
                "properties": {
                    "method": {
                        "type": "string",
                        "enum": ["GET", "POST", "PUT", "PATCH", "DELETE"],
                        "description": "HTTP method"
                    },
                    "url": {
                        "type": "string",
                        "description": "Full URL including protocol (https://...)"
                    },
                    "headers": {
                        "type": "object",
                        "description": "Additional HTTP headers as key-value pairs"
                    },
                    "params": {
                        "type": "object",
                        "description": "URL query parameters as key-value pairs"
                    },
                    "body": {
                        "type": "object",
                        "description": "Request body (will be sent as JSON)"
                    },
                    "auth_type": {
                        "type": "string",
                        "enum": ["bearer", "basic", "api_key"],
                        "description": "Authentication type"
                    },
                    "auth_value": {
                        "type": "string",
                        "description": "Auth token/key value. For basic: 'user:password'"
                    },
                    "timeout": {
                        "type": "integer",
                        "description": "Request timeout in seconds",
                        "default": 30
                    }
                },
                "required": ["method", "url"]
            }
        }
    },

    # ─── 8. PARALLEL TASKS ───────────────────────────────────────────
    {
        "type": "function",
        "function": {
            "name": "parallel_tasks",
            "description": "Execute multiple independent Python code tasks in parallel using ThreadPoolExecutor. Use when you need to process multiple items simultaneously (e.g., scrape 10 URLs, analyze 5 files, run 3 calculations at once). Returns aggregated results.",
            "parameters": {
                "type": "object",
                "properties": {
                    "tasks": {
                        "type": "array",
                        "description": "List of tasks to execute in parallel",
                        "items": {
                            "type": "object",
                            "properties": {
                                "id": {"type": "string", "description": "Unique task identifier"},
                                "code": {"type": "string", "description": "Python code to execute"},
                                "description": {"type": "string", "description": "Human-readable task description"}
                            },
                            "required": ["code"]
                        }
                    },
                    "max_workers": {
                        "type": "integer",
                        "description": "Maximum parallel workers (default: 5, max: 20)",
                        "default": 5
                    },
                    "timeout_per_task": {
                        "type": "integer",
                        "description": "Timeout per individual task in seconds",
                        "default": 60
                    }
                },
                "required": ["tasks"]
            }
        }
    },

    # ─── 9. RESEARCH DEEP ────────────────────────────────────────────
    {
        "type": "function",
        "function": {
            "name": "research_deep",
            "description": "Deep multi-source research on any topic. Searches the web, fetches full content from multiple sources, and synthesizes a comprehensive report using AI. Use for: market research, competitor analysis, technical research, fact-checking.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Research topic or question"
                    },
                    "depth": {
                        "type": "integer",
                        "description": "Research depth 1-5 (5 = most thorough)",
                        "default": 3
                    },
                    "sources": {
                        "type": "integer",
                        "description": "Number of sources to analyze (default: 5)",
                        "default": 5
                    },
                    "output_format": {
                        "type": "string",
                        "enum": ["report", "summary", "bullets"],
                        "description": "Output format: full report, short summary, or bullet points",
                        "default": "report"
                    }
                },
                "required": ["query"]
            }
        }
    },

    # ─── 10. LONG MEMORY SEARCH ──────────────────────────────────────
    {
        "type": "function",
        "function": {
            "name": "long_memory_search",
            "description": "Search agent's long-term memory across all sessions. Finds relevant past experiences, learned facts, and procedural knowledge. Use to: recall previous server configs, remember user preferences, find past solutions to similar problems.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Search query to find relevant memories"
                    },
                    "user_id": {
                        "type": "string",
                        "description": "Filter by user ID (leave empty for all users)"
                    },
                    "memory_type": {
                        "type": "string",
                        "enum": ["episodic", "semantic", "procedural", "all"],
                        "description": "Type of memory to search: episodic (past events), semantic (facts), procedural (how-to patterns), all",
                        "default": "all"
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Maximum number of results",
                        "default": 10
                    }
                },
                "required": ["query"]
            }
        }
    }
]
