"""Conservative layered dispatch; uncertainty never becomes a negative label."""

import re
import unicodedata

from . import interval, symbolic
from .models import result


def _choice(text):
    normalized = unicodedata.normalize("NFKC", str(text)).upper().strip()
    normalized = re.sub(r"^(?:\u7b54\u6848|\u9009|\u9009\u62e9|ANSWER)\s*[:\uff1a]?\s*", "", normalized)
    normalized = normalized.replace("\u3001", ",").replace("\uff0c", ",")
    match = re.match(r"^\(?\s*([A-D](?:\s*,\s*[A-D]){1,3}|[A-D]{1,4})\s*\)?", normalized)
    if not match:
        return None
    choice = "".join(sorted(set(match.group(1).replace(",", "").replace(" ", ""))))
    rest = normalized[match.end():].strip()
    if not rest:
        return choice
    # A leading explicit choice may be followed by its option value or a
    # redundant Chinese choice list, but not another conflicting choice.
    repeat = re.fullmatch(r"[\(\uff08]\s*\u9009\s*([A-D](?:\s*,\s*[A-D]){0,3})\s*[\)\uff09]", rest)
    if repeat:
        repeated = "".join(sorted(set(repeat.group(1).replace(",", "").replace(" ", ""))))
        return choice if repeated == choice else None
    if re.match(r"^[.\uff0e:：\s\$]", rest) or (normalized.startswith("(") and rest.startswith("$")):
        return choice
    return None


def _labeled_parts(text, parts):
    if not isinstance(text, str):
        return None
    labels = {"part_1": "1", "part_2": "2"}
    if any(not isinstance(part, dict) or part.get("part_id") not in labels for part in parts):
        return None
    markers = list(re.finditer(r"[\(\uff08]([12])[\)\uff09]", text))
    if not markers or len(markers) > len(parts) or [
        marker.group(1) for marker in markers
    ] != [labels[part["part_id"]] for part in parts[:len(markers)]] or text[:markers[0].start()].strip():
        return None
    values = {}
    for index, marker in enumerate(markers):
        end = markers[index + 1].start() if index + 1 < len(markers) else len(text)
        value = text[marker.end():end].strip(" \t\n;\uff1b\u3002")
        if not value:
            return None
        values[parts[index]["part_id"]] = value
    return values


def _typed(actual, expected, kind, variable=None):
    value = expected.get("value")
    if value is None or not isinstance(value, (str, int, float)):
        return result("invalid_reference", "schema", diagnostics=["missing value"])
    if kind in {"choice", "multiple_choice"}:
        left, right = _choice(actual), _choice(value)
        if right is None:
            return result("invalid_reference", "choice")
        if left is None:
            return result("needs_review", "choice")
        return result("correct" if left == right else "incorrect", "choice")
    if kind == "proof_conclusion":
        if isinstance(actual, str):
            normalized = actual.replace("\u2225", "parallel")
            reference = str(value).replace("\u2225", "parallel")
            if re.sub(r"\s+", "", normalized).casefold() == re.sub(r"\s+", "", reference).casefold():
                return result("correct", "proof_conclusion_literal")
        return result("needs_review", "proof_conclusion")
    if kind in {"numeric", "expression"}:
        text = str(actual).strip()
        if kind == "expression":
            text = text.strip(" \t\n;\uff1b\u3002$")
        if kind == "numeric":
            text = text.strip(" \t\n;\uff1b\u3002$")
        if kind == "numeric":
            unit = expected.get("unit")
            units = re.findall(r"(?<=\d)\s*(\u4eba|\u7c73|\u4e07\u5143|\u4e07|\u5143|\u5ea6|%)", text)
            if unit and units and units[-1] != unit:
                return result("incorrect", "unit")
            if unit:
                text = re.sub(rf"\s*{re.escape(unit)}\s*$", "", text)
        if "=" in text:
            text = text.rsplit("=", 1)[-1].strip()
        elif kind == "expression":
            text = re.sub(r"^.*?((?:-?\d+)\s*\()", r"\1", text)
        text = text.strip(" \t\n;\uff1b\u3002$")
        try:
            left, right = symbolic.parse_math(text), symbolic.parse_math(value)
            delta = symbolic.sp.simplify(left - right)
            if delta == 0 and not (left.free_symbols or right.free_symbols):
                return result("correct", "symbolic_equivalence")
            if delta.is_zero is False and not delta.free_symbols:
                tolerance = expected.get("absolute_tolerance", 0)
                if kind == "numeric" and tolerance:
                    status = "correct" if abs(float(delta)) <= float(tolerance) else "incorrect"
                    return result(status, "numeric_tolerance")
                return result("incorrect", "symbolic_equivalence")
        except (symbolic.UnsupportedMath, TypeError, ValueError, OverflowError):
            pass
        return result("needs_review", "symbolic")
    if kind in {"interval", "inequality"}:
        if not isinstance(variable, str) or not re.fullmatch(r"[A-Za-z]\w{0,12}", variable):
            return result("invalid_reference", "interval", diagnostics=["missing variable"])
        text = str(actual).strip()
        if "\u5373" in text:
            text = text.split("\u5373", 1)[0].strip().rstrip("(").strip()
        try:
            matched = interval.equivalent(text, str(value), variable)
            return result("correct" if matched else "incorrect", "set_equivalence")
        except (symbolic.UnsupportedMath, TypeError, ValueError):
            return result("needs_review", "interval")
    return result("needs_review", "unsupported_type")


def verify_answer(actual, expected, *, question_type=None):
    """Return a private deterministic judgment, not an Agent-visible tool result."""
    from tools.common import answers_equivalent, canonicalize_answer

    if canonicalize_answer(actual) == canonicalize_answer(expected):
        return result("correct", "legacy_rules")
    if isinstance(actual, str) and actual.strip().lower() == "incorrect":
        return result("incorrect", "invalid_answer_placeholder")
    if question_type in {"multiple_choice", "multiple_select"} and answers_equivalent(actual, expected):
        return result("correct", "legacy_rules")
    if isinstance(expected, dict) and "answer_type" in expected:
        kind = expected["answer_type"]
        if kind == "multipart":
            parts = expected.get("parts")
            if not isinstance(parts, list) or not parts:
                return result("invalid_reference", "multipart")
            if any(not isinstance(part, dict) or not part.get("part_id")
                   or "answer_type" not in part for part in parts):
                return result("invalid_reference", "multipart")
            if not isinstance(actual, dict):
                actual = _labeled_parts(actual, parts)
                if actual is None:
                    return result("needs_review", "multipart_extraction")
            outcomes, missing = [], []
            for part in parts:
                part_id = str(part.get("part_id", ""))
                if not part_id or "answer_type" not in part:
                    return result("invalid_reference", "multipart")
                if part_id not in actual:
                    if part.get("required", True):
                        missing.append(part_id)
                    continue
                verdict = verify_answer(actual[part_id], part, question_type=question_type)
                outcomes.append({"part_id": part_id, **verdict})
            states = {item["status"] for item in outcomes}
            status = ("invalid_reference" if "invalid_reference" in states else
                      "incorrect" if missing or "incorrect" in states else
                      "needs_review" if "needs_review" in states else "correct")
            output = result(status, "multipart", parts=outcomes)
            output["missing_parts"] = missing
            return output
        return _typed(actual, expected, kind, expected.get("variable"))
    if question_type in {"multiple_choice", "multiple_select"} and isinstance(expected, str):
        return _typed(actual, {"value": expected}, "choice")
    if isinstance(actual, str) and isinstance(expected, str):
        if question_type == "proof":
            return result("needs_review", "proof")
        extrema = r"\u6700\u5927\u503c\s*\$?\s*=?\s*(-?\d+)\s*\$?\s*[,，]\s*\u6700\u5c0f\u503c\s*\$?\s*=?\s*(-?\d+)\s*\$?[\u3002.]?"
        reference_extrema = re.fullmatch(extrema, expected.strip())
        if reference_extrema:
            submitted_extrema = re.fullmatch(extrema, actual.strip())
            if submitted_extrema:
                return result("correct" if submitted_extrema.groups() == reference_extrema.groups()
                              else "incorrect", "extrema_values")
            return result("needs_review", "extrema_values")
        if any(mark in expected for mark in ("\uff1b", ";", "\uff0c")):
            return result("needs_review", "legacy_composite")
        if expected.isdecimal():
            count = re.fullmatch(r"\s*(?:\u7ea6\s*)?(\d+)\s*\u4eba(?:\u9009\u62e9\u51fa\u79df\u8f66)?[\u3002.]?\s*", actual)
            if count:
                return result("correct" if count.group(1) == expected else "incorrect", "legacy_count")
        try:
            left = actual.rsplit("=", 1)[-1].strip()
            left = left.strip(" \t\n;\uff1b\u3002$")
            right = expected.rsplit("=", 1)[-1].strip()
            matched = symbolic.equivalent(left, right)
            if matched is not None:
                return result("correct" if matched else "incorrect", "legacy_symbolic")
        except (symbolic.UnsupportedMath, ValueError, TypeError):
            pass
        interval_reference = re.fullmatch(r"([A-Za-z])\s*(?:in|\u2208)\s*(.+)", expected)
        if interval_reference:
            variable, expected_set = interval_reference.groups()
            try:
                value = actual.split("\uff08\u5373", 1)[0].split("\u5373", 1)[0].strip().rstrip("(").strip()
                matched = interval.equivalent(value, expected_set, variable)
                return result("correct" if matched else "incorrect", "legacy_set")
            except (symbolic.UnsupportedMath, ValueError, TypeError):
                pass
    return result("needs_review", "unresolved")
