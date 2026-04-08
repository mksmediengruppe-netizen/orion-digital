"""
ARCANE 2 — Tool Executor
==========================
Dispatcher: receives tool calls from AgentLoop, routes to actual implementations.
Connects file I/O, sandbox, SSH, browser, image generation.

Interface expected by agent_loop.py:
    executor.get_tools_schema() → list[dict]   (OpenAI function calling format)
    executor.execute(tool_name, arguments, project_id, user_id) → str

Spec refs: §4 (SSH tools), §5.3 (tool call batching), §12 (security)
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import time
from pathlib import Path
from typing import Any, Callable, Optional

from core.tool_registry import (
    ToolRegistry,
    FILE_WRITE_SCHEMA, FILE_CREATE_SCHEMA, FILE_READ_SCHEMA,
    FILE_EDIT_SCHEMA, FILE_LIST_SCHEMA,
    SHELL_EXEC_SCHEMA, MESSAGE_SCHEMA, PLAN_SCHEMA, SCRATCHPAD_SCHEMA,
    WEB_SEARCH_SCHEMA,
    SSH_EXEC_SCHEMA, SSH_READ_FILE_SCHEMA, SSH_WRITE_FILE_SCHEMA,
    SSH_LIST_DIR_SCHEMA, SSH_PATCH_FILE_SCHEMA, SSH_BACKUP_SCHEMA,
    SSH_BATCH_SCHEMA, SSH_TAIL_LOG_SCHEMA,
    IMAGE_GENERATE_SCHEMA,
    DEPLOY_TO_VPS_SCHEMA,
)

logger = logging.getLogger("arcane2.tool_executor")


class ToolExecutor:
    """
    Central tool dispatcher for AgentLoop.

    Usage:
        registry = ToolRegistry()
        executor = ToolExecutor(registry=registry, project_dir="/workspace/projects/my_project/src")
        
        # Core tools (files, shell, message) are registered automatically.
        # SSH/browser/image tools are registered conditionally:
        executor.register_ssh_tools(ssh_instance, server_config)
        executor.register_image_tools(image_generator)
        
        # AgentLoop uses:
        schema = executor.get_tools_schema(capabilities={"ssh"})
        result = await executor.execute("file_write", {"path": "index.html", "content": "..."})
    """

    def __init__(
        self,
        registry: ToolRegistry | None = None,
        project_dir: str = "/tmp/arcane_workspace",
        security_context=None,
    ):
        self._registry = registry or ToolRegistry()
        self._project_dir = project_dir
        self._capabilities: set[str] = set()
        self._security_context = security_context  #
        self._image_gen_call_count: int = 0   # persists across register_image_tools re-calls
        self._IMAGE_GEN_LIMIT: int = 8

        # Ensure project dir exists
        os.makedirs(self._project_dir, exist_ok=True)

        # Register core tools
        self._register_core_tools()

    # ═══════════════════════════════════════════════════════════════════════════
    # Public interface (used by agent_loop.py)
    # ═══════════════════════════════════════════════════════════════════════════

    def get_tools_schema(self, capabilities: set[str] | None = None) -> list[dict]:
        """Return tool schemas for LLM. Filters by active capabilities."""
        caps = capabilities or self._capabilities
        return self._registry.get_tools_schema(caps)

    async def execute(
        self,
        tool_name: str,
        arguments: dict[str, Any] | None = None,
        project_id: str = "",
        user_id: str = "",
    ) -> str:
        """
        Execute a tool by name. Returns result as string.
        This is the interface agent_loop.py calls.
        """
        # Parse string arguments (JSON)
        if isinstance(arguments, str):
            try:
                arguments = json.loads(arguments)
            except (json.JSONDecodeError, TypeError):
                logger.error(f"Cannot parse arguments string for {tool_name}: {str(arguments)[:200]}")
                arguments = {}
        arguments = arguments or {}
        # FIX: Claude sometimes wraps all args in a single "raw" key as JSON string
        if len(arguments) == 1 and "raw" in arguments and isinstance(arguments["raw"], str):
            try:
                parsed = json.loads(arguments["raw"])
                if isinstance(parsed, dict):
                    logger.info(f"Unwrapped raw arguments for {tool_name}: {list(parsed.keys())}")
                    arguments = parsed
            except (json.JSONDecodeError, TypeError):
                if tool_name in ("file_write", "file_create"):
                    logger.warning("file_write got raw content without path")
                    return (
                        "ERROR: file_write requires path and content as JSON. "
                        "Example: file_write(path=\"index.html\", content=\"<html>...\")" 
                        " For large files use append=True to write in 300-line chunks."
                    )
        handler = self._registry.get_handler(tool_name)

        if not handler:
            logger.warning(f"Unknown tool: {tool_name}")
            return f"Error: unknown tool '{tool_name}'. Available: {self._registry.list_tools()}"

        # ── Security: ApprovalGate for destructive actions (§12.1) ────────
        _GATED_TOOLS = {"shell_exec", "ssh_exec", "ssh_write_file", "ssh_patch_file", "ssh_batch"}
        if tool_name in _GATED_TOOLS:
            try:
                from core.security import ApprovalGate, ApprovalRequired as CoreApprovalRequired, AuditLog
                if hasattr(self, '_security_context') and self._security_context:
                    self._security_context.approval_gate.check(
                        action=tool_name,
                        model=getattr(self, '_model_id', 'unknown'),
                        project_id=project_id or ""
                    )
                else:
                    gate = ApprovalGate(audit_log=AuditLog())
                    gate.check(
                        action=tool_name,
                        model=getattr(self, '_model_id', 'unknown'),
                        project_id=project_id or ""
                    )
            except CoreApprovalRequired as e:
                logger.warning(f"Tool {tool_name} requires approval: {e}")
                return f"APPROVAL_REQUIRED: {e}"
            except Exception as e:
                logger.error(f"Security gate BLOCKED tool {tool_name}: {e}")
                return {"error": f"Action blocked by security: {e}"}  # fail-closed

        t0 = time.time()
        try:
            if asyncio.iscoroutinefunction(handler):
                result = await handler(**arguments)
            else:
                result = handler(**arguments)

            elapsed = time.time() - t0
            result_str = str(result) if result is not None else "OK"
            logger.info(f"Tool {tool_name}: OK ({elapsed:.1f}s, {len(result_str)} chars)")
            return result_str

        except Exception as e:
            elapsed = time.time() - t0
            logger.error(f"Tool {tool_name} failed ({elapsed:.1f}s): {e}")
            return f"Error in {tool_name}: {type(e).__name__}: {str(e)[:500]}"

    # ═══════════════════════════════════════════════════════════════════════════
    # Core tool registration
    # ═══════════════════════════════════════════════════════════════════════════

    def _register_core_tools(self):
        """Register built-in tools (always available)."""
        r = self._registry

        # Files
        r.register("file_write", self._file_write, FILE_WRITE_SCHEMA)
        r.register("file_read", self._file_read, FILE_READ_SCHEMA)
        r.register("file_edit", self._file_edit, FILE_EDIT_SCHEMA)
        r.register("file_list", self._file_list, FILE_LIST_SCHEMA)

        # Shell
        r.register("shell_exec", self._shell_exec, SHELL_EXEC_SCHEMA)

        # Communication
        r.register("message", self._message, MESSAGE_SCHEMA)
        r.register("plan", self._plan, PLAN_SCHEMA)
        r.register("update_scratchpad", self._update_scratchpad, SCRATCHPAD_SCHEMA)

        # Web search
        r.register("web_search", self._web_search, WEB_SEARCH_SCHEMA)

        # Collective Mind — multi-round debate between models
        COLLECTIVE_MIND_SCHEMA = {
            "type": "function",
            "function": {
                "name": "collective_mind_deliberate",
                "description": (
                    "Run a multi-round debate between 2-5 AI models. "
                    "Models answer independently, critique each other, revise positions, "
                    "then a judge synthesizes the final answer. "
                    "Use for complex questions, research, architecture decisions, code review."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "prompt": {
                            "type": "string",
                            "description": "The question or task to deliberate on",
                        },
                        "models": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "2-5 model IDs (e.g. ['gpt-5.4-nano','gemini-2.5-flash','deepseek-v3.2']). Leave empty for defaults.",
                        },
                        "rounds": {
                            "type": "integer",
                            "description": "Number of critique+revision rounds (1-3, default 2)",
                        },
                    },
                    "required": ["prompt"],
                },
            },
        }
        r.register("collective_mind_deliberate", self._collective_mind, COLLECTIVE_MIND_SCHEMA)
        r.register("deploy_to_vps", self._deploy_to_vps, DEPLOY_TO_VPS_SCHEMA)

        LINT_CODE_SCHEMA = {
            "type": "function",
            "function": {
                "name": "lint_code",
                "description": (
                    "Lint and validate a source file. "
                    "Supports .py (flake8), .js (node --check), .html (structure check), .css. "
                    "USE THIS after writing code to catch errors before delivery. "
                    "Returns 'PASS' or list of specific issues to fix."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "Relative path to file"},
                        "fix": {"type": "boolean", "description": "Attempt auto-fix (Python only)", "default": False},
                    },
                    "required": ["path"],
                },
            },
        }
        VALIDATE_HTML_SCHEMA = {
            "type": "function",
            "function": {
                "name": "validate_html",
                "description": (
                    "Deep validate HTML file: DOCTYPE, charset, viewport, alt tags, "
                    "placeholder text, responsive design. "
                    "USE THIS before delivering web_design tasks."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "Path to HTML file"},
                    },
                    "required": ["path"],
                },
            },
        }
        RUN_TESTS_SCHEMA = {
            "type": "function",
            "function": {
                "name": "run_tests",
                "description": "Run pytest or unittest tests. Use after writing Python code to verify it works.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "Path to test file or directory", "default": "."},
                        "pattern": {"type": "string", "description": "Test file pattern", "default": "test_*.py"},
                    },
                    "required": [],
                },
            },
        }
        r.register("lint_code", self._lint_code, LINT_CODE_SCHEMA)

        HTTP_REQUEST_SCHEMA = {
            "type": "function",
            "function": {
                "name": "http_request",
                "description": (
                    "Make an HTTP request to any URL. "
                    "Use to: check if deployed site is up (GET health check), "
                    "test API endpoints, verify HTTP status codes after deployment."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "url": {"type": "string", "description": "Full URL including http/https"},
                        "method": {"type": "string", "enum": ["GET","POST","PUT","DELETE","HEAD"], "default": "GET"},
                        "headers": {"type": "object", "description": "Request headers", "default": {}},
                        "body": {"type": "string", "description": "Request body (for POST/PUT)"},
                        "timeout": {"type": "integer", "description": "Timeout in seconds", "default": 15},
                    },
                    "required": ["url"],
                },
            },
        }
        r.register("http_request", self._http_request, HTTP_REQUEST_SCHEMA)

        r.register("validate_html", self._validate_html, VALIDATE_HTML_SCHEMA)
        r.register("run_tests", self._run_tests, RUN_TESTS_SCHEMA)


        logger.info(f"Core tools registered: {len(r)} tools")


    # ═══════════════════════════════════════════════════════════════
    # Quality tools — lint, validate, test
    # ═══════════════════════════════════════════════════════════════


    async def _http_request(
        self, url: str, method: str = "GET",
        headers: dict = None, body: str = None, timeout: int = 15
    ) -> str:
        """Make HTTP request to external URL. Use for testing APIs, checking deployments."""
        import httpx
        try:
            async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
                kwargs = {"headers": headers or {}}
                if body:
                    kwargs["content"] = body.encode() if isinstance(body, str) else body
                resp = await getattr(client, method.lower())(url, **kwargs)
                ct = resp.headers.get("content-type", "")
                body_text = resp.text[:3000]
                return (
                    f"Status: {resp.status_code}\n"
                    f"Content-Type: {ct}\n"
                    f"Body: {body_text}"
                )
        except httpx.TimeoutException:
            return f"Error: request to {url} timed out after {timeout}s"
        except Exception as e:
            return f"Error: {e}"

    async def _lint_code(self, path: str, fix: bool = False) -> str:
        """
        Lint source file and return issues.
        Supports: .py (flake8 + pyflakes), .js/.ts (node --check),
                  .html (basic validation), .css (basic checks).
        """
        full = self._safe_path(path)
        if not os.path.exists(full):
            return f"Error: file not found: {path}"

        ext = os.path.splitext(path)[1].lower()
        results = []

        if ext == ".py":
            # Check syntax first
            proc = await asyncio.create_subprocess_exec(
                "python3", "-m", "py_compile", full,
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            )
            _, stderr = await asyncio.wait_for(proc.communicate(), timeout=15)
            if proc.returncode != 0:
                return f"SYNTAX ERROR in {path}:\n{stderr.decode()[:500]}"

            # flake8 if available
            proc2 = await asyncio.create_subprocess_exec(
                "python3", "-m", "flake8", "--max-line-length=120",
                "--ignore=E501,W503,E302,E305", full,
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
                cwd=self._project_dir,
            )
            stdout2, _ = await asyncio.wait_for(proc2.communicate(), timeout=15)
            out = stdout2.decode().strip()
            if out:
                # Shorten paths
                out = out.replace(str(full), path)
                issues = out.split("\n")[:20]
                results.append(f"flake8 issues ({len(issues)}):\n" + "\n".join(issues))
            else:
                results.append(f"✅ {path}: no Python issues")

        elif ext in (".js", ".mjs", ".cjs"):
            proc = await asyncio.create_subprocess_exec(
                "node", "--check", full,
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            )
            _, stderr = await asyncio.wait_for(proc.communicate(), timeout=15)
            err = stderr.decode().strip()
            if err:
                results.append(f"JS syntax error in {path}:\n{err[:400]}")
            else:
                results.append(f"✅ {path}: JS syntax OK")

        elif ext == ".ts":
            # TypeScript check via npx tsc if available
            proc = await asyncio.create_subprocess_shell(
                f"npx --yes tsc --noEmit --allowJs {full} 2>&1 || node --check {full}",
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
                cwd=self._project_dir,
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=30)
            out = stdout.decode().strip()
            if out and "error" in out.lower():
                results.append(f"TS issues in {path}:\n{out[:400]}")
            else:
                results.append(f"✅ {path}: TypeScript OK")

        elif ext in (".html", ".htm"):
            with open(full, "r", encoding="utf-8", errors="replace") as f:
                html = f.read()
            issues = []
            if "<!DOCTYPE html>" not in html and "<!doctype html>" not in html.lower():
                issues.append("Missing <!DOCTYPE html>")
            if 'charset' not in html.lower():
                issues.append("Missing charset meta tag")
            if 'viewport' not in html.lower():
                issues.append("Missing viewport meta tag")
            if '<title>' not in html.lower():
                issues.append("Missing <title> tag")
            # Check for placeholder content
            # Check placeholder CONTENT — not HTML attribute placeholder=""
            _ph_texts = ["Lorem ipsum", "dolor sit amet", "Placeholder text",
                         "Sample text", "Coming soon", "Your text here"]
            for bad in _ph_texts:
                if bad.lower() in html.lower():
                    issues.append(f"Found placeholder text: '{bad}'")
            if "<!-- TODO" in html or "// TODO" in html:
                issues.append("Found TODO comment in code")
            # Check for empty href
            import re
            broken = re.findall(r'href=(#|javascript:void\(0\)|javascript:;)', html, re.I)
            if broken:
                issues.append(f"Found {len(broken)} empty/broken links")

            if issues:
                results.append(f"HTML issues in {path}:\n" + "\n".join(f"  - {i}" for i in issues))
            else:
                results.append(f"✅ {path}: HTML validation passed")

        elif ext == ".css":
            with open(full, "r", encoding="utf-8", errors="replace") as f:
                css = f.read()
            issues = []
            if "!important" in css:
                count = css.count("!important")
                if count > 3:
                    issues.append(f"Overuse of !important ({count} times)")
            if "@media" not in css:
                issues.append("No @media queries found (not responsive?)")
            if issues:
                results.append(f"CSS suggestions for {path}:\n" + "\n".join(f"  - {i}" for i in issues))
            else:
                results.append(f"✅ {path}: CSS looks good")

        else:
            results.append(f"No linter for {ext} files (supported: .py .js .ts .html .css)")

        return "\n".join(results) if results else f"✅ {path}: no issues found"

    async def _validate_html(self, path: str) -> str:
        """
        Validate HTML file structure and content quality.
        Returns detailed report with specific line numbers where possible.
        """
        full = self._safe_path(path)
        if not os.path.exists(full):
            return f"Error: file not found: {path}"
        with open(full, "r", encoding="utf-8", errors="replace") as f:
            html = f.read()

        import re
        issues = []
        warnings = []
        passed = []

        # Critical checks
        if "<!DOCTYPE html>" not in html and "<!doctype html>" not in html.lower():
            issues.append("❌ Missing <!DOCTYPE html>")
        else:
            passed.append("✅ DOCTYPE present")

        if 'charset="utf-8"' not in html.lower() and "charset=utf-8" not in html.lower():
            issues.append("❌ Missing charset=utf-8 meta tag")
        else:
            passed.append("✅ charset UTF-8")

        if 'name="viewport"' not in html.lower():
            issues.append("❌ Missing viewport meta tag (not mobile-friendly)")
        else:
            passed.append("✅ viewport meta tag")

        if "<title>" not in html.lower() or "<title></title>" in html.lower():
            issues.append("❌ Missing or empty <title>")
        else:
            passed.append("✅ title tag")

        # Images without alt
        imgs_without_alt = len(re.findall(r'<img(?![^>]*\balt=)[^>]*>', html, re.I))
        if imgs_without_alt:
            issues.append(f"❌ {imgs_without_alt} image(s) missing alt attribute")
        else:
            passed.append("✅ All images have alt")

        # Placeholder content
        placeholders = []
        for bad in ["Lorem ipsum", "Coming soon", "TODO", "FIXME", "Sample text"]:
            if bad.lower() in html.lower():
                placeholders.append(bad)
        if placeholders:
            issues.append(f"❌ Placeholder text found: {', '.join(placeholders)}")
        else:
            passed.append("✅ No placeholder text")

        # Responsive check
        if "@media" not in html.lower() and "responsive" not in html.lower():
            warnings.append("⚠️ No CSS media queries found — may not be responsive")
        else:
            passed.append("✅ Media queries present")

        # External resources (basic check)
        ext_resources = re.findall(r'src="https?://[^"]{4,}"', html)
        if len(ext_resources) > 10:
            warnings.append(f"⚠️ {len(ext_resources)} external resources (may be slow)")

        # Build summary
        lines = []
        if issues:
            lines.append(f"ERRORS ({len(issues)}):")
            lines.extend(f"  {i}" for i in issues)
        if warnings:
            lines.append(f"\nWARNINGS ({len(warnings)}):")
            lines.extend(f"  {w}" for w in warnings)
        if passed:
            lines.append(f"\nPASSED ({len(passed)}):")
            lines.extend(f"  {p}" for p in passed[:5])

        overall = "PASS" if not issues else "FAIL"
        lines.insert(0, f"HTML Validation: {overall} | {len(issues)} errors, {len(warnings)} warnings")
        return "\n".join(lines)

    async def _run_tests(self, path: str = ".", pattern: str = "test_*.py") -> str:
        """
        Run tests in project directory.
        Supports pytest (Python) and basic JS test runners.
        """
        target = self._safe_path(path)
        ext = os.path.splitext(path)[1].lower()

        if ext in (".py", "") :
            # Try pytest first
            proc = await asyncio.create_subprocess_exec(
                "python3", "-m", "pytest", target, "-v", "--tb=short", "-q",
                "--timeout=30",
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
                cwd=self._project_dir,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=60)
            out = stdout.decode() + stderr.decode()
            if "no module named pytest" in out.lower():
                # Fallback to unittest
                proc2 = await asyncio.create_subprocess_exec(
                    "python3", "-m", "unittest", "discover", "-s", target, "-v",
                    stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
                    cwd=self._project_dir,
                )
                stdout2, stderr2 = await asyncio.wait_for(proc2.communicate(), timeout=60)
                out = stdout2.decode() + stderr2.decode()
            return out[:3000] if out else f"No tests found in {path}"

        elif ext == ".js":
            proc = await asyncio.create_subprocess_shell(
                f"node {target} 2>&1",
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
                cwd=self._project_dir,
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=30)
            return stdout.decode()[:2000]

        return f"No test runner configured for {ext} files"



    # ═══════════════════════════════════════════════════════════════════════════
    # Conditional registration (SSH, browser, image gen)
    # ═══════════════════════════════════════════════════════════════════════════


    async def _deploy_to_vps(self, project_id: str, deploy_path: str = "/var/www/html") -> str:
        """Deploy project files to VPS via SSH. (Stage E)"""
        import os
        from pathlib import Path
        
        workspace = os.environ.get("ARCANE_WORKSPACE", "/root/workspace")
        src_dir = Path(workspace) / "projects" / project_id / "src"
        
        if not src_dir.exists():
            return f"Error: project src directory not found: {src_dir}"
        
        files = [f for f in src_dir.rglob("*") if f.is_file()]
        if not files:
            return "Error: no files to deploy"
        
        if "ssh" not in self._capabilities:
            return "Error: SSH tools not registered. Add server config to project settings first."
        
        deployed = []
        errors = []
        
        # Get SSH tools from registry
        ssh_write = self._registry.get("ssh_write_file")
        ssh_exec_fn = self._registry.get("ssh_exec")
        
        if not ssh_write or not ssh_exec_fn:
            return "Error: SSH tools not available in registry"
        
        for f in files:
            rel = f.relative_to(src_dir)
            remote_path = f"{deploy_path}/{rel}"
            try:
                content = f.read_text(encoding="utf-8", errors="replace")
                result = await ssh_write(path=remote_path, content=content)
                if "Error" not in str(result):
                    deployed.append(str(rel))
                else:
                    errors.append(f"{rel}: {result}")
            except Exception as e:
                errors.append(f"{rel}: {e}")
        
        # Reload nginx
        nginx_result = "skipped"
        try:
            nginx_result = await ssh_exec_fn(command="nginx -t && systemctl reload nginx 2>&1 || echo 'nginx not available'")
        except Exception as e:
            nginx_result = f"nginx reload failed: {e}"
        
        # Health check
        health = "unknown"
        try:
            health = await ssh_exec_fn(command="curl -s -o /dev/null -w '%{http_code}' http://localhost 2>/dev/null || echo 'no-http'")
        except Exception:
            pass
        
        summary = f"Deployed {len(deployed)}/{len(files)} files to {deploy_path}. Health: {health}."
        if errors:
            summary += f" Errors ({len(errors)}): {'; '.join(errors[:3])}"
        
        return summary

    def register_ssh_tools(self, ssh_tools_instance, server_config=None):
        """Register SSH tools. Call when task needs_ssh=True."""
        r = self._registry
        ssh = ssh_tools_instance
        cfg = server_config

        # Wrap SSH methods to inject server_config
        async def _ssh_exec(command: str) -> str:
            result = await ssh.ssh_exec(cfg, command)
            return result.data if result.ok else f"Error: {result.error}"

        async def _ssh_read_file(path: str) -> str:
            result = await ssh.ssh_read_file(cfg, path)
            return result.data if result.ok else f"Error: {result.error}"

        async def _ssh_write_file(path: str, content: str) -> str:
            result = await ssh.ssh_write_file(cfg, path, content)
            return result.data if result.ok else f"Error: {result.error}"

        async def _ssh_list_dir(path: str) -> str:
            result = await ssh.ssh_list_dir(cfg, path)
            return result.data if result.ok else f"Error: {result.error}"

        async def _ssh_patch_file(path: str, line_from: int, line_to: int, new_content: str) -> str:
            result = await ssh.ssh_patch_file(cfg, path, line_from, line_to, new_content)
            return result.data if result.ok else f"Error: {result.error}"

        async def _ssh_backup(path: str) -> str:
            result = await ssh.ssh_backup(cfg, path)
            return result.data if result.ok else f"Error: {result.error}"

        async def _ssh_batch(commands: list) -> str:
            result = await ssh.ssh_batch(cfg, commands)
            return str(result)

        async def _ssh_tail_log(path: str, lines: int = 50) -> str:
            result = await ssh.ssh_tail_log(cfg, path, lines)
            return result.data if result.ok else f"Error: {result.error}"

        r.register("ssh_exec", _ssh_exec, SSH_EXEC_SCHEMA, requires="ssh")
        r.register("ssh_read_file", _ssh_read_file, SSH_READ_FILE_SCHEMA, requires="ssh")
        r.register("ssh_write_file", _ssh_write_file, SSH_WRITE_FILE_SCHEMA, requires="ssh")
        r.register("ssh_list_dir", _ssh_list_dir, SSH_LIST_DIR_SCHEMA, requires="ssh")
        r.register("ssh_patch_file", _ssh_patch_file, SSH_PATCH_FILE_SCHEMA, requires="ssh")
        r.register("ssh_backup", _ssh_backup, SSH_BACKUP_SCHEMA, requires="ssh")
        r.register("ssh_batch", _ssh_batch, SSH_BATCH_SCHEMA, requires="ssh")
        r.register("ssh_tail_log", _ssh_tail_log, SSH_TAIL_LOG_SCHEMA, requires="ssh")

        self._capabilities.add("ssh")
        logger.info(f"SSH tools registered ({len(r)} total tools)")

    def register_image_tools(self, image_generator):
        """Register image generation tools."""
        async def _image_generate(prompt: str, style: str = "photo",
                                   size: str = "1024x1024", filename: str = "") -> str:
            # ═══ ARCANE v14.1: IMAGE CACHE ═══
            # Skip Flux call if we already generated this image (saves $0.05 per cached call).
            # Cache survives crashes, OpenRouter 402, server restarts, retries.
            # Cache key = sha256(prompt + filename + size) — same prompt → same cache hit.
            import hashlib as _hl, json as _cjs, os as _cios
            _cache_key = _hl.sha256(f"{prompt}|{filename}|{size}".encode("utf-8")).hexdigest()[:16]
            _cache_dir = _cios.path.join(self._project_dir, ".arcane")
            _cache_file = _cios.path.join(_cache_dir, "images_cache.json")
            _cache = {}
            try:
                if _cios.path.exists(_cache_file):
                    with open(_cache_file, encoding="utf-8") as _cf:
                        _cache = _cjs.load(_cf)
            except Exception as _ce:
                logger.debug(f"image cache read failed: {_ce}")
            
            # Cache HIT — return cached result without calling Flux
            if _cache_key in _cache:
                _cached = _cache[_cache_key]
                _cached_path = _cached.get("absolute_path", "")
                _rel_path = _cached.get("relative_path", "")
                # Verify file still exists on disk
                _full_rel = _cios.path.join(self._project_dir, _rel_path) if _rel_path else ""
                if _full_rel and _cios.path.exists(_full_rel):
                    logger.info(f"image_generate CACHE HIT: {_rel_path} (saved ~$0.055)")
                    return _cjs.dumps({
                        "success": True,
                        "path": _rel_path,
                        "relative_path": _rel_path,
                        "html": f'<img src="{_rel_path}" alt="" loading="lazy">',
                        "cached": True,
                    })
                else:
                    logger.debug(f"image cache entry exists but file missing: {_full_rel}")
            
            # ═══ Original logic — call Flux ═══
            self._image_gen_call_count += 1
            if self._image_gen_call_count > self._IMAGE_GEN_LIMIT:
                logger.warning(f"image_generate LIMIT {self._image_gen_call_count}/{self._IMAGE_GEN_LIMIT}")
                return json.dumps({"error": f"Limit reached ({self._IMAGE_GEN_LIMIT} images per run). "
                                            "Write HTML now using images already in src/images/."})
            result = await image_generator.generate(
                prompt=prompt,
                style=style,
                size=size,
            )
            # FIX v12: extract path from image_gen response structure
            # image_gen ALWAYS returns {"images": [{"path": "..."}], "success": true}
            # NEVER {"path": "..."} at root — checking root = always None = infinite loop
            if isinstance(result, dict) and not result.get("path"):
                _imgs = result.get("images", [])
                if _imgs and isinstance(_imgs[0], dict) and _imgs[0].get("path"):
                    result = {**result, "path": _imgs[0]["path"]}
                    logger.info(f"image_generate: path from images[0]: {result['path']}")
            if isinstance(result, dict) and result.get("path"):
                import shutil as _sh, os as _ios
                abs_path = result["path"]
                if _ios.path.exists(abs_path):
                    # Determine target filename — force .webp for smaller size (ARCANE v13)
                    _fname = filename.strip() if filename.strip() else _ios.path.basename(abs_path)
                    # Strip any existing extension and use .webp
                    _base = _ios.path.splitext(_fname)[0] or "image"
                    _fname = _base + ".webp"
                    
                    # Copy to project src/images/
                    _images_dir = _ios.path.join(self._project_dir, "images")
                    _ios.makedirs(_images_dir, exist_ok=True)
                    _dest = _ios.path.join(_images_dir, _fname)
                    
                    # ARCANE v13 FIX 6: Compress with Pillow — convert to webp, resize, 85% quality
                    # Flux generates 1.5+ MB PNG files; web needs 100-400 KB
                    _compressed = False
                    try:
                        from PIL import Image as _PILImage
                        _img = _PILImage.open(abs_path)
                        # Resize if wider than 1600px (keeps aspect ratio)
                        _w, _h = _img.size
                        if _w > 1600:
                            _ratio = 1600 / _w
                            _new_size = (1600, int(_h * _ratio))
                            _img = _img.resize(_new_size, _PILImage.Resampling.LANCZOS)
                            logger.info(f"Resized image {_w}x{_h} → {_new_size[0]}x{_new_size[1]}")
                        # Convert to RGB if needed (webp doesn't support some modes)
                        if _img.mode in ("RGBA", "P"):
                            _img = _img.convert("RGB")
                        # Save as webp with quality 85
                        _img.save(_dest, "WEBP", quality=85, method=6)
                        _compressed = True
                        _orig_size = _ios.path.getsize(abs_path)
                        _new_size_b = _ios.path.getsize(_dest)
                        logger.info(
                            f"Compressed image: {_orig_size//1024} KB → {_new_size_b//1024} KB "
                            f"({100*_new_size_b//_orig_size if _orig_size else 0}%)"
                        )
                    except ImportError:
                        logger.debug("Pillow not available, using raw copy")
                    except Exception as _pe:
                        logger.warning(f"Image compression failed: {_pe}, using raw copy")
                    
                    # Fallback to raw copy if compression failed
                    if not _compressed:
                        _sh.copy2(abs_path, _dest)
                    
                    rel_path = f"images/{_fname}"
                    logger.info(f"Image saved to {rel_path}")
                    
                    # ═══ ARCANE v14.1: SAVE TO CACHE ═══
                    # After successful generation, save to cache so retry doesn't pay again
                    try:
                        _cios.makedirs(_cache_dir, exist_ok=True)
                        _cache[_cache_key] = {
                            "prompt": prompt[:200],  # truncate for storage
                            "filename": filename,
                            "size": size,
                            "relative_path": rel_path,
                            "absolute_path": _dest,
                        }
                        with open(_cache_file, "w", encoding="utf-8") as _cwf:
                            _cjs.dump(_cache, _cwf, ensure_ascii=False, indent=2)
                        logger.debug(f"image cache saved: {_cache_key} → {rel_path}")
                    except Exception as _cse:
                        logger.warning(f"image cache write failed: {_cse}")
                    
                    # Return relative path for use in HTML src=
                    return json.dumps({**result, "path": rel_path, "relative_path": rel_path,
                                       "html": f'<img src="{rel_path}" alt="" loading="lazy">'})
            if isinstance(result, dict):
                return json.dumps(result)
            return str(result)

        self._registry.register("image_generate", _image_generate, IMAGE_GENERATE_SCHEMA, requires="image")
        self._capabilities.add("image")
        logger.info(f"Image generation tools registered")

    # ═══════════════════════════════════════════════════════════════════════════
    # Core tool implementations
    # ═══════════════════════════════════════════════════════════════════════════

    # ── Files ─────────────────────────────────────────────────────────────────

    async def _file_write(self, path: str, content: str = "", raw: bool = False, append: bool = False, **kwargs) -> str:
        """Write file to project workspace.
        raw: ignored (accepted for Claude compatibility — Claude sometimes passes raw=True)
        """
        if not content and not kwargs.get("_allow_empty"):
            return f"Error: file_write called without content for {path}. The file content was truncated by the model. Please write the file in sections: first write the HTML head and hero section, then append the remaining sections using separate file_write calls with append=True. Or use a shorter, more concise HTML structure."
        full = self._safe_path(path)
        
        # ARCANE v14.2 FIX 3: Anti-overwrite protection for large files
        # If file exists, is large (>2KB), and Developer writes without append=True —
        # this means he's trying to rewrite from scratch, losing all previous work.
        # Return warning instead of silently overwriting.
        if not append and os.path.exists(full):
            try:
                _existing_size = os.path.getsize(full)
                if _existing_size > 2000:  # 2KB threshold — small files OK to overwrite
                    logger.warning(
                        f"Anti-overwrite: {path} has {_existing_size} bytes, "
                        f"refusing to overwrite without append=True"
                    )
                    return (
                        f"⚠️ REFUSED: {path} already has {_existing_size} bytes of content. "
                        f"You're about to OVERWRITE existing work and start over. "
                        f"This is almost certainly wrong.\n\n"
                        f"FIX: Add `append=True` to continue writing the next section:\n"
                        f"  file_write(path=\"{path}\", content=\"<your new section>\", append=True)\n\n"
                        f"If you REALLY need to rewrite from scratch (rare), use file_edit instead, "
                        f"or delete the file first with shell_exec(command=\"rm {path}\")."
                    )
            except Exception as _ae:
                logger.debug(f"Anti-overwrite check failed: {_ae}")
        
        def _write():
            os.makedirs(os.path.dirname(full), exist_ok=True)
            mode = "a" if append else "w"
            with open(full, mode, encoding="utf-8") as f:
                f.write(content)
        await asyncio.to_thread(_write)
        action = "Appended" if append else "Written"
        return f"{action} {len(content)} chars to {path}"

    async def _file_read(self, path: str) -> str:
        """Read file from project workspace."""
        full = self._safe_path(path)
        if not os.path.exists(full):
            return f"Error: file not found: {path}"
        def _read():
            with open(full, "r", encoding="utf-8", errors="replace") as f:
                return f.read()
        content = await asyncio.to_thread(_read)
        if len(content) > 50000:
            return content[:50000] + f"\n... (truncated, total {len(content)} chars)"
        return content

    async def _file_edit(self, path: str, old_str: str, new_str: str) -> str:
        """Edit file by replacing exact string."""
        full = self._safe_path(path)
        if not os.path.exists(full):
            return f"Error: file not found: {path}"
        def _edit():
            with open(full, "r", encoding="utf-8") as f:
                content = f.read()
            count = content.count(old_str)
            if count == 0:
                return f"Error: string not found in {path}. First 200 chars of file:\n{content[:200]}"
            if count > 1:
                return f"Error: string found {count} times in {path}. Must be unique."
            new_content = content.replace(old_str, new_str, 1)
            with open(full, "w", encoding="utf-8") as f:  # always overwrite (edit replaces content)
                f.write(new_content)
            return f"Edited {path}: replaced {len(old_str)} chars with {len(new_str)} chars"
        return await asyncio.to_thread(_edit)

    async def _file_list(self, path: str = ".") -> str:
        """List files in directory."""
        full = self._safe_path(path)
        if not os.path.isdir(full):
            return f"Error: not a directory: {path}"
        def _list():
            entries = []
            for item in sorted(os.listdir(full)):
                item_path = os.path.join(full, item)
                if os.path.isdir(item_path):
                    entries.append(f"  {item}/")
                else:
                    size = os.path.getsize(item_path)
                    entries.append(f"  {item} ({size} bytes)")
            return f"Directory: {path}\n" + "\n".join(entries) if entries else f"Empty directory: {path}"
        return await asyncio.to_thread(_list)

    # ── Shell ─────────────────────────────────────────────────────────────────

    # ── ARCANE 3.0: Blocked shell commands (SSH = Manus only) ────────────────
    _BLOCKED_COMMANDS = re.compile(
        r"\b(ssh|scp|rsync|sftp)\s",
        re.IGNORECASE,
    )

    async def _shell_exec(self, command: str) -> str:
        """Execute shell command in sandbox.
        
        ARCANE 3.0 SECURITY: ssh, scp, rsync, sftp are blocked.
        Server access is exclusively through Manus.
        """
        # ── Security gate: block SSH commands ─────────────────────────
        if self._BLOCKED_COMMANDS.search(command):
            blocked_cmd = self._BLOCKED_COMMANDS.search(command).group(1)
            logger.warning(f"BLOCKED: shell_exec attempted '{blocked_cmd}' command. SSH access is Manus-only.")
            return (
                f"ERROR: Command '{blocked_cmd}' is blocked. "
                f"Server access (SSH, SCP, rsync) is exclusively handled by Manus. "
                f"Developer writes code locally. Manus deploys."
            )
        try:
            from core.sandbox import execute
            result = await execute(command, working_dir=self._project_dir, timeout=60)
            output = result.get("output", "")
            error = result.get("error", "")
            exit_code = result.get("exit_code", result.get("returncode", -1))
            parts = []
            if output:
                parts.append(output[:10000])
            if error:
                parts.append(f"STDERR: {error[:5000]}")
            parts.append(f"Exit code: {exit_code}")
            return "\n".join(parts)
        except ImportError:
            # Fallback: direct subprocess (less secure, but works without sandbox)
            proc = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=self._project_dir,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=60)
            parts = []
            if stdout:
                parts.append(stdout.decode(errors="replace")[:10000])
            if stderr:
                parts.append(f"STDERR: {stderr.decode(errors='replace')[:5000]}")
            parts.append(f"Exit code: {proc.returncode}")
            return "\n".join(parts)

    # ── Communication ─────────────────────────────────────────────────────────

    def _message(self, type: str = "info", content: str = "", **kwargs) -> str:
        """Send message. agent_loop handles 'result' type specially."""
        return content

    def _plan(self, steps: list | None = None, **kwargs) -> str:
        """Create execution plan."""
        steps = steps or []
        plan_text = "\n".join(f"{i+1}. {s}" for i, s in enumerate(steps))
        # Save to scratchpad
        plan_path = os.path.join(self._project_dir, ".arcane", "plan.md")
        os.makedirs(os.path.dirname(plan_path), exist_ok=True)
        with open(plan_path, "w") as f:
            f.write(f"# Plan\n\n{plan_text}\n")
        return f"Plan created ({len(steps)} steps):\n{plan_text}"

    async def _update_scratchpad(self, content: str) -> str:
        """Update working scratchpad."""
        path = os.path.join(self._project_dir, ".arcane", "scratchpad.md")
        def _write():
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                f.write(content)
        await asyncio.to_thread(_write)
        return f"Scratchpad updated ({len(content)} chars)"

    # ── Web search ────────────────────────────────────────────────────────────

    async def _web_search(self, query: str) -> str:
        """Search the web via Tavily API."""
        api_key = os.environ.get("TAVILY_API_KEY", "")
        if not api_key:
            return "Web search unavailable: TAVILY_API_KEY not set"
        try:
            import httpx
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.post(
                    "https://api.tavily.com/search",
                    json={"query": query, "api_key": api_key, "max_results": 5},
                )
                data = resp.json()
                results = data.get("results", [])
                if not results:
                    return f"No results for: {query}"
                parts = []
                for r in results[:5]:
                    parts.append(f"**{r.get('title', '')}**\n{r.get('url', '')}\n{r.get('content', '')[:300]}\n")
                return "\n---\n".join(parts)
        except Exception as e:
            return f"Web search failed: {e}"

    # ── Collective Mind ───────────────────────────────────────────────────

    async def _collective_mind(
        self,
        prompt: str,
        models: list[str] | None = None,
        rounds: int = 2,
    ) -> str:
        """Multi-round debate between models. Returns structured result."""
        api_key = os.environ.get("OPENROUTER_API_KEY", "")
        if not api_key:
            return "Collective Mind unavailable: OPENROUTER_API_KEY not set"

        try:
            from core.collective_reasoning import deliberate, DeliberationConfig
            from shared.llm.llm_client import MODEL_MAP

            # Default models if not specified
            if not models or len(models) < 2:
                models = ["gpt-5.4-nano", "gemini-2.5-flash", "deepseek-v3.2"]

            # Convert internal IDs → OpenRouter IDs
            or_models = tuple(MODEL_MAP.get(m, m) for m in models)
            rounds = max(1, min(3, rounds))

            config = DeliberationConfig(
                models=or_models,
                judge="google/gemini-2.5-flash",
                rounds=rounds,
            )

            report = await deliberate(prompt=prompt, config=config, api_key=api_key)

            # Format result for agent
            result_parts = [
                f"## Collective Mind Result ({len(or_models)} models, {rounds} rounds)",
                f"**Confidence:** {report.confidence:.0%}",
                f"**Cost:** ${report.total_cost_usd:.4f} | **Time:** {report.total_latency_s:.1f}s",
                "",
                f"### Final Answer\n{report.final_answer}",
                "",
                f"### Consensus\n{report.consensus}",
            ]

            if report.disagreements:
                result_parts.append("\n### Disagreements")
                for d in report.disagreements:
                    result_parts.append(f"- {d}")

            if report.contributions:
                result_parts.append("\n### Unique Contributions")
                for c in report.contributions:
                    result_parts.append(f"- {c}")

            return "\n".join(result_parts)

        except Exception as e:
            return f"Collective Mind failed: {type(e).__name__}: {str(e)[:500]}"

    # ═══════════════════════════════════════════════════════════════════════════
    # Helpers
    # ═══════════════════════════════════════════════════════════════════════════

    def _safe_path(self, path: str) -> str:
        """Resolve path safely within project directory. Prevent traversal."""
        clean = os.path.normpath(path).lstrip("/").lstrip("\\")
        if ".." in clean.split(os.sep):
            raise ValueError(f"Path traversal detected: {path}")
        resolved = os.path.realpath(os.path.join(self._project_dir, clean))
        if not resolved.startswith(os.path.realpath(self._project_dir)):
            raise ValueError(f"Path escapes project directory: {path}")
        return resolved
