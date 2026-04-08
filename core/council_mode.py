"""
ARCANE 2 — Council Mode (Режим Совета)
======================================
Each model gives an independent opinion in parallel (no cross-pollination).
A synthesizer model reads all opinions and produces a structured conclusion.

Unlike Debate (adversarial, iterative), Council is deliberative:
- Models don't see each other's answers
- Each gives their best independent assessment
- Synthesizer identifies consensus, unique insights, and contradictions

Architecture:
  Phase 1: All models answer in parallel (blind, independent)
  Phase 2: Synthesizer reads all opinions → structured conclusion

Spec ref: §10.5 Council Mode
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from dataclasses import dataclass, field
from typing import Any, Optional

import httpx

logger = logging.getLogger("arcane2.council_mode")

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

# ═══════════════════════════════════════════════════════════════════════════════
# System prompts
# ═══════════════════════════════════════════════════════════════════════════════

COUNCIL_MEMBER_SYSTEM = """You are a council member providing your expert opinion.
Give a thorough, honest assessment. Be specific. Take a clear position.
Acknowledge limitations and uncertainties. Max 500 words."""

COUNCIL_SYNTHESIZER_SYSTEM = """You are the council synthesizer for ARCANE.
You have received independent opinions from multiple AI models on the same question.
Your task: synthesize them into a structured conclusion.

Output valid JSON only with these exact keys:
{
  "final_answer": "the best comprehensive answer synthesizing all valid points",
  "consensus": "what all or most models agreed on",
  "unique_insights": [
    {"model": "ModelA", "insight": "something only this model mentioned that adds value"}
  ],
  "contradictions": [
    {"topic": "...", "model_a": "ModelA", "position_a": "...", "model_b": "ModelB", "position_b": "..."}
  ],
  "most_insightful": "which model gave the most valuable contribution and why",
  "recommendation": "actionable recommendation based on the council's collective wisdom",
  "confidence": 0.85
}"""


# ═══════════════════════════════════════════════════════════════════════════════
# Data structures
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class CouncilConfig:
    models: tuple[str, ...]           # 2-5 models (OpenRouter IDs)
    synthesizer: str                  # Synthesizer model
    temperature: float = 0.4
    synthesizer_temperature: float = 0.1
    timeout_per_call: float = 90.0
    max_retries: int = 1
    max_response_chars: int = 10000
    model_labels: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self):
        if not self.model_labels:
            labels = tuple(f"Советник {chr(1040+i)}" for i in range(len(self.models)))
            object.__setattr__(self, 'model_labels', labels)


@dataclass
class CouncilOpinion:
    model_id: str
    model_label: str
    content: str
    latency_s: float = 0.0
    cost_usd: float = 0.0
    error: Optional[str] = None

    @property
    def ok(self) -> bool:
        return self.error is None and bool(self.content)

    def to_dict(self) -> dict:
        return {
            "model_id": self.model_id,
            "model_label": self.model_label,
            "content": self.content,
            "latency_s": round(self.latency_s, 2),
            "cost_usd": round(self.cost_usd, 6),
            "ok": self.ok,
            "error": self.error,
        }


@dataclass
class CouncilReport:
    question: str
    final_answer: str
    consensus: str
    unique_insights: list[dict]
    contradictions: list[dict]
    most_insightful: str
    recommendation: str
    confidence: float
    opinions: list[dict]            # raw opinions from all models
    synthesizer_model: str
    models_used: list[str]
    total_cost_usd: float
    total_latency_s: float

    def to_dict(self) -> dict:
        return {
            "question": self.question,
            "final_answer": self.final_answer,
            "consensus": self.consensus,
            "unique_insights": self.unique_insights,
            "contradictions": self.contradictions,
            "most_insightful": self.most_insightful,
            "recommendation": self.recommendation,
            "confidence": self.confidence,
            "opinions": self.opinions,
            "synthesizer_model": self.synthesizer_model,
            "models_used": self.models_used,
            "total_cost_usd": round(self.total_cost_usd, 6),
            "total_latency_s": round(self.total_latency_s, 1),
        }


# ═══════════════════════════════════════════════════════════════════════════════
# Core API call
# ═══════════════════════════════════════════════════════════════════════════════

async def _call(
    client: httpx.AsyncClient,
    api_key: str,
    model_id: str,
    messages: list[dict],
    temperature: float,
    timeout_s: float,
    max_retries: int = 1,
) -> tuple[str, float, float, str | None]:
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://arcaneai.ru",
        "X-Title": "Arcane 2 Council",
    }
    payload = {
        "model": model_id,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": 2048,
    }
    t0 = time.monotonic()
    last_err = None
    for attempt in range(1 + max_retries):
        try:
            resp = await client.post(
                OPENROUTER_URL, headers=headers, json=payload, timeout=timeout_s,
            )
            if resp.status_code == 429:
                await asyncio.sleep(2 ** attempt)
                continue
            if resp.status_code != 200:
                last_err = f"HTTP {resp.status_code}: {resp.text[:200]}"
                continue
            data = resp.json()
            content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
            usage = data.get("usage", {})
            tok_in = usage.get("prompt_tokens", 0)
            tok_out = usage.get("completion_tokens", 0)
            cost = (tok_in * 2.0 + tok_out * 10.0) / 1_000_000
            return content, time.monotonic() - t0, cost, None
        except Exception as e:
            last_err = str(e)
            if attempt < max_retries:
                await asyncio.sleep(1)
    return "", time.monotonic() - t0, 0.0, last_err


# ═══════════════════════════════════════════════════════════════════════════════
# Council phases
# ═══════════════════════════════════════════════════════════════════════════════

async def _gather_opinions(
    client: httpx.AsyncClient,
    api_key: str,
    question: str,
    config: CouncilConfig,
) -> list[CouncilOpinion]:
    """Phase 1: All models answer independently in parallel."""

    async def _ask(i: int, model_id: str) -> CouncilOpinion:
        label = config.model_labels[i]
        messages = [
            {"role": "system", "content": COUNCIL_MEMBER_SYSTEM},
            {"role": "user", "content": f"Question for the council:\n\n{question}"},
        ]
        content, lat, cost, err = await _call(
            client, api_key, model_id, messages,
            config.temperature, config.timeout_per_call, config.max_retries,
        )
        return CouncilOpinion(
            model_id=model_id, model_label=label,
            content=content, latency_s=lat, cost_usd=cost, error=err,
        )

    results = await asyncio.gather(*[_ask(i, m) for i, m in enumerate(config.models)])
    return list(results)


async def _synthesize(
    client: httpx.AsyncClient,
    api_key: str,
    question: str,
    opinions: list[CouncilOpinion],
    config: CouncilConfig,
) -> tuple[str, float, float, str | None]:
    """Phase 2: Synthesizer reads all opinions and produces structured conclusion."""
    opinions_text = "\n\n---\n\n".join(
        f"[{op.model_label}]\n{op.content[:config.max_response_chars]}"
        for op in opinions if op.ok
    )
    messages = [
        {"role": "system", "content": COUNCIL_SYNTHESIZER_SYSTEM},
        {
            "role": "user",
            "content": (
                f"Question posed to the council:\n{question}\n\n"
                f"=== COUNCIL OPINIONS ===\n{opinions_text}\n\n"
                f"Synthesize the council's collective wisdom. Output JSON only."
            ),
        },
    ]
    return await _call(
        client, api_key, config.synthesizer, messages,
        config.synthesizer_temperature, config.timeout_per_call + 30, config.max_retries,
    )


def _parse_synthesis(content: str) -> dict:
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", content, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(1))
        except Exception:
            pass
    start = content.find("{")
    end = content.rfind("}")
    if start != -1 and end > start:
        try:
            return json.loads(content[start:end + 1])
        except Exception:
            pass
    return {
        "final_answer": content,
        "consensus": "",
        "unique_insights": [],
        "contradictions": [],
        "most_insightful": "",
        "recommendation": "",
        "confidence": 0.5,
    }


# ═══════════════════════════════════════════════════════════════════════════════
# Main entry point
# ═══════════════════════════════════════════════════════════════════════════════

async def run_council(
    question: str,
    config: CouncilConfig,
    api_key: str,
    *,
    budget_remaining_usd: float | None = None,
    on_event: Any = None,  # async callable(event_dict) for streaming
) -> CouncilReport:
    """
    Run a council session: parallel opinions → synthesized conclusion.

    Args:
        question: The question for the council
        config: Council configuration
        api_key: OpenRouter API key
        budget_remaining_usd: Budget limit
        on_event: Optional async callback for streaming progress events
    """
    t0 = time.monotonic()
    total_cost = 0.0

    async def emit(event_type: str, data: dict):
        if on_event:
            try:
                await on_event({"type": event_type, **data})
            except Exception:
                pass

    # Rough cost estimate: (models + 1 synthesizer) × avg_cost
    est_cost = (len(config.models) + 1) * 0.005
    if budget_remaining_usd is not None and est_cost > budget_remaining_usd:
        raise ValueError(
            f"Estimated cost ${est_cost:.3f} exceeds budget ${budget_remaining_usd:.3f}"
        )

    async with httpx.AsyncClient(timeout=config.timeout_per_call + 20) as client:

        # ── Phase 1: Gather opinions ──────────────────────────────────────
        logger.info(f"Council: Gathering opinions from {len(config.models)} models")
        await emit("phase_start", {
            "phase": "opinions",
            "models": list(config.model_labels),
            "count": len(config.models),
        })

        opinions = await _gather_opinions(client, api_key, question, config)
        round_cost = sum(op.cost_usd for op in opinions)
        total_cost += round_cost

        for op in opinions:
            await emit("opinion", op.to_dict())

        ok_count = sum(1 for op in opinions if op.ok)
        logger.info(f"  Opinions: {ok_count}/{len(opinions)} OK, ${round_cost:.4f}")

        if ok_count < 2:
            raise ValueError(f"Only {ok_count} models responded successfully — need at least 2")

        # ── Phase 2: Synthesize ───────────────────────────────────────────
        logger.info(f"Council: Synthesizing with {config.synthesizer}")
        await emit("phase_start", {
            "phase": "synthesis",
            "synthesizer": config.synthesizer.split("/")[-1],
        })

        content, lat, cost, err = await _synthesize(client, api_key, question, opinions, config)
        total_cost += cost

        if err:
            logger.error(f"Synthesis failed: {err}")

        parsed = _parse_synthesis(content)
        await emit("synthesis", {**parsed, "cost_usd": cost})

        report = CouncilReport(
            question=question,
            final_answer=parsed.get("final_answer", content),
            consensus=parsed.get("consensus", ""),
            unique_insights=parsed.get("unique_insights", []),
            contradictions=parsed.get("contradictions", []),
            most_insightful=parsed.get("most_insightful", ""),
            recommendation=parsed.get("recommendation", ""),
            confidence=float(parsed.get("confidence", 0.5)),
            opinions=[op.to_dict() for op in opinions],
            synthesizer_model=config.synthesizer.split("/")[-1],
            models_used=[m.split("/")[-1] for m in config.models],
            total_cost_usd=total_cost,
            total_latency_s=time.monotonic() - t0,
        )

        logger.info(
            f"Council done: confidence={report.confidence:.2f}, "
            f"${total_cost:.4f}, {report.total_latency_s:.1f}s"
        )
        return report
