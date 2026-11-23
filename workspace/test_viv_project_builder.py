import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from viv_autonomy import Store
from viv_project_builder import build_project_once, extract_files, head, queue_project, scheduler_spec, validate_files


class ProjectIntegrityTests(unittest.TestCase):
    def test_normalizes_source_maps_without_dropping_helper_modules(self):
        files = extract_files({"files": {"scheduler.py": "import helpers"}, "modules": {"helpers.py": "def run(): return 1"}})
        self.assertEqual(set(files), {"scheduler.py", "helpers.py"})
        with self.assertRaises(ValueError):
            extract_files({"files": {"scheduler.py": "x=1"}, "modules": {"scheduler.py": "x=2"}})
    def test_model_paths_cannot_escape_project(self):
        for path in ["../escape.py", "/absolute.py", "C:/escape.py", "a\\escape.py", "a//b.py", "a/../b.py"]:
            with self.subTest(path=path), self.assertRaises(ValueError):
                validate_files({path: "x=1"})

    def test_failed_revision_keeps_prior_head_and_regressions(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = Store(tmp)
            request = scheduler_spec()
            queue_project(store, request)
            answer = json.dumps({"files": {"scheduler.py": "def solve(value): return {'order': []}"}})
            def passed(_image, _code, cases):
                return [{"passed": True} for _ in cases]
            with patch("viv_autonomy.ask_model", return_value=answer), patch("viv_autonomy.evaluate", side_effect=passed):
                build_project_once(store, "test-image")
            original = head(store, request["project"])
            revision = dict(request, requirement=request["requirement"] + " Add a new behavior.")
            queue_project(store, revision)
            observed = []
            def failed(_image, _code, cases):
                observed.extend(cases)
                return [{"passed": False} for _ in cases]
            with patch("viv_autonomy.ask_model", return_value=answer), patch("viv_autonomy.evaluate", side_effect=failed):
                build_project_once(store, "test-image")
            self.assertEqual(head(store, request["project"])["version"], original["version"])
            self.assertEqual(observed, request["cases"])

    def test_manifest_tampering_blocks_invocation(self):
        from viv_project_builder import invoke_project
        with tempfile.TemporaryDirectory() as tmp:
            store = Store(tmp)
            queue_project(store, scheduler_spec())
            with patch("viv_autonomy.ask_model", return_value=json.dumps({"files": {"scheduler.py": "def solve(x): return x"}})), patch("viv_autonomy.evaluate", return_value=[{"passed": True}]):
                build_project_once(store, "test-image")
            version = head(store, "viv_task_scheduler")
            Path(version["manifest"]).write_text("{}", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "differs"):
                invoke_project(store, "viv_task_scheduler", {})


if __name__ == "__main__":
    unittest.main()
