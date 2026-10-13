"""Convert supported one-variable intervals and inequalities to SymPy sets."""

import re

from .symbolic import UnsupportedMath, parse_math, sp


def parse_set(text, variable):
    if sp is None:
        raise UnsupportedMath("SymPy is not installed")
    text = str(text).strip().replace("\u221e", "infinity")
    text = text.replace("\u2264", "<=").replace("\u2265", ">=").replace("\u2208", "in")
    match = re.fullmatch(
        rf"(?:{re.escape(variable)}\s*in\s*)?([\[(])\s*([^,]+)\s*,\s*([^,]+?)\s*([\])])",
        text,
    )
    if match:
        left_bracket, low, high, right_bracket = match.groups()

        def endpoint(value):
            value = value.strip().lower()
            if value in {"-infinity", "-inf", "-oo"}:
                return -sp.oo
            if value in {"+infinity", "infinity", "+inf", "inf", "oo", "+oo"}:
                return sp.oo
            return parse_math(value)

        return sp.Interval(endpoint(low), endpoint(high),
                           left_open=left_bracket == "(",
                           right_open=right_bracket == ")")
    chained = re.fullmatch(
        rf"(.+?)\s*(<=|<)\s*{re.escape(variable)}\s*(<=|<)\s*(.+)", text
    )
    if chained:
        low, left_op, right_op, high = chained.groups()
        return sp.Interval(parse_math(low), parse_math(high),
                           left_open=left_op == "<", right_open=right_op == "<")
    single = re.fullmatch(rf"{re.escape(variable)}\s*(<=|>=|<|>)\s*(.+)", text)
    if single:
        op, bound = single.groups()
        value = parse_math(bound)
        if op.startswith(">"):
            return sp.Interval(value, sp.oo, left_open=op == ">")
        return sp.Interval(-sp.oo, value, right_open=op == "<")
    raise UnsupportedMath("unsupported interval")


def equivalent(actual, expected, variable):
    return parse_set(actual, variable) == parse_set(expected, variable)
