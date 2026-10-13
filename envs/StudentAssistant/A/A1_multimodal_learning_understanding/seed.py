"""Seed the A1 SQLite database from the normalized dataset files."""

from __future__ import annotations

import csv
import json
import sqlite3
from pathlib import Path
from typing import Any, Iterable


DEFAULT_DATA_DIR = Path(__file__).resolve().parent


def _read_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8-sig") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise ValueError(f"Expected a JSON object in {path}")
    return value


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def _as_bool(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return int(value)
    return int(str(value).strip().lower() in {"1", "true", "yes"})


def _year_status(value: Any) -> str:
    return "unknown" if value in (None, "", "unknown") else "known"


def _source_id(artifact_id: str) -> str:
    return f"source_{artifact_id.removeprefix('art_')}"


def _region_id(artifact_id: str, region_index: int) -> str:
    return f"region_{artifact_id}_{region_index:02d}"


def _insert_sources(conn: sqlite3.Connection, rows: Iterable[dict[str, str]]) -> None:
    for row in rows:
        year = row.get("year") or None
        conn.execute(
            """
            INSERT INTO sources (
                source_id, source_type, title, exam_type, year, year_status,
                region, paper_variant, publisher, snapshot_path, content_hash,
                license, verification_status, notes
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                _source_id(row["artifact_id"]),
                row.get("source_type") or "unknown",
                row.get("publisher") or row.get("file_name"),
                row.get("exam_type") or None,
                year,
                _year_status(year),
                row.get("region") or None,
                row.get("paper_variant") or None,
                row.get("publisher") or None,
                row.get("file_name") or "",
                "",
                row.get("license") or None,
                row.get("verification_status") or "unverified",
                row.get("notes") or None,
            ),
        )


def _insert_artifacts(conn: sqlite3.Connection, rows: Iterable[dict[str, str]]) -> None:
    for row in rows:
        status = {"collected": "uploaded"}.get(
            row.get("status", ""), row.get("status") or "uploaded"
        )
        conn.execute(
            """
            INSERT INTO artifacts (
                artifact_id, user_id, source_id, file_name, media_type,
                storage_path, content_hash, size_bytes, width, height, status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                row["artifact_id"],
                None,
                _source_id(row["artifact_id"]),
                row["file_name"],
                row["media_type"],
                row["storage_path"],
                row["sha256"],
                int(row["size_bytes"]) if row.get("size_bytes") else None,
                int(row["width"]) if row.get("width") else None,
                int(row["height"]) if row.get("height") else None,
                status,
            ),
        )


def _insert_problems(conn: sqlite3.Connection, problems: Iterable[dict[str, Any]]) -> None:
    for problem in problems:
        exam = problem.get("exam") or {}
        provenance = problem.get("provenance") or {}
        curation = problem.get("curation") or {}
        year = exam.get("year")
        conn.execute(
            """
            INSERT INTO problems (
                problem_id, object_type, subject, grade_band, statement, latex,
                topic, question_type, has_diagram, requires_confirmation,
                source_id, exam_type, year, year_status, region, paper_variant,
                question_no, annotation_status, notes
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                problem["problem_id"],
                problem.get("object_type", "question"),
                problem["subject"],
                problem.get("grade_band"),
                problem["statement"],
                problem.get("latex"),
                problem.get("topic"),
                problem["question_type"],
                _as_bool(problem.get("has_diagram")),
                _as_bool(problem.get("requires_confirmation")) or 0,
                provenance.get("source_id"),
                exam.get("exam_type"),
                str(year) if year is not None else None,
                exam.get("year_status", _year_status(year)),
                exam.get("region"),
                exam.get("paper_variant"),
                exam.get("question_no"),
                curation.get("annotation_status", "pending"),
                curation.get("notes") or provenance.get("notes"),
            ),
        )


def _insert_regions_and_ground_truth(
    conn: sqlite3.Connection,
    ground_truth_by_artifact: dict[str, dict[str, Any]],
) -> None:
    for artifact_id, ground_truth in ground_truth_by_artifact.items():
        path = f"fixtures/ground_truth/{artifact_id}.json"
        regions = ground_truth["expected_regions"]
        expected_count = int(ground_truth["expected_region_count"])
        if expected_count != len(regions):
            raise ValueError(f"Region count mismatch in {path}")
        for region in regions:
            index = int(region["region_index"])
            annotation_status = region.get("annotation_status", "pending")
            bbox = region.get("bbox")
            conn.execute(
                """
                INSERT INTO artifact_regions (
                    region_id, artifact_id, region_index, region_type,
                    bbox_json, bbox_status, confidence, status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    _region_id(artifact_id, index),
                    artifact_id,
                    index,
                    region.get("region_type", "unknown"),
                    json.dumps(bbox, ensure_ascii=False) if bbox is not None else None,
                    region.get("bbox_status", "not_annotated"),
                    None,
                    "confirmed" if annotation_status == "verified" else "detected",
                ),
            )
            conn.execute(
                """
                INSERT INTO recognition_ground_truth (
                    ground_truth_id, artifact_id, region_id, problem_id,
                    ground_truth_version, ground_truth_path,
                    expected_region_count, statement, latex, question_no,
                    subject, grade_band, exam_type, year, region, paper_variant,
                    topic, question_type, has_diagram, requires_confirmation,
                    annotation_status, notes
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                          ?, ?, ?, ?, ?)
                """,
                (
                    f"ground_truth_{artifact_id}_{index:02d}",
                    artifact_id,
                    _region_id(artifact_id, index),
                    region.get("problem_id"),
                    ground_truth.get("ground_truth_version", "1.0"),
                    path,
                    expected_count,
                    region.get("statement"),
                    region.get("latex"),
                    region.get("question_no"),
                    region.get("subject"),
                    region.get("grade_band"),
                    region.get("exam_type"),
                    region.get("year"),
                    region.get("region"),
                    region.get("paper_variant"),
                    region.get("topic"),
                    region.get("question_type"),
                    _as_bool(region.get("has_diagram")),
                    _as_bool(region.get("requires_confirmation")) or 0,
                    annotation_status,
                    ground_truth.get("notes"),
                ),
            )


def _insert_occurrences(conn: sqlite3.Connection, problems: Iterable[dict[str, Any]]) -> None:
    for problem in problems:
        occurrence = problem["occurrence"]
        artifact_id = occurrence["artifact_id"]
        index = int(occurrence["region_index"])
        conn.execute(
            """
            INSERT INTO problem_occurrences (
                occurrence_id, problem_id, artifact_id, region_id, question_no,
                ground_truth_path, occurrence_status
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                f"occurrence_{problem['problem_id']}",
                problem["problem_id"],
                artifact_id,
                _region_id(artifact_id, index),
                problem.get("exam", {}).get("question_no"),
                occurrence.get("ground_truth_path"),
                "confirmed"
                if problem.get("curation", {}).get("annotation_status") == "verified"
                else "candidate",
            ),
        )


def _insert_solutions(conn: sqlite3.Connection, solutions: Iterable[dict[str, Any]]) -> None:
    for solution in solutions:
        conn.execute(
            """
            INSERT INTO solutions (
                solution_id, problem_id, final_answer_json, solution_source,
                source_id, verification_status, verification_method, notes
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                solution["solution_id"],
                solution["problem_id"],
                json.dumps(solution["final_answer"], ensure_ascii=False),
                solution["solution_source"],
                solution.get("source_id"),
                solution["verification_status"],
                solution.get("verification_method"),
                solution.get("notes"),
            ),
        )
        for step in solution.get("solution_steps", []):
            conn.execute(
                """
                INSERT INTO solution_steps (
                    solution_id, step_no, text, expression, justification,
                    is_key_step
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    solution["solution_id"],
                    int(step["step_no"]),
                    step["text"],
                    step.get("expression"),
                    step.get("justification"),
                    _as_bool(step.get("is_key_step")) or 0,
                ),
            )
        for knowledge_point in dict.fromkeys(solution.get("knowledge_points", [])):
            conn.execute(
                """
                INSERT INTO solution_knowledge_points (
                    solution_id, knowledge_point
                ) VALUES (?, ?)
                """,
                (solution["solution_id"], knowledge_point),
            )


def seed(conn: sqlite3.Connection, data_dir: str | Path | None = None) -> None:
    """Import the checked-in A1 dataset into an initialized SQLite database."""
    root = Path(data_dir) if data_dir is not None else DEFAULT_DATA_DIR
    manifest = _read_csv(root / "raw" / "asset_manifest.csv")
    sources = _read_csv(root / "raw" / "source_annotations.csv")
    problems = _read_json(root / "normalized" / "problems.json")["problems"]
    solutions = _read_json(root / "normalized" / "solutions.json")["solutions"]
    ground_truth = {
        item["artifact_id"]: item
        for item in (
            _read_json(path)
            for path in sorted((root / "fixtures" / "ground_truth").glob("*.json"))
        )
    }

    conn.execute("PRAGMA foreign_keys = ON")
    with conn:
        _insert_sources(conn, sources)
        _insert_artifacts(conn, manifest)
        _insert_problems(conn, problems)
        _insert_regions_and_ground_truth(conn, ground_truth)
        _insert_occurrences(conn, problems)
        _insert_solutions(conn, solutions)
