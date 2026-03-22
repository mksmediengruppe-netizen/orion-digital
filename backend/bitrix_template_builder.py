"""
Bitrix Template Builder — Создаёт шаблон Битрикс из HTML/CSS.
Генерирует header.php, footer.php, template_styles.css, .styles.php.
Выход: template_report.json + файлы шаблона на сервере.
"""
import json
import logging
import re
import time
from typing import Callable, Optional

logger = logging.getLogger(__name__)

TEMPLATE_STRUCTURE = {
    "header.php": "Шапка сайта (до $APPLICATION->ShowPanel())",
    "footer.php": "Подвал сайта (после контента)",
    "template_styles.css": "CSS стили шаблона",
    "styles.css": "Дополнительные стили",
    ".styles.php": "Визуальные стили для редактора",
    "description.php": "Описание шаблона",
    "components/": "Кастомизированные компоненты",
    "images/": "Изображения шаблона",
    "js/": "JavaScript файлы",
}


def build_template(
    ssh_fn: Callable,
    template_name: str,
    html_content: str,
    css_content: str = "",
    js_content: str = "",
    install_path: str = "/var/www/html",
    site_name: str = "Новый сайт",
    description: str = "Шаблон создан через ORION",
) -> dict:
    """
    Создаёт шаблон Битрикс из HTML/CSS.

    Args:
        ssh_fn: SSH функция
        template_name: Имя шаблона (slug)
        html_content: Полный HTML лендинга/сайта
        css_content: CSS стили
        js_content: JavaScript
        install_path: Путь установки Битрикс
        site_name: Название сайта
        description: Описание шаблона

    Returns:
        dict: Отчёт о создании шаблона
    """
    report = {
        "template_name": template_name,
        "status": "building",
        "files_created": [],
        "errors": [],
    }

    tpl_path = f"{install_path}/bitrix/templates/{template_name}"

    # 1. Create template directory structure
    dirs = [tpl_path, f"{tpl_path}/components", f"{tpl_path}/images", f"{tpl_path}/js"]
    for d in dirs:
        ssh_fn(f"mkdir -p {d}")

    # 2. Split HTML into header and footer
    header_php, footer_php = _split_html(html_content, site_name)

    # 3. Extract CSS from HTML if not provided separately
    if not css_content:
        css_content = _extract_css(html_content)

    # 4. Write header.php
    _write_file(ssh_fn, f"{tpl_path}/header.php", header_php, report)

    # 5. Write footer.php
    _write_file(ssh_fn, f"{tpl_path}/footer.php", footer_php, report)

    # 6. Write template_styles.css
    _write_file(ssh_fn, f"{tpl_path}/template_styles.css", css_content, report)

    # 7. Write styles.css (empty or with overrides)
    _write_file(ssh_fn, f"{tpl_path}/styles.css", "/* Custom overrides */\n", report)

    # 8. Write description.php
    desc_php = f"""<?php
if (!defined("B_PROLOG_INCLUDED") || B_PROLOG_INCLUDED !== true) die();
$arTemplate = array(
    "NAME" => "{template_name}",
    "DESCRIPTION" => "{description}",
    "SORT" => 100,
    "TYPE" => "D",
);
"""
    _write_file(ssh_fn, f"{tpl_path}/description.php", desc_php, report)

    # 9. Write .styles.php
    styles_php = """<?php
if (!defined("B_PROLOG_INCLUDED") || B_PROLOG_INCLUDED !== true) die();
// Visual editor styles
$arStyles = array();
$arTemplateParameters = array();
"""
    _write_file(ssh_fn, f"{tpl_path}/.styles.php", styles_php, report)

    # 10. Write JS
    if js_content:
        _write_file(ssh_fn, f"{tpl_path}/js/script.js", js_content, report)

    # 11. Set permissions
    ssh_fn(f"chown -R www-data:www-data {tpl_path}")
    ssh_fn(f"chmod -R 755 {tpl_path}")

    # 12. Set as active template
    _activate_template(ssh_fn, install_path, template_name)

    # Verify
    check = str(ssh_fn(f"test -f {tpl_path}/header.php && test -f {tpl_path}/footer.php && echo 'OK' || echo 'FAIL'"))
    report["status"] = "success" if "OK" in check else "partial"
    report["template_path"] = tpl_path

    logger.info(f"[BitrixTemplateBuilder] Template '{template_name}' "
                f"{'created' if report['status'] == 'success' else 'partially created'}: "
                f"{len(report['files_created'])} files")
    return report


def _split_html(html, site_name):
    """Разделяет HTML на header.php и footer.php для Битрикс."""
    # Find the main content area (usually after header/nav, before footer)
    header_end = None
    footer_start = None

    # Try to find <main> or content div
    main_match = re.search(r'(<main[^>]*>)', html, re.I)
    if main_match:
        header_end = main_match.end()

    main_close = re.search(r'(</main>)', html, re.I)
    if main_close:
        footer_start = main_close.start()

    if not header_end:
        # Fallback: split after </header> or </nav>
        for tag in ['</header>', '</nav>']:
            match = re.search(re.escape(tag), html, re.I)
            if match:
                header_end = match.end()
                break

    if not footer_start:
        # Fallback: split before <footer>
        match = re.search(r'<footer', html, re.I)
        if match:
            footer_start = match.start()

    if not header_end:
        header_end = len(html) // 2
    if not footer_start:
        footer_start = header_end

    header_html = html[:header_end]
    footer_html = html[footer_start:]

    # Convert to Bitrix template format
    header_php = f"""<?php
if (!defined("B_PROLOG_INCLUDED") || B_PROLOG_INCLUDED !== true) die();
?>
<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title><?php $APPLICATION->ShowTitle(); ?> - {site_name}</title>
    <?php $APPLICATION->ShowHead(); ?>
    <link rel="stylesheet" href="<?=SITE_TEMPLATE_PATH?>/template_styles.css">
</head>
<body>
    <div id="panel"><?php $APPLICATION->ShowPanel(); ?></div>
{_indent(_extract_body_content(header_html), 4)}
    <main id="content">
"""

    footer_php = f"""    </main>
{_indent(_extract_body_content(footer_html), 4)}
    <script src="<?=SITE_TEMPLATE_PATH?>/js/script.js"></script>
</body>
</html>
"""
    return header_php, footer_php


def _extract_body_content(html):
    """Извлекает содержимое body."""
    body_match = re.search(r'<body[^>]*>(.*)', html, re.S | re.I)
    if body_match:
        content = body_match.group(1)
        content = re.sub(r'</body>.*', '', content, flags=re.S | re.I)
        return content.strip()
    # Remove head/html tags
    content = re.sub(r'<(!DOCTYPE|html|head).*?>', '', html, flags=re.S | re.I)
    content = re.sub(r'</?(html|head|body)>', '', content, flags=re.I)
    return content.strip()


def _extract_css(html):
    """Извлекает CSS из HTML."""
    styles = re.findall(r'<style[^>]*>(.*?)</style>', html, re.S | re.I)
    return "\n\n".join(styles) if styles else "/* No inline styles found */\n"


def _indent(text, spaces):
    """Добавляет отступы."""
    prefix = " " * spaces
    return "\n".join(prefix + line if line.strip() else line for line in text.split("\n"))


def _write_file(ssh_fn, path, content, report):
    """Записывает файл через SSH."""
    try:
        # Escape content for heredoc
        escaped = content.replace("'", "'\\''")
        ssh_fn(f"cat > {path} << 'ORION_EOF'\n{content}\nORION_EOF")
        report["files_created"].append(path)
    except Exception as e:
        report["errors"].append(f"Failed to write {path}: {e}")


def _activate_template(ssh_fn, install_path, template_name):
    """Активирует шаблон в настройках сайта."""
    try:
        # Update via PHP
        php_code = f"""
require_once('{install_path}/bitrix/modules/main/include/prolog_admin_before.php');
CSite::Update('s1', array('TEMPLATE' => array(array('TEMPLATE' => '{template_name}', 'SORT' => 1, 'CONDITION' => ''))));
echo 'TEMPLATE_SET';
"""
        ssh_fn(f"php -r \"{php_code}\" 2>/dev/null")
    except Exception as e:
        logger.warning(f"[BitrixTemplateBuilder] Could not auto-activate template: {e}")


def save_report(report: dict, path: str = "template_report.json"):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    return path
