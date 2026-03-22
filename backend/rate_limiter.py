"""
Rate Limiter + Contracts v1.0 — Защита от злоупотреблений и валидация.

Rate Limiting:
- Per-user rate limiting (requests per minute)
- Per-IP rate limiting
- Global rate limiting
- Sliding window algorithm

Contracts:
- Input validation для каждого tool
- Output validation
- Schema enforcement
"""

import time
import threading
import logging
from typing import Dict, Optional, Tuple, Any, List
from collections import defaultdict

logger = logging.getLogger("rate_limiter")


# ══════════════════════════════════════════════════════════════════
# ██ RATE LIMITER ██
# ══════════════════════════════════════════════════════════════════

class SlidingWindowRateLimiter:
    """
    Sliding window rate limiter.
    Thread-safe, in-memory.
    """

    def __init__(self, max_requests: int = 30, window_seconds: int = 60):
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._requests: Dict[str, List[float]] = defaultdict(list)
        self._lock = threading.Lock()

    def is_allowed(self, key: str) -> Tuple[bool, Dict]:
        """
        Check if request is allowed.

        Returns: (allowed, info)
            info: {remaining, reset_at, retry_after}
        """
        now = time.time()
        window_start = now - self.window_seconds

        with self._lock:
            # Clean old entries
            self._requests[key] = [
                t for t in self._requests[key] if t > window_start
            ]

            current_count = len(self._requests[key])

            if current_count >= self.max_requests:
                # Rate limited
                oldest = self._requests[key][0] if self._requests[key] else now
                retry_after = oldest + self.window_seconds - now

                return False, {
                    "remaining": 0,
                    "limit": self.max_requests,
                    "reset_at": oldest + self.window_seconds,
                    "retry_after": max(0, retry_after),
                    "current": current_count
                }

            # Allow and record
            self._requests[key].append(now)

            return True, {
                "remaining": self.max_requests - current_count - 1,
                "limit": self.max_requests,
                "reset_at": now + self.window_seconds,
                "retry_after": 0,
                "current": current_count + 1
            }

    def get_usage(self, key: str) -> Dict:
        """Get current usage for a key."""
        now = time.time()
        window_start = now - self.window_seconds

        with self._lock:
            self._requests[key] = [
                t for t in self._requests[key] if t > window_start
            ]
            current = len(self._requests[key])

        return {
            "current": current,
            "limit": self.max_requests,
            "remaining": max(0, self.max_requests - current),
            "window_seconds": self.window_seconds
        }

    def reset(self, key: str = None):
        """Reset rate limit for a key or all keys."""
        with self._lock:
            if key:
                self._requests.pop(key, None)
            else:
                self._requests.clear()


# ══════════════════════════════════════════════════════════════════
# ██ RATE LIMIT TIERS ██
# ══════════════════════════════════════════════════════════════════

class RateLimitManager:
    """
    Manages multiple rate limiters for different tiers.

    Tiers:
    - message: user messages per minute
    - api: API calls per minute
    - tool: tool executions per minute
    - global: global requests per minute
    """

    def __init__(self):
        self.limiters = {
            "message": SlidingWindowRateLimiter(max_requests=20, window_seconds=60),
            "api": SlidingWindowRateLimiter(max_requests=60, window_seconds=60),
            "tool": SlidingWindowRateLimiter(max_requests=100, window_seconds=60),
            "global": SlidingWindowRateLimiter(max_requests=500, window_seconds=60),
        }

    def check(self, tier: str, key: str) -> Tuple[bool, Dict]:
        """Check rate limit for a tier and key."""
        limiter = self.limiters.get(tier)
        if not limiter:
            return True, {"remaining": -1, "limit": -1}

        return limiter.is_allowed(key)

    def check_message(self, user_id: str) -> Tuple[bool, Dict]:
        """Check if user can send a message."""
        return self.check("message", f"user:{user_id}")

    def check_api(self, ip: str) -> Tuple[bool, Dict]:
        """Check if IP can make API call."""
        return self.check("api", f"ip:{ip}")

    def check_tool(self, user_id: str) -> Tuple[bool, Dict]:
        """Check if user can execute a tool."""
        return self.check("tool", f"user:{user_id}")

    def get_all_usage(self, user_id: str = None, ip: str = None) -> Dict:
        """Get usage across all tiers."""
        result = {}
        if user_id:
            result["message"] = self.limiters["message"].get_usage(f"user:{user_id}")
            result["tool"] = self.limiters["tool"].get_usage(f"user:{user_id}")
        if ip:
            result["api"] = self.limiters["api"].get_usage(f"ip:{ip}")
        return result


# ══════════════════════════════════════════════════════════════════
# ██ CONTRACTS (Input/Output Validation) ██
# ══════════════════════════════════════════════════════════════════

class ContractError(Exception):
    """Raised when a contract is violated."""
    def __init__(self, tool: str, field: str, message: str):
        self.tool = tool
        self.field = field
        super().__init__(f"Contract violation [{tool}.{field}]: {message}")


class ToolContracts:
    """
    Input/Output contracts for each tool.
    Validates arguments before execution and results after.
    """

    # Input contracts: tool_name -> {field: validator_func}
    INPUT_CONTRACTS = {
        "ssh_execute": {
            "host": lambda v: isinstance(v, str) and len(v) > 0 and len(v) < 256,
            "command": lambda v: isinstance(v, str) and len(v) > 0 and len(v) < 10000,
            "username": lambda v: v is None or (isinstance(v, str) and len(v) < 64),
        },
        "file_write": {
            "host": lambda v: isinstance(v, str) and len(v) > 0 and len(v) < 256,
            "path": lambda v: isinstance(v, str) and v.startswith("/") and len(v) < 1024,
            "content": lambda v: isinstance(v, str) and len(v) < 5_000_000,  # 5MB max
        },
        "file_read": {
            "host": lambda v: isinstance(v, str) and len(v) > 0,
            "path": lambda v: isinstance(v, str) and v.startswith("/") and len(v) < 1024,
        },
        "browser_navigate": {
            "url": lambda v: isinstance(v, str) and (v.startswith("http://") or v.startswith("https://")),
        },
        "browser_check_site": {
            "url": lambda v: isinstance(v, str) and (v.startswith("http://") or v.startswith("https://")),
        },
        "browser_get_text": {
            "url": lambda v: isinstance(v, str) and (v.startswith("http://") or v.startswith("https://")),
        },
        "browser_check_api": {
            "url": lambda v: isinstance(v, str) and len(v) > 0,
            "method": lambda v: v is None or v in ("GET", "POST", "PUT", "DELETE", "PATCH"),
        },
        "task_complete": {
            "summary": lambda v: isinstance(v, str) and len(v) > 0,
        }
    }

    # Output contracts: tool_name -> {field: validator_func}
    OUTPUT_CONTRACTS = {
        "ssh_execute": {
            "success": lambda v: isinstance(v, bool),
        },
        "file_write": {
            "success": lambda v: isinstance(v, bool),
        },
        "file_read": {
            "success": lambda v: isinstance(v, bool),
        },
        "browser_check_site": {
            "success": lambda v: isinstance(v, bool),
        },
    }

    # Dangerous command patterns (blocked)
    DANGEROUS_PATTERNS = [
        r"rm\s+-rf\s+/\s*$",           # rm -rf /
        r"rm\s+-rf\s+/\*",             # rm -rf /*
        r"mkfs\.",                       # mkfs.ext4 etc
        r"dd\s+if=.+of=/dev/sd",       # dd to disk
        r":(){ :\|:& };:",             # fork bomb
        r">\s*/dev/sd",                 # write to disk device
    ]

    @classmethod
    def validate_input(cls, tool_name: str, args: Dict) -> Tuple[bool, Optional[str]]:
        """
        Validate tool input arguments.

        Returns: (valid, error_message)
        """
        contracts = cls.INPUT_CONTRACTS.get(tool_name, {})

        for field, validator in contracts.items():
            value = args.get(field)
            try:
                if not validator(value):
                    return False, f"Invalid {field}: {str(value)[:100]}"
            except Exception as e:
                return False, f"Validation error for {field}: {str(e)}"

        # Check for dangerous commands
        if tool_name == "ssh_execute":
            import re
            command = args.get("command", "")
            for pattern in cls.DANGEROUS_PATTERNS:
                if re.search(pattern, command):
                    return False, f"Dangerous command blocked: {command[:100]}"

        return True, None

    @classmethod
    def validate_output(cls, tool_name: str, result: Dict) -> Tuple[bool, Optional[str]]:
        """
        Validate tool output.

        Returns: (valid, error_message)
        """
        contracts = cls.OUTPUT_CONTRACTS.get(tool_name, {})

        for field, validator in contracts.items():
            value = result.get(field)
            try:
                if not validator(value):
                    return False, f"Invalid output {field}: {str(value)[:100]}"
            except Exception as e:
                return False, f"Output validation error for {field}: {str(e)}"

        return True, None


# ══════════════════════════════════════════════════════════════════
# ██ SINGLETON ██
# ══════════════════════════════════════════════════════════════════

_rate_limit_manager: Optional[RateLimitManager] = None


def get_rate_limiter() -> RateLimitManager:
    """Get singleton RateLimitManager instance."""
    global _rate_limit_manager
    if _rate_limit_manager is None:
        _rate_limit_manager = RateLimitManager()
    return _rate_limit_manager
