#!/usr/bin/env bash

# Run every candidate task in a task JSON and save one trajectory per task.
# Usage:
#   ./run_all_rollouts.sh
#   ./run_all_rollouts.sh generated/tasks_seed_42_validation.json
#
# Optional environment variables:
#   OUTPUT_DIR=generated/rollouts_batch_20260921
#   MAX_TURNS=12
#   MAX_TOOL_CALLS=40
#   MAX_TOTAL_TOKENS=60000
#   MAX_SECONDS=600
#   TASK_FILTER=task_a1_000001
#   PYTHON=/path/to/python  # Override the project virtual environment

set -u
set -o pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../../../../" && pwd)"
if [[ -z "${PYTHON:-}" ]]; then
  if [[ -x "$PROJECT_ROOT/eduworld/Scripts/python.exe" ]]; then
    PYTHON="$PROJECT_ROOT/eduworld/Scripts/python.exe"
  elif [[ -x "$PROJECT_ROOT/eduworld/bin/python" ]]; then
    PYTHON="$PROJECT_ROOT/eduworld/bin/python"
  else
    echo "eduworld virtual environment not found; set PYTHON explicitly" >&2
    exit 2
  fi
fi
cd "$SCRIPT_DIR" || exit 1

SOURCE="${1:-generated/tasks_seed_42.json}"
OUTPUT_DIR="${OUTPUT_DIR:-generated/rollouts}"
MAX_TURNS="${MAX_TURNS:-12}"
MAX_TOOL_CALLS="${MAX_TOOL_CALLS:-40}"
MAX_TOTAL_TOKENS="${MAX_TOTAL_TOKENS:-60000}"
MAX_SECONDS="${MAX_SECONDS:-600}"
TASK_FILTER="${TASK_FILTER:-}"

if [[ ! -f "$SOURCE" ]]; then
  echo "Task source does not exist: $SOURCE" >&2
  exit 2
fi

mkdir -p "$OUTPUT_DIR"

mapfile -t TASK_IDS < <(
  "$PYTHON" - "$SOURCE" "$TASK_FILTER" <<'PY'
import json
import sys

source_path = sys.argv[1]
task_filter = sys.argv[2]

with open(source_path, "r", encoding="utf-8-sig") as handle:
    payload = json.load(handle)

tasks = payload["tasks"] if isinstance(payload, dict) else payload
for task in tasks:
    task_id = task["task_id"]
    if not task_filter or task_id == task_filter:
        print(task_id)
PY
)

if [[ "${#TASK_IDS[@]}" -eq 0 ]]; then
  echo "No tasks found in $SOURCE" >&2
  exit 3
fi

timestamp="$(date +%Y%m%d_%H%M%S)"
run_dir="$OUTPUT_DIR/batch_$timestamp"
mkdir -p "$run_dir"
summary_path="$run_dir/summary.json"

total="${#TASK_IDS[@]}"
completed=0
incomplete=0
needs_review=0
failed=0
error=0
other=0
index=0

echo "Running $total task(s)"
echo "Source: $SOURCE"
echo "Output: $run_dir"

for task_id in "${TASK_IDS[@]}"; do
  # Python on Windows may emit CRLF; remove the trailing carriage return
  # before using the ID in paths and command arguments.
  task_id="${task_id//$'\r'/}"
  index=$((index + 1))
  output_path="$run_dir/${task_id}.json"
  echo "[$index/$total] $task_id"

  if "$PYTHON" -m rollout.runner \
      "$SOURCE" \
      --task-id "$task_id" \
      --output "$output_path" \
      --max-turns "$MAX_TURNS" \
      --max-tool-calls "$MAX_TOOL_CALLS" \
      --max-total-tokens "$MAX_TOTAL_TOKENS" \
      --max-seconds "$MAX_SECONDS"; then
    status="$("$PYTHON" - "$output_path" <<'PY'
import json
import sys

with open(sys.argv[1], "r", encoding="utf-8") as handle:
    print(json.load(handle).get("status", "unknown"))
PY
)"
  else
    status="$("$PYTHON" - "$output_path" <<'PY'
import json
import sys

try:
    with open(sys.argv[1], "r", encoding="utf-8") as handle:
        print(json.load(handle).get("status", "process_error"))
except Exception:
    print("process_error")
PY
)"
  fi

  case "$status" in
    completed) completed=$((completed + 1)) ;;
    incomplete) incomplete=$((incomplete + 1)) ;;
    needs_review) needs_review=$((needs_review + 1)) ;;
    failed) failed=$((failed + 1)) ;;
    error) error=$((error + 1)) ;;
    *) other=$((other + 1)) ;;
  esac
  echo "  status=$status trajectory=$output_path"
done

"$PYTHON" - "$run_dir" "$summary_path" "$SOURCE" "$total" \
  "$completed" "$incomplete" "$needs_review" "$failed" "$error" "$other" <<'PY'
import json
import sys
from pathlib import Path

run_dir = Path(sys.argv[1])
summary_path = Path(sys.argv[2])
source = sys.argv[3]
total, completed, incomplete, needs_review, failed, error, other = map(int, sys.argv[4:11])

tasks = []
for path in sorted(run_dir.glob("task_*.json")):
    with path.open("r", encoding="utf-8") as handle:
        trajectory = json.load(handle)
    tasks.append({
        "task_id": trajectory.get("task_id"),
        "status": trajectory.get("status"),
        "termination_reason": trajectory.get("termination_reason"),
        "trajectory": str(path),
    })

summary = {
    "source": source,
    "run_directory": str(run_dir),
    "total": total,
    "counts": {
        "completed": completed,
        "incomplete": incomplete,
        "needs_review": needs_review,
        "failed": failed,
        "error": error,
        "other": other,
    },
    "tasks": tasks,
}
summary_path.write_text(
    json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
    encoding="utf-8",
)
PY

echo
echo "Finished."
echo "completed=$completed incomplete=$incomplete needs_review=$needs_review failed=$failed error=$error other=$other"
echo "summary=$summary_path"

# A batch is useful even when some model rollouts fail. Return non-zero only
# when the script itself could not enumerate or execute the batch.
exit 0
