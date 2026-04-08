"""
project_manager.py — CRUD проектов, structured state, жизненный цикл.

Source of truth — .arcane/state.json (structured state).
PROJECT.md генерируется из него как human-readable view.
Нельзя создать чат без проекта. Проект — вечный. Чаты — разговоры внутри.
"""

from __future__ import annotations

import fcntl
import json
import logging
import os
import re
import shutil
import subprocess
import tarfile
import tempfile
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from enum import Enum
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logger = logging.getLogger("arcane.project_manager")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

WORKSPACE_ROOT = Path(os.environ.get("ARCANE_WORKSPACE", "/root/workspace/projects"))

ARCANE_DIR = ".arcane"
STATE_FILE = "state.json"
SETTINGS_FILE = "settings.json"
BUDGET_FILE = "budget.json"
SCRATCHPAD_FILE = "scratchpad.md"
CHATS_DIR = "chats"
PROJECT_MD = "PROJECT.md"
ARCHIVE_INDEX_FILE = "_archive_index.json"  # workspace-level registry

# Текущая версия state schema.
# _migrate_state() обновляет старые проекты при чтении.
STATE_VERSION = 2

# Append-only поля — update_state не может заменить их на более короткие
APPEND_ONLY_FIELDS = {"decisions", "runs"}

# Лимит записей в runs/decisions хранимых в state.json.
# Старые записи ротируются в .arcane/{field}_archive.jsonl при превышении.
MAX_RUNS = 500
MAX_DECISIONS = 200

# Regex: project_id и chat_id — только безопасные символы
_SAFE_ID_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_\-]{0,63}$")


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class ProjectStatus(str, Enum):
    ACTIVE = "active"           # Разработка — мгновенное восстановление
    MAINTENANCE = "maintenance" # Иногда правки — мгновенное восстановление
    SLEEPING = "sleeping"       # 30+ дней без задач — 5-10 сек восстановление
    ARCHIVED = "archived"       # tar.gz + паттерны в глоб. базе — распаковка


# Допустимые переходы lifecycle (state machine).
# archive() и restore_from_archive() управляют переходами в/из ARCHIVED.
_LIFECYCLE_TRANSITIONS: dict[ProjectStatus, set[ProjectStatus]] = {
    ProjectStatus.ACTIVE:      {ProjectStatus.MAINTENANCE, ProjectStatus.SLEEPING},
    ProjectStatus.MAINTENANCE: {ProjectStatus.ACTIVE, ProjectStatus.SLEEPING},
    ProjectStatus.SLEEPING:    {ProjectStatus.ACTIVE},
    ProjectStatus.ARCHIVED:    set(),  # только через restore_from_archive
}


class ProjectMode(str, Enum):
    AUTO = "auto"
    MANUAL = "manual"
    TOP = "top"
    OPTIMUM = "optimum"        # Default
    LITE = "lite"
    FREE = "free"


class DevFlow(str, Enum):
    WORKSPACE = "workspace"    # Clone → edit → test → PR → deploy
    SSH_DIRECT = "ssh_direct"  # Прямая работа на сервере клиента


# ---------------------------------------------------------------------------
# Structured State — default template
# ---------------------------------------------------------------------------

def _default_structured_state(
    project_id: str,
    name: str,
    client: str = "",
    goal: str = "",
) -> dict[str, Any]:
    """Полная структура state.json — source of truth проекта."""
    now = datetime.now(timezone.utc).isoformat()
    return {
        "version": 2,
        "project_id": project_id,
        "created_at": now,
        "updated_at": now,

        # --- профиль ---
        "project_profile": {
            "name": name,
            "client": client,
            "goal": goal,
        },

        # --- стек ---
        "tech_stack": {
            "framework": "",
            "css": "",
            "db": "",
            "hosting": "",
            "languages": [],
            "extras": [],
        },

        # --- дизайн ---
        "design_system": {
            "colors": [],
            "fonts": [],
            "style": "",
        },

        # --- окружение ---
        "environment": {
            "servers": [],       # [{host, user, ssh_key_ref, role}]
            "domains": [],
            "ssh_refs": [],
        },

        # --- решения (append-only) ---
        "decisions": [],         # [{date, what, why, who}]

        # --- статус ---
        "status": {
            "lifecycle": ProjectStatus.ACTIVE.value,
            "pages_done": [],
            "pages_todo": [],
            "known_issues": [],
        },

        # --- история run'ов ---
        "runs": [],              # [{id, task, model, cost, result, ts}]

        # --- личность проекта ---
        "personality": {
            "tone": "",          # «строго» / «дружелюбно» / ...
            "preferences": [],   # [«serif шрифты», «тёмные тона»]
            "dislikes": [],      # [«Tailwind», «анимации»]
        },

        # --- dev flow по умолчанию ---
        "dev_flow": DevFlow.WORKSPACE.value,
    }


def _default_settings() -> dict[str, Any]:
    """settings.json — режим, кастомные модели, лимиты."""
    return {
        "mode": ProjectMode.OPTIMUM.value,
        "custom_models": {},          # role → model override
        "budget_limit_usd": 10.0,     # дефолтный лимит на проект
        "consolidation": {
            "enabled": False,
            "models": [],
            "consolidator": "gemini-2.5-flash",
        },
        "dog_racing": {
            "enabled": False,
        },
        "global_kb_opt_in": False,    # глобальная KB выключена по умолчанию
        "speculative_execution": True,
    }


def _deep_merge(base: dict, patch: dict) -> dict:
    """Deep merge patch into base. Nested dicts are merged, not overwritten."""
    for k, v in patch.items():
        if k in base and isinstance(base[k], dict) and isinstance(v, dict):
            _deep_merge(base[k], v)
        else:
            base[k] = v
    return base


def _default_budget() -> dict[str, Any]:
    """budget.json — расходы по каждому агенту.
    
    Schema unified with budget_controller.py and auto_documenter.py:
    - limits.per_task          → used by budget_controller
    - limits.per_project_month → used by budget_controller  
    - limits.monthly_usd       → alias for auto_documenter BudgetGate
    - limits.per_call_usd      → alias for auto_documenter BudgetGate
    """
    return {
        "total_spent_usd": 0.0,
        "warning": None,              # None | "WARNING" | "PAUSE" | "STOP"
        "limits": {
            "per_task": 1.0,          # USD max per single task
            "per_project_month": 10.0, # USD max per project per month
            "monthly_usd": 10.0,      # alias (auto_documenter compat)
            "per_call_usd": 0.50,     # USD max per single LLM call
        },
        "by_agent": {},               # agent_name → spent_usd
        "by_run": [],                 # [{run_id, model, tokens_in, tokens_out, cost}]
        "month_started": datetime.now(timezone.utc).strftime("%Y-%m"),
    }


def _default_scratchpad() -> str:
    """scratchpad.md — структурированные рабочие заметки (не свободный MD)."""
    return (
        "# Scratchpad\n\n"
        "## Цель\n\n\n"
        "## Сделано\n\n\n"
        "## Проблемы\n\n\n"
        "## Заметки\n\n"
    )


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------

def _validate_safe_id(value: str, label: str = "id") -> None:
    """
    Валидация project_id / chat_id — только безопасные символы.
    Защита от path traversal (../../etc).
    """
    if not _SAFE_ID_RE.match(value):
        raise ValueError(
            f"Недопустимый {label}: {value!r}. "
            f"Разрешены: a-z, A-Z, 0-9, _, - (1-64 символа, "
            f"начинается с буквы или цифры)."
        )


def _ensure_within(child: Path, parent: Path) -> None:
    """Проверка что resolved child находится внутри parent."""
    child_resolved = child.resolve()
    parent_resolved = parent.resolve()
    if not str(child_resolved).startswith(str(parent_resolved) + os.sep) and \
       child_resolved != parent_resolved:
        raise SecurityError(
            f"Path traversal: {child} выходит за пределы {parent}"
        )


def _ensure_aware_utc(dt: datetime) -> datetime:
    """Гарантировать timezone-aware datetime (UTC)."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


# Type constraints для критичных полей state.json.
# Если поле есть в этом dict, его значение должно быть указанного типа.
_FIELD_TYPE_GUARDS: dict[str, type] = {
    "project_profile": dict,
    "tech_stack": dict,
    "design_system": dict,
    "environment": dict,
    "decisions": list,
    "status": dict,
    "runs": list,
    "personality": dict,
}


def _guard_field_type(key: str, value: Any) -> None:
    """Проверить что тип значения для ключа допустим."""
    expected = _FIELD_TYPE_GUARDS.get(key)
    if expected is not None and not isinstance(value, expected):
        raise TypeError(
            f"Поле {key!r} ожидает {expected.__name__}, "
            f"получен {type(value).__name__}: {value!r}"
        )


def _migrate_state(state: dict[str, Any]) -> bool:
    """
    Миграция state schema при чтении.
    Возвращает True если state был изменён (нужна перезапись).

    Миграции идемпотентны. Каждая проверяет version и добавляет
    недостающие поля. После миграции version = STATE_VERSION.
    """
    changed = False
    version = state.get("version", 1)

    if version < 2:
        # v1 → v2: добавить personality и dev_flow
        if "personality" not in state:
            state["personality"] = {"tone": "", "preferences": [], "dislikes": []}
            changed = True
        if "dev_flow" not in state:
            state["dev_flow"] = "workspace"
            changed = True
        state["version"] = 2
        changed = True

    # Будущие миграции:
    # if version < 3:
    #     ...
    #     state["version"] = 3
    #     changed = True

    return changed


# ---------------------------------------------------------------------------
# PROJECT.md generator
# ---------------------------------------------------------------------------

def generate_project_md(state: dict[str, Any]) -> str:
    """
    Генерирует PROJECT.md из structured state.
    PROJECT.md — human-readable VIEW, не source of truth.
    """
    p = state.get("project_profile", {})
    ts = state.get("tech_stack", {})
    ds = state.get("design_system", {})
    env = state.get("environment", {})
    st = state.get("status", {})
    pers = state.get("personality", {})
    decisions = state.get("decisions", [])
    runs = state.get("runs", [])

    lines: list[str] = []

    # --- Header ---
    lines.append(f"# Проект: {p.get('name', '—')}")
    if p.get("client"):
        lines.append(f"**Клиент:** {p['client']}")
    if p.get("goal"):
        lines.append(f"**Цель:** {p['goal']}")
    lines.append("")

    # --- Стек ---
    stack_parts = []
    for key in ("framework", "css", "db", "hosting"):
        v = ts.get(key)
        if v:
            stack_parts.append(v)
    if ts.get("languages"):
        stack_parts.extend(ts["languages"])
    if stack_parts:
        lines.append(f"## Стек: {', '.join(stack_parts)}")
        lines.append("")

    # --- Дизайн ---
    design_parts = []
    if ds.get("colors"):
        design_parts.append(", ".join(ds["colors"]))
    if ds.get("fonts"):
        design_parts.append(", ".join(ds["fonts"]))
    if ds.get("style"):
        design_parts.append(ds["style"])
    if design_parts:
        lines.append(f"## Дизайн: {' | '.join(design_parts)}")
        lines.append("")

    # --- Серверы ---
    servers = env.get("servers", [])
    if servers:
        hosts = [s.get("host", "?") for s in servers]
        lines.append(f"## Серверы: {', '.join(hosts)}")
        lines.append("")

    # --- Решения ---
    if decisions:
        lines.append("## Решения")
        for d in decisions[-10:]:  # последние 10
            date = d.get("date", "?")
            what = d.get("what", "")
            why = d.get("why", "")
            who = d.get("who", "")
            entry = f"- **{date}** — {what}"
            if why:
                entry += f" ({why})"
            if who:
                entry += f" [{who}]"
            lines.append(entry)
        lines.append("")

    # --- Статус ---
    lines.append("## Статус")
    lifecycle = st.get("lifecycle", "active")
    lines.append(f"**Фаза:** {lifecycle}")
    for page in st.get("pages_done", []):
        lines.append(f"- [x] {page}")
    for page in st.get("pages_todo", []):
        lines.append(f"- [ ] {page}")
    issues = st.get("known_issues", [])
    if issues:
        lines.append("")
        lines.append("**Известные проблемы:**")
        for issue in issues:
            lines.append(f"- {issue}")
    lines.append("")

    # --- Последние задачи ---
    if runs:
        lines.append("## Последние задачи")
        for r in runs[-5:]:
            rid = r.get("id", "?")[:8]
            task = r.get("task", "")
            model = r.get("model", "?")
            cost = r.get("cost", 0)
            result = r.get("result", "?")
            lines.append(f"- `{rid}` {task} → {model} (${cost:.4f}) [{result}]")
        lines.append("")

    # --- Личность ---
    if pers.get("tone") or pers.get("preferences") or pers.get("dislikes"):
        lines.append("## Предпочтения")
        if pers.get("tone"):
            lines.append(f"**Тон:** {pers['tone']}")
        if pers.get("preferences"):
            lines.append(f"**Нравится:** {', '.join(pers['preferences'])}")
        if pers.get("dislikes"):
            lines.append(f"**Не нравится:** {', '.join(pers['dislikes'])}")
        lines.append("")

    # --- Footer ---
    updated = state.get("updated_at", "")
    lines.append(f"---\n*Сгенерировано из structured state. Обновлено: {updated}*")

    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# ProjectManager — основной класс
# ---------------------------------------------------------------------------

class ProjectManager:
    """
    CRUD проектов. Structured state как source of truth.
    Генерация PROJECT.md. Жизненный цикл. Personality.

    Каждый проект:
        {workspace_root}/{project_id}/
            src/                        — код (Git)
            assets/                     — изображения, документы
            .arcane/state.json          — structured state (source of truth)
            .arcane/settings.json       — режим, кастомные модели, лимиты
            .arcane/budget.json         — расходы по каждому агенту
            .arcane/scratchpad.md       — рабочий блокнот текущей задачи
            .arcane/chats/              — лог всех чатов
            PROJECT.md                  — генерируется из state.json
    """

    def __init__(self, workspace_root: Path | str = WORKSPACE_ROOT):
        self.root = Path(workspace_root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # helpers — paths
    # ------------------------------------------------------------------

    def _project_dir(self, project_id: str) -> Path:
        return self.root / project_id

    def _arcane_dir(self, project_id: str) -> Path:
        return self._project_dir(project_id) / ARCANE_DIR

    def _state_path(self, project_id: str) -> Path:
        return self._arcane_dir(project_id) / STATE_FILE

    def _settings_path(self, project_id: str) -> Path:
        return self._arcane_dir(project_id) / SETTINGS_FILE

    def _budget_path(self, project_id: str) -> Path:
        return self._arcane_dir(project_id) / BUDGET_FILE

    def _scratchpad_path(self, project_id: str) -> Path:
        return self._arcane_dir(project_id) / SCRATCHPAD_FILE

    def _project_md_path(self, project_id: str) -> Path:
        return self._project_dir(project_id) / PROJECT_MD

    def _lock_path(self, project_id: str) -> Path:
        return self._arcane_dir(project_id) / ".lock"

    def _archive_index_path(self) -> Path:
        """Workspace-level archive registry."""
        return self.root / ARCHIVE_INDEX_FILE

    # ------------------------------------------------------------------
    # helpers — archive index (archived projects remain visible)
    # ------------------------------------------------------------------

    def _read_archive_index(self) -> dict[str, dict]:
        """Read archive index. {project_id: {name, client, archived_at, archive_path}}."""
        path = self._archive_index_path()
        if not path.exists():
            return {}
        try:
            return self._read_json(path)
        except (json.JSONDecodeError, OSError):
            logger.warning("Повреждён archive index, пересоздаю")
            return {}

    def _write_archive_index(self, index: dict[str, dict]) -> None:
        self._write_json(self._archive_index_path(), index)

    # ------------------------------------------------------------------
    # helpers — atomic I/O
    # ------------------------------------------------------------------

    def _write_json(self, path: Path, data: dict) -> None:
        """
        Атомарная запись JSON: write → tmp, затем os.replace.
        Гарантирует что при crash файл либо старый, либо новый — не обрезанный.
        """
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, path)   # атомарно на POSIX

    def _write_text_atomic(self, path: Path, text: str) -> None:
        """Атомарная запись текста."""
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(text, encoding="utf-8")
        os.replace(tmp, path)

    def _read_json(self, path: Path) -> dict:
        return json.loads(path.read_text(encoding="utf-8"))

    @contextmanager
    def _state_lock(self, project_id: str):
        """
        Файловая блокировка на запись state.json.
        Все read-modify-write операции идут через этот контекстный менеджер.
        Предотвращает race condition при параллельных append-операциях.
        """
        lock_path = self._lock_path(project_id)
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        fd = open(lock_path, "w")
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
            yield
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
            fd.close()

    def _touch_updated(self, state: dict) -> dict:
        state["updated_at"] = datetime.now(timezone.utc).isoformat()
        return state

    # ------------------------------------------------------------------
    # helpers — existence / validation
    # ------------------------------------------------------------------

    def _exists(self, project_id: str) -> bool:
        return self._state_path(project_id).exists()

    def _require_exists(self, project_id: str) -> None:
        if not self._exists(project_id):
            raise ProjectNotFoundError(project_id)

    def _require_not_archived(self, project_id: str, state: dict | None = None) -> None:
        if state is None:
            state = self._read_json(self._state_path(project_id))
        if state["status"]["lifecycle"] == ProjectStatus.ARCHIVED.value:
            raise ProjectArchivedError(project_id)

    def _validate_project_id(self, project_id: str) -> None:
        """Path traversal protection для project_id."""
        _validate_safe_id(project_id, "project_id")
        _ensure_within(self._project_dir(project_id), self.root)

    # ------------------------------------------------------------------
    # CREATE
    # ------------------------------------------------------------------

    def create(
        self,
        name: str,
        client: str = "",
        goal: str = "",
        project_id: str | None = None,
        mode: ProjectMode = ProjectMode.OPTIMUM,
        init_git: bool = True,
    ) -> dict[str, Any]:
        """
        Создать проект. Возвращает structured state.

        Создаёт структуру:
            {project_id}/src/
            {project_id}/assets/
            {project_id}/.arcane/state.json
            {project_id}/.arcane/settings.json
            {project_id}/.arcane/budget.json
            {project_id}/.arcane/scratchpad.md
            {project_id}/.arcane/chats/
            {project_id}/PROJECT.md
        """
        pid = project_id or uuid.uuid4().hex[:12]
        self._validate_project_id(pid)
        project_dir = self._project_dir(pid)

        if project_dir.exists():
            raise ProjectExistsError(pid)

        # Структура каталогов
        (project_dir / "src").mkdir(parents=True)
        (project_dir / "assets").mkdir(parents=True)
        arcane = self._arcane_dir(pid)
        arcane.mkdir(parents=True)
        (arcane / CHATS_DIR).mkdir()

        # Structured state — source of truth
        state = _default_structured_state(pid, name, client, goal)
        self._write_json(self._state_path(pid), state)

        # Settings
        settings = _default_settings()
        settings["mode"] = mode.value
        self._write_json(self._settings_path(pid), settings)

        # Budget
        self._write_json(self._budget_path(pid), _default_budget())

        # Scratchpad
        self._write_text_atomic(self._scratchpad_path(pid), _default_scratchpad())

        # PROJECT.md — view, генерируется из state
        self._regenerate_project_md(pid, state)

        # Git init
        if init_git:
            self._git_init(pid)

        return state

    def _git_init(self, project_id: str) -> None:
        """git init + initial commit в src/."""
        src = self._project_dir(project_id) / "src"
        try:
            subprocess.run(["git", "init"], cwd=src, capture_output=True, timeout=10)
            subprocess.run(["git", "add", "."], cwd=src, capture_output=True, timeout=10)
            subprocess.run(
                ["git", "commit", "-m", "init: project created by Arcane"],
                cwd=src, capture_output=True, timeout=10,
                env={**__import__("os").environ, "GIT_AUTHOR_NAME": "Arcane", 
                     "GIT_AUTHOR_EMAIL": "arcane@local",
                     "GIT_COMMITTER_NAME": "Arcane", "GIT_COMMITTER_EMAIL": "arcane@local"},
            )
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass  # git не установлен или timeout — не критично

    # ------------------------------------------------------------------
    # READ
    # ------------------------------------------------------------------

    def get_state(self, project_id: str) -> dict[str, Any]:
        """Полный structured state. Source of truth. Мигрирует если нужно."""
        self._require_exists(project_id)
        state = self._read_json(self._state_path(project_id))
        if _migrate_state(state):
            self._write_json(self._state_path(project_id), state)
            logger.info("Мигрирован state для %s до версии %d", project_id, STATE_VERSION)
        return state

    def get_state_slice(self, project_id: str, keys: list[str]) -> dict[str, Any]:
        """
        Релевантный срез structured state — не весь файл.
        Экономичнее для подачи в LLM.

        Пример: get_state_slice(pid, ["project_profile", "tech_stack", "personality"])
        """
        state = self.get_state(project_id)
        return {k: state[k] for k in keys if k in state}

    def get_settings(self, project_id: str) -> dict[str, Any]:
        self._require_exists(project_id)
        return self._read_json(self._settings_path(project_id))

    def get_budget(self, project_id: str) -> dict[str, Any]:
        self._require_exists(project_id)
        return self._read_json(self._budget_path(project_id))

    def get_project_md(self, project_id: str) -> str:
        """Прочитать PROJECT.md (view, не source of truth)."""
        self._require_exists(project_id)
        return self._project_md_path(project_id).read_text(encoding="utf-8")

    def list_projects(self, status_filter: ProjectStatus | None = None) -> list[dict[str, Any]]:
        """
        Список проектов. Опционально фильтр по lifecycle статусу.
        Archived проекты берутся из archive index (не с диска — их директории удалены).
        """
        result = []
        if not self.root.exists():
            return result

        # Живые проекты (на диске)
        for d in sorted(self.root.iterdir()):
            state_path = d / ARCANE_DIR / STATE_FILE
            if not state_path.exists():
                continue
            try:
                state = self._read_json(state_path)
            except (json.JSONDecodeError, OSError, KeyError) as exc:
                logger.warning("Пропускаю повреждённый проект %s: %s", d.name, exc)
                continue
            try:
                lifecycle = state["status"]["lifecycle"]
                if status_filter and lifecycle != status_filter.value:
                    continue
                result.append({
                    "project_id": state["project_id"],
                    "name": state["project_profile"]["name"],
                    "client": state["project_profile"].get("client", ""),
                    "lifecycle": lifecycle,
                    "updated_at": state.get("updated_at", ""),
                })
            except (KeyError, TypeError) as exc:
                logger.warning("Пропускаю проект с битой структурой %s: %s", d.name, exc)
                continue

        # Archived проекты (из archive index)
        if status_filter is None or status_filter == ProjectStatus.ARCHIVED:
            live_ids = {p["project_id"] for p in result}
            for pid, meta in self._read_archive_index().items():
                if pid not in live_ids:
                    result.append({
                        "project_id": pid,
                        "name": meta.get("name", "?"),
                        "client": meta.get("client", ""),
                        "lifecycle": ProjectStatus.ARCHIVED.value,
                        "updated_at": meta.get("archived_at", ""),
                    })

        return result

    # ------------------------------------------------------------------
    # UPDATE — core locked mutator
    # ------------------------------------------------------------------

    def _mutate_state(
        self,
        project_id: str,
        mutator,
        regenerate_md: bool = True,
    ) -> dict[str, Any]:
        """
        Атомарный read-modify-write с файловой блокировкой.
        mutator(state) -> None (мутирует state in-place).
        Единственная точка записи state.json (кроме create/archive/restore).
        """
        self._require_exists(project_id)
        with self._state_lock(project_id):
            state = self._read_json(self._state_path(project_id))
            self._require_not_archived(project_id, state)
            # Ensure required list fields exist (for projects created before CRIT-4 fix)
            for _field in ("runs", "decisions", "escalations"):
                if _field not in state:
                    state[_field] = []
            if "environment" not in state:
                state["environment"] = {"servers": [], "env_vars": {}}
            elif "servers" not in state.get("environment", {}):
                state["environment"]["servers"] = []
            mutator(state)
            state = self._touch_updated(state)
            self._write_json(self._state_path(project_id), state)
            if regenerate_md:
                self._regenerate_project_md(project_id, state)
        return state

    def update_state(
        self,
        project_id: str,
        patch: dict[str, Any],
        regenerate_md: bool = True,
    ) -> dict[str, Any]:
        """
        Обновить structured state (shallow merge на первом уровне).
        Автоматически обновляет updated_at и PROJECT.md.

        Запрещает менять: project_id, version, created_at.
        Защищает append-only поля (decisions, runs) от уменьшения длины.
        Валидирует типы критичных полей.
        """
        # Копия — не мутируем входной dict вызывающего кода
        patch = {k: v for k, v in patch.items()
                 if k not in {"project_id", "version", "created_at"}}

        def _apply(state: dict) -> None:
            for key, value in patch.items():
                # Type guards для критичных полей
                _guard_field_type(key, value)
                # Защита append-only полей от случайного обнуления
                if key in APPEND_ONLY_FIELDS and isinstance(value, list):
                    existing = state.get(key, [])
                    if isinstance(existing, list) and len(value) < len(existing):
                        raise ValueError(
                            f"Поле {key!r} — append-only: нельзя уменьшить "
                            f"с {len(existing)} до {len(value)} записей. "
                            f"Используйте специализированные методы add_*."
                        )
                # shallow merge для dict-полей
                if key in state and isinstance(state[key], dict) and isinstance(value, dict):
                    state[key].update(value)
                else:
                    state[key] = value

        return self._mutate_state(project_id, _apply, regenerate_md)

    def update_profile(self, project_id: str, **kwargs) -> dict[str, Any]:
        """Обновить project_profile (name, client, goal)."""
        return self.update_state(project_id, {"project_profile": kwargs})

    def update_tech_stack(self, project_id: str, **kwargs) -> dict[str, Any]:
        """Обновить tech_stack."""
        return self.update_state(project_id, {"tech_stack": kwargs})

    def update_design_system(self, project_id: str, **kwargs) -> dict[str, Any]:
        """Обновить design_system."""
        return self.update_state(project_id, {"design_system": kwargs})

    def update_settings(self, project_id: str, patch: dict[str, Any]) -> dict[str, Any]:
        """Обновить settings.json (deep merge — не перетирает вложенные объекты)."""
        self._require_exists(project_id)
        settings = self.get_settings(project_id)
        _deep_merge(settings, patch)
        self._write_json(self._settings_path(project_id), settings)
        return settings

    # ------------------------------------------------------------------
    # UPDATE — personality
    # ------------------------------------------------------------------

    def set_personality(
        self,
        project_id: str,
        tone: str | None = None,
        preferences: list[str] | None = None,
        dislikes: list[str] | None = None,
    ) -> dict[str, Any]:
        """
        Установить personality проекта.
        «Сделай как мы любим» → модель получает personality в контексте.
        """
        pers_patch: dict[str, Any] = {}
        if tone is not None:
            pers_patch["tone"] = tone
        if preferences is not None:
            pers_patch["preferences"] = preferences
        if dislikes is not None:
            pers_patch["dislikes"] = dislikes
        return self.update_state(project_id, {"personality": pers_patch})

    # ------------------------------------------------------------------
    # UPDATE — decisions (append-only, locked)
    # ------------------------------------------------------------------

    def add_decision(
        self,
        project_id: str,
        what: str,
        why: str = "",
        who: str = "",
    ) -> dict[str, Any]:
        """Добавить решение в decisions log (append-only)."""
        entry = {
            "date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            "what": what,
            "why": why,
            "who": who,
        }

        def _append(state: dict) -> None:
            state["decisions"].append(entry)
            self._maybe_rotate(state, "decisions", MAX_DECISIONS, project_id)

        return self._mutate_state(project_id, _append)

    # ------------------------------------------------------------------
    # UPDATE — runs (append-only, locked)
    # ------------------------------------------------------------------

    def add_run(
        self,
        project_id: str,
        task: str,
        model: str,
        cost: float,
        result: str,
        run_id: str | None = None,
    ) -> dict[str, Any]:
        """Добавить запись о run'е."""
        entry = {
            "id": run_id or uuid.uuid4().hex[:12],
            "task": task,
            "model": model,
            "cost": cost,
            "result": result,
            "ts": datetime.now(timezone.utc).isoformat(),
        }

        def _append(state: dict) -> None:
            if not isinstance(state.get("runs"), list):
                state["runs"] = []
            state["runs"].append(entry)
            self._maybe_rotate(state, "runs", MAX_RUNS, project_id)

        return self._mutate_state(project_id, _append)

    def _maybe_rotate(
        self,
        state: dict,
        field: str,
        max_count: int,
        project_id: str,
    ) -> None:
        """Ротация старых записей в архивный файл при превышении лимита."""
        items = state.get(field, [])
        if len(items) <= max_count:
            return
        overflow = items[:-max_count]
        state[field] = items[-max_count:]
        # Дописываем overflow в .arcane/{field}_archive.jsonl
        archive_path = self._arcane_dir(project_id) / f"{field}_archive.jsonl"
        with open(archive_path, "a", encoding="utf-8") as f:
            for item in overflow:
                f.write(json.dumps(item, ensure_ascii=False) + "\n")

    # ------------------------------------------------------------------
    # UPDATE — environment / servers (locked)
    # ------------------------------------------------------------------

    def add_server(
        self,
        project_id: str,
        host: str,
        user: str = "root",
        ssh_key_ref: str = "",
        role: str = "production",
    ) -> dict[str, Any]:
        """Добавить сервер в environment.servers."""
        server = {"host": host, "user": user, "ssh_key_ref": ssh_key_ref, "role": role}

        def _append(state: dict) -> None:
            state["environment"]["servers"].append(server)

        return self._mutate_state(project_id, _append)

    # ------------------------------------------------------------------
    # UPDATE — status pages (locked)
    # ------------------------------------------------------------------

    def mark_page_done(self, project_id: str, page: str) -> dict[str, Any]:
        """Переместить страницу из todo в done."""
        def _move(state: dict) -> None:
            status = state["status"]
            if page in status["pages_todo"]:
                status["pages_todo"].remove(page)
            if page not in status["pages_done"]:
                status["pages_done"].append(page)
        return self._mutate_state(project_id, _move)

    def add_page_todo(self, project_id: str, page: str) -> dict[str, Any]:
        """Добавить страницу в todo."""
        def _add(state: dict) -> None:
            status = state["status"]
            if page not in status["pages_todo"] and page not in status["pages_done"]:
                status["pages_todo"].append(page)
        return self._mutate_state(project_id, _add)

    def add_known_issue(self, project_id: str, issue: str) -> dict[str, Any]:
        """Добавить known issue."""
        def _add(state: dict) -> None:
            state["status"]["known_issues"].append(issue)
        return self._mutate_state(project_id, _add)

    # ------------------------------------------------------------------
    # LIFECYCLE (state machine)
    # ------------------------------------------------------------------

    def set_lifecycle(self, project_id: str, new_status: ProjectStatus) -> dict[str, Any]:
        """
        Смена фазы жизненного цикла.

        Допустимые переходы (state machine):
            active      → maintenance, sleeping
            maintenance → active, sleeping
            sleeping    → active

        Для archived используйте archive() / restore_from_archive().
        """
        if new_status == ProjectStatus.ARCHIVED:
            raise LifecycleError("Для архивации используйте archive()")

        def _transition(state: dict) -> None:
            current = ProjectStatus(state["status"]["lifecycle"])
            allowed = _LIFECYCLE_TRANSITIONS.get(current, set())
            if new_status not in allowed:
                raise LifecycleError(
                    f"Переход {current.value} → {new_status.value} недопустим. "
                    f"Допустимые: {', '.join(s.value for s in allowed) or 'нет'}."
                )
            state["status"]["lifecycle"] = new_status.value

        return self._mutate_state(project_id, _transition)

    def check_sleeping_candidates(self, days_threshold: int = 30) -> list[str]:
        """
        Найти проекты без активности 30+ дней → кандидаты в sleeping.
        Проверяет не только state updated_at, но и mtime файлов
        budget.json, settings.json и директории chats/.
        """
        candidates = []
        cutoff = datetime.now(timezone.utc) - timedelta(days=days_threshold)
        cutoff_ts = cutoff.timestamp()
        for project in self.list_projects(ProjectStatus.ACTIVE):
            pid = project["project_id"]
            # Проверяем updated_at из state
            latest_activity = 0.0
            updated = project.get("updated_at", "")
            if updated:
                try:
                    updated_dt = _ensure_aware_utc(datetime.fromisoformat(updated))
                    latest_activity = max(latest_activity, updated_dt.timestamp())
                except (ValueError, TypeError):
                    pass
            # Проверяем mtime файлов которые update_state не трогает
            for extra_file in (
                self._budget_path(pid),
                self._settings_path(pid),
                self._scratchpad_path(pid),
            ):
                try:
                    latest_activity = max(latest_activity, extra_file.stat().st_mtime)
                except OSError:
                    pass
            # Проверяем самый свежий чат
            chat_dir = self._arcane_dir(pid) / CHATS_DIR
            try:
                for chat_file in chat_dir.iterdir():
                    latest_activity = max(latest_activity, chat_file.stat().st_mtime)
            except OSError:
                pass

            if latest_activity > 0 and latest_activity < cutoff_ts:
                candidates.append(pid)
        return candidates

    def wake_up(self, project_id: str) -> dict[str, Any]:
        """Разбудить sleeping проект → active."""
        def _wake(state: dict) -> None:
            if state["status"]["lifecycle"] != ProjectStatus.SLEEPING.value:
                raise LifecycleError(
                    f"wake_up доступен только для sleeping проектов, "
                    f"текущий статус: {state['status']['lifecycle']}"
                )
            state["status"]["lifecycle"] = ProjectStatus.ACTIVE.value
        return self._mutate_state(project_id, _wake)

    # ------------------------------------------------------------------
    # ARCHIVE / RESTORE
    # ------------------------------------------------------------------

    def archive(self, project_id: str, archive_dir: Path | None = None) -> Path:
        """
        Архивировать проект → tar.gz.

        Транзакционно:
          1. Создаём tar.gz (может упасть — проект не тронут)
          2. Обновляем статус → archived
          3. Удаляем директорию

        Если шаг 1 падает — проект остаётся нетронутым.
        Паттерны остаются в глобальной базе (анонимно).
        """
        self._require_exists(project_id)
        self._validate_project_id(project_id)
        state = self.get_state(project_id)

        if state["status"]["lifecycle"] == ProjectStatus.ARCHIVED.value:
            raise ProjectArchivedError(project_id)

        # 1. Создаём tar.gz СНАЧАЛА — если падает, проект не тронут
        dest = archive_dir or (self.root / "_archives")
        dest.mkdir(parents=True, exist_ok=True)
        ts_str = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        archive_path = dest / f"{project_id}_{ts_str}.tar.gz"

        with tarfile.open(archive_path, "w:gz") as tar:
            tar.add(self._project_dir(project_id), arcname=project_id)

        # 2. Архив создан — теперь безопасно обновить статус
        state["status"]["lifecycle"] = ProjectStatus.ARCHIVED.value
        state = self._touch_updated(state)
        self._write_json(self._state_path(project_id), state)

        # 3. Записать в archive index (archived проекты остаются видимыми в list_projects)
        index = self._read_archive_index()
        index[project_id] = {
            "name": state["project_profile"].get("name", "?"),
            "client": state["project_profile"].get("client", ""),
            "archived_at": state["updated_at"],
            "archive_path": str(archive_path),
        }
        self._write_archive_index(index)

        # 4. Удалить директорию проекта
        shutil.rmtree(self._project_dir(project_id))

        return archive_path

    def restore_from_archive(self, archive_path: Path | str) -> dict[str, Any]:
        """
        Восстановить проект из tar.gz архива.
        - Определяет project_id ДО распаковки
        - Отказывает если проект уже существует на диске
        - Распаковывает во временную staging dir, затем перемещает
        - Убирает проект из archive index
        """
        archive_path = Path(archive_path)
        if not archive_path.exists():
            raise FileNotFoundError(f"Архив не найден: {archive_path}")

        root_resolved = self.root.resolve()

        # 1. Определить project_id и валидировать ДО распаковки
        with tarfile.open(archive_path, "r:gz") as tar:
            top_dirs = {m.name.split("/")[0] for m in tar.getmembers()}
        if len(top_dirs) != 1:
            raise ValueError(
                f"Архив должен содержать ровно одну top-level директорию, "
                f"найдено: {top_dirs}"
            )
        project_id = top_dirs.pop()
        _validate_safe_id(project_id, "project_id в архиве")

        # 2. Проверить что проект не существует на диске
        if self._project_dir(project_id).exists():
            raise ProjectExistsError(project_id)

        # 3. Валидация содержимого tar (path traversal, symlinks)
        import tempfile
        staging_dir = Path(tempfile.mkdtemp(prefix="arcane_restore_", dir=self.root))
        try:
            with tarfile.open(archive_path, "r:gz") as tar:
                for member in tar.getmembers():
                    resolved = (staging_dir / member.name).resolve()
                    staging_resolved = staging_dir.resolve()
                    if not str(resolved).startswith(str(staging_resolved) + os.sep) and \
                       resolved != staging_resolved:
                        raise SecurityError(f"Опасный путь в архиве: {member.name}")
                    if member.issym() or member.islnk():
                        link_target = (staging_dir / member.linkname).resolve()
                        if not str(link_target).startswith(str(staging_resolved) + os.sep):
                            raise SecurityError(
                                f"Опасная ссылка в архиве: {member.name} → {member.linkname}"
                            )
                    # Запрет device/special файлов
                    if member.isdev() or member.ischr() or member.isblk() or member.isfifo():
                        raise SecurityError(f"Спец-файл в архиве: {member.name}")
                tar.extractall(staging_dir)

            # 4. Проверить что state.json есть
            staged_state = staging_dir / project_id / ARCANE_DIR / STATE_FILE
            if not staged_state.exists():
                raise ValueError(
                    f"Архив не содержит {ARCANE_DIR}/{STATE_FILE} — "
                    f"не похож на проект Arcane"
                )

            # 5. Переместить из staging в workspace
            shutil.move(str(staging_dir / project_id), str(self._project_dir(project_id)))

        finally:
            # Очистить staging в любом случае
            if staging_dir.exists():
                shutil.rmtree(staging_dir, ignore_errors=True)

        # 6. Поменять статус на active
        state = self._read_json(self._state_path(project_id))
        if _migrate_state(state):
            pass  # migration applied
        state["status"]["lifecycle"] = ProjectStatus.ACTIVE.value
        state = self._touch_updated(state)
        self._write_json(self._state_path(project_id), state)
        self._regenerate_project_md(project_id, state)

        # 7. Убрать из archive index
        index = self._read_archive_index()
        if project_id in index:
            del index[project_id]
            self._write_archive_index(index)

        return state

    # ------------------------------------------------------------------
    # DELETE
    # ------------------------------------------------------------------

    def delete(self, project_id: str, force: bool = False) -> None:
        """
        Удалить проект.
        Без force — только archived/sleeping.
        С force — любой.

        Удаление = удаление ВСЕХ данных (файлы, Git, чаты, бюджет).
        Глобальные паттерны — анонимны, остаются.
        """
        self._require_exists(project_id)
        self._validate_project_id(project_id)

        if not force:
            state = self.get_state(project_id)
            lifecycle = state["status"]["lifecycle"]
            if lifecycle in (ProjectStatus.ACTIVE.value, ProjectStatus.MAINTENANCE.value):
                raise LifecycleError(
                    f"Нельзя удалить {lifecycle} проект без force=True. "
                    f"Сначала архивируйте или используйте force."
                )

        shutil.rmtree(self._project_dir(project_id))

    # ------------------------------------------------------------------
    # PROJECT.md regeneration
    # ------------------------------------------------------------------

    def _regenerate_project_md(
        self,
        project_id: str,
        state: dict[str, Any] | None = None,
    ) -> None:
        """Перегенерировать PROJECT.md из structured state."""
        if state is None:
            state = self._read_json(self._state_path(project_id))
        md = generate_project_md(state)
        self._write_text_atomic(self._project_md_path(project_id), md)

    def regenerate_md(self, project_id: str) -> str:
        """Публичный метод: перегенерировать и вернуть PROJECT.md."""
        self._require_exists(project_id)
        self._regenerate_project_md(project_id)
        return self.get_project_md(project_id)

    # ------------------------------------------------------------------
    # Context for LLM (что подавать модели)
    # ------------------------------------------------------------------

    def get_llm_context(
        self,
        project_id: str,
        include: list[str] | None = None,
    ) -> dict[str, Any]:
        """
        Сформировать контекст для подачи в LLM.
        Подаётся релевантный срез structured state, не весь файл.

        По умолчанию: project_profile, tech_stack, design_system, personality, status, dev_flow.
        """
        default_keys = [
            "project_profile",
            "tech_stack",
            "design_system",
            "personality",
            "status",
            "dev_flow",
        ]
        keys = include or default_keys

        # Одно чтение state — не два
        state = self.get_state(project_id)
        context = {k: state[k] for k in keys if k in state}

        settings = self.get_settings(project_id)
        context["_mode"] = settings.get("mode", ProjectMode.OPTIMUM.value)

        return context

    # ------------------------------------------------------------------
    # Scratchpad (горячая память)
    # ------------------------------------------------------------------

    def get_scratchpad(self, project_id: str) -> str:
        self._require_exists(project_id)
        return self._scratchpad_path(project_id).read_text(encoding="utf-8")

    def update_scratchpad(self, project_id: str, content: str) -> None:
        self._require_exists(project_id)
        self._write_text_atomic(self._scratchpad_path(project_id), content)

    # ------------------------------------------------------------------
    # Chat logs
    # ------------------------------------------------------------------

    def save_chat(self, project_id: str, chat_id: str, messages: list[dict]) -> Path:
        """Сохранить лог чата. Нельзя создать чат без проекта."""
        self._require_exists(project_id)
        _validate_safe_id(chat_id, "chat_id")
        chat_dir = self._arcane_dir(project_id) / CHATS_DIR
        chat_dir.mkdir(exist_ok=True)
        chat_path = chat_dir / f"{chat_id}.json"
        self._write_json(chat_path, {
            "chat_id": chat_id,
            "project_id": project_id,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "messages": messages,
        })
        return chat_path

    def list_chats(self, project_id: str) -> list[str]:
        """Список chat_id для проекта."""
        self._require_exists(project_id)
        chat_dir = self._arcane_dir(project_id) / CHATS_DIR
        return [p.stem for p in sorted(chat_dir.glob("*.json"))]

    # ------------------------------------------------------------------
    # Budget tracking
    # ------------------------------------------------------------------

    def record_cost(
        self,
        project_id: str,
        run_id: str,
        model: str,
        tokens_in: int,
        tokens_out: int,
        cost_usd: float,
    ) -> dict[str, Any]:
        """
        Записать расход. Проверить лимиты.
        Warning вычисляется ПЕРЕД записью на диск и сохраняется вместе с бюджетом.
        """
        # Валидация — нельзя уводить бюджет в минус
        if cost_usd < 0:
            raise ValueError(f"cost_usd не может быть отрицательным: {cost_usd}")
        if tokens_in < 0 or tokens_out < 0:
            raise ValueError(f"tokens не могут быть отрицательными: in={tokens_in}, out={tokens_out}")

        self._require_exists(project_id)
        budget = self.get_budget(project_id)
        settings = self.get_settings(project_id)

        budget["total_spent_usd"] += cost_usd
        budget["by_agent"][model] = budget["by_agent"].get(model, 0.0) + cost_usd
        budget["by_run"].append({
            "run_id": run_id,
            "model": model,
            "tokens_in": tokens_in,
            "tokens_out": tokens_out,
            "cost": cost_usd,
            "ts": datetime.now(timezone.utc).isoformat(),
        })

        # Ротация by_run если слишком длинный
        if len(budget["by_run"]) > MAX_RUNS:
            archive_path = self._arcane_dir(project_id) / "budget_runs_archive.jsonl"
            overflow = budget["by_run"][:-MAX_RUNS]
            budget["by_run"] = budget["by_run"][-MAX_RUNS:]
            with open(archive_path, "a", encoding="utf-8") as f:
                for item in overflow:
                    f.write(json.dumps(item, ensure_ascii=False) + "\n")

        # Вычислить warning ПЕРЕД записью на диск
        budget_for_limit = self._read_json(self._budget_path(project_id))  # CRIT-5
        limit = budget_for_limit.get("limits", {}).get("per_project_month", 10.0)
        spent = budget["total_spent_usd"]

        if limit <= 0:
            # limit=0 означает «бюджет не выделен» → STOP
            budget["warning"] = "STOP"
        else:
            ratio = spent / limit
            if ratio >= 1.0:
                budget["warning"] = "STOP"
            elif ratio >= 0.95:
                budget["warning"] = "PAUSE"
            elif ratio >= 0.80:
                budget["warning"] = "WARNING"
            else:
                budget["warning"] = None

        # Записываем С warning на диск
        self._write_json(self._budget_path(project_id), budget)

        return budget

    def add_run_with_cost(
        self,
        project_id: str,
        task: str,
        model: str,
        tokens_in: int,
        tokens_out: int,
        cost_usd: float,
        result: str,
        run_id: str | None = None,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        """
        Атомарная операция: add_run + record_cost.
        Гарантирует что либо оба записаны, либо ни один.
        Использует один run_id для связи.
        Возвращает (state, budget).
        """
        rid = run_id or uuid.uuid4().hex[:12]
        state = self.add_run(project_id, task, model, cost_usd, result, run_id=rid)
        try:
            budget = self.record_cost(project_id, rid, model, tokens_in, tokens_out, cost_usd)
        except Exception:
            # Rollback: убрать run из state
            # (best-effort — если и это упадёт, хотя бы run без cost лучше чем cost без run)
            try:
                def _remove_run(st: dict) -> None:
                    st["runs"] = [r for r in st["runs"] if r.get("id") != rid]
                self._mutate_state(project_id, _remove_run)
            except Exception:
                logger.error("Не удалось откатить run %s после ошибки record_cost", rid)
            raise
        return state, budget


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class ProjectError(Exception):
    """Base exception for project operations."""


class ProjectNotFoundError(ProjectError):
    def __init__(self, project_id: str):
        super().__init__(f"Проект не найден: {project_id}")
        self.project_id = project_id


class ProjectExistsError(ProjectError):
    def __init__(self, project_id: str):
        super().__init__(f"Проект уже существует: {project_id}")
        self.project_id = project_id


class ProjectArchivedError(ProjectError):
    def __init__(self, project_id: str):
        super().__init__(f"Проект архивирован: {project_id}. Используйте restore_from_archive().")
        self.project_id = project_id


class LifecycleError(ProjectError):
    pass


class SecurityError(ProjectError):
    pass
