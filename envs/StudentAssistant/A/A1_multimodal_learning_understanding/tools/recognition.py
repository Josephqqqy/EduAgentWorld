"""Question-region and deterministic fixture-recognition tools."""

from __future__ import annotations

import json
import os
import uuid
import base64
import io
import urllib.error
import urllib.request
from pathlib import Path

from PIL import Image

from .common import audit


def real_ocr_mode():
    return _read_project_env().get("OCR_MODE", "standard").strip().lower() == "real"


def latest_real_text(conn, region_id):
    row = conn.execute(
        """
        SELECT normalized_output FROM recognition_runs
        WHERE region_id = ? AND engine = 'vision_model_ocr'
          AND status = 'completed'
        ORDER BY rowid DESC LIMIT 1
        """,
        (region_id,),
    ).fetchone()
    if row is None or not row[0]:
        raise ValueError(f"Real OCR required for region: {region_id}")
    return row[0]


def _read_project_env() -> dict[str, str]:
    values = {}
    path = Path(__file__).resolve()
    for parent in [path.parent, *path.parents]:
        env_path = parent / ".env"
        if env_path.is_file():
            for line in env_path.read_text(encoding="utf-8-sig").splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                values[key.strip()] = value.strip().strip("\"'")
            break
    values.update(os.environ)
    return values


def _region_image(conn, region_id):
    row = conn.execute(
        """
        SELECT a.storage_path, r.bbox_json
        FROM artifact_regions AS r
        JOIN artifacts AS a ON a.artifact_id = r.artifact_id
        WHERE r.region_id = ?
        """,
        (region_id,),
    ).fetchone()
    if row is None:
        raise LookupError(f"Unknown region: {region_id}")

    image_path = Path(row[0])
    if not image_path.is_absolute():
        env_dir = Path(__file__).resolve().parents[1]
        image_path = env_dir / image_path
    if not image_path.is_file():
        raise FileNotFoundError(
            f"Artifact image not found for region {region_id}: {image_path}"
        )
    image = Image.open(image_path).convert("RGB")
    if row[1]:
        try:
            bbox = json.loads(row[1])
            if isinstance(bbox, dict):
                bbox = [
                    bbox.get("x", 0),
                    bbox.get("y", 0),
                    bbox.get("width", image.width),
                    bbox.get("height", image.height),
                ]
            x, y, width, height = [int(float(value)) for value in bbox]
            if width <= 0 or height <= 0 or x < 0 or y < 0 or x + width > image.width or y + height > image.height:
                raise ValueError(f"Invalid bounding box for region: {region_id}")
            image = image.crop((x, y, x + width, y + height))
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise ValueError(f"Invalid bounding box for region: {region_id}") from exc
    else:
        count = conn.execute(
            "SELECT COUNT(*) FROM artifact_regions WHERE artifact_id = (SELECT artifact_id FROM artifact_regions WHERE region_id = ?)",
            (region_id,),
        ).fetchone()[0]
        if count > 1:
            raise ValueError(f"Bounding box required for multi-question artifact: {region_id}")
    return image


def _vision_text(content):
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict) and item.get("type") == "text":
                parts.append(str(item.get("text", "")))
        return "\n".join(part for part in parts if part).strip()
    return ""


def _recognize_with_vision_model(conn, region_id, modality):
    config = _read_project_env()
    api_key = config.get("OCR_VISION_API_KEY", "").strip()
    base_url = config.get("OCR_VISION_BASE_URL", "").strip().rstrip("/")
    model = config.get("OCR_VISION_MODEL", "").strip()
    if not api_key:
        raise ValueError("OCR_VISION_API_KEY is required for vision_model OCR")
    if not base_url:
        raise ValueError("OCR_VISION_BASE_URL is required for vision_model OCR")
    if not model:
        raise ValueError("OCR_VISION_MODEL is required for vision_model OCR")

    try:
        timeout = float(config.get("OCR_VISION_TIMEOUT", "300"))
    except ValueError:
        timeout = 300.0
    try:
        temperature = float(config.get("OCR_VISION_TEMPERATURE", "0"))
    except ValueError:
        temperature = 0.0
    try:
        max_tokens = int(config.get("OCR_VISION_MAX_TOKENS", "16384"))
    except ValueError:
        max_tokens = 16384

    image = _region_image(conn, region_id)
    image_buffer = io.BytesIO()
    image.save(image_buffer, format="PNG")
    image_data = base64.b64encode(image_buffer.getvalue()).decode("ascii")
    prompt = (
        "请严格转录图片中的全部文字、数字、选项和数学公式。"
        "不要解题，不要补全，不要改写。无法确认的内容使用 [UNK]。"
        "只返回转录结果。"
    )
    payload = {
        "model": model,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/png;base64,{image_data}"
                        },
                    },
                ],
            }
        ],
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    request = urllib.request.Request(
        f"{base_url}/chat/completions",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            response_payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise RuntimeError(
            f"Vision OCR request failed with HTTP {exc.code}"
        ) from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Vision OCR request failed: {exc.reason}") from exc
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise RuntimeError("Vision OCR returned invalid JSON") from exc

    try:
        message = response_payload["choices"][0]["message"]
        normalized_output = _vision_text(message.get("content"))
    except (KeyError, IndexError, TypeError) as exc:
        raise RuntimeError("Vision OCR response has no assistant content") from exc
    if not normalized_output:
        raise RuntimeError("Vision OCR returned empty content")

    # Keep only non-sensitive response fields in the database and trajectory.
    raw_output = json.dumps(
        {
            "provider": "vision_model",
            "model": model,
            "text": normalized_output,
        },
        ensure_ascii=False,
    )
    recognition_id = f"recognition_{uuid.uuid4().hex[:12]}"
    conn.execute(
        """
        INSERT INTO recognition_runs (
            recognition_id, region_id, modality, engine, raw_output,
            normalized_output, confidence, status
        ) VALUES (?, ?, ?, 'vision_model_ocr', ?, ?, NULL, 'completed')
        """,
        (recognition_id, region_id, modality, raw_output, normalized_output),
    )
    audit(conn, "recognize_content", recognition_id, region_id)
    conn.commit()
    return {
        "recognition_id": recognition_id,
        "region_id": region_id,
        "modality": modality,
        "engine": "vision_model_ocr",
        "raw_output": raw_output,
        "normalized_output": normalized_output,
        "confidence": None,
        "status": "completed",
    }


def list_artifact_regions(conn, artifact_id):
    columns = [
        "region_id",
        "artifact_id",
        "region_index",
        "region_type",
        "bbox_json",
        "bbox_status",
        "confidence",
        "status",
    ]
    rows = conn.execute(
        """
        SELECT region_id, artifact_id, region_index, region_type, bbox_json,
               bbox_status, confidence, status
        FROM artifact_regions
        WHERE artifact_id = ?
        ORDER BY region_index
        """,
        (artifact_id,),
    ).fetchall()
    regions = [dict(zip(columns, row)) for row in rows]
    if real_ocr_mode():
        return [
            {key: region[key] for key in ("region_id", "region_index", "bbox_json")}
            for region in regions
        ]
    return regions


def recognize_content(conn, region_id, modality="ocr"):
    """Recognize a region using fixture mode or the configured real OCR provider."""
    allowed = {"ocr", "formula", "layout", "vision", "other"}
    if modality not in allowed:
        raise ValueError(f"Unsupported modality: {modality}")
    config = _read_project_env()
    if config.get("OCR_MODE", "standard").strip().lower() == "real":
        provider = config.get("OCR_PROVIDER", "vision_model").strip().lower()
        if provider in {"vision_model", "vision", "deepseek"}:
            return _recognize_with_vision_model(conn, region_id, modality)
        raise ValueError(f"Unsupported real OCR provider: {provider}")

    row = conn.execute(
        """
        SELECT r.region_id, gt.statement, gt.latex
        FROM artifact_regions AS r
        LEFT JOIN recognition_ground_truth AS gt ON gt.region_id = r.region_id
        WHERE r.region_id = ?
        """,
        (region_id,),
    ).fetchone()
    if row is None:
        raise LookupError(f"Unknown region: {region_id}")

    raw_output = row[1] or row[2] or ""
    if not raw_output:
        raise ValueError(f"No fixture recognition content for region: {region_id}")

    recognition_id = f"recognition_{uuid.uuid4().hex[:12]}"
    conn.execute(
        """
        INSERT INTO recognition_runs (
            recognition_id, region_id, modality, engine, raw_output,
            normalized_output, confidence, status
        ) VALUES (?, ?, ?, 'fixture_ocr_v1', ?, ?, 1.0, 'completed')
        """,
        (recognition_id, region_id, modality, raw_output, raw_output),
    )
    audit(conn, "recognize_content", recognition_id, region_id)
    conn.commit()
    return {
        "recognition_id": recognition_id,
        "region_id": region_id,
        "modality": modality,
        "engine": "fixture_ocr_v1",
        "raw_output": raw_output,
        "normalized_output": raw_output,
        "confidence": 1.0,
        "status": "completed",
    }


def extract_editable_text(conn, region_id, include_latex=True):
    """Return recognized question content in an editable Markdown shape."""
    if real_ocr_mode():
        return {
            "region_id": region_id,
            "text": latest_real_text(conn, region_id),
            "format": "markdown",
        }
    row = conn.execute(
        """
        SELECT statement, latex
        FROM recognition_ground_truth
        WHERE region_id = ?
        """,
        (region_id,),
    ).fetchone()
    if row is None:
        raise LookupError(f"Unknown region: {region_id}")

    statement, latex = row
    if not statement and not latex:
        raise ValueError(f"No editable text for region: {region_id}")

    result = {
        "region_id": region_id,
        "text": statement or latex or "",
        "format": "markdown",
    }
    if include_latex:
        result["latex"] = latex or ""
    return result


def assess_content_completeness(conn, region_id):
    """Assess fixture completeness without claiming pixel-level inspection."""
    if real_ocr_mode():
        text = latest_real_text(conn, region_id)
        uncertain = "[UNK]" in text or "\ufffd" in text
        return {
            "region_id": region_id,
            "is_complete": None,
            "missing_parts": ["OCR uncertain content"] if uncertain else [],
            "confidence": None,
            "needs_user_action": uncertain,
            "status": "requires_visual_review",
        }
    row = conn.execute(
        """
        SELECT gt.statement, gt.latex, gt.annotation_status,
               gt.requires_confirmation, r.status
        FROM artifact_regions AS r
        LEFT JOIN recognition_ground_truth AS gt ON gt.region_id = r.region_id
        WHERE r.region_id = ?
        """,
        (region_id,),
    ).fetchone()
    if row is None:
        raise LookupError(f"Unknown region: {region_id}")

    statement, latex, annotation_status, requires_confirmation, region_status = row
    missing_parts = []
    if not statement and not latex:
        missing_parts.append("题目识别文本")
    if annotation_status != "verified":
        missing_parts.append("已验证标注")
    if region_status == "rejected":
        missing_parts.append("有效题目区域")

    is_complete = not missing_parts and not requires_confirmation
    return {
        "region_id": region_id,
        "is_complete": is_complete,
        "missing_parts": missing_parts,
        "confidence": 1.0 if is_complete else 0.0,
        "needs_user_action": not is_complete,
    }
