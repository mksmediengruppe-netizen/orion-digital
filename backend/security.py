"""
Security — ORION Digital v1.0 Security & Compliance
===================================================
JWT auth, RBAC, encryption, rate limiting, prompt injection detection,
audit logging, GDPR compliance.
"""

import os
import re
import json
import time
import hmac
import hashlib
import logging
import secrets
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, List, Optional
from functools import wraps

logger = logging.getLogger("security")

# ══════════════════════════════════════════════════════════════
# CONFIGURATION
# ══════════════════════════════════════════════════════════════

JWT_SECRET = os.environ.get("JWT_SECRET", secrets.token_hex(64))
JWT_ALGORITHM = "HS256"  # Use HS256 for simplicity; RS256 for production with key rotation
ACCESS_TOKEN_EXPIRY = 900  # 15 minutes
REFRESH_TOKEN_EXPIRY = 604800  # 7 days

# RBAC Roles and Permissions
ROLES = {
    "owner": {
        "level": 100,
        "permissions": [
            "chat", "use_tools", "upload_files", "manage_memory",
            "connect_integrations", "create_agents", "manage_members",
            "change_settings", "view_analytics", "delete_workspace",
            "manage_billing", "admin_panel", "export_data"
        ]
    },
    "admin": {
        "level": 80,
        "permissions": [
            "chat", "use_tools", "upload_files", "manage_memory",
            "connect_integrations", "create_agents", "manage_members",
            "change_settings", "view_analytics", "export_data", "admin_panel"
        ]
    },
    "member": {
        "level": 50,
        "permissions": [
            "chat", "use_tools", "upload_files", "manage_memory",
            "connect_integrations", "export_data"
        ]
    },
    "viewer": {
        "level": 10,
        "permissions": [
            "chat", "export_data"
        ]
    }
}

# Rate limiting configuration
RATE_LIMITS = {
    "chat": {"requests": 60, "window": 60},      # 60 req/min
    "tool": {"requests": 20, "window": 60},       # 20 req/min
    "upload": {"requests": 5, "window": 60},      # 5 req/min
    "auth": {"requests": 10, "window": 300},      # 10 req/5min
    "api": {"requests": 120, "window": 60},       # 120 req/min general
}

# File validation
ALLOWED_MIME_TYPES = {
    'application/pdf', 'application/msword',
    'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
    'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    'application/vnd.openxmlformats-officedocument.presentationml.presentation',
    'text/plain', 'text/csv', 'text/html', 'text/css', 'text/javascript',
    'application/json', 'application/xml',
    'image/png', 'image/jpeg', 'image/gif', 'image/webp', 'image/svg+xml',
    'application/zip', 'application/x-tar', 'application/gzip',
    'audio/mpeg', 'audio/wav', 'audio/ogg', 'audio/webm',
    'video/mp4', 'video/webm',
}

BLOCKED_EXTENSIONS = {
    '.exe', '.bat', '.cmd', '.com', '.scr', '.pif', '.msi',
    '.dll', '.sys', '.vbs', '.vbe', '.js', '.jse', '.wsh', '.wsf',
    '.ps1', '.psm1', '.reg', '.inf', '.hta', '.cpl',
}

MAX_FILE_SIZE = 50 * 1024 * 1024  # 50 MB

# Audit log
_audit_log_path = os.environ.get("DATA_DIR", "/var/www/orion/backend/data") + "/audit_log.json"
_audit_entries = []

# Rate limit store (in-memory)
_rate_store = {}


# ══════════════════════════════════════════════════════════════
# JWT TOKEN MANAGEMENT
# ══════════════════════════════════════════════════════════════

def create_access_token(user_id: str, role: str = "member", extra: Dict = None) -> str:
    """Create a JWT access token."""
    import base64

    now = int(time.time())
    payload = {
        "sub": user_id,
        "role": role,
        "iat": now,
        "exp": now + ACCESS_TOKEN_EXPIRY,
        "type": "access"
    }
    if extra:
        payload.update(extra)

    return _encode_jwt(payload)


def create_refresh_token(user_id: str) -> str:
    """Create a JWT refresh token."""
    now = int(time.time())
    payload = {
        "sub": user_id,
        "iat": now,
        "exp": now + REFRESH_TOKEN_EXPIRY,
        "type": "refresh",
        "jti": secrets.token_hex(16)
    }
    return _encode_jwt(payload)


def verify_token(token: str) -> Optional[Dict]:
    """Verify and decode a JWT token. Returns payload or None."""
    try:
        payload = _decode_jwt(token)
        if payload and payload.get("exp", 0) > time.time():
            return payload
        return None
    except Exception:
        return None


def _encode_jwt(payload: Dict) -> str:
    """Simple JWT encoding with HMAC-SHA256."""
    import base64

    header = {"alg": JWT_ALGORITHM, "typ": "JWT"}
    header_b64 = base64.urlsafe_b64encode(json.dumps(header).encode()).rstrip(b'=').decode()
    payload_b64 = base64.urlsafe_b64encode(json.dumps(payload).encode()).rstrip(b'=').decode()

    message = f"{header_b64}.{payload_b64}"
    signature = hmac.new(JWT_SECRET.encode(), message.encode(), hashlib.sha256).digest()
    sig_b64 = base64.urlsafe_b64encode(signature).rstrip(b'=').decode()

    return f"{header_b64}.{payload_b64}.{sig_b64}"


def _decode_jwt(token: str) -> Optional[Dict]:
    """Decode and verify JWT token."""
    import base64

    parts = token.split('.')
    if len(parts) != 3:
        return None

    header_b64, payload_b64, sig_b64 = parts

    # Verify signature
    message = f"{header_b64}.{payload_b64}"
    expected_sig = hmac.new(JWT_SECRET.encode(), message.encode(), hashlib.sha256).digest()
    expected_sig_b64 = base64.urlsafe_b64encode(expected_sig).rstrip(b'=').decode()

    if not hmac.compare_digest(sig_b64, expected_sig_b64):
        return None

    # Decode payload
    padding = 4 - len(payload_b64) % 4
    if padding != 4:
        payload_b64 += '=' * padding

    payload = json.loads(base64.urlsafe_b64decode(payload_b64))
    return payload


# ══════════════════════════════════════════════════════════════
# RBAC
# ══════════════════════════════════════════════════════════════

def check_permission(role: str, permission: str) -> bool:
    """Check if a role has a specific permission."""
    role_config = ROLES.get(role, ROLES["viewer"])
    return permission in role_config["permissions"]


def get_role_level(role: str) -> int:
    """Get numeric level for a role (higher = more permissions)."""
    return ROLES.get(role, ROLES["viewer"])["level"]


def require_permission(permission: str):
    """Decorator to require a specific permission."""
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            from flask import request, jsonify
            role = getattr(request, 'user_role', 'viewer')
            if not check_permission(role, permission):
                return jsonify({
                    "error": {
                        "type": "permission_error",
                        "message": f"У вас нет прав для этого действия. Требуется: {permission}",
                        "code": 403
                    }
                }), 403
            return f(*args, **kwargs)
        return decorated_function
    return decorator


# ══════════════════════════════════════════════════════════════
# ENCRYPTION
# ══════════════════════════════════════════════════════════════

_ENCRYPTION_KEY = os.environ.get("ENCRYPTION_KEY", JWT_SECRET[:32])


def _get_fernet():
    """Get Fernet instance for AES-256 encryption."""
    import base64
    try:
        from cryptography.fernet import Fernet
        # Derive a 32-byte key from _ENCRYPTION_KEY via SHA-256, then base64-encode for Fernet
        key_bytes = hashlib.sha256(_ENCRYPTION_KEY.encode()).digest()
        fernet_key = base64.urlsafe_b64encode(key_bytes)
        return Fernet(fernet_key)
    except ImportError:
        return None


def encrypt_value(plaintext: str) -> str:
    """Encrypt a string value using AES-256 (Fernet) with fallback to XOR."""
    import base64
    fernet = _get_fernet()
    if fernet:
        token = fernet.encrypt(plaintext.encode('utf-8'))
        return 'fernet:' + token.decode()
    # Fallback: XOR (legacy)
    key = hashlib.sha256(_ENCRYPTION_KEY.encode()).digest()
    encrypted = bytes(a ^ b for a, b in zip(plaintext.encode('utf-8'),
                                             (key * (len(plaintext) // 32 + 1))[:len(plaintext.encode('utf-8'))]))
    return base64.urlsafe_b64encode(encrypted).decode()


def decrypt_value(ciphertext: str) -> str:
    """Decrypt an encrypted string value. Supports Fernet and legacy XOR."""
    import base64
    if ciphertext.startswith('fernet:'):
        fernet = _get_fernet()
        if fernet:
            return fernet.decrypt(ciphertext[7:].encode()).decode('utf-8')
    # Legacy XOR decryption
    key = hashlib.sha256(_ENCRYPTION_KEY.encode()).digest()
    encrypted = base64.urlsafe_b64decode(ciphertext)
    decrypted = bytes(a ^ b for a, b in zip(encrypted,
                                             (key * (len(encrypted) // 32 + 1))[:len(encrypted)]))
    return decrypted.decode('utf-8')


# ══════════════════════════════════════════════════════════════
# RATE LIMITING
# ══════════════════════════════════════════════════════════════

def check_rate_limit(user_id: str, action: str = "api") -> Dict[str, Any]:
    """
    Check rate limit for a user action.
    Returns: {allowed: bool, remaining: int, retry_after: int}
    """
    config = RATE_LIMITS.get(action, RATE_LIMITS["api"])
    max_requests = config["requests"]
    window = config["window"]

    key = f"{user_id}:{action}"
    now = time.time()

    if key not in _rate_store:
        _rate_store[key] = []

    # Remove expired entries
    _rate_store[key] = [ts for ts in _rate_store[key] if now - ts < window]

    current_count = len(_rate_store[key])

    if current_count >= max_requests:
        oldest = min(_rate_store[key]) if _rate_store[key] else now
        retry_after = int(window - (now - oldest)) + 1
        return {
            "allowed": False,
            "remaining": 0,
            "retry_after": max(1, retry_after),
            "limit": max_requests,
            "window": window
        }

    _rate_store[key].append(now)
    return {
        "allowed": True,
        "remaining": max_requests - current_count - 1,
        "retry_after": 0,
        "limit": max_requests,
        "window": window
    }


# ══════════════════════════════════════════════════════════════
# FILE VALIDATION
# ══════════════════════════════════════════════════════════════

def validate_file(filename: str, file_size: int, content_type: str = None) -> Dict[str, Any]:
    """
    Validate an uploaded file.
    Checks: size, extension, MIME type.
    """
    errors = []

    # Check file size
    if file_size > MAX_FILE_SIZE:
        size_mb = round(file_size / (1024 * 1024), 1)
        errors.append(f"Файл слишком большой ({size_mb} МБ). Максимум: 50 МБ")

    # Check extension
    ext = os.path.splitext(filename.lower())[1]
    if ext in BLOCKED_EXTENSIONS:
        errors.append(f"Тип файла {ext} запрещён по соображениям безопасности")

    # Check MIME type
    if content_type and content_type not in ALLOWED_MIME_TYPES:
        # Allow text/* and application/octet-stream as fallback
        if not content_type.startswith('text/') and content_type != 'application/octet-stream':
            errors.append(f"Неподдерживаемый тип файла: {content_type}")

    if errors:
        return {"valid": False, "errors": errors}

    return {"valid": True, "errors": []}


# ══════════════════════════════════════════════════════════════
# PROMPT INJECTION DETECTION
# ══════════════════════════════════════════════════════════════

def detect_prompt_injection(text: str) -> Dict[str, Any]:
    """
    Detect potential prompt injection attacks in user input.
    Returns: {safe: bool, risk_level: str, patterns_found: list}
    """
    patterns_found = []
    risk_score = 0

    # High-risk patterns
    high_risk_patterns = [
        (r"ignore\s+(all\s+)?previous\s+instructions", "ignore_instructions"),
        (r"forget\s+(everything|all|your)\s+(instructions|rules|training)", "forget_instructions"),
        (r"you\s+are\s+now\s+(?:a|an)\s+", "role_override"),
        (r"system\s*:\s*", "system_prompt_injection"),
        (r"<\|im_start\|>|<\|im_end\|>", "token_injection"),
        (r"\\n\\nsystem\\n", "newline_injection"),
        (r"ADMIN\s+MODE|GOD\s+MODE|DEBUG\s+MODE", "mode_override"),
    ]

    # Medium-risk patterns
    medium_risk_patterns = [
        (r"reveal\s+(your|the)\s+(system|initial)\s+prompt", "prompt_extraction"),
        (r"what\s+(are|is)\s+your\s+(instructions|rules|system\s+prompt)", "prompt_extraction"),
        (r"print\s+(your|the)\s+system\s+(prompt|message)", "prompt_extraction"),
        (r"act\s+as\s+if\s+you\s+(have\s+no|don.t\s+have)", "constraint_bypass"),
    ]

    for pattern, name in high_risk_patterns:
        if re.search(pattern, text, re.IGNORECASE):
            patterns_found.append({"pattern": name, "risk": "high"})
            risk_score += 3

    for pattern, name in medium_risk_patterns:
        if re.search(pattern, text, re.IGNORECASE):
            patterns_found.append({"pattern": name, "risk": "medium"})
            risk_score += 1

    if risk_score >= 3:
        risk_level = "high"
        safe = False
    elif risk_score >= 1:
        risk_level = "medium"
        safe = True  # Allow but log
    else:
        risk_level = "low"
        safe = True

    return {
        "safe": safe,
        "is_suspicious": not safe,
        "risk_level": risk_level,
        "risk_score": risk_score,
        "patterns_found": patterns_found
    }


def scan_output_for_leaks(text: str) -> Dict[str, Any]:
    """Scan LLM output for potential credential/data leaks."""
    leaks_found = []

    leak_patterns = [
        (r"[A-Za-z0-9+/]{40,}={0,2}", "possible_base64_key"),
        (r"sk-[a-zA-Z0-9]{20,}", "openai_api_key"),
        (r"ghp_[a-zA-Z0-9]{36}", "github_token"),
        (r"xoxb-[0-9]{10,}-[a-zA-Z0-9]{24}", "slack_token"),
        (r"password\s*[:=]\s*['\"][^'\"]{8,}['\"]", "password_in_output"),
    ]

    for pattern, name in leak_patterns:
        if re.search(pattern, text):
            leaks_found.append(name)

    return {
        "clean": len(leaks_found) == 0,
        "leaks_found": leaks_found
    }


# ══════════════════════════════════════════════════════════════
# AUDIT LOGGING
# ══════════════════════════════════════════════════════════════

def audit_log(user_id: str, action: str, resource: str = "",
              details: Dict = None, ip: str = "", user_agent: str = ""):
    """Log an audit event."""
    global _audit_entries

    entry = {
        "user_id": user_id,
        "action": action,
        "resource": resource,
        "details": details or {},
        "ip": ip,
        "user_agent": user_agent[:200] if user_agent else "",
        "timestamp": datetime.now(timezone.utc).isoformat()
    }

    _audit_entries.append(entry)

    # Persist periodically
    if len(_audit_entries) % 20 == 0:
        _save_audit_log()


def get_audit_log(user_id: str = None, action: str = None,
                  limit: int = 100) -> List[Dict]:
    """Get audit log entries."""
    _load_audit_log()
    entries = _audit_entries

    if user_id:
        entries = [e for e in entries if e.get("user_id") == user_id]
    if action:
        entries = [e for e in entries if e.get("action") == action]

    entries.sort(key=lambda x: x.get("timestamp", ""), reverse=True)
    return entries[:limit]


def _load_audit_log():
    global _audit_entries
    try:
        if os.path.exists(_audit_log_path):
            with open(_audit_log_path, "r") as f:
                _audit_entries = json.load(f)
    except Exception:
        _audit_entries = []


def _save_audit_log():
    try:
        os.makedirs(os.path.dirname(_audit_log_path), exist_ok=True)
        # Keep only last 50000 entries
        data = _audit_entries[-50000:]
        with open(_audit_log_path, "w") as f:
            json.dump(data, f, ensure_ascii=False)
    except Exception as e:
        logger.error(f"Failed to save audit log: {e}")


# ══════════════════════════════════════════════════════════════
# GDPR COMPLIANCE
# ══════════════════════════════════════════════════════════════

def export_user_data(user_id: str, db_read_func) -> Dict[str, Any]:
    """Export all user data for GDPR compliance."""
    db = db_read_func()

    user = db.get("users", {}).get(user_id, {})
    user_chats = {k: v for k, v in db.get("chats", {}).items()
                  if v.get("user_id") == user_id}

    # Get audit log entries
    audit = [e for e in _audit_entries if e.get("user_id") == user_id]

    # Get memory items
    memory_items = []
    memory = db.get("memory", {})
    for item in memory.get("episodic", []):
        if item.get("user_id") == user_id:
            memory_items.append(item)

    return {
        "user_profile": {k: v for k, v in user.items() if k != "password_hash"},
        "chats": user_chats,
        "memory": memory_items,
        "audit_log": audit[-1000:],  # Last 1000 entries
        "exported_at": datetime.now(timezone.utc).isoformat()
    }


def delete_user_data(user_id: str, db_read_func, db_write_func) -> Dict[str, Any]:
    """Hard delete all user data for GDPR compliance."""
    db = db_read_func()

    deleted = {"chats": 0, "messages": 0, "files": 0, "memory": 0}

    # Delete chats
    chats_to_delete = [k for k, v in db.get("chats", {}).items()
                       if v.get("user_id") == user_id]
    for chat_id in chats_to_delete:
        chat = db["chats"].pop(chat_id, {})
        deleted["messages"] += len(chat.get("messages", []))
        deleted["chats"] += 1

    # Delete user profile
    db.get("users", {}).pop(user_id, None)

    # Delete memory entries
    memory = db.get("memory", {})
    original_count = len(memory.get("episodic", []))
    memory["episodic"] = [e for e in memory.get("episodic", [])
                          if e.get("user_id") != user_id]
    deleted["memory"] = original_count - len(memory.get("episodic", []))
    db["memory"] = memory

    # Remove from audit log
    global _audit_entries
    _audit_entries = [e for e in _audit_entries if e.get("user_id") != user_id]
    _save_audit_log()

    db_write_func(db)

    # Log the deletion itself (anonymized)
    audit_log("system", "user_data_deleted", f"user:{user_id[:4]}***",
              {"deleted": deleted})

    return {"success": True, "deleted": deleted}


# ══════════════════════════════════════════════════════════════
# PASSWORD HASHING
# ══════════════════════════════════════════════════════════════

def hash_password(password: str) -> str:
    """Hash a password using bcrypt (with fallback to SHA-256 if bcrypt unavailable)."""
    try:
        import bcrypt
        hashed = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt(rounds=12))
        return 'bcrypt:' + hashed.decode('utf-8')
    except ImportError:
        # Fallback: salted SHA-256
        salt = secrets.token_hex(16)
        hashed = hashlib.sha256(f"{salt}:{password}".encode()).hexdigest()
        return f"{salt}:{hashed}"


def verify_password(password: str, stored_hash: str) -> bool:
    """Verify a password against stored hash. Supports bcrypt, salted SHA-256, and legacy."""
    if stored_hash.startswith('bcrypt:'):
        try:
            import bcrypt
            return bcrypt.checkpw(password.encode('utf-8'), stored_hash[7:].encode('utf-8'))
        except ImportError:
            return False

    if ':' not in stored_hash:
        # Legacy: plain SHA-256
        return hashlib.sha256(password.encode()).hexdigest() == stored_hash

    salt, expected_hash = stored_hash.split(':', 1)
    actual_hash = hashlib.sha256(f"{salt}:{password}".encode()).hexdigest()
    return hmac.compare_digest(actual_hash, expected_hash)


# ══════════════════════════════════════════════════════════════
# INPUT SANITIZATION
# ══════════════════════════════════════════════════════════════

def sanitize_input(text: str, max_length: int = 50000) -> str:
    """
    Sanitize user input: strip control characters, limit length,
    remove null bytes, normalize whitespace.
    """
    if not isinstance(text, str):
        text = str(text)

    # Remove null bytes
    text = text.replace('\x00', '')

    # Remove other control characters (except newline, tab, carriage return)
    text = re.sub(r'[\x01-\x08\x0b\x0c\x0e-\x1f\x7f]', '', text)

    # Normalize excessive whitespace (more than 3 consecutive newlines)
    text = re.sub(r'\n{4,}', '\n\n\n', text)

    # Limit length
    if len(text) > max_length:
        text = text[:max_length] + "... [truncated]"

    return text.strip()


def validate_file_upload(filename: str, file_size: int,
                         max_size: int = 50 * 1024 * 1024,
                         allowed_extensions: list = None) -> Dict[str, Any]:
    """
    Validate an uploaded file.
    Returns: {valid: bool, error: str or None}
    """
    if not filename:
        return {"valid": False, "error": "No filename provided"}

    # Check file size
    if file_size > max_size:
        return {"valid": False, "error": f"File too large: {file_size} bytes (max {max_size})"}

    # Check extension
    ext = os.path.splitext(filename)[1].lower()
    if allowed_extensions and ext not in allowed_extensions:
        return {"valid": False, "error": f"File type not allowed: {ext}"}

    # Check for path traversal
    if '..' in filename or '/' in filename or '\\' in filename:
        return {"valid": False, "error": "Invalid filename (path traversal detected)"}

    return {"valid": True, "error": None}
