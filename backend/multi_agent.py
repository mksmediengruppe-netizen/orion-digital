"""
ORION Digital — Multi-Agent Loop.
Extracted from agent_loop.py (TASK 7).
"""
import logging
import json
import time
import traceback
from typing import Dict, List, Optional

logger = logging.getLogger("multi_agent")

# Import from agent_loop
from agent_loop import AgentLoop, TOOLS_SCHEMA, AGENT_SYSTEM_PROMPT, get_system_prompt

# ══════════════════════════════════════════════════════════════
# ██ MULTI-AGENT LOOP ██
# ══════════════════════════════════════════════════════════════════

class MultiAgentLoop(AgentLoop):
    """
    Extended agent loop with multi-agent architecture:
    Architect -> Coder -> Reviewer -> QA
    Each agent has its own system prompt and can use tools.
    Inherits retry, idempotency, and self-healing from AgentLoop.
    """

    AGENTS = {
        "architect": {
            "name": "Архитектор",
            "emoji": "🏗️",
            "prompt_suffix": """Ты — Архитектор. Проанализируй задачу и создай план:
1. Какие файлы нужно создать/изменить
2. Какие команды выполнить
3. Порядок действий
4. Как проверить результат
Используй инструменты для исследования текущего состояния (ssh_execute для ls, cat и т.д.)."""
        },
        "coder": {
            "name": "Кодер",
            "emoji": "💻",
            "prompt_suffix": """Ты — Кодер. Реализуй план архитектора:
1. Создавай файлы через file_write
2. Выполняй команды через ssh_execute
3. Устанавливай зависимости
4. Деплой код на сервер
Пиши production-ready код. Используй инструменты для РЕАЛЬНОГО создания файлов и выполнения команд."""
        },
        "reviewer": {
            "name": "Ревьюер",
            "emoji": "🔍",
            "prompt_suffix": """Ты — Ревьюер. Проверь что сделал Кодер:
1. Прочитай созданные файлы через file_read
2. Проверь что сервисы работают через ssh_execute и browser_check_site
3. Если есть ошибки — исправь через file_write и ssh_execute
4. Убедись что всё соответствует требованиям."""
        },
        "qa": {
            "name": "QA Инженер",
            "emoji": "✅",
            "prompt_suffix": """Ты — QA Инженер. Финальная проверка:
1. Проверь доступность через browser_check_site
2. Проверь API через browser_check_api
3. Проверь логи через ssh_execute
4. Если всё работает — вызови task_complete с описанием результата.
Если есть проблемы — исправь их."""
        }
    }

    def run_stream(self, user_message, chat_history=None, file_content=None, ssh_credentials=None):
        """Override run_stream to handle orchestrator sequential pipeline."""
        import logging
        _mlog = logging.getLogger('agent_loop')
        _mlog.info(f'[MULTI] run_stream CALLED, class={self.__class__.__name__}')
        if ssh_credentials:
            self.ssh_credentials = ssh_credentials
        
        plan = getattr(self, '_orchestrator_plan', None)
        _mlog.info(f'[MULTI] plan exists={plan is not None}, mode={plan.get("mode") if plan else None}, phases={len(plan.get("phases",[])) if plan else 0}')
        if plan and plan.get('mode') == 'multi_sequential' and plan.get('phases'):
            _mlog.info(f'[MULTI] STARTING sequential pipeline with {len(plan["phases"])} phases')
            yield from self._run_sequential_pipeline(user_message, chat_history, file_content, plan)
        else:
            # Fallback to parent AgentLoop.run_stream
            yield from super().run_stream(user_message, chat_history, file_content, ssh_credentials)

    def _run_sequential_pipeline(self, user_message, chat_history, file_content, plan):
        """Execute orchestrator phases sequentially, each as a separate agent loop."""
        import json as _json
        import logging as _plog
        _plog.info(f"[Pipeline] _run_sequential_pipeline ENTERED with {len(plan.get('phases', []))} phases")
        phases = plan.get('phases', [])
        total_phases = len(phases)
        
        # Send plan to frontend
        yield self._sse({
            "type": "task_steps",
            "steps": [{"name": p["name"], "agent": p.get("agents", ["developer"])[0], "status": "pending"} for p in phases],
            "total": total_phases
        })
        
        context = user_message
        if file_content:
            context = f"{file_content}\n\n---\n\nЗадача:\n{user_message}"
        if self.ssh_credentials.get('host'):
            context += f"\n\n[Сервер: {self.ssh_credentials['host']}, user: {self.ssh_credentials.get('username', 'root')}]"
        
        phase_results = {}
        
        for idx, phase in enumerate(phases):
            if self._stop_requested:
                yield self._sse({"type": "stopped", "text": "Остановлено пользователем"})
                return
            
            phase_name = phase.get('name', f'Phase {idx+1}')
            phase_agents = phase.get('agents', ['developer'])
            phase_desc = phase.get('description', '')
            agent_key = phase_agents[0] if phase_agents else 'developer'
            _plog.info(f"[Pipeline] Starting phase {idx+1}/{total_phases}: {phase_name} (agent: {agent_key})")
            
            # Notify frontend
            yield self._sse({
                "type": "step_update",
                "step_index": idx,
                "status": "running",
                "name": phase_name
            })
            yield self._sse({
                "type": "agent_start",
                "agent": phase_name,
                "emoji": self._agent_emoji(agent_key),
                "role": agent_key
            })
            
            # Switch model for this phase agent
            # For Pro/Architect: keep ONE model for entire pipeline (no switching)
            _current_orion_mode = getattr(self, 'orion_mode', getattr(self, '_orion_mode', 'turbo_standard'))
            if _current_orion_mode in PRO_MODES:
                _plog.info(f"[Pipeline] Pro/Architect mode: keeping model {self.model} (no switch)")
            else:
                try:
                    from orchestrator_v2 import get_model_for_agent
                    _phase_model = get_model_for_agent(agent_key, _current_orion_mode)
                    if _phase_model and isinstance(_phase_model, str):
                        _old_model = self.model
                        self.model = _phase_model
                        _plog.info(f"[Pipeline] Phase model: {agent_key} → {_phase_model}")
                    else:
                        _plog.warning(f"[Pipeline] get_model_for_agent returned None for {agent_key}, keeping {self.model}")
                except Exception as _me:
                    _plog.warning(f"[Pipeline] Could not switch model for {agent_key}: {_me}, keeping {self.model}")
            
            # Build phase prompt
            phase_prompt = f"""ТЕКУЩАЯ ФАЗА ({idx+1}/{total_phases}): {phase_name}

ОПИСАНИЕ ФАЗЫ: {phase_desc}

ОРИГИНАЛЬНАЯ ЗАДАЧА: {context}"""
            
            if phase_results:
                prev = "\n\n".join([f"=== {k} ===\n{v[:2000]}" for k, v in phase_results.items()])
                phase_prompt += f"\n\nРЕЗУЛЬТАТЫ ПРЕДЫДУЩИХ ФАЗ:\n{prev}"
            
            phase_prompt += f"""\n\nВАЖНО:
- Ты выполняешь ТОЛЬКО эту фазу: {phase_name}
- Используй инструменты (ssh_execute, file_write, browser_navigate и т.д.) для РЕАЛЬНОГО выполнения
- Не просто описывай что нужно сделать — ДЕЛАЙ
- Когда фаза выполнена — вызови task_complete"""
            
            # Get agent-specific prompt
            agent_prompt_extra = ""
            try:
                from orchestrator_v2 import AGENT_PROMPTS
                agent_prompt_extra = AGENT_PROMPTS.get(agent_key, "")
            except:
                pass
            
            # Build messages for this phase
            system_prompt = get_system_prompt(getattr(self, "orion_mode", "turbo_standard"))
            if agent_prompt_extra:
                system_prompt += "\n\n" + agent_prompt_extra
            if hasattr(self, '_orchestrator_prompt') and self._orchestrator_prompt:
                system_prompt += "\n\n" + self._orchestrator_prompt
            
            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": phase_prompt}
            ]
            
            # Run agent loop for this phase
            phase_text = ""
            iteration = 0
            max_iterations = 20
            
            while iteration < max_iterations and not self._stop_requested:
                iteration += 1
                yield self._sse({"type": "heartbeat", "message": "agent_thinking"})
                tool_calls_received = None
                ai_text = ""
                import logging as _pipe_log
                _pipe_log.info(f"[Pipeline] Phase {phase_name} iteration {iteration}/{max_iterations}")
                
                try:
                    for event in self._call_ai_stream(messages, tools=TOOLS_SCHEMA):
                        if event["type"] == "text_delta":
                            ai_text += event["text"]
                            phase_text += event["text"]
                            yield self._sse({"type": "content", "text": event["text"], "agent": phase_name})
                        elif event["type"] == "tool_calls":
                            tool_calls_received = event["tool_calls"]
                except Exception as e:
                    logging.error(f"[Pipeline] Phase {phase_name} AI call error: {e}")
                    yield self._sse({"type": "error", "text": f"Ошибка в фазе {phase_name}: {str(e)}"})
                    break
                
                if ai_text:
                    messages.append({"role": "assistant", "content": ai_text})
                
                if not tool_calls_received:
                    break
                
                # Process tool calls — BUG-9 FIX: tool_calls from _call_ai_stream already have OpenAI format
                # Format: {"id": ..., "type": "function", "function": {"name": ..., "arguments": "..."}}
                messages.append({"role": "assistant", "content": ai_text, "tool_calls": tool_calls_received})
                
                for tc in tool_calls_received:
                    tool_name = tc["function"]["name"]
                    tool_args_str = tc["function"].get("arguments", "{}")
                    try:
                        tool_args = _json.loads(tool_args_str) if isinstance(tool_args_str, str) else tool_args_str
                    except _json.JSONDecodeError:
                        tool_args = {}
                    tool_id = tc["id"]
                    
                    # Check for task_complete
                    if tool_name == "task_complete":
                        phase_text += "\n[ФАЗА ЗАВЕРШЕНА]"
                        yield self._sse({"type": "tool_start", "tool": "task_complete", "args": tool_args})
                        messages.append({"role": "tool", "tool_call_id": tool_id, "content": "Phase completed"})
                        # PATCH 6: Quality Gate after pipeline phase with rework
                        if hasattr(self, '_check_quality_gate'):
                            _qg = self._check_quality_gate(phase_name, self.actions_log)
                            if _qg["passed"]:
                                logging.info(f"[QualityGate] Phase '{phase_name}' PASSED")
                                yield self._sse({"type": "quality_gate", "phase": phase_name, "passed": True})
                            else:
                                logging.warning(f"[QualityGate] Phase '{phase_name}' FAILED: {_qg['reason']}")
                                yield self._sse({"type": "quality_gate", "phase": phase_name, "passed": False, "reason": _qg["reason"]})
                                # REWORK: retry phase once if not already retried
                                if not phase.get('_qg_retried'):
                                    phase['_qg_retried'] = True
                                    logging.warning(f"[QualityGate] Rework: retrying phase '{phase_name}'")
                                    yield self._sse({"type": "quality_gate_rework", "phase": phase_name,
                                                    "reason": _qg["reason"],
                                                    "text": f"♻️ Quality Gate: повторяю фазу '{phase_name}' (причина: {_qg['reason']})"})
                                    messages.append({"role": "system",
                                        "content": f"[Quality Gate] Фаза '{phase_name}' не прошла проверку качества. "
                                                   f"Причина: {_qg['reason']}. "
                                                   f"Исправь проблему и снова вызови task_complete."})
                                    # Reset iteration counter to allow rework
                                    iteration = 0
                                    tool_calls_received = {}  # Don't break — continue loop
                                    continue
                                else:
                                    logging.warning(f"[QualityGate] Phase '{phase_name}' failed rework too, continuing")
                        tool_calls_received = None
                        break
                    
                    _display_args = {k: str(v)[:100] for k, v in tool_args.items()} if isinstance(tool_args, dict) else {}
                    yield self._sse({"type": "tool_start", "tool": tool_name, "args": _display_args})
                    
                    try:
                        result = self._execute_tool(tool_name, tool_args)
                    except Exception as e:
                        result = {"error": str(e)}
                    
                    result_preview = self._preview_result(tool_name, result)
                    yield self._sse({"type": "tool_result", "tool": tool_name, "result": result_preview})
                    
                    _result_clean = {k: ("[screenshot sent to user]" if k == "screenshot" else v) for k, v in result.items()}
                    result_str = _json.dumps(_result_clean, ensure_ascii=False)
                    if len(result_str) > self.MAX_TOOL_OUTPUT:
                        result_str = result_str[:self.MAX_TOOL_OUTPUT] + "..."
                    
                    messages.append({"role": "tool", "tool_call_id": tool_id, "content": result_str})
                
                if tool_calls_received is None:
                    break  # task_complete was called
            
            phase_results[phase_name] = phase_text[:3000]
            
            yield self._sse({
                "type": "step_update",
                "step_index": idx,
                "status": "done",
                "name": phase_name
            })
            yield self._sse({
                "type": "agent_complete",
                "agent": phase_name,
                "role": agent_key
            })


            # ── PREMIUM DESIGN QUALITY CHECK v2 (MiniMax→Opus→MiniMax pipeline) ────────
            # Initialize _is_deploy_phase here for PremiumQC (also defined again below for standard QC)
            _is_deploy_phase = (
                agent_key.lower() in ('devops', 'deployer', 'deploy') or
                any(kw in phase_name.lower() for kw in ('деплой', 'deploy', 'настройк', 'сервер', 'nginx'))
            )
            _qc_host = self.ssh_credentials.get('host', '')
            if _is_deploy_phase and _qc_host and getattr(self, 'premium_design', False):
                import logging as _pqc_log, requests as _pqc_req, base64 as _pqc_b64
                _pqc_log.info("[PremiumQC v2] Starting MiniMax→Opus→MiniMax pipeline")
                yield self._sse({"type": "content", "text": "\n\n✨ **Premium QC v2**: MiniMax создаёт → Opus проверяет → MiniMax исправляет\n", "agent": "Premium QC"})
                _pqc_api_key = self.api_key
                _pqc_headers = {"Authorization": f"Bearer {_pqc_api_key}", "Content-Type": "application/json", "HTTP-Referer": "https://orion.mksitdev.ru"}
                _pqc_minimax_model = "minimax/minimax-m2.5"
                _pqc_opus_model = "anthropic/claude-opus-4"
                _pqc_html_content = _qc_html_content if '_qc_html_content' in dir() else None
                _pqc_site_url = f"http://{_qc_host}"
                
                def _pqc_take_screenshot(url):
                    """Take screenshot via BrowserAgent and return base64."""
                    try:
                        _ss_result = self._execute_tool('browser_navigate', {'url': url})
                        _ss = _ss_result.get('screenshot', '')
                        return _ss if _ss else None
                    except Exception as _e:
                        _pqc_log.warning(f"[PremiumQC v2] Screenshot error: {_e}")
                        return None
                
                def _pqc_deploy_html(html_content, path='/var/www/html/index.html'):
                    """Deploy HTML to server."""
                    try:
                        self._execute_tool('file_write', {
                            'host': _qc_host,
                            'username': self.ssh_credentials.get('username', 'root'),
                            'password': self.ssh_credentials.get('password', ''),
                            'path': path,
                            'content': html_content
                        })
                        return True
                    except Exception as _e:
                        _pqc_log.warning(f"[PremiumQC v2] Deploy error: {_e}")
                        return False
                
                try:
                    # ── STEP 1: MiniMax creates full HTML ($0.50-1.00) ──
                    yield self._sse({"type": "content", "text": "  📝 Шаг 1/4: MiniMax создаёт полный HTML...\n", "agent": "Premium QC"})
                    if not _pqc_html_content:
                        _mm_create = _pqc_req.post(self.api_url, headers=_pqc_headers, json={
                            "model": _pqc_minimax_model,
                            "messages": [{"role": "user", "content": (
                                "Create a complete, stunning single-page HTML website. "
                                "Requirements: Tailwind CSS CDN, modern gradients, smooth animations, "
                                "responsive design, Inter font, glassmorphism effects. "
                                "Return ONLY complete HTML starting with <!DOCTYPE html>."
                            )}],
                            "temperature": 0.7, "max_tokens": 16000, "stream": False
                        }, timeout=120)
                        _mm_html = _mm_create.json().get("choices", [{}])[0].get("message", {}).get("content", "")
                        if '```html' in _mm_html:
                            _mm_html = _mm_html.split('```html')[1].split('```')[0].strip()
                        elif '```' in _mm_html:
                            _mm_html = _mm_html.split('```')[1].split('```')[0].strip()
                        if _mm_html and _mm_html.strip().startswith('<'):
                            _pqc_html_content = _mm_html
                            _pqc_deploy_html(_pqc_html_content)
                            yield self._sse({"type": "content", "text": "  ✅ MiniMax создал HTML, задеплоен\n", "agent": "Premium QC"})
                    
                    # ── STEP 2: MiMo deploys + screenshot ──
                    yield self._sse({"type": "content", "text": "  📸 Шаг 2/4: Скриншот после деплоя...\n", "agent": "Premium QC"})
                    _ss1 = _pqc_take_screenshot(_pqc_site_url)
                    
                    # ── STEP 3: Opus reviews screenshot → issues list ($0.50) ──
                    _opus_issues = ""
                    if _ss1:
                        yield self._sse({"type": "content", "text": "  🔍 Шаг 3/4: Opus анализирует дизайн...\n", "agent": "Premium QC"})
                        _opus_review = _pqc_req.post(self.api_url, headers=_pqc_headers, json={
                            "model": _pqc_opus_model,
                            "messages": [{"role": "user", "content": [
                                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{_ss1}"}},
                                {"type": "text", "text": (
                                    "You are a senior UI/UX designer. Review this website screenshot critically.\n"
                                    "Rate 1-10 and list SPECIFIC improvements needed.\n"
                                    "Format:\nSCORE: X/10\nISSUES:\n- issue1\n- issue2\nPRIORITY_FIXES:\n- fix1\n- fix2"
                                )}
                            ]}],
                            "temperature": 0.3, "max_tokens": 1000, "stream": False
                        }, timeout=60)
                        _opus_issues = _opus_review.json().get("choices", [{}])[0].get("message", {}).get("content", "")
                        import re as _pqc_re
                        _score_m = _pqc_re.search(r'SCORE:\s*(\d+)', _opus_issues)
                        _score = int(_score_m.group(1)) if _score_m else 5
                        yield self._sse({"type": "content", "text": f"  📋 Opus: оценка {_score}/10\n{_opus_issues[:300]}\n", "agent": "Premium QC"})
                        
                        # ── STEP 4: MiniMax fixes based on Opus list ($0.30) ──
                        if _score < 9 and _pqc_html_content:
                            yield self._sse({"type": "content", "text": "  🔧 Шаг 4/4: MiniMax исправляет по списку Opus...\n", "agent": "Premium QC"})
                            _mm_fix = _pqc_req.post(self.api_url, headers=_pqc_headers, json={
                                "model": _pqc_minimax_model,
                                "messages": [{"role": "user", "content": (
                                    f"Fix this HTML based on these design issues:\n{_opus_issues}\n\n"
                                    "Apply ALL fixes. Return ONLY complete fixed HTML starting with <!DOCTYPE html>.\n\n"
                                    f"Current HTML:\n{_pqc_html_content[:14000]}"
                                )}],
                                "temperature": 0.3, "max_tokens": 16000, "stream": False
                            }, timeout=120)
                            _fixed_html = _mm_fix.json().get("choices", [{}])[0].get("message", {}).get("content", "")
                            if '```html' in _fixed_html:
                                _fixed_html = _fixed_html.split('```html')[1].split('```')[0].strip()
                            elif '```' in _fixed_html:
                                _fixed_html = _fixed_html.split('```')[1].split('```')[0].strip()
                            if _fixed_html and _fixed_html.strip().startswith('<'):
                                _pqc_html_content = _fixed_html
                                _pqc_deploy_html(_pqc_html_content)
                                yield self._sse({"type": "content", "text": "  ✅ MiniMax исправил HTML, задеплоен\n", "agent": "Premium QC"})
                                # ── Opus final check ($0.50) ──
                                _ss2 = _pqc_take_screenshot(_pqc_site_url)
                                if _ss2:
                                    _opus_final = _pqc_req.post(self.api_url, headers=_pqc_headers, json={
                                        "model": _pqc_opus_model,
                                        "messages": [{"role": "user", "content": [
                                            {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{_ss2}"}},
                                            {"type": "text", "text": "Final design check. Rate 1-10. Is it Dribbble/Awwwards quality? SCORE: X/10\nVERDICT: ..."}
                                        ]}],
                                        "temperature": 0.2, "max_tokens": 300, "stream": False
                                    }, timeout=45)
                                    _final_review = _opus_final.json().get("choices", [{}])[0].get("message", {}).get("content", "")
                                    _final_score_m = _pqc_re.search(r'SCORE:\s*(\d+)', _final_review)
                                    _final_score = int(_final_score_m.group(1)) if _final_score_m else 8
                                    yield self._sse({"type": "content", "text": f"  🏆 Opus финальная оценка: {_final_score}/10\n{_final_review[:200]}\n", "agent": "Premium QC"})
                        else:
                            yield self._sse({"type": "content", "text": f"  🏆 Дизайн одобрен Opus — оценка {_score}/10!\n", "agent": "Premium QC"})
                    yield self._sse({"type": "content", "text": "\n✅ **Premium QC v2 завершён** (~$2-3 вместо $40)\n", "agent": "Premium QC"})
                    _pqc_log.info("[PremiumQC v2] Pipeline completed")
                except Exception as _pqc_v2_err:
                    _pqc_log.warning(f"[PremiumQC v2] Error: {_pqc_v2_err}")
                    yield self._sse({"type": "content", "text": f"  ⚠️ PremiumQC v2 ошибка: {_pqc_v2_err}\n", "agent": "Premium QC"})
            # ── END PREMIUM DESIGN QUALITY CHECK ──────────────────────────────────

            # ── QUALITY CHECK CYCLE: after deploy phases (PATCH-13: + mobile screenshot) ──
            # Detect if this was a deploy phase by agent key or phase name
            _is_deploy_phase = (
                agent_key.lower() in ('devops', 'deployer', 'deploy') or
                any(kw in phase_name.lower() for kw in ('деплой', 'deploy', 'настройк', 'сервер', 'nginx'))
            )
            # Only run quality check if there's a server URL available
            _qc_host = self.ssh_credentials.get('host', '')
            if _is_deploy_phase and _qc_host and _current_orion_mode not in PRO_MODES:
                import logging as _qc_log
                _qc_log.info(f"[QualityCheck] Starting post-deploy quality check for phase: {phase_name}")
                yield self._sse({"type": "content", "text": "\n\n🔍 **Quality Check**: Проверяю результат деплоя...\n", "agent": "Quality Check"})

                _qc_url = f"http://{_qc_host}"
                _qc_max_iterations = 2
                _qc_iteration = 0
                _qc_html_content = None  # Will store current HTML from phase_results

                # Extract HTML content from phase results (designer/developer phases)
                for _prev_phase_name, _prev_phase_text in phase_results.items():
                    if any(kw in _prev_phase_name.lower() for kw in ('дизайн', 'верстк', 'разработк', 'design', 'develop')):
                        _qc_html_content = _prev_phase_text
                        break

                while _qc_iteration < _qc_max_iterations:
                    _qc_iteration += 1
                    _qc_log.info(f"[QualityCheck] Iteration {_qc_iteration}/{_qc_max_iterations}")

                    # Step 1: MiMo (current model = hands model) takes screenshot
                    yield self._sse({"type": "content", "text": f"🌐 Открываю {_qc_url} для проверки...\n", "agent": "Quality Check"})
                    try:
                        _nav_result = self._execute_tool('browser_navigate', {'url': _qc_url})
                        _screenshot_b64 = _nav_result.get('screenshot', '')
                        if not _screenshot_b64:
                            # Try explicit screenshot
                            _ss_result = self._execute_tool('browser_screenshot', {})
                            _screenshot_b64 = _ss_result.get('screenshot', '')
                    except Exception as _qc_e:
                        _qc_log.warning(f"[QualityCheck] Browser error: {_qc_e}")
                        break

                    if not _screenshot_b64:
                        _qc_log.warning("[QualityCheck] No screenshot obtained, skipping quality check")
                        break

                    # Step 2: Send screenshot to MiniMax for design review
                    yield self._sse({"type": "content", "text": "🧠 MiniMax проверяет дизайн...\n", "agent": "Quality Check"})
                    _b64_clean = _screenshot_b64
                    if 'base64,' in _b64_clean:
                        _b64_clean = _b64_clean.split('base64,')[1]

                    _review_messages = [
                        {"role": "user", "content": [
                            {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{_b64_clean}"}},
                            {"type": "text", "text": (
                                "Посмотри на этот скриншот сайта. "
                                "CSS работает? Дизайн выглядит правильно? "
                                "Если нет — опиши конкретно что не так и напиши ИСПРАВИТЬ. "
                                "Если всё хорошо — напиши ХОРОШО. "
                                "Отвечай кратко."
                            )}
                        ]}
                    ]

                    try:
                        _review_headers = {
                            "Authorization": f"Bearer {self.api_key}",
                            "Content-Type": "application/json",
                            "HTTP-Referer": "https://orion.mksitdev.ru",
                            "X-Title": "ORION Digital v1.0"
                        }
                        _review_payload = {
                            "model": "minimax/minimax-m2.5",
                            "messages": _review_messages,
                            "temperature": 0.1,
                            "max_tokens": 800,
                            "stream": False,
                        }
                        import requests as _qc_requests
                        _review_resp = _qc_requests.post(
                            self.api_url, headers=_review_headers,
                            json=_review_payload, timeout=30
                        )
                        _review_text = ""
                        if _review_resp.status_code == 200:
                            _review_text = _review_resp.json().get("choices", [{}])[0].get("message", {}).get("content", "")
                    except Exception as _rv_e:
                        _qc_log.warning(f"[QualityCheck] MiniMax review error: {_rv_e}")
                        break

                    _qc_log.info(f"[QualityCheck] MiniMax review: {_review_text[:200]}")
                    yield self._sse({"type": "content", "text": f"💬 MiniMax: {_review_text[:300]}\n", "agent": "Quality Check"})

                    # Step 3: Check if MiniMax says there's a problem
                    _needs_fix = 'ИСПРАВИТЬ' in _review_text.upper() or 'FIX' in _review_text.upper() or 'ИСПРАВЬ' in _review_text.upper()
                    if not _needs_fix:
                        _qc_log.info("[QualityCheck] MiniMax approved the design, no fix needed")
                        yield self._sse({"type": "content", "text": "✅ Дизайн одобрен MiniMax\n", "agent": "Quality Check"})
                        break

                    # Step 4: MiniMax fixes the HTML
                    yield self._sse({"type": "content", "text": "🔧 MiniMax исправляет HTML...\n", "agent": "Quality Check"})
                    _fix_messages = [
                        {"role": "user", "content": [
                            {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{_b64_clean}"}},
                            {"type": "text", "text": (
                                f"Проблема: {_review_text}\n\n"
                                "Исправь HTML/CSS. Верни ТОЛЬКО полный исправленный HTML файл, без объяснений. "
                                "Начни с <!DOCTYPE html> и заверши </html>."
                                + (f"\n\nТекущий HTML:\n{_qc_html_content[:8000]}" if _qc_html_content else "")
                            )}
                        ]}
                    ]

                    try:
                        _fix_payload = {
                            "model": "minimax/minimax-m2.5",
                            "messages": _fix_messages,
                            "temperature": 0.3,
                            "max_tokens": 16000,
                            "stream": False,
                        }
                        _fix_resp = _qc_requests.post(
                            self.api_url, headers=_review_headers,
                            json=_fix_payload, timeout=60
                        )
                        _fixed_html = ""
                        if _fix_resp.status_code == 200:
                            _fixed_html = _fix_resp.json().get("choices", [{}])[0].get("message", {}).get("content", "")
                            # Extract HTML if wrapped in markdown code block
                            if '```html' in _fixed_html:
                                _fixed_html = _fixed_html.split('```html')[1].split('```')[0].strip()
                            elif '```' in _fixed_html:
                                _fixed_html = _fixed_html.split('```')[1].split('```')[0].strip()
                    except Exception as _fx_e:
                        _qc_log.warning(f"[QualityCheck] MiniMax fix error: {_fx_e}")
                        break

                    if not _fixed_html or not _fixed_html.strip().startswith('<'):
                        _qc_log.warning("[QualityCheck] MiniMax did not return valid HTML")
                        break

                    # Step 5: MiMo redeploys the fixed HTML
                    yield self._sse({"type": "content", "text": "🚀 Деплою исправленный HTML...\n", "agent": "Quality Check"})

                    # Find the deployed path from phase_results or use default
                    _deploy_path = "/var/www/html/index.html"
                    for _pr_name, _pr_text in phase_results.items():
                        import re as _qc_re
                        _path_match = _qc_re.search(r'/var/www/[\w./\-]+\.html', _pr_text)
                        if _path_match:
                            _deploy_path = _path_match.group(0)
                            break

                    # Switch to MiMo (hands model) for deployment
                    _saved_model = self.model
                    try:
                        from orchestrator_v2 import get_model_for_agent
                        self.model = get_model_for_agent('devops', _current_orion_mode)
                    except Exception:
                        pass

                    _deploy_result = self._execute_tool('file_write', {
                        'host': _qc_host,
                        'username': self.ssh_credentials.get('username', 'root'),
                        'password': self.ssh_credentials.get('password', ''),
                        'path': _deploy_path,
                        'content': _fixed_html
                    })
                    self.model = _saved_model

                    if _deploy_result.get('success'):
                        _qc_html_content = _fixed_html  # Update for next iteration
                        yield self._sse({"type": "content", "text": f"✅ Исправленный HTML задеплоен в {_deploy_path}\n", "agent": "Quality Check"})
                    else:
                        _qc_log.warning(f"[QualityCheck] Redeploy failed: {_deploy_result}")
                        break

                _qc_log.info(f"[QualityCheck] Completed after {_qc_iteration} iteration(s)")
            # ── END QUALITY CHECK CYCLE ──────────────────────────────────────────────
            # ── AUTO-PHOTO CHECK (PATCH-14): find missing images and generate ──────────
            if _is_deploy_phase and _qc_host:
                import logging as _ap_log
                _ap_log.info("[AutoPhoto] Starting auto-photo check")
                yield self._sse({"type": "content", "text": "\n🖼️ **Auto-Photo**: Проверяю изображения на сайте...\n", "agent": "Auto Photo"})
                try:
                    # Get HTML content from server
                    _ap_html_result = self._execute_tool('ssh_execute', {
                        'host': _qc_host,
                        'username': self.ssh_credentials.get('username', 'root'),
                        'password': self.ssh_credentials.get('password', ''),
                        'command': 'cat /var/www/html/index.html 2>/dev/null || cat /var/www/*/index.html 2>/dev/null | head -500'
                    })
                    _ap_html = _ap_html_result.get('output', '') if _ap_html_result.get('success') else ''
                    
                    # Find all img src with placeholder or missing images
                    import re as _ap_re
                    # Fixed: use compiled pattern to avoid quote escaping issues
                    _ap_pattern = re.compile(r'<img[^>]+src=[\x22\x27]([^\x22\x27]*(?:placehold|placeholder|photo\d|image\d|hero|about|team|service)[^\x22\x27]*)[\x22\x27]', re.IGNORECASE)
                    _placeholder_imgs = _ap_pattern.findall(_ap_html)
                    
                    if _placeholder_imgs:
                        _ap_log.info(f"[AutoPhoto] Found {len(_placeholder_imgs)} placeholder images")
                        yield self._sse({"type": "content", "text": f"📸 Найдено {len(_placeholder_imgs)} placeholder изображений. Генерирую AI фото...\n", "agent": "Auto Photo"})
                        
                        _generated_count = 0
                        for _img_idx, _img_src in enumerate(_placeholder_imgs[:6]):  # Max 6 images
                            # Generate descriptive prompt based on image context
                            _img_context = _img_src.lower()
                            _prompts = {
                                'hero': 'Professional modern office interior with natural lighting, minimalist design, 8k quality, photorealistic',
                                'about': 'Professional team meeting in modern conference room, diverse people collaborating, warm lighting, 8k quality',
                                'team': 'Professional portrait of business person in modern office, confident smile, soft lighting, 8k quality',
                                'service': 'Abstract technology concept with glowing blue connections and data visualization, dark background, 8k quality',
                            }
                            _prompt = 'Professional high quality business photo, modern clean aesthetic, 8k quality photorealistic'
                            for _key, _val in _prompts.items():
                                if _key in _img_context:
                                    _prompt = _val
                                    break
                            
                            try:
                                _gen_result = self._execute_tool('generate_image', {
                                    'prompt': _prompt,
                                    'width': 800,
                                    'height': 600
                                })
                                if _gen_result.get('success') and _gen_result.get('url'):
                                    _generated_count += 1
                                    yield self._sse({"type": "content", "text": f"  ✅ Фото {_generated_count} сгенерировано\n", "agent": "Auto Photo"})
                            except Exception as _gen_e:
                                _ap_log.warning(f"[AutoPhoto] generate_image failed: {_gen_e}")
                        
                        if _generated_count > 0:
                            yield self._sse({"type": "content", "text": f"🖼️ Сгенерировано {_generated_count} AI фото\n", "agent": "Auto Photo"})
                    else:
                        yield self._sse({"type": "content", "text": "✅ Placeholder изображений не найдено\n", "agent": "Auto Photo"})
                except Exception as _ap_e:
                    _ap_log.warning(f"[AutoPhoto] Error: {_ap_e}")
            # ── END AUTO-PHOTO CHECK ──────────────────────────────────────────────
            # ── TAILWIND CDN CHECK (PATCH-15) ──────────────────────────────
            if _is_deploy_phase and _qc_host:
                import logging as _tw_log
                try:
                    _tw_result = self._execute_tool('ssh_execute', {
                        'host': _qc_host,
                        'username': self.ssh_credentials.get('username', 'root'),
                        'password': self.ssh_credentials.get('password', ''),
                        'command': 'grep -l "cdn.tailwindcss" /var/www/html/index.html /var/www/*/index.html 2>/dev/null || echo "NO_TAILWIND"'
                    })
                    _tw_output = _tw_result.get('output', '') if _tw_result.get('success') else 'NO_TAILWIND'
                    if 'NO_TAILWIND' in _tw_output:
                        _tw_log.info("[TailwindCheck] Tailwind CDN not found, adding...")
                        yield self._sse({"type": "content", "text": "⚠️ Tailwind CDN не найден — добавляю...\n", "agent": "Tailwind Check"})
                        # Add Tailwind CDN to head
                        self._execute_tool('ssh_execute', {
                            'host': _qc_host,
                            'username': self.ssh_credentials.get('username', 'root'),
                            'password': self.ssh_credentials.get('password', ''),
                            'command': 'sed -i \'s|</head>|<script src="https://cdn.tailwindcss.com"></script>\n</head>|\' /var/www/html/index.html 2>/dev/null'
                        })
                        yield self._sse({"type": "content", "text": "✅ Tailwind CDN добавлен\n", "agent": "Tailwind Check"})
                    else:
                        yield self._sse({"type": "content", "text": "✅ Tailwind CDN подключён\n", "agent": "Tailwind Check"})
                except Exception as _tw_e:
                    _tw_log.warning(f"[TailwindCheck] Error: {_tw_e}")
            # ── END TAILWIND CDN CHECK ──────────────────────────────────────



        # All phases complete
        yield self._sse({
            "type": "task_complete",
            "text": f"Все {total_phases} фаз выполнены.",
            "phases_completed": total_phases
        })
    
    def _agent_emoji(self, agent_key):
        """Get emoji for agent type."""
        emojis = {
            'devops': '🔧', 'designer': '🎨', 'developer': '💻',
            'tester': '🧪', 'analyst': '📊', 'copywriter': '✍️',
            'architect': '🏗️'
        }
        return emojis.get(agent_key, '🤖')

    def run_multi_agent_stream(self, user_message, chat_history=None, file_content=None):
        """Run multi-agent pipeline with streaming."""
        if chat_history is None:
            chat_history = []

        context = user_message
        if file_content:
            context = f"{file_content}\n\n---\n\nЗадача:\n{user_message}"

        if self.ssh_credentials.get("host"):
            context += f"\n\n[Сервер: {self.ssh_credentials['host']}, user: {self.ssh_credentials.get('username', 'root')}]"

        agent_results = {}

        for agent_key, agent_info in self.AGENTS.items():
            if self._stop_requested:
                # BLOCK 3: Pause charter on stop
                if hasattr(self, "_current_task_id") and self._current_task_id:
                    try:
                        self._charter_store.pause(self._current_task_id)
                        self._snapshot_store.create(
                            task_id=self._current_task_id,
                            step_id="stopped",
                            snapshot_type="user_interrupt",
                            iteration=0,
                            cost_so_far=0
                        )
                        logger.info(f"[BLOCK3] Charter paused: {self._current_task_id}")
                    except Exception as _b3_stop_err:
                        logger.debug(f"[BLOCK3] Stop error: {_b3_stop_err}")
                yield self._sse({"type": "stopped", "text": "Остановлено пользователем"})
                return

            yield self._sse({
                "type": "agent_start",
                "agent": agent_info["name"],
                "emoji": agent_info["emoji"],
                "role": agent_key
            })

            messages = [{
                "role": "system",
                "content": AGENT_SYSTEM_PROMPT + "\n\n" + agent_info["prompt_suffix"]
            }]

            if agent_results:
                prev_context = "\n\n".join([
                    f"=== Результат {self.AGENTS[k]['name']} ===\n{v}"
                    for k, v in agent_results.items()
                ])
                messages.append({
                    "role": "user",
                    "content": f"Предыдущие результаты:\n{prev_context}\n\n---\n\nОригинальная задача:\n{context}"
                })
            else:
                messages.append({"role": "user", "content": context})

            agent_text = ""
            agent_iteration = 0
            max_agent_iterations = 8
            heal_attempts = 0

            while agent_iteration < max_agent_iterations and not self._stop_requested:
                yield self._sse({"type": "heartbeat", "message": "agent_thinking"})
                agent_iteration += 1

                tool_calls_received = None
                ai_text = ""

                for event in self._call_ai_stream(messages, tools=TOOLS_SCHEMA):
                    if event["type"] == "text_delta":
                        ai_text += event["text"]
                        agent_text += event["text"]
                        yield self._sse({"type": "content", "text": event["text"], "agent": agent_info["name"]})

                    elif event["type"] == "tool_calls":
                        tool_calls_received = event["tool_calls"]
                        ai_text = event.get("content", "")
                        if ai_text:
                            agent_text += ai_text

                    elif event["type"] == "text_complete":
                        break

                    elif event["type"] == "error":
                        yield self._sse({"type": "error", "text": event["error"]})
                        break

                if not tool_calls_received:
                    break

                assistant_msg = {"role": "assistant", "content": ai_text or ""}
                assistant_msg["tool_calls"] = tool_calls_received
                messages.append(assistant_msg)

                for tc in tool_calls_received:
                    tool_name = tc["function"]["name"]
                    tool_args_str = tc["function"]["arguments"]
                    tool_id = tc.get("id", f"call_{agent_iteration}")

                    try:
                        tool_args = json.loads(tool_args_str)
                    except Exception:
                        tool_args = {}

                    yield self._sse({
                        "type": "tool_start",
                        "tool": tool_name,
                        "args": self._sanitize_args(tool_args),
                        "agent": agent_info["name"]
                    })

                    if tool_name == "task_complete":
                        result = self._execute_tool(tool_name, tool_args_str)
                        yield self._sse({
                            "type": "tool_result",
                            "tool": tool_name,
                            "success": True,
                            "summary": result.get("summary", "")
                        })
                        yield self._sse({"type": "task_complete", "summary": result.get("summary", "")})
                        messages.append({
                            "role": "tool",
                            "tool_call_id": tool_id,
                            "content": json.dumps({k: ("[screenshot sent to user]" if k == "screenshot" else v) for k, v in result.items()}, ensure_ascii=False)
                        })
                        return

                    start_time = time.time()
                    result = self._execute_tool(tool_name, tool_args_str)
                    elapsed = round(time.time() - start_time, 2)

                    self.actions_log.append({
                        "agent": agent_key,
                        "iteration": agent_iteration,
                        "tool": tool_name,
                        "success": result.get("success", False),
                        "elapsed": elapsed
                    })
                    # BUG-11 FIX: Anti-loop detection
                    import hashlib as _hl
                    _tc_key = tool_name + ":" + str(sorted(tool_args.items()) if isinstance(tool_args, dict) else str(tool_args))
                    _tc_hash = _hl.md5(_tc_key.encode()).hexdigest()[:8]
                    if not hasattr(self, "_loop_counter"):
                        self._loop_counter = {}
                    self._loop_counter[_tc_hash] = self._loop_counter.get(_tc_hash, 0) + 1
                    _repeat_count = self._loop_counter[_tc_hash]
                    if _repeat_count >= 3:
                        _current_model = self.model
                        _fallback = ["anthropic/claude-sonnet-4-5", "anthropic/claude-opus-4-5", "openai/gpt-4o"]
                        _new_model = next((m for m in _fallback if m != _current_model), _fallback[0])
                        logging.warning("[AntiLoop] " + tool_name + " repeated " + str(_repeat_count) + "x! Switching model " + _current_model + " -> " + _new_model)
                        self.model = _new_model
                        messages.append({"role": "system", "content": "ВНИМАНИЕ: Ты уже вызывал инструмент '" + tool_name + "' с теми же аргументами " + str(_repeat_count) + " раз. ОБЯЗАТЕЛЬНО попробуй ДРУГОЙ инструмент или ДРУГОЙ подход."})
                    elif _repeat_count >= 2:
                        logging.warning("[AntiLoop] " + tool_name + " repeated " + str(_repeat_count) + "x - warning injected")
                        messages.append({"role": "system", "content": "ПРЕДУПРЕЖДЕНИЕ: Ты уже вызывал '" + tool_name + "' с похожими аргументами. Если результат тот же - попробуй другой подход."})

                    # ── ANTI-LOOP for pipeline ──
                    _ph_hash = hashlib.md5(f"{tool_name}:{tool_args_str[:200]}".encode()).hexdigest()
                    _phase_tool_history[_ph_hash] = _phase_tool_history.get(_ph_hash, 0) + 1
                    _ph_count = _phase_tool_history[_ph_hash]
                    if _ph_count >= 2:
                        _phase_consecutive_loops += 1
                        logger.warning(f"[ANTI-LOOP-PIPELINE] Phase {phase_idx+1} agent {agent_key}: {tool_name} called {_ph_count}x. Loop: {_phase_consecutive_loops}")
                        if _phase_consecutive_loops >= 3 and _phase_model_escalation == 0:
                            _phase_model_escalation = 1
                            self.model = "anthropic/claude-sonnet-4-5"
                            logger.warning(f"[ANTI-LOOP-PIPELINE] Escalating to Sonnet")
                            yield self._sse({"type": "info", "message": f"🔄 Переключаю на Sonnet для выхода из цикла в фазе {phase_idx+1}..."})
                            messages.append({"role": "system", "content": (
                                f"КРИТИЧЕСКОЕ: Ты вызвал {tool_name} {_ph_count} раз с теми же аргументами. "
                                f"Это цикл. Немедленно используй ДРУГОЙ инструмент или вызови task_complete."
                            )})
                        elif _phase_consecutive_loops >= 5 and _phase_model_escalation == 1:
                            _phase_model_escalation = 2
                            self.model = "anthropic/claude-opus-4-5"
                            logger.warning(f"[ANTI-LOOP-PIPELINE] Escalating to Opus")
                            yield self._sse({"type": "info", "message": f"🔄 Переключаю на Claude Opus для выхода из цикла..."})
                        elif _phase_consecutive_loops >= 7:
                            _ask_result = self._execute_tool("ask_user", json.dumps({
                                "question": f"Агент застрял в фазе '{phase.get('name', phase_idx+1)}' на действии '{tool_name}' ({_ph_count} повторений). Как продолжить?",
                                "context": "Pipeline застрял в цикле"
                            }, ensure_ascii=False))
                            yield self._sse({"type": "info", "message": "⚠️ Pipeline застрял — запрашиваю помощь пользователя"})
                            messages.append({"role": "tool", "tool_call_id": tool_id, "content": json.dumps(_ask_result, ensure_ascii=False)})
                            _phase_consecutive_loops = 0
                            _phase_tool_history.clear()
                    else:
                        _phase_consecutive_loops = max(0, _phase_consecutive_loops - 1)
                        if _phase_model_escalation > 0:
                            self.model = _phase_original_model
                            _phase_model_escalation = 0

                    result_preview = self._preview_result(tool_name, result)
                    yield self._sse({
                        "type": "tool_result",
                        "tool": tool_name,
                        "success": result.get("success", False),
                        "preview": result_preview,
                        "elapsed": elapsed,
                        "agent": agent_info["name"]
                    })

                    # Self-Healing in multi-agent mode
                    if not result.get("success", False) and heal_attempts < self.MAX_HEAL_ATTEMPTS:
                        fixes = self._analyze_error(tool_name, tool_args, result)
                        if fixes:
                            heal_attempts += 1
                            yield self._sse({
                                "type": "self_heal",
                                "attempt": heal_attempts,
                                "max_attempts": self.MAX_HEAL_ATTEMPTS,
                                "fixes_count": len(fixes),
                                "fix_description": fixes[0]["description"],
                                "agent": agent_info["name"]
                            })

                            fix = fixes[0]
                            fix_tool = fix["action"]["tool"]
                            fix_args = fix["action"]["args"]

                            yield self._sse({
                                "type": "tool_start",
                                "tool": fix_tool,
                                "args": self._sanitize_args(fix_args),
                                "agent": agent_info["name"],
                                "is_heal": True
                            })

                            fix_result = self._execute_tool(fix_tool, json.dumps(fix_args))
                            fix_preview = self._preview_result(fix_tool, fix_result)
                            yield self._sse({
                                "type": "tool_result",
                                "tool": fix_tool,
                                "success": fix_result.get("success", False),
                                "preview": fix_preview,
                                "agent": agent_info["name"],
                                "is_heal": True
                            })

                            heal_info = json.dumps({
                                "self_heal": True,
                                "original_error": str(result.get("error", ""))[:200],
                                "fix_applied": fix["description"],
                                "fix_result": fix_result
                            }, ensure_ascii=False)

                            if len(heal_info) > self.MAX_TOOL_OUTPUT:
                                heal_info = heal_info[:self.MAX_TOOL_OUTPUT] + "..."

                            messages.append({
                                "role": "tool",
                                "tool_call_id": tool_id,
                                "content": heal_info
                            })
                            continue

                    _result_clean = {k: ("[screenshot sent to user]" if k == "screenshot" else v) for k, v in result.items()}
                    result_str = json.dumps(_result_clean, ensure_ascii=False)
                    if len(result_str) > self.MAX_TOOL_OUTPUT:
                        result_str = result_str[:self.MAX_TOOL_OUTPUT] + "..."

                    messages.append({
                        "role": "tool",
                        "tool_call_id": tool_id,
                        "content": result_str
                    })

            agent_results[agent_key] = agent_text

            yield self._sse({
                "type": "agent_complete",
                "agent": agent_info["name"],
                "role": agent_key
            })
