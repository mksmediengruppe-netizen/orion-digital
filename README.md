# ORION Digital — AI IT-Studio

**ORION** is an autonomous multi-agent AI system designed to independently execute web development tasks: server management, CMS administration, browser automation, and full-stack development.

## Architecture

```
┌─────────────────────────────────────────────┐
│                  Frontend                    │
│        HTML + CSS + Vanilla JS               │
│        SSE streaming, Activity Panel         │
├─────────────────────────────────────────────┤
│                  Backend                     │
│        Flask + Gunicorn (Python 3.11)        │
│        Agent Loop + Orchestrator v2          │
├─────────────────────────────────────────────┤
│               AI Models                      │
│   DeepSeek V3 · Claude Sonnet · Gemini Pro   │
│   Qwen3 · GPT-4.1                           │
├─────────────────────────────────────────────┤
│              Capabilities                    │
│   SSH/FTP · Browser Automation (Playwright)  │
│   Code Generation · Image Generation         │
│   Bitrix/WordPress CMS · SEO · Copywriting   │
└─────────────────────────────────────────────┘
```

## Key Features

- **Multi-Agent System** — Orchestrator assigns tasks to specialized agents (developer, designer, devops, tester, copywriter)
- **Browser Automation** — Full Playwright integration: click, fill, submit, select, screenshot, login detection
- **FTP Tools** — Direct file upload/download via `ftplib` (no SSH required)
- **SSH Execution** — Remote command execution with auto-backup before destructive operations
- **Memory System** — v9 memory engine with semantic search, working memory, and aggressive context compression
- **Solution Cache** — Learns from successful solutions and reuses patterns
- **Cross-Learning** — Shares knowledge between agents via error patterns database
- **Auth Flow** — Secure browser login: agent detects login forms, asks user for credentials via UI (no passwords stored in chat)
- **Task Planning** — Generates execution plan before starting, shows progress in Activity Panel
- **Auto-Estimate** — `/api/estimate` endpoint for project cost estimation

## Project Structure

```
backend/
├── app.py                  # Flask API, routing, auth
├── agent_loop.py           # Agent loop, tools, prompts (TOOLS_SCHEMA)
├── orchestrator_v2.py      # Task planner, model selection, agent prompts
├── parallel_agents.py      # Parallel/sequential agent execution
├── browser_agent.py        # Playwright browser automation + FTP
├── specialized_agents.py   # Agent definitions and pipelines
├── solution_cache.py       # Successful solution caching
├── ssh_executor.py         # SSH/SFTP execution
├── model_router.py         # LLM model routing
├── database.py             # SQLite database operations
├── memory_v9/              # Memory engine
│   ├── config.py           # Memory thresholds
│   ├── engine.py           # Core memory engine
│   ├── working.py          # Working memory with compression
│   └── semantic.py         # Semantic search
└── data/                   # Runtime data (gitignored)

frontend/
├── index.html              # Main UI
├── app.js                  # UI logic, SSE handling, AuthForm
└── style.css               # Styles
```

## Deployment

**Server:** Ubuntu 22.04 with Gunicorn + Nginx

```bash
# Service
sudo systemctl restart orion-api
sudo systemctl status orion-api

# Logs
journalctl -u orion-api -n 50

# Service file
/etc/systemd/system/orion-api.service
```

## Applied Patches

| Patch | Description |
|-------|-------------|
| A1-A3 | Brain + UI Polish |
| A4-A6 | Orchestrator v2 |
| A7-A9 | Frontend TaskPlan, AskUser, MultiSSH |
| Task 1 | Browser Automation (Playwright) + FTP tools + browser_ask_auth |
| Task 4 | Professional Developer Prompt |
| W1-1 | Mode persistence in localStorage |
| W1-2 | Task plan before execution |
| W1-3 | Auto-backup before destructive operations |
| W1-4 | Enhanced task queue UI |
| W1-5 | Screenshot auto-analysis |
| W2-1 | Aggressive context compression |
| W2-2 | Activity Panel task progress |
| W2-3 | Copywriter + SEO agent |
| W2-4 | Auto-estimate /api/estimate |
| W2-5 | Parallel agents improvements |

## Environment Variables

```
OPENROUTER_API_KEY=...    # LLM API access
ANTHROPIC_API_KEY=...     # Claude models
```

## License

Proprietary — MKS Mediengruppe / Netizen
