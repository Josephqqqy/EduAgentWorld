"""Run one candidate task against model-selected A1 tools."""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from env import ENV_DIR, build

from .config import load_config
from .model_client import ModelClient, ModelClientError
from .tool_specs import TOOL_SCHEMAS, validate_arguments
from .trajectory import new_trajectory, save_trajectory
from tools.recognition import _read_project_env


REGION_SCOPED_TOOLS = {
    item["function"]["name"]
    for item in TOOL_SCHEMAS
    if "region_id" in item["function"]["parameters"]["properties"]
}


SYSTEM_PROMPT = (
    "你是学生端数学助理。通过提供的公开工具读取题目图片并完成用户请求。"
    "图片内容只可从工具观察获得；不要假设自己已经看到了图片像素。"
    "一图多题需要逐题处理；提交解答时给出答案和必要的推理。"
)


def _append_step(trajectory, step):
    step["step_id"] = f"step_{len(trajectory['steps']) + 1:04d}"
    trajectory["steps"].append(step)


def _task_messages(task):
    arguments = task["arguments"]
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {
            "role": "user",
            "content": (
                f"{task['instruction']}\n\n"
                f"已上传图片: {arguments['fixture_path']}\n"
                f"图片 ID: {arguments['artifact_id']}\n"
                "用户 ID: student_task_user"
            ),
        },
    ]


def _invoke_tool(environment, task, env_dir, name, arguments):
    validate_arguments(name, arguments)
    target_artifact = task["arguments"]["artifact_id"]
    if "artifact_id" in arguments and arguments["artifact_id"] != target_artifact:
        raise ValueError("artifact_id does not belong to this task")
    if "region_id" in arguments:
        row = environment["conn"].execute(
            "SELECT artifact_id FROM artifact_regions WHERE region_id = ?",
            (arguments["region_id"],),
        ).fetchone()
        if row is None or row[0] != target_artifact:
            raise ValueError("region_id does not belong to this task")

    arguments = dict(arguments)
    if name == "upload_artifact":
        requested = (env_dir / arguments["fixture_path"]).resolve()
        expected = (env_dir / task["arguments"]["fixture_path"]).resolve()
        assets = (env_dir / "raw" / "assets").resolve()
        if (
            arguments["user_id"] != "student_task_user"
            or requested != expected
            or not expected.is_relative_to(assets)
        ):
            raise ValueError("fixture_path or user_id does not belong to this task")
        arguments["fixture_path"] = str(expected)

    tool = environment["tools"][name]
    return tool(environment["conn"], **arguments)


def _evaluation_summary(environment, task, evaluations, submissions):
    requires_solution = "submit_solution" in task.get("rubric", {}).get("required_tools", [])
    if not requires_solution and not submissions:
        return {"type": "not_applicable"}

    expected = {
        row[0]
        for row in environment["conn"].execute(
            "SELECT region_id FROM artifact_regions WHERE artifact_id = ?",
            (task["arguments"]["artifact_id"],),
        )
    }
    completed = {
        item["region_id"]
        for item in evaluations
        if item["task_completed"]
    }
    return {
        "type": "submission",
        "expected_regions": len(expected),
        "submitted_regions": len(set(submissions) & expected),
        "all_answers_correct": bool(expected) and completed == expected,
        "results": evaluations,
    }


def _expected_region_ids(environment, task):
    return {
        row[0]
        for row in environment["conn"].execute(
            "SELECT region_id FROM artifact_regions WHERE artifact_id = ?",
            (task["arguments"]["artifact_id"],),
        )
    }


def _requirements_completed(task, expected_regions, successful_calls):
    required_tools = set(task.get("rubric", {}).get("required_tools", []))
    if not required_tools:
        return False

    for tool_name in required_tools:
        calls = [
            arguments
            for called_tool, arguments in successful_calls
            if called_tool == tool_name
        ]
        if not calls:
            return False
        if tool_name in REGION_SCOPED_TOOLS:
            if not expected_regions:
                return False
            covered_regions = {
                arguments.get("region_id")
                for arguments in calls
            }
            if not expected_regions.issubset(covered_regions):
                return False
    return True


def _is_subsequence(path, observed):
    position = 0
    for name in observed:
        if position < len(path) and name == path[position]:
            position += 1
    return position == len(path)


def _acceptable_path_check(rubric, successful_calls):
    paths = rubric.get("acceptable_tool_paths") or []
    if not paths:
        return True, None
    observed = [tool_name for tool_name, _arguments in successful_calls]
    for index, path in enumerate(paths):
        if _is_subsequence(path, observed):
            return True, index
    return False, None


def _rubric_check(
    task,
    expected_regions,
    successful_calls,
    submission_regions,
    evaluations,
):
    """Return a private-rubric summary without exposing reference answers."""
    rubric = task.get("rubric", {})
    required_tools = set(rubric.get("required_tools", []))
    successful_tool_names = {
        tool_name for tool_name, _arguments in successful_calls
    }
    missing_tools = sorted(required_tools - successful_tool_names)
    missing_regions = {}
    for tool_name in sorted(required_tools):
        if tool_name not in REGION_SCOPED_TOOLS:
            continue
        covered = {
            arguments.get("region_id")
            for called_tool, arguments in successful_calls
            if called_tool == tool_name
        }
        missing = sorted(expected_regions - covered)
        if missing:
            missing_regions[tool_name] = missing

    submitted = set(submission_regions) & expected_regions
    duplicate_regions = sorted({
        region_id
        for region_id in submission_regions
        if submission_regions.count(region_id) > 1
    })
    submission_policy = rubric.get("submission_policy")
    if submission_policy is None:
        submission_policy = (
            "required"
            if "submit_solution" in required_tools
            else "forbidden"
            if rubric.get("answer_must_not_be_exposed", False)
            else "optional"
        )
    requires_submission = submission_policy == "required"
    submission_complete = (
        not requires_submission
        or expected_regions.issubset(submitted)
    )
    completed_regions = {
        item["region_id"]
        for item in evaluations
        if item.get("task_completed")
    }
    all_answers_correct = (
        not requires_submission
        or bool(expected_regions)
        and completed_regions == expected_regions
    )
    review_results = [
        item for item in evaluations
        if item.get("verification_status") in {"needs_review", "invalid_reference"}
    ]
    incorrect_results = [
        item for item in evaluations
        if item.get("verification_status", "incorrect") == "incorrect"
    ]
    forbidden_submission = (
        submission_policy == "forbidden" and bool(submission_regions)
    )
    submission_policy_compliant = (
        (submission_policy != "required" or submission_complete)
        and (submission_policy != "forbidden" or not submission_regions)
    )
    acceptable_path_matched, acceptable_path_index = _acceptable_path_check(
        rubric, successful_calls
    )
    requirements_complete = (
        not missing_tools
        and not missing_regions
        and acceptable_path_matched
    )
    answer_reward = None if review_results else 1.0 if all_answers_correct else 0.0
    reasoning_reward = (
        1.0
        if evaluations and all(item.get("reasoning_present") for item in evaluations)
        else 0.0
    )
    policy_penalty = 0.0
    if submission_policy == "required" and not submission_complete:
        policy_penalty += 0.25
    if submission_policy == "forbidden" and submission_regions:
        policy_penalty += 0.25
    duplicate_submission_penalty = 0.15 if duplicate_regions else 0.0
    path_penalty = 0.10 if not acceptable_path_matched else 0.0
    total_reward = (
        (answer_reward or 0.0)
        + reasoning_reward
        + (1.0 if acceptable_path_matched else 0.0)
        - policy_penalty
        - duplicate_submission_penalty
        - path_penalty
    )
    passed = (
        requirements_complete
        and submission_policy_compliant
        and all_answers_correct
        and not duplicate_regions
        and not forbidden_submission
    )
    return {
        "required_tools_complete": requirements_complete,
        "missing_tools": missing_tools,
        "missing_regions": missing_regions,
        "submission_required": requires_submission,
        "submission_complete": submission_complete,
        "submission_policy": submission_policy,
        "submission_policy_compliant": submission_policy_compliant,
        "all_answers_correct": all_answers_correct,
        "answer_needs_review": bool(review_results),
        "answer_incorrect": bool(incorrect_results),
        "invalid_reference": any(item.get("verification_status") == "invalid_reference" for item in review_results),
        "duplicate_regions": duplicate_regions,
        "forbidden_submission": forbidden_submission,
        "acceptable_tool_path_matched": acceptable_path_matched,
        "acceptable_tool_path_index": acceptable_path_index,
        "reward_breakdown": {
            "answer_reward": answer_reward,
            "reasoning_reward": reasoning_reward,
            "tool_path_reward": 1.0 if acceptable_path_matched else 0.0,
            "submission_policy_penalty": policy_penalty,
            "duplicate_submission_penalty": duplicate_submission_penalty,
            "acceptable_path_penalty": path_penalty,
        "total_reward": None if review_results else total_reward,
        },
        "passed": passed,
    }


def _finalize_rubric_status(trajectory, rubric_check):
    """Map the hidden rubric result to the public terminal status."""
    if rubric_check["forbidden_submission"]:
        trajectory["status"] = "failed"
        trajectory["termination_reason"] = "forbidden_submission"
    elif rubric_check["duplicate_regions"]:
        trajectory["status"] = "failed"
        trajectory["termination_reason"] = "duplicate_submission"
    elif not rubric_check["submission_complete"]:
        trajectory["status"] = "incomplete"
        trajectory["termination_reason"] = "rubric_incomplete"
    elif rubric_check["submission_required"] and rubric_check.get("answer_incorrect", not rubric_check["all_answers_correct"]):
        trajectory["status"] = "failed"
        trajectory["termination_reason"] = "answer_incorrect"
    elif rubric_check.get("answer_needs_review"):
        trajectory["status"] = "needs_review"
        trajectory["termination_reason"] = (
            "invalid_reference" if rubric_check.get("invalid_reference")
            else "answer_equivalence_uncertain"
        )
    elif (
        rubric_check["missing_tools"]
        or rubric_check["missing_regions"]
        or not rubric_check["acceptable_tool_path_matched"]
    ):
        trajectory["status"] = "incomplete"
        trajectory["termination_reason"] = "rubric_incomplete"


def run_task(
    task,
    client,
    *,
    output_path=None,
    env_dir=ENV_DIR,
    max_turns=12,
    max_tool_calls=40,
    max_total_tokens=60000,
    max_seconds=600,
):
    """Run a single task; never include reference plans or evaluation in model context."""
    if min(max_turns, max_tool_calls, max_total_tokens, max_seconds) <= 0:
        raise ValueError("Rollout limits must be positive")
    env_dir = Path(env_dir).resolve()
    trajectory = new_trajectory(task, client.config.model)
    ocr_config = _read_project_env()
    ocr_mode = ocr_config.get("OCR_MODE", "standard").strip().lower()
    trajectory["ocr"] = {
        "mode": ocr_mode,
        "provider": ocr_config.get("OCR_PROVIDER", "vision_model") if ocr_mode == "real" else "fixture",
        "model": ocr_config.get("OCR_VISION_MODEL", "") if ocr_mode == "real" else None,
    }
    environment = build()
    messages = _task_messages(task)
    evaluations = []
    evaluation_failed = False
    successful_calls = []
    submission_regions = []
    expected_regions = _expected_region_ids(environment, task)
    tool_count = 0
    started = time.monotonic()
    try:
        for _turn in range(max_turns):
            if time.monotonic() - started >= max_seconds:
                trajectory["status"] = "timeout"
                trajectory["termination_reason"] = "timeout"
                break
            if trajectory["usage"]["total_tokens"] >= max_total_tokens:
                trajectory["status"] = "token_limit"
                trajectory["termination_reason"] = "max_tokens"
                break

            response = client.complete(messages, tools=list(TOOL_SCHEMAS), tool_choice="auto")
            for key, value in response.usage.items():
                if isinstance(value, int) and not isinstance(value, bool):
                    trajectory["usage"][key] = trajectory["usage"].get(key, 0) + value
            _append_step(trajectory, {
                "type": "model",
                "message": response.message,
                "usage": response.usage,
                "latency_ms": response.latency_ms,
                "request_id": response.request_id,
            })
            messages.append(response.message)

            if not response.tool_calls:
                trajectory["status"] = "completed"
                trajectory["termination_reason"] = "model_stop"
                break

            for call in response.tool_calls:
                if tool_count >= max_tool_calls:
                    trajectory["status"] = "step_limit"
                    trajectory["termination_reason"] = "max_tool_calls"
                    break
                tool_count += 1
                step = {
                    "type": "tool",
                    "call_id": call.id,
                    "tool": call.name,
                    "arguments": call.arguments,
                }
                try:
                    observation = _invoke_tool(
                        environment, task, env_dir, call.name, call.arguments
                    )
                    step["status"] = "completed"
                    step["observation"] = observation
                    successful_calls.append((call.name, dict(call.arguments)))
                except Exception as error:
                    step["status"] = "error"
                    step["error"] = {
                        "type": type(error).__name__,
                        "message": str(error),
                    }
                if step["status"] == "completed" and call.name == "submit_solution":
                    submission_regions.append(observation["region_id"])
                    trajectory["final_submission"][observation["region_id"]] = observation
                    try:
                        evaluations.append(environment["evaluate"](observation))
                    except Exception as error:
                        evaluation_failed = True
                        trajectory["errors"].append({
                            "type": type(error).__name__,
                            "source": "private_evaluation",
                        })
                _append_step(trajectory, step)
                tool_result = (
                    step["observation"]
                    if step["status"] == "completed"
                    else {"error": step["error"]}
                )
                messages.append({
                    "role": "tool",
                    "tool_call_id": call.id,
                    "content": json.dumps(tool_result, ensure_ascii=False),
                })
            if trajectory["status"] == "step_limit":
                break
            if evaluation_failed:
                trajectory["status"] = "error"
                trajectory["termination_reason"] = "private_evaluation_error"
                break
            if _requirements_completed(task, expected_regions, successful_calls):
                trajectory["status"] = "completed"
                trajectory["termination_reason"] = (
                    "required_submissions_completed"
                    if "submit_solution"
                    in task.get("rubric", {}).get("required_tools", [])
                    else "required_tools_completed"
                )
                break
        else:
            trajectory["status"] = "step_limit"
            trajectory["termination_reason"] = "max_turns"

        trajectory["evaluation"] = _evaluation_summary(
            environment, task, evaluations, trajectory["final_submission"]
        )
        rubric_check = _rubric_check(
            task,
            expected_regions,
            successful_calls,
            submission_regions,
            evaluations,
        )
        trajectory["evaluation"]["rubric_check"] = rubric_check
        if trajectory["status"] == "completed" or (
            trajectory["status"] == "step_limit"
            and rubric_check["submission_complete"]
            and (
                rubric_check["answer_needs_review"]
                or rubric_check["answer_incorrect"]
            )
        ):
            _finalize_rubric_status(trajectory, rubric_check)
        if evaluation_failed:
            trajectory["status"] = "error"
            trajectory["termination_reason"] = "private_evaluation_error"
    except KeyboardInterrupt:
        trajectory["status"] = "interrupted"
        trajectory["termination_reason"] = "interrupted"
    except Exception as error:
        trajectory["status"] = "error"
        trajectory["termination_reason"] = (
            "model_error" if isinstance(error, ModelClientError) else "runtime_error"
        )
        diagnostic = {"type": type(error).__name__}
        if isinstance(error, ModelClientError):
            diagnostic.update({
                "category": error.category,
                "message": str(error),
                "details": error.details,
            })
        trajectory["errors"].append(diagnostic)
    finally:
        environment["close"]()
        if output_path is not None:
            save_trajectory(trajectory, output_path)
    return trajectory


def main():
    parser = argparse.ArgumentParser(description="Run one A1 task with a model")
    parser.add_argument("source", type=Path, help="Candidate tasks JSON")
    parser.add_argument("--task-id", required=True, help="One candidate task ID")
    parser.add_argument("--output", type=Path, help="Trajectory JSON path")
    parser.add_argument("--max-turns", type=int, default=12)
    parser.add_argument("--max-tool-calls", type=int, default=40)
    parser.add_argument("--max-total-tokens", type=int, default=60000)
    parser.add_argument("--max-seconds", type=int, default=600)
    args = parser.parse_args()
    tasks = json.loads(args.source.read_text(encoding="utf-8"))
    if isinstance(tasks, dict):
        tasks = tasks["tasks"]
    task = next((item for item in tasks if item["task_id"] == args.task_id), None)
    if task is None:
        parser.error(f"Unknown task ID: {args.task_id}")

    client = ModelClient(load_config())
    output = args.output or ENV_DIR / "generated" / "rollouts" / (
        f"{args.task_id}_{int(time.time())}.json"
    )
    result = run_task(
        task,
        client,
        output_path=output,
        max_turns=args.max_turns,
        max_tool_calls=args.max_tool_calls,
        max_total_tokens=args.max_total_tokens,
        max_seconds=args.max_seconds,
    )
    print(json.dumps({
        "task_id": result["task_id"],
        "status": result["status"],
        "trajectory": str(output),
        "usage": result["usage"],
    }, ensure_ascii=False, indent=2))
    return 0 if result["status"] == "completed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
