import json
import sqlite3
import sys
import unittest
from pathlib import Path


ENV_DIR = Path(__file__).resolve().parents[1]
SCHEMA_PATH = ENV_DIR / "schema.sql"
if str(ENV_DIR) not in sys.path:
    sys.path.insert(0, str(ENV_DIR))


class SeedTests(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))

    def tearDown(self):
        self.conn.close()

    def test_seed_imports_complete_normalized_dataset(self):
        from seed import seed

        seed(self.conn, ENV_DIR)

        expected_counts = {
            "sources": 30,
            "artifacts": 30,
            "artifact_regions": 32,
            "problems": 32,
            "problem_occurrences": 32,
            "recognition_ground_truth": 32,
            "solutions": 32,
            "solution_steps": 109,
            "solution_knowledge_points": 75,
        }
        for table, expected in expected_counts.items():
            with self.subTest(table=table):
                actual = self.conn.execute(
                    f"SELECT COUNT(*) FROM {table}"
                ).fetchone()[0]
                self.assertEqual(actual, expected)

    def test_seed_preserves_one_artifact_to_many_problems(self):
        from seed import seed

        seed(self.conn, ENV_DIR)

        rows = self.conn.execute(
            """
            SELECT r.region_index, o.problem_id
            FROM problem_occurrences AS o
            JOIN artifact_regions AS r ON r.region_id = o.region_id
            WHERE o.artifact_id = 'art_0012'
            ORDER BY region_index
            """
        ).fetchall()
        self.assertEqual(
            rows,
            [
                (1, "problem_0012_01"),
                (2, "problem_0012_02"),
                (3, "problem_0012_03"),
            ],
        )

        region_count = self.conn.execute(
            """
            SELECT COUNT(*)
            FROM artifact_regions
            WHERE artifact_id = 'art_0012'
            """
        ).fetchone()[0]
        self.assertEqual(region_count, 3)

    def test_seed_stores_multiquiz_boxes_and_valid_json_answers(self):
        from seed import seed

        seed(self.conn, ENV_DIR)

        bbox, bbox_status = self.conn.execute(
            """
            SELECT bbox_json, bbox_status
            FROM artifact_regions
            WHERE region_id = 'region_art_0012_01'
            """
        ).fetchone()
        self.assertEqual(json.loads(bbox), [0, 0, 3193, 170])
        self.assertEqual(bbox_status, "annotated")
        other_bbox = self.conn.execute(
            "SELECT bbox_json FROM artifact_regions WHERE region_id = 'region_art_0016_01'"
        ).fetchone()[0]
        self.assertIsNone(other_bbox)

        invalid_answers = self.conn.execute(
            """
            SELECT COUNT(*)
            FROM solutions
            WHERE json_valid(final_answer_json) = 0
            """
        ).fetchone()[0]
        self.assertEqual(invalid_answers, 0)

        final_answer = self.conn.execute(
            """
            SELECT final_answer_json
            FROM solutions
            WHERE solution_id = 'solution_0029'
            """
        ).fetchone()[0]
        self.assertIsInstance(json.loads(final_answer), dict)

    def test_seed_enables_foreign_key_integrity(self):
        from seed import seed

        seed(self.conn, ENV_DIR)

        self.assertEqual(
            self.conn.execute("PRAGMA foreign_key_check").fetchall(),
            [],
        )


if __name__ == "__main__":
    unittest.main()
