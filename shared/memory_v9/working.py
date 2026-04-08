"""
L1: Working Memory — всё что живёт внутри контекстного окна LLM.
GoalAnchor, TaskPlanner, Scratchpad, ContextCompactor, SmartHistory, SmartToolOutput.
"""
import json
import os
import logging
from typing import List, Dict, Optional
from .config import MemoryConfig

logger = logging.getLogger("memory.working")


class TaskPlanner:
    PLANNER_PROMPT = """Ты — планировщик. Разбей задание на 3-12 конкретных шагов.
Ответь СТРОГО в JSON (без markdown):
{"goal":"цель","steps":[{"id":1,"task":"шаг","tools":["ssh_execute"]}],"success_criteria":"проверка"}"""

    def __init__(self, call_llm):
        self._call = call_llm
        self.plan = None
        self.completed = set()

    def create_plan(self, task: str, file_content: str = "") -> Optional[Dict]:
        if len(task) < MemoryConfig.PLANNER_MIN_TASK_LENGTH:
            self.plan = {"goal": task[:200], "steps": [{"id": 1, "task": task[:200], "tools": []}], "success_criteria": "готово"}
            return self.plan
        ctx = f"{file_content[:5000]}\n---\n{task}" if file_content else task
        try:
            resp = self._call([{"role": "system", "content": self.PLANNER_PROMPT}, {"role": "user", "content": ctx[:6000]}])
            resp = resp.strip()
            if resp.startswith("```"): resp = resp.split("\n", 1)[1].rsplit("```", 1)[0]
            self.plan = json.loads(resp)
            self.plan["steps"] = self.plan.get("steps", [])[:MemoryConfig.PLANNER_MAX_STEPS]
            return self.plan
        except Exception as e:
            logger.warning(f"TaskPlanner fallback: {e}")
            self.plan = {"goal": task[:200], "steps": [{"id": 1, "task": task[:200], "tools": []}], "success_criteria": "готово"}
            return self.plan

    def mark_done(self, step_id: int): self.completed.add(step_id)

    def auto_detect(self, tool_name: str, args: Dict, success: bool):
        if not self.plan or not success: return
        for s in self.plan.get("steps", []):
            if s["id"] not in self.completed and tool_name in s.get("tools", []):
                self.completed.add(s["id"]); break

    def progress_text(self) -> str:
        if not self.plan: return ""
        lines = [f"ЦЕЛЬ: {self.plan.get('goal','')}","ПЛАН:"]
        for s in self.plan.get("steps", []):
            lines.append(f"  {'✅' if s['id'] in self.completed else '⬜'} {s['id']}. {s['task']}")
        lines.append(f"ПРОГРЕСС: {len(self.completed)}/{len(self.plan.get('steps',[]))}")
        lines.append(f"КРИТЕРИЙ: {self.plan.get('success_criteria','')}")
        return "\n".join(lines)


class GoalAnchor:
    TAG = "::GOAL_ANCHOR::"

    def __init__(self, task: str, planner: Optional[TaskPlanner] = None):
        self.task = task
        self.planner = planner
        self.actions = []

    def record(self, tool: str, ok: bool, summary: str):
        self.actions.append({"tool": tool, "ok": ok, "s": summary[:100]})

    def build(self, iteration: int, max_iter: int, scratchpad: str = "", extra_context: str = "") -> Dict:
        parts = []
        preview = self.task[:MemoryConfig.ANCHOR_MAX_TASK_CHARS]
        if len(self.task) > MemoryConfig.ANCHOR_MAX_TASK_CHARS: preview += "..."
        parts.append(f"ОРИГИНАЛЬНАЯ ЗАДАЧА:\n{preview}")
        if self.planner and self.planner.plan: parts.append(self.planner.progress_text())
        if scratchpad: parts.append(f"БЛОКНОТ:\n{scratchpad}")
        if extra_context: parts.append(extra_context)
        if self.actions:
            recent = self.actions[-MemoryConfig.ANCHOR_MAX_ACTIONS:]
            a_text = "\n".join(f"  {'✅' if a['ok'] else '❌'} {a['tool']}: {a['s']}" for a in recent)
            parts.append(f"ВЫПОЛНЕНО ({len(self.actions)}):\n{a_text}")
        parts.append(f"ШАГ: {iteration}/{max_iter}. Если готово — task_complete.")
        return {"role": "system", "content": self.TAG + "\n" + "\n\n".join(parts)}


class Scratchpad:
    def __init__(self, chat_id: str = None):
        self._id = chat_id
        self._content = ""
        self._dir = MemoryConfig.SCRATCHPAD_DIR
        os.makedirs(self._dir, exist_ok=True)
        self._load()

    def _path(self): return os.path.join(self._dir, f"{self._id or '_default'}.txt")
    def _load(self):
        try:
            p = self._path()
            if os.path.exists(p):
                with open(p) as f: self._content = f.read()
        except: self._content = ""
    def _save(self):
        try:
            with open(self._path(), "w") as f: f.write(self._content[:MemoryConfig.SCRATCHPAD_MAX])
        except: pass

    def update(self, content: str) -> Dict:
        self._content = content[:MemoryConfig.SCRATCHPAD_MAX]; self._save()
        return {"success": True, "length": len(self._content)}
    def get(self) -> str: return self._content
    def clear(self): self._content = ""; self._save()


class ContextCompactor:
    def __init__(self, call_llm=None): self._call = call_llm

    def should_compact(self, messages: List[Dict], iteration: int) -> bool:
        if iteration > 0 and iteration % MemoryConfig.COMPACT_EVERY_N == 0 and len(messages) > 10: return True
        return len(messages) > MemoryConfig.COMPACT_MSG_THRESHOLD

    def compact(self, messages: List[Dict]) -> List[Dict]:
        kf, kl = MemoryConfig.COMPACT_KEEP_FIRST, MemoryConfig.COMPACT_KEEP_LAST
        if len(messages) <= kf + kl: return messages
        first, middle, last = messages[:kf], messages[kf:-kl], messages[-kl:]
        summary = self._summarize(middle)
        return first + [{"role": "system", "content": f"РЕЗЮМЕ ({len(middle)} сообщений сжато):\n{summary}"}] + last

    def _summarize(self, messages: List[Dict]) -> str:
        if self._call:
            try:
                ctx = "\n".join(f"[{m['role']}]: {m.get('content','')[:300]}" for m in messages[:20])
                r = self._call([{"role":"system","content":"Сожми диалог в 5 предложений. Что сделано, что получилось, какие ошибки. Русский."},{"role":"user","content":ctx[:4000]}])
                if r and len(r) > 20: return r[:600]
            except: pass
        facts = []
        for m in messages:
            if m.get("role") == "tool":
                try:
                    d = json.loads(m.get("content",""))
                    if isinstance(d,dict):
                        ok = "✅" if d.get("success") else "❌"
                        cmd = d.get("command",d.get("path",d.get("url","")))
                        if cmd: facts.append(f"{ok} {str(cmd)[:80]}")
                except: pass
        return "\n".join(facts[-10:]) or "Нет существенных действий"


class SmartHistory:
    @staticmethod
    def build(chat_messages: List[Dict]) -> List[Dict]:
        mx = MemoryConfig.HISTORY_MAX_TOTAL
        mc = MemoryConfig.HISTORY_MAX_CHARS
        if not chat_messages: return []
        if len(chat_messages) <= mx:
            result, total = [], 0
            for m in chat_messages:
                c = m.get("content","")
                if total + len(c) > mc: c = c[:1000] + "...[обрезано]"
                result.append({"role":m["role"],"content":c}); total += len(c)
            return result
        kf = MemoryConfig.HISTORY_KEEP_FIRST
        kl = mx - kf - 1
        first, middle, last = chat_messages[:kf], chat_messages[kf:-kl], chat_messages[-kl:]
        result = [{"role":m["role"],"content":m.get("content","")[:2000]} for m in first]
        if middle:
            sp = []
            for m in middle:
                c = m.get("content","")[:150]
                if m.get("role") == "assistant" and c: sp.append(f"AI: {c.split('.')[0][:100]}")
                elif m.get("role") == "user" and c: sp.append(f"User: {c[:100]}")
            if sp: result.append({"role":"system","content":f"[{len(middle)} сообщений пропущено:\n"+"\n".join(sp[-5:])+"]"})
        for m in last:
            c = m.get("content","")
            if len(c) > 3000: c = c[:1500]+"...[обрезано]..."+c[-500:]
            result.append({"role":m["role"],"content":c})
        return result


class SmartToolOutput:
    @staticmethod
    def truncate(result: Dict, tool_name: str) -> str:
        rs = json.dumps(result, ensure_ascii=False)
        mx = MemoryConfig.TOOL_OUTPUT_MAX_CHARS
        if len(rs) <= mx: return rs
        if tool_name == "ssh_execute":
            stdout = result.get("stdout","")
            if len(stdout) > 1600:
                lines = stdout.split("\n")
                h, t = MemoryConfig.SSH_HEAD_LINES, MemoryConfig.SSH_TAIL_LINES
                if len(lines) > h+t:
                    result["stdout"] = "\n".join(lines[:h])+f"\n...[{len(lines)-h-t} строк]...\n"+"\n".join(lines[-t:])
            return json.dumps(result, ensure_ascii=False)[:mx]
        if tool_name == "file_read":
            c = result.get("content","")
            if len(c) > 2000: result["content"] = c[:1000]+f"\n...[{len(c)} симв.]...\n"+c[-500:]
            return json.dumps(result, ensure_ascii=False)[:mx]
        if tool_name in ("browser_navigate","browser_get_text","browser_check_site"):
            if "html" in result and len(result.get("html","")) > 500: result["html"] = result["html"][:500]+"...[обрезано]"
            if "text" in result and len(result.get("text","")) > 1500: result["text"] = result["text"][:1500]+"...[обрезано]"
            return json.dumps(result, ensure_ascii=False)[:mx]
        return rs[:mx-50]+"\n...[обрезано]" if len(rs) > mx else rs
