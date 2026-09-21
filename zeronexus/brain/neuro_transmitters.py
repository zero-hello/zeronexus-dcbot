"""ZeroNexus 本地生物神經遞質狀態機 (Biological Neurotransmitter State Machine)

模擬人類大腦邊緣系統之神經化學傳導機制：
- 多巴胺 (Dopamine)：好奇心、興奮度、探索欲與獎勵預期。
- 血清素 (Serotonin)：情緒穩定度、滿足感、平和與同理心。
- 皮質醇 (Cortisol)：壓力值、受傷防備心、焦慮與警覺度。
- 催產素 (Oxytocin)：親密羈絆值、信任感與依戀度（針對特定使用者個別積累）。
- 生理精力 (Energy)：體能狀態，隨互動微量消耗，隨睡眠與離線休息自然回充。

所有數值均遵循生理半衰期（Leaky Integrator）自然代謝演算法，絕非隨機跳動。
"""

import json
import logging
import math
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Dict, Optional

log = logging.getLogger("ZeroNexus.Brain.Neuro")

DEFAULT_BRAIN_DATA_DIR = Path("data/brain")
DEFAULT_NEURO_STATE_FILE = DEFAULT_BRAIN_DATA_DIR / "neuro_state.json"


@dataclass
class NeuroChemicalProfile:
    """單一核心實體之神經化學狀態資料結構"""

    # 4 大核心神經遞質 (0.0 ~ 100.0)
    dopamine: float = 55.0  # 基準值：適度好奇與積極
    serotonin: float = 65.0  # 基準值：情緒平穩健康
    cortisol: float = 12.0  # 基準值：低壓力狀態
    energy: float = 100.0  # 基準值：精力充沛

    # 各使用者專屬催產素（親密度與信任度）映射表：user_id -> float (0.0 ~ 100.0)
    oxytocin_bonds: Dict[str, float] = field(default_factory=dict)

    # 基因基準錨點（Baseline Homeostasis Anchor）
    baseline_dopamine: float = 55.0
    baseline_serotonin: float = 65.0
    baseline_cortisol: float = 12.0

    # 時間追蹤
    last_update_timestamp: float = field(default_factory=time.time)
    creation_timestamp: float = field(default_factory=time.time)


class NeuroTransmitterEngine:
    """本地生物神經遞質物理演算引擎"""

    def __init__(self, state_file: Optional[Path] = None) -> None:
        self.state_file = state_file or DEFAULT_NEURO_STATE_FILE
        self.profile = self._load_or_initialize()

    def _load_or_initialize(self) -> NeuroChemicalProfile:
        """從本地磁碟載入神經狀態，若不存在則初始化"""
        try:
            if self.state_file.exists():
                raw_text = self.state_file.read_text(encoding="utf-8").strip()
                if raw_text:
                    data = json.loads(raw_text)
                    profile = NeuroChemicalProfile(
                        dopamine=float(data.get("dopamine", 55.0)),
                        serotonin=float(data.get("serotonin", 65.0)),
                        cortisol=float(data.get("cortisol", 12.0)),
                        energy=float(data.get("energy", 100.0)),
                        oxytocin_bonds=data.get("oxytocin_bonds", {}),
                        baseline_dopamine=float(data.get("baseline_dopamine", 55.0)),
                        baseline_serotonin=float(data.get("baseline_serotonin", 65.0)),
                        baseline_cortisol=float(data.get("baseline_cortisol", 12.0)),
                        last_update_timestamp=float(data.get("last_update_timestamp", time.time())),
                        creation_timestamp=float(data.get("creation_timestamp", time.time())),
                    )
                    log.info("成功載入本地生物神經狀態檔案。")
                    return profile
        except Exception as e:
            log.warning(f"讀取神經狀態檔案失敗，將重置為健康初始狀態: {e}")

        new_profile = NeuroChemicalProfile(last_update_timestamp=time.time())
        self._persist(new_profile)
        return new_profile

    def _persist(self, profile: Optional[NeuroChemicalProfile] = None) -> None:
        """安全寫入本地檔案"""
        target = profile or self.profile
        try:
            self.state_file.parent.mkdir(parents=True, exist_ok=True)
            temp_file = self.state_file.with_suffix(".tmp")
            temp_file.write_text(json.dumps(asdict(target), indent=2, ensure_ascii=False), encoding="utf-8")
            temp_file.replace(self.state_file)
        except Exception as e:
            log.error(f"持久化神經遞質狀態至磁碟時發生錯誤: {e}")

    def apply_homeostasis_decay(self) -> None:
        """生理半衰期代謝（Leaky Integrator 衰減方程式）

        隨著真實世界時間的流逝，神經遞質濃度會依指數規律逐漸代謝、回到基因基準線（Homeostasis）。
        同時在無人打擾時，體力精力會隨時間自動恢復。
        """
        now = time.time()
        elapsed_seconds = max(0.0, now - self.profile.last_update_timestamp)
        if elapsed_seconds < 1.0:
            return

        elapsed_minutes = elapsed_seconds / 60.0

        # 多巴胺半衰期約 45 分鐘（興奮會慢慢回歸平靜）
        dopamine_decay_rate = 1.0 - math.exp(-0.015 * elapsed_minutes)
        self.profile.dopamine += (self.profile.baseline_dopamine - self.profile.dopamine) * dopamine_decay_rate

        # 皮質醇半衰期約 60 分鐘（委屈與壓力消退較慢）
        cortisol_decay_rate = 1.0 - math.exp(-0.011 * elapsed_minutes)
        self.profile.cortisol += (self.profile.baseline_cortisol - self.profile.cortisol) * cortisol_decay_rate

        # 血清素半衰期約 90 分鐘（心情放鬆程度）
        serotonin_decay_rate = 1.0 - math.exp(-0.008 * elapsed_minutes)
        self.profile.serotonin += (self.profile.baseline_serotonin - self.profile.serotonin) * serotonin_decay_rate

        # 體力精力恢復：每閒置休息 1 小時恢復約 15% 精力
        energy_recovery = 0.25 * elapsed_minutes
        self.profile.energy = min(100.0, self.profile.energy + energy_recovery)

        self.profile.last_update_timestamp = now
        self._persist()

    def get_oxytocin(self, user_id: str) -> float:
        """取得特定使用者的催產素親密度（預設為 25.0 初見友善值）"""
        return float(self.profile.oxytocin_bonds.get(str(user_id), 25.0))

    def stimulate(
        self,
        user_id: str,
        delta_dopamine: float = 0.0,
        delta_serotonin: float = 0.0,
        delta_cortisol: float = 0.0,
        delta_oxytocin: float = 0.0,
        energy_cost: float = 1.5,
    ) -> Dict[str, float]:
        """接收感測器之神經刺激脈衝，即時更新化學遞質濃度"""
        self.apply_homeostasis_decay()

        # 施加增量
        self.profile.dopamine = max(0.0, min(100.0, self.profile.dopamine + delta_dopamine))
        self.profile.serotonin = max(0.0, min(100.0, self.profile.serotonin + delta_serotonin))
        self.profile.cortisol = max(0.0, min(100.0, self.profile.cortisol + delta_cortisol))
        self.profile.energy = max(5.0, min(100.0, self.profile.energy - energy_cost))

        # 更新與特定使用者的專屬親密度
        uid_str = str(user_id)
        current_bond = self.get_oxytocin(uid_str)
        new_bond = max(0.0, min(100.0, current_bond + delta_oxytocin))
        self.profile.oxytocin_bonds[uid_str] = round(new_bond, 2)

        self.profile.last_update_timestamp = time.time()
        self._persist()

        return {
            "dopamine": round(self.profile.dopamine, 2),
            "serotonin": round(self.profile.serotonin, 2),
            "cortisol": round(self.profile.cortisol, 2),
            "oxytocin": round(new_bond, 2),
            "energy": round(self.profile.energy, 2),
        }

    def sleep_and_restore(self) -> None:
        """進入深度睡眠固化模式：清除皮質醇壓力，回滿精力"""
        self.profile.energy = 100.0
        self.profile.cortisol = self.profile.baseline_cortisol
        self.profile.serotonin = max(self.profile.baseline_serotonin, 70.0)
        self.profile.last_update_timestamp = time.time()
        self._persist()
        log.info("大腦完成深度睡眠與荷爾蒙恆定自癒。")
