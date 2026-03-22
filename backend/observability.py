"""
Observability — ORION Digital v1.0
=================================
Request tracing, structured logging, metrics collection,
health checks, and performance monitoring.
"""

import os
import time
import uuid
import json
import logging
import threading
from datetime import datetime, timezone
from typing import Dict, Any, Optional, List
from functools import wraps

logger = logging.getLogger("observability")

# ══════════════════════════════════════════════════════════════
# REQUEST TRACING
# ══════════════════════════════════════════════════════════════

_trace_store: Dict[str, Dict] = {}
_trace_lock = threading.Lock()


def generate_request_id() -> str:
    """Generate a unique request ID for tracing."""
    return f"req_{uuid.uuid4().hex[:16]}"


def start_trace(request_id: str, operation: str, metadata: Dict = None) -> Dict:
    """Start a new trace span."""
    trace = {
        "request_id": request_id,
        "operation": operation,
        "start_time": time.time(),
        "end_time": None,
        "duration_ms": None,
        "status": "in_progress",
        "spans": [],
        "metadata": metadata or {},
        "timestamp": datetime.now(timezone.utc).isoformat()
    }
    with _trace_lock:
        _trace_store[request_id] = trace
    return trace


def add_span(request_id: str, name: str, data: Dict = None) -> None:
    """Add a span to an existing trace."""
    with _trace_lock:
        trace = _trace_store.get(request_id)
        if trace:
            trace["spans"].append({
                "name": name,
                "timestamp": time.time(),
                "data": data or {}
            })


def end_trace(request_id: str, status: str = "success", error: str = None) -> Optional[Dict]:
    """End a trace and calculate duration."""
    with _trace_lock:
        trace = _trace_store.get(request_id)
        if trace:
            trace["end_time"] = time.time()
            trace["duration_ms"] = round((trace["end_time"] - trace["start_time"]) * 1000, 2)
            trace["status"] = status
            if error:
                trace["error"] = error
            return trace
    return None


def get_trace(request_id: str) -> Optional[Dict]:
    """Get trace by request ID."""
    return _trace_store.get(request_id)


# ══════════════════════════════════════════════════════════════
# METRICS COLLECTION
# ══════════════════════════════════════════════════════════════

class MetricsCollector:
    """Collects and aggregates application metrics."""

    def __init__(self):
        self._counters: Dict[str, int] = {}
        self._gauges: Dict[str, float] = {}
        self._histograms: Dict[str, List[float]] = {}
        self._lock = threading.Lock()

    def increment(self, name: str, value: int = 1):
        """Increment a counter."""
        with self._lock:
            self._counters[name] = self._counters.get(name, 0) + value

    def set_gauge(self, name: str, value: float):
        """Set a gauge value."""
        with self._lock:
            self._gauges[name] = value

    def record(self, name: str, value: float):
        """Record a value in a histogram."""
        with self._lock:
            if name not in self._histograms:
                self._histograms[name] = []
            self._histograms[name].append(value)
            # Keep only last 1000 values
            if len(self._histograms[name]) > 1000:
                self._histograms[name] = self._histograms[name][-1000:]

    def get_metrics(self) -> Dict[str, Any]:
        """Get all collected metrics."""
        with self._lock:
            result = {
                "counters": dict(self._counters),
                "gauges": dict(self._gauges),
                "histograms": {}
            }
            for name, values in self._histograms.items():
                if values:
                    sorted_vals = sorted(values)
                    result["histograms"][name] = {
                        "count": len(values),
                        "min": sorted_vals[0],
                        "max": sorted_vals[-1],
                        "avg": sum(values) / len(values),
                        "p50": sorted_vals[len(sorted_vals) // 2],
                        "p95": sorted_vals[int(len(sorted_vals) * 0.95)],
                        "p99": sorted_vals[int(len(sorted_vals) * 0.99)]
                    }
            return result

    def reset(self):
        """Reset all metrics."""
        with self._lock:
            self._counters.clear()
            self._gauges.clear()
            self._histograms.clear()


# Singleton
_metrics = MetricsCollector()


def get_metrics_collector() -> MetricsCollector:
    return _metrics


# ══════════════════════════════════════════════════════════════
# STRUCTURED LOGGING
# ══════════════════════════════════════════════════════════════

class StructuredLogger:
    """JSON-formatted structured logger."""

    def __init__(self, name: str = "orion-digital"):
        self.name = name
        self._log_file = os.environ.get("LOG_FILE", "/var/www/orion/backend/data/app.log")

    def log(self, level: str, message: str, **kwargs):
        """Write a structured log entry."""
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": level,
            "logger": self.name,
            "message": message,
            **kwargs
        }
        # Console output
        logger.log(
            getattr(logging, level.upper(), logging.INFO),
            json.dumps(entry, ensure_ascii=False)
        )
        # File output
        try:
            os.makedirs(os.path.dirname(self._log_file), exist_ok=True)
            with open(self._log_file, "a") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except Exception:
            pass

    def info(self, message: str, **kwargs):
        self.log("info", message, **kwargs)

    def warning(self, message: str, **kwargs):
        self.log("warning", message, **kwargs)

    def error(self, message: str, **kwargs):
        self.log("error", message, **kwargs)

    def debug(self, message: str, **kwargs):
        self.log("debug", message, **kwargs)


# ══════════════════════════════════════════════════════════════
# HEALTH CHECKS
# ══════════════════════════════════════════════════════════════

class HealthChecker:
    """System health monitoring."""

    def __init__(self):
        self._checks: Dict[str, callable] = {}

    def register(self, name: str, check_func: callable):
        """Register a health check function."""
        self._checks[name] = check_func

    def run_all(self) -> Dict[str, Any]:
        """Run all health checks."""
        results = {}
        overall_healthy = True

        for name, check_func in self._checks.items():
            try:
                result = check_func()
                results[name] = {
                    "status": "healthy" if result else "unhealthy",
                    "checked_at": datetime.now(timezone.utc).isoformat()
                }
                if not result:
                    overall_healthy = False
            except Exception as e:
                results[name] = {
                    "status": "error",
                    "error": str(e),
                    "checked_at": datetime.now(timezone.utc).isoformat()
                }
                overall_healthy = False

        return {
            "overall": "healthy" if overall_healthy else "unhealthy",
            "checks": results
        }


# ══════════════════════════════════════════════════════════════
# DECORATORS
# ══════════════════════════════════════════════════════════════

def traced(operation: str = None):
    """Decorator to automatically trace function execution."""
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            op_name = operation or func.__name__
            request_id = generate_request_id()
            start_trace(request_id, op_name)
            _metrics.increment(f"{op_name}_total")

            try:
                result = func(*args, **kwargs)
                trace = end_trace(request_id, "success")
                if trace:
                    _metrics.record(f"{op_name}_duration_ms", trace["duration_ms"])
                return result
            except Exception as e:
                end_trace(request_id, "error", str(e))
                _metrics.increment(f"{op_name}_errors")
                raise
        return wrapper
    return decorator


def timed(name: str = None):
    """Decorator to measure function execution time."""
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            metric_name = name or func.__name__
            start = time.time()
            try:
                return func(*args, **kwargs)
            finally:
                duration_ms = (time.time() - start) * 1000
                _metrics.record(f"{metric_name}_duration_ms", duration_ms)
        return wrapper
    return decorator
