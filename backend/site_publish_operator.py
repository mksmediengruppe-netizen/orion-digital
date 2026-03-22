"""
Site Publish Operator — Публикует сайт на сервере.
Создаёт директорию, копирует файлы, настраивает nginx + PHP,
подключает домен, HTTPS (certbot), перезапускает сервисы, smoke check.
Выход: publish_report.json с URL
"""
import json
import logging
import os
import time
from typing import Callable, Optional

logger = logging.getLogger(__name__)

# ── Шаблон nginx конфига ─────────────────────────────────────────
NGINX_TEMPLATE = """server {{
    listen 80;
    server_name {server_name};

    root {root_path};
    index index.html index.php;

    # Security headers
    add_header X-Frame-Options "SAMEORIGIN" always;
    add_header X-Content-Type-Options "nosniff" always;
    add_header X-XSS-Protection "1; mode=block" always;

    # Gzip
    gzip on;
    gzip_types text/plain text/css application/json application/javascript text/xml;
    gzip_min_length 256;

    # Static assets cache
    location ~* \\.(jpg|jpeg|png|gif|ico|css|js|svg|woff2?)$ {{
        expires 30d;
        add_header Cache-Control "public, immutable";
    }}

    # PHP
    location ~ \\.php$ {{
        include snippets/fastcgi-php.conf;
        fastcgi_pass unix:/var/run/php/php{php_version}-fpm.sock;
        fastcgi_param SCRIPT_FILENAME $document_root$fastcgi_script_name;
        include fastcgi_params;
    }}

    location / {{
        try_files $uri $uri/ /index.html;
    }}

    # Deny hidden files
    location ~ /\\. {{
        deny all;
    }}
}}
"""


def publish_site(
    build_dir: str,
    target_host: str,
    target_path: str,
    domain: str,
    ssh_fn: Callable,
    scp_fn: Optional[Callable] = None,
    enable_https: bool = True,
    php_version: str = "8.1",
) -> dict:
    """
    Публикует сайт на сервере.
    
    Args:
        build_dir: Локальная директория с файлами сайта
        target_host: IP или хост сервера
        target_path: Путь на сервере (напр. /var/www/html/mysite)
        domain: Домен сайта (для nginx)
        ssh_fn: Функция SSH-выполнения (cmd -> result)
        scp_fn: Функция SCP-копирования (local, remote -> result)
        enable_https: Включить HTTPS через certbot
        php_version: Версия PHP-FPM
    
    Returns:
        dict: publish_report
    """
    report = {
        "status": "publishing",
        "steps": [],
        "url": "",
        "errors": [],
    }
    
    server_name = domain if domain else target_host
    
    # ── 1. Создаём директорию ────────────────────────────────
    step = _run_step("create_directory", f"mkdir -p {target_path}", ssh_fn)
    report["steps"].append(step)
    if not step["success"]:
        report["status"] = "failed"
        report["errors"].append(f"Cannot create directory: {step['output']}")
        return report
    
    # ── 2. Копируем файлы ────────────────────────────────────
    if scp_fn:
        try:
            scp_result = scp_fn(build_dir, target_path)
            report["steps"].append({
                "name": "copy_files",
                "success": True,
                "output": f"Files copied via SCP to {target_path}",
            })
        except Exception as e:
            report["steps"].append({
                "name": "copy_files",
                "success": False,
                "output": str(e),
            })
            report["errors"].append(f"SCP failed: {e}")
    else:
        # Fallback: use tar + ssh
        step = _copy_via_tar(build_dir, target_path, ssh_fn)
        report["steps"].append(step)
        if not step["success"]:
            report["errors"].append(f"File copy failed: {step['output']}")
    
    # ── 3. Устанавливаем права ───────────────────────────────
    chmod_cmds = [
        f"chown -R www-data:www-data {target_path}",
        f"chmod -R 755 {target_path}",
        f"chmod 644 {target_path}/*.html {target_path}/*.css {target_path}/*.js 2>/dev/null || true",
        f"chmod 755 {target_path}/*.php 2>/dev/null || true",
    ]
    for cmd in chmod_cmds:
        step = _run_step("set_permissions", cmd, ssh_fn)
        report["steps"].append(step)
    
    # ── 4. Проверяем PHP-FPM ─────────────────────────────────
    step = _run_step("check_php", f"systemctl is-active php{php_version}-fpm", ssh_fn)
    report["steps"].append(step)
    if not step["success"] or "active" not in step.get("output", ""):
        # Try to install and start PHP-FPM
        install_step = _run_step("install_php", 
            f"apt-get install -y php{php_version}-fpm php{php_version}-common && "
            f"systemctl enable php{php_version}-fpm && systemctl start php{php_version}-fpm",
            ssh_fn)
        report["steps"].append(install_step)
    
    # ── 5. Настраиваем nginx ─────────────────────────────────
    nginx_conf = NGINX_TEMPLATE.format(
        server_name=server_name,
        root_path=target_path,
        php_version=php_version,
    )
    
    conf_name = domain.replace(".", "_") if domain else "site"
    conf_path = f"/etc/nginx/sites-available/{conf_name}"
    enabled_path = f"/etc/nginx/sites-enabled/{conf_name}"
    
    # Write nginx config via SSH
    escaped_conf = nginx_conf.replace("'", "'\\''")
    write_cmd = f"echo '{escaped_conf}' > {conf_path}"
    step = _run_step("write_nginx_config", write_cmd, ssh_fn)
    report["steps"].append(step)
    
    # Enable site
    step = _run_step("enable_site", 
        f"ln -sf {conf_path} {enabled_path}", ssh_fn)
    report["steps"].append(step)
    
    # Test nginx config
    step = _run_step("test_nginx", "nginx -t", ssh_fn)
    report["steps"].append(step)
    if not step["success"]:
        report["errors"].append(f"Nginx config error: {step['output']}")
    
    # Reload nginx
    step = _run_step("reload_nginx", "systemctl reload nginx", ssh_fn)
    report["steps"].append(step)
    
    # ── 6. HTTPS (certbot) ───────────────────────────────────
    if enable_https and domain:
        step = _setup_https(domain, ssh_fn)
        report["steps"].append(step)
        if step["success"]:
            report["url"] = f"https://{domain}"
        else:
            report["url"] = f"http://{domain}"
            report["errors"].append(f"HTTPS setup failed: {step['output']}")
    else:
        report["url"] = f"http://{server_name}"
    
    # ── 7. Smoke check ───────────────────────────────────────
    time.sleep(2)  # Wait for services to settle
    smoke = _smoke_check(report["url"], ssh_fn)
    report["steps"].append(smoke)
    
    if smoke["success"]:
        report["status"] = "published"
        logger.info(f"[PublishOperator] Site published: {report['url']}")
    else:
        report["status"] = "published_with_warnings"
        report["errors"].append(f"Smoke check failed: {smoke['output']}")
        logger.warning(f"[PublishOperator] Published with warnings: {report['url']}")
    
    return report


def _run_step(name: str, cmd: str, ssh_fn: Callable) -> dict:
    """Выполняет шаг через SSH"""
    try:
        result = ssh_fn(cmd)
        output = result if isinstance(result, str) else str(result)
        success = True
        # Check for common error patterns
        if any(err in output.lower() for err in ["error", "failed", "fatal", "permission denied"]):
            if "warning" not in output.lower():
                success = False
        return {"name": name, "command": cmd, "success": success, "output": output[:500]}
    except Exception as e:
        return {"name": name, "command": cmd, "success": False, "output": str(e)[:500]}


def _copy_via_tar(build_dir: str, target_path: str, ssh_fn: Callable) -> dict:
    """Копирует файлы через tar + SSH"""
    try:
        # Create tar archive locally, then extract on remote
        # This is a simplified version - in practice, use paramiko SCP
        files = []
        for root, dirs, filenames in os.walk(build_dir):
            for f in filenames:
                files.append(os.path.join(root, f))
        
        # Use SSH to copy each file (fallback method)
        for filepath in files:
            rel_path = os.path.relpath(filepath, build_dir)
            remote_path = os.path.join(target_path, rel_path)
            remote_dir = os.path.dirname(remote_path)
            
            with open(filepath, "r", encoding="utf-8", errors="replace") as f:
                content = f.read()
            
            ssh_fn(f"mkdir -p {remote_dir}")
            # Use base64 for safe transfer
            import base64
            encoded = base64.b64encode(content.encode()).decode()
            ssh_fn(f"echo '{encoded}' | base64 -d > {remote_path}")
        
        return {
            "name": "copy_files_tar",
            "success": True,
            "output": f"Copied {len(files)} files to {target_path}",
        }
    except Exception as e:
        return {
            "name": "copy_files_tar",
            "success": False,
            "output": str(e),
        }


def _setup_https(domain: str, ssh_fn: Callable) -> dict:
    """Настраивает HTTPS через certbot"""
    try:
        # Check if certbot is installed
        check = ssh_fn("which certbot")
        if "certbot" not in str(check):
            ssh_fn("apt-get install -y certbot python3-certbot-nginx")
        
        # Run certbot
        result = ssh_fn(
            f"certbot --nginx -d {domain} --non-interactive --agree-tos "
            f"--email admin@{domain} --redirect"
        )
        output = str(result)
        success = "congratulations" in output.lower() or "certificate" in output.lower()
        return {"name": "setup_https", "success": success, "output": output[:500]}
    except Exception as e:
        return {"name": "setup_https", "success": False, "output": str(e)[:500]}


def _smoke_check(url: str, ssh_fn: Callable) -> dict:
    """Проверяет доступность сайта"""
    try:
        result = ssh_fn(f"curl -sL -o /dev/null -w '%{{http_code}}' {url}")
        output = str(result).strip()
        status_code = int(output) if output.isdigit() else 0
        success = status_code == 200
        return {
            "name": "smoke_check",
            "success": success,
            "output": f"HTTP {status_code} for {url}",
            "status_code": status_code,
        }
    except Exception as e:
        return {"name": "smoke_check", "success": False, "output": str(e)[:500]}


def save_publish_report(report: dict, path: str = "publish_report.json"):
    """Сохраняет отчёт о публикации"""
    with open(path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    logger.info(f"[PublishOperator] Report saved to {path}")
    return path
