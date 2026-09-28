# ZeroNexus (ZN) 更新日誌 (Changelog)

---

## [2.9.8] - 2026-09-28

### 📊 重製 `/當前狀態` 系統資訊面板
- 移除所有 AI API Key、金鑰池與金鑰數量資訊，改顯示非敏感的 AI 服務成效。
- 新增整體健康度、版本／運行時間、Discord Gateway 延遲、主機資源、資料庫與快取健康、模組狀態。
- 增加可用模型數、AI 成功／失敗／備援、平均延遲、近期 P95、Token 使用量與熱門 Function Calling 工具統計。
- 新增狀態面板不洩露金鑰資訊的回歸測試；同步更新合法版本號至 `2.9.8`。

## [2.9.7] - 2026-09-27

### 🎮 2048 控制盤中央方塊與手動結算
- 完成 3×3 方向盤四角及中央禁用方塊；移除棋盤內方向鍵說明行。
- 在「重新開始」旁新增「結束遊戲」按鈕；手動結束及無合法移動時結算分數並移除所有控制按鈕。
- 更新 README 操作說明並新增結束／版面回歸測試。
- 同步更新所有目前版本標記至 `2.9.7`。

## [2.9.7] - 2026-09-27

### 🎮 2048 無效移動與結算畫面改善
- 無效方向移動不再回傳私人提示；保留公開棋盤且分數、步數與棋盤狀態完全不變。
- 手動結束或棋盤無法移動時保存成績，公開更新最終棋盤與分數，移除整組互動按鈕。
- 加入無效移動與結算後移除 View 的回歸測試。
- 同步更新所有目前版本標記至 `2.9.7`。

## [2.9.5] - 2026-09-27

### 🎮 新增完整 2048 互動遊戲與伺服器排行榜
- 新增 `/娛樂 2048`，支援 4x4 棋盤、方向按鈕、合併計分、無效步驟保護、達成 2048 提示與繼續挑戰。
- 新增 `/娛樂 2048排行榜`，每個伺服器獨立排名玩家最佳分數，並保存最高方塊、最佳步數與遊玩局數。
- 新增遊戲成績資料表與核心規則測試，測試合併、移動、生成、遊戲結束及指令註冊。
- 遊戲 UI 公開顯示但只允許開局玩家操作；方向控制改成 3x3 方位鍵盤，四角使用禁用方塊。
- 加入依分數及最高方塊升級的鼓勵等級；2048 方塊為里程碑，可繼續挑戰。
- 成績寫入加鎖及伺服器/玩家唯一限制，重開與逾時會結算前一局，避免並行重複排行資料。
- 新增按鈕位置、禁用格、互動者限制與等級回歸測試。
- 同步更新所有目前版本標記至 `2.9.5`。

## [2.9.3] - 2026-09-27

### 🔴 修復 Agent 與 Zero Intelligence 循環匯入造成的啟動崩潰
- 將 Agent 對 DynamicToolProjector 的引用改為執行任務時延遲匯入，避免套件初始化期間相互引用。
- 新增乾淨子程序啟動匯入測試，涵蓋 bot/deep-thinking、Agent 與智慧投影器載入順序。
- 同步更新所有目前版本標記至 `2.9.3`。

## [2.9.2] - 2026-09-27

### 🔴 Zero 智慧工具平台擴充與伺服器隱私防護
- 執行時實際註冊 **272 個唯一 Function Calling 工具**，新增 Discord 可見資料／頻道分析與 AI 寫作、分析、程式輔助及隱私工具。
- AI 工具目錄拆分為 Discord 與 AI workflow 模組，能力提示由執行時工具登錄表產生。
- 一般訊息與斜線 AI 對話共用工具執行路由；短句明確查詢可觸發工具，問候維持零工具快速回覆。
- Discord 查詢只限目前伺服器，並檢查 Bot 與提問者的頻道可見權限；成員資料限可見頻道範圍，頻道分析改為私密回覆。
- 頻道歷史工具 fail-closed，缺少提問者上下文、跨伺服器或權限不足時拒絕讀取。
- 整理 scripts 為用途子資料夾，保留舊路徑相容啟動器。
- 新增工具數量、路由、頻道權限與執行器回歸測試。
- Agent 改為先投影授權工具、限制工具數與總執行時間；不再 fuzzy-match 未授權工具或以無關診斷當預設答案。
- 新增 Function Calling 各工具成功率、錯誤率、逾時數與平均耗時指標。
- 同步更新所有目前版本標記至合法三段式版本 `2.9.2`。

## [2.8.15] - 2026-09-27

### 🔴 修復 Lavalink 公開節點候選清單被錯誤清空
- 修正公共節點抓取後僅保留私人設定中已配置憑證主機的過濾錯誤。
- 改為直接探測抓取到且包含主機與密碼的公共節點，只連線健康節點。
- 新增公開節點回退探測與連線回歸測試。
- 同步更新所有目前版本標記至 `2.8.15`。

## [2.8.14] - 2026-09-27

### 🔴 修復 AI 指令群組超出 Discord 子指令上限
- 將「對話摘要」改為頂層 `/對話摘要`，不再佔用 `/人工智慧` 群組的第 26 個子指令。
- 新增 Cog 註冊測試，確保 AI 群組不超過 Discord 的 25 子指令限制。
- 同步更新所有目前版本標記至 `2.8.14`。

## [2.8.13] - 2026-09-27

### 🔴 AI 附件安全與對話摘要
- `/人工智慧 對話` 圖片改用共用附件安全管線，驗證實際檔案格式、大小與像素上限，避免偽 MIME 或大型圖片直接進入模型請求。
- 新增 `/人工智慧 對話摘要`，可依最近 3–30 回合整理主題、決定與待處理事項，使用者私密查看且不改寫原始記錄。
- 摘要輸入加入字元上限及單訊息截斷，避免大量歷史內容增加延遲或超過模型上下文。
- 新增摘要上下文安全邊界回歸測試；同步更新所有目前版本標記至 `2.8.13`。

## [2.8.12] - 2026-09-27

### 🔴 Lavalink 連線韌性與開機效能
- Lavalink 健康節點探測及公用節點抓取移至背景重試，不再阻塞 Discord 啟動；探測逾時縮短並並行抓取公用清單。
- 節點探測失敗時不再把離線節點交給 Wavelink，避免 DNS 錯誤造成重連風暴；重試採指數退避。
- 本地 ONNX 模型下載與載入移至 Discord 登入後背景初始化，移除啟動時重複初始化模型的流程。
- Lavalink 密碼改由環境變數供應，移除設定檔內的明文服務密碼。
- 加入 Lavalink 無健康節點時不呼叫 Wavelink 的回歸測試。
- 同步更新所有目前版本標記至 `2.8.12`。

## [2.8.9] - 2026-09-27

### 🔴 本地推論逾時資源控制與模型路徑防護
- 本地 GGUF 模型名稱限制為 basename，避免路徑片段逃逸模型目錄。
- 對同步原生推論逾時使用執行緒工作仍在背景執行的情況加入單併發閘門，避免逾時請求累積佔滿執行緒池。
- 同步更新所有目前版本標記至 `2.8.9`。

## [2.8.8] - 2026-09-27

### 🔴 安全性、穩定性與資源界限強化
- Redis 快取改用 JSON 序列化，移除不安全的 pickle 反序列化；關閉時會回收清理背景任務。
- 修正附件影像格式驗證，加入每則訊息附件數、總大小與像素上限，並修復缺少 asyncio 匯入的執行錯誤。
- 啟動時將阻塞式大腦模型自檢移至工作執行緒；訊息去重與使用者提示快取加入 TTL 清理及硬容量。
- 修正訊號關機流程等待競態、維護任務逾時處理，並限制 llama.cpp 壓縮檔解壓路徑與項目類型。
- 本地 GGUF 模型名稱限制為 basename，並限制原生推論併發，避免超時後的不可取消執行緒持續堆積。
- 新增快取安全、舊 Redis pickle 拒絕及附件格式／大小限制的回歸測試。
- 同步更新所有目前版本標記至 `2.8.9`。
- 語意記憶的無模型備援向量改用穩定雜湊與 cosine 相似度，修正跨程序結果不穩定及相似度排序失真。

## [2.8.7] - 2026-09-27

### 🔴 移除 BRAIN_MASTER_KEY 環境變數依賴並強化日記加密
- 記憶庫不再讀取 `BRAIN_MASTER_KEY`；改用資料庫旁權限為 `0600` 的本地隨機金鑰檔。
- 移除不安全的 XOR 日記加密降級；缺少 `cryptography` 時拒絕寫入或解密。
- 同步更新所有目前版本標記至 `2.8.7`。

## [2.8.6] - 2026-09-27

### 🔴 修復版本號不同步與 BRAIN_MASTER_KEY 阻塞啟動
- 更新 [`zeronexus/settings.json`](zeronexus/settings.json)：版本號 2.7.9 → 2.8.6
- 更新 [`zeronexus/core/config.py`](zeronexus/core/config.py)：版本號 2.7.9 → 2.8.6
- 更新 [`zeronexus/__init__.py`](zeronexus/__init__.py)：版本號 2.7.9 → 2.8.6
- 更新 [`README.md`](README.md)：版本徽章 2.7.8 → 2.8.6
- 更新 [`zeronexus/brain/memory_vault.py`](zeronexus/brain/memory_vault.py)：
  - 缺少 BRAIN_MASTER_KEY 時自動生成安全隨機金鑰並持久化，不再阻塞啟動

---

## [2.8.5] - 2026-09-27

### 🔴 緊急修復：NameError 導致系統無法啟動
- 更新 [`zeronexus/models/user.py`](zeronexus/models/user.py)：
  - 修正 `AIModelQuotaRecord` 複合索引使用 `Index()` 但未匯入的 NameError
  - 在 SQLAlchemy import 中補上 `Index`

---

## [2.8.4] - 2026-09-27

### 🔴 定期維護機制
- 新增 [`zeronexus/core/maintenance.py`](zeronexus/core/maintenance.py)：
  - 建立自動化定期維護排程器
  - 每日維護：清理過期快取、記憶與費率限制窗口
  - 每週維護：安全審計（資料庫連線池、排程器狀態、快取命中率）
  - 每月維護：完整審計（依賴套件安全性、系統健康檢查）

---

## [2.8.3] - 2026-09-27

### 🔴 Brain 子系統修復（並發安全 + 數值一致性）
- 更新 [`zeronexus/brain/neuro_transmitters.py`](zeronexus/brain/neuro_transmitters.py)：
  - 加入 `threading.RLock` 保護 `apply_homeostasis_decay` 與 `stimulate` 的 read-modify-write 操作
  - 精力恢復公式加入上限保護，避免極端溢位
- 更新 [`zeronexus/brain/emotion_state_engine.py`](zeronexus/brain/emotion_state_engine.py)：
  - 加入 `threading.RLock` 保護 `apply_time_decay` 與 `update_state`
  - 補全 `social_need` 與 `energy` 的半衰期定義
- 更新 [`zeronexus/brain/core.py`](zeronexus/brain/core.py)：
  - `trigger_nightly_reflection` 改用臺灣時區日期
- 更新 [`zeronexus/brain/circadian.py`](zeronexus/brain/circadian.py)：
  - 修正深夜時段邏輯判斷

### 🔴 Intelligence 子系統修復（並發安全 + 狀態管理）
- 更新 [`zeronexus/intelligence/cognitive_network.py`](zeronexus/intelligence/cognitive_network.py)：
  - 加入 `threading.RLock` 保護活化能量操作
  - 加入 `_auto_decay()` 自動衰減機制，防止認知網絡飽和
- 更新 [`zeronexus/intelligence/deep_thinking_controller.py`](zeronexus/intelligence/deep_thinking_controller.py)：
  - `active_contexts` 改用 `OrderedDict` + TTL 淘汰機制
  - 加入 `threading.RLock` 保護並發修改
- 更新 [`zeronexus/intelligence/thought_search_mcts.py`](zeronexus/intelligence/thought_search_mcts.py)：
  - 加入 `max_iterations` 與 `max_depth` 安全上限

---

## [2.8.2] - 2026-09-27

### 🔴 God Class 拆分完成
- 更新 [`zeronexus/bot.py`](zeronexus/bot.py)：
  - 引用 `zeronexus.core.message_editor.safe_edit_status_message`
  - 引用 `zeronexus.engines.attachment_processor.ingest_attachments`
  - 完成 God Class 拆分的第一步

### 🔴 Scheduler 修復
- 更新 [`zeronexus/core/scheduler.py`](zeronexus/core/scheduler.py)：
  - `remove_job` 現在會取消正在執行的任務實例

### 🔴 Database Session 修復
- 更新 [`zeronexus/core/database.py`](zeronexus/core/database.py)：
  - 簡化 `finally` 區塊的 session 關閉邏輯
  - 避免巢狀 `asyncio.shield` 在極端 CancelError 情境下導致 session 未被正確關閉

---

## [2.8.1] - 2026-09-27

### 🔴 事件迴圈保護（Blocking I/O 修復）
- 更新 [`zeronexus/ai_gateway/gateway.py`](zeronexus/ai_gateway/gateway.py)：
  - `sanitize_perspective` 改用 `asyncio.to_thread` 非同步執行，避免阻塞事件迴圈
- 更新 [`zeronexus/ai_gateway/context_builder.py`](zeronexus/ai_gateway/context_builder.py)：
  - 新增 `async_enforce_taiwan_localization` 非同步版本，避免阻塞事件迴圈
- 更新 [`zeronexus/modules/developer/cog.py`](zeronexus/modules/developer/cog.py)：
  - `cmd_sysinfo` 的 psutil 操作改用 `asyncio.to_thread` 非同步執行

### 🔴 資料庫查詢優化（N+1 修復）
- 更新 [`zeronexus/ai_gateway/context_builder.py`](zeronexus/ai_gateway/context_builder.py)：
  - 長期記憶寫入改為批量載入 + 本地字典查找，消除 N+1 查詢問題
  - 記憶計數改用本地 `len()` 而非每次查詢 DB

### 🔴 安全防護強化
- 更新 [`zeronexus/security/sanitizer.py`](zeronexus/security/sanitizer.py)：
  - 新增 AWS Access Key (`AKIA...`) 遮蔽支援
  - 新增 Slack Token (`xox...`) 遮蔽支援
  - 新增 JWT Token (`eyJ...`) 遮蔽支援

### 🔴 快取管理優化
- 更新 [`zeronexus/core/cache.py`](zeronexus/core/cache.py)：
  - 新增背景清理任務（每 5 分鐘自動清理過期項目）
  - 新增 `close()` 方法正確關閉背景任務

### 🔴 並發控制強化
- 更新 [`zeronexus/engines/web_client.py`](zeronexus/engines/web_client.py)：
  - 新增 `asyncio.Semaphore(5)` 限制並發搜尋數，防止連線池耗盡

### 🔴 God Class 拆分準備
- 新增 [`zeronexus/core/message_editor.py`](zeronexus/core/message_editor.py)：
  - 提取 `_safe_edit_status_message` 為獨立模組
- 新增 [`zeronexus/engines/attachment_processor.py`](zeronexus/engines/attachment_processor.py)：
  - 提取 `_ingest_attachments` 為獨立模組

---

## [2.8.0] - 2026-09-27

### 🔴 CWA 子系統全面修復（連線逾時、斷路器、請求去重）
- **根本原因修復**：
  - 更新 [`zeronexus/engines/cwa_client.py`](zeronexus/engines/cwa_client.py)：
    - `keepalive_expiry` 由 15.0s 提升至 300.0s，避免每次輪詢都重新建立 TCP 連線
    - `connect` timeout 由 15.0s 提升至 30.0s，`read` timeout 由 20.0s 提升至 60.0s
    - 加入指數退避 + 隨機 jitter（1~60 秒），避免雷群效應
  - 更新 [`zeronexus/engines/cwa_notifier.py`](zeronexus/engines/cwa_notifier.py)：
    - 加入斷路器（Circuit Breaker）模式：連續失敗 10 次後暫停 10~600 秒
    - 加入請求去重機制（`_poll_in_progress`），防止多個輪詢任務同時飛行
  - 更新 [`zeronexus/bot.py`](zeronexus/bot.py)：
    - 地震輪詢間隔由 60s 提升至 120s，降低 CWA API 觸發冷却的風險

### 🔴 安全性強化
- **加密金鑰安全**：
  - 更新 [`zeronexus/brain/memory_vault.py`](zeronexus/brain/memory_vault.py)：
    - 移除 `DISCORD_BOT_TOKEN` 作為加密種子，改用獨立 `BRAIN_MASTER_KEY`
    - 移除非安全的 hardcoded fallback 種子，未設定時拋出異常
- **開發者指令保護**：
  - 更新 [`zeronexus/modules/developer/cog.py`](zeronexus/modules/developer/cog.py)：
    - `cmd_eval` 加入危險操作黑名單過濾（禁止 os.system、subprocess、open 等）
    - 加入 30 秒執行逾時保護
- **並發安全**：
  - 更新 [`zeronexus/security/ratelimit.py`](zeronexus/security/ratelimit.py)：
    - `SlidingWindowRateLimiter` 加入 `threading.Lock` 保護
  - 更新 [`zeronexus/security/blacklist.py`](zeronexus/security/blacklist.py)：
    - `GlobalBlacklistManager` 加入 `threading.RLock` 保護

### 🔴 效能與記憶體修復
- **Memory Leak 修復**：
  - 更新 [`zeronexus/ai_gateway/quota_service.py`](zeronexus/ai_gateway/quota_service.py)：
    - `_reminded_thresholds` 加入每日清理機制（`_daily_cleanup_if_needed`）
    - `_model_in_flight` 字典計數歸零時刪除鍵，防止無限增長
- **Database 索引優化**：
  - 更新 [`zeronexus/models/user.py`](zeronexus/models/user.py)：
    - `AIModelQuotaRecord` 新增 `(user_id, model_id, date_str)` 複合索引

---

## [2.7.8] - 2026-09-26

### 🛡️ 開機指令同步防卡死機制、Presence 狀態除錯與 CWA 網路連線寬限 (Resilience & Stability Hardening)
- **開機指令樹同步 30s 逾時防護與背景自癒重試**：
  - 更新 [`zeronexus/bot.py`](zeronexus/bot.py)：
    - 在 `setup_hook` 的 `self.tree.sync()` 加上 `asyncio.wait_for(timeout=30.0)` 保護，若遭遇 Discord Gateway 限流或網路抖動，不再卡死開機程序 5 分鐘，自動轉由登入就緒後在背景非同步自癒重試 (`_background_retry_sync`)。
- **Presence 動態輪播崩潰修復與傳輸抑制**：
  - 更新 [`zeronexus/bot.py`](zeronexus/bot.py)：
    - 修復開機與斷線重連時 `self.latency` 呈 `inf` 導致 `OverflowError: cannot convert float infinity to integer` 的崩潰問題。
    - 增加 WebSocket 連線就緒與閉合狀態感知，徹底抑制重連時 `Cannot write to closing transport` 的日誌刷屏。
- **中央氣象署 CWA 連線握手寬限**：
  - 更新 [`zeronexus/engines/cwa_client.py`](zeronexus/engines/cwa_client.py)：
    - 將 TCP/TLS 連線逾時由 10.0s 適度放寬至 15.0s，減少境外託管伺服器連線台灣氣象署因網路延遲造成的逾時警告。

---

## [2.7.7] - 2026-09-26

### 🚀 賽揚雙核記憶體頻寬解套、Stop 停止詞防複讀與秒級推論監測 (Dual-Core Cache & Stop Defense)
- **賽揚雙核黃金執行緒調度**：
  - 更新 [`zeronexus/ai_gateway/adapters/local_gguf.py`](zeronexus/ai_gateway/adapters/local_gguf.py)：
    - 調整執行緒為賽揚實體雙核架構最適之 2 緒 (`threads = max(1, min(os.cpu_count() or 1, 2))`)，解決 4 執行緒在 2MB L3 快取賽揚主機上互相踩踏記憶體頻寬與頻繁 Context Switch 的瓶頸。
    - 啟用 `--cache-reuse 256` 提示詞 KV 快取重用，大幅縮短 Prompt 評估耗時。
- **Stop Sequences 停止詞防護網 (杜絕無窮複讀與自問自答)**：
  - 加入 `<|im_end|>`, `<|endoftext|>`, `\nUser:`, `\n使用者：` 嚴格停止標籤。
  - 將日常推論上限調節為 `min(max_tokens, 120)`，解決 0.5B 小模型在回答完後因缺乏停止標籤而一路自言自語填滿 256 tokens 導致耗時 100 秒的致命問題。
- **對話歷史修剪至最近 1 輪 (極限壓縮 Prompt Tokens)**：
  - 本地模型推論僅傳入最近 2 則對話 (1 輪交互)，將 Prompt 評估總量壓縮在 80~120 tokens 以內，1~2 秒內完成 Prompt 評估。
- **即時推論效能日誌 (TPS 監控)**：
  - 推論完成時自動記錄 `耗時`、`Prompt Tokens`、`生成 Tokens` 與 `Tokens/s (tps)` 速率指標，推論瓶頸一目了然。

---

## [2.7.6] - 2026-09-26

### ⚡ 本地推論全核代碼加速與 240s 逾時防護 (Full-Core Code Acceleration & 240s Anti-Timeout)
- **外層 240s 逾時保護，杜絕中斷**：
  - 更新 [`zeronexus/bot.py`](zeronexus/bot.py)：
    - 針對本地模型 (`local`, `qwen2.5-0.5b`, `gguf`) 自動將請求逾時時間由原先雲端預設之 70s 放寬至 240s，徹底解決賽揚 CPU 運算時遭外層提前掐斷拋出 `AI response generation timed out` 的問題。
- **全核調度與執行緒優先度最佳化**：
  - 更新 [`zeronexus/ai_gateway/adapters/local_gguf.py`](zeronexus/ai_gateway/adapters/local_gguf.py)：
    - 解除原先最大 2 核限制，全速調度可用 CPU 核心 (`threads = max(1, os.cpu_count() or 2)`)。
    - 加入批次評估執行緒旗標 `-tb`，並啟用 `--prio 2 --prio-batch 2` 提高行程排程優先級。
- **KV Cache 與批次處理向量化加速**：
  - 上下文由 8192 最佳化調整為 2048 (`-c 2048`)，節省 75% 龐大記憶體存取與計算開銷。
  - 啟用 `-b 512 -ub 256 --parallel 1`，成批向量化評估 Prompt，單一槽位全力計算。
- **提示詞極限精煉與歷史修剪 (Prompt Optimization)**：
  - 系統提示詞長度精煉至 350 字元，對話歷史由 8 則縮為 4 則（2 輪交互），Prompt Tokens 暴減 85%，在無 AVX2 CPU 上的 Prompt Evaluation 耗時從 100+ 秒銳減至數秒！
  - 檢測到伺服器參數不符時自動進行熱重啟套用加速配置。

---

## [2.7.5] - 2026-09-26

### 🚀 新增 Qwen 2.5 0.5B Instruct Q4_K_M 極速輕量化本地模型 (Q4_K_M Fast Local Edge Model)
- **選單排序與清楚標示**：
  - 更新 [`zeronexus/ui/model_select_view.py`](zeronexus/ui/model_select_view.py)：
    - 將 `qwen2.5-0.5b-instruct-q4_k_m` 放置於選單第三個選項（index 2），緊接在 `gemini-3.1-flash-lite` 與 `qwen2.5-0.5b-instruct-q8_0` 之後。
    - 嚴格標示清楚精確規格：第二項明確標記為 `[8-bit/Q8_0 高精度]`，第三項明確標記為 `[4-bit/Q4_K_M 極速推薦]`，便於使用者依設備負載快速挑選。
- **全套自癒下載與完整規格註冊**：
  - 更新 [`zeronexus/brain/bootstrap.py`](zeronexus/brain/bootstrap.py)：
    - 擴充 `GGUF_MODELS_SPEC` 字典，新增 Q4_K_M 專屬 HuggingFace 下載來源（約 350MB，門檻 300MB）與直鏈備援。
    - 支援 `match_gguf_spec()` 智慧匹配路徑與模型識別碼。
    - `download_gguf_model()` 與 `ensure_gguf_model_ready()` 升級支援指定模型規格與自癒補齊。
- **適配器多模型切換與平滑熱重啟**：
  - 更新 [`zeronexus/ai_gateway/adapters/local_gguf.py`](zeronexus/ai_gateway/adapters/local_gguf.py)：
    - `_resolve_model_path()` 智慧識別 Q4 系列，避免誤退回 Q8，並於本地檔案缺失時自動觸發非同步自癒下載。
    - `_ensure_server_running()` 新增 `_server_model_path` 切換感知，當使用者在 Q8_0 與 Q4_K_M 之間切換時，自動關閉舊伺服器並以新模型重啟。
- **模型註冊表與配額體系完備**：
  - 更新 [`zeronexus/ai_gateway/model_registry.py`](zeronexus/ai_gateway/model_registry.py)：
    - 完整註冊 `qwen2.5-0.5b-instruct-q4_k_m` 及其別名 `local/qwen2.5-0.5b-instruct-q4_k_m`。
  - 更新 [`zeronexus/ai_gateway/quota_service.py`](zeronexus/ai_gateway/quota_service.py)：
    - 設定 Q4_K_M 本地自主運算模型之配額為無限額度（999999 次）。
- **完整單元測試覆蓋**：
  - 更新 [`tests/test_local_gguf_adapter.py`](tests/test_local_gguf_adapter.py)：
    - 驗證選單第三項為 Q4_K_M、標籤 8 與 4 區分清楚、註冊表元數據正確以及路徑解析自癒，11 項本地推論測試全數通過，全系統 92 項回歸測試全綠。

---

## [2.7.4] - 2026-09-25

### 🚀 提示詞智慧精簡與上下文擴展 (Context Expansion & Smart Compaction)
- **8192 Tokens 上下文擴展與自動熱重啟**：
  - 更新 [`zeronexus/ai_gateway/adapters/local_gguf.py`](zeronexus/ai_gateway/adapters/local_gguf.py)：
    - 將 `llama-server` 上下文大小由 1024 擴增至 `-c 8192`，徹底解決 `exceed_context_size_error` (HTTP 400) 報錯。
    - 啟動前自動探測端點 `/props`，若現有伺服器之上下文小於 8192，自動進行背景進程平滑熱重啟升級。
- **本地小模型提示詞智慧精簡機制 (Smart Prompt Compaction)**：
  - 新增 `_compact_system_instruction()`，針對 0.5B 本地輕量模型自動提取核心繁體中文規範與身分設定，過濾冗長雲端專用工具描述，將高達 6000+ tokens 的龐大提示詞緊湊壓縮至 500~800 tokens 範圍。
  - 對話歷史自動保留最近 8 則輪次，避免長對話導致賽揚 CPU 計算時間過長。
- **請求逾時自適應放寬**：
  - 伺服器通訊超時時間放寬至 `max(timeout, 120.0)` 秒，為賽揚 CPU 之 Prompt Evaluation 預留充裕運算緩衝。

---

## [2.7.3] - 2026-09-25

### ⚡ 賽揚/奔騰無 AVX2 實體 CPU 專屬 SSE4.2 二進位直通通道 (Celeron / Pentium Direct Path)
- **硬體指令集感知與專屬通道調度**：
  - 更新 [`zeronexus/ai_gateway/adapters/local_gguf.py`](zeronexus/ai_gateway/adapters/local_gguf.py)：
    - 新增 `_has_avx2()` CPU 旗標偵測。
    - **無 AVX2 環境 (如 Intel Celeron / Pentium 物理限制晶片)**：直接直通專屬 SSE4.2 官方二進位引擎（`llama-server`），主動繞開 Python AVX2 套件，杜絕一切 `SIGILL (Illegal instruction)` 警告與崩潰。
    - **具備 AVX2 環境**：維持內部原生推論優先，兼顧極速與彈性。
- **推論常駐伺服器參數最適化 (低負載 / 賽揚友善)**：
  - 調整上下文限制至 `-c 1024`，執行緒數上限設為 2，記憶體開銷降至 500MB 以內，推論載入僅需 500ms。
  - 增強進程提前退出（Crash）之即時 stderr 錯誤診斷機制，避免長時間空轉等待。
- **全自動端到端實測通過**：
  - 模擬無 AVX2 賽揚環境進行實測，自動啟動 SSE4.2 通道並成功輸出繁體中文回應（耗時約 6 秒），10 項單元測試全數 100% 綠燈通過。

---

## [2.7.2] - 2026-09-25

### 📦 專案內建 libgomp.so.1 與 Git-Pull 零維護即插即用 (Zero-Touch Git-Pull Deployment)
- **內建 OpenMP 執行時期函式庫（zeronexus/assets/bin/libgomp.so.1）**：
  - 針對各類限制 root 權限、無法執行 `apt-get` 的第三方託管容器（如 Pterodactyl 等），將標準輕量版 `libgomp.so.1` (僅 377KB) 直接納入專案資產進行 Git 版本追蹤。
  - **使用者只需執行 `git pull` 即可自動送達**，無需任何 Linux 系統管理員權限或額外安裝步驟。
- **開機自癒自動同步與動態路徑載入**：
  - 更新 [`zeronexus/brain/bootstrap.py`](zeronexus/brain/bootstrap.py)：開機時若偵測到執行目錄缺少 `libgomp.so.1`，自動將專案內建庫複製就緒。
  - 更新 [`zeronexus/ai_gateway/adapters/local_gguf.py`](zeronexus/ai_gateway/adapters/local_gguf.py)：
    - 啟動 `llama-server` / `llama-cli` 時，`LD_LIBRARY_PATH` 自動優先載入專案內建庫與執行目錄。
    - 擴充 `_is_libgomp_available()`，優先探測本地資產，解決外部引擎被誤判略過之問題。
- **無 AVX2 虛擬 CPU 之自動平滑切換**：
  - 當主機 CPU 未具備 AVX2 或當前 Python 套件拋出 SIGILL 時，系統自動平滑切換至官方二進位引擎（`llama-server`）。
  - 搭配內建 `libgomp.so.1` 與動態多世代 CPU 後端（`libggml-cpu-x64.so`），真正做到 **「Git Pull 即用、重啟即跑、零編譯、零報錯」**。

---

## [2.7.1] - 2026-09-25

### 🛡️ 容器 OpenMP 系統依賴修復與相容推論優化 (Container OpenMP Fix & Robust Inference)
- **容器環境系統依賴補齊 (libgomp1)**：
  - 更新 [`Dockerfile`](Dockerfile)：在 `apt-get` 依賴中正式加入 `libgomp1`（OpenMP 執行時期函式庫），徹底解決精簡 Linux 容器執行 C++/二進位推論時缺少 `libgomp.so.1` (代碼 127) 之問題。
- **無 AVX/AVX2/FMA 相容性編譯標準化**：
  - 更新 [`Dockerfile`](Dockerfile) 與 [`zeronexus/brain/bootstrap.py`](zeronexus/brain/bootstrap.py)：
    - 標準化相容編譯參數：`CMAKE_ARGS="-DGGML_AVX=OFF -DGGML_AVX2=OFF -DGGML_FMA=OFF"`。
    - 支援 `ARG COMPAT_CPU=1`，確保無論容器在哪種虛擬 CPU 託管環境運行皆具備 100% 絕對相容性，徹底根除 `SIGILL` (Illegal instruction)。
- **推論優先順序與配置防護重構**：
  - 更新 [`zeronexus/ai_gateway/adapters/local_gguf.py`](zeronexus/ai_gateway/adapters/local_gguf.py)：
    - **優先模式（Python 內部相容引擎）**：優先使用 Python 內部 `llama_cpp.Llama` 進行推論，避免調用外部程序遇到動態連結庫缺失。
    - **容器最適相容配置**：調整為 `n_ctx=1024`，執行緒數預設 `n_threads=2`，大幅降低記憶體消耗並提升啟動秒速。
    - **動態庫前置安全探測**：增加 `_is_libgomp_available()`，在外部二進位引擎啟動前主動檢查 `libgomp.so.1`，並提供精確診斷與修復提示。
- **單元測試擴展與全數通過**：
  - 更新 [`tests/test_local_gguf_adapter.py`](tests/test_local_gguf_adapter.py)，新增 `test_is_libgomp_available_check` 與 `test_generate_prioritizes_internal_python_engine`，共 10 項測試 100% 綠燈通過。

---

## [2.7.0] - 2026-09-25

### 🚀 方案 B：官方多 CPU 動態自適應二進位推論引擎 (Dynamic Binary Inference Engine)
- **免 gcc、免 root、免 AVX2 限制之本地原生推論**：
  - 徹底克服無 AVX2、無 C/C++ 編譯器環境（如各種 PaaS/虛擬機器託管伺服器）無法安裝 `llama-cpp-python` 的痛點。
  - 整合官方原生預編譯二進位執行檔套件（含動態載入之 `libggml-cpu-x64.so`、`libggml-cpu-ivybridge.so`、`libggml-cpu-sse42.so` 等）。
- **全自動依賴自癒下載（Zero-Touch Bootstrap）**：
  - 在 [`zeronexus/brain/bootstrap.py`](zeronexus/brain/bootstrap.py) 新增 `ensure_llama_binaries_ready()`，於開機偵測主機環境時，自動自官方儲存庫高速下載並解壓縮原生二進位推論引擎至 `data/bin/llama/`。
- **雙模推論服務架構（Server HTTP + CLI Fallback）**：
  - 更新 [`zeronexus/ai_gateway/adapters/local_gguf.py`](zeronexus/ai_gateway/adapters/local_gguf.py)：
    - **優先模式（llama-server HTTP API）**：背景守護行程常駐，透過本機回環標準 OpenAI 格式端點（`http://127.0.0.1:8089/v1/chat/completions`）提供毫秒級串流與快速推論，避免程序頻繁重複啟動加載模型。
    - **備援模式（llama-cli 命令列）**：若伺服器通訊逾時或受限，自動切換命令列管道推論。
    - **終端安全釋放**：實作非同步 `close()` 自動探測並終止本機常駐程序，確保系統記憶體安全釋放。
- **UI 與選單體驗升級**：
  - 恢復選單友好標籤，在託管伺服器上亦可順暢體驗純 CPU 本地模型。

---

## [2.6.6] - 2026-09-25

### ☁️ 託管環境友善指引與選單標註 (Hosting Environment Guidance & UI Tags)
- **Discord 互動選單規格標註**：
  - 更新 [`zeronexus/ui/model_select_view.py`](zeronexus/ui/model_select_view.py)，在 `Qwen 2.5 0.5B GGUF` 選單標籤中明確註明 `(需主機支援 AVX2，託管伺服器請選雲端模型)`，防範託管平台使用者誤選進入沙盒降級流程。
- **日誌與防護提示通俗化**：
  - 更新 [`zeronexus/ai_gateway/adapters/local_gguf.py`](zeronexus/ai_gateway/adapters/local_gguf.py) 的錯誤診斷訊息，移除對無 Docker 權限之託管使用者無意義之指令指引，給予針對託管環境 CPU 特性之清楚說明與最佳實踐推薦。

---

## [2.6.5] - 2026-09-25

### ⚡ 無 AVX2 伺服器相容構建與動態自癒 (Zero-AVX Auto-Compilation & Universal Resilience)
- **Dockerfile 智慧 CPU 特徵偵測與相容構建**：
  - 更新 [`Dockerfile`](Dockerfile)：
    - 建置階段自動探測主機 `/proc/cpuinfo`。
    - 若主機支援 AVX2，自動秒級下載官方預編譯優化 Wheel。
    - 若檢測到主機 CPU 未具備 AVX2，自動啟用相容性原始碼編譯參數 `CMAKE_ARGS="-DGGML_AVX2=OFF -DGGML_AVX=OFF -DGGML_FMA=OFF -DGGML_F16C=OFF"`，在本地自動編譯出完全相容當前 CPU 之二進位執行檔，使老舊或虛擬化 VPS CPU 亦能無礙運行本地模型。
- **大腦依賴自癒無 AVX 自動調度**：
  - 更新 [`zeronexus/brain/bootstrap.py`](zeronexus/brain/bootstrap.py) 中的 `check_and_repair_dependencies()`，開機動態安裝時若探測到缺少 AVX2，自動切換至無 AVX 編譯環境，杜絕預編譯 AVX2 輪子導致的指令集衝突。
- **錯誤提示與重建指引深化**：
  - 於 [`zeronexus/ai_gateway/adapters/local_gguf.py`](zeronexus/ai_gateway/adapters/local_gguf.py) 增強錯誤日誌指引，明確引導使用者透過 `docker compose build --no-cache` 一鍵由系統自動編譯相容版本。

---

## [2.6.4] - 2026-09-25

### 🛡️ 沙盒獨立子行程硬體安全探測與 SIGILL 零崩潰隔離 (Subprocess Sandbox Probe & SIGILL Immunity)
- **沙盒隔離硬體相容性探測（防止主進程 SIGILL 暴斃重啟）**：
  - 在 [`zeronexus/ai_gateway/adapters/local_gguf.py`](zeronexus/ai_gateway/adapters/local_gguf.py) 實作 `LocalGGUFAdapter.probe_hardware_safety()` 機制。
  - 在主程序加載 C++ 動態函式庫前，優先啟動沙盒獨立子行程執行微型實例化探測。若底層 CPU 缺少 AVX2 指令集並觸發 `Illegal instruction`（SIGILL，退出代碼 `-4` 或 `132`），主程序在毫秒級精準攔截。
  - **主行程零崩潰保證**：主程式與 Discord 連線絲毫不受波及，機器人永不重啟，徹底告別 `CRASHED` 狀態。
- **快取記憶與智慧降級 (Zero-Overhead Safe Fallback)**：
  - 探測結果自動快取至 `_hardware_probe_cache`，避免反覆啟動子進程。
  - 遇到指令集不相容之硬體環境時，適配器主動拋出友善保護異常，觸發 AI Gateway 智慧降級路由，無縫切換至備援雲端模型（Gemini、DeepSeek 等）。
- **單元測試強化**：
  - 於 `tests/test_local_gguf_adapter.py` 新增 `test_hardware_safety_probe_sigill_protection`，以 mock 模擬子行程回傳 SIGILL (-4)，驗證硬體探測保護、快取紀錄與主行程零崩潰拋出防護異常之完整生命週期。

---

## [2.6.3] - 2026-09-25

### 🚀 預編譯二進位 Wheel 與無編譯器環境相容強化 (Prebuilt Wheels & Zero-Compiler Fallback)
- **CPU 預編譯 Wheel 索引整合**：
  - 在 [`requirements.txt`](requirements.txt) 與 [`Dockerfile`](Dockerfile) 中全面引入官方二進位預編譯索引源 `--extra-index-url https://abetlen.github.io/llama-cpp-python/whl/cpu` 與 `--prefer-binary` 參數，杜絕容器因缺少編譯器而嘗試原始碼構建失敗。
- **無效 CC/CXX 環境變數隔離與環境自癒**：
  - 更新 [`zeronexus/brain/bootstrap.py`](zeronexus/brain/bootstrap.py) 的 `check_and_repair_dependencies()`：
    - 在調用 pip 之前自動檢驗系統是否存在 `gcc` / `g++`；若不存在，隔離清理可能殘留的無效 `CC` / `CXX` 環境變數，防範 CMake 報錯 `Could not find the compiler specified in the environment variable CC: gcc`。
    - 自癒安裝命令全面採用 `--prefer-binary`，在無 C++ 編譯器的容器環境中直接下載官方預編譯 CPU 輪子，秒級完成安裝。
- **Dockerfile 雙重保險完善**：
  - 在 [`Dockerfile`](Dockerfile) 額外補齊系統依賴套件 `gcc`、`g++` 與 `curl`，使容器同時兼備「直接安裝預編譯 Wheel」與「本地 C++ 原始碼編譯」雙重防禦。

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
