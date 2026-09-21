#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ZeroNexus AI 即時對話與大腦感官測試工具

使用方式：
    # 互動式聊天模式
    ./znenv/bin/python3 scripts/test_ai_chat.py

    # 單句快速測試
    ./znenv/bin/python3 scripts/test_ai_chat.py "你好呀！請自我介紹一下"
"""

import sys
import time
import asyncio
from pathlib import Path

# 將專案根目錄加入路徑
BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from zeronexus.brain import bio_brain
from zeronexus.ai_gateway.gateway import ai_gateway
from zeronexus.ai_gateway.model_registry import model_registry


async def chat_once(prompt: str, user_id: str = "cli_tester", user_name: str = "測試指揮官"):
    # 1. 本地生物大腦感知與遞質更新
    t0 = time.perf_counter()
    analysis, chem = bio_brain.perceive(user_id, user_name, prompt)
    phys = bio_brain.get_model_params(user_id)
    brain_ms = (time.perf_counter() - t0) * 1000.0

    print(f"\n🧠 【本地生物神經大腦】(耗時: {brain_ms:.1f}ms)")
    print(f"  • 主導情緒: {analysis.dominant_emotion} | 複合狀態: 【{analysis.composite_sentiment}】 (強度: {analysis.intensity*100:.0f}%)")
    print(f"  • 神經遞質: 多巴胺 {chem['dopamine']:.0f}% | 血清素 {chem['serotonin']:.0f}% | 皮質醇 {chem['cortisol']:.0f}% | 催產素 {chem['oxytocin']:.0f}%")
    print(f"  • 調製參數: 溫度={phys.temperature} | 節奏={phys.speaking_tempo_desc}")

    # 2. 準備系統提示詞與大腦生理膠囊
    capsule = bio_brain.get_prompt_capsule(user_id, user_name)
    system_prompt = (
        "你是 ZeroNexus，一個充滿活力、可愛、開朗且聰明的次世代 Discord 智慧中樞。\n"
        "回答請使用道地臺灣繁體中文，生動自然、富有感情，絕不使用死板機械式的客服套話。\n\n"
        f"{capsule}"
    )

    # 3. 呼叫 AI Gateway
    model = model_registry.get_active_default_model()
    print(f"\n🌐 【AI Gateway 推論】發送至模型: \033[38;5;51m{model}\033[0m ...")

    messages = [{"role": "user", "content": prompt}]
    t_gen = time.perf_counter()

    try:
        ai_res, fallback = await ai_gateway.generate_response(
            system_instruction=system_prompt,
            messages=messages,
            override_model=model,
            allow_fallback=True,
        )
        gen_ms = (time.perf_counter() - t_gen) * 1000.0

        if ai_res and ai_res.text:
            print(f"\n✨ \033[38;5;48mZeroNexus 回應\033[0m (耗時: {gen_ms:.0f}ms | 供應商: {ai_res.provider} | 實際模型: {ai_res.model_name}):")
            if ai_res.thinking_process:
                print(f"\033[38;5;244m💭 思維歷程:\n{ai_res.thinking_process.strip()}\033[0m\n")
            print("─" * 60)
            print(ai_res.text.strip())
            print("─" * 60)
            if fallback:
                print(f"⚠️ 注意：主模型觸發限額，已無縫容災降級至: {ai_res.model_name}")
        else:
            print(f"\n❌ 回應失敗，未取得有效文字輸出。")
    except Exception as e:
        print(f"\n❌ 呼叫 AI Gateway 異常: {e}")


async def main():
    print("=" * 65)
    print("🌌 ZeroNexus AI 端到端連線與神經大腦測試工具")
    print("=" * 65)

    if len(sys.argv) > 1:
        query = " ".join(sys.argv[1:])
        print(f"💬 測試問句: {query}")
        await chat_once(query)
        await ai_gateway.close()
        return

    print("提示：已進入終端互動模式，輸入你想對機器人說的話（輸入 exit 結束）：\n")
    try:
        while True:
            user_input = input("💬 請輸入問句: ").strip()
            if not user_input:
                continue
            if user_input.lower() in ("exit", "quit", "q"):
                print("👋 測試結束。")
                break
            await chat_once(user_input)
    except (KeyboardInterrupt, EOFError):
        print("\n👋 測試結束。")
    finally:
        await ai_gateway.close()


if __name__ == "__main__":
    asyncio.run(main())
