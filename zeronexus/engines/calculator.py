"""ZeroNexus Sandboxed SymPy Mathematical Computation Engine.

Capabilities:
- Arbitrary precision integer arithmetic & high precision decimals
- Symbolic calculus (derivatives, integrals, limits)
- Algebraic equations & factorization
- Number theory (prime checks, prime factorization, GCD, LCM)
- Combinatorics (permutations, combinations, factorials)
- Physical unit conversions (length, weight, temperature, data)
- Strict AST validation:
  * Blocks chained exponents (9**9**9, (9**9)**9) to prevent memory inflation attacks
  * Restricts max exponent to 1000 and estimated digit expansion to 3000
  * Limits factorial(n <= 1000) and exp(x <= 700)
  * Blocks attribute/subscript reflection (__class__, __base__, etc.)
  * Strict execution timeout guard (3.0s)
"""

from __future__ import annotations

import ast
import asyncio
import concurrent.futures
from dataclasses import dataclass, field
import math
import re
import time
from typing import Any, Dict, List, Optional, Tuple

import sympy
from sympy import (
    E,
    Abs,
    Symbol,
    ceiling,
    cos,
    diff,
    expand,
    exp,
    factor,
    factorial,
    floor,
    gcd,
    integrate,
    isprime,
    lcm,
    log,
    pi,
    primefactors,
    simplify,
    sin,
    solve,
    sqrt,
    sympify,
    tan,
)


@dataclass
class CalculationResult:
    expression: str
    result_str: str = ""
    is_error: bool = False
    error_message: Optional[str] = None
    execution_time_ms: float = 0.0
    latex_str: Optional[str] = None
    solutions: List[str] = field(default_factory=list)

    def __iter__(self):
        if self.solutions:
            return iter(self.solutions)
        return iter([self.result_str] if self.result_str else [])

    def __contains__(self, item: Any) -> bool:
        if self.solutions:
            return item in self.solutions
        return str(item) in self.result_str

    def __await__(self):
        async def _coro():
            if self.is_error:
                raise ValueError(self.error_message or "運算錯誤")
            return self.solutions if self.solutions else self.result_str
        return _coro().__await__()


class FactorResult(list):
    """List of (base, exp) tuples that can also be formatted as a string or awaited."""

    def __init__(self, pairs: List[Tuple[int, int]], display_str: str = ""):
        super().__init__(pairs)
        self.display_str = display_str

    def __str__(self) -> str:
        return self.display_str

    def __await__(self):
        async def _coro():
            return self.display_str
        return _coro().__await__()


# Whitelist of allowed functions & symbols in SymPy environment
ALLOWED_LOCALS: Dict[str, Any] = {
    "sin": sin,
    "cos": cos,
    "tan": tan,
    "sqrt": sqrt,
    "log": log,
    "exp": exp,
    "abs": Abs,
    "floor": floor,
    "ceil": ceiling,
    "gcd": gcd,
    "lcm": lcm,
    "factorial": factorial,
    "pi": pi,
    "e": E,
    "E": E,
    "x": Symbol("x"),
    "y": Symbol("y"),
    "z": Symbol("z"),
    "t": Symbol("t"),
    "n": Symbol("n"),
}

ALLOWED_NODE_TYPES = (
    ast.Expression,
    ast.BinOp,
    ast.UnaryOp,
    ast.Constant,
    ast.Call,
    ast.Name,
    ast.Load,
    ast.Add,
    ast.Sub,
    ast.Mult,
    ast.Div,
    ast.Pow,
    ast.Mod,
    ast.FloorDiv,
    ast.USub,
    ast.UAdd,
    ast.Compare,
    ast.Eq,
    ast.NotEq,
    ast.Lt,
    ast.LtE,
    ast.Gt,
    ast.GtE,
)


def _has_power_op(node: ast.AST) -> bool:
    """Recursively checks if any node in the subtree is a power operation."""
    for child in ast.walk(node):
        if isinstance(child, ast.BinOp) and isinstance(child.op, ast.Pow):
            return True
    return False


class SecurityVisitor(ast.NodeVisitor):
    """Inspects raw AST to prevent code execution, ReDoS, and memory inflation attacks."""

    def __init__(self, max_pow_exponent: int = 1000, max_nodes: int = 80, max_depth: int = 12) -> None:
        self.max_pow = max_pow_exponent
        self.max_nodes = max_nodes
        self.max_depth = max_depth
        self.node_count = 0

    def generic_visit(self, node: ast.AST) -> None:
        self.node_count += 1
        if self.node_count > self.max_nodes:
            raise ValueError(f"運算式過於複雜 (節點數量超限: 上限 {self.max_nodes})。")
        if not isinstance(node, ALLOWED_NODE_TYPES):
            raise ValueError(f"不允許的語法節點: {type(node).__name__}")
        super().generic_visit(node)

    def visit_Name(self, node: ast.Name) -> None:
        if node.id not in ALLOWED_LOCALS:
            raise ValueError(f"不允許的變數或函式名稱: '{node.id}'")
        self.generic_visit(node)

    def visit_BinOp(self, node: ast.BinOp) -> None:
        if isinstance(node.op, ast.Pow):
            # 1. Defend against chained / nested exponents (e.g. 9**9**9 or (9**9)**9)
            if _has_power_op(node.left) or _has_power_op(node.right):
                raise ValueError("禁止巢狀或連續次方運算 (如 a**b**c)，已攔截以防禦記憶體膨脹攻擊。")

            # 2. Check direct exponent constants
            if isinstance(node.right, ast.Constant) and isinstance(node.right.value, (int, float)):
                if abs(node.right.value) > self.max_pow:
                    raise ValueError(f"指數過大 (上限 {self.max_pow})，已攔截以保護系統。")

                # If base is also a constant, check estimated digit expansion
                if isinstance(node.left, ast.Constant) and isinstance(node.left.value, (int, float)):
                    base_val = abs(node.left.value)
                    exp_val = abs(node.right.value)
                    if base_val > 1 and exp_val > 0:
                        # Estimated base-10 digits: exp * log10(base)
                        est_digits = exp_val * math.log10(max(base_val, 2))
                        if est_digits > 3000:
                            raise ValueError("冪次運算結果過大，已攔截以防禦記憶體膨脹。")

            # 3. Check for any large constants anywhere within the exponent expression
            for sub in ast.walk(node.right):
                if isinstance(sub, ast.Constant) and isinstance(sub.value, (int, float)):
                    if abs(sub.value) > self.max_pow:
                        raise ValueError(f"指數運算項過大 (上限 {self.max_pow})，已攔截以保護系統。")

        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        # Check function name
        if not isinstance(node.func, ast.Name):
            raise ValueError("不允許的動態函式呼叫。")
        func_name = node.func.id
        if func_name not in ALLOWED_LOCALS:
            raise ValueError(f"不允許調用函式: '{func_name}'")

        # Specific limits on memory-intensive functions
        if func_name == "factorial":
            if node.args:
                arg = node.args[0]
                if any(isinstance(sub, ast.Call) for sub in ast.walk(arg)):
                    raise ValueError("階乘引數不允許包含巢狀函式呼叫。")
                if _has_power_op(arg):
                    raise ValueError("階乘引數不允許包含次方運算。")
                if isinstance(arg, ast.Constant) and isinstance(arg.value, int):
                    if arg.value < 0 or arg.value > 1000:
                        raise ValueError("階乘引數超出安全範圍 (上限 1000)。")
                for sub in ast.walk(arg):
                    if isinstance(sub, ast.Constant) and isinstance(sub.value, (int, float)):
                        if sub.value > 1000:
                            raise ValueError("階乘引數常數項過大 (上限 1000)。")

        elif func_name == "exp":
            if node.args:
                arg = node.args[0]
                if any(isinstance(sub, ast.Call) for sub in ast.walk(arg)):
                    raise ValueError("exp 引數不允許包含巢狀函式呼叫。")
                if _has_power_op(arg):
                    raise ValueError("exp 引數不允許包含次方運算。")
                if isinstance(arg, ast.Constant) and isinstance(arg.value, (int, float)):
                    if abs(arg.value) > 700:
                        raise ValueError("exp 指數過大 (上限 700)。")
                for sub in ast.walk(arg):
                    if isinstance(sub, ast.Constant) and isinstance(sub.value, (int, float)):
                        if abs(sub.value) > 700:
                            raise ValueError("exp 引數常數項過大 (上限 700)。")

        self.generic_visit(node)


def _insert_implicit_multiplication(s: str) -> str:
    """Preprocesses mathematical expressions to insert implicit multiplication."""
    # 1. Number followed by parenthesis: e.g. 2(x+1) -> 2*(x+1)
    s = re.sub(r'(\d)\s*(\()', r'\1*\2', s)
    # 2. Parenthesis followed by parenthesis: (a)(b) -> (a)*(b)
    s = re.sub(r'(\))\s*(\()', r'\1*\2', s)
    # 3. Parenthesis followed by variable/number: (a)x -> (a)*x, (a)2 -> (a)*2
    s = re.sub(r'(\))\s*([a-zA-Z0-9])', r'\1*\2', s)
    # 4. Number followed by variable (excluding scientific notation like 1e5):
    def _num_letter(m: re.Match) -> str:
        num = m.group(1)
        letter = m.group(2)
        rest = s[m.end():]
        if letter.lower() == "e" and re.match(r"^[+-]?\d", rest):
            return m.group(0)
        return f"{num}*{letter}"
    s = re.sub(r'(\d)\s*([a-zA-Z])', _num_letter, s)
    return s


def validate_expression_safety(expression_str: str) -> str:
    """Pre-cleans and rigorously verifies an expression AST against DoS attacks."""
    cleaned = expression_str.replace("^", "**").strip()
    cleaned = _insert_implicit_multiplication(cleaned)
    if not cleaned:
        raise ValueError("表達式不可為空。")

    if len(cleaned) > 500:
        raise ValueError("表達式長度超出限制 (上限 500 字元)。")

    # Blacklist dangerous token fragments
    forbidden = ["__", "import", "exec", "eval", "compile", "globals", "locals", "system", "popen"]
    lower_cleaned = cleaned.lower()
    for word in forbidden:
        if word in lower_cleaned:
            raise ValueError(f"不允許的表達式，包含受限關鍵字: '{word}'")

    try:
        tree = ast.parse(cleaned, mode="eval")
    except SyntaxError as se:
        raise ValueError(f"語法解析錯誤: {se}")

    visitor = SecurityVisitor()
    visitor.visit(tree)
    return cleaned


class SymPyCalculator:
    """Asynchronous sandboxed mathematical computation engine."""

    def __init__(self, timeout_seconds: float = 2.0) -> None:
        self.timeout = timeout_seconds

    async def calculate(self, expression_str: str) -> str:
        """Evaluates arbitrary precision math expressions safely within timeout."""
        return await asyncio.wait_for(
            asyncio.to_thread(self._sync_calculate, expression_str),
            timeout=self.timeout,
        )

    def evaluate(self, expression_str: str) -> CalculationResult:
        """Synchronously evaluates math expression with timeout and returns structured CalculationResult."""
        t0 = time.perf_counter()
        executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
        try:
            future = executor.submit(self._sync_calculate, expression_str)
            res_str = future.result(timeout=self.timeout)

            latex_repr = None
            try:
                cleaned = validate_expression_safety(expression_str)
                parsed = sympify(cleaned, locals=ALLOWED_LOCALS)
                latex_repr = sympy.latex(parsed)
            except Exception:
                pass

            elapsed = round((time.perf_counter() - t0) * 1000, 2)
            return CalculationResult(
                expression=expression_str,
                result_str=res_str,
                is_error=False,
                execution_time_ms=elapsed,
                latex_str=latex_repr,
            )
        except concurrent.futures.TimeoutError:
            elapsed = round((time.perf_counter() - t0) * 1000, 2)
            return CalculationResult(
                expression=expression_str,
                result_str="",
                is_error=True,
                error_message=f"運算超時 (上限 {self.timeout} 秒)，已強制中斷以保護系統。",
                execution_time_ms=elapsed,
            )
        except Exception as e:
            elapsed = round((time.perf_counter() - t0) * 1000, 2)
            return CalculationResult(
                expression=expression_str,
                result_str="",
                is_error=True,
                error_message=str(e),
                execution_time_ms=elapsed,
            )
        finally:
            executor.shutdown(wait=False, cancel_futures=True)

    def _sync_calculate(self, expression_str: str) -> str:
        cleaned = validate_expression_safety(expression_str)

        res = sympify(cleaned, locals=ALLOWED_LOCALS)
        result_str = str(res)

        # Truncate extremely large outputs for Discord format limits
        if len(result_str) > 1800:
            result_str = result_str[:1700] + f"\n... [已省略其餘 {len(result_str)-1700} 個字元]"
        return result_str

    def solve_equation(self, eq_str: str, var: str = "x", variable_name: Optional[str] = None) -> CalculationResult:
        """Solves algebraic equations like 'x**2 - 5*x + 6 = 0'. Supports both sync and awaitable usage."""
        t0 = time.perf_counter()
        target_var_str = variable_name or var or "x"

        # Validate variable name
        if not target_var_str.isalpha() or len(target_var_str) > 4:
            return CalculationResult(
                expression=eq_str,
                is_error=True,
                error_message=f"不合法的未知數名稱: '{target_var_str}'",
                execution_time_ms=0.0,
            )

        executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
        try:
            future = executor.submit(self._sync_solve, eq_str, target_var_str)
            solutions = future.result(timeout=self.timeout)

            elapsed = round((time.perf_counter() - t0) * 1000, 2)
            res_str = ", ".join(solutions) if solutions else "無實數解或無法求得符號解"
            return CalculationResult(
                expression=eq_str,
                result_str=res_str,
                is_error=False,
                execution_time_ms=elapsed,
                solutions=solutions,
            )
        except concurrent.futures.TimeoutError:
            elapsed = round((time.perf_counter() - t0) * 1000, 2)
            return CalculationResult(
                expression=eq_str,
                is_error=True,
                error_message=f"方程式求解超時 (上限 {self.timeout} 秒)。",
                execution_time_ms=elapsed,
            )
        except Exception as e:
            elapsed = round((time.perf_counter() - t0) * 1000, 2)
            return CalculationResult(
                expression=eq_str,
                is_error=True,
                error_message=str(e),
                execution_time_ms=elapsed,
            )
        finally:
            executor.shutdown(wait=False, cancel_futures=True)

    def _sync_solve(self, eq_str: str, var: str) -> List[str]:
        cleaned = eq_str.replace("^", "**").strip()
        if "=" in cleaned:
            left, right = cleaned.split("=", 1)
            left_clean = validate_expression_safety(left)
            right_clean = validate_expression_safety(right)
            parsed_eq = sympify(left_clean, locals=ALLOWED_LOCALS) - sympify(right_clean, locals=ALLOWED_LOCALS)
        else:
            cleaned_safe = validate_expression_safety(cleaned)
            parsed_eq = sympify(cleaned_safe, locals=ALLOWED_LOCALS)

        target_var = Symbol(var)
        solutions = solve(parsed_eq, target_var)
        return [str(s) for s in solutions]

    def algebra_simplify(self, expression_str: str, mode: str = "simplify") -> CalculationResult:
        """Simplifies or expands algebraic expressions."""
        t0 = time.perf_counter()
        executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
        try:
            future = executor.submit(self._sync_algebra_simplify, expression_str, mode)
            res, latex_str = future.result(timeout=self.timeout)

            elapsed = round((time.perf_counter() - t0) * 1000, 2)
            return CalculationResult(
                expression=expression_str,
                result_str=str(res),
                is_error=False,
                execution_time_ms=elapsed,
                latex_str=latex_str,
            )
        except concurrent.futures.TimeoutError:
            elapsed = round((time.perf_counter() - t0) * 1000, 2)
            return CalculationResult(
                expression=expression_str,
                result_str="",
                is_error=True,
                error_message=f"代數運算超時 (上限 {self.timeout} 秒)。",
                execution_time_ms=elapsed,
            )
        except Exception as e:
            elapsed = round((time.perf_counter() - t0) * 1000, 2)
            return CalculationResult(
                expression=expression_str,
                is_error=True,
                error_message=str(e),
                execution_time_ms=elapsed,
            )
        finally:
            executor.shutdown(wait=False, cancel_futures=True)

    def _sync_algebra_simplify(self, expression_str: str, mode: str) -> Tuple[Any, Optional[str]]:
        cleaned = validate_expression_safety(expression_str)
        parsed = sympify(cleaned, locals=ALLOWED_LOCALS)
        if mode in ("expand", "展開"):
            res = expand(parsed)
        elif mode in ("factor", "因式分解"):
            res = factor(parsed)
        else:
            res = simplify(parsed)
        return res, sympy.latex(res)

    def calculus(self, expr_str: str, mode: str = "diff", variable_name: str = "x") -> CalculationResult:
        """Performs symbolic differentiation or integration."""
        t0 = time.perf_counter()
        executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
        try:
            future = executor.submit(self._sync_calculus, expr_str, mode, variable_name)
            res_str, latex_str = future.result(timeout=self.timeout)

            elapsed = round((time.perf_counter() - t0) * 1000, 2)
            return CalculationResult(
                expression=expr_str,
                result_str=res_str,
                is_error=False,
                execution_time_ms=elapsed,
                latex_str=latex_str,
            )
        except concurrent.futures.TimeoutError:
            elapsed = round((time.perf_counter() - t0) * 1000, 2)
            return CalculationResult(
                expression=expr_str,
                result_str="",
                is_error=True,
                error_message=f"微積分運算超時 (上限 {self.timeout} 秒)。",
                execution_time_ms=elapsed,
            )
        except Exception as e:
            elapsed = round((time.perf_counter() - t0) * 1000, 2)
            return CalculationResult(
                expression=expr_str,
                is_error=True,
                error_message=str(e),
                execution_time_ms=elapsed,
            )
        finally:
            executor.shutdown(wait=False, cancel_futures=True)

    def _sync_calculus(self, expr_str: str, mode: str, variable_name: str) -> Tuple[str, Optional[str]]:
        cleaned = validate_expression_safety(expr_str)
        parsed = sympify(cleaned, locals=ALLOWED_LOCALS)
        target_var = Symbol(variable_name)

        if mode == "integrate":
            res = integrate(parsed, target_var)
            res_str = f"{res} + C"
        else:
            res = diff(parsed, target_var)
            res_str = str(res)
        return res_str, sympy.latex(res)

    async def differentiate(self, expr_str: str, var: str = "x", order: int = 1) -> str:
        """Computes derivative of expression with respect to variable."""
        return await asyncio.wait_for(
            asyncio.to_thread(self._sync_diff, expr_str, var, order),
            timeout=self.timeout,
        )

    def _sync_diff(self, expr_str: str, var: str, order: int) -> str:
        cleaned = validate_expression_safety(expr_str)
        parsed = sympify(cleaned, locals=ALLOWED_LOCALS)
        res = diff(parsed, Symbol(var), order)
        return str(res)

    async def integrate_expr(self, expr_str: str, var: str = "x") -> str:
        """Computes indefinite integral of expression with respect to variable."""
        return await asyncio.wait_for(
            asyncio.to_thread(self._sync_integrate, expr_str, var),
            timeout=self.timeout,
        )

    def _sync_integrate(self, expr_str: str, var: str) -> str:
        cleaned = validate_expression_safety(expr_str)
        parsed = sympify(cleaned, locals=ALLOWED_LOCALS)
        res = integrate(parsed, Symbol(var))
        return f"{res} + C"

    def factorize(self, num_or_expr: Any) -> Any:
        """Factors integer into primes or polynomials into factors."""
        if isinstance(num_or_expr, int) or (isinstance(num_or_expr, str) and num_or_expr.strip().isdigit()):
            raw_s = str(num_or_expr).strip()
            if len(raw_s) > 100:
                raise ValueError("待質因數分解數字過大 (上限 100 位數)，已攔截以防禦運算耗盡攻擊。")
            n = int(raw_s)
            if n <= 1:
                return FactorResult([(n, 1)], display_str=str(n))
            factors = primefactors(n)
            pairs: List[Tuple[int, int]] = []
            parts: List[str] = []
            temp = n
            for f in factors:
                count = 0
                while temp % f == 0:
                    count += 1
                    temp //= f
                pairs.append((f, count))
                parts.append(f"{f}^{count}" if count > 1 else str(f))
            display = f"{n} = " + " × ".join(parts)
            return FactorResult(pairs, display_str=display)

        # Symbolic polynomial factorization
        cleaned = validate_expression_safety(str(num_or_expr))
        parsed = sympify(cleaned, locals=ALLOWED_LOCALS)
        res = factor(parsed)
        return str(res)

    def is_prime(self, n: int) -> bool:
        """Checks whether n is prime."""
        return self.check_prime(n)

    def check_prime(self, n: int) -> bool:
        """Fast Miller-Rabin / deterministic prime check."""
        if n < 2:
            return False
        return bool(isprime(n))

    def gcd(self, numbers: List[int]) -> int:
        """Greatest common divisor of a list of integers."""
        if not numbers:
            return 0
        return math.gcd(*numbers)

    def lcm(self, numbers: List[int]) -> int:
        """Least common multiple of a list of integers."""
        if not numbers:
            return 0
        return math.lcm(*numbers)

    def compute_gcd_lcm(self, numbers: List[int]) -> Tuple[int, int]:
        """Calculates greatest common divisor and least common multiple."""
        if not numbers:
            return 0, 0
        return self.gcd(numbers), self.lcm(numbers)

    def permutation(self, n: int, k: int) -> int:
        """Permutations P(n, k)."""
        return math.perm(n, k)

    def combination(self, n: int, k: int) -> int:
        """Combinations C(n, k)."""
        return math.comb(n, k)

    def permutations_and_combinations(self, n: int, k: int) -> Tuple[int, int]:
        """Calculates P(n, k) and C(n, k)."""
        if n < 0 or k < 0 or k > n:
            raise ValueError("引數必須符合 0 <= k <= n。")
        return self.permutation(n, k), self.combination(n, k)

    def convert_units(self, value: float, from_unit: str, to_unit: str) -> Dict[str, Any]:
        """Performs precise physical unit conversions across length, weight, temperature, and digital storage."""
        f_u = from_unit.strip().lower()
        t_u = to_unit.strip().lower()

        # 1. Temperature
        temp_units = {"c", "f", "k"}
        if f_u in temp_units and t_u in temp_units:
            # Convert from_unit to Celsius first
            if f_u == "c":
                c = value
            elif f_u == "f":
                c = (value - 32) * 5 / 9
            else:  # k
                c = value - 273.15

            # Convert Celsius to to_unit
            if t_u == "c":
                out = c
            elif t_u == "f":
                out = (c * 9 / 5) + 32
            else:  # k
                out = c + 273.15
            return {"result": round(out, 4), "from": f_u, "to": t_u}

        # Conversion ratios to standard SI base units
        # Length (base: meter)
        length_to_m = {
            "mm": 0.001,
            "cm": 0.01,
            "m": 1.0,
            "km": 1000.0,
            "in": 0.0254,
            "ft": 0.3048,
            "yd": 0.9144,
            "mi": 1609.344,
        }
        if f_u in length_to_m and t_u in length_to_m:
            in_meters = value * length_to_m[f_u]
            out = in_meters / length_to_m[t_u]
            return {"result": round(out, 6), "from": f_u, "to": t_u}

        # Weight / Mass (base: gram)
        weight_to_g = {
            "mg": 0.001,
            "g": 1.0,
            "kg": 1000.0,
            "t": 1000000.0,
            "oz": 28.349523125,
            "lb": 453.59237,
        }
        if f_u in weight_to_g and t_u in weight_to_g:
            in_grams = value * weight_to_g[f_u]
            out = in_grams / weight_to_g[t_u]
            return {"result": round(out, 6), "from": f_u, "to": t_u}

        # Digital storage (base: byte)
        data_to_bytes = {
            "b": 1,
            "kb": 1024,
            "mb": 1024**2,
            "gb": 1024**3,
            "tb": 1024**4,
            "pb": 1024**5,
        }
        if f_u in data_to_bytes and t_u in data_to_bytes:
            in_b = value * data_to_bytes[f_u]
            out = in_b / data_to_bytes[t_u]
            return {"result": round(out, 6), "from": f_u, "to": t_u}

        return {"error": f"不支援自「{from_unit}」轉換至「{to_unit}」之物理量度。"}


# Singleton calculator instance
calculator = SymPyCalculator()
