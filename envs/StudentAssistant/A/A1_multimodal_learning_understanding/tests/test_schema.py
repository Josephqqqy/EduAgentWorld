import sqlite3
import unittest
from pathlib import Path


ENV_DIR = Path(__file__).resolve().parents[1]
SCHEMA_PATH = ENV_DIR / "schema.sql"


class SchemaTests(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))

    def tearDown(self):
        self.conn.close()

    def test_schema_contains_normalized_problem_and_solution_tables(self):
        table_names = {
            row[0]
            for row in self.conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }

        self.assertTrue(
            {
                "recognition_ground_truth",
                "problems",
                "problem_occurrences",
                "solutions",
                "solution_steps",
            }.issubset(table_names)
        )

    def test_one_artifact_can_contain_multiple_unique_regions(self):
        self._insert_source_and_artifact()
        self.conn.execute(
            """
            INSERT INTO artifact_regions (
                region_id, artifact_id, region_index, region_type,
                bbox_status, status
            ) VALUES ('region_0012_01', 'art_0012', 1, 'question',
                      'not_annotated', 'confirmed')
            """
        )
        self.conn.execute(
            """
            INSERT INTO artifact_regions (
                region_id, artifact_id, region_index, region_type,
                bbox_status, status
            ) VALUES ('region_0012_02', 'art_0012', 2, 'question',
                      'not_annotated', 'confirmed')
            """
        )

        with self.assertRaises(sqlite3.IntegrityError):
            self.conn.execute(
                """
                INSERT INTO artifact_regions (
                    region_id, artifact_id, region_index, region_type,
                    bbox_status, status
                ) VALUES ('region_duplicate', 'art_0012', 2, 'question',
                          'not_annotated', 'confirmed')
                """
            )

    def test_problem_occurrence_requires_existing_problem_and_region(self):
        self._insert_source_and_artifact()
        self.conn.execute(
            """
            INSERT INTO artifact_regions (
                region_id, artifact_id, region_index, region_type,
                bbox_status, status
            ) VALUES ('region_0012_01', 'art_0012', 1, 'question',
                      'not_annotated', 'confirmed')
            """
        )

        with self.assertRaises(sqlite3.IntegrityError):
            self.conn.execute(
                """
                INSERT INTO problem_occurrences (
                    occurrence_id, problem_id, artifact_id, region_id,
                    ground_truth_path
                ) VALUES (
                    'occurrence_0012_01', 'missing_problem', 'art_0012',
                    'region_0012_01', 'fixtures/ground_truth/art_0012.json'
                )
                """
            )

    def test_solution_steps_are_ordered_and_unique_per_solution(self):
        self._insert_problem()
        self.conn.execute(
            """
            INSERT INTO solutions (
                solution_id, problem_id, final_answer_json,
                solution_source, verification_status
            ) VALUES (
                'solution_0012', 'problem_0012_01', '"4"',
                'derived_from_verified_statement', 'independently_verified'
            )
            """
        )
        self.conn.execute(
            """
            INSERT INTO solution_steps (
                solution_id, step_no, text
            ) VALUES ('solution_0012', 1, 'first step')
            """
        )

        with self.assertRaises(sqlite3.IntegrityError):
            self.conn.execute(
                """
                INSERT INTO solution_steps (
                    solution_id, step_no, text
                ) VALUES ('solution_0012', 1, 'duplicate step')
                """
            )

    def test_invalid_match_type_is_rejected(self):
        self._insert_source_and_artifact()
        self.conn.execute(
            """
            INSERT INTO learning_objects (
                object_id, artifact_id, object_type, confirmation_status
            ) VALUES ('object_0012_01', 'art_0012', 'question', 'confirmed')
            """
        )

        with self.assertRaises(sqlite3.IntegrityError):
            self.conn.execute(
                """
                INSERT INTO object_matches (
                    match_id, object_id, match_type, status
                ) VALUES (
                    'match_0012_01', 'object_0012_01', 'approximately',
                    'candidate'
                )
                """
            )

    def test_current_annotation_enum_values_are_supported(self):
        self.conn.execute(
            """
            INSERT INTO sources (
                source_id, source_type, verification_status
            ) VALUES ('source_web', 'web_image', 'partially_verified')
            """
        )
        self.conn.execute(
            """
            INSERT INTO problems (
                problem_id, object_type, subject, statement,
                question_type, annotation_status, source_id
            ) VALUES (
                'problem_current_values', 'question', 'math',
                'sample statement', 'constructed_response',
                'verified', 'source_web'
            )
            """
        )
        self.conn.execute(
            """
            INSERT INTO problems (
                problem_id, object_type, subject, statement,
                question_type, annotation_status, source_id
            ) VALUES (
                'problem_current_values_2', 'question', 'math',
                'sample statement', 'proof_and_calculation',
                'verified', 'source_web'
            )
            """
        )

    def _insert_source_and_artifact(self):
        self.conn.execute(
            """
            INSERT INTO sources (
                source_id, source_type, verification_status
            ) VALUES ('source_0012', 'official_exam', 'verified')
            """
        )
        self.conn.execute(
            """
            INSERT INTO artifacts (
                artifact_id, source_id, file_name, media_type, storage_path,
                content_hash, status
            ) VALUES (
                'art_0012', 'source_0012', '12.png', 'image',
                'raw/assets/12.png', 'sha256:test', 'verified'
            )
            """
        )

    def _insert_problem(self):
        self.conn.execute(
            """
            INSERT INTO sources (
                source_id, source_type, verification_status
            ) VALUES ('source_0012', 'official_exam', 'verified')
            """
        )
        self.conn.execute(
            """
            INSERT INTO problems (
                problem_id, object_type, subject, grade_band, statement,
                topic, question_type, source_id, annotation_status
            ) VALUES (
                'problem_0012_01', 'question', 'math', 'high_school',
                'sample statement', 'algebra.inequality', 'fill_blank',
                'source_0012', 'verified'
            )
            """
        )


if __name__ == "__main__":
    unittest.main()
