"""Forge Sweep analyzer: READ-ONLY. Reads per-drive indexes, writes a markdown report.

Usage: python sweep_analyze.py <report_dir> <DriveLetter> [<DriveLetter> ...]
Reports: top folders by size, duplicate candidates (size -> hash), stale training checkpoints.
Duplicates are confirmed ONLY by full SHA-256; size match alone is never trusted.
"""
import glob
import hashlib
import json
import os
import re
import sys
from collections import Counter, defaultdict

PROTECTED = ("\\windows\\", "\\program files", "\\system32\\", "\\.git\\", "\\aios_v2\\")
MIN_DUPE = 50 * 1024 * 1024  # only consider files >= 50 MB for hashing


def latest_index(letter):
    files = sorted(glob.glob(f"{letter}:\\_drive_index\\index_*.jsonl"))
    return files[-1] if files else None


def load(letter):
    path = latest_index(letter)
    if not path:
        return []
    out = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            d = json.loads(line)
            if "s" in d:
                out.append((d["p"], d["s"], d["m"]))
    return out


def sha256(path, chunk=1 << 20):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while b := f.read(chunk):
            h.update(b)
    return h.hexdigest()


def main(report_dir, letters):
    os.makedirs(report_dir, exist_ok=True)
    rows = []
    for l in letters:
        rows += load(l)
    lines = [f"# Forge Sweep report ({', '.join(letters)})", ""]

    folders = Counter()
    for p, s, _ in rows:
        parts = p.split("\\")
        folders["\\".join(parts[:3])] += s
    lines += ["## Top folders", ""]
    lines += [f"- {v / 1e9:.1f} GB  `{k}`" for k, v in folders.most_common(25)]

    by_size = defaultdict(list)
    for p, s, _ in rows:
        if s >= MIN_DUPE and not any(x in p.lower() for x in PROTECTED):
            by_size[s].append(p)
    lines += ["", "## Confirmed duplicates (SHA-256, files >= 50 MB)", ""]
    saved = 0
    for s, paths in sorted(by_size.items(), reverse=True):
        if len(paths) < 2:
            continue
        groups = defaultdict(list)
        for p in paths:
            try:
                groups[sha256(p)].append(p)
            except OSError:
                pass
        for h, g in groups.items():
            if len(g) > 1:
                saved += s * (len(g) - 1)
                lines.append(f"- {s / 1e9:.2f} GB x{len(g)}  (reclaimable {s * (len(g) - 1) / 1e9:.2f} GB)")
                lines += [f"  - `{x}`" for x in g]
    lines.insert(len(lines) - 0, f"\n**Total reclaimable from duplicates: {saved / 1e9:.1f} GB**")

    ck = defaultdict(list)
    for p, s, m in rows:
        if re.search(r"checkpoint-\d+", p, re.I):
            ck[re.split(r"checkpoint-\d+", p, flags=re.I)[0]].append((p, s))
    lines += ["", "## Intermediate training checkpoints (review, not auto-delete)", ""]
    for base, items in ck.items():
        total = sum(s for _, s in items)
        lines.append(f"- {total / 1e9:.2f} GB in {len(items)} files under `{base}`")

    out = os.path.join(report_dir, "sweep_report.md")
    with open(out, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print("Wrote", out)


if __name__ == "__main__":
    if len(sys.argv) < 3:
        raise SystemExit(__doc__)
    main(sys.argv[1], sys.argv[2:])
