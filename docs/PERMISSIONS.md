# ZeroNexus (ZN) — 權限階層與安全架構

## 五級權限體系
```
DEVELOPER (5) ──> GUILD_OWNER (4) ──> ADMINISTRATOR (3) ──> MODERATOR (2) ──> TRUSTED (1) ──> EVERYONE (0)
```

- **DEVELOPER**：僅由 `.env` 的 `DEV_USERS` 數字 ID 解析判定，無法透過任何 Discord 權限或對話誘騙偽裝。
- **身分組層級檢查 (Role Hierarchy)**：管理員無法對自身或比自己順位更高者進行踢出/封鎖/禁言；機器人亦受身分組順位防護。
- **高危操作二次確認**：所有封鎖、大量刪訊與伺服器重設指令均彈出具備 60 秒逾時防呆之 `ZNConfirmView`。
