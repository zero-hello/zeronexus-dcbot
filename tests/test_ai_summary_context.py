from zeronexus.ai_gateway.context_builder import format_conversation_for_summary


def test_summary_transcript_is_bounded_and_keeps_newest_messages() -> None:
    history = [
        {"role": "user", "content": "舊訊息" * 500},
        {"role": "assistant", "content": "早期回答" * 500},
        {"role": "user", "content": "最新問題"},
    ]

    transcript = format_conversation_for_summary(history, max_chars=2600, max_message_chars=400)

    assert len(transcript) <= 2600
    assert "最新問題" in transcript
    assert "訊息已截斷" in transcript


def test_summary_transcript_handles_empty_history_and_invalid_limits() -> None:
    assert format_conversation_for_summary([]) == ""
    assert format_conversation_for_summary([{"role": "user", "content": "hi"}], max_chars=0) == ""


def test_summary_transcript_never_exceeds_tiny_remaining_budget() -> None:
    history = [
        {"role": "user", "content": "x" * 100},
        {"role": "assistant", "content": "latest"},
    ]

    transcript = format_conversation_for_summary(history, max_chars=30, max_message_chars=100)

    assert len(transcript) <= 30
    assert "latest" in transcript
