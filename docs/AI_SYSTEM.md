# ZeroNexus (ZN) — AI Gateway 與認知體系

## 1. 三級容錯轉移架構 (Tri-Level Fallback)
```
Gemini (Primary) ──(429/逾時/無金鑰)──> DeepSeek (Secondary) ──(故障)──> OpenRouter (Tertiary)
```

## 2. 多金鑰池 (Key Pool)
- 狀態機：🟢 正常 (Healthy) / 🟡 冷卻中 (Cooldown) / 🔴 已停用 (Disabled)
- 遇到 429 配額耗盡或連線逾時，自動啟動指數退避冷卻機制（30s, 60s, 120s...），冷卻結束自動嘗試自癒恢復。
- 金鑰於 Discord 與日誌中嚴格掩蔽展示：`Key ••••A91F`。

## 3. 三層記憶體系 (Triple-Layer Memory)
1. **共享頻道記憶 (Shared Channel)**：多人聊天脈絡，群體動態理解。
2. **短期記憶 (Short-Term Rolling)**：每位使用者保留最近 400 則訊息。
3. **長期記憶 (Long-Term Fact)**：AI 根據對話需求自動萃取值得保留之偏好與要事（`[REMEMBER: key = value]`），使用者可隨時檢視與刪除。
