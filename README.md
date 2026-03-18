# ORION Digital — Autonomous AI IT-Studio

**ORION** is an autonomous multi-agent AI system that independently executes web development tasks: server management, CMS administration, browser automation, and full-stack development.

**Live Demo:** [orion.mksitdev.ru](https://orion.mksitdev.ru)

---

## Architecture

```
┌──────────────────────────────────────────────────┐
│                   Frontend                        │
│          HTML + CSS + Vanilla JS                  │
│          SSE streaming, Activity Panel            │
├──────────────────────────────────────────────────┤
│                   Backend                         │
│          Flask + Gunicorn (Python 3.12)           │
│          Agent Loop + Orchestrator v2             │
├──────────────────────────────────────────────────┤
│                 AI Models                         │
│    DeepSeek V3 · Claude Sonnet · Claude Opus      │
│    Gemini Pro · GPT-4.1                           │
├──────────────────────────────────────────────────┤
│                Capabilities                       │
│    SSH/FTP · Browser Automation (Playwright)      │
│    Code Generation · Image Generation             │
│    Bitrix/WordPress CMS · SEO · Copywriting       │
└──────────────────────────────────────────────────┘
```

## Dual Prompt Architecture (BUG-11)

ORION uses a **dual prompt system** that adapts to model capabilities:

| Mode | Model | System Prompt | Context Window |
|------|-------|---------------|----------------|
| Turbo Standard | DeepSeek V3 | Full (50+ rules) | 10 messages |
| Turbo Premium | DeepSeek V3 | Full (50+ rules) | 10 messages |
| Pro Standard | Claude Sonnet | Minimal (20 lines) | 50 messages |
| Pro Premium | Claude Sonnet | Minimal (20 lines) | 50 messages |
| Architect | Claude Opus | Minimal (20 lines) | 50 messages |

**Philosophy:** Trust smart models. Sonnet and Opus already know how to work with nginx, Docker, Bitrix, etc. They don't need 50 rules teaching them. DeepSeek, being weaker, still benefits from detailed instructions.

## Key Features

- **Multi-Agent System** — Orchestrator assigns tasks to specialized agents (developer, designer, devops, tester, copywriter)
- **Browser Automation** — Full Playwright integration: click, fill, submit, select, screenshot, login detection
- **FTP Tools** — Direct file upload/download via `ftplib` (no SSH required)
- **SSH Execution** — Remote command execution with auto-backup before destructive operations
- **Anti-Loop Detection** — Detects 3 identical tool calls in a row; Pro mode warns the model, Turbo mode escalates to Sonnet
- **Memory System** — v9 memory engine with semantic search, working memory, and aggressive context compression
- **Solution Cache** — Learns from successful solutions and reuses patterns
- **Cross-Learning** — Shares knowledge between agents via error patterns database
- **Auth Flow** — Secure browser login: agent detects login forms, asks user for credentials via UI
- **Task Planning** — Generates execution plan before starting, shows progress in Activity Panel
- **Chain of Thought** — Pro/Architect modes think and plan before acting (visible in Activity Panel)
- **File Logging** — All backend activity logged to `/var/log/orion-backend.log`

## Project Structure

```
orion/
├── backend/
│   ├── app.py                  # Flask API, routing, auth
│   ├── agent_loop.py           # Agent loop, tools, prompts (TOOLS_SCHEMA)
│   ├── orchestrator_v2.py      # Task planner, model selection, agent prompts
│   ├── parallel_agents.py      # Parallel/sequential agent execution
│   ├── browser_agent.py        # Playwright browser automation + FTP
│   ├── specialized_agents.py   # Agent definitions and pipelines
│   ├── solution_cache.py       # Successful solution caching
│   ├── ssh_executor.py         # SSH/SFTP execution
│   ├── model_router.py         # LLM model routing
│   ├── database.py             # SQLite database operations
│   ├── memory_v9/              # Memory engine
│   │   ├── config.py
│   │   ├── engine.py
│   │   ├── working.py
│   │   └── semantic.py
│   └── data/
│       └── knowledge_base/     # Hosting guides, DNS configs
├── frontend/
│   ├── app.js                  # SPA frontend
│   └── index.html              # Entry point
├── docs/
│   └── BUG-11-report.md        # Architecture change report
├── robots.txt                  # Allow all crawlers
└── README.md
```

## Modes

### Turbo (DeepSeek V3)
Best for simple tasks. Cheap and fast. Uses detailed prompts with 50+ rules to guide the model.

### Pro (Claude Sonnet)
Best for complex tasks. Minimal prompt — the model decides how to approach the task. 5x larger context window. Chain of thought planning.

### Architect (Claude Opus)
Best for system design and architecture. Uses the most capable model with full autonomy.

## Quick Start

```bash
# Clone
git clone https://github.com/mksmediengruppe-netizen/orion.git
cd orion

# Setup
cd backend
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Configure
cp .env.example .env
# Edit .env with your API keys

# Run
gunicorn --worker-class gthread --workers 1 --threads 8 --bind 0.0.0.0:3510 app:app
```

## Environment Variables

| Variable | Description |
|----------|-------------|
| `OPENROUTER_API_KEY` | OpenRouter API key for model access |
| `DATA_DIR` | Data directory path (default: `./data`) |
| `PLAYWRIGHT_BROWSERS_PATH` | Playwright browser path |

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/login` | POST | User authentication |
| `/api/chats` | GET | List user chats |
| `/api/chats/<id>/send` | POST | Send message (SSE stream) |
| `/api/chats/<id>/send_v2` | POST | Send message v2 (SSE stream) |
| `/api/estimate` | POST | Project cost estimation |
| `/api/admin/stats` | GET | Admin statistics |

## License

Proprietary. MKS Mediengruppe / Netizen.

## Changelog

- **v6.1** (2026-03-18) — Dual prompt architecture, anti-loop detection, file logging
- **v6.0** (2026-03-17) — Creative Suite, Web Search, Memory & Projects, Canvas, Multi-Model Routing
- **v5.0** — Browser Automation, FTP Tools, Professional Prompts
- **v4.0** — Multi-Agent Orchestrator, Parallel Execution
- **v3.0** — Memory v9, Solution Cache, Cross-Learning
