"""Weighted tool-dependency graph and AgentWorld-style random walks."""

from __future__ import annotations

import random
from dataclasses import dataclass


PUBLIC_TOOL_NAMES = (
    "upload_artifact",
    "get_artifact",
    "list_artifact_regions",
    "recognize_content",
    "extract_editable_text",
    "assess_content_completeness",
    "get_problem_context",
    "get_artifact_problem_contexts",
    "analyze_diagram",
    "analyze_problem_knowledge",
    "submit_solution",
)

EDGE_WEIGHTS = {
    "independent": 1,
    "weak": 2,
    "strong": 3,
}


@dataclass(frozen=True)
class ToolGraph:
    nodes: tuple[str, ...]
    edges: dict[tuple[str, str], dict[str, object]]

    def edge(self, source: str, target: str) -> dict[str, object]:
        try:
            return self.edges[(source, target)]
        except KeyError as exc:
            raise LookupError(f"Unknown tool edge: {source} -> {target}") from exc

    def successors(self, source: str) -> list[str]:
        if source not in self.nodes:
            raise LookupError(f"Unknown tool node: {source}")
        return [target for target in self.nodes if target != source]


def _set_edge(edges, source, target, kind):
    edges[(source, target)] = {
        "kind": kind,
        "weight": EDGE_WEIGHTS[kind],
    }


def build_tool_graph() -> ToolGraph:
    """Build a fully connected graph with explicit dependency overrides."""
    nodes = PUBLIC_TOOL_NAMES
    edges = {}
    for source in nodes:
        for target in nodes:
            if source != target:
                _set_edge(edges, source, target, "independent")

    strong_edges = {
        ("upload_artifact", "get_artifact"),
        ("upload_artifact", "list_artifact_regions"),
        ("upload_artifact", "get_artifact_problem_contexts"),
        ("list_artifact_regions", "recognize_content"),
        ("list_artifact_regions", "extract_editable_text"),
        ("list_artifact_regions", "assess_content_completeness"),
        ("list_artifact_regions", "get_problem_context"),
        ("list_artifact_regions", "analyze_diagram"),
        ("list_artifact_regions", "analyze_problem_knowledge"),
        ("list_artifact_regions", "submit_solution"),
        ("get_problem_context", "submit_solution"),
        ("get_artifact_problem_contexts", "submit_solution"),
    }
    for source, target in strong_edges:
        _set_edge(edges, source, target, "strong")

    weak_pairs = {
        ("recognize_content", "extract_editable_text"),
        ("recognize_content", "assess_content_completeness"),
        ("recognize_content", "get_problem_context"),
        ("recognize_content", "analyze_diagram"),
        ("recognize_content", "analyze_problem_knowledge"),
        ("extract_editable_text", "assess_content_completeness"),
        ("get_problem_context", "analyze_diagram"),
        ("get_problem_context", "analyze_problem_knowledge"),
        ("analyze_diagram", "analyze_problem_knowledge"),
    }
    for left, right in weak_pairs:
        _set_edge(edges, left, right, "weak")
        _set_edge(edges, right, left, "weak")

    return ToolGraph(nodes=nodes, edges=edges)


def random_walk(graph, length, rng=None, start=None):
    """Sample a weighted walk that may revisit tools through graph cycles."""
    if length < 1:
        raise ValueError("length must be positive")

    rng = rng or random.Random()
    current = start or "upload_artifact"
    if current not in graph.nodes:
        raise LookupError(f"Unknown start tool: {current}")

    sequence = [current]
    while len(sequence) < length:
        candidates = graph.successors(current)
        weights = [graph.edge(current, tool)["weight"] for tool in candidates]
        current = rng.choices(candidates, weights=weights, k=1)[0]
        sequence.append(current)
    return sequence
