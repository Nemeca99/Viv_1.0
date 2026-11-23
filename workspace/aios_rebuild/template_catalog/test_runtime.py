from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from runtime import AiosTemplateCatalog, CatalogError

ROOT = Path(r"L:\LocalCoder\workspace\aios_rebuild")
RUN = ROOT / "rebuild_runs" / "full_horizontal_candidate_v5"
CATALOG = RUN / "template_catalog_v2"
CANDIDATE = RUN / "candidate"


class AiosTemplateCatalogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.catalog = AiosTemplateCatalog(CATALOG, CANDIDATE)
        cls.registry = json.loads(
            (CATALOG / "registry.json").read_text(encoding="utf-8")
        )
        cls.entries: dict[str, dict] = {}
        with (CATALOG / "functions.jsonl").open("rb") as stream:
            for template_id, offset in cls.catalog.index.items():
                stream.seek(offset)
                row = json.loads(stream.readline())
                if row["core"] == "dream_core":
                    cls.entries[template_id] = row

    def test_reads_full_catalog_entry_and_checks_exact_source_span(self) -> None:
        template_id = next(
            key
            for key, row in self.entries.items()
            if row["qualified_name"] == "DreamCore._is_fresh"
        )
        entry = self.catalog.get(template_id)
        self.assertEqual(entry.core, "dream_core")
        self.assertEqual(entry.qualified_name, "DreamCore._is_fresh")
        self.assertIn("def _is_fresh", entry.snippet_utf8)

    def test_stamps_selected_top_level_templates_byte_exactly(self) -> None:
        template_id = next(
            key
            for key, row in self.entries.items()
            if row["qualified_name"] == "main" and row["kind"] == "function"
        )
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            out = root / "dream_core_rebuilt.py"
            receipt = self.catalog.stamp(
                [template_id], out, expected_core="dream_core", output_root=root
            )
            source = out.read_text(encoding="utf-8")
            self.assertEqual(
                source, self.entries[template_id]["snippet_utf8"].rstrip() + "\n"
            )
            compile(source, str(out), "exec", dont_inherit=True)
            self.assertEqual(receipt.template_count, 1)
            self.assertTrue(receipt.syntax_valid)
            self.assertEqual(
                receipt.output_sha256,
                __import__("hashlib").sha256(out.read_bytes()).hexdigest(),
            )

    def test_rejects_other_core_nested_and_duplicate_selections(self) -> None:
        top_level = next(
            key
            for key, row in self.entries.items()
            if row["qualified_name"] == "main" and row["kind"] == "function"
        )
        nested = next(
            key
            for key, row in self.entries.items()
            if "." in row["qualified_name"] and row["kind"] == "function"
        )
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            with self.assertRaisesRegex(CatalogError, "crosses its assigned core"):
                self.catalog.stamp(
                    [top_level],
                    root / "bad.py",
                    expected_core="luna_core",
                    output_root=root,
                )
            with self.assertRaises(CatalogError):
                self.catalog.stamp(
                    [top_level, top_level],
                    root / "duplicate.py",
                    expected_core="dream_core",
                    output_root=root,
                )
            with self.assertRaises(CatalogError):
                self.catalog.stamp(
                    [nested],
                    root / "nested.py",
                    expected_core="dream_core",
                    output_root=root,
                )

    def test_rejects_existing_and_escaping_outputs(self) -> None:
        template_id = next(
            key
            for key, row in self.entries.items()
            if row["qualified_name"] == "main" and row["kind"] == "function"
        )
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            out = root / "existing.py"
            out.write_text("preserve", encoding="utf-8")
            with self.assertRaisesRegex(CatalogError, "new file"):
                self.catalog.stamp(
                    [template_id], out, expected_core="dream_core", output_root=root
                )
            with self.assertRaisesRegex(CatalogError, "new file"):
                self.catalog.stamp(
                    [template_id],
                    root.parent / "escape.py",
                    expected_core="dream_core",
                    output_root=root,
                )
            self.assertEqual(out.read_text(encoding="utf-8"), "preserve")

    def test_catalog_covers_every_manifest_core_and_template(self) -> None:
        self.assertEqual(len(self.catalog.index), self.registry["template_count"])
        self.assertEqual(len(self.catalog.core_names), 19)
        self.assertEqual({row["core"] for row in self.entries.values()}, {"dream_core"})

    def test_mind_menu_has_bounded_hash_pinned_candidates_for_every_core(self) -> None:
        cards = self.catalog.candidate_cards(per_core=8)
        self.assertEqual(set(cards), set(self.catalog.core_names))
        self.assertTrue(all(1 <= len(rows) <= 8 for rows in cards.values()))
        self.assertTrue(
            all(
                "." not in row["qualified_name"]
                for rows in cards.values()
                for row in rows
            )
        )
        self.assertTrue(
            all(
                len({row["qualified_name"] for row in rows}) == len(rows)
                for rows in cards.values()
            )
        )
        self.assertTrue(
            all(
                row["template_id"] in self.catalog.index
                for rows in cards.values()
                for row in rows
            )
        )


if __name__ == "__main__":
    unittest.main()
