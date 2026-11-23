"""Hash-checked access and deterministic stamping for the full AIOS function catalog.

The Mind may select catalog IDs. This runtime copies their exact source spans;
it never accepts source text or executes imported AIOS modules.
"""

from __future__ import annotations

import ast
import hashlib
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable


class CatalogError(ValueError):
    """The catalog, source tree, selection, or output violated its contract."""


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


@dataclass(frozen=True)
class CatalogTemplate:
    template_id: str
    core: str
    source_path: str
    source_file_sha256: str
    qualified_name: str
    kind: str
    start_line: int
    end_line: int
    snippet_sha256: str
    snippet_utf8: str


@dataclass(frozen=True)
class StampReceipt:
    output_path: Path
    output_sha256: str
    template_ids: tuple[str, ...]
    template_count: int
    source_files: tuple[str, ...]
    syntax_valid: bool


class AiosTemplateCatalog:
    """Read catalog entries and stamp exact spans into a new candidate artifact."""

    def __init__(self, catalog_dir: Path, candidate_root: Path) -> None:
        self.catalog_dir = catalog_dir.resolve(strict=True)
        self.candidate_root = candidate_root.resolve(strict=True)
        try:
            self.registry = json.loads(
                (self.catalog_dir / "registry.json").read_text(encoding="utf-8")
            )
            self.index: dict[str, int] = json.loads(
                (self.catalog_dir / "lookup.json").read_text(encoding="utf-8")
            )
        except (OSError, UnicodeError, json.JSONDecodeError) as error:
            raise CatalogError(f"catalog metadata invalid: {error}") from error
        if self.registry.get("schema") != "aios_19_core_function_template_registry_v1":
            raise CatalogError("catalog schema invalid")
        if (
            self.registry.get("status") != "PASS"
            or self.registry.get("source_imported_or_executed") is not False
        ):
            raise CatalogError("catalog is not a verified parse-only registry")
        data_path = self.catalog_dir / "functions.jsonl"
        lookup_path = self.catalog_dir / "lookup.json"
        if _sha(data_path.read_bytes()) != self.registry.get("functions_jsonl_sha256"):
            raise CatalogError("catalog data digest mismatch")
        if _sha(lookup_path.read_bytes()) != self.registry.get("lookup_sha256"):
            raise CatalogError("catalog lookup digest mismatch")
        if len(self.index) != self.registry.get("template_count"):
            raise CatalogError("catalog index count mismatch")
        self.data_path = data_path
        self.core_order = tuple(self.registry.get("core_names", []))
        self.core_names = frozenset(self.core_order)
        if (
            len(self.core_names) != len(self.registry.get("core_names", []))
            or not self.core_names
        ):
            raise CatalogError("catalog core manifest invalid")

    def _source_path(self, relative: str) -> Path:
        rel = Path(relative)
        if (
            rel.is_absolute()
            or rel.drive
            or not rel.parts
            or any(p in {".", ".."} for p in rel.parts)
        ):
            raise CatalogError("template source path is not relative")
        if rel.parts[0] not in self.core_names:
            raise CatalogError("template source is outside the 19-core manifest")
        lexical = self.candidate_root.joinpath(rel)
        path = lexical.resolve(strict=True)
        if (
            self.candidate_root not in path.parents
            or path.is_symlink()
            or not path.is_file()
        ):
            raise CatalogError("template source escapes candidate root")
        is_junction = getattr(os.path, "isjunction", None)
        cursor = lexical
        while cursor != self.candidate_root and cursor != cursor.parent:
            if cursor.exists() and (
                cursor.is_symlink() or (is_junction and is_junction(cursor))
            ):
                raise CatalogError("template source crosses a reparse point")
            cursor = cursor.parent
        return path

    def get(self, template_id: str) -> CatalogTemplate:
        if not isinstance(template_id, str) or template_id not in self.index:
            raise CatalogError("template ID is not in the verified catalog")
        offset = self.index[template_id]
        if not isinstance(offset, int) or offset < 0:
            raise CatalogError("catalog byte offset invalid")
        try:
            with self.data_path.open("rb") as stream:
                stream.seek(offset)
                row: dict[str, Any] = json.loads(stream.readline())
            template = CatalogTemplate(
                template_id=row["template_id"],
                core=row["core"],
                source_path=row["source_path"],
                source_file_sha256=row["source_file_sha256"],
                qualified_name=row["qualified_name"],
                kind=row["kind"],
                start_line=row["start_line"],
                end_line=row["end_line"],
                snippet_sha256=row["snippet_sha256"],
                snippet_utf8=row["snippet_utf8"],
            )
        except (
            OSError,
            UnicodeError,
            json.JSONDecodeError,
            KeyError,
            TypeError,
        ) as error:
            raise CatalogError(f"catalog row invalid: {error}") from error
        if template.template_id != template_id or template.core not in self.core_names:
            raise CatalogError("catalog row identity invalid")
        if not (1 <= template.start_line <= template.end_line):
            raise CatalogError("catalog line range invalid")
        snippet = template.snippet_utf8.encode("utf-8")
        if _sha(snippet) != template.snippet_sha256:
            raise CatalogError("template snippet digest mismatch")
        source = self._source_path(template.source_path)
        raw = source.read_bytes()
        if _sha(raw) != template.source_file_sha256:
            raise CatalogError("candidate source changed since catalog build")
        try:
            lines = raw.decode("utf-8").splitlines(keepends=True)
        except UnicodeDecodeError as error:
            raise CatalogError("candidate source is not UTF-8") from error
        if (
            "".join(lines[template.start_line - 1 : template.end_line])
            != template.snippet_utf8
        ):
            raise CatalogError("template span no longer matches its source")
        return template

    def candidate_cards(self, *, per_core: int = 10) -> dict[str, list[dict[str, Any]]]:
        """Return a compact, deterministic menu of top-level definitions for Mind planning."""
        if not 1 <= per_core <= 32:
            raise CatalogError("candidate-card bound must be between 1 and 32")
        cards: dict[str, list[dict[str, Any]]] = {core: [] for core in self.core_order}
        with self.data_path.open("rb") as stream:
            for line in stream:
                try:
                    row = json.loads(line)
                except (UnicodeError, json.JSONDecodeError) as error:
                    raise CatalogError(
                        f"catalog row cannot be read: {error}"
                    ) from error
                if row.get("kind") not in {"class", "function"} or "." in row.get(
                    "qualified_name", ""
                ):
                    continue
                core = row.get("core")
                if core not in cards:
                    raise CatalogError("catalog row core is outside the registry")
                snippet = row.get("snippet_utf8")
                if not isinstance(snippet, str) or _sha(
                    snippet.encode("utf-8")
                ) != row.get("snippet_sha256"):
                    raise CatalogError("candidate-card snippet digest mismatch")
                try:
                    node = ast.parse(snippet).body[0]
                except (SyntaxError, IndexError) as error:
                    raise CatalogError(
                        "top-level candidate is not parseable"
                    ) from error
                doc = ast.get_docstring(node, clean=True) or ""
                doc = re.sub(r"\s+", " ", doc).strip()[:240]
                parts = Path(row["source_path"]).parts
                shallow_path = max(0, 3 - len(parts))
                calls = row.get("direct_calls", [])
                score = (
                    (5 if row["kind"] == "class" else 0)
                    + shallow_path
                    + min(len(calls), 12) / 12
                    + min(max(row["end_line"] - row["start_line"], 0), 240) / 240
                )
                cards[core].append(
                    {
                        "template_id": row["template_id"],
                        "qualified_name": row["qualified_name"],
                        "kind": row["kind"],
                        "source_path": row["source_path"],
                        "parameters": row.get("parameters", []),
                        "direct_calls": calls[:12],
                        "docstring": doc,
                        "source_lines": row["end_line"] - row["start_line"] + 1,
                        "selection_score": round(score, 4),
                    }
                )
        for core, items in cards.items():
            items.sort(
                key=lambda item: (
                    -item["selection_score"],
                    item["source_path"],
                    item["qualified_name"],
                )
            )
            unique: list[dict[str, Any]] = []
            seen_names: set[str] = set()
            for item in items:
                if item["qualified_name"] in seen_names:
                    continue
                seen_names.add(item["qualified_name"])
                unique.append(item)
            cards[core] = unique[:per_core]
            if not cards[core]:
                raise CatalogError(
                    f"core has no selectable top-level templates: {core}"
                )
        return cards

    def stamp(
        self,
        template_ids: Iterable[str],
        output_path: Path,
        *,
        expected_core: str,
        output_root: Path,
        max_templates: int = 128,
    ) -> StampReceipt:
        ids = tuple(template_ids)
        if expected_core not in self.core_names:
            raise CatalogError("requested core is not in the source manifest")
        if not ids or len(ids) > max_templates or len(set(ids)) != len(ids):
            raise CatalogError(
                "selection must contain unique IDs within the configured bound"
            )
        output_root = output_root.resolve(strict=True)
        target = output_path.resolve(strict=False)
        if output_root not in target.parents or target.exists():
            raise CatalogError(
                "output must be a new file below the isolated run output root"
            )
        entries = [self.get(template_id) for template_id in ids]
        if any(entry.core != expected_core for entry in entries):
            raise CatalogError("selection crosses its assigned core")
        if any("." in entry.qualified_name for entry in entries):
            raise CatalogError("nested methods require their containing class template")
        occupied: dict[str, list[tuple[int, int]]] = {}
        names: set[str] = set()
        for entry in entries:
            spans = occupied.setdefault(entry.source_path, [])
            current = (entry.start_line, entry.end_line)
            if any(current[0] <= end and start <= current[1] for start, end in spans):
                raise CatalogError(
                    "selection contains nested or overlapping source spans"
                )
            spans.append(current)
            top_name = entry.qualified_name.split(".", 1)[0]
            if top_name in names:
                raise CatalogError(
                    "selection repeats a top-level class or function name"
                )
            names.add(top_name)
        snippets = [entry.snippet_utf8.rstrip("\r\n") for entry in entries]
        source = "\n\n\n".join(snippets) + "\n"
        try:
            ast.parse(source, filename=str(target))
        except SyntaxError as error:
            raise CatalogError(
                f"composed template artifact does not parse: {error}"
            ) from error
        target.parent.mkdir(parents=True, exist_ok=True)
        # Exclusive creation avoids overwriting another task's artifact.
        with target.open("xb") as stream:
            stream.write(source.encode("utf-8"))
            stream.flush()
            os.fsync(stream.fileno())
        raw = target.read_bytes()
        return StampReceipt(
            output_path=target,
            output_sha256=_sha(raw),
            template_ids=ids,
            template_count=len(entries),
            source_files=tuple(sorted({entry.source_path for entry in entries})),
            syntax_valid=True,
        )
