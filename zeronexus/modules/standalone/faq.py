"""Small dependency-free FAQ catalogue used by the help commands."""

FAQ_ENTRIES = (
    ("AI 額度", "使用 `/人工智慧 對話額度` 查看對話與生圖用量；不同額度分開計算，台灣時間每日 00:00 重設。"),
    ("AI 模型", "使用 `/人工智慧 模型目錄` 查看文字、圖片理解、即時工具能力與費用標示，再使用 `/人工智慧 切換模型`。"),
    ("記憶與隱私", "單次對話可勾選「不使用記憶」；可用 `/人工智慧 記憶檢視`、`記憶刪除` 或 `記憶清空` 管理個人記憶。"),
    ("取消 AI 回覆", "AI 思考期間可使用回覆下方的「取消回應」按鈕；取消後本次預約額度會釋放。"),
    ("音樂播放", "先加入 Bot 所在語音頻道。使用 `/音樂 隊列` 查看，`/音樂 移除隊列` 移除歌曲，`/音樂 清空隊列` 清空待播歌曲。"),
    ("權限不足", "查看 `/幫助` 的指令分類與權限標記；若為機器人缺少權限，請管理員在伺服器或頻道權限中授予。"),
    ("功能搜尋", "使用 `/搜尋指令 關鍵字`，例如 `/搜尋指令 天氣`、`/搜尋指令 音樂 隊列`。"),
)


def search_faq(query: str, limit: int = 5):
    """Return a small ranked FAQ result list without loading external indexes."""
    terms = [part.casefold() for part in (query or "").split() if part]
    if not terms:
        return []
    ranked = []
    for question, answer in FAQ_ENTRIES:
        searchable = f"{question} {answer}".casefold()
        score = sum(1 for term in terms if term in searchable)
        if score:
            ranked.append((score, question, answer))
    ranked.sort(key=lambda item: (-item[0], item[1]))
    return [(question, answer) for _, question, answer in ranked[:max(1, min(limit, 10))]]
