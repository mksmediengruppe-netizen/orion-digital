"""
ARCANE Error Analyzer
Classifies raw error output (stderr, tracebacks) into structured
ErrorReport objects using 40+ regex patterns. Used by the Self-Healing
Loop to understand what went wrong and how to fix it.
"""

from __future__ import annotations

import re
from typing import Optional

from shared.models.schemas import ErrorCategory, ErrorReport, ErrorSeverity


# ═══════════════════════════════════════════════════════════════════════════════
# ERROR PATTERNS — regex → (category, severity, root_cause_template, fixes)
# ═══════════════════════════════════════════════════════════════════════════════

PATTERNS: list[tuple[str, ErrorCategory, ErrorSeverity, str, list[str], bool]] = [

    # ── Syntax Errors ─────────────────────────────────────────────────────────
    (r"SyntaxError:\s*(.+)", ErrorCategory.SYNTAX, ErrorSeverity.HIGH,
     "Python syntax error: {0}", ["Fix the syntax error in the indicated line"], True),

    (r"IndentationError:\s*(.+)", ErrorCategory.SYNTAX, ErrorSeverity.HIGH,
     "Indentation error: {0}", ["Fix indentation to use consistent spaces (4 per level)"], True),

    (r"TabError:\s*(.+)", ErrorCategory.SYNTAX, ErrorSeverity.MEDIUM,
     "Mixed tabs and spaces: {0}", ["Convert all tabs to 4 spaces"], True),

    (r"JSONDecodeError:\s*(.+)", ErrorCategory.SYNTAX, ErrorSeverity.MEDIUM,
     "Invalid JSON: {0}", ["Validate JSON structure", "Check for trailing commas"], True),

    # ── Import Errors ─────────────────────────────────────────────────────────
    (r"ModuleNotFoundError:\s*No module named '([^']+)'", ErrorCategory.IMPORT, ErrorSeverity.MEDIUM,
     "Missing Python module: {0}", ["Install with: pip install {0}", "Check virtual environment"], True),

    (r"ImportError:\s*cannot import name '([^']+)' from '([^']+)'", ErrorCategory.IMPORT, ErrorSeverity.MEDIUM,
     "Cannot import {0} from {1}", ["Check module version", "Verify the export exists"], True),

    (r"ImportError:\s*(.+)", ErrorCategory.IMPORT, ErrorSeverity.MEDIUM,
     "Import error: {0}", ["Check module installation and Python path"], True),

    # ── Runtime Errors ────────────────────────────────────────────────────────
    (r"TypeError:\s*(.+)", ErrorCategory.RUNTIME, ErrorSeverity.MEDIUM,
     "Type error: {0}", ["Check argument types", "Verify function signatures"], True),

    (r"ValueError:\s*(.+)", ErrorCategory.RUNTIME, ErrorSeverity.MEDIUM,
     "Value error: {0}", ["Validate input data", "Check value ranges"], True),

    (r"KeyError:\s*(.+)", ErrorCategory.RUNTIME, ErrorSeverity.MEDIUM,
     "Missing dictionary key: {0}", ["Use .get() with default", "Check data structure"], True),

    (r"IndexError:\s*(.+)", ErrorCategory.RUNTIME, ErrorSeverity.MEDIUM,
     "Index out of range: {0}", ["Check list/array bounds", "Add length validation"], True),

    (r"AttributeError:\s*(.+)", ErrorCategory.RUNTIME, ErrorSeverity.MEDIUM,
     "Attribute error: {0}", ["Check object type", "Verify attribute exists"], True),

    (r"NameError:\s*name '([^']+)' is not defined", ErrorCategory.RUNTIME, ErrorSeverity.HIGH,
     "Undefined variable: {0}", ["Define the variable before use", "Check for typos"], True),

    (r"ZeroDivisionError", ErrorCategory.RUNTIME, ErrorSeverity.MEDIUM,
     "Division by zero", ["Add zero-check before division"], True),

    (r"RecursionError", ErrorCategory.RUNTIME, ErrorSeverity.HIGH,
     "Maximum recursion depth exceeded", ["Add base case", "Convert to iterative"], True),

    (r"MemoryError", ErrorCategory.RUNTIME, ErrorSeverity.CRITICAL,
     "Out of memory", ["Reduce data size", "Use generators", "Increase memory limit"], False),

    (r"FileNotFoundError:\s*(.+)", ErrorCategory.RUNTIME, ErrorSeverity.MEDIUM,
     "File not found: {0}", ["Check file path", "Create directory if needed"], True),

    (r"IsADirectoryError", ErrorCategory.RUNTIME, ErrorSeverity.LOW,
     "Expected file but got directory", ["Use correct file path"], True),

    (r"UnicodeDecodeError:\s*(.+)", ErrorCategory.RUNTIME, ErrorSeverity.MEDIUM,
     "Unicode decode error: {0}", ["Specify encoding='utf-8'", "Try encoding='latin-1'"], True),

    # ── Permission Errors ─────────────────────────────────────────────────────
    (r"PermissionError:\s*(.+)", ErrorCategory.PERMISSION, ErrorSeverity.HIGH,
     "Permission denied: {0}", ["Run with sudo", "Check file permissions (chmod)"], True),

    (r"Permission denied", ErrorCategory.PERMISSION, ErrorSeverity.HIGH,
     "Permission denied", ["Check user permissions", "Use sudo if appropriate"], True),

    (r"EACCES", ErrorCategory.PERMISSION, ErrorSeverity.HIGH,
     "Access denied (EACCES)", ["Fix file/directory permissions"], True),

    # ── Network Errors ────────────────────────────────────────────────────────
    (r"ConnectionRefusedError", ErrorCategory.NETWORK, ErrorSeverity.HIGH,
     "Connection refused — service not running", ["Start the target service", "Check port number"], True),

    (r"ConnectionResetError", ErrorCategory.NETWORK, ErrorSeverity.MEDIUM,
     "Connection reset by peer", ["Retry the request", "Check network stability"], True),

    (r"TimeoutError|asyncio\.TimeoutError|httpx\.TimeoutException", ErrorCategory.TIMEOUT, ErrorSeverity.MEDIUM,
     "Operation timed out", ["Increase timeout", "Check network/service health"], True),

    (r"SSLError|SSL_ERROR|CERTIFICATE_VERIFY_FAILED", ErrorCategory.NETWORK, ErrorSeverity.HIGH,
     "SSL/TLS certificate error", ["Update certificates", "Check SSL configuration"], True),

    (r"DNSLookupError|getaddrinfo failed|Name or service not known", ErrorCategory.NETWORK, ErrorSeverity.HIGH,
     "DNS resolution failed", ["Check domain name", "Verify DNS settings"], True),

    (r"ECONNREFUSED|Connection refused", ErrorCategory.NETWORK, ErrorSeverity.HIGH,
     "Connection refused", ["Verify service is running", "Check firewall rules"], True),

    (r"502 Bad Gateway|503 Service Unavailable|504 Gateway Timeout", ErrorCategory.NETWORK, ErrorSeverity.MEDIUM,
     "Upstream server error", ["Wait and retry", "Check upstream service"], True),

    # ── Database Errors ───────────────────────────────────────────────────────
    (r"OperationalError.*(?:could not connect|Connection refused|no such table)", ErrorCategory.DATABASE, ErrorSeverity.HIGH,
     "Database connection/schema error", ["Check DB connection string", "Run migrations"], True),

    (r"IntegrityError.*(?:UNIQUE|duplicate|violates)", ErrorCategory.DATABASE, ErrorSeverity.MEDIUM,
     "Database integrity violation (duplicate)", ["Handle unique constraint", "Check for existing records"], True),

    (r"ProgrammingError.*(?:relation.*does not exist|column.*does not exist)", ErrorCategory.DATABASE, ErrorSeverity.HIGH,
     "Missing database table or column", ["Run database migrations", "Check schema"], True),

    # ── Dependency Errors ─────────────────────────────────────────────────────
    (r"npm ERR!|yarn error|pnpm ERR", ErrorCategory.DEPENDENCY, ErrorSeverity.MEDIUM,
     "Node.js package manager error", ["Delete node_modules and reinstall", "Check package.json"], True),

    (r"pip.*ERROR|Could not find a version", ErrorCategory.DEPENDENCY, ErrorSeverity.MEDIUM,
     "Python package installation error", ["Check package name", "Try different version"], True),

    (r"ENOENT.*package\.json", ErrorCategory.DEPENDENCY, ErrorSeverity.MEDIUM,
     "Missing package.json", ["Initialize with npm init", "Check working directory"], True),

    # ── Configuration Errors ──────────────────────────────────────────────────
    (r"nginx:.*\[emerg\].*(.+)", ErrorCategory.CONFIGURATION, ErrorSeverity.HIGH,
     "Nginx configuration error: {0}", ["Check nginx config syntax", "Run nginx -t"], True),

    (r"(?:EADDRINUSE|Address already in use).*?(\d+)", ErrorCategory.CONFIGURATION, ErrorSeverity.MEDIUM,
     "Port {0} already in use", ["Kill process on that port", "Use a different port"], True),

    (r"docker.*(?:Error|error).*(.+)", ErrorCategory.CONFIGURATION, ErrorSeverity.MEDIUM,
     "Docker error: {0}", ["Check Docker daemon status", "Verify Dockerfile"], True),

    # ── Security Patterns ─────────────────────────────────────────────────────
    (r"(?:password|secret|token|api_key)\s*=\s*['\"][^'\"]+['\"]", ErrorCategory.SECURITY, ErrorSeverity.CRITICAL,
     "Hardcoded secret detected", ["Move to environment variable", "Use .env file"], True),

    (r"eval\s*\(|exec\s*\(", ErrorCategory.SECURITY, ErrorSeverity.HIGH,
     "Dangerous eval/exec usage", ["Replace with safe alternative", "Validate input"], True),

    # ── Catch-all ─────────────────────────────────────────────────────────────
    (r"Traceback \(most recent call last\)", ErrorCategory.UNKNOWN, ErrorSeverity.MEDIUM,
     "Unclassified Python traceback", ["Analyze the full traceback for root cause"], True),

    (r"Error:|ERROR|FATAL|CRITICAL", ErrorCategory.UNKNOWN, ErrorSeverity.MEDIUM,
     "Unclassified error", ["Review the full error output"], True),
]


def analyze_error(raw_error: str) -> ErrorReport:
    """
    Analyze raw error output and return a structured ErrorReport.

    Scans through 40+ regex patterns to classify the error by category,
    severity, root cause, and suggested fixes. Returns the first
    (most specific) match.
    """
    if not raw_error or not raw_error.strip():
        return ErrorReport(
            category=ErrorCategory.UNKNOWN,
            severity=ErrorSeverity.LOW,
            root_cause="Empty error output",
            suggested_fixes=["Check if the command produced any output"],
            is_retryable=True,
            raw_error=raw_error,
        )

    for pattern, category, severity, cause_template, fixes, retryable in PATTERNS:
        match = re.search(pattern, raw_error, re.IGNORECASE | re.MULTILINE)
        if match:
            # Format root cause with captured groups
            groups = match.groups()
            try:
                root_cause = cause_template.format(*groups) if groups else cause_template
            except (IndexError, KeyError):
                root_cause = cause_template

            # Format fixes with captured groups
            formatted_fixes = []
            for fix in fixes:
                try:
                    formatted_fixes.append(fix.format(*groups) if groups else fix)
                except (IndexError, KeyError):
                    formatted_fixes.append(fix)

            return ErrorReport(
                category=category,
                severity=severity,
                root_cause=root_cause,
                suggested_fixes=formatted_fixes,
                is_retryable=retryable,
                raw_error=raw_error[:2000],  # Truncate for storage
                pattern_matched=pattern,
            )

    # No pattern matched
    return ErrorReport(
        category=ErrorCategory.UNKNOWN,
        severity=ErrorSeverity.MEDIUM,
        root_cause="Unrecognized error pattern",
        suggested_fixes=["Review the full error output manually"],
        is_retryable=True,
        raw_error=raw_error[:2000],
    )


def is_critical(report: ErrorReport) -> bool:
    """Check if an error is critical and should stop execution."""
    return report.severity in (ErrorSeverity.CRITICAL,) and not report.is_retryable


def should_escalate_tier(report: ErrorReport) -> bool:
    """Determine if the error warrants escalating to a higher model tier."""
    # Complex logic errors benefit from smarter models
    escalation_categories = {
        ErrorCategory.RUNTIME,
        ErrorCategory.UNKNOWN,
    }
    return (
        report.category in escalation_categories
        and report.severity in (ErrorSeverity.HIGH, ErrorSeverity.CRITICAL)
    )
