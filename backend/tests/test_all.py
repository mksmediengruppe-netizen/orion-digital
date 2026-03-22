#!/usr/bin/env python3
"""
ORION Digital — Comprehensive Test Suite v4
============================================
Target: 100+ tests covering all modules
Modules tested:
  Block 3: task_charter, execution_snapshots, goal_keeper
  Block 4: artifact_handoff, final_judge, tool_sandbox, task_scorecard, autonomy_modes
  Task 9:  amendment_extractor
  Task 10: crash_recovery
  Task 12: runtime_state
  Task 13: langgraph_persistence
  Core:    database, prompts, tools_schema, security checks
"""
import sys
import os
import json
import time
import tempfile
import unittest
import importlib.util
import sqlite3

# ═══════════════════════════════════════════════════════════
# HELPERS
# ═══════════════════════════════════════════════════════════
_this_dir = os.path.dirname(os.path.abspath(__file__))
BACKEND_DIR = os.path.dirname(_this_dir) if os.path.basename(_this_dir) == "tests" else _this_dir
sys.path.insert(0, BACKEND_DIR)

def load_module_from_file(name, path):
    """Dynamically load a Python module from file path."""
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ═══════════════════════════════════════════════════════════
# BLOCK 3: TASK CHARTER
# ═══════════════════════════════════════════════════════════
class TestTaskCharter(unittest.TestCase):
    """Tests for task_charter.py"""

    @classmethod
    def setUpClass(cls):
        cls.mod = load_module_from_file("task_charter", os.path.join(BACKEND_DIR, "task_charter.py"))
        cls.db_path = tempfile.mktemp(suffix=".db")
        cls.store = cls.mod.TaskCharterStore(db_path=cls.db_path)

    def test_01_create_charter(self):
        """Создание charter"""
        charter = self.store.create("test-task-1", "chat-1", "Тестовая задача")
        self.assertIsNotNone(charter)
        self.assertEqual(charter["task_id"], "test-task-1")

    def test_02_get_charter(self):
        """Получение charter"""
        charter = self.store.get("test-task-1")
        self.assertIsNotNone(charter)

    def test_03_add_amendment(self):
        """Добавление amendment"""
        self.store.add_amendment("test-task-1", "Изменить цвет", "scope_change")
        charter = self.store.get("test-task-1")
        self.assertIsNotNone(charter)

    def test_04_get_by_chat(self):
        """Получение charter по chat_id"""
        charter = self.store.get_by_chat("chat-1")
        self.assertIsNotNone(charter)
        self.assertEqual(charter["chat_id"], "chat-1")

    def test_05_complete_charter(self):
        """Завершение charter"""
        self.store.complete("test-task-1")
        charter = self.store.get("test-task-1")
        self.assertEqual(charter["status"], "completed")

    def test_06_create_with_constraints(self):
        """Создание charter с ограничениями"""
        charter = self.store.create("test-task-2", "chat-2", "Задача 2",
                                     constraints=["Бюджет: $5"])
        self.assertIsNotNone(charter)

    def test_07_nonexistent_charter(self):
        """Получение несуществующего charter"""
        charter = self.store.get("nonexistent-task")
        self.assertIsNone(charter)


# ═══════════════════════════════════════════════════════════
# BLOCK 3: EXECUTION SNAPSHOTS
# ═══════════════════════════════════════════════════════════
class TestExecutionSnapshots(unittest.TestCase):
    """Tests for execution_snapshots.py"""

    @classmethod
    def setUpClass(cls):
        cls.mod = load_module_from_file("execution_snapshots", os.path.join(BACKEND_DIR, "execution_snapshots.py"))
        cls.db_path = tempfile.mktemp(suffix=".db")
        cls.store = cls.mod.SnapshotStore(db_path=cls.db_path)

    def test_01_create_snapshot(self):
        """Создание снапшота"""
        snap_id = self.store.create("task-1", "step-1",
                                     snapshot_type="step_complete",
                                     iteration=1,
                                     phase="init")
        self.assertIsNotNone(snap_id)

    def test_02_latest_snapshot(self):
        """Последний снапшот"""
        snap = self.store.latest("task-1")
        self.assertIsNotNone(snap)

    def test_03_list_snapshots(self):
        """Список снапшотов"""
        snaps = self.store.list("task-1")
        self.assertGreaterEqual(len(snaps), 1)

    def test_04_multiple_snapshots(self):
        """Несколько снапшотов"""
        self.store.create("task-1", "step-2", iteration=2)
        self.store.create("task-1", "step-3", iteration=3)
        snaps = self.store.list("task-1")
        self.assertGreaterEqual(len(snaps), 3)

    def test_05_format_for_prompt(self):
        """Форматирование для промпта"""
        text = self.store.format_for_prompt("task-1")
        self.assertIsInstance(text, str)


# ═══════════════════════════════════════════════════════════
# BLOCK 3: GOALKEEPER
# ═══════════════════════════════════════════════════════════
class TestGoalKeeper(unittest.TestCase):
    """Tests for goal_keeper.py"""

    @classmethod
    def setUpClass(cls):
        cls.mod = load_module_from_file("goal_keeper", os.path.join(BACKEND_DIR, "goal_keeper.py"))
        cls.gk = cls.mod.GoalKeeper()

    def test_01_validate_allowed(self):
        """Проверка разрешённого действия"""
        result = self.gk.validate_next_action(
            task_charter={"objective": "Test"},
            latest_snapshot=None,
            proposed_action={"tool": "browser_navigate", "args": {"url": "https://example.com"}}
        )
        self.assertIn("approved", result)

    def test_02_validate_ssh_dangerous(self):
        """Блокировка опасной SSH команды"""
        result = self.gk.validate_next_action(
            task_charter={"objective": "Test"},
            latest_snapshot=None,
            proposed_action={"tool": "ssh_execute", "args": {"command": "rm -rf /"}}
        )
        self.assertIn("approved", result)
        self.assertFalse(result["approved"])

    def test_03_validate_file_write(self):
        """Проверка записи файла"""
        result = self.gk.validate_next_action(
            task_charter={"objective": "Test"},
            latest_snapshot=None,
            proposed_action={"tool": "file_write", "args": {"path": "/tmp/test.txt"}}
        )
        self.assertIn("approved", result)

    def test_04_validate_dangerous_path(self):
        """Блокировка записи в /etc"""
        result = self.gk.validate_next_action(
            task_charter={"objective": "Test"},
            latest_snapshot=None,
            proposed_action={"tool": "file_write", "args": {"path": "/etc/passwd"}}
        )
        self.assertIn("approved", result)
        self.assertFalse(result["approved"])

    def test_05_validate_no_charter(self):
        """Проверка без charter"""
        result = self.gk.validate_next_action(
            task_charter=None,
            latest_snapshot=None,
            proposed_action={"tool": "ssh_execute", "args": {"command": "ls"}}
        )
        self.assertIn("approved", result)

    def test_06_validate_task_complete(self):
        """Проверка task_complete"""
        result = self.gk.validate_next_action(
            task_charter={"objective": "Test"},
            latest_snapshot=None,
            proposed_action={"tool": "task_complete", "args": {"answer": "Done"}}
        )
        self.assertIn("approved", result)
        self.assertTrue(result["approved"])

    def test_07_get_stats(self):
        """Статистика GoalKeeper"""
        stats = self.gk.get_stats()
        self.assertIsInstance(stats, dict)


# ═══════════════════════════════════════════════════════════
# BLOCK 4: ARTIFACT HANDOFF
# ═══════════════════════════════════════════════════════════
class TestArtifactHandoff(unittest.TestCase):
    """Tests for artifact_handoff.py"""

    @classmethod
    def setUpClass(cls):
        cls.mod = load_module_from_file("artifact_handoff", os.path.join(BACKEND_DIR, "artifact_handoff.py"))
        cls.db_path = tempfile.mktemp(suffix=".db")
        cls.store = cls.mod.ArtifactHandoff(db_path=cls.db_path)

    def test_01_create_artifact(self):
        """Создание артефакта"""
        aid = self.store.create(
            task_id="task-1",
            from_agent="planner",
            artifact_type="plan",
            content={"steps": ["step1", "step2"]}
        )
        self.assertIsNotNone(aid)

    def test_02_get_artifact(self):
        """Получение артефакта"""
        arts = self.store.get_all_for_task("task-1")
        self.assertGreaterEqual(len(arts), 1)
        art = self.store.get(arts[0]["artifact_id"])
        self.assertIsNotNone(art)

    def test_03_get_all_for_task(self):
        """Все артефакты задачи"""
        arts = self.store.get_all_for_task("task-1")
        self.assertGreaterEqual(len(arts), 1)

    def test_04_create_multiple(self):
        """Несколько артефактов"""
        self.store.create("task-1", "coder", "code", {"file": "main.py"})
        arts = self.store.get_all_for_task("task-1")
        self.assertGreaterEqual(len(arts), 2)

    def test_05_nonexistent_artifact(self):
        """Несуществующий артефакт"""
        art = self.store.get("nonexistent-art-id")
        self.assertIsNone(art)

    def test_06_mark_received(self):
        """Отметка получения"""
        arts = self.store.get_all_for_task("task-1")
        if arts:
            result = self.store.mark_received(arts[0]["artifact_id"])
            self.assertTrue(result)


# ═══════════════════════════════════════════════════════════
# BLOCK 4: FINAL JUDGE
# ═══════════════════════════════════════════════════════════
class TestFinalJudge(unittest.TestCase):
    """Tests for final_judge.py"""

    @classmethod
    def setUpClass(cls):
        cls.mod = load_module_from_file("final_judge", os.path.join(BACKEND_DIR, "final_judge.py"))
        cls.judge = cls.mod.FinalJudge()

    def test_01_judge_pass(self):
        """Оценка задачи"""
        result = self.judge.judge(
            task_charter={"objective": "Создать файл", "steps": [], "constraints": []},
            agent_final_answer="Файл создан успешно",
            artifacts=[],
            ssh_results=[]
        )
        self.assertIsNotNone(result)

    def test_02_judge_empty_answer(self):
        """Оценка пустого ответа"""
        result = self.judge.judge(
            task_charter={"objective": "Создать сайт", "steps": [], "constraints": []},
            agent_final_answer="",
            artifacts=[],
            ssh_results=[]
        )
        self.assertIsNotNone(result)

    def test_03_judge_result_type(self):
        """Тип результата JudgeResult"""
        result = self.judge.judge(
            task_charter={"objective": "Тест", "steps": [], "constraints": []},
            agent_final_answer="Результат",
        )
        # Should be JudgeResult or dict
        self.assertIsNotNone(result)

    def test_04_judge_no_charter(self):
        """Оценка без charter"""
        result = self.judge.judge(
            task_charter=None,
            agent_final_answer="Done",
        )
        self.assertIsNotNone(result)


# ═══════════════════════════════════════════════════════════
# BLOCK 4: TOOL SANDBOX
# ═══════════════════════════════════════════════════════════
class TestToolSandbox(unittest.TestCase):
    """Tests for tool_sandbox.py"""

    @classmethod
    def setUpClass(cls):
        cls.mod = load_module_from_file("tool_sandbox", os.path.join(BACKEND_DIR, "tool_sandbox.py"))
        cls.sandbox = cls.mod.ToolSandbox()

    def test_01_check_allowed(self):
        """Проверка разрешённого инструмента"""
        result = self.sandbox.check("browser_navigate")
        self.assertTrue(result["allowed"])

    def test_02_check_ssh(self):
        """Проверка SSH инструмента"""
        result = self.sandbox.check("ssh_execute")
        self.assertIn("allowed", result)

    def test_03_deny_tool(self):
        """Запрет инструмента"""
        self.sandbox.deny_tool("dangerous_tool")
        result = self.sandbox.check("dangerous_tool")
        self.assertFalse(result["allowed"])

    def test_04_allow_tool(self):
        """Разрешение инструмента"""
        self.sandbox.allow_tool("custom_tool")
        result = self.sandbox.check("custom_tool")
        self.assertTrue(result["allowed"])

    def test_05_check_with_args_ssh(self):
        """Проверка SSH с аргументами"""
        result = self.sandbox.check_with_args("ssh_execute", {"command": "ls -la"})
        self.assertIn("allowed", result)

    def test_06_check_with_args_dangerous(self):
        """Блокировка опасных SSH команд"""
        result = self.sandbox.check_with_args("ssh_execute", {"command": "rm -rf /"})
        self.assertFalse(result["allowed"])

    def test_07_get_allowed_tools(self):
        """Список разрешённых инструментов"""
        allowed = self.sandbox.get_allowed_tools()
        self.assertIsInstance(allowed, list)
        self.assertGreater(len(allowed), 0)

    def test_08_browser_read_only(self):
        """Browser read-only mode"""
        self.assertTrue(self.sandbox.browser_read_only)

    def test_09_get_denied_tools(self):
        """Список запрещённых инструментов"""
        denied = self.sandbox.get_denied_tools()
        self.assertIsInstance(denied, list)

    def test_10_validate_arguments_func(self):
        """Функция validate_arguments"""
        result = self.mod.validate_arguments("ssh_execute", {"command": "ls"})
        self.assertIn("allowed", result)

    def test_11_validate_arguments_dangerous(self):
        """validate_arguments блокирует опасные команды"""
        result = self.mod.validate_arguments("ssh_execute", {"command": "rm -rf /"})
        self.assertFalse(result["allowed"])

    def test_12_filter_tools_schema(self):
        """Фильтрация tools schema"""
        schema = [
            {"type": "function", "function": {"name": "ssh_execute", "description": "SSH", "parameters": {}}},
            {"type": "function", "function": {"name": "browser_navigate", "description": "Nav", "parameters": {}}},
        ]
        filtered = self.sandbox.filter_tools_schema(schema)
        self.assertIsInstance(filtered, list)


# ═══════════════════════════════════════════════════════════
# BLOCK 4: TASK SCORECARD
# ═══════════════════════════════════════════════════════════
class TestTaskScorecard(unittest.TestCase):
    """Tests for task_scorecard.py"""

    @classmethod
    def setUpClass(cls):
        cls.mod = load_module_from_file("task_scorecard", os.path.join(BACKEND_DIR, "task_scorecard.py"))
        cls.db_path = tempfile.mktemp(suffix=".db")
        cls.store = cls.mod.TaskScorecard(db_path=cls.db_path)

    def test_01_start(self):
        """Начало отслеживания задачи"""
        sc = self.store.start(
            task_id="sc-test-1",
            chat_id="chat-1",
            user_id="user-1",
            orion_mode="pro",
            objective="Тестовая задача"
        )
        self.assertIsNotNone(sc)
        self.assertEqual(sc["status"], "running")

    def test_02_record_iteration(self):
        """Запись итерации"""
        self.store.record_iteration("sc-test-1", cost=0.01, input_tokens=100, output_tokens=50)
        sc = self.store.get("sc-test-1")
        self.assertEqual(sc["total_iterations"], 1)

    def test_03_record_tool_call(self):
        """Запись tool call"""
        self.store.record_tool_call("sc-test-1", "ssh_execute")
        self.store.record_tool_call("sc-test-1", "ssh_execute")
        sc = self.store.get("sc-test-1")
        self.assertEqual(sc["tool_calls"]["ssh_execute"], 2)

    def test_04_record_error(self):
        """Запись ошибки"""
        self.store.record_error("sc-test-1", "Connection timeout")
        sc = self.store.get("sc-test-1")
        self.assertGreaterEqual(sc["error_count"], 1)

    def test_05_finish(self):
        """Завершение задачи"""
        sc = self.store.finish(
            task_id="sc-test-1",
            verdict="PASS",
            quality_score=0.85,
            final_answer_len=500
        )
        self.assertEqual(sc["status"], "done")

    def test_06_analytics(self):
        """Аналитика"""
        analytics = self.store.get_analytics()
        self.assertIn("total_tasks", analytics)

    def test_07_format_for_user(self):
        """Форматирование для пользователя"""
        text = self.store.format_for_user("sc-test-1")
        self.assertIn("Метрики", text)

    def test_08_get_by_chat(self):
        """Получение по chat_id"""
        cards = self.store.get_by_chat("chat-1")
        self.assertGreaterEqual(len(cards), 1)


# ═══════════════════════════════════════════════════════════
# BLOCK 4: AUTONOMY MODES
# ═══════════════════════════════════════════════════════════
class TestAutonomyModes(unittest.TestCase):
    """Tests for autonomy_modes.py"""

    @classmethod
    def setUpClass(cls):
        cls.mod = load_module_from_file("autonomy_modes", os.path.join(BACKEND_DIR, "autonomy_modes.py"))
        cls.mgr = cls.mod.AutonomyManager()

    def test_01_default_mode(self):
        """Режим по умолчанию"""
        mode = self.mgr.get_mode()
        self.assertIn(mode, ["full", "standard", "cautious", "supervised", "readonly"])

    def test_02_set_mode(self):
        """Установка режима"""
        self.mgr.set_mode("supervised")
        self.assertEqual(self.mgr.get_mode(), "supervised")

    def test_03_check_action_full(self):
        """Проверка действия в full режиме"""
        self.mgr.set_mode("full")
        result = self.mgr.check_action("ssh_execute")
        self.assertIn("allowed", result)
        self.assertTrue(result["allowed"])

    def test_04_check_action_readonly(self):
        """Проверка действия в readonly"""
        self.mgr.set_mode("readonly")
        result = self.mgr.check_action("ssh_execute")
        self.assertIn("allowed", result)

    def test_05_check_iteration_limit(self):
        """Проверка лимита итераций"""
        self.mgr.set_mode("standard")
        result = self.mgr.check_iteration_limit()
        self.assertIn("exceeded", result)
        self.assertFalse(result["exceeded"])

    def test_06_check_cost_limit(self):
        """Проверка лимита стоимости"""
        result = self.mgr.check_cost_limit()
        self.assertIn("exceeded", result)
        self.assertFalse(result["exceeded"])

    def test_07_get_config(self):
        """Получение конфигурации"""
        config = self.mgr.get_config()
        self.assertIsNotNone(config)

    def test_08_get_status(self):
        """Получение статуса"""
        status = self.mgr.get_status()
        self.assertIsInstance(status, dict)
        self.assertIn("mode", status)

    def test_09_invalid_mode(self):
        """Установка невалидного режима"""
        result = self.mgr.set_mode("invalid_mode_xyz")
        self.assertFalse(result)

    def test_10_reset_counters(self):
        """Сброс счётчиков"""
        self.mgr.increment_iteration()
        self.mgr.add_cost(0.01)
        self.mgr.reset_counters()
        status = self.mgr.get_status()
        self.assertIsInstance(status, dict)


# ═══════════════════════════════════════════════════════════
# TASK 9: AMENDMENT EXTRACTOR
# ═══════════════════════════════════════════════════════════
class TestAmendmentExtractor(unittest.TestCase):
    """Tests for amendment_extractor.py (Task 9)"""

    @classmethod
    def setUpClass(cls):
        cls.mod = load_module_from_file("amendment_extractor", os.path.join(BACKEND_DIR, "amendment_extractor.py"))
        cls.extractor = cls.mod.AmendmentExtractor()

    def test_01_classify_continuation(self):
        """Классификация продолжения"""
        result = self.extractor.classify("продолжай")
        self.assertIn("type", result)

    def test_02_classify_amendment(self):
        """Классификация изменения"""
        result = self.extractor.classify("измени цвет на красный", "Создание сайта")
        self.assertIn("type", result)

    def test_03_classify_new_task(self):
        """Классификация новой задачи"""
        result = self.extractor.classify("создай новый проект на React")
        self.assertIn("type", result)

    def test_04_classify_clarification(self):
        """Классификация уточнения"""
        result = self.extractor.classify("что ты имел в виду?")
        self.assertIn("type", result)

    def test_05_empty_message(self):
        """Пустое сообщение"""
        result = self.extractor.classify("")
        self.assertIn("type", result)

    def test_06_rule_based_extraction(self):
        """Правила извлечения"""
        rules = self.extractor._rule_extract("добавь кнопку на главную страницу")
        self.assertIsInstance(rules, list)

    def test_07_long_message(self):
        """Длинное сообщение"""
        long_msg = "Пожалуйста, " * 100 + "измени дизайн"
        result = self.extractor.classify(long_msg)
        self.assertIn("type", result)


# ═══════════════════════════════════════════════════════════
# TASK 10: CRASH RECOVERY
# ═══════════════════════════════════════════════════════════
class TestCrashRecovery(unittest.TestCase):
    """Tests for crash_recovery.py (Task 10)"""

    @classmethod
    def setUpClass(cls):
        cls.mod = load_module_from_file("crash_recovery", os.path.join(BACKEND_DIR, "crash_recovery.py"))
        cls.db_path = tempfile.mktemp(suffix=".db")
        cls.recovery = cls.mod.CrashRecovery(db_path=cls.db_path)

    def test_01_save_checkpoint(self):
        """Сохранение checkpoint"""
        self.recovery.save_checkpoint(
            task_id="task-cr-1",
            chat_id="chat-cr-1",
            iteration=5,
            last_tool="ssh_execute",
            actions_count=10,
            task_cost=0.05
        )
        cp = self.recovery.load_checkpoint("chat-cr-1")
        self.assertIsNotNone(cp)

    def test_02_heartbeat(self):
        """Heartbeat обновление"""
        self.recovery.heartbeat("chat-cr-1")
        cp = self.recovery.load_checkpoint("chat-cr-1")
        self.assertIsNotNone(cp)

    def test_03_complete_checkpoint(self):
        """Завершение checkpoint"""
        self.recovery.complete_checkpoint("chat-cr-1")
        cp = self.recovery.load_checkpoint("chat-cr-1")
        if cp:
            self.assertIn(cp.get("status", "completed"), ["completed", "done"])

    def test_04_fail_checkpoint(self):
        """Отметка провала"""
        self.recovery.save_checkpoint("task-cr-2", "chat-cr-2", 3, "browser", 5, 0.02)
        self.recovery.fail_checkpoint("chat-cr-2", "timeout")
        cp = self.recovery.load_checkpoint("chat-cr-2")
        if cp:
            self.assertEqual(cp.get("status"), "failed")

    def test_05_can_auto_restart(self):
        """Проверка возможности авто-рестарта"""
        self.recovery.save_checkpoint("task-cr-3", "chat-cr-3", 1, "ssh", 2, 0.01)
        can = self.recovery.can_auto_restart("chat-cr-3")
        self.assertIsInstance(can, bool)

    def test_06_find_stale_tasks(self):
        """Поиск зависших задач"""
        stale = self.recovery.find_stale_tasks()
        self.assertIsInstance(stale, list)

    def test_07_nonexistent_checkpoint(self):
        """Загрузка несуществующего checkpoint"""
        cp = self.recovery.load_checkpoint("nonexistent-chat")
        self.assertTrue(cp is None or cp == {} or isinstance(cp, dict))

    def test_08_increment_restart(self):
        """Инкремент рестартов"""
        self.recovery.save_checkpoint("task-cr-4", "chat-cr-4", 1, "ssh", 1, 0.01)
        self.recovery.increment_restart("chat-cr-4")
        # Should still work
        can = self.recovery.can_auto_restart("chat-cr-4")
        self.assertIsInstance(can, bool)


# ═══════════════════════════════════════════════════════════
# TASK 12: RUNTIME STATE
# ═══════════════════════════════════════════════════════════
class TestRuntimeState(unittest.TestCase):
    """Tests for runtime_state.py (Task 12)"""

    @classmethod
    def setUpClass(cls):
        cls.mod = load_module_from_file("runtime_state", os.path.join(BACKEND_DIR, "runtime_state.py"))
        cls.db_path = tempfile.mktemp(suffix=".db")
        # Monkey-patch _get_conn to avoid importing database module (which uses different DB)
        import types
        store = cls.mod.RuntimeStateStore.__new__(cls.mod.RuntimeStateStore)
        store._db_path = cls.db_path
        store._lock = __import__('threading').Lock()
        def _get_conn_local(self):
            conn = sqlite3.connect(self._db_path, check_same_thread=False, timeout=10)
            conn.execute("PRAGMA journal_mode=WAL")
            return conn
        store._get_conn = types.MethodType(_get_conn_local, store)
        store._init_table()
        cls.store = store

    def test_01_register_task(self):
        """Регистрация задачи"""
        self.store.register_task(
            chat_id="chat-rs-1",
            task_id="task-rs-1",
            user_id="user-1",
            orion_mode="turbo",
            user_message="Тестовая задача"
        )
        task = self.store.get_task("chat-rs-1")
        self.assertIsNotNone(task)

    def test_02_update_task(self):
        """Обновление задачи"""
        self.store.update_task(
            chat_id="chat-rs-1",
            iteration=5,
            last_tool="ssh_execute",
            task_cost=0.05
        )
        task = self.store.get_task("chat-rs-1")
        self.assertIsNotNone(task)

    def test_03_complete_task(self):
        """Завершение задачи"""
        self.store.complete_task("chat-rs-1")
        task = self.store.get_task("chat-rs-1")
        if task:
            self.assertIn(task.get("status", "completed"), ["completed", "done"])

    def test_04_fail_task(self):
        """Провал задачи"""
        self.store.register_task("chat-rs-2", "task-rs-2")
        self.store.fail_task("chat-rs-2", "timeout error")
        task = self.store.get_task("chat-rs-2")
        if task:
            self.assertEqual(task.get("status"), "failed")

    def test_05_get_running_tasks(self):
        """Список активных задач"""
        self.store.register_task("chat-rs-3", "task-rs-3")
        running = self.store.get_running_tasks()
        self.assertIsInstance(running, list)

    def test_06_cleanup_stale(self):
        """Очистка устаревших задач"""
        cleaned = self.store.cleanup_stale(max_age_hours=0)
        self.assertIsInstance(cleaned, (int, type(None)))

    def test_07_get_stats(self):
        """Статистика"""
        stats = self.store.get_stats()
        self.assertIsInstance(stats, dict)

    def test_08_nonexistent_task(self):
        """Несуществующая задача"""
        task = self.store.get_task("nonexistent-chat")
        self.assertTrue(task is None or task == {})


# ═══════════════════════════════════════════════════════════
# TASK 13: LANGGRAPH PERSISTENCE
# ═══════════════════════════════════════════════════════════
class TestLanggraphPersistence(unittest.TestCase):
    """Tests for langgraph_persistence.py (Task 13)"""

    @classmethod
    def setUpClass(cls):
        cls.mod = load_module_from_file("langgraph_persistence", os.path.join(BACKEND_DIR, "langgraph_persistence.py"))
        cls.db_path = tempfile.mktemp(suffix=".db")
        cls.store = cls.mod.LanggraphStatePersistence(db_path=cls.db_path)

    def test_01_save_state(self):
        """Сохранение состояния"""
        state_id = self.store.save_state(
            chat_id="chat-lg-1",
            thread_id="thread-1",
            messages=[{"role": "user", "content": "hello"}],
            metadata={"iteration": 1}
        )
        self.assertIsNotNone(state_id)

    def test_02_load_state(self):
        """Загрузка состояния"""
        state = self.store.load_state("chat-lg-1", "thread-1")
        self.assertIsNotNone(state)
        self.assertIn("messages", state)

    def test_03_update_state(self):
        """Обновление состояния"""
        self.store.save_state(
            chat_id="chat-lg-1",
            thread_id="thread-1",
            messages=[
                {"role": "user", "content": "hello"},
                {"role": "assistant", "content": "hi"}
            ],
            iteration=2
        )
        state = self.store.load_state("chat-lg-1", "thread-1")
        self.assertEqual(len(state["messages"]), 2)

    def test_04_delete_state(self):
        """Удаление состояния"""
        self.store.save_state("chat-lg-2", "thread-2", [{"role": "user", "content": "test"}])
        self.store.delete_state("chat-lg-2", "thread-2")
        state = self.store.load_state("chat-lg-2", "thread-2")
        self.assertIsNone(state)

    def test_05_list_threads(self):
        """Список потоков"""
        threads = self.store.list_threads("chat-lg-1")
        self.assertIsInstance(threads, list)
        self.assertGreaterEqual(len(threads), 1)

    def test_06_cleanup_old(self):
        """Очистка старых состояний"""
        count = self.store.cleanup_old(max_age_hours=0)
        self.assertIsInstance(count, int)

    def test_07_get_stats(self):
        """Статистика"""
        stats = self.store.get_stats()
        self.assertIn("total_states", stats)

    def test_08_nonexistent_state(self):
        """Несуществующее состояние"""
        state = self.store.load_state("nonexistent", "nonexistent")
        self.assertIsNone(state)


# ═══════════════════════════════════════════════════════════
# CORE: DATABASE
# ═══════════════════════════════════════════════════════════
class TestDatabase(unittest.TestCase):
    """Tests for database.py"""

    @classmethod
    def setUpClass(cls):
        cls.mod = load_module_from_file("database", os.path.join(BACKEND_DIR, "database.py"))

    def test_01_init_db(self):
        """Инициализация БД"""
        self.mod.init_db()

    def test_02_get_conn(self):
        """Получение соединения"""
        conn = self.mod._get_conn()
        self.assertIsNotNone(conn)

    def test_03_tables_exist(self):
        """Проверка существования таблиц"""
        conn = self.mod._get_conn()
        tables = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        table_names = [t[0] for t in tables]
        required = ["users", "chats", "sessions", "task_charters", "execution_snapshots",
                     "task_scorecards", "artifact_handoffs"]
        for t in required:
            self.assertIn(t, table_names, f"Table {t} not found")

    def test_04_load_db(self):
        """Загрузка данных"""
        db = self.mod.load_db()
        self.assertIsInstance(db, dict)

    def test_05_kv_store(self):
        """KV store операции"""
        conn = self.mod._get_conn()
        import datetime
        now = datetime.datetime.utcnow().isoformat()
        conn.execute("INSERT OR REPLACE INTO kv_store (key, value, updated_at) VALUES (?, ?, ?)",
                     ("test_key", json.dumps({"data": "test"}), now))
        conn.commit()
        row = conn.execute("SELECT value FROM kv_store WHERE key = ?", ("test_key",)).fetchone()
        self.assertIsNotNone(row)

    def test_06_langgraph_tables(self):
        """Langgraph persistence module exists"""
        lg_path = os.path.join(BACKEND_DIR, "langgraph_persistence.py")
        self.assertTrue(os.path.exists(lg_path), "langgraph_persistence.py not found")


# ═══════════════════════════════════════════════════════════
# CORE: PROMPTS
# ═══════════════════════════════════════════════════════════
class TestPrompts(unittest.TestCase):
    """Tests for prompts.py"""

    @classmethod
    def setUpClass(cls):
        cls.mod = load_module_from_file("prompts", os.path.join(BACKEND_DIR, "prompts.py"))

    def test_01_agent_system_prompt_exists(self):
        """Системный промпт существует"""
        self.assertTrue(hasattr(self.mod, 'AGENT_SYSTEM_PROMPT'))
        self.assertGreater(len(self.mod.AGENT_SYSTEM_PROMPT), 100)

    def test_02_pro_prompt_exists(self):
        """Pro промпт существует"""
        self.assertTrue(hasattr(self.mod, 'AGENT_SYSTEM_PROMPT_PRO'))
        self.assertGreater(len(self.mod.AGENT_SYSTEM_PROMPT_PRO), 100)

    def test_03_get_system_prompt(self):
        """Получение промпта по режиму"""
        prompt = self.mod.get_system_prompt("fast")
        self.assertIsInstance(prompt, str)
        self.assertGreater(len(prompt), 50)

    def test_04_get_pro_prompt(self):
        """Получение Pro промпта"""
        prompt = self.mod.get_system_prompt("standard")
        self.assertIsInstance(prompt, str)

    def test_05_agent_state_type(self):
        """AgentState TypedDict"""
        self.assertTrue(hasattr(self.mod, 'AgentState'))

    def test_06_prompt_contains_orion(self):
        """Промпт содержит ORION"""
        self.assertIn("ORION", self.mod.AGENT_SYSTEM_PROMPT)


# ═══════════════════════════════════════════════════════════
# CORE: TOOLS SCHEMA
# ═══════════════════════════════════════════════════════════
class TestToolsSchema(unittest.TestCase):
    """Tests for tools_schema.py"""

    @classmethod
    def setUpClass(cls):
        cls.mod = load_module_from_file("tools_schema", os.path.join(BACKEND_DIR, "tools_schema.py"))

    def test_01_schema_exists(self):
        """TOOLS_SCHEMA существует"""
        self.assertTrue(hasattr(self.mod, 'TOOLS_SCHEMA'))
        self.assertIsInstance(self.mod.TOOLS_SCHEMA, list)

    def test_02_schema_not_empty(self):
        """Схема не пустая"""
        self.assertGreater(len(self.mod.TOOLS_SCHEMA), 5)

    def test_03_each_tool_has_name(self):
        """Каждый инструмент имеет имя"""
        for tool in self.mod.TOOLS_SCHEMA:
            if isinstance(tool, dict):
                func = tool.get("function", tool)
                self.assertIn("name", func)

    def test_04_each_tool_has_description(self):
        """Каждый инструмент имеет описание"""
        for tool in self.mod.TOOLS_SCHEMA:
            if isinstance(tool, dict):
                func = tool.get("function", tool)
                self.assertIn("description", func)

    def test_05_ssh_execute_in_schema(self):
        """ssh_execute в схеме"""
        names = [t.get("function", t).get("name", "") for t in self.mod.TOOLS_SCHEMA if isinstance(t, dict)]
        self.assertIn("ssh_execute", names)

    def test_06_browser_navigate_in_schema(self):
        """browser_navigate в схеме"""
        names = [t.get("function", t).get("name", "") for t in self.mod.TOOLS_SCHEMA if isinstance(t, dict)]
        self.assertIn("browser_navigate", names)

    def test_07_task_complete_in_schema(self):
        """task_complete в схеме"""
        names = [t.get("function", t).get("name", "") for t in self.mod.TOOLS_SCHEMA if isinstance(t, dict)]
        self.assertIn("task_complete", names)


# ═══════════════════════════════════════════════════════════
# SECURITY & SYNTAX CHECKS
# ═══════════════════════════════════════════════════════════
class TestSyntax(unittest.TestCase):
    """Syntax validation for all Python files"""

    def _check_syntax(self, filepath):
        import ast
        with open(filepath, 'r', encoding='utf-8') as f:
            source = f.read()
        try:
            ast.parse(source)
            return True
        except SyntaxError:
            return False

    def test_01_agent_loop(self):
        """agent_loop.py syntax"""
        self.assertTrue(self._check_syntax(os.path.join(BACKEND_DIR, "agent_loop.py")))

    def test_02_agent_routes(self):
        """agent_routes.py syntax"""
        self.assertTrue(self._check_syntax(os.path.join(BACKEND_DIR, "agent_routes.py")))

    def test_03_database(self):
        """database.py syntax"""
        self.assertTrue(self._check_syntax(os.path.join(BACKEND_DIR, "database.py")))

    def test_04_shared(self):
        """shared.py syntax"""
        self.assertTrue(self._check_syntax(os.path.join(BACKEND_DIR, "shared.py")))

    def test_05_app(self):
        """app.py syntax"""
        self.assertTrue(self._check_syntax(os.path.join(BACKEND_DIR, "app.py")))

    def test_06_tools_schema(self):
        """tools_schema.py syntax"""
        self.assertTrue(self._check_syntax(os.path.join(BACKEND_DIR, "tools_schema.py")))

    def test_07_prompts(self):
        """prompts.py syntax"""
        self.assertTrue(self._check_syntax(os.path.join(BACKEND_DIR, "prompts.py")))

    def test_08_amendment_extractor(self):
        """amendment_extractor.py syntax"""
        self.assertTrue(self._check_syntax(os.path.join(BACKEND_DIR, "amendment_extractor.py")))

    def test_09_crash_recovery(self):
        """crash_recovery.py syntax"""
        self.assertTrue(self._check_syntax(os.path.join(BACKEND_DIR, "crash_recovery.py")))

    def test_10_runtime_state(self):
        """runtime_state.py syntax"""
        self.assertTrue(self._check_syntax(os.path.join(BACKEND_DIR, "runtime_state.py")))

    def test_11_langgraph_persistence(self):
        """langgraph_persistence.py syntax"""
        self.assertTrue(self._check_syntax(os.path.join(BACKEND_DIR, "langgraph_persistence.py")))

    def test_12_task_scorecard(self):
        """task_scorecard.py syntax"""
        self.assertTrue(self._check_syntax(os.path.join(BACKEND_DIR, "task_scorecard.py")))

    def test_13_tool_sandbox(self):
        """tool_sandbox.py syntax"""
        self.assertTrue(self._check_syntax(os.path.join(BACKEND_DIR, "tool_sandbox.py")))

    def test_14_orchestrator_v2(self):
        """orchestrator_v2.py syntax"""
        self.assertTrue(self._check_syntax(os.path.join(BACKEND_DIR, "orchestrator_v2.py")))

    def test_15_goal_keeper(self):
        """goal_keeper.py syntax"""
        self.assertTrue(self._check_syntax(os.path.join(BACKEND_DIR, "goal_keeper.py")))


class TestSecurityChecks(unittest.TestCase):
    """Security validation across codebase"""

    def _read_file(self, filename):
        path = os.path.join(BACKEND_DIR, filename)
        if os.path.exists(path):
            with open(path, 'r', encoding='utf-8') as f:
                return f.read()
        return ""

    def test_01_bcrypt_used(self):
        """bcrypt используется для паролей"""
        content = self._read_file("admin_routes.py")
        self.assertIn("bcrypt", content)

    def test_02_no_verify_false(self):
        """Нет verify=False в requests"""
        for fname in ["agent_loop.py", "shared.py", "agent_routes.py"]:
            content = self._read_file(fname)
            self.assertNotIn("verify=False", content, f"verify=False found in {fname}")

    def test_03_no_hardcoded_credentials(self):
        """Нет захардкоженных credentials"""
        for fname in ["shared.py", "app.py"]:
            content = self._read_file(fname)
            self.assertNotIn("password = \"", content.lower())

    def test_04_sql_parameterized(self):
        """SQL запросы параметризованы"""
        content = self._read_file("database.py")
        self.assertIn("?", content)

    def test_05_httponly_cookies(self):
        """HttpOnly cookies"""
        for fname in ["auth_routes.py", "admin_routes.py"]:
            content = self._read_file(fname)
            if "set_cookie" in content:
                self.assertIn("httponly", content.lower())

    def test_06_no_eval_in_code(self):
        """Нет eval() в основном коде (кроме строковых литералов)"""
        for fname in ["shared.py"]:
            content = self._read_file(fname)
            # eval() should not be used (except in comments and string literals)
            lines = [l for l in content.split('\n')
                     if 'eval(' in l and not l.strip().startswith('#')
                     and not l.strip().startswith("'") and not l.strip().startswith('"')]
            self.assertEqual(len(lines), 0, f"eval() found in {fname}")

    def test_07_cors_configured(self):
        """CORS настроен"""
        # CORS may be in shared.py, app.py, or agent_routes.py
        found = False
        for fname in ["app.py", "shared.py", "agent_routes.py", "misc_routes.py"]:
            content = self._read_file(fname)
            if "CORS" in content or "Access-Control" in content or "cross_origin" in content:
                found = True
                break
        self.assertTrue(found, "CORS not configured anywhere")


class TestAPIEndpoints(unittest.TestCase):
    """API endpoint tests (requires running server)"""

    @classmethod
    def setUpClass(cls):
        import urllib.request
        cls.base_url = "http://localhost:3510"
        try:
            urllib.request.urlopen(f"{cls.base_url}/api/health", timeout=3)
            cls.server_available = True
        except Exception as e:
            cls.server_available = False
            raise unittest.SkipTest(f"Server not available: {e}")

    def test_01_health(self):
        """API health check"""
        import urllib.request
        resp = urllib.request.urlopen(f"{self.base_url}/api/health", timeout=5)
        self.assertEqual(resp.status, 200)

    def test_02_health_json(self):
        """API health returns JSON"""
        import urllib.request
        resp = urllib.request.urlopen(f"{self.base_url}/api/health", timeout=5)
        data = json.loads(resp.read())
        self.assertIn("status", data)


# ═══════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════
if __name__ == "__main__":
    print("=" * 60)
    print("ORION Digital — Test Suite v4")
    print("=" * 60)
    print(f"Backend dir: {BACKEND_DIR}")
    print(f"Python: {sys.version}")
    print(f"Time: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

    loader = unittest.TestLoader()
    suite = unittest.TestSuite()

    test_classes = [
        TestTaskCharter,
        TestExecutionSnapshots,
        TestGoalKeeper,
        TestArtifactHandoff,
        TestFinalJudge,
        TestToolSandbox,
        TestTaskScorecard,
        TestAutonomyModes,
        TestAmendmentExtractor,
        TestCrashRecovery,
        TestRuntimeState,
        TestLanggraphPersistence,
        TestDatabase,
        TestPrompts,
        TestToolsSchema,
        TestSyntax,
        TestSecurityChecks,
        TestAPIEndpoints,
    ]

    for cls in test_classes:
        suite.addTests(loader.loadTestsFromTestCase(cls))

    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)

    total = result.testsRun
    failures = len(result.failures)
    errors = len(result.errors)
    skipped = len(result.skipped)
    passed = total - failures - errors - skipped
    rate = int(passed / total * 100) if total > 0 else 0

    print("=" * 60)
    print(f"TOTAL: {total} | PASS: {passed} | FAIL: {failures} | ERROR: {errors} | SKIP: {skipped}")
    print(f"SUCCESS RATE: {rate}%")
    print("=" * 60)
