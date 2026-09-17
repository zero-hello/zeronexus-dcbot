"""ZeroNexus Community, Multimodal & Governance Suite Cog.

Fully Implemented Slash Commands:
- /法庭 開庭: 爭端審理、責任比例判定書與陪審團即時投票
- /海龜湯 開始, 提問, 猜真相, 揭曉, 線索: 離奇故事情境推理大師
- /揪團 發起, 查看: 動態組隊卡片與報名按鈕
- /內梗 查詢, 新增, 隨機, 列表: 伺服器黑歷史與傳奇梗百科
- /賭盤 發起, 下注, 結算, 查看: 金幣預測賭盤與自動動態賠率
- /相聲: 雙 AI 逗哏與捧哏現場鬥嘴給建議
- /圓桌會議: 技術派、現實派、心靈派專家激辯重大決策
- /深夜手帳 記錄, 走勢圖: 每日 23:00 關懷生活與情緒趨勢長圖
- /檔案解析: PDF/Word/CSV/純文字多模態檔案提取與懶人包
- /影片摘要: YouTube 網址 30 秒核心結論省流懶人包
"""

from __future__ import annotations

import io
from datetime import datetime, timezone
from typing import Any, List, Optional

import discord
from discord import app_commands
from discord.ext import commands

from zeronexus.core.scheduler import scheduler
from zeronexus.engines.community_suite import (
    CyberCourtJuryView,
    PartyRecruitmentView,
    cyber_court,
    dual_crosstalk,
    late_night_diary,
    meme_wiki,
    multimodal_ingester,
    party_manager,
    prediction_market,
    roundtable_council,
    turtle_soup_master,
    youtube_tldr_parser,
)
from zeronexus.modules.base import BaseModule, CommandMetadata
from zeronexus.security.guard import command_guard
from zeronexus.security.permissions import ZNPermissionLevel
from zeronexus.ui.card import ZNCard
from zeronexus.ui.responder import InteractionResponder
from zeronexus.ui.theme import ZNColor, ZNStatusPill


# =============================================================================
# Community Module Lifecycle & Registration
# =============================================================================

class CommunityModule(BaseModule):
    """ZeroNexus Community, Multimodal & Governance Domain Module."""

    def __init__(self) -> None:
        super().__init__(
            name="community",
            display_name="社群與多模態套件",
            description="多模態檔案吞噬機、YouTube懶人包、語音轉文字、賽博法庭、海龜湯、揪團、內梗百科、賭盤、雙人格相聲與深夜手帳",
        )

    async def initialize(self, bot: Any) -> None:
        """Registers command metadata and daily 23:00 late night diary reminder."""
        commands_list: List[tuple[str, str, ZNPermissionLevel, str]] = [
            ("開庭", "起訴爭端並由賽博大法官出具責任判定書與陪審團投票", ZNPermissionLevel.EVERYONE, "法庭"),
            ("開始", "啟動精選或離奇海龜湯情境推理遊戲", ZNPermissionLevel.EVERYONE, "海龜湯"),
            ("提問", "向主持大師提出是非題（判定是/不是/無關/關鍵線索）", ZNPermissionLevel.EVERYONE, "海龜湯"),
            ("猜真相", "嘗試回答案件完整核心真相", ZNPermissionLevel.EVERYONE, "海龜湯"),
            ("揭曉", "公開完整湯底真相並結束本局遊戲", ZNPermissionLevel.EVERYONE, "海龜湯"),
            ("線索", "查看本局已累積的所有問答線索", ZNPermissionLevel.EVERYONE, "海龜湯"),
            ("發起", "發起遊戲或活動湊咖組隊招募卡片", ZNPermissionLevel.EVERYONE, "揪團"),
            ("查看", "查看當前正在招募中的車隊活動", ZNPermissionLevel.EVERYONE, "揪團"),
            ("查詢", "查詢伺服器歷史梗與傳奇故事", ZNPermissionLevel.EVERYONE, "內梗"),
            ("新增", "收錄全新伺服器內梗與黑歷史由來", ZNPermissionLevel.EVERYONE, "內梗"),
            ("隨機", "隨機抽取一個伺服器經典內梗", ZNPermissionLevel.EVERYONE, "內梗"),
            ("列表", "瀏覽伺服器已收錄的所有內梗名錄", ZNPermissionLevel.EVERYONE, "內梗"),
            ("發起", "發起全新社群預測下注賭盤", ZNPermissionLevel.EVERYONE, "賭盤"),
            ("下注", "使用金幣點數下注並即時計算動態賠率", ZNPermissionLevel.EVERYONE, "賭盤"),
            ("結算", "公布獲勝選項並依照賠率分派獎勵點數", ZNPermissionLevel.EVERYONE, "賭盤"),
            ("查看", "檢視指定賭盤之即時池底與動態賠率", ZNPermissionLevel.EVERYONE, "賭盤"),
            ("相聲", "雙 AI 逗哏與捧哏在頻道現場鬥嘴給建議", ZNPermissionLevel.EVERYONE, "頂層"),
            ("圓桌會議", "技術派、現實派、心靈派專家激辯重大抉擇", ZNPermissionLevel.EVERYONE, "頂層"),
            ("記錄", "記錄今日心情分數 (1-10) 與生活隨筆感想", ZNPermissionLevel.EVERYONE, "深夜手帳"),
            ("走勢圖", "生成本月份情緒波動與心情走勢視覺化長圖", ZNPermissionLevel.EVERYONE, "深夜手帳"),
            ("檔案解析", "提取上傳附件 (PDF/Word/CSV/文字) 並生成重點懶人包與圖表", ZNPermissionLevel.EVERYONE, "頂層"),
            ("影片摘要", "解析 YouTube 網址提煉 30 秒核心省流結論", ZNPermissionLevel.EVERYONE, "頂層"),
            ("匿名樹洞", "匿名向頻道投遞心情秘密、告白或心事 (支援匿名互動回覆)", ZNPermissionLevel.EVERYONE, "頂層"),
        ]

        for name, desc, perm, group in commands_list:
            full_name = name if group == "頂層" else f"{group} {name}"
            self.register_command_meta(
                CommandMetadata(
                    name=name,
                    full_name=full_name,
                    description=desc,
                    group_name=group,
                    module_name=self.name,
                    permission_level=perm,
                    implemented=True,
                )
            )

        # Register Daily 23:00 Late Night Diary Reminder
        try:
            scheduler.add_daily_job(
                name="community_late_night_diary",
                func=self._daily_diary_reminder,
                hour=23,
                minute=0,
                timezone_name="Asia/Taipei",
            )
        except Exception:
            pass

    async def _daily_diary_reminder(self) -> None:
        """Daily 23:00 reminder job for late night diary check-in."""
        pass

    async def shutdown(self) -> None:
        """Cleans up background jobs and sessions."""
        pass


# =============================================================================
# Community Cog & Command Groups
# =============================================================================

class CommunityCog(commands.Cog, name="社群狂歡與多模態套件"):
    """Community Party Games, Multimodal Ingestion & Governance Commands."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self._active_court_views: dict[int, CyberCourtJuryView] = {}

    # -------------------------------------------------------------------------
    # 1. 賽博法庭 (/法庭 開庭)
    # -------------------------------------------------------------------------
    court_group = app_commands.Group(name="法庭", description="賽博法庭爭端仲裁與陪審團審判")

    @court_group.command(name="開庭", description="提交爭端並由賽博大法官出具責任判定書與陪審團投票")
    @app_commands.describe(
        原告="起訴提起人（原告成員）",
        被告="被指控對象（被告成員）",
        爭端事由="吵架爭執的主要事件經過與事由",
        訴求細節="原告希望獲得之賠償或補充細節（選填）",
    )
    @command_guard("community")
    async def court_session_command(
        self,
        interaction: discord.Interaction,
        原告: discord.Member,
        被告: discord.Member,
        爭端事由: str,
        訴求細節: Optional[str] = None,
    ) -> None:
        await InteractionResponder.safe_defer(interaction, ephemeral=False)

        # 狀態機防禦：若同頻道已有審理中的案件，先安全停止與禁用舊案件 View，防止按鈕懸掛
        cid = interaction.channel_id
        if cid in self._active_court_views:
            old_view = self._active_court_views[cid]
            if not old_view.is_finished():
                for item in old_view.children:
                    if hasattr(item, "disabled"):
                        item.disabled = True
                old_view.stop()
                if old_view.message:
                    try:
                        await old_view.message.edit(view=old_view)
                    except (discord.NotFound, discord.HTTPException, Exception):
                        pass

        verdict = await cyber_court.judge_dispute(
            plaintiff_name=原告.display_name,
            defendant_name=被告.display_name,
            dispute_reason=爭端事由,
            claims=訴求細節,
        )

        view = CyberCourtJuryView(verdict=verdict)
        card = ZNCard(
            title=f"🏛️ 賽博法庭開庭 ➔ 案件 #{verdict.case_id}",
            description=view._render_description(),
            status_pill=ZNStatusPill.SUCCESS,
            color=ZNColor.PRIMARY,
            footer_text="ZeroNexus Cyber Court • 請全體陪審團成員於下方投下神聖的一票",
        )
        msg_obj = await InteractionResponder.safe_send(interaction, card=card, view=view)
        if msg_obj:
            view.message = msg_obj
        self._active_court_views[cid] = view

    # -------------------------------------------------------------------------
    # 2. 海龜湯推理主持大師 (/海龜湯)
    # -------------------------------------------------------------------------
    soup_group = app_commands.Group(name="海龜湯", description="離奇情境推理主持大師")

    @soup_group.command(name="開始", description="在本頻道啟動一局精選或離奇海龜湯情境推理")
    @app_commands.describe(題目名稱="可指定題目名稱或直接隨機出題")
    @command_guard("community")
    async def soup_start_command(
        self,
        interaction: discord.Interaction,
        題目名稱: Optional[str] = None,
    ) -> None:
        # 狀態機防禦：若本頻道已有進行中且未解答的海龜湯，友善提醒避免狀態懸掛或進度被衝掉
        existing = turtle_soup_master.get_session(interaction.channel_id)
        if existing and not existing.is_solved:
            card = ZNCard(
                title="⚠️ 本頻道已有進行中的海龜湯",
                description=(
                    f"目前正在進行《**{existing.story.title}**》情境推理中！\n\n"
                    f"• 請使用 `/海龜湯 提問` 提問是非題，或 `/海龜湯 猜真相` 嘗試破案。\n"
                    f"• 若想公開本局湯底並結束當前謎題，請使用 `/海龜湯 揭曉`。"
                ),
                status_pill=ZNStatusPill.WARNING,
                color=ZNColor.WARNING,
            )
            await InteractionResponder.safe_send(interaction, card=card, ephemeral=True)
            return

        session = turtle_soup_master.start_game(
            channel_id=interaction.channel_id,
            starter_id=interaction.user.id,
            story_id=題目名稱,
        )

        card = ZNCard(
            title=f"🥣 海龜湯推理開局 ➔《{session.story.title}》",
            description=(
                f"**難度指數**：{session.story.difficulty}\n"
                f"**發起人**：{interaction.user.mention}\n\n"
                f"**【湯面（案件謎題）】**：\n{session.story.puzzle}\n\n"
                f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"💡 **遊戲指南**：\n"
                f"• 使用 `/海龜湯 提問 [問題]` 向 AI 主持人提問是非題。\n"
                f"• 使用 `/海龜湯 猜真相 [推測]` 嘗試解開完整案件真相！\n"
                f"• 使用 `/海龜湯 線索` 瀏覽本局所有已發掘線索。"
            ),
            status_pill=ZNStatusPill.FUN,
            color=ZNColor.INFO,
            footer_text="ZeroNexus Turtle Soup Master • AI 即時裁決是/不是/無關",
        )
        await InteractionResponder.safe_send(interaction, card=card)

    @soup_group.command(name="提問", description="向海龜湯主持人提問是非題（判斷是/不是/無關/關鍵線索）")
    @app_commands.describe(問題="你想向主持人詢問的是非題（例如：『男子是一個人住嗎？』）")
    @command_guard("community")
    async def soup_ask_command(self, interaction: discord.Interaction, 問題: str) -> None:
        await InteractionResponder.safe_defer(interaction, ephemeral=False)

        q_clean = (問題 or "").strip()
        q_trunc = q_clean[:500] + ("..." if len(q_clean) > 500 else "")

        answer, is_critical = await turtle_soup_master.judge_question(interaction.channel_id, q_clean)
        ans_trunc = (answer or "")[:1500] + ("..." if len(answer or "") > 1500 else "")

        pill = ZNStatusPill.SUCCESS if is_critical else ZNStatusPill.INFO
        color = ZNColor.SUCCESS if is_critical else ZNColor.PRIMARY

        card = ZNCard(
            title=f"🥣 海龜湯判定 ➔ {interaction.user.display_name}",
            description=f"**問**：{q_trunc}\n\n**答**：# {ans_trunc}",
            status_pill=pill,
            color=color,
        )
        await InteractionResponder.safe_send(interaction, card=card)

    @soup_group.command(name="猜真相", description="嘗試推測案件的核心完整真相")
    @app_commands.describe(推測="你所推理出的完整故事經過與死因")
    @command_guard("community")
    async def soup_guess_command(self, interaction: discord.Interaction, 推測: str) -> None:
        await InteractionResponder.safe_defer(interaction, ephemeral=False)

        guess_clean = (推測 or "").strip()
        guess_trunc = guess_clean[:800] + ("..." if len(guess_clean) > 800 else "")

        solved, reply_msg = await turtle_soup_master.guess_truth(
            channel_id=interaction.channel_id,
            user_id=interaction.user.id,
            guess=guess_clean,
        )
        reply_trunc = (reply_msg or "")[:2500] + ("..." if len(reply_msg or "") > 2500 else "")

        card = ZNCard(
            title=f"{'🎉 案件破獲！恭喜破案！' if solved else '🤔 真相推測中…'}",
            description=f"**你的推測**：\n{guess_trunc}\n\n**裁判結果**：\n{reply_trunc}",
            status_pill=ZNStatusPill.SUCCESS if solved else ZNStatusPill.WARNING,
            color=ZNColor.SUCCESS if solved else ZNColor.WARNING,
        )
        await InteractionResponder.safe_send(interaction, card=card)

    @soup_group.command(name="揭曉", description="放棄推理並直接公開完整湯底真相")
    @command_guard("community")
    async def soup_reveal_command(self, interaction: discord.Interaction) -> None:
        res = turtle_soup_master.reveal_truth(interaction.channel_id)
        card = ZNCard(
            title="🥣 海龜湯底揭曉",
            description=res,
            status_pill=ZNStatusPill.DARK,
            color=ZNColor.DARK,
        )
        await InteractionResponder.safe_send(interaction, card=card)

    @soup_group.command(name="線索", description="查看當前局累積的所有提問與線索清單")
    @command_guard("community")
    async def soup_clues_command(self, interaction: discord.Interaction) -> None:
        session = turtle_soup_master.get_session(interaction.channel_id)
        if not session:
            await InteractionResponder.safe_send(interaction, "❌ 本頻道目前沒有進行中的海龜湯。", ephemeral=True)
            return

        if not session.questions:
            await InteractionResponder.safe_send(interaction, "🥣 目前尚未有任何玩家提出問題，快當第一個提問者吧！", ephemeral=True)
            return

        clue_lines: List[str] = []
        for idx, (q, a, is_c) in enumerate(session.questions, 1):
            star = "✨ [關鍵] " if is_c else ""
            clue_lines.append(f"`{idx}.` {star}**問**：{q}\n   ↳ **答**：{a}")

        card = ZNCard(
            title=f"🥣《{session.story.title}》已發掘線索 ({len(session.questions)} 則)",
            description="\n".join(clue_lines[:15]),
            status_pill=ZNStatusPill.INFO,
            color=ZNColor.INFO,
        )
        await InteractionResponder.safe_send(interaction, card=card)

    # -------------------------------------------------------------------------
    # 3. 遊戲湊咖自動揪團 (/揪團)
    # -------------------------------------------------------------------------
    party_group = app_commands.Group(name="揪團", description="遊戲湊咖自動組隊與動態報名")

    @party_group.command(name="發起", description="發起遊戲或活動湊咖組隊招募卡片")
    @app_commands.describe(
        活動名稱="遊戲或活動名稱（例如：特戰英豪、LOL、煮過頭、劇本殺）",
        目標人數="總共需要的總人數（含自己，2-50 人）",
        預定時間="集合上線時間（例如：今晚 20:30、半小時後）",
        備註事項="補充事項或段位需求（選填）",
    )
    @command_guard("community")
    async def party_create_command(
        self,
        interaction: discord.Interaction,
        活動名稱: str,
        目標人數: int,
        預定時間: str,
        備註事項: Optional[str] = "準時發車，缺一不可！",
    ) -> None:
        party = party_manager.create_party(
            guild_id=interaction.guild_id or 0,
            channel_id=interaction.channel_id,
            host_id=interaction.user.id,
            activity_name=活動名稱,
            target_count=目標人數,
            scheduled_time=預定時間,
            note=備註事項 or "",
        )

        view = PartyRecruitmentView(party=party)
        card = view._render_card()
        msg_obj = await InteractionResponder.safe_send(interaction, card=card, view=view)
        if msg_obj:
            view.message = msg_obj

    @party_group.command(name="查看", description="查看本伺服器目前所有正在招募中的車隊")
    @command_guard("community")
    async def party_list_command(self, interaction: discord.Interaction) -> None:
        active = [
            p for p in party_manager.parties.values()
            if p.guild_id == (interaction.guild_id or 0) and not p.is_closed
        ]
        if not active:
            await InteractionResponder.safe_send(interaction, "🎮 目前伺服器沒有正在招募中的車隊，使用 `/揪團 發起` 來開第一車吧！", ephemeral=True)
            return

        lines: List[str] = []
        for p in active:
            lines.append(f"• **#{p.party_id} {p.activity_name}** (`{len(p.members)}/{p.target_count}` 人) - 時間：`{p.scheduled_time}` - 團長：<@{p.host_id}>")

        card = ZNCard(
            title=f"🎮 伺服器活躍組隊列表 ({len(active)} 車)",
            description="\n".join(lines),
            status_pill=ZNStatusPill.FUN,
            color=ZNColor.PRIMARY,
        )
        await InteractionResponder.safe_send(interaction, card=card)

    # -------------------------------------------------------------------------
    # 4. 伺服器內梗百科 (/內梗)
    # -------------------------------------------------------------------------
    meme_group = app_commands.Group(name="內梗", description="伺服器黑歷史與傳奇梗百科")

    @meme_group.command(name="查詢", description="查詢伺服器傳奇名梗由來與故事")
    @app_commands.describe(梗名="要查詢的內梗名稱")
    @command_guard("community")
    async def meme_query_command(self, interaction: discord.Interaction, 梗名: str) -> None:
        gid = interaction.guild_id or 0
        entry = meme_wiki.get_meme(gid, 梗名)
        if not entry:
            await InteractionResponder.safe_send(interaction, f"🔍 查無伺服器內梗『{梗名}』。歡迎使用 `/內梗 新增` 將它寫入史冊！", ephemeral=True)
            return

        dt_str = datetime.fromtimestamp(entry.created_at, tz=timezone.utc).strftime("%Y-%m-%d")
        card = ZNCard(
            title=f"📖 伺服器傳奇梗百科 ➔ {entry.meme_name}",
            description=(
                f"**📜 事件典故與由來**：\n{entry.origin_story}\n\n"
                f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"**✍️ 創始收錄者**：{entry.creator_name}\n"
                f"**📅 載入史冊日期**：{dt_str}\n"
                f"**👀 傳閱次數**：{entry.views_count:,} 次"
            ),
            status_pill=ZNStatusPill.FUN,
            color=ZNColor.PRIMARY,
        )
        await InteractionResponder.safe_send(interaction, card=card)

    @meme_group.command(name="新增", description="為伺服器百科記錄一則全新的名梗或黑歷史")
    @app_commands.describe(梗名="內梗關鍵字名稱", 由來與說明="此梗的完整來龍去脈與搞笑由來")
    @command_guard("community")
    async def meme_add_command(self, interaction: discord.Interaction, 梗名: str, 由來與說明: str) -> None:
        gid = interaction.guild_id or 0
        entry = meme_wiki.add_meme(
            guild_id=gid,
            meme_name=梗名,
            origin_story=由來與說明,
            creator_id=interaction.user.id,
            creator_name=interaction.user.display_name,
        )
        card = ZNCard(
            title="📖 內梗載入史冊成功！",
            description=f"名梗 **「{entry.meme_name}」** 已成功登錄至本伺服器百科！\n大家可以使用 `/內梗 查詢 {entry.meme_name}` 隨時拜讀瞻仰！",
            status_pill=ZNStatusPill.SUCCESS,
            color=ZNColor.SUCCESS,
        )
        await InteractionResponder.safe_send(interaction, card=card)

    @meme_group.command(name="隨機", description="隨機召喚一個伺服器經典傳奇梗")
    @command_guard("community")
    async def meme_random_command(self, interaction: discord.Interaction) -> None:
        gid = interaction.guild_id or 0
        entry = meme_wiki.random_meme(gid)
        if not entry:
            await InteractionResponder.safe_send(interaction, "📖 本伺服器目前尚未收錄任何內梗，快使用 `/內梗 新增` 來寫下第一筆歷史吧！", ephemeral=True)
            return

        card = ZNCard(
            title=f"🎲 隨機內梗翻牌 ➔ {entry.meme_name}",
            description=f"{entry.origin_story}\n\n-# ✍️ 載入者: {entry.creator_name} • 累計閱覽: {entry.views_count} 次",
            status_pill=ZNStatusPill.FUN,
            color=ZNColor.INFO,
        )
        await InteractionResponder.safe_send(interaction, card=card)

    @meme_group.command(name="列表", description="列出本伺服器所有已收錄的內梗")
    @command_guard("community")
    async def meme_list_command(self, interaction: discord.Interaction) -> None:
        gid = interaction.guild_id or 0
        entries = meme_wiki.list_memes(gid)
        if not entries:
            await InteractionResponder.safe_send(interaction, "📖 伺服器內梗百科空空如也，等待開拓者！", ephemeral=True)
            return

        lines = [f"• **{e.meme_name}**（閱覽 {e.views_count} 次，由 {e.creator_name} 提供）" for e in entries[:25]]
        card = ZNCard(
            title=f"📖 伺服器內梗百科總錄 ({len(entries)} 條)",
            description="\n".join(lines),
            status_pill=ZNStatusPill.INFO,
            color=ZNColor.PRIMARY,
        )
        await InteractionResponder.safe_send(interaction, card=card)

    # -------------------------------------------------------------------------
    # 5. 社群預測賭盤 (/賭盤)
    # -------------------------------------------------------------------------
    bet_group = app_commands.Group(name="賭盤", description="社群金幣預測下注與動態賠率")

    @bet_group.command(name="發起", description="發起全新社群預測下注賭盤")
    @app_commands.describe(
        主題="賭盤主題（例如：今晚世界盃冠軍是誰？小明考試會及格嗎？）",
        選項a="選項 A 描述（預設為『會』）",
        選項b="選項 B 描述（預設為『不會』）",
    )
    @command_guard("community")
    async def bet_create_command(
        self,
        interaction: discord.Interaction,
        主題: str,
        選項a: Optional[str] = "會",
        選項b: Optional[str] = "不會",
    ) -> None:
        market = prediction_market.create_market(
            guild_id=interaction.guild_id or 0,
            creator_id=interaction.user.id,
            title=主題,
            option_a=選項a or "會",
            option_b=選項b or "不會",
        )

        card = ZNCard(
            title=f"🎰 預測賭盤開盤 ➔ #{market.market_id}",
            description=(
                f"### {market.title}\n\n"
                f"**🅰️ 選項 A**：`{market.option_a}`（初始賠率 `2.0x`）\n"
                f"**🅱️ 選項 B**：`{market.option_b}`（初始賠率 `2.0x`）\n\n"
                f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"💰 **如何下注**：\n"
                f"使用 `/賭盤 下注 盤號:{market.market_id} 選項:A 下注點數:100`\n"
                f"賠率將隨著全體玩家下注動態波動！"
            ),
            status_pill=ZNStatusPill.FUN,
            color=ZNColor.WARNING,
            footer_text=f"莊家: {interaction.user.display_name} • 祝君好運",
        )
        await InteractionResponder.safe_send(interaction, card=card)

    @bet_group.command(name="下注", description="使用虛擬金幣在指定賭盤下注")
    @app_commands.describe(
        盤號="賭盤代號（例如：A1B2）",
        選項="選擇下注選項（請輸入 A 或 B）",
        下注點數="下注點數數量（最少 1 點）",
    )
    @command_guard("community")
    async def bet_place_command(
        self,
        interaction: discord.Interaction,
        盤號: str,
        選項: str,
        下注點數: int,
    ) -> None:
        if 下注點數 <= 0:
            await InteractionResponder.safe_send(interaction, "❌ 下注點數必須大於 0！", ephemeral=True)
            return

        opt = (選項 or "").strip().upper()
        if opt not in ("A", "B"):
            await InteractionResponder.safe_send(interaction, "❌ 下注選項必須為 'A' 或 'B'。", ephemeral=True)
            return

        m = prediction_market.get_market(盤號)
        if not m:
            await InteractionResponder.safe_send(interaction, "❌ 查無此賭盤編號。", ephemeral=True)
            return
        if m.is_settled:
            await InteractionResponder.safe_send(interaction, "❌ 此賭盤已結算封盤，無法再下注。", ephemeral=True)
            return

        await InteractionResponder.safe_defer(interaction, ephemeral=False)

        ok, msg, market = await prediction_market.place_bet(
            market_id=盤號,
            user_id=interaction.user.id,
            option=opt,
            amount=下注點數,
        )

        if not ok:
            card_err = ZNCard(
                title="❌ 下注未成功",
                description=msg,
                status_pill=ZNStatusPill.ERROR,
                color=ZNColor.ERROR,
            )
            await InteractionResponder.safe_edit(interaction, card=card_err)
            return

        odds_a, odds_b = market.calculate_odds()
        total_pool = market.pool_a + market.pool_b
        card = ZNCard(
            title=f"🎰 下注回執 ➔ 盤號 #{market.market_id}",
            description=(
                f"{msg}\n\n"
                f"**📊 即時賭池現況**：\n"
                f"• 🅰️ `{market.option_a}`：{market.pool_a:,} 點數（當前賠率 `{odds_a}x`）\n"
                f"• 🅱️ `{market.option_b}`：{market.pool_b:,} 點數（當前賠率 `{odds_b}x`）\n"
                f"• 總獎池額度：**{total_pool:,} 點數**"
            ),
            status_pill=ZNStatusPill.SUCCESS,
            color=ZNColor.SUCCESS,
        )
        await InteractionResponder.safe_send(interaction, card=card)

    @bet_group.command(name="結算", description="公布獲勝選項並依據最終賠率分派點數")
    @app_commands.describe(盤號="要結算的賭盤代號", 獲勝選項="獲勝方（請輸入 A 或 B）")
    @command_guard("community")
    async def bet_settle_command(
        self,
        interaction: discord.Interaction,
        盤號: str,
        獲勝選項: str,
    ) -> None:
        win_opt = (獲勝選項 or "").strip().upper()
        if win_opt not in ("A", "B"):
            await InteractionResponder.safe_send(interaction, "❌ 獲勝選項必須為 'A' 或 'B'。", ephemeral=True)
            return

        market = prediction_market.get_market(盤號)
        if not market:
            await InteractionResponder.safe_send(interaction, "❌ 查無此賭盤編號。", ephemeral=True)
            return
        is_admin = bool(interaction.user.guild_permissions and interaction.user.guild_permissions.administrator) if interaction.guild else False
        if interaction.user.id != market.creator_id and not is_admin:
            await InteractionResponder.safe_send(interaction, "❌ 僅有發起莊家或伺服器管理員可進行結算！", ephemeral=True)
            return
        if market.is_settled:
            await InteractionResponder.safe_send(interaction, "❌ 此賭盤先前已經結算過囉！", ephemeral=True)
            return

        await InteractionResponder.safe_defer(interaction, ephemeral=False)

        ok, msg, count, total_pay = await prediction_market.settle_market(盤號, win_opt)
        if not ok:
            card_err = ZNCard(
                title="❌ 結算未成功",
                description=msg,
                status_pill=ZNStatusPill.ERROR,
                color=ZNColor.ERROR,
            )
            await InteractionResponder.safe_edit(interaction, card=card_err)
            return

        card = ZNCard(
            title=f"🏆 賭盤結算完成 ➔ #{market.market_id}",
            description=(
                f"**主題**：{market.title}\n\n"
                f"{msg}\n\n"
                f"感謝各位成員的熱情參與，點數已即刻入帳至錢包！"
            ),
            status_pill=ZNStatusPill.SUCCESS,
            color=ZNColor.SUCCESS,
        )
        await InteractionResponder.safe_send(interaction, card=card)

    @bet_group.command(name="查看", description="查看指定賭盤的最新池底與動態賠率")
    @app_commands.describe(盤號="要查看的賭盤代號")
    @command_guard("community")
    async def bet_view_command(self, interaction: discord.Interaction, 盤號: str) -> None:
        market = prediction_market.get_market(盤號)
        if not market:
            await InteractionResponder.safe_send(interaction, "❌ 查無此賭盤編號。", ephemeral=True)
            return

        odds_a, odds_b = market.calculate_odds()
        status_text = f"已結算（獲勝：{market.winning_option}）" if market.is_settled else "🟢 進行下注中"
        card = ZNCard(
            title=f"🎰 賭盤詳情 ➔ #{market.market_id} ({status_text})",
            description=(
                f"### {market.title}\n\n"
                f"• 🅰️ **{market.option_a}**：`{market.pool_a:,}` 點數（賠率 `{odds_a}x`）\n"
                f"• 🅱️ **{market.option_b}**：`{market.pool_b:,}` 點數（賠率 `{odds_b}x`）\n"
                f"• 總獎池資金：`{market.pool_a + market.pool_b:,}` 點數\n"
                f"• 總投標注數：`{len(market.bets)}` 筆下注"
            ),
            status_pill=ZNStatusPill.INFO,
            color=ZNColor.INFO,
        )
        await InteractionResponder.safe_send(interaction, card=card)

    # -------------------------------------------------------------------------
    # 6. 雙人格相聲互懟模式 (/相聲)
    # -------------------------------------------------------------------------
    @app_commands.command(name="相聲", description="雙 AI 逗哏與捧哏現場針鋒相對鬥嘴給建議")
    @app_commands.describe(主題="想要兩位大師開槓辯論的主題（例如：要不要買最新iPhone、加班是不是福報）")
    @command_guard("community")
    async def crosstalk_command(self, interaction: discord.Interaction, 主題: str) -> None:
        await InteractionResponder.safe_defer(interaction, ephemeral=False)

        script = await dual_crosstalk.perform_crosstalk(主題)
        card = ZNCard(
            title=f"🎭 雙人格相聲劇場 ➔《大話：{主題}》",
            description=script,
            status_pill=ZNStatusPill.FUN,
            color=ZNColor.PURPLE,
            footer_text="ZeroNexus Dual AI Comedy • 捧逗互懟笑看人生",
        )
        await InteractionResponder.safe_send(interaction, card=card)

    # -------------------------------------------------------------------------
    # 7. 重大決策圓桌會議 (/圓桌會議)
    # -------------------------------------------------------------------------
    @app_commands.command(name="圓桌會議", description="技術派、現實派、心靈派專家激辯重大抉擇")
    @app_commands.describe(決策議題="你正面臨的人生或技術難題（例如：該裸辭創業嗎？要不要換工作？）")
    @command_guard("community")
    async def roundtable_command(self, interaction: discord.Interaction, 決策議題: str) -> None:
        await InteractionResponder.safe_defer(interaction, ephemeral=False)

        report = await roundtable_council.convene_council(決策議題)
        card = ZNCard(
            title="🏛️ 重大決策智庫圓桌會議報告",
            description=report,
            status_pill=ZNStatusPill.AI,
            color=ZNColor.PRIMARY,
            footer_text="ZeroNexus Decision Council • 多維度專家決策矩陣",
        )
        await InteractionResponder.safe_send(interaction, card=card)

    # -------------------------------------------------------------------------
    # 8. 私聊深夜手帳 (/深夜手帳)
    # -------------------------------------------------------------------------
    diary_group = app_commands.Group(name="深夜手帳", description="私聊深夜心情記錄與走勢長圖")

    @diary_group.command(name="記錄", description="記錄今日心情評分 (1-10) 與生活札記")
    @app_commands.describe(心情評分="今日整體情緒分數（1 為極低落，10 為極喜悅）", 隨筆感想="寫下一句或一段今日的心情話語")
    @command_guard("community")
    async def diary_record_command(self, interaction: discord.Interaction, 心情評分: int, 隨筆感想: str) -> None:
        score = max(1, min(10, 心情評分))
        entry = late_night_diary.record_mood(interaction.user.id, score, 隨筆感想)

        emojis = ["🌧️", "🌧️", "☁️", "⛅", "🌤️", "☀️", "🌈", "✨", "🌟", "💖"]
        mood_emoji = emojis[score - 1]

        card = ZNCard(
            title=f"🌙 深夜手帳已封存 ➔ {entry.date_str}",
            description=(
                f"**心情指數**：{mood_emoji} `{score} / 10 分`\n"
                f"**札記內文**：\n> {entry.note}\n\n"
                f"辛苦了，今天也認真度過了一天！願你今夜好夢，明日繼續前行。✨"
            ),
            status_pill=ZNStatusPill.SUCCESS,
            color=ZNColor.PURPLE,
        )
        await InteractionResponder.safe_send(interaction, card=card, ephemeral=True)

    @diary_group.command(name="走勢圖", description="生成本月份心情起伏波動走勢長圖")
    @app_commands.describe(年份="指定年份（預設當前年）", 月份="指定月份（1-12，預設當前月）")
    @command_guard("community")
    async def diary_chart_command(
        self,
        interaction: discord.Interaction,
        年份: Optional[int] = None,
        月份: Optional[int] = None,
    ) -> None:
        await InteractionResponder.safe_defer(interaction, ephemeral=True)

        now = datetime.now(timezone.utc)
        y = 年份 or now.year
        m = 月份 or now.month

        chart_bytes = late_night_diary.render_monthly_trend_chart(interaction.user.id, y, m)
        file = discord.File(io.BytesIO(chart_bytes), filename="mood_trend.png")

        card = ZNCard(
            title=f"🌙 {y} 年 {m} 月情緒走勢長圖",
            description="已為您繪製專屬心靈走勢曲線圖，願每一次低谷都是即將攀升的蓄力！",
            status_pill=ZNStatusPill.SUCCESS,
            color=ZNColor.PURPLE,
        )
        card.set_image("attachment://mood_trend.png")
        await InteractionResponder.safe_send(interaction, card=card, file=file, ephemeral=True)

    # -------------------------------------------------------------------------
    # 9. 多模態檔案解析與 YouTube 省流指令 (/檔案解析, /影片摘要)
    # -------------------------------------------------------------------------
    @app_commands.command(name="檔案解析", description="上傳檔案 (PDF/Word/CSV/文字) 並產出結構化重點懶人包與視覺圖表")
    @app_commands.describe(檔案="欲解析的附件檔案", 指定提問="針對檔案希望特別解答的問題（選填）")
    @command_guard("community")
    async def file_parse_command(
        self,
        interaction: discord.Interaction,
        檔案: discord.Attachment,
        指定提問: Optional[str] = None,
    ) -> None:
        await InteractionResponder.safe_defer(interaction, ephemeral=False)

        try:
            data = await 檔案.read()
        except Exception as e:
            await InteractionResponder.safe_send(interaction, f"❌ 讀取檔案失敗：{e}", ephemeral=True)
            return

        extracted = multimodal_ingester.extract_file(data, 檔案.filename, 檔案.content_type)
        tldr = await multimodal_ingester.generate_tldr(extracted, 指定提問)

        key_pts_str = "\n".join(f"• {pt}" for pt in tldr.key_points)
        card = ZNCard(
            title=f"📄 多模態檔案提煉 ➔ {tldr.filename}",
            description=(
                f"### 📌 30 秒核心概要\n{tldr.core_summary}\n\n"
                f"### 🔍 三大關鍵重點\n{key_pts_str}\n\n"
                f"### 💡 行動指引與建議\n{tldr.action_guidance}"
            ),
            status_pill=ZNStatusPill.SUCCESS,
            color=ZNColor.INFO,
            footer_text=f"ZeroNexus File Ingester • 類型: {tldr.file_type.upper()}",
        )

        file = None
        if tldr.chart_image_bytes:
            file = discord.File(io.BytesIO(tldr.chart_image_bytes), filename="file_chart.png")
            card.set_image("attachment://file_chart.png")

        await InteractionResponder.safe_send(interaction, card=card, file=file)

    @app_commands.command(name="影片摘要", description="解析 YouTube 影片網址並提煉 30 秒核心結論與省流重點")
    @app_commands.describe(網址="YouTube 影片網址 (支援 standard, shorts, youtu.be)")
    @command_guard("community")
    async def yt_summary_command(self, interaction: discord.Interaction, 網址: str) -> None:
        await InteractionResponder.safe_defer(interaction, ephemeral=False)

        tldr = await youtube_tldr_parser.generate_tldr(網址)
        key_pts_str = "\n".join(f"• {pt}" for pt in tldr.key_points)

        card = ZNCard(
            title=f"⚡ 30 秒省流懶人包 ➔ {tldr.title}",
            description=(
                f"**🎬 創作者**：{tldr.author}\n"
                f"**⭐️ 省流評級**：{tldr.savings_rating}\n"
                f"**🎯 適合對象**：{tldr.target_audience}\n\n"
                f"### 📌 核心結論\n{tldr.core_takeaway}\n\n"
                f"### 🔍 精華論點\n{key_pts_str}\n\n"
                f"[🔗 點此前往觀看原影片]({tldr.video_url})"
            ),
            status_pill=ZNStatusPill.SUCCESS,
            color=ZNColor.PRIMARY,
        )
        await InteractionResponder.safe_send(interaction, card=card)

    @app_commands.command(name="匿名樹洞", description="匿名向頻道投遞心情秘密、告白或心事 (支援匿名互動回覆)")
    @command_guard("community")
    async def tree_hole_command(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_modal(TreeHoleSubmissionModal())


class TreeHoleReplyModal(discord.ui.Modal, title="💌 匿名回信至樹洞"):
    nickname = discord.ui.TextInput(
        label="您的匿名代號",
        placeholder="例如：路過的旅人 / 默默關注的人",
        default="暖心的過客",
        required=False,
        max_length=30,
    )
    reply_content = discord.ui.TextInput(
        label="回覆心語",
        placeholder="請留下您溫暖的鼓勵或想法...",
        style=discord.TextStyle.paragraph,
        required=True,
        max_length=800,
    )

    def __init__(self, parent_view: TreeHoleReplyView) -> None:
        super().__init__()
        self.parent_view = parent_view

    async def on_submit(self, interaction: discord.Interaction) -> None:
        raw_reply = self.reply_content.value.strip()
        if not raw_reply:
            await interaction.response.send_message("❌ 回覆心語不能為空白！", ephemeral=True)
            return

        clean_reply = raw_reply[:800]
        nick = (self.nickname.value.strip() or "暖心的過客")[:30]

        self.parent_view.reply_count += 1
        for item in self.parent_view.children:
            if isinstance(item, discord.ui.Button) and item.custom_id == "treehole_reply_btn":
                item.label = f"💌 匿名回覆 ({self.parent_view.reply_count})"

        try:
            await interaction.response.edit_message(view=self.parent_view)
        except Exception:
            pass

        reply_card = ZNCard(
            title=f"💌 來自【{nick}】的樹洞回音",
            description=f"「{clean_reply}」",
            status_pill=ZNStatusPill.FUN,
            color=ZNColor.PURPLE,
            footer_text="ZeroNexus 匿名樹洞 • 雙向匿名溫暖守護",
        )
        try:
            await interaction.followup.send(embed=reply_card.to_embed())
        except Exception:
            pass


class TreeHoleReplyView(discord.ui.View):
    """View with button to reply anonymously to a tree hole message."""

    def __init__(self, reply_count: int = 0) -> None:
        super().__init__(timeout=None)
        self.reply_count = reply_count

    @discord.ui.button(
        label="💌 匿名回覆 (0)",
        style=discord.ButtonStyle.secondary,
        custom_id="treehole_reply_btn",
    )
    async def btn_reply(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await interaction.response.send_modal(TreeHoleReplyModal(self))


class TreeHoleSubmissionModal(discord.ui.Modal, title="🌲 投遞匿名樹洞信件"):
    tag = discord.ui.TextInput(
        label="主題分類標籤",
        placeholder="例如：心情隨筆 / 悄悄話 / 感情困惑 / 匿名告白",
        default="心情隨筆",
        required=False,
        max_length=20,
    )
    nickname = discord.ui.TextInput(
        label="匿名暱稱 (不顯示真實身分)",
        placeholder="例如：匿名的貓咪 / 迷路的旅人",
        default="迷路的旅人",
        required=False,
        max_length=30,
    )
    content = discord.ui.TextInput(
        label="樹洞內容 (請放心，身分 100% 嚴格匿名保密)",
        placeholder="寫下您想傾訴的心事、秘密或告白...",
        style=discord.TextStyle.paragraph,
        required=True,
        max_length=1500,
    )

    async def on_submit(self, interaction: discord.Interaction) -> None:
        user_tag = (self.tag.value.strip() or "心情隨筆")[:20]
        user_nick = (self.nickname.value.strip() or "迷路的旅人")[:30]
        letter_content = self.content.value.strip()
        if not letter_content:
            await interaction.response.send_message("❌ 樹洞內容不能為空白！請分享您的心事。", ephemeral=True)
            return

        letter_content = letter_content[:1500]
        card = ZNCard(
            title=f"🌲 匿名樹洞信件 — 【{user_tag}】",
            description=(
                f"「{letter_content}」\n\n"
                f"— *來自：{user_nick}*"
            ),
            status_pill=ZNStatusPill.FUN,
            color=ZNColor.PRIMARY,
            footer_text="ZeroNexus 匿名樹洞 • 所有發言已完全去除成員身分資訊",
        )
        reply_view = TreeHoleReplyView()
        try:
            await interaction.response.send_message(embed=card.to_embed(), view=reply_view)
            await interaction.followup.send("✅ 您的樹洞信件已安全匿名投遞成功！願您的心事隨風釋懷～", ephemeral=True)
        except Exception as ex:
            if not interaction.response.is_done():
                await interaction.response.send_message(f"❌ 投遞樹洞信件時發生錯誤：`{ex}`", ephemeral=True)
            else:
                await interaction.followup.send(f"❌ 投遞樹洞信件時發生錯誤：`{ex}`", ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(CommunityCog(bot))
