"""
ARCANE SSH Worker
Manages remote servers via SSH for deployment and system administration.

Capabilities:
  - Execute commands on remote servers
  - Upload/download files via SCP/SFTP
  - Deploy websites (static, Node.js, Python)
  - Configure Nginx virtual hosts
  - Set up SSL certificates via Let's Encrypt
  - Manage Docker containers and systemd services
  - Configure DNS records (via Cloudflare API)
"""

from __future__ import annotations

import asyncio
import json
import os
import tempfile
from typing import Optional

from shared.utils.error_analyzer import analyze_error
from shared.utils.logger import get_logger, log_with_data

logger = get_logger("workers.ssh")

NGINX_TEMPLATE = """server {{
    listen 80;
    server_name {domain};

    location / {{
        root {web_root};
        index index.html;
        try_files $uri $uri/ /index.html;
    }}

    location ~* \\.(js|css|png|jpg|jpeg|gif|ico|svg|woff|woff2|ttf|eot)$ {{
        root {web_root};
        expires 30d;
        add_header Cache-Control "public, immutable";
    }}
}}"""

NGINX_PROXY_TEMPLATE = """server {{
    listen 80;
    server_name {domain};

    location / {{
        proxy_pass http://127.0.0.1:{port};
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection 'upgrade';
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_cache_bypass $http_upgrade;
    }}
}}"""


class SSHWorker:
    """
    Manages remote server operations via SSH.
    """

    def __init__(
        self,
        default_host: str = "",
        default_user: str = "root",
        default_key_path: str = "",
        default_password: str = "",
    ):
        self._default_host = default_host
        self._default_user = default_user
        self._default_key_path = default_key_path
        self._default_password = default_password

    async def execute(
        self,
        command: str,
        host: str = None,
        user: str = None,
        timeout: int = 30,
    ) -> dict:
        """Execute a command on a remote server via SSH."""
        host = host or self._default_host
        user = user or self._default_user

        if not host:
            return {"exit_code": -1, "stdout": "", "stderr": "No host specified"}

        ssh_cmd = self._build_ssh_command(host, user, command)

        try:
            proc = await asyncio.create_subprocess_shell(
                ssh_cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)

            return {
                "exit_code": proc.returncode,
                "stdout": stdout.decode("utf-8", errors="replace")[:10000],
                "stderr": stderr.decode("utf-8", errors="replace")[:5000],
            }
        except asyncio.TimeoutError:
            return {"exit_code": -1, "stdout": "", "stderr": f"SSH timeout after {timeout}s"}
        except Exception as e:
            return {"exit_code": -1, "stdout": "", "stderr": str(e)}

    async def upload_directory(
        self,
        local_dir: str,
        remote_dir: str,
        host: str = None,
        user: str = None,
    ) -> dict:
        """Upload a local directory to a remote server via rsync/scp."""
        host = host or self._default_host
        user = user or self._default_user

        # Ensure remote directory exists
        await self.execute(f"mkdir -p {remote_dir}", host=host, user=user)

        # Use rsync for efficient transfer
        ssh_opts = self._build_ssh_options()
        cmd = f"rsync -avz --delete -e 'ssh {ssh_opts}' {local_dir}/ {user}@{host}:{remote_dir}/"

        try:
            proc = await asyncio.create_subprocess_shell(
                cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=120)

            return {
                "success": proc.returncode == 0,
                "stdout": stdout.decode("utf-8", errors="replace"),
                "stderr": stderr.decode("utf-8", errors="replace"),
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def deploy_static_site(
        self,
        local_dir: str,
        domain: str,
        host: str = None,
        user: str = None,
    ) -> dict:
        """
        Deploy a static website to a VPS.
        Steps: upload files → configure Nginx → get SSL → reload Nginx.
        """
        host = host or self._default_host
        user = user or self._default_user
        web_root = f"/var/www/{domain}"
        steps = []

        # Step 1: Upload files
        upload_result = await self.upload_directory(local_dir, web_root, host, user)
        steps.append({"step": "upload", "success": upload_result.get("success", False)})

        if not upload_result.get("success"):
            return {"success": False, "steps": steps, "error": "Upload failed"}

        # Step 2: Set permissions
        await self.execute(f"chown -R www-data:www-data {web_root} && chmod -R 755 {web_root}", host=host, user=user)
        steps.append({"step": "permissions", "success": True})

        # Step 3: Configure Nginx
        nginx_config = NGINX_TEMPLATE.format(domain=domain, web_root=web_root)
        config_path = f"/etc/nginx/sites-available/{domain}"
        enabled_path = f"/etc/nginx/sites-enabled/{domain}"

        # Write config via SSH
        escaped_config = nginx_config.replace("'", "'\\''")
        await self.execute(
            f"echo '{escaped_config}' > {config_path} && ln -sf {config_path} {enabled_path}",
            host=host, user=user,
        )
        steps.append({"step": "nginx_config", "success": True})

        # Step 4: Test Nginx config
        test_result = await self.execute("nginx -t", host=host, user=user)
        nginx_ok = test_result["exit_code"] == 0
        steps.append({"step": "nginx_test", "success": nginx_ok})

        if not nginx_ok:
            return {"success": False, "steps": steps, "error": test_result["stderr"]}

        # Step 5: Reload Nginx
        await self.execute("systemctl reload nginx", host=host, user=user)
        steps.append({"step": "nginx_reload", "success": True})

        # Step 6: SSL via Certbot
        ssl_result = await self.execute(
            f"certbot --nginx -d {domain} --non-interactive --agree-tos --email admin@{domain} 2>&1 || true",
            host=host, user=user, timeout=60,
        )
        ssl_ok = "successfully" in ssl_result.get("stdout", "").lower() or "certificate" in ssl_result.get("stdout", "").lower()
        steps.append({"step": "ssl", "success": ssl_ok})

        return {
            "success": True,
            "url": f"https://{domain}" if ssl_ok else f"http://{domain}",
            "steps": steps,
            "web_root": web_root,
        }

    async def deploy_nodejs_app(
        self,
        local_dir: str,
        domain: str,
        port: int = 3000,
        host: str = None,
        user: str = None,
    ) -> dict:
        """Deploy a Node.js application with PM2 and Nginx reverse proxy."""
        host = host or self._default_host
        user = user or self._default_user
        app_dir = f"/var/www/{domain}"
        steps = []

        # Upload files
        upload_result = await self.upload_directory(local_dir, app_dir, host, user)
        steps.append({"step": "upload", "success": upload_result.get("success", False)})

        # Install dependencies
        install_result = await self.execute(
            f"cd {app_dir} && npm install --production",
            host=host, user=user, timeout=120,
        )
        steps.append({"step": "npm_install", "success": install_result["exit_code"] == 0})

        # Start with PM2
        await self.execute(f"pm2 delete {domain} 2>/dev/null || true", host=host, user=user)
        pm2_result = await self.execute(
            f"cd {app_dir} && PORT={port} pm2 start npm --name {domain} -- start",
            host=host, user=user,
        )
        steps.append({"step": "pm2_start", "success": pm2_result["exit_code"] == 0})

        # Save PM2 config
        await self.execute("pm2 save", host=host, user=user)

        # Configure Nginx reverse proxy
        nginx_config = NGINX_PROXY_TEMPLATE.format(domain=domain, port=port)
        config_path = f"/etc/nginx/sites-available/{domain}"
        enabled_path = f"/etc/nginx/sites-enabled/{domain}"

        escaped_config = nginx_config.replace("'", "'\\''")
        await self.execute(
            f"echo '{escaped_config}' > {config_path} && ln -sf {config_path} {enabled_path}",
            host=host, user=user,
        )

        # Test and reload Nginx
        test_result = await self.execute("nginx -t && systemctl reload nginx", host=host, user=user)
        steps.append({"step": "nginx", "success": test_result["exit_code"] == 0})

        # SSL
        await self.execute(
            f"certbot --nginx -d {domain} --non-interactive --agree-tos --email admin@{domain} 2>&1 || true",
            host=host, user=user, timeout=60,
        )

        return {
            "success": all(s["success"] for s in steps),
            "url": f"https://{domain}",
            "steps": steps,
            "port": port,
        }

    async def deploy_python_app(
        self,
        local_dir: str,
        domain: str,
        port: int = 8000,
        host: str = None,
        user: str = None,
    ) -> dict:
        """Deploy a Python (FastAPI/Flask) application with Gunicorn and Nginx."""
        host = host or self._default_host
        user = user or self._default_user
        app_dir = f"/var/www/{domain}"
        steps = []

        # Upload files
        upload_result = await self.upload_directory(local_dir, app_dir, host, user)
        steps.append({"step": "upload", "success": upload_result.get("success", False)})

        # Create virtualenv and install
        install_result = await self.execute(
            f"cd {app_dir} && python3 -m venv venv && source venv/bin/activate && pip install -r requirements.txt gunicorn uvicorn",
            host=host, user=user, timeout=120,
        )
        steps.append({"step": "pip_install", "success": install_result["exit_code"] == 0})

        # Create systemd service
        service_content = f"""[Unit]
Description={domain} ARCANE App
After=network.target

[Service]
User=www-data
Group=www-data
WorkingDirectory={app_dir}
ExecStart={app_dir}/venv/bin/gunicorn -w 4 -k uvicorn.workers.UvicornWorker -b 127.0.0.1:{port} app:app
Restart=always
Environment=PATH={app_dir}/venv/bin

[Install]
WantedBy=multi-user.target"""

        service_name = domain.replace(".", "-")
        escaped = service_content.replace("'", "'\\''")
        await self.execute(
            f"echo '{escaped}' > /etc/systemd/system/{service_name}.service",
            host=host, user=user,
        )

        # Start service
        await self.execute(
            f"systemctl daemon-reload && systemctl enable {service_name} && systemctl restart {service_name}",
            host=host, user=user,
        )
        steps.append({"step": "systemd", "success": True})

        # Nginx reverse proxy
        nginx_config = NGINX_PROXY_TEMPLATE.format(domain=domain, port=port)
        config_path = f"/etc/nginx/sites-available/{domain}"
        enabled_path = f"/etc/nginx/sites-enabled/{domain}"

        escaped_config = nginx_config.replace("'", "'\\''")
        await self.execute(
            f"echo '{escaped_config}' > {config_path} && ln -sf {config_path} {enabled_path} && nginx -t && systemctl reload nginx",
            host=host, user=user,
        )
        steps.append({"step": "nginx", "success": True})

        return {
            "success": True,
            "url": f"https://{domain}",
            "steps": steps,
            "port": port,
        }

    def _build_ssh_command(self, host: str, user: str, command: str) -> str:
        """Build SSH command with proper options."""
        opts = self._build_ssh_options()
        escaped_command = command.replace("'", "'\\''")
        if self._default_password:
            return f"sshpass -p '{self._default_password}' ssh {opts} {user}@{host} '{escaped_command}'"
        return f"ssh {opts} {user}@{host} '{escaped_command}'"

    def _build_ssh_options(self) -> str:
        """Build SSH options string."""
        opts = "-o StrictHostKeyChecking=no -o ConnectTimeout=10"
        if self._default_key_path:
            opts += f" -i {self._default_key_path}"
        return opts
