"""ZeroNexus Python Secure Code and Chart Sandbox Engine.

Provides an isolated, secure Python subprocess execution environment
with hard resource limits, network sandboxing, Discord Dark Mode styling,
and 100% Traditional Chinese font anti-garbled rendering guarantees.
"""

from __future__ import annotations

import asyncio
import base64
import io
import json
import os
import sys
import tempfile
import textwrap
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

import discord

from zeronexus.core.logger import log

# Resolve project paths
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_FONTS_DIR = _PROJECT_ROOT / "data" / "fonts"


@dataclass
class SandboxResult:
    """Represents the execution result of the Python sandbox."""

    success: bool
    stdout: str
    stderr: str
    has_image: bool
    image_bytes: Optional[bytes] = None
    image_base64: Optional[str] = None
    execution_time_ms: float = 0.0
    error: Optional[str] = None

    def to_discord_file(self, filename: str = "chart.png") -> Optional[discord.File]:
        """Wraps captured image bytes into a discord.File ready for attachment."""
        if not self.has_image or not self.image_bytes:
            return None
        return discord.File(fp=io.BytesIO(self.image_bytes), filename=filename)

    def to_dict(self) -> Dict[str, Any]:
        """Converts result to JSON-friendly dictionary for tool call output."""
        return {
            "success": self.success,
            "stdout": self.stdout.strip(),
            "stderr": self.stderr.strip(),
            "has_image": self.has_image,
            "image_base64": self.image_base64,
            "execution_time_ms": round(self.execution_time_ms, 2),
            "error": self.error,
        }


class CodeSandboxEngine:
    """Secure Python Subprocess Code Execution & High-End Charting Sandbox."""

    DEFAULT_TIMEOUT: float = 5.0
    MAX_TIMEOUT: float = 10.0
    DEFAULT_MEMORY_MB: int = 1024

    # Discord Dark Mode Color Palette (Vibrant & High-End)
    DISCORD_PALETTE: List[str] = [
        "#5865F2",  # Blurple
        "#57F287",  # Green
        "#FEE75C",  # Yellow
        "#EB459E",  # Fuchsia
        "#ED4245",  # Coral Red
        "#00B0F4",  # Cyan
        "#9B59B6",  # Purple
        "#E67E22",  # Orange
    ]

    # Discord Theme UI Hex Colors
    DISCORD_BG: str = "#2B2D31"       # Primary container background
    DISCORD_CARD_BG: str = "#313338"  # Inner axes / plot card background
    DISCORD_TEXT: str = "#DBDEE1"     # Main white-ish text
    DISCORD_MUTED: str = "#949BA4"    # Subtle secondary text / ticks
    DISCORD_GRID: str = "#3F4147"     # Subtle grid lines
    DISCORD_SPINE: str = "#4E5058"    # Axis border lines

    def __init__(self) -> None:
        self.font_paths = self._discover_font_paths()

    def _discover_font_paths(self) -> List[str]:
        """Locates project-bundled and system Chinese fonts in priority order."""
        candidates = [
            _FONTS_DIR / "NotoSansTC.ttf",
            _FONTS_DIR / "GoogleSans-Regular.ttf",
            _FONTS_DIR / "GoogleSans-Bold.ttf",
            Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"),
            Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc"),
            Path("/usr/share/fonts/truetype/droid/DroidSansFallbackFull.ttf"),
        ]
        valid_paths: List[str] = []
        for p in candidates:
            if p.is_file() and p.stat().st_size > 1000:
                valid_paths.append(str(p.resolve()))
        return valid_paths

    def _generate_runner_script(self, user_code: str, tmpdir: Optional[str] = None) -> str:
        """Generates the isolated wrapper Python script executing inside the sandbox."""
        font_paths_repr = json.dumps(self.font_paths, ensure_ascii=False)
        palette_repr = json.dumps(self.DISCORD_PALETTE, ensure_ascii=False)
        work_dir_repr = json.dumps(str(Path(tmpdir).resolve()) if tmpdir else "")
        project_root_repr = json.dumps(str(_PROJECT_ROOT.resolve()))

        script = f'''# -*- coding: utf-8 -*-
import sys
import os
import json
from pathlib import Path

# 1. Security & Network Isolation via CPython Audit Hooks
_in_user_code = False
_allowed_work_dir = {work_dir_repr}
_project_root = {project_root_repr}

def _sandbox_audit_hook(event, args):
    # 阻斷外網網路連線
    if event in ("socket.connect", "socket.getaddrinfo", "socket.bind", "socket.sendmsg", "socket.sendto"):
        raise PermissionError("沙盒安全限制：禁止外網網路連線 (" + str(event) + ")")
    
    # 阻斷衍生子行程
    if event in ("os.system", "subprocess.Popen", "os.spawn", "os.posix_spawn", "os.exec", "os.execve", "pty.spawn", "os.fork", "os.forkpty"):
        raise PermissionError("沙盒安全限制：禁止衍生子行程 (" + str(event) + ")")

    # 使用者代碼執行期間的檔案系統與二進位擴充嚴格防護
    if _in_user_code:
        # 阻斷 ctypes 底層調用逃逸（嚴禁載入或調用任意底層 C 二進位函式庫與符號）
        if "ctypes" in event:
            raise PermissionError("沙盒安全限制：禁止調用底層二進位擴充函式庫 (" + str(event) + ")")

        if event == "open":
            try:
                target_path = str(args[0]) if args else ""
                mode = str(args[1]) if len(args) > 1 else "r"
                norm_p = os.path.abspath(target_path)

                # 寫入模式檢查：只允許寫入當前臨時工作目錄
                if any(m in mode for m in ("w", "a", "+", "x")):
                    if _allowed_work_dir and not norm_p.startswith(_allowed_work_dir):
                        raise PermissionError("沙盒安全限制：禁止寫入工作目錄以外之路徑 (" + str(target_path) + ")")

                # 敏感檔案讀取檢查：嚴格阻擋設定檔、金鑰、資料庫與系統敏感檔案
                lower_p = norm_p.lower()
                sensitive_keywords = (
                    ".env", "id_rsa", "id_ed25519", "id_ecdsa", "id_dsa",
                    "/etc/shadow", "/etc/passwd", "/etc/sudoers",
                    "zeronexus.db", ".sqlite", "credentials", "secret",
                    ".git/config", ".ssh"
                )
                if any(kw in lower_p for kw in sensitive_keywords):
                    raise PermissionError("沙盒安全限制：禁止存取敏感系統或專案設定檔 (" + str(target_path) + ")")

                # 嚴禁讀取專案代碼根目錄（字型檔、快取目錄與虛擬環境套件庫除外）
                if _project_root and norm_p.startswith(_project_root):
                    allowed_subpaths = ("/data/fonts", "/data/cache", "/znenv", "/.venv", "/venv")
                    if not any(sub in norm_p for sub in allowed_subpaths):
                        raise PermissionError("沙盒安全限制：禁止越權讀取專案核心目錄 (" + str(target_path) + ")")
            except PermissionError:
                raise
            except Exception:
                pass

        if event in ("os.remove", "os.unlink", "os.rmdir", "shutil.rmtree", "os.rename", "os.replace", "os.chmod", "os.chown"):
            try:
                target_p = str(args[0]) if args else ""
                norm_p = os.path.abspath(target_p)
                if _allowed_work_dir and not norm_p.startswith(_allowed_work_dir):
                    raise PermissionError("沙盒安全限制：禁止修改或刪除沙盒外之檔案 (" + str(event) + ")")
            except PermissionError:
                raise
            except Exception:
                pass

sys.addaudithook(_sandbox_audit_hook)

# Monkeypatch socket methods to ensure immediate, clean blocking without breaking class inheritance
import socket
def _blocked_net(*args, **kwargs):
    raise PermissionError("沙盒安全限制：已完全禁止網路連線 (Network access is disabled in sandbox)")
socket.socket.connect = _blocked_net
socket.socket.connect_ex = _blocked_net
socket.create_connection = _blocked_net

# 2. Memory limits on Linux
try:
    import resource
    mem_bytes = {self.DEFAULT_MEMORY_MB} * 1024 * 1024
    resource.setrlimit(resource.RLIMIT_AS, (mem_bytes, mem_bytes))
except Exception:
    pass

# 3. Fast Lazy-Loading & Preload Setup
class _LazyLoader:
    def __init__(self, loader):
        self._loader = loader
        self._obj = None
    def _ensure_loaded(self):
        if self._obj is None:
            global _in_user_code
            was_in = _in_user_code
            _in_user_code = False
            try:
                self._obj = self._loader()
            finally:
                _in_user_code = was_in
        return self._obj
    def __getattr__(self, attr):
        return getattr(self._ensure_loaded(), attr)
    def __call__(self, *args, **kwargs):
        return self._ensure_loaded()(*args, **kwargs)
    def __getitem__(self, item):
        return self._ensure_loaded()[item]

font_candidates = {font_paths_repr}
discord_colors = {palette_repr}

def _init_matplotlib():
    import logging
    logging.getLogger("matplotlib.font_manager").setLevel(logging.ERROR)
    logging.getLogger("matplotlib").setLevel(logging.WARNING)
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import matplotlib.font_manager as fm

    registered_fonts = []
    for fpath in font_candidates:
        if os.path.isfile(fpath) and os.path.getsize(fpath) > 1000:
            try:
                fm.fontManager.addfont(fpath)
                prop = fm.FontProperties(fname=fpath)
                fname = prop.get_name()
                if fname and fname not in registered_fonts:
                    registered_fonts.append(fname)
            except Exception:
                pass

    for fb in ["Noto Sans TC", "Google Sans", "Noto Sans CJK TC", "Microsoft JhengHei", "PingFang TC", "sans-serif"]:
        if fb not in registered_fonts:
            registered_fonts.append(fb)

    plt.rcParams["font.sans-serif"] = registered_fonts
    plt.rcParams["axes.unicode_minus"] = False

    plt.style.use("dark_background")
    plt.rcParams["figure.facecolor"] = "{self.DISCORD_BG}"
    plt.rcParams["axes.facecolor"] = "{self.DISCORD_CARD_BG}"
    plt.rcParams["savefig.facecolor"] = "{self.DISCORD_BG}"
    plt.rcParams["savefig.edgecolor"] = "{self.DISCORD_BG}"
    plt.rcParams["axes.edgecolor"] = "{self.DISCORD_SPINE}"
    plt.rcParams["axes.labelcolor"] = "{self.DISCORD_TEXT}"
    plt.rcParams["xtick.color"] = "{self.DISCORD_MUTED}"
    plt.rcParams["ytick.color"] = "{self.DISCORD_MUTED}"
    plt.rcParams["text.color"] = "{self.DISCORD_TEXT}"
    plt.rcParams["grid.color"] = "{self.DISCORD_GRID}"
    plt.rcParams["grid.alpha"] = 0.5
    plt.rcParams["grid.linestyle"] = "--"
    plt.rcParams["font.size"] = 11
    plt.rcParams["axes.prop_cycle"] = plt.cycler(color=discord_colors)
    return plt

def _init_seaborn():
    _init_matplotlib()
    import seaborn as sns
    try:
        sns.set_palette(discord_colors)
    except Exception:
        pass
    return sns

_lazy_plt = _LazyLoader(_init_matplotlib)
_lazy_sns = _LazyLoader(_init_seaborn)
_lazy_np = _LazyLoader(lambda: __import__("numpy"))
_lazy_pd = _LazyLoader(lambda: __import__("pandas"))
_lazy_fm = _LazyLoader(lambda: __import__("matplotlib.font_manager", fromlist=["font_manager"]))
_lazy_matplotlib = _LazyLoader(lambda: __import__("matplotlib"))

import math
import datetime

# 4. Execute User Code
user_code_str = {json.dumps(user_code)}
user_env = {{
    "__name__": "__main__",
    "matplotlib": _lazy_matplotlib,
    "plt": _lazy_plt,
    "fm": _lazy_fm,
    "sns": _lazy_sns,
    "np": _lazy_np,
    "pd": _lazy_pd,
    "math": math,
    "datetime": datetime,
    "json": json,
    "DISCORD_PALETTE": discord_colors,
}}

# 若代碼包含繪圖相關呼叫，在進入嚴格安全審核前預先完成繪圖函式庫載入
if any(k in user_code_str for k in ("plt", "matplotlib", "sns", "seaborn")):
    try:
        _lazy_plt._ensure_loaded()
    except Exception:
        pass

_in_user_code = True
try:
    exec(user_code_str, user_env)
except Exception as user_exc:
    print("執行階段錯誤 (RuntimeError): " + str(user_exc), file=sys.stderr)
    import traceback
    traceback.print_exc(file=sys.stderr)
    sys.exit(1)
finally:
    _in_user_code = False

# 5. Automatic Chart Capture
try:
    import sys
    active_plt = None
    if "matplotlib.pyplot" in sys.modules:
        active_plt = sys.modules["matplotlib.pyplot"]
    elif _lazy_plt._obj is not None:
        active_plt = _lazy_plt
    elif "plt" in user_env and hasattr(user_env["plt"], "get_fignums"):
        active_plt = user_env["plt"]

    if active_plt is not None and active_plt.get_fignums():
        active_plt.tight_layout()
        active_plt.savefig("output.png", dpi=150, bbox_inches="tight")
        active_plt.close("all")
except Exception as save_err:
    print("圖表捕捉錯誤: " + str(save_err), file=sys.stderr)
'''
        return script

    async def execute_code(
        self,
        code: str,
        timeout: float = DEFAULT_TIMEOUT,
    ) -> SandboxResult:
        """Executes Python code in a safe, isolated subprocess with timeout and resource limits."""
        timeout_val = min(max(float(timeout), 0.5), self.MAX_TIMEOUT)
        t0 = time.perf_counter()

        with tempfile.TemporaryDirectory(prefix="zn_sandbox_") as tmpdir:
            runner_file = os.path.join(tmpdir, "runner.py")
            output_png = os.path.join(tmpdir, "output.png")
            mpl_cache_dir = _PROJECT_ROOT / "data" / "cache" / "matplotlib"
            mpl_cache_dir.mkdir(parents=True, exist_ok=True)

            script_content = self._generate_runner_script(code, tmpdir=tmpdir)
            with open(runner_file, "w", encoding="utf-8") as f:
                f.write(script_content)

            # Build sanitized environment
            clean_env = {
                "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
                "PYTHONUNBUFFERED": "1",
                "MPLCONFIGDIR": str(mpl_cache_dir),
                "LANG": "C.UTF-8",
                "LC_ALL": "C.UTF-8",
            }
            # Preserve virtualenv if active
            if "VIRTUAL_ENV" in os.environ:
                clean_env["VIRTUAL_ENV"] = os.environ["VIRTUAL_ENV"]
            if "PYTHONPATH" in os.environ:
                clean_env["PYTHONPATH"] = os.environ["PYTHONPATH"]

            # Select python executable (prefer project virtualenv if available)
            py_bin = sys.executable
            znenv_py = _PROJECT_ROOT / "znenv" / "bin" / "python"
            if not znenv_py.exists():
                znenv_py = _PROJECT_ROOT / "znenv" / "bin" / "python3"
            if znenv_py.exists():
                py_bin = str(znenv_py)

            try:
                proc = await asyncio.create_subprocess_exec(
                    py_bin,
                    runner_file,
                    cwd=tmpdir,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    env=clean_env,
                )

                try:
                    stdout_data, stderr_data = await asyncio.wait_for(
                        proc.communicate(),
                        timeout=timeout_val,
                    )
                except asyncio.TimeoutError:
                    try:
                        proc.kill()
                        await proc.wait()
                    except Exception:
                        pass
                    elapsed_ms = (time.perf_counter() - t0) * 1000.0
                    return SandboxResult(
                        success=False,
                        stdout="",
                        stderr="",
                        has_image=False,
                        execution_time_ms=elapsed_ms,
                        error=f"執行逾時（超過 {timeout_val:.1f} 秒安全限制）",
                    )

                elapsed_ms = (time.perf_counter() - t0) * 1000.0
                stdout_str = stdout_data.decode("utf-8", errors="replace")
                stderr_str = stderr_data.decode("utf-8", errors="replace")

                # Check if image was captured
                has_image = os.path.isfile(output_png) and os.path.getsize(output_png) > 0
                image_bytes: Optional[bytes] = None
                image_base64: Optional[str] = None
                if has_image:
                    with open(output_png, "rb") as img_f:
                        image_bytes = img_f.read()
                        image_base64 = base64.b64encode(image_bytes).decode("ascii")

                is_success = (proc.returncode == 0) and ("執行階段錯誤" not in stderr_str)
                err_msg = None
                if not is_success:
                    err_msg = stderr_str.strip() or f"行程退出代碼異常: {proc.returncode}"

                return SandboxResult(
                    success=is_success,
                    stdout=stdout_str,
                    stderr=stderr_str,
                    has_image=has_image,
                    image_bytes=image_bytes,
                    image_base64=image_base64,
                    execution_time_ms=elapsed_ms,
                    error=err_msg,
                )

            except Exception as e:
                elapsed_ms = (time.perf_counter() - t0) * 1000.0
                log.error(f"[CodeSandbox] Subprocess execution exception: {e}")
                return SandboxResult(
                    success=False,
                    stdout="",
                    stderr=str(e),
                    has_image=False,
                    execution_time_ms=elapsed_ms,
                    error=f"沙盒內部異常: {e}",
                )

    async def plot_chart(
        self,
        chart_type: str,
        title: str,
        data_json: Union[str, Dict[str, Any], List[Any]],
        x_label: str = "",
        y_label: str = "",
    ) -> SandboxResult:
        """Generates and renders high-end Discord Dark Mode charts from structured data."""
        # Parse data if JSON string
        if isinstance(data_json, str):
            try:
                data = json.loads(data_json)
            except Exception as json_err:
                return SandboxResult(
                    success=False,
                    stdout="",
                    stderr=str(json_err),
                    has_image=False,
                    error=f"資料解析失敗：data_json 不是合法的 JSON 格式 ({json_err})",
                )
        else:
            data = data_json

        ctype = chart_type.lower().strip()
        data_repr = json.dumps(data, ensure_ascii=False)

        # Construct Python plotting code
        code = textwrap.dedent(f"""
            raw_data = {data_repr}
            chart_type = "{ctype}"
            title = "{title}"
            x_label = "{x_label}"
            y_label = "{y_label}"

            fig, ax = plt.subplots(figsize=(9, 5.5), dpi=150)

            # Data Normalization
            labels = []
            values = []

            if isinstance(raw_data, dict):
                if "labels" in raw_data and "values" in raw_data:
                    labels = [str(x) for x in raw_data["labels"]]
                    values = [float(y) for y in raw_data["values"]]
                elif "x" in raw_data and "y" in raw_data:
                    labels = [str(x) for x in raw_data["x"]]
                    values = [float(y) for y in raw_data["y"]]
                else:
                    labels = [str(k) for k in raw_data.keys()]
                    values = [float(v) for v in raw_data.values()]
            elif isinstance(raw_data, list):
                if all(isinstance(item, dict) for item in raw_data):
                    # List of dicts e.g. [dict(name='A', val=10), ...]
                    keys = list(raw_data[0].keys())
                    k_lbl = keys[0]
                    k_val = keys[1] if len(keys) > 1 else keys[0]
                    for it in raw_data:
                        labels.append(str(it.get(k_lbl, "")))
                        values.append(float(it.get(k_val, 0)))
                elif all(isinstance(item, (list, tuple)) and len(item) >= 2 for item in raw_data):
                    for it in raw_data:
                        labels.append(str(it[0]))
                        values.append(float(it[1]))
                else:
                    labels = [str(i + 1) for i in range(len(raw_data))]
                    values = [float(x) for x in raw_data]

            # Render Chart by Type
            if chart_type in ("bar", "bar_chart", "長條圖", "柱狀圖"):
                colors = [DISCORD_PALETTE[i % len(DISCORD_PALETTE)] for i in range(len(labels))]
                bars = ax.bar(labels, values, color=colors, edgecolor="{self.DISCORD_BG}", width=0.6, zorder=3)
                ax.bar_label(bars, padding=3, color="{self.DISCORD_TEXT}", fontsize=10, weight="bold")
                ax.grid(axis="y", linestyle="--", alpha=0.4, color="{self.DISCORD_GRID}", zorder=0)

            elif chart_type in ("line", "line_chart", "折線圖", "走勢圖"):
                ax.plot(labels, values, marker="o", markersize=7, linewidth=2.5, color=DISCORD_PALETTE[0], label="數值", zorder=4)
                ax.fill_between(range(len(labels)), values, color=DISCORD_PALETTE[0], alpha=0.15, zorder=2)
                for i, v in enumerate(values):
                    lbl_txt = str(int(v)) if float(v).is_integer() else str(round(v, 2))
                    ax.annotate(lbl_txt, (i, v), textcoords="offset points", xytext=(0, 8), ha="center", fontsize=9, color="{self.DISCORD_TEXT}", weight="bold")
                ax.grid(True, linestyle="--", alpha=0.4, color="{self.DISCORD_GRID}", zorder=0)

            elif chart_type in ("pie", "pie_chart", "圓餅圖", "餅圖"):
                ax.clear()
                colors = [DISCORD_PALETTE[i % len(DISCORD_PALETTE)] for i in range(len(labels))]
                wedges, texts, autotexts = ax.pie(
                    values,
                    labels=labels,
                    autopct="%1.1f%%",
                    startangle=140,
                    colors=colors,
                    wedgeprops=dict(edgecolor="{self.DISCORD_BG}", linewidth=2),
                    textprops=dict(color="{self.DISCORD_TEXT}", fontsize=11),
                )
                for at in autotexts:
                    at.set_color("#FFFFFF")
                    at.set_weight("bold")

            elif chart_type in ("scatter", "散佈圖", "散布圖"):
                colors = [DISCORD_PALETTE[i % len(DISCORD_PALETTE)] for i in range(len(labels))]
                ax.scatter(labels, values, color=colors, s=80, alpha=0.9, edgecolors="{self.DISCORD_BG}", linewidth=1.5, zorder=3)
                ax.grid(True, linestyle="--", alpha=0.4, color="{self.DISCORD_GRID}", zorder=0)

            elif chart_type in ("hist", "histogram", "直方圖"):
                ax.hist(values, bins=min(len(values), 10), color=DISCORD_PALETTE[0], edgecolor="{self.DISCORD_BG}", alpha=0.85, zorder=3)
                ax.grid(axis="y", linestyle="--", alpha=0.4, color="{self.DISCORD_GRID}", zorder=0)

            else:
                # Default fallback to line
                ax.plot(labels, values, marker="s", color=DISCORD_PALETTE[0], linewidth=2)
                ax.grid(True, linestyle="--", alpha=0.4, color="{self.DISCORD_GRID}")

            # Titles & Labels
            if title:
                ax.set_title(title, fontsize=14, weight="bold", pad=15, color="{self.DISCORD_TEXT}")
            if x_label:
                ax.set_xlabel(x_label, fontsize=11, labelpad=8, color="{self.DISCORD_MUTED}")
            if y_label:
                ax.set_ylabel(y_label, fontsize=11, labelpad=8, color="{self.DISCORD_MUTED}")

            # Rotate x labels if long or many
            if len(labels) > 6 or any(len(str(lbl)) > 4 for lbl in labels):
                plt.xticks(rotation=25, ha="right")

            print(f"圖表繪製完成：{{title}} (類型: {{chart_type}}, 數據點: {{len(values)}})")
        """)

        return await self.execute_code(code)


# Master singleton instance
code_sandbox = CodeSandboxEngine()

__all__ = ["CodeSandboxEngine", "SandboxResult", "code_sandbox"]
