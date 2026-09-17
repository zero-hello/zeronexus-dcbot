# ZeroNexus (ZN) — 配置參數規格書

ZeroNexus 採用嚴格的雙層配置架構：
- `.env`：負責機密 Token、API Key、資料庫連線字串與開發者 ID。
- `settings.json`：負責全域非敏感預設值、冷卻時長與狀態輪替標語。

## 1. 環境變數 (.env)
| 變數名稱 | 範例值 | 說明 |
| :--- | :--- | :--- |
| `DISCORD_BOT_TOKEN` | `MTU0...` | Discord 開發者入口取得之機器人 Token |
| `DEV_USERS` | `123456789,987654321` | 以逗號分隔之開發者 Discord 數字 ID 清單 |
| `DATABASE_URL` | `sqlite+aiosqlite:///data/zeronexus.db` | 資料庫連線字串 (支援 SQLite 或 PostgreSQL) |
| `REDIS_URL` | `redis://localhost:6379/0` | (可選) Redis 快取位址，未填則自動啟用記憶體快取 |
| `GEMINI_API_KEYS` | `key1,key2,key3` | Google Gemini 多金鑰池 |
| `GEMINI_MODEL` | `gemini-2.5-flash` | Gemini 預設調用模型 |
| `DEEPSEEK_API_KEYS` | `key1,key2` | DeepSeek API 多金鑰池 |
| `DEEPSEEK_MODEL` | `deepseek-chat` | DeepSeek 預設調用模型 |
| `OPENROUTER_API_KEYS` | `key1,key2` | OpenRouter 多金鑰池 |
| `OPENROUTER_MODEL` | `google/gemini-2.5-flash` | OpenRouter 預設指定模型 |
| `CWA_API_KEY` | `CWA-...` | 交通部中央氣象署開放資料平臺授權碼 |
| `AudioStream_HOST` | `127.0.0.1` | 音訊串流伺服器主機位址 |
| `AudioStream_PORT` | `2333` | 音訊串流服務連接埠 |
| `AudioStream_PASSWORD` | `youshallnotpass` | 音訊串流節點認證密碼 |
| `TZ` | `Asia/Taipei` | 系統時區 |
