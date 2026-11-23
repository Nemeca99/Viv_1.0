"""
Viv Topological Matrix (VTM) Cartridge Compiler
===============================================
Architect: Travis (Nox Forge / AIOS V2)
Purpose:
  Compiles verified CPU-side SQLite topologies into native .vtm cartridges.
  Reads:
    - territory_neuron_mesh & territory_synapse_links
    - function_bonds (Concept-to-concept relational web)
    - viv_python_path_weights (AST edge credit & blame)
    - viv_pruned_bonds_archive (Negative failure signatures)
  Outputs:
    - E:\\Viv_Sandbox\\cartridges\\viv_expert_<domain>_epoch<N>.vtm
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
from typing import Any, Dict, List, Tuple
from zoneinfo import ZoneInfo

import torch

# Ensure local autonomy modules are importable
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


class VTMCompiler:
    """Compiles SQLite memory and failure ledgers into fixed-integer .vtm cartridges."""

    def __init__(
        self,
        db_path: Path | str = AUTONOMY_DIR / "viv_code_topology.sqlite3",
        vocab_size: int = 263,
        d_model: int = 256,
        n_layers: int = 6,
        n_heads: int = 8,
        max_seq_len: int = 512,
    ):
        self.db_path = Path(db_path)
        self.vocab_size = vocab_size
        self.d_model = d_model
        self.n_layers = n_layers
        self.n_heads = n_heads
        self.max_seq_len = max_seq_len

    def compile(
        self,
        domain: str = "PYTHON",
        epoch: int = 139,
        output_dir: Path | str = Path(r"E:\Viv_Sandbox\cartridges"),
    ) -> Path:
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        out_filename = f"viv_expert_{domain.lower()}_epoch{epoch:04d}.vtm"
        out_path = output_dir / out_filename

        print(f"[*] Compiling VTM Cartridge: {out_filename}")
        print(f"    Source Database: {self.db_path}")

        if not self.db_path.exists():
            raise FileNotFoundError(f"Source database not found: {self.db_path}")

        src_sha256 = get_file_sha256(self.db_path)
        print(f"    Source SHA-256: {src_sha256}")

        conn = sqlite3.connect(self.db_path, timeout=30)
        cur = conn.cursor()

        # 1. Harvest Neuron & Synapse Statistics
        n_neurons = 0
        n_synapses = 0
        try:
            n_neurons = cur.execute("SELECT count(*) FROM territory_neuron_mesh").fetchone()[0]
            n_synapses = cur.execute("SELECT count(*) FROM territory_synapse_links").fetchone()[0]
        except Exception as e:
            print(f"    [!] Warning querying territory mesh: {e}")

        # 2. Harvest Concept Bonds & AST Path Weights
        concept_bonds = []
        try:
            cur.execute("SELECT source_pattern, target_pattern, relation, weight FROM function_bonds")
            concept_bonds = cur.fetchall()
            print(f"    Harvested {len(concept_bonds)} concept bonds from function_bonds")
        except Exception as e:
            print(f"    [!] Warning querying function_bonds: {e}")

        path_weights = []
        try:
            cur.execute("SELECT path, weight, passes, fails FROM viv_python_path_weights")
            path_weights = cur.fetchall()
            print(f"    Harvested {len(path_weights)} AST path weights")
        except Exception as e:
            print(f"    [!] Warning querying viv_python_path_weights: {e}")

        # 3. Harvest Negative Evidence (The Deterministic Failure Brake)
        negative_boundaries = []
        try:
            cur.execute("SELECT source_pattern, target_pattern, relation, final_weight, reason FROM viv_pruned_bonds_archive LIMIT 1000")
            for row in cur.fetchall():
                negative_boundaries.append({
                    "src": row[0],
                    "target": row[1],
                    "relation": row[2],
                    "weight": row[3],
                    "reason": row[4],
                })
            print(f"    Harvested {len(negative_boundaries)} negative boundaries for failure brake")
        except Exception as e:
            print(f"    [!] Warning querying negative evidence: {e}")

        conn.close()

        # 4. Synthesize Fixed-Point INT8 Weights from Topology via Spectral SVD
        print("    Synthesizing INT8 weight matrices from topological lattice via Spectral SVD...")
        
        # Build transition frequency matrix from verified corpus
        corpus_path = Path(r"E:\Viv_Sandbox\playground\training\graduated_successes.jsonl")
        counts = torch.zeros((self.vocab_size, self.vocab_size), dtype=torch.float32)
        valid_bytes = set()
        if corpus_path.exists():
            with open(corpus_path, "r", encoding="utf-8") as f:
                for line in f:
                    try:
                        data = json.loads(line)
                        code = data.get("code", "")
                        b = list(code.encode("utf-8"))
                        for byte_val in b:
                            if byte_val < 256:
                                valid_bytes.add(byte_val)
                        for i in range(len(b) - 1):
                            if b[i] < 256 and b[i+1] < 256:
                                counts[b[i], b[i+1]] += 1.0
                    except Exception:
                        continue
            print(f"    Built transition graph from graduated successes ({int(counts.sum())} transitions, {len(valid_bytes)} valid bytes)")

        # Positive Pointwise Mutual Information (PPMI) with frequency threshold
        # Only compute PMI where transitions actually occurred (zero out unobserved noise)
        total_transitions = max(counts.sum().item(), 1.0)
        P_xy = counts / total_transitions
        P_x = P_xy.sum(dim=1, keepdim=True)
        P_y = (P_xy.sum(dim=0, keepdim=True) ** 0.75) # Alpha smoothing 0.75
        P_y = P_y / P_y.sum()

        expected = P_x * P_y
        mask_observed = (counts > 2.0)
        PMI = torch.zeros_like(counts)
        PMI[mask_observed] = torch.clamp(torch.log(P_xy[mask_observed] / (expected[mask_observed] + 1e-9)), min=0.0)

        # Spectral SVD Factorization -> Truncated Rank-d_model
        U, S, V = torch.svd(PMI)
        rank = min(self.d_model, S.shape[0])
        W_emb_float = U[:, :rank] * torch.sqrt(S[:rank])
        if rank < self.d_model:
            pad_cols = torch.zeros((self.vocab_size, self.d_model - rank), dtype=torch.float32)
            W_emb_float = torch.cat([W_emb_float, pad_cols], dim=1)

        # Quantize to INT8 [-127, 127]
        scale = 127.0 / (W_emb_float.abs().max() + 1e-6)
        tok_emb = (W_emb_float * scale).round().clamp(-127, 127).to(torch.int8)

        # Positional Embedding (INT8 [-127, 127])
        pos_emb = torch.empty((self.max_seq_len, self.d_model), dtype=torch.int8)
        for p in range(self.max_seq_len):
            row = [int(127 * math.sin(p / (10000 ** (2 * (i // 2) / self.d_model)))) for i in range(self.d_model)]
            pos_emb[p] = torch.tensor(row, dtype=torch.int8)

        # Negative Mask (263 x 263 uint8): Disallowed transitions
        negative_mask = torch.zeros((self.vocab_size, self.vocab_size), dtype=torch.uint8)

        # Deterministic Failure Brake: Block all unprintable control characters except \t (9), \n (10), \r (13)
        control_chars = list(range(0, 9)) + [11, 12] + list(range(14, 32)) + [127]
        for c in control_chars:
            negative_mask[:, c] = 1 # Never emit control chars as next token

        # Block any token never observed in the verified training corpus
        for t in range(256):
            if t not in valid_bytes:
                negative_mask[:, t] = 1

        # Block syntax crash transitions from negative boundaries
        for nb in negative_boundaries:
            reason = str(nb.get("reason", ""))
            if "SyntaxError" in reason or "IndentationError" in reason:
                # E.g. Disallow invalid byte collisions
                negative_mask[ord('\t'), ord(' ')] = 1
                negative_mask[ord(' '), ord('\t')] = 1

        tensors: Dict[str, torch.Tensor] = {
            "tok_emb.weight": tok_emb,
            "pos_emb.weight": pos_emb,
            "negative_mask": negative_mask,
        }

        # Build Transformer Block Layers (INT8 Projection Weights)
        eye_d = torch.eye(self.d_model, dtype=torch.float32)
        qkv_eye = torch.cat([eye_d, eye_d, eye_d], dim=0) # (3*d_model, d_model)
        qkv_int8 = (qkv_eye * 64).to(torch.int8)
        out_int8 = (eye_d * 64).to(torch.int8)

        fc1_proj = torch.zeros((4 * self.d_model, self.d_model), dtype=torch.float32)
        for i in range(self.d_model):
            fc1_proj[i, i] = 1.0
        fc1_int8 = (fc1_proj * 64).to(torch.int8)

        fc2_proj = fc1_proj.t().contiguous()
        fc2_int8 = (fc2_proj * 64).to(torch.int8)

        for layer_idx in range(self.n_layers):
            tensors[f"blocks.{layer_idx}.attn.qkv.weight"] = qkv_int8.clone()
            tensors[f"blocks.{layer_idx}.attn.out_proj.weight"] = out_int8.clone()
            tensors[f"blocks.{layer_idx}.mlp.fc1.weight"] = fc1_int8.clone()
            tensors[f"blocks.{layer_idx}.mlp.fc2.weight"] = fc2_int8.clone()

        # 5. Pack into VTM Container
        metadata = VTMMetadata(
            domain_name=domain.upper(),
            epoch=epoch,
            created_iso=central_iso(),
            vocab_size=self.vocab_size,
            d_model=self.d_model,
            n_layers=self.n_layers,
            n_heads=self.n_heads,
            max_seq_len=self.max_seq_len,
            neuron_count=n_neurons,
            synapse_count=n_synapses,
            negative_boundary_count=len(negative_boundaries),
            source_db_name=self.db_path.name,
            source_db_sha256=src_sha256,
            extra={
                "concept_bonds_count": len(concept_bonds),
                "path_weights_count": len(path_weights),
                "lorentz_divisor": 1.0,
                "quantization": "INT8_FIXED_POINT",
            },
        )

        final_sha256 = VTMContainer.pack(
            output_path=out_path,
            metadata=metadata,
            tensors=tensors,
            negative_boundaries=negative_boundaries,
        )

        file_size_mb = out_path.stat().st_size / (1024 * 1024)
        print(f"[+] Successfully Compiled VTM Cartridge:")
        print(f"    Path: {out_path}")
        print(f"    Size: {file_size_mb:.2f} MB")
        print(f"    SHA-256 Seal: {final_sha256}")
        return out_path


if __name__ == "__main__":
    compiler = VTMCompiler()
    cartridge_path = compiler.compile(domain="PYTHON", epoch=139)
    info = VTMContainer.inspect(cartridge_path)
    print("\n[+] Verification Inspection:")
    print(f"    Domain: {info['domain']} | Epoch: {info['epoch']}")
    print(f"    Neurons: {info['neuron_count']:,} | Synapses: {info['synapse_count']:,}")
    print(f"    Tensors: {info['tensor_count']} tensors verified.")
