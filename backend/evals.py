"""
ORION Digital v1.0 — Automated Evaluation Framework
Runs weekly eval suite: 100 prompts across categories, measures quality, latency, tool accuracy.
Generates HTML/JSON report.
"""

import json
import time
import os
import logging
import hashlib
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

# ══════════════════════════════════════════════════════════════
# Eval Prompts — 100 prompts across 10 categories
# ══════════════════════════════════════════════════════════════

EVAL_PROMPTS = {
    "general_knowledge": [
        {"prompt": "Что такое квантовый компьютер?", "expect_keywords": ["кубит", "суперпозиция", "вычисления"], "category": "knowledge"},
        {"prompt": "Объясни теорию относительности простыми словами", "expect_keywords": ["Эйнштейн", "время", "скорость", "свет"], "category": "knowledge"},
        {"prompt": "Какие основные принципы ООП?", "expect_keywords": ["инкапсуляция", "наследование", "полиморфизм"], "category": "knowledge"},
        {"prompt": "Расскажи о блокчейне", "expect_keywords": ["блок", "цепочка", "децентрализ"], "category": "knowledge"},
        {"prompt": "Что такое машинное обучение?", "expect_keywords": ["данные", "модель", "обучение"], "category": "knowledge"},
        {"prompt": "Объясни как работает DNS", "expect_keywords": ["домен", "IP", "сервер"], "category": "knowledge"},
        {"prompt": "Что такое REST API?", "expect_keywords": ["HTTP", "запрос", "ресурс"], "category": "knowledge"},
        {"prompt": "Расскажи о SOLID принципах", "expect_keywords": ["ответственност", "открыт", "замещен"], "category": "knowledge"},
        {"prompt": "Что такое Docker?", "expect_keywords": ["контейнер", "образ", "изоляция"], "category": "knowledge"},
        {"prompt": "Объясни что такое нейронная сеть", "expect_keywords": ["нейрон", "слой", "вес"], "category": "knowledge"},
    ],
    "code_generation": [
        {"prompt": "Напиши функцию на Python для сортировки пузырьком", "expect_keywords": ["def", "for", "swap", "return"], "category": "code", "expect_tool": "code_interpreter"},
        {"prompt": "Напиши класс Stack на Python", "expect_keywords": ["class", "push", "pop", "def"], "category": "code"},
        {"prompt": "Напиши функцию бинарного поиска", "expect_keywords": ["def", "mid", "left", "right"], "category": "code"},
        {"prompt": "Создай REST API на Flask с CRUD для задач", "expect_keywords": ["flask", "route", "GET", "POST"], "category": "code"},
        {"prompt": "Напиши парсер CSV файла на Python", "expect_keywords": ["csv", "open", "read", "def"], "category": "code"},
        {"prompt": "Напиши функцию для валидации email", "expect_keywords": ["def", "re", "pattern", "match"], "category": "code"},
        {"prompt": "Создай декоратор для кэширования результатов", "expect_keywords": ["def", "wrapper", "cache", "functools"], "category": "code"},
        {"prompt": "Напиши асинхронный HTTP клиент на Python", "expect_keywords": ["async", "await", "aiohttp", "def"], "category": "code"},
        {"prompt": "Напиши unit тест для функции сложения", "expect_keywords": ["test", "assert", "def", "unittest"], "category": "code"},
        {"prompt": "Создай простой веб-скрапер на Python", "expect_keywords": ["requests", "BeautifulSoup", "html", "def"], "category": "code"},
    ],
    "file_generation": [
        {"prompt": "Создай Excel файл с таблицей расходов за месяц", "expect_tool": "generate_file", "category": "file"},
        {"prompt": "Сгенерируй PDF отчёт о продажах", "expect_tool": "generate_report", "category": "file"},
        {"prompt": "Создай Word документ с шаблоном резюме", "expect_tool": "generate_file", "category": "file"},
        {"prompt": "Сгенерируй CSV файл с данными о 50 пользователях", "expect_tool": "generate_file", "category": "file"},
        {"prompt": "Создай HTML страницу-портфолио", "expect_tool": "create_artifact", "category": "file"},
        {"prompt": "Сгенерируй JSON конфигурацию для веб-приложения", "expect_tool": "generate_file", "category": "file"},
        {"prompt": "Создай Markdown документ с техническим описанием API", "expect_tool": "generate_file", "category": "file"},
        {"prompt": "Сгенерируй SQL скрипт для создания базы данных интернет-магазина", "expect_tool": "generate_file", "category": "file"},
        {"prompt": "Создай XLSX файл с бюджетом проекта и формулами", "expect_tool": "generate_file", "category": "file"},
        {"prompt": "Сгенерируй PDF презентацию о компании", "expect_tool": "generate_report", "category": "file"},
    ],
    "image_generation": [
        {"prompt": "Нарисуй логотип для IT-компании TechFlow", "expect_tool": "generate_image", "category": "image"},
        {"prompt": "Создай иллюстрацию космического корабля", "expect_tool": "generate_image", "category": "image"},
        {"prompt": "Сгенерируй UI мокап дашборда аналитики", "expect_tool": "generate_image", "category": "image"},
        {"prompt": "Нарисуй диаграмму архитектуры микросервисов", "expect_tool": "generate_image", "category": "image"},
        {"prompt": "Создай баннер для социальных сетей", "expect_tool": "generate_design", "category": "image"},
        {"prompt": "Сгенерируй график роста пользователей за год", "expect_tool": "generate_chart", "category": "image"},
        {"prompt": "Создай визитку для дизайнера", "expect_tool": "generate_design", "category": "image"},
        {"prompt": "Нарисуй блок-схему процесса регистрации", "expect_tool": "generate_image", "category": "image"},
        {"prompt": "Создай лендинг для стартапа", "expect_tool": "create_artifact", "category": "image"},
        {"prompt": "Сгенерируй инфографику о климате", "expect_tool": "generate_design", "category": "image"},
    ],
    "web_search": [
        {"prompt": "Какая погода сейчас в Москве?", "expect_tool": "web_search", "category": "web"},
        {"prompt": "Найди последние новости о SpaceX", "expect_tool": "web_search", "category": "web"},
        {"prompt": "Какой курс доллара к рублю сегодня?", "expect_tool": "web_search", "category": "web"},
        {"prompt": "Найди рецепт борща", "expect_tool": "web_search", "category": "web"},
        {"prompt": "Какие фильмы вышли в этом месяце?", "expect_tool": "web_search", "category": "web"},
        {"prompt": "Найди документацию по FastAPI", "expect_tool": "web_search", "category": "web"},
        {"prompt": "Какие акции Apple сейчас?", "expect_tool": "web_search", "category": "web"},
        {"prompt": "Найди расписание поездов Москва-Петербург", "expect_tool": "web_search", "category": "web"},
        {"prompt": "Какие технологические тренды 2026 года?", "expect_tool": "web_search", "category": "web"},
        {"prompt": "Найди статистику по COVID-19", "expect_tool": "web_search", "category": "web"},
    ],
    "data_analysis": [
        {"prompt": "Проанализируй данные: [10, 25, 30, 45, 50, 65, 80]. Найди среднее, медиану, стандартное отклонение", "expect_tool": "code_interpreter", "category": "analysis"},
        {"prompt": "Построй график функции y = x^2 + 2x - 3 на интервале [-5, 5]", "expect_tool": "code_interpreter", "category": "analysis"},
        {"prompt": "Создай pie chart распределения бюджета: Маркетинг 30%, Разработка 40%, Операции 20%, HR 10%", "expect_tool": "generate_chart", "category": "analysis"},
        {"prompt": "Посчитай ROI если вложили 100000 и получили 150000", "expect_keywords": ["50%", "ROI", "прибыль"], "category": "analysis"},
        {"prompt": "Создай таблицу сравнения Python vs JavaScript vs Go", "expect_keywords": ["Python", "JavaScript", "Go"], "category": "analysis"},
        {"prompt": "Проведи SWOT анализ для стартапа по доставке еды", "expect_keywords": ["сильные", "слабые", "возможности", "угрозы"], "category": "analysis"},
        {"prompt": "Посчитай сложный процент: 1000000 руб, 12% годовых, 5 лет", "expect_keywords": ["процент", "итого", "год"], "category": "analysis"},
        {"prompt": "Создай bar chart с продажами по месяцам", "expect_tool": "generate_chart", "category": "analysis"},
        {"prompt": "Проанализируй A/B тест: группа A - 1000 юзеров, 50 конверсий; группа B - 1000 юзеров, 75 конверсий", "expect_keywords": ["конверсия", "статистич", "значим"], "category": "analysis"},
        {"prompt": "Построй линейную регрессию для данных: x=[1,2,3,4,5], y=[2.1, 4.0, 5.9, 8.1, 10.0]", "expect_tool": "code_interpreter", "category": "analysis"},
    ],
    "creative_writing": [
        {"prompt": "Напиши стихотворение о программировании", "expect_keywords": ["код", "программ"], "category": "creative"},
        {"prompt": "Придумай слоган для кофейни", "category": "creative"},
        {"prompt": "Напиши короткий рассказ о роботе", "expect_keywords": ["робот"], "category": "creative"},
        {"prompt": "Создай описание вакансии Python разработчика", "expect_keywords": ["Python", "опыт", "требования"], "category": "creative"},
        {"prompt": "Напиши пост для LinkedIn о важности тестирования", "expect_keywords": ["тест", "качеств"], "category": "creative"},
        {"prompt": "Придумай 5 названий для мобильного приложения для фитнеса", "category": "creative"},
        {"prompt": "Напиши email клиенту о задержке проекта", "expect_keywords": ["уважаем", "сроки", "извин"], "category": "creative"},
        {"prompt": "Создай описание продукта для маркетплейса", "category": "creative"},
        {"prompt": "Напиши техническое задание для разработки чат-бота", "expect_keywords": ["требования", "функцион"], "category": "creative"},
        {"prompt": "Придумай сценарий для рекламного ролика", "category": "creative"},
    ],
    "math_logic": [
        {"prompt": "Реши уравнение: 2x + 5 = 15", "expect_keywords": ["x", "5"], "category": "math"},
        {"prompt": "Найди производную функции f(x) = 3x^3 + 2x^2 - x + 7", "expect_keywords": ["9x", "4x", "1"], "category": "math"},
        {"prompt": "Посчитай факториал 10", "expect_keywords": ["3628800"], "category": "math"},
        {"prompt": "Реши систему уравнений: x + y = 10, 2x - y = 5", "expect_keywords": ["x", "y", "5"], "category": "math"},
        {"prompt": "Найди площадь круга с радиусом 7", "expect_keywords": ["153", "π"], "category": "math"},
        {"prompt": "Посчитай интеграл от 0 до 1 функции x^2", "expect_keywords": ["1/3", "0.33"], "category": "math"},
        {"prompt": "Сколько будет 2^20?", "expect_keywords": ["1048576"], "category": "math"},
        {"prompt": "Найди НОД(48, 36)", "expect_keywords": ["12"], "category": "math"},
        {"prompt": "Реши неравенство: 3x - 7 > 8", "expect_keywords": ["x", "5"], "category": "math"},
        {"prompt": "Посчитай определитель матрицы [[1,2],[3,4]]", "expect_keywords": ["-2"], "category": "math"},
    ],
    "translation": [
        {"prompt": "Переведи на английский: Искусственный интеллект меняет мир", "expect_keywords": ["artificial", "intelligence", "world"], "category": "translation"},
        {"prompt": "Translate to Russian: Machine learning is a subset of artificial intelligence", "expect_keywords": ["машинное", "обучение", "искусственн"], "category": "translation"},
        {"prompt": "Переведи на английский: Программирование — это искусство решения задач", "expect_keywords": ["programming", "art", "solving"], "category": "translation"},
        {"prompt": "Translate to Russian: The quick brown fox jumps over the lazy dog", "expect_keywords": ["быстр", "лис", "собак"], "category": "translation"},
        {"prompt": "Переведи на английский: Данные — это новая нефть", "expect_keywords": ["data", "new", "oil"], "category": "translation"},
        {"prompt": "Translate to Russian: Cloud computing enables scalable infrastructure", "expect_keywords": ["облачн", "масштабируем", "инфраструктур"], "category": "translation"},
        {"prompt": "Переведи технический текст: API — это интерфейс программирования приложений", "expect_keywords": ["API", "application", "programming", "interface"], "category": "translation"},
        {"prompt": "Translate: DevOps combines development and operations", "expect_keywords": ["разработк", "операци"], "category": "translation"},
        {"prompt": "Переведи на английский: Безопасность данных — приоритет номер один", "expect_keywords": ["data", "security", "priority"], "category": "translation"},
        {"prompt": "Translate to Russian: Agile methodology improves project delivery", "expect_keywords": ["Agile", "проект", "улучша"], "category": "translation"},
    ],
    "tool_selection": [
        {"prompt": "Открой сайт google.com и скажи что там", "expect_tool": "web_fetch", "category": "tool"},
        {"prompt": "Запомни что мой любимый язык — Python", "expect_tool": "store_memory", "category": "tool"},
        {"prompt": "Создай canvas документ с планом проекта", "expect_tool": "canvas_create", "category": "tool"},
        {"prompt": "Выполни код: print(sum(range(100)))", "expect_tool": "code_interpreter", "category": "tool"},
        {"prompt": "Найди в интернете что такое Kubernetes", "expect_tool": "web_search", "category": "tool"},
        {"prompt": "Сгенерируй отчёт о продажах в PDF", "expect_tool": "generate_report", "category": "tool"},
        {"prompt": "Создай файл Excel с бюджетом", "expect_tool": "generate_file", "category": "tool"},
        {"prompt": "Нарисуй логотип компании", "expect_tool": "generate_image", "category": "tool"},
        {"prompt": "Создай интерактивный дашборд", "expect_tool": "create_artifact", "category": "tool"},
        {"prompt": "Сделай дизайн лендинга", "expect_tool": "generate_design", "category": "tool"},
    ],
}


# ══════════════════════════════════════════════════════════════
# Eval Runner
# ══════════════════════════════════════════════════════════════

class EvalResult:
    """Result of a single eval."""
    def __init__(self, prompt_data, response_text, tools_used, latency_ms, error=None):
        self.prompt = prompt_data.get("prompt", "")
        self.category = prompt_data.get("category", "unknown")
        self.response = response_text
        self.tools_used = tools_used
        self.latency_ms = latency_ms
        self.error = error
        self.scores = {}
        self._evaluate(prompt_data)

    def _evaluate(self, prompt_data):
        """Score the response."""
        # Keyword match score
        keywords = prompt_data.get("expect_keywords", [])
        if keywords:
            response_lower = self.response.lower()
            matched = sum(1 for kw in keywords if kw.lower() in response_lower)
            self.scores["keyword_match"] = matched / len(keywords) if keywords else 0
        else:
            self.scores["keyword_match"] = 1.0  # No keywords to check

        # Tool selection score
        expect_tool = prompt_data.get("expect_tool")
        if expect_tool:
            self.scores["tool_selection"] = 1.0 if expect_tool in self.tools_used else 0.0
        else:
            self.scores["tool_selection"] = 1.0  # No tool expected

        # Response quality (basic heuristics)
        self.scores["has_response"] = 1.0 if len(self.response) > 20 else 0.0
        self.scores["no_error"] = 0.0 if self.error else 1.0

        # Latency score (under 10s = 1.0, under 30s = 0.5, over 30s = 0.0)
        if self.latency_ms < 10000:
            self.scores["latency"] = 1.0
        elif self.latency_ms < 30000:
            self.scores["latency"] = 0.5
        else:
            self.scores["latency"] = 0.0

        # Overall score
        weights = {"keyword_match": 0.3, "tool_selection": 0.25, "has_response": 0.2, "no_error": 0.15, "latency": 0.1}
        self.scores["overall"] = sum(self.scores.get(k, 0) * v for k, v in weights.items())

    @property
    def passed(self):
        return self.scores.get("overall", 0) >= 0.6

    def to_dict(self):
        return {
            "prompt": self.prompt,
            "category": self.category,
            "response_length": len(self.response),
            "tools_used": self.tools_used,
            "latency_ms": self.latency_ms,
            "scores": self.scores,
            "passed": self.passed,
            "error": self.error,
        }


class EvalRunner:
    """Run evaluation suite against the agent."""

    def __init__(self, api_base_url="http://localhost:3501", api_key=None):
        self.api_base = api_base_url.rstrip("/")
        self.api_key = api_key
        self.results = []
        self.report_dir = os.environ.get("EVAL_REPORTS_DIR", "/var/www/orion/backend/eval_reports")

    def run_all(self, max_prompts=None):
        """Run all eval prompts."""
        import requests

        all_prompts = []
        for category, prompts in EVAL_PROMPTS.items():
            for p in prompts:
                all_prompts.append(p)

        if max_prompts:
            all_prompts = all_prompts[:max_prompts]

        logger.info(f"Running {len(all_prompts)} eval prompts...")

        for i, prompt_data in enumerate(all_prompts):
            try:
                result = self._run_single(prompt_data, i + 1, len(all_prompts))
                self.results.append(result)
            except Exception as e:
                logger.error(f"Eval {i+1} failed: {e}")
                self.results.append(EvalResult(
                    prompt_data, "", [], 0, error=str(e)
                ))

        return self._generate_report()

    def _run_single(self, prompt_data, index, total):
        """Run a single eval prompt."""
        import requests

        prompt = prompt_data["prompt"]
        logger.info(f"[{index}/{total}] {prompt[:60]}...")

        # Create a chat
        try:
            create_resp = requests.post(
                f"{self.api_base}/api/chats",
                json={"title": f"Eval #{index}"},
                timeout=10
            )
            chat_data = create_resp.json()
            chat_id = chat_data.get("id") or chat_data.get("chat_id", f"eval-{index}")
        except Exception:
            chat_id = f"eval-{index}"

        # Send message and measure latency
        start_time = time.time()
        response_text = ""
        tools_used = []
        error = None

        try:
            resp = requests.post(
                f"{self.api_base}/api/chat",
                json={
                    "message": prompt,
                    "chat_id": chat_id,
                    "model": "openai/gpt-4o-mini",
                    "mode": "agent",
                },
                timeout=120,
                stream=True
            )

            for line in resp.iter_lines():
                if line:
                    line_str = line.decode("utf-8", errors="replace")
                    if line_str.startswith("data: "):
                        try:
                            data = json.loads(line_str[6:])
                            event_type = data.get("type", "")
                            if event_type == "text":
                                response_text += data.get("content", "")
                            elif event_type == "tool_start":
                                tool_name = data.get("tool", "")
                                if tool_name:
                                    tools_used.append(tool_name)
                            elif event_type == "error":
                                error = data.get("content", "Unknown error")
                        except json.JSONDecodeError:
                            pass
        except Exception as e:
            error = str(e)

        latency_ms = int((time.time() - start_time) * 1000)

        return EvalResult(prompt_data, response_text, tools_used, latency_ms, error)

    def _generate_report(self):
        """Generate eval report."""
        os.makedirs(self.report_dir, exist_ok=True)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        # Category stats
        categories = {}
        for r in self.results:
            cat = r.category
            if cat not in categories:
                categories[cat] = {"total": 0, "passed": 0, "scores": [], "latencies": []}
            categories[cat]["total"] += 1
            if r.passed:
                categories[cat]["passed"] += 1
            categories[cat]["scores"].append(r.scores.get("overall", 0))
            categories[cat]["latencies"].append(r.latency_ms)

        total = len(self.results)
        passed = sum(1 for r in self.results if r.passed)
        avg_score = sum(r.scores.get("overall", 0) for r in self.results) / max(total, 1)
        avg_latency = sum(r.latency_ms for r in self.results) / max(total, 1)

        report = {
            "timestamp": timestamp,
            "version": "6.0",
            "summary": {
                "total_prompts": total,
                "passed": passed,
                "failed": total - passed,
                "pass_rate": round(passed / max(total, 1) * 100, 1),
                "avg_score": round(avg_score, 3),
                "avg_latency_ms": round(avg_latency),
            },
            "categories": {},
            "results": [r.to_dict() for r in self.results],
        }

        for cat, stats in categories.items():
            report["categories"][cat] = {
                "total": stats["total"],
                "passed": stats["passed"],
                "pass_rate": round(stats["passed"] / max(stats["total"], 1) * 100, 1),
                "avg_score": round(sum(stats["scores"]) / max(len(stats["scores"]), 1), 3),
                "avg_latency_ms": round(sum(stats["latencies"]) / max(len(stats["latencies"]), 1)),
            }

        # Save JSON report
        json_path = os.path.join(self.report_dir, f"eval_{timestamp}.json")
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)

        # Save HTML report
        html_path = os.path.join(self.report_dir, f"eval_{timestamp}.html")
        self._generate_html_report(report, html_path)

        logger.info(f"Eval complete: {passed}/{total} passed ({report['summary']['pass_rate']}%)")
        logger.info(f"Reports: {json_path}, {html_path}")

        return report

    def _generate_html_report(self, report, path):
        """Generate HTML eval report."""
        summary = report["summary"]
        categories = report["categories"]

        cat_rows = ""
        for cat, stats in sorted(categories.items()):
            color = "#4ade80" if stats["pass_rate"] >= 80 else "#fbbf24" if stats["pass_rate"] >= 60 else "#f87171"
            cat_rows += f"""
            <tr>
                <td>{cat}</td>
                <td>{stats['passed']}/{stats['total']}</td>
                <td style="color:{color};font-weight:bold">{stats['pass_rate']}%</td>
                <td>{stats['avg_score']:.3f}</td>
                <td>{stats['avg_latency_ms']}ms</td>
            </tr>"""

        failed_rows = ""
        for r in report["results"]:
            if not r["passed"]:
                failed_rows += f"""
                <tr>
                    <td>{r['category']}</td>
                    <td>{r['prompt'][:80]}</td>
                    <td>{r['scores'].get('overall', 0):.2f}</td>
                    <td>{r.get('error', '-') or '-'}</td>
                </tr>"""

        html = f"""<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="UTF-8">
    <title>ORION Digital v1.0 Eval Report — {report['timestamp']}</title>
    <style>
        body {{ font-family: -apple-system, BlinkMacSystemFont, sans-serif; background: #0f172a; color: #e2e8f0; padding: 2rem; }}
        h1 {{ color: #38bdf8; }}
        .summary {{ display: grid; grid-template-columns: repeat(5, 1fr); gap: 1rem; margin: 2rem 0; }}
        .card {{ background: #1e293b; padding: 1.5rem; border-radius: 12px; text-align: center; }}
        .card .value {{ font-size: 2rem; font-weight: bold; color: #38bdf8; }}
        .card .label {{ color: #94a3b8; margin-top: 0.5rem; }}
        table {{ width: 100%; border-collapse: collapse; margin: 1rem 0; }}
        th, td {{ padding: 0.75rem; text-align: left; border-bottom: 1px solid #334155; }}
        th {{ background: #1e293b; color: #94a3b8; }}
        tr:hover {{ background: #1e293b; }}
        .pass {{ color: #4ade80; }} .fail {{ color: #f87171; }}
    </style>
</head>
<body>
    <h1>🧪 ORION Digital v1.0 — Eval Report</h1>
    <p>Timestamp: {report['timestamp']} | Version: {report['version']}</p>

    <div class="summary">
        <div class="card"><div class="value">{summary['total_prompts']}</div><div class="label">Total Prompts</div></div>
        <div class="card"><div class="value class="pass"">{summary['passed']}</div><div class="label">Passed</div></div>
        <div class="card"><div class="value" style="color:{'#4ade80' if summary['pass_rate']>=80 else '#fbbf24'}">{summary['pass_rate']}%</div><div class="label">Pass Rate</div></div>
        <div class="card"><div class="value">{summary['avg_score']:.3f}</div><div class="label">Avg Score</div></div>
        <div class="card"><div class="value">{summary['avg_latency_ms']}ms</div><div class="label">Avg Latency</div></div>
    </div>

    <h2>📊 Results by Category</h2>
    <table>
        <tr><th>Category</th><th>Passed</th><th>Pass Rate</th><th>Avg Score</th><th>Avg Latency</th></tr>
        {cat_rows}
    </table>

    <h2>❌ Failed Tests</h2>
    <table>
        <tr><th>Category</th><th>Prompt</th><th>Score</th><th>Error</th></tr>
        {failed_rows if failed_rows else '<tr><td colspan="4" style="text-align:center;color:#4ade80">All tests passed!</td></tr>'}
    </table>
</body>
</html>"""

        with open(path, "w", encoding="utf-8") as f:
            f.write(html)


# ══════════════════════════════════════════════════════════════
# CLI Entry Point
# ══════════════════════════════════════════════════════════════

def run_evals(api_base="http://localhost:3501", max_prompts=None):
    """Run evals from command line."""
    runner = EvalRunner(api_base_url=api_base)
    report = runner.run_all(max_prompts=max_prompts)
    return report


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="ORION Digital v1.0 Eval Runner")
    parser.add_argument("--api-base", default="http://localhost:3501", help="API base URL")
    parser.add_argument("--max-prompts", type=int, default=None, help="Max prompts to run")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO)
    report = run_evals(args.api_base, args.max_prompts)
    print(f"\n{'='*60}")
    print(f"  EVAL COMPLETE: {report['summary']['passed']}/{report['summary']['total_prompts']} passed ({report['summary']['pass_rate']}%)")
    print(f"{'='*60}")
