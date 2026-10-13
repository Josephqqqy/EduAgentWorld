"""Generate A1 tasks from weighted walks over the public tool graph."""

from __future__ import annotations

import json
import random

from .graph import build_tool_graph, random_walk


_CAPABILITY_TEXT = {
    "get_artifact": "\u786e\u8ba4\u5b66\u4e60\u6750\u6599\u7684\u57fa\u672c\u4fe1\u606f",
    "list_artifact_regions": "\u533a\u5206\u56fe\u7247\u4e2d\u5305\u542b\u7684\u5404\u9053\u9898\u76ee",
    "recognize_content": "\u8bc6\u522b\u9898\u76ee\u5185\u5bb9\u548c\u6570\u5b66\u8868\u8fbe\u5f0f",
    "extract_editable_text": "\u6574\u7406\u6210\u53ef\u7f16\u8f91\u7684\u6587\u672c",
    "assess_content_completeness": "\u5224\u65ad\u9898\u76ee\u5185\u5bb9\u662f\u5426\u5b8c\u6574\u5e76\u6307\u51fa\u7f3a\u5931\u90e8\u5206",
    "get_problem_context": "\u7ed3\u5408\u9898\u76ee\u7c7b\u578b\u548c\u4e0a\u4e0b\u6587\u8fdb\u884c\u7406\u89e3",
    "get_artifact_problem_contexts": "\u9010\u9898\u6574\u7406\u56fe\u7247\u4e2d\u7684\u5168\u90e8\u9898\u76ee",
    "analyze_diagram": "\u8bf4\u660e\u9898\u76ee\u4e2d\u6570\u5b66\u56fe\u5f62\u7684\u4f5c\u7528\u548c\u5df2\u77e5\u5173\u7cfb",
    "analyze_problem_knowledge": "\u5206\u6790\u6d89\u53ca\u7684\u77e5\u8bc6\u70b9",
    "submit_solution": "\u5206\u522b\u7ed9\u51fa\u7b54\u6848\u548c\u5fc5\u8981\u7684\u63a8\u7406\u8fc7\u7a0b",
}

_ARTIFACT_TOOLS = {
    "get_artifact",
    "list_artifact_regions",
    "get_artifact_problem_contexts",
}

_REGION_TOOLS = {
    "recognize_content",
    "extract_editable_text",
    "assess_content_completeness",
    "get_problem_context",
    "analyze_diagram",
    "analyze_problem_knowledge",
    "submit_solution",
}

_ANALYSIS_TOOLS = _REGION_TOOLS - {"submit_solution"}

_TOOL_ORDER = {
    "upload_artifact": 0,
    "get_artifact": 1,
    "get_artifact_problem_contexts": 1,
    "list_artifact_regions": 2,
    "recognize_content": 3,
    "extract_editable_text": 3,
    "assess_content_completeness": 3,
    "get_problem_context": 4,
    "analyze_diagram": 5,
    "analyze_problem_knowledge": 5,
    "submit_solution": 6,
}


def _select_fixture(conn, rng):
    candidates = conn.execute(
        "SELECT artifact_id, file_name FROM artifacts ORDER BY artifact_id"
    ).fetchall()
    if not candidates:
        raise ValueError("Cannot generate a task without an artifact fixture")
    return rng.choice(candidates)


def _instruction(sequence):
    actions = list(dict.fromkeys(
        _CAPABILITY_TEXT[tool]
        for tool in sequence
        if tool in _CAPABILITY_TEXT
    ))
    if not actions:
        return "\u8bf7\u5904\u7406\u6211\u4e0a\u4f20\u7684\u6570\u5b66\u5b66\u4e60\u6750\u6599\u3002"
    return "\u8bf7\u5904\u7406\u6211\u4e0a\u4f20\u7684\u6570\u5b66\u9898\u56fe\u7247\uff1a" + "\uff1b".join(actions) + "\u3002"


def _build_rubric(sequence):
    """Separate hard capabilities from interchangeable navigation paths."""
    unique = list(dict.fromkeys(sequence))
    required = []
    if "get_artifact" in unique:
        required.append("get_artifact")
    required.extend(tool for tool in unique if tool in _ANALYSIS_TOOLS)
    if "submit_solution" in unique:
        required.append("submit_solution")

    region_tools = [
        tool for tool in unique
        if tool in _ANALYSIS_TOOLS or tool == "submit_solution"
    ]
    needs_region_navigation = region_tools or any(
        tool in {"list_artifact_regions", "get_artifact_problem_contexts"}
        for tool in unique
    )
    if needs_region_navigation:
        acceptable_paths = [
            ["list_artifact_regions"],
            ["get_artifact_problem_contexts"],
        ]
    else:
        acceptable_paths = []

    submission_policy = (
        "required" if "submit_solution" in unique else "forbidden"
    )
    return {
        "required_tools": list(dict.fromkeys(required)),
        "acceptable_tool_paths": acceptable_paths,
        "submission_policy": submission_policy,
        "min_steps": len(set(required)) + bool(acceptable_paths),
        "answer_must_not_be_exposed": submission_policy == "forbidden",
    }


def refine_tool_sequence(sequence):
    """Add prerequisites and normalize executable dependency order."""
    requested = list(sequence)
    has_submission = "submit_solution" in requested
    non_submissions = [tool for tool in requested if tool != "submit_solution"]

    if not non_submissions:
        non_submissions = ["upload_artifact"]
    if "upload_artifact" not in non_submissions:
        non_submissions.insert(0, "upload_artifact")

    if any(tool in _REGION_TOOLS for tool in non_submissions):
        if "list_artifact_regions" not in non_submissions:
            non_submissions.append("list_artifact_regions")

    if has_submission and not any(
        tool in {"get_problem_context", "get_artifact_problem_contexts"}
        for tool in non_submissions
    ):
        non_submissions.append("get_problem_context")

    non_submissions.sort(key=lambda tool: _TOOL_ORDER.get(tool, 99))
    if has_submission:
        non_submissions.append("submit_solution")
    return non_submissions


def build_execution_plan(sequence, fixture_path):
    """Instantiate tool arguments with bindings to preceding observations."""
    plan = []
    tool_counts = {}
    recognition_modalities = ("ocr", "formula", "vision")
    submission_added = False

    for tool in sequence:
        if tool == "submit_solution":
            if submission_added:
                continue
            submission_added = True

        occurrence = tool_counts.get(tool, 0)
        tool_counts[tool] = occurrence + 1
        if tool == "upload_artifact":
            arguments = {
                "user_id": "student_task_user",
                "fixture_path": fixture_path,
            }
        elif tool in _ARTIFACT_TOOLS:
            arguments = {"artifact_id": "$upload.artifact_id"}
        elif tool == "recognize_content":
            arguments = {
                "region_id": "$item.region_id",
                "modality": recognition_modalities[
                    occurrence % len(recognition_modalities)
                ],
            }
        elif tool == "submit_solution":
            arguments = {
                "region_id": "$item.region_id",
                "final_answer": "$agent.final_answer",
                "reasoning": "$agent.reasoning",
            }
        else:
            arguments = {"region_id": "$item.region_id"}

        save_as = {
            "upload_artifact": "upload",
            "get_artifact": "artifact",
            "list_artifact_regions": "regions",
            "get_artifact_problem_contexts": "problems",
        }.get(tool, tool)
        call = {
            "call_id": f"call_{len(plan) + 1:03d}",
            "tool": tool,
            "arguments": arguments,
            "save_as": save_as,
        }
        if tool in _REGION_TOOLS:
            call["for_each"] = "$regions"
        plan.append(call)
    return plan


def prune_redundant_calls(plan):
    """Remove exact duplicate idempotent calls and retain one submission."""
    seen_idempotent_calls = set()
    result = []
    submission_added = False
    for call in plan:
        tool = call["tool"]
        if tool == "submit_solution":
            if submission_added:
                continue
            submission_added = True
            result.append(call)
            continue

        signature = (
            tool,
            json.dumps(call.get("arguments", {}), sort_keys=True),
            call.get("for_each"),
        )
        if signature in seen_idempotent_calls:
            continue
        seen_idempotent_calls.add(signature)
        result.append(call)

    for index, call in enumerate(result, start=1):
        call["call_id"] = f"call_{index:03d}"
    return result


def generate_task(conn, rng=None, length=5, task_index=1):
    """Generate one public instruction plus hidden execution metadata."""
    rng = rng or random.Random()
    graph = build_tool_graph()
    raw_sequence = random_walk(graph, length=length, rng=rng)
    refined_sequence = refine_tool_sequence(raw_sequence)
    artifact_id, file_name = _select_fixture(conn, rng)
    fixture_path = f"raw/assets/{file_name}"
    execution_plan = prune_redundant_calls(
        build_execution_plan(refined_sequence, fixture_path)
    )
    sequence = [call["tool"] for call in execution_plan]

    return {
        "task_id": f"task_a1_{task_index:06d}",
        "environment": "A1_multimodal_learning_understanding",
        "instruction": _instruction(sequence),
        "arguments": {
            "artifact_id": artifact_id,
            "fixture_path": fixture_path,
        },
        "tool_sequence": sequence,
        "raw_walk": raw_sequence,
        "execution_plan": execution_plan,
        "difficulty": (
            "simple" if length <= 3 else "medium" if length <= 5 else "complex"
        ),
        "rubric": _build_rubric(sequence),
    }


def generate_tasks(conn, count, seed=None, length=5):
    """Generate a reproducible batch using one seeded random stream."""
    if count < 1:
        raise ValueError("count must be positive")
    if isinstance(length, int):
        lengths = [length] * count
    else:
        lengths = list(length)
        if len(lengths) != count:
            raise ValueError("length must contain one value per task")
    rng = random.Random(seed)
    return [
        generate_task(conn, rng=rng, length=task_length, task_index=index)
        for index, task_length in enumerate(lengths, start=1)
    ]
