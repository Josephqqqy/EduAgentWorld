import json
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch


ENV_DIR = Path(__file__).resolve().parents[1]
if str(ENV_DIR) not in sys.path:
    sys.path.insert(0, str(ENV_DIR))

from rollout.model_client import ModelResponse, ToolCall


def reply(content=None, calls=(), usage=None):
    raw_calls = [
        {
            "id": call.id,
            "type": "function",
            "function": {
                "name": call.name,
                "arguments": json.dumps(call.arguments, ensure_ascii=False),
            },
        }
        for call in calls
    ]
    message = {"role": "assistant", "content": content}
    if raw_calls:
        message["tool_calls"] = raw_calls
    return ModelResponse(
        message=message,
        content=content,
        tool_calls=tuple(calls),
        finish_reason="tool_calls" if calls else "stop",
        usage=usage or {"total_tokens": 10},
        model="fake-model",
        request_id="fake-request",
        latency_ms=1.0,
    )


def call(name, arguments, index=1):
    return ToolCall(id=f"call-{index}", name=name, arguments=arguments)


class ScriptedClient:
    def __init__(self, actions):
        self.actions = iter(actions)
        self.config = SimpleNamespace(model="fake-model")
        self.requests = []

    def complete(self, messages, *, tools, tool_choice):
        self.requests.append(
            {
                "messages": json.loads(json.dumps(messages, ensure_ascii=False)),
                "tools": tools,
                "tool_choice": tool_choice,
            }
        )
        action = next(self.actions)
        if isinstance(action, Exception):
            raise action
        return action(messages) if callable(action) else action


class RolloutTests(unittest.TestCase):
    def test_real_mode_trajectory_records_non_secret_ocr_configuration(self):
        from rollout.runner import run_task

        task = {
            "task_id": "task_mode_metadata",
            "instruction": "Inspect image",
            "arguments": {"artifact_id": "art_0021", "fixture_path": "raw/assets/21.png"},
        }
        with patch.dict(
            "os.environ",
            {"OCR_MODE": "real", "OCR_PROVIDER": "vision_model",
             "OCR_VISION_MODEL": "vision-test", "OCR_VISION_API_KEY": "SECRET_TEST"},
        ):
            result = run_task(task, ScriptedClient([reply(content="done")]))
        self.assertEqual(result["ocr"], {
            "mode": "real", "provider": "vision_model", "model": "vision-test"
        })
        self.assertNotIn("SECRET_TEST", json.dumps(result))

    def test_private_evaluator_failure_never_reaches_model(self):
        from env import build
        from rollout.runner import run_task

        task = {
            "task_id": "task_eval_failure",
            "instruction": "解答图片中的题目",
            "arguments": {"artifact_id": "art_0021", "fixture_path": "raw/assets/21.png"},
            "rubric": {"required_tools": ["submit_solution"]},
        }
        environment = build()
        region = environment["conn"].execute(
            "SELECT region_id FROM artifact_regions WHERE artifact_id = ? LIMIT 1",
            ("art_0021",),
        ).fetchone()[0]

        def broken_evaluation(submission):
            raise RuntimeError("PRIVATE_REFERENCE_ANSWER")

        environment["evaluate"] = broken_evaluation
        client = ScriptedClient([
            reply(calls=(call("submit_solution", {
                "region_id": region, "final_answer": "42", "reasoning": "尝试求解"
            }),)),
            reply(content="已提交"),
        ])
        try:
            with patch("rollout.runner.build", return_value=environment):
                result = run_task(task, client)
        finally:
            environment["close"]()
        self.assertEqual(result["status"], "error")
        self.assertEqual(result["steps"][1]["status"], "completed")
        self.assertNotIn("PRIVATE_REFERENCE_ANSWER", json.dumps(client.requests))
        self.assertNotIn("PRIVATE_REFERENCE_ANSWER", json.dumps(result))
        self.assertEqual(result["termination_reason"], "private_evaluation_error")
        self.assertEqual(len(client.requests), 1)

    def test_rejects_other_artifact_and_region_ids(self):
        from env import build
        from rollout.runner import run_task

        environment = build()
        try:
            other_region = environment["conn"].execute(
                "SELECT region_id FROM artifact_regions WHERE artifact_id = ? LIMIT 1",
                ("art_0012",),
            ).fetchone()[0]
        finally:
            environment["close"]()
        task = {
            "task_id": "task_foreign",
            "instruction": "检查图片",
            "arguments": {"artifact_id": "art_0021", "fixture_path": "raw/assets/21.png"},
        }
        client = ScriptedClient([
            reply(calls=(
                call("get_artifact", {"artifact_id": "art_0012"}, 1),
                call("get_problem_context", {"region_id": other_region}, 2),
            )),
            reply(content="完成"),
        ])
        result = run_task(task, client)
        self.assertEqual([step["status"] for step in result["steps"] if step["type"] == "tool"],
                         ["error", "error"])
        self.assertEqual(result["status"], "completed")

    def test_partial_multi_problem_submission_is_incomplete(self):
        from env import build
        from rollout.runner import run_task

        environment = build()
        try:
            region = environment["conn"].execute(
                "SELECT region_id FROM artifact_regions WHERE artifact_id = ? LIMIT 1",
                ("art_0012",),
            ).fetchone()[0]
        finally:
            environment["close"]()
        task = {
            "task_id": "task_partial",
            "instruction": "逐题解答",
            "arguments": {"artifact_id": "art_0012", "fixture_path": "raw/assets/12.png"},
            "rubric": {"required_tools": ["submit_solution"]},
        }
        client = ScriptedClient([
            reply(calls=(call("submit_solution", {
                "region_id": region, "final_answer": "incorrect", "reasoning": "尝试"
            }),)),
            reply(content="已结束"),
        ])
        result = run_task(task, client)
        self.assertEqual(result["status"], "incomplete")
        self.assertEqual(result["evaluation"]["submitted_regions"], 1)
        self.assertEqual(result["evaluation"]["expected_regions"], 3)

    def test_schemas_match_public_tools_and_exclude_internal_arguments(self):
        from env import build
        from rollout.tool_specs import TOOL_SCHEMAS

        environment = build()
        try:
            self.assertEqual(
                {item["function"]["name"] for item in TOOL_SCHEMAS},
                set(environment["tools"]),
            )
            self.assertNotIn("evaluate_submission", str(TOOL_SCHEMAS))
            for item in TOOL_SCHEMAS:
                parameters = item["function"]["parameters"]
                self.assertNotIn("conn", parameters["properties"])
                self.assertFalse(parameters["additionalProperties"])
        finally:
            environment["close"]()

    def test_public_task_only_is_sent_to_model_and_trace_is_saved(self):
        from rollout.runner import run_task

        client = ScriptedClient(
            [
                reply(calls=(call("upload_artifact", {
                    "user_id": "student_task_user",
                    "fixture_path": "raw/assets/21.png",
                }),)),
                reply(calls=(call("list_artifact_regions", {
                    "artifact_id": "art_0021"
                }),)),
                reply(content="图片包含一道题，已整理。"),
            ]
        )
        task = {
            "task_id": "task_public",
            "instruction": "整理图片中的题目",
            "arguments": {
                "artifact_id": "art_0021",
                "fixture_path": "raw/assets/21.png",
            },
            "execution_plan": [{"private_marker": "hidden-plan"}],
            "raw_walk": ["hidden-walk"],
            "rubric": {"private_marker": "hidden-rubric", "required_tools": []},
        }
        with TemporaryDirectory() as directory:
            path = Path(directory) / "trajectory.json"
            result = run_task(task, client, output_path=path)
            saved = json.loads(path.read_text(encoding="utf-8"))

        self.assertEqual(result["status"], "completed")
        self.assertEqual(saved, result)
        self.assertEqual(result["usage"]["total_tokens"], 30)
        self.assertEqual(result["final_submission"], {})
        self.assertIn(
            "submit_solution",
            {
                item["function"]["name"]
                for item in client.requests[0]["tools"]
            },
        )
        self.assertEqual(
            [step["step_id"] for step in result["steps"]],
            ["step_0001", "step_0002", "step_0003", "step_0004", "step_0005"],
        )
        self.assertEqual(result["task"], {
            "instruction": task["instruction"],
            "arguments": task["arguments"],
        })
        sent = json.dumps(client.requests, ensure_ascii=False)
        self.assertIn("raw/assets/21.png", sent)
        for marker in ("hidden-plan", "hidden-walk", "hidden-rubric"):
            self.assertNotIn(marker, sent)
            self.assertNotIn(marker, json.dumps(saved, ensure_ascii=False))
        self.assertEqual(client.requests[-1]["messages"][-1]["role"], "tool")

    def test_multi_problem_submission_is_evaluated_privately(self):
        from rollout.runner import run_task

        def submit_all(messages):
            regions = json.loads(messages[-1]["content"])
            return reply(calls=tuple(
                call(
                    "submit_solution",
                    {"region_id": region["region_id"],
                     "final_answer": "incorrect",
                     "reasoning": "A model-generated attempt."},
                    index=index,
                )
                for index, region in enumerate(regions, start=1)
            ))

        client = ScriptedClient([
            reply(calls=(call("list_artifact_regions", {"artifact_id": "art_0012"}),)),
            submit_all,
            reply(content="已经逐题提交。"),
        ])
        task = {
            "task_id": "task_multi",
            "instruction": "请分别解答所有题目",
            "arguments": {
                "artifact_id": "art_0012",
                "fixture_path": "raw/assets/12.jpg",
            },
            "rubric": {"required_tools": ["submit_solution"]},
        }
        result = run_task(task, client)

        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["termination_reason"], "answer_incorrect")
        self.assertEqual(result["evaluation"]["submitted_regions"], 3)
        self.assertEqual(result["evaluation"]["expected_regions"], 3)
        self.assertFalse(result["evaluation"]["all_answers_correct"])
        self.assertEqual(len(result["final_submission"]), 3)
        self.assertEqual(len(client.requests), 2)
        sent = json.dumps(client.requests, ensure_ascii=False)
        self.assertNotIn("answer_correct", sent)
        self.assertNotIn("reward", sent)
        self.assertNotIn("required_tools", sent)

    def test_required_region_tools_complete_without_an_extra_model_turn(self):
        from rollout.runner import run_task

        def analyze_all(messages):
            regions = json.loads(messages[-1]["content"])
            return reply(calls=tuple(
                call(
                    "analyze_problem_knowledge",
                    {"region_id": region["region_id"]},
                    index=index,
                )
                for index, region in enumerate(regions, start=1)
            ))

        client = ScriptedClient([
            reply(calls=(call("list_artifact_regions", {"artifact_id": "art_0012"}),)),
            analyze_all,
            reply(content="This response must not be requested."),
        ])
        task = {
            "task_id": "task_region_completion",
            "instruction": "Analyze the knowledge points for every problem.",
            "arguments": {
                "artifact_id": "art_0012",
                "fixture_path": "raw/assets/12.png",
            },
            "rubric": {
                "required_tools": [
                    "list_artifact_regions",
                    "analyze_problem_knowledge",
                ],
            },
        }

        result = run_task(task, client)

        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["termination_reason"], "required_tools_completed")
        self.assertEqual(len(client.requests), 2)

    def test_model_stop_with_missing_required_tools_is_incomplete(self):
        from rollout.runner import run_task

        client = ScriptedClient([
            reply(calls=(call("list_artifact_regions", {
                "artifact_id": "art_0021"
            }),)),
            reply(content="我先结束。"),
        ])
        task = {
            "task_id": "task_missing_requirement",
            "instruction": "识别图片中的题目。",
            "arguments": {
                "artifact_id": "art_0021",
                "fixture_path": "raw/assets/21.png",
            },
            "rubric": {
                "required_tools": [
                    "list_artifact_regions",
                    "get_artifact_problem_contexts",
                ],
            },
        }

        result = run_task(task, client)

        self.assertEqual(result["status"], "incomplete")
        self.assertEqual(result["termination_reason"], "rubric_incomplete")
        self.assertEqual(
            result["evaluation"]["rubric_check"]["missing_tools"],
            ["get_artifact_problem_contexts"],
        )

    def test_forbidden_submission_is_not_completed(self):
        from rollout.runner import run_task

        environment = __import__("env").build()
        region = environment["conn"].execute(
            "SELECT region_id FROM artifact_regions WHERE artifact_id = ? LIMIT 1",
            ("art_0021",),
        ).fetchone()[0]
        environment["close"]()
        client = ScriptedClient([
            reply(calls=(
                call("list_artifact_regions", {"artifact_id": "art_0021"}),
                call("submit_solution", {
                    "region_id": region,
                    "final_answer": "42",
                    "reasoning": "不应提交。",
                }, 2),
            )),
        ])
        task = {
            "task_id": "task_forbidden_submission",
            "instruction": "只分析题目，不提交答案。",
            "arguments": {
                "artifact_id": "art_0021",
                "fixture_path": "raw/assets/21.png",
            },
            "rubric": {
                "required_tools": ["list_artifact_regions"],
                "answer_must_not_be_exposed": True,
            },
        }

        result = run_task(task, client)

        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["termination_reason"], "forbidden_submission")
        self.assertTrue(result["evaluation"]["rubric_check"]["forbidden_submission"])

    def test_incorrect_full_submission_is_failed(self):
        from rollout.runner import run_task

        def submit_all(messages):
            regions = json.loads(messages[-1]["content"])
            return reply(calls=tuple(
                call(
                    "submit_solution",
                    {
                        "region_id": region["region_id"],
                        "final_answer": "incorrect",
                        "reasoning": "尝试。",
                    },
                    index=index,
                )
                for index, region in enumerate(regions, start=1)
            ))

        client = ScriptedClient([
            reply(calls=(call("list_artifact_regions", {
                "artifact_id": "art_0012"
            }),)),
            submit_all,
        ])
        task = {
            "task_id": "task_wrong_answer",
            "instruction": "回答全部题目。",
            "arguments": {
                "artifact_id": "art_0012",
                "fixture_path": "raw/assets/12.jpg",
            },
            "rubric": {"required_tools": ["submit_solution"]},
        }

        result = run_task(task, client)

        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["termination_reason"], "answer_incorrect")
        self.assertFalse(result["evaluation"]["all_answers_correct"])

    def test_incorrect_answer_is_failed_even_when_another_tool_is_missing(self):
        from rollout.runner import _finalize_rubric_status

        trajectory = {
            "status": "completed",
            "termination_reason": "model_stop",
        }
        _finalize_rubric_status(
            trajectory,
            {
                "forbidden_submission": False,
                "duplicate_regions": [],
                "submission_required": True,
                "submission_complete": True,
                "all_answers_correct": False,
                "missing_tools": ["recognize_content"],
                "missing_regions": {},
                "acceptable_tool_path_matched": True,
            },
        )

        self.assertEqual(trajectory["status"], "failed")
        self.assertEqual(trajectory["termination_reason"], "answer_incorrect")

    def test_uncertain_answer_has_distinct_terminal_status(self):
        from rollout.runner import _finalize_rubric_status

        trajectory = {"status": "completed", "termination_reason": "model_stop"}
        _finalize_rubric_status(trajectory, {
            "forbidden_submission": False,
            "duplicate_regions": [],
            "submission_required": True,
            "submission_complete": True,
            "all_answers_correct": False,
            "answer_incorrect": False,
            "answer_needs_review": True,
            "invalid_reference": False,
            "missing_tools": [],
            "missing_regions": {},
            "acceptable_tool_path_matched": True,
        })
        self.assertEqual(trajectory["status"], "needs_review")
        self.assertEqual(trajectory["termination_reason"], "answer_equivalence_uncertain")

    def test_optional_uncertain_submission_needs_review(self):
        from rollout.runner import _finalize_rubric_status

        trajectory = {"status": "completed", "termination_reason": "model_stop"}
        _finalize_rubric_status(trajectory, {
            "forbidden_submission": False,
            "duplicate_regions": [],
            "submission_required": False,
            "submission_complete": True,
            "all_answers_correct": True,
            "answer_incorrect": False,
            "answer_needs_review": True,
            "invalid_reference": False,
            "missing_tools": [],
            "missing_regions": {},
            "acceptable_tool_path_matched": True,
        })
        self.assertEqual(trajectory["status"], "needs_review")

    def test_mixed_incorrect_and_uncertain_has_no_final_reward(self):
        from rollout.runner import _rubric_check

        task = {"rubric": {"required_tools": ["submit_solution"]}}
        evaluation = [
            {"region_id": "r1", "verification_status": "incorrect", "task_completed": False},
            {"region_id": "r2", "verification_status": "needs_review", "task_completed": False},
        ]
        check = _rubric_check(
            task, {"r1", "r2"},
            [("submit_solution", {"region_id": "r1"}),
             ("submit_solution", {"region_id": "r2"})],
            ["r1", "r2"], evaluation,
        )
        self.assertTrue(check["answer_incorrect"])
        self.assertTrue(check["answer_needs_review"])
        self.assertIsNone(check["reward_breakdown"]["total_reward"])

    def test_review_survives_turn_limit_after_submission(self):
        from rollout.runner import run_task

        environment = __import__("env").build()
        region = environment["conn"].execute(
            "SELECT region_id FROM artifact_regions WHERE artifact_id = ? LIMIT 1",
            ("art_0011",),
        ).fetchone()[0]
        environment["close"]()
        task = {
            "task_id": "task_review_at_limit",
            "instruction": "Answer the problem",
            "arguments": {"artifact_id": "art_0011", "fixture_path": "raw/assets/11.png"},
            "rubric": {"required_tools": ["submit_solution", "recognize_content"]},
        }
        client = ScriptedClient([reply(calls=(call("submit_solution", {
            "region_id": region,
            "final_answer": "Unstructured proof",
            "reasoning": "Attempted proof",
        }),))])
        outcome = run_task(task, client, max_turns=1)
        self.assertEqual(outcome["status"], "needs_review")
        self.assertEqual(outcome["termination_reason"], "answer_equivalence_uncertain")
        self.assertIsNone(outcome["evaluation"]["rubric_check"]["reward_breakdown"]["total_reward"])

    def test_missing_required_submission_remains_incomplete(self):
        from rollout.runner import _finalize_rubric_status

        trajectory = {
            "status": "completed",
            "termination_reason": "model_stop",
        }
        _finalize_rubric_status(
            trajectory,
            {
                "forbidden_submission": False,
                "duplicate_regions": [],
                "submission_required": True,
                "submission_complete": False,
                "all_answers_correct": False,
                "missing_tools": ["submit_solution"],
                "missing_regions": {"submit_solution": ["region_1"]},
                "acceptable_tool_path_matched": True,
            },
        )

        self.assertEqual(trajectory["status"], "incomplete")
        self.assertEqual(trajectory["termination_reason"], "rubric_incomplete")

    def test_duplicate_submission_is_failed(self):
        from rollout.runner import run_task

        environment = __import__("env").build()
        region = environment["conn"].execute(
            "SELECT region_id FROM artifact_regions WHERE artifact_id = ? LIMIT 1",
            ("art_0021",),
        ).fetchone()[0]
        environment["close"]()
        submission = {
            "region_id": region,
            "final_answer": "42",
            "reasoning": "尝试。",
        }
        client = ScriptedClient([
            reply(calls=(
                call("submit_solution", submission, 1),
                call("submit_solution", submission, 2),
            )),
        ])
        task = {
            "task_id": "task_duplicate_submission",
            "instruction": "回答题目。",
            "arguments": {
                "artifact_id": "art_0021",
                "fixture_path": "raw/assets/21.png",
            },
            "rubric": {"required_tools": ["submit_solution"]},
        }

        result = run_task(task, client)

        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["termination_reason"], "duplicate_submission")
        self.assertTrue(result["evaluation"]["rubric_check"]["duplicate_regions"])

    def test_rejects_other_fixture_paths_and_recovers_from_tool_error(self):
        from rollout.runner import run_task

        client = ScriptedClient([
            reply(calls=(call("upload_artifact", {
                "user_id": "student_task_user",
                "fixture_path": "../../.env",
            }),)),
            reply(calls=(call("upload_artifact", {
                "user_id": "student_task_user",
                "fixture_path": "raw/assets/21.png",
            }),)),
            reply(content="完成。"),
        ])
        task = {
            "task_id": "task_recover",
            "instruction": "整理图片",
            "arguments": {
                "artifact_id": "art_0021",
                "fixture_path": "raw/assets/21.png",
            },
        }
        result = run_task(task, client)

        self.assertEqual(result["status"], "completed")
        tool_steps = [step for step in result["steps"] if step["type"] == "tool"]
        self.assertEqual(tool_steps[0]["status"], "error")
        self.assertEqual(tool_steps[1]["status"], "completed")
        self.assertNotIn("AGENT_API_KEY", json.dumps(result))

    def test_step_limit_and_model_failure_still_write_trajectory(self):
        from rollout.model_client import ModelClientError
        from rollout.runner import run_task

        task = {
            "task_id": "task_limit",
            "instruction": "检查图片",
            "arguments": {
                "artifact_id": "art_0021",
                "fixture_path": "raw/assets/21.png",
            },
        }
        client = ScriptedClient([
            reply(calls=(call("get_artifact", {"artifact_id": "art_0021"}),)),
        ])
        with TemporaryDirectory() as directory:
            path = Path(directory) / "limit.json"
            limited = run_task(task, client, output_path=path, max_turns=1)
            self.assertEqual(limited["status"], "step_limit")
            self.assertEqual(limited["termination_reason"], "max_turns")
            self.assertEqual(json.loads(path.read_text(encoding="utf-8")), limited)

            failed = run_task(
                task,
                ScriptedClient([
                    ModelClientError(
                        "Model API connection failed: TimeoutError",
                        category="connection",
                        details={"exception_type": "TimeoutError"},
                    )
                ]),
                output_path=path,
            )
            self.assertEqual(failed["status"], "error")
            self.assertEqual(failed["termination_reason"], "model_error")
            self.assertEqual(json.loads(path.read_text(encoding="utf-8")), failed)
            self.assertEqual(failed["errors"][0], {
                "type": "ModelClientError",
                "category": "connection",
                "message": "Model API connection failed: TimeoutError",
                "details": {"exception_type": "TimeoutError"},
            })


if __name__ == "__main__":
    unittest.main()
