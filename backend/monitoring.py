"""
ORION Monitoring & Metrics Module
===================================
Provides Prometheus-compatible metrics endpoint and system health dashboard.
Tracks: HTTP requests, response times, LLM usage, sandbox stats, error rates.
"""

import time
import threading
import os
import json
import logging
import psutil
from collections import defaultdict, deque
from functools import wraps
from flask import Flask, request, Response, jsonify

logger = logging.getLogger("monitoring")

# ── Metrics Store (thread-safe) ──

class MetricsCollector:
    """Thread-safe metrics collector with Prometheus-compatible output."""

    def __init__(self):
        self._lock = threading.Lock()
        # Counters
        self.http_requests_total = defaultdict(int)  # {method_path_status: count}
        self.llm_requests_total = defaultdict(int)   # {model: count}
        self.llm_tokens_total = defaultdict(int)     # {model: tokens}
        self.errors_total = defaultdict(int)          # {type: count}
        self.sandbox_creates = 0
        self.sandbox_destroys = 0
        self.file_uploads = 0
        self.chat_messages = 0

        # Gauges
        self.active_connections = 0
        self.active_sandboxes = 0
        self.active_tasks = 0

        # Histograms (store last 1000 values)
        self.http_duration_ms = deque(maxlen=1000)
        self.llm_duration_ms = deque(maxlen=1000)
        self.llm_first_token_ms = deque(maxlen=1000)

        # System metrics cache
        self._sys_cache = {}
        self._sys_cache_time = 0

    def inc_http(self, method: str, path: str, status: int):
        with self._lock:
            key = f'{method}_{self._normalize_path(path)}_{status}'
            self.http_requests_total[key] += 1

    def observe_http_duration(self, duration_ms: float):
        with self._lock:
            self.http_duration_ms.append(duration_ms)

    def inc_llm(self, model: str, tokens: int = 0):
        with self._lock:
            self.llm_requests_total[model] += 1
            self.llm_tokens_total[model] += tokens

    def observe_llm_duration(self, duration_ms: float):
        with self._lock:
            self.llm_duration_ms.append(duration_ms)

    def inc_error(self, error_type: str):
        with self._lock:
            self.errors_total[error_type] += 1

    def inc_chat_message(self):
        with self._lock:
            self.chat_messages += 1

    def inc_file_upload(self):
        with self._lock:
            self.file_uploads += 1

    def set_active_connections(self, n: int):
        with self._lock:
            self.active_connections = n

    def set_active_sandboxes(self, n: int):
        with self._lock:
            self.active_sandboxes = n

    def set_active_tasks(self, n: int):
        with self._lock:
            self.active_tasks = n

    def _normalize_path(self, path: str) -> str:
        """Normalize path for metrics (replace IDs with :id)."""
        parts = path.strip("/").split("/")
        normalized = []
        for i, p in enumerate(parts):
            if len(p) >= 8 and not p.startswith("api"):
                normalized.append(":id")
            else:
                normalized.append(p)
        return "/".join(normalized[:4])  # max 4 segments

    def _get_system_metrics(self) -> dict:
        """Get system metrics (cached for 5 seconds)."""
        now = time.time()
        if now - self._sys_cache_time < 5:
            return self._sys_cache

        try:
            cpu_percent = psutil.cpu_percent(interval=0)
            mem = psutil.virtual_memory()
            disk = psutil.disk_usage("/")

            self._sys_cache = {
                "cpu_percent": cpu_percent,
                "memory_used_bytes": mem.used,
                "memory_total_bytes": mem.total,
                "memory_percent": mem.percent,
                "disk_used_bytes": disk.used,
                "disk_total_bytes": disk.total,
                "disk_percent": disk.percent,
            }
            self._sys_cache_time = now
        except Exception as e:
            logger.debug(f"System metrics error: {e}")

        return self._sys_cache

    def _histogram_stats(self, data: deque) -> dict:
        """Calculate histogram statistics."""
        if not data:
            return {"count": 0, "avg": 0, "p50": 0, "p95": 0, "p99": 0, "max": 0}
        sorted_data = sorted(data)
        n = len(sorted_data)
        return {
            "count": n,
            "avg": round(sum(sorted_data) / n, 2),
            "p50": round(sorted_data[int(n * 0.5)], 2),
            "p95": round(sorted_data[min(int(n * 0.95), n - 1)], 2),
            "p99": round(sorted_data[min(int(n * 0.99), n - 1)], 2),
            "max": round(sorted_data[-1], 2),
        }

    def to_prometheus(self) -> str:
        """Export metrics in Prometheus text format."""
        lines = []
        with self._lock:
            # HTTP requests
            lines.append("# HELP orion_http_requests_total Total HTTP requests")
            lines.append("# TYPE orion_http_requests_total counter")
            for key, count in self.http_requests_total.items():
                parts = key.rsplit("_", 1)
                if len(parts) == 2:
                    lines.append(f'orion_http_requests_total{{endpoint="{parts[0]}",status="{parts[1]}"}} {count}')

            # HTTP duration
            stats = self._histogram_stats(self.http_duration_ms)
            lines.append("# HELP orion_http_duration_ms HTTP request duration in ms")
            lines.append("# TYPE orion_http_duration_ms summary")
            lines.append(f'orion_http_duration_ms{{quantile="0.5"}} {stats["p50"]}')
            lines.append(f'orion_http_duration_ms{{quantile="0.95"}} {stats["p95"]}')
            lines.append(f'orion_http_duration_ms{{quantile="0.99"}} {stats["p99"]}')
            lines.append(f'orion_http_duration_ms_count {stats["count"]}')

            # LLM requests
            lines.append("# HELP orion_llm_requests_total Total LLM API calls")
            lines.append("# TYPE orion_llm_requests_total counter")
            for model, count in self.llm_requests_total.items():
                lines.append(f'orion_llm_requests_total{{model="{model}"}} {count}')

            # LLM tokens
            lines.append("# HELP orion_llm_tokens_total Total LLM tokens used")
            lines.append("# TYPE orion_llm_tokens_total counter")
            for model, tokens in self.llm_tokens_total.items():
                lines.append(f'orion_llm_tokens_total{{model="{model}"}} {tokens}')

            # Gauges
            lines.append("# HELP orion_active_connections Current active connections")
            lines.append("# TYPE orion_active_connections gauge")
            lines.append(f"orion_active_connections {self.active_connections}")

            lines.append("# HELP orion_active_sandboxes Current active sandboxes")
            lines.append("# TYPE orion_active_sandboxes gauge")
            lines.append(f"orion_active_sandboxes {self.active_sandboxes}")

            lines.append("# HELP orion_active_tasks Current active tasks")
            lines.append("# TYPE orion_active_tasks gauge")
            lines.append(f"orion_active_tasks {self.active_tasks}")

            lines.append("# HELP orion_chat_messages_total Total chat messages")
            lines.append("# TYPE orion_chat_messages_total counter")
            lines.append(f"orion_chat_messages_total {self.chat_messages}")

            lines.append("# HELP orion_file_uploads_total Total file uploads")
            lines.append("# TYPE orion_file_uploads_total counter")
            lines.append(f"orion_file_uploads_total {self.file_uploads}")

            # Errors
            lines.append("# HELP orion_errors_total Total errors by type")
            lines.append("# TYPE orion_errors_total counter")
            for etype, count in self.errors_total.items():
                lines.append(f'orion_errors_total{{type="{etype}"}} {count}')

            # System metrics
            sys_metrics = self._get_system_metrics()
            lines.append("# HELP orion_cpu_percent CPU usage percent")
            lines.append("# TYPE orion_cpu_percent gauge")
            lines.append(f'orion_cpu_percent {sys_metrics.get("cpu_percent", 0)}')

            lines.append("# HELP orion_memory_percent Memory usage percent")
            lines.append("# TYPE orion_memory_percent gauge")
            lines.append(f'orion_memory_percent {sys_metrics.get("memory_percent", 0)}')

            lines.append("# HELP orion_disk_percent Disk usage percent")
            lines.append("# TYPE orion_disk_percent gauge")
            lines.append(f'orion_disk_percent {sys_metrics.get("disk_percent", 0)}')

        return "\n".join(lines) + "\n"

    def to_json_dashboard(self) -> dict:
        """Export metrics as JSON for the built-in dashboard."""
        with self._lock:
            sys_m = self._get_system_metrics()
            return {
                "system": sys_m,
                "http": {
                    "requests": dict(self.http_requests_total),
                    "duration": self._histogram_stats(self.http_duration_ms),
                },
                "llm": {
                    "requests": dict(self.llm_requests_total),
                    "tokens": dict(self.llm_tokens_total),
                    "duration": self._histogram_stats(self.llm_duration_ms),
                },
                "counters": {
                    "chat_messages": self.chat_messages,
                    "file_uploads": self.file_uploads,
                    "sandbox_creates": self.sandbox_creates,
                    "sandbox_destroys": self.sandbox_destroys,
                },
                "gauges": {
                    "active_connections": self.active_connections,
                    "active_sandboxes": self.active_sandboxes,
                    "active_tasks": self.active_tasks,
                },
                "errors": dict(self.errors_total),
            }


# ── Singleton ──
_collector = MetricsCollector()

def get_metrics() -> MetricsCollector:
    return _collector


# ── Flask middleware ──

def metrics_middleware(app: Flask):
    """Add metrics collection middleware to Flask app."""

    @app.before_request
    def _before():
        request._start_time = time.time()

    @app.after_request
    def _after(response):
        if hasattr(request, "_start_time"):
            duration = (time.time() - request._start_time) * 1000
            _collector.observe_http_duration(duration)
            _collector.inc_http(request.method, request.path, response.status_code)
        return response


def register_metrics_routes(app: Flask):
    """Register /metrics and /api/monitoring endpoints."""

    @app.route("/metrics")
    def prometheus_metrics():
        """Prometheus scrape endpoint."""
        return Response(_collector.to_prometheus(), mimetype="text/plain; charset=utf-8")

    @app.route("/api/monitoring")
    def monitoring_dashboard():
        """JSON monitoring dashboard data."""
        return jsonify(_collector.to_json_dashboard())

    @app.route("/api/monitoring/health")
    def monitoring_health():
        """Detailed health check."""
        sys_m = _collector._get_system_metrics()
        health = {
            "status": "healthy",
            "uptime_seconds": time.time() - app.config.get("START_TIME", time.time()),
            "system": sys_m,
            "active_tasks": _collector.active_tasks,
            "active_sandboxes": _collector.active_sandboxes,
        }
        if sys_m.get("cpu_percent", 0) > 90:
            health["status"] = "degraded"
            health["warning"] = "High CPU usage"
        if sys_m.get("memory_percent", 0) > 90:
            health["status"] = "degraded"
            health["warning"] = "High memory usage"
        return jsonify(health)

    logger.info("[MONITORING] Metrics routes registered (/metrics, /api/monitoring)")
