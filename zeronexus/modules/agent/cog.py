"""ZeroNexus Native Agent Slash Command Cog.

Implements /代理人 commands:
- 執行: Runs a multi-stage analytical or diagnostic agent task with progressive ZNCard UI updates
- 診斷: Comprehensive full-stack platform and guild inspection
- 狀態: Displays native Agent engine capabilities and read-only safety boundaries
"""

import time
from typing import Any

import discord
from discord import app_commands
from discord.ext import commands

from zeronexus.agent.engine import AgentProgress, agent_engine
from zeronexus.agent.tools import agent_tools
from zeronexus.modules.base import BaseModule, CommandMetadata
from zeronexus.security.guard import command_guard
from zeronexus.security.permissions import ZNPermissionLevel
from zeronexus.ui.card import ZNCard
from zeronexus.ui.responder import InteractionResponder
from zeronexus.ui.theme import ZNColor, ZNStatusPill


class AgentModule(BaseModule):
    """Native 5-Stage Agent Orchestration Engine Module."""

    def __init__(self) -> None:
        super().__init__(
            name="agent",
            display_name="代理人模組",
            description="原生 5 階段 Agent 執行引擎 (規劃、路由、執行、驗證、復原)，具備嚴格唯讀安全防線",
        )

    async def initialize(self, bot: Any) -> None:
        commands_list = [
            ("執行", "啟動原生 5 階段代理人執行多步驟唯讀推理或診斷任務", ZNPermissionLevel.EVERYONE),
            ("診斷", "自動對 Bot 資源、模組健康、伺服器配置進行全方位深度巡檢", ZNPermissionLevel.ADMINISTRATOR),
            ("狀態", "檢視代理人原生引擎運作指標、唯讀工具箱與安全邊界", ZNPermissionLevel.EVERYONE),
        ]
        for name, desc, perm in commands_list:
            self.register_command_meta(CommandMetadata(
                name=name,
                full_name=f"代理人 {name}",
                description=desc,
                group_name="代理人",
                module_name=self.name,
                permission_level=perm,
            ))

    async def shutdown(self) -> None:
        pass


class AgentCog(commands.Cog):
    """Discord Slash Command Group for /代理人."""

    agent_group = app_commands.Group(name="代理人", description="原生 5 階段 Agent 代理人與全域唯讀診斷引擎")

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    def _render_progress_card(self, progress: AgentProgress) -> ZNCard:
        stage_names = {
            "PLANNER": ("📋 規劃階段 (Planner)", ZNStatusPill.THINKING, ZNColor.INFO),
            "ROUTER": ("🔀 路由階段 (Tool Router)", ZNStatusPill.TOOL, ZNColor.INFO),
            "EXECUTOR": ("⚙️ 執行階段 (Executor)", ZNStatusPill.AI, ZNColor.AI),
            "VERIFIER": ("🔍 驗證階段 (Verifier)", ZNStatusPill.WARNING, ZNColor.WARNING),
            "RECOVERY": ("🛠️ 復原階段 (Recovery)", ZNStatusPill.WARNING, ZNColor.WARNING),
            "COMPLETED": ("✅ 任務完成 (Completed)", ZNStatusPill.SUCCESS, ZNColor.SUCCESS),
            "FAILED": ("❌ 執行未果 (Failed)", ZNStatusPill.ERROR, ZNColor.ERROR),
        }

        stage_title, pill, color = stage_names.get(progress.current_stage, ("🤖 代理人運作中", ZNStatusPill.AI, ZNColor.AI))

        card = ZNCard(
            title=f"ZeroNexus 智慧代理人 — {stage_title}",
            description=f"🎯 **任務目標**：{progress.task_goal}\n📍 **當前進度**：{progress.stage_description}",
            status_pill=pill,
            color=color,
        )

        if progress.steps:
            step_lines = []
            for s in progress.steps:
                icon = "⏳" if s.status == "PENDING" else ("🔄" if s.status == "RUNNING" else ("✅" if s.status == "COMPLETED" else "❌"))
                tool_label = f"`[{s.tool_name}]` " if s.tool_name else ""
                step_lines.append(f"{icon} **步驟 {s.step_id}**：{tool_label}{s.title}")
            card.add_section("📋 執行路線圖規劃", "\n".join(step_lines), inline=False)

        card.add_section("⏱️ 累計耗時", f"`{progress.elapsed_ms} ms`", inline=True)
        card.add_section("🛡️ 安全隔離防線", "`唯讀受限沙盒 (Read-Only)`", inline=True)

        return card

    async def _execute_agent_task(self, interaction: discord.Interaction, 任務: str) -> None:
        任務 = 任務.strip()
        if not 任務:
            await InteractionResponder.safe_send(interaction, "💡 請輸入欲委託代理人分析或執行的任務說明喔！例如：`全方位巡檢伺服器健康狀態`。", ephemeral=True)
            return

        if len(任務) > 500:
            await InteractionResponder.safe_send(interaction, "📝 任務說明長度請保持在 500 個字元以內，清晰精煉的描述有助於代理人更精確地規劃路線圖！", ephemeral=True)
            return

        if not await InteractionResponder.safe_defer(interaction):
            return

        # Initial card
        init_progress = AgentProgress(
            task_goal=任務,
            current_stage="PLANNER",
            stage_description="正在啟動原生 Agent 推理引擎並初始化分析上下文...",
        )
        init_card = self._render_progress_card(init_progress)
        await InteractionResponder.safe_send(interaction, card=init_card)

        last_edit_time = 0.0

        async def on_progress(p: AgentProgress) -> None:
            nonlocal last_edit_time
            now = time.time()
            # Throttle edits to prevent Discord rate limits (minimum 0.8s between edits unless completed)
            if (now - last_edit_time > 0.8) or p.current_stage in ("COMPLETED", "FAILED"):
                last_edit_time = now
                card = self._render_progress_card(p)
                if p.current_stage == "COMPLETED" and p.final_output:
                    card.add_section("📊 綜合報告產出", p.final_output[:1024], inline=False)
                try:
                    await InteractionResponder.safe_edit(interaction, card=card)
                except Exception:
                    pass

        try:
            final_progress = await agent_engine.run_task(
                task_goal=任務,
                guild=interaction.guild,
                channel=interaction.channel if isinstance(interaction.channel, discord.TextChannel) else None,
                user=interaction.user,
                progress_callback=on_progress,
            )
            # Final guaranteed render
            final_card = self._render_progress_card(final_progress)
            if final_progress.final_output:
                final_card.add_section("📊 綜合報告產出", final_progress.final_output[:1024], inline=False)
            await InteractionResponder.safe_edit(interaction, card=final_card)
        except Exception as e:
            from zeronexus.security.sanitizer import redact_secrets
            clean_err = redact_secrets(str(e))
            err_card = ZNCard(
                title="代理人執行遇到狀況",
                description=(
                    "代理人在執行推演分析的過程中遇到了未預期的問題。\n\n"
                    f"📌 **狀況簡述**：`{clean_err[:120]}`\n\n"
                    "💡 **您可以嘗試**：\n"
                    "- 嘗試簡化任務目標或拆分成更明確的單一子目標。\n"
                    "- 確認所需資料或權限是否完備，稍後再次嘗試。"
                ),
                status_pill=ZNStatusPill.ERROR,
                color=ZNColor.ERROR,
            )
            await InteractionResponder.safe_edit(interaction, card=err_card)

    @agent_group.command(name="執行", description="啟動原生 Agent 執行多步驟深度推理、資料提取或系統診斷任務")
    @app_commands.describe(任務="欲由代理人完成之目標 (例如：診斷伺服器健康狀況、計算 2**64 並檢查模組狀態)")
    @command_guard("agent")
    async def run_command(self, interaction: discord.Interaction, 任務: str) -> None:
        await self._execute_agent_task(interaction, 任務=任務)

    @agent_group.command(name="診斷", description="全方位自動深度巡檢 Bot 資源、11 個功能模組與目前伺服器設定")
    @command_guard("agent", required_level=ZNPermissionLevel.ADMINISTRATOR)
    async def diagnose_command(self, interaction: discord.Interaction) -> None:
        await self._execute_agent_task(interaction, 任務="全方位深度巡檢系統資源負載、功能模組健康狀態與伺服器架構")

    @agent_group.command(name="狀態", description="檢視 ZeroNexus 原生代理人引擎運作指標與唯讀工具箱清單")
    @command_guard("agent")
    async def status_command(self, interaction: discord.Interaction) -> None:
        tools = agent_tools.list_tools()
        categories = agent_tools.get_categories()
        cat_lines = []
        for cat in categories:
            cat_tools = agent_tools.list_by_category(cat)
            sample_names = ", ".join(f"`{t.name}`" for t in cat_tools[:3])
            more = f" 等 {len(cat_tools)} 種" if len(cat_tools) > 3 else ""
            cat_lines.append(f"• **{cat}** ({len(cat_tools)} 種)：{sample_names}{more}")

        card = ZNCard(
            title="ZeroNexus 原生代理人工具庫狀態",
            description=(
                f"ZeroNexus 代理人配備**自研 5 階段推理架構**（規劃 ➔ 路由 ➔ 執行 ➔ 驗證 ➔ 復原），\n"
                f"全平台已裝載高達 **{len(tools)} 種受限唯讀工具**，全面支援 Function Calling 原生調用。"
            ),
            status_pill=ZNStatusPill.AI,
            color=ZNColor.AI,
        )
        card.add_section(f"🛠️ 10 大領域工具箱 (共 {len(tools)} 種工具)", "\n".join(cat_lines), inline=False)
        card.add_section("🛡️ 唯讀安全防線", "✅ 零破壞性寫入，嚴格限制管理員寫入操作，杜絕越權風險", inline=False)
        card.add_section("⚡ 支援調用方式", "1. `/代理人 執行` 即時多階段推理分析卡片\n2. `/人工智慧 對話` 自適應 Function Calling 與工具增強推理", inline=False)

        await InteractionResponder.safe_send(interaction, card=card)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(AgentCog(bot))
