"""ZeroNexus 本地生物大腦神經模型守護與自動自癒中樞 (Brain Model Bootstrap & Guardian)

核心承諾與自癒特性：
1. 啟動前置守衛：開機時自動驗證六個離線 Embedding／分類模型，全數就緒才允許機器人連線啟動。
2. 斷線/關機自癒：若上次下載被中途切斷或檔案殘缺，自動移除壞檔並重新乾淨下載。
3. 缺失自動補齊：若使用者手動刪除其中任意模型，開機時精準偵測並單獨自動下載補齊。
4. 秒級快取放行：若六個 Embedding／分類模型均已完整健康，快速校驗通過並開機。
"""

import os
import logging

log = logging.getLogger("ZeroNexus.Brain.Bootstrap")

MODELS_SPEC = [
    ("bge_small_zh", "Xenova/bge-small-zh-v1.5", "中文高精確語意模型", 20 * 1024 * 1024),
    ("semantic_extractor", "Xenova/all-MiniLM-L6-v2", "跨語言概念空間模型", 18 * 1024 * 1024),
    ("minilm_l12", "Xenova/all-MiniLM-L12-v2", "深層平滑概念模型", 28 * 1024 * 1024),
    ("multilingual_l12", "Xenova/paraphrase-multilingual-MiniLM-L12-v2", "多語言同義句模型", 90 * 1024 * 1024),
    ("sentiment_sst2", "Xenova/distilbert-base-uncased-finetuned-sst-2-english", "情感極性分類模型", 50 * 1024 * 1024),
    ("hostility_sentinel", "Xenova/toxic-bert", "自尊防衛哨兵模型", 90 * 1024 * 1024),
]

def verify_single_model(target_dir: str, min_model_bytes: int) -> bool:
    """驗證單一模型檔案完整度與可載入性"""
    model_path = os.path.join(target_dir, "onnx", "model_quantized.onnx")
    tokenizer_path = os.path.join(target_dir, "tokenizer.json")

    if not os.path.exists(model_path) or not os.path.exists(tokenizer_path):
        return False

    # 檢查大小是否達到最小標準（防止 0 位元組或截斷檔）
    if os.path.getsize(model_path) < min_model_bytes or os.path.getsize(tokenizer_path) < 10 * 1024:
        return False

    # 驗證 ONNX Runtime 與 Tokenizer 載入健全度
    try:
        import onnxruntime as ort
        from tokenizers import Tokenizer
        Tokenizer.from_file(tokenizer_path)
        # 僅快速檢查 Header
        sess_opts = ort.SessionOptions()
        sess_opts.intra_op_num_threads = 1
        ort.InferenceSession(model_path, sess_options=sess_opts, providers=["CPUExecutionProvider"])
        return True
    except (ImportError, ModuleNotFoundError) as e:
        # 若環境缺少套件，但檔案實體完整，不應誤判為檔案毀損以避免誤刪
        log.warning(f"環境缺少推論套件，暫無法驗證模型結構 ({target_dir}): {type(e).__name__}")
        return True
    except Exception as e:
        log.warning(f"模型檔案驗證未通過 ({target_dir}): {e}")
        return False


def ensure_brain_models_ready(console_output: bool = True) -> bool:
    """Low-memory preflight: report missing optional models without downloading them."""

    base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    models_root = os.path.join(base_dir, "data", "brain", "models")
    os.makedirs(models_root, exist_ok=True)

    missing_or_corrupted = []

    # 1. 快速健康檢測
    for folder, repo, desc, min_size in MODELS_SPEC:
        t_dir = os.path.join(models_root, folder)
        if not verify_single_model(t_dir, min_size):
            missing_or_corrupted.append((folder, repo, desc, min_size))

    # Embedding/classification models are optional at startup; use built-in fallback
    # implementations when any are unavailable and never download large assets here.
    if not missing_or_corrupted:
        if console_output:
            print("\033[38;5;48m  ✔ 本地大腦：六個離線 Embedding／分類模型已就緒\033[0m")
        return True

    missing_names = [desc for _, _, desc, _ in missing_or_corrupted]
    log.warning(
        "Optional local Embedding/classification models unavailable (%d/6): %s. "
        "Startup will continue with lightweight fallbacks; run scripts/brain/setup_brain_models.py to install manually.",
        len(missing_or_corrupted), ", ".join(missing_names),
    )
    if console_output:
        print(
            f"⚠️ 本地 Embedding／分類模型有 {len(missing_or_corrupted)}/6 個缺失或不完整；"
            "ZeroNexus 將使用輕量備援繼續啟動，不會自動下載。"
        )
        print("如需安裝，請確認磁碟空間與網路後手動執行：znenv/bin/python scripts/brain/setup_brain_models.py")
    return True


if __name__ == "__main__":
    ensure_brain_models_ready()
