#!/usr/bin/env python3
"""ZeroNexus 本地六核離線神經模型矩陣自動部署腳本 (Hexa-Model Array)

部署完整六大離線神經模型（總體積 ~362MB，遠低於 1GB 上限）：
1. 中文專屬語意共情: Xenova/bge-small-zh-v1.5 (~23MB)
2. 跨語言概念空間幾何: Xenova/all-MiniLM-L6-v2 (~22MB)
3. 跨語言深層微調幾何: Xenova/all-MiniLM-L12-v2 (~32MB)
4. 多語言同義句共鳴: Xenova/paraphrase-multilingual-MiniLM-L12-v2 (~113MB)
5. 情感極性專用分類器: Xenova/distilbert-base-uncased-finetuned-sst-2-english (~65MB)
6. 神經自尊防衛哨兵: Xenova/toxic-bert (~106MB)
搭配基底層微秒級幾何張量投影 (< 1ms, 14KB)，組成全方位感知神經網。
"""

import os
import sys
from huggingface_hub import hf_hub_download

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODELS_DIR = os.path.join(BASE_DIR, "data", "brain", "models")

MODEL_SPECS = [
    ("bge_small_zh", "Xenova/bge-small-zh-v1.5", "中文高精確 BGE-ZH 語意模型"),
    ("semantic_extractor", "Xenova/all-MiniLM-L6-v2", "跨語言通用概念空間 MiniLM-L6"),
    ("minilm_l12", "Xenova/all-MiniLM-L12-v2", "深層概念平滑 MiniLM-L12"),
    ("multilingual_l12", "Xenova/paraphrase-multilingual-MiniLM-L12-v2", "50+ 多語言同義句共鳴模型"),
    ("sentiment_sst2", "Xenova/distilbert-base-uncased-finetuned-sst-2-english", "DistilBERT-SST-2 情感極性分類器"),
    ("hostility_sentinel", "Xenova/toxic-bert", "Toxic-BERT 自尊防衛哨兵模型"),
]


def setup_models():
    print("=" * 70)
    print("開始部署 ZeroNexus 本地生物大腦【六核離線神經模型矩陣】...")
    print("=" * 70)

    total_size = 0
    for idx, (folder, repo, desc) in enumerate(MODEL_SPECS, 1):
        target_dir = os.path.join(MODELS_DIR, folder)
        os.makedirs(target_dir, exist_ok=True)
        print(f"\n[{idx}/6] 檢查/下載 {desc} ({repo})...")
        m_path = hf_hub_download(repo_id=repo, filename="onnx/model_quantized.onnx", local_dir=target_dir)
        t_path = hf_hub_download(repo_id=repo, filename="tokenizer.json", local_dir=target_dir)
        m_size = os.path.getsize(m_path)
        t_size = os.path.getsize(t_path)
        total_size += m_size + t_size
        print(f"  ✓ 模型檔案: {m_path} ({m_size / 1024 / 1024:.2f} MB)")
        print(f"  ✓ 分詞器檔案: {t_path} ({t_size / 1024:.2f} KB)")

    print("\n" + "=" * 70)
    print(f"✅ 六大離線神經模型矩陣全數部署就緒！")
    print(f"📦 陣列總佔用空間: {total_size / 1024 / 1024:.2f} MB（遠低於 1GB 上限）")
    print("=" * 70)


if __name__ == "__main__":
    setup_models()
