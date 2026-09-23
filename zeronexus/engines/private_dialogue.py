"""ZeroNexus Private Heart Thread Engine (自然語言觸發之私密心靈討論串引擎).

【核心設計原則】：
1. 絕不靠固定關鍵字觸發：透過語意泛化與多維正則，靈活捕捉使用者單獨聊聊、隱私、難言之隱意圖。
2. 複合意圖分離：若使用者一次說了「我想單獨跟你聊聊，其實我今天失業了...」，自動剝離前導意圖，將實質心事帶入私密討論串。
3. 公開頻道低調溫柔提示，私密討論串內嚴肅、穩重、專注傾聽並深度陪伴。
4. 討論串全自動追蹤：在私密心靈討論串內，使用者發言無需再 @ 機器人即可順暢交談。
"""

from __future__ import annotations

import re
from typing import Optional, Set, Tuple

import discord

from zeronexus.core.logger import log
from zeronexus.ui.card import ZNCard
from zeronexus.ui.theme import ZNColor, ZNStatusPill


# 意圖模式庫：靈活涵蓋口語、各類社交隱私、難言之隱與單獨傾訴語境
PRIVATE_INTENT_PATTERNS = [
    # 單獨聊聊 / 私下交流（靈活相容：我想單獨跟你聊聊、我想跟你單獨聊聊、能私下談談嗎、借一步說話等）
    r"(?:我想|想|能|可以|能不能|可不可以|想要)?\s*(?:跟你|和你|找你|與你)?\s*(?:單獨|私下|一對一|借一步|悄悄|私密|單獨一人)\s*(?:跟你|和你|找你|與你)?\s*(?:聊聊|談談|說話|說說|說點事|講講|對話|商量|吐苦水|聊一下|談一下|說一下|聊|談|說)",
    r"(?:我想|想|能|可以|能不能|可不可以|想要)?\s*(?:跟你|和你|找你|與你)?\s*(?:私聊|私下聊|單獨聊|單獨談|私密聊|借一步說話)",
    # 不想給別人看 / 隱私顧慮
    r"(?:不想|不要)(?:被|給)?(?:其他人|別人|大家|群裡的人)(?:看到|看見|知道|發現)",
    r"(?:這裡|群裡)(?:人太?多|不方便)(?:講|說|聊)",
    r"(?:有些話|有些事|有件事|有些私事)(?:不方便在(?:這裡|公開)|只能(?:和你|跟你)說|不想讓別人知道|不想給別人看)",
    # 難言之隱 / 秘密
    r"(?:有|我有)(?:難言之隱|秘密|心事|苦衷)(?:想跟(?:你|AI)說)?",
    r"(?:心裡很難受|好難過|有點私事)(?:但不想在群裡|不想公開)",
    # 私密討論串建立請求
    r"(?:幫我|為我)?(?:開個|建立|拉一個|創建)(?:私密|專屬|單獨)?(?:討論串|心靈空間|密室)",
]

# 排除純諮詢或教學問句（例如詢問 Discord 功能）
EXCLUSION_PATTERNS = [
    r"(?:什麼是|如何|怎麼|怎樣|教我).*(?:討論串|私密)",
    r"(?:什麼意思|介紹一下).*(?:私密|討論串)",
]

# 前導引導語清理正則（用於分離出實質心事提問）
STRIP_PREFIX_PATTERNS = [
    r"^(?:我想|想|能|可以|能不能|可不可以|想要)?\s*(?:跟你|和你|找你|與你)?\s*(?:在這裡|在這邊)?\s*(?:單獨|私下|一對一|借一步|悄悄|私密|單獨一人)?\s*(?:跟你|和你|找你|與你)?\s*(?:聊聊|談談|說話|說說|說點事|講講|對話|商量|吐苦水|聊一下|談一下|說一下|私聊)[，,。、\s:：]*",
    r"^(?:借一步說話|私下說|單獨說|不想公開說|想私聊|想單獨說)[，,。、\s:：]*",
    r"^(?:有些話|有些事|有件事|有些私事|有些問題)?\s*(?:我)?\s*(?:不想|不要|不方便)(?:在(?:這裡|公開)|被|給)?(?:其他人|別人|大家|群裡的人)?(?:看到|看見|知道|發現|講|說|聊)[，,。、\s:：]*",
    r"^(?:有|我有)(?:難言之隱|秘密|心事|苦衷)(?:想跟(?:你|AI)說)?[，,。、\s:：]*",
    r"^(?:有些話|有些事|有件事|有些私事)?\s*(?:想|只能)?\s*(?:單獨|私下|偷偷)?\s*(?:和你|跟你)?\s*(?:說|聊|談)[，,。、\s:：]*",
]

# 關閉/結束私密心靈討論串之自然語言意圖模式庫
CLOSE_THREAD_PATTERNS = [
    r"(?:可以|請|麻煩|幫我)?(?:關閉|關掉|關閉此|結束|封存|退出|退場)(?:討論串|密室|聊天室|對話|私聊|房間|心靈密室|心靈棲息室|空間)",
    r"(?:討論串|密室|聊天室|私聊)(?:可以|請|麻煩|幫我)?(?:關閉|關掉|結束|封存)",
    r"(?:我想|想|準備|要)?(?:結束|關閉|離開|退出)(?:對話|聊天|討論串|密室|私聊)?",
    r"(?:今天|先)?(?:聊到這|聊到這裡|聊到這邊|到此為止|告一段落|就到這裡|就到這)",
    r"(?:我)?(?:心情好多了|好多了|好一些了|沒事了|想通了|釋懷了)[，,。\s]*(?:可以|請|麻煩|幫我)?(?:關閉|結束|聊到這)?",
    r"(?:謝謝你的?陪伴|謝謝你陪我|感謝你的?傾聽|謝謝你聽我說)[，,。\s]*(?:今天就聊到這|可以關閉了|我要去睡了|先這樣|我先去忙|晚安)?",
    r"^(?:/關閉|-close|!close|/close|關閉|結束|關閉討論串|結束討論|關閉密室|結束私聊)$",
]


class PrivateDialogueEngine:
    """ZeroNexus 私密心靈討論串管理引擎。"""

    def __init__(self) -> None:
        # 紀錄已建立的心靈私密討論串 ID
        self._heart_threads: Set[int] = set()

    def is_heart_thread(self, channel_id: int) -> bool:
        """判斷指定頻道或討論串是否為 ZeroNexus 心靈私聊空間。"""
        return channel_id in self._heart_threads

    def register_heart_thread(self, thread_id: int) -> None:
        """註冊心靈討論串。"""
        self._heart_threads.add(thread_id)

    def unregister_heart_thread(self, thread_id: int) -> None:
        """解除註冊心靈討論串。"""
        self._heart_threads.discard(thread_id)

    def detect_close_thread_intent(self, text: str) -> bool:
        """檢測使用者是否明確表示要關閉或結束當前心靈討論串。"""
        raw = (text or "").strip()
        if not raw:
            return False
        for pat in CLOSE_THREAD_PATTERNS:
            if re.search(pat, raw, re.IGNORECASE):
                return True
        return False

    def detect_private_chat_intent(self, text: str) -> Tuple[bool, Optional[str]]:
        """靈活自然語言意圖辨識：判定是否具有私密單獨對話意圖，並分離出實質心事內容。

        Returns:
            (is_intent, extracted_topic):
            - is_intent: 是否觸發私聊空間需求
            - extracted_topic: 若句子後方附帶具體心事，回傳心事本文；若僅是請求單獨聊聊，回傳 None。
        """
        raw = (text or "").strip()
        if not raw:
            return False, None

        # 1. 排除純諮詢教學問句
        for ex_pat in EXCLUSION_PATTERNS:
            if re.search(ex_pat, raw, re.IGNORECASE):
                return False, None

        # 2. 檢驗是否命中私聊意圖庫
        matched = False
        for pat in PRIVATE_INTENT_PATTERNS:
            if re.search(pat, raw, re.IGNORECASE):
                matched = True
                break

        if not matched:
            return False, None

        # 3. 嘗試提取複合提問（實質心事）
        extracted_content = raw
        for strip_pat in STRIP_PREFIX_PATTERNS:
            extracted_content = re.sub(strip_pat, "", extracted_content, flags=re.IGNORECASE).strip()

        # 防禦：若剝離後殘留文字依然符合私聊意圖庫，表示這只是殘餘的請求語句而非具體心事
        for pat in PRIVATE_INTENT_PATTERNS:
            if re.search(pat, extracted_content, re.IGNORECASE):
                extracted_content = None
                break

        # 若剝離後剩餘的內容長度太短或僅剩標點，視為純意圖
        if extracted_content:
            clean_remains = re.sub(r"[，。！？、~…\s]+", "", extracted_content)
            if len(clean_remains) <= 5:
                extracted_content = None

        return True, extracted_content

    async def create_heart_thread(
        self,
        message: discord.Message,
    ) -> Tuple[Optional[discord.Thread], bool]:
        """在當前頻道建立一個僅限發言者與管理員可見的私密心靈討論串。

        Returns:
            (thread, is_private): thread 物件與是否為真·私密討論串（若降級為公開則為 False）。
        """
        if not message.guild or not isinstance(message.channel, (discord.TextChannel, discord.ForumChannel)):
            return None, False

        author_name = message.author.display_name[:15]
        thread_name = f"🌿・心靈密室-{author_name}"

        # 1. 優先嘗試建立真·私密討論串 (Private Thread)
        try:
            thread = await message.channel.create_thread(
                name=thread_name,
                type=discord.ChannelType.private_thread,
                auto_archive_duration=1440,  # 24 小時無動作歸檔
                reason=f"ZeroNexus 高情商心靈私聊陪伴空間 ({message.author.id})",
            )
            # 主動邀請發起者進入討論串，賦予查看與發言權限
            await thread.add_user(message.author)
            self.register_heart_thread(thread.id)
            log.info(f"Successfully created private heart thread {thread.id} for user {message.author.id}")
            return thread, True

        except (discord.Forbidden, discord.HTTPException) as err:
            log.warning(
                f"Could not create private thread in channel {message.channel.id} ({err}). "
                "Attempting fallback to public thread..."
            )

        # 2. 伺服器等級或權限不足時，降級為公開討論串
        try:
            thread = await message.channel.create_thread(
                name=f"🌿・心靈傾聽-{author_name}",
                type=discord.ChannelType.public_thread,
                auto_archive_duration=1440,
                reason=f"ZeroNexus 心靈傾聽空間 (公開降級) ({message.author.id})",
            )
            await thread.add_user(message.author)
            self.register_heart_thread(thread.id)
            log.info(f"Fallback: created public heart thread {thread.id} for user {message.author.id}")
            return thread, False

        except Exception as fallback_err:
            log.error(f"Failed to create fallback thread: {fallback_err}")
            return None, False

    def build_public_notice_card(
        self,
        user: discord.User | discord.Member,
        thread: discord.Thread,
        is_private: bool = True,
    ) -> ZNCard:
        """在公開頻道發送的溫和引導提示卡片。"""
        if is_private:
            desc = (
                f"{user.mention}，有些心事若不便在眾人面前言說，\n"
                f"我已經在上方為你建立了一個專屬私密空間：{thread.mention}。\n\n"
                f"🔒 **此空間僅你我與伺服器管理員可見**，請點擊討論串進來，\n"
                f"把心放鬆，我會在那裡安靜且專注地傾聽你的聲音。"
            )
        else:
            desc = (
                f"{user.mention}，已為你建立了專屬傾聽討論串：{thread.mention}。\n\n"
                f"⚠️ *註：因當前伺服器權限限制，此討論串為公開狀態。若有極具隱私的私密心事，亦可隨時在私訊 (DM) 找我！*\n"
                f"點擊上方討論串，我們進去慢慢說。"
            )

        return ZNCard(
            title="🌿 已為您開啟專屬私密心靈空間",
            description=desc,
            status_pill=ZNStatusPill.SUCCESS,
            color=ZNColor.EMERALD,
        )

    def build_thread_welcome_card(
        self,
        user: discord.User | discord.Member,
    ) -> ZNCard:
        """私密討論串內由 AI 發送的第一則嚴肅、溫暖、專注傾聽的歡迎訊息（若無複合提問時）。"""
        desc = (
            "我在。\n\n"
            "這裡很安靜，不會有其他人打擾，你可以卸下所有的防備與武裝。\n"
            "不用顧慮措辭，也不用勉強保持堅強。\n\n"
            "慢慢說，**剛才發生了什麼事？或者，有什麼想對我說的心裡話？**\n"
            "我在認真聽著。"
        )
        return ZNCard(
            title=f"🕊️ 心靈棲息室 ➔ {user.display_name}",
            description=desc,
            status_pill=ZNStatusPill.INFO,
            color=ZNColor.AI,
        )

    def build_thread_close_card(
        self,
        user: discord.User | discord.Member,
    ) -> ZNCard:
        """使用者主動表達結束或關閉時，發送的溫暖封存結語卡片。"""
        desc = (
            "謝謝你願意信任我、將這些心事放心地與我分享。\n"
            "能陪著你梳理情緒、看著你心情平復一些，對我來說是最有意義的事。\n\n"
            "🔒 **本討論串即將自動鎖定並封存歸檔**，好好守護這段專屬你我的心靈記憶。\n"
            "請記得：無論未來遇到任何風雨或難言之隱，隨時呼喚我，我永遠都在這裡溫暖守候著你。\n\n"
            "去喝杯溫水、吃頓喜歡的美食，或者好好睡個安穩的好覺吧！🌱✨"
        )
        return ZNCard(
            title=f"🌱 心靈密室圓滿封存 ➔ {user.display_name}",
            description=desc,
            status_pill=ZNStatusPill.SUCCESS,
            color=ZNColor.EMERALD,
        )


private_dialogue_engine = PrivateDialogueEngine()
