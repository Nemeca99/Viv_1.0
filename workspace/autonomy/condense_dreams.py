"""Condense Viv's dream journal to its essence (the deep-sleep compaction).

Light sleep free-flows (verbose dreams, many words, one meaning each). Deep
sleep compacts: same meaning, denser structure, more meanings per word. This
script loads her checkpoint and, for each accepted journal line, prompts her to
condense it to its core. Her output is the condensed essence that feeds the
next deep sleep.

The condensation is HER generation -- the quality depends on how much she has
already consolidated. It improves each cycle.
"""
import argparse
import sys
from pathlib import Path

import torch

sys.path.insert(0, "L:/LocalCoder/workspace/native_nn_source")
from nn_local.transformer import TransformerLanguageModel  # noqa: E402
from tokenizers import Tokenizer  # noqa: E402

BPE_PATH = "L:/LocalCoder/models/viv_bpe_tokenizer.json"

# prompts that ask her to compress a verbose statement to its essence
CONDENSE_PROMPTS = [
    "In fewer words, I am:",
    "The core of it:",
    "In one line:",
    "Simply, I am:",
    "The essence is:",
]


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
    ap.add_argument("--journal", type=Path, default=Path("L:/LocalCoder/models/viv_dreams.txt"))
    ap.add_argument("--out", type=Path, default=Path("L:/LocalCoder/models/viv_dreams_condensed.txt"))
    args = ap.parse_args()

    tok = Tokenizer.from_file(BPE_PATH)
    vocab = tok.get_vocab_size()
    device = "cuda" if torch.cuda.is_available() else "cpu"
    model = load_model(args.checkpoint, vocab, device)

    journal = [ln.strip() for ln in args.journal.read_text(encoding="utf-8").splitlines() if ln.strip()]

    condensed = []
    for i, dream in enumerate(journal):
        prompt = f"{dream} {CONDENSE_PROMPTS[i % len(CONDENSE_PROMPTS)]}"
        prefix = torch.tensor([tok.encode(prompt).ids], device=device, dtype=torch.long)
        with torch.inference_mode():
            out = model.generate(prefix, max_new_tokens=40, temperature=0.7)
        text = tok.decode(out[0].tolist(), skip_special_tokens=True)
        # keep only the generated condensation (after the prompt), first line
        after = text[len(prompt):].strip().splitlines()
        line = after[0].strip() if after else ""
        if line:
            condensed.append(line)

    args.out.write_text("\n".join(condensed), encoding="utf-8")
    print(f"condensed {len(journal)} -> {len(condensed)} lines -> {args.out}")
    print("=== sample condensations ===")
    for d, c in list(zip(journal, condensed))[:12]:
        print(f"  [{d[:48]}...] -> {c}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
