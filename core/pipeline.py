"""
ARCANE 2 — Multi-Agent Pipeline
=================================
Реализует конвейер где разные модели выполняют разные фазы одной задачи.

Принцип: агенты не разговаривают друг с другом напрямую.
Они говорят с файловой системой и структурированным контекстом.
ARCANE передаёт вывод одного агента как контекст следующему.

Конвейер для web_design:
  1. Architect (GPT-5.4)          → декомпозиция, tech stack, структура файлов
  2. Builder (Claude/Qwen)        → пишет HTML/CSS/JS по архитектуре
  3. QA Reviewer (Gemini/GPT)     → находит баги, проблемы UX
  4. Fixer (тот же Builder)       → исправляет по фидбэку QA
  5. Deployer (Claude/SSH model)  → деплой + health check

Конвейер для coding:
  1. Architect   → структура кода, API дизайн, типы данных
  2. Builder     → реализация
  3. QA          → code review, тесты, edge cases
  4. Fixer       → исправления
"""
from __future__ import annotations

import asyncio
import logging
import os
from typing import Any, Callable, Optional

logger = logging.getLogger("arcane.pipeline")


# ── Phase definitions ─────────────────────────────────────────────────────────

class PipelinePhase:
    """One phase of a multi-agent pipeline."""

    def __init__(
        self,
        name: str,
        role: str,                      # role key in team dict
        system_instruction: str,        # что делает эта модель
        output_key: str,                # куда пишет результат
        depends_on: list[str] | None = None,  # фазы от которых зависит
        skip_if_empty: bool = False,    # пропустить если нет артефактов
    ):
        self.name = name
        self.role = role
        self.system_instruction = system_instruction
        self.output_key = output_key
        self.depends_on = depends_on or []
        self.skip_if_empty = skip_if_empty


PIPELINE_WEB_DESIGN = [
    PipelinePhase(
        name="architecture",
        role="planner",
        output_key="architecture_plan",
        system_instruction="""You are a senior web architect. Given the task, produce ONLY a structured plan:

1. TECH STACK: list exact technologies (e.g. "HTML5, CSS3 with custom properties, vanilla JS")
2. FILE STRUCTURE: list all files to create (e.g. index.html, style.css, script.js)  
3. SECTIONS: list each section of the page with its content (e.g. "Hero: title, CTA button, background image")
4. COLOR SCHEME: primary, secondary, background, text colors (hex codes)
5. KEY FEATURES: list 3-5 specific features to implement

Be specific and concise. No HTML code yet — just the plan.""",
    ),
    PipelinePhase(
        name="build",
        role="designer",
        output_key="built_artifacts",
        depends_on=["architecture"],
        system_instruction="""You are an expert frontend developer. 
Build the complete web page following the architecture plan exactly.
Write production-quality code — no placeholders, no Lorem ipsum.
Create all files specified in the plan.""",
    ),
    PipelinePhase(
        name="review",
        role="qa",
        output_key="review_feedback",
        depends_on=["build"],
        skip_if_empty=True,
        system_instruction="""You are a senior UX/code reviewer. Review the built page and list SPECIFIC issues:

For each issue provide:
- ISSUE: what's wrong
- FILE: which file
- FIX: exactly how to fix it (be specific, not generic)

Categories to check:
1. Responsiveness (does it work on 320px?)
2. Content (any Lorem ipsum, placeholder, TODO?)
3. Links (any href="#" or broken?)
4. Accessibility (alt tags, contrast, focus styles?)
5. Performance (blocking scripts, missing lazy loading?)
6. Visual quality (looks professional?)

Format: list of specific actionable fixes. Max 5 most important.""",
    ),
    PipelinePhase(
        name="fix",
        role="designer",
        output_key="fixed_artifacts",
        depends_on=["review"],
        skip_if_empty=True,
        system_instruction="""You are an expert frontend developer.
Apply ALL the review fixes to the code.
Make targeted edits — don't rewrite everything, just fix the specific issues.""",
    ),
]

PIPELINE_CODING = [
    PipelinePhase(
        name="architecture",
        role="planner",
        output_key="architecture_plan",
        system_instruction="""You are a senior software architect. Given the task, produce ONLY:

1. MODULE STRUCTURE: list all files/modules with their responsibility
2. KEY CLASSES/FUNCTIONS: with signatures and brief description
3. DATA MODELS: types, interfaces, schemas
4. DEPENDENCIES: external libraries needed
5. EDGE CASES: list 3-5 edge cases to handle

Be specific. No code yet — just the design.""",
    ),
    PipelinePhase(
        name="build",
        role="coder",
        output_key="built_artifacts",
        depends_on=["architecture"],
        system_instruction="""You are an expert software engineer.
Implement the complete solution following the architecture plan.
Write production-quality code with type hints, error handling, and docstrings.""",
    ),
    PipelinePhase(
        name="review",
        role="qa",
        output_key="review_feedback",
        depends_on=["build"],
        skip_if_empty=True,
        system_instruction="""You are a senior code reviewer. Review the code and provide SPECIFIC fixes:

1. BUGS: logic errors, off-by-one, null pointer, etc.
2. EDGE CASES: unhandled inputs, empty data, network failures
3. SECURITY: injection, hardcoded secrets, unsafe operations
4. PERFORMANCE: inefficient loops, missing caching
5. STYLE: inconsistent naming, missing types, poor error messages

For each issue: ISSUE + FILE + LINE + FIX. Max 5 most critical.""",
    ),
    PipelinePhase(
        name="fix",
        role="coder",
        output_key="fixed_artifacts",
        depends_on=["review"],
        skip_if_empty=True,
        system_instruction="""Apply all review fixes precisely.
Run validation after each fix. Confirm all issues are resolved.""",
    ),
]


PIPELINES = {
    "web_design": PIPELINE_WEB_DESIGN,
    "design": PIPELINE_WEB_DESIGN,
    "coding": PIPELINE_CODING,
    "automation": PIPELINE_CODING,
    "cms_management": PIPELINE_CODING,
}


# ── Pipeline executor ─────────────────────────────────────────────────────────

class MultiAgentPipeline:
    """
    Runs a sequence of specialized agents, each using the best model for its role.
    Agents communicate through structured context (not direct conversation).
    """

    def __init__(
        self,
        llm_client,
        team: dict[str, str],       # role → model_id
        project_id: str,
        task: str,
        task_type: str,
        workspace: str | None = None,
        on_progress: Callable | None = None,   # callback(phase, message)
        budget_limit: float | None = None,
    ):
        self._llm = llm_client
        self._team = team
        self._project_id = project_id
        self._task = task
        self._task_type = task_type
        self._workspace = workspace or os.environ.get("ARCANE_WORKSPACE", "/root/workspace")
        self._on_progress = on_progress
        self._budget_limit = budget_limit or 10.0
        self._total_cost = 0.0
        self._context: dict[str, Any] = {}   # accumulated context across phases

    def _get_model(self, role: str) -> str:
        """Get the best model for this role."""
        # Direct role match
        if role in self._team:
            return self._team[role]
        # Fallback chain
        fallbacks = {
            "planner":   ["architect", "coder", "designer", "claude-sonnet-4.6"],
            "architect": ["planner", "coder", "claude-sonnet-4.6"],
            "designer":  ["coder", "claude-haiku-4.5", "qwen3-coder-free"],
            "coder":     ["designer", "claude-haiku-4.5", "qwen3-coder-free"],
            "qa":        ["coder", "gpt-5.4-nano", "qwen3-coder-free"],
            "reviewer":  ["qa", "gpt-5.4-nano"],
        }
        for fb in fallbacks.get(role, []):
            if fb in self._team:
                return self._team[fb]
            # Check if it's a model ID directly
            if "/" in fb or "-" in fb:
                return fb
        # Ultimate fallback
        return next(iter(self._team.values()), "claude-haiku-4.5")

    async def _emit(self, phase: str, message: str):
        if self._on_progress:
            try:
                if asyncio.iscoroutinefunction(self._on_progress):
                    await self._on_progress(phase, message)
                else:
                    self._on_progress(phase, message)
            except Exception:
                pass
        logger.info(f"[Pipeline:{self._project_id}] [{phase}] {message}")

    def _build_phase_prompt(self, phase: PipelinePhase) -> str:
        """Build the prompt for this phase including context from previous phases."""
        parts = [
            f"# TASK\n{self._task}\n",
            f"# YOUR ROLE IN THIS PHASE: {phase.name.upper()}\n{phase.system_instruction}\n",
        ]

        # Inject context from previous phases
        for dep in phase.depends_on:
            if dep in self._context:
                dep_output = str(self._context[dep])[:3000]
                parts.append(f"# OUTPUT FROM {dep.upper()} PHASE\n{dep_output}\n")

        # Inject current workspace state (existing files)
        src_dir = os.path.join(self._workspace, "projects", self._project_id, "src")
        if os.path.isdir(src_dir):
            files = []
            for root, dirs, fnames in os.walk(src_dir):
                dirs[:] = [d for d in dirs if not d.startswith(".")]
                for fname in fnames[:10]:
                    fpath = os.path.join(root, fname)
                    rel = os.path.relpath(fpath, src_dir)
                    try:
                        size = os.path.getsize(fpath)
                        files.append(f"  {rel} ({size} bytes)")
                    except OSError:
                        pass
            if files:
                parts.append(f"# EXISTING FILES IN PROJECT\n" + "\n".join(files) + "\n")

        return "\n".join(parts)

    async def _run_phase(self, phase: PipelinePhase) -> str:
        """Run a single pipeline phase and return its output."""
        model = self._get_model(phase.role)
        await self._emit(phase.name, f"Starting with {model}")

        prompt = self._build_phase_prompt(phase)

        try:
            response = await asyncio.wait_for(
                self._llm.chat(
                    model=model,
                    messages=[
                        {
                            "role": "system",
                            "content": f"You are a specialized AI agent in a multi-agent pipeline. "
                                       f"Your role is: {phase.name}. "
                                       f"Be precise, specific, and actionable. "
                                       f"Focus only on your role's responsibilities.",
                        },
                        {"role": "user", "content": prompt},
                    ],
                    max_tokens=4096,
                    temperature=0.2,
                ),
                timeout=90.0,
            )

            if isinstance(response, dict):
                cost = response.get("cost_usd", 0.0)
                self._total_cost += cost
                output = response.get("content", "")
                tokens = response.get("tokens_out", 0)
                await self._emit(phase.name, f"Done ({tokens} tokens, ${cost:.4f})")
            else:
                output = str(response)
                await self._emit(phase.name, "Done")

            return output

        except asyncio.TimeoutError:
            await self._emit(phase.name, "TIMEOUT — skipping phase")
            return ""
        except Exception as e:
            await self._emit(phase.name, f"ERROR: {e}")
            return ""

    async def run(self) -> dict:
        """
        Execute the full pipeline.
        Returns: {phases, total_cost, final_context, artifacts_hint}
        """
        phases = PIPELINES.get(self._task_type, PIPELINE_CODING)

        await self._emit("pipeline", f"Starting {len(phases)}-phase pipeline for {self._task_type}")

        phase_results = {}
        for phase in phases:
            # Check budget
            if self._total_cost >= self._budget_limit * 0.8:
                await self._emit("pipeline", f"Budget limit approaching (${self._total_cost:.3f}), skipping remaining phases")
                break

            # Skip if depends on empty phase
            if phase.skip_if_empty:
                for dep in phase.depends_on:
                    if dep in self._context and not self._context[dep].strip():
                        await self._emit(phase.name, "Skipping — no input from previous phase")
                        continue

            output = await self._run_phase(phase)
            self._context[phase.output_key] = output
            self._context[phase.name] = output   # also store by phase name
            phase_results[phase.name] = {
                "model": self._get_model(phase.role),
                "output_length": len(output),
                "output_preview": output[:200],
            }

        await self._emit("pipeline", f"Pipeline complete. Total cost: ${self._total_cost:.4f}")

        return {
            "phases": phase_results,
            "total_cost": self._total_cost,
            "context": self._context,
            "task_type": self._task_type,
            "final_plan": self._context.get("architecture_plan", ""),
            "review_feedback": self._context.get("review_feedback", ""),
        }

    def get_enriched_task(self) -> str:
        """
        Get the original task enriched with pipeline results.
        Pass this to the main AgentLoop so it has full context.
        """
        parts = [self._task, ""]

        if "architecture_plan" in self._context:
            parts.append("=== АРХИТЕКТУРА (разработана специализированной моделью) ===")
            parts.append(self._context["architecture_plan"][:2000])
            parts.append("")

        if "review_feedback" in self._context and self._context["review_feedback"]:
            parts.append("=== ФИДБЭК QA (от специализированной модели) ===")
            parts.append(self._context["review_feedback"][:1000])
            parts.append("")
            parts.append("ВАЖНО: Учти весь фидбэк QA при выполнении задачи.")

        return "\n".join(parts)


# ── Convenience function ──────────────────────────────────────────────────────

async def run_pipeline_for_task(
    llm_client,
    team: dict[str, str],
    project_id: str,
    task: str,
    task_type: str,
    workspace: str | None = None,
    on_progress: Callable | None = None,
    budget_limit: float | None = None,
) -> tuple[str, float]:
    """
    Run multi-agent pipeline and return (enriched_task, cost).
    The enriched_task includes architecture + QA feedback,
    ready to pass to the main AgentLoop.
    """
    if task_type not in PIPELINES:
        # No pipeline defined for this type — return original task
        return task, 0.0

    pipeline = MultiAgentPipeline(
        llm_client=llm_client,
        team=team,
        project_id=project_id,
        task=task,
        task_type=task_type,
        workspace=workspace,
        on_progress=on_progress,
        budget_limit=budget_limit,
    )

    await pipeline.run()
    enriched = pipeline.get_enriched_task()
    return enriched, pipeline._total_cost
