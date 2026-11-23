import json
from pathlib import Path

receipts_file = Path(r"E:\Viv_Sandbox\playground\receipts\playground_receipts.jsonl")
monologue_file = Path(r"E:\Viv_Sandbox\playground\monologue\viv_monologue.md")
agenda_file = Path(r"E:\Viv_Sandbox\playground\agenda\viv_agenda.json")
grad_file = Path(r"E:\Viv_Sandbox\playground\training\graduated_successes.jsonl")

# 1. Parse receipts
receipts = []
with open(receipts_file, "r", encoding="utf-8") as f:
    for line in f:
        line = line.strip()
        if line:
            try:
                receipts.append(json.loads(line))
            except Exception:
                pass

print(f"Total receipts parsed: {len(receipts)}")

# 2. Parse monologue file
mono_entries = []
if monologue_file.exists():
    raw_mono = monologue_file.read_text(encoding="utf-8")
    blocks = raw_mono.split("### Entry ")
    for b in blocks[1:]:
        entry_header = b.splitlines()[0] if b.splitlines() else ""
        mono_entries.append((entry_header, b))

print(f"Total monologue entries: {len(mono_entries)}")

# 3. Analyze task failure -> success transitions
history = {}
for idx, r in enumerate(receipts):
    action = r.get("action")
    title = r.get("title") or r.get("archetype") or r.get("source")
    if not title:
        continue
    key = f"{action}::{title}"
    if key not in history:
        history[key] = []
    history[key].append({
        "step": r.get("step", idx),
        "timestamp": r.get("timestamp"),
        "passed": r.get("passed", False),
        "executed_ok": r.get("executed_ok", False),
        "is_graduated": r.get("is_graduated", False),
        "assert_count": r.get("assert_count", 0),
        "error": r.get("grad_reason") or r.get("error", ""),
        "organ_file": r.get("organ_file")
    })

# Identify items that had failures followed by successes
recovered_cases = []
for key, runs in history.items():
    passed_runs = [run for run in runs if run["passed"]]
    failed_runs = [run for run in runs if not run["passed"]]
    if passed_runs and failed_runs:
        # Check chronological order: did at least one failure happen before a success?
        first_fail = failed_runs[0]
        first_pass = passed_runs[0]
        if first_fail["step"] < first_pass["step"]:
            recovered_cases.append({
                "key": key,
                "first_fail": first_fail,
                "first_pass": first_pass,
                "total_runs": len(runs),
                "total_fails": len(failed_runs),
                "total_passes": len(passed_runs)
            })

print(f"\n--- Found {len(recovered_cases)} Recovered Trajectories (Failed First -> Succeeded Later) ---")
for c in recovered_cases:
    print(f"\n[KEY]: {c['key']}")
    print(f"  Fails: {c['total_fails']}, Passes: {c['total_passes']}")
    print(f"  First Failure: Step {c['first_fail']['step']} @ {c['first_fail']['timestamp']}")
    print(f"    Error: {c['first_fail']['error'][:100]}")
    print(f"  First Success: Step {c['first_pass']['step']} @ {c['first_pass']['timestamp']}")
    print(f"    Asserts: {c['first_pass']['assert_count']}, Status: Verified Exit 0")
