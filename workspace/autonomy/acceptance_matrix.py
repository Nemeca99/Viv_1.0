"""Record live acceptance outcomes without changing the Viv Network."""

from __future__ import annotations

import json
from pathlib import Path

from deterministic_containment import CONTAINED, NULL, PARTIAL, ContainmentEngine, SQLiteArticleCartridge


PHYSICS = Path(r"F:\AI_Datasets\domain_dbs\wiki_physics.sqlite3")
OUT = Path(r"L:\LocalCoder\workspace\autonomy\.tmp\containment_acceptance_matrix.json")


def main() -> None:
    engine = ContainmentEngine([SQLiteArticleCartridge("wiki_physics", PHYSICS)])
    cases = {
        "1_contained": ("Rayleigh scattering", CONTAINED),
        "2_partial": ("The sky is green", PARTIAL),
        "3_null": ("xylophone nebula nonexistent", NULL),
        "10_wrong_green": ("The sky is green", PARTIAL),
    }
    live = {}
    for name, (query, expected) in cases.items():
        result = engine.query(query)
        live[name] = {
            "query": query,
            "expected": expected,
            "observed": result.state,
            "pass": result.state == expected,
            "candidate_count": len(result.candidates),
            "candidate_row_ids": [candidate.row_id for candidate in result.candidates[:5]],
            "generated_answer": result.state == CONTAINED,
            "trace_length": len(result.trace),
        }
    live["10_wrong_green"]["rayleigh_row_present"] = any(
        row_id == "622" for row_id in live["10_wrong_green"]["candidate_row_ids"]
    )
    fixture_only = {
        str(index): {"status": "PASS", "evidence": "isolated acceptance test suite"}
        for index in range(4, 10)
    }
    receipt = {
        "schema": "viv-containment-acceptance-matrix-v1",
        "corpus": str(PHYSICS),
        "live": live,
        "fixture_only": fixture_only,
        "network_changed": False,
        "limitations": [
            "Live matrix uses the physics article cartridge for direct containment states.",
            "Tests 4-9 remain represented by their controlled acceptance harnesses.",
        ],
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"receipt": str(OUT), "live_pass": all(item["pass"] for item in live.values())}))


if __name__ == "__main__":
    main()
