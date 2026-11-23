"""Measures whether Viv is learning from receipts: pass-rate trend, graduation trend, loss trend, lessons."""
import json
from pathlib import Path

R = Path(r"E:\Viv_Sandbox\playground")


def jl(p):
    out = []
    if p.exists():
        for l in p.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                out.append(json.loads(l))
            except Exception:
                pass
    return out


rc = jl(R / "receipts" / "playground_receipts.jsonl")
work = [r for r in rc if r.get("action") in ("agenda", "game")]
print(f"work receipts: {len(work)}")

# Pass rate by quartile (chronological)
q = max(1, len(work) // 4)
for i in range(4):
    chunk = work[i * q:(i + 1) * q] if i < 3 else work[3 * q:]
    p = sum(1 for r in chunk if r.get("passed"))
    g = sum(1 for r in chunk if r.get("is_graduated"))
    e = sum(1 for r in chunk if r.get("executed_ok"))
    print(f"Q{i+1}: n={len(chunk)} exec_ok={e/len(chunk):.1%} graduated={g/len(chunk):.1%} passed={p/len(chunk):.1%}")

# Assertion density of graduated code over time
grad = jl(R / "training" / "graduated_successes.jsonl")
if grad:
    h = len(grad) // 2
    a1 = sum(x.get("assert_count", 0) for x in grad[:h]) / max(1, h)
    a2 = sum(x.get("assert_count", 0) for x in grad[h:]) / max(1, len(grad) - h)
    print(f"graduated programs: {len(grad)}; mean asserts first half={a1:.2f} second half={a2:.2f}")

# Sleep training loss trend
sl = jl(R / "receipts" / "sleep_training_receipts.jsonl")
losses = [(s["epoch"], s["final_loss"]) for s in sl if s.get("final_loss")]
if losses:
    n = len(losses)
    f = sum(l for _, l in losses[:n // 3]) / max(1, n // 3)
    t = sum(l for _, l in losses[-(n // 3):]) / max(1, n // 3)
    print(f"sleep epochs trained: {n}; mean loss first third={f:.3f} last third={t:.3f}")

# AIOS organs
organs = [p.name for p in (R / "my_aios").glob("*.py")]
print(f"organs reconstructed: {len(organs)} -> {organs}")
ag = [r for r in rc if r.get("action") == "agenda" and r.get("organ_file")]
print(f"organ attempts: {len(ag)}; passed: {sum(1 for r in ag if r.get('passed'))}")
for o in sorted(set(r['organ_file'] for r in ag)):
    rs = [r for r in ag if r['organ_file'] == o]
    print(f"  {o}: {sum(1 for r in rs if r.get('passed'))}/{len(rs)}")

ls = jl(R / "lessons" / "lessons.jsonl")
print(f"lessons recorded: {len(ls)}")
for l in ls[-3:]:
    print(f"  [{l['title']}] error: {l['error'][:90]}")
