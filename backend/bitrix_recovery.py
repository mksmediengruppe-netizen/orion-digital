"""
Bitrix Recovery — Восстановление и откат Битрикс-сайта.
Бэкап БД, файлов, откат шаблона, восстановление из snapshot.
Выход: recovery_report.json
"""
import json
import logging
import re
import time
from typing import Callable, Optional

logger = logging.getLogger(__name__)


def create_backup(
    ssh_fn: Callable,
    install_path: str = "/var/www/html",
    backup_dir: str = "/root/backups",
    include_db: bool = True,
    include_files: bool = True,
    label: str = "",
) -> dict:
    """
    Создаёт бэкап Битрикс-сайта.

    Args:
        ssh_fn: SSH функция
        install_path: Путь установки
        backup_dir: Директория для бэкапов
        include_db: Включить БД
        include_files: Включить файлы
        label: Метка бэкапа

    Returns:
        dict: Отчёт о бэкапе
    """
    timestamp = time.strftime("%Y%m%d_%H%M%S")
    if not label:
        label = f"backup_{timestamp}"

    report = {
        "label": label,
        "timestamp": timestamp,
        "status": "creating",
        "files": {},
        "errors": [],
    }

    ssh_fn(f"mkdir -p {backup_dir}")

    # 1. Backup database
    if include_db:
        try:
            db_info = _get_db_credentials(ssh_fn, install_path)
            db_file = f"{backup_dir}/{label}_db.sql.gz"
            cmd = (
                f"mysqldump -h {db_info['host']} -u {db_info['user']} "
                f"-p'{db_info['password']}' {db_info['name']} 2>/dev/null | gzip > {db_file}"
            )
            ssh_fn(cmd)
            size = str(ssh_fn(f"du -sh {db_file} 2>/dev/null | awk '{{print $1}}'")).strip()
            report["files"]["database"] = {"path": db_file, "size": size}
        except Exception as e:
            report["errors"].append(f"DB backup failed: {e}")

    # 2. Backup files
    if include_files:
        try:
            files_archive = f"{backup_dir}/{label}_files.tar.gz"
            ssh_fn(
                f"tar czf {files_archive} "
                f"--exclude='{install_path}/bitrix/cache' "
                f"--exclude='{install_path}/bitrix/managed_cache' "
                f"--exclude='{install_path}/bitrix/stack_cache' "
                f"-C / {install_path.lstrip('/')} 2>/dev/null"
            )
            size = str(ssh_fn(f"du -sh {files_archive} 2>/dev/null | awk '{{print $1}}'")).strip()
            report["files"]["files"] = {"path": files_archive, "size": size}
        except Exception as e:
            report["errors"].append(f"Files backup failed: {e}")

    # 3. Save metadata
    meta = {
        "label": label,
        "timestamp": timestamp,
        "install_path": install_path,
        "files": report["files"],
    }
    meta_path = f"{backup_dir}/{label}_meta.json"
    ssh_fn(f"cat > {meta_path} << 'ORION_EOF'\n{json.dumps(meta, ensure_ascii=False, indent=2)}\nORION_EOF")

    report["status"] = "success" if len(report["errors"]) == 0 else "partial"
    report["meta_path"] = meta_path

    logger.info(f"[BitrixRecovery] Backup '{label}' {report['status']}")
    return report


def restore_backup(
    ssh_fn: Callable,
    backup_dir: str = "/root/backups",
    label: str = "",
    restore_db: bool = True,
    restore_files: bool = True,
) -> dict:
    """
    Восстанавливает Битрикс из бэкапа.

    Args:
        ssh_fn: SSH функция
        backup_dir: Директория бэкапов
        label: Метка бэкапа
        restore_db: Восстановить БД
        restore_files: Восстановить файлы

    Returns:
        dict: Отчёт о восстановлении
    """
    report = {"label": label, "status": "restoring", "steps": [], "errors": []}

    # Load metadata
    meta_path = f"{backup_dir}/{label}_meta.json"
    try:
        meta_raw = str(ssh_fn(f"cat {meta_path} 2>/dev/null"))
        meta = json.loads(re.search(r'\{.*\}', meta_raw, re.S).group())
    except Exception as e:
        report["status"] = "failed"
        report["errors"].append(f"Cannot read backup metadata: {e}")
        return report

    install_path = meta.get("install_path", "/var/www/html")

    # 1. Stop services
    ssh_fn("systemctl stop apache2 2>/dev/null; systemctl stop nginx 2>/dev/null")
    report["steps"].append("services_stopped")

    # 2. Restore files
    if restore_files:
        files_archive = meta.get("files", {}).get("files", {}).get("path", "")
        if files_archive:
            try:
                ssh_fn(f"tar xzf {files_archive} -C / 2>/dev/null")
                report["steps"].append("files_restored")
            except Exception as e:
                report["errors"].append(f"Files restore failed: {e}")

    # 3. Restore database
    if restore_db:
        db_file = meta.get("files", {}).get("database", {}).get("path", "")
        if db_file:
            try:
                db_info = _get_db_credentials(ssh_fn, install_path)
                ssh_fn(
                    f"gunzip -c {db_file} | mysql -h {db_info['host']} "
                    f"-u {db_info['user']} -p'{db_info['password']}' {db_info['name']} 2>/dev/null"
                )
                report["steps"].append("database_restored")
            except Exception as e:
                report["errors"].append(f"DB restore failed: {e}")

    # 4. Fix permissions
    ssh_fn(f"chown -R www-data:www-data {install_path}")
    report["steps"].append("permissions_fixed")

    # 5. Clear cache
    ssh_fn(f"rm -rf {install_path}/bitrix/cache/* {install_path}/bitrix/managed_cache/* 2>/dev/null")
    report["steps"].append("cache_cleared")

    # 6. Restart services
    ssh_fn("systemctl start apache2 2>/dev/null; systemctl start nginx 2>/dev/null")
    report["steps"].append("services_started")

    report["status"] = "success" if len(report["errors"]) == 0 else "partial"
    logger.info(f"[BitrixRecovery] Restore '{label}' {report['status']}")
    return report


def list_backups(ssh_fn: Callable, backup_dir: str = "/root/backups") -> list:
    """Список доступных бэкапов."""
    try:
        r = str(ssh_fn(f"ls -1 {backup_dir}/*_meta.json 2>/dev/null"))
        files = [f.strip() for f in r.split("\n") if f.strip()]
        backups = []
        for f in files:
            try:
                raw = str(ssh_fn(f"cat {f}"))
                meta = json.loads(re.search(r'\{.*\}', raw, re.S).group())
                backups.append(meta)
            except Exception:
                pass
        return sorted(backups, key=lambda x: x.get("timestamp", ""), reverse=True)
    except Exception:
        return []


def rollback_template(
    ssh_fn: Callable,
    install_path: str = "/var/www/html",
    template_name: str = ".default",
) -> dict:
    """Откатывает шаблон на стандартный."""
    try:
        php = (
            f"require_once('{install_path}/bitrix/modules/main/include/prolog_admin_before.php');"
            f"CSite::Update('s1', array('TEMPLATE' => array(array("
            f"'TEMPLATE' => '{template_name}', 'SORT' => 1, 'CONDITION' => ''))));"
            f"echo 'ROLLBACK_OK';"
        )
        r = str(ssh_fn(f"php -r \"{php}\" 2>/dev/null"))
        ok = "ROLLBACK_OK" in r
        return {"status": "success" if ok else "failed", "template": template_name}
    except Exception as e:
        return {"status": "failed", "error": str(e)}


def cleanup_old_backups(
    ssh_fn: Callable,
    backup_dir: str = "/root/backups",
    keep_last: int = 5,
) -> dict:
    """Удаляет старые бэкапы, оставляя последние N."""
    backups = list_backups(ssh_fn, backup_dir)
    if len(backups) <= keep_last:
        return {"deleted": 0, "kept": len(backups)}

    to_delete = backups[keep_last:]
    deleted = 0
    for b in to_delete:
        label = b.get("label", "")
        if label:
            ssh_fn(f"rm -f {backup_dir}/{label}_* 2>/dev/null")
            deleted += 1

    return {"deleted": deleted, "kept": keep_last}


def _get_db_credentials(ssh_fn, install_path):
    """Извлекает учётные данные БД из dbconn.php."""
    r = str(ssh_fn(f"cat {install_path}/bitrix/php_interface/dbconn.php 2>/dev/null"))
    creds = {"host": "localhost", "user": "root", "password": "", "name": "bitrix"}
    for var, key in [("DBHost", "host"), ("DBLogin", "user"), ("DBPassword", "password"), ("DBName", "name")]:
        match = re.search(rf'\${var}\s*=\s*["\']([^"\']*)["\']', r)
        if match:
            creds[key] = match.group(1)
    return creds


def save_report(report: dict, path: str = "recovery_report.json"):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    return path
