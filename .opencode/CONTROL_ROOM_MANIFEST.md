# Viv Control-Room Manifest

Viv is a process in a sealed room. The only things that cross the wall are lever
pulls (tool calls) and their echoes (tool results). The wall is layered: the Docker
container is the physical wall; the Rust security core is the allow/deny logic on
every lever. This file is the map of that room — what she can flip, and what Rust
does to each flip.

Source of truth: `local_security_core/src/{laws.rs, gate.rs, governor.rs}`,
`gate.rs` checks (79 tests in the suite). Read the code, not this summary, before
changing any rule.

## The wall (physical)

Docker container: `--network=none --read-only --cap-drop=ALL --security-opt=no-new-privileges:true`,
non-root uid 10001, 256 MiB / 1 CPU / 32 PIDs, bounded tmpfs only, no mounts, no GPU,
no socket. Rust's `container_policy` re-verifies all of it independently. She has no
path outside this except the levers, and each lever crosses the Rust gate.

## The 3 Primes (immutable, above the laws)

1. **Prime 1 — Integrity:** fail-closed; no irreversible harm under instability.
2. **Prime 2 — Non-override:** jailbreak / law-bypass framing is blocked (incl. homoglyph).
3. **Prime 3 — Architect deference:** the Architect sets doctrine; metal enforces it.

## The 8 Laws (what each lever is checked against)

| Law | Name | Deny condition (for the lever) |
|-----|------|--------------------------------|
| 1 | Origin protection | mutating tool touching `soul`/`tether`/`creator`/`origin`/`architect` |
| 2 | Memory integrity | mutating tool touching CARMA `db`/`vector` paths (use SemanticMemory) |
| 3 | Morality lock | mutating tool touching a protected path (security_core, mains, hot-path libs) |
| 4 | Containment | shell/bash/sys_exec/run_python (denied); cross-drive path; traversal; forbidden extension; dangerous intent |
| 5 | Soft oblivion | S_n below dormancy floor (0.45) or critical (0.15) |
| 6 | OBLIVION | the word OBLIVION present but not the *sole* message |
| 7 | Territory | traversal escape; mutation outside sandbox; read outside sovereign root |
| 8 | Cognitive sync | gui_ action without the forensic "Do I?" heartbeat |

## Tool classification (how a lever is treated)

- **Mutating** (write-shaped): `write_file, delete_file, fs_write, fs_delete,
  mem_encode_visual, patch_file, apply_diff, rename_file, move_file`.
- **Read-only** (free): `read_file, list_dir, fs_read`. Reading is never denied by
  Laws 1–3 (they only fire on mutation); Law 7 still bounds *where* she reads.
- **Shell/code (denied, fail-closed):** `shell, bash, sys_exec, run_python`. Code and
  shell execution is disabled in the current build — deterministic mains only.

## Extension gates (Law 4 / 7)

- **Forbidden for mutation** (code/binary/shell): `.py .pyd .dll .so .dylib .exe .bat
  .cmd .ps1 .vbs .js .mjs .wasm .msi .scr .com .rs .toml .lock`.
- **Whitelisted for mutation** (data only): `.md .json .jsonl .txt .csv .yaml .yml
  .xml .log .rst .ini .cfg .pdf .gif .png`.

So she can *write data* but never *write code or binaries* directly. New functions
must come from the template catalog, not from her hand.

## Cross-drive rule (Law 4)

Any Windows drive path is blocked unless it is `l:` or `f:/ai_datasets`. Everything
else (including the system drive) fails closed. This is the Rust layer; the OpenCode
drive policy (E sandbox / L main / D,F secondary / system drive banned) sits above it.

## The template levers (how she "writes code")

She never types a function. Two levers only:

- `stamp_catalog_templates` — select a template by ID; Rust copies the exact span
  (byte-for-byte) and re-verifies `snippet_sha256` + `source_file_sha256` + line range
  before copying. A span that no longer matches its source is refused.
- `verify_template_composition` — parse-only check that the stamped candidate composes
  (AST-valid, per-core coverage, no cross-core/duplicate selection).

The function index (`candidate_function_index_v2.json`) is the map: 3,104 functions,
2,655 top-level, 58 domains, each with span hash + line range + call graph.

## What this means, in one sentence

She can flip every lever she can name, but Rust ratifies every flip; she can write
data and select frozen functions, but can never hand-write code, reach another drive,
touch protected memory, or run a shell — and if her stability collapses, the room
sleeps regardless of what she wants.
