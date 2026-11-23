from __future__ import annotations

import unittest

from run_full_manifest_rebuild import build_manifest, task_contracts, verify_upstream


class FullManifestPlanTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        baseline, verification, transform = verify_upstream()
        cls.manifest = build_manifest(baseline, verification, transform)
        cls.contracts = task_contracts(cls.manifest)

    def test_inventory_covers_every_baseline_file_and_all_nineteen_cores(self) -> None:
        self.assertEqual(self.manifest["file_count"], 3641)
        self.assertEqual(len(self.manifest["cores"]), 19)
        by_id = {row["id"]: row for row in self.contracts}
        core_rows = [by_id[f"core_{core['name']}"] for core in self.manifest["cores"]]
        workspace = by_id["workspace_support"]
        self.assertEqual(
            sum(row["scope_file_count"] for row in core_rows)
            + workspace["scope_file_count"],
            self.manifest["file_count"],
        )
        self.assertEqual(
            sum(row["scope_bytes"] for row in core_rows) + workspace["scope_bytes"],
            self.manifest["catalogued_bytes"],
        )

    def test_verify_task_waits_for_every_core_workspace_and_bridge_task(self) -> None:
        verify_task = next(
            row for row in self.contracts if row["id"] == "verify_candidate"
        )
        required = set(verify_task["required_depends_on"])
        self.assertTrue(
            all(f"core_{core['name']}" in required for core in self.manifest["cores"])
        )
        self.assertTrue({"workspace_support", "numpy_cupy_bridge"} <= required)

    def test_v5_content_is_a_full_hash_pinned_manifest(self) -> None:
        paths = [row["path"] for row in self.manifest["files"]]
        self.assertEqual(len(paths), len(set(paths)))
        self.assertTrue(all(len(row["sha256"]) == 64 for row in self.manifest["files"]))


if __name__ == "__main__":
    unittest.main()
