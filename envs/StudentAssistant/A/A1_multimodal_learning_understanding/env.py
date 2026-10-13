"""A1 minimal task harness assembly."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from seed import seed
from tools import (
    analyze_diagram,
    analyze_problem_knowledge,
    assess_content_completeness,
    evaluate_submission,
    extract_editable_text,
    generate_task,
    generate_tasks,
    get_artifact,
    get_artifact_problem_contexts,
    get_problem_context,
    list_artifact_regions,
    recognize_content,
    submit_solution,
    upload_artifact,
)


THEME = "multimodal_learning_understanding"
ENV_DIR = Path(__file__).resolve().parent


def _open_database(db_path):
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript((ENV_DIR / "schema.sql").read_text(encoding="utf-8"))
    seed(conn, ENV_DIR)
    return conn


def build(db_path=":memory:"):
    """Build the A1 environment with public tools and a private evaluator."""
    conn = _open_database(db_path)
    public_tools = {
        "upload_artifact": upload_artifact,
        "get_artifact": get_artifact,
        "list_artifact_regions": list_artifact_regions,
        "recognize_content": recognize_content,
        "extract_editable_text": extract_editable_text,
        "assess_content_completeness": assess_content_completeness,
        "analyze_diagram": analyze_diagram,
        "analyze_problem_knowledge": analyze_problem_knowledge,
        "get_problem_context": get_problem_context,
        "get_artifact_problem_contexts": get_artifact_problem_contexts,
        "submit_solution": submit_solution,
    }
    return {
        "theme": THEME,
        "conn": conn,
        "tools": public_tools,
        "evaluate": lambda submission: evaluate_submission(conn, submission),
        "generate_task": lambda length=5: generate_task(conn, length=length),
        "generate_tasks": lambda count, seed=None, length=5: generate_tasks(
            conn, count=count, seed=seed, length=length
        ),
        "close": conn.close,
    }
