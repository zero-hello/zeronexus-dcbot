"""Zero Intelligence 自適應複雜度控制器 (Adaptive Complexity Router).

核心精神：
依據使用者任務目標自適應動態調度，不做過度思考，也不做淺層應付。
精準分級：
- SIMPLE: 打招呼、閒聊、簡單常識、常規對話 ➔ 0 工具毫秒直出，不浪費算力與假裝思考。
- MEDIUM: 即時單點查詢（如查油價、天氣、股票、發票） ➔ 單步工具精確命中。
- COMPLEX: 多步推演（跨時段頻道訊息統整、多維數據統計） ➔ 啟動步驟規劃與驗證。
- EXTREME: 深度代碼除錯、安全沙盒多步探索 ➔ 啟動完整動作帳本與自適應驗證。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple


class ComplexityLevel(str, Enum):
    """任務複雜度等級枚舉。

    支援數值優先級排序比較（SIMPLE < MEDIUM < COMPLEX < EXTREME）。
    """

    SIMPLE = "SIMPLE"      # 閒聊問候、常規對話、純文字回覆
    MEDIUM = "MEDIUM"      # 單點外部探針查詢（天氣、油價、發票、匯率等）
    COMPLEX = "COMPLEX"    # 多步推演、跨頻道歷史統整、多維數據統計
    EXTREME = "EXTREME"    # 深度程式碼除錯、安全沙盒探索、動作帳本驗證

    @property
    def rank(self) -> int:
        """取得複雜度數值階級，便於進行比較。"""
        ranks = {
            ComplexityLevel.SIMPLE: 1,
            ComplexityLevel.MEDIUM: 2,
            ComplexityLevel.COMPLEX: 3,
            ComplexityLevel.EXTREME: 4,
        }
        return ranks[self]

    def __lt__(self, other: Any) -> bool:
        if isinstance(other, ComplexityLevel):
            return self.rank < other.rank
        return NotImplemented

    def __le__(self, other: Any) -> bool:
        if isinstance(other, ComplexityLevel):
            return self.rank <= other.rank
        return NotImplemented

    def __gt__(self, other: Any) -> bool:
        if isinstance(other, ComplexityLevel):
            return self.rank > other.rank
        return NotImplemented

    def __ge__(self, other: Any) -> bool:
        if isinstance(other, ComplexityLevel):
            return self.rank >= other.rank
        return NotImplemented


@dataclass(frozen=True)
class ComplexityDecision:
    """複雜度評估之結構化決策結果。"""

    level: ComplexityLevel
    confidence: float
    reason: str
    matched_intent: str
    suggested_timeout_seconds: float
    max_allowed_steps: int
    requires_tools: bool
    requires_verification: bool


# =============================================================================
# 啟發式規則與正則特徵庫
# =============================================================================

# 1. EXTREME 特徵：深度程式碼除錯、沙盒探索、安全驗證
_EXTREME_PATTERNS: List[Tuple[str, str]] = [
    (r"(?:python_code_sandbox|代碼沙盒|程式碼沙盒|安全沙盒|沙盒探索|沙盒執行)", "明確請求沙盒環境執行"),
    (r"(?:沙盒|sandbox).*(?:除錯|執行|代碼|程式碼|python|探索|跑|測試)", "沙盒與程式碼結合探索"),
    (r"(?:除錯|debug|修復|排查|找出).*(?:代碼|程式碼|python|程式|腳本|函式|函數|bug|錯誤|例外)", "深度程式碼修復與除錯"),
    (r"(?:代碼|程式碼|python|腳本|程式).*(?:除錯|debug|修復|報錯|異常|沙盒|bug)", "代碼關聯性除錯診斷"),
    (r"(?:traceback|exception|stack\s*trace|零除錯誤|zerodivisionerror|syntaxerror|typeerror|nameerror|indexerror|keyerror)", "包含錯誤堆疊日誌追蹤"),
    (r"(?:記憶體洩漏|memory\s*leak|死結|deadlock|競態條件|race\s*condition|緩衝區溢位)", "並行架構與底層系統除錯"),
    (r"(?:滲透測試|安全漏洞審計|逆向工程|二進位反編譯|動態追蹤)", "高階安全與逆向探索"),
]

# 2. COMPLEX 特徵：多步推演、跨頻道訊息統整、多維數據統計、歷史趨勢
_COMPLEX_PATTERNS: List[Tuple[str, str]] = [
    (r"(?:跨頻道|多頻道|整個伺服器|所有頻道).*(?:統整|分析|統計|彙總|歸納)", "跨頻道資訊彙總"),
    (r"(?:統整|分析|彙整|彙總|總結|統計|梳理).*(?:頻道|訊息|聊天|發言|討論)", "頻道訊息綜合分析"),
    (r"(?:頻道|聊天室|群組).*(?:訊息|發言|記錄|紀錄|動態).*(?:統整|分析|統計|彙整|彙總|總結)", "頻道記錄時序分析"),
    (r"(?:過去|最近|近)\s*(?:\d+|[一二兩三四五六七八九十]+|幾|數)\s*(?:天|週|小時|個月).*(?:訊息|聊天|發言|討論|趨勢|動態)", "跨時段歷史訊息時序分析"),
    (r"(?:多維數據|多維度統計|交叉比對|多變量分析|相關性分析)", "多維度統計分析"),
    (r"(?:inspect_channel_messages|analyze_channel_activity|inspect_channel_overview)", "明確指定頻道深層探針"),
    (r"(?:步驟規劃|多步推演|多階段驗證|擬定計畫並執行|全面排查)", "多階段複雜流程推演"),
    (r"(?:統計最活躍|排行前|成員發言榜|互動趨勢圖|活躍度排行)", "社群動態計量與排行"),
]

# 3. MEDIUM 特徵：即時單點查詢（油價、氣象、股票、發票、台鐵、系統診斷等）
_MEDIUM_PATTERNS: List[Tuple[str, str]] = [
    # 生活情資
    (r"(?:油價|中油|浮動油價|95無鉛|98無鉛|柴油價格|cpc_fuel)", "即時油價查詢"),
    (r"(?:天氣|氣象|即時天氣|天氣預報|降雨機率|降雨量|紫外線|雷達回波|衛星雲圖|颱風|地震|cwa|帶傘|雨傘|下雨|下雪|晴天|陰天|氣溫|溫度)", "中央氣象情資查詢"),
    (r"(?:統一發票|發票開獎|發票中獎|對獎|開獎號碼|taiwan_invoice)", "統一發票對獎查詢"),
    (r"(?:空氣品質|aqi|pm2\.5|空氣指標)", "環境空氣品質查詢"),
    (r"(?:台鐵|火車時刻|高鐵時刻|時刻表|轉乘資訊|捷運|公車動態|rail_timetable)", "大眾運輸即時時刻查詢"),
    # 金融網路
    (r"(?:股票|股價|收盤價|台積電|聯發科|美股|開盤價|stock_quote)", "股票行情查詢"),
    (r"(?:匯率|美金匯率|日幣匯率|歐元匯率|貨幣轉換|換算成)", "外匯即時匯率轉換"),
    (r"(?:比特幣|以太幣|加密貨幣|虛擬貨幣|crypto|btc|eth)", "加密貨幣行情查詢"),
    # 系統診斷與網路探測
    (r"(?:系統診斷|主機狀態|伺服器健康|記憶體使用率|cpu使用率|主機延遲|系統磁碟|bot延遲|system_diagnostics)", "主機與程序系統診斷"),
    (r"(?:查詢\s*ip|ip\s*查詢|dns\s*查詢|網站\s*ssl|檢查網址|whois|網址安全)", "網路與網域名稱探測"),
    # 計算與文本工具
    (r"(?:質因數分解|最大公因數|最小公倍數|一元二次方程式|解方程式|計算機|算一下|計算|階乘|算式|百分比計算|三角函數)", "精確數學與科學運算"),
    (r"(?:base64|sha256|md5|urlencode|正規表達式|regex|字數統計|json驗證)", "文本與資料編碼單步工具"),
    # 公開社群娛樂單點
    (r"(?:minecraft|當個創世神|麥塊伺服器|伺服器人數|ping\s*mc)", "Minecraft 伺服器探針"),
    (r"(?:steam|遊戲特惠|今日歷史上的今天|維基百科|wikipedia|抽塔羅牌|擲骰子|擲硬幣)", "生態與休閒工具查詢"),
]

# 4. SIMPLE 特徵：問候、閒聊、感謝、無工具常規對話
_SIMPLE_PATTERNS: List[Tuple[str, str]] = [
    (r"^(?:嗨|嗨囉|哈囉|hello|hi|hey|安安|早安|午安|晚安|你好|您好|在嗎|在不在|哈囉你好)[！!。~～\s]*$", "招呼問候語"),
    (r"^(?:謝謝|感謝|多謝|感恩|thank\s*you|thanks|3q|辛苦了)[！!。~～\s]*$", "禮貌感謝語"),
    (r"^(?:掰掰|再見|拜拜|goodbye|bye|晚安囉)[！!。~～\s]*$", "告別問候語"),
    (r"(?:講個笑話|說個笑話|逗我笑|說笑話)", "趣味社交閒聊"),
    (r"(?:你是誰|介紹你自己|自我介紹|你有什麼能力|自我說明)", "機器人身分介紹"),
    (r"(?:今天心情好嗎|你喜歡什麼|今天過得如何|聊聊天|陪我聊聊)", "一般日常閒聊"),
]


class ComplexityRouter:
    """自適應複雜度控制器核心實例。"""

    @classmethod
    def evaluate(cls, user_prompt: str, context: Optional[Dict[str, Any]] = None) -> ComplexityLevel:
        """自適應分類評估器入口，回傳對應的 ComplexityLevel。"""
        decision = cls.analyze(user_prompt, context)
        return decision.level

    @classmethod
    def analyze(cls, user_prompt: str, context: Optional[Dict[str, Any]] = None) -> ComplexityDecision:
        """深入分析使用者提問，產出包含信心度、最大限制與理由的詳細決策。"""
        ctx = context or {}
        cleaned_prompt = (user_prompt or "").strip()

        # 1. 檢查 Context 中是否有強制指定層級 (Developer / Direct Override)
        if "force_level" in ctx:
            forced = ctx["force_level"]
            if isinstance(forced, ComplexityLevel):
                return cls._build_decision(
                    forced, 1.0, f"依據上下文強制指定複雜度: {forced.value}", "context_force_override"
                )
            if isinstance(forced, str) and forced.upper() in ComplexityLevel.__members__:
                lvl = ComplexityLevel[forced.upper()]
                return cls._build_decision(
                    lvl, 1.0, f"依據上下文強制指定複雜度: {lvl.value}", "context_force_override"
                )

        # 2. 檢查 Context 特徵旗標
        if ctx.get("is_code_debugging") or ctx.get("requires_sandbox"):
            return cls._build_decision(
                ComplexityLevel.EXTREME,
                0.95,
                "上下文已標註需進行深度程式碼除錯或沙盒操作",
                "context_code_debugging",
            )
        if ctx.get("is_channel_analysis") or ctx.get("requires_multi_step_planning"):
            return cls._build_decision(
                ComplexityLevel.COMPLEX,
                0.95,
                "上下文已標註需進行頻道情資統整或多步推演",
                "context_channel_analysis",
            )

        # 若 Prompt 為空，預設為 SIMPLE
        if not cleaned_prompt:
            return cls._build_decision(
                ComplexityLevel.SIMPLE, 1.0, "輸入為空字串，直接以預設對話模式響應", "empty_prompt"
            )

        lower_prompt = cleaned_prompt.lower()

        # 3. 檢查 EXTREME 條件（除錯、沙盒探索）
        for pattern, reason in _EXTREME_PATTERNS:
            if re.search(pattern, lower_prompt):
                return cls._build_decision(
                    ComplexityLevel.EXTREME,
                    0.95,
                    f"偵測到深度程式碼除錯或安全沙盒特徵（{reason}）",
                    "extreme_code_sandbox",
                )

        # 4. 檢查 COMPLEX 條件（多步推演、跨頻道統整、多維統計）
        for pattern, reason in _COMPLEX_PATTERNS:
            if re.search(pattern, lower_prompt):
                return cls._build_decision(
                    ComplexityLevel.COMPLEX,
                    0.92,
                    f"偵測到多步推演或跨時段頻道訊息統整特徵（{reason}）",
                    "complex_multi_step_analytics",
                )

        # 5. 檢查 MEDIUM 條件（即時單點外部查詢）
        for pattern, reason in _MEDIUM_PATTERNS:
            if re.search(pattern, lower_prompt):
                return cls._build_decision(
                    ComplexityLevel.MEDIUM,
                    0.90,
                    f"偵測到單點即時情報或工具查詢需求（{reason}）",
                    "medium_single_probe",
                )

        # 6. 檢查純 SIMPLE 語意特徵（問候、致謝、打招呼、身分介紹）
        for pattern, reason in _SIMPLE_PATTERNS:
            if re.search(pattern, lower_prompt):
                return cls._build_decision(
                    ComplexityLevel.SIMPLE,
                    0.95,
                    f"偵測到日常問候、禮貌回應或基礎常識對話（{reason}）",
                    "simple_greeting_conversation",
                )

        # 7. 兜底啟發式自適應決策：
        # 如果句子很短（小於 15 字元）且未匹配任何工具關鍵字，歸類為 SIMPLE 常規對話
        if len(cleaned_prompt) < 15 and not any(k in cleaned_prompt for k in ["查", "找", "算", "分析", "統計", "除錯"]):
            return cls._build_decision(
                ComplexityLevel.SIMPLE,
                0.80,
                "短句日常對話，未觸發工具查詢，0 工具直出",
                "heuristic_short_conversation",
            )

        # 若句子帶有問題或查詢意圖但未匹配特定領域，預設升級至 MEDIUM 以啟用通用網路與常規探測工具
        if any(q in cleaned_prompt for q in ["嗎", "?", "？", "怎", "如何", "為什麼", "查", "搜尋", "幫我"]):
            return cls._build_decision(
                ComplexityLevel.MEDIUM,
                0.70,
                "包含通用提問或查詢意圖，配置單點基礎工具集",
                "heuristic_general_query",
            )

        # 預設為 SIMPLE（常規對話，不濫用算力）
        return cls._build_decision(
            ComplexityLevel.SIMPLE,
            0.75,
            "一般日常對話交流，無外部資料依賴，0 工具毫秒直出",
            "default_simple_conversation",
        )

    @classmethod
    def _build_decision(
        cls,
        level: ComplexityLevel,
        confidence: float,
        reason: str,
        matched_intent: str,
    ) -> ComplexityDecision:
        """根據評定等級封裝對應的參數限額。"""
        if level == ComplexityLevel.SIMPLE:
            return ComplexityDecision(
                level=level,
                confidence=confidence,
                reason=reason,
                matched_intent=matched_intent,
                suggested_timeout_seconds=5.0,
                max_allowed_steps=0,
                requires_tools=False,
                requires_verification=False,
            )
        elif level == ComplexityLevel.MEDIUM:
            return ComplexityDecision(
                level=level,
                confidence=confidence,
                reason=reason,
                matched_intent=matched_intent,
                suggested_timeout_seconds=15.0,
                max_allowed_steps=2,
                requires_tools=True,
                requires_verification=False,
            )
        elif level == ComplexityLevel.COMPLEX:
            return ComplexityDecision(
                level=level,
                confidence=confidence,
                reason=reason,
                matched_intent=matched_intent,
                suggested_timeout_seconds=45.0,
                max_allowed_steps=6,
                requires_tools=True,
                requires_verification=True,
            )
        else:  # EXTREME
            return ComplexityDecision(
                level=level,
                confidence=confidence,
                reason=reason,
                matched_intent=matched_intent,
                suggested_timeout_seconds=90.0,
                max_allowed_steps=10,
                requires_tools=True,
                requires_verification=True,
            )


# 模組快捷進入點
evaluate_complexity = ComplexityRouter.evaluate
analyze_complexity = ComplexityRouter.analyze
complexity_router = ComplexityRouter()

__all__ = [
    "ComplexityLevel",
    "ComplexityDecision",
    "ComplexityRouter",
    "evaluate_complexity",
    "analyze_complexity",
    "complexity_router",
]

