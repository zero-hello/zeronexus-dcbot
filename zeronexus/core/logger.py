"""ZeroNexus Structured Logging Engine.

Features:
- Guaranteed Secret Redaction Filter (no bot tokens, API keys, or passwords ever reach stdout or log files)
- Colored console output with standardized formatting
- Optional rotating file logs in data/logs/
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Set

from zeronexus.core.config import config, mask_secret


class SecretRedactionFilter(logging.Filter):
    """Intercepts and sanitizes log records before emission."""

    def __init__(self, secrets: Set[str] | None = None) -> None:
        super().__init__()
        self.secrets: Set[str] = set()
        if secrets:
            for s in secrets:
                if len(s) >= 4:  # Avoid redacting tiny substrings
                    self.secrets.add(s)

    def update_secrets(self, new_secrets: Set[str]) -> None:
        for s in new_secrets:
            if len(s) >= 4:
                self.secrets.add(s)

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = self._sanitize(record.msg)
        if record.args:
            if isinstance(record.args, dict):
                record.args = {k: self._sanitize(v) if isinstance(v, str) else v for k, v in record.args.items()}
            elif isinstance(record.args, tuple):
                record.args = tuple(self._sanitize(v) if isinstance(v, str) else v for v in record.args)
        return True

    def _sanitize(self, text: str) -> str:
        from zeronexus.security.sanitizer import redact_secrets
        # First pass with known secrets
        for secret in self.secrets:
            if secret in text:
                masked = mask_secret(secret, prefix_len=4, suffix_len=4)
                text = text.replace(secret, masked)
        # Second pass with comprehensive regex patterns
        return redact_secrets(text)


# Global filter instance
_redaction_filter = SecretRedactionFilter(config.collect_all_secrets())


import re


class ColorFormatter(logging.Formatter):
    """現代科技感 ANSI 彩色格式化器，排版整潔俐落、對齊一致。"""

    # 徽章定義：寬度一致對齊
    LEVEL_BADGES = {
        logging.DEBUG: ("\033[38;5;244m", "DEBUG"),
        logging.INFO: ("\033[1;38;5;45m", "INFO "),
        logging.WARNING: ("\033[1;38;5;214m", "WARN "),
        logging.ERROR: ("\033[1;38;5;196m", "ERROR"),
        logging.CRITICAL: ("\033[1;37;41m", "FATAL"),
    }
    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    CYAN = "\033[38;5;51m"
    SKY_BLUE = "\033[38;5;45m"
    BLUE = "\033[38;5;75m"
    MAGENTA = "\033[38;5;207m"
    PURPLE_BANNER = "\033[1;38;5;231;48;5;129m"
    YELLOW = "\033[38;5;221m"
    GREEN = "\033[38;5;48m"
    RED = "\033[38;5;196m"
    GRAY = "\033[38;5;242m"
    DARK_GRAY = "\033[38;5;239m"

    # 正則高亮快取
    _RE_LATENCY = re.compile(r"(\b\d+(?:\.\d+)?\s*(?:ms|毫秒|s|秒)\b)")
    _RE_ARROW = re.compile(r"(➔|->|➜|=>)")

    def format(self, record: logging.LogRecord) -> str:
        color, badge = self.LEVEL_BADGES.get(record.levelno, (self.RESET, record.levelname[:5].ljust(5)))
        # 控制台使用更俐落的精準時間 HH:MM:SS
        time_str = self.formatTime(record, "%H:%M:%S")
        record.asctime = time_str

        msg = record.getMessage()

        # 1. 核心工具調用旗標高亮
        if "🛠️" in msg or "工具調用" in msg or "TOOL CALL" in msg:
            msg = msg.replace("[🛠️ 工具調用 / FUNCTION CALL]", f"{self.PURPLE_BANNER} 🛠️ 工具調用 {self.RESET}")
            msg = msg.replace("[🛠️ 工具調用 / TOOL CALL]", f"{self.PURPLE_BANNER} 🛠️ 工具調用 {self.RESET}")
            msg = msg.replace("[🛠️ 工具調用]", f"{self.PURPLE_BANNER} 🛠️ 工具調用 {self.RESET}")

        # 2. 狀態標籤色彩強化
        if "[通過]" in msg or "[PASS]" in msg:
            msg = msg.replace("[通過]", f"\033[1;38;5;48m✔ 通過{self.RESET}").replace("[PASS]", f"\033[1;38;5;48m✔ PASS{self.RESET}")
        if "[成功]" in msg or "[SUCCESS]" in msg:
            msg = msg.replace("[成功]", f"\033[1;38;5;48m✔ 成功{self.RESET}").replace("[SUCCESS]", f"\033[1;38;5;48m✔ OK{self.RESET}")
        if "[失敗]" in msg or "[FAIL]" in msg:
            msg = msg.replace("[失敗]", f"\033[1;38;5;196m✘ 失敗{self.RESET}").replace("[FAIL]", f"\033[1;38;5;196m✘ FAIL{self.RESET}")
        if "[警告]" in msg or "[WARN]" in msg:
            msg = msg.replace("[警告]", f"\033[1;38;5;214m▲ 警告{self.RESET}").replace("[WARN]", f"\033[1;38;5;214m▲ WARN{self.RESET}")

        # 3. 領域標籤色彩（CWA, AI, DB 等）
        if "[CWA" in msg or "[中央氣象署" in msg:
            msg = re.sub(r"(\[(?:CWA[^\]]*|中央氣象署[^\]]*)\])", f"{self.SKY_BLUE}\\1{self.RESET}", msg)
        if "[AI" in msg or "[人工智慧" in msg or "[模型" in msg or "[ZeroNexus]" in msg:
            msg = re.sub(r"(\[(?:AI[^\]]*|人工智慧[^\]]*|模型[^\]]*|ZeroNexus[^\]]*)\])", f"{self.MAGENTA}\\1{self.RESET}", msg)
        if "[資料庫" in msg or "[DB" in msg:
            msg = re.sub(r"(\[(?:資料庫[^\]]*|DB[^\]]*)\])", f"{self.YELLOW}\\1{self.RESET}", msg)

        # 4. 耗時與箭頭語法高亮
        msg = self._RE_LATENCY.sub(f"{self.YELLOW}\\1{self.RESET}", msg)
        msg = self._RE_ARROW.sub(f"{self.CYAN}\\1{self.RESET}", msg)

        # 格式化輸出：時間  等級  內容
        formatted = f"{self.DARK_GRAY}{time_str}{self.RESET} {color}{badge}{self.RESET} {msg}"

        if record.exc_info:
            formatted += "\n" + self.formatException(record.exc_info)
        return _redaction_filter._sanitize(formatted)


class SanitizedFileFormatter(logging.Formatter):
    """檔案日誌格式化器，嚴格確保金鑰與敏感資訊脫敏。"""

    def format(self, record: logging.LogRecord) -> str:
        formatted = super().format(record)
        return _redaction_filter._sanitize(formatted)


def suppress_external_loggers() -> None:
    """壓制第三方噪聲模組（Discord Gateway 心跳、HTTP 輪詢等），使終端保持清爽。"""
    noisy_modules = (
        "discord",
        "discord.gateway",
        "discord.http",
        "discord.client",
        "aiohttp.access",
        "urllib3",
        "asyncio",
        "httpcore",
        "httpx",
        "matplotlib",
        "matplotlib.font_manager",
    )
    for name in noisy_modules:
        logging.getLogger(name).setLevel(logging.WARNING)


def setup_logger(name: str = "zeronexus", level: int = logging.INFO) -> logging.Logger:
    """配置並回傳帶有金鑰遮蔽與美化色彩的 Logger。"""
    suppress_external_loggers()
    logger = logging.getLogger(name)
    logger.setLevel(level)
    logger.propagate = False

    # 若已配置 handler 則避免重複添加
    if logger.handlers:
        return logger

    # 控制台 Handler
    console_handler = logging.StreamHandler()
    console_handler.setLevel(level)
    console_handler.setFormatter(ColorFormatter())
    console_handler.addFilter(_redaction_filter)
    logger.addHandler(console_handler)

    # 檔案 Handler（logs 目錄）
    log_dir = Path(__file__).resolve().parent.parent.parent / "logs"
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(log_dir / "zeronexus.log", encoding="utf-8")
        file_handler.setLevel(logging.DEBUG)
        file_formatter = SanitizedFileFormatter(
            "[%(asctime)s] [%(levelname)-7s] [%(name)s]: %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
        file_handler.setFormatter(file_formatter)
        file_handler.addFilter(_redaction_filter)
        logger.addHandler(file_handler)
    except Exception as e:
        print(f"[WARN] 無法建立檔案日誌處理器: {e}")

    return logger


# 主全域 Logger 實例
log = setup_logger("zeronexus")


def refresh_secret_redactions() -> None:
    """執行時期熱重載敏感金鑰脫敏池。"""
    _redaction_filter.update_secrets(config.collect_all_secrets())
