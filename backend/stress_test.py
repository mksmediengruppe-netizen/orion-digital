"""
ORION Stress Test Framework
============================
Tests parallel task execution with 10-20 concurrent tasks.
Measures response times, error rates, and resource usage.
"""

import requests
import threading
import time
import json
import statistics
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import List, Dict, Optional

@dataclass
class TestResult:
    task_id: int
    chat_id: str = ""
    status: str = "pending"
    response_time: float = 0.0
    first_token_time: float = 0.0
    tokens_received: int = 0
    error: str = ""

@dataclass
class StressTestReport:
    total_tasks: int = 0
    successful: int = 0
    failed: int = 0
    avg_response_time: float = 0.0
    p50_response_time: float = 0.0
    p95_response_time: float = 0.0
    p99_response_time: float = 0.0
    avg_first_token: float = 0.0
    total_duration: float = 0.0
    tasks_per_second: float = 0.0
    results: List[TestResult] = field(default_factory=list)


class OrionStressTest:
    """Stress test framework for ORION Digital."""

    def __init__(self, base_url: str, email: str, password: str):
        self.base_url = base_url.rstrip("/")
        self.email = email
        self.password = password
        self.token: Optional[str] = None
        self.session = requests.Session()

    def login(self) -> bool:
        """Authenticate and get token."""
        try:
            resp = self.session.post(
                f"{self.base_url}/api/auth/login",
                json={"email": self.email, "password": self.password},
                timeout=10,
            )
            data = resp.json()
            self.token = data.get("token")
            return bool(self.token)
        except Exception as e:
            print(f"Login failed: {e}")
            return False

    def _headers(self) -> Dict:
        return {"Authorization": f"Bearer {self.token}", "Content-Type": "application/json"}

    def _create_chat(self, title: str) -> Optional[str]:
        """Create a new chat and return its ID."""
        try:
            resp = requests.post(
                f"{self.base_url}/api/chats",
                headers=self._headers(),
                json={"title": title},
                timeout=10,
            )
            return resp.json().get("chat", {}).get("id")
        except:
            return None

    def _send_message(self, chat_id: str, message: str, mode: str = "fast") -> TestResult:
        """Send a message and measure response metrics."""
        result = TestResult(task_id=0, chat_id=chat_id)
        start = time.time()
        first_token = None
        tokens = 0

        try:
            resp = requests.post(
                f"{self.base_url}/api/chats/{chat_id}/send",
                headers=self._headers(),
                json={"message": message, "mode": mode},
                stream=True,
                timeout=60,
            )

            for line in resp.iter_lines(decode_unicode=True):
                if not line or not line.startswith("data:"):
                    continue
                if first_token is None:
                    first_token = time.time() - start
                tokens += 1

                try:
                    payload = json.loads(line[5:].strip())
                    if payload.get("type") == "done":
                        break
                except:
                    pass

            result.response_time = time.time() - start
            result.first_token_time = first_token or result.response_time
            result.tokens_received = tokens
            result.status = "success" if tokens > 0 else "empty"

        except Exception as e:
            result.response_time = time.time() - start
            result.status = "error"
            result.error = str(e)

        return result

    def run_stress_test(
        self,
        num_tasks: int = 10,
        mode: str = "fast",
        messages: List[str] = None,
    ) -> StressTestReport:
        """
        Run a stress test with N parallel tasks.
        """
        if not self.token:
            if not self.login():
                raise RuntimeError("Cannot login")

        if messages is None:
            messages = [
                "Сколько будет 2+2?",
                "Что такое Python?",
                "Напиши Hello World на JavaScript",
                "Объясни что такое Docker",
                "Какие есть типы данных в Python?",
                "Что такое REST API?",
                "Напиши функцию сортировки на Python",
                "Что такое Git?",
                "Объясни паттерн MVC",
                "Что такое SQL?",
                "Напиши CSS для центрирования div",
                "Что такое JSON?",
                "Объясни HTTP методы",
                "Что такое WebSocket?",
                "Напиши регулярное выражение для email",
                "Что такое Redis?",
                "Объясни SOLID принципы",
                "Что такое Kubernetes?",
                "Напиши Dockerfile для Python приложения",
                "Что такое GraphQL?",
            ]

        report = StressTestReport(total_tasks=num_tasks)
        print(f"\n{'='*60}")
        print(f"ORION STRESS TEST — {num_tasks} parallel tasks ({mode} mode)")
        print(f"{'='*60}")

        # Phase 1: Create all chats
        print(f"\n[1/3] Creating {num_tasks} chats...")
        chat_ids = []
        for i in range(num_tasks):
            cid = self._create_chat(f"Stress Test #{i+1}")
            if cid:
                chat_ids.append(cid)
            else:
                print(f"  WARNING: Failed to create chat {i+1}")
        print(f"  Created {len(chat_ids)}/{num_tasks} chats")

        if not chat_ids:
            print("FATAL: No chats created!")
            return report

        # Phase 2: Send all messages in parallel
        print(f"\n[2/3] Sending {len(chat_ids)} messages in parallel...")
        start_time = time.time()

        def task_worker(idx):
            cid = chat_ids[idx]
            msg = messages[idx % len(messages)]
            result = self._send_message(cid, msg, mode)
            result.task_id = idx + 1
            return result

        results = []
        with ThreadPoolExecutor(max_workers=min(num_tasks, 20)) as executor:
            futures = {executor.submit(task_worker, i): i for i in range(len(chat_ids))}
            for future in as_completed(futures):
                result = future.result()
                results.append(result)
                status_icon = "✅" if result.status == "success" else "❌"
                print(f"  {status_icon} Task {result.task_id}: {result.response_time:.2f}s, "
                      f"first_token: {result.first_token_time:.2f}s, "
                      f"tokens: {result.tokens_received}")

        total_time = time.time() - start_time

        # Phase 3: Calculate statistics
        print(f"\n[3/3] Calculating statistics...")
        report.results = sorted(results, key=lambda r: r.task_id)
        report.successful = sum(1 for r in results if r.status == "success")
        report.failed = sum(1 for r in results if r.status != "success")
        report.total_duration = total_time

        response_times = [r.response_time for r in results if r.status == "success"]
        first_tokens = [r.first_token_time for r in results if r.status == "success"]

        if response_times:
            report.avg_response_time = statistics.mean(response_times)
            sorted_rt = sorted(response_times)
            n = len(sorted_rt)
            report.p50_response_time = sorted_rt[int(n * 0.5)]
            report.p95_response_time = sorted_rt[min(int(n * 0.95), n - 1)]
            report.p99_response_time = sorted_rt[min(int(n * 0.99), n - 1)]

        if first_tokens:
            report.avg_first_token = statistics.mean(first_tokens)

        report.tasks_per_second = len(chat_ids) / total_time if total_time > 0 else 0

        # Print report
        print(f"\n{'='*60}")
        print(f"STRESS TEST REPORT")
        print(f"{'='*60}")
        print(f"  Total tasks:      {report.total_tasks}")
        print(f"  Successful:       {report.successful}")
        print(f"  Failed:           {report.failed}")
        print(f"  Success rate:     {report.successful/max(len(results),1)*100:.1f}%")
        print(f"  Total duration:   {report.total_duration:.2f}s")
        print(f"  Tasks/second:     {report.tasks_per_second:.2f}")
        print(f"  Avg response:     {report.avg_response_time:.2f}s")
        print(f"  P50 response:     {report.p50_response_time:.2f}s")
        print(f"  P95 response:     {report.p95_response_time:.2f}s")
        print(f"  P99 response:     {report.p99_response_time:.2f}s")
        print(f"  Avg first token:  {report.avg_first_token:.2f}s")
        print(f"{'='*60}")

        return report

    def to_json(self, report: StressTestReport) -> str:
        """Convert report to JSON."""
        return json.dumps({
            "total_tasks": report.total_tasks,
            "successful": report.successful,
            "failed": report.failed,
            "success_rate": f"{report.successful/max(report.total_tasks,1)*100:.1f}%",
            "total_duration_s": round(report.total_duration, 2),
            "tasks_per_second": round(report.tasks_per_second, 2),
            "avg_response_s": round(report.avg_response_time, 2),
            "p50_response_s": round(report.p50_response_time, 2),
            "p95_response_s": round(report.p95_response_time, 2),
            "p99_response_s": round(report.p99_response_time, 2),
            "avg_first_token_s": round(report.avg_first_token, 2),
            "results": [
                {
                    "task_id": r.task_id,
                    "status": r.status,
                    "response_time": round(r.response_time, 2),
                    "first_token_time": round(r.first_token_time, 2),
                    "tokens": r.tokens_received,
                    "error": r.error,
                }
                for r in report.results
            ],
        }, indent=2, ensure_ascii=False)


if __name__ == "__main__":
    base_url = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:3510"
    num = int(sys.argv[2]) if len(sys.argv) > 2 else 10

    tester = OrionStressTest(base_url, "admin@orion.ai", "admin123")
    report = tester.run_stress_test(num_tasks=num, mode="fast")

    # Save report
    with open("/tmp/stress_test_report.json", "w") as f:
        f.write(tester.to_json(report))
    print(f"\nReport saved to /tmp/stress_test_report.json")
