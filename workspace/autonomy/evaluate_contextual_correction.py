"""Deterministic tiny-corpus calibration and untouched typo-context evaluation."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import random
import urllib.request

import torch

from experimental_contextual_correction import ContextualCorrection
from experimental_word_char_lm import WordCharTransformer, next_piece_loss
from viv_answer_frame import LocalAnswerFrameParser
from word_char_tokenizer import WordCharTokenizer


TRAIN = [
    "This angle is acute.", "The angle measures degrees.",
    "An angel has wings.", "An angel can fly.",
    "The river bank is muddy.", "Money is kept at the bank.",
    "The capitol is a building.", "Each country has a capital.",
    "Sunlight scatters blue.", "A lamp gives bright light.",
    "She smiles when birds fly.", "River waters flood the banks.",
    "Visitors enter the building.", "A nation's flag marks its capital.",
]

# Exact noisy strings never occur in TRAIN. Membership below keeps the
# domain-ambiguous capitel example in calibration and a separate one held out.
PAIRS = [
    ("The angl is acute.", "angle"),
    ("This angl measures degrees.", "angle"),
    ("Visitors toured the capitel.", "capitol"),
    ("A nation's capitel marks its flag.", "capital"),
    ("She saw an angl fly.", "angel"),
    ("An angl has wings.", "angel"),
    ("River baank is muddy.", "bank"),
    ("Money is kept at the baank.", "bank"),
]
CALIBRATION_INDICES = [0, 1, 2, 4]
HELD_OUT_INDICES = [3, 5, 6, 7]


def _sha(value) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _metrics(rows, threshold):
    selected = [row for row in rows if row["margin"] is not None and row["margin"] >= threshold]
    correct = sum(row["candidate_correct"] for row in selected)
    return {
        "total": len(rows), "accepted_by_margin": len(selected),
        "correct_accepted": correct, "wrong_accepted": len(selected) - correct,
        "abstained": len(rows) - len(selected),
        "candidate_accuracy_all": sum(row["candidate_correct"] for row in rows) / max(1, len(rows)),
        "precision_accepted": correct / max(1, len(selected)),
    }


def main() -> None:
    seed = 20261110
    random.seed(seed)
    torch.manual_seed(seed)
    torch.set_num_threads(2)
    torch.use_deterministic_algorithms(True)

    tokenizer = WordCharTokenizer.from_texts(TRAIN)
    model = WordCharTransformer(len(tokenizer.words), width=32, heads=4, layers=1, max_context=128)
    sequences = [tokenizer.encode(text) for text in TRAIN]
    optimizer = torch.optim.AdamW(model.parameters(), lr=0.006)
    initial_loss = sum(next_piece_loss(model, seq).item() for seq in sequences) / len(sequences)
    train_steps = 900
    for step in range(train_steps):
        optimizer.zero_grad(set_to_none=True)
        loss = next_piece_loss(model, sequences[step % len(sequences)])
        loss.backward()
        optimizer.step()
    final_loss = sum(next_piece_loss(model, seq).item() for seq in sequences) / len(sequences)

    corrector = ContextualCorrection(tokenizer, model)
    with urllib.request.urlopen("http://127.0.0.1:1234/v1/models", timeout=5) as response:
        local_models = json.load(response).get("data", [])
    if not local_models:
        raise RuntimeError("local DeepSeek answer-frame parser is unavailable")
    frame_parser = LocalAnswerFrameParser(
        model_id=local_models[0]["id"],
        active_adapter=local_models[0].get("active_adapter"),
    )
    rows = []
    for index, (text, expected) in enumerate(PAIRS):
        proposal = corrector.propose(text)
        rows.append({
            "partition": "calibration" if index in CALIBRATION_INDICES else "held_out",
            "input": text, "expected_word": expected,
            "proposed_word": proposal.get("candidate"),
            "corrected_text": proposal.get("corrected"),
            "candidate_correct": proposal.get("candidate") == expected,
            "margin": proposal.get("margin"), "gain": proposal.get("gain"),
            "ranked_candidates": [
                {"word": item["candidate"], "log_probability": item["log_probability"]}
                for item in proposal.get("ranked", [])
            ],
        })

    calibration = [rows[index] for index in CALIBRATION_INDICES]
    wrong_margins = [r["margin"] for r in calibration
                     if not r["candidate_correct"] and r["margin"] is not None]
    threshold = max(wrong_margins) + 0.001 if wrong_margins else 0.0
    calibration_metrics = _metrics(calibration, threshold)
    heldout = [rows[index] for index in HELD_OUT_INDICES]
    heldout_margin_metrics = _metrics(heldout, threshold)

    def answer(text: str) -> str:
        return model.generate(tokenizer, text, max_new_pieces=6)

    verified = []
    for row in heldout:
        question = "What proposition does the supplied sentence express?"
        proposal = corrector.propose(row["input"])
        correction = ({proposal["suspect"]: proposal["candidate"]}
                      if proposal.get("suspect") and proposal.get("candidate") else {})
        comparison = {}
        def frame_compare(original_answer: str, corrected_answer: str) -> dict:
            comparison.update(frame_parser.compare(
                question=question, original_sentence=row["input"],
                corrected_sentence=proposal["corrected"],
                original_answer=original_answer, corrected_answer=corrected_answer,
                domain="general", correction=correction,
            ))
            return comparison
        result = corrector.verify(row["input"], answer, min_margin=threshold,
                                  answers_equivalent=frame_compare)
        verified.append({
            "input": row["input"], "expected_word": row["expected_word"],
            "proposed_word": row["proposed_word"], "decision": result["decision"],
            "reason": result["reason"], "answers_agree": result.get("answers_agree"),
            "frame_state": comparison.get("state", "NOT_RUN"),
            "frame_reason": comparison.get("reason"),
            "frame_comparison": comparison,
            "original_answer": result.get("original_answer"),
            "corrected_answer": result.get("corrected_answer"),
        })

    corpus_dir = Path(__file__).resolve().parent / "learning" / "contextual_correction_evals"
    corpus_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    receipt_path = corpus_dir / f"context_correction_{stamp}.json"
    receipt = {
        "schema": "viv-contextual-correction-eval-v1",
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "seed": seed, "device": "cpu", "model": {"width": 32, "heads": 4, "layers": 1,
                                                       "train_steps": train_steps},
        "tokenizer_sha256": tokenizer.manifest()["sha256"],
        "training_corpus_sha256": _sha(TRAIN), "pair_set_sha256": _sha(PAIRS),
        "training_sentence_count": len(TRAIN), "training_loss": {
            "initial_mean": initial_loss, "final_mean": final_loss,
        },
        "split": {"calibration_indices": CALIBRATION_INDICES, "held_out_indices": HELD_OUT_INDICES,
                  "exact_inputs_disjoint_from_training": all(text not in TRAIN for text, _ in PAIRS)},
        "threshold_selection": {
            "method": "max_wrong_calibration_margin_plus_0.001",
            "minimum_margin": threshold,
            "warning": "tiny calibration set; exploratory threshold only",
        },
        "calibration_metrics": calibration_metrics,
        "held_out_candidate_metrics": heldout_margin_metrics,
        "held_out_answer_verification": verified,
        "examples": rows,
    }
    receipt["receipt_sha256"] = _sha(receipt)
    receipt_path.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "receipt": str(receipt_path), "receipt_sha256": receipt["receipt_sha256"],
        "training_loss": receipt["training_loss"], "calibration_threshold": threshold,
        "calibration": calibration_metrics, "held_out_candidates": heldout_margin_metrics,
        "held_out_verification": {
            "accepted": sum(row["decision"] == "ACCEPT_CORRECTION" for row in verified),
            "rejected_or_abstained": sum(row["decision"] != "ACCEPT_CORRECTION" for row in verified),
            "answer_agreement": sum(row["answers_agree"] is True for row in verified),
        },
    }, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()
