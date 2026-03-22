"""
Autonomy Modes — режимы автономности ORION.
===========================================

Определяет насколько самостоятельно действует агент:

FULL      — полная автономность, без подтверждений
STANDARD  — автономный, но спрашивает перед деплоем
CAUTIOUS  — спрашивает перед любым execute/deploy
SUPERVISED — спрашивает перед каждым действием
READONLY  — только чтение, ничего не меняет

Режим влияет на:
- ToolSandbox (какие инструменты доступны)
- GoalKeeper (насколько строгие проверки)
- Количество подтверждений у пользователя
- Лимиты итераций и стоимости
"""

import logging
from typing import Dict, Optional, Callable, List
from dataclasses import dataclass, field

logger = logging.getLogger("autonomy_modes")


# ═══════════════════════════════════════════
# MODE DEFINITIONS
# ═══════════════════════════════════════════

@dataclass
class AutonomyConfig:
    """Конфигурация режима автономности."""
    name: str
    display_name: str
    description: str

    # Разрешения
    can_execute_ssh: bool = True
    can_deploy: bool = True
    can_write_files: bool = True
    can_browse: bool = True
    can_run_code: bool = True

    # Подтверждения
    confirm_ssh: bool = False           # Спрашивать перед SSH
    confirm_deploy: bool = False        # Спрашивать перед деплоем
    confirm_file_write: bool = False    # Спрашивать перед записью файлов
    confirm_all_actions: bool = False   # Спрашивать перед каждым действием

    # Лимиты
    max_iterations: int = 30
    max_cost_usd: float = 5.0
    max_ssh_commands: int = 100
    max_file_writes: int = 50

    # GoalKeeper настройки
    goal_keeper_strict: bool = False    # Строгая проверка каждого действия
    require_charter: bool = False       # Требовать Charter перед началом

    # Дополнительные настройки
    auto_snapshot: bool = True          # Автоматические снапшоты
    snapshot_interval: int = 5          # Каждые N итераций


AUTONOMY_CONFIGS: Dict[str, AutonomyConfig] = {
    "full": AutonomyConfig(
        name="full",
        display_name="Полная автономность",
        description="Агент действует полностью самостоятельно без подтверждений. "
                    "Подходит для опытных пользователей с чёткими задачами.",
        can_execute_ssh=True,
        can_deploy=True,
        can_write_files=True,
        can_browse=True,
        can_run_code=True,
        confirm_ssh=False,
        confirm_deploy=False,
        confirm_file_write=False,
        confirm_all_actions=False,
        max_iterations=50,
        max_cost_usd=20.0,
        max_ssh_commands=200,
        max_file_writes=100,
        goal_keeper_strict=False,
        require_charter=False,
        auto_snapshot=True,
        snapshot_interval=10,
    ),

    "standard": AutonomyConfig(
        name="standard",
        display_name="Стандартный",
        description="Агент автономен в большинстве действий, но спрашивает "
                    "перед деплоем в production. Рекомендуемый режим.",
        can_execute_ssh=True,
        can_deploy=True,
        can_write_files=True,
        can_browse=True,
        can_run_code=True,
        confirm_ssh=False,
        confirm_deploy=True,
        confirm_file_write=False,
        confirm_all_actions=False,
        max_iterations=30,
        max_cost_usd=10.0,
        max_ssh_commands=100,
        max_file_writes=50,
        goal_keeper_strict=False,
        require_charter=False,
        auto_snapshot=True,
        snapshot_interval=5,
    ),

    "cautious": AutonomyConfig(
        name="cautious",
        display_name="Осторожный",
        description="Агент спрашивает подтверждение перед SSH командами и деплоем. "
                    "Подходит для важных проектов.",
        can_execute_ssh=True,
        can_deploy=True,
        can_write_files=True,
        can_browse=True,
        can_run_code=True,
        confirm_ssh=True,
        confirm_deploy=True,
        confirm_file_write=False,
        confirm_all_actions=False,
        max_iterations=25,
        max_cost_usd=5.0,
        max_ssh_commands=50,
        max_file_writes=30,
        goal_keeper_strict=True,
        require_charter=True,
        auto_snapshot=True,
        snapshot_interval=3,
    ),

    "supervised": AutonomyConfig(
        name="supervised",
        display_name="Под наблюдением",
        description="Агент спрашивает подтверждение перед каждым значимым действием. "
                    "Максимальный контроль пользователя.",
        can_execute_ssh=True,
        can_deploy=True,
        can_write_files=True,
        can_browse=True,
        can_run_code=True,
        confirm_ssh=True,
        confirm_deploy=True,
        confirm_file_write=True,
        confirm_all_actions=True,
        max_iterations=20,
        max_cost_usd=3.0,
        max_ssh_commands=30,
        max_file_writes=20,
        goal_keeper_strict=True,
        require_charter=True,
        auto_snapshot=True,
        snapshot_interval=1,
    ),

    "readonly": AutonomyConfig(
        name="readonly",
        display_name="Только чтение",
        description="Агент только читает и анализирует. Никаких изменений. "
                    "Безопасный режим для аудита и анализа.",
        can_execute_ssh=False,
        can_deploy=False,
        can_write_files=False,
        can_browse=True,
        can_run_code=False,
        confirm_ssh=True,
        confirm_deploy=True,
        confirm_file_write=True,
        confirm_all_actions=False,
        max_iterations=15,
        max_cost_usd=1.0,
        max_ssh_commands=0,
        max_file_writes=0,
        goal_keeper_strict=True,
        require_charter=False,
        auto_snapshot=False,
        snapshot_interval=0,
    ),
}

# Режим по умолчанию
DEFAULT_AUTONOMY_MODE = "standard"


class AutonomyManager:
    """
    Управляет режимом автономности для сессии.
    
    Интегрируется с:
    - ToolSandbox: фильтрует доступные инструменты
    - GoalKeeper: настраивает строгость проверок
    - AgentLoop: управляет лимитами
    """

    def __init__(self):
        self._current_mode = DEFAULT_AUTONOMY_MODE
        self._config = AUTONOMY_CONFIGS[DEFAULT_AUTONOMY_MODE]
        self._confirm_callback: Optional[Callable] = None
        self._iteration_count = 0
        self._cost_spent = 0.0
        self._ssh_count = 0
        self._file_write_count = 0

    # ═══════════════════════════════════════════
    # CONFIGURATION
    # ═══════════════════════════════════════════

    def set_mode(self, mode: str) -> bool:
        """
        Установить режим автономности.
        
        Returns:
            True если режим установлен, False если неизвестный режим
        """
        if mode not in AUTONOMY_CONFIGS:
            logger.warning(f"[autonomy] Unknown mode: {mode}, keeping {self._current_mode}")
            return False

        old_mode = self._current_mode
        self._current_mode = mode
        self._config = AUTONOMY_CONFIGS[mode]
        logger.info(f"[autonomy] Mode changed: {old_mode} → {mode}")
        return True

    def get_mode(self) -> str:
        return self._current_mode

    def get_config(self) -> AutonomyConfig:
        return self._config

    def set_confirm_callback(self, callback: Callable):
        """Установить callback для запроса подтверждения у пользователя."""
        self._confirm_callback = callback

    # ═══════════════════════════════════════════
    # CHECKS
    # ═══════════════════════════════════════════

    def check_action(self, tool_name: str, args: Dict = None) -> Dict:
        """
        Проверить действие с учётом режима автономности.
        
        Returns:
            {
                "allowed": True/False,
                "requires_confirm": True/False,
                "reason": "...",
                "limit_warning": "..." (если приближается к лимиту)
            }
        """
        cfg = self._config
        args = args or {}
        result = {
            "allowed": True,
            "requires_confirm": False,
            "reason": "OK",
            "limit_warning": ""
        }

        # Проверить разрешения
        if tool_name == "ssh_execute" and not cfg.can_execute_ssh:
            result["allowed"] = False
            result["reason"] = f"Режим '{cfg.display_name}' не разрешает SSH"
            return result

        if tool_name in ("deploy_site", "ftp_upload") and not cfg.can_deploy:
            result["allowed"] = False
            result["reason"] = f"Режим '{cfg.display_name}' не разрешает деплой"
            return result

        if tool_name == "file_write" and not cfg.can_write_files:
            result["allowed"] = False
            result["reason"] = f"Режим '{cfg.display_name}' не разрешает запись файлов"
            return result

        # Проверить лимиты
        if tool_name == "ssh_execute":
            if self._ssh_count >= cfg.max_ssh_commands:
                result["allowed"] = False
                result["reason"] = f"Лимит SSH команд исчерпан: {cfg.max_ssh_commands}"
                return result
            if self._ssh_count >= cfg.max_ssh_commands * 0.8:
                result["limit_warning"] = (
                    f"Осталось SSH команд: {cfg.max_ssh_commands - self._ssh_count}"
                )

        if tool_name == "file_write":
            if self._file_write_count >= cfg.max_file_writes:
                result["allowed"] = False
                result["reason"] = f"Лимит записи файлов исчерпан: {cfg.max_file_writes}"
                return result

        # Проверить требование подтверждения
        if cfg.confirm_all_actions:
            result["requires_confirm"] = True
        elif cfg.confirm_ssh and tool_name == "ssh_execute":
            result["requires_confirm"] = True
        elif cfg.confirm_deploy and tool_name in ("deploy_site", "ftp_upload"):
            result["requires_confirm"] = True
        elif cfg.confirm_file_write and tool_name == "file_write":
            result["requires_confirm"] = True

        return result

    def check_iteration_limit(self) -> Dict:
        """Проверить лимит итераций."""
        cfg = self._config
        remaining = cfg.max_iterations - self._iteration_count
        return {
            "exceeded": self._iteration_count >= cfg.max_iterations,
            "remaining": remaining,
            "warning": remaining <= 5 and remaining > 0,
            "current": self._iteration_count,
            "max": cfg.max_iterations
        }

    def check_cost_limit(self) -> Dict:
        """Проверить лимит стоимости."""
        cfg = self._config
        remaining = cfg.max_cost_usd - self._cost_spent
        return {
            "exceeded": self._cost_spent >= cfg.max_cost_usd,
            "remaining": round(remaining, 4),
            "warning": remaining <= cfg.max_cost_usd * 0.2,
            "current": round(self._cost_spent, 4),
            "max": cfg.max_cost_usd
        }

    # ═══════════════════════════════════════════
    # COUNTERS
    # ═══════════════════════════════════════════

    def increment_iteration(self):
        self._iteration_count += 1

    def add_cost(self, cost: float):
        self._cost_spent += cost

    def increment_ssh(self):
        self._ssh_count += 1

    def increment_file_write(self):
        self._file_write_count += 1

    def reset_counters(self):
        """Сбросить счётчики (для новой задачи)."""
        self._iteration_count = 0
        self._cost_spent = 0.0
        self._ssh_count = 0
        self._file_write_count = 0

    # ═══════════════════════════════════════════
    # INFO
    # ═══════════════════════════════════════════

    def get_status(self) -> Dict:
        """Текущий статус режима."""
        cfg = self._config
        return {
            "mode": self._current_mode,
            "display_name": cfg.display_name,
            "iterations": f"{self._iteration_count}/{cfg.max_iterations}",
            "cost": f"${self._cost_spent:.4f}/${cfg.max_cost_usd:.2f}",
            "ssh_commands": f"{self._ssh_count}/{cfg.max_ssh_commands}",
            "file_writes": f"{self._file_write_count}/{cfg.max_file_writes}",
        }

    def format_for_prompt(self) -> str:
        """Форматирует режим для вставки в системный промпт."""
        cfg = self._config
        lines = [
            f"## Режим автономности: {cfg.display_name}",
            f"Описание: {cfg.description}",
        ]

        restrictions = []
        if not cfg.can_execute_ssh:
            restrictions.append("SSH запрещён")
        if not cfg.can_deploy:
            restrictions.append("Деплой запрещён")
        if not cfg.can_write_files:
            restrictions.append("Запись файлов запрещена")

        if restrictions:
            lines.append(f"Ограничения: {', '.join(restrictions)}")

        confirmations = []
        if cfg.confirm_ssh:
            confirmations.append("SSH")
        if cfg.confirm_deploy:
            confirmations.append("деплой")
        if cfg.confirm_file_write:
            confirmations.append("запись файлов")
        if cfg.confirm_all_actions:
            confirmations.append("все действия")

        if confirmations:
            lines.append(
                f"Требует подтверждения: {', '.join(confirmations)}. "
                f"Используй инструмент browser_ask_user для запроса."
            )

        lines.append(
            f"Лимиты: {cfg.max_iterations} итераций, "
            f"${cfg.max_cost_usd:.2f} бюджет"
        )

        return "\n".join(lines)

    @staticmethod
    def list_modes() -> List[Dict]:
        """Список всех доступных режимов."""
        return [
            {
                "name": name,
                "display_name": cfg.display_name,
                "description": cfg.description,
                "can_ssh": cfg.can_execute_ssh,
                "can_deploy": cfg.can_deploy,
                "max_iterations": cfg.max_iterations,
                "max_cost": cfg.max_cost_usd,
            }
            for name, cfg in AUTONOMY_CONFIGS.items()
        ]


# ═══════════════════════════════════════════
# SINGLETON
# ═══════════════════════════════════════════

_autonomy_manager: Optional[AutonomyManager] = None

def get_autonomy_manager() -> AutonomyManager:
    global _autonomy_manager
    if _autonomy_manager is None:
        _autonomy_manager = AutonomyManager()
    return _autonomy_manager
