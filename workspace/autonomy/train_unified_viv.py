"""Unified AIOS Viv / H-Vive Mind Toddler Developmental Training Runner.

Combines:
1. `Standalone\\NN` (`SQLiteNeuronGraphStore`, `101,251` neurons, `12,584` `STABLE` words,
   `SparseNeuronAttention`, `UniversalCurriculumEngine`) cloned into an isolated run store.
2. `LocalCoder\\UML_Calc` (`uml_engine` + `uml_neural_gate` `!0` division-by-zero boundary
   and triadic RID stability $S_n = RSR \\times LTP \\times RLE$).
3. `LocalCoder\\workspace\\INN` (`LanguageEngine` + `INNCharacterTokenizer`) trained across
   three toddler developmental stages:
   - **Stage 1 (Spelling & Unscrambling)**: Spell 1-to-4 letter words and reconstruct scrambled
     letter inventories grounded in hierarchical neuron routes (`cat = c + at`, `made = ma + de`).
   - **Stage 2 (Toddler Speaking)**: Speak short 2-to-4 word toddler utterances strictly gated
     by admitted `STABLE` word neurons.
   - **Stage 3 (Meaning Binding)**: Bind admitted 1-to-4 letter `WORD` neurons to child-level
     meanings and record `VIV_TODDLER_MEANING_BINDING_V1` in the isolated candidate neuron graph.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

WORKSPACE = Path(r"L:\LocalCoder\workspace")
INN_ROOT = WORKSPACE / "INN"
for _p in (INN_ROOT, WORKSPACE):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import torch  # noqa: E402
from autonomy.inn_hive import _atomic_json  # noqa: E402
from inn.unified_brain import (  # noqa: E402
    DEFAULT_CUMULATIVE_LADDER_DB,
    DEFAULT_LIVE_EMERGENCE_DB,
    UnifiedVivBrain,
    copy_sqlite_store,
    file_sha256,
)

LEARNING_DIR = WORKSPACE / "autonomy" / "learning"
STATUS_PATH = LEARNING_DIR / "unified_viv_status.json"
RUNS_DIR = LEARNING_DIR / "unified_viv_runs"


def utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def run_unified_training(
    *,
    source_db: Path | None = None,
    max_word_length: int = 4,
    per_length_limit: int = 12,
    updates: int = 350,
    batch_size: int = 16,
    lr: float = 2.5e-3,
    threads: int = 4,
    seed: int = 812,
    bind_meanings_in_clone: bool = True,
    output_dir: Path | None = None,
) -> dict[str, Any]:
    torch.set_num_threads(max(1, int(threads)))
    started = time.monotonic()

    origin_db = Path(
        source_db
        if source_db is not None
        else (
            DEFAULT_LIVE_EMERGENCE_DB
            if DEFAULT_LIVE_EMERGENCE_DB.is_file()
            else DEFAULT_CUMULATIVE_LADDER_DB
        )
    ).resolve()
    if not origin_db.is_file():
        raise FileNotFoundError(f"Canonical Steel Brain DB not found: {origin_db}")

    origin_sha_before = file_sha256(origin_db)

    run_dir = (
        Path(output_dir).resolve()
        if output_dir is not None
        else (RUNS_DIR / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ"))
    )
    run_dir.mkdir(parents=True, exist_ok=True)
    isolated_db = run_dir / "isolated_steel_brain.sqlite3"
    copy_sqlite_store(origin_db, isolated_db)
    isolated_sha_initial = file_sha256(isolated_db)

    status_payload: dict[str, Any] = {
        "schema": "VIV_UNIFIED_LEARNING_STATUS_V1",
        "stage": "initializing",
        "at_utc": utc_iso(),
        "run": str(run_dir),
        "origin_db": str(origin_db),
        "origin_sha256_before": origin_sha_before,
        "isolated_db": str(isolated_db),
        "isolated_sha256_initial": isolated_sha_initial,
        "update": 0,
        "total_updates": int(updates),
    }
    _atomic_json(STATUS_PATH, status_payload)

    with UnifiedVivBrain(
        graph_db_path=isolated_db,
        readonly_graph=not bind_meanings_in_clone,
        max_word_length=max_word_length,
        seed=seed,
    ) as brain:
        summary = brain.summary()
        selected_words = brain.select_toddler_curriculum_words(
            per_length_limit=per_length_limit
        )
        curriculum = brain.build_developmental_curriculum(selected_words, seed=seed)

        status_payload.update(
            {
                "stage": "training",
                "at_utc": utc_iso(),
                "brain_summary": summary,
                "curriculum_words_count": len(selected_words),
                "curriculum_words": selected_words,
                "curriculum_rows": {
                    "spelling": len(curriculum["spelling"]),
                    "speaking": len(curriculum["speaking"]),
                    "meaning": len(curriculum["meaning"]),
                    "total": len(curriculum["all"]),
                },
            }
        )
        _atomic_json(STATUS_PATH, status_payload)

        def _on_progress(step: int, total: int, loss: float, telemetry: dict[str, Any]) -> None:
            status_payload.update(
                {
                    "stage": "training",
                    "at_utc": utc_iso(),
                    "update": int(step),
                    "total_updates": int(total),
                    "current_loss": round(float(loss), 6),
                    "uml_grad_state": telemetry.get("uml_grad_state", "Standard Flow"),
                    "uml_grad_norm": round(float(telemetry.get("uml_grad_norm", 0.0)), 6),
                }
            )
            _atomic_json(STATUS_PATH, status_payload)

        train_metrics = brain.train_curriculum(
            curriculum["all"],
            updates=updates,
            batch_size=batch_size,
            lr=lr,
            seed=seed,
            progress_callback=_on_progress,
        )

        status_payload.update(
            {
                "stage": "evaluating",
                "at_utc": utc_iso(),
                "train_metrics": train_metrics,
            }
        )
        _atomic_json(STATUS_PATH, status_payload)

        eval_results = brain.evaluate_curriculum(curriculum)

        # Stage 0 / Emergent Flashcard Deck + Reshuffle Loop over 26 letters + 1 SHIFT neuron
        # Include cased flashcards (e.g. 'An', 'Cat', 'Made') alongside the curriculum words
        flashcard_words = ["An", "In", "Cat", "Sun", "Made", "Said"] + [
            w for w in selected_words if w not in ("an", "in", "cat", "sun", "made", "said")
        ]
        flashcard_report = brain.run_emergent_flashcard_deck(
            flashcard_words,
            confirmations=3,
            max_rounds=64,
            seed=seed,
            persist_synapses=bind_meanings_in_clone,
        )

        # Bind meanings into the isolated candidate neuron graph (never touches origin_db)
        bound_meanings = 0
        last_event_head = None
        if bind_meanings_in_clone:
            for word in selected_words:
                res = brain.explain_meaning(word, record_in_graph=True)
                if res.get("graph_event_head"):
                    bound_meanings += 1
                    last_event_head = res["graph_event_head"]

        rid_metrics = brain.compute_rid_stability(
            spelling_acc=float(eval_results["spelling"]["accuracy"]),
            speaking_acc=float(eval_results["speaking"]["accuracy"]),
            meaning_acc=float(eval_results["meaning"]["accuracy"]),
            loss_before=float(train_metrics["loss_before"]),
            loss_after=float(train_metrics["loss_after"]),
        )

        # Save neural checkpoint and tokenizer manifest
        checkpoint_path = run_dir / "unified_viv_engine.pt"
        brain.language_engine.save(checkpoint_path)
        checkpoint_sha = file_sha256(checkpoint_path)

        tokenizer_manifest = brain.tokenizer.manifest()
        (run_dir / "tokenizer.json").write_text(
            json.dumps(tokenizer_manifest, indent=2), encoding="utf-8"
        )

        # Collect interactive showcase demonstrations across 1-, 2-, 3-, and 4-letter words
        demo_words = [w for w in ("a", "i", "am", "go", "cat", "sun", "made", "said", "went", "tell") if w in brain.all_stable_words][:6]
        demonstrations = []
        for w in demo_words:
            demonstrations.append(
                {
                    "word": w,
                    "spell": brain.spell(w),
                    "speak": brain.speak_toddler(w, use_voice=False),
                    "meaning": brain.explain_meaning(w, record_in_graph=False),
                }
            )

    origin_sha_after = file_sha256(origin_db)
    isolated_sha_final = file_sha256(isolated_db)
    origin_immutable_verified = origin_sha_before == origin_sha_after

    receipt: dict[str, Any] = {
        "schema": "VIV_UNIFIED_EVALUATION_RECEIPT_V1",
        "at_utc": utc_iso(),
        "run": str(run_dir),
        "origin_db": str(origin_db),
        "origin_sha256_before": origin_sha_before,
        "origin_sha256_after": origin_sha_after,
        "origin_immutable_verified": origin_immutable_verified,
        "isolated_db": str(isolated_db),
        "isolated_sha256_initial": isolated_sha_initial,
        "isolated_sha256_final": isolated_sha_final,
        "checkpoint_path": str(checkpoint_path),
        "checkpoint_sha256": checkpoint_sha,
        "tokenizer_sha256": tokenizer_manifest["sha256"],
        "brain_summary": summary,
        "curriculum_words_count": len(selected_words),
        "curriculum_words": selected_words,
        "emergent_flashcard_deck": flashcard_report,
        "train_metrics": train_metrics,
        "stages": {
            stage_key: {
                "exact": eval_results[stage_key]["exact"],
                "total": eval_results[stage_key]["total"],
                "accuracy": round(float(eval_results[stage_key]["accuracy"]), 6),
                "samples": eval_results[stage_key]["samples"],
            }
            for stage_key in ("spelling", "speaking", "meaning")
        },
        "rid_stability": asdict(rid_metrics),
        "bound_meanings_in_clone": bound_meanings,
        "last_graph_event_head": last_event_head,
        "demonstrations": demonstrations,
        "elapsed_seconds": round(time.monotonic() - started, 3),
        "passed": bool(
            origin_immutable_verified
            and flashcard_report["state"] == "PASS"
            and rid_metrics.s_n >= 0.75
            and eval_results["spelling"]["accuracy"] >= 0.80
            and eval_results["speaking"]["accuracy"] >= 0.80
            and eval_results["meaning"]["accuracy"] >= 0.80
        ),
    }

    (run_dir / "evaluation.json").write_text(
        json.dumps(receipt, indent=2), encoding="utf-8"
    )
    status_payload.update(
        {
            "stage": "completed",
            "at_utc": utc_iso(),
            "update": int(updates),
            "total_updates": int(updates),
            "receipt": receipt,
        }
    )
    _atomic_json(STATUS_PATH, status_payload)
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Train Unified AIOS Viv Toddler Brain (Steel Brain Neurons + UML !0 + INN Language)."
    )
    parser.add_argument("--source-db", type=Path, default=None, help="Path to Steel Brain SQLite DB")
    parser.add_argument("--max-word-length", type=int, default=4, help="Maximum word length in toddler ladder (default: 4)")
    parser.add_argument("--per-length-limit", type=int, default=12, help="Curriculum words per word length")
    parser.add_argument("--updates", type=int, default=350, help="Number of optimizer updates")
    parser.add_argument("--batch-size", type=int, default=16, help="Mini-batch size")
    parser.add_argument("--lr", type=float, default=2.5e-3, help="Learning rate")
    parser.add_argument("--threads", type=int, default=4, help="PyTorch CPU threads")
    parser.add_argument("--seed", type=int, default=812, help="Deterministic seed")
    parser.add_argument("--no-bind-graph", action="store_true", help="Do not write meaning bindings into isolated DB clone")
    args = parser.parse_args()

    receipt = run_unified_training(
        source_db=args.source_db,
        max_word_length=args.max_word_length,
        per_length_limit=args.per_length_limit,
        updates=args.updates,
        batch_size=args.batch_size,
        lr=args.lr,
        threads=args.threads,
        seed=args.seed,
        bind_meanings_in_clone=not args.no_bind_graph,
    )
    print(
        json.dumps(
            {
                "run": receipt["run"],
                "passed": receipt["passed"],
                "origin_immutable_verified": receipt["origin_immutable_verified"],
                "total_neurons": receipt["brain_summary"]["total_neurons"],
                "total_stable_words": receipt["brain_summary"]["total_stable_words"],
                "curriculum_words_count": receipt["curriculum_words_count"],
                "loss_before": round(receipt["train_metrics"]["loss_before"], 4),
                "loss_after": round(receipt["train_metrics"]["loss_after"], 4),
                "spelling_acc": receipt["stages"]["spelling"]["accuracy"],
                "speaking_acc": receipt["stages"]["speaking"]["accuracy"],
                "meaning_acc": receipt["stages"]["meaning"]["accuracy"],
                "rid_s_n": receipt["rid_stability"]["s_n"],
                "rid_state": receipt["rid_stability"]["triadic_state"],
                "flashcard_deck_state": receipt["emergent_flashcard_deck"]["state"],
                "flashcard_mastered": f"{receipt['emergent_flashcard_deck']['mastered_cards']}/{receipt['emergent_flashcard_deck']['deck_size']}",
                "flashcard_reshuffles": receipt["emergent_flashcard_deck"]["total_reshuffles"],
                "hardcoded_primitives": receipt["emergent_flashcard_deck"]["hardcoded_foundation"]["total_hardcoded_primitives"],
                "bound_meanings_in_clone": receipt["bound_meanings_in_clone"],
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
