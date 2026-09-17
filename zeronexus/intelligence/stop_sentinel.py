"""Zero Intelligence 終止智能與迴圈熔斷器 (Stop Sentinel & Circuit Breaker).

核心精神：
即時監控 ReAct 執行歷程中的工具調用序列，守護系統穩定度與資源：
1. 死迴圈檢測 (Loop Detection)：連續 2 次以上發送完全相同的搜尋 Query 或參數相同的工具調用，即刻熔斷。
2. 震盪循環檢測 (Oscillating Loop)：檢測 A -> B -> A -> B 交互調用死迴圈並即刻阻斷。
3. 收斂檢驗 (Convergence Check)：若連續多步未產生新觀察 (No New Information)，強制終止並優雅回覆已知結果。
4. 提供安全熔斷保護與容錯總結輸出 (Safe Response)。
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set

from zeronexus.intelligence.complexity_router import ComplexityLevel


@dataclass
class ToolCallRecord:
    """單步工具呼叫歷程記錄。"""

    step: int
    tool_name: str
    parameters: Dict[str, Any]
    observation: Any
    timestamp: float = field(default_factory=time.time)
    signature: str = ""
    observation_hash: str = ""

    def __post_init__(self) -> None:
        if not self.signature:
            self.signature = self._generate_signature(self.tool_name, self.parameters)
        if not self.observation_hash:
            self.observation_hash = self._generate_observation_hash(self.observation)

    @staticmethod
    def _generate_signature(tool_name: str, parameters: Dict[str, Any]) -> str:
        """根據工具名稱與標準化參數生成唯一識別簽名。"""
        # 過濾不影響語意的非確定性參數（如 guild, channel 等內部參照）
        clean_params = {
            k: v for k, v in parameters.items()
            if k not in {"guild", "channel", "user", "interaction"}
        }
        # 序列化字典，key 嚴格排序
        raw_json = json.dumps(clean_params, sort_keys=True, ensure_ascii=False, default=str)
        return f"{tool_name}:{raw_json}"

    @staticmethod
    def _generate_observation_hash(observation: Any) -> str:
        """計算觀察結果之內容雜湊。"""
        if observation is None:
            return "empty:none"
        raw_str = json.dumps(observation, sort_keys=True, ensure_ascii=False, default=str)
        if not raw_str.strip() or raw_str in ('""', "{}", "[]", "null"):
            return "empty:blank"
        return hashlib.sha256(raw_str.encode("utf-8")).hexdigest()[:16]


@dataclass(frozen=True)
class SentinelDecision:
    """終止智能哨兵之判定結果。"""

    should_stop: bool
    reason: str
    is_loop: bool = False
    is_converged: bool = False
    circuit_broken: bool = False
    safe_response: Optional[str] = None


class StopSentinel:
    """終止智能與迴圈熔斷器核心實例。"""

    def __init__(
        self,
        max_identical_calls: int = 2,
        no_new_info_threshold: int = 2,
        max_steps: int = 8,
        complexity: Optional[ComplexityLevel] = None,
    ) -> None:
        """初始化終止哨兵。

        Args:
            max_identical_calls: 連續執行完全相同調用之熔斷門檻（預設 2 次即熔斷）。
            no_new_info_threshold: 連續無新資訊產生之收斂門檻（預設 2 步）。
            max_steps: 最大允許執行步數上限。
            complexity: 若有指定任務複雜度，自動自適應配置對應步數。
        """
        self.max_identical_calls = max_identical_calls
        self.no_new_info_threshold = no_new_info_threshold
        self.max_steps = self._resolve_max_steps(max_steps, complexity)
        self.complexity = complexity
        self._history: List[ToolCallRecord] = []
        self._seen_signatures: List[str] = []
        self._seen_observation_hashes: Set[str] = set()

    @staticmethod
    def _resolve_max_steps(default_steps: int, complexity: Optional[ComplexityLevel]) -> int:
        """根據複雜度自適應微調最大步數。"""
        if complexity == ComplexityLevel.SIMPLE:
            return 0
        if complexity == ComplexityLevel.MEDIUM:
            return min(default_steps, 3)
        if complexity == ComplexityLevel.COMPLEX:
            return max(default_steps, 6)
        if complexity == ComplexityLevel.EXTREME:
            return max(default_steps, 10)
        return default_steps

    def record_and_evaluate(
        self,
        tool_name: str,
        parameters: Optional[Dict[str, Any]] = None,
        observation: Any = None,
    ) -> SentinelDecision:
        """記錄單步工具呼叫並即時執行熔斷與收斂判定。"""
        params = parameters or {}
        step_idx = len(self._history) + 1
        record = ToolCallRecord(
            step=step_idx,
            tool_name=tool_name,
            parameters=params,
            observation=observation,
        )
        self._history.append(record)
        self._seen_signatures.append(record.signature)

        # 1. 檢測死迴圈（連續相同調用）
        if self._detect_identical_loop():
            safe_resp = self.generate_safe_response(
                "偵測到重複發起相同參數之查詢，已即刻熔斷以防止無效循環。"
            )
            return SentinelDecision(
                should_stop=True,
                reason=f"觸發死迴圈熔斷：連續 {self.max_identical_calls} 次執行完全相同的工具呼叫 ({tool_name})",
                is_loop=True,
                circuit_broken=True,
                safe_response=safe_resp,
            )

        # 2. 檢測震盪死迴圈（A -> B -> A -> B）
        if self._detect_oscillating_loop():
            safe_resp = self.generate_safe_response(
                "偵測到工具呼叫在兩種狀態間往復震盪，已啟動安全熔斷。"
            )
            return SentinelDecision(
                should_stop=True,
                reason="觸發震盪循環熔斷：工具呼叫陷入雙重交替死迴圈 (Oscillating Loop)",
                is_loop=True,
                circuit_broken=True,
                safe_response=safe_resp,
            )

        # 3. 檢測資訊收斂（連續未獲取新資訊）
        if self._detect_convergence():
            safe_resp = self.generate_safe_response(
                "當前觀察情資已達到飽和或未獲取增量資訊，已為您整合現有成果。"
            )
            return SentinelDecision(
                should_stop=True,
                reason=f"觸發收斂終止：連續 {self.no_new_info_threshold} 步未獲取有效新觀察 (No New Information)",
                is_converged=True,
                circuit_broken=False,
                safe_response=safe_resp,
            )

        # 4. 檢測執行步數預算超限
        if len(self._history) >= self.max_steps:
            safe_resp = self.generate_safe_response(
                f"任務已達本階段最大允許步數上限 ({self.max_steps} 步)，已終止探索並回傳已知總結。"
            )
            return SentinelDecision(
                should_stop=True,
                reason=f"達到最大步數上限 ({self.max_steps} 步)，觸發安全預算熔斷",
                circuit_broken=True,
                safe_response=safe_resp,
            )

        # 未觸發任何終止條件，可繼續推進
        return SentinelDecision(
            should_stop=False,
            reason="工具調用序列健康，允許繼續執行",
        )

    def _detect_identical_loop(self) -> bool:
        """檢驗歷史末端是否連續出現相同簽名。"""
        if len(self._history) < self.max_identical_calls:
            return False
        recent_sigs = [r.signature for r in self._history[-self.max_identical_calls:]]
        # 若最後 N 個簽名全部相同，即為死迴圈
        return len(set(recent_sigs)) == 1

    def _detect_oscillating_loop(self) -> bool:
        """檢驗是否呈現 [A, B, A, B] 的交替震盪循環（長度 >= 4）。"""
        if len(self._history) < 4:
            return False
        sigs = [r.signature for r in self._history[-4:]]
        # sigs[0] == sigs[2] 且 sigs[1] == sigs[3]，且 sigs[0] != sigs[1]
        return sigs[0] == sigs[2] and sigs[1] == sigs[3] and sigs[0] != sigs[1]

    def _detect_convergence(self) -> bool:
        """檢驗連續多步是否未產生實質新資訊。"""
        if len(self._history) < self.no_new_info_threshold:
            return False

        recent_records = self._history[-self.no_new_info_threshold:]

        # 情況 A：連續多步的 observation_hash 皆相同
        recent_hashes = [r.observation_hash for r in recent_records]
        if len(set(recent_hashes)) == 1:
            return True

        # 情況 B：連續多步均為空白/空結構/無資訊
        all_empty = all(r.observation_hash.startswith("empty:") for r in recent_records)
        if all_empty:
            return True

        # 情況 C：連續多步均回傳錯誤物件
        all_errors = all(
            isinstance(r.observation, dict) and "error" in r.observation
            for r in recent_records
        )
        if all_errors:
            return True

        return False

    def generate_safe_response(self, context_notice: str = "") -> str:
        """當熔斷或收斂發生時，優雅整合已知的成功資訊，避免使用者面對空白或例外。"""
        lines: List[str] = []
        if context_notice:
            lines.append(f"⚠️ **【執行狀態說明】**：{context_notice}\n")

        valid_observations: List[Dict[str, Any]] = []
        for r in self._history:
            obs = r.observation
            if obs and not (isinstance(obs, dict) and "error" in obs):
                valid_observations.append({
                    "step": r.step,
                    "tool": r.tool_name,
                    "data": obs,
                })

        if valid_observations:
            lines.append("📋 **【已獲取之已知事實摘要】**：")
            for item in valid_observations:
                lines.append(f"- **步驟 {item['step']} ({item['tool']})**：")
                obs_data = item["data"]
                if isinstance(obs_data, dict):
                    # 擷取關鍵鍵值
                    sample_kvs = [
                        f"{k}: {v}" for k, v in list(obs_data.items())[:4]
                    ]
                    lines.append(f"  - 觀測資料：{', '.join(sample_kvs)}")
                else:
                    lines.append(f"  - 觀測資料：{str(obs_data)[:120]}")
            lines.append("\n系統已依據上述已驗證之觀測結果完成推論。")
        else:
            lines.append("ℹ️ 探索過程中尚未取得有效外部觀測數據，已為您轉由通用常識模型進行直覺回答。")

        return "\n".join(lines)

    @property
    def history(self) -> List[ToolCallRecord]:
        """取得目前完整的調用記錄清單。"""
        return list(self._history)

    def reset(self) -> None:
        """重置哨兵內部歷程。"""
        self._history.clear()
        self._seen_signatures.clear()
        self._seen_observation_hashes.clear()


stop_sentinel = StopSentinel()

__all__ = [
    "ToolCallRecord",
    "SentinelDecision",
    "StopSentinel",
    "stop_sentinel",
]
