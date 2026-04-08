"""
Tests for ARCANE Golden Paths — Promotion Criteria (spec §10.2)
+ archive security + concurrency + all audit-identified gaps.

Validates that a pattern is promoted to Golden Path ONLY when:
    1. 3+ successful runs
    2. Tests passed on every successful run
    3. Zero rollbacks across all runs (including failed)
    4. (optional) Human approval
"""

from __future__ import annotations

import concurrent.futures
import json
import os
import sys
import tempfile
import uuid
import zipfile

import pytest

_arcane_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _arcane_root not in sys.path:
    sys.path.insert(0, _arcane_root)

from core.golden_paths import (
    GoldenPathStore,
    RunOutcome,
    OutcomeVerdict,
    compute_pattern_signature,
    record_run_outcome,
    find_golden_path,
    find_similar_golden_paths,
    approve_golden_path,
    list_golden_paths,
    MIN_SUCCESSES_FOR_PROMOTION,
    MAX_OUTCOMES_PER_CANDIDATE,
    # Template / archive API
    get_template,
    list_templates,
    generate_template_prompt,
    create_delivery_archive,
    _sanitize_project_name,
    _is_excluded,
)


# ═══════════════════════════════════════════════════════════════════════════════
# FIXTURES
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.fixture
def tmp_project(tmp_path):
    """Create a temporary project directory."""
    project_dir = tmp_path / "test_project"
    project_dir.mkdir()
    return str(project_dir)


@pytest.fixture
def store(tmp_project):
    """Fresh GoldenPathStore for each test."""
    return GoldenPathStore(tmp_project)


def _make_outcome(
    sig: str = "abc123",
    *,
    success: bool = True,
    tests_passed: bool = True,
    rollback: bool = False,
    run_id: str | None = None,
    duration_ms: int = 5000,
    cost_usd: float = 0.20,
) -> RunOutcome:
    return RunOutcome(
        run_id=run_id or uuid.uuid4().hex[:8],
        pattern_signature=sig,
        verdict=OutcomeVerdict.SUCCESS if success else OutcomeVerdict.FAILED,
        tests_passed=tests_passed,
        rollback_triggered=rollback,
        duration_ms=duration_ms,
        cost_usd=cost_usd,
        model_used="sonnet-4.6",
    )


def _candidate_info(
    label: str = "Landing page",
    task_type: str = "landing_page",
    steps: list[str] | None = None,
    requires_human_approval: bool = False,
) -> dict:
    return {
        "pattern_label": label,
        "task_type": task_type,
        "steps_summary": steps or ["scaffold", "code", "qa", "deploy"],
        "requires_human_approval": requires_human_approval,
    }


# ═══════════════════════════════════════════════════════════════════════════════
# 1. PATTERN SIGNATURE
# ═══════════════════════════════════════════════════════════════════════════════

class TestPatternSignature:

    def test_deterministic(self):
        s1 = compute_pattern_signature("landing", ["scaffold", "code", "deploy"])
        s2 = compute_pattern_signature("landing", ["scaffold", "code", "deploy"])
        assert s1 == s2

    def test_case_insensitive(self):
        s1 = compute_pattern_signature("Landing", ["Scaffold", "CODE", "Deploy"])
        s2 = compute_pattern_signature("landing", ["scaffold", "code", "deploy"])
        assert s1 == s2

    def test_strips_whitespace(self):
        s1 = compute_pattern_signature("  landing  ", ["  scaffold ", " code"])
        s2 = compute_pattern_signature("landing", ["scaffold", "code"])
        assert s1 == s2

    def test_different_steps_different_sig(self):
        s1 = compute_pattern_signature("landing", ["scaffold", "code"])
        s2 = compute_pattern_signature("landing", ["scaffold", "code", "deploy"])
        assert s1 != s2

    def test_different_type_different_sig(self):
        s1 = compute_pattern_signature("landing", ["scaffold", "code"])
        s2 = compute_pattern_signature("api", ["scaffold", "code"])
        assert s1 != s2

    def test_empty_steps_filtered(self):
        s1 = compute_pattern_signature("landing", ["scaffold", "", "code", "  "])
        s2 = compute_pattern_signature("landing", ["scaffold", "code"])
        assert s1 == s2

    def test_returns_hex_string(self):
        sig = compute_pattern_signature("x", ["y"])
        assert len(sig) == 16
        assert all(c in "0123456789abcdef" for c in sig)


# ═══════════════════════════════════════════════════════════════════════════════
# 2. PROMOTION CRITERIA — CORE LOGIC
# ═══════════════════════════════════════════════════════════════════════════════

class TestPromotionCriteria:

    def test_not_promoted_after_1_success(self, store):
        r = store.record_outcome(_make_outcome("s1"), _candidate_info())
        assert r["promoted"] is False
        assert "need 3" in r["reason"]

    def test_not_promoted_after_2_successes(self, store):
        for _ in range(2):
            r = store.record_outcome(_make_outcome("s1"), _candidate_info())
        assert r["promoted"] is False

    def test_promoted_after_3_successes(self, store):
        for _ in range(3):
            r = store.record_outcome(_make_outcome("s1"), _candidate_info())
        assert r["promoted"] is True
        assert r["reason"] == "all_criteria_met"

    def test_promoted_after_5_successes(self, store):
        for _ in range(5):
            r = store.record_outcome(_make_outcome("s1"), _candidate_info())
        assert r["promoted"] is True

    def test_not_promoted_if_tests_failed(self, store):
        store.record_outcome(_make_outcome("s1", tests_passed=True), _candidate_info())
        store.record_outcome(_make_outcome("s1", tests_passed=False), _candidate_info())
        r = store.record_outcome(_make_outcome("s1", tests_passed=True), _candidate_info())
        assert r["promoted"] is False
        assert "tests not passed" in r["reason"]

    def test_not_promoted_if_rollback(self, store):
        store.record_outcome(_make_outcome("s1"), _candidate_info())
        store.record_outcome(_make_outcome("s1", rollback=True), _candidate_info())
        r = store.record_outcome(_make_outcome("s1"), _candidate_info())
        assert r["promoted"] is False
        assert "rollback" in r["reason"]

    def test_failed_runs_dont_count_as_success(self, store):
        for _ in range(10):
            store.record_outcome(
                _make_outcome("s1", success=False, tests_passed=False),
                _candidate_info(),
            )
        for _ in range(3):
            r = store.record_outcome(_make_outcome("s1"), _candidate_info())
        assert r["promoted"] is True

    def test_failed_run_with_rollback_blocks_promotion(self, store):
        store.record_outcome(
            _make_outcome("s1", success=False, rollback=True),
            _candidate_info(),
        )
        for _ in range(3):
            r = store.record_outcome(_make_outcome("s1"), _candidate_info())
        assert r["promoted"] is False
        assert "rollback" in r["reason"]

    def test_already_promoted_stays_promoted(self, store):
        for _ in range(3):
            store.record_outcome(_make_outcome("s1"), _candidate_info())
        r = store.record_outcome(
            _make_outcome("s1", success=False, rollback=True),
            _candidate_info(),
        )
        assert r["promoted"] is True
        assert r["reason"] == "already_promoted"


# ═══════════════════════════════════════════════════════════════════════════════
# 3. HUMAN APPROVAL GATE
# ═══════════════════════════════════════════════════════════════════════════════

class TestHumanApproval:

    def test_not_promoted_without_approval(self, store):
        info = _candidate_info(requires_human_approval=True)
        for _ in range(3):
            r = store.record_outcome(_make_outcome("s1"), info)
        assert r["promoted"] is False
        assert r["reason"] == "waiting_for_human_approval"

    def test_promoted_after_approval(self, store):
        info = _candidate_info(requires_human_approval=True)
        for _ in range(3):
            store.record_outcome(_make_outcome("s1"), info)
        promoted = store.approve_candidate("s1", approved_by="admin")
        assert promoted is True
        cand = store.get_candidate("s1")
        assert cand["promoted"] is True
        assert cand["human_approved_by"] == "admin"

    def test_approve_nonexistent_returns_false(self, store):
        assert store.approve_candidate("nonexistent") is False

    def test_approval_before_3_successes_no_promotion(self, store):
        info = _candidate_info(requires_human_approval=True)
        store.record_outcome(_make_outcome("s1"), info)
        assert store.approve_candidate("s1", approved_by="admin") is False

    def test_requires_human_approval_escalation(self, store):
        """FIX audit#6: later calls with requires_human_approval=True
        must escalate even if first call was False."""
        info_no = _candidate_info(requires_human_approval=False)
        store.record_outcome(_make_outcome("s1"), info_no)
        store.record_outcome(_make_outcome("s1"), info_no)

        info_yes = _candidate_info(requires_human_approval=True)
        r = store.record_outcome(_make_outcome("s1"), info_yes)
        # Should be blocked — escalated to requiring approval
        assert r["promoted"] is False
        assert r["reason"] == "waiting_for_human_approval"


# ═══════════════════════════════════════════════════════════════════════════════
# 4. STORE PERSISTENCE
# ═══════════════════════════════════════════════════════════════════════════════

class TestStorePersistence:

    def test_data_persists_across_instances(self, tmp_project):
        s1 = GoldenPathStore(tmp_project)
        s1.record_outcome(_make_outcome("s1"), _candidate_info())
        s2 = GoldenPathStore(tmp_project)
        cand = s2.get_candidate("s1")
        assert cand is not None
        assert cand["total_runs"] == 1

    def test_corrupted_store_resets(self, tmp_project):
        store_path = os.path.join(tmp_project, ".arcane", "golden_paths.json")
        os.makedirs(os.path.dirname(store_path), exist_ok=True)
        with open(store_path, "w") as f:
            f.write("{invalid json!!!")
        store = GoldenPathStore(tmp_project)
        r = store.record_outcome(_make_outcome("s1"), _candidate_info())
        assert r["promoted"] is False
        assert store.get_candidate("s1") is not None

    def test_store_file_created_on_first_write(self, tmp_project):
        store_path = os.path.join(tmp_project, ".arcane", "golden_paths.json")
        assert not os.path.exists(store_path)
        store = GoldenPathStore(tmp_project)
        store.record_outcome(_make_outcome("s1"), _candidate_info())
        assert os.path.exists(store_path)
        with open(store_path) as f:
            data = json.load(f)
        assert "s1" in data["candidates"]

    def test_promoted_list_persisted(self, tmp_project):
        store = GoldenPathStore(tmp_project)
        for _ in range(3):
            store.record_outcome(_make_outcome("s1"), _candidate_info())
        store2 = GoldenPathStore(tmp_project)
        promoted = store2.list_promoted()
        assert len(promoted) == 1
        assert promoted[0]["pattern_signature"] == "s1"


# ═══════════════════════════════════════════════════════════════════════════════
# 5. RUN_ID DEDUPLICATION (audit #5)
# ═══════════════════════════════════════════════════════════════════════════════

class TestRunIdDeduplication:

    def test_duplicate_run_id_rejected(self, store):
        """Same run_id recorded twice must not double-count."""
        outcome = _make_outcome("s1", run_id="RUN-001")
        r1 = store.record_outcome(outcome, _candidate_info())
        r2 = store.record_outcome(outcome, _candidate_info())
        assert r2["reason"] == "duplicate_run_id"
        cand = store.get_candidate("s1")
        assert cand["total_runs"] == 1
        assert len(cand["outcomes"]) == 1

    def test_three_copies_of_same_run_dont_promote(self, store):
        """Sending the same run_id 3 times must NOT promote."""
        outcome = _make_outcome("s1", run_id="RUN-SAME")
        for _ in range(3):
            r = store.record_outcome(outcome, _candidate_info())
        assert r["promoted"] is False
        cand = store.get_candidate("s1")
        assert cand["success_count"] == 1  # Only the first counted


# ═══════════════════════════════════════════════════════════════════════════════
# 6. MUTABLE RETURN PROTECTION (audit #7)
# ═══════════════════════════════════════════════════════════════════════════════

class TestMutableReturnProtection:

    def test_get_candidate_returns_copy(self, store):
        store.record_outcome(_make_outcome("s1"), _candidate_info())
        cand = store.get_candidate("s1")
        cand["total_runs"] = 999
        fresh = store.get_candidate("s1")
        assert fresh["total_runs"] == 1  # not mutated

    def test_list_promoted_returns_copies(self, store):
        for _ in range(3):
            store.record_outcome(_make_outcome("s1"), _candidate_info())
        promoted = store.list_promoted()
        promoted[0]["promoted"] = False
        fresh = store.list_promoted()
        assert fresh[0]["promoted"] is True

    def test_get_template_returns_copy(self):
        t = get_template("dark_luxury")
        t["name"] = "CORRUPTED"
        fresh = get_template("dark_luxury")
        assert fresh["name"] == "Dark Luxury"


# ═══════════════════════════════════════════════════════════════════════════════
# 7. OUTCOMES CAP (audit #9)
# ═══════════════════════════════════════════════════════════════════════════════

class TestOutcomesCap:

    def test_outcomes_trimmed_at_max(self, store):
        """Outcomes list must not exceed MAX_OUTCOMES_PER_CANDIDATE."""
        for i in range(MAX_OUTCOMES_PER_CANDIDATE + 20):
            store.record_outcome(_make_outcome("s1"), _candidate_info())
        cand = store.get_candidate("s1")
        assert len(cand["outcomes"]) <= MAX_OUTCOMES_PER_CANDIDATE

    def test_oldest_outcomes_trimmed(self, store):
        """When trimmed, the most recent outcomes are kept."""
        for i in range(MAX_OUTCOMES_PER_CANDIDATE + 5):
            store.record_outcome(
                _make_outcome("s1", run_id=f"run-{i:04d}"),
                _candidate_info(),
            )
        cand = store.get_candidate("s1")
        run_ids = [o["run_id"] for o in cand["outcomes"]]
        # Oldest runs should have been trimmed
        assert "run-0000" not in run_ids
        assert f"run-{MAX_OUTCOMES_PER_CANDIDATE + 4:04d}" in run_ids


# ═══════════════════════════════════════════════════════════════════════════════
# 8. TESTS_PASSED_COUNT ACCURACY (audit #10)
# ═══════════════════════════════════════════════════════════════════════════════

class TestTestsPassedCount:

    def test_tests_passed_only_on_success(self, store):
        """tests_passed_count should only count successful runs with tests_passed."""
        # Failed run with tests_passed=True — should NOT count
        store.record_outcome(
            _make_outcome("s1", success=False, tests_passed=True),
            _candidate_info(),
        )
        # Successful run with tests_passed=True — should count
        store.record_outcome(
            _make_outcome("s1", success=True, tests_passed=True),
            _candidate_info(),
        )
        cand = store.get_candidate("s1")
        assert cand["tests_passed_count"] == 1  # not 2


# ═══════════════════════════════════════════════════════════════════════════════
# 9. QUERY & MATCH
# ═══════════════════════════════════════════════════════════════════════════════

class TestQueryAndMatch:

    def test_find_matching_path_exact(self, store):
        sig = compute_pattern_signature("landing", ["scaffold", "code", "deploy"])
        for _ in range(3):
            store.record_outcome(
                _make_outcome(sig),
                _candidate_info(task_type="landing", steps=["scaffold", "code", "deploy"]),
            )
        result = store.find_matching_path("landing", ["scaffold", "code", "deploy"])
        assert result is not None
        assert result["promoted"] is True

    def test_find_matching_path_not_promoted(self, store):
        sig = compute_pattern_signature("landing", ["scaffold", "code"])
        store.record_outcome(
            _make_outcome(sig),
            _candidate_info(task_type="landing", steps=["scaffold", "code"]),
        )
        assert store.find_matching_path("landing", ["scaffold", "code"]) is None

    def test_find_similar_by_task_type(self, store):
        for steps in [["a", "b", "c"], ["x", "y", "z"]]:
            sig = compute_pattern_signature("landing", steps)
            for _ in range(3):
                store.record_outcome(
                    _make_outcome(sig),
                    _candidate_info(task_type="landing", steps=steps),
                )
        similar = store.find_similar_paths("landing", promoted_only=True)
        assert len(similar) == 2

    def test_end_to_end_with_real_signatures(self, tmp_project):
        """Integration test: record_run_outcome + find_golden_path using
        real computed signatures, not hardcoded 's1'."""
        steps = ["scaffold", "search", "code", "qa", "deploy"]
        for _ in range(3):
            record_run_outcome(
                tmp_project,
                run_id=uuid.uuid4().hex[:8],
                task_type="landing_page",
                steps=steps,
                pattern_label="Landing page (HTML)",
                success=True,
                tests_passed=True,
                rollback_triggered=False,
            )
        gp = find_golden_path(tmp_project, "landing_page", steps)
        assert gp is not None
        assert gp["promoted"] is True
        assert gp["pattern_label"] == "Landing page (HTML)"


# ═══════════════════════════════════════════════════════════════════════════════
# 10. CONCURRENT WRITES (audit #3)
# ═══════════════════════════════════════════════════════════════════════════════

class TestConcurrentWrites:

    def test_parallel_records_no_data_loss(self, tmp_project):
        """Multiple threads writing simultaneously must not lose records."""
        n_threads = 8

        def _record(i):
            return record_run_outcome(
                tmp_project,
                run_id=f"thread-{i}",
                task_type="concurrent_test",
                steps=["a"],
                success=True,
                tests_passed=True,
                rollback_triggered=False,
            )

        with concurrent.futures.ThreadPoolExecutor(max_workers=n_threads) as ex:
            futures = [ex.submit(_record, i) for i in range(n_threads)]
            results = [f.result() for f in futures]

        store = GoldenPathStore(tmp_project)
        cand = store.list_candidates()
        sig = compute_pattern_signature("concurrent_test", ["a"])
        matching = [c for c in cand if c["pattern_signature"] == sig]
        assert len(matching) == 1
        assert matching[0]["total_runs"] == n_threads
        assert len(matching[0]["outcomes"]) == n_threads


# ═══════════════════════════════════════════════════════════════════════════════
# 11. GENERATE_TEMPLATE_PROMPT (audit #1)
# ═══════════════════════════════════════════════════════════════════════════════

class TestGenerateTemplatePrompt:

    def test_returns_nonempty_for_valid_template(self):
        """Must not raise KeyError — all required keys present."""
        prompt = generate_template_prompt("dark_luxury", {"name": "Test Biz"})
        assert len(prompt) > 200
        assert "Dark Luxury" in prompt
        assert "Test Biz" in prompt

    def test_returns_empty_for_unknown_template(self):
        assert generate_template_prompt("nonexistent", {}) == ""

    def test_all_templates_produce_valid_prompts(self):
        """Every template in the catalog must generate a prompt without error."""
        for tpl in list_templates():
            prompt = generate_template_prompt(tpl["type"], {"brand": "Acme"})
            assert len(prompt) > 100, f"Template {tpl['type']} produced empty prompt"
            assert "Acme" in prompt

    def test_prompt_contains_color_scheme(self):
        prompt = generate_template_prompt("clean_tech", {})
        assert "#4f46e5" in prompt  # primary color

    def test_prompt_contains_sections(self):
        prompt = generate_template_prompt("bold_energy", {})
        assert "Programs" in prompt or "Trainers" in prompt

    def test_template_has_all_required_keys(self):
        """Every template must have style, color_scheme, sections."""
        for key, tpl in __import__(
            "core.golden_paths", fromlist=["LANDING_PAGE_TEMPLATES"]
        ).LANDING_PAGE_TEMPLATES.items():
            assert "style" in tpl, f"{key} missing 'style'"
            assert "color_scheme" in tpl, f"{key} missing 'color_scheme'"
            assert "sections" in tpl, f"{key} missing 'sections'"
            cs = tpl["color_scheme"]
            for field in ("primary", "secondary", "accent", "background", "text"):
                assert field in cs, f"{key} color_scheme missing '{field}'"


# ═══════════════════════════════════════════════════════════════════════════════
# 12. CREATE_DELIVERY_ARCHIVE — SECURITY (audit #2, #3, #4)
# ═══════════════════════════════════════════════════════════════════════════════

class TestDeliveryArchiveSecurity:

    def test_sanitize_rejects_absolute_path(self):
        with pytest.raises(ValueError, match="relative"):
            _sanitize_project_name("/tmp/evil")

    def test_sanitize_rejects_traversal(self):
        with pytest.raises(ValueError, match="\\.\\."):
            _sanitize_project_name("../../etc")

    def test_sanitize_rejects_slashes(self):
        with pytest.raises(ValueError, match="separator"):
            _sanitize_project_name("a/b")

    def test_sanitize_rejects_leading_dot(self):
        with pytest.raises(ValueError, match="start with '.'"):
            _sanitize_project_name(".hidden")

    def test_sanitize_rejects_empty(self):
        with pytest.raises(ValueError, match="empty"):
            _sanitize_project_name("")

    def test_sanitize_accepts_valid_name(self):
        assert _sanitize_project_name("my-project_v2") == "my-project_v2"

    def test_symlink_not_included_in_archive(self, tmp_path):
        """Symlinks to files outside the project must be skipped."""
        project = tmp_path / "proj"
        project.mkdir()
        (project / "legit.txt").write_text("hello")

        # Create a file outside the project and symlink to it
        secret = tmp_path / "secret.txt"
        secret.write_text("TOP SECRET DATA")
        (project / "sneaky_link").symlink_to(secret)

        # We need to be under allowed paths for create_delivery_archive
        # Since /tmp is allowed, and tmp_path is under /tmp, this works.
        archive = create_delivery_archive(
            str(project),
            project_name="safe-test",
            include_readme=False,
            include_deploy_instructions=False,
        )

        with zipfile.ZipFile(archive) as zf:
            names = zf.namelist()
            assert any("legit.txt" in n for n in names)
            assert not any("sneaky" in n for n in names)
            # Also verify content doesn't contain the secret
            for name in names:
                content = zf.read(name).decode("utf-8", errors="ignore")
                assert "TOP SECRET DATA" not in content

    def test_env_production_excluded(self, tmp_path):
        """Files like .env.production must be excluded."""
        project = tmp_path / "proj"
        project.mkdir()
        (project / "index.html").write_text("<html></html>")
        (project / ".env").write_text("SECRET=1")
        (project / ".env.production").write_text("PROD_SECRET=2")
        (project / ".env.local").write_text("LOCAL_SECRET=3")

        archive = create_delivery_archive(
            str(project),
            project_name="env-test",
            include_readme=False,
            include_deploy_instructions=False,
        )
        with zipfile.ZipFile(archive) as zf:
            names = zf.namelist()
            assert any("index.html" in n for n in names)
            assert not any(".env" in n for n in names), f"Sensitive files in archive: {names}"

    def test_arcane_dir_excluded(self, tmp_path):
        """The .arcane/ directory must never be in the archive."""
        project = tmp_path / "proj"
        project.mkdir()
        (project / "index.html").write_text("<html></html>")
        arcane_dir = project / ".arcane"
        arcane_dir.mkdir()
        (arcane_dir / "state.json").write_text('{"secrets": true}')

        archive = create_delivery_archive(
            str(project),
            project_name="arcane-excl-test",
            include_readme=False,
            include_deploy_instructions=False,
        )
        with zipfile.ZipFile(archive) as zf:
            names = zf.namelist()
            assert not any(".arcane" in n for n in names)

    def test_credential_files_excluded(self, tmp_path):
        """Private keys and credential files must be excluded."""
        project = tmp_path / "proj"
        project.mkdir()
        (project / "app.py").write_text("print('ok')")
        for name in ["id_rsa", "server.pem", "cert.key", ".npmrc", ".pypirc"]:
            (project / name).write_text("sensitive")

        archive = create_delivery_archive(
            str(project),
            project_name="cred-test",
            include_readme=False,
            include_deploy_instructions=False,
        )
        with zipfile.ZipFile(archive) as zf:
            names = zf.namelist()
            for sensitive in ["id_rsa", "server.pem", "cert.key", ".npmrc", ".pypirc"]:
                assert not any(sensitive in n for n in names), \
                    f"{sensitive} found in archive: {names}"


class TestDeliveryArchiveFunctionality:

    def test_happy_path(self, tmp_path):
        project = tmp_path / "proj"
        project.mkdir()
        (project / "index.html").write_text("<html>Hello</html>")

        archive = create_delivery_archive(
            str(project),
            project_name="happy-test",
            include_readme=True,
            include_deploy_instructions=True,
        )
        assert os.path.exists(archive)
        with zipfile.ZipFile(archive) as zf:
            names = zf.namelist()
            assert any("index.html" in n for n in names)
            assert any("README.md" in n for n in names)
            assert any("DEPLOY.md" in n for n in names)

    def test_empty_exclude_disables_defaults(self, tmp_path):
        """Passing exclude_patterns=[] should disable default exclusions."""
        project = tmp_path / "proj"
        project.mkdir()
        pycache = project / "__pycache__"
        pycache.mkdir()
        (pycache / "mod.cpython-312.pyc").write_bytes(b"bytecode")
        (project / "app.py").write_text("pass")

        archive = create_delivery_archive(
            str(project),
            project_name="no-excl-test",
            exclude_patterns=[],
            include_readme=False,
            include_deploy_instructions=False,
        )
        with zipfile.ZipFile(archive) as zf:
            names = zf.namelist()
            # __pycache__ should be present since we disabled defaults
            # But .env* still excluded via _SENSITIVE_PATTERNS
            assert any("__pycache__" in n for n in names)

    def test_project_not_found_raises(self):
        with pytest.raises(FileNotFoundError):
            create_delivery_archive("/nonexistent/path")

    def test_max_size_enforced(self, tmp_path):
        project = tmp_path / "proj"
        project.mkdir()
        # Create a 2 MB file
        (project / "big.bin").write_bytes(b"x" * (2 * 1024 * 1024))

        with pytest.raises(ValueError, match="exceed"):
            create_delivery_archive(
                str(project),
                project_name="size-test",
                max_size_mb=1.0,
                include_readme=False,
                include_deploy_instructions=False,
            )


# ═══════════════════════════════════════════════════════════════════════════════
# 13. IS_EXCLUDED HELPER
# ═══════════════════════════════════════════════════════════════════════════════

class TestIsExcluded:

    def test_exact_file_match(self):
        assert _is_excluded(".DS_Store", "src", {".DS_Store"}) is True

    def test_glob_pattern(self):
        assert _is_excluded("module.pyc", "src", {"*.pyc"}) is True

    def test_env_variants(self):
        """All .env variants must be caught by _SENSITIVE_PATTERNS."""
        assert _is_excluded(".env", "root", set()) is True
        assert _is_excluded(".env.production", "root", set()) is True
        assert _is_excluded(".env.local", "root", set()) is True

    def test_normal_file_not_excluded(self):
        assert _is_excluded("index.html", "src", set()) is False

    def test_dir_exclusion(self):
        assert _is_excluded("", "node_modules", {"node_modules"}) is True
        assert _is_excluded("", ".git", {".git"}) is True


# ═══════════════════════════════════════════════════════════════════════════════
# 14. AGGREGATE STATS
# ═══════════════════════════════════════════════════════════════════════════════

class TestAggregateStats:

    def test_avg_duration_and_cost(self, store):
        store.record_outcome(
            _make_outcome("s1", duration_ms=1000, cost_usd=0.10),
            _candidate_info(),
        )
        store.record_outcome(
            _make_outcome("s1", duration_ms=3000, cost_usd=0.30),
            _candidate_info(),
        )
        cand = store.get_candidate("s1")
        assert cand["avg_duration_ms"] == 2000
        assert cand["avg_cost_usd"] == pytest.approx(0.20, abs=0.01)

    def test_total_runs_count(self, store):
        for _ in range(5):
            store.record_outcome(_make_outcome("s1"), _candidate_info())
        cand = store.get_candidate("s1")
        assert cand["total_runs"] == 5
        assert cand["success_count"] == 5
        assert cand["rollback_count"] == 0


# ═══════════════════════════════════════════════════════════════════════════════
# 15. CONVENIENCE HELPERS
# ═══════════════════════════════════════════════════════════════════════════════

class TestConvenienceHelpers:

    def test_record_run_outcome_promotes(self, tmp_project):
        for _ in range(3):
            r = record_run_outcome(
                tmp_project,
                run_id=uuid.uuid4().hex[:8],
                task_type="landing_page",
                steps=["scaffold", "code", "qa", "deploy"],
                pattern_label="Landing (HTML)",
                success=True,
                tests_passed=True,
                rollback_triggered=False,
            )
        assert r["promoted"] is True

    def test_list_golden_paths_helper(self, tmp_project):
        for _ in range(3):
            record_run_outcome(
                tmp_project,
                run_id=uuid.uuid4().hex[:8],
                task_type="landing",
                steps=["a"],
                success=True,
                tests_passed=True,
                rollback_triggered=False,
            )
        paths = list_golden_paths(tmp_project)
        assert len(paths) == 1

    def test_find_similar_golden_paths_helper(self, tmp_project):
        for steps in [["a", "b"], ["x", "y"]]:
            for _ in range(3):
                record_run_outcome(
                    tmp_project,
                    run_id=uuid.uuid4().hex[:8],
                    task_type="landing",
                    steps=steps,
                    success=True,
                    tests_passed=True,
                    rollback_triggered=False,
                )
        similar = find_similar_golden_paths(tmp_project, "landing")
        assert len(similar) == 2


# ═══════════════════════════════════════════════════════════════════════════════
# 16. LEGACY API BACKWARD COMPATIBILITY
# ═══════════════════════════════════════════════════════════════════════════════

class TestLegacyAPI:

    def test_get_template_returns_dict(self):
        t = get_template("dark_luxury")
        assert t is not None
        assert t["name"] == "Dark Luxury"

    def test_get_template_unknown_returns_none(self):
        assert get_template("nonexistent_theme") is None

    def test_list_templates_returns_all(self):
        templates = list_templates()
        assert len(templates) == 7
        names = {t["type"] for t in templates}
        assert "dark_luxury" in names
        assert "clean_tech" in names

    def test_list_templates_structure(self):
        for t in list_templates():
            assert "type" in t
            assert "name" in t
            assert "description" in t


# ═══════════════════════════════════════════════════════════════════════════════
# 17. EDGE CASES
# ═══════════════════════════════════════════════════════════════════════════════

class TestEdgeCases:

    def test_multiple_patterns_independent(self, store):
        for _ in range(3):
            store.record_outcome(_make_outcome("s1"), _candidate_info(label="A"))
        for _ in range(2):
            store.record_outcome(_make_outcome("s2"), _candidate_info(label="B"))
        assert store.get_candidate("s1")["promoted"] is True
        assert store.get_candidate("s2")["promoted"] is False

    def test_promoted_at_timestamp_set(self, store):
        for _ in range(3):
            store.record_outcome(_make_outcome("s1"), _candidate_info())
        cand = store.get_candidate("s1")
        assert cand["promoted_at"] is not None
        assert "T" in cand["promoted_at"]
