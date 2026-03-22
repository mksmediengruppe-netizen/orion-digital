"""
Tool Sandbox — уровни доступа к инструментам.
==============================================

Определяет, какие инструменты доступны агенту в зависимости от:
- Режима ORION (turbo / pro / architect)
- Уровня автономности (autonomy_mode)
- Текущей фазы задачи (planning / coding / deployment / review)
- Явных разрешений пользователя

Это "паспортный контроль" перед каждым tool call.
"""

import logging
from typing import Dict, List, Optional, Set, Callable

logger = logging.getLogger("tool_sandbox")


# ═══════════════════════════════════════════
# PERMISSION LEVELS
# ═══════════════════════════════════════════

PERM_READ    = "read"       # Только чтение (поиск, просмотр)
PERM_WRITE   = "write"      # Создание/изменение файлов
PERM_EXECUTE = "execute"    # Выполнение кода, SSH команды
PERM_DEPLOY  = "deploy"     # Деплой, изменение production
PERM_ADMIN   = "admin"      # Системные операции, управление сервисами


# ═══════════════════════════════════════════
# TOOL PERMISSION MAP
# ═══════════════════════════════════════════

TOOL_PERMISSIONS: Dict[str, str] = {
    # READ
    "web_search":          PERM_READ,
    "read_url":            PERM_READ,
    "file_read":           PERM_READ,
    "browser_check_site":  PERM_READ,
    "browser_screenshot":  PERM_READ,
    "browser_get_text":    PERM_READ,
    "browser_page_info":   PERM_READ,
    "browser_elements":    PERM_READ,
    "search_knowledge":    PERM_READ,
    "get_task_charter":    PERM_READ,
    "list_snapshots":      PERM_READ,
    "task_complete":       PERM_READ,
    "update_scratchpad":   PERM_READ,
    "update_task_charter": PERM_READ,
    "memory_search":       PERM_READ,
    "memory_get":          PERM_READ,

    # WRITE
    "file_write":          PERM_WRITE,
    "create_artifact":     PERM_WRITE,
    "generate_image":      PERM_WRITE,
    "generate_file":       PERM_WRITE,
    "memory_save":         PERM_WRITE,
    "python_exec":         PERM_WRITE,
    "browser_fill":        PERM_WRITE,
    "browser_type":        PERM_WRITE,

    # EXECUTE
    "ssh_execute":         PERM_EXECUTE,
    "browser_navigate":    PERM_READ,     # reclassified: navigation is reading
    "browser_click":       PERM_EXECUTE,
    "browser_submit":      PERM_EXECUTE,
    "browser_js":          PERM_EXECUTE,
    "browser_press_key":   PERM_EXECUTE,
    "browser_scroll":      PERM_READ,     # reclassified: scrolling is reading
    "browser_hover":       PERM_READ,     # reclassified: hover is passive
    "browser_wait":        PERM_READ,     # reclassified: waiting is passive
    "browser_select":      PERM_EXECUTE,
    "ftp_upload":          PERM_EXECUTE,
    "ftp_download":        PERM_EXECUTE,
    "ftp_list":            PERM_EXECUTE,

    # DEPLOY
    "deploy_site":         PERM_DEPLOY,
    "browser_ask_auth":    PERM_DEPLOY,
    "browser_ask_user":    PERM_DEPLOY,
    "browser_takeover_done": PERM_DEPLOY,

    # ADMIN
    "manage_service":      PERM_ADMIN,
    "system_command":      PERM_ADMIN,
}

# Порядок уровней (от низкого к высокому)
PERM_ORDER = [PERM_READ, PERM_WRITE, PERM_EXECUTE, PERM_DEPLOY, PERM_ADMIN]


# ═══════════════════════════════════════════
# MODE PERMISSION SETS
# ═══════════════════════════════════════════

# Какие уровни разрешены для каждого режима ORION
MODE_PERMISSIONS: Dict[str, Set[str]] = {
    "fast": {PERM_READ, PERM_WRITE, PERM_EXECUTE},
    # REMOVED DUPLICATE: "fast":  {PERM_READ, PERM_WRITE, PERM_EXECUTE, PERM_DEPLOY},
    # REMOVED DUPLICATE LINE: "pro":            {PERM_READ, PERM_WRITE, PERM_EXECUTE, PERM_DEPLOY},
    # REMOVED DUPLICATE LINE: "architect":      {PERM_READ, PERM_WRITE, PERM_EXECUTE, PERM_DEPLOY, PERM_ADMIN},
    # REMOVED DUPLICATE LINE: "budget":         {PERM_READ, PERM_WRITE},
    # REMOVED DUPLICATE LINE: "default":        {PERM_READ, PERM_WRITE, PERM_EXECUTE},
}

# Какие уровни разрешены для каждого уровня автономности
AUTONOMY_PERMISSIONS: Dict[str, Set[str]] = {
    "full":      {PERM_READ, PERM_WRITE, PERM_EXECUTE, PERM_DEPLOY, PERM_ADMIN},
    "standard":  {PERM_READ, PERM_WRITE, PERM_EXECUTE, PERM_DEPLOY},
    "cautious":  {PERM_READ, PERM_WRITE, PERM_EXECUTE},
    "readonly":  {PERM_READ},
    "supervised":{PERM_READ, PERM_WRITE},  # Требует подтверждения для execute+
}



# ═══════════════════════════════════════════
# BROWSER INTERACTIVE TOOLS (blocked in read_only mode)
# ═══════════════════════════════════════════
BROWSER_INTERACTIVE_TOOLS = {
    "browser_click", "browser_fill", "browser_type", "browser_submit",
    "browser_js", "browser_press_key", "browser_select",
    "browser_ask_auth", "browser_ask_user", "browser_takeover_done",
}

class ToolSandbox:
    """
    Контролирует доступ к инструментам.
    
    Проверяет:
    1. Разрешён ли инструмент для текущего режима?
    2. Разрешён ли инструмент для текущего уровня автономности?
    3. Есть ли явный запрет от пользователя?
    4. Требуется ли подтверждение?
    """

    def __init__(self):
        self._explicit_allows: Set[str] = set()   # Явно разрешённые инструменты
        self._explicit_denies: Set[str] = set()    # Явно запрещённые инструменты
        self._require_confirm: Set[str] = set()    # Требуют подтверждения
        self._confirm_callback: Optional[Callable] = None
        self.browser_read_only = True  # TASK 4: browser read-only by default

    def configure(
        self,
        orion_mode: str = "default",
        autonomy_mode: str = "standard",
        explicit_allows: List[str] = None,
        explicit_denies: List[str] = None,
        require_confirm: List[str] = None
    ):
        """
        Настроить sandbox для сессии.
        
        Args:
            orion_mode: режим ORION (fast, standard, premium, ...)
            autonomy_mode: уровень автономности (full, standard, cautious, readonly)
            explicit_allows: список явно разрешённых инструментов
            explicit_denies: список явно запрещённых инструментов
            require_confirm: инструменты, требующие подтверждения
        """
        self._orion_mode = orion_mode
        self._autonomy_mode = autonomy_mode
        self._explicit_allows = set(explicit_allows or [])
        self._explicit_denies = set(explicit_denies or [])
        self._require_confirm = set(require_confirm or [])

        logger.info(
            f"[sandbox] Configured: mode={orion_mode}, autonomy={autonomy_mode}, "
            f"allows={len(self._explicit_allows)}, denies={len(self._explicit_denies)}"
        )

    def check_with_args(self, tool_name: str, args: dict = None) -> Dict:
        """Check tool + argument-level policies."""
        result = self.check(tool_name)
        if not result.get("allowed", False):
            return result
        if args:
            arg_result = validate_arguments(tool_name, args)
            if not arg_result.get("allowed", True):
                return arg_result
        return result

    def check(self, tool_name: str) -> Dict:
        """
        Проверить доступность инструмента.
        
        Returns:
            {
                "allowed": True/False,
                "reason": "...",
                "requires_confirm": True/False,
                "permission_level": "read/write/execute/deploy/admin"
            }
        """
        # Явный запрет — высший приоритет
        if tool_name in self._explicit_denies:
            return {
                "allowed": False,
                "reason": f"Инструмент явно запрещён: {tool_name}",
                "requires_confirm": False,
                "permission_level": TOOL_PERMISSIONS.get(tool_name, "unknown")
            }

        # Явное разрешение — второй приоритет
        if tool_name in self._explicit_allows:
            return {
                "allowed": True,
                "reason": f"Инструмент явно разрешён: {tool_name}",
                "requires_confirm": tool_name in self._require_confirm,
                "permission_level": TOOL_PERMISSIONS.get(tool_name, "unknown")
            }

        # Получить уровень разрешения инструмента
        tool_perm = TOOL_PERMISSIONS.get(tool_name, PERM_EXECUTE)  # По умолчанию execute

        # Получить разрешённые уровни для режима
        mode_perms = MODE_PERMISSIONS.get(
            getattr(self, "_orion_mode", "default"), 
            MODE_PERMISSIONS["default"]
        )

        # Получить разрешённые уровни для автономности
        autonomy_perms = AUTONOMY_PERMISSIONS.get(
            getattr(self, "_autonomy_mode", "standard"),
            AUTONOMY_PERMISSIONS["standard"]
        )

        # Инструмент разрешён если его уровень входит в ОБА набора
        allowed = tool_perm in mode_perms and tool_perm in autonomy_perms

        if not allowed:
            # Определить причину
            if tool_perm not in mode_perms:
                reason = (
                    f"Режим {getattr(self, '_orion_mode', 'default')} "
                    f"не поддерживает {tool_perm} операции"
                )
            else:
                reason = (
                    f"Уровень автономности {getattr(self, '_autonomy_mode', 'standard')} "
                    f"не разрешает {tool_perm} операции"
                )
            return {
                "allowed": False,
                "reason": reason,
                "requires_confirm": False,
                "permission_level": tool_perm
            }

        # Проверить требование подтверждения
        requires_confirm = (
            tool_name in self._require_confirm or
            (getattr(self, "_autonomy_mode", "standard") == "supervised" and
             tool_perm in {PERM_EXECUTE, PERM_DEPLOY, PERM_ADMIN})
        )

        return {
            "allowed": True,
            "reason": "OK",
            "requires_confirm": requires_confirm,
            "permission_level": tool_perm
        }

    def filter_tools_schema(self, tools_schema: List[Dict]) -> List[Dict]:
        """
        Фильтрует список инструментов для LLM промпта.
        Убирает запрещённые инструменты из schema.
        
        Args:
            tools_schema: список tool definitions для OpenAI API
            
        Returns:
            Отфильтрованный список
        """
        filtered = []
        for tool_def in tools_schema:
            tool_name = tool_def.get("function", {}).get("name", "")
            check = self.check(tool_name)
            if check["allowed"]:
                filtered.append(tool_def)
            else:
                logger.debug(f"[sandbox] Filtered out tool: {tool_name} ({check['reason']})")
        
        logger.info(f"[sandbox] Tools: {len(filtered)}/{len(tools_schema)} allowed")
        return filtered

    def get_allowed_tools(self) -> List[str]:
        """Список разрешённых инструментов."""
        all_tools = list(TOOL_PERMISSIONS.keys()) + list(self._explicit_allows)
        result = [t for t in all_tools if self.check(t)["allowed"]]
        # ── TASK 4: Browser read_only filter ──
        if self.browser_read_only:
            result = [t for t in result if t not in BROWSER_INTERACTIVE_TOOLS]
        return result

    def get_denied_tools(self) -> List[str]:
        """Список запрещённых инструментов."""
        all_tools = list(TOOL_PERMISSIONS.keys())
        return [t for t in all_tools if not self.check(t)["allowed"]]

    def deny_tool(self, tool_name: str):
        """Динамически запретить инструмент."""
        self._explicit_denies.add(tool_name)
        logger.info(f"[sandbox] Tool denied: {tool_name}")

    def allow_tool(self, tool_name: str):
        """Динамически разрешить инструмент."""
        self._explicit_allows.add(tool_name)
        self._explicit_denies.discard(tool_name)
        logger.info(f"[sandbox] Tool allowed: {tool_name}")

    def require_confirmation(self, tool_name: str):
        """Потребовать подтверждения для инструмента."""
        self._require_confirm.add(tool_name)


# ═══════════════════════════════════════════
# SINGLETON
# ═══════════════════════════════════════════

_tool_sandbox: Optional[ToolSandbox] = None

def get_tool_sandbox() -> ToolSandbox:
    global _tool_sandbox
    if _tool_sandbox is None:
        _tool_sandbox = ToolSandbox()
        _tool_sandbox.configure()  # Defaults
    return _tool_sandbox


# ═══════════════════════════════════════════
# ARGUMENT-LEVEL POLICIES (TASK 11)
# ═══════════════════════════════════════════
# Rules that validate specific arguments of tools before execution.
# Each rule: {"tool": str, "arg": str, "policy": "deny_pattern"|"allow_pattern"|"max_length"|"require", "value": ...}

ARGUMENT_POLICIES = [
    # SSH: block dangerous commands
    {
        "tool": "ssh_execute",
        "arg": "command",
        "policy": "deny_pattern",
        "patterns": [
            r"rm\s+-rf\s+/(?!tmp|var/www)",   # rm -rf / (except /tmp, /var/www)
            r"mkfs\.",                            # format disk
            r"dd\s+if=.*of=/dev/",               # overwrite disk
            r":(){ :|:& };:",                      # fork bomb
            r"chmod\s+-R\s+777\s+/",            # chmod 777 /
            r"shutdown|reboot|poweroff|halt",      # system shutdown
            r"iptables\s+-F",                     # flush firewall
            r"passwd\s+root",                     # change root password
            r"userdel\s+root",                    # delete root
        ],
        "reason": "Dangerous system command blocked by policy"
    },
    # SSH: max command length
    {
        "tool": "ssh_execute",
        "arg": "command",
        "policy": "max_length",
        "value": 10000,
        "reason": "SSH command too long (max 10000 chars)"
    },
    # File write: block writing to system directories
    {
        "tool": "file_write",
        "arg": "path",
        "policy": "deny_pattern",
        "patterns": [
            r"^/etc/",           # system config
            r"^/usr/",           # system binaries
            r"^/boot/",          # boot partition
            r"^/proc/",          # proc filesystem
            r"^/sys/",           # sys filesystem
            r"\.env$",          # .env files (secrets)
            r"id_rsa|id_ed25519", # SSH keys
        ],
        "reason": "Writing to protected path blocked by policy"
    },
    # File write: max content length (5MB)
    {
        "tool": "file_write",
        "arg": "content",
        "policy": "max_length",
        "value": 5_000_000,
        "reason": "File content too large (max 5MB)"
    },
    # Browser JS: block dangerous JavaScript
    {
        "tool": "browser_js",
        "arg": "code",
        "policy": "deny_pattern",
        "patterns": [
            r"document\.cookie",                  # cookie theft
            r"localStorage\.getItem.*token",      # token theft
            r"eval\(",                             # eval injection
            r"window\.location\s*=.*http",        # redirect
            r"fetch\(.*\.onion",                  # tor access
        ],
        "reason": "Dangerous JavaScript blocked by policy"
    },
    # Python exec: block dangerous imports
    {
        "tool": "python_exec",
        "arg": "code",
        "policy": "deny_pattern",
        "patterns": [
            r"import\s+subprocess",               # subprocess
            r"os\.system\(",                      # os.system
            r"os\.popen\(",                       # os.popen
            r"__import__\(",                       # dynamic import
            r"exec\(.*input",                      # exec user input
        ],
        "reason": "Dangerous Python code blocked by policy"
    },
    # Browser navigate: block dangerous URLs
    {
        "tool": "browser_navigate",
        "arg": "url",
        "policy": "deny_pattern",
        "patterns": [
            r"\.onion",                            # tor
            r"file:///etc/",                        # local file access
            r"javascript:",                         # javascript: protocol
            r"data:text/html",                      # data: XSS
        ],
        "reason": "Dangerous URL blocked by policy"
    },
]

import re

def validate_arguments(tool_name: str, args: dict) -> dict:
    """
    Validate tool arguments against policies.
    
    Returns:
        {"allowed": True} or {"allowed": False, "reason": "...", "policy": "...", "arg": "..."}
    """
    for policy in ARGUMENT_POLICIES:
        if policy["tool"] != tool_name:
            continue
        
        arg_name = policy["arg"]
        arg_value = args.get(arg_name, "")
        if not isinstance(arg_value, str):
            arg_value = str(arg_value)
        
        if policy["policy"] == "deny_pattern":
            for pattern in policy.get("patterns", []):
                try:
                    if re.search(pattern, arg_value, re.IGNORECASE):
                        logger.warning(
                            f"[POLICY] Blocked {tool_name}.{arg_name}: "
                            f"matched deny pattern '{pattern}'"
                        )
                        return {
                            "allowed": False,
                            "reason": policy.get("reason", f"Argument blocked by pattern: {pattern}"),
                            "policy": "deny_pattern",
                            "arg": arg_name,
                            "pattern": pattern
                        }
                except re.error:
                    pass
        
        elif policy["policy"] == "max_length":
            max_len = policy.get("value", 10000)
            if len(arg_value) > max_len:
                logger.warning(
                    f"[POLICY] Blocked {tool_name}.{arg_name}: "
                    f"length {len(arg_value)} > max {max_len}"
                )
                return {
                    "allowed": False,
                    "reason": policy.get("reason", f"Argument too long: {len(arg_value)} > {max_len}"),
                    "policy": "max_length",
                    "arg": arg_name
                }
        
        elif policy["policy"] == "require":
            if not arg_value or not arg_value.strip():
                return {
                    "allowed": False,
                    "reason": policy.get("reason", f"Required argument missing: {arg_name}"),
                    "policy": "require",
                    "arg": arg_name
                }
        
        elif policy["policy"] == "allow_pattern":
            patterns = policy.get("patterns", [])
            if patterns:
                matched = any(re.search(p, arg_value) for p in patterns)
                if not matched:
                    return {
                        "allowed": False,
                        "reason": policy.get("reason", f"Argument doesn't match allowed patterns"),
                        "policy": "allow_pattern",
                        "arg": arg_name
                    }
    
    return {"allowed": True}
