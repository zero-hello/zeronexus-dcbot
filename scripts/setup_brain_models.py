#!/usr/bin/env python3
"""ZeroNexus 本地神經模型陣列自動部署腳本

部署兩大本地離線神經模型（總體積 < 100MB）：
1. 語意特徵嵌入模型 (Semantic Extractor): Xenova/all-MiniLM-L6-v2 (quantized ONNX ~23MB)
2. 防衛與毒性哨兵模型 (Hostility Sentinel): Xenova/toxic-bert (quantized ONNX ~65MB)
搭配第 1 層的微秒級高維幾何張量投影 (14KB)，組成完整三層感知與防衛陣列。
"""

import os
import sys
from huggingface_hub import hf_hub_download

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODELS_DIR = os.path.join(BASE_DIR, "data", "brain", "models")


def setup_models():
    print("=" * 60)
    print("開始部署 ZeroNexus 本地神經生物大腦模型陣列...")
    print("=" * 60)

    # 1. 語意特徵嵌入模型
    semantic_dir = os.path.join(MODELS_DIR, "semantic_extractor")
    os.makedirs(semantic_dir, exist_ok=True)
    print("\n[1/2] 檢查/下載第 2 層語意特徵嵌入模型 (MiniLM-L6 量化 ONNX)...")
    
    p1 = hf_hub_download(
        repo_id="Xenova/all-MiniLM-L6-v2",
        filename="onnx/model_quantized.onnx",
        local_dir=semantic_dir,
    )
    p2 = hf_hub_download(
        repo_id="Xenova/all-MiniLM-L6-v2",
        filename="tokenizer.json",
        local_dir=semantic_dir,
    )
    print(f"  ✓ 模型檔案: {p1} ({os.path.getsize(p1) / 1024 / 1024:.2f} MB)")
    print(f"  ✓ 分詞器檔案: {p2} ({os.path.getsize(p2) / 1024:.2f} KB)")

    # 2. 防衛與毒性哨兵模型
    sentinel_dir = os.path.join(MODELS_DIR, "hostility_sentinel")
    os.makedirs(sentinel_dir, exist_ok=True)
    print("\n[2/2] 檢查/下載第 3 層防衛與毒性哨兵模型 (Toxic-BERT 量化 ONNX)...")
    
    s1 = hf_hub_download(
        repo_id="Xenova/toxic-bert",
        filename="onnx/model_quantized.onnx",
        local_dir=sentinel_dir,
    )
    s2 = hf_hub_download(
        repo_id="Xenova/toxic-bert",
        filename="tokenizer.json",
        local_dir=sentinel_dir,
    )
    print(f"  ✓ 哨兵模型檔案: {s1} ({os.path.getsize(s1) / 1024 / 1024:.2f} MB)")
    print(f"  ✓ 哨兵分詞器: {s2} ({os.path.getsize(s2) / 1024:.2f} KB)")

    total_size = (
        os.path.getsize(p1) + os.path.getsize(p2) + os.path.getsize(s1) + os.path.getsize(s2)
    )
    print("\n" + "=" * 60)
    print(f"✅ 神經模型陣列部署完成！")
    print(f"📦 總佔用空間: {total_size / 1024 / 1024:.2f} MB（遠低於 1GB 上限）")
    print("=" * 60)


if __name__ == "__main__":
    setup_models()
