"""Train a fact-recall candidate with low-rate replay from verified code."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import importlib.util
import json
from pathlib import Path
import random
import sys
import urllib.request

HERE = Path(__file__).resolve().parent
WORKSPACE = HERE.parent
if str(WORKSPACE) not in sys.path:
    sys.path.insert(0, str(WORKSPACE))
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import viv_sleep_trainer as trainer

API = "http://127.0.0.1:1234"
LIVE = Path(r"E:\Viv_Sandbox\playground\adapters\epoch_10001")
PARENT = Path(r"F:\LocalCoder_Archive\Viv_model_candidates\epoch_10002")
ROOT = Path(r"F:\LocalCoder_Archive\Viv_model_candidates")
EPOCH = 10004
SEED = 20261112
FACT = "brindle-qat-731"


def sha_obj(value: object) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     separators=(",", ":")).encode("utf-8")).hexdigest()


def request(path: str, payload: dict | None = None) -> dict:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(API + path, data=data,
                                 headers={"Content-Type": "application/json"} if data else {})
    with urllib.request.urlopen(req, timeout=240) as response:
        return json.load(response)


def _code_replay() -> tuple[list[dict], list[str]]:
    module_path = HERE / "run_deepseek_candidate_e2e.py"
    spec = importlib.util.spec_from_file_location("candidate_code_replay", module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    rows, lineage = module.accepted_training_samples()
    return rows, [row["task"] for row in lineage]


def _fact_rows() -> list[dict]:
    variants = [
        ("Remember this for later: the fictional Vesper device's serial label is brindle-qat-731.",
         "The fictional Vesper device's serial label is brindle-qat-731."),
        ("What is the serial label for the fictional Vesper device?",
         "The serial label is brindle-qat-731."),
        ("Vesper's unique identifier is brindle-qat-731. Keep that association.",
         "Understood. Vesper's unique identifier is brindle-qat-731."),
    ]
    return [{"category": "new_fact_recall", "prompt": f"USER: {question}\n\nASSISTANT:\n",
             "completion": answer + "\n"}
            for question, answer in variants for _ in range(5)]


def main() -> int:
    destination = ROOT / f"epoch_{EPOCH:05d}"
    if destination.exists():
        raise FileExistsError(destination)
    for path in (LIVE / "adapter_model.safetensors", PARENT / "adapter_model.safetensors"):
        if not path.is_file():
            raise FileNotFoundError(path)
    live_status = request("/v1/status")
    if live_status.get("status") != "ACTIVE" or live_status.get("active_adapter") != LIVE.name:
        raise RuntimeError(f"Unexpected live adapter: {live_status}")

    replay, replay_tasks = _code_replay()
    facts = _fact_rows()
    samples = replay + facts
    print(json.dumps({"phase": "preflight", "parent": str(PARENT),
                      "parent_sha256": hashlib.file_digest((PARENT / "adapter_model.safetensors").open("rb"), "sha256").hexdigest(),
                      "code_replay_count": len(replay), "code_replay_tasks": replay_tasks,
                      "fact_examples": len(facts), "fact_probe": FACT,
                      "training_sha256": sha_obj(samples), "live": live_status}, indent=2), flush=True)

    if request("/v1/quiesce", {}).get("status") != "QUIESCED":
        raise RuntimeError("Tutor did not quiesce")
    import torch
    from transformers import set_seed
    random.seed(SEED)
    torch.manual_seed(SEED)
    torch.cuda.manual_seed_all(SEED)
    set_seed(SEED)
    trainer.ADAPTERS_ROOT = ROOT
    trainer.RECEIPTS_FILE = ROOT / "training_receipts.jsonl"
    outcome = trainer.run_sleep_training(
        epoch=EPOCH, steps=45, lr=2e-5, parent_adapter=PARENT,
        training_samples=samples,
    )
    if not outcome.get("ok"):
        raise RuntimeError(outcome)
    candidate_path = destination / "adapter_model.safetensors"
    receipt = {
        "schema": "viv_deepseek_fact_candidate_training_v1",
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "seed": SEED, "live_adapter_before": live_status,
        "parent": str(PARENT), "parent_sha256": hashlib.file_digest((PARENT / "adapter_model.safetensors").open("rb"), "sha256").hexdigest(),
        "candidate": str(destination), "candidate_sha256": hashlib.file_digest(candidate_path.open("rb"), "sha256").hexdigest(),
        "training_sha256": sha_obj(samples), "code_replay_tasks": replay_tasks,
        "new_fact": FACT, "training": outcome, "promoted": False,
    }
    receipt["receipt_sha256"] = sha_obj(receipt)
    receipt_path = HERE / "learning" / "deepseek_candidate_runs" / "fact_candidate_10004.json"
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    receipt_path.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"phase": "complete", "candidate": str(destination),
                      "steps": outcome["receipt"]["steps_completed"],
                      "loss": outcome["receipt"]["final_loss"],
                      "receipt": str(receipt_path), "promoted": False}, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
