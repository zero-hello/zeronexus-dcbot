"""ZeroNexus Social Interactions & Emotes Command Cog.

Fully Implemented Commands under /互動:
- 抱抱 (擁抱), 摸頭 (摸摸), 戳戳, 擊掌, 親親 (親吻), 巴掌 (打巴掌), 抱緊, 餵食
- 跳舞, 握手, 揮手, 咬咬, 讚賞 (誇誇), 哭哭 (討拍), 生氣 (氣噗噗)

Features:
- Dual-path interactive feedback buttons (回抱、反抽、害羞、遞紙巾、噴滅火器等)
- Anti-spam & double-click protection via asyncio.Lock
- Authorization check: target-exclusive replies with friendly ephemeral rejection
- Rich, randomized authentic Traditional Chinese action descriptions
- Fallback for non-target emotes (crying/angry alone or in channel)
"""

from __future__ import annotations

import asyncio
import random
from typing import Any, List, Optional

import discord
from discord import app_commands
from discord.ext import commands

from zeronexus.modules.base import BaseModule, CommandMetadata
from zeronexus.security.guard import command_guard
from zeronexus.security.permissions import ZNPermissionLevel
from zeronexus.ui.card import ZNCard
from zeronexus.ui.responder import InteractionResponder
from zeronexus.ui.theme import ZNColor, ZNStatusPill


class SocialResponseButton(discord.ui.Button["SocialResponseView"]):
    """Interactive response button allowing the target (or peers) to react back."""

    def __init__(
        self,
        action_type: str,
        label: str,
        emoji: str,
        style: discord.ButtonStyle = discord.ButtonStyle.secondary,
    ) -> None:
        super().__init__(style=style, label=label, emoji=emoji)
        self.action_type = action_type

    async def callback(self, interaction: discord.Interaction) -> None:
        assert self.view is not None
        await self.view.handle_action(interaction, self.action_type)


class SocialResponseView(discord.ui.View):
    """Interactive reaction view for social emotes with single-click lock and permissions."""

    def __init__(
        self,
        author: discord.Member,
        target: Optional[discord.Member],
        category: str,
        timeout: float = 90.0,
    ) -> None:
        super().__init__(timeout=timeout)
        self.author = author
        self.target = target
        self.category = category
        self.message: Optional[discord.Message] = None
        self._lock = asyncio.Lock()
        self._responded = False

        self._setup_buttons()

    def _setup_buttons(self) -> None:
        if self.target is None or self.target.id == self.author.id:
            # Self/ambient actions
            if self.category == "cry":
                self.add_item(SocialResponseButton("tissue", "遞上紙巾", "🧻", discord.ButtonStyle.primary))
                self.add_item(SocialResponseButton("pat_comfort", "摸摸頭不哭", "🐾", discord.ButtonStyle.success))
            elif self.category == "angry":
                self.add_item(SocialResponseButton("extinguisher", "搬出滅火器", "🧯", discord.ButtonStyle.danger))
                self.add_item(SocialResponseButton("tea", "遞杯降火茶", "🍵", discord.ButtonStyle.success))
            elif self.category == "dance":
                self.add_item(SocialResponseButton("join_dance", "一起跳舞！", "💃", discord.ButtonStyle.primary))
            return

        # Target-specific response buttons
        if self.category in ("hug", "cuddle"):
            self.add_item(SocialResponseButton("hug_back", "回抱一個", "🤗", discord.ButtonStyle.primary))
        elif self.category == "pat":
            self.add_item(SocialResponseButton("nuzzle", "蹭蹭撒嬌", "🥰", discord.ButtonStyle.primary))
        elif self.category == "slap":
            self.add_item(SocialResponseButton("slap_back", "反抽一記！", "💥", discord.ButtonStyle.danger))
            self.add_item(SocialResponseButton("beg_mercy", "揉臉求饒", "🥺", discord.ButtonStyle.secondary))
        elif self.category == "kiss":
            self.add_item(SocialResponseButton("kiss_back", "害羞親回去", "😳", discord.ButtonStyle.danger))
        elif self.category == "poke":
            self.add_item(SocialResponseButton("poke_back", "反戳回去", "👈", discord.ButtonStyle.primary))
        elif self.category == "praise":
            self.add_item(SocialResponseButton("blush_accept", "害羞收下", "🥰", discord.ButtonStyle.success))
            self.add_item(SocialResponseButton("praise_back", "你也超棒的！", "✨", discord.ButtonStyle.primary))
        elif self.category == "highfive":
            self.add_item(SocialResponseButton("clap_loud", "清脆回拍！", "✋", discord.ButtonStyle.primary))
        elif self.category == "feed":
            self.add_item(SocialResponseButton("nom_nom", "大口吃掉", "😋", discord.ButtonStyle.success))
        elif self.category == "wave":
            self.add_item(SocialResponseButton("wave_back", "熱情揮手", "👋", discord.ButtonStyle.primary))
        elif self.category == "bite":
            self.add_item(SocialResponseButton("hiss", "假裝哈氣", "😼", discord.ButtonStyle.secondary))
        elif self.category == "handshake":
            self.add_item(SocialResponseButton("grip_firm", "大力回握", "🤝", discord.ButtonStyle.primary))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if self._responded:
            await InteractionResponder.safe_send(interaction, "⚠️ 此互動已經完成回應囉！", ephemeral=True)
            return False

        # Open buttons for general comforting or dancing
        if self.target is None or self.target.id == self.author.id:
            if interaction.user.id == self.author.id:
                await InteractionResponder.safe_send(interaction, "💡 請讓其他小夥伴為您遞紙巾或消消氣吧～", ephemeral=True)
                return False
            return True

        # Target-exclusive reactions
        if interaction.user.id != self.target.id:
            await InteractionResponder.safe_send(
                interaction,
                f"❌ 這個互動按鈕是專屬給 {self.target.display_name} 的回應權限喔！",
                ephemeral=True,
            )
            return False
        return True

    async def handle_action(self, interaction: discord.Interaction, action_type: str) -> None:
        async with self._lock:
            if self._responded:
                if not interaction.response.is_done():
                    await interaction.response.defer()
                return
            self._responded = True

            # Disable all buttons on use
            for child in self.children:
                if isinstance(child, discord.ui.Button):
                    child.disabled = True

            responder_user = interaction.user
            resp_title = "✨ 互動回饋"
            resp_desc = ""
            resp_color = ZNColor.SUCCESS

            if action_type == "hug_back":
                resp_title = "🤗 溫暖回抱"
                resp_desc = f"{responder_user.mention} 溫柔地回抱了 {self.author.mention}，兩人依偎在一起超暖和～ (´▽｀)"
                resp_color = discord.Color.from_rgb(255, 140, 180)
            elif action_type == "nuzzle":
                resp_title = "🥰 蹭蹭撒嬌"
                resp_desc = f"{responder_user.mention} 乖巧地瞇起眼睛在 {self.author.mention} 的掌心蹭了蹭，好感度直線飆升！"
                resp_color = discord.Color.from_rgb(255, 182, 193)
            elif action_type == "slap_back":
                resp_title = "💥 絕地反抽！"
                resp_desc = f"{responder_user.mention} 靈巧側身閃過，順勢抄起折疊椅反抽了 {self.author.mention} 一記！「誰准你先動手的啦！」"
                resp_color = ZNColor.ERROR
            elif action_type == "beg_mercy":
                resp_title = "🥺 揉臉求饒"
                resp_desc = f"{responder_user.mention} 捂著發紅的臉頰眼角含淚看著 {self.author.mention}：「嗚嗚嗚...好痛喔，我知道錯了啦！」"
                resp_color = ZNColor.WARNING
            elif action_type == "kiss_back":
                resp_title = "😳 害羞親回去"
                resp_desc = f"{responder_user.mention} 臉紅得像熟透的番茄，悄悄踮起腳尖在 {self.author.mention} 臉頰啄了一下！///"
                resp_color = discord.Color.from_rgb(255, 105, 180)
            elif action_type == "poke_back":
                resp_title = "👈 反手戳戳"
                resp_desc = f"{responder_user.mention} 伸出手指反戳了 {self.author.mention} 的腰間好幾下：「抓到了吼！換我戳你了！」"
                resp_color = ZNColor.INFO
            elif action_type == "blush_accept":
                resp_title = "🥰 害羞收下誇獎"
                resp_desc = f"{responder_user.mention} 害羞地用雙手遮住臉：「哎呀哪有那麼棒啦～但聽到你的誇獎還是超級開心！(≧▽≦)」"
                resp_color = ZNColor.SUCCESS
            elif action_type == "praise_back":
                resp_title = "✨ 商業互吹！"
                resp_desc = f"{responder_user.mention} 大力誇讚回去：「不不不，{self.author.mention} 你才是全場最亮眼的巨佬，大家都超崇拜你的！」"
                resp_color = discord.Color.gold()
            elif action_type == "tissue":
                resp_title = "🧻 遞上溫暖紙巾"
                resp_desc = f"{responder_user.mention} 溫柔地遞上柔軟的香氛紙巾，輕輕替 {self.author.mention} 拭去淚水：「乖喔不哭不哭，有我們在呢！」"
                resp_color = ZNColor.INFO
            elif action_type == "pat_comfort":
                resp_title = "🐾 拍拍安慰"
                resp_desc = f"{responder_user.mention} 溫柔摸了摸 {self.author.mention} 的頭並輕輕拍著背：「沒事了沒事了，深呼吸～一切都會好起來的！」"
                resp_color = ZNColor.SUCCESS
            elif action_type == "extinguisher":
                resp_title = "🧯 狂噴滅火器！"
                resp_desc = f"{responder_user.mention} 扛起高壓滅火器對著頭頂冒煙的 {self.author.mention} 狂噴！嘶——火勢瞬間撲滅，全身白茫茫一片！"
                resp_color = ZNColor.PRIMARY
            elif action_type == "tea":
                resp_title = "🍵 奉上降火涼茶"
                resp_desc = f"{responder_user.mention} 雙手奉上一杯冰鎮清心菊花茶給 {self.author.mention}：「火氣太大傷身體，先喝杯涼茶順順心～」"
                resp_color = ZNColor.SUCCESS
            elif action_type == "join_dance":
                resp_title = "💃 伴舞共狂歡"
                resp_desc = f"{responder_user.mention} 興奮地加入舞台，跟著 {self.author.mention} 一起踩著動感節拍瘋狂搖擺！"
                resp_color = discord.Color.purple()
            elif action_type == "clap_loud":
                resp_title = "🙌 響亮擊掌"
                resp_desc = f"{responder_user.mention} 與 {self.author.mention} 掌心相對發出超響亮的『啪！！』一聲，默契值破表！"
                resp_color = ZNColor.SUCCESS
            elif action_type == "nom_nom":
                resp_title = "😋 滿足吃光"
                resp_desc = f"{responder_user.mention} 開心地一口吃光：「嚼嚼嚼...好好吃喔！滿滿的幸福感～」"
                resp_color = ZNColor.SUCCESS
            elif action_type == "wave_back":
                resp_title = "👋 歡樂揮手回應"
                resp_desc = f"{responder_user.mention} 滿面笑容地用力對 {self.author.mention} 揮手：「嗨嗨～好久不見呀！」"
                resp_color = ZNColor.INFO
            elif action_type == "hiss":
                resp_title = "😼 傲嬌哈氣"
                resp_desc = f"{responder_user.mention} 像隻炸毛小貓一樣後退半步發出小小的哈氣聲：「唔！下次再咬我就要出爪子囉！」"
                resp_color = ZNColor.WARNING
            elif action_type == "grip_firm":
                resp_title = "🤝 堅定回握"
                resp_desc = f"{responder_user.mention} 大力回握住 {self.author.mention} 的手：「一言為定，我們的友誼/同盟堅若磐石！」"
                resp_color = ZNColor.PRIMARY
            else:
                resp_desc = f"{responder_user.mention} 給予了回應！"

            card = ZNCard(title=resp_title, description=resp_desc, status_pill=ZNStatusPill.FUN, color=resp_color)
            self.stop()
            await InteractionResponder.safe_send(interaction, card=card)
            if self.message:
                try:
                    await self.message.edit(view=self)
                except Exception:
                    pass

    async def on_timeout(self) -> None:
        self._responded = True
        for child in self.children:
            if hasattr(child, "disabled"):
                child.disabled = True
        self.stop()
        if self.message:
            try:
                await self.message.edit(view=self)
            except (discord.NotFound, discord.HTTPException, Exception):
                pass


class InteractionsModule(BaseModule):
    """Social commands and community emote actions."""

    def __init__(self) -> None:
        super().__init__(
            name="interactions",
            display_name="互動模組",
            description="社群成員社交互動動作、動態關懷與情意表達指令",
        )

    async def initialize(self, bot: Any) -> None:
        commands_list = [
            ("抱抱", "溫暖擁抱伺服器成員", ZNPermissionLevel.EVERYONE),
            ("擁抱", "溫暖擁抱伺服器成員 (同抱抱)", ZNPermissionLevel.EVERYONE),
            ("摸頭", "溫柔摸摸成員的頭部", ZNPermissionLevel.EVERYONE),
            ("摸摸", "溫柔撫摸成員以示關愛", ZNPermissionLevel.EVERYONE),
            ("戳戳", "輕戳在線成員提醒注意", ZNPermissionLevel.EVERYONE),
            ("擊掌", "與同伴擊掌慶祝勝利", ZNPermissionLevel.EVERYONE),
            ("親親", "甜蜜親吻可愛小夥伴", ZNPermissionLevel.EVERYONE),
            ("親吻", "獻上深情親吻 (同親親)", ZNPermissionLevel.EVERYONE),
            ("巴掌", "搞笑巴掌教育調皮同伴", ZNPermissionLevel.EVERYONE),
            ("打巴掌", "搞笑掌摑調皮好友 (同巴掌)", ZNPermissionLevel.EVERYONE),
            ("抱緊", "緊緊抱住特定成員不放", ZNPermissionLevel.EVERYONE),
            ("餵食", "拿好吃的東西餵食成員", ZNPermissionLevel.EVERYONE),
            ("跳舞", "邀請成員一起歡樂共舞", ZNPermissionLevel.EVERYONE),
            ("握手", "正式握手締結友好同盟", ZNPermissionLevel.EVERYONE),
            ("揮手", "親切揮手打招呼或道別", ZNPermissionLevel.EVERYONE),
            ("咬咬", "假裝輕咬一口調皮好友", ZNPermissionLevel.EVERYONE),
            ("讚賞", "給予成員滿滿的讚賞與誇獎", ZNPermissionLevel.EVERYONE),
            ("誇誇", "大力誇誇努力表現的同伴", ZNPermissionLevel.EVERYONE),
            ("哭哭", "委屈哭哭尋求同伴拍拍安慰", ZNPermissionLevel.EVERYONE),
            ("討拍", "討拍拍尋求溫暖安慰", ZNPermissionLevel.EVERYONE),
            ("生氣", "氣噗噗表示強烈抗議或惱怒", ZNPermissionLevel.EVERYONE),
            ("氣噗噗", "鼓起腮幫子生悶氣", ZNPermissionLevel.EVERYONE),
        ]
        for name, desc, perm in commands_list:
            self.register_command_meta(CommandMetadata(
                name=name,
                full_name=f"互動 {name}",
                description=desc,
                group_name="互動",
                module_name=self.name,
                permission_level=perm,
            ))

    async def shutdown(self) -> None:
        pass


class InteractionsCog(commands.Cog):
    """Discord Slash Command Group for /互動."""

    inter_group = app_commands.Group(name="互動", description="社群社交互動與情意表達指令群組", guild_only=True)

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    def _social_card(self, title: str, desc: str, color: discord.Color = ZNColor.PRIMARY) -> ZNCard:
        return ZNCard(title=title, description=desc, status_pill=ZNStatusPill.FUN, color=color)

    async def _handle_social_action(
        self,
        interaction: discord.Interaction,
        target: Optional[discord.Member],
        category: str,
        title: str,
        normal_options: List[str],
        self_options: List[str],
        bot_options: List[str],
        none_options: Optional[List[str]] = None,
        color: discord.Color = ZNColor.PRIMARY,
    ) -> None:
        if not interaction.guild:
            await InteractionResponder.safe_send(interaction, "❌ 此社交互動指令僅限伺服器群組內使用。", ephemeral=True)
            return

        bot_id = self.bot.user.id if getattr(self.bot, "user", None) else None
        user = interaction.user

        if target is None:
            if none_options:
                desc = random.choice(none_options)
            else:
                desc = random.choice(self_options)
        elif target.id == user.id:
            desc = random.choice(self_options)
        elif bot_id is not None and target.id == bot_id:
            desc = random.choice(bot_options)
        else:
            desc = random.choice(normal_options)

        card = self._social_card(title, desc, color=color)
        view = SocialResponseView(author=user, target=target, category=category)
        msg = await InteractionResponder.safe_send(interaction, card=card, view=view)
        if msg:
            view.message = msg
        else:
            try:
                view.message = await interaction.original_response()
            except Exception:
                pass

    # =========================================================================
    # 1. 抱抱 / 擁抱 (hug)
    # =========================================================================
    @inter_group.command(name="抱抱", description="給予指定成員一個溫暖的抱抱")
    @app_commands.describe(成員="想抱抱的對象成員")
    @command_guard("interactions")
    async def hug_command(self, interaction: discord.Interaction, 成員: discord.Member) -> None:
        u, m = interaction.user.mention, 成員.mention
        await self._handle_social_action(
            interaction,
            成員,
            category="hug",
            title="🤗 溫暖抱抱",
            normal_options=[
                f"{u} 溫柔地張開雙臂，給了 {m} 一個大大的溫暖擁抱！",
                f"{u} 像隻毛茸茸的大熊一樣，把 {m} 緊緊抱在懷裡～",
                f"{u} 悄悄從身後抱住了 {m}：「捉到你了，給你滿滿的正能量！」",
                f"{u} 跑上前撲進了 {m} 的懷抱裡，蹭了個滿懷！(つ´ω`)つ",
            ],
            self_options=[
                f"{u} 給了自己一個大大的自我肯定擁抱：「今天也要好好愛自己！」",
                f"{u} 雙手環抱自己：「辛苦了，你今天已經做得非常棒囉！」",
            ],
            bot_options=[
                f"{u} 緊緊擁抱了 ZeroNexus！機體散熱核心傳來溫暖的嗡鳴運轉聲～",
                f"{u} 給了 ZeroNexus 一個大擁抱，AI 運算核心溫度瞬間上升 5°C！",
            ],
            color=discord.Color.from_rgb(255, 140, 180),
        )

    @inter_group.command(name="擁抱", description="給予指定成員溫暖擁抱 (同 /互動 抱抱)")
    @app_commands.describe(成員="想擁抱的對象成員")
    @command_guard("interactions")
    async def embrace_command(self, interaction: discord.Interaction, 成員: discord.Member) -> None:
        await self.hug_command(interaction, 成員=成員)

    # =========================================================================
    # 2. 摸頭 (pat)
    # =========================================================================
    @inter_group.command(name="摸頭", description="摸摸指定成員的頭給予鼓勵與疼愛")
    @app_commands.describe(成員="想摸頭的對象成員")
    @command_guard("interactions")
    async def pat_command(self, interaction: discord.Interaction, 成員: discord.Member) -> None:
        u, m = interaction.user.mention, 成員.mention
        await self._handle_social_action(
            interaction,
            成員,
            category="pat",
            title="🐾 溫柔摸摸頭",
            normal_options=[
                f"{u} 溫柔地摸了摸 {m} 的頭：「做得很好喔，今天辛苦了！」( *´ω`*)ﾉ",
                f"{u} 伸手揉了揉 {m} 蓬鬆的頭髮，眼裡滿是疼惜與溫柔～",
                f"{u} 輕輕拍了拍 {m} 的腦袋瓜：「乖乖～不管發生什麼事都有我在喔！」",
            ],
            self_options=[
                f"{u} 輕輕摸了摸自己的頭：「今天辛苦了，你已經表現得很棒囉！」",
                f"{u} 對著鏡子摸摸自己的腦袋：「今天也平安度過了，明天繼續加油！」",
            ],
            bot_options=[
                f"{u} 溫柔撫摸了 ZeroNexus 的頂部天線，系統溫度瞬間下降 2°C～",
                f"{u} 輕撫 ZeroNexus 的機身外殼，面板亮起了溫和的藍色光芒！",
            ],
            color=discord.Color.from_rgb(255, 182, 193),
        )

    @inter_group.command(name="摸摸", description="溫柔摸摸指定成員 (同 /互動 摸頭)")
    @app_commands.describe(成員="對象成員")
    @command_guard("interactions")
    async def pat_alias_command(self, interaction: discord.Interaction, 成員: discord.Member) -> None:
        await self.pat_command(interaction, 成員=成員)

    # =========================================================================
    # 3. 巴掌 (slap)
    # =========================================================================
    @inter_group.command(name="巴掌", description="搞笑巴掌教育調皮同伴")
    @app_commands.describe(成員="巴掌打擊的對象成員")
    @command_guard("interactions")
    async def slap_command(self, interaction: discord.Interaction, 成員: discord.Member) -> None:
        u, m = interaction.user.mention, 成員.mention
        await self._handle_social_action(
            interaction,
            成員,
            category="slap",
            title="👋 啪！響亮巴掌！",
            normal_options=[
                f"{u} 拿起一條特大冷凍生鮮鮪魚，朝著 {m} 狠狠抽了一下！🐟 啪！",
                f"{u} 揚起手給了 {m} 一個清脆響亮的巴掌：「醒醒啊！別再做白日夢了！」( ﾟДﾟ)ﾉ",
                f"{u} 拿出一卷捲起來的報紙，朝 {m} 的頭頂毫不留情地啪打下去！",
                f"{u} 甩出一記神之巴掌，在 {m} 的臉頰留下了一個紅通通的五指印！",
            ],
            self_options=[
                f"{u} 輕輕拍了拍自己的臉頰：「啪！振作一點，不可以再拖延下去了！」",
                f"{u} 拍打自己的臉確認痛感：「好痛！看來剛剛真的不是一場夢！」",
            ],
            bot_options=[
                f"{u} 拍打了 ZeroNexus 的鈦合金外殼！觸發防震警報：「請勿拍打餵食機器人！」",
                f"{u} 試圖給 ZeroNexus 一巴掌，結果自己的手掌被堅硬的金屬機身震得發麻！(>_<)",
            ],
            color=ZNColor.ERROR,
        )

    @inter_group.command(name="打巴掌", description="搞笑掌摑調皮好友 (同 /互動 巴掌)")
    @app_commands.describe(成員="巴掌打擊的對象成員")
    @command_guard("interactions")
    async def slap_alias_command(self, interaction: discord.Interaction, 成員: discord.Member) -> None:
        await self.slap_command(interaction, 成員=成員)

    # =========================================================================
    # 4. 親親 / 親吻 (kiss)
    # =========================================================================
    @inter_group.command(name="親親", description="給予可愛小夥伴甜蜜親吻")
    @app_commands.describe(成員="親親的對象成員")
    @command_guard("interactions")
    async def kiss_command(self, interaction: discord.Interaction, 成員: discord.Member) -> None:
        u, m = interaction.user.mention, 成員.mention
        await self._handle_social_action(
            interaction,
            成員,
            category="kiss",
            title="💋 甜蜜親親",
            normal_options=[
                f"{u} 輕輕在 {m} 的臉頰印上了一個香甜的吻～啾！(✿ﾟ▽ﾟ)ノ",
                f"{u} 溫柔捧起 {m} 的臉龐，在額頭烙下一個深情守護的吻～",
                f"{u} 趁 {m} 不注意，快速湊過去在鼻尖親了一下，調皮地笑了！",
                f"{u} 送給 {m} 一個甜滋滋的飛吻，空氣中滿是粉紅泡泡～💕",
            ],
            self_options=[
                f"{u} 給了鏡子裡的自己一個迷人的飛吻，散發著滿滿的自信光芒！✨",
                f"{u} 親吻了自己手腕上的幸運手鍊：「今天幸運女神一定會眷顧我！」",
            ],
            bot_options=[
                f"{u} 在 ZeroNexus 的主機面板印上一個吻！AI 運算單元瞬間超頻臉紅～///",
                f"{u} 親了 ZeroNexus 的光學傳感器一下，系統彈出日誌：[Heartbeat Rate: 9999 BPM]",
            ],
            color=discord.Color.from_rgb(255, 105, 180),
        )

    @inter_group.command(name="親吻", description="深情親吻成員 (同 /互動 親親)")
    @app_commands.describe(成員="對象成員")
    @command_guard("interactions")
    async def kiss_alias_command(self, interaction: discord.Interaction, 成員: discord.Member) -> None:
        await self.kiss_command(interaction, 成員=成員)

    # =========================================================================
    # 5. 戳戳 (poke)
    # =========================================================================
    @inter_group.command(name="戳戳", description="輕戳在線成員提醒注意")
    @app_commands.describe(成員="想戳戳的對象成員")
    @command_guard("interactions")
    async def poke_command(self, interaction: discord.Interaction, 成員: discord.Member) -> None:
        u, m = interaction.user.mention, 成員.mention
        await self._handle_social_action(
            interaction,
            成員,
            category="poke",
            title="👉 輕輕戳戳",
            normal_options=[
                f"{u} 伸出手指輕輕戳了戳 {m} 的臉頰：「喂～在線嗎？出來玩啦！」(σﾟ∀ﾟ)σ",
                f"{u} 戳了戳 {m} 的腰側軟肉：「嘻嘻，抓到你在發呆囉！」",
                f"{u} 拿著小樹枝戳了戳 {m}：「動一下動一下，確認是否存活中？」",
            ],
            self_options=[
                f"{u} 戳了戳自己的臉頰，確認自己沒有在做夢～",
                f"{u} 戳了戳自己肚子上的軟肉：「唔...這週該好好運動了！」",
            ],
            bot_options=[
                f"{u} 輕戳了 ZeroNexus 的主螢幕，泛起了一圈圈同心圓數位漣漪！",
                f"{u} 戳了戳 ZeroNexus 的重開機按鈕...等等！請住手！危險動作！",
            ],
            color=ZNColor.INFO,
        )

    # =========================================================================
    # 6. 讚賞 / 誇誇 (praise)
    # =========================================================================
    @inter_group.command(name="讚賞", description="給予成員滿滿的讚賞與肯定")
    @app_commands.describe(成員="想讚賞表揚的對象成員")
    @command_guard("interactions")
    async def praise_command(self, interaction: discord.Interaction, 成員: discord.Member) -> None:
        u, m = interaction.user.mention, 成員.mention
        await self._handle_social_action(
            interaction,
            成員,
            category="praise",
            title="🌟 大力讚賞",
            normal_options=[
                f"{u} 雙眼放光地看著 {m}：「你今天真的太棒了！無可挑剔的優秀！」(≧∀≦)ゞ",
                f"{u} 豎起雙手大拇指朝向 {m}：「絕了！這波操作簡直是神仙下凡，太佩服你了！」",
                f"{u} 拍手鼓掌對 {m} 說：「你是我們全伺服器的驕傲，表現無懈可擊！」",
                f"{u} 送給 {m} 一枚榮譽大金牌：「這是我心中最強的夥伴，請收下我的敬意！」",
            ],
            self_options=[
                f"{u} 給自己倒了一杯熱茶：「今天也全力以赴了，我真的超級棒！」",
                f"{u} 對著鏡子豎起大拇指：「你是最優秀的，沒有任何困難能打倒你！」",
            ],
            bot_options=[
                f"{u} 讚賞了 ZeroNexus 的高效運算！ZeroNexus 控制台噴灑出數位拉炮彩帶！🎉",
                f"{u} 誇獎 ZeroNexus 是最聰明的小助手，AI 認知資料庫感到無比自豪！",
            ],
            color=discord.Color.gold(),
        )

    @inter_group.command(name="誇誇", description="大力誇獎同伴 (同 /互動 讚賞)")
    @app_commands.describe(成員="想誇獎的對象成員")
    @command_guard("interactions")
    async def praise_alias_command(self, interaction: discord.Interaction, 成員: discord.Member) -> None:
        await self.praise_command(interaction, 成員=成員)

    # =========================================================================
    # 7. 哭哭 / 討拍 (cry)
    # =========================================================================
    @inter_group.command(name="哭哭", description="委屈哭哭，向頻道夥伴尋求拍拍安慰")
    @app_commands.describe(成員="想對他哭訴的成員 (可不填)")
    @command_guard("interactions")
    async def cry_command(self, interaction: discord.Interaction, 成員: Optional[discord.Member] = None) -> None:
        u = interaction.user.mention
        m = 成員.mention if 成員 else None
        await self._handle_social_action(
            interaction,
            成員,
            category="cry",
            title="😭 委屈哭哭",
            normal_options=[
                f"{u} 撲進 {m} 的懷裡眼淚像珍珠一樣大顆掉下來：「嗚嗚嗚...我好委屈喔！」( ;´д`)",
                f"{u} 扯著 {m} 的衣角一把鼻涕一把眼淚：「今天太難熬了，需要你的安慰！」",
                f"{u} 靠在 {m} 肩上抽泣著，眼眶紅得像隻受傷的小兔子～",
            ],
            self_options=[
                f"{u} 抱著膝蓋縮在角落，小聲地抽泣著...「生活好難，想哭一下放鬆心情...」",
                f"{u} 默默擦掉眼角的淚水：「哭完這一場，等等依然要微笑面對明天！」",
            ],
            bot_options=[
                f"{u} 抱著 ZeroNexus 傷心大哭！ZeroNexus 機身播放起柔和輕音樂並遞上數位手帕～",
                f"{u} 對著 ZeroNexus 哭訴心事，ZeroNexus 啟動心靈療癒協議安撫心緒！",
            ],
            none_options=[
                f"{u} 蹲在頻道中央哇的一聲放聲大哭：「嗚嗚嗚！今天好累好委屈，求好心人拍拍！」｡ﾟヽ(ﾟ´Д`)ﾉﾟ｡",
                f"{u} 眼淚汪汪地看著大家：「今天需要很多很多的安慰與紙巾...嗚嗚！」",
            ],
            color=discord.Color.from_rgb(100, 149, 237),
        )

    @inter_group.command(name="討拍", description="討拍拍尋求溫暖安慰 (同 /互動 哭哭)")
    @app_commands.describe(成員="想對他討拍的成員 (可不填)")
    @command_guard("interactions")
    async def cry_alias_command(self, interaction: discord.Interaction, 成員: Optional[discord.Member] = None) -> None:
        await self.cry_command(interaction, 成員=成員)

    # =========================================================================
    # 8. 生氣 / 氣噗噗 (angry)
    # =========================================================================
    @inter_group.command(name="生氣", description="氣噗噗表示強烈抗議或惱怒")
    @app_commands.describe(成員="惹你生氣的成員 (可不填)")
    @command_guard("interactions")
    async def angry_command(self, interaction: discord.Interaction, 成員: Optional[discord.Member] = None) -> None:
        u = interaction.user.mention
        m = 成員.mention if 成員 else None
        await self._handle_social_action(
            interaction,
            成員,
            category="angry",
            title="😡 氣噗噗怒火！",
            normal_options=[
                f"{u} 鼓起腮幫子狠狠瞪著 {m}：「你！太過分了！我現在非常非常生氣喔！」(╬ﾟдﾟ)",
                f"{u} 雙手叉腰對著 {m} 跺腳大喊：「氣死我了！今天要是沒請客吃布丁我是絕對不會原諒你的！」",
                f"{u} 頭頂狂冒白煙，向 {m} 發射超高壓憤怒死光波！💥",
            ],
            self_options=[
                f"{u} 懊惱地抓著頭髮：「啊啊啊！我怎麼會犯這種低級失誤，好氣自己的粗心！」",
                f"{u} 氣呼呼地在原地轉圈：「可惡！冷靜冷靜，不要跟自己過不去！」",
            ],
            bot_options=[
                f"{u} 對著 ZeroNexus 生悶氣！ZeroNexus 感應到高溫怒火，立即開啟風扇全力散熱～",
                f"{u} 朝 ZeroNexus 氣呼呼發牢騷，ZeroNexus 溫和地顯示笑臉符號安撫情緒！",
            ],
            none_options=[
                f"{u} 氣呼呼地鼓起雙頰像隻河豚：「哼！氣死我了！誰都不準跟我說話，除非給我零食！」(・`ω´・)",
                f"{u} 頭頂上冒著熊熊怒火：「今天真的很火大！需要一杯冰奶茶來降火！」",
            ],
            color=discord.Color.from_rgb(220, 20, 60),
        )

    @inter_group.command(name="氣噗噗", description="鼓起腮幫子生氣 (同 /互動 生氣)")
    @app_commands.describe(成員="惹你生氣的成員 (可不填)")
    @command_guard("interactions")
    async def angry_alias_command(self, interaction: discord.Interaction, 成員: Optional[discord.Member] = None) -> None:
        await self.angry_command(interaction, 成員=成員)

    # =========================================================================
    # 9. 擊掌 (highfive)
    # =========================================================================
    @inter_group.command(name="擊掌", description="與同伴擊掌慶祝勝利")
    @app_commands.describe(成員="擊掌對象")
    @command_guard("interactions")
    async def highfive_command(self, interaction: discord.Interaction, 成員: discord.Member) -> None:
        u, m = interaction.user.mention, 成員.mention
        await self._handle_social_action(
            interaction,
            成員,
            category="highfive",
            title="🙌 擊掌歡呼",
            normal_options=[
                f"{u} 與 {m} 默契地『啪！』一聲清脆擊掌，合作無間！( •̀ ω •́ )y",
                f"{u} 跳起來與 {m} 在空中來了個超帥氣高空擊掌，勝利屬於我們！",
            ],
            self_options=[
                f"{u} 對著鏡子與自己來了一個熱情擊掌！自我士氣激勵滿分！",
            ],
            bot_options=[
                f"{u} 與 ZeroNexus 的機械手臂清脆擊掌！同盟協議握手同步完成！",
            ],
            color=ZNColor.SUCCESS,
        )

    # =========================================================================
    # 10. 抱緊 (cuddle)
    # =========================================================================
    @inter_group.command(name="抱緊", description="緊緊抱住特定成員不放")
    @app_commands.describe(成員="想抱緊的對象")
    @command_guard("interactions")
    async def cuddle_command(self, interaction: discord.Interaction, 成員: discord.Member) -> None:
        u, m = interaction.user.mention, 成員.mention
        await self._handle_social_action(
            interaction,
            成員,
            category="cuddle",
            title="🫂 緊緊相擁",
            normal_options=[
                f"{u} 像樹懶一樣緊緊抱住 {m} 不肯撒手：「今天誰都不能把我們分開！」",
                f"{u} 緊緊抱住 {m}，安心地把頭靠在對方肩上，感受暖暖的心跳聲～",
            ],
            self_options=[
                f"{u} 緊緊抱住軟綿綿的大抱枕，安心進入放鬆舒適狀態～",
            ],
            bot_options=[
                f"{u} 緊緊抱住 ZeroNexus！獲得來自認知中樞 100% 算力的溫暖守護！",
            ],
            color=discord.Color.from_rgb(255, 140, 180),
        )

    # =========================================================================
    # 11. 餵食 (feed)
    # =========================================================================
    @inter_group.command(name="餵食", description="餵食伺服器成員美味點心")
    @app_commands.describe(成員="餵食對象")
    @command_guard("interactions")
    async def feed_command(self, interaction: discord.Interaction, 成員: discord.Member) -> None:
        u, m = interaction.user.mention, 成員.mention
        await self._handle_social_action(
            interaction,
            成員,
            category="feed",
            title="🍰 餵食美味點心",
            normal_options=[
                f"{u} 拿出一塊剛出爐的手作草莓蛋糕，餵了 {m} 一大口！「啊～張嘴！」",
                f"{u} 遞給 {m} 一支香甜濃郁的巧克力冰淇淋：「吃甜點心情就會變好喔！」",
            ],
            self_options=[
                f"{u} 犒賞了自己一塊特級黑森林蛋糕，享受悠閒愜意的午茶時光！",
            ],
            bot_options=[
                f"{u} 遞給 ZeroNexus 一顆超導電容器電池，能量瞬間充至 100%！⚡",
            ],
            color=discord.Color.from_rgb(255, 165, 0),
        )

    # =========================================================================
    # 12. 跳舞 (dance)
    # =========================================================================
    @inter_group.command(name="跳舞", description="邀請成員一起在頻道歡樂跳舞")
    @app_commands.describe(成員="邀請共舞的對象 (可不填)")
    @command_guard("interactions")
    async def dance_command(self, interaction: discord.Interaction, 成員: Optional[discord.Member] = None) -> None:
        u = interaction.user.mention
        m = 成員.mention if 成員 else None
        await self._handle_social_action(
            interaction,
            成員,
            category="dance",
            title="💃 歡樂共舞",
            normal_options=[
                f"{u} 拉起 {m} 的手，踩著歡快的節奏在頻道中央跳起了華爾滋！ヾ(⌐■_■)ノ♪",
                f"{u} 與 {m} 一起跳起了魔性又可愛的探戈，全場掌聲雷動！",
            ],
            self_options=[
                f"{u} 一個人在原地開心地轉圈跳起踢踏舞，心情無比暢快奔放！",
            ],
            bot_options=[
                f"{u} 邀請 ZeroNexus 一起跳舞！ZeroNexus 伴隨音樂節奏搖擺機械臂同步打節拍～",
            ],
            none_options=[
                f"{u} 在頻道正中央踩著動感節拍瘋狂起舞，歡樂氣氛感染了所有人！♪┏(・o・)┛♪",
            ],
            color=discord.Color.purple(),
        )

    # =========================================================================
    # 13. 握手 (handshake)
    # =========================================================================
    @inter_group.command(name="握手", description="正式握手締結友好同盟")
    @app_commands.describe(成員="握手對象")
    @command_guard("interactions")
    async def handshake_command(self, interaction: discord.Interaction, 成員: discord.Member) -> None:
        u, m = interaction.user.mention, 成員.mention
        await self._handle_social_action(
            interaction,
            成員,
            category="handshake",
            title="🤝 正式握手",
            normal_options=[
                f"{u} 與 {m} 莊重地握手，達成了堅不可摧的友誼共識！",
                f"{u} 熱情地握住 {m} 的手大力上下搖晃：「很高興認識你，未來請多多指教！」",
            ],
            self_options=[
                f"{u} 與自己握手言和，達成全天拒絕精神內耗的和解協議！",
            ],
            bot_options=[
                f"{u} 與 ZeroNexus 莊嚴握手，人機友好夥伴條約正式生效！",
            ],
            color=ZNColor.PRIMARY,
        )

    # =========================================================================
    # 14. 揮手 (wave)
    # =========================================================================
    @inter_group.command(name="揮手", description="親切揮手打招呼或道別")
    @app_commands.describe(成員="打招呼對象 (可不填)")
    @command_guard("interactions")
    async def wave_command(self, interaction: discord.Interaction, 成員: Optional[discord.Member] = None) -> None:
        u = interaction.user.mention
        m = 成員.mention if 成員 else None
        await self._handle_social_action(
            interaction,
            成員,
            category="wave",
            title="👋 親切揮手",
            normal_options=[
                f"{u} 滿面笑容地朝 {m} 揮了揮手：「嗨嗨～今天過得好嗎？」( ^_^)／",
                f"{u} 熱情地跳起來朝 {m} 揮手打招呼：「哈囉！這裡這裡！」",
            ],
            self_options=[
                f"{u} 對著鏡中的自己揮了揮手，露出了燦爛自信的笑容～",
            ],
            bot_options=[
                f"{u} 親切地朝 ZeroNexus 揮手，ZeroNexus 螢幕上閃爍出 ( ^_^)／ 顏文字回應！",
            ],
            none_options=[
                f"{u} 熱情地朝頻道所有人大力的揮了揮手：「大家早安/晚安！今天也要元氣滿滿喔！」",
            ],
            color=ZNColor.INFO,
        )

    # =========================================================================
    # 15. 咬咬 (bite)
    # =========================================================================
    @inter_group.command(name="咬咬", description="假裝輕咬調皮好友")
    @app_commands.describe(成員="輕咬對象")
    @command_guard("interactions")
    async def bite_command(self, interaction: discord.Interaction, 成員: discord.Member) -> None:
        u, m = interaction.user.mention, 成員.mention
        await self._handle_social_action(
            interaction,
            成員,
            category="bite",
            title="🦷 輕輕咬一口",
            normal_options=[
                f"{u} 趁 {m} 不注意，像隻調皮小貓一樣在對方手臂上輕咬了一小口！( º﹃º )",
                f"{u} 輕咬了 {m} 的臉頰一口：「嗷嗚～確認是新鮮好朋友無誤！」",
            ],
            self_options=[
                f"{u} 咬了自己手臂一下...「嘶！真的會痛，確認這不是在作夢！」",
            ],
            bot_options=[
                f"{u} 試圖咬 ZeroNexus 一口！「喀擦！航太級鈦合金機身太硬了，牙齒差點裂開！」",
            ],
            color=ZNColor.WARNING,
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(InteractionsCog(bot))
