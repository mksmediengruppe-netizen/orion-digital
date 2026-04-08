"""
ssh_tools.py — 9 SSH-инструментов Arcane 2
==========================================

Спека v1.4, раздел 4: SSH-инструменты.

Инструменты:
    1. ssh_exec         — выполнить команду
    2. ssh_read_file    — прочитать файл
    3. ssh_read_lines   — прочитать фрагмент (строки from..to)
    4. ssh_write_file   — записать файл (с автобэкапом, через SFTP)
    5. ssh_patch_file   — заменить по номерам строк (не по тексту)
    6. ssh_list_dir     — список файлов
    7. ssh_backup       — бэкап файла/директории
    8. ssh_restore      — откат из бэкапа
    9. ssh_tail_log     — последние N строк лога
   10. ssh_batch        — пакетное выполнение (Tool Call Batching)

Безопасность (раздел 4.3):
    - Детекция деструктивных команд → ApprovalRequired
    - Автобэкап перед ssh_write / ssh_patch
    - Audit log каждого действия (с маскировкой секретов)
    - File lock per server (запись последовательно, чтение параллельно)
    - Проверка path на защищённые системные файлы
    - Host key verification включена по умолчанию
    - SFTP для записи файлов (без heredoc-инъекций)
    - Approval gates на write/patch/restore в protected paths
"""

from __future__ import annotations

import asyncio
import collections
import datetime as dt
import fnmatch
import hashlib
import json
import logging
import os
import re
import time
import uuid
from dataclasses import dataclass, field, asdict
from enum import Enum
from pathlib import PurePosixPath
from typing import Any, Sequence

import asyncssh  # pip install asyncssh

logger = logging.getLogger("arcane.ssh_tools")


# ---------------------------------------------------------------------------
# Конфигурация
# ---------------------------------------------------------------------------

BACKUP_SUBDIR = ".arcane/backups"     # суффикс к cfg.home → абсолютный путь
MAX_FILE_READ = 5 * 1024 * 1024       # 5 МБ — лимит чтения за раз
MAX_EXEC_OUTPUT = 1 * 1024 * 1024     # 1 МБ — лимит stdout/stderr ssh_exec
MAX_TAIL_LINES = 10_000               # максимум строк для ssh_tail_log

# P-9: SSH retry settings
_SSH_MAX_RETRIES = 3
_SSH_RETRY_DELAY_BASE = 2.0  # seconds, exponential: 2s, 4s, 8s
MAX_BATCH_COMMANDS = 50               # максимум команд в ssh_batch
MAX_WRITE_SIZE = 50 * 1024 * 1024     # 50 МБ — лимит записи за раз
AUDIT_MAX_ENTRIES = 50_000            # ротация in-memory лога

# Абсолютные пути, запись в которые ВСЕГДА требует approval.
PROTECTED_PATHS: list[str] = [
    "/etc/",
    "/boot/",
    "/usr/lib/",
    "/usr/bin/",
    "/usr/sbin/",
    "/sbin/",
    "/bin/",
    "/root/.ssh/",
    "/home/*/.ssh/",
    "/var/spool/cron/",
    "/proc/",
    "/sys/",
    "/dev/",
]

# Паттерны деструктивных SHELL-команд.
DESTRUCTIVE_PATTERNS: list[re.Pattern[str]] = [
    # --- файловая система ---
    re.compile(r"\brm\s+(-[a-zA-Z]*[rf]|[^\s]*\s+/)", re.I),
    re.compile(r"\brm\s+/", re.I),
    re.compile(r"\brm\s+\*", re.I),
    re.compile(r"\bmkfs\b", re.I),
    re.compile(r"\bdd\s+if=", re.I),
    re.compile(r"\bchmod\s+(777|000|666|a\+[rwx])", re.I),
    re.compile(r"\bchown\s+(-R|--recursive)", re.I),
    # --- truncation через redirect ---
    re.compile(r">\s*/etc/", re.I),
    re.compile(r">\s*/var/", re.I),
    re.compile(r'echo\s+"?\s*"?\s*>\s*/', re.I),
    re.compile(r"\btee\s+/etc/", re.I),
    re.compile(r">\s*/dev/sd", re.I),
    # --- SQL ---
    re.compile(r"\bDROP\s+(TABLE|DATABASE|INDEX|SCHEMA|USER)", re.I),
    re.compile(r"\bALTER\s+TABLE", re.I),
    re.compile(r"\bTRUNCATE\s+(TABLE)?", re.I),
    re.compile(r"\bDELETE\s+FROM\b", re.I),
    re.compile(r"\bUPDATE\s+\S+\s+SET\b", re.I),
    # --- remote code execution ---
    re.compile(r"\bcurl\b.*\|\s*(ba)?sh", re.I),
    re.compile(r"\bwget\b.*\|\s*(ba)?sh", re.I),
    re.compile(r"\bwget\s+-O\s*-", re.I),
    # --- service/system ---
    re.compile(r"\bdeploy\s+(prod|production)", re.I),
    re.compile(r"\bsystemctl\s+(stop|disable|mask|restart)", re.I),
    re.compile(r"\bservice\s+\S+\s+(stop|restart)", re.I),
    re.compile(r"\bkill\s+(-9\s+)?-1\b", re.I),
    re.compile(r"\bkillall\b", re.I),
    re.compile(r"\breboot\b", re.I),
    re.compile(r"\bshutdown\b", re.I),
    re.compile(r"\binit\s+[06]\b", re.I),
    # --- user/auth ---
    re.compile(r"\buserdel\b", re.I),
    re.compile(r"\bgroupdel\b", re.I),
    re.compile(r"\bpasswd\b", re.I),
    re.compile(r"\bvisudo\b", re.I),
    # --- network ---
    re.compile(r"\biptables\s+-F", re.I),
    re.compile(r"\biptables\s+-X", re.I),
    re.compile(r"\bufw\s+disable", re.I),
    re.compile(r"\b(rndc|nsupdate|dns.*change)", re.I),
    # --- cron ---
    re.compile(r"\bcrontab\s+-r", re.I),
    # --- kubernetes / docker ---
    re.compile(r"\bkubectl\s+delete\b", re.I),
    re.compile(r"\bdocker\s+(rm|rmi|system\s+prune)", re.I),
    # --- fork bomb ---
    re.compile(r":\(\)\{", re.I),
    # --- sed in-place on system files ---
    re.compile(r"\bsed\s+-i.*\s+/etc/", re.I),
]

# Маскировка секретов в audit log.
_SECRET_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"(password|passwd|secret|token|api.?key|authorization)\s*[:=]\s*\S+", re.I),
    re.compile(r"\b[A-Za-z0-9+/]{40,}={0,2}\b"),
]


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

from core.security import ApprovalGate, ApprovalRequired as CoreApprovalRequired, AuditLog as CoreAuditLog

class SSHToolError(Exception):
    """Базовая ошибка SSH-инструментов."""


class ApprovalRequired(SSHToolError):
    """Деструктивное действие — нужно подтверждение пользователя."""
    def __init__(self, action: str, detail: str):
        self.action = action
        self.detail = detail
        super().__init__(f"Approval required for [{action}]: {detail}")


class FileLocked(SSHToolError):
    """Файл заблокирован другим агентом на запись."""


class PathForbidden(SSHToolError):
    """Попытка записи в защищённый системный путь."""


# ---------------------------------------------------------------------------
# Data-классы
# ---------------------------------------------------------------------------

class AuditAction(str, Enum):
    EXEC = "exec"
    READ = "read"
    READ_LINES = "read_lines"
    WRITE = "write"
    PATCH = "patch"
    LIST_DIR = "list_dir"
    BACKUP = "backup"
    RESTORE = "restore"
    TAIL_LOG = "tail_log"
    BATCH = "batch"


@dataclass
class AuditEntry:
    """Одна запись audit-лога.  Спека 4.3: время, модель, сервер, команда, результат."""
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    timestamp: str = field(
        default_factory=lambda: dt.datetime.now(dt.timezone.utc).isoformat(timespec="milliseconds")
    )
    server: str = ""
    model: str = ""
    action: str = ""
    detail: str = ""
    success: bool = True
    error: str | None = None
    duration_ms: int = 0

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class SSHResult:
    """Результат одного SSH-вызова."""
    ok: bool
    data: Any = None
    error: str | None = None
    audit_id: str | None = None

    def to_dict(self) -> dict:
        return {"ok": self.ok, "data": self.data, "error": self.error, "audit_id": self.audit_id}


@dataclass
class _RunResult:
    """Внутренний результат _run() с уже truncated output."""
    stdout: str
    stderr: str
    returncode: int


@dataclass
class ServerConfig:
    """Конфигурация SSH-подключения."""
    host: str
    port: int = 22
    username: str = "root"
    key_path: str | None = None
    password: str | None = None
    known_hosts: str = "~/.ssh/known_hosts"   # FIX: явный дефолт, не None → MITM невозможен
    home: str = "/root"
    # Если задан — запись разрешена ТОЛЬКО в эти директории.
    # Если None — действует только PROTECTED_PATHS блокировка.
    allowed_write_roots: list[str] | None = None


# ---------------------------------------------------------------------------
# Audit Log (с ротацией)
# ---------------------------------------------------------------------------

class AuditLog:
    """
    In-memory (с ротацией через deque) + file-append audit log.

    Спека 4.3: «Каждая команда: время, модель, сервер, команда, результат.
    Видно в dashboard. Экспорт.»
    """

    def __init__(self, log_dir: str = ".arcane/audit", max_entries: int = AUDIT_MAX_ENTRIES):
        self._entries: collections.deque[AuditEntry] = collections.deque(maxlen=max_entries)
        self._log_dir = log_dir
        os.makedirs(log_dir, exist_ok=True)

    def record(self, entry: AuditEntry) -> None:
        self._entries.append(entry)
        path = os.path.join(self._log_dir, f"{entry.server.replace(':', '_')}.jsonl")
        try:
            with open(path, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry.to_dict(), ensure_ascii=False) + "\n")
        except OSError:
            logger.warning("Failed to persist audit entry %s", entry.id)

    def query(
        self,
        server: str | None = None,
        action: str | None = None,
        limit: int = 100,
    ) -> list[dict]:
        result: list[AuditEntry] = list(self._entries)
        if server:
            result = [e for e in result if e.server == server]
        if action:
            result = [e for e in result if e.action == action]
        return [e.to_dict() for e in result[-limit:]]

    def export_json(self) -> str:
        return json.dumps([e.to_dict() for e in self._entries], ensure_ascii=False, indent=2)


# ---------------------------------------------------------------------------
# File Lock  (per-server, per-path)
# ---------------------------------------------------------------------------

class FileLockManager:
    """
    Спека 4.3: «Один агент пишет — другие ждут. Чтение параллельно.»

    ОГРАНИЧЕНИЕ: in-process only.  Для multi-worker — заменить на Redis-lock.
    TODO(production): RedisLockManager с тем же интерфейсом.
    """

    def __init__(self):
        self._locks: dict[str, asyncio.Lock] = {}
        self._guard = asyncio.Lock()   # FIX: защита от race при создании Lock

    def _key(self, server: str, path: str) -> str:
        return f"{server}::{path}"

    async def acquire_write(self, server: str, path: str, timeout: float = 30.0) -> None:
        key = self._key(server, path)
        async with self._guard:
            if key not in self._locks:
                self._locks[key] = asyncio.Lock()
            lock = self._locks[key]
        try:
            await asyncio.wait_for(lock.acquire(), timeout=timeout)
        except asyncio.TimeoutError:
            raise FileLocked(f"File {path} on {server} is locked by another agent")

    def release_write(self, server: str, path: str) -> None:
        key = self._key(server, path)
        lock = self._locks.get(key)
        if lock and lock.locked():
            lock.release()


# ---------------------------------------------------------------------------
# Детектор деструктивных команд + проверка путей
# ---------------------------------------------------------------------------

# detect_destructive moved to core.security for central management
from core.security import detect_destructive  # noqa: F811


def is_protected_path(path: str) -> bool:
    """Проверяет, является ли path защищённым системным путём."""
    resolved = PurePosixPath(path).as_posix()
    for prot in PROTECTED_PATHS:
        if "*" in prot:
            if fnmatch.fnmatch(resolved, prot + "*"):
                return True
        else:
            if resolved == prot.rstrip("/") or resolved.startswith(prot):
                return True
    return False


def check_write_allowed(cfg: ServerConfig, path: str) -> None:
    """
    Проверяет allowlist (если задан).

    Protected path check (is_protected_path → ApprovalRequired) выполняется
    в каждом вызывающем методе отдельно.

    Raises PathForbidden если path вне allowed_write_roots.
    """
    resolved = PurePosixPath(path).as_posix()
    if cfg.allowed_write_roots is not None:
        allowed = any(
            resolved.startswith(root.rstrip("/") + "/") or resolved == root.rstrip("/")
            for root in cfg.allowed_write_roots
        )
        if not allowed:
            raise PathForbidden(
                f"Path {path} is outside allowed write roots: {cfg.allowed_write_roots}"
            )


def _mask_secrets(text: str) -> str:
    """Маскирует секреты в строке для audit log."""
    result = text
    for pat in _SECRET_PATTERNS:
        result = pat.sub("[REDACTED]", result)
    return result


def _truncate_output(text: str, max_bytes: int = MAX_EXEC_OUTPUT) -> str:
    """Обрезает вывод до лимита."""
    if len(text) <= max_bytes:
        return text
    return text[:max_bytes] + f"\n... [TRUNCATED at {max_bytes} bytes]"


# ---------------------------------------------------------------------------
# Connection Pool (race-safe, учитывает auth-контекст)
# ---------------------------------------------------------------------------

class ConnectionPool:
    """
    Пул asyncssh-соединений.

    FIX: Ключ включает host+port+username+key_path (auth-контекст).
    FIX: Создание соединения защищено от race condition через per-key Lock.
    """

    def __init__(self):
        self._pool: dict[str, asyncssh.SSHClientConnection] = {}
        self._creating: dict[str, asyncio.Lock] = {}
        self._guard = asyncio.Lock()

    def _pool_key(self, cfg: ServerConfig) -> str:
        return f"{cfg.username}@{cfg.host}:{cfg.port}|key={cfg.key_path or 'none'}"

    async def get(self, cfg: ServerConfig) -> asyncssh.SSHClientConnection:
        key = self._pool_key(cfg)

        # Быстрый путь: есть живое соединение
        conn = self._pool.get(key)
        if conn is not None:
            try:
                await asyncio.wait_for(conn.run("echo ok", check=True), timeout=5)
                return conn
            except Exception:
                try:
                    conn.close()
                except Exception:
                    pass
                self._pool.pop(key, None)

        # Медленный путь: создаём, защищая от race.
        async with self._guard:
            if key not in self._creating:
                self._creating[key] = asyncio.Lock()
            create_lock = self._creating[key]

        async with create_lock:
            # Double-check: другая корутина могла создать пока мы ждали.
            existing = self._pool.get(key)
            if existing is not None:
                try:
                    await asyncio.wait_for(existing.run("echo ok", check=True), timeout=5)
                    return existing
                except Exception:
                    try:
                        existing.close()
                    except Exception:
                        pass
                    self._pool.pop(key, None)

            opts: dict[str, Any] = {
                "host": cfg.host,
                "port": cfg.port,
                "username": cfg.username,
                "known_hosts": cfg.known_hosts,   # FIX: not None by default
            }
            if cfg.key_path:
                opts["client_keys"] = [cfg.key_path]
            if cfg.password:
                opts["password"] = cfg.password

            conn = await asyncssh.connect(**opts)
            self._pool[key] = conn
            return conn

    async def close_all(self) -> None:
        for conn in self._pool.values():
            try:
                conn.close()
            except Exception:
                pass
        self._pool.clear()


# ---------------------------------------------------------------------------
# SSHTools — основной класс
# ---------------------------------------------------------------------------

class SSHTools:
    """
    9 SSH-инструментов Arcane 2.

    Каждый метод:
        1. Валидирует параметры.
        2. Проверяет безопасность.
        3. Логирует в audit log (с маскировкой секретов).
        4. При записи: автобэкап + file lock.
        5. Возвращает SSHResult с корректным ok (проверяет returncode).
    """

    def __init__(
        self,
        audit: AuditLog | None = None,
        locks: FileLockManager | None = None,
        pool: ConnectionPool | None = None,
    ):
        self.audit = audit or AuditLog()
        self.locks = locks or FileLockManager()
        self.pool = pool or ConnectionPool()

    # ---- helpers ----------------------------------------------------------

    async def _conn(self, cfg: ServerConfig) -> asyncssh.SSHClientConnection:
        return await self.pool.get(cfg)

    def _backup_dir(self, cfg: ServerConfig) -> str:
        """Абсолютный путь к директории бэкапов.  FIX: используем cfg.home."""
        return f"{cfg.home.rstrip('/')}/{BACKUP_SUBDIR}"

    def _audit(
        self,
        cfg: ServerConfig,
        action: AuditAction,
        detail: str,
        model: str,
        success: bool = True,
        error: str | None = None,
        duration_ms: int = 0,
    ) -> str:
        entry = AuditEntry(
            server=f"{cfg.host}:{cfg.port}",
            model=model,
            action=action.value,
            detail=_mask_secrets(detail[:2000]),
            success=success,
            error=_mask_secrets(error) if error else None,
            duration_ms=duration_ms,
        )
        self.audit.record(entry)
        return entry.id

    async def _run(
        self,
        cfg: ServerConfig,
        cmd: str,
        *,
        timeout: float = 60,
        max_output: int = MAX_EXEC_OUTPUT,
    ) -> _RunResult:
        """Выполняет команду с retry при timeout/connection error (P-9)."""
        last_error: Exception | None = None
        for attempt in range(_SSH_MAX_RETRIES):
            try:
                conn = await self._conn(cfg)
                result = await asyncio.wait_for(conn.run(cmd, check=False), timeout=timeout)
                stdout = _truncate_output(result.stdout or "", max_output)
                stderr = _truncate_output(result.stderr or "", max_output)
                return _RunResult(
                    stdout=stdout,
                    stderr=stderr,
                    returncode=result.returncode if result.returncode is not None else -1,
                )
            except (asyncio.TimeoutError, ConnectionError, OSError) as e:
                last_error = e
                # Invalidate pooled connection so next attempt creates a fresh one
                key = self.pool._pool_key(cfg)
                old_conn = self.pool._pool.pop(key, None)
                if old_conn is not None:
                    try:
                        old_conn.close()
                    except Exception:
                        pass
                if attempt < _SSH_MAX_RETRIES - 1:
                    wait = _SSH_RETRY_DELAY_BASE * (2 ** attempt)
                    logger.warning(
                        f"SSH {type(e).__name__} on {cfg.host} "
                        f"(attempt {attempt+1}/{_SSH_MAX_RETRIES}), retrying in {wait:.0f}s"
                    )
                    await asyncio.sleep(wait)
                    continue
        raise RuntimeError(
            f"SSH command failed after {_SSH_MAX_RETRIES} attempts on {cfg.host}: {last_error}"
        )

    async def _ensure_backup_dir(self, cfg: ServerConfig) -> None:
        bdir = self._backup_dir(cfg)
        await self._run(cfg, f"mkdir -p {_sq(bdir)}")

    def _backup_name(self, cfg: ServerConfig, path: str) -> str:
        """FIX: UUID-суффикс предотвращает коллизию при бэкапах в одну секунду."""
        ts = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%d_%H%M%S")
        uid = uuid.uuid4().hex[:8]
        safe = path.replace("/", "__")
        bdir = self._backup_dir(cfg)
        return f"{bdir}/{safe}.{ts}_{uid}.bak"

    # ---- 1. ssh_exec ------------------------------------------------------

    async def ssh_exec(
        self,
        cfg: ServerConfig,
        cmd: str,
        *,
        model: str = "",
        approved: bool = False,
        timeout: float = 120,
    ) -> SSHResult:
        """
        Выполнить команду на сервере.

        Спека 4.2: ssh_exec(cmd) — выполнить команду (ls, grep, curl, mysql).
        Спека 4.3: деструктивные → пауза, подтверждение.
        """
        if not approved:
            danger = detect_destructive(cmd)
            if danger:
                raise ApprovalRequired("ssh_exec", f"Command: {cmd!r}. {danger}")

        t0 = time.monotonic()
        try:
            result = await self._run(cfg, cmd, timeout=timeout)
            ok = result.returncode == 0
            data = {
                "stdout": result.stdout or "",
                "stderr": result.stderr or "",
                "exit_code": result.returncode,
            }
            elapsed = int((time.monotonic() - t0) * 1000)
            aid = self._audit(cfg, AuditAction.EXEC, cmd, model, success=ok,
                              error=result.stderr if not ok else None, duration_ms=elapsed)
            return SSHResult(ok=ok, data=data, audit_id=aid)
        except Exception as exc:
            elapsed = int((time.monotonic() - t0) * 1000)
            aid = self._audit(cfg, AuditAction.EXEC, cmd, model, success=False,
                              error=str(exc), duration_ms=elapsed)
            return SSHResult(ok=False, error=str(exc), audit_id=aid)

    # ---- 2. ssh_read_file -------------------------------------------------

    async def ssh_read_file(
        self,
        cfg: ServerConfig,
        path: str,
        *,
        model: str = "",
        max_bytes: int = MAX_FILE_READ,
    ) -> SSHResult:
        """Прочитать файл целиком (до max_bytes).  Спека 4.2."""
        if max_bytes <= 0:
            return SSHResult(ok=False, error="max_bytes must be positive")
        max_bytes = min(max_bytes, MAX_FILE_READ)

        t0 = time.monotonic()
        try:
            result = await self._run(cfg, f"head -c {max_bytes} {_sq(path)}")
            ok = result.returncode == 0
            elapsed = int((time.monotonic() - t0) * 1000)
            aid = self._audit(cfg, AuditAction.READ, path, model, success=ok,
                              error=result.stderr if not ok else None, duration_ms=elapsed)
            return SSHResult(ok=ok, data=result.stdout or "",
                             error=result.stderr if not ok else None, audit_id=aid)
        except Exception as exc:
            elapsed = int((time.monotonic() - t0) * 1000)
            aid = self._audit(cfg, AuditAction.READ, path, model, success=False,
                              error=str(exc), duration_ms=elapsed)
            return SSHResult(ok=False, error=str(exc), audit_id=aid)

    # ---- 3. ssh_read_lines ------------------------------------------------

    async def ssh_read_lines(
        self,
        cfg: ServerConfig,
        path: str,
        line_from: int,
        line_to: int,
        *,
        model: str = "",
    ) -> SSHResult:
        """Прочитать строки [line_from..line_to] включительно.  Спека 4.2."""
        if line_from < 1:
            return SSHResult(ok=False, error=f"line_from must be >= 1, got {line_from}")
        if line_to < line_from:
            return SSHResult(ok=False, error=f"line_to ({line_to}) must be >= line_from ({line_from})")

        t0 = time.monotonic()
        try:
            cmd = f"sed -n '{int(line_from)},{int(line_to)}p' {_sq(path)}"
            result = await self._run(cfg, cmd)
            ok = result.returncode == 0
            elapsed = int((time.monotonic() - t0) * 1000)
            aid = self._audit(cfg, AuditAction.READ_LINES, f"{path}:{line_from}-{line_to}",
                              model, success=ok, error=result.stderr if not ok else None,
                              duration_ms=elapsed)
            return SSHResult(ok=ok, data=result.stdout or "",
                             error=result.stderr if not ok else None, audit_id=aid)
        except Exception as exc:
            elapsed = int((time.monotonic() - t0) * 1000)
            aid = self._audit(cfg, AuditAction.READ_LINES, f"{path}:{line_from}-{line_to}",
                              model, success=False, error=str(exc), duration_ms=elapsed)
            return SSHResult(ok=False, error=str(exc), audit_id=aid)

    # ---- 4. ssh_write_file ------------------------------------------------

    async def ssh_write_file(
        self,
        cfg: ServerConfig,
        path: str,
        content: str | bytes,
        *,
        model: str = "",
        approved: bool = False,
    ) -> SSHResult:
        """
        Записать файл целиком через SFTP (атомарно: tmp → rename).

        FIX: SFTP вместо heredoc — нет shell-инъекций через content.
        FIX: проверка path + approval для protected paths.
        Спека 4.2 + 4.3.
        """
        # Проверка пути
        check_write_allowed(cfg, path)
        if not approved and is_protected_path(path):
            raise ApprovalRequired("ssh_write_file", f"Writing to protected path: {path}")

        content_bytes = content.encode("utf-8") if isinstance(content, str) else content
        if len(content_bytes) > MAX_WRITE_SIZE:
            return SSHResult(ok=False, error=f"Content too large: {len(content_bytes)} > {MAX_WRITE_SIZE} bytes")
        detail = f"write {path} ({len(content_bytes)} bytes)"
        t0 = time.monotonic()

        await self.locks.acquire_write(cfg.host, path)
        try:
            # Автобэкап
            await self._auto_backup(cfg, path, model)

            # SFTP-запись: write to tmp → atomic rename
            conn = await self._conn(cfg)
            tmp_path = f"{path}.arcane_tmp_{uuid.uuid4().hex[:8]}"
            async with conn.start_sftp_client() as sftp:
                async with sftp.open(tmp_path, "wb") as f:
                    await f.write(content_bytes)
                await sftp.rename(tmp_path, path)
                # NOTE: asyncssh rename() uses SSH_FXP_RENAME which OpenSSH
                # implements as POSIX rename (atomic overwrite). For non-OpenSSH
                # servers, consider sftp.posix_rename() which uses the
                # posix-rename@openssh.com extension explicitly.

            elapsed = int((time.monotonic() - t0) * 1000)
            aid = self._audit(cfg, AuditAction.WRITE, detail, model, duration_ms=elapsed)
            return SSHResult(ok=True, data={"path": path, "bytes": len(content_bytes)}, audit_id=aid)

        except (PathForbidden, ApprovalRequired):
            raise
        except Exception as exc:
            elapsed = int((time.monotonic() - t0) * 1000)
            aid = self._audit(cfg, AuditAction.WRITE, detail, model, success=False,
                              error=str(exc), duration_ms=elapsed)
            # Cleanup tmp
            try:
                conn2 = await self._conn(cfg)
                async with conn2.start_sftp_client() as sftp_c:
                    try:
                        await sftp_c.remove(tmp_path)
                    except Exception:
                        pass
            except Exception:
                pass
            return SSHResult(ok=False, error=str(exc), audit_id=aid)
        finally:
            self.locks.release_write(cfg.host, path)

    # ---- 5. ssh_patch_file ------------------------------------------------

    async def ssh_patch_file(
        self,
        cfg: ServerConfig,
        path: str,
        line_from: int,
        line_to: int,
        new_content: str,
        *,
        model: str = "",
        expected_hash: str | None = None,
        approved: bool = False,
    ) -> SSHResult:
        """
        Заменить строки [line_from..line_to] на new_content.

        FIX: скрипт передаётся через SFTP, path через sys.argv (не string interpolation).
        FIX: optional expected_hash для optimistic concurrency.

        Спека 4.2: ssh_patch_file(path, line_from, line_to, new).
        """
        if line_from < 1:
            return SSHResult(ok=False, error=f"line_from must be >= 1, got {line_from}")
        if line_to < line_from:
            return SSHResult(ok=False, error=f"line_to ({line_to}) must be >= line_from ({line_from})")

        check_write_allowed(cfg, path)
        if not approved and is_protected_path(path):
            raise ApprovalRequired("ssh_patch_file", f"Patching protected path: {path}")

        detail = f"patch {path} lines {line_from}-{line_to}"
        t0 = time.monotonic()

        await self.locks.acquire_write(cfg.host, path)
        try:
            await self._auto_backup(cfg, path, model)

            # FIX: path через sys.argv, new_content через json.dumps
            patch_script = _build_patch_script_safe(line_from, line_to, new_content, expected_hash)

            # Загружаем скрипт через SFTP
            conn = await self._conn(cfg)
            script_remote = f"/tmp/.arcane_patch_{uuid.uuid4().hex[:8]}.py"
            async with conn.start_sftp_client() as sftp:
                async with sftp.open(script_remote, "w") as f:
                    await f.write(patch_script)

            # Выполняем: path передаётся как shell-escaped аргумент
            result = await self._run(cfg, f"python3 {_sq(script_remote)} {_sq(path)}", timeout=30)
            # Удаляем скрипт
            await self._run(cfg, f"rm -f {_sq(script_remote)}")

            ok = result.returncode == 0
            elapsed = int((time.monotonic() - t0) * 1000)
            aid = self._audit(cfg, AuditAction.PATCH, detail, model, success=ok,
                              error=result.stderr if not ok else None, duration_ms=elapsed)
            return SSHResult(ok=ok, data={"path": path, "lines": f"{line_from}-{line_to}"},
                             error=result.stderr if not ok else None, audit_id=aid)
        except (PathForbidden, ApprovalRequired):
            raise
        except Exception as exc:
            elapsed = int((time.monotonic() - t0) * 1000)
            aid = self._audit(cfg, AuditAction.PATCH, detail, model, success=False,
                              error=str(exc), duration_ms=elapsed)
            return SSHResult(ok=False, error=str(exc), audit_id=aid)
        finally:
            self.locks.release_write(cfg.host, path)

    # ---- 6. ssh_list_dir --------------------------------------------------

    async def ssh_list_dir(
        self,
        cfg: ServerConfig,
        path: str,
        *,
        model: str = "",
    ) -> SSHResult:
        """Список файлов в директории.  Спека 4.2."""
        t0 = time.monotonic()
        try:
            cmd = f"ls -lah --color=never {_sq(path)}"
            result = await self._run(cfg, cmd)
            ok = result.returncode == 0
            elapsed = int((time.monotonic() - t0) * 1000)
            aid = self._audit(cfg, AuditAction.LIST_DIR, path, model, success=ok,
                              error=result.stderr if not ok else None, duration_ms=elapsed)
            return SSHResult(ok=ok, data=result.stdout or "",
                             error=result.stderr if not ok else None, audit_id=aid)
        except Exception as exc:
            elapsed = int((time.monotonic() - t0) * 1000)
            aid = self._audit(cfg, AuditAction.LIST_DIR, path, model, success=False,
                              error=str(exc), duration_ms=elapsed)
            return SSHResult(ok=False, error=str(exc), audit_id=aid)

    # ---- 7. ssh_backup ----------------------------------------------------

    async def ssh_backup(
        self,
        cfg: ServerConfig,
        path: str,
        *,
        model: str = "",
    ) -> SSHResult:
        """Ручной бэкап файла или директории.  Спека 4.2."""
        t0 = time.monotonic()
        try:
            await self._ensure_backup_dir(cfg)
            backup_path = self._backup_name(cfg, path)
            cmd = f"cp -a {_sq(path)} {_sq(backup_path)}"
            result = await self._run(cfg, cmd)
            ok = result.returncode == 0
            elapsed = int((time.monotonic() - t0) * 1000)
            aid = self._audit(cfg, AuditAction.BACKUP, f"{path} → {backup_path}", model,
                              success=ok, error=result.stderr if not ok else None,
                              duration_ms=elapsed)
            return SSHResult(ok=ok, data={"backup_path": backup_path},
                             error=result.stderr if not ok else None, audit_id=aid)
        except Exception as exc:
            elapsed = int((time.monotonic() - t0) * 1000)
            aid = self._audit(cfg, AuditAction.BACKUP, path, model, success=False,
                              error=str(exc), duration_ms=elapsed)
            return SSHResult(ok=False, error=str(exc), audit_id=aid)

    # ---- 8. ssh_restore ---------------------------------------------------

    async def ssh_restore(
        self,
        cfg: ServerConfig,
        path: str,
        *,
        backup_path: str | None = None,
        model: str = "",
        approved: bool = False,
    ) -> SSHResult:
        """
        Откат файла из бэкапа.

        FIX: backup_path валидируется через realpath (внутри backup_dir).
        FIX: берём write-lock.
        FIX: approval для protected paths.

        Спека 4.2: ssh_restore(path) — откат.
        """
        check_write_allowed(cfg, path)
        if not approved and is_protected_path(path):
            raise ApprovalRequired("ssh_restore", f"Restoring to protected path: {path}")

        t0 = time.monotonic()
        bdir = self._backup_dir(cfg)

        await self.locks.acquire_write(cfg.host, path)
        try:
            if not backup_path:
                # FIX: safe escaping для поиска бэкапов
                safe = path.replace("/", "__")
                # Используем shell-escaped имена для безопасности
                find_cmd = f"ls -t {_sq(bdir)}/{_sq(safe)}.*.bak 2>/dev/null | head -1"
                find_result = await self._run(cfg, find_cmd)
                backup_path = (find_result.stdout or "").strip()
                if not backup_path:
                    return SSHResult(ok=False, error=f"No backup found for {path}")

            # FIX: валидация через realpath — ловим symlink-атаки
            real_result = await self._run(cfg, f"realpath {_sq(backup_path)}")
            real_backup = (real_result.stdout or "").strip()
            if not real_backup.startswith(bdir + "/"):
                return SSHResult(
                    ok=False,
                    error=f"Backup path resolves to {real_backup} which is outside {bdir}/",
                )

            cmd = f"cp -a {_sq(real_backup)} {_sq(path)}"
            result = await self._run(cfg, cmd)
            ok = result.returncode == 0
            elapsed = int((time.monotonic() - t0) * 1000)
            aid = self._audit(cfg, AuditAction.RESTORE, f"{real_backup} → {path}", model,
                              success=ok, error=result.stderr if not ok else None,
                              duration_ms=elapsed)
            return SSHResult(ok=ok, data={"restored_from": real_backup},
                             error=result.stderr if not ok else None, audit_id=aid)
        except (PathForbidden, ApprovalRequired):
            raise
        except Exception as exc:
            elapsed = int((time.monotonic() - t0) * 1000)
            aid = self._audit(cfg, AuditAction.RESTORE, path, model, success=False,
                              error=str(exc), duration_ms=elapsed)
            return SSHResult(ok=False, error=str(exc), audit_id=aid)
        finally:
            self.locks.release_write(cfg.host, path)

    # ---- 9. ssh_tail_log --------------------------------------------------

    async def ssh_tail_log(
        self,
        cfg: ServerConfig,
        path: str,
        n: int = 100,
        *,
        model: str = "",
    ) -> SSHResult:
        """Последние N строк лога.  Спека 4.2: ssh_tail_log(path, n)."""
        if n <= 0:
            return SSHResult(ok=False, error=f"n must be positive, got {n}")
        n = min(n, MAX_TAIL_LINES)

        t0 = time.monotonic()
        try:
            cmd = f"tail -n {int(n)} {_sq(path)}"
            result = await self._run(cfg, cmd)
            ok = result.returncode == 0
            elapsed = int((time.monotonic() - t0) * 1000)
            aid = self._audit(cfg, AuditAction.TAIL_LOG, f"{path} (last {n})", model,
                              success=ok, error=result.stderr if not ok else None,
                              duration_ms=elapsed)
            return SSHResult(ok=ok, data=result.stdout or "",
                             error=result.stderr if not ok else None, audit_id=aid)
        except Exception as exc:
            elapsed = int((time.monotonic() - t0) * 1000)
            aid = self._audit(cfg, AuditAction.TAIL_LOG, f"{path} (last {n})", model,
                              success=False, error=str(exc), duration_ms=elapsed)
            return SSHResult(ok=False, error=str(exc), audit_id=aid)

    # ---- 10. ssh_batch ----------------------------------------------------

    async def ssh_batch(
        self,
        cfg: ServerConfig,
        commands: Sequence[str],
        *,
        model: str = "",
        approved: bool = False,
        stop_on_error: bool = False,
        total_timeout: float = 300,
    ) -> SSHResult:
        """
        Пакетное выполнение N команд за ОДИН SSH-вызов.

        FIX: команды объединяются в один shell-скрипт и выполняются
        одним conn.run(), а не N отдельными round-trip'ами.

        Спека 5.3: «Вместо 5 последовательных SSH-вызовов — один batch.
        Радикально снижает latency.»
        """
        if not commands:
            return SSHResult(ok=False, error="commands list is empty")
        if len(commands) > MAX_BATCH_COMMANDS:
            return SSHResult(ok=False, error=f"Too many commands: {len(commands)} > {MAX_BATCH_COMMANDS}")

        # Pre-flight: проверить ВСЕ команды ДО выполнения
        if not approved:
            for i, cmd in enumerate(commands):
                danger = detect_destructive(cmd)
                if danger:
                    raise ApprovalRequired("ssh_batch", f"Command #{i}: {cmd!r}. {danger}")

        t0 = time.monotonic()
        marker = f"__ARCANE_BATCH_{uuid.uuid4().hex[:8]}__"

        # Строим один shell-скрипт с маркерами между командами.
        # При stop_on_error: каждая команда проверяет exit code и прерывает batch.
        parts = []
        for i, cmd in enumerate(commands):
            if stop_on_error:
                parts.append(
                    f"( {cmd} ); __ec=$?; echo '{marker}|{i}|'$__ec; "
                    f"[ $__ec -ne 0 ] && exit $__ec"
                )
            else:
                parts.append(f"( {cmd} ); __ec=$?; echo '{marker}|{i}|'$__ec")
        batch_cmd = " ; ".join(parts)

        try:
            result = await self._run(cfg, batch_cmd, timeout=total_timeout,
                                     max_output=MAX_EXEC_OUTPUT * 2)
            stdout_full = result.stdout or ""
            parsed_results = _parse_batch_output(stdout_full, marker, commands)

            all_ok = all(r["ok"] for r in parsed_results)
            elapsed = int((time.monotonic() - t0) * 1000)
            aid = self._audit(cfg, AuditAction.BATCH, f"batch({len(commands)} cmds)", model,
                              success=all_ok, duration_ms=elapsed)
            return SSHResult(ok=all_ok, data=parsed_results, audit_id=aid)
        except Exception as exc:
            elapsed = int((time.monotonic() - t0) * 1000)
            aid = self._audit(cfg, AuditAction.BATCH, f"batch({len(commands)} cmds)", model,
                              success=False, error=str(exc), duration_ms=elapsed)
            return SSHResult(ok=False, error=str(exc), audit_id=aid)

    # ---- internal ---------------------------------------------------------

    async def _auto_backup(self, cfg: ServerConfig, path: str, model: str) -> None:
        """
        Автобэкап перед записью.  Спека 4.3.

        FIX: одна команда cp без TOCTOU-разрыва (test -f → cp).
        Если файла нет — cp вернёт ошибку, игнорируем.
        """
        await self._ensure_backup_dir(cfg)
        backup_path = self._backup_name(cfg, path)
        result = await self._run(cfg, f"cp -a {_sq(path)} {_sq(backup_path)} 2>/dev/null")
        if result.returncode == 0:
            logger.info("Auto-backup: %s → %s", path, backup_path)

    async def close(self) -> None:
        """Закрыть все SSH-соединения."""
        await self.pool.close_all()


# ---------------------------------------------------------------------------
# LLM Tool Definitions (для оркестратора)
# ---------------------------------------------------------------------------

TOOL_DEFINITIONS: list[dict] = [
    {
        "name": "ssh_exec",
        "description": "Execute a shell command on the remote server. Destructive commands require approval.",
        "parameters": {
            "type": "object",
            "properties": {
                "server_id": {"type": "string", "description": "Server identifier from project config"},
                "cmd": {"type": "string", "description": "Shell command to execute"},
            },
            "required": ["server_id", "cmd"],
        },
    },
    {
        "name": "ssh_read_file",
        "description": "Read an entire file from the remote server (up to 5MB).",
        "parameters": {
            "type": "object",
            "properties": {
                "server_id": {"type": "string"},
                "path": {"type": "string", "description": "Absolute path to the file"},
            },
            "required": ["server_id", "path"],
        },
    },
    {
        "name": "ssh_read_lines",
        "description": "Read a specific line range from a file. line_from >= 1, line_to >= line_from.",
        "parameters": {
            "type": "object",
            "properties": {
                "server_id": {"type": "string"},
                "path": {"type": "string"},
                "line_from": {"type": "integer", "minimum": 1},
                "line_to": {"type": "integer", "minimum": 1},
            },
            "required": ["server_id", "path", "line_from", "line_to"],
        },
    },
    {
        "name": "ssh_write_file",
        "description": "Write content to a file via SFTP (atomic). Auto-backup. Protected paths require approval.",
        "parameters": {
            "type": "object",
            "properties": {
                "server_id": {"type": "string"},
                "path": {"type": "string"},
                "content": {"type": "string"},
            },
            "required": ["server_id", "path", "content"],
        },
    },
    {
        "name": "ssh_patch_file",
        "description": "Replace lines by number via SFTP. Auto-backup. Optional expected_hash for concurrency.",
        "parameters": {
            "type": "object",
            "properties": {
                "server_id": {"type": "string"},
                "path": {"type": "string"},
                "line_from": {"type": "integer", "minimum": 1},
                "line_to": {"type": "integer", "minimum": 1},
                "new_content": {"type": "string"},
                "expected_hash": {"type": "string", "description": "SHA-256 of old content for optimistic locking"},
            },
            "required": ["server_id", "path", "line_from", "line_to", "new_content"],
        },
    },
    {
        "name": "ssh_list_dir",
        "description": "List files and directories at a path.",
        "parameters": {
            "type": "object",
            "properties": {
                "server_id": {"type": "string"},
                "path": {"type": "string"},
            },
            "required": ["server_id", "path"],
        },
    },
    {
        "name": "ssh_backup",
        "description": "Create a manual backup of a file or directory.",
        "parameters": {
            "type": "object",
            "properties": {
                "server_id": {"type": "string"},
                "path": {"type": "string"},
            },
            "required": ["server_id", "path"],
        },
    },
    {
        "name": "ssh_restore",
        "description": "Restore from backup. Validates backup_path is inside backup dir. Protected paths require approval.",
        "parameters": {
            "type": "object",
            "properties": {
                "server_id": {"type": "string"},
                "path": {"type": "string"},
                "backup_path": {"type": "string", "description": "Optional specific backup path"},
            },
            "required": ["server_id", "path"],
        },
    },
    {
        "name": "ssh_tail_log",
        "description": "Read the last N lines of a log file (max 10,000).",
        "parameters": {
            "type": "object",
            "properties": {
                "server_id": {"type": "string"},
                "path": {"type": "string"},
                "n": {"type": "integer", "default": 100, "maximum": 10000},
            },
            "required": ["server_id", "path"],
        },
    },
    {
        "name": "ssh_batch",
        "description": "Execute multiple commands in ONE SSH call. Max 50 commands.",
        "parameters": {
            "type": "object",
            "properties": {
                "server_id": {"type": "string"},
                "commands": {"type": "array", "items": {"type": "string"}, "maxItems": 50},
                "stop_on_error": {"type": "boolean", "default": False},
            },
            "required": ["server_id", "commands"],
        },
    },
]


# ---------------------------------------------------------------------------
# Утилиты
# ---------------------------------------------------------------------------

def _sq(s: str) -> str:
    """Shell-safe single-quote escaping."""
    return "'" + s.replace("'", "'\\''") + "'"


def _build_patch_script_safe(
    line_from: int,
    line_to: int,
    new_content: str,
    expected_hash: str | None = None,
) -> str:
    """
    Генерирует Python-скрипт для line-based patching.

    FIX: path берётся из sys.argv[1], не из string interpolation → нет code injection.
    new_content передаётся через json.dumps → безопасная сериализация.
    expected_hash → optimistic concurrency control.
    """
    content_json = json.dumps(new_content, ensure_ascii=False)
    hash_json = json.dumps(expected_hash) if expected_hash else "None"

    return f'''#!/usr/bin/env python3
"""Arcane 2 patch script — auto-generated, do not edit."""
import hashlib
import json
import pathlib
import sys

if len(sys.argv) < 2:
    print("Usage: patch.py <filepath>", file=sys.stderr)
    sys.exit(1)

filepath = pathlib.Path(sys.argv[1])
if not filepath.exists():
    print(f"File not found: {{filepath}}", file=sys.stderr)
    sys.exit(1)

lines = filepath.read_text(encoding="utf-8").splitlines(True)

line_from = {line_from}
line_to = {line_to}
new_content = json.loads({json.dumps(content_json, ensure_ascii=False)})
expected_hash = {hash_json}

if line_from < 1 or line_to < line_from or line_from > len(lines):
    print(f"Invalid range: {{line_from}}-{{line_to}} (file has {{len(lines)}} lines)", file=sys.stderr)
    sys.exit(1)

# Optimistic concurrency: check hash of old content
if expected_hash is not None:
    old_slice = "".join(lines[line_from - 1 : line_to])
    actual_hash = hashlib.sha256(old_slice.encode("utf-8")).hexdigest()
    if actual_hash != expected_hash:
        print(f"Hash mismatch: expected {{expected_hash}}, got {{actual_hash}}. File was modified.", file=sys.stderr)
        sys.exit(2)

# Apply patch
new_lines = new_content.splitlines(True)
new_lines = [l if l.endswith("\\n") else l + "\\n" for l in new_lines] if new_lines else []
lines[line_from - 1 : line_to] = new_lines

# Atomic write: tmp file → rename (same pattern as ssh_write_file)
import tempfile, os
tmp_fd, tmp_path = tempfile.mkstemp(dir=str(filepath.parent), suffix=".arcane_patch")
closed = False
try:
    os.write(tmp_fd, "".join(lines).encode("utf-8"))
    os.close(tmp_fd)
    closed = True
    os.rename(tmp_path, str(filepath))
except BaseException:
    if not closed:
        os.close(tmp_fd)
    try:
        os.unlink(tmp_path)
    except OSError:
        pass
    raise
print(f"Patched lines {{line_from}}-{{line_to}} ({{len(new_lines)}} new lines)")
'''


def _parse_batch_output(
    stdout: str,
    marker: str,
    commands: Sequence[str],
) -> list[dict]:
    """Парсит вывод batch-команды, разделённый маркерами."""
    results: list[dict] = []
    segments = stdout.split(marker)

    outputs: list[str] = []
    exit_codes: list[int] = []

    for i, seg in enumerate(segments):
        if i == 0:
            outputs.append(seg.rstrip("\n"))
            continue
        lines_in_seg = seg.split("\n", 1)
        header = lines_in_seg[0]
        parts = header.split("|")
        if len(parts) >= 3:
            try:
                exit_codes.append(int(parts[2]))
            except ValueError:
                exit_codes.append(-1)
        else:
            exit_codes.append(-1)
        if len(lines_in_seg) > 1:
            outputs.append(lines_in_seg[1].rstrip("\n"))

    for i, cmd in enumerate(commands):
        ec = exit_codes[i] if i < len(exit_codes) else -1
        out = outputs[i] if i < len(outputs) else ""
        results.append({
            "index": i,
            "cmd": cmd,
            "ok": ec == 0,
            "stdout": _truncate_output(out),
            "exit_code": ec,
        })

    return results

SSHWorker = SSHToolError  # compatibility alias
