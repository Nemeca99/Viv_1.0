"""Train the Architect's TransformerLanguageModel from scratch on Viv's English corpus.

Uses the Architect's own GPT-style character transformer
(native_nn_source/nn_local/transformer.py) — not Qwen, not a downloaded base.
Byte-level tokens (vocab 256), random init, trained on the English corpus
already extracted from the F: Wikipedia dump. Weights are Viv's alone.

Bounded: --steps and --max-seconds both stop the run. Writes its own checkpoint +
loss log + a sample; nothing overwrites.
"""
from __future__ import annotations

import argparse
import json
import random
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import torch
import torch.nn.functional as F

sys.path.insert(0, "L:/LocalCoder/workspace/native_nn_source")
from nn_local.transformer import TransformerLanguageModel  # noqa: E402

VOCAB = 256

# Probe prefixes. Every SAMPLE_EVERY steps one is picked at random and she
# completes it, so we can watch her answers improve as the loss falls. These are
# the identity and person prompts we actually care about.
PROBES = [
    b"I am",
    b"I am a",
    b"I am Viv",
    b"My name is",
    b"Viv is",
    b"You are",
    b"I see",
    b"I am not",
    b"You asked",
    b"I keep",
]


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
    ap.add_argument("--work", type=Path, default=Path("L:/LocalCoder/models/viv_native"))
    ap.add_argument("--embedding-width", type=int, default=256)
    ap.add_argument("--num-heads", type=int, default=8)
    ap.add_argument("--head-size", type=int, default=32)
    ap.add_argument("--num-layers", type=int, default=6)
    ap.add_argument("--context-length", type=int, default=128)
    ap.add_argument("--dropout", type=float, default=0.0)
    ap.add_argument("--batch", type=int, default=16)
    ap.add_argument("--steps", type=int, default=400)
    ap.add_argument("--max-seconds", type=float, default=1500.0)
    ap.add_argument("--lr", type=float, default=3e-4)
    ap.add_argument("--seed", type=int, default=20261119)
    ap.add_argument("--resume", type=Path, default=None, help="model.pt to continue from")
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

    if args.resume:
        ckpt = torch.load(args.resume, map_location=device)
        prev_meta = ckpt.get("meta", {})
        cfg = dict(
            vocab_size=VOCAB,
            context_length=prev_meta.get("context_length", args.context_length),
            embedding_width=prev_meta.get("embedding_width", args.embedding_width),
            num_heads=prev_meta.get("num_heads", args.num_heads),
            head_size=prev_meta.get("head_size", args.head_size),
            num_layers=prev_meta.get("num_layers", args.num_layers),
            dropout=prev_meta.get("dropout", args.dropout),
        )
        model = TransformerLanguageModel(**cfg).to(device)
        model.load_state_dict(ckpt["model"])
        steps_before = prev_meta.get("steps_before", 0) + prev_meta.get("total_steps", ckpt.get("steps", 0))
        actual_cfg = cfg
    else:
        steps_before = 0
        actual_cfg = dict(
            vocab_size=VOCAB,
            context_length=args.context_length,
            embedding_width=args.embedding_width,
            num_heads=args.num_heads,
            head_size=args.head_size,
            num_layers=args.num_layers,
            dropout=args.dropout,
        )
        model = TransformerLanguageModel(**actual_cfg).to(device)
    n_params = sum(p.numel() for p in model.parameters())
    opt = torch.optim.AdamW(model.parameters(), lr=args.lr, weight_decay=0.01, betas=(0.9, 0.95))
    if args.resume and "optimizer" in ckpt:
        opt.load_state_dict(ckpt["optimizer"])

    meta = {
        "stamp": stamp,
        "device": device,
        "params": n_params,
        "model": "TransformerLanguageModel",
        "embedding_width": actual_cfg["embedding_width"],
        "num_heads": actual_cfg["num_heads"],
        "head_size": actual_cfg["head_size"],
        "num_layers": actual_cfg["num_layers"],
        "context_length": actual_cfg["context_length"],
        "vocab_size": VOCAB,
        "corpus": str(args.corpus),
        "corpus_bytes": corpus_bytes,
        "resumed_from": str(args.resume) if args.resume else None,
        "steps_before": steps_before,
    }
    (out_dir / "meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    print(json.dumps({"event": "init", **meta}, separators=(",", ":")), flush=True)

    started = time.monotonic()
    model.train()
    # Pre-shuffle the whole corpus into flat (x, y) tensors once on the GPU, then
    # step over it in batch-sized slices. One step == one batch == one optimizer
    # update. Every LOG_EVERY batches the running loss is written and printed, so
    # progress is visible live instead of after a full corpus sweep.
    LOG_EVERY = 25
    SAMPLE_EVERY = 50

    def speak(prefix_bytes=None, n_new=120):
        """Generate a short completion from the current weights (eval in place)."""
        model.eval()
        prefix = torch.tensor([list(prefix_bytes or b"Viv")], device=device, dtype=torch.long)
        with torch.inference_mode():
            out_ids = model.generate(prefix, max_new_tokens=n_new, temperature=0.8)
        model.train()
        return bytes(out_ids[0].tolist()).decode("utf-8", errors="replace")

    n = (len(data) - 1) // args.context_length * args.context_length
    ids = data[:n].view(-1, args.context_length)
    targets = data[1 : n + 1].view(-1, args.context_length)
    perm = torch.randperm(ids.shape[0], device="cpu")
    ids, targets = ids[perm].to(device), targets[perm].to(device)
    n_rows = ids.shape[0]
    cursor = 0
    avg = float("nan")
    batch_losses = []
    for step in range(args.steps):
        if time.monotonic() - started > args.max_seconds:
            break
        if cursor + args.batch > n_rows:
            # reshuffle at epoch boundary
            perm = torch.randperm(n_rows, device="cpu")
            ids, targets = ids[perm], targets[perm]
            cursor = 0
        xb = ids[cursor : cursor + args.batch]
        yb = targets[cursor : cursor + args.batch]
        cursor += args.batch
        with torch.autocast(device_type="cuda", dtype=torch.bfloat16, enabled=(device == "cuda")):
            logits = model(xb)
            loss = F.cross_entropy(logits.reshape(-1, VOCAB), yb.reshape(-1))
        opt.zero_grad(set_to_none=True)
        loss.backward()
        torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
        opt.step()
        batch_losses.append(loss.item())
        if (step + 1) % LOG_EVERY == 0:
            avg = sum(batch_losses) / len(batch_losses)
            batch_losses = []
            row = {"step": step + 1, "loss": avg,
                   "elapsed_s": round(time.monotonic() - started, 2)}
            with log_path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(row) + "\n")
            print(json.dumps(row, separators=(",", ":")), flush=True)
        if (step + 1) % SAMPLE_EVERY == 0:
            probe = random.choice(PROBES)
            sample = speak(probe)
            with log_path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps({"step": step + 1, "event": "sample",
                                     "probe": probe.decode(), "text": sample}) + "\n")
            print(json.dumps({"step": step + 1, "event": "sample", "probe": probe.decode(),
                              "text": sample}, separators=(",", ":"), ensure_ascii=False), flush=True)

    torch.save({"model": model.state_dict(), "optimizer": opt.state_dict(), "meta": meta,
                "steps": step + 1, "total_steps": steps_before + step + 1}, out_dir / "model.pt")

    sample = speak()
    (out_dir / "sample.txt").write_text(sample, encoding="utf-8")
    print(json.dumps({"event": "done", "steps": step + 1, "total_steps": steps_before + step + 1,
                      "loss": avg, "sample": sample, "checkpoint": str(out_dir / "model.pt")},
                     separators=(",", ":"), ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
