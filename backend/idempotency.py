"""
Idempotency Module — Гарантия идемпотентности мутирующих операций.

Покрывает:
- file_write: повторная запись того же файла с тем же содержимым — не дублируется
- ssh_execute: команды с побочными эффектами (mkdir, apt install) — не повторяются
- Создание чатов/пользователей — дедупликация по ключу
- API запросы — защита от двойных кликов

Стратегия:
1. Клиент передаёт Idempotency-Key в заголовке (или генерируется из хеша параметров)
2. Сервер проверяет: если ключ уже есть — возвращает кешированный результат
3. TTL: 1 час для API, 5 минут для tool operations
"""

import hashlib
import json
import time
import threading
import os
from typing import Any, Optional, Dict, Tuple
from datetime import datetime, timezone


class IdempotencyStore:
    """
    Хранилище ключей идемпотентности.
    In-memory с опциональным persistence в JSON файл.
    """

    def __init__(self, persist_path: Optional[str] = None, default_ttl: int = 3600):
        self._store: Dict[str, Dict] = {}
        self._lock = threading.Lock()
        self._persist_path = persist_path
        self._default_ttl = default_ttl
        self._stats = {
            "total_checks": 0,
            "cache_hits": 0,
            "cache_misses": 0,
            "total_stored": 0,
        }

        if persist_path and os.path.exists(persist_path):
            try:
                with open(persist_path, "r") as f:
                    data = json.load(f)
                    self._store = data.get("store", {})
                    # Очистить просроченные
                    self._cleanup()
            except (json.JSONDecodeError, IOError):
                self._store = {}

    def _cleanup(self):
        """Удалить просроченные записи."""
        now = time.time()
        expired = [k for k, v in self._store.items() if now > v.get("expires_at", 0)]
        for k in expired:
            del self._store[k]

    def _persist(self):
        """Сохранить на диск если настроен persist_path."""
        if not self._persist_path:
            return
        try:
            tmp = self._persist_path + ".tmp"
            with open(tmp, "w") as f:
                json.dump({"store": self._store, "updated_at": time.time()}, f, ensure_ascii=False)
            os.replace(tmp, self._persist_path)
        except IOError:
            pass

    def check(self, key: str) -> Tuple[bool, Optional[Any]]:
        """
        Проверить ключ идемпотентности.

        Returns:
            (is_duplicate, cached_result)
            - (True, result) — дубликат, вернуть кешированный результат
            - (False, None) — новый запрос, нужно выполнить
        """
        with self._lock:
            self._stats["total_checks"] += 1

            if key in self._store:
                entry = self._store[key]
                if time.time() <= entry.get("expires_at", 0):
                    self._stats["cache_hits"] += 1
                    return True, entry.get("result")
                else:
                    # Просрочен — удалить
                    del self._store[key]

            self._stats["cache_misses"] += 1
            return False, None

    def store(self, key: str, result: Any, ttl: Optional[int] = None):
        """Сохранить результат для ключа идемпотентности."""
        with self._lock:
            self._stats["total_stored"] += 1
            self._store[key] = {
                "result": result,
                "created_at": time.time(),
                "expires_at": time.time() + (ttl or self._default_ttl),
            }

            # Периодическая очистка (каждые 100 записей)
            if len(self._store) % 100 == 0:
                self._cleanup()

            self._persist()

    def invalidate(self, key: str):
        """Удалить ключ (при необходимости принудительного повтора)."""
        with self._lock:
            self._store.pop(key, None)
            self._persist()

    @property
    def stats(self):
        return {**self._stats, "active_keys": len(self._store)}


# ── Глобальные хранилища ─────────────────────────────────────────

# Для API запросов (TTL 1 час)
_api_store = IdempotencyStore(default_ttl=3600)

# Для tool операций (TTL 5 минут)
_tool_store = IdempotencyStore(default_ttl=300)

# Для file_write (TTL 10 минут)
_file_store = IdempotencyStore(default_ttl=600)


def get_api_store() -> IdempotencyStore:
    return _api_store


def get_tool_store() -> IdempotencyStore:
    return _tool_store


def get_file_store() -> IdempotencyStore:
    return _file_store


# ── Генерация ключей идемпотентности ─────────────────────────────

def make_key(*args, **kwargs) -> str:
    """
    Генерировать ключ идемпотентности из произвольных аргументов.
    Используется SHA-256 хеш от JSON-сериализации параметров.
    """
    data = json.dumps({"args": args, "kwargs": kwargs}, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(data.encode()).hexdigest()[:32]


def make_file_key(host: str, path: str, content: str) -> str:
    """Ключ идемпотентности для file_write."""
    content_hash = hashlib.sha256(content.encode()).hexdigest()[:16]
    return f"file:{host}:{path}:{content_hash}"


def make_ssh_key(host: str, command: str) -> str:
    """Ключ идемпотентности для ssh_execute (только для идемпотентных команд)."""
    cmd_hash = hashlib.sha256(command.encode()).hexdigest()[:16]
    return f"ssh:{host}:{cmd_hash}"


def make_api_key(user_id: str, endpoint: str, body_hash: str) -> str:
    """Ключ идемпотентности для API запросов."""
    return f"api:{user_id}:{endpoint}:{body_hash}"


# ── Классификация команд по идемпотентности ──────────────────────

# Команды, которые безопасно повторять (идемпотентные)
IDEMPOTENT_COMMANDS = {
    "ls", "cat", "head", "tail", "grep", "find", "which", "whoami",
    "hostname", "uname", "uptime", "df", "du", "free", "top",
    "ps", "netstat", "ss", "ip", "ifconfig", "ping",
    "systemctl status", "journalctl", "docker ps", "docker logs",
    "git status", "git log", "git diff", "git branch",
    "npm list", "pip list", "pip show",
    "test", "stat", "file", "wc", "sort", "uniq",
    "echo", "date", "env", "printenv",
}

# Команды с побочными эффектами (НЕ идемпотентные — нужен ключ)
MUTATING_COMMANDS = {
    "rm", "mv", "cp", "mkdir", "touch", "chmod", "chown",
    "apt", "apt-get", "yum", "dnf", "pip install", "npm install",
    "systemctl start", "systemctl stop", "systemctl restart", "systemctl enable",
    "docker run", "docker stop", "docker rm", "docker build",
    "git add", "git commit", "git push", "git pull", "git checkout",
    "sed", "awk", "tee", "truncate",
    "useradd", "userdel", "passwd",
    "iptables", "ufw",
}


def is_idempotent_command(command: str) -> bool:
    """Проверить, является ли SSH команда идемпотентной."""
    cmd_parts = command.strip().split()
    if not cmd_parts:
        return True

    base_cmd = cmd_parts[0].split("/")[-1]  # Убрать путь

    # Проверить базовую команду
    if base_cmd in IDEMPOTENT_COMMANDS:
        return True

    # Проверить составные команды (systemctl status, etc.)
    if len(cmd_parts) >= 2:
        two_word = f"{base_cmd} {cmd_parts[1]}"
        if two_word in IDEMPOTENT_COMMANDS:
            return True

    return False


def is_mutating_command(command: str) -> bool:
    """Проверить, является ли SSH команда мутирующей."""
    cmd_parts = command.strip().split()
    if not cmd_parts:
        return False

    base_cmd = cmd_parts[0].split("/")[-1]

    if base_cmd in MUTATING_COMMANDS:
        return True

    if len(cmd_parts) >= 2:
        two_word = f"{base_cmd} {cmd_parts[1]}"
        if two_word in MUTATING_COMMANDS:
            return True

    return False


# ── Декоратор идемпотентности для Flask endpoints ────────────────

def idempotent_endpoint(store: Optional[IdempotencyStore] = None, ttl: int = 3600):
    """
    Декоратор для Flask endpoints — проверяет Idempotency-Key заголовок.
    Если ключ уже есть — возвращает кешированный ответ.
    """
    import functools
    from flask import request, jsonify

    _store = store or _api_store

    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            # Получить ключ из заголовка или сгенерировать
            idem_key = request.headers.get("Idempotency-Key", "")
            if not idem_key:
                # Автогенерация из body + endpoint
                body = request.get_data(as_text=True) or ""
                body_hash = hashlib.sha256(body.encode()).hexdigest()[:16]
                user_id = getattr(request, "user_id", "anon")
                idem_key = make_api_key(str(user_id), request.path, body_hash)

            # Проверить кеш
            is_dup, cached = _store.check(idem_key)
            if is_dup and cached is not None:
                return cached

            # Выполнить
            result = func(*args, **kwargs)

            # Сохранить результат
            # Для Flask Response — сохраняем только JSON
            try:
                if hasattr(result, "get_json"):
                    _store.store(idem_key, result, ttl=ttl)
                elif isinstance(result, tuple):
                    _store.store(idem_key, result, ttl=ttl)
            except Exception:
                pass

            return result

        return wrapper
    return decorator


# ── Статистика ───────────────────────────────────────────────────

def get_idempotency_stats() -> dict:
    """Получить статистику всех хранилищ идемпотентности."""
    return {
        "api": _api_store.stats,
        "tool": _tool_store.stats,
        "file": _file_store.stats,
    }
