"""
Tool definitions для agent — scratchpad, store_memory, recall_memory.
"""

SCRATCHPAD_TOOL = {
    "type": "function",
    "function": {
        "name": "update_scratchpad",
        "description": "Обновить блокнот агента. Используй для сохранения промежуточных результатов, планов, важных данных между итерациями.",
        "parameters": {
            "type": "object",
            "properties": {
                "content": {
                    "type": "string",
                    "description": "Содержимое блокнота (полностью заменяет предыдущее)"
                }
            },
            "required": ["content"]
        }
    }
}

STORE_MEMORY_TOOL = {
    "type": "function",
    "function": {
        "name": "store_memory",
        "description": "Сохранить важный факт в долгосрочную память для использования в будущих сессиях.",
        "parameters": {
            "type": "object",
            "properties": {
                "key": {
                    "type": "string",
                    "description": "Ключ/тема воспоминания"
                },
                "value": {
                    "type": "string",
                    "description": "Содержимое воспоминания"
                },
                "category": {
                    "type": "string",
                    "description": "Категория: fact, preference, project, decision",
                    "enum": ["fact", "preference", "project", "decision", "context"]
                }
            },
            "required": ["key", "value"]
        }
    }
}

RECALL_MEMORY_TOOL = {
    "type": "function",
    "function": {
        "name": "recall_memory",
        "description": "Найти воспоминания по запросу из долгосрочной памяти.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Поисковый запрос"
                }
            },
            "required": ["query"]
        }
    }
}

SNAPSHOT_TOOL = {
    "type": "function",
    "function": {
        "name": "snapshot_server",
        "description": "Сделать снимок состояния сервера для отслеживания изменений.",
        "parameters": {
            "type": "object",
            "properties": {
                "host": {
                    "type": "string",
                    "description": "IP или hostname сервера"
                }
            },
            "required": ["host"]
        }
    }
}

ALL_MEMORY_TOOLS = [
    SCRATCHPAD_TOOL,
    STORE_MEMORY_TOOL,
    RECALL_MEMORY_TOOL,
    SNAPSHOT_TOOL,
]
