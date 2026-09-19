"""ZeroNexus 開發者與系統維護專用回文指令模組 (Developer Cog).

提供系統開發者專用的 30 個強大診斷、熱重載、效能監控與管理指令，加上專屬 help 幫助指令。
所有指令前綴支援 `!zn <command>`，具備嚴格的開發者權限校驗，杜絕非授權存取。
"""

from __future__ import annotations

import asyncio
import gc
import io
import logging
import os
import platform
import psutil
import re
import sys
import threading
import time
from typing import Any, Dict, List, Optional, Tuple

import discord
from discord.ext import commands

from zeronexus.core.cache import cache
from zeronexus.core.config import config
from zeronexus.core.database import db
from zeronexus.core.logger import log
from zeronexus.core.scheduler import scheduler
from zeronexus.core.stats import stats
from zeronexus.modules.base import BaseModule, CommandMetadata, ModuleState
from zeronexus.security.permissions import PermissionEngine, ZNPermissionLevel
from zeronexus.security.sanitizer import redact_secrets
from zeronexus.ui.card import ZNCard
from zeronexus.ui.theme import ZNColor, ZNStatusPill

logger = logging.getLogger("zeronexus.modules.developer")


class DeveloperModule(BaseModule):
    """開發者與維護專用領域模組生命週期管理類別。"""

    def __init__(self) -> None:
        super().__init__(
            name="developer",
            display_name="🛠️ 開發者專用模組 (developer)",
            description="提供 ZeroNexus 核心開發者之後台除錯、熱重載、系統監控與即時診斷指令集",
        )
        # 註冊指令中繼資料
        commands_info = [
            ("reload", "熱重載指定模組或全部擴充套件"),
            ("restart", "安全重啟 ZeroNexus 核心行程"),
            ("shutdown", "優雅關閉資源並終止程序"),
            ("sync", "手動同步斜線指令樹至 Discord 閘道"),
            ("eval", "非同步執行 Python 表達式或程式碼塊"),
            ("sysinfo", "檢視主機 CPU、記憶體與磁碟硬體環境"),
            ("proc", "查詢 Bot 行程 PID、Uptime 與資源佔用"),
            ("threads", "列出活躍執行緒與非同步 Tasks 呼叫堆疊"),
            ("env", "檢查系統環境變數配置狀態 (自動脫敏)"),
            ("gc", "強制執行記憶體垃圾回收並統計回收物件"),
            ("dbstat", "檢視資料庫連線池狀態與查詢延遲"),
            ("dbtables", "查詢資料表清單與記錄總筆數"),
            ("sql", "安全唯讀執行 SQL 查詢語句 (限 20 筆)"),
            ("cachestat", "檢視記憶體與 Redis 快取命中率與容量"),
            ("cacheflush", "清空或依模式清除快取項目"),
            ("aimodels", "列出 AI Gateway 當前可用模型與預設等級"),
            ("aistat", "查看 AI 請求成功率、Token 消耗與延遲"),
            ("aicontext", "檢查指定使用者在當前頻道的上下文記憶"),
            ("cognetwork", "診斷認知網絡概念節點與活躍能量狀態"),
            ("causalaudit", "現場執行因果邏輯審查器與矛盾檢測"),
            ("ping", "多端點延遲檢測 (Gateway/REST/Database)"),
            ("guilds", "列出 Bot 所在的所有伺服器詳細清單"),
            ("channelinfo", "查詢指定頻道的底層技術屬性與權限"),
            ("userinfo", "查詢使用者的 Discord 屬性與資料庫設定"),
            ("auditlog", "即時拉取當前伺服器最新審核日誌記錄"),
            ("jobs", "列出所有背景排程任務與下次觸發時間"),
            ("jobrun", "手動立即觸發執行指定背景排程工作"),
            ("logs", "即時讀取系統日誌檔案末尾行數 (自動脫敏)"),
            ("loglevel", "動態查看或切換全域日誌輸出級別"),
            ("ratelimit", "檢查速率限制器追蹤窗口與黑名單狀態"),
            ("help", "展示所有 30 個開發者專用指令的用法指南"),
        ]
        for cname, cdesc in commands_info:
            self.registered_commands.append(
                CommandMetadata(
                    name=cname,
                    full_name=f"!zn {cname}",
                    description=cdesc,
                    group_name="developer",
                    module_name="developer",
                    permission_level=ZNPermissionLevel.DEVELOPER,
                    guild_only=False,
                )
            )

    async def initialize(self, bot: Any) -> None:
        self.set_state(ModuleState.READY)
        self.loaded_at = time.time()

    async def shutdown(self) -> None:
        self.set_state(ModuleState.DISABLED)


class DeveloperCog(commands.Cog, name="開發者專用指令集"):
    """包含 30 個專業開發者指令 + 1 個 help 指令的核心 Cog。"""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self._start_time = time.time()
        if self.bot.get_command("help"):
            self.bot.remove_command("help")

    async def cog_check(self, ctx: commands.Context) -> bool:
        """全域指令保護：嚴格僅允許授權開發者或應用程式擁有者執行。"""
        is_dev = PermissionEngine.is_developer(ctx.author.id)
        if not is_dev:
            try:
                is_dev = await self.bot.is_owner(ctx.author)
            except Exception:
                is_dev = False

        if not is_dev:
            card = ZNCard(
                title="🚫 【存取受限】缺乏開發者權限",
                description=(
                    f"抱歉，`!zn` 回文指令集專為 ZeroNexus 核心開發者與維護人員設計。\n"
                    f"您的 Discord ID (`{ctx.author.id}`) 未在開發者授權白名單內，無法執行此指令。"
                ),
                status_pill=ZNStatusPill.ERROR,
                color=ZNColor.ERROR,
            )
            await ctx.send(embed=card.to_embed())
            return False
        return True

    # =========================================================================
    # 一、核心運行與熱重載 (Core & Hot Reload - 5 個指令)
    # =========================================================================

    @commands.command(name="reload", aliases=["rel"])
    async def cmd_reload(self, ctx: commands.Context, module_name: Optional[str] = None) -> None:
        """熱重載指定模組 Cog 或全部擴充套件，免重啟 Bot 立即更新代碼。"""
        t0 = time.perf_counter()
        from zeronexus.bot import EXTENSION_MODULES

        if module_name:
            target = module_name.strip()
            # 支援簡稱對齊
            full_ext = target if target.startswith("zeronexus.modules.") else f"zeronexus.modules.{target}.cog"
            try:
                await self.bot.reload_extension(full_ext)
                elapsed = (time.perf_counter() - t0) * 1000.0
                card = ZNCard(
                    title="🔄 模組熱重載完成",
                    description=f"成功重載模組：`{full_ext}`\n耗時：`{elapsed:.2f} ms`",
                    status_pill=ZNStatusPill.SUCCESS,
                    color=ZNColor.SUCCESS,
                )
                await ctx.send(embed=card.to_embed())
            except Exception as e:
                card = ZNCard(
                    title="❌ 模組熱重載失敗",
                    description=f"重載模組 `{full_ext}` 時發生錯誤：\n```py\n{redact_secrets(str(e))}\n```",
                    status_pill=ZNStatusPill.ERROR,
                    color=ZNColor.ERROR,
                )
                await ctx.send(embed=card.to_embed())
        else:
            # 重載全部模組
            successes: List[str] = []
            failures: List[str] = []
            for ext in EXTENSION_MODULES:
                try:
                    await self.bot.reload_extension(ext)
                    successes.append(ext.split(".")[-2])
                except Exception as e:
                    failures.append(f"{ext.split('.')[-2]} ({e})")

            elapsed = (time.perf_counter() - t0) * 1000.0
            desc = f"**成功重載 ({len(successes)})**：{', '.join(successes)}\n"
            if failures:
                desc += f"**失敗模組 ({len(failures)})**：\n" + "\n".join(f"- `{f}`" for f in failures) + "\n"
            desc += f"\n總耗時：`{elapsed:.2f} ms`"

            card = ZNCard(
                title="🔄 全體擴充模組熱重載結果",
                description=desc,
                status_pill=ZNStatusPill.SUCCESS if not failures else ZNStatusPill.WARNING,
                color=ZNColor.SUCCESS if not failures else ZNColor.WARNING,
            )
            await ctx.send(embed=card.to_embed())

    @commands.command(name="restart")
    async def cmd_restart(self, ctx: commands.Context) -> None:
        """安全關閉非同步任務、保存記憶體狀態並重新啟動 Bot 行程。"""
        card = ZNCard(
            title="🔄 正在重啟 ZeroNexus",
            description="正在中斷非同步連線、保存當前狀態並以新行程重啟...",
            status_pill=ZNStatusPill.INFO,
            color=ZNColor.INFO,
        )
        await ctx.send(embed=card.to_embed())
        log.info(f"開發者 {ctx.author} 觸發了遠端重啟指令。")
        try:
            await scheduler.stop()
            await db.close()
            await cache.close()
            await self.bot.close()
        finally:
            os.execv(sys.executable, [sys.executable] + sys.argv)

    @commands.command(name="shutdown")
    async def cmd_shutdown(self, ctx: commands.Context) -> None:
        """優雅關閉所有連線池、排程任務並退出 Bot 程序。"""
        card = ZNCard(
            title="🛑 正在安全關閉 ZeroNexus",
            description="正在優雅停止所有背景服務與排程工作，感謝您的維護！",
            status_pill=ZNStatusPill.WARNING,
            color=ZNColor.WARNING,
        )
        await ctx.send(embed=card.to_embed())
        log.warning(f"開發者 {ctx.author} 觸發了遠端關機指令。")
        await scheduler.stop()
        await db.close()
        await cache.close()
        await self.bot.close()

    @commands.command(name="sync")
    async def cmd_sync(self, ctx: commands.Context, scope: Optional[str] = None) -> None:
        """手動強制同步斜線指令樹至 Discord 閘道 (可選: guild / global)。"""
        t0 = time.perf_counter()
        async with ctx.typing():
            try:
                if scope == "guild" and ctx.guild:
                    self.bot.tree.copy_global_to(guild=ctx.guild)
                    synced = await self.bot.tree.sync(guild=ctx.guild)
                    scope_desc = f"當前伺服器 `{ctx.guild.name}` ({ctx.guild.id})"
                else:
                    synced = await self.bot.tree.sync()
                    scope_desc = "全域 (Global)"

                elapsed = (time.perf_counter() - t0) * 1000.0
                card = ZNCard(
                    title="📡 斜線指令樹同步完成",
                    description=f"同步範圍：**{scope_desc}**\n成功同步指令數量：`{len(synced)}` 個頂層命令\n同步耗時：`{elapsed:.2f} ms`",
                    status_pill=ZNStatusPill.SUCCESS,
                    color=ZNColor.SUCCESS,
                )
                await ctx.send(embed=card.to_embed())
            except Exception as e:
                card = ZNCard(
                    title="❌ 同步斜線指令失敗",
                    description=f"錯誤資訊：\n```py\n{redact_secrets(str(e))}\n```",
                    status_pill=ZNStatusPill.ERROR,
                    color=ZNColor.ERROR,
                )
                await ctx.send(embed=card.to_embed())

    @commands.command(name="eval", aliases=["ev", "py"])
    async def cmd_eval(self, ctx: commands.Context, *, code: str) -> None:
        """非同步即時執行任意 Python 表達式或腳本塊，內建環境變數注入。"""
        # 清理 code markdown
        clean_code = code.strip()
        if clean_code.startswith("```"):
            clean_code = re.sub(r"^```(?:py|python)?\n", "", clean_code)
            clean_code = re.sub(r"\n```$", "", clean_code)
        clean_code = clean_code.strip()

        env_globals: Dict[str, Any] = {
            "bot": self.bot,
            "ctx": ctx,
            "channel": ctx.channel,
            "author": ctx.author,
            "guild": ctx.guild,
            "message": ctx.message,
            "discord": discord,
            "commands": commands,
            "asyncio": asyncio,
            "db": db,
            "cache": cache,
            "config": config,
            "stats": stats,
            "scheduler": scheduler,
        }

        stdout = io.StringIO()
        t0 = time.perf_counter()

        # 封裝非同步執行函式
        wrapped_code = (
            "async def _eval_executor():\n"
            + "\n".join(f"    {line}" for line in clean_code.splitlines())
        )

        try:
            exec(wrapped_code, env_globals)
            func = env_globals["_eval_executor"]
            sys_stdout_orig = sys.stdout
            sys.stdout = stdout
            try:
                ret = await func()
            finally:
                sys.stdout = sys_stdout_orig

            elapsed = (time.perf_counter() - t0) * 1000.0
            captured = stdout.getvalue()

            result_str = ""
            if captured:
                result_str += f"**標準輸出 (Stdout)**:\n```py\n{captured[:1200]}\n```\n"
            if ret is not None:
                result_str += f"**回傳值 (Return)**:\n```py\n{repr(ret)[:600]}\n```\n"
            if not result_str:
                result_str = "程式碼已順利執行完成，無輸出內容。"

            result_str = redact_secrets(result_str)
            card = ZNCard(
                title="⚡ Python 執行成功",
                description=f"{result_str}\n⏱️ 執行耗時：`{elapsed:.2f} ms`",
                status_pill=ZNStatusPill.SUCCESS,
                color=ZNColor.SUCCESS,
            )
            await ctx.send(embed=card.to_embed())
        except Exception as e:
            elapsed = (time.perf_counter() - t0) * 1000.0
            card = ZNCard(
                title="❌ Python 執行發生例外",
                description=f"```py\n{redact_secrets(str(e))}\n```\n⏱️ 執行耗時：`{elapsed:.2f} ms`",
                status_pill=ZNStatusPill.ERROR,
                color=ZNColor.ERROR,
            )
            await ctx.send(embed=card.to_embed())

    # =========================================================================
    # 二、系統硬體與執行緒診斷 (System & Process Diagnostics - 5 個指令)
    # =========================================================================

    @commands.command(name="sysinfo", aliases=["sys"])
    async def cmd_sysinfo(self, ctx: commands.Context) -> None:
        """顯示主機詳細硬體環境 (CPU、記憶體、磁碟、作業系統核心與架構)。"""
        vm = psutil.virtual_memory()
        disk = psutil.disk_usage("/")
        cpu_pct = psutil.cpu_percent(interval=0.2)
        cpu_count = psutil.cpu_count(logical=True)
        cpu_phys = psutil.cpu_count(logical=False)

        card = ZNCard(
            title="🖥️ 系統主機硬體環境診斷",
            description="主機核心硬體資源與作業系統配置如下：",
            status_pill=ZNStatusPill.INFO,
            color=ZNColor.INFO,
        )
        card.add_section("作業系統", f"`{platform.system()} {platform.release()} ({platform.machine()})`", inline=True)
        card.add_section("Python 核心", f"`{platform.python_version()} ({platform.python_implementation()})`", inline=True)
        card.add_section("Discord.py", f"`v{discord.__version__}`", inline=True)
        card.add_section("中央處理器 (CPU)", f"核心數：`{cpu_phys}P / {cpu_count}L`\n即時使用率：`{cpu_pct}%`", inline=True)
        card.add_section("記憶體 (RAM)", f"已用：`{vm.used / (1024**3):.2f} GB` / `{vm.total / (1024**3):.2f} GB` (`{vm.percent}%`)\n可用：`{vm.available / (1024**3):.2f} GB`", inline=True)
        card.add_section("根目錄磁碟 (Disk)", f"已用：`{disk.used / (1024**3):.2f} GB` / `{disk.total / (1024**3):.2f} GB` (`{disk.percent}%`)\n可用：`{disk.free / (1024**3):.2f} GB`", inline=True)
        await ctx.send(embed=card.to_embed())

    @commands.command(name="proc")
    async def cmd_proc(self, ctx: commands.Context) -> None:
        """查詢 Bot 當前程序的 PID、Uptime、記憶體 RSS/VMS、FDs 與執行緒數。"""
        p = psutil.Process()
        mem = p.memory_info()
        uptime_sec = time.time() - self._start_time
        d = int(uptime_sec // 86400)
        h = int((uptime_sec % 86400) // 3600)
        m = int((uptime_sec % 3600) // 60)
        s = int(uptime_sec % 60)
        uptime_fmt = f"{d}天 {h}時 {m}分 {s}秒"

        try:
            num_fds = p.num_fds()
        except Exception:
            num_fds = "不支援"

        card = ZNCard(
            title="⚙️ Bot 執行程序即時指標",
            description="當前 Python 應用程式行程之即時資源佔用：",
            status_pill=ZNStatusPill.SUCCESS,
            color=ZNColor.PRIMARY,
        )
        card.add_section("行程識別碼 (PID)", f"`{p.pid}`", inline=True)
        card.add_section("持續運行時間 (Uptime)", f"`{uptime_fmt}`", inline=True)
        card.add_section("執行緒數量 (Threads)", f"`{p.num_threads()}`", inline=True)
        card.add_section("實體記憶體 (RSS)", f"`{mem.rss / (1024**2):.2f} MB`", inline=True)
        card.add_section("虛擬記憶體 (VMS)", f"`{mem.vms / (1024**2):.2f} MB`", inline=True)
        card.add_section("檔案描述子 (FDs)", f"`{num_fds}`", inline=True)
        await ctx.send(embed=card.to_embed())

    @commands.command(name="threads")
    async def cmd_threads(self, ctx: commands.Context) -> None:
        """列出活躍執行緒與非同步 Tasks 呼叫堆疊。"""
        threads = threading.enumerate()
        tasks = [t for t in asyncio.all_tasks() if not t.done()]

        desc = f"**系統執行緒總數**：`{len(threads)}` 條\n"
        for th in threads[:8]:
            desc += f"- `{th.name}` (ID: `{th.ident}`, Daemon: `{th.daemon}`)\n"
        if len(threads) > 8:
            desc += f"...及其他 `{len(threads) - 8}` 條執行緒\n"

        desc += f"\n**非同步 Tasks 總數**：`{len(tasks)}` 個正在運行\n"
        for t in tasks[:8]:
            desc += f"- Task `{t.get_name()}`\n"
        if len(tasks) > 8:
            desc += f"...及其他 `{len(tasks) - 8}` 個非同步任務"

        card = ZNCard(
            title="🧵 執行緒與非同步 Tasks 清單",
            description=desc,
            status_pill=ZNStatusPill.INFO,
            color=ZNColor.INFO,
        )
        await ctx.send(embed=card.to_embed())

    @commands.command(name="env")
    async def cmd_env(self, ctx: commands.Context, key: Optional[str] = None) -> None:
        """檢查環境變數設定狀態 (敏感金鑰自動加遮罩掩碼，保障安全)。"""
        if key:
            k = key.strip().upper()
            val = os.getenv(k)
            if val is None:
                content = f"環境變數 `{k}` 未設定 (None)。"
            else:
                masked = redact_secrets(val)
                content = f"環境變數 `{k}` = `{masked}`"
        else:
            important_keys = [
                "DISCORD_TOKEN", "GEMINI_API_KEY", "OPENROUTER_API_KEY",
                "DATABASE_URL", "REDIS_URL", "ENVIRONMENT", "LOG_LEVEL",
                "TZ", "CHANNELID", "SECRET_CHANNEL_ID"
            ]
            lines = []
            for k in important_keys:
                v = os.getenv(k)
                if v:
                    lines.append(f"✅ `{k}`: 已配置 (`{redact_secrets(v)[:15]}...`)")
                else:
                    lines.append(f"⚪ `{k}`: 未配置")
            content = "\n".join(lines)

        card = ZNCard(
            title="🔐 核心環境變數配置狀態",
            description=content,
            status_pill=ZNStatusPill.INFO,
            color=ZNColor.INFO,
        )
        await ctx.send(embed=card.to_embed())

    @commands.command(name="gc")
    async def cmd_gc(self, ctx: commands.Context) -> None:
        """手動強制觸發 Python 記憶體垃圾回收 (Garbage Collection) 並回報統計。"""
        t0 = time.perf_counter()
        counts_before = gc.get_count()
        collected = gc.collect()
        counts_after = gc.get_count()
        elapsed = (time.perf_counter() - t0) * 1000.0

        card = ZNCard(
            title="🧹 記憶體垃圾回收 (GC) 完成",
            description=(
                f"回收不可達物件數量：`{collected}` 個\n"
                f"回收前世代物件計數：`Gen0: {counts_before[0]}, Gen1: {counts_before[1]}, Gen2: {counts_before[2]}`\n"
                f"回收後世代物件計數：`Gen0: {counts_after[0]}, Gen1: {counts_after[1]}, Gen2: {counts_after[2]}`\n"
                f"回收耗時：`{elapsed:.2f} ms`"
            ),
            status_pill=ZNStatusPill.SUCCESS,
            color=ZNColor.SUCCESS,
        )
        await ctx.send(embed=card.to_embed())

    # =========================================================================
    # 三、資料庫與快取管理 (Database & Cache Ops - 5 個指令)
    # =========================================================================

    @commands.command(name="dbstat")
    async def cmd_dbstat(self, ctx: commands.Context) -> None:
        """檢視資料庫連線池狀態、大小、作用中連線與延遲。"""
        t0 = time.perf_counter()
        db_ok = False
        err_msg = ""
        try:
            from sqlalchemy import text
            async with db.session() as session:
                await session.execute(text("SELECT 1"))
            db_ok = True
        except Exception as e:
            err_msg = str(e)
        elapsed = (time.perf_counter() - t0) * 1000.0

        card = ZNCard(
            title="🗄️ 資料庫引擎連線狀態",
            description=(
                f"**連線位址**：`{redact_secrets(config.database.url)}`\n"
                f"**健康狀態**：`{'正常連通 ✅' if db_ok else '異常中斷 ❌'}`\n"
                f"**查詢延遲 (Ping)**：`{elapsed:.2f} ms`\n"
                f"{f'**錯誤詳情**：`{err_msg}`' if err_msg else ''}"
            ),
            status_pill=ZNStatusPill.SUCCESS if db_ok else ZNStatusPill.ERROR,
            color=ZNColor.SUCCESS if db_ok else ZNColor.ERROR,
        )
        await ctx.send(embed=card.to_embed())

    @commands.command(name="dbtables")
    async def cmd_dbtables(self, ctx: commands.Context) -> None:
        """列出資料庫中所有資料表名稱與各自的資料筆數統計。"""
        from sqlalchemy import text
        table_counts: List[str] = []

        try:
            async with db.session() as session:
                # 兼容 SQLite 與 PostgreSQL
                if "sqlite" in config.database.url:
                    res = await session.execute(text("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%';"))
                    tables = [row[0] for row in res.fetchall()]
                else:
                    res = await session.execute(text("SELECT table_name FROM information_schema.tables WHERE table_schema='public';"))
                    tables = [row[0] for row in res.fetchall()]

                for t in tables[:15]:
                    try:
                        c_res = await session.execute(text(f"SELECT COUNT(*) FROM \"{t}\";"))
                        cnt = c_res.scalar() or 0
                        table_counts.append(f"- 表格 `{t}`: **{cnt:,}** 筆記錄")
                    except Exception:
                        table_counts.append(f"- 表格 `{t}`: (統計失敗)")

            desc = "\n".join(table_counts) if table_counts else "資料庫中目前未發現任何表格。"
            card = ZNCard(
                title=f"📊 資料庫結構概覽 (共 {len(tables)} 張資料表)",
                description=desc,
                status_pill=ZNStatusPill.INFO,
                color=ZNColor.INFO,
            )
            await ctx.send(embed=card.to_embed())
        except Exception as e:
            card = ZNCard(
                title="❌ 查詢資料庫表格失敗",
                description=f"錯誤資訊：`{e}`",
                status_pill=ZNStatusPill.ERROR,
                color=ZNColor.ERROR,
            )
            await ctx.send(embed=card.to_embed())

    @commands.command(name="sql")
    async def cmd_sql(self, ctx: commands.Context, *, query: str) -> None:
        """安全唯讀執行 SQL 查詢 (自動限制 LIMIT 20，嚴格阻擋破壞性語法)。"""
        clean_sql = query.strip()
        forbidden = ["DROP", "DELETE", "UPDATE", "INSERT", "ALTER", "TRUNCATE", "RENAME", "GRANT", "REVOKE"]
        upper_sql = clean_sql.upper()
        if any(re.search(rf"\b{word}\b", upper_sql) for word in forbidden):
            card = ZNCard(
                title="🚫 SQL 安全策略攔截",
                description="`!zn sql` 指令僅允許唯讀查詢語法 (`SELECT` / `EXPLAIN`)，禁止任何寫入、修改或銷毀操作！",
                status_pill=ZNStatusPill.ERROR,
                color=ZNColor.ERROR,
            )
            await ctx.send(embed=card.to_embed())
            return

        if "LIMIT" not in upper_sql:
            clean_sql = clean_sql.rstrip(";") + " LIMIT 20;"

        t0 = time.perf_counter()
        from sqlalchemy import text
        try:
            async with db.session() as session:
                res = await session.execute(text(clean_sql))
                rows = res.fetchall()
                keys = res.keys()

            elapsed = (time.perf_counter() - t0) * 1000.0
            if not rows:
                desc = "查詢結果為空 (0 rows returned)。"
            else:
                table_lines = [f"| {' | '.join(keys)} |"]
                table_lines.append(f"|{'-' * (len(table_lines[0]) - 2)}|")
                for r in rows[:10]:
                    row_str = " | ".join(str(v)[:25] for v in r)
                    table_lines.append(f"| {row_str} |")
                desc = "```\n" + "\n".join(table_lines) + f"\n```\n*(顯示前 {len(rows)} 筆結果)*"

            card = ZNCard(
                title="🔍 SQL 唯讀查詢結果",
                description=f"{desc}\n⏱️ 執行耗時：`{elapsed:.2f} ms`",
                status_pill=ZNStatusPill.SUCCESS,
                color=ZNColor.SUCCESS,
            )
            await ctx.send(embed=card.to_embed())
        except Exception as e:
            card = ZNCard(
                title="❌ SQL 執行錯誤",
                description=f"```sql\n{redact_secrets(str(e))}\n```",
                status_pill=ZNStatusPill.ERROR,
                color=ZNColor.ERROR,
            )
            await ctx.send(embed=card.to_embed())

    @commands.command(name="cachestat")
    async def cmd_cachestat(self, ctx: commands.Context) -> None:
        """檢視記憶體快取與 Redis 快取命中率、鍵總數與狀態。"""
        stats_data = await cache.get_stats()
        card = ZNCard(
            title="⚡ 快取系統 (Cache) 即時統計",
            description=(
                f"**快取引擎**：`{stats_data.get('driver', 'Memory')}`\n"
                f"**追蹤總鍵數**：`{stats_data.get('keys_count', 0):,}`\n"
                f"**快取命中次數**：`{stats_data.get('hits', 0):,}`\n"
                f"**快取未命中數**：`{stats_data.get('misses', 0):,}`\n"
                f"**即時命中率**：`{stats_data.get('hit_ratio', 0.0):.2f}%`"
            ),
            status_pill=ZNStatusPill.INFO,
            color=ZNColor.INFO,
        )
        await ctx.send(embed=card.to_embed())

    @commands.command(name="cacheflush")
    async def cmd_cacheflush(self, ctx: commands.Context, pattern: Optional[str] = None) -> None:
        """清除符合指定模式或全部快取。"""
        t0 = time.perf_counter()
        if pattern:
            cleaned = await cache.delete_pattern(pattern.strip())
            desc = f"已清除符合模式 `{pattern}` 的快取鍵，共清空 `{cleaned}` 個項目。"
        else:
            await cache.clear()
            desc = "已清空快取系統中所有資料！"

        elapsed = (time.perf_counter() - t0) * 1000.0
        card = ZNCard(
            title="🧹 快取清理完成",
            description=f"{desc}\n耗時：`{elapsed:.2f} ms`",
            status_pill=ZNStatusPill.SUCCESS,
            color=ZNColor.SUCCESS,
        )
        await ctx.send(embed=card.to_embed())

    # =========================================================================
    # 四、AI 網關與認知架構診斷 (AI Gateway & Zero Intelligence - 5 個指令)
    # =========================================================================

    @commands.command(name="aimodels")
    async def cmd_aimodels(self, ctx: commands.Context) -> None:
        """列出 AI Gateway 當前載入的所有可用模型、優先序與狀態。"""
        from zeronexus.ai_gateway.model_registry import model_registry
        active_models = model_registry.list_available_models()
        default_model = model_registry.get_active_default_model()

        lines = [f"**當前預設模型**：`{default_model}`\n", "**可用模型登錄清單**："]
        for idx, m in enumerate(active_models[:12], 1):
            star = "⭐ (預設)" if m == default_model else ""
            lines.append(f"{idx}. `{m}` {star}")

        card = ZNCard(
            title="🧠 AI Gateway 模型登錄清單",
            description="\n".join(lines),
            status_pill=ZNStatusPill.SUCCESS,
            color=ZNColor.AI,
        )
        await ctx.send(embed=card.to_embed())

    @commands.command(name="aistat")
    async def cmd_aistat(self, ctx: commands.Context) -> None:
        """查看 AI 管道計量統計 (成功率、Token 消耗、延遲百分位數)。"""
        total_reqs = stats.get("ai_requests_total", 0)
        deep_counts = stats.get("deep_thinking_count", 0)
        tool_counts = stats.get("ai_tool_calls_total", 0)

        card = ZNCard(
            title="📈 AI 認知運算指標統計",
            description=(
                f"**累計呼叫次數**：`{total_reqs:,}` 次\n"
                f"**深度思考 (Deep Thinking) 啟動次數**：`{deep_counts:,}` 次\n"
                f"**自主工具調度 (Function Calling) 次數**：`{tool_counts:,}` 次\n"
                f"**深度思考自主元認知狀態**：`已就緒 (7大維度審查中)`"
            ),
            status_pill=ZNStatusPill.INFO,
            color=ZNColor.AI,
        )
        await ctx.send(embed=card.to_embed())

    @commands.command(name="aicontext")
    async def cmd_aicontext(self, ctx: commands.Context, user: Optional[discord.User] = None) -> None:
        """檢查指定使用者在當前頻道的短期與長期記憶上下文狀態。"""
        target_user = user or ctx.author
        from zeronexus.ai_gateway.context_builder import context_builder
        memories = await context_builder.get_interaction_memories(target_user, ctx.channel)

        card = ZNCard(
            title=f"👤 AI 上下文狀態：{target_user.display_name}",
            description=(
                f"**使用者 ID**：`{target_user.id}`\n"
                f"**對應頻道**：`{ctx.channel.name}` (`{ctx.channel.id}`)\n"
                f"**短期對話記憶條目**：`{len(memories)}` 筆對話\n"
                f"**記憶容量限制**：`400 輪` (滑動窗口自動淘汰)"
            ),
            status_pill=ZNStatusPill.INFO,
            color=ZNColor.AI,
        )
        await ctx.send(embed=card.to_embed())

    @commands.command(name="cognetwork")
    async def cmd_cognetwork(self, ctx: commands.Context) -> None:
        """診斷 Zero Intelligence 符號神經認知網絡 (概念節點、邊數、活躍能量)。"""
        from zeronexus.intelligence.cognitive_network import cognitive_network
        top_concepts = cognitive_network.get_activated_concepts(threshold=0.05)

        lines = [
            f"**概念節點總數**：`{len(cognitive_network.concepts)}` 個",
            f"**概念連通邊數**：`{len(cognitive_network.associations)}` 條",
            "\n**當前能量活躍 Top 概念**：",
        ]
        if top_concepts:
            for c, w in top_concepts[:8]:
                lines.append(f"- `{c}`：能量強度 `{w:.3f}`")
        else:
            lines.append("*(目前處於平靜低能耗狀態，無顯著活化概念)*")

        card = ZNCard(
            title="🕸️ 符號神經認知網絡狀態 (Cognitive Network)",
            description="\n".join(lines),
            status_pill=ZNStatusPill.SUCCESS,
            color=ZNColor.PRIMARY,
        )
        await ctx.send(embed=card.to_embed())

    @commands.command(name="causalaudit")
    async def cmd_causalaudit(self, ctx: commands.Context, *, prompt: str) -> None:
        """現場運行因果邏輯審查器 (CausalEngine)，展示輸入命題之推導與矛盾檢測。"""
        from zeronexus.intelligence.causal_engine import CausalEngine
        from zeronexus.intelligence.truth_spectrum import TruthLevel

        t0 = time.perf_counter()
        dag = CausalEngine()
        dag.add_node("premise", f"輸入命題: {prompt[:25]}", value=0.9, truth_level=TruthLevel.OBSERVED)
        dag.add_node("hypothesis", "核心因果推論假說", value=0.85, truth_level=TruthLevel.DERIVED)
        dag.add_node("validation", "客觀邏輯相容性檢驗", value=0.95, truth_level=TruthLevel.KNOWN)

        dag.add_edge("premise", "hypothesis", weight=0.85)
        dag.add_edge("hypothesis", "validation", weight=0.9)
        dag.propagate_forward()
        report = dag.audit_contradictions()
        elapsed = (time.perf_counter() - t0) * 1000.0

        card = ZNCard(
            title="⚖️ 因果邏輯審查報告 (Causal Audit)",
            description=(
                f"**輸入命題**：`{prompt[:60]}`\n"
                f"**推導節點數**：`{len(dag.nodes)}` 個\n"
                f"**因果關聯邊數**：`{len(dag.edges)}` 條\n"
                f"**自洽一致性評分**：`{report.coherence_score:.2f} / 1.00`\n"
                f"**邏輯衝突檢測**：`{'發現矛盾 ⚠️' if report.has_conflict else '邏輯自洽無矛盾 ✅'}`\n"
                f"**運算耗時**：`{elapsed:.2f} ms`"
            ),
            status_pill=ZNStatusPill.SUCCESS if not report.has_conflict else ZNStatusPill.WARNING,
            color=ZNColor.SUCCESS if not report.has_conflict else ZNColor.WARNING,
        )
        await ctx.send(embed=card.to_embed())

    # =========================================================================
    # 五、網路與 Discord 閘道監控 (Network & Gateway - 5 個指令)
    # =========================================================================

    @commands.command(name="ping")
    async def cmd_ping(self, ctx: commands.Context) -> None:
        """多端點延遲檢測 (Gateway WebSocket / REST API / 資料庫往返)。"""
        # 1. Gateway Ping
        gw_ms = self.bot.latency * 1000.0

        # 2. REST API Round-trip
        t0 = time.perf_counter()
        tmp_msg = await ctx.send("🏓 正在測量網路與資料庫延遲...")
        rest_ms = (time.perf_counter() - t0) * 1000.0

        # 3. DB Ping
        t_db = time.perf_counter()
        try:
            from sqlalchemy import text
            async with db.session() as session:
                await session.execute(text("SELECT 1;"))
            db_ms = (time.perf_counter() - t_db) * 1000.0
            db_str = f"`{db_ms:.1f} ms`"
        except Exception:
            db_str = "`連線超時`"

        card = ZNCard(
            title="🏓 端對端延遲檢測報告",
            description=(
                f"**Discord WebSocket 閘道心跳**：`{gw_ms:.1f} ms`\n"
                f"**Discord REST API HTTP 往返**：`{rest_ms:.1f} ms`\n"
                f"**內部資料庫 (Database) 查詢**：{db_str}\n\n"
                f"狀態評定：`{'優良 🟢' if gw_ms < 150 and rest_ms < 300 else '良好 🟡'}`"
            ),
            status_pill=ZNStatusPill.SUCCESS,
            color=ZNColor.SUCCESS,
        )
        await tmp_msg.edit(content=None, embed=card.to_embed())

    @commands.command(name="guilds")
    async def cmd_guilds(self, ctx: commands.Context, limit: int = 15) -> None:
        """列出 Bot 所在的所有伺服器詳細清單 (名稱、ID、成員總數)。"""
        all_guilds = sorted(self.bot.guilds, key=lambda g: g.member_count or 0, reverse=True)
        total_members = sum(g.member_count or 0 for g in all_guilds)

        lines = [f"**服務伺服器總數**：`{len(all_guilds)}` 個伺服器\n**涵蓋使用者總數**：`{total_members:,}` 名成員\n"]
        for idx, g in enumerate(all_guilds[:limit], 1):
            owner = f"<@{g.owner_id}>" if g.owner_id else "未知"
            lines.append(f"{idx}. **{g.name}** (`{g.id}`)\n   成員：`{g.member_count}` 人 | 擁有者：{owner}")

        if len(all_guilds) > limit:
            lines.append(f"\n*(及其他 {len(all_guilds) - limit} 個伺服器)*")

        card = ZNCard(
            title="🏰 伺服器部署分佈清單",
            description="\n".join(lines),
            status_pill=ZNStatusPill.INFO,
            color=ZNColor.INFO,
        )
        await ctx.send(embed=card.to_embed())

    @commands.command(name="channelinfo")
    async def cmd_channelinfo(self, ctx: commands.Context, channel: Optional[discord.TextChannel] = None) -> None:
        """查詢指定頻道的底層技術屬性與權限。"""
        ch = channel or ctx.channel
        slowmode = getattr(ch, "slowmode_delay", 0)
        nsfw = getattr(ch, "is_nsfw", lambda: False)()

        card = ZNCard(
            title=f"📺 頻道技術屬性：#{ch.name}",
            description=(
                f"**頻道識別碼 (ID)**：`{ch.id}`\n"
                f"**頻道類型**：`{ch.type}`\n"
                f"**所屬分組 (Category)**：`{ch.category.name if ch.category else '無'}`\n"
                f"**慢速限制 (Slowmode)**：`{slowmode} 秒`\n"
                f"**年齡限制 (NSFW)**：`{'是' if nsfw else '否'}`\n"
                f"**建立時間**：`{ch.created_at.strftime('%Y-%m-%d %H:%M:%S UTC')}`"
            ),
            status_pill=ZNStatusPill.INFO,
            color=ZNColor.INFO,
        )
        await ctx.send(embed=card.to_embed())

    @commands.command(name="userinfo")
    async def cmd_userinfo(self, ctx: commands.Context, user: Optional[discord.User] = None) -> None:
        """查詢使用者的全域 Discord 資訊與資料庫偏好設定。"""
        u = user or ctx.author
        created_days = (time.time() - u.created_at.timestamp()) // 86400

        member = ctx.guild.get_member(u.id) if ctx.guild else None
        joined_str = member.joined_at.strftime('%Y-%m-%d') if member and member.joined_at else "非本群成員"
        top_role = member.top_role.mention if member and member.top_role else "無"

        card = ZNCard(
            title=f"👤 使用者情報：{u.name}",
            description=(
                f"**使用者 ID**：`{u.id}`\n"
                f"**機器人標記**：`{'是 🤖' if u.bot else '真人用戶 👤'}`\n"
                f"**帳號建立日期**：`{u.created_at.strftime('%Y-%m-%d')}` (`{int(created_days)} 天前`)\n"
                f"**加入伺服器日期**：`{joined_str}`\n"
                f"**最高身分組**：{top_role}\n"
                f"**開發者權限**：`{'是 🌟' if PermissionEngine.is_developer(u.id) else '否'}`"
            ),
            status_pill=ZNStatusPill.INFO,
            color=ZNColor.PRIMARY,
        )
        if u.avatar:
            card.set_thumbnail(u.avatar.url)
        await ctx.send(embed=card.to_embed())

    @commands.command(name="auditlog")
    async def cmd_auditlog(self, ctx: commands.Context, limit: int = 8) -> None:
        """即時拉取當前伺服器最新的審核日誌 (Audit Log) 記錄。"""
        if not ctx.guild:
            await ctx.send("此指令僅能在 Discord 伺服器頻道中使用。")
            return

        async with ctx.typing():
            lines = []
            try:
                async for entry in ctx.guild.audit_logs(limit=min(limit, 15)):
                    user = entry.user.name if entry.user else "未知"
                    target = entry.target
                    t_str = getattr(target, "name", str(target))
                    lines.append(f"- `{entry.action.name}` | 執行者: `{user}` | 目標: `{t_str}`")
            except Exception as e:
                lines.append(f"無法讀取審核日誌：`{e}` (可能缺乏 VIEW_AUDIT_LOG 權限)")

        card = ZNCard(
            title=f"📜 最新伺服器審核日誌 (前 {len(lines)} 筆)",
            description="\n".join(lines) if lines else "無審核紀錄。",
            status_pill=ZNStatusPill.INFO,
            color=ZNColor.INFO,
        )
        await ctx.send(embed=card.to_embed())

    # =========================================================================
    # 六、排程、日誌與安全守門 (Scheduler, Logs & Guard - 5 個指令)
    # =========================================================================

    @commands.command(name="jobs")
    async def cmd_jobs(self, ctx: commands.Context) -> None:
        """列出核心排程器中的所有背景排程任務與觸發時間。"""
        jobs_list = scheduler.list_jobs()
        lines = [f"**已排程任務總數**：`{len(jobs_list)}` 個\n"]
        for j in jobs_list:
            t_type = "週期定時" if getattr(j, "interval_seconds", None) else "每日定時"
            lines.append(f"- **{j.job_id}** (`{t_type}`)\n  間隔：`{getattr(j, 'interval_seconds', '每日固定時間')}s` | 下次執行：`{getattr(j, 'next_run', '待排程')}`")

        card = ZNCard(
            title="⏰ 系統背景排程任務清單 (Scheduled Jobs)",
            description="\n".join(lines),
            status_pill=ZNStatusPill.INFO,
            color=ZNColor.INFO,
        )
        await ctx.send(embed=card.to_embed())

    @commands.command(name="jobrun")
    async def cmd_jobrun(self, ctx: commands.Context, job_id: str) -> None:
        """手動立即觸發執行指定的背景排程任務。"""
        jid = job_id.strip()
        t0 = time.perf_counter()
        try:
            ran = await scheduler.trigger_job_now(jid)
            elapsed = (time.perf_counter() - t0) * 1000.0
            if ran:
                card = ZNCard(
                    title="⚡ 排程工作手動觸發成功",
                    description=f"任務 `{jid}` 已於背景完成執行。\n耗時：`{elapsed:.2f} ms`",
                    status_pill=ZNStatusPill.SUCCESS,
                    color=ZNColor.SUCCESS,
                )
            else:
                card = ZNCard(
                    title="⚠️ 排程任務不存在",
                    description=f"找不到名為 `{jid}` 的註冊工作，請輸入 `!zn jobs` 檢查任務清單。",
                    status_pill=ZNStatusPill.WARNING,
                    color=ZNColor.WARNING,
                )
        except Exception as e:
            card = ZNCard(
                title="❌ 執行排程工作失敗",
                description=f"執行 `{jid}` 時遭遇錯誤：\n```py\n{e}\n```",
                status_pill=ZNStatusPill.ERROR,
                color=ZNColor.ERROR,
            )
        await ctx.send(embed=card.to_embed())

    @commands.command(name="logs")
    async def cmd_logs(self, ctx: commands.Context, lines: int = 20) -> None:
        """即時讀取系統日誌檔案末尾行數 (自動過濾敏感 Token)。"""
        log_paths = ["logs/zeronexus.log", "bot.log", "zeronexus.log"]
        target_path = None
        for p in log_paths:
            if os.path.exists(p):
                target_path = p
                break

        if not target_path:
            await ctx.send("未找到本機日誌檔案（日誌可能輸出至系統日誌串流）。")
            return

        try:
            with open(target_path, "r", encoding="utf-8", errors="replace") as f:
                all_lines = f.readlines()
            recent = all_lines[-min(lines, 40):]
            content = "".join(recent)
            content = redact_secrets(content)
            if len(content) > 1800:
                content = content[-1800:]

            card = ZNCard(
                title=f"📜 系統日誌記錄 (末尾 {len(recent)} 行)",
                description=f"```log\n{content}\n```",
                status_pill=ZNStatusPill.INFO,
                color=ZNColor.INFO,
            )
            await ctx.send(embed=card.to_embed())
        except Exception as e:
            await ctx.send(f"讀取日誌失敗：`{e}`")

    @commands.command(name="loglevel")
    async def cmd_loglevel(self, ctx: commands.Context, level: Optional[str] = None) -> None:
        """動態查看或切換全域日誌輸出級別 (DEBUG / INFO / WARNING / ERROR)。"""
        root_logger = logging.getLogger()
        if level:
            lvl_name = level.strip().upper()
            numeric_level = getattr(logging, lvl_name, None)
            if numeric_level is None or not isinstance(numeric_level, int):
                await ctx.send("無效的日誌層級，請使用 `DEBUG`, `INFO`, `WARNING`, `ERROR`。")
                return
            root_logger.setLevel(numeric_level)
            card = ZNCard(
                title="⚙️ 全域日誌級別已動態更新",
                description=f"系統日誌層級已即時切換至：**`{lvl_name}`**",
                status_pill=ZNStatusPill.SUCCESS,
                color=ZNColor.SUCCESS,
            )
        else:
            current_lvl = logging.getLevelName(root_logger.level)
            card = ZNCard(
                title="⚙️ 當前全域日誌級別",
                description=f"目前系統日誌輸出級別為：**`{current_lvl}`**",
                status_pill=ZNStatusPill.INFO,
                color=ZNColor.INFO,
            )
        await ctx.send(embed=card.to_embed())

    @commands.command(name="ratelimit")
    async def cmd_ratelimit(self, ctx: commands.Context) -> None:
        """檢查速率限制器追蹤窗口與黑名單狀態。"""
        from zeronexus.security.ratelimit import rate_limiter
        stats_rl = rate_limiter.get_stats()

        card = ZNCard(
            title="🛡️ 速率限制防護器 (Rate Limiter) 狀態",
            description=(
                f"**目前追蹤之窗口數**：`{stats_rl.get('active_windows', 0):,}` 個\n"
                f"**遭臨時封鎖實體數**：`{stats_rl.get('blocked_entities', 0):,}` 個\n"
                f"**累計攔截違規次數**：`{stats_rl.get('violations_total', 0):,}` 次\n"
                f"**防護機制**：`滑動窗口 (Sliding Window Counter)`"
            ),
            status_pill=ZNStatusPill.SUCCESS,
            color=ZNColor.SUCCESS,
        )
        await ctx.send(embed=card.to_embed())

    # =========================================================================
    # 七、專屬開發者幫助指令 (Developer Help - 1 個指令)
    # =========================================================================

    @commands.command(name="help", aliases=["commands", "h"])
    async def cmd_help(self, ctx: commands.Context, command_name: Optional[str] = None) -> None:
        """展示所有 30 個開發者專用指令的用法、語法、參數與分類說明。"""
        if command_name:
            cmd = self.bot.get_command(command_name.strip())
            if not cmd:
                card = ZNCard(
                    title="⚠️ 找不到指令",
                    description=f"在開發者指令庫中未找到名為 `{command_name}` 的指令。\n請輸入 `!zn help` 瀏覽完整指令清單！",
                    status_pill=ZNStatusPill.WARNING,
                    color=ZNColor.WARNING,
                )
                await ctx.send(embed=card.to_embed())
                return

            aliases_str = f"`{', '.join(cmd.aliases)}`" if cmd.aliases else "無"
            doc_str = cmd.help or "此指令暫無詳細說明。"
            card = ZNCard(
                title=f"📖 指令手冊：!zn {cmd.name}",
                description=(
                    f"**指令名稱**：`!zn {cmd.name}`\n"
                    f"**別名 (Aliases)**：{aliases_str}\n"
                    f"**功能簡介**：{doc_str}\n"
                    f"**使用權限**：`ZeroNexus 核心開發者 (Developer)`"
                ),
                status_pill=ZNStatusPill.INFO,
                color=ZNColor.PRIMARY,
            )
            await ctx.send(embed=card.to_embed())
            return

        # 完整 30 個指令清單分組
        groups: Dict[str, List[Tuple[str, str]]] = {
            "一、核心運行與熱重載 (5)": [
                ("reload [module]", "熱重載指定模組或全部擴充套件"),
                ("restart", "安全保存狀態並重啟 Bot 行程"),
                ("shutdown", "優雅關閉所有連線池與排程並終止程序"),
                ("sync [scope]", "強制同步斜線指令樹 (guild / global)"),
                ("eval <code>", "非同步執行 Python 表達式或程式碼塊"),
            ],
            "二、系統硬體與環境診斷 (5)": [
                ("sysinfo", "主機硬體環境 (CPU、記憶體、磁碟、OS)"),
                ("proc", "Bot 行程 PID、Uptime、RSS/VMS 佔用"),
                ("threads", "列出活躍 Python 執行緒與非同步 Tasks"),
                ("env [key]", "檢查環境變數設定狀態 (自動脫敏)"),
                ("gc", "強制執行記憶體垃圾回收並統計釋放物件"),
            ],
            "三、資料庫與快取管理 (5)": [
                ("dbstat", "檢視資料庫連線池容量、作用中狀態與延遲"),
                ("dbtables", "查詢資料庫內所有表格名稱與總記錄筆數"),
                ("sql <query>", "安全唯讀執行 SQL 語句 (限 20 筆)"),
                ("cachestat", "檢視快取系統命中率、容量與鍵總數"),
                ("cacheflush [pat]", "清除指定模式或全部快取項目"),
            ],
            "四、AI 網關與認知架構 (5)": [
                ("aimodels", "列出 AI Gateway 當前載入的所有可用模型"),
                ("aistat", "查看 AI 請求成功率、Token 消耗與延遲"),
                ("aicontext [user]", "檢查指定使用者的對話上下文緩衝區"),
                ("cognetwork", "診斷認知網絡概念節點與活躍能量狀態"),
                ("causalaudit <prompt>", "現場運行因果邏輯審查器與矛盾檢測"),
            ],
            "五、網路與 Discord 閘道 (5)": [
                ("ping", "多端點延遲檢測 (Gateway / REST / DB)"),
                ("guilds [limit]", "列出 Bot 加入的伺服器分佈清單"),
                ("channelinfo [ch]", "查詢頻道的底層技術屬性與權限"),
                ("userinfo <user>", "查詢使用者的 Discord 屬性與資料庫設定"),
                ("auditlog [limit]", "即時拉取當前伺服器最新審核日誌記錄"),
            ],
            "六、排程、日誌與防護 (5)": [
                ("jobs", "列出系統背景排程任務與下次觸發時間"),
                ("jobrun <job_id>", "手動立即觸發執行指定背景排程任務"),
                ("logs [lines]", "即時讀取系統日誌末尾 N 行 (自動脫敏)"),
                ("loglevel [level]", "動態查看或切換全域日誌輸出級別"),
                ("ratelimit", "檢查速率限制器追蹤窗口與防護狀態"),
            ],
        }

        card = ZNCard(
            title="🛠️ ZeroNexus 開發者指令手冊 (前綴：`!zn <指令>`)",
            description=(
                "為核心開發者量身打造之 30 個強大維護指令。\n"
                "如需查詢單一指令詳細用法，請輸入：`!zn help <指令名稱>`\n"
            ),
            status_pill=ZNStatusPill.PRIMARY,
            color=ZNColor.PRIMARY,
        )

        for group_title, cmd_list in groups.items():
            content = "\n".join(f"`!zn {name}` — {desc}" for name, desc in cmd_list)
            card.add_section(group_title, content, inline=False)

        await ctx.send(embed=card.to_embed())


async def setup(bot: commands.Bot) -> None:
    """Extension dynamic setup entrypoint."""
    await bot.add_cog(DeveloperCog(bot))
    log.info("🛠️ 已成功載入開發者專用回文指令集 Cog (DeveloperCog)。")
