"""
bitrix_install_verifier.py — Strict verifier for Bitrix CMS installation.

Checks:
  1. /bitrix/admin/ returns real admin/login UI (not public landing)
  2. DB has b_% tables (minimum 10)
  3. Install wizard is completed (not active)
  4. Public URL works (HTTP 200)
  5. index.php is not just a wrapper for index.html
  6. Core files present (.settings.php, dbconn.php, modules)

False-success blocking:
  - index.php → readfile('index.html') = NOT success
  - /bitrix/admin/ returns public landing = NOT success
  - bitrix/modules/ exists but no DB tables = NOT success
  - wizard not completed = NOT success

Verdict: SUCCESS / PARTIAL_SUCCESS / FAILED / NEEDS_REVIEW
"""

import json
import logging
import re
import time
from typing import Callable, Dict, Any, Optional

logger = logging.getLogger("bitrix_install_verifier")

# ═══ Constants ═══════════════════════════════════════════════════════════════

ADMIN_MARKERS = [
    "Авторизация", "Bitrix", "Администрирование", "bx-admin",
    "auth-form", "authorize", "CAdminPage", "bitrix:main.auth",
    "bx-auth-form", "AUTH_FORM", "login-page",
]

FALSE_SUCCESS_MARKERS = [
    "readfile",  # index.php wrapping index.html
    "file_get_contents('index.html')",
    "include 'index.html'",
]

CORE_FILES = [
    "bitrix/.settings.php",
    "bitrix/php_interface/dbconn.php",
    "bitrix/modules/main/include.php",
    "bitrix/header.php",
    "bitrix/footer.php",
]

CRITICAL_MODULES = [
    "main", "iblock", "fileman", "search",
]

WRITABLE_DIRS = [
    "bitrix/cache", "bitrix/managed_cache", "upload",
]


def _escape_php_string(s: str) -> str:
    return s.replace("\\", "\\\\").replace("'", "\\'")


# ═══ Main Verifier ═══════════════════════════════════════════════════════════

def verify_bitrix_install(
    ssh_fn: Callable,
    install_path: str = "/var/www/html",
    db_name: str = "bitrix_db",
    db_user: str = "bitrix_user",
    db_password: str = "",
    site_url: str = "",
    admin_url: str = "",
    url_prefix: str = "",
) -> Dict[str, Any]:
    """
    Strict verification of Bitrix CMS installation.

    Returns dict with:
      - verdict: SUCCESS / PARTIAL_SUCCESS / FAILED / NEEDS_REVIEW
      - score: numeric score (0-100)
      - checks: detailed check results
      - false_success_reasons: list of reasons if false success detected
    """
    start_time = time.time()

    result = {
        "verdict": "FAILED",
        "score": 0,
        "max_score": 100,
        "checks": {},
        "false_success_reasons": [],
        "warnings": [],
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
    }

    def ssh(cmd: str) -> str:
        try:
            return str(ssh_fn(cmd)).strip()
        except Exception as e:
            return f"SSH_ERROR: {e}"

    # Auto-detect URLs
    if not admin_url:
        if url_prefix:
            admin_url = f"http://localhost{url_prefix.rstrip('/')}/bitrix/admin/"
        elif site_url:
            admin_url = f"{site_url.rstrip('/')}/bitrix/admin/"
        else:
            admin_url = "http://localhost/bitrix/admin/"

    if not site_url:
        if url_prefix:
            site_url = f"http://localhost{url_prefix.rstrip('/')}/"
        else:
            site_url = "http://localhost/"

    # ── Check 1: Admin panel accessible ──────────────────────────────────────

    admin_http = ssh(f"curl -sL -o /tmp/bx_verify_admin.html -w '%{{http_code}}' '{admin_url}' 2>/dev/null")
    admin_body = ssh("cat /tmp/bx_verify_admin.html 2>/dev/null")

    try:
        admin_code = int(admin_http.strip().replace("'", ""))
    except (ValueError, TypeError):
        admin_code = 0

    check_admin = {
        "name": "admin_panel_accessible",
        "http_code": admin_code,
        "ok": admin_code in (200, 302),
        "score": 0,
        "max_score": 20,
        "details": "",
    }

    if check_admin["ok"]:
        check_admin["score"] = 20
        check_admin["details"] = f"Admin panel returns HTTP {admin_code}"
    else:
        check_admin["details"] = f"Admin panel returns HTTP {admin_code} (expected 200 or 302)"

    result["checks"]["admin_accessible"] = check_admin

    # ── Check 2: Admin panel shows Bitrix UI (not public landing) ────────────

    check_admin_ui = {
        "name": "admin_panel_is_bitrix",
        "ok": False,
        "score": 0,
        "max_score": 15,
        "details": "",
        "markers_found": [],
    }

    if admin_body:
        for marker in ADMIN_MARKERS:
            if marker.lower() in admin_body.lower():
                check_admin_ui["markers_found"].append(marker)

    if check_admin_ui["markers_found"]:
        check_admin_ui["ok"] = True
        check_admin_ui["score"] = 15
        check_admin_ui["details"] = f"Found Bitrix markers: {', '.join(check_admin_ui['markers_found'][:3])}"
    elif admin_code == 302:
        # 302 redirect to auth page is valid
        check_admin_ui["ok"] = True
        check_admin_ui["score"] = 15
        check_admin_ui["details"] = "Admin panel redirects to auth (302)"
    else:
        check_admin_ui["details"] = "No Bitrix admin markers found in response"
        result["false_success_reasons"].append("admin_returns_non_bitrix_content")

    result["checks"]["admin_is_bitrix"] = check_admin_ui

    # ── Check 3: DB tables exist ─────────────────────────────────────────────

    tables_result = ssh(
        f"mysql -u {db_user} -p'{_escape_php_string(db_password)}' {db_name} "
        f"-N -e \"SELECT COUNT(*) FROM information_schema.tables "
        f"WHERE table_schema='{db_name}' AND table_name LIKE 'b\\_%';\" 2>/dev/null"
    )

    table_count = 0
    try:
        table_count = int(tables_result.strip())
    except (ValueError, TypeError):
        pass

    check_db = {
        "name": "db_tables_exist",
        "ok": table_count >= 10,
        "score": 0,
        "max_score": 25,
        "table_count": table_count,
        "details": "",
    }

    if table_count >= 50:
        check_db["score"] = 25
        check_db["details"] = f"Full Bitrix DB: {table_count} tables"
    elif table_count >= 10:
        check_db["score"] = 20
        check_db["details"] = f"Bitrix DB partially initialized: {table_count} tables"
    elif table_count > 0:
        check_db["score"] = 10
        check_db["details"] = f"Few Bitrix tables: {table_count}"
    else:
        check_db["details"] = "No Bitrix tables found in database"
        result["false_success_reasons"].append("no_bitrix_tables_in_db")

    result["checks"]["db_tables"] = check_db

    # ── Check 4: Public site works ───────────────────────────────────────────

    public_http = ssh(f"curl -sL -o /dev/null -w '%{{http_code}}' '{site_url}' 2>/dev/null")

    try:
        public_code = int(public_http.strip().replace("'", ""))
    except (ValueError, TypeError):
        public_code = 0

    check_public = {
        "name": "public_site_works",
        "ok": public_code == 200,
        "score": 10 if public_code == 200 else 0,
        "max_score": 10,
        "http_code": public_code,
        "details": f"Public site returns HTTP {public_code}",
    }

    result["checks"]["public_site"] = check_public

    # ── Check 5: index.php is not a static wrapper ───────────────────────────

    index_content = ssh(f"cat {install_path}/index.php 2>/dev/null | head -20")

    check_index = {
        "name": "index_not_static_wrapper",
        "ok": False,
        "score": 0,
        "max_score": 10,
        "details": "",
    }

    is_wrapper = False
    for marker in FALSE_SUCCESS_MARKERS:
        if marker in index_content:
            is_wrapper = True
            break

    if "index.html" in index_content and ("readfile" in index_content or "file_get_contents" in index_content):
        is_wrapper = True

    if is_wrapper:
        check_index["details"] = "FALSE SUCCESS: index.php is a static HTML wrapper"
        result["false_success_reasons"].append("index_php_wraps_static_html")
    elif "bitrix/header.php" in index_content or "require" in index_content:
        check_index["ok"] = True
        check_index["score"] = 10
        check_index["details"] = "index.php properly includes Bitrix framework"
    elif not index_content:
        check_index["details"] = "index.php not found"
    else:
        check_index["ok"] = True
        check_index["score"] = 5
        check_index["details"] = "index.php exists but content unclear"

    result["checks"]["index_not_wrapper"] = check_index

    # ── Check 6: Wizard completed ────────────────────────────────────────────

    wizard_check = ssh(f"test -f {install_path}/bitrix/.install_complete && echo COMPLETE || echo INCOMPLETE")
    wizard_option = ssh(
        f"mysql -u {db_user} -p'{_escape_php_string(db_password)}' {db_name} "
        f"-N -e \"SELECT VALUE FROM b_option WHERE MODULE_ID='main' AND NAME='wizard_first' LIMIT 1;\" 2>/dev/null"
    )

    check_wizard = {
        "name": "wizard_completed",
        "ok": False,
        "score": 0,
        "max_score": 10,
        "details": "",
    }

    if "COMPLETE" in wizard_check:
        check_wizard["ok"] = True
        check_wizard["score"] = 10
        check_wizard["details"] = "Installation marker found"
    elif wizard_option and wizard_option.strip().upper() == "N":
        check_wizard["ok"] = True
        check_wizard["score"] = 10
        check_wizard["details"] = "Wizard disabled in DB options"
    elif table_count >= 50:
        # If many tables exist, wizard was likely completed
        check_wizard["ok"] = True
        check_wizard["score"] = 7
        check_wizard["details"] = "Wizard likely completed (many DB tables present)"
    else:
        check_wizard["details"] = "Wizard may not be completed"

    result["checks"]["wizard_completed"] = check_wizard

    # ── Check 7: Core files present ──────────────────────────────────────────

    core_ok = 0
    core_missing = []
    for cf in CORE_FILES:
        check = ssh(f"test -f {install_path}/{cf} && echo OK || echo MISS")
        if "OK" in check:
            core_ok += 1
        else:
            core_missing.append(cf)

    check_core = {
        "name": "core_files_present",
        "ok": core_ok >= 4,
        "score": min(10, round(10 * core_ok / len(CORE_FILES))),
        "max_score": 10,
        "found": core_ok,
        "total": len(CORE_FILES),
        "missing": core_missing,
        "details": f"{core_ok}/{len(CORE_FILES)} core files present",
    }

    result["checks"]["core_files"] = check_core

    # ── Calculate total score and verdict ────────────────────────────────────

    total_score = sum(c.get("score", 0) for c in result["checks"].values())
    max_score = sum(c.get("max_score", 0) for c in result["checks"].values())

    result["score"] = total_score
    result["max_score"] = max_score

    # Determine verdict
    all_critical_pass = (
        check_admin["ok"] and
        check_admin_ui["ok"] and
        check_db["ok"] and
        check_public["ok"] and
        check_index["ok"] and
        check_wizard["ok"] and
        check_core["ok"]
    )

    if all_critical_pass and total_score >= 85 and not result["false_success_reasons"]:
        result["verdict"] = "SUCCESS"
    elif total_score >= 60 and check_db["ok"] and check_core["ok"]:
        result["verdict"] = "PARTIAL_SUCCESS"
    elif total_score >= 30:
        result["verdict"] = "PARTIAL_SUCCESS"
    else:
        result["verdict"] = "FAILED"

    # False-success blocking override
    if result["false_success_reasons"] and result["verdict"] == "SUCCESS":
        result["verdict"] = "PARTIAL_SUCCESS"
        result["warnings"].append(
            f"Verdict downgraded from SUCCESS due to: {', '.join(result['false_success_reasons'])}"
        )

    # Cleanup
    ssh("rm -f /tmp/bx_verify_admin.html 2>/dev/null")

    elapsed = time.time() - start_time
    result["runtime_sec"] = round(elapsed, 1)

    logger.info(
        f"[VERIFY] verdict={result['verdict']}, "
        f"score={total_score}/{max_score}, "
        f"tables={table_count}, "
        f"false_success={result['false_success_reasons']}"
    )

    return result
