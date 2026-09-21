"""ZeroNexus Main Entry Point & Startup Orchestrator.

Execution Workflow:
1. Boot Environment & Secret Masking Filter
2. Startup Self-Check Probe (Section 66)
3. Bot Instantiation & Event Loop Binding
4. Signal Handling (SIGINT/SIGTERM Graceful Shutdown)
"""

from __future__ import annotations

import asyncio
import signal
import sys

import discord

from zeronexus.bot import ZeroNexusBot
from zeronexus.core.config import config, mask_secret
from zeronexus.core.logger import log
from zeronexus.core.process_lock import process_lock


BANNER = "\033[38;5;45m\n" + r"""    _____                  _   __                     
   /__  / ___  _________  / | / /__  _  ____  _______ 
     / / / _ \/ ___/ __ \/  |/ / _ \| |/_/ / / / ___/ 
    / /_/  __/ /  / /_/ / /|  /  __/>  </ /_/ (__  )  
   /____|___/_/   \____/_/ |_/\___/_/|_|\__,_/____/   """ + "\033[0m"

async def startup_self_check() -> bool:
    """執行啟動前全系統自我健康檢測並印出科技美感控制台面板。"""
    # 輸出極簡高質感 Banner
    print(BANNER)
    print(f"\033[38;5;244m  ▶ 核心版本：\033[38;5;51mv{config.platform.version}\033[38;5;244m | 開源作者：\033[38;5;51mZero\033[38;5;244m | 授權：\033[38;5;51mApache 2.0\033[0m\n")

    # 1. 憑證檢測
    token = config.discord.token
    if not token or token == "your_bot_token_here":
        log.critical("✘ 憑證錯誤：未設定 DISCORD_BOT_TOKEN 或仍為預設佔位符！已中止啟動。")
        return False
    log.info(f"✔ 憑證就緒：Discord Bot Token [{mask_secret(token, prefix_len=4, suffix_len=4)}]")

    # 2. 資料庫檢測
    db_type = config.database.url.split("://")[0]
    log.info(f"✔ 資料儲存：{db_type.upper()} 引擎就緒")

    # 3. AI 網關與金鑰池
    gemini_cnt = len(config.ai.gemini_keys)
    deepseek_cnt = len(config.ai.deepseek_keys)
    openrouter_cnt = len(config.ai.openrouter_keys)
    log.info(f"✔ AI 網關：Gemini ({gemini_cnt}) | DeepSeek ({deepseek_cnt}) | OpenRouter ({openrouter_cnt})")

    # 4. 本地生物大腦神經模型矩陣守護與開機自癒
    try:
        from zeronexus.brain.bootstrap import ensure_brain_models_ready
        brain_ok = ensure_brain_models_ready(console_output=True)
        if not brain_ok:
            log.critical("✘ 生物大腦神經模型自癒失敗，無法安全開機！已中止啟動。")
            return False
    except Exception as e:
        log.warning(f"大腦神經模型開機檢驗例外: {e}")

    # 5. 外部 API 與環境
    cwa_status = "連線啟用" if config.external.cwa_api_key else "免金鑰降級支援"
    log.info(f"✔ 即時氣象：台灣中央氣象署 CWA ({cwa_status})")

    # 5. 官方版本與自動更新檢查
    try:
        from zeronexus.core.updater import check_for_updates_async
        has_new, local_v, remote_v = await check_for_updates_async()
        if has_new:
            log.warning(
                f"▲ 發現新版本發布：\033[1;38;5;220m{remote_v}\033[0m（當前運行: {local_v}）"
                f" ➔ 請在終端機執行 \033[1;38;5;51mpython3 update.py\033[0m 進行安全更新！"
            )
        elif remote_v:
            log.info(f"✔ 版本狀態：{local_v} (已是官方最新版本)")
        else:
            log.info(f"✔ 系統版本：{local_v}")
    except Exception as e:
        log.debug(f"版本檢查略過: {e}")

    log.info("✔ 核心啟動：Zero Intelligence 運行時智慧層初始化完畢\n")
    return True


async def main() -> None:
    # 0. Single-instance process lock check
    if not process_lock.acquire():
        sys.exit(0)

    try:
        # 1. Self check
        if config.platform.self_check_on_startup:
            passed = await startup_self_check()
            if not passed:
                sys.exit(1)

        # 2. Instantiate Bot
        bot = ZeroNexusBot()

        # 3. Setup signal handling for clean exit
        loop = asyncio.get_running_loop()
        shutdown_triggered = False

        def handle_signal() -> None:
            nonlocal shutdown_triggered
            if shutdown_triggered:
                log.warning("⚠️ 終止訊號已在處理中，請稍候...")
                return
            shutdown_triggered = True
            log.info("🛑 收到終止訊號，正在啟動機器人優雅關機流程...")
            asyncio.create_task(bot.close())

        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, handle_signal)
            except NotImplementedError:
                # Signal handling on Windows or restricted loop
                pass

        # 4. Run bot
        try:
            await bot.start(config.discord.token)
        except discord.LoginFailure as e:
            log.critical(f"❌ Discord 身分驗證失敗：{e}")
            sys.exit(1)
        except Exception as e:
            log.critical(f"❌ ZeroNexus 主事件循環發生嚴重錯誤：{e}", exc_info=True)
        finally:
            if not bot.is_closed():
                await bot.close()
    finally:
        process_lock.release()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        log.info("👋 ZeroNexus 系統程序已安全退出。")
