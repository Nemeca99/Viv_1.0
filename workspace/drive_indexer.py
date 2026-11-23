"""Per-drive indexer: read-only snapshot of every file on a drive.

Usage: L:\\.venv\\Scripts\\python.exe drive_indexer.py D
Writes  <drive>:\\_drive_index\\index_<YYYYMMDD_HHMMSS>.jsonl  (+ summary .json)
Each line: {"p": path, "s": size_bytes, "m": mtime_epoch}
Never modifies or deletes anything except its own index output.
Junctions / symlinks are recorded but NOT followed (avoids double counting).
"""
import json
import os
import sys
import time

SKIP_DIRS = {"$recycle.bin", "system volume information", "_drive_index"}


def index_drive(letter: str) -> None:
    root = f"{letter.upper()}:\\"
    if not os.path.isdir(root):
        raise SystemExit(f"Drive not found: {root}")
    out_dir = os.path.join(root, "_drive_index")
    os.makedirs(out_dir, exist_ok=True)
    stamp = time.strftime("%Y%m%d_%H%M%S")
    out_path = os.path.join(out_dir, f"index_{stamp}.jsonl")
    files = total = errors = links = 0
    started = time.time()
    stack = [root]
    with open(out_path, "w", encoding="utf-8") as out:
        while stack:
            cur = stack.pop()
            try:
                with os.scandir(cur) as it:
                    for e in it:
                        try:
                            if e.is_symlink() or (hasattr(e, "is_junction") and e.is_junction()):
                                links += 1
                                out.write(json.dumps({"p": e.path, "link": True}) + "\n")
                            elif e.is_dir(follow_symlinks=False):
                                if e.name.lower() not in SKIP_DIRS:
                                    stack.append(e.path)
                            else:
                                st = e.stat(follow_symlinks=False)
                                out.write(json.dumps({"p": e.path, "s": st.st_size, "m": int(st.st_mtime)}) + "\n")
                                files += 1
                                total += st.st_size
                        except OSError:
                            errors += 1
            except OSError:
                errors += 1
            if files and files % 200000 == 0:
                print(f"{files:,} files, {total / 1e9:.1f} GB, {time.time() - started:.0f}s", flush=True)
    summary = {
        "drive": root, "files": files, "bytes": total, "links": links,
        "errors": errors, "seconds": round(time.time() - started, 1), "index": out_path,
    }
    with open(os.path.join(out_dir, f"summary_{stamp}.json"), "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("usage: drive_indexer.py <DriveLetter>")
    index_drive(sys.argv[1])
