"""
Bitrix Reverse Engineer — Анализ существующего Битрикс-сайта.
Извлекает: шаблон, компоненты, инфоблоки, модули, настройки.
Выход: bitrix_analysis.json
"""
import json
import logging
import re
import time
from typing import Callable, Optional

logger = logging.getLogger(__name__)


def analyze_bitrix_site(
    ssh_fn: Callable,
    install_path: str = "/var/www/html",
    url: str = "",
) -> dict:
    """
    Полный анализ существующего Битрикс-сайта.

    Args:
        ssh_fn: SSH функция
        install_path: Путь установки
        url: URL сайта

    Returns:
        dict: Полный анализ сайта
    """
    analysis = {
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "install_path": install_path,
        "url": url,
        "version": _get_version(ssh_fn, install_path),
        "edition": _get_edition(ssh_fn, install_path),
        "template": _analyze_template(ssh_fn, install_path),
        "modules": _list_modules(ssh_fn, install_path),
        "iblocks": _list_iblocks(ssh_fn, install_path),
        "components_used": _find_components(ssh_fn, install_path),
        "web_forms": _list_web_forms(ssh_fn, install_path),
        "pages": _list_pages(ssh_fn, install_path),
        "settings": _analyze_settings(ssh_fn, install_path),
        "database": _analyze_database(ssh_fn, install_path),
        "custom_code": _find_custom_code(ssh_fn, install_path),
        "file_stats": _file_stats(ssh_fn, install_path),
    }

    logger.info(f"[BitrixReverseEngineer] Analysis complete: "
                f"v{analysis['version']}, {analysis['edition']}, "
                f"{len(analysis['modules'])} modules, "
                f"{len(analysis['iblocks'])} iblocks")
    return analysis


def _get_version(ssh_fn, path):
    try:
        r = str(ssh_fn(f"grep 'SM_VERSION' {path}/bitrix/modules/main/classes/general/version.php 2>/dev/null"))
        match = re.search(r"'(\d+\.\d+\.\d+)'", r)
        return match.group(1) if match else "unknown"
    except Exception:
        return "unknown"


def _get_edition(ssh_fn, path):
    try:
        r = str(ssh_fn(f"grep -i 'edition' {path}/bitrix/.settings.php 2>/dev/null | head -3"))
        if "business" in r.lower():
            return "business"
        elif "standard" in r.lower():
            return "standard"
        elif "start" in r.lower():
            return "start"
        # Try by installed modules
        r2 = str(ssh_fn(f"ls {path}/bitrix/modules/ | wc -l"))
        count = int(r2.strip()) if r2.strip().isdigit() else 0
        if count > 40:
            return "business"
        elif count > 25:
            return "standard"
        return "start"
    except Exception:
        return "unknown"


def _analyze_template(ssh_fn, path):
    try:
        templates = str(ssh_fn(f"ls -1 {path}/bitrix/templates/ 2>/dev/null | grep -v '^\\.'"
                                )).strip().split("\n")
        templates = [t.strip() for t in templates if t.strip()]

        active = "unknown"
        r = str(ssh_fn(f"grep -r 'TEMPLATE' {path}/bitrix/.settings.php 2>/dev/null | head -3"))
        for t in templates:
            if t in r and t != ".default":
                active = t
                break

        template_info = {
            "available": templates,
            "active": active,
            "files": {},
        }

        if active != "unknown":
            tpl_path = f"{path}/bitrix/templates/{active}"
            for f in ["header.php", "footer.php", "template_styles.css", "description.php"]:
                check = str(ssh_fn(f"test -f {tpl_path}/{f} && wc -l {tpl_path}/{f} | awk '{{print $1}}' || echo '0'"))
                template_info["files"][f] = int(check.strip()) if check.strip().isdigit() else 0

        return template_info
    except Exception as e:
        return {"error": str(e)}


def _list_modules(ssh_fn, path):
    try:
        r = str(ssh_fn(f"ls -1 {path}/bitrix/modules/ 2>/dev/null | grep -v '^\\.'"
                        )).strip().split("\n")
        return [m.strip() for m in r if m.strip()]
    except Exception:
        return []


def _list_iblocks(ssh_fn, path):
    try:
        php = (
            f"require_once('{path}/bitrix/modules/main/include/prolog_before.php');"
            f"CModule::IncludeModule('iblock');"
            f"$rs = CIBlock::GetList(array('SORT'=>'ASC'), array());"
            f"$result = array();"
            f"while($ar = $rs->Fetch()) $result[] = array('ID'=>$ar['ID'],'NAME'=>$ar['NAME'],'TYPE'=>$ar['IBLOCK_TYPE_ID']);"
            f"echo json_encode($result, JSON_UNESCAPED_UNICODE);"
        )
        r = str(ssh_fn(f"php -r \"{php}\" 2>/dev/null"))
        match = re.search(r'\[.*\]', r, re.S)
        if match:
            return json.loads(match.group())
    except Exception:
        pass
    return []


def _find_components(ssh_fn, path):
    try:
        r = str(ssh_fn(
            f"grep -roh 'IncludeComponent(\"[^\"]*\"' {path}/*.php {path}/bitrix/templates/*/header.php "
            f"{path}/bitrix/templates/*/footer.php 2>/dev/null | sort -u | head -30"
        ))
        components = re.findall(r'IncludeComponent\("([^"]+)"', r)
        return list(set(components))
    except Exception:
        return []


def _list_web_forms(ssh_fn, path):
    try:
        php = (
            f"require_once('{path}/bitrix/modules/main/include/prolog_before.php');"
            f"if(CModule::IncludeModule('form'))"
            f"{{$rs = CForm::GetList($by='s_id',$order='asc',array(),false);"
            f"$result=array();"
            f"while($ar=$rs->Fetch()) $result[]=array('ID'=>$ar['ID'],'NAME'=>$ar['NAME'],'SID'=>$ar['SID']);"
            f"echo json_encode($result, JSON_UNESCAPED_UNICODE);}}"
            f"else echo '[]';"
        )
        r = str(ssh_fn(f"php -r \"{php}\" 2>/dev/null"))
        match = re.search(r'\[.*\]', r, re.S)
        if match:
            return json.loads(match.group())
    except Exception:
        pass
    return []


def _list_pages(ssh_fn, path):
    try:
        r = str(ssh_fn(
            f"find {path} -maxdepth 2 -name '*.php' -not -path '*/bitrix/*' "
            f"-not -path '*/upload/*' 2>/dev/null | head -30"
        ))
        pages = [p.strip().replace(path, "") for p in r.split("\n") if p.strip()]
        return pages
    except Exception:
        return []


def _analyze_settings(ssh_fn, path):
    try:
        r = str(ssh_fn(f"php -r \"var_export(include '{path}/bitrix/.settings.php');\" 2>/dev/null"))
        settings = {}
        if "connections" in r:
            settings["has_connections"] = True
        if "cache" in r:
            settings["has_cache_config"] = True
        if "exception_handling" in r:
            settings["has_exception_handling"] = True
        settings["file_size"] = str(ssh_fn(f"wc -c {path}/bitrix/.settings.php 2>/dev/null | awk '{{print $1}}'")).strip()
        return settings
    except Exception as e:
        return {"error": str(e)}


def _analyze_database(ssh_fn, path):
    try:
        r = str(ssh_fn(
            f"grep -E 'DBHost|DBName|DBLogin' {path}/bitrix/php_interface/dbconn.php 2>/dev/null"
        ))
        db_info = {}
        for var in ["DBHost", "DBName", "DBLogin"]:
            match = re.search(rf'\${var}\s*=\s*["\']([^"\']+)["\']', r)
            if match:
                db_info[var] = match.group(1)

        # Table count
        if "DBName" in db_info:
            tc = str(ssh_fn(
                f"mysql -N -e \"SELECT COUNT(*) FROM information_schema.tables "
                f"WHERE table_schema='{db_info['DBName']}'\" 2>/dev/null"
            )).strip()
            db_info["table_count"] = int(tc) if tc.isdigit() else 0

        return db_info
    except Exception as e:
        return {"error": str(e)}


def _find_custom_code(ssh_fn, path):
    try:
        custom = {}
        # init.php
        r = str(ssh_fn(f"wc -l {path}/bitrix/php_interface/init.php 2>/dev/null | awk '{{print $1}}'")).strip()
        custom["init_php_lines"] = int(r) if r.isdigit() else 0

        # Custom components
        r = str(ssh_fn(f"find {path}/bitrix/components/custom/ -name 'class.php' 2>/dev/null | wc -l")).strip()
        custom["custom_components"] = int(r) if r.isdigit() else 0

        # Local modules
        r = str(ssh_fn(f"ls {path}/local/modules/ 2>/dev/null | wc -l")).strip()
        custom["local_modules"] = int(r) if r.isdigit() else 0

        return custom
    except Exception as e:
        return {"error": str(e)}


def _file_stats(ssh_fn, path):
    try:
        total = str(ssh_fn(f"du -sh {path} 2>/dev/null | awk '{{print $1}}'")).strip()
        upload = str(ssh_fn(f"du -sh {path}/upload 2>/dev/null | awk '{{print $1}}'")).strip()
        cache = str(ssh_fn(f"du -sh {path}/bitrix/cache 2>/dev/null | awk '{{print $1}}'")).strip()
        return {"total_size": total, "upload_size": upload, "cache_size": cache}
    except Exception:
        return {}


def save_analysis(analysis: dict, path: str = "bitrix_analysis.json"):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(analysis, f, ensure_ascii=False, indent=2)
    return path
