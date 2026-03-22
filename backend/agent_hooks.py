"""
MEGA PATCH Part 7.3: Auto-hooks for agent_loop.py
Provides automatic backup, error analysis, responsive check, and QA hooks.
Import and call from agent_loop.py at appropriate points.
"""
import logging

logger = logging.getLogger("agent_hooks")

_consecutive_errors = {}


def pre_install_hook(chat_id, project_path, server=None):
    """Call before installing anything. Creates automatic backup."""
    from high_level_operators import create_backup
    logger.info(f"[HOOK] Pre-install backup for {project_path}")
    result = create_backup(project_path, server)
    if result.get("success"):
        logger.info(f"[HOOK] Backup created: {result['backup_path']} ({result['size_mb']}MB)")
    else:
        logger.warning(f"[HOOK] Backup failed: {result.get('error', 'unknown')}")
    return result


def on_error_hook(chat_id, error_log, project_path=None):
    """Call on error. After 3 consecutive errors, triggers analyze + replan."""
    from high_level_operators import analyze_traceback, replan_task

    _consecutive_errors[chat_id] = _consecutive_errors.get(chat_id, 0) + 1
    count = _consecutive_errors[chat_id]
    logger.warning(f"[HOOK] Error #{count} in chat {chat_id}")

    analysis = analyze_traceback(error_log)

    if count >= 3:
        logger.error(f"[HOOK] 3+ errors in chat {chat_id}, triggering replan")
        _consecutive_errors[chat_id] = 0
        return {"action": "replan", "analysis": analysis}

    return {"action": "retry", "analysis": analysis}


def on_success_hook(chat_id):
    """Call on successful operation. Resets error counter."""
    _consecutive_errors[chat_id] = 0


def post_deploy_hook(chat_id, url, server=None):
    """Call after deploying a site. Checks responsive layout."""
    from high_level_operators import check_responsive_layout, check_site_health

    logger.info(f"[HOOK] Post-deploy check for {url}")
    health = check_site_health(url)
    if not health.get("healthy"):
        logger.warning(f"[HOOK] Site unhealthy: {health.get('error')}")
        return {"healthy": False, "health": health}

    responsive = check_responsive_layout(url, server)
    logger.info(f"[HOOK] Responsive score: {responsive.get('score', 0)}/10")
    return {"healthy": True, "health": health, "responsive": responsive}


def post_qa_hook(chat_id, project_path, server=None):
    """Call after task_complete if project has tests."""
    from high_level_operators import run_project_qa

    logger.info(f"[HOOK] Running QA for {project_path}")
    result = run_project_qa(project_path, server)
    if result.get("failed", 0) > 0:
        logger.warning(f"[HOOK] QA failed: {result['failed']} tests failed")
    return result
