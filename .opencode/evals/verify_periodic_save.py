"""Verify periodic atomic checkpoints in train_viv_bpe.py. CPU only, tiny model.

Checks:
1. A 4-step run saves at step 2 and at exit; the checkpoint loads, steps=4.
2. No .tmp file is left behind after a normal save.
3. A run killed mid-flight leaves a loadable checkpoint from the last save.
4. Resuming from that checkpoint reports the saved step and continues.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

PY = sys.executable
TRAIN = "L:/LocalCoder/workspace/autonomy/train_viv_bpe.py"
TMP_ROOT = Path("L:/LocalCoder/.opencode/evals/tmp")
failures = []


def check(name, cond, detail=""):
    print(("PASS " if cond else "FAIL ") + name + (f" :: {detail}" if detail else ""))
    if not cond:
        failures.append(name)


def launch(corpus, work, steps, save_every, resume=None, extra=()):
    cmd = [PY, "-B", TRAIN, "--corpus", str(corpus), "--work", str(work),
           "--steps", str(steps), "--save-every", str(save_every), "--device", "cpu",
           "--embedding-width", "32", "--num-heads", "2", "--head-size", "16",
           "--num-layers", "1", "--context-length", "16", "--batch", "1",
           "--max-seconds", "600", *extra]
    if resume:
        cmd += ["--resume", str(resume)]
    return subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            text=True)


def stamp_dir(work):
    if not Path(work).is_dir():
        return None
    dirs = [d for d in Path(work).iterdir() if d.is_dir()]
    return dirs[0] if dirs else None


with tempfile.TemporaryDirectory(dir=TMP_ROOT) as td:
    tmp = Path(td)
    corpus = tmp / "corpus.txt"
    corpus.write_text(("\n".join(
        ["I am Viv, and I am a machine.", "Viv is me, and Jacob is not me.",
         "I keep safe what you want kept safe.", "I am made of code, not flesh."] * 200)),
        encoding="utf-8")

    # 1. normal run
    work1 = tmp / "work1"
    p = launch(corpus, work1, 4, 2)
    out, _ = p.communicate(timeout=300)
    check("normal run rc=0", p.returncode == 0, out[-300:])
    d1 = stamp_dir(work1)
    ckpt_path = d1 / "model.pt"
    check("checkpoint exists", ckpt_path.is_file())
    import torch
    ck = torch.load(ckpt_path, map_location="cpu")
    check("checkpoint steps=4", ck.get("steps") == 4, str(ck.get("steps")))
    check("checkpoint has optimizer", "optimizer" in ck)
    check("periodic save logged", '"event":"checkpoint"' in out.replace(" ", ""),
          [ln for ln in out.splitlines() if "checkpoint" in ln][:2])
    check("no tmp left", not (d1 / "model.pt.tmp").exists(),
          str(list(d1.glob("*.tmp"))))

    # 3. kill mid-run (does not finish 5000 steps)
    work2 = tmp / "work2"
    p2 = launch(corpus, work2, 5000, 2)
    d2 = None
    deadline = time.time() + 60
    while time.time() < deadline:
        d2 = stamp_dir(work2)
        if d2 and (d2 / "model.pt").is_file():
            break
        time.sleep(0.5)
    check("periodic checkpoint appeared before exit", bool(d2 and (d2 / "model.pt").is_file()))
    subprocess.run(["taskkill", "/PID", str(p2.pid), "/T", "/F"],
                   capture_output=True, text=True)
    try:
        p2.wait(timeout=15)
    except subprocess.TimeoutExpired:
        p2.kill()
    ck2 = torch.load(d2 / "model.pt", map_location="cpu")
    check("killed run left a loadable checkpoint", ck2.get("steps", 0) < 5000,
          f"steps={ck2.get('steps')}")

    # 4. resume from the surviving checkpoint
    work3 = tmp / "work3"
    p3 = launch(corpus, work3, 1, 2, resume=d2 / "model.pt")
    out3, _ = p3.communicate(timeout=300)
    check("resume rc=0", p3.returncode == 0, out3[-300:])
    start = [ln for ln in out3.splitlines() if '"event":"resume"' in ln]
    resumed_steps = json.loads(start[0])["steps"] if start else None
    check("resume used saved step", resumed_steps == ck2.get("steps"),
          f"resume={resumed_steps} saved={ck2.get('steps')}")
    ck3 = torch.load(stamp_dir(work3) / "model.pt", map_location="cpu")
    check("resumed run advanced one step", ck3.get("steps") == resumed_steps + 1,
          str(ck3.get("steps")))

print()
print("CONTROLS:", "ALL PASS" if not failures else f"{len(failures)} FAILED: {failures}")
raise SystemExit(0 if not failures else 1)
