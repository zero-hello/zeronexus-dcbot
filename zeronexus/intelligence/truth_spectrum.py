"""Zero Intelligence 真理光譜模組 (Truth Spectrum Engine).

本模組落實 Zero Intelligence 之第一核心公理：
- 執行時期真實（Runtime Truth）> 模型猜測（Model Guess）。
- 工具觀測結果（OBSERVED）> 模型記憶與假設。
- 嚴禁 MODEL_CLAIM -> RUNTIME_TRUTH（模型口頭宣稱不等於真實事實）。
- 嚴格提供真實性六級光譜、衝突降級處置與斷言安全檢查。
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional, Sequence


class TruthLevel(str, Enum):
    """真實性六級光譜枚舉。
    
    置信度由高至低嚴格排序：
    - OBSERVED: 真實工具觀察到的，置信度最高（執行時期直接觀測）
    - DERIVED: 由確定事實推導或邏輯計算得出的
    - KNOWN: 系統執行時期內建之確定事實
    - HYPOTHESIS: 假設推測，待驗證
    - ESTIMATE: 粗估數據
    - UNKNOWN: 未知
    """

    OBSERVED = "OBSERVED"
    DERIVED = "DERIVED"
    KNOWN = "KNOWN"
    HYPOTHESIS = "HYPOTHESIS"
    ESTIMATE = "ESTIMATE"
    UNKNOWN = "UNKNOWN"

    @property
    def rank(self) -> int:
        """取得該真實性等級的權重排名數值。數值越高代表置信度越確定。"""
        _RANKS: dict[str, int] = {
            "OBSERVED": 60,
            "DERIVED": 50,
            "KNOWN": 40,
            "HYPOTHESIS": 30,
            "ESTIMATE": 20,
            "UNKNOWN": 10,
        }
        return _RANKS[self.value]

    def __lt__(self, other: Any) -> bool:
        if not isinstance(other, TruthLevel):
            return NotImplemented
        return self.rank < other.rank

    def __le__(self, other: Any) -> bool:
        if not isinstance(other, TruthLevel):
            return NotImplemented
        return self.rank <= other.rank

    def __gt__(self, other: Any) -> bool:
        if not isinstance(other, TruthLevel):
            return NotImplemented
        return self.rank > other.rank

    def __ge__(self, other: Any) -> bool:
        if not isinstance(other, TruthLevel):
            return NotImplemented
        return self.rank >= other.rank


class TruthViolationError(Exception):
    """真實性斷言違反或未達標準例外。"""


class TruthConflictError(Exception):
    """同級事實矛盾且無法自動調解例外。"""


@dataclass
class TruthFact:
    """代表帶有真實性等級認證的原子事實資料結構。

    屬性:
        key: 事實鍵識別碼（例如 'member_count', 'channel_status' 等）。
        value: 事實對應之真實內容。
        level: 真實性等級（TruthLevel）。
        source: 事實來源標記（例如 'discord_rest_api', 'calculator_engine', 'user_input'）。
        timestamp: 事實產生之 Unix 時間戳記。
        evidence_token: 依據憑證（如工具回傳之憑證雜湊或呼叫識別碼）。
        metadata: 附帶之後設資料字典。
    """

    key: str
    value: Any
    level: TruthLevel
    source: str
    timestamp: float = field(default_factory=time.time)
    evidence_token: Optional[str] = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def is_verified(self) -> bool:
        """檢查此事實是否為最高置信度之工具觀測事實 (OBSERVED)。"""
        return self.level == TruthLevel.OBSERVED

    def is_reliable(self, min_level: TruthLevel = TruthLevel.KNOWN) -> bool:
        """檢查此事實是否達到指定的最低可信度標準。"""
        return self.level >= min_level

    @property
    def rank(self) -> int:
        """取得事實所屬真實性等級的權重排名數值。"""
        return self.level.rank

    def downgrade(self, new_level: TruthLevel, reason: str = "") -> TruthFact:
        """將事實降級為更低之置信等級。

        注意：嚴禁逆向透過降級函式進行不當提權。
        """
        if new_level > self.level:
            raise ValueError(
                f"不可透過 downgrade 提升真實性等級（目前: {self.level.value}，目標: {new_level.value}）"
            )
        new_meta = dict(self.metadata)
        history = list(new_meta.get("downgrade_history", []))
        history.append({
            "from_level": self.level.value,
            "to_level": new_level.value,
            "reason": reason,
            "timestamp": time.time(),
        })
        new_meta["downgrade_history"] = history

        return TruthFact(
            key=self.key,
            value=self.value,
            level=new_level,
            source=self.source,
            timestamp=self.timestamp,
            evidence_token=self.evidence_token,
            metadata=new_meta,
        )

    def to_dict(self) -> dict[str, Any]:
        """將事實序列化為字典格式。"""
        return {
            "key": self.key,
            "value": self.value,
            "level": self.level.value,
            "source": self.source,
            "timestamp": self.timestamp,
            "evidence_token": self.evidence_token,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TruthFact:
        """自字典反序列化為事實實例。"""
        level_val = data["level"]
        level = TruthLevel(level_val) if isinstance(level_val, str) else level_val
        return cls(
            key=data["key"],
            value=data["value"],
            level=level,
            source=data["source"],
            timestamp=data.get("timestamp", time.time()),
            evidence_token=data.get("evidence_token"),
            metadata=data.get("metadata", {}),
        )


def compare_facts(fact_a: TruthFact, fact_b: TruthFact) -> dict[str, Any]:
    """比對兩個事實並分析其一致性與主導權。

    回傳比對結果字典，包含是否衝突、主導事實及等級差距。
    """
    keys_match = fact_a.key == fact_b.key
    values_match = fact_a.value == fact_b.value
    is_conflict = keys_match and not values_match

    dominant_fact: Optional[TruthFact] = None
    if fact_a.level > fact_b.level:
        dominant_fact = fact_a
    elif fact_b.level > fact_a.level:
        dominant_fact = fact_b
    elif values_match:
        # 同等級且值相同，以最新觀測者為主
        dominant_fact = fact_a if fact_a.timestamp >= fact_b.timestamp else fact_b

    return {
        "key": fact_a.key,
        "keys_match": keys_match,
        "values_match": values_match,
        "is_conflict": is_conflict,
        "dominant_fact": dominant_fact,
        "rank_difference": fact_a.rank - fact_b.rank,
    }


def resolve_conflict(
    fact_a: TruthFact,
    fact_b: TruthFact,
    strict: bool = False,
    fallback_to_lower: bool = True,
) -> TruthFact:
    """依據真實性公理調解兩個事實間的衝突。

    核心公理：
    1. 執行時期真實（Runtime Truth）> 模型猜測（Model Guess）。
    2. 等級較高者覆蓋等級較低者。
    3. 若等級相同但值不同（同級衝突）：
       - 若 strict=True，直接引發 TruthConflictError。
       - 若 fallback_to_lower=True，啟動衝突降級（Downgrade），以防未驗證臆測造成危害。
    """
    if fact_a.key != fact_b.key:
        raise ValueError(f"無法比對不同鍵的事實：'{fact_a.key}' vs '{fact_b.key}'")

    # 若值相同，回傳等級高者
    if fact_a.value == fact_b.value:
        return fact_a if fact_a.level >= fact_b.level else fact_b

    # 值不同時，若等級有高下，依公理以高者為準
    if fact_a.level > fact_b.level:
        result_meta = dict(fact_a.metadata)
        result_meta["superseded_fact"] = fact_b.to_dict()
        result_meta["resolution_note"] = (
            f"高等級事實 [{fact_a.level.value}] 依真理公理覆蓋低等級事實 [{fact_b.level.value}]"
        )
        return TruthFact(
            key=fact_a.key,
            value=fact_a.value,
            level=fact_a.level,
            source=fact_a.source,
            timestamp=fact_a.timestamp,
            evidence_token=fact_a.evidence_token,
            metadata=result_meta,
        )

    if fact_b.level > fact_a.level:
        result_meta = dict(fact_b.metadata)
        result_meta["superseded_fact"] = fact_a.to_dict()
        result_meta["resolution_note"] = (
            f"高等級事實 [{fact_b.level.value}] 依真理公理覆蓋低等級事實 [{fact_a.level.value}]"
        )
        return TruthFact(
            key=fact_b.key,
            value=fact_b.value,
            level=fact_b.level,
            source=fact_b.source,
            timestamp=fact_b.timestamp,
            evidence_token=fact_b.evidence_token,
            metadata=result_meta,
        )

    # 等級完全相同且值矛盾
    if strict:
        raise TruthConflictError(
            f"同等級事實衝突：鍵 '{fact_a.key}'，等級均為 [{fact_a.level.value}]，"
            f"但值分別為 {fact_a.value} ({fact_a.source}) 與 {fact_b.value} ({fact_b.source})"
        )

    if not fallback_to_lower:
        # 非嚴格模式且不降級時，以時間戳最新者為準
        return fact_a if fact_a.timestamp >= fact_b.timestamp else fact_b

    # 執行降級梯隊
    downgrade_map: dict[TruthLevel, TruthLevel] = {
        TruthLevel.OBSERVED: TruthLevel.HYPOTHESIS,
        TruthLevel.DERIVED: TruthLevel.HYPOTHESIS,
        TruthLevel.KNOWN: TruthLevel.HYPOTHESIS,
        TruthLevel.HYPOTHESIS: TruthLevel.ESTIMATE,
        TruthLevel.ESTIMATE: TruthLevel.UNKNOWN,
        TruthLevel.UNKNOWN: TruthLevel.UNKNOWN,
    }
    target_level = downgrade_map.get(fact_a.level, TruthLevel.UNKNOWN)

    conflict_meta = {
        "conflict_detected": True,
        "conflicting_facts": [fact_a.to_dict(), fact_b.to_dict()],
        "downgrade_reason": f"同級事實衝突，由 [{fact_a.level.value}] 自動降級至 [{target_level.value}]",
        "resolved_at": time.time(),
    }

    # 以最新時間點的值作為降級基準，但等級標記為降級後等級
    base_fact = fact_a if fact_a.timestamp >= fact_b.timestamp else fact_b
    return TruthFact(
        key=base_fact.key,
        value=base_fact.value,
        level=target_level,
        source=f"conflict_resolved({fact_a.source},{fact_b.source})",
        timestamp=time.time(),
        evidence_token=None,  # 衝突後憑證失效，需重新驗證
        metadata=conflict_meta,
    )


def downgrade_on_conflict(
    facts: Sequence[TruthFact], target_level: Optional[TruthLevel] = None
) -> TruthFact:
    """對一組相互矛盾的事實進行集體降級。

    將所有衝突事實之歷程收納於後設資料中，並降級為低置信等級（預設為 UNKNOWN）。
    """
    if not facts:
        raise ValueError(" facts 序列不可為空")

    first_key = facts[0].key
    if any(f.key != first_key for f in facts):
        raise ValueError("降級處理之事實必須具有相同的鍵")

    chosen_level = target_level or TruthLevel.UNKNOWN
    latest_fact = max(facts, key=lambda f: f.timestamp)

    conflict_history = [f.to_dict() for f in facts]
    new_metadata = {
        "conflict_downgraded": True,
        "original_facts_count": len(facts),
        "facts_history": conflict_history,
        "downgrade_timestamp": time.time(),
    }

    return TruthFact(
        key=first_key,
        value=latest_fact.value,
        level=chosen_level,
        source="collective_downgrade",
        timestamp=time.time(),
        evidence_token=None,
        metadata=new_metadata,
    )


def assert_truth(
    fact: TruthFact,
    min_level: TruthLevel = TruthLevel.KNOWN,
    expected_value: Any = None,
) -> bool:
    """執行真實性斷言安全檢查。

    參數:
        fact: 待檢查之事實。
        min_level: 預期之最低真實性等級（預設為 KNOWN）。
        expected_value: 預期之事實值（若提供則進行值比對）。

    例外:
        TruthViolationError: 若等級不足或值不符合預期。
    """
    if fact.level < min_level:
        raise TruthViolationError(
            f"真實性斷言失敗：事實 '{fact.key}' 之等級為 [{fact.level.value}] (權重 {fact.rank})，"
            f"未達要求之最低等級 [{min_level.value}] (權重 {min_level.rank})"
        )

    if expected_value is not None and fact.value != expected_value:
        raise TruthViolationError(
            f"真實性斷言失敗：事實 '{fact.key}' 之值與預期不符。"
            f"預期: {expected_value}，實際: {fact.value}"
        )

    return True


def verify_runtime_truth(claim_value: Any, runtime_fact: TruthFact) -> bool:
    """驗證模型或外部宣稱是否符合執行時期真實（Runtime Truth）。

    嚴禁 MODEL_CLAIM -> RUNTIME_TRUTH：
    1. 用於驗證的 runtime_fact 必須是真實工具觀測到的最高置信等級 (OBSERVED)。
    2. 宣稱值必須與執行時期觀測值嚴格相符。
    """
    if runtime_fact.level < TruthLevel.OBSERVED:
        raise TruthViolationError(
            f"公理違規：驗證依據必須為最高置信度之工具觀測事實 [OBSERVED]，"
            f"實際提供之等級為 [{runtime_fact.level.value}]，嚴禁將未經工具驗證之資料視為執行時期真理！"
        )

    if claim_value != runtime_fact.value:
        raise TruthViolationError(
            f"真實性檢驗未通過：模型宣稱值 '{claim_value}' 與執行時期觀測真實 '{runtime_fact.value}' 不一致！"
        )

    return True
