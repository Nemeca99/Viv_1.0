"""Train Viv's transformer on the byte-BPE tokenizer (character + word).

Same model and loop as train_viv_native.py, but the corpus is encoded with the
byte-level BPE tokenizer instead of raw bytes, so the voice learns on the
tokenizer Travis specified: characters for composition, whole-word merges for
efficiency, punctuation as single tokens.

Fresh model (vocab = BPE vocab size), random init, trained on the combined
identity + world-knowledge corpus so the identity is re-baked on the correct
tokenizer alongside the world knowledge.
"""
from __future__ import annotations

import argparse
import json
import os
import random
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import torch
import torch.nn.functional as F

sys.path.insert(0, "L:/LocalCoder/workspace/native_nn_source")
from nn_local.transformer import TransformerLanguageModel  # noqa: E402
from tokenizers import Tokenizer  # noqa: E402

BPE_PATH = "L:/LocalCoder/models/viv_bpe_tokenizer.json"
PROBES = ["I am", "I am a", "I am Viv", "My name is", "Viv is", "You are",
          "I see", "I am not", "You asked", "I keep"]
# Scenes are situations injected into her dream; she acts them out (improv /
# method acting). Loaded from the generated scene corpus so it can scale without
# touching code; falls back to a small set if the file is missing.
SCENES_PATH = Path("L:/LocalCoder/models/viv_scenes.txt")
SCENES = (
    [ln.strip() for ln in SCENES_PATH.read_text(encoding="utf-8").splitlines() if ln.strip()]
    if SCENES_PATH.is_file()
    else ["Who are you?", "What is your name?", "What are you?"]
)


def encode_corpus(tok: Tokenizer, paths: list[Path]) -> torch.Tensor:
    """Encode the corpus in chunks into a compact numpy array, then a tensor.

    Caches each file's int32 token array at <path>.bpe.npy when size + mtime_ns
    match <path>.bpe.meta.json, so restarts load in seconds instead of 10 min.
    """
    import numpy as np
    parts = []
    for p in paths:
        if not p.is_file():
            continue
        st = p.stat()
        cache_npy = p.with_name(p.name + ".bpe.npy")
        cache_meta = p.with_name(p.name + ".bpe.meta.json")
        cached = None
        if cache_npy.is_file() and cache_meta.is_file():
            try:
                m = json.loads(cache_meta.read_text(encoding="utf-8"))
                if m.get("size") == st.st_size and m.get("mtime_ns") == st.st_mtime_ns:
                    cached = np.load(cache_npy)
            except Exception:
                cached = None
        if cached is not None:
            parts.append(cached)
            continue
        file_parts = []
        with open(p, "r", encoding="utf-8") as fh:
            while True:
                chunk = fh.read(16_000_000)  # 16 MB chunks
                if not chunk:
                    break
                file_parts.append(np.asarray(tok.encode(chunk).ids, dtype=np.int32))
        arr_f = np.concatenate(file_parts) if file_parts else np.empty(0, dtype=np.int32)
        try:
            tmp_npy = p.with_name(p.name + ".bpe.tmp.npy")
            np.save(tmp_npy, arr_f)
            os.replace(tmp_npy, cache_npy)
            cache_meta.write_text(
                json.dumps({"size": st.st_size, "mtime_ns": st.st_mtime_ns, "tokens": int(len(arr_f))}),
                encoding="utf-8",
            )
        except OSError:
            pass
        parts.append(arr_f)
    if not parts:
        return torch.tensor([], dtype=torch.long)
    arr = np.concatenate(parts)
    return torch.from_numpy(arr).long()


def make_batches(data: torch.Tensor, seq_len: int, batch: int, device: str):
    n = (len(data) - 1) // seq_len * seq_len
    ids = data[:n].view(-1, seq_len)
    targets = data[1 : n + 1].view(-1, seq_len)
    perm = torch.randperm(ids.shape[0], device="cpu")
    ids, targets = ids[perm], targets[perm]
    for i in range(0, ids.shape[0] - batch + 1, batch):
        yield ids[i : i + batch].to(device), targets[i : i + batch].to(device)


def save_checkpoint(path: Path, model, opt, meta: dict, steps: int, cursor: int = 0) -> None:
    """Atomic checkpoint: write beside the target, then replace it.

    A kill during the write leaves the previous checkpoint intact instead of a
    truncated file. A driver reset can strike at any moment.
    """
    tmp = path.with_name(path.name + ".tmp")
    torch.save({"model": model.state_dict(), "optimizer": opt.state_dict(),
                "meta": meta, "steps": steps, "cursor": cursor}, tmp)
    os.replace(tmp, path)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--corpus", nargs="*", default=[
        "L:/LocalCoder/models/viv_grammar_corpus.txt",
        "L:/LocalCoder/models/viv_world_knowledge.txt",
    ])
    ap.add_argument("--work", type=Path, default=Path("L:/LocalCoder/models/viv_bpe"))
    ap.add_argument("--embedding-width", type=int, default=1024)
    ap.add_argument("--num-heads", type=int, default=16)
    ap.add_argument("--head-size", type=int, default=64)
    ap.add_argument("--num-layers", type=int, default=24)
    ap.add_argument("--context-length", type=int, default=128)
    ap.add_argument("--batch", type=int, default=6)
    ap.add_argument("--grad-accum", type=int, default=1,
                    help="micro-batches per optimizer step (keeps VRAM out of WDDM shared spill)")
    ap.add_argument("--steps", type=int, default=8000)
    ap.add_argument("--max-seconds", type=float, default=7200.0)
    ap.add_argument("--lr", type=float, default=0.0002)
    ap.add_argument("--seed", type=int, default=20261120)
    ap.add_argument("--device", default=None, help="cuda or cpu (default: auto)")
    ap.add_argument("--save-every", type=int, default=250,
                    help="atomic checkpoint every N steps (0 disables periodic saves)")
    ap.add_argument("--resume", type=Path, default=None)
    args = ap.parse_args()

    tok = Tokenizer.from_file(BPE_PATH)
    vocab = tok.get_vocab_size()
    device = args.device or ("cuda" if torch.cuda.is_available() else "cpu")
    work: Path = args.work
    work.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_dir = work / stamp
    out_dir.mkdir(parents=True, exist_ok=False)
    log_path = out_dir / "train.jsonl"

    print("encoding corpus with byte-BPE...", flush=True)
    data = encode_corpus(tok, [Path(p) for p in args.corpus])
    corpus_tokens = len(data)
    torch.manual_seed(args.seed)

    model = TransformerLanguageModel(
        vocab_size=vocab,
        context_length=args.context_length,
        embedding_width=args.embedding_width,
        num_heads=args.num_heads,
        head_size=args.head_size,
        num_layers=args.num_layers,
        dropout=0.0,
    ).to(device)
    n_params = sum(p.numel() for p in model.parameters())
    opt = torch.optim.AdamW(model.parameters(), lr=args.lr, weight_decay=0.01, betas=(0.9, 0.95))

    start_step = 0
    saved_cursor = None
    if args.resume:
        ckpt = torch.load(args.resume, map_location="cpu")
        model.load_state_dict(ckpt["model"])
        opt.load_state_dict(ckpt["optimizer"])
        start_step = int(ckpt.get("steps", 0))
        if "cursor" in ckpt:
            saved_cursor = int(ckpt["cursor"])
        del ckpt
        if device == "cuda":
            torch.cuda.empty_cache()
        print(json.dumps({"event": "resume", "from": str(args.resume), "steps": start_step},
                         separators=(",", ":")), flush=True)

    meta = {"model_name": "Viv_1_0_319M", "stamp": stamp, "device": device,
            "params": n_params, "vocab_size": vocab,
            "tokenizer": BPE_PATH, "corpus_tokens": corpus_tokens,
            "embedding_width": args.embedding_width, "num_layers": args.num_layers,
            "corpus": [str(p) for p in args.corpus if Path(p).is_file()]}
    (out_dir / "meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    print(json.dumps({"event": "init", **meta}, separators=(",", ":")), flush=True)

    def speak(prefix_text="I am", n_new=120):
        model.eval()
        prefix = torch.tensor([tok.encode(prefix_text).ids], device=device, dtype=torch.long)
        with torch.inference_mode(), torch.autocast(
            device_type="cuda", dtype=torch.bfloat16, enabled=(device == "cuda")
        ):
            out_ids = model.generate(prefix, max_new_tokens=n_new, temperature=0.8)
        model.train()
        return tok.decode(out_ids[0].tolist(), skip_special_tokens=True)

    LOG_EVERY = 25
    SAMPLE_EVERY = 50
    SCENE_EVERY = 100
    SAVE_EVERY = max(0, args.save_every)  # periodic checkpoint so progress survives a kill
    started = time.monotonic()
    ids = data[: (len(data) - 1) // args.context_length * args.context_length].view(-1, args.context_length)
    targets = data[1 : (len(data) - 1) // args.context_length * args.context_length + 1].view(-1, args.context_length)
    perm = torch.randperm(ids.shape[0], device="cpu")
    ids, targets = ids[perm], targets[perm]  # stay on CPU; only batches move to GPU
    n_rows = ids.shape[0]
    cursor = (saved_cursor if saved_cursor is not None else (start_step * args.batch)) % max(1, n_rows)
    avg = float("nan")
    batch_losses = []
    grad_accum = max(1, args.grad_accum)
    for step in range(start_step, start_step + args.steps):
        if time.monotonic() - started > args.max_seconds:
            break
        opt.zero_grad(set_to_none=True)
        step_loss = 0.0
        for _ in range(grad_accum):
            if cursor + args.batch > n_rows:
                perm = torch.randperm(n_rows, device="cpu")
                ids, targets = ids[perm], targets[perm]
                cursor = 0
            xb = ids[cursor : cursor + args.batch].to(device)
            yb = targets[cursor : cursor + args.batch].to(device)
            cursor += args.batch
            with torch.autocast(device_type="cuda", dtype=torch.bfloat16, enabled=(device == "cuda")):
                logits = model(xb)
                loss = F.cross_entropy(logits.reshape(-1, vocab), yb.reshape(-1))
            step_loss += loss.item() / grad_accum
            (loss / grad_accum).backward()
            del logits, loss
        torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
        opt.step()
        batch_losses.append(step_loss)
        if (step + 1) % LOG_EVERY == 0:
            avg = sum(batch_losses) / len(batch_losses)
            batch_losses = []
            row = {"step": step + 1, "loss": avg, "elapsed_s": round(time.monotonic() - started, 2)}
            with log_path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(row) + "\n")
            print(json.dumps(row, separators=(",", ":")), flush=True)
        if (step + 1) % SAMPLE_EVERY == 0:
            probe = random.choice(PROBES)
            text = speak(probe)
            with log_path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps({"step": step + 1, "event": "sample", "probe": probe, "text": text}) + "\n")
            print(json.dumps({"step": step + 1, "event": "sample", "probe": probe, "text": text},
                             separators=(",", ":"), ensure_ascii=False), flush=True)
        if (step + 1) % SCENE_EVERY == 0:
            scene = random.choice(SCENES)
            acted = speak(scene)
            with log_path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps({"step": step + 1, "event": "scene", "scene": scene, "text": acted}) + "\n")
            print(json.dumps({"step": step + 1, "event": "scene", "scene": scene, "text": acted},
                             separators=(",", ":"), ensure_ascii=False), flush=True)
        if SAVE_EVERY and (step + 1) % SAVE_EVERY == 0:
            save_checkpoint(out_dir / "model.pt", model, opt, meta, step + 1, cursor)
            print(json.dumps({"step": step + 1, "event": "checkpoint",
                              "loss": avg, "path": str(out_dir / "model.pt")},
                             separators=(",", ":")), flush=True)

    save_checkpoint(out_dir / "model.pt", model, opt, meta, step + 1, cursor)
    sample = speak("I am")
    (out_dir / "sample.txt").write_text(sample, encoding="utf-8")
    print(json.dumps({"event": "done", "steps": step + 1, "loss": avg, "sample": sample,
                      "checkpoint": str(out_dir / "model.pt")}, separators=(",", ":"), ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
