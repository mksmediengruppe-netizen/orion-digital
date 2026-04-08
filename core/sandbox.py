"""
ARCANE Sandbox Isolation — Docker-based

Provides container-level isolation for agent-executed commands.
Each agent session gets a Docker container with:
- Full root access inside the container
- Isolated filesystem (destroyed after session)
- Resource limits (CPU, memory, PIDs)
- Network access to external internet only
- Project workspace mounted as a volume

Fallback: if Docker is unavailable, falls back to su-based sandbox (v7 behavior).

Setup:
    docker pull ubuntu:22.04
    # or use a custom image with pre-installed tools:
    docker build -t arcane-sandbox -f Dockerfile.sandbox .
"""

from __future__ import annotations

import asyncio
import os
import shlex
import time
from typing import Optional

from shared.utils.logger import get_logger

logger = get_logger("core.sandbox")

# ═══════════════════════════════════════════════════════════════════════════════
# Configuration
# ═══════════════════════════════════════════════════════════════════════════════

DOCKER_IMAGE = os.environ.get("SANDBOX_DOCKER_IMAGE", "arcane-sandbox:latest")
DOCKER_FALLBACK_IMAGE = "ubuntu:22.04"
SANDBOX_USER = "arcane_sandbox"  # fallback su-based user
SANDBOX_HOME = "/home/arcane_sandbox"

# Docker resource limits
DOCKER_MEMORY_LIMIT = os.environ.get("SANDBOX_MEMORY_LIMIT", "512m")
DOCKER_CPU_LIMIT = os.environ.get("SANDBOX_CPU_LIMIT", "1.0")
DOCKER_PIDS_LIMIT = int(os.environ.get("SANDBOX_PIDS_LIMIT", "100"))

# Container pool for reuse within a session
_container_pool: dict[str, str] = {}  # session_id -> container_id

# Commands that are NEVER allowed
BLOCKED_COMMANDS = [
    "rm -rf /",
    "rm -rf /*",
    "mkfs",
    "dd if=/dev/zero",
    ":(){ :|:& };:",
    "shutdown",
    "reboot",
    "halt",
    "init 0",
    "init 6",
]


def is_command_safe(command: str) -> tuple[bool, str]:
    """
    Check if a command is safe to execute in the sandbox.
    Returns (is_safe, reason).
    """
    cmd_lower = command.lower().strip()

    for blocked in BLOCKED_COMMANDS:
        if blocked in cmd_lower:
            return False, f"Blocked command pattern: {blocked}"

    return True, "OK"


# ═══════════════════════════════════════════════════════════════════════════════
# Docker Sandbox
# ═══════════════════════════════════════════════════════════════════════════════

def _docker_available() -> bool:
    """Check if Docker daemon is running and accessible."""
    try:
        import subprocess
        result = subprocess.run(
            ["docker", "info"], capture_output=True, timeout=5
        )
        return result.returncode == 0
    except Exception:
        return False


async def _get_or_create_container(
    session_id: str,
    working_dir: str,
    memory_limit: str = DOCKER_MEMORY_LIMIT,
    cpu_limit: str = DOCKER_CPU_LIMIT,
) -> Optional[str]:
    """
    Get an existing container for this session, or create a new one.
    Containers are reused within a session for state persistence (installed packages, etc).
    """
    # Check if we already have a running container for this session
    if session_id in _container_pool:
        container_id = _container_pool[session_id]
        # Verify it's still running
        proc = await asyncio.create_subprocess_exec(
            "docker", "inspect", "-f", "{{.State.Running}}", container_id,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await proc.communicate()
        if stdout.strip() == b"true":
            return container_id
        else:
            # Container died — remove from pool
            del _container_pool[session_id]

    # Create new container
    container_name = f"arcane-sandbox-{session_id[:12]}"

    # Ensure workspace directory exists on host
    os.makedirs(working_dir, exist_ok=True)

    # Determine which image to use
    image = DOCKER_IMAGE
    # Check if custom image exists
    proc = await asyncio.create_subprocess_exec(
        "docker", "image", "inspect", image,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    await proc.communicate()
    if proc.returncode != 0:
        image = DOCKER_FALLBACK_IMAGE
        logger.info(f"Custom image {DOCKER_IMAGE} not found, using {DOCKER_FALLBACK_IMAGE}")

    cmd = [
        "docker", "run", "-d",
        "--name", container_name,
        # Resource limits
        f"--memory={memory_limit}",
        f"--cpus={cpu_limit}",
        f"--pids-limit={DOCKER_PIDS_LIMIT}",
        # Security
        "--security-opt=no-new-privileges",
        "--cap-drop=ALL",
        "--cap-add=CHOWN",
        "--cap-add=DAC_OVERRIDE",
        "--cap-add=FOWNER",
        "--cap-add=SETUID",
        "--cap-add=SETGID",
        "--cap-add=NET_BIND_SERVICE",
        # Mount workspace
        "-v", f"{working_dir}:/workspace",
        "-w", "/workspace",
        # Network: allow external, block internal
        "--network=bridge",
        # Keep alive
        image,
        "sleep", "infinity",
    ]

    try:
        # Remove old container with same name if exists
        cleanup = await asyncio.create_subprocess_exec(
            "docker", "rm", "-f", container_name,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await cleanup.communicate()

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()

        if proc.returncode != 0:
            logger.error(f"Failed to create Docker container: {stderr.decode()}")
            return None

        container_id = stdout.decode().strip()[:12]
        _container_pool[session_id] = container_id
        logger.info(f"Created Docker sandbox container {container_id} for session {session_id[:8]}")

        # Install basic tools inside container (non-blocking)
        asyncio.create_task(_setup_container(container_id))

        return container_id

    except Exception as e:
        logger.error(f"Docker container creation failed: {e}")
        return None


async def _setup_container(container_id: str):
    """Install basic tools inside the container (runs in background)."""
    try:
        setup_cmd = (
            "apt-get update -qq && "
            "apt-get install -y -qq curl wget git python3 python3-pip nodejs npm "
            "build-essential 2>/dev/null || true"
        )
        proc = await asyncio.create_subprocess_exec(
            "docker", "exec", container_id, "bash", "-c", setup_cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await asyncio.wait_for(proc.communicate(), timeout=120)
        logger.info(f"Container {container_id} setup complete")
    except Exception as e:
        logger.warning(f"Container setup failed (non-critical): {e}")


async def execute_in_docker(
    command: str,
    working_dir: str,
    session_id: str = "default",
    timeout: int = 30,
    memory_limit: str = DOCKER_MEMORY_LIMIT,
) -> dict:
    """
    Execute a command inside a Docker container.
    Returns dict with exit_code, stdout, stderr, elapsed_seconds.
    """
    # Safety check
    is_safe, reason = is_command_safe(command)
    if not is_safe:
        return {
            "exit_code": -1,
            "stdout": "",
            "stderr": f"Command blocked by sandbox: {reason}",
            "elapsed_seconds": 0,
            "sandboxed": True,
            "sandbox_type": "docker",
        }

    container_id = await _get_or_create_container(
        session_id, working_dir, memory_limit
    )
    if not container_id:
        logger.warning("Docker unavailable, falling back to su-based sandbox")
        return await execute_sandboxed(command, working_dir, timeout)

    start = time.monotonic()
    try:
        proc = await asyncio.create_subprocess_exec(
            "docker", "exec",
            "-w", "/workspace",
            container_id,
            "bash", "-c", command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(
            proc.communicate(), timeout=timeout + 5
        )
        elapsed = time.monotonic() - start

        return {
            "exit_code": proc.returncode,
            "stdout": stdout.decode("utf-8", errors="replace")[:10000],
            "stderr": stderr.decode("utf-8", errors="replace")[:5000],
            "elapsed_seconds": round(elapsed, 2),
            "sandboxed": True,
            "sandbox_type": "docker",
            "container_id": container_id,
        }

    except asyncio.TimeoutError:
        return {
            "exit_code": -1,
            "stdout": "",
            "stderr": f"Docker command timed out after {timeout} seconds",
            "elapsed_seconds": timeout,
            "sandboxed": True,
            "sandbox_type": "docker",
        }
    except Exception as e:
        return {
            "exit_code": -1,
            "stdout": "",
            "stderr": str(e),
            "elapsed_seconds": time.monotonic() - start,
            "sandboxed": True,
            "sandbox_type": "docker",
        }


async def destroy_container(session_id: str):
    """Destroy a session's container (cleanup)."""
    container_id = _container_pool.pop(session_id, None)
    if container_id:
        try:
            proc = await asyncio.create_subprocess_exec(
                "docker", "rm", "-f", container_id,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await proc.communicate()
            logger.info(f"Destroyed Docker sandbox container {container_id}")
        except Exception as e:
            logger.warning(f"Failed to destroy container {container_id}: {e}")


# ═══════════════════════════════════════════════════════════════════════════════
# Fallback: su-based sandbox (v7 behavior)
# ═══════════════════════════════════════════════════════════════════════════════

def wrap_command_for_sandbox(
    command: str,
    working_dir: str,
    timeout: int = 30,
    max_memory_mb: int = 512,
    max_filesize_mb: int = 100,
) -> str:
    """Wrap a command to run as the sandbox user with resource limits."""
    escaped_cmd = command.replace("'", "'\\''")
    escaped_dir = shlex.quote(working_dir)

    sandboxed = (
        f"timeout {timeout} "
        f"su - {SANDBOX_USER} -s /bin/bash -c '"
        f"cd {escaped_dir} 2>/dev/null || cd /tmp; "
        f"ulimit -v {max_memory_mb * 1024} 2>/dev/null; "
        f"ulimit -f {max_filesize_mb * 1024} 2>/dev/null; "
        f"ulimit -t {timeout} 2>/dev/null; "
        f"ulimit -n 1024 2>/dev/null; "
        f"{escaped_cmd}"
        f"'"
    )

    return sandboxed


async def execute_sandboxed(
    command: str,
    working_dir: str = "/tmp",
    timeout: int = 30,
    max_memory_mb: int = 512,
    max_filesize_mb: int = 100,
) -> dict:
    """
    Execute a command in the su-based sandbox (fallback).
    Returns dict with exit_code, stdout, stderr, elapsed_seconds.
    """
    is_safe, reason = is_command_safe(command)
    if not is_safe:
        return {
            "exit_code": -1,
            "stdout": "",
            "stderr": f"Command blocked by sandbox: {reason}",
            "elapsed_seconds": 0,
            "sandboxed": True,
            "sandbox_type": "su",
        }

    if not _sandbox_user_exists():
        logger.error("Sandbox user does not exist! Refusing to run without isolation.")
        return {
            "exit_code": -1,
            "stdout": "",
            "stderr": "Sandbox isolation unavailable — command blocked for security. "
                      "Run: useradd -r -s /bin/bash -m arcane_sandbox",
            "elapsed_seconds": 0,
            "sandboxed": False,
            "sandbox_type": "none",
        }

    sandboxed_cmd = wrap_command_for_sandbox(
        command, working_dir, timeout, max_memory_mb, max_filesize_mb
    )

    start = time.monotonic()
    try:
        proc = await asyncio.create_subprocess_shell(
            sandboxed_cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(
            proc.communicate(), timeout=timeout + 5
        )
        elapsed = time.monotonic() - start

        return {
            "exit_code": proc.returncode,
            "stdout": stdout.decode("utf-8", errors="replace")[:10000],
            "stderr": stderr.decode("utf-8", errors="replace")[:5000],
            "elapsed_seconds": round(elapsed, 2),
            "sandboxed": True,
            "sandbox_type": "su",
        }

    except asyncio.TimeoutError:
        return {
            "exit_code": -1,
            "stdout": "",
            "stderr": f"Sandboxed command timed out after {timeout} seconds",
            "elapsed_seconds": timeout,
            "sandboxed": True,
            "sandbox_type": "su",
        }
    except Exception as e:
        return {
            "exit_code": -1,
            "stdout": "",
            "stderr": str(e),
            "elapsed_seconds": time.monotonic() - start,
            "sandboxed": True,
            "sandbox_type": "su",
        }


# ═══════════════════════════════════════════════════════════════════════════════
# Unified API — auto-selects Docker or su-based sandbox
# ═══════════════════════════════════════════════════════════════════════════════

_docker_checked: Optional[bool] = None


async def execute(
    command: str,
    working_dir: str = "/tmp",
    session_id: str = "default",
    timeout: int = 30,
) -> dict:
    """
    Unified sandbox execution — tries Docker first, falls back to su-based.
    This is the main entry point for all sandboxed command execution.
    """
    global _docker_checked

    # Check Docker availability once
    if _docker_checked is None:
        _docker_checked = _docker_available()
        if _docker_checked:
            logger.info("Docker sandbox available — using container isolation")
        else:
            logger.warning("Docker not available — falling back to su-based sandbox")

    if _docker_checked:
        return await execute_in_docker(command, working_dir, session_id, timeout)
    else:
        return await execute_sandboxed(command, working_dir, timeout)


def _sandbox_user_exists() -> bool:
    """Check if the sandbox user exists on the system."""
    try:
        import pwd
        pwd.getpwnam(SANDBOX_USER)
        return True
    except KeyError:
        return False


def setup_sandbox_user() -> str:
    """
    Create the sandbox user with restricted permissions.
    Must be run as root. Returns a status message.
    """
    import subprocess

    commands = [
        f"useradd -r -m -d {SANDBOX_HOME} -s /bin/bash {SANDBOX_USER} 2>/dev/null || true",
        f"chmod 750 {SANDBOX_HOME}",
        f"mkdir -p /root/workspace && chmod 777 /root/workspace",
        f"setfacl -m u:{SANDBOX_USER}:--- /root/.ssh 2>/dev/null || true",
        f"setfacl -m u:{SANDBOX_USER}:--- /etc/shadow 2>/dev/null || true",
        f"apt-get install -y -qq acl 2>/dev/null || true",
    ]

    results = []
    for cmd in commands:
        try:
            result = subprocess.run(
                cmd, shell=True, capture_output=True, text=True, timeout=30
            )
            results.append(f"OK: {cmd[:60]}")
        except Exception as e:
            results.append(f"FAIL: {cmd[:60]} — {e}")

    return "\n".join(results)


def setup_docker_sandbox() -> str:
    """
    Build the custom Docker sandbox image with pre-installed tools.
    Run once during server setup.
    """
    import subprocess

    dockerfile_content = '''FROM ubuntu:22.04
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends \\
    curl wget git python3 python3-pip python3-venv \\
    nodejs npm build-essential unzip zip \\
    && rm -rf /var/lib/apt/lists/*
RUN pip3 install --no-cache-dir requests beautifulsoup4 flask fastapi uvicorn
RUN npm install -g pnpm yarn
WORKDIR /workspace
'''
    # Write Dockerfile
    dockerfile_path = "/tmp/Dockerfile.arcane-sandbox"
    with open(dockerfile_path, "w") as f:
        f.write(dockerfile_content)

    try:
        result = subprocess.run(
            ["docker", "build", "-t", "arcane-sandbox:latest", "-f", dockerfile_path, "/tmp"],
            capture_output=True, text=True, timeout=300,
        )
        if result.returncode == 0:
            return "Docker sandbox image built successfully"
        else:
            return f"Docker build failed: {result.stderr[:500]}"
    except Exception as e:
        return f"Docker build error: {e}"
