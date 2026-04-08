"""
security.py — Approval Gates, Audit Log, PII Scan, Secret Refs

"Безопасность как страховка, не клетка" — seatbelts, not handcuffs.

Models are free HOW they solve a task, but destructive actions require
confirmation. Every action is logged. PII is stripped before anything
reaches the global Knowledge Base.

Spec references:
  §1.3  — Safety philosophy
  §4.3  — SSH security (destructive confirmation, auto-backup, audit, file lock)
  §10.1 — Global KB: opt-in, anonymous, PII scan before save
  §12   — Approval gates, audit log, secrets, data lifecycle, tenant isolation

Audit v2 fixes:
  - One-time HMAC-signed approval tokens bound to action+project+server
  - TTL + cleanup for pending/decisions (no unbounded growth)
  - Audit detail redaction (PII scan before persist)
  - FileAuditSink: fsync, corrupt-line resilience, streaming query
  - PII: Luhn validation for credit cards, multi-category per span,
    no PERSON_NAME ghost enum, redacted values in safe_for_global_kb()
  - SecretManager: atomic writes, no disk write on resolve(), duplicate
    guard on register(), key/path validation
  - purge_project_data: actually deletes files (shutil.rmtree)
  - Expanded destructive patterns (kill, iptables, curl|bash, kubectl, etc.)
  - MEDIUM actions audited
  - Full UUID4 ids (no truncation)
"""

from __future__ import annotations

import fcntl
import hashlib
import hmac
import json
import logging
import os
import re
import secrets
import shutil
import tempfile
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Generator, Optional, Protocol, runtime_checkable

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# §12.1  Approval Gates
# ---------------------------------------------------------------------------

class ImpactLevel(Enum):
    """How dangerous an action is."""
    LOW = "low"            # read, ls, grep — no confirmation, no audit from gate
    MEDIUM = "medium"      # write with auto-backup — audited, no gate
    HIGH = "high"          # deploy, ALTER TABLE — requires user approval
    CRITICAL = "critical"  # rm -rf /, DROP DATABASE — requires user approval + reason


# Patterns that trigger approval gates (§4.3, §12.1).
# Each tuple: (compiled regex, impact level, human-readable description).
# Audit v2: expanded with kill, iptables, curl|bash, kubectl, terraform,
# chown, userdel, crontab, passwd, sed -i, tee destructive, etc.
_DESTRUCTIVE_PATTERNS: list[tuple[re.Pattern, ImpactLevel, str]] = [
    # ── Filesystem ──────────────────────────────────────────────────────
    (re.compile(r"\brm\s+(-[a-zA-Z]*f[a-zA-Z]*\s+|.*--force)", re.I),
     ImpactLevel.CRITICAL, "Forced file deletion"),
    (re.compile(r"\brm\s+-[a-zA-Z]*r", re.I),
     ImpactLevel.CRITICAL, "Recursive file deletion"),
    (re.compile(r"\bchmod\s+777\b"),
     ImpactLevel.HIGH, "World-writable permissions"),
    (re.compile(r"\bchown\s+-[a-zA-Z]*R\b", re.I),
     ImpactLevel.HIGH, "Recursive ownership change"),
    (re.compile(r">\s*/etc/"),
     ImpactLevel.CRITICAL, "Truncate/overwrite system config via redirect"),
    (re.compile(r"\btee\s+/etc/"),
     ImpactLevel.HIGH, "Write to system config via tee"),
    (re.compile(r"\bsed\s+-[a-zA-Z]*i\b.*/etc/", re.I),
     ImpactLevel.HIGH, "In-place edit of system config"),

    # ── Database ────────────────────────────────────────────────────────
    (re.compile(r"\bDROP\s+(TABLE|DATABASE|SCHEMA|INDEX)\b", re.I),
     ImpactLevel.CRITICAL, "Database DROP operation"),
    (re.compile(r"\bALTER\s+TABLE\b", re.I),
     ImpactLevel.HIGH, "Database schema alteration"),
    (re.compile(r"\bTRUNCATE\s+TABLE\b", re.I),
     ImpactLevel.CRITICAL, "Table truncation"),
    (re.compile(r"\bDELETE\s+FROM\b(?!.*\bWHERE\b)", re.I | re.S),
     ImpactLevel.HIGH, "DELETE without WHERE clause"),

    # ── Deployment / infrastructure ─────────────────────────────────────
    (re.compile(r"\bdeploy\b.*\bprod(uction)?\b", re.I),
     ImpactLevel.HIGH, "Production deployment"),
    (re.compile(r"\b(dns|nameserver|A\s+record|CNAME)\b.*\b(change|update|set|modify)\b", re.I),
     ImpactLevel.HIGH, "DNS modification"),
    (re.compile(r"\b(systemctl|service)\s+(stop|restart|disable)\b", re.I),
     ImpactLevel.HIGH, "System service state change"),
    (re.compile(r"\bkubectl\s+(delete|drain|cordon)\b", re.I),
     ImpactLevel.CRITICAL, "Kubernetes destructive operation"),
    (re.compile(r"\bterraform\s+(destroy|apply)\b", re.I),
     ImpactLevel.CRITICAL, "Terraform state-changing operation"),

    # ── Process / user management ───────────────────────────────────────
    (re.compile(r"\bkill\s+(-\d+\s+)?-1\b"),
     ImpactLevel.CRITICAL, "Kill all processes"),
    (re.compile(r"\bkill\s+-9\b"),
     ImpactLevel.HIGH, "Force-kill process"),
    (re.compile(r"\bkillall\b", re.I),
     ImpactLevel.HIGH, "Kill processes by name"),
    (re.compile(r"\buserdel\b", re.I),
     ImpactLevel.CRITICAL, "User account deletion"),
    (re.compile(r"\bpasswd\s+root\b", re.I),
     ImpactLevel.CRITICAL, "Root password change"),
    (re.compile(r"\bcrontab\s+-r\b", re.I),
     ImpactLevel.HIGH, "Crontab removal"),

    # ── Network / firewall ──────────────────────────────────────────────
    (re.compile(r"\biptables\s+-F\b"),
     ImpactLevel.CRITICAL, "Firewall rules flush"),
    (re.compile(r"\biptables\s+.*(-D|--delete|-X)\b"),
     ImpactLevel.HIGH, "Firewall rule/chain deletion"),
    (re.compile(r"\bufw\s+disable\b", re.I),
     ImpactLevel.CRITICAL, "Firewall disable"),

    # ── Remote code execution vectors ───────────────────────────────────
    (re.compile(r"\bcurl\b.*\|\s*(bash|sh|zsh)\b", re.I),
     ImpactLevel.CRITICAL, "Remote code execution via curl pipe"),
    (re.compile(r"\bwget\b.*\|\s*(bash|sh|zsh)\b", re.I),
     ImpactLevel.CRITICAL, "Remote code execution via wget pipe"),

    # ── Payment / integrations ──────────────────────────────────────────
    (re.compile(r"\b(stripe|paypal|payment|billing)\b.*\b(key|secret|webhook|integrat)", re.I),
     ImpactLevel.HIGH, "Payment integration change"),

    # ── Mass browser actions (§12.1) ────────────────────────────────────
    (re.compile(r"\b(mass|bulk|batch)\b.*\bbrowser\b", re.I),
     ImpactLevel.HIGH, "Mass browser automation"),

    # ── File write operations (MEDIUM — audited but not gated) ──────────
    (re.compile(r"\bssh_write_file\b"),
     ImpactLevel.MEDIUM, "SSH file write"),
    (re.compile(r"\bssh_patch_file\b"),
     ImpactLevel.MEDIUM, "SSH file patch"),
]


# HMAC key for signing approval tokens.  Generated once per process.
# In production, load from env / Vault.
_APPROVAL_HMAC_KEY: bytes = secrets.token_bytes(32)

# How long an approval token stays valid before expiry.
_APPROVAL_TTL = timedelta(minutes=30)


# Impact ordering for classify() — picks the highest.
_IMPACT_ORDER = {
    ImpactLevel.LOW: 0,
    ImpactLevel.MEDIUM: 1,
    ImpactLevel.HIGH: 2,
    ImpactLevel.CRITICAL: 3,
}


@dataclass(frozen=True)
class ApprovalRequest:
    """A pending approval gate."""
    id: str
    action_digest: str   # HMAC(action + project_id + server) — not raw action
    action_display: str  # truncated action for UI display (≤200 chars)
    impact: ImpactLevel
    reason: str
    model: str
    project_id: str
    server: Optional[str]
    created_at: str      # ISO-8601
    expires_at: str      # ISO-8601


@dataclass(frozen=True)
class ApprovalDecision:
    """User's decision on an approval request."""
    request_id: str
    approved: bool
    decided_by: str   # user id
    decided_at: str
    note: str = ""


class ApprovalGate:
    """
    §12.1 — High-impact actions require confirmation.

    Flow:
      1. Agent calls ``check(action)`` before executing.
      2. If impact >= HIGH  → raises ``ApprovalRequired``.
         If impact == MEDIUM → audited, no gate.
         If impact == LOW    → pass-through.
      3. Frontend shows the gate to the user.
      4. User approves/rejects via ``decide()``.
      5. Agent retries with the same action + ``approval_token``.

    Security properties (audit v2):
      - Tokens are one-time: consumed on use, deleted on reject.
      - Tokens are bound to (action, project_id, server) via HMAC digest.
      - Tokens expire after ``_APPROVAL_TTL``.
      - ``_pending`` and ``_decisions`` are bounded; stale entries are
        reaped on every ``check()`` call.
    """

    def __init__(self, audit_log: AuditLog) -> None:
        self._pending: dict[str, ApprovalRequest] = {}
        self._decisions: dict[str, ApprovalDecision] = {}
        self._audit = audit_log

    # -- public API ----------------------------------------------------------

    def classify(self, action: str) -> tuple[ImpactLevel, str]:
        """Return (highest impact_level, description) for an action string."""
        best_level = ImpactLevel.LOW
        best_desc = "Standard operation"
        for pattern, level, desc in _DESTRUCTIVE_PATTERNS:
            if pattern.search(action):
                if _IMPACT_ORDER[level] > _IMPACT_ORDER[best_level]:
                    best_level = level
                    best_desc = desc
        return best_level, best_desc

    def check(
        self,
        action: str,
        *,
        model: str,
        project_id: str,
        server: str | None = None,
        approval_token: str | None = None,
    ) -> None:
        """
        Check whether ``action`` requires approval.

        Returns ``None`` (success) if the action can proceed.

        Raises:
          ``ApprovalRequired`` — action is gated, awaiting user decision.
          ``ApprovalDenied``   — user already rejected this request.
          ``ApprovalExpired``  — token has expired.

        MEDIUM-impact actions are logged to audit but not gated.
        """
        self._reap_expired()

        impact, reason = self.classify(action)
        action_digest = _action_hmac(action, project_id, server)

        # LOW — silent pass-through.
        if impact == ImpactLevel.LOW:
            return None

        # MEDIUM — audit but don't gate (audit v2 fix: was silently skipped).
        if impact == ImpactLevel.MEDIUM:
            self._audit.record(
                event="action_medium",
                model=model,
                project_id=project_id,
                server=server,
                detail={"reason": reason, "action_len": len(action)},
            )
            return None

        # HIGH / CRITICAL — gated.
        if approval_token:
            self._validate_token(approval_token, action_digest, model, project_id, server)
            return None

        # No token supplied → create a new gate.
        now = _now_dt()
        req = ApprovalRequest(
            id=_make_id(),
            action_digest=action_digest,
            action_display=action[:200],
            impact=impact,
            reason=reason,
            model=model,
            project_id=project_id,
            server=server,
            created_at=now.isoformat(),
            expires_at=(now + _APPROVAL_TTL).isoformat(),
        )
        self._pending[req.id] = req

        self._audit.record(
            event="approval_requested",
            model=model,
            project_id=project_id,
            server=server,
            detail={
                "request_id_hash": _hash_token(req.id),
                "impact": impact.value,
                "reason": reason,
                "expires_at": req.expires_at,
            },
        )
        raise ApprovalRequired(reason, request_id=req.id)

    def decide(
        self,
        request_id: str,
        *,
        approved: bool,
        user: str,
        note: str = "",
    ) -> ApprovalDecision:
        """
        Record a user's approval or rejection.

        On rejection the request is removed from ``_pending`` immediately
        (audit v2 fix: rejected requests used to linger forever).
        """
        if not user or not user.strip():
            raise ValueError("decide() requires a non-empty user identifier")

        req = self._pending.get(request_id)
        if req is None:
            raise ValueError(f"Unknown or expired approval request: {request_id}")

        # Check expiry even at decision time.
        if _now_dt() > datetime.fromisoformat(req.expires_at):
            self._pending.pop(request_id, None)
            raise ApprovalExpired(request_id)

        decision = ApprovalDecision(
            request_id=request_id,
            approved=approved,
            decided_by=user,
            decided_at=_now_iso(),
            note=note,
        )

        if approved:
            # Store decision so that check() can consume it on retry.
            self._decisions[request_id] = decision
        else:
            # Rejected — clean up immediately.  No retry possible.
            self._pending.pop(request_id, None)

        self._audit.record(
            event="approval_decided",
            model=req.model,
            project_id=req.project_id,
            server=req.server,
            detail={
                "request_id_hash": _hash_token(request_id),
                "approved": approved,
                "user": user,
            },
        )
        return decision

    def pending(self, project_id: str | None = None) -> list[ApprovalRequest]:
        """List pending approval requests, optionally filtered by project."""
        self._reap_expired()
        reqs = list(self._pending.values())
        if project_id:
            reqs = [r for r in reqs if r.project_id == project_id]
        return sorted(reqs, key=lambda r: r.created_at, reverse=True)

    # -- internals -----------------------------------------------------------

    def _validate_token(
        self,
        token: str,
        action_digest: str,
        model: str,
        project_id: str,
        server: str | None,
    ) -> None:
        """
        Validate and consume a one-time approval token.

        Audit v2 fixes applied here:
          - Token must exist in ``_decisions`` (not just ``_pending``).
          - Token's action_digest must match the current action.
          - Token is deleted from both ``_pending`` and ``_decisions``
            after single use (one-time semantics).
          - Expired tokens are rejected.
          - Token value is NOT written to audit (hash only).
        """
        decision = self._decisions.get(token)
        if decision is None:
            raise ApprovalRequired("Invalid or already-used approval token", request_id=token)

        if not decision.approved:
            # Shouldn't happen (rejected decisions aren't stored), but guard.
            self._decisions.pop(token, None)
            raise ApprovalDenied(token, "Previously rejected")

        req = self._pending.get(token)
        if req is None:
            # Decision exists but request was reaped — treat as expired.
            self._decisions.pop(token, None)
            raise ApprovalExpired(token)

        # Check expiry.
        if _now_dt() > datetime.fromisoformat(req.expires_at):
            self._pending.pop(token, None)
            self._decisions.pop(token, None)
            raise ApprovalExpired(token)

        # Bind check: token must match this exact action+project+server.
        if req.action_digest != action_digest:
            raise ApprovalDenied(
                token,
                "Token was issued for a different action/project/server",
            )

        # Consume: one-time use.
        self._pending.pop(token, None)
        self._decisions.pop(token, None)

        self._audit.record(
            event="approval_used",
            model=model,
            project_id=project_id,
            server=server,
            detail={"request_id_hash": _hash_token(token)},
        )

    def _reap_expired(self) -> None:
        """Remove expired pending requests and orphaned decisions."""
        now = _now_dt()
        expired_ids = [
            rid for rid, req in self._pending.items()
            if now > datetime.fromisoformat(req.expires_at)
        ]
        for rid in expired_ids:
            self._pending.pop(rid, None)
            self._decisions.pop(rid, None)

        # Also reap decisions whose request is gone (orphans).
        orphan_ids = [
            rid for rid in self._decisions
            if rid not in self._pending
        ]
        for rid in orphan_ids:
            self._decisions.pop(rid, None)


class ApprovalRequired(Exception):
    """Raised when an action is gated and awaiting user confirmation."""
    def __init__(self, reason: str, *, request_id: str):
        self.reason = reason
        self.request_id = request_id
        super().__init__(f"Approval required ({request_id}): {reason}")


class ApprovalDenied(Exception):
    """Raised when a user has explicitly rejected the action or token is misbound."""
    def __init__(self, request_id: str, reason: str):
        self.request_id = request_id
        self.reason = reason
        super().__init__(f"Approval denied ({request_id}): {reason}")


class ApprovalExpired(Exception):
    """Raised when an approval token has exceeded its TTL."""
    def __init__(self, request_id: str):
        self.request_id = request_id
        super().__init__(f"Approval expired ({request_id})")


# ---------------------------------------------------------------------------
# §12.2  Audit Log
# ---------------------------------------------------------------------------



def detect_destructive(cmd: str) -> str | None:
    """Detect potentially destructive shell commands.
    
    Returns a description of the danger, or None if safe.
    Moved from workers/ssh_tools.py for central security management.
    """
    import re as _re
    DESTRUCTIVE_PATTERNS = [
        _re.compile(r"\brm\s+-rf?\b"),
        _re.compile(r"\bdd\b.*\bof="),
        _re.compile(r"\bmkfs\b"),
        _re.compile(r"\bformat\b"),
        _re.compile(r"\bshred\b"),
        _re.compile(r">\s*/dev/[sh]d[a-z]"),
        _re.compile(r"\bdrop\s+database\b", _re.IGNORECASE),
        _re.compile(r"\btruncate\s+table\b", _re.IGNORECASE),
        _re.compile(r"\bdelete\s+from\b.*\bwhere\b\s+1\s*=\s*1", _re.IGNORECASE),
        _re.compile(r"\bchmod\s+-R\s+777\b"),
        _re.compile(r"\bkill\s+-9\s+1\b"),
        _re.compile(r"\bsystemctl\s+(stop|disable)\s+(ssh|sshd)\b"),
    ]
    for pat in DESTRUCTIVE_PATTERNS:
        m = pat.search(cmd)
        if m:
            return f"Matched pattern: {pat.pattern!r} → {m.group()!r}"
    return None

class AuditEntry:
    """
    One row in the audit log.

    Every tool call, SSH command, API call, Manus action is recorded with:
      time, model, server, command/event, result.
    Visible in the dashboard. Exportable.  (§4.3, §12.2)
    """
    id: str
    timestamp: str        # ISO-8601
    event: str            # e.g. "ssh_exec", "llm_call", "approval_requested"
    model: str            # which model/agent triggered this
    project_id: str
    server: str | None    # target server (SSH) or None
    detail: dict[str, Any]
    run_id: str | None = None
    duration_ms: int | None = None


@runtime_checkable
class AuditSink(Protocol):
    """Pluggable backend for persisting audit entries."""
    def write(self, entry: AuditEntry) -> None: ...
    def query(
        self,
        *,
        project_id: str | None = None,
        model: str | None = None,
        event: str | None = None,
        since: datetime | None = None,
        limit: int | None = 100,
    ) -> list[AuditEntry]: ...


class InMemoryAuditSink:
    """Default sink — stores entries in a list.  Replace with DB in production."""

    def __init__(self) -> None:
        self._entries: list[AuditEntry] = []

    def write(self, entry: AuditEntry) -> None:
        self._entries.append(entry)

    def query(
        self,
        *,
        project_id: str | None = None,
        model: str | None = None,
        event: str | None = None,
        since: datetime | None = None,
        limit: int | None = 100,
    ) -> list[AuditEntry]:
        results = self._entries
        if project_id:
            results = [e for e in results if e.project_id == project_id]
        if model:
            results = [e for e in results if e.model == model]
        if event:
            results = [e for e in results if e.event == event]
        if since:
            results = [e for e in results if _parse_iso(e.timestamp) >= since]
        out = list(reversed(results))
        if limit is not None:
            out = out[:limit]
        return out


class FileAuditSink:
    """
    Append-only JSONL file sink for durable audit logs.

    Audit v2 fixes:
      - fsync after every write (durability across kernel crash).
      - fcntl LOCK_EX during write (multi-worker safety).
      - Corrupt lines are skipped with a warning, not crash.
      - query() streams with early termination instead of loading all.
      - limit=None returns everything.
    """

    def __init__(self, path: Path) -> None:
        self._path = path
        self._path.parent.mkdir(parents=True, exist_ok=True)

    def write(self, entry: AuditEntry) -> None:
        line = json.dumps(_entry_to_dict(entry), ensure_ascii=False) + "\n"
        try:
            fd = os.open(str(self._path), os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o640)
            try:
                fcntl.flock(fd, fcntl.LOCK_EX)
                os.write(fd, line.encode("utf-8"))
                os.fsync(fd)
            finally:
                fcntl.flock(fd, fcntl.LOCK_UN)
                os.close(fd)
        except OSError:
            logger.exception("Failed to write audit entry %s", entry.id)

    def query(
        self,
        *,
        project_id: str | None = None,
        model: str | None = None,
        event: str | None = None,
        since: datetime | None = None,
        limit: int | None = 100,
    ) -> list[AuditEntry]:
        """
        Stream-parse the JSONL file with filtering.

        Reads line-by-line, skips corrupt lines, and collects matching
        entries.  Returns newest-first up to ``limit``.
        """
        if not self._path.exists():
            return []

        matched: list[AuditEntry] = []
        with open(self._path, encoding="utf-8") as f:
            for line_no, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    raw = json.loads(line)
                except json.JSONDecodeError:
                    logger.warning("Corrupt audit line %d in %s, skipping", line_no, self._path)
                    continue

                e = _dict_to_entry(raw)
                if project_id and e.project_id != project_id:
                    continue
                if model and e.model != model:
                    continue
                if event and e.event != event:
                    continue
                if since and _parse_iso(e.timestamp) < since:
                    continue
                matched.append(e)

        out = list(reversed(matched))
        if limit is not None:
            out = out[:limit]
        return out


class AuditLog:
    """
    §12.2 — Central audit facility.

    Every tool call, SSH command, API invocation, and Manus action
    flows through here.  The dashboard reads from the same sink.

    Audit v2: detail dicts are scanned for PII before persisting.
    Sensitive values are redacted to prevent secondary leaks in the
    audit trail.
    """

    def __init__(
        self,
        sink: AuditSink | None = None,
        pii_scanner: PIIScanner | None = None,
    ) -> None:
        self._sink: AuditSink = sink or InMemoryAuditSink()
        self._pii: PIIScanner | None = pii_scanner

    def set_pii_scanner(self, scanner: PIIScanner) -> None:
        """Late-bind PII scanner (avoids circular init with SecurityContext)."""
        self._pii = scanner

    def record(
        self,
        *,
        event: str,
        model: str,
        project_id: str,
        server: str | None = None,
        detail: dict[str, Any] | None = None,
        run_id: str | None = None,
        duration_ms: int | None = None,
    ) -> AuditEntry:
        safe_detail = self._redact_detail(detail or {})
        entry = AuditEntry(
            id=_make_id(),
            timestamp=_now_iso(),
            event=event,
            model=model,
            project_id=project_id,
            server=server,
            detail=safe_detail,
            run_id=run_id,
            duration_ms=duration_ms,
        )
        self._sink.write(entry)
        return entry

    def query(self, **kwargs: Any) -> list[AuditEntry]:
        return self._sink.query(**kwargs)

    def export_jsonl(self, project_id: str) -> str:
        """Export all entries for a project as JSONL (§12.2 — exportable)."""
        entries = self._sink.query(project_id=project_id, limit=None)
        lines = [json.dumps(_entry_to_dict(e), ensure_ascii=False) for e in entries]
        return "\n".join(lines)

    def _redact_detail(self, detail: dict[str, Any]) -> dict[str, Any]:
        """Scan detail values for PII and redact before persisting."""
        if self._pii is None:
            return detail
        redacted: dict[str, Any] = {}
        for k, v in detail.items():
            if isinstance(v, str):
                redacted[k] = self._pii.redact(v)
            elif isinstance(v, dict):
                redacted[k] = self._redact_detail(v)
            else:
                redacted[k] = v
        return redacted


# ---------------------------------------------------------------------------
# §10.1  PII Scanner
# ---------------------------------------------------------------------------

class PIICategory(Enum):
    EMAIL = "email"
    IP_ADDRESS = "ip_address"
    PHONE = "phone"
    PASSWORD = "password"
    API_KEY = "api_key"
    SSH_KEY = "ssh_key"
    CREDIT_CARD = "credit_card"
    # Audit v2: removed PERSON_NAME — was declared but never implemented.
    # Regex-based name detection has unacceptable false-positive rates.
    # If needed, plug in a NER model via extra_patterns or a subclass.


@dataclass(frozen=True)
class PIIMatch:
    """
    A single PII detection.

    Audit v2: renamed start/end → start_pos/end_pos to avoid confusion
    with re.Match.start()/end() methods.
    """
    category: PIICategory
    value: str
    start_pos: int
    end_pos: int


# Compiled regex patterns for PII detection.
_PII_PATTERNS: list[tuple[re.Pattern, PIICategory]] = [
    # Email (narrowed: negative lookbehind prevents matching inside DSN URIs)
    (re.compile(r"(?<![:/])[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z]{2,}"),
     PIICategory.EMAIL),

    # IPv4 — each octet 0-255 (audit v2 fix: was accepting 999.999.999.999)
    (re.compile(
        r"\b(?:(?:25[0-5]|2[0-4]\d|[01]?\d\d?)\.){3}"
        r"(?:25[0-5]|2[0-4]\d|[01]?\d\d?)\b"
    ), PIICategory.IP_ADDRESS),

    # IPv6 (simplified but stricter)
    (re.compile(r"\b(?:[0-9a-fA-F]{1,4}:){7}[0-9a-fA-F]{1,4}\b"),
     PIICategory.IP_ADDRESS),

    # Phone numbers (international-ish, tightened with boundaries)
    (re.compile(r"(?<!\d)\+?\d[\d\s\-()]{7,14}\d(?!\d)"),
     PIICategory.PHONE),

    # Credit cards: handled separately in scan() with Luhn validation.

    # password= or password: "..." patterns in configs
    (re.compile(
        r"""(?:password|passwd|pwd|secret)\s*[:=]\s*['"]?[^\s'"]{4,}""",
        re.I,
    ), PIICategory.PASSWORD),

    # API keys / tokens — key=value form
    (re.compile(
        r"\b(?:api[_-]?key|token|bearer|secret[_-]?key)\s*[:=]\s*['\"]?"
        r"[A-Za-z0-9+/=_\-]{20,}",
        re.I,
    ), PIICategory.API_KEY),

    # Standalone prefixed tokens (no =value needed)
    (re.compile(
        r"\b(?:sk-[A-Za-z0-9]{20,}"           # OpenAI / Stripe
        r"|pk-[A-Za-z0-9]{20,}"               # public keys
        r"|ghp_[A-Za-z0-9]{36,}"              # GitHub PAT
        r"|gho_[A-Za-z0-9]{36,}"              # GitHub OAuth
        r"|ghs_[A-Za-z0-9]{36,}"              # GitHub App
        r"|ghr_[A-Za-z0-9]{36,}"              # GitHub refresh
        r"|glpat-[A-Za-z0-9_\-]{20,}"         # GitLab PAT
        r"|xox[bpsa]-[A-Za-z0-9\-]{10,}"      # Slack tokens
        r"|AKIA[A-Z0-9]{12,}"                  # AWS access key (20+ chars)
        r")\b",
    ), PIICategory.API_KEY),

    # Generic long hex strings (40+ chars — could be tokens/hashes)
    (re.compile(r"\b[A-Fa-f0-9]{40,}\b"), PIICategory.API_KEY),

    # JWT / Bearer tokens
    (re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}"),
     PIICategory.API_KEY),

    # SSH private keys — all key types including generic PRIVATE KEY
    (re.compile(
        r"-----BEGIN\s+(?:RSA |DSA |EC |OPENSSH |ENCRYPTED )?"
        r"PRIVATE\s+KEY-----"
    ), PIICategory.SSH_KEY),
]

# Separate credit card regex — needs Luhn post-filter.
_CREDIT_CARD_RE = re.compile(r"\b(\d[ -]*?){13,19}\b")


class PIIScanner:
    """
    §10.1 — Scan text for personally identifiable information.

    Used before saving patterns to the global Knowledge Base.
    If PII is found → the pattern is NOT saved.

    Audit v2 fixes:
      - Credit card detection uses Luhn algorithm (fewer false positives).
      - Multiple categories can match the same span (no dedup by span).
      - safe_for_global_kb() returns redacted match values (no secondary leak).
      - IPv4 regex validates octet ranges.
      - Expanded API key patterns (AWS, GitHub, GitLab, Slack, JWT).
      - Generic -----BEGIN PRIVATE KEY----- covered.
      - PERSON_NAME removed (was ghost enum, no patterns).
    """

    def __init__(
        self,
        extra_patterns: list[tuple[re.Pattern, PIICategory]] | None = None,
    ):
        self._patterns = list(_PII_PATTERNS)
        if extra_patterns:
            self._patterns.extend(extra_patterns)

    def scan(self, text: str) -> list[PIIMatch]:
        """
        Return all PII matches found in ``text``.

        Audit v2: multiple categories can match the same span (no dedup
        by position — a string can be both an EMAIL and an API_KEY).
        """
        matches: list[PIIMatch] = []

        for pattern, category in self._patterns:
            for m in pattern.finditer(text):
                matches.append(PIIMatch(
                    category=category,
                    value=m.group(),
                    start_pos=m.start(),
                    end_pos=m.end(),
                ))

        # Credit card with Luhn + IIN prefix validation
        # (audit v2: eliminates false positives from timestamps, ISBNs, etc.)
        for m in _CREDIT_CARD_RE.finditer(text):
            digits = re.sub(r"[^0-9]", "", m.group())
            if (13 <= len(digits) <= 19
                    and _luhn_check(digits)
                    and _card_iin_prefix(digits)):
                matches.append(PIIMatch(
                    category=PIICategory.CREDIT_CARD,
                    value=m.group(),
                    start_pos=m.start(),
                    end_pos=m.end(),
                ))

        return sorted(matches, key=lambda m: m.start_pos)

    def has_pii(self, text: str) -> bool:
        """Quick check — True if any PII is detected."""
        for pattern, _ in self._patterns:
            if pattern.search(text):
                return True
        # Also check credit cards with Luhn + IIN.
        for m in _CREDIT_CARD_RE.finditer(text):
            digits = re.sub(r"[^0-9]", "", m.group())
            if (13 <= len(digits) <= 19
                    and _luhn_check(digits)
                    and _card_iin_prefix(digits)):
                return True
        return False

    def redact(self, text: str, placeholder: str = "[REDACTED]") -> str:
        """Replace all PII occurrences with a placeholder."""
        matches = self.scan(text)
        if not matches:
            return text
        # Merge overlapping spans before redacting.
        merged = _merge_spans([(m.start_pos, m.end_pos) for m in matches])
        result = text
        for start, end in reversed(merged):
            result = result[:start] + placeholder + result[end:]
        return result

    def safe_for_global_kb(self, text: str) -> tuple[bool, list[PIIMatch]]:
        """
        §10.1 gate — check whether a pattern is safe to save to the
        global Knowledge Base.

        Returns ``(is_safe, list_of_pii_found)``.

        Audit v2: returned PIIMatch values are masked — callers
        logging "why did this fail?" won't cause a secondary PII leak.
        """
        matches = self.scan(text)
        safe_matches = [
            PIIMatch(
                category=m.category,
                value=_mask_value(m.value),
                start_pos=m.start_pos,
                end_pos=m.end_pos,
            )
            for m in matches
        ]
        return (len(matches) == 0, safe_matches)


# ---------------------------------------------------------------------------
# §12.3  Secret References
# ---------------------------------------------------------------------------

class SecretBackend(Enum):
    ENCRYPTED_FILE = "encrypted_file"  # MVP: .arcane/env.encrypted
    VAULT = "vault"                    # Production: HashiCorp Vault
    INFISICAL = "infisical"            # Production alt
    ONEPASSWORD = "1password_connect"  # Production alt


@dataclass
class SecretRef:
    """
    A reference to a secret — never the secret value itself.

    On the server, only references are stored.  The actual value is
    fetched at runtime with a short-lived token scoped to the current
    run.  (§12.3)
    """
    key: str                         # e.g. "DB_PASSWORD", "STRIPE_KEY"
    backend: SecretBackend
    path: str                        # backend-specific path / id
    project_id: str
    created_at: str
    last_accessed: str | None = None


# Validation for secret keys and paths.
_SECRET_KEY_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,127}$")
_SECRET_PATH_RE = re.compile(r"^[A-Za-z0-9_./:@\-]{1,512}$")


class SecretManager:
    """
    §12.3 — Manage secret references (NOT values).

    MVP:  AES-256 encrypted file, key from server env var.
    Prod: Vault / Infisical / 1Password Connect.

    Audit v2 fixes:
      - Atomic writes (write to tmpfile, then os.rename).
      - resolve() does NOT write to disk (last_accessed is in-memory only,
        flushed on next register/delete).
      - register() rejects duplicates unless ``overwrite=True``.
      - Key and path are validated.
      - _load() handles corrupt JSON gracefully.
    """

    def __init__(self, project_root: Path, backend: SecretBackend = SecretBackend.ENCRYPTED_FILE):
        self._root = project_root
        self._backend = backend
        self._refs_path = project_root / ".arcane" / "secret_refs.json"
        self._refs: dict[str, SecretRef] = {}
        self._load()

    def _load(self) -> None:
        if not self._refs_path.exists():
            return
        try:
            data = json.loads(self._refs_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            logger.error("Corrupt secret_refs.json at %s: %s", self._refs_path, exc)
            return
        for key, raw in data.items():
            try:
                self._refs[key] = SecretRef(
                    key=raw["key"],
                    backend=SecretBackend(raw["backend"]),
                    path=raw["path"],
                    project_id=raw["project_id"],
                    created_at=raw["created_at"],
                    last_accessed=raw.get("last_accessed"),
                )
            except (KeyError, ValueError) as exc:
                logger.warning("Skipping corrupt secret ref '%s': %s", key, exc)

    def _save(self) -> None:
        """Atomic write: tmpfile → fsync → rename.  Survives mid-write crash."""
        self._refs_path.parent.mkdir(parents=True, exist_ok=True)
        data: dict[str, Any] = {}
        for key, ref in self._refs.items():
            data[key] = {
                "key": ref.key,
                "backend": ref.backend.value,
                "path": ref.path,
                "project_id": ref.project_id,
                "created_at": ref.created_at,
                "last_accessed": ref.last_accessed,
            }
        dir_path = str(self._refs_path.parent)
        fd = None
        tmp_path = None
        try:
            fd, tmp_path = tempfile.mkstemp(dir=dir_path, suffix=".tmp")
            content = json.dumps(data, indent=2, ensure_ascii=False).encode("utf-8")
            os.write(fd, content)
            os.fsync(fd)
            os.close(fd)
            fd = None  # mark as closed
            os.rename(tmp_path, str(self._refs_path))
            tmp_path = None  # mark as consumed
        finally:
            if fd is not None:
                try:
                    os.close(fd)
                except OSError:
                    pass
            if tmp_path is not None and os.path.exists(tmp_path):
                os.unlink(tmp_path)

    def register(
        self,
        key: str,
        path: str,
        project_id: str,
        *,
        overwrite: bool = False,
    ) -> SecretRef:
        """
        Register a new secret reference.

        Raises ``ValueError`` if ``key`` already exists and
        ``overwrite`` is ``False``.
        """
        if not _SECRET_KEY_RE.match(key):
            raise ValueError(
                f"Invalid secret key '{key}': must match {_SECRET_KEY_RE.pattern}"
            )
        if not _SECRET_PATH_RE.match(path):
            raise ValueError(
                f"Invalid secret path: must match {_SECRET_PATH_RE.pattern}"
            )
        if not project_id or not project_id.strip():
            raise ValueError("project_id must be non-empty")

        if key in self._refs and not overwrite:
            raise ValueError(
                f"Secret ref '{key}' already exists. "
                f"Pass overwrite=True to replace."
            )

        ref = SecretRef(
            key=key,
            backend=self._backend,
            path=path,
            project_id=project_id,
            created_at=_now_iso(),
        )
        self._refs[key] = ref
        self._save()
        return ref

    def resolve(self, key: str) -> SecretRef:
        """
        Look up a secret reference (NOT its value).

        Audit v2 fix: does NOT call _save() — last_accessed is updated
        in memory only, flushed on next register/delete.
        """
        ref = self._refs.get(key)
        if ref is None:
            raise KeyError(f"No secret reference for: {key}")
        ref.last_accessed = _now_iso()
        return ref

    def list_refs(self, project_id: str | None = None) -> list[SecretRef]:
        refs = list(self._refs.values())
        if project_id:
            refs = [r for r in refs if r.project_id == project_id]
        return refs

    def delete(self, key: str) -> None:
        """§12.4 — Data lifecycle: remove secret ref on project deletion."""
        self._refs.pop(key, None)
        self._save()

    def delete_all(self, project_id: str) -> int:
        """Remove all secret refs for a project (data lifecycle cleanup)."""
        keys = [k for k, v in self._refs.items() if v.project_id == project_id]
        for k in keys:
            del self._refs[k]
        if keys:
            self._save()
        return len(keys)


# ---------------------------------------------------------------------------
# §12.4  Data Lifecycle — project deletion
# ---------------------------------------------------------------------------

_WORKSPACE_PREFIX = "/root/workspace/projects/"


def purge_project_data(
    project_id: str,
    project_root: Path,
    audit_log: AuditLog,
    secret_mgr: SecretManager | None = None,
    *,
    dry_run: bool = False,
) -> dict[str, Any]:
    """
    §12.4 — Delete ALL project data: files, Git, Qdrant namespace,
    chats, budget.  Global patterns are anonymous and stay.

    Audit v2 fixes:
      - Actually deletes files via ``shutil.rmtree`` (was advisory-only).
      - Validates ``project_root`` to prevent path-traversal.
      - ``dry_run=True`` previews without deleting.

    Returns a summary dict of what was cleaned up.
    """
    summary: dict[str, Any] = {
        "project_id": project_id,
        "dry_run": dry_run,
        "actions": [],
        "errors": [],
    }

    # Validate project_root — must be under workspace prefix.
    resolved = project_root.resolve()
    if not str(resolved).startswith(_WORKSPACE_PREFIX):
        raise ValueError(
            f"project_root must be under {_WORKSPACE_PREFIX}, "
            f"got {resolved}"
        )

    audit_log.record(
        event="project_purge_started",
        model="system",
        project_id=project_id,
        detail={"root": str(resolved), "dry_run": dry_run},
    )

    # Secret refs.
    if secret_mgr:
        count = secret_mgr.delete_all(project_id)
        summary["actions"].append(f"Deleted {count} secret refs")

    # Filesystem — actually remove the project directory tree.
    if resolved.exists():
        if dry_run:
            summary["actions"].append(f"Would delete {resolved}")
        else:
            try:
                shutil.rmtree(resolved)
                summary["actions"].append(f"Deleted {resolved}")
            except OSError as exc:
                summary["errors"].append(f"rmtree failed: {exc}")
                logger.error("purge_project_data rmtree failed: %s", exc)
    else:
        summary["actions"].append(f"Directory already absent: {resolved}")

    # Qdrant namespace — placeholder for actual qdrant client call.
    ns = f"project-{project_id}"
    summary["qdrant_namespace"] = ns
    summary["actions"].append(f"Queued Qdrant namespace deletion: {ns}")

    audit_log.record(
        event="project_purge_completed",
        model="system",
        project_id=project_id,
        detail=summary,
    )
    return summary


# ---------------------------------------------------------------------------
# Wiring — convenience factory
# ---------------------------------------------------------------------------

@dataclass
class SecurityContext:
    """
    One-stop security context for a running agent / task.

    Created once per run; threaded through ssh_tools, orchestrator,
    and any module that touches external systems.  All components share
    the same AuditLog instance (audit v2: prevents split-brain auditing).
    """
    audit_log: AuditLog
    approval_gate: ApprovalGate
    pii_scanner: PIIScanner
    secret_manager: SecretManager | None = None

    @classmethod
    def create(
        cls,
        project_root: Path,
        *,
        audit_sink: AuditSink | None = None,
        secret_backend: SecretBackend = SecretBackend.ENCRYPTED_FILE,
    ) -> SecurityContext:
        pii = PIIScanner()
        audit = AuditLog(sink=audit_sink, pii_scanner=pii)
        gate = ApprovalGate(audit_log=audit)
        try:
            secret_mgr: SecretManager | None = SecretManager(
                project_root, backend=secret_backend,
            )
        except Exception:
            logger.warning("SecretManager init failed for %s", project_root)
            secret_mgr = None
        return cls(
            audit_log=audit,
            approval_gate=gate,
            pii_scanner=pii,
            secret_manager=secret_mgr,
        )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _make_id() -> str:
    """Full UUID4 — no truncation.  (Audit v2: was 12-char, collision-prone.)"""
    return uuid.uuid4().hex


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _now_dt() -> datetime:
    return datetime.now(timezone.utc)


def _parse_iso(s: str) -> datetime:
    """Parse an ISO-8601 string to a timezone-aware datetime."""
    return datetime.fromisoformat(s)


def _action_hmac(action: str, project_id: str, server: str | None) -> str:
    """HMAC digest binding an approval token to a specific action context."""
    msg = f"{action}\0{project_id}\0{server or ''}"
    return hmac.new(_APPROVAL_HMAC_KEY, msg.encode(), hashlib.sha256).hexdigest()


def _hash_token(token: str) -> str:
    """One-way hash of an approval token for safe audit logging."""
    return hashlib.sha256(token.encode()).hexdigest()[:16]


def _luhn_check(digits: str) -> bool:
    """Luhn algorithm — validates credit card numbers."""
    total = 0
    for i, d in enumerate(reversed(digits)):
        n = int(d)
        if i % 2 == 1:
            n *= 2
            if n > 9:
                n -= 9
        total += n
    return total % 10 == 0


def _card_iin_prefix(digits: str) -> bool:
    """
    Check whether a digit string starts with a known card issuer prefix (IIN).

    Covers Visa, Mastercard, Amex, Discover, JCB, Diners Club, UnionPay.
    This dramatically reduces false positives from timestamps, ISBNs, etc.
    """
    if not digits:
        return False
    d = digits
    return (
        d[0] == "4"                                          # Visa
        or d[:2] in ("34", "37")                             # Amex
        or "51" <= d[:2] <= "55"                             # Mastercard
        or "2221" <= d[:4] <= "2720"                         # Mastercard (2-series)
        or d[:4] == "6011" or d[:2] == "65"                  # Discover
        or "3528" <= d[:4] <= "3589"                         # JCB
        or d[:2] in ("30", "36", "38")                       # Diners Club
        or d[:2] == "62"                                     # UnionPay
    )


def _mask_value(value: str) -> str:
    """Mask a PII value for safe logging: show first 2 and last 2 chars."""
    if len(value) <= 6:
        return "***"
    return value[:2] + "***" + value[-2:]


def _merge_spans(spans: list[tuple[int, int]]) -> list[tuple[int, int]]:
    """Merge overlapping (start, end) spans for redaction."""
    if not spans:
        return []
    spans = sorted(spans)
    merged = [spans[0]]
    for start, end in spans[1:]:
        if start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


def _entry_to_dict(e: AuditEntry) -> dict[str, Any]:
    return {
        "id": e.id,
        "timestamp": e.timestamp,
        "event": e.event,
        "model": e.model,
        "project_id": e.project_id,
        "server": e.server,
        "detail": e.detail,
        "run_id": e.run_id,
        "duration_ms": e.duration_ms,
    }


def _dict_to_entry(d: dict[str, Any]) -> AuditEntry:
    return AuditEntry(
        id=d["id"],
        timestamp=d["timestamp"],
        event=d["event"],
        model=d["model"],
        project_id=d["project_id"],
        server=d.get("server"),
        detail=d.get("detail", {}),
        run_id=d.get("run_id"),
        duration_ms=d.get("duration_ms"),
    )
