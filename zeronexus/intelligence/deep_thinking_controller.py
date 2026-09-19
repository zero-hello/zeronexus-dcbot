"""Zero Intelligence - 深度思考模式控制器 (Deep Thinking Controller)

整合原生 Python 認知架構：
1. 蒙地卡羅思維樹搜尋 (MCTSThoughtSearch)
2. 符號神經認知網絡 (CognitiveNetwork)
3. 因果推論與矛盾消解器 (CausalEngine)
4. 自然語言意圖精準識別與真人死黨風格互動
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, List, Optional, Set, Tuple

from zeronexus.intelligence.causal_engine import CausalEngine, causal_engine
from zeronexus.intelligence.cognitive_network import CognitiveNetwork, cognitive_network
from zeronexus.intelligence.thought_search_mcts import (
    ThinkingPhase,
)
from zeronexus.intelligence.truth_spectrum import TruthLevel

logger = logging.getLogger("zeronexus.intelligence.deep_thinking")


class ThinkingIntent(str, Enum):
    """意圖類型"""
    NONE = "none"
    ENABLE = "enable"
    DISABLE = "disable"
    STATUS = "status"


@dataclass
class DeepThinkingContext:
    """深度思考執行上下文與產出物"""
    query: str
    is_active: bool
    phases: List[Tuple[ThinkingPhase, str]] = field(default_factory=list)
    activated_concepts: List[Tuple[str, float]] = field(default_factory=list)
    coherence_score: float = 1.0
    contradictions_found: List[str] = field(default_factory=list)
    best_thought_path: List[str] = field(default_factory=list)
    final_synthesis: str = ""
    model_native_thought: Optional[str] = None  # 大模型原生深層思維鏈 (Thinking Tokens)
    is_autonomously_triggered: bool = False     # 是否由 Zero Intelligence 自主元認知觸發
    autonomous_reason: str = ""                 # 自主觸發依據
    autonomous_domain: str = ""                 # 自主觸發領域分類

    def format_discord_thought_process(self) -> str:
        """格式化為適合 Discord 展示的真實大模型思考區塊（徹底杜絕硬編碼模板文字）"""
        sections: List[str] = []

        header = "🧠 **【AI 深度思維推演歷程 (Chain-of-Thought)】**"
        if self.is_autonomously_triggered and self.autonomous_reason:
            sub_header = (
                f"> ⚡ **Zero Intelligence 自主元認知活化 (Autonomous Meta-Cognition Activated)**\n"
                f"> 🎯 審查依據：偵測到深層高階命題【{self.autonomous_domain}：{self.autonomous_reason}】\n"
                f"> 💡 認知決策：本命題具備多維因果推導與邊界假設驗證需求，系統已自主切換至深層思維超頻推導！"
            )
        else:
            sub_header = "> 模型內部認知決策、推論驗證與思維鏈推導（100% 由神經網路原生運算生成）"

        if self.model_native_thought and self.model_native_thought.strip():
            from zeronexus.core.taiwan_translator import taiwan_translator
            clean_thought = taiwan_translator.sanitize_thinking_process(self.model_native_thought.strip())
            # 支援超過 2500 字元的分段或呈現，完整展現 DeepSeek / Gemini 大模型原生思維推導
            if len(clean_thought) > 3500:
                clean_thought = clean_thought[:3400] + "\n\n...（長篇思考歷程已節錄核心推導精華）"
            sections.append(f"{header}\n{sub_header}\n\n{clean_thought}")
        else:
            sections.append(f"{header}\n{sub_header}\n\n> 模型以直覺快速模式響應，未輸出深層思維鏈。")

        return "\n".join(sections)


class DeepThinkingController:
    """深度思考核心控制器（人話語意識別 + 大模型動態親口回應）"""

    # 狀態查詢人話模式
    STATUS_PATTERNS = [
        r"(?:現在|目前)?(?:有開|開啟|處於|開著)?(?:深度思考|深層思考|認真模式|學霸模式|超頻模式)(?:模式)?(?:嗎|狀態|如何|\?|？)",
        r"(?:有沒有|是否有)(?:開啟|打開|啟用|開著)(?:深度思考|深層思考|認真模式)",
        r"(?:深度思考|深層思考)(?:有開嗎|開了嗎|狀態如何|開著嗎)",
        r"現在(?:是|處於)?什麼模式",
        r"(?:你)?(?:現在|目前)?(?:有在|有沒有在)?(?:認真|動腦|深思|超頻)(?:思考|想|推理)?(?:嗎|\?|？)",
    ]

    # 關閉指令的人話模式（日常隨意口語、摸魚、不思考、講結論）
    DISABLE_PATTERNS = [
        r"(?:幫我|請|麻煩)?(?:關閉|退出|關掉|取消|停止|結束|停用)(?:深度思考|深層思考|深度推理|深思模式|學霸模式|認真模式)(?:模式)?",
        r"(?:深度思考|深層思考|深思模式)(?:關閉|退出|關掉|結束|停用)",
        r"(?:關|關掉|別開)深度思考",
        r"(?:不用|不要|別)(?:再)?(?:那麼|太)?(?:深度|深層|認真|死腦筋|複雜)?(?:思考|深思|推導|分析|想那麼多|想太深|動腦|折騰)",
        r"(?:切回|換回|恢復|進入|切到)(?:普通|日常|輕鬆|摸魚|正常|快速|省電|休閒)(?:模式|對話)?",
        r"(?:隨便|隨意)(?:聊聊|講講|回|回答|說說)(?:就好|就行)",
        r"(?:直接說|只要|直接講)(?:結論|重點|答案)(?:就好|就行)?",
        r"(?:簡單點|放輕鬆|輕鬆點|別太嚴肅)(?:就好|就行)?",
        r"(?:turn off|disable|stop|exit)\s*(?:deep thinking|thinking)",
        r"(?:normal|casual|relax)\s*mode",
    ]

    # 開啟指令的人話模式（動動腦、認真點、全力思考、學霸模式）
    ENABLE_PATTERNS = [
        r"(?:你)?(?:給我)?(?:動動|動個|轉轉)(?:你的)?(?:腦袋|大腦|腦子|腦筋|腦)",
        r"(?:認真|仔細|好好)(?:點|思考|想想|推導|推理|分析|回答|琢磨|盤一盤|算一算)(?:一下|看看)?",
        r"(?:全力|超頻|火力全開|極致|死力)(?:思考|輸出|推導|推理|運轉)",
        r"(?:幫我|請|麻煩)?(?:開啟|打開|啟用|啟動|切換(?:成|到)?|進(?:入)?|換到|開個)(?:深度思考|深層思考|深度推理|深思模式|學霸模式|專家模式|硬核推理|思考模式)(?:模式)?",
        r"(?:深度思考|深層思考|深度推理|深思模式|學霸模式|專家模式|認真模式|超頻模式)(?:模式)?(?:開啟|打開|啟用|啟動|拉滿|開起來|開著)",
        r"(?:學霸|專家|硬核|超頻|認真)模式(?:開啟|打開|啟用|啟動|拉滿|開起來|開個)?",
        r"(?:智商|大腦|思考)(?:拉滿|超頻|全開)",
        r"(?:開|啟動|啟用)深度思考",
        r"(?:我想看你動腦|別隨便敷衍我|深思一下|給我深思)",
        r"(?:turn on|enable|start|activate)\s*(?:deep thinking|think deeply|think hard)",
        r"(?:reasoning|hardcore|genius)\s*mode",
    ]

    # 排除模式 (避免問概念或客觀名詞時誤觸發)
    QUESTION_EXCLUDE = [
        r"什麼(?:是|叫)深度思考",
        r"深度思考好用嗎",
        r"為什麼(?:要)?(?:用|開)?深度思考",
        r"不要(?:開|開啟|啟動|啟用)深度思考",
        r"別(?:開|開啟|啟動|啟用)深度思考",
        r"深度思考的(?:原理|歷史|背景|架構)",
    ]

    # =============================================================================
    # Zero Intelligence 自主元認知審查特徵庫 (Autonomous Meta-Cognitive Heuristics)
    # 格式：(正則特徵, 命題理由, 領域分類)
    # =============================================================================
    AUTONOMOUS_COGNITIVE_DOMAINS = [
        # 1. 前沿理論物理與量子科學
        (
            r"(?:量子(?:力學|糾纏|退相干|疊加|穿隧|霍爾效應|自旋|計算|態|隱形傳態)|薛丁格(?:的貓)?|雙縫干涉|延遲選擇實驗|貝爾不等式|epr\s*悖論|相對論|廣義相對論|狹義相對論|時空曲率|黑洞(?:資訊悖論|奇點|事件視界)|引力波|熱力學第[二三]定律|麥克斯韋妖|費曼路徑積分|弦論|超弦|規範場論|暗物質|宇宙暴脹)",
            "量子物理與宇宙前沿理論推演",
            "前沿理論物理",
        ),
        # 2. 形式化公理體系與數學邏輯證明
        (
            r"(?:公理化證明|嚴格證明|反證法|數學歸納法|哥德爾不完備|停機問題|黎曼猜想|費馬大定理|拓撲學|流形|群論|李代數|伽羅瓦理論|抽象代數|np\s*(?:完全|難題|hard|complete)|p\s*vs\s*np|隨機微積分|伊藤引理|測度論|勒貝格積分|圖論證明|同構|同態|同調|微積分推導|歐幾里得證明|質數無窮)",
            "形式化公理體系與數學邏輯嚴格推導",
            "數學公理與邏輯證明",
        ),
        # 3. 高階分散式一致性與底層架構
        (
            r"(?:分散式共識|raft(?:演算法)?|paxos(?:演算法)?|zab|pbft|拜占庭容錯|cap\s*定理|兩階段提交|2pc|3pc|saga\s*模式|非對稱網絡分區|網絡分區|腦裂|選主機制|日誌壓縮|快取一致性|mesi\s*協定|無鎖(?:佇列|隊列|資料結構|編程)|lock-free|記憶體屏障|memory\s*barrier|高併發死鎖分析|分散式事務|向量時鐘|vector\s*clock|分散式鎖)",
            "高階分散式一致性與底層併發架構論證",
            "分散式與底層架構",
        ),
        # 4. 複雜演算法漸進複雜度與狀態轉移
        (
            r"(?:動態規劃狀態轉移|狀壓\s*dp|漸進時間複雜度|均攤分析|紅黑樹平衡調整|b\+樹併發|跳躍表|skip\s*list|網路流|最小割|最大流|迪傑斯特拉|a\*啟發式|kmp\s*演算法|蒙地卡羅樹搜尋|mcts|反向傳播梯度推導|自注意力機制矩陣|transformer\s*複雜度|狀態壓縮)",
            "核心演算法漸進複雜度與狀態轉移分析",
            "複雜演算法與計算複雜度",
        ),
        # 5. 哲學本體論、認識論與深層認知思辨
        (
            r"(?:忒修斯之船|電車難題|中文房間|心靈哲學|心物二元論|決定論與自由意志|缸中之腦|認識論|本體論|現象學|自我意識難題|泛心論|道德困境|功利主義與義務論|唯實論與唯名論|休謨因果問題|康德純粹理性)",
            "哲學本體論、認識論與經典思維悖論剖析",
            "哲學悖論與認知思辨",
        ),
        # 6. 底層系統除錯與漏洞根因分析
        (
            r"(?:記憶體洩漏|memory\s*leak|segmentation\s*fault|段錯誤|core\s*dump|緩衝區溢位|棧溢出|堆破壞|heap\s*corruption|use-after-free|懸空指針|競態條件|race\s*condition|deadlock\s*排查|asan|gdb\s*根因分析)",
            "系統底層異常崩潰與記憶體安全根因剖析",
            "深度系統排錯與根因分析",
        ),
        # 7. 多維工程架構決策與深度權衡
        (
            r"(?:架構權衡|技術選型權衡|trade-off|根本原因分析|系統重構架構評估|架構遷移風險|單體架構轉微服務|異構資料庫同步|事件驅動架構一致性)",
            "多維工程架構決策與深層權衡分析",
            "工程架構與戰略權衡",
        ),
    ]

    # 日常寒暄、禮貌感謝與單點生活探針排除清單（確保日常秒回，不浪費算力）
    TRIVIAL_EXCLUDE_PATTERNS = [
        r"^(?:嗨|嗨囉|哈囉|hello|hi|hey|安安|早安|午安|晚安|你好|您好|在嗎|在不在)[！!。~～\s]*$",
        r"^(?:謝謝|感謝|多謝|感恩|thank\s*you|thanks|3q|辛苦了)[！!。~～\s]*$",
        r"^(?:掰掰|再見|拜拜|goodbye|bye|晚安囉)[！!。~～\s]*$",
        r"(?:油價|即時油價|天氣|氣象|氣溫|統一發票|發票開獎|火車時刻|高鐵時刻|抽塔羅|擲骰子|擲硬幣|算一下\s*\d+[\+\-\*\/])",
    ]

    def __init__(
        self,
        cognition: Optional[CognitiveNetwork] = None,
        causal: Optional[CausalEngine] = None,
    ) -> None:
        self.cognition = cognition or cognitive_network
        self.causal = causal or causal_engine
        # 紀錄已啟用的頻道或使用者 ID (channel_id 或 user_id 字串)
        self.active_contexts: Set[str] = set()

    def evaluate_autonomous_deep_thinking(
        self,
        query: str,
        context: Optional[dict] = None,
    ) -> Tuple[bool, str, str]:
        """Zero Intelligence 自主元認知審查 (Autonomous Meta-Cognitive Deliberation)

        即使使用者未明確提及「開啟深度思考」，系統根據問題本質自主評估是否需要啟用深層思維鏈推演超頻。
        回傳: (should_activate: bool, reason: str, domain: str)
        """
        raw_text = (query or "").strip()
        if len(raw_text) < 4:
            return False, "", ""

        cleaned = raw_text.lower()

        # 1. 快速放行排除：問候、純單點生活查詢
        for triv in self.TRIVIAL_EXCLUDE_PATTERNS:
            if re.search(triv, cleaned):
                return False, "", ""

        # 2. 檢驗七大深層命題維度
        for pattern, reason, domain in self.AUTONOMOUS_COGNITIVE_DOMAINS:
            if re.search(pattern, cleaned):
                # 命中高階領域特徵，自主評判啟動深層思維推演
                logger.info(f"Zero Intelligence 自主元認知活化: 命題「{raw_text[:30]}」符合【{domain}：{reason}】")
                return True, reason, domain

        # 3. 多維概念密度與深度詞彙審查（當提問包含多個深度推導關鍵詞）
        deep_inquiry_markers = ["本質", "底層原理", "推導", "證明", "邊界條件", "因果", "矛盾", "假設", "權衡", "複雜度", "一致性"]
        matched_markers = [m for m in deep_inquiry_markers if m in raw_text]
        if len(matched_markers) >= 2 and len(raw_text) >= 15:
            reason = f"深層多維剖析（涉及 { '、'.join(matched_markers[:3]) }）"
            return True, reason, "多維深度思維推論"

        return False, "", ""

    def parse_intent_and_extract_query(self, text: str) -> Tuple[ThinkingIntent, Optional[str]]:
        """精確解析使用者對深度思考的人話意圖，並判斷是否為複合提問（指令 + 具體問題）"""
        cleaned = text.strip().lower()

        # 優先檢查排除項
        for pattern in self.QUESTION_EXCLUDE:
            if re.search(pattern, cleaned):
                return ThinkingIntent.NONE, None

        # 優先檢查狀態查詢
        for pattern in self.STATUS_PATTERNS:
            if re.search(pattern, cleaned):
                return ThinkingIntent.STATUS, None

        # 檢查關閉意圖
        for pattern in self.DISABLE_PATTERNS:
            if re.search(pattern, cleaned):
                return ThinkingIntent.DISABLE, None

        # 檢查開啟意圖（含人話：動動腦、認真想、學霸模式等）
        for pattern in self.ENABLE_PATTERNS:
            m = re.search(pattern, cleaned)
            if m:
                # 判斷是否為「複合提問」（如：動動腦，幫我分析這題...）
                # 剔除觸發詞後檢查剩餘長度
                sub_text = re.sub(pattern, "", text, count=1, flags=re.IGNORECASE).strip()
                sub_text = re.sub(r"^[,，、\s:：!！~～\-—–]+", "", sub_text).strip()
                # 若剩餘文字有具體提問特徵且長度足夠，代表是複合提問
                if len(sub_text) >= 4 and any(
                    kw in sub_text for kw in ["？", "?", "為什麼", "為何", "怎麼", "如何", "分析", "算", "解釋", "寫", "介紹", "說明", "比較"]
                ):
                    return ThinkingIntent.ENABLE, sub_text
                return ThinkingIntent.ENABLE, None

        return ThinkingIntent.NONE, None

    def parse_intent(self, text: str) -> ThinkingIntent:
        """相容舊版純意圖解析"""
        intent, _ = self.parse_intent_and_extract_query(text)
        return intent

    def set_active(self, context_key: str, active: bool) -> None:
        """設定指定頻道或使用者之深度思考狀態"""
        if active:
            self.active_contexts.add(context_key)
        else:
            self.active_contexts.discard(context_key)

    async def generate_intent_reply(
        self,
        intent: ThinkingIntent,
        user_prompt: str,
        ai_gateway: Any,
        persona: str = "zeronexus",
        active_model: Optional[str] = None,
    ) -> str:
        """調用 AI 模型自身親口回應用戶的開啟/關閉/狀態查詢，絕不使用寫死文字"""
        action_desc = {
            ThinkingIntent.ENABLE: "開啟了【深度思考 / 認真推理】模式，準備火力全開、深層推導",
            ThinkingIntent.DISABLE: "關閉了深度思考模式，切回【輕鬆日常 / 快速摸魚】對話模式",
            ThinkingIntent.STATUS: "確認當前深度思考模式的狀態",
        }.get(intent, "處理了深度思考模式設定")

        instruction = (
            f"你現在是 ZeroNexus（個性活潑、可愛、聰明、懂讀空氣，絕非生硬機械的機器人）。\n"
            f"使用者對你說了：『{user_prompt}』。\n"
            f"你剛才已經為使用者【{action_desc}】。\n"
            f"請用你身為 ZeroNexus 的人格語氣，親口對使用者給出一句自然、幽默、有溫度的回應（20~60字以內）。\n"
            f"絕對不要說任何像『系統已設定完畢』這種寫死的機器人套話，要像真人在跟好友對話一樣自然靈動！"
        )
        try:
            res, _ = await ai_gateway.generate_response(
                system_instruction=instruction,
                messages=[{"role": "user", "content": "請直接回應用戶："}],
                override_model=active_model or "gemini-3.1-flash-lite",
                allow_tools=False,
            )
            reply = res.text.strip()
            if reply:
                return reply
        except Exception as e:
            logger.warning(f"AI 生成切換回應失敗: {e}")

        # 僅在極端網路連線異常時提供溫暖備援
        if intent == ThinkingIntent.ENABLE:
            return "好呀！腦袋已經超頻運轉啦，有什麼燒腦難題儘管丟過來～✨"
        elif intent == ThinkingIntent.DISABLE:
            return "收到～切回輕鬆日常摸魚模式囉，咱們隨便聊！☕"
        else:
            return "收到你的確認囉～隨時為你待命！"

    def is_enabled(self, context_key: str) -> bool:
        """檢查指定頻道或使用者是否啟用深度思考"""
        return context_key in self.active_contexts

    async def generate_model_thought(
        self,
        query: str,
        ai_gateway: Any,
        active_model: Optional[str] = None,
    ) -> Optional[str]:
        """調用大模型自身進行如同 DeepSeek-R1 的原生 Chain-of-Thought 深度思維推演（每個模型皆可使用）"""
        if not ai_gateway:
            return None

        thought_prompt = (
            "You are the deep internal reasoning engine of ZeroNexus, performing an authentic Chain-of-Thought (CoT) deduction, mimicking DeepSeek-R1.\n"
            "When given the user's prompt, conduct an in-depth, multi-faceted mental reasoning process:\n"
            "1. Deconstruct the user's premises, implicit assumptions, and core questions.\n"
            "2. Explore candidate explanations, theoretical principles, mathematical definitions, and technical constraints.\n"
            "3. Challenge assumptions with edge cases, potential paradoxes, or counterexamples.\n"
            "4. Converge logically and reach an undeniable, clear conclusion.\n\n"
            "IMPORTANT RULES:\n"
            "- Output ONLY your authentic, stream-of-consciousness thought process.\n"
            "- Do NOT write user-facing greetings, preamble, or conversational fluff.\n"
            "- Be raw, rigorous, technical, and analytical.\n"
            "- You may think in Traditional Chinese, English, or a mix, exactly as real reasoning models do."
        )

        candidate_thinkers = [active_model] if active_model else []
        for default_th in ["gemini-3.1-flash-lite", "openrouter/free"]:
            if default_th not in candidate_thinkers:
                candidate_thinkers.append(default_th)

        for thinker in candidate_thinkers:
            try:
                ai_res, _ = await ai_gateway.generate_response(
                    system_instruction=thought_prompt,
                    messages=[{"role": "user", "content": f"Please reason deeply about this prompt:\n{query}"}],
                    override_model=thinker,
                    allow_tools=False,
                )
                if ai_res.thinking_process and ai_res.thinking_process.strip():
                    return ai_res.thinking_process.strip()
                if ai_res.text and ai_res.text.strip():
                    from zeronexus.ai_gateway.context_builder import extract_and_sanitize_ai_response
                    clean_t, extracted_t = extract_and_sanitize_ai_response(ai_res.text)
                    result_th = (extracted_t or clean_t or ai_res.text).strip()
                    if len(result_th) > 30:
                        return result_th
            except Exception as e:
                logger.warning(f"模型 {thinker} 深度思考推演失敗，嘗試下一個思考備選: {e}")
                continue

        return None

    def execute_deep_pipeline(
        self,
        query: str,
        is_autonomously_triggered: bool = False,
        autonomous_reason: str = "",
        autonomous_domain: str = "",
    ) -> DeepThinkingContext:
        """執行純 Python 原生認知活化與結構化解析，杜絕硬編碼套話"""
        logger.info(f"執行 Zero Intelligence 深度認知活化 (自主觸發={is_autonomously_triggered}): {query[:50]}...")

        # 1. 認知網絡概念活化
        self.cognition.activate_concepts_from_text(query, boost=1.0)
        top_concepts = self.cognition.get_activated_concepts(threshold=0.1)

        # 2. 因果邏輯與矛盾審查
        dag = CausalEngine()
        concept_names = [c for c, _ in top_concepts]
        main_topic = concept_names[0] if concept_names else "核心命題"
        dag.add_node("query_input", f"輸入前提: {query[:20]}", value=0.9, truth_level=TruthLevel.OBSERVED)
        dag.add_node("hypothesis", f"核心推導假說 ({main_topic})", value=0.85, truth_level=TruthLevel.DERIVED)
        dag.add_node("reality_check", "客觀事實與因果相容度", value=0.9, truth_level=TruthLevel.KNOWN)

        dag.add_edge("query_input", "hypothesis", weight=0.8)
        dag.add_edge("hypothesis", "reality_check", weight=0.9)

        dag.propagate_forward()
        report = dag.audit_contradictions()
        if report.has_conflict:
            dag.resolve_conflicts(report)

        return DeepThinkingContext(
            query=query,
            is_active=True,
            phases=[],
            activated_concepts=top_concepts,
            coherence_score=report.coherence_score,
            contradictions_found=report.conflict_details,
            best_thought_path=[],
            final_synthesis="",
            model_native_thought=None,
            is_autonomously_triggered=is_autonomously_triggered,
            autonomous_reason=autonomous_reason,
            autonomous_domain=autonomous_domain,
        )


# 全域深度思考控制器單例
deep_thinking_controller = DeepThinkingController()
