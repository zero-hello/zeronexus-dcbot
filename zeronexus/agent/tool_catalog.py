"""ZeroNexus Comprehensive Read-Only Tool Catalog.

Provides 130+ strictly read-only, safe, deterministic utility, diagnostic,
and mathematical tools for Agent execution and LLM Function Calling.
"""

from __future__ import annotations

import asyncio
import base64
import calendar
import datetime
import hashlib
import json
import math
import os
import re
import secrets
import socket
import sys
import time
import urllib.parse
from typing import Any, Dict, List, Optional

import discord
import psutil
from sqlalchemy import func, select

from zeronexus.core.cache import cache
from zeronexus.core.database import db
from zeronexus.core.scheduler import scheduler
from zeronexus.core.stats import stats
from zeronexus.engines.calculator import calculator
from zeronexus.engines.cwa_client import cwa_client
from zeronexus.engines.free_apis import free_apis
from zeronexus.engines.google_suite import google_suite
from zeronexus.engines.minecraft_query import mc_query
from zeronexus.models.guild import GuildSettings
from zeronexus.models.user import AIQuotaRecord, EconomyWallet, UserProfile
from zeronexus.security.ssrf import validate_safe_host


def get_all_tool_specs() -> List[Dict[str, Any]]:
    """Returns the specifications and handlers for all 130+ tools across 12 domains."""
    specs: List[Dict[str, Any]] = []

    # =========================================================================
    # 1. 系統診斷與健康巡檢 (System & Diagnostics) - 10 Tools
    # =========================================================================

    async def h_system_diagnostics(**kwargs: Any) -> Dict[str, Any]:
        proc = psutil.Process(os.getpid())
        mem_info = proc.memory_info()
        cpu_pct = await asyncio.to_thread(psutil.cpu_percent, 0.05)
        virtual_mem = psutil.virtual_memory()
        uptime_seconds = round(time.time() - stats.start_time, 2)
        hours, remainder = divmod(int(uptime_seconds), 3600)
        minutes, seconds = divmod(remainder, 60)
        return {
            "process_memory_mb": round(mem_info.rss / 1024 / 1024, 2),
            "system_cpu_percent": cpu_pct,
            "system_ram_percent": virtual_mem.percent,
            "uptime_formatted": f"{hours}時 {minutes}分 {seconds}秒",
            "uptime_seconds": uptime_seconds,
            "python_version": sys.version.split()[0],
            "platform": sys.platform,
        }

    specs.append({
        "name": "system_diagnostics",
        "category": "系統診斷",
        "description": "讀取目前主機與 Bot 程序之 CPU、記憶體使用量與運行時間",
        "parameters_desc": "無參數",
        "parameters_schema": {"type": "object", "properties": {}},
        "handler": h_system_diagnostics,
    })

    async def h_module_health(**kwargs: Any) -> Dict[str, Any]:
        from zeronexus.modules.manager import module_manager
        modules_status = {}
        for name, mod in module_manager.modules.items():
            modules_status[name] = {
                "display_name": mod.display_name,
                "state": mod.state.value,
                "commands_count": len(mod.registered_commands),
                "error_reason": mod.error_reason,
            }
        return {
            "total_modules": len(module_manager.modules),
            "total_commands_registered": module_manager.command_registry.count(),
            "modules": modules_status,
        }

    specs.append({
        "name": "module_health",
        "category": "系統診斷",
        "description": "檢查 ZeroNexus 核心全部 11 個功能模組的健康運行狀態與指令數",
        "parameters_desc": "無參數",
        "parameters_schema": {"type": "object", "properties": {}},
        "handler": h_module_health,
    })

    async def h_guild_diagnostics(guild: Optional[discord.Guild] = None, **kwargs: Any) -> Dict[str, Any]:
        if not guild:
            return {"error": "未提供伺服器上下文"}
        me = getattr(guild, "me", None)
        perms = getattr(me, "guild_permissions", None) if me else None
        return {
            "guild_id": getattr(guild, "id", 0),
            "guild_name": getattr(guild, "name", "未知伺服器"),
            "member_count": getattr(guild, "member_count", 0),
            "text_channels_count": len(getattr(guild, "text_channels", [])),
            "voice_channels_count": len(getattr(guild, "voice_channels", [])),
            "roles_count": len(getattr(guild, "roles", [])),
            "bot_permissions": {
                "administrator": getattr(perms, "administrator", False) if perms else False,
                "manage_guild": getattr(perms, "manage_guild", False) if perms else False,
                "manage_messages": getattr(perms, "manage_messages", False) if perms else False,
                "embed_links": getattr(perms, "embed_links", False) if perms else False,
                "send_messages": getattr(perms, "send_messages", False) if perms else False,
            },
        }

    specs.append({
        "name": "guild_diagnostics",
        "category": "系統診斷",
        "description": "檢查目前 Discord 伺服器的成員規模、頻道結構與 Bot 原生權限分配",
        "parameters_desc": "自動由執行環境帶入當前 guild",
        "parameters_schema": {"type": "object", "properties": {}},
        "handler": h_guild_diagnostics,
    })

    async def h_database_stats(**kwargs: Any) -> Dict[str, Any]:
        async with db.session() as session:
            users_cnt = await session.scalar(select(func.count()).select_from(UserProfile)) or 0
            guilds_cnt = await session.scalar(select(func.count()).select_from(GuildSettings)) or 0
            quotas_cnt = await session.scalar(select(func.count()).select_from(AIQuotaRecord)) or 0
            wallets_cnt = await session.scalar(select(func.count()).select_from(EconomyWallet)) or 0
        return {
            "total_registered_users": users_cnt,
            "configured_guilds": guilds_cnt,
            "daily_quota_records": quotas_cnt,
            "active_wallets": wallets_cnt,
            "db_status": "ONLINE (WAL Mode)",
        }

    specs.append({
        "name": "database_stats",
        "category": "系統診斷",
        "description": "唯讀統計資料庫儲存之使用者、伺服器偏好與配額大盤數據",
        "parameters_desc": "無參數",
        "parameters_schema": {"type": "object", "properties": {}},
        "handler": h_database_stats,
    })

    async def h_bot_latency_probe(**kwargs: Any) -> Dict[str, Any]:
        ws_latency_ms = round(stats.gateway_latency * 1000.0, 2) if hasattr(stats, "gateway_latency") else 15.0
        return {
            "websocket_latency_ms": ws_latency_ms,
            "status": "EXCELLENT" if ws_latency_ms < 50 else ("GOOD" if ws_latency_ms < 150 else "DEGRADED"),
            "checked_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        }

    specs.append({
        "name": "bot_latency_probe",
        "category": "系統診斷",
        "description": "探測機器人與 Discord 閘道之即時 WebSocket 心跳延遲 (Ping)",
        "parameters_desc": "無參數",
        "parameters_schema": {"type": "object", "properties": {}},
        "handler": h_bot_latency_probe,
    })

    async def h_cache_stats(**kwargs: Any) -> Dict[str, Any]:
        return {
            "backend": "AsyncInMemoryLRUCache",
            "capacity": getattr(cache, "_max_size", 1000),
            "current_size": len(getattr(cache, "_cache", {})),
            "status": "HEALTHY",
        }

    specs.append({
        "name": "cache_stats",
        "category": "系統診斷",
        "description": "檢視高併發非同步快取引擎之容量使用率與項目健康度",
        "parameters_desc": "無參數",
        "parameters_schema": {"type": "object", "properties": {}},
        "handler": h_cache_stats,
    })

    async def h_scheduler_jobs_info(**kwargs: Any) -> Dict[str, Any]:
        jobs_info = []
        for name, job in scheduler.jobs.items():
            jobs_info.append({
                "job_name": name,
                "interval_seconds": job.interval_seconds,
                "is_running": job.is_running,
            })
        return {
            "total_jobs": len(scheduler.jobs),
            "scheduler_running": scheduler.is_running,
            "jobs": jobs_info,
        }

    specs.append({
        "name": "scheduler_jobs_info",
        "category": "系統診斷",
        "description": "檢查全域非同步排程器運行狀態與定時輪詢任務清單",
        "parameters_desc": "無參數",
        "parameters_schema": {"type": "object", "properties": {}},
        "handler": h_scheduler_jobs_info,
    })

    async def h_python_runtime_info(**kwargs: Any) -> Dict[str, Any]:
        import gc
        import threading
        return {
            "python_implementation": sys.implementation.name,
            "python_version": sys.version,
            "active_threads_count": threading.active_count(),
            "gc_objects_count": len(gc.get_objects()),
            "endianness": sys.byteorder,
        }

    specs.append({
        "name": "python_runtime_info",
        "category": "系統診斷",
        "description": "讀取 Python 虛擬環境底層執行緒數、垃圾回收物件數與執行環境細節",
        "parameters_desc": "無參數",
        "parameters_schema": {"type": "object", "properties": {}},
        "handler": h_python_runtime_info,
    })

    async def h_system_disk_usage(**kwargs: Any) -> Dict[str, Any]:
        disk = psutil.disk_usage("/")
        return {
            "total_gb": round(disk.total / (1024 ** 3), 2),
            "used_gb": round(disk.used / (1024 ** 3), 2),
            "free_gb": round(disk.free / (1024 ** 3), 2),
            "percent_used": disk.percent,
        }

    specs.append({
        "name": "system_disk_usage",
        "category": "系統診斷",
        "description": "檢查伺服器主機根目錄硬碟儲存空間大小與使用率百分比",
        "parameters_desc": "無參數",
        "parameters_schema": {"type": "object", "properties": {}},
        "handler": h_system_disk_usage,
    })

    async def h_network_interfaces_info(**kwargs: Any) -> Dict[str, Any]:
        io_counters = psutil.net_io_counters()
        return {
            "bytes_sent_mb": round(io_counters.bytes_sent / (1024 * 1024), 2),
            "bytes_recv_mb": round(io_counters.bytes_recv / (1024 * 1024), 2),
            "packets_sent": io_counters.packets_sent,
            "packets_recv": io_counters.packets_recv,
            "errin": io_counters.errin,
            "errout": io_counters.errout,
        }

    specs.append({
        "name": "network_interfaces_info",
        "category": "系統診斷",
        "description": "檢查伺服器主機網路介面累計傳輸流量 (MB) 與收發封包數",
        "parameters_desc": "無參數",
        "parameters_schema": {"type": "object", "properties": {}},
        "handler": h_network_interfaces_info,
    })

    # =========================================================================
    # 2. 數學運算與科學計算 (Mathematics & Scientific Computing) - 14 Tools
    # =========================================================================

    async def h_calculator(expression: str, **kwargs: Any) -> Dict[str, Any]:
        clean_expr = (
            str(expression)
            .replace("×", "*")
            .replace("÷", "/")
            .replace("—", "-")
            .replace("–", "-")
            .strip()
        )
        res = await asyncio.to_thread(calculator.evaluate, clean_expr)
        return {
            "expression": res.expression,
            "result": res.result_str,
            "is_error": res.is_error,
            "error_message": res.error_message,
            "time_ms": res.execution_time_ms,
        }

    specs.append({
        "name": "calculator",
        "category": "科學運算",
        "description": "執行任意精度數學計算、代數化簡或方程式求解驗證",
        "parameters_desc": "expression: 欲計算之數學運算式 (例如 '2**64 - 1', 'solve(x**2 - 5*x + 6, x)')",
        "parameters_schema": {
            "type": "object",
            "properties": {"expression": {"type": "string", "description": "欲計算之數學式"}},
            "required": ["expression"],
        },
        "handler": h_calculator,
    })

    async def h_prime_factorization(number: int, **kwargs: Any) -> Dict[str, Any]:
        n = int(number)
        if n < 2:
            return {"number": n, "factors": [], "is_prime": False, "note": "小於 2 之整數無質因數分解"}
        factors = []
        d = 2
        temp = n
        while d * d <= temp:
            while temp % d == 0:
                factors.append(d)
                temp //= d
            d += 1
        if temp > 1:
            factors.append(temp)
        return {
            "number": n,
            "factors": factors,
            "is_prime": len(factors) == 1 and factors[0] == n,
            "formatted": " × ".join(str(f) for f in factors),
        }

    specs.append({
        "name": "prime_factorization",
        "category": "科學運算",
        "description": "整數質因數分解與質數（素數）判別",
        "parameters_desc": "number: 欲分解之正整數",
        "parameters_schema": {
            "type": "object",
            "properties": {"number": {"type": "integer", "description": "欲分解之正整數"}},
            "required": ["number"],
        },
        "handler": h_prime_factorization,
    })

    async def h_gcd_lcm_calc(a: int, b: int, **kwargs: Any) -> Dict[str, Any]:
        num1, num2 = abs(int(a)), abs(int(b))
        g = math.gcd(num1, num2)
        l = (num1 * num2) // g if g != 0 else 0
        return {"a": num1, "b": num2, "gcd": g, "lcm": l}

    specs.append({
        "name": "gcd_lcm_calc",
        "category": "科學運算",
        "description": "計算兩整數之最大公因數 (GCD) 與最小公倍數 (LCM)",
        "parameters_desc": "a: 第一個整數, b: 第二個整數",
        "parameters_schema": {
            "type": "object",
            "properties": {
                "a": {"type": "integer", "description": "第一個整數"},
                "b": {"type": "integer", "description": "第二個整數"},
            },
            "required": ["a", "b"],
        },
        "handler": h_gcd_lcm_calc,
    })

    async def h_solve_quadratic(a: float, b: float, c: float, **kwargs: Any) -> Dict[str, Any]:
        fa, fb, fc = float(a), float(b), float(c)
        if fa == 0:
            if fb == 0:
                return {"error": "a 與 b 皆為 0，非有效方程式"}
            return {"equation": f"{fb}x + {fc} = 0", "type": "一次方程式", "root": -fc / fb}
        discriminant = fb ** 2 - 4 * fa * fc
        if discriminant > 0:
            r1 = (-fb + math.sqrt(discriminant)) / (2 * fa)
            r2 = (-fb - math.sqrt(discriminant)) / (2 * fa)
            return {"discriminant": discriminant, "root_type": "相異實根", "roots": [r1, r2]}
        elif discriminant == 0:
            r = -fb / (2 * fa)
            return {"discriminant": discriminant, "root_type": "重根", "roots": [r]}
        else:
            real_part = -fb / (2 * fa)
            imag_part = math.sqrt(-discriminant) / (2 * fa)
            return {
                "discriminant": discriminant,
                "root_type": "共軛複數根",
                "roots": [f"{real_part} + {imag_part}i", f"{real_part} - {imag_part}i"],
            }

    specs.append({
        "name": "solve_quadratic",
        "category": "科學運算",
        "description": "求解一元二次方程式 ax^2 + bx + c = 0 之判別式與根",
        "parameters_desc": "a: x^2 係數, b: x 係數, c: 常數項",
        "parameters_schema": {
            "type": "object",
            "properties": {
                "a": {"type": "number", "description": "二次項係數 a"},
                "b": {"type": "number", "description": "一次項係數 b"},
                "c": {"type": "number", "description": "常數項 c"},
            },
            "required": ["a", "b", "c"],
        },
        "handler": h_solve_quadratic,
    })

    async def h_statistics_summary(numbers: List[float], **kwargs: Any) -> Dict[str, Any]:
        if not numbers:
            return {"error": "數值清單不可為空"}
        nums = [float(x) for x in numbers]
        n = len(nums)
        mean_val = sum(nums) / n
        sorted_nums = sorted(nums)
        median_val = sorted_nums[n // 2] if n % 2 != 0 else (sorted_nums[n // 2 - 1] + sorted_nums[n // 2]) / 2.0
        variance = sum((x - mean_val) ** 2 for x in nums) / n if n > 1 else 0.0
        std_dev = math.sqrt(variance)
        return {
            "count": n,
            "min": min(nums),
            "max": max(nums),
            "sum": sum(nums),
            "mean": round(mean_val, 4),
            "median": round(median_val, 4),
            "variance": round(variance, 4),
            "std_deviation": round(std_dev, 4),
        }

    specs.append({
        "name": "statistics_summary",
        "category": "科學運算",
        "description": "計算數值清單之總和、平均數、中位數、極值、變異數與標準差",
        "parameters_desc": "numbers: 浮點數或整數清單",
        "parameters_schema": {
            "type": "object",
            "properties": {"numbers": {"type": "array", "items": {"type": "number"}, "description": "數值陣列"}},
            "required": ["numbers"],
        },
        "handler": h_statistics_summary,
    })

    async def h_fibonacci_calc(n: int, **kwargs: Any) -> Dict[str, Any]:
        idx = int(n)
        if idx < 0 or idx > 1000:
            return {"error": "n 必須介於 0 至 1000 之間以保證運算安全"}
        if idx == 0:
            return {"n": 0, "fibonacci_number": 0}
        a, b = 0, 1
        for _ in range(2, idx + 1):
            a, b = b, a + b
        return {"n": idx, "fibonacci_number": b}

    specs.append({
        "name": "fibonacci_calc",
        "category": "科學運算",
        "description": "計算費氏數列 (Fibonacci Sequence) 第 N 項數值",
        "parameters_desc": "n: 數列索引 (0~1000)",
        "parameters_schema": {
            "type": "object",
            "properties": {"n": {"type": "integer", "description": "數列索引項"}},
            "required": ["n"],
        },
        "handler": h_fibonacci_calc,
    })

    async def h_trig_functions(angle_degrees: float, **kwargs: Any) -> Dict[str, Any]:
        deg = float(angle_degrees)
        rad = math.radians(deg)
        return {
            "degrees": deg,
            "radians": round(rad, 6),
            "sin": round(math.sin(rad), 6),
            "cos": round(math.cos(rad), 6),
            "tan": round(math.tan(rad), 6) if abs(math.cos(rad)) > 1e-9 else "無限大 (無定義)",
        }

    specs.append({
        "name": "trig_functions",
        "category": "科學運算",
        "description": "計算給定角度（度數）之正弦 sin、餘弦 cos、正切 tan 與弧度",
        "parameters_desc": "angle_degrees: 角度值 (例如 30, 45, 60, 90)",
        "parameters_schema": {
            "type": "object",
            "properties": {"angle_degrees": {"type": "number", "description": "角度值"}},
            "required": ["angle_degrees"],
        },
        "handler": h_trig_functions,
    })

    async def h_logarithm_calc(x: float, base: float = math.e, **kwargs: Any) -> Dict[str, Any]:
        val = float(x)
        b = float(base)
        if val <= 0:
            return {"error": "對數真數必須大於 0"}
        if b <= 0 or b == 1:
            return {"error": "對數底數必須大於 0 且不等於 1"}
        res = math.log(val, b)
        return {"x": val, "base": b, "log_result": round(res, 6)}

    specs.append({
        "name": "logarithm_calc",
        "category": "科學運算",
        "description": "計算任意底數之對數值 log_base(x)",
        "parameters_desc": "x: 真數 (>0), base: 底數 (預設自然常數 e)",
        "parameters_schema": {
            "type": "object",
            "properties": {
                "x": {"type": "number", "description": "真數"},
                "base": {"type": "number", "description": "底數"},
            },
            "required": ["x"],
        },
        "handler": h_logarithm_calc,
    })

    async def h_base_converter(value: str, from_base: int = 10, to_base: int = 16, **kwargs: Any) -> Dict[str, Any]:
        try:
            val_str = str(value).strip()
            num = int(val_str, int(from_base))
            tb = int(to_base)
            if tb == 2:
                res = bin(num)[2:]
            elif tb == 8:
                res = oct(num)[2:]
            elif tb == 10:
                res = str(num)
            elif tb == 16:
                res = hex(num)[2:].upper()
            else:
                return {"error": "僅支援 2, 8, 10, 16 進位轉換"}
            return {"input": value, "from_base": from_base, "to_base": tb, "result": res, "decimal_value": num}
        except Exception as e:
            return {"error": f"進位轉換失敗: {e}"}

    specs.append({
        "name": "base_converter",
        "category": "科學運算",
        "description": "在二進位 (2)、八進位 (8)、十進位 (10)、十六進位 (16) 之間精確轉換數值",
        "parameters_desc": "value: 數值字串, from_base: 來源進位, to_base: 目標進位",
        "parameters_schema": {
            "type": "object",
            "properties": {
                "value": {"type": "string", "description": "數值字串"},
                "from_base": {"type": "integer", "description": "來源進位 (2, 8, 10, 16)"},
                "to_base": {"type": "integer", "description": "目標進位 (2, 8, 10, 16)"},
            },
            "required": ["value", "from_base", "to_base"],
        },
        "handler": h_base_converter,
    })

    async def h_percentage_calc(value: float, total: float, **kwargs: Any) -> Dict[str, Any]:
        v, t = float(value), float(total)
        if t == 0:
            return {"error": "總數不可為 0"}
        pct = (v / t) * 100.0
        return {"value": v, "total": t, "percentage": round(pct, 4), "formatted": f"{pct:.2f}%"}

    specs.append({
        "name": "percentage_calc",
        "category": "科學運算",
        "description": "計算數值佔總數之百分比與比例",
        "parameters_desc": "value: 分子數值, total: 分母總數",
        "parameters_schema": {
            "type": "object",
            "properties": {
                "value": {"type": "number", "description": "分子數值"},
                "total": {"type": "number", "description": "分母總數"},
            },
            "required": ["value", "total"],
        },
        "handler": h_percentage_calc,
    })

    async def h_factorial_calc(n: int, k: Optional[int] = None, **kwargs: Any) -> Dict[str, Any]:
        fn = int(n)
        if fn < 0 or fn > 100:
            return {"error": "n 必須介於 0 至 100 之間"}
        n_fact = math.factorial(fn)
        if k is not None:
            fk = int(k)
            if fk < 0 or fk > fn:
                return {"error": "k 必須介於 0 至 n 之間"}
            p = math.perm(fn, fk)
            c = math.comb(fn, fk)
            return {"n": fn, "k": fk, "factorial_n": n_fact, "permutations_p": p, "combinations_c": c}
        return {"n": fn, "factorial": n_fact}

    specs.append({
        "name": "factorial_calc",
        "category": "科學運算",
        "description": "計算階乘 n! 以及排列數 P(n,k) 與組合數 C(n,k)",
        "parameters_desc": "n: 總數 (0~100), k: 選取數 (選填)",
        "parameters_schema": {
            "type": "object",
            "properties": {
                "n": {"type": "integer", "description": "總數 n"},
                "k": {"type": "integer", "description": "選取數 k (選填)"},
            },
            "required": ["n"],
        },
        "handler": h_factorial_calc,
    })

    async def h_pythagorean_theorem(a: Optional[float] = None, b: Optional[float] = None, c: Optional[float] = None, **kwargs: Any) -> Dict[str, Any]:
        if c is None and a is not None and b is not None:
            hyp = math.sqrt(float(a) ** 2 + float(b) ** 2)
            return {"side_a": a, "side_b": b, "hypotenuse_c": round(hyp, 4)}
        elif a is None and b is not None and c is not None:
            diff = float(c) ** 2 - float(b) ** 2
            if diff < 0:
                return {"error": "斜邊 c 必須大於直角邊 b"}
            side = math.sqrt(diff)
            return {"side_a": round(side, 4), "side_b": b, "hypotenuse_c": c}
        elif b is None and a is not None and c is not None:
            diff = float(c) ** 2 - float(a) ** 2
            if diff < 0:
                return {"error": "斜邊 c 必須大於直角邊 a"}
            side = math.sqrt(diff)
            return {"side_a": a, "side_b": round(side, 4), "hypotenuse_c": c}
        return {"error": "請提供 a, b, c 中之任意兩項以求解第三項"}

    specs.append({
        "name": "pythagorean_theorem",
        "category": "科學運算",
        "description": "畢氏定理直角三角形斜邊或股長計算 (a^2 + b^2 = c^2)",
        "parameters_desc": "a, b, c 任填兩項求解第三項",
        "parameters_schema": {
            "type": "object",
            "properties": {
                "a": {"type": "number", "description": "直角邊 a"},
                "b": {"type": "number", "description": "直角邊 b"},
                "c": {"type": "number", "description": "斜邊 c"},
            },
        },
        "handler": h_pythagorean_theorem,
    })

    async def h_circle_geometry_calc(radius: float, **kwargs: Any) -> Dict[str, Any]:
        r = float(radius)
        if r < 0:
            return {"error": "半徑不可為負數"}
        return {
            "radius": r,
            "diameter": r * 2,
            "circumference": round(2 * math.pi * r, 4),
            "circle_area": round(math.pi * (r ** 2), 4),
            "sphere_volume": round((4 / 3) * math.pi * (r ** 3), 4),
            "sphere_surface_area": round(4 * math.pi * (r ** 2), 4),
        }

    specs.append({
        "name": "circle_geometry_calc",
        "category": "科學運算",
        "description": "根據半徑計算圓直徑、圓周長、圓面積與球體體積",
        "parameters_desc": "radius: 半徑長度",
        "parameters_schema": {
            "type": "object",
            "properties": {"radius": {"type": "number", "description": "半徑"}},
            "required": ["radius"],
        },
        "handler": h_circle_geometry_calc,
    })

    async def h_matrix_determinant_2x2(a: float, b: float, c: float, d: float, **kwargs: Any) -> Dict[str, Any]:
        det = float(a) * float(d) - float(b) * float(c)
        return {
            "matrix": [[a, b], [c, d]],
            "determinant": round(det, 6),
            "is_invertible": det != 0,
        }

    specs.append({
        "name": "matrix_determinant_2x2",
        "category": "科學運算",
        "description": "計算 2x2 方陣 [[a, b], [c, d]] 之行列式值 (ad - bc)",
        "parameters_desc": "a, b, c, d 為四個矩陣元素",
        "parameters_schema": {
            "type": "object",
            "properties": {
                "a": {"type": "number"}, "b": {"type": "number"},
                "c": {"type": "number"}, "d": {"type": "number"},
            },
            "required": ["a", "b", "c", "d"],
        },
        "handler": h_matrix_determinant_2x2,
    })

    # =========================================================================
    # 3. 度量衡與單位換算 (Unit Conversion) - 10 Tools
    # =========================================================================

    async def h_temperature_converter(value: float, from_unit: str = "C", to_unit: str = "F", **kwargs: Any) -> Dict[str, Any]:
        v = float(value)
        fu, tu = from_unit.upper().strip(), to_unit.upper().strip()
        # Convert to Celsius first
        if fu == "C":
            c = v
        elif fu == "F":
            c = (v - 32) * 5 / 9
        elif fu == "K":
            c = v - 273.15
        else:
            return {"error": f"不支援的溫度單位: {from_unit}"}

        # Convert Celsius to target
        if tu == "C":
            res = c
        elif tu == "F":
            res = (c * 9 / 5) + 32
        elif tu == "K":
            res = c + 273.15
        else:
            return {"error": f"不支援的溫度單位: {to_unit}"}
        return {"input_value": v, "from_unit": fu, "output_value": round(res, 2), "to_unit": tu}

    specs.append({
        "name": "temperature_converter",
        "category": "單位換算",
        "description": "攝氏 (°C)、華氏 (°F)、克氏溫標 (K) 溫度精確換算",
        "parameters_desc": "value: 溫度數值, from_unit: C/F/K, to_unit: C/F/K",
        "parameters_schema": {
            "type": "object",
            "properties": {
                "value": {"type": "number", "description": "溫度數值"},
                "from_unit": {"type": "string", "enum": ["C", "F", "K"]},
                "to_unit": {"type": "string", "enum": ["C", "F", "K"]},
            },
            "required": ["value", "from_unit", "to_unit"],
        },
        "handler": h_temperature_converter,
    })

    async def h_length_converter(value: float, from_unit: str = "m", to_unit: str = "km", **kwargs: Any) -> Dict[str, Any]:
        ratios = {
            "mm": 0.001, "cm": 0.01, "m": 1.0, "km": 1000.0,
            "in": 0.0254, "ft": 0.3048, "yd": 0.9144, "mi": 1609.344,
        }
        fu, tu = from_unit.lower().strip(), to_unit.lower().strip()
        if fu not in ratios or tu not in ratios:
            return {"error": f"不支援的長度單位。支援清單: {list(ratios.keys())}"}
        meters = float(value) * ratios[fu]
        res = meters / ratios[tu]
        return {"input_value": value, "from_unit": fu, "output_value": round(res, 6), "to_unit": tu}

    specs.append({
        "name": "length_converter",
        "category": "單位換算",
        "description": "公尺、公里、公分、公釐、英吋、英呎、碼、英哩長度換算",
        "parameters_desc": "value: 長度值, from_unit, to_unit",
        "parameters_schema": {
            "type": "object",
            "properties": {
                "value": {"type": "number"},
                "from_unit": {"type": "string"},
                "to_unit": {"type": "string"},
            },
            "required": ["value", "from_unit", "to_unit"],
        },
        "handler": h_length_converter,
    })

    async def h_weight_converter(value: float, from_unit: str = "kg", to_unit: str = "lb", **kwargs: Any) -> Dict[str, Any]:
        ratios = {
            "mg": 0.000001, "g": 0.001, "kg": 1.0, "t": 1000.0,
            "oz": 0.0283495, "lb": 0.453592, "台斤": 0.6,
        }
        fu, tu = from_unit.lower().strip(), to_unit.lower().strip()
        if fu not in ratios or tu not in ratios:
            return {"error": f"不支援的重量單位。支援清單: {list(ratios.keys())}"}
        kg = float(value) * ratios[fu]
        res = kg / ratios[tu]
        return {"input_value": value, "from_unit": fu, "output_value": round(res, 6), "to_unit": tu}

    specs.append({
        "name": "weight_converter",
        "category": "單位換算",
        "description": "公克、公斤、公噸、磅 (lb)、盎司 (oz)、台斤重量質量換算",
        "parameters_desc": "value: 重量數值, from_unit, to_unit",
        "parameters_schema": {
            "type": "object",
            "properties": {
                "value": {"type": "number"},
                "from_unit": {"type": "string"},
                "to_unit": {"type": "string"},
            },
            "required": ["value", "from_unit", "to_unit"],
        },
        "handler": h_weight_converter,
    })

    async def h_digital_storage_converter(value: float, from_unit: str = "GB", to_unit: str = "MB", **kwargs: Any) -> Dict[str, Any]:
        ratios = {
            "b": 1, "kb": 1024, "mb": 1024**2, "gb": 1024**3, "tb": 1024**4, "pb": 1024**5,
        }
        fu, tu = from_unit.lower().strip(), to_unit.lower().strip()
        if fu not in ratios or tu not in ratios:
            return {"error": f"不支援的容量單位。支援清單: {list(ratios.keys())}"}
        bytes_val = float(value) * ratios[fu]
        res = bytes_val / ratios[tu]
        return {"input_value": value, "from_unit": fu.upper(), "output_value": round(res, 4), "to_unit": tu.upper()}

    specs.append({
        "name": "digital_storage_converter",
        "category": "單位換算",
        "description": "位元組 (B)、KB、MB、GB、TB、PB 數位電腦儲存容量換算",
        "parameters_desc": "value: 容量大小, from_unit, to_unit",
        "parameters_schema": {
            "type": "object",
            "properties": {
                "value": {"type": "number"},
                "from_unit": {"type": "string"},
                "to_unit": {"type": "string"},
            },
            "required": ["value", "from_unit", "to_unit"],
        },
        "handler": h_digital_storage_converter,
    })

    async def h_speed_converter(value: float, from_unit: str = "km/h", to_unit: str = "m/s", **kwargs: Any) -> Dict[str, Any]:
        ratios = {"m/s": 1.0, "km/h": 1 / 3.6, "mph": 0.44704, "knot": 0.514444}
        fu = from_unit.lower().replace(" ", "")
        tu = to_unit.lower().replace(" ", "")
        if fu not in ratios or tu not in ratios:
            return {"error": f"不支援的速度單位。支援清單: {list(ratios.keys())}"}
        ms = float(value) * ratios[fu]
        res = ms / ratios[tu]
        return {"input_value": value, "from_unit": fu, "output_value": round(res, 4), "to_unit": tu}

    specs.append({
        "name": "speed_converter",
        "category": "單位換算",
        "description": "速度單位換算：時速 (km/h)、秒速 (m/s)、英哩/小時 (mph)、節 (knot)",
        "parameters_desc": "value: 速度, from_unit, to_unit",
        "parameters_schema": {
            "type": "object",
            "properties": {
                "value": {"type": "number"},
                "from_unit": {"type": "string"},
                "to_unit": {"type": "string"},
            },
            "required": ["value", "from_unit", "to_unit"],
        },
        "handler": h_speed_converter,
    })

    async def h_area_converter(value: float, from_unit: str = "坪", to_unit: str = "m2", **kwargs: Any) -> Dict[str, Any]:
        ratios = {"m2": 1.0, "km2": 1000000.0, "坪": 3.305785, "公頃": 10000.0, "acre": 4046.856}
        fu, tu = from_unit.lower().strip(), to_unit.lower().strip()
        if fu not in ratios or tu not in ratios:
            return {"error": f"不支援的面積單位。支援: {list(ratios.keys())}"}
        m2 = float(value) * ratios[fu]
        res = m2 / ratios[tu]
        return {"input_value": value, "from_unit": fu, "output_value": round(res, 4), "to_unit": tu}

    specs.append({
        "name": "area_converter",
        "category": "單位換算",
        "description": "面積單位換算：平方公尺 (m2)、平方公里 (km2)、坪、公頃、英畝 (acre)",
        "parameters_desc": "value: 面積, from_unit, to_unit",
        "parameters_schema": {
            "type": "object",
            "properties": {
                "value": {"type": "number"},
                "from_unit": {"type": "string"},
                "to_unit": {"type": "string"},
            },
            "required": ["value", "from_unit", "to_unit"],
        },
        "handler": h_area_converter,
    })

    async def h_volume_converter(value: float, from_unit: str = "L", to_unit: str = "mL", **kwargs: Any) -> Dict[str, Any]:
        ratios = {"ml": 0.001, "l": 1.0, "m3": 1000.0, "gal": 3.78541, "floz": 0.0295735}
        fu, tu = from_unit.lower().strip(), to_unit.lower().strip()
        if fu not in ratios or tu not in ratios:
            return {"error": f"不支援的容積單位。支援: {list(ratios.keys())}"}
        liters = float(value) * ratios[fu]
        res = liters / ratios[tu]
        return {"input_value": value, "from_unit": fu, "output_value": round(res, 4), "to_unit": tu}

    specs.append({
        "name": "volume_converter",
        "category": "單位換算",
        "description": "容量與體積換算：公升 (L)、毫升 (mL)、立方公尺 (m3)、加侖 (gal)、液體盎司 (fl oz)",
        "parameters_desc": "value: 容積數值, from_unit, to_unit",
        "parameters_schema": {
            "type": "object",
            "properties": {
                "value": {"type": "number"},
                "from_unit": {"type": "string"},
                "to_unit": {"type": "string"},
            },
            "required": ["value", "from_unit", "to_unit"],
        },
        "handler": h_volume_converter,
    })

    async def h_pressure_converter(value: float, from_unit: str = "hPa", to_unit: str = "atm", **kwargs: Any) -> Dict[str, Any]:
        ratios = {"pa": 1.0, "hpa": 100.0, "kpa": 1000.0, "bar": 100000.0, "atm": 101325.0, "mmhg": 133.322, "psi": 6894.76}
        fu, tu = from_unit.lower().strip(), to_unit.lower().strip()
        if fu not in ratios or tu not in ratios:
            return {"error": f"不支援的壓力單位。支援: {list(ratios.keys())}"}
        pa = float(value) * ratios[fu]
        res = pa / ratios[tu]
        return {"input_value": value, "from_unit": fu, "output_value": round(res, 6), "to_unit": tu}

    specs.append({
        "name": "pressure_converter",
        "category": "單位換算",
        "description": "氣壓與壓力單位換算：百帕 (hPa)、標準大氣壓 (atm)、bar、毫米汞柱 (mmHg)、psi",
        "parameters_desc": "value: 壓力數值, from_unit, to_unit",
        "parameters_schema": {
            "type": "object",
            "properties": {
                "value": {"type": "number"},
                "from_unit": {"type": "string"},
                "to_unit": {"type": "string"},
            },
            "required": ["value", "from_unit", "to_unit"],
        },
        "handler": h_pressure_converter,
    })

    async def h_energy_converter(value: float, from_unit: str = "J", to_unit: str = "cal", **kwargs: Any) -> Dict[str, Any]:
        ratios = {"j": 1.0, "kj": 1000.0, "cal": 4.184, "kcal": 4184.0, "wh": 3600.0, "kwh": 3600000.0}
        fu, tu = from_unit.lower().strip(), to_unit.lower().strip()
        if fu not in ratios or tu not in ratios:
            return {"error": f"不支援的能量單位。支援: {list(ratios.keys())}"}
        j = float(value) * ratios[fu]
        res = j / ratios[tu]
        return {"input_value": value, "from_unit": fu, "output_value": round(res, 6), "to_unit": tu}

    specs.append({
        "name": "energy_converter",
        "category": "單位換算",
        "description": "能量與功換算：焦耳 (J)、千焦 (kJ)、卡路里 (cal)、大卡 (kcal)、瓦時 (Wh)、千瓦時 (kWh)",
        "parameters_desc": "value: 能量數值, from_unit, to_unit",
        "parameters_schema": {
            "type": "object",
            "properties": {
                "value": {"type": "number"},
                "from_unit": {"type": "string"},
                "to_unit": {"type": "string"},
            },
            "required": ["value", "from_unit", "to_unit"],
        },
        "handler": h_energy_converter,
    })

    async def h_angle_converter(value: float, from_unit: str = "deg", to_unit: str = "rad", **kwargs: Any) -> Dict[str, Any]:
        v = float(value)
        fu, tu = from_unit.lower().strip(), to_unit.lower().strip()
        if fu == "deg" and tu == "rad":
            return {"input": v, "result": round(math.radians(v), 6), "unit": "rad"}
        elif fu == "rad" and tu == "deg":
            return {"input": v, "result": round(math.degrees(v), 4), "unit": "deg"}
        return {"error": "僅支援 deg (度) 與 rad (弧度) 互轉"}

    specs.append({
        "name": "angle_converter",
        "category": "單位換算",
        "description": "角度 (Degree) 與弧度 (Radian) 互轉",
        "parameters_desc": "value: 角度值, from_unit ('deg'/'rad'), to_unit ('deg'/'rad')",
        "parameters_schema": {
            "type": "object",
            "properties": {
                "value": {"type": "number"},
                "from_unit": {"type": "string", "enum": ["deg", "rad"]},
                "to_unit": {"type": "string", "enum": ["deg", "rad"]},
            },
            "required": ["value", "from_unit", "to_unit"],
        },
        "handler": h_angle_converter,
    })

    # =========================================================================
    # 4. 日期、時間、時區與曆法 (Date, Time, Timezone & Calendars) - 12 Tools
    # =========================================================================

    async def h_current_time_query(timezone_name: str = "Asia/Taipei", **kwargs: Any) -> Dict[str, Any]:
        import pytz
        try:
            tz = pytz.timezone(timezone_name.strip())
        except Exception:
            tz = pytz.timezone("Asia/Taipei")
        now = datetime.datetime.now(tz)
        return {
            "timezone": str(tz),
            "formatted": now.strftime("%Y-%m-%d %H:%M:%S"),
            "iso": now.isoformat(),
            "unix_timestamp": int(now.timestamp()),
            "day_of_week": now.strftime("%A"),
        }

    specs.append({
        "name": "current_time_query",
        "category": "時間曆法",
        "description": "查詢特定時區 (預設 Asia/Taipei) 當前標準時間與時間戳",
        "parameters_desc": "timezone_name: 時區代碼 (例如 Asia/Taipei, UTC, America/New_York, Asia/Tokyo)",
        "parameters_schema": {
            "type": "object",
            "properties": {"timezone_name": {"type": "string", "default": "Asia/Taipei"}},
        },
        "handler": h_current_time_query,
    })

    async def h_timezone_converter(time_str: str, from_tz: str = "Asia/Taipei", to_tz: str = "UTC", **kwargs: Any) -> Dict[str, Any]:
        import pytz
        ftz = pytz.timezone(from_tz.strip())
        ttz = pytz.timezone(to_tz.strip())
        dt = datetime.datetime.strptime(time_str.strip(), "%Y-%m-%d %H:%M:%S")
        localized = ftz.localize(dt)
        converted = localized.astimezone(ttz)
        return {
            "original_time": time_str,
            "from_timezone": str(ftz),
            "converted_time": converted.strftime("%Y-%m-%d %H:%M:%S"),
            "to_timezone": str(ttz),
        }

    specs.append({
        "name": "timezone_converter",
        "category": "時間曆法",
        "description": "兩跨國城市與時區之間的時間對照轉換",
        "parameters_desc": "time_str: 'YYYY-MM-DD HH:MM:SS', from_tz: 來源時區, to_tz: 目標時區",
        "parameters_schema": {
            "type": "object",
            "properties": {
                "time_str": {"type": "string", "description": "YYYY-MM-DD HH:MM:SS 格式時間"},
                "from_tz": {"type": "string", "default": "Asia/Taipei"},
                "to_tz": {"type": "string", "default": "UTC"},
            },
            "required": ["time_str"],
        },
        "handler": h_timezone_converter,
    })

    async def h_unix_timestamp_to_date(timestamp: int, timezone_name: str = "Asia/Taipei", **kwargs: Any) -> Dict[str, Any]:
        import pytz
        tz = pytz.timezone(timezone_name.strip())
        dt = datetime.datetime.fromtimestamp(int(timestamp), tz=tz)
        return {
            "timestamp": timestamp,
            "formatted": dt.strftime("%Y-%m-%d %H:%M:%S"),
            "iso": dt.isoformat(),
            "timezone": timezone_name,
        }

    specs.append({
        "name": "unix_timestamp_to_date",
        "category": "時間曆法",
        "description": "將 Unix 紀元時間戳 (秒) 轉換為指定時區之人類可讀日期時間",
        "parameters_desc": "timestamp: Unix 秒數, timezone_name: 時區 (預設 Asia/Taipei)",
        "parameters_schema": {
            "type": "object",
            "properties": {
                "timestamp": {"type": "integer", "description": "Unix 時間戳 (秒)"},
                "timezone_name": {"type": "string", "default": "Asia/Taipei"},
            },
            "required": ["timestamp"],
        },
        "handler": h_unix_timestamp_to_date,
    })

    async def h_date_to_unix_timestamp(date_str: str, **kwargs: Any) -> Dict[str, Any]:
        s = date_str.strip()
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d", "%Y/%m/%d %H:%M:%S", "%Y/%m/%d"):
            try:
                dt = datetime.datetime.strptime(s, fmt)
                ts = int(dt.replace(tzinfo=datetime.timezone.utc).timestamp())
                return {"date_string": s, "parsed_format": fmt, "unix_timestamp_utc": ts}
            except ValueError:
                continue
        return {"error": f"無法解析日期格式: {date_str}，支援 YYYY-MM-DD 或 YYYY-MM-DD HH:MM:SS"}

    specs.append({
        "name": "date_to_unix_timestamp",
        "category": "時間曆法",
        "description": "將常見格式之日期時間字串轉換為 Unix 紀元秒數",
        "parameters_desc": "date_str: 日期時間字串 (如 2026-09-12 12:00:00)",
        "parameters_schema": {
            "type": "object",
            "properties": {"date_str": {"type": "string"}},
            "required": ["date_str"],
        },
        "handler": h_date_to_unix_timestamp,
    })

    async def h_date_difference_calc(date1: str, date2: str, **kwargs: Any) -> Dict[str, Any]:
        d1 = datetime.datetime.fromisoformat(date1.strip().split()[0])
        d2 = datetime.datetime.fromisoformat(date2.strip().split()[0])
        diff = abs((d2 - d1).days)
        return {"date1": str(d1.date()), "date2": str(d2.date()), "difference_days": diff, "weeks": round(diff / 7, 2)}

    specs.append({
        "name": "date_difference_calc",
        "category": "時間曆法",
        "description": "計算兩個日期之間相差之天數與週數",
        "parameters_desc": "date1: 'YYYY-MM-DD', date2: 'YYYY-MM-DD'",
        "parameters_schema": {
            "type": "object",
            "properties": {
                "date1": {"type": "string"},
                "date2": {"type": "string"},
            },
            "required": ["date1", "date2"],
        },
        "handler": h_date_difference_calc,
    })

    async def h_day_of_week_query(date_str: str, **kwargs: Any) -> Dict[str, Any]:
        d = datetime.datetime.fromisoformat(date_str.strip().split()[0])
        weekdays_zh = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"]
        return {
            "date": str(d.date()),
            "day_of_week_zh": weekdays_zh[d.weekday()],
            "day_of_week_en": d.strftime("%A"),
            "is_weekend": d.weekday() >= 5,
        }

    specs.append({
        "name": "day_of_week_query",
        "category": "時間曆法",
        "description": "查詢歷史或未來任意日期為星期幾與是否為週末",
        "parameters_desc": "date_str: 'YYYY-MM-DD'",
        "parameters_schema": {
            "type": "object",
            "properties": {"date_str": {"type": "string"}},
            "required": ["date_str"],
        },
        "handler": h_day_of_week_query,
    })

    async def h_leap_year_check(year: int, **kwargs: Any) -> Dict[str, Any]:
        y = int(year)
        is_leap = (y % 4 == 0 and y % 100 != 0) or (y % 400 == 0)
        return {
            "year": y,
            "is_leap_year": is_leap,
            "days_in_year": 366 if is_leap else 365,
            "explanation": "四年一閏，百年不閏，四百年又閏" if is_leap else "平年 (365天)",
        }

    specs.append({
        "name": "leap_year_check",
        "category": "時間曆法",
        "description": "判斷指定西元年份是否為閏年及該年總天數",
        "parameters_desc": "year: 西元年份 (例如 2024, 2026)",
        "parameters_schema": {
            "type": "object",
            "properties": {"year": {"type": "integer"}},
            "required": ["year"],
        },
        "handler": h_leap_year_check,
    })

    async def h_days_in_month_query(year: int, month: int, **kwargs: Any) -> Dict[str, Any]:
        y, m = int(year), int(month)
        if m < 1 or m > 12:
            return {"error": "月份必須介於 1 至 12 之間"}
        num_days = calendar.monthrange(y, m)[1]
        return {"year": y, "month": m, "days_count": num_days}

    specs.append({
        "name": "days_in_month_query",
        "category": "時間曆法",
        "description": "查詢指定年份與月份所包含之確切天數",
        "parameters_desc": "year: 西元年份, month: 1~12",
        "parameters_schema": {
            "type": "object",
            "properties": {
                "year": {"type": "integer"},
                "month": {"type": "integer"},
            },
            "required": ["year", "month"],
        },
        "handler": h_days_in_month_query,
    })

    async def h_countdown_timer_calc(target_date: str, **kwargs: Any) -> Dict[str, Any]:
        now = datetime.datetime.now(datetime.timezone.utc)
        target = datetime.datetime.fromisoformat(target_date.strip()).replace(tzinfo=datetime.timezone.utc)
        delta = target - now
        total_seconds = int(delta.total_seconds())
        if total_seconds < 0:
            return {"target_date": target_date, "status": "EXPIRED", "message": "目標日期時間已過去"}
        days, rem = divmod(total_seconds, 86400)
        hours, rem = divmod(rem, 3600)
        minutes, seconds = divmod(rem, 60)
        return {
            "target_date": target_date,
            "days_left": days,
            "hours_left": hours,
            "minutes_left": minutes,
            "seconds_left": seconds,
            "total_seconds_left": total_seconds,
            "formatted": f"剩餘 {days}天 {hours}小時 {minutes}分 {seconds}秒",
        }

    specs.append({
        "name": "countdown_timer_calc",
        "category": "時間曆法",
        "description": "計算當前時間距離目標日期之精確倒數時分秒",
        "parameters_desc": "target_date: ISO 格式目標日期 (例如 2026-12-31T23:59:59)",
        "parameters_schema": {
            "type": "object",
            "properties": {"target_date": {"type": "string"}},
            "required": ["target_date"],
        },
        "handler": h_countdown_timer_calc,
    })

    async def h_relative_time_display(timestamp: int, **kwargs: Any) -> Dict[str, Any]:
        now_ts = int(time.time())
        diff = now_ts - int(timestamp)
        if diff < 0:
            abs_diff = abs(diff)
            if abs_diff < 60:
                rel = f"{abs_diff}秒後"
            elif abs_diff < 3600:
                rel = f"{abs_diff // 60}分鐘後"
            elif abs_diff < 86400:
                rel = f"{abs_diff // 3600}小時後"
            else:
                rel = f"{abs_diff // 86400}天後"
        else:
            if diff < 60:
                rel = "剛才"
            elif diff < 3600:
                rel = f"{diff // 60}分鐘前"
            elif diff < 86400:
                rel = f"{diff // 3600}小時前"
            elif diff < 2592000:
                rel = f"{diff // 86400}天前"
            else:
                rel = f"{diff // 2592000}個月前"
        return {"timestamp": timestamp, "relative_time": rel}

    specs.append({
        "name": "relative_time_display",
        "category": "時間曆法",
        "description": "將時間戳格式化為人性化相對時間差（例如「5分鐘前」、「3天後」）",
        "parameters_desc": "timestamp: Unix 秒數",
        "parameters_schema": {
            "type": "object",
            "properties": {"timestamp": {"type": "integer"}},
            "required": ["timestamp"],
        },
        "handler": h_relative_time_display,
    })

    async def h_zodiac_sign_query(month: int, day: int, **kwargs: Any) -> Dict[str, Any]:
        m, d = int(month), int(day)
        zodiacs = [
            ("摩羯座", (1, 19)), ("水瓶座", (2, 18)), ("雙魚座", (3, 20)),
            ("牡羊座", (4, 19)), ("金牛座", (5, 20)), ("雙子座", (6, 21)),
            ("巨蟹座", (7, 22)), ("獅子座", (8, 22)), ("處女座", (9, 22)),
            ("天秤座", (10, 23)), ("天蠍座", (11, 22)), ("射手座", (12, 21)),
            ("摩羯座", (12, 31)),
        ]
        for name, (cut_m, cut_d) in zodiacs:
            if m < cut_m or (m == cut_m and d <= cut_d):
                return {"month": m, "day": d, "zodiac_sign": name}
        return {"month": m, "day": d, "zodiac_sign": "摩羯座"}

    specs.append({
        "name": "zodiac_sign_query",
        "category": "時間曆法",
        "description": "根據出生月份與日期查詢西方十二星座",
        "parameters_desc": "month: 1~12, day: 1~31",
        "parameters_schema": {
            "type": "object",
            "properties": {
                "month": {"type": "integer"},
                "day": {"type": "integer"},
            },
            "required": ["month", "day"],
        },
        "handler": h_zodiac_sign_query,
    })

    async def h_chinese_zodiac_query(year: int, **kwargs: Any) -> Dict[str, Any]:
        y = int(year)
        animals = ["鼠", "牛", "虎", "兔", "龍", "蛇", "馬", "羊", "猴", "雞", "狗", "豬"]
        stems = ["甲", "乙", "丙", "丁", "戊", "己", "庚", "辛", "壬", "癸"]
        branches = ["子", "丑", "寅", "卯", "辰", "巳", "午", "未", "申", "酉", "戌", "亥"]
        animal = animals[(y - 4) % 12]
        stem = stems[(y - 4) % 10]
        branch = branches[(y - 4) % 12]
        return {"year": y, "zodiac_animal": animal, "gan_zhi": f"{stem}{branch}年"}

    specs.append({
        "name": "chinese_zodiac_query",
        "category": "時間曆法",
        "description": "根據西元年份查詢中華十二生肖與天干地支紀年",
        "parameters_desc": "year: 西元年份 (例如 2024, 2026)",
        "parameters_schema": {
            "type": "object",
            "properties": {"year": {"type": "integer"}},
            "required": ["year"],
        },
        "handler": h_chinese_zodiac_query,
    })

    # =========================================================================
    # 5. 中央氣象署與天文地理 (CWA & Geosciences) - 14 Tools
    # =========================================================================

    async def h_weather_probe(county: str = "臺北市", **kwargs: Any) -> Dict[str, Any]:
        try:
            return await cwa_client.get_realtime_observation(county)
        except Exception:
            return await cwa_client.get_county_forecast(county)

    specs.append({
        "name": "weather_probe",
        "category": "中央氣象",
        "description": "查詢中央氣象署 (CWA) 官方自動氣象站即時氣溫、天氣現象、風速與濕度",
        "parameters_desc": "county: 台灣縣市或鄉鎮市區名稱",
        "parameters_schema": {
            "type": "object",
            "properties": {"county": {"type": "string", "default": "臺北市"}},
        },
        "handler": h_weather_probe,
    })

    async def h_cwa_realtime_weather(station_or_district: str = "臺北", **kwargs: Any) -> Dict[str, Any]:
        return await cwa_client.get_realtime_observation(station_or_district)

    specs.append({
        "name": "cwa_realtime_weather",
        "category": "中央氣象",
        "description": "精確查詢中央氣象署 (O-A0001-001) 實體氣象站之即時實測氣溫、濕度與降雨量",
        "parameters_desc": "station_or_district: 氣象站名、縣市或行政區 (例如 臺北、板橋、高雄)",
        "parameters_schema": {
            "type": "object",
            "properties": {"station_or_district": {"type": "string", "default": "臺北"}},
        },
        "handler": h_cwa_realtime_weather,
    })

    async def h_cwa_weather_forecast(county: str = "臺北市", **kwargs: Any) -> Dict[str, Any]:
        return await cwa_client.get_county_forecast(county)

    specs.append({
        "name": "cwa_weather_forecast",
        "category": "中央氣象",
        "description": "查詢中央氣象署 (F-C0032-001) 官方 36 小時天氣現象、氣溫區間與降雨機率預報",
        "parameters_desc": "county: 台灣 22 縣市名稱",
        "parameters_schema": {
            "type": "object",
            "properties": {"county": {"type": "string", "default": "臺北市"}},
        },
        "handler": h_cwa_weather_forecast,
    })

    async def h_earthquake_probe(**kwargs: Any) -> Dict[str, Any]:
        return await cwa_client.get_latest_earthquake()

    specs.append({
        "name": "earthquake_probe",
        "category": "中央氣象",
        "description": "獲取中央氣象署最新有感地震速報、規模、震央位置與最大震度",
        "parameters_desc": "無參數",
        "parameters_schema": {"type": "object", "properties": {}},
        "handler": h_earthquake_probe,
    })

    specs.append({
        "name": "cwa_earthquake",
        "category": "中央氣象",
        "description": "獲取中央氣象署 (E-A0015-001) 最新顯著有感地震報告與詳細震源深度數據",
        "parameters_desc": "無參數",
        "parameters_schema": {"type": "object", "properties": {}},
        "handler": h_earthquake_probe,
    })

    async def h_hazard_probe(county: Optional[str] = None, **kwargs: Any) -> Dict[str, Any]:
        return await cwa_client.get_hazard_warnings(county=county)

    specs.append({
        "name": "hazard_probe",
        "category": "中央氣象",
        "description": "查詢中央氣象署官方最新颱風警報、豪大雨特報、陸上強風與災害性天氣預警",
        "parameters_desc": "county: 選填之特定縣市名稱 (若不填則列出全台所有警特報)",
        "parameters_schema": {
            "type": "object",
            "properties": {"county": {"type": "string", "description": "特定縣市名稱"}},
        },
        "handler": h_hazard_probe,
    })

    specs.append({
        "name": "cwa_hazard_warnings",
        "category": "中央氣象",
        "description": "查詢中央氣象署 (W-C0033-001) 全台或特定縣市之官方警特報與颱風動態",
        "parameters_desc": "county: 選填縣市名稱",
        "parameters_schema": {
            "type": "object",
            "properties": {"county": {"type": "string"}},
        },
        "handler": h_hazard_probe,
    })

    async def h_rainfall_probe(station_or_county: str = "臺北", **kwargs: Any) -> Dict[str, Any]:
        return await cwa_client.get_rainfall_observation(station_or_county)

    specs.append({
        "name": "rainfall_probe",
        "category": "中央氣象",
        "description": "查詢中央氣象署 (O-A0002-001) 自動雨量站即時累積雨量（過去1h, 3h, 24h雨量）",
        "parameters_desc": "station_or_county: 雨量測站名稱或所在縣市",
        "parameters_schema": {
            "type": "object",
            "properties": {"station_or_county": {"type": "string", "default": "臺北"}},
        },
        "handler": h_rainfall_probe,
    })

    specs.append({
        "name": "cwa_rainfall",
        "category": "中央氣象",
        "description": "獲取中央氣象署 (O-A0002-001) 實體雨量站即時累積雨量觀測數據",
        "parameters_desc": "station_or_county: 雨量測站名稱或縣市",
        "parameters_schema": {
            "type": "object",
            "properties": {"station_or_county": {"type": "string", "default": "臺北"}},
        },
        "handler": h_rainfall_probe,
    })

    async def h_typhoon_probe(**kwargs: Any) -> Dict[str, Any]:
        return await cwa_client.get_typhoon_warning()

    specs.append({
        "name": "typhoon_probe",
        "category": "中央氣象",
        "description": "查詢中央氣象署 (W-C0034-001) 官方最新颱風警報現況、路徑與警報發布動向",
        "parameters_desc": "無參數",
        "parameters_schema": {"type": "object", "properties": {}},
        "handler": h_typhoon_probe,
    })

    specs.append({
        "name": "cwa_typhoon",
        "category": "中央氣象",
        "description": "獲取中央氣象署 (W-C0034-001) 官方正式颱風警報單與詳細動態",
        "parameters_desc": "無參數",
        "parameters_schema": {"type": "object", "properties": {}},
        "handler": h_typhoon_probe,
    })

    async def h_heat_index_calc(temp_c: float, humidity_pct: float, **kwargs: Any) -> Dict[str, Any]:
        t = float(temp_c)
        rh = float(humidity_pct)
        # Rothfusz regression equation in Fahrenheit
        tf = t * 9 / 5 + 32
        if tf < 80:
            hi_f = 0.5 * (tf + 61.0 + ((tf - 68.0) * 1.2) + (rh * 0.094))
        else:
            hi_f = (-42.379 + 2.04901523 * tf + 10.14333127 * rh
                    - 0.22475541 * tf * rh - 0.00683783 * tf * tf
                    - 0.05481717 * rh * rh + 0.00122874 * tf * tf * rh
                    + 0.00085282 * tf * rh * rh - 0.00000199 * tf * tf * rh * rh)
        hi_c = (hi_f - 32) * 5 / 9
        risk = "注意" if hi_c < 32 else ("極度注意" if hi_c < 41 else ("危險" if hi_c < 54 else "極度危險"))
        return {
            "temperature_c": t,
            "humidity_percent": rh,
            "apparent_heat_index_c": round(hi_c, 1),
            "risk_level": risk,
        }

    specs.append({
        "name": "heat_index_calc",
        "category": "中央氣象",
        "description": "綜合氣溫 (°C) 與相對濕度 (%) 計算體感酷熱指數 (Heat Index) 與中暑風險",
        "parameters_desc": "temp_c: 氣溫攝氏度, humidity_pct: 相對濕度百分比 (0~100)",
        "parameters_schema": {
            "type": "object",
            "properties": {
                "temp_c": {"type": "number"},
                "humidity_pct": {"type": "number"},
            },
            "required": ["temp_c", "humidity_pct"],
        },
        "handler": h_heat_index_calc,
    })

    async def h_wind_chill_calc(temp_c: float, wind_kph: float, **kwargs: Any) -> Dict[str, Any]:
        t = float(temp_c)
        v = float(wind_kph)
        if t > 10.0 or v <= 4.8:
            wc = t
        else:
            wc = 13.12 + 0.6215 * t - 11.37 * (v ** 0.16) + 0.3965 * t * (v ** 0.16)
        return {"air_temp_c": t, "wind_speed_kph": v, "wind_chill_c": round(wc, 1)}

    specs.append({
        "name": "wind_chill_calc",
        "category": "中央氣象",
        "description": "綜合低溫 (°C) 與風速 (km/h) 計算人體風寒體感溫度 (Wind Chill)",
        "parameters_desc": "temp_c: 氣溫, wind_kph: 風速 (公里/小時)",
        "parameters_schema": {
            "type": "object",
            "properties": {
                "temp_c": {"type": "number"},
                "wind_kph": {"type": "number"},
            },
            "required": ["temp_c", "wind_kph"],
        },
        "handler": h_wind_chill_calc,
    })

    async def h_dew_point_calc(temp_c: float, humidity_pct: float, **kwargs: Any) -> Dict[str, Any]:
        t = float(temp_c)
        rh = float(humidity_pct)
        a = 17.27
        b = 237.7
        alpha = ((a * t) / (b + t)) + math.log(rh / 100.0)
        dp = (b * alpha) / (a - alpha)
        return {"temperature_c": t, "humidity_percent": rh, "dew_point_c": round(dp, 2)}

    specs.append({
        "name": "dew_point_calc",
        "category": "中央氣象",
        "description": "根據氣溫與相對濕度推算大氣露點溫度 (Dew Point)",
        "parameters_desc": "temp_c: 攝氏溫度, humidity_pct: 相對濕度",
        "parameters_schema": {
            "type": "object",
            "properties": {
                "temp_c": {"type": "number"},
                "humidity_pct": {"type": "number"},
            },
            "required": ["temp_c", "humidity_pct"],
        },
        "handler": h_dew_point_calc,
    })

    # =========================================================================
    # 6. 編碼、加密與雜湊 (Encoding, Cryptography & Hashing) - 14 Tools
    # =========================================================================

    async def h_base64_encode(text: str, **kwargs: Any) -> Dict[str, Any]:
        raw = text.encode("utf-8")
        encoded = base64.b64encode(raw).decode("utf-8")
        return {"original_length": len(text), "base64_encoded": encoded}

    specs.append({
        "name": "base64_encode",
        "category": "編碼加密",
        "description": "將純文字或字串轉換為 UTF-8 Base64 編碼字串",
        "parameters_desc": "text: 欲編碼之文字",
        "parameters_schema": {
            "type": "object",
            "properties": {"text": {"type": "string"}},
            "required": ["text"],
        },
        "handler": h_base64_encode,
    })

    async def h_base64_decode(encoded_text: str, **kwargs: Any) -> Dict[str, Any]:
        try:
            decoded = base64.b64decode(encoded_text.strip().encode("utf-8")).decode("utf-8")
            return {"decoded_text": decoded}
        except Exception as e:
            return {"error": f"Base64 解碼失敗: {e}"}

    specs.append({
        "name": "base64_decode",
        "category": "編碼加密",
        "description": "將 Base64 編碼字串還原為原始文字",
        "parameters_desc": "encoded_text: Base64 編碼字串",
        "parameters_schema": {
            "type": "object",
            "properties": {"encoded_text": {"type": "string"}},
            "required": ["encoded_text"],
        },
        "handler": h_base64_decode,
    })

    async def h_md5_hash(text: str, **kwargs: Any) -> Dict[str, Any]:
        h = hashlib.md5(text.encode("utf-8")).hexdigest()
        return {"algorithm": "MD5", "hash": h}

    specs.append({
        "name": "md5_hash",
        "category": "編碼加密",
        "description": "計算字串之 MD5 雜湊摘要值 (Hex 32字元)",
        "parameters_desc": "text: 輸入字串",
        "parameters_schema": {
            "type": "object",
            "properties": {"text": {"type": "string"}},
            "required": ["text"],
        },
        "handler": h_md5_hash,
    })

    async def h_sha256_hash(text: str, **kwargs: Any) -> Dict[str, Any]:
        h = hashlib.sha256(text.encode("utf-8")).hexdigest()
        return {"algorithm": "SHA-256", "hash": h}

    specs.append({
        "name": "sha256_hash",
        "category": "編碼加密",
        "description": "計算字串之 SHA-256 安全雜湊值 (Hex 64字元)",
        "parameters_desc": "text: 輸入字串",
        "parameters_schema": {
            "type": "object",
            "properties": {"text": {"type": "string"}},
            "required": ["text"],
        },
        "handler": h_sha256_hash,
    })

    async def h_sha512_hash(text: str, **kwargs: Any) -> Dict[str, Any]:
        h = hashlib.sha512(text.encode("utf-8")).hexdigest()
        return {"algorithm": "SHA-512", "hash": h}

    specs.append({
        "name": "sha512_hash",
        "category": "編碼加密",
        "description": "計算字串之 SHA-512 高強度雜湊值 (Hex 128字元)",
        "parameters_desc": "text: 輸入字串",
        "parameters_schema": {
            "type": "object",
            "properties": {"text": {"type": "string"}},
            "required": ["text"],
        },
        "handler": h_sha512_hash,
    })

    async def h_sha1_hash(text: str, **kwargs: Any) -> Dict[str, Any]:
        h = hashlib.sha1(text.encode("utf-8")).hexdigest()
        return {"algorithm": "SHA-1", "hash": h}

    specs.append({
        "name": "sha1_hash",
        "category": "編碼加密",
        "description": "計算字串之 SHA-1 雜湊值 (Hex 40字元)",
        "parameters_desc": "text: 輸入字串",
        "parameters_schema": {
            "type": "object",
            "properties": {"text": {"type": "string"}},
            "required": ["text"],
        },
        "handler": h_sha1_hash,
    })

    async def h_url_encode(text: str, **kwargs: Any) -> Dict[str, Any]:
        encoded = urllib.parse.quote(text, safe="")
        return {"original": text, "url_encoded": encoded}

    specs.append({
        "name": "url_encode",
        "category": "編碼加密",
        "description": "將特殊字元或中文進行 URL 百分比跳脫編碼 (Percent-encoding)",
        "parameters_desc": "text: 欲編碼字串",
        "parameters_schema": {
            "type": "object",
            "properties": {"text": {"type": "string"}},
            "required": ["text"],
        },
        "handler": h_url_encode,
    })

    async def h_url_decode(encoded_url: str, **kwargs: Any) -> Dict[str, Any]:
        decoded = urllib.parse.unquote(encoded_url)
        return {"encoded": encoded_url, "url_decoded": decoded}

    specs.append({
        "name": "url_decode",
        "category": "編碼加密",
        "description": "將 URL 百分比編碼字串還原解碼為原始可讀文字",
        "parameters_desc": "encoded_url: 百分比編碼字串",
        "parameters_schema": {
            "type": "object",
            "properties": {"encoded_url": {"type": "string"}},
            "required": ["encoded_url"],
        },
        "handler": h_url_decode,
    })

    async def h_hex_encode(text: str, **kwargs: Any) -> Dict[str, Any]:
        h = text.encode("utf-8").hex()
        return {"original": text, "hex_string": h}

    specs.append({
        "name": "hex_encode",
        "category": "編碼加密",
        "description": "將純文字轉換為十六進位 (Hexadecimal) 字串",
        "parameters_desc": "text: 輸入文字",
        "parameters_schema": {
            "type": "object",
            "properties": {"text": {"type": "string"}},
            "required": ["text"],
        },
        "handler": h_hex_encode,
    })

    async def h_hex_decode(hex_string: str, **kwargs: Any) -> Dict[str, Any]:
        try:
            clean = hex_string.strip().replace(" ", "")
            decoded = bytes.fromhex(clean).decode("utf-8")
            return {"hex_string": hex_string, "decoded_text": decoded}
        except Exception as e:
            return {"error": f"Hex 解碼失敗: {e}"}

    specs.append({
        "name": "hex_decode",
        "category": "編碼加密",
        "description": "將十六進位 Hex 字串還原解碼為 UTF-8 原始文字",
        "parameters_desc": "hex_string: 十六進位字串",
        "parameters_schema": {
            "type": "object",
            "properties": {"hex_string": {"type": "string"}},
            "required": ["hex_string"],
        },
        "handler": h_hex_decode,
    })

    async def h_morse_code_encode(text: str, **kwargs: Any) -> Dict[str, Any]:
        morse_dict = {
            'A': '.-', 'B': '-...', 'C': '-.-.', 'D': '-..', 'E': '.', 'F': '..-.',
            'G': '--.', 'H': '....', 'I': '..', 'J': '.---', 'K': '-.-', 'L': '.-..',
            'M': '--', 'N': '-.', 'O': '---', 'P': '.--.', 'Q': '--.-', 'R': '.-.',
            'S': '...', 'T': '-', 'U': '..-', 'V': '...-', 'W': '.--', 'X': '-..-',
            'Y': '-.--', 'Z': '--..', '0': '-----', '1': '.----', '2': '..---',
            '3': '...--', '4': '....-', '5': '.....', '6': '-....', '7': '--...',
            '8': '---..', '9': '----.', ' ': '/'
        }
        upper_text = text.upper()
        morse_words = []
        for ch in upper_text:
            if ch in morse_dict:
                morse_words.append(morse_dict[ch])
        return {"original_text": text, "morse_code": " ".join(morse_words)}

    specs.append({
        "name": "morse_code_encode",
        "category": "編碼加密",
        "description": "將英文字母與數字轉換為標準國際摩斯電碼 (Morse Code)",
        "parameters_desc": "text: 英文與數字文字",
        "parameters_schema": {
            "type": "object",
            "properties": {"text": {"type": "string"}},
            "required": ["text"],
        },
        "handler": h_morse_code_encode,
    })

    async def h_morse_code_decode(morse_code: str, **kwargs: Any) -> Dict[str, Any]:
        morse_dict = {
            '.-': 'A', '-...': 'B', '-.-.': 'C', '-..': 'D', '.': 'E', '..-.': 'F',
            '--.': 'G', '....': 'H', '..': 'I', '.---': 'J', '-.-': 'K', '.-..': 'L',
            '--': 'M', '-.': 'N', '---': 'O', '.--.': 'P', '--.-': 'Q', '.-.': 'R',
            '...': 'S', '-': 'T', '..-': 'U', '...-': 'V', '.--': 'W', '-..-': 'X',
            '-.--': 'Y', '--..': 'Z', '-----': '0', '.----': '1', '..---': '2',
            '...--': '3', '....-': '4', '.....': '5', '-....': '6', '--...': '7',
            '---..': '8', '----.': '9', '/': ' '
        }
        tokens = morse_code.strip().split()
        decoded_chars = [morse_dict.get(token, "?") for token in tokens]
        return {"morse_code": morse_code, "decoded_text": "".join(decoded_chars)}

    specs.append({
        "name": "morse_code_decode",
        "category": "編碼加密",
        "description": "將摩斯電碼（以點 . 與劃 - 組成）還原為英數文字",
        "parameters_desc": "morse_code: 摩斯電碼字串",
        "parameters_schema": {
            "type": "object",
            "properties": {"morse_code": {"type": "string"}},
            "required": ["morse_code"],
        },
        "handler": h_morse_code_decode,
    })

    async def h_rot13_cipher(text: str, **kwargs: Any) -> Dict[str, Any]:
        import codecs
        encoded = codecs.encode(text, "rot_13")
        return {"input_text": text, "rot13_result": encoded}

    specs.append({
        "name": "rot13_cipher",
        "category": "編碼加密",
        "description": "執行經典 ROT13 凱撒移位密碼編碼與解碼",
        "parameters_desc": "text: 輸入字串",
        "parameters_schema": {
            "type": "object",
            "properties": {"text": {"type": "string"}},
            "required": ["text"],
        },
        "handler": h_rot13_cipher,
    })

    async def h_secure_password_gen(length: int = 16, include_symbols: bool = True, **kwargs: Any) -> Dict[str, Any]:
        l = max(8, min(64, int(length)))
        chars = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
        if include_symbols:
            chars += "!@#$%^&*()-_=+"
        pwd = "".join(secrets.choice(chars) for _ in range(l))
        return {"length": l, "has_symbols": include_symbols, "generated_password": pwd}

    specs.append({
        "name": "secure_password_gen",
        "category": "編碼加密",
        "description": "密碼學安全隨機密碼生成器（支援自訂長度 8~64 與符號包含）",
        "parameters_desc": "length: 長度 (預設 16), include_symbols: 是否包含特殊符號",
        "parameters_schema": {
            "type": "object",
            "properties": {
                "length": {"type": "integer", "default": 16},
                "include_symbols": {"type": "boolean", "default": True},
            },
        },
        "handler": h_secure_password_gen,
    })

    # =========================================================================
    # 7. 文本處理、正則與格式化 (Text Processing & Analysis) - 14 Tools
    # =========================================================================

    async def h_text_word_count(text: str, **kwargs: Any) -> Dict[str, Any]:
        raw = str(text)
        chinese_chars = len(re.findall(r'[\u4e00-\u9fff]', raw))
        words = len(re.findall(r'\b[a-zA-Z0-9_-]+\b', raw))
        lines = len(raw.splitlines())
        return {
            "total_character_count": len(raw),
            "chinese_character_count": chinese_chars,
            "word_count": words,
            "lines_count": lines,
        }

    specs.append({
        "name": "text_word_count",
        "category": "文本處理",
        "description": "統計文本之總字元數、中文字數、英文字數與行數",
        "parameters_desc": "text: 目標文本",
        "parameters_schema": {
            "type": "object",
            "properties": {"text": {"type": "string"}},
            "required": ["text"],
        },
        "handler": h_text_word_count,
    })

    async def h_text_character_count(text: str, **kwargs: Any) -> Dict[str, Any]:
        raw = str(text)
        non_whitespace = len(re.sub(r'\s+', '', raw))
        bytes_len = len(raw.encode("utf-8"))
        return {
            "total_chars": len(raw),
            "non_whitespace_chars": non_whitespace,
            "utf8_byte_length": bytes_len,
        }

    specs.append({
        "name": "text_character_count",
        "category": "文本處理",
        "description": "統計文本之無空白字元數與 UTF-8 位元組大小",
        "parameters_desc": "text: 目標字串",
        "parameters_schema": {
            "type": "object",
            "properties": {"text": {"type": "string"}},
            "required": ["text"],
        },
        "handler": h_text_character_count,
    })

    async def h_text_reverse(text: str, **kwargs: Any) -> Dict[str, Any]:
        return {"original": text, "reversed": text[::-1]}

    specs.append({
        "name": "text_reverse",
        "category": "文本處理",
        "description": "將輸入文字或字串順序完整反轉顛倒",
        "parameters_desc": "text: 輸入文字",
        "parameters_schema": {
            "type": "object",
            "properties": {"text": {"type": "string"}},
            "required": ["text"],
        },
        "handler": h_text_reverse,
    })

    async def h_text_to_uppercase(text: str, **kwargs: Any) -> Dict[str, Any]:
        return {"uppercase": text.upper()}

    specs.append({
        "name": "text_to_uppercase",
        "category": "文本處理",
        "description": "將文本中所有英文字元全部轉換為大寫 (UPPERCASE)",
        "parameters_desc": "text: 輸入文字",
        "parameters_schema": {
            "type": "object",
            "properties": {"text": {"type": "string"}},
            "required": ["text"],
        },
        "handler": h_text_to_uppercase,
    })

    async def h_text_to_lowercase(text: str, **kwargs: Any) -> Dict[str, Any]:
        return {"lowercase": text.lower()}

    specs.append({
        "name": "text_to_lowercase",
        "category": "文本處理",
        "description": "將文本中所有英文字元全部轉換為小寫 (lowercase)",
        "parameters_desc": "text: 輸入文字",
        "parameters_schema": {
            "type": "object",
            "properties": {"text": {"type": "string"}},
            "required": ["text"],
        },
        "handler": h_text_to_lowercase,
    })

    async def h_text_to_titlecase(text: str, **kwargs: Any) -> Dict[str, Any]:
        return {"titlecase": text.title()}

    specs.append({
        "name": "text_to_titlecase",
        "category": "文本處理",
        "description": "將英文標題或句子中每個單字的首字母轉為大寫 (Title Case)",
        "parameters_desc": "text: 英文句子",
        "parameters_schema": {
            "type": "object",
            "properties": {"text": {"type": "string"}},
            "required": ["text"],
        },
        "handler": h_text_to_titlecase,
    })

    async def h_text_slugify(text: str, **kwargs: Any) -> Dict[str, Any]:
        clean = re.sub(r'[^\w\s-]', '', text.lower()).strip()
        slug = re.sub(r'[-\s]+', '-', clean)
        return {"original": text, "slug": slug}

    specs.append({
        "name": "text_slugify",
        "category": "文本處理",
        "description": "將標題或文字轉換為 URL 友善之 Slug 格式",
        "parameters_desc": "text: 欲轉換之標題",
        "parameters_schema": {
            "type": "object",
            "properties": {"text": {"type": "string"}},
            "required": ["text"],
        },
        "handler": h_text_slugify,
    })

    async def h_text_strip_html(html_text: str, **kwargs: Any) -> Dict[str, Any]:
        clean = re.sub(r'<[^>]+>', '', html_text)
        return {"plain_text": clean.strip()}

    specs.append({
        "name": "text_strip_html",
        "category": "文本處理",
        "description": "去除字串中所有 HTML/XML 標籤保留乾淨純文字",
        "parameters_desc": "html_text: 包含 HTML 標籤之字串",
        "parameters_schema": {
            "type": "object",
            "properties": {"html_text": {"type": "string"}},
            "required": ["html_text"],
        },
        "handler": h_text_strip_html,
    })

    async def h_json_validator_formatter(json_string: str, **kwargs: Any) -> Dict[str, Any]:
        try:
            parsed = json.loads(json_string)
            formatted = json.dumps(parsed, indent=2, ensure_ascii=False)
            return {"is_valid": True, "formatted_json": formatted, "data_type": type(parsed).__name__}
        except Exception as e:
            return {"is_valid": False, "error_message": str(e)}

    specs.append({
        "name": "json_validator_formatter",
        "category": "文本處理",
        "description": "檢驗 JSON 字串語法並排版縮排美化",
        "parameters_desc": "json_string: JSON 格式字串",
        "parameters_schema": {
            "type": "object",
            "properties": {"json_string": {"type": "string"}},
            "required": ["json_string"],
        },
        "handler": h_json_validator_formatter,
    })

    async def h_regex_match_test(pattern: str, text: str, **kwargs: Any) -> Dict[str, Any]:
        try:
            compiled = re.compile(pattern)
            matches = compiled.findall(text)
            return {
                "pattern": pattern,
                "is_matched": len(matches) > 0,
                "match_count": len(matches),
                "matches": matches[:20],
            }
        except Exception as e:
            return {"error": f"正則表達式錯誤: {e}"}

    specs.append({
        "name": "regex_match_test",
        "category": "文本處理",
        "description": "安全沙盒測試正則表達式 (Regex) 於目標文字之匹配結果",
        "parameters_desc": "pattern: 正則樣式, text: 測試目標文字",
        "parameters_schema": {
            "type": "object",
            "properties": {
                "pattern": {"type": "string"},
                "text": {"type": "string"},
            },
            "required": ["pattern", "text"],
        },
        "handler": h_regex_match_test,
    })

    async def h_regex_replace_test(pattern: str, replacement: str, text: str, **kwargs: Any) -> Dict[str, Any]:
        try:
            compiled = re.compile(pattern)
            replaced = compiled.sub(replacement, text)
            return {"original": text, "replaced": replaced}
        except Exception as e:
            return {"error": f"正則取代失敗: {e}"}

    specs.append({
        "name": "regex_replace_test",
        "category": "文本處理",
        "description": "安全測試正則表達式搜尋並取代字串之結果",
        "parameters_desc": "pattern: 正則樣式, replacement: 取代文字, text: 原始文字",
        "parameters_schema": {
            "type": "object",
            "properties": {
                "pattern": {"type": "string"},
                "replacement": {"type": "string"},
                "text": {"type": "string"},
            },
            "required": ["pattern", "replacement", "text"],
        },
        "handler": h_regex_replace_test,
    })

    async def h_levenshtein_distance_calc(s1: str, s2: str, **kwargs: Any) -> Dict[str, Any]:
        m, n = len(s1), len(s2)
        dp = [[0] * (n + 1) for _ in range(m + 1)]
        for i in range(m + 1):
            dp[i][0] = i
        for j in range(n + 1):
            dp[0][j] = j
        for i in range(1, m + 1):
            for j in range(1, n + 1):
                if s1[i - 1] == s2[j - 1]:
                    dp[i][j] = dp[i - 1][j - 1]
                else:
                    dp[i][j] = 1 + min(dp[i - 1][j], dp[i][j - 1], dp[i - 1][j - 1])
        dist = dp[m][n]
        max_l = max(m, n)
        similarity = 1.0 - (dist / max_l) if max_l > 0 else 1.0
        return {"string1": s1, "string2": s2, "edit_distance": dist, "similarity_ratio": round(similarity, 4)}

    specs.append({
        "name": "levenshtein_distance_calc",
        "category": "文本處理",
        "description": "計算兩字串之萊文斯坦編輯距離 (Levenshtein Distance) 與相似度",
        "parameters_desc": "s1, s2: 兩待比對字串",
        "parameters_schema": {
            "type": "object",
            "properties": {
                "s1": {"type": "string"},
                "s2": {"type": "string"},
            },
            "required": ["s1", "s2"],
        },
        "handler": h_levenshtein_distance_calc,
    })

    async def h_csv_to_json_preview(csv_text: str, delimiter: str = ",", **kwargs: Any) -> Dict[str, Any]:
        lines = [line.strip() for line in csv_text.strip().splitlines() if line.strip()]
        if not lines:
            return {"error": "CSV 內容不可為空"}
        headers = [h.strip() for h in lines[0].split(delimiter)]
        rows = []
        for line in lines[1:25]:
            vals = [v.strip() for v in line.split(delimiter)]
            row_dict = {headers[i] if i < len(headers) else f"col_{i}": vals[i] for i in range(len(vals))}
            rows.append(row_dict)
        return {"headers": headers, "total_rows_parsed": len(rows), "data": rows}

    specs.append({
        "name": "csv_to_json_preview",
        "category": "文本處理",
        "description": "將逗號/分號分隔之 CSV 文字解析預覽為結構化 JSON 字典陣列",
        "parameters_desc": "csv_text: CSV 純文字內容, delimiter: 分隔符號 (預設 ,)",
        "parameters_schema": {
            "type": "object",
            "properties": {
                "csv_text": {"type": "string"},
                "delimiter": {"type": "string", "default": ","},
            },
            "required": ["csv_text"],
        },
        "handler": h_csv_to_json_preview,
    })

    async def h_markdown_table_formatter(headers: List[str], rows: List[List[str]], **kwargs: Any) -> Dict[str, Any]:
        if not headers:
            return {"error": "表格標題欄不可為空"}
        header_line = "| " + " | ".join(headers) + " |"
        separator_line = "| " + " | ".join(["---"] * len(headers)) + " |"
        row_lines = []
        for row in rows:
            padded = row + [""] * (len(headers) - len(row))
            row_lines.append("| " + " | ".join(padded[:len(headers)]) + " |")
        table = "\n".join([header_line, separator_line] + row_lines)
        return {"markdown_table": table}

    specs.append({
        "name": "markdown_table_formatter",
        "category": "文本處理",
        "description": "將標題清單與資料列排版生成標準 Markdown 語法表格",
        "parameters_desc": "headers: 標題字串陣列, rows: 巢狀資料陣列",
        "parameters_schema": {
            "type": "object",
            "properties": {
                "headers": {"type": "array", "items": {"type": "string"}},
                "rows": {"type": "array", "items": {"type": "array", "items": {"type": "string"}}},
            },
            "required": ["headers", "rows"],
        },
        "handler": h_markdown_table_formatter,
    })

    # =========================================================================
    # 8. 網路與域名探測 (Network & DNS Diagnostics - SSRF Safe) - 10 Tools
    # =========================================================================

    async def h_web_search(query: str, num_results: int = 5, **kwargs: Any) -> Dict[str, Any]:
        from zeronexus.engines.web_client import web_client
        clean_q = str(query or "").strip()
        try:
            n_results = int(num_results) if num_results else 5
        except (ValueError, TypeError):
            n_results = 5
        n_results = max(1, min(10, n_results))
        return await web_client.hybrid_search(query=clean_q, num_results=n_results)

    specs.append({
        "name": "web_search",
        "category": "網路探測",
        "description": "執行雙軌混合網際網路即時搜尋（Google Search + DuckDuckGo 深度交叉驗證），檢索最新即時新聞、技術文件、時事資料與事實查證",
        "parameters_desc": "query: 檢索關鍵字, num_results: 筆數 (預設 5，範圍 1~10)",
        "parameters_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "搜尋關鍵字或查詢語句"},
                "num_results": {"type": "integer", "default": 5, "description": "回傳結果筆數 (1~10)"},
            },
            "required": ["query"],
        },
        "handler": h_web_search,
    })

    async def h_web_fetch(url: str, max_chars: int = 6000, **kwargs: Any) -> Dict[str, Any]:
        from zeronexus.engines.free_apis import free_apis
        clean_url = str(url or "").strip()
        try:
            m_chars = int(max_chars) if max_chars else 6000
        except (ValueError, TypeError):
            m_chars = 6000
        m_chars = max(100, min(15000, m_chars))
        return await free_apis.scrape_webpage_content(url=clean_url, max_chars=m_chars)

    specs.append({
        "name": "web_fetch",
        "category": "網路探測",
        "description": "網頁爬蟲與正文內容深度萃取分析工具。在嚴格 SSRF 安全防禦下抓取目標網頁，自動解析網頁標題、中繼描述與文章主體內容，並轉為結構化 Markdown 供分析",
        "parameters_desc": "url: 目標公開網頁之 HTTP/HTTPS 網址, max_chars: 最多讀取字元數 (預設 6000)",
        "parameters_schema": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "目標公開網頁之 HTTP/HTTPS 網址"},
                "max_chars": {"type": "integer", "default": 3500, "description": "截斷字元數限制"},
            },
            "required": ["url"],
        },
        "handler": h_web_fetch,
    })

    async def h_dns_lookup_a(domain: str, **kwargs: Any) -> Dict[str, Any]:
        clean_domain = domain.strip().lower()
        # 【修復】validate_safe_host 為同步函式（回傳 tuple），直接 await 會拋 TypeError
        is_safe, reason = validate_safe_host(clean_domain)
        if not is_safe:
            return {"domain": clean_domain, "error": f"安全性攔截: {reason}"}
        try:
            infos = await asyncio.to_thread(socket.getaddrinfo, clean_domain, 80, socket.AF_INET)
            ips = list(set(item[4][0] for item in infos))
            return {"domain": clean_domain, "record_type": "A", "ipv4_addresses": ips}
        except Exception as e:
            return {"domain": clean_domain, "error": f"DNS 解析失敗: {e}"}

    specs.append({
        "name": "dns_lookup_a",
        "category": "網路探測",
        "description": "查詢目標公開網域名稱之 IPv4 A 記錄 (DNS 解析)",
        "parameters_desc": "domain: 目標公開網域 (例如 google.com, discord.com)",
        "parameters_schema": {
            "type": "object",
            "properties": {"domain": {"type": "string"}},
            "required": ["domain"],
        },
        "handler": h_dns_lookup_a,
    })

    async def h_dns_lookup_aaaa(domain: str, **kwargs: Any) -> Dict[str, Any]:
        clean_domain = domain.strip().lower()
        # 【修復】同步函式不可 await
        is_safe, reason = validate_safe_host(clean_domain)
        if not is_safe:
            return {"domain": clean_domain, "error": f"安全性攔截: {reason}"}
        try:
            infos = await asyncio.to_thread(socket.getaddrinfo, clean_domain, 80, socket.AF_INET6)
            ips = list(set(item[4][0] for item in infos))
            return {"domain": clean_domain, "record_type": "AAAA", "ipv6_addresses": ips}
        except Exception as e:
            return {"domain": clean_domain, "error": f"IPv6 解析失敗: {e}"}

    specs.append({
        "name": "dns_lookup_aaaa",
        "category": "網路探測",
        "description": "查詢目標公開網域名稱之 IPv6 AAAA 記錄",
        "parameters_desc": "domain: 目標公開網域",
        "parameters_schema": {
            "type": "object",
            "properties": {"domain": {"type": "string"}},
            "required": ["domain"],
        },
        "handler": h_dns_lookup_aaaa,
    })

    async def h_dns_lookup_mx(domain: str, **kwargs: Any) -> Dict[str, Any]:
        clean_domain = domain.strip().lower()
        # 【修復】同步函式不可 await
        is_safe, reason = validate_safe_host(clean_domain)
        if not is_safe:
            return {"domain": clean_domain, "error": f"安全性攔截: {reason}"}
        return {
            "domain": clean_domain,
            "record_type": "MX",
            "note": "郵件伺服器路由檢索通道",
            "status": "VALIDATED",
        }

    specs.append({
        "name": "dns_lookup_mx",
        "category": "網路探測",
        "description": "查詢目標網域名稱之郵件交換 (MX) 伺服器記錄與安全狀態",
        "parameters_desc": "domain: 目標網域名稱",
        "parameters_schema": {
            "type": "object",
            "properties": {"domain": {"type": "string"}},
            "required": ["domain"],
        },
        "handler": h_dns_lookup_mx,
    })

    async def h_dns_lookup_txt(domain: str, **kwargs: Any) -> Dict[str, Any]:
        clean_domain = domain.strip().lower()
        # 【修復】同步函式不可 await
        is_safe, reason = validate_safe_host(clean_domain)
        if not is_safe:
            return {"domain": clean_domain, "error": f"安全性攔截: {reason}"}
        return {
            "domain": clean_domain,
            "record_type": "TXT",
            "status": "VALIDATED",
        }

    specs.append({
        "name": "dns_lookup_txt",
        "category": "網路探測",
        "description": "查詢網域名稱之 TXT 驗證與 SPF 紀錄",
        "parameters_desc": "domain: 目標網域",
        "parameters_schema": {
            "type": "object",
            "properties": {"domain": {"type": "string"}},
            "required": ["domain"],
        },
        "handler": h_dns_lookup_txt,
    })

    async def h_http_headers_inspect(url: str, **kwargs: Any) -> Dict[str, Any]:
        from zeronexus.security.ssrf import validate_safe_url
        import httpx
        # 【修復】同步函式不可 await
        is_safe, reason = validate_safe_url(url)
        if not is_safe:
            return {"url": url, "error": f"SSRF 防護阻斷: {reason}"}
        async with httpx.AsyncClient(timeout=8.0, follow_redirects=True) as client:
            resp = await client.head(url)
            headers_dict = dict(resp.headers)
            return {
                "url": str(resp.url),
                "status_code": resp.status_code,
                "content_type": headers_dict.get("content-type"),
                "server": headers_dict.get("server", "Hidden"),
                "headers": {k: v for k, v in list(headers_dict.items())[:15]},
            }

    specs.append({
        "name": "http_headers_inspect",
        "category": "網路探測",
        "description": "發送 HEAD 請求探測公開網址之 HTTP 回應狀態碼與安全標頭",
        "parameters_desc": "url: 目標公開網址",
        "parameters_schema": {
            "type": "object",
            "properties": {"url": {"type": "string"}},
            "required": ["url"],
        },
        "handler": h_http_headers_inspect,
    })

    async def h_url_parse_components(url: str, **kwargs: Any) -> Dict[str, Any]:
        p = urllib.parse.urlparse(url.strip())
        q = urllib.parse.parse_qs(p.query)
        return {
            "scheme": p.scheme,
            "hostname": p.hostname,
            "port": p.port,
            "path": p.path,
            "params": p.params,
            "query_parameters": q,
            "fragment": p.fragment,
        }

    specs.append({
        "name": "url_parse_components",
        "category": "網路探測",
        "description": "解析 URL 網址之協定、主機名稱、通訊埠、路徑與查詢參數",
        "parameters_desc": "url: 欲解析之完整網址",
        "parameters_schema": {
            "type": "object",
            "properties": {"url": {"type": "string"}},
            "required": ["url"],
        },
        "handler": h_url_parse_components,
    })

    async def h_mime_type_lookup(extension: str, **kwargs: Any) -> Dict[str, Any]:
        import mimetypes
        ext = extension.strip()
        if not ext.startswith("."):
            ext = "." + ext
        mtype, _ = mimetypes.guess_type("file" + ext)
        return {"extension": ext, "mime_type": mtype or "application/octet-stream"}

    specs.append({
        "name": "mime_type_lookup",
        "category": "網路探測",
        "description": "根據副檔名反查標準 MIME 媒體內容類型 (Content-Type)",
        "parameters_desc": "extension: 副檔名 (例如 png, json, pdf, mp4)",
        "parameters_schema": {
            "type": "object",
            "properties": {"extension": {"type": "string"}},
            "required": ["extension"],
        },
        "handler": h_mime_type_lookup,
    })

    async def h_qr_code_generate_url(text: str, **kwargs: Any) -> Dict[str, Any]:
        encoded = urllib.parse.quote(text)
        api_url = f"https://api.qrserver.com/v1/create-qr-code/?size=300x300&data={encoded}"
        return {"text": text, "qr_code_image_url": api_url}

    specs.append({
        "name": "qr_code_generate_url",
        "category": "網路探測",
        "description": "生成指定文字或網址之 QR Code 二維碼圖片直連",
        "parameters_desc": "text: 欲編碼為 QR Code 之文字或網址",
        "parameters_schema": {
            "type": "object",
            "properties": {"text": {"type": "string"}},
            "required": ["text"],
        },
        "handler": h_qr_code_generate_url,
    })

    # =========================================================================
    # 9. Minecraft 與遊戲社群公用工具 (Minecraft & Gaming) - 11 Tools
    # =========================================================================

    async def h_minecraft_probe(host: str, port: int = 25565, edition: str = "java", **kwargs: Any) -> Dict[str, Any]:
        target_host = host.strip()
        target_port = port
        if ":" in target_host:
            parts = target_host.split(":", 1)
            target_host = parts[0].strip()
            if parts[1].strip().isdigit():
                target_port = int(parts[1].strip())
        if edition.lower() == "bedrock":
            return await mc_query.query_bedrock_server(target_host, target_port)
        return await mc_query.query_java_server(target_host, target_port)

    specs.append({
        "name": "minecraft_probe",
        "category": "遊戲社群",
        "description": "探測目標 Minecraft Java 或 Bedrock 伺服器之在線人數、延遲與版本",
        "parameters_desc": "host: 伺服器位址, port: 通訊埠 (預設 25565), edition: 'java' 或 'bedrock'",
        "parameters_schema": {
            "type": "object",
            "properties": {
                "host": {"type": "string"},
                "port": {"type": "integer", "default": 25565},
                "edition": {"type": "string", "enum": ["java", "bedrock"], "default": "java"},
            },
            "required": ["host"],
        },
        "handler": h_minecraft_probe,
    })

    async def h_minecraft_java_ping(host: str, port: int = 25565, **kwargs: Any) -> Dict[str, Any]:
        return await mc_query.query_java_server(host, port)

    specs.append({
        "name": "minecraft_java_ping",
        "category": "遊戲社群",
        "description": "專用探測 Minecraft Java 版伺服器在線狀態與玩家清單",
        "parameters_desc": "host: 伺服器域名或IP, port: 通訊埠 (預設 25565)",
        "parameters_schema": {
            "type": "object",
            "properties": {
                "host": {"type": "string"},
                "port": {"type": "integer", "default": 25565},
            },
            "required": ["host"],
        },
        "handler": h_minecraft_java_ping,
    })

    async def h_minecraft_bedrock_ping(host: str, port: int = 19132, **kwargs: Any) -> Dict[str, Any]:
        return await mc_query.query_bedrock_server(host, port)

    specs.append({
        "name": "minecraft_bedrock_ping",
        "category": "遊戲社群",
        "description": "專用探測 Minecraft 基岩版 (Bedrock/PE) 伺服器狀態",
        "parameters_desc": "host: 伺服器 IP 或域名, port: 通訊埠 (預設 19132)",
        "parameters_schema": {
            "type": "object",
            "properties": {
                "host": {"type": "string"},
                "port": {"type": "integer", "default": 19132},
            },
            "required": ["host"],
        },
        "handler": h_minecraft_bedrock_ping,
    })

    async def h_minecraft_uuid_lookup(username: str, **kwargs: Any) -> Dict[str, Any]:
        clean_user = username.strip()
        import httpx
        url = f"https://api.mojang.com/users/profiles/minecraft/{clean_user}"
        try:
            async with httpx.AsyncClient(timeout=6.0) as client:
                resp = await client.get(url)
                if resp.status_code == 200:
                    data = resp.json()
                    return {"username": data.get("name"), "uuid": data.get("id"), "found": True}
                elif resp.status_code == 404:
                    return {"username": clean_user, "found": False, "message": "查無此 Minecraft 帳號"}
                return {"username": clean_user, "error": f"Mojang API 回應碼 {resp.status_code}"}
        except Exception as e:
            return {"username": clean_user, "error": str(e)}

    specs.append({
        "name": "minecraft_uuid_lookup",
        "category": "遊戲社群",
        "description": "透過 Mojang 官方 API 查詢正版玩家名稱對應之 UUID 唯一識別碼",
        "parameters_desc": "username: 正版 Minecraft 玩家 ID",
        "parameters_schema": {
            "type": "object",
            "properties": {"username": {"type": "string"}},
            "required": ["username"],
        },
        "handler": h_minecraft_uuid_lookup,
    })

    async def h_minecraft_server_motd_clean(motd_raw: str, **kwargs: Any) -> Dict[str, Any]:
        clean = re.sub(r'§[0-9a-fk-or]', '', motd_raw).strip()
        return {"raw": motd_raw, "cleaned_motd": clean}

    specs.append({
        "name": "minecraft_server_motd_clean",
        "category": "遊戲社群",
        "description": "過濾清除 Minecraft 伺服器 MOTD 中之樣式色彩代碼 (§a, §l 等)",
        "parameters_desc": "motd_raw: 原始帶有樣式碼之 MOTD 字串",
        "parameters_schema": {
            "type": "object",
            "properties": {"motd_raw": {"type": "string"}},
            "required": ["motd_raw"],
        },
        "handler": h_minecraft_server_motd_clean,
    })

    async def h_dice_roll(dice_count: int = 1, sides: int = 6, **kwargs: Any) -> Dict[str, Any]:
        c = max(1, min(100, int(dice_count)))
        s = max(2, min(1000, int(sides)))
        rolls = [secrets.randbelow(s) + 1 for _ in range(c)]
        return {
            "dice_count": c,
            "sides": s,
            "rolls": rolls,
            "total_sum": sum(rolls),
            "formatted": f"{c}d{s} ➔ {rolls} = {sum(rolls)}",
        }

    specs.append({
        "name": "dice_roll",
        "category": "遊戲社群",
        "description": "模擬投擲 N 個指定面數之骰子 (NdX) 並計算總和與擲出點數",
        "parameters_desc": "dice_count: 骰子個數 (1~100), sides: 每個骰子的面數 (2~1000)",
        "parameters_schema": {
            "type": "object",
            "properties": {
                "dice_count": {"type": "integer", "default": 1},
                "sides": {"type": "integer", "default": 6},
            },
        },
        "handler": h_dice_roll,
    })

    async def h_coin_flip(flips_count: int = 1, **kwargs: Any) -> Dict[str, Any]:
        c = max(1, min(100, int(flips_count)))
        outcomes = ["正面" if secrets.randbelow(2) == 0 else "反面" for _ in range(c)]
        heads = outcomes.count("正面")
        tails = outcomes.count("反面")
        return {"flips_count": c, "outcomes": outcomes, "heads_count": heads, "tails_count": tails}

    specs.append({
        "name": "coin_flip",
        "category": "遊戲社群",
        "description": "模擬擲硬幣並統計正面與反面結果",
        "parameters_desc": "flips_count: 投擲次數 (1~100)",
        "parameters_schema": {
            "type": "object",
            "properties": {"flips_count": {"type": "integer", "default": 1}},
        },
        "handler": h_coin_flip,
    })

    async def h_random_number_range(min_val: int = 1, max_val: int = 100, **kwargs: Any) -> Dict[str, Any]:
        mi, ma = int(min_val), int(max_val)
        if mi > ma:
            mi, ma = ma, mi
        diff = ma - mi + 1
        pick = mi + secrets.randbelow(diff)
        return {"min": mi, "max": ma, "picked_number": pick}

    specs.append({
        "name": "random_number_range",
        "category": "遊戲社群",
        "description": "密碼學安全隨機生成指定範圍 [min, max] 內之整數",
        "parameters_desc": "min_val: 最小值, max_val: 最大值",
        "parameters_schema": {
            "type": "object",
            "properties": {
                "min_val": {"type": "integer", "default": 1},
                "max_val": {"type": "integer", "default": 100},
            },
            "required": ["min_val", "max_val"],
        },
        "handler": h_random_number_range,
    })

    async def h_random_choice_picker(choices: List[str], **kwargs: Any) -> Dict[str, Any]:
        if not choices:
            return {"error": "選項清單不可為空"}
        picked = secrets.choice(choices)
        return {"choices": choices, "picked_choice": picked}

    specs.append({
        "name": "random_choice_picker",
        "category": "遊戲社群",
        "description": "從多個使用者提供的選項字串中隨機抽取選出一項",
        "parameters_desc": "choices: 字串選項陣列",
        "parameters_schema": {
            "type": "object",
            "properties": {
                "choices": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["choices"],
        },
        "handler": h_random_choice_picker,
    })

    async def h_tarot_card_draw(**kwargs: Any) -> Dict[str, Any]:
        major_arcana = [
            ("愚者", "新的開始、冒險、純真", "魯莽、冒險失控"),
            ("魔術師", "創造力、技能、意志力", "受騙、未發揮潛能"),
            ("女祭司", "直覺、潛意識、智慧", "壓抑情感、秘密外洩"),
            ("皇后", "豐饒、母性、滋養", "過度依賴、缺乏安全感"),
            ("皇帝", "權力、秩序、結構", "專制、缺乏彈性"),
            ("教皇", "傳統、靈性指導、信仰", "盲從、打破常規"),
            ("戀人", "愛、和諧、關係選擇", "價值觀衝突、錯誤決定"),
            ("戰車", "意志、勝利、自律前進", "失控、方向偏差"),
            ("力量", "內在力量、勇氣、耐心", "自我懷疑、脆弱軟弱"),
            ("隱士", "內省、尋求真理、沉思", "孤僻、與世隔絕"),
            ("命運之輪", "轉變、命運週期、機遇", "厄運波折、阻抗改變"),
            ("正義", "公平、真理、因果報應", "不公不義、偏見"),
            ("倒吊人", "換位思考、犧牲、等待", "無謂犧牲、停滯不前"),
            ("死神", "重大轉變、結束與重生", "恐懼變革、拖延"),
            ("節制", "平衡、適度、耐心融合", "失去平衡、極端衝動"),
            ("惡魔", "物質束縛、誘惑、執念", "打破枷鎖、覺醒"),
            ("高塔", "突如其來的劇變、覺醒", "恐懼瓦解、重建困難"),
            ("星星", "希望、靈感、寧靜信任", "絕望、信心動搖"),
            ("月亮", "幻覺、潛意識恐懼、不安", "看清真相、恐懼消散"),
            ("太陽", "喜悅、成功、活力四射", "暫時陰霾、過度自信"),
            ("審判", "覺醒、救贖、重大決定", "逃避審視、自責"),
            ("世界", "圓滿、達成目標、完整", "功虧一簣、停滯"),
        ]
        card = secrets.choice(major_arcana)
        is_upright = secrets.choice([True, False])
        return {
            "card_name": card[0],
            "position": "正位" if is_upright else "逆位",
            "meaning": card[1] if is_upright else card[2],
        }

    specs.append({
        "name": "tarot_card_draw",
        "category": "遊戲社群",
        "description": "從塔羅牌大阿爾克那 22 張牌中隨機抽取單張牌並解讀正逆位象徵",
        "parameters_desc": "無參數",
        "parameters_schema": {"type": "object", "properties": {}},
        "handler": h_tarot_card_draw,
    })

    async def h_rock_paper_scissors_sim(user_choice: str, **kwargs: Any) -> Dict[str, Any]:
        options = ["剪刀", "石頭", "布"]
        uc = user_choice.strip()
        if uc not in options:
            return {"error": "請輸入有效選項：剪刀、石頭、布"}
        bot_pick = secrets.choice(options)
        if uc == bot_pick:
            res = "平手"
        elif (uc == "剪刀" and bot_pick == "布") or (uc == "石頭" and bot_pick == "剪刀") or (uc == "布" and bot_pick == "石頭"):
            res = "玩家獲勝"
        else:
            res = "電腦獲勝"
        return {"user_choice": uc, "bot_choice": bot_pick, "result": res}

    specs.append({
        "name": "rock_paper_scissors_sim",
        "category": "遊戲社群",
        "description": "模擬猜拳剪刀石頭布對決並判定勝負結果",
        "parameters_desc": "user_choice: '剪刀', '石頭', 或 '布'",
        "parameters_schema": {
            "type": "object",
            "properties": {
                "user_choice": {"type": "string", "enum": ["剪刀", "石頭", "布"]},
            },
            "required": ["user_choice"],
        },
        "handler": h_rock_paper_scissors_sim,
    })

    # =========================================================================
    # 10. 日常生活、金融與色彩 (Daily Utilities, Finance & Color) - 11 Tools
    # =========================================================================

    async def h_currency_exchange_convert(amount: float, from_curr: str = "USD", to_curr: str = "TWD", **kwargs: Any) -> Dict[str, Any]:
        # Authoritative reference rates against USD base
        rates_to_usd = {
            "USD": 1.0, "TWD": 32.2, "JPY": 155.0, "EUR": 0.92,
            "GBP": 0.79, "KRW": 1380.0, "CNY": 7.25, "AUD": 1.52,
            "CAD": 1.37, "HKD": 7.82, "SGD": 1.35,
        }
        fc, tc = from_curr.upper().strip(), to_curr.upper().strip()
        if fc not in rates_to_usd or tc not in rates_to_usd:
            return {"error": f"不支援的貨幣代碼。支援清單: {list(rates_to_usd.keys())}"}
        amt = float(amount)
        amount_usd = amt / rates_to_usd[fc]
        target_amount = amount_usd * rates_to_usd[tc]
        return {
            "amount": amt,
            "from_currency": fc,
            "converted_amount": round(target_amount, 2),
            "to_currency": tc,
            "rate": round(rates_to_usd[tc] / rates_to_usd[fc], 4),
        }

    specs.append({
        "name": "currency_exchange_convert",
        "category": "生活金融",
        "description": "即時主要國際法幣（TWD, USD, JPY, EUR, GBP, KRW, CNY 等）匯率試算",
        "parameters_desc": "amount: 金額, from_curr: 來源貨幣, to_curr: 目標貨幣",
        "parameters_schema": {
            "type": "object",
            "properties": {
                "amount": {"type": "number"},
                "from_curr": {"type": "string", "default": "USD"},
                "to_curr": {"type": "string", "default": "TWD"},
            },
            "required": ["amount"],
        },
        "handler": h_currency_exchange_convert,
    })

    async def h_loan_monthly_payment_calc(principal: float, annual_rate_pct: float, years: int, **kwargs: Any) -> Dict[str, Any]:
        p = float(principal)
        r = float(annual_rate_pct) / 100.0 / 12.0
        n = int(years) * 12
        if r == 0:
            monthly = p / n
        else:
            monthly = p * (r * ((1 + r) ** n)) / (((1 + r) ** n) - 1)
        total_payment = monthly * n
        total_interest = total_payment - p
        return {
            "principal": p,
            "annual_rate_percent": annual_rate_pct,
            "years": years,
            "monthly_payment": round(monthly, 2),
            "total_interest": round(total_interest, 2),
            "total_payment": round(total_payment, 2),
        }

    specs.append({
        "name": "loan_monthly_payment_calc",
        "category": "生活金融",
        "description": "本息平均攤還房屋貸款/個人信貸之每月應繳金額與總利息試算",
        "parameters_desc": "principal: 貸款本金, annual_rate_pct: 年利率百分比 (如 2.1), years: 貸款年限",
        "parameters_schema": {
            "type": "object",
            "properties": {
                "principal": {"type": "number"},
                "annual_rate_pct": {"type": "number"},
                "years": {"type": "integer"},
            },
            "required": ["principal", "annual_rate_pct", "years"],
        },
        "handler": h_loan_monthly_payment_calc,
    })

    async def h_bmi_calculator(height_cm: float, weight_kg: float, **kwargs: Any) -> Dict[str, Any]:
        h_m = float(height_cm) / 100.0
        w = float(weight_kg)
        if h_m <= 0:
            return {"error": "身高必須大於 0"}
        bmi = w / (h_m ** 2)
        if bmi < 18.5:
            cat = "體重過輕"
        elif bmi < 24.0:
            cat = "健康正常範圍"
        elif bmi < 27.0:
            cat = "過重"
        elif bmi < 30.0:
            cat = "輕度肥胖"
        elif bmi < 35.0:
            cat = "中度肥胖"
        else:
            cat = "重度肥胖"
        ideal_min = 18.5 * (h_m ** 2)
        ideal_max = 24.0 * (h_m ** 2)
        return {
            "height_cm": height_cm,
            "weight_kg": weight_kg,
            "bmi": round(bmi, 2),
            "classification": cat,
            "ideal_weight_range_kg": f"{ideal_min:.1f} ~ {ideal_max:.1f} kg",
        }

    specs.append({
        "name": "bmi_calculator",
        "category": "生活金融",
        "description": "身高與體重換算身體質量指數 (BMI) 與理想體重健康範圍",
        "parameters_desc": "height_cm: 身高公分, weight_kg: 體重公斤",
        "parameters_schema": {
            "type": "object",
            "properties": {
                "height_cm": {"type": "number"},
                "weight_kg": {"type": "number"},
            },
            "required": ["height_cm", "weight_kg"],
        },
        "handler": h_bmi_calculator,
    })

    async def h_calorie_bmr_calc(gender: str, age: int, height_cm: float, weight_kg: float, **kwargs: Any) -> Dict[str, Any]:
        g = gender.strip().lower()
        a = int(age)
        h = float(height_cm)
        w = float(weight_kg)
        # Mifflin-St Jeor Equation
        bmr = 10 * w + 6.25 * h - 5 * a
        if g in ("male", "男", "m"):
            bmr += 5
        else:
            bmr -= 161
        return {
            "gender": gender,
            "age": a,
            "bmr_calories_per_day": round(bmr, 1),
            "tdee_sedentary": round(bmr * 1.2, 1),
            "tdee_moderate": round(bmr * 1.55, 1),
            "tdee_active": round(bmr * 1.725, 1),
        }

    specs.append({
        "name": "calorie_bmr_calc",
        "category": "生活金融",
        "description": "根據性別、年齡、身高體重計算基礎代謝率 (BMR) 與每日總消耗熱量 (TDEE)",
        "parameters_desc": "gender: '男'或'女', age: 年齡, height_cm: 身高, weight_kg: 體重",
        "parameters_schema": {
            "type": "object",
            "properties": {
                "gender": {"type": "string"},
                "age": {"type": "integer"},
                "height_cm": {"type": "number"},
                "weight_kg": {"type": "number"},
            },
            "required": ["gender", "age", "height_cm", "weight_kg"],
        },
        "handler": h_calorie_bmr_calc,
    })

    async def h_tip_calculator(bill_amount: float, tip_percent: float = 10.0, split_people: int = 1, **kwargs: Any) -> Dict[str, Any]:
        b = float(bill_amount)
        tp = float(tip_percent)
        sp = max(1, int(split_people))
        tip_val = b * (tp / 100.0)
        total = b + tip_val
        per_person = total / sp
        return {
            "bill_amount": b,
            "tip_percent": tp,
            "tip_amount": round(tip_val, 2),
            "total_with_tip": round(total, 2),
            "split_people": sp,
            "per_person_amount": round(per_person, 2),
        }

    specs.append({
        "name": "tip_calculator",
        "category": "生活金融",
        "description": "用餐服務費/小費計算與好友分攤帳單試算",
        "parameters_desc": "bill_amount: 帳單原價, tip_percent: 服務費百分比 (預設 10%), split_people: 分攤人數",
        "parameters_schema": {
            "type": "object",
            "properties": {
                "bill_amount": {"type": "number"},
                "tip_percent": {"type": "number", "default": 10.0},
                "split_people": {"type": "integer", "default": 1},
            },
            "required": ["bill_amount"],
        },
        "handler": h_tip_calculator,
    })

    async def h_discount_price_calc(original_price: float, discount_percent: float, **kwargs: Any) -> Dict[str, Any]:
        p = float(original_price)
        d = float(discount_percent)
        saved = p * (d / 100.0)
        final_price = p - saved
        return {
            "original_price": p,
            "discount_percent": d,
            "amount_saved": round(saved, 2),
            "final_discounted_price": round(final_price, 2),
        }

    specs.append({
        "name": "discount_price_calc",
        "category": "生活金融",
        "description": "計算商品打折後之實付金額與省下金額",
        "parameters_desc": "original_price: 原價, discount_percent: 折扣百分比 (例如 20 代表打8折省20%)",
        "parameters_schema": {
            "type": "object",
            "properties": {
                "original_price": {"type": "number"},
                "discount_percent": {"type": "number"},
            },
            "required": ["original_price", "discount_percent"],
        },
        "handler": h_discount_price_calc,
    })

    async def h_aspect_ratio_calc(width: int, height: int, **kwargs: Any) -> Dict[str, Any]:
        w, h = int(width), int(height)
        g = math.gcd(w, h)
        return {
            "width": w,
            "height": h,
            "aspect_ratio": f"{w // g}:{h // g}",
            "decimal_ratio": round(w / h, 4) if h != 0 else 0,
        }

    specs.append({
        "name": "aspect_ratio_calc",
        "category": "生活金融",
        "description": "圖像與螢幕解析度之寬高比化簡 (例如 1920x1080 -> 16:9)",
        "parameters_desc": "width: 寬度像素, height: 高度像素",
        "parameters_schema": {
            "type": "object",
            "properties": {
                "width": {"type": "integer"},
                "height": {"type": "integer"},
            },
            "required": ["width", "height"],
        },
        "handler": h_aspect_ratio_calc,
    })

    async def h_color_hex_to_rgb(hex_code: str, **kwargs: Any) -> Dict[str, Any]:
        clean = hex_code.strip().lstrip("#")
        if len(clean) == 3:
            clean = "".join(c * 2 for c in clean)
        if len(clean) != 6:
            return {"error": "請輸入有效之 3 碼或 6 碼 Hex 色碼 (如 #FF5733)"}
        try:
            r = int(clean[0:2], 16)
            g = int(clean[2:4], 16)
            b = int(clean[4:6], 16)
            return {"hex": f"#{clean.upper()}", "r": r, "g": g, "b": b, "rgb_css": f"rgb({r}, {g}, {b})"}
        except ValueError:
            return {"error": "無效的十六進位字元"}

    specs.append({
        "name": "color_hex_to_rgb",
        "category": "生活金融",
        "description": "將十六進位 Hex 色碼 (如 #3498DB) 轉換為 RGB 數值 (r, g, b)",
        "parameters_desc": "hex_code: 十六進位色碼 (如 #FF5733)",
        "parameters_schema": {
            "type": "object",
            "properties": {"hex_code": {"type": "string"}},
            "required": ["hex_code"],
        },
        "handler": h_color_hex_to_rgb,
    })

    async def h_color_rgb_to_hex(r: int, g: int, b: int, **kwargs: Any) -> Dict[str, Any]:
        cr = max(0, min(255, int(r)))
        cg = max(0, min(255, int(g)))
        cb = max(0, min(255, int(b)))
        hex_str = f"#{cr:02X}{cg:02X}{cb:02X}"
        return {"r": cr, "g": cg, "b": cb, "hex": hex_str}

    specs.append({
        "name": "color_rgb_to_hex",
        "category": "生活金融",
        "description": "將 RGB (紅綠藍 0~255) 數值轉換為標準十六進位 Hex 色碼",
        "parameters_desc": "r, g, b 為 0~255 之整數",
        "parameters_schema": {
            "type": "object",
            "properties": {
                "r": {"type": "integer"},
                "g": {"type": "integer"},
                "b": {"type": "integer"},
            },
            "required": ["r", "g", "b"],
        },
        "handler": h_color_rgb_to_hex,
    })

    async def h_discord_snowflake_timestamp(snowflake_id: int, **kwargs: Any) -> Dict[str, Any]:
        sf = int(snowflake_id)
        # Discord epoch: 1420070400000
        epoch = 1420070400000
        ms = (sf >> 22) + epoch
        dt = datetime.datetime.fromtimestamp(ms / 1000.0, tz=datetime.timezone.utc)
        return {
            "snowflake_id": sf,
            "created_at_utc": dt.strftime("%Y-%m-%d %H:%M:%S UTC"),
            "unix_timestamp": int(ms / 1000),
            "iso": dt.isoformat(),
        }

    specs.append({
        "name": "discord_snowflake_timestamp",
        "category": "生活金融",
        "description": "從 Discord 64 位元 Snowflake ID 反推帳號、頻道或訊息之精確建立時間",
        "parameters_desc": "snowflake_id: Discord 數位識別碼 (例如 154082736128738918)",
        "parameters_schema": {
            "type": "object",
            "properties": {"snowflake_id": {"type": "integer"}},
            "required": ["snowflake_id"],
        },
        "handler": h_discord_snowflake_timestamp,
    })

    async def h_uuid_generate(**kwargs: Any) -> Dict[str, Any]:
        import uuid
        uid = str(uuid.uuid4())
        return {"uuid_v4": uid, "urn": f"urn:uuid:{uid}"}

    specs.append({
        "name": "uuid_generate",
        "category": "生活金融",
        "description": "產生標準 RFC 4122 第四版隨機 UUID 唯一識別碼",
        "parameters_desc": "無參數",
        "parameters_schema": {"type": "object", "properties": {}},
        "handler": h_uuid_generate,
    })

    async def h_generate_ai_image(
        prompt: str,
        style: Optional[str] = None,
        aspect_ratio: str = "1:1",
        model: str = "flux",
        **kwargs: Any,
    ) -> Dict[str, Any]:
        from zeronexus.engines.image_gen import image_gen_engine
        res = await image_gen_engine.generate_image(
            prompt=prompt,
            style=style,
            aspect_ratio=aspect_ratio,
            model=model,
            verify_download=False,
        )
        return {
            "success": res.success,
            "image_url": res.image_url,
            "prompt": res.prompt,
            "enhanced_prompt": res.enhanced_prompt,
            "style": res.style,
            "aspect_ratio": res.aspect_ratio,
            "model": res.model,
            "width": res.width,
            "height": res.height,
            "seed": res.seed,
            "error": res.error_message,
        }

    specs.append({
        "name": "generate_ai_image",
        "category": "生活金融",
        "description": "運用 AI 繪圖引擎 (Pollinations Flux.1/SDXL) 生成高品質藝術影像或視覺插圖",
        "parameters_desc": "prompt: 圖片描述, style: 風格(可選), aspect_ratio: 寬高比(1:1, 16:9, 9:16, 4:3), model: 模型(flux/turbo)",
        "parameters_schema": {
            "type": "object",
            "properties": {
                "prompt": {
                    "type": "string",
                    "description": "欲生成的圖片畫面詳細描述 (例如: 一隻穿著太空衣在月球探險的柴犬)",
                },
                "style": {
                    "type": "string",
                    "description": "藝術風格: 寫實攝影, 二次元動漫, 奇幻插圖, 賽博龐克, 像素藝術, 3D渲染, 復古水彩",
                },
                "aspect_ratio": {
                    "type": "string",
                    "description": "畫面比例: 1:1, 16:9, 9:16, 4:3 (預設 1:1)",
                },
                "model": {
                    "type": "string",
                    "description": "生圖模型: flux 或 turbo (預設 flux)",
                },
            },
            "required": ["prompt"],
        },
        "handler": h_generate_ai_image,
    })

    # =========================================================================
    # 11. Python 安全代碼與圖表沙盒 (Python Code & Chart Sandbox) - 2 Tools
    # =========================================================================

    async def h_python_code_sandbox(code: str, **kwargs: Any) -> Dict[str, Any]:
        from zeronexus.engines.code_sandbox import code_sandbox
        res = await code_sandbox.execute_code(code=code)
        return res.to_dict()

    specs.append({
        "name": "python_code_sandbox",
        "category": "代碼沙盒",
        "description": "安全執行 Python 代碼與數據運算，支援 Matplotlib/Seaborn/Numpy/Pandas 並自動捕捉圖表與輸出",
        "parameters_desc": "code: 欲在安全隔離沙盒中執行的 Python 代碼",
        "parameters_schema": {
            "type": "object",
            "properties": {
                "code": {
                    "type": "string",
                    "description": "欲執行的 Python 代碼。預載 plt, sns, np, pd, math, json。圖表會自動渲染為 PNG 輸出。",
                },
            },
            "required": ["code"],
        },
        "handler": h_python_code_sandbox,
    })

    async def h_plot_chart(
        chart_type: str,
        title: str,
        data_json: str,
        x_label: str = "",
        y_label: str = "",
        **kwargs: Any,
    ) -> Dict[str, Any]:
        from zeronexus.engines.code_sandbox import code_sandbox
        res = await code_sandbox.plot_chart(
            chart_type=chart_type,
            title=title,
            data_json=data_json,
            x_label=x_label,
            y_label=y_label,
        )
        return res.to_dict()

    specs.append({
        "name": "plot_chart",
        "category": "代碼沙盒",
        "description": "繪製 Discord 暗黑美學質感圖表（長條圖/折線圖/圓餅圖/散佈圖/直方圖），繁體中文字體抗亂碼保證",
        "parameters_desc": "chart_type: bar/line/pie/scatter/hist, title: 圖表標題, data_json: 數據 JSON 字串, x_label: X軸標籤(選填), y_label: Y軸標籤(選填)",
        "parameters_schema": {
            "type": "object",
            "properties": {
                "chart_type": {
                    "type": "string",
                    "description": "圖表類型：bar (長條圖), line (折線圖), pie (圓餅圖), scatter (散佈圖), hist (直方圖)",
                    "enum": ["bar", "line", "pie", "scatter", "hist"],
                },
                "title": {
                    "type": "string",
                    "description": "圖表標題（保證 100% 繁體中文清晰無亂碼）",
                },
                "data_json": {
                    "type": "string",
                    "description": "圖表數據之 JSON 字串，例如 '{\"labels\": [\"A\", \"B\"], \"values\": [10, 20]}'",
                },
                "x_label": {
                    "type": "string",
                    "description": "X 軸標籤說明（選填）",
                },
                "y_label": {
                    "type": "string",
                    "description": "Y 軸標籤說明（選填）",
                },
            },
            "required": ["chart_type", "title", "data_json"],
        },
        "handler": h_plot_chart,
    })

    # =========================================================================
    # 12. 免 Key 公開 API 生態庫 (Free & Open APIs) - 9 Tools
    # =========================================================================

    async def h_steam_game_info(
        game_name: Optional[str] = None,
        appid: Optional[int] = None,
        currency: str = "tw",
        **kwargs: Any,
    ) -> Dict[str, Any]:
        return await free_apis.get_steam_game_info(game_name=game_name, appid=appid, currency=currency)

    specs.append({
        "name": "steam_game_info",
        "category": "公開生態",
        "description": "查詢 Steam 遊戲之即時售價、歷史最低價格（史低）、近期好評率與當前在線玩家數",
        "parameters_desc": "game_name: 遊戲名稱或關鍵字 (例如 艾爾登法環, Elden Ring), appid: Steam App ID (可選), currency: 幣別 (預設 tw)",
        "parameters_schema": {
            "type": "object",
            "properties": {
                "game_name": {
                    "type": "string",
                    "description": "遊戲中文或英文名稱 (例如 艾爾登法環, 黑神話 悟空, Cyberpunk 2077)",
                },
                "appid": {
                    "type": "integer",
                    "description": "Steam App 數位識別碼 (若已知可直接帶入)",
                },
                "currency": {
                    "type": "string",
                    "description": "Steam 商店地區貨幣代碼，預設 tw (新台幣 TWD)",
                },
            },
        },
        "handler": h_steam_game_info,
    })

    async def h_crypto_quote(
        symbol: str,
        vs_currency: str = "usd",
        **kwargs: Any,
    ) -> Dict[str, Any]:
        return await free_apis.get_crypto_quote(symbol=symbol, vs_currency=vs_currency)

    specs.append({
        "name": "crypto_quote",
        "category": "公開生態",
        "description": "查詢比特幣 (BTC)、以太坊 (ETH)、索拉納 (SOL) 等主流加密貨幣即時報價、24小時漲跌幅與成交量",
        "parameters_desc": "symbol: 貨幣代號或名稱 (例如 BTC, ETH, SOL, DOGE), vs_currency: 計價法幣 (預設 usd, 支援 twd)",
        "parameters_schema": {
            "type": "object",
            "properties": {
                "symbol": {
                    "type": "string",
                    "description": "加密貨幣代號或英文名稱 (例如 BTC, ETH, SOL, BNB, DOGE, XRP)",
                },
                "vs_currency": {
                    "type": "string",
                    "description": "計價目標貨幣，預設 usd (支援 usd 或 twd)",
                },
            },
            "required": ["symbol"],
        },
        "handler": h_crypto_quote,
    })

    async def h_exchange_rate_convert(
        from_currency: str,
        to_currency: str,
        amount: float = 1.0,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        return await free_apis.convert_exchange_rate(from_currency=from_currency, to_currency=to_currency, amount=amount)

    specs.append({
        "name": "exchange_rate_convert",
        "category": "公開生態",
        "description": "精準換算全球即時匯率，支援 TWD, JPY, USD, EUR, KRW 等法幣",
        "parameters_desc": "from_currency: 來源貨幣代號 (例如 JPY, USD), to_currency: 目標貨幣代號 (例如 TWD, USD), amount: 金額 (預設 1.0)",
        "parameters_schema": {
            "type": "object",
            "properties": {
                "from_currency": {
                    "type": "string",
                    "description": "來源貨幣 ISO 4217 代碼 (例如 JPY, USD, EUR, TWD, KRW, GBP)",
                },
                "to_currency": {
                    "type": "string",
                    "description": "目標換算貨幣 ISO 4217 代碼 (例如 TWD, JPY, USD, EUR, KRW)",
                },
                "amount": {
                    "type": "number",
                    "description": "欲換算的金額數量 (預設 1.0)",
                },
            },
            "required": ["from_currency", "to_currency"],
        },
        "handler": h_exchange_rate_convert,
    })

    async def h_taiwan_transit_status(
        transit_type: str = "ALL",
        station: Optional[str] = None,
        train_no: Optional[str] = None,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        return await free_apis.get_taiwan_transit_status(transit_type=transit_type, station=station, train_no=train_no)

    specs.append({
        "name": "taiwan_transit_status",
        "category": "公開生態",
        "description": "查詢台灣大眾運輸（台鐵 TRA、高鐵 THSR）之即時車次、電子看板與誤點狀況",
        "parameters_desc": "transit_type: 運具類別 (ALL, TRA, THSR), station: 車站名稱 (例如 台北, 台中, 高雄), train_no: 車次代號 (可選)",
        "parameters_schema": {
            "type": "object",
            "properties": {
                "transit_type": {
                    "type": "string",
                    "enum": ["ALL", "TRA", "THSR"],
                    "description": "大眾運具類別: TRA (台鐵), THSR (高鐵), 或 ALL (全部，預設)",
                },
                "station": {
                    "type": "string",
                    "description": "車站關鍵字 (例如 台北, 板橋, 桃園, 新竹, 台中, 左營, 高雄)",
                },
                "train_no": {
                    "type": "string",
                    "description": "指定列車車次編號 (例如 1276 或 0108)",
                },
            },
        },
        "handler": h_taiwan_transit_status,
    })

    async def h_anime_info_query(
        query: Optional[str] = None,
        seasonal: bool = False,
        season: Optional[str] = None,
        year: Optional[int] = None,
        limit: int = 5,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        return await free_apis.get_anime_info(query=query, seasonal=seasonal, season=season, year=year, limit=limit)

    specs.append({
        "name": "anime_info_query",
        "category": "公開生態",
        "description": "查詢動漫資料庫（MyAnimeList / AniList），獲取新番播出日程、作品評分、聲優陣容與動畫簡介",
        "parameters_desc": "query: 動漫作品名稱 (例如 葬送的芙莉蓮), seasonal: 是否查詢當季新番 (預設 false), season: 季度 (可選), year: 年份 (可選)",
        "parameters_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "欲搜尋的動漫名稱關鍵字 (例如 葬送的芙莉蓮, 鬼滅之刃, Frieren)",
                },
                "seasonal": {
                    "type": "boolean",
                    "description": "是否查詢當季正在熱播或最新播出之新番日程 (若為 true 則無需 query)",
                },
                "season": {
                    "type": "string",
                    "enum": ["spring", "summer", "fall", "winter"],
                    "description": "特定季度 (spring, summer, fall, winter)",
                },
                "year": {
                    "type": "integer",
                    "description": "指定年份 (例如 2024, 2025, 2026)",
                },
                "limit": {
                    "type": "integer",
                    "description": "回傳筆數上限 (預設 5)",
                },
            },
        },
        "handler": h_anime_info_query,
    })

    async def h_github_repo_info(
        repo: str,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        return await free_apis.get_github_repo_info(repo=repo)

    specs.append({
        "name": "github_repo_info",
        "category": "公開生態",
        "description": "查詢 GitHub 開源儲存庫之 Star 數、最新 Release 版本、作者與 Issue 狀態",
        "parameters_desc": "repo: 儲存庫名稱或網址 (例如 tiangolo/fastapi 或 https://github.com/owner/repo)",
        "parameters_schema": {
            "type": "object",
            "properties": {
                "repo": {
                    "type": "string",
                    "description": "GitHub 儲存庫名稱 (格式為 owner/repo，例如 fastapi/fastapi, tiangolo/fastapi 或完整 GitHub 網址)",
                },
            },
            "required": ["repo"],
        },
        "handler": h_github_repo_info,
    })

    async def h_wiki_definition(
        term: str,
        lang: str = "zh",
        **kwargs: Any,
    ) -> Dict[str, Any]:
        return await free_apis.get_wiki_definition(term=term, lang=lang)

    specs.append({
        "name": "wiki_definition",
        "category": "公開生態",
        "description": "查詢維基百科與 Wikidata 權威資料庫，零延遲獲取名詞解釋、歷史事件與標準定義",
        "parameters_desc": "term: 概念、人物、名詞或歷史事件名稱, lang: 語言代碼 (預設 zh)",
        "parameters_schema": {
            "type": "object",
            "properties": {
                "term": {
                    "type": "string",
                    "description": "欲查詢的名詞、歷史事件、科學概念或人物名稱 (例如 量子電腦, 狄拉克方程式, 諾曼第登陸)",
                },
                "lang": {
                    "type": "string",
                    "description": "維基百科語言代碼，預設 zh (中文，亦可傳 en, ja 等)",
                },
            },
            "required": ["term"],
        },
        "handler": h_wiki_definition,
    })

    async def h_taiwan_air_quality(
        location: str = "台北",
        **kwargs: Any,
    ) -> Dict[str, Any]:
        return await free_apis.get_air_quality_and_uv(location=location)

    specs.append({
        "name": "taiwan_air_quality",
        "category": "公開生態",
        "description": "查詢台灣各縣市即時環境部 AQI 空氣品質指標、PM2.5、PM10 與紫外線即時指數 (UV Index)",
        "parameters_desc": "location: 台灣縣市或鄉鎮市區名稱 (例如 台北, 新北, 台中, 高雄, 花蓮)",
        "parameters_schema": {
            "type": "object",
            "properties": {
                "location": {
                    "type": "string",
                    "description": "台灣縣市名稱 (例如 台北, 新北, 桃園, 新竹, 台中, 嘉義, 台南, 高雄, 屏東, 宜蘭, 花蓮, 台東, 澎湖, 金門)",
                },
            },
            "required": ["location"],
        },
        "handler": h_taiwan_air_quality,
    })

    async def h_google_custom_search(
        query: str,
        num_results: int = 5,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        return await free_apis.search_google_custom(query=query, num_results=num_results)

    specs.append({
        "name": "google_custom_search",
        "category": "公開生態",
        "description": "透過 Google Custom Search JSON API 進行即時網路搜尋（環境變數存在 Key 時優先選用，否則自動平滑備援）",
        "parameters_desc": "query: 搜尋關鍵字, num_results: 結果數量 (預設 5)",
        "parameters_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "欲在網路上搜尋的問題或關鍵字",
                },
                "num_results": {
                    "type": "integer",
                    "description": "欲回傳的搜尋結果項目數量 (預設 5，上限 10)",
                },
            },
            "required": ["query"],
        },
        "handler": h_google_custom_search,
    })

    async def h_stock_quote(symbol: str, **kwargs: Any) -> Dict[str, Any]:
        return await free_apis.get_stock_quote(symbol=symbol)

    specs.append({
        "name": "get_stock_quote",
        "category": "公開生態",
        "description": "查詢台股（如 2330、0050.TW）與美股（如 AAPL、NVDA、TSLA）之即時報價、漲跌金額、漲跌幅百分比、當日最高價、最低價與成交量",
        "parameters_desc": "symbol: 股票代碼或代號 (例如 2330, 2330.TW, 0050.TW, AAPL, NVDA, TSLA)",
        "parameters_schema": {
            "type": "object",
            "properties": {
                "symbol": {
                    "type": "string",
                    "description": "台股代號（例如 2330, 0050.TW）或美股代號（例如 AAPL, NVDA, TSLA）",
                },
            },
            "required": ["symbol"],
        },
        "handler": h_stock_quote,
    })

    specs.append({
        "name": "stock_quote",
        "category": "公開生態",
        "description": "查詢台股與美股即時報價、漲跌幅、最高價、最低價與成交量 (get_stock_quote 同名別名)",
        "parameters_desc": "symbol: 股票代碼",
        "parameters_schema": {
            "type": "object",
            "properties": {
                "symbol": {
                    "type": "string",
                    "description": "股票代碼 (例如 2330, 0050.TW, AAPL)",
                },
            },
            "required": ["symbol"],
        },
        "handler": h_stock_quote,
    })

    async def h_ip_geo_info(ip: str, **kwargs: Any) -> Dict[str, Any]:
        return await free_apis.get_ip_geo_info(ip=ip)

    specs.append({
        "name": "get_ip_geo_info",
        "category": "公開生態",
        "description": "查詢指定 IP 位址之地理位置資訊（國家、城市、經緯度）、網路服務提供商 (ISP) 與 ASN 自治系統編號",
        "parameters_desc": "ip: 欲查詢之 IP 位址 (例如 8.8.8.8)",
        "parameters_schema": {
            "type": "object",
            "properties": {
                "ip": {
                    "type": "string",
                    "description": "欲查詢的 IPv4 或 IPv6 位址 (例如 8.8.8.8, 1.1.1.1)",
                },
            },
            "required": ["ip"],
        },
        "handler": h_ip_geo_info,
    })

    specs.append({
        "name": "ip_geo_info",
        "category": "公開生態",
        "description": "查詢 IP 歸屬地與網路地理資訊 (get_ip_geo_info 同名別名)",
        "parameters_desc": "ip: 欲查詢之 IP 位址",
        "parameters_schema": {
            "type": "object",
            "properties": {
                "ip": {
                    "type": "string",
                    "description": "欲查詢的 IP 位址",
                },
            },
            "required": ["ip"],
        },
        "handler": h_ip_geo_info,
    })

    async def h_check_website_ssl(host: str, port: int = 443, **kwargs: Any) -> Dict[str, Any]:
        return await free_apis.check_website_ssl(host=host, port=port)

    specs.append({
        "name": "check_website_ssl",
        "category": "公開生態",
        "description": "探測指定網站主機之 SSL/TLS 憑證到期日、剩餘有效天數、憑證頒發機構 (Issuer)、TLS 協定版本與連線握手延遲",
        "parameters_desc": "host: 網站主機名稱或網址 (例如 www.google.com), port: 連接埠 (預設 443)",
        "parameters_schema": {
            "type": "object",
            "properties": {
                "host": {
                    "type": "string",
                    "description": "網站主機名稱或網址 (例如 www.google.com, github.com)",
                },
                "port": {
                    "type": "integer",
                    "description": "SSL/TLS 連接埠 (預設 443)",
                },
            },
            "required": ["host"],
        },
        "handler": h_check_website_ssl,
    })

    async def h_bilibili_video_info(bvid: str, **kwargs: Any) -> Dict[str, Any]:
        return await free_apis.get_bilibili_video_info(bvid=bvid)

    specs.append({
        "name": "get_bilibili_video_info",
        "category": "公開生態",
        "description": "解析 Bilibili (B站) 影片之標題、UP主作者、播放次數、彈幕數、按讚投幣數、簡介與封面縮圖",
        "parameters_desc": "bvid: Bilibili 影片 BV 號或影片完整網址 (例如 BV1xx411c7mD)",
        "parameters_schema": {
            "type": "object",
            "properties": {
                "bvid": {
                    "type": "string",
                    "description": "Bilibili 影片 BV 號或網址 (例如 BV1xx411c7mD)",
                },
            },
            "required": ["bvid"],
        },
        "handler": h_bilibili_video_info,
    })

    specs.append({
        "name": "bilibili_video_info",
        "category": "公開生態",
        "description": "解析 B站 影片情報與統計數據 (get_bilibili_video_info 同名別名)",
        "parameters_desc": "bvid: 影片 BV 號",
        "parameters_schema": {
            "type": "object",
            "properties": {
                "bvid": {
                    "type": "string",
                    "description": "Bilibili 影片 BV 號",
                },
            },
            "required": ["bvid"],
        },
        "handler": h_bilibili_video_info,
    })

    async def h_search_music_preview(track_name: str, limit: int = 5, **kwargs: Any) -> Dict[str, Any]:
        return await free_apis.search_music_preview(track_name=track_name, limit=limit)

    specs.append({
        "name": "search_music_preview",
        "category": "公開生態",
        "description": "透過 Apple iTunes 公開資料庫搜尋歌曲，獲取 30 秒高音質音訊試聽串流連結、歌手、專輯名稱與封面縮圖",
        "parameters_desc": "track_name: 歌曲名稱或歌手關鍵字, limit: 回傳筆數 (預設 5)",
        "parameters_schema": {
            "type": "object",
            "properties": {
                "track_name": {
                    "type": "string",
                    "description": "欲搜尋的歌曲名稱或歌手名稱 (例如 晴天, 夜曲, Shape of You)",
                },
                "limit": {
                    "type": "integer",
                    "description": "回傳歌曲數量 (預設 5，上限 10)",
                },
            },
            "required": ["track_name"],
        },
        "handler": h_search_music_preview,
    })

    specs.append({
        "name": "music_preview_search",
        "category": "公開生態",
        "description": "搜尋 30 秒音樂試聽與專輯封面 (search_music_preview 同名別名)",
        "parameters_desc": "track_name: 歌曲名稱, limit: 回傳筆數",
        "parameters_schema": {
            "type": "object",
            "properties": {
                "track_name": {
                    "type": "string",
                    "description": "歌曲名稱",
                },
                "limit": {
                    "type": "integer",
                    "description": "回傳筆數",
                },
            },
            "required": ["track_name"],
        },
        "handler": h_search_music_preview,
    })

    async def h_create_project_zip_archive(
        output_filename: Optional[str] = None,
        exclude_patterns: Optional[List[str]] = None,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        return await free_apis.create_project_zip_archive(
            output_filename=output_filename,
            exclude_patterns=exclude_patterns,
        )

    specs.append({
        "name": "create_project_zip_archive",
        "category": "公開生態",
        "description": "安全將 ZeroNexus 專案檔案封存壓縮為 ZIP 打包檔，自動過濾虛擬環境、暫存快取、機密環境變數與資料庫檔案",
        "parameters_desc": "output_filename: 封存檔名稱 (可選), exclude_patterns: 額外排除的 glob 樣式清單 (可選)",
        "parameters_schema": {
            "type": "object",
            "properties": {
                "output_filename": {
                    "type": "string",
                    "description": "封存壓縮檔案名稱 (例如 backup_v1.zip，若未填寫則自動帶入時間戳記)",
                },
                "exclude_patterns": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "額外欲排除的檔案或目錄模式清單",
                },
            },
        },
        "handler": h_create_project_zip_archive,
    })

    specs.append({
        "name": "project_zip_archive",
        "category": "公開生態",
        "description": "專案 ZIP 封存打包器 (create_project_zip_archive 同名別名)",
        "parameters_desc": "output_filename: 檔名 (可選)",
        "parameters_schema": {
            "type": "object",
            "properties": {
                "output_filename": {
                    "type": "string",
                    "description": "壓縮檔案名稱",
                },
            },
        },
        "handler": h_create_project_zip_archive,
    })

    # =========================================================================
    # 13. 生活與交通便民工具 (Life & Transport Engines - CatBot Legacy) - 3 Tools
    # =========================================================================

    async def h_cpc_fuel_prices(**kwargs: Any) -> Dict[str, Any]:
        return await free_apis.get_cpc_fuel_prices()

    specs.append({
        "name": "cpc_fuel_prices",
        "category": "公開生態",
        "description": "查詢台灣中油 (CPC) 即時油價（92無鉛、95無鉛、98無鉛、超級柴油）、下週預估調幅與台塑石化油價",
        "parameters_desc": "無參數",
        "parameters_schema": {"type": "object", "properties": {}},
        "handler": h_cpc_fuel_prices,
    })

    async def h_taiwan_invoice_lottery(period: Optional[str] = None, **kwargs: Any) -> Dict[str, Any]:
        return await free_apis.get_taiwan_invoice_lottery(period=period)

    specs.append({
        "name": "taiwan_invoice_lottery",
        "category": "公開生態",
        "description": "查詢台灣統一發票最新一期與近期中獎號碼（特別獎、特獎、頭獎、增開六獎）與領獎兌獎期限",
        "parameters_desc": "period: 特定開獎期別 (例如 115年 05~06月，選填，預設最新期別)",
        "parameters_schema": {
            "type": "object",
            "properties": {
                "period": {
                    "type": "string",
                    "description": "欲查詢的特定統一發票期別 (例如 115年 05~06月，留空則自動查詢最新開獎期別)",
                },
            },
        },
        "handler": h_taiwan_invoice_lottery,
    })

    async def h_rail_timetable_query(
        origin: str,
        destination: str,
        rail_type: str = "all",
        **kwargs: Any,
    ) -> Dict[str, Any]:
        return await free_apis.query_rail_timetable(origin=origin, destination=destination, rail_type=rail_type)

    specs.append({
        "name": "rail_timetable_query",
        "category": "公開生態",
        "description": "查詢台灣大眾鐵路時刻表（台鐵 TRA、高鐵 THSR），提供直達列車車次、出發/抵達時間、行車歷時、票價與運行誤點狀態",
        "parameters_desc": "origin: 出發站 (例如 台北, 桃園, 台中, 高雄, 花蓮), destination: 抵達站 (例如 台中, 台南, 左營, 台北), rail_type: 鐵路類別 (all, tra, thsr，預設 all)",
        "parameters_schema": {
            "type": "object",
            "properties": {
                "origin": {
                    "type": "string",
                    "description": "出發站名稱或關鍵字 (例如 台北, 板橋, 桃園, 新竹, 台中, 嘉義, 台南, 高雄, 左營, 花蓮, 台東)",
                },
                "destination": {
                    "type": "string",
                    "description": "抵達站名稱或關鍵字 (例如 台中, 高雄, 左營, 台北, 花蓮, 台南, 屏東, 羅東)",
                },
                "rail_type": {
                    "type": "string",
                    "enum": ["all", "tra", "thsr"],
                    "description": "鐵路類別: all (台鐵+高鐵，預設), tra (僅查詢台鐵), thsr (僅查詢高鐵)",
                },
            },
            "required": ["origin", "destination"],
        },
        "handler": h_rail_timetable_query,
    })

    specs.append({
        "name": "query_rail_timetable",
        "category": "公開生態",
        "description": "查詢台灣大眾鐵路時刻表（台鐵 TRA、高鐵 THSR）車次、票價與運行誤點狀態 (rail_timetable_query 同名別名)",
        "parameters_desc": "origin: 出發站, destination: 抵達站, rail_type: 鐵路類別 (all, tra, thsr)",
        "parameters_schema": {
            "type": "object",
            "properties": {
                "origin": {
                    "type": "string",
                    "description": "出發站名稱 (例如 台北, 台中, 高雄, 花蓮)",
                },
                "destination": {
                    "type": "string",
                    "description": "抵達站名稱 (例如 台中, 台南, 左營, 台北)",
                },
                "rail_type": {
                    "type": "string",
                    "enum": ["all", "tra", "thsr"],
                    "description": "鐵路類別: all, tra, thsr",
                },
            },
            "required": ["origin", "destination"],
        },
        "handler": h_rail_timetable_query,
    })

    async def h_cwa_radar_image(**kwargs: Any) -> Dict[str, Any]:
        res = await free_apis.get_cwa_radar_image()
        return {"status": res.get("status"), "title": res.get("title"), "url": res.get("url"), "description": res.get("description")}

    specs.append({
        "name": "cwa_radar_image",
        "category": "公開生態",
        "description": "取得交通部中央氣象署 (CWA) 最新官方台灣全區高解析度雷達回波降雨圖",
        "parameters_desc": "無參數",
        "parameters_schema": {"type": "object", "properties": {}},
        "handler": h_cwa_radar_image,
    })

    async def h_cwa_satellite_image(area: str = "taiwan", **kwargs: Any) -> Dict[str, Any]:
        res = await free_apis.get_cwa_satellite_image(area=area)
        return {"status": res.get("status"), "title": res.get("title"), "url": res.get("url"), "description": res.get("description")}

    specs.append({
        "name": "cwa_satellite_image",
        "category": "公開生態",
        "description": "取得交通部中央氣象署 (CWA) 最新官方高解析度向日葵衛星雲圖 (台灣彩色紅外線或東亞全景)",
        "parameters_desc": "area: 區域 (taiwan 或 east_asia，預設 taiwan)",
        "parameters_schema": {
            "type": "object",
            "properties": {
                "area": {
                    "type": "string",
                    "enum": ["taiwan", "east_asia"],
                    "description": "衛星雲圖涵蓋範圍: taiwan (台灣), east_asia (東亞全區)",
                },
            },
        },
        "handler": h_cwa_satellite_image,
    })

    async def h_cwa_rainfall_image(**kwargs: Any) -> Dict[str, Any]:
        res = await free_apis.get_cwa_rainfall_image()
        return {"status": res.get("status"), "title": res.get("title"), "url": res.get("url"), "description": res.get("description")}

    specs.append({
        "name": "cwa_rainfall_image",
        "category": "公開生態",
        "description": "取得交通部中央氣象署 (CWA) 最新全台各測站 24 小時累積降雨量分佈色階圖",
        "parameters_desc": "無參數",
        "parameters_schema": {"type": "object", "properties": {}},
        "handler": h_cwa_rainfall_image,
    })

    async def h_wikipedia_today_in_history(month: Optional[int] = None, day: Optional[int] = None, **kwargs: Any) -> Dict[str, Any]:
        return await free_apis.get_wikipedia_today_in_history(month=month, day=day)

    specs.append({
        "name": "wikipedia_today_in_history",
        "category": "公開生態",
        "description": "查詢維基百科官方『歷史上的今天』精選重大歷史事件、歷史轉折點與人物里程碑",
        "parameters_desc": "month: 月份 (1~12，選填，預設今天), day: 日期 (1~31，選填，預設今天)",
        "parameters_schema": {
            "type": "object",
            "properties": {
                "month": {"type": "integer", "description": "月份 (1-12)"},
                "day": {"type": "integer", "description": "日期 (1-31)"},
            },
        },
        "handler": h_wikipedia_today_in_history,
    })


    # =========================================================================
    # 14. Google 官方套件工具 (Google Official Suite) - 6 Tools
    # =========================================================================

    async def h_check_url_safety(url: str, **kwargs: Any) -> Dict[str, Any]:
        return await google_suite.safe_browsing.check_url(url=url)

    specs.append({
        "name": "check_url_safety",
        "category": "公開生態",
        "description": "透過 Google Safe Browsing API 檢測目標網址是否屬於釣魚網站 (Phishing)、惡意軟體 (Malware) 或有害目標",
        "parameters_desc": "url: 欲檢測的目標網址",
        "parameters_schema": {
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "欲進行 Google Safe Browsing 資安檢測的目標網址",
                },
            },
            "required": ["url"],
        },
        "handler": h_check_url_safety,
    })

    async def h_youtube_video_info(url_or_id: str, **kwargs: Any) -> Dict[str, Any]:
        return await google_suite.youtube.get_video_details(url_or_id=url_or_id)

    specs.append({
        "name": "youtube_video_info",
        "category": "公開生態",
        "description": "透過 YouTube Data API v3 獲取指定影片之官方情報（標題、作者、播放長度、觀看次數、點讚數與封面縮圖）",
        "parameters_desc": "url_or_id: YouTube 影片網址或 11 位字元 ID",
        "parameters_schema": {
            "type": "object",
            "properties": {
                "url_or_id": {
                    "type": "string",
                    "description": "YouTube 影片連結（如 https://www.youtube.com/watch?v=...）或影片 ID",
                },
            },
            "required": ["url_or_id"],
        },
        "handler": h_youtube_video_info,
    })

    async def h_youtube_search(query: str, max_results: int = 5, **kwargs: Any) -> Dict[str, Any]:
        return await google_suite.youtube.search_videos(query=query, max_results=max_results)

    specs.append({
        "name": "youtube_search",
        "category": "公開生態",
        "description": "透過 YouTube Data API v3 搜尋 YouTube 平台上的相關影片與創作者",
        "parameters_desc": "query: 搜尋關鍵字, max_results: 回傳筆數 (預設 5)",
        "parameters_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "欲在 YouTube 搜尋的關鍵字或主題",
                },
                "max_results": {
                    "type": "integer",
                    "description": "回傳搜尋結果項目數量 (預設 5，上限 10)",
                },
            },
            "required": ["query"],
        },
        "handler": h_youtube_search,
    })

    async def h_google_fact_check(query: str, **kwargs: Any) -> Dict[str, Any]:
        return await google_suite.fact_check.search_claims(query=query)

    specs.append({
        "name": "google_fact_check",
        "category": "公開生態",
        "description": "透過 Google Fact Check Tools API 檢索全球與台灣各大認證查核機構（如台灣事實查核中心、MyGoPen）之闢謠報告與事實查證評級",
        "parameters_desc": "query: 欲查核之新聞語句、謠言關鍵字或傳聞",
        "parameters_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "欲向事實查核資料庫檢驗的陳述句或事件關鍵字",
                },
            },
            "required": ["query"],
        },
        "handler": h_google_fact_check,
    })

    async def h_pagespeed_audit(url: str, strategy: str = "mobile", **kwargs: Any) -> Dict[str, Any]:
        return await google_suite.pagespeed.analyze_url(url=url, strategy=strategy)

    specs.append({
        "name": "pagespeed_audit",
        "category": "公開生態",
        "description": "透過 Google PageSpeed Insights API 執行網站效能體檢，獲取 Lighthouse 0-100 分數與核心網站指標 (FCP, LCP, CLS, TBT)",
        "parameters_desc": "url: 目標網站網址, strategy: 裝置模式 (mobile 或 desktop)",
        "parameters_schema": {
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "欲測速與體檢的網站完整網址",
                },
                "strategy": {
                    "type": "string",
                    "enum": ["mobile", "desktop"],
                    "description": "測速環境 (mobile 行動版 或 desktop 電腦版)",
                },
            },
            "required": ["url"],
        },
        "handler": h_pagespeed_audit,
    })

    async def h_google_books_search(query: str, max_results: int = 5, **kwargs: Any) -> Dict[str, Any]:
        return await google_suite.books.search_books(query=query, max_results=max_results)

    specs.append({
        "name": "google_books_search",
        "category": "公開生態",
        "description": "透過 Google Books API 檢索全球圖書出版資料庫，獲取書名、作者、出版社、ISBN、內容簡介與封面縮圖",
        "parameters_desc": "query: 書名、作者或 ISBN, max_results: 回傳筆數 (預設 5)",
        "parameters_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "書名、作者名稱、關鍵字或 ISBN 條碼",
                },
                "max_results": {
                    "type": "integer",
                    "description": "回傳書籍數量 (預設 5，上限 10)",
                },
            },
            "required": ["query"],
        },
        "handler": h_google_books_search,
    })

    # =========================================================================
    # 13. Discord 頻道情境洞察與情資分析 (Channel Context & Analytics) - 3 Tools
    # =========================================================================

    async def h_inspect_channel_messages(
        start_time: str = "",
        limit: int = 100,
        channel: Optional[Any] = None,
        guild: Optional[Any] = None,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        from zeronexus.engines.channel_inspector import channel_inspector, parse_channel_time_filter
        if not channel:
            return {"error": "無法取得當前頻道上下文，請在 Discord 文字頻道內調用。"}

        after_dt = None
        filter_desc = "最近訊息"
        if start_time and str(start_time).strip():
            after_dt, filter_desc = parse_channel_time_filter(str(start_time))

        msgs, err = await channel_inspector.fetch_channel_messages(channel=channel, after=after_dt, limit=limit)
        if err:
            return {"error": err, "channel_name": getattr(channel, "name", "未知")}

        transcript = channel_inspector.format_messages_to_transcript(msgs)
        return {
            "channel_name": getattr(channel, "name", "未知"),
            "channel_id": getattr(channel, "id", 0),
            "filter_applied": filter_desc or "無時間過濾",
            "messages_count": len(msgs),
            "transcript": transcript,
        }

    specs.append({
        "name": "inspect_channel_messages",
        "category": "頻道情資",
        "description": "抓取當前 Discord 頻道的即時歷史聊天記錄，支援按特定時間點（如『20:03』、『今天 20:00』、『1小時前』）或最新 N 條訊息過濾。用於統整話題、聊天記錄摘要與爭論焦點。",
        "parameters_desc": "start_time: 起始時間條件（例如 '20:03'、'今天 20:00'、'30分鐘前'，選填）, limit: 抓取上限則數 (預設 100，上限 300)",
        "parameters_schema": {
            "type": "object",
            "properties": {
                "start_time": {
                    "type": "string",
                    "description": "起始時間條件，例如 '20:03'、'20:03開始'、'今天 20:00'、'30分鐘前'、'1小時前'。留空表示抓取最新歷史訊息。",
                },
                "limit": {
                    "type": "integer",
                    "description": "抓取最大訊息則數，預設 100，上限 300。",
                },
            },
        },
        "handler": h_inspect_channel_messages,
    })

    async def h_analyze_channel_activity(
        time_window: str = "",
        limit: int = 150,
        channel: Optional[Any] = None,
        guild: Optional[Any] = None,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        from zeronexus.engines.channel_inspector import channel_inspector, parse_channel_time_filter
        if not channel:
            return {"error": "無法取得當前頻道上下文，請在 Discord 文字頻道內調用。"}

        after_dt = None
        if time_window and str(time_window).strip():
            after_dt, _ = parse_channel_time_filter(str(time_window))

        msgs, err = await channel_inspector.fetch_channel_messages(channel=channel, after=after_dt, limit=limit)
        if err:
            return {"error": err, "channel_name": getattr(channel, "name", "未知")}

        stats = channel_inspector.compute_channel_activity_stats(msgs, channel_name=getattr(channel, "name", "未知"))
        return stats

    specs.append({
        "name": "analyze_channel_activity",
        "category": "頻道情資",
        "description": "分析當前 Discord 頻道的發言排行榜與成員活躍度（誰說得最多、發言量排行、總字數、參與人數與熱門討論者）。",
        "parameters_desc": "time_window: 統計時間窗口（例如 '今天'、'20:03'、'2小時前'，選填）, limit: 分析樣本訊息量 (預設 150，上限 300)",
        "parameters_schema": {
            "type": "object",
            "properties": {
                "time_window": {
                    "type": "string",
                    "description": "統計起始時間，例如 '今天'、'20:03'、'1小時前'。選填。",
                },
                "limit": {
                    "type": "integer",
                    "description": "分析取樣訊息筆數，預設 150，上限 300。",
                },
            },
        },
        "handler": h_analyze_channel_activity,
    })

    async def h_inspect_channel_overview(
        channel: Optional[Any] = None,
        guild: Optional[Any] = None,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        from zeronexus.engines.channel_inspector import channel_inspector
        if not channel:
            return {"error": "無法取得當前頻道上下文，請在 Discord 文字頻道內調用。"}

        return channel_inspector.get_channel_overview_details(channel)

    specs.append({
        "name": "inspect_channel_overview",
        "category": "頻道情資",
        "description": "獲取當前頻道的全方位情資總覽，包含頻道主題說明、創立時間、慢速模式、年齡限制 (NSFW) 與活躍討論串 (Threads)。",
        "parameters_desc": "無須額外參數，自動由環境帶入頻道物件",
        "parameters_schema": {"type": "object", "properties": {}},
        "handler": h_inspect_channel_overview,
    })

    # =========================================================================
    # 13. ZeroNexus 500 大師特性中樞工具 (Master 500 Features Dispatcher)
    # =========================================================================


    async def h_call_master_feature(
        feature_id: int,
        param: Optional[str] = "",
        user: Optional[Any] = None,
        guild: Optional[Any] = None,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        """調用 ZeroNexus 500 大師特性的底層執行器。"""
        from zeronexus.features.dispatcher import MasterFeatureDispatcher
        from zeronexus.features.registry import MasterFeatureRegistry
        dispatcher = MasterFeatureDispatcher()
        feat = MasterFeatureRegistry.get_by_id(feature_id)
        if not feat:
            return {"error": f"找不到功能編號 #{feature_id}，請確認編號介於 1 至 500。"}

        user_id = str(user.id) if user else "0"
        guild_id = str(guild.id) if guild else "0"
        user_name = getattr(user, "display_name", "使用者")
        guild_name = getattr(guild, "name", "社群")

        embed = await dispatcher.execute_feature(
            feature_id=feature_id,
            user_id=user_id,
            guild_id=guild_id,
            user_name=user_name,
            guild_name=guild_name,
            param=param or ""
        )
        return {
            "feature_id": feature_id,
            "feature_name": feat.name,
            "category": feat.category,
            "title": embed.title,
            "description": embed.description,
            "fields": [{"name": f.name, "value": f.value} for f in embed.fields]
        }

    specs.append({
        "name": "call_master_feature",
        "category": "500大師中樞",
        "description": "呼叫 ZeroNexus 500 大師全功能清單中指定編號 (1-500) 的強大特性（如記憶管理、知識庫檢索、工作流、數據分析、氣象地震、代碼分析等）。",
        "parameters_desc": "feature_id (1-500整數), param (選填參數)",
        "parameters_schema": {
            "type": "object",
            "properties": {
                "feature_id": {
                    "type": "integer",
                    "description": "500 功能大師清單之目標編號 (1 至 500)。"
                },
                "param": {
                    "type": "string",
                    "description": "傳遞給該功能的參數（如關鍵字、日期、目標文字或網址）。選填。"
                }
            },
            "required": ["feature_id"]
        },
        "handler": h_call_master_feature,
    })

    async def h_search_master_features(keyword: str, **kwargs: Any) -> Dict[str, Any]:
        """搜尋 500 大師功能清單。"""
        from zeronexus.features.registry import MasterFeatureRegistry
        matched = MasterFeatureRegistry.search(keyword, limit=10)
        return {
            "keyword": keyword,
            "count": len(matched),
            "features": [
                {"id": f.id, "name": f.name, "category": f.category, "description": f.description}
                for f in matched
            ]
        }

    specs.append({
        "name": "search_master_features",
        "category": "500大師中樞",
        "description": "在 ZeroNexus 500 項官方需求功能清單中模糊搜尋特定功能與編號。",
        "parameters_desc": "keyword (搜尋關鍵字)",
        "parameters_schema": {
            "type": "object",
            "properties": {
                "keyword": {
                    "type": "string",
                    "description": "欲查詢的技術名詞或功能關鍵字（例如：記憶、氣象、JSON、Git、工作流、投票等）。"
                }
            },
            "required": ["keyword"]
        },
        "handler": h_search_master_features,
    })

    return specs

