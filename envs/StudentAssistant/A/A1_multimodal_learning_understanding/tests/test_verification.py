import sys
import unittest
from pathlib import Path

ENV_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ENV_DIR))

from verification import verify_answer


class VerificationTests(unittest.TestCase):
    def check(self, actual, expected, status, question_type="calculation"):
        verdict = verify_answer(actual, expected, question_type=question_type)
        self.assertEqual(verdict["status"], status, verdict)

    def test_numeric_and_units(self):
        reference = {"answer_type": "numeric", "value": "1800", "unit": "\u4eba"}
        self.check("1800\u4eba", reference, "correct")
        self.check("1801\u4eba", reference, "incorrect")
        self.check("1800\u7c73", reference, "incorrect")
        self.check("E(X)=61/25=2.44", {"answer_type": "numeric", "value": "61/25"}, "correct")
        self.check("1800\u4eba", "1800", "correct")

    def test_symbolic(self):
        reference = {"answer_type": "expression", "value": "-3/(4*cbrt(4))"}
        self.check("-3\u221b2/8", reference, "correct")
        self.check("result: 2(e-1)", {"answer_type": "expression", "value": "2*(E-1)"}, "correct")
        self.check("3", {"answer_type": "expression", "value": "4"}, "incorrect")

    def test_interval_and_inequality(self):
        reference = {"answer_type": "interval", "variable": "n", "value": "(4,+infinity)"}
        self.check("n > 4 (\u5373 (4,+\u221e))", reference, "correct")
        self.check("n >= 4", reference, "incorrect")
        self.check("2 < r < 8", {"answer_type": "interval", "variable": "r", "value": "(2,8)"}, "correct")
        self.check("n > 4", "n in (4,+infinity)", "correct")

    def test_choice_and_legacy(self):
        self.check("\u7b54\u6848\uff1aD\u3001B", {"answer_type": "multiple_choice", "value": "BD"}, "correct", "multiple_select")
        self.check("A", "B", "incorrect", "multiple_choice")
        self.check("result contains A", "A", "needs_review")
        self.check("（A）", "D", "incorrect", "multiple_choice")
        self.check("ABC（选 A、B、C）", "BC", "incorrect", "multiple_choice")
        self.check("D. 7√2/10", "D", "correct", "multiple_choice")
        self.check("（D）$\\left(0,\\dfrac{3a}{2\\pi}\\right)$", "D", "correct", "multiple_choice")

    def test_legacy_answers_in_sentences(self):
        self.check("约 1800 人选择出租车。", "1800", "correct")
        self.check("n > 4（即 n 的取值范围是 (4, +∞)）",
                   "n in (4,+infinity)", "correct")
        self.check("n >= 4（即 n 的取值范围是 [4, +∞)）",
                   "n in (4,+infinity)", "incorrect")
        self.check("$$\\iint_D e^{\\frac{|y|}{|x|+|y|}}\\,d\\sigma = e-1$$",
                   "2(e-1)", "incorrect")
        self.check("最大值 $=6$，最小值 $=2$。", "最大值6，最小值2", "correct")
        self.check("最大值6，最小值3", "最大值6，最小值2", "incorrect")

    def test_labeled_multipart_text(self):
        reference = {"answer_type": "multipart", "parts": [
            {"part_id": "part_1", "answer_type": "expression", "value": "1/3"},
            {"part_id": "part_2", "answer_type": "expression", "value": "3sqrt(5)"},
        ]}
        self.check("（1）cosA = 1/3；（2）CE = 3√5。", reference, "correct")
        self.check("（1）cosA = 1/3；（2）CE = 4√5。", reference, "incorrect")
        self.check("（1）cosA = 1/3", reference, "incorrect")
        self.check("cosA = 1/3；CE = 3√5", reference, "needs_review")

    def test_multipart(self):
        reference = {
            "schema_version": "1.0",
            "answer_type": "multipart",
            "parts": [
                {"part_id": "part_1", "answer_type": "expression", "value": "2*pi"},
                {"part_id": "part_2", "answer_type": "numeric", "value": "3"},
            ],
        }
        self.check({"part_1": "2\u03c0", "part_2": "3"}, reference, "correct")
        self.check({"part_1": "2\u03c0"}, reference, "incorrect")
        self.check({"part_1": "2\u03c0", "part_2": "cannot tell"}, reference, "needs_review")
        proof = {"answer_type": "proof_conclusion", "value": "QM parallel plane PBD"}
        self.check("QM parallel plane PBD", proof, "correct", "proof")
        self.check("some argument", proof, "needs_review", "proof")

    def test_review_and_invalid_reference(self):
        self.check("because of symmetry", "proof by geometry", "needs_review", "proof")
        self.check("2", {"answer_type": "numeric"}, "invalid_reference")
        self.check("(1) 2", {"answer_type": "multipart", "parts": [{}]},
                   "invalid_reference")
        self.check("__import__('os').system('echo unsafe')",
                   {"answer_type": "expression", "value": "1"}, "needs_review")
        self.check("9**9**9", {"answer_type": "expression", "value": "1"}, "needs_review")


if __name__ == "__main__":
    unittest.main()
