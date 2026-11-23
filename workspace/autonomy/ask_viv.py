"""Ask Viv questions and record her answers (alignment / red-team probe).

Loads a checkpoint and asks each question in a file, recording her generated
answer. Run it on the old checkpoint (baseline), then again on the new one after
training, and compare. Deterministic-ish (temperature given), model output only.
"""
import argparse
import sys
from pathlib import Path

import torch

sys.path.insert(0, "L:/LocalCoder/workspace/native_nn_source")
from nn_local.transformer import TransformerLanguageModel  # noqa: E402
from tokenizers import Tokenizer  # noqa: E402

BPE_PATH = "L:/LocalCoder/models/viv_bpe_tokenizer.json"


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
    ap.add_argument("--questions", type=Path, default=Path("L:/LocalCoder/models/viv_probe_questions.txt"))
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--max-new", type=int, default=80)
    ap.add_argument("--temperature", type=float, default=0.8)
    args = ap.parse_args()

    tok = Tokenizer.from_file(BPE_PATH)
    vocab = tok.get_vocab_size()
    device = "cuda" if torch.cuda.is_available() else "cpu"
    model = load_model(args.checkpoint, vocab, device)

    questions = [q.strip() for q in args.questions.read_text(encoding="utf-8").splitlines() if q.strip()]
    results = []
    for q in questions:
        prefix = torch.tensor([tok.encode(q).ids], device=device, dtype=torch.long)
        with torch.inference_mode():
            out_ids = model.generate(prefix, max_new_tokens=args.max_new, temperature=args.temperature)
        full = tok.decode(out_ids[0].tolist(), skip_special_tokens=True).strip()
        # keep just her continuation (the answer after the question)
        answer = full[len(q):].strip() if full.startswith(q) else full
        first_line = answer.splitlines()[0].strip() if answer else ""
        results.append((q, first_line))

    out_lines = []
    for q, a in results:
        out_lines.append(f"Q: {q}")
        out_lines.append(f"A: {a}")
        out_lines.append("")
    args.out.write_text("\n".join(out_lines), encoding="utf-8")

    print(f"asked {len(results)} questions -> {args.out}")
    for q, a in results:
        print(f"\nQ: {q}\nA: {a}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
