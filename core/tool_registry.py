"""
ARCANE 2 — Tool Registry
==========================
Registry of tools available to the AgentLoop.
Each tool has a name, async handler, and OpenAI function-calling schema.

Used by: core/tool_executor.py, core/agent_loop.py (via get_tools_schema)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

logger = logging.getLogger("arcane2.tool_registry")


@dataclass
class RegisteredTool:
    """A single registered tool."""
    name: str
    handler: Callable
    schema: dict[str, Any]
    requires: str = ""          # "ssh", "browser", "" = always available
    description: str = ""


class ToolRegistry:
    """
    Central registry of tools.

    Usage:
        registry = ToolRegistry()
        registry.register("file_write", handler_fn, FILE_WRITE_SCHEMA)
        schemas = registry.get_tools_schema()
        handler = registry.get_handler("file_write")
    """

    def __init__(self):
        self._tools: dict[str, RegisteredTool] = {}

    def register(
        self,
        name: str,
        handler: Callable,
        schema: dict[str, Any],
        requires: str = "",
        description: str = "",
    ) -> None:
        """Register a tool with its handler and schema."""
        self._tools[name] = RegisteredTool(
            name=name,
            handler=handler,
            schema=schema,
            requires=requires,
            description=description or schema.get("function", {}).get("description", ""),
        )
        logger.debug(f"Registered tool: {name}" + (f" [requires={requires}]" if requires else ""))

    def get_tools_schema(self, capabilities: set[str] | None = None) -> list[dict]:
        """
        Return tool schemas in OpenAI function-calling format.
        Filters by capabilities (e.g. {"ssh", "browser"}).
        Tools with no `requires` are always included.
        """
        result = []
        for tool in self._tools.values():
            if tool.requires:
                if capabilities is None or tool.requires not in capabilities:
                    continue
            result.append(tool.schema)
        return result

    def get_handler(self, name: str) -> Callable | None:
        """Get handler for a tool by name."""
        tool = self._tools.get(name)
        return tool.handler if tool else None

    def has_tool(self, name: str) -> bool:
        return name in self._tools

    def list_tools(self) -> list[str]:
        return list(self._tools.keys())

    def __len__(self) -> int:
        return len(self._tools)


# ═══════════════════════════════════════════════════════════════════════════════
# TOOL SCHEMAS — OpenAI function-calling format
# ═══════════════════════════════════════════════════════════════════════════════

def _schema(name: str, description: str, properties: dict, required: list[str]) -> dict:
    """Helper to build OpenAI function-calling schema."""
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {
                "type": "object",
                "properties": properties,
                "required": required,
            },
        },
    }


# ── File tools ────────────────────────────────────────────────────────────────

FILE_WRITE_SCHEMA = _schema(
    "file_write",
    "Write content to a file. Creates directories if needed. Overwrites if exists.",
    {
        "path":    {"type": "string",  "description": "Relative path from project root (e.g. 'src/index.html')"},
        "content": {"type": "string",  "description": "Full file content to write"},
        "raw":     {"type": "boolean", "description": "Optional flag, ignored — always writes UTF-8 text", "default": False},
    },
    ["path", "content"],
)

FILE_CREATE_SCHEMA = _schema(
    "file_create",
    "Create a new file with content. Alias for file_write.",
    {
        "path": {"type": "string", "description": "Relative path from project root"},
        "content": {"type": "string", "description": "File content"},
    },
    ["path", "content"],
)

FILE_READ_SCHEMA = _schema(
    "file_read",
    "Read content of a file.",
    {
        "path": {"type": "string", "description": "Relative path from project root"},
    },
    ["path"],
)

FILE_EDIT_SCHEMA = _schema(
    "file_edit",
    "Edit a file by replacing a specific string. old_str must appear exactly once.",
    {
        "path": {"type": "string", "description": "Relative path from project root"},
        "old_str": {"type": "string", "description": "Exact string to find and replace"},
        "new_str": {"type": "string", "description": "Replacement string"},
    },
    ["path", "old_str", "new_str"],
)

FILE_LIST_SCHEMA = _schema(
    "file_list",
    "List files in a directory.",
    {
        "path": {"type": "string", "description": "Relative directory path (default: '.')"},
    },
    [],
)

# ── Shell ─────────────────────────────────────────────────────────────────────

SHELL_EXEC_SCHEMA = _schema(
    "shell_exec",
    "Execute a shell command in the project directory. Use for running tests, installing packages, building, etc.",
    {
        "command": {"type": "string", "description": "Shell command to execute"},
    },
    ["command"],
)

# ── Communication ─────────────────────────────────────────────────────────────

MESSAGE_SCHEMA = _schema(
    "message",
    "Send a message. type='result' for final answer, type='info' for progress updates.",
    {
        "type": {"type": "string", "enum": ["result", "info"], "description": "'result' = final answer, 'info' = progress update"},
        "content": {"type": "string", "description": "Message content"},
    },
    ["type", "content"],
)

PLAN_SCHEMA = _schema(
    "plan",
    "Create or update the task execution plan.",
    {
        "steps": {
            "type": "array",
            "items": {"type": "string"},
            "description": "List of steps to complete the task",
        },
    },
    ["steps"],
)

SCRATCHPAD_SCHEMA = _schema(
    "update_scratchpad",
    "Update working notes (scratchpad). Use to track progress, decisions, issues.",
    {
        "content": {"type": "string", "description": "Full scratchpad content (replaces previous)"},
    },
    ["content"],
)

# ── Search ────────────────────────────────────────────────────────────────────

WEB_SEARCH_SCHEMA = _schema(
    "web_search",
    "Search the web for information.",
    {
        "query": {"type": "string", "description": "Search query"},
    },
    ["query"],
)

# ── SSH tools (registered conditionally) ──────────────────────────────────────

SSH_EXEC_SCHEMA = _schema(
    "ssh_exec",
    "Execute a command on the remote server via SSH.",
    {
        "command": {"type": "string", "description": "Command to execute"},
    },
    ["command"],
)

SSH_READ_FILE_SCHEMA = _schema(
    "ssh_read_file",
    "Read a file from the remote server.",
    {
        "path": {"type": "string", "description": "Absolute path on the server"},
    },
    ["path"],
)

SSH_WRITE_FILE_SCHEMA = _schema(
    "ssh_write_file",
    "Write a file on the remote server (with automatic backup).",
    {
        "path": {"type": "string", "description": "Absolute path on the server"},
        "content": {"type": "string", "description": "File content"},
    },
    ["path", "content"],
)

SSH_LIST_DIR_SCHEMA = _schema(
    "ssh_list_dir",
    "List files in a directory on the remote server.",
    {
        "path": {"type": "string", "description": "Absolute directory path on the server"},
    },
    ["path"],
)

SSH_PATCH_FILE_SCHEMA = _schema(
    "ssh_patch_file",
    "Replace lines in a file on the remote server by line numbers.",
    {
        "path": {"type": "string", "description": "Absolute path on the server"},
        "line_from": {"type": "integer", "description": "Start line number (1-based)"},
        "line_to": {"type": "integer", "description": "End line number (inclusive)"},
        "new_content": {"type": "string", "description": "Replacement content"},
    },
    ["path", "line_from", "line_to", "new_content"],
)

SSH_BACKUP_SCHEMA = _schema(
    "ssh_backup",
    "Create a backup of a file or directory on the remote server.",
    {
        "path": {"type": "string", "description": "Path to backup"},
    },
    ["path"],
)

SSH_BATCH_SCHEMA = _schema(
    "ssh_batch",
    "Execute multiple commands on the remote server in one call.",
    {
        "commands": {
            "type": "array",
            "items": {"type": "string"},
            "description": "List of commands to execute sequentially",
        },
    },
    ["commands"],
)

SSH_TAIL_LOG_SCHEMA = _schema(
    "ssh_tail_log",
    "Read the last N lines of a log file on the remote server.",
    {
        "path": {"type": "string", "description": "Absolute path to log file"},
        "lines": {"type": "integer", "description": "Number of lines (default 50)"},
    },
    ["path"],
)

# ── Image generation (registered conditionally) ──────────────────────────────

IMAGE_GENERATE_SCHEMA = _schema(
    "image_generate",
    "Generate an image from a text description.",
    {
        "prompt": {"type": "string", "description": "Image description/prompt"},
        "style": {"type": "string", "description": "Style: 'photo', 'illustration', 'icon', 'logo'"},
        "size": {"type": "string", "description": "Size: '1024x1024', '1024x768', '768x1024'"},
    },
    ["prompt"],
)

DEPLOY_TO_VPS_SCHEMA = _schema(
    "deploy_to_vps",
    "Deploy project files to VPS via SSH. Uploads files, reloads nginx, runs health check.",
    {
        "project_id": {"type": "string", "description": "Project ID to deploy"},
        "deploy_path": {"type": "string", "description": "Remote deploy path (default: /var/www/html)"},
    },
    ["project_id"],
)

