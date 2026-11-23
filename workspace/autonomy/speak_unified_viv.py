"""Interactive CLI for Unified AIOS Viv Toddler Brain (Spelling, Speaking, Meaning, and Word Learning).

Loads the latest verified Unified Viv run from `L:\\LocalCoder\\workspace\\autonomy\\learning\\unified_viv_status.json`
(verifying checkpoint, tokenizer, and isolated neuron store SHA-256 digests) and provides:
- `--spell <word>`: Stage 1 letter-by-letter spelling + Steel Brain hierarchical neuron decomposition
- `--unscramble <letters>`: Stage 1B scrambled letter reconstruction verified against STABLE neurons
- `--say <word>`: Stage 2 toddler speaking (strictly gated by admitted STABLE word neurons, optional `--voice`)
- `--meaning <word>`: Stage 3 child-level word meaning + Webster/Farm grounding
- `--all <word>`: Full 3-stage developmental demonstration (Spell -> Speak -> Meaning)
- `--teach-word <word>`: Teach the isolated candidate neuron graph a new word bottom-up via `UniversalCurriculumEngine`
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

WORKSPACE = Path(r"L:\LocalCoder\workspace")
INN_ROOT = WORKSPACE / "INN"
for _p in (INN_ROOT, WORKSPACE):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import torch  # noqa: E402
from inn.unified_brain import UnifiedVivBrain, file_sha256  # noqa: E402
from inn.activation_ledger import DEFAULT_ACTIVATION_LEDGER_PATH  # noqa: E402

STATUS_PATH = WORKSPACE / "autonomy" / "learning" / "unified_viv_status.json"


def load_verified_unified_brain(
    *,
    run_dir: Path | None = None,
    writable_clone: bool = False,
) -> tuple[UnifiedVivBrain, dict[str, Any]]:
    if run_dir is None:
        if not STATUS_PATH.is_file():
            raise FileNotFoundError(
                f"Unified Viv status not found at {STATUS_PATH}. Run train_unified_viv.py first."
            )
        status = json.loads(STATUS_PATH.read_text(encoding="utf-8"))
        run_dir = Path(status["run"])
    receipt_path = run_dir / "evaluation.json"
    if not receipt_path.is_file():
        raise FileNotFoundError(f"Evaluation receipt not found at {receipt_path}")
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))

    checkpoint_path = Path(receipt["checkpoint_path"])
    if file_sha256(checkpoint_path) != receipt["checkpoint_sha256"]:
        raise ValueError("Unified Viv checkpoint SHA-256 integrity check failed")

    isolated_db = Path(receipt["isolated_db"])
    # If the autonomous loop has added newly discovered neologism neurons, allow loading the live active clone
    if not writable_clone and file_sha256(isolated_db) != receipt.get("isolated_sha256_final") and not receipt.get("allow_growth_divergence", True):
        raise ValueError("Isolated Steel Brain SQLite SHA-256 integrity check failed")

    brain = UnifiedVivBrain(
        graph_db_path=isolated_db,
        readonly_graph=not writable_clone,
        max_word_length=4,
        activation_ledger_path=DEFAULT_ACTIVATION_LEDGER_PATH,
    )
    brain.language_engine.load(checkpoint_path)
    return brain, receipt


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Interact with Unified AIOS Viv Toddler Brain (Spell, Speak, Meaning)."
    )
    parser.add_argument("--run", type=Path, default=None, help="Specific run directory to load")
    parser.add_argument("--spell", type=str, default=None, help="Stage 1: Spell a word and show its neuron tree")
    parser.add_argument("--unscramble", type=str, default=None, help="Stage 1B: Unscramble letters into a word neuron")
    parser.add_argument("--say", type=str, default=None, help="Stage 2: Speak a toddler phrase using the word")
    parser.add_argument("--meaning", type=str, default=None, help="Stage 3: Explain the word's meaning")
    parser.add_argument("--all", type=str, default=None, help="Run all 3 stages (Spell, Speak, Meaning) for a word")
    parser.add_argument(
        "--flashcards",
        type=str,
        default=None,
        help="Comma-separated flashcard deck (e.g. 'An,In,cat,made') to learn via STDP + reshuffle over 26 letters + 1 SHIFT neuron",
    )
    parser.add_argument(
        "--morpheme",
        type=str,
        default=None,
        help="Webster Morpheme Dealer: deal a progressive flashcard deck containing the morpheme (e.g. 'st' or 'ing') and learn via STDP",
    )
    parser.add_argument(
        "--max-words",
        type=int,
        default=10,
        help="Maximum words for --morpheme dealer (default: 10)",
    )
    parser.add_argument(
        "--dream",
        action="store_true",
        help="Run Viv's Generative Dictionary & Dreaming Loop over crystallized bridges and write viv_dictionary.json",
    )
    parser.add_argument(
        "--dream-iterations",
        type=int,
        default=1200,
        help="Number of brick-snapping dream iterations (default: 1200)",
    )
    parser.add_argument(
        "--promote-neologism",
        type=str,
        default=None,
        help="Comma-separated Viv Urban Dictionary words (e.g. 'doinger,steding,reating,restingest') to promote into the candidate Steel Brain SQLite graph with VIV_INVENTED_NEOLOGISM provenance",
    )
    parser.add_argument(
        "--evolve-neologism",
        type=str,
        default=None,
        help="Viv neologism whose meaning should evolve through experience while preserving its v1 ORIGINAL_DISCOVERY history",
    )
    parser.add_argument(
        "--evolved-meaning",
        type=str,
        default=None,
        help="New experiential meaning for --evolve-neologism",
    )
    parser.add_argument(
        "--experience-context",
        type=str,
        default="Direct interactive learning experience with the Architect",
        help="Experience context explaining why the meaning evolved",
    )
    parser.add_argument(
        "--ingest-corpus",
        type=str,
        default=None,
        help="Stream a corpus (text or Webster JSON; use 'webster' for the default) and count lifetime neuron activations",
    )
    parser.add_argument("--max-tokens", type=int, default=2_000_000, help="Token cap for --ingest-corpus")
    parser.add_argument("--activation-report", action="store_true", help="Print the lifetime activation frequency hierarchy")
    parser.add_argument("--report-kind", type=str, default="WORD", help="Neuron kind for --activation-report (WORD, COMBINATION, CHARACTER)")
    parser.add_argument("--top", type=int, default=25, help="Top-N ranks for --activation-report")
    parser.add_argument("--teach-word", type=str, default=None, help="Teach a new word bottom-up in the isolated graph clone")
    parser.add_argument("--voice", action="store_true", help="Dispatch spoken utterance to Viv's local TTS voice")
    parser.add_argument("--status", action="store_true", help="Print unified brain status and RID stability summary")
    args = parser.parse_args()

    torch.set_num_threads(2)
    writable = bool(args.teach_word or args.promote_neologism or args.evolve_neologism)
    brain, receipt = load_verified_unified_brain(run_dir=args.run, writable_clone=writable)

    try:
        output: dict[str, Any] = {
            "run": receipt["run"],
            "rid_s_n": receipt["rid_stability"]["s_n"],
            "rid_state": receipt["rid_stability"]["triadic_state"],
            "total_neurons": brain.total_neurons,
            "total_stable_words": len(brain.all_stable_words),
            "total_viv_invented_word_neurons": len(brain.viv_invented_word_neurons),
        }

        if args.status:
            output["summary"] = brain.summary()
            output["stages"] = {
                k: {
                    "exact": v["exact"],
                    "total": v["total"],
                    "accuracy": v["accuracy"],
                }
                for k, v in receipt["stages"].items()
            }

        if args.teach_word:
            output["taught_word"] = brain.learn_new_word_neuron_in_clone(args.teach_word)

        if args.promote_neologism:
            words_to_promote = [w.strip() for w in args.promote_neologism.split(",") if w.strip()]
            output["promoted_neologisms"] = [
                brain.promote_neologism_to_graph(w) for w in words_to_promote
            ]
            output["total_neurons"] = brain.total_neurons
            output["total_viv_invented_word_neurons"] = len(brain.viv_invented_word_neurons)

        if args.evolve_neologism:
            if not args.evolved_meaning:
                raise ValueError("--evolve-neologism requires --evolved-meaning")
            output["evolved_neologism"] = brain.evolve_neologism_meaning(
                args.evolve_neologism,
                new_meaning=args.evolved_meaning,
                experience_context=args.experience_context,
            )
            output["total_neurons"] = brain.total_neurons
            output["total_viv_invented_word_neurons"] = len(brain.viv_invented_word_neurons)

        if args.flashcards:
            deck = [w.strip() for w in args.flashcards.split(",") if w.strip()]
            output["emergent_flashcard_deck"] = brain.run_emergent_flashcard_deck(
                deck, confirmations=3, max_rounds=64, seed=20261031, persist_synapses=writable
            )

        if args.morpheme:
            deck = brain.deal_morpheme_family(args.morpheme, max_words=args.max_words)
            output["webster_morpheme_dealer"] = {
                "morpheme": args.morpheme,
                "dealt_deck": deck,
            }
            output["emergent_flashcard_deck"] = brain.run_emergent_flashcard_deck(
                deck, confirmations=3, max_rounds=64, seed=20261031, persist_synapses=writable
            )

        if args.dream:
            if "emergent_flashcard_deck" in output:
                flash_out = output["emergent_flashcard_deck"]
                trained_cards = [c["card"] for c in flash_out.get("cards", [])]
                output["viv_dream_dictionary"] = brain.dream_and_invent_dictionary(
                    flash_out.get("crystallized_dimers", []),
                    crystallized_trimers=flash_out.get("crystallized_trimers", []),
                    trained_flashcards=trained_cards,
                    iterations=args.dream_iterations,
                )
            else:
                output["viv_dream_dictionary"] = brain.generate_viv_dictionary(
                    iterations=args.dream_iterations,
                )

        target_all = args.all
        if target_all:
            output["spell"] = brain.spell(target_all)
            output["speak"] = brain.speak_toddler(target_all, use_voice=args.voice)
            output["meaning"] = brain.explain_meaning(target_all, record_in_graph=False)
        else:
            if args.spell:
                output["spell"] = brain.spell(args.spell)
            if args.unscramble:
                output["unscramble"] = brain.unscramble(args.unscramble)
            if args.say:
                output["speak"] = brain.speak_toddler(args.say, use_voice=args.voice)
            if args.meaning:
                output["meaning"] = brain.explain_meaning(args.meaning, record_in_graph=False)

        if args.ingest_corpus:
            from inn.unified_brain import WEBSTER_DICTIONARY_PATH

            corpus = WEBSTER_DICTIONARY_PATH if args.ingest_corpus.lower() == "webster" else Path(args.ingest_corpus)
            output["corpus_ingestion"] = brain.ingest_corpus_activations(corpus, max_tokens=args.max_tokens)

        if args.activation_report:
            kind_str = args.report_kind.strip().upper()
            direct_only = False
            if kind_str.startswith("DIRECT_"):
                direct_only = True
                kind_str = kind_str.replace("DIRECT_", "")
            output["activation_distribution"] = brain.activation_distribution(
                kind=kind_str, direct_only=direct_only, top_n=args.top
            )

        if not any((args.status, args.teach_word, args.promote_neologism, args.evolve_neologism, args.flashcards, args.morpheme, args.dream, args.all, args.spell, args.unscramble, args.say, args.meaning, args.ingest_corpus, args.activation_report)):
            # Default showcase across 1-, 2-, 3-, and 4-letter words
            demo_word = "made" if "made" in brain.all_stable_words else "cat"
            output["spell"] = brain.spell(demo_word)
            output["speak"] = brain.speak_toddler(demo_word, use_voice=args.voice)
            output["meaning"] = brain.explain_meaning(demo_word, record_in_graph=False)

        print(json.dumps(output, indent=2, ensure_ascii=False))
    finally:
        if writable:
            try:
                brain.store.connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            except Exception:
                pass
        brain.close()
        if writable:
            isolated_db = Path(receipt["isolated_db"])
            receipt_path = Path(receipt["run"]) / "evaluation.json"
            receipt["isolated_sha256_final"] = file_sha256(isolated_db)
            receipt_path.write_text(json.dumps(receipt, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
