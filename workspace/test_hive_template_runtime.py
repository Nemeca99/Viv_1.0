"""Tests for the LocalCoder data-only Python template materializer."""

from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

from hive_template_runtime import TemplateError, TemplateRuntime


class TemplateRuntimeTests(unittest.TestCase):
    def test_registered_templates_stamp_expected_parts(self) -> None:
        runtime = TemplateRuntime()
        doc = runtime.render(
            "python.module_docstring", {"docstring": "Hive greeting module"}
        )
        imp = runtime.render("python.typing_final_import", {})
        fn = runtime.render(
            "python.greeting_function",
            {"greeting": "Hello from the Hive!", "function_name": "greet"},
        )
        self.assertEqual(doc.code, '"Hive greeting module"\n')
        self.assertEqual(imp.code, "from typing import Final\n")
        self.assertIn('GREETING: Final[str] = "Hello from the Hive!"', fn.code)
        self.assertIn("def greet() -> str:", fn.code)

    def test_slots_are_data_and_python_strings_are_escaped(self) -> None:
        runtime = TemplateRuntime()
        source = runtime.render(
            "python.module_docstring",
            {"docstring": "safe'\n__import__('os').remove('x')"},
        ).code
        compile(source, "safe_template.py", "exec", dont_inherit=True)
        self.assertEqual(source.count("\n"), 1)

    def test_rendered_literals_and_top_level_spacing_match_formatter(self) -> None:
        runtime = TemplateRuntime()
        doc = runtime.render("python.module_docstring", {"docstring": "Viv's module"})
        imp = runtime.render("python.typing_final_import", {})
        fn = runtime.render(
            "python.greeting_function",
            {"greeting": "Hello from the Hive!", "function_name": "greet"},
        )
        source = doc.code.rstrip() + "\n\n" + imp.code.rstrip() + "\n\n" + fn.code
        self.assertEqual(
            source,
            '"Viv\'s module"\n\nfrom typing import Final\n\n'
            'GREETING: Final[str] = "Hello from the Hive!"\n\n\n'
            "def greet() -> str:\n    return GREETING\n",
        )
        compile(source, "formatted_template.py", "exec", dont_inherit=True)

    def test_rejects_unknown_slots_and_unlisted_templates(self) -> None:
        runtime = TemplateRuntime()
        with self.assertRaises(TemplateError):
            runtime.render(
                "python.module_docstring", {"docstring": "x", "source": "print(1)"}
            )
        with self.assertRaises(TemplateError):
            runtime.render("python.arbitrary_source", {})

    def test_rejects_invalid_function_identifiers(self) -> None:
        runtime = TemplateRuntime()
        for name in ("bad-name", "class", "x\nimport os"):
            with self.subTest(name=name), self.assertRaises(TemplateError):
                runtime.render(
                    "python.greeting_function",
                    {"greeting": "Hi", "function_name": name},
                )

    def test_template_source_hash_drift_holds(self) -> None:
        source_root = Path(__file__).parent / "code_templates"
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp) / "code_templates"
            shutil.copytree(source_root, target)
            template = target / "source" / "python_greeting_function.py.tpl"
            template.write_text(
                template.read_text(encoding="utf-8") + "# drift\n", encoding="utf-8"
            )
            with self.assertRaisesRegex(TemplateError, "template_hash_mismatch"):
                TemplateRuntime(target / "registry.json")


if __name__ == "__main__":
    unittest.main()
