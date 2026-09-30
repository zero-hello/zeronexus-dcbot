from zeronexus.modules.standalone.faq import FAQ_ENTRIES, search_faq


def test_faq_search_returns_relevant_small_results() -> None:
    matches = search_faq("音樂 隊列", limit=3)
    assert matches
    assert len(matches) <= 3
    assert any("音樂" in answer and "隊列" in answer for _, answer in matches)


def test_faq_search_empty_query_is_safe() -> None:
    assert search_faq("   ") == []
    assert len(FAQ_ENTRIES) <= 10
