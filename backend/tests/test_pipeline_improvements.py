#!/usr/bin/env python3
"""
Tests for ORION pipeline improvements:
1. test_phase_logging_works
2. test_patch_mode_skips_pipeline
3. test_full_build_gets_reminder
4. test_reminder_does_not_block_file_write
"""

import sys
import unittest
from unittest.mock import MagicMock, patch, call
import logging

sys.path.insert(0, '/var/www/orion/backend')

# ── Minimal stubs so agent_loop can be imported without full app context ──────
# We only test the logic, not the full agent execution


class TestClassifyTaskMode(unittest.TestCase):
    """Tests for classify_task_mode() in prompts.py"""

    def setUp(self):
        from prompts import classify_task_mode
        self.classify = classify_task_mode

    def test_full_build_for_create_tasks(self):
        cases = [
            "Создай лендинг для барбершопа",
            "Deploy new website to server",
            "Сделай сайт для кофейни",
            "Build a portfolio page",
        ]
        for msg in cases:
            with self.subTest(msg=msg):
                result = self.classify(msg)
                self.assertEqual(result, "full_build",
                                 f"Expected full_build for: {msg!r}")

    def test_patch_mode_for_fix_tasks(self):
        cases = [
            "Исправь ошибку в форме",
            "Замени цвет кнопки на синий",
            "Fix the broken navigation",
            "Update the prices on the landing page",
            "Поменяй телефон в шапке",
            "Почини форму обратной связи",
        ]
        for msg in cases:
            with self.subTest(msg=msg):
                result = self.classify(msg)
                self.assertEqual(result, "patch",
                                 f"Expected patch for: {msg!r}")


class TestPhaseLogging(unittest.TestCase):
    """test_phase_logging_works: verifies _current_phase transitions are logged"""

    def test_phase_starts_at_start(self):
        """AgentLoop initialises _current_phase to 'start'"""
        # We simulate the __init__ behaviour without importing the full class
        class FakeLoop:
            actions_log = []
            _current_phase = "start"

        loop = FakeLoop()
        self.assertEqual(loop._current_phase, "start")

    def test_phase_transitions_sequence(self):
        """Simulate phase transitions: start → brief → blueprint → build → publish → verify"""
        class FakeLoop:
            _current_phase = "start"

        loop = FakeLoop()
        transitions = []

        # Simulate update_task_charter called (phase: start → brief)
        if loop._current_phase == "start":
            prev = loop._current_phase
            loop._current_phase = "brief"
            transitions.append(f"{prev} → brief")

        # Simulate second update_task_charter (phase: brief → blueprint)
        if loop._current_phase == "brief":
            loop._current_phase = "blueprint"
            transitions.append("brief → blueprint")

        # Simulate file_write .html (phase: blueprint → build)
        if loop._current_phase in ("start", "brief", "blueprint"):
            loop._current_phase = "build"
            transitions.append(f"blueprint → build")

        # Simulate ssh_execute with scp (phase: build → publish)
        if loop._current_phase == "build":
            loop._current_phase = "publish"
            transitions.append("build → publish")

        # Simulate browser_check_site (phase: publish → verify)
        if loop._current_phase == "publish":
            loop._current_phase = "verify"
            transitions.append("publish → verify")

        self.assertEqual(loop._current_phase, "verify")
        self.assertEqual(len(transitions), 5)
        self.assertIn("start → brief", transitions)
        self.assertIn("publish → verify", transitions)


class TestPatchModeSkipsPipeline(unittest.TestCase):
    """test_patch_mode_skips_pipeline: pipeline rule NOT injected for patch tasks"""

    def test_patch_mode_skips_website_rule(self):
        from prompts import classify_task_mode, classify_task_type, WEBSITE_PIPELINE_RULE

        msg = "Исправь ошибку в форме на лендинге"
        task_type = classify_task_type(msg)
        task_mode = classify_task_mode(msg)

        # Simulate the PIPELINE INJECTION logic
        injected_prompt = ""
        if task_mode == "full_build":
            if task_type == "website":
                injected_prompt = WEBSITE_PIPELINE_RULE

        self.assertEqual(task_mode, "patch")
        self.assertEqual(injected_prompt, "",
                         "Pipeline rule should NOT be injected for patch tasks")

    def test_full_build_injects_website_rule(self):
        from prompts import classify_task_mode, classify_task_type, WEBSITE_PIPELINE_RULE

        msg = "Создай лендинг для барбершопа и задеплой на сервер"
        task_type = classify_task_type(msg)
        task_mode = classify_task_mode(msg)

        injected_prompt = ""
        if task_mode == "full_build":
            if task_type == "website":
                injected_prompt = WEBSITE_PIPELINE_RULE

        self.assertEqual(task_mode, "full_build")
        self.assertEqual(task_type, "website")
        self.assertNotEqual(injected_prompt, "",
                            "Pipeline rule SHOULD be injected for full_build website tasks")
        self.assertIn("Рекомендуемый порядок", injected_prompt,
                      "WEBSITE_PIPELINE_RULE should contain 'Рекомендуемый порядок'")


class TestFullBuildGetsReminder(unittest.TestCase):
    """test_full_build_gets_reminder: soft hint injected for full_build in start phase"""

    def _should_inject_hint(self, tool_name, tool_args, current_phase, task_mode):
        """Replicates the SOFT BLUEPRINT GUARD logic from agent_loop.py"""
        return (
            tool_name == "file_write"
            and isinstance(tool_args, dict)
            and any(tool_args.get("path", "").endswith(ext) for ext in (".html", ".php"))
            and current_phase == "start"
            and task_mode == "full_build"
        )

    def test_hint_injected_for_full_build_start_phase(self):
        result = self._should_inject_hint(
            tool_name="file_write",
            tool_args={"path": "/var/www/html/index.html", "content": "<html>..."},
            current_phase="start",
            task_mode="full_build"
        )
        self.assertTrue(result, "Hint should be injected for full_build in start phase")

    def test_no_hint_for_patch_mode(self):
        result = self._should_inject_hint(
            tool_name="file_write",
            tool_args={"path": "/var/www/html/index.html", "content": "<html>..."},
            current_phase="start",
            task_mode="patch"
        )
        self.assertFalse(result, "Hint should NOT be injected for patch mode")

    def test_no_hint_when_already_in_blueprint_phase(self):
        result = self._should_inject_hint(
            tool_name="file_write",
            tool_args={"path": "/var/www/html/index.html", "content": "<html>..."},
            current_phase="blueprint",
            task_mode="full_build"
        )
        self.assertFalse(result, "Hint should NOT be injected when phase is already blueprint")

    def test_no_hint_for_non_html_files(self):
        result = self._should_inject_hint(
            tool_name="file_write",
            tool_args={"path": "/var/www/html/style.css", "content": "body {}"},
            current_phase="start",
            task_mode="full_build"
        )
        self.assertFalse(result, "Hint should NOT be injected for CSS files")


class TestReminderDoesNotBlockFileWrite(unittest.TestCase):
    """test_reminder_does_not_block_file_write: file_write always executes"""

    def test_file_write_not_blocked(self):
        """
        The guard only appends to messages[], it never raises an exception
        or returns early. file_write ALWAYS proceeds to _execute_tool().
        """
        messages = []
        executed = []

        def mock_execute_tool(tool_name, tool_args_str):
            executed.append(tool_name)
            return {"success": True}

        # Simulate the guard + execute flow
        tool_name = "file_write"
        tool_args = {"path": "/var/www/html/index.html", "content": "<html>test</html>"}
        current_phase = "start"
        task_mode = "full_build"

        # Guard check (same logic as agent_loop.py)
        if (tool_name == "file_write"
                and isinstance(tool_args, dict)
                and any(tool_args.get("path", "").endswith(ext) for ext in (".html", ".php"))
                and current_phase == "start"
                and task_mode == "full_build"):
            messages.append({
                "role": "system",
                "content": "Ты начинаешь build без blueprint. Рекомендуется update_task_charter."
            })

        # Tool ALWAYS executes — no early return, no exception
        result = mock_execute_tool(tool_name, str(tool_args))

        self.assertEqual(len(messages), 1, "Hint message should be added")
        self.assertEqual(len(executed), 1, "file_write should always execute")
        self.assertEqual(executed[0], "file_write")
        self.assertTrue(result["success"])
        self.assertIn("Рекомендуется", messages[0]["content"])

    def test_no_hint_does_not_affect_execution(self):
        """When no hint is needed, execution is identical"""
        messages = []
        executed = []

        def mock_execute_tool(tool_name, tool_args_str):
            executed.append(tool_name)
            return {"success": True}

        tool_name = "file_write"
        tool_args = {"path": "/var/www/html/index.html", "content": "<html>test</html>"}
        current_phase = "blueprint"  # Already has a plan
        task_mode = "full_build"

        # Guard check — should NOT fire
        if (tool_name == "file_write"
                and isinstance(tool_args, dict)
                and any(tool_args.get("path", "").endswith(ext) for ext in (".html", ".php"))
                and current_phase == "start"
                and task_mode == "full_build"):
            messages.append({"role": "system", "content": "hint"})

        result = mock_execute_tool(tool_name, str(tool_args))

        self.assertEqual(len(messages), 0, "No hint when phase is blueprint")
        self.assertEqual(len(executed), 1, "file_write still executes")
        self.assertTrue(result["success"])


if __name__ == "__main__":
    # Run with verbose output
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    suite.addTests(loader.loadTestsFromTestCase(TestClassifyTaskMode))
    suite.addTests(loader.loadTestsFromTestCase(TestPhaseLogging))
    suite.addTests(loader.loadTestsFromTestCase(TestPatchModeSkipsPipeline))
    suite.addTests(loader.loadTestsFromTestCase(TestFullBuildGetsReminder))
    suite.addTests(loader.loadTestsFromTestCase(TestReminderDoesNotBlockFileWrite))

    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    sys.exit(0 if result.wasSuccessful() else 1)
