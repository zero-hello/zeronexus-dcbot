#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ZeroNexus 本地生物大腦與情緒神經系統互動式測試工具

使用方式：
    ./znenv/bin/python3 scripts/interactive_brain_test.py
"""

import sys
import time
from pathlib import Path

# 將專案根目錄加入 sys.path
BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from zeronexus.brain import bio_brain


def render_bar(val: float, max_val: float = 100.0, width: int = 20, fill_char: str = "█") -> str:
    clamped = max(0.0, min(max_val, val))
    fill_len = int((clamped / max_val) * width)
    bar = fill_char * fill_len + "░" * (width - fill_len)
    return f"[{bar}] {int(val):3d}%"


def main():
    print("=" * 70)
    print("🧠 ZeroNexus 本地生物神經網絡與情緒大腦【即時互動測試終端】")
    print("說明：輸入任何話語（誇獎、抱怨、撒嬌、生氣、問候），觀察神經遞質即時波動！")
    print("輸入 'exit' 或 'quit' 退出測試。")
    print("=" * 70)

    user_id = "test_user_zero"
    user_name = "Zero"

    while True:
        try:
            user_input = input("\n💬 請輸入你想對機器人說的話: ").strip()
            if not user_input:
                continue
            if user_input.lower() in ("exit", "quit", "q"):
                print("👋 測試結束，大腦進入休眠恆定狀態。")
                break

            # 1. 觸發感知與神經遞質更新
            t0 = time.perf_counter()
            analysis, chem = bio_brain.perceive(user_id, user_name, user_input)
            phys = bio_brain.get_model_params(user_id)
            elapsed_ms = (time.perf_counter() - t0) * 1000.0

            # 2. 顯示高維情緒幾何投影分析
            print("\n" + "─" * 70)
            print(f"📊 【高維情緒幾何投影】 (耗時: {elapsed_ms:.2f} ms)")
            print(f"  • 主導情緒: {analysis.dominant_emotion} (次要: {analysis.secondary_emotion})")
            print(f"  • 複合情感: 【{analysis.composite_sentiment}】 (強度: {analysis.intensity * 100:.1f}%)")
            print(f"  • 幾何座標: 愉悅度(Valence): {analysis.valence:+.2f} | 激動度(Arousal): {analysis.arousal:.2f}")
            print(f"  • 語意摘要: {analysis.sentiment_summary}")

            # 3. 顯示即時神經遞質儀表板
            print("\n🧪 【即時神經遞質與生理狀態】")
            print(f"  • 多巴胺 (好奇/興奮): {render_bar(chem['dopamine'])} (變化: {analysis.delta_dopamine:+.1f})")
            print(f"  • 血清素 (滿足/穩定): {render_bar(chem['serotonin'])} (變化: {analysis.delta_serotonin:+.1f})")
            print(f"  • 皮質醇 (壓力/防備): {render_bar(chem['cortisol'])} (變化: {analysis.delta_cortisol:+.1f})")
            print(f"  • 催產素 (對你的羈絆): {render_bar(chem['oxytocin'])} (變化: {analysis.delta_oxytocin:+.1f})")
            print(f"  • 身體精力 (體力狀況): {render_bar(chem['energy'])}")

            # 4. 顯示模型物理超參數調製
            print("\n🎛️ 【大腦驅動之模型物理超參數】")
            print(f"  • Temperature (隨機度/思維活躍): {phys.temperature}  (多巴胺驅動)")
            print(f"  • Top-P       (詞彙核採樣):     {phys.top_p}")
            print(f"  • Max Tokens  (輸出長度限制):   {phys.max_tokens} 字 (體力精力驅動)")
            print(f"  • 語速與神經節奏: {phys.speaking_tempo_desc}")
            print(f"  • 生理自然微動作: {phys.physical_action_hint}")

            # 5. 顯示注入大腦膠囊預覽
            capsule = bio_brain.get_prompt_capsule(user_id, user_name)
            print("\n💊 【注入給 Gemini 之生理狀態膠囊】")
            print(capsule)
            print("─" * 70)

        except (KeyboardInterrupt, EOFError):
            print("\n👋 測試中斷，已保存狀態。")
            break
        except Exception as e:
            print(f"\n❌ 測試過程發生異常: {e}")


if __name__ == "__main__":
    main()
