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
    CYBER_COURT = "賽博法庭與爭端裁決公道伯"
    AI_GATEWAY = "三階 AI 模型智慧閘道與動態切換"
    BIO_BRAIN = "本地六核離線神經感官矩陣與生物大腦"
    TAIWAN_LIFE = "臺灣民生與交通即時情資"
    FINANCE_NETWORK = "金融市場與網路安全診斷"
    METEOROLOGY_EARTHQUAKE = "中央氣象署全景氣象與地震速報"
    CODE_SANDBOX = "Python 安全沙盒與計算分析"
    MULTIMODAL_IMAGE = "多模態檔案剖析與 AI 影像生成"
    TICKET_MODERATION = "伺服器工單系統與資安防護"
    COMMUNITY_ECONOMY_MUSIC = "社群等級經濟與語音音樂播放"
    CHANNEL_CONTEXT = "頻道情境洞察與情資分析"


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
        # 1. 賽博法庭與爭端裁決公道伯
        self.register(SystemCapability(
            capability_id="cyber_court_arbitration",
            name="賽博法庭：爭端回溯與超炸裂公道判決系統",
            domain=CapabilityDomain.CYBER_COURT,
            description="當群友吵架、意見分歧或需要公正評判時，只要引用回覆（Reply）爭論起點訊息並向 ZeroNexus 提問，系統自動精準回溯案發現場完整對話脈絡。AI 以賽博大法官之威嚴與高情商幽默，輸出包含『開庭主文、雙方核心論點拆解、邏輯與情緒漏洞法醫剖析、責任勝訴百分比、法外施恩處分』之超豐富完整判決書！",
            trigger_keywords=["評理", "誰有理", "吵架", "裁決", "公道", "誰對誰錯", "判決", "法官"],
            slash_command="回覆爭論起點訊息並自然提問",
            tool_names=[]
        ))

        # 2. 三階 AI 模型智慧閘道與動態切換
        self.register(SystemCapability(
            capability_id="tri_vendor_ai_gateway",
            name="三階頂尖 AI 模型智慧閘道",
            domain=CapabilityDomain.AI_GATEWAY,
            description="支援三大頂尖模型架構：Rank 1 旗艦預設（Google Gemini 原生百萬上下文超低延遲）、Rank 2 深度思維（DeepSeek 複雜邏輯推理）、Rank 3 繁中代碼（Qwen 卓越工程能力）。支援自然語言（如『切換到 deepseek』）或指令秒級切換，具備多金鑰輪詢池與零中斷自動容災降級。",
            trigger_keywords=["換模型", "切換模型", "gemini", "deepseek", "qwen"],
            slash_command="/ai_model | /人工智慧 切換模型 | zn!model",
            tool_names=[]
        ))

        # 3. 本地六核離線神經感官矩陣與生物大腦
        self.register(SystemCapability(
            capability_id="bio_neural_brain",
            name="本地六核離線神經感官矩陣與情緒大腦",
            domain=CapabilityDomain.BIO_BRAIN,
            description="內建本地離線六核多層神經感官矩陣與邊緣心智狀態機：即時運算多巴胺（好奇興奮）、血清素（滿足穩定）、皮質醇（自尊防衛）、催產素（親密羈絆）與精力值；Asia/Taipei 臺灣標準時間五大時段晝夜生物鐘；海馬迴深夜夢境編織；個人專屬親密稱號與生活忌口偏好雷達；AES-256 加密記憶保險庫。",
            trigger_keywords=["心情", "大腦", "生物鐘", "感覺怎樣", "親密感", "做夢"],
            slash_command="自然語言即時情感反應與互動",
            tool_names=[]
        ))

        # 4. 臺灣民生與交通即時情資
        self.register(SystemCapability(
            capability_id="taiwan_life_traffic",
            name="臺灣民生油價、統一發票與雙鐵即時班次時刻",
            domain=CapabilityDomain.TAIWAN_LIFE,
            description="即時查詢臺灣中油當前油價（92/95/98/柴油）與下週漲跌預測；財政部統一發票最新中獎號碼開獎比對；台鐵與臺灣高鐵即時班次時刻表、抵達時間與延誤誤點通報。",
            trigger_keywords=["油價", "下週油價", "中油", "發票", "中獎號碼", "台鐵", "火車", "高鐵", "誤點", "時刻表"],
            slash_command="/生活 (或直接自然語言提問)",
            tool_names=["get_cpc_fuel_prices", "get_taiwan_invoice_lottery", "query_rail_timetable"]
        ))

        # 5. 金融市場與網路安全診斷
        self.register(SystemCapability(
            capability_id="finance_and_network",
            name="台美股市即時行情、IP 歸屬與網站安全檢驗",
            domain=CapabilityDomain.FINANCE_NETWORK,
            description="台股（如台積電 2330、0050）與美股（NVDA、AAPL、TSLA）即時報價與漲跌行情；IP 歸屬地與 ISP 檢索；網站 SSL 憑證健康度與過期檢查；B站 (Bilibili) 影片情報解析；iTunes 30 秒母帶音樂試聽；安全專案封存打包。",
            trigger_keywords=["股票", "股價", "台積電", "美股", "IP", "歸屬地", "SSL", "憑證", "B站", "bilibili", "試聽"],
            slash_command="/工具 (或直接自然語言提問)",
            tool_names=["get_stock_quote", "get_ip_geo_info", "check_website_ssl", "get_bilibili_video_info", "search_music_preview", "create_project_zip_archive"]
        ))

        # 6. 中央氣象署全景氣象與地震速報
        self.register(SystemCapability(
            capability_id="cwa_weather_earthquake",
            name="交通部中央氣象署 (CWA) 實時觀測與地震速報",
            domain=CapabilityDomain.METEOROLOGY_EARTHQUAKE,
            description="全台各縣市自動氣象站實時溫濕度風向觀測、36 小時逐時天氣預報，以及全自動顯著有感地震即時報告與區域地震速報推播。",
            trigger_keywords=["天氣", "氣溫", "下雨", "氣象", "地震", "地震報告"],
            slash_command="/氣象 (或直接自然語言提問)",
            tool_names=["get_cwa_weather", "get_earthquake_report"]
        ))

        # 7. Python 安全沙盒與計算分析
        self.register(SystemCapability(
            capability_id="code_sandbox",
            name="Python 受限安全沙盒運算引擎",
            domain=CapabilityDomain.CODE_SANDBOX,
            description="在受嚴格記憶體、超時與 AST 隔離的安全沙盒中直接執行真實 Python 程式碼，進行複雜數學運算、數據處理與精確統計，絕不憑空臆測計算結果。",
            trigger_keywords=["計算", "算一下", "執行代碼", "python", "運算", "統計計算"],
            slash_command="自然語言觸發或工具調用",
            tool_names=["execute_python_sandbox"]
        ))

        # 8. 多模態檔案剖析與 AI 影像生成
        self.register(SystemCapability(
            capability_id="multimodal_and_image",
            name="全格式檔案剖析與旗艦 AI 影像生成引擎",
            domain=CapabilityDomain.MULTIMODAL_IMAGE,
            description="自動解析使用者上傳之 PDF、Word (.docx)、CSV、純文字及各類程式碼原始檔；支援 Gemini 2.5 旗艦 AI 繪圖引擎，內建每人每日 3 張配額保護與無縫備援。",
            trigger_keywords=["生成圖片", "畫圖", "產圖", "檔案總結", "閱讀附件"],
            slash_command="/人工智慧 生圖 | /image",
            tool_names=["generate_ai_image"]
        ))

        # 9. 伺服器工單系統與資安防護
        self.register(SystemCapability(
            capability_id="ticket_and_moderation",
            name="伺服器企業級工單客服與主動資安防護",
            domain=CapabilityDomain.TICKET_MODERATION,
            description="一鍵建立專屬客服與管理員工單頻道（`/ticket`）；全天候自動透過 Google Safe Browsing 掃描並秒級攔截惡意釣魚連結與木馬網址；內建防連點與防重複送出保護。",
            trigger_keywords=["工單", "ticket", "客服", "資安", "防護"],
            slash_command="/ticket",
            tool_names=[]
        ))

        # 10. 社群等級經濟與語音音樂播放
        self.register(SystemCapability(
            capability_id="economy_level_music",
            name="社群等級經驗值、經濟系統與語音頻道音樂串流",
            domain=CapabilityDomain.COMMUNITY_ECONOMY_MUSIC,
            description="伺服器成員聊天升級經驗值、個人身分圖卡（`/rank`）、全服排行榜（`/leaderboard`）；每日簽到金幣經濟；支援加入語音頻道的高音質音樂播放（`/play`）、暫停、跳過與佇列管理。",
            trigger_keywords=["等級", "rank", "排行榜", "音樂", "放歌", "play"],
            slash_command="/rank | /leaderboard | /play | /skip",
            tool_names=[]
        ))

        # 11. 頻道情境洞察與情資分析
        self.register(SystemCapability(
            capability_id="channel_inspector",
            name="Discord 頻道即時情境與聊天洞察",
            domain=CapabilityDomain.CHANNEL_CONTEXT,
            description="支援自然語言時間解析（如 20:03、半小時前、今天上午），可統整歷史聊天話題、抓取指定時段訊息、計算頻道發言之王排行榜與活躍度大盤。",
            trigger_keywords=["統整", "聊天", "聊什麼", "誰說最多", "發言排行", "頻道活躍", "歷史訊息"],
            slash_command="/頻道 摘要 | /頻道 統計 | /頻道 總覽",
            tool_names=["inspect_channel_messages", "analyze_channel_activity", "inspect_channel_overview"]
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
        lines.append("> **真實性公理與非宣傳原則**：")
        lines.append("> 1. 本清單僅作為你『受到使用者明確詢問功能或要求執行特定任務時』之事實依據，【絕對禁止】在日常打招呼、寒暄、一般閒聊時主動搬出或背誦本清單！")
        lines.append("> 2. 絕不聲稱不存在的功能，亦不隱瞞你真實具備的本領；嚴禁在項目名稱前反覆附加使用者的暱稱！")
        return "\n".join(lines)


# 全域單例
capability_registry = CapabilityRegistry()
