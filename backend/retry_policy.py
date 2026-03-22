"""
Retry Policy — Единая политика повторных попыток для всех внешних вызовов.

Покрывает:
- OpenRouter API (LLM calls) — retry на 429, 500, 502, 503, 504, таймауты
- SSH/Paramiko — retry на ConnectionError, AuthenticationException, socket.timeout
- Requests (Browser Agent) — retry на ConnectionError, Timeout, 5xx
- SFTP операции — retry на IOError, SSHException

Стратегия: Exponential backoff с jitter.
  base_delay * (2 ** attempt) + random(0, jitter)

По умолчанию: 3 попытки, base_delay=1s, max_delay=30s, jitter=0.5s
"""

import time
import random
import functools
import logging
import traceback
from typing import Callable, Tuple, Type, Optional, Any

logger = logging.getLogger("retry_policy")


# ── Исключения для классификации ошибок ──────────────────────────

class RetryableError(Exception):
    """Ошибка, которую имеет смысл повторить."""
    pass


class NonRetryableError(Exception):
    """Ошибка, которую повторять бессмысленно (400, 401, 404)."""
    pass


class CircuitBreakerOpen(Exception):
    """Circuit breaker разомкнут — сервис недоступен."""
    pass


# ── Retry Decorator ──────────────────────────────────────────────

def retry(
    max_attempts: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 30.0,
    jitter: float = 0.5,
    retryable_exceptions: Tuple[Type[Exception], ...] = (Exception,),
    non_retryable_exceptions: Tuple[Type[Exception], ...] = (),
    on_retry: Optional[Callable] = None,
    context: str = "unknown"
):
    """
    Декоратор retry с exponential backoff + jitter.

    Args:
        max_attempts: Максимум попыток (включая первую)
        base_delay: Базовая задержка в секундах
        max_delay: Максимальная задержка
        jitter: Случайный разброс (0..jitter секунд)
        retryable_exceptions: Исключения, при которых повторяем
        non_retryable_exceptions: Исключения, при которых НЕ повторяем
        on_retry: Callback(attempt, exception, delay) при каждом retry
        context: Название контекста для логирования
    """
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            last_exception = None

            for attempt in range(1, max_attempts + 1):
                try:
                    return func(*args, **kwargs)

                except non_retryable_exceptions as e:
                    # Не повторяем — сразу пробрасываем
                    logger.warning(f"[{context}] Non-retryable error on attempt {attempt}: {e}")
                    raise

                except retryable_exceptions as e:
                    last_exception = e

                    if attempt >= max_attempts:
                        logger.error(
                            f"[{context}] All {max_attempts} attempts failed. "
                            f"Last error: {e}"
                        )
                        raise

                    # Exponential backoff + jitter
                    delay = min(base_delay * (2 ** (attempt - 1)), max_delay)
                    delay += random.uniform(0, jitter)

                    logger.warning(
                        f"[{context}] Attempt {attempt}/{max_attempts} failed: {e}. "
                        f"Retrying in {delay:.1f}s..."
                    )

                    if on_retry:
                        try:
                            on_retry(attempt, e, delay)
                        except Exception:
                            pass

                    time.sleep(delay)

            # Shouldn't reach here, but just in case
            if last_exception:
                raise last_exception

        return wrapper
    return decorator


def retry_generator(
    max_attempts: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 30.0,
    jitter: float = 0.5,
    retryable_exceptions: Tuple[Type[Exception], ...] = (Exception,),
    non_retryable_exceptions: Tuple[Type[Exception], ...] = (),
    context: str = "unknown"
):
    """
    Декоратор retry для генераторов (yield).
    При ошибке перезапускает генератор с начала.
    """
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            last_exception = None

            for attempt in range(1, max_attempts + 1):
                try:
                    yield from func(*args, **kwargs)
                    return  # Успешно завершился

                except non_retryable_exceptions as e:
                    raise

                except retryable_exceptions as e:
                    last_exception = e

                    if attempt >= max_attempts:
                        logger.error(f"[{context}] Generator: all {max_attempts} attempts failed: {e}")
                        raise

                    delay = min(base_delay * (2 ** (attempt - 1)), max_delay)
                    delay += random.uniform(0, jitter)
                    logger.warning(f"[{context}] Generator attempt {attempt} failed: {e}. Retry in {delay:.1f}s")
                    time.sleep(delay)

            if last_exception:
                raise last_exception

        return wrapper
    return decorator


# ── Circuit Breaker ──────────────────────────────────────────────

class CircuitBreaker:
    """
    Circuit Breaker паттерн для защиты от каскадных сбоев.

    Состояния:
    - CLOSED: нормальная работа, считаем ошибки
    - OPEN: сервис недоступен, сразу отказываем
    - HALF_OPEN: пробуем одну попытку, если ок — закрываем
    """

    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"

    def __init__(self, name: str, failure_threshold: int = 5,
                 recovery_timeout: float = 60.0, success_threshold: int = 2):
        self.name = name
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.success_threshold = success_threshold

        self.state = self.CLOSED
        self.failure_count = 0
        self.success_count = 0
        self.last_failure_time = 0
        self._stats = {"total_calls": 0, "total_failures": 0, "total_opens": 0}

    def can_execute(self) -> bool:
        """Проверить можно ли выполнять запрос."""
        if self.state == self.CLOSED:
            return True
        elif self.state == self.OPEN:
            if time.time() - self.last_failure_time >= self.recovery_timeout:
                self.state = self.HALF_OPEN
                self.success_count = 0
                logger.info(f"[CircuitBreaker:{self.name}] OPEN -> HALF_OPEN")
                return True
            return False
        elif self.state == self.HALF_OPEN:
            return True
        return False

    def record_success(self):
        """Записать успешный вызов."""
        self._stats["total_calls"] += 1
        if self.state == self.HALF_OPEN:
            self.success_count += 1
            if self.success_count >= self.success_threshold:
                self.state = self.CLOSED
                self.failure_count = 0
                logger.info(f"[CircuitBreaker:{self.name}] HALF_OPEN -> CLOSED")
        elif self.state == self.CLOSED:
            self.failure_count = max(0, self.failure_count - 1)

    def record_failure(self):
        """Записать неудачный вызов."""
        self._stats["total_calls"] += 1
        self._stats["total_failures"] += 1
        self.failure_count += 1
        self.last_failure_time = time.time()

        if self.state == self.HALF_OPEN:
            self.state = self.OPEN
            self._stats["total_opens"] += 1
            logger.warning(f"[CircuitBreaker:{self.name}] HALF_OPEN -> OPEN")
        elif self.state == self.CLOSED and self.failure_count >= self.failure_threshold:
            self.state = self.OPEN
            self._stats["total_opens"] += 1
            logger.warning(f"[CircuitBreaker:{self.name}] CLOSED -> OPEN (failures: {self.failure_count})")

    @property
    def stats(self):
        return {**self._stats, "state": self.state, "failure_count": self.failure_count}


# ── Предустановленные Circuit Breakers ───────────────────────────

_breakers = {}


def get_breaker(name: str, **kwargs) -> CircuitBreaker:
    """Получить или создать circuit breaker по имени."""
    if name not in _breakers:
        _breakers[name] = CircuitBreaker(name, **kwargs)
    return _breakers[name]


def get_all_breaker_stats() -> dict:
    """Получить статистику всех circuit breakers."""
    return {name: cb.stats for name, cb in _breakers.items()}


# ── Retry-обёртки для конкретных сервисов ────────────────────────

# HTTP-ошибки, которые имеет смысл повторять
RETRYABLE_HTTP_CODES = {429, 500, 502, 503, 504, 520, 521, 522, 523, 524}
NON_RETRYABLE_HTTP_CODES = {400, 401, 403, 404, 405, 409, 422}


def is_retryable_http_error(response) -> bool:
    """Проверить, стоит ли повторять HTTP запрос."""
    if response is None:
        return True
    return response.status_code in RETRYABLE_HTTP_CODES


def retry_http_call(func, *args, max_attempts=3, context="http", **kwargs):
    """
    Retry-обёртка для HTTP вызовов с проверкой status code.
    Возвращает response или бросает исключение.
    """
    import requests as http_requests

    breaker = get_breaker(context, failure_threshold=5, recovery_timeout=60)
    last_error = None

    for attempt in range(1, max_attempts + 1):
        if not breaker.can_execute():
            raise CircuitBreakerOpen(f"Circuit breaker [{context}] is OPEN")

        try:
            response = func(*args, **kwargs)

            if response.status_code in NON_RETRYABLE_HTTP_CODES:
                breaker.record_success()  # Сервис работает, просто ошибка клиента
                return response

            if response.status_code in RETRYABLE_HTTP_CODES:
                breaker.record_failure()
                last_error = f"HTTP {response.status_code}"

                if attempt >= max_attempts:
                    return response  # Вернуть последний ответ

                delay = min(1.0 * (2 ** (attempt - 1)), 30.0) + random.uniform(0, 0.5)

                # Respect Retry-After header
                retry_after = response.headers.get("Retry-After")
                if retry_after:
                    try:
                        delay = max(delay, float(retry_after))
                    except ValueError:
                        pass

                logger.warning(f"[{context}] HTTP {response.status_code}, retry {attempt}/{max_attempts} in {delay:.1f}s")
                time.sleep(delay)
                continue

            # Success
            breaker.record_success()
            return response

        except (http_requests.ConnectionError, http_requests.Timeout,
                ConnectionError, TimeoutError, OSError) as e:
            breaker.record_failure()
            last_error = str(e)

            if attempt >= max_attempts:
                raise

            delay = min(1.0 * (2 ** (attempt - 1)), 30.0) + random.uniform(0, 0.5)
            logger.warning(f"[{context}] Connection error: {e}, retry {attempt}/{max_attempts} in {delay:.1f}s")
            time.sleep(delay)

    raise Exception(f"[{context}] All {max_attempts} attempts failed: {last_error}")


# ── SSH Retry ────────────────────────────────────────────────────

def retry_ssh(max_attempts=3, base_delay=2.0):
    """Декоратор retry специально для SSH операций."""
    import paramiko

    return retry(
        max_attempts=max_attempts,
        base_delay=base_delay,
        max_delay=30.0,
        jitter=1.0,
        retryable_exceptions=(
            paramiko.SSHException,
            paramiko.AuthenticationException,
            ConnectionError,
            TimeoutError,
            OSError,
            IOError,
            EOFError,
        ),
        non_retryable_exceptions=(
            ValueError,  # Неправильные параметры
            FileNotFoundError,
        ),
        context="ssh"
    )


# ── LLM Retry ───────────────────────────────────────────────────

def retry_llm(max_attempts=3, base_delay=2.0):
    """Декоратор retry для LLM API вызовов."""
    import requests as http_requests

    return retry(
        max_attempts=max_attempts,
        base_delay=base_delay,
        max_delay=60.0,
        jitter=1.0,
        retryable_exceptions=(
            http_requests.ConnectionError,
            http_requests.Timeout,
            ConnectionError,
            TimeoutError,
            OSError,
        ),
        non_retryable_exceptions=(),
        context="llm_api"
    )
