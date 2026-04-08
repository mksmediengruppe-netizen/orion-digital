"""
manus_pipeline.py — ARCANE 4.0 Manus Pipeline Orchestration

High-level pipelines that coordinate Manus with other agents:

1. ResearchPipeline   — Manus browses Awwwards/competitors, Researcher analyzes
2. AssemblyPipeline   — Manus assembles HTML/CSS from specs, does visual QA
3. DeployPipeline     — Manus deploys to server with backup + health check

These pipelines are called by the Orchestrator after Observer routes the task.
"""
from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

logger = logging.getLogger("arcane.manus_pipeline")

# ─── Data structures ──────────────────────────────────────────────────────────

@dataclass
class ResearchResult:
    """Output of ResearchPipeline."""
    success: bool
    awwwards_references: list[dict] = field(default_factory=list)  # [{url, title, screenshot, notes}]
    competitor_analysis: list[dict] = field(default_factory=list)  # [{name, url, strengths, weaknesses}]
    market_insights: str = ""
    raw_manus_output: str = ""
    error: str = ""
    duration_seconds: float = 0.0


@dataclass
class AssemblyResult:
    """Output of AssemblyPipeline."""
    success: bool
    deploy_url: str = ""
    screenshots: dict[str, str] = field(default_factory=dict)  # {desktop, mobile}
    visual_issues: list[str] = field(default_factory=list)
    lighthouse_score: int = 0
    qa_rounds: int = 0
    error: str = ""
    duration_seconds: float = 0.0


@dataclass
class DeployResult:
    """Output of DeployPipeline."""
    success: bool
    deploy_url: str = ""
    backup_path: str = ""
    health_check_ok: bool = False
    error: str = ""
    duration_seconds: float = 0.0


# ─── Research Pipeline ────────────────────────────────────────────────────────

class ResearchPipeline:
    """
    Manus browses Awwwards and competitor sites.
    Observer watches for infinite loops.
    Researcher (Opus) analyzes the collected data.

    Flow:
        1. Observer validates budget
        2. Manus browses Awwwards (top 5 references for task type)
        3. Manus browses competitor sites (from positioning.json if available)
        4. Manus returns screenshots + text summaries
        5. Researcher (Opus) synthesizes into research_report.json
    """

    def __init__(self, manus_bridge=None, observer=None, llm_client=None):
        self.manus = manus_bridge
        self.observer = observer
        self.llm = llm_client

    async def run(
        self,
        project_id: str,
        task: str,
        project_dir: str | Path,
        positioning: dict | None = None,
        on_progress: Callable | None = None,
        mode: str = "balanced",
    ) -> ResearchResult:
        """Run full research pipeline."""
        start = time.time()
        project_path = Path(project_dir)

        if on_progress:
            await on_progress({"phase": "research", "step": "starting", "message": "Research: Manus начинает сбор референсов..."})

        # ── Build Manus research task ─────────────────────────────────────────
        competitors = []
        if positioning:
            competitors = [c.get("name", "") for c in positioning.get("competitors", []) if c.get("name")]

        competitor_str = ""
        if competitors:
            competitor_str = f"\n\nТакже изучи сайты конкурентов: {', '.join(competitors[:3])}"

        research_prompt = f"""Ты исследуешь рынок для проекта: {task}

ЗАДАЧА:
1. Зайди на https://www.awwwards.com/websites/ и найди 3-5 лучших сайтов похожей тематики
2. Для каждого сайта: сделай скриншот, запиши URL, отметь что делает его особенным
3. Обрати внимание на: цветовые схемы, типографику, анимации, структуру секций{competitor_str}

ФОРМАТ ОТВЕТА (JSON):
{{
  "awwwards_references": [
    {{
      "url": "https://...",
      "title": "название сайта",
      "industry": "тематика",
      "notable_features": ["особенность 1", "особенность 2"],
      "color_palette": ["#hex1", "#hex2"],
      "animation_style": "описание анимаций",
      "typography": "шрифты и стиль"
    }}
  ],
  "competitor_analysis": [
    {{
      "name": "название",
      "url": "https://...",
      "strengths": ["сильная сторона 1"],
      "weaknesses": ["слабость 1"],
      "design_quality": "low|medium|high"
    }}
  ],
  "market_insights": "общие выводы о рынке и дизайн-трендах"
}}"""

        if not self.manus:
            logger.warning("[ResearchPipeline] No Manus bridge, returning mock result")
            return ResearchResult(
                success=True,
                market_insights="Manus not configured — research skipped",
                duration_seconds=time.time() - start,
            )

        # ── Submit to Manus ───────────────────────────────────────────────────
        from core.manus_bridge import ManusPackage, ManusMode
        package = ManusPackage(
            project_id=project_id,
            task_description=research_prompt,
            instructions=[
                "Browse Awwwards.com and find 3-5 reference sites",
                "Take screenshots of each reference",
                "Analyze competitor sites if provided",
                "Return structured JSON with findings",
            ],
            mode=ManusMode(mode),
        )

        # Watchdog tick
        if self.observer:
            if not self.observer.watchdog_tick(project_id, project_id, "manus"):
                return ResearchResult(
                    success=False,
                    error="Observer/Watchdog: Research Manus stuck, aborting",
                    duration_seconds=time.time() - start,
                )

        manus_result = await self.manus.submit(package)

        if not manus_result.success:
            return ResearchResult(
                success=False,
                error=f"Manus research failed: {manus_result.error}",
                duration_seconds=time.time() - start,
            )

        # ── Parse Manus output ────────────────────────────────────────────────
        research_data = self._parse_research_output(manus_result.output or "")

        # ── Save research_report.json ─────────────────────────────────────────
        specs_dir = project_path / ".arcane" / "specs"
        specs_dir.mkdir(parents=True, exist_ok=True)
        research_file = specs_dir / "research_report.json"
        try:
            research_file.write_text(
                json.dumps(research_data, ensure_ascii=False, indent=2),
                encoding="utf-8"
            )
            logger.info("[ResearchPipeline] Saved research_report.json: %s", research_file)
        except Exception as e:
            logger.warning("[ResearchPipeline] Could not save research_report.json: %s", e)

        if on_progress:
            await on_progress({
                "phase": "research",
                "step": "complete",
                "message": f"Research: собрано {len(research_data.get('awwwards_references', []))} референсов"
            })

        return ResearchResult(
            success=True,
            awwwards_references=research_data.get("awwwards_references", []),
            competitor_analysis=research_data.get("competitor_analysis", []),
            market_insights=research_data.get("market_insights", ""),
            raw_manus_output=manus_result.output or "",
            duration_seconds=time.time() - start,
        )

    def _parse_research_output(self, output: str) -> dict:
        """Extract JSON from Manus output."""
        # Try to find JSON block
        if "{" in output and "}" in output:
            start = output.find("{")
            end = output.rfind("}") + 1
            try:
                return json.loads(output[start:end])
            except json.JSONDecodeError:
                pass

        # Fallback: return raw as insights
        return {
            "awwwards_references": [],
            "competitor_analysis": [],
            "market_insights": output[:500] if output else "No research data",
        }


# ─── Assembly Pipeline ────────────────────────────────────────────────────────

class AssemblyPipeline:
    """
    Manus assembles the site from code + specs, does visual QA.
    Observer controls QA rounds (max 3).
    Art Director (Opus) reviews screenshots and gives corrections.

    Flow:
        1. Observer validates budget
        2. Manus assembles: copies files to server, opens in browser
        3. Manus takes desktop + mobile screenshots
        4. Art Director (Opus) reviews screenshots → visual_issues list
        5. If issues: Developer fixes → Manus re-checks (max 3 rounds)
        6. Final deploy
    """

    def __init__(self, manus_bridge=None, observer=None, llm_client=None):
        self.manus = manus_bridge
        self.observer = observer
        self.llm = llm_client

    async def run(
        self,
        project_id: str,
        task: str,
        project_dir: str | Path,
        design_spec: dict | None = None,
        deploy_target: dict | None = None,
        motion_spec: dict | None = None,
        on_progress: Callable | None = None,
        mode: str = "balanced",
    ) -> AssemblyResult:
        """Run full assembly + visual QA pipeline."""
        start = time.time()
        project_path = Path(project_dir)
        qa_rounds = 0

        if not self.manus:
            logger.warning("[AssemblyPipeline] No Manus bridge configured")
            return AssemblyResult(
                success=True,
                deploy_url="http://localhost (mock)",
                duration_seconds=time.time() - start,
            )

        while True:
            # ── Watchdog check ────────────────────────────────────────────────
            if self.observer:
                if not self.observer.watchdog_tick(project_id, project_id, "qa"):
                    logger.warning("[AssemblyPipeline] QA rounds limit reached, accepting result")
                    break

            if on_progress:
                await on_progress({
                    "phase": "visual_qa",
                    "step": f"round_{qa_rounds + 1}",
                    "message": f"Visual QA раунд {qa_rounds + 1}: Manus проверяет..."
                })

            # ── Build and submit Manus package ────────────────────────────────
            package = self.manus.build_package(
                project_id=project_id,
                task=self._build_qa_task(task, qa_rounds, design_spec, motion_spec),
                project_dir=project_dir,
                design_spec=design_spec,
                deploy_target=deploy_target if qa_rounds == 0 else None,  # deploy only on first round
                mode=mode,
            )

            manus_result = await self.manus.submit(package)

            if not manus_result.success:
                return AssemblyResult(
                    success=False,
                    error=f"Manus assembly failed (round {qa_rounds + 1}): {manus_result.error}",
                    qa_rounds=qa_rounds,
                    duration_seconds=time.time() - start,
                )

            qa_rounds += 1

            # ── Check if visual issues need fixing ────────────────────────────
            if not manus_result.has_visual_issues:
                logger.info("[AssemblyPipeline] Visual QA passed in %d rounds", qa_rounds)
                break

            # ── Art Director review (if LLM available) ────────────────────────
            if self.llm and manus_result.screenshots:
                art_director_issues = await self._art_director_review(
                    manus_result.screenshots,
                    design_spec,
                    manus_result.visual_issues,
                )
                if not art_director_issues:
                    logger.info("[AssemblyPipeline] Art Director approved result")
                    break
                logger.info(
                    "[AssemblyPipeline] Art Director found %d issues, round %d",
                    len(art_director_issues), qa_rounds
                )
            else:
                # No LLM review — accept after first pass
                break

        return AssemblyResult(
            success=True,
            deploy_url=manus_result.deploy_url if manus_result else "",
            screenshots=manus_result.screenshots if manus_result else {},
            visual_issues=manus_result.visual_issues if manus_result else [],
            lighthouse_score=manus_result.lighthouse_score if manus_result else 0,
            qa_rounds=qa_rounds,
            duration_seconds=time.time() - start,
        )

    def _build_qa_task(
        self,
        original_task: str,
        round_num: int,
        design_spec: dict | None,
        motion_spec: dict | None,
    ) -> str:
        """Build QA task description for Manus."""
        base = f"Visual QA for: {original_task}"

        if round_num == 0:
            instructions = [
                "Open the site in browser at 1440px width (desktop)",
                "Take full-page screenshot",
                "Resize to 375px (mobile) and take screenshot",
                "Check: no horizontal scroll on mobile",
                "Check: all fonts loaded correctly",
                "Check: images not broken",
                "Run Lighthouse performance audit",
            ]
        else:
            instructions = [
                f"QA Round {round_num + 1}: Re-check after fixes",
                "Compare with previous screenshots",
                "Verify all reported issues are resolved",
                "Take new desktop + mobile screenshots",
            ]

        if design_spec:
            palette = design_spec.get("color_palette", {})
            if palette:
                primary = palette.get("primary", "")
                if primary:
                    instructions.append(f"Verify primary color {primary} is used correctly")

        if motion_spec:
            instructions.append("Check: scroll animations trigger correctly")
            instructions.append("Check: page transitions are smooth (60fps)")

        return base + "\n\nInstructions:\n" + "\n".join(f"- {i}" for i in instructions)

    async def _art_director_review(
        self,
        screenshots: dict,
        design_spec: dict | None,
        manus_issues: list[str],
    ) -> list[str]:
        """Art Director (Opus) reviews screenshots and returns additional issues."""
        if not self.llm:
            return []

        try:
            spec_summary = ""
            if design_spec:
                spec_summary = f"\nDesign spec: {json.dumps(design_spec, ensure_ascii=False)[:500]}"

            manus_issues_str = "\n".join(f"- {i}" for i in manus_issues) if manus_issues else "None"

            prompt = f"""Ты — Art Director ARCANE 4.0. Проверь визуальное качество сайта.

Manus уже нашёл эти проблемы:
{manus_issues_str}
{spec_summary}

Скриншоты прикреплены. Найди ДОПОЛНИТЕЛЬНЫЕ проблемы:
- Несоответствие дизайн-спеке (цвета, шрифты, отступы)
- Визуальный дисбаланс или непропорциональность
- Проблемы с типографикой (размеры, межстрочный интервал)
- Недостаточный контраст
- Анимации выглядят дёшево или сломаны

Ответь JSON:
{{"additional_issues": ["проблема 1", "проблема 2"], "approved": true/false}}
Если approved: true — дополнительных проблем нет."""

            response = await self.llm.complete(
                model="claude-opus-4.6",
                messages=[{"role": "user", "content": prompt}],
                max_tokens=300,
                temperature=0.0,
            )

            text = response.get("content", "").strip()
            if "{" in text:
                data = json.loads(text[text.find("{"):text.rfind("}") + 1])
                if data.get("approved"):
                    return []
                return data.get("additional_issues", [])

        except Exception as e:
            logger.warning("[AssemblyPipeline] Art Director review failed: %s", e)

        return []


# ─── Deploy Pipeline ──────────────────────────────────────────────────────────

class DeployPipeline:
    """
    Manus deploys to production server via SSH.
    Creates backup before deploy.
    Verifies HTTP 200 after deploy.
    """

    def __init__(self, manus_bridge=None, observer=None):
        self.manus = manus_bridge
        self.observer = observer

    async def run(
        self,
        project_id: str,
        project_dir: str | Path,
        deploy_target: dict,
        on_progress: Callable | None = None,
        mode: str = "balanced",
    ) -> DeployResult:
        """Deploy to production."""
        start = time.time()

        if not self.manus:
            return DeployResult(
                success=False,
                error="Manus bridge not configured",
                duration_seconds=time.time() - start,
            )

        if on_progress:
            await on_progress({
                "phase": "deploy",
                "step": "starting",
                "message": f"Deploy: Manus деплоит на {deploy_target.get('host', 'server')}..."
            })

        # Watchdog check
        if self.observer:
            if not self.observer.watchdog_tick(project_id, project_id, "manus"):
                return DeployResult(
                    success=False,
                    error="Observer/Watchdog: Deploy Manus stuck, aborting",
                    duration_seconds=time.time() - start,
                )

        package = self.manus.build_package(
            project_id=project_id,
            task=f"Deploy project {project_id} to production",
            project_dir=project_dir,
            deploy_target=deploy_target,
            mode=mode,
        )
        # Override instructions for deploy-only
        package.instructions = [
            f"SSH to {deploy_target.get('user', 'root')}@{deploy_target.get('host', '')}",
            f"Create backup: cp -r {deploy_target.get('path', '/var/www/html')} {deploy_target.get('path', '/var/www/html')}.bak.$(date +%Y%m%d_%H%M%S)",
            f"Upload files to {deploy_target.get('path', '/var/www/html')}",
            "Verify HTTP 200: curl -s -o /dev/null -w '%{http_code}' http://localhost",
            "If HTTP 200: report success. If not: rollback from backup.",
        ]

        manus_result = await self.manus.submit(package)

        if on_progress:
            status = "success" if manus_result.success else "failed"
            await on_progress({
                "phase": "deploy",
                "step": status,
                "message": f"Deploy: {manus_result.deploy_status}"
            })

        return DeployResult(
            success=manus_result.success,
            deploy_url=manus_result.deploy_url,
            health_check_ok=manus_result.deploy_status == "deployed",
            error=manus_result.error if not manus_result.success else "",
            duration_seconds=time.time() - start,
        )


# ─── Pipeline Factory ─────────────────────────────────────────────────────────

class ManusPipelineFactory:
    """Creates pipeline instances with shared dependencies."""

    def __init__(self, manus_bridge=None, observer=None, llm_client=None):
        self.manus = manus_bridge
        self.observer = observer
        self.llm = llm_client

    def research(self) -> ResearchPipeline:
        return ResearchPipeline(self.manus, self.observer, self.llm)

    def assembly(self) -> AssemblyPipeline:
        return AssemblyPipeline(self.manus, self.observer, self.llm)

    def deploy(self) -> DeployPipeline:
        return DeployPipeline(self.manus, self.observer)
