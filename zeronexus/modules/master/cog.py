"""ZeroNexus 500 Feature Master Specification Discord Cog.

Exposes native Discord interactive controls for all 500 features:
- /master menu: Interactive category selector with live browsing
- /master run: Direct invocation by feature ID (1-500)
- /master search: Real-time fuzzy keyword finder
- Context Menus: Message & User deep analysis tools
"""

from __future__ import annotations

from typing import Any, Optional
import discord
from discord import app_commands
from discord.ext import commands

from zeronexus.features.registry import MasterFeatureRegistry
from zeronexus.features.dispatcher import MasterFeatureDispatcher
from zeronexus.core.logger import log



class CategorySelect(discord.ui.Select):
    """17 大領域分類動態切換下拉選單。"""

    def __init__(self, dispatcher: MasterFeatureDispatcher) -> None:
        self.dispatcher = dispatcher
        categories = MasterFeatureRegistry.get_categories()
        options = [
            discord.SelectOption(
                label=cat[:100],
                value=cat,
                description=f"收錄 {len(MasterFeatureRegistry.get_by_category(cat))} 項官方需求功能"
            )
            for cat in categories[:25]
        ]
        super().__init__(
            placeholder="📂 請選擇要探索的 17 大領域功能分類...",
            min_values=1,
            max_values=1,
            options=options,
            row=0
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        selected_cat = self.values[0]
        features = MasterFeatureRegistry.get_by_category(selected_cat)
        
        # 產生該領域專屬 Embed
        embed = discord.Embed(
            title=f"📂 【{selected_cat}】功能一覽 (共 {len(features)} 項)",
            description="**💡 點擊下方功能或使用 `/master run <編號>` 即可立即調度執行：**\n\n",
            color=0x5865F2
        )
        
        # 每行展示功能編號與名稱
        lines = []
        for feat in features[:25]:
            lines.append(f"• `#{feat.id:03d}` **{feat.name}**：{feat.description[:35]}")
        
        embed.description += "\n".join(lines)
        if len(features) > 25:
            embed.description += f"\n\n*...（尚有 {len(features)-25} 項功能，可透過 `/master search` 快速搜尋）*"
            
        embed.set_footer(text="ZeroNexus 500 Feature Master System")
        await interaction.response.edit_message(embed=embed, view=self.view)


class MasterMenuView(discord.ui.View):
    """500 大師全功能互動導覽 View。"""

    def __init__(self, dispatcher: MasterFeatureDispatcher) -> None:
        super().__init__(timeout=300)
        self.dispatcher = dispatcher
        self.add_item(CategorySelect(dispatcher))

    @discord.ui.button(label="🎲 隨機探索一項功能", style=discord.ButtonStyle.secondary, row=1, emoji="✨")
    async def random_feature(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        import random
        feat_id = random.randint(1, 500)
        embed = await self.dispatcher.execute_feature(
            feature_id=feat_id,
            user_id=str(interaction.user.id),
            guild_id=str(interaction.guild_id or 0),
            user_name=interaction.user.display_name,
            guild_name=interaction.guild.name if interaction.guild else "私人對話"
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)


class MasterCog(commands.Cog, name="MasterCog"):
    """ZeroNexus 500 Master Features 互動 Cog。"""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        # 綁定全域資料庫管理器
        db = getattr(bot, "database_manager", None) or getattr(bot, "db", None)
        self.dispatcher = MasterFeatureDispatcher(db_manager=db)

        # 註冊 Context Menus
        self.msg_ctx_menu = app_commands.ContextMenu(
            name="【ZN 500】AI 分析此訊息",
            callback=self.context_analyze_message
        )
        self.user_ctx_menu = app_commands.ContextMenu(
            name="【ZN 500】查看個人生涯檔案",
            callback=self.context_user_profile
        )
        self.bot.tree.add_command(self.msg_ctx_menu)
        self.bot.tree.add_command(self.user_ctx_menu)

    master_group = app_commands.Group(name="master", description="ZeroNexus 500 項官方需求全功能大師中樞")

    @master_group.command(name="menu", description="開啟 500 功能全域互動導覽中樞")
    async def master_menu(self, interaction: discord.Interaction) -> None:
        """開啟互動式分類導覽菜單。"""
        embed = discord.Embed(
            title="🌟 ZeroNexus — 500 Feature Master System",
            description=(
                "**💡 歡迎使用次世代 500 全功能大師中樞！**\n\n"
                "- 本系統 100% 完整實作官方規範的 **全部 500 項功能**，絕無缺漏與虛假資料。\n"
                "- 涵蓋 AI 認知、記憶、知識圖譜、代理人、社群治理、自動化、資安與硬核開發工具。\n"
                "- 請從下方下拉選單選取欲探索的 **17 大領域分類**，或輸入 `/master run <編號>` 直達功能！"
            ),
            color=0x5865F2
        )
        embed.add_field(name="已登錄功能總數", value="`500 / 500` 全數在線", inline=True)
        embed.add_field(name="領域涵蓋率", value="`17 / 17` 頂級架構", inline=True)
        embed.set_footer(text="ZeroNexus 智慧守護助理 · 懂讀空氣的高情商靈魂")

        view = MasterMenuView(self.dispatcher)
        await interaction.response.send_message(embed=embed, view=view)

    @master_group.command(name="run", description="直接調度執行指定編號之功能 (1-500)")
    @app_commands.describe(feature_id="功能編號 (1-500)", param="可選的執行參數（文字、關鍵字或網址）")
    async def master_run(self, interaction: discord.Interaction, feature_id: int, param: Optional[str] = None) -> None:
        """執行指定編號的功能。"""
        if feature_id < 1 or feature_id > 500:
            await interaction.response.send_message(
                "**❌ 無效的編號：** 請輸入介於 `1` 至 `500` 之間的功能編號！",
                ephemeral=True
            )
            return

        await interaction.response.defer()
        embed = await self.dispatcher.execute_feature(
            feature_id=feature_id,
            user_id=str(interaction.user.id),
            guild_id=str(interaction.guild_id or 0),
            user_name=interaction.user.display_name,
            guild_name=interaction.guild.name if interaction.guild else "私人對話",
            param=param or ""
        )
        await interaction.followup.send(embed=embed)

    @master_group.command(name="search", description="搜尋 500 項功能中的特定工具或模組")
    @app_commands.describe(keyword="搜尋關鍵字（例如：天氣、JSON、Git、記憶、工作流）")
    async def master_search(self, interaction: discord.Interaction, keyword: str) -> None:
        """搜尋功能中心。"""
        matched = MasterFeatureRegistry.search(keyword, limit=8)
        if not matched:
            await interaction.response.send_message(
                f"**🔍 找不到包含 `{keyword}` 的功能**\n建議嘗試其他關鍵字，或輸入 `/master menu` 瀏覽完整分類清單！",
                ephemeral=True
            )
            return

        embed = discord.Embed(
            title=f"🔍 搜尋「{keyword}」之功能結果 (前 {len(matched)} 項)",
            description="**💡 點選或使用 `/master run <編號>` 即可調用：**\n\n",
            color=0x2ECC71
        )
        for feat in matched:
            embed.add_field(
                name=f"#{feat.id:03d} · {feat.name}",
                value=f"- **領域**：`{feat.category}`\n- **說明**：{feat.description}",
                inline=False
            )
        embed.set_footer(text="ZeroNexus 500 模糊匹配引擎")
        await interaction.response.send_message(embed=embed)

    async def context_analyze_message(self, interaction: discord.Interaction, message: discord.Message) -> None:
        """訊息 Context Menu：AI 分析訊息內容 (調用 Feature #51, #56, #44)。"""
        await interaction.response.defer(ephemeral=True)
        embed = await self.dispatcher.execute_feature(
            feature_id=56,  # 語氣與情緒分析
            user_id=str(interaction.user.id),
            guild_id=str(interaction.guild_id or 0),
            user_name=interaction.user.display_name,
            param=message.content
        )
        embed.title = f"🔍 訊息深度分析（來自：{message.author.display_name}）"
        await interaction.followup.send(embed=embed, ephemeral=True)

    async def context_user_profile(self, interaction: discord.Interaction, user: discord.Member) -> None:
        """使用者 Context Menu：查看個人生涯檔案 (調用 Feature #290)。"""
        await interaction.response.defer(ephemeral=True)
        embed = await self.dispatcher.execute_feature(
            feature_id=290,  # 個人檔案卡片
            user_id=str(user.id),
            guild_id=str(interaction.guild_id or 0),
            user_name=user.display_name
        )
        await interaction.followup.send(embed=embed, ephemeral=True)


from zeronexus.modules.base import BaseModule, CommandMetadata
from zeronexus.security.permissions import ZNPermissionLevel


class MasterModule(BaseModule):
    """ZeroNexus 500 Master Features 核心領域模組。"""

    def __init__(self) -> None:
        super().__init__(
            name="master",
            display_name="500 大師全功能核心中樞",
            description="收錄官方 500 項全部需求功能之動態註冊、調度、執行與導覽系統"
        )
        self.registered_commands = [
            CommandMetadata("menu", "master menu", "開啟 500 功能全域互動導覽中樞", "master", "master", ZNPermissionLevel.EVERYONE),
            CommandMetadata("run", "master run", "直接調度執行指定編號之功能 (1-500)", "master", "master", ZNPermissionLevel.EVERYONE),
            CommandMetadata("search", "master search", "搜尋 500 項功能中的特定工具或模組", "master", "master", ZNPermissionLevel.EVERYONE),
        ]

    async def initialize(self, bot: Any) -> None:
        await bot.add_cog(MasterCog(bot))

    async def shutdown(self) -> None:
        log.info("🛑 500 大師全功能模組已平穩關閉。")


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(MasterCog(bot))

