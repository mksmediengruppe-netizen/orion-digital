"""
SuperMemoryEngine v9.1 — объединяет ВСЕ 26 компонентов памяти + Structured State.
Единая точка входа для agent_loop.py и app.py.

v9.1: Интеграция с Structured State (§2.2 спеки Arcane 2).
  - state.json — source of truth проекта
  - PROJECT.md генерируется автоматически
  - Релевантный срез state подаётся в каждый LLM-запрос

Использование:
    from memory_v9 import SuperMemoryEngine

    # В AgentLoop.__init__:
    self.memory = SuperMemoryEngine(call_llm_func=self._call_ai_simple)

    # Перед работой:
    self.memory.init_task(user_message, file_content, user_id, chat_id, api_key, api_url,
                          project_path="/root/workspace/projects/abc123")
    messages = self.memory.build_messages(system_prompt, chat_history, user_message, file_content, ssh_creds)

    # В while-цикле:
    messages = self.memory.before_iteration(messages, iteration, max_iter)
    # ... _call_ai_stream ...
    # ... _execute_tool ...
    result_str = self.memory.after_tool(tool_name, tool_args, result, preview)

    # После завершения:
    self.memory.after_chat(user_message, full_response, chat_id, success)
"""

import json, logging, time
from typing import List, Dict, Optional
from .config import MemoryConfig
from .working import TaskPlanner, GoalAnchor, Scratchpad, ContextCompactor, SmartHistory, SmartToolOutput
from .session import SessionMemory
from .semantic import get_semantic
from .learning import ToolLearning, ErrorPatterns, EpisodicReplay, SelfReflection
from .graph import KnowledgeGraph
from .profile import UserProfile
from .knowledge import get_knowledge_base
from .temporal import get_temporal
from .predictive import ContextBudget, PredictivePreload
from .lifecycle import ConflictResolver
from .collaborative import SharedMemory
# ── Safe stubs (disabled modules) ─────────────────────────────────────────
# dynamic_tools  — DISABLED: subprocess exec of AI-generated code = security risk
# finetuning     — DISABLED: requires GPU + unsloth/axolotl (not installed)
# cross_learning — DISABLED by default; enable: ARCANE_CROSS_LEARNING=true
import os as _os_eng
_CROSS_LEARNING_ENABLED = _os_eng.environ.get("ARCANE_CROSS_LEARNING", "false").lower() == "true"

class DynamicToolManager:
    @staticmethod
    def check_and_generate(*a, **kw): pass

class ToolGenerator:
    @staticmethod
    def get_tools_schema(*a, **kw): return []
    @staticmethod
    def execute(*a, **kw): return {"ok": False, "error": "dynamic tools disabled"}

class CrossUserLearning:
    @staticmethod
    def get_prompt_suggestions(*a, **kw): return None
    @staticmethod
    def record_command_pair(*a, **kw): pass
    @staticmethod
    def record_tool_sequence(*a, **kw): pass
    @staticmethod
    def suggest_error_fix(*a, **kw): return None

class DatasetExporter:
    @staticmethod
    def export_all(): return []

class FineTuner:
    @staticmethod
    def train(*a, **kw): raise NotImplementedError("GPU required for fine-tuning")

class InferenceRouter:
    @staticmethod
    def should_use_finetuned(*a, **kw): return False

from .structured_state import StructuredState

logger = logging.getLogger("memory.engine")


class SuperMemoryEngine:
    """Единый интерфейс ко всей системе памяти + Structured State."""

    def __init__(self, call_llm_func=None, enable_planner: bool = True):
        self._call_llm = call_llm_func
        self._enable_planner = enable_planner

        # L1: Working
        self.planner = None
        self.anchor = None
        self.scratchpad = None
        self.compactor = ContextCompactor(call_llm_func)
        self.budget = ContextBudget()

        # Structured State (§2.2 Arcane 2)
        self.structured_state: Optional[StructuredState] = None
        self._project_path = None

        # Context
        self._user_id = None
        self._chat_id = None
        self._api_key = ""
        self._api_url = ""
        self._profile = None
        self._task_start_time = None

    # ══════════════════════════════════════════════════════════
    # INIT — вызвать один раз перед началом задачи
    # ══════════════════════════════════════════════════════════

    def init_task(self, user_message: str, file_content: str = "",
                  user_id: str = None, chat_id: str = None,
                  api_key: str = "", api_url: str = "",
                  ssh_host: str = "", project_path: str = ""):
        """Инициализация перед новой задачей."""
        self._user_id = user_id
        self._chat_id = chat_id
        self._api_key = api_key
        self._api_url = api_url
        self._task_start_time = time.time()
        self._project_path = project_path

        # Structured State (§2.2): загрузить source of truth проекта
        if project_path:
            try:
                self.structured_state = StructuredState(project_path)
                self.structured_state.load()
                logger.info(f"Structured state loaded for project: {project_path}")
            except Exception as e:
                logger.warning(f"Failed to load structured state: {e}")
                self.structured_state = None

        # Scratchpad
        self.scratchpad = Scratchpad(chat_id=chat_id)

        # Task Planner
        if self._enable_planner and self._call_llm:
            self.planner = TaskPlanner(self._call_llm)
            self.planner.create_plan(user_message, file_content)

        # Goal Anchor
        self.anchor = GoalAnchor(user_message, self.planner)

        # User Profile
        try:
            self._profile = UserProfile(user_id or "default")
            self._profile.increment_chats()
        except: self._profile = None

        # Check for interrupted task (Conversation Continuity)
        try:
            interrupted = SessionMemory.get_interrupted(user_id or "default")
            if interrupted and "продолж" in user_message.lower():
                # Восстановить контекст прерванной задачи
                self.scratchpad.update(
                    f"ПРЕРВАННАЯ ЗАДАЧА (продолжение):\n"
                    f"Задача: {interrupted.get('task','')[:500]}\n"
                    f"Прогресс: {interrupted.get('progress','')[:500]}\n"
                    f"Был на итерации: {interrupted.get('iteration','?')}"
                )
                SessionMemory.clear_interrupted(user_id or "default")
        except: pass

    # ══════════════════════════════════════════════════════════
    # BUILD MESSAGES — заменяет run_stream строки 2025-2042
    # ══════════════════════════════════════════════════════════

    def build_messages(self, system_prompt: str, chat_history: List[Dict],
                       user_message: str, file_content: str = "",
                       ssh_credentials: Dict = None) -> List[Dict]:
        """Построить начальный массив messages со всеми слоями памяти."""
        full_system = system_prompt

        # L5: User Profile
        if self._profile:
            ctx = self._profile.get_prompt_context()
            if ctx: full_system += f"\n\n{ctx}"

        # Structured State — тёплый слой (§9.1), source of truth (§2.2)
        # Подаём релевантный срез, не весь файл
        if self.structured_state:
            try:
                state_slice = self.structured_state.get_relevant_slice(
                    user_message=user_message,
                    task_type=self._detect_task_type(user_message)
                )
                if state_slice:
                    full_system += f"\n\n{state_slice}"
            except Exception as e:
                logger.debug(f"Structured state slice failed: {e}")

        # L3: Semantic Memory (vector search + re-ranking)
        try:
            sem = get_semantic()
            results = sem.search(user_message, limit=MemoryConfig.MEMORY_MAX_ITEMS * 2,
                                 user_id=self._user_id)
            if results and MemoryConfig.MEMORY_RERANK and self._call_llm:
                results = sem.rerank(results, user_message, self._call_llm)
            results = ConflictResolver.resolve(results)
            if results:
                parts = ["КОНТЕКСТ ИЗ ПАМЯТИ:"]
                for r in results[:MemoryConfig.MEMORY_MAX_ITEMS]:
                    label = {"episodic":"Опыт","semantic":"Факт","procedural":"Навык",
                             "knowledge":"Документ","shared":"Команда","visual":"Скриншот"
                             }.get(r.get("type",""), "Заметка")
                    parts.append(f"  [{label}] {r['content'][:200]}")
                full_system += "\n\n" + "\n".join(parts)
        except: pass

        # Knowledge Graph context
        try:
            graph_ctx = KnowledgeGraph.get_context_for_prompt(user_message, self._user_id or "default")
            if graph_ctx: full_system += f"\n\n{graph_ctx}"
        except: pass

        # L6: Knowledge Base (RAG)
        try:
            kb = get_knowledge_base()
            kb_ctx = kb.get_context_for_prompt(user_message, self._user_id or "default")
            if kb_ctx: full_system += f"\n\n{kb_ctx}"
        except: pass

        # Tool Learning: серверные навыки
        ssh_host = (ssh_credentials or {}).get("host", "")
        if ssh_host:
            try:
                server_profile = ToolLearning.get_server_profile(ssh_host)
                if server_profile: full_system += f"\n\n{server_profile}"
            except: pass

        # Success Replay: похожие успешные эпизоды
        try:
            replay = EpisodicReplay.get_success_replay_prompt(user_message, self._user_id)
            if replay: full_system += f"\n\n{replay}"
        except: pass

        # Predictive Pre-load
        try:
            predictive_ctx = PredictivePreload.predict_context(
                self._user_id or "default", user_message, chat_history
            )
            if predictive_ctx: full_system += f"\n\n{predictive_ctx}"
        except: pass

        # Cross-User Learning (opt-in: ARCANE_CROSS_LEARNING=true)
        if _CROSS_LEARNING_ENABLED:
            try:
                cross_ctx = CrossUserLearning.get_prompt_suggestions(
                    "general", user_message[:100]
                )
                if cross_ctx: full_system += f"\n\n{cross_ctx}"
            except: pass

        # Task Planner
        if self.planner and self.planner.plan:
            full_system += f"\n\n{self.planner.progress_text()}"

        # Scratchpad
        if self.scratchpad and self.scratchpad.get():
            full_system += f"\n\nБЛОКНОТ:\n{self.scratchpad.get()}"

        # Budget trim
        full_system = self.budget.trim_to_budget(full_system, "system_prompt")

        messages = [{"role": "system", "content": full_system}]

        # Smart History
        smart_history = SmartHistory.build(chat_history or [])
        messages.extend(smart_history)

        # User message
        full_message = user_message
        if file_content:
            if len(file_content) > 30000:
                file_content = file_content[:30000] + f"\n...[обрезано, {len(file_content)} симв.]"
            full_message = f"{file_content}\n\n---\n\nЗадача:\n{user_message}"
        if ssh_host:
            full_message += f"\n\n[Серверы: {ssh_host}]"

        messages.append({"role": "user", "content": full_message})
        return messages

    # ══════════════════════════════════════════════════════════
    # BEFORE ITERATION — вызывать перед каждым _call_ai_stream
    # ══════════════════════════════════════════════════════════

    def before_iteration(self, messages: List[Dict],
                         iteration: int, max_iter: int) -> List[Dict]:
        """Подготовить messages для итерации."""
        # Убрать старый anchor
        messages = [m for m in messages if GoalAnchor.TAG not in m.get("content","")]

        # Вставить новый anchor
        if self.anchor and iteration > 1:
            anchor_msg = self.anchor.build(
                iteration, max_iter,
                scratchpad=self.scratchpad.get() if self.scratchpad else ""
            )
            messages.insert(1, anchor_msg)

        # Compaction
        if self.compactor.should_compact(messages, iteration):
            messages = self.compactor.compact(messages)
            logger.info(f"Compacted at iteration {iteration}: {len(messages)} messages")

        return messages

    # ══════════════════════════════════════════════════════════
    # AFTER TOOL — вызывать после каждого _execute_tool
    # ══════════════════════════════════════════════════════════

    def after_tool(self, tool_name: str, tool_args: Dict,
                   result: Dict, preview: str) -> str:
        """
        Обработать результат инструмента. Возвращает обрезанный result_str.
        Записывает в Tool Learning, Error Patterns, Session Memory.
        """
        success = result.get("success", False)

        # Goal Anchor
        if self.anchor:
            self.anchor.record(tool_name, success, preview[:100])

        # Task Planner
        if self.planner:
            self.planner.auto_detect(tool_name, tool_args, success)

        # Tool Learning
        host = tool_args.get("host", "")
        if host and tool_name in ("ssh_execute", "file_write", "file_read"):
            try:
                ToolLearning.record(host, tool_name,
                                    tool_args.get("command", tool_args.get("path", "")),
                                    success)
            except: pass

        # Error Patterns
        if not success:
            error_msg = result.get("error", result.get("stderr", ""))
            if error_msg:
                try: ErrorPatterns.record_error(str(error_msg)[:500], tool_name)
                except: pass

        # Session Memory
        try:
            SessionMemory.store_message(
                chat_id=self._chat_id or "",
                role="tool", content=preview[:500],
                user_id=self._user_id,
                tool_name=tool_name,
                tool_args=json.dumps(tool_args, ensure_ascii=False)[:500],
                tool_result="success" if success else str(result.get("error",""))[:200]
            )
        except: pass

        # Smart truncation
        return SmartToolOutput.truncate(result, tool_name)

    # ══════════════════════════════════════════════════════════
    # HANDLE TOOLS — обработчики для memory-специфичных tools
    # ══════════════════════════════════════════════════════════

    def handle_tool(self, tool_name: str, args: Dict) -> Optional[Dict]:
        """Обработать memory-tool. Возвращает result или None если не наш tool."""
        if tool_name == "update_scratchpad":
            return self.scratchpad.update(args.get("content", "")) if self.scratchpad else {"success": False}

        if tool_name == "store_memory":
            try:
                sem = get_semantic()
                ok = sem.store(content=f"{args.get('key','')}: {args.get('value','')}",
                               memory_type="semantic",
                               metadata={"key": args.get("key",""), "category": args.get("category","fact")},
                               user_id=self._user_id, confidence=0.9)
                return {"success": ok, "key": args.get("key","")}
            except: return {"success": False}

        if tool_name == "recall_memory":
            try:
                sem = get_semantic()
                results = sem.search(args.get("query",""), limit=5, user_id=self._user_id)
                return {"success": True, "memories": [{"content": r["content"], "type": r["type"], "score": r["score"]} for r in results]}
            except: return {"success": False, "memories": []}

        if tool_name == "snapshot_server":
            return {"success": True, "message": f"Сделай SSH на {args.get('host','')} и выполни команды: " + ", ".join(MemoryConfig.SNAPSHOT_COMMANDS)}

        if tool_name == "diff_server":
            try:
                t = get_temporal()
                diff = t.get_diff(args.get("host",""))
                return {"success": True, "diff": diff}
            except Exception as e:
                return {"success": False, "error": str(e)}

        # ── Structured State tools (§2.2) ──
        if tool_name == "read_project_state":
            if self.structured_state:
                return self.structured_state.handle_read(args.get("section", ""))
            return {"success": False, "error": "No project loaded (project_path not set)"}

        if tool_name == "update_project_state":
            if self.structured_state:
                result = self.structured_state.handle_update(
                    args.get("section", ""), args.get("data", {})
                )
                return result
            return {"success": False, "error": "No project loaded (project_path not set)"}

        if tool_name == "add_decision":
            if self.structured_state:
                self.structured_state.add_decision(
                    what=args.get("what", ""),
                    why=args.get("why", ""),
                    who=args.get("who", "agent"),
                )
                self.structured_state.save()
                return {"success": True, "message": "Decision recorded"}
            return {"success": False, "error": "No project loaded"}

        return None  # Не наш tool

    # ══════════════════════════════════════════════════════════
    # AFTER CHAT — вызывать после завершения чата
    # ══════════════════════════════════════════════════════════

    def after_chat(self, user_message: str, full_response: str,
                   chat_id: str = None, success: bool = True):
        """Финализация после завершения чата."""
        duration = time.time() - (self._task_start_time or time.time())

        # Episodic Replay
        try:
            actions = self.anchor.actions if self.anchor else []
            plan_text = json.dumps(self.planner.plan, ensure_ascii=False) if self.planner and self.planner.plan else ""
            EpisodicReplay.store(
                user_id=self._user_id or "default",
                chat_id=chat_id or self._chat_id or "",
                task=user_message[:2000],
                plan=plan_text[:2000],
                actions=actions,
                result=full_response[:2000],
                success=success,
                duration=duration
            )
        except: pass

        # Self-Reflection
        if self._call_llm and self.anchor:
            try:
                reflection = SelfReflection.reflect(
                    chat_id or "", self._user_id or "default",
                    self._call_llm, self.anchor.actions,
                    user_message, full_response
                )
                if reflection and reflection.get("improve"):
                    # Сохранить урок в Episodic
                    try:
                        from .semantic import get_semantic
                        sem = get_semantic()
                        sem.store(f"Урок: {reflection['improve'][:300]}",
                                  memory_type="procedural",
                                  user_id=self._user_id, confidence=0.85)
                    except: pass
            except: pass

        # Knowledge Graph extraction
        try:
            KnowledgeGraph.extract_from_conversation(
                user_message, full_response,
                self._user_id or "default", self._call_llm
            )
        except: pass

        # User Profile extraction
        if self._profile and self._call_llm:
            try:
                self._profile.extract_from_chat(user_message, full_response, self._call_llm)
            except: pass

        # LLM Fact Extractor (project_manager integration)
        try:
            from project_manager import extract_memory_from_conversation
            extract_memory_from_conversation(
                user_message=user_message,
                assistant_response=full_response[:500],
                user_id=self._user_id or "default",
                api_key=self._api_key, api_url=self._api_url
            )
        except: pass

        # Dynamic Tool Creation: detect patterns → generate tools
        if self.anchor and self._call_llm:
            try:
                DynamicToolManager.check_and_generate(
                    self._user_id or "default",
                    self.anchor.actions,
                    self._call_llm
                )
            except: pass

        # Cross-User Learning (opt-in)
        if _CROSS_LEARNING_ENABLED and self.anchor and len(self.anchor.actions) >= 2:
            try:
                actions = self.anchor.actions
                # Record consecutive command pairs
                for i in range(len(actions) - 1):
                    CrossUserLearning.record_command_pair(
                        f"{actions[i].get('tool','')}:{actions[i].get('s','')}",
                        f"{actions[i+1].get('tool','')}:{actions[i+1].get('s','')}",
                        actions[i+1].get("ok", False)
                    )
                # Record tool sequence
                tool_seq = [a.get("tool","") for a in actions if a.get("tool")]
                success_rate = sum(1 for a in actions if a.get("ok")) / max(len(actions), 1)
                CrossUserLearning.record_tool_sequence(tool_seq, success_rate, user_message[:100])
            except: pass

        # ── Structured State: record run + extract updates (§2.2) ──
        if self.structured_state:
            try:
                # Record this run
                model_name = ""
                total_cost = 0.0
                if self.anchor:
                    actions = self.anchor.actions
                    if actions:
                        model_name = actions[0].get("model", "") if actions else ""
                self.structured_state.record_run(
                    task=user_message[:300],
                    model=model_name,
                    cost=total_cost,
                    result="success" if success else "failed",
                    duration_s=duration,
                    run_id=chat_id or self._chat_id or "",
                )
            except Exception as e:
                logger.debug(f"Structured state record_run failed: {e}")

            # LLM-driven extraction: решения, стек, personality из разговора
            if self._call_llm:
                try:
                    self.structured_state.extract_from_conversation(
                        user_message, full_response, self._call_llm
                    )
                except Exception as e:
                    logger.debug(f"Structured state extraction failed: {e}")

            # Save (если были изменения)
            try:
                self.structured_state.save()
            except: pass

    # ══════════════════════════════════════════════════════════
    # ON STOP — когда пользователь останавливает агента
    # ══════════════════════════════════════════════════════════

    def on_stop(self, user_message: str, iteration: int):
        """Сохранить состояние для продолжения позже."""
        try:
            SessionMemory.save_interrupted(
                chat_id=self._chat_id or "",
                user_id=self._user_id or "default",
                task=user_message[:2000],
                plan=json.dumps(self.planner.plan) if self.planner and self.planner.plan else "",
                progress=self.planner.progress_text() if self.planner else "",
                scratchpad=self.scratchpad.get() if self.scratchpad else "",
                iteration=iteration,
                reason="user_stop"
            )
        except: pass

        # Structured State: сохранить при остановке
        if self.structured_state:
            try:
                self.structured_state.save()
            except: pass

    # ══════════════════════════════════════════════════════════
    # HELPERS
    # ══════════════════════════════════════════════════════════

    @staticmethod
    def _detect_task_type(user_message: str) -> str:
        """Определить тип задачи для выбора среза structured state."""
        msg = user_message.lower()
        if any(w in msg for w in ("ssh", "сервер", "deploy", "nginx", "docker",
                                   "битрикс", "wordpress", "server", "devops")):
            return "ssh"
        if any(w in msg for w in ("дизайн", "верстка", "стиль", "лендинг", "css",
                                   "html", "цвет", "шрифт", "design", "frontend",
                                   "landing", "tailwind", "figma")):
            return "design"
        if any(w in msg for w in ("код", "api", "бэкенд", "backend", "python",
                                   "django", "функци", "endpoint", "code")):
            return "coding"
        return "general"

    # ══════════════════════════════════════════════════════════
    # MULTI-AGENT — оптимизация передачи между агентами
    # ══════════════════════════════════════════════════════════

    @staticmethod
    def build_agent_handoff(context: str, agent_results: Dict,
                            agents_info: Dict) -> str:
        """Построить сообщение для следующего агента. ТЗ ПЕРВЫМ."""
        parts = [f"ЗАДАЧА (приоритет!):\n{context}"]
        if agent_results:
            parts.append("\n---\nПредыдущие агенты:")
            for key, text in agent_results.items():
                name = agents_info.get(key, {}).get("name", key)
                compressed = text[:800] + f"...[{len(text)} симв.]" if len(text) > 800 else text
                parts.append(f"\n=== {name} ===\n{compressed}")
        return "\n".join(parts)

    # ══════════════════════════════════════════════════════════
    # ERROR PATTERN LOOKUP — для Self-Healing 2.0
    # ══════════════════════════════════════════════════════════

    def find_known_fix(self, error_msg: str) -> Optional[Dict]:
        """Найти известное решение ошибки из Error Pattern DB."""
        try:
            return ErrorPatterns.find_fix(error_msg)
        except: return None

    # ── Cross-User Error Fix ──
    def find_cross_user_fix(self, error_msg: str) -> Optional[Dict]:
        """Найти решение из анонимного опыта всех пользователей."""
        try:
            return CrossUserLearning.suggest_error_fix(error_msg)
        except: return None

    # ── Dynamic Tools ──
    def get_dynamic_tools_schema(self) -> List[Dict]:
        """Получить TOOLS_SCHEMA для динамически созданных tools."""
        try:
            return ToolGenerator.get_tools_schema(self._user_id)
        except: return []

    def execute_dynamic_tool(self, tool_name: str, args: Dict,
                             ssh_executor=None) -> Dict:
        """Выполнить динамический tool."""
        return ToolGenerator.execute(tool_name, args, ssh_executor)

    # ── Fine-Tuning ──
    @staticmethod
    def export_training_data() -> Dict:
        """Экспортировать данные для fine-tuning."""
        return DatasetExporter.export_all()

    @staticmethod
    def start_finetuning(dataset_path: str) -> Dict:
        """Запустить fine-tuning (требует GPU)."""
        return FineTuner.train(dataset_path)

    @staticmethod
    def can_use_finetuned(task: str, user_id: str) -> bool:
        """Проверить стоит ли использовать fine-tuned модель."""
        return InferenceRouter.should_use_finetuned(task, user_id)

    @staticmethod
    def query_finetuned(prompt: str) -> Optional[str]:
        """Запросить fine-tuned модель."""
        return InferenceRouter.query_finetuned(prompt)


# ══════════════════════════════════════════════════════════════════
# INTEGRATION GUIDE (v9.1 — with Structured State)
# ══════════════════════════════════════════════════════════════════
#
# 1. Скопировать папку memory_v9/ в backend/
#
# 2. В agent_loop.py:
#    from memory_v9 import SuperMemoryEngine, ALL_MEMORY_TOOLS
#    TOOLS_SCHEMA.extend(ALL_MEMORY_TOOLS)
#
# 3. В AgentLoop.__init__:
#    self.memory = None
#
# 4. Добавить:
#    def _call_ai_simple(self, messages):
#        content, _, error = self._call_ai(messages)
#        if error: raise Exception(error)
#        return content or ""
#
# 5. В run_stream() ЗАМЕНИТЬ строки 2022-2042:
#    self.memory = SuperMemoryEngine(self._call_ai_simple)
#    self.memory.init_task(user_message, file_content,
#        user_id=getattr(self,'_user_id',None),
#        chat_id=getattr(self,'_chat_id',None),
#        api_key=self.api_key, api_url=self.api_url,
#        ssh_host=self.ssh_credentials.get("host",""),
#        project_path=project_path)  # ← NEW: путь к проекту
#    messages = self.memory.build_messages(
#        AGENT_SYSTEM_PROMPT, chat_history or [],
#        user_message, file_content, self.ssh_credentials)
#
# 6. В while-цикле ПЕРЕД _call_ai_stream:
#    messages = self.memory.before_iteration(messages, iteration, self.MAX_ITERATIONS)
#
# 7. В _execute_tool добавить ПЕРЕД основным switch:
#    mem_result = self.memory.handle_tool(tool_name, args)
#    if mem_result is not None: return mem_result
#
# 8. ПОСЛЕ _execute_tool:
#    result_str = self.memory.after_tool(tool_name, tool_args, result, result_preview)
#    (это заменяет старый result_str = json.dumps...)
#
# 9. При self._stop_requested:
#    self.memory.on_stop(user_message, iteration)
#
# 10. В app.py ПОСЛЕ генерации ответа (строка ~1363):
#     try: agent.memory.after_chat(user_message, full_response, chat_id,
#          success="❌" not in full_response[:100])
#     except: pass
#
# 11. Для MultiAgentLoop ЗАМЕНИТЬ строки 2325-2328:
#     content = SuperMemoryEngine.build_agent_handoff(context, agent_results, self.AGENTS)
#     messages.append({"role":"user","content":content})
#
# 12. В memory.py строка 177:
#     # self._client = QdrantClient(":memory:")
#     # ↓
#     self._client = QdrantClient(path=MemoryConfig.QDRANT_PATH)
#
# 13. ФОНОВЫЕ ЗАДАЧИ (cron / systemd timer):
#     from memory_v9.lifecycle import MemoryDecay, MemoryConsolidation, MemoryVersioning
#     # Ежедневно: MemoryDecay.run(user_id)
#     # Еженедельно: MemoryConsolidation.run(user_id, call_llm)
#     # Перед деплоем: MemoryVersioning.create_snapshot("pre_deploy")
