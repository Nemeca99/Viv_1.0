"""Persistent incremental index of eligible source files on mounted fixed drives."""
from __future__ import annotations

import os
import pathlib
import hashlib
import json
import sqlite3
import time

TEXT_SUFFIXES = {
    ".py", ".pyi", ".rs", ".md", ".rst", ".txt", ".toml", ".yaml", ".yml",
    ".json", ".jsonl", ".csv", ".tsv", ".log", ".html", ".htm", ".xml",
    ".ini", ".cfg", ".conf", ".ps1", ".psm1", ".bat", ".cmd", ".sh",
    ".bash", ".ipynb", ".js", ".jsx", ".ts", ".tsx", ".go", ".java",
    ".c", ".h", ".cc", ".cpp", ".hh", ".hpp", ".cs", ".sql", ".rb",
    ".php", ".swift", ".kt", ".kts", ".scala", ".vue", ".svelte", ".css",
    ".scss", ".r", ".m", ".pl", ".lua", ".ex", ".exs", ".erl", ".hs",
    ".jl", ".dart", ".proto", ".tf", ".gradle", ".properties", ".tex",
}
SKIP_SUFFIXES = {".env", ".pem", ".key", ".p12", ".pfx", ".db", ".sqlite", ".sqlite3"}
SKIP_COMPONENTS = {
    ".git", ".venv", ".hive_proof_env", ".tox", "venv", "env", "__pycache__",
    "site-packages", "dist-packages", "node_modules", "models", "modelzoo", "adapters",
    "checkpoints", "outputs", "output", "cache", ".cache", "appdata", "windows",
    "program files", "program files (x86)", "programdata", "system volume information",
    "$recycle.bin", "$windows.~tmp", "steamlibrary", "steamapps", "browser", "browsers",
    "user data", "profiles", ".ssh", ".aws", ".azure", ".docker", ".ollama", "secrets",
    "credentials", "credential", "passwords", "cookies", "mail", "email", "phone",
    "old phone", "movies", "music", "videos", "recordings", "screenshots", "pictures",
    "desktop storage",
}
MAX_FILE_BYTES = 1_000_000
SLICE_MAX_DIRS = 512
SLICE_MAX_SECONDS = 8.0
INDEX_REFRESH_SECONDS = 24 * 60 * 60


def mounted_drive_roots() -> tuple[pathlib.Path, ...]:
    """Return every currently mounted drive root (C: through Z:), read-only."""
    roots = []
    for letter in "CDEFGHIJKLMNOPQRSTUVWXYZ":
        root = pathlib.Path(f"{letter}:/")
        try:
            if root.is_dir():
                roots.append(root)
        except OSError:
            continue
    return tuple(roots)


def _reparse(entry: os.DirEntry) -> bool:
    try:
        return entry.is_symlink() or bool(getattr(entry.stat(follow_symlinks=False),
                                                    "st_file_attributes", 0) & 0x400)
    except OSError:
        return True


def _connect(path: pathlib.Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path, timeout=20)
    con.execute("PRAGMA busy_timeout=20000")
    con.executescript("""
        CREATE TABLE IF NOT EXISTS directories(
            path TEXT PRIMARY KEY, root TEXT NOT NULL, state TEXT NOT NULL,
            error TEXT NOT NULL DEFAULT '');
        CREATE INDEX IF NOT EXISTS directories_pending ON directories(state,root,path);
        CREATE TABLE IF NOT EXISTS files(
            path TEXT PRIMARY KEY, root TEXT NOT NULL, size INTEGER NOT NULL,
            mtime_ns INTEGER NOT NULL);
        CREATE INDEX IF NOT EXISTS files_root ON files(root);
        CREATE TABLE IF NOT EXISTS roots(path TEXT PRIMARY KEY, state TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS index_meta(key TEXT PRIMARY KEY,value TEXT NOT NULL);
    """)
    return con


def advance_index(db_path: pathlib.Path, roots: tuple[pathlib.Path, ...] | None = None, *,
                  max_dirs: int = SLICE_MAX_DIRS,
                  max_seconds: float = SLICE_MAX_SECONDS) -> dict:
    """Advance a round-robin bounded scan; progress survives process restarts."""
    roots = roots if roots is not None else mounted_drive_roots()
    con = _connect(db_path)
    started = time.monotonic()
    scanned = errors = skipped_large = 0
    try:
        policy = json.dumps({"schema": 2, "suffixes": sorted(TEXT_SUFFIXES),
                            "skip_suffixes": sorted(SKIP_SUFFIXES),
                            "skip_components": sorted(SKIP_COMPONENTS),
                            "max_file_bytes": MAX_FILE_BYTES},
                           sort_keys=True, separators=(",", ":"))
        policy_sha = hashlib.sha256(policy.encode("utf-8")).hexdigest()
        prior_policy = con.execute(
            "SELECT value FROM index_meta WHERE key='policy_sha256'").fetchone()
        if prior_policy is None or prior_policy[0] != policy_sha:
            with con:
                con.execute("UPDATE directories SET state='pending',error=''")
                con.execute("DELETE FROM files")
                con.execute("INSERT OR REPLACE INTO index_meta(key,value) VALUES('policy_sha256',?)",
                            (policy_sha,))
                con.execute("DELETE FROM index_meta WHERE key='last_complete_scan'")
        with con:
            for root in roots:
                raw = str(root.resolve())
                con.execute("INSERT OR IGNORE INTO roots(path,state) VALUES (?, 'indexing')", (raw,))
                con.execute("INSERT OR IGNORE INTO directories(path,root,state) VALUES (?,?,'pending')",
                            (raw, raw))
        root_strings = [str(root.resolve()) for root in roots]
        while scanned < max_dirs and time.monotonic() - started < max_seconds:
            did_work = False
            for root in root_strings:
                if scanned >= max_dirs or time.monotonic() - started >= max_seconds:
                    break
                row = con.execute(
                    "SELECT path FROM directories WHERE root=? AND state='pending' ORDER BY path LIMIT 1",
                    (root,)).fetchone()
                if row is None:
                    continue
                did_work = True
                directory = pathlib.Path(row[0])
                try:
                    with os.scandir(directory) as entries:
                        for entry in entries:
                            name = entry.name.casefold()
                            if name in SKIP_COMPONENTS or _reparse(entry):
                                continue
                            if entry.is_dir(follow_symlinks=False):
                                child = str(pathlib.Path(entry.path).resolve())
                                con.execute(
                                    "INSERT OR IGNORE INTO directories(path,root,state) VALUES (?,?,'pending')",
                                    (child, root))
                            elif entry.is_file(follow_symlinks=False):
                                suffix = pathlib.Path(entry.name).suffix.casefold()
                                if suffix not in TEXT_SUFFIXES or suffix in SKIP_SUFFIXES:
                                    continue
                                try:
                                    stat = entry.stat(follow_symlinks=False)
                                    if stat.st_size > MAX_FILE_BYTES:
                                        skipped_large += 1
                                        continue
                                    raw_path = str(pathlib.Path(entry.path).resolve())
                                    con.execute(
                                        "INSERT INTO files(path,root,size,mtime_ns) VALUES (?,?,?,?) "
                                        "ON CONFLICT(path) DO UPDATE SET root=excluded.root, "
                                        "size=excluded.size,mtime_ns=excluded.mtime_ns",
                                        (raw_path, root, stat.st_size, stat.st_mtime_ns))
                                except OSError:
                                    errors += 1
                    con.execute("UPDATE directories SET state='done',error='' WHERE path=?", (row[0],))
                except OSError as exc:
                    errors += 1
                    con.execute("UPDATE directories SET state='error',error=? WHERE path=?",
                                (type(exc).__name__, row[0]))
                scanned += 1
            if not did_work:
                break
            con.commit()
        pending = con.execute("SELECT COUNT(*) FROM directories WHERE state='pending'").fetchone()[0]
        if pending == 0:
            last_complete = con.execute(
                "SELECT value FROM index_meta WHERE key='last_complete_scan'").fetchone()
            try:
                last_scan_time = float(last_complete[0]) if last_complete else None
            except (TypeError, ValueError):
                last_scan_time = None
            if last_scan_time is not None and time.time() - last_scan_time >= INDEX_REFRESH_SECONDS:
                with con:
                    con.execute("UPDATE directories SET state='pending',error='' WHERE state='done'")
                    con.execute("DELETE FROM index_meta WHERE key='last_complete_scan'")
                pending = con.execute("SELECT COUNT(*) FROM directories WHERE state='pending'").fetchone()[0]
        if pending == 0:
            with con:
                con.execute("INSERT OR REPLACE INTO index_meta(key,value) VALUES('last_complete_scan',?)",
                            (str(time.time()),))
        root_stats = []
        for root in root_strings:
            dirs_done, dirs_error = con.execute(
                "SELECT SUM(state='done'),SUM(state='error') FROM directories WHERE root=?", (root,)
            ).fetchone()
            file_count = con.execute("SELECT COUNT(*) FROM files WHERE root=?", (root,)).fetchone()[0]
            root_stats.append({"root": root, "directories_indexed": dirs_done or 0,
                               "directory_errors": dirs_error or 0, "eligible_files": file_count,
                               "complete": con.execute(
                                   "SELECT 1 FROM directories WHERE root=? AND state='pending' LIMIT 1",
                                   (root,)).fetchone() is None})
        total_files = con.execute("SELECT COUNT(*) FROM files").fetchone()[0]
        errored_directories = sum(item[0] or 0 for item in con.execute(
            "SELECT SUM(state='error') FROM directories GROUP BY root"))
        return {"mode": "persistent_read_only_drive_index", "roots": root_stats,
                "directories_scanned_this_slice": scanned, "pending_directories": pending,
                "eligible_files_indexed": total_files,
                "index_complete": pending == 0 and errored_directories == 0,
                "index_traversal_finished": pending == 0,
                "directory_errors_total": errored_directories,
                "index_policy_sha256": policy_sha,
                "scan_errors_this_slice": errors, "skipped_large_this_slice": skipped_large,
                "slice_elapsed_seconds": round(time.monotonic() - started, 3),
                "sensitive_and_non_source_paths_pruned": True}
    finally:
        con.close()


def indexed_paths(db_path: pathlib.Path) -> list[pathlib.Path]:
    con = _connect(db_path)
    try:
        return [pathlib.Path(row[0]) for row in con.execute("SELECT path FROM files")]
    finally:
        con.close()


def random_indexed_paths(db_path: pathlib.Path, count: int, rng, *,
                         root: str | None = None) -> list[pathlib.Path]:
    """Return a bounded pseudo-random sample using SQLite rowid seeks."""
    if not isinstance(count, int) or not 1 <= count <= 1024:
        raise ValueError("count must be an integer from 1 to 1024")
    con = _connect(db_path)
    try:
        if root is None:
            bounds = con.execute(
                "SELECT MIN(rowid),MAX(rowid) FROM files").fetchone()
        else:
            bounds = con.execute(
                "SELECT MIN(rowid),MAX(rowid) FROM files WHERE root=?", (root,)).fetchone()
        low, high = bounds
        if low is None or high is None:
            return []

        def seek(target):
            if root is None:
                row = con.execute(
                    "SELECT rowid,path FROM files WHERE rowid>=? ORDER BY rowid LIMIT 1",
                    (target,)).fetchone()
                return row or con.execute(
                    "SELECT rowid,path FROM files ORDER BY rowid LIMIT 1").fetchone()
            row = con.execute(
                "SELECT rowid,path FROM files WHERE root=? AND rowid>=? ORDER BY rowid LIMIT 1",
                (root, target)).fetchone()
            return row or con.execute(
                "SELECT rowid,path FROM files WHERE root=? ORDER BY rowid LIMIT 1",
                (root,)).fetchone()

        paths = []
        seen_rowids = set()
        attempts = 0
        while len(paths) < count and attempts < count * 16:
            row = seek(rng.randint(low, high))
            attempts += 1
            if row is None or row[0] in seen_rowids:
                continue
            seen_rowids.add(row[0])
            paths.append(pathlib.Path(row[1]))
        return paths
    finally:
        con.close()
