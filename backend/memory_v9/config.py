"""
Все настройки системы памяти в одном месте.
Можно переопределить через переменные окружения.
"""
import os

class MemoryConfig:
    # ── Пути ── (обновлены для ORION)
    DATA_DIR = os.environ.get("DATA_DIR", "/var/www/orion/backend/data")
    QDRANT_PATH = os.path.join(DATA_DIR, "qdrant_storage")
    SESSION_DB = os.path.join(DATA_DIR, "session_memory.db")
    GRAPH_DB = os.path.join(DATA_DIR, "knowledge_graph.db")
    PROFILES_DIR = os.path.join(DATA_DIR, "user_profiles")
    KNOWLEDGE_DIR = os.path.join(DATA_DIR, "knowledge_base")
    SCRATCHPAD_DIR = os.path.join(DATA_DIR, "scratchpads")
    SNAPSHOTS_DIR = os.path.join(DATA_DIR, "server_snapshots")
    PATTERNS_DB = os.path.join(DATA_DIR, "error_patterns.db")

    # ── Task Planner ──
    PLANNER_MIN_TASK_LENGTH = 80
    PLANNER_MAX_STEPS = 12

    # ── Goal Anchor ──
    ANCHOR_MAX_TASK_CHARS = 1200
    ANCHOR_MAX_ACTIONS = 8

    # ── Compaction ──
    COMPACT_EVERY_N = 5          # ПАТЧ W2-1: было 4
    COMPACT_MSG_THRESHOLD = 15     # ПАТЧ W2-1: было 30 — агрессивнее
    COMPACT_KEEP_FIRST = 2         # ПАТЧ W2-1: было 3
    COMPACT_KEEP_LAST = 6          # ПАТЧ W2-1: было 8

    # ── Tool Output ──
    TOOL_OUTPUT_MAX_CHARS = 2400
    SSH_HEAD_LINES = 8
    SSH_TAIL_LINES = 8

    # ── Smart History ──
    HISTORY_KEEP_FIRST = 2
    HISTORY_KEEP_LAST = 10
    HISTORY_MAX_TOTAL = 20
    HISTORY_MAX_CHARS = 15000

    # ── Memory ──
    MEMORY_MAX_ITEMS = 5
    MEMORY_MIN_SCORE = 0.15
    MEMORY_RERANK = True
    SCRATCHPAD_MAX = 3000

    # ── Embeddings ──
    EMBEDDING_MODEL = "paraphrase-multilingual-MiniLM-L12-v2"
    EMBEDDING_DIM = 384
    EMBEDDING_FALLBACK_DIM = 512  # TF-IDF fallback
    USE_NEURAL_EMBEDDINGS = True  # False = TF-IDF fallback

    # ── Knowledge Base ──
    CHUNK_SIZE = 500           # слов в чанке
    CHUNK_OVERLAP = 50         # слов перекрытия
    KB_COLLECTION = "knowledge_base"
    KB_MAX_RESULTS = 5

    # ── Knowledge Graph ──
    GRAPH_MAX_HOPS = 3         # глубина обхода графа
    GRAPH_MIN_CONFIDENCE = 0.5

    # ── Tool Learning ──
    TOOL_LEARN_MIN_USES = 2    # мин. успешных использований для «навыка»
    ERROR_PATTERN_MIN_OCCURRENCES = 2

    # ── Temporal ──
    SNAPSHOT_COMMANDS = [
        "uname -a",
        "uptime",
        "df -h",
        "free -m",
        "systemctl list-units --state=failed --no-pager",
        "docker ps --format 'table {{.Names}}\\t{{.Status}}' 2>/dev/null || true",
    ]
    SNAPSHOT_INTERVAL_HOURS = 6

    # ── Profile ──
    PROFILE_EXTRACT_AFTER_N_CHATS = 1
    PROFILE_MAX_FACTS = 50

    # ── Collaborative ──
    SHARED_COLLECTION = "shared_knowledge"

    # ── Lifecycle ──
    DECAY_INTERVAL_DAYS = 1
    DECAY_RATE = 0.05
    DECAY_DELETE_THRESHOLD = 0.15
    CONSOLIDATION_SIMILARITY = 0.85  # порог для слияния похожих записей
    MAX_MEMORY_VERSIONS = 10

    # ── Context Budget ──
    MAX_CONTEXT_TOKENS = 28000  # бюджет на весь контекст
    BUDGET_SYSTEM_PROMPT = 0.20
    BUDGET_MEMORY = 0.10
    BUDGET_HISTORY = 0.25
    BUDGET_ANCHOR = 0.10
    BUDGET_USER_MSG = 0.20
    BUDGET_RESERVE = 0.15  # для tool results во время работы
