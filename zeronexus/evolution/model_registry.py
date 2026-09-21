"""ZeroNexus 獨立模型工件與 Model Registry (Model Artifact & Lineage)

嚴格依據計畫書第 21、22、23、24、33、34、35、42 條規範設計：
1. 每個模型都是完全自包含的獨立工件 (Independent Model Artifact):
   data/models/zero_model_XXX/
   ├── model.onnx
   ├── config.json
   ├── metadata.json
   └── evaluation.json
2. 完整模型血統 (Model Lineage & Provenance):
   永久紀錄：model_id, dataset_id, dataset_version, training_run_id,
   framework, architecture, base_model, evaluation_result。
3. Model Registry 全域註冊表：
   管理生產部署狀態 (PRODUCTION, SHADOW, TESTING, ARCHIVED)。
4. 零停機安全回滾機制 (Instant Rollback):
   若新模型出現回歸異常，秒級切回上一代穩定模型。
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

log = logging.getLogger("ZeroNexus.Evolution.ModelRegistry")

DEFAULT_MODELS_DIR = Path("data/models")
DEFAULT_REGISTRY_FILE = DEFAULT_MODELS_DIR / "registry.json"


@dataclass
class ModelMetadata:
    """獨立模型工件之血統溯源與元數據"""

    model_id: str                         # 如 zero_model_001
    model_version: str = "1.0.0"
    dataset_id: str = ""                  # 溯源源頭資料集 (如 zero_dataset_001)
    dataset_sha256: str = ""              # 源頭資料集之防偽雜湊指紋
    training_run_id: str = ""             # 訓練執行序號
    framework: str = "PyTorch -> ONNX"
    architecture: str = "DeltaEmotionMLP"
    status: str = "TESTING"               # PRODUCTION, SHADOW, TESTING, ARCHIVED
    created_at: float = field(default_factory=time.time)
    evaluation_scores: Dict[str, float] = field(default_factory=dict)
    lineage_parent_model: Optional[str] = None  # 上一代模型 ID


class ModelArtifact:
    """單一獨立模型工件封裝"""

    def __init__(self, model_dir: Path) -> None:
        self.model_dir = model_dir
        self.metadata_file = model_dir / "metadata.json"
        self.config_file = model_dir / "config.json"
        self.onnx_file = model_dir / "model.onnx"
        self.eval_file = model_dir / "evaluation.json"
        self.metadata = self._load_metadata()

    def _load_metadata(self) -> ModelMetadata:
        if self.metadata_file.exists():
            try:
                raw = json.loads(self.metadata_file.read_text(encoding="utf-8"))
                return ModelMetadata(**raw)
            except Exception as e:
                log.warning(f"讀取模型元數據失敗: {e}")
        return ModelMetadata(model_id=self.model_dir.name)

    def save_metadata(self) -> None:
        self.metadata_file.write_text(
            json.dumps(asdict(self.metadata), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )


class ModelRegistry:
    """模型註冊中樞與血統管理器"""

    def __init__(self, root_dir: Optional[Path] = None) -> None:
        self.root_dir = root_dir or DEFAULT_MODELS_DIR
        self.registry_file = self.root_dir / "registry.json"
        self.root_dir.mkdir(parents=True, exist_ok=True)
        self.registry_data = self._load_registry()

    def _load_registry(self) -> Dict[str, Any]:
        if self.registry_file.exists():
            try:
                return json.loads(self.registry_file.read_text(encoding="utf-8"))
            except Exception as e:
                log.warning(f"讀取全域模型註冊表失敗: {e}")
        return {
            "current_production_model": None,
            "shadow_model": None,
            "models": {},
            "history": [],
        }

    def _save_registry(self) -> None:
        try:
            temp = self.registry_file.with_suffix(".tmp")
            temp.write_text(
                json.dumps(self.registry_data, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            temp.replace(self.registry_file)
        except Exception as e:
            log.error(f"儲存全域模型註冊表失敗: {e}")

    def register_model_artifact(
        self,
        model_id: str,
        dataset_id: str,
        dataset_sha256: str,
        training_run_id: str,
        architecture: str = "DeltaEmotionMLP",
        evaluation_scores: Optional[Dict[str, float]] = None,
    ) -> ModelArtifact:
        """登記並建立新的獨立模型工件"""
        target_dir = self.root_dir / model_id
        target_dir.mkdir(parents=True, exist_ok=True)

        artifact = ModelArtifact(target_dir)
        artifact.metadata.model_id = model_id
        artifact.metadata.dataset_id = dataset_id
        artifact.metadata.dataset_sha256 = dataset_sha256
        artifact.metadata.training_run_id = training_run_id
        artifact.metadata.architecture = architecture
        artifact.metadata.evaluation_scores = evaluation_scores or {}
        artifact.metadata.lineage_parent_model = self.registry_data.get("current_production_model")
        artifact.save_metadata()

        # 登記進全域註冊表
        self.registry_data["models"][model_id] = asdict(artifact.metadata)
        self._save_registry()
        log.info(f"🏛️ 已登記新獨立模型工件: {model_id} (溯源資料集: {dataset_id})")
        return artifact

    def promote_to_production(self, model_id: str) -> bool:
        """將指定模型升級為 Production 線上生產模型"""
        target_dir = self.root_dir / model_id
        if not target_dir.exists():
            log.error(f"找不到模型目錄: {model_id}")
            return False

        old_prod = self.registry_data.get("current_production_model")
        if old_prod and old_prod in self.registry_data["models"]:
            self.registry_data["models"][old_prod]["status"] = "ARCHIVED"

        self.registry_data["current_production_model"] = model_id
        if model_id in self.registry_data["models"]:
            self.registry_data["models"][model_id]["status"] = "PRODUCTION"

        self.registry_data["history"].append({
            "action": "PROMOTE",
            "model_id": model_id,
            "previous_model": old_prod,
            "timestamp": time.time(),
        })
        self._save_registry()
        log.info(f"🚀 模型 {model_id} 已正式晉升為生產環境 (Production)！(前一代: {old_prod})")
        return True

    def rollback_to_previous(self) -> Tuple[bool, Optional[str]]:
        """一鍵安全回滾至上一代模型 (Rollback)"""
        current = self.registry_data.get("current_production_model")
        if not current:
            return False, "目前無上線中之生產模型。"

        # 自歷史紀錄尋找上一個穩定版本
        candidates = [
            h["previous_model"] for h in reversed(self.registry_data.get("history", []))
            if h.get("action") == "PROMOTE" and h.get("previous_model")
        ]

        if not candidates:
            return False, "無可回滾之歷史模型版本。"

        target_model = candidates[0]
        log.warning(f"⚠️ 正在執行模型回滾：自 {current} ➔ 回滾至 {target_model}")
        success = self.promote_to_production(target_model)
        if success:
            self.registry_data["history"].append({
                "action": "ROLLBACK",
                "from_model": current,
                "to_model": target_model,
                "timestamp": time.time(),
            })
            self._save_registry()
            return True, target_model
        return False, "回滾切換失敗。"

    def get_lineage_report(self) -> str:
        """生成模型血統追溯圖與狀態總覽"""
        curr = self.registry_data.get("current_production_model", "無 (基底離線陣列)")
        shadow = self.registry_data.get("shadow_model", "無")
        models = self.registry_data.get("models", {})

        lines = [
            "# 🏛️ ZeroNexus Model Registry 全域註冊總覽",
            f"- **線上生產模型 (Production)**: `{curr}`",
            f"- **影子測試模型 (Shadow)**: `{shadow}`",
            f"- **已註冊獨立模型總數**: `{len(models)}`",
            "",
            "### 🧬 模型血統溯源樹 (Lineage Provenance):",
        ]
        if not models:
            lines.append("（目前尚無自訓模型工件，由底層 6 核離線神經模型陣列承載運行）")
        for mid, m in models.items():
            lines.append(
                f"- **[{m.get('status')}] `{mid}`** ➔ 來源資料集: `{m.get('dataset_id')}` "
                f"| 訓練序號: `{m.get('training_run_id')}` | 架構: `{m.get('architecture')}`"
            )

        return "\n".join(lines)


# 全域單例
model_registry = ModelRegistry()
