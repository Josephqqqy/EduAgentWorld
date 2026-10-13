import json
import sys
import unittest
from pathlib import Path


ENV_DIR = Path(__file__).resolve().parents[1]
if str(ENV_DIR) not in sys.path:
    sys.path.insert(0, str(ENV_DIR))


class BindingTests(unittest.TestCase):
    def test_resolve_binding_reads_nested_saved_output(self):
        from sandbox.bindings import resolve_value

        scope = {"upload": {"artifact_id": "art_0012"}}

        self.assertEqual(
            resolve_value("$upload.artifact_id", scope),
            "art_0012",
        )

    def test_resolve_binding_rejects_unknown_root(self):
        from sandbox.bindings import BindingResolutionError, resolve_value

        with self.assertRaisesRegex(
            BindingResolutionError,
            "Unknown binding root",
        ):
            resolve_value("$missing.artifact_id", {})


class SandboxRunnerTests(unittest.TestCase):
    def _multi_problem_task(self):
        return {
            "task_id": "task_test_multi",
            "environment": "A1_multimodal_learning_understanding",
            "instruction": "处理图片中的全部题目并分别提交答案。",
            "execution_plan": [
                {
                    "call_id": "call_001",
                    "tool": "upload_artifact",
                    "arguments": {
                        "user_id": "student_task_user",
                        "fixture_path": "raw/assets/12.jpg",
                    },
                    "save_as": "upload",
                },
                {
                    "call_id": "call_002",
                    "tool": "list_artifact_regions",
                    "arguments": {
                        "artifact_id": "$upload.artifact_id",
                    },
                    "save_as": "regions",
                },
                {
                    "call_id": "call_003",
                    "tool": "get_problem_context",
                    "arguments": {
                        "region_id": "$item.region_id",
                    },
                    "save_as": "contexts",
                    "for_each": "$regions",
                },
                {
                    "call_id": "call_004",
                    "tool": "submit_solution",
                    "arguments": {
                        "region_id": "$item.region_id",
                        "final_answer": "$agent.final_answer",
                        "reasoning": "$agent.reasoning",
                    },
                    "save_as": "submissions",
                    "for_each": "$regions",
                },
            ],
        }

    def test_execute_task_iterates_and_evaluates_every_problem_region(self):
        from sandbox.runner import execute_task

        result = execute_task(self._multi_problem_task(), env_dir=ENV_DIR)

        self.assertEqual(result["status"], "passed")
        self.assertEqual(result["region_iterations"], 6)
        self.assertEqual(len(result["evaluations"]), 3)
        self.assertTrue(
            all(item["task_completed"] for item in result["evaluations"])
        )
        submit_trace = next(
            item for item in result["trace"] if item["tool"] == "submit_solution"
        )
        self.assertEqual(len(submit_trace["observations"]), 3)

    def test_execute_task_records_missing_fixture_without_raising(self):
        from sandbox.runner import execute_task

        task = self._multi_problem_task()
        task["task_id"] = "task_test_missing_fixture"
        task["execution_plan"][0]["arguments"]["fixture_path"] = (
            "raw/assets/not_found.png"
        )

        result = execute_task(task, env_dir=ENV_DIR)

        self.assertEqual(result["status"], "failed")
        self.assertEqual(len(result["errors"]), 1)
        self.assertEqual(result["errors"][0]["call_id"], "call_001")
        self.assertEqual(result["errors"][0]["error_type"], "FileNotFoundError")

    def test_batch_validation_continues_after_a_failed_task(self):
        from sandbox.runner import validate_tasks

        failed_task = self._multi_problem_task()
        failed_task["task_id"] = "task_test_failed"
        failed_task["execution_plan"][0]["arguments"]["fixture_path"] = (
            "raw/assets/not_found.png"
        )
        passed_task = self._multi_problem_task()
        passed_task["task_id"] = "task_test_passed"

        report = validate_tasks([failed_task, passed_task], env_dir=ENV_DIR)

        self.assertEqual(report["summary"]["total"], 2)
        self.assertEqual(report["summary"]["passed"], 1)
        self.assertEqual(report["summary"]["failed"], 1)
        self.assertEqual(
            [item["status"] for item in report["tasks"]],
            ["failed", "passed"],
        )
        json.dumps(report, ensure_ascii=False)


if __name__ == "__main__":
    unittest.main()
