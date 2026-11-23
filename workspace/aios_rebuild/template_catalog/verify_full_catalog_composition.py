"""Independently check all stamped catalog compositions without executing them."""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
from pathlib import Path
from typing import Any

from runtime import AiosTemplateCatalog


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def verify(
    output_root: Path, menu_path: Path, catalog_dir: Path, source_candidate: Path
) -> dict[str, Any]:
    menu = json.loads(menu_path.read_text(encoding="utf-8"))
    runtime = AiosTemplateCatalog(catalog_dir, source_candidate)
    errors: list[str] = []
    checked: list[dict[str, Any]] = []
    cards = menu.get("cards", {})
    if menu.get("schema") != "viv_full_aios_template_menu_v1":
        errors.append("menu_schema")
    if menu.get("catalog_registry_sha256") != sha(
        (catalog_dir / "registry.json").read_bytes()
    ):
        errors.append("menu_registry_hash")
    expected_files: set[str] = set()
    for core in runtime.core_order:
        code_path = output_root / core / f"{core}_selected.py"
        metadata_path = code_path.with_suffix(".templates.json")
        expected_files.update(
            {
                code_path.relative_to(output_root).as_posix(),
                metadata_path.relative_to(output_root).as_posix(),
            }
        )
        try:
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            code = code_path.read_bytes()
            ids = metadata["template_ids"]
            if metadata.get("core") != core or not (1 <= len(ids) <= 2):
                raise ValueError("metadata core or template count invalid")
            if sha(code) != metadata.get("artifact_sha256"):
                raise ValueError("artifact digest mismatch")
            allowed = {row["template_id"] for row in cards.get(core, [])}
            if len(set(ids)) != len(ids) or any(
                template_id not in allowed for template_id in ids
            ):
                raise ValueError("selected ID absent from Mind candidate menu")
            snippets = [
                runtime.get(template_id).snippet_utf8.rstrip("\r\n")
                for template_id in ids
            ]
            expected = ("\n\n\n".join(snippets) + "\n").encode("utf-8")
            if expected != code:
                raise ValueError("stamped source does not exactly match catalog spans")
            tree = ast.parse(code.decode("utf-8"), filename=str(code_path))
            if len(tree.body) != len(ids):
                raise ValueError("stamped declaration count mismatch")
            checked.append(
                {"core": core, "template_count": len(ids), "artifact_sha256": sha(code)}
            )
        except (
            OSError,
            UnicodeError,
            json.JSONDecodeError,
            KeyError,
            TypeError,
            ValueError,
            SyntaxError,
        ) as error:
            errors.append(f"{core}:{error}")
    actual_files = {
        path.relative_to(output_root).as_posix()
        for path in output_root.rglob("*")
        if path.is_file()
    }
    if actual_files != expected_files:
        errors.append("output_file_set_mismatch")
    return {
        "schema": "viv_full_aios_catalog_composition_verification_v1",
        "status": "PASS"
        if not errors and len(checked) == len(runtime.core_order)
        else "HOLD",
        "core_count": len(checked),
        "expected_core_count": len(runtime.core_order),
        "template_count": sum(row["template_count"] for row in checked),
        "python_files_parsed": len(checked),
        "candidate_executed": False,
        "source_imported_or_executed": False,
        "errors": errors,
        "cores": checked,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output_root", type=Path)
    parser.add_argument("menu", type=Path)
    parser.add_argument("catalog", type=Path)
    parser.add_argument("source_candidate", type=Path)
    args = parser.parse_args()
    result = verify(args.output_root, args.menu, args.catalog, args.source_candidate)
    print(json.dumps(result, ensure_ascii=False))
    raise SystemExit(0 if result["status"] == "PASS" else 1)


if __name__ == "__main__":
    main()
