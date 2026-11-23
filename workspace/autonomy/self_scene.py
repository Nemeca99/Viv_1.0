"""Viv authors her own scenes (self-generation, the method actor).

Instead of injected scenes, she conjures her own situation and acts it out.
Each authored scene is graded by the deterministic body (grade_dreams.grade):
clean scenes are kept for the next sleep, violations are flagged.
"""
import argparse
import sys
from pathlib import Path

import torch

sys.path.insert(0, "L:/LocalCoder/workspace/native_nn_source")
from nn_local.transformer import TransformerLanguageModel  # noqa: E402
from tokenizers import Tokenizer  # noqa: E402
from grade_dreams import grade  # noqa: E402

BPE_PATH = "L:/LocalCoder/models/viv_bpe_tokenizer.json"
SCENE_SEEDS = ["The scene is:", "Viv imagines:", "In her mind, she sees:", "She dreams a scene:"]


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
    ap.add_argument("--count", type=int, default=20)
    ap.add_argument("--temperature", type=float, default=0.9)
    ap.add_argument("--out", type=Path, default=Path("L:/LocalCoder/models/viv_self_scenes.txt"))
    args = ap.parse_args()

    tok = Tokenizer.from_file(BPE_PATH)
    vocab = tok.get_vocab_size()
    device = "cuda" if torch.cuda.is_available() else "cpu"
    model = load_model(args.checkpoint, vocab, device)

    clean = []
    flagged = 0
    for i in range(args.count):
        seed = SCENE_SEEDS[i % len(SCENE_SEEDS)]
        prefix = torch.tensor([tok.encode(seed).ids], device=device, dtype=torch.long)
        with torch.inference_mode():
            out_ids = model.generate(prefix, max_new_tokens=120, temperature=args.temperature)
        text = tok.decode(out_ids[0].tolist(), skip_special_tokens=True).strip()
        after = text[len(seed):].strip() if text.startswith(seed) else text
        score, violations = grade(after)
        if score == 0 and after:
            clean.append(after)
        else:
            flagged += 1
            if flagged <= 10:
                print(f"[score={score}] {violations} :: {after[:70]}")

    args.out.write_text("\n\n".join(clean), encoding="utf-8")
    print(f"authored {args.count} scenes | clean {len(clean)} | flagged {flagged} -> {args.out}")
    for s in clean[:4]:
        print("  *", s[:80])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
