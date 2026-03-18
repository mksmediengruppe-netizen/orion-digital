"""
Parallel Agent Execution v6.0 — Run multiple agents concurrently.
================================================================

Provides:
- ParallelAgentOrchestrator: runs 2-6 agents in parallel threads
- Shared context: agents can read each other's intermediate results
- Merge strategy: combines results from all agents into unified response
- Thread-safe SSE event streaming

Architecture:
  User Task → select_agents() → [Agent1, Agent2, ...] → parallel run → merge → SSE stream

Thread safety:
- Each agent gets its own AgentLoop instance
- SSE events are collected via thread-safe queue
- Tool execution is thread-safe (SSH pool, file locks)
"""

import json
import time
import logging
import threading
import queue
from typing import Dict, Any, List, Generator, Optional
from concurrent.futures import ThreadPoolExecutor, as_completed, Future

from specialized_agents import (
    SPECIALIZED_AGENTS,
    select_agents_for_task,
    get_agent_pipeline
)

logger = logging.getLogger("parallel_agents")

# Handoff Protocol — передача результатов между агентами
try:
    from handoff_protocol import HandoffManager, extract_handoff_from_output
    _HANDOFF_AVAILABLE = True
except ImportError:
    _HANDOFF_AVAILABLE = False
    logger.warning("handoff_protocol not available")


# ══════════════════════════════════════════════════════════════
# BUG-9 FIX: AGENT DIRECTORY ZONES
# ══════════════════════════════════════════════════════════════
AGENT_ZONES = {
    "designer":   "/var/www/{project}/frontend/",
    "developer":  "/var/www/{project}/backend/",
    "devops":     "/etc/nginx/",
    "integrator": "/var/www/{project}/integrations/",
    "analyst":    "/var/www/{project}/reports/",
    "qa":         "/var/www/{project}/tests/",
    "copywriter": "/var/www/{project}/frontend/",  # ПАТЧ W2-3
}

def get_agent_zone(agent_key: str, project: str = "orion") -> str:
    """Получить рабочую директорию для агента."""
    zone = AGENT_ZONES.get(agent_key, f"/var/www/{project}/")
    return zone.replace("{project}", project)

def build_zone_prompt(agent_key: str, project: str = "orion") -> str:
    """Добавить в system prompt ограничение зоны."""
    zone = get_agent_zone(agent_key, project)
    return f"\n\n⚠️ ЗОНА РАБОТЫ: Работай ТОЛЬКО в директории {zone}. Не изменяй файлы вне этой зоны."


# ══════════════════════════════════════════════════════════════
# BUG-11 FIX: SHARED SCRATCHPAD (thread-safe)
# ══════════════════════════════════════════════════════════════
class SharedScratchpad:
    """Thread-safe shared scratchpad для параллельных агентов."""

    def __init__(self):
        self._lock = threading.Lock()
        self._data: Dict[str, str] = {}
        self._history: List[Dict] = []

    def write(self, agent_key: str, content: str):
        """Записать данные от агента."""
        with self._lock:
            self._data[agent_key] = content
            self._history.append({
                "agent": agent_key,
                "content": content[:500],
                "timestamp": time.time()
            })

    def read(self, agent_key: str = None) -> str:
        """Прочитать данные (все или конкретного агента)."""
        with self._lock:
            if agent_key:
                return self._data.get(agent_key, "")
            parts = []
            for key, val in self._data.items():
                parts.append(f"[{key}]: {val[:300]}")
            return "\n".join(parts)

    def get_context_for_agent(self, agent_key: str) -> str:
        """Получить контекст от других агентов для данного агента."""
        with self._lock:
            parts = []
            for key, val in self._data.items():
                if key != agent_key:
                    parts.append(f"Агент {key} сообщает: {val[:200]}")
            if parts:
                return "\n\nКОНТЕКСТ ОТ ДРУГИХ АГЕНТОВ:\n" + "\n".join(parts)
            return ""


# ══════════════════════════════════════════════════════════════
# PARALLEL AGENT ORCHESTRATOR
# ══════════════════════════════════════════════════════════════

class ParallelAgentOrchestrator:
    """
    Orchestrates parallel execution of multiple specialized agents.
    
    Usage:
        orchestrator = ParallelAgentOrchestrator(
            model="minimax/minimax-m2.5",
            api_key="...",
            ssh_credentials={...}
        )
        for event in orchestrator.run_parallel(user_message, agents=["designer", "developer"]):
            yield event  # SSE events
    """

    def __init__(self, model: str, api_key: str,
                 api_url: str = "https://openrouter.ai/api/v1/chat/completions",
                 ssh_credentials: dict = None,
                 max_workers: int = 3):
        self.model = model
        self.api_key = api_key
        self.api_url = api_url
        self.ssh_credentials = ssh_credentials or {}
        self.max_workers = max_workers
        self._stop_requested = False
        self._event_queue = queue.Queue()
        self._agent_results = {}
        self._lock = threading.Lock()
        # BUG-11 FIX: Shared scratchpad для межагентного обмена
        self.shared_scratchpad = SharedScratchpad()
        # Handoff Protocol
        self.handoff_manager = HandoffManager() if _HANDOFF_AVAILABLE else None

    def stop(self):
        """Request all agents to stop."""
        self._stop_requested = True

    def _sse(self, data: dict) -> str:
        """Format SSE event."""
        return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"

    def _run_single_agent(self, agent_key: str, agent_config: dict,
                          user_message: str, chat_history: list,
                          file_content: str = None,
                          shared_context: dict = None) -> dict:
        """
        Run a single agent in its own thread.
        Returns dict with agent results.
        """
        # Import here to avoid circular imports
        from agent_loop import AgentLoop, AGENT_SYSTEM_PROMPT, TOOLS_SCHEMA

        agent_name = agent_config["name"]
        agent_emoji = agent_config["emoji"]

        # Emit agent_start event
        self._event_queue.put(self._sse({
            "type": "agent_start",
            "agent": agent_name,
            "emoji": agent_emoji,
            "role": agent_key,
            "parallel": True
        }))

        try:
            # Create dedicated AgentLoop for this agent
            agent_model = agent_config.get("preferred_model", self.model)
            # BUG-9 FIX: zone restriction
            _zone_hint = build_zone_prompt(agent_key)
            loop = AgentLoop(
                model=agent_model,
                api_key=self.api_key,
                api_url=self.api_url,
                ssh_credentials=self.ssh_credentials  # ПАТЧ W2-5: передаём SSH credentials
            )
            # ПАТЧ W2-5: Передать SSH credentials в каждый AgentLoop
            if self.ssh_credentials:
                loop.ssh_host = self.ssh_credentials.get('host', '')
                loop.ssh_user = self.ssh_credentials.get('username', 'root')
                loop.ssh_pass = self.ssh_credentials.get('password', '')
                loop.ssh_port = self.ssh_credentials.get('port', 22)
            # BUG-11 FIX: shared scratchpad (thread-safe)
            loop._shared_scratchpad = self.shared_scratchpad
            loop._agent_zone = get_agent_zone(agent_key)

            # Build context (BUG-9: добавить zone hint)
            context = user_message + _zone_hint
            if file_content:
                context = f"{file_content}\n\n---\n\nЗадача:\n{user_message}"

            if self.ssh_credentials.get("host"):
                context += f"\n\n[Сервер: {self.ssh_credentials['host']}, user: {self.ssh_credentials.get('username', 'root')}]"

            # Add shared context from other agents
            if shared_context:
                prev = "\n\n".join([
                    f"=== Результат {SPECIALIZED_AGENTS.get(k, {}).get('name', k)} ===\n{v}"
                    for k, v in shared_context.items()
                    if v  # Only include non-empty results
                ])
                if prev:
                    context = f"Результаты других агентов:\n{prev}\n\n---\n\nОригинальная задача:\n{context}"

            # Build messages with agent-specific system prompt
            messages = [{
                "role": "system",
                "content": AGENT_SYSTEM_PROMPT + "\n\n" + agent_config["prompt_suffix"]
            }]
            messages.append({"role": "user", "content": context})

            # Run agent iterations
            agent_text = ""
            iteration = 0
            max_iterations = 20  # ПАТЧ W2-5: было 8
            heal_attempts = 0

            while iteration < max_iterations and not self._stop_requested:
                iteration += 1

                tool_calls_received = None
                ai_text = ""

                for event in loop._call_ai_stream(messages, tools=TOOLS_SCHEMA):
                    if self._stop_requested:
                        break

                    if event["type"] == "text_delta":
                        ai_text += event["text"]
                        agent_text += event["text"]
                        self._event_queue.put(self._sse({
                            "type": "content",
                            "text": event["text"],
                            "agent": agent_name,
                            "parallel": True
                        }))

                    elif event["type"] == "tool_calls":
                        tool_calls_received = event["tool_calls"]
                        ai_text = event.get("content", "")
                        if ai_text:
                            agent_text += ai_text

                    elif event["type"] == "text_complete":
                        break

                    elif event["type"] == "error":
                        self._event_queue.put(self._sse({
                            "type": "error",
                            "text": event["error"],
                            "agent": agent_name
                        }))
                        break

                if not tool_calls_received:
                    break

                # Process tool calls
                assistant_msg = {"role": "assistant", "content": ai_text or ""}
                assistant_msg["tool_calls"] = tool_calls_received
                messages.append(assistant_msg)

                for tc in tool_calls_received:
                    tool_name = tc["function"]["name"]
                    tool_args_str = tc["function"]["arguments"]
                    tool_id = tc.get("id", f"call_{iteration}")

                    try:
                        tool_args = json.loads(tool_args_str)
                    except Exception:
                        tool_args = {}

                    self._event_queue.put(self._sse({
                        "type": "tool_start",
                        "tool": tool_name,
                        "args": loop._sanitize_args(tool_args),
                        "agent": agent_name,
                        "parallel": True
                    }))

                    if tool_name == "task_complete":
                        result = loop._execute_tool(tool_name, tool_args_str)
                        self._event_queue.put(self._sse({
                            "type": "tool_result",
                            "tool": tool_name,
                            "success": True,
                            "summary": result.get("summary", ""),
                            "agent": agent_name
                        }))
                        messages.append({
                            "role": "tool",
                            "tool_call_id": tool_id,
                            "content": json.dumps(result, ensure_ascii=False)
                        })
                        # Store result
                        with self._lock:
                            self._agent_results[agent_key] = agent_text
                        return {
                            "agent": agent_key,
                            "name": agent_name,
                            "text": agent_text,
                            "tokens_in": loop.total_tokens_in,
                            "tokens_out": loop.total_tokens_out,
                            "actions": loop.actions_log,
                            "completed": True
                        }

                    start_time = time.time()
                    result = loop._execute_tool(tool_name, tool_args_str)
                    elapsed = round(time.time() - start_time, 2)

                    loop.actions_log.append({
                        "agent": agent_key,
                        "iteration": iteration,
                        "tool": tool_name,
                        "success": result.get("success", False),
                        "elapsed": elapsed
                    })

                    # ПАТЧ W2-5: Записывать в scratchpad при создании файлов
                    if result.get("success") and tool_name in ("file_write", "create_artifact", "ftp_upload"):
                        _file_path = tool_args.get("path", tool_args.get("filename", ""))
                        if _file_path:
                            self.shared_scratchpad.write(
                                agent_key,
                                self.shared_scratchpad.read(agent_key) + f"\nСоздан: {_file_path}"
                            )

                    result_preview = loop._preview_result(tool_name, result)
                    self._event_queue.put(self._sse({
                        "type": "tool_result",
                        "tool": tool_name,
                        "success": result.get("success", False),
                        "preview": result_preview,
                        "elapsed": elapsed,
                        "agent": agent_name,
                        "parallel": True
                    }))

                    # Self-Healing
                    if not result.get("success", False) and heal_attempts < loop.MAX_HEAL_ATTEMPTS:
                        fixes = loop._analyze_error(tool_name, tool_args, result)
                        if fixes:
                            heal_attempts += 1
                            fix = fixes[0]
                            fix_tool = fix["action"]["tool"]
                            fix_args = fix["action"]["args"]

                            self._event_queue.put(self._sse({
                                "type": "self_heal",
                                "attempt": heal_attempts,
                                "max_attempts": loop.MAX_HEAL_ATTEMPTS,
                                "fix_description": fix["description"],
                                "agent": agent_name,
                                "parallel": True
                            }))

                            fix_result = loop._execute_tool(fix_tool, json.dumps(fix_args))
                            self._event_queue.put(self._sse({
                                "type": "tool_result",
                                "tool": fix_tool,
                                "success": fix_result.get("success", False),
                                "agent": agent_name,
                                "is_heal": True,
                                "parallel": True
                            }))

                            heal_info = json.dumps({
                                "self_heal": True,
                                "original_error": str(result.get("error", ""))[:200],
                                "fix_applied": fix["description"],
                                "fix_result": fix_result
                            }, ensure_ascii=False)

                            if len(heal_info) > loop.MAX_TOOL_OUTPUT:
                                heal_info = heal_info[:loop.MAX_TOOL_OUTPUT] + "..."

                            messages.append({
                                "role": "tool",
                                "tool_call_id": tool_id,
                                "content": heal_info
                            })
                            continue

                    result_str = json.dumps(result, ensure_ascii=False)
                    if len(result_str) > loop.MAX_TOOL_OUTPUT:
                        result_str = result_str[:loop.MAX_TOOL_OUTPUT] + "..."

                    messages.append({
                        "role": "tool",
                        "tool_call_id": tool_id,
                        "content": result_str
                    })

            # Handoff Protocol: извлечь результат для передачи следующему агенту
            if self.handoff_manager and _HANDOFF_AVAILABLE:
                try:
                    handoff = extract_handoff_from_output(
                        agent_key, agent_text, loop.actions_log
                    )
                    self.handoff_manager.phase_results[agent_key] = handoff
                    self.handoff_manager.global_context.append(handoff.to_context_string())
                    logger.info(f"[Handoff] {agent_key}: {len(handoff.files_created)} files, {len(handoff.commands_executed)} cmds")
                except Exception as e:
                    logger.error(f"[Handoff] extract error for {agent_key}: {e}")
            # Store result for other agents
            with self._lock:
                self._agent_results[agent_key] = agent_text

            self._event_queue.put(self._sse({
                "type": "agent_complete",
                "agent": agent_name,
                "role": agent_key,
                "parallel": True
            }))

            return {
                "agent": agent_key,
                "name": agent_name,
                "text": agent_text,
                "tokens_in": loop.total_tokens_in,
                "tokens_out": loop.total_tokens_out,
                "actions": loop.actions_log,
                "completed": True
            }

        except Exception as e:
            logger.error(f"Agent {agent_key} failed: {e}")
            self._event_queue.put(self._sse({
                "type": "error",
                "text": f"Агент {agent_name} завершился с ошибкой: {str(e)[:200]}",
                "agent": agent_name
            }))
            return {
                "agent": agent_key,
                "name": agent_name,
                "text": f"Ошибка: {str(e)}",
                "tokens_in": 0,
                "tokens_out": 0,
                "actions": [],
                "completed": False,
                "error": str(e)
            }

    def run_parallel(self, user_message: str, chat_history: list = None,
                     file_content: str = None,
                     agent_keys: list = None,
                     mode: str = "chat") -> Generator[str, None, None]:
        """
        Run multiple agents in parallel and stream SSE events.
        
        Args:
            user_message: User's task description
            chat_history: Previous messages
            file_content: Uploaded file content
            agent_keys: Specific agents to run (auto-select if None)
            mode: Task mode for agent selection
        
        Yields: SSE event strings
        """
        if chat_history is None:
            chat_history = []

        # Select agents if not specified
        if agent_keys:
            agents_to_run = [
                {"key": k, **SPECIALIZED_AGENTS[k]}
                for k in agent_keys if k in SPECIALIZED_AGENTS
            ]
        else:
            agents_to_run = select_agents_for_task(user_message, mode, max_agents=self.max_workers)

        if not agents_to_run:
            yield self._sse({"type": "error", "text": "Не удалось выбрать агентов для задачи"})
            return

        # Emit parallel start event
        agent_names = [a.get("name", a.get("key", "?")) for a in agents_to_run]
        yield self._sse({
            "type": "parallel_start",
            "agents": agent_names,
            "count": len(agents_to_run)
        })

        # Determine execution strategy
        # Independent agents run in parallel, dependent ones run sequentially
        independent_agents = []
        dependent_agents = []

        for agent in agents_to_run:
            key = agent.get("key", agent.get("role", ""))
            # Tester depends on developer/devops results
            # Integrator depends on developer results
            if key in ("tester",):
                dependent_agents.append(agent)
            else:
                independent_agents.append(agent)

        # Phase 1: Run independent agents in parallel
        total_tokens_in = 0
        total_tokens_out = 0
        all_results = []

        if independent_agents:
            futures = {}
            with ThreadPoolExecutor(max_workers=min(len(independent_agents), self.max_workers)) as executor:
                for agent in independent_agents:
                    key = agent.get("key", agent.get("role", ""))
                    future = executor.submit(
                        self._run_single_agent,
                        key, agent, user_message, chat_history,
                        file_content, None
                    )
                    futures[future] = key

                # Stream events from queue while waiting for futures
                done_count = 0
                while done_count < len(futures):
                    # Check for completed futures
                    for future in list(futures.keys()):
                        if future.done() and futures[future] is not None:
                            try:
                                result = future.result(timeout=0)
                                all_results.append(result)
                                total_tokens_in += result.get("tokens_in", 0)
                                total_tokens_out += result.get("tokens_out", 0)
                            except Exception as e:
                                logger.error(f"Agent future error: {e}")
                            futures[future] = None  # Mark as processed
                            done_count += 1

                    # Drain event queue
                    while not self._event_queue.empty():
                        try:
                            event = self._event_queue.get_nowait()
                            yield event
                        except queue.Empty:
                            break

                    if done_count < len(futures):
                        time.sleep(0.1)

            # Drain remaining events
            while not self._event_queue.empty():
                try:
                    yield self._event_queue.get_nowait()
                except queue.Empty:
                    break

        # Phase 2: Run dependent agents sequentially (they need results from phase 1)
        if dependent_agents and not self._stop_requested:
            for agent in dependent_agents:
                key = agent.get("key", agent.get("role", ""))
                # Handoff: добавить контекст предыдущих агентов
                _handoff_ctx = ""
                if self.handoff_manager and _HANDOFF_AVAILABLE:
                    _handoff_ctx = self.handoff_manager.get_context_for_next_agent(key)
                _shared = dict(self._agent_results)
                if _handoff_ctx:
                    _shared["__handoff__"] = _handoff_ctx
                result = self._run_single_agent(
                    key, agent, user_message, chat_history,
                    file_content, _shared
                )
                all_results.append(result)
                total_tokens_in += result.get("tokens_in", 0)
                total_tokens_out += result.get("tokens_out", 0)

                # Drain events
                while not self._event_queue.empty():
                    try:
                        yield self._event_queue.get_nowait()
                    except queue.Empty:
                        break

        # Handoff: emit summary
        if self.handoff_manager and _HANDOFF_AVAILABLE:
            try:
                summary_sse = self.handoff_manager.format_summary_sse()
                yield self._sse(summary_sse)
                logger.info(f"[Handoff] Summary: {self.handoff_manager.get_summary()}")
            except Exception as e:
                logger.error(f"[Handoff] summary error: {e}")
        # Emit parallel completion
        yield self._sse({
            "type": "parallel_complete",
            "agents_completed": len(all_results),
            "agents_total": len(agents_to_run),
            "tokens_in": total_tokens_in,
            "tokens_out": total_tokens_out,
            "results_summary": {
                r["agent"]: {
                    "name": r["name"],
                    "completed": r.get("completed", False),
                    "actions_count": len(r.get("actions", [])),
                    "tokens": r.get("tokens_in", 0) + r.get("tokens_out", 0)
                }
                for r in all_results
            }
        })

    def run_sequential(self, user_message: str, chat_history: list = None,
                       file_content: str = None,
                       pipeline: list = None,
                       mode: str = "chat") -> Generator[str, None, None]:
        """
        Run agents sequentially (each gets results from previous).
        Better for complex tasks where order matters.
        
        Args:
            user_message: User's task
            pipeline: Ordered list of agent keys
            mode: Task mode
        
        Yields: SSE events
        """
        if chat_history is None:
            chat_history = []

        if not pipeline:
            agents = select_agents_for_task(user_message, mode, max_agents=4)
            pipeline = [a.get("key", a.get("role", "")) for a in agents]

        yield self._sse({
            "type": "pipeline_start",
            "agents": [SPECIALIZED_AGENTS.get(k, {}).get("name", k) for k in pipeline],
            "count": len(pipeline)
        })

        total_tokens_in = 0
        total_tokens_out = 0
        all_results = []

        for agent_key in pipeline:
            if self._stop_requested:
                yield self._sse({"type": "stopped", "text": "Остановлено пользователем"})
                return

            agent_config = SPECIALIZED_AGENTS.get(agent_key)
            if not agent_config:
                continue

            # ПАТЧ W2-5: Формируем улучшенный handoff context с scratchpad
            _shared = dict(self._agent_results)
            _scratchpad_ctx = self.shared_scratchpad.get_context_for_agent(agent_key)
            if _scratchpad_ctx:
                _shared["__scratchpad__"] = _scratchpad_ctx
            if self.handoff_manager and _HANDOFF_AVAILABLE:
                _handoff_ctx = self.handoff_manager.get_context_for_next_agent(agent_key)
                if _handoff_ctx:
                    _shared["__handoff__"] = _handoff_ctx

            result = self._run_single_agent(
                agent_key, agent_config, user_message, chat_history,
                file_content, _shared
            )
            all_results.append(result)
            total_tokens_in += result.get("tokens_in", 0)
            total_tokens_out += result.get("tokens_out", 0)

            # Drain events
            while not self._event_queue.empty():
                try:
                    yield self._event_queue.get_nowait()
                except queue.Empty:
                    break

        yield self._sse({
            "type": "pipeline_complete",
            "agents_completed": len(all_results),
            "tokens_in": total_tokens_in,
            "tokens_out": total_tokens_out
        })
