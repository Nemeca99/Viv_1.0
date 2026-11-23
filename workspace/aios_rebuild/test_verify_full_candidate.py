from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from verify_full_candidate import verify


class FullCandidateVerifierTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.source = self.root / "source"
        self.candidate = self.root / "candidate"
        self.source.mkdir()
        self.candidate.mkdir()

    def tearDown(self) -> None:
        self.temp.cleanup()

    def write_pair(self, path: str, content: bytes) -> dict[str, str | int]:
        for root in (self.source, self.candidate):
            target = root / Path(path)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)
        return {
            "path": path,
            "sha256": hashlib.sha256(content).hexdigest(),
            "bytes": len(content),
        }

    def manifest(self, files: list[dict], exclusions: list[dict] | None = None) -> Path:
        path = self.root / "manifest.json"
        path.write_text(
            json.dumps(
                {
                    "schema": "aios_clean_source_baseline_v1",
                    "files": files,
                    "cores": [{"name": "alpha_core"}],
                    "compile_exclusions": exclusions or [],
                }
            ),
            encoding="utf-8",
        )
        return path

    def test_verifies_full_manifest_and_compiles_nonexcluded_python(self) -> None:
        files = [
            self.write_pair("alpha_core/module.py", b"def answer():\n    return 42\n"),
            self.write_pair("README.md", b"candidate\n"),
        ]
        receipt = verify(self.manifest(files), self.source, self.candidate)
        self.assertEqual(receipt["status"], "PASS")
        self.assertEqual(receipt["manifest_file_count"], 2)
        self.assertEqual(receipt["python_syntax_checked"], 1)
        self.assertFalse(receipt["candidate_executed"])

    def test_known_template_exclusion_is_explicit_and_does_not_hide_other_errors(
        self,
    ) -> None:
        excluded = "alpha_core/template.py"
        regular = "alpha_core/regular.py"
        files = [
            self.write_pair(excluded, b"def broken(:\n"),
            self.write_pair(regular, b"def answer():\n    return 42\n"),
        ]
        receipt = verify(
            self.manifest(files, [{"path": excluded, "reason": "template syntax"}]),
            self.source,
            self.candidate,
        )
        self.assertEqual(receipt["status"], "PASS")
        self.assertEqual(receipt["python_syntax_checked"], 1)
        self.assertEqual(receipt["python_syntax_exclusion_count"], 1)
        self.assertIn(excluded, receipt["python_syntax_excluded"])

        bad = self.manifest(files, [{"path": excluded, "reason": "template syntax"}])
        (self.candidate / regular).write_bytes(b"def broken(:\n")
        held = verify(bad, self.source, self.candidate)
        self.assertEqual(held["status"], "HOLD")
        self.assertEqual(held["python_syntax_error_count"], 1)

    def test_rejects_exclusions_outside_manifest_and_duplicate_exclusions(self) -> None:
        files = [self.write_pair("alpha_core/module.py", b"pass\n")]
        with self.assertRaisesRegex(ValueError, "invalid or not in the manifest"):
            verify(
                self.manifest(
                    files, [{"path": "outside.py", "reason": "not in manifest"}]
                ),
                self.source,
                self.candidate,
            )
        with self.assertRaisesRegex(ValueError, "invalid or not in the manifest"):
            verify(
                self.manifest(
                    files,
                    [
                        {"path": "alpha_core/module.py", "reason": "first"},
                        {"path": "alpha_core/module.py", "reason": "second"},
                    ],
                ),
                self.source,
                self.candidate,
            )


if __name__ == "__main__":
    unittest.main()
