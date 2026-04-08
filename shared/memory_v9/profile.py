"""
L5: User Profile — кумулятивный профиль пользователя + Adaptive Prompting.
"""
import json, os, logging
from datetime import datetime, timezone
from typing import Dict, Optional, List
from .config import MemoryConfig

logger = logging.getLogger("memory.profile")

class UserProfile:
    def __init__(self, user_id: str):
        self.user_id = user_id
        self._dir = MemoryConfig.PROFILES_DIR
        os.makedirs(self._dir, exist_ok=True)
        self.data = self._load()

    def _path(self): return os.path.join(self._dir, f"{self.user_id}.json")

    def _load(self) -> Dict:
        try:
            if os.path.exists(self._path()):
                with open(self._path()) as f: return json.load(f)
        except: pass
        return {"user_id": self.user_id, "facts": {}, "preferences": {},
                "tech_stack": [], "servers": [], "style": "default",
                "skill_level": "unknown", "chat_count": 0, "created_at": datetime.now(timezone.utc).isoformat()}

    def _save(self):
        try:
            with open(self._path(), "w") as f: json.dump(self.data, f, indent=2, ensure_ascii=False)
        except: pass

    def update_fact(self, key: str, value: str, confidence: float = 0.8):
        self.data["facts"][key] = {"value": value, "confidence": confidence,
                                    "updated": datetime.now(timezone.utc).isoformat()}
        if len(self.data["facts"]) > MemoryConfig.PROFILE_MAX_FACTS:
            sorted_facts = sorted(self.data["facts"].items(), key=lambda x: x[1].get("confidence",0))
            self.data["facts"] = dict(sorted_facts[-MemoryConfig.PROFILE_MAX_FACTS:])
        self._save()

    def increment_chats(self): self.data["chat_count"] = self.data.get("chat_count",0)+1; self._save()

    def get_prompt_context(self) -> str:
        if not self.data.get("facts") and not self.data.get("tech_stack"): return ""
        parts = ["ПРОФИЛЬ ПОЛЬЗОВАТЕЛЯ:"]
        for k, v in list(self.data.get("facts",{}).items())[:15]:
            parts.append(f"  {k}: {v['value']}")
        if self.data.get("tech_stack"): parts.append(f"  Стек: {', '.join(self.data['tech_stack'][:10])}")
        if self.data.get("servers"): parts.append(f"  Серверы: {', '.join(self.data['servers'][:5])}")
        return "\n".join(parts)

    def get_adaptive_prompt_suffix(self, task_type: str = "general") -> str:
        """Adaptive Prompting: разные инструкции под тип задачи и уровень."""
        level = self.data.get("skill_level", "unknown")
        suffixes = {
            "deploy": "Фокус на: проверь что сервис запустился, SSL работает, логи чистые." if level != "senior" else "",
            "analysis": "Давай структурированный отчёт с выводами." if level != "senior" else "Кратко, без воды.",
            "debug": "Покажи ход рассуждений. Проверяй гипотезы последовательно.",
            "design": "Предложи 2-3 варианта перед реализацией.",
        }
        return suffixes.get(task_type, "")

    def extract_from_chat(self, user_msg: str, assistant_resp: str, call_llm=None):
        """Извлечь факты о пользователе из диалога."""
        if call_llm and self.data.get("chat_count",0) >= MemoryConfig.PROFILE_EXTRACT_AFTER_N_CHATS:
            try:
                resp = call_llm([
                    {"role":"system","content":"Извлеки факты о пользователе. JSON: {\"facts\":{\"name\":\"Юра\",\"role\":\"CEO\"}, \"tech\":[\"Python\",\"Flask\"]}. Только конкретное. Без markdown."},
                    {"role":"user","content":f"User: {user_msg[:300]}\nAgent: {assistant_resp[:300]}"}
                ])
                resp = resp.strip()
                if resp.startswith("```"): resp = resp.split("\n",1)[1].rsplit("```",1)[0]
                data = json.loads(resp)
                for k, v in data.get("facts",{}).items(): self.update_fact(k, str(v))
                for t in data.get("tech",[]): 
                    if t not in self.data.get("tech_stack",[]): self.data.setdefault("tech_stack",[]).append(t)
                self._save()
            except: pass
