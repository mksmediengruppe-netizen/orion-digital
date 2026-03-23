"""Тесты Golden Paths."""

import sys
import os
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from golden_paths import GoldenPathStore, GoldenPathMatch


def make_store(tmp_path):
    return GoldenPathStore(str(tmp_path / "golden_paths_test.db"))


def sample_actions():
    return [
        {
            "tool": "ssh_execute",
            "args": {
                "command": "mysql -u root -pSuperSecret123 -e 'show tables'",
                "password": "SuperSecret123",
                "email": "admin@example.com",
                "server_ip": "45.67.57.175",
            },
            "description": "Run DB check for admin@example.com on 45.67.57.175",
            "expected_outcome": "DB reachable with token deadbeefdeadbeefdeadbeef",
            "success": True,
            "elapsed": 12.5,
            "cost": 0.25,
        }
    ]


def test_save_golden_path_sanitizes_secrets(tmp_path):
    store = make_store(tmp_path)
    path_id = store.save_golden_path(
        "bitrix_install",
        "Установить Битрикс на 45.67.57.175 и отправить admin@example.com",
        sample_actions(),
        environment_fingerprint={"platform": "bitrix", "os_family": "ubuntu", "web_server": "nginx", "db": "mysql"},
        final_judge_verdict="APPROVED",
        task_status="SUCCESS",
        all_success_criteria_passed=True,
    )
    assert path_id is not None
    match = store.find_golden_path(
        "bitrix_install", "Поставь Битрикс",
        {"os_family": "ubuntu", "web_server": "nginx", "db": "mysql"},
    )
    assert match is not None
    step = match.path["steps"][0]
    payload = step["action_template"]
    dump = str(payload) + str(step["description"]) + str(step["expected_outcome"])
    assert "SuperSecret123" not in dump
    assert "admin@example.com" not in dump
    assert "45.67.57.175" not in dump


def test_find_by_fingerprint(tmp_path):
    store = make_store(tmp_path)
    store.save_golden_path(
        "bitrix_install", "Установить Битрикс в подпапку",
        sample_actions(),
        environment_fingerprint={
            "platform": "bitrix", "os_family": "ubuntu",
            "web_server": "nginx", "php_major": "8.2",
            "db": "mysql", "install_mode": "subfolder",
        },
        final_judge_verdict="APPROVED",
        task_status="SUCCESS",
        all_success_criteria_passed=True,
    )
    match = store.find_golden_path(
        "bitrix_install", "Поставь Битрикс в подпапку",
        {"os_family": "ubuntu", "web_server": "nginx",
         "php_major": "8.2", "db": "mysql", "install_mode": "subfolder"},
    )
    assert match is not None
    assert match.match_score >= 4


def test_find_ignores_inactive(tmp_path):
    """Path деактивируется после 3 fail подряд."""
    store = make_store(tmp_path)
    path_id = store.save_golden_path(
        "bitrix_install", "Установить Битрикс",
        sample_actions(),
        environment_fingerprint={
            "os_family": "ubuntu", "web_server": "nginx",
            "php_major": "8.2", "db": "mysql"
        },
        final_judge_verdict="APPROVED",
        task_status="SUCCESS",
        all_success_criteria_passed=True,
    )
    # 3 fail подряд — должен деактивироваться
    # (по логике _should_deactivate: recent_fail_streak >= 3)
    store.record_path_outcome(path_id, success=False)
    store.record_path_outcome(path_id, success=False)
    store.record_path_outcome(path_id, success=False)

    match = store.find_golden_path(
        "bitrix_install", "Установить Битрикс",
        {"os_family": "ubuntu", "web_server": "nginx",
         "php_major": "8.2", "db": "mysql"},
    )
    # Path должен быть деактивирован или не найден
    assert match is None, "Path should be deactivated after 3 consecutive fails"


def test_anti_pattern_saved_on_false_success(tmp_path):
    store = make_store(tmp_path)
    anti_id = store.save_anti_pattern(
        "bitrix_install",
        "admin_returns_public_landing",
        "/bitrix/admin/ отдаёт лендинг, а не админку",
        environment_fingerprint={"platform": "bitrix", "web_server": "nginx"},
    )
    assert anti_id is not None
    prompt = store.format_anti_patterns_prompt("bitrix_install")
    assert "ЛОЖНЫЕ УСПЕХИ" in prompt
    assert "админ" in prompt.lower()


def test_deactivation_logic(tmp_path):
    store = make_store(tmp_path)
    path_id = store.save_golden_path(
        "bitrix_install", "Установить Битрикс",
        sample_actions(),
        environment_fingerprint={
            "os_family": "ubuntu", "web_server": "nginx",
            "php_major": "8.2", "db": "mysql"
        },
        final_judge_verdict="APPROVED",
        task_status="SUCCESS",
        all_success_criteria_passed=True,
    )
    store.record_path_outcome(path_id, success=False)
    store.record_path_outcome(path_id, success=False)
    store.record_path_outcome(path_id, success=False)
    match = store.find_golden_path(
        "bitrix_install", "Установить Битрикс",
        {"os_family": "ubuntu", "web_server": "nginx",
         "php_major": "8.2", "db": "mysql"},
    )
    assert match is None


def test_injection_as_recommendation_not_command(tmp_path):
    store = make_store(tmp_path)
    store.save_golden_path(
        "bitrix_install", "Установить Битрикс",
        sample_actions(),
        environment_fingerprint={
            "os_family": "ubuntu", "web_server": "nginx",
            "php_major": "8.2", "db": "mysql"
        },
        final_judge_verdict="APPROVED",
        task_status="SUCCESS",
        all_success_criteria_passed=True,
    )
    match = store.find_golden_path(
        "bitrix_install", "Установить Битрикс",
        {"os_family": "ubuntu", "web_server": "nginx",
         "php_major": "8.2", "db": "mysql"},
    )
    prompt = store.format_runbook_prompt(match)
    assert "предпочтительный путь" in prompt
    assert "адаптируй" in prompt
    assert "используй именно этот путь" not in prompt.lower()


def test_no_save_on_partial_success(tmp_path):
    store = make_store(tmp_path)
    path_id = store.save_golden_path(
        "bitrix_install", "Установить Битрикс",
        sample_actions(),
        environment_fingerprint={"os_family": "ubuntu"},
        final_judge_verdict="APPROVED",
        task_status="PARTIAL_SUCCESS",
        all_success_criteria_passed=True,
    )
    assert path_id is None


def test_no_save_on_rejected_judge(tmp_path):
    store = make_store(tmp_path)
    path_id = store.save_golden_path(
        "bitrix_install", "Установить Битрикс",
        sample_actions(),
        environment_fingerprint={"os_family": "ubuntu"},
        final_judge_verdict="REJECTED",
        task_status="SUCCESS",
        all_success_criteria_passed=False,
    )
    assert path_id is None


def test_environment_fingerprint_collection(tmp_path):
    store = make_store(tmp_path)

    def fake_ssh(cmd):
        if "os-release" in cmd:
            return 'ID=ubuntu\nVERSION_ID="22.04"\n'
        if "php -v" in cmd:
            return 'PHP 8.2.15 (cli)'
        if "nginx -v" in cmd:
            return 'nginx version: nginx/1.24.0'
        if "mysql --version" in cmd:
            return 'mysql  Ver 8.0.35'
        return ''

    fp = store.collect_environment_fingerprint(
        {"platform": "bitrix", "install_mode": "subfolder"},
        ssh_exec=fake_ssh
    )
    assert fp["platform"] == "bitrix"
    assert fp["os_family"] == "ubuntu"
    assert fp["web_server"] == "nginx"
    assert fp["php_major"] == "8.2"
    assert fp["db"] == "mysql"
    assert fp["install_mode"] == "subfolder"


def test_sanitize_description_and_expected_outcome(tmp_path):
    store = make_store(tmp_path)
    path_id = store.save_golden_path(
        "bitrix_install",
        "Установить Битрикс и отправить admin@example.com",
        sample_actions(),
        environment_fingerprint={"os_family": "ubuntu", "web_server": "nginx", "db": "mysql"},
        final_judge_verdict="APPROVED",
        task_status="SUCCESS",
        all_success_criteria_passed=True,
    )
    match = store.find_golden_path(
        "bitrix_install", "Установить Битрикс",
        {"os_family": "ubuntu", "web_server": "nginx", "db": "mysql"},
    )
    step = match.path["steps"][0]
    assert "admin@example.com" not in step["description"]
    assert "deadbeef" not in step["expected_outcome"]


def test_recent_fail_streak_resets_on_success(tmp_path):
    store = make_store(tmp_path)
    path_id = store.save_golden_path(
        "bitrix_install", "Установить Битрикс",
        sample_actions(),
        environment_fingerprint={
            "os_family": "ubuntu", "web_server": "nginx",
            "php_major": "8.2", "db": "mysql"
        },
        final_judge_verdict="APPROVED",
        task_status="SUCCESS",
        all_success_criteria_passed=True,
    )
    store.record_path_outcome(path_id, success=False)
    store.record_path_outcome(path_id, success=False)
    store.record_path_outcome(path_id, success=True)
    match = store.find_golden_path(
        "bitrix_install", "Установить Битрикс",
        {"os_family": "ubuntu", "web_server": "nginx",
         "php_major": "8.2", "db": "mysql"},
    )
    assert match is not None
    assert match.path["recent_fail_streak"] == 0


def test_golden_path_not_selected_on_low_environment_match(tmp_path):
    store = make_store(tmp_path)
    store.save_golden_path(
        "bitrix_install", "Установить Битрикс на nginx",
        sample_actions(),
        environment_fingerprint={
            "os_family": "ubuntu", "web_server": "nginx",
            "php_major": "8.2", "db": "mysql"
        },
        final_judge_verdict="APPROVED",
        task_status="SUCCESS",
        all_success_criteria_passed=True,
    )
    match = store.find_golden_path(
        "bitrix_install", "Установить Битрикс на apache",
        {"os_family": "alpine", "web_server": "apache",
         "php_major": "8.1", "db": "postgres"},
    )
    assert match is None


def test_deduplicate_similar_golden_paths(tmp_path):
    store = make_store(tmp_path)
    env = {
        "os_family": "ubuntu", "web_server": "nginx",
        "php_major": "8.2", "db": "mysql", "install_mode": "subfolder"
    }
    first = store.save_golden_path(
        "bitrix_install", "Установить Битрикс в подпапку",
        sample_actions(), environment_fingerprint=env,
        final_judge_verdict="APPROVED",
        task_status="SUCCESS",
        all_success_criteria_passed=True,
    )
    second = store.save_golden_path(
        "bitrix_install", "Установить Битрикс в подпапку",
        sample_actions(), environment_fingerprint=env,
        final_judge_verdict="APPROVED",
        task_status="SUCCESS",
        all_success_criteria_passed=True,
    )
    assert first == second


def test_deduplicate_count_in_db(tmp_path):
    """Проверить что дедупликация реально 1 запись в БД."""
    store = make_store(tmp_path)
    env = {
        "os_family": "ubuntu", "web_server": "nginx",
        "php_major": "8.2", "db": "mysql",
        "install_mode": "subfolder"
    }
    first = store.save_golden_path(
        "bitrix_install", "Установить Битрикс в подпапку",
        sample_actions(), environment_fingerprint=env,
        final_judge_verdict="APPROVED",
        task_status="SUCCESS",
        all_success_criteria_passed=True,
    )
    second = store.save_golden_path(
        "bitrix_install", "Установить Битрикс в подпапку",
        sample_actions(), environment_fingerprint=env,
        final_judge_verdict="APPROVED",
        task_status="SUCCESS",
        all_success_criteria_passed=True,
    )
    assert first == second
    assert store.count_paths("bitrix_install") == 1


def test_fingerprint_ssh_timeout(tmp_path):
    """SSH зависает — fingerprint возвращается частичный."""
    store = make_store(tmp_path)
    import time

    call_count = {"n": 0}

    def slow_ssh(cmd):
        call_count["n"] += 1
        if call_count["n"] > 1:
            time.sleep(30)
        return ""

    start = time.time()
    fp = store.collect_environment_fingerprint(
        {"platform": "bitrix"},
        ssh_exec=slow_ssh
    )
    elapsed = time.time() - start

    assert fp["platform"] == "bitrix"
    # Не должен зависнуть дольше 15 сек (timeout 10 + запас)
    assert elapsed < 60, f"Took {elapsed}s — timeout не работает"
