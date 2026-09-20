"""ZeroNexus Composite Card & Response Presentation System.

Renders authentic Discord Components V2 messages with unified typography,
timezone-aware standard footers, and modular action components.
"""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple, Union

import discord

from zeronexus.ui.theme import ZNColor, ZNStatusPill, ZNTheme


def strip_markdown_headings(text: str) -> str:
    """Removes leading Markdown heading markers (#, ##, ###, ####) and trims whitespace."""
    if not text:
        return ""
    clean = re.sub(r"^#{1,6}\s*", "", text.strip())
    return clean.strip()


def extract_markdown_headings(text: str, default_title: str = "✨ 智慧回覆") -> Tuple[str, Optional[str], str]:
    """Intelligently detects top Markdown headings (#, ##, ###) from AI generated text.
    
    Returns:
        (title, subtitle, clean_body)
    - If a top-level heading (# or ## or ###) is present, extracts it as title and removes it from the body.
    - If followed immediately by a sub-heading (## or ### or ####), extracts it as subtitle and removes it.
    - Preserves all inner Markdown formatting (code blocks, lists, bold, links, tables) in clean_body.
    """
    if not text:
        return default_title, None, ""

    lines = text.split("\n")
    idx = 0
    while idx < len(lines) and not lines[idx].strip():
        idx += 1

    if idx >= len(lines):
        return default_title, None, ""

    title = default_title
    subtitle: Optional[str] = None
    consumed = 0

    first_line = lines[idx].strip()
    m_top = re.match(r"^(#{1,3})\s+(.+)$", first_line)
    if m_top:
        title = strip_markdown_headings(m_top.group(2))
        consumed = idx + 1

        # Check for immediate subtitle line
        sub_idx = consumed
        while sub_idx < len(lines) and not lines[sub_idx].strip():
            sub_idx += 1
        if sub_idx < len(lines):
            second_line = lines[sub_idx].strip()
            m_sub = re.match(r"^(#{2,4})\s+(.+)$", second_line)
            if m_sub:
                subtitle = strip_markdown_headings(m_sub.group(2))
                consumed = sub_idx + 1

    clean_body = "\n".join(lines[consumed:]).lstrip("\n")
    return title, subtitle, clean_body


def chunk_text_for_components(text: str, max_chunk_size: int = 3800) -> List[str]:
    """Splits long text into chunks safe for Discord Components V2 TextDisplay items.
    
    Respects paragraph boundaries and code blocks so syntax is never mangled.
    """
    if not text:
        return []
    if len(text) <= max_chunk_size:
        return [text]

    chunks: List[str] = []
    current_chunk: List[str] = []
    current_len = 0
    in_code_block = False

    paragraphs = text.split("\n")
    for line in paragraphs:
        if line.strip().startswith("```"):
            in_code_block = not in_code_block

        line_len = len(line) + 1  # newline
        if current_len + line_len > max_chunk_size and current_chunk:
            # If we're cutting inside a code block, close it cleanly in current and reopen in next
            if in_code_block:
                current_chunk.append("```")
                chunks.append("\n".join(current_chunk))
                current_chunk = ["```", line]
                current_len = 4 + line_len
            else:
                chunks.append("\n".join(current_chunk))
                current_chunk = [line]
                current_len = line_len
        else:
            current_chunk.append(line)
            current_len += line_len

    if current_chunk:
        chunks.append("\n".join(current_chunk))

    return chunks


class ZNLayoutView(discord.ui.LayoutView):
    """Native Discord Components V2 LayoutView container with lifecycle tracking and locks."""

    def __init__(self, *, timeout: Optional[float] = 180.0) -> None:
        super().__init__(timeout=timeout)
        self.message: Optional[discord.Message] = None
        self._last_interaction: Optional[discord.Interaction] = None
        self._lock = asyncio.Lock()

    async def on_timeout(self) -> None:
        """Universal timeout disabling across all interactive items embedded in LayoutView."""
        for child in self.walk_children():
            if hasattr(child, "disabled"):
                child.disabled = True
        for child in self.children:
            if hasattr(child, "disabled"):
                child.disabled = True
        if self.message:
            try:
                await self.message.edit(view=self)
                return
            except Exception:
                pass
        if self._last_interaction:
            from zeronexus.ui.responder import InteractionResponder
            await InteractionResponder.safe_edit(self._last_interaction, view=self)


@dataclass
class ZNSection:
    """A distinct structural section within a ZN card."""
    name: str
    value: str
    inline: bool = False


@dataclass
class ZNCard:
    """Represents a visual ZeroNexus card payload, rendering to Discord Components V2."""
    title: str
    subtitle: Optional[str] = None
    description: Optional[str] = None
    status_pill: str = ZNStatusPill.SUCCESS
    color: discord.Color = ZNColor.PRIMARY
    sections: List[ZNSection] = field(default_factory=list)
    footer_text: Optional[str] = None
    footer_icon_url: Optional[str] = None
    thumbnail_url: Optional[str] = None
    image_url: Optional[str] = None
    timezone_name: Optional[str] = None

    def add_section(self, name: str, value: str, inline: bool = False) -> ZNCard:
        self.sections.append(ZNSection(name=name, value=value, inline=inline))
        return self

    def set_image(self, image_url: Optional[str]) -> ZNCard:
        self.image_url = image_url
        return self

    def set_thumbnail(self, thumbnail_url: Optional[str]) -> ZNCard:
        self.thumbnail_url = thumbnail_url
        return self

    def to_layout_view(
        self,
        extra_view: Optional[Union[discord.ui.View, discord.ui.LayoutView]] = None,
        timeout: Optional[float] = 180.0,
    ) -> ZNLayoutView:
        """Renders this card as an authentic Discord Components V2 LayoutView.
        
        Structure:
        LayoutView -> Container (accent_color) -> [
            TextDisplay (Title / Subtitle),
            Separator,
            Thumbnail (optional),
            TextDisplay (Body chunks),
            Sections (TextDisplay + subtle dividers),
            MediaGallery (optional),
            Separator,
            TextDisplay (Footer: -# ...),
            ActionRow (Buttons / Selects from extra_view)
        ]
        """
        layout_view = ZNLayoutView(timeout=timeout)
        layout_view.card = self
        layout_view.extra_view = extra_view
        container = discord.ui.Container(accent_color=self.color)

        # 1. Header: Title and Subtitle (with Thumbnail if present as Section accessory)
        pill_str = getattr(self.status_pill, "value", str(self.status_pill)) if self.status_pill else ""
        clean_title = strip_markdown_headings(self.title)
        
        header_text = f"### {pill_str} {clean_title}".strip() if pill_str else f"### {clean_title}"

        if self.thumbnail_url:
            section_items: List[Union[str, discord.ui.Item]] = [discord.ui.TextDisplay(header_text)]
            if self.subtitle:
                clean_sub = strip_markdown_headings(self.subtitle)
                if clean_sub:
                    section_items.append(discord.ui.TextDisplay(f"*{clean_sub}*"))
            container.add_item(
                discord.ui.Section(
                    *section_items,
                    accessory=discord.ui.Thumbnail(self.thumbnail_url),
                )
            )
        else:
            container.add_item(discord.ui.TextDisplay(header_text))
            if self.subtitle:
                clean_sub = strip_markdown_headings(self.subtitle)
                if clean_sub:
                    container.add_item(discord.ui.TextDisplay(f"*{clean_sub}*"))

        # Separator after header
        container.add_item(discord.ui.Separator(visible=True, spacing=discord.SeparatorSpacing.small))

        # 2. Description / Body (Thumbnail placed in Section accessory above to satisfy Discord V2 schema)
        if self.description:
            chunks = chunk_text_for_components(self.description)
            for chunk in chunks:
                if chunk.strip():
                    container.add_item(discord.ui.TextDisplay(chunk))

        # 4. Sections
        for sec in self.sections:
            if sec.name and sec.value:
                container.add_item(discord.ui.Separator(visible=False, spacing=discord.SeparatorSpacing.small))
                container.add_item(discord.ui.TextDisplay(f"**{sec.name}**\n{sec.value}"))

        # 5. Media Gallery (Images)
        if self.image_url:
            container.add_item(discord.ui.MediaGallery(discord.MediaGalleryItem(self.image_url)))

        # 6. Standard Footer
        footer = self.footer_text or ZNTheme.standard_footer(tz_name=self.timezone_name)
        if footer:
            container.add_item(discord.ui.Separator(visible=True, spacing=discord.SeparatorSpacing.small))
            container.add_item(discord.ui.TextDisplay(f"-# {footer}"))

        # 7. Attach Interactive Elements (from extra_view or attached buttons)
        if extra_view is not None:
            from collections import defaultdict
            rows_dict = defaultdict(list)
            for item in getattr(extra_view, "children", []):
                if isinstance(item, (discord.ui.Button, discord.ui.Select)):
                    row_idx = getattr(item, "row", 0) or 0
                    rows_dict[row_idx].append(item)

            if rows_dict:
                for r_idx in sorted(rows_dict.keys()):
                    items = rows_dict[r_idx]
                    for i in range(0, len(items), 5):
                        container.add_item(discord.ui.ActionRow(*items[i:i+5]))

        layout_view.add_item(container)
        return layout_view

    def to_embed(self) -> discord.Embed:
        """Legacy Discord Embed renderer maintained strictly for backward-compatible fallback."""
        pill_str = getattr(self.status_pill, "value", str(self.status_pill)) if self.status_pill else ""
        clean_title = strip_markdown_headings(self.title)
        display_title = f"{pill_str} {clean_title}".strip() if pill_str else clean_title
        embed = discord.Embed(
            title=display_title,
            description=self.description,
            color=self.color,
        )

        for sec in self.sections:
            if sec.name and sec.value:
                embed.add_field(name=sec.name, value=sec.value, inline=sec.inline)

        footer = self.footer_text or ZNTheme.standard_footer(tz_name=self.timezone_name)
        embed.set_footer(text=footer, icon_url=self.footer_icon_url)

        if self.thumbnail_url:
            embed.set_thumbnail(url=self.thumbnail_url)
        if self.image_url:
            embed.set_image(url=self.image_url)

        return embed

    @classmethod
    def thinking(cls, description: str = "ZeroNexus 正在為您深入分析並組織精確回答，請稍候片刻…") -> ZNCard:
        """Standard Components V2 loading/thinking state card."""
        return cls(
            title="正在細心思考…",
            description=description,
            status_pill=ZNStatusPill.THINKING,
            color=ZNColor.AI,
        )

    @classmethod
    def from_embed(cls, embed: discord.Embed) -> ZNCard:
        """Constructs an authentic ZNCard from a legacy discord.Embed to enable universal Components V2 rendering."""
        if not embed:
            return cls(title="系統訊息")

        title = embed.title or "系統訊息"
        desc = embed.description or ""
        color = embed.color or ZNColor.PRIMARY

        card = cls(
            title=title,
            description=desc,
            color=color,
            status_pill=ZNStatusPill.SUCCESS,
        )
        if embed.thumbnail and embed.thumbnail.url:
            card.thumbnail_url = embed.thumbnail.url
        if embed.image and embed.image.url:
            card.image_url = embed.image.url
        if embed.footer and embed.footer.text:
            card.footer_text = embed.footer.text

        for f in getattr(embed, "fields", []):
            card.add_section(f.name, f.value, inline=getattr(f, "inline", False))

        return card


class ZNResponse:
    """High-level response wrapper for Discord Components V2 message lifecycle."""

    def __init__(
        self,
        card: Optional[ZNCard] = None,
        content: Optional[str] = None,
        view: Optional[Union[discord.ui.View, discord.ui.LayoutView]] = None,
        ephemeral: bool = False,
    ) -> None:
        self.card = card
        self.content = content
        self.view = view
        self.ephemeral = ephemeral

    def to_send_kwargs(self) -> Dict[str, Any]:
        """Converts into standard kwargs for interaction.response.send_message / followup.send / channel.send.
        
        Guarantees that Components V2 LayoutView is provided without legacy Embeds.
        """
        if self.card:
            layout_view = self.card.to_layout_view(extra_view=self.view)
            return {"view": layout_view, "ephemeral": self.ephemeral}
        elif self.view:
            return {"view": self.view, "content": self.content, "ephemeral": self.ephemeral}
        return {"content": self.content or "", "ephemeral": self.ephemeral}

    def to_edit_kwargs(self) -> Dict[str, Any]:
        """Converts into standard kwargs for safe_edit / edit_message / edit_original_response.
        
        Explicitly nullifies embed and embeds to guarantee clean Discord Components V2 rendering.
        If content was explicitly set on ZNResponse, preserves it; otherwise clears it with None.
        """
        if self.card:
            layout_view = self.card.to_layout_view(extra_view=self.view)
            return {
                "view": layout_view,
                "content": self.content if self.content is not None else None,
                "embed": None,
                "embeds": [],
            }
        elif self.view:
            return {
                "view": self.view,
                "content": self.content,
                "embed": None,
                "embeds": [],
            }
        return {
            "content": self.content,
            "embed": None,
            "embeds": [],
        }


    # Preset Factory Methods
    @classmethod
    def success(
        cls,
        title: str,
        description: Optional[str] = None,
        view: Optional[Union[discord.ui.View, discord.ui.LayoutView]] = None,
        ephemeral: bool = False,
    ) -> ZNResponse:
        card = ZNCard(
            title=title,
            description=description,
            status_pill=ZNStatusPill.SUCCESS,
            color=ZNColor.SUCCESS,
        )
        return cls(card=card, view=view, ephemeral=ephemeral)

    @classmethod
    def error(
        cls,
        title: str = "處理時遇到了一點小狀況",
        description: Optional[str] = None,
        view: Optional[Union[discord.ui.View, discord.ui.LayoutView]] = None,
        ephemeral: bool = True,
    ) -> ZNResponse:
        desc = description or (
            "處理您的請求時遇到了一些阻礙，請別擔心，您的資料安全完好。\n\n"
            "💡 **您可以嘗試**：稍候數秒再次發送請求，或檢查輸入格式是否完整。"
        )
        card = ZNCard(
            title=title,
            description=desc,
            status_pill=ZNStatusPill.ERROR,
            color=ZNColor.ERROR,
        )
        return cls(card=card, view=view, ephemeral=ephemeral)

    @classmethod
    def warning(
        cls,
        title: str,
        description: Optional[str] = None,
        view: Optional[Union[discord.ui.View, discord.ui.LayoutView]] = None,
        ephemeral: bool = False,
    ) -> ZNResponse:
        card = ZNCard(
            title=title,
            description=description,
            status_pill=ZNStatusPill.WARNING,
            color=ZNColor.WARNING,
        )
        return cls(card=card, view=view, ephemeral=ephemeral)

    @classmethod
    def info(
        cls,
        title: str,
        description: Optional[str] = None,
        view: Optional[Union[discord.ui.View, discord.ui.LayoutView]] = None,
        ephemeral: bool = False,
    ) -> ZNResponse:
        card = ZNCard(
            title=title,
            description=description,
            status_pill=ZNStatusPill.INFO,
            color=ZNColor.INFO,
        )
        return cls(card=card, view=view, ephemeral=ephemeral)

    @classmethod
    def ai(
        cls,
        answer: str,
        model_name: str,
        fallback_notice: Optional[str] = None,
        persona_name: Optional[str] = None,
        author_name: Optional[str] = None,
        thumbnail_url: Optional[str] = None,
        image_url: Optional[str] = None,
        image_model: Optional[str] = None,
        footer_override: Optional[str] = None,
        thinking_process: Optional[str] = None,
    ) -> ZNResponse:
        """Constructs an authentic Discord Components V2 AI response.
        
        Key Enhancements:
        1. Intelligently extracts Markdown headings (#, ##, ###) into structured title and subtitle.
        2. Eliminates raw Markdown heading markers (#, ###) from visible titles.
        3. Completely removes internal persona identifiers like '(01_cat)' from user-facing titles.
        4. Accurately formats runtime footer with actual serving model name.
        5. When image is generated, accurately attributes the footer to the image generation model.
        6. Integrates transparent thinking/reasoning quotes directly into body.
        """
        from zeronexus.ai_gateway.model_registry import model_registry
        if footer_override:
            clean_footer = footer_override
        elif image_model:
            im_low = image_model.lower()
            if "gemini-2.5-flash-image" in im_low:
                clean_name = "Google Gemini 2.5 Flash Image"
            elif "pollinations" in im_low:
                clean_name = "Pollinations.ai (Flux/SDXL)"
            else:
                clean_name = image_model.replace("google/", "").replace(":free", "")
            clean_footer = f"🎨 圖像生成引擎：{clean_name}"
        else:
            clean_footer = model_registry.format_footer(model_name)

        if fallback_notice:
            clean_footer = f"{clean_footer}\n↳ {fallback_notice}"
        full_footer = clean_footer

        author_suffix = f" ➔ {author_name}" if author_name else ""
        default_title = f"✨ 智慧回覆{author_suffix}"

        # Extract leading headings from AI response
        parsed_title, subtitle, clean_body = extract_markdown_headings(answer, default_title=default_title)
        
        # If a custom heading was extracted, append author suffix cleanly if not present
        if parsed_title != default_title and author_name and author_name not in parsed_title:
            final_title = f"{parsed_title}{author_suffix}"
        else:
            final_title = parsed_title

        body_display = clean_body
        if thinking_process and thinking_process.strip():
            th_clean = thinking_process.strip()
            # 判斷是否為純工具執行脈絡
            if "## ⚙️ 工具調用" in th_clean and "## 💭 AI 思維推演" not in th_clean:
                if "python_code_sandbox" in th_clean or "安全程式碼沙盒" in th_clean:
                    summary_text = "已在安全沙盒中執行 Python 程式碼完成計算"
                elif "weather_probe" in th_clean or "氣象署" in th_clean:
                    summary_text = "已檢索中央氣象署即時觀測數據"
                elif "cpc_fuel_prices" in th_clean or "中油" in th_clean:
                    summary_text = "已檢索中油即時油價與預估走勢"
                elif "stock_quote" in th_clean or "股市" in th_clean:
                    summary_text = "已檢索股市即時行情與報價"
                elif "web_search" in th_clean or "網路搜尋" in th_clean:
                    summary_text = "已完成即時網路檢索與資訊彙整"
                elif "inspect_channel_messages" in th_clean or "頻道歷史" in th_clean:
                    summary_text = "已讀取並統整目標時段之頻道聊天記錄"
                elif "analyze_channel_activity" in th_clean or "發言活躍度" in th_clean:
                    summary_text = "已完成頻道成員發言排行榜與活躍度統計"
                elif "inspect_channel_overview" in th_clean or "頻道全方位" in th_clean:
                    summary_text = "已檢索頻道配置參數與社群情資總覽"
                else:
                    summary_text = "已調用相關工具完成即時資料運算與檢索"
                thinking_quote = f"> ⚙️ **工具執行脈絡**：*{summary_text}*（點擊下方按鈕檢視完整程式碼與數據）\n\n"
            else:
                # 包含模型原生思維推演，過濾開頭 Markdown 標題符號
                meaningful_lines = [
                    line.strip() for line in th_clean.split("\n")
                    if line.strip() and not line.strip().startswith("#") and not line.strip().startswith("---")
                ]
                th_snippet = meaningful_lines[0][:120].strip() if meaningful_lines else "正在深度推演決策脈絡"
                # 消除大模型原生英文思維開場標題（例如 My Thoughts on...）
                if th_snippet.lower().startswith("my thoughts on"):
                    topic_part = th_snippet[14:].strip().rstrip(". ")
                    th_snippet = f"關於「{topic_part}」的心靈思維推演"
                elif re.match(r"^[A-Za-z\s,\.'\?!\-]+$", th_snippet):
                    th_snippet = "深度因果邏輯與同理認知推演中"

                thinking_quote = f"> 💭 **思維推演歷程**\n> *「{th_snippet}…」*（點擊下方按鈕檢視完整脈絡）\n\n"
            body_display = f"{thinking_quote}{clean_body}"

        # Dynamic model theme color & brand subtitle
        model_disp = model_registry.get_display_name(model_name)
        m_low = (model_name or "").lower()
        model_color = ZNColor.AI
        brand_prefix = "🤖"
        if "gemini" in m_low:
            model_color = ZNColor.PRIMARY
            brand_prefix = "💎 Google Gemini"
        elif "deepseek-reasoner" in m_low or "r1" in m_low:
            model_color = ZNColor.DARK
            brand_prefix = "🔬 DeepSeek-R1 深度推理"
        elif "v4-flash-vision" in m_low or "v4.1" in m_low or "v4-flash" in m_low or "v4" in m_low:
            model_color = ZNColor.AI
            brand_prefix = "👁️ DeepSeek-V4 視覺推理"
        elif "deepseek" in m_low:
            model_color = ZNColor.PRIMARY
            brand_prefix = "💬 DeepSeek 旗艦節點"
        elif "qwen" in m_low:
            model_color = ZNColor.WARNING
            brand_prefix = "🇨🇳 阿里通義千問"
        elif "grok" in m_low:
            model_color = ZNColor.WARNING
            brand_prefix = "⚡ xAI Grok"
        elif "gpt-4o" in m_low:
            model_color = ZNColor.SUCCESS
            brand_prefix = "🚀 OpenAI GPT-4o"

        final_subtitle = subtitle or f"{brand_prefix} ｜ {model_disp}"

        card = ZNCard(
            title=final_title,
            subtitle=final_subtitle,
            description=body_display,
            status_pill=ZNStatusPill.MODEL,
            color=model_color,
            footer_text=full_footer,
            thumbnail_url=thumbnail_url,
            image_url=image_url,
        )
        return cls(card=card)

