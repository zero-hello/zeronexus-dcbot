"""ZeroNexus Server Information & Community Insights Cog.

16 Fully Implemented Commands under /伺服器:
- 資訊, 成員列表, 身分組清單, 頻道清單, 表情符號, 邀請連結, 統計
- 伺服器圖示, 橫幅, 權限檢視, 頻道資訊, 身分組資訊, 成員資訊, 升級加成, 排行榜, 頭像
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Union

import discord
from discord import app_commands
from discord.ext import commands
from sqlalchemy import desc, select

from zeronexus.ai_gateway.gateway import ai_gateway
from zeronexus.core.database import db
from zeronexus.engines.channel_inspector import channel_inspector, parse_channel_time_filter
from zeronexus.models.user import EconomyWallet
from zeronexus.modules.base import BaseModule, CommandMetadata
from zeronexus.security.guard import command_guard
from zeronexus.security.permissions import ZNPermissionLevel
from zeronexus.ui.card import ZNCard
from zeronexus.ui.responder import InteractionResponder
from zeronexus.ui.theme import ZNColor, ZNStatusPill


# ==============================================================================
# Localization Dictionaries
# ==============================================================================

VERIFICATION_LEVELS: Dict[str, str] = {
    "none": "無限制 (None)",
    "low": "低 (需已驗證電子郵件)",
    "medium": "中 (帳號註冊滿 5 分鐘)",
    "high": "高 (加入本伺服器滿 10 分鐘)",
    "highest": "最高 (需已綁定驗證手機號碼)",
}

EXPLICIT_FILTER_LEVELS: Dict[str, str] = {
    "disabled": "關閉過濾掃描",
    "no_role": "過濾掃描無身分組成員訊息",
    "all_members": "過濾掃描所有成員訊息",
}

MFA_LEVELS: Dict[str, str] = {
    "none": "未強制要求",
    "elevated": "強制要求雙重認證 (2FA)",
}

NOTIFICATION_LEVELS: Dict[str, str] = {
    "all_messages": "所有訊息",
    "only_mentions": "僅提及 (@mentions)",
}

GUILD_FEATURES: Dict[str, str] = {
    "COMMUNITY": "社群伺服器",
    "PARTNERED": "Discord 官方合作夥伴",
    "VERIFIED": "官方認證伺服器",
    "VANITY_URL": "自訂個性邀請網址",
    "BANNER": "專屬伺服器橫幅",
    "ANIMATED_ICON": "動態伺服器圖示",
    "INVITE_SPLASH": "自訂邀請背景圖",
    "ROLE_ICONS": "自訂身分組圖示",
    "NEWS": "公告發布頻道",
    "DISCOVERABLE": "伺服器探索列表",
    "FEATURABLE": "精選探索資格",
    "AUTO_MODERATION": "AutoMod 智慧安全防護",
    "CREATOR_MONETIZATION_PERKS": "創作者營利特權",
    "DEVELOPER_SUPPORT_SERVER": "官方認證開發者支援伺服器",
}

USER_FLAGS_MAP: Dict[str, str] = {
    "staff": "Discord 官方員工",
    "partner": "合作夥伴伺服器負責人",
    "hypesquad": "HypeSquad 活動成員",
    "bug_hunter": "Bug 獵人 (等級 1)",
    "bug_hunter_level_2": "Bug 獵人 (等級 2)",
    "hypesquad_bravery": "HypeSquad 勇氣之扉 (Bravery)",
    "hypesquad_brilliance": "HypeSquad 卓越之輝 (Brilliance)",
    "hypesquad_balance": "HypeSquad 平衡之誓 (Balance)",
    "early_supporter": "早期 Nitro 支持者",
    "verified_bot_developer": "早期已驗證開發者",
    "active_developer": "活躍開發者 (Active Developer)",
}


# ==============================================================================
# Module Definition
# ==============================================================================

class ServerModule(BaseModule):
    """Server insights, channel directories, roles, and member inspection."""

    def __init__(self) -> None:
        super().__init__(
            name="server",
            display_name="伺服器模組",
            description="伺服器資訊檢索、成員統計、身分組權限分析、頭像查詢與社群總覽",
        )

    async def initialize(self, bot: Any) -> None:
        commands_list = [
            ("資訊", "檢視伺服器詳細創立資訊、安全等級與配置", ZNPermissionLevel.EVERYONE),
            ("成員列表", "統計在線狀態、真人與機器人人數分布", ZNPermissionLevel.EVERYONE),
            ("身分組清單", "列出伺服器所有身分組與成員人數順位", ZNPermissionLevel.EVERYONE),
            ("頻道清單", "分類統計文字、語音、討論串與論壇頻道", ZNPermissionLevel.EVERYONE),
            ("表情符號", "檢視伺服器自訂靜態表情、動態表情與貼圖", ZNPermissionLevel.EVERYONE),
            ("邀請連結", "檢視有效邀請代碼、創建者與點擊統計", ZNPermissionLevel.MODERATOR),
            ("統計", "檢視伺服器活躍概況與音訊頻寬上限矩陣", ZNPermissionLevel.EVERYONE),
            ("伺服器圖示", "獲取伺服器高解析度圖示與下載連結", ZNPermissionLevel.EVERYONE),
            ("橫幅", "獲取伺服器專屬橫幅與邀請背景插圖", ZNPermissionLevel.EVERYONE),
            ("權限檢視", "分析指定成員或身分組在頻道的權限設定", ZNPermissionLevel.EVERYONE),
            ("頻道資訊", "檢視頻道建立時間、主題說明與慢速模式", ZNPermissionLevel.EVERYONE),
            ("身分組資訊", "檢視身分組權限位元、顏色代碼與成員數", ZNPermissionLevel.EVERYONE),
            ("成員資訊", "檢視成員帳號註冊日、伺服器加入日與身分組", ZNPermissionLevel.EVERYONE),
            ("升級加成", "檢視伺服器 Nitro Boost 等級與加成者權益", ZNPermissionLevel.EVERYONE),
            ("排行榜", "檢視伺服器虛擬點數活躍貢獻排行榜", ZNPermissionLevel.EVERYONE),
            ("頭像", "檢視成員或使用者之高畫質個人頭像與伺服器自訂頭像", ZNPermissionLevel.EVERYONE),
            ("成員橫幅", "檢視成員或使用者之高畫質個人個人檔案橫幅 (Profile Banner)", ZNPermissionLevel.EVERYONE),
        ]
        for name, cmd_desc, perm in commands_list:
            self.register_command_meta(CommandMetadata(
                name=name,
                full_name=f"伺服器 {name}",
                description=cmd_desc,
                group_name="伺服器",
                module_name=self.name,
                permission_level=perm,
            ))

        channel_commands_list = [
            ("摘要", "透過 AI 統整特定時間區間或最近的頻道聊天話題與焦點", ZNPermissionLevel.EVERYONE),
            ("統計", "統計頻道成員發言之王排行榜、字數比例與活躍概況", ZNPermissionLevel.EVERYONE),
            ("總覽", "檢視頻道全方位情資、主題說明與活躍討論串", ZNPermissionLevel.EVERYONE),
        ]
        for name, cmd_desc, perm in channel_commands_list:
            self.register_command_meta(CommandMetadata(
                name=name,
                full_name=f"頻道 {name}",
                description=cmd_desc,
                group_name="頻道",
                module_name=self.name,
                permission_level=perm,
            ))

    async def shutdown(self) -> None:
        pass


# ==============================================================================
# Cog Implementation
# ==============================================================================

class ServerCog(commands.Cog):
    """Discord Slash Command Group for /伺服器."""

    server_group = app_commands.Group(name="伺服器", description="伺服器資訊檢索與社群狀態指令群組", guild_only=True)

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if not interaction.guild:
            await InteractionResponder.safe_send(interaction, "❌ 伺服器資訊相關指令僅限在 Discord 伺服器群組內使用。", ephemeral=True)
            return False
        return True

    # --------------------------------------------------------------------------
    # 1. 伺服器資訊 serverinfo
    # --------------------------------------------------------------------------
    @server_group.command(name="資訊", description="檢視伺服器詳細基本資料、配置與安全層級")
    @command_guard("server")
    async def info_command(self, interaction: discord.Interaction) -> None:
        g = interaction.guild
        owner = g.owner or (await self.bot.fetch_user(g.owner_id) if g.owner_id else None)
        owner_name = f"{owner.display_name} (`{owner.id}`)" if owner else f"ID: `{g.owner_id}`"

        created_ts = int(g.created_at.timestamp())
        verify_key = str(g.verification_level).lower().split(".")[-1]
        verify_str = VERIFICATION_LEVELS.get(verify_key, str(g.verification_level).capitalize())

        explicit_key = str(g.explicit_content_filter).lower().split(".")[-1]
        explicit_str = EXPLICIT_FILTER_LEVELS.get(explicit_key, str(g.explicit_content_filter))

        mfa_key = "elevated" if getattr(g, "mfa_level", 0) else "none"
        mfa_str = MFA_LEVELS.get(mfa_key, "未強制")

        notify_key = str(g.default_notifications).lower().split(".")[-1]
        notify_str = NOTIFICATION_LEVELS.get(notify_key, str(g.default_notifications))

        channels_total = len(g.channels)
        roles_total = len([r for r in g.roles if not r.is_default()])
        emojis_total = len(g.emojis)
        stickers_total = len(g.stickers)

        card = ZNCard(
            title=f"{g.name} — 伺服器資訊總覽",
            description=g.description or "這座伺服器尚未填寫專屬社群簡介。",
            status_pill=ZNStatusPill.SYSTEM,
            color=ZNColor.PRIMARY,
            thumbnail_url=g.icon.url if g.icon else None,
        )
        card.add_section("👑 伺服器擁有者", f"<@{g.owner_id}> ({owner_name})", inline=True)
        card.add_section("🆔 伺服器 ID", f"`{g.id}`", inline=True)
        card.add_section("📅 創立時間", f"<t:{created_ts}:F>\n(<t:{created_ts}:R>)", inline=True)
        card.add_section("👥 成員總數", f"`{g.member_count}` 位成員", inline=True)
        card.add_section("💬 頻道總數", f"`{channels_total}` 個 (文字/語音/論壇)", inline=True)
        card.add_section("🛡️ 身分組與表情", f"`{roles_total}` 身分組 / `{emojis_total}` 表情 / `{stickers_total}` 貼圖", inline=True)
        card.add_section("🛡️ 安全驗證等級", f"`{verify_str}`", inline=True)
        card.add_section("🔐 兩步驟驗證要求", f"`{mfa_str}`", inline=True)
        card.add_section("🔔 預設通知設定", f"`{notify_str}`", inline=True)
        card.add_section("🔞 違規內容過濾", f"`{explicit_str}`", inline=True)
        card.add_section("🚀 Nitro 加成", f"等級 {g.premium_tier} ({g.premium_subscription_count} 次加成)", inline=True)

        if g.vanity_url_code:
            card.add_section("🔗 自訂個性連結", f"discord.gg/{g.vanity_url_code}", inline=True)

        await InteractionResponder.safe_send(interaction, card=card)

    # --------------------------------------------------------------------------
    # 2. 成員列表 members
    # --------------------------------------------------------------------------
    @server_group.command(name="成員列表", description="檢視伺服器成員狀態分布與機器人統計")
    @command_guard("server")
    async def members_command(self, interaction: discord.Interaction) -> None:
        g = interaction.guild
        total = int(getattr(g, "member_count", 0) or len(getattr(g, "members", [])))
        cached_members = getattr(g, "members", [])
        bots = sum(1 for m in cached_members if getattr(m, "bot", False))
        humans = max(0, total - bots)
        ratio = (humans / total * 100) if total > 0 else 0.0

        # Status presence breakdown if members are cached
        online = sum(1 for m in cached_members if str(m.status) == "online")
        idle = sum(1 for m in cached_members if str(m.status) == "idle")
        dnd = sum(1 for m in cached_members if str(m.status) == "dnd")
        offline = sum(1 for m in cached_members if str(m.status) == "offline")

        desc_lines = [
            f"- **伺服器總人數**：`{total}` 位",
            f"- 👤 **真人成員**：`{humans}` 位 (`{ratio:.1f}%`)",
            f"- 🤖 **機器人帳號**：`{bots}` 位",
        ]

        if online + idle + dnd > 0:
            desc_lines.extend([
                "",
                "**🟢 即時在線狀態概況**：",
                f"- 🟢 **在線**：`{online}` 人",
                f"- 🟡 **閒置**：`{idle}` 人",
                f"- 🔴 **請勿打擾**：`{dnd}` 人",
                f"- ⚫ **離線 / 隱匿**：`{offline}` 人",
            ])

        card = ZNCard(
            title=f"{g.name} — 成員統計與在線分布",
            description="\n".join(desc_lines),
            status_pill=ZNStatusPill.TOOL,
            color=ZNColor.INFO,
        )
        await InteractionResponder.safe_send(interaction, card=card)

    # --------------------------------------------------------------------------
    # 3. 身分組清單 roles
    # --------------------------------------------------------------------------
    @server_group.command(name="身分組清單", description="列出伺服器所有身分組與順位人數")
    @command_guard("server")
    async def roles_command(self, interaction: discord.Interaction) -> None:
        roles = sorted(
            [r for r in interaction.guild.roles if not r.is_default()],
            key=lambda r: r.position,
            reverse=True,
        )

        lines: List[str] = []
        for r in roles:
            hoist_mark = "📌 " if r.hoist else ""
            lines.append(f"{hoist_mark}{r.mention} — `{len(r.members)} 人` (順位: `{r.position}`)")

        display_text = "\n".join(lines[:25])
        if len(lines) > 25:
            display_text += f"\n\n*... 以及其餘 {len(lines) - 25} 個身分組*"

        card = ZNCard(
            title=f"身分組階層清單 (共 {len(roles)} 個自訂身分組)",
            description=display_text or "本伺服器目前無自訂身分組。",
            status_pill=ZNStatusPill.TOOL,
            color=ZNColor.INFO,
        )
        await InteractionResponder.safe_send(interaction, card=card)

    # --------------------------------------------------------------------------
    # 4. 頻道清單 channels
    # --------------------------------------------------------------------------
    @server_group.command(name="頻道清單", description="分類統計文字、語音、論壇與討論串")
    @command_guard("server")
    async def channels_command(self, interaction: discord.Interaction) -> None:
        g = interaction.guild
        text_count = len(g.text_channels)
        voice_count = len(g.voice_channels)
        stage_count = len(g.stage_channels)
        forum_count = len(getattr(g, "forum_channels", []))
        thread_count = len(g.threads)
        category_count = len(g.categories)
        total_channels = text_count + voice_count + stage_count + forum_count

        card = ZNCard(
            title=f"{g.name} — 頻道結構矩陣",
            description=(
                f"伺服器共計建置 **{total_channels}** 個頻道節點：\n\n"
                f"- 📁 **分類目錄**：`{category_count}` 個目錄\n"
                f"- 💬 **文字頻道**：`{text_count}` 個頻道\n"
                f"- 🔊 **語音頻道**：`{voice_count}` 個頻道\n"
                f"- 🎭 **舞台活動頻道**：`{stage_count}` 個頻道\n"
                f"- 📑 **論壇頻道**：`{forum_count}` 個頻道\n"
                f"- 🧵 **進行中討論串**：`{thread_count}` 個串"
            ),
            status_pill=ZNStatusPill.TOOL,
            color=ZNColor.PRIMARY,
        )
        await InteractionResponder.safe_send(interaction, card=card)

    # --------------------------------------------------------------------------
    # 5. 表情清單 emojis
    # --------------------------------------------------------------------------
    @server_group.command(name="表情符號", description="檢視伺服器靜態與動態表情符號總覽")
    @command_guard("server")
    async def emojis_command(self, interaction: discord.Interaction) -> None:
        g = interaction.guild
        static_emojis = [str(e) for e in g.emojis if not e.animated]
        animated_emojis = [str(e) for e in g.emojis if e.animated]
        stickers_count = len(g.stickers)
        limit = g.emoji_limit

        card = ZNCard(
            title=f"{g.name} — 自訂表情與貼圖",
            description=(
                f"**靜態表情符號 ({len(static_emojis)}/{limit})**：\n"
                f"{' '.join(static_emojis[:30]) if static_emojis else '無自訂靜態表情'}"
                f"{f' *(其餘 {len(static_emojis)-30} 個已省略)*' if len(static_emojis) > 30 else ''}\n\n"
                f"**動態表情符號 ({len(animated_emojis)}/{limit})**：\n"
                f"{' '.join(animated_emojis[:30]) if animated_emojis else '無自訂動態表情'}"
                f"{f' *(其餘 {len(animated_emojis)-30} 個已省略)*' if len(animated_emojis) > 30 else ''}\n\n"
                f"**自訂貼圖總數**：`{stickers_count} / {g.sticker_limit}` 個"
            ),
            status_pill=ZNStatusPill.FUN,
            color=ZNColor.INFO,
        )
        await InteractionResponder.safe_send(interaction, card=card)

    # --------------------------------------------------------------------------
    # 6. 邀請連結 invites
    # --------------------------------------------------------------------------
    @server_group.command(name="邀請連結", description="檢視伺服器有效邀請連結與點擊紀錄")
    @command_guard("server", required_level=ZNPermissionLevel.MODERATOR)
    async def invites_command(self, interaction: discord.Interaction) -> None:
        bot_member = interaction.guild.me
        if not bot_member or not bot_member.guild_permissions.manage_guild:
            await InteractionResponder.safe_send(interaction, "❌ ZeroNexus 缺少「管理伺服器 (Manage Server)」權限，無法讀取邀請連結清單。", ephemeral=True)
            return

        await InteractionResponder.safe_defer(interaction, ephemeral=True)
        try:
            invites = await interaction.guild.invites()
        except discord.Forbidden:
            await InteractionResponder.safe_send(interaction, "❌ Discord 權限不足：無法調取此伺服器的邀請連結。", ephemeral=True)
            return
        except discord.HTTPException as ex:
            await InteractionResponder.safe_send(interaction, f"❌ 調取邀請連結失敗 (HTTP {ex.status})：`{ex.text or ex}`", ephemeral=True)
            return

        if not invites:
            card = ZNCard(
                title="邀請連結清單",
                description="伺服器目前無任何有效或公開之自訂邀請連結。",
                status_pill=ZNStatusPill.TOOL,
                color=ZNColor.INFO,
            )
            await InteractionResponder.safe_send(interaction, card=card, ephemeral=True)
            return

        lines: List[str] = []
        for inv in invites[:10]:
            inviter = inv.inviter.display_name if inv.inviter else "系統/未知"
            channel_name = inv.channel.name if inv.channel else "未知頻道"
            max_uses_str = f"/{inv.max_uses}" if inv.max_uses else " (無次數限制)"
            lines.append(
                f"- [`{inv.code}`]({inv.url}) — 建立者：**{inviter}** (已使用: `{inv.uses}{max_uses_str}` | 目標: #{channel_name})"
            )

        card = ZNCard(
            title=f"伺服器邀請連結清單 (共 {len(invites)} 筆)",
            description="\n".join(lines),
            status_pill=ZNStatusPill.TOOL,
            color=ZNColor.INFO,
        )
        await InteractionResponder.safe_send(interaction, card=card, ephemeral=True)

    # --------------------------------------------------------------------------
    # 7. 統計 stats
    # --------------------------------------------------------------------------
    @server_group.command(name="統計", description="檢視伺服器活躍指標、特權與技術規格")
    @command_guard("server")
    async def stats_command(self, interaction: discord.Interaction) -> None:
        g = interaction.guild
        features_translated = [
            GUILD_FEATURES.get(f, f) for f in g.features
        ]

        card = ZNCard(
            title=f"{g.name} — 伺服器規格與特權大盤",
            description=(
                f"- **成員容納規模**：`{g.member_count} / {g.max_members or '無固定上限'}`\n"
                f"- **Nitro Boost 加成**：`等級 {g.premium_tier}` (`{g.premium_subscription_count}` 次加成)\n"
                f"- **語音位元率上限**：`{g.bitrate_limit // 1000} kbps`\n"
                f"- **檔案上傳大小上限**：`{g.filesize_limit / (1024 * 1024):.0f} MB`\n"
                f"- **表情符號容量上限**：`{g.emoji_limit}` 個\n"
                f"- **貼圖容量上限**：`{g.sticker_limit}` 個\n\n"
                f"**🏅 伺服器解鎖特性**：\n"
                f"{'、'.join(features_translated) if features_translated else '標準伺服器配置 (無特殊徽章特性)'}"
            ),
            status_pill=ZNStatusPill.SYSTEM,
            color=ZNColor.PRIMARY,
        )
        await InteractionResponder.safe_send(interaction, card=card)

    # --------------------------------------------------------------------------
    # 8. 伺服器圖示 icon
    # --------------------------------------------------------------------------
    @server_group.command(name="伺服器圖示", description="獲取伺服器圖示高解析度原圖與下載連結")
    @command_guard("server")
    async def icon_command(self, interaction: discord.Interaction) -> None:
        if not interaction.guild.icon:
            await InteractionResponder.safe_send(interaction, "❌ 本伺服器尚未設置專屬圖示。", ephemeral=True)
            return

        icon = interaction.guild.icon
        is_anim = icon.is_animated()
        formats = [
            f"[PNG]({icon.replace(format='png', size=1024).url})",
            f"[JPG]({icon.replace(format='jpeg', size=1024).url})",
            f"[WEBP]({icon.replace(format='webp', size=1024).url})",
        ]
        if is_anim:
            formats.append(f"[GIF]({icon.replace(format='gif', size=1024).url})")

        img_url = icon.with_size(1024).url
        card = ZNCard(
            title=f"{interaction.guild.name} — 伺服器圖示",
            description=f"下載原始 1024x1024 高解析度圖檔：\n{' • '.join(formats)}",
            image_url=img_url,
            status_pill=ZNStatusPill.TOOL,
            color=ZNColor.PRIMARY,
        )
        await InteractionResponder.safe_send(interaction, card=card)

    # --------------------------------------------------------------------------
    # 9. 橫幅 banner
    # --------------------------------------------------------------------------
    @server_group.command(name="橫幅", description="獲取伺服器專屬橫幅與邀請背景插圖")
    @command_guard("server")
    async def banner_command(self, interaction: discord.Interaction) -> None:
        g = interaction.guild
        target_asset = g.banner or g.splash or g.discovery_splash

        if not target_asset:
            await InteractionResponder.safe_send(interaction, "❌ 本伺服器尚未配置專屬橫幅或自訂背景圖片。", ephemeral=True)
            return

        asset_name = "伺服器橫幅" if g.banner else ("邀請背景插圖" if g.splash else "探索橫幅")
        is_anim = target_asset.is_animated()
        formats = [
            f"[PNG]({target_asset.replace(format='png', size=1024).url})",
            f"[JPG]({target_asset.replace(format='jpeg', size=1024).url})",
            f"[WEBP]({target_asset.replace(format='webp', size=1024).url})",
        ]
        if is_anim:
            formats.append(f"[GIF]({target_asset.replace(format='gif', size=1024).url})")

        img_url = target_asset.with_size(1024).url
        card = ZNCard(
            title=f"{g.name} — {asset_name}",
            description=f"下載原始高解析度圖檔：\n{' • '.join(formats)}",
            image_url=img_url,
            status_pill=ZNStatusPill.TOOL,
            color=ZNColor.PRIMARY,
        )
        await InteractionResponder.safe_send(interaction, card=card)

    # --------------------------------------------------------------------------
    # 10. 權限檢視 permissions
    # --------------------------------------------------------------------------
    @server_group.command(name="權限檢視", description="檢視指定成員或身分組在頻道的權限設定")
    @app_commands.describe(目標成員="指定成員 (選填)", 目標身分組="指定身分組 (選填)", 頻道="指定頻道 (預設當前)")
    @command_guard("server")
    async def permissions_command(
        self,
        interaction: discord.Interaction,
        目標成員: Optional[discord.Member] = None,
        目標身分組: Optional[discord.Role] = None,
        頻道: Optional[discord.abc.GuildChannel] = None,
    ) -> None:
        ch = 頻道 or interaction.channel
        if not hasattr(ch, "permissions_for"):
            await InteractionResponder.safe_send(interaction, "❌ 此頻道不支援權限檢視。", ephemeral=True)
            return

        target_obj = 目標身分組 or 目標成員 or interaction.user
        perms = ch.permissions_for(target_obj)
        target_title = f"身分組 @{target_obj.name}" if isinstance(target_obj, discord.Role) else f"成員 {target_obj.display_name}"

        perm_badges: List[str] = []

        def check(flag: bool, name: str) -> None:
            if flag:
                perm_badges.append(f"✅ {name}")
            else:
                perm_badges.append(f"❌ {name}")

        check(perms.administrator, "👑 管理員 (Administrator)")
        check(perms.manage_guild, "⚙️ 管理伺服器")
        check(perms.manage_roles, "🛡️ 管理身分組")
        check(perms.manage_channels, "📁 管理頻道")
        check(perms.view_audit_log, "📜 檢視審核日誌")
        check(perms.view_channel, "👀 檢視頻道")
        check(perms.send_messages, "💬 發送訊息")
        check(perms.manage_messages, "🗑️ 管理訊息")
        check(perms.embed_links, "🔗 嵌入連結")
        check(perms.attach_files, "📎 附加檔案")
        check(perms.mention_everyone, "🔔 提及 @everyone")
        check(perms.connect, "🔊 連接語音")
        check(perms.speak, "🎙️ 語音發言")
        check(perms.mute_members, "🔇 靜音成員")

        card = ZNCard(
            title=f"權限檢視 — {target_title}",
            description=f"在頻道 {ch.mention} 的權限狀態：\n\n" + "\n".join(perm_badges),
            status_pill=ZNStatusPill.MODERATION,
            color=target_obj.color if hasattr(target_obj, "color") and target_obj.color.value != 0 else ZNColor.INFO,
        )
        await InteractionResponder.safe_send(interaction, card=card)

    # --------------------------------------------------------------------------
    # 11. 頻道資訊 channelinfo
    # --------------------------------------------------------------------------
    @server_group.command(name="頻道資訊", description="檢視頻道的建立時間、主題說明與配置參數")
    @app_commands.describe(頻道="目標頻道 (預設當前頻道)")
    @command_guard("server")
    async def channel_info_command(
        self,
        interaction: discord.Interaction,
        頻道: Optional[discord.abc.GuildChannel] = None,
    ) -> None:
        ch = 頻道 or interaction.channel
        ch_name = getattr(ch, "name", "未知頻道")
        topic = getattr(ch, "topic", None) or "此頻道未填寫主題說明。"
        slowmode = getattr(ch, "slowmode_delay", 0)
        is_nsfw = getattr(ch, "is_nsfw", lambda: False)() if callable(getattr(ch, "is_nsfw", None)) else bool(getattr(ch, "is_nsfw", False))
        created_ts = int(ch.created_at.timestamp()) if hasattr(ch, "created_at") and ch.created_at else 0

        type_names = {
            discord.ChannelType.text: "文字頻道",
            discord.ChannelType.voice: "語音頻道",
            discord.ChannelType.stage_voice: "舞台頻道",
            discord.ChannelType.forum: "論壇頻道",
            discord.ChannelType.category: "分類目錄",
            discord.ChannelType.news: "公告頻道",
            discord.ChannelType.public_thread: "公開討論串",
            discord.ChannelType.private_thread: "私人討論串",
        }
        ch_type_str = type_names.get(getattr(ch, "type", None), "標準頻道")

        card = ZNCard(
            title=f"頻道資訊 — #{ch_name}",
            description=topic,
            status_pill=ZNStatusPill.TOOL,
            color=ZNColor.INFO,
        )
        card.add_section("🆔 頻道 ID", f"`{getattr(ch, 'id', 0)}`", inline=True)
        card.add_section("📑 頻道類型", f"`{ch_type_str}`", inline=True)
        if created_ts:
            card.add_section("📅 創立時間", f"<t:{created_ts}:F>", inline=True)

        if hasattr(ch, "category") and ch.category:
            card.add_section("📁 所屬分類", f"`{ch.category.name}`", inline=True)

        if hasattr(ch, "slowmode_delay"):
            card.add_section("⏱️ 慢速模式", f"`{slowmode} 秒`" if slowmode > 0 else "`關閉`", inline=True)

        if hasattr(ch, "bitrate"):
            card.add_section("🎙️ 語音位元率", f"`{ch.bitrate // 1000} kbps`", inline=True)
        if hasattr(ch, "user_limit"):
            card.add_section("👥 人數上限", f"`{ch.user_limit} 人`" if ch.user_limit else "`無上限`", inline=True)

        card.add_section("🔞 年齡限制 (NSFW)", f"`{'是' if is_nsfw else '否'}`", inline=True)
        await InteractionResponder.safe_send(interaction, card=card)

    # --------------------------------------------------------------------------
    # 12. 身分組資訊 roleinfo
    # --------------------------------------------------------------------------
    @server_group.command(name="身分組資訊", description="檢視身分組權限位元、色碼與階層成員數")
    @app_commands.describe(身分組="目標身分組")
    @command_guard("server")
    async def role_info_command(self, interaction: discord.Interaction, 身分組: discord.Role) -> None:
        card = ZNCard(
            title=f"身分組資訊 — @{身分組.name}",
            status_pill=ZNStatusPill.TOOL,
            color=身分組.color if 身分組.color.value != 0 else ZNColor.INFO,
        )
        created_ts = int(身分組.created_at.timestamp())
        card.add_section("🆔 身分組 ID", f"`{身分組.id}`", inline=True)
        card.add_section("🎨 顏色代碼", f"`{身分組.color}`", inline=True)
        card.add_section("👥 成員數量", f"`{len(身分組.members)} 人`", inline=True)
        card.add_section("🔝 階層順位", f"`第 {身分組.position} 位`", inline=True)
        card.add_section("📌 單獨列出", f"`{'是' if 身分組.hoist else '否'}`", inline=True)
        card.add_section("🔔 可被提及", f"`{'是' if 身分組.mentionable else '否'}`", inline=True)
        card.add_section("🤖 代管身分組", f"`{'是' if 身分組.managed else '否'}`", inline=True)
        card.add_section("📅 建立時間", f"<t:{created_ts}:F>", inline=True)

        key_perms: List[str] = []
        if 身分組.permissions.administrator:
            key_perms.append("管理員 (Administrator)")
        if 身分組.permissions.manage_guild:
            key_perms.append("管理伺服器")
        if 身分組.permissions.manage_roles:
            key_perms.append("管理身分組")
        if 身分組.permissions.manage_channels:
            key_perms.append("管理頻道")
        if 身分組.permissions.kick_members:
            key_perms.append("踢出成員")
        if 身分組.permissions.ban_members:
            key_perms.append("封鎖成員")
        if 身分組.permissions.moderate_members:
            key_perms.append("中斷成員通訊")

        card.add_section("🛡️ 核心特權", "、".join(key_perms) if key_perms else "普通成員權限", inline=False)
        await InteractionResponder.safe_send(interaction, card=card)

    # --------------------------------------------------------------------------
    # 13. 成員資訊 userinfo
    # --------------------------------------------------------------------------
    @server_group.command(name="成員資訊", description="檢視成員帳號註冊日、伺服器加入日與身分組")
    @app_commands.describe(成員="目標成員或使用者 (預設自己)")
    @command_guard("server")
    async def user_info_command(
        self,
        interaction: discord.Interaction,
        成員: Optional[Union[discord.Member, discord.User]] = None,
    ) -> None:
        target = 成員 or interaction.user
        created_ts = int(target.created_at.timestamp())
        avatar_url = target.display_avatar.url

        color = getattr(target, "color", None)
        card_color = color if (color and color.value != 0) else ZNColor.PRIMARY

        card = ZNCard(
            title=f"成員檔案 — {target.display_name}",
            description=f"全球使用者名稱：`{target.name}`",
            status_pill=ZNStatusPill.TOOL,
            color=card_color,
            thumbnail_url=avatar_url,
        )
        card.add_section("🆔 使用者 ID", f"`{target.id}`", inline=True)
        card.add_section("🤖 是否為機器人", f"`{'是' if target.bot else '否'}`", inline=True)
        card.add_section("📅 帳號註冊時間", f"<t:{created_ts}:F>\n(<t:{created_ts}:R>)", inline=True)

        if isinstance(target, discord.Member):
            if target.joined_at:
                joined_ts = int(target.joined_at.timestamp())
                card.add_section("📥 加入伺服器時間", f"<t:{joined_ts}:F>\n(<t:{joined_ts}:R>)", inline=True)

            top_role_text = target.top_role.mention if getattr(target, "top_role", None) else "@everyone"
            card.add_section("👑 最高身分組", top_role_text, inline=True)

            roles_list = [r.mention for r in target.roles if not r.is_default()]
            roles_text = " ".join(roles_list[:10]) if roles_list else "無自訂身分組"
            if len(roles_list) > 10:
                roles_text += f" *(等共 {len(roles_list)} 個)*"
            card.add_section("🛡️ 擁護身分組", roles_text, inline=False)

        flags = getattr(target, "public_flags", None)
        if flags:
            user_badges = [USER_FLAGS_MAP[k] for k, v in flags if v and k in USER_FLAGS_MAP]
            if user_badges:
                card.add_section("🏅 專屬社群徽章", "、".join(user_badges), inline=False)

        await InteractionResponder.safe_send(interaction, card=card)

    # --------------------------------------------------------------------------
    # 14. 升級加成 boosts
    # --------------------------------------------------------------------------
    @server_group.command(name="升級加成", description="檢視伺服器 Nitro Boost 等級與加成特權")
    @command_guard("server")
    async def boosts_command(self, interaction: discord.Interaction) -> None:
        g = interaction.guild
        sub_count = g.premium_subscription_count or 0
        tier = g.premium_tier

        perks = {
            0: "需要 2 次 Boost 解鎖等級 1 (+50 表情容量、128 kbps 語音位元率)",
            1: "已享有 128 kbps 語音位元率、100 個表情容量、720p 60fps 串流",
            2: "已享有 256 kbps 語音位元率、150 個表情容量、50MB 檔案上傳、伺服器橫幅",
            3: "已享有 384 kbps 語音位元率、250 個表情容量、100MB 檔案上傳、自訂邀請連結",
        }

        card = ZNCard(
            title=f"{g.name} — Nitro Boost 加成狀態",
            description=(
                f"- **當前等級**：`等級 {tier}`\n"
                f"- **Boost 總次數**：`{sub_count}` 次\n"
                f"- **音訊位元率上限**：`{g.bitrate_limit // 1000} kbps`\n"
                f"- **自訂表情上限**：`{g.emoji_limit}` 個\n"
                f"- **檔案上傳上限**：`{g.filesize_limit / (1024*1024):.0f} MB`\n\n"
                f"**🚀 當前等級特權說明**：\n{perks.get(tier, '最高等級全特權已解鎖')}"
            ),
            status_pill=ZNStatusPill.SYSTEM,
            color=discord.Color(0xF47FFF),
        )
        await InteractionResponder.safe_send(interaction, card=card)

    # --------------------------------------------------------------------------
    # 15. 排行榜 leaderboard
    # --------------------------------------------------------------------------
    @server_group.command(name="排行榜", description="檢視伺服器成員活躍度與點數財富排行榜")
    @command_guard("server")
    async def leaderboard_command(self, interaction: discord.Interaction) -> None:
        async with db.session() as session:
            stmt = select(EconomyWallet).order_by(desc(EconomyWallet.points)).limit(10)
            res = await session.execute(stmt)
            wallets = res.scalars().all()

        lines: List[str] = []
        medals = ["🥇", "🥈", "🥉", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟"]

        for idx, w in enumerate(wallets):
            medal = medals[idx] if idx < len(medals) else f"`#{idx+1}`"
            lines.append(f"{medal} <@{w.user_id}> — **{w.points:,}** 點數 (連續簽到: `{w.daily_streak}` 天)")

        desc_text = (
            "全伺服器虛擬點數與簽到先鋒榜單：\n\n" + "\n".join(lines)
            if lines
            else "目前尚無任何成員之點數錢包紀錄。成員可透過每日簽到與互動獲取虛擬點數！"
        )

        card = ZNCard(
            title=f"{interaction.guild.name} — 榮譽排行榜",
            description=desc_text,
            status_pill=ZNStatusPill.FUN,
            color=ZNColor.PRIMARY,
        )
        await InteractionResponder.safe_send(interaction, card=card)

    # --------------------------------------------------------------------------
    # 16. 頭像查詢 avatar
    # --------------------------------------------------------------------------
    @server_group.command(name="頭像", description="檢視成員或使用者的高解析度個人頭像與伺服器自訂頭像")
    @app_commands.describe(使用者="要檢視頭像的成員或使用者 (預設自己)", 顯示伺服器自訂頭像="若有伺服器專屬頭像是否優先展示 (預設是)")
    @command_guard("server")
    async def avatar_command(
        self,
        interaction: discord.Interaction,
        使用者: Optional[Union[discord.Member, discord.User]] = None,
        顯示伺服器自訂頭像: bool = True,
    ) -> None:
        target = 使用者 or interaction.user

        # Fetch member object if available in guild to check guild avatar
        target_member = interaction.guild.get_member(target.id) if interaction.guild else None
        guild_avatar = getattr(target_member, "guild_avatar", None) if target_member else None
        global_avatar = target.avatar

        # Determine which avatar to showcase as primary image
        chosen_asset = (guild_avatar if (guild_avatar and 顯示伺服器自訂頭像) else global_avatar) or target.display_avatar

        is_anim = chosen_asset.is_animated()
        formats = [
            f"[PNG]({chosen_asset.replace(format='png', size=1024).url})",
            f"[JPG]({chosen_asset.replace(format='jpeg', size=1024).url})",
            f"[WEBP]({chosen_asset.replace(format='webp', size=1024).url})",
        ]
        if is_anim:
            formats.append(f"[GIF]({chosen_asset.replace(format='gif', size=1024).url})")

        extra_links: List[str] = []
        if guild_avatar and global_avatar:
            if chosen_asset == guild_avatar:
                extra_links.append(f"• [檢視全域個人頭像]({global_avatar.with_size(1024).url})")
            else:
                extra_links.append(f"• [檢視伺服器專屬頭像]({guild_avatar.with_size(1024).url})")

        desc_lines = [
            f"**點擊下載 1024x1024 高畫質檔案**：\n{' • '.join(formats)}",
        ]
        if extra_links:
            desc_lines.extend(["", *extra_links])

        card = ZNCard(
            title=f"{target.display_name} 的頭像",
            description="\n".join(desc_lines),
            image_url=chosen_asset.with_size(1024).url,
            status_pill=ZNStatusPill.TOOL,
            color=target.color if hasattr(target, "color") and target.color.value != 0 else ZNColor.PRIMARY,
        )
        await InteractionResponder.safe_send(interaction, card=card)

    # --------------------------------------------------------------------------
    # 17. 成員橫幅 member_banner
    # --------------------------------------------------------------------------
    @server_group.command(name="成員橫幅", description="檢視指定成員或使用者之高畫質個人個人檔案橫幅 (Profile Banner)")
    @app_commands.describe(成員="要檢視橫幅的成員或使用者 (預設自己)")
    @command_guard("server")
    async def member_banner_command(
        self,
        interaction: discord.Interaction,
        成員: Optional[Union[discord.Member, discord.User]] = None,
    ) -> None:
        target = 成員 or interaction.user
        try:
            fetched_user = await self.bot.fetch_user(target.id)
        except Exception:
            fetched_user = target

        banner = getattr(fetched_user, "banner", None)
        if not banner:
            accent = getattr(fetched_user, "accent_color", None)
            accent_str = f"`{accent}`" if accent else "無 (預設透明/暗色)"
            card = ZNCard(
                title=f"{target.display_name} — 個人檔案橫幅",
                description=f"成員 **{target.display_name}** 尚未配置個人檔案自訂橫幅 (Profile Banner)。\n- **個人代表色彩代碼**：{accent_str}",
                thumbnail_url=target.display_avatar.url,
                status_pill=ZNStatusPill.INFO,
                color=accent or ZNColor.PRIMARY,
            )
            await InteractionResponder.safe_send(interaction, card=card, ephemeral=True)
            return

        is_anim = banner.is_animated()
        formats = [
            f"[PNG]({banner.replace(format='png', size=1024).url})",
            f"[JPG]({banner.replace(format='jpeg', size=1024).url})",
            f"[WEBP]({banner.replace(format='webp', size=1024).url})",
        ]
        if is_anim:
            formats.append(f"[GIF]({banner.replace(format='gif', size=1024).url})")

        img_url = banner.with_size(1024).url
        card = ZNCard(
            title=f"{target.display_name} — 個人檔案橫幅",
            description=f"下載原始 1024px 高解析度橫幅：\n{' • '.join(formats)}",
            image_url=img_url,
            thumbnail_url=target.display_avatar.url,
            status_pill=ZNStatusPill.TOOL,
            color=target.color if hasattr(target, "color") and target.color.value != 0 else ZNColor.PRIMARY,
        )
        await InteractionResponder.safe_send(interaction, card=card)

    # ==========================================================================
    # 頻道情境洞察與情資分析指令群組 /頻道
    # ==========================================================================
    channel_group = app_commands.Group(name="頻道", description="Discord 頻道資訊、發言統計與 AI 歷史摘要", guild_only=True)

    @channel_group.command(name="摘要", description="透過 AI 統整特定時間區間或最近的頻道聊天話題與焦點")
    @app_commands.describe(
        從何時開始="例如: 20:03、今天 20:00、1小時前 (留空表示最近訊息)",
        數量="讀取訊息筆數 (預設 80，上限 200)",
        目標頻道="目標文字頻道 (預設當前頻道)",
    )
    @command_guard("server")
    async def channel_summary_command(
        self,
        interaction: discord.Interaction,
        從何時開始: Optional[str] = None,
        數量: Optional[int] = 80,
        目標頻道: Optional[discord.TextChannel] = None,
    ) -> None:
        await InteractionResponder.safe_defer(interaction, ephemeral=False)
        target_ch = 目標頻道 or interaction.channel
        ch_name = getattr(target_ch, "name", "未知頻道")

        after_dt = None
        filter_label = "最近聊天訊息"
        if 從何時開始 and 從何時開始.strip():
            after_dt, filter_label = parse_channel_time_filter(從何時開始.strip())
            if not after_dt:
                filter_label = f"時間解析略過 ({從何時開始})"

        fetch_limit = min(max(數量 or 80, 10), 200)
        bot_user_id = self.bot.user.id if self.bot and self.bot.user else None
        msgs, err = await channel_inspector.fetch_channel_messages(
            channel=target_ch,
            after=after_dt,
            limit=fetch_limit,
            bot_user_id=bot_user_id,
        )
        if err:
            card = ZNCard(
                title="⚠️ 頻道訊息讀取失敗",
                description=err,
                status_pill=ZNStatusPill.ERROR,
                color=ZNColor.ERROR,
            )
            await InteractionResponder.safe_send(interaction, card=card)
            return

        if not msgs:
            card = ZNCard(
                title=f"📋 頻道歷史摘要 — #{ch_name}",
                description=f"在時間條件 **{filter_label}** 之後未找到任何新的聊天訊息。",
                status_pill=ZNStatusPill.INFO,
                color=ZNColor.INFO,
            )
            await InteractionResponder.safe_send(interaction, card=card)
            return

        transcript = channel_inspector.format_messages_to_transcript(msgs, max_chars=6000)

        prompt = (
            f"以下是 Discord 伺服器頻道 #{ch_name} 在「{filter_label}」區間內的 {len(msgs)} 則真實對話記錄：\n\n"
            f"{transcript}\n\n"
            f"請以繁體中文（臺灣），為伺服器群友整理一份清晰、生動、重點分明的「頻道話題統整」：\n"
            f"1. 【核心話題總結】：大家主要在討論什麼？\n"
            f"2. 【焦點討論事項與結論】：有哪些關鍵對話、爭端、結論或共識？\n"
            f"3. 【活躍成員與重要發言節錄】：有哪些重要發言者提到了值得注意的內容？\n"
            f"口吻保持開朗親切、專業客觀且條理分明，禁止機械模板句。"
        )

        try:
            ai_res, _ = await ai_gateway.generate_response(
                system_instruction="你是一個專精於社群情境洞察與聊天記錄摘要的 Discord 旗艦助手。",
                messages=[{"role": "user", "content": prompt}],
                allow_tools=False,
            )
            summary_text = ai_res.text
        except Exception as e:
            summary_text = f"AI 摘要運算暫時遭遇波動：{e}\n以下提供讀取之訊息數量：{len(msgs)} 則。"

        card = ZNCard(
            title=f"📋 頻道情境脈絡摘要 — #{ch_name}",
            description=summary_text,
            status_pill=ZNStatusPill.AI,
            color=ZNColor.PRIMARY,
        )
        card.add_section("⏱️ 檢索範圍", f"`{filter_label}`（共讀取 {len(msgs)} 則訊息）", inline=True)
        card.add_section("💬 目標頻道", f"<#{getattr(target_ch, 'id', 0)}>", inline=True)
        await InteractionResponder.safe_send(interaction, card=card)

    @channel_group.command(name="統計", description="統計頻道成員發言之王排行榜、字數比例與活躍概況")
    @app_commands.describe(
        時間區間="例如: 今天、20:03、2小時前 (留空表示最近 150 則)",
        目標頻道="目標文字頻道 (預設當前頻道)",
    )
    @command_guard("server")
    async def channel_stats_command(
        self,
        interaction: discord.Interaction,
        時間區間: Optional[str] = None,
        目標頻道: Optional[discord.TextChannel] = None,
    ) -> None:
        await InteractionResponder.safe_defer(interaction, ephemeral=False)
        target_ch = 目標頻道 or interaction.channel
        ch_name = getattr(target_ch, "name", "未知頻道")

        after_dt = None
        filter_label = "最近 150 則訊息"
        if 時間區間 and 時間區間.strip():
            after_dt, filter_label = parse_channel_time_filter(時間區間.strip())

        bot_user_id = self.bot.user.id if self.bot and self.bot.user else None
        msgs, err = await channel_inspector.fetch_channel_messages(
            channel=target_ch,
            after=after_dt,
            limit=150,
            bot_user_id=bot_user_id,
        )
        if err:
            card = ZNCard(
                title="⚠️ 統計失敗",
                description=err,
                status_pill=ZNStatusPill.ERROR,
                color=ZNColor.ERROR,
            )
            await InteractionResponder.safe_send(interaction, card=card)
            return

        stats = channel_inspector.compute_channel_activity_stats(msgs, channel_name=ch_name)

        card = ZNCard(
            title=f"📊 頻道成員發言活躍度大盤 — #{ch_name}",
            description=f"統計區間：**{filter_label}**（有效時間軸：`{stats.get('time_span', '無')}`）",
            status_pill=ZNStatusPill.TOOL,
            color=ZNColor.SUCCESS,
        )
        card.add_section("💬 總訊息量", f"`{stats['total_messages']} 則`", inline=True)
        card.add_section("✍️ 總字數統計", f"`{stats['total_characters']:,} 字`", inline=True)
        card.add_section("👥 參與人數", f"`{stats['unique_authors_count']} 人`", inline=True)

        top_speakers = stats.get("top_speakers", [])
        if top_speakers:
            medals = ["🥇", "🥈", "🥉", "4️⃣", "5️⃣"]
            rank_lines = []
            for sp in top_speakers[:5]:
                m_icon = medals[sp["rank"] - 1] if sp["rank"] <= len(medals) else f"{sp['rank']}."
                bot_str = " `[BOT]`" if sp.get("is_bot") else ""
                rank_lines.append(
                    f"{m_icon} **{sp['name']}**{bot_str} — `{sp['message_count']} 則` ({sp['percentage']}%) · `{sp['character_count']} 字`"
                )
            card.add_section("🏆 發言之王排行榜 (Top 5)", "\n".join(rank_lines), inline=False)

        if stats.get("attachment_count", 0) > 0:
            card.add_section("📷 圖片與附件分享", f"共上傳 `{stats['attachment_count']}` 個多媒體檔案", inline=True)

        await InteractionResponder.safe_send(interaction, card=card)

    @channel_group.command(name="總覽", description="檢視頻道全方位情資、主題說明與活躍討論串")
    @app_commands.describe(目標頻道="目標頻道 (預設當前頻道)")
    @command_guard("server")
    async def channel_full_info_command(
        self,
        interaction: discord.Interaction,
        目標頻道: Optional[discord.abc.GuildChannel] = None,
    ) -> None:
        target_ch = 目標頻道 or interaction.channel
        details = channel_inspector.get_channel_overview_details(target_ch)

        card = ZNCard(
            title=f"📑 頻道全方位情資 — #{details['channel_name']}",
            description=f"**頻道主題**：\n{details['topic']}",
            status_pill=ZNStatusPill.TOOL,
            color=ZNColor.INFO,
        )
        card.add_section("🆔 頻道 ID", f"`{details['channel_id']}`", inline=True)
        card.add_section("📁 所屬分類", f"`{details['category_name']}`", inline=True)
        card.add_section("📅 創立時間", f"`{details['created_at']}`", inline=True)

        slowmode_sec = details['slowmode_delay']
        slowmode_str = f"{slowmode_sec} 秒" if slowmode_sec > 0 else "關閉"
        card.add_section("⏱️ 慢速模式", f"`{slowmode_str}`", inline=True)
        card.add_section("🔞 年齡限制 (NSFW)", f"`{'是' if details['is_nsfw'] else '否'}`", inline=True)
        card.add_section("🧵 活躍討論串", f"`{details['active_threads_count']} 個`", inline=True)

        threads_sample = details.get("active_threads_sample", [])
        if threads_sample:
            card.add_section("💬 熱門討論串列表", "\n".join(threads_sample), inline=False)

        await InteractionResponder.safe_send(interaction, card=card)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(ServerCog(bot))
