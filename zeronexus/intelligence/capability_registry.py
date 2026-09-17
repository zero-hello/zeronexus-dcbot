"""Zero Intelligence - 執行時期動態能力註冊與投影器 (Capability Registry).

核心哲學與規範：
- 終結「靜態寫死在人設 Prompt 中導致功能過期、脫節」的系統痛點。
- 達成「程式碼新增工具或模組，所有模型與人設 0 秒自動同步最新能力清單」。
- 嚴格遵守真實性公理 (Ground-Truth Axiom)：只列出真實已實作與啟用的功能，杜絕假能力宣稱。
- 音樂模組硬性隔離：絕不干擾音訊串流組件。
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional


class CapabilityDomain(str, Enum):
    """能力所屬領域分類。"""
    CHANNEL_CONTEXT = "頻道情境洞察與情資分析"
    TAIWAN_LIFE = "臺灣民生與交通即時情資"
    FINANCE_NETWORK = "金融市場與網路安全診斷"
    CODE_SANDBOX = "Python 安全沙盒與計算分析"
    MULTIMODAL_IMAGE = "多模態檔案剖析與 AI 影像生成"
    COMMUNITY_INTERACTION = "社群娛樂與 Components V2 互動"
    METEOROLOGY_EARTHQUAKE = "中央氣象署全景氣象與地震速報"


@dataclass
class SystemCapability:
    """代表一項系統已實裝且運行的真實能力。"""
    capability_id: str
    name: str
    domain: CapabilityDomain
    description: str
    trigger_keywords: List[str] = field(default_factory=list)
    slash_command: Optional[str] = None
    tool_names: List[str] = field(default_factory=list)
    is_active: bool = True


class CapabilityRegistry:
    """全域動態能力註冊表，負責維護真實能力清單並生成動態提示詞。"""

    def __init__(self) -> None:
        self._capabilities: Dict[str, SystemCapability] = {}
        self._initialize_core_capabilities()

    def _initialize_core_capabilities(self) -> None:
        """初始化目前專案真實具備之全部最新核心能力。"""
        # 1. 頻道情境洞察與情資分析
        self.register(SystemCapability(
            capability_id="channel_inspector",
            name="Discord 頻道即時情境與聊天洞察",
            domain=CapabilityDomain.CHANNEL_CONTEXT,
            description="支援自然語言時間解析（如 20:03、半小時前、今天上午），可統整歷史聊天話題、抓取指定時段訊息、計算頻道發言之王排行榜與活躍度大盤。",
            trigger_keywords=["統整", "聊天", "聊什麼", "誰說最多", "發言排行", "頻道活躍", "歷史訊息"],
            slash_command="/頻道 摘要 | /頻道 統計 | /頻道 總覽",
            tool_names=["inspect_channel_messages", "analyze_channel_activity", "inspect_channel_overview"]
        ))

        # 2. 臺灣民生與交通即時情資
        self.register(SystemCapability(
            capability_id="taiwan_life_traffic",
            name="臺灣民生油價、發票與雙鐵時刻",
            domain=CapabilityDomain.TAIWAN_LIFE,
            description="即時查詢臺灣中油當前油價（92/95/98/柴油）與下週預估調幅；財政部統一發票最新中獎號碼比對；台鐵與臺灣高鐵即時班次時刻表與延誤通報。",
            trigger_keywords=["油價", "下週油價", "中油", "發票", "中獎號碼", "台鐵", "火車", "高鐵", "誤點", "時刻表"],
            slash_command="/生活 (或直接自然語言提問)",
            tool_names=["get_cpc_fuel_prices", "get_taiwan_invoice_lottery", "query_rail_timetable"]
        ))

        # 3. 金融市場與網路安全診斷
        self.register(SystemCapability(
            capability_id="finance_and_network",
            name="台美股市行情、IP 地理與網站安全檢驗",
            domain=CapabilityDomain.FINANCE_NETWORK,
            description="台股（如 2330、0050）與美股（NVDA、AAPL、TSLA）即時報價走勢；IP 歸屬地與 ISP 檢索；網站 SSL 憑證健康度與過期檢查；B站影片情資解析；iTunes 30 秒母帶音樂試聽；安全專案封存打包。",
            trigger_keywords=["股票", "股價", "台積電", "美股", "IP", "歸屬地", "SSL", "憑證", "B站", "bilibili", "試聽", "音樂預聽"],
            slash_command="/工具 (或直接自然語言提問)",
            tool_names=["get_stock_quote", "get_ip_geo_info", "check_website_ssl", "get_bilibili_video_info", "search_music_preview", "create_project_zip_archive"]
        ))

        # 4. Python 安全沙盒與計算分析
        self.register(SystemCapability(
            capability_id="code_sandbox",
            name="Python 受限安全沙盒運算引擎",
            domain=CapabilityDomain.CODE_SANDBOX,
            description="在受嚴格記憶體、超時與 AST 隔離的安全沙盒中直接執行真實 Python 程式碼，進行數學運算、數據處理與分析，絕不憑空臆測計算結果。",
            trigger_keywords=["計算", "算一下", "執行代碼", "python", "運算", "統計計算"],
            slash_command="自然語言觸發或工具調用",
            tool_names=["execute_python_sandbox"]
        ))

        # 5. 多模態檔案剖析與 AI 影像生成
        self.register(SystemCapability(
            capability_id="multimodal_and_image",
            name="全格式檔案剖析與 AI 影像生成引擎",
            domain=CapabilityDomain.MULTIMODAL_IMAGE,
            description="自動解析使用者上傳之 PDF、Word (.docx)、CSV、純文字及原始碼檔案；支援 Gemini 2.5 旗艦繪圖引擎，內建每人每日 3 張配額保護。",
            trigger_keywords=["生成圖片", "畫圖", "產圖", "檔案總結", "閱讀附件"],
            slash_command="/人工智慧 生圖",
            tool_names=["generate_ai_image"]
        ))

        # 6. 社群娛樂與 Components V2 互動
        self.register(SystemCapability(
            capability_id="community_interactions",
            name="Discord Components V2 動態社群娛樂套件",
            domain=CapabilityDomain.COMMUNITY_INTERACTION,
            description="互動式海龜湯情境推理裁判、賽博法庭公審陪審團、匿名樹洞真心話投遞、猜歌遊戲與抽卡娛樂。",
            trigger_keywords=["海龜湯", "賽博法庭", "樹洞", "猜歌", "抽卡"],
            slash_command="/娛樂 | /社群",
            tool_names=[]
        ))

        # 7. 中央氣象署全景氣象與地震速報
        self.register(SystemCapability(
            capability_id="cwa_weather_earthquake",
            name="交通部中央氣象署 (CWA) 實時觀測與地震速報",
            domain=CapabilityDomain.METEOROLOGY_EARTHQUAKE,
            description="全台自動氣象站實時溫濕度風向觀測、36小時逐時天氣預報，以及全自動顯著有感地震報告與區域地震速報推送。",
            trigger_keywords=["天氣", "氣溫", "下雨", "氣象", "地震", "地震報告"],
            slash_command="/氣象",
            tool_names=["get_cwa_weather", "get_earthquake_report"]
        ))

    def register(self, capability: SystemCapability) -> None:
        """註冊一項能力。"""
        self._capabilities[capability.capability_id] = capability

    def unregister(self, capability_id: str) -> None:
        """註銷一項能力。"""
        if capability_id in self._capabilities:
            del self._capabilities[capability_id]

    def get_all_active_capabilities(self) -> List[SystemCapability]:
        """取得所有啟用中的能力。"""
        return [c for c in self._capabilities.values() if c.is_active]

    def get_dynamic_capabilities_prompt(self) -> str:
        """產出即時動態 Markdown 格式能力清單，用於注入到模型推論上下文 (System Prompt)。
        
        該清單保證永遠為執行時期最新真理，徹底根除人設 Prompt 功能過期與脫節。
        """
        active_caps = self.get_all_active_capabilities()
        lines = [
            "### 🛠️ 【ZeroNexus 執行時期真實能力與即時工具清單 (Runtime Ground-Truth)】",
            "本區塊由系統依據當前已加載模組動態生成，代表你「真實具備」的即時功能與工具，請隨時依此回答使用者的功能諮詢與調度需求：",
            ""
        ]

        # 按領域分組
        domains: Dict[CapabilityDomain, List[SystemCapability]] = {}
        for cap in active_caps:
            domains.setdefault(cap.domain, []).append(cap)

        for domain, caps in domains.items():
            lines.append(f"#### ❖ {domain.value}")
            for cap in caps:
                cmd_info = f"（指令：`{cap.slash_command}`）" if cap.slash_command else ""
                lines.append(f"- **{cap.name}**{cmd_info}：{cap.description}")
            lines.append("")

        lines.append("> [!IMPORTANT]")
        lines.append("> **真實性公理守則**：當使用者詢問你能做什麼或要求執行上述任務時，請明確自信地運用上述能力；絕不聲稱不存在的功能，亦不隱瞞你已具備的上述最新本領！")
        return "\n".join(lines)


# 全域單例
capability_registry = CapabilityRegistry()
