"""
SuperMemoryEngine v9.0 — объединяет ВСЕ компоненты памяти.
Единая точка входа для agent_loop.py.

INTEGRATION GUIDE (12 шагов):
1. from memory_v9 import SuperMemoryEngine, ALL_MEMORY_TOOLS
2. TOOLS_SCHEMA.extend(ALL_MEMORY_TOOLS)
3. В AgentLoop.__init__: self.memory = None
4. Добавить _call_ai_simple()
5. В run_stream() инициализировать: self.memory = SuperMemoryEngine(...)
6. В while-цикле ПЕРЕД _call_ai_stream: messages = self.memory.before_iteration(...)
7. В _execute_tool ПЕРЕД switch: mem_result = self.memory.handle_tool(...)
8. ПОСЛЕ _execute_tool: result_str = self.memory.after_tool(...)
9. При stop: self.memory.on_stop(...)
10. В app.py ПОСЛЕ ответа: agent.memory.after_chat(...)
11. Для MultiAgent: content = SuperMemoryEngine.build_agent_handoff(...)
12. Qdrant persistent path уже настроен в config.py
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
from .dynamic_tools import DynamicToolManager, ToolGenerator
from .cross_learning import CrossUserLearning
from .finetuning import DatasetExporter, FineTuner, InferenceRouter

logger = logging.getLogger("memory.engine")


class SuperMemoryEngine:
    """Единый интерфейс ко всей системе памяти."""

    def __init__(self, call_llm_func=None, enable_planner: bool = True):
        self._call_llm = call_llm_func
        self._enable_planner = enable_planner

        # L1: Working
        self.planner = None
        self.anchor = None
        self.scratchpad = None
        self.compactor = ContextCompactor(call_llm_func)
        self.budget = ContextBudget()

        # Context
        self._user_id = None
        self._chat_id = None
        self._api_key = ""
        self._api_url = ""
        self._profile = None
        self._task_start_time = None

    # ══════════════════════════════════════════════════════════
    # INIT
    # ══════════════════════════════════════════════════════════

    def init_task(self, user_message: str, file_content: str = "",
                  user_id: str = None, chat_id: str = None,
                  api_key: str = "", api_url: str = "",
                  ssh_host: str = ""):
        """Инициализация перед новой задачей."""
        self._user_id = user_id
        self._chat_id = chat_id
        self._api_key = api_key
        self._api_url = api_url
        self._task_start_time = time.time()

        # Scratchpad
        self.scratchpad = Scratchpad(chat_id=chat_id)

        # Task Planner
        if self._enable_planner and self._call_llm:
            try:
                self.planner = TaskPlanner(self._call_llm)
                self.planner.create_plan(user_message, file_content)
            except Exception as e:
                logger.warning(f"TaskPlanner init failed: {e}")
                self.planner = None

        # Goal Anchor
        self.anchor = GoalAnchor(user_message, self.planner)

        # User Profile
        try:
            self._profile = UserProfile(user_id or "default")
            self._profile.increment_chats()
        except:
            self._profile = None

        # Check for interrupted task
        try:
            interrupted = SessionMemory.get_interrupted(user_id or "default")
            if interrupted and "продолж" in user_message.lower():
                self.scratchpad.update(
                    f"ПРЕРВАННАЯ ЗАДАЧА (продолжение):\n"
                    f"Задача: {interrupted.get('task','')[:500]}\n"
                    f"Прогресс: {interrupted.get('progress','')[:500]}\n"
                    f"Итерация: {interrupted.get('iteration','?')}"
                )
                SessionMemory.clear_interrupted(user_id or "default")
        except:
            pass

    # ══════════════════════════════════════════════════════════
    # BUILD MESSAGES
    # ══════════════════════════════════════════════════════════

    def build_messages(self, system_prompt: str, chat_history: List[Dict],
                       user_message: str, file_content: str = "",
                       ssh_credentials: Dict = None) -> List[Dict]:
        """Построить начальный массив messages со всеми слоями памяти."""
        logger.info(f"[MEMORY] build_messages: user_id={self._user_id!r}, profile={self._profile is not None}")
        full_system = system_prompt

        # L5: User Profile
        if self._profile:
            try:
                ctx = self._profile.get_prompt_context()
                if ctx:
                    full_system += f"\n\n{ctx}"
                    logger.info(f"[MEMORY] build_messages: profile context injected ({len(ctx)} chars)")
                else:
                    logger.info(f"[MEMORY] build_messages: profile context EMPTY (no facts yet)")
            except Exception as _pe:
                logger.warning(f"[MEMORY] build_messages profile error: {_pe}")
        else:
            logger.warning(f"[MEMORY] build_messages: _profile is None!")

        # L3: Semantic Memory
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
                    label = {
                        "episodic": "Опыт", "semantic": "Факт",
                        "procedural": "Навык", "knowledge": "Документ",
                        "shared": "Команда", "visual": "Скриншот"
                    }.get(r.get("type", ""), "Заметка")
                    parts.append(f"  [{label}] {r['content'][:200]}")
                full_system += "\n\n" + "\n".join(parts)
        except:
            pass

        # Knowledge Graph context
        try:
            graph_ctx = KnowledgeGraph.get_context_for_prompt(
                user_message, self._user_id or "default"
            )
            if graph_ctx:
                full_system += f"\n\n{graph_ctx}"
        except:
            pass

        # L6: Knowledge Base (RAG)
        try:
            kb = get_knowledge_base()
            kb_ctx = kb.get_context_for_prompt(user_message, self._user_id or "default")
            if kb_ctx:
                full_system += f"\n\n{kb_ctx}"
        except:
            pass

        # Tool Learning: серверные навыки
        ssh_host = (ssh_credentials or {}).get("host", "")
        if ssh_host:
            try:
                server_profile = ToolLearning.get_server_profile(ssh_host)
                if server_profile:
                    full_system += f"\n\n{server_profile}"
            except:
                pass

        # Success Replay
        try:
            replay = EpisodicReplay.get_success_replay_prompt(user_message, self._user_id)
            if replay:
                full_system += f"\n\n{replay}"
        except:
            pass

        # Predictive Pre-load
        try:
            predictive_ctx = PredictivePreload.predict_context(
                self._user_id or "default", user_message, chat_history
            )
            if predictive_ctx:
                full_system += f"\n\n{predictive_ctx}"
        except:
            pass

        # Task Planner
        if self.planner and self.planner.plan:
            try:
                full_system += f"\n\n{self.planner.progress_text()}"
            except:
                pass

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
    # BEFORE ITERATION
    # ══════════════════════════════════════════════════════════

    def before_iteration(self, messages: List[Dict],
                         iteration: int, max_iter: int) -> List[Dict]:
        """Подготовить messages для итерации."""
        # Убрать старый anchor
        messages = [m for m in messages if GoalAnchor.TAG not in m.get("content", "")]

        # Вставить новый anchor
        if self.anchor and iteration > 1:
            try:
                anchor_msg = self.anchor.build(
                    iteration, max_iter,
                    scratchpad=self.scratchpad.get() if self.scratchpad else ""
                )
                messages.insert(1, anchor_msg)
            except:
                pass

        # Compaction
        if self.compactor.should_compact(messages, iteration):
            try:
                messages = self.compactor.compact(messages)
                logger.info(f"Compacted at iteration {iteration}: {len(messages)} messages")
            except:
                pass

        return messages

    # ══════════════════════════════════════════════════════════
    # AFTER TOOL
    # ══════════════════════════════════════════════════════════

    def after_tool(self, tool_name: str, tool_args: Dict,
                   result: Dict, preview: str) -> str:
        """Обработать результат инструмента."""
        success = result.get("success", False)

        # Goal Anchor
        if self.anchor:
            try:
                self.anchor.record(tool_name, success, preview[:100])
            except:
                pass

        # Task Planner
        if self.planner:
            try:
                self.planner.auto_detect(tool_name, tool_args, success)
            except:
                pass

        # Tool Learning
        host = tool_args.get("host", "")
        if host and tool_name in ("ssh_execute", "file_write", "file_read"):
            try:
                ToolLearning.record(
                    host, tool_name,
                    tool_args.get("command", tool_args.get("path", "")),
                    success
                )
            except:
                pass

        # Error Patterns
        if not success:
            error_msg = result.get("error", result.get("stderr", ""))
            if error_msg:
                try:
                    ErrorPatterns.record_error(str(error_msg)[:500], tool_name)
                except:
                    pass

        # Session Memory
        try:
            SessionMemory.store_message(
                chat_id=self._chat_id or "",
                role="tool",
                content=preview[:500],
                user_id=self._user_id,
                tool_name=tool_name,
                tool_args=json.dumps(tool_args, ensure_ascii=False)[:500],
                tool_result="success" if success else str(result.get("error", ""))[:200]
            )
        except:
            pass

        # Smart truncation
        return SmartToolOutput.truncate(result, tool_name)

    # ══════════════════════════════════════════════════════════
    # HANDLE TOOL — memory-специфичные tools
    # ══════════════════════════════════════════════════════════

    def handle_tool(self, tool_name: str, args: Dict) -> Optional[Dict]:
        """Обработать memory-tool. Возвращает result или None."""
        if tool_name == "update_scratchpad":
            if self.scratchpad:
                return self.scratchpad.update(args.get("content", ""))
            return {"success": False, "error": "Scratchpad not initialized"}

        if tool_name == "store_memory":
            try:
                sem = get_semantic()
                ok = sem.store(
                    content=f"{args.get('key','')}: {args.get('value','')}",
                    memory_type="semantic",
                    metadata={"key": args.get("key", ""), "category": args.get("category", "fact")},
                    user_id=self._user_id,
                    confidence=0.9
                )
                return {"success": ok, "key": args.get("key", "")}
            except Exception as e:
                return {"success": False, "error": str(e)}

        if tool_name == "recall_memory":
            try:
                sem = get_semantic()
                results = sem.search(args.get("query", ""), limit=5, user_id=self._user_id)
                return {
                    "success": True,
                    "memories": [
                        {"content": r["content"], "type": r.get("type",""), "score": r.get("score",0)}
                        for r in results
                    ]
                }
            except Exception as e:
                return {"success": False, "memories": [], "error": str(e)}

        if tool_name == "snapshot_server":
            return {
                "success": True,
                "message": f"Снимок сервера {args.get('host','')} запрошен"
            }

        if tool_name == "diff_server":
            try:
                t = get_temporal()
                diff = t.get_diff(args.get("host", ""))
                return {"success": True, "diff": diff}
            except Exception as e:
                return {"success": False, "error": str(e)}

        return None  # Не наш tool

    # ══════════════════════════════════════════════════════════
    # AFTER CHAT
    # ══════════════════════════════════════════════════════════

    def after_chat(self, user_message: str, full_response: str,
                   chat_id: str = None, success: bool = True):
        """Финализация после завершения чата."""
        logger.info(f"[MEMORY] after_chat START: user_id={self._user_id!r}, chat_id={chat_id!r}, msg={user_message[:80]!r}")
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
        except:
            pass

        # Self-Reflection
        if self._call_llm and self.anchor:
            try:
                SelfReflection.reflect(
                    chat_id or "", self._user_id or "default",
                    self._call_llm, self.anchor.actions,
                    user_message, full_response
                )
            except:
                pass

        # Knowledge Graph extraction
        try:
            KnowledgeGraph.extract_from_conversation(
                user_message, full_response,
                self._user_id or "default", self._call_llm
            )
        except:
            pass

        # User Profile extraction
        if self._profile:
            try:
                self._profile.increment_chats()
            except Exception as _ic_err:
                logger.warning(f"[MEMORY] increment_chats error: {_ic_err}")
        if self._profile and self._call_llm:
            try:
                logger.info(f"[MEMORY] calling extract_from_chat: user_id={self._user_id!r}")
                self._profile.extract_from_chat(user_message, full_response, self._call_llm)
            except Exception as _ef_err:
                logger.warning(f"[MEMORY] extract_from_chat error: {_ef_err}", exc_info=True)
        elif self._profile and not self._call_llm:
            logger.warning(f"[MEMORY] extract_from_chat SKIPPED: _call_llm is None!")

        # LLM Fact Extractor (project_manager integration)
        try:
            from project_manager import extract_memory_from_conversation
            extract_memory_from_conversation(
                user_message=user_message,
                assistant_response=full_response[:500],
                user_id=self._user_id or "default",
                api_key=self._api_key,
                api_url=self._api_url
            )
        except:
            pass

        # Cross-User Learning
        if self.anchor and len(self.anchor.actions) >= 2:
            try:
                actions = self.anchor.actions
                for i in range(len(actions) - 1):
                    CrossUserLearning.record_command_pair(
                        f"{actions[i].get('tool','')}:{actions[i].get('s','')}",
                        f"{actions[i+1].get('tool','')}:{actions[i+1].get('s','')}",
                        actions[i+1].get("ok", False)
                    )
                tool_seq = [a.get("tool", "") for a in actions if a.get("tool")]
                success_rate = sum(1 for a in actions if a.get("ok")) / max(len(actions), 1)
                CrossUserLearning.record_tool_sequence(tool_seq, success_rate, user_message[:100])
            except:
                pass

    # ══════════════════════════════════════════════════════════
    # ON STOP
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
        except:
            pass

    # ══════════════════════════════════════════════════════════
    # MULTI-AGENT
    # ══════════════════════════════════════════════════════════

    @staticmethod
    def build_agent_handoff(context: str, agent_results: Dict,
                            agents_info: Dict) -> str:
        """Построить сообщение для следующего агента."""
        parts = [f"ЗАДАЧА (приоритет!):\n{context}"]
        if agent_results:
            parts.append("\n---\nПредыдущие агенты:")
            for key, text in agent_results.items():
                name = agents_info.get(key, {}).get("name", key)
                compressed = text[:800] + f"...[{len(text)} симв.]" if len(text) > 800 else text
                parts.append(f"\n=== {name} ===\n{compressed}")
        return "\n".join(parts)

    # ══════════════════════════════════════════════════════════
    # ERROR PATTERN LOOKUP
    # ══════════════════════════════════════════════════════════

    def find_known_fix(self, error_msg: str) -> Optional[Dict]:
        try:
            return ErrorPatterns.find_fix(error_msg)
        except:
            return None

    def find_cross_user_fix(self, error_msg: str) -> Optional[Dict]:
        try:
            return CrossUserLearning.suggest_error_fix(error_msg)
        except:
            return None


    def store_fact(self, key: str, value: str, category: str = "fact", metadata: dict = None):
        """Сохранить факт в долгосрочную память."""
        try:
            # В semantic memory (векторный поиск)
            from .semantic import get_semantic
            sem = get_semantic()
            if sem:
                sem.store(
                    content=f"{key}: {value}",
                    memory_type=category,
                    metadata={
                        "category": category,
                        "key": key,
                        **(metadata or {})
                    },
                    user_id=self._user_id or "default"
                )
            logger.info(f"[MEMORY] store_fact OK: {key[:50]}")
        except Exception as e:
            logger.warning(f"store_fact failed: {e}")

    def recall(self, query: str, category: str = None, top_k: int = 10):
        """Вспомнить факты из памяти по запросу."""
        try:
            from .semantic import get_semantic
            sem = get_semantic()
            if sem:
                results = sem.search(
                    query=query,
                    limit=top_k,
                    user_id=self._user_id or "default",
                    memory_type=category
                )
                if results:
                    return [r.get("content", "") for r in results if r.get("content")]
            return []
        except Exception as e:
            logger.warning(f"recall failed: {e}")
            return []

    def recall_all(self, category: str, limit: int = 100):
        """Загрузить ВСЕ записи категории без семантического поиска."""
        try:
            from .semantic import get_semantic
            sem = get_semantic()
            if sem:
                results = sem.get_all_by_type(
                    memory_type=category,
                    user_id=self._user_id or "default",
                    limit=limit
                )
                if results:
                    return [r.get("content", "") for r in results if r.get("content")]
            return []
        except Exception as e:
            logger.warning(f"recall_all failed: {e}")
            return []

    def get_dynamic_tools_schema(self) -> List[Dict]:
        try:
            return ToolGenerator.get_tools_schema(self._user_id)
        except:
            return []

    def execute_dynamic_tool(self, tool_name: str, args: Dict,
                             ssh_executor=None) -> Dict:
        return ToolGenerator.execute(tool_name, args, ssh_executor)

    @staticmethod
    def export_training_data() -> Dict:
        return DatasetExporter.export_all()

    @staticmethod
    def start_finetuning(dataset_path: str) -> Dict:
        return FineTuner.train(dataset_path)

    @staticmethod
    def can_use_finetuned(task: str, user_id: str) -> bool:
        return InferenceRouter.should_use_finetuned(task, user_id)

    @staticmethod
    def query_finetuned(prompt: str) -> Optional[str]:
        return InferenceRouter.query_finetuned(prompt)
