"""Compare correction paths with the already-running local DeepSeek endpoint."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import urllib.request

import torch

from evaluate_contextual_correction import (
    CALIBRATION_INDICES, HELD_OUT_INDICES, PAIRS, TRAIN,
)
from experimental_contextual_correction import ContextualCorrection
from experimental_word_char_lm import WordCharTransformer, next_piece_loss
from relation_alias_store import RelationAliasStore
from viv_answer_frame import LocalAnswerFrameParser
from word_char_tokenizer import WordCharTokenizer


URL = "http://127.0.0.1:1234"
QUESTIONS = {
    "The angl is acute.": "What does the sentence say is acute?",
    "This angl measures degrees.": "What does the sentence say measures degrees?",
    "Visitors toured the capitel.": "What place did the visitors tour?",
    "A nation's capitel marks its flag.": "What place does the sentence say a nation has?",
    "She saw an angl fly.": "What entity does the sentence say she saw flying?",
    "An angl has wings.": "What kind of entity does the sentence say has wings?",
    "River baank is muddy.": "What is described as muddy?",
    "Money is kept at the baank.": "Where is the money kept?",
}
DOMAINS = {
    "The angl is acute.": "geometry",
    "This angl measures degrees.": "geometry",
    "Visitors toured the capitel.": "civic",
    "A nation's capitel marks its flag.": "civic",
    "She saw an angl fly.": "general",
    "An angl has wings.": "general",
    "River baank is muddy.": "geography",
    "Money is kept at the baank.": "finance",
}
ALIASES = {
    ("geometry", "angle"): "geometric_angle",
    ("geometry", "angel"): "angel_entity",
    ("geometry", "acute"): "acute_relation",
    ("geometry", "is"): "copula",
    ("geometry", "is described as"): "copula",
    ("civic", "capital"): "capital_city",
    ("civic", "capitol"): "capitol_building",
    ("geography", "bank"): "river_bank",
    ("geography", "river bank"): "river_bank",
    ("geography", "is"): "copula",
    ("geography", "is described as"): "copula",
    ("geography", "muddy"): "property:muddy",
    ("geography", "is muddy"): "property:muddy",
    ("geography", "is described as muddy"): "property:muddy",
    ("geography", "described as muddy"): "property:muddy",
    ("finance", "bank"): "financial_institution",
    ("general", "angel"): "angel_entity",
    ("general", "angle"): "angle_entity",
}
RELATION_ALIAS_FIXTURE = {
    ("geometry", "acute"): "acute_relation",
    ("geometry", "is acute"): "acute_relation",
    ("geometry", "is"): "copula",
    ("geometry", "is described as"): "copula",
    ("geometry", "measures"): "measures",
    ("geography", "is"): "copula",
    ("geography", "is described as"): "copula",
    ("geography", "muddy"): "property:muddy",
    ("geography", "is muddy"): "property:muddy",
    ("geography", "is described as muddy"): "property:muddy",
    ("geography", "described as muddy"): "property:muddy",
    ("finance", "kept"): "kept_at",
}
RELATION_SIGNATURE_FIXTURE = {
    "measures": {"object": "value"},
}


def _request(path: str, payload=None):
    data = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(URL + path, data=data,
                                    headers={"Content-Type": "application/json"} if data else {})
    with urllib.request.urlopen(request, timeout=100) as response:
        return json.load(response)


def _sha(obj) -> str:
    return hashlib.sha256(json.dumps(obj, ensure_ascii=False, sort_keys=True,
                                     separators=(",", ":")).encode("utf-8")).hexdigest()


def _candidate_span_hint(sentence: str, proposal: dict) -> dict | None:
    suspect, candidate = proposal.get("suspect"), proposal.get("candidate")
    if not suspect or not candidate:
        return None
    matches = list(re.finditer(rf"(?<!\w){re.escape(suspect)}(?!\w)", sentence, re.IGNORECASE))
    if len(matches) != 1:
        return None
    match = matches[0]
    return {"start": match.start(), "end": match.end(),
            "surface": match.group(0), "candidate": candidate}


def _answer(model_id: str, expected_adapter: str | None, sentence: str, question: str) -> str:
    result = _request("/v1/chat/completions", {
        "model": model_id,
        "messages": [
            {"role": "system", "content": (
                "Answer only from the supplied sentence. Give a concise answer. "
                "If the sentence does not support an answer, say unclear."
            )},
            {"role": "user", "content": f"Sentence: {sentence}\nQuestion: {question}"},
        ],
        "max_tokens": 40, "temperature": 0,
        "stop": ["\nUSER:", "\nSYSTEM:"],
    })
    if result.get("active_adapter") != expected_adapter:
        raise RuntimeError("local adapter changed during paired-answer evaluation")
    return result["choices"][0]["message"]["content"].strip()


def main() -> None:
    argument_parser = argparse.ArgumentParser()
    argument_parser.add_argument(
        "--indices", type=int, nargs="+", default=list(range(len(PAIRS))),
        help="Pair indices to execute; default runs all pairs",
    )
    args = argument_parser.parse_args()
    if any(index < 0 or index >= len(PAIRS) for index in args.indices):
        argument_parser.error(f"indices must be between 0 and {len(PAIRS) - 1}")
    selected_indices = list(dict.fromkeys(args.indices))
    model_info = _request("/v1/models")
    if not model_info.get("data"):
        raise RuntimeError("local model endpoint returned no models")
    model_id = model_info["data"][0]["id"]
    active_adapter = model_info["data"][0].get("active_adapter")
    relation_store = RelationAliasStore()
    for (domain, alias), relation_id in RELATION_ALIAS_FIXTURE.items():
        relation_store.add_alias(domain, alias, relation_id)
    for relation_id, arguments in RELATION_SIGNATURE_FIXTURE.items():
        for argument_name, expected_type in arguments.items():
            relation_store.add_signature(relation_id, argument_name, expected_type)
    relation_aliases = relation_store.relation_aliases()
    relation_signatures = relation_store.signatures()
    frame_parser = LocalAnswerFrameParser(model_id=model_id, active_adapter=active_adapter,
                                          aliases=ALIASES,
                                          relation_aliases=relation_aliases,
                                          relation_signatures=relation_signatures)

    torch.manual_seed(20261110)
    torch.set_num_threads(2)
    torch.use_deterministic_algorithms(True)
    tokenizer = WordCharTokenizer.from_texts(TRAIN)
    model = WordCharTransformer(len(tokenizer.words), width=32, heads=4, layers=1, max_context=128)
    sequences = [tokenizer.encode(text) for text in TRAIN]
    optimizer = torch.optim.AdamW(model.parameters(), lr=0.006)
    for step in range(900):
        optimizer.zero_grad(set_to_none=True)
        loss = next_piece_loss(model, sequences[step % len(sequences)])
        loss.backward()
        optimizer.step()
    corrector = ContextualCorrection(tokenizer, model)

    proposals = [corrector.propose(text) for text, _ in PAIRS]
    calibration = [proposals[i] for i in CALIBRATION_INDICES]
    calibration_pairs = [PAIRS[i] for i in CALIBRATION_INDICES]
    wrong_margins = [p["margin"] for p, (_, expected) in zip(calibration, calibration_pairs)
                     if p.get("candidate") != expected and p.get("margin") is not None]
    threshold = max(wrong_margins) + 0.001 if wrong_margins else 0.0
    calibration_results = [{
        "input": text, "expected_word": expected,
        "proposed_word": proposal.get("candidate"),
        "candidate_correct": proposal.get("candidate") == expected,
        "margin": proposal.get("margin"),
        "accepted_by_margin": proposal.get("margin") is not None and proposal["margin"] >= threshold,
    } for proposal, (text, expected) in zip(calibration, calibration_pairs)]

    out_dir = Path(__file__).resolve().parent / "learning" / "contextual_correction_evals"
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    progress_path = out_dir / f"local_answerer_progress_{stamp}.json"
    results = []
    for index in selected_indices:
        text, expected = PAIRS[index]
        question = QUESTIONS[text]
        proposal = proposals[index]
        def answer_fn(candidate_text: str) -> str:
            return _answer(model_id, active_adapter, candidate_text, question)
        correction = ({proposal["suspect"]: proposal["candidate"]}
                      if proposal.get("suspect") and proposal.get("candidate") else {})
        candidate_hint = _candidate_span_hint(text, proposal)
        comparison_cache = {}
        def frame_compare(original_answer: str, corrected_answer: str) -> dict:
            comparison_cache.update(frame_parser.compare(
                question=question,
                original_sentence=text,
                corrected_sentence=proposal["corrected"],
                original_answer=original_answer,
                corrected_answer=corrected_answer,
                domain=DOMAINS[text],
                correction=correction,
                candidate_span_hint=candidate_hint,
            ))
            return comparison_cache
        result = corrector.verify(text, answer_fn, min_margin=threshold,
                                  answers_equivalent=frame_compare)
        results.append({
            "partition": "calibration" if index in CALIBRATION_INDICES else "held_out",
            "input": text, "question": question, "expected_word": expected,
            "proposed_word": proposal.get("candidate"),
            "candidate_correct": proposal.get("candidate") == expected,
            "margin": proposal.get("margin"), "gain": proposal.get("gain"),
            "decision": result["decision"], "reason": result["reason"],
            "answers_agree": result.get("answers_agree"),
            "frame_state": comparison_cache.get("state", "NOT_RUN"),
            "frame_reason": comparison_cache.get("reason"),
            "frame_comparison": comparison_cache,
            "original_answer": result.get("original_answer"),
            "corrected_answer": result.get("corrected_answer"),
        })
        progress = {
            "schema": "viv-contextual-correction-local-answerer-progress-v1",
            "model_id": model_id, "active_adapter": active_adapter,
            "completed_count": len(results), "selected_indices": selected_indices,
            "results": results,
        }
        progress_path.write_text(json.dumps(progress, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps({"completed": len(results), "total": len(selected_indices),
                          "partition": results[-1]["partition"], "input": text,
                          "frame_state": results[-1]["frame_state"],
                          "frame_reason": results[-1]["frame_reason"],
                          "decision": results[-1]["decision"]}, ensure_ascii=False), flush=True)

    path = out_dir / f"local_answerer_{stamp}.json"
    receipt = {
        "schema": "viv-contextual-correction-local-answerer-v1",
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "endpoint": URL, "model_id": model_id, "active_adapter": active_adapter,
        "correction_threshold": threshold,
        "frame_schema": "viv_answer_frame_v1",
        "frame_parser": "prompted local DeepSeek; deterministic schema/evidence/alias validation",
        "domain_alias_fixture_sha256": _sha([
            {"domain": domain, "alias": alias, "canonical_id": entity_id}
            for (domain, alias), entity_id in sorted(ALIASES.items())
        ]),
        "relation_alias_schema": "domain_id+alias_norm->canonical_relation_id",
        "relation_alias_fixture_sha256": _sha([
            {"domain": domain, "alias_norm": alias, "canonical_relation_id": relation_id}
            for (domain, alias), relation_id in sorted(relation_aliases.items())
        ]),
        "relation_signatures": relation_signatures,
        "calibration_pair_indices": CALIBRATION_INDICES,
        "held_out_pair_indices": HELD_OUT_INDICES,
        "selected_indices": selected_indices,
        "calibration_results": calibration_results,
        "calibration_metrics": {
            "total": len(calibration_results),
            "accepted_by_margin": sum(r["accepted_by_margin"] for r in calibration_results),
            "wrong_accepted": sum(r["accepted_by_margin"] and not r["candidate_correct"] for r in calibration_results),
            "correct_accepted": sum(r["accepted_by_margin"] and r["candidate_correct"] for r in calibration_results),
        },
        "training_corpus_sha256": _sha(TRAIN),
        "pair_set_sha256": _sha(PAIRS),
        "tokenizer_sha256": tokenizer.manifest()["sha256"],
        "results": results,
    }
    receipt["receipt_sha256"] = _sha(receipt)
    path.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    held_out_results = [row for row in results if row["partition"] == "held_out"]
    calibration_results = [row for row in results if row["partition"] == "calibration"]
    print(json.dumps({
        "receipt": str(path), "receipt_sha256": receipt["receipt_sha256"],
        "model_id": model_id, "active_adapter": active_adapter,
        "correction_threshold": threshold,
        "calibration_metrics": receipt["calibration_metrics"],
        "calibration": {"total": len(calibration_results),
                        "accepted": sum(r["decision"] == "ACCEPT_CORRECTION" for r in calibration_results),
                        "frame_states": {state: sum(r["frame_state"] == state for r in calibration_results)
                                         for state in ("AGREES", "CONTRADICTS", "UNKNOWN", "NOT_RUN")}},
        "held_out": len(held_out_results),
        "held_out_candidate_correct": sum(r["candidate_correct"] for r in held_out_results),
        "held_out_accepted": sum(r["decision"] == "ACCEPT_CORRECTION" for r in held_out_results),
        "held_out_answer_agreement": sum(r["answers_agree"] is True for r in held_out_results),
        "held_out_frame_states": {state: sum(r["frame_state"] == state for r in held_out_results)
                         for state in ("AGREES", "CONTRADICTS", "UNKNOWN", "NOT_RUN")},
    }, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()
