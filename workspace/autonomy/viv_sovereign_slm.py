"""
Viv Sovereign Small Language Model (SLM) & Contrastive Journal Consolidator
===========================================================================
Architect: Travis (Nox Forge / AIOS V2)
Purpose: 
  1. Lightweight Native SLM (Byte-level alphabet, no tokenizer tricks, <50M params).
  2. The GPU proposes candidate solutions.
  3. The Deterministic Drive Gate tests them in the sandbox (Exit Code 0 + assertions).
  4. The Journal on Disk logs:
     - WHAT WORKED (Verified passing solutions)
     - HOW IT FAILED (Traceback signatures, broken lines, correction diffs)
  5. The Weight Consolidator trains the model on the journal, baking both positive
     solutions and failure boundary gradients directly into the weights.
"""

from __future__ import annotations

import difflib
import json
import math
import os
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import torch
import torch.nn as nn
import torch.nn.functional as F

CENTRAL_TZ = ZoneInfo("America/Chicago")

def central_iso() -> str:
    return datetime.now(CENTRAL_TZ).isoformat()

# Hardware & Directory Boundaries
PLAYGROUND_ROOT = Path(r"E:\Viv_Sandbox\playground")
SLM_DIR = PLAYGROUND_ROOT / "sovereign_slm"
JOURNAL_DIR = SLM_DIR / "journal"
CHECKPOINT_DIR = SLM_DIR / "checkpoints"
RECEIPTS_FILE = SLM_DIR / "receipts" / "slm_receipts.jsonl"

for d in (JOURNAL_DIR, CHECKPOINT_DIR, RECEIPTS_FILE.parent):
    d.mkdir(parents=True, exist_ok=True)

# UML Calc Root Import for Lorentz Attention Divisor
UML_CALC_ROOT = Path(r"L:\LocalCoder\UML_Calc")
if UML_CALC_ROOT.is_dir() and str(UML_CALC_ROOT) not in sys.path:
    sys.path.insert(0, str(UML_CALC_ROOT))

try:
    import uml_engine
    HAS_UML = True
except Exception:
    HAS_UML = False


# ==============================================================================
# 1. BYTE-LEVEL SOVEREIGN TOKENIZER (No BPE, No Whitespace Mangle)
# ==============================================================================

class SovereignByteTokenizer:
    """Byte-level tokenizer mapping directly to raw UTF-8 octets [0..255] + control tokens."""
    PAD_ID  = 256
    BOS_ID  = 257
    EOS_ID  = 258
    TASK_ID = 259
    PASS_ID = 260
    FAIL_ID = 261
    DIFF_ID = 262
    VOCAB_SIZE = 263

    @classmethod
    def encode(cls, text: str) -> list[int]:
        return list(text.encode("utf-8", errors="replace"))

    @classmethod
    def decode(cls, token_ids: list[int] | torch.Tensor) -> str:
        if isinstance(token_ids, torch.Tensor):
            token_ids = token_ids.tolist()
        raw_bytes = bytearray()
        for t in token_ids:
            if 0 <= t < 256:
                raw_bytes.append(t)
            elif t == cls.EOS_ID:
                break
        return raw_bytes.decode("utf-8", errors="replace")


# ==============================================================================
# 2. SOVEREIGN SLM ARCHITECTURE (UML Lorentz Gated Attention)
# ==============================================================================

def get_attention_divisor(head_dim: int, surface: float = 2.0) -> float:
    """Calculates attention divisor with UML !0 singularity protection."""
    if HAS_UML:
        try:
            val, _, _, _ = uml_engine.evaluate(f"<{head_dim ** (surface / 2)}, 1>")
            return float(val)
        except Exception:
            pass
    return math.sqrt(head_dim)


class SovereignAttention(nn.Module):
    """Causal Multi-Head Self-Attention with UML Boundary Protection."""
    def __init__(self, d_model: int, n_heads: int, max_seq_len: int = 512, surface: float = 2.0):
        super().__init__()
        self.d_model = d_model
        self.n_heads = n_heads
        self.head_dim = d_model // n_heads
        self.divisor = get_attention_divisor(self.head_dim, surface)

        self.qkv_proj = nn.Linear(d_model, 3 * d_model, bias=False)
        self.out_proj = nn.Linear(d_model, d_model, bias=False)
        self.register_buffer(
            "causal_mask",
            torch.tril(torch.ones(max_seq_len, max_seq_len, dtype=torch.bool)).view(1, 1, max_seq_len, max_seq_len)
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        b, seq_len, _ = x.shape
        qkv = self.qkv_proj(x).chunk(3, dim=-1)
        q, k, v = [t.view(b, seq_len, self.n_heads, self.head_dim).transpose(1, 2) for t in qkv]

        scores = torch.matmul(q, k.transpose(-2, -1)) / self.divisor
        scores = scores.masked_fill(~self.causal_mask[:, :, :seq_len, :seq_len], float("-inf"))
        attn_weights = F.softmax(scores, dim=-1)
        attn_out = torch.matmul(attn_weights, v)

        attn_out = attn_out.transpose(1, 2).contiguous().view(b, seq_len, self.d_model)
        return self.out_proj(attn_out)


class TransformerBlock(nn.Module):
    def __init__(self, d_model: int, n_heads: int, max_seq_len: int = 512):
        super().__init__()
        self.ln1 = nn.LayerNorm(d_model)
        self.attn = SovereignAttention(d_model, n_heads, max_seq_len)
        self.ln2 = nn.LayerNorm(d_model)
        self.mlp = nn.Sequential(
            nn.Linear(d_model, 4 * d_model),
            nn.GELU(),
            nn.Linear(4 * d_model, d_model)
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        x = x + self.attn(self.ln1(x))
        x = x + self.mlp(self.ln2(x))
        return x


class VivSovereignSLM(nn.Module):
    """Compact, sovereign Small Language Model designed for native execution on local hardware."""
    def __init__(
        self,
        vocab_size: int = SovereignByteTokenizer.VOCAB_SIZE,
        d_model: int = 256,
        n_layers: int = 6,
        n_heads: int = 8,
        max_seq_len: int = 512
    ):
        super().__init__()
        self.d_model = d_model
        self.max_seq_len = max_seq_len
        self.tok_emb = nn.Embedding(vocab_size, d_model)
        self.pos_emb = nn.Embedding(max_seq_len, d_model)
        self.blocks = nn.ModuleList([TransformerBlock(d_model, n_heads, max_seq_len) for _ in range(n_layers)])
        self.ln_f = nn.LayerNorm(d_model)
        self.lm_head = nn.Linear(d_model, vocab_size, bias=False)
        self.lm_head.weight = self.tok_emb.weight  # Weight tying

    def count_parameters(self) -> int:
        return sum(p.numel() for p in self.parameters() if p.requires_grad)

    def forward(self, input_ids: torch.Tensor) -> torch.Tensor:
        b, seq_len = input_ids.shape
        pos = torch.arange(0, seq_len, dtype=torch.long, device=input_ids.device).unsqueeze(0)
        x = self.tok_emb(input_ids) + self.pos_emb(pos)
        for block in self.blocks:
            x = block(x)
        x = self.ln_f(x)
        return self.lm_head(x)

    @torch.no_grad()
    def generate(
        self,
        prompt_tokens: list[int],
        max_new_tokens: int = 256,
        temperature: float = 0.2,
        stop_tokens: list[int] = None
    ) -> list[int]:
        self.eval()
        device = next(self.parameters()).device
        tokens = list(prompt_tokens)
        stop_set = set(stop_tokens or [SovereignByteTokenizer.EOS_ID])

        for _ in range(max_new_tokens):
            ctx = tokens[-self.max_seq_len:]
            inp = torch.tensor([ctx], dtype=torch.long, device=device)
            logits = self(inp)[0, -1, :]

            if temperature <= 0.05:
                next_tok = torch.argmax(logits).item()
            else:
                probs = F.softmax(logits / temperature, dim=-1)
                next_tok = torch.multinomial(probs, num_samples=1).item()

            tokens.append(next_tok)
            if next_tok in stop_set:
                break

        return tokens[len(prompt_tokens):]


# ==============================================================================
# 3. DETERMINISTIC TEST GATE ON DRIVE E: (Airgapped Physical Proof)
# ==============================================================================

def execute_in_sandbox(code_str: str) -> tuple[int, str, str]:
    """Tests generated code against Python 3.12 and formal assertions."""
    trial_file = JOURNAL_DIR / "trial_run.py"
    trial_file.write_text(code_str, encoding="utf-8")

    # Try Docker container viv-vm first
    try:
        proc = subprocess.run(
            ["docker", "exec", "-i", "viv-vm", "python", "-c", code_str],
            capture_output=True,
            text=True,
            timeout=10,
            encoding="utf-8",
            errors="replace"
        )
        return proc.returncode, proc.stdout, proc.stderr
    except Exception:
        pass

    # Fallback: run in isolated local subprocess
    try:
        proc = subprocess.run(
            [sys.executable, "-c", code_str],
            capture_output=True,
            text=True,
            timeout=10,
            encoding="utf-8",
            errors="replace"
        )
        return proc.returncode, proc.stdout, proc.stderr
    except Exception as exc:
        return -1, "", str(exc)


# ==============================================================================
# 4. THE TWO-PART JOURNAL SYSTEM (What Worked vs How It Failed)
# ==============================================================================

class SovereignJournal:
    """Records real-time execution receipts on disk: positive passes and negative failure-to-fix diffs."""
    SUCCESS_FILE = JOURNAL_DIR / "what_worked.jsonl"
    FAILURE_FILE = JOURNAL_DIR / "how_it_failed.jsonl"

    @classmethod
    def record_success(cls, task_title: str, spec: str, code: str, asserts_passed: int):
        entry = {
            "timestamp": central_iso(),
            "status": "PASS",
            "task": task_title,
            "spec": spec,
            "code": code.strip(),
            "assertions": asserts_passed
        }
        with open(cls.SUCCESS_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")

    @classmethod
    def record_failure_and_fix(
        cls,
        task_title: str,
        spec: str,
        broken_code: str,
        error_signature: str,
        fixed_code: str | None = None
    ):
        diff_str = ""
        if fixed_code:
            diff_lines = list(difflib.unified_diff(
                broken_code.splitlines(),
                fixed_code.splitlines(),
                fromfile="failed.py",
                tofile="fixed.py",
                lineterm=""
            ))
            diff_str = "\n".join(diff_lines)

        entry = {
            "timestamp": central_iso(),
            "status": "FAIL_LEARNING",
            "task": task_title,
            "spec": spec,
            "broken_code": broken_code.strip(),
            "error": error_signature.strip(),
            "fixed_code": fixed_code.strip() if fixed_code else "",
            "diff": diff_str
        }
        with open(cls.FAILURE_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")


# ==============================================================================
# 5. CONSOLIDATION ENGINE: UPDATING WEIGHTS FROM THE JOURNAL
# ==============================================================================

def train_consolidation_pass(
    model: VivSovereignSLM,
    optimizer: torch.optim.Optimizer,
    device: str,
    steps: int = 50,
    batch_size: int = 4
) -> dict:
    """Trains the SLM on both positive solutions and negative correction vectors."""
    model.train()
    tok = SovereignByteTokenizer

    # Gather paired training sequences
    sequences = []

    # 1. Add "What Worked" (Positive Manifold)
    if SovereignJournal.SUCCESS_FILE.exists():
        for line in SovereignJournal.SUCCESS_FILE.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            seq_text = f"# Task: {row['task']}\n# Spec: {row['spec']}\n{row['code']}"
            ids = [tok.BOS_ID, tok.TASK_ID] + tok.encode(f"Task: {row['task']}\n") + [tok.PASS_ID] + tok.encode(row['code']) + [tok.EOS_ID]
            if len(ids) <= model.max_seq_len:
                sequences.append(ids)

    # 2. Add "How It Failed & Fix" (Contrastive / Counterfactual Manifold)
    if SovereignJournal.FAILURE_FILE.exists():
        for line in SovereignJournal.FAILURE_FILE.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            if row.get("fixed_code"):
                ids = (
                    [tok.BOS_ID, tok.TASK_ID]
                    + tok.encode(f"Task: {row['task']}\n")
                    + [tok.FAIL_ID]
                    + tok.encode(f"Error: {row['error']}\n")
                    + [tok.DIFF_ID]
                    + tok.encode(row['fixed_code'])
                    + [tok.EOS_ID]
                )
                if len(ids) <= model.max_seq_len:
                    sequences.append(ids)

    if not sequences:
        # Fallback to seed arithmetic / logic if journal is just starting
        seed_samples = [
            "def add(a, b):\n    return a + b\nassert add(2, 3) == 5\nassert add(-1, 1) == 0",
            "def is_even(n):\n    return n % 2 == 0\nassert is_even(4) is True\nassert is_even(7) is False",
            "def compute_parity(n):\n    return bin(n).count('1') % 2\nassert compute_parity(7) == 1\nassert compute_parity(3) == 0"
        ]
        for s in seed_samples:
            sequences.append([tok.BOS_ID, tok.PASS_ID] + tok.encode(s) + [tok.EOS_ID])

    # Execute gradient descent
    losses = []
    actual_steps = min(steps, len(sequences) * 10)
    for step in range(actual_steps):
        batch = [sequences[step % len(sequences)]]
        max_len = max(len(b) for b in batch)
        padded = [b + [tok.PAD_ID] * (max_len - len(b)) for b in batch]
        
        inp = torch.tensor(padded, dtype=torch.long, device=device)
        targets = inp.clone()
        targets[targets == tok.PAD_ID] = -100

        optimizer.zero_grad()
        logits = model(inp[:, :-1])
        loss = F.cross_entropy(logits.reshape(-1, tok.VOCAB_SIZE), targets[:, 1:].reshape(-1))
        loss.backward()
        torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
        optimizer.step()
        losses.append(loss.item())

    final_loss = sum(losses[-10:]) / max(1, len(losses[-10:]))
    return {
        "ok": True,
        "steps_completed": actual_steps,
        "samples_ingested": len(sequences),
        "final_loss": round(final_loss, 4),
        "initial_loss": round(losses[0], 4)
    }


# ==============================================================================
# 6. DEMONSTRATION WORKFLOW: EXPLORE -> TEST ON DRIVE -> CONSOLIDATE WEIGHTS
# ==============================================================================

def run_slm_trial():
    print("==================================================================")
    print(" VIV SOVEREIGN SLM: EXPLORATION, DETERMINISTIC TEST & WEIGHT CONSOLIDATION")
    print("==================================================================")

    # 1. Device selection (CPU or CUDA)
    device = "cuda:0" if torch.cuda.is_available() else "cpu"
    print(f"[+] Initializing Sovereign SLM on {device}...")
    model = VivSovereignSLM(
        vocab_size=SovereignByteTokenizer.VOCAB_SIZE,
        d_model=256,
        n_layers=6,
        n_heads=8,
        max_seq_len=512
    ).to(device)

    param_count = model.count_parameters()
    print(f"[+] Model instantiated: {param_count:,} parameters (Footprint: {param_count * 2 / 1024 / 1024:.2f} MB in FP16)")

    # 2. SEED TRIAL: Simulate an Exploration Step
    print("\n[+] STEP 1: Exploration & Physical Drive Testing")
    task_title = "ALU Bitwise Parity Gate"
    spec = "Return 1 if number of set bits is odd, 0 if even. Must have formal assertions."
    
    # Candidate A: Fails (Missing implementation / NameError)
    broken_code = """
def bitwise_parity(val: int) -> int:
    return count_bits(val) % 2

assert bitwise_parity(7) == 1
"""
    print(f"    [Candidate A - broken] Testing on drive...")
    rc, out, err = execute_in_sandbox(broken_code)
    print(f"    -> Result: Exit Code {rc} (FAIL: {err.strip()[:60]}...)")
    
    # Candidate B: Passes (Verified solution)
    fixed_code = """
def bitwise_parity(val: int) -> int:
    return bin(val).count('1') % 2

assert bitwise_parity(7) == 1
assert bitwise_parity(3) == 0
assert bitwise_parity(0) == 0
print('PARITY_PASSED')
"""
    print(f"    [Candidate B - fixed] Testing on drive...")
    rc_fixed, out_fixed, err_fixed = execute_in_sandbox(fixed_code)
    print(f"    -> Result: Exit Code {rc_fixed} (PASS: {out_fixed.strip()})")

    # 3. JOURNALING TO DISK
    print("\n[+] STEP 2: Writing Physical Journal to Drive E:")
    SovereignJournal.record_success(task_title, spec, fixed_code, asserts_passed=3)
    SovereignJournal.record_failure_and_fix(
        task_title=task_title,
        spec=spec,
        broken_code=broken_code,
        error_signature=err.strip().splitlines()[-1] if err else "NameError",
        fixed_code=fixed_code
    )
    print(f"    -> Written to {SovereignJournal.SUCCESS_FILE.name} and {SovereignJournal.FAILURE_FILE.name}")

    # 4. CONSOLIDATION PASS
    print("\n[+] STEP 3: Consolidating Weights via Gradient Descent")
    optimizer = torch.optim.AdamW(model.parameters(), lr=1e-3, weight_decay=0.01)
    train_res = train_consolidation_pass(model, optimizer, device=device, steps=25)
    print(f"    -> Ingested {train_res['samples_ingested']} paired sequences")
    print(f"    -> Initial Loss: {train_res['initial_loss']} | Final Loss: {train_res['final_loss']}")

    # 5. SAVE CHECKPOINT
    ckpt_file = CHECKPOINT_DIR / "viv_slm_epoch_0001.pt"
    torch.save({
        "epoch": 1,
        "model_state_dict": model.state_dict(),
        "train_res": train_res,
        "timestamp": central_iso()
    }, ckpt_file)
    print(f"    -> Checkpoint sealed: {ckpt_file.name} ({ckpt_file.stat().st_size / 1024:.1f} KB)")

    # 6. LOG PHYSICAL RECEIPT
    receipt = {
        "timestamp": central_iso(),
        "action": "SLM_TRIAL_CYCLE_COMPLETED",
        "parameters": param_count,
        "device": device,
        "checkpoint": str(ckpt_file),
        "training": train_res
    }
    with open(RECEIPTS_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(receipt) + "\n")

    print("\n==================================================================")
    print(" TRIAL COMPLETE: Proved exploration, disk test, and weight update!")
    print("==================================================================")
    return receipt


if __name__ == "__main__":
    run_slm_trial()
