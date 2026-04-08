"""
Structured State — JSON source of truth проекта.
Спека §2.2: "PROJECT.md НЕ является source of truth.
Source of truth — structured state в JSON."

Файл: .arcane/state.json
Генерирует: PROJECT.md (human-readable view)

Использование:
    state = StructuredState(project_path="/root/workspace/projects/abc123")
    state.load()
    slice = state.get_relevant_slice(user_message, task_type="coding")
    state.add_decision("Не React, чистый HTML", why="Проще для клиента", who="opus-4.6")
    state.update_status(pages_done=["Главная"], pages_todo=["Каталог"])
    state.record_run(task="Лендинг", model="sonnet-4.6", cost=0.12, result="success")
    state.save()
"""

import json
import os
import hashlib
import logging
import time
from datetime import datetime
from typing import Any, Dict, List, Optional
from pathlib import Path

logger = logging.getLogger("memory.structured_state")

# ══════════════════════════════════════════════════════════
# Схема по умолчанию (§2.2)
# ══════════════════════════════════════════════════════════

DEFAULT_STATE = {
    "version": "2.0",
    "project_profile": {
        "name": "",
        "client": "",
        "goal": "",
        "created_at": "",
        "updated_at": "",
    },
    "tech_stack": {
        "framework": "",
        "css": "",
        "db": "",
        "hosting": "",
        "languages": [],
        "extras": [],
    },
    "design_system": {
        "colors": {},          # {"primary": "#2D5016", "secondary": "#..."}
        "fonts": {},           # {"heading": "Playfair Display", "body": "Inter"}
        "style": "",           # "минималистичный", "тёмный luxury"
        "references": [],      # URL-ы референсов
    },
    "environment": {
        "servers": [],         # [{"host": "45.67.89.10", "role": "production", "os": "Ubuntu 24"}]
        "domains": [],         # ["example.com", "staging.example.com"]
        "ssh_refs": [],        # ссылки на SSH-ключи в Vault/encrypted
        "workspace_flow": "workspace",  # "workspace" | "ssh-direct"
    },
    "decisions": [],           # [{"date": "2025-03-28", "what": "не React", "why": "...", "who": "opus"}]
    "status": {
        "phase": "development",  # development | support | sleeping | archived
        "pages_done": [],
        "pages_todo": [],
        "known_issues": [],
        "last_activity": "",
    },
    "runs": [],                # [{"id": "...", "date": "...", "task": "...", "model": "...", "cost": 0.0, "result": "...", "duration_s": 0}]
    "personality": {
        "tone": "",            # "строго" | "дружелюбно" | "профессионально"
        "preferences": [],     # ["serif шрифты", "большие отступы"]
        "dislikes": [],        # ["Tailwind", "яркие цвета"]
    },
}


class StructuredState:
    """
    Менеджер structured state проекта.
    Читает/пишет .arcane/state.json.
    Генерирует PROJECT.md.
    Выдаёт релевантные срезы для LLM-контекста.
    """

    def __init__(self, project_path: str):
        self.project_path = Path(project_path)
        self.arcane_dir = self.project_path / ".arcane"
        self.state_path = self.arcane_dir / "state.json"
        self.project_md_path = self.project_path / "PROJECT.md"
        self._state: Dict[str, Any] = {}
        self._dirty = False
        self._last_hash = ""

    # ══════════════════════════════════════════════════════════
    # LOAD / SAVE
    # ══════════════════════════════════════════════════════════

    def load(self) -> Dict[str, Any]:
        """Загрузить state.json. Если нет — создать из шаблона."""
        if self.state_path.exists():
            try:
                raw = self.state_path.read_text(encoding="utf-8")
                self._state = json.loads(raw)
                self._last_hash = hashlib.md5(raw.encode()).hexdigest()
                # Миграция: добавить новые поля из DEFAULT_STATE
                self._migrate()
                logger.info(f"Loaded structured state: {self.state_path}")
            except (json.JSONDecodeError, OSError) as e:
                logger.error(f"Failed to load state.json: {e}")
                self._state = json.loads(json.dumps(DEFAULT_STATE))
        else:
            self._state = json.loads(json.dumps(DEFAULT_STATE))
            self._state["project_profile"]["created_at"] = datetime.utcnow().isoformat()
            self._dirty = True
            logger.info("Created new structured state from template")
        return self._state

    def save(self) -> bool:
        """Сохранить state.json + регенерировать PROJECT.md."""
        try:
            self.arcane_dir.mkdir(parents=True, exist_ok=True)
            self._state["project_profile"]["updated_at"] = datetime.utcnow().isoformat()

            raw = json.dumps(self._state, ensure_ascii=False, indent=2)
            new_hash = hashlib.md5(raw.encode()).hexdigest()

            # Пишем только если изменилось
            if new_hash != self._last_hash:
                self.state_path.write_text(raw, encoding="utf-8")
                self._last_hash = new_hash
                self._generate_project_md()
                logger.info("Saved structured state + regenerated PROJECT.md")
            self._dirty = False
            return True
        except OSError as e:
            logger.error(f"Failed to save state.json: {e}")
            return False

    def _migrate(self):
        """Добавить недостающие ключи из DEFAULT_STATE (forward-compat)."""
        def _deep_merge(default: dict, current: dict) -> bool:
            changed = False
            for key, val in default.items():
                if key not in current:
                    current[key] = json.loads(json.dumps(val))
                    changed = True
                elif isinstance(val, dict) and isinstance(current.get(key), dict):
                    if _deep_merge(val, current[key]):
                        changed = True
            return changed
        if _deep_merge(DEFAULT_STATE, self._state):
            self._dirty = True

    # ══════════════════════════════════════════════════════════
    # GETTERS / SETTERS
    # ══════════════════════════════════════════════════════════

    @property
    def state(self) -> Dict[str, Any]:
        return self._state

    def get(self, dotpath: str, default=None) -> Any:
        """Получить значение по dotpath: 'tech_stack.framework'."""
        parts = dotpath.split(".")
        obj = self._state
        for p in parts:
            if isinstance(obj, dict):
                obj = obj.get(p)
            else:
                return default
            if obj is None:
                return default
        return obj

    def set(self, dotpath: str, value: Any):
        """Установить значение по dotpath."""
        parts = dotpath.split(".")
        obj = self._state
        for p in parts[:-1]:
            if p not in obj or not isinstance(obj[p], dict):
                obj[p] = {}
            obj = obj[p]
        obj[parts[-1]] = value
        self._dirty = True

    # ══════════════════════════════════════════════════════════
    # ВЫСОКОУРОВНЕВЫЕ МУТАЦИИ (для engine.py)
    # ══════════════════════════════════════════════════════════

    def add_decision(self, what: str, why: str = "", who: str = ""):
        """Записать архитектурное/проектное решение."""
        self._state.setdefault("decisions", []).append({
            "date": datetime.utcnow().strftime("%Y-%m-%d"),
            "what": what[:500],
            "why": why[:500],
            "who": who[:100],
        })
        # Лимит: последние 50 решений
        if len(self._state["decisions"]) > 50:
            self._state["decisions"] = self._state["decisions"][-50:]
        self._dirty = True

    def record_run(self, task: str, model: str, cost: float = 0.0,
                   result: str = "", duration_s: float = 0.0,
                   run_id: str = ""):
        """Записать завершённый run."""
        self._state.setdefault("runs", []).append({
            "id": run_id or hashlib.md5(f"{time.time()}{task}".encode()).hexdigest()[:12],
            "date": datetime.utcnow().isoformat(),
            "task": task[:300],
            "model": model[:50],
            "cost": round(cost, 6),
            "result": result[:200],
            "duration_s": round(duration_s, 1),
        })
        # Лимит: последние 100 runs
        if len(self._state["runs"]) > 100:
            self._state["runs"] = self._state["runs"][-100:]
        self._dirty = True

    def update_status(self, pages_done: List[str] = None,
                      pages_todo: List[str] = None,
                      known_issues: List[str] = None,
                      phase: str = None):
        """Обновить статус проекта."""
        s = self._state.setdefault("status", {})
        if pages_done is not None:
            s["pages_done"] = pages_done
        if pages_todo is not None:
            s["pages_todo"] = pages_todo
        if known_issues is not None:
            s["known_issues"] = known_issues
        if phase:
            s["phase"] = phase
        s["last_activity"] = datetime.utcnow().isoformat()
        self._dirty = True

    def update_tech_stack(self, **kwargs):
        """Обновить tech_stack: framework, css, db, hosting, languages, extras."""
        ts = self._state.setdefault("tech_stack", {})
        for k, v in kwargs.items():
            if k in ("framework", "css", "db", "hosting"):
                ts[k] = str(v)
            elif k in ("languages", "extras"):
                ts[k] = list(v) if isinstance(v, (list, tuple)) else [str(v)]
        self._dirty = True

    def update_personality(self, tone: str = None,
                           preferences: List[str] = None,
                           dislikes: List[str] = None):
        """Обновить personality проекта."""
        p = self._state.setdefault("personality", {})
        if tone is not None:
            p["tone"] = tone
        if preferences is not None:
            p["preferences"] = preferences
        if dislikes is not None:
            p["dislikes"] = dislikes
        self._dirty = True

    def update_design_system(self, colors: Dict = None,
                             fonts: Dict = None,
                             style: str = None):
        """Обновить дизайн-систему."""
        ds = self._state.setdefault("design_system", {})
        if colors is not None:
            ds["colors"] = colors
        if fonts is not None:
            ds["fonts"] = fonts
        if style is not None:
            ds["style"] = style
        self._dirty = True

    def add_server(self, host: str, role: str = "production", os_info: str = ""):
        """Добавить сервер в environment."""
        env = self._state.setdefault("environment", {})
        servers = env.setdefault("servers", [])
        # Не дублировать
        if not any(s.get("host") == host for s in servers):
            servers.append({"host": host, "role": role, "os": os_info})
            self._dirty = True

    # ══════════════════════════════════════════════════════════
    # RELEVANT SLICE — подаётся в LLM (§2.2)
    # ══════════════════════════════════════════════════════════

    def get_relevant_slice(self, user_message: str = "",
                           task_type: str = "") -> str:
        """
        Сгенерировать релевантный срез structured state для подачи в LLM.
        Не весь файл — только то, что нужно для задачи.
        Возвращает компактный текст для system prompt.
        """
        parts = []
        pp = self._state.get("project_profile", {})
        name = pp.get("name", "")
        if name:
            parts.append(f"ПРОЕКТ: {name}")
            if pp.get("goal"):
                parts.append(f"  Цель: {pp['goal']}")
            if pp.get("client"):
                parts.append(f"  Клиент: {pp['client']}")

        # Tech stack — всегда релевантно для coding/devops
        ts = self._state.get("tech_stack", {})
        ts_parts = []
        for field in ("framework", "css", "db", "hosting"):
            val = ts.get(field, "")
            if val:
                ts_parts.append(f"{field}: {val}")
        if ts.get("languages"):
            ts_parts.append(f"языки: {', '.join(ts['languages'])}")
        if ts_parts:
            parts.append(f"  Стек: {' | '.join(ts_parts)}")

        # Design system — для design/frontend задач
        msg_lower = user_message.lower()
        is_design = task_type in ("design", "frontend", "landing") or \
                    any(w in msg_lower for w in ("дизайн", "стиль", "цвет", "шрифт",
                                                 "design", "style", "color", "font",
                                                 "css", "верстка", "html", "лендинг"))
        ds = self._state.get("design_system", {})
        if is_design and any(ds.get(k) for k in ("colors", "fonts", "style")):
            ds_text = []
            if ds.get("colors"):
                ds_text.append(f"цвета: {json.dumps(ds['colors'], ensure_ascii=False)}")
            if ds.get("fonts"):
                ds_text.append(f"шрифты: {json.dumps(ds['fonts'], ensure_ascii=False)}")
            if ds.get("style"):
                ds_text.append(f"стиль: {ds['style']}")
            parts.append(f"  Дизайн: {' | '.join(ds_text)}")

        # Environment — для ssh/devops задач
        is_devops = task_type in ("ssh", "devops", "deploy") or \
                    any(w in msg_lower for w in ("сервер", "ssh", "deploy", "битрикс",
                                                 "wordpress", "nginx", "docker", "server"))
        env = self._state.get("environment", {})
        if is_devops:
            servers = env.get("servers", [])
            if servers:
                srv_list = [f"{s['host']} ({s.get('role','')}{', '+s['os'] if s.get('os') else ''})"
                            for s in servers[:5]]
                parts.append(f"  Серверы: {', '.join(srv_list)}")
            if env.get("domains"):
                parts.append(f"  Домены: {', '.join(env['domains'][:5])}")
            if env.get("workspace_flow"):
                parts.append(f"  Flow: {env['workspace_flow']}")

        # Personality — всегда, если заполнено
        pers = self._state.get("personality", {})
        pers_parts = []
        if pers.get("tone"):
            pers_parts.append(f"тон: {pers['tone']}")
        if pers.get("preferences"):
            pers_parts.append(f"нравится: {', '.join(pers['preferences'][:5])}")
        if pers.get("dislikes"):
            pers_parts.append(f"не нравится: {', '.join(pers['dislikes'][:5])}")
        if pers_parts:
            parts.append(f"  Личность: {' | '.join(pers_parts)}")

        # Decisions — последние 5, всегда полезны
        decisions = self._state.get("decisions", [])
        if decisions:
            recent = decisions[-5:]
            dec_lines = [f"    {d['date']}: {d['what']}" +
                         (f" ({d['why']})" if d.get('why') else "")
                         for d in recent]
            parts.append("  Решения:\n" + "\n".join(dec_lines))

        # Status
        status = self._state.get("status", {})
        status_parts = []
        if status.get("pages_done"):
            status_parts.append(f"готово: {', '.join(status['pages_done'][:10])}")
        if status.get("pages_todo"):
            status_parts.append(f"todo: {', '.join(status['pages_todo'][:10])}")
        if status.get("known_issues"):
            status_parts.append(f"проблемы: {', '.join(status['known_issues'][:5])}")
        if status.get("phase"):
            status_parts.append(f"фаза: {status['phase']}")
        if status_parts:
            parts.append(f"  Статус: {' | '.join(status_parts)}")

        # Runs — последние 3 (краткий контекст)
        runs = self._state.get("runs", [])
        if runs:
            recent_runs = runs[-3:]
            run_lines = [f"    {r.get('date','')[:10]} {r['task'][:80]} → {r.get('result','')[:40]} (${r.get('cost',0):.4f})"
                         for r in recent_runs]
            parts.append("  Последние задачи:\n" + "\n".join(run_lines))

        if not parts:
            return ""

        return "STRUCTURED STATE (source of truth):\n" + "\n".join(parts)

    # ══════════════════════════════════════════════════════════
    # PROJECT.md GENERATION (§2.2: "генерируется из JSON")
    # ══════════════════════════════════════════════════════════

    def _generate_project_md(self):
        """Генерировать PROJECT.md из structured state."""
        try:
            lines = []
            pp = self._state.get("project_profile", {})
            name = pp.get("name", "Unnamed Project")
            lines.append(f"# Проект: {name}\n")
            if pp.get("client"):
                lines.append(f"**Клиент:** {pp['client']}")
            if pp.get("goal"):
                lines.append(f"**Цель:** {pp['goal']}\n")

            # Tech Stack
            ts = self._state.get("tech_stack", {})
            ts_items = []
            for k in ("framework", "css", "db", "hosting"):
                if ts.get(k):
                    ts_items.append(f"{k}: {ts[k]}")
            if ts.get("languages"):
                ts_items.append(f"языки: {', '.join(ts['languages'])}")
            if ts_items:
                lines.append(f"## Стек\n{' | '.join(ts_items)}\n")

            # Design System
            ds = self._state.get("design_system", {})
            ds_lines = []
            if ds.get("colors"):
                ds_lines.append(f"- Цвета: {json.dumps(ds['colors'], ensure_ascii=False)}")
            if ds.get("fonts"):
                ds_lines.append(f"- Шрифты: {json.dumps(ds['fonts'], ensure_ascii=False)}")
            if ds.get("style"):
                ds_lines.append(f"- Стиль: {ds['style']}")
            if ds_lines:
                lines.append("## Дизайн-система\n" + "\n".join(ds_lines) + "\n")

            # Environment
            env = self._state.get("environment", {})
            if env.get("servers") or env.get("domains"):
                lines.append("## Окружение")
                for s in env.get("servers", []):
                    lines.append(f"- Сервер: {s['host']} ({s.get('role','')})")
                for d in env.get("domains", []):
                    lines.append(f"- Домен: {d}")
                lines.append("")

            # Decisions
            decisions = self._state.get("decisions", [])
            if decisions:
                lines.append("## Решения")
                for d in decisions[-15:]:
                    line = f"- **{d['date']}** — {d['what']}"
                    if d.get("why"):
                        line += f" _{d['why']}_"
                    lines.append(line)
                lines.append("")

            # Status
            status = self._state.get("status", {})
            if status.get("pages_done") or status.get("pages_todo"):
                lines.append("## Статус")
                for p in status.get("pages_done", []):
                    lines.append(f"- [x] {p}")
                for p in status.get("pages_todo", []):
                    lines.append(f"- [ ] {p}")
                if status.get("known_issues"):
                    lines.append("\n### Известные проблемы")
                    for issue in status["known_issues"]:
                        lines.append(f"- ⚠️ {issue}")
                lines.append("")

            # Personality
            pers = self._state.get("personality", {})
            if any(pers.get(k) for k in ("tone", "preferences", "dislikes")):
                lines.append("## Предпочтения")
                if pers.get("tone"):
                    lines.append(f"- Тон: {pers['tone']}")
                if pers.get("preferences"):
                    lines.append(f"- Нравится: {', '.join(pers['preferences'])}")
                if pers.get("dislikes"):
                    lines.append(f"- Не нравится: {', '.join(pers['dislikes'])}")
                lines.append("")

            # Runs
            runs = self._state.get("runs", [])
            if runs:
                lines.append("## Последние задачи")
                for r in runs[-10:]:
                    lines.append(f"- {r.get('date','')[:10]} | {r['task'][:80]} | "
                                 f"{r.get('model','')} | ${r.get('cost',0):.4f} | {r.get('result','')[:50]}")
                lines.append("")

            # Footer
            lines.append(f"\n---\n_Сгенерировано из state.json: {datetime.utcnow().strftime('%Y-%m-%d %H:%M')} UTC_")

            self.project_md_path.write_text("\n".join(lines), encoding="utf-8")
        except OSError as e:
            logger.error(f"Failed to generate PROJECT.md: {e}")

    # ══════════════════════════════════════════════════════════
    # LLM-DRIVEN EXTRACTION (after_chat)
    # ══════════════════════════════════════════════════════════

    def extract_from_conversation(self, user_message: str,
                                  assistant_response: str,
                                  call_llm=None):
        """
        Попросить LLM извлечь обновления для structured state
        из завершённого разговора.
        """
        if not call_llm:
            return

        # Только если разговор содержит решения / изменения
        triggers = ("решил", "выбрал", "будем", "стек", "используем", "не будем",
                     "нравится", "ненавидит", "домен", "сервер", "decided", "stack",
                     "deploy", "готово", "сделано", "issue", "баг", "проблема")
        combined = (user_message + assistant_response).lower()
        if not any(t in combined for t in triggers):
            return

        current_slice = json.dumps({
            "project_profile": self._state.get("project_profile", {}),
            "tech_stack": self._state.get("tech_stack", {}),
            "personality": self._state.get("personality", {}),
        }, ensure_ascii=False)

        prompt = f"""Из разговора извлеки обновления для structured state проекта.
Текущее состояние (фрагмент):
{current_slice}

Разговор:
USER: {user_message[:1000]}
ASSISTANT: {assistant_response[:1000]}

Верни ТОЛЬКО JSON (без markdown, без комментариев):
{{
  "decisions": [{{"what": "...", "why": "..."}}],
  "tech_updates": {{"framework": "...", "css": "..."}},
  "personality_updates": {{"tone": "...", "preferences": ["..."], "dislikes": ["..."]}},
  "status_updates": {{"pages_done": ["..."], "known_issues": ["..."]}}
}}
Пустые поля не включай. Если ничего не изменилось — верни {{}}."""

        try:
            raw = call_llm([{"role": "user", "content": prompt}])
            # Очистить от markdown
            raw = raw.strip()
            if raw.startswith("```"):
                raw = raw.split("\n", 1)[-1].rsplit("```", 1)[0]
            updates = json.loads(raw)

            if updates.get("decisions"):
                for d in updates["decisions"]:
                    if d.get("what"):
                        self.add_decision(d["what"], d.get("why", ""), "auto-extract")

            if updates.get("tech_updates"):
                tu = updates["tech_updates"]
                non_empty = {k: v for k, v in tu.items() if v}
                if non_empty:
                    self.update_tech_stack(**non_empty)

            if updates.get("personality_updates"):
                pu = updates["personality_updates"]
                self.update_personality(
                    tone=pu.get("tone"),
                    preferences=pu.get("preferences"),
                    dislikes=pu.get("dislikes"),
                )

            if updates.get("status_updates"):
                su = updates["status_updates"]
                # Merge, not replace
                current_done = self._state.get("status", {}).get("pages_done", [])
                current_issues = self._state.get("status", {}).get("known_issues", [])
                new_done = list(set(current_done + (su.get("pages_done") or [])))
                new_issues = list(set(current_issues + (su.get("known_issues") or [])))
                self.update_status(pages_done=new_done, known_issues=new_issues)

            if self._dirty:
                self.save()
                logger.info("Structured state updated from conversation extraction")

        except Exception as e:
            logger.debug(f"State extraction failed (non-critical): {e}")

    # ══════════════════════════════════════════════════════════
    # TOOL HANDLERS (для handle_tool в engine)
    # ══════════════════════════════════════════════════════════

    def handle_read(self, section: str = "") -> Dict:
        """Tool: read_project_state."""
        if section:
            val = self.get(section)
            if val is not None:
                return {"success": True, "section": section, "data": val}
            return {"success": False, "error": f"Section '{section}' not found"}
        # Весь state (без runs — слишком длинный)
        compact = {k: v for k, v in self._state.items() if k != "runs"}
        compact["runs_count"] = len(self._state.get("runs", []))
        return {"success": True, "data": compact}

    def handle_update(self, section: str, data: Any) -> Dict:
        """Tool: update_project_state."""
        allowed_sections = {
            "project_profile", "tech_stack", "design_system",
            "environment", "personality", "status",
        }
        top_key = section.split(".")[0]
        if top_key not in allowed_sections:
            return {"success": False, "error": f"Section '{top_key}' is read-only or unknown"}
        self.set(section, data)
        self.save()
        return {"success": True, "section": section, "updated": True}
