"""
ARCANE Data Models (Pydantic v2)
Central schema definitions used across all workers and the orchestrator.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


# ─── Enums ────────────────────────────────────────────────────────────────────

class TaskStatus(str, Enum):
    PENDING = "pending"
    PLANNING = "planning"
    IN_PROGRESS = "in_progress"
    WAITING_USER = "waiting_user"       # ask_human / take_over_browser
    COMPLETED = "completed"
    PARTIAL = "partial"                 # completed with issues
    FAILED = "failed"
    CANCELLED = "cancelled"


class PhaseStatus(str, Enum):
    PENDING = "pending"
    ACTIVE = "active"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


class WorkerType(str, Enum):
    CODING = "coding"
    BROWSER = "browser"
    SSH = "ssh"
    QA = "qa"
    SEARCH = "search"
    PLANNER = "planner"


class MessageType(str, Enum):
    INFO = "info"           # progress update, no response needed
    ASK = "ask"             # blocking question, wait for user
    RESULT = "result"       # final result with attachments


class SuggestedAction(str, Enum):
    NONE = "none"
    CONFIRM_BROWSER_OP = "confirm_browser_operation"
    TAKE_OVER_BROWSER = "take_over_browser"


class Tier(str, Enum):
    FREE = "free"   # CRIT-6: truly free models ($0 cost)
    NANO = "nano"
    FAST = "fast"
    STANDARD = "standard"
    GENIUS = "genius"
    DEEP = "deep"


class Provider(str, Enum):
    OPENAI = "openai"
    OPENROUTER = "openrouter"


class ErrorSeverity(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class ErrorCategory(str, Enum):
    SYNTAX = "syntax"
    IMPORT = "import"
    RUNTIME = "runtime"
    PERMISSION = "permission"
    NETWORK = "network"
    DATABASE = "database"
    TIMEOUT = "timeout"
    CONFIGURATION = "configuration"
    DEPENDENCY = "dependency"
    SECURITY = "security"
    UNKNOWN = "unknown"


class DeployTarget(str, Enum):
    VERCEL = "vercel"
    CLOUDFLARE = "cloudflare"
    VPS = "vps"


class SearchType(str, Enum):
    INFO = "info"
    IMAGE = "image"
    API = "api"
    NEWS = "news"
    CODE = "code"


# ─── Core Models ──────────────────────────────────────────────────────────────

class Project(BaseModel):
    """A user project (website, API, integration, etc.)."""
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    user_id: str
    name: str
    description: str = ""
    status: TaskStatus = TaskStatus.PENDING
    strategy: str = "balance"           # ModelStrategy value
    budget_limit: float = 5.0
    budget_spent: float = 0.0
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    metadata: dict[str, Any] = Field(default_factory=dict)


class TaskPlan(BaseModel):
    """Structured plan for a task, analogous to Manus plan tool."""
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    project_id: str
    goal: str
    phases: list[TaskPhase] = Field(default_factory=list)
    current_phase_id: int = 1
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class TaskPhase(BaseModel):
    """A single phase within a task plan."""
    id: int
    title: str
    status: PhaseStatus = PhaseStatus.PENDING
    worker_type: Optional[WorkerType] = None
    capabilities: dict[str, bool] = Field(default_factory=dict)
    result: Optional[str] = None
    error: Optional[str] = None
    iterations: int = 0
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None


# ─── LLM Models ──────────────────────────────────────────────────────────────

class ModelSpec(BaseModel):
    """Specification of an LLM model."""
    id: str                             # e.g. "gpt-5.4"
    provider: Provider
    display_name: str
    input_price_per_mtok: float         # USD per 1M input tokens
    output_price_per_mtok: float        # USD per 1M output tokens
    cached_input_price_per_mtok: Optional[float] = None
    max_context: int = 128000
    supports_vision: bool = False
    supports_function_calling: bool = True
    supports_streaming: bool = True


class ModelRole(BaseModel):
    """A role in the system with tiered model assignment."""
    name: str                           # e.g. "coding", "qa", "browser"
    tiers: dict[Tier, str] = Field(default_factory=dict)  # Tier -> model_id
    fallback_chain: dict[str, str] = Field(default_factory=dict)  # model_id -> fallback_model_id
    default_tier: Tier = Tier.FAST


class LLMRequest(BaseModel):
    """Request to the Unified LLM Client."""
    messages: list[dict[str, Any]]
    model_id: Optional[str] = None      # explicit model override
    role: Optional[str] = None          # role name for auto-routing
    tier: Optional[Tier] = None         # tier override
    tools: Optional[list[dict]] = None
    temperature: float = 0.0
    max_tokens: Optional[int] = None
    stream: bool = False
    user_id: Optional[str] = None       # for rate limiting
    project_id: Optional[str] = None    # for budget tracking


class LLMResponse(BaseModel):
    """Normalized response from any LLM provider."""
    content: Optional[str] = None
    tool_calls: Optional[list[ToolCall]] = None
    model_id: str
    provider: Provider
    tier: Optional[Tier] = None
    input_tokens: int = 0
    output_tokens: int = 0
    cached_tokens: int = 0
    cost_usd: float = 0.0
    latency_ms: int = 0
    finish_reason: Optional[str] = "stop"
    raw_response: Optional[dict] = None


class ToolCall(BaseModel):
    """A tool call from the LLM."""
    id: str
    name: str
    arguments: dict[str, Any] = Field(default_factory=dict)


# ─── Usage Tracking ──────────────────────────────────────────────────────────

class UsageRecord(BaseModel):
    """Single LLM API call usage record."""
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    project_id: str
    user_id: str
    model_id: str
    provider: Provider
    tier: Optional[Tier] = None
    worker: str                         # which worker made the call
    role: str                           # role name
    input_tokens: int = 0
    output_tokens: int = 0
    cached_tokens: int = 0
    cost_usd: float = 0.0
    latency_ms: int = 0
    iteration: int = 1                  # self-healing iteration number
    escalated: bool = False             # was this an escalation?
    error: Optional[str] = None
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class BudgetStatus(BaseModel):
    """Current budget status for a project."""
    project_id: str
    budget_limit: float
    budget_spent: float
    budget_remaining: float
    percentage_used: float
    is_warning: bool                    # >90%
    is_exceeded: bool                   # >100%
    total_calls: int = 0
    breakdown_by_worker: dict[str, float] = Field(default_factory=dict)
    breakdown_by_model: dict[str, float] = Field(default_factory=dict)


# ─── Error Analysis ──────────────────────────────────────────────────────────

class ErrorReport(BaseModel):
    """Structured error analysis output."""
    category: ErrorCategory
    severity: ErrorSeverity
    root_cause: str
    suggested_fixes: list[str] = Field(default_factory=list)
    is_retryable: bool = True
    raw_error: str = ""
    pattern_matched: Optional[str] = None


# ─── Agent Communication ─────────────────────────────────────────────────────

class AgentMessage(BaseModel):
    """Message from agent to user (via WebSocket/SSE)."""
    type: MessageType
    content: str
    suggested_action: SuggestedAction = SuggestedAction.NONE
    attachments: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class AgentEvent(BaseModel):
    """Real-time event streamed to the UI."""
    event: str                          # e.g. "agent:thinking", "agent:tool_call"
    data: dict[str, Any] = Field(default_factory=dict)
    project_id: Optional[str] = None
    timestamp: datetime = Field(default_factory=datetime.utcnow)


# ─── Worker Communication ────────────────────────────────────────────────────

class WorkerTask(BaseModel):
    """Task dispatched from orchestrator to a worker."""
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    project_id: str
    phase_id: int
    worker_type: WorkerType
    instruction: str
    context: dict[str, Any] = Field(default_factory=dict)
    strategy: str = "balance"
    budget_remaining: float = 5.0
    timeout: int = 300                  # seconds
    created_at: datetime = Field(default_factory=datetime.utcnow)


class WorkerResult(BaseModel):
    """Result returned from a worker to the orchestrator."""
    task_id: str
    worker_type: WorkerType
    success: bool
    output: Optional[str] = None
    files_created: list[str] = Field(default_factory=list)
    files_modified: list[str] = Field(default_factory=list)
    screenshots: list[str] = Field(default_factory=list)
    urls: list[str] = Field(default_factory=list)
    error: Optional[ErrorReport] = None
    usage: list[UsageRecord] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    duration_ms: int = 0


# ─── Workspace Versioning ────────────────────────────────────────────────────

class FileVersion(BaseModel):
    """A versioned snapshot of a workspace file."""
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    project_id: str
    file_path: str
    version: int
    content_hash: str
    storage_key: str                    # MinIO key
    created_by: str                     # worker name
    iteration: int                      # self-healing iteration
    created_at: datetime = Field(default_factory=datetime.utcnow)


# ─── Agent State ────────────────────────────────────────────────────────────

class AgentState(BaseModel):
    """Full state of the agent loop at any point in time."""
    project_id: str
    chat_id: str
    status: TaskStatus = TaskStatus.PENDING
    plan: Optional[TaskPlan] = None
    current_phase_id: int = 0
    iteration: int = 0
    max_iterations: int = 50
    consecutive_errors: int = 0
    current_tier: Tier = Tier.FAST
    messages: list[dict[str, Any]] = Field(default_factory=list)
    tool_history: list[dict[str, Any]] = Field(default_factory=list)
    files_created: list[str] = Field(default_factory=list)
    files_modified: list[str] = Field(default_factory=list)
    screenshots: list[str] = Field(default_factory=list)
    urls: list[str] = Field(default_factory=list)
    total_cost: float = 0.0
    total_tokens: int = 0
    budget_limit: float = 5.0
    strategy: str = "balance"
    started_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    error: Optional[str] = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ProjectState(BaseModel):
    """Aggregated state of a project across all agent runs."""
    project_id: str
    user_id: str
    name: str = ""
    description: str = ""
    status: TaskStatus = TaskStatus.PENDING
    strategy: str = "balance"
    budget_limit: float = 5.0
    budget_spent: float = 0.0
    total_runs: int = 0
    total_tokens: int = 0
    files: list[str] = Field(default_factory=list)
    urls: list[str] = Field(default_factory=list)
    plan: Optional[TaskPlan] = None
    last_agent_state: Optional[AgentState] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    metadata: dict[str, Any] = Field(default_factory=dict)


# Forward references for nested models
TaskPlan.model_rebuild()
LLMResponse.model_rebuild()
AgentState.model_rebuild()
ProjectState.model_rebuild()
