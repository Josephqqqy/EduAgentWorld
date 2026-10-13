"""Problem observation and Agent solution-submission tools."""

from __future__ import annotations

import uuid

from .common import audit
from .recognition import latest_real_text, real_ocr_mode


def get_problem_context(conn, region_id):
    columns = [
        "problem_id",
        "subject",
        "grade_band",
        "statement",
        "latex",
        "topic",
        "question_type",
        "has_diagram",
        "question_no",
    ]
    row = conn.execute(
        """
        SELECT p.problem_id, p.subject, p.grade_band, p.statement, p.latex,
               p.topic, p.question_type, p.has_diagram, p.question_no
        FROM problem_occurrences AS o
        JOIN problems AS p ON p.problem_id = o.problem_id
        WHERE o.region_id = ?
        """,
        (region_id,),
    ).fetchone()
    if row is None:
        raise LookupError(f"No normalized problem for region: {region_id}")

    result = dict(zip(columns, row))
    if real_ocr_mode():
        return {
            "region_id": region_id,
            "statement": latest_real_text(conn, region_id),
            "latex": None,
        }
    result["region_id"] = region_id
    return result


def get_artifact_problem_contexts(conn, artifact_id):
    """Return normalized, answer-free contexts for every question region."""
    rows = conn.execute(
        """
        SELECT r.region_id
        FROM artifact_regions AS r
        JOIN problem_occurrences AS o ON o.region_id = r.region_id
        WHERE r.artifact_id = ?
          AND o.occurrence_status = 'confirmed'
        ORDER BY r.region_index
        """,
        (artifact_id,),
    ).fetchall()
    return [get_problem_context(conn, row[0]) for row in rows]


def submit_solution(conn, region_id, final_answer, reasoning):
    if not reasoning or not reasoning.strip():
        raise ValueError("reasoning must be non-empty")

    if conn.execute(
        "SELECT 1 FROM problem_occurrences WHERE region_id = ?", (region_id,)
    ).fetchone() is None:
        raise LookupError(f"No normalized problem for region: {region_id}")
    submission_id = f"submission_{uuid.uuid4().hex[:12]}"
    result = {
        "submission_id": submission_id,
        "region_id": region_id,
        "final_answer": final_answer,
        "reasoning": reasoning.strip(),
        "status": "submitted",
    }
    audit(conn, "submit_solution", submission_id, region_id)
    conn.commit()
    return result
