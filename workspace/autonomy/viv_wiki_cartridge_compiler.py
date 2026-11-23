"""
Viv Wikipedia Domain Cartridge Compiler
=======================================
Architect: Travis (Nox Forge / AIOS V2)
Purpose:
  Compiles domain-isolated Wikipedia SQLite databases (e.g. wiki_physics.sqlite3,
  wiki_comp_sci.sqlite3) into native, modular .vtm cartridges for GPU associative inference.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import sqlite3
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Set
from zoneinfo import ZoneInfo

import torch

AUTONOMY_DIR = Path(__file__).resolve().parent
if str(AUTONOMY_DIR) not in sys.path:
    sys.path.insert(0, str(AUTONOMY_DIR))

from vtm_spec import VTMContainer, VTMMetadata

CENTRAL_TZ = ZoneInfo("America/Chicago")
DOMAIN_DB_DIR = Path(r"F:\AI_Datasets\domain_dbs")
OUTPUT_CARTRIDGE_DIR = Path(r"E:\Viv_Sandbox\cartridges\wiki")
OUTPUT_CARTRIDGE_DIR.mkdir(parents=True, exist_ok=True)


def central_iso() -> str:
    return datetime.now(CENTRAL_TZ).isoformat()


def get_file_sha256(filepath: Path | str) -> str:
    h = hashlib.sha256()
    with open(filepath, "rb") as f:
        while chunk := f.read(1048576):
            h.update(chunk)
    return h.hexdigest()


class WikiCartridgeCompiler:
    def __init__(
        self,
        domain: str = "physics",
        vocab_size: int = 263,
        d_model: int = 256,
        n_layers: int = 6,
        n_heads: int = 8,
        max_seq_len: int = 512,
    ):
        self.domain = domain.lower()
        self.db_path = DOMAIN_DB_DIR / f"wiki_{self.domain}.sqlite3"
        self.vocab_size = vocab_size
        self.d_model = d_model
        self.n_layers = n_layers
        self.n_heads = n_heads
        self.max_seq_len = max_seq_len

    def compile(self, epoch: int = 140) -> Path:
        if not self.db_path.exists():
            raise FileNotFoundError(f"Domain database not found: {self.db_path}")

        out_filename = f"wiki_{self.domain}_epoch{epoch:04d}.vtm"
        out_path = OUTPUT_CARTRIDGE_DIR / out_filename

        print(f"[*] Compiling Domain Cartridge: {out_filename}")
        print(f"    Source Database: {self.db_path}")

        # Harvest summaries
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute("SELECT title, summary FROM articles WHERE length(summary) > 30")
        rows = cur.fetchall()
        conn.close()

        print(f"    Loaded {len(rows):,} articles from domain database.")

        import numpy as np
        counts_np = np.zeros((self.vocab_size, self.vocab_size), dtype=np.float32)
        valid_bytes: Set[int] = set()

        for title, summary in rows:
            text = f"{title}: {summary}\n"
            raw_b = text.encode("utf-8", errors="replace")
            arr = np.frombuffer(raw_b, dtype=np.uint8)
            if len(arr) > 1:
                np.add.at(counts_np, (arr[:-1], arr[1:]), 1)
            valid_bytes.update(arr.tolist())

        counts = torch.from_numpy(counts_np)

        total_transitions = int(counts.sum().item())
        print(f"    Built {self.domain.upper()} transition graph: {total_transitions:,} transitions across {len(valid_bytes)} valid bytes")

        # PPMI
        P_xy = counts / max(total_transitions, 1.0)
        P_x = P_xy.sum(dim=1, keepdim=True)
        P_y = (P_xy.sum(dim=0, keepdim=True) ** 0.75)
        P_y = P_y / P_y.sum()

        expected = P_x * P_y
        mask_observed = (counts > 2.0)
        PMI = torch.zeros_like(counts)
        PMI[mask_observed] = torch.clamp(torch.log(P_xy[mask_observed] / (expected[mask_observed] + 1e-9)), min=0.0)

        # Truncated Spectral SVD
        print("    Computing Truncated Spectral SVD on domain manifold...")
        U, S, V = torch.svd(PMI)
        rank = min(self.d_model, S.shape[0])
        W_emb_float = U[:, :rank] * torch.sqrt(S[:rank])
        if rank < self.d_model:
            pad_cols = torch.zeros((self.vocab_size, self.d_model - rank), dtype=torch.float32)
            W_emb_float = torch.cat([W_emb_float, pad_cols], dim=1)

        scale = 127.0 / (W_emb_float.abs().max() + 1e-6)
        tok_emb = (W_emb_float * scale).round().clamp(-127, 127).to(torch.int8)

        # Positional Embedding (INT8)
        pos_emb = torch.empty((self.max_seq_len, self.d_model), dtype=torch.int8)
        for p in range(self.max_seq_len):
            row = [int(127 * math.sin(p / (10000 ** (2 * (i // 2) / self.d_model)))) for i in range(self.d_model)]
            pos_emb[p] = torch.tensor(row, dtype=torch.int8)

        # Negative Mask (Control characters & unobserved tokens blocked)
        negative_mask = torch.zeros((self.vocab_size, self.vocab_size), dtype=torch.uint8)
        control_chars = list(range(0, 9)) + [11, 12] + list(range(14, 32)) + [127]
        for c in control_chars:
            negative_mask[:, c] = 1

        for t in range(256):
            if t not in valid_bytes:
                negative_mask[:, t] = 1

        tensors: Dict[str, torch.Tensor] = {
            "tok_emb.weight": tok_emb,
            "pos_emb.weight": pos_emb,
            "negative_mask": negative_mask,
        }

        # Identity Transformer Blocks
        eye_d = torch.eye(self.d_model, dtype=torch.float32)
        qkv_int8 = (torch.cat([eye_d, eye_d, eye_d], dim=0) * 64).to(torch.int8)
        out_int8 = (eye_d * 64).to(torch.int8)

        fc1_proj = torch.zeros((4 * self.d_model, self.d_model), dtype=torch.float32)
        for i in range(self.d_model):
            fc1_proj[i, i] = 1.0
        fc1_int8 = (fc1_proj * 64).to(torch.int8)
        fc2_int8 = (fc1_proj.t().contiguous() * 64).to(torch.int8)

        for l in range(self.n_layers):
            tensors[f"blocks.{l}.attn.qkv.weight"] = qkv_int8.clone()
            tensors[f"blocks.{l}.attn.out_proj.weight"] = out_int8.clone()
            tensors[f"blocks.{l}.mlp.fc1.weight"] = fc1_int8.clone()
            tensors[f"blocks.{l}.mlp.fc2.weight"] = fc2_int8.clone()

        src_sha = get_file_sha256(self.db_path)
        metadata = VTMMetadata(
            domain_name=f"WIKI_{self.domain.upper()}",
            epoch=epoch,
            created_iso=central_iso(),
            vocab_size=self.vocab_size,
            d_model=self.d_model,
            n_layers=self.n_layers,
            n_heads=self.n_heads,
            max_seq_len=self.max_seq_len,
            neuron_count=len(rows),
            synapse_count=total_transitions,
            negative_boundary_count=len(control_chars),
            source_db_name=self.db_path.name,
            source_db_sha256=src_sha,
            extra={
                "article_count": len(rows),
                "quantization": "INT8_SPECTRAL_SVD",
            },
        )

        final_sha = VTMContainer.pack(
            output_path=out_path,
            metadata=metadata,
            tensors=tensors,
        )

        size_mb = out_path.stat().st_size / (1024 * 1024)
        print(f"[+] Successfully Compiled Domain Cartridge: {out_path.name}")
        print(f"    Size: {size_mb:.2f} MB | SHA-256: {final_sha[:16]}...")
        return out_path


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--domain", default="physics")
    parser.add_argument("--epoch", type=int, default=140)
    args = parser.parse_args()

    compiler = WikiCartridgeCompiler(domain=args.domain)
    cart = compiler.compile(epoch=args.epoch)
    info = VTMContainer.inspect(cart)
    print("\n[+] Verification Inspection:")
    print(f"    Domain: {info['domain']} | Epoch: {info['epoch']}")
    print(f"    Articles: {info['neuron_count']:,} | Transitions: {info['synapse_count']:,}")
