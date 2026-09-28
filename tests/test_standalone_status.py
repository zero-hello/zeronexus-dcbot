from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from zeronexus.modules.standalone.cog import StandaloneCog


@pytest.mark.asyncio
async def test_status_card_is_useful_and_never_exposes_ai_key_pool(monkeypatch) -> None:
    monkeypatch.setattr(
        "zeronexus.modules.standalone.cog.stats.get_system_resources",
        lambda: {
            "python_version": "3.11.9",
            "os": "Linux",
            "threads_count": 8,
            "process_ram_mb": 256,
            "system_ram_used_pct": 30.0,
            "system_ram_total_gb": 8.0,
            "cpu_percent": 12.0,
        },
    )
    monkeypatch.setattr("zeronexus.modules.standalone.cog.stats.format_uptime", lambda: "2d 1h 3m")
    monkeypatch.setattr("zeronexus.modules.standalone.cog.stats.summary", lambda: {
        "ai_usage": {"gemini": {"total": 4, "success": 4, "failed": 0, "fallbacks": 1, "tokens": 1234, "avg_latency_ms": 345.0}},
        "usage": {"tool_invocations_total": 2},
    })
    monkeypatch.setattr("zeronexus.modules.standalone.cog.stats.ai_interactions_total", 4)
    monkeypatch.setattr("zeronexus.modules.standalone.cog.stats.ai_interactions_success", 3)
    monkeypatch.setattr("zeronexus.modules.standalone.cog.stats.ai_interactions_failure", 1)
    monkeypatch.setattr("zeronexus.modules.standalone.cog.stats.ai_fallback_total", 1)
    monkeypatch.setattr("zeronexus.modules.standalone.cog.stats.get_ai_latency_percentiles", lambda: {"total_latency_ms": {"p95": 900.0}})
    monkeypatch.setattr("zeronexus.modules.standalone.cog.stats.ai_tools", {})
    monkeypatch.setattr("zeronexus.modules.standalone.cog.cache.stats", AsyncMock(return_value={"mode": "In-Memory", "hit_rate_pct": 80.0, "keys_count": 20, "max_items": 100}))
    monkeypatch.setattr("zeronexus.modules.standalone.cog.cache.health_check", AsyncMock(return_value={"healthy": True}))
    monkeypatch.setattr("zeronexus.modules.standalone.cog.db.health_check", AsyncMock(return_value={"healthy": True, "driver": "sqlite", "latency_ms": 4.2}))
    monkeypatch.setattr("zeronexus.modules.standalone.cog.module_manager.get_health_summary", lambda: {
        "ai": {"display_name": "AI 模組", "state": "RUNNING"},
        "music": {"display_name": "音樂模組", "state": "DEGRADED"},
    })
    monkeypatch.setattr("zeronexus.modules.standalone.cog.module_manager.command_registry.count", lambda: 263)
    monkeypatch.setattr("zeronexus.ai_gateway.model_registry.model_registry.list_active_models", lambda: [MagicMock(), MagicMock()])

    bot = MagicMock()
    bot.guilds = [MagicMock() for _ in range(3)]
    bot.users = [MagicMock() for _ in range(20)]
    bot.latency = 0.04
    bot.is_ready.return_value = True

    card = await StandaloneCog.generate_status_card(bot)
    content = "\n".join([card.title, card.description or "", *(f"{s.name}\n{s.value}" for s in card.sections)])

    assert "目前未就緒" not in content
    assert "伺服器" in content
    assert "DB" in content and "Cache" in content
    assert "✅ 成功 `3`" in content
    assert "❌ 失敗 `1`" in content
    assert "Token" in content
    assert "Function Calls `2`" in content
    assert "金鑰池" not in content
    assert "支金鑰" not in content
    assert "AIza" not in content and "sk-or" not in content
