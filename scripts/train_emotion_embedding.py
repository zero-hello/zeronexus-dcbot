#!/usr/bin/env python3
"""ZeroNexus 專屬情緒對比學習微調腳本 (Emotion Contrastive Learning Fine-tuning)

針對繁體中文語境，使用對比學習（Contrastive Learning）微調語意嵌入模型（如 BAAI/bge-small-zh-v1.5），
強化普魯契克 8 大原色情緒在幾何向量空間中的語意解析度與邊界區隔能力，
消除對立情緒沾黏（如喜悅與悲傷、信任與厭惡），使語氣氛圍感知更細膩敏銳。

支援功能：
1. 內建 8 大原色情緒繁體中文三元組（Anchor, Positive, Negative）高質量語料庫。
2. 支援外部 JSONL / CSV 資料集匯入。
3. 支援 TripletLoss 與 MultipleNegativesRankingLoss 兩種損失函式。
4. 支援 --dry-run 模擬驗證模式（無需 GPU 或 PyTorch 即可校驗資料管線）。
5. 支援自動儲存模型權重至本地目錄。
"""

import argparse
import csv
import json
import logging
import os
import sys
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("ZeroNexus.TrainEmotion")

# 內建 8 大原色情緒繁體中文對比三元組資料庫
BUILTIN_EMOTION_TRIPLETS: List[Dict[str, str]] = [
    # 1. 喜悅 (Joy)
    {
        "emotion": "喜悅",
        "anchor": "太讚了，今天發布超順利，真的好開心！",
        "positive": "好耶大成功！心情好到想原地轉圈跳舞！",
        "negative": "今天過得好累好心酸，事情一件都沒做成。",
    },
    {
        "emotion": "喜悅",
        "anchor": "看到你為我準備的驚喜，真的好幸福好感動！",
        "positive": "心裡暖洋洋的，覺得遇見你是我最幸運的事！",
        "negative": "算了吧，反正也沒有人會在乎我的感受。",
    },
    {
        "emotion": "喜悅",
        "anchor": "哈哈哈哈笑死我了，這梗圖真的太好笑了！",
        "positive": "超爆笑！笑到我肚子快抽筋，眼淚都流出來了！",
        "negative": "有什麼好笑的？這種行為真的很低級無聊。",
    },
    # 2. 悲傷 (Sadness)
    {
        "emotion": "悲傷",
        "anchor": "覺得心裡好難過好累，挫折又無力，好想哭。",
        "positive": "獨自一人在房間裡發呆，眼淚不知不覺就掉了下來。",
        "negative": "今天太充實了，整個人充滿幹勁與熱情！",
    },
    {
        "emotion": "悲傷",
        "anchor": "付出了這麼多努力，最後還是落得一場空，好失落。",
        "positive": "心碎成一片一片的，再怎麼努力好像也沒有意義了。",
        "negative": "期待明天的全新挑戰，我一定可以克服它！",
    },
    {
        "emotion": "悲傷",
        "anchor": "沒有人理解我，孤單和委屈快要把我淹沒了。",
        "positive": "好委屈好難受，為什麼總是只有我在承受這些痛苦。",
        "negative": "謝謝大家的陪伴與鼓勵，有你們真好！",
    },
    # 3. 信任 (Trust)
    {
        "emotion": "信任",
        "anchor": "謝謝你一直以來的支持與信任，有你真安心可靠。",
        "positive": "只要有你在身邊，我就完全不用擔心任何問題，放心交給你了！",
        "negative": "誰知道你在背後搞什麼鬼，少在那邊裝模作樣！",
    },
    {
        "emotion": "信任",
        "anchor": "你是我最珍貴的夥伴，我毫無保留地相信你。",
        "positive": "我們之間的羈絆無可取代，我永遠願意把背後交給你。",
        "negative": "這種人滿嘴謊話，噁心又虛偽，我絕對不會再理你。",
    },
    {
        "emotion": "信任",
        "anchor": "辛苦了，這段時間全靠你罩著，真的很溫暖很感激。",
        "positive": "摸摸頭辛苦啦，有你在旁邊陪伴，整個人都放鬆下來了。",
        "negative": "滾遠一點，別出現在我眼前礙眼！",
    },
    # 4. 厭惡 (Disgust)
    {
        "emotion": "厭惡",
        "anchor": "好噁心反感，這種行為真的很令人唾棄與反胃。",
        "positive": "看見這種虛偽作作的嘴臉就讓人反胃下頭，爛透了！",
        "negative": "好精緻的禮物，看起來真的太有心了，很喜歡！",
    },
    {
        "emotion": "厭惡",
        "anchor": "滿嘴謊言還在那裡裝清高，噁心鬼離我遠一點。",
        "positive": "差勁又沒品，看到就反感，簡直是浪費空氣。",
        "negative": "感謝你的誠意，我覺得這次溝通非常真誠坦率。",
    },
    # 5. 恐懼 (Fear)
    {
        "emotion": "恐懼",
        "anchor": "好害怕焦慮，萬一搞砸了怎麼辦，心裡慌得不行。",
        "positive": "緊張得全身都在發抖，心跳跳得超快，深怕出大問題！",
        "negative": "安啦，這點小場面根本不用慌，我胸有成竹！",
    },
    {
        "emotion": "恐懼",
        "anchor": "周圍突然變得好安靜，感覺背後發涼，真的好恐怖。",
        "positive": "嚇死我了，心臟差點跳出來，完全不敢回頭看。",
        "negative": "這個環境好舒適祥和，微風吹過真讓人心曠神怡。",
    },
    # 6. 憤怒 (Anger)
    {
        "emotion": "憤怒",
        "anchor": "真的太令人生氣了，莫名其妙，火大至極！",
        "positive": "氣炸！憑什麼這樣對我？真的不爽到了極點，超火大！",
        "negative": "沒關係啦，大家都不容易，互相體諒一下就好了。",
    },
    {
        "emotion": "憤怒",
        "anchor": "少在那邊推卸責任，搞砸了還敢狡辯，欠揍是不是？",
        "positive": "可惡至極，每次都搞這齣，真的讓人抓狂暴怒！",
        "negative": "這件事我也有一部分責任，我們坐下來心平氣和討論吧。",
    },
    # 7. 驚訝 (Surprise)
    {
        "emotion": "驚訝",
        "anchor": "真的假的啦？！天啊，居然真的被你做到了，太扯了！",
        "positive": "哇塞！完全出乎我的意料之外，太不可思議了，嚇我一跳！",
        "negative": "跟平常差不多，平平淡淡沒什麼特別的。",
    },
    {
        "emotion": "驚訝",
        "anchor": "這神展開也太神了吧！我整個人都驚呆愣住了！",
        "positive": "太驚人了！完全沒有預料到會是這種結局！",
        "negative": "這一切都在預料之中，按部就班進行而已。",
    },
    # 8. 期待 (Anticipation)
    {
        "emotion": "期待",
        "anchor": "好期待未來的合作與冒險，迫不及待想嘗試！",
        "positive": "敲碗期待！每天都在倒數計時，等不及想要親自體驗了！",
        "negative": "想到明天又要重複一樣的日子，就覺得厭煩無趣。",
    },
    {
        "emotion": "期待",
        "anchor": "好希望新的功能趕快上線，一定超級好玩！",
        "positive": "滿懷憧憬與期待，希望我們的願望都能順利實現！",
        "negative": "算了吧，期望越高失望越大，我已經不抱任何指望了。",
    },
]


def load_dataset_from_file(file_path: str) -> List[Dict[str, str]]:
    """從自訂檔案 (JSONL 或 CSV) 載入情緒三元組資料集"""
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"找不到指定的資料集檔案: {file_path}")

    triplets = []
    ext = os.path.splitext(file_path)[1].lower()

    if ext in (".jsonl", ".json"):
        with open(file_path, "r", encoding="utf-8") as f:
            for line_idx, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                    if "anchor" in obj and "positive" in obj and "negative" in obj:
                        triplets.append(obj)
                except Exception as e:
                    log.warning(f"解析 JSONL 第 {line_idx} 行時發生錯誤: {e}")
    elif ext == ".csv":
        with open(file_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                if "anchor" in row and "positive" in row and "negative" in row:
                    triplets.append(row)
    else:
        raise ValueError(f"不支援的檔案格式: {ext} (僅支援 .jsonl, .json, .csv)")

    log.info(f"從 {file_path} 成功載入 {len(triplets)} 筆三元組樣本。")
    return triplets


def run_dry_run_validation(triplets: List[Dict[str, str]], output_dir: str) -> None:
    """執行 Dry-run 模擬驗證，分析三元組完整度與情緒類別分佈"""
    print("\n" + "=" * 70)
    print("🔍 [Dry-Run 模式] 執行情緒對比學習資料集與管線檢驗")
    print("=" * 70)

    category_count: Dict[str, int] = {}
    total = len(triplets)

    for item in triplets:
        emo = item.get("emotion", "未分類")
        category_count[emo] = category_count.get(emo, 0) + 1

    print(f"📊 總三元組樣本數: {total} 組")
    print("📋 情緒分佈統計:")
    for emo, cnt in sorted(category_count.items(), key=lambda x: x[1], reverse=True):
        print(f"  - 【{emo}】: {cnt} 筆 ({cnt / total * 100:.1f}%)")

    print("\n🔬 三元組語料品質抽檢 (前 3 筆):")
    for i, item in enumerate(triplets[:3], 1):
        emo_tag = f"【{item.get('emotion', '一般')}】"
        print(f"\n  範例 #{i} {emo_tag}:")
        print(f"    - 錨點 (Anchor)   : {item.get('anchor')}")
        print(f"    - 正向 (Positive) : {item.get('positive')}")
        print(f"    - 負向 (Negative) : {item.get('negative')}")

    print("\n📁 目標輸出路徑:", os.path.abspath(output_dir))
    print("💡 驗證結論: 三元組資料結構合規，可直接投入模型訓練。")
    print("💡 若需正式執行微調訓練，請確保虛擬環境已安裝必要套件：")
    print("    pip install sentence-transformers torch accelerate")
    print("=" * 70 + "\n")


def train_emotion_embedding(
    model_name: str,
    triplets: List[Dict[str, str]],
    output_dir: str,
    epochs: int = 3,
    batch_size: int = 16,
    lr: float = 2e-5,
    loss_type: str = "triplet",
) -> None:
    """使用 sentence-transformers 執行情緒對比學習微調"""
    try:
        import torch
        from sentence_transformers import InputExample, SentenceTransformer, losses
        from torch.utils.data import DataLoader
    except ImportError as e:
        log.error(f"微調所需的依賴庫未安裝: {e}")
        log.error("請在虛擬環境中執行: pip install sentence-transformers torch")
        sys.exit(1)

    device = "cuda" if torch.cuda.is_available() else "cpu"
    log.info(f"使用運算裝置: {device.upper()}")
    log.info(f"載入基礎語意模型: {model_name}")

    model = SentenceTransformer(model_name, device=device)

    # 建立 InputExample
    train_examples = []
    for item in triplets:
        train_examples.append(
            InputExample(
                texts=[item["anchor"], item["positive"], item["negative"]],
            )
        )

    log.info(f"成功構建 {len(train_examples)} 筆 InputExample 訓練樣本。")
    train_dataloader = DataLoader(train_examples, shuffle=True, batch_size=batch_size)

    # 配置損失函式
    if loss_type == "mnrl":
        log.info("採用損失函式: MultipleNegativesRankingLoss")
        train_loss = losses.MultipleNegativesRankingLoss(model)
    else:
        log.info("採用損失函式: BatchHardTripletLoss / TripletLoss (Margin=0.3)")
        train_loss = losses.TripletLoss(model, margin=0.3)

    warmup_steps = int(len(train_dataloader) * epochs * 0.1)
    log.info(f"開始微調訓練 (Epochs: {epochs}, Batch Size: {batch_size}, LR: {lr}, Warmup: {warmup_steps})...")

    model.fit(
        train_objectives=[(train_dataloader, train_loss)],
        epochs=epochs,
        warmup_steps=warmup_steps,
        optimizer_params={"lr": lr},
        show_progress_bar=True,
    )

    os.makedirs(output_dir, exist_ok=True)
    log.info(f"微調訓練完成，正在匯出模型權重至: {output_dir}")
    model.save(output_dir)

    print("\n" + "=" * 70)
    print("🎉 情緒對比學習微調完成！")
    print(f"📦 模型已儲存於: {output_dir}")
    print("💡 後續匯出為 ONNX 建議指令:")
    print(f"    optimum-cli export onnx --model {output_dir} {output_dir}/onnx/")
    print("=" * 70 + "\n")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="ZeroNexus 專屬情緒對比學習微調腳本 (Emotion Contrastive Learning)"
    )
    parser.add_argument(
        "--model-name",
        type=str,
        default="BAAI/bge-small-zh-v1.5",
        help="基礎模型名稱或路徑 (預設: BAAI/bge-small-zh-v1.5)",
    )
    parser.add_argument(
        "--dataset",
        type=str,
        default=None,
        help="自訂外部三元組資料集路徑 (支援 .jsonl, .json, .csv)",
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default="data/brain/models/bge-small-emotion-v1",
        help="微調後模型儲存路徑 (預設: data/brain/models/bge-small-emotion-v1)",
    )
    parser.add_argument(
        "--epochs",
        type=int,
        default=3,
        help="訓練輪數 (預設: 3)",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=16,
        help="批次大小 (預設: 16)",
    )
    parser.add_argument(
        "--learning-rate",
        type=float,
        default=2e-5,
        help="學習率 (預設: 2e-5)",
    )
    parser.add_argument(
        "--loss",
        type=str,
        choices=["triplet", "mnrl"],
        default="triplet",
        help="損失函式類型: triplet (TripletLoss) 或 mnrl (MultipleNegativesRankingLoss)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="僅執行資料管線檢驗與分佈分析，不進行實際模型訓練",
    )

    args = parser.parse_args()

    # 1. 載入資料集
    if args.dataset:
        log.info(f"從指定外部檔案載入資料集: {args.dataset}")
        triplets = load_dataset_from_file(args.dataset)
    else:
        log.info("未指定外部資料集，使用內建普魯契克 8 大原色情緒高品質繁體中文對比三元組資料庫。")
        triplets = BUILTIN_EMOTION_TRIPLETS

    # 2. 若為 dry-run 模式
    if args.dry_run:
        run_dry_run_validation(triplets, args.output_dir)
        return

    # 3. 執行正式微調訓練
    train_emotion_embedding(
        model_name=args.model_name,
        triplets=triplets,
        output_dir=args.output_dir,
        epochs=args.epochs,
        batch_size=args.batch_size,
        lr=args.learning_rate,
        loss_type=args.loss,
    )


if __name__ == "__main__":
    main()
