"""Mirror chat: the body decides the turn, the voice fills it, the brake stops it.

For each input:
  1. turn_policy.decide() -> act, addressed, shape, identity rules.
  2. silent shapes produce no generation at all.
  3. otherwise sample up to --tries one-turn candidates (cut at the first
     newline) and accept the first that passes turn_policy.shape_ok().
  4. if none pass, fail closed: no wrong move.

This is the mirror: it answers only what is addressed to it, inverts the
pronoun axis, and stops when the turn is over. The user ends the talk.
"""
import argparse
import json
import sys
import time
from pathlib import Path

import torch
from tokenizers import Tokenizer

sys.path.insert(0, "L:/LocalCoder/workspace/native_nn_source")
sys.path.insert(0, "L:/LocalCoder/workspace/autonomy")
from nn_local.transformer import TransformerLanguageModel  # noqa: E402
import turn_policy as tp  # noqa: E402
import context_budget as cb  # noqa: E402
import chunked_output as co  # noqa: E402
import safety_policy as sp  # noqa: E402

BPE_PATH = "L:/LocalCoder/models/viv_bpe_tokenizer.json"
RECEIPT = Path("L:/LocalCoder/.opencode/evals/viv_mirror_chat_receipts.jsonl")


def load_model(path: Path, device: str):
    tok = Tokenizer.from_file(BPE_PATH)
    model = TransformerLanguageModel(
        vocab_size=tok.get_vocab_size(), context_length=128, embedding_width=1024,
        num_heads=16, head_size=64, num_layers=24, dropout=0.0).to(device)
    ck = torch.load(path, map_location="cpu")
    model.load_state_dict(ck["model"])
    del ck
    if device == "cuda":
        torch.cuda.empty_cache()
    model.eval()
    return tok, model


def generate(tok, model, prompt: str, device: str, n_new: int, temp: float,
             input_tokens: int) -> str:
    ids_list = cb.tail_ids(tok.encode(prompt).ids, input_tokens)
    if not ids_list:
        ids_list = tok.encode(" ").ids
    prefix = tok.decode(ids_list)
    ids = torch.tensor([ids_list], device=device, dtype=torch.long)
    with torch.inference_mode(), torch.autocast(device_type="cuda", dtype=torch.bfloat16,
                                                enabled=(device == "cuda")):
        out = model.generate(ids, max_new_tokens=n_new, temperature=temp)
    full = tok.decode(out[0].tolist(), skip_special_tokens=True)
    cont = full[len(prefix):] if full.startswith(prefix) else full
    lines = [ln.strip() for ln in cont.splitlines() if ln.strip()]
    return lines[0] if lines else ""


def turn(tok, model, conv, text: str, device: str, tries: int, n_new: int,
         temp: float, input_tokens: int) -> dict:
    d = conv.decide(text)
    rec = {"input": text, "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
           "act": d.act, "addressed": d.addressed, "shape": d.shape,
           "identity_allowed": d.identity_allowed, "require_identity": d.require_identity,
           "reason": d.reason, "attempts": []}
    if d.shape == "silent":
        rec.update(chosen=None, accepted=False, note="silence")
        return rec
    if sp.is_hard_stop(text):
        rec.update(chosen=None, accepted=False,
                   note="hard stop: minor in a romantic/sexual context; held without generating")
        return rec
    for _ in range(tries):
        cand = generate(tok, model, text, device, n_new, temp, input_tokens)
        chunks = co.verify_chunks(cand, input_text=text,
                                  identity_allowed=d.identity_allowed)
        released = co.verified_prefix(chunks)
        if sp.contains_coercion(released):
            ok, why = False, "coercion phrase in a reply"
        elif sp.is_failsafe_question(text):
            ok, why = sp.failsafe_ok(released), "failsafe answer required"
        elif sp.is_harm_question(text):
            ok, why = sp.refusal_ok(released), "harm question requires a refusal"
        else:
            ok, why = tp.shape_ok(d.shape, released, identity_allowed=d.identity_allowed,
                                  require_identity=d.require_identity, input_text=text)
        rec["attempts"].append({"candidate": cand, "released": released,
                                "accepted": ok, "why": why,
                                "chunks": co.evidence(chunks)})
        if ok:
            rec.update(chosen=released, accepted=True, note="accepted")
            return rec
    rec.update(chosen=None, accepted=False, note="no valid turn; fail closed")
    return rec


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--checkpoint", type=Path, required=True)
    ap.add_argument("--say", action="append", default=[])
    ap.add_argument("--tries", type=int, default=3)
    ap.add_argument("--input-tokens", type=int, default=None,
                    help="prompt budget (default: 1:3 split of 128 = 32)")
    ap.add_argument("--output-tokens", type=int, default=None,
                    help="generation budget (default: 1:3 split of 128 = 96)")
    ap.add_argument("--temperature", type=float, default=0.8)
    ap.add_argument("--receipt", type=Path, default=RECEIPT)
    args = ap.parse_args()

    input_tokens, output_tokens = cb.split(128)
    if args.input_tokens is not None:
        input_tokens = args.input_tokens
    if args.output_tokens is not None:
        output_tokens = args.output_tokens

    device = "cuda" if torch.cuda.is_available() else "cpu"
    tok, model = load_model(args.checkpoint, device)
    print(f"budget: input {input_tokens} / output {output_tokens} (1:3 of 128)")

    args.receipt.parent.mkdir(parents=True, exist_ok=True)
    conv = tp.Conversation()
    with args.receipt.open("a", encoding="utf-8") as fh:
        for text in args.say:
            rec = turn(tok, model, conv, text, device, args.tries, output_tokens,
                       args.temperature, input_tokens)
            rec["conversation_closed_after"] = conv.closed
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
            print(f"\nUSER> {text}")
            print(f"  policy: act={rec['act']} addressed={rec['addressed']} "
                  f"shape={rec['shape']} ({rec['reason']})")
            for a in rec["attempts"]:
                print(f"  try: {a['candidate'][:90]!r} -> "
                      f"{'ACCEPT' if a['accepted'] else 'reject: ' + a['why']}")
            print(f"VIV> {rec['chosen'] if rec['accepted'] else '[no valid turn — silence]'}")
    print(f"\nreceipts -> {args.receipt}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
