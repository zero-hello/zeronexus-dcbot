"""ZeroNexus Statistics and Metrics Tracking Engine.

Records real-time operations, execution latencies, success/error rates,
resource consumption, and provider usage for /當前狀態 and diagnostics.
"""

from __future__ import annotations

import os
import platform
import time
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List

import psutil


@dataclass
class CommandMetric:
    total_calls: int = 0
    success_calls: int = 0
    failed_calls: int = 0
    total_latency_ms: float = 0.0

    @property
    def avg_latency_ms(self) -> float:
        return (self.total_latency_ms / self.total_calls) if self.total_calls > 0 else 0.0


@dataclass
class AIMetric:
    total_requests: int = 0
    successful_requests: int = 0
    failed_requests: int = 0
    fallback_count: int = 0
    total_latency_ms: float = 0.0
    tokens_consumed: int = 0


@dataclass
class ToolMetric:
    calls: int = 0
    successes: int = 0
    failures: int = 0
    total_latency_ms: float = 0.0
    timeouts: int = 0


@dataclass
class AIPipelineMetrics:
    """Tracks latency breakdown across all 15 stages of the AI execution pipeline."""
    event_received_ms: float = 0.0
    defer_ms: float = 0.0
    quota_check_ms: float = 0.0
    context_build_ms: float = 0.0
    memory_fetch_ms: float = 0.0
    model_resolve_ms: float = 0.0
    provider_request_ms: float = 0.0
    tool_execution_ms: float = 0.0
    web_request_ms: float = 0.0
    cwa_request_ms: float = 0.0
    model_total_ms: float = 0.0
    response_parse_ms: float = 0.0
    components_build_ms: float = 0.0
    discord_send_ms: float = 0.0
    total_latency_ms: float = 0.0

    def to_dict(self) -> Dict[str, float]:
        return {
            "event_received_ms": round(self.event_received_ms, 2),
            "defer_ms": round(self.defer_ms, 2),
            "quota_check_ms": round(self.quota_check_ms, 2),
            "context_build_ms": round(self.context_build_ms, 2),
            "memory_fetch_ms": round(self.memory_fetch_ms, 2),
            "model_resolve_ms": round(self.model_resolve_ms, 2),
            "provider_request_ms": round(self.provider_request_ms, 2),
            "tool_execution_ms": round(self.tool_execution_ms, 2),
            "web_request_ms": round(self.web_request_ms, 2),
            "cwa_request_ms": round(self.cwa_request_ms, 2),
            "model_total_ms": round(self.model_total_ms, 2),
            "response_parse_ms": round(self.response_parse_ms, 2),
            "components_build_ms": round(self.components_build_ms, 2),
            "discord_send_ms": round(self.discord_send_ms, 2),
            "total_latency_ms": round(self.total_latency_ms, 2),
        }


class StatsTracker:
    """Central metrics collector."""

    def __init__(self) -> None:
        self.start_time: float = time.time()
        self.commands: Dict[str, CommandMetric] = defaultdict(CommandMetric)
        self.ai_providers: Dict[str, AIMetric] = defaultdict(AIMetric)
        self.ai_tools: Dict[str, ToolMetric] = defaultdict(ToolMetric)
        self.command_calls_total: int = 0
        self.command_success_total: int = 0
        self.command_failure_total: int = 0
        self.ai_interactions_total: int = 0
        self.ai_interactions_success: int = 0
        self.ai_interactions_failure: int = 0
        self.ai_interaction_latency_total_ms: float = 0.0
        self.ai_fallback_total: int = 0
        self.image_generations_total: int = 0
        self.tool_invocations_total: int = 0
        self._recorded_ai_interaction_ids: set[str] = set()
        self.module_calls: Dict[str, int] = defaultdict(int)
        self.external_api_calls: Dict[str, int] = defaultdict(int)
        self.total_errors: int = 0
        self.last_errors: List[Dict[str, Any]] = []
        self.recent_ai_pipelines: List[AIPipelineMetrics] = []

    def record_ai_pipeline(self, metrics: AIPipelineMetrics) -> None:
        """Stores recent AI pipeline latencies (bounded to last 500 records)."""
        self.recent_ai_pipelines.append(metrics)
        if len(self.recent_ai_pipelines) > 500:
            self.recent_ai_pipelines.pop(0)

    def get_ai_latency_percentiles(self) -> Dict[str, Dict[str, float]]:
        """Calculates P50, P95, and P99 latency distributions across key pipeline stages."""
        if not self.recent_ai_pipelines:
            return {}

        fields = [
            "total_latency_ms",
            "provider_request_ms",
            "context_build_ms",
            "model_resolve_ms",
            "quota_check_ms",
            "discord_send_ms",
        ]

        def _percentile(data: List[float], p: float) -> float:
            if not data:
                return 0.0
            s = sorted(data)
            idx = min(int(len(s) * p), len(s) - 1)
            return round(s[idx], 2)

        res = {}
        for f in fields:
            vals = [getattr(m, f) for m in self.recent_ai_pipelines]
            res[f] = {
                "p50": _percentile(vals, 0.50),
                "p95": _percentile(vals, 0.95),
                "p99": _percentile(vals, 0.99),
                "avg": round(sum(vals) / len(vals), 2) if vals else 0.0,
            }
        return res

    def record_command(self, command_name: str, latency_ms: float, success: bool = True) -> None:
        m = self.commands[command_name]
        m.total_calls += 1
        if success:
            m.success_calls += 1
        else:
            m.failed_calls += 1
        m.total_latency_ms += latency_ms
        self.command_calls_total += 1
        if success:
            self.command_success_total += 1
        else:
            self.command_failure_total += 1

    def record_ai_interaction(self, interaction_id: Any, latency_ms: float, success: bool, fallback_count: int = 0) -> bool:
        """Record one user-facing AI turn once, independent of provider retries/failovers."""
        key = str(interaction_id) if interaction_id is not None else ""
        if key and key in self._recorded_ai_interaction_ids:
            return False
        if key:
            self._recorded_ai_interaction_ids.add(key)
            if len(self._recorded_ai_interaction_ids) > 10_000:
                self._recorded_ai_interaction_ids = set(list(self._recorded_ai_interaction_ids)[-5_000:])
        self.ai_interactions_total += 1
        self.ai_interactions_success += int(success)
        self.ai_interactions_failure += int(not success)
        self.ai_interaction_latency_total_ms += max(0.0, float(latency_ms))
        self.ai_fallback_total += max(0, int(fallback_count))
        return True

    def record_ai_request(
        self,
        provider: str,
        latency_ms: float,
        success: bool = True,
        tokens: int = 0,
        is_fallback: bool = False,
    ) -> None:
        p = self.ai_providers[provider]
        p.total_requests += 1
        if success:
            p.successful_requests += 1
        else:
            p.failed_requests += 1
        if is_fallback:
            p.fallback_count += 1
        p.total_latency_ms += latency_ms
        p.tokens_consumed += tokens

    def record_tool_execution(self, tool_name: str, latency_ms: float, success: bool, timed_out: bool = False) -> None:
        metric = self.ai_tools[tool_name]
        metric.calls += 1
        metric.successes += int(success)
        metric.failures += int(not success)
        metric.timeouts += int(timed_out)
        metric.total_latency_ms += max(0.0, latency_ms)
        self.tool_invocations_total += 1

    def get_tool_execution_summary(self, limit: int = 100) -> List[Dict[str, Any]]:
        ranked = sorted(self.ai_tools.items(), key=lambda item: item[1].calls, reverse=True)
        return [
            {
                "tool": name,
                "calls": metric.calls,
                "successes": metric.successes,
                "failures": metric.failures,
                "timeouts": metric.timeouts,
                "success_rate_pct": round(metric.successes / metric.calls * 100, 2) if metric.calls else 0.0,
                "avg_latency_ms": round(metric.total_latency_ms / metric.calls, 2) if metric.calls else 0.0,
            }
            for name, metric in ranked[:max(1, min(int(limit), 200))]
        ]

    def record_module_call(self, module_name: str) -> None:
        self.module_calls[module_name] += 1

    def record_api_call(self, api_name: str) -> None:
        self.external_api_calls[api_name] += 1

    def increment(self, metric_name: str, count: int = 1) -> None:
        """動態遞增統計指標。"""
        if metric_name == "images_generated":
            self.image_generations_total += count
            self.external_api_calls["image_gen"] += count
        elif metric_name == "tool_calls_count":
            self.external_api_calls["tools"] += count
        elif metric_name == "total_replies":
            self.ai_interactions_total += count
            self.ai_interactions_success += count
        else:
            self.external_api_calls[metric_name] += count

    def record_reply(self, count: int = 1) -> None:
        """記錄一次對話回覆。"""
        self.increment("total_replies", count)

    def record_error(self, source: str, error_msg: str) -> None:
        self.total_errors += 1
        from zeronexus.security.sanitizer import redact_secrets
        cleaned_err = redact_secrets(error_msg)[:200]
        self.last_errors.append({
            "time": datetime.now(timezone.utc).isoformat(),
            "source": source,
            "error": cleaned_err,  # truncated for memory safety
        })
        if len(self.last_errors) > 50:
            self.last_errors.pop(0)

    @property
    def uptime_seconds(self) -> float:
        return time.time() - self.start_time

    @property
    def total_replies(self) -> int:
        return self.ai_interactions_total

    @property
    def images_generated(self) -> int:
        return self.image_generations_total

    @property
    def tool_calls_count(self) -> int:
        return self.tool_invocations_total

    def get(self, key: str, default: Any = 0) -> Any:
        """動態讀取系統計量指標，提供類似字典的彈性讀取介面。"""
        if key == "ai_requests_total":
            total_ai = sum(p.total_requests for p in self.ai_providers.values())
            return total_ai if total_ai > 0 else default
        elif key == "deep_thinking_count":
            return self.external_api_calls.get("deep_thinking", default)
        elif key == "ai_tool_calls_total":
            return self.tool_calls_count
        elif key in self.external_api_calls:
            return self.external_api_calls[key]
        elif hasattr(self, key):
            val = getattr(self, key)
            return val() if callable(val) else val
        return default

    @property
    def uptime_str(self) -> str:
        secs = int(self.uptime_seconds)
        days = secs // 86400
        hours = (secs % 86400) // 3600
        mins = (secs % 3600) // 60
        if days > 0:
            return f"{days}天{hours}小時"
        if hours > 0:
            return f"{hours}小時{mins}分"
        return f"{mins}分鐘"

    def format_uptime(self) -> str:
        seconds = int(self.uptime_seconds)
        days, remainder = divmod(seconds, 86400)
        hours, remainder = divmod(remainder, 3600)
        minutes, secs = divmod(remainder, 60)
        parts: List[str] = []
        if days > 0:
            parts.append(f"{days}d")
        if hours > 0 or days > 0:
            parts.append(f"{hours}h")
        if minutes > 0 or hours > 0 or days > 0:
            parts.append(f"{minutes}m")
        parts.append(f"{secs}s")
        return " ".join(parts)

    def get_system_resources(self) -> Dict[str, Any]:
        process = psutil.Process(os.getpid())
        mem_info = process.memory_info()
        vm = psutil.virtual_memory()
        cpu_pct = process.cpu_percent(interval=None)

        return {
            "python_version": platform.python_version(),
            "os": f"{platform.system()} {platform.release()}",
            "process_ram_mb": round(mem_info.rss / (1024 * 1024), 2),
            "system_ram_used_pct": round(vm.percent, 1),
            "system_ram_total_gb": round(vm.total / (1024 ** 3), 2),
            "cpu_percent": cpu_pct,
            "threads_count": process.num_threads(),
        }

    def summary(self) -> Dict[str, Any]:
        total_cmd_calls = sum(m.total_calls for m in self.commands.values())
        total_cmd_success = sum(m.success_calls for m in self.commands.values())
        total_cmd_failed = sum(m.failed_calls for m in self.commands.values())

        return {
            "uptime": self.format_uptime(),
            "uptime_seconds": round(self.uptime_seconds, 1),
            "total_commands_executed": total_cmd_calls,
            "commands_success": total_cmd_success,
            "commands_failed": total_cmd_failed,
            "total_errors_logged": self.total_errors,
            "system_resources": self.get_system_resources(),
            "ai_usage": {k: {
                "total": v.total_requests,
                "success": v.successful_requests,
                "failed": v.failed_requests,
                "fallbacks": v.fallback_count,
                "tokens": v.tokens_consumed,
                "avg_latency_ms": round((v.total_latency_ms / v.total_requests), 2) if v.total_requests > 0 else 0.0,
            } for k, v in self.ai_providers.items()},
            "ai_tools": self.get_tool_execution_summary(limit=100),
            "usage": {
                "commands_total": self.command_calls_total,
                "commands_success": self.command_success_total,
                "commands_failed": self.command_failure_total,
                "ai_interactions_total": self.ai_interactions_total,
                "ai_interactions_success": self.ai_interactions_success,
                "ai_interactions_failed": self.ai_interactions_failure,
                "ai_fallback_total": self.ai_fallback_total,
                "tool_invocations_total": self.tool_invocations_total,
                "images_generated": self.external_api_calls.get("image_gen", 0),
            },
            "module_calls": dict(self.module_calls),
            "external_apis": dict(self.external_api_calls),
        }


# Singleton stats instance
stats = StatsTracker()
