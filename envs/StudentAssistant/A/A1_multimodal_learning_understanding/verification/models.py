"""Uniform result for deterministic answer comparison."""


def result(status, method, *, parts=None, diagnostics=None):
    return {
        "status": status,
        "score": 1.0 if status == "correct" else 0.0 if status == "incorrect" else None,
        "match_method": method,
        "needs_review": status in {"needs_review", "invalid_reference"},
        "part_results": parts or [],
        "missing_parts": [],
        "diagnostics": diagnostics or [],
    }
