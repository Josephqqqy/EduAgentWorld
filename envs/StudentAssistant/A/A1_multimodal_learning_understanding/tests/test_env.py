import sqlite3
import sys
import unittest
from pathlib import Path


ENV_DIR = Path(__file__).resolve().parents[1]
if str(ENV_DIR) not in sys.path:
    sys.path.insert(0, str(ENV_DIR))


class EnvironmentTests(unittest.TestCase):
    def test_build_exposes_agent_tools_and_hidden_evaluator(self):
        from env import build

        environment = build()

        self.assertIn("tools", environment)
        self.assertIn("upload_artifact", environment["tools"])
        self.assertIn("recognize_content", environment["tools"])
        self.assertIn("extract_editable_text", environment["tools"])
        self.assertIn("assess_content_completeness", environment["tools"])
        self.assertIn("analyze_diagram", environment["tools"])
        self.assertIn("analyze_problem_knowledge", environment["tools"])
        self.assertIn("get_artifact_problem_contexts", environment["tools"])
        self.assertIn("get_problem_context", environment["tools"])
        self.assertIn("submit_solution", environment["tools"])
        self.assertNotIn("evaluate_submission", environment["tools"])
        self.assertIn("evaluate", environment)
        self.assertNotIn("tool_graph", environment)
        self.assertIsInstance(environment["conn"], sqlite3.Connection)

        environment["close"]()


if __name__ == "__main__":
    unittest.main()
