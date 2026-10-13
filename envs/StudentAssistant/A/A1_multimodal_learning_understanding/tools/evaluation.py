"""Harness-only evaluation for submitted Agent solutions."""

from __future__ import annotations

import json

from .common import audit
from verification import verify_answer


def evaluate_submission(conn, submission):
    """Evaluate a submission against hidden reference data."""
    row = conn.execute(
        """
        SELECT p.problem_id, p.question_type, s.final_answer_json
        FROM problem_occurrences AS o
        JOIN problems AS p ON p.problem_id = o.problem_id
        LEFT JOIN solutions AS s ON s.problem_id = p.problem_id
        WHERE o.region_id = ?
        """,
        (submission["region_id"],),
    ).fetchone()
    if row is None or row[2] is None:
        raise LookupError(f"No solution for region: {submission['region_id']}")

    problem_id, question_type, answer_json = row
    expected = json.loads(answer_json)
    verdict = verify_answer(
        submission["final_answer"], expected, question_type=question_type
    )
    answer_correct = (
        True if verdict["status"] == "correct"
        else False if verdict["status"] == "incorrect" else None
    )
    reasoning_present = bool(submission.get("reasoning", "").strip())
    task_completed = answer_correct is True and reasoning_present
    result = {
        "submission_id": submission["submission_id"],
        "region_id": submission["region_id"],
        "problem_id": problem_id,
        "answer_correct": answer_correct,
        "verification_status": verdict["status"],
        "verification_method": verdict["match_method"],
        "verification": verdict,
        "needs_review": verdict["needs_review"],
        "reasoning_present": reasoning_present,
        "task_completed": task_completed,
        "reward": None if verdict["needs_review"] else 1.0 if task_completed else 0.0,
    }
    audit(
        conn,
        "evaluate_submission",
        submission["submission_id"],
        json.dumps(result, ensure_ascii=False),
    )
    conn.commit()
    return result
