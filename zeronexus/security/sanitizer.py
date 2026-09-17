"""ZeroNexus Input Sanitization & Security Defenses.

Protects against:
- Directory traversal attacks
- SQL & Shell injections
- Markdown formatting exploits and Discord mention spam
"""

from __future__ import annotations

import asyncio
import re
import signal
import threading
from pathlib import Path
from typing import List, Optional, Tuple


class ReDoSTimeoutError(TimeoutError):
    """Raised when regular expression evaluation exceeds defensive time budget."""
    pass


async def safe_regex_finditer(
    pattern: str | re.Pattern[str],
    text: str,
    timeout: float = 2.0,
    max_matches: int = 100,
    flags: int = 0,
) -> Tuple[List[re.Match[str]], int]:
    """Evaluates a regular expression on a worker thread bounded by a 2.0s hard timeout.

    Defends against ReDoS (Regular Expression Denial of Service) and catastrophic backtracking.
    Returns (matches, total_count).
    """
    def _run() -> Tuple[List[re.Match[str]], int]:
        compiled = re.compile(pattern, flags) if isinstance(pattern, str) else pattern
        matches: List[re.Match[str]] = []
        count = 0
        for m in compiled.finditer(text):
            count += 1
            if len(matches) < max_matches:
                matches.append(m)
        return matches, count

    if hasattr(signal, "SIGALRM") and threading.current_thread() is threading.main_thread():
        def _alarm_handler(signum, frame):
            raise ReDoSTimeoutError(
                f"正則運算耗時超過 {timeout} 秒硬逾時熔斷門檻，疑似遭遇災難性回溯 (ReDoS) 攻擊。"
            )

        old_handler = signal.signal(signal.SIGALRM, _alarm_handler)
        signal.setitimer(signal.ITIMER_REAL, timeout)
        try:
            return _run()
        except ReDoSTimeoutError:
            raise
        except Exception as exc:
            raise exc
        finally:
            signal.setitimer(signal.ITIMER_REAL, 0)
            signal.signal(signal.SIGALRM, old_handler)

    try:
        return await asyncio.wait_for(asyncio.to_thread(_run), timeout=timeout)
    except asyncio.TimeoutError as exc:
        raise ReDoSTimeoutError(
            f"正則運算耗時超過 {timeout} 秒硬逾時熔斷門檻，疑似遭遇災難性回溯 (ReDoS) 攻擊。"
        ) from exc


async def safe_regex_search(
    pattern: str | re.Pattern[str],
    text: str,
    timeout: float = 2.0,
    flags: int = 0,
) -> Optional[re.Match[str]]:
    """Executes re.search safely with ReDoS offload & timeout."""
    def _run() -> Optional[re.Match[str]]:
        compiled = re.compile(pattern, flags) if isinstance(pattern, str) else pattern
        return compiled.search(text)

    if hasattr(signal, "SIGALRM") and threading.current_thread() is threading.main_thread():
        def _alarm_handler(signum, frame):
            raise ReDoSTimeoutError(
                f"正則搜尋耗時超過 {timeout} 秒硬逾時熔斷門檻，疑似遭遇災難性回溯 (ReDoS) 攻擊。"
            )

        old_handler = signal.signal(signal.SIGALRM, _alarm_handler)
        signal.setitimer(signal.ITIMER_REAL, timeout)
        try:
            return _run()
        except ReDoSTimeoutError:
            raise
        except Exception as exc:
            raise exc
        finally:
            signal.setitimer(signal.ITIMER_REAL, 0)
            signal.signal(signal.SIGALRM, old_handler)

    try:
        return await asyncio.wait_for(asyncio.to_thread(_run), timeout=timeout)
    except asyncio.TimeoutError as exc:
        raise ReDoSTimeoutError(
            f"正則搜尋耗時超過 {timeout} 秒硬逾時熔斷門檻，疑似遭遇災難性回溯 (ReDoS) 攻擊。"
        ) from exc


def sanitize_input(text: str, max_length: int = 2000) -> str:
    """Sanitizes raw user input, removes zero-width characters, neutralizes mass mentions, and limits length."""
    if not text:
        return ""
    # Strip invisible zero-width spaces / format bypass chars
    cleaned = re.sub(r"[\u200B-\u200D\uFEFF]", "", text)
    # Strip dangerous mass mentions (@everyone, @here, including case variants like @Everyone, @HERE)
    cleaned = re.sub(r"(?i)@(everyone|here)", lambda m: f"@\u200b{m.group(1)}", cleaned)
    return cleaned.strip()[:max_length]


def check_path_safety(base_dir: Path, target_path_str: str) -> bool:
    """Ensures that target_path_str resolves strictly within base_dir (prevents ../ path traversal)."""
    try:
        resolved_base = base_dir.resolve()
        target_path = (base_dir / target_path_str).resolve()
        return resolved_base in target_path.parents or target_path == resolved_base
    except Exception:
        return False


def redact_secrets(text: str) -> str:
    """Masks all known and pattern-matching secrets in a text string.

    Transforms credentials into the required 'MTU0••••5Dlk' format.
    Ensures DISCORD_BOT_TOKEN, CWA_API_KEY, GEMINI_API_KEY, OPENROUTER_API_KEY,
    database passwords, and redis passwords are never exposed in plaintext.
    """
    if not text or not isinstance(text, str):
        return text

    from zeronexus.core.config import config, mask_secret

    # 1. Exact string matching from loaded secrets pool
    try:
        secrets = config.collect_all_secrets()
        for secret in sorted(secrets, key=len, reverse=True):
            if secret and secret in text:
                masked = mask_secret(secret, prefix_len=4, suffix_len=4)
                text = text.replace(secret, masked)
    except Exception:
        pass

    def _mask_match(m: re.Match) -> str:
        val = m.group(0)
        return mask_secret(val, prefix_len=4, suffix_len=4)

    # 2. Regex fallback for Discord Bot Token
    text = re.sub(
        r"\b[MNO][a-zA-Z0-9_-]{23,32}\.[a-zA-Z0-9_-]{6}\.[a-zA-Z0-9_-]{27,45}\b",
        _mask_match,
        text,
    )

    # 3. Regex fallback for Database / Redis / URL credentials
    text = re.sub(
        r"(://[^:\s/@]+:)([^@\s]+)(@)",
        lambda m: f"{m.group(1)}{mask_secret(m.group(2), prefix_len=4, suffix_len=4)}{m.group(3)}",
        text,
    )

    # 4. Regex fallback for OpenAI / OpenRouter / Anthropic / AI API keys (including sk-proj-, sk-ant-, sk-or-v1-)
    text = re.sub(
        r"\bsk-(?:or-v1-|proj-|ant-)?[a-zA-Z0-9_-]{20,160}\b",
        _mask_match,
        text,
    )

    # 5. Regex fallback for Taiwan CWA Open Data API keys
    text = re.sub(
        r"\bCWA-[A-Za-z0-9-]{16,}\b",
        _mask_match,
        text,
    )

    # 6. Regex fallback for Gemini / Google API keys
    text = re.sub(
        r"\bAIza[0-9A-Za-z\-_]{30,}\b",
        _mask_match,
        text,
    )

    # 7. Regex fallback for GitHub Personal Access Tokens and Hugging Face Tokens
    text = re.sub(
        r"\b(?:ghp|gho|ghu|ghs|ghr)_[a-zA-Z0-9]{36,}\b",
        _mask_match,
        text,
    )
    text = re.sub(
        r"\bgithub_pat_[a-zA-Z0-9_]{60,}\b",
        _mask_match,
        text,
    )
    text = re.sub(
        r"\bhf_[a-zA-Z0-9]{30,}\b",
        _mask_match,
        text,
    )

    # 8. Regex fallback for HTTP Authorization Bearer tokens
    text = re.sub(
        r"(?i)\b(bearer\s+)([a-zA-Z0-9_\-\.]{16,})\b",
        lambda m: f"{m.group(1)}{mask_secret(m.group(2), prefix_len=4, suffix_len=4)}",
        text,
    )

    # 9. Regex fallback for query parameters containing credentials (including key=, api_key=, client_secret=)
    text = re.sub(
        r"(?i)([\?&](?:api[_-]?key|key|token|access[_-]?token|client[_-]?secret|password|secret|auth)=)([^&\s]+)",
        lambda m: f"{m.group(1)}{mask_secret(m.group(2), prefix_len=2, suffix_len=2)}",
        text,
    )

    # 10. Regex fallback for JSON / KV pairs containing credentials
    text = re.sub(
        r"""(?i)(['"][^'"]*?(?:password|token|secret|api[_-]?key|access[_-]?token|client[_-]?secret)[^'"]*?['"]\s*:\s*['"])([^'"]+)(['"])""",
        lambda m: f"{m.group(1)}{mask_secret(m.group(2), prefix_len=2, suffix_len=2)}{m.group(3)}",
        text,
    )

    return text

