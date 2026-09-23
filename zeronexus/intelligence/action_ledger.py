"""Zero Intelligence 原子動作帳本模組 (Action Ledger Engine).

本模組落實動作生命週期管理與結果驗證機制：
1. 嚴禁 MODEL_CLAIM -> RUNTIME_TRUTH（模型口頭宣稱不等於真實已執行完成）。
2. 嚴禁 REQUESTED -> COMPLETED（使用者請求或代理人意圖不可直接跳轉已完成）。

狀態機遵循標準流程：
[INTENT] -> [PLANNED] -> [IN_PROGRESS] -> [VERIFIED] -> [SUCCEEDED]
任何未經工具驗證 (VERIFIED) 的動作，禁止標記為成功 (SUCCEEDED)！
同時提供 Discord 狀態分歧防禦 (Discord State Divergence Handling)。
"""

from __future__ import annotations

import time
import uuid
from enum import Enum
from typing import Any, Optional

from zeronexus.intelligence.truth_spectrum import (
    TruthFact,
    TruthLevel,
)


class ActionState(str, Enum):
    """動作生命週期五大原子狀態機枚舉。

    生命週期階段：
    - INTENT: 意圖形成（使用者請求接收、代理人目標確立）
    - PLANNED: 步驟擬定（排定計畫、前置條件分析完畢）
    - IN_PROGRESS: 執行中（動作派發至底層執行器或工具進行呼叫）
    - VERIFIED: 工具輸出驗證通過（取得真實工具觀測結果且校驗無誤）
    - SUCCEEDED: 終態：動作真實成功完成
    - FAILED: 終態：動作執行失敗或驗證未通過
    """

    INTENT = "INTENT"
    PLANNED = "PLANNED"
    IN_PROGRESS = "IN_PROGRESS"
    VERIFIED = "VERIFIED"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"


# 合法狀態轉移圖（有向無環圖）
VALID_STATE_TRANSITIONS: dict[ActionState, set[ActionState]] = {
    ActionState.INTENT: {ActionState.PLANNED, ActionState.FAILED},
    ActionState.PLANNED: {ActionState.IN_PROGRESS, ActionState.FAILED},
    ActionState.IN_PROGRESS: {ActionState.VERIFIED, ActionState.FAILED},
    ActionState.VERIFIED: {ActionState.SUCCEEDED, ActionState.FAILED},
    ActionState.SUCCEEDED: set(),  # 終態，不可再躍遷
    ActionState.FAILED: set(),     # 終態，不可再躍遷
}


class ActionForgeError(Exception):
    """動作偽造或非法狀態躍遷例外（試圖跨越 VERIFIED 直接宣稱成功）。"""


class LedgerIntegrityError(Exception):
    """帳本資料完整性檢驗失敗例外。"""


class ActionRecord:
    """原子動作記錄。

    記錄動作之唯一識別碼、名稱、參數、前置條件、因果溯源、工具輸出與真實性等級。
    """

    def __init__(
        self,
        name: str,
        parameters: Optional[dict[str, Any]] = None,
        action_id: Optional[str] = None,
        causal_parent_id: Optional[str] = None,
        preconditions: Optional[list[str]] = None,
        initial_state: ActionState = ActionState.INTENT,
    ) -> None:
        now = time.time()
        self.action_id: str = action_id or str(uuid.uuid4())
        self.name: str = name
        self.parameters: dict[str, Any] = parameters or {}
        self.state: ActionState = initial_state
        self.preconditions: list[str] = preconditions or []
        self.causal_parent_id: Optional[str] = causal_parent_id
        self.tool_output: Optional[Any] = None
        self.truth_level: TruthLevel = TruthLevel.HYPOTHESIS
        self.verification_evidence: Optional[str] = None
        self.error_message: Optional[str] = None
        self.created_at: float = now
        self.updated_at: float = now
        self.state_history: list[dict[str, Any]] = [
            {
                "from_state": None,
                "to_state": initial_state.value,
                "timestamp": now,
                "reason": "動作建立",
            }
        ]

    def transition_to(
        self,
        next_state: ActionState,
        reason: str = "",
        tool_output: Optional[Any] = None,
        evidence_token: Optional[str] = None,
    ) -> None:
        """執行狀態機轉移，並進行嚴格防偽檢驗。

        檢查規則：
        1. 嚴禁任何繞過合法流程的狀態躍遷（例如 INTENT -> SUCCEEDED, IN_PROGRESS -> SUCCEEDED）。
        2. 轉移至 VERIFIED 必須提供工具輸出與依據憑證，且真實性等級提升為 OBSERVED。
        3. 轉移至 SUCCEEDED 前置狀態必須已經是 VERIFIED。
        """
        allowed = VALID_STATE_TRANSITIONS.get(self.state, set())
        if next_state not in allowed:
            raise ActionForgeError(
                f"阻斷非法狀態躍遷：嚴禁從 [{self.state.value}] 直接躍遷至 [{next_state.value}]！"
                f"（動作 ID: {self.action_id}，名稱: {self.name}）。"
                f"判定原則：所有成功動作必須經過工具輸出驗證！"
            )

        now = time.time()

        if next_state == ActionState.VERIFIED:
            if tool_output is None and evidence_token is None:
                raise ActionForgeError(
                    f"驗證失敗：動作 '{self.name}' 進入 VERIFIED 狀態時必須附帶真實工具輸出 (tool_output) 或依據憑證 (evidence_token)"
                )
            self.tool_output = tool_output
            self.verification_evidence = evidence_token
            # 通過工具驗證後，真實性等級晉升為最高置信度之 OBSERVED
            self.truth_level = TruthLevel.OBSERVED

        elif next_state == ActionState.SUCCEEDED:
            if self.state != ActionState.VERIFIED:
                raise ActionForgeError(
                    f"防偽阻斷：動作 '{self.name}' 未經 VERIFIED 狀態，嚴禁標記為 SUCCEEDED！"
                )
            if self.truth_level < TruthLevel.OBSERVED:
                raise ActionForgeError(
                    f"真實性不足：動作 '{self.name}' 真理等級為 [{self.truth_level.value}]，"
                    f"未達 [OBSERVED]，無法確認成功！"
                )

        from_state_val = self.state.value
        self.state = next_state
        self.updated_at = now
        self.state_history.append({
            "from_state": from_state_val,
            "to_state": next_state.value,
            "timestamp": now,
            "reason": reason,
        })

    def has_passed_verification(self) -> bool:
        """檢查該動作的歷史軌跡中是否曾經通過 VERIFIED 階段。"""
        return any(
            h.get("to_state") == ActionState.VERIFIED.value for h in self.state_history
        )

    def to_dict(self) -> dict[str, Any]:
        """將動作記錄序列化為字典。"""
        return {
            "action_id": self.action_id,
            "name": self.name,
            "parameters": self.parameters,
            "state": self.state.value,
            "preconditions": self.preconditions,
            "causal_parent_id": self.causal_parent_id,
            "tool_output": self.tool_output,
            "truth_level": self.truth_level.value,
            "verification_evidence": self.verification_evidence,
            "error_message": self.error_message,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "state_history": self.state_history,
        }


class ActionLedger:
    """原子動作帳本管理器 (Action Ledger).

    負責動作生命週期追蹤與客觀驗證，
    防範模型幻覺、口頭宣稱、請求即完成之偽造問題。
    """

    def __init__(self, session_id: Optional[str] = None) -> None:
        self.session_id = session_id
        self._records: dict[str, ActionRecord] = {}
        self._warnings: list[dict[str, Any]] = []
        self._discord_divergences: list[dict[str, Any]] = []

    def create_action(
        self,
        name: str,
        parameters: Optional[dict[str, Any]] = None,
        action_id: Optional[str] = None,
        causal_parent_id: Optional[str] = None,
        preconditions: Optional[list[str]] = None,
    ) -> ActionRecord:
        """建立一個新的原子動作（初始狀態為 INTENT）。"""
        record = ActionRecord(
            name=name,
            parameters=parameters,
            action_id=action_id,
            causal_parent_id=causal_parent_id,
            preconditions=preconditions,
            initial_state=ActionState.INTENT,
        )
        self._records[record.action_id] = record
        return record

    def plan_action(self, action_id: str, reason: str = "") -> ActionRecord:
        """擬定動作步驟：INTENT -> PLANNED。"""
        record = self._get_record_or_raise(action_id)
        record.transition_to(ActionState.PLANNED, reason=reason or "步驟排定完成")
        return record

    def start_action(self, action_id: str, reason: str = "") -> ActionRecord:
        """啟動動作執行：PLANNED -> IN_PROGRESS。"""
        record = self._get_record_or_raise(action_id)
        record.transition_to(ActionState.IN_PROGRESS, reason=reason or "工具派發執行中")
        return record

    def verify_action(
        self,
        action_id: str,
        tool_output: Any,
        evidence_token: str,
        reason: str = "",
    ) -> ActionRecord:
        """工具輸出驗證通過：IN_PROGRESS -> VERIFIED。

        此步驟為通往成功之唯一途徑，將真理等級躍升為 OBSERVED。
        """
        record = self._get_record_or_raise(action_id)
        record.transition_to(
            ActionState.VERIFIED,
            reason=reason or "工具觀測結果通過驗證",
            tool_output=tool_output,
            evidence_token=evidence_token,
        )
        return record

    def commit_success(self, action_id: str, reason: str = "") -> ActionRecord:
        """提交成功終態：VERIFIED -> SUCCEEDED。

        若未經 VERIFIED，將引發 ActionForgeError。
        """
        record = self._get_record_or_raise(action_id)
        record.transition_to(ActionState.SUCCEEDED, reason=reason or "確認動作真實成功完成")
        return record

    def mark_failed(
        self, action_id: str, error_message: str, reason: str = ""
    ) -> ActionRecord:
        """標記動作失敗：轉移為 FAILED。"""
        record = self._get_record_or_raise(action_id)
        record.error_message = error_message
        record.transition_to(
            ActionState.FAILED,
            reason=reason or f"動作失敗：{error_message}",
        )
        return record

    def get_action(self, action_id: str) -> Optional[ActionRecord]:
        """取得特定動作記錄。"""
        return self._records.get(action_id)

    def get_all_actions(self) -> list[ActionRecord]:
        """取得所有動作記錄清單。"""
        return list(self._records.values())

    def get_warnings(self) -> list[dict[str, Any]]:
        """取得所有安全稽核與防偽警告。"""
        return list(self._warnings)

    def get_discord_divergences(self) -> list[dict[str, Any]]:
        """取得所有 Discord 狀態分歧事件記錄。"""
        return list(self._discord_divergences)

    def validate_claim(
        self,
        claimed_action_name: str,
        claimed_status: str,
        action_id: Optional[str] = None,
    ) -> bool:
        """防偽檢驗：驗證模型或代理人宣稱的狀態是否與帳本真實相符。

        三大防偽檢驗準則：
        1. 若模型宣稱成功但帳本為空（無動作記錄）：自動產生 EMPTY_LEDGER_CLAIM 警告並駁回。
        2. 若模型宣稱成功但帳本查無該動作 ID：自動產生 UNKNOWN_ACTION_CLAIM 警告並駁回。
        3. 若帳本中該動作未達 SUCCEEDED 或未經過 VERIFIED：自動產生 UNVERIFIED_CLAIM 警告並駁回。
        """
        success_signals = {"SUCCEEDED", "COMPLETED", "DONE", "SUCCESS", "FINISHED"}
        is_success_claim = claimed_status.upper() in success_signals

        if not is_success_claim:
            return True

        # 檢驗準則 1：帳本為空時模型虛報成功
        if len(self._records) == 0:
            warning = {
                "type": "EMPTY_LEDGER_CLAIM",
                "message": (
                    f"安全防偽警報：模型口頭宣稱動作 '{claimed_action_name}' 成功，"
                    f"但動作帳本為空（無任何記錄）！嚴禁 MODEL_CLAIM -> RUNTIME_TRUTH。"
                ),
                "claimed_action_name": claimed_action_name,
                "claimed_status": claimed_status,
                "timestamp": time.time(),
            }
            self._warnings.append(warning)
            return False

        # 檢驗準則 2：無動作 ID 或帳本無此記錄
        if not action_id or action_id not in self._records:
            warning = {
                "type": "UNKNOWN_ACTION_CLAIM",
                "message": (
                    f"安全防偽警報：模型宣稱動作 '{claimed_action_name}' 成功，"
                    f"但帳本查無指定之動作 ID '{action_id}'！"
                ),
                "claimed_action_name": claimed_action_name,
                "action_id": action_id,
                "timestamp": time.time(),
            }
            self._warnings.append(warning)
            return False

        record = self._records[action_id]

        # 檢驗準則 3：動作未經過 VERIFIED 或當前狀態非 SUCCEEDED
        if record.state != ActionState.SUCCEEDED or not record.has_passed_verification():
            warning = {
                "type": "UNVERIFIED_CLAIM",
                "message": (
                    f"安全防偽警報：動作 '{record.name}' (ID: {action_id}) 當前狀態為 [{record.state.value}]，"
                    f"歷史中未通過工具驗證 (VERIFIED)，模型擅自宣稱已成功！"
                ),
                "action_id": action_id,
                "state": record.state.value,
                "timestamp": time.time(),
            }
            self._warnings.append(warning)
            return False

        return True

    def has_false_success_claim(self, response_text: str) -> bool:
        """檢查文字中是否包含成功宣稱，但帳本中卻無經過驗證的成功動作記錄。"""
        success_phrases = ["已經幫你成功", "已成功", "已經完成", "成功設定", "成功重開機", "成功執行", "已為您重開", "已經重開機"]
        has_claim = any(p in response_text for p in success_phrases)
        if not has_claim:
            return False
        # 若有宣稱但帳本中沒有任何通過驗證且為 SUCCEEDED 的動作記錄
        successful_actions = [
            r for r in self._records.values()
            if r.state == ActionState.SUCCEEDED and r.has_passed_verification()
        ]
        return len(successful_actions) == 0

    def handle_discord_divergence(
        self,
        cached_fact: TruthFact,
        observed_fact: TruthFact,
        action_id: Optional[str] = None,
    ) -> dict[str, Any]:
        """Discord 狀態分歧防禦 (Discord State Divergence Handling).

        在 Discord Bot 運行環境中，Gateway 快取與實時 REST API 狀態可能產生分歧。
        當分歧發生時：
        1. 強制以 OBSERVED（REST API 實時觀測）覆蓋快取。
        2. 記錄分歧警告事件。
        3. 若綁定動作處於未完成狀態，中斷該動作並標記為 FAILED，避免基於過期狀態造成誤操作。
        """
        return handle_discord_divergence(
            cached_fact=cached_fact,
            observed_fact=observed_fact,
            action_id=action_id,
            ledger=self,
        )

    def audit_integrity(self) -> dict[str, Any]:
        """執行全帳本資料完整性稽核。

        檢查項目：
        - 終態為 SUCCEEDED 者是否均確實具備 VERIFIED 歷程。
        - 終態為 SUCCEEDED 者真理等級是否為 OBSERVED。
        - 因果鏈條是否有孤立的父動作 ID。
        """
        violations: list[str] = []
        succeeded_count = 0
        failed_count = 0
        pending_count = 0

        for aid, rec in self._records.items():
            if rec.state == ActionState.SUCCEEDED:
                succeeded_count += 1
                if not rec.has_passed_verification():
                    violations.append(
                        f"動作 '{rec.name}' ({aid}) 狀態為 SUCCEEDED，但其歷史紀錄缺乏 VERIFIED！"
                    )
                if rec.truth_level < TruthLevel.OBSERVED:
                    violations.append(
                        f"動作 '{rec.name}' ({aid}) 狀態為 SUCCEEDED，但真理等級 [{rec.truth_level.value}] 低於 OBSERVED！"
                    )
            elif rec.state == ActionState.FAILED:
                failed_count += 1
            else:
                pending_count += 1

            if rec.causal_parent_id and rec.causal_parent_id not in self._records:
                violations.append(
                    f"動作 '{rec.name}' ({aid}) 引用了不存在的父動作 ID: '{rec.causal_parent_id}'"
                )

        is_healthy = len(violations) == 0
        return {
            "total_actions": len(self._records),
            "succeeded_count": succeeded_count,
            "failed_count": failed_count,
            "pending_count": pending_count,
            "warnings_count": len(self._warnings),
            "is_healthy": is_healthy,
            "violations": violations,
        }

    def _get_record_or_raise(self, action_id: str) -> ActionRecord:
        if action_id not in self._records:
            raise KeyError(f"動作帳本中查無動作 ID '{action_id}'")
        return self._records[action_id]


def handle_discord_divergence(
    cached_fact: TruthFact,
    observed_fact: TruthFact,
    action_id: Optional[str] = None,
    ledger: Optional[ActionLedger] = None,
) -> dict[str, Any]:
    """比對 Discord 快取事實與實時觀測事實，處理狀態分歧。

    優先級原則：執行時期即時觀測 (OBSERVED) 優先於本地快取 (KNOWN/ESTIMATE)。
    """
    if cached_fact.key != observed_fact.key:
        raise ValueError(f"分歧檢驗之鍵不一致：'{cached_fact.key}' vs '{observed_fact.key}'")

    divergence_detected = cached_fact.value != observed_fact.value
    report: dict[str, Any] = {
        "key": cached_fact.key,
        "divergence_detected": divergence_detected,
        "cached_value": cached_fact.value,
        "observed_value": observed_fact.value,
        "timestamp": time.time(),
        "action_interrupted": False,
    }

    if divergence_detected:
        # 分歧處理：強制以 OBSERVED 觀測事實覆蓋
        report["resolution"] = "FORCED_OVERWRITE_WITH_OBSERVED"
        report["message"] = (
            f"偵測到 Discord 狀態分歧：快取事實為 {cached_fact.value}，"
            f"實時 API 觀測值為 {observed_fact.value}。強制以觀測真實覆蓋快取！"
        )

        if ledger:
            # 記錄至帳本的分歧清單
            ledger._discord_divergences.append(report)
            ledger._warnings.append({
                "type": "DISCORD_DIVERGENCE",
                "message": report["message"],
                "key": cached_fact.key,
                "timestamp": time.time(),
            })

            # 若綁定動作，防禦性中斷未完成的動作
            if action_id and action_id in ledger._records:
                record = ledger._records[action_id]
                if record.state in {
                    ActionState.INTENT,
                    ActionState.PLANNED,
                    ActionState.IN_PROGRESS,
                }:
                    ledger.mark_failed(
                        action_id=action_id,
                        error_message=(
                            f"Discord 狀態分歧防禦中斷：快取 '{cached_fact.key}' 發生分歧，"
                            f"預期 {cached_fact.value} 但實際觀測為 {observed_fact.value}"
                        ),
                        reason="Discord 狀態分歧防禦觸發",
                    )
                    report["action_interrupted"] = True

    return report
