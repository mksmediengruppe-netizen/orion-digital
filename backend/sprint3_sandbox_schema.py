"""Sprint 3 Sandbox Tools Schema for ORION."""

SPRINT3_TOOLS_SCHEMA = [
    {
        "type": "function",
        "function": {
            "name": "sandbox_exec",
            "description": (
                "Execute code in an isolated Docker sandbox. "
                "Supports Python, Node.js, Bash. "
                "Use for running untrusted code, testing scripts, "
                "data processing, or any code that needs isolation. "
                "Returns stdout, stderr, exit_code, and any output files."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "code": {
                        "type": "string",
                        "description": "Code to execute in the sandbox"
                    },
                    "language": {
                        "type": "string",
                        "enum": ["python", "node", "javascript", "bash", "sh"],
                        "description": "Programming language (default: python)",
                        "default": "python"
                    },
                    "session_id": {
                        "type": "string",
                        "description": "Optional: reuse existing sandbox session ID"
                    },
                    "files": {
                        "type": "object",
                        "description": "Dict of {filename: content} to write before execution",
                        "additionalProperties": {"type": "string"}
                    },
                    "timeout": {
                        "type": "integer",
                        "description": "Max execution time in seconds (default: 30)",
                        "default": 30
                    },
                    "install_packages": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of pip/npm packages to install before execution"
                    }
                },
                "required": ["code"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "sandbox_create_session",
            "description": (
                "Create a persistent sandbox session for multiple code executions. "
                "Returns a session_id to reuse across multiple sandbox_exec calls. "
                "Use when you need to maintain state between code executions."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "language": {
                        "type": "string",
                        "enum": ["python", "node", "javascript", "bash"],
                        "description": "Primary language for this session",
                        "default": "python"
                    },
                    "packages": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Packages to pre-install in the session"
                    },
                    "session_name": {
                        "type": "string",
                        "description": "Human-readable name for this session"
                    }
                },
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "sandbox_list_sessions",
            "description": "List all active sandbox sessions with their status and metadata.",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "sandbox_destroy_session",
            "description": "Destroy a sandbox session and free resources.",
            "parameters": {
                "type": "object",
                "properties": {
                    "session_id": {
                        "type": "string",
                        "description": "Session ID to destroy"
                    }
                },
                "required": ["session_id"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "runtime_logs",
            "description": (
                "Get runtime logs from a Docker container or system service. "
                "Use to debug running services, check ORION API logs, "
                "or monitor container output."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "container_name": {
                        "type": "string",
                        "description": "Docker container name or ID"
                    },
                    "service": {
                        "type": "string",
                        "description": "System service name (e.g. 'orion-api', 'nginx')"
                    },
                    "lines": {
                        "type": "integer",
                        "description": "Number of log lines to return (default: 100)",
                        "default": 100
                    }
                },
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "docker_run_image",
            "description": (
                "Run a Docker image with custom parameters. "
                "Use for running databases (postgres, redis, mysql), "
                "custom environments, or any Docker-based service."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "image": {
                        "type": "string",
                        "description": "Docker image name (e.g. 'postgres:15', 'redis:7')"
                    },
                    "command": {
                        "type": "string",
                        "description": "Command to run in the container"
                    },
                    "env_vars": {
                        "type": "object",
                        "description": "Environment variables as {KEY: VALUE}",
                        "additionalProperties": {"type": "string"}
                    },
                    "volumes": {
                        "type": "object",
                        "description": "Volume mounts as {host_path: container_path}",
                        "additionalProperties": {"type": "string"}
                    },
                    "ports": {
                        "type": "object",
                        "description": "Port mappings as {host_port: container_port}",
                        "additionalProperties": {"type": "string"}
                    },
                    "detach": {
                        "type": "boolean",
                        "description": "Run in background (default: false)",
                        "default": False
                    },
                    "timeout": {
                        "type": "integer",
                        "description": "Timeout in seconds (default: 60)",
                        "default": 60
                    }
                },
                "required": ["image", "command"]
            }
        }
    }
]
