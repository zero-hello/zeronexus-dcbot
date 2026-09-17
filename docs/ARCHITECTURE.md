# ZeroNexus (ZN) — 系統架構白皮書

```
                         ZeroNexus
                             │
                    ┌────────┴────────┐
                    │ Command / AI    │
                    │     Router      │
                    └────────┬────────┘
                             │
       ┌─────────────────────┼─────────────────────┐
       │                     │                     │
       ▼                     ▼                     ▼
  ZeroNexus Core        External APIs          AI Gateway
       │                     │                     │
       │                     ├─ CWA               ├─ Gemini
       │                     ├─ Minecraft        ├─ DeepSeek
       │                     └─ Other APIs       └─ OpenRouter
       │
       ├─ Calculator
       ├─ Permissions
       ├─ Database
       ├─ Cache
       ├─ Scheduler
       ├─ Event System
       ├─ Statistics
       ├─ Rate Limiter
       ├─ Configuration
       ├─ Diagnostics
       └─ Module Manager
                             │
                             ▼
                         Modules
                             │
       ┌───────────────┬─────┼─────┬──────────────┐
       ▼               ▼     ▼     ▼              ▼
   Moderation       Music    AI   Minecraft    Entertainment
```

## 模組生命週期狀態機
```
DISCOVERED ──> INITIALIZING ──> READY ──> RUNNING
                                             │
                                             ├──> DEGRADED
                                             │       │
                                             └──> DISABLED ──> RECOVERING ──> RUNNING
```

## 模組隔離機制（Module Isolation）
1. 每個模組繼承自 `BaseModule`，獨立管理其連線資源與註冊命令。
2. 當外部依賴（如音訊串流節點中斷、CWA API 金鑰未填）發生故障時，僅該模組狀態轉為 `DISABLED` 或 `DEGRADED`。
3. `command_guard` 會自動在執行期攔截屬於已停用模組的指令，並回傳格式化的健康狀態診斷卡片，主程序持續運作。
