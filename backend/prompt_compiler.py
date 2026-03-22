"""
Prompt Compiler — динамическая сборка промптов из блоков.
=========================================================
Вместо одного гигантского system prompt —
компилятор собирает промпт из блоков:

- role_block: "Ты — ORION, автономный AI-агент..."
- charter_block: текущая задача, цели, критерии
- project_block: контекст проекта (из ProjectBrain)
- tools_block: доступные инструменты
- history_block: последние N действий
- constraints_block: ограничения, бюджет
- recovery_block: если crash recovery — контекст восстановления

Каждый блок имеет:
- priority (1-10, 10 = обязательно)
- max_tokens (лимит на блок)
- condition (когда включать)

Компилятор:
1. Собирает все блоки
2. Фильтрует по conditions
3. Сортирует по priority
4. Обрезает по token budget
5. Возвращает финальный промпт
"""
import json
import time
import logging
from typing import Optional, Dict, List, Callable, Any

logger = logging.getLogger("prompt_compiler")


class PromptBlock:
    """Один блок промпта."""

    def __init__(self, name: str, content: str = "",
                 priority: int = 5,
                 max_tokens: int = 2000,
                 condition: Callable = None,
                 section: str = "system"):
        self.name = name
        self.content = content
        self.priority = priority  # 1-10, 10 = must include
        self.max_tokens = max_tokens
        self.condition = condition  # function() -> bool
        self.section = section  # system, user, context

    def is_active(self, context: Dict = None) -> bool:
        """Проверить, активен ли блок."""
        if self.condition is None:
            return True
        try:
            return self.condition(context or {})
        except Exception:
            return True

    def render(self, context: Dict = None) -> str:
        """Рендер блока с подстановкой переменных."""
        text = self.content
        if context:
            for key, value in context.items():
                placeholder = "{{" + key + "}}"
                if placeholder in text:
                    text = text.replace(placeholder, str(value))
        return text

    @property
    def estimated_tokens(self) -> int:
        """Примерная оценка токенов (4 символа ~ 1 токен)."""
        return len(self.content) // 4

    def to_dict(self) -> Dict:
        return {
            "name": self.name,
            "priority": self.priority,
            "max_tokens": self.max_tokens,
            "section": self.section,
            "estimated_tokens": self.estimated_tokens,
            "content_preview": self.content[:100] + "..." if len(self.content) > 100 else self.content
        }


class PromptCompiler:
    """
    Компилятор промптов из блоков.
    Собирает, фильтрует, сортирует, обрезает.
    """

    # Default blocks
    DEFAULT_BLOCKS = {
        "role": {
            "content": (
                "You are ORION — an autonomous AI agent for web development. "
                "You execute tasks step by step, verify results, and deliver quality work."
            ),
            "priority": 10,
            "max_tokens": 500,
            "section": "system"
        },
        "tools": {
            "content": (
                "Available tools: ssh_execute, browser_navigate, browser_click, "
                "browser_input, file_read, file_write, web_search, task_complete."
            ),
            "priority": 9,
            "max_tokens": 1000,
            "section": "system"
        },
        "constraints": {
            "content": (
                "Constraints:\n"
                "- Always verify results after each action\n"
                "- Never exceed budget limit\n"
                "- Ask for confirmation before destructive operations\n"
                "- Log all actions for audit trail"
            ),
            "priority": 8,
            "max_tokens": 500,
            "section": "system"
        }
    }

    def __init__(self, token_budget: int = 8000):
        self.token_budget = token_budget
        self._blocks: Dict[str, PromptBlock] = {}
        self._compiled_cache: Optional[str] = None
        self._cache_context_hash: Optional[str] = None

        # Register default blocks
        for name, config in self.DEFAULT_BLOCKS.items():
            self.register_block(
                name=name,
                content=config["content"],
                priority=config["priority"],
                max_tokens=config["max_tokens"],
                section=config["section"]
            )

    # ═══════════════════════════════════════════
    # BLOCK MANAGEMENT
    # ═══════════════════════════════════════════
    def register_block(self, name: str, content: str = "",
                       priority: int = 5,
                       max_tokens: int = 2000,
                       condition: Callable = None,
                       section: str = "system") -> PromptBlock:
        """Зарегистрировать блок промпта."""
        block = PromptBlock(
            name=name,
            content=content,
            priority=priority,
            max_tokens=max_tokens,
            condition=condition,
            section=section
        )
        self._blocks[name] = block
        self._compiled_cache = None  # Invalidate cache
        return block

    def update_block(self, name: str, content: str = None,
                     priority: int = None) -> Optional[PromptBlock]:
        """Обновить существующий блок."""
        if name not in self._blocks:
            return None
        block = self._blocks[name]
        if content is not None:
            block.content = content
        if priority is not None:
            block.priority = priority
        self._compiled_cache = None
        return block

    def remove_block(self, name: str) -> bool:
        """Удалить блок."""
        if name in self._blocks:
            del self._blocks[name]
            self._compiled_cache = None
            return True
        return False

    def get_block(self, name: str) -> Optional[Dict]:
        """Получить информацию о блоке."""
        if name in self._blocks:
            return self._blocks[name].to_dict()
        return None

    def list_blocks(self) -> List[Dict]:
        """Список всех блоков."""
        return [b.to_dict() for b in sorted(
            self._blocks.values(),
            key=lambda x: x.priority,
            reverse=True
        )]

    # ═══════════════════════════════════════════
    # COMPILATION
    # ═══════════════════════════════════════════
    def compile(self, context: Dict = None,
                token_budget: int = None) -> str:
        """
        Скомпилировать промпт из блоков.
        1. Filter by conditions
        2. Sort by priority (desc)
        3. Trim to token budget
        4. Join sections
        """
        budget = token_budget or self.token_budget
        ctx = context or {}

        # 1. Filter active blocks
        active_blocks = [
            b for b in self._blocks.values()
            if b.is_active(ctx)
        ]

        # 2. Sort by priority (highest first)
        active_blocks.sort(key=lambda x: x.priority, reverse=True)

        # 3. Render and trim
        sections = {"system": [], "context": [], "user": []}
        used_tokens = 0

        for block in active_blocks:
            rendered = block.render(ctx)
            block_tokens = len(rendered) // 4

            # Trim block if over its max
            if block_tokens > block.max_tokens:
                char_limit = block.max_tokens * 4
                rendered = rendered[:char_limit] + "\n[...truncated]"
                block_tokens = block.max_tokens

            # Check total budget
            if used_tokens + block_tokens > budget:
                # Only skip if priority < 8 (non-essential)
                if block.priority < 8:
                    continue
                # Essential block — trim to fit
                remaining = budget - used_tokens
                if remaining > 100:
                    char_limit = remaining * 4
                    rendered = rendered[:char_limit] + "\n[...truncated]"
                    block_tokens = remaining
                else:
                    continue

            sections[block.section].append(rendered)
            used_tokens += block_tokens

        # 4. Join
        parts = []
        if sections["system"]:
            parts.append("\n\n".join(sections["system"]))
        if sections["context"]:
            parts.append("--- CONTEXT ---\n" + "\n\n".join(sections["context"]))
        if sections["user"]:
            parts.append("\n\n".join(sections["user"]))

        compiled = "\n\n".join(parts)
        logger.info(
            f"[prompt_compiler] Compiled: {len(active_blocks)} blocks, "
            f"~{used_tokens} tokens"
        )
        return compiled

    def compile_for_charter(self, charter: Dict,
                            project_context: str = "",
                            history: List[Dict] = None) -> str:
        """Скомпилировать промпт для конкретной задачи."""
        # Add charter block
        charter_text = (
            f"## Current Task\n"
            f"Objective: {charter.get('objective', 'N/A')}\n"
            f"Deliverables: {', '.join(charter.get('deliverables', []))}\n"
            f"Success Criteria: {', '.join(charter.get('success_criteria', []))}\n"
            f"Max Cost: ${charter.get('max_cost_usd', 'unlimited')}"
        )
        self.register_block("charter", charter_text, priority=9, section="context")

        # Add project context if available
        if project_context:
            self.register_block("project", project_context, priority=7, section="context")

        # Add history if available
        if history:
            history_text = "## Recent Actions:\n"
            for h in history[-5:]:
                tool = h.get("tool", "unknown")
                result = "OK" if h.get("success", True) else "FAIL"
                history_text += f"- {tool}: {result}\n"
            self.register_block("history", history_text, priority=6, section="context")

        return self.compile()

    # ═══════════════════════════════════════════
    # STATS
    # ═══════════════════════════════════════════
    def stats(self) -> Dict:
        """Статистика компилятора."""
        total_tokens = sum(b.estimated_tokens for b in self._blocks.values())
        return {
            "total_blocks": len(self._blocks),
            "total_estimated_tokens": total_tokens,
            "token_budget": self.token_budget,
            "utilization": f"{min(100, total_tokens / self.token_budget * 100):.0f}%",
            "blocks_by_section": {
                section: sum(1 for b in self._blocks.values() if b.section == section)
                for section in ["system", "context", "user"]
            }
        }


# ═══════════════════════════════════════════
# SINGLETON
# ═══════════════════════════════════════════
_compiler = None

def get_prompt_compiler(token_budget: int = 8000) -> PromptCompiler:
    global _compiler
    if _compiler is None:
        _compiler = PromptCompiler(token_budget)
    return _compiler
