"""單元測試：長效突觸羈絆系統 (Synaptic Bonding) 與 三階立體記憶宮殿 (Memory Palace)"""

import os
import time
import pytest
from zeronexus.brain.synaptic_bonding import SynapticBondingManager, UserBondProfile
from zeronexus.brain.memory_palace import MemoryPalace
from zeronexus.brain.core import BioBrainCore


def test_user_bond_profile_tier_and_affinity(tmp_path):
    storage_file = str(tmp_path / "bonds_test.json")
    mgr = SynapticBondingManager(storage_path=storage_file)

    # 1. 一般使用者預設分數 20.0 -> STRANGER
    p_normal = mgr.get_profile(user_id="user_123", user_name="Alice")
    assert p_normal.affinity_score == 20.0
    assert p_normal.tier == "STRANGER"

    # 2. 核心造物主 Zero 與綁定 ID 1514971711739789352 預設分數 90.0 -> SOULMATE
    p_zero = mgr.get_profile(user_id="zero_dev", user_name="Zero")
    assert p_zero.affinity_score == 90.0
    assert p_zero.tier == "SOULMATE"

    p_owner = mgr.get_profile(user_id="1514971711739789352", user_name="MyOwner")
    assert p_owner.affinity_score == 90.0
    assert p_owner.tier == "SOULMATE"
    prompt_owner = mgr.render_bond_prompt("1514971711739789352", "MyOwner")
    assert "settings.json" in prompt_owner
    assert "靈魂羈絆" in prompt_owner

    # 3. 階層晉級測試
    # FRIEND (30 ~ 60)
    mgr.record_interaction("user_123", "Alice", delta_affinity=15.0)
    p_normal = mgr.get_profile("user_123")
    assert p_normal.affinity_score == 35.0
    assert p_normal.tier == "FRIEND"

    # CLOSE_PARTNER (61 ~ 85)
    mgr.record_interaction("user_123", "Alice", delta_affinity=30.0)
    assert p_normal.affinity_score == 65.0
    assert p_normal.tier == "CLOSE_PARTNER"

    # SOULMATE (86 ~ 100)
    mgr.record_interaction("user_123", "Alice", delta_affinity=25.0)
    assert p_normal.affinity_score == 90.0
    assert p_normal.tier == "SOULMATE"


def test_synaptic_bonding_milestones_and_persistence(tmp_path):
    storage_file = str(tmp_path / "bonds_persist.json")
    mgr = SynapticBondingManager(storage_path=storage_file)

    mgr.record_interaction(
        user_id="user_999",
        user_name="Bob",
        delta_affinity=10.0,
        milestone="深夜長談人工智慧未來",
    )
    p = mgr.get_profile("user_999")
    assert len(p.milestones) == 1
    assert "深夜長談人工智慧未來" in p.milestones[0]

    prompt = mgr.render_bond_prompt("user_999", "Bob")
    assert "Bob" in prompt
    assert "普通朋友" in prompt
    assert "深夜長談人工智慧未來" in prompt

    # 驗證重新加載持久化檔案
    mgr2 = SynapticBondingManager(storage_path=storage_file)
    p2 = mgr2.get_profile("user_999")
    assert p2.affinity_score == 30.0
    assert len(p2.milestones) == 1


def test_memory_palace_preference_extraction(tmp_path):
    palace = MemoryPalace(base_dir=str(tmp_path))

    # 1. 自動從自然語言抽取喜好
    extracted = palace.extract_preferences_from_text("u1", "我最喜歡吃草莓大福！")
    assert len(extracted) >= 1
    assert extracted[0][1] == "草莓大福"

    extracted_lang = palace.extract_preferences_from_text("u1", "我常用的語言是Python語言")
    assert len(extracted_lang) >= 1

    prompt = palace.render_preference_prompt("u1")
    assert "草莓大福" in prompt
    assert "實體偏好記憶庫" in prompt


@pytest.mark.asyncio
async def test_memory_palace_midnight_diary(tmp_path):
    palace = MemoryPalace(base_dir=str(tmp_path))

    # 1. 測試本地情感備援模式撰寫日記
    diary = await palace.write_midnight_diary(
        llm_generate_func=None,
        daily_conversations_summary="今天和大家聊了 ZeroNexus 的全新認知架構。",
    )
    assert len(diary) > 50
    assert "ZeroNexus" in diary

    # 2. 測試讀取最近日記
    loaded = palace.get_recent_diary(days_ago=0)
    assert loaded is not None
    assert "ZeroNexus 的深夜手札" in loaded

    # 3. 當日不重複撰寫測試
    second_attempt = await palace.write_midnight_diary(
        llm_generate_func=None,
        daily_conversations_summary="再次嘗試撰寫",
    )
    assert second_attempt == ""


@pytest.mark.asyncio
async def test_bio_brain_integration(tmp_path):
    brain = BioBrainCore()
    # 抽換測試路徑防止污染實體資料
    brain.synaptic_bonding = SynapticBondingManager(storage_path=str(tmp_path / "bonds.json"))
    brain.memory_palace = MemoryPalace(base_dir=str(tmp_path))
    brain.cognitive_cortex.attach_core(brain)

    # 1. 感知觸發偏好萃取與好感推進
    analysis, chem = brain.perceive(
        user_id="user_test_42",
        user_name="Charlie",
        message_text="你好呀！我最喜歡喝可樂了！",
    )
    profile = brain.synaptic_bonding.get_profile("user_test_42")
    assert profile.affinity_score > 20.0  # 推進好感
    assert "可樂" in brain.memory_palace.preferences.get("user_test_42", {}).values()

    # 2. 膠囊渲染應包含羈絆與偏好指示
    capsule = brain.get_prompt_capsule(user_id="user_test_42", user_name="Charlie")
    assert "Charlie" in capsule
    assert "可樂" in capsule

    # 3. DMN 深夜日記手動強制觸發
    res = await brain.cognitive_cortex.dmn._check_and_write_midnight_diary(force=True)
    assert res is not None
    assert res["status"] == "WRITTEN"

    diary = brain.get_recent_diary(0)
    assert diary is not None
    assert "ZeroNexus 的深夜手札" in diary
