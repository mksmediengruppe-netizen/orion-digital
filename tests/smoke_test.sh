#!/bin/bash
# ═══════════════════════════════════════════════════════════════════════════════
# ARCANE 2 — Smoke Test
# Run after every deploy to verify nothing is broken.
# Usage: bash tests/smoke_test.sh [/path/to/arcane2]
# ═══════════════════════════════════════════════════════════════════════════════

set -uo pipefail

ARCANE="${1:-/root/arcane2}"
cd "$ARCANE" || { echo "ERROR: $ARCANE not found"; exit 1; }

# Add paths
export PYTHONPATH="$ARCANE:$ARCANE/core:$ARCANE/shared/llm:$ARCANE/shared:$ARCANE/shared/models:$ARCANE/workers"

P=0; F=0
t() {
    local desc="$1"; shift
    if python3 -c "$@" 2>/dev/null; then
        echo "  ✓ $desc"
        P=$((P+1))
    else
        echo "  ✗ $desc"
        F=$((F+1))
    fi
}

echo "═══ Arcane 2 Smoke Test ═══"
echo ""

echo "── Import tests ──"
t "core.orchestrator"         "from core.orchestrator import Orchestrator, RunStatus"
t "core.agent_loop"           "from core.agent_loop import AgentLoop"
t "core.intent_classifier"    "from core.intent_classifier import classify_intent"
t "core.tool_registry"        "from core.tool_registry import ToolRegistry"
t "core.tool_executor"        "from core.tool_executor import ToolExecutor"
t "core.budget_controller"    "from core.budget_controller import BudgetController"
t "core.project_manager"      "from core.project_manager import ProjectManager"
t "core.security"             "from core.security import SecurityContext"
t "core.consolidation"        "from core.consolidation import consolidate, ConsolidationConfig"
t "core.golden_paths"         "from core.golden_paths import record_run_outcome"
t "core.sandbox"              "from core.sandbox import execute"
t "core.context_manager"      "from core.context_manager import Scratchpad"
t "shared.llm.model_registry" "from shared.llm.model_registry import MODELS, ROLES"
t "shared.llm.preset_manager" "from shared.llm.preset_manager import PresetManager, PresetMode"
t "shared.llm.llm_client"     "from shared.llm.llm_client import SimpleLLMClient"
t "shared.llm.client (shim)"  "from shared.llm.client import UnifiedLLMClient, BudgetExceededError"
t "shared.llm.router"         "from shared.llm.router import ModelRouter"
t "shared.llm.usage_tracker"  "from shared.llm.usage_tracker import get_usage_tracker"
t "shared.prompt_templates"   "from shared.prompt_templates import detect_language"
t "shared.memory.engine"      "from shared.memory.engine import SuperMemoryEngine"
t "api.chat_store"            "from api.chat_store import get_messages"

echo ""
echo "── Functional tests ──"
t "ToolExecutor creates 9+ tools" \
    "from core.tool_registry import ToolRegistry; from core.tool_executor import ToolExecutor; e=ToolExecutor(registry=ToolRegistry()); assert len(e.get_tools_schema())>=9; print(f'{len(e.get_tools_schema())} tools')"

t "PresetManager resolves models" \
    "from shared.llm.preset_manager import PresetManager, PresetMode; pm=PresetManager(mode=PresetMode.OPTIMUM); m=pm.resolve_model('coder'); assert m; print(f'coder={m}')"

t "Orchestrator has agent_loop_factory" \
    "from core.orchestrator import Orchestrator; o=Orchestrator(); assert o.agent_loop_factory is not None"

t "BudgetController.get_remaining works" \
    "from core.budget_controller import BudgetController; b=BudgetController(); r=b.get_remaining('test'); print(f'remaining={r}')"

t "Model registry has 25+ models" \
    "from shared.llm.model_registry import MODELS; assert len(MODELS)>=25; print(f'{len(MODELS)} models')"

t "DeepSeek slug is correct" \
    "from shared.llm.model_registry import MODELS; m=MODELS['deepseek-v3.2']; assert 'v3-0324' in m.openrouter_id or 'deepseek-chat' in m.openrouter_id; print(m.openrouter_id)"

t "detect_language works" \
    "from shared.prompt_templates import detect_language; assert detect_language('привет')=='ru'; assert detect_language('hello')=='en'; print('OK')"

echo ""
echo "── API test (if running) ──"
if curl -sf http://localhost:8900/api/health >/dev/null 2>&1; then
    t "API health" \
        "import urllib.request,json; d=json.load(urllib.request.urlopen('http://localhost:8900/api/health')); assert d['status']=='ok'; print(d)"
    t "API models" \
        "import urllib.request,json; d=json.load(urllib.request.urlopen('http://localhost:8900/api/models')); print(f\"{d.get('count',len(d.get('models',[])))} models\")"
else
    echo "  ⊘ API not running on port 8900, skipping"
fi

echo ""
echo "═══════════════════════════════════"
echo "  Result: $P passed, $F failed"
echo "═══════════════════════════════════"

exit $F
