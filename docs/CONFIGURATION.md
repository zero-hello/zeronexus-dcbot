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
| `OPENAI_API_KEY` / `OPENAI_API_KEYS` | 中轉站 API 金鑰 | 選填；配置後啟用 OpenAI Responses API Function Calling |
| `OPENAI_BASE_URL` | `https://api.openai.com/v1` | API 根路徑；中轉站需支援 `/responses` |
| `OPENAI_MODEL` | `gpt-4.1-mini` | 上游模型 ID；模型切換時使用 `openai/<模型ID>` |
| `CWA_API_KEY` | `CWA-...` | 交通部中央氣象署開放資料平臺授權碼 |
| `AudioStream_HOST` | `127.0.0.1` | 音訊串流伺服器主機位址 |
| `AudioStream_PORT` | `2333` | 音訊串流服務連接埠 |
| `AudioStream_PASSWORD` | `youshallnotpass` | 音訊串流節點認證密碼 |
| `AUDIO_NODE_1_HOST` / `AUDIO_NODE_1_PASSWORD` | 私有 Lavalink 主機與密碼 | 選填；節點密碼只由環境變數載入，不要寫入 `settings.json` |
| `AUDIO_NODE_2_PASSWORD` / `AUDIO_NODE_3_PASSWORD` | 公開節點密碼 | 選填；分別對應 settings.json 中的第二、第三個節點 |
| `TZ` | `Asia/Taipei` | 系統時區 |

設定 `OPENAI_API_KEY` 後，Responses API 會加入供應商路由；切換到指定中轉模型時使用 `openai/<上游模型ID>`，例如 `openai/gpt-4.1-mini`。中轉站需實作 OpenAI Responses API 的 `/responses` 端點及其工具呼叫格式。配置完成並重新啟動後，模型會自動出現在 `/人工智慧 切換模型` 的選單與自動完成中，並顯示 Responses API、圖片理解及 Function Calling 描述；未設定 API Key 時不會列出。
