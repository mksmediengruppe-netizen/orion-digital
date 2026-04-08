
# PATCH 03: Pipeline Artifacts Schemas
from shared.models.pipeline_artifacts import (  # noqa: F401
    ResearchReport, Positioning, DesignTokens,
    ContentSpec, IconsSpec, MotionSpec, ManusBrief,
    QAReport, A11yReport,
    validate_artifact, extract_json,
)
