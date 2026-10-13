"""Artifact upload and lookup tools."""

from __future__ import annotations

import mimetypes
from pathlib import Path

from .common import audit, hash_file


_ARTIFACT_COLUMNS = [
    "artifact_id",
    "user_id",
    "file_name",
    "media_type",
    "storage_path",
    "content_hash",
    "size_bytes",
    "width",
    "height",
    "status",
]


def _media_type(path: Path) -> str:
    guessed, _ = mimetypes.guess_type(path.name)
    if guessed and guessed.startswith("image/"):
        return "image"
    if guessed == "application/pdf":
        return "pdf"
    return "text"


def _artifact_row(conn, artifact_id):
    row = conn.execute(
        """
        SELECT artifact_id, user_id, file_name, media_type, storage_path,
               content_hash, size_bytes, width, height, status
        FROM artifacts
        WHERE artifact_id = ?
        """,
        (artifact_id,),
    ).fetchone()
    return dict(zip(_ARTIFACT_COLUMNS, row)) if row else None


def upload_artifact(conn, user_id, fixture_path):
    """Register an uploaded fixture, reusing a content-identical artifact."""
    path = Path(fixture_path).resolve()
    if not path.is_file():
        raise FileNotFoundError(path)

    content_hash = hash_file(path)
    existing = conn.execute(
        """
        SELECT artifact_id
        FROM artifacts
        WHERE content_hash = ?
        ORDER BY artifact_id
        LIMIT 1
        """,
        (content_hash,),
    ).fetchone()
    if existing:
        return _artifact_row(conn, existing[0])

    fixture_id = f"art_{path.stem.zfill(4)}" if path.stem.isdigit() else None
    fixture = (
        conn.execute(
            "SELECT artifact_id FROM artifacts WHERE artifact_id = ?",
            (fixture_id,),
        ).fetchone()
        if fixture_id
        else None
    )
    if fixture:
        conn.execute(
            """
            UPDATE artifacts
            SET user_id = ?, file_name = ?, media_type = ?, storage_path = ?,
                content_hash = ?, size_bytes = ?, status = 'uploaded'
            WHERE artifact_id = ?
            """,
            (
                user_id,
                path.name,
                _media_type(path),
                str(path),
                content_hash,
                path.stat().st_size,
                fixture_id,
            ),
        )
        audit(conn, "upload_artifact", fixture_id, str(path))
        conn.commit()
        return _artifact_row(conn, fixture_id)

    artifact_id = f"artifact_upload_{content_hash.split(':', 1)[1][:12]}"
    conn.execute(
        """
        INSERT INTO artifacts (
            artifact_id, user_id, file_name, media_type, storage_path,
            content_hash, size_bytes, status
        ) VALUES (?, ?, ?, ?, ?, ?, ?, 'uploaded')
        """,
        (
            artifact_id,
            user_id,
            path.name,
            _media_type(path),
            str(path),
            content_hash,
            path.stat().st_size,
        ),
    )
    audit(conn, "upload_artifact", artifact_id, str(path))
    conn.commit()
    return _artifact_row(conn, artifact_id)


def get_artifact(conn, artifact_id):
    artifact = _artifact_row(conn, artifact_id)
    if artifact is None:
        raise LookupError(f"Unknown artifact: {artifact_id}")
    return artifact
