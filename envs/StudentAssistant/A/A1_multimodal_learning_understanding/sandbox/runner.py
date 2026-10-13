"""Execute generated candidate tasks in isolated in-memory A1 environments."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from env import ENV_DIR, build

from .bindings import resolve_value


REDACTED = "<hidden_reference>"


def _hidden_solution(conn, region_id):
    row = conn.execute(
        """
        SELECT s.solution_id, s.final_answer_json
        FROM problem_occurrences AS o
        JOIN solutions AS s ON s.problem_id = o.problem_id
        WHERE o.region_id = ?
        """,
        (region_id,),
    ).fetchone()
    if row is None:
        raise LookupError(f"No hidden solution for region: {region_id}")

    steps = conn.execute(
        """
        SELECT text
        FROM solution_steps
        WHERE solution_id = ?
        ORDER BY step_no
        """,
        (row[0],),
    ).fetchall()
    reasoning = "\n".join(step[0] for step in steps if step[0] and step[0].strip())
    if not reasoning:
        reasoning = "使用隐藏标准答案验证候选任务执行链路。"
    return json.loads(row[1]), reasoning


def _resolve_arguments(call, scope, env_dir):
    arguments = dict(call.get("arguments", {}))
    fixture_path = arguments.get("fixture_path")
    if fixture_path and not Path(fixture_path).is_absolute():
        arguments["fixture_path"] = str((env_dir / fixture_path).resolve())
    return resolve_value(arguments, scope)


def _public_arguments(arguments):
    result = dict(arguments)
    if "final_answer" in result:
        result["final_answer"] = REDACTED
    if "reasoning" in result:
        result["reasoning"] = REDACTED
    return result


def _public_observation(tool_name, observation):
    if tool_name != "submit_solution":
        return observation
    return {
        "submission_id": observation["submission_id"],
        "region_id": observation["region_id"],
        "final_answer": REDACTED,
        "reasoning": REDACTED,
        "status": observation["status"],
    }


def _invoke(environment, call, scope, env_dir, item=None):
    local_scope = dict(scope)
    if item is not None:
        local_scope["item"] = item

    if call["tool"] == "submit_solution":
        region_id = resolve_value(call["arguments"]["region_id"], local_scope)
        final_answer, reasoning = _hidden_solution(environment["conn"], region_id)
        local_scope["agent"] = {
            "final_answer": final_answer,
            "reasoning": reasoning,
        }

    arguments = _resolve_arguments(call, local_scope, env_dir)
    tool = environment["tools"].get(call["tool"])
    if tool is None:
        raise LookupError(f"Unknown public tool: {call['tool']}")

    observation = tool(environment["conn"], **arguments)
    evaluation = None
    if call["tool"] == "submit_solution":
        evaluation = environment["evaluate"](observation)
        if not evaluation["task_completed"]:
            raise AssertionError(
                f"Hidden reference submission failed for {observation['region_id']}"
            )
    return arguments, observation, evaluation


def execute_task(task, env_dir=ENV_DIR):
    """Execute one task and return a JSON-serializable validation result."""
    env_dir = Path(env_dir).resolve()
    environment = build()
    scope = {}
    result = {
        "task_id": task.get("task_id", "<missing-task-id>"),
        "status": "passed",
        "planned_calls": len(task.get("execution_plan", [])),
        "executed_calls": 0,
        "region_iterations": 0,
        "trace": [],
        "evaluations": [],
        "errors": [],
    }

    try:
        for call in task.get("execution_plan", []):
            trace_entry = {
                "call_id": call.get("call_id"),
                "tool": call.get("tool"),
                "status": "completed",
                "observations": [],
            }
            result["trace"].append(trace_entry)
            try:
                if "for_each" in call:
                    items = resolve_value(call["for_each"], scope)
                    if not isinstance(items, list):
                        raise TypeError(
                            f"for_each must resolve to a list: {call['for_each']}"
                        )
                    observations = []
                    for item in items:
                        arguments, observation, evaluation = _invoke(
                            environment, call, scope, env_dir, item=item
                        )
                        observations.append(observation)
                        trace_entry["observations"].append(
                            {
                                "arguments": _public_arguments(arguments),
                                "observation": _public_observation(
                                    call["tool"], observation
                                ),
                            }
                        )
                        result["executed_calls"] += 1
                        result["region_iterations"] += 1
                        if evaluation is not None:
                            result["evaluations"].append(evaluation)
                    if call.get("save_as"):
                        scope[call["save_as"]] = observations
                else:
                    arguments, observation, evaluation = _invoke(
                        environment, call, scope, env_dir
                    )
                    trace_entry["observations"].append(
                        {
                            "arguments": _public_arguments(arguments),
                            "observation": _public_observation(
                                call["tool"], observation
                            ),
                        }
                    )
                    result["executed_calls"] += 1
                    if call.get("save_as"):
                        scope[call["save_as"]] = observation
                    if evaluation is not None:
                        result["evaluations"].append(evaluation)
            except Exception as exc:
                trace_entry["status"] = "failed"
                error = {
                    "call_id": call.get("call_id"),
                    "tool": call.get("tool"),
                    "error_type": type(exc).__name__,
                    "message": str(exc),
                }
                trace_entry["error"] = error
                result["errors"].append(error)
                result["status"] = "failed"
                break
    finally:
        environment["close"]()

    return result


def validate_tasks(tasks, env_dir=ENV_DIR, source=None):
    """Execute every task independently and summarize validation outcomes."""
    results = [execute_task(task, env_dir=env_dir) for task in tasks]
    passed = sum(item["status"] == "passed" for item in results)
    report = {
        "source": source,
        "summary": {
            "total": len(results),
            "passed": passed,
            "failed": len(results) - passed,
        },
        "tasks": results,
    }
    return report


def validate_file(source_path, output_path=None, env_dir=ENV_DIR):
    """Load candidate tasks, execute them, and optionally write the report."""
    source_path = Path(source_path).resolve()
    tasks = json.loads(source_path.read_text(encoding="utf-8"))
    if isinstance(tasks, dict):
        tasks = tasks["tasks"]
    report = validate_tasks(
        tasks,
        env_dir=env_dir,
        source=str(source_path),
    )
    if output_path is not None:
        output_path = Path(output_path).resolve()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    return report


def main():
    parser = argparse.ArgumentParser(description="验证 A1 候选任务是否可执行")
    parser.add_argument("source", help="候选任务 JSON 路径")
    parser.add_argument("-o", "--output", help="验证报告输出路径")
    args = parser.parse_args()
    report = validate_file(args.source, args.output)
    print(json.dumps(report["summary"], ensure_ascii=False, indent=2))
    return 0 if report["summary"]["failed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
