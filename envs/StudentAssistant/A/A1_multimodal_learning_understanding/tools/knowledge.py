"""Knowledge-point analysis tools for normalized learning objects."""

from __future__ import annotations

from .solving import get_problem_context
from .recognition import real_ocr_mode


def analyze_problem_knowledge(conn, region_id):
    """Return topic metadata and solution-linked knowledge points, without answers."""
    context = get_problem_context(conn, region_id)
    if real_ocr_mode():
        return {
            "region_id": region_id,
            "knowledge_points": [],
            "analysis_basis": "ocr_text_only_no_verified_metadata",
        }
    rows = conn.execute(
        """
        SELECT sk.knowledge_point
        FROM problem_occurrences AS o
        JOIN solutions AS s ON s.problem_id = o.problem_id
        JOIN solution_knowledge_points AS sk ON sk.solution_id = s.solution_id
        WHERE o.region_id = ?
        ORDER BY sk.knowledge_point
        """,
        (region_id,),
    ).fetchall()
    points = []
    if context.get("topic"):
        points.append(context["topic"])
    points.extend(row[0] for row in rows)
    return {
        "region_id": region_id,
        "problem_id": context["problem_id"],
        "subject": context["subject"],
        "grade_band": context["grade_band"],
        "question_type": context["question_type"],
        "knowledge_points": list(dict.fromkeys(points)),
        "has_diagram": bool(context["has_diagram"]),
        "analysis_basis": "normalized_metadata",
    }
