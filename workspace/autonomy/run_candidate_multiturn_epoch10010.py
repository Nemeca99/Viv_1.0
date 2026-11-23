"""Run the established two-turn Python edit proof against epoch_10010."""
from pathlib import Path
import os
import sys

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE.parent), str(HERE)]
import evaluate_candidate_multiturn_python_v1 as proof

candidate = Path(os.environ.get("VIV_CODE_CANDIDATE", r"F:\LocalCoder_Archive\Viv_model_candidates\epoch_10010"))
epoch = candidate.name.removeprefix("epoch_")
proof.CANDIDATE = candidate
proof.OUT = HERE / "learning" / "deepseek_candidate_runs" / f"multiturn_candidate_{epoch}.json"

if __name__ == "__main__":
    raise SystemExit(proof.main())
