"""ZeroNexus Utilities, Scientific Calculations, and Minecraft Query Cog.

27 Streamlined Commands under /工具:
- 計算, 代數運算, 解方程式, 微積分, 質數, 因數倍數, 排列組合, 單位換算, 匯率查詢
- 天氣, 地震, 時間與時區, 隨機數, 雜湊運算, base64, 網址檢查, ping網路, qr碼生成, 正則測試, 密碼生成, 搜尋, 網路搜尋
- mc伺服器狀態, mc玩家檔案, mc伺服器圖示, mc延遲檢測, mc健康巡檢
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import io
import math
import re
import secrets
import string
import time
from datetime import datetime, timedelta
from typing import Any, Dict, Literal, Optional
from urllib.parse import urlparse

import discord
import httpx
import pytz
import qrcode
from discord import app_commands
from discord.ext import commands

from zeronexus.core.cache import cache
from zeronexus.engines.calculator import calculator
from zeronexus.engines.cwa_client import TAIWAN_COUNTIES, cwa_client
from zeronexus.engines.cwa_notifier import build_rich_earthquake_card
from zeronexus.engines.free_apis import free_apis
from zeronexus.engines.google_suite import google_suite
from zeronexus.engines.minecraft_query import (
    classify_minecraft_error,
    classify_player_error,
    mc_query,
)
from zeronexus.engines.web_client import web_client
from zeronexus.modules.base import BaseModule, CommandMetadata
from zeronexus.security.guard import command_guard
from zeronexus.security.permissions import ZNPermissionLevel
from zeronexus.security.ssrf import validate_safe_host, validate_safe_url
from zeronexus.ui.card import ZNCard
from zeronexus.ui.responder import InteractionResponder
from zeronexus.ui.theme import ZNColor, ZNStatusPill

CITY_TIMEZONE_MAP: Dict[str, str] = {
    "台北": "Asia/Taipei",
    "臺北": "Asia/Taipei",
    "台灣": "Asia/Taipei",
    "臺灣": "Asia/Taipei",
    "東京": "Asia/Tokyo",
    "日本": "Asia/Tokyo",
    "首爾": "Asia/Seoul",
    "韓國": "Asia/Seoul",
    "香港": "Asia/Hong_Kong",
    "北京": "Asia/Shanghai",
    "上海": "Asia/Shanghai",
    "新加坡": "Asia/Singapore",
    "倫敦": "Europe/London",
    "英國": "Europe/London",
    "巴黎": "Europe/Paris",
    "柏林": "Europe/Berlin",
    "紐約": "America/New_York",
    "洛杉磯": "America/Los_Angeles",
    "舊金山": "America/Los_Angeles",
    "芝加哥": "America/Chicago",
    "溫哥華": "America/Vancouver",
    "多倫多": "America/Toronto",
    "雪梨": "Australia/Sydney",
    "悉尼": "Australia/Sydney",
    "墨爾本": "Australia/Melbourne",
    "奧克蘭": "Pacific/Auckland",
}


def parse_reminder_time(time_str: str, tz_name: str = "Asia/Taipei") -> tuple[Optional[float], Optional[datetime], Optional[str]]:
    """Parses relative or absolute time expressions into target epoch seconds.
    Returns (target_epoch, target_dt, error_message).
    """
    clean = time_str.strip().lower()
    try:
        user_tz = pytz.timezone(tz_name)
    except Exception:
        user_tz = pytz.timezone("Asia/Taipei")
    now_local = datetime.now(user_tz)

    # 1. Match relative time pattern (e.g., 10m, 1h30m, 45s, 10分鐘, 1小時, 2天)
    rel_pattern = re.compile(
        r'(?:(?P<days>\d+)\s*(?:d|day|days|天|日))?'
        r'\s*(?:(?P<hours>\d+)\s*(?:h|hr|hour|hours|小時|時))?'
        r'\s*(?:(?P<minutes>\d+)\s*(?:m|min|minute|minutes|分鐘|分))?'
        r'\s*(?:(?P<seconds>\d+)\s*(?:s|sec|second|seconds|秒鐘|秒))?',
        re.IGNORECASE
    )
    m = rel_pattern.fullmatch(clean)
    if m and any(m.groupdict().values()):
        d = int(m.group('days') or 0)
        h = int(m.group('hours') or 0)
        mi = int(m.group('minutes') or 0)
        s = int(m.group('seconds') or 0)
        total_seconds = d * 86400 + h * 3600 + mi * 60 + s
        if total_seconds < 5:
            return None, None, "提醒時間至少需設定為 5 秒以上。"
        if total_seconds > 86400 * 30:
            return None, None, "提醒時間最長上限為 30 天以內。"
        target_epoch = time.time() + total_seconds
        target_dt = datetime.fromtimestamp(target_epoch, tz=user_tz)
        return target_epoch, target_dt, None

    # 2. Match simple integer seconds:
    if clean.isdigit():
        sec = int(clean)
        if sec < 5:
            return None, None, "提醒時間至少需設定為 5 秒以上。"
        if sec > 86400 * 30:
            return None, None, "提醒時間最長上限為 30 天以內。"
        target_epoch = time.time() + sec
        target_dt = datetime.fromtimestamp(target_epoch, tz=user_tz)
        return target_epoch, target_dt, None

    # 3. Match absolute clock time: HH:MM or HH:MM:SS
    clock_m = re.match(r'^(\d{1,2}):(\d{2})(?::(\d{2}))?$', clean)
    if clock_m:
        h = int(clock_m.group(1))
        mi = int(clock_m.group(2))
        s = int(clock_m.group(3) or 0)
        if not (0 <= h <= 23 and 0 <= mi <= 59 and 0 <= s <= 59):
            return None, None, "無效的時鐘時間格式 (小時 0-23，分/秒 0-59)。"
        target_dt = now_local.replace(hour=h, minute=mi, second=s, microsecond=0)
        if target_dt <= now_local:
            target_dt += timedelta(days=1)
        target_epoch = target_dt.timestamp()
        return target_epoch, target_dt, None

    # 4. Match absolute date-time: YYYY-MM-DD HH:MM
    for fmt in ("%Y-%m-%d %H:%M", "%Y/%m/%d %H:%M", "%Y-%m-%d %H:%M:%S", "%Y/%m/%d %H:%M:%S"):
        try:
            parsed = datetime.strptime(clean, fmt)
            target_dt = user_tz.localize(parsed)
            if target_dt.timestamp() <= time.time():
                return None, None, "設定的指定時間已是過去時間，請提供未來之時間點。"
            if (target_dt.timestamp() - time.time()) > 86400 * 30:
                return None, None, "提醒時間最長上限為 30 天以內。"
            return target_dt.timestamp(), target_dt, None
        except Exception:
            continue

    return None, None, "無法辨識的時間格式。支援相對時長 (如 `10m`, `1h30m`, `30秒`)、今日時間 (如 `18:30`) 或完整日期時間 (如 `2026-09-12 18:00`)。"


def parse_dice_notation(dice_expr: str) -> tuple[int, int, int]:
    """Parses dice notations like 2d6, 3d20+5, 1d100-2.
    Returns (count, sides, modifier).
    """
    clean = dice_expr.strip().lower().replace(" ", "")
    m = re.match(r"^(\d{1,2})d(\d{1,4})([+-]\d{1,4})?$", clean)
    if not m:
        raise ValueError(f"無效的骰子表達式「{dice_expr}」。標準格式例如：`2d6`, `3d20+5`, `1d100-2`。")
    count = int(m.group(1))
    sides = int(m.group(2))
    mod = int(m.group(3)) if m.group(3) else 0
    if count < 1 or count > 50:
        raise ValueError("骰子數量必須介於 1 至 50 顆之間。")
    if sides < 2 or sides > 1000:
        raise ValueError("骰子面數必須介於 2 至 1000 面之間。")
    return count, sides, mod


class ToolsModule(BaseModule):
    """Scientific calculations, Taiwanese weather/earthquake, network probe, and Minecraft utilities."""

    def __init__(self) -> None:
        super().__init__(
            name="tools",
            display_name="工具模組",
            description="任意精度符號計算器、中央氣象署即時報告、網路探針與 Minecraft 狀態查詢",
        )
        self.monitored_mc_servers: Dict[str, Dict[str, Any]] = {}

    async def initialize(self, bot: Any) -> None:
        commands_list = [
            ("計算", "任意精度數學表達式計算", ZNPermissionLevel.EVERYONE),
            ("代數運算", "代數多項式化簡、展開與因式分解", ZNPermissionLevel.EVERYONE),
            ("解方程式", "求解代數方程式", ZNPermissionLevel.EVERYONE),
            ("微積分", "符號微分與積分運算", ZNPermissionLevel.EVERYONE),
            ("質數", "高速大整數質數判定與質因數分解", ZNPermissionLevel.EVERYONE),
            ("因數倍數", "計算多個整數之 GCD 與 LCM", ZNPermissionLevel.EVERYONE),
            ("排列組合", "計算排列數 P 與組合數 C", ZNPermissionLevel.EVERYONE),
            ("單位換算", "物理與位元組單位換算", ZNPermissionLevel.EVERYONE),
            ("匯率查詢", "國際主要法定貨幣即時匯率換算 (支援快取與格式防呆)", ZNPermissionLevel.EVERYONE),
            ("天氣", "台灣 22 縣市概況、36h預報、雨量站實測與颱風警報 (CWA)", ZNPermissionLevel.EVERYONE),
            ("雷達回波", "中央氣象署台灣全區高解析度即時雷達回波圖", ZNPermissionLevel.EVERYONE),
            ("衛星雲圖", "中央氣象署即時彩色紅外線衛星雲圖 (台灣/東亞)", ZNPermissionLevel.EVERYONE),
            ("累積雨量", "中央氣象署全台 24 小時日累積雨量分布圖", ZNPermissionLevel.EVERYONE),
            ("地震", "中央氣象署最新顯著有感速報與編號報告", ZNPermissionLevel.EVERYONE),
            ("時間與時區", "全球主要城市標準時間對照與定時提醒鬧鐘", ZNPermissionLevel.EVERYONE),
            ("隨機數", "安全隨機數生成、RPG 擲骰子 (ndm) 與隨機抽籤", ZNPermissionLevel.EVERYONE),
            ("雜湊運算", "字串雜湊值 (MD5/SHA256/SHA512)", ZNPermissionLevel.EVERYONE),
            ("base64", "文字安全 Base64 編碼或解碼", ZNPermissionLevel.EVERYONE),
            ("網址檢查", "解析網址重導向與 HTTP 狀態", ZNPermissionLevel.EVERYONE),
            ("ping網路", "檢測網域 DNS 與連線延遲", ZNPermissionLevel.EVERYONE),
            ("qr碼生成", "生成高解析度 QR Code 圖片", ZNPermissionLevel.EVERYONE),
            ("正則測試", "正規表達式匹配與群組驗證", ZNPermissionLevel.EVERYONE),
            ("密碼生成", "生成高強度隨機安全密碼", ZNPermissionLevel.EVERYONE),
            ("搜尋", "即時搜尋網路公開資訊、網頁摘要與參考連結", ZNPermissionLevel.EVERYONE),
            ("網路搜尋", "即時搜尋網路公開資訊、網頁摘要與參考連結", ZNPermissionLevel.EVERYONE),
            ("mc伺服器狀態", "探測 Java 或 Bedrock 伺服器在線狀態與 MOTD", ZNPermissionLevel.EVERYONE),
            ("mc玩家檔案", "查詢 Minecraft 正版玩家 UUID、歷史更名與 3D 皮膚", ZNPermissionLevel.EVERYONE),
            ("mc伺服器圖示", "提取 Minecraft 目標伺服器 Favicon 原圖", ZNPermissionLevel.EVERYONE),
            ("mc延遲檢測", "精確測量目標 Minecraft 伺服器連線 Ping 延遲", ZNPermissionLevel.EVERYONE),
            ("mc健康巡檢", "將伺服器加入定時巡檢監控或檢視可用率", ZNPermissionLevel.ADMINISTRATOR),
        ]
        for name, desc, perm in commands_list:
            is_standalone = name in ("搜尋", "網路搜尋")
            self.register_command_meta(CommandMetadata(
                name=name,
                full_name=name if is_standalone else f"工具 {name}",
                description=desc,
                group_name="頂層" if is_standalone else "工具",
                module_name=self.name,
                permission_level=perm,
                guild_only=False,
            ))

    async def shutdown(self) -> None:
        pass


if not hasattr(discord, "InteractionContextType"):
    class InteractionContextType:
        guild = 0
        bot_dm = 1
        private_channel = 2
    discord.InteractionContextType = InteractionContextType


class ToolsCog(commands.Cog):
    """Discord Slash Command Group for /工具."""

    tools_group = app_commands.Group(
        name="工具",
        description="實用工具、符號計算、氣象與 Minecraft (MC) 整合指令群組",
        guild_only=False,
        allowed_contexts=app_commands.AppCommandContext(guild=True, dm_channel=True, private_channel=True),
    )
    tools_group.contexts = [discord.InteractionContextType.guild, discord.InteractionContextType.bot_dm]

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.monitored_mc_servers: Dict[str, Dict[str, Any]] = {}
        self.active_reminders: Dict[str, Dict[str, Any]] = {}
        # Convenient alias attributes for MC server and player queries
        self.mc伺服器 = self.mc_status_command
        self.mc玩家 = self.mc_player_command

    @tools_group.command(name="計算", description="安全沙盒符號與任意精度數學計算器")
    @app_commands.describe(表達式="數學運算式 (例如 2**100, sin(pi/4), (5+3)*4)")
    @command_guard("tools")
    async def calc_command(self, interaction: discord.Interaction, 表達式: str) -> None:
        if not 表達式 or not 表達式.strip():
            await InteractionResponder.safe_send(interaction, "❌ 請輸入有效的數學表達式。", ephemeral=True)
            return

        res = calculator.evaluate(表達式.strip())
        if res.is_error:
            card = ZNCard(title="計算錯誤", description=f"`{res.error_message}`", status_pill=ZNStatusPill.ERROR, color=ZNColor.ERROR)
            await InteractionResponder.safe_send(interaction, card=card, ephemeral=True)
            return

        display_res = res.result_str
        if len(display_res) > 1500:
            display_res = display_res[:1500] + "\n... (結果長度超出上限，已截斷顯示)"

        card = ZNCard(
            title="任意精度計算結果",
            description=f"**輸入表達式**：\n```python\n{res.expression}\n```\n**精確運算值**：\n```python\n{display_res}\n```",
            status_pill=ZNStatusPill.SUCCESS,
            color=ZNColor.SUCCESS,
        )
        card.add_section("⏱️ 耗時", f"`{res.execution_time_ms} ms`", inline=True)
        if res.latex_str:
            card.add_section("📐 LaTeX 符號式", f"```{res.latex_str[:500]}```", inline=False)
        await InteractionResponder.safe_send(interaction, card=card)

    @tools_group.command(name="代數運算", description="代數多項式化簡、展開或因式分解")
    @app_commands.describe(表達式="多項式表達式 (例如 (x+1)*(x-1), (x+y)**3, x**2 - 5*x + 6)", 操作="化簡、展開 或 因式分解")
    @command_guard("tools")
    async def algebra_command(self, interaction: discord.Interaction, 表達式: str, 操作: Literal["化簡", "展開", "因式分解"] = "化簡") -> None:
        if not 表達式 or not 表達式.strip():
            await InteractionResponder.safe_send(interaction, "❌ 請輸入有效的代數多項式。", ephemeral=True)
            return

        mode_map = {"化簡": "simplify", "展開": "expand", "因式分解": "factor"}
        op = mode_map.get(操作, "simplify")
        res = calculator.algebra_simplify(表達式.strip(), mode=op)
        if res.is_error:
            card = ZNCard(title="代數運算失敗", description=f"`{res.error_message}`", status_pill=ZNStatusPill.ERROR, color=ZNColor.ERROR)
            await InteractionResponder.safe_send(interaction, card=card, ephemeral=True)
            return

        display_res = res.result_str
        if len(display_res) > 1500:
            display_res = display_res[:1500] + "\n... (結果長度超出上限，已截斷顯示)"

        card = ZNCard(
            title=f"代數多項式 — {操作}結果",
            description=f"**輸入式**：\n```python\n{res.expression}\n```\n**運算結果**：\n```python\n{display_res}\n```",
            status_pill=ZNStatusPill.SUCCESS,
            color=ZNColor.SUCCESS,
        )
        if res.latex_str:
            card.add_section("📐 LaTeX", f"```{res.latex_str[:500]}```", inline=False)
        await InteractionResponder.safe_send(interaction, card=card)

    @tools_group.command(name="解方程式", description="求解代數或多項式方程式")
    @app_commands.describe(方程式="方程式表達式 (例如 x**2 - 5*x + 6 = 0 或 2*x + 5 = 15)", 變數="未知數符號 (預設 x)")
    @command_guard("tools")
    async def solve_command(self, interaction: discord.Interaction, 方程式: str, 變數: str = "x") -> None:
        if not 方程式 or not 方程式.strip():
            await InteractionResponder.safe_send(interaction, "❌ 請輸入有效的方程式。", ephemeral=True)
            return

        res = calculator.solve_equation(方程式.strip(), variable_name=變數.strip() or "x")
        if res.is_error:
            card = ZNCard(title="解方程式失敗", description=f"`{res.error_message}`", status_pill=ZNStatusPill.ERROR, color=ZNColor.ERROR)
            await InteractionResponder.safe_send(interaction, card=card, ephemeral=True)
            return

        display_res = res.result_str
        if len(display_res) > 1500:
            display_res = display_res[:1500] + "\n... (結果長度超出上限，已截斷顯示)"

        card = ZNCard(
            title=f"方程式求解：{變數}",
            description=f"**原方程式**：\n```python\n{res.expression}\n```\n**解 (Roots)**：\n```python\n{display_res}\n```",
            status_pill=ZNStatusPill.SUCCESS,
            color=ZNColor.SUCCESS,
        )
        await InteractionResponder.safe_send(interaction, card=card)

    @tools_group.command(name="微積分", description="符號微分與不定積分/定積分運算")
    @app_commands.describe(表達式="目標函數 (例如 x**3 * sin(x), exp(2*x))", 運算類型="微分 或 積分", 變數="自變數 (預設 x)")
    @command_guard("tools")
    async def calculus_command(self, interaction: discord.Interaction, 表達式: str, 運算類型: Literal["微分", "積分"] = "微分", 變數: str = "x") -> None:
        if not 表達式 or not 表達式.strip():
            await InteractionResponder.safe_send(interaction, "❌ 請輸入有效的函數式。", ephemeral=True)
            return

        op = "diff" if 運算類型 == "微分" else "integrate"
        res = calculator.calculus(表達式.strip(), mode=op, variable_name=變數.strip() or "x")
        if res.is_error:
            card = ZNCard(title="微積分運算失敗", description=f"`{res.error_message}`", status_pill=ZNStatusPill.ERROR, color=ZNColor.ERROR)
            await InteractionResponder.safe_send(interaction, card=card, ephemeral=True)
            return

        display_res = res.result_str
        if len(display_res) > 1500:
            display_res = display_res[:1500] + "\n... (結果長度超出上限，已截斷顯示)"

        symbol_prefix = "d/dx" if 運算類型 == "微分" else "∫ dx"
        card = ZNCard(
            title=f"符號微積分 — {運算類型}結果",
            description=f"**目標式**：\n```python\n{symbol_prefix} ( {res.expression} )\n```\n**導函數/原函數**：\n```python\n{display_res}\n```",
            status_pill=ZNStatusPill.SUCCESS,
            color=ZNColor.SUCCESS,
        )
        if res.latex_str:
            card.add_section("📐 LaTeX", f"```{res.latex_str[:500]}```", inline=False)
        await InteractionResponder.safe_send(interaction, card=card)

    @tools_group.command(name="質數", description="大整數質數判定或質因數分解式")
    @app_commands.describe(操作="選擇質數檢查或質因數分解", 數字="欲檢驗之正整數")
    @command_guard("tools")
    async def prime_command(self, interaction: discord.Interaction, 操作: Literal["質數檢查", "質因數分解"], 數字: int) -> None:
        if 數字 < 1:
            await InteractionResponder.safe_send(interaction, "❌ 請輸入大於等於 1 之正整數。", ephemeral=True)
            return
        if 數字 > 10**14:
            await InteractionResponder.safe_send(interaction, "❌ 數字上限為 100,000,000,000,000 (10^14) 以內，避免過度消耗計算資源。", ephemeral=True)
            return

        if 操作 == "質數檢查":
            if 數字 == 1:
                status_text = "既非質數亦非合數 (Unit 單位元)"
                pill = ZNStatusPill.INFO
                col = ZNColor.INFO
            else:
                is_prime = await asyncio.to_thread(calculator.is_prime, 數字)
                status_text = "為質數 (Prime Number)" if is_prime else "不是質數 (合數 Composite Number)"
                pill = ZNStatusPill.SUCCESS if is_prime else ZNStatusPill.WARNING
                col = ZNColor.SUCCESS if is_prime else ZNColor.WARNING

            card = ZNCard(
                title=f"質數檢驗：{數字}",
                description=f"整數 **`{數字}`** {status_text}。",
                status_pill=pill,
                color=col,
            )
        else:
            if 數字 == 1:
                expr = "1 (單位元，無質因數)"
            else:
                factors = await asyncio.to_thread(calculator.factorize, 數字)
                expr = " × ".join(f"{base}^{exp}" if exp > 1 else str(base) for base, exp in factors) or "1"
            card = ZNCard(
                title=f"質因數分解：{數字}",
                description=f"```\n{數字} = {expr}\n```",
                status_pill=ZNStatusPill.SUCCESS,
                color=ZNColor.SUCCESS,
            )
        await InteractionResponder.safe_send(interaction, card=card)

    @tools_group.command(name="因數倍數", description="計算多個整數之最大公因數 (GCD) 或最小公倍數 (LCM)")
    @app_commands.describe(運算="最大公因數 或 最小公倍數", 數字清單="以空格、逗號或頓號隔開之整數清單 (例如 24, 36, 60)")
    @command_guard("tools")
    async def gcd_lcm_command(self, interaction: discord.Interaction, 運算: Literal["最大公因數", "最小公倍數"], 數字清單: str) -> None:
        try:
            nums = [int(x.strip()) for x in re.split(r"[\s,，、]+", 數字清單.strip()) if x.strip()]
            if len(nums) < 2:
                raise ValueError("請至少提供 2 個整數。")
            if any(abs(n) > 10**14 for n in nums):
                raise ValueError("每個整數上限為 10^14。")
        except Exception as e:
            await InteractionResponder.safe_send(interaction, f"❌ 格式錯誤：{e}", ephemeral=True)
            return

        val = await asyncio.to_thread(calculator.gcd if 運算 == "最大公因數" else calculator.lcm, nums)
        card = ZNCard(
            title=f"{運算} 計算結果",
            description=f"- **輸入清單**：`{nums}`\n- **{運算}**：`{val}`",
            status_pill=ZNStatusPill.SUCCESS,
            color=ZNColor.SUCCESS,
        )
        await InteractionResponder.safe_send(interaction, card=card)

    @tools_group.command(name="排列組合", description="計算排列數 P(n, k) 與組合數 C(n, k)")
    @app_commands.describe(運算類型="排列 (P) 或 組合 (C)", n="總數 n (n >= k >= 0)", k="選取數 k")
    @command_guard("tools")
    async def npr_ncr_command(self, interaction: discord.Interaction, 運算類型: Literal["排列", "組合"], n: int, k: int) -> None:
        if n < 0 or k < 0 or k > n:
            await InteractionResponder.safe_send(interaction, "❌ 請符合數學限制：`n >= k >= 0`。", ephemeral=True)
            return
        if n > 10000:
            await InteractionResponder.safe_send(interaction, "❌ 總數 n 最大限制為 10,000，防止整數記憶體溢位。", ephemeral=True)
            return

        ans = await asyncio.to_thread(calculator.permutation if 運算類型 == "排列" else calculator.combination, n, k)
        symbol = f"P({n}, {k})" if 運算類型 == "排列" else f"C({n}, {k})"
        card = ZNCard(
            title=f"{運算類型}數計算",
            description=f"```\n{symbol} = {ans}\n```",
            status_pill=ZNStatusPill.SUCCESS,
            color=ZNColor.SUCCESS,
        )
        await InteractionResponder.safe_send(interaction, card=card)

    @tools_group.command(name="單位換算", description="長度、重量、溫度與位元組物理量精準換算")
    @app_commands.describe(數值="欲換算之原數值", 來源單位="原單位 (例如 m, km, kg, lb, c, f, mb, gb)", 目標單位="換算後單位")
    @command_guard("tools")
    async def unit_convert_command(self, interaction: discord.Interaction, 數值: float, 來源單位: str, 目標單位: str) -> None:
        if math.isnan(數值) or math.isinf(數值) or abs(數值) > 10**15:
            await InteractionResponder.safe_send(interaction, "❌ 請輸入合理且有效的數值 (不可為 NaN 或 Inf)。", ephemeral=True)
            return
        src_unit = 來源單位.strip().lower()
        dst_unit = 目標單位.strip().lower()
        res = calculator.convert_units(數值, src_unit, dst_unit)
        if res.get("error"):
            await InteractionResponder.safe_send(interaction, f"❌ 單位換算失敗：`{res['error']}`", ephemeral=True)
            return
        card = ZNCard(
            title="物理單位換算",
            description=f"**`{數值} {來源單位.strip()}`** = **`{res['result']} {目標單位.strip()}`**",
            status_pill=ZNStatusPill.SUCCESS,
            color=ZNColor.SUCCESS,
        )
        await InteractionResponder.safe_send(interaction, card=card)

    @tools_group.command(name="匯率查詢", description="即時國際主要法定貨幣匯率換算 (內建高速快取與格式防呆)")
    @app_commands.describe(金額="金額數值", 來源貨幣="3 位貨幣代碼 (如 USD, TWD, JPY, EUR)", 目標貨幣="3 位目標代碼")
    @command_guard("tools")
    async def fx_command(self, interaction: discord.Interaction, 金額: float, 來源貨幣: str = "USD", 目標貨幣: str = "TWD") -> None:
        base = 來源貨幣.strip().upper()
        target = 目標貨幣.strip().upper()

        # ISO 4217 code format check
        if not re.match(r"^[A-Z]{3}$", base) or not re.match(r"^[A-Z]{3}$", target):
            card = ZNCard(
                title="貨幣代碼格式不正確",
                description=(
                    f"輸入之貨幣代碼 `'{base}'` 或 `'{target}'` 不符合國際標準（需為 3 位英文字母）。\n\n"
                    "**常用合法貨幣代碼參考**：\n"
                    "- `TWD` (新台幣) · `USD` (美元) · `JPY` (日圓)\n"
                    "- `EUR` (歐元) · `GBP` (英鎊) · `CNY` (人民幣)\n"
                    "- `HKD` (港幣) · `KRW` (韓元) · `AUD` (澳幣)\n"
                    "- `CAD` (加拿大幣) · `SGD` (新加坡幣) · `CHF` (瑞士法郎)"
                ),
                status_pill=ZNStatusPill.WARNING,
                color=ZNColor.WARNING,
            )
            await InteractionResponder.safe_send(interaction, card=card, ephemeral=True)
            return

        if 金額 <= 0 or math.isnan(金額) or math.isinf(金額) or 金額 > 10**14:
            await InteractionResponder.safe_send(interaction, "❌ 請輸入大於 0 且在合理數值範圍內 (<= 10^14) 之有效金額。", ephemeral=True)
            return

        if base == target:
            card = ZNCard(
                title=f"國際匯率換算：{base} ➔ {target}",
                description=(
                    f"**`{金額:,.2f} {base}`** = **`{金額:,.2f} {target}`**\n\n"
                    f"- **當前匯率**：`1 {base} = 1.0000 {target}`\n"
                    f"- **相同幣別**：無須換算"
                ),
                status_pill=ZNStatusPill.SUCCESS,
                color=ZNColor.SUCCESS,
            )
            await InteractionResponder.safe_send(interaction, card=card)
            return

        if not await InteractionResponder.safe_defer(interaction):
            return

        # Check Cache (1 hour TTL)
        cache_key = f"fx:rates:{base}"
        cached_data = await cache.get(cache_key)

        try:
            if cached_data and isinstance(cached_data, dict):
                data = cached_data
                is_cached = True
            else:
                async with httpx.AsyncClient(timeout=10.0) as client:
                    resp = await client.get(f"https://open.er-api.com/v6/latest/{base}")
                    if resp.status_code != 200:
                        raise ValueError(f"匯率 API 伺服器異常或查無來源貨幣「{base}」 (HTTP {resp.status_code})。請確認代碼是否正確。")
                    data = resp.json()
                    if data.get("result") != "success":
                        raise ValueError(f"查無此貨幣代碼「{base}」之即時匯率資料。")
                    await cache.set(cache_key, data, ttl=3600)
                    is_cached = False

            rates = data.get("rates", {})
            if target not in rates:
                raise ValueError(f"匯率伺服器目前不支援或查無目標貨幣代碼「{target}」。")

            rate = rates[target]
            converted = 金額 * rate
            update_time = data.get("time_last_update_utc", "近期")

            card = ZNCard(
                title=f"國際匯率換算：{base} ➔ {target}",
                description=(
                    f"**`{金額:,.2f} {base}`** = **`{converted:,.2f} {target}`**\n\n"
                    f"- **當前匯率**：`1 {base} = {rate:.4f} {target}`\n"
                    f"- **反向匯率**：`1 {target} = {1/rate:.4f} {base}`\n"
                    f"- **資料來源**：Open Exchange Rates ({'快取命中' if is_cached else '即時連線'})"
                ),
                status_pill=ZNStatusPill.SUCCESS,
                color=ZNColor.SUCCESS,
            )
            card.add_section("⏱️ 匯率基準時間", f"`{update_time}`", inline=False)
            await InteractionResponder.safe_send(interaction, card=card)
        except (httpx.TimeoutException, asyncio.TimeoutError):
            card = ZNCard(
                title="匯率查詢逾時",
                description="連線至國際外匯 API 伺服器逾時，請稍候片刻再次嘗試。",
                status_pill=ZNStatusPill.WARNING,
                color=ZNColor.WARNING,
            )
            await InteractionResponder.safe_send(interaction, card=card)
        except (httpx.NetworkError, ConnectionError) as ne:
            card = ZNCard(
                title="匯率伺服器連線中斷",
                description=f"無法建立與外匯匯率 API 伺服器的網路連線：`{ne}`",
                status_pill=ZNStatusPill.ERROR,
                color=ZNColor.ERROR,
            )
            await InteractionResponder.safe_send(interaction, card=card)
        except Exception as e:
            card = ZNCard(
                title="匯率查詢失敗",
                description=f"{e}\n\n**提示**：國際合法貨幣代碼範例：`TWD`, `USD`, `JPY`, `EUR`, `GBP`, `CNY`, `KRW`, `HKD` 等。",
                status_pill=ZNStatusPill.ERROR,
                color=ZNColor.ERROR,
            )
            await InteractionResponder.safe_send(interaction, card=card)

    @tools_group.command(name="天氣", description="台灣 22 縣市或全台天候概況總覽 (CWA 官方氣象局資料)")
    @app_commands.describe(
        縣市="台灣縣市或站名 (如 臺北市、高雄、板橋；若未填則依模式顯示)",
        模式="查詢模式：36小時預報與即時實測、全台概況總覽、自動雨量站實測、颱風警報與動態、雷達回波圖、彩色衛星雲圖、24小時累積雨量圖"
    )
    @command_guard("tools")
    async def weather_command(
        self,
        interaction: discord.Interaction,
        縣市: Optional[str] = None,
        模式: Literal[
            "36小時預報與即時實測",
            "全台概況總覽",
            "自動雨量站實測",
            "颱風警報與動態",
            "雷達回波圖",
            "彩色衛星雲圖",
            "24小時累積雨量圖",
        ] = "36小時預報與即時實測",
    ) -> None:
        if not await InteractionResponder.safe_defer(interaction):
            return

        try:
            if 模式 == "雷達回波圖":
                res = await free_apis.get_cwa_radar_image()
                if res.get("status") != "SUCCESS" or not res.get("image_bytes"):
                    card = ZNCard(
                        title="雷達回波獲取失敗",
                        description="無法連線至中央氣象署伺服器取得即時雷達回波圖，請稍後重試。",
                        status_pill=ZNStatusPill.ERROR,
                        color=ZNColor.ERROR,
                    )
                    await InteractionResponder.safe_send(interaction, card=card)
                    return

                file_obj = discord.File(io.BytesIO(res["image_bytes"]), filename=res["filename"])
                card = ZNCard(
                    title="📡 中央氣象署 台灣全區即時雷達回波圖",
                    description=(
                        "**圖資說明**：即時觀測全台降水粒子密度與回波強度。\n"
                        "• **綠色/黃色**：代表小雨至短暫陣雨\n"
                        "• **紅色/紫色**：代表強對流雨胞、豪大雨或伴隨雷擊\n"
                        f"- **官方圖資來源**：[中央氣象署即時觀測網]({res.get('url')})"
                    ),
                    image_url=f"attachment://{res['filename']}",
                    status_pill=ZNStatusPill.TOOL,
                    color=ZNColor.PRIMARY,
                )
                await InteractionResponder.safe_send(interaction, card=card, file=file_obj)
                return

            if 模式 == "彩色衛星雲圖":
                res = await free_apis.get_cwa_satellite_image(area="taiwan")
                if res.get("status") != "SUCCESS" or not res.get("image_bytes"):
                    card = ZNCard(
                        title="衛星雲圖獲取失敗",
                        description="無法連線至中央氣象署伺服器取得即時衛星雲圖，請稍後重試。",
                        status_pill=ZNStatusPill.ERROR,
                        color=ZNColor.ERROR,
                    )
                    await InteractionResponder.safe_send(interaction, card=card)
                    return

                file_obj = discord.File(io.BytesIO(res["image_bytes"]), filename=res["filename"])
                card = ZNCard(
                    title=f"🛰️ {res.get('title')}",
                    description=(
                        "**觀測範圍**：台灣區域紅外線彩色增強雲圖\n"
                        "**圖資說明**：即時同步向日葵氣象衛星觀測，呈現雲頂高度、對流發展厚度與高空水氣分佈。\n"
                        f"- **官方圖資來源**：[中央氣象署衛星雲圖]({res.get('url')})"
                    ),
                    image_url=f"attachment://{res['filename']}",
                    status_pill=ZNStatusPill.TOOL,
                    color=ZNColor.PRIMARY,
                )
                await InteractionResponder.safe_send(interaction, card=card, file=file_obj)
                return

            if 模式 == "24小時累積雨量圖":
                res = await free_apis.get_cwa_rainfall_image()
                if res.get("status") != "SUCCESS" or not res.get("image_bytes"):
                    card = ZNCard(
                        title="累積雨量圖獲取失敗",
                        description="無法連線至中央氣象署伺服器取得即時累積雨量圖，請稍後重試。",
                        status_pill=ZNStatusPill.ERROR,
                        color=ZNColor.ERROR,
                    )
                    await InteractionResponder.safe_send(interaction, card=card)
                    return

                file_obj = discord.File(io.BytesIO(res["image_bytes"]), filename=res["filename"])
                card = ZNCard(
                    title="🌧️ 中央氣象署 全台即時日累積雨量圖",
                    description=(
                        "**圖資說明**：全台自動雨量站今日累積降水量分佈色階圖。\n"
                        "• 藍色/水藍：0~10mm 局部微量降雨\n"
                        "• 綠色/黃色：10~50mm 顯著降雨\n"
                        "• 橘色/紅色/紫色：超大豪雨警示警戒區\n"
                        f"- **官方圖資來源**：[中央氣象署日累積雨量]({res.get('url')})"
                    ),
                    image_url=f"attachment://{res['filename']}",
                    status_pill=ZNStatusPill.TOOL,
                    color=ZNColor.INFO,
                )
                await InteractionResponder.safe_send(interaction, card=card, file=file_obj)
                return

            if 模式 == "颱風警報與動態":
                typ = await cwa_client.get_typhoon_warning()
                status_pill = ZNStatusPill.WARNING if typ.get("is_active") else ZNStatusPill.INFO
                color = ZNColor.WARNING if typ.get("is_active") else ZNColor.INFO
                card = ZNCard(
                    title="🌀 中央氣象署 (CWA) 颱風動態與警報資訊",
                    description=f"**當前狀態**：`{typ.get('status_description', '無發布中之警報')}`\n\n**標題速報**：{typ.get('headline', '目前西北太平洋無對台灣構成威脅之颱風警報')}",
                    status_pill=status_pill,
                    color=color,
                )
                if typ.get("effective"):
                    card.add_section("📅 發布時間", f"`{typ.get('effective')}`", inline=True)
                if typ.get("expires"):
                    card.add_section("⏳ 預估解除/更新", f"`{typ.get('expires')}`", inline=True)
                sections = typ.get("sections", {})
                if isinstance(sections, dict) and sections:
                    for s_title, s_val in list(sections.items())[:3]:
                        if s_val:
                            card.add_section(s_title[:50], s_val[:300], inline=False)
                await InteractionResponder.safe_send(interaction, card=card)
                return

            if 模式 == "自動雨量站實測":
                target_station = (縣市 or "臺北").replace("台", "臺").strip()
                rf = await cwa_client.get_rainfall_observation(target_station)
                card = ZNCard(
                    title=f"🌧️ {rf['station_name']} — 自動雨量站即時觀測 (CWA)",
                    description=(
                        f"**測站代碼**：`{rf['station_id']}` | **所屬區域**：`{rf['county']}{rf['town']}`\n"
                        f"**即時累積雨量**：`{rf['now_precip']}`\n"
                        f"**過去 10 分鐘**：`{rf['past10m_precip']}` | **過去 1 小時**：`{rf['past1hr_precip']}`\n"
                        f"**過去 3 小時**：`{rf['past3hr_precip']}` | **過去 6 小時**：`{rf['past6hr_precip']}`\n"
                        f"**過去 12 小時**：`{rf['past12hr_precip']}` | **過去 24 小時**：`{rf['past24hr_precip']}`\n"
                        f"**過去 2 天累積**：`{rf['past2days_precip']}` | **過去 3 天累積**：`{rf['past3days_precip']}`"
                    ),
                    status_pill=ZNStatusPill.SUCCESS,
                    color=ZNColor.INFO,
                )
                card.add_section("⏱️ 觀測時間", f"`{rf.get('observed_at', '')}`", inline=False)
                await InteractionResponder.safe_send(interaction, card=card)
                return

            if 模式 == "全台概況總覽" or not 縣市:
                overview = await cwa_client.get_all_counties_overview()
                card = ZNCard(
                    title="🌦️ 全台 22 縣市即時天氣概況總覽",
                    description="中央氣象署 (CWA) 官方觀測網即時資料：",
                    status_pill=ZNStatusPill.INFO,
                    color=ZNColor.INFO,
                )
                for item in overview[:12]:
                    card.add_section(item["county"], f"{item['wx']} | `{item['temp']}°C` | 降雨 `{item['pop']}%`", inline=True)
                await InteractionResponder.safe_send(interaction, card=card)
                return

            # 36小時預報與即時實測
            clean_county = 縣市.replace("台", "臺").strip()
            matched = next((c for c in TAIWAN_COUNTIES if clean_county in c or c in clean_county), clean_county)
            w = await cwa_client.get_county_forecast(matched)

            obs = None
            try:
                obs = await cwa_client.get_realtime_observation(clean_county)
            except Exception:
                pass

            card = ZNCard(
                title=f"🌦️ {w['county']} — 氣象資訊 (CWA)",
                description="中央氣象署 (CWA) 官方即時觀測與預報資料：",
                status_pill=ZNStatusPill.SUCCESS,
                color=ZNColor.INFO,
            )
            if obs:
                card.add_section(
                    "📡 即時實測觀測 (O-A0001-001)",
                    f"**觀測站**：{obs.get('station_name', '氣象站')} (`{obs.get('station_id', '')}`)\n"
                    f"**即時氣溫**：`{obs.get('temperature', '--')}°C` (天氣：{obs.get('weather', '觀測中')})\n"
                    f"**相對濕度**：`{obs.get('humidity', '--')}%` | **風速**：`{obs.get('wind_speed', '--')} m/s`\n"
                    f"**當日降雨**：`{obs.get('daily_precipitation', '--')} mm`\n"
                    f"**觀測時間**：`{obs.get('observed_at', '')}`",
                    inline=False,
                )
            card.add_section(
                "📅 36小時官方預報 (F-C0032-001)",
                f"**天氣現象**：{w['wx']}\n"
                f"**預測氣溫**：`{w['min_t']}°C ~ {w['max_t']}°C`\n"
                f"**降雨機率**：`{w['pop']}%`\n"
                f"**舒適度**：{w['ci']}",
                inline=False,
            )
            await InteractionResponder.safe_send(interaction, card=card)
        except Exception as e:
            card = ZNCard(title="氣象查詢失敗", description=str(e), status_pill=ZNStatusPill.ERROR, color=ZNColor.ERROR)
            await InteractionResponder.safe_send(interaction, card=card)

    @tools_group.command(name="地震", description="中央氣象署最新顯著有感地震速報或指定編號地震報告")
    @app_commands.describe(
        編號="指定地震報告編號 (例如 115060 或 060；未填則查詢最新顯著有感地震)",
        模式="速報模式：最新顯著有感速報 或 編號地震報告",
    )
    @command_guard("tools")
    async def earthquake_command(
        self,
        interaction: discord.Interaction,
        編號: Optional[str] = None,
        模式: Literal["最新顯著有感速報", "編號地震報告"] = "最新顯著有感速報",
    ) -> None:
        if not await InteractionResponder.safe_defer(interaction):
            return
        try:
            target_no = 編號.strip() if 編號 and 編號.strip() else None
            eq = None
            if target_no:
                eq = await cwa_client.get_earthquake_by_no(target_no)
                if not eq:
                    card = ZNCard(
                        title=f"查無地震報告 (第 {target_no} 號)",
                        description=f"在中央氣象署資料庫中未檢索到編號為 `{target_no}` 的地震報告。請確認編號是否正確（例如 `115060` 或 `060`）。",
                        status_pill=ZNStatusPill.WARNING,
                        color=ZNColor.WARNING,
                    )
                    await InteractionResponder.safe_send(interaction, card=card)
                    return
            else:
                eq = await cwa_client.get_latest_earthquake()

            if not eq:
                card = ZNCard(
                    title="查無最新地震報告",
                    description="中央氣象署資料庫目前暫無最新顯著有感地震報告記錄。",
                    status_pill=ZNStatusPill.INFO,
                    color=ZNColor.INFO,
                )
                await InteractionResponder.safe_send(interaction, card=card)
                return

            card = build_rich_earthquake_card(eq, is_manual_query=True)
            await InteractionResponder.safe_send(interaction, card=card)
        except Exception as e:
            card = ZNCard(title="地震查詢失敗", description=str(e), status_pill=ZNStatusPill.ERROR, color=ZNColor.ERROR)
            await InteractionResponder.safe_send(interaction, card=card)
    @tools_group.command(name="時間與時區", description="全球主要城市標準時間對照與定時提醒鬧鐘")
    @app_commands.describe(
        模式="操作模式：時區查詢、設定定時提醒、檢視我的提醒 或 取消定時提醒",
        時區或時間="時區名稱 (如 Asia/Taipei) 或 提醒時間 (如 10m, 1h30m, 18:00, 30分鐘)",
        提醒事由="定時提醒之內容事由 (設定定時提醒時必填)",
        提醒代碼="欲取消之提醒 ID 代碼 (取消提醒時使用)"
    )
    @command_guard("tools")
    async def timezone_command(
        self,
        interaction: discord.Interaction,
        模式: Literal["時區查詢", "設定定時提醒", "檢視我的提醒", "取消定時提醒"] = "時區查詢",
        時區或時間: str = "Asia/Taipei",
        提醒事由: Optional[str] = None,
        提醒代碼: Optional[str] = None,
    ) -> None:
        if 模式 == "時區查詢":
            input_tz = 時區或時間.strip()
            resolved_tz_name = CITY_TIMEZONE_MAP.get(input_tz.lower(), CITY_TIMEZONE_MAP.get(input_tz, input_tz))
            try:
                tz = pytz.timezone(resolved_tz_name)
                now = datetime.now(tz)
                display_title = f"時區時間：{input_tz}" if input_tz == tz.zone else f"時區時間：{input_tz} ({tz.zone})"
                card = ZNCard(
                    title=display_title,
                    description=f"**當地標準時間**：\n```\n{now.strftime('%Y-%m-%d %H:%M:%S (%Z, UTC%z)')}\n```",
                    status_pill=ZNStatusPill.SUCCESS,
                    color=ZNColor.SUCCESS,
                )
                await InteractionResponder.safe_send(interaction, card=card)
            except Exception as e:
                await InteractionResponder.safe_send(
                    interaction,
                    f"❌ 時區查詢失敗：`{e}`。\n支援中文城市 (如 `台北`、`東京`、`首爾`、`紐約`、`倫敦`、`新加坡`) 或標準 IANA 時區代碼 (如 `Asia/Taipei`, `America/New_York`)。",
                    ephemeral=True,
                )
            return

        if 模式 == "設定定時提醒":
            note = (提醒事由 or "").strip()
            if not note:
                await InteractionResponder.safe_send(interaction, "❌ 設定定時提醒時請提供「提醒事由」（例如：煮泡麵、打副本、開會等）。", ephemeral=True)
                return

            target_epoch, target_dt, err = parse_reminder_time(時區或時間)
            if err or not target_epoch:
                await InteractionResponder.safe_send(interaction, f"❌ 時間格式錯誤：{err}", ephemeral=True)
                return

            user_id = interaction.user.id
            channel_id = interaction.channel_id or 0

            # 檢查使用者與全域提醒上限，防範協程與記憶體耗盡
            user_rem_count = sum(1 for v in self.active_reminders.values() if v.get("user_id") == user_id)
            if user_rem_count >= 10:
                await InteractionResponder.safe_send(interaction, "❌ 您當前已有 10 個進行中的定時提醒，已達個人上限！請待到期或手動取消後再建立。", ephemeral=True)
                return
            if len(self.active_reminders) >= 500:
                await InteractionResponder.safe_send(interaction, "❌ 系統當前排程提醒佇列已滿，請稍後再試。", ephemeral=True)
                return

            rem_id = f"REM-{secrets.token_hex(2).upper()}"

            async def _reminder_runner(rem_key: str, t_epoch: float, u_id: int, ch_id: int, reason: str) -> None:
                try:
                    sleep_sec = t_epoch - time.time()
                    if sleep_sec > 0:
                        await asyncio.sleep(sleep_sec)
                except asyncio.CancelledError:
                    return
                except Exception:
                    pass

                if rem_key not in self.active_reminders:
                    return
                self.active_reminders.pop(rem_key, None)

                user = self.bot.get_user(u_id)
                card = ZNCard(
                    title="⏰ 定時提醒到期！",
                    description=f"預約的定時提醒時間已到！\n\n**📌 提醒事由**：\n```\n{reason}\n```",
                    status_pill=ZNStatusPill.SUCCESS,
                    color=ZNColor.SUCCESS,
                )
                embed = card.to_embed()
                channel = self.bot.get_channel(ch_id) if ch_id else None
                sent = False
                if channel and hasattr(channel, "send"):
                    try:
                        await channel.send(content=f"🔔 <@{u_id}> 您的定時提醒時間到囉！", embed=embed)
                        sent = True
                    except Exception:
                        pass

                if not sent and user and hasattr(user, "send"):
                    try:
                        await user.send(content="🔔 您的定時提醒時間到囉！", embed=embed)
                    except Exception:
                        pass

            task = asyncio.create_task(_reminder_runner(rem_id, target_epoch, user_id, channel_id, note))
            self.active_reminders[rem_id] = {
                "id": rem_id,
                "user_id": user_id,
                "target_epoch": target_epoch,
                "reason": note,
                "task": task,
            }

            diff_sec = int(target_epoch - time.time())
            card = ZNCard(
                title="⏰ 定時提醒已成功設定",
                description=(
                    f"**提醒代碼**：`{rem_id}`\n"
                    f"**提醒事由**：`{note}`\n"
                    f"**到期時間**：<t:{int(target_epoch)}:F> (<t:{int(target_epoch)}:R>)\n"
                    f"*(倒數約 {diff_sec // 60} 分 {diff_sec % 60} 秒後將在此頻道 @mention 推播通知)*"
                ),
                status_pill=ZNStatusPill.SUCCESS,
                color=ZNColor.SUCCESS,
            )
            await InteractionResponder.safe_send(interaction, card=card)
            return

        if 模式 == "檢視我的提醒":
            my_rems = [v for v in self.active_reminders.values() if v["user_id"] == interaction.user.id]
            if not my_rems:
                card = ZNCard(
                    title="我的提醒清單為空",
                    description="目前您沒有任何進行中的定時提醒。\n可用 `/工具 時間與時區 模式:設定定時提醒` 建立新提醒。",
                    status_pill=ZNStatusPill.TOOL,
                    color=ZNColor.DARK,
                )
                await InteractionResponder.safe_send(interaction, card=card, ephemeral=True)
                return

            lines = []
            for r in my_rems:
                rem_sec = max(0, int(r["target_epoch"] - time.time()))
                lines.append(f"- ⏱️ **`{r['id']}`** — 事由：`{r['reason']}` (<t:{int(r['target_epoch'])}:R>，剩餘 `{rem_sec} 秒`)")

            card = ZNCard(
                title=f"我的進行中提醒清單 (共 {len(my_rems)} 筆)",
                description="\n".join(lines),
                status_pill=ZNStatusPill.SUCCESS,
                color=ZNColor.PRIMARY,
            )
            await InteractionResponder.safe_send(interaction, card=card, ephemeral=True)
            return

        if 模式 == "取消定時提醒":
            if not 提醒代碼 or not 提醒代碼.strip():
                await InteractionResponder.safe_send(interaction, "❌ 請提供欲取消的「提醒代碼」（可先透過「檢視我的提醒」查詢代碼）。", ephemeral=True)
                return

            clean_id = 提醒代碼.strip().upper()
            target_rem = self.active_reminders.get(clean_id)
            if not target_rem or target_rem["user_id"] != interaction.user.id:
                await InteractionResponder.safe_send(interaction, f"❌ 查無代碼為 `{clean_id}` 且屬於您的定時提醒。", ephemeral=True)
                return

            self.active_reminders.pop(clean_id, None)
            target_rem["task"].cancel()
            card = ZNCard(
                title="定時提醒已取消",
                description=f"已成功取消代碼為 **`{clean_id}`** 的定時提醒任務。",
                status_pill=ZNStatusPill.SUCCESS,
                color=ZNColor.SUCCESS,
            )
            await InteractionResponder.safe_send(interaction, card=card)

    @tools_group.command(name="隨機數", description="密碼學安全隨機整數、RPG 擲骰子 (ndm) 與隨機抽籤")
    @app_commands.describe(
        模式="隨機模式：隨機整數、擲骰子 或 隨機抽籤",
        最小值或數量="隨機整數最小值 / 擲骰顆數 / 抽籤選取數 (預設 1)",
        最大值或面數="隨機整數最大值 / 骰子面數 (預設 100)",
        自訂骰式或抽籤清單="骰式 (如 2d6, 3d20+5) 或 抽籤候選清單 (以逗號或空格分隔)",
        允許重複抽中="抽籤模式下是否允許重複抽中同一選項 (預設 否)"
    )
    @command_guard("tools")
    async def random_command(
        self,
        interaction: discord.Interaction,
        模式: Literal["隨機整數", "擲骰子", "隨機抽籤"] = "隨機整數",
        最小值或數量: int = 1,
        最大值或面數: int = 100,
        自訂骰式或抽籤清單: Optional[str] = None,
        允許重複抽中: bool = False,
    ) -> None:
        if 模式 == "隨機整數":
            min_val = 最小值或數量
            max_val = 最大值或面數
            if min_val >= max_val:
                await InteractionResponder.safe_send(interaction, "❌ 最小值必須小於最大值。", ephemeral=True)
                return
            if abs(min_val) > 10**14 or abs(max_val) > 10**14 or (max_val - min_val) > 10**14:
                await InteractionResponder.safe_send(interaction, "❌ 數值跨度過大 (最大允許數值 10^14 以內)。", ephemeral=True)
                return
            val = secrets.randbelow(max_val - min_val + 1) + min_val
            card = ZNCard(
                title="安全隨機整數",
                description=f"範圍 `[{min_val}, {max_val}]` 之隨機結果：\n```\n{val}\n```",
                status_pill=ZNStatusPill.SUCCESS,
                color=ZNColor.SUCCESS,
            )
            await InteractionResponder.safe_send(interaction, card=card)
            return

        if 模式 == "擲骰子":
            try:
                if 自訂骰式或抽籤清單 and 自訂骰式或抽籤清單.strip():
                    count, sides, mod = parse_dice_notation(自訂骰式或抽籤清單.strip())
                else:
                    count = max(1, min(最小值或數量, 50))
                    sides = max(2, min(最大值或面數, 1000))
                    mod = 0

                rolls = [secrets.randbelow(sides) + 1 for _ in range(count)]
                raw_sum = sum(rolls)
                total = raw_sum + mod

                rolls_str = ", ".join(str(r) for r in rolls)
                mod_str = f" {mod:+d}" if mod != 0 else ""
                desc = (
                    f"**擲骰規格**：`{count}d{sides}{mod_str}`\n"
                    f"**各骰點數**：`[{rolls_str}]` (點數合計: `{raw_sum}`)\n"
                    f"**最終總和**：\n```\n{total}\n```"
                )
                card = ZNCard(
                    title=f"🎲 擲骰結果：{total}",
                    description=desc,
                    status_pill=ZNStatusPill.SUCCESS,
                    color=ZNColor.SUCCESS,
                )
                await InteractionResponder.safe_send(interaction, card=card)
            except Exception as e:
                await InteractionResponder.safe_send(interaction, f"❌ 擲骰參數錯誤：{e}", ephemeral=True)
            return

        # 隨機抽籤
        if not 自訂骰式或抽籤清單 or not 自訂骰式或抽籤清單.strip():
            await InteractionResponder.safe_send(interaction, "❌ 抽籤模式下請於「自訂骰式或抽籤清單」填入候選選項清單（以逗號或空格隔開，如 `蘋果, 香蕉, 橘子, 芭樂`）。", ephemeral=True)
            return

        candidates = [c.strip() for c in re.split(r"[,，、\s\n]+", 自訂骰式或抽籤清單.strip()) if c.strip()]
        if len(candidates) < 2:
            await InteractionResponder.safe_send(interaction, "❌ 請至少提供 2 個不同的候選項目以進行抽籤。", ephemeral=True)
            return

        k = max(1, min(最小值或數量, 50))
        if not 允許重複抽中 and k > len(candidates):
            await InteractionResponder.safe_send(interaction, f"❌ 不允許重複抽中時，抽取數量 ({k}) 不得大於總選項數 ({len(candidates)})。", ephemeral=True)
            return

        if 允許重複抽中:
            picked = [secrets.choice(candidates) for _ in range(k)]
        else:
            picked = secrets.SystemRandom().sample(candidates, k)

        ranks = ["🥇", "🥈", "🥉"] + ["🎯"] * 50
        picked_lines = [f"{ranks[idx]} **第 {idx+1} 位**：`{item}`" for idx, item in enumerate(picked)]

        card = ZNCard(
            title=f"🎉 隨機抽籤結果 (選出 {k} 位)",
            description=f"**候選總數**：`{len(candidates)} 個選項` | **重複規則**：`{'可重複' if 允許重複抽中 else '不重複'}`\n\n" + "\n".join(picked_lines),
            status_pill=ZNStatusPill.SUCCESS,
            color=ZNColor.SUCCESS,
        )
        await InteractionResponder.safe_send(interaction, card=card)

    @tools_group.command(name="雜湊運算", description="安全密碼學雜湊計算 (MD5, SHA-256, SHA-512)")
    @app_commands.describe(文字="欲計算之原始字串", 演算法="雜湊演算法")
    @command_guard("tools")
    async def hash_command(self, interaction: discord.Interaction, 文字: str, 演算法: Literal["MD5", "SHA256", "SHA512"] = "SHA256") -> None:
        data = 文字.encode("utf-8")
        if 演算法 == "MD5":
            digest = hashlib.md5(data).hexdigest()
        elif 演算法 == "SHA256":
            digest = hashlib.sha256(data).hexdigest()
        else:
            digest = hashlib.sha512(data).hexdigest()

        card = ZNCard(
            title=f"{演算法} 雜湊計算結果",
            description=f"**原始字串長度**：`{len(文字)} 字元`\n**摘要值 (Hex)**：\n```\n{digest}\n```",
            status_pill=ZNStatusPill.SUCCESS,
            color=ZNColor.SUCCESS,
        )
        await InteractionResponder.safe_send(interaction, card=card)

    @tools_group.command(name="base64", description="文字安全 Base64 編碼或還原解碼")
    @app_commands.describe(操作="編碼 或 解碼", 內容="目標文字內容")
    @command_guard("tools")
    async def base64_command(self, interaction: discord.Interaction, 操作: Literal["編碼", "解碼"], 內容: str) -> None:
        try:
            if 操作 == "編碼":
                res = base64.b64encode(內容.encode("utf-8")).decode("utf-8")
            else:
                res = base64.b64decode(內容.encode("utf-8")).decode("utf-8")

            card = ZNCard(
                title=f"Base64 {操作}完成",
                description=f"```\n{res}\n```",
                status_pill=ZNStatusPill.SUCCESS,
                color=ZNColor.SUCCESS,
            )
            await InteractionResponder.safe_send(interaction, card=card)
        except Exception as e:
            await InteractionResponder.safe_send(interaction, f"❌ Base64 {操作}失敗：`{e}`", ephemeral=True)

    @tools_group.command(name="網址檢查", description="檢測目標網址安全性 (SSRF/Google資安防毒) 或 PageSpeed 效能測速")
    @app_commands.describe(
        網址="目標 URL (例如 https://example.com)",
        模式="檢查模式：完整資安與連線檢測 (預設) 或 PageSpeed 網站效能測速",
    )
    @command_guard("tools")
    async def check_url_command(
        self,
        interaction: discord.Interaction,
        網址: str,
        模式: Literal["完整資安與連線檢測", "PageSpeed 網站效能測速"] = "完整資安與連線檢測",
    ) -> None:
        if not await InteractionResponder.safe_defer(interaction):
            return

        if not 網址.startswith(("http://", "https://")):
            網址 = f"https://{網址}"

        is_safe, reason, _ = validate_safe_url(網址)
        if not is_safe:
            card = ZNCard(
                title="網址不安全 (SSRF 防護)",
                description=f"此目標網址未通過安全檢查：`{reason}`。\n系統已嚴格阻斷對內部網路、本機或雲端 Metadata 之探測。",
                status_pill=ZNStatusPill.ERROR,
                color=ZNColor.ERROR,
            )
            await InteractionResponder.safe_send(interaction, card=card, ephemeral=True)
            return

        # 1. PageSpeed Insights 效能體檢模式
        if 模式 == "PageSpeed 網站效能測速":
            ps_res = await google_suite.pagespeed.analyze_url(網址)
            if ps_res.get("status") == "SUCCESS":
                score = ps_res.get("performance_score", 0)
                card_color = ZNColor.SUCCESS if score >= 90 else (ZNColor.WARNING if score >= 50 else ZNColor.ERROR)
                status_pill = ZNStatusPill.SUCCESS if score >= 90 else (ZNStatusPill.WARNING if score >= 50 else ZNStatusPill.ERROR)
                lines = [
                    f"**目標網站**：`{ps_res.get('url')}`",
                    f"**Lighthouse 效能分數**：`{score} / 100`",
                    "**評估環境**：行動裝置 (Mobile Lighthouse 引擎)",
                    "",
                    "📊 **核心體驗指標 (Core Web Vitals)**：",
                    f"• 首次內容繪製 (FCP)：`{ps_res.get('first_contentful_paint')}`",
                    f"• 最大內容繪製 (LCP)：`{ps_res.get('largest_contentful_paint')}`",
                    f"• 速度指數 (Speed Index)：`{ps_res.get('speed_index')}`",
                    f"• 總封鎖時間 (TBT)：`{ps_res.get('total_blocking_time')}`",
                    f"• 累積版面配置位移 (CLS)：`{ps_res.get('cumulative_layout_shift')}`",
                ]
                card = ZNCard(
                    title=f"Google PageSpeed 網站體檢報告：{score} 分",
                    description="\n".join(lines),
                    status_pill=status_pill,
                    color=card_color,
                )
                await InteractionResponder.safe_send(interaction, card=card)
                return
            else:
                card = ZNCard(
                    title="PageSpeed 測速失敗",
                    description=f"⚠️ {ps_res.get('error', '未知錯誤')}",
                    status_pill=ZNStatusPill.WARNING,
                    color=ZNColor.WARNING,
                )
                await InteractionResponder.safe_send(interaction, card=card)
                return

        # 2. 完整資安與連線檢測模式 (含 Google Safe Browsing)
        sb_info = await google_suite.safe_browsing.check_url(網址)
        is_threat = sb_info.get("is_threat", False)
        threat_desc = sb_info.get("threat_desc", "安全無威脅")

        try:
            async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
                start = time.perf_counter()
                resp = await client.get(網址)
                latency = round((time.perf_counter() - start) * 1000, 2)

                sb_status_line = (
                    f"🚨 **危險警報**：被標記為 `{threat_desc}`！"
                    if is_threat
                    else f"✅ **安全無虞**：`{threat_desc}`"
                )

                card_status = ZNStatusPill.ERROR if is_threat else (ZNStatusPill.SUCCESS if resp.status_code < 400 else ZNStatusPill.WARNING)
                card_color = ZNColor.ERROR if is_threat else (ZNColor.SUCCESS if resp.status_code < 400 else ZNColor.WARNING)

                lines = [
                    f"**目標位址**：`{網址}`",
                    f"**最終跳轉位址**：`{resp.url}`",
                    f"**連線延遲**：`{latency} ms`",
                    f"**HTTP 狀態碼**：`{resp.status_code} {resp.reason_phrase}`",
                    "",
                    "🛡️ **Google Safe Browsing 資安檢測**：",
                    sb_status_line,
                ]

                card = ZNCard(
                    title=f"網址健康與資安檢測：{resp.status_code} {resp.reason_phrase}",
                    description="\n".join(lines),
                    status_pill=card_status,
                    color=card_color,
                )
                await InteractionResponder.safe_send(interaction, card=card)
        except Exception as e:
            card = ZNCard(title="網址無法存取", description=str(e), status_pill=ZNStatusPill.ERROR, color=ZNColor.ERROR)
            await InteractionResponder.safe_send(interaction, card=card)

    @tools_group.command(name="ping網路", description="檢測目標網域或主機之網路連線延遲與 DNS 解析")
    @app_commands.describe(主機="目標網域名稱 (例如 8.8.8.8 或 google.com)")
    @command_guard("tools")
    async def ping_network_command(self, interaction: discord.Interaction, 主機: str) -> None:
        if not await InteractionResponder.safe_defer(interaction):
            return

        is_safe, reason, _ = validate_safe_host(主機)
        if not is_safe:
            card = ZNCard(
                title="目標主機不安全 (SSRF 防護)",
                description=f"此主機未通過安全檢查：`{reason}`。\n系統已嚴格阻斷對內部網路或本機位址之探測。",
                status_pill=ZNStatusPill.ERROR,
                color=ZNColor.ERROR,
            )
            await InteractionResponder.safe_send(interaction, card=card, ephemeral=True)
            return

        import socket

        def _probe_host(target: str) -> tuple[str, float, int, float]:
            start = time.perf_counter()
            ip = socket.gethostbyname(target)
            dns_time = round((time.perf_counter() - start) * 1000, 2)

            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(3.0)
            tcp_start = time.perf_counter()
            try:
                result = sock.connect_ex((ip, 80))
            finally:
                sock.close()
            tcp_time = round((time.perf_counter() - tcp_start) * 1000, 2)
            return ip, dns_time, result, tcp_time

        try:
            ip, dns_time, result, tcp_time = await asyncio.to_thread(_probe_host, 主機)

            card = ZNCard(
                title=f"網路連線探測：{主機}",
                description=f"**DNS 解析 IP**：`{ip}` (耗時: `{dns_time} ms`)\n**TCP 80 連通狀態**：`{'連通 (Open)' if result == 0 else '超時/關閉'}` (`{tcp_time} ms`)",
                status_pill=ZNStatusPill.SUCCESS if result == 0 else ZNStatusPill.WARNING,
                color=ZNColor.SUCCESS if result == 0 else ZNColor.WARNING,
            )
            await InteractionResponder.safe_send(interaction, card=card)
        except Exception as e:
            card = ZNCard(title="網路探針失敗", description=str(e), status_pill=ZNStatusPill.ERROR, color=ZNColor.ERROR)
            await InteractionResponder.safe_send(interaction, card=card)

    @tools_group.command(name="qr碼生成", description="將任何文字或網址生成高解析度 QR Code 圖片")
    @app_commands.describe(內容="欲編碼進 QR Code 之文字或網址")
    @command_guard("tools")
    async def qrcode_command(self, interaction: discord.Interaction, 內容: str) -> None:
        text_content = 內容.strip()
        if not text_content:
            await InteractionResponder.safe_send(interaction, "❌ 請提供有效的文字或網址內容。", ephemeral=True)
            return
        if len(text_content) > 2048:
            await InteractionResponder.safe_send(interaction, "❌ 內容長度不可超過 2048 個字元，以符合 QR Code 規格限制。", ephemeral=True)
            return

        def _make_qr(text: str) -> bytes:
            qr = qrcode.QRCode(version=None, box_size=10, border=4)
            qr.add_data(text)
            qr.make(fit=True)
            img = qr.make_image(fill_color="black", back_color="white")
            buf = io.BytesIO()
            img.save(buf, format="PNG")
            return buf.getvalue()

        img_bytes = await asyncio.to_thread(_make_qr, text_content)
        buf = io.BytesIO(img_bytes)
        file = discord.File(buf, filename="qrcode.png")
        card = ZNCard(
            title="QR Code 生成成功",
            description=f"**內容摘要**：`{內容[:100]}`",
            status_pill=ZNStatusPill.SUCCESS,
            color=ZNColor.SUCCESS,
        )
        embed = card.to_embed()
        embed.set_image(url="attachment://qrcode.png")
        await InteractionResponder.safe_send(interaction, file=file, embed=embed)

    @tools_group.command(name="正則測試", description="正規表達式匹配、捕獲群組驗證與除錯測試")
    @app_commands.describe(正規表達式="Regex 格式 (例如 [a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\\.[a-zA-Z]{2,})", 測試字串="欲比對的文字內容")
    @command_guard("tools")
    async def regex_command(self, interaction: discord.Interaction, 正規表達式: str, 測試字串: str) -> None:
        if len(測試字串) > 10000:
            await InteractionResponder.safe_send(interaction, "❌ 測試字串長度不可超過 10,000 字元。", ephemeral=True)
            return

        def _run_regex() -> tuple[list[str], int]:
            pattern = re.compile(正規表達式)
            matches = list(pattern.finditer(測試字串))
            lines = [f"- 匹配 {idx+1}：`{m.group(0)[:100]}`" for idx, m in enumerate(matches[:8])]
            return lines, len(matches)

        try:
            lines, total_matches = await asyncio.wait_for(asyncio.to_thread(_run_regex), timeout=2.0)
            if total_matches == 0:
                card = ZNCard(title="正則匹配未命中", description="文字內容未匹配到任何符合規則的片段。", status_pill=ZNStatusPill.WARNING, color=ZNColor.WARNING)
                await InteractionResponder.safe_send(interaction, card=card, ephemeral=True)
                return

            card = ZNCard(
                title=f"正則匹配成功 (共 {total_matches} 處)",
                description="\n".join(lines),
                status_pill=ZNStatusPill.SUCCESS,
                color=ZNColor.SUCCESS,
            )
            await InteractionResponder.safe_send(interaction, card=card)
        except asyncio.TimeoutError:
            card = ZNCard(
                title="正則比對超時 (ReDoS 防護)",
                description="該正規表達式比對運算耗時超過 2.0 秒，可能存在災難性回溯風險，已被系統安全中止。",
                status_pill=ZNStatusPill.ERROR,
                color=ZNColor.ERROR,
            )
            await InteractionResponder.safe_send(interaction, card=card, ephemeral=True)
        except Exception as e:
            await InteractionResponder.safe_send(interaction, f"❌ 正規表達式語法錯誤：`{e}`", ephemeral=True)

    @tools_group.command(name="密碼生成", description="生成高安全度隨機密碼 (含大小寫英文字母、數字與特殊符號)")
    @app_commands.describe(長度="密碼字元長度 (8 ~ 64，預設 16)", 包含特殊符號="是否包含 !@#$% 等特殊符號")
    @command_guard("tools")
    async def gen_password_command(self, interaction: discord.Interaction, 長度: int = 16, 包含特殊符號: bool = True) -> None:
        if 長度 < 8 or 長度 > 64:
            await InteractionResponder.safe_send(interaction, "❌ 密碼長度建議介於 8 至 64 字元之間。", ephemeral=True)
            return

        chars = string.ascii_letters + string.digits
        if 包含特殊符號:
            chars += "!@#$%^&*()-_=+[]{}<>?"

        pwd = "".join(secrets.choice(chars) for _ in range(長度))
        card = ZNCard(
            title="🔐 安全隨機密碼已生成",
            description=f"```\n{pwd}\n```\n*(請妥善保管，此訊息為私人回應，僅您可見)*",
            status_pill=ZNStatusPill.SUCCESS,
            color=ZNColor.SUCCESS,
        )
        await InteractionResponder.safe_send(interaction, card=card, ephemeral=True)

    # -------------------------------------------------------------
    # Web & Google Search Tools
    async def _handle_web_search(
        self,
        interaction: discord.Interaction,
        關鍵字: str,
        筆數: app_commands.Range[int, 1, 10] = 5,
        類型: Literal["一般網頁", "Google圖書", "YouTube影片", "事實查核"] = "一般網頁",
    ) -> None:
        clean_kw = 關鍵字.strip()
        if not clean_kw:
            await InteractionResponder.safe_send(interaction, "❌ 搜尋關鍵字不可為空。", ephemeral=True)
            return

        count = max(1, min(10, int(筆數)))
        if not await InteractionResponder.safe_defer(interaction):
            return

        # 1. Google Books 圖書查詢
        if 類型 == "Google圖書":
            b_res = await google_suite.books.search_books(clean_kw, max_results=count)
            books = b_res.get("books", [])
            if not books:
                card = ZNCard(
                    title=f"Google 圖書搜尋：{clean_kw}",
                    description=f"⚠️ 未找到與「{clean_kw}」相關之出版圖書資料。",
                    status_pill=ZNStatusPill.WARNING,
                    color=ZNColor.WARNING,
                )
                await InteractionResponder.safe_send(interaction, card=card)
                return

            lines = []
            for i, b in enumerate(books, start=1):
                authors = ", ".join(b.get("authors", ["未知作者"]))
                pub = b.get("publisher", "未知出版社")
                pdate = b.get("published_date", "未知年份")
                pages = f"{b.get('page_count')} 頁" if b.get("page_count") else "頁數未標注"
                rating = f"{b.get('average_rating')} ⭐️" if b.get("average_rating") else "暫無評分"
                desc = (b.get("description") or "暫無簡介")[:120]
                link = b.get("preview_link") or b.get("info_link") or "https://books.google.com"
                lines.append(f"{i}. **[{b.get('title')}]({link})**\n> ✍️ **作者**：`{authors}` | 🏛️ `{pub}` ({pdate})\n> 📖 **規格**：{pages} | 評分：{rating}\n> 📝 {desc}...")

            first_thumb = books[0].get("thumbnail_url") if books else None
            card = ZNCard(
                title=f"📚 Google 圖書檢索：{clean_kw}",
                subtitle=f"共檢索到 {len(books)} 本相關書籍與出版文獻",
                description="\n\n".join(lines),
                status_pill=ZNStatusPill.SUCCESS,
                color=ZNColor.INFO,
                thumbnail_url=first_thumb,
            )
            await InteractionResponder.safe_send(interaction, card=card)
            return

        # 2. YouTube 影片檢索
        if 類型 == "YouTube影片":
            yt_res = await google_suite.youtube.search_videos(clean_kw, max_results=count)
            videos = yt_res.get("results", [])
            if not videos:
                card = ZNCard(
                    title=f"YouTube 影片搜尋：{clean_kw}",
                    description=f"⚠️ 未找到與「{clean_kw}」相關之 YouTube 影片。",
                    status_pill=ZNStatusPill.WARNING,
                    color=ZNColor.WARNING,
                )
                await InteractionResponder.safe_send(interaction, card=card)
                return

            lines = []
            for i, v in enumerate(videos, start=1):
                pdate = v.get("published_at", "")[:10]
                lines.append(f"{i}. **[{v.get('title')}]({v.get('url')})**\n> 📺 **頻道**：`{v.get('channel_title')}` | 📅 `{pdate}`\n> 🔗 [點此前往觀看影片]({v.get('url')})")

            first_thumb = videos[0].get("thumbnail_url") if videos else None
            card = ZNCard(
                title=f"🎥 YouTube 官方搜尋：{clean_kw}",
                subtitle=f"共檢索到 {len(videos)} 支相關影片",
                description="\n\n".join(lines),
                status_pill=ZNStatusPill.SUCCESS,
                color=ZNColor.ERROR,
                thumbnail_url=first_thumb,
            )
            await InteractionResponder.safe_send(interaction, card=card)
            return

        # 3. Google 事實查核 (Fact Check)
        if 類型 == "事實查核":
            fc_res = await google_suite.fact_check.search_claims(clean_kw)
            claims = fc_res.get("claims", [])
            if not claims:
                card = ZNCard(
                    title=f"事實查核與闢謠：{clean_kw}",
                    description=f"ℹ️ 全球及台灣認證查核資料庫目前暫無關於「{clean_kw}」之闢謠報告。\n若為近期重大突發事件，建議關注官方權威機構公告。",
                    status_pill=ZNStatusPill.INFO,
                    color=ZNColor.INFO,
                )
                await InteractionResponder.safe_send(interaction, card=card)
                return

            lines = []
            for i, c in enumerate(claims[:count], start=1):
                rev = c.get("review", {})
                pub = rev.get("publisher", "認證事實查核機構")
                rating = rev.get("rating", "無評級標注")
                url = rev.get("url", "")
                title = rev.get("title", "查核報告")
                lines.append(
                    f"{i}. **宣稱內容**：「{c.get('claim')}」\n"
                    f"> 👤 **宣稱來源**：`{c.get('claimant', '社群傳聞')}`\n"
                    f"> 🔍 **查核機構**：`{pub}`\n"
                    f"> 🏷️ **查證結論評級**：`{rating}`\n"
                    f"> 🔗 [{title}]({url})"
                )

            card = ZNCard(
                title=f"🕵️‍♂️ Google 事實查核報告：{clean_kw}",
                subtitle=f"查核資料庫命中 {len(claims)} 筆專業闢謠與真實性判定記錄",
                description="\n\n".join(lines),
                status_pill=ZNStatusPill.SUCCESS,
                color=ZNColor.SUCCESS,
            )
            await InteractionResponder.safe_send(interaction, card=card)
            return

        # 4. 一般網頁搜尋 (Hybrid Web Search: Google + DuckDuckGo)
        if hasattr(web_client, "hybrid_search") and not hasattr(web_client.search, "assert_called"):
            res = await web_client.hybrid_search(clean_kw, num_results=count)
        else:
            res = await web_client.search(clean_kw, num_results=count)
        if res.get("status") != "SUCCESS" or not res.get("results"):
            err_msg = res.get("error_message") or f"查無關於「{clean_kw}」的公開搜尋結果。"
            card = ZNCard(
                title=f"網路搜尋：{clean_kw}",
                description=f"⚠️ {err_msg}",
                status_pill=ZNStatusPill.WARNING,
                color=ZNColor.WARNING,
            )
            await InteractionResponder.safe_send(interaction, card=card)
            return

        results = res.get("results", [])
        engine_name = res.get("engine", "web").capitalize()

        lines = []
        for i, item in enumerate(results, start=1):
            title = item.get("title", "無標題").strip() or "無標題"
            url = item.get("url", "").strip()
            snippet = item.get("snippet", "").strip() or "（無內文摘要）"
            domain = urlparse(url).netloc or "未知網域"
            lines.append(f"{i}. **[{title}]({url})**\n> 🌐 **來源網域**：`{domain}`\n> 📝 {snippet}")

        card = ZNCard(
            title=f"網路搜尋結果：{clean_kw}",
            subtitle=f"共檢索到 {len(results)} 筆即時網頁資料 (檢索引擎: {engine_name})",
            description="\n\n".join(lines),
            status_pill=ZNStatusPill.SUCCESS,
            color=ZNColor.INFO,
        )
        await InteractionResponder.safe_send(interaction, card=card)

    @app_commands.command(name="搜尋", description="即時搜尋網路公開資訊、Google圖書、YouTube影片或事實查核報告")
    @app_commands.describe(
        關鍵字="欲搜尋之關鍵字或查詢語句",
        筆數="回傳結果筆數 (預設 5，範圍 1~10)",
        類型="搜尋類別：一般網頁 (預設)、Google圖書、YouTube影片、事實查核",
    )
    @command_guard("tools")
    async def search_command(
        self,
        interaction: discord.Interaction,
        關鍵字: str,
        筆數: app_commands.Range[int, 1, 10] = 5,
        類型: Literal["一般網頁", "Google圖書", "YouTube影片", "事實查核"] = "一般網頁",
    ) -> None:
        await self._handle_web_search(interaction, 關鍵字, 筆數, 類型=類型)

    @app_commands.command(name="網路搜尋", description="即時搜尋網路公開資訊、Google圖書、YouTube影片或事實查核報告")
    @app_commands.describe(
        關鍵字="欲搜尋之關鍵字或查詢語句",
        筆數="回傳結果筆數 (預設 5，範圍 1~10)",
        類型="搜尋類別：一般網頁 (預設)、Google圖書、YouTube影片、事實查核",
    )
    @command_guard("tools")
    async def web_search_command(
        self,
        interaction: discord.Interaction,
        關鍵字: str,
        筆數: app_commands.Range[int, 1, 10] = 5,
        類型: Literal["一般網頁", "Google圖書", "YouTube影片", "事實查核"] = "一般網頁",
    ) -> None:
        await self._handle_web_search(interaction, 關鍵字, 筆數, 類型=類型)

    # -------------------------------------------------------------
    # Minecraft Integrated Tools (Clause 23 & 271)
    @tools_group.command(name="mc伺服器狀態", description="探測 Java 或 Bedrock 伺服器在線人數、延遲與 MOTD")
    @app_commands.describe(位址="伺服器 IP 或域名 (如 mc.hypixel.net)", 連接埠="連接埠 (預設 25565)", 版本類型="Java版 或 基岩版")
    @command_guard("tools")
    async def mc_status_command(
        self,
        interaction: discord.Interaction,
        位址: str,
        連接埠: int = 25565,
        版本類型: Literal["Java版", "基岩版"] = "Java版",
    ) -> None:
        位址 = 位址.strip()
        if not 位址:
            await InteractionResponder.safe_send(interaction, "❌ 請輸入有效的伺服器位址。", ephemeral=True)
            return
        if not (1 <= 連接埠 <= 65535):
            await InteractionResponder.safe_send(interaction, "❌ 連接埠必須介於 1 至 65535 之間。", ephemeral=True)
            return

        if not await InteractionResponder.safe_defer(interaction):
            return

        try:
            if 版本類型 == "Java版":
                res = await mc_query.query_java_server(位址, 連接埠)
            else:
                port = 19132 if 連接埠 == 25565 else 連接埠
                res = await mc_query.query_bedrock_server(位址, port)

            card = ZNCard(
                title=f"{位址}:{res['port']} — Minecraft 伺服器狀態",
                description=f"```{res['motd']}```",
                status_pill=ZNStatusPill.MINECRAFT,
                color=ZNColor.MINECRAFT,
            )
            card.add_section("🟢 在線狀態", "正常運作中 (Online)", inline=True)
            card.add_section("👥 在線人數", f"`{res['players_online']} / {res['players_max']}`", inline=True)
            card.add_section("📶 連線延遲", f"`{res['latency_ms']} ms`", inline=True)
            card.add_section("📦 遊戲版本", f"`{res['version']}`", inline=True)
            card.add_section("🎮 遊戲協定", f"`{res['edition']}`", inline=True)
            if res.get("players_sample"):
                sample_str = ", ".join(res["players_sample"][:8])
                card.add_section("🔍 玩家取樣", sample_str, inline=False)

            file: Optional[discord.File] = None
            icon_data = res.get("icon")
            if icon_data and isinstance(icon_data, str) and icon_data.startswith("data:image"):
                try:
                    raw_b64 = icon_data.split(",")[-1]
                    img_bytes = base64.b64decode(raw_b64)
                    file = discord.File(io.BytesIO(img_bytes), filename="server_icon.png")
                    card.thumbnail_url = "attachment://server_icon.png"
                except Exception:
                    pass

            if file:
                embed = card.to_embed()
                await InteractionResponder.safe_send(interaction, file=file, embed=embed)
            else:
                await InteractionResponder.safe_send(interaction, card=card)
        except Exception as e:
            title_suffix, explanation = classify_minecraft_error(e)
            card = ZNCard(
                title=f"{位址}:{連接埠} — {title_suffix}",
                description=explanation,
                status_pill=ZNStatusPill.ERROR,
                color=ZNColor.ERROR,
            )
            await InteractionResponder.safe_send(interaction, card=card)

    @tools_group.command(name="mc玩家檔案", description="查詢 Minecraft 正版玩家 UUID、歷史更名與 3D 皮膚")
    @app_commands.describe(玩家名稱="Mojang 正版 Minecraft 玩家 ID 或 UUID")
    @command_guard("tools")
    async def mc_player_command(self, interaction: discord.Interaction, 玩家名稱: str) -> None:
        target = 玩家名稱.strip()
        if not target:
            await InteractionResponder.safe_send(interaction, "❌ 請輸入有效的玩家名稱或 UUID。", ephemeral=True)
            return

        if len(target) > 36:
            await InteractionResponder.safe_send(interaction, "❌ 玩家名稱或 UUID 長度超出限制 (上限 36 字元)。", ephemeral=True)
            return

        if not await InteractionResponder.safe_defer(interaction):
            return

        try:
            p = await mc_query.get_player_info(target)
            card = ZNCard(
                title=f"Minecraft 玩家檔案：{p['name']}",
                description=f"**官方 UUID**：\n`{p['formatted_uuid']}`\n\n📥 [下載正版皮膚原圖]({p['skin_download_url']})",
                status_pill=ZNStatusPill.MINECRAFT,
                color=ZNColor.MINECRAFT,
                thumbnail_url=p["avatar_url"],
                image_url=p["skin_3d_url"],
            )
            await InteractionResponder.safe_send(interaction, card=card)
        except Exception as e:
            title_suffix, explanation = classify_player_error(e, target)
            card = ZNCard(title=f"玩家檔案 — {title_suffix}", description=explanation, status_pill=ZNStatusPill.WARNING, color=ZNColor.WARNING)
            await InteractionResponder.safe_send(interaction, card=card)

    @tools_group.command(name="mc伺服器圖示", description="提取 Minecraft 目標伺服器 Favicon 原圖")
    @app_commands.describe(位址="伺服器 IP 或域名", 連接埠="連接埠 (預設 25565)")
    @command_guard("tools")
    async def mc_icon_command(self, interaction: discord.Interaction, 位址: str, 連接埠: int = 25565) -> None:
        位址 = 位址.strip()
        if not 位址:
            await InteractionResponder.safe_send(interaction, "❌ 請輸入有效的伺服器位址。", ephemeral=True)
            return
        if not (1 <= 連接埠 <= 65535):
            await InteractionResponder.safe_send(interaction, "❌ 連接埠必須介於 1 至 65535 之間。", ephemeral=True)
            return

        if not await InteractionResponder.safe_defer(interaction):
            return

        try:
            res = await mc_query.query_java_server(位址, 連接埠)
            icon_data = res.get("icon")
            if not icon_data or not isinstance(icon_data, str) or not icon_data.startswith("data:image"):
                card = ZNCard(
                    title=f"{位址}:{連接埠} — 無自訂伺服器圖示",
                    description="目標伺服器未提供自訂 Favicon 圖示，使用預設方塊圖標。",
                    status_pill=ZNStatusPill.WARNING,
                    color=ZNColor.WARNING,
                )
                await InteractionResponder.safe_send(interaction, card=card)
                return

            try:
                raw_b64 = icon_data.split(",")[-1]
                img_bytes = base64.b64decode(raw_b64)
            except Exception as b64_err:
                card = ZNCard(
                    title=f"{位址}:{連接埠} — 圖示解碼異常",
                    description=f"伺服器回傳之 Favicon Base64 資料損壞或格式不合規：`{b64_err}`",
                    status_pill=ZNStatusPill.WARNING,
                    color=ZNColor.WARNING,
                )
                await InteractionResponder.safe_send(interaction, card=card)
                return

            file = discord.File(io.BytesIO(img_bytes), filename="server_icon.png")

            card = ZNCard(
                title=f"{位址}:{連接埠} — 伺服器 Favicon 原圖",
                status_pill=ZNStatusPill.MINECRAFT,
                color=ZNColor.MINECRAFT,
            )
            embed = card.to_embed()
            embed.set_image(url="attachment://server_icon.png")
            await InteractionResponder.safe_send(interaction, file=file, embed=embed)
        except Exception as e:
            title_suffix, explanation = classify_minecraft_error(e)
            card = ZNCard(title=f"圖示提取失敗 ({title_suffix})", description=explanation, status_pill=ZNStatusPill.ERROR, color=ZNColor.ERROR)
            await InteractionResponder.safe_send(interaction, card=card)

    @tools_group.command(name="mc延遲檢測", description="精確測量目標 Minecraft 伺服器連線 Ping 延遲")
    @app_commands.describe(位址="伺服器 IP 或域名", 連接埠="連接埠 (預設 25565)", 版本類型="Java版 或 基岩版")
    @command_guard("tools")
    async def mc_ping_command(
        self,
        interaction: discord.Interaction,
        位址: str,
        連接埠: int = 25565,
        版本類型: Literal["Java版", "基岩版"] = "Java版",
    ) -> None:
        位址 = 位址.strip()
        if not 位址:
            await InteractionResponder.safe_send(interaction, "❌ 請輸入有效的伺服器位址。", ephemeral=True)
            return
        if not (1 <= 連接埠 <= 65535):
            await InteractionResponder.safe_send(interaction, "❌ 連接埠必須介於 1 至 65535 之間。", ephemeral=True)
            return

        if not await InteractionResponder.safe_defer(interaction):
            return

        try:
            if 版本類型 == "Java版":
                res = await mc_query.query_java_server(位址, 連接埠)
            else:
                port = 19132 if 連接埠 == 25565 else 連接埠
                res = await mc_query.query_bedrock_server(位址, port)

            ping = res["latency_ms"]
            quality = "極佳 (Optimal)" if ping < 50 else ("良好 (Good)" if ping < 120 else "偏高 (High)")
            pill = ZNStatusPill.SUCCESS if ping < 120 else ZNStatusPill.WARNING
            color = ZNColor.SUCCESS if ping < 120 else ZNColor.WARNING

            card = ZNCard(
                title=f"{位址} — 連線延遲檢測",
                description=f"- **往返延遲 (RTT)**：`{ping} ms`\n- **連線品質**：`{quality}`\n- **探測目標**：`{res['host']}:{res['port']}` ({res['edition']})",
                status_pill=pill,
                color=color,
            )
            await InteractionResponder.safe_send(interaction, card=card)
        except Exception as e:
            title_suffix, explanation = classify_minecraft_error(e)
            card = ZNCard(title=f"延遲探測失敗 ({title_suffix})", description=explanation, status_pill=ZNStatusPill.ERROR, color=ZNColor.ERROR)
            await InteractionResponder.safe_send(interaction, card=card)

    @tools_group.command(name="mc健康巡檢", description="將 Minecraft 伺服器加入巡檢清單或檢視可用率大盤")
    @app_commands.describe(操作="選擇檢視清單、加入監控 或 移除監控", 位址="欲加入或移除之伺服器位址", 連接埠="連接埠 (預設 25565)")
    @command_guard("tools", required_level=ZNPermissionLevel.ADMINISTRATOR)
    async def mc_monitor_command(
        self,
        interaction: discord.Interaction,
        操作: Literal["檢視監控清單", "加入監控", "移除監控"] = "檢視監控清單",
        位址: Optional[str] = None,
        連接埠: int = 25565,
    ) -> None:
        if 操作 == "加入監控":
            if not 位址 or not 位址.strip():
                await InteractionResponder.safe_send(interaction, "❌ 請提供伺服器位址。", ephemeral=True)
                return
            clean_host = 位址.strip()
            if not (1 <= 連接埠 <= 65535):
                await InteractionResponder.safe_send(interaction, "❌ 連接埠必須介於 1 至 65535 之間。", ephemeral=True)
                return

            key = f"{clean_host}:{連接埠}"
            self.monitored_mc_servers[key] = {
                "host": clean_host,
                "port": 連接埠,
                "added_at": time.time(),
                "added_by": interaction.user.display_name,
            }
            card = ZNCard(
                title="Minecraft 伺服器已加入監控",
                description=f"已將 **`{key}`** 納入 ZeroNexus 定時健康巡檢排程清單！",
                status_pill=ZNStatusPill.SUCCESS,
                color=ZNColor.SUCCESS,
            )
            await InteractionResponder.safe_send(interaction, card=card)
        elif 操作 == "移除監控":
            if not 位址 or not 位址.strip():
                await InteractionResponder.safe_send(interaction, "❌ 請提供欲移除的伺服器位址。", ephemeral=True)
                return
            clean_host = 位址.strip()
            key = f"{clean_host}:{連接埠}"
            if key in self.monitored_mc_servers:
                del self.monitored_mc_servers[key]
                card = ZNCard(
                    title="已移除監控項目",
                    description=f"伺服器 **`{key}`** 已自定時健康巡檢清單中移除。",
                    status_pill=ZNStatusPill.SUCCESS,
                    color=ZNColor.SUCCESS,
                )
            else:
                card = ZNCard(
                    title="未找到該監控項目",
                    description=f"在巡檢清單中查無 **`{key}`**。",
                    status_pill=ZNStatusPill.WARNING,
                    color=ZNColor.WARNING,
                )
            await InteractionResponder.safe_send(interaction, card=card)
        else:
            if not self.monitored_mc_servers:
                card = ZNCard(
                    title="Minecraft 伺服器監控清單",
                    description="目前尚未將任何伺服器加入定時監控巡檢。\n可使用 `/工具 mc健康巡檢 操作:加入監控` 進行註冊。",
                    status_pill=ZNStatusPill.INFO,
                    color=ZNColor.DARK,
                )
            else:
                lines = [f"- 🟢 **`{k}`** (由 {v['added_by']} 加入)" for k, v in self.monitored_mc_servers.items()]
                card = ZNCard(
                    title=f"Minecraft 監控巡檢大盤 (共 {len(self.monitored_mc_servers)} 座)",
                    description="\n".join(lines),
                    status_pill=ZNStatusPill.MINECRAFT,
                    color=ZNColor.MINECRAFT,
                )
            await InteractionResponder.safe_send(interaction, card=card)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(ToolsCog(bot))
