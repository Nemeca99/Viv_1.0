"""Candidate-only teaching, fresh-process retrieval, and grounded response proof."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
import urllib.request

ROOT = Path(r"L:\LocalCoder\workspace")
HERE = ROOT / "autonomy"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from aios_rebuild.privacy_core.privacy_core import PrivacyCore
from autonomy.deterministic_containment import ContainmentEngine, JsonFactCartridge, NULL
from autonomy.grounded_rnn_answer_bridge import GroundedRNNAnswerBridge, NULL_UNLEARNED_ENTITY

API = "http://127.0.0.1:1234"
LIVE_ADAPTER = Path(r"E:\Viv_Sandbox\playground\adapters\epoch_10001")
MODEL_CANDIDATE = Path(r"F:\LocalCoder_Archive\Viv_model_candidates\epoch_10002")
MEMORY_SOURCE = ROOT / "aios_rebuild" / "memory" / "persistent_memory.json"
TOPOLOGY = HERE / "viv_code_topology.sqlite3"
RNN_CANDIDATE = HERE / ".tmp" / "rnn_candidate.json"
MEMORY_CANDIDATE = ROOT / "aios_rebuild" / "memory" / "candidate_epoch_10005.json"
JOURNAL = ROOT / "aios_rebuild" / "memory" / "candidate_epoch_10005_journal.jsonl"
OUT = HERE / "learning" / "deepseek_candidate_runs" / "candidate_memory_proof_10005.json"
QUESTION = "What serial label belongs to the fictional Vesper device?"
UNKNOWN = "What activation phrase belongs to Orion?"
FACT = {
    "subject": "fictional Vesper device",
    "relation": "has_serial_label",
    "object": "KESTREL-4821",
    "raw": "The fictional Vesper device's serial label is KESTREL-4821.",
}


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def request(path: str, payload: dict | None = None) -> dict:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(API + path, data=data,
                                 headers={"Content-Type": "application/json"} if data else {})
    with urllib.request.urlopen(req, timeout=180) as response:
        return json.load(response)


def activate(adapter: Path) -> dict:
    request("/v1/reload_adapter", {"adapter_dir": str(adapter)})
    status = request("/v1/status")
    if status.get("status") != "ACTIVE" or status.get("active_adapter") != adapter.name:
        raise RuntimeError(f"adapter load failed: {status}")
    return status


def main() -> int:
    for path in (MEMORY_SOURCE, TOPOLOGY, RNN_CANDIDATE, MODEL_CANDIDATE / "adapter_model.safetensors"):
        if not path.is_file():
            raise FileNotFoundError(path)
    if MEMORY_CANDIDATE.exists() or JOURNAL.exists() or OUT.exists():
        raise FileExistsError("candidate memory proof artifacts already exist; refusing overwrite")
    initial = request("/v1/status")
    if initial.get("status") != "ACTIVE" or initial.get("active_adapter") != LIVE_ADAPTER.name:
        raise RuntimeError(f"unexpected initial tutor: {initial}")

    privacy = PrivacyCore()
    topology_hash_before = sha(TOPOLOGY)
    source_memory_hash = sha(MEMORY_SOURCE)
    candidate_memory = {"facts": [], "candidate_only": True, "created_utc": datetime.now(timezone.utc).isoformat()}
    memory_write = privacy.write_text(MEMORY_CANDIDATE,
                                      json.dumps(candidate_memory, ensure_ascii=False, indent=2) + "\n")

    cartridge = JsonFactCartridge("candidate-memory", MEMORY_CANDIDATE)
    engine = ContainmentEngine([cartridge])
    before = engine.query(QUESTION)
    if before.state != NULL:
        raise AssertionError(f"empty candidate memory should be NULL, got {before.state}")
    journal_auth = privacy.authorize_file_write(JOURNAL)
    if journal_auth.get("allowed") is not True:
        raise PermissionError(f"PrivacyCore denied candidate learning journal: {journal_auth}")
    admission = engine.learn_after(before, cartridge_id="candidate-memory", fact=FACT,
                                   journal_path=JOURNAL)
    if admission.get("decision") != "COMMIT":
        raise AssertionError(f"candidate fact was not admitted: {admission}")
    candidate_memory["facts"] = cartridge.rows
    memory_write_after = privacy.write_text(
        MEMORY_CANDIDATE, json.dumps(candidate_memory, ensure_ascii=False, indent=2) + "\n")

    # Fresh instances ensure retrieval is from the durable candidate file.
    fresh_cartridge = JsonFactCartridge("candidate-memory", MEMORY_CANDIDATE)
    fresh_engine = ContainmentEngine([fresh_cartridge])
    retrieved = fresh_engine.query(QUESTION)
    unknown = fresh_engine.query(UNKNOWN)
    topology_hash = sha(TOPOLOGY)
    bridge = GroundedRNNAnswerBridge(MEMORY_CANDIDATE, RNN_CANDIDATE,
                                     topology_sha256=topology_hash)
    bridge_known = bridge.answer(QUESTION)
    bridge_unknown = bridge.answer(UNKNOWN)

    generated = ""
    generated_has_fact = False
    restore = None
    try:
        activate(MODEL_CANDIDATE)
        response = request("/v1/chat/completions", {
            "model": "deepseek-coder-6.7b-base",
            "messages": [
                {"role": "system", "content": (
                    "Answer the user's question using only the verified retrieved fact. "
                    "State the label exactly as written. If it does not answer the question, say you do not know."
                )},
                {"role": "user", "content": (
                    QUESTION + "\n\nVerified memory evidence: " + bridge_known["answer"] +
                    "\nEvidence ID: " + bridge_known["evidence"][0]
                )},
            ],
            "temperature": 0.0, "max_tokens": 72,
            "stop": ["\nUSER:", "\nSYSTEM:"],
        })
        generated = response["choices"][0]["message"]["content"].strip()
        generated_has_fact = "KESTREL-4821" in generated
    finally:
        restore = activate(LIVE_ADAPTER)

    passed = bool(
        memory_write.get("allowed") and memory_write_after.get("allowed")
        and admission.get("decision") == "COMMIT"
        and retrieved.state == "CONTAINED" and FACT["raw"] in retrieved.answer
        and unknown.state == NULL
        and bridge_known.get("status") == "GROUNDED"
        and FACT["raw"] == bridge_known.get("answer")
        and bridge_unknown.get("answer") == NULL_UNLEARNED_ENTITY
        and topology_hash_before == sha(TOPOLOGY)
        and source_memory_hash == sha(MEMORY_SOURCE)
        and restore.get("active_adapter") == LIVE_ADAPTER.name
    )
    receipt = {
        "schema": "viv_candidate_memory_learning_proof_v1",
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "source_memory_path": str(MEMORY_SOURCE), "source_memory_sha256_before_after": source_memory_hash,
        "topology_path": str(TOPOLOGY), "topology_sha256_before": topology_hash_before,
        "topology_sha256_after": sha(TOPOLOGY),
        "candidate_memory_path": str(MEMORY_CANDIDATE),
        "candidate_memory_sha256": sha(MEMORY_CANDIDATE),
        "privacy_authorization": {"initial_write": memory_write, "journal": journal_auth,
                                  "persisted_commit": memory_write_after},
        "training_input": FACT, "initial_query_state": before.state,
        "admission": admission, "fresh_containment": {
            "state": retrieved.state, "answer": retrieved.answer, "receipt": retrieved.receipt,
        },
        "fresh_unknown": {"state": unknown.state, "answer": unknown.answer},
        "grounded_bridge": {"known": bridge_known, "unknown": bridge_unknown},
        "model_generation": {"candidate": str(MODEL_CANDIDATE), "output": generated,
                             "exact_fact_present": generated_has_fact},
        "live_adapter_before": initial, "live_adapter_restored": restore,
        "candidate_learning_passed": passed, "model_paraphrase_passed": generated_has_fact,
        "promoted": False,
    }
    payload = json.dumps(receipt, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    receipt["receipt_sha256"] = hashlib.sha256(payload).hexdigest()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"receipt": str(OUT), "candidate_learning_passed": passed,
                      "model_paraphrase_passed": generated_has_fact,
                      "fresh_state": retrieved.state, "unknown_state": unknown.state,
                      "active_adapter": restore.get("active_adapter"),
                      "candidate_only": True, "promoted": False}, indent=2), flush=True)
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
