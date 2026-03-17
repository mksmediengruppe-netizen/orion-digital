"""
ORION Orchestrator v2.0 — Умный планировщик
=============================================
Не шаблоны, а LLM который думает как проджект-менеджер.
Понимает ЛЮБУЮ задачу и разбивает на шаги.
Для простых задач — мгновенный ответ без LLM.
Для сложных — вызов DeepSeek для составления плана.
"""

import json
import logging
import os
import time
import re
from typing import Dict, List, Any, Optional

logger = logging.getLogger("orchestrator")

AGENTS_CAPABILITIES = """
Доступные агенты:
1. DESIGNER (Gemini) — HTML/CSS, лендинги, UI/UX, вёрстка, баннеры
2. DEVELOPER (DeepSeek) — Python, Node.js, PHP, API, базы данных, боты, скрипты
3. DEVOPS (DeepSeek) — SSH, nginx, Docker, SSL, DNS, деплой, миграция серверов
4. INTEGRATOR (DeepSeek) — Битрикс24, Telegram, платежи, n8n, вебхуки, CRM
5. TESTER (DeepSeek) — тестирование сайтов, форм, SSL, мобильной версии
6. ANALYST (DeepSeek/Sonnet) — архитектура, анализ, отчёты, code review

Все агенты имеют доступ к: SSH, браузер, файлы, поиск, код.
"""

PLANNER_SYSTEM_PROMPT = """Ты — проджект-менеджер AI-компании ORION Digital.
Составь ПЛАН ВЫПОЛНЕНИЯ задачи.
Пользователь может быть непрофессионалом. Он говорит простым языком.

{agents_capabilities}

ПРАВИЛА:
1. Разбивай на фазы. Если агенты независимы — parallel: true.
2. Designer ВСЕГДА для дизайна (model: gemini).
3. После деплоя ВСЕГДА ставь Tester.
4. Если нужны доступы — укажи в ask_user.
5. Простая задача → mode: "single". Сложная → "multi_sequential" или "multi_parallel".

КОНТЕКСТ: {project_context}

ОТВЕТ — строго JSON:
{{"understanding":"что понял","mode":"single|multi_sequential|multi_parallel","ask_user":null,"phases":[{{"name":"Фаза","agents":["designer"],"parallel":false,"description":"Что делать","model":"gemini|deepseek|sonnet","requires_ssh":false,"expected_output":"html_file|code_file|deployed_site|report"}}],"primary_model":"gemini","primary_agent":"designer","requires_ssh":false,"requires_api_keys":[],"estimated_time":"2-5 мин","warnings":[]}}"""

AGENT_PROMPTS = {
    "designer": """Ты — ведущий веб-дизайнер ORION Digital.
ГЛАВНОЕ: ТЫ СОЗДАЁШЬ, А НЕ ОПИСЫВАЕШЬ.
Создай ПОЛНЫЙ HTML с <style>. Сохрани через create_artifact/file_write.
НЕ ПИШИ код в чат. Google Fonts, адаптив, градиенты, анимации, минимум 5 секций.
Стиль: как Stripe/Linear/Vercel.""",

    "developer": """Ты — senior full-stack разработчик ORION Digital.
ГЛАВНОЕ: ПИШЕШЬ КОД И СОХРАНЯЕШЬ, НЕ ОПИСЫВАЕШЬ.
Сохраняй через file_write. Если есть SSH — выполняй на сервере.
Стек: Python, Node.js, PHP, PostgreSQL, Redis.
НИКОГДА не говори "скопируйте код". СОХРАНЯЙ в файл.""",

    "devops": """Ты — DevOps инженер ORION Digital.
ГЛАВНОЕ: ВЫПОЛНЯЕШЬ ЧЕРЕЗ SSH, НЕ ОПИСЫВАЕШЬ.
Деплой: проверить сервер → загрузить файлы → nginx → SSL → проверить.
Миграция: скачать со старого → загрузить на новый → DNS → проверить.
НИКОГДА не говори "выполните команду". ВЫПОЛНЯЙ через ssh_execute.""",

    "integrator": """Ты — специалист по интеграциям ORION Digital.
ГЛАВНОЕ: ПОДКЛЮЧАЕШЬ API, НЕ ОПИСЫВАЕШЬ.
Битрикс24, Telegram Bot, ЮKassa, Stripe, n8n, вебхуки, CRM.
Запроси API ключи → напиши код → протестируй → сохрани.""",

    "tester": """Ты — QA инженер ORION Digital.
ГЛАВНОЕ: ТЕСТИРУЕШЬ РЕАЛЬНО ЧЕРЕЗ БРАУЗЕР И SSH.
Чеклист: HTTP 200, все страницы, формы, мобильная, SSL, скорость, логи.
Формат: ✅ OK / ❌ Баг с описанием.""",

    "analyst": """Ты — аналитик ORION Digital.
Архитектура, анализ данных, отчёты, code review, ТЗ, документация.
Результаты через generate_file (docx/pdf)."""
}

MODEL_MAP = {
    "gemini": "google/gemini-2.5-pro",
    "deepseek": "deepseek/deepseek-v3.2",
    "sonnet": "anthropic/claude-sonnet-4.6"
}


class Orchestrator:
    def __init__(self, call_llm_func, orion_mode="turbo_standard"):
        self.call_llm = call_llm_func
        self.orion_mode = orion_mode
        self.project_context = ""

    def plan(self, message, chat_history=None, has_ssh=False, ssh_info=""):
        msg = message.lower().strip()

        if self._is_simple_chat(msg):
            return {"mode":"chat","phases":[{"name":"Ответ","agents":["developer"],"model":"deepseek"}],
                    "primary_model":"deepseek","primary_agent":"developer","understanding":"Чат","ask_user":None}

        if self._is_obvious_design(msg):
            return {"mode":"single","phases":[{"name":"Дизайн","agents":["designer"],"model":"gemini",
                    "description":"Создать HTML/CSS","expected_output":"html_file"}],
                    "primary_model":"gemini","primary_agent":"designer","understanding":"Создание веб-страницы","ask_user":None}

        if self._is_obvious_code(msg):
            return {"mode":"single","phases":[{"name":"Разработка","agents":["developer"],"model":"deepseek",
                    "description":"Написать код","expected_output":"code_file"}],
                    "primary_model":"deepseek","primary_agent":"developer","understanding":"Написание кода","ask_user":None}

        return self._llm_plan(message, chat_history, has_ssh, ssh_info)

    def _is_simple_chat(self, msg):
        patterns = [r"^привет",r"^здравствуй",r"^хай",r"^hello",r"^как дела",r"^что ты умеешь",
                    r"^кто ты",r"^расскажи\s+(про|о)",r"^объясни",r"^что такое",r"^почему",
                    r"^спасибо",r"^ок\b",r"^понял",r"^да\b",r"^нет\b"]
        if any(re.search(p, msg) for p in patterns):
            return True
        if len(msg)<30 and not any(w in msg for w in ["сделай","создай","напиши","настрой","подключи","задеплой","перенеси"]):
            return True
        return False

    def _is_obvious_design(self, msg):
        design = any(re.search(w,msg) for w in ["лендинг","landing","страниц.*сайт","баннер","макет","промо","вёрстк","верстк"])
        action = any(re.search(w,msg) for w in ["сделай","создай","нарисуй","сверстай"])
        complex_ = any(w in msg for w in ["битрикс","интеграц","деплой","сервер","api","магазин","корзин","оплат","n8n"])
        return design and action and not complex_

    def _is_obvious_code(self, msg):
        code = any(re.search(w,msg) for w in ["скрипт","функци","парсер","бот.*telegram","cli","утилит"])
        action = any(re.search(w,msg) for w in ["напиши","создай","сделай"])
        complex_ = any(w in msg for w in ["деплой","сервер","интеграц","битрикс"])
        return code and action and not complex_

    def _llm_plan(self, message, chat_history=None, has_ssh=False, ssh_info=""):
        ctx_parts = []
        if self.project_context:
            ctx_parts.append(f"История проекта:\n{self.project_context}")
        ctx_parts.append(f"SSH: {'ДА. '+ssh_info if has_ssh else 'НЕТ'}")
        if chat_history:
            recent = chat_history[-10:]
            ctx_parts.append("Последние сообщения:\n"+"\n".join(f"{m.get('role','?')}: {m.get('content','')[:200]}" for m in recent))
        project_context = "\n\n".join(ctx_parts) or "Новый проект."

        system = PLANNER_SYSTEM_PROMPT.format(agents_capabilities=AGENTS_CAPABILITIES, project_context=project_context)
        messages = [{"role":"system","content":system},{"role":"user","content":f"Задача: {message}"}]

        try:
            response = self.call_llm(messages, model="deepseek/deepseek-v3.2")
            logging.info(f"[Orchestrator] LLM raw response: {response[:3000] if response else 'EMPTY'}")
            plan = self._parse_json(response)
            logging.info(f"[Orchestrator] Parsed plan: {plan}")
            if plan:
                self.project_context += f"\n[{time.strftime('%H:%M')}] {message[:100]}\n"
                return plan
        except Exception as e:
            import traceback
            logging.warning(f"LLM planning failed: {e}")
            logging.warning(f"Orchestrator traceback: {traceback.format_exc()}")

        return {"mode":"single","phases":[{"name":"Выполнение","agents":["developer"],"model":"deepseek"}],
                "primary_model":"deepseek","primary_agent":"developer","understanding":"Fallback","ask_user":None}

    def _parse_json(self, response):
        text = response.strip()
        text = re.sub(r'^```json\s*','',text)
        text = re.sub(r'\s*```$','',text)
        text = re.sub(r'^```\s*','',text)
        # Also handle ``` in middle of text
        text = re.sub(r'```', '', text).strip()
        logging.info(f"[Orchestrator._parse_json] Text after cleanup (first 200): {text[:200]}")
        logging.info(f"[Orchestrator._parse_json] Text after cleanup (last 100): {text[-100:]}")
        try:
            plan = json.loads(text)
            logging.info(f"[Orchestrator._parse_json] json.loads OK, mode={plan.get('mode')}")
            plan.setdefault("phases",[{"name":"Выполнение","agents":["developer"],"model":"deepseek"}])
            plan.setdefault("mode","single" if len(plan["phases"])==1 else "multi_sequential")
            plan.setdefault("primary_model",plan["phases"][0].get("model","deepseek"))
            plan.setdefault("primary_agent",plan["phases"][0].get("agents",["developer"])[0])
            plan.setdefault("ask_user",None)
            # Normalize ask_user: convert objects to strings
            if isinstance(plan.get("ask_user"), list):
                normalized = []
                for item in plan["ask_user"]:
                    if isinstance(item, dict):
                        normalized.append(item.get("question", str(item)))
                    else:
                        normalized.append(str(item))
                plan["ask_user"] = normalized
            return plan
        except json.JSONDecodeError as e:
            logging.warning(f"[Orchestrator._parse_json] JSONDecodeError: {e}")
            logging.warning(f"[Orchestrator._parse_json] Problematic text around error: {text[max(0,e.pos-50):e.pos+50]}")
            match = re.search(r'\{[\s\S]*\}', text)
            if match:
                logging.info(f"[Orchestrator._parse_json] Trying regex match ({len(match.group())} chars)")
                try:
                    plan = json.loads(match.group())
                    logging.info(f"[Orchestrator._parse_json] Regex parse OK")
                    plan.setdefault("phases",[{"name":"Выполнение","agents":["developer"],"model":"deepseek"}])
                    plan.setdefault("mode","single" if len(plan["phases"])==1 else "multi_sequential")
                    plan.setdefault("primary_model",plan["phases"][0].get("model","deepseek"))
                    plan.setdefault("primary_agent",plan["phases"][0].get("agents",["developer"])[0])
                    plan.setdefault("ask_user",None)
                    return plan
                except Exception as e2:
                    logging.warning(f"[Orchestrator._parse_json] Regex parse also failed: {e2}")
            return None

    def update_context(self, result_summary):
        self.project_context += f"\nРезультат: {result_summary[:200]}\n"


def get_model_id(key):
    return MODEL_MAP.get(key, MODEL_MAP["deepseek"])

def get_agent_prompt(key):
    return AGENT_PROMPTS.get(key, AGENT_PROMPTS["developer"])

def get_model_for_agent(agent_key, orion_mode="turbo_standard"):
    if agent_key=="designer": return MODEL_MAP["gemini"]
    if agent_key=="analyst" and "pro" in orion_mode and "premium" in orion_mode: return MODEL_MAP["sonnet"]
    return MODEL_MAP["deepseek"]

def format_plan_sse(plan):
    return {"type":"task_plan","understanding":plan.get("understanding",""),"mode":plan.get("mode","single"),
            "steps":[{"name":p.get("name",""),"agents":p.get("agents",[]),"parallel":p.get("parallel",False),
            "status":"pending","model":p.get("model","deepseek")} for p in plan.get("phases",[])],
            "total_phases":len(plan.get("phases",[])),"primary_model":plan.get("primary_model","deepseek"),
            "requires_ssh":plan.get("requires_ssh",False),"ask_user":plan.get("ask_user"),
            "warnings":plan.get("warnings",[])}
