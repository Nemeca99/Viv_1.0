"""Train the Architect's VivGPT2LanguageTrunk from scratch on Viv's own English corpus.

Uses the Architect's GPT-2-style transformer (L:/Standalone/Viv) — not Qwen, not
my own throwaway. Byte-level tokenization (vocab 256), so no external tokenizer
is needed. Random init -> train on the English corpus already extracted from the
F: Wikipedia dump. Weights are Viv's alone.

Bounded: --steps and --max-seconds both stop the run. Writes its own checkpoint +
loss log + a sample; nothing overwrites.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import torch
import torch.nn.functional as F

sys.path.insert(0, "L:/Standalone/Viv")
from training.language.viv_gpt2_language_trunk_v1 import (  # noqa: E402
    VivGPT2LanguageConfig,
    VivGPT2LanguageTrunk,
)

VOCAB = 256


def load_corpus_bytes(path: Path) -> tuple[torch.Tensor, int]:
    data = path.read_bytes()
    return torch.tensor(list(data), dtype=torch.long), len(data)


def make_batches(data: torch.Tensor, seq_len: int, batch: int, device: str):
    n = (len(data) - 1) // seq_len * seq_len
    ids = data[:n].view(-1, seq_len)
    targets = data[1 : n + 1].view(-1, seq_len)
    idxs = torch.randperm(ids.shape[0], device="cpu")
    ids, targets = ids[idxs], targets[idxs]
    for i in range(0, ids.shape[0] - batch + 1, batch):
        yield ids[i : i + batch].to(device), targets[i : i + batch].to(device)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--corpus", type=Path, default=Path("L:/LocalCoder/models/viv_scratch_corpus.txt"))
    ap.add_argument("--work", type=Path, default=Path("L:/LocalCoder/models/viv_trunk"))
    ap.add_argument("--width", type=int, default=512)
    ap.add_argument("--layers", type=int, default=8)
    ap.add_argument("--heads", type=int, default=8)
    ap.add_argument("--feed-forward", type=int, default=2048)
    ap.add_argument("--context-length", type=int, default=256)
    ap.add_argument("--batch", type=int, default=8)
    ap.add_argument("--steps", type=int, default=400)
    ap.add_argument("--max-seconds", type=float, default=1500.0)
    ap.add_argument("--lr", type=float, default=3e-4)
    ap.add_argument("--seed", type=int, default=20261119)
    args = ap.parse_args()

    torch.manual_seed(args.seed)
    device = "cuda" if torch.cuda.is_available() else "cpu"
    work: Path = args.work
    work.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_dir = work / stamp
    out_dir.mkdir(parents=True, exist_ok=False)
    log_path = out_dir / "train.jsonl"

    data, corpus_bytes = load_corpus_bytes(args.corpus)

    config = VivGPT2LanguageConfig(
        vocab_size=VOCAB,
        context_length=args.context_length,
        width=args.width,
        layers=args.layers,
        heads=args.heads,
        feed_forward=args.feed_forward,
        gradient_checkpointing=True,
    )
    model = VivGPT2LanguageTrunk(config).to(device)
    n_params = model.parameter_count
    opt = torch.optim.AdamW(model.parameters(), lr=args.lr, weight_decay=0.01, betas=(0.9, 0.95))

    meta = {
        "stamp": stamp,
        "device": device,
        "params": n_params,
        "architecture": model.contract()["architecture"],
        "width": args.width,
        "layers": args.layers,
        "heads": args.heads,
        "feed_forward": args.feed_forward,
        "context_length": args.context_length,
        "vocab_size": VOCAB,
        "corpus": str(args.corpus),
        "corpus_bytes": corpus_bytes,
    }
    (out_dir / "meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    print(json.dumps({"event": "init", **meta}, separators=(",", ":")), flush=True)

    started = time.monotonic()
    model.train()
    step = 0
    avg = float("nan")
    for step in range(args.steps):
        if time.monotonic() - started > args.max_seconds:
            break
        epoch_loss, epoch_batches = 0.0, 0
        for xb, yb in make_batches(data, args.context_length, args.batch, device):
            if time.monotonic() - started > args.max_seconds:
                break
            with torch.autocast(device_type="cuda", dtype=torch.bfloat16, enabled=(device == "cuda")):
                logits = model(xb)
                loss = F.cross_entropy(logits.reshape(-1, VOCAB), yb.reshape(-1))
            opt.zero_grad(set_to_none=True)
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            opt.step()
            epoch_loss += loss.item()
            epoch_batches += 1
        if epoch_batches:
            avg = epoch_loss / epoch_batches
            with log_path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps({"step": step, "loss": avg,
                                     "elapsed_s": round(time.monotonic() - started, 2)}) + "\n")
            print(json.dumps({"step": step, "loss": avg,
                              "elapsed_s": round(time.monotonic() - started, 2)}, separators=(",", ":")), flush=True)

    torch.save({"model": model.state_dict(), "config": config, "meta": meta, "steps": step + 1},
               out_dir / "model.pt")

    model.eval()
    prefix = torch.tensor([list(b"Viv")], device=device, dtype=torch.long)
    out_ids = model.generate_greedy(prefix, stop_id=0, max_new_tokens=200)
    sample = bytes(out_ids[0].tolist()).decode("utf-8", errors="replace")
    (out_dir / "sample.txt").write_text(sample, encoding="utf-8")
    print(json.dumps({"event": "done", "steps": step + 1, "loss": avg, "sample": sample,
                      "checkpoint": str(out_dir / "model.pt")}, separators=(",", ":"), ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
