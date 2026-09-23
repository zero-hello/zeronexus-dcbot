"""ZeroNexus 全域封鎖與黑名單管理系統 (Global Blacklist System)

提供造物主 (Zero) 與管理系統嚴格的全域封鎖功能：
1. 封鎖特定使用者無法調用任何 ZeroNexus AI 回應、生活情報或指令功能。
2. 遭封鎖使用者發起互動時，卡片直接轉為紅色封鎖狀態並提示申訴管道。
3. 支援 Web Panel 進行全域封鎖之查詢、新增與解除。
"""

import json
import logging
import os
import time
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional

log = logging.getLogger("ZeroNexus.Security.Blacklist")


@dataclass
class BlacklistRecord:
    """全域封鎖記錄"""

    user_id: str
    user_name: str = ""
    reason: str = "違反使用條款或濫用機器人資源"
    banned_at: str = field(default_factory=lambda: time.strftime("%Y-%m-%d %H:%M:%S"))
    banned_by: str = "Zero"


class GlobalBlacklistManager:
    """全域黑名單總控管理器"""

    def __init__(self, storage_path: str = "data/security/global_blacklist.json") -> None:
        self.storage_path = storage_path
        self._blacklist: Dict[str, BlacklistRecord] = {}
        self._load()

    def is_banned(self, user_id: Any) -> bool:
        """檢查特定使用者是否已被全域封鎖"""
        uid = str(user_id).strip()
        return uid in self._blacklist

    def get_ban_info(self, user_id: Any) -> Optional[Dict[str, Any]]:
        """取得特定使用者的封鎖詳細資訊"""
        uid = str(user_id).strip()
        record = self._blacklist.get(uid)
        return asdict(record) if record else None

    def ban_user(
        self,
        user_id: Any,
        reason: str = "違反使用條款或濫用機器人資源",
        user_name: str = "",
        banned_by: str = "Zero",
    ) -> Dict[str, Any]:
        """將使用者加入全域黑名單"""
        uid = str(user_id).strip()
        # 保護造物主 ID 絕對不可被封鎖
        if uid == "1514971711739789352":
            log.warning("嘗試封鎖造物主 Zero，操作已自動拒絕！")
            raise ValueError("不可封鎖造物主 Zero！")

        record = BlacklistRecord(
            user_id=uid,
            user_name=user_name.strip(),
            reason=reason.strip() or "違反使用條款或濫用機器人資源",
            banned_at=time.strftime("%Y-%m-%d %H:%M:%S"),
            banned_by=banned_by.strip() or "Zero",
        )
        self._blacklist[uid] = record
        self._save()
        log.warning(f"🚫 [全域封鎖] 使用者 {uid} ({user_name}) 已被加入全域黑名單！原因: {reason}")
        return asdict(record)

    def unban_user(self, user_id: Any) -> bool:
        """將使用者從全域黑名單中移除"""
        uid = str(user_id).strip()
        if uid in self._blacklist:
            del self._blacklist[uid]
            self._save()
            log.info(f"✔ [解除封鎖] 使用者 {uid} 已成功從全域黑名單中解除。")
            return True
        return False

    def list_banned_users(self) -> List[Dict[str, Any]]:
        """列出所有遭到全域封鎖的使用者清單"""
        return [asdict(r) for r in self._blacklist.values()]

    def _save(self) -> None:
        """持久化寫入本地儲存庫"""
        try:
            folder = os.path.dirname(self.storage_path)
            if folder:
                os.makedirs(folder, exist_ok=True)
            with open(self.storage_path, "w", encoding="utf-8") as f:
                data = {k: asdict(v) for k, v in self._blacklist.items()}
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            log.error(f"儲存全域黑名單資料庫失敗: {e}")

    def _load(self) -> None:
        """從本地儲存庫載入黑名單資料"""
        if os.path.exists(self.storage_path):
            try:
                with open(self.storage_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if isinstance(data, dict):
                        self._blacklist = {k: BlacklistRecord(**v) for k, v in data.items()}
            except Exception as e:
                log.warning(f"載入全域黑名單資料庫失敗: {e}，初始化為空。")
                self._blacklist = {}


# 全域單例
global_blacklist = GlobalBlacklistManager()
