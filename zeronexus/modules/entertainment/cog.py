"""ZeroNexus Entertainment, Mini-Games & Economy Cog.

Fully Implemented Commands under /娛樂:
- 拉霸機 (槽位拉霸), 猜拳 (剪刀石頭布), 數字炸彈 (終極密碼)
- 丟硬幣 (拋硬幣), 骰子 (擲骰子), 幫我選 (選擇困難)
- 每日簽到, 餘額 (個人錢包), 轉帳, 財富排行榜
- 21點, 井字棋, 四子棋, 俄羅斯輪盤, 抽籤
- 猜數字 (1A2B), 猜單字 (Wordle), 海龜湯, 趣味問答, 戀愛契合度

Features:
- Full EconomyWallet persistence with atomic anti-TOCTOU concurrency checks
- Interactive Discord UI Views with modal inputs, anti-spam asyncio.Lock protection
- True channel-based session management for 終極密碼 (數字炸彈) & 1A2B
- Vivid, authentic, and engaging Traditional Chinese localization
"""

from __future__ import annotations

import asyncio
import hashlib
import random
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

import discord
from discord import app_commands
from discord.ext import commands
from sqlalchemy import desc, select, update

from zeronexus.core.database import db
from zeronexus.models.user import EconomyWallet
from zeronexus.modules.base import BaseModule, CommandMetadata
from zeronexus.security.guard import command_guard
from zeronexus.security.permissions import ZNPermissionLevel
from zeronexus.engines.free_apis import free_apis
from zeronexus.ui.card import ZNCard
from zeronexus.ui.responder import InteractionResponder
from zeronexus.ui.theme import ZNColor, ZNStatusPill


# =============================================================================
# Helper: Economy Wallet Utilities
# =============================================================================

async def _get_or_create_wallet(session: Any, user_id: int, default_points: int = 100) -> EconomyWallet:
    stmt = select(EconomyWallet).where(EconomyWallet.user_id == user_id)
    res = await session.execute(stmt)
    wallet = res.scalars().first()
    if not wallet:
        wallet = EconomyWallet(user_id=user_id, points=default_points)
        session.add(wallet)
        await session.flush()
    return wallet


# =============================================================================
# 1. 水果拉霸機 View (SlotMachineView)
# =============================================================================

class SlotMachineView(discord.ui.View):
    """Interactive Slot Machine with atomic betting, anti-double-click lock, and balance guards."""

    SYMBOLS = ["🍒", "🍋", "🍇", "🔔", "⭐", "💎", "7️⃣"]
    WEIGHTS = [30, 25, 20, 12, 8, 4, 1]

    def __init__(self, author_id: int, bet: int, timeout: float = 60.0) -> None:
        super().__init__(timeout=timeout)
        self.author_id = author_id
        self.bet = bet
        self.message: Optional[discord.Message] = None
        self._lock = asyncio.Lock()

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await InteractionResponder.safe_send(interaction, "❌ 此拉霸機僅限啟動玩家操作喔！", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="再拉一把！", emoji="🎰", style=discord.ButtonStyle.primary)
    async def spin_again(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        async with self._lock:
            # 1. Atomic deduction
            async with db.session() as session:
                wallet = await _get_or_create_wallet(session, self.author_id)
                if wallet.points < self.bet:
                    button.disabled = True
                    card = ZNCard(
                        title="💰 餘額不足提醒",
                        description=f"您的點數餘額僅剩 **{wallet.points:,} 點數**，不足以支付下注額 **{self.bet:,} 點數**！\n可使用 `/娛樂 每日簽到` 領取補貼喔！",
                        status_pill=ZNStatusPill.WARNING,
                        color=ZNColor.WARNING,
                    )
                    await InteractionResponder.safe_send(interaction, card=card, ephemeral=True)
                    if self.message:
                        try:
                            await self.message.edit(view=self)
                        except Exception:
                            pass
                    return

                # Deduct bet atomically
                stmt_deduct = (
                    update(EconomyWallet)
                    .where(EconomyWallet.user_id == self.author_id, EconomyWallet.points >= self.bet)
                    .values(points=EconomyWallet.points - self.bet)
                )
                deduct_res = await session.execute(stmt_deduct)
                if deduct_res.rowcount == 0:
                    button.disabled = True
                    await InteractionResponder.safe_send(interaction, "❌ 點數扣除失敗，餘額不足。", ephemeral=True)
                    return

                # 2. Spin reels
                s1, s2, s3 = random.choices(self.SYMBOLS, weights=self.WEIGHTS, k=3)

                win_mult = 0
                win_title = "💨 銘謝惠顧！"
                win_color = ZNColor.DARK

                if s1 == s2 == s3:
                    if s1 == "7️⃣":
                        win_mult = 50
                        win_title = "👑 驚天大獎！JACKPOT 777！！"
                        win_color = discord.Color.gold()
                    elif s1 == "💎":
                        win_mult = 20
                        win_title = "💎 璀璨鑽石大獎！"
                        win_color = discord.Color.teal()
                    elif s1 == "⭐":
                        win_mult = 12
                        win_title = "⭐ 幸運星輝大獎！"
                        win_color = discord.Color.purple()
                    elif s1 == "🔔":
                        win_mult = 8
                        win_title = "🔔 歡樂金鈴大獎！"
                        win_color = ZNColor.SUCCESS
                    else:
                        win_mult = 5
                        win_title = "🍇 水果滿貫大三元！"
                        win_color = ZNColor.SUCCESS
                elif s1 == s2 or s2 == s3 or s1 == s3:
                    win_mult = 2
                    win_title = "✨ 雙星連線小獎！"
                    win_color = ZNColor.INFO
                else:
                    win_mult = 0
                    win_title = "💨 差一點點就中了～再來一把試試手氣！"
                    win_color = ZNColor.DARK

                win_amount = self.bet * win_mult
                if win_amount > 0:
                    stmt_win = (
                        update(EconomyWallet)
                        .where(EconomyWallet.user_id == self.author_id)
                        .values(points=EconomyWallet.points + win_amount)
                    )
                    await session.execute(stmt_win)

                # Fetch latest balance
                stmt_bal = select(EconomyWallet.points).where(EconomyWallet.user_id == self.author_id)
                bal_res = await session.execute(stmt_bal)
                current_bal = bal_res.scalar() or 0

            net_gain = win_amount - self.bet
            net_str = f"+{net_gain:,}" if net_gain >= 0 else f"{net_gain:,}"

            card = ZNCard(
                title=f"🎰 水果拉霸機 — {win_title}",
                description=(
                    f"# [  {s1}  |  {s2}  |  {s3}  ]\n\n"
                    f"**本局押注**：`{self.bet:,} 點數`\n"
                    f"**贏得獎金**：`{win_amount:,} 點數` (淨收益: **{net_str}**)\n"
                    f"**目前錢包餘額**：💰 **{current_bal:,} 點數**"
                ),
                status_pill=ZNStatusPill.FUN,
                color=win_color,
            )
            await InteractionResponder.safe_edit(interaction, card=card, view=self)

    async def on_timeout(self) -> None:
        for child in self.children:
            if hasattr(child, "disabled"):
                child.disabled = True
        self.stop()
        if self.message:
            try:
                await self.message.edit(view=self)
            except (discord.NotFound, discord.HTTPException, Exception):
                pass


# =============================================================================
# 2. 剪刀石頭布 View (RPS vs Bot & PvP)
# =============================================================================

class RPSButton(discord.ui.Button["RPSView"]):
    def __init__(self, name: str, emoji: str) -> None:
        super().__init__(label=name, emoji=emoji, style=discord.ButtonStyle.secondary)
        self.choice_name = name

    async def callback(self, interaction: discord.Interaction) -> None:
        assert self.view is not None
        await self.view.play_rps(interaction, self.choice_name)


class RPSView(discord.ui.View):
    """Rock-Paper-Scissors against bot with consecutive streak counter and instant replay."""

    EMOJIS = {"剪刀": "✌️", "石頭": "✊", "布": "🖐️"}

    def __init__(self, author_id: int, timeout: float = 45.0) -> None:
        super().__init__(timeout=timeout)
        self.author_id = author_id
        self.streak = 0
        self.message: Optional[discord.Message] = None
        self._lock = asyncio.Lock()
        self._add_rps_buttons()

    def _add_rps_buttons(self) -> None:
        self.clear_items()
        for name, emoji in [("石頭", "✊"), ("布", "🖐️"), ("剪刀", "✌️")]:
            self.add_item(RPSButton(name, emoji))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await InteractionResponder.safe_send(interaction, "❌ 此猜拳對決僅限發起者操作。", ephemeral=True)
            return False
        return True

    async def play_rps(self, interaction: discord.Interaction, user_pick: str) -> None:
        async with self._lock:
            bot_pick = random.choice(["剪刀", "石頭", "布"])

            if user_pick == bot_pick:
                outcome = "🤝 平手！英雄所見略同，心有靈犀！"
                c = ZNColor.INFO
            elif (
                (user_pick == "石頭" and bot_pick == "剪刀")
                or (user_pick == "剪刀" and bot_pick == "布")
                or (user_pick == "布" and bot_pick == "石頭")
            ):
                self.streak += 1
                streak_bonus = f"🔥 連續獲勝：**{self.streak} 連勝**！" if self.streak > 1 else ""
                outcome = f"🎉 恭喜你贏了！精彩的心理博弈！ {streak_bonus}"
                c = ZNColor.SUCCESS
            else:
                self.streak = 0
                outcome = "😈 哈哈！這把是 ZeroNexus 技高一籌贏下了！"
                c = ZNColor.ERROR

            card = ZNCard(
                title="✊✌️🖐️ 猜拳對決結果",
                description=(
                    f"**你的出拳**：{self.EMOJIS[user_pick]} **{user_pick}**\n"
                    f"**ZN 出拳**：{self.EMOJIS[bot_pick]} **{bot_pick}**\n\n"
                    f"# {outcome}\n\n"
                    f"*(可點擊下方按鈕直接再來一局！)*"
                ),
                status_pill=ZNStatusPill.FUN,
                color=c,
            )
            self._add_rps_buttons()
            await InteractionResponder.safe_edit(interaction, card=card, view=self)

    async def on_timeout(self) -> None:
        for child in self.children:
            if hasattr(child, "disabled"):
                child.disabled = True
        self.stop()
        if self.message:
            try:
                await self.message.edit(view=self)
            except (discord.NotFound, discord.HTTPException, Exception):
                pass


class PvPRPSButton(discord.ui.Button["PvPRPSView"]):
    def __init__(self, name: str, emoji: str) -> None:
        super().__init__(label=name, emoji=emoji, style=discord.ButtonStyle.secondary)
        self.choice_name = name

    async def callback(self, interaction: discord.Interaction) -> None:
        assert self.view is not None
        await self.view.make_choice(interaction, self.choice_name)


class PvPRPSView(discord.ui.View):
    """PvP Rock-Paper-Scissors with blind pick mechanism."""

    EMOJIS = {"剪刀": "✌️", "石頭": "✊", "布": "🖐️"}

    def __init__(self, p1: discord.Member, p2: discord.Member, timeout: float = 60.0) -> None:
        super().__init__(timeout=timeout)
        self.p1 = p1
        self.p2 = p2
        self.choices: Dict[int, str] = {}
        self.message: Optional[discord.Message] = None
        self._lock = asyncio.Lock()

        for name, emoji in [("石頭", "✊"), ("布", "🖐️"), ("剪刀", "✌️")]:
            self.add_item(PvPRPSButton(name, emoji))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id not in (self.p1.id, self.p2.id):
            await InteractionResponder.safe_send(interaction, "❌ 此對決為雙人專屬對弈，觀戰成員請勿點擊。", ephemeral=True)
            return False
        return True

    async def make_choice(self, interaction: discord.Interaction, pick: str) -> None:
        async with self._lock:
            uid = interaction.user.id
            if uid in self.choices:
                await InteractionResponder.safe_send(interaction, f"⚠️ 您已經秘密出過拳了 ({self.choices[uid]})，正在等待對手出拳！", ephemeral=True)
                return

            self.choices[uid] = pick
            await InteractionResponder.safe_send(interaction, f"🔒 秘密出拳成功：{self.EMOJIS[pick]} **{pick}**！等待對方就緒中...", ephemeral=True)

            if len(self.choices) == 2:
                # Both picked! Reveal
                p1_pick = self.choices[self.p1.id]
                p2_pick = self.choices[self.p2.id]

                if p1_pick == p2_pick:
                    result = "🤝 勢均力敵！雙方出了一樣的拳，平手！"
                    color = ZNColor.INFO
                elif (
                    (p1_pick == "石頭" and p2_pick == "剪刀")
                    or (p1_pick == "剪刀" and p2_pick == "布")
                    or (p1_pick == "布" and p2_pick == "石頭")
                ):
                    result = f"👑 恭喜 {self.p1.mention} 獲勝！"
                    color = ZNColor.SUCCESS
                else:
                    result = f"👑 恭喜 {self.p2.mention} 獲勝！"
                    color = ZNColor.SUCCESS

                for child in self.children:
                    if isinstance(child, discord.ui.Button):
                        child.disabled = True

                card = ZNCard(
                    title="⚔️ 雙人猜拳對抗賽結果揭曉",
                    description=(
                        f"{self.p1.mention} 出：{self.EMOJIS[p1_pick]} **{p1_pick}**\n"
                        f"{self.p2.mention} 出：{self.EMOJIS[p2_pick]} **{p2_pick}**\n\n"
                        f"# {result}"
                    ),
                    status_pill=ZNStatusPill.FUN,
                    color=color,
                )
                self.stop()
                if self.message:
                    try:
                        await self.message.edit(embed=card.to_embed(), view=self)
                    except Exception:
                        await InteractionResponder.safe_send(interaction, card=card)
                else:
                    await InteractionResponder.safe_send(interaction, card=card)

    async def on_timeout(self) -> None:
        for child in self.children:
            if hasattr(child, "disabled"):
                child.disabled = True
        self.stop()
        if self.message:
            try:
                await self.message.edit(view=self)
            except (discord.NotFound, discord.HTTPException, Exception):
                pass


# =============================================================================
# 3. 數字炸彈 / 終極密碼 Session & Modal View
# =============================================================================

class NumberBombModal(discord.ui.Modal, title="💣 拆彈猜測數字"):
    guess_input = discord.ui.TextInput(
        label="輸入您的猜測整數",
        placeholder="請輸入範圍內的數字...",
        min_length=1,
        max_length=6,
        required=True,
    )

    def __init__(self, session: "NumberBombSession") -> None:
        super().__init__()
        self.game_session = session

    async def on_submit(self, interaction: discord.Interaction) -> None:
        val_str = self.guess_input.value.strip()
        if not val_str.isdigit():
            await InteractionResponder.safe_send(interaction, "❌ 請輸入有效的正整數！", ephemeral=True)
            return
        guess = int(val_str)
        await self.game_session.process_guess(interaction, guess)


class NumberBombView(discord.ui.View):
    """Interactive view for Number Bomb in channels."""

    def __init__(self, session: "NumberBombSession", timeout: float = 180.0) -> None:
        super().__init__(timeout=timeout)
        self.session = session

    @discord.ui.button(label="我要拆彈！", emoji="💥", style=discord.ButtonStyle.danger)
    async def guess_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if not self.session.active:
            await InteractionResponder.safe_send(interaction, "⚠️ 本局數字炸彈已結束，請發起新局！", ephemeral=True)
            return
        modal = NumberBombModal(self.session)
        await interaction.response.send_modal(modal)

    @discord.ui.button(label="重開新局", emoji="🔄", style=discord.ButtonStyle.secondary)
    async def reset_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        async with self.session.lock:
            self.session.reset()
            card = self.session.render_card(f"🔄 {interaction.user.mention} 重新重置了數字炸彈！")
            await InteractionResponder.safe_send(interaction, card=card, view=self)

    async def on_timeout(self) -> None:
        self.session.active = False
        for child in self.children:
            if hasattr(child, "disabled"):
                child.disabled = True
        self.stop()
        if self.session.message:
            try:
                await self.session.message.edit(view=self)
            except (discord.NotFound, discord.HTTPException, Exception):
                pass


class NumberBombSession:
    """Channel-level active session for Number Bomb (終極密碼)."""

    def __init__(self, channel_id: int, min_val: int = 1, max_val: int = 100) -> None:
        self.channel_id = channel_id
        self.min_val = min_val
        self.max_val = max_val
        self.bomb = random.randint(min_val + 1, max_val - 1)
        self.active = True
        self.last_guesser: Optional[str] = None
        self.last_guess: Optional[int] = None
        self.lock = asyncio.Lock()
        self.message: Optional[discord.Message] = None
        self.view: Optional[NumberBombView] = None
        self.created_at = time.time()

    def reset(self, min_val: int = 1, max_val: int = 100) -> None:
        self.min_val = min_val
        self.max_val = max_val
        self.bomb = random.randint(min_val + 1, max_val - 1)
        self.active = True
        self.last_guesser = None
        self.last_guess = None
        self.created_at = time.time()
        if self.view:
            for child in self.view.children:
                if hasattr(child, "disabled"):
                    child.disabled = False

    def render_card(self, note: str = "") -> ZNCard:
        desc_lines = [
            f"# 💣 安全範圍：[ {self.min_val} ~ {self.max_val} ]",
            "",
            f"**最後出手者**：{self.last_guesser or '尚未有人出招'}",
            f"**最新猜測**：`{self.last_guess if self.last_guess is not None else '無'}`",
        ]
        if note:
            desc_lines.append(f"\n{note}")

        return ZNCard(
            title="💣 數字炸彈 (終極密碼)",
            description="\n".join(desc_lines),
            status_pill=ZNStatusPill.FUN,
            color=ZNColor.WARNING if self.active else ZNColor.ERROR,
        )

    async def process_guess(self, interaction: discord.Interaction, guess: int) -> None:
        async with self.lock:
            if not self.active:
                await InteractionResponder.safe_send(interaction, "⚠️ 本局數字炸彈已結束，請使用 `/娛樂 數字炸彈` 發起新局！", ephemeral=True)
                return

            if guess <= self.min_val or guess >= self.max_val:
                await InteractionResponder.safe_send(
                    interaction,
                    f"❌ 數字必須介於安全範圍內：**{self.min_val + 1} 至 {self.max_val - 1}** 之間！",
                    ephemeral=True,
                )
                return

            self.last_guesser = interaction.user.mention
            self.last_guess = guess

            if guess == self.bomb:
                self.active = False
                if self.view:
                    for child in self.view.children:
                        if getattr(child, "label", None) == "我要拆彈！":
                            child.disabled = True
                card = ZNCard(
                    title="💥💥 轟！！BOOM！！踩中炸彈了！",
                    description=(
                        f"🚨 {interaction.user.mention} 倒楣地引爆了終極密碼！！\n"
                        f"# 炸彈數字正是：**{self.bomb}**！\n\n"
                        f"全體成員起立為這位勇敢的拆彈烈士鼓掌致敬～👏👏👏\n"
                        f"*(遊戲已結束，點擊下方按鈕即可重新開局)*"
                    ),
                    status_pill=ZNStatusPill.ERROR,
                    color=ZNColor.ERROR,
                )
                await InteractionResponder.safe_send(interaction, card=card, view=self.view)
            else:
                if guess < self.bomb:
                    self.min_val = guess
                    hint = "💨 呼～安全！數字在更高處！新範圍已縮小。"
                else:
                    self.max_val = guess
                    hint = "💨 呼～安全！數字在更低處！新範圍已縮小。"

                card = self.render_card(hint)
                await InteractionResponder.safe_send(interaction, card=card, view=self.view)


_BOMB_SESSIONS: Dict[int, NumberBombSession] = {}


# =============================================================================
# 4. 21點扑克 (BlackjackView)
# =============================================================================

class BlackjackView(discord.ui.View):
    """Interactive full-featured Blackjack poker game."""

    SUITS = ["♠️", "♥️", "♦️", "♣️"]
    RANKS = ["A", "2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K"]

    def __init__(self, author_id: int, bet: int = 0, timeout: float = 60.0) -> None:
        super().__init__(timeout=timeout)
        self.author_id = author_id
        self.bet = bet
        self.deck = [(r, s) for r in self.RANKS for s in self.SUITS]
        random.shuffle(self.deck)
        self.player_hand: List[Tuple[str, str]] = [self.draw(), self.draw()]
        self.dealer_hand: List[Tuple[str, str]] = [self.draw(), self.draw()]
        self.game_over = False
        self._lock = asyncio.Lock()
        self.message: Optional[discord.Message] = None

    def draw(self) -> Tuple[str, str]:
        if not self.deck:
            self.deck = [(r, s) for r in self.RANKS for s in self.SUITS]
            random.shuffle(self.deck)
        return self.deck.pop()

    def calc_score(self, hand: List[Tuple[str, str]]) -> int:
        score = 0
        aces = 0
        for r, _ in hand:
            if r in ("J", "Q", "K"):
                score += 10
            elif r == "A":
                aces += 1
                score += 11
            else:
                score += int(r)
        while score > 21 and aces > 0:
            score -= 10
            aces -= 1
        return score

    def format_hand(self, hand: List[Tuple[str, str]], hide_second: bool = False) -> str:
        if hide_second:
            return f"`[{hand[0][1]}{hand[0][0]}]` `[🂠 ?]`"
        return " ".join(f"`[{s}{r}]`" for r, s in hand)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await InteractionResponder.safe_send(interaction, "❌ 此 21 點對決為私人牌桌，其他人無法插手。", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="要牌 (Hit)", emoji="🃏", style=discord.ButtonStyle.primary)
    async def hit(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        async with self._lock:
            if self.game_over:
                return

            self.player_hand.append(self.draw())
            p_score = self.calc_score(self.player_hand)

            if p_score > 21:
                self.game_over = True
                self._disable_buttons()
                card = ZNCard(
                    title="♠️ 撲克 21 點 — 爆牌出局！",
                    description=(
                        f"**您的手牌**：{self.format_hand(self.player_hand)} (點數: **{p_score}** 💥 爆牌)\n"
                        f"**莊家手牌**：{self.format_hand(self.dealer_hand)} (點數: **{self.calc_score(self.dealer_hand)}**)\n\n"
                        f"# 💥 哎呀！點數超過 21 點，您爆牌了！"
                    ),
                    status_pill=ZNStatusPill.ERROR,
                    color=ZNColor.ERROR,
                )
                self.stop()
                await InteractionResponder.safe_edit(interaction, card=card, view=self)
            elif p_score == 21:
                await self._dealer_turn(interaction)
            else:
                card = ZNCard(
                    title="♠️ 撲克 21 點 (Blackjack)",
                    description=(
                        f"**您的手牌**：{self.format_hand(self.player_hand)} (點數: **{p_score}**)\n"
                        f"**莊家手牌**：{self.format_hand(self.dealer_hand, hide_second=True)}\n\n"
                        f"請決定是否繼續要牌或停牌："
                    ),
                    status_pill=ZNStatusPill.FUN,
                    color=ZNColor.PRIMARY,
                )
                await InteractionResponder.safe_edit(interaction, card=card, view=self)

    @discord.ui.button(label="停牌 (Stand)", emoji="✋", style=discord.ButtonStyle.secondary)
    async def stand(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        async with self._lock:
            if self.game_over:
                return
            await self._dealer_turn(interaction)

    async def _dealer_turn(self, interaction: discord.Interaction) -> None:
        self.game_over = True
        self._disable_buttons()

        # Dealer hits on < 17
        while self.calc_score(self.dealer_hand) < 17:
            self.dealer_hand.append(self.draw())

        p_score = self.calc_score(self.player_hand)
        d_score = self.calc_score(self.dealer_hand)

        if d_score > 21:
            res_msg = "🎉 莊家爆牌了！恭喜您贏得這局！"
            color = ZNColor.SUCCESS
        elif p_score > d_score:
            res_msg = f"🎉 您的點數 ({p_score}) 高於莊家 ({d_score})！恭喜獲勝！"
            color = ZNColor.SUCCESS
        elif p_score < d_score:
            res_msg = f"💨 莊家點數 ({d_score}) 高於您 ({p_score})，這把莊家贏了！"
            color = ZNColor.ERROR
        else:
            res_msg = f"🤝 雙方同為 {p_score} 點，平手 (Push)！"
            color = ZNColor.INFO

        card = ZNCard(
            title="♠️ 撲克 21 點對決結果",
            description=(
                f"**您的手牌**：{self.format_hand(self.player_hand)} (總計: **{p_score}** 點)\n"
                f"**莊家手牌**：{self.format_hand(self.dealer_hand)} (總計: **{d_score}** 點)\n\n"
                f"# {res_msg}"
            ),
            status_pill=ZNStatusPill.FUN,
            color=color,
        )
        self.stop()
        await InteractionResponder.safe_edit(interaction, card=card, view=self)

    def _disable_buttons(self) -> None:
        for child in self.children:
            if isinstance(child, discord.ui.Button):
                child.disabled = True

    async def on_timeout(self) -> None:
        self.game_over = True
        self._disable_buttons()
        self.stop()
        if self.message:
            try:
                await self.message.edit(view=self)
            except (discord.NotFound, discord.HTTPException, Exception):
                pass


# =============================================================================
# 5. 井字棋 View (TicTacToeView)
# =============================================================================

class TicTacToeButton(discord.ui.Button["TicTacToeView"]):
    def __init__(self, x: int, y: int) -> None:
        super().__init__(style=discord.ButtonStyle.secondary, label="\u200b", row=y)
        self.x = x
        self.y = y

    async def callback(self, interaction: discord.Interaction) -> None:
        assert self.view is not None
        view: TicTacToeView = self.view
        async with view._lock:
            if interaction.user != view.current_player:
                await InteractionResponder.safe_send(interaction, "❌ 現在不是您的回合喔！", ephemeral=True)
                return

            if view.board[self.y][self.x] != 0:
                await InteractionResponder.safe_send(interaction, "❌ 此格已經落過棋子了！", ephemeral=True)
                return

            if view.current_player == view.p1:
                self.style = discord.ButtonStyle.danger
                self.label = "X"
                self.disabled = True
                view.board[self.y][self.x] = 1
                view.current_player = view.p2
                turn_msg = f"輪到 {view.p2.mention} (O) 落子！"
            else:
                self.style = discord.ButtonStyle.success
                self.label = "O"
                self.disabled = True
                view.board[self.y][self.x] = 2
                view.current_player = view.p1
                turn_msg = f"輪到 {view.p1.mention} (X) 落子！"

            winner = view.check_winner()
            if winner:
                for child in view.children:
                    if isinstance(child, discord.ui.Button):
                        child.disabled = True
                if winner == 1:
                    content = f"🎉 恭喜 {view.p1.mention} (X) 贏得了井字棋對決勝利！"
                elif winner == 2:
                    content = f"🎉 恭喜 {view.p2.mention} (O) 贏得了井字棋對決勝利！"
                else:
                    content = "🤝 平手！這是一場勢均力敵的頂尖博弈。"
                view.stop()
                await InteractionResponder.safe_edit(interaction, content=content, view=view)
            else:
                await InteractionResponder.safe_edit(interaction, content=turn_msg, view=view)


class TicTacToeView(discord.ui.View):
    def __init__(self, p1: discord.Member, p2: discord.Member) -> None:
        super().__init__(timeout=180.0)
        self.p1 = p1
        self.p2 = p2
        self.current_player = p1
        self.board = [[0, 0, 0], [0, 0, 0], [0, 0, 0]]
        self.message: Optional[discord.Message] = None
        self._lock = asyncio.Lock()

        for y in range(3):
            for x in range(3):
                self.add_item(TicTacToeButton(x, y))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id not in (self.p1.id, self.p2.id):
            await InteractionResponder.safe_send(interaction, "❌ 此井字棋為專屬對弈，觀戰成員請勿點擊。", ephemeral=True)
            return False
        return True

    def check_winner(self) -> int:
        for row in self.board:
            if row[0] == row[1] == row[2] != 0:
                return row[0]
        for col in range(3):
            if self.board[0][col] == self.board[1][col] == self.board[2][col] != 0:
                return self.board[0][col]
        if self.board[0][0] == self.board[1][1] == self.board[2][2] != 0:
            return self.board[0][0]
        if self.board[0][2] == self.board[1][1] == self.board[2][0] != 0:
            return self.board[0][2]
        if all(self.board[y][x] != 0 for y in range(3) for x in range(3)):
            return 3  # Tie
        return 0

    async def on_timeout(self) -> None:
        for child in self.children:
            if hasattr(child, "disabled"):
                child.disabled = True
        self.stop()
        if self.message:
            try:
                await self.message.edit(content="⏰ 井字棋對決已逾時結束。", view=self)
            except (discord.NotFound, discord.HTTPException, Exception):
                pass


# =============================================================================
# 6. 四子棋 View (Connect4View)
# =============================================================================

class Connect4ColButton(discord.ui.Button["Connect4View"]):
    def __init__(self, col: int) -> None:
        super().__init__(style=discord.ButtonStyle.secondary, label=f"{col+1} 列", row=0 if col < 4 else 1)
        self.col = col

    async def callback(self, interaction: discord.Interaction) -> None:
        assert self.view is not None
        await self.view.drop_piece(interaction, self.col)


class Connect4View(discord.ui.View):
    """Interactive Connect 4 (四子棋) board with 6 rows and 7 columns."""

    ROWS = 6
    COLS = 7

    def __init__(self, p1: discord.Member, p2: discord.Member, timeout: float = 180.0) -> None:
        super().__init__(timeout=timeout)
        self.p1 = p1  # 🔴
        self.p2 = p2  # 🟡
        self.current_player = p1
        self.board = [[0 for _ in range(self.COLS)] for _ in range(self.ROWS)]
        self.message: Optional[discord.Message] = None
        self._lock = asyncio.Lock()

        for c in range(self.COLS):
            self.add_item(Connect4ColButton(c))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id not in (self.p1.id, self.p2.id):
            await InteractionResponder.safe_send(interaction, "❌ 此四子棋為雙人專屬對弈，觀戰成員請勿點擊。", ephemeral=True)
            return False
        return True

    def render_board(self) -> str:
        icons = {0: "⚪", 1: "🔴", 2: "🟡"}
        lines = []
        for r in range(self.ROWS):
            lines.append("".join(icons[self.board[r][c]] for c in range(self.COLS)))
        lines.append("1️⃣2️⃣3️⃣4️⃣5️⃣6️⃣7️⃣")
        return "\n".join(lines)

    def check_win(self, p: int) -> bool:
        # Horizontal
        for r in range(self.ROWS):
            for c in range(self.COLS - 3):
                if all(self.board[r][c + i] == p for i in range(4)):
                    return True
        # Vertical
        for r in range(self.ROWS - 3):
            for c in range(self.COLS):
                if all(self.board[r + i][c] == p for i in range(4)):
                    return True
        # Diagonal /
        for r in range(3, self.ROWS):
            for c in range(self.COLS - 3):
                if all(self.board[r - i][c + i] == p for i in range(4)):
                    return True
        # Diagonal \
        for r in range(self.ROWS - 3):
            for c in range(self.COLS - 3):
                if all(self.board[r + i][c + i] == p for i in range(4)):
                    return True
        return False

    async def drop_piece(self, interaction: discord.Interaction, col: int) -> None:
        async with self._lock:
            if interaction.user != self.current_player:
                await InteractionResponder.safe_send(interaction, "❌ 現在不是您的回合！", ephemeral=True)
                return

            # Find lowest empty row in this col
            placed_row = -1
            for r in reversed(range(self.ROWS)):
                if self.board[r][col] == 0:
                    placed_row = r
                    break

            if placed_row == -1:
                await InteractionResponder.safe_send(interaction, "❌ 該列已經落滿了，請挑選其他列！", ephemeral=True)
                return

            piece = 1 if self.current_player == self.p1 else 2
            self.board[placed_row][col] = piece

            if self.check_win(piece):
                for child in self.children:
                    if isinstance(child, discord.ui.Button):
                        child.disabled = True
                winner = self.p1 if piece == 1 else self.p2
                card = ZNCard(
                    title="🎉 四子棋對局勝利！",
                    description=f"# 恭喜 {winner.mention} 連成四子贏得對決！\n\n{self.render_board()}",
                    status_pill=ZNStatusPill.SUCCESS,
                    color=ZNColor.SUCCESS,
                )
                self.stop()
                await InteractionResponder.safe_edit(interaction, card=card, view=self)
                return

            # Check full board tie
            if all(self.board[0][c] != 0 for c in range(self.COLS)):
                for child in self.children:
                    if isinstance(child, discord.ui.Button):
                        child.disabled = True
                card = ZNCard(
                    title="🤝 四子棋平局！",
                    description=f"# 棋盤已滿，雙方勢均力敵打成平手！\n\n{self.render_board()}",
                    status_pill=ZNStatusPill.FUN,
                    color=ZNColor.INFO,
                )
                self.stop()
                await InteractionResponder.safe_edit(interaction, card=card, view=self)
                return

            # Switch turn
            self.current_player = self.p2 if self.current_player == self.p1 else self.p1
            curr_icon = "🔴" if self.current_player == self.p1 else "🟡"
            card = ZNCard(
                title="🔴🟡 四子棋連線對弈",
                description=f"{self.render_board()}\n\n👉 輪到 {self.current_player.mention} ({curr_icon}) 落子！",
                status_pill=ZNStatusPill.FUN,
                color=ZNColor.PRIMARY,
            )
            await InteractionResponder.safe_edit(interaction, card=card, view=self)

    async def on_timeout(self) -> None:
        for child in self.children:
            if hasattr(child, "disabled"):
                child.disabled = True
        self.stop()
        if self.message:
            try:
                await self.message.edit(view=self)
            except (discord.NotFound, discord.HTTPException, Exception):
                pass


# =============================================================================
# 7. 擲骰子 / 拋硬幣 / 幫我選 Re-roll Views
# =============================================================================

class DiceReRollView(discord.ui.View):
    def __init__(self, author_id: int, count: int, sides: int, timeout: float = 60.0) -> None:
        super().__init__(timeout=timeout)
        self.author_id = author_id
        self.count = count
        self.sides = sides
        self.message: Optional[discord.Message] = None
        self._lock = asyncio.Lock()

    @discord.ui.button(label="再擲一次", emoji="🎲", style=discord.ButtonStyle.primary)
    async def reroll(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        async with self._lock:
            if interaction.user.id != self.author_id:
                await InteractionResponder.safe_send(interaction, "❌ 此按鈕僅限投擲者操作喔！", ephemeral=True)
                return

            rolls = [random.randint(1, self.sides) for _ in range(self.count)]
            total = sum(rolls)
            crit = "🔥 完美大成功！" if (self.sides == 20 and 20 in rolls) else ""

            card = ZNCard(
                title=f"🎲 擲骰子 ({self.count}d{self.sides})",
                description=f"**點數明細**：`{rolls}`\n# 總點數：**{total}** {crit}",
                status_pill=ZNStatusPill.FUN,
                color=ZNColor.SUCCESS,
            )
            await InteractionResponder.safe_edit(interaction, card=card, view=self)

    async def on_timeout(self) -> None:
        for child in self.children:
            if hasattr(child, "disabled"):
                child.disabled = True
        self.stop()
        if self.message:
            try:
                await self.message.edit(view=self)
            except (discord.NotFound, discord.HTTPException, Exception):
                pass


class CoinReFlipView(discord.ui.View):
    def __init__(self, author_id: int, guess: Optional[str] = None, timeout: float = 60.0) -> None:
        super().__init__(timeout=timeout)
        self.author_id = author_id
        self.guess = guess
        self.message: Optional[discord.Message] = None
        self._lock = asyncio.Lock()

    @discord.ui.button(label="再丟一次", emoji="🪙", style=discord.ButtonStyle.primary)
    async def reflip(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        async with self._lock:
            if interaction.user.id != self.author_id:
                await InteractionResponder.safe_send(interaction, "❌ 此按鈕僅限投擲者操作喔！", ephemeral=True)
                return

            is_heads = random.choice([True, False])
            result_str = "正面" if is_heads else "反面"
            icon = "🟡" if is_heads else "⚪"

            guess_feedback = ""
            color = ZNColor.INFO
            if self.guess:
                if self.guess == result_str:
                    guess_feedback = "\n🎉 恭喜猜中了！神準的直覺！"
                    color = ZNColor.SUCCESS
                else:
                    guess_feedback = "\n💨 哎呀猜錯了，幸運女神正在路上～"
                    color = ZNColor.WARNING

            card = ZNCard(
                title="🪙 拋擲硬幣結果",
                description=f"硬幣在空中高高旋轉翻騰，清脆地落在手背上……\n# {icon} **{result_str}** (Heads/Tails){guess_feedback}",
                status_pill=ZNStatusPill.FUN,
                color=color,
            )
            await InteractionResponder.safe_edit(interaction, card=card, view=self)

    async def on_timeout(self) -> None:
        for child in self.children:
            if hasattr(child, "disabled"):
                child.disabled = True
        self.stop()
        if self.message:
            try:
                await self.message.edit(view=self)
            except (discord.NotFound, discord.HTTPException, Exception):
                pass


class ChooseAgainView(discord.ui.View):
    def __init__(self, author_id: int, options: List[str], timeout: float = 60.0) -> None:
        super().__init__(timeout=timeout)
        self.author_id = author_id
        self.options = options
        self.message: Optional[discord.Message] = None
        self._lock = asyncio.Lock()

    @discord.ui.button(label="命運重抽！", emoji="🔄", style=discord.ButtonStyle.primary)
    async def rechoose(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        async with self._lock:
            if interaction.user.id != self.author_id:
                await InteractionResponder.safe_send(interaction, "❌ 此按鈕僅限發起人操作喔！", ephemeral=True)
                return

            pick = random.choice(self.options)
            quips = [
                "猶豫就會敗北，ZeroNexus 幫你下定決心了！",
                "命運之輪再次轉動，就選這個準沒錯！",
                "直覺告訴我，這就是最好的解答！",
            ]
            card = ZNCard(
                title="🎯 幫我選 — 命運抉擇",
                description=f"候選項目：`{', '.join(self.options)}`\n\nZeroNexus 的裁定是：\n# 👉 **{pick}**\n\n*{random.choice(quips)}*",
                status_pill=ZNStatusPill.FUN,
                color=ZNColor.SUCCESS,
            )
            await InteractionResponder.safe_edit(interaction, card=card, view=self)

    async def on_timeout(self) -> None:
        for child in self.children:
            if hasattr(child, "disabled"):
                child.disabled = True
        self.stop()
        if self.message:
            try:
                await self.message.edit(view=self)
            except (discord.NotFound, discord.HTTPException, Exception):
                pass


# =============================================================================
# Entertainment Module & Cog
# =============================================================================

class EntertainmentModule(BaseModule):
    """Games, Economy, and Community Entertainment."""

    def __init__(self) -> None:
        super().__init__(
            name="entertainment",
            display_name="娛樂模組",
            description="互動棋盤小遊戲 (井字棋/四子棋)、21點、水果拉霸、猜拳、數字炸彈、運勢占卜與社群虛擬經濟",
        )

    async def initialize(self, bot: Any) -> None:
        commands_list = [
            ("拉霸機", "經典三軸水果拉霸機，下注拼大獎", ZNPermissionLevel.EVERYONE),
            ("槽位拉霸", "水果拉霸機 (同 /娛樂 拉霸機)", ZNPermissionLevel.EVERYONE),
            ("猜拳", "剪刀石頭布互動猜拳對決 (人機或雙人 PvP)", ZNPermissionLevel.EVERYONE),
            ("剪刀石頭布", "剪刀石頭布 (同 /娛樂 猜拳)", ZNPermissionLevel.EVERYONE),
            ("數字炸彈", "經典範圍數字炸彈 (終極密碼)", ZNPermissionLevel.EVERYONE),
            ("終極密碼", "終極密碼 (同 /娛樂 數字炸彈)", ZNPermissionLevel.EVERYONE),
            ("丟硬幣", "拋擲一枚硬幣判定正反面", ZNPermissionLevel.EVERYONE),
            ("拋硬幣", "拋硬幣 (同 /娛樂 丟硬幣)", ZNPermissionLevel.EVERYONE),
            ("骰子", "投擲自訂數量與面數之骰子", ZNPermissionLevel.EVERYONE),
            ("擲骰子", "擲骰子 (同 /娛樂 骰子)", ZNPermissionLevel.EVERYONE),
            ("幫我選", "在多個選項中由 ZeroNexus 為您定奪", ZNPermissionLevel.EVERYONE),
            ("選擇困難", "選擇困難定奪 (同 /娛樂 幫我選)", ZNPermissionLevel.EVERYONE),
            ("每日簽到", "領取每日虛擬點數與累計簽到連勝", ZNPermissionLevel.EVERYONE),
            ("餘額", "檢視個人或他人點數餘額與簽到天數", ZNPermissionLevel.EVERYONE),
            ("個人錢包", "個人錢包 (同 /娛樂 餘額)", ZNPermissionLevel.EVERYONE),
            ("轉帳", "將個人虛擬點數安全轉移給他人", ZNPermissionLevel.EVERYONE),
            ("財富排行榜", "伺服器富豪排行榜總覽 TOP 10", ZNPermissionLevel.EVERYONE),
            ("21點", "完整撲克 21 點要牌停牌對決", ZNPermissionLevel.EVERYONE),
            ("井字棋", "3x3 Discord 按鈕雙人即時對弈", ZNPermissionLevel.EVERYONE),
            ("四子棋", "經典 6x7 四子棋連線棋盤對戰", ZNPermissionLevel.EVERYONE),
            ("俄羅斯輪盤", "刺激輪盤對抗，中彈者自動禁言 60 秒", ZNPermissionLevel.EVERYONE),
            ("抽籤", "今日運勢占卜與詩籤", ZNPermissionLevel.EVERYONE),
            ("猜數字", "1A2B 邏輯推理解謎遊戲", ZNPermissionLevel.EVERYONE),
            ("猜單字", "每日 Wordle 猜字推理解謎", ZNPermissionLevel.EVERYONE),
            ("海龜湯", "精選情境推理題庫與提示真相", ZNPermissionLevel.EVERYONE),
            ("趣味問答", "隨機跨領域知識搶答測驗", ZNPermissionLevel.EVERYONE),
            ("戀愛契合度", "測算兩名成員間的趣味契合指數", ZNPermissionLevel.EVERYONE),
            ("猜歌", "30 秒音樂聽力試聽搶答賽 (Components V2 按鈕搶答)", ZNPermissionLevel.EVERYONE),
            ("抽卡", "ACG 角色卡池抽卡模擬器 (單抽/十連抽/保底機制)", ZNPermissionLevel.EVERYONE),
        ]
        for name, cmd_desc, perm in commands_list:
            self.register_command_meta(CommandMetadata(
                name=name,
                full_name=f"娛樂 {name}",
                description=cmd_desc,
                group_name="娛樂",
                module_name=self.name,
                permission_level=perm,
            ))

    async def shutdown(self) -> None:
        pass


class Guess1A2BSession:
    """Session for 1A2B Guess Number game per user."""

    def __init__(self, user_id: int) -> None:
        self.user_id = user_id
        self.target = "".join(random.sample("0123456789", 4))
        self.history: List[Tuple[str, int, int]] = []
        self.started_at = datetime.now(timezone.utc)

    def check(self, guess: str) -> Tuple[int, int]:
        a = sum(1 for i in range(4) if guess[i] == self.target[i])
        b = sum(1 for ch in guess if ch in self.target) - a
        self.history.append((guess, a, b))
        return a, b


_1A2B_SESSIONS: Dict[int, Guess1A2BSession] = {}


class EntertainmentCog(commands.Cog):
    """Discord Slash Command Group for /娛樂."""

    fun_group = app_commands.Group(name="娛樂", description="趣味小遊戲、占卜與虛擬經濟指令群組")

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self._active_music_quizzes: Dict[int, MusicGuessQuizView] = {}
        self._active_gacha_views: Dict[int, ACGGachaView] = {}

    # =========================================================================
    # 1. 拉霸機 (/娛樂 拉霸機)
    # =========================================================================
    @fun_group.command(name="拉霸機", description="經典三軸水果拉霸機，下注拼大獎！")
    @app_commands.describe(下注="下注點數 (1~50,000，預設 10)")
    @command_guard("entertainment")
    async def slots_command(self, interaction: discord.Interaction, 下注: int = 10) -> None:
        if 下注 <= 0:
            await InteractionResponder.safe_send(interaction, "❌ 下注點數必須大於 0 點！", ephemeral=True)
            return
        if 下注 > 50000:
            await InteractionResponder.safe_send(interaction, "❌ 單次下注上限為 50,000 點數。", ephemeral=True)
            return

        async with db.session() as session:
            wallet = await _get_or_create_wallet(session, interaction.user.id)
            if wallet.points < 下注:
                await InteractionResponder.safe_send(
                    interaction,
                    f"❌ 您的點數餘額不足！目前錢包僅有 **{wallet.points:,} 點數**，無法下注 `{下注:,}` 點數。\n請先使用 `/娛樂 每日簽到` 領取補貼！",
                    ephemeral=True,
                )
                return

            # Atomic deduct
            stmt_deduct = (
                update(EconomyWallet)
                .where(EconomyWallet.user_id == interaction.user.id, EconomyWallet.points >= 下注)
                .values(points=EconomyWallet.points - 下注)
            )
            res = await session.execute(stmt_deduct)
            if res.rowcount == 0:
                await InteractionResponder.safe_send(interaction, "❌ 點數扣除失敗，餘額不足。", ephemeral=True)
                return

            # Spin
            s1, s2, s3 = random.choices(SlotMachineView.SYMBOLS, weights=SlotMachineView.WEIGHTS, k=3)
            win_mult = 0
            win_title = "💨 銘謝惠顧！"
            win_color = ZNColor.DARK

            if s1 == s2 == s3:
                if s1 == "7️⃣":
                    win_mult = 50
                    win_title = "👑 驚天大獎！JACKPOT 777！！"
                    win_color = discord.Color.gold()
                elif s1 == "💎":
                    win_mult = 20
                    win_title = "💎 璀璨鑽石大獎！"
                    win_color = discord.Color.teal()
                elif s1 == "⭐":
                    win_mult = 12
                    win_title = "⭐ 幸運星輝大獎！"
                    win_color = discord.Color.purple()
                elif s1 == "🔔":
                    win_mult = 8
                    win_title = "🔔 歡樂金鈴大獎！"
                    win_color = ZNColor.SUCCESS
                else:
                    win_mult = 5
                    win_title = "🍇 水果滿貫大三元！"
                    win_color = ZNColor.SUCCESS
            elif s1 == s2 or s2 == s3 or s1 == s3:
                win_mult = 2
                win_title = "✨ 雙星連線小獎！"
                win_color = ZNColor.INFO

            win_amount = 下注 * win_mult
            if win_amount > 0:
                stmt_win = (
                    update(EconomyWallet)
                    .where(EconomyWallet.user_id == interaction.user.id)
                    .values(points=EconomyWallet.points + win_amount)
                )
                await session.execute(stmt_win)

            stmt_bal = select(EconomyWallet.points).where(EconomyWallet.user_id == interaction.user.id)
            bal_res = await session.execute(stmt_bal)
            current_bal = bal_res.scalar() or 0

        net_gain = win_amount - 下注
        net_str = f"+{net_gain:,}" if net_gain >= 0 else f"{net_gain:,}"

        card = ZNCard(
            title=f"🎰 水果拉霸機 — {win_title}",
            description=(
                f"# [  {s1}  |  {s2}  |  {s3}  ]\n\n"
                f"**本局押注**：`{下注:,} 點數`\n"
                f"**贏得彩金**：`{win_amount:,} 點數` (淨收益: **{net_str}**)\n"
                f"**錢包總餘額**：💰 **{current_bal:,} 點數**"
            ),
            status_pill=ZNStatusPill.FUN,
            color=win_color,
        )
        view = SlotMachineView(author_id=interaction.user.id, bet=下注)
        msg = await InteractionResponder.safe_send(interaction, card=card, view=view)
        if msg:
            view.message = msg

    # =========================================================================
    # 2. 剪刀石頭布 / 猜拳 (/娛樂 猜拳)
    # =========================================================================
    @fun_group.command(name="猜拳", description="剪刀石頭布互動猜拳對決 (可單人或邀請好友 PvP)")
    @app_commands.describe(對象="邀請對決的成員 (留空則與 ZeroNexus 對戰)")
    @command_guard("entertainment")
    async def rps_command(self, interaction: discord.Interaction, 對象: Optional[discord.Member] = None) -> None:
        if 對象 is not None:
            if 對象.id == interaction.user.id:
                await InteractionResponder.safe_send(interaction, "❌ 無法與自己進行雙人猜拳，請邀請其他朋友或直接挑戰 ZeroNexus！", ephemeral=True)
                return
            if 對象.bot:
                await InteractionResponder.safe_send(interaction, "❌ 若想挑戰機器人，請直接留空對象參數即可對戰 ZeroNexus！", ephemeral=True)
                return

            view = PvPRPSView(p1=interaction.user, p2=對象)
            card = ZNCard(
                title="⚔️ 雙人猜拳挑戰展開！",
                description=f"{interaction.user.mention} 向 {對象.mention} 發起了猜拳挑戰！\n請雙方點擊下方按鈕進行**秘密盲選出拳**：",
                status_pill=ZNStatusPill.FUN,
                color=ZNColor.PRIMARY,
            )
            msg = await InteractionResponder.safe_send(interaction, card=card, view=view)
            if msg:
                view.message = msg
        else:
            view_bot = RPSView(author_id=interaction.user.id)
            card = ZNCard(
                title="✊✌️🖐️ 猜拳對決 (vs ZeroNexus)",
                description="請點擊下方按鈕出拳：",
                status_pill=ZNStatusPill.FUN,
                color=ZNColor.INFO,
            )
            msg = await InteractionResponder.safe_send(interaction, card=card, view=view_bot)
            if msg:
                view_bot.message = msg


    # =========================================================================
    # 3. 數字炸彈 / 終極密碼 (/娛樂 數字炸彈)
    # =========================================================================
    @fun_group.command(name="數字炸彈", description="經典範圍數字炸彈 (終極密碼)")
    @app_commands.describe(猜測數字="輸入 1~100 內的整數 (若未輸入則開啟互動按鈕)")
    @command_guard("entertainment")
    async def number_bomb_command(self, interaction: discord.Interaction, 猜測數字: Optional[int] = None) -> None:
        cid = interaction.channel_id or interaction.user.id
        now_ts = time.time()
        # 清理超過 2 小時或結束超過 10 分鐘的炸彈局，防範記憶體洩漏
        expired_cids = [c for c, s in _BOMB_SESSIONS.items() if (now_ts - getattr(s, "created_at", 0) > 7200) or (not s.active and now_ts - getattr(s, "created_at", 0) > 600)]
        for c in expired_cids:
            _BOMB_SESSIONS.pop(c, None)

        session = _BOMB_SESSIONS.get(cid)
        if session and session.view:
            session.view.stop()

        if session is None or not session.active:
            session = NumberBombSession(channel_id=cid)
            _BOMB_SESSIONS[cid] = session

        view = NumberBombView(session)
        session.view = view

        if 猜測數字 is not None:
            await session.process_guess(interaction, 猜測數字)
        else:
            card = session.render_card("👉 遊戲進行中！點擊下方 **[ 💥 我要拆彈！ ]** 按鈕即可輸入數字！")
            msg = await InteractionResponder.safe_send(interaction, card=card, view=view)
            if msg:
                session.message = msg


    # =========================================================================
    # 4. 丟硬幣 (/娛樂 丟硬幣)
    # =========================================================================
    @fun_group.command(name="丟硬幣", description="拋擲一枚硬幣並判定正反面")
    @app_commands.describe(猜測="可選猜測：正面 或 反面")
    @app_commands.choices(猜測=[
        app_commands.Choice(name="🟡 正面 (Heads)", value="正面"),
        app_commands.Choice(name="⚪ 反面 (Tails)", value="反面"),
    ])
    @command_guard("entertainment")
    async def coinflip_command(self, interaction: discord.Interaction, 猜測: Optional[str] = None) -> None:
        is_heads = random.choice([True, False])
        result_str = "正面" if is_heads else "反面"
        icon = "🟡" if is_heads else "⚪"

        guess_feedback = ""
        color = ZNColor.INFO
        if 猜測:
            if 猜測 == result_str:
                guess_feedback = "\n🎉 恭喜猜中了！神準的直覺！"
                color = ZNColor.SUCCESS
            else:
                guess_feedback = "\n💨 哎呀猜錯了，幸運女神正在路上～"
                color = ZNColor.WARNING

        card = ZNCard(
            title="🪙 拋擲硬幣結果",
            description=f"硬幣在空中高高旋轉翻騰，清脆地落在手背上……\n# {icon} **{result_str}** (Heads/Tails){guess_feedback}",
            status_pill=ZNStatusPill.FUN,
            color=color,
        )
        view = CoinReFlipView(author_id=interaction.user.id, guess=猜測)
        msg = await InteractionResponder.safe_send(interaction, card=card, view=view)
        if msg:
            view.message = msg


    # =========================================================================
    # 5. 骰子 (/娛樂 骰子)
    # =========================================================================
    @fun_group.command(name="骰子", description="投擲自訂數量與面數的骰子 (如 2d6, 1d20)")
    @app_commands.describe(數量="投擲骰子數量 (1~10)", 面數="骰子面數 (2~100)")
    @command_guard("entertainment")
    async def roll_command(self, interaction: discord.Interaction, 數量: int = 1, 面數: int = 6) -> None:
        count = max(1, min(10, 數量))
        sides = max(2, min(100, 面數))
        rolls = [random.randint(1, sides) for _ in range(count)]
        total = sum(rolls)
        crit = "🔥 完美大成功！" if (sides == 20 and 20 in rolls) else ""

        card = ZNCard(
            title=f"🎲 擲骰子 ({count}d{sides})",
            description=f"**點數結果**：`{rolls}`\n# 總點數：**{total}** {crit}",
            status_pill=ZNStatusPill.FUN,
            color=ZNColor.SUCCESS,
        )
        view = DiceReRollView(author_id=interaction.user.id, count=count, sides=sides)
        msg = await InteractionResponder.safe_send(interaction, card=card, view=view)
        if msg:
            view.message = msg


    # =========================================================================
    # 6. 幫我選 (/娛樂 幫我選)
    # =========================================================================
    @fun_group.command(name="幫我選", description="在多個選項中由 ZeroNexus 幫您隨機挑選")
    @app_commands.describe(選項清單="以逗號、頓號或空格分隔的選項 (如 麥當勞, 火鍋, 拉麵)")
    @command_guard("entertainment")
    async def choose_command(self, interaction: discord.Interaction, 選項清單: str) -> None:
        import re
        opts = [o.strip() for o in re.split(r"[,，\s\n/、]+", 選項清單) if o.strip()]
        if not opts:
            await InteractionResponder.safe_send(interaction, "❌ 請輸入至少一個選項。", ephemeral=True)
            return
        pick = random.choice(opts)
        card = ZNCard(
            title="🎯 幫我選 — 命運抉擇",
            description=f"候選項目：`{', '.join(opts)}`\n\nZeroNexus 為您定奪選擇了：\n# 👉 **{pick}**\n\n*猶豫就會敗北，就決定是你了！*",
            status_pill=ZNStatusPill.FUN,
            color=ZNColor.SUCCESS,
        )
        view = ChooseAgainView(author_id=interaction.user.id, options=opts)
        msg = await InteractionResponder.safe_send(interaction, card=card, view=view)
        if msg:
            view.message = msg

    # =========================================================================
    # 7. 每日簽到 (/娛樂 每日簽到)
    # =========================================================================
    @fun_group.command(name="每日簽到", description="領取每日虛擬點數與累計連續簽到獎勵")
    @command_guard("entertainment")
    async def daily_command(self, interaction: discord.Interaction) -> None:
        now = datetime.now(timezone.utc)
        async with db.session() as session:
            stmt = select(EconomyWallet).where(EconomyWallet.user_id == interaction.user.id)
            res = await session.execute(stmt)
            wallet = res.scalars().first()

            if not wallet:
                wallet = EconomyWallet(user_id=interaction.user.id, points=200, daily_streak=1, last_daily_claim=now)
                session.add(wallet)
                reward = 100
                streak = 1
                streak_msg = "🎉 歡迎首次簽到！獲得新手大禮包 100 點數！"
            else:
                last_claim = wallet.last_daily_claim
                if last_claim is not None and last_claim.tzinfo is None:
                    last_claim = last_claim.replace(tzinfo=timezone.utc)

                # Cooldown check: 20 hours
                if last_claim and (now - last_claim) < timedelta(hours=20):
                    rem = timedelta(hours=20) - (now - last_claim)
                    hrs = rem.seconds // 3600
                    mins = (rem.seconds % 3600) // 60
                    await InteractionResponder.safe_send(
                        interaction,
                        f"⏳ 您今天已經簽到過囉！請於 **{hrs} 小時 {mins} 分** 後再來領取新的一天獎勵。",
                        ephemeral=True,
                    )
                    return

                # Streak reset check: if > 48 hours, reset streak
                if last_claim and (now - last_claim) > timedelta(hours=48):
                    wallet.daily_streak = 1
                    streak_msg = "⚠️ 哎呀斷簽了！連續簽到已重置為 1 天，重新開始累積吧～"
                else:
                    wallet.daily_streak += 1
                    streak_msg = f"🔥 連續簽到連勝中！已累積 **{wallet.daily_streak} 天**！"

                streak = wallet.daily_streak
                base_reward = 100
                streak_bonus = min(200, streak * 15)
                milestone_bonus = 0

                if streak == 7:
                    milestone_bonus = 150
                    streak_msg += "\n🌟 達成連續 7 天簽到里程碑！加贈 150 點紅包！"
                elif streak == 14:
                    milestone_bonus = 300
                    streak_msg += "\n🌟 達成連續 14 天簽到里程碑！加贈 300 點紅包！"
                elif streak == 30:
                    milestone_bonus = 500
                    streak_msg += "\n👑 達成連續 30 天月簽到成就！加贈 500 點巨額彩金！"

                reward = base_reward + streak_bonus + milestone_bonus
                wallet.points += reward
                wallet.last_daily_claim = now

            total_pts = wallet.points

        card = ZNCard(
            title="📅 每日簽到成功！",
            description=(
                f"**獲得獎勵**：`+{reward:,} 點數`\n"
                f"**目前錢包總額**：💰 **{total_pts:,} 點數**\n\n"
                f"{streak_msg}"
            ),
            status_pill=ZNStatusPill.SUCCESS,
            color=ZNColor.SUCCESS,
        )
        await InteractionResponder.safe_send(interaction, card=card)

    # =========================================================================
    # 8. 餘額查詢 (/娛樂 餘額)
    # =========================================================================
    @fun_group.command(name="餘額", description="檢視個人或伺服器成員的虛擬點數錢包與簽到天數")
    @app_commands.describe(成員="欲查詢的成員 (留空則查詢自己)")
    @command_guard("entertainment")
    async def balance_command(self, interaction: discord.Interaction, 成員: Optional[discord.Member] = None) -> None:
        target = 成員 or interaction.user
        async with db.session() as session:
            stmt = select(EconomyWallet).where(EconomyWallet.user_id == target.id)
            res = await session.execute(stmt)
            wallet = res.scalars().first()
            pts = wallet.points if wallet else 100
            streak = wallet.daily_streak if wallet else 0

        card = ZNCard(
            title=f"💰 {target.display_name} 的虛擬錢包",
            description=(
                f"# 點數餘額：**{pts:,} 點**\n\n"
                f"**累計連續簽到**：`{streak} 天`\n"
                f"**會員狀態**：{'👑 伺服器富豪榜競爭者' if pts >= 1000 else '🌱 努力累積財富中'}"
            ),
            status_pill=ZNStatusPill.FUN,
            color=ZNColor.SUCCESS,
        )
        await InteractionResponder.safe_send(interaction, card=card)


    # =========================================================================
    # 9. 玩家轉帳 (/娛樂 轉帳)
    # =========================================================================
    @fun_group.command(name="轉帳", description="安全轉移個人虛擬點數給其他成員")
    @app_commands.describe(對象="接收轉帳的成員", 金額="轉帳點數 (大於 0)", 備註="可選的轉帳備註留言")
    @command_guard("entertainment")
    async def transfer_command(
        self,
        interaction: discord.Interaction,
        對象: discord.Member,
        金額: int,
        備註: Optional[str] = None,
    ) -> None:
        if 金額 <= 0 or 金額 > 10**12:
            await InteractionResponder.safe_send(interaction, "❌ 轉帳金額必須大於 0 且在合理數值範圍內 (<= 10^12)。", ephemeral=True)
            return
        if 對象.id == interaction.user.id or 對象.bot:
            await InteractionResponder.safe_send(interaction, "❌ 無法轉帳給自己或機器人帳號。", ephemeral=True)
            return

        async with db.session() as session:
            # 1. Ensure sender wallet exists
            await _get_or_create_wallet(session, interaction.user.id)

            # 2. Atomic conditional decrement to eliminate TOCTOU double-spending
            stmt_deduct = (
                update(EconomyWallet)
                .where(EconomyWallet.user_id == interaction.user.id, EconomyWallet.points >= 金額)
                .values(points=EconomyWallet.points - 金額)
            )
            deduct_res = await session.execute(stmt_deduct)
            if deduct_res.rowcount == 0:
                await InteractionResponder.safe_send(interaction, "❌ 您的點數餘額不足，無法完成此筆轉帳。", ephemeral=True)
                return

            # 3. Credit recipient wallet atomically
            stmt_recv = select(EconomyWallet).where(EconomyWallet.user_id == 對象.id)
            recv_res = await session.execute(stmt_recv)
            recv_wallet = recv_res.scalars().first()
            if not recv_wallet:
                recv_wallet = EconomyWallet(user_id=對象.id, points=100 + 金額)
                session.add(recv_wallet)
            else:
                recv_wallet.points += 金額

            # 4. Get updated sender balance
            stmt_rem = select(EconomyWallet.points).where(EconomyWallet.user_id == interaction.user.id)
            rem_res = await session.execute(stmt_rem)
            remaining_pts = rem_res.scalar() or 0

        note_str = f"\n**轉帳留言**：`{備註}`" if 備註 else ""
        card = ZNCard(
            title="💸 轉帳交易成功",
            description=(
                f"已成功將 **{金額:,} 點數** 轉移給 {對象.mention}！{note_str}\n\n"
                f"**您目前的剩餘餘額**：💰 **{remaining_pts:,} 點數**"
            ),
            status_pill=ZNStatusPill.SUCCESS,
            color=ZNColor.SUCCESS,
        )
        await InteractionResponder.safe_send(interaction, card=card)

    # =========================================================================
    # 10. 財富排行榜 (/娛樂 財富排行榜)
    # =========================================================================
    @fun_group.command(name="財富排行榜", description="檢視伺服器富豪財富排行榜 TOP 10")
    @command_guard("entertainment")
    async def wealth_leaderboard_command(self, interaction: discord.Interaction) -> None:
        async with db.session() as session:
            stmt = select(EconomyWallet).order_by(desc(EconomyWallet.points)).limit(10)
            res = await session.execute(stmt)
            wallets = res.scalars().all()

        medals = {0: "🥇", 1: "🥈", 2: "🥉"}
        lines = []
        for i, w in enumerate(wallets):
            rank_icon = medals.get(i, f"`#{i+1}`")
            lines.append(f"{rank_icon} <@{w.user_id}> — **{w.points:,} 點數** (連簽 {w.daily_streak} 天)")

        card = ZNCard(
            title="🏆 伺服器財富排行榜 (TOP 10)",
            description="\n".join(lines) if lines else "目前尚無財富資料。",
            status_pill=ZNStatusPill.FUN,
            color=ZNColor.PRIMARY,
        )
        await InteractionResponder.safe_send(interaction, card=card)

    # =========================================================================
    # 11. 21點 (/娛樂 21點)
    # =========================================================================
    @fun_group.command(name="21點", description="與 ZeroNexus 進行經典撲克 21 點互動對決")
    @command_guard("entertainment")
    async def blackjack_command(self, interaction: discord.Interaction) -> None:
        view = BlackjackView(author_id=interaction.user.id)
        p_score = view.calc_score(view.player_hand)
        d_first = view.dealer_hand[0]

        card = ZNCard(
            title="♠️ 撲克 21 點 (Blackjack)",
            description=(
                f"**您的手牌**：{view.format_hand(view.player_hand)} (點數: **{p_score}**)\n"
                f"**莊家明牌**：`[{d_first[1]}{d_first[0]}]` `[🂠 ?]`\n\n"
                f"請點擊下方按鈕選擇要牌或停牌："
            ),
            status_pill=ZNStatusPill.FUN,
            color=ZNColor.PRIMARY,
        )
        msg = await InteractionResponder.safe_send(interaction, card=card, view=view)
        if msg:
            view.message = msg

    # =========================================================================
    # 12. 井字棋 (/娛樂 井字棋)
    # =========================================================================
    @fun_group.command(name="井字棋", description="透過按鈕進行雙人井字棋對弈")
    @app_commands.describe(對手="邀請對戰的伺服器成員")
    @command_guard("entertainment")
    async def tictactoe_command(self, interaction: discord.Interaction, 對手: discord.Member) -> None:
        if 對手.id == interaction.user.id or 對手.bot:
            await InteractionResponder.safe_send(interaction, "❌ 請邀請另一位非機器人的伺服器夥伴對弈。", ephemeral=True)
            return

        view = TicTacToeView(interaction.user, 對手)
        content = f"🎮 **井字棋對決展開**！\n{interaction.user.mention} (X) vs {對手.mention} (O)\n輪到 {interaction.user.mention} 先手落子！"
        msg = await InteractionResponder.safe_send(interaction, content=content, view=view)
        if msg:
            view.message = msg

    # =========================================================================
    # 13. 四子棋 (/娛樂 四子棋)
    # =========================================================================
    @fun_group.command(name="四子棋", description="發起經典 6x7 四子棋連線棋盤對戰")
    @app_commands.describe(對手="邀請對戰的伺服器成員")
    @command_guard("entertainment")
    async def connect4_command(self, interaction: discord.Interaction, 對手: discord.Member) -> None:
        if 對手.id == interaction.user.id or 對手.bot:
            await InteractionResponder.safe_send(interaction, "❌ 請邀請另一位非機器人的伺服器夥伴對弈。", ephemeral=True)
            return

        view = Connect4View(interaction.user, 對手)
        card = ZNCard(
            title="🔴🟡 四子棋連線對弈",
            description=f"{view.render_board()}\n\n👉 輪到 {interaction.user.mention} (🔴) 先手落子！",
            status_pill=ZNStatusPill.FUN,
            color=ZNColor.PRIMARY,
        )
        msg = await InteractionResponder.safe_send(interaction, card=card, view=view)
        if msg:
            view.message = msg

    # =========================================================================
    # 14. 俄羅斯輪盤 (/娛樂 俄羅斯輪盤)
    # =========================================================================
    @fun_group.command(name="俄羅斯輪盤", description="刺激輪盤對抗，中彈者自動禁言 60 秒")
    @command_guard("entertainment")
    async def roulette_command(self, interaction: discord.Interaction) -> None:
        bullet_chamber = random.randint(1, 6)
        shot = random.randint(1, 6)

        if shot == bullet_chamber:
            timeout_success = False
            try:
                if isinstance(interaction.user, discord.Member):
                    await interaction.user.timeout(timedelta(seconds=60), reason="俄羅斯輪盤中彈冷靜")
                    timeout_success = True
            except Exception:
                pass

            punish_text = "已被系統請去安靜喝茶 60 秒冷靜一下！" if timeout_success else "僥倖逃過了管理員的禁言神掌，但臉上已經黑成一團！"
            card = ZNCard(
                title="💥 碰！！槍聲震耳欲聾！你中彈了！",
                description=f"撞針重重扣下！\n{interaction.user.mention} 不幸命中實彈，{punish_text}",
                status_pill=ZNStatusPill.ERROR,
                color=ZNColor.ERROR,
            )
        else:
            card = ZNCard(
                title="💨 喀！撞針擊發了空膛！",
                description=f"左輪轉盤飛速旋轉……\n{interaction.user.mention} 幸運撿回了一條命！深吸一口氣大難不死！",
                status_pill=ZNStatusPill.SUCCESS,
                color=ZNColor.SUCCESS,
            )
        await InteractionResponder.safe_send(interaction, card=card)

    # =========================================================================
    # 15. 抽籤 (/娛樂 抽籤)
    # =========================================================================
    @fun_group.command(name="抽籤", description="今日運勢占卜與吉祥詩籤")
    @command_guard("entertainment")
    async def fortune_command(self, interaction: discord.Interaction) -> None:
        fortunes = [
            ("🎋 大吉", "萬事亨通，今天適合大膽推展重要專案，靈感如泉湧！", "紅色", "7", "咖啡一杯"),
            ("✨ 中吉", "順風順水，與身邊朋友溝通融洽，注意多補充水分～", "藍色", "3", "薄荷糖"),
            ("🌱 小吉", "步步為營，細節處將有意外驚喜，耐心即是最好的幸運符！", "綠色", "9", "小綠植"),
            ("🌤️ 吉", "平淡是福，無風無浪便是最好的進展，適合享受片刻悠閒。", "白色", "5", "輕音樂"),
            ("🍵 末吉", "先苦後甘，上午若有波折下午必迎轉機，保持沉著穩健！", "米色", "2", "溫熱開水"),
            ("⚡ 凶", "今日不宜衝動下重大決策，部署伺服器前請務必做備份！", "紫色", "1", "備份隨身碟"),
        ]
        title, desc_txt, lucky_color, lucky_num, lucky_item = random.choice(fortunes)
        card = ZNCard(
            title=f"今日運勢詩籤 — {title}",
            description=(
                f"{desc_txt}\n\n"
                f"🎨 **幸運顏色**：`{lucky_color}`\n"
                f"🔢 **幸運數字**：`{lucky_num}`\n"
                f"🍀 **幸運物品**：`{lucky_item}`"
            ),
            status_pill=ZNStatusPill.FUN,
            color=ZNColor.SUCCESS if "吉" in title else ZNColor.WARNING,
        )
        await InteractionResponder.safe_send(interaction, card=card)


    # =========================================================================
    # 16. 猜數字 (1A2B) (/娛樂 猜數字)
    # =========================================================================
    @fun_group.command(name="猜數字", description="經典 1A2B 邏輯推理猜數字遊戲")
    @app_commands.describe(猜測數字="輸入 4 位完全不重複的數字 (如 1234)", 重開新局="是否放棄當前題目並重開新一局")
    @command_guard("entertainment")
    async def guess_number_command(
        self,
        interaction: discord.Interaction,
        猜測數字: str,
        重開新局: bool = False,
    ) -> None:
        user_id = interaction.user.id
        now_dt = datetime.now(timezone.utc)
        # 清理逾期 1 小時未活動的舊 session，防止記憶體洩漏
        expired_uids = [uid for uid, s in _1A2B_SESSIONS.items() if (now_dt - s.started_at) > timedelta(hours=1)]
        for uid in expired_uids:
            _1A2B_SESSIONS.pop(uid, None)

        session = _1A2B_SESSIONS.get(user_id)
        if 重開新局 or session is None or (now_dt - session.started_at) > timedelta(hours=1):
            session = Guess1A2BSession(user_id)
            _1A2B_SESSIONS[user_id] = session

        cleaned = 猜測數字.strip()
        if len(cleaned) != 4 or not cleaned.isdigit() or len(set(cleaned)) != 4:
            await InteractionResponder.safe_send(interaction, "❌ 請輸入剛好 4 位完全不重複的正整數！(例如 1234)", ephemeral=True)
            return

        a, b = session.check(cleaned)
        attempts = len(session.history)

        if a == 4:
            _1A2B_SESSIONS.pop(user_id, None)
            card = ZNCard(
                title="🎉 1A2B 猜數字 — 完全答對！",
                description=(
                    f"# 恭喜神之推理！目標數字正是：**{session.target}**\n\n"
                    f"🎯 **總共耗費嘗試次數**：`{attempts} 次`\n"
                    f"可隨時再次使用 `/娛樂 猜數字` 開始全新的挑戰！"
                ),
                status_pill=ZNStatusPill.SUCCESS,
                color=ZNColor.SUCCESS,
            )
        else:
            hist_lines = [f"`#{i+1:02d}` **{g}** ➔ **{ra}A{rb}B**" for i, (g, ra, rb) in enumerate(session.history)]
            shown_hist = "\n".join(hist_lines[-6:])

            card = ZNCard(
                title=f"🔢 1A2B 猜數字 (第 {attempts} 次猜測)",
                description=(
                    f"當前猜測：`{cleaned}` ➔ # **{a}A{b}B**\n\n"
                    f"**近期猜測紀錄**：\n{shown_hist}\n\n"
                    f"💡 *繼續輸入 `/娛樂 猜數字 猜測數字:xxxx` 追擊答案！*"
                ),
                status_pill=ZNStatusPill.FUN,
                color=ZNColor.INFO,
            )
        await InteractionResponder.safe_send(interaction, card=card)

    # =========================================================================
    # 17. 猜單字 (Wordle) (/娛樂 猜單字)
    # =========================================================================
    @fun_group.command(name="猜單字", description="每日英文單字 Wordle 推理解謎")
    @app_commands.describe(單字="輸入 5 個英文字母 (如 NEXUS, BRAIN)")
    @command_guard("entertainment")
    async def wordle_command(self, interaction: discord.Interaction, 單字: str) -> None:
        cleaned = 單字.strip().lower()
        if len(cleaned) != 5 or not cleaned.isalpha():
            await InteractionResponder.safe_send(interaction, "❌ 請輸入剛好 5 個英文字母 (A-Z)。", ephemeral=True)
            return

        word_list = [
            "nexus", "apple", "smart", "brain", "cloud", "light", "focus", "tiger", "earth", "magic",
            "sound", "water", "dream", "plant", "music", "flame", "space", "power", "heart", "stone",
            "river", "ocean", "world", "green", "night", "white", "black", "house", "table", "clock",
            "bread", "train", "storm", "fruit", "glass", "smile", "peace", "guard", "sugar", "spark",
            "sword", "shield", "tower", "metal", "paper", "laser", "solar", "cyber", "ghost", "stars",
            "orbit", "pixel", "robot", "quest", "amber", "blade", "charm", "frost", "grape", "honey",
        ]
        day_index = int(datetime.now(timezone.utc).strftime("%Y%m%d")) % len(word_list)
        target = word_list[day_index]

        # Standard two-pass Wordle evaluation to handle duplicate letters accurately
        boxes = ["⬛"] * 5
        target_counts: Dict[str, int] = {}
        for ch in target:
            target_counts[ch] = target_counts.get(ch, 0) + 1

        for i in range(5):
            if cleaned[i] == target[i]:
                boxes[i] = "🟩"
                target_counts[cleaned[i]] -= 1

        for i in range(5):
            if boxes[i] != "🟩":
                ch = cleaned[i]
                if target_counts.get(ch, 0) > 0:
                    boxes[i] = "🟨"
                    target_counts[ch] -= 1

        is_win = (cleaned == target)
        card = ZNCard(
            title="🔤 Wordle 每日猜字回饋",
            description=(
                f"# {' '.join(boxes)}\n"
                f"**您的輸入**：`{cleaned.upper()}`\n\n"
                f"{'🎉 完全答對！解鎖今日單字大師！' if is_win else '🟩: 位置正確 | 🟨: 包含此字母 | ⬛: 不在此單字中'}"
            ),
            status_pill=ZNStatusPill.FUN,
            color=ZNColor.SUCCESS if is_win else ZNColor.INFO,
        )
        await InteractionResponder.safe_send(interaction, card=card)

    # =========================================================================
    # 18. 海龜湯 (/娛樂 海龜湯)
    # =========================================================================
    @fun_group.command(name="海龜湯", description="精選情境推理題目與線索")
    @command_guard("entertainment")
    async def riddle_command(self, interaction: discord.Interaction) -> None:
        riddles = [
            (
                "海龜湯：暴風雨夜的男子",
                "男子在暴風雨夜走進房間，打開燈，看了看四周，隨後絕望地關上燈自盡。請問發生了什麼事？",
                "男子是一名燈塔看守員。暴風雨夜燈塔發電機故障，他走進燈房才發現燈熄滅了，遠處海面上多艘輪船因失去航向指引觸礁沉沒。他感到無比自責與絕望，遂關燈自盡。",
            ),
            (
                "海龜湯：草地上的胡蘿蔔",
                "空曠的草地上有一條圍巾、幾塊木炭和一根胡蘿蔔，周圍沒有任何腳印。請問發生了什麼？",
                "這是在冬天堆的雪人。春天來臨氣溫回升，積雪全部融化了，只剩下當初用來裝飾雪人的圍巾、木炭眼睛和胡蘿蔔鼻子。",
            ),
            (
                "海龜湯：半根火柴",
                "男子赤身裸體死在沙漠中央，手裡緊緊握著半根折斷的火柴。請問發生了什麼？",
                "他和同伴搭乘的熱氣球發生故障下墜，為了減重大家脫光了所有衣物仍無法阻止下墜，最後眾人抽火柴決定誰必須跳下去犧牲，抽到半根火柴的他被迫跳了下去。",
            ),
            (
                "海龜湯：滿地碎玻璃與水",
                "小明回到家，發現地上有一灘水和一地碎玻璃，湯姆和傑利倒在水灘中死去了。現場沒有打鬥痕跡。請問發生了什麼？",
                "湯姆和傑利是金魚。窗外的大風吹落了擺在窗邊的玻璃魚缸，魚缸摔碎在地上，金魚離開水後窒息而亡。",
            ),
            (
                "海龜湯：一杯水與一聲巨響",
                "男子走進酒吧，向酒保要了一杯水。酒保看著他，突然拔出一把手槍對著天花板開了一槍！男子愣了一下，隨後微笑著向酒保道謝並離開了酒吧。請問為什麼？",
                "男子在劇烈打嗝。酒保看出他的困擾，用突如其來的槍聲嚇他，透過驚嚇成功治好了男子的打嗝，男子因此誠心道謝。",
            ),
            (
                "海龜湯：電梯裡的矮個子",
                "住在 10 樓的男子每天上班都搭電梯直達一樓；但下班回家時，如果電梯裡沒有其他人且外面沒有下雨，他只會搭到 7 樓，再爬 3 層樓梯回家。請問為什麼？",
                "男子的身高很矮，夠不著電梯裡 10 樓的按鈕。搭到一樓因為按鈕在最下方他按得到；下班時若有其他人可以幫忙按，下雨天他可以用隨身雨傘戳 10 樓按鈕，平時自己一人只能勉強按到 7 樓。",
            ),
            (
                "海龜湯：深夜的敲門聲",
                "一名獨居女子深夜在臥室熟睡，突然聽見規律的敲門聲。她害怕極了，不敢開門也不敢出聲，直到隔天早上警察趕到時，女子嚇得痛哭。請問發生了什麼？",
                "昨夜公寓發生了火災，鄰居為了救她瘋狂敲門示警，但女子誤以為是壞人或歹徒不敢應門，鄰居最終只能先逃生，所幸火勢在隔壁被消防隊撲滅，女子得知真相後心有餘悸。",
            ),
            (
                "海龜湯：掛在牆上的畫",
                "一名畫家在畫室裡自縊身亡。警察勘驗現場時，發現畫家腳邊沒有任何墊腳的椅子或箱子，只有一灘已蒸發的水漬。請問他是如何上吊的？",
                "畫家搬來了一大塊巨大的冰塊墊在腳下，將繩索套在脖子上後等待冰塊自然融化。融化後的水流到了排水孔，只剩下少量水漬。",
            ),
        ]
        title, prompt, truth = random.choice(riddles)
        card = ZNCard(
            title=title,
            description=f"**情境謎面**：\n{prompt}\n\n||**湯底真相**：\n{truth}|| *(點擊黑色方塊揭曉湯底)*",
            status_pill=ZNStatusPill.FUN,
            color=ZNColor.INFO,
        )
        await InteractionResponder.safe_send(interaction, card=card)

    # =========================================================================
    # 19. 趣味問答 (/娛樂 趣味問答)
    # =========================================================================
    @fun_group.command(name="趣味問答", description="隨機生活常識與科普快問快答")
    @command_guard("entertainment")
    async def trivia_command(self, interaction: discord.Interaction) -> None:
        q_list = [
            ("光速在真空中傳播的速度大約是多少？", "約為每秒 30 萬公里 (精準值為 299,792,458 m/s)"),
            ("人體最大的器官是哪一個？", "皮膚 (Skin)"),
            ("地球上最深的海溝叫什麼名字？", "馬里亞納海溝 (Mariana Trench，最深處約 11,000 公尺)"),
            ("撲克牌中哪一位國王 (K) 的畫像沒有鬍子？", "紅心 K (King of Hearts)，代表查理曼大帝"),
            ("世界上第一款電腦病毒誕生於哪一年？", "1971 年 (Creeper 病毒)"),
            ("人體中最小且最輕的骨頭位於哪裡？", "耳朵中的鐙骨 (Stapes)，長度僅約 3 毫米"),
            ("太陽系中自轉方向與公轉方向相反（順時針自轉）的行星是哪一顆？", "金星 (Venus) 以及天王星 (橫向自轉)"),
            ("世界上第一座核電廠建於哪一個國家？", "蘇聯 (奧布寧斯克核電廠，1954 年投入運行)"),
            ("大英博物館位於哪一個城市？", "英國倫敦 (London)"),
            ("化學元素週期表中，原子序號第 1 號的元素是什麼？", "氫 (Hydrogen，元素符號 H)"),
            ("企鵝主要生活在地球的哪一個半球？", "南半球 (除了加拉巴哥企鵝棲息在赤道附近外，全部分佈於南半球)"),
            ("一般大富翁（Monopoly）遊戲棋盤上共有幾格？", "40 格"),
            ("世界上面積最大的淡水湖（按表面積計算）是哪一個？", "蘇必略湖 (Lake Superior)"),
            ("世界上使用人數最多的程式語言 Python 是以什麼命名的？", "英國喜劇團體蒙提·派森 (Monty Python)"),
            ("人體的心臟通常有幾個心室與心房？", "4 個（左心房、右心房、左心室、右心室）"),
            ("世界上最高的山峰聖母峰（珠穆朗瑪峰）海拔高度約多少公尺？", "8,848.86 公尺"),
            ("藍鯨的心臟大約有一輛什麼交通工具的大小？", "一輛小型汽車 (約重達 180 公斤)"),
            ("國際象棋中，棋盤上一共有多少個黑白相間的格子？", "64 格 (8x8)"),
            ("DNA 的雙螺旋結構是由哪兩位科學家於 1953 年共同發表的？", "詹姆斯·華生 (James Watson) 與 法蘭西斯·克里克 (Francis Crick)"),
            ("奧林匹克五環標誌中的五種顏色分別是什麼？", "藍、黃、黑、綠、紅（代表五大洲）"),
        ]
        q, a = random.choice(q_list)
        card = ZNCard(
            title="🧠 知識快問快答",
            description=f"**題目**：\n{q}\n\n||**答案**：{a}|| *(點擊黑色方塊查看答案)*",
            status_pill=ZNStatusPill.FUN,
            color=ZNColor.INFO,
        )
        await InteractionResponder.safe_send(interaction, card=card)

    # =========================================================================
    # 20. 戀愛契合度 (/娛樂 戀愛契合度)
    # =========================================================================
    @fun_group.command(name="戀愛契合度", description="測算兩名成員間的趣味契合度")
    @app_commands.describe(對象="要測算的目標成員")
    @command_guard("entertainment")
    async def love_command(self, interaction: discord.Interaction, 對象: discord.Member) -> None:
        if interaction.user.id == 對象.id:
            card = ZNCard(
                title="💖 終極自愛指數測算",
                description=(
                    f"{interaction.user.mention} 測算了與自己的契合度：\n"
                    f"# **100% 完美自愛！**\n\n"
                    f"💖 「愛自己，是終生浪漫的開始。」\n"
                    f"無論何時，你都是世界上最值得被好好珍視、最獨一無二的存在！✨"
                ),
                status_pill=ZNStatusPill.FUN,
                color=discord.Color.from_rgb(255, 105, 180),
            )
            await InteractionResponder.safe_send(interaction, card=card)
            return

        # Stable deterministic score across bot restarts using SHA-256
        u1, u2 = sorted([interaction.user.id, 對象.id])
        hash_digest = hashlib.sha256(f"zn-love-{u1}-{u2}".encode("utf-8")).hexdigest()
        pct = (int(hash_digest[:8], 16) % 100) + 1

        if pct >= 90:
            comment = "💖 天生一對！默契滿分，宛如命定般的靈魂伴侶！"
            card_color = discord.Color.from_rgb(255, 105, 180)
        elif pct >= 70:
            comment = "✨ 相談甚歡！志趣相投，在一起總有說不完的話題～"
            card_color = discord.Color.from_rgb(255, 140, 180)
        elif pct >= 40:
            comment = "🌱 互補互助！雖然偶爾理念不同，但能擦出奇妙的火花！"
            card_color = discord.Color.from_rgb(255, 180, 200)
        else:
            comment = "⚡ 歡喜冤家！見面少不了鬥嘴，但在關鍵時刻特別有默契！"
            card_color = discord.Color.from_rgb(220, 150, 180)

        card = ZNCard(
            title="❤️ 戀愛契合度測算",
            description=(
                f"{interaction.user.mention} 與 {對象.mention} 的契合指數：\n"
                f"# **{pct}%**\n\n"
                f"{comment}"
            ),
            status_pill=ZNStatusPill.FUN,
            color=card_color,
        )
        await InteractionResponder.safe_send(interaction, card=card)

    # --------------------------------------------------------------------------
    # 28. 30秒音樂猜歌搶答賽 guess_song
    # --------------------------------------------------------------------------
    @fun_group.command(name="猜歌", description="30 秒音樂聽力試聽搶答賽 (Components V2 按鈕搶答)")
    @command_guard("entertainment")
    async def guess_song_command(self, interaction: discord.Interaction) -> None:
        # 狀態機防禦：若本頻道已有進行中且未結束的猜歌搶答賽，防止衝突與懸掛
        cid = interaction.channel_id
        if cid in self._active_music_quizzes:
            existing_quiz = self._active_music_quizzes[cid]
            if not existing_quiz._answered and not existing_quiz.is_finished():
                await InteractionResponder.safe_send(
                    interaction,
                    "⚠️ 本頻道已有正在進行中的 30 秒音樂猜歌搶答賽，請等待本題結束後再發起新題目！",
                    ephemeral=True,
                )
                return

        if not await InteractionResponder.safe_defer(interaction):
            return

        popular_queries = [
            "周杰倫", "告五人", "YOASOBI", "米津玄師", "Taylor Swift",
            "Aimer", "宇多田光", "蔡依林", "五月天", "Ed Sheeran", "Adele", "LiSA",
        ]
        target_q = random.choice(popular_queries)
        res = await free_apis.search_music_preview(track_name=target_q, limit=10)
        tracks = res.get("results", []) if res.get("status") == "SUCCESS" else []
        valid_tracks = [t for t in tracks if t.get("preview_url") and t.get("track_name")]

        if len(valid_tracks) < 4:
            # Fallback query
            res2 = await free_apis.search_music_preview(track_name="Hits", limit=15)
            valid_tracks = [t for t in res2.get("results", []) if t.get("preview_url") and t.get("track_name")]

        if len(valid_tracks) < 4:
            card = ZNCard(
                title="猜歌題目取得失敗",
                description="暫時無法向音樂串流服務獲取足夠之 30 秒試聽題目，請稍後再試。",
                status_pill=ZNStatusPill.ERROR,
                color=ZNColor.ERROR,
            )
            await InteractionResponder.safe_send(interaction, card=card)
            return

        correct = random.choice(valid_tracks)
        distractors = [t for t in valid_tracks if t["track_name"] != correct["track_name"]]
        random.shuffle(distractors)
        chosen_distractors = distractors[:3]

        options = [correct["track_name"]] + [d["track_name"] for d in chosen_distractors]
        random.shuffle(options)

        quiz_view = MusicGuessQuizView(
            author_id=interaction.user.id,
            correct_title=correct["track_name"],
            artist=correct.get("artist_name", "未知歌手"),
            options=options,
            preview_url=correct["preview_url"],
            timeout=35.0,
        )
        self._active_music_quizzes[cid] = quiz_view

        card = ZNCard(
            title="🎵 30 秒音樂猜歌搶答賽開始！",
            description=(
                "點擊下方連結聆聽 30 秒音訊串流，搶先點擊正確歌名按鈕者可獲 **+50 點數** 獎勵！\n\n"
                f"- **歌手提示**：`{correct.get('artist_name')}`\n"
                f"- **所屬專輯**：`{correct.get('album_name')}`\n"
                f"🔗 **[點擊此處聆聽 30 秒試聽串流音訊]({correct['preview_url']})**\n\n"
                f"*(作答倒數 35 秒，請由下方 4 個選項中搶答！)*"
            ),
            thumbnail_url=correct.get("artwork_url"),
            status_pill=ZNStatusPill.FUN,
            color=ZNColor.PRIMARY,
        )
        msg_obj = await InteractionResponder.safe_send(interaction, card=card, view=quiz_view)
        if msg_obj and hasattr(quiz_view, "message"):
            quiz_view.message = msg_obj

    # --------------------------------------------------------------------------
    # 29. ACG 手遊抽卡模擬器 gacha
    # --------------------------------------------------------------------------
    @fun_group.command(name="抽卡", description="ACG 角色卡池抽卡模擬器 (單抽/十連抽/保底機制)")
    @command_guard("entertainment")
    async def gacha_command(self, interaction: discord.Interaction) -> None:
        uid = interaction.user.id
        if uid in self._active_gacha_views:
            old_gacha = self._active_gacha_views[uid]
            if not old_gacha.is_finished():
                for item in old_gacha.children:
                    if hasattr(item, "disabled"):
                        item.disabled = True
                old_gacha.stop()
                if old_gacha.message:
                    try:
                        await old_gacha.message.edit(view=old_gacha)
                    except (discord.NotFound, discord.HTTPException, Exception):
                        pass

        gacha_view = ACGGachaView(author_id=interaction.user.id, timeout=90.0)
        self._active_gacha_views[uid] = gacha_view

        card = ZNCard(
            title=f"✨ 星願祈願卡池 ➔ {interaction.user.display_name}",
            description=(
                "歡迎光臨 **ZeroNexus ACG 角色祈願模擬器**！\n\n"
                "• 🟡 **5星角色 (UR)**：`0.6%` (90 抽必中傳奇)\n"
                "• 🟣 **4星角色 (SR)**：`5.1%` (10 抽必中史詩)\n"
                "• 🔵 **3星武器 (R)**：`94.3%`\n\n"
                "每次單抽消耗 **160 點數**，十連抽消耗 **1600 點數**。\n"
                "點擊下方按鈕開始祈願！"
            ),
            status_pill=ZNStatusPill.FUN,
            color=ZNColor.PURPLE,
        )
        msg_obj = await InteractionResponder.safe_send(interaction, card=card, view=gacha_view)
        if msg_obj and hasattr(gacha_view, "message"):
            gacha_view.message = msg_obj


class MusicGuessQuizView(discord.ui.View):
    """30-second Music Guessing Quiz View using Components V2 buttons."""

    def __init__(
        self,
        author_id: int,
        correct_title: str,
        artist: str,
        options: List[str],
        preview_url: str,
        timeout: float = 35.0,
    ) -> None:
        super().__init__(timeout=timeout)
        self.author_id = author_id
        self.correct_title = correct_title
        self.artist = artist
        self.preview_url = preview_url
        self.winner: Optional[discord.User] = None
        self._answered = False
        self.message: Optional[discord.Message] = None

        for opt in options:
            btn = discord.ui.Button(label=opt[:80], style=discord.ButtonStyle.secondary)
            btn.callback = self._make_callback(opt)
            self.add_item(btn)

    def _make_callback(self, choice: str):
        async def callback(interaction: discord.Interaction):
            if self._answered:
                await interaction.response.send_message("⌛ 本題已被其他玩家搶先答對囉！", ephemeral=True)
                return

            if choice == self.correct_title:
                self._answered = True
                self.winner = interaction.user
                self.stop()

                async with db.session() as session:
                    wallet = await _get_or_create_wallet(session, interaction.user.id)
                    wallet.points += 50
                    await session.commit()

                for item in self.children:
                    if isinstance(item, discord.ui.Button):
                        item.disabled = True
                        if item.label == self.correct_title:
                            item.style = discord.ButtonStyle.success

                win_card = ZNCard(
                    title="🎉 猜歌搶答成功！",
                    description=(
                        f"恭喜 {interaction.user.mention} 搶先答對！\n\n"
                        f"- **正確歌名**：《{self.correct_title}》\n"
                        f"- **演唱歌手**：{self.artist}\n"
                        f"- **搶答獎勵**：獲得 **+50 點數** 💰\n\n"
                        f"🔗 [再次聆聽 30 秒試聽串流]({self.preview_url})"
                    ),
                    status_pill=ZNStatusPill.SUCCESS,
                    color=ZNColor.SUCCESS,
                )
                try:
                    await interaction.response.edit_message(embed=win_card.to_embed(), view=self)
                except (discord.NotFound, discord.HTTPException, Exception):
                    pass
            else:
                await interaction.response.send_message("❌ 猜錯囉！再仔細聽聽看！", ephemeral=True)

        return callback

    async def on_timeout(self) -> None:
        if not self._answered:
            self._answered = True
            for item in self.children:
                if isinstance(item, discord.ui.Button):
                    item.disabled = True
                    if item.label == self.correct_title:
                        item.style = discord.ButtonStyle.success
            self.stop()
            timeout_card = ZNCard(
                title="⏰ 猜歌搶答時間截止",
                description=(
                    f"很可惜時間到無人答對！\n\n"
                    f"- **正確歌名**：《{self.correct_title}》\n"
                    f"- **演唱歌手**：{self.artist}\n\n"
                    f"🔗 [點此聆聽 30 秒試聽串流]({self.preview_url})"
                ),
                status_pill=ZNStatusPill.DARK,
                color=ZNColor.DARK,
            )
            if self.message:
                try:
                    await self.message.edit(embed=timeout_card.to_embed(), view=self)
                except (discord.NotFound, discord.HTTPException, Exception):
                    pass


class ACGGachaView(discord.ui.View):
    """Interactive ACG Gacha Simulator with R/SR/UR rarities and pity."""

    UR_POOL = [
        "【雷電將軍】一心淨土", "【芙寧娜】眾水的頌詩", "【流螢】裝甲薩姆",
        "【黑天鵝】記憶之手", "【愛莉希雅】真我之律者", "【初音未來】星塵歌姬",
        "【阿爾托莉雅】誓約勝利之劍", "【2B】寄葉二號B型", "【早坂愛】完美特工",
    ]
    SR_POOL = [
        "【班尼特】命運試金石", "【香菱】萬民百味", "【行秋】少年春衫",
        "【停雲】八面玲瓏", "【三月七】純美啟程", "【佩拉】冰雪之智", "【遠坂凜】魔術名門",
    ]
    R_POOL = [
        "黎明神劍", "討龍英傑譚", "黑纓槍", "沐浴光輝的法球", "幽邃鴉眼",
        "神射手之弓", "彈弓", "魔導緒論", "飛天大御劍", "白鐵大劍",
    ]

    def __init__(self, author_id: int, timeout: float = 90.0) -> None:
        super().__init__(timeout=timeout)
        self.author_id = author_id
        self.pity_sr = 0
        self.pity_ur = 0
        self.message: Optional[discord.Message] = None
        self._lock = asyncio.Lock()

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await InteractionResponder.safe_send(interaction, "❌ 此抽卡機台僅限啟動玩家操作喔！", ephemeral=True)
            return False
        return True

    def _pull_one(self) -> Tuple[str, str, int]:
        self.pity_sr += 1
        self.pity_ur += 1

        if self.pity_ur >= 90:
            self.pity_ur = 0
            self.pity_sr = 0
            return random.choice(self.UR_POOL), "UR (5星)", 5

        roll = random.random() * 100.0
        if roll < 0.6:
            self.pity_ur = 0
            self.pity_sr = 0
            return random.choice(self.UR_POOL), "UR (5星)", 5
        elif roll < (0.6 + 5.1) or self.pity_sr >= 10:
            self.pity_sr = 0
            return random.choice(self.SR_POOL), "SR (4星)", 4
        else:
            return random.choice(self.R_POOL), "R (3星)", 3

    @discord.ui.button(label="🎲 單抽 (160點)", style=discord.ButtonStyle.primary)
    async def btn_single_pull(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        async with self._lock:
            async with db.session() as session:
                wallet = await _get_or_create_wallet(session, self.author_id)
                if wallet.points < 160:
                    await InteractionResponder.safe_send(interaction, f"❌ 點數不足！單抽需要 160 點數，您目前僅有 {wallet.points:,} 點數！", ephemeral=True)
                    return
                wallet.points -= 160
                await session.commit()

            item, rarity, stars = self._pull_one()
            color = ZNColor.WARNING if stars == 5 else (ZNColor.PURPLE if stars == 4 else ZNColor.PRIMARY)
            pill = "🟡 金色傳奇！" if stars == 5 else ("🟣 紫色史詩" if stars == 4 else "🔵 普通裝備")
            star_str = "⭐" * stars

            card = ZNCard(
                title=f"🎲 祈願招募結果 ➔ {interaction.user.display_name}",
                description=(
                    f"### {star_str} **{item}**\n\n"
                    f"- **獲得品質**：{pill}\n"
                    f"- **當前保底水位**：5星保底 `{self.pity_ur}/90` | 4星保底 `{self.pity_sr}/10`\n"
                ),
                status_pill=ZNStatusPill.FUN,
                color=color,
            )
            try:
                await interaction.response.edit_message(embed=card.to_embed(), view=self)
            except (discord.NotFound, discord.HTTPException, Exception):
                pass

    @discord.ui.button(label="🎰 十連抽 (1600點)", style=discord.ButtonStyle.success)
    async def btn_ten_pull(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        async with self._lock:
            async with db.session() as session:
                wallet = await _get_or_create_wallet(session, self.author_id)
                if wallet.points < 1600:
                    await InteractionResponder.safe_send(interaction, f"❌ 點數不足！十連抽需要 1600 點數，您目前僅有 {wallet.points:,} 點數！", ephemeral=True)
                    return
                wallet.points -= 1600
                await session.commit()

            results = [self._pull_one() for _ in range(10)]
            has_ur = any(r[2] == 5 for r in results)
            has_sr = any(r[2] == 4 for r in results)

            color = ZNColor.WARNING if has_ur else (ZNColor.PURPLE if has_sr else ZNColor.PRIMARY)

            lines = []
            for idx, (item, rarity, stars) in enumerate(results, 1):
                star_emoji = "🟡" if stars == 5 else ("🟣" if stars == 4 else "⚪")
                lines.append(f"`{idx:02d}.` {star_emoji} **{'⭐'*stars}** {item}")

            card = ZNCard(
                title=f"🎰 十連祈願招募結果 ➔ {interaction.user.display_name}",
                description=(
                    "\n".join(lines)
                    + f"\n\n- **當前保底水位**：5星保底 `{self.pity_ur}/90` | 4星保底 `{self.pity_sr}/10`"
                ),
                status_pill=ZNStatusPill.FUN,
                color=color,
            )
            try:
                await interaction.response.edit_message(embed=card.to_embed(), view=self)
            except (discord.NotFound, discord.HTTPException, Exception):
                pass

    @discord.ui.button(label="📜 卡池說明", style=discord.ButtonStyle.secondary)
    async def btn_rates(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        card = ZNCard(
            title="📜 ACG 角色祈願卡池規則與機率",
            description=(
                "**機率分佈**：\n"
                "• 🟡 **5星角色 (UR)**：`0.6%` (90 抽必出)\n"
                "• 🟣 **4星角色 (SR)**：`5.1%` (10 抽必出)\n"
                "• 🔵 **3星武器 (R)**：`94.3%`\n\n"
                "**保底繼承**：\n"
                "每次抽卡均累計保底水位，抽中對應品質後自動重設計數！"
            ),
            status_pill=ZNStatusPill.INFO,
            color=ZNColor.INFO,
        )
        await interaction.response.send_message(embed=card.to_embed(), ephemeral=True)

    async def on_timeout(self) -> None:
        """Gracefully disable buttons and stop view on timeout."""
        for child in self.children:
            if hasattr(child, "disabled"):
                child.disabled = True
        self.stop()
        if self.message:
            try:
                await self.message.edit(view=self)
            except (discord.NotFound, discord.HTTPException, Exception):
                pass


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(EntertainmentCog(bot))
