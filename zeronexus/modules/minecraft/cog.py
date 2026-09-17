"""ZeroNexus Minecraft Command Cog.

12 Fully Implemented Commands under /mc (已整合於 /工具):
- 伺服器查詢, java伺服器, 基岩伺服器, 延遲檢測, 玩家皮膚, 玩家頭像
- 玩家uuid, 歷史名稱, 伺服器圖示, motd檢視, 監控設定, 監控狀態
"""

from __future__ import annotations

import asyncio
import base64
import io
import time
from typing import Any, Dict, List, Literal, Optional

import discord
from discord import app_commands
from discord.ext import commands

from zeronexus.engines.minecraft_query import (
    classify_minecraft_error,
    classify_player_error,
    mc_query,
)
from zeronexus.modules.base import BaseModule, CommandMetadata
from zeronexus.security.guard import command_guard
from zeronexus.security.permissions import ZNPermissionLevel
from zeronexus.ui.card import ZNCard
from zeronexus.ui.responder import InteractionResponder
from zeronexus.ui.theme import ZNColor, ZNStatusPill


class MinecraftModule(BaseModule):
    """Minecraft server query and player profile inspection."""

    def __init__(self) -> None:
        super().__init__(
            name="minecraft",
            display_name="MC (Minecraft) 模組",
            description="Java 與 Bedrock 伺服器狀態探測、在線人數、延遲檢測與玩家皮膚檢視",
        )
        self.monitored_servers: Dict[str, Dict[str, Any]] = {}

    async def initialize(self, bot: Any) -> None:
        commands_list = [
            ("伺服器查詢", "自動探測伺服器協定並回報綜合狀態", ZNPermissionLevel.EVERYONE),
            ("java伺服器", "查詢 Java 版伺服器人數、版本與 MOTD", ZNPermissionLevel.EVERYONE),
            ("基岩伺服器", "查詢 Bedrock 版伺服器封包狀態", ZNPermissionLevel.EVERYONE),
            ("延遲檢測", "測量目標伺服器連線延遲 Ping", ZNPermissionLevel.EVERYONE),
            ("玩家皮膚", "下載正版玩家 3D 皮膚渲染圖與皮膚檔", ZNPermissionLevel.EVERYONE),
            ("玩家頭像", "獲取正版玩家高畫質頭像", ZNPermissionLevel.EVERYONE),
            ("玩家uuid", "檢索玩家 Mojang 官方 UUID", ZNPermissionLevel.EVERYONE),
            ("歷史名稱", "查詢正版帳號歷史更名紀錄", ZNPermissionLevel.EVERYONE),
            ("伺服器圖示", "提取伺服器 Favicon 原圖", ZNPermissionLevel.EVERYONE),
            ("motd檢視", "檢視格式化後的伺服器宣傳標語", ZNPermissionLevel.EVERYONE),
            ("監控設定", "將伺服器加入或移除定時健康巡檢清單", ZNPermissionLevel.ADMINISTRATOR),
            ("監控狀態", "即時探測並檢視當前已監控伺服器可用率", ZNPermissionLevel.EVERYONE),
        ]
        for name, desc, perm in commands_list:
            self.register_command_meta(CommandMetadata(
                name=name,
                full_name=f"mc {name}",
                description=desc,
                group_name="mc",
                module_name=self.name,
                permission_level=perm,
            ))

    async def shutdown(self) -> None:
        pass


class MinecraftCog(commands.Cog):
    """Discord Slash Command Group for /mc."""

    mc_group = app_commands.Group(name="mc", description="Minecraft 伺服器探測與玩家檔案查詢")

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    async def _execute_java_query(self, interaction: discord.Interaction, 位址: str, 連接埠: int = 25565) -> None:
        位址 = 位址.strip()
        if not 位址:
            await InteractionResponder.safe_send(interaction, "💡 請輸入欲查詢的 Minecraft 伺服器 IP 或網域名稱（例如 `mc.hypixel.net`）。", ephemeral=True)
            return

        if len(位址) > 255:
            await InteractionResponder.safe_send(interaction, "📝 伺服器位址長度超出上限，請確認輸入是否包含多餘字元。", ephemeral=True)
            return

        if not (1 <= 連接埠 <= 65535):
            await InteractionResponder.safe_send(interaction, "🔢 連接埠 (Port) 請填寫 1 至 65535 之間的有效通訊埠數字（Java 版預設為 25565）。", ephemeral=True)
            return

        if not await InteractionResponder.safe_defer(interaction):
            return

        try:
            res = await mc_query.query_java_server(位址, 連接埠)
            card = ZNCard(
                title=f"{位址}:{res['port']} — Java 伺服器狀態",
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
                status_pill=ZNStatusPill.WARNING,
                color=ZNColor.WARNING,
            )
            await InteractionResponder.safe_send(interaction, card=card)

    async def _execute_bedrock_query(self, interaction: discord.Interaction, 位址: str, 連接埠: int = 19132) -> None:
        位址 = 位址.strip()
        if not 位址:
            await InteractionResponder.safe_send(interaction, "💡 請輸入欲查詢的 Minecraft 基岩版伺服器位址或 IP。", ephemeral=True)
            return

        if len(位址) > 255:
            await InteractionResponder.safe_send(interaction, "📝 伺服器位址長度超出上限，請確認輸入是否包含多餘字元。", ephemeral=True)
            return

        if not (1 <= 連接埠 <= 65535):
            await InteractionResponder.safe_send(interaction, "🔢 連接埠 (Port) 請填寫 1 至 65535 之間的有效通訊埠數字（基岩版預設為 19132）。", ephemeral=True)
            return

        if not await InteractionResponder.safe_defer(interaction):
            return

        try:
            res = await mc_query.query_bedrock_server(位址, 連接埠)
            card = ZNCard(
                title=f"{位址}:{連接埠} — 基岩版伺服器狀態",
                description=f"```{res['motd']}```",
                status_pill=ZNStatusPill.MINECRAFT,
                color=ZNColor.MINECRAFT,
            )
            card.add_section("🟢 在線狀態", "正常運作中 (Online)", inline=True)
            card.add_section("👥 在線人數", f"`{res['players_online']} / {res['players_max']}`", inline=True)
            card.add_section("📶 連線延遲", f"`{res['latency_ms']} ms`", inline=True)
            card.add_section("📦 遊戲版本", f"`{res['version']}`", inline=True)
            card.add_section("⚔️ 遊戲模式", f"`{res['gamemode']}`", inline=True)
            await InteractionResponder.safe_send(interaction, card=card)
        except Exception as e:
            title_suffix, explanation = classify_minecraft_error(e)
            card = ZNCard(
                title=f"{位址}:{連接埠} — {title_suffix}",
                description=explanation,
                status_pill=ZNStatusPill.WARNING,
                color=ZNColor.WARNING,
            )
            await InteractionResponder.safe_send(interaction, card=card)

    @mc_group.command(name="伺服器查詢", description="探測 Java 或 Bedrock 伺服器狀態 (支援自動版本協定辨別)")
    @app_commands.describe(
        位址="伺服器 IP 或網域名稱 (例如 mc.hypixel.net)",
        連接埠="連接埠 (Java 預設 25565，基岩預設 19132)",
        版本類型="指定伺服器版本協定，或由系統自動探測"
    )
    @command_guard("minecraft")
    async def query_command(
        self,
        interaction: discord.Interaction,
        位址: str,
        連接埠: Optional[int] = None,
        版本類型: Literal["自動探測", "Java版", "基岩版"] = "自動探測",
    ) -> None:
        port = 連接埠 if 連接埠 is not None else (19132 if 版本類型 == "基岩版" else 25565)
        if 版本類型 == "Java版":
            await self._execute_java_query(interaction, 位址, port)
        elif 版本類型 == "基岩版":
            await self._execute_bedrock_query(interaction, 位址, port)
        else:
            # Automatic protocol detection: Try Java first, fallback to Bedrock
            if not await InteractionResponder.safe_defer(interaction):
                return
            try:
                res = await mc_query.query_java_server(位址, port)
                card = ZNCard(
                    title=f"{位址}:{res['port']} — Java 伺服器狀態",
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
                await InteractionResponder.safe_send(interaction, card=card)
                return
            except Exception:
                # Java query failed; attempt Bedrock query
                pass

            bedrock_port = 連接埠 if 連接埠 is not None else 19132
            try:
                res = await mc_query.query_bedrock_server(位址, bedrock_port)
                card = ZNCard(
                    title=f"{位址}:{bedrock_port} — 基岩版伺服器狀態",
                    description=f"```{res['motd']}```",
                    status_pill=ZNStatusPill.MINECRAFT,
                    color=ZNColor.MINECRAFT,
                )
                card.add_section("🟢 在線狀態", "正常運作中 (Online)", inline=True)
                card.add_section("👥 在線人數", f"`{res['players_online']} / {res['players_max']}`", inline=True)
                card.add_section("📶 連線延遲", f"`{res['latency_ms']} ms`", inline=True)
                card.add_section("📦 遊戲版本", f"`{res['version']}`", inline=True)
                card.add_section("⚔️ 遊戲模式", f"`{res['gamemode']}`", inline=True)
                await InteractionResponder.safe_send(interaction, card=card)
            except Exception as e:
                title_suffix, explanation = classify_minecraft_error(e)
                card = ZNCard(
                    title=f"{位址} — {title_suffix}",
                    description=f"{explanation}\n*(已自動嘗試探測 Java 與 Bedrock 基岩版埠口均未連通)*",
                    status_pill=ZNStatusPill.ERROR,
                    color=ZNColor.ERROR,
                )
                await InteractionResponder.safe_send(interaction, card=card)

    @mc_group.command(name="java伺服器", description="精確查詢 Java 版伺服器詳細狀態")
    @app_commands.describe(位址="Java 伺服器位址", 連接埠="連接埠 (預設 25565)")
    @command_guard("minecraft")
    async def java_command(self, interaction: discord.Interaction, 位址: str, 連接埠: int = 25565) -> None:
        await self._execute_java_query(interaction, 位址, 連接埠)

    @mc_group.command(name="基岩伺服器", description="查詢 Bedrock 基岩版伺服器狀態")
    @app_commands.describe(位址="基岩版伺服器位址", 連接埠="連接埠 (預設 19132)")
    @command_guard("minecraft")
    async def bedrock_command(self, interaction: discord.Interaction, 位址: str, 連接埠: int = 19132) -> None:
        await self._execute_bedrock_query(interaction, 位址, 連接埠)

    @mc_group.command(name="延遲檢測", description="測量目標 Minecraft 伺服器之網路連線 Ping 延遲")
    @app_commands.describe(位址="伺服器位址", 連接埠="連接埠 (Java 預設 25565，基岩預設 19132)", 版本類型="Java版 或 基岩版")
    @command_guard("minecraft")
    async def ping_command(
        self,
        interaction: discord.Interaction,
        位址: str,
        連接埠: Optional[int] = None,
        版本類型: Literal["Java版", "基岩版"] = "Java版",
    ) -> None:
        port = 連接埠 if 連接埠 is not None else (19132 if 版本類型 == "基岩版" else 25565)
        位址 = 位址.strip()
        if not 位址:
            await InteractionResponder.safe_send(interaction, "💡 請輸入欲檢測延遲的 Minecraft 伺服器位址或 IP。", ephemeral=True)
            return

        if len(位址) > 255:
            await InteractionResponder.safe_send(interaction, "📝 伺服器位址長度超出上限，請確認輸入內容。", ephemeral=True)
            return

        if not (1 <= port <= 65535):
            await InteractionResponder.safe_send(interaction, "🔢 連接埠必須介於 1 至 65535 之間。", ephemeral=True)
            return

        if not await InteractionResponder.safe_defer(interaction):
            return

        try:
            if 版本類型 == "Java版":
                res = await mc_query.query_java_server(位址, port)
            else:
                res = await mc_query.query_bedrock_server(位址, port)

            ping = res["latency_ms"]
            quality = "極佳 (Optimal)" if ping < 50 else ("良好 (Good)" if ping < 120 else "偏高 (High)")
            pill = ZNStatusPill.SUCCESS if ping < 120 else ZNStatusPill.WARNING
            color = ZNColor.SUCCESS if ping < 120 else ZNColor.WARNING

            card = ZNCard(
                title=f"{位址}:{port} — 連線延遲檢測",
                description=f"- **往返延遲 (RTT)**：`{ping} ms`\n- **連線品質**：`{quality}`\n- **探測目標**：`{res['host']}:{res['port']}` ({res['edition']})",
                status_pill=pill,
                color=color,
            )
            await InteractionResponder.safe_send(interaction, card=card)
        except Exception as e:
            title_suffix, explanation = classify_minecraft_error(e)
            card = ZNCard(
                title=f"{位址}:{port} — {title_suffix}",
                description=explanation,
                status_pill=ZNStatusPill.WARNING,
                color=ZNColor.WARNING,
            )
            await InteractionResponder.safe_send(interaction, card=card)

    @mc_group.command(name="玩家皮膚", description="查詢正版玩家 3D 皮膚渲染圖與皮膚貼圖下載連結")
    @app_commands.describe(玩家名稱或uuid="正版玩家名稱 (如 Notch) 或 32/36 位 UUID")
    @command_guard("minecraft")
    async def skin_command(self, interaction: discord.Interaction, 玩家名稱或uuid: str) -> None:
        target = 玩家名稱或uuid.strip()
        if not target:
            await InteractionResponder.safe_send(interaction, "💡 請輸入正版 Minecraft 玩家名稱（例如 `Notch`）或 32/36 碼 UUID。", ephemeral=True)
            return

        if len(target) > 36:
            await InteractionResponder.safe_send(interaction, "📝 輸入長度超出規範（玩家名稱上限 16 字元，UUID 上限 36 字元）。", ephemeral=True)
            return

        if not await InteractionResponder.safe_defer(interaction):
            return

        try:
            info = await mc_query.get_player_info(target)
            card = ZNCard(
                title=f"玩家皮膚 — {info['name']}",
                description=f"**玩家正版 ID**：`{info['name']}`\n**UUID**：`{info['formatted_uuid']}`\n\n📥 [點此下載原始皮膚貼圖]({info['skin_download_url']})",
                status_pill=ZNStatusPill.MINECRAFT,
                color=ZNColor.MINECRAFT,
                image_url=info["skin_3d_url"],
                thumbnail_url=info["avatar_url"],
            )
            await InteractionResponder.safe_send(interaction, card=card)
        except Exception as e:
            title_suffix, explanation = classify_player_error(e, target)
            card = ZNCard(
                title=f"玩家皮膚 — {title_suffix}",
                description=explanation,
                status_pill=ZNStatusPill.WARNING,
                color=ZNColor.WARNING,
            )
            await InteractionResponder.safe_send(interaction, card=card)

    @mc_group.command(name="玩家頭像", description="獲取正版玩家高畫質 2D 頭像")
    @app_commands.describe(玩家名稱或uuid="正版玩家名稱或 UUID")
    @command_guard("minecraft")
    async def avatar_command(self, interaction: discord.Interaction, 玩家名稱或uuid: str) -> None:
        target = 玩家名稱或uuid.strip()
        if not target:
            await InteractionResponder.safe_send(interaction, "💡 請輸入正版 Minecraft 玩家名稱或 UUID。", ephemeral=True)
            return

        if len(target) > 36:
            await InteractionResponder.safe_send(interaction, "📝 輸入內容長度超出規範（上限 36 字元）。", ephemeral=True)
            return

        if not await InteractionResponder.safe_defer(interaction):
            return

        try:
            info = await mc_query.get_player_info(target)
            card = ZNCard(
                title=f"玩家頭像 — {info['name']}",
                description=f"- **正版名稱**：`{info['name']}`\n- **UUID**：`{info['formatted_uuid']}`",
                status_pill=ZNStatusPill.MINECRAFT,
                color=ZNColor.MINECRAFT,
                image_url=info["avatar_url"],
            )
            await InteractionResponder.safe_send(interaction, card=card)
        except Exception as e:
            title_suffix, explanation = classify_player_error(e, target)
            card = ZNCard(
                title=f"玩家頭像 — {title_suffix}",
                description=explanation,
                status_pill=ZNStatusPill.WARNING,
                color=ZNColor.WARNING,
            )
            await InteractionResponder.safe_send(interaction, card=card)

    @mc_group.command(name="玩家uuid", description="查詢正版玩家之 Mojang 唯一 UUID (支援雙向解析)")
    @app_commands.describe(玩家名稱或uuid="玩家名稱或 32/36 位 UUID")
    @command_guard("minecraft")
    async def uuid_command(self, interaction: discord.Interaction, 玩家名稱或uuid: str) -> None:
        target = 玩家名稱或uuid.strip()
        if not target:
            await InteractionResponder.safe_send(interaction, "💡 請輸入欲查詢的玩家名稱或 UUID。", ephemeral=True)
            return

        if len(target) > 36:
            await InteractionResponder.safe_send(interaction, "📝 輸入長度超出規範（UUID 最長為 36 字元）。", ephemeral=True)
            return

        if not await InteractionResponder.safe_defer(interaction):
            return

        try:
            info = await mc_query.get_player_info(target)
            card = ZNCard(
                title=f"Mojang 玩家識別 — {info['name']}",
                description=(
                    f"**正版使用者名稱**：`{info['name']}`\n\n"
                    f"- **標準 UUID (連字號)**：\n`{info['formatted_uuid']}`\n"
                    f"- **純 Hex UUID (32位元)**：\n`{info['raw_uuid']}`"
                ),
                status_pill=ZNStatusPill.MINECRAFT,
                color=ZNColor.INFO,
                thumbnail_url=info["avatar_url"],
            )
            await InteractionResponder.safe_send(interaction, card=card)
        except Exception as e:
            title_suffix, explanation = classify_player_error(e, target)
            card = ZNCard(
                title=f"Mojang 玩家識別 — {title_suffix}",
                description=explanation,
                status_pill=ZNStatusPill.WARNING,
                color=ZNColor.WARNING,
            )
            await InteractionResponder.safe_send(interaction, card=card)

    @mc_group.command(name="歷史名稱", description="查詢正版帳號歷史更名紀錄 (由 PlayerDB 存檔資料庫提供)")
    @app_commands.describe(玩家名稱或uuid="當前玩家名稱或 UUID")
    @command_guard("minecraft")
    async def history_command(self, interaction: discord.Interaction, 玩家名稱或uuid: str) -> None:
        target = 玩家名稱或uuid.strip()
        if not target:
            await InteractionResponder.safe_send(interaction, "💡 請輸入欲查詢歷史更名紀錄的玩家名稱或 UUID。", ephemeral=True)
            return

        if len(target) > 36:
            await InteractionResponder.safe_send(interaction, "📝 玩家名稱或 UUID 長度超出上限（上限 36 字元）。", ephemeral=True)
            return

        if not await InteractionResponder.safe_defer(interaction):
            return

        try:
            res = await mc_query.get_player_history(target)
            info = res["player"]
            hist_list = res.get("history", [])

            if hist_list:
                lines = []
                for idx, h in enumerate(hist_list):
                    t_str = ""
                    if h.get("changed_at"):
                        try:
                            ts = int(h["changed_at"]) / 1000.0
                            t_str = f" (更名於: <t:{int(ts)}:f>)"
                        except Exception:
                            pass
                    lines.append(f"{idx+1}. **`{h['name']}`**{t_str}")
                desc = f"玩家 **`{info['name']}`** (UUID: `{info['formatted_uuid'][:8]}...`) 歷史紀錄：\n\n" + "\n".join(lines)
            else:
                desc = (
                    f"目標正版玩家 **`{info['name']}`** (UUID: `{info['formatted_uuid'][:8]}...`)\n\n"
                    f"該帳號目前未記錄有曾變更名稱之歷史（為原始註冊名稱或未公開更名存檔）。"
                )

            card = ZNCard(
                title=f"名稱歷史紀錄 — {info['name']}",
                description=desc,
                status_pill=ZNStatusPill.MINECRAFT,
                color=ZNColor.INFO,
                thumbnail_url=info["avatar_url"],
            )
            await InteractionResponder.safe_send(interaction, card=card)
        except Exception as e:
            title_suffix, explanation = classify_player_error(e, target)
            card = ZNCard(
                title=f"名稱歷史紀錄 — {title_suffix}",
                description=explanation,
                status_pill=ZNStatusPill.WARNING,
                color=ZNColor.WARNING,
            )
            await InteractionResponder.safe_send(interaction, card=card)

    @mc_group.command(name="伺服器圖示", description="提取並下載伺服器 Favicon 圖示原圖")
    @app_commands.describe(位址="伺服器位址", 連接埠="連接埠 (預設 25565)")
    @command_guard("minecraft")
    async def mc_icon_command(self, interaction: discord.Interaction, 位址: str, 連接埠: int = 25565) -> None:
        位址 = 位址.strip()
        if not 位址:
            await InteractionResponder.safe_send(interaction, "💡 請輸入欲提取圖示的伺服器位址。", ephemeral=True)
            return

        if len(位址) > 255:
            await InteractionResponder.safe_send(interaction, "📝 伺服器位址長度超出上限。", ephemeral=True)
            return

        if not (1 <= 連接埠 <= 65535):
            await InteractionResponder.safe_send(interaction, "🔢 連接埠必須介於 1 至 65535 之間。", ephemeral=True)
            return

        if not await InteractionResponder.safe_defer(interaction):
            return

        try:
            res = await mc_query.query_java_server(位址, 連接埠)
            icon_data = res.get("icon")
            if not icon_data or not isinstance(icon_data, str) or not icon_data.startswith("data:image"):
                card = ZNCard(
                    title=f"{位址}:{連接埠} — 伺服器未設定自訂圖示",
                    description=(
                        "目標伺服器目前連線正常，但伺服器端並未放置自訂的 `server-icon.png` (64x64 圖標)。\n\n"
                        "💡 **小秘訣**：伺服器管理員可將 64x64 解析度的 PNG 圖檔命名為 `server-icon.png` 並置於伺服器根目錄重啟即可！"
                    ),
                    status_pill=ZNStatusPill.INFO,
                    color=ZNColor.INFO,
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
                description="已成功提取伺服器自訂圖標 (64x64 PNG 原圖)：",
                status_pill=ZNStatusPill.MINECRAFT,
                color=ZNColor.MINECRAFT,
            )
            embed = card.to_embed()
            embed.set_image(url="attachment://server_icon.png")
            await InteractionResponder.safe_send(interaction, file=file, embed=embed)
        except Exception as e:
            title_suffix, explanation = classify_minecraft_error(e)
            card = ZNCard(title=f"取得圖示失敗 ({title_suffix})", description=explanation, status_pill=ZNStatusPill.WARNING, color=ZNColor.WARNING)
            await InteractionResponder.safe_send(interaction, card=card)

    @mc_group.command(name="motd檢視", description="檢視伺服器宣傳標語 MOTD 並解析色彩代碼")
    @app_commands.describe(位址="伺服器位址", 連接埠="連接埠 (Java 預設 25565，基岩預設 19132)", 版本類型="Java版 或 基岩版")
    @command_guard("minecraft")
    async def motd_command(
        self,
        interaction: discord.Interaction,
        位址: str,
        連接埠: Optional[int] = None,
        版本類型: Literal["Java版", "基岩版"] = "Java版",
    ) -> None:
        port = 連接埠 if 連接埠 is not None else (19132 if 版本類型 == "基岩版" else 25565)
        位址 = 位址.strip()
        if not 位址:
            await InteractionResponder.safe_send(interaction, "💡 請輸入欲檢視 MOTD 的伺服器位址。", ephemeral=True)
            return

        if len(位址) > 255:
            await InteractionResponder.safe_send(interaction, "📝 伺服器位址長度超出上限。", ephemeral=True)
            return

        if not (1 <= port <= 65535):
            await InteractionResponder.safe_send(interaction, "🔢 連接埠必須介於 1 至 65535 之間。", ephemeral=True)
            return

        if not await InteractionResponder.safe_defer(interaction):
            return

        try:
            if 版本類型 == "Java版":
                res = await mc_query.query_java_server(位址, port)
            else:
                res = await mc_query.query_bedrock_server(位址, port)

            card = ZNCard(
                title=f"{位址}:{port} — 伺服器 MOTD ({res['edition']})",
                description=f"```fix\n{res['motd']}\n```",
                status_pill=ZNStatusPill.MINECRAFT,
                color=ZNColor.MINECRAFT,
            )
            card.add_section("📦 遊戲版本", f"`{res['version']}`", inline=True)
            card.add_section("👥 在線人數", f"`{res['players_online']} / {res['players_max']}`", inline=True)
            await InteractionResponder.safe_send(interaction, card=card)
        except Exception as e:
            title_suffix, explanation = classify_minecraft_error(e)
            card = ZNCard(title=f"MOTD 檢視失敗 ({title_suffix})", description=explanation, status_pill=ZNStatusPill.WARNING, color=ZNColor.WARNING)
            await InteractionResponder.safe_send(interaction, card=card)

    @mc_group.command(name="監控設定", description="設定 Minecraft 伺服器之定時可用度巡檢清單")
    @app_commands.describe(
        操作="選擇加入監控、移除監控 或 清空清單",
        位址="伺服器位址 (清空清單時可不填)",
        連接埠="連接埠 (Java 預設 25565，基岩預設 19132)",
        版本類型="指定為 Java版 或 基岩版"
    )
    @command_guard("minecraft", required_level=ZNPermissionLevel.ADMINISTRATOR)
    async def monitor_command(
        self,
        interaction: discord.Interaction,
        操作: Literal["加入監控", "移除監控", "清空清單"] = "加入監控",
        位址: Optional[str] = None,
        連接埠: Optional[int] = None,
        版本類型: Literal["Java版", "基岩版"] = "Java版",
    ) -> None:
        from zeronexus.modules.manager import module_manager
        mod = module_manager.get_module("minecraft")
        if not isinstance(mod, MinecraftModule):
            mod = None

        if 操作 == "清空清單":
            if mod:
                mod.monitored_servers.clear()
            card = ZNCard(
                title="巡檢監控清單已全數清空",
                description="已為您清除伺服器定時健康巡檢清單中的所有項目，目前暫無排程中的巡檢工作。",
                status_pill=ZNStatusPill.SUCCESS,
                color=ZNColor.SUCCESS,
            )
            await InteractionResponder.safe_send(interaction, card=card)
            return

        if not 位址 or not 位址.strip():
            await InteractionResponder.safe_send(interaction, "💡 請提供欲加入或移除巡檢的伺服器位址（例如 `mc.example.com`）。", ephemeral=True)
            return

        clean_host = 位址.strip()
        port = 連接埠 if 連接埠 is not None else (19132 if 版本類型 == "基岩版" else 25565)
        if not (1 <= port <= 65535):
            await InteractionResponder.safe_send(interaction, "🔢 連接埠必須介於 1 至 65535 之間。", ephemeral=True)
            return

        key = f"{clean_host}:{port}"

        if 操作 == "移除監控":
            if mod and key in mod.monitored_servers:
                del mod.monitored_servers[key]
                card = ZNCard(
                    title="已成功移除巡檢項目",
                    description=f"伺服器 **`{key}`** 已從健康巡檢排程中移除，今後將停止定期探測。",
                    status_pill=ZNStatusPill.SUCCESS,
                    color=ZNColor.SUCCESS,
                )
            else:
                card = ZNCard(
                    title="未找到該伺服器項目",
                    description=(
                        f"在現有的監控清單中未找到 **`{key}`**。\n\n"
                        "💡 **您可以嘗試**：使用 `/工具 mc健康巡檢` 檢視目前已在監控中的伺服器清單與連接埠。"
                    ),
                    status_pill=ZNStatusPill.INFO,
                    color=ZNColor.WARNING,
                )
            await InteractionResponder.safe_send(interaction, card=card)
            return

        # 加入監控
        if mod is not None:
            mod.monitored_servers[key] = {
                "host": clean_host,
                "port": port,
                "edition": 版本類型,
                "added_at": time.time(),
                "added_by": interaction.user.display_name,
                "active": True,
            }

        card = ZNCard(
            title="Minecraft 伺服器已加入健康巡檢",
            description=(
                f"已成功將 **`{key}`** ({版本類型}) 納入 ZeroNexus 健康巡檢清單中！\n\n"
                "📊 隨時可使用 `/工具 mc健康巡檢` 檢視所有登記節點的可用率與即時延遲大盤。"
            ),
            status_pill=ZNStatusPill.SUCCESS,
            color=ZNColor.SUCCESS,
        )
        await InteractionResponder.safe_send(interaction, card=card)

    @mc_group.command(name="監控狀態", description="即時探測並檢視目前已登記伺服器之可用度大盤")
    @command_guard("minecraft")
    async def monitor_status_command(self, interaction: discord.Interaction) -> None:
        from zeronexus.modules.manager import module_manager
        mod = module_manager.get_module("minecraft")
        servers = dict(mod.monitored_servers) if isinstance(mod, MinecraftModule) else {}

        if not servers:
            card = ZNCard(
                title="目前尚無登記巡檢的伺服器",
                description=(
                    "ZeroNexus 的 Minecraft 巡檢清單中目前空空如也。\n\n"
                    "💡 **如何新增**：\n"
                    "伺服器管理員可使用 `/工具 mc健康巡檢 操作:加入監控` 輸入伺服器 IP 與 Port，即可即時建立監控！"
                ),
                status_pill=ZNStatusPill.INFO,
                color=ZNColor.INFO,
            )
            await InteractionResponder.safe_send(interaction, card=card)
            return

        if not await InteractionResponder.safe_defer(interaction):
            return

        # Probe all monitored servers in parallel
        async def _probe_one(k: str, sdata: Dict[str, Any]) -> Dict[str, Any]:
            host = sdata.get("host", k.split(":")[0])
            port = sdata.get("port", 25565)
            edition = sdata.get("edition", "Java版")
            t0 = time.perf_counter()
            try:
                if edition == "基岩版":
                    res = await mc_query.query_bedrock_server(host, port)
                else:
                    res = await mc_query.query_java_server(host, port)
                latency = round((time.perf_counter() - t0) * 1000, 1)
                return {
                    "key": k,
                    "online": True,
                    "latency": latency,
                    "players": f"{res['players_online']}/{res['players_max']}",
                    "version": res.get("version", ""),
                    "edition": edition,
                }
            except Exception as e:
                title_suffix, _ = classify_minecraft_error(e)
                return {
                    "key": k,
                    "online": False,
                    "error": title_suffix,
                    "edition": edition,
                }

        results = await asyncio.gather(*[_probe_one(k, v) for k, v in servers.items()])

        lines: List[str] = []
        online_count = 0
        for r in results:
            if r["online"]:
                online_count += 1
                lines.append(f"- 🟢 **`{r['key']}`** ({r['edition']}) — 在線 `{r['latency']} ms` | 玩家 `{r['players']}`")
            else:
                lines.append(f"- 🔴 **`{r['key']}`** ({r['edition']}) — 離線 (`{r.get('error', '連線失敗')}`)")

        uptime_pct = round((online_count / len(results)) * 100, 1) if results else 100.0
        pill = ZNStatusPill.SUCCESS if uptime_pct == 100.0 else (ZNStatusPill.WARNING if uptime_pct > 0 else ZNStatusPill.ERROR)
        col = ZNColor.SUCCESS if uptime_pct == 100.0 else (ZNColor.WARNING if uptime_pct > 0 else ZNColor.ERROR)

        card = ZNCard(
            title=f"Minecraft 伺服器健康巡檢大盤 (可用率: {uptime_pct}%)",
            description=f"已即時探測全數 {len(results)} 座已登記節點：\n\n" + "\n".join(lines),
            status_pill=pill,
            color=col,
        )
        card.add_section("📊 妥善率統計", f"🟢 在線：`{online_count}` 座 | 🔴 離線：`{len(results)-online_count}` 座", inline=False)
        await InteractionResponder.safe_send(interaction, card=card)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(MinecraftCog(bot))
