"""
ORION Surgical File Editing
============================
Provides Manus-style file editing capabilities:
- file_edit: Find and replace specific text (surgical edits)
- file_write: Full file overwrite
- file_read: Read file with optional line range
- file_append: Append content to file

Mirrors Manus AI file tool with `edit` action supporting
multiple find/replace operations in a single call.
"""

import os
import logging
from typing import Dict, List, Optional

logger = logging.getLogger("surgical_file_edit")


def tool_file_edit(path: str, edits: List[Dict], sandbox_id: str = None) -> Dict:
    """
    Make targeted edits to a text file.
    Each edit has {find, replace, all} — finds exact text and replaces it.
    All edits are applied sequentially; all must succeed or none are applied.
    
    Mirrors Manus file tool `edit` action.
    
    Args:
        path: Absolute file path
        edits: List of {find: str, replace: str, all: bool}
        sandbox_id: If provided, edit inside sandbox (via ephemeral_sandbox)
    
    Returns:
        Dict with success, edits_applied, path
    """
    try:
        if not edits:
            return {"success": False, "error": "No edits provided"}

        # Read file
        if sandbox_id:
            from ephemeral_sandbox import get_sandbox_manager
            mgr = get_sandbox_manager()
            result = mgr.read_file(sandbox_id, path)
            if not result.get("success"):
                return result
            content = result["content"]
        else:
            if not os.path.exists(path):
                return {"success": False, "error": f"File not found: {path}"}
            with open(path, "r", encoding="utf-8") as f:
                content = f.read()

        original = content
        applied = []

        # Apply edits sequentially
        for i, edit in enumerate(edits):
            find_text = edit.get("find", "")
            replace_text = edit.get("replace", "")
            replace_all = edit.get("all", False)

            if not find_text:
                return {
                    "success": False,
                    "error": f"Edit {i}: 'find' text is empty",
                    "edits_applied": 0,
                }

            if find_text not in content:
                return {
                    "success": False,
                    "error": f"Edit {i}: text not found: {find_text[:80]}...",
                    "edits_applied": 0,
                    "content_preview": content[:500],
                }

            if replace_all:
                count = content.count(find_text)
                content = content.replace(find_text, replace_text)
                applied.append({"edit": i, "replacements": count})
            else:
                content = content.replace(find_text, replace_text, 1)
                applied.append({"edit": i, "replacements": 1})

        # Write back
        if sandbox_id:
            result = mgr.write_file(sandbox_id, path, content)
            if not result.get("success"):
                return result
        else:
            os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                f.write(content)

        total_replacements = sum(e["replacements"] for e in applied)
        logger.info(f"[FILE_EDIT] {path}: {len(applied)} edits, {total_replacements} replacements")

        return {
            "success": True,
            "path": path,
            "edits_applied": len(applied),
            "total_replacements": total_replacements,
            "details": applied,
        }

    except Exception as e:
        logger.error(f"[FILE_EDIT] Error: {e}")
        return {"success": False, "error": str(e)}


def tool_file_read(path: str, start_line: int = None, end_line: int = None,
                   sandbox_id: str = None) -> Dict:
    """
    Read file with optional line range.
    
    Args:
        path: File path
        start_line: First line to read (1-indexed)
        end_line: Last line to read (-1 for end)
        sandbox_id: If provided, read from sandbox
    """
    try:
        if sandbox_id:
            from ephemeral_sandbox import get_sandbox_manager
            mgr = get_sandbox_manager()
            result = mgr.read_file(sandbox_id, path)
            if not result.get("success"):
                return result
            content = result["content"]
        else:
            if not os.path.exists(path):
                return {"success": False, "error": f"File not found: {path}"}
            with open(path, "r", encoding="utf-8") as f:
                content = f.read()

        lines = content.split("\n")
        total_lines = len(lines)

        if start_line or end_line:
            s = max(0, (start_line or 1) - 1)
            e = total_lines if (end_line is None or end_line == -1) else end_line
            selected = lines[s:e]
            # Add line numbers
            numbered = [f"{s + i + 1}: {line}" for i, line in enumerate(selected)]
            content = "\n".join(numbered)
        else:
            # If file is too long, truncate with hint
            if total_lines > 500:
                numbered = [f"{i + 1}: {line}" for i, line in enumerate(lines[:200])]
                content = "\n".join(numbered)
                content += f"\n\n... (truncated, {total_lines} lines total. Use start_line/end_line to read specific range)"

        return {
            "success": True,
            "path": path,
            "content": content,
            "total_lines": total_lines,
        }

    except Exception as e:
        return {"success": False, "error": str(e)}


def tool_file_write(path: str, content: str, sandbox_id: str = None) -> Dict:
    """Write full file content (overwrite)."""
    try:
        if sandbox_id:
            from ephemeral_sandbox import get_sandbox_manager
            mgr = get_sandbox_manager()
            return mgr.write_file(sandbox_id, path, content)
        else:
            os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                f.write(content)
            return {"success": True, "path": path, "size": len(content)}
    except Exception as e:
        return {"success": False, "error": str(e)}


def tool_file_append(path: str, content: str, sandbox_id: str = None) -> Dict:
    """Append content to a file."""
    try:
        if sandbox_id:
            from ephemeral_sandbox import get_sandbox_manager
            mgr = get_sandbox_manager()
            existing = mgr.read_file(sandbox_id, path)
            old = existing.get("content", "") if existing.get("success") else ""
            return mgr.write_file(sandbox_id, path, old + content)
        else:
            os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
            with open(path, "a", encoding="utf-8") as f:
                f.write(content)
            size = os.path.getsize(path)
            return {"success": True, "path": path, "size": size}
    except Exception as e:
        return {"success": False, "error": str(e)}


# ── Tool Schemas ──

SURGICAL_FILE_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "file_edit",
            "description": "Make targeted edits to a text file using find/replace. Multiple edits applied sequentially. All must succeed or none are applied. Use this for surgical code changes instead of rewriting entire files.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Absolute path to the file"
                    },
                    "edits": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "find": {"type": "string", "description": "Exact text to find"},
                                "replace": {"type": "string", "description": "Replacement text"},
                                "all": {"type": "boolean", "description": "Replace all occurrences (default: false)"}
                            },
                            "required": ["find", "replace"]
                        },
                        "description": "List of find/replace edits"
                    }
                },
                "required": ["path", "edits"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "file_read",
            "description": "Read a text file with optional line range. Returns content with line numbers.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Absolute file path"},
                    "start_line": {"type": "integer", "description": "First line to read (1-indexed)"},
                    "end_line": {"type": "integer", "description": "Last line to read (-1 for end of file)"}
                },
                "required": ["path"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "file_write",
            "description": "Write full content to a file (overwrites existing). Creates directories if needed.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Absolute file path"},
                    "content": {"type": "string", "description": "Full file content to write"}
                },
                "required": ["path", "content"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "file_append",
            "description": "Append content to the end of a file. Creates file if it doesn't exist.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Absolute file path"},
                    "content": {"type": "string", "description": "Content to append"}
                },
                "required": ["path", "content"]
            }
        }
    },
]
