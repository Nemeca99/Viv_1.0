"""Posthoc checks for an isolated fixture.echo Hive rebuild."""

from __future__ import annotations

import ast
import hashlib
import importlib.util
import json
from pathlib import Path
import sys


def digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def verify(run: Path, reference: Path) -> dict[str, object]:
    artifact = run / "fixture_echo.py"
    registry = json.loads((run / "registry.json").read_text(encoding="utf-8"))
    if registry.get("schema_version") != "hive_rebuilt_template_registry_v1":
        raise ValueError("registry schema mismatch")
    (row,) = registry["templates"]
    if row != {
        "template_id": "fixture.echo",
        "source": "fixture_echo.py",
        "source_sha256": digest(artifact.read_bytes()),
        "declared_variables": ["message", "suffix"],
    }:
        raise ValueError("registry source binding mismatch")
    source = artifact.read_text(encoding="utf-8")
    original = reference.read_text(encoding="utf-8")
    start = "# TEMPLATE VARIABLES BEGIN\n"
    end = "# TEMPLATE VARIABLES END\n"

    def outside_variables(text: str) -> str:
        left, rest = text.split(start, 1)
        _, right = rest.split(end, 1)
        return left + right

    if outside_variables(source) != outside_variables(original):
        raise ValueError("non-variable source span changed")
    tree = ast.parse(source)
    assignments = [
        node
        for node in tree.body
        if isinstance(node, ast.Assign)
        and len(node.targets) == 1
        and isinstance(node.targets[0], ast.Name)
        and node.targets[0].id == "VARIABLES"
    ]
    if len(assignments) != 1:
        raise ValueError("VARIABLES assignment missing or repeated")
    values = ast.literal_eval(assignments[0].value)
    if not isinstance(values, dict) or set(values) != {"message", "suffix"}:
        raise ValueError("declared variable keys changed")
    if not all(isinstance(value, str) and value for value in values.values()):
        raise ValueError("variable values invalid")
    compile(source, str(artifact), "exec")
    spec = importlib.util.spec_from_file_location("hive_rebuilt_fixture_echo", artifact)
    if spec is None or spec.loader is None:
        raise ValueError("module import spec unavailable")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    result = module.main({"probe": 1}, module.VARIABLES)
    if result != {
        "ok": True,
        "message": values["message"],
        "suffix": values["suffix"],
        "context_keys": ["probe"],
        "variables": values,
    }:
        raise ValueError("explicit function result mismatch")
    return {
        "status": "PASS",
        "source_sha256": digest(artifact.read_bytes()),
        "body_unchanged": True,
        "compiled": True,
        "explicit_execution": result,
    }


if __name__ == "__main__":
    print(json.dumps(verify(Path(sys.argv[1]), Path(sys.argv[2])), sort_keys=True))
