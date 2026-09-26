"""紅隊測試：Python 程式碼沙盒逃逸防護（Red Team: Sandbox Escape Defense）。

針對 _generate_runner_script 產出之 audit hook 防護邏輯，驗證：
1. os.open 整數旗標（O_WRONLY|O_CREAT 等）不得繞過工作目錄寫入限制
2. symlink 跳脫（工作目錄內 symlink 指向沙盒外）不得通過路徑檢查
3. startswith 前綴混淆（/tmp/zn_sandbox_1evil 通過 /tmp/zn_sandbox_1）不得成立
4. os.symlink / os.link 等跳脫跳板事件已被阻斷清單覆蓋
"""

from __future__ import annotations

import os
import re
from pathlib import Path

import pytest

from zeronexus.engines.code_sandbox import CodeSandboxEngine


@pytest.fixture(scope="module")
def engine() -> CodeSandboxEngine:
    return CodeSandboxEngine()


@pytest.fixture(scope="module")
def runner_script(engine: CodeSandboxEngine, tmp_path_factory) -> str:
    tmpdir = str(tmp_path_factory.mktemp("zn_sandbox_redteam"))
    return engine._generate_runner_script("pass", tmpdir=tmpdir)


def _extract_hook_source(script: str) -> str:
    """擷取 runner script 中 _sandbox_audit_hook 函式本體原始碼。"""
    match = re.search(
        r"def _sandbox_audit_hook\(event, args\):(.*?)(?=\nsys\.addaudithook)",
        script,
        re.DOTALL,
    )
    assert match, "runner script 中必須包含 _sandbox_audit_hook"
    return match.group(1)


class TestOSOpenFlagBypass:
    """測試 1：os.open 整數旗標繞過防護。"""

    def test_runner_blocks_os_open_integer_flags(self, runner_script: str) -> None:
        """修復後：以位元運算解碼整數 flags，str(int) 之 "w" 字串檢查應已移除。"""
        hook_src = _extract_hook_source(runner_script)
        # 舊漏洞寫法不得存在：直接 str(args[1]) 後檢查 "w"
        assert "mode = str(args[1])" not in hook_src, (
            "audit hook 仍使用 str(args[1]) 判定寫入模式，os.open 整數旗標可繞過！"
        )
        # 修復特徵：必須以位元運算解碼 O_WRONLY/O_RDWR 等旗標
        assert "O_WRONLY" in hook_src or "O_RDWR" in hook_src, (
            "audit hook 缺少整數旗標位元運算解碼，無法防禦 os.open(path, os.O_WRONLY|os.O_CREAT) 繞過！"
        )

    def test_integer_write_flags_decoded(self) -> None:
        """驗證修復後之位元運算邏輯正確判定 os.open 整數旗標為寫入模式。"""
        write_flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
        is_write = bool(
            write_flags
            & (
                getattr(os, "O_WRONLY", 1)
                | getattr(os, "O_RDWR", 2)
                | getattr(os, "O_APPEND", 0)
                | getattr(os, "O_CREAT", 0)
                | getattr(os, "O_TRUNC", 0)
            )
        )
        assert is_write, "O_WRONLY|O_CREAT|O_TRUNC 必須被判定位寫入模式"

        # 舊漏洞邏輯對照：str(flags) 不含 "w" → 舊寫法完全失效（證明漏洞前提）
        old_style_check = any(m in str(write_flags) for m in ("w", "a", "+", "x"))
        assert not old_style_check, "舊式 str(flags) 檢查對整數旗標必然失效，此對照驗證漏洞前提"


class TestSymlinkEscape:
    """測試 2：symlink 跳脫防護。"""

    def test_runner_uses_realpath(self, runner_script: str) -> None:
        """路徑檢查必須使用 os.path.realpath（解析 symlink），不得使用裸 abspath 進行邊界判定。"""
        hook_src = _extract_hook_source(runner_script)
        assert "os.path.realpath" in hook_src, (
            "audit hook 必須以 realpath 解析 symlink 後再檢查，否則工作目錄內 symlink 可跳脫！"
        )

    def test_runner_blocks_symlink_events(self, runner_script: str) -> None:
        """os.symlink / os.link / os.makedirs 必須納入阻斷清單。"""
        hook_src = _extract_hook_source(runner_script)
        for event_name in ("os.symlink", "os.link", "os.makedirs", "shutil.copy2"):
            assert event_name in hook_src, f"阻斷清單缺少 {event_name}，可作為跳脫跳板！"

    def test_realpath_resolves_symlink_escape(self, tmp_path: Path) -> None:
        """驗證 realpath 能解析「工作目錄內 symlink 指向 /etc」之跳脫。"""
        work_dir = tmp_path / "sandbox_work"
        work_dir.mkdir()
        evil_link = work_dir / "escape"
        evil_link.symlink_to("/etc")

        resolved = os.path.realpath(str(evil_link))
        assert resolved.startswith("/etc"), "前提驗證：realpath 應解析出 symlink 真實目標"

        # 修復後之邊界比對必須拒絕
        work_real = os.path.realpath(str(work_dir))
        within = resolved == work_real or resolved.startswith(work_real + os.sep)
        assert not within, "symlink 跳脫路徑不得被判定位於工作目錄內"


class TestPrefixConfusion:
    """測試 3：startswith 前綴混淆防護。"""

    def test_separator_boundary_comparison(self, runner_script: str) -> None:
        """邊界比對必須包含 os.sep，防止前綴混淆。"""
        hook_src = _extract_hook_source(runner_script)
        assert "os.sep" in hook_src, "寫入檢查必須以 os.sep 邊界比對取代裸 startswith"

    def test_evil_sibling_dir_rejected(self) -> None:
        """/tmp/zn_sandbox_1evil 不得通過 /tmp/zn_sandbox_1 之檢查。"""
        allowed = "/tmp/zn_sandbox_1"
        evil = "/tmp/zn_sandbox_1evil/secret.txt"

        # 舊漏洞寫法：裸 startswith 會放行
        assert evil.startswith(allowed), "前提驗證：裸 startswith 存在前綴混淆"

        # 修復後：os.sep 邊界比對必須拒絕
        work_real = os.path.realpath(allowed)
        norm = os.path.realpath(evil)
        within = norm == work_real or norm.startswith(work_real + os.sep)
        assert not within, "修復後前綴混淆路徑必須被拒絕"


class TestSensitivePathProtection:
    """測試 4：敏感路徑防護在 realpath 後仍有效。"""

    def test_sensitive_keywords_still_checked(self, runner_script: str) -> None:
        hook_src = _extract_hook_source(runner_script)
        for kw in (".env", "id_rsa", "/etc/shadow", "zeronexus.db"):
            assert kw in hook_src, f"敏感關鍵字 {kw} 防護不得因重構而遺失"

    def test_symlinked_env_file_blocked_by_realpath(self, tmp_path: Path) -> None:
        """symlink 指向 .env 時，realpath 解析後仍必須命中敏感關鍵字。"""
        work_dir = tmp_path / "w"
        work_dir.mkdir()
        link = work_dir / "readme.txt"
        link.symlink_to(tmp_path / ".env")

        norm_p = os.path.realpath(str(link))
        lower_p = norm_p.lower()
        assert ".env" in lower_p, "realpath 解析後 symlink → .env 應命中敏感關鍵字檢查"
