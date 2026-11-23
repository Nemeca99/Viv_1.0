"""Read-only probe for deciding when Viv's composition gate needs another shift."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import sys
from typing import Any

WORKSPACE = Path(__file__).resolve().parents[1]
if str(WORKSPACE) not in sys.path:
    sys.path.insert(0, str(WORKSPACE))

from autonomy.composition_progression import compose_paragraphs
from autonomy.fractal_cognitive_engine import latest_run, load_graduated_words
from autonomy.graph_attention import GraphAttentionScorer


def _records(path: Path, limit: int) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    rows = rows[-limit:]
    return [
        {
            "sentence": row.get("sentence", ""),
            "type": row.get("sentence_type", row.get("tier", "UNKNOWN")),
            "relation_path": row.get("provenance") or [],
        }
        for row in rows
    ]


def run_probe(
    receipt_path: Path,
    *,
    limit: int = 200,
    graph_path: Path | None = None,
) -> dict[str, Any]:
    records = _records(receipt_path, limit)
    graph = GraphAttentionScorer(graph_path or (Path(latest_run()) / "neuron_graph.sqlite3"))
    learned = load_graduated_words()
    report = compose_paragraphs(records, learned, known_neurons=graph.known_surfaces)
    total = max(1, len(records))
    valid = report["valid_sentence_count"]
    paragraphs = report["paragraph_count"]
    novel = report["novel_valid_sentence_count"]
    provenance = sum(bool(item.get("relation_path")) for item in records)
    graph_token_hits = 0
    graph_token_total = 0
    for item in records:
        tokens = set(re.findall(r"[a-z][a-z'-]*", str(item.get("sentence", "")).casefold()))
        graph_token_total += len(tokens)
        graph_token_hits += len(tokens & graph.known_surfaces)

    # These are observations, not automatic policy changes.  They indicate
    # when the current gate is no longer the dominant source of impedance.
    ratios = {
        "provenance_coverage": round(provenance / total, 4),
        "valid_sentence_rate": round(valid / total, 4),
        "novel_valid_rate": round(novel / max(1, valid), 4),
        "paragraph_yield": round(paragraphs / max(1, valid), 4),
        "graph_token_coverage": round(graph_token_hits / max(1, graph_token_total), 4),
    }
    signals = {
        "gate_still_dominant": ratios["graph_token_coverage"] >= 0.95 and ratios["valid_sentence_rate"] < 0.50,
        "sentence_layer_ready_for_paragraph_refinement": ratios["valid_sentence_rate"] >= 0.50 and ratios["paragraph_yield"] < 0.10,
        "paragraph_layer_ready_for_relation_refinement": ratios["paragraph_yield"] >= 0.10 and ratios["novel_valid_rate"] < 0.25,
        "observe_only": True,
    }
    return {
        "schema": "viv_composition_transition_probe_v1",
        "receipt_count": len(records),
        "graph_word_neurons": len(graph.known_surfaces),
        "ratios": ratios,
        "signals": signals,
        "counts": {
            "valid_sentences": valid,
            "invalid_sentences": report["invalid_sentence_count"],
            "novel_valid_sentences": novel,
            "paragraphs": paragraphs,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--receipts",
        type=Path,
        default=Path(r"L:\LocalCoder\workspace\autonomy\learning\daemon_graduation_receipts.jsonl"),
    )
    parser.add_argument("--limit", type=int, default=200)
    args = parser.parse_args()
    print(json.dumps(run_probe(args.receipts, limit=args.limit), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

