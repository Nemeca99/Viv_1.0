"""Reuse the candidate memory proof with isolated epoch_10010 artifacts."""
from pathlib import Path
import os
import sys

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE.parent), str(HERE)]
import candidate_memory_learning_proof as proof

RUNS = HERE / "learning" / "deepseek_candidate_runs"
candidate = Path(os.environ.get("VIV_CODE_CANDIDATE", r"F:\LocalCoder_Archive\Viv_model_candidates\epoch_10010"))
epoch = candidate.name.removeprefix("epoch_")
proof.MODEL_CANDIDATE = candidate
proof.MEMORY_CANDIDATE = HERE.parent / "aios_rebuild" / "memory" / f"candidate_epoch_{epoch}.json"
proof.JOURNAL = HERE.parent / "aios_rebuild" / "memory" / f"candidate_epoch_{epoch}_journal.jsonl"
proof.OUT = RUNS / f"candidate_memory_proof_{epoch}.json"

if __name__ == "__main__":
    raise SystemExit(proof.main())
