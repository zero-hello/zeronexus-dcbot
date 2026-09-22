"""ZeroNexus 大腦自主心跳守護程序 (Brain Heartbeat System)

模擬人類大腦自發性生物神經節律：
1. 定期推進體內恆定動機 (Homeostatic State) 之自然代謝（飢餓/好奇/精力累積）。
2. 在背景靜息時段驅動預設模式網路 (DMN) 之自主心智漫遊、記憶修剪與主動發話衝動。
3. 採用 Zero Failure 防護，確保心跳協程在任何不可預期異常下皆能平穩推進。
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Optional

log = logging.getLogger("ZeroNexus.Brain.Heartbeat")


class BrainHeartbeatDaemon:
    """大腦自主心跳守護程序，常駐背景以固定週期推進認知代謝與心智漫遊。"""

    def __init__(self, cortex: Any, tick_interval: float = 30.0) -> None:
        self.cortex = cortex
        self.tick_interval = max(5.0, tick_interval)
        self._task: Optional[asyncio.Task] = None
        self._is_running: bool = False
        self._last_tick_ts: float = time.time()
        self._tick_count: int = 0

    @property
    def is_running(self) -> bool:
        """檢查大腦心跳守護程序是否活躍運行中。"""
        return self._is_running and self._task is not None and not self._task.done()

    def start(self) -> Optional[asyncio.Task]:
        """啟動非同步大腦心跳循環。若已運行則直接返回既有任務。"""
        if self.is_running:
            return self._task

        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop and loop.is_running():
            self._is_running = True
            self._last_tick_ts = time.time()
            self._task = loop.create_task(self._run_loop(), name="BrainHeartbeatLoop")
            log.info(f"💓 ZeroNexus 大腦自主心跳守護程序已啟動 (週期: {self.tick_interval}s)")
            return self._task
        else:
            log.debug("未檢測到運行的 asyncio 事件循環，心跳守護程序處於待命狀態。")
            return None

    def stop(self) -> None:
        """優雅停止大腦心跳守護程序。"""
        self._is_running = False
        if self._task and not self._task.done():
            self._task.cancel()
            log.info("🛑 ZeroNexus 大腦心跳守護程序已安全停止。")
        self._task = None

    async def trigger_single_tick(self) -> None:
        """手動推進單次心跳（供單元測試與即時排程呼叫）。"""
        await self._on_tick()

    async def _run_loop(self) -> None:
        """心跳主循環。"""
        while self._is_running:
            try:
                await asyncio.sleep(self.tick_interval)
                if not self._is_running:
                    break
                await self._on_tick()
            except asyncio.CancelledError:
                break
            except Exception as ex:
                log.error(f"大腦心跳循環發生未預期異常: {ex}", exc_info=True)
                await asyncio.sleep(2.0)  # 異常時退讓重試，防止 CPU 空轉

    async def _on_tick(self) -> None:
        """推進一次大腦心跳節拍。"""
        now = time.time()
        elapsed = max(0.1, now - self._last_tick_ts)
        self._last_tick_ts = now
        self._tick_count += 1

        if not self.cortex:
            return

        try:
            # 1. 推進體內恆定動機代謝
            if hasattr(self.cortex, "homeostasis") and self.cortex.homeostasis:
                self.cortex.homeostasis.tick_decay(elapsed)

            # 2. 驅動預設模式網路 (DMN) 自主心智漫遊
            if hasattr(self.cortex, "dmn") and self.cortex.dmn:
                await self.cortex.dmn.spontaneous_mind_wandering()

            if self._tick_count % 20 == 0:
                h = getattr(self.cortex, "homeostasis", None)
                if h:
                    log.debug(
                        f"💓 [大腦心跳節律 Tick #{self._tick_count}] "
                        f"社交渴求: {h.social_hunger:.2f} | 好奇心: {h.curiosity_drive:.2f} | 精力: {h.energy_reserve:.2f}"
                    )
        except Exception as e:
            log.warning(f"大腦心跳單次 Tick 處理過程發生錯誤: {e}")

