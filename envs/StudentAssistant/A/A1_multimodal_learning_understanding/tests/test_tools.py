import json
import os
import sqlite3
import sys
import unittest
from pathlib import Path
from unittest.mock import patch


ENV_DIR = Path(__file__).resolve().parents[1]
if str(ENV_DIR) not in sys.path:
    sys.path.insert(0, str(ENV_DIR))


class ToolTests(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.conn.executescript((ENV_DIR / "schema.sql").read_text(encoding="utf-8"))
        from seed import seed

        seed(self.conn, ENV_DIR)

    def tearDown(self):
        self.conn.close()

    def test_tools_are_exported_from_the_tools_package(self):
        import tools
        from tools.artifacts import get_artifact, upload_artifact
        from tools.evaluation import evaluate_submission
        from tools.recognition import (
            assess_content_completeness,
            extract_editable_text,
            list_artifact_regions,
            recognize_content,
        )
        from tools.solving import (
            get_artifact_problem_contexts,
            get_problem_context,
            submit_solution,
        )
        from tools.diagram import analyze_diagram
        from tools.knowledge import analyze_problem_knowledge

        self.assertEqual(tools.upload_artifact, upload_artifact)
        self.assertEqual(tools.get_artifact, get_artifact)
        self.assertEqual(tools.list_artifact_regions, list_artifact_regions)
        self.assertEqual(tools.recognize_content, recognize_content)
        self.assertEqual(tools.extract_editable_text, extract_editable_text)
        self.assertEqual(
            tools.assess_content_completeness, assess_content_completeness
        )
        self.assertEqual(
            tools.get_artifact_problem_contexts, get_artifact_problem_contexts
        )
        self.assertEqual(tools.analyze_diagram, analyze_diagram)
        self.assertEqual(
            tools.analyze_problem_knowledge, analyze_problem_knowledge
        )
        self.assertEqual(tools.get_problem_context, get_problem_context)
        self.assertEqual(tools.submit_solution, submit_solution)
        self.assertEqual(tools.evaluate_submission, evaluate_submission)

    def test_upload_artifact_returns_seeded_fixture_without_duplicate(self):
        from tools import upload_artifact

        image_path = ENV_DIR / "raw" / "assets" / "16.jpg"
        first = upload_artifact(self.conn, "student_001", image_path)
        second = upload_artifact(self.conn, "student_001", image_path)

        self.assertEqual(first["artifact_id"], "art_0016")
        self.assertEqual(first, second)
        count = self.conn.execute(
            "SELECT COUNT(*) FROM artifacts WHERE user_id = ?",
            ("student_001",),
        ).fetchone()[0]
        self.assertEqual(count, 1)

    def test_recognize_content_returns_question_observation_not_solution(self):
        from tools import get_problem_context, recognize_content

        result = recognize_content(
            self.conn, "region_art_0016_01", modality="ocr"
        )

        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["modality"], "ocr")
        self.assertTrue(result["raw_output"])
        self.assertNotIn("ACD", result["raw_output"])
        context = get_problem_context(self.conn, "region_art_0016_01")
        self.assertIn("statement", context)
        self.assertNotIn("final_answer", context)

    def test_vision_model_ocr_sends_image_and_persists_result(self):
        from tools.recognition import recognize_content

        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc_value, traceback):
                return False

            def read(self):
                return json.dumps(
                    {
                        "choices": [
                            {
                                "message": {
                                    "content": "识别出的数学题文本"
                                }
                            }
                        ]
                    },
                    ensure_ascii=False,
                ).encode("utf-8")

        captured = {}

        def fake_urlopen(request, timeout):
            captured["request"] = request
            captured["timeout"] = timeout
            return FakeResponse()

        values = {
            "OCR_MODE": "real",
            "OCR_PROVIDER": "vision_model",
            "OCR_VISION_API_KEY": "test-key",
            "OCR_VISION_BASE_URL": "https://ocr.example.test/v1",
            "OCR_VISION_MODEL": "vision-test-model",
            "OCR_VISION_TIMEOUT": "17",
            "OCR_VISION_TEMPERATURE": "0",
            "OCR_VISION_MAX_TOKENS": "2048",
        }
        with patch.dict(os.environ, values, clear=False), patch(
            "urllib.request.urlopen", side_effect=fake_urlopen
        ):
            result = recognize_content(
                self.conn, "region_art_0016_01", modality="ocr"
            )

        request = captured["request"]
        payload = json.loads(request.data.decode("utf-8"))
        message_content = payload["messages"][0]["content"]
        self.assertEqual(captured["timeout"], 17.0)
        self.assertEqual(
            request.full_url,
            "https://ocr.example.test/v1/chat/completions",
        )
        self.assertEqual(payload["model"], "vision-test-model")
        self.assertEqual(payload["temperature"], 0)
        self.assertEqual(payload["max_tokens"], 2048)
        self.assertEqual(message_content[1]["type"], "image_url")
        self.assertTrue(message_content[1]["image_url"]["url"].startswith("data:image/png;base64,"))
        self.assertEqual(result["engine"], "vision_model_ocr")
        self.assertEqual(result["normalized_output"], "识别出的数学题文本")
        self.assertEqual(result["status"], "completed")
        self.assertNotIn("test-key", json.dumps(result, ensure_ascii=False))
        stored = self.conn.execute(
            """
            SELECT engine, normalized_output, confidence, status
            FROM recognition_runs
            WHERE recognition_id = ?
            """,
            (result["recognition_id"],),
        ).fetchone()
        self.assertEqual(stored, ("vision_model_ocr", "识别出的数学题文本", None, "completed"))

    def test_real_mode_public_context_requires_ocr_and_never_uses_fixture_text(self):
        from tools import extract_editable_text, get_problem_context

        region = "region_art_0016_01"
        with patch.dict(os.environ, {"OCR_MODE": "real"}):
            with self.assertRaises(ValueError):
                get_problem_context(self.conn, region)
            with self.assertRaises(ValueError):
                extract_editable_text(self.conn, region)
            self.conn.execute(
                """
                INSERT INTO recognition_runs
                (recognition_id, region_id, modality, engine, raw_output,
                 normalized_output, status)
                VALUES ('real_test_1', ?, 'ocr', 'vision_model_ocr',
                        'Observed question', 'Observed question', 'completed')
                """,
                (region,),
            )
            context = get_problem_context(self.conn, region)
            editable = extract_editable_text(self.conn, region)
            self.assertEqual(context["statement"], "Observed question")
            self.assertEqual(set(context), {"region_id", "statement", "latex"})
            self.assertEqual(editable["text"], "Observed question")
            self.assertNotIn("latex", editable)

    def test_real_mode_private_evaluation_can_submit_without_public_context(self):
        from tools import evaluate_submission, submit_solution

        with patch.dict(os.environ, {"OCR_MODE": "real"}):
            submission = submit_solution(
                self.conn, "region_art_0016_01", "ACD", "Verified separately"
            )
            result = evaluate_submission(self.conn, submission)
        self.assertTrue(result["answer_correct"])

    def test_multiquiz_image_uses_distinct_crops(self):
        from tools.recognition import _region_image

        images = [
            _region_image(self.conn, f"region_art_0012_{index:02d}")
            for index in (1, 2, 3)
        ]
        self.assertTrue(all(image.width > 0 and image.height > 0 for image in images))
        self.assertLess(sum(image.height for image in images), 2 * 628)
        self.assertEqual(len({image.tobytes()[:4096] for image in images}), 3)

    def test_real_mode_region_listing_hides_annotation_status(self):
        from tools import list_artifact_regions

        with patch.dict(os.environ, {"OCR_MODE": "real"}):
            regions = list_artifact_regions(self.conn, "art_0012")
        self.assertEqual(len(regions), 3)
        self.assertEqual(set(regions[0]), {"region_id", "region_index", "bbox_json"})

    def test_multiple_choice_options_are_available_in_all_text_paths(self):
        from tools import extract_editable_text, get_problem_context, recognize_content

        expected = {
            16: ("A. ∠A₁MA₂=π/6", "B. |MA₁|=2|MA₂|", "C. C的离心率为√13", "D. 当a=√2时，四边形NA₁MA₂的面积为8√3"),
            17: ("A. √2/10", "B. √2/5", "C. 3√2/10", "D. 7√2/10"),
            18: ("A. ∠CAD≥60°", "B. CD≥√3", "C. 当AB⊥CD时，CD⊥平面ABD", "D. 当AB⊥平面ACD时，AC⊥AD"),
            19: ("A. 12", "B. 4√5", "C. 6", "D. √65/2"),
        }
        for number, options in expected.items():
            with self.subTest(image=number):
                region_id = f"region_art_{number:04d}_01"
                texts = (
                    recognize_content(self.conn, region_id)["raw_output"],
                    extract_editable_text(self.conn, region_id)["text"],
                    get_problem_context(self.conn, region_id)["statement"],
                )
                for text in texts:
                    for option in options:
                        self.assertIn(option, text)

    def test_one_artifact_can_expose_multiple_regions(self):
        from tools import list_artifact_regions

        regions = list_artifact_regions(self.conn, "art_0012")

        self.assertEqual(
            [region["region_id"] for region in regions],
            [
                "region_art_0012_01",
                "region_art_0012_02",
                "region_art_0012_03",
            ],
        )

    def test_artifact_problem_contexts_cover_each_question_in_order(self):
        from tools import get_artifact_problem_contexts

        contexts = get_artifact_problem_contexts(self.conn, "art_0012")

        self.assertEqual(len(contexts), 3)
        self.assertEqual(
            [context["region_id"] for context in contexts],
            [
                "region_art_0012_01",
                "region_art_0012_02",
                "region_art_0012_03",
            ],
        )
        self.assertTrue(all("final_answer" not in item for item in contexts))

    def test_extract_editable_text_returns_markdown_text_and_latex(self):
        from tools import extract_editable_text

        result = extract_editable_text(self.conn, "region_art_0016_01")

        self.assertEqual(result["format"], "markdown")
        self.assertTrue(result["text"])
        self.assertIn("latex", result)
        self.assertNotIn("final_answer", result)

    def test_completeness_assessment_reports_verified_fixture_as_complete(self):
        from tools import assess_content_completeness

        result = assess_content_completeness(self.conn, "region_art_0016_01")

        self.assertTrue(result["is_complete"])
        self.assertEqual(result["missing_parts"], [])
        self.assertFalse(result["needs_user_action"])

    def test_completeness_assessment_reports_missing_fixture_content(self):
        from tools import assess_content_completeness

        self.conn.execute(
            """
            INSERT INTO artifacts (
                artifact_id, file_name, media_type, storage_path, content_hash
            ) VALUES ('art_empty', 'empty.png', 'image', 'empty.png', 'sha256:empty')
            """
        )
        self.conn.execute(
            """
            INSERT INTO artifact_regions (
                region_id, artifact_id, region_index, region_type
            ) VALUES ('region_empty', 'art_empty', 1, 'question')
            """
        )
        self.conn.commit()

        result = assess_content_completeness(self.conn, "region_empty")

        self.assertFalse(result["is_complete"])
        self.assertIn("题目识别文本", result["missing_parts"])
        self.assertTrue(result["needs_user_action"])

    def test_diagram_analysis_is_explicit_about_fixture_limitations(self):
        from tools import analyze_diagram

        result = analyze_diagram(self.conn, "region_art_0011_01")

        self.assertTrue(result["has_diagram"])
        self.assertEqual(result["diagram_type"], "geometry")
        self.assertEqual(result["entities"], [])
        self.assertEqual(result["relations"], [])
        self.assertEqual(result["status"], "metadata_only")

    def test_knowledge_analysis_returns_topics_without_solution_answer(self):
        from tools import analyze_problem_knowledge

        result = analyze_problem_knowledge(self.conn, "region_art_0016_01")

        self.assertEqual(result["subject"], "math")
        self.assertTrue(result["knowledge_points"])
        self.assertNotIn("final_answer", result)
        self.assertNotIn("solution_steps", result)

    def test_submission_is_evaluated_against_hidden_solution(self):
        from tools import evaluate_submission, submit_solution

        submission = submit_solution(
            self.conn,
            "region_art_0016_01",
            final_answer="ACD",
            reasoning="逐项判断后，正确选项为 A、C、D。",
        )

        self.assertEqual(submission["status"], "submitted")
        evaluation = evaluate_submission(self.conn, submission)
        self.assertTrue(evaluation["answer_correct"])
        self.assertTrue(evaluation["reasoning_present"])
        self.assertTrue(evaluation["task_completed"])
        self.assertEqual(evaluation["reward"], 1.0)

    def test_wrong_submission_is_not_marked_complete(self):
        from tools import evaluate_submission, submit_solution

        submission = submit_solution(
            self.conn,
            "region_art_0016_01",
            final_answer="ABC",
            reasoning="我选择了前三项。",
        )

        evaluation = evaluate_submission(self.conn, submission)

        self.assertFalse(evaluation["answer_correct"])
        self.assertTrue(evaluation["reasoning_present"])
        self.assertFalse(evaluation["task_completed"])
        self.assertEqual(evaluation["reward"], 0.0)

    def test_uncertain_submission_is_not_treated_as_wrong(self):
        from tools import evaluate_submission, submit_solution

        submission = submit_solution(
            self.conn, "region_art_0011_01",
            final_answer="A proof with no structured subanswers",
            reasoning="Attempted geometric proof.",
        )
        evaluation = evaluate_submission(self.conn, submission)
        self.assertEqual(evaluation["verification_status"], "needs_review")
        self.assertIsNone(evaluation["answer_correct"])
        self.assertIsNone(evaluation["reward"])
        self.assertFalse(evaluation["task_completed"])

    def test_equivalent_choice_and_count_answer_is_accepted(self):
        from tools import evaluate_submission, submit_solution

        submission = submit_solution(
            self.conn,
            "region_art_0010_01",
            final_answer="（B）2",
            reasoning="判断可得第②、③项正确，因此共有2个正确结论，选择B。",
        )

        evaluation = evaluate_submission(self.conn, submission)

        self.assertTrue(evaluation["answer_correct"])
        self.assertTrue(evaluation["task_completed"])

    def test_different_choice_and_count_answer_is_rejected(self):
        from tools import evaluate_submission, submit_solution

        submission = submit_solution(
            self.conn,
            "region_art_0010_01",
            final_answer="（A）1",
            reasoning="我判断只有一个结论正确，因此选择A。",
        )

        evaluation = evaluate_submission(self.conn, submission)

        self.assertFalse(evaluation["answer_correct"])
        self.assertFalse(evaluation["task_completed"])

    def test_choice_answer_includes_its_option_value(self):
        from tools import evaluate_submission, submit_solution

        submission = submit_solution(
            self.conn,
            "region_art_0007_01",
            final_answer="D",
            reasoning="选择D。",
        )

        evaluation = evaluate_submission(self.conn, submission)

        self.assertTrue(evaluation["answer_correct"])
        self.assertTrue(evaluation["task_completed"])

    def test_submission_requires_reasoning(self):
        from tools import submit_solution

        with self.assertRaises(ValueError):
            submit_solution(
                self.conn,
                "region_art_0016_01",
                final_answer="ACD",
                reasoning="",
            )


if __name__ == "__main__":
    unittest.main()
