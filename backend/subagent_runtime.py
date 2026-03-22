"""
Subagent Runtime — единый фреймворк для работы агентов как команды.
==================================================================
Роли:
- director: читает задачу, держит цель, решает стратегию
- planner: разбивает на шаги, оценивает стоимость
- worker: выполняет шаги (coding, SSH, browser)
- critic: проверяет результат после каждого шага
- judge: финальная проверка
- recovery: восстановление после сбоя

Стандартный handoff формат между агентами.
Очередь задач между агентами.
Метрики по каждому агенту (scorecard per agent).
"""
import json
import time
import logging
import uuid
from typing import Optional, Dict, List, Any
from dataclasses import dataclass, field, asdict
from collections import defaultdict

logger = logging.getLogger("subagent_runtime")


# ═══════════════════════════════════════════
# DATA CLASSES
# ═══════════════════════════════════════════
@dataclass
class AgentHandoff:
    """Стандартный формат передачи между агентами."""
    from_agent: str
    to_agent: str
    task_charter: Dict = field(default_factory=dict)
    plan_step: Dict = field(default_factory=dict)
    artifacts_so_far: List[Dict] = field(default_factory=list)
    constraints: List[str] = field(default_factory=list)
    context: Dict = field(default_factory=dict)
    created_at: float = 0.0

    def __post_init__(self):
        if self.created_at == 0.0:
            self.created_at = time.time()

    def to_dict(self) -> Dict:
        return asdict(self)


@dataclass
class AgentMetrics:
    """Метрики одного агента."""
    agent_role: str
    tasks_completed: int = 0
    tasks_failed: int = 0
    total_duration: float = 0.0
    avg_quality_score: float = 0.0
    retries: int = 0
    handoffs_sent: int = 0
    handoffs_received: int = 0
    last_active: float = 0.0

    def to_dict(self) -> Dict:
        return asdict(self)

    @property
    def success_rate(self) -> float:
        total = self.tasks_completed + self.tasks_failed
        return self.tasks_completed / total if total > 0 else 0.0


# ═══════════════════════════════════════════
# AGENT ROLES
# ═══════════════════════════════════════════
AGENT_ROLES = {
    "director": {
        "description": "Reads task, holds goal, decides strategy",
        "capabilities": ["strategy", "delegation", "goal_tracking"],
        "can_delegate_to": ["planner", "worker", "recovery"]
    },
    "planner": {
        "description": "Breaks task into steps, estimates cost",
        "capabilities": ["planning", "cost_estimation", "decomposition"],
        "can_delegate_to": ["worker"]
    },
    "worker": {
        "description": "Executes steps: coding, SSH, browser",
        "capabilities": ["coding", "ssh", "browser", "file_ops"],
        "can_delegate_to": ["critic"]
    },
    "critic": {
        "description": "Reviews result after each step",
        "capabilities": ["review", "quality_check", "feedback"],
        "can_delegate_to": ["worker", "planner"]
    },
    "judge": {
        "description": "Final verification before completion",
        "capabilities": ["final_review", "acceptance", "scoring"],
        "can_delegate_to": ["worker", "recovery"]
    },
    "recovery": {
        "description": "Handles failures and crash recovery",
        "capabilities": ["error_analysis", "rollback", "retry"],
        "can_delegate_to": ["worker", "planner"]
    }
}


class SubagentRuntime:
    """
    Управляет командой агентов.
    Очередь задач, handoffs, метрики.
    """

    def __init__(self):
        self._task_queue: List[Dict] = []
        self._handoff_log: List[AgentHandoff] = []
        self._metrics: Dict[str, AgentMetrics] = {}
        self._active_agent: Optional[str] = None
        self._session_id: str = str(uuid.uuid4())[:8]

        # Initialize metrics for all roles
        for role in AGENT_ROLES:
            self._metrics[role] = AgentMetrics(agent_role=role)

    # ═══════════════════════════════════════════
    # ROLE MANAGEMENT
    # ═══════════════════════════════════════════
    def list_roles(self) -> List[Dict]:
        """Список всех ролей агентов."""
        return [
            {"role": role, **info}
            for role, info in AGENT_ROLES.items()
        ]

    def get_role_info(self, role: str) -> Optional[Dict]:
        """Информация о роли."""
        if role in AGENT_ROLES:
            return {"role": role, **AGENT_ROLES[role]}
        return None

    def get_active_agent(self) -> Optional[str]:
        """Текущий активный агент."""
        return self._active_agent

    def set_active_agent(self, role: str) -> bool:
        """Установить активного агента."""
        if role in AGENT_ROLES:
            self._active_agent = role
            self._metrics[role].last_active = time.time()
            return True
        return False

    # ═══════════════════════════════════════════
    # HANDOFF
    # ═══════════════════════════════════════════
    def create_handoff(self, from_agent: str, to_agent: str,
                       task_charter: Dict = None,
                       plan_step: Dict = None,
                       artifacts: List[Dict] = None,
                       constraints: List[str] = None,
                       context: Dict = None) -> AgentHandoff:
        """Создать handoff между агентами."""
        # Validate roles
        if from_agent not in AGENT_ROLES:
            raise ValueError(f"Unknown agent role: {from_agent}")
        if to_agent not in AGENT_ROLES:
            raise ValueError(f"Unknown agent role: {to_agent}")

        # Check delegation permission
        allowed = AGENT_ROLES[from_agent].get("can_delegate_to", [])
        if to_agent not in allowed:
            logger.warning(
                f"[subagent] {from_agent} -> {to_agent}: not in allowed list {allowed}"
            )

        handoff = AgentHandoff(
            from_agent=from_agent,
            to_agent=to_agent,
            task_charter=task_charter or {},
            plan_step=plan_step or {},
            artifacts_so_far=artifacts or [],
            constraints=constraints or [],
            context=context or {}
        )
        self._handoff_log.append(handoff)

        # Update metrics
        self._metrics[from_agent].handoffs_sent += 1
        self._metrics[to_agent].handoffs_received += 1

        # Set active agent
        self._active_agent = to_agent
        self._metrics[to_agent].last_active = time.time()

        logger.info(f"[subagent] Handoff: {from_agent} -> {to_agent}")
        return handoff

    def get_handoff_log(self, limit: int = 20) -> List[Dict]:
        """История handoffs."""
        return [h.to_dict() for h in self._handoff_log[-limit:]]

    # ═══════════════════════════════════════════
    # TASK QUEUE
    # ═══════════════════════════════════════════
    def enqueue_task(self, task: Dict, priority: int = 5) -> str:
        """Добавить задачу в очередь."""
        task_id = task.get("task_id", str(uuid.uuid4())[:8])
        entry = {
            "task_id": task_id,
            "task": task,
            "priority": priority,
            "status": "queued",
            "queued_at": time.time(),
            "assigned_to": None
        }
        self._task_queue.append(entry)
        # Sort by priority (lower = higher priority)
        self._task_queue.sort(key=lambda x: x["priority"])
        return task_id

    def dequeue_task(self, agent_role: str = None) -> Optional[Dict]:
        """Взять следующую задачу из очереди."""
        for entry in self._task_queue:
            if entry["status"] == "queued":
                entry["status"] = "in_progress"
                entry["assigned_to"] = agent_role or self._active_agent
                entry["started_at"] = time.time()
                return entry
        return None

    def complete_task(self, task_id: str, success: bool = True,
                      quality_score: float = 7.0) -> bool:
        """Отметить задачу как завершённую."""
        for entry in self._task_queue:
            if entry["task_id"] == task_id:
                entry["status"] = "completed" if success else "failed"
                entry["completed_at"] = time.time()
                entry["quality_score"] = quality_score

                # Update agent metrics
                agent = entry.get("assigned_to")
                if agent and agent in self._metrics:
                    m = self._metrics[agent]
                    if success:
                        m.tasks_completed += 1
                    else:
                        m.tasks_failed += 1
                    duration = entry["completed_at"] - entry.get("started_at", entry["queued_at"])
                    m.total_duration += duration
                    # Running average of quality
                    total = m.tasks_completed + m.tasks_failed
                    m.avg_quality_score = (
                        (m.avg_quality_score * (total - 1) + quality_score) / total
                    )
                return True
        return False

    def get_queue_status(self) -> Dict:
        """Статус очереди."""
        statuses = defaultdict(int)
        for entry in self._task_queue:
            statuses[entry["status"]] += 1
        return {
            "total": len(self._task_queue),
            "queued": statuses.get("queued", 0),
            "in_progress": statuses.get("in_progress", 0),
            "completed": statuses.get("completed", 0),
            "failed": statuses.get("failed", 0)
        }

    # ═══════════════════════════════════════════
    # METRICS
    # ═══════════════════════════════════════════
    def get_agent_metrics(self, role: str) -> Optional[Dict]:
        """Метрики конкретного агента."""
        if role in self._metrics:
            m = self._metrics[role]
            d = m.to_dict()
            d["success_rate"] = m.success_rate
            return d
        return None

    def get_all_metrics(self) -> Dict[str, Dict]:
        """Метрики всех агентов."""
        result = {}
        for role, m in self._metrics.items():
            d = m.to_dict()
            d["success_rate"] = m.success_rate
            result[role] = d
        return result

    def get_team_summary(self) -> Dict:
        """Сводка по команде."""
        total_tasks = sum(m.tasks_completed + m.tasks_failed for m in self._metrics.values())
        total_completed = sum(m.tasks_completed for m in self._metrics.values())
        total_failed = sum(m.tasks_failed for m in self._metrics.values())
        total_handoffs = sum(m.handoffs_sent for m in self._metrics.values())

        return {
            "session_id": self._session_id,
            "active_agent": self._active_agent,
            "total_tasks": total_tasks,
            "completed": total_completed,
            "failed": total_failed,
            "total_handoffs": total_handoffs,
            "queue": self.get_queue_status(),
            "agents": {
                role: {
                    "completed": m.tasks_completed,
                    "failed": m.tasks_failed,
                    "success_rate": f"{m.success_rate:.0%}"
                }
                for role, m in self._metrics.items()
                if m.tasks_completed + m.tasks_failed > 0
            }
        }

    # ═══════════════════════════════════════════
    # STANDARD WORKFLOW
    # ═══════════════════════════════════════════
    def standard_workflow(self) -> List[Dict]:
        """Стандартный workflow: director -> planner -> worker -> critic -> judge."""
        return [
            {"step": 1, "agent": "director", "action": "analyze_task", "next": "planner"},
            {"step": 2, "agent": "planner", "action": "create_plan", "next": "worker"},
            {"step": 3, "agent": "worker", "action": "execute_step", "next": "critic"},
            {"step": 4, "agent": "critic", "action": "review_result", "next": "worker_or_judge"},
            {"step": 5, "agent": "judge", "action": "final_check", "next": "done_or_recovery"},
            {"step": 6, "agent": "recovery", "action": "handle_failure", "next": "worker_or_planner"}
        ]

    def reset(self):
        """Сбросить runtime."""
        self._task_queue.clear()
        self._handoff_log.clear()
        self._active_agent = None
        for m in self._metrics.values():
            m.tasks_completed = 0
            m.tasks_failed = 0
            m.total_duration = 0
            m.avg_quality_score = 0
            m.retries = 0
            m.handoffs_sent = 0
            m.handoffs_received = 0


# ═══════════════════════════════════════════
# SINGLETON
# ═══════════════════════════════════════════
_runtime = None

def get_subagent_runtime() -> SubagentRuntime:
    global _runtime
    if _runtime is None:
        _runtime = SubagentRuntime()
    return _runtime
