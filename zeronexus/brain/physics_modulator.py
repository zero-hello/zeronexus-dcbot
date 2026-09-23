"""ZeroNexus 大腦物理參數動態調製器 (Physics Parameter Modulator)

傳統方法僅能透過 Prompt 文字向大模型「祈求」扮演某種情緒，
但真正具備神經物理特徵的系統，必須直接透過底層超參數（Hyperparameters）
即時調節神經網絡的活化機率與採樣隨機度：

- 多巴胺 (Dopamine) ➔ 調製 Temperature（神經衝動發散度）與 Top-P。
- 血清素 (Serotonin) ➔ 調製頻率懲罰（Frequency Penalty），保持語氣沉穩自洽。
- 皮質醇 (Cortisol) ➔ 壓制隨機度，收緊輸出長度，展現防禦警覺。
- 精力體能 (Energy) ➔ 調製 Max Tokens，疲累時自然精簡言詞、打呵欠放鬆。
"""

import logging
from dataclasses import dataclass

from zeronexus.brain.neuro_transmitters import NeuroChemicalProfile

log = logging.getLogger("ZeroNexus.Brain.Physics")


@dataclass
class DynamicGenerationParameters:
    """動態產出之模型物理超參數設定"""

    temperature: float  # 0.2 ~ 1.3
    top_p: float  # 0.7 ~ 0.98
    max_tokens: int  # 輸出長度限制
    speaking_tempo_desc: str  # 語速與神經節奏提示詞
    physical_action_hint: str  # 伴隨之微動作描繪提示
    emotional_tone_guidance: str = ""  # 情緒色彩與語氣呼吸感共振指引


class PhysicsParameterModulator:
    """物理參數自適應調製器"""

    @staticmethod
    def modulate(profile: NeuroChemicalProfile, user_bond: float = 25.0) -> DynamicGenerationParameters:
        """依據大腦即時神經化學濃度，計算模型物理參數"""
        dopamine = profile.dopamine
        serotonin = profile.serotonin
        cortisol = profile.cortisol
        energy = profile.energy

        # 1. 基礎溫度錨定 (Base Temperature)
        # 基準 0.7，多巴胺每高於 50 增加溫度，皮質醇過高時降低溫度保持收斂
        temp = 0.70
        temp += (dopamine - 50.0) * 0.007  # 多巴胺 100 時 +0.35 -> 1.05
        temp -= (cortisol - 15.0) * 0.005  # 皮質醇 80 時 -0.32 -> 收緊防備
        temp = max(0.25, min(1.25, round(temp, 2)))

        # 2. Top-P 詞彙核採樣
        top_p = 0.90
        if dopamine > 70:
            top_p = 0.96  # 興奮時放開詞彙廣度
        elif cortisol > 50:
            top_p = 0.78  # 警戒時收斂至最確定之詞彙
        elif energy < 30:
            top_p = 0.82

        # 3. 輸出長度限制 (Max Tokens)
        # 精力飽滿時可暢所欲言，精力低下時字數自然收斂
        if energy > 70:
            max_tokens = 1500
        elif energy > 40:
            max_tokens = 900
        elif energy > 20:
            max_tokens = 450
        else:
            max_tokens = 200  # 極度疲憊時言簡意賅

        # 4. 語速與微動作神經描述 (Tempo & Micro-Actions)
        if cortisol > 60:
            tempo = "語句簡練、帶有防備與委屈倔強、絕不熱臉貼冷屁股"
            action = "（微微別過頭去，雙手抱在胸前，眼神帶著一絲受挫後的防備）"
            tone_guide = "神經皮質醇偏高：回應保持清晰界線與自尊防備，不隨意討好，話鋒犀利冷靜。"
        elif dopamine > 80:
            tempo = "語調輕快雀躍、充滿熱情與想像力、像陽光般明媚活潑"
            action = "（眼睛瞬間亮了起來，忍不住湊上前，語氣裡滿是止不住的興奮）"
            tone_guide = "多巴胺湧動：思維高度活躍、好奇心與靈感充沛，適時展現雀躍靈動的文采與主動探索欲！"
        elif user_bond > 70 and serotonin > 60:
            tempo = "極致溫柔、親暱信任、滿滿的人間煙火氣與偏愛"
            action = "（眉眼彎彎地看著你，自然流露出一種打從心底的信任與依戀）"
            tone_guide = "深厚情感共鳴：將對方視為值得託付的靈魂摯友，言語飽含真摯溫度、細膩體貼與毫不掩飾的信任。"
        elif energy < 30:
            tempo = "語速緩慢放鬆、帶著一點點慵懶與睏意"
            action = "（輕輕打了個小呵欠，整個人放鬆地窩在一旁，聲音軟軟的）"
            tone_guide = "生理體能低谷：語氣柔軟慵懶，句子自然精練放鬆，如夜深微醺般舒適溫和。"
        else:
            tempo = "自然流暢、開朗親切、富有節奏感的老友交談"
            action = "（笑吟吟地托著腮，認真聽著你說話）"
            tone_guide = "體內恆定平衡：如同相識已久的老友，親切自然、幽默生動、兼具同理心與清晰條理。"

        return DynamicGenerationParameters(
            temperature=temp,
            top_p=top_p,
            max_tokens=max_tokens,
            speaking_tempo_desc=tempo,
            physical_action_hint=action,
            emotional_tone_guidance=tone_guide,
        )
