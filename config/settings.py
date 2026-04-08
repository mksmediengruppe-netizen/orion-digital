"""
ARCANE Configuration
Central configuration module. All settings are loaded from environment
variables with sensible defaults. No hardcoded secrets.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional
from functools import lru_cache


class Environment(str, Enum):
    DEVELOPMENT = "development"
    STAGING = "staging"
    PRODUCTION = "production"


class ModelStrategy(str, Enum):
    """User-selectable cost/quality presets."""
    ECONOMY = "economy"       # ~$0.08 per landing
    BALANCE = "balance"       # ~$0.40 per landing (default)
    QUALITY = "quality"       # ~$0.80 per landing
    MAXIMUM = "maximum"       # ~$2.50 per landing


@dataclass(frozen=True)
class DatabaseConfig:
    host: str = os.getenv("POSTGRES_HOST", "localhost")
    port: int = int(os.getenv("POSTGRES_PORT", "5432"))
    name: str = os.getenv("POSTGRES_DB", "arcane")
    user: str = os.getenv("POSTGRES_USER", "arcane")
    password: str = os.getenv("POSTGRES_PASSWORD", "")

    @property
    def url(self) -> str:
        return f"postgresql+asyncpg://{self.user}:{self.password}@{self.host}:{self.port}/{self.name}"

    @property
    def sync_url(self) -> str:
        return f"postgresql://{self.user}:{self.password}@{self.host}:{self.port}/{self.name}"


@dataclass(frozen=True)
class RedisConfig:
    host: str = os.getenv("REDIS_HOST", "localhost")
    port: int = int(os.getenv("REDIS_PORT", "6380"))
    password: str = os.getenv("REDIS_PASSWORD", "")
    db: int = int(os.getenv("REDIS_DB", "0"))

    @property
    def url(self) -> str:
        auth = f":{self.password}@" if self.password else ""
        return f"redis://{auth}{self.host}:{self.port}/{self.db}"


@dataclass(frozen=True)
class MinIOConfig:
    endpoint: str = os.getenv("MINIO_ENDPOINT", "localhost:9000")
    access_key: str = os.getenv("MINIO_ACCESS_KEY", "")
    secret_key: str = os.getenv("MINIO_SECRET_KEY", "")
    bucket: str = os.getenv("MINIO_BUCKET", "arcane-artifacts")
    secure: bool = os.getenv("MINIO_SECURE", "false").lower() == "true"


@dataclass(frozen=True)
class QdrantConfig:
    host: str = os.getenv("QDRANT_HOST", "localhost")
    port: int = int(os.getenv("QDRANT_PORT", "6333"))
    collection: str = os.getenv("QDRANT_COLLECTION", "arcane_memory")


@dataclass(frozen=True)
class OpenAIConfig:
    api_key: str = os.getenv("OPENAI_API_KEY", "")
    base_url: str = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
    max_retries: int = 3
    timeout: int = 120


@dataclass(frozen=True)
class OpenRouterConfig:
    api_key: str = os.getenv("OPENROUTER_API_KEY", "")
    base_url: str = "https://openrouter.ai/api/v1"
    max_retries: int = 3
    timeout: int = 120


@dataclass(frozen=True)
class TavilyConfig:
    api_key: str = os.getenv("TAVILY_API_KEY", "")
    base_url: str = "https://api.tavily.com"


@dataclass(frozen=True)
class DeployConfig:
    vercel_token: str = os.getenv("VERCEL_TOKEN", "")
    cloudflare_api_token: str = os.getenv("CLOUDFLARE_API_TOKEN", "")
    cloudflare_zone_id: str = os.getenv("CLOUDFLARE_ZONE_ID", "")
    default_vps_host: str = os.getenv("DEFAULT_VPS_HOST", "")
    default_vps_user: str = os.getenv("DEFAULT_VPS_USER", "root")
    default_vps_key_path: str = os.getenv("DEFAULT_VPS_KEY_PATH", "~/.ssh/id_rsa")


@dataclass(frozen=True)
class RateLimitConfig:
    """Per-user rate limits to prevent one user from exhausting API quotas."""
    max_parallel_projects: int = int(os.getenv("MAX_PARALLEL_PROJECTS", "3"))
    max_requests_per_minute_openai: int = int(os.getenv("RATE_LIMIT_OPENAI_RPM", "60"))
    max_requests_per_minute_openrouter: int = int(os.getenv("RATE_LIMIT_OPENROUTER_RPM", "30"))
    max_tokens_per_minute_openai: int = int(os.getenv("RATE_LIMIT_OPENAI_TPM", "800000"))
    max_tokens_per_minute_openrouter: int = int(os.getenv("RATE_LIMIT_OPENROUTER_TPM", "400000"))


@dataclass(frozen=True)
class SelfHealingConfig:
    max_iterations: int = int(os.getenv("MAX_HEAL_ITERATIONS", "5"))
    max_tier_escalations: int = int(os.getenv("MAX_TIER_ESCALATIONS", "2"))
    sandbox_timeout: int = int(os.getenv("SANDBOX_TIMEOUT", "60"))


@dataclass(frozen=True)
class ArcaneConfig:
    """Root configuration object for the entire ARCANE system."""
    env: Environment = Environment(os.getenv("ARCANE_ENV", "production"))
    debug: bool = os.getenv("ARCANE_DEBUG", "false").lower() == "true"
    host: str = os.getenv("ARCANE_HOST", "0.0.0.0")
    port: int = int(os.getenv("ARCANE_PORT", "8100"))
    secret_key: str = os.getenv("ARCANE_SECRET_KEY", "change-me-in-production")
    default_strategy: ModelStrategy = ModelStrategy(
        os.getenv("DEFAULT_MODEL_STRATEGY", "balance")
    )
    default_budget_limit: float = float(os.getenv("DEFAULT_BUDGET_LIMIT", "5.0"))

    # Sub-configs
    db: DatabaseConfig = field(default_factory=DatabaseConfig)
    redis: RedisConfig = field(default_factory=RedisConfig)
    minio: MinIOConfig = field(default_factory=MinIOConfig)
    qdrant: QdrantConfig = field(default_factory=QdrantConfig)
    openai: OpenAIConfig = field(default_factory=OpenAIConfig)
    openrouter: OpenRouterConfig = field(default_factory=OpenRouterConfig)
    tavily: TavilyConfig = field(default_factory=TavilyConfig)
    deploy: DeployConfig = field(default_factory=DeployConfig)
    rate_limit: RateLimitConfig = field(default_factory=RateLimitConfig)
    self_healing: SelfHealingConfig = field(default_factory=SelfHealingConfig)

    # P1-1 FIX: Single canonical workspace root for all modules
    workspace_root: str = os.getenv("ARCANE_WORKSPACE_ROOT", "/root/workspace")

    # Phase 5: Feature flags for migration control
    # REMOVED: legacy_coder_enabled — cutover v1 (2026-03-31). Scene-only path is now default.

    # Cloudflared (already on server — used for expose_port)
    cloudflared_bin: str = os.getenv("CLOUDFLARED_BIN", "/usr/local/bin/cloudflared")
    expose_domain_suffix: str = os.getenv("EXPOSE_DOMAIN_SUFFIX", ".mksitdev.ru")

    def get_project_dir(self, project_id: str) -> str:
        """Return the canonical workspace path for a project."""
        import os as _os
        return _os.path.join(self.workspace_root, project_id)


@lru_cache(maxsize=1)
def get_config() -> ArcaneConfig:
    """True singleton config loader. Cached after first call."""
    return ArcaneConfig()

# Module-level exports for direct import
import os as _os
OPENROUTER_API_KEY = _os.getenv("OPENROUTER_API_KEY", "")
OPENAI_API_KEY = _os.getenv("OPENAI_API_KEY", "")
ANTHROPIC_API_KEY = _os.getenv("ANTHROPIC_API_KEY", "")
MANUS_API_KEY = _os.getenv("MANUS_API_KEY", "")
DEFAULT_BUDGET_USD = float(_os.getenv("DEFAULT_BUDGET_USD", "10.0"))
MAX_BUDGET_USD = float(_os.getenv("MAX_BUDGET_USD", "100.0"))
TELEGRAM_BOT_TOKEN = _os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = _os.getenv("TELEGRAM_CHAT_ID", "")
