"""Bounded, read-only local source and documentation observer for Viv."""
from __future__ import annotations

import hashlib
import os
import pathlib
import random
import re
import secrets
import time
from functools import lru_cache
from autonomy.pc_source_index import (MAX_FILE_BYTES, SKIP_SUFFIXES, TEXT_SUFFIXES,
                                     advance_index, indexed_paths, mounted_drive_roots)

MAX_FILES = 60_000
MAX_DIRS = 20_000
MAX_SECONDS = 25.0
MAX_RESULTS = 8
MAX_SNIPPET_CHARS = 900
LEARNING_SNIPPET_CHARS = 240
SENSITIVE_FILE_NAME = re.compile(
    r"(?i)^(?:\.env(?:\..*)?|.*(?:^|[._-])(?:key|secret|secrets|credential|credentials|"
    r"password|passwd|token|api[_-]?key|private[_-]?key|id_rsa|id_ed25519)(?:$|[._-]).*)$")
SENSITIVE_VALUE = re.compile(
    r"(?i)(?:api[_-]?key|access[_-]?token|password|passwd|secret|authorization)\s*[:=]"
    r"|\b(?:sk-[A-Za-z0-9_-]{20,}|gh[pousr]_[A-Za-z0-9]{20,}|hf_[A-Za-z0-9]{20,})\b"
    r"|-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----")

SCAN_ROOTS = mounted_drive_roots()
PC_INDEX_DB = pathlib.Path(__file__).resolve().parent / "autonomy" / "pc_source_index.sqlite3"
SKIP_COMPONENTS = {
    ".git", ".venv", ".hive_proof_env", ".tox", "venv", "env", "__pycache__",
    "site-packages", "dist-packages", "node_modules", "models",
    "modelzoo", "adapters", "checkpoints", "outputs", "output", "cache", ".cache",
    "appdata", "windows", "program files", "program files (x86)", "programdata",
    "system volume information", "$recycle.bin", "$windows.~tmp", "steamlibrary",
    "steamapps", "browser", "browsers", "user data", "profiles", ".ssh", ".aws",
    ".azure", ".docker", ".ollama", "secrets", "credentials", "credential",
    "passwords", "cookies", "mail", "email", "phone", "old phone", "movies",
    "music", "videos", "recordings", "screenshots", "pictures", "desktop storage",
}
REPO_MARKERS = {"readme.md", "agents.md", "pyproject.toml", "cargo.toml", "go.mod", "package.json"}
SOURCE_SUFFIXES = {
    ".py", ".pyi", ".rs", ".md", ".rst", ".toml", ".yaml", ".yml",
    ".ps1", ".psm1", ".sql", ".js", ".jsx", ".ts", ".tsx", ".go",
    ".java", ".c", ".h", ".cc", ".cpp", ".cs", ".rb", ".php", ".swift",
    ".kt", ".scala", ".vue", ".svelte", ".tf", ".proto",
}
ARCHIVE_COMPONENT_HINTS = (
    "archive", "backup", "old_project", "comprehensive_scan", "batch_",
)
SAMPLE_TIER_WEIGHTS = {"source_document": 0.70, "structured_text": 0.25,
                       "archive_or_log": 0.05}


def sample_tier(path: pathlib.Path) -> str:
    """Return a deterministic usefulness tier without excluding indexed content."""
    components = [part.casefold() for part in path.parts]
    if (path.suffix.casefold() == ".log"
            or any(any(hint in part for hint in ARCHIVE_COMPONENT_HINTS)
                   for part in components)):
        return "archive_or_log"
    if path.suffix.casefold() in SOURCE_SUFFIXES:
        return "source_document"
    return "structured_text"


def _sensitive_source_path(path: pathlib.Path) -> bool:
    return bool(SENSITIVE_FILE_NAME.fullmatch(path.name))


def _is_reparse(path: pathlib.Path) -> bool:
    try:
        st = path.lstat()
        return path.is_symlink() or bool(getattr(st, "st_file_attributes", 0) & 0x400)
    except OSError:
        return True


@lru_cache(maxsize=8)
def _walk_cached(roots: tuple[pathlib.Path, ...]) -> tuple[list[pathlib.Path], dict]:
    found: list[pathlib.Path] = []
    stats = {"roots": [], "directories": 0, "files": 0, "skipped_large": 0,
             "errors": 0, "truncated": False, "elapsed_seconds": 0.0}
    start = time.monotonic()
    for root in roots:
        if not root.exists() or _is_reparse(root):
            continue
        stats["roots"].append(str(root))
        root_start = time.monotonic()
        root_dirs = 0
        root_files = 0
        for current, dirs, files in os.walk(root, topdown=True, followlinks=False):
            stats["directories"] += 1
            root_dirs += 1
            if (root_dirs >= 1800 or root_files >= 6000 or time.monotonic() - root_start >= 2.5):
                stats["truncated"] = True
                break
            if (stats["directories"] >= MAX_DIRS or stats["files"] >= MAX_FILES
                    or time.monotonic() - start >= MAX_SECONDS):
                stats["truncated"] = True
                stats["elapsed_seconds"] = round(time.monotonic() - start, 2)
                return found, stats
            cur = pathlib.Path(current)
            dirs[:] = [d for d in dirs if d.casefold() not in SKIP_COMPONENTS
                       and not _is_reparse(cur / d)]
            for name in files:
                stats["files"] += 1
                root_files += 1
                if stats["files"] >= MAX_FILES or time.monotonic() - start >= MAX_SECONDS:
                    stats["truncated"] = True
                    stats["elapsed_seconds"] = round(time.monotonic() - start, 2)
                    return found, stats
                p = cur / name
                if p.suffix.casefold() not in TEXT_SUFFIXES or p.suffix.casefold() in SKIP_SUFFIXES:
                    continue
                if _is_reparse(p):
                    continue
                try:
                    if p.stat().st_size > MAX_FILE_BYTES:
                        stats["skipped_large"] += 1
                        continue
                    found.append(p)
                except OSError:
                    stats["errors"] += 1
    stats["elapsed_seconds"] = round(time.monotonic() - start, 2)
    return found, stats


def _walk(*, refresh: bool = False,
          roots: tuple[pathlib.Path, ...] | None = None) -> tuple[list[pathlib.Path], dict]:
    if refresh:
        _walk_cached.cache_clear()
    files, stats = _walk_cached(tuple(roots or SCAN_ROOTS))
    return files, dict(stats)


def inventory_pc_sources(*, refresh: bool = False, drive: str | None = None) -> dict:
    """Advance and report the persistent read-only index, optionally for one drive."""
    roots = mounted_drive_roots() or SCAN_ROOTS
    if drive is not None:
        letter = drive.rstrip(":\\/").upper()
        if letter not in {"C", "D", "E", "F", "L"}:
            raise ValueError("drive must be one of the configured mounted roots")
        roots = tuple(root for root in roots if root.drive.rstrip(":\\/").upper() == letter)
        if not roots:
            raise ValueError(f"Drive {letter}: is not currently mounted")
    stats = advance_index(PC_INDEX_DB, roots)
    files = indexed_paths(PC_INDEX_DB)
    if drive is not None:
        files = [path for path in files if path.drive.rstrip(":\\/").upper() == letter]
    groups: dict[str, dict] = {}
    for path in files:
        name = path.name.casefold()
        if name not in REPO_MARKERS and name not in {"objective.md", "current_task.json"}:
            continue
        parent = path.parent
        rec = groups.setdefault(str(parent), {"path": str(parent), "markers": [], "documents": []})
        rec["markers"].append(name)
        if name in {"readme.md", "agents.md", "objective.md", "current_task.json"}:
            rec["documents"].append(str(path))
    ranked = sorted(groups.values(), key=lambda g: (
        -sum(k in g["path"].casefold() for k in ("viv", "aios", "localcoder", "nn")),
        -len(g["markers"]), g["path"].casefold()))[:40]
    docs = []
    chars_left = 9_000
    for group in ranked:
        for raw_path in group["documents"][:3]:
            if len(docs) >= 24 or chars_left <= 0:
                break
            path = pathlib.Path(raw_path)
            try:
                body = path.read_text(encoding="utf-8", errors="replace")[:750]
            except OSError:
                continue
            body = re.sub(r"(?i)(api[_-]?key|access[_-]?token|password|secret|authorization)(\s*[:=]\s*)[^\s,;]+",
                          r"\1\2[REDACTED]", body)
            docs.append({"path": raw_path, "text": body})
            chars_left -= len(body)
    return {"mode": "read_only", "inventory": stats, "projects": ranked,
            "orientation_documents": docs}


def search_pc_content(query: str, *, exclude: set[tuple[str, int, str]] | None = None,
                       drive: str | None = None,
                       exclude_seen_only: bool = False) -> dict:
    """Search local source/docs for query terms and return hash-pinned snippets."""
    if not isinstance(query, str) or not query.strip() or len(query) > 400:
        raise ValueError("query must be 1–400 characters")
    terms = list(dict.fromkeys(re.findall(r"[\w-]{3,}", query.casefold())))[:12]
    if not terms:
        raise ValueError("query needs at least one term of three or more characters")
    if drive is not None:
        letter = drive.rstrip(":\\/").upper()
        if letter not in {"C", "D", "E", "F", "L"}:
            raise ValueError("drive must be one of the configured mounted roots")
        search_roots = tuple(root for root in SCAN_ROOTS
                             if root.drive.rstrip(":\\/").upper() == letter)
        if not search_roots:
            raise ValueError(f"Drive {letter}: is not currently mounted")
    else:
        search_roots = SCAN_ROOTS
    files, stats = _walk(roots=search_roots)
    hits = []
    search_start = time.monotonic()
    bytes_read = 0
    for path in files:
        if _sensitive_source_path(path):
            continue
        if time.monotonic() - search_start >= MAX_SECONDS or bytes_read >= 32_000_000:
            stats["truncated"] = True
            break
        try:
            raw = path.read_bytes()
            if b"\x00" in raw:
                continue
            text = raw.decode("utf-8", errors="replace")
            bytes_read += len(raw)
        except OSError:
            stats["errors"] += 1
            continue
        lines = text.splitlines()
        for index, line in enumerate(lines):
            low = line.casefold()
            score = sum(low.count(term) for term in terms)
            if score:
                snippet = line.strip()
                if SENSITIVE_VALUE.search(snippet):
                    continue
                snippet = re.sub(r"(?i)(api[_-]?key|access[_-]?token|password|secret|authorization)(\s*[:=]\s*)[^\s,;]+",
                                 r"\1\2[REDACTED]", snippet)
                if len(snippet) > MAX_SNIPPET_CHARS:
                    snippet = snippet[:MAX_SNIPPET_CHARS] + "…"
                source_hash = hashlib.sha256(raw).hexdigest()
                source_key = (str(path.resolve()).casefold(), index + 1, source_hash)
                hits.append({"score": score, "path": str(path), "line": index + 1,
                             "sha256": source_hash, "snippet": snippet,
                             "_previously_seen": source_key in (exclude or set())})
    # Prefer concise source lines that the learner can quote and cite. Large
    # minified JSON records otherwise dominate broad queries by repeating terms.
    hits.sort(key=lambda h: (h["_previously_seen"],
                             len(h["snippet"]) > LEARNING_SNIPPET_CHARS,
                             -h["score"], len(h["snippet"]),
                             h["path"].casefold(), h["line"]))
    if exclude_seen_only:
        hits = [hit for hit in hits if not hit["_previously_seen"]]
    matches = hits[:MAX_RESULTS]
    for hit in matches:
        hit.pop("_previously_seen", None)
    return {"mode": "read_only", "query": query, "terms": terms,
            "inventory": stats, "matches": matches,
            "truncated": stats["truncated"], "bytes_read": bytes_read}


def sample_pc_content(*, exclude: set[tuple[str, int, str]] | None = None,
                       count: int = MAX_RESULTS, seed: int | None = None,
                       roots: tuple[pathlib.Path, ...] | None = None,
                       drive: str | None = None) -> dict:
    """Monte Carlo sample concise lines across the discovered local corpus, read-only."""
    if not isinstance(count, int) or not 1 <= count <= 32:
        raise ValueError("count must be an integer from 1 to 32")
    seed = secrets.randbits(64) if seed is None else seed
    if not isinstance(seed, int):
        raise ValueError("seed must be an integer or None")
    rng = random.Random(seed)
    stats = advance_index(PC_INDEX_DB, roots if roots is not None else mounted_drive_roots() or SCAN_ROOTS)
    files = indexed_paths(PC_INDEX_DB)
    if drive is not None:
        requested_drive = drive.rstrip(":\\/").upper()
        if requested_drive not in {"C", "D", "E", "F", "L"}:
            raise ValueError("drive must be one of the configured mounted roots")
        files = [path for path in files if path.drive.rstrip(":\\/").upper() == requested_drive]
    candidate_tiers = {tier: [] for tier in SAMPLE_TIER_WEIGHTS}
    for path in files:
        if _sensitive_source_path(path):
            continue
        candidate_tiers[sample_tier(path)].append(path)
    for paths in candidate_tiers.values():
        rng.shuffle(paths)
    sampled_tier_counts = {tier: 0 for tier in SAMPLE_TIER_WEIGHTS}
    skipped_binary_files = 0
    skipped_sensitive_lines = 0
    matches = []
    bytes_read = 0
    sampled_files = 0
    started = time.monotonic()
    sample_truncated = False
    excluded = exclude or set()
    while any(candidate_tiers.values()):
        if len(matches) >= count or sampled_files >= 256:
            break
        if time.monotonic() - started >= MAX_SECONDS or bytes_read >= 32_000_000:
            sample_truncated = True
            break
        available = [tier for tier, paths in candidate_tiers.items() if paths]
        tier = rng.choices(available, weights=[SAMPLE_TIER_WEIGHTS[item]
                                               for item in available], k=1)[0]
        path = candidate_tiers[tier].pop()
        sampled_files += 1
        try:
            raw = path.read_bytes()
            bytes_read += len(raw)
            if b"\x00" in raw:
                skipped_binary_files += 1
                continue
            lines = raw.decode("utf-8", errors="replace").splitlines()
        except OSError:
            stats["errors"] += 1
            continue
        if not lines:
            continue
        # Randomize the starting point, then inspect each line at most once.
        start_at = rng.randrange(len(lines))
        source_hash = hashlib.sha256(raw).hexdigest()
        for offset in range(len(lines)):
            line_number = (start_at + offset) % len(lines) + 1
            snippet = lines[line_number - 1].strip()
            if not snippet or len(snippet) > LEARNING_SNIPPET_CHARS:
                continue
            if SENSITIVE_VALUE.search(snippet):
                skipped_sensitive_lines += 1
                continue
            source_key = (str(path.resolve()).casefold(), line_number, source_hash)
            if source_key in excluded:
                continue
            matches.append({"path": str(path), "line": line_number,
                            "sha256": source_hash, "snippet": snippet,
                            "sampling_tier": tier})
            sampled_tier_counts[tier] += 1
            break
    if len(matches) < count and sampled_files >= 256:
        sample_truncated = True
    return {"mode": "read_only_macro_random_sample", "sampling_seed": seed,
            "drive": requested_drive if drive is not None else None,
            "inventory": stats, "sampled_files": sampled_files,
            "sampling_tier_weights": dict(SAMPLE_TIER_WEIGHTS),
            "sampling_tier_counts": sampled_tier_counts,
            "skipped_binary_files": skipped_binary_files,
            "skipped_sensitive_lines": skipped_sensitive_lines,
            "bytes_read": bytes_read, "matches": matches,
            "truncated": sample_truncated,
            "index_complete": stats["index_complete"],
            "index_traversal_finished": stats["index_traversal_finished"]}
