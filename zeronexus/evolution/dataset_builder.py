"""ZeroNexus 獨立資料集工件建造器 (Dataset Builder & Artifact System)

嚴格依據計畫書第 18、19、20、25、28、41 條規範設計：
1. 每個 Dataset 都是完全自包含的獨立目錄 (Independent Artifact):
   data/datasets/zero_dataset_XXX/
   ├── dataset.jsonl
   ├── metadata.json
   ├── statistics.json
   ├── README.md
   └── (可選特徵 embeddings/)
2. 完整的生命週期狀態機：
   COLLECTING ➔ THRESHOLD_REACHED ➔ FREEZE ➔ VALIDATED ➔ TRAINED ➔ ARCHIVED
3. 嚴格防竄改校驗：
   Freeze 瞬間計算整份 dataset.jsonl 之 SHA-256 數位指紋，後續訓練與評估強制校驗雜湊。
4. 獨立備份、獨立驗證、獨立重新訓練。
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

log = logging.getLogger("ZeroNexus.Evolution.DatasetBuilder")

DEFAULT_DATASETS_DIR = Path("data/datasets")


@dataclass
class DatasetMetadata:
    """獨立資料集工件之全生命週期元數據"""

    dataset_id: str                      # 如 zero_dataset_001
    dataset_version: str = "1.0.0"       # 語意版本號
    status: str = "COLLECTING"           # COLLECTING, THRESHOLD_REACHED, FREEZE, VALIDATED, TRAINED, ARCHIVED
    created_at: float = field(default_factory=time.time)
    closed_at: Optional[float] = None
    sample_count: int = 0
    source: str = "ZeroNexus Smart Collector"
    collector_version: str = "v1.5.5"
    schema_version: str = "2.0.0"
    quality_score_avg: float = 0.0
    novelty_score_avg: float = 0.0
    content_sha256: str = ""             # Freeze 時鎖定的完整性指紋
    embedding_model: str = "bge_small_zh"
    tags: List[str] = field(default_factory=lambda: ["taiwan_conversational", "emotion_transition"])


class DatasetArtifact:
    """單一獨立資料集工件封裝"""

    def __init__(self, dataset_dir: Path) -> None:
        self.dataset_dir = dataset_dir
        self.metadata_file = dataset_dir / "metadata.json"
        self.data_file = dataset_dir / "dataset.jsonl"
        self.stats_file = dataset_dir / "statistics.json"
        self.readme_file = dataset_dir / "README.md"
        self.metadata = self._load_metadata()

    def _load_metadata(self) -> DatasetMetadata:
        if self.metadata_file.exists():
            try:
                raw = json.loads(self.metadata_file.read_text(encoding="utf-8"))
                return DatasetMetadata(**raw)
            except Exception as e:
                log.warning(f"讀取資料集元數據失敗: {e}")
        return DatasetMetadata(dataset_id=self.dataset_dir.name)

    def save_metadata(self) -> None:
        self.metadata_file.write_text(
            json.dumps(asdict(self.metadata), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    def calculate_sha256(self) -> str:
        """計算 dataset.jsonl 之完整性 SHA-256 雜湊"""
        if not self.data_file.exists():
            return ""
        hasher = hashlib.sha256()
        with self.data_file.open("rb") as f:
            while chunk := f.read(65536):
                hasher.update(chunk)
        return hasher.hexdigest()

    def freeze(self) -> bool:
        """凍結資料集 (Freeze) - 鎖定內容，計算雜湊，禁止靜默修改"""
        if not self.data_file.exists():
            return False

        # 計算內容雜湊
        sha = self.calculate_sha256()
        self.metadata.content_sha256 = sha
        self.metadata.status = "FREEZE"
        self.metadata.closed_at = time.time()
        self.save_metadata()

        # 自動生成統計與可讀報告
        self._generate_statistics_and_readme()
        log.info(f"🔒 資料集工件 {self.metadata.dataset_id} 已成功凍結，SHA-256: {sha[:16]}...")
        return True

    def validate_integrity(self) -> Tuple[bool, str]:
        """驗證資料集內容是否遭到非法竄改"""
        if self.metadata.status not in ("FREEZE", "VALIDATED", "TRAINED", "ARCHIVED"):
            return True, "資料集處於動態收集階段，尚未鎖定。"
        current_sha = self.calculate_sha256()
        if current_sha != self.metadata.content_sha256:
            return False, f"雜湊不符！紀錄: {self.metadata.content_sha256[:12]}, 當前: {current_sha[:12]}"
        return True, "完整性校驗通過。"

    def _generate_statistics_and_readme(self) -> None:
        """生成 statistics.json 與 README.md"""
        samples: List[Dict[str, Any]] = []
        if self.data_file.exists():
            with self.data_file.open("r", encoding="utf-8") as f:
                for line in f:
                    if line.strip():
                        try:
                            samples.append(json.loads(line))
                        except Exception:
                            pass

        count = len(samples)
        self.metadata.sample_count = count
        avg_q = sum(float(s.get("quality_score", 0.5)) for s in samples) / max(1, count)
        self.metadata.quality_score_avg = round(avg_q, 3)

        # 統計事件類型分佈
        event_dist: Dict[str, int] = {}
        for s in samples:
            evt = s.get("event_type", "general")
            event_dist[evt] = event_dist.get(evt, 0) + 1

        stats_data = {
            "dataset_id": self.metadata.dataset_id,
            "total_samples": count,
            "quality_average": self.metadata.quality_score_avg,
            "event_distribution": event_dist,
            "sha256": self.metadata.content_sha256,
            "generated_at": time.time(),
        }
        self.stats_file.write_text(json.dumps(stats_data, indent=2, ensure_ascii=False), encoding="utf-8")

        # 生成報告 README.md
        readme_content = (
            f"# ZeroNexus 獨立資料集工件: {self.metadata.dataset_id}\n\n"
            f"- **版本 (Version)**: `{self.metadata.dataset_version}`\n"
            f"- **狀態 (Status)**: `{self.metadata.status}`\n"
            f"- **樣本總量 (Sample Count)**: `{count}`\n"
            f"- **平均品質 (Average Quality)**: `{self.metadata.quality_score_avg}`\n"
            f"- **SHA-256 數位指紋**: `{self.metadata.content_sha256}`\n"
            f"- **建立時間**: `{time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(self.metadata.created_at))}`\n\n"
            f"### 事件類型分佈\n"
            + "\n".join(f"- **{k}**: {v} 則" for k, v in event_dist.items()) + "\n\n"
            "> 💡 本資料集為完全自包含 (Self-Contained) 之獨立單位，具備不可竄改之 Provenance 溯源保證。\n"
        )
        self.readme_file.write_text(readme_content, encoding="utf-8")
        self.save_metadata()


class DatasetBuilder:
    """資料集工件建造中樞"""

    def __init__(self, root_dir: Optional[Path] = None) -> None:
        self.root_dir = root_dir or DEFAULT_DATASETS_DIR
        self.root_dir.mkdir(parents=True, exist_ok=True)

    def get_or_create_collecting_dataset(self, prefix: str = "zero_dataset") -> DatasetArtifact:
        """取得當前正在收集中的 Dataset 工件，若無則依流水序號開創新工件"""
        # 尋找現有處於 COLLECTING 狀態的資料集
        for child in sorted(self.root_dir.iterdir()):
            if child.is_dir() and child.name.startswith(prefix):
                art = DatasetArtifact(child)
                if art.metadata.status == "COLLECTING":
                    return art

        # 計算下一個序號
        existing_indices = []
        for child in self.root_dir.iterdir():
            if child.is_dir() and child.name.startswith(f"{prefix}_"):
                try:
                    idx = int(child.name.split("_")[-1])
                    existing_indices.append(idx)
                except ValueError:
                    pass

        next_idx = max(existing_indices, default=0) + 1
        new_id = f"{prefix}_{next_idx:03d}"
        target_dir = self.root_dir / new_id
        target_dir.mkdir(parents=True, exist_ok=True)

        artifact = DatasetArtifact(target_dir)
        artifact.metadata.dataset_id = new_id
        artifact.save_metadata()
        log.info(f"📦 已建立新獨立資料集工件: {new_id}")
        return artifact

    def add_sample_to_current(
        self,
        sample_dict: Dict[str, Any],
        threshold_to_freeze: int = 500,
    ) -> DatasetArtifact:
        """將合格樣本寫入當前資料集，並在達到門檻時觸發凍結"""
        artifact = self.get_or_create_collecting_dataset()
        with artifact.data_file.open("a", encoding="utf-8") as f:
            f.write(json.dumps(sample_dict, ensure_ascii=False) + "\n")

        artifact.metadata.sample_count += 1
        artifact.save_metadata()

        if artifact.metadata.sample_count >= threshold_to_freeze:
            artifact.freeze()

        return artifact


# 全域單例
dataset_builder = DatasetBuilder()
