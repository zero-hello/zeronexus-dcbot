"""Zero Intelligence 動態能力投影器 (Dynamic Tool Projector).

核心精神：
絕對拒絕將 130+ (現有 160+) 個工具一股腦全塞進 Prompt！
依據使用者意圖與任務複雜度，動態投影最精確相關的 3~8 個工具 Schema 作為 Active Tool Set。
針對日常問候/常規閒聊 (SIMPLE)，動態投影 0 個工具，實現 0 Token 浪費與毫秒直出。
同時對外部語音與音訊播放組件建立硬性隔離保護，絕不允許 AI Agent 投影或干預音訊管線。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple

from zeronexus.agent.tools import ReadOnlyTool, agent_tools
from zeronexus.intelligence.complexity_router import ComplexityLevel, evaluate_complexity


@dataclass(frozen=True)
class ProjectedTool:
    """單一投影工具之元資料封裝。"""

    name: str
    category: str
    description: str
    relevance_score: float
    openai_schema: Dict[str, Any] = field(default_factory=dict)
    gemini_schema: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ActiveToolSet:
    """動態投影之活耀工具集合 (Active Tool Set)。"""

    tools: List[ProjectedTool]
    primary_domain: str
    complexity: ComplexityLevel
    user_prompt: str

    @property
    def total_projected(self) -> int:
        """取得當前投影工具總數。"""
        return len(self.tools)

    @property
    def tool_names(self) -> List[str]:
        """取得工具名稱清單。"""
        return [t.name for t in self.tools]

    def to_openai_tools(self) -> List[Dict[str, Any]]:
        """輸出標準 OpenAI Function Calling Schema 清單。"""
        return [t.openai_schema for t in self.tools if t.openai_schema]

    def to_gemini_tools(self) -> List[Dict[str, Any]]:
        """輸出標準 Gemini Function Calling Schema 清單。"""
        return [t.gemini_schema for t in self.tools if t.gemini_schema]

    def contains_tool(self, name: str) -> bool:
        """判斷特定工具是否在當前 Active Tool Set 中。"""
        return any(t.name == name for t in self.tools)


class DynamicToolProjector:
    """動態能力投影器核心控制器。"""

    # 絕對隔離名單：音訊通道控制相關字根（嚴格禁止投影至 Agent）
    ISOLATED_MUSIC_DENYLIST: Set[str] = {
        "play_music",
        "pause_music",
        "skip_music",
        "stop_music",
        "volume_music",
        "queue_music",
        "voice_channel",
        "voice_stream",
        "music_player",
        "audio_node",
    }

    # 領域意圖關鍵字與核心對應工具映射
    DOMAIN_INTENT_MAP: Dict[str, Dict[str, Any]] = {
        "LIFE_INTEL": {
            "name": "生活情資",
            "keywords": [
                "油價", "中油", "天氣", "氣象", "降雨", "氣溫", "颱風", "地震", "發票", "統一發票",
                "空氣品質", "aqi", "台鐵", "火車", "捷運", "公車", "路況", "cpc", "cwa",
                "傘", "帶傘", "雨傘", "下雨", "晴天", "陰天", "溫度"
            ],
            "core_tools": [
                "cpc_fuel_prices",
                "taiwan_invoice_lottery",
                "cwa_realtime_weather",
                "weather_probe",
                "cwa_earthquake",
                "taiwan_air_quality",
                "rail_timetable_query",
                "taiwan_transit_status",
            ],
        },
        "SERVER_MANAGEMENT": {
            "name": "伺服器管理與診斷",
            "keywords": [
                "伺服器狀態", "系統診斷", "主機健康", "記憶體", "cpu", "主機延遲", "延遲", "ping",
                "磁碟", "程序", "模組狀態", "資料庫統計", "快取"
            ],
            "core_tools": [
                "system_diagnostics",
                "module_health",
                "guild_diagnostics",
                "database_stats",
                "bot_latency_probe",
                "cache_stats",
                "system_disk_usage",
                "python_runtime_info",
            ],
        },
        "CHANNEL_ANALYTICS": {
            "name": "頻道分析與情資",
            "keywords": [
                "頻道訊息", "統整頻道", "分析頻道", "聊天紀錄", "發言統計", "活躍成員", "訊息統整",
                "歷史發言", "社群趨勢", "活躍度"
            ],
            "core_tools": [
                "inspect_channel_messages",
                "analyze_channel_activity",
                "inspect_channel_overview",
                "text_word_count",
                "statistics_summary",
            ],
        },
        "SANDBOX_COMPUTE": {
            "name": "沙盒計算與工程",
            "keywords": [
                "程式碼", "代碼", "python", "沙盒", "除錯", "debug", "執行", "腳本", "計算",
                "算式", "矩陣", "圖表", "繪圖", "統計", "質因數", "正規表達式", "階乘", "數學"
            ],
            "core_tools": [
                "python_code_sandbox",
                "plot_chart",
                "calculator",
                "statistics_summary",
                "prime_factorization",
                "regex_match_test",
                "json_validator_formatter",
            ],
        },
        "FINANCE_NETWORK": {
            "name": "金融網路與公開生態",
            "keywords": [
                "股票", "股價", "收盤價", "美股", "匯率", "貨幣轉換", "比特幣", "虛擬貨幣", "crypto",
                "網址", "域名", "ip", "ssl", "dns", "搜尋", "網路查詢", "百科"
            ],
            "core_tools": [
                "stock_quote",
                "crypto_quote",
                "currency_exchange_convert",
                "web_search",
                "web_fetch",
                "get_ip_geo_info",
                "check_website_ssl",
                "dns_lookup_a",
            ],
        },
    }

    # 通用常備補充工具（當特定領域工具數不足 3 項時作為穩定補充）
    FALLBACK_GENERAL_TOOLS: List[str] = [
        "web_search",
        "system_diagnostics",
        "calculator",
        "current_time_query",
    ]

    @classmethod
    def project(
        cls,
        user_prompt: str,
        complexity: Optional[ComplexityLevel] = None,
        min_tools: int = 3,
        max_tools: int = 8,
        registry: Optional[Any] = None,
    ) -> ActiveToolSet:
        """根據使用者提問與任務複雜度，動態投影 3~8 個工具之 Active Tool Set。

        規則：
        1. 若複雜度為 SIMPLE ➔ 返回 0 工具，不浪費 Token 與延遲。
        2. 若為 MEDIUM / COMPLEX / EXTREME ➔ 投影 3~8 個工具。
        3. 嚴格過濾隔離音訊串流播放組件。
        """
        prompt = (user_prompt or "").strip()
        reg = registry or agent_tools

        # 若未傳入 complexity，自動自適應評估
        actual_complexity = complexity or evaluate_complexity(prompt)

        # 核心規範：SIMPLE 等級 0 工具毫秒直出
        if actual_complexity == ComplexityLevel.SIMPLE:
            return ActiveToolSet(
                tools=[],
                primary_domain="CONVERSATION",
                complexity=actual_complexity,
                user_prompt=prompt,
            )

        # 1. 判定領域與得分
        lower_prompt = prompt.lower()
        matched_domain = cls._detect_primary_domain(lower_prompt)

        # 2. 計算所有工具對 Prompt 與領域的相關性分數
        all_tools: List[ReadOnlyTool] = reg.list_tools()
        scored_tools: List[Tuple[float, ReadOnlyTool]] = []

        for tool in all_tools:
            # 安全隔離檢查：若涉及音訊串流播放相關，絕對排除
            if cls._is_isolated_music_tool(tool.name, tool.description):
                continue

            score = cls._calculate_tool_relevance(
                tool=tool,
                prompt=lower_prompt,
                primary_domain=matched_domain,
            )
            if score > 0.0:
                scored_tools.append((score, tool))

        # 依分數由高至低排序
        scored_tools.sort(key=lambda x: x[0], reverse=True)

        # 3. 選取推薦工具
        selected_tool_objs: List[ReadOnlyTool] = []
        selected_names: Set[str] = set()

        for score, tool in scored_tools:
            if tool.name not in selected_names:
                selected_tool_objs.append(tool)
                selected_names.add(tool.name)
                if len(selected_tool_objs) >= max_tools:
                    break

        # 4. 若符合條件之工具少於 min_tools，自領域核心工具或備用工具中補充
        if len(selected_tool_objs) < min_tools:
            # 先從領域 core_tools 補充
            domain_info = cls.DOMAIN_INTENT_MAP.get(matched_domain)
            if domain_info:
                for tool_name in domain_info["core_tools"]:
                    if tool_name not in selected_names:
                        tool_obj = reg.get_tool(tool_name)
                        if tool_obj and not cls._is_isolated_music_tool(tool_obj.name, tool_obj.description):
                            selected_tool_objs.append(tool_obj)
                            selected_names.add(tool_obj.name)
                            if len(selected_tool_objs) >= min_tools:
                                break

            # 若仍不足，自通用補充工具集中補充
            if len(selected_tool_objs) < min_tools:
                for fallback_name in cls.FALLBACK_GENERAL_TOOLS:
                    if fallback_name not in selected_names:
                        tool_obj = reg.get_tool(fallback_name)
                        if tool_obj and not cls._is_isolated_music_tool(tool_obj.name, tool_obj.description):
                            selected_tool_objs.append(tool_obj)
                            selected_names.add(tool_obj.name)
                            if len(selected_tool_objs) >= min_tools:
                                break

        # 截斷確保不超過上限 max_tools
        final_tools = selected_tool_objs[:max_tools]

        # 5. 包裝為 ProjectedTool 物件
        projected_list: List[ProjectedTool] = []
        for tool in final_tools:
            score = next((s for s, t in scored_tools if t.name == tool.name), 10.0)
            projected_list.append(
                ProjectedTool(
                    name=tool.name,
                    category=tool.category,
                    description=tool.description,
                    relevance_score=round(score, 2),
                    openai_schema=tool.to_openai_tool_schema(),
                    gemini_schema=tool.to_gemini_tool_schema(),
                )
            )

        return ActiveToolSet(
            tools=projected_list,
            primary_domain=matched_domain,
            complexity=actual_complexity,
            user_prompt=prompt,
        )

    @classmethod
    def _detect_primary_domain(cls, lower_prompt: str) -> str:
        """根據 Prompt 關鍵字匹配最佳主領域。"""
        domain_scores: Dict[str, int] = {}

        for domain_key, data in cls.DOMAIN_INTENT_MAP.items():
            score = 0
            for kw in data["keywords"]:
                if kw in lower_prompt:
                    score += 10
            domain_scores[domain_key] = score

        best_domain = max(domain_scores, key=lambda k: domain_scores[k])
        if domain_scores[best_domain] > 0:
            return best_domain
        return "GENERAL_PROBE"

    @classmethod
    def _calculate_tool_relevance(
        cls,
        tool: ReadOnlyTool,
        prompt: str,
        primary_domain: str,
    ) -> float:
        """計算單一工具針對使用者提問與領域之相關性得分。"""
        score = 0.0
        tool_name_lower = tool.name.lower()
        desc_lower = tool.description.lower()

        # 1. 領域核心工具加權
        domain_data = cls.DOMAIN_INTENT_MAP.get(primary_domain)
        if domain_data:
            if tool.name in domain_data["core_tools"]:
                score += 80.0
            for kw in domain_data["keywords"]:
                if kw in desc_lower or kw in tool_name_lower:
                    score += 15.0

        # 2. Prompt 直接命中工具名稱關鍵詞
        # 分割工具名稱以底線隔開的詞元
        tokens = [tk for tk in tool_name_lower.split("_") if len(tk) > 1]
        for token in tokens:
            if token in prompt:
                score += 40.0

        # 3. Prompt 與工具描述之中文與英文詞元比對
        if any(w in prompt for w in ["油價", "中油"] if w in desc_lower):
            score += 100.0
        if any(w in prompt for w in ["天氣", "氣象", "預報", "氣溫"] if w in desc_lower):
            score += 100.0
        if any(w in prompt for w in ["發票", "對獎", "中獎號碼"] if w in desc_lower):
            score += 100.0
        if any(w in prompt for w in ["股票", "股價", "收盤價"] if w in desc_lower):
            score += 100.0
        if any(w in prompt for w in ["頻道", "訊息", "聊天紀錄"] if w in desc_lower):
            score += 100.0
        if any(w in prompt for w in ["沙盒", "python", "程式碼", "除錯"] if w in desc_lower):
            score += 100.0
        if any(w in prompt for w in ["系統", "記憶體", "主機", "健康"] if w in desc_lower):
            score += 60.0

        # 基礎詞頻統計
        words = re.findall(r"[\u4e00-\u9fa5]{2,}|[a-zA-Z]{3,}", prompt)
        for w in set(words):
            if w.lower() in desc_lower:
                score += 20.0

        return score

    @classmethod
    def _is_isolated_music_tool(cls, name: str, description: str) -> bool:
        """判定工具是否屬於被絕對隔離保護的音訊串流播放組件。"""
        lower_name = name.lower()
        lower_desc = description.lower()
        for kw in cls.ISOLATED_MUSIC_DENYLIST:
            if kw in lower_name or kw in lower_desc:
                return True
        return False


# 模組快捷進入點
project_active_tools = DynamicToolProjector.project
dynamic_projector = DynamicToolProjector()

__all__ = [
    "ProjectedTool",
    "ActiveToolSet",
    "DynamicToolProjector",
    "project_active_tools",
    "dynamic_projector",
]

