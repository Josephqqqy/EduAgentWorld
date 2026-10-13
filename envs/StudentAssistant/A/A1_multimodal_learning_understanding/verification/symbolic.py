"""Restricted mathematical expression conversion; no eval or parse_expr."""

import ast
import re

try:
    import sympy as sp
except ImportError:
    sp = None


class UnsupportedMath(ValueError):
    pass


def _prepare(text):
    text = str(text).strip()
    if len(text) > 180:
        raise UnsupportedMath("expression too long")
    slash = chr(92)
    text = re.sub(re.escape(slash) + r"frac\s*\{([^{}]+)\}\s*\{([^{}]+)\}",
                  r"(\1)/(\2)", text)
    text = re.sub(re.escape(slash) + r"sqrt\s*\{([^{}]+)\}",
                  r"sqrt(\1)", text)
    text = text.replace(slash + "pi", "pi").replace("\u03c0", "pi")
    text = re.sub(r"\u221b\s*(\d+)", r"cbrt(\1)", text)
    text = re.sub(r"\u221a\s*(\d+)", r"sqrt(\1)", text)
    text = text.replace("\u00d7", "*").replace("\u2212", "-").replace("^", "**")
    text = re.sub(r"(?<=\d)(?=[A-Za-z(])", "*", text)
    text = re.sub(r"(?<=\))(?=[A-Za-z(])", "*", text)
    return text


def parse_math(text):
    if sp is None:
        raise UnsupportedMath("SymPy is not installed")
    text = _prepare(text)
    if not re.fullmatch(r"[A-Za-z0-9_+\-*/()., \t]+", text):
        raise UnsupportedMath("unsupported characters")
    try:
        node = ast.parse(text, mode="eval")
    except (SyntaxError, ValueError) as exc:
        raise UnsupportedMath("invalid expression") from exc
    if sum(1 for _ in ast.walk(node)) > 60:
        raise UnsupportedMath("expression too complex")
    symbols = {}

    def convert(item, depth=0):
        if depth > 18:
            raise UnsupportedMath("expression too deep")
        if isinstance(item, ast.Constant) and type(item.value) in (int, float):
            if abs(item.value) > 1000000:
                raise UnsupportedMath("literal too large")
            return sp.Rational(str(item.value))
        if isinstance(item, ast.Name):
            if item.id in {"pi", "PI"}:
                return sp.pi
            if item.id in {"E", "e"}:
                return sp.E
            if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,12}", item.id):
                raise UnsupportedMath("invalid symbol")
            if len(symbols) >= 3 and item.id not in symbols:
                raise UnsupportedMath("too many symbols")
            return symbols.setdefault(item.id, sp.Symbol(item.id, real=True))
        if isinstance(item, ast.UnaryOp) and type(item.op) in (ast.UAdd, ast.USub):
            value = convert(item.operand, depth + 1)
            return value if isinstance(item.op, ast.UAdd) else -value
        if isinstance(item, ast.BinOp) and type(item.op) in (
            ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Pow
        ):
            if isinstance(item.op, ast.Pow) and not (
                isinstance(item.right, ast.Constant)
                and type(item.right.value) in (int, float)
                and abs(item.right.value) <= 12
            ):
                raise UnsupportedMath("unsupported exponent")
            left, right = convert(item.left, depth + 1), convert(item.right, depth + 1)
            if isinstance(item.op, ast.Add):
                return left + right
            if isinstance(item.op, ast.Sub):
                return left - right
            if isinstance(item.op, ast.Mult):
                return left * right
            if isinstance(item.op, ast.Div):
                return left / right
            if right.is_number is not True or abs(float(right)) > 12:
                raise UnsupportedMath("power outside supported range")
            return left ** right
        if isinstance(item, ast.Call) and isinstance(item.func, ast.Name):
            if item.keywords or len(item.args) != 1:
                raise UnsupportedMath("invalid function call")
            func = {"sqrt": sp.sqrt, "cbrt": sp.cbrt, "sin": sp.sin,
                    "cos": sp.cos, "exp": sp.exp, "log": sp.log, "ln": sp.log}.get(item.func.id)
            if func is None:
                raise UnsupportedMath("unsupported function")
            return func(convert(item.args[0], depth + 1))
        raise UnsupportedMath("unsupported syntax")

    return convert(node.body)


def equivalent(actual, expected):
    left, right = parse_math(actual), parse_math(expected)
    difference = sp.simplify(left - right)
    if difference == 0 and not (left.free_symbols or right.free_symbols):
        return True
    if difference.is_zero is False and not difference.free_symbols:
        return False
    return None
