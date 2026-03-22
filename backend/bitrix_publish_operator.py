"""
Bitrix Publish Operator — Деплой Битрикс-сайта на продакшен.
Загружает шаблон, контент, настраивает домен, SSL, кеш.
Выход: bitrix_deploy_report.json
"""
import json
import logging
import time
from typing import Callable, Optional

logger = logging.getLogger(__name__)


def publish_bitrix(
    ssh_fn: Callable,
    install_path: str = "/var/www/html",
    domain: str = "",
    template_name: str = "",
    html_content: str = "",
    css_content: str = "",
    js_content: str = "",
    images: list = None,
    enable_ssl: bool = True,
    clear_cache: bool = True,
) -> dict:
    """
    Публикует Битрикс-сайт.

    Args:
        ssh_fn: SSH функция
        install_path: Путь установки
        domain: Домен сайта
        template_name: Имя шаблона
        html_content: HTML контент главной страницы
        css_content: CSS стили
        js_content: JavaScript
        images: Список путей к изображениям
        enable_ssl: Настроить SSL
        clear_cache: Очистить кеш

    Returns:
        dict: Отчёт о деплое
    """
    report = {
        "status": "deploying",
        "domain": domain,
        "install_path": install_path,
        "steps": [],
        "errors": [],
        "warnings": [],
    }

    # 1. Upload template if provided
    if template_name and (html_content or css_content):
        _step(report, "upload_template", lambda: _upload_template(
            ssh_fn, install_path, template_name, html_content, css_content, js_content
        ))

    # 2. Upload images
    if images:
        _step(report, "upload_images", lambda: _upload_images(
            ssh_fn, install_path, template_name, images
        ))

    # 3. Create/update index.php
    _step(report, "create_index", lambda: _create_index(ssh_fn, install_path))

    # 4. Configure domain
    if domain:
        _step(report, "configure_domain", lambda: _configure_domain(
            ssh_fn, install_path, domain
        ))

    # 5. Configure web server
    if domain:
        _step(report, "configure_webserver", lambda: _configure_webserver(
            ssh_fn, install_path, domain
        ))

    # 6. SSL certificate
    if enable_ssl and domain:
        _step(report, "setup_ssl", lambda: _setup_ssl(ssh_fn, domain))

    # 7. Clear cache
    if clear_cache:
        _step(report, "clear_cache", lambda: _clear_cache(ssh_fn, install_path))

    # 8. Set permissions
    _step(report, "set_permissions", lambda: ssh_fn(
        f"chown -R www-data:www-data {install_path} && "
        f"find {install_path} -type d -exec chmod 755 {{}} \\; && "
        f"find {install_path} -type f -exec chmod 644 {{}} \\;"
    ))

    # 9. Restart services
    _step(report, "restart_services", lambda: ssh_fn(
        "systemctl restart apache2 2>/dev/null; "
        "systemctl restart nginx 2>/dev/null; "
        "systemctl restart php*-fpm 2>/dev/null; "
        "echo 'RESTARTED'"
    ))

    # 10. Verify
    if domain:
        url = f"https://{domain}" if enable_ssl else f"http://{domain}"
    else:
        url = f"http://localhost"
    _step(report, "verify_deploy", lambda: _verify_deploy(ssh_fn, url))

    errors = [s for s in report["steps"] if not s.get("success")]
    report["status"] = "success" if len(errors) == 0 else "partial" if len(errors) <= 2 else "failed"
    report["url"] = url

    logger.info(f"[BitrixPublishOperator] Deploy {report['status']}: "
                f"{len(report['steps'])} steps, {len(errors)} errors")
    return report


def _step(report, name, fn):
    try:
        result = fn()
        report["steps"].append({"name": name, "success": True, "output": str(result)[:300]})
    except Exception as e:
        report["steps"].append({"name": name, "success": False, "output": str(e)[:300]})
        report["errors"].append(f"{name}: {e}")


def _upload_template(ssh_fn, install_path, template_name, html, css, js):
    tpl_path = f"{install_path}/bitrix/templates/{template_name}"
    ssh_fn(f"mkdir -p {tpl_path}/js {tpl_path}/images {tpl_path}/components")

    if css:
        ssh_fn(f"cat > {tpl_path}/template_styles.css << 'ORION_EOF'\n{css}\nORION_EOF")

    if js:
        ssh_fn(f"cat > {tpl_path}/js/script.js << 'ORION_EOF'\n{js}\nORION_EOF")

    # Split HTML into header/footer
    from bitrix_template_builder import _split_html
    header_php, footer_php = _split_html(html, template_name)
    ssh_fn(f"cat > {tpl_path}/header.php << 'ORION_EOF'\n{header_php}\nORION_EOF")
    ssh_fn(f"cat > {tpl_path}/footer.php << 'ORION_EOF'\n{footer_php}\nORION_EOF")

    return "Template uploaded"


def _upload_images(ssh_fn, install_path, template_name, images):
    tpl_path = f"{install_path}/bitrix/templates/{template_name}/images"
    ssh_fn(f"mkdir -p {tpl_path}")
    uploaded = 0
    for img_path in images:
        try:
            # Assume images are already on server or will be uploaded via SFTP
            ssh_fn(f"test -f {img_path} && cp {img_path} {tpl_path}/ 2>/dev/null")
            uploaded += 1
        except Exception:
            pass
    return f"Uploaded {uploaded}/{len(images)} images"


def _create_index(ssh_fn, install_path):
    index_php = """<?php
require($_SERVER["DOCUMENT_ROOT"]."/bitrix/header.php");
$APPLICATION->SetTitle("Главная");
?>

<?php require($_SERVER["DOCUMENT_ROOT"]."/bitrix/footer.php"); ?>
"""
    ssh_fn(f"cat > {install_path}/index.php << 'ORION_EOF'\n{index_php}\nORION_EOF")
    return "index.php created"


def _configure_domain(ssh_fn, install_path, domain):
    php = (
        f"require_once('{install_path}/bitrix/modules/main/include/prolog_admin_before.php');"
        f"CSite::Update('s1', array('SERVER_NAME' => '{domain}', 'NAME' => '{domain}'));"
        f"echo 'DOMAIN_SET';"
    )
    return str(ssh_fn(f"php -r \"{php}\" 2>/dev/null"))


def _configure_webserver(ssh_fn, install_path, domain):
    # Try nginx first
    nginx_conf = f"""server {{
    listen 80;
    server_name {domain} www.{domain};
    root {install_path};
    index index.php index.html;
    client_max_body_size 64m;

    location / {{ try_files $uri $uri/ /index.php?$args; }}
    location ~ \\.php$ {{
        include snippets/fastcgi-php.conf;
        fastcgi_pass unix:/var/run/php/php8.1-fpm.sock;
    }}
    location ~* \\.(jpg|jpeg|gif|png|svg|js|css|ico|woff2?)$ {{ expires 30d; }}
    location ~ /\\. {{ deny all; }}
}}"""
    ssh_fn(f"cat > /etc/nginx/sites-available/{domain} << 'ORION_EOF'\n{nginx_conf}\nORION_EOF")
    ssh_fn(f"ln -sf /etc/nginx/sites-available/{domain} /etc/nginx/sites-enabled/{domain}")
    ssh_fn("nginx -t 2>&1 && systemctl reload nginx")
    return "Webserver configured"


def _setup_ssl(ssh_fn, domain):
    # Install certbot if needed
    ssh_fn("apt-get install -y certbot python3-certbot-nginx 2>/dev/null")
    result = str(ssh_fn(
        f"certbot --nginx -d {domain} -d www.{domain} --non-interactive --agree-tos "
        f"--email admin@{domain} 2>&1 || echo 'SSL_FAIL'"
    ))
    return result


def _clear_cache(ssh_fn, install_path):
    ssh_fn(f"rm -rf {install_path}/bitrix/cache/* {install_path}/bitrix/managed_cache/* "
           f"{install_path}/bitrix/stack_cache/* 2>/dev/null")
    return "Cache cleared"


def _verify_deploy(ssh_fn, url):
    r = str(ssh_fn(f"curl -sL -o /dev/null -w '%{{http_code}}' '{url}'")).strip()
    return f"HTTP {r}"


def save_report(report: dict, path: str = "bitrix_deploy_report.json"):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    return path
