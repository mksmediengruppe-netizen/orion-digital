"""
SSH Executor Module — Реальное подключение к серверам и выполнение команд.
Использует paramiko для SSH и SFTP операций.
"""

import paramiko
import io
import os
import time
import threading
import json
from datetime import datetime, timezone


class SSHExecutor:
    """Manages SSH connections and executes commands on remote servers."""

    def __init__(self, host, username="root", password=None, port=22, key_path=None, timeout=30):
        self.host = host
        self.username = username
        self.password = password
        self.port = port
        self.key_path = key_path
        self.timeout = timeout
        self.client = None
        self.sftp = None
        self._connected = False

    def connect(self):
        """Establish SSH connection."""
        try:
            self.client = paramiko.SSHClient()
            self.client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

            connect_kwargs = {
                "hostname": self.host,
                "port": self.port,
                "username": self.username,
                "timeout": self.timeout,
                "allow_agent": False,
                "look_for_keys": False,
            }

            if self.key_path and os.path.exists(self.key_path):
                connect_kwargs["key_filename"] = self.key_path
            elif self.password:
                connect_kwargs["password"] = self.password
            else:
                raise ValueError("No password or key provided for SSH connection")

            self.client.connect(**connect_kwargs)
            self._connected = True
            return {"success": True, "message": f"Connected to {self.host}:{self.port}"}
        except Exception as e:
            self._connected = False
            return {"success": False, "error": str(e)}

    def disconnect(self):
        """Close SSH connection."""
        try:
            if self.sftp:
                self.sftp.close()
                self.sftp = None
            if self.client:
                self.client.close()
                self.client = None
            self._connected = False
        except:
            pass

    @property
    def is_connected(self):
        return self._connected and self.client is not None

    def execute_command(self, command, timeout=60):
        """Execute a command on the remote server and return output."""
        if not self.is_connected:
            conn = self.connect()
            if not conn["success"]:
                return {"success": False, "error": f"Connection failed: {conn['error']}", "stdout": "", "stderr": "", "exit_code": -1}

        try:
            stdin, stdout, stderr = self.client.exec_command(command, timeout=timeout)
            exit_code = stdout.channel.recv_exit_status()

            stdout_text = stdout.read().decode("utf-8", errors="replace").strip()
            stderr_text = stderr.read().decode("utf-8", errors="replace").strip()

            # Limit output size to prevent memory issues
            max_output = 50000
            if len(stdout_text) > max_output:
                stdout_text = stdout_text[:max_output] + "\n... [output truncated]"
            if len(stderr_text) > max_output:
                stderr_text = stderr_text[:max_output] + "\n... [output truncated]"

            return {
                "success": exit_code == 0,
                "stdout": stdout_text,
                "stderr": stderr_text,
                "exit_code": exit_code,
                "command": command
            }
        except Exception as e:
            self._connected = False
            return {
                "success": False,
                "stdout": "",
                "stderr": str(e),
                "exit_code": -1,
                "command": command
            }

    def execute_command_stream(self, command, timeout=120):
        """Execute command and yield output lines in real-time."""
        if not self.is_connected:
            conn = self.connect()
            if not conn["success"]:
                yield {"type": "error", "text": f"Connection failed: {conn['error']}"}
                return

        try:
            transport = self.client.get_transport()
            channel = transport.open_session()
            channel.settimeout(timeout)
            channel.exec_command(command)

            output = ""
            while True:
                if channel.recv_ready():
                    chunk = channel.recv(4096).decode("utf-8", errors="replace")
                    output += chunk
                    # Yield line by line
                    while "\n" in output:
                        line, output = output.split("\n", 1)
                        yield {"type": "stdout", "text": line}
                if channel.recv_stderr_ready():
                    chunk = channel.recv_stderr(4096).decode("utf-8", errors="replace")
                    yield {"type": "stderr", "text": chunk.strip()}
                if channel.exit_status_ready():
                    # Flush remaining
                    while channel.recv_ready():
                        chunk = channel.recv(4096).decode("utf-8", errors="replace")
                        if chunk:
                            yield {"type": "stdout", "text": chunk.strip()}
                    if output.strip():
                        yield {"type": "stdout", "text": output.strip()}
                    exit_code = channel.recv_exit_status()
                    yield {"type": "exit", "code": exit_code}
                    break
                time.sleep(0.1)
        except Exception as e:
            yield {"type": "error", "text": str(e)}

    def _get_sftp(self):
        """Get or create SFTP client."""
        if not self.is_connected:
            conn = self.connect()
            if not conn["success"]:
                raise ConnectionError(f"Cannot connect: {conn['error']}")
        if self.sftp is None:
            self.sftp = self.client.open_sftp()
        return self.sftp

    def file_write(self, remote_path, content):
        """Write content to a file on the remote server."""
        try:
            sftp = self._get_sftp()
            # Ensure directory exists
            dir_path = os.path.dirname(remote_path)
            if dir_path:
                self.execute_command(f"mkdir -p '{dir_path}'")

            with sftp.file(remote_path, "w") as f:
                f.write(content)

            return {"success": True, "path": remote_path, "size": len(content)}
        except Exception as e:
            return {"success": False, "error": str(e), "path": remote_path}

    def file_read(self, remote_path):
        """Read content from a file on the remote server."""
        try:
            sftp = self._get_sftp()
            with sftp.file(remote_path, "r") as f:
                content = f.read().decode("utf-8", errors="replace")
            return {"success": True, "content": content, "path": remote_path}
        except Exception as e:
            return {"success": False, "error": str(e), "path": remote_path}

    def file_exists(self, remote_path):
        """Check if a file exists on the remote server."""
        try:
            sftp = self._get_sftp()
            sftp.stat(remote_path)
            return True
        except FileNotFoundError:
            return False
        except:
            return False

    def file_delete(self, remote_path):
        """Delete a file on the remote server."""
        try:
            sftp = self._get_sftp()
            sftp.remove(remote_path)
            return {"success": True, "path": remote_path}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def file_list(self, remote_path):
        """List files in a directory on the remote server."""
        try:
            sftp = self._get_sftp()
            items = sftp.listdir_attr(remote_path)
            result = []
            for item in items:
                result.append({
                    "name": item.filename,
                    "size": item.st_size,
                    "is_dir": item.st_mode is not None and (item.st_mode & 0o40000) != 0,
                    "modified": datetime.fromtimestamp(item.st_mtime).isoformat() if item.st_mtime else None
                })
            return {"success": True, "files": result, "path": remote_path}
        except Exception as e:
            return {"success": False, "error": str(e), "path": remote_path}

    def file_append(self, remote_path, content):
        """Append content to a file on the remote server."""
        try:
            sftp = self._get_sftp()
            with sftp.file(remote_path, "a") as f:
                f.write(content)
            return {"success": True, "path": remote_path}
        except Exception as e:
            return {"success": False, "error": str(e)}


class SSHConnectionPool:
    """Pool of SSH connections for reuse."""

    def __init__(self):
        self._connections = {}
        self._lock = threading.Lock()

    def get_connection(self, host, username="root", password=None, port=22, key_path=None):
        import logging as _log
        _log.getLogger("ssh_debug").info(f"[SSH_DEBUG] Connecting to {username}@{host} password_len={len(password or '')}...")  # PATCH 12 bug8: removed password_repr from logs
        """Get or create SSH connection."""
        key = f"{username}@{host}:{port}"
        with self._lock:
            if key in self._connections:
                conn = self._connections[key]
                if conn.is_connected:
                    return conn
                else:
                    conn.disconnect()

            conn = SSHExecutor(host=host, username=username, password=password, port=port, key_path=key_path)
            result = conn.connect()
            if result["success"]:
                self._connections[key] = conn
                return conn
            else:
                raise ConnectionError(f"Failed to connect to {key}: {result['error']}")

    def release_all(self):
        """Close all connections."""
        with self._lock:
            for conn in self._connections.values():
                conn.disconnect()
            self._connections.clear()


# Global connection pool
ssh_pool = SSHConnectionPool()
