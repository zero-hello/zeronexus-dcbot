# ZeroNexus (ZN) — 生產環境部署指引

## 1. 系統硬體與環境需求
- **Python**：Python 3.11 或更高版本
- **記憶體**：建議至少 1 GB RAM（若開啟高並發音訊串流建議額外配置 1 GB）
- **作業系統**：Linux (Ubuntu/Debian/Alpine) 或 macOS/Windows

## 2. Docker Compose 生產部署 (推薦)
1. 配置 `.env`：
   ```bash
   cp .env.example .env
   # 填入 DISCORD_BOT_TOKEN 等資訊
   ```
2. 啟動容器集：
   ```bash
   docker-compose up -d --build
   ```
3. 檢查容器狀態：
   ```bash
   docker-compose ps
   ```

## 3. Systemd 服務單元 (單機部署)
若以 Linux systemd 常駐執行，可建立 `/etc/systemd/system/zeronexus.service`：
```ini
[Unit]
Description=ZeroNexus Discord Platform
After=network.target

[Service]
Type=simple
User=zero
WorkingDirectory=/home/zero/Desktop/專案備份/ZeroNexus
ExecStart=/home/zero/Desktop/專案備份/ZeroNexus/znenv/bin/python -m zeronexus.main
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```
