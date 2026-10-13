"""Deterministic diagram observations backed by normalized question metadata."""

from __future__ import annotations

from .solving import get_problem_context
from .recognition import real_ocr_mode


def analyze_diagram(conn, region_id):
    """Describe known diagram metadata and expose fixture limitations explicitly."""
    context = get_problem_context(conn, region_id)
    if real_ocr_mode():
        return {
            "region_id": region_id,
            "has_diagram": None,
            "diagram_type": None,
            "entities": [],
            "relations": [],
            "description": "",
            "status": "visual_analysis_unavailable",
        }
    if not context["has_diagram"]:
        return {
            "region_id": region_id,
            "has_diagram": False,
            "diagram_type": None,
            "entities": [],
            "relations": [],
            "description": "",
            "status": "no_diagram",
        }

    topic = (context.get("topic") or "").lower()
    diagram_type = "geometry" if any(
        word in topic
        for word in ("几何", "geometry", "立体", "圆", "三角形", "解析")
    ) else "mathematical"
    return {
        "region_id": region_id,
        "has_diagram": True,
        "diagram_type": diagram_type,
        "entities": [],
        "relations": [],
        "description": (
            "题目标注表确认存在数学图形；当前 Fixture 未提供独立的图形实体、"
            "空间关系或像素级几何测量标注。"
        ),
        "status": "metadata_only",
    }
