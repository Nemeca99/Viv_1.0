"""Archive old language-route snapshots to F: with hash verification.

Copy first, hash both sides, delete the L: copy only when every file matches.
Never touches non-route runs (protected pointers reference those). Writes a manifest.
"""
import hashlib
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

RUNS = Path(r"L:\LocalCoder\workspace\autonomy\learning\neural_runs")
ARCHIVE = Path(r"F:\LocalCoder_Archive\INN_live_runs")
KEEP_NEWEST = 5


def sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main():
    ARCHIVE.mkdir(parents=True, exist_ok=True)
    routes = sorted(p for p in RUNS.glob("language-routes-*") if p.is_dir())
    candidates = routes[:-KEEP_NEWEST] if len(routes) > KEEP_NEWEST else []
    print(f"route runs: {len(routes)}; archiving {len(candidates)}; keeping {len(routes) - len(candidates)}", flush=True)
    manifest = {"created_utc": datetime.now(timezone.utc).isoformat(), "runs": {}}
    freed = 0
    for run in candidates:
        dest = ARCHIVE / run.name
        if dest.exists():
            print(f"SKIP exists: {run.name}", flush=True)
            continue
        shutil.copytree(run, dest)
        files = {}
        ok = True
        for source in sorted(p for p in run.rglob("*") if p.is_file()):
            relative = str(source.relative_to(run))
            copied = dest / relative
            source_hash = sha256(source)
            if not copied.is_file() or sha256(copied) != source_hash:
                ok = False
                print(f"HASH MISMATCH: {run.name}/{relative}", flush=True)
                break
            files[relative] = source_hash
        if not ok:
            print(f"KEEP source (unverified): {run.name}", flush=True)
            continue
        size = sum(p.stat().st_size for p in run.rglob("*") if p.is_file())
        manifest["runs"][run.name] = {"files": files, "bytes": size, "archived_to": str(dest)}
        shutil.rmtree(run)
        freed += size
        print(f"ARCHIVED {run.name} ({size / 1e6:.0f} MB) freed total {freed / 1e9:.2f} GB", flush=True)
        (ARCHIVE / "manifest_20261101.json").write_text(json.dumps(manifest, indent=1), encoding="utf-8")
    (ARCHIVE / "manifest_20261101.json").write_text(json.dumps(manifest, indent=1), encoding="utf-8")
    print(f"DONE archived {len(manifest['runs'])} runs, freed {freed / 1e9:.2f} GB", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
