"""
ARCANE 2 — Debate Mode (Режим Дебатов)
======================================
True adversarial debate: each model sees the other models' arguments and
responds directly, building a real back-and-forth conversation.

Architecture:
  Phase 0: Moderator generates opening question / sub-questions
  Phase 1: Each model gives opening statement (parallel, blind)
  Phase 2..N: Each model reads ALL previous statements and responds directly
              (sequential within round, parallel across models)
  Final: Judge/moderator synthesizes winner + key insights

Unlike collective_reasoning.py (critique → revision), here models
ARGUE — they can agree, disagree, challenge, or build on each other.

Spec ref: §10.5 Debate Mode
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any, AsyncGenerator, Optional

import httpx

logger = logging.getLogger("arcane2.debate_mode")

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

# ═══════════════════════════════════════════════════════════════════════════════
# System prompts
# ═══════════════════════════════════════════════════════════════════════════════

MODERATOR_SYSTEM = """You are a debate moderator for ARCANE — an AI platform.
Your job is to structure the debate: generate sharp, focused sub-questions
that will reveal genuine disagreements between AI models.
Be concise and neutral. Output JSON only."""

OPENING_SYSTEM = """You are participating in a structured AI debate.
Give your opening statement on the topic. Be direct, specific, and take a clear position.
Acknowledge uncertainty where it exists. Max 400 words."""

REBUTTAL_SYSTEM = """You are in a live AI debate. You have read the other participants' arguments.
Your job: respond directly to specific points made by others.
- Quote or reference specific claims you're addressing
- Challenge weak reasoning, not just conclusions
- Concede points where others are correct
- Advance your own position with new evidence or logic
Max 350 words. Be sharp and substantive."""

SYNTHESIS_SYSTEM = """You are the debate judge for ARCANE.
Analyze the full debate and produce a structured synthesis.
Output valid JSON only with these exact keys:
{
  "winner": "model_name or 'draw'",
  "winner_reason": "why this model won or why it's a draw",
  "final_answer": "the best answer to the original question, synthesizing all valid points",
  "key_agreements": ["point 1", "point 2"],
  "key_disagreements": [{"topic": "...", "positions": {"ModelA": "...", "ModelB": "..."}}],
  "strongest_argument": {"model": "...", "argument": "..."},
  "weakest_argument": {"model": "...", "argument": "..."},
  "confidence": 0.85
}"""


# ═══════════════════════════════════════════════════════════════════════════════
# Data structures
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class DebateConfig:
    models: tuple[str, ...]           # 2-4 models (OpenRouter IDs)
    judge: str                        # Synthesizer model
    rounds: int = 2                   # Number of rebuttal rounds (1-3)
    moderator: str = ""               # If empty, use judge as moderator
    temperature: float = 0.5
    judge_temperature: float = 0.1
    timeout_per_call: float = 90.0
    max_retries: int = 1
    max_response_chars: int = 8000
    model_labels: tuple[str, ...] = field(default_factory=tuple)  # display names

    def __post_init__(self):
        if not self.moderator:
            object.__setattr__(self, 'moderator', self.judge)
        if not self.model_labels:
            labels = tuple(f"Model {chr(65+i)}" for i in range(len(self.models)))
            object.__setattr__(self, 'model_labels', labels)


@dataclass
class DebateStatement:
    model_id: str
    model_label: str
    phase: str          # "opening" | "rebuttal_1" | "rebuttal_2" | ...
    round_num: int
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
            "phase": self.phase,
            "round_num": self.round_num,
            "content": self.content,
            "latency_s": round(self.latency_s, 2),
            "cost_usd": round(self.cost_usd, 6),
            "ok": self.ok,
            "error": self.error,
        }


@dataclass
class DebateReport:
    topic: str
    winner: str
    winner_reason: str
    final_answer: str
    key_agreements: list[str]
    key_disagreements: list[dict]
    strongest_argument: dict
    weakest_argument: dict
    confidence: float
    all_statements: list[list[dict]]   # [round][statements]
    judge_model: str
    models_used: list[str]
    total_cost_usd: float
    total_latency_s: float
    num_rounds: int

    def to_dict(self) -> dict:
        return {
            "topic": self.topic,
            "winner": self.winner,
            "winner_reason": self.winner_reason,
            "final_answer": self.final_answer,
            "key_agreements": self.key_agreements,
            "key_disagreements": self.key_disagreements,
            "strongest_argument": self.strongest_argument,
            "weakest_argument": self.weakest_argument,
            "confidence": self.confidence,
            "all_statements": self.all_statements,
            "judge_model": self.judge_model,
            "models_used": self.models_used,
            "total_cost_usd": round(self.total_cost_usd, 6),
            "total_latency_s": round(self.total_latency_s, 1),
            "num_rounds": self.num_rounds,
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
    """Returns (content, latency_s, cost_usd, error)."""
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://arcaneai.ru",
        "X-Title": "Arcane 2 Debate",
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
# Debate phases
# ═══════════════════════════════════════════════════════════════════════════════

async def _opening_statements(
    client: httpx.AsyncClient,
    api_key: str,
    topic: str,
    config: DebateConfig,
) -> list[DebateStatement]:
    """Phase 1: All models give opening statements in parallel (blind)."""

    async def _open(i: int, model_id: str) -> DebateStatement:
        label = config.model_labels[i]
        messages = [
            {"role": "system", "content": OPENING_SYSTEM},
            {"role": "user", "content": f"Debate topic: {topic}\n\nGive your opening statement."},
        ]
        content, lat, cost, err = await _call(
            client, api_key, model_id, messages,
            config.temperature, config.timeout_per_call, config.max_retries,
        )
        return DebateStatement(
            model_id=model_id, model_label=label,
            phase="opening", round_num=0,
            content=content, latency_s=lat, cost_usd=cost, error=err,
        )

    results = await asyncio.gather(*[_open(i, m) for i, m in enumerate(config.models)])
    return list(results)


async def _rebuttal_round(
    client: httpx.AsyncClient,
    api_key: str,
    topic: str,
    all_previous: list[DebateStatement],
    config: DebateConfig,
    round_num: int,
) -> list[DebateStatement]:
    """Rebuttal round: each model reads ALL previous statements and responds."""

    # Build the debate transcript so far
    def _build_transcript(exclude_model_idx: int) -> str:
        parts = []
        for stmt in all_previous:
            if stmt.ok:
                parts.append(
                    f"[{stmt.model_label} — {stmt.phase}]\n"
                    f"{stmt.content[:config.max_response_chars]}\n"
                )
        return "\n---\n".join(parts)

    async def _rebut(i: int, model_id: str) -> DebateStatement:
        label = config.model_labels[i]
        transcript = _build_transcript(i)
        messages = [
            {"role": "system", "content": REBUTTAL_SYSTEM},
            {
                "role": "user",
                "content": (
                    f"Debate topic: {topic}\n\n"
                    f"=== DEBATE SO FAR ===\n{transcript}\n\n"
                    f"=== YOUR TURN ===\n"
                    f"You are {label}. Give your rebuttal (round {round_num})."
                ),
            },
        ]
        content, lat, cost, err = await _call(
            client, api_key, model_id, messages,
            config.temperature, config.timeout_per_call, config.max_retries,
        )
        return DebateStatement(
            model_id=model_id, model_label=label,
            phase=f"rebuttal_{round_num}", round_num=round_num,
            content=content, latency_s=lat, cost_usd=cost, error=err,
        )

    results = await asyncio.gather(*[_rebut(i, m) for i, m in enumerate(config.models)])
    return list(results)


async def _synthesize(
    client: httpx.AsyncClient,
    api_key: str,
    topic: str,
    all_statements: list[DebateStatement],
    config: DebateConfig,
) -> dict:
    """Final judge synthesizes the full debate."""
    transcript_parts = []
    for stmt in all_statements:
        if stmt.ok:
            transcript_parts.append(
                f"[{stmt.model_label} — {stmt.phase}]\n"
                f"{stmt.content[:3000]}"
            )
    transcript = "\n\n---\n\n".join(transcript_parts)

    messages = [
        {"role": "system", "content": SYNTHESIS_SYSTEM},
        {
            "role": "user",
            "content": (
                f"Debate topic: {topic}\n\n"
                f"=== FULL DEBATE TRANSCRIPT ===\n{transcript}\n\n"
                f"Synthesize the debate. Output JSON only."
            ),
        },
    ]
    content, lat, cost, err = await _call(
        client, api_key, config.judge, messages,
        config.judge_temperature, config.timeout_per_call + 30, config.max_retries,
    )
    return {"content": content, "latency_s": lat, "cost_usd": cost, "error": err}


def _parse_synthesis(content: str) -> dict:
    """Parse JSON from judge synthesis response."""
    import re
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
        "winner": "draw",
        "winner_reason": "Could not parse synthesis",
        "final_answer": content,
        "key_agreements": [],
        "key_disagreements": [],
        "strongest_argument": {},
        "weakest_argument": {},
        "confidence": 0.5,
    }


# ═══════════════════════════════════════════════════════════════════════════════
# Main entry point
# ═══════════════════════════════════════════════════════════════════════════════

async def run_debate(
    topic: str,
    config: DebateConfig,
    api_key: str,
    *,
    budget_remaining_usd: float | None = None,
    on_event: Any = None,  # async callable(event_dict) for streaming
) -> DebateReport:
    """
    Run a full debate session.

    Args:
        topic: The debate question/topic
        config: Debate configuration
        api_key: OpenRouter API key
        budget_remaining_usd: Stop if cost exceeds this
        on_event: Optional async callback for streaming progress events
    """
    t0 = time.monotonic()
    total_cost = 0.0
    all_statements: list[DebateStatement] = []
    all_rounds_dicts: list[list[dict]] = []

    async def emit(event_type: str, data: dict):
        if on_event:
            try:
                await on_event({"type": event_type, **data})
            except Exception:
                pass

    async with httpx.AsyncClient(timeout=config.timeout_per_call + 20) as client:

        # ── Phase 1: Opening statements ───────────────────────────────────
        logger.info(f"Debate: Opening statements — {len(config.models)} models")
        await emit("phase_start", {"phase": "opening", "models": list(config.model_labels)})

        openings = await _opening_statements(client, api_key, topic, config)
        round_cost = sum(s.cost_usd for s in openings)
        total_cost += round_cost
        all_statements.extend(openings)
        all_rounds_dicts.append([s.to_dict() for s in openings])

        for stmt in openings:
            await emit("statement", stmt.to_dict())

        logger.info(f"  Openings: {sum(1 for s in openings if s.ok)}/{len(openings)} OK, ${round_cost:.4f}")

        # ── Phases 2..N: Rebuttal rounds ──────────────────────────────────
        for round_num in range(1, config.rounds + 1):
            if budget_remaining_usd is not None and total_cost > budget_remaining_usd * 0.9:
                logger.warning(f"Budget limit approaching, stopping at round {round_num}")
                break

            logger.info(f"Debate: Rebuttal round {round_num}")
            await emit("phase_start", {
                "phase": f"rebuttal_{round_num}",
                "round_num": round_num,
                "models": list(config.model_labels),
            })

            rebuttals = await _rebuttal_round(
                client, api_key, topic, all_statements, config, round_num,
            )
            round_cost = sum(s.cost_usd for s in rebuttals)
            total_cost += round_cost
            all_statements.extend(rebuttals)
            all_rounds_dicts.append([s.to_dict() for s in rebuttals])

            for stmt in rebuttals:
                await emit("statement", stmt.to_dict())

            logger.info(f"  Rebuttals: {sum(1 for s in rebuttals if s.ok)}/{len(rebuttals)} OK, ${round_cost:.4f}")

        # ── Final: Synthesis ──────────────────────────────────────────────
        logger.info(f"Debate: Synthesis by {config.judge}")
        await emit("phase_start", {"phase": "synthesis", "judge": config.judge.split("/")[-1]})

        synth = await _synthesize(client, api_key, topic, all_statements, config)
        total_cost += synth["cost_usd"]

        parsed = _parse_synthesis(synth["content"])
        await emit("synthesis", {**parsed, "cost_usd": synth["cost_usd"]})

        report = DebateReport(
            topic=topic,
            winner=parsed.get("winner", "draw"),
            winner_reason=parsed.get("winner_reason", ""),
            final_answer=parsed.get("final_answer", synth["content"]),
            key_agreements=parsed.get("key_agreements", []),
            key_disagreements=parsed.get("key_disagreements", []),
            strongest_argument=parsed.get("strongest_argument", {}),
            weakest_argument=parsed.get("weakest_argument", {}),
            confidence=float(parsed.get("confidence", 0.5)),
            all_statements=all_rounds_dicts,
            judge_model=config.judge.split("/")[-1],
            models_used=[m.split("/")[-1] for m in config.models],
            total_cost_usd=total_cost,
            total_latency_s=time.monotonic() - t0,
            num_rounds=config.rounds,
        )

        logger.info(
            f"Debate done: winner={report.winner}, "
            f"${total_cost:.4f}, {report.total_latency_s:.1f}s"
        )
        return report
