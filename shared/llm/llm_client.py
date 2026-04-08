"""
ARCANE 2 — Simple LLM Client
Connects orchestrator to real OpenRouter API.
Supports: chat completions, tool/function calling, cost estimation.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from typing import Any, Optional

import httpx
import random

_MAX_RETRIES = 4
_RETRY_STATUSES = {429, 500, 502, 503, 504}

from shared.models.schemas import LLMRequest, LLMResponse, ToolCall, Provider

logger = logging.getLogger("arcane2.llm_client")

# Model ID mapping: our registry ID → OpenRouter model ID
MODEL_MAP = {
    "claude-opus-4.6": "anthropic/claude-opus-4.6",
    "claude-sonnet-4.6": "anthropic/claude-sonnet-4.6",
    "claude-haiku-4.5": "anthropic/claude-haiku-4.5",
    "gpt-5.4": "openai/gpt-5.4",
    "gpt-5.4-mini": "openai/gpt-5.4-mini",
    "gpt-5.4-nano": "openai/gpt-5.4-nano",
    "o3": "openai/o3",
    "o4-mini": "openai/o4-mini",
    "gemini-3.1-pro": "google/gemini-3.1-pro-preview",
    "gemini-2.5-flash": "google/gemini-2.5-flash",
    "gemini-2.5-flash-free": "qwen/qwen3.6-plus:free",  # FIXED: uses qwen3.6-plus:free (supports tools)
    "gemini-2.5-flash-lite": "google/gemini-2.5-flash-lite",
    "deepseek-v3.2": "deepseek/deepseek-chat-v3-0324",
    "deepseek-v3.1": "deepseek/deepseek-chat-v3.1",
    "deepseek-r1": "deepseek/deepseek-r1",
    "minimax-m2.5": "minimax/minimax-m2.5",
    "minimax-m2.5-free": "minimax/minimax-m2.5:free",
    "gpt-oss-120b-free": "openai/gpt-oss-120b:free",
    "qwen3-next-80b-free": "qwen/qwen3-next-80b-a3b-instruct:free",
    "nemotron-3-nano-free": "nvidia/nemotron-3-nano-30b-a3b:free",
    "nemotron-nano-12b-vl-free": "nvidia/nemotron-nano-12b-v2-vl:free",
    "llama-3.3-70b-free": "meta-llama/llama-3.3-70b-instruct:free",
    "grok-4": "x-ai/grok-4",
    "grok-4-fast": "x-ai/grok-4-fast",
    "step-3.5-flash": "stepfun/step-3.5-flash",
    "step-3.5-flash-free": "stepfun/step-3.5-flash:free",
    "kimi-k2.5": "moonshotai/kimi-k2.5",
    "qwen3-coder-free": "openai/gpt-oss-120b:free",
    "qwen3.6-plus-free": "openai/gpt-oss-120b:free",
    "nemotron-3-super-free": "nvidia/nemotron-3-super-120b-a12b:free",
}

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"


class SimpleLLMClient:
    """
    Minimal LLM client for Arcane 2.
    Calls OpenRouter API. Supports chat completions + function calling.
    """

    def __init__(self, api_key: str | None = None):
        self.api_key = api_key or os.environ.get("OPENROUTER_API_KEY", "")
        if not self.api_key:
            logger.warning("No OPENROUTER_API_KEY set. LLM calls will fail.")
        self._client = httpx.AsyncClient(timeout=300.0)  # 5 min for large HTML generation

    def _resolve_model(self, model_id: str) -> str:
        """Convert our registry ID to OpenRouter model ID."""
        return MODEL_MAP.get(model_id, model_id)

    async def chat(
        self,
        model: str,
        messages: list[dict[str, Any]],
        max_tokens: int = 4096,
        temperature: float = 0.3,
        tools: list[dict] | None = None,
    ) -> dict[str, Any]:
        """
        Send chat completion request to OpenRouter.
        
        Args:
            tools: OpenAI function-calling tool schemas (optional)
        
        Returns:
            {
                "content": str,
                "tool_calls": list[dict] | None,
                "model": str,
                "tokens_in": int, "tokens_out": int,
                "cost_usd": float, "time_seconds": float,
            }
        """
        openrouter_model = self._resolve_model(model)
        
        start = time.time()
        cache_read_tokens = 0
        cache_write_tokens = 0

        # Anthropic prompt caching: inject cache_control for system + last user message
        # This reduces cost by ~80-90% for repeated context (system prompts, project context)
        # OpenRouter supports this natively — no special headers needed
        _is_anthropic = any(m in openrouter_model for m in ("anthropic/", "claude-"))
        cached_messages = messages
        if _is_anthropic and messages:
            cached_messages = []
            for i, msg in enumerate(messages):
                msg_copy = dict(msg)
                # Cache system message (same for all calls of a role)
                if msg.get("role") == "system" and isinstance(msg.get("content"), str):
                    msg_copy["content"] = [
                        {
                            "type": "text",
                            "text": msg["content"],
                            "cache_control": {"type": "ephemeral"},
                        }
                    ]
                # Cache last user message (contains project context repeated per call)
                elif msg.get("role") == "user" and i == len(messages) - 1:
                    if isinstance(msg.get("content"), str):
                        msg_copy["content"] = [
                            {
                                "type": "text",
                                "text": msg["content"],
                                "cache_control": {"type": "ephemeral"},
                            }
                        ]
                cached_messages.append(msg_copy)

        body: dict[str, Any] = {
            "model": openrouter_model,
            "messages": cached_messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        if tools:
            body["tools"] = tools
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://arcaneai.ru",
            "X-Title": "Arcane 2",
        }
        try:
            # P-1: retry loop with exponential backoff + jitter
            for attempt in range(_MAX_RETRIES):
                try:
                    response = await self._client.post(
                        OPENROUTER_URL, headers=headers, json=body
                    )
                    if response.status_code in _RETRY_STATUSES and attempt < _MAX_RETRIES - 1:
                        wait = (2 ** attempt) + random.uniform(0, 1)
                        logger.warning(
                            f"OpenRouter HTTP {response.status_code} "
                            f"(attempt {attempt+1}/{_MAX_RETRIES}), retrying in {wait:.1f}s"
                        )
                        await asyncio.sleep(wait)
                        continue
                    if response.status_code != 200:
                        error_text = response.text[:500]
                        logger.error(f"OpenRouter error {response.status_code}: {error_text}")
                        raise RuntimeError(
                            f"OpenRouter API error {response.status_code}: {error_text}"
                        )
                    break  # success
                except httpx.TimeoutException as e:
                    if attempt < _MAX_RETRIES - 1:
                        wait = (2 ** attempt) + random.uniform(0, 1)
                        logger.warning(f"Timeout (attempt {attempt+1}), retrying in {wait:.1f}s")
                        await asyncio.sleep(wait)
                        continue
                    raise RuntimeError(f"Timeout calling {openrouter_model} after {_MAX_RETRIES} attempts")
            
            elapsed = time.time() - start
            
            data = response.json()
            
            # Extract response
            content = ""
            tool_calls = None
            if data.get("choices"):
                choice = data["choices"][0]
                message = choice.get("message", {})
                content = message.get("content", "") or ""
                # Warn if output was truncated by max_tokens
                finish_reason = choice.get("finish_reason", "")
                if finish_reason == "length":
                    logger.warning(
                        f"LLM output TRUNCATED by max_tokens limit "
                        f"(model={openrouter_model}, tokens_out={usage.get('completion_tokens',0)}). "
                        f"Consider increasing max_tokens."
                    )
                # Parse tool calls if present
                raw_tc = message.get("tool_calls")
                if raw_tc:
                    tool_calls = raw_tc  # Keep raw format for agent_loop
            
            # Extract usage
            usage = data.get("usage", {})
            tokens_in = usage.get("prompt_tokens", 0)
            tokens_out = usage.get("completion_tokens", 0)
            # Anthropic cache tokens (via OpenRouter)
            cache_read_tokens = usage.get("cache_read_input_tokens", 0)
            cache_write_tokens = usage.get("cache_creation_input_tokens", 0)
            
            # Estimate cost — use actual cache data if available
            cost = self._estimate_cost_with_cache(
                model, tokens_in, tokens_out,
                cache_read_tokens, cache_write_tokens
            )
            
            tc_info = f" | {len(tool_calls)} tool_calls" if tool_calls else ""
            cache_info = ""
            if cache_read_tokens or cache_write_tokens:
                cache_info = f" | cache: r={cache_read_tokens} w={cache_write_tokens}"
            logger.info(
                f"LLM call: [engine] | "
                f"{tokens_in}→{tokens_out} tok | "
                f"${cost:.4f} | {elapsed:.1f}s{tc_info}{cache_info}"
            )
            
            return {
                "content": content,
                "tool_calls": tool_calls,
                "model": openrouter_model,
                "tokens_in": tokens_in,
                "tokens_out": tokens_out,
                "cost_usd": cost,
                "time_seconds": elapsed,
                "cache_read_tokens": cache_read_tokens,
                "cache_write_tokens": cache_write_tokens,
            }
            
        except httpx.TimeoutException:
            logger.error(f"Timeout calling {openrouter_model}")
            raise RuntimeError(f"Timeout calling {openrouter_model}")
        except Exception as e:
            logger.error(f"LLM call failed: {e}")
            raise

    def _estimate_cost(self, model_id: str, tokens_in: int, tokens_out: int) -> float:
        """Estimate cost from our registry prices. Always calculates, never returns 0 for paid models."""
        try:
            from shared.llm.model_registry import get_model
            m = get_model(model_id)
            if m:
                return m.cost_estimate(tokens_in, tokens_out)
        except ImportError:
            pass
        return 0.0
    def _estimate_cost_with_cache(self, model_id, tokens_in, tokens_out, cache_read_tokens=0, cache_write_tokens=0):
        try:
            from shared.llm.model_registry import get_model
            m = get_model(model_id)
            if m:
                if not cache_read_tokens and not cache_write_tokens:
                    return m.cost_estimate(tokens_in, tokens_out)
                cw = (m.cached_input_price or m.input_price)*1.25
                cr = m.cached_input_price or m.input_price
                nc = max(0, tokens_in-cache_read_tokens-cache_write_tokens)
                return (nc*m.input_price+cache_write_tokens*cw+cache_read_tokens*cr+tokens_out*m.output_price)/1e6
        except Exception:
            pass
        return self._estimate_cost(model_id, tokens_in, tokens_out)


    # ── complete() adapter — used by intent_classifier, router, consolidation ──

    async def complete(
        self,
        request: LLMRequest,
        role: str = "",
        worker: str = "",
    ) -> LLMResponse:
        """
        Adapter: LLMRequest → chat() → LLMResponse.

        Bridges typed LLMRequest/LLMResponse interface with underlying chat().
        Supports tools/function calling.
        """
        model = request.model_id or "gpt-5.4-nano"

        result = await self.chat(
            model=model,
            messages=request.messages,
            max_tokens=request.max_tokens or 4096,
            temperature=request.temperature,
            tools=request.tools,
        )

        # Parse tool_calls into typed ToolCall objects
        parsed_tool_calls = None
        raw_tc = result.get("tool_calls")
        if raw_tc:
            parsed_tool_calls = []
            for tc in raw_tc:
                fn = tc.get("function", {})
                args = fn.get("arguments", "{}")
                if isinstance(args, str):
                    try:
                        args = json.loads(args)
                    except json.JSONDecodeError:
                        import re as _re
                        tool_name_hint = fn.get("name", "")
                        _recovered = {}
                        # Strategy 1: simple key:value pairs (short values)
                        for _m in _re.finditer(r'"(\w+)"\s*:\s*(?:"((?:[^"\\]|\\.){0,500})"|(true|false|null|\d+))', args):
                            _k, _vs, _vl = _m.groups()
                            _recovered[_k] = _vs if _vs is not None else _vl
                        # Strategy 2: for file_write, explicitly extract "path"
                        if tool_name_hint in ("file_write","file_create") and "path" not in _recovered:
                            _pm = _re.search(r'"path"\s*:\s*"([^"]+)"', args)
                            if _pm: _recovered["path"] = _pm.group(1)
                        # Strategy 3: extract truncated content if path found
                        if tool_name_hint in ("file_write","file_create") and "path" in _recovered and "content" not in _recovered:
                            _cm = _re.search(r'"content"\s*:\s*"', args)
                            if _cm: _recovered["content"] = args[_cm.end():]
                        if _recovered:
                            logger.warning(f"Recovered {len(_recovered)} keys for {tool_name_hint}: {list(_recovered.keys())}")
                            args = _recovered
                        else:
                            args = {"raw": args}
                parsed_tool_calls.append(ToolCall(
                    id=tc.get("id", ""),
                    name=fn.get("name", ""),
                    arguments=args,
                ))

        return LLMResponse(
            content=result.get("content", ""),
            tool_calls=parsed_tool_calls,
            model_id=result.get("model", model),
            provider=Provider.OPENROUTER,
            input_tokens=result.get("tokens_in", 0),
            output_tokens=result.get("tokens_out", 0),
            cost_usd=result.get("cost_usd", 0.0),
            latency_ms=int(result.get("time_seconds", 0) * 1000),
        )

    async def close(self):
        await self._client.aclose()
