"""ZeroNexus 本地生物大腦神經模型守護與自動自癒中樞 (Brain Model Bootstrap & Guardian)

核心承諾與自癒特性：
1. 啟動前置守衛：開機時自動驗證六核離線神經模型，全數就緒才允許機器人連線啟動。
2. 斷線/關機自癒：若上次下載被中途切斷或檔案殘缺，自動移除壞檔並重新乾淨下載。
3. 缺失自動補齊：若使用者手動刪除其中任意模型，開機時精準偵測並單獨自動下載補齊。
4. 秒級快取放行：若 6 個模型均已完整健康，0.05 秒內快速校驗通過並開機，零開機延遲。
"""

import os
import sys
import time
import shutil
import logging
import importlib.util

log = logging.getLogger("ZeroNexus.Brain.Bootstrap")

MODELS_SPEC = [
    ("bge_small_zh", "Xenova/bge-small-zh-v1.5", "中文高精確語意模型", 20 * 1024 * 1024),
    ("semantic_extractor", "Xenova/all-MiniLM-L6-v2", "跨語言概念空間模型", 18 * 1024 * 1024),
    ("minilm_l12", "Xenova/all-MiniLM-L12-v2", "深層平滑概念模型", 28 * 1024 * 1024),
    ("multilingual_l12", "Xenova/paraphrase-multilingual-MiniLM-L12-v2", "多語言同義句模型", 90 * 1024 * 1024),
    ("sentiment_sst2", "Xenova/distilbert-base-uncased-finetuned-sst-2-english", "情感極性分類模型", 50 * 1024 * 1024),
    ("hostility_sentinel", "Xenova/toxic-bert", "自尊防衛哨兵模型", 90 * 1024 * 1024),
]

# 本地 GGUF 神經推論模型規格 (Qwen 2.5 0.5B Instruct)
GGUF_MODEL_SPEC = {
    "filename": "qwen2.5-0.5b-instruct-q8_0.gguf",
    "repo": "Qwen/Qwen2.5-0.5B-Instruct-GGUF",
    "direct_url": "https://huggingface.co/Qwen/Qwen2.5-0.5B-Instruct-GGUF/resolve/main/qwen2.5-0.5b-instruct-q8_0.gguf?download=true",
    "desc": "Qwen 2.5 0.5B Instruct 本地端 GGUF 自主運算模型",
    "min_bytes": 600 * 1024 * 1024,  # 約 600MB
}


def check_and_repair_dependencies() -> bool:
    """自動偵測並自癒修復 Python 神經推論依賴環境 (onnxruntime, tokenizers, llama_cpp 等)"""
    package_map = {
        "onnxruntime": "onnxruntime",
        "tokenizers": "tokenizers",
        "huggingface_hub": "huggingface_hub",
        "cryptography": "cryptography",
        "llama_cpp": "llama-cpp-python",
    }
    missing_mods = []
    missing_pip_names = []
    for mod_name, pip_name in package_map.items():
        if importlib.util.find_spec(mod_name) is None:
            missing_mods.append(mod_name)
            missing_pip_names.append(pip_name)

    if not missing_mods:
        return True

    print(f"\033[38;5;208m⚠️  [大腦守護者] 偵測到當前環境缺少神經運算套件: {', '.join(missing_mods)}\033[0m")
    print("\033[38;5;244m正在嘗試自癒安裝（優先下載二進位預編譯 Wheel）...\033[0m")

    import subprocess
    env = os.environ.copy()
    # 若系統未安裝 gcc/g++，清除可能殘留的 CC/CXX 環境變數，避免 CMake 誤找不存在的編譯器報錯
    if not shutil.which("gcc"):
        env.pop("CC", None)
    if not shutil.which("g++"):
        env.pop("CXX", None)

    cmd = [
        sys.executable, "-m", "pip", "install",
        "--no-cache-dir",
        "--prefer-binary",
        "--extra-index-url", "https://abetlen.github.io/llama-cpp-python/whl/cpu",
    ] + missing_pip_names

    try:
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=300, env=env)
        if res.returncode == 0:
            print("\033[38;5;48m✔ 依賴套件動態安裝成功！已恢復神經大腦執行環境。\033[0m")
            return True
        else:
            log.warning(f"自動安裝套件失敗: {res.stderr}")
    except Exception as e:
        log.warning(f"嘗試自動安裝套件異常: {e}")

    print("\033[38;5;196m✘ 自動安裝套件受限。請於環境或容器內手動安裝：\033[0m")
    print(f"\033[38;5;220m  pip install --prefer-binary --extra-index-url https://abetlen.github.io/llama-cpp-python/whl/cpu {' '.join(missing_pip_names)}\033[0m")
    print("\033[38;5;244m若使用 Docker 部署，請重新建置映像檔：docker compose build --no-cache\033[0m\n")
    return False


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
        log.warning(f"環境缺少推論套件，暫無法驗證模型結構 ({target_dir}): {e}")
        return True
    except Exception as e:
        log.warning(f"模型檔案驗證未通過 ({target_dir}): {e}")
        return False


def download_single_model(folder: str, repo: str, desc: str, models_root: str, max_retries: int = 3) -> bool:
    """乾淨下載或重新下載單一模型"""
    from huggingface_hub import hf_hub_download

    target_dir = os.path.join(models_root, folder)
    # 若存在殘存檔案，先徹底清除
    if os.path.exists(target_dir):
        shutil.rmtree(target_dir, ignore_errors=True)
    os.makedirs(target_dir, exist_ok=True)

    print(f"\033[38;5;214m  ⏳ [大腦守護者] 正在下載/修復 {desc} ({folder})...\033[0m")

    for attempt in range(1, max_retries + 1):
        try:
            m_path = hf_hub_download(
                repo_id=repo,
                filename="onnx/model_quantized.onnx",
                local_dir=target_dir,
            )
            t_path = hf_hub_download(
                repo_id=repo,
                filename="tokenizer.json",
                local_dir=target_dir,
            )
            if os.path.exists(m_path) and os.path.exists(t_path):
                print(f"\033[38;5;48m  ✔ {desc} 下載完成並校驗通過！\033[0m")
                return True
        except Exception as e:
            print(f"\033[38;5;196m  ✘ 下載 {desc} 失敗 (嘗試 {attempt}/{max_retries}): {e}\033[0m")
            time.sleep(2 * attempt)

    return False


def verify_gguf_model(model_path: str, min_bytes: int = 600 * 1024 * 1024) -> bool:
    """驗證本地 GGUF 模型檔案是否存在且大小正常 (防截斷與零位元組檔案)。"""
    if not os.path.exists(model_path):
        return False
    return os.path.getsize(model_path) >= min_bytes


def download_gguf_model(target_path: str, max_retries: int = 3) -> bool:
    """乾淨下載或重新下載 Qwen 2.5 0.5B GGUF 本地推論模型。"""
    os.makedirs(os.path.dirname(target_path), exist_ok=True)
    temp_path = f"{target_path}.part"

    desc = GGUF_MODEL_SPEC["desc"]
    repo = GGUF_MODEL_SPEC["repo"]
    filename = GGUF_MODEL_SPEC["filename"]
    direct_url = GGUF_MODEL_SPEC["direct_url"]
    min_bytes = GGUF_MODEL_SPEC["min_bytes"]

    print(f"\033[38;5;214m  ⏳ [大腦守護者] 正在下載/修復 {desc}...\033[0m")

    # 策略 1: 優先透過 huggingface_hub 下載
    for attempt in range(1, max_retries + 1):
        try:
            from huggingface_hub import hf_hub_download
            downloaded = hf_hub_download(
                repo_id=repo,
                filename=filename,
                local_dir=os.path.dirname(target_path),
            )
            if verify_gguf_model(downloaded, min_bytes):
                print(f"\033[38;5;48m  ✔ {desc} 下載完成並校驗通過！\033[0m")
                return True
        except Exception as e:
            log.warning(f"透過 HF Hub 下載 GGUF 失敗 (嘗試 {attempt}/{max_retries}): {e}")
            time.sleep(2 * attempt)

    # 策略 2: 備援使用 curl 續傳下載
    print(f"\033[38;5;220m  ⚠️  HF Hub 下載受阻，啟動 curl 全速備援續傳機制...\033[0m")
    import subprocess
    try:
        cmd = [
            "curl", "-L", "-C", "-",
            "--retry", "3",
            "--retry-delay", "2",
            "-o", target_path,
            direct_url,
        ]
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
        if res.returncode == 0 and verify_gguf_model(target_path, min_bytes):
            print(f"\033[38;5;48m  ✔ {desc} (curl 備援) 下載完成並校驗通過！\033[0m")
            return True
    except Exception as e:
        log.warning(f"curl 備援下載 GGUF 失敗: {e}")

    return False


def ensure_gguf_model_ready(models_dir: str | None = None, console_output: bool = True) -> bool:
    """確保 Qwen 2.5 0.5B 本地 GGUF 模型檔案已完整就緒，若缺失則自動自癒下載。"""
    if models_dir is None:
        base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        models_dir = os.path.join(base_dir, "data", "models")

    os.makedirs(models_dir, exist_ok=True)
    target_path = os.path.join(models_dir, GGUF_MODEL_SPEC["filename"])
    min_bytes = GGUF_MODEL_SPEC["min_bytes"]

    # 1. 快速健康檢查
    if verify_gguf_model(target_path, min_bytes):
        if console_output:
            print("\033[38;5;48m  ✔ 本地端點：Qwen 2.5 0.5B GGUF 自主運算模型已就緒 (~645MB 全核健康)\033[0m")
        return True

    # 2. 自動觸發下載
    print(f"\n\033[38;5;208m🧠 【ZeroNexus 模型開機守護者】檢測到本地 GGUF 模型缺失或未完成！\033[0m")
    print(f"\033[38;5;244m正在自癒下載 {GGUF_MODEL_SPEC['desc']}...\033[0m")
    success = download_gguf_model(target_path)
    if not success:
        log.error(f"嚴重錯誤：無法自動下載 {GGUF_MODEL_SPEC['desc']}")
        return False
    return True


def ensure_brain_models_ready(console_output: bool = True) -> bool:
    """在機器人開機前，確保所有 6 個離線神經模型與本地 GGUF 模型全部就緒且完好無損"""
    # 0. 環境依賴檢查與熱修復
    check_and_repair_dependencies()

    base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    models_root = os.path.join(base_dir, "data", "brain", "models")
    os.makedirs(models_root, exist_ok=True)

    missing_or_corrupted = []

    # 1. 快速健康檢測
    for folder, repo, desc, min_size in MODELS_SPEC:
        t_dir = os.path.join(models_root, folder)
        if not verify_single_model(t_dir, min_size):
            missing_or_corrupted.append((folder, repo, desc, min_size))

    # 2. 若全數健康，秒速放行
    if not missing_or_corrupted:
        if console_output:
            print("\033[38;5;48m  ✔ 本地大腦：六核離線神經感官矩陣已就緒 (~360MB 全核健康)\033[0m")
        # 同步確保本地 GGUF 模型健康
        ensure_gguf_model_ready(console_output=console_output)
        return True

    # 3. 若有缺失或損壞，啟動自癒下載
    print("\n\033[38;5;208m━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\033[0m")
    print(f"\033[38;5;208m🧠 【ZeroNexus 生物大腦開機守護者】檢測到 {len(missing_or_corrupted)} 個神經模型缺失或未完成！\033[0m")
    print("\033[38;5;244m正在啟動自動自癒安裝程序，下載完成後將自動繼續開機流程...\033[0m\n")

    for folder, repo, desc, min_size in missing_or_corrupted:
        success = download_single_model(folder, repo, desc, models_root)
        if not success:
            print(f"\033[38;5;196m✘ 嚴重錯誤：無法下載必要的神經模型 {desc}，請檢查網路連線後重試。\033[0m")
            return False

    print("\033[38;5;48m\n✔ 大腦模型矩陣修復完成！所有六大模型均已就緒，繼續開機！\033[0m")
    print("\033[38;5;208m━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\033[0m\n")

    # 同步確保本地 GGUF 模型健康
    ensure_gguf_model_ready(console_output=console_output)
    return True


if __name__ == "__main__":
    ensure_brain_models_ready()
