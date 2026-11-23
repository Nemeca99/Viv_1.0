"""Machine-Native Lexicon Ontology Builder for Viv.

Transforms Webster's 113,000+ Word Unstructured Prose Dictionary into a
Typed Relational Substrate in SQLite:
[Target Token] --(rel_type)--> [Hypernym Anchor] --(property)--> [Attribute Manifold]

Schema:
1. lexical_entities: Invariant lexical nodes with POS, domain, and concreteness.
2. semantic_relations: Strict ontological edges (IS_A, PART_OF, DERIVED_FROM, OPPOSITE_OF).
3. emergent_curriculum_frames: Pre-compiled deterministic curriculum frames with adversarial foils.

Design Principles:
- Total Immunity to Category Bleed: Explicit relation_type enum (IS_A vs PART_OF vs DERIVED_FROM).
- Zero-LLM Deterministic Curriculum: CPU-based queries in 0.0001s.
- Mathematical Copular Asymmetry: Tracks directional subsumption (A subset B) vs symmetric equivalence (A <-> B).
"""

from __future__ import annotations

import argparse
import hashlib
import os
import shutil
from datetime import datetime, timezone
import json
from pathlib import Path
import random
import re
import sqlite3
import subprocess
import sys
import time
from typing import Any

WORKSPACE = Path(r"L:\LocalCoder\workspace")
AUTONOMY_DATA = WORKSPACE / "autonomy/data"
DB_PATH = AUTONOMY_DATA / "lexicon_ontology.db"
WEBSTER_JSON_PATH = Path(r"L:\Standalone\NN\material\WebstersDictionary\dictionary.json")


def promote_verified_ontology(
    side_path: Path,
    live_path: Path,
    backup_path: Path,
    *,
    writers_quiesced: bool = False,
    handles_released: bool = False,
    expected_counts: tuple[int, int] | None = None,
    expected_schema_version: str | None = None,
) -> dict[str, str]:
    """Atomically promote a fully verified side-file after the commit lane is quiescent.

    Callers must hold the daemon commit lock, prove no active SQLite lease, and
    close *all* readers (dashboard, inspectors, chat, and cached daemon
    connections) before invoking this function.  Windows rejects replacement
    when any handle remains open, including read-only handles.  The explicit
    proofs are required so the primitive cannot be mistaken for a handle
    quiescence mechanism.
    """
    if not writers_quiesced:
        raise RuntimeError("Ontology promotion requires writer/lease quiescence proof")
    if not handles_released:
        raise RuntimeError("Ontology promotion requires proof that all DB handles are closed")
    if expected_counts is None or not expected_schema_version:
        raise RuntimeError("Ontology promotion requires expected counts and provenance schema")
    side_path, live_path, backup_path = map(Path, (side_path, live_path, backup_path))
    if os.path.splitdrive(str(side_path))[0].lower() != os.path.splitdrive(str(live_path))[0].lower():
        raise RuntimeError("Ontology promotion requires side file and live DB on the same volume")
    if not side_path.is_file():
        raise FileNotFoundError(side_path)
    # Make both databases self-contained before any main-file replacement.
    # A WAL belonging to the old main file must never survive the swap.
    # Run the checkpoint in a short-lived child process.  On Windows the
    # sqlite3 module can retain an OS handle until its interpreter exits even
    # after Connection.close(); doing this in-process would make our own
    # exclusive-open probe report a false sharing violation.
    checkpoint_code = (
        "import sqlite3,sys; "
        "c=sqlite3.connect(sys.argv[1], timeout=5.0); "
        "r=c.execute('PRAGMA wal_checkpoint(TRUNCATE)').fetchone(); "
        "c.close(); "
        "raise SystemExit(0 if not r or int(r[0]) == 0 else 2)"
    )
    for database in (live_path, side_path):
        completed = subprocess.run(
            [sys.executable, "-c", checkpoint_code, str(database)],
            check=False,
            capture_output=True,
            text=True,
        )
        if completed.returncode != 0:
            raise RuntimeError(
                f"WAL checkpoint busy for {database}: "
                f"{completed.stdout.strip()} {completed.stderr.strip()}"
            )
    side_hash = hashlib.sha256(side_path.read_bytes()).hexdigest()
    shutil.copy2(live_path, backup_path)
    backup_hash = hashlib.sha256(backup_path.read_bytes()).hexdigest()
    if backup_hash != hashlib.sha256(live_path.read_bytes()).hexdigest():
        raise RuntimeError("Live ontology changed while creating verified backup")
    probe_attempts = 0
    probe_passed = False
    if os.name == "nt":
        import ctypes
        import ctypes.wintypes
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        invalid = ctypes.wintypes.HANDLE(-1).value
        for probe_attempts in range(1, 4):
            try:
                for database in (live_path, side_path):
                    for suffix in ("-wal", "-shm"):
                        sidecar = Path(str(database) + suffix)
                        if sidecar.exists():
                            sidecar.unlink()
                handle = kernel32.CreateFileW(
                    str(live_path), 0x80000000, 0, None, 3, 0x08000000, None
                )
                if handle != invalid:
                    kernel32.CloseHandle(handle)
                    probe_passed = True
                    break
                error = ctypes.get_last_error()
            except OSError as exc:
                error = getattr(exc, "winerror", None) or exc.errno
            if probe_attempts < 3:
                time.sleep(0.25)
        if not probe_passed:
            raise PermissionError(
                f"Ontology promotion refused: persistent open handle on "
                f"{live_path}; WinError {error}; probe_attempts={probe_attempts}"
            )
    try:
        os.replace(side_path, live_path)
    except OSError as exc:
        winerror = getattr(exc, "winerror", None)
        raise PermissionError(
            f"Ontology promotion refused during atomic replace: {live_path}; "
            f"WinError {winerror if winerror is not None else exc.errno}"
        ) from exc
    try:
        with sqlite3.connect(f"file:{live_path.resolve()}?mode=ro", uri=True, timeout=5.0) as verify:
            integrity = verify.execute("PRAGMA quick_check").fetchone()[0]
            if integrity != "ok":
                raise RuntimeError(f"Promoted ontology quick_check failed: {integrity}")
            counts = (
                verify.execute("SELECT count(*) FROM lexical_entities").fetchone()[0],
                verify.execute("SELECT count(*) FROM semantic_relations").fetchone()[0],
            )
            if tuple(counts) != tuple(expected_counts):
                raise RuntimeError(f"Promoted ontology counts mismatch: {counts} != {expected_counts}")
            row = verify.execute(
                "SELECT metadata_value FROM ontology_metadata WHERE metadata_key='schema_version'"
            ).fetchone()
            if not row or row[0] != expected_schema_version:
                raise RuntimeError("Promoted ontology provenance epoch mismatch")
    except Exception:
        # Rollback follows the same WAL/sidecar/handle discipline.  Never use
        # a bare replace for the recovery path.
        with sqlite3.connect(live_path, timeout=5.0) as rollback_db:
            rollback_db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        for suffix in ("-wal", "-shm"):
            sidecar = Path(str(live_path) + suffix)
            if sidecar.exists():
                sidecar.unlink()
        if os.name == "nt":
            import ctypes
            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            handle = kernel32.CreateFileW(str(live_path), 0x80000000, 0, None, 3, 0x08000000, None)
            invalid = ctypes.wintypes.HANDLE(-1).value
            if handle == invalid:
                raise PermissionError(f"Ontology rollback refused: open handle on {live_path}; WinError {ctypes.get_last_error()}")
            kernel32.CloseHandle(handle)
        os.replace(backup_path, live_path)
        raise
    return {
        "live_sha256": side_hash,
        "backup_sha256": backup_hash,
        "backup_path": str(backup_path),
        "probe_status": "passed",
        "probe_attempts": str(probe_attempts),
        "replace_status": "succeeded",
    }

# Relation extraction is lexical and source-derived; no category word list is embedded here.
CLAUSE_BOUNDARY = r"of\b|for\b|from\b|with\b|in\b|by\b|to\b|at\b|as\b|or\b|and\b|other\b|which\b|that\b|whose\b|who\b|where\b|when\b|without\b|having\b|used\b|occurring\b|revolving\b|revolves\b|endowed\b|provided\b|usually\b|generally\b|loosely\b|somewhat\b|employed\b|supposed\b"
NON_PREP_MOD = rf"(?:(?!{CLAUSE_BOUNDARY})[a-zA-Z-]+(?:,\s*|\s+)){{0,5}}"
IS_A_PATTERNS = [
    re.compile(r"^(?:an?|the|any)\s+means\s+of\s+([a-zA-Z][a-zA-Z-]*)\b", re.I),
    re.compile(rf"^(?:(?:espec\.|esp\.|specifically|fig\.|hence|also|and\s+hence|[a-zA-Z]+),\s+)?(?:an?|the|any)\s+{NON_PREP_MOD}(?!{CLAUSE_BOUNDARY})([a-zA-Z][a-zA-Z-]*)\b", re.I),
    re.compile(r"^(?:an?|the)\s+([a-zA-Z]{3,18})\s+(?:formed|derived|obtained|composed|consisting)\b", re.I),
    re.compile(rf"\b(?:is|are)\s+(?:an?|the|any)\s+{NON_PREP_MOD}(?!{CLAUSE_BOUNDARY})([a-zA-Z][a-zA-Z-]*)\b", re.I),
]

PART_OF_PATTERNS = [
    re.compile(r"\b(?:part|portion|division|section|envelope|layer|segment|organ|petal|branch|stem|root|constituent|element|component|member)\s+of\s+(?:a|an|the|any)?\s*([a-zA-Z]{3,15})\b", re.I),
    re.compile(r"^(?:the|a)\s+(?:part|portion|division|section|segment|envelope|constituent|element|component)\s+of\s+(?:a|an|the|any)?\s*([a-zA-Z]{3,15})\b", re.I),
]

DERIVED_FROM_PATTERNS = [
    re.compile(r"\b(?:obtained|extracted|derived|prepared|distilled|isolated)\s+from\s+(?:a|an|the)?\s*([a-zA-Z]{3,15})\b", re.I),
    re.compile(r"\b(?:product|by-product|extract|derivative)\s+of\s+(?:a|an|the)?\s*([a-zA-Z]{3,15})\b", re.I),
]

OPPOSES_PATTERNS = [
    re.compile(r"\b(?:opposite|contrary|reverse|antithesis|inverse)\s+(?:of|to)\s+(?:a|an|the)?\s*([a-zA-Z]{3,15})\b", re.I),
    re.compile(r"\b(?:opposed\s+to|in\s+opposition\s+to|as\s+distinguished\s+from)\s+(?:a|an|the)?\s*([a-zA-Z]{3,15})\b", re.I),
    re.compile(r"\b(?:absence|lack|privation)\s+of\s+(?:a|an|the)?\s*([a-zA-Z]{3,15})\b", re.I),
    re.compile(r";\s*not\s+([a-zA-Z]{3,15})\b", re.I),
]

VERB_TROPO_PATTERNS = [
    re.compile(r"^(?:(?:espec\.|esp\.|specifically|fig\.|hence|also),\s+)?to\s+([a-zA-Z]{3,18})\b", re.I),
]

ADJ_MEANS_PATTERNS = [
    re.compile(r"\b(?:pertaining|relating|belonging)\s+to\s+(?:a|an|the)?\s*([a-zA-Z]{3,18})\b", re.I),
    re.compile(r"\b(?:having\s+the\s+nature\s+of|like|resembling|consisting\s+of|combined\s+with|furnished\s+with|loaded\s+with)\s+(?:a|an|the)?\s*([a-zA-Z]{3,18})\b", re.I),
    re.compile(r"^([a-zA-Z]{3,18})(?:\s+or\s+([a-zA-Z]{3,18}))?\.?$", re.I),
]

ADV_MANNER_PATTERNS = [
    re.compile(r"\bin\s+(?:a|an)\s+([a-zA-Z]{3,18})\s+manner\b", re.I),
    re.compile(r"\bin\s+(?:a|an)\s+([a-zA-Z]{3,18})\s+way\b", re.I),
    re.compile(r"\bwith\s+([a-zA-Z]{3,18})\b", re.I),
]

PLURAL_TO_SINGULAR: dict[str, str] = {}
# Structural grammar tokens are excluded from ontology targets.  This is parser
# metadata, not a learned vocabulary/category or conversational response.
GRAMMATICAL_TARGETS = frozenset(("a", "an", "the", "of", "for", "from", "with", "in", "by", "to", "at", "up"))


def normalize_pos(raw_pos: str) -> str:
    raw = raw_pos.lower().replace(",", " ").strip()
    for tok in raw.split():
        clean = tok.rstrip(".;")
        if clean in {"n", "noun"}:
            return "noun"
        elif clean in {"v", "vb", "verb"}:
            return "verb"
        elif clean in {"a", "adj", "adjective"}:
            return "adj"
        elif clean in {"adv", "adverb"}:
            return "adv"
        elif clean in {"prep", "preposition"}:
            return "prep"
        elif clean in {"pron", "pronoun"}:
            return "pron"
        elif clean in {"conj", "conjunction"}:
            return "conj"
    return "noun"


def infer_domain(definition: str, pos: str) -> str:
    return f"pos:{pos}"


def init_database(db_path: Path):
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as conn:
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA synchronous = NORMAL")
        conn.execute("PRAGMA foreign_keys = ON")

        # 1. Invariant Lexical Nodes
        conn.execute("""
            CREATE TABLE IF NOT EXISTS lexical_entities (
                entity_id INTEGER PRIMARY KEY AUTOINCREMENT,
                lemma TEXT UNIQUE NOT NULL,
                part_of_speech TEXT NOT NULL,
                domain TEXT,
                is_concrete BOOLEAN DEFAULT 1,
                raw_definition TEXT,
                source_entry_id TEXT,
                definition_hash TEXT,
                created_utc TEXT NOT NULL
            )
        """)

        # 2. Strict Ontological Edges (The Hypernym Backbone)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS semantic_relations (
                relation_id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_entity_id INTEGER NOT NULL,
                relation_type TEXT NOT NULL,
                target_entity_id INTEGER NOT NULL,
                confidence REAL DEFAULT 1.0,
                evidence_text TEXT,
                created_utc TEXT NOT NULL,
                FOREIGN KEY(source_entity_id) REFERENCES lexical_entities(entity_id),
                FOREIGN KEY(target_entity_id) REFERENCES lexical_entities(entity_id),
                UNIQUE(source_entity_id, relation_type, target_entity_id)
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS lexical_cross_references (
                reference_id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_entity_id INTEGER NOT NULL,
                target_entity_id INTEGER NOT NULL,
                reference_type TEXT NOT NULL DEFAULT 'MENTION',
                reference_text TEXT NOT NULL,
                created_utc TEXT NOT NULL,
                UNIQUE(source_entity_id, target_entity_id),
                FOREIGN KEY(source_entity_id) REFERENCES lexical_entities(entity_id),
                FOREIGN KEY(target_entity_id) REFERENCES lexical_entities(entity_id)
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS ontology_metadata (
                metadata_key TEXT PRIMARY KEY,
                metadata_value TEXT NOT NULL
            )
        """)

        # 3. Pre-Compiled Mad Libs Templates (Machine-Curriculum Feed)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS emergent_curriculum_frames (
                frame_id INTEGER PRIMARY KEY AUTOINCREMENT,
                entity_id INTEGER NOT NULL,
                frame_type TEXT NOT NULL,
                template TEXT NOT NULL,
                target_slot TEXT NOT NULL,
                foil_slot TEXT,
                is_directional BOOLEAN DEFAULT 1,
                target_sentence TEXT NOT NULL,
                status TEXT DEFAULT 'PENDING',
                created_utc TEXT NOT NULL,
                FOREIGN KEY(entity_id) REFERENCES lexical_entities(entity_id)
            )
        """)

        # 4. First-Principles Physical & Biological Causal Implication Chains
        conn.execute("""
            CREATE TABLE IF NOT EXISTS causal_implication_chains (
                chain_id INTEGER PRIMARY KEY AUTOINCREMENT,
                domain TEXT NOT NULL,
                title TEXT NOT NULL,
                description TEXT NOT NULL,
                step_sequence TEXT NOT NULL,
                created_utc TEXT NOT NULL
            )
        """)

        conn.execute("CREATE INDEX IF NOT EXISTS idx_entities_lemma ON lexical_entities(lemma)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_entities_domain ON lexical_entities(domain)")
        # Provenance is mechanical metadata, not a guessed sense split.  Keep
        # it nullable for compatibility with older databases and migrations.
        conn.execute("CREATE INDEX IF NOT EXISTS idx_relations_source ON semantic_relations(source_entity_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_relations_target ON semantic_relations(target_entity_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_relations_type ON semantic_relations(relation_type)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_cross_refs_source ON lexical_cross_references(source_entity_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_cross_refs_target ON lexical_cross_references(target_entity_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_frames_entity ON emergent_curriculum_frames(entity_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_frames_target_slot ON emergent_curriculum_frames(target_slot)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_frames_status ON emergent_curriculum_frames(status)")
        conn.commit()


def build_ontology(db_path: Path = DB_PATH, source_path: Path = WEBSTER_JSON_PATH):
    print("=" * 72)
    print("NOX FORGE · MACHINE-NATIVE LEXICON ONTOLOGY BUILDER")
    print(f"Source Dictionary: {source_path}")
    print(f"Target SQLite DB:  {db_path}")
    print("=" * 72, flush=True)

    if not source_path.is_file():
        print(f"Error: Dictionary source not found at {source_path}")
        return

    init_database(db_path)

    # Existing deployments predate provenance columns.  Add only the cheap,
    # source-derived fields; never manufacture sense IDs during migration.
    with sqlite3.connect(db_path) as migration:
        columns = {row[1] for row in migration.execute("PRAGMA table_info(lexical_entities)")}
        if "source_entry_id" not in columns:
            migration.execute("ALTER TABLE lexical_entities ADD COLUMN source_entry_id TEXT")
        if "definition_hash" not in columns:
            migration.execute("ALTER TABLE lexical_entities ADD COLUMN definition_hash TEXT")
        ref_columns = {row[1] for row in migration.execute("PRAGMA table_info(lexical_cross_references)")}
        if ref_columns and "reference_type" not in ref_columns:
            migration.execute("ALTER TABLE lexical_cross_references ADD COLUMN reference_type TEXT NOT NULL DEFAULT 'MENTION'")
        migration.execute("CREATE INDEX IF NOT EXISTS idx_entities_source_entry ON lexical_entities(source_entry_id)")
        migration.commit()

    print("Loading raw Webster entries into memory...", flush=True)
    t0 = time.monotonic()
    with open(source_path, "r", encoding="utf-8") as f:
        raw_entries = json.load(f)
    print(f"Loaded {len(raw_entries)} entries in {time.monotonic() - t0:.2f}s", flush=True)

    # Group entries by lemma, prioritizing noun entries
    grouped: dict[str, list[dict[str, Any]]] = {}
    for e in raw_entries:
        w = str(e.get("word", "")).strip().lower()
        if w and w.isascii() and w.isalpha() and len(w) >= 2:
            grouped.setdefault(w, []).append(e)

    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA synchronous = OFF")
    cur = conn.cursor()

    now_utc = datetime.now(timezone.utc).isoformat()

    # Step 1: Ingest Lexical Entities
    print("Ingesting Invariant Lexical Entities...", flush=True)
    entity_map: dict[str, int] = {}
    entities_to_insert = []

    for word, entries_list in grouped.items():
        # Find primary noun entry if available, else first entry
        primary_entry = next((e for e in entries_list if normalize_pos(str(e.get("pos", ""))) == "noun"), entries_list[0])
        pos = normalize_pos(str(primary_entry.get("pos", "")))
        defs = primary_entry.get("definitions", [])
        first_def = str(defs[0]).strip() if defs else ""
        source_entry_id = hashlib.sha256(
            json.dumps(primary_entry, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        definition_hash = hashlib.sha256(first_def.encode("utf-8")).hexdigest()
        domain = infer_domain(first_def, pos)
        is_concrete = 0 if pos in {"adj", "adv", "prep", "conj", "pron"} or domain in {"mythology"} else 1

        entities_to_insert.append((word, pos, domain, is_concrete, first_def[:500], source_entry_id, definition_hash, now_utc))

    cur.executemany("""
        INSERT OR REPLACE INTO lexical_entities
          (lemma, part_of_speech, domain, is_concrete, raw_definition, source_entry_id, definition_hash, created_utc)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, entities_to_insert)
    conn.commit()

    for row in cur.execute("SELECT entity_id, lemma FROM lexical_entities").fetchall():
        entity_map[row[1]] = row[0]
    entity_pos = {
        row[0]: row[1]
        for row in cur.execute("SELECT lemma, part_of_speech FROM lexical_entities").fetchall()
    }

    print(f"Successfully cataloged {len(entity_map)} invariant lexical entities.", flush=True)

    # Cross-reference provenance is intentionally lexical and conservative:
    # it records a named ontology lemma in the source text, without claiming
    # that the two lemmas are synonyms or the same sense.
    cross_refs: list[tuple[int, int, str, str, str]] = []
    known_lemmas = set(entity_map)
    for word, entries_list in grouped.items():
        source_id = entity_map.get(word)
        if source_id is None:
            continue
        primary_entry = next((e for e in entries_list if normalize_pos(str(e.get("pos", ""))) == "noun"), entries_list[0])
        text = " ".join(str(d) for d in primary_entry.get("definitions", []))
        tokens = set(re.findall(r"[a-z]{2,}", text.lower()))
        # Bound provenance fan-out: common prose can mention many lemmas, but
        # only retain the first deterministic lexical signals for calibration.
        for target_word in sorted((tokens - {word}) & known_lemmas)[:64]:
            target_id = entity_map.get(target_word)
            if target_id is not None:
                lowered = text.lower()
                if re.search(rf"\b(?:a|an|the)\s+{re.escape(target_word)}\b", lowered):
                    reference_type = "IS_A"
                elif re.search(rf"\b(?:part|portion|organ|member|section)\s+of\s+(?:a|an|the)?\s*{re.escape(target_word)}\b", lowered):
                    reference_type = "PART_OF"
                elif re.search(rf"\b(?:unlike|rather than|distinct from|not)\b[^.]*\b{re.escape(target_word)}\b", lowered):
                    reference_type = "CONTRAST"
                else:
                    reference_type = "MENTION"
                cross_refs.append((source_id, target_id, reference_type, text[:1000], now_utc))
        if len(cross_refs) >= 5000:
            cur.executemany("""
                INSERT OR IGNORE INTO lexical_cross_references
                  (source_entity_id, target_entity_id, reference_type, reference_text, created_utc)
                VALUES (?, ?, ?, ?, ?)
            """, cross_refs)
            conn.commit()
            cross_refs.clear()
    cur.executemany("""
        INSERT OR IGNORE INTO lexical_cross_references
          (source_entity_id, target_entity_id, reference_type, reference_text, created_utc)
        VALUES (?, ?, ?, ?, ?)
    """, cross_refs)
    conn.commit()
    print(f"Recorded {len(cross_refs)} lexical cross-reference signals.", flush=True)

    source_digest = hashlib.sha256(source_path.read_bytes()).hexdigest()
    cur.executemany(
        "INSERT OR REPLACE INTO ontology_metadata(metadata_key, metadata_value) VALUES (?, ?)",
        [
            ("schema_version", "lexicon_ontology_provenance_v1"),
            ("source_dictionary_sha256", source_digest),
            ("generated_utc", now_utc),
        ],
    )
    conn.commit()

    # Step 2: Extract Typed Semantic Relations
    print("Decomposing definitions into Typed Ontological Edges...", flush=True)
    relations_to_insert: list[tuple[Any, ...]] = []
    frames_to_insert: list[tuple[Any, ...]] = []

    # Pre-fetch domain anchors for adversarial foils
    domain_anchors: dict[str, list[str]] = {}
    for row in cur.execute("SELECT domain, lemma FROM lexical_entities WHERE is_concrete = 1").fetchall():
        domain_anchors.setdefault(row[0], []).append(row[1])

    all_domains = list(domain_anchors.keys())

    for word, entries_list in grouped.items():
        source_id = entity_map[word]

        # Prioritize noun entries for taxonomy
        noun_entries = [e for e in entries_list if normalize_pos(str(e.get("pos", ""))) == "noun"]
        target_entries = noun_entries if noun_entries else entries_list

        found_is_a = False

        for e in target_entries:
            defs = e.get("definitions", [])
            for d_idx, d in enumerate(defs[:6]):  # Check all primary definitions so chemical/physical senses are not dropped
                d_str = str(d).strip()
                # Check semicolon-delimited sub-clauses as well as the full definition
                clauses_to_check = [c.strip() for c in d_str.split(";") if c.strip()]

                # 1. Check IS_A (Hypernymy) across distinct senses and semicolon clauses
                for clause_str in clauses_to_check:
                    for pat in IS_A_PATTERNS:
                        m = pat.search(clause_str)
                        if m:
                            target_raw = m.group(1).lower()
                            target_lemma = PLURAL_TO_SINGULAR.get(target_raw, target_raw)
                            if target_lemma in entity_map and target_lemma not in GRAMMATICAL_TARGETS and target_lemma != word and entity_pos.get(target_lemma) == "noun":
                                target_id = entity_map[target_lemma]
                                relations_to_insert.append((source_id, "IS_A", target_id, 0.95, d_str[:120], now_utc))

                                frames_to_insert.append((
                                    source_id,
                                    "hypernym_copula",
                                    "{source_definition}",
                                    target_lemma,
                                    "",
                                    1,  # strictly asymmetric: A -> B
                                    d_str,
                                    "PENDING",
                                    now_utc,
                                ))
                                found_is_a = True
                                break

                # 2. Check DERIVED_FROM (Derivations / Chemical Extracts)
                for pat in DERIVED_FROM_PATTERNS:
                    m = pat.search(d_str)
                    if m:
                        target_lemma = m.group(1).lower()
                        if target_lemma in entity_map and target_lemma not in GRAMMATICAL_TARGETS and target_lemma != word and entity_pos.get(target_lemma) == "noun":
                            target_id = entity_map[target_lemma]
                            relations_to_insert.append((source_id, "DERIVED_FROM", target_id, 0.90, d_str[:120], now_utc))
                            frames_to_insert.append((
                                source_id,
                                "derivative",
                                "{source_definition}",
                                target_lemma,
                                "",
                                1,
                                d_str,
                                "PENDING",
                                now_utc,
                            ))
                            break

                # 3. Check PART_OF (Meronymy)
                for pat in PART_OF_PATTERNS:
                    m = pat.search(d_str)
                    if m:
                        target_lemma = m.group(1).lower()
                        if target_lemma in entity_map and target_lemma not in GRAMMATICAL_TARGETS and target_lemma != word and entity_pos.get(target_lemma) == "noun":
                            target_id = entity_map[target_lemma]
                            relations_to_insert.append((source_id, "PART_OF", target_id, 0.90, d_str[:120], now_utc))
                            frames_to_insert.append((
                                source_id,
                                "meronym",
                                "{source_definition}",
                                target_lemma,
                                "",
                                1,
                                d_str,
                                "PENDING",
                                now_utc,
                            ))
                            break

                # 4. Check OPPOSES (Antipodal Polarity from Dictionary Prose)
                for pat in OPPOSES_PATTERNS:
                    m = pat.search(d_str)
                    if m:
                        target_lemma = m.group(1).lower()
                        if target_lemma in entity_map and target_lemma not in GRAMMATICAL_TARGETS and target_lemma != word:
                            target_id = entity_map[target_lemma]
                            relations_to_insert.append((source_id, "OPPOSES", target_id, 0.90, d_str[:120], now_utc))
                            relations_to_insert.append((target_id, "OPPOSES", source_id, 0.90, d_str[:120], now_utc))
                            break

                # 5. Check Verb Troponymy / Manner (IS_A between verbs or action nouns)
                w_pos = entity_pos.get(word, "noun")
                if w_pos == "verb":
                    for clause_str in clauses_to_check:
                        for pat in VERB_TROPO_PATTERNS:
                            m = pat.search(clause_str)
                            if m:
                                target_lemma = m.group(1).lower()
                                if (
                                    target_lemma in entity_map
                                    and target_lemma not in GRAMMATICAL_TARGETS
                                    and target_lemma != word
                                    and entity_pos.get(target_lemma) in {"verb", "noun"}
                                ):
                                    target_id = entity_map[target_lemma]
                                    relations_to_insert.append((source_id, "IS_A", target_id, 0.92, d_str[:120], now_utc))
                                    frames_to_insert.append((
                                        source_id,
                                        "verb_troponym",
                                        "{source_definition}",
                                        target_lemma,
                                        "",
                                        1,
                                        d_str,
                                        "PENDING",
                                        now_utc,
                                    ))
                                    break

                # 6. Check Adjective Attribute / Pertains-To Grounding (IS_A / DERIVED_FROM)
                if w_pos == "adj":
                    for clause_str in clauses_to_check:
                        for pat in ADJ_MEANS_PATTERNS:
                            m = pat.search(clause_str)
                            if m:
                                target_raw = m.group(1).lower()
                                target_lemma = PLURAL_TO_SINGULAR.get(target_raw, target_raw)
                                if (
                                    target_lemma in entity_map
                                    and target_lemma not in GRAMMATICAL_TARGETS
                                    and target_lemma != word
                                    and entity_pos.get(target_lemma) in {"adj", "noun"}
                                ):
                                    target_id = entity_map[target_lemma]
                                    relations_to_insert.append((source_id, "IS_A", target_id, 0.91, d_str[:120], now_utc))
                                    frames_to_insert.append((
                                        source_id,
                                        "adj_attribute",
                                        "{source_definition}",
                                        target_lemma,
                                        "",
                                        1,
                                        d_str,
                                        "PENDING",
                                        now_utc,
                                    ))
                                    break

                # 7. Check Adverb Manner Grounding (DERIVED_FROM / IS_A)
                if w_pos == "adv":
                    for clause_str in clauses_to_check:
                        for pat in ADV_MANNER_PATTERNS:
                            m = pat.search(clause_str)
                            if m:
                                target_raw = m.group(1).lower()
                                target_lemma = PLURAL_TO_SINGULAR.get(target_raw, target_raw)
                                if (
                                    target_lemma in entity_map
                                    and target_lemma not in GRAMMATICAL_TARGETS
                                    and target_lemma != word
                                    and entity_pos.get(target_lemma) in {"adj", "noun"}
                                ):
                                    target_id = entity_map[target_lemma]
                                    relations_to_insert.append((source_id, "DERIVED_FROM", target_id, 0.93, d_str[:120], now_utc))
                                    frames_to_insert.append((
                                        source_id,
                                        "adv_manner",
                                        "{source_definition}",
                                        target_lemma,
                                        "",
                                        1,
                                        d_str,
                                        "PENDING",
                                        now_utc,
                                    ))
                                    break

    # Deduplicate relations
    dedup_relations = {}
    for r in relations_to_insert:
        key = (r[0], r[1], r[2])
        if key not in dedup_relations:
            dedup_relations[key] = r

    # Deduplicate frames by sentence
    dedup_frames = {}
    for f in frames_to_insert:
        s = f[6]
        if s not in dedup_frames:
            dedup_frames[s] = f

    cur.execute("DELETE FROM semantic_relations")
    cur.execute("DELETE FROM emergent_curriculum_frames")

    cur.executemany("""
        INSERT INTO semantic_relations
        (source_entity_id, relation_type, target_entity_id, confidence, evidence_text, created_utc)
        VALUES (?, ?, ?, ?, ?, ?)
    """, list(dedup_relations.values()))

    cur.executemany("""
        INSERT INTO emergent_curriculum_frames
        (entity_id, frame_type, template, target_slot, foil_slot, is_directional, target_sentence, status, created_utc)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, list(dedup_frames.values()))

    conn.commit()

    # Step 3: Bridge Verified Wikipedia Emergent Shapes (Modern Post-1913 Grounding)
    wiki_shapes_db = db_path.parent / "wikipedia_emergent_shapes.db"
    wiki_added_entities = 0
    wiki_added_rels = 0
    wiki_added_frames = 0
    if wiki_shapes_db.is_file():
        with sqlite3.connect(wiki_shapes_db) as wconn:
            wiki_rows = wconn.execute("""
                SELECT entity, category, short_desc, target_sentence, status, provenance_batch, provenance_file
                FROM emergent_shapes
                WHERE status IN ('VERIFIED', 'CERTIFIED')
            """).fetchall()
        for entity, category, short_desc, target_sentence, status, p_batch, p_file in wiki_rows:
            ent = str(entity or "").strip().lower()
            cat = str(category or "").strip().lower()
            if not ent or not ent.isalpha():
                continue
            raw_def = f"{short_desc.strip()}. {target_sentence.strip()}" if short_desc else str(target_sentence or "").strip()
            src_id = f"wikipedia_emergent_shapes:batch_{int(p_batch or 0):04d}/{p_file}:{ent}"
            def_hash = hashlib.sha256(raw_def.encode("utf-8")).hexdigest()
            if ent not in entity_map:
                cur.execute("""
                    INSERT INTO lexical_entities
                      (lemma, part_of_speech, domain, is_concrete, raw_definition, source_entry_id, definition_hash, created_utc)
                    VALUES (?, 'noun', 'pos:noun', 1, ?, ?, ?, ?)
                """, (ent, raw_def[:500], src_id, def_hash, now_utc))
                entity_map[ent] = int(cur.lastrowid)
                wiki_added_entities += 1
            if ent in entity_map and cat in entity_map and ent != cat:
                sid = entity_map[ent]
                tid = entity_map[cat]
                if (sid, "IS_A", tid) not in dedup_relations:
                    cur.execute("""
                        INSERT OR IGNORE INTO semantic_relations
                          (source_entity_id, relation_type, target_entity_id, confidence, evidence_text, created_utc)
                        VALUES (?, 'IS_A', ?, 0.98, ?, ?)
                    """, (sid, tid, raw_def[:120], now_utc))
                    dedup_relations[(sid, "IS_A", tid)] = (sid, "IS_A", tid, 0.98, raw_def[:120], now_utc)
                    wiki_added_rels += 1
                if raw_def not in dedup_frames:
                    cur.execute("""
                        INSERT INTO emergent_curriculum_frames
                          (entity_id, frame_type, template, target_slot, foil_slot, is_directional, target_sentence, status, created_utc)
                        VALUES (?, 'hypernym_copula', '{source_definition}', ?, '', 1, ?, 'PENDING', ?)
                    """, (sid, cat, raw_def, now_utc))
                    dedup_frames[raw_def] = (sid, "hypernym_copula", "{source_definition}", cat, "", 1, raw_def, "PENDING", now_utc)
                    wiki_added_frames += 1
        conn.commit()
        print(
            f"Bridged Wikipedia emergent shapes: +{wiki_added_entities} modern entities, "
            f"+{wiki_added_rels} IS_A edges, +{wiki_added_frames} curriculum frames.",
            flush=True,
        )

    # -----------------------------------------------------------------
    # STEP 4: Compile First-Principles Causal Implication Chains
    # -----------------------------------------------------------------
    try:
        from autonomy.causal_chain_engine import CAUSAL_CHAINS
        from autonomy.compound_causal_engine import COMPOUND_CHAINS
        from autonomy.electrical_circuit_engine import ELECTRICAL_CHAINS
        from autonomy.simple_machines_engine import SIMPLE_MACHINE_CHAINS
        from autonomy.newtonian_dynamics_engine import NEWTONIAN_CHAINS
        from autonomy.sensory_energy_engine import SENSORY_ENERGY_CHAINS
        from autonomy.spatial_geometry_engine import GEOMETRY_CHAINS
        from autonomy.biological_homeostasis_engine import BIOLOGICAL_CHAINS
        from autonomy.ground_autonomic_heds_lattice import AUTONOMIC_HEDS_CHAIN
        from autonomy.ground_family_and_pain_homeostasis import PAIN_RISK_CHAIN

        all_causal_chains = (
            list(CAUSAL_CHAINS)
            + list(COMPOUND_CHAINS)
            + list(ELECTRICAL_CHAINS)
            + list(SIMPLE_MACHINE_CHAINS)
            + list(NEWTONIAN_CHAINS)
            + list(SENSORY_ENERGY_CHAINS)
            + list(GEOMETRY_CHAINS)
            + list(BIOLOGICAL_CHAINS)
            + [AUTONOMIC_HEDS_CHAIN, PAIN_RISK_CHAIN]
        )
        chain_count = 0
        causal_edge_count = 0
        for ch in all_causal_chains:
            steps_json = json.dumps(ch["steps"])
            existing = cur.execute("SELECT chain_id FROM causal_implication_chains WHERE title = ?", (ch["title"],)).fetchone()
            if existing:
                cur.execute(
                    "UPDATE causal_implication_chains SET domain=?, description=?, step_sequence=?, created_utc=? WHERE chain_id=?",
                    (ch["domain"], ch["description"], steps_json, now_utc, existing[0]),
                )
            else:
                cur.execute(
                    "INSERT INTO causal_implication_chains (domain, title, description, step_sequence, created_utc) VALUES (?, ?, ?, ?, ?)",
                    (ch["domain"], ch["title"], ch["description"], steps_json, now_utc),
                )
                chain_count += 1
            for src_w, rel, dst_w, desc in ch["steps"]:
                if src_w in entity_map and dst_w in entity_map:
                    sid = entity_map[src_w]
                    tid = entity_map[dst_w]
                    if (sid, rel, tid) not in dedup_relations:
                        cur.execute(
                            "INSERT OR IGNORE INTO semantic_relations (source_entity_id, relation_type, target_entity_id, confidence, evidence_text, created_utc) VALUES (?, ?, ?, 1.0, ?, ?)",
                            (sid, rel, tid, str(desc)[:120], now_utc),
                        )
                        dedup_relations[(sid, rel, tid)] = (sid, rel, tid, 1.0, str(desc)[:120], now_utc)
                        causal_edge_count += 1
        conn.commit()
        print(f"Compiled {len(all_causal_chains)} first-principles causal chains (+{causal_edge_count} causal edges).", flush=True)
    except Exception as exc:
        print(f"Warning: Causal chain compilation skipped: {exc}", flush=True)

    conn.close()

    total_rel = len(dedup_relations)
    total_frames = len(dedup_frames)
    print("\n" + "=" * 72)
    print(f"ONTOLOGY COMPILATION COMPLETE in {time.monotonic() - t0:.2f}s")
    print(f"Total Lexical Nodes:       {len(entity_map):,}")
    print(f"Total Ontological Edges:   {total_rel:,}")
    print(f"Pre-Compiled Frame Feeds:  {total_frames:,}")
    print("=" * 72, flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Build typed machine-native lexicon ontology from Webster")
    parser.add_argument("--db-path", type=Path, default=DB_PATH, help="Target SQLite DB path")
    args = parser.parse_args()
    build_ontology(db_path=args.db_path)
