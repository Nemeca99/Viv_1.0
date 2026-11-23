"""Invariant 4 end-to-end: Body-permit -> INN candidate begin -> one-shot consume (synthetic)."""
import importlib.machinery
import importlib.util
import json
import os
import shutil
from pathlib import Path

WORKSPACE = Path(r"L:\LocalCoder\workspace\aios_rebuild")
library = WORKSPACE / "local_security_core" / "target" / "debug" / "security_core.dll"

loader = importlib.machinery.ExtensionFileLoader("security_core", str(library))
spec = importlib.util.spec_from_file_location("security_core", library, loader=loader)
mod = importlib.util.module_from_spec(spec)
loader.exec_module(mod)

stability_sn = 0.75
sensor_age = 1.0
threads = 1
staging_root = "L:/LocalCoder/workspace/autonomy/learning/neural_candidate_staging"
runs_root = "L:/LocalCoder/workspace/autonomy/learning/neural_runs"


def make_request(run_id, permit=None):
    req = {
        "action": "BEGIN_INN_CANDIDATE",
        "stage_id": "inn_candidate",
        "run_id": run_id,
        "model_role": "inn_candidate_trainer",
        "manifest_hash": "a" * 64,
        "source_hashes": ["b" * 64],
        "paths": [f"{staging_root}/{run_id}", f"{runs_root}/{run_id}"],
        "artifact_class": "inn_candidate_bundle",
        "master_s_n": stability_sn,
        "process_id": os.getpid(),
        "max_duration_s": 60,
        "max_vram_mib": 8192,
        "max_ram_mib": 28672,
        "max_disk_mib": 512,
        "sequence_cap": 384,
        "lora_rank": 0,
        "body_requested_threads": threads,
    }
    if permit is not None:
        req["body_runtime_permit"] = permit
    return req


def cleanup(run_id):
    staging = Path(staging_root) / run_id
    if staging.exists():
        shutil.rmtree(staging, ignore_errors=True)


run_a = "invariant4a-" + str(os.getpid())
run_b = "invariant4b-" + str(os.getpid())

# 1. Body ALLOW -> issue process-bound one-use permit
token_a = mod.issue_body_runtime_permit(stability_sn, sensor_age, threads, run_a)
print("1. permit minted: len=%d hex=%s" % (len(token_a), all(c in "0123456789abcdef" for c in token_a)))

# 2. begin with valid permit -> allowed (permit consumed here)
r = mod.begin_training_lease(json.dumps(make_request(run_a, token_a)))
print("2. begin(valid permit) allowed=%s reason=%s lease_token=%s" % (r.get("allowed"), r.get("reason"), (r.get("lease_token") or "")[:12]))

# 3. cleanup staging, then replay the SAME consumed permit -> one-shot denial
cleanup(run_a)
r = mod.begin_training_lease(json.dumps(make_request(run_a, token_a)))
print("3. begin(replayed permit) allowed=%s reason=%s" % (r.get("allowed"), r.get("reason")))
cleanup(run_a)

# 4. missing permit -> denied before filesystem write
r = mod.begin_training_lease(json.dumps(make_request(run_b)))
print("4. begin(no permit) allowed=%s reason=%s" % (r.get("allowed"), r.get("reason")))

# 5. a FRESH permit for run_b -> allowed (proves permits are not globally exhausted)
token_b = mod.issue_body_runtime_permit(stability_sn, sensor_age, threads, run_b)
r = mod.begin_training_lease(json.dumps(make_request(run_b, token_b)))
print("5. begin(fresh permit) allowed=%s reason=%s" % (r.get("allowed"), r.get("reason")))
cleanup(run_b)

print("DONE")
