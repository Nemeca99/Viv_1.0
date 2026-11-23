"""Deterministic controls for the 1:3 context budget. No model, no GPU."""
import sys

sys.path.insert(0, "L:/LocalCoder/workspace/autonomy")
import context_budget as cb  # noqa: E402

fails = []


def check(name, cond, detail=""):
    print(("PASS " if cond else "FAIL ") + name + (f" :: {detail}" if detail else ""))
    if not cond:
        fails.append(name)


check("128 at 1:3 -> 32/96", cb.split(128) == (32, 96), str(cb.split(128)))
check("input+output equals context", sum(cb.split(128)) == 128)
check("128 at 1:1 -> 64/64", cb.split(128, (1, 1)) == (64, 64))
check("64 at 1:3 -> 16/48", cb.split(64) == (16, 48))
check("ratio is configurable", cb.split(128, (1, 7)) == (16, 112))

for bad in ((0, 3), (1, 0), (-1, 3)):
    try:
        cb.split(128, bad)
        check(f"invalid ratio {bad} rejected", False)
    except ValueError:
        check(f"invalid ratio {bad} rejected", True)

try:
    cb.split(1)
    check("tiny context rejected", False)
except ValueError:
    check("tiny context rejected", True)

ids = list(range(100))
check("tail keeps most recent 32", cb.tail_ids(ids, 32) == list(range(68, 100)))
check("short prompt unchanged", cb.tail_ids([1, 2, 3], 32) == [1, 2, 3])

print()
print("CONTROLS:", "ALL PASS" if not fails else f"{len(fails)} FAILED: {fails}")
raise SystemExit(0 if not fails else 1)
