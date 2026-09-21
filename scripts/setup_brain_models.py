#!/usr/bin/env python3
"""ZeroNexus 本地神經模型陣列自動部署腳本

部署三大本地離線神經模型（總體積 < 200MB）：
1. 中文/繁體語意共情模型: Xenova/bge-small-zh-v1.5 (quantized ONNX ~48MB)
2. 跨語言概念嵌入模型: Xenova/all-MiniLM-L6-v2 (quantized ONNX ~23MB)
3. 防衛與毒性哨兵模型: Xenova/toxic-bert (quantized ONNX ~107MB)
搭配第 1 層的微秒級高維幾何張量投影 (14KB)，組成全方位感知與防衛陣列。
"""

import os
import sys
from huggingface_hub import hf_hub_download

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODELS_DIR = os.path.join(BASE_DIR, "data", "brain", "models")


def setup_models():
    print("=" * 65)
    print("開始部署 ZeroNexus 本地神經生物大腦【三大離線模型陣列】...")
    print("=" * 65)

    all_files = []

    # 1. 中文專屬語意共鳴模型 (BGE-small-zh)
    bge_dir = os.path.join(MODELS_DIR, "bge_small_zh")
    os.makedirs(bge_dir, exist_ok=True)
    print("\n[1/3] 檢查/下載中文專屬高精確語意共情模型 (BGE-Small-ZH-v1.5 量化 ONNX)...")
    b1 = hf_hub_download(repo_id="Xenova/bge-small-zh-v1.5", filename="onnx/model_quantized.onnx", local_dir=bge_dir)
    b2 = hf_hub_download(repo_id="Xenova/bge-small-zh-v1.5", filename="tokenizer.json", local_dir=bge_dir)
    print(f"  ✓ 中文模型檔案: {b1} ({os.path.getsize(b1) / 1024 / 1024:.2f} MB)")
    print(f"  ✓ 中文分詞器: {b2} ({os.path.getsize(b2) / 1024:.2f} KB)")
    all_files.extend([b1, b2])

    # 2. 跨語言語意特徵嵌入模型 (MiniLM-L6)
    semantic_dir = os.path.join(MODELS_DIR, "semantic_extractor")
    os.makedirs(semantic_dir, exist_ok=True)
    print("\n[2/3] 檢查/下載跨語言概念空間模型 (MiniLM-L6 量化 ONNX)...")
    p1 = hf_hub_download(repo_id="Xenova/all-MiniLM-L6-v2", filename="onnx/model_quantized.onnx", local_dir=semantic_dir)
    p2 = hf_hub_download(repo_id="Xenova/all-MiniLM-L6-v2", filename="tokenizer.json", local_dir=semantic_dir)
    print(f"  ✓ 跨語言模型檔案: {p1} ({os.path.getsize(p1) / 1024 / 1024:.2f} MB)")
    print(f"  ✓ 跨語言分詞器: {p2} ({os.path.getsize(p2) / 1024:.2f} KB)")
    all_files.extend([p1, p2])

    # 3. 防衛與毒性哨兵模型 (Toxic-BERT)
    sentinel_dir = os.path.join(MODELS_DIR, "hostility_sentinel")
    os.makedirs(sentinel_dir, exist_ok=True)
    print("\n[3/3] 檢查/下載防衛與毒性哨兵模型 (Toxic-BERT 量化 ONNX)...")
    s1 = hf_hub_download(repo_id="Xenova/toxic-bert", filename="onnx/model_quantized.onnx", local_dir=sentinel_dir)
    s2 = hf_hub_download(repo_id="Xenova/toxic-bert", filename="tokenizer.json", local_dir=sentinel_dir)
    print(f"  ✓ 哨兵模型檔案: {s1} ({os.path.getsize(s1) / 1024 / 1024:.2f} MB)")
    print(f"  ✓ 哨兵分詞器: {s2} ({os.path.getsize(s2) / 1024:.2f} KB)")
    all_files.extend([s1, s2])

    total_size = sum(os.path.getsize(f) for f in all_files)
    print("\n" + "=" * 65)
    print(f"✅ 三大神經模型陣列部署完成！")
    print(f"📦 總佔用空間: {total_size / 1024 / 1024:.2f} MB（遠低於 1GB 上限）")
    print("=" * 65)


if __name__ == "__main__":
    setup_models()
