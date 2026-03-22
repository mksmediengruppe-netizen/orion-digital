"""
ORION Handoff Protocol v1.0
=============================
Структурированная передача результатов между агентами.

Проблема: Designer создал HTML → Developer не знает где файл.
           Developer написал backend → DevOps не знает что деплоить.

Решение: Каждый агент после завершения формирует handoff — 
         структурированный JSON с результатами.
         Следующий агент получает handoff в контексте.

Интегрируется в parallel_agents.py и agent_loop.py.
"""

import json
import time
import logging
from typing import Dict, List, Any, Optional

logger = logging.getLogger("handoff")


class HandoffResult:
    """Результат работы одного агента для передачи следующему."""
    
    def __init__(self, agent_key: str, phase_name: str = ""):
        self.agent_key = agent_key
        self.phase_name = phase_name
        self.started_at = time.time()
        self.completed_at = None
        self.success = False
        self.files_created: List[Dict] = []      # Созданные файлы
        self.files_modified: List[Dict] = []      # Изменённые файлы
        self.commands_executed: List[Dict] = []   # SSH команды
        self.urls_deployed: List[str] = []        # Задеплоенные URL
        self.decisions: List[str] = []            # Ключевые решения
        self.errors: List[str] = []               # Ошибки
        self.summary: str = ""                    # Краткое резюме
        self.raw_output: str = ""                 # Полный текст ответа
        self.metadata: Dict = {}                  # Доп. данные
    
    def add_file(self, path: str, file_type: str = "unknown", size: int = 0, description: str = ""):
        self.files_created.append({
            "path": path,
            "type": file_type,  # html, css, js, py, conf, etc.
            "size": size,
            "description": description
        })
    
    def add_command(self, command: str, result: str = "", success: bool = True):
        self.commands_executed.append({
            "command": command,
            "result": result[:500],  # Обрезать длинные результаты
            "success": success
        })
    
    def add_url(self, url: str):
        self.urls_deployed.append(url)
    
    def add_decision(self, decision: str):
        self.decisions.append(decision)
    
    def add_error(self, error: str):
        self.errors.append(error)
    
    def complete(self, success: bool = True, summary: str = ""):
        self.completed_at = time.time()
        self.success = success
        self.summary = summary
    
    def to_dict(self) -> Dict:
        return {
            "agent": self.agent_key,
            "phase": self.phase_name,
            "success": self.success,
            "duration_sec": round((self.completed_at or time.time()) - self.started_at, 1),
            "summary": self.summary,
            "files_created": self.files_created,
            "files_modified": self.files_modified,
            "commands_executed": self.commands_executed[-10:],  # Последние 10
            "urls_deployed": self.urls_deployed,
            "decisions": self.decisions,
            "errors": self.errors,
            "metadata": self.metadata
        }
    
    def to_context_string(self) -> str:
        """Сформировать текстовый контекст для следующего агента."""
        parts = [f"=== Результат агента: {self.agent_key.upper()} ==="]
        
        if self.summary:
            parts.append(f"Резюме: {self.summary}")
        
        if self.files_created:
            parts.append("Созданные файлы:")
            for f in self.files_created:
                parts.append(f"  - {f['path']} ({f.get('type', '?')}) — {f.get('description', '')}")
        
        if self.urls_deployed:
            parts.append(f"Задеплоено: {', '.join(self.urls_deployed)}")
        
        if self.decisions:
            parts.append("Решения: " + "; ".join(self.decisions))
        
        if self.errors:
            parts.append("⚠️ Ошибки: " + "; ".join(self.errors))
        
        if self.commands_executed:
            last_cmds = self.commands_executed[-5:]
            parts.append("Последние команды:")
            for c in last_cmds:
                status = "✅" if c["success"] else "❌"
                parts.append(f"  {status} {c['command'][:100]}")
        
        return "\n".join(parts)


class HandoffManager:
    """Управляет передачей результатов между фазами."""
    
    def __init__(self):
        self.phase_results: Dict[str, HandoffResult] = {}  # phase_name → result
        self.agent_results: Dict[str, HandoffResult] = {}  # agent_key → result
        self.global_context: List[str] = []  # Накопленный контекст
    
    def start_phase(self, phase_name: str, agent_key: str) -> HandoffResult:
        """Начать новую фазу."""
        result = HandoffResult(agent_key, phase_name)
        self.phase_results[phase_name] = result
        self.agent_results[agent_key] = result
        return result
    
    def complete_phase(self, phase_name: str, success: bool = True, summary: str = ""):
        """Завершить фазу."""
        if phase_name in self.phase_results:
            self.phase_results[phase_name].complete(success, summary)
            # Добавить в глобальный контекст
            context = self.phase_results[phase_name].to_context_string()
            self.global_context.append(context)
    
    def get_context_for_next_agent(self, next_agent_key: str) -> str:
        """Получить контекст для следующего агента.
        
        Включает результаты всех предыдущих фаз.
        Фильтрует по релевантности для агента.
        """
        if not self.global_context:
            return ""
        
        parts = ["РЕЗУЛЬТАТЫ ПРЕДЫДУЩИХ АГЕНТОВ:\n"]
        
        for ctx in self.global_context:
            parts.append(ctx)
            parts.append("")  # Пустая строка между блоками
        
        # Специфичные подсказки для агента
        if next_agent_key == "devops":
            parts.append("ИНСТРУКЦИЯ ДЛЯ DEVOPS:")
            # Собрать все файлы для деплоя
            all_files = []
            for result in self.phase_results.values():
                all_files.extend(result.files_created)
            if all_files:
                parts.append("Файлы для деплоя:")
                for f in all_files:
                    parts.append(f"  {f['path']}")
            parts.append("Задеплой ВСЕ эти файлы на сервер.")
        
        elif next_agent_key == "tester":
            parts.append("ИНСТРУКЦИЯ ДЛЯ ТЕСТЕРА:")
            # Собрать URL для тестирования
            all_urls = []
            for result in self.phase_results.values():
                all_urls.extend(result.urls_deployed)
            if all_urls:
                parts.append(f"Проверь ВСЕ эти URL: {', '.join(all_urls)}")
            parts.append("Проверь: работает ли сайт, формы, мобильная версия, SSL.")
        
        elif next_agent_key == "integrator":
            parts.append("ИНСТРУКЦИЯ ДЛЯ ИНТЕГРАТОРА:")
            parts.append("Подключи интеграции к уже созданному сайту/приложению.")
        
        return "\n".join(parts)
    
    def get_all_files(self) -> List[Dict]:
        """Получить все созданные файлы из всех фаз."""
        files = []
        for result in self.phase_results.values():
            files.extend(result.files_created)
        return files
    
    def get_all_urls(self) -> List[str]:
        """Получить все задеплоенные URL."""
        urls = []
        for result in self.phase_results.values():
            urls.extend(result.urls_deployed)
        return urls
    
    def get_summary(self) -> Dict:
        """Общее резюме всех фаз."""
        total_time = 0
        total_files = 0
        total_commands = 0
        all_errors = []
        all_urls = []
        phase_summaries = []
        
        for name, result in self.phase_results.items():
            duration = (result.completed_at or time.time()) - result.started_at
            total_time += duration
            total_files += len(result.files_created)
            total_commands += len(result.commands_executed)
            all_errors.extend(result.errors)
            all_urls.extend(result.urls_deployed)
            
            status = "✅" if result.success else "❌"
            phase_summaries.append(f"{status} {name} ({result.agent_key}) — {round(duration, 1)}с")
        
        return {
            "total_phases": len(self.phase_results),
            "total_time_sec": round(total_time, 1),
            "total_files": total_files,
            "total_commands": total_commands,
            "errors": all_errors,
            "urls": all_urls,
            "phase_summaries": phase_summaries,
            "all_success": all(r.success for r in self.phase_results.values())
        }
    
    def format_summary_for_user(self) -> str:
        """Красивое резюме для пользователя."""
        s = self.get_summary()
        
        lines = []
        
        if s["all_success"]:
            lines.append("✅ **Задача выполнена!**")
        else:
            lines.append("⚠️ **Задача выполнена с ошибками**")
        
        lines.append(f"⏱ {s['total_time_sec']}с · 📄 {s['total_files']} файлов · 🔧 {s['total_commands']} команд")
        
        if s["urls"]:
            lines.append("🌐 " + ", ".join(s["urls"]))
        
        lines.append("")
        for ps in s["phase_summaries"]:
            lines.append(ps)
        
        if s["errors"]:
            lines.append("")
            lines.append("Ошибки:")
            for e in s["errors"][:5]:
                lines.append(f"  ❌ {e}")
        
        return "\n".join(lines)
    
    def format_summary_sse(self) -> Dict:
        """SSE событие с итогом."""
        s = self.get_summary()
        return {
            "type": "task_complete",
            "success": s["all_success"],
            "total_time": s["total_time_sec"],
            "total_files": s["total_files"],
            "total_commands": s["total_commands"],
            "urls": s["urls"],
            "errors": s["errors"],
            "phases": s["phase_summaries"]
        }


def extract_handoff_from_output(agent_key: str, raw_output: str, tool_calls: List[Dict] = None) -> HandoffResult:
    """Автоматически извлечь handoff из вывода агента.
    
    Анализирует: какие файлы создал, какие команды выполнил, 
    какие URL задеплоил.
    """
    result = HandoffResult(agent_key)
    result.raw_output = raw_output[:5000]
    
    if tool_calls:
        for tc in tool_calls:
            name = tc.get("name", tc.get("tool", ""))
            args = tc.get("args", tc.get("arguments", {}))
            output = tc.get("result", tc.get("output", ""))
            success = tc.get("success", True)
            
            if name in ("file_write", "create_artifact", "generate_file"):
                path = args.get("path", args.get("filename", "unknown"))
                file_type = path.split(".")[-1] if "." in path else "unknown"
                result.add_file(path, file_type, description=args.get("description", ""))
            
            elif name == "ssh_execute":
                cmd = args.get("command", "")
                result.add_command(cmd, str(output)[:200], success)
            
            elif name in ("browser_navigate", "browser_check_site"):
                url = args.get("url", "")
                if url:
                    result.add_url(url)
    
    # Извлечь резюме из текста
    if raw_output:
        # Первые 200 символов как резюме
        result.summary = raw_output[:200].split("\n")[0]
    
    result.complete(success=len(result.errors) == 0)
    return result
