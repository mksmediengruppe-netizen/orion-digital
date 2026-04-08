"""
Tool definitions для agent_loop — scratchpad, memory, recall.
Добавить в TOOLS_SCHEMA.
"""

SCRATCHPAD_TOOL = {
    "type": "function",
    "function": {
        "name": "update_scratchpad",
        "description": "Обновить блокнот агента. Записывай ТЗ, планы, чек-листы, промежуточные результаты. Содержимое ВСЕГДА видно в начале каждой итерации.",
        "parameters": {"type": "object", "properties": {"content": {"type": "string", "description": "Полный текст блокнота (Markdown)"}}, "required": ["content"]}
    }
}

STORE_MEMORY_TOOL = {
    "type": "function",
    "function": {
        "name": "store_memory",
        "description": "Сохранить факт в долгосрочную память. Используй для: предпочтений пользователя, конфигов серверов, решений, навыков.",
        "parameters": {"type": "object", "properties": {
            "key": {"type": "string", "description": "Ключ (user_name, server_config, tech_stack...)"},
            "value": {"type": "string", "description": "Значение"},
            "category": {"type": "string", "description": "Категория: preference, fact, project, decision", "default": "fact"}
        }, "required": ["key", "value"]}
    }
}

RECALL_MEMORY_TOOL = {
    "type": "function",
    "function": {
        "name": "recall_memory",
        "description": "Вспомнить из долгосрочной памяти. Поиск по ключу или тексту.",
        "parameters": {"type": "object", "properties": {
            "query": {"type": "string", "description": "Что вспомнить"},
            "category": {"type": "string", "description": "Фильтр по категории (опционально)"}
        }, "required": ["query"]}
    }
}

SNAPSHOT_SERVER_TOOL = {
    "type": "function",
    "function": {
        "name": "snapshot_server",
        "description": "Сделать снимок состояния сервера (uptime, диски, сервисы, docker). Для сравнения 'что изменилось'.",
        "parameters": {"type": "object", "properties": {
            "host": {"type": "string", "description": "IP или hostname сервера"}
        }, "required": ["host"]}
    }
}

DIFF_SERVER_TOOL = {
    "type": "function",
    "function": {
        "name": "diff_server",
        "description": "Сравнить текущее состояние сервера с предыдущим снимком. Показывает что изменилось.",
        "parameters": {"type": "object", "properties": {
            "host": {"type": "string", "description": "IP или hostname сервера"}
        }, "required": ["host"]}
    }
}

# ── Structured State Tools (§2.2 Arcane 2) ──

READ_PROJECT_STATE_TOOL = {
    "type": "function",
    "function": {
        "name": "read_project_state",
        "description": "Прочитать structured state проекта (source of truth). Без section — весь state. С section — конкретный раздел (dotpath: 'tech_stack', 'design_system.colors', 'status.pages_done').",
        "parameters": {"type": "object", "properties": {
            "section": {"type": "string", "description": "Раздел (dotpath). Пусто = весь state. Примеры: tech_stack, design_system, environment.servers, personality", "default": ""}
        }}
    }
}

UPDATE_PROJECT_STATE_TOOL = {
    "type": "function",
    "function": {
        "name": "update_project_state",
        "description": "Обновить раздел structured state проекта. Доступные разделы: project_profile, tech_stack, design_system, environment, personality, status. Runs и decisions — read-only (обновляются автоматически).",
        "parameters": {"type": "object", "properties": {
            "section": {"type": "string", "description": "Раздел для обновления (dotpath). Пример: 'tech_stack.framework', 'design_system.colors'"},
            "data": {"description": "Новое значение для раздела (строка, объект или массив)"}
        }, "required": ["section", "data"]}
    }
}

ADD_DECISION_TOOL = {
    "type": "function",
    "function": {
        "name": "add_decision",
        "description": "Записать проектное/архитектурное решение в structured state. Примеры: выбор стека, отказ от технологии, изменение дизайна.",
        "parameters": {"type": "object", "properties": {
            "what": {"type": "string", "description": "Что решили (кратко)"},
            "why": {"type": "string", "description": "Почему (обоснование)", "default": ""},
            "who": {"type": "string", "description": "Кто принял решение (модель/пользователь)", "default": "agent"}
        }, "required": ["what"]}
    }
}

ALL_MEMORY_TOOLS = [
    SCRATCHPAD_TOOL,
    STORE_MEMORY_TOOL,
    RECALL_MEMORY_TOOL,
    SNAPSHOT_SERVER_TOOL,
    DIFF_SERVER_TOOL,
    READ_PROJECT_STATE_TOOL,
    UPDATE_PROJECT_STATE_TOOL,
    ADD_DECISION_TOOL,
]

# Набор без state tools (для обратной совместимости)
CORE_MEMORY_TOOLS = [
    SCRATCHPAD_TOOL,
    STORE_MEMORY_TOOL,
    RECALL_MEMORY_TOOL,
    SNAPSHOT_SERVER_TOOL,
    DIFF_SERVER_TOOL,
]

# Только state tools (для проектного контекста)
STATE_TOOLS = [
    READ_PROJECT_STATE_TOOL,
    UPDATE_PROJECT_STATE_TOOL,
    ADD_DECISION_TOOL,
]
