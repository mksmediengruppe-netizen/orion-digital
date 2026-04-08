"""
shared/utils/workspace.py — Fix #11
Единый источник правды для путей рабочего пространства.

Использование:
    from shared.utils.workspace import get_workspace_root, get_project_dir
"""
import os


def get_workspace_root() -> str:
    """Return the root workspace directory.
    
    Reads ARCANE_WORKSPACE env var, falls back to /root/workspace.
    """
    return os.environ.get("ARCANE_WORKSPACE", "/root/workspace")


def get_projects_dir() -> str:
    """Return the projects directory inside the workspace."""
    return os.path.join(get_workspace_root(), "projects")


def get_project_dir(project_id: str) -> str:
    """Return the directory for a specific project."""
    return os.path.join(get_projects_dir(), project_id)


def get_project_arcane_dir(project_id: str) -> str:
    """Return the .arcane metadata directory for a project."""
    return os.path.join(get_project_dir(project_id), ".arcane")


def get_project_runs_dir(project_id: str) -> str:
    """Return the runs directory for a project."""
    return os.path.join(get_project_arcane_dir(project_id), "runs")


def get_project_budget_path(project_id: str) -> str:
    """Return the budget.json path for a project."""
    return os.path.join(get_project_arcane_dir(project_id), "budget.json")


def get_project_settings_path(project_id: str) -> str:
    """Return the settings.json path for a project."""
    return os.path.join(get_project_arcane_dir(project_id), "settings.json")
