"""Public trace and private evaluation storage for a single A1 run."""

from __future__ import annotations

import json
import uuid
from pathlib import Path


def new_trajectory(task, model_name):
    return {
        "trajectory_id": f"traj_{uuid.uuid4().hex}",
        "task_id": task["task_id"],
        "model": {"name": model_name},
        "task": {
            "instruction": task["instruction"],
            "arguments": {
                "artifact_id": task["arguments"]["artifact_id"],
                "fixture_path": task["arguments"]["fixture_path"],
            },
        },
        "steps": [],
        "final_submission": {},
        "evaluation": {},
        "usage": {"total_tokens": 0},
        "status": "running",
        "termination_reason": None,
        "errors": [],
    }


def save_trajectory(trajectory, path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(trajectory, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return path
