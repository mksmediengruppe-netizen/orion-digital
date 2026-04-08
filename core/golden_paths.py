"""
ARCANE Golden Paths — Automatic Recipe Learning & Template Delivery

Golden Paths are proven, optimized task sequences that have been tested
and refined through real execution.  A pattern is promoted to a Golden
Path ONLY when ALL four criteria are met (spec §10.2):

    1. Repeatability  — the same pattern executed **3+ times successfully**
    2. Success        — at least 3 runs with verdict=SUCCESS
    3. Tests passed   — automated tests/QA passed on **every** successful run
    4. No rollback    — **zero** rollbacks across **all** runs (including failed)

Note: failed runs do not block promotion on their own, but a rollback
on *any* run (even a failed one) permanently blocks the candidate.
Optionally, human approval can be required before final promotion.

Also provides:
  • Pre-built landing-page blueprint templates (static catalog)
  • ZIP archive packaging for project delivery
"""

from __future__ import annotations

import copy
import fcntl
import fnmatch
import hashlib
import json
import os
import uuid
import zipfile
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from shared.utils.logger import get_logger

logger = get_logger("core.golden_paths")


# ═══════════════════════════════════════════════════════════════════════════════
# CONSTANTS
# ═══════════════════════════════════════════════════════════════════════════════

MIN_SUCCESSES_FOR_PROMOTION = 3
GOLDEN_PATHS_STORE = ".arcane/golden_paths.json"
MAX_OUTCOMES_PER_CANDIDATE = 50
MAX_ARCHIVE_SIZE_MB = 500


# ═══════════════════════════════════════════════════════════════════════════════
# DATA MODELS
# ═══════════════════════════════════════════════════════════════════════════════

class OutcomeVerdict(str, Enum):
    """Possible verdicts for a single run outcome."""
    SUCCESS = "success"
    FAILED = "failed"
    PARTIAL = "partial"


@dataclass
class RunOutcome:
    """Result of a single task execution, used for golden path evaluation."""
    run_id: str
    pattern_signature: str
    verdict: OutcomeVerdict
    tests_passed: bool
    rollback_triggered: bool
    duration_ms: int = 0
    cost_usd: float = 0.0
    model_used: str = ""
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    metadata: dict = field(default_factory=dict)


@dataclass
class GoldenPathCandidate:
    """
    Tracks accumulated outcomes for a pattern signature.
    Becomes a full Golden Path when promotion criteria are met.
    """
    pattern_signature: str
    pattern_label: str
    task_type: str                        # e.g. "landing_page", "api_deploy"
    steps_summary: list[str] = field(default_factory=list)
    outcomes: list[dict] = field(default_factory=list)

    # Promotion state
    promoted: bool = False
    promoted_at: Optional[str] = None
    requires_human_approval: bool = False
    human_approved: bool = False
    human_approved_by: Optional[str] = None

    # Stats (derived, but cached for quick access)
    total_runs: int = 0
    success_count: int = 0
    tests_passed_count: int = 0           # tests passed on SUCCESSFUL runs only
    rollback_count: int = 0
    avg_duration_ms: int = 0
    avg_cost_usd: float = 0.0

    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    updated_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


# ═══════════════════════════════════════════════════════════════════════════════
# PATTERN SIGNATURE
# ═══════════════════════════════════════════════════════════════════════════════

def compute_pattern_signature(
    task_type: str,
    steps: list[str],
    *,
    extra: str = "",
) -> str:
    """
    Compute a stable hash identifying a repeatable task pattern.

    Two runs match the same pattern when their task_type + ordered step
    sequence are identical.  The hash is deterministic so that different
    projects producing the same workflow converge on a single candidate.
    """
    normalized = [s.strip().lower() for s in steps if s.strip()]
    blob = json.dumps(
        {"task_type": task_type.lower().strip(), "steps": normalized, "extra": extra},
        sort_keys=True,
        ensure_ascii=False,
    )
    return hashlib.sha256(blob.encode()).hexdigest()[:16]


# ═══════════════════════════════════════════════════════════════════════════════
# GOLDEN PATH STORE  (project-local JSON file)
# ═══════════════════════════════════════════════════════════════════════════════

class GoldenPathStore:
    """
    Persistent store for golden path candidates and promoted paths.

    Storage layout (per project):
        {project_dir}/.arcane/golden_paths.json
        {
            "candidates": { "<signature>": { ... GoldenPathCandidate ... } },
            "promoted":   [ "<signature>", ... ]
        }

    Concurrency:
        Uses ``fcntl.flock(LOCK_EX)`` to serialize writes.  Every public
        mutating method re-reads from disk under the lock so stale caches
        cannot silently overwrite a concurrent update.
    """

    def __init__(self, project_dir: str):
        self._project_dir = project_dir
        self._store_path = os.path.join(project_dir, GOLDEN_PATHS_STORE)

    # ── persistence ──────────────────────────────────────────────

    def _ensure_dir(self) -> None:
        os.makedirs(os.path.dirname(self._store_path), exist_ok=True)

    def _read_disk(self) -> dict:
        """Always read from disk — never cache across calls."""
        if os.path.exists(self._store_path):
            try:
                with open(self._store_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if not isinstance(data, dict):
                        raise json.JSONDecodeError("not a dict", "", 0)
                    return data
            except (json.JSONDecodeError, OSError) as exc:
                logger.warning("Corrupted golden_paths store, resetting: %s", exc)
                return {"candidates": {}, "promoted": []}
        return {"candidates": {}, "promoted": []}

    def _write_disk(self, data: dict) -> None:
        """Atomic write: tmp + rename, under exclusive flock."""
        self._ensure_dir()
        tmp = self._store_path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, self._store_path)

    def _locked_update(self, fn):
        """
        Run *fn(data) -> result* under an exclusive file lock.

        The lock file is separate from the data file so we never
        truncate the data while another reader has it open.
        """
        self._ensure_dir()
        lock_path = self._store_path + ".lock"
        with open(lock_path, "w") as lock_fd:
            fcntl.flock(lock_fd, fcntl.LOCK_EX)
            try:
                data = self._read_disk()
                result = fn(data)
                self._write_disk(data)
                return result
            finally:
                fcntl.flock(lock_fd, fcntl.LOCK_UN)

    # ── public API ───────────────────────────────────────────────

    def record_outcome(self, outcome: RunOutcome, candidate_info: dict) -> dict:
        """
        Record a run outcome and evaluate promotion.

        Args:
            outcome: The run result.
            candidate_info: Must contain 'pattern_label', 'task_type',
                            'steps_summary', and optionally
                            'requires_human_approval'.

        Returns:
            A status dict: {"promoted": bool, "candidate": {...}, "reason": str}
        """
        def _do(data: dict) -> dict:
            sig = outcome.pattern_signature
            candidates = data.setdefault("candidates", {})

            # Upsert candidate
            if sig not in candidates:
                candidates[sig] = asdict(GoldenPathCandidate(
                    pattern_signature=sig,
                    pattern_label=candidate_info.get("pattern_label", sig),
                    task_type=candidate_info.get("task_type", "unknown"),
                    steps_summary=candidate_info.get("steps_summary", []),
                    requires_human_approval=candidate_info.get(
                        "requires_human_approval", False
                    ),
                ))

            cand = candidates[sig]

            # FIX audit#6: always escalate requires_human_approval to True
            if candidate_info.get("requires_human_approval"):
                cand["requires_human_approval"] = True

            # FIX audit#5: deduplicate by run_id
            existing_run_ids = {o.get("run_id") for o in cand["outcomes"]}
            if outcome.run_id in existing_run_ids:
                logger.warning(
                    "Duplicate run_id %s for pattern %s — skipping",
                    outcome.run_id, sig,
                )
                return {
                    "promoted": cand.get("promoted", False),
                    "candidate": copy.deepcopy(cand),
                    "reason": "duplicate_run_id",
                }

            cand["outcomes"].append(asdict(outcome))
            cand["total_runs"] += 1
            cand["updated_at"] = datetime.now(timezone.utc).isoformat()

            # Update aggregate stats
            is_success = outcome.verdict == OutcomeVerdict.SUCCESS
            if is_success:
                cand["success_count"] += 1
            # FIX audit#10: only count tests_passed on successful runs
            if is_success and outcome.tests_passed:
                cand["tests_passed_count"] += 1
            if outcome.rollback_triggered:
                cand["rollback_count"] += 1

            durations = [
                o["duration_ms"] for o in cand["outcomes"] if o.get("duration_ms")
            ]
            costs = [
                o["cost_usd"] for o in cand["outcomes"] if o.get("cost_usd")
            ]
            cand["avg_duration_ms"] = (
                int(sum(durations) / len(durations)) if durations else 0
            )
            cand["avg_cost_usd"] = (
                round(sum(costs) / len(costs), 4) if costs else 0.0
            )

            # FIX audit#9: cap outcomes to prevent unbounded growth
            if len(cand["outcomes"]) > MAX_OUTCOMES_PER_CANDIDATE:
                cand["outcomes"] = cand["outcomes"][-MAX_OUTCOMES_PER_CANDIDATE:]

            result = self._evaluate_promotion(cand, data)
            return result

        return self._locked_update(_do)

    def get_candidate(self, signature: str) -> dict | None:
        data = self._read_disk()
        cand = data.get("candidates", {}).get(signature)
        return copy.deepcopy(cand) if cand else None  # FIX audit#7

    def list_promoted(self) -> list[dict]:
        """Return all promoted golden paths (deep copies)."""
        data = self._read_disk()
        promoted_sigs = set(data.get("promoted", []))
        return [
            copy.deepcopy(cand)
            for sig, cand in data.get("candidates", {}).items()
            if sig in promoted_sigs
        ]

    def list_candidates(self, *, promoted_only: bool = False) -> list[dict]:
        """Return all candidates (deep copies), optionally filtered."""
        data = self._read_disk()
        candidates = list(data.get("candidates", {}).values())
        if promoted_only:
            promoted_sigs = set(data.get("promoted", []))
            candidates = [
                c for c in candidates if c["pattern_signature"] in promoted_sigs
            ]
        return copy.deepcopy(candidates)

    def approve_candidate(self, signature: str, approved_by: str = "user") -> bool:
        """
        Human-approve a candidate that is waiting for approval.
        Returns True if this triggered promotion.
        """
        def _do(data: dict) -> bool:
            cand = data.get("candidates", {}).get(signature)
            if not cand:
                return False

            cand["human_approved"] = True
            cand["human_approved_by"] = approved_by
            cand["updated_at"] = datetime.now(timezone.utc).isoformat()

            result = self._evaluate_promotion(cand, data)
            return result.get("promoted", False)

        return self._locked_update(_do)

    def find_matching_path(self, task_type: str, steps: list[str]) -> dict | None:
        """
        Check if a task matches an existing promoted golden path.
        Returns a deep copy of the golden path dict or None.
        """
        sig = compute_pattern_signature(task_type, steps)
        data = self._read_disk()
        promoted_sigs = set(data.get("promoted", []))
        if sig in promoted_sigs:
            cand = data["candidates"].get(sig)
            return copy.deepcopy(cand) if cand else None
        return None

    def find_similar_paths(
        self,
        task_type: str,
        *,
        promoted_only: bool = True,
    ) -> list[dict]:
        """
        Return golden paths of the same task_type, sorted by success_count.
        """
        data = self._read_disk()
        promoted_sigs = set(data.get("promoted", []))
        results = []
        for sig, cand in data.get("candidates", {}).items():
            if cand.get("task_type", "").lower() != task_type.lower():
                continue
            if promoted_only and sig not in promoted_sigs:
                continue
            results.append(cand)
        results.sort(key=lambda c: c.get("success_count", 0), reverse=True)
        return copy.deepcopy(results)

    # ── promotion logic ──────────────────────────────────────────

    @staticmethod
    def _evaluate_promotion(cand: dict, data: dict) -> dict:
        """
        Evaluate whether a candidate meets ALL promotion criteria.

        Mutates *cand* and *data["promoted"]* in-place if promotion
        succeeds.  The caller is responsible for persisting *data*.

        Returns {"promoted": bool, "candidate": <deep-copy>, "reason": str}
        """
        sig = cand["pattern_signature"]

        # Already promoted — nothing to do
        if cand.get("promoted"):
            return {
                "promoted": True,
                "candidate": copy.deepcopy(cand),
                "reason": "already_promoted",
            }

        # --- Criterion 1: 3+ successful outcomes ---
        success_count = cand.get("success_count", 0)
        if success_count < MIN_SUCCESSES_FOR_PROMOTION:
            return {
                "promoted": False,
                "candidate": copy.deepcopy(cand),
                "reason": (
                    f"need {MIN_SUCCESSES_FOR_PROMOTION} successes, "
                    f"have {success_count}"
                ),
            }

        # --- Criterion 2: tests passed on every successful run ---
        successful_outcomes = [
            o for o in cand.get("outcomes", [])
            if o.get("verdict") == OutcomeVerdict.SUCCESS
        ]
        all_tests_passed = all(o.get("tests_passed") for o in successful_outcomes)
        if not all_tests_passed:
            failed_tests = sum(
                1 for o in successful_outcomes if not o.get("tests_passed")
            )
            return {
                "promoted": False,
                "candidate": copy.deepcopy(cand),
                "reason": (
                    f"tests not passed on {failed_tests} of "
                    f"{len(successful_outcomes)} successful runs"
                ),
            }

        # --- Criterion 3: zero rollbacks across ALL runs ---
        rollback_count = cand.get("rollback_count", 0)
        if rollback_count > 0:
            return {
                "promoted": False,
                "candidate": copy.deepcopy(cand),
                "reason": f"rollback triggered {rollback_count} time(s)",
            }

        # --- Criterion 4 (optional): human approval ---
        if cand.get("requires_human_approval") and not cand.get("human_approved"):
            return {
                "promoted": False,
                "candidate": copy.deepcopy(cand),
                "reason": "waiting_for_human_approval",
            }

        # All criteria met — promote
        cand["promoted"] = True
        cand["promoted_at"] = datetime.now(timezone.utc).isoformat()

        promoted_list = data.setdefault("promoted", [])
        if sig not in promoted_list:
            promoted_list.append(sig)

        logger.info(
            "Golden path PROMOTED: %s (%s) — %d successes, tests OK, 0 rollbacks",
            cand.get("pattern_label", sig),
            sig,
            success_count,
        )
        return {
            "promoted": True,
            "candidate": copy.deepcopy(cand),
            "reason": "all_criteria_met",
        }


# ═══════════════════════════════════════════════════════════════════════════════
# CONVENIENCE HELPERS  (used by orchestrator / planner)
# ═══════════════════════════════════════════════════════════════════════════════

def record_run_outcome(
    project_dir: str,
    *,
    run_id: str,
    task_type: str,
    steps: list[str],
    pattern_label: str = "",
    success: bool,
    tests_passed: bool,
    rollback_triggered: bool,
    duration_ms: int = 0,
    cost_usd: float = 0.0,
    model_used: str = "",
    requires_human_approval: bool = False,
    metadata: dict | None = None,
) -> dict:
    """
    One-call helper: record an outcome and return promotion status.

    Typical call site — end of AgentLoop._finalize_task():

        from core.golden_paths import record_run_outcome
        result = record_run_outcome(
            project_dir=self._project_dir,
            run_id=state.chat_id,
            task_type="landing_page",
            steps=["scaffold", "search", "code", "qa", "deploy"],
            pattern_label="Landing page (HTML)",
            success=state.status == TaskStatus.COMPLETED,
            tests_passed=qa_passed,
            rollback_triggered=rollback_used,
            duration_ms=elapsed,
            cost_usd=state.total_cost,
            model_used=state.current_tier,
        )
        if result["promoted"]:
            logger.info("New golden path: %s", result["candidate"]["pattern_label"])
    """
    sig = compute_pattern_signature(task_type, steps)

    outcome = RunOutcome(
        run_id=run_id,
        pattern_signature=sig,
        verdict=OutcomeVerdict.SUCCESS if success else OutcomeVerdict.FAILED,
        tests_passed=tests_passed,
        rollback_triggered=rollback_triggered,
        duration_ms=duration_ms,
        cost_usd=cost_usd,
        model_used=model_used,
        metadata=metadata or {},
    )

    store = GoldenPathStore(project_dir)
    return store.record_outcome(
        outcome,
        candidate_info={
            "pattern_label": pattern_label or task_type,
            "task_type": task_type,
            "steps_summary": steps,
            "requires_human_approval": requires_human_approval,
        },
    )


def find_golden_path(
    project_dir: str,
    task_type: str,
    steps: list[str],
) -> dict | None:
    """Check if an exact golden path exists for the given pattern."""
    store = GoldenPathStore(project_dir)
    return store.find_matching_path(task_type, steps)


def find_similar_golden_paths(
    project_dir: str,
    task_type: str,
) -> list[dict]:
    """Find promoted golden paths of the same task_type."""
    store = GoldenPathStore(project_dir)
    return store.find_similar_paths(task_type, promoted_only=True)


def approve_golden_path(
    project_dir: str,
    signature: str,
    approved_by: str = "user",
) -> bool:
    """Human-approve a candidate waiting for approval."""
    store = GoldenPathStore(project_dir)
    return store.approve_candidate(signature, approved_by)


def list_golden_paths(project_dir: str) -> list[dict]:
    """List all promoted golden paths for a project."""
    store = GoldenPathStore(project_dir)
    return store.list_promoted()


# ═══════════════════════════════════════════════════════════════════════════════
# STATIC GOLDEN PATH TEMPLATES  (pre-defined blueprints)
# ═══════════════════════════════════════════════════════════════════════════════

LANDING_PAGE_TEMPLATES = {
    "dark_luxury": {
        "name": "Dark Luxury",
        "description": "Premium dark theme for barbershops, nightclubs, premium auto, jewelry",
        "file": "dark_luxury.html",
        "style": "Premium dark with gold accents and cinematic feel",
        "color_scheme": {
            "primary": "#1a1a2e",
            "secondary": "#16213e",
            "accent": "#d4af37",
            "background": "#0f0f1a",
            "text": "#e0e0e0",
        },
        "sections": [
            "hero", "features", "gallery", "testimonials",
            "pricing", "contact", "footer",
        ],
    },
    "warm_editorial": {
        "name": "Warm Editorial",
        "description": "Elegant warm theme for restaurants, cafes, bakeries, wine bars",
        "file": "warm_editorial.html",
        "style": "Warm editorial with serif typography and earthy palette",
        "color_scheme": {
            "primary": "#5c3d2e",
            "secondary": "#8b6f47",
            "accent": "#c4956a",
            "background": "#faf6f1",
            "text": "#2d2017",
        },
        "sections": [
            "hero", "about", "menu", "gallery",
            "testimonials", "reservation", "footer",
        ],
    },
    "clean_tech": {
        "name": "Clean Tech",
        "description": "Modern clean theme for SaaS, fintech, AI startups, B2B",
        "file": "clean_tech.html",
        "style": "Clean minimal with subtle gradients and sharp typography",
        "color_scheme": {
            "primary": "#4f46e5",
            "secondary": "#7c3aed",
            "accent": "#06b6d4",
            "background": "#ffffff",
            "text": "#111827",
        },
        "sections": [
            "hero", "features", "how_it_works", "pricing",
            "testimonials", "faq", "cta", "footer",
        ],
    },
    "bold_energy": {
        "name": "Bold Energy",
        "description": "Aggressive bold theme for fitness, sports, events, extreme",
        "file": "bold_energy.html",
        "style": "High-contrast bold with neon accents and dynamic angles",
        "color_scheme": {
            "primary": "#ef4444",
            "secondary": "#f97316",
            "accent": "#facc15",
            "background": "#0a0a0a",
            "text": "#ffffff",
        },
        "sections": [
            "hero", "programs", "trainers", "schedule",
            "testimonials", "pricing", "contact", "footer",
        ],
    },
    "soft_wellness": {
        "name": "Soft Wellness",
        "description": "Calm soft theme for medical, spa, beauty, education",
        "file": "soft_wellness.html",
        "style": "Soft pastels with rounded shapes and calming whitespace",
        "color_scheme": {
            "primary": "#6366f1",
            "secondary": "#a78bfa",
            "accent": "#34d399",
            "background": "#f8fafc",
            "text": "#334155",
        },
        "sections": [
            "hero", "services", "about", "team",
            "testimonials", "booking", "footer",
        ],
    },
    "japandi_minimal": {
        "name": "Japandi Minimal",
        "description": "Ultra-minimal theme for architecture, interior design, portfolios",
        "file": "japandi_minimal.html",
        "style": "Ultra-minimal with negative space, muted tones, hairline details",
        "color_scheme": {
            "primary": "#78716c",
            "secondary": "#a8a29e",
            "accent": "#c2b280",
            "background": "#fafaf9",
            "text": "#1c1917",
        },
        "sections": [
            "hero", "portfolio", "about", "philosophy",
            "contact", "footer",
        ],
    },
    "neobrutalist": {
        "name": "Neobrutalist",
        "description": "Edgy brutalist theme for creative agencies, web3, youth brands",
        "file": "neobrutalist.html",
        "style": "Thick borders, raw shapes, high contrast, intentional roughness",
        "color_scheme": {
            "primary": "#000000",
            "secondary": "#ff5722",
            "accent": "#ffeb3b",
            "background": "#f5f5dc",
            "text": "#000000",
        },
        "sections": [
            "hero", "services", "work", "about",
            "manifesto", "contact", "footer",
        ],
    },
}


def get_template(template_type: str) -> Optional[dict]:
    """Get a golden path template by type (returns a deep copy)."""
    tpl = LANDING_PAGE_TEMPLATES.get(template_type)
    return copy.deepcopy(tpl) if tpl else None  # FIX audit#7


def list_templates() -> list[dict]:
    """List all available golden path templates."""
    return [
        {"type": key, "name": val["name"], "description": val["description"]}
        for key, val in LANDING_PAGE_TEMPLATES.items()
    ]


def generate_template_prompt(template_type: str, user_details: dict) -> str:
    """
    Generate a detailed prompt for the LLM to create a landing page
    based on the golden path template and user's specific details.
    """
    template = get_template(template_type)
    if not template:
        return ""

    colors = template.get("color_scheme", {})
    sections = template.get("sections", [])
    style = template.get("style", template["name"])

    prompt = f"""Create a stunning, production-ready landing page using the following template:

Template: {template['name']}
Style: {style}

Color Scheme:
- Primary: {colors.get('primary', '#4f46e5')}
- Secondary: {colors.get('secondary', '#7c3aed')}
- Accent: {colors.get('accent', '#06b6d4')}
- Background: {colors.get('background', '#ffffff')}
- Text: {colors.get('text', '#111827')}

Required Sections (in order):
{chr(10).join(f'  {i+1}. {section.replace("_", " ").title()}' for i, section in enumerate(sections))}

User Details:
{json.dumps(user_details, indent=2, ensure_ascii=False)}

Technical Requirements:
- Single HTML file with embedded CSS (TailwindCSS via CDN)
- Responsive design (mobile-first with sm:, md:, lg:, xl: breakpoints)
- Smooth CSS animations: fade-in on scroll via IntersectionObserver, hover transitions (transition-all duration-300)
- Professional typography: Import 2 Google Fonts (one for headings, one for body)
- Semantic HTML5 with proper heading hierarchy (h1 > h2 > h3)
- Accessibility: ARIA labels, alt text on images, WCAG AA contrast ratios
- Performance: lazy-load images (loading="lazy"), minimal vanilla JS
- Include meta viewport, charset, title, description, Open Graph tags
- Use high-quality images from source.unsplash.com (800x600 for cards, 1920x1080 for hero)

DESIGN STANDARDS (MANDATORY — this is what separates amateur from agency-level):
- Hero section: Full-viewport height (min-h-screen), gradient overlay on background image, large bold headline (text-5xl md:text-7xl), glowing CTA button
- Cards: rounded-2xl, shadow-xl, hover:shadow-2xl hover:-translate-y-2 transition-all duration-300, backdrop-blur-sm bg-white/5 border border-white/10
- Buttons: bg-gradient-to-r, rounded-xl px-8 py-4 text-lg font-semibold, hover:scale-105 transition-transform, add subtle box-shadow glow
- Sections: py-20 md:py-32 padding, max-w-7xl mx-auto container, alternating background tones
- Colors: Use a cohesive palette with primary gradient (e.g., from-indigo-600 to-purple-600), dark background (#0f172a or #111827), light text
- Spacing: Generous whitespace, gap-8 between grid items, mb-16 between section title and content
- Footer: Multi-column grid with links, contact info, social icons (SVG), copyright
- Mobile menu: Hamburger icon with JS toggle, slide-in or fade-in animation

The page MUST look like it was designed by Pentagram or Fantasy Interactive.
Every section should have real, compelling content based on the user's details.
NEVER use placeholder data — if data is missing, use visible [PLACEHOLDER] markers.
"""
    return prompt


# ═══════════════════════════════════════════════════════════════════════════════
# ZIP ARCHIVE DELIVERY
# ═══════════════════════════════════════════════════════════════════════════════

# Patterns to always exclude from delivery archives
_DEFAULT_EXCLUDE_PATTERNS = [
    "node_modules",
    ".git",
    "__pycache__",
    ".DS_Store",
    "*.pyc",
    ".venv",
    "venv",
    ".deliveries",
    ".arcane",           # FIX audit#3: internal state must not leak
]

# Sensitive file patterns — checked with fnmatch against file names
_SENSITIVE_PATTERNS = [
    ".env",
    ".env.*",
    "*.pem",
    "*.key",
    "*.p12",
    "*.pfx",
    "*.jks",
    ".npmrc",
    ".pypirc",
    ".netrc",
    "id_rsa",
    "id_rsa.*",
    "id_ed25519",
    "id_ed25519.*",
    "*.secret",
    "secrets.json",
    "credentials.json",
    "service_account.json",
]


def _sanitize_project_name(name: str) -> str:
    """
    Sanitize project_name to prevent path traversal and invalid entries.
    Raises ValueError if the name is unsafe.
    """
    # Strip whitespace
    name = name.strip()
    if not name:
        raise ValueError("project_name must not be empty")

    # Reject absolute paths and traversal
    if os.path.isabs(name):
        raise ValueError(f"project_name must be relative, got: {name!r}")
    if ".." in name.split(os.sep):
        raise ValueError(f"project_name must not contain '..': {name!r}")
    if "/" in name or "\\" in name:
        raise ValueError(f"project_name must not contain path separators: {name!r}")

    # Must be a simple filename-like string
    # Allow alphanumerics, hyphens, underscores, dots (not leading dot)
    if name.startswith("."):
        raise ValueError(f"project_name must not start with '.': {name!r}")

    return name


def _is_excluded(file_name: str, dir_name: str, exclude: set[str]) -> bool:
    """Check if a file or directory should be excluded using fnmatch."""
    # Check directory-level exclusion
    if dir_name in exclude:
        return True
    for pat in exclude:
        if fnmatch.fnmatch(dir_name, pat):
            return True

    # Check file-level exclusion
    if file_name in exclude:
        return True
    for pat in exclude:
        if fnmatch.fnmatch(file_name, pat):
            return True

    # Check sensitive patterns
    for pat in _SENSITIVE_PATTERNS:
        if fnmatch.fnmatch(file_name, pat):
            return True

    return False


def create_delivery_archive(
    project_dir: str,
    project_name: str = "arcane-project",
    include_readme: bool = True,
    include_deploy_instructions: bool = True,
    exclude_patterns: Optional[list[str]] = None,
    max_size_mb: float = MAX_ARCHIVE_SIZE_MB,
) -> str:
    """
    Package project files into a downloadable ZIP archive.

    Args:
        project_dir: Path to the project directory
        project_name: Name for the archive (must be a simple name, no slashes)
        include_readme: Whether to generate a README.md
        include_deploy_instructions: Whether to include deployment guide
        exclude_patterns: File patterns to exclude (e.g., ['node_modules', '.git']).
                          Pass None for defaults; pass [] to disable defaults.
        max_size_mb: Maximum total uncompressed size in MB (default 500 MB)

    Returns:
        Path to the created ZIP file
    """
    if not os.path.isdir(project_dir):
        raise FileNotFoundError(f"Project directory not found: {project_dir}")

    # FIX audit#2: sanitize project_name
    project_name = _sanitize_project_name(project_name)

    # Bug #12 fix: validate project_dir is within allowed paths
    real_dir = os.path.realpath(project_dir)
    allowed = ["/root/workspace", "/tmp", "/home/arcane_sandbox"]
    path_valid = False
    for a in allowed:
        try:
            if os.path.commonpath([real_dir, a]) == a:
                path_valid = True
                break
        except ValueError:
            continue
    if not path_valid:
        raise PermissionError(
            f"Access denied: {project_dir} is outside allowed directories"
        )

    # FIX audit#8: None → defaults, [] → no defaults (allow override)
    if exclude_patterns is None:
        exclude = set(_DEFAULT_EXCLUDE_PATTERNS)
    else:
        exclude = set(exclude_patterns)

    # FIX audit#2: validate delivery_base after construction
    delivery_base = os.path.join("/root/workspace", project_name, ".deliveries")
    real_delivery = os.path.realpath(delivery_base)
    if not real_delivery.startswith("/root/workspace/"):
        raise PermissionError(
            f"Delivery path escaped workspace: {real_delivery}"
        )
    os.makedirs(delivery_base, exist_ok=True)

    archive_name = f"{project_name}_{uuid.uuid4().hex[:6]}"
    archive_path = os.path.join(delivery_base, f"{archive_name}.zip")

    total_bytes = 0
    max_bytes = int(max_size_mb * 1024 * 1024)

    with zipfile.ZipFile(archive_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for root, dirs, files in os.walk(project_dir):
            # Filter excluded directories (in-place)
            dirs[:] = [
                d for d in dirs
                if not _is_excluded("", d, exclude)
                and not os.path.islink(os.path.join(root, d))
            ]

            for file_name in files:
                filepath = os.path.join(root, file_name)
                parent_dir = os.path.basename(root)

                # FIX audit#4: skip symlinks
                if os.path.islink(filepath):
                    logger.debug("Skipping symlink: %s", filepath)
                    continue

                # FIX audit#8: fnmatch-based exclusion
                if _is_excluded(file_name, parent_dir, exclude):
                    continue

                # FIX audit#4: ensure real path is within project
                real_file = os.path.realpath(filepath)
                if not real_file.startswith(real_dir + os.sep) and real_file != real_dir:
                    logger.warning(
                        "Skipping file outside project: %s → %s",
                        filepath, real_file,
                    )
                    continue

                # FIX audit#10-zip: enforce size limit
                try:
                    fsize = os.path.getsize(filepath)
                except OSError:
                    continue
                total_bytes += fsize
                if total_bytes > max_bytes:
                    raise ValueError(
                        f"Archive would exceed {max_size_mb} MB limit "
                        f"(at {total_bytes / (1024*1024):.1f} MB). "
                        f"Reduce project size or increase max_size_mb."
                    )

                arcname = os.path.join(
                    project_name,
                    os.path.relpath(filepath, project_dir),
                )
                try:
                    zf.write(filepath, arcname)
                except Exception as e:
                    logger.warning("Skipping file %s: %s", filepath, e)

        if include_readme:
            readme = _generate_readme(project_name, project_dir)
            zf.writestr(f"{project_name}/README.md", readme)

        if include_deploy_instructions:
            deploy_guide = _generate_deploy_guide(project_name, project_dir)
            zf.writestr(f"{project_name}/DEPLOY.md", deploy_guide)

    size_mb = os.path.getsize(archive_path) / (1024 * 1024)
    logger.info("Created delivery archive: %s (%.1f MB)", archive_path, size_mb)

    return archive_path


def _generate_readme(project_name: str, project_dir: str) -> str:
    """Generate a README.md for the project archive."""
    files = os.listdir(project_dir) if os.path.isdir(project_dir) else []
    has_html = any(f.endswith(".html") for f in files)
    has_package_json = "package.json" in files
    has_requirements = "requirements.txt" in files
    has_docker = "Dockerfile" in files or "docker-compose.yml" in files

    readme = f"""# {project_name}

Generated by [ARCANE AI](https://arcaneai.ru) — Autonomous AI Agent System.

## Project Structure

"""
    for f in sorted(files)[:20]:
        if not f.startswith("."):
            readme += f"- `{f}`\n"

    readme += "\n## Quick Start\n\n"

    if has_html:
        readme += "Open `index.html` in your browser to view the project.\n\n"
    if has_package_json:
        readme += "```bash\nnpm install\nnpm run dev\n```\n\n"
    if has_requirements:
        readme += "```bash\npip install -r requirements.txt\npython app.py\n```\n\n"
    if has_docker:
        readme += "```bash\ndocker-compose up -d\n```\n\n"

    readme += """## License

This project was generated by ARCANE AI. You are free to use, modify,
and distribute it for any purpose.
"""
    return readme


def _generate_deploy_guide(project_name: str, project_dir: str) -> str:
    """Generate deployment instructions."""
    files = os.listdir(project_dir) if os.path.isdir(project_dir) else []
    has_html = any(f.endswith(".html") for f in files)
    has_package_json = "package.json" in files

    guide = f"""# Deployment Guide — {project_name}

## Option 1: Static Hosting (Simplest)

"""
    if has_html:
        guide += """Upload the files to any static hosting:
- **Vercel**: `npx vercel --prod`
- **Netlify**: Drag & drop the folder at netlify.com
- **GitHub Pages**: Push to a `gh-pages` branch
- **Nginx**: Copy files to `/var/www/html/`

"""

    if has_package_json:
        guide += """## Option 2: Node.js Hosting

```bash
npm install
npm run build
# Deploy the `dist/` or `build/` folder
```

"""

    guide += """## Option 3: VPS Deployment

```bash
# On your VPS:
scp -r ./* user@your-server:/var/www/your-domain/
sudo systemctl reload nginx
```

## Option 4: Docker

```bash
docker build -t your-project .
docker run -p 80:80 your-project
```
"""
    return guide
