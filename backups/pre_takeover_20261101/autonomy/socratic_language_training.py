"""Bounded spelling and sentence lessons for the existing Unified Viv checkpoint."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
from pathlib import Path
import random
import sys
import time
from datetime import datetime, timezone

WORKSPACE = Path(__file__).resolve().parents[1]
for source_root in (WORKSPACE, WORKSPACE / "INN", WORKSPACE / "aios_rebuild"):
    if str(source_root) not in sys.path:
        sys.path.insert(0, str(source_root))

SENTENCE_LESSONS = {
    "cat": "The cat sat.",
    "dog": "The dog ran.",
    "sun": "The sun is hot.",
    "sky": "The sky is blue.",
    "wave": "The wave is big.",
}


def sentence_curriculum():
    lessons = [{"prompt": f"Say: {word}\n", "target": sentence}
               for word, sentence in SENTENCE_LESSONS.items()]
    combinations, heldout = [], []
    for noun_index, noun in enumerate(("cat", "dog", "bird", "child")):
        for verb_index, verb in enumerate(("sat", "ran", "slept", "ate")):
            example = {"prompt": f"Say: {noun} {verb}\n", "target": f"The {noun} {verb}."}
            destination = heldout if verb_index == (noun_index + 2) % 4 else combinations
            destination.append(example)
    return lessons, combinations, heldout


def evaluate(engine, examples, guard):
    rows = []
    for example in examples:
        guard.check()
        generated = engine.speak(example["prompt"], max_new=80)
        rows.append({**example, "generated": generated, "exact": generated == example["target"]})
    return {"exact": sum(row["exact"] for row in rows), "total": len(rows), "examples": rows}


def learning_passed(before, after, unchanged):
    retained = [row for row in before["retention"]["examples"] if row["exact"]]
    after_by_prompt = {row["prompt"]: row for row in after["retention"]["examples"]}
    retention_ok = bool(retained) and sum(
        after_by_prompt[row["prompt"]]["exact"] for row in retained
    ) / len(retained) >= 0.95
    return bool(
        unchanged and retention_ok
        and all(after[name]["exact"] == after[name]["total"] for name in ("spelling", "sentences"))
        and after["fresh_combinations"]["exact"] >= 3
        and after["fresh_combinations"]["exact"] > before["fresh_combinations"]["exact"]
    )


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def body_receipt(verdict, run_id):
    return {**{key: value for key, value in verdict.items() if key != "body_runtime_permit"},
            "candidate_run_id": run_id}


def run_language_lessons(updates=300):
    if not 1 <= updates <= 500:
        raise ValueError("Language lesson budget must be 1..500 updates")
    from main_core.mind_runtime_gate import RuntimeBodyGuard
    from autonomy.inn_candidate_lease import InnCandidateLease, LeaseAwareRuntimeGuard
    from viv_autonomy import file_lock, worker_alive

    with file_lock(WORKSPACE / "autonomy" / "socratic_language_training.lock"):
        if worker_alive():
            raise RuntimeError("The Hive worker must be paused for this bounded lesson")
        run_id = "language-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        guard = RuntimeBodyGuard(requested_threads=2, candidate_run_id=run_id)
        verdict = guard.check(force=True)
        status_path = WORKSPACE / "autonomy/learning/unified_viv_status.json"
        status_hash = digest(status_path)
        status = json.loads(status_path.read_text(encoding="utf-8"))
        receipt_path = Path(status["run"]) / "evaluation.json"
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        parent = Path(receipt["checkpoint_path"])
        parent_hash = digest(parent)
        if receipt.get("passed") is not True or parent_hash != receipt["checkpoint_sha256"]:
            raise ValueError("Unified language parent failed receipt/integrity verification")
        lease = InnCandidateLease.begin(
            run_id, [digest(__file__), digest(receipt_path), parent_hash],
            float(verdict["stability_sn"]), verdict.get("body_runtime_permit"),
            verdict.get("requested_threads"),
        )
        guard = LeaseAwareRuntimeGuard(guard, lease)
        run = lease.stage_root
        started = time.monotonic()
        lease.write_json(run / "body_gate.json", body_receipt(verdict, run_id))
        import torch
        from inn.unified_brain import UnifiedVivBrain

        torch.set_num_threads(2)
        torch.use_deterministic_algorithms(True)
        brain = None
        try:
            brain = UnifiedVivBrain(graph_db_path=Path(receipt["isolated_db"]), readonly_graph=True)
            engine = brain.language_engine
            engine.load(parent)
            lessons, combinations, heldout = sentence_curriculum()
            spelling = [row for row in brain.build_developmental_curriculum(
                list(SENTENCE_LESSONS), seed=812
            )["spelling"] if row["subtask"] == "spell_word"]
            if len(spelling) != len(SENTENCE_LESSONS):
                raise ValueError("A lesson word lacks an existing verified word neuron")
            old_curriculum = brain.build_developmental_curriculum(status["curriculum_words"], seed=812)
            retention = old_curriculum["spelling"] + old_curriculum["meaning"]
            taught = spelling + lessons + combinations
            reserved_targets = {row["target"] for row in heldout}
            if reserved_targets & {row["target"] for row in taught + retention}:
                raise ValueError("Fresh sentence targets overlap teaching data")
            tests = {"spelling": spelling, "sentences": lessons,
                     "fresh_combinations": heldout, "retention": retention}
            lease.write_json(run / "lessons.json", {"teaching": taught, "retention": retention, "heldout": heldout})
            lease.write_json(run / "protocol.json", {
                "parent": str(parent), "parent_sha256": parent_hash,
                "updates": updates, "threads": 2, "seconds_limit": 600,
                "scope": "Five word spellings, five complete sentences, and four unseen noun/verb combinations",
                "gate": "All taught spelling/sentences; >=3/4 fresh combinations with improvement; >=95% prior correct spelling/meaning retained",
                "training_targets": "Explicit elementary English lessons; tutor log outputs are not assumed correct",
                "live_activated": False,
            })
            before = {name: evaluate(engine, examples, guard) for name, examples in tests.items()}
            lease.write_json(run / "before.json", before)
            print(json.dumps({"run": run_id, "before": {name: result["exact"] for name, result in before.items()}}), flush=True)
            rng = random.Random(812)
            for group in engine.optimizer.param_groups:
                group["lr"] = 0.001
            for update in range(1, updates + 1):
                guard.check()
                if time.monotonic() - started > 600:
                    raise TimeoutError("Language lesson exceeded its 600-second budget")
                batch = rng.choices(taught, k=8) + rng.choices(retention, k=8)
                telemetry = engine.train_joint(batch, [])
                if update % 50 == 0:
                    print(json.dumps({"update": update, "total": updates, "loss": telemetry["language_loss"]}), flush=True)
            guard.check(force=True)
            buffer = io.BytesIO()
            engine.save(buffer)
            lease.write_artifact(run / "engine.pt", buffer.getvalue())
            brain.close()
            brain = UnifiedVivBrain(graph_db_path=Path(receipt["isolated_db"]), readonly_graph=True)
            engine = brain.language_engine
            engine.load(run / "engine.pt")
            after = {name: evaluate(engine, examples, guard) for name, examples in tests.items()}
            unchanged = digest(parent) == parent_hash and digest(status_path) == status_hash
            result = {
                "schema": "socratic_language_candidate_v1", "run": str(lease.final_root),
                "parent": str(parent), "parent_sha256": parent_hash,
                "checkpoint_sha256": digest(run / "engine.pt"),
                "before": before, "after": after, "parent_unchanged": unchanged,
                "passed": learning_passed(before, after, unchanged), "live_activated": False,
                "updates": updates, "elapsed_seconds": time.monotonic() - started,
                "evaluation_scope": "Small development test of spelling and sentence composition; general language mastery unproven",
            }
            verdict = guard.check(force=True)
            lease.write_json(run / "evaluation.json", result)
            lease.commit()
            print(json.dumps({"run": result["run"], "passed": result["passed"],
                              "after": {name: value["exact"] for name, value in after.items()}}), flush=True)
            return result
        except Exception as exc:
            try:
                lease.write_json(run / "failure.json", {"error": str(exc), "type": type(exc).__name__, "live_activated": False})
            except Exception:
                pass
            raise
        finally:
            if brain is not None:
                brain.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--updates", type=int, default=300)
    arguments = parser.parse_args()
    outcome = run_language_lessons(arguments.updates)
    raise SystemExit(0 if outcome["passed"] else 2)
