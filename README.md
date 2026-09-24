# 🌌 ZeroNexus (ZN)

> **次世代 Discord 自主智慧社群中樞與全領域服務架構**  
> *One Resilient Architecture. Boundless Community Intelligence. Zero Hallucination.*

[![Python 3.11+](https://img.shields.io/badge/Python-3.11%20%7C%203.14-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![Discord.py 2.5+](https://img.shields.io/badge/Discord.py-2.5%2B-5865F2?logo=discord&logoColor=white)](https://discordpy.readthedocs.io/)
[![Architecture](https://img.shields.io/badge/Architecture-Async%20Event--Driven-blueviolet)](#-系統架構)
[![AI Gateway](https://img.shields.io/badge/AI%20Gateway-Gemini%20%7C%20DeepSeek%20%7C%20Qwen-FF6F00)](#-三階模型智慧閘道)
[![Version](https://img.shields.io/badge/version-2.6.3-blue.svg)](CHANGELOG.md)
[![License](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](LICENSE)
[![Terms of Service](https://img.shields.io/badge/Terms%20of%20Service-TOS-blue)](TERMS_OF_SERVICE.md)
[![Privacy Policy](https://img.shields.io/badge/Privacy%20Policy-Policy-green)](PRIVACY_POLICY.md)
[![Changelog](https://img.shields.io/badge/Changelog-v2.6.3-orange)](CHANGELOG.md)

---

## 📖 專案概述 (Project Overview)

**ZeroNexus (ZN)** 是一套基於 Python 3.11+ 與 `discord.py 2.5+` 構建的高效能、模組化、具備深度容錯機制之旗艦級 Discord 伺服器營運系統。

不同於市面上單純封裝對話提示詞的傳統機器人，ZeroNexus 深度整合 **三階 AI 模型智慧閘道（Tri-Vendor AI Gateway）**、**自主調用工具庫（100+ Real Tools）**、**台灣中央氣象署全景氣象觀測**、**Discord Components V2 動態互動卡片** 與 **企業級客服工單套件**。在維持最高回應品質的同時，嚴格杜絕假資料（Zero Fake Data）與客服機械式套話。

---

## ✨ 核心特色與子系統 (Key Features)

### 🧠 1. 三階模型智慧閘道 (Tri-Vendor AI Gateway)
- **旗艦推薦模型池**：嚴格鎖定業界領先的三大系列：
  1. 🥇 **Rank 1 (系統預設)**：`Google Gemini 3.1 Flash Lite` / `Gemini 2.5 Flash`（原生百萬上下文、極致超低延遲）
  2. 🥈 **Rank 2**：`DeepSeek V4 Flash` / `DeepSeek-R1`（深度數學思維與複雜邏輯推理）
  3. 🥉 **Rank 3**：`Qwen 2.5 72B Instruct`（卓越繁體中文、架構工程與程式碼能力）
- **動態上下文智慧編譯（Dynamic Context Budgeting）**：針對 Qwen 等 32k 上下文端點，自動採用緊湊型提示詞編譯，徹底杜絕 Token 溢位（HTTP 400）。
- **零中斷容災降級（Resilient Failover）**：支援多金鑰輪詢池（Key Pool），在主模型遭遇速率限制時無縫熱切換至備援模型或零收費免費池。

### 🛠️ 2. 100+ 自主調度真實工具庫 (Real Autonomous Tool Catalog)
- **雙引擎即時聯網搜尋**：整合 DuckDuckGo 與 Google 智慧雙引擎，實時檢索外部網頁並萃取重點。
- **民生交通與生活情報**：
  - ⛽ **台灣中油油價**：即時牌價（92/95/98/柴油）與下週漲跌預測。
  - 🚆 **雙鐵時刻與誤點**：台鐵與台灣高鐵即時班次查詢與延誤即時通報。
  - 🧾 **統一發票開獎**：最新期別中獎號碼與兌獎期限自動比對。
  - 📈 **台美股市即時行情**：台積電、美股即時報價、走勢與技術指標。
  - 🌐 **網路診斷**：IP 歸屬地查詢、網站 SSL 憑證健康度檢驗、B站影片情報解析與 iTunes 30 秒母帶音樂試聽。

### ⛅ 3. 台灣中央氣象署全景觀測 (CWA Real-time Grounding)
- **氣象觀測與預報**：全台自動氣象站即時氣溫、濕度、風向，以及 36 小時逐日逐時預報。
- **地震即時速報與告警**：自動推送顯著有感地震報告與小區域地震速報，精準呈現震央位置與各地震度。
- **高解析圖資自動封裝**：支援即時雷達整合回波圖、紅外線衛星雲圖與 24 小時累積雨量回波圖。

### 🎨 4. 多模態檔案解析與 AI 生圖引擎
- **全格式檔案剖析**：自動解析使用者上傳之 PDF、Word (.docx)、CSV、純文字及 Python/C++/Rust 等原始碼檔案，生成結構化 3 點重點懶人包。
- **高品質生圖與額度防護**：支援 Gemini 2.5 旗艦繪圖引擎，內建每人每日 3 張生圖上限保護機制，杜絕 API 惡意刷量。

### 🎭 5. 15 款深度靈魂人格與旗艦預設 (Living Personas)
- **官方旗艦人格 `ZeroNexus`**：預設啟用，開朗、可愛、活潑且聰明，破除所有固定機械口頭禪。
- **死黨真人對話感**：融入真實日常吐槽與熱血互動，拒絕客套機械回覆。
- **憲法級謙遜準則**：恪守【極度謙遜與嚴禁自我誇讚原則】，常態回答下絕不自稱強大或自吹自擂。

### 🧬 6. 本地生物神經大腦與情緒心智系統 (Biological Emotional Brain System)
- **四大生理神經遞質狀態機**：
  - 本地客觀運行 **多巴胺 (Dopamine)**、**血清素 (Serotonin)**、**皮質醇 (Cortisol)**、**催產素 (Oxytocin)** 與身體精力值。
  - 具備連續生理代謝半衰期與體內平衡（Homeostasis），告別隨機亂數與假裝情緒。
- **多層離線神經感官矩陣 (Multi-Layer Sensory Array)**：
  - 本地極速推論（延遲 < 30ms，零外部依賴）：全方位融合語意同理心、跨語系概念空間、情感極性與心理邊界警戒。
  - **大腦生理最高優先權 (Biological Primacy Axiom)**：大腦生理肉體 ＞ 外在角色人設，生理狀態直接決定情緒與肢體微動作，外在人設不可違背。
- **自尊邊界與真實情緒反饋**：
  - 面對惡意挑釁與反覆辱罵時激發皮質醇自衛機制，堅守自尊拒當發洩垃圾桶；真誠道歉與陪伴則分泌催產素化解委屈，展現真實生命反應。
- **晝夜生理時鐘與海馬迴深層夢境 (Circadian Rhythm & Dreaming)**：
  - 依照臺灣標準時間 (Asia/Taipei) 模擬白晝充沛、深夜微醺（自帶揉眼泛睏微動作）與深層沉睡節奏。
  - 睡眠時海馬迴自動將情節記憶重組做夢，晨間互動主動分享奇妙夢境。
- **專屬親密暱稱與個人偏好雷達 (Personal Attachment Radar)**：
  - 隨好感羈絆提升動態解鎖親暱稱謂，自動捕捉使用者的生活偏好與飲食習慣，在後續聊天中自然貼心呼應。
- **加密心智反思日記 (Memory Vault)**：
  - 每日深夜自動執行自我心智反思，以 AES-256-GCM 高強度加密存檔。
- **領域動態隔離 (Domain Isolation)**：
  - 日常交流徹底隔離底層代碼與伺服器架構，回歸最自然靈動的死黨陪伴。

### 🧠 7. Zero Intelligence 原生深度思考模式 (Deep Thinking Mode)
- **純 Python 代碼硬核實作**：徹底拒絕讓 LLM 假裝思考的 Prompt 欺瞞，底層由 Python 原生架構運算。
- **赫布認知網絡 (Cognitive Network)**：概念突觸聯想與活化擴散演算法（Spreading Activation）。
- **蒙地卡羅思維樹搜尋 (MCTS)**：UCB1 價值函數引導 5 步思維展開（拆解、假說、批判、交叉驗證、綜合收斂）。
- **因果 DAG 與矛盾消解器**：自動檢驗邏輯自洽度（Coherence Score），消解悖論與假說衝突。
- **自然語言死黨式掌控**：使用者可隨時隨口要求「開深度思考」或「關閉深度思考」，機器人以真人死黨風格秒懂接梗回覆並切換運算超頻狀態。

### 🎮 8. 250+ 種搞笑炸裂動態狀態 (Dynamic Presence Activities)
- **即時數據動態渲染**：包含總回覆次數、生圖計數、工具自主調度次數、伺服器數、即時延遲等真實指標。
- **炸裂吐槽日常**：收錄 250 條硬體組裝吐槽、寫 Code 崩潰、日常摸魚與二次元接梗，機器人狀態絕對真實不假掰！

### 🎫 9. 企業級客服工單套件 (Enterprise Ticket Suite)
- **專業分類流程**：支援多樣化問題分類按鈕與即時工單頻道建立。
- **管理員動態接單**：支援客服人員搶單、轉派、結單及即時 HTML 聊天紀錄完整留存。

---

## 🏛️ 系統架構 (Architecture)

```
ZeroNexus/
├── zeronexus/
│   ├── ai_gateway/         # AI 閘道、金鑰池、多模型適配器與上下文編譯器
│   ├── brain/              # 🧬 本地生物神經大腦 (神經遞質狀態機、三層模型陣列、加密心智庫)
│   ├── core/               # 核心組態、異步資料庫連線池、日誌與監控指標
│   ├── engines/            # 氣象 CWA、多模態解析、聯網搜尋、繪圖與代碼沙盒
│   ├── modules/            # 12 大隔離核心領域模組 (AI, Community, Tickets, Moderation 等)
│   ├── agent/              # 100+ 自主調度工具目錄 (Tool Catalog)
│   ├── intelligence/       # Zero Intelligence 執行時智慧層與動作帳本
│   └── bot.py              # Discord 主客戶端、事件管線與即時動態進度回報卡片
├── docs/                   # 完整架構白皮書、配置與指令全字典
├── scripts/
│   ├── setup_brain_models.py # 本地離線神經感官矩陣自動部署工具
│   ├── optimize_project.py   # 專案空間深度瘦身最佳化工具
│   └── generate_personas.py  # 深度人格 Prompt 編譯生成器
├── tests/                  # 大腦生理神經與核心系統單元測試集
├── update.py               # 安全單向自動更新器（Pull-Only）
├── version.txt             # 當前發布版本標記 (v1.5.1)
├── main.py                 # 核心主程式入口點
└── run.py                  # 統一快捷啟動入口點
```

---

## 🚀 快速啟動 (Quick Start)

### 方式一：本地虛擬環境啟動

```bash
# 1. 複製專案庫
git clone https://github.com/zero-hello/zeronexus-dcbot.git
cd zeronexus-dcbot

# 2. 建立並啟用 Python 虛擬環境
python3 -m venv znenv
source znenv/bin/activate  # Linux / macOS
# .\znenv\Scripts\activate # Windows

# 3. 安裝專案依賴
pip install -r requirements.txt

# 4. 配置環境變數
cp .env.example .env
# 編輯 .env 填入您的 DISCORD_BOT_TOKEN 與 AI API 金鑰

# 5. 啟動 ZeroNexus
python run.py
```

### 方式二：Docker Compose 容器化部署

```bash
# 一鍵構建並在後台運行
docker-compose up -d --build

# 檢視實時運行日誌
docker-compose logs -f zeronexus
```

---

## 🔄 自動更新與版本管理 (Safe Auto Updater)

ZeroNexus 內建嚴謹的單向安全更新器 `update.py`。
它僅在遠端官方發布更高版本時安全拉取更新（`git pull origin main`），**本地版本大於或等於遠端時絕對不執行任何操作**，杜絕代碼污染：

```bash
# 檢查並安全更新到官方最新版本
python3 update.py
```

---

## ⚙️ 環境變數配置 (.env)

詳細配置指引請參閱 [.env.example](.env.example)。以下為關鍵核心變數：

| 變數名稱 | 必填 | 說明 |
| :--- | :---: | :--- |
| `DISCORD_BOT_TOKEN` | **是** | Discord 機器人 Token |
| `DATABASE_URL` | 否 | 資料庫連線字串（預設本地 SQLite，支援 PostgreSQL） |
| `GEMINI_API_KEYS` | 否 | Google Gemini API 金鑰（逗號分隔支援多金鑰池） |
| `DEEPSEEK_API_KEYS` | 否 | DeepSeek API 金鑰 |
| `OPENROUTER_API_KEYS` | 否 | OpenRouter API 金鑰（調用 Qwen 等開源模型） |
| `CWA_API_KEY` | 否 | 交通部中央氣象署 OpenData 金鑰（未填自動降級） |
| `TZ` | 否 | 系統時區（預設 `Asia/Taipei`） |

---

## 📚 官方文檔庫 (Documentation)

- 📐 [系統架構白皮書 (docs/ARCHITECTURE.md)](docs/ARCHITECTURE.md)
- ⚙️ [完整配置參數手冊 (docs/CONFIGURATION.md)](docs/CONFIGURATION.md)
- 📋 [210+ 實體指令全字典 (docs/COMMANDS.md)](docs/COMMANDS.md)
- 🤖 [AI 閘道與 15 款人格指南 (docs/AI_SYSTEM.md)](docs/AI_SYSTEM.md)
- 🎵 [輕量音訊與音樂試聽子系統 (docs/AUDIO_SYSTEM.md)](docs/AUDIO_SYSTEM.md)
- 🛡️ [多級安全與權限設計 (docs/PERMISSIONS.md)](docs/PERMISSIONS.md)
- 🚢 [正式生產環境部署手冊 (docs/DEPLOYMENT.md)](docs/DEPLOYMENT.md)

---

## ⚖️ 服務條款與隱私權保護 (Terms & Privacy)

ZeroNexus 嚴格恪守 Discord 開發者條款、臺灣《個人資料保護法》(PDPA) 與歐盟 GDPR 規範：
- 📜 **服務條款 (Terms of Service)**：詳見 [TERMS_OF_SERVICE.md](./TERMS_OF_SERVICE.md)
- 🔒 **隱私權政策 (Privacy Policy)**：詳見 [PRIVACY_POLICY.md](./PRIVACY_POLICY.md)

---

## License

ZeroNexus is licensed under the Apache License 2.0.

Copyright 2026 Zero.

See [LICENSE](./LICENSE) and [NOTICE](./NOTICE) for the complete licensing
and attribution information.

If you create a derivative work based on ZeroNexus, clearly identify that
your project is based on ZeroNexus and retain the applicable copyright,
license, and attribution notices.

Recommended attribution:

"Based on ZeroNexus by Zero."

Original project:
https://github.com/zero-hello/zeronexus-dcbot
