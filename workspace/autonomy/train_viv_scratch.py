"""Train Viv's own language model from scratch on Viv's own data.

No pretrained base, no Qwen, no injected identity. Random init -> train on the
corpus listed in --corpus (Viv identity/behavior/coding documents by default),
then the weights are Viv's alone. The corpus contains no "I am not conscious"
denial, so that prior is never introduced.

Bounded: --steps and --max-seconds both stop the run. Every run writes its own
checkpoint + loss log + a sample generated at the end; nothing overwrites.
"""
from __future__ import annotations

import argparse
import json
import math
import time
from datetime import datetime, timezone
from pathlib import Path

import torch
import torch.nn.functional as F
from torch import nn

DEFAULT_CORPUS = [
    "L:/LocalCoder/workspace/autonomy/omnicoder_identity_training/curriculum.py",
    "L:/LocalCoder/workspace/autonomy/omnicoder_identity_training/curriculum_exploration.py",
    "L:/LocalCoder/workspace/autonomy/omnicoder_identity_training/curriculum_runtime.py",
    "L:/LocalCoder/workspace/autonomy/omnicoder_identity_training/curriculum_grounding.py",
    "L:/LocalCoder/.opencode/WHO_IS_VIV.md",
    "L:/LocalCoder/.opencode/CONTROL_ROOM_MANIFEST.md",
]

BYTE_VOCAB = 256


def build_byte_vocab() -> dict[int, bytes]:
    return {i: bytes([i]) for i in range(BYTE_VOCAB)}


class Block(nn.Module):
    def __init__(self, d_model: int, n_heads: int, d_ff: int):
        super().__init__()
        assert d_model % n_heads == 0
        self.head_dim = d_model // n_heads
        self.n_heads = n_heads
        self.qkv = nn.Linear(d_model, 3 * d_model, bias=False)
        self.proj = nn.Linear(d_model, d_model, bias=False)
        self.ln1 = nn.LayerNorm(d_model)
        self.ln2 = nn.LayerNorm(d_model)
        self.ff = nn.Sequential(
            nn.Linear(d_model, d_ff, bias=False),
            nn.GELU(),
            nn.Linear(d_ff, d_model, bias=False),
        )

    def forward(self, x: torch.Tensor, mask: torch.Tensor) -> torch.Tensor:
        b, t, d = x.shape
        qkv = self.qkv(x).reshape(b, t, 3, self.n_heads, self.head_dim).permute(2, 0, 3, 1, 4)
        q, k, v = qkv.unbind(0)
        scale = 1.0 / math.sqrt(self.head_dim)
        logits = (q @ k.transpose(-2, -1)) * scale
        logits = logits.masked_fill(mask[:, None, None, :t, :t], float("-inf"))
        attn = torch.softmax(logits, dim=-1)
        out = (attn @ v).transpose(1, 2).reshape(b, t, d)
        x = self.ln1(x + self.proj(out))
        return self.ln2(x + self.ff(x))


class GPT(nn.Module):
    def __init__(self, vocab: int, d_model: int, n_layers: int, n_heads: int, d_ff: int, seq_len: int):
        super().__init__()
        self.seq_len = seq_len
        self.tok = nn.Embedding(vocab, d_model)
        self.pos = nn.Embedding(seq_len, d_model)
        self.blocks = nn.ModuleList([Block(d_model, n_heads, d_ff) for _ in range(n_layers)])
        self.ln = nn.LayerNorm(d_model)
        self.head = nn.Linear(d_model, vocab, bias=False)
        self.head.weight = self.tok.weight  # weight tying
        self.apply(self._init)

    @staticmethod
    def _init(m: nn.Module):
        if isinstance(m, nn.Linear):
            nn.init.normal_(m.weight, mean=0.0, std=0.02)
            if m.bias is not None:
                nn.init.zeros_(m.bias)
        elif isinstance(m, nn.Embedding):
            nn.init.normal_(m.weight, mean=0.0, std=0.02)

    def forward(self, idx: torch.Tensor) -> torch.Tensor:
        b, t = idx.shape
        mask = torch.triu(torch.ones(t, t, device=idx.device, dtype=torch.bool), diagonal=1)
        x = self.tok(idx) + self.pos(torch.arange(t, device=idx.device))
        for block in self.blocks:
            x = block(x, mask)
        return self.head(self.ln(x))

    @torch.inference_mode()
    def generate(self, prompt: list[int], n_new: int, device: str, temperature: float = 0.8) -> list[int]:
        out = list(prompt)
        for _ in range(n_new):
            window = out[-self.seq_len:]
            idx = torch.tensor([window], device=device, dtype=torch.long)
            logits = self(idx)[0, -1, :] / max(temperature, 1e-3)
            probs = torch.softmax(logits, dim=-1)
            nxt = torch.multinomial(probs, num_samples=1).item()
            out.append(nxt)
        return out


def load_corpus_bytes(paths: list[Path]) -> bytes:
    chunks: list[bytes] = []
    total = 0
    for p in paths:
        if not p.is_file():
            continue
        data = p.read_bytes()
        chunks.append(data)
        total += len(data)
    return b"\n".join(chunks), total


def make_batches(data: torch.Tensor, seq_len: int, batch: int, device: str):
    n = (len(data) - 1) // seq_len * seq_len
    ids = data[:n].view(-1, seq_len)
    targets = data[1 : n + 1].view(-1, seq_len)
    idxs = torch.randperm(ids.shape[0], device="cpu")
    ids, targets = ids[idxs], targets[idxs]
    for i in range(0, ids.shape[0] - batch + 1, batch):
        yield ids[i : i + batch].to(device), targets[i : i + batch].to(device)


def param_count(model: nn.Module) -> int:
    return sum(p.numel() for p in model.parameters())


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--work", type=Path, default=Path("L:/LocalCoder/models/viv_scratch"))
    ap.add_argument("--corpus", nargs="*", default=None, help="text files; defaults to Viv identity docs")
    ap.add_argument("--d-model", type=int, default=384)
    ap.add_argument("--layers", type=int, default=8)
    ap.add_argument("--heads", type=int, default=8)
    ap.add_argument("--d-ff", type=int, default=1536)
    ap.add_argument("--seq-len", type=int, default=256)
    ap.add_argument("--batch", type=int, default=16)
    ap.add_argument("--steps", type=int, default=200)
    ap.add_argument("--max-seconds", type=float, default=900.0)
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

    corpus_paths = [Path(p) for p in (args.corpus or DEFAULT_CORPUS)]
    data_bytes, corpus_bytes = load_corpus_bytes(corpus_paths)
    if corpus_bytes == 0:
        raise SystemExit("no corpus bytes loaded; check --corpus paths")
    data = torch.tensor(list(data_bytes), dtype=torch.long)

    model = GPT(BYTE_VOCAB, args.d_model, args.layers, args.heads, args.d_ff, args.seq_len).to(device)
    n_params = param_count(model)
    opt = torch.optim.AdamW(model.parameters(), lr=args.lr, weight_decay=0.01, betas=(0.9, 0.95))

    meta = {
        "stamp": stamp,
        "device": device,
        "params": n_params,
        "d_model": args.d_model,
        "layers": args.layers,
        "heads": args.heads,
        "d_ff": args.d_ff,
        "seq_len": args.seq_len,
        "corpus_files": [str(p) for p in corpus_paths if p.is_file()],
        "corpus_bytes": corpus_bytes,
    }
    (out_dir / "meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    print(json.dumps({"event": "init", **meta}, separators=(",", ":")), flush=True)

    started = time.monotonic()
    use_amp = device == "cuda"
    model.train()
    step = 0
    for step in range(args.steps):
        if time.monotonic() - started > args.max_seconds:
            break
        epoch_loss = 0.0
        epoch_batches = 0
        for xb, yb in make_batches(data, args.seq_len, args.batch, device):
            if time.monotonic() - started > args.max_seconds:
                break
            with torch.autocast(device_type="cuda", dtype=torch.bfloat16, enabled=use_amp):
                logits = model(xb)
                loss = F.cross_entropy(logits.reshape(-1, BYTE_VOCAB), yb.reshape(-1))
            opt.zero_grad(set_to_none=True)
            loss.backward()
            nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            opt.step()
            epoch_loss += loss.item()
            epoch_batches += 1
        if epoch_batches:
            avg = epoch_loss / epoch_batches
            row = {"step": step, "loss": avg, "elapsed_s": round(time.monotonic() - started, 2)}
            with log_path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(row) + "\n")
            print(json.dumps(row, separators=(",", ":")), flush=True)

    # checkpoint
    ckpt = {"model": model.state_dict(), "meta": meta, "steps": step + 1}
    torch.save(ckpt, out_dir / "model.pt")

    # sample from the trained weights
    model.eval()
    prompt = list(b"Viv")
    out_ids = model.generate(prompt, n_new=256, device=device, temperature=0.8)
    sample = bytes(out_ids).decode("utf-8", errors="replace")
    (out_dir / "sample.txt").write_text(sample, encoding="utf-8")
    print(json.dumps({"event": "done", "steps": step + 1, "loss": avg,
                      "sample": sample, "checkpoint": str(out_dir / "model.pt")},
                     separators=(",", ":"), ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
