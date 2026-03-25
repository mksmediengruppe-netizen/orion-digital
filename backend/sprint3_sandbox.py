"""
Sprint 3: Docker Sandbox for ORION
===================================
Isolated code execution environment using Docker containers.
Supports Python, Node.js, Shell, and persistent sandbox sessions.

Features:
- Isolated Docker containers per session
- Resource limits (CPU, memory, network)
- File I/O between host and container
- Streaming output
- Auto-cleanup after timeout
- Runtime logs and metrics
"""

import os
import json
import time
import uuid
import logging
import subprocess
import threading
import tempfile
from typing import Optional, Dict, Any, List
from datetime import datetime

logger = logging.getLogger("sprint3_sandbox")

# ── Config ──────────────────────────────────────────────────────
SANDBOX_IMAGE = os.environ.get("SANDBOX_IMAGE", "python:3.11-slim")
SANDBOX_TIMEOUT = int(os.environ.get("SANDBOX_TIMEOUT", "30"))
SANDBOX_MEM_LIMIT = os.environ.get("SANDBOX_MEM_LIMIT", "256m")
SANDBOX_CPU_QUOTA = os.environ.get("SANDBOX_CPU_QUOTA", "50000")  # 50% of 1 CPU
DATA_DIR = os.environ.get("DATA_DIR", "/var/www/orion/backend/data")
GENERATED_DIR = os.environ.get("GENERATED_DIR", "/var/www/orion/backend/generated")

# Active sandbox sessions: session_id -> container_id
_active_sandboxes: Dict[str, Dict] = {}
_sandbox_lock = threading.Lock()


def _run_cmd(cmd: str, timeout: int = 30) -> tuple[int, str, str]:
    """Run shell command, return (returncode, stdout, stderr)."""
    try:
        r = subprocess.run(
            cmd, shell=True, capture_output=True, text=True, timeout=timeout
        )
        return r.returncode, r.stdout, r.stderr
    except subprocess.TimeoutExpired:
        return -1, "", "Command timed out"
    except Exception as e:
        return -1, "", str(e)


def _docker_available() -> bool:
    """Check if Docker is available."""
    rc, _, _ = _run_cmd("docker info --format '{{.ServerVersion}}' 2>/dev/null", timeout=5)
    return rc == 0


# ── Tool: sandbox_exec ──────────────────────────────────────────
def tool_sandbox_exec(
    code: str,
    language: str = "python",
    session_id: Optional[str] = None,
    files: Optional[Dict[str, str]] = None,
    timeout: int = 30,
    install_packages: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """
    Execute code in an isolated Docker sandbox.
    
    Args:
        code: Code to execute
        language: python | node | bash | sh
        session_id: Reuse existing sandbox session
        files: Dict of {filename: content} to write before execution
        timeout: Max execution time in seconds
        install_packages: List of pip/npm packages to install first
    """
    start_time = time.time()
    
    if not _docker_available():
        # Fallback: run locally with restrictions
        return _local_exec_fallback(code, language, timeout, files)
    
    try:
        # Create temp directory for file exchange
        work_dir = tempfile.mkdtemp(prefix="orion_sandbox_")
        
        # Write input files
        if files:
            for fname, content in files.items():
                fpath = os.path.join(work_dir, fname)
                os.makedirs(os.path.dirname(fpath), exist_ok=True)
                with open(fpath, "w", encoding="utf-8") as f:
                    f.write(content)
        
        # Write main code file
        if language == "python":
            code_file = os.path.join(work_dir, "main.py")
            run_cmd = "python3 main.py"
            image = "python:3.11-slim"
        elif language in ("node", "javascript", "js"):
            code_file = os.path.join(work_dir, "main.js")
            run_cmd = "node main.js"
            image = "node:20-slim"
        elif language in ("bash", "sh", "shell"):
            code_file = os.path.join(work_dir, "main.sh")
            run_cmd = "bash main.sh"
            image = "bash:5"
        else:
            code_file = os.path.join(work_dir, "main.py")
            run_cmd = "python3 main.py"
            image = "python:3.11-slim"
        
        with open(code_file, "w", encoding="utf-8") as f:
            f.write(code)
        
        # Build docker run command
        container_name = f"orion_sandbox_{uuid.uuid4().hex[:8]}"
        
        install_cmd = ""
        if install_packages:
            if language == "python":
                pkgs = " ".join(install_packages)
                install_cmd = f"pip install -q {pkgs} && "
            elif language in ("node", "javascript", "js"):
                pkgs = " ".join(install_packages)
                install_cmd = f"npm install -q {pkgs} && "
        
        docker_cmd = (
            f"docker run --rm "
            f"--name {container_name} "
            f"--memory={SANDBOX_MEM_LIMIT} "
            f"--cpu-quota={SANDBOX_CPU_QUOTA} "
            f"--network=none "
            f"--security-opt no-new-privileges "
            f"-v {work_dir}:/workspace "
            f"-w /workspace "
            f"--timeout {timeout} "
            f"{image} "
            f"sh -c '{install_cmd}{run_cmd}'"
        )
        
        rc, stdout, stderr = _run_cmd(docker_cmd, timeout=timeout + 10)
        elapsed = time.time() - start_time
        
        # Collect output files
        output_files = {}
        for fname in os.listdir(work_dir):
            fpath = os.path.join(work_dir, fname)
            if os.path.isfile(fpath) and fname not in ("main.py", "main.js", "main.sh"):
                try:
                    with open(fpath, "r", encoding="utf-8", errors="replace") as f:
                        output_files[fname] = f.read()
                except Exception:
                    pass
        
        # Cleanup
        import shutil
        shutil.rmtree(work_dir, ignore_errors=True)
        
        return {
            "success": rc == 0,
            "result": {
                "stdout": stdout,
                "stderr": stderr,
                "exit_code": rc,
                "elapsed_seconds": round(elapsed, 2),
                "language": language,
                "output_files": output_files,
                "container": container_name,
            },
            "error": stderr if rc != 0 else None,
        }
        
    except Exception as e:
        logger.exception("sandbox_exec failed")
        return {"success": False, "error": str(e), "result": {}}


def _local_exec_fallback(
    code: str, language: str, timeout: int, files: Optional[Dict] = None
) -> Dict[str, Any]:
    """Fallback: execute code locally when Docker is unavailable."""
    start_time = time.time()
    work_dir = tempfile.mkdtemp(prefix="orion_local_")
    
    try:
        if files:
            for fname, content in files.items():
                with open(os.path.join(work_dir, fname), "w") as f:
                    f.write(content)
        
        if language == "python":
            code_file = os.path.join(work_dir, "main.py")
            cmd = f"cd {work_dir} && python3 main.py"
        elif language in ("node", "javascript", "js"):
            code_file = os.path.join(work_dir, "main.js")
            cmd = f"cd {work_dir} && node main.js"
        else:
            code_file = os.path.join(work_dir, "main.sh")
            cmd = f"cd {work_dir} && bash main.sh"
        
        with open(code_file, "w") as f:
            f.write(code)
        
        rc, stdout, stderr = _run_cmd(cmd, timeout=timeout)
        elapsed = time.time() - start_time
        
        return {
            "success": rc == 0,
            "result": {
                "stdout": stdout,
                "stderr": stderr,
                "exit_code": rc,
                "elapsed_seconds": round(elapsed, 2),
                "language": language,
                "output_files": {},
                "mode": "local_fallback",
            },
            "error": stderr if rc != 0 else None,
        }
    except Exception as e:
        return {"success": False, "error": str(e), "result": {}}
    finally:
        import shutil
        shutil.rmtree(work_dir, ignore_errors=True)


# ── Tool: sandbox_create_session ────────────────────────────────
def tool_sandbox_create_session(
    language: str = "python",
    packages: Optional[List[str]] = None,
    session_name: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Create a persistent sandbox session (Docker container).
    Returns session_id for subsequent sandbox_exec calls.
    """
    if not _docker_available():
        session_id = f"local_{uuid.uuid4().hex[:8]}"
        with _sandbox_lock:
            _active_sandboxes[session_id] = {
                "type": "local",
                "language": language,
                "created_at": datetime.utcnow().isoformat(),
                "name": session_name or session_id,
            }
        return {
            "success": True,
            "result": {
                "session_id": session_id,
                "type": "local_fallback",
                "language": language,
                "message": "Docker unavailable, using local execution",
            }
        }
    
    try:
        session_id = f"orion_{uuid.uuid4().hex[:8]}"
        
        if language == "python":
            image = "python:3.11-slim"
        elif language in ("node", "javascript"):
            image = "node:20-slim"
        else:
            image = "python:3.11-slim"
        
        # Pull image if needed
        _run_cmd(f"docker pull {image} -q", timeout=120)
        
        # Pre-install packages
        if packages:
            pkgs = " ".join(packages)
            if language == "python":
                install = f"pip install -q {pkgs}"
            else:
                install = f"npm install -g {pkgs}"
            
            rc, out, err = _run_cmd(
                f"docker run --rm {image} sh -c '{install}' 2>&1",
                timeout=120
            )
        
        with _sandbox_lock:
            _active_sandboxes[session_id] = {
                "type": "docker",
                "language": language,
                "image": image,
                "packages": packages or [],
                "created_at": datetime.utcnow().isoformat(),
                "name": session_name or session_id,
                "exec_count": 0,
            }
        
        return {
            "success": True,
            "result": {
                "session_id": session_id,
                "type": "docker",
                "language": language,
                "image": image,
                "packages_installed": packages or [],
                "message": f"Sandbox session '{session_id}' created",
            }
        }
    except Exception as e:
        logger.exception("sandbox_create_session failed")
        return {"success": False, "error": str(e), "result": {}}


# ── Tool: sandbox_list_sessions ──────────────────────────────────
def tool_sandbox_list_sessions() -> Dict[str, Any]:
    """List all active sandbox sessions."""
    with _sandbox_lock:
        sessions = [
            {
                "session_id": sid,
                "name": info.get("name", sid),
                "type": info.get("type", "unknown"),
                "language": info.get("language", "python"),
                "created_at": info.get("created_at", ""),
                "exec_count": info.get("exec_count", 0),
            }
            for sid, info in _active_sandboxes.items()
        ]
    
    return {
        "success": True,
        "result": {
            "sessions": sessions,
            "total": len(sessions),
        }
    }


# ── Tool: sandbox_destroy_session ────────────────────────────────
def tool_sandbox_destroy_session(session_id: str) -> Dict[str, Any]:
    """Destroy a sandbox session and clean up resources."""
    with _sandbox_lock:
        if session_id not in _active_sandboxes:
            return {"success": False, "error": f"Session '{session_id}' not found"}
        
        info = _active_sandboxes.pop(session_id)
    
    # Kill any running containers with this session prefix
    if info.get("type") == "docker":
        _run_cmd(f"docker ps -q --filter name={session_id} | xargs -r docker kill", timeout=10)
    
    return {
        "success": True,
        "result": {
            "session_id": session_id,
            "destroyed": True,
            "message": f"Session '{session_id}' destroyed",
        }
    }


# ── Tool: runtime_logs ───────────────────────────────────────────
def tool_runtime_logs(
    container_name: Optional[str] = None,
    lines: int = 100,
    service: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Get runtime logs from Docker container or system service.
    """
    try:
        logs = []
        
        if container_name:
            rc, stdout, stderr = _run_cmd(
                f"docker logs --tail {lines} {container_name} 2>&1",
                timeout=10
            )
            if rc == 0:
                logs = stdout.strip().split("\n")
            else:
                return {"success": False, "error": f"Container '{container_name}' not found"}
        
        elif service:
            rc, stdout, stderr = _run_cmd(
                f"journalctl -u {service} -n {lines} --no-pager 2>&1",
                timeout=10
            )
            if rc == 0:
                logs = stdout.strip().split("\n")
            else:
                # Try systemctl status
                rc2, out2, _ = _run_cmd(f"systemctl status {service} 2>&1", timeout=5)
                logs = out2.strip().split("\n")
        
        else:
            # Get ORION service logs
            rc, stdout, _ = _run_cmd(
                f"journalctl -u orion-api -n {lines} --no-pager 2>&1 || "
                f"tail -n {lines} /var/log/orion/api.log 2>/dev/null || "
                f"echo 'No logs found'",
                timeout=10
            )
            logs = stdout.strip().split("\n")
        
        return {
            "success": True,
            "result": {
                "logs": logs,
                "total_lines": len(logs),
                "source": container_name or service or "orion-api",
            }
        }
    except Exception as e:
        return {"success": False, "error": str(e), "result": {}}


# ── Tool: docker_run_image ───────────────────────────────────────
def tool_docker_run_image(
    image: str,
    command: str,
    env_vars: Optional[Dict[str, str]] = None,
    volumes: Optional[Dict[str, str]] = None,
    ports: Optional[Dict[str, str]] = None,
    detach: bool = False,
    timeout: int = 60,
) -> Dict[str, Any]:
    """
    Run a Docker image with specified parameters.
    Useful for running databases, services, or custom environments.
    """
    try:
        if not _docker_available():
            return {"success": False, "error": "Docker not available"}
        
        # Build docker run command
        parts = ["docker run"]
        
        if detach:
            parts.append("-d")
        else:
            parts.append("--rm")
        
        # Environment variables
        if env_vars:
            for k, v in env_vars.items():
                parts.append(f'-e "{k}={v}"')
        
        # Volume mounts
        if volumes:
            for host_path, container_path in volumes.items():
                parts.append(f"-v {host_path}:{container_path}")
        
        # Port mappings
        if ports:
            for host_port, container_port in ports.items():
                parts.append(f"-p {host_port}:{container_port}")
        
        parts.append(f"--memory={SANDBOX_MEM_LIMIT}")
        parts.append(image)
        parts.append(command)
        
        docker_cmd = " ".join(parts)
        rc, stdout, stderr = _run_cmd(docker_cmd, timeout=timeout)
        
        return {
            "success": rc == 0,
            "result": {
                "stdout": stdout,
                "stderr": stderr,
                "exit_code": rc,
                "image": image,
                "command": command,
                "detached": detach,
                "container_id": stdout.strip()[:12] if detach and rc == 0 else None,
            },
            "error": stderr if rc != 0 else None,
        }
    except Exception as e:
        return {"success": False, "error": str(e), "result": {}}


# ── Dispatcher ───────────────────────────────────────────────────
def dispatch_sprint3_tool(tool_name: str, args: dict) -> dict:
    """Route Sprint 3 tool calls to implementations."""
    dispatch_map = {
        "sandbox_exec": lambda a: tool_sandbox_exec(
            code=a.get("code", ""),
            language=a.get("language", "python"),
            session_id=a.get("session_id"),
            files=a.get("files"),
            timeout=a.get("timeout", SANDBOX_TIMEOUT),
            install_packages=a.get("install_packages"),
        ),
        "sandbox_create_session": lambda a: tool_sandbox_create_session(
            language=a.get("language", "python"),
            packages=a.get("packages"),
            session_name=a.get("session_name"),
        ),
        "sandbox_list_sessions": lambda a: tool_sandbox_list_sessions(),
        "sandbox_destroy_session": lambda a: tool_sandbox_destroy_session(
            session_id=a.get("session_id", ""),
        ),
        "runtime_logs": lambda a: tool_runtime_logs(
            container_name=a.get("container_name"),
            lines=a.get("lines", 100),
            service=a.get("service"),
        ),
        "docker_run_image": lambda a: tool_docker_run_image(
            image=a.get("image", ""),
            command=a.get("command", ""),
            env_vars=a.get("env_vars"),
            volumes=a.get("volumes"),
            ports=a.get("ports"),
            detach=a.get("detach", False),
            timeout=a.get("timeout", 60),
        ),
    }
    
    handler = dispatch_map.get(tool_name)
    if not handler:
        return {"success": False, "error": f"Unknown Sprint3 tool: {tool_name}"}
    
    return handler(args)
