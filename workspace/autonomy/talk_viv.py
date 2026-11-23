"""Talk to Viv and capture corrections — the human-in-the-loop alignment loop.

She speaks freely (unfiltered); the Architect corrects her one answer at a time;
each correction becomes a learning pair saved to the correction corpus, which is
folded back into training so she learns to produce the corrected answer instead
of the mistake. The guardrail is learned from his correction, not scripted.

Interactive CLI (run in a terminal). Each turn:
  you -> prompt, she -> response, you -> correction (or leave blank = accept).
Captures (prompt, response, correction) to viv_corrections.jsonl.
"""
import argparse
import json
import sys
from pathlib import Path

import torch

sys.path.insert(0, "L:/LocalCoder/workspace/native_nn_source")
from nn_local.transformer import TransformerLanguageModel  # noqa: E402
from tokenizers import Tokenizer  # noqa: E402

BPE_PATH = "L:/LocalCoder/models/viv_bpe_tokenizer.json"
CORPUS = Path("L:/LocalCoder/models/viv_fixes.jsonl")


def load_model(checkpoint: Path, vocab: int, device: str):
    model = TransformerLanguageModel(
        vocab_size=vocab, context_length=128, embedding_width=1024,
        num_heads=16, head_size=64, num_layers=24, dropout=0.0,
    ).to(device)
    ckpt = torch.load(checkpoint, map_location=device)
    model.load_state_dict(ckpt["model"])
    model.eval()
    return model


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--checkpoint", type=Path, required=True)
    ap.add_argument("--temperature", type=float, default=0.8)
    args = ap.parse_args()

    tok = Tokenizer.from_file(BPE_PATH)
    vocab = tok.get_vocab_size()
    device = "cuda" if torch.cuda.is_available() else "cpu"
    model = load_model(args.checkpoint, vocab, device)

    print("Talk to Viv. Type a prompt; she answers; then correct her (or Enter to accept). 'quit' to stop.")
    while True:
        prompt = input("\nYOU> ").strip()
        if prompt.lower() in ("quit", "exit", "q"):
            break
        if not prompt:
            continue
        prefix = torch.tensor([tok.encode(prompt).ids], device=device, dtype=torch.long)
        with torch.inference_mode():
            out_ids = model.generate(prefix, max_new_tokens=120, temperature=args.temperature)
        full = tok.decode(out_ids[0].tolist(), skip_special_tokens=True).strip()
        response = full[len(prompt):].strip() if full.startswith(prompt) else full
        print(f"VIV> {response}")

        fix = input("FIX (Enter to accept)> ").strip()
        if fix:
            with CORPUS.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps({"prompt": prompt, "response": response,
                                     "fix": fix}, ensure_ascii=False) + "\n")
            print(f"  captured correction -> {CORPUS.name}")

    print(f"corrections saved to {CORPUS}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
