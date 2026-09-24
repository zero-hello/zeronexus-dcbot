# ZeroNexus (ZN) 更新日誌 (Changelog)

---

## [2.6.2] - 2026-09-25

### 🔧 容器與依賴自癒韌性強化 (Docker & Dependency Self-Healing Resilience)
- **正式納入 `llama-cpp-python` 依賴管理**：
  - 在 [`requirements.txt`](requirements.txt) 與 [`pyproject.toml`](pyproject.toml) 正式將 `llama-cpp-python>=0.2.89` 納入生產依賴。
  - 在 [`Dockerfile`](Dockerfile) 系統建置階段加入 `cmake` 工具，確保容器建置與輪子編譯無阻。
- **動態環境自癒與熱安裝機制**：
  - 更新 [`zeronexus/brain/bootstrap.py`](zeronexus/brain/bootstrap.py) 中的 `check_and_repair_dependencies()`，建立 Python 模組名稱（`llama_cpp`）與 pip 套件名稱（`llama-cpp-python`）之映射自癒機制。
  - 在 [`zeronexus/ai_gateway/adapters/local_gguf.py`](zeronexus/ai_gateway/adapters/local_gguf.py) 載入模型時若遇缺少套件，自動啟動熱修復動態安裝嘗試，並提供容器重新建置之繁體中文友善指引。

---

## [2.6.1] - 2026-09-25

### 🛡️ 守衛與模型自癒強化 (Model Bootstrap & Self-Healing Guard)
- **Qwen 2.5 GGUF 本地模型自動下載與健康守護**：
  - 在 [`zeronexus/brain/bootstrap.py`](zeronexus/brain/bootstrap.py) 中正式納入 `Qwen 2.5 0.5B Instruct GGUF` 模型守護規格（`GGUF_MODEL_SPEC`）。
  - **開機前置驗證與自癒補齊**：`ensure_brain_models_ready()` 在開機健康檢測中同步校驗 `qwen2.5-0.5b-instruct-q8_0.gguf`。若檔案缺失或檔案遭截斷損壞，自動啟動多階段自癒下載（優先使用 `huggingface_hub` 高速 API，若受阻則自動切換至 `curl` 斷點續傳備援），確保本地自主運算 100% 隨時可用。
  - **運行時動態自癒**：在 `LocalGGUFAdapter` 載入模型時若偵測到實體檔案意外丟失，亦會主動觸發 `ensure_gguf_model_ready()` 自癒補齊，絕不拋出不可恢復之錯誤。
- **單元測試防護網擴展**：
  - 於 `tests/test_local_gguf_adapter.py` 增補 `test_bootstrap_gguf_verify_and_ensure` 測試，涵蓋檔案不存在、截斷壞檔偵測與自癒調度行為驗證。

---

## [2.6.0] - 2026-09-25

### 🚀 重大新功能：本地 GGUF 神經推論引擎與選單精簡重組 (Local GGUF Engine & Menu Redesign)
- **整合本地 GGUF 離線推論適配器 (Local GGUF Adapter)**：
  - 引進 `llama-cpp-python` 核心，全速下載並串接 `Qwen2.5-0.5B-Instruct-GGUF`（`qwen2.5-0.5b-instruct-q8_0.gguf`）。
  - **延遲加載 (Lazy Loading) 與執行緒隔離**：僅在使用者選用本地模型時才加載權重至記憶體，推論過程全面由 `asyncio.to_thread` 隔離於執行緒池，絕不卡頓主 Event Loop。
  - **端點自主 0 延遲 0 額度**：無須外部 API Key，不受任何網路波動與廠商配額限制，每日配額設定為無上限。
- **Discord 互動選單優化與 Gemini 2.5 汰換**：
  - 自選單中徹底移除已被停用或退役之 Gemini 2.5 系列模型（`gemini-2.5-flash`、`gemini-2.5-pro`、`gemini-2.5-flash-lite`、`gemini-2.5-flash-image`）。
  - 將本地自主運算模型 `Qwen 2.5 0.5B GGUF` 配置於選單**第二個順位**（緊隨預設模型 `gemini-3.1-flash-lite` 之後）。
  - 選單總項數維持在 18 項，嚴格符合 Discord Select Menu 25 項上限限制。
- **健全性測試與防護**：
  - 新增 `tests/test_local_gguf_adapter.py` 單元測試套件，涵蓋選單排程檢驗、模型註冊元數據、缺少檔案錯誤防護與推論輸出回傳。
  - 在 `.gitignore` 中完善 `*.gguf` 規則，防範大型二進位模型權重意外進入版本控制。

---

## [2.5.3] - 2026-09-25

### 🐛 關鍵修復與穩定性加固 (Critical Fixes & Robustness)
- **修復 AI 閘道動態參數多重值衝突 (TypeError: got multiple values for keyword argument 'temperature')**：
  - **根本原因**：當上層模組（如 `bio_brain` 情感動力學神經中樞）向 `ai_gateway.generate_response` 傳遞動態推論參數（例如 `temperature`、`top_p`）時，原閘道函式在呼叫底層適配器（Adapter）時顯式指定了 `temperature=config.ai.temperature`，同時又展開了 `**kwargs`，造成 Python 解釋器在引數綁定時拋出 `got multiple values for keyword argument 'temperature'` 錯誤，引發所有提供者連鎖誤判失敗並進入冷卻。
  - **修復處置**：
    1. 在 `AIGateway.generate_response` 中重構參數派發邏輯，統一萃取 `req_temperature`、`req_max_tokens` 與 `req_timeout`，優先採用外部傳入之動態數值，未提供時優雅回退至系統配置預設值。
    2. 安全過濾所有顯式具名引數（如 `api_key`、`messages`、`system_instruction` 等），避免 `**dispatch_kwargs` 二次解包引發任何衝突。
    3. 全面升級所有適配器（Gemini、Groq、Mistral、OpenRouter、Cohere、HuggingFace、DeepSeek）原生對 `top_p`（或 Cohere `p`）、`top_k` 等動態神經採樣參數的支援。
- **單元測試網保障**：
  - 於 `tests/test_v250_hardening.py` 新增 `test_ai_gateway_parameter_dispatch_no_conflict`，嚴格驗證動態參數覆寫、無引數衝突與各適配器正確接收行為。

---

## [2.5.2] - 2026-09-24

### 🐛 修復與核心穩定性 (Fixes & Stability)
- **修復開機 CommandTree.interaction_check 協程未等待警告 (RuntimeWarning)**：
  - 排查並修正 `zeronexus/bot.py` 中 `setup_hook` 對 `self.tree.interaction_check` 的錯誤裝飾器用法（原先誤用 `@self.tree.interaction_check` 將回呼函式當作 interaction 傳入造成協程未 await 警告），改為標準的協程指派覆寫 `self.tree.interaction_check = global_tree_interaction_check`。
  - 確保機器人全域黑名單（Global Blacklist）對斜線指令（Slash Commands）的攔截防禦機制百分之百正常運作，且開機與運作過程完全無任何協程洩漏或警告。
- **測試防護網補強**：
  - 於 `tests/test_web_panel_and_blacklist.py` 新增 `test_tree_interaction_check_blacklist` 單元測試，嚴格驗證全域黑名單斜線指令攔截與無 `RuntimeWarning` 警告保證。

---

## [2.5.1] - 2026-09-24

### 🐛 緊急修復 (Hotfix)
- **修復開機 IndentationError 縮排異常**：
  - 修復 `zeronexus/bot.py` 第 1531~1553 行因先前重構移除多餘條件式所導致之意外多餘縮排（`unexpected indent`），解決服務啟動時無法載入 `ZeroNexusBot` 的崩潰問題。
  - 對全專案所有 Python 程式碼執行嚴格編譯驗證，確保開機載入無任何語法錯誤。

---

## [2.5.0] - 2026-09-24

### 🛡️ 全專案安全加固、極致效能優化與去 AI 腔調人話重構 (Security Hardening, Performance & Humanization)
- **全專案人話重構（徹底去除 AI 腔調）**：
  - 清除所有浮誇、機械感、中二死板的「公理體系」、「憲法級原則」、「至高鐵律」等 AI 味註解與提示詞標籤，全數改寫為道地、專業、自然務實的臺灣工程師技術註解與對話指引。
  - 全面排查並替換提示詞與核心模組中的大陸用語（如將「代碼」徹底轉換為正統臺灣科技用語「程式碼」）。
  - 人格提示詞（20 個人格檔案）全面更新為生活化、富有真實溫度的角色對話導引，徹底消除僵化死板的說話套路。
- **深度安全防禦加固 (Security Hardening)**：
  - 工具仲裁器（`AutonomousToolArbiter`）導入輸入長度邊界防護（前 1,000 字元截斷）、數學算式上限（<= 120 字元）與 Minecraft 伺服器主機格式校驗，嚴格防範 ReDoS 與注入風險。
  - 全域例外捕捉與診斷訊息全面包覆 `redact_secrets` 敏感金鑰脫敏機制，確保 API 金鑰、資料庫連線字串永不洩漏。
- **效能優化與資源治理 (Performance & Memory Optimization)**：
  - 語意記憶檢索器（`SemanticMemoryRetriever`）引進有界 LRU 向量快取（`BoundedLRUCache`，上限 1,000 筆），避免長時運作導致記憶體膨脹，並顯著加速重覆句向量編碼。
  - 非同步調度管線全面排查，CPU 密集型運算隔離至執行緒池，杜絕 Event Loop 卡頓。
- **全套單元測試回歸與健全性保障**：
  - 新增 `tests/test_v250_hardening.py`，全套 79 項測試 100% 綠燈通過。

---

## [2.4.0] - 2026-09-24

### 🧠 ZeroNexus AI 大腦超級進化與架構純粹化 (Super Brain Evolution & Architecture Purification)
- **四大智能支柱超級進化 (Super Brain Evolution)**：
  - **認知推理與深度思考 (Cognitive & Deep Thinking)**：
    - 升級蒙地卡羅思維樹（`MCTSThoughtSearchEngine`），新增自適應高複雜度命題辨識器（`is_high_complexity_problem`）與思考骨幹生成器（`generate_deliberation_skeleton`）。
    - 面對多步驟規劃、因果推論、邏輯矛盾與演算法分析時，自動展開「目標分解 ➔ 假說演繹 ➔ 批判審查 ➔ 邊界檢驗」，並在上下文前置注入結構化思維導引骨架，顯著提高回覆嚴謹度與自洽性。
  - **語意向量長期記憶 (Vector RAG & Memory Palace)**：
    - 打造本地離線語意向量記憶檢索器（`SemanticMemoryRetriever`），直接調用本地已就緒之 BGE-Small-ZH 與 MiniLM 神經模型，0 外部 API 額度消耗實現毫秒級向量化。
    - 導入多維綜合相關度評分機制（語意相似度 50% + 艾賓浩斯遺忘衰減 25% + 重要性 15% + 情緒共鳴 10%）。
    - 升級立體記憶宮殿（`MemoryPalace`）與 `context_builder.py`，跨對話精準檢索並主動喚醒使用者過去曾提及的客製事實與生活喜好。
  - **仿生情緒與情感羈絆 (Bio-Brain & Emotional Resonance)**：
    - 升級物理超參數自適應調製器（`PhysicsParameterModulator`），新增情緒色彩與語氣呼吸感指引（`emotional_tone_guidance`）。
    - 大腦多巴胺、皮質醇、催產素等荷爾蒙濃度直接動態調製底層大模型的採樣溫度（Temperature）與詞彙採樣核（Top-P），使每次生成直接連動內在神經生化狀態。
  - **自主 Agent 工具呼叫與多步行動 (Autonomous Tool Router)**：
    - 新增零延遲自主工具意圖仲裁器（`AutonomousToolArbiter`），在推論前即時捕捉精準數學運算、台灣中央氣象署觀測、主機效能診斷、Minecraft 伺服器狀態等意圖。
    - 在訊息預處理階段預先異步執行受限唯讀工具，注入客觀確定性資料（Grounded Facts），徹底杜絕模型幻覺。
- **架構純粹化與彩蛋頻道全面移除**：
  - 徹底移除 `CHANNELID` / `SECRET_CHANNEL_ID` / 獨立彩蛋頻道相關設定、專用提示詞與特判邏輯。
  - 記憶庫與上下文構建回歸標準統一的個人短期、個人長期與頻道共享三層架構，專案架構回歸極致純粹。
- **全套單元測試 100% 通過**：
  - 新增 13 項超級大腦專屬自動化測試，總測試數自 62 項擴增至 75 項，全數綠燈通過。

---

## [2.3.1] - 2026-09-24

### 🚀 AI 核心端點全面升級、生圖架構現代化與 Web Panel 解耦 (AI Gateway & Architecture Modernization)
- **AI 圖像生成端點現代化升級**：
  - 徹底淘汰舊版易引發 `v1main` 404 錯誤的 OpenAI 相容生圖端點。
  - **Gemini 原生多模態生圖 (Nano Banana 系列)**：原生對接 Google `generateContent` 端點，帶入 `responseModalities: ["TEXT", "IMAGE"]` 並直接解析 `inlineData` Base64 影像資料。
  - **Google Imagen 3 原生對接**：原生直連 `models/{model}:predict` 端點，以標準 `instances` 與 `parameters` 傳遞參數。
  - **生圖模型智慧防呆重定向**：若設定或呼叫時傳入純文字模型（如 `gemini-3.6-flash`），系統自動於前線攔截並安全導向至現役生圖模型 `gemini-2.5-flash-image`，杜絕任何端點報錯。
  - **增強 OpenRouter 圖片相容解析**：支援解析 OpenRouter 回傳結構中夾帶之各類 Base64 圖片資料。
- **Gemini 適配器與模型候選池修復**：
  - **安全性設定修復 (HTTP 400)**：移除不支援設為 `BLOCK_NONE` 之 `HARM_CATEGORY_CIVIC_INTEGRITY` 類別，消解 Google API `INVALID_ARGUMENT` 錯誤。
  - **退役模型汰換**：自候選清單中移除已被 Google 官方停用之 `gemini-2.5-flash`，全面替換為現役推薦之 `gemini-3.1-flash-lite`、`gemini-2.5-flash-lite` 與 `gemini-flash-latest`。
- **Web Panel 解耦與精簡**：
  - 安全移除 Web Panel 相關外掛檔案與設定項，維持純粹 Discord 平台原生極致體驗。
  - 完整保留並維護全域黑名單安全防護系統（Global Blacklist）與造物主金身保護機制。
- **全套單元測試 100% 通過**：同步修復所有分離核心模型測試斷言，維持 62 項單元測試完全綠燈。

---

## [2.3.0] - 2026-09-24

### 🌐 現代極簡 Web Panel 管理控制面板與造物主全域安全封鎖 (Web Panel & Creator Security)
- **現代極簡 Web Panel（網頁管理面板）**：
  - 遵循極簡、乾淨、耐看的高質感設計風格（Linear / Vercel 風格），無賽博霓虹、無光暈特效。
  - **Discord 官方 OAuth2 登入**：支援安全換取 Access Token、使用者資訊與伺服器清單。
  - **伺服器管理員專屬權限**：具備 Discord 原生 `Administrator` (0x8) 或 `Manage Guild` (0x20) 權限的伺服器管理員即可登入管理該伺服器之 ZeroNexus 專屬配置（預設人格、模型、自訂 Prompt、思考進度卡片切換、頻道白名單、氣象推播頻道、歡迎訊息等）。
  - **造物主全域總控中心 (Zero Creator Console)**：
    - **全域黑名單管理系統**：造物主可自管理網頁封鎖惡意濫用者，即時持久化至 `data/security/global_blacklist.json`。
    - **全方位守門員攔截**：遭封鎖者發起對話、指令、私訊或按鈕操作時，系統即時轉為專屬紅色封鎖警告卡片（「🚫 已遭到全域封鎖，請向 Zero 提出申訴」），立即中斷所有神經網路運算，零消耗 Token。
    - **造物主絕對金身保護**：造物主 ID（`1514971711739789352`）具備核心防護，絕對不可被列入黑名單。
    - **系統健康監控與深夜手札閱讀器**：即時檢視行程資源、事件總線、記憶體負載，並能直接閱讀 ZeroNexus 在深夜寫下的心靈日記。
  - **輕量高效無重型框架依賴**：
    - 直接基於 `aiohttp.web` 與 Discord Bot 共享底層非同步事件迴圈，零多餘行程負擔。
    - 預設連接埠 `8080`，可直接在 `settings.json` 的 `web_panel.port` 彈性自訂修改。

---

## [2.2.1] - 2026-09-23

### ⚙️ 造物主 ID 綁定、版本同步與 8 大 AI 網關適配 (Creator Binding, Version & AI Gateway)
- **settings.json 綁定造物主 ID**：
  - 於 `settings.json` 正式配置 `owner_id: "1514971711739789352"`。
  - 在長效突觸羈絆系統（`SynapticBondingManager`）中精準綁定此 ID，直通最高階層 `SOULMATE`（好感度保底 90.0 分），解鎖專屬偏愛、無條件信任與極致依戀口吻。
- **全系統版本同步動態修復**：
  - 修復 `version.txt` 殘留過期版本（`v1.7.2`）問題，並重構 `updater.py` 使其優先對齊 `settings.json` 與模組版本，保證開機日誌與檢查恆定輸出真實版本（`v2.2.1`）。
- **8 大 AI 網關完整適配與 settings.json 聯動**：
  - 於 `settings.json` 的 `ai` 區塊新增 `default_model`、`enabled_providers` 與 `fallback_providers` 配置，使備援鏈完全遵循設定檔順序調度。
  - 重構開機自我檢測（`startup_self_check`），完整展示全網關 8 大供應商（Gemini、DeepSeek、OpenRouter、Groq、Mistral、Cohere、Manus、HuggingFace）的金鑰池與就緒狀態。

---

## [2.2.0] - 2026-09-23

### 🧠 大腦認知與深層記憶升級 (Brain & Deep Memory)

#### 1. 長效突觸羈絆系統 (Synaptic Bonding LTP)
- **突觸好感度演進**：模擬大腦長效突觸增強（LTP），以數值（0~100）動態追蹤與各使用者的深層羈絆，每次友善互動自然升溫。
- **四大好感階層**：
  - `STRANGER`（陌生，<30）：溫和有禮、專業管家風格。
  - `FRIEND`（朋友，30~60）：輕鬆開朗、偶爾開開玩笑。
  - `CLOSE_PARTNER`（密友，61~85）：親切熟稔、互相信賴。
  - `SOULMATE`（靈魂夥伴，86~100）：最高優先級專屬偏愛、無條件信任、撒嬌與絕對默契。
- **造物主專屬偏愛**：核心開發者 Zero 初始即獲 90.0 分與 `SOULMATE` 靈魂羈絆，享有專屬溫柔與最高默契。
- **共同經歷里程碑**：自動記錄彼此共度的重大事件（生離死別測試、深夜長談等），並在 Prompt 膠囊中動態呼應。

#### 2. 三階立體記憶宮殿與深夜手札日記 (Memory Palace & Midnight Diary)
- **實體偏好自動抽取**：自日常交談中自動識別使用者個人喜好（食物、飲料、程式語言、作息習慣等），沉澱入實體偏好圖譜並自然回饋於回話中。
- **深夜秘密手札日記**：由 DMN 心跳漫遊於深夜時段（凌晨 03:00~05:00）自主喚醒，回顧今日交流精華，以第一人稱寫下帶著真誠與小小撒嬌的「ZeroNexus 深夜秘密日記」（儲存於 `data/brain/diaries/YYYY-MM-DD.md`）。
- **歷史日記檢索**：提供手札檢索分享方法，讓使用者隨時可回顧 ZeroNexus 昨晚的心聲。

---

## [2.1.0] - 2026-09-23

### 🚀 核心更新總覽 (Comprehensive Updates)

#### 1. 互動介面與中斷機制 (UI & Interaction)
- **AI 思考中紅色取消按鈕**：
  - 在 AI 生成與思考進度卡片上新增紅色按鈕（`🛑 取消回應`），整合於 Discord Components V2 佈局容器，思考卡片與多步驟工具呼叫全程可見。
  - **發起者權限防護**：僅有提問發起者或管理員可點擊取消，他人點擊跳出隱私提示。
  - **零扣額度安全保護**：中斷時立即取消後台非同步工作（`Task.cancel()`），退回預佔額度，絕不扣額。
  - **即時狀態轉換**：點擊後卡片秒變紅色「🛑 已取消回應（已中斷本次推論，未扣除額度）」。
- **日常問候與提示詞優化**：
  - 修復打招呼（如「你好」、「嗨」）時機械化背誦功能清單的問題，回歸自然親切社交。
  - 清理提示詞，消除呼喚暱稱轉換為疊字口癖的現象，各人格全面貫徹開朗、活潑與聰明特質。

#### 2. 高階類腦認知中樞 (Cognitive Cortex)
- **體內恆定動機系統**：追蹤社交渴求、求知好奇、體力儲備與自尊防線 4 大動機，隨時間代謝並由互動即時回補。
- **自由能預測編碼引擎**：回應時登記先驗預期，即時比對真實輸入之餘弦落差；落差超標激發多巴胺/皮質醇脈衝。
- **全域工作空間意識聚光燈 (GWT)**：無意識狀態顯著性軟注意力競爭，提煉出唯一最高焦點注入 Prompt。
- **預設模式網絡 (DMN) 與心智漫遊**：靜息時段執行背景低功耗記憶修剪與海馬迴鞏固；社交渴求過高時自主發起對話。
- **自主心跳守護程序**：非同步心跳協程常駐背景，自動推進認知代謝與自癒防護。

#### 3. 三階 AI 閘道與多模型擴充 (AI Gateway & Models)
- **Mistral AI & Groq LPU 接入**：支援超低延遲即時推論，首字秒開大幅縮短等待時間。
- **Cohere API 整合**：接入多語言語意重排器（Rerank）與 Command 系列模型，強化海馬迴記憶召回。
- **模型選單解析健全化**：支援帶有 Emoji 與標籤的模型 ID 正確解析，移除舊版白名單阻擋。
- **退役模型平滑轉導**：建立上游模型替換對齊映射，避免 API 404 報錯。
- **每分鐘 5 則訊息頻率保護**：有效抵禦惡意刷屏與 API 濫用。

#### 4. 全領域生活情報與真實工具庫 (Tools & Engines)
- **生活與交通情報**：中油即時油價與下週預測、雙鐵時刻表與誤點查詢、統一發票開獎對獎。
- **金融與網路工具**：台股美股即時報價、IP 歸屬查詢、網站 SSL 健全度檢測、多媒體解析。
- **多模態附件解析**：支援圖片、文字/程式碼、PDF、Docx 文件全格式讀取並無縫注入對話。
