"""Resolve execution-plan references against saved tool observations."""

from __future__ import annotations


class BindingResolutionError(ValueError):
    """Raised when an execution-plan binding cannot be resolved."""


def resolve_value(value, scope):
    """Resolve binding strings recursively while preserving literal values."""
    if isinstance(value, dict):
        return {key: resolve_value(item, scope) for key, item in value.items()}
    if isinstance(value, list):
        return [resolve_value(item, scope) for item in value]
    if not isinstance(value, str) or not value.startswith("$"):
        return value

    path = value[1:].split(".")
    root = path[0]
    if root not in scope:
        raise BindingResolutionError(f"Unknown binding root: ${root}")

    current = scope[root]
    for segment in path[1:]:
        if isinstance(current, dict) and segment in current:
            current = current[segment]
            continue
        raise BindingResolutionError(
            f"Cannot resolve binding {value}: missing segment {segment}"
        )
    return current
