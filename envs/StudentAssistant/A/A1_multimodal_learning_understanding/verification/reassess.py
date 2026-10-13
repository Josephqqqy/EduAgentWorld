"""Re-evaluate saved submissions without rerunning or editing model trajectories."""

import argparse
import json
from collections import Counter
from pathlib import Path

from env import build
from rollout.runner import _expected_region_ids, _finalize_rubric_status, _rubric_check
from verification import verify_answer


def reassess_batch(source, destination, task_source):
    source, destination, task_source = Path(source), Path(destination), Path(task_source)
    if destination.exists():
        raise FileExistsError(f"Refusing to overwrite: {destination}")
    tasks = {
        task["task_id"]: task
        for task in json.loads(task_source.read_text(encoding="utf-8"))
    }
    environment = build()
    records = []
    try:
        for path in sorted(source.glob("task_a1_*.json")):
            trajectory = json.loads(path.read_text(encoding="utf-8"))
            if trajectory["status"] != "needs_review":
                continue
            task = tasks[trajectory["task_id"]]
            if not task.get("rubric", {}).get("required_tools"):
                raise ValueError(f"Missing source rubric: {trajectory['task_id']}")
            if task["arguments"] != trajectory["task"]["arguments"]:
                raise ValueError(f"Task arguments changed: {trajectory['task_id']}")
            calls = [
                (step["tool"], step["arguments"])
                for step in trajectory["steps"]
                if step["type"] == "tool" and step["status"] == "completed"
            ]
            submissions = [
                step["observation"]["region_id"]
                for step in trajectory["steps"]
                if step["type"] == "tool" and step["tool"] == "submit_solution"
                and step["status"] == "completed"
            ]
            evaluations = []
            for region_id, submission in trajectory["final_submission"].items():
                context = environment["tools"]["get_problem_context"](environment["conn"], region_id)
                row = environment["conn"].execute(
                    "SELECT final_answer_json FROM solutions WHERE problem_id = ?",
                    (context["problem_id"],),
                ).fetchone()
                if row is None:
                    raise LookupError(context["problem_id"])
                verdict = verify_answer(
                    submission["final_answer"], json.loads(row[0]),
                    question_type=context["question_type"],
                )
                evaluations.append({
                    "region_id": region_id,
                    "problem_id": context["problem_id"],
                    "verification": verdict,
                    "verification_status": verdict["status"],
                    "task_completed": verdict["status"] == "correct"
                    and bool(submission.get("reasoning", "").strip()),
                    "reasoning_present": bool(submission.get("reasoning", "").strip()),
                })
            rubric = _rubric_check(
                task, _expected_region_ids(environment, task),
                calls, submissions, evaluations,
            )
            fresh = {"status": "completed", "termination_reason": "offline_reassessment"}
            _finalize_rubric_status(fresh, rubric)
            records.append({
                "task_id": trajectory["task_id"],
                "source_trajectory": path.name,
                "original_status": trajectory["status"],
                "reassessed_status": fresh["status"],
                "termination_reason": fresh["termination_reason"],
                "evaluations": evaluations,
                "rubric_check": rubric,
            })
    finally:
        environment["close"]()
    destination.mkdir(parents=True)
    report = {
        "source": str(source),
        "task_source": str(task_source),
        "scope": "original needs_review tasks only; model steps unchanged",
        "counts": dict(Counter(item["reassessed_status"] for item in records)),
        "tasks": records,
    }
    (destination / "reassessment.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    queue = [
        {
            "task_id": item["task_id"],
            "source_trajectory": item["source_trajectory"],
            "automated_status": item["reassessed_status"],
            "human_decision": None,
            "reviewer": None,
            "evidence": None,
            "notes": None,
        }
        for item in records if item["reassessed_status"] == "needs_review"
    ]
    (destination / "manual_review_queue.json").write_text(
        json.dumps(queue, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("destination", type=Path)
    parser.add_argument("--tasks", required=True, type=Path)
    args = parser.parse_args()
    print(json.dumps(reassess_batch(args.source, args.destination, args.tasks)["counts"]))


if __name__ == "__main__":
    main()
