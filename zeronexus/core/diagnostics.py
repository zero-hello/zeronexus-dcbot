"""ZeroNexus System Diagnostics & Self-Check Engine.

Evaluates connectivity, latency, and status across:
- Database (SQLAlchemy Async connection ping)
- Cache (Dual-Mode In-Memory / Redis test write & read)
- AI Providers (Gemini, DeepSeek, OpenRouter Key Pool health)
- AudioNode Audio Node (Wavelink WebSocket status)
- Taiwan CWA Weather API (reachability probe)
- Minecraft Protocol Engine (socket probe)
- Module Manager & Lifecycle Health
"""

from __future__ import annotations

import time
from typing import Any, Dict

from zeronexus.core.cache import cache
from zeronexus.core.database import db
from zeronexus.core.logger import log


class DiagnosticStatus:
    HEALTHY = "🟢"
    DEGRADED = "🟡"
    OFFLINE = "🔴"
    DISABLED = "⚪"


class DiagnosticsManager:
    """Orchestrates system self-checks and live diagnostic scans."""

    def __init__(self) -> None:
        self._last_scan: Dict[str, Any] = {}

    async def run_full_diagnostics(self, bot_instance: Any = None) -> Dict[str, Any]:
        """Runs concurrent health probes across all ZeroNexus dependencies."""
        log.info("Initiating full system diagnostic scan...")

        results: Dict[str, Any] = {
            "timestamp": time.time(),
            "subsystems": {},
            "all_healthy": True,
        }

        # 1. Database check
        db_res = await db.health_check()
        results["subsystems"]["database"] = {
            "name": "資料庫 (Database)",
            "icon": DiagnosticStatus.HEALTHY if db_res.get("healthy") else DiagnosticStatus.OFFLINE,
            "latency_ms": db_res.get("latency_ms", -1),
            "details": db_res.get("driver", "Unknown"),
            "error": db_res.get("error"),
        }
        if not db_res.get("healthy"):
            results["all_healthy"] = False

        # 2. Cache check
        cache_res = await cache.health_check()
        results["subsystems"]["cache"] = {
            "name": "快取系統 (Cache)",
            "icon": DiagnosticStatus.HEALTHY if cache_res.get("healthy") else DiagnosticStatus.OFFLINE,
            "latency_ms": cache_res.get("latency_ms", -1),
            "details": cache_res.get("mode", "In-Memory"),
            "error": cache_res.get("error"),
        }
        if not cache_res.get("healthy"):
            results["all_healthy"] = False

        # 3. Discord Gateway check
        if bot_instance and hasattr(bot_instance, "latency"):
            gw_latency = round(bot_instance.latency * 1000, 2)
            gw_healthy = bot_instance.is_ready()
            results["subsystems"]["discord_gateway"] = {
                "name": "Discord Gateway",
                "icon": DiagnosticStatus.HEALTHY if gw_healthy else DiagnosticStatus.DEGRADED,
                "latency_ms": gw_latency,
                "details": f"Guilds: {len(bot_instance.guilds)}",
            }
        else:
            results["subsystems"]["discord_gateway"] = {
                "name": "Discord Gateway",
                "icon": DiagnosticStatus.DEGRADED,
                "latency_ms": -1,
                "details": "Bot not fully attached or offline",
            }

        # 4. AI Gateway check
        try:
            from zeronexus.ai_gateway.gateway import ai_gateway
            ai_res = await ai_gateway.health_check()
            results["subsystems"]["ai_gateway"] = ai_res
        except Exception as e:
            results["subsystems"]["ai_gateway"] = {
                "name": "AI 閘道 (AI Gateway)",
                "icon": DiagnosticStatus.DEGRADED,
                "details": str(e),
            }

        # 5. CWA Weather API check
        try:
            from zeronexus.engines.cwa_client import cwa_client
            cwa_res = await cwa_client.health_check()
            results["subsystems"]["cwa_weather"] = cwa_res
        except Exception as e:
            results["subsystems"]["cwa_weather"] = {
                "name": "中央氣象署 API (CWA)",
                "icon": DiagnosticStatus.DEGRADED,
                "details": str(e),
            }

        # 6. Scheduler check
        try:
            from zeronexus.core.scheduler import scheduler
            sched_res = scheduler.health_check()
            sched_healthy = sched_res.get("status") in ("GREEN", "YELLOW")
            results["subsystems"]["scheduler"] = {
                "name": "排程器 (Scheduler)",
                "icon": DiagnosticStatus.HEALTHY if sched_res.get("status") == "GREEN" else (DiagnosticStatus.DEGRADED if sched_res.get("status") == "YELLOW" else DiagnosticStatus.OFFLINE),
                "latency_ms": -1,
                "details": f"任務數: {sched_res.get('jobs_count', 0)} | 執行中: {sched_res.get('active_tasks_count', 0)}",
            }
            if not sched_healthy:
                results["all_healthy"] = False
        except Exception as e:
            results["subsystems"]["scheduler"] = {
                "name": "排程器 (Scheduler)",
                "icon": DiagnosticStatus.DEGRADED,
                "details": str(e),
            }

        # 7. Module Manager check
        try:
            from zeronexus.modules.manager import module_manager
            mod_res = module_manager.get_health_summary()
            results["modules"] = mod_res
        except Exception:
            results["modules"] = {}

        # Global secret redaction pass over all diagnostic fields
        from zeronexus.security.sanitizer import redact_secrets

        def _sanitize_dict(obj: Any) -> Any:
            if isinstance(obj, str):
                return redact_secrets(obj)
            if isinstance(obj, dict):
                return {k: _sanitize_dict(v) for k, v in obj.items()}
            if isinstance(obj, list):
                return [_sanitize_dict(item) for item in obj]
            return obj

        results = _sanitize_dict(results)
        self._last_scan = results
        return results


    def get_cached_diagnostics(self) -> Dict[str, Any]:
        return self._last_scan


# Singleton diagnostics instance
diagnostics = DiagnosticsManager()
