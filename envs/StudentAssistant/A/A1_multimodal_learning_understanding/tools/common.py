"""Internal helpers shared by A1 tool modules."""

from __future__ import annotations

import hashlib
import re
import unicodedata
from pathlib import Path
from typing import Any


def audit(conn, event: str, entity_id: str | None, detail: str) -> None:
    conn.execute(
        "INSERT INTO audit_log (event, entity_id, detail) VALUES (?, ?, ?)",
        (event, entity_id, detail),
    )


def hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return f"sha256:{digest.hexdigest()}"


def canonicalize_answer(value: Any) -> Any:
    if isinstance(value, str):
        value = unicodedata.normalize("NFKC", value)
        return "".join(value.split()).upper()
    if isinstance(value, list):
        return [canonicalize_answer(item) for item in value]
    if isinstance(value, dict):
        return {key: canonicalize_answer(item) for key, item in value.items()}
    return value


_CHOICE_RE = re.compile(r"(?<![A-Z])([A-D]{1,4})(?![A-Z])")
_COUNT_RE = re.compile(r"(?:共|有|選|选)\D*(\d+)\D*(?:个|項|项)?")


def _choice_answer_signature(value: str) -> tuple[str, int | None] | None:
    """Extract a choice token from plain answers with optional explanations."""
    normalized = unicodedata.normalize("NFKC", value).upper()
    compact = "".join(normalized.split())
    candidates = _CHOICE_RE.findall(compact)
    if not candidates:
        return None
    # Prefer a token at the beginning or immediately after an answer marker.
    choice = candidates[0]
    for marker in ("答案", "ANSWER", "选项", "選項"):
        index = compact.find(marker)
        if index >= 0:
            match = _CHOICE_RE.search(compact[index + len(marker):])
            if match:
                choice = match.group(1)
                break
    count_match = _COUNT_RE.search(compact)
    count = int(count_match.group(1)) if count_match else None
    return choice, count


def _choice_alias_is_safe(value: str, choice: str) -> bool:
    """Do not collapse a multi-part mathematical answer to its first letter."""
    normalized = unicodedata.normalize("NFKC", value).upper()
    compact = "".join(normalized.split())
    start = compact.find(choice)
    if start < 0:
        return False
    remainder = compact[start + len(choice):]
    # Explanatory parentheticals such as ``B（①正确，②错误）`` are safe.
    remainder = re.sub(r"\([^()]*\)", "", remainder)
    remainder = re.sub(r"（[^（）]*）", "", remainder)
    remainder = remainder.strip("：:，,。.;；")
    if not remainder:
        return True
    return not bool(re.search(r"[=<>+\-*/]|[0-9]", remainder))


def answers_equivalent(actual: Any, expected: Any) -> bool:
    """Compare exact values, then conservative multiple-choice aliases."""
    if canonicalize_answer(actual) == canonicalize_answer(expected):
        return True
    if not isinstance(actual, str) or not isinstance(expected, str):
        return False

    actual_signature = _choice_answer_signature(actual)
    expected_signature = _choice_answer_signature(expected)
    if actual_signature is None or expected_signature is None:
        return False
    actual_choice, actual_count = actual_signature
    expected_choice, expected_count = expected_signature
    if actual_choice != expected_choice:
        return False
    if not _choice_alias_is_safe(expected, expected_choice):
        return False
    if (
        actual_count is not None
        and expected_count is not None
        and actual_count != expected_count
    ):
        return False
    return True
