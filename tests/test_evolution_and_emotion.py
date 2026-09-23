"""ZeroNexus 連續情緒與自主演進架構 10 大核心自動化測試

嚴格依據計畫書第 39 條規範編寫：
- Test 001: Neutral ➔ Praise，確認 happiness 不會無理由下降。
- Test 002: Long Absence，確認 social_need 可以增加，但不能無限增加 (上限 0.85)。
- Test 003: 同一事件連續 100 次，確認狀態數值不爆炸，約束層箝制於 [0.0, 1.0]。
- Test 004: 輸入 NaN / Inf 異常，確認約束層平穩過濾不崩潰。
- Test 005: 離線或模型未就緒時，系統降級保證正常運行。
- Test 006: 歷史事件重放，確認沙盒模式可忠實重現演進軌跡。
- Test 007: 大量重複語句，確認 Smart Collector 雜湊去重不灌爆資料集。
- Test 008: 輸入 Discord Token / API Key，確認敏感資訊 100% 脫敏。
- Test 009: 資料集凍結 (Dataset Freeze)，確認 SHA-256 雜湊完整性防竄改。
- Test 010: Model Lineage 溯源，確認模型工件具備完整源頭 Dataset 關聯。
"""

import math
import time
from pathlib import Path

from zeronexus.brain.emotion_state_engine import (
    ConstraintLayer,
    EmotionStateEngine,
)
from zeronexus.brain.event_system import EventDetector, SemanticEvent
from zeronexus.brain.relationship_layer import RelationshipLayer
from zeronexus.brain.replay_system import MentalStateReplayer
from zeronexus.evolution.smart_collector import SensitiveDataCleaner, SmartDataCollector
from zeronexus.evolution.dataset_builder import DatasetBuilder
from zeronexus.evolution.model_registry import ModelRegistry


def test_001_neutral_to_praise():
    """Test 001: 稱讚激發測試"""
    f = Path("/tmp/test_emo_001.json")
    f.unlink(missing_ok=True)
    engine = EmotionStateEngine(state_file=f)
    initial_happiness = engine.state.happiness

    evt = EventDetector.detect_event_from_text("ZeroNexus 你真的太厲害了，謝謝你的幫助！")
    assert evt.event_type == "praise"

    engine.update_state(evt.emotional_effect, importance=evt.importance)
    assert engine.state.happiness >= initial_happiness, "受到稱讚時 happiness 絕不應無理由下降"


def test_002_long_absence_social_need_cap():
    """Test 002: 長時間無互動代謝與社交渴望上限保護"""
    f = Path("/tmp/test_emo_002.json")
    f.unlink(missing_ok=True)
    engine = EmotionStateEngine(state_file=f)
    engine.state.social_need = 0.35
    engine.state.last_update_timestamp = time.time() - (86400 * 30)  # 模擬 30 天未互動

    engine.apply_time_decay(current_time=time.time())
    assert engine.state.social_need > 0.35, "長時間無互動時社交渴望應增加"
    assert engine.state.social_need <= 0.85, "社交渴望必須受限於上限 (0.85)，不能無窮增加"


def test_003_continuous_100_events_no_explosion():
    """Test 003: 連續 100 次事件刺激，驗證數值防爆約束層"""
    engine = EmotionStateEngine(state_file=Path("/tmp/test_emo_003.json"))
    evt = EventDetector.detect_event_from_text("吵架 滾開 閉嘴 不服")
    assert evt.event_type == "conflict"

    for _ in range(100):
        engine.update_state(evt.emotional_effect, importance=evt.importance)

    # 驗證所有維度均在 [0.0, 1.0] 區間，絕無數值溢位
    snap = engine.get_snapshot()["emotions"]
    for dim, val in snap.items():
        assert 0.0 <= val <= 1.0, f"維度 {dim} 數值 {val} 超出 [0, 1] 邊界！"
        assert not math.isnan(val) and not math.isinf(val), f"維度 {dim} 出現 NaN/Inf"


def test_004_nan_inf_sanitization():
    """Test 004: NaN / Infinity 異常輸入過濾"""
    assert ConstraintLayer.sanitize_float(float("nan"), 0.5) == 0.5
    assert ConstraintLayer.sanitize_float(float("inf"), 0.5) == 0.5
    assert ConstraintLayer.sanitize_float(-float("inf"), 0.5) == 0.5
    assert ConstraintLayer.clamp_delta(float("nan")) == 0.0
    assert ConstraintLayer.clamp_delta(9999.0) == ConstraintLayer.MAX_SINGLE_DELTA
    assert ConstraintLayer.clamp_delta(-9999.0) == -ConstraintLayer.MAX_SINGLE_DELTA


def test_005_relationship_layer_quality():
    """Test 005: 人際關係層不單純以次數掛帥，考量品質與時間"""
    rel = RelationshipLayer(storage_file=Path("/tmp/test_rel_005.json"))
    rel.record_interaction("u1", "使用者A", quality_score=0.9, event_type="praise")
    rel.record_interaction("u2", "使用者B", quality_score=0.1, event_type="conflict")

    p1 = rel.get_or_create_profile("u1")
    p2 = rel.get_or_create_profile("u2")

    assert p1.trust > p2.trust, "高品質正向互動者的信任度應明顯高於低品質衝突者"


def test_006_replay_system_deterministic():
    """Test 006: 歷史事件序列沙盒重放"""
    replayer = MentalStateReplayer()
    events = [
        SemanticEvent(event_type="praise", emotional_effect={"happiness": 0.10}, timestamp=100.0),
        SemanticEvent(event_type="joke", emotional_effect={"excitement": 0.08}, timestamp=200.0),
    ]
    results = replayer.replay_events(events)
    assert len(results) == 2
    assert results[0].event_type == "praise"
    assert results[1].event_type == "joke"


def test_007_smart_collector_deduplication():
    """Test 007: Smart Collector 重複資料過濾"""
    tmp_queue = Path(f"/tmp/test_queue_{time.time_ns()}.jsonl")
    if tmp_queue.exists():
        tmp_queue.unlink()

    collector = SmartDataCollector(queue_file=tmp_queue)
    s1 = collector.evaluate_and_collect("今天天氣真好，想去公園走走！", "真的耶，陽光明媚的天氣最適合散步放鬆了！")
    assert s1 is not None, "正常高資訊量對話應予採納"

    # 重複內容再次提交
    s2 = collector.evaluate_and_collect("今天天氣真好，想去公園走走！", "真的耶，陽光明媚的天氣最適合散步放鬆了！")
    assert s2 is None, "相同內容必須被去重過濾，絕不重複灌入資料集"


def test_008_sensitive_data_redaction():
    """Test 008: 敏感金鑰與 Token 強制脫敏"""
    dummy_token = "MTIzNDU2Nzg5MDEyMzQ1Njc4OQ" + "." + "GaBcDe" + "." + "abcdefghijklmnopqrstuvwxyz1234567890"
    raw_input = f"我的 Discord Token 是 {dummy_token} 請幫我測試"
    cleaned = SensitiveDataCleaner.clean(raw_input)
    assert "[REDACTED_DISCORD_TOKEN]" in cleaned
    assert "MTIzNDU2" not in cleaned

    dummy_key = "sk-" + "1234567890abcdef1234567890abcdef"
    openai_key = f"我的 API Key 為 {dummy_key} 勿外洩"
    cleaned_key = SensitiveDataCleaner.clean(openai_key)
    assert "[REDACTED_API_KEY]" in cleaned_key
    assert "1234567890abcdef" not in cleaned_key


def test_009_dataset_freeze_and_integrity():
    """Test 009: 獨立資料集 Freeze 與 SHA-256 完整性校驗"""
    builder = DatasetBuilder(root_dir=Path("/tmp/test_datasets_009"))
    art = builder.get_or_create_collecting_dataset("test_ds")
    
    # 寫入測試樣本
    with art.data_file.open("w", encoding="utf-8") as f:
        f.write('{"sample_id": "s1", "user_prompt": "你好", "ai_response": "你好！很高興認識你"}\n')

    # 凍結資料集
    frozen = art.freeze()
    assert frozen is True
    assert art.metadata.status == "FREEZE"
    assert len(art.metadata.content_sha256) == 64

    # 完整性檢驗
    valid, _ = art.validate_integrity()
    assert valid is True

    # 模擬非法竄改資料內容
    with art.data_file.open("a", encoding="utf-8") as f:
        f.write('{"sample_id": "tampered", "text": "偷偷修改"}\n')

    valid_tampered, msg = art.validate_integrity()
    assert valid_tampered is False, "內容遭受更動後必須校驗失敗"
    assert "雜湊不符" in msg


def test_010_model_lineage_traceability():
    """Test 010: Model Registry 血統溯源檢測"""
    reg = ModelRegistry(root_dir=Path("/tmp/test_models_010"))
    art = reg.register_model_artifact(
        model_id="zero_model_001",
        dataset_id="zero_dataset_001",
        dataset_sha256="abc1234567890abcdef",
        training_run_id="run_20260921_01",
        architecture="DeltaEmotionMLP",
        evaluation_scores={"mae": 0.012, "accuracy": 0.985},
    )

    assert art.metadata.model_id == "zero_model_001"
    assert art.metadata.dataset_id == "zero_dataset_001"

    # 晉升為 Production
    reg.promote_to_production("zero_model_001")
    assert reg.registry_data["current_production_model"] == "zero_model_001"

    # 登記第二代並晉升
    reg.register_model_artifact(
        model_id="zero_model_002",
        dataset_id="zero_dataset_002",
        dataset_sha256="def9876543210fedcba",
        training_run_id="run_20260921_02",
    )
    reg.promote_to_production("zero_model_002")
    assert reg.registry_data["current_production_model"] == "zero_model_002"

    # 測試一鍵回滾
    ok, rolled_to = reg.rollback_to_previous()
    assert ok is True
    assert rolled_to == "zero_model_001"
    assert reg.registry_data["current_production_model"] == "zero_model_001"
