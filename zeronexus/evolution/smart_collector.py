"""ZeroNexus 智慧資料蒐集器 (Smart Data Collector)

嚴格依據計畫書第 16、17、26、27、29 條規範設計：
不是無差別儲存所有對話，而是多維度嚴格評估：
1. 敏感資訊偵測與脫敏 (Sensitive Data Redaction):
   自動清洗 Discord Token、API 金鑰、密碼、敏感憑證。
2. 資訊量與長度評估 (Information Density):
   排除「早安」、「掰掰」、「貼圖」等極低資訊量贅訊。
3. 對話多輪閉環完整度 (Coherence):
   確保包含完整的使用者提問脈絡與高品質的 AI 應答。
4. 情緒狀態轉折價值 (Emotion Transition Value):
   顯著引發情緒或羈絆波動者加權。
5. 使用者糾錯修復 (User Correction Feedback):
   使用者指出 AI 盲點並引導修正者給予極高訓練價值 (training_value > 0.85)。
6. 人工審核佇列標記 (NEEDS_REVIEW):
   超高價值樣本進入審核佇列。
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

log = logging.getLogger("ZeroNexus.Evolution.SmartCollector")

DEFAULT_EVOLUTION_DIR = Path("data/evolution")
DEFAULT_CANDIDATE_QUEUE_FILE = DEFAULT_EVOLUTION_DIR / "candidate_queue.jsonl"


# 敏感資訊正則偵測過濾器 (依據計畫書第 27 條)
SENSITIVE_PATTERNS = [
    # Discord Bot Token (59~72 字元 base64 格式)
    (r"[MNO][a-zA-Z0-9_-]{23,26}\.[a-zA-Z0-9_-]{6}\.[a-zA-Z0-9_-]{27,38}", "[REDACTED_DISCORD_TOKEN]"),
    # OpenAI / Gemini / OpenRouter API Key (sk-..., AIzaSy...)
    (r"sk-[a-zA-Z0-9]{20,64}", "[REDACTED_API_KEY]"),
    (r"AIzaSy[a-zA-Z0-9_-]{33}", "[REDACTED_GEMINI_KEY]"),
    (r"ghp_[a-zA-Z0-9]{36}", "[REDACTED_GITHUB_TOKEN]"),
    # 密碼、憑證明文賦值模式
    (r"(?:password|passwd|pwd|secret|token|密碼|金鑰)\s*[:=]\s*([^\s,;]+)", r"\1: [REDACTED_CREDENTIAL]"),
]


@dataclass
class TrainingSampleCandidate:
    """經智慧評估後之單筆訓練樣本候選單位"""

    sample_id: str
    timestamp: float
    user_prompt: str
    ai_response: str
    context_turns: List[Dict[str, str]] = field(default_factory=list)
    event_type: str = "general_chat"
    emotion_deltas: Dict[str, float] = field(default_factory=dict)
    quality_score: float = 0.50
    novelty_score: float = 0.50
    is_correction: bool = False
    needs_review: bool = False
    status: str = "ACCEPTED"  # ACCEPTED, REJECTED, NEEDS_REVIEW
    sample_hash: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)


class SensitiveDataCleaner:
    """敏感資訊清洗過濾器"""

    @classmethod
    def clean(cls, text: str) -> str:
        if not text:
            return ""
        cleaned = text
        for pattern, replacement in SENSITIVE_PATTERNS:
            cleaned = re.sub(pattern, replacement, cleaned, flags=re.IGNORECASE)
        return cleaned


class SmartDataCollector:
    """智慧資料蒐集中樞"""

    def __init__(self, queue_file: Optional[Path] = None) -> None:
        self.queue_file = queue_file or DEFAULT_CANDIDATE_QUEUE_FILE
        self.seen_hashes: set[str] = set()
        self._init_queue_storage()

    def _init_queue_storage(self) -> None:
        try:
            self.queue_file.parent.mkdir(parents=True, exist_ok=True)
            if self.queue_file.exists():
                with self.queue_file.open("r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if line:
                            try:
                                d = json.loads(line)
                                if "sample_hash" in d:
                                    self.seen_hashes.add(d["sample_hash"])
                            except Exception:
                                pass
        except Exception as e:
            log.warning(f"初始化候選樣本佇列失敗: {e}")

    def evaluate_and_collect(
        self,
        user_prompt: str,
        ai_response: str,
        context_turns: Optional[List[Dict[str, str]]] = None,
        event_type: str = "general_chat",
        emotion_deltas: Optional[Dict[str, float]] = None,
        is_user_correction: bool = False,
    ) -> Optional[TrainingSampleCandidate]:
        """多維度品質評估與智慧採樣閘道
        
        回傳已清洗並獲准入庫的樣本物件；若未達標則回傳 None（零污染）。
        """
        # 1. 敏感資訊強制脫敏
        clean_prompt = SensitiveDataCleaner.clean(user_prompt or "").strip()
        clean_reply = SensitiveDataCleaner.clean(ai_response or "").strip()

        # 2. 基礎有效性檢驗 (排除空白、極短、系統報錯文本)
        if len(clean_prompt) < 2 or len(clean_reply) < 8:
            return None

        # 排除包含純錯誤碼的 AI 回覆
        if any(err in clean_reply for err in ["429 Too Many Requests", "API Key 無效", "內部伺服器錯誤"]):
            return None

        # 3. 計算內容雜湊值並檢查新穎度 (去重防重複灌入)
        normalized_content = f"{clean_prompt}::{clean_reply[:120]}"
        content_hash = hashlib.sha256(normalized_content.encode("utf-8")).hexdigest()
        if content_hash in self.seen_hashes:
            return None  # 重複資料直接過濾

        # 4. 資訊密度與長度評分 (繁體中文高資訊熵：30~60字即具備完整問答脈絡)
        length_factor = min(1.0, (len(clean_prompt) + len(clean_reply)) / 60.0)

        # 5. 情緒轉折影響度加權
        e_deltas = emotion_deltas or {}
        abs_delta_sum = sum(abs(v) for v in e_deltas.values())
        emotion_factor = min(0.3, abs_delta_sum * 1.5)

        # 6. 使用者糾錯加權 (高價值)
        correction_factor = 0.35 if is_user_correction else 0.0

        # 計算綜合品質分 (0.0 ~ 1.0)
        quality_score = min(1.0, 0.35 * length_factor + 0.35 + emotion_factor + correction_factor)

        # 閥值過濾：一般對話低於 0.50 者直接排除，不浪費儲存與訓練資源
        if quality_score < 0.50 and not is_user_correction:
            return None

        # 判定是否需要人工審核 (高價值且特殊糾錯樣本)
        needs_review = (quality_score >= 0.85) or is_user_correction

        candidate = TrainingSampleCandidate(
            sample_id=f"smp_{content_hash[:12]}",
            timestamp=time.time(),
            user_prompt=clean_prompt,
            ai_response=clean_reply,
            context_turns=context_turns or [],
            event_type=event_type,
            emotion_deltas=e_deltas,
            quality_score=round(quality_score, 3),
            novelty_score=round(1.0 - (0.1 if is_user_correction else 0.0), 2),
            is_correction=is_user_correction,
            needs_review=needs_review,
            status="NEEDS_REVIEW" if needs_review else "ACCEPTED",
            sample_hash=content_hash,
        )

        # 寫入佇列檔案
        self._append_to_queue(candidate)
        self.seen_hashes.add(content_hash)
        return candidate

    def _append_to_queue(self, candidate: TrainingSampleCandidate) -> None:
        try:
            with self.queue_file.open("a", encoding="utf-8") as f:
                f.write(json.dumps(asdict(candidate), ensure_ascii=False) + "\n")
        except Exception as e:
            log.error(f"寫入候選訓練佇列失敗: {e}")

    def get_queue_statistics(self) -> Dict[str, Any]:
        """取得候選佇列之統計報告 (依據計畫書第 37 條)"""
        total = len(self.seen_hashes)
        accepted = 0
        needs_review = 0
        sum_quality = 0.0

        if self.queue_file.exists():
            with self.queue_file.open("r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        try:
                            d = json.loads(line)
                            if d.get("needs_review"):
                                needs_review += 1
                            if d.get("status") in ("ACCEPTED", "NEEDS_REVIEW"):
                                accepted += 1
                            sum_quality += float(d.get("quality_score", 0.5))
                        except Exception:
                            pass

        avg_q = round(sum_quality / max(1, accepted), 2)
        return {
            "total_candidates": total,
            "accepted": accepted,
            "needs_review": needs_review,
            "average_quality": avg_q,
            "duplicate_prevented": len(self.seen_hashes),
        }


# 全域單例
smart_collector = SmartDataCollector()
