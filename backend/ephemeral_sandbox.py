"""
ORION Ephemeral Sandbox Manager
================================
Creates isolated, ephemeral Docker containers for each task.
Each sandbox has its own filesystem, network namespace, and resource limits.
Containers are auto-destroyed after task completion or timeout.

Architecture mirrors Manus AI's sandbox approach:
- Per-task isolation (no cross-contamination)
- Pre-installed Python, Node.js, common tools
- Resource limits (CPU, memory, disk)
- Auto-cleanup with configurable TTL
- File transfer in/out of sandbox
"""

import docker
import logging
import os
import time
import threading
import uuid
import tarfile
import io
from typing import Dict, Optional, List, Any
from collections import OrderedDict

logger = logging.getLogger("ephemeral_sandbox")

# ── Configuration ──
SANDBOX_IMAGE = os.environ.get("SANDBOX_IMAGE", "python:3.11-slim")
SANDBOX_TTL = int(os.environ.get("SANDBOX_TTL", "1800"))  # 30 min default
SANDBOX_MEM_LIMIT = os.environ.get("SANDBOX_MEM_LIMIT", "512m")
SANDBOX_CPU_PERIOD = int(os.environ.get("SANDBOX_CPU_PERIOD", "100000"))
SANDBOX_CPU_QUOTA = int(os.environ.get("SANDBOX_CPU_QUOTA", "50000"))  # 50% of 1 core
SANDBOX_WORK_DIR = "/home/sandbox"
MAX_ACTIVE_SANDBOXES = int(os.environ.get("MAX_ACTIVE_SANDBOXES", "10"))


class EphemeralSandbox:
    """Represents a single ephemeral Docker sandbox for a task."""

    def __init__(self, sandbox_id: str, container, created_at: float):
        self.sandbox_id = sandbox_id
        self.container = container
        self.created_at = created_at
        self.last_used = created_at
        self.task_id: Optional[str] = None
        self.chat_id: Optional[str] = None
        self.user_id: Optional[str] = None
        self.exec_count = 0
        self.is_active = True

    def to_dict(self) -> Dict:
        return {
            "sandbox_id": self.sandbox_id,
            "container_id": self.container.short_id if self.container else None,
            "task_id": self.task_id,
            "chat_id": self.chat_id,
            "created_at": self.created_at,
            "last_used": self.last_used,
            "exec_count": self.exec_count,
            "is_active": self.is_active,
            "uptime": time.time() - self.created_at,
        }


class SandboxManager:
    """
    Manages ephemeral Docker sandboxes for ORION tasks.
    Each task gets its own isolated container that is destroyed after use.
    """

    def __init__(self):
        self._sandboxes: OrderedDict[str, EphemeralSandbox] = OrderedDict()
        self._lock = threading.Lock()
        self._client: Optional[docker.DockerClient] = None
        self._cleanup_thread: Optional[threading.Thread] = None
        self._running = False

    def _get_docker(self) -> docker.DockerClient:
        """Get or create Docker client."""
        if self._client is None:
            try:
                self._client = docker.from_env()
                self._client.ping()
                logger.info("[SANDBOX] Docker client connected")
            except Exception as e:
                logger.error(f"[SANDBOX] Docker not available: {e}")
                raise RuntimeError(f"Docker not available: {e}")
        return self._client

    def start(self):
        """Start the sandbox manager and cleanup thread."""
        self._running = True
        self._cleanup_thread = threading.Thread(
            target=self._cleanup_loop, daemon=True, name="sandbox-cleanup"
        )
        self._cleanup_thread.start()
        logger.info("[SANDBOX] Manager started")

    def stop(self):
        """Stop the sandbox manager and destroy all sandboxes."""
        self._running = False
        with self._lock:
            for sid in list(self._sandboxes.keys()):
                self._destroy_sandbox(sid)
        logger.info("[SANDBOX] Manager stopped")

    def create_sandbox(
        self,
        task_id: str = None,
        chat_id: str = None,
        user_id: str = None,
        packages: List[str] = None,
    ) -> Dict[str, Any]:
        """
        Create a new ephemeral sandbox for a task.
        Returns sandbox info dict.
        """
        with self._lock:
            # Check limits
            active = sum(1 for s in self._sandboxes.values() if s.is_active)
            if active >= MAX_ACTIVE_SANDBOXES:
                # Try to evict oldest inactive
                self._evict_oldest()
                active = sum(1 for s in self._sandboxes.values() if s.is_active)
                if active >= MAX_ACTIVE_SANDBOXES:
                    return {"success": False, "error": f"Max sandboxes reached ({MAX_ACTIVE_SANDBOXES})"}

        sandbox_id = f"orion-sb-{uuid.uuid4().hex[:12]}"

        try:
            client = self._get_docker()

            # Build setup command
            setup_cmds = [
                "apt-get update -qq",
                "apt-get install -y -qq curl wget git unzip net-tools procps > /dev/null 2>&1",
                f"mkdir -p {SANDBOX_WORK_DIR}",
                "pip install --quiet requests beautifulsoup4 numpy pandas 2>/dev/null || true",
            ]
            if packages:
                for pkg in packages[:10]:  # limit to 10 packages
                    setup_cmds.append(f"pip install --quiet {pkg} 2>/dev/null || true")

            setup_script = " && ".join(setup_cmds)

            container = client.containers.run(
                image=SANDBOX_IMAGE,
                name=sandbox_id,
                command=["bash", "-c", f"{setup_script} && tail -f /dev/null"],
                detach=True,
                mem_limit=SANDBOX_MEM_LIMIT,
                cpu_period=SANDBOX_CPU_PERIOD,
                cpu_quota=SANDBOX_CPU_QUOTA,
                network_mode="bridge",
                working_dir=SANDBOX_WORK_DIR,
                labels={
                    "orion.sandbox": "true",
                    "orion.task_id": task_id or "",
                    "orion.chat_id": chat_id or "",
                    "orion.user_id": user_id or "",
                },
                environment={
                    "SANDBOX_ID": sandbox_id,
                    "TASK_ID": task_id or "",
                    "HOME": SANDBOX_WORK_DIR,
                },
                auto_remove=False,
            )

            # Wait for container to be fully ready
            for _ in range(10):
                container.reload()
                if container.status == "running":
                    break
                time.sleep(0.5)

            sandbox = EphemeralSandbox(sandbox_id, container, time.time())
            sandbox.task_id = task_id
            sandbox.chat_id = chat_id
            sandbox.user_id = user_id

            with self._lock:
                self._sandboxes[sandbox_id] = sandbox

            logger.info(f"[SANDBOX] Created {sandbox_id} for task={task_id}")
            return {
                "success": True,
                "sandbox_id": sandbox_id,
                "container_id": container.short_id,
                "work_dir": SANDBOX_WORK_DIR,
            }

        except Exception as e:
            logger.error(f"[SANDBOX] Create failed: {e}")
            return {"success": False, "error": str(e)}

    def exec_command(
        self,
        sandbox_id: str,
        command: str,
        timeout: int = 30,
        work_dir: str = None,
    ) -> Dict[str, Any]:
        """Execute a command inside an ephemeral sandbox."""
        with self._lock:
            sandbox = self._sandboxes.get(sandbox_id)

        # If not in memory (multi-worker), try to recover from Docker
        if not sandbox or not sandbox.is_active:
            try:
                client = self._get_docker()
                container = client.containers.get(sandbox_id)
                if container.status == "running":
                    sandbox = EphemeralSandbox(sandbox_id, container, time.time())
                    sandbox.is_active = True
                    with self._lock:
                        self._sandboxes[sandbox_id] = sandbox
                    logger.info(f"[SANDBOX] Recovered {sandbox_id} from Docker")
                else:
                    return {"success": False, "error": f"Sandbox {sandbox_id} exists but not running (status: {container.status})"}
            except Exception:
                return {"success": False, "error": f"Sandbox {sandbox_id} not found or inactive"}

        try:
            sandbox.last_used = time.time()
            sandbox.exec_count += 1

            wd = work_dir or SANDBOX_WORK_DIR
            full_cmd = f"cd {wd} && timeout {timeout} bash -c {repr(command)}"

            exit_code, output = sandbox.container.exec_run(
                ["bash", "-c", full_cmd],
                workdir=wd,
                demux=True,
            )

            stdout = (output[0] or b"").decode("utf-8", errors="replace")
            stderr = (output[1] or b"").decode("utf-8", errors="replace")

            # Truncate long output
            max_out = 50000
            if len(stdout) > max_out:
                stdout = stdout[:max_out] + f"\n... (truncated, {len(stdout)} chars total)"
            if len(stderr) > max_out:
                stderr = stderr[:max_out] + f"\n... (truncated)"

            return {
                "success": exit_code == 0,
                "exit_code": exit_code,
                "stdout": stdout,
                "stderr": stderr,
                "sandbox_id": sandbox_id,
                "exec_count": sandbox.exec_count,
            }

        except Exception as e:
            logger.error(f"[SANDBOX] Exec failed in {sandbox_id}: {e}")
            return {"success": False, "error": str(e)}

    def write_file(self, sandbox_id: str, path: str, content: str) -> Dict:
        """Write a file into the sandbox."""
        with self._lock:
            sandbox = self._sandboxes.get(sandbox_id)
            if not sandbox or not sandbox.is_active:
                return {"success": False, "error": "Sandbox not found"}

        try:
            # Create tar archive with the file
            data = content.encode("utf-8")
            tarstream = io.BytesIO()
            with tarfile.open(fileobj=tarstream, mode="w") as tar:
                info = tarfile.TarInfo(name=os.path.basename(path))
                info.size = len(data)
                tar.addfile(info, io.BytesIO(data))
            tarstream.seek(0)

            dest_dir = os.path.dirname(path) or SANDBOX_WORK_DIR
            # Ensure directory exists
            sandbox.container.exec_run(["mkdir", "-p", dest_dir])
            sandbox.container.put_archive(dest_dir, tarstream)

            return {"success": True, "path": path, "size": len(data)}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def read_file(self, sandbox_id: str, path: str) -> Dict:
        """Read a file from the sandbox."""
        with self._lock:
            sandbox = self._sandboxes.get(sandbox_id)
            if not sandbox or not sandbox.is_active:
                return {"success": False, "error": "Sandbox not found"}

        try:
            bits, stat = sandbox.container.get_archive(path)
            file_data = b""
            for chunk in bits:
                file_data += chunk

            # Extract from tar
            tarstream = io.BytesIO(file_data)
            with tarfile.open(fileobj=tarstream) as tar:
                member = tar.getmembers()[0]
                f = tar.extractfile(member)
                content = f.read().decode("utf-8", errors="replace") if f else ""

            return {"success": True, "content": content, "path": path, "size": len(content)}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def destroy_sandbox(self, sandbox_id: str) -> Dict:
        """Destroy a sandbox and its container."""
        with self._lock:
            return self._destroy_sandbox(sandbox_id)

    def _destroy_sandbox(self, sandbox_id: str) -> Dict:
        """Internal destroy (must hold lock)."""
        sandbox = self._sandboxes.get(sandbox_id)
        if not sandbox:
            # Try to find container directly in Docker (multi-worker recovery)
            try:
                client = self._get_docker()
                container = client.containers.get(sandbox_id)
                container.stop(timeout=5)
                container.remove(force=True)
                logger.info(f"[SANDBOX] Destroyed {sandbox_id} (recovered from Docker)")
                return {"success": True, "sandbox_id": sandbox_id}
            except Exception:
                return {"success": False, "error": "Not found"}

        try:
            if sandbox.container:
                sandbox.container.stop(timeout=5)
                sandbox.container.remove(force=True)
        except Exception as e:
            logger.debug(f"[SANDBOX] Destroy {sandbox_id}: {e}")

        sandbox.is_active = False
        del self._sandboxes[sandbox_id]
        logger.info(f"[SANDBOX] Destroyed {sandbox_id}")
        return {"success": True, "sandbox_id": sandbox_id}

    def _evict_oldest(self):
        """Evict oldest inactive sandbox."""
        oldest_id = None
        oldest_time = float("inf")
        for sid, sb in self._sandboxes.items():
            if sb.last_used < oldest_time:
                oldest_time = sb.last_used
                oldest_id = sid
        if oldest_id:
            self._destroy_sandbox(oldest_id)

    def get_sandbox(self, sandbox_id: str) -> Optional[Dict]:
        """Get sandbox info."""
        with self._lock:
            sb = self._sandboxes.get(sandbox_id)
            return sb.to_dict() if sb else None

    def get_sandbox_for_task(self, task_id: str) -> Optional[str]:
        """Find sandbox ID for a given task."""
        with self._lock:
            for sid, sb in self._sandboxes.items():
                if sb.task_id == task_id and sb.is_active:
                    return sid
        return None

    def list_sandboxes(self) -> List[Dict]:
        """List all active sandboxes."""
        with self._lock:
            return [sb.to_dict() for sb in self._sandboxes.values() if sb.is_active]

    def _cleanup_loop(self):
        """Background thread to clean up expired sandboxes."""
        while self._running:
            try:
                time.sleep(60)
                now = time.time()
                expired = []
                with self._lock:
                    for sid, sb in self._sandboxes.items():
                        if sb.is_active and (now - sb.last_used) > SANDBOX_TTL:
                            expired.append(sid)

                for sid in expired:
                    logger.info(f"[SANDBOX] TTL expired: {sid}")
                    self.destroy_sandbox(sid)

            except Exception as e:
                logger.debug(f"[SANDBOX] Cleanup error: {e}")


# ── Singleton ──
_manager: Optional[SandboxManager] = None
_manager_lock = threading.Lock()


def get_sandbox_manager() -> SandboxManager:
    """Get or create the global sandbox manager."""
    global _manager
    if _manager is None:
        with _manager_lock:
            if _manager is None:
                _manager = SandboxManager()
                _manager.start()
    return _manager


# ── Tool functions for agent ──

def tool_sandbox_create(task_id: str = None, chat_id: str = None,
                        user_id: str = None, packages: list = None) -> dict:
    """Create a new ephemeral sandbox."""
    mgr = get_sandbox_manager()
    return mgr.create_sandbox(task_id=task_id, chat_id=chat_id,
                              user_id=user_id, packages=packages)


def tool_sandbox_exec(sandbox_id: str, command: str,
                      timeout: int = 30, work_dir: str = None) -> dict:
    """Execute a command in a sandbox."""
    mgr = get_sandbox_manager()
    return mgr.exec_command(sandbox_id, command, timeout=timeout, work_dir=work_dir)


def tool_sandbox_write_file(sandbox_id: str, path: str, content: str) -> dict:
    """Write a file into a sandbox."""
    mgr = get_sandbox_manager()
    return mgr.write_file(sandbox_id, path, content)


def tool_sandbox_read_file(sandbox_id: str, path: str) -> dict:
    """Read a file from a sandbox."""
    mgr = get_sandbox_manager()
    return mgr.read_file(sandbox_id, path)


def tool_sandbox_destroy(sandbox_id: str) -> dict:
    """Destroy a sandbox."""
    mgr = get_sandbox_manager()
    return mgr.destroy_sandbox(sandbox_id)


# ── Tool schemas for agent ──

EPHEMERAL_SANDBOX_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "sandbox_create",
            "description": "Create a new isolated ephemeral sandbox (Docker container) for executing code safely. Each task should have its own sandbox. Returns sandbox_id.",
            "parameters": {
                "type": "object",
                "properties": {
                    "packages": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Python packages to pre-install in the sandbox"
                    }
                },
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "sandbox_exec",
            "description": "Execute a shell command inside an ephemeral sandbox. Supports bash, python, node. Returns stdout, stderr, exit_code.",
            "parameters": {
                "type": "object",
                "properties": {
                    "sandbox_id": {
                        "type": "string",
                        "description": "Sandbox ID returned from sandbox_create"
                    },
                    "command": {
                        "type": "string",
                        "description": "Shell command to execute"
                    },
                    "timeout": {
                        "type": "integer",
                        "description": "Timeout in seconds (default: 30, max: 300)"
                    }
                },
                "required": ["sandbox_id", "command"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "sandbox_write_file",
            "description": "Write a file into the sandbox filesystem.",
            "parameters": {
                "type": "object",
                "properties": {
                    "sandbox_id": {"type": "string", "description": "Sandbox ID"},
                    "path": {"type": "string", "description": "File path inside sandbox"},
                    "content": {"type": "string", "description": "File content to write"}
                },
                "required": ["sandbox_id", "path", "content"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "sandbox_read_file",
            "description": "Read a file from the sandbox filesystem.",
            "parameters": {
                "type": "object",
                "properties": {
                    "sandbox_id": {"type": "string", "description": "Sandbox ID"},
                    "path": {"type": "string", "description": "File path inside sandbox"}
                },
                "required": ["sandbox_id", "path"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "sandbox_destroy",
            "description": "Destroy an ephemeral sandbox and free resources. Called automatically after task completion.",
            "parameters": {
                "type": "object",
                "properties": {
                    "sandbox_id": {"type": "string", "description": "Sandbox ID to destroy"}
                },
                "required": ["sandbox_id"]
            }
        }
    },
]
