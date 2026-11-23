"""The verifier must inspect untrusted code without executing it."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from hive_control.switchboard import dispatch

CASES = [
    {"input": -100, "expected": -99},
    {"input": -1, "expected": 0},
    {"input": 0, "expected": 1},
    {"input": 1, "expected": 2},
    {"input": 2, "expected": 3},
    {"input": 100, "expected": 101},
]


class SpecialistVerifierTests(unittest.TestCase):
    def test_python_increment_passes_multiple_values_without_execution(self) -> None:
        result = dispatch(
            {
                "op": "specialist_verify",
                "language": "python",
                "code": "def increment(value: int) -> int:\n    return value + 1\n",
                "check": {"cases": CASES},
            }
        )
        self.assertTrue(result["passed"])
        self.assertEqual(result["case_count"], len(CASES))
        self.assertEqual(result["execution"], "not_run_static_ast_contract")

    def test_python_rejects_hardcoded_answer_and_executable_top_level_code(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as folder:
            marker = Path(folder) / "must_not_exist.txt"
            hostile = (
                f"from pathlib import Path\nPath({str(marker)!r}).write_text('ran')\n"
                "def increment(value: int) -> int:\n    return 3\n"
            )
            result = dispatch(
                {
                    "op": "specialist_verify",
                    "language": "python",
                    "code": hostile,
                    "check": {"cases": CASES},
                }
            )
            self.assertFalse(result["passed"])
            self.assertFalse(marker.exists())

    def test_rust_increment_is_compiled_but_never_executed(self) -> None:
        result = dispatch(
            {
                "op": "specialist_verify",
                "language": "rust",
                "code": "fn increment(value: i32) -> i32 {\n    value + 1\n}",
                "check": {"cases": CASES},
            }
        )
        self.assertTrue(result["passed"], result["error"])
        self.assertEqual(result["case_count"], len(CASES))
        self.assertEqual(result["execution"], "compiled_not_run_static_source_contract")

    def test_rust_rejects_additional_executable_source(self) -> None:
        hostile = (
            "fn increment(value: i32) -> i32 { value + 1 }\n"
            "fn main() { std::process::exit(7); }"
        )
        result = dispatch(
            {
                "op": "specialist_verify",
                "language": "rust",
                "code": hostile,
                "check": {"cases": CASES},
            }
        )
        self.assertFalse(result["passed"])
        self.assertIn("bounded Rust increment grammar", result["error"])


if __name__ == "__main__":
    unittest.main()
