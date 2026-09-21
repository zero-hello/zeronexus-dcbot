"""ZeroNexus 全域臺灣在地繁體中文轉換與淨化引擎 (Taiwan Traditional Localization Engine)

功能特色：
1. 3100+ 常用簡繁字元快速對照轉換 (str.translate，微秒級執行)
2. 自動載入 taiwan_localization_lexicon.txt 詞庫，依照詞長長度優先替換
3. 支援 Markdown 程式碼區塊防護，避免污染程式語法關鍵字
4. 深度思考與推理推演歷程 (Chain-of-Thought) 100% 強制繁體化淨化
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
import re
from typing import Dict, List, Tuple

log = logging.getLogger("zeronexus.core.taiwan_translator")

BASE_DIR = Path(__file__).resolve().parent.parent
CHAR_MAP_FILE = BASE_DIR / "prompts" / "simp_to_trad_char_map.json"
LEXICON_FILE = BASE_DIR / "prompts" / "taiwan_localization_lexicon.txt"


class TaiwanTranslator:
    """全域臺灣繁體中文在地化轉換器。"""

    def __init__(self) -> None:
        self._char_map: Dict[str, str] = {}
        self._translation_table = str.maketrans({})
        self._phrase_pairs: List[Tuple[str, str]] = []
        self._initialized = False

    def initialize(self) -> None:
        """載入字元映射表與詞彙字典檔。"""
        if self._initialized:
            return

        # 1. 載入字元級簡繁映射表
        if CHAR_MAP_FILE.exists():
            try:
                with open(CHAR_MAP_FILE, "r", encoding="utf-8") as f:
                    self._char_map = json.load(f)
                self._translation_table = str.maketrans(self._char_map)
            except Exception as e:
                log.warning(f"Failed to load char map from {CHAR_MAP_FILE}: {e}")

        # 2. 載入詞彙級在地化替換表
        pairs: List[Tuple[str, str]] = []
        if LEXICON_FILE.exists():
            try:
                with open(LEXICON_FILE, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if not line or line.startswith("#") or line.startswith("["):
                            continue
                        if "->" in line:
                            parts = line.split("->", 1)
                            src = parts[0].strip()
                            dst = parts[1].strip()
                            # 嚴格防護：絕對禁止長度小於 2 的單字全域替換，杜絕單字破壞語意（如「位」->「位元」導致「各位元」、「那位元元」）
                            if len(src) < 2:
                                continue
                            # 清除說明備註（例如括號）
                            dst = re.sub(r"\(.*?\)", "", dst).strip()
                            if "/" in dst:
                                dst = dst.split("/")[0].strip()
                            if src and dst and src != dst and len(dst) >= 1:
                                pairs.append((src, dst))
            except Exception as e:
                log.warning(f"Failed to load lexicon from {LEXICON_FILE}: {e}")

        # 補充核心高頻詞組，確保最高優先級覆蓋
        core_pairs = [
            ("源代碼", "原始碼"),
            ("偽代碼", "虛擬碼"),
            ("代碼", "程式碼"),
            ("服務器", "伺服器"),
            ("客戶端", "用戶端"),
            ("用戶", "使用者"),
            ("內存", "記憶體"),
            ("顯存", "視訊記憶體"),
            ("硬盤", "硬碟"),
            ("默認", "預設"),
            ("網絡", "網路"),
            ("軟件", "軟體"),
            ("硬件", "硬體"),
            ("數組", "陣列"),
            ("字符串", "字串"),
            ("鏈表", "鏈結串列"),
            ("異步", "非同步"),
            ("多線程", "多執行緒"),
            ("線程", "執行緒"),
            ("多進程", "多行程"),
            ("進程", "行程"),
            ("調試", "除錯"),
            ("數據庫", "資料庫"),
            ("操作系統", "作業系統"),
            ("面向對象", "物件導向"),
            ("面向過程", "程序導向"),
            ("算法", "演算法"),
            ("複雜度", "複雜度"),
            ("接口", "介面"),
            ("函數", "函式"),
            ("變量", "變數"),
            ("常量", "常數"),
            ("參數", "參數"),
            ("遞歸", "遞迴"),
            ("循環", "迴圈"),
            ("回調", "回呼"),
            ("堆棧", "堆疊"),
            ("二維碼", "QR Code"),
            ("表情包", "貼圖"),
            ("土豆", "馬鈴薯"),
            ("西紅柿", "番茄"),
            ("菠蘿", "鳳梨"),
            ("獼猴桃", "奇異果"),
            ("三文魚", "鮭魚"),
            ("金槍魚", "鮪魚"),
            ("方便麵", "泡麵"),
            ("盒飯", "便當"),
            ("地鐵", "捷運"),
            ("公交車", "公車"),
            ("出租車", "計程車"),
            ("打車", "搭計程車"),
            ("立馬", "立刻"),
            ("屏幕", "螢幕"),
            ("視頻", "影片"),
            ("音頻", "音訊"),
            ("博客", "部落格"),
            ("點贊", "按讚"),
            ("支持", "支援"),
            ("項目", "專案"),
            ("優化", "最佳化"),
        ]
        all_pairs = list(dict.fromkeys(core_pairs + pairs))

        # 建立繁轉簡表，以便自動生成所有詞彙的簡體形式
        t2s_map = {v: k for k, v in self._char_map.items()}
        t2s_trans = str.maketrans(t2s_map)

        # 自動生成簡體與繁體雙向映射詞對
        expanded_pairs: List[Tuple[str, str]] = []
        for src, dst in all_pairs:
            expanded_pairs.append((src, dst))
            sim_src = src.translate(t2s_trans)
            if sim_src != src:
                expanded_pairs.append((sim_src, dst))

        # 去重並依來源長度由長到短排序
        phrase_dict: Dict[str, str] = {}
        for src, dst in expanded_pairs:
            if src not in phrase_dict:
                phrase_dict[src] = dst

        self._phrase_dict = phrase_dict
        sorted_keys = sorted(phrase_dict.keys(), key=len, reverse=True)
        self._phrase_regex = re.compile("|".join(re.escape(k) for k in sorted_keys)) if sorted_keys else None
        self._initialized = True
        log.info(f"TaiwanTranslator initialized: {len(self._char_map)} chars, {len(self._phrase_dict)} phrases.")

    def to_taiwan_traditional(self, text: str) -> str:
        """將輸入文字全面轉換為道地臺灣繁體中文。
        
        步驟：
        1. 保留 Markdown 程式碼區塊語法，避免損毀英文程式關鍵字。
        2. 以單遍正則掃描執行高階詞彙在地化替換（防重複與疊加替換）。
        3. 再執行字元級簡繁轉換（將所有剩餘簡體字全部翻轉為臺灣繁體字）。
        """
        if not text:
            return ""
        if not self._initialized:
            self.initialize()

        # 0. 防衛性修復：自動修正因歷史單字錯誤替換而殘留的「位元元+」或量詞位元污染
        text = re.sub(r"位元{2,}", "位", text)
        text = re.sub(r"(那|這|各|哪|每|一|幾|第[一二三四五六七八九十0-9]+|兩)位元(?![組率位長運])", r"\1位", text)
        text = re.sub(r"數位元(?![組率位長運])", "數位", text)

        segments = re.split(r"(```[\s\S]*?```|`[^`\n]+`)", text)
        result = []
        for seg in segments:
            # 程式碼區塊內部僅做字元映射（保留英文語法關鍵字與變數）
            if seg.startswith("```") or seg.startswith("`"):
                result.append(seg.translate(self._translation_table))
            else:
                s = seg
                # 1. 單遍正則詞彙替換（從左至右線性匹配最長詞，絕不二次重複替換）
                if self._phrase_regex:
                    s = self._phrase_regex.sub(lambda m: self._phrase_dict[m.group(0)], s)
                # 2. 全文字元簡轉繁
                s = s.translate(self._translation_table)
                result.append(s)

        return "".join(result)

    def sanitize_thinking_process(self, thinking: str) -> str:
        """深度思考思維鏈專屬淨化器：
        
        1. 將大模型原生輸出的英文思維開場與結構標題轉化為臺灣繁體標題。
        2. 將原生簡體思維推演文字 100% 強制轉換為道地臺灣繁體中文。
        """
        if not thinking or not thinking.strip():
            return ""
        if not self._initialized:
            self.initialize()

        s = thinking.strip()

        # 大模型英文思維慣用語替換
        english_thought_replacements = [
            (r"(?i)\bthinking\s+process\s*[:：]", "## 🧠 思維推演歷程："),
            (r"(?i)\bmy\s+thoughts\s+on\s+([^\n:]+)", r"關於「\1」的深層推演"),
            (r"(?i)\b(?:1\.|step\s*1[:：]?)\s*(?:understand|analy[zs]e)\s+(?:the\s+)?(?:user(?:'s)?\s+)?(?:prompt|query|intent|question)[:：]?", "1. 解析使用者核心意圖："),
            (r"(?i)\b(?:2\.|step\s*2[:：]?)\s*(?:retrieve|check|analy[zs]e)\s+(?:context|memory|history|background)[:：]?", "2. 檢索歷史脈絡與情感記憶："),
            (r"(?i)\b(?:3\.|step\s*3[:：]?)\s*(?:consider|evaluate)\s+(?:empathy|emotion|tone|feelings?)[:：]?", "3. 評估使用者情緒狀態與同理心深度："),
            (r"(?i)\b(?:4\.|step\s*4[:：]?)\s*(?:formulate|plan|draft)\s+(?:the\s+)?(?:response|answer|reply)[:：]?", "4. 組織深刻共鳴與具體建設性之解答："),
            (r"(?i)\b(?:5\.|step\s*5[:：]?)\s*(?:verify|review|final\s+check)[:：]?", "5. 審查繁體中文標準與高情商語氣："),
            (r"(?i)\buser\s+prompt\s*[:：]", "使用者提問："),
            (r"(?i)\buser\s+emotion\s*[:：]", "使用者情緒狀態："),
            (r"(?i)\bcore\s+intent\s*[:：]", "核心提問焦點："),
            (r"(?i)\bcontext\s+analysis\s*[:：]", "情境與脈絡分析："),
            (r"(?i)\breasoning\s*[:：]", "因果邏輯推理："),
            (r"(?i)\bconclusion\s*[:：]", "推演結論："),
            (r"(?i)\bfinal\s+output\s*[:：]", "最終輸出規劃："),
            (r"(?i)\bresponse\s+strategy\s*[:：]", "應對陪伴策略："),
        ]
        for pat, repl in english_thought_replacements:
            s = re.sub(pat, repl, s)

        return self.to_taiwan_traditional(s)


taiwan_translator = TaiwanTranslator()
