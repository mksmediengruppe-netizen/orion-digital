"""Sprint 2 Tools Schema — extends TOOLS_SCHEMA with new Manus-like tools."""

SPRINT2_TOOLS_SCHEMA = [
    {
        "type": "function",
        "function": {
            "name": "dev_server_start",
            "description": "Start a local development server for a project directory or file and get a live preview URL. Supports static HTML, Python apps, and Node.js apps.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Path to directory or file to serve"},
                    "port": {"type": "integer", "description": "Port to run server on (default: 8080)"},
                    "server_type": {"type": "string", "enum": ["static", "python", "node"], "description": "Type of server to start"},
                    "session_id": {"type": "string", "description": "Session ID for managing multiple servers"}
                },
                "required": ["path"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "dev_server_stop",
            "description": "Stop a running development server.",
            "parameters": {
                "type": "object",
                "properties": {
                    "session_id": {"type": "string", "description": "Session ID of the server to stop"}
                },
                "required": ["session_id"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "checkpoint_create",
            "description": "Create a snapshot/checkpoint of the current workspace state. Allows rolling back to this point if something goes wrong.",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Name for this checkpoint (e.g., 'before_database_migration')"},
                    "paths": {"type": "array", "items": {"type": "string"}, "description": "List of file/directory paths to include in checkpoint"},
                    "description": {"type": "string", "description": "Description of what this checkpoint represents"},
                    "chat_id": {"type": "string", "description": "Chat ID for context"}
                },
                "required": ["name"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "checkpoint_restore",
            "description": "Restore workspace to a previous checkpoint state.",
            "parameters": {
                "type": "object",
                "properties": {
                    "checkpoint_id": {"type": "string", "description": "ID or name of the checkpoint to restore"}
                },
                "required": ["checkpoint_id"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "web_search_deep",
            "description": "Enhanced web search using multiple sources (DuckDuckGo + Bing) with synthesis. Returns more comprehensive results than basic web_search.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query"},
                    "num_results": {"type": "integer", "description": "Number of results to return (default: 10)"},
                    "synthesize": {"type": "boolean", "description": "Whether to synthesize results into a summary (default: true)"}
                },
                "required": ["query"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "code_run_file",
            "description": "Execute a code file (Python .py, Node.js .js, Shell .sh) and capture output. Supports passing arguments and environment variables.",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {"type": "string", "description": "Path to the file to execute"},
                    "args": {"type": "array", "items": {"type": "string"}, "description": "Command line arguments to pass"},
                    "timeout": {"type": "integer", "description": "Execution timeout in seconds (default: 60)"},
                    "env_vars": {"type": "object", "description": "Environment variables to set"}
                },
                "required": ["file_path"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "data_analyze",
            "description": "Analyze CSV, JSON, or Excel data files using pandas. Supports summary statistics, correlation analysis, groupby, and filtering.",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {"type": "string", "description": "Path to data file (CSV, JSON, XLSX)"},
                    "analysis_type": {"type": "string", "enum": ["summary", "correlation", "groupby", "filter"], "description": "Type of analysis to perform"},
                    "columns": {"type": "array", "items": {"type": "string"}, "description": "Specific columns to analyze"},
                    "query": {"type": "string", "description": "Query string for groupby (format: 'group_col:agg_col') or filter (pandas query syntax)"}
                },
                "required": ["file_path"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "image_process",
            "description": "Process, resize, crop, convert, or apply filters to images using Pillow.",
            "parameters": {
                "type": "object",
                "properties": {
                    "input_path": {"type": "string", "description": "Path to input image"},
                    "operations": {
                        "type": "array",
                        "description": "List of operations to apply",
                        "items": {
                            "type": "object",
                            "properties": {
                                "type": {"type": "string", "enum": ["resize", "crop", "rotate", "grayscale", "blur", "brightness", "contrast", "thumbnail"]},
                                "width": {"type": "integer"},
                                "height": {"type": "integer"},
                                "angle": {"type": "number"},
                                "factor": {"type": "number"},
                                "radius": {"type": "number"},
                                "size": {"type": "integer"}
                            }
                        }
                    },
                    "output_path": {"type": "string", "description": "Path for output image"},
                    "output_format": {"type": "string", "description": "Output format (jpg, png, webp, etc.)"}
                },
                "required": ["input_path"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "deploy_static",
            "description": "Deploy a static HTML/CSS/JS project to a public URL via nginx. Returns the public URL.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Path to directory or HTML file to deploy"},
                    "subdomain": {"type": "string", "description": "Subdomain for the deployment (auto-generated if not provided)"},
                    "chat_id": {"type": "string", "description": "Chat ID for context"}
                },
                "required": ["path"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "task_memory_save",
            "description": "Save important task learnings, facts, or context to long-term memory for future sessions.",
            "parameters": {
                "type": "object",
                "properties": {
                    "content": {"type": "string", "description": "Content to save to memory"},
                    "category": {"type": "string", "description": "Category (e.g., 'server_config', 'user_preference', 'learned_fact')"},
                    "tags": {"type": "array", "items": {"type": "string"}, "description": "Tags for easier retrieval"},
                    "importance": {"type": "integer", "description": "Importance level 1-10 (default: 5)"},
                    "chat_id": {"type": "string", "description": "Chat ID for context"}
                },
                "required": ["content"]
            }
        }
    }
]

# Extend main TOOLS_SCHEMA
try:
    from tools_schema import TOOLS_SCHEMA
    # Check if already added
    existing_names = {(t["function"]["name"] if "function" in t else t["name"]) for t in TOOLS_SCHEMA}
    for tool in SPRINT2_TOOLS_SCHEMA:
        if tool["function"]["name"] not in existing_names:
            TOOLS_SCHEMA.append(tool)
except ImportError:
    pass
