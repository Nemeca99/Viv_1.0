"""
Viv English Core VTM Compiler (Sovereign Dialogue Cartridge)
============================================================
Architect: Travis (Nox Forge / AIOS V2)
Purpose:
  Compiles Viv's natural English lexicon, curriculum sentences, and
  2.6-million-character inner monologue into a native .vtm cartridge.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import sqlite3
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Set
from zoneinfo import ZoneInfo

import torch

AUTONOMY_DIR = Path(__file__).resolve().parent
if str(AUTONOMY_DIR) not in sys.path:
    sys.path.insert(0, str(AUTONOMY_DIR))

from vtm_spec import VTMContainer, VTMMetadata

CENTRAL_TZ = ZoneInfo("America/Chicago")


def central_iso() -> str:
    return datetime.now(CENTRAL_TZ).isoformat()


def get_file_sha256(filepath: Path | str) -> str:
    h = hashlib.sha256()
    with open(filepath, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


class EnglishVTMCompiler:
    def __init__(
        self,
        lexicon_db: Path | str = AUTONOMY_DIR / "data" / "lexicon_ontology.db",
        monologue_md: Path | str = Path(r"E:\Viv_Sandbox\playground\monologue\viv_monologue.md"),
        vocab_size: int = 263,
        d_model: int = 256,
        n_layers: int = 6,
        n_heads: int = 8,
        max_seq_len: int = 512,
    ):
        self.lexicon_db = Path(lexicon_db)
        self.monologue_md = Path(monologue_md)
        self.vocab_size = vocab_size
        self.d_model = d_model
        self.n_layers = n_layers
        self.n_heads = n_heads
        self.max_seq_len = max_seq_len

    def compile(
        self,
        epoch: int = 140,
        output_dir: Path | str = Path(r"E:\Viv_Sandbox\cartridges"),
    ) -> Path:
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        out_filename = f"viv_core_english_epoch{epoch:04d}.vtm"
        out_path = output_dir / out_filename

        print(f"[*] Compiling Sovereign English VTM Cartridge: {out_filename}")
        
        # 1. Harvest English Sentences from Lexicon & Monologue
        counts = torch.zeros((self.vocab_size, self.vocab_size), dtype=torch.float32)
        valid_bytes: Set[int] = set()
        total_sentences = 0

        # Monologue harvest (Viv's actual voice)
        if self.monologue_md.exists():
            text = self.monologue_md.read_text(encoding="utf-8", errors="replace")
            lines = [l.strip() for l in text.splitlines() if len(l.strip()) > 15]
            print(f"    Harvesting {len(lines)} lines from Viv Monologue...")
            for line in lines:
                b = list(line.encode("utf-8"))
                for byte_val in b:
                    if byte_val < 256:
                        valid_bytes.add(byte_val)
                for i in range(len(b) - 1):
                    if b[i] < 256 and b[i+1] < 256:
                        counts[b[i], b[i+1]] += 2.0  # Weight her own voice 2x
                total_sentences += 1

        # Lexicon curriculum harvest
        if self.lexicon_db.exists():
            conn = sqlite3.connect(self.lexicon_db)
            cur = conn.cursor()
            cur.execute("SELECT target_sentence FROM emergent_curriculum_frames WHERE target_sentence IS NOT NULL LIMIT 40000")
            print("    Harvesting 40,000 sentences from emergent_curriculum_frames...")
            for row in cur.fetchall():
                sent = row[0]
                b = list(sent.encode("utf-8"))
                for byte_val in b:
                    if byte_val < 256:
                        valid_bytes.add(byte_val)
                for i in range(len(b) - 1):
                    if b[i] < 256 and b[i+1] < 256:
                        counts[b[i], b[i+1]] += 1.0
                total_sentences += 1
            conn.close()

        total_transitions = int(counts.sum().item())
        print(f"    Built English transition lattice: {total_transitions:,} transitions across {total_sentences:,} sentences")

        # 2. Positive Pointwise Mutual Information (PPMI) with Frequency Thresholding
        P_xy = counts / max(total_transitions, 1.0)
        P_x = P_xy.sum(dim=1, keepdim=True)
        P_y = (P_xy.sum(dim=0, keepdim=True) ** 0.75)
        P_y = P_y / P_y.sum()

        expected = P_x * P_y
        mask_observed = (counts > 5.0)
        PMI = torch.zeros_like(counts)
        PMI[mask_observed] = torch.clamp(torch.log(P_xy[mask_observed] / (expected[mask_observed] + 1e-9)), min=0.0)

        # 3. Truncated Spectral SVD Factorization -> Rank d_model
        print("    Computing Truncated Spectral SVD on English semantic manifold...")
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

        # Transformer Projection Blocks (Identity projection scaled for INT8 GEMM)
        eye_d = torch.eye(self.d_model, dtype=torch.float32)
        qkv_eye = torch.cat([eye_d, eye_d, eye_d], dim=0)
        qkv_int8 = (qkv_eye * 64).to(torch.int8)
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

        # Metadata
        lex_sha = get_file_sha256(self.lexicon_db) if self.lexicon_db.exists() else "0"*64
        metadata = VTMMetadata(
            domain_name="ENGLISH",
            epoch=epoch,
            created_iso=central_iso(),
            vocab_size=self.vocab_size,
            d_model=self.d_model,
            n_layers=self.n_layers,
            n_heads=self.n_heads,
            max_seq_len=self.max_seq_len,
            neuron_count=total_sentences,
            synapse_count=total_transitions,
            negative_boundary_count=len(control_chars),
            source_db_name=self.lexicon_db.name,
            source_db_sha256=lex_sha,
            extra={
                "monologue_lines": len(lines) if self.monologue_md.exists() else 0,
                "curriculum_sentences": 40000,
                "quantization": "INT8_SPECTRAL_SVD",
            },
        )

        final_sha256 = VTMContainer.pack(
            output_path=out_path,
            metadata=metadata,
            tensors=tensors,
        )

        size_mb = out_path.stat().st_size / (1024 * 1024)
        print(f"[+] Successfully Compiled English VTM Cartridge:")
        print(f"    Path: {out_path}")
        print(f"    Size: {size_mb:.2f} MB")
        print(f"    SHA-256 Seal: {final_sha256}")
        return out_path


if __name__ == "__main__":
    compiler = EnglishVTMCompiler()
    cart_path = compiler.compile(epoch=140)
    info = VTMContainer.inspect(cart_path)
    print("\n[+] Verification Inspection:")
    print(f"    Domain: {info['domain']} | Epoch: {info['epoch']}")
    print(f"    Transitions: {info['synapse_count']:,} | Tensors: {info['tensor_count']}")
