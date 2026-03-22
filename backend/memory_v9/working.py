"""
L1: Working Memory — GoalAnchor, TaskPlanner, Scratchpad, Compaction, SmartHistory, SmartToolOutput.
"""
import json, os, re, logging, threading
from typing import List, Dict, Optional
from .config import MemoryConfig

logger = logging.getLogger("memory.working")


class GoalAnchor:
    """Якорь цели — напоминает агенту о задаче каждую итерацию."""
    TAG = "⚓ ЦЕЛЬ:"

    def __init__(self, user_message: str, planner=None):
        self._task = user_message[:MemoryConfig.ANCHOR_MAX_TASK_CHARS]
        self._planner = planner
        self.actions: List[Dict] = []

    def record(self, tool: str, success: bool, summary: str = ""):
        self.actions.append({"tool": tool, "ok": success, "s": summary[:100]})
        if len(self.actions) > MemoryConfig.ANCHOR_MAX_ACTIONS:
            self.actions = self.actions[-MemoryConfig.ANCHOR_MAX_ACTIONS:]

    def build(self, iteration: int, max_iter: int, scratchpad: str = "") -> Dict:
        lines = [f"{self.TAG} {self._task[:300]}"]
        lines.append(f"Итерация {iteration}/{max_iter}")
        if self.actions:
            lines.append("Последние действия:")
            for a in self.actions[-4:]:
                icon = "✅" if a["ok"] else "❌"
                lines.append(f"  {icon} {a['tool']}: {a['s']}")
        if scratchpad:
            lines.append(f"Блокнот: {scratchpad[:200]}")
        return {"role": "user", "content": "\n".join(lines)}


class TaskPlanner:
    """Планировщик задач — разбивает задачу на шаги."""

    def __init__(self, call_llm):
        self._call_llm = call_llm
        self.plan: List[Dict] = []
        self._current_step = 0

    def create_plan(self, task: str, context: str = "") -> List[Dict]:
        if len(task) < MemoryConfig.PLANNER_MIN_TASK_LENGTH:
            return []
        try:
            resp = self._call_llm([
                {"role": "system", "content": "Разбей задачу на шаги. JSON массив: [{\"step\":1,\"action\":\"...\",\"tool\":\"ssh_execute\"}]. Максимум 8 шагов. Без markdown."},
                {"role": "user", "content": f"Задача: {task[:1000]}\nКонтекст: {context[:500]}"}
            ])
            resp = resp.strip()
            if resp.startswith("```"):
                resp = resp.split("\n", 1)[1].rsplit("```", 1)[0]
            self.plan = json.loads(resp)[:MemoryConfig.PLANNER_MAX_STEPS]
            for s in self.plan:
                s["done"] = False
            return self.plan
        except Exception as e:
            logger.warning(f"TaskPlanner: {e}")
            return []

    def auto_detect(self, tool_name: str, args: Dict, success: bool):
        """Автоматически отмечать шаги как выполненные."""
        if not self.plan or not success:
            return
        for step in self.plan:
            if step.get("done"):
                continue
            step_tool = step.get("tool", "")
            if step_tool and step_tool == tool_name:
                step["done"] = True
                self._current_step = step.get("step", 0)
                break

    def progress_text(self) -> str:
        if not self.plan:
            return ""
        lines = ["ПЛАН ЗАДАЧИ:"]
        for s in self.plan:
            icon = "✅" if s.get("done") else "⬜"
            lines.append(f"  {icon} Шаг {s.get('step','?')}: {s.get('action','')[:100]}")
        done = sum(1 for s in self.plan if s.get("done"))
        lines.append(f"Прогресс: {done}/{len(self.plan)}")
        return "\n".join(lines)


class Scratchpad:
    """Блокнот агента — персистентный между итерациями."""

    def __init__(self, chat_id: str = None):
        self._chat_id = chat_id or "default"
        self._content = ""
        self._lock = threading.Lock()
        self._load()

    def _path(self) -> str:
        os.makedirs(MemoryConfig.SCRATCHPAD_DIR, exist_ok=True)
        safe = re.sub(r'[^a-zA-Z0-9_-]', '_', self._chat_id)
        return os.path.join(MemoryConfig.SCRATCHPAD_DIR, f"{safe}.txt")

    def _load(self):
        try:
            p = self._path()
            if os.path.exists(p):
                with open(p, "r", encoding="utf-8") as f:
                    self._content = f.read()[:MemoryConfig.SCRATCHPAD_MAX]
        except:
            pass

    def update(self, content: str) -> Dict:
        with self._lock:
            self._content = content[:MemoryConfig.SCRATCHPAD_MAX]
            try:
                with open(self._path(), "w", encoding="utf-8") as f:
                    f.write(self._content)
            except:
                pass
        return {"success": True, "length": len(self._content)}

    def get(self) -> str:
        return self._content

    def append(self, text: str):
        with self._lock:
            self._content = (self._content + "\n" + text)[-MemoryConfig.SCRATCHPAD_MAX:]


class ContextCompactor:
    """Сжимает историю сообщений когда она становится слишком длинной."""

    def __init__(self, call_llm=None):
        self._call_llm = call_llm

    def should_compact(self, messages: List[Dict], iteration: int) -> bool:
        if len(messages) < MemoryConfig.COMPACT_MSG_THRESHOLD:
            return False
        if iteration % MemoryConfig.COMPACT_EVERY_N != 0:
            return False
        return True

    @staticmethod
    def _fix_tool_pairs(messages: List[Dict]) -> List[Dict]:
        """Ensure every tool_result has a matching tool_use in the previous assistant message.
        Remove orphan tool_result blocks that would cause Claude 400 errors."""
        cleaned = []
        for i, msg in enumerate(messages):
            if msg.get('role') == 'tool':
                # Find the tool_use_id this result refers to
                tool_use_id = msg.get('tool_call_id', '')
                # Check if there's a matching tool_use in preceding assistant messages
                found = False
                for j in range(i - 1, -1, -1):
                    prev = messages[j]
                    if prev.get('role') == 'assistant':
                        # Check tool_calls list
                        for tc in (prev.get('tool_calls') or []):
                            if tc.get('id') == tool_use_id:
                                found = True
                                break
                        # Also check content blocks for Claude format
                        if not found and isinstance(prev.get('content'), list):
                            for block in prev['content']:
                                if isinstance(block, dict) and block.get('type') == 'tool_use' and block.get('id') == tool_use_id:
                                    found = True
                                    break
                        break  # Only check the immediately preceding assistant message
                if found:
                    cleaned.append(msg)
                else:
                    logger.warning(f"[COMPACT] Removed orphan tool_result: {tool_use_id}")
            else:
                cleaned.append(msg)
        return cleaned

    def compact(self, messages: List[Dict]) -> List[Dict]:
        if not self._call_llm or len(messages) < 10:
            return messages
        try:
            system = [m for m in messages if m["role"] == "system"]
            non_system = [m for m in messages if m["role"] != "system"]
            keep_first = non_system[:MemoryConfig.COMPACT_KEEP_FIRST]
            keep_last = non_system[-MemoryConfig.COMPACT_KEEP_LAST:]
            middle = non_system[MemoryConfig.COMPACT_KEEP_FIRST:-MemoryConfig.COMPACT_KEEP_LAST]
            if not middle:
                return messages

            # ПАТЧ W2-1: Более умная суммаризация — сохраняем конкретику
            middle_parts = []
            for m in middle:
                role = m['role'].upper()
                content = str(m.get('content', ''))
                # Для tool результатов — извлекаем ключевое
                # ── MANUS FEATURE 3: RESTORABLE COMPRESSION ──
                if role == 'TOOL' and len(content) > 300:
                    # Если результат был сохранён в файл — оставить только ссылку
                    try:
                        _data = json.loads(content) if content.startswith('{') else {}
                        if _data.get('_saved_to'):
                            middle_parts.append(f"TOOL: result in {_data['_saved_to']}")
                            continue
                    except Exception:
                        pass
                if role == 'TOOL':
                    try:
                        _td = json.loads(content) if content.startswith('{') else {}
                        if _td.get('success'):
                            _stdout = _td.get('stdout', '')[:150]
                            _path = _td.get('path', '')
                            middle_parts.append(f"TOOL OK: {_path} {_stdout}".strip()[:200])
                        else:
                            _err = _td.get('error', content[:150])
                            middle_parts.append(f"TOOL ERR: {_err}"[:200])
                    except Exception:
                        middle_parts.append(f"{role}: {content[:200]}")
                else:
                    middle_parts.append(f"{role}: {content[:300]}")

            middle_text = "\n".join(middle_parts)
            summary = self._call_llm([
                {"role": "system", "content": (
                    "Сожми историю в 3-5 предложений. ОБЯЗАТЕЛЬНО сохрани:\n"
                    "1. Какие файлы были созданы/изменены (точные пути)\n"
                    "2. Какие команды сработали/не сработали\n"
                    "3. Какие URL были открыты и их статус\n"
                    "4. Ошибки и как их обошли\n"
                    "Формат: краткие факты без воды."
                )},
                {"role": "user", "content": middle_text[:8000]}
            ])
            summary_msg = {"role": "assistant", "content": f"[СЖАТАЯ ИСТОРИЯ]\n{summary}"}
            logger.info(f"[COMPACT] Сжали {len(middle)} сообщений в 1 summary ({len(summary)} chars)")
            result = system + keep_first + [summary_msg] + keep_last
            # ── FIX: Validate tool_use/tool_result pairs ──
            result = self._fix_tool_pairs(result)
            return result
        except Exception as e:
            logger.warning(f"Compaction failed: {e}")
            return messages


class SmartHistory:
    """Умная история — обрезает старые сообщения."""

    @staticmethod
    def build(chat_history: List[Dict]) -> List[Dict]:
        if not chat_history:
            return []
        total_chars = sum(len(str(m.get("content", ""))) for m in chat_history)
        if (len(chat_history) <= MemoryConfig.HISTORY_MAX_TOTAL and
                total_chars <= MemoryConfig.HISTORY_MAX_CHARS):
            return chat_history
        keep_first = chat_history[:MemoryConfig.HISTORY_KEEP_FIRST]
        keep_last = chat_history[-MemoryConfig.HISTORY_KEEP_LAST:]
        result = keep_first + keep_last
        # Обрезать длинные сообщения
        trimmed = []
        for m in result:
            content = str(m.get("content", ""))
            if len(content) > 3000:
                content = content[:3000] + f"...[обрезано, {len(content)} симв.]"
            trimmed.append({**m, "content": content})
        return trimmed


class SmartToolOutput:
    """Умная обрезка вывода инструментов."""

    @staticmethod
    def truncate(result: Dict, tool_name: str) -> str:
        if tool_name == "ssh_execute":
            stdout = result.get("stdout", "")
            stderr = result.get("stderr", "")
            lines = stdout.split("\n")
            if len(lines) > MemoryConfig.SSH_HEAD_LINES + MemoryConfig.SSH_TAIL_LINES:
                head = "\n".join(lines[:MemoryConfig.SSH_HEAD_LINES])
                tail = "\n".join(lines[-MemoryConfig.SSH_TAIL_LINES:])
                stdout = f"{head}\n...[{len(lines)} строк]...\n{tail}"
            out = {"stdout": stdout, "success": result.get("success", False)}
            if stderr:
                out["stderr"] = stderr[:500]
            return json.dumps(out, ensure_ascii=False)[:MemoryConfig.TOOL_OUTPUT_MAX_CHARS]
        result_str = json.dumps(result, ensure_ascii=False)
        if len(result_str) > MemoryConfig.TOOL_OUTPUT_MAX_CHARS:
            return result_str[:MemoryConfig.TOOL_OUTPUT_MAX_CHARS] + "...[обрезано]"
        return result_str
