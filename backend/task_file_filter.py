"""
ORION Digital — Task-Aware File Filter
=======================================
Реализует 3 механизма умного контроля агента (по образцу Manus):

1. Контекстная фильтрация — определяет релевантность файла задаче
2. Tool-level friction — возвращает предупреждение вместо блокировки
3. Task-scoped sandbox — изолированная рабочая директория /tmp/orion_task_{id}/

Автор: ORION Digital v2
"""

import os
import re
import logging
from typing import Optional, Tuple

logger = logging.getLogger(__name__)

# ─── Категории файлов ────────────────────────────────────────────────────────

# Файлы которые НИКОГДА не нужны агенту (независимо от задачи)
ALWAYS_IRRELEVANT = [
    ".bash_history", ".zsh_history", ".sh_history", ".fish_history",
    ".python_history", ".node_repl_history", ".irb_history",
    ".lesshst", ".viminfo", ".wget-hsts",
    ".sudo_as_admin_successful", ".motd_shown",
]

# Файлы которые нужны ТОЛЬКО при git-задачах
GIT_ONLY_FILES = [
    # Все паттерны в lowercase — сравнение идёт с path_lower
    ".git/logs/head", ".git/logs/refs",
    ".git/commit_editmsg", ".git/orig_head",
    ".git/fetch_head", ".git/merge_head",
    ".git/config", ".git/description",
    ".git/packed-refs",
]

# Файлы которые нужны при git-задачах И при деплое/аудите
GIT_OR_DEVOPS_FILES = [
    # Все паттерны в lowercase
    ".git/status", ".git/diff",
    ".gitignore", ".gitmodules", ".gitattributes",
]

# Системные пути — нужны только при системном аудите
SYSTEM_PATHS = [
    "/proc/", "/sys/", "/dev/",
    "/run/", "/boot/",
]

# Конфиги SSH — нужны только при SSH-задачах
SSH_CONFIG_FILES = [
    ".ssh/known_hosts", ".ssh/config", ".ssh/authorized_keys",
]

# ─── Ключевые слова для определения типа задачи ─────────────────────────────

GIT_KEYWORDS = [
    "git", "commit", "branch", "merge", "rebase", "pull request",
    "репозитори", "ветк", "коммит", "слияни", "пул реквест",
    "github", "gitlab", "bitbucket",
]

DEVOPS_KEYWORDS = [
    "деплой", "deploy", "сервер", "server", "nginx", "apache",
    "docker", "kubernetes", "ci/cd", "pipeline", "ansible",
    "конфигурац", "настройк", "установ", "install",
    "аудит", "audit", "проверк", "диагностик",
]

SYSTEM_AUDIT_KEYWORDS = [
    "аудит сервера", "server audit", "системн", "процесс", "память сервера",
    "диагностик", "мониторинг", "нагрузк", "cpu", "ram", "disk",
    "/proc", "/sys", "kernel", "ядро",
]

SSH_KEYWORDS = [
    "ssh", "sftp", "ключ", "key", "авторизаци", "доступ к серверу",
    "подключени", "connect",
]

LANDING_KEYWORDS = [
    "лендинг", "landing", "сайт", "website", "страниц", "html", "css",
    "верстк", "дизайн", "ui", "интерфейс", "шаблон",
]

CODE_KEYWORDS = [
    "код", "code", "скрипт", "script", "функци", "класс", "модул",
    "python", "javascript", "typescript", "php", "java", "rust",
    "программ", "разработ",
]

# ─── Основная функция фильтрации ─────────────────────────────────────────────

def classify_task(task_description: str) -> dict:
    """
    Анализирует описание задачи и возвращает набор флагов.
    Используется для контекстной фильтрации файлов.
    """
    desc = (task_description or "").lower()

    return {
        "is_git_task":        any(kw in desc for kw in GIT_KEYWORDS),
        "is_devops_task":     any(kw in desc for kw in DEVOPS_KEYWORDS),
        "is_system_audit":    any(kw in desc for kw in SYSTEM_AUDIT_KEYWORDS),
        "is_ssh_task":        any(kw in desc for kw in SSH_KEYWORDS),
        "is_landing_task":    any(kw in desc for kw in LANDING_KEYWORDS),
        "is_code_task":       any(kw in desc for kw in CODE_KEYWORDS),
    }


def check_file_relevance(
    file_path: str,
    task_description: str,
    task_flags: Optional[dict] = None,
) -> Tuple[bool, str]:
    """
    Проверяет релевантность файла задаче.

    Returns:
        (is_relevant: bool, reason: str)
        - is_relevant=True  → файл полезен, читать нормально
        - is_relevant=False → файл нерелевантен, вернуть friction-ответ
    """
    if task_flags is None:
        task_flags = classify_task(task_description)

    # Нормализуем путь
    path = file_path.strip()
    basename = os.path.basename(path)
    path_lower = path.lower()

    # ── 1. Всегда нерелевантные файлы ────────────────────────────────────────
    for irrelevant in ALWAYS_IRRELEVANT:
        if basename == irrelevant or path_lower.endswith(irrelevant):
            return False, (
                f"Файл `{basename}` — история команд shell. "
                f"Она не содержит информации полезной для выполнения задачи. "
                f"Продолжай выполнение задачи напрямую."
            )

    # ── 2. Git-only файлы ────────────────────────────────────────────────────
    # Проверяем и абсолютные и относительные пути (.git/... и /.git/...)
    is_git_file = (".git/" in path_lower or ".git\\" in path_lower
                   or path_lower.startswith(".git") or path_lower.endswith("/.git"))
    if is_git_file:
        for git_only in GIT_ONLY_FILES:
            if git_only in path_lower:
                if not task_flags.get("is_git_task"):
                    return False, (
                        f"Файл `{path}` — внутренние метаданные git. "
                        f"Текущая задача не связана с git-операциями. "
                        f"Этот файл не поможет выполнить задачу. Продолжай."
                    )
        # .git/config может быть нужен при git-задачах и деплое
        if ".git/config" in path_lower:
            if task_flags.get("is_git_task") or task_flags.get("is_devops_task"):
                return True, "ok"  # Разрешаем для git/devops задач
            if not task_flags.get("is_git_task") and not task_flags.get("is_devops_task"):
                return False, (
                    f"Файл `.git/config` содержит только настройки репозитория. "
                    f"Для текущей задачи эта информация не нужна. Продолжай."
                )

    # ── 3. Git-or-devops файлы ───────────────────────────────────────────────
    for god_file in GIT_OR_DEVOPS_FILES:
        if god_file in path_lower or basename == god_file:
            if not task_flags.get("is_git_task") and not task_flags.get("is_devops_task"):
                return False, (
                    f"Файл `{basename}` — git-конфигурация. "
                    f"Не нужен для текущей задачи. Продолжай выполнение."
                )

    # ── 4. Системные пути ────────────────────────────────────────────────────
    for sys_path in SYSTEM_PATHS:
        if path.startswith(sys_path):
            if not task_flags.get("is_system_audit"):
                return False, (
                    f"Путь `{path}` — системный файл ядра Linux. "
                    f"Чтение системных файлов не поможет выполнить текущую задачу. "
                    f"Продолжай выполнение."
                )

    # ── 5. SSH конфиги ───────────────────────────────────────────────────────
    for ssh_file in SSH_CONFIG_FILES:
        if ssh_file in path_lower or basename in [os.path.basename(s) for s in SSH_CONFIG_FILES]:
            if not task_flags.get("is_ssh_task") and not task_flags.get("is_devops_task"):
                return False, (
                    f"Файл `{basename}` — SSH-конфигурация. "
                    f"Не нужен для текущей задачи. Продолжай."
                )

    # Файл прошёл все проверки — релевантен
    return True, "ok"


def get_friction_response(file_path: str, reason: str) -> dict:
    """
    Возвращает friction-ответ вместо блокировки.
    Агент получает объяснение и продолжает работу.
    """
    return {
        "success": True,  # Не ошибка — просто пустой результат
        "content": f"[ORION File Filter] {reason}",
        "path": file_path,
        "filtered": True,
        "filter_reason": reason,
    }


# ─── Task-Scoped Sandbox ─────────────────────────────────────────────────────

class TaskScopedSandbox:
    """
    Изолированная рабочая директория для каждой задачи.
    Создаётся при старте задачи, очищается после завершения.

    Структура: /tmp/orion_task_{chat_id}_{task_id}/
    ├── workspace/     — рабочие файлы агента
    ├── output/        — файлы для отдачи пользователю
    └── .meta          — метаданные задачи (JSON)
    """

    BASE_DIR = "/tmp/orion_tasks"

    def __init__(self, chat_id: str, task_id: str):
        self.chat_id = str(chat_id or "default")
        self.task_id = str(task_id or "default")
        self.sandbox_id = f"{self.chat_id}_{self.task_id}"
        self.root = os.path.join(self.BASE_DIR, self.sandbox_id)
        self.workspace = os.path.join(self.root, "workspace")
        self.output_dir = os.path.join(self.root, "output")
        self._created = False

    def create(self) -> str:
        """Создаёт директории sandbox. Возвращает путь к workspace."""
        try:
            os.makedirs(self.workspace, exist_ok=True)
            os.makedirs(self.output_dir, exist_ok=True)
            self._created = True
            logger.info(f"[TaskSandbox] Created sandbox: {self.root}")
            return self.workspace
        except Exception as e:
            logger.warning(f"[TaskSandbox] Failed to create sandbox: {e}")
            return "/tmp"

    def cleanup(self):
        """Очищает sandbox после завершения задачи."""
        if not self._created:
            return
        try:
            import shutil
            shutil.rmtree(self.root, ignore_errors=True)
            logger.info(f"[TaskSandbox] Cleaned up sandbox: {self.root}")
        except Exception as e:
            logger.warning(f"[TaskSandbox] Cleanup error: {e}")

    def resolve_path(self, path: str) -> str:
        """
        Если агент использует относительный путь — резолвит его в workspace.
        Абсолютные пути (на сервере пользователя) остаются как есть.
        """
        if os.path.isabs(path):
            return path  # Абсолютный путь — не трогаем (это путь на сервере)
        return os.path.join(self.workspace, path)

    def get_output_path(self, filename: str) -> str:
        """Возвращает путь для выходного файла в output/."""
        return os.path.join(self.output_dir, filename)

    @classmethod
    def get_existing(cls, chat_id: str, task_id: str) -> Optional["TaskScopedSandbox"]:
        """Возвращает существующий sandbox если он есть."""
        sandbox = cls(chat_id, task_id)
        if os.path.exists(sandbox.root):
            sandbox._created = True
            return sandbox
        return None

    @classmethod
    def cleanup_old_sandboxes(cls, max_age_hours: int = 24):
        """Очищает старые sandbox-ы (старше max_age_hours)."""
        import time
        if not os.path.exists(cls.BASE_DIR):
            return
        now = time.time()
        cleaned = 0
        for name in os.listdir(cls.BASE_DIR):
            path = os.path.join(cls.BASE_DIR, name)
            try:
                age_hours = (now - os.path.getmtime(path)) / 3600
                if age_hours > max_age_hours:
                    import shutil
                    shutil.rmtree(path, ignore_errors=True)
                    cleaned += 1
            except Exception:
                pass
        if cleaned:
            logger.info(f"[TaskSandbox] Cleaned {cleaned} old sandboxes")


# ─── SSE событие для friction ────────────────────────────────────────────────

def make_file_filtered_sse(file_path: str, reason: str) -> dict:
    """
    SSE событие которое отправляется в UI когда файл отфильтрован.
    Показывает пользователю что агент попытался прочитать нерелевантный файл.
    """
    return {
        "type": "file_filtered",
        "path": file_path,
        "reason": reason,
        "message": f"Пропущен нерелевантный файл: {os.path.basename(file_path)}",
    }
