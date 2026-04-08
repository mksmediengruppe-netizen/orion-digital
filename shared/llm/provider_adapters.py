"""
provider_adapters.py — Arcane 2 Transport Layer
OpenRouter (default) + OpenAI Native + Anthropic Native

Architecture: AbstractLLMClient → ProviderAdapter → Concrete API
Spec ref: §3.4, §12.6, §11.1

Audit v2: all findings from both code reviews addressed.
Changes from v1:
  - [CRITICAL] Rate limiter: lock released before sleep, while-loop rechecks
  - [CRITICAL] API_VERSION: "2023-06-01" (was "2023-01-01")
  - [CRITICAL] MODEL_MAP: fixed OpenRouter slugs (DeepSeek, Gemini, MiniMax)
  - [CRITICAL] Stream fallback: blocked after first yield → StreamInterruptedError
  - [CRITICAL] on_cost: now called for stream() via accumulated usage
  - copy.deepcopy in _prepare (was shallow copy)
  - Latency passed as separate param, not mutated into API response dict
  - raw response stored via deepcopy (no mutable ref leak)
  - extended_thinking cannot be overridden by metadata.provider
  - Multiple SYSTEM messages concatenated (not overwritten) for Anthropic
  - estimate_cost: longest-key-first prefix match (deterministic)
  - Connection pool limits in _get_client
  - http_client ownership tracking (_owns_client)
  - Callbacks isolated with _safe_callback (won't crash requests)
  - Retry-After header: safe parsing with 120s cap
  - base_url: validated against ALLOWED_BASE_DOMAINS whitelist
  - Idempotency key: sent as header to OpenAI + Anthropic
  - _get_token_field(): OpenAI native uses max_completion_tokens
  - Anthropic streaming: removed fake [DONE], added content_block_start/stop
  - json.loads in Anthropic serializer: try/except for tool_call args
  - Narrowed exception handling: no broad `except Exception` in fallback
  - Removed create_client_from_settings (keys must come from env/Vault)
  - logger: %-formatting instead of f-strings
  - CompletionRequest.validate() for basic input checks
  - Shared OpenAI-format helpers (DRY for OpenRouter + OpenAI native)
"""

from __future__ import annotations

import asyncio
import copy
import json
import logging
import random
import time
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, AsyncIterator, Callable, Optional
from urllib.parse import urlparse

import httpx

logger = logging.getLogger("arcane.providers")

# ─────────────────────────────────────────────
# Allowed base_url domains (§12 security)
# Prevents credential exfiltration via custom base_url
# ─────────────────────────────────────────────

ALLOWED_BASE_DOMAINS: set[str] = {
    "api.openai.com",
    "api.anthropic.com",
    "openrouter.ai",
    # Add staging/custom domains here as needed
}


def _validate_base_url(url: str) -> str:
    """Validate base_url against allowed domains. Raises ValueError."""
    parsed = urlparse(url)
    if parsed.scheme not in ("https",):
        raise ValueError("base_url must use HTTPS: %s" % url)
    host = parsed.hostname or ""
    if host not in ALLOWED_BASE_DOMAINS:
        raise ValueError(
            "base_url domain '%s' not in allowed list. "
            "Add to ALLOWED_BASE_DOMAINS if intentional." % host
        )
    return url


# ─────────────────────────────────────────────
# Data structures
# ─────────────────────────────────────────────


class Role(str, Enum):
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


@dataclass
class Message:
    role: Role
    content: str | list[dict[str, Any]]
    name: Optional[str] = None
    tool_call_id: Optional[str] = None
    tool_calls: Optional[list[dict]] = None


@dataclass
class ToolDefinition:
    """Provider-agnostic tool definition."""
    name: str
    description: str
    parameters: dict[str, Any]  # JSON Schema


@dataclass
class ToolCall:
    """Parsed tool call from model response."""
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    reasoning_tokens: int = 0

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens


@dataclass
class CompletionResponse:
    """Unified response across all providers."""
    content: str
    tool_calls: list[ToolCall] = field(default_factory=list)
    usage: Usage = field(default_factory=Usage)
    model: str = ""
    provider: str = ""
    finish_reason: str = ""
    raw: Optional[dict] = None
    thinking: Optional[str] = None
    latency_ms: float = 0.0
    idempotency_key: Optional[str] = None


@dataclass
class StreamChunk:
    """Single chunk from a streaming response."""
    delta: str = ""
    tool_calls_delta: Optional[list[dict]] = None
    thinking_delta: Optional[str] = None
    finish_reason: Optional[str] = None
    usage: Optional[Usage] = None


@dataclass
class CompletionRequest:
    """Provider-agnostic completion request."""
    model: str
    messages: list[Message]
    tools: Optional[list[ToolDefinition]] = None
    tool_choice: Optional[str | dict] = None
    temperature: float = 0.7
    max_tokens: int = 4096
    top_p: Optional[float] = None
    stop: Optional[list[str]] = None
    stream: bool = False
    extended_thinking: bool = False
    thinking_budget: Optional[int] = None
    idempotency_key: Optional[str] = None
    timeout: float = 120.0
    metadata: dict[str, Any] = field(default_factory=dict)

    def validate(self) -> None:
        """Basic input validation. Raises ValueError."""
        if not self.model:
            raise ValueError("model is required")
        if not self.messages:
            raise ValueError("messages cannot be empty")
        if not (0.0 <= self.temperature <= 2.0):
            raise ValueError("temperature must be 0.0–2.0")
        if self.max_tokens < 1:
            raise ValueError("max_tokens must be >= 1")
        if self.top_p is not None and not (0.0 <= self.top_p <= 1.0):
            raise ValueError("top_p must be 0.0–1.0")
        if self.timeout < 1.0:
            raise ValueError("timeout must be >= 1.0s")


# ─────────────────────────────────────────────
# Cost calculation (§3.1)
# ─────────────────────────────────────────────

MODEL_PRICING: dict[str, tuple[float, float]] = {
    # Dashed slugs (native provider IDs)
    "claude-opus-4-6":     (5.00, 25.00),
    "claude-sonnet-4-6":   (3.00, 15.00),
    "claude-haiku-4-5":    (1.00, 5.00),
    # Dotted slugs (our internal IDs — used by budget_controller, model_registry)
    "claude-opus-4.6":     (5.00, 25.00),
    "claude-sonnet-4.6":   (3.00, 15.00),
    "claude-haiku-4.5":    (1.00, 5.00),
    # GPT (same slug format everywhere)
    "gpt-5.4":             (2.50, 15.00),
    "gpt-5.4-mini":        (0.75, 4.50),
    "gpt-5.4-nano":        (0.20, 1.25),
    # Others
    "gemini-3.1-pro":      (2.00, 12.00),
    "gemini-2.5-flash":    (0.30, 2.50),
    "deepseek-v3.2":       (0.28, 0.42),
    "minimax-m2.5":        (0.30, 1.20),
    "kimi-k2.5":           (0.00, 0.00),
    "step-3.5-flash":      (0.00, 0.00),
    "nemotron-3-super":    (0.00, 0.00),
}

# Sorted longest-first for deterministic prefix matching
_PRICING_KEYS_BY_LENGTH: list[str] = sorted(
    MODEL_PRICING.keys(), key=len, reverse=True
)


def estimate_cost(model: str, usage: Usage) -> float:
    """Cost in USD. Returns 0.0 for unknown models."""
    key = model.split("/")[-1] if "/" in model else model
    pricing = MODEL_PRICING.get(key)
    if not pricing:
        for k in _PRICING_KEYS_BY_LENGTH:
            if key.startswith(k):
                pricing = MODEL_PRICING[k]
                break
    if not pricing:
        logger.warning("No pricing for model: %s", key)
        return 0.0
    in_p, out_p = pricing
    return round(
        (usage.input_tokens * in_p + usage.output_tokens * out_p) / 1_000_000, 6
    )


# ─────────────────────────────────────────────
# Rate limiter (§11.1)
# Lock released before sleep; while-loop rechecks after wake
# ─────────────────────────────────────────────

class TokenBucketRateLimiter:
    """Per-provider rate limiter. Thread-safe via asyncio.Lock."""

    def __init__(self, rpm: int = 60, tpm: int = 1_000_000):
        self.rpm = rpm
        self.tpm = tpm
        self._request_times: list[float] = []
        self._token_count: int = 0
        self._token_window_start: float = time.monotonic()
        self._lock = asyncio.Lock()

    async def acquire(self, estimated_tokens: int = 0) -> None:
        while True:
            wait_time = 0.0
            async with self._lock:
                now = time.monotonic()
                self._request_times = [
                    t for t in self._request_times if now - t < 60
                ]
                if len(self._request_times) >= self.rpm:
                    wait_time = max(0.0, 60.0 - (now - self._request_times[0]))
                if wait_time == 0.0:
                    if now - self._token_window_start >= 60:
                        self._token_count = 0
                        self._token_window_start = now
                    if self._token_count + estimated_tokens > self.tpm:
                        wait_time = max(
                            0.0, 60.0 - (now - self._token_window_start)
                        )
                if wait_time == 0.0:
                    self._request_times.append(time.monotonic())
                    self._token_count += estimated_tokens
                    return
            # Sleep OUTSIDE lock, then re-check
            logger.debug("Rate limit wait: %.1fs", wait_time)
            await asyncio.sleep(wait_time)

    def record_actual_usage(self, actual: int, estimated: int) -> None:
        """Reconcile actual vs estimated token usage."""
        delta = actual - estimated
        if delta != 0:
            self._token_count = max(0, self._token_count + delta)


# ─────────────────────────────────────────────
# Retry / Errors
# ─────────────────────────────────────────────

_RETRYABLE_NETWORK_ERRORS = (httpx.TimeoutException, httpx.ConnectError)


class RetryConfig:
    def __init__(
        self,
        max_retries: int = 3,
        base_delay: float = 1.0,
        max_delay: float = 30.0,
        retry_status_codes: tuple[int, ...] = (429, 500, 502, 503, 504),
    ):
        self.max_retries = max_retries
        self.base_delay = base_delay
        self.max_delay = max_delay
        self.retry_status_codes = retry_status_codes

    def delay_for(self, attempt: int) -> float:
        delay = min(self.base_delay * (2 ** attempt), self.max_delay)
        return delay * (0.5 + random.random() * 0.5)


class ProviderError(Exception):
    def __init__(self, message: str, status_code: int = 0, provider: str = "",
                 retryable: bool = False):
        super().__init__(message)
        self.status_code = status_code
        self.provider = provider
        self.retryable = retryable


class RateLimitError(ProviderError):
    def __init__(self, message: str, retry_after: float = 0, **kw):
        super().__init__(message, retryable=True, **kw)
        self.retry_after = retry_after


class BudgetExceededError(ProviderError):
    pass


class StreamInterruptedError(ProviderError):
    """Stream failed after chunks were already yielded."""
    pass


# ─────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────

def _safe_callback(fn: Optional[Callable], *args: Any) -> None:
    """Call fn, swallowing exceptions to protect critical path."""
    if fn is None:
        return
    try:
        fn(*args)
    except Exception:
        logger.exception("Callback error (swallowed)")


def _parse_retry_after(value: Optional[str], fallback: float) -> float:
    """Safe Retry-After parsing, capped at 120s."""
    if not value:
        return fallback
    try:
        return min(max(float(value), 0), 120.0)
    except (ValueError, OverflowError):
        return fallback


# ─────────────────────────────────────────────
# Abstract provider adapter
# ─────────────────────────────────────────────

class ProviderAdapter(ABC):
    PROVIDER_NAME: str = "abstract"

    def __init__(
        self,
        api_key: str,
        base_url: Optional[str] = None,
        rate_limiter: Optional[TokenBucketRateLimiter] = None,
        retry_config: Optional[RetryConfig] = None,
        http_client: Optional[httpx.AsyncClient] = None,
        validate_base_url: bool = True,
    ):
        self.api_key = api_key
        if base_url and validate_base_url:
            base_url = _validate_base_url(base_url)
        self.base_url = base_url or self._default_base_url()
        self.rate_limiter = rate_limiter or TokenBucketRateLimiter()
        self.retry = retry_config or RetryConfig()
        self._client = http_client
        self._owns_client = http_client is None

    @abstractmethod
    def _default_base_url(self) -> str: ...
    @abstractmethod
    def _build_headers(self, idempotency_key: Optional[str] = None) -> dict[str, str]: ...
    @abstractmethod
    def _serialize_request(self, req: CompletionRequest) -> dict[str, Any]: ...
    @abstractmethod
    def _parse_response(self, data: dict, req: CompletionRequest, latency_ms: float) -> CompletionResponse: ...
    @abstractmethod
    def _parse_stream_chunk(self, line: str) -> Optional[StreamChunk]: ...
    @abstractmethod
    def _completion_endpoint(self) -> str: ...

    def _get_model_id(self, model: str) -> str:
        return model

    def _get_token_field(self) -> str:
        return "max_tokens"

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(120.0),
                limits=httpx.Limits(
                    max_connections=50,
                    max_keepalive_connections=20,
                    keepalive_expiry=30,
                ),
            )
            self._owns_client = True
        return self._client

    async def complete(self, request: CompletionRequest) -> CompletionResponse:
        request.validate()
        req = self._prepare(request, stream=False)
        body = self._serialize_request(req)
        data, latency_ms = await self._post_with_retry(body, req)
        resp = self._parse_response(data, req, latency_ms)
        resp.provider = self.PROVIDER_NAME
        resp.idempotency_key = req.idempotency_key
        return resp

    async def stream(self, request: CompletionRequest) -> AsyncIterator[StreamChunk]:
        request.validate()
        req = self._prepare(request, stream=True)
        body = self._serialize_request(req)
        token_est = body.get(self._get_token_field(), 4096)
        await self.rate_limiter.acquire(estimated_tokens=token_est)
        client = await self._get_client()
        headers = self._build_headers(idempotency_key=req.idempotency_key)

        async with client.stream(
            "POST",
            f"{self.base_url}{self._completion_endpoint()}",
            json=body, headers=headers,
            timeout=httpx.Timeout(req.timeout, connect=10.0),
        ) as resp:
            if resp.status_code != 200:
                await resp.aread()
                raise ProviderError(
                    "Stream error %d" % resp.status_code,
                    status_code=resp.status_code,
                    provider=self.PROVIDER_NAME,
                    retryable=resp.status_code in self.retry.retry_status_codes,
                )
            async for line in resp.aiter_lines():
                if not line.strip():
                    continue
                chunk = self._parse_stream_chunk(line)
                if chunk is not None:
                    yield chunk

    def _prepare(self, request: CompletionRequest, stream: bool) -> CompletionRequest:
        req = copy.deepcopy(request)
        req.stream = stream
        req.model = self._get_model_id(req.model)
        if not req.idempotency_key:
            req.idempotency_key = str(uuid.uuid4())
        return req

    async def _post_with_retry(
        self, body: dict, req: CompletionRequest
    ) -> tuple[dict, float]:
        """Returns (data, latency_ms). Never mutates the API response."""
        last_error: Optional[Exception] = None
        token_est = body.get(self._get_token_field(), 4096)

        for attempt in range(self.retry.max_retries + 1):
            try:
                await self.rate_limiter.acquire(estimated_tokens=token_est)
                client = await self._get_client()
                headers = self._build_headers(idempotency_key=req.idempotency_key)
                t0 = time.monotonic()
                resp = await client.post(
                    f"{self.base_url}{self._completion_endpoint()}",
                    json=body, headers=headers,
                    timeout=httpx.Timeout(req.timeout, connect=10.0),
                )
                latency_ms = (time.monotonic() - t0) * 1000

                if resp.status_code == 429:
                    ra = _parse_retry_after(
                        resp.headers.get("retry-after"),
                        self.retry.delay_for(attempt),
                    )
                    raise RateLimitError(
                        "Rate limited", retry_after=ra,
                        status_code=429, provider=self.PROVIDER_NAME,
                    )
                if resp.status_code >= 400:
                    raise ProviderError(
                        "HTTP %d from %s" % (resp.status_code, self.PROVIDER_NAME),
                        status_code=resp.status_code,
                        provider=self.PROVIDER_NAME,
                        retryable=resp.status_code in self.retry.retry_status_codes,
                    )
                return resp.json(), latency_ms

            except RateLimitError as e:
                last_error = e
                wait = e.retry_after or self.retry.delay_for(attempt)
                logger.warning("[%s] Rate limited, wait %.1fs", self.PROVIDER_NAME, wait)
                await asyncio.sleep(wait)

            except ProviderError as e:
                last_error = e
                if not e.retryable or attempt >= self.retry.max_retries:
                    raise
                wait = self.retry.delay_for(attempt)
                logger.warning("[%s] HTTP %d, retry %d in %.1fs",
                               self.PROVIDER_NAME, e.status_code, attempt + 1, wait)
                await asyncio.sleep(wait)

            except _RETRYABLE_NETWORK_ERRORS as e:
                last_error = e
                if attempt >= self.retry.max_retries:
                    raise ProviderError(
                        "Connection failed after %d retries: %s"
                        % (self.retry.max_retries, type(e).__name__),
                        provider=self.PROVIDER_NAME, retryable=False,
                    )
                wait = self.retry.delay_for(attempt)
                logger.warning("[%s] %s, retry %d in %.1fs",
                               self.PROVIDER_NAME, type(e).__name__, attempt + 1, wait)
                await asyncio.sleep(wait)

        raise last_error or ProviderError("Unknown error", provider=self.PROVIDER_NAME)

    async def close(self) -> None:
        if self._client and self._owns_client:
            await self._client.aclose()
            self._client = None


# ─────────────────────────────────────────────
# Shared OpenAI-format helpers (OpenRouter + OpenAI native)
# ─────────────────────────────────────────────

def _serialize_messages_openai(messages: list[Message]) -> list[dict]:
    result = []
    for m in messages:
        msg: dict[str, Any] = {"role": m.role.value, "content": m.content}
        if m.name:
            msg["name"] = m.name
        if m.tool_call_id:
            msg["tool_call_id"] = m.tool_call_id
        if m.tool_calls:
            msg["tool_calls"] = m.tool_calls
        result.append(msg)
    return result


def _serialize_tool_openai(tool: ToolDefinition) -> dict:
    return {
        "type": "function",
        "function": {
            "name": tool.name,
            "description": tool.description,
            "parameters": tool.parameters,
        },
    }


def _parse_tool_calls_openai(raw: list[dict]) -> list[ToolCall]:
    result = []
    for tc in raw:
        args = tc["function"].get("arguments", "{}")
        if isinstance(args, str):
            try:
                args = json.loads(args)
            except json.JSONDecodeError:
                logger.warning("Bad JSON in tool args for '%s'",
                               tc["function"].get("name", "?"))
                args = {"_raw": args, "_parse_error": True}
        result.append(ToolCall(
            id=tc["id"], name=tc["function"]["name"], arguments=args,
        ))
    return result


def _parse_openai_response(
    data: dict, req: CompletionRequest, latency_ms: float
) -> CompletionResponse:
    choice = data["choices"][0]
    msg = choice["message"]
    tool_calls = _parse_tool_calls_openai(msg["tool_calls"]) if msg.get("tool_calls") else []
    u = data.get("usage", {})
    return CompletionResponse(
        content=msg.get("content") or "",
        tool_calls=tool_calls,
        usage=Usage(
            input_tokens=u.get("prompt_tokens", 0),
            output_tokens=u.get("completion_tokens", 0),
        ),
        model=data.get("model", req.model),
        finish_reason=choice.get("finish_reason", ""),
        raw=copy.deepcopy(data),
        latency_ms=latency_ms,
    )


def _parse_openai_stream_chunk(line: str) -> Optional[StreamChunk]:
    if not line.startswith("data: "):
        return None
    payload = line[6:].strip()
    if payload == "[DONE]":
        return StreamChunk(finish_reason="stop")
    try:
        data = json.loads(payload)
    except json.JSONDecodeError:
        return None
    choice = data.get("choices", [{}])[0]
    delta = choice.get("delta", {})
    chunk = StreamChunk(
        delta=delta.get("content") or "",
        finish_reason=choice.get("finish_reason"),
    )
    if delta.get("tool_calls"):
        chunk.tool_calls_delta = delta["tool_calls"]
    if "usage" in data and data["usage"]:
        u = data["usage"]
        chunk.usage = Usage(
            input_tokens=u.get("prompt_tokens", 0),
            output_tokens=u.get("completion_tokens", 0),
        )
    return chunk


# ─────────────────────────────────────────────
# OpenRouter adapter (§3.4)
# ─────────────────────────────────────────────

class OpenRouterAdapter(ProviderAdapter):
    PROVIDER_NAME = "openrouter"

    # Verified against OpenRouter + model_registry.py
    MODEL_MAP: dict[str, str] = {
        "claude-opus-4-6":   "anthropic/claude-opus-4-6",
        "claude-sonnet-4-6": "anthropic/claude-sonnet-4-6",
        "claude-haiku-4-5":  "anthropic/claude-haiku-4-5",
        "gpt-5.4":          "openai/gpt-5.4",
        "gpt-5.4-mini":     "openai/gpt-5.4-mini",
        "gpt-5.4-nano":     "openai/gpt-5.4-nano",
        "gemini-3.1-pro":   "google/gemini-3.1-pro-preview",
        "gemini-2.5-flash": "google/gemini-2.5-flash",
        "deepseek-v3.2":    "deepseek/deepseek-chat-v3-0324",
        "minimax-m2.5":     "minimax/minimax-m2.5",
        "kimi-k2.5":        "moonshot/kimi-k2.5",
        "step-3.5-flash":   "stepfun/step-3.5-flash",
        "nemotron-3-super": "nvidia/nemotron-3-super",
    }

    def __init__(self, api_key: str, app_name: str = "Arcane2", **kw):
        self.app_name = app_name
        super().__init__(api_key=api_key, **kw)

    def _default_base_url(self) -> str:
        return "https://openrouter.ai/api"

    def _completion_endpoint(self) -> str:
        return "/v1/chat/completions"

    def _build_headers(self, idempotency_key: Optional[str] = None) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://arcane.ai",
            "X-Title": self.app_name,
        }

    def _get_model_id(self, model: str) -> str:
        return self.MODEL_MAP.get(model, model)

    def _serialize_request(self, req: CompletionRequest) -> dict[str, Any]:
        body: dict[str, Any] = {
            "model": req.model,
            "messages": _serialize_messages_openai(req.messages),
            "temperature": req.temperature,
            "max_tokens": req.max_tokens,
            "stream": req.stream,
        }
        if req.top_p is not None:
            body["top_p"] = req.top_p
        if req.stop:
            body["stop"] = req.stop
        if req.tools:
            body["tools"] = [_serialize_tool_openai(t) for t in req.tools]
        if req.tool_choice is not None:
            body["tool_choice"] = req.tool_choice
        return body

    def _parse_response(self, data: dict, req: CompletionRequest, latency_ms: float) -> CompletionResponse:
        return _parse_openai_response(data, req, latency_ms)

    def _parse_stream_chunk(self, line: str) -> Optional[StreamChunk]:
        return _parse_openai_stream_chunk(line)


# ─────────────────────────────────────────────
# OpenAI Native adapter (§3.4)
# ─────────────────────────────────────────────

class OpenAINativeAdapter(ProviderAdapter):
    PROVIDER_NAME = "openai"

    MODEL_MAP: dict[str, str] = {
        "gpt-5.4":      "gpt-5.4",
        "gpt-5.4-mini": "gpt-5.4-mini",
        "gpt-5.4-nano": "gpt-5.4-nano",
    }

    def __init__(self, api_key: str, organization: Optional[str] = None, **kw):
        self.organization = organization
        super().__init__(api_key=api_key, **kw)

    def _default_base_url(self) -> str:
        return "https://api.openai.com"

    def _completion_endpoint(self) -> str:
        return "/v1/chat/completions"

    def _build_headers(self, idempotency_key: Optional[str] = None) -> dict[str, str]:
        h = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        if self.organization:
            h["OpenAI-Organization"] = self.organization
        if idempotency_key:
            h["Idempotency-Key"] = idempotency_key
        return h

    def _get_model_id(self, model: str) -> str:
        return self.MODEL_MAP.get(model, model)

    def _get_token_field(self) -> str:
        return "max_completion_tokens"

    def _serialize_request(self, req: CompletionRequest) -> dict[str, Any]:
        body: dict[str, Any] = {
            "model": req.model,
            "messages": _serialize_messages_openai(req.messages),
            "temperature": req.temperature,
            "max_completion_tokens": req.max_tokens,
            "stream": req.stream,
        }
        if req.stream:
            body["stream_options"] = {"include_usage": True}
        if req.top_p is not None:
            body["top_p"] = req.top_p
        if req.stop:
            body["stop"] = req.stop
        if req.tools:
            body["tools"] = [_serialize_tool_openai(t) for t in req.tools]
        if req.tool_choice is not None:
            body["tool_choice"] = req.tool_choice
        if req.metadata.get("reasoning_effort"):
            body["reasoning_effort"] = req.metadata["reasoning_effort"]
        return body

    def _parse_response(self, data: dict, req: CompletionRequest, latency_ms: float) -> CompletionResponse:
        resp = _parse_openai_response(data, req, latency_ms)
        details = data.get("usage", {}).get("completion_tokens_details", {})
        if details:
            resp.usage.reasoning_tokens = details.get("reasoning_tokens", 0)
        return resp

    def _parse_stream_chunk(self, line: str) -> Optional[StreamChunk]:
        return _parse_openai_stream_chunk(line)


# ─────────────────────────────────────────────
# Anthropic Native adapter (§3.4)
# API_VERSION = "2023-06-01" (FIXED from "2023-01-01")
# ─────────────────────────────────────────────

class AnthropicNativeAdapter(ProviderAdapter):
    PROVIDER_NAME = "anthropic"

    MODEL_MAP: dict[str, str] = {
        "claude-opus-4-6":   "claude-opus-4-6-20260301",
        "claude-sonnet-4-6": "claude-sonnet-4-6-20260301",
        "claude-haiku-4-5":  "claude-haiku-4-5-20251001",
    }

    API_VERSION = "2023-06-01"

    def _default_base_url(self) -> str:
        return "https://api.anthropic.com"

    def _completion_endpoint(self) -> str:
        return "/v1/messages"

    def _build_headers(self, idempotency_key: Optional[str] = None) -> dict[str, str]:
        h = {
            "x-api-key": self.api_key,
            "anthropic-version": self.API_VERSION,
            "Content-Type": "application/json",
        }
        if idempotency_key:
            h["idempotency-key"] = idempotency_key
        return h

    def _get_model_id(self, model: str) -> str:
        return self.MODEL_MAP.get(model, model)

    def _serialize_request(self, req: CompletionRequest) -> dict[str, Any]:
        system_parts: list[str] = []
        messages = []
        for m in req.messages:
            if m.role == Role.SYSTEM:
                part = m.content if isinstance(m.content, str) else json.dumps(m.content)
                system_parts.append(part)
            elif m.role == Role.TOOL:
                messages.append({
                    "role": "user",
                    "content": [{
                        "type": "tool_result",
                        "tool_use_id": m.tool_call_id,
                        "content": m.content if isinstance(m.content, str) else json.dumps(m.content),
                    }],
                })
            elif m.role == Role.ASSISTANT and m.tool_calls:
                blocks: list[dict] = []
                if m.content:
                    blocks.append({"type": "text", "text": m.content})
                for tc in m.tool_calls:
                    raw_args = tc["function"]["arguments"]
                    if isinstance(raw_args, str):
                        try:
                            parsed = json.loads(raw_args)
                        except json.JSONDecodeError:
                            logger.warning("Bad JSON in tool_call args during serialization")
                            parsed = {"_raw": raw_args}
                    else:
                        parsed = raw_args
                    blocks.append({
                        "type": "tool_use",
                        "id": tc["id"],
                        "name": tc["function"]["name"],
                        "input": parsed,
                    })
                messages.append({"role": "assistant", "content": blocks})
            else:
                messages.append({"role": m.role.value, "content": m.content})

        body: dict[str, Any] = {
            "model": req.model,
            "messages": messages,
            "max_tokens": req.max_tokens,
            "stream": req.stream,
        }
        if system_parts:
            body["system"] = "\n\n".join(system_parts)
        if not req.extended_thinking:
            body["temperature"] = req.temperature
        if req.top_p is not None and not req.extended_thinking:
            body["top_p"] = req.top_p
        if req.stop:
            body["stop_sequences"] = req.stop
        if req.tools:
            body["tools"] = [{"name": t.name, "description": t.description,
                              "input_schema": t.parameters} for t in req.tools]
        if req.tool_choice is not None:
            body["tool_choice"] = self._map_tool_choice(req.tool_choice)
        if req.extended_thinking:
            body["thinking"] = {
                "type": "enabled",
                "budget_tokens": req.thinking_budget or (req.max_tokens // 2),
            }
        return body

    def _map_tool_choice(self, choice: str | dict) -> dict:
        if isinstance(choice, dict):
            return choice
        m = {"auto": {"type": "auto"}, "none": {"type": "none"}, "required": {"type": "any"}}
        return m.get(choice, {"type": "tool", "name": choice})

    def _parse_response(self, data: dict, req: CompletionRequest, latency_ms: float) -> CompletionResponse:
        content_parts, thinking_parts, tool_calls = [], [], []
        for block in data.get("content", []):
            bt = block.get("type", "")
            if bt == "text":
                content_parts.append(block["text"])
            elif bt == "thinking":
                thinking_parts.append(block.get("thinking", ""))
            elif bt == "tool_use":
                tool_calls.append(ToolCall(
                    id=block["id"], name=block["name"],
                    arguments=block.get("input", {}),
                ))
        u = data.get("usage", {})
        return CompletionResponse(
            content="\n".join(content_parts),
            tool_calls=tool_calls,
            usage=Usage(
                input_tokens=u.get("input_tokens", 0),
                output_tokens=u.get("output_tokens", 0),
                cache_read_tokens=u.get("cache_read_input_tokens", 0),
                cache_write_tokens=u.get("cache_creation_input_tokens", 0),
            ),
            model=data.get("model", req.model),
            finish_reason=data.get("stop_reason", ""),
            raw=copy.deepcopy(data),
            thinking="\n".join(thinking_parts) if thinking_parts else None,
            latency_ms=latency_ms,
        )

    def _parse_stream_chunk(self, line: str) -> Optional[StreamChunk]:
        """
        Anthropic SSE: NO 'data: [DONE]'.
        Handles: message_start, content_block_start, content_block_delta,
                 content_block_stop, message_delta, message_stop.
        """
        if not line.startswith("data: "):
            return None
        try:
            data = json.loads(line[6:].strip())
        except json.JSONDecodeError:
            return None

        et = data.get("type", "")

        if et == "content_block_start":
            block = data.get("content_block", {})
            if block.get("type") == "tool_use":
                return StreamChunk(tool_calls_delta=[{
                    "type": "tool_use_start",
                    "index": data.get("index", 0),
                    "id": block.get("id", ""),
                    "name": block.get("name", ""),
                }])
            return None

        if et == "content_block_delta":
            delta = data.get("delta", {})
            dt = delta.get("type", "")
            if dt == "text_delta":
                return StreamChunk(delta=delta.get("text", ""))
            if dt == "thinking_delta":
                return StreamChunk(thinking_delta=delta.get("thinking", ""))
            if dt == "input_json_delta":
                return StreamChunk(tool_calls_delta=[{
                    "type": "input_json_delta",
                    "index": data.get("index", 0),
                    "partial_json": delta.get("partial_json", ""),
                }])
            return None

        if et == "content_block_stop":
            return StreamChunk(tool_calls_delta=[{
                "type": "tool_use_stop", "index": data.get("index", 0),
            }])

        if et == "message_delta":
            return StreamChunk(
                finish_reason=data.get("delta", {}).get("stop_reason"),
                usage=Usage(output_tokens=data.get("usage", {}).get("output_tokens", 0)),
            )

        if et == "message_start":
            u = data.get("message", {}).get("usage", {})
            if u:
                return StreamChunk(usage=Usage(input_tokens=u.get("input_tokens", 0)))

        if et == "message_stop":
            return StreamChunk(finish_reason="end_turn")

        return None


# ─────────────────────────────────────────────
# LLMClient — provider selection + fallback (§3.4, §12.6)
# ─────────────────────────────────────────────

PROVIDER_MODEL_SUPPORT: dict[str, list[str]] = {
    "openrouter": ["claude-", "gpt-", "gemini-", "deepseek-", "minimax-",
                    "kimi-", "step-", "nemotron-"],
    "openai": ["gpt-"],
    "anthropic": ["claude-"],
}


def _provider_supports_model(provider: str, model: str) -> bool:
    return any(model.startswith(p) for p in PROVIDER_MODEL_SUPPORT.get(provider, []))


class LLMClient:
    """
    High-level client with provider selection + fallback.
    Stream fallback ONLY before first chunk (StreamInterruptedError after).
    """

    def __init__(
        self,
        openrouter_key: Optional[str] = None,
        openai_key: Optional[str] = None,
        anthropic_key: Optional[str] = None,
        openrouter_base_url: Optional[str] = None,
        openai_base_url: Optional[str] = None,
        anthropic_base_url: Optional[str] = None,
        openai_organization: Optional[str] = None,
        on_cost: Optional[Callable[[str, str, float, Usage], None]] = None,
        on_fallback: Optional[Callable[[str, str, str], None]] = None,
    ):
        self._adapters: dict[str, ProviderAdapter] = {}
        self.on_cost = on_cost
        self.on_fallback = on_fallback

        if openrouter_key:
            self._adapters["openrouter"] = OpenRouterAdapter(
                api_key=openrouter_key, base_url=openrouter_base_url)
        if openai_key:
            self._adapters["openai"] = OpenAINativeAdapter(
                api_key=openai_key, base_url=openai_base_url,
                organization=openai_organization)
        if anthropic_key:
            self._adapters["anthropic"] = AnthropicNativeAdapter(
                api_key=anthropic_key, base_url=anthropic_base_url)
        if not self._adapters:
            raise ValueError("At least one provider API key is required")

    def _select_provider(self, request: CompletionRequest) -> list[str]:
        model = request.model
        # extended_thinking → Anthropic mandatory (cannot be overridden)
        if request.extended_thinking:
            if "anthropic" not in self._adapters:
                raise ProviderError(
                    "extended_thinking requires Anthropic API key", provider="none")
            if not _provider_supports_model("anthropic", model):
                raise ProviderError(
                    "extended_thinking requires Claude model, got '%s'" % model,
                    provider="none")
            if request.metadata.get("provider") and request.metadata["provider"] != "anthropic":
                logger.warning("Ignoring metadata.provider='%s' — extended_thinking forces Anthropic",
                               request.metadata["provider"])
            return ["anthropic"]

        # Explicit provider (no tech constraints)
        if request.metadata.get("provider"):
            explicit = request.metadata["provider"]
            if explicit in self._adapters:
                return [explicit]
            logger.warning("Provider '%s' not available, using default chain", explicit)

        # Default chain: OpenRouter → native fallbacks
        providers: list[str] = []
        if "openrouter" in self._adapters and _provider_supports_model("openrouter", model):
            providers.append("openrouter")
        if _provider_supports_model("openai", model) and "openai" in self._adapters:
            if "openai" not in providers:
                providers.append("openai")
        if _provider_supports_model("anthropic", model) and "anthropic" in self._adapters:
            if "anthropic" not in providers:
                providers.append("anthropic")
        if "openrouter" in self._adapters and "openrouter" not in providers:
            providers.append("openrouter")
        if not providers:
            raise ProviderError(
                "No provider for '%s'. Available: %s" % (model, list(self._adapters)),
                provider="none")
        return providers

    async def complete(self, request: CompletionRequest) -> CompletionResponse:
        chain = self._select_provider(request)
        last_err: Optional[Exception] = None
        for i, name in enumerate(chain):
            try:
                resp = await self._adapters[name].complete(request)
                cost = estimate_cost(request.model, resp.usage)
                _safe_callback(self.on_cost, request.model, name, cost, resp.usage)
                if i > 0:
                    _safe_callback(self.on_fallback, request.model, chain[0], name)
                return resp
            except ProviderError as e:
                last_err = e
                logger.warning("[LLMClient] %s failed (status=%d)", name, e.status_code)
                if not e.retryable and e.status_code in (400, 401, 403, 404, 422):
                    raise
            except _RETRYABLE_NETWORK_ERRORS as e:
                last_err = ProviderError("Network: %s" % type(e).__name__,
                                         provider=name, retryable=True)
        raise last_err or ProviderError("All providers failed", provider="all")

    async def stream(self, request: CompletionRequest) -> AsyncIterator[StreamChunk]:
        chain = self._select_provider(request)
        last_err: Optional[Exception] = None
        for i, name in enumerate(chain):
            chunks_yielded = False
            acc_usage: Optional[Usage] = None
            try:
                if i > 0:
                    _safe_callback(self.on_fallback, request.model, chain[0], name)
                async for chunk in self._adapters[name].stream(request):
                    chunks_yielded = True
                    if chunk.usage is not None:
                        acc_usage = chunk.usage
                    yield chunk
                if acc_usage:
                    cost = estimate_cost(request.model, acc_usage)
                    _safe_callback(self.on_cost, request.model, name, cost, acc_usage)
                return
            except (ProviderError, httpx.TimeoutException, httpx.ConnectError) as e:
                if chunks_yielded:
                    raise StreamInterruptedError(
                        "Stream interrupted after partial output from %s" % name,
                        provider=name, retryable=False) from e
                last_err = e if isinstance(e, ProviderError) else ProviderError(
                    "Network: %s" % type(e).__name__, provider=name, retryable=True)
                if isinstance(e, ProviderError) and not e.retryable and e.status_code in (400, 401, 403, 404, 422):
                    raise
        raise last_err or ProviderError("All providers failed (stream)", provider="all")

    def get_adapter(self, provider: str) -> Optional[ProviderAdapter]:
        return self._adapters.get(provider)

    async def close(self) -> None:
        for a in self._adapters.values():
            await a.close()

    async def __aenter__(self) -> "LLMClient":
        return self

    async def __aexit__(self, *args) -> None:
        await self.close()


# ─────────────────────────────────────────────
# Factory (§12.3 — keys from env/Vault only)
# ─────────────────────────────────────────────

def create_client_from_env() -> LLMClient:
    """Create LLMClient from env vars. Keys belong in env, not settings.json."""
    import os
    return LLMClient(
        openrouter_key=os.getenv("OPENROUTER_API_KEY"),
        openai_key=os.getenv("OPENAI_API_KEY"),
        anthropic_key=os.getenv("ANTHROPIC_API_KEY"),
        openai_organization=os.getenv("OPENAI_ORG_ID"),
    )
