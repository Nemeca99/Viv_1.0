"""Training monitor daemon: report Viv's deep-training status every 10 minutes.

Reads the deep-training log, extracts the latest loss / sample / acted scene,
and appends one JSON status line to a monitor log. Runs in the background until
the training finishes (it sees the "done" event), then reports the final state
and exits. Logged only -- no model judgement, no interpretation.
"""
import json
import time
from datetime import datetime, timezone
from pathlib import Path

TRAIN_LOG = Path("L:/LocalCoder/.opencode/evals/viv-deep-training.log")
MONITOR_LOG = Path("L:/LocalCoder/.opencode/evals/viv-deep-training-monitor.log")
INTERVAL = 600  # seconds = 10 minutes


def scan() -> tuple[dict | None, dict | None, dict | None, bool]:
    """Return (last_loss, last_sample, last_scene, done)."""
    if not TRAIN_LOG.is_file():
        return None, None, None, False
    last_loss = last_sample = last_scene = None
    done = False
    for ln in TRAIN_LOG.read_text(encoding="utf-8", errors="replace").splitlines():
        if '"event":"sample"' in ln:
            try:
                last_sample = json.loads(ln)
            except json.JSONDecodeError:
                pass
        elif '"event":"scene"' in ln:
            try:
                last_scene = json.loads(ln)
            except json.JSONDecodeError:
                pass
        elif '"event":"done"' in ln:
            try:
                j = json.loads(ln)
                last_loss = {"step": j.get("steps"), "loss": j.get("loss")}
                done = True
            except json.JSONDecodeError:
                pass
        elif '"loss"' in ln:
            try:
                j = json.loads(ln)
                if "step" in j and "loss" in j:
                    last_loss = j
            except json.JSONDecodeError:
                pass
    return last_loss, last_sample, last_scene, done


def main() -> int:
    while True:
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        loss, sample, scene, done = scan()
        line = {"ts": ts}
        if loss:
            line["step"] = loss.get("step")
            line["loss"] = round(loss["loss"], 4) if loss.get("loss") is not None else None
        if sample:
            line["probe"] = sample.get("probe")
            line["probe_text"] = sample.get("text", "").splitlines()[0][:90] if sample.get("text") else ""
        if scene:
            line["scene"] = scene.get("scene")
            line["scene_text"] = scene.get("text", "").splitlines()[0][:90] if scene.get("text") else ""
        if not any(k in line for k in ("loss", "probe", "scene")):
            line["status"] = "no training output yet"
        with MONITOR_LOG.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(line) + "\n")
        if done:
            return 0
        time.sleep(INTERVAL)


if __name__ == "__main__":
    raise SystemExit(main())
