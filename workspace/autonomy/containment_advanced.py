"""Nested containment traces and owned-ISA round-trip identity checks."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
import ast
import hashlib
import json
from typing import Any, Callable, Sequence


@dataclass(frozen=True)
class FrameReceipt:
    frame_id: str
    status: str
    local_trace: tuple[str, ...]
    children: tuple["FrameReceipt", ...] = ()


def fork_join(frame_id: str, children: Sequence[tuple[str, Callable[[], bool]]]) -> FrameReceipt:
    """Run independent children in parallel, then verify the parent join."""
    with ThreadPoolExecutor(max_workers=max(1, len(children))) as pool:
        results = list(pool.map(lambda item: (item[0], item[1]()), children))
    child_receipts = tuple(FrameReceipt(name, "PASS" if passed else "HOLD", (f"CHILD:{name}",)) for name, passed in results)
    status = "PASS" if child_receipts and all(child.status == "PASS" for child in child_receipts) else "HOLD"
    return FrameReceipt(frame_id, status, (f"FRAME:{frame_id}", "JOIN"), child_receipts)


def round_trip_fact(fact: dict[str, str], *, inject_drift: bool = False) -> dict[str, Any]:
    """Compile a tiny owned ISA fact, emit canonical Python, and re-ingest it."""
    original = json.dumps(fact, sort_keys=True, separators=(",", ":"))
    original_hash = hashlib.sha256(original.encode()).hexdigest()
    opcode = {"op": "FACT", "subject": fact["subject"], "relation": fact["relation"], "object": fact["object"]}
    python_source = "FACT = " + repr(opcode)
    if inject_drift:
        python_source = python_source.replace(opcode["object"], opcode["object"] + "_DRIFT")
    tree = ast.parse(python_source)
    namespace: dict[str, Any] = {}
    exec(compile(tree, "<owned-isa>", "exec"), {}, namespace)
    recovered = namespace["FACT"]
    recovered_fact = {key: recovered[key] for key in ("subject", "relation", "object")}
    recovered_text = json.dumps(recovered_fact, sort_keys=True, separators=(",", ":"))
    recovered_hash = hashlib.sha256(recovered_text.encode()).hexdigest()
    return {
        "status": "PASS" if original_hash == recovered_hash else "HOLD",
        "original_sha256": original_hash,
        "recovered_sha256": recovered_hash,
        "python_source": python_source,
        "sql_row": recovered_fact,
    }


__all__ = ["FrameReceipt", "fork_join", "round_trip_fact"]
