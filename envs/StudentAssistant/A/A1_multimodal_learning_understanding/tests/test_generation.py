import random
import sqlite3
import sys
import unittest
from pathlib import Path
from unittest.mock import patch


ENV_DIR = Path(__file__).resolve().parents[1]
if str(ENV_DIR) not in sys.path:
    sys.path.insert(0, str(ENV_DIR))


class GraphAndGenerationTests(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.conn.executescript((ENV_DIR / "schema.sql").read_text(encoding="utf-8"))
        from seed import seed

        seed(self.conn, ENV_DIR)

    def tearDown(self):
        self.conn.close()

    def test_tool_graph_has_weighted_dependency_edges_and_excludes_evaluator(self):
        from tools.graph import build_tool_graph

        graph = build_tool_graph()
        self.assertIn("upload_artifact", graph.nodes)
        self.assertNotIn("evaluate_submission", graph.nodes)
        self.assertEqual(
            graph.edge("upload_artifact", "list_artifact_regions")["kind"], "strong"
        )
        self.assertEqual(
            graph.edge("upload_artifact", "list_artifact_regions")["weight"], 3
        )
        self.assertEqual(
            graph.edge("recognize_content", "analyze_diagram")["kind"], "weak"
        )
        self.assertEqual(
            graph.edge("recognize_content", "analyze_diagram")["weight"], 2
        )
        self.assertEqual(
            graph.edge("get_artifact", "analyze_diagram")["kind"], "independent"
        )
        self.assertEqual(
            graph.edge("get_artifact", "analyze_diagram")["weight"], 1
        )

    def test_random_walk_starts_from_root_and_can_revisit_tools(self):
        from tools.graph import build_tool_graph, random_walk

        graph = build_tool_graph()
        self.assertEqual(
            random_walk(graph, length=5, rng=random.Random(7))[0],
            "upload_artifact",
        )
        sequence = random_walk(graph, length=15, rng=random.Random(9))
        self.assertEqual(len(sequence), 15)
        self.assertLess(len(set(sequence)), len(sequence))

    def test_task_generation_returns_public_instruction_and_hidden_rubric(self):
        from tools.task_generation import generate_task

        task = generate_task(self.conn, rng=random.Random(3), length=5)
        self.assertTrue(task["task_id"].startswith("task_a1_"))
        self.assertTrue(task["instruction"])
        self.assertTrue(task["arguments"]["fixture_path"].startswith("raw/assets/"))
        self.assertEqual(task["tool_sequence"][0], "upload_artifact")
        self.assertIn("required_tools", task["rubric"])
        self.assertNotIn("evaluate_submission", task["tool_sequence"])
        self.assertNotIn("schema.sql", task["instruction"])
        self.assertNotIn("upload_artifact", task["instruction"])
        self.assertEqual(
            [call["tool"] for call in task["execution_plan"]],
            task["tool_sequence"],
        )
        self.assertEqual(
            task["execution_plan"][0]["arguments"]["fixture_path"],
            task["arguments"]["fixture_path"],
        )

    def test_solution_task_allows_answer_submission(self):
        from tools.task_generation import generate_task

        with patch(
            "tools.task_generation.random_walk",
            return_value=[
                "upload_artifact",
                "list_artifact_regions",
                "get_problem_context",
                "submit_solution",
            ],
        ):
            task = generate_task(self.conn, rng=random.Random(3), length=4)
        self.assertIn("submit_solution", task["rubric"]["required_tools"])
        self.assertFalse(task["rubric"]["answer_must_not_be_exposed"])

    def test_rollout_rubric_treats_upload_as_harness_setup(self):
        from tools.task_generation import generate_task

        with patch(
            "tools.task_generation.random_walk",
            return_value=[
                "upload_artifact",
                "list_artifact_regions",
                "recognize_content",
                "submit_solution",
            ],
        ):
            task = generate_task(self.conn, rng=random.Random(3), length=4)

        self.assertNotIn("upload_artifact", task["rubric"]["required_tools"])
        self.assertEqual(
            task["rubric"]["acceptable_tool_paths"],
            [
                ["list_artifact_regions"],
                ["get_artifact_problem_contexts"],
            ],
        )
        self.assertEqual(task["execution_plan"][0]["tool"], "upload_artifact")

    def test_non_solution_task_prohibits_answer_submission(self):
        from tools.task_generation import generate_task

        with patch(
            "tools.task_generation.random_walk",
            return_value=["upload_artifact", "get_artifact"],
        ):
            task = generate_task(self.conn, rng=random.Random(1), length=2)
        self.assertNotIn("submit_solution", task["rubric"]["required_tools"])
        self.assertTrue(task["rubric"]["answer_must_not_be_exposed"])

    def test_refinement_adds_prerequisites_before_region_tools(self):
        from tools.task_generation import refine_tool_sequence

        self.assertEqual(
            refine_tool_sequence(
                ["upload_artifact", "analyze_diagram", "submit_solution"]
            ),
            [
                "upload_artifact",
                "list_artifact_regions",
                "get_problem_context",
                "analyze_diagram",
                "submit_solution",
            ],
        )

    def test_refinement_removes_repeated_submissions_and_keeps_them_terminal(self):
        from tools.task_generation import refine_tool_sequence

        sequence = refine_tool_sequence(
            [
                "upload_artifact",
                "submit_solution",
                "analyze_diagram",
                "submit_solution",
                "get_artifact",
            ]
        )
        self.assertEqual(sequence.count("submit_solution"), 1)
        self.assertEqual(sequence[-1], "submit_solution")
        self.assertLess(sequence.index("get_artifact"), sequence.index("submit_solution"))

    def test_refinement_preserves_repeated_tool_visits(self):
        from tools.task_generation import refine_tool_sequence

        sequence = refine_tool_sequence(
            [
                "upload_artifact",
                "list_artifact_regions",
                "recognize_content",
                "assess_content_completeness",
                "recognize_content",
            ]
        )
        self.assertEqual(sequence.count("recognize_content"), 2)

    def test_instruction_uses_valid_utf8_chinese_without_mojibake(self):
        from tools.task_generation import _instruction

        instruction = _instruction(
            ["upload_artifact", "recognize_content", "recognize_content"]
        )
        self.assertEqual(instruction.count("识别题目内容和数学表达式"), 1)
        self.assertNotIn("璇嗗埆", instruction)
        self.assertIn("请处理", instruction)

    def test_execution_plan_uses_previous_outputs_for_dependent_arguments(self):
        from tools.task_generation import build_execution_plan

        plan = build_execution_plan(
            [
                "upload_artifact",
                "list_artifact_regions",
                "recognize_content",
                "get_problem_context",
                "submit_solution",
            ],
            fixture_path="raw/assets/12.jpg",
        )
        self.assertEqual(plan[1]["arguments"]["artifact_id"], "$upload.artifact_id")
        self.assertEqual(plan[0]["save_as"], "upload")
        self.assertEqual(plan[1]["save_as"], "regions")
        self.assertEqual(plan[0]["call_id"], "call_001")
        self.assertEqual(plan[1]["call_id"], "call_002")
        self.assertEqual(plan[2]["for_each"], "$regions")
        self.assertEqual(plan[2]["arguments"]["region_id"], "$item.region_id")
        self.assertEqual(plan[4]["arguments"]["final_answer"], "$agent.final_answer")
        self.assertEqual(plan[4]["arguments"]["reasoning"], "$agent.reasoning")

    def test_execution_plan_batches_submission_over_all_regions(self):
        from tools.task_generation import build_execution_plan

        plan = build_execution_plan(
            [
                "upload_artifact",
                "list_artifact_regions",
                "recognize_content",
                "submit_solution",
                "submit_solution",
            ],
            fixture_path="raw/assets/12.jpg",
        )
        submissions = [call for call in plan if call["tool"] == "submit_solution"]
        self.assertEqual(len(submissions), 1)
        self.assertEqual(submissions[0]["for_each"], "$regions")
        self.assertEqual(
            submissions[0]["arguments"]["region_id"], "$item.region_id"
        )

    def test_execution_plan_has_legal_bindings_and_dependency_order(self):
        from tools.task_generation import build_execution_plan

        plan = build_execution_plan(
            [
                "upload_artifact",
                "get_artifact",
                "list_artifact_regions",
                "recognize_content",
                "get_problem_context",
                "analyze_diagram",
                "submit_solution",
            ],
            fixture_path="raw/assets/12.jpg",
        )
        positions = {call["tool"]: index for index, call in enumerate(plan)}
        self.assertLess(
            positions["upload_artifact"], positions["list_artifact_regions"]
        )
        self.assertLess(
            positions["list_artifact_regions"], positions["recognize_content"]
        )
        self.assertLess(
            positions["recognize_content"], positions["get_problem_context"]
        )
        self.assertLess(positions["get_problem_context"], positions["analyze_diagram"])

        allowed_roots = {"$upload", "$regions", "$item", "$agent"}
        region_tools = {
            "recognize_content",
            "extract_editable_text",
            "assess_content_completeness",
            "get_problem_context",
            "analyze_diagram",
            "analyze_problem_knowledge",
            "submit_solution",
        }
        for call in plan:
            for value in call["arguments"].values():
                if isinstance(value, str) and value.startswith("$"):
                    self.assertIn(value.split(".", 1)[0], allowed_roots)
            if call["tool"] in region_tools:
                self.assertEqual(call["for_each"], "$regions")
            else:
                self.assertNotIn("for_each", call)

    def test_call_level_pruning_removes_only_redundant_read_calls(self):
        from tools.task_generation import prune_redundant_calls

        plan = [
            {
                "call_id": "call_001",
                "tool": "recognize_content",
                "arguments": {"region_id": "$item.region_id", "modality": "ocr"},
                "for_each": "$regions",
            },
            {
                "call_id": "call_002",
                "tool": "recognize_content",
                "arguments": {"region_id": "$item.region_id", "modality": "ocr"},
                "for_each": "$regions",
            },
            {
                "call_id": "call_003",
                "tool": "recognize_content",
                "arguments": {"region_id": "$item.region_id", "modality": "vision"},
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
                "for_each": "$regions",
            },
            {
                "call_id": "call_005",
                "tool": "submit_solution",
                "arguments": {
                    "region_id": "$item.region_id",
                    "final_answer": "$agent.final_answer",
                    "reasoning": "$agent.reasoning",
                },
                "for_each": "$regions",
            },
        ]
        pruned = prune_redundant_calls(plan)
        self.assertEqual(
            [call["tool"] for call in pruned],
            ["recognize_content", "recognize_content", "submit_solution"],
        )

    def test_call_level_pruning_removes_duplicate_idempotent_uploads(self):
        from tools.task_generation import prune_redundant_calls

        plan = [
            {
                "call_id": "call_001",
                "tool": "upload_artifact",
                "arguments": {
                    "user_id": "student_task_user",
                    "fixture_path": "raw/assets/12.jpg",
                },
            },
            {
                "call_id": "call_002",
                "tool": "get_artifact",
                "arguments": {"artifact_id": "$upload.artifact_id"},
            },
            {
                "call_id": "call_003",
                "tool": "upload_artifact",
                "arguments": {
                    "user_id": "student_task_user",
                    "fixture_path": "raw/assets/12.jpg",
                },
            },
            {
                "call_id": "call_004",
                "tool": "get_artifact",
                "arguments": {"artifact_id": "$upload.artifact_id"},
            },
        ]
        pruned = prune_redundant_calls(plan)
        self.assertEqual(
            [call["tool"] for call in pruned], ["upload_artifact", "get_artifact"]
        )

    def test_generate_tasks_can_create_reproducible_batch(self):
        from tools.task_generation import generate_tasks

        tasks = generate_tasks(self.conn, count=4, seed=11, length=4)
        self.assertEqual(len(tasks), 4)
        self.assertEqual(
            [task["task_id"] for task in tasks],
            [
                "task_a1_000001",
                "task_a1_000002",
                "task_a1_000003",
                "task_a1_000004",
            ],
        )
        self.assertTrue(
            all(task["tool_sequence"][0] == "upload_artifact" for task in tasks)
        )

    def test_generate_tasks_accepts_one_length_per_task(self):
        from tools.task_generation import generate_tasks

        tasks = generate_tasks(
            self.conn,
            count=4,
            seed=42,
            length=[5, 8, 13, 21],
        )

        self.assertEqual(
            [len(task["raw_walk"]) for task in tasks],
            [5, 8, 13, 21],
        )

    def test_generated_fixture_paths_exist_in_environment(self):
        from tools.task_generation import generate_tasks

        tasks = generate_tasks(self.conn, count=30, seed=42, length=15)

        missing = [
            task["arguments"]["fixture_path"]
            for task in tasks
            if not (ENV_DIR / task["arguments"]["fixture_path"]).is_file()
        ]
        self.assertEqual(missing, [])


if __name__ == "__main__":
    unittest.main()
