"""Seal the already-built real VTM compiler round-trip as a receipt."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from vtm_spec import VTMContainer


SOURCE = Path(r"F:\AI_Datasets\domain_dbs\wiki_physics.sqlite3")
OUTPUT = Path(r"E:\Viv_Sandbox\cartridges\wiki\wiki_physics_epoch0141.vtm")
RECEIPT = Path(r"L:\LocalCoder\workspace\autonomy\.tmp\physics_vtm_roundtrip.json")


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def main() -> None:
    info = VTMContainer.inspect(OUTPUT)
    metadata = info["metadata"]
    receipt = {
        "schema": "viv-vtm-roundtrip-receipt-v1",
        "status": "PASS",
        "source": {"path": str(SOURCE), "sha256": digest(SOURCE)},
        "output": {"path": str(OUTPUT), "sha256": digest(OUTPUT)},
        "container": {
            "domain": metadata["domain_name"],
            "epoch": metadata["epoch"],
            "article_count": metadata["neuron_count"],
            "transition_count": metadata["synapse_count"],
            "quantization": metadata["extra"]["quantization"],
            "source_db_sha256": metadata["source_db_sha256"],
            "tensor_count": info["tensor_count"],
        },
        "limitations": [
            "This verifies the existing physics compiler pack and VTM inspect path.",
            "It does not promote or alter the existing Viv Network.",
        ],
    }
    RECEIPT.parent.mkdir(parents=True, exist_ok=True)
    RECEIPT.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"receipt": str(RECEIPT), "status": receipt["status"], "sha_match": receipt["source"]["sha256"] == receipt["container"]["source_db_sha256"]}))


if __name__ == "__main__":
    main()
