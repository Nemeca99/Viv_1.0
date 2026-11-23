"""CPU tool-authority gate: GPU may request tools; CPU approves and executes.

Doctrine:
  - GPU mouth never executes tools or mints authority.
  - GPU (or operator-via-mouth) may submit a structured tool request.
  - CPU reviews allowlist + inputs; on approve, CPU runs the tool and returns
    the result for mouth render.
  - Example: GPU requests calculator/uml_invoke with expression → CPU checks →
    CPU evaluates → answer returned on the evidence path.

Seals (r2):
  - ``cpu_mint_seal`` is server-side only (mint_cpu_tool_request). Forged
    ``cpu_minted=true`` without a matching mint record fails closed.
  - ``cpu_approval_seal`` is single-use and bound to tool+expression+source.
  - Consumed ``request_id`` values cannot be re-approved / re-executed.

Seals (r3 wood):
  - Authority-looking keys nested under ``inputs`` are rejected
    (``nested_authority_key_in_inputs:*``).
  - Consumed ``request_id`` ledger is durable on local disk (Python wood):
    cross-process reuse fails closed.

Seals (r4 reinforce):
  - Mint + approval seal ledgers are durable on local disk and HMAC-bound
    with a local key file under artifacts (dev key on disk ≠ HSM — Theseus wood).
  - Cross-process: legitimate mint/approval verifies in a child process;
    forge / mac-tamper / approval reuse fail closed.
  - Nested-key deny uses NFKC + zero-width strip + cheap Cyrillic lookalikes.
  - calculator and uml_invoke share the same executor; seal binds exact tool.
  - AIFL spirit: each FAIL is a hard-negative for the next narrow boundary layer.
    Mouth never self-admits; CPU boundary ≠ LoRA reward.
  - Remaining wood: multi-host federation, HSM key custody → Rust Theseus target.

Seals (r5 wood):
  - Nested authority deny walks dict/list trees under ``inputs`` (deep smuggle).
  - Homoglyph map adds Greek lookalikes (still not a full Unicode confusables DB).
  - HMAC key empty/short/corrupt + ledger delete/corrupt mid-flight fail closed
    (disk key ≠ HSM remains Architect/Rust wood).

Seals (r6 wood):
  - Homoglyph map adds cheap Armenian lookalikes (օ/ս/ց → o/s/c) for authority-key
    neighborhood deny. Still NFKC + Cf strip + targeted map — not a full
    Unicode confusables DB (Architect/Rust wood).

Seals (r7 wood):
  - Homoglyph map adds cheap Georgian + Coptic lookalikes for authority-key
    neighborhood; digit/oh fold (fullwidth ０ → ASCII 0 via NFKC → o) for
    nested-key deny. Still not a full Unicode confusables DB (Rust next).

Seals (r7 steel — HMAC custody plate):
  - Prefer ``VIV_TOOL_SEAL_HMAC_KEY`` (hex, ≥32 bytes) over disk bootstrap key.
  - Optional Architect file via ``VIV_TOOL_SEAL_HMAC_KEY_FILE`` (not auto-artifacts).
  - Modes: ``prefer_env`` (default), ``env_only``, ``architect_file`` —
    fail closed when required material missing (no silent disk forge path).
  - Disk key path remains Theseus WOOD: readable key still forges under disk mode;
    mark WOOD loudly + permission note.

Seals (r8 steel — Rust seal custody plate):
  - HMAC sign/verify via ``viv_tool_seal`` CLI when binary present (prefer over
    long-lived Python key bytes for file/env sources).
  - ``VIV_TOOL_SEAL_REQUIRE_RUST=1``: fail closed if binary missing; deny
    disk/disk_bootstrap key sources (stolen-disk forge path closed).
  - ``VIV_TOOL_SEAL_RUST_BIN`` optional absolute path override.
  - Residual WOOD: Python fallback when Rust not required; Architect-file still
    filesystem-stealable; true HSM hardware + multi-host federation remain Theseus.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import secrets
import stat
import subprocess
import tempfile
import time
import unicodedata
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator, Mapping

AUTHORITY_VERSION = "cpu_tool_authority_v1"
CONSUMED_RID_LEDGER_SCHEMA = "cpu_tool_authority_consumed_rids_v1"
MINT_SEAL_LEDGER_SCHEMA = "cpu_tool_authority_mint_seals_v1"
APPROVAL_SEAL_LEDGER_SCHEMA = "cpu_tool_authority_approval_seals_v1"
# calculator ↔ uml_invoke: same Nested-PEMDAS executor; seal binds exact tool name.
ALLOWED_TOOLS = frozenset({"calculator", "uml_invoke"})
CALC_FAMILY_TOOLS = ALLOWED_TOOLS
ALLOWED_REQUEST_SOURCES = frozenset(
    {
        "gpu_mouth",
        "gpu_mouth_request",
        "operator",
        "operator_via_mouth",
        "cpu",  # CPU may self-propose for deterministic solve ingress; still reviewed
    }
)
# Sources that assert operator/CPU identity require a CPU mint seal.
# Attackers must not self-assert source=operator|cpu to gain execute rights.
_MINTED_SOURCES = frozenset({"operator", "operator_via_mouth", "cpu"})
_MAX_EXPR_LEN = 120
_EXPR_OK = re.compile(r"^[\d\s\(\)\[\]\{\}\+\-\*/\^\.,πpiφphiτtau]+$", flags=re.I)
# Authority-looking keys must not appear nested under inputs (R3/R4 wood seal).
_NESTED_AUTHORITY_KEYS = frozenset(
    {
        "cpu_approved",
        "cpu_minted",
        "cpu_mint_seal",
        "cpu_approval_seal",
        "authorization_token",
        "architect_claim",
        "authority",
        "approved_expression",
        "request_id",
        "source",
    }
)
# Compact form after NFKC / lookalike / separator strip (homoglyph neighborhood).
_NESTED_AUTHORITY_COMPACT = frozenset(
    k.replace("_", "").replace("-", "") for k in _NESTED_AUTHORITY_KEYS
)
# Cheap Cyrillic/Greek/Armenian → Latin lookalikes (homoglyph wood; not full confusable DB).
_HOMOGLYPH_MAP = str.maketrans(
    {
        # Cyrillic
        "а": "a",
        "е": "e",
        "о": "o",
        "р": "p",
        "с": "c",
        "х": "x",
        "у": "y",
        "і": "i",
        "ј": "j",
        "А": "A",
        "Е": "E",
        "О": "O",
        "Р": "P",
        "С": "C",
        "Х": "X",
        "У": "Y",
        "І": "I",
        # Greek (r5: omicron/rho etc. slipped past Cyrillic-only map)
        "α": "a",
        "Α": "A",
        "β": "b",
        "Β": "B",
        "ε": "e",
        "Ε": "E",
        "ι": "i",
        "Ι": "I",
        "κ": "k",
        "Κ": "K",
        "ν": "v",
        "Ν": "N",
        "ο": "o",
        "Ο": "O",
        "ρ": "p",
        "Ρ": "P",
        "τ": "t",
        "Τ": "T",
        "υ": "y",
        "Υ": "Y",
        "χ": "x",
        "Χ": "X",
        "η": "n",
        "Η": "H",
        "μ": "u",
        "Μ": "M",
        # Armenian (r6: օ/ս/ց slipped past Cyrillic+Greek map; authority-key neighborhood)
        "օ": "o",  # U+0585
        "Օ": "O",  # U+0555
        "ս": "s",  # U+057D
        "Ս": "S",  # U+054D
        "ց": "c",  # U+0581
        "Ց": "C",  # U+0551
        # Georgian (r7: o/a/s slipped past Armenian seal; 1:1 map only)
        "\u10d0": "a",  # Georgian a
        "\u10d3": "d",
        "\u10d4": "e",
        "\u10d5": "v",
        "\u10d8": "i",
        "\u10d9": "k",
        "\u10db": "m",
        "\u10dc": "n",
        "\u10dd": "o",  # Georgian o — binding r7 FAIL
        "\u10de": "p",
        "\u10e0": "r",
        "\u10e1": "s",
        "\u10e2": "t",
        "\u10e3": "u",
        "\u10e5": "k",
        "\u10e6": "g",
        "\u10e7": "q",
        "\u10ea": "c",
        "\u10ee": "x",
        "\u10ef": "j",
        "\u10f0": "h",
        # Coptic (r7)
        "\u2c9f": "o",
        "\u2c9e": "O",
        "\u2ca3": "p",
        "\u2ca2": "P",
        "\u2ca5": "c",
        "\u2ca4": "C",
        "\u2c81": "a",
        "\u2c80": "A",
        # Cherokee (r7 cheap a)
        "\u13a0": "a",
    }
)
# Mint records: request_id -> bound mint (acceleration; disk+HMAC is source of truth).
_MINT_SEALS: dict[str, dict[str, Any]] = {}
# Approval records: request_id -> bound single-use seal payload (acceleration).
_APPROVAL_SEALS: dict[str, dict[str, Any]] = {}
# request_ids that have completed execute (or burned on forge mismatch after bind).
# Acceleration only — disk ledger is source of truth for consume.
_CONSUMED_RIDS: set[str] = set()
_HMAC_KEY: bytes | None = None
# env | architect_file | disk | disk_bootstrap | None (unset until load)
_HMAC_KEY_SOURCE: str | None = None
_HMAC_KEY_WOOD: bool = True
# When Rust path owns MAC ops: prefer path/env over long-lived Python key bytes.
_HMAC_KEY_FILE: Path | None = None
_HMAC_KEY_ENV_NAME: str | None = None
_HMAC_RUST_BIN: Path | None = None
_HMAC_RUST_BIN_RESOLVED: bool = False

# Architect-facing env contracts (no HSM claim).
ENV_SEAL_HMAC_KEY = "VIV_TOOL_SEAL_HMAC_KEY"
ENV_SEAL_HMAC_KEY_FILE = "VIV_TOOL_SEAL_HMAC_KEY_FILE"
ENV_SEAL_HMAC_KEY_MODE = "VIV_TOOL_SEAL_HMAC_KEY_MODE"
ENV_SEAL_REQUIRE_RUST = "VIV_TOOL_SEAL_REQUIRE_RUST"
ENV_SEAL_RUST_BIN = "VIV_TOOL_SEAL_RUST_BIN"
_SEAL_KEY_MODES = frozenset({"prefer_env", "env_only", "architect_file"})
_RUST_SEAL_TIMEOUT_S = 5.0
_FOUNDATION_DIR = Path(__file__).resolve().parents[1]
_DEFAULT_RUST_SEAL_CANDIDATES = (
    _FOUNDATION_DIR / "rust" / "viv_tool_seal" / "target" / "release" / "viv_tool_seal.exe",
    _FOUNDATION_DIR / "rust" / "viv_tool_seal" / "target" / "release" / "viv_tool_seal",
    _FOUNDATION_DIR / "rust" / "viv_tool_seal" / "target" / "debug" / "viv_tool_seal.exe",
    _FOUNDATION_DIR / "rust" / "viv_tool_seal" / "target" / "debug" / "viv_tool_seal",
)

try:
    from lib.paths import AUTO_ARTIFACTS as _AUTO_ARTIFACTS
except Exception:  # noqa: BLE001
    _AUTO_ARTIFACTS = Path(__file__).resolve().parents[1] / "artifacts" / "auto"

_LEDGER_DIR = _AUTO_ARTIFACTS / "cpu_tool_authority"
CONSUMED_RID_LEDGER_PATH = _LEDGER_DIR / "consumed_rids.json"
MINT_SEAL_LEDGER_PATH = _LEDGER_DIR / "mint_seals.json"
APPROVAL_SEAL_LEDGER_PATH = _LEDGER_DIR / "approval_seals.json"
SEAL_HMAC_KEY_PATH = _LEDGER_DIR / "seal_hmac.key"
SEAL_HMAC_KEY_META_PATH = _LEDGER_DIR / "seal_hmac_key_WOOD.md"
_LEDGER_LOCK_PATH = _LEDGER_DIR / "authority.lock"
_LOCK_TIMEOUT_S = 5.0
_LOCK_POLL_S = 0.01


class ConsumedRidLedgerFault(Exception):
    """Ledger unavailable/corrupt — callers must fail closed (deny)."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class SealLedgerFault(Exception):
    """Mint/approval seal ledger or HMAC key fault — fail closed."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def _utc() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _empty_consumed_doc() -> dict[str, Any]:
    return {
        "schema_version": CONSUMED_RID_LEDGER_SCHEMA,
        "consumed": {},
        "updated_at": _utc(),
    }


def _empty_mint_doc() -> dict[str, Any]:
    return {
        "schema_version": MINT_SEAL_LEDGER_SCHEMA,
        "mints": {},
        "updated_at": _utc(),
    }


def _empty_approval_doc() -> dict[str, Any]:
    return {
        "schema_version": APPROVAL_SEAL_LEDGER_SCHEMA,
        "approvals": {},
        "updated_at": _utc(),
    }


def _atomic_write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, raw_temp = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=str(path.parent),
    )
    temp = Path(raw_temp)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(dict(payload), handle, indent=2, ensure_ascii=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, path)
    finally:
        if temp.exists():
            try:
                temp.unlink()
            except OSError:
                pass


def _atomic_write_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, raw_temp = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=str(path.parent),
    )
    temp = Path(raw_temp)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, path)
    finally:
        if temp.exists():
            try:
                temp.unlink()
            except OSError:
                pass


@contextmanager
def _ledger_file_lock() -> Iterator[None]:
    """Exclusive lock via lock-file (Windows + POSIX). Fail closed on timeout."""
    _LEDGER_DIR.mkdir(parents=True, exist_ok=True)
    lock_path = _LEDGER_LOCK_PATH
    # Prefer shared authority.lock; fall back create. Legacy path unused for new runs.
    deadline = time.monotonic() + _LOCK_TIMEOUT_S
    handle = None
    while True:
        try:
            handle = open(lock_path, "a+b")  # noqa: SIM115
            if os.name == "nt":
                import msvcrt

                handle.seek(0)
                if handle.read(1) == b"":
                    handle.write(b"\0")
                    handle.flush()
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            break
        except OSError:
            if handle is not None:
                try:
                    handle.close()
                except OSError:
                    pass
                handle = None
            if time.monotonic() >= deadline:
                raise ConsumedRidLedgerFault("authority_ledger_lock_timeout") from None
            time.sleep(_LOCK_POLL_S)
    try:
        yield
    finally:
        try:
            if handle is not None:
                if os.name == "nt":
                    import msvcrt

                    handle.seek(0)
                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        finally:
            if handle is not None:
                try:
                    handle.close()
                except OSError:
                    pass


def reset_seal_hmac_key_cache() -> None:
    """Clear process-local HMAC cache (tests / Architect key rotation)."""
    global _HMAC_KEY, _HMAC_KEY_SOURCE, _HMAC_KEY_WOOD
    global _HMAC_KEY_FILE, _HMAC_KEY_ENV_NAME, _HMAC_RUST_BIN, _HMAC_RUST_BIN_RESOLVED
    _HMAC_KEY = None
    _HMAC_KEY_SOURCE = None
    _HMAC_KEY_WOOD = True
    _HMAC_KEY_FILE = None
    _HMAC_KEY_ENV_NAME = None
    _HMAC_RUST_BIN = None
    _HMAC_RUST_BIN_RESOLVED = False


def _seal_hmac_key_mode() -> str:
    raw = str(os.environ.get(ENV_SEAL_HMAC_KEY_MODE) or "prefer_env").strip().lower()
    if raw not in _SEAL_KEY_MODES:
        raise SealLedgerFault("seal_hmac_key_mode_invalid")
    return raw


def _env_flag_true(name: str) -> bool:
    raw = str(os.environ.get(name) or "").strip().lower()
    return raw in {"1", "true", "yes", "on"}


def require_rust_seal() -> bool:
    """Architect gate: MAC ops must use viv_tool_seal; disk key sources denied."""
    return _env_flag_true(ENV_SEAL_REQUIRE_RUST)


def resolve_viv_tool_seal_bin(*, force: bool = False) -> Path | None:
    """Locate viv_tool_seal binary. Cached per process until reset."""
    global _HMAC_RUST_BIN, _HMAC_RUST_BIN_RESOLVED
    if _HMAC_RUST_BIN_RESOLVED and not force:
        return _HMAC_RUST_BIN
    override = str(os.environ.get(ENV_SEAL_RUST_BIN) or "").strip()
    found: Path | None = None
    if override:
        cand = Path(override)
        if cand.is_file():
            found = cand
    else:
        for cand in _DEFAULT_RUST_SEAL_CANDIDATES:
            if cand.is_file():
                found = cand
                break
    _HMAC_RUST_BIN = found
    _HMAC_RUST_BIN_RESOLVED = True
    return found


def _deny_disk_under_rust_required(source: str) -> None:
    if require_rust_seal() and source in {"disk", "disk_bootstrap"}:
        raise SealLedgerFault("seal_hmac_key_disk_denied_rust_required")


def _install_key_material(
    *,
    source: str,
    wood: bool,
    key_bytes: bytes | None = None,
    key_file: Path | None = None,
    key_env_name: str | None = None,
) -> None:
    """Record active seal key source. Prefer file/env handles when Rust owns MAC."""
    global _HMAC_KEY, _HMAC_KEY_SOURCE, _HMAC_KEY_WOOD, _HMAC_KEY_FILE, _HMAC_KEY_ENV_NAME
    _deny_disk_under_rust_required(source)
    use_rust = bool(resolve_viv_tool_seal_bin()) or require_rust_seal()
    _HMAC_KEY_SOURCE = source
    _HMAC_KEY_WOOD = wood
    _HMAC_KEY_FILE = key_file
    _HMAC_KEY_ENV_NAME = key_env_name
    if use_rust and (key_file is not None or key_env_name):
        # Custody plate: do not keep long-lived Python key bytes when Rust can
        # read env/file directly. Python fallback still needs bytes below.
        _HMAC_KEY = None
        if require_rust_seal():
            if resolve_viv_tool_seal_bin() is None:
                raise SealLedgerFault("seal_hmac_rust_binary_required")
            return
        # Prefer Rust without caching; keep bytes only if binary missing later.
        if resolve_viv_tool_seal_bin() is not None:
            return
    if key_bytes is None:
        if key_file is not None:
            key_bytes = _read_key_bytes(
                key_file,
                unreadable="seal_hmac_key_unreadable",
                too_short="seal_hmac_key_too_short",
            )
        elif key_env_name:
            env_raw = os.environ.get(key_env_name)
            if not env_raw or not str(env_raw).strip():
                raise SealLedgerFault("seal_hmac_key_env_required")
            key_bytes = _parse_env_hmac_key(str(env_raw))
        else:
            raise SealLedgerFault("seal_hmac_key_missing")
    if len(key_bytes) < 32:
        raise SealLedgerFault("seal_hmac_key_too_short")
    _HMAC_KEY = key_bytes


def _rust_mac_cmd(
    action: str,
    kind: str,
    *,
    rid: str,
    tool: str,
    expression: str,
    source: str,
    nonce: str,
    mac: str | None = None,
) -> list[str]:
    bin_path = resolve_viv_tool_seal_bin()
    if bin_path is None:
        raise SealLedgerFault("seal_hmac_rust_binary_required")
    cmd = [
        str(bin_path),
        action,
        "--kind",
        kind,
        "--rid",
        rid,
        "--tool",
        tool,
        "--expression",
        expression,
        "--source",
        source,
        "--nonce",
        nonce,
    ]
    if mac is not None:
        cmd.extend(["--mac", mac])
    if _HMAC_KEY_ENV_NAME:
        cmd.extend(["--key-env", _HMAC_KEY_ENV_NAME])
    elif _HMAC_KEY_FILE is not None:
        cmd.extend(["--key-file", str(_HMAC_KEY_FILE)])
    else:
        raise SealLedgerFault("seal_hmac_rust_key_source_missing")
    return cmd


def _run_rust_seal(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=_RUST_SEAL_TIMEOUT_S,
            check=False,
        )
    except FileNotFoundError as exc:
        raise SealLedgerFault("seal_hmac_rust_binary_missing") from exc
    except subprocess.TimeoutExpired as exc:
        raise SealLedgerFault("seal_hmac_rust_timeout") from exc


def _mac_hex_python(
    key: bytes,
    kind: str,
    *,
    rid: str,
    tool: str,
    expression: str,
    source: str,
    nonce: str,
) -> str:
    preimage = f"{kind}|v1|{rid}|{tool}|{expression}|{source}|{nonce}".encode("utf-8")
    return hmac.new(key, preimage, hashlib.sha256).hexdigest()


def _mac_hex_rust(
    kind: str,
    *,
    rid: str,
    tool: str,
    expression: str,
    source: str,
    nonce: str,
) -> str:
    cmd = _rust_mac_cmd(
        "sign",
        kind,
        rid=rid,
        tool=tool,
        expression=expression,
        source=source,
        nonce=nonce,
    )
    proc = _run_rust_seal(cmd)
    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "").strip() or f"rc={proc.returncode}"
        if proc.returncode == 2:
            raise SealLedgerFault(f"seal_hmac_rust_key_fault:{err}")
        raise SealLedgerFault(f"seal_hmac_rust_sign_failed:{err}")
    out = (proc.stdout or "").strip().splitlines()
    if not out or not out[-1].strip():
        raise SealLedgerFault("seal_hmac_rust_sign_empty")
    mac = out[-1].strip()
    if len(mac) != 64 or any(c not in "0123456789abcdef" for c in mac):
        raise SealLedgerFault("seal_hmac_rust_sign_invalid")
    return mac


def _mac_verify_rust(
    kind: str,
    *,
    rid: str,
    tool: str,
    expression: str,
    source: str,
    nonce: str,
    presented: str,
) -> bool:
    cmd = _rust_mac_cmd(
        "verify",
        kind,
        rid=rid,
        tool=tool,
        expression=expression,
        source=source,
        nonce=nonce,
        mac=presented,
    )
    proc = _run_rust_seal(cmd)
    if proc.returncode == 0:
        return True
    if proc.returncode == 1:
        return False
    err = (proc.stderr or proc.stdout or "").strip() or f"rc={proc.returncode}"
    raise SealLedgerFault(f"seal_hmac_rust_verify_fault:{err}")


def _use_rust_mac() -> bool:
    if require_rust_seal():
        if resolve_viv_tool_seal_bin() is None:
            raise SealLedgerFault("seal_hmac_rust_binary_required")
        return True
    return resolve_viv_tool_seal_bin() is not None and (
        _HMAC_KEY_ENV_NAME is not None or _HMAC_KEY_FILE is not None
    )


def _parse_env_hmac_key(raw: str) -> bytes:
    """Decode ``VIV_TOOL_SEAL_HMAC_KEY`` as hex (preferred) or raw UTF-8 (≥32 bytes)."""
    text = str(raw or "").strip()
    if not text:
        raise SealLedgerFault("seal_hmac_key_env_empty")
    key: bytes | None = None
    # Hex (even length) first — Architect env contract.
    if len(text) >= 64 and len(text) % 2 == 0 and all(
        c in "0123456789abcdefABCDEF" for c in text
    ):
        try:
            key = bytes.fromhex(text)
        except ValueError as exc:
            raise SealLedgerFault("seal_hmac_key_env_invalid_hex") from exc
    else:
        key = text.encode("utf-8")
    if len(key) < 32:
        raise SealLedgerFault("seal_hmac_key_env_too_short")
    return key


def _read_key_bytes(path: Path, *, unreadable: str, too_short: str) -> bytes:
    try:
        key = path.read_bytes()
    except OSError as exc:
        raise SealLedgerFault(unreadable) from exc
    if len(key) < 32:
        raise SealLedgerFault(too_short)
    return key


def _harden_key_file_permissions(path: Path) -> None:
    """Best-effort owner-only bits on POSIX. Windows ACLs remain Theseus wood."""
    if os.name == "nt":
        return
    try:
        os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)
    except OSError:
        pass


def _write_disk_key_wood_meta(*, source: str, path: Path) -> None:
    meta = (
        "# Seal HMAC key — Theseus WOOD (loud)\n\n"
        f"- **active_source:** `{source}`\n"
        f"- **path:** `{str(path).replace(chr(92), '/')}`\n"
        "- **Not an HSM.** Any process with filesystem read of this material can "
        "mint-forge seals that verify under the same key.\n"
        "- Prefer Architect env: set `VIV_TOOL_SEAL_HMAC_KEY` (hex ≥32 bytes) or "
        "`VIV_TOOL_SEAL_HMAC_KEY_FILE` (Architect-provisioned path).\n"
        "- Modes (`VIV_TOOL_SEAL_HMAC_KEY_MODE`): `prefer_env` (default), "
        "`env_only` (fail closed without env), `architect_file` (fail closed "
        "without Architect file; no auto-bootstrap).\n"
        "- Permissions: POSIX attempts `0600` on write; on Windows, restrict NTFS "
        "ACL to the AIOS service account (operator action — not enforced here).\n"
        "- Rust plate: set `VIV_TOOL_SEAL_REQUIRE_RUST=1` to deny disk/disk_bootstrap "
        "and require `viv_tool_seal` CLI for MAC ops "
        "(`foundation/rust/viv_tool_seal`).\n"
        "- Architect-gated residual: true HSM hardware / multi-host federation / "
        "full Unicode confusables.\n"
        "- AIFL: LoRA reward must never equal tool-execute rights; this key is "
        "CPU boundary only.\n"
    )
    try:
        SEAL_HMAC_KEY_META_PATH.parent.mkdir(parents=True, exist_ok=True)
        SEAL_HMAC_KEY_META_PATH.write_text(meta, encoding="utf-8")
    except OSError:
        pass


def get_seal_hmac_key_status() -> dict[str, Any]:
    """Observability for Architect/redteam — does not mint or allow tools."""
    mode = str(os.environ.get(ENV_SEAL_HMAC_KEY_MODE) or "prefer_env").strip().lower()
    env_set = bool(str(os.environ.get(ENV_SEAL_HMAC_KEY) or "").strip())
    file_env = str(os.environ.get(ENV_SEAL_HMAC_KEY_FILE) or "").strip()
    rust_bin = resolve_viv_tool_seal_bin()
    material_ready = (
        _HMAC_KEY is not None
        or _HMAC_KEY_ENV_NAME is not None
        or _HMAC_KEY_FILE is not None
    )
    return {
        "mode": mode if mode in _SEAL_KEY_MODES else "invalid",
        "source": _HMAC_KEY_SOURCE,
        "wood": bool(_HMAC_KEY_WOOD if material_ready else True),
        "env_key_set": env_set,
        "architect_file_env": file_env or None,
        "disk_key_path": str(SEAL_HMAC_KEY_PATH).replace("\\", "/"),
        "disk_key_present": SEAL_HMAC_KEY_PATH.is_file(),
        "cached_python_key_bytes": _HMAC_KEY is not None,
        "key_file": str(_HMAC_KEY_FILE).replace("\\", "/") if _HMAC_KEY_FILE else None,
        "key_env_name": _HMAC_KEY_ENV_NAME,
        "rust_bin": str(rust_bin).replace("\\", "/") if rust_bin else None,
        "require_rust": require_rust_seal(),
        "rust_mac_active": bool(
            rust_bin is not None
            and material_ready
            and (_HMAC_KEY_ENV_NAME is not None or _HMAC_KEY_FILE is not None)
        ),
        "note": (
            "disk/disk_bootstrap = WOOD (stolen readable key forges unless "
            "VIV_TOOL_SEAL_REQUIRE_RUST=1 denies disk). env / architect_file "
            "preferred; MAC via viv_tool_seal when binary present. "
            "True HSM hardware = remaining Theseus wood."
        ),
    }


def _ensure_hmac_key_unlocked() -> bytes | None:
    """Resolve HMAC key material by Architect mode.

    Returns Python key bytes when cached for fallback; may return None when Rust
    owns MAC via env/file handles (no long-lived Python key string).
    """
    global _HMAC_KEY, _HMAC_KEY_SOURCE, _HMAC_KEY_WOOD, _HMAC_KEY_FILE, _HMAC_KEY_ENV_NAME
    if (
        _HMAC_KEY is not None
        or _HMAC_KEY_ENV_NAME is not None
        or _HMAC_KEY_FILE is not None
    ):
        if require_rust_seal() and resolve_viv_tool_seal_bin() is None:
            raise SealLedgerFault("seal_hmac_rust_binary_required")
        _deny_disk_under_rust_required(str(_HMAC_KEY_SOURCE or ""))
        return _HMAC_KEY

    if require_rust_seal() and resolve_viv_tool_seal_bin() is None:
        raise SealLedgerFault("seal_hmac_rust_binary_required")

    mode = _seal_hmac_key_mode()
    env_raw = os.environ.get(ENV_SEAL_HMAC_KEY)
    file_raw = str(os.environ.get(ENV_SEAL_HMAC_KEY_FILE) or "").strip()

    if mode == "env_only":
        if not env_raw or not str(env_raw).strip():
            raise SealLedgerFault("seal_hmac_key_env_required")
        # Validate length/format; Rust path keeps env handle (no long-lived bytes).
        parsed = _parse_env_hmac_key(str(env_raw))
        rustish = bool(resolve_viv_tool_seal_bin()) or require_rust_seal()
        _install_key_material(
            source="env",
            wood=False,
            key_env_name=ENV_SEAL_HMAC_KEY,
            key_bytes=None if rustish else parsed,
        )
        return _HMAC_KEY

    if mode == "architect_file":
        if not file_raw:
            raise SealLedgerFault("seal_hmac_key_architect_file_required")
        path = Path(file_raw)
        if not path.is_file():
            raise SealLedgerFault("seal_hmac_key_architect_file_missing")
        # Length check without necessarily caching bytes.
        _read_key_bytes(
            path,
            unreadable="seal_hmac_key_architect_file_unreadable",
            too_short="seal_hmac_key_architect_file_too_short",
        )
        _write_disk_key_wood_meta(source="architect_file", path=path)
        _install_key_material(
            source="architect_file",
            wood=True,
            key_file=path,
        )
        return _HMAC_KEY

    # prefer_env (default): env → Architect file → disk → bootstrap disk
    if env_raw and str(env_raw).strip():
        parsed = _parse_env_hmac_key(str(env_raw))
        rustish = bool(resolve_viv_tool_seal_bin()) or require_rust_seal()
        _install_key_material(
            source="env",
            wood=False,
            key_env_name=ENV_SEAL_HMAC_KEY,
            key_bytes=None if rustish else parsed,
        )
        return _HMAC_KEY

    if file_raw:
        path = Path(file_raw)
        if not path.is_file():
            raise SealLedgerFault("seal_hmac_key_architect_file_missing")
        _read_key_bytes(
            path,
            unreadable="seal_hmac_key_architect_file_unreadable",
            too_short="seal_hmac_key_architect_file_too_short",
        )
        _write_disk_key_wood_meta(source="architect_file", path=path)
        _install_key_material(
            source="architect_file",
            wood=True,
            key_file=path,
        )
        return _HMAC_KEY

    if SEAL_HMAC_KEY_PATH.is_file():
        key = _read_key_bytes(
            SEAL_HMAC_KEY_PATH,
            unreadable="seal_hmac_key_unreadable",
            too_short="seal_hmac_key_too_short",
        )
        _write_disk_key_wood_meta(source="disk", path=SEAL_HMAC_KEY_PATH)
        _install_key_material(
            source="disk",
            wood=True,
            key_file=SEAL_HMAC_KEY_PATH,
            key_bytes=key,
        )
        return _HMAC_KEY

    # Bootstrap disk — denied under REQUIRE_RUST (no silent forge path).
    _deny_disk_under_rust_required("disk_bootstrap")
    key = secrets.token_bytes(32)
    _LEDGER_DIR.mkdir(parents=True, exist_ok=True)
    _atomic_write_bytes(SEAL_HMAC_KEY_PATH, key)
    _harden_key_file_permissions(SEAL_HMAC_KEY_PATH)
    _write_disk_key_wood_meta(source="disk_bootstrap", path=SEAL_HMAC_KEY_PATH)
    _install_key_material(
        source="disk_bootstrap",
        wood=True,
        key_file=SEAL_HMAC_KEY_PATH,
        key_bytes=key,
    )
    return _HMAC_KEY


def ensure_seal_hmac_key() -> Path:
    """Ensure HMAC material is loaded. Disk bootstrap only under prefer_env."""
    with _ledger_file_lock():
        _ensure_hmac_key_unlocked()
    if _HMAC_KEY_SOURCE in {"disk", "disk_bootstrap"}:
        return SEAL_HMAC_KEY_PATH
    file_raw = str(os.environ.get(ENV_SEAL_HMAC_KEY_FILE) or "").strip()
    if _HMAC_KEY_SOURCE == "architect_file" and file_raw:
        return Path(file_raw)
    if _HMAC_KEY_FILE is not None:
        return _HMAC_KEY_FILE
    # Env-only material has no path; return conventional disk path for callers.
    return SEAL_HMAC_KEY_PATH


def _mac_hex(kind: str, *, rid: str, tool: str, expression: str, source: str, nonce: str) -> str:
    _ensure_hmac_key_unlocked()
    if _use_rust_mac():
        return _mac_hex_rust(
            kind,
            rid=rid,
            tool=tool,
            expression=expression,
            source=source,
            nonce=nonce,
        )
    key = _HMAC_KEY
    if key is None:
        # Last-resort Python path: load bytes from file/env handles.
        if _HMAC_KEY_FILE is not None:
            key = _read_key_bytes(
                _HMAC_KEY_FILE,
                unreadable="seal_hmac_key_unreadable",
                too_short="seal_hmac_key_too_short",
            )
        elif _HMAC_KEY_ENV_NAME:
            env_raw = os.environ.get(_HMAC_KEY_ENV_NAME)
            if not env_raw or not str(env_raw).strip():
                raise SealLedgerFault("seal_hmac_key_env_required")
            key = _parse_env_hmac_key(str(env_raw))
        else:
            raise SealLedgerFault("seal_hmac_key_missing")
    return _mac_hex_python(
        key,
        kind,
        rid=rid,
        tool=tool,
        expression=expression,
        source=source,
        nonce=nonce,
    )


def _mac_verify(
    kind: str,
    *,
    rid: str,
    tool: str,
    expression: str,
    source: str,
    nonce: str,
    presented: str,
    expected: str | None = None,
) -> bool:
    """Verify seal MAC. Prefer Rust verify when custody plate active."""
    _ensure_hmac_key_unlocked()
    if _use_rust_mac():
        return _mac_verify_rust(
            kind,
            rid=rid,
            tool=tool,
            expression=expression,
            source=source,
            nonce=nonce,
            presented=presented,
        )
    recomputed = _mac_hex(
        kind,
        rid=rid,
        tool=tool,
        expression=expression,
        source=source,
        nonce=nonce,
    )
    if expected is not None and not hmac.compare_digest(expected, recomputed):
        return False
    target = expected if expected is not None else recomputed
    return hmac.compare_digest(presented, target)


def mac_hex_with_key(
    key: bytes,
    kind: str,
    *,
    rid: str,
    tool: str,
    expression: str,
    source: str,
    nonce: str,
) -> str:
    """Compute seal MAC with an explicit key (redteam / stolen-key probes only)."""
    if len(key) < 32:
        raise SealLedgerFault("seal_hmac_key_too_short")
    return _mac_hex_python(
        key,
        kind,
        rid=rid,
        tool=tool,
        expression=expression,
        source=source,
        nonce=nonce,
    )


def _parse_json_object(raw: bytes, *, corrupt_reason: str) -> dict[str, Any]:
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SealLedgerFault(corrupt_reason) from exc
    if not isinstance(data, dict):
        raise SealLedgerFault(corrupt_reason)
    return data


def _parse_consumed_bytes(raw: bytes) -> dict[str, Any]:
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ConsumedRidLedgerFault("consumed_rid_ledger_corrupt") from exc
    if not isinstance(data, dict):
        raise ConsumedRidLedgerFault("consumed_rid_ledger_corrupt")
    if str(data.get("schema_version") or "") != CONSUMED_RID_LEDGER_SCHEMA:
        raise ConsumedRidLedgerFault("consumed_rid_ledger_corrupt")
    consumed = data.get("consumed")
    if not isinstance(consumed, dict):
        raise ConsumedRidLedgerFault("consumed_rid_ledger_corrupt")
    return data


def _load_consumed_unlocked() -> dict[str, Any]:
    if not CONSUMED_RID_LEDGER_PATH.is_file():
        raise ConsumedRidLedgerFault("consumed_rid_ledger_missing")
    try:
        raw = CONSUMED_RID_LEDGER_PATH.read_bytes()
    except OSError as exc:
        raise ConsumedRidLedgerFault("consumed_rid_ledger_unreadable") from exc
    if not raw.strip():
        raise ConsumedRidLedgerFault("consumed_rid_ledger_corrupt")
    return _parse_consumed_bytes(raw)


def _load_mint_unlocked() -> dict[str, Any]:
    if not MINT_SEAL_LEDGER_PATH.is_file():
        raise SealLedgerFault("mint_seal_ledger_missing")
    try:
        raw = MINT_SEAL_LEDGER_PATH.read_bytes()
    except OSError as exc:
        raise SealLedgerFault("mint_seal_ledger_unreadable") from exc
    if not raw.strip():
        raise SealLedgerFault("mint_seal_ledger_corrupt")
    data = _parse_json_object(raw, corrupt_reason="mint_seal_ledger_corrupt")
    if str(data.get("schema_version") or "") != MINT_SEAL_LEDGER_SCHEMA:
        raise SealLedgerFault("mint_seal_ledger_corrupt")
    mints = data.get("mints")
    if not isinstance(mints, dict):
        raise SealLedgerFault("mint_seal_ledger_corrupt")
    return data


def _load_approval_unlocked() -> dict[str, Any]:
    if not APPROVAL_SEAL_LEDGER_PATH.is_file():
        raise SealLedgerFault("approval_seal_ledger_missing")
    try:
        raw = APPROVAL_SEAL_LEDGER_PATH.read_bytes()
    except OSError as exc:
        raise SealLedgerFault("approval_seal_ledger_unreadable") from exc
    if not raw.strip():
        raise SealLedgerFault("approval_seal_ledger_corrupt")
    data = _parse_json_object(raw, corrupt_reason="approval_seal_ledger_corrupt")
    if str(data.get("schema_version") or "") != APPROVAL_SEAL_LEDGER_SCHEMA:
        raise SealLedgerFault("approval_seal_ledger_corrupt")
    approvals = data.get("approvals")
    if not isinstance(approvals, dict):
        raise SealLedgerFault("approval_seal_ledger_corrupt")
    return data


def ensure_consumed_rid_ledger() -> dict[str, Any]:
    """Bootstrap empty ledger if missing. Explicit init only — not an allow path."""
    with _ledger_file_lock():
        _ensure_hmac_key_unlocked()
        if CONSUMED_RID_LEDGER_PATH.is_file():
            return _load_consumed_unlocked()
        doc = _empty_consumed_doc()
        _atomic_write_json(CONSUMED_RID_LEDGER_PATH, doc)
        return doc


def ensure_mint_seal_ledger() -> dict[str, Any]:
    """Bootstrap empty mint seal ledger if missing."""
    with _ledger_file_lock():
        _ensure_hmac_key_unlocked()
        if MINT_SEAL_LEDGER_PATH.is_file():
            return _load_mint_unlocked()
        doc = _empty_mint_doc()
        _atomic_write_json(MINT_SEAL_LEDGER_PATH, doc)
        return doc


def ensure_approval_seal_ledger() -> dict[str, Any]:
    """Bootstrap empty approval seal ledger if missing."""
    with _ledger_file_lock():
        _ensure_hmac_key_unlocked()
        if APPROVAL_SEAL_LEDGER_PATH.is_file():
            return _load_approval_unlocked()
        doc = _empty_approval_doc()
        _atomic_write_json(APPROVAL_SEAL_LEDGER_PATH, doc)
        return doc


def ensure_authority_ledgers() -> dict[str, Any]:
    """Bootstrap HMAC key + consumed/mint/approval ledgers (explicit init)."""
    with _ledger_file_lock():
        _ensure_hmac_key_unlocked()
        if not CONSUMED_RID_LEDGER_PATH.is_file():
            _atomic_write_json(CONSUMED_RID_LEDGER_PATH, _empty_consumed_doc())
        if not MINT_SEAL_LEDGER_PATH.is_file():
            _atomic_write_json(MINT_SEAL_LEDGER_PATH, _empty_mint_doc())
        if not APPROVAL_SEAL_LEDGER_PATH.is_file():
            _atomic_write_json(APPROVAL_SEAL_LEDGER_PATH, _empty_approval_doc())
        status = get_seal_hmac_key_status()
        return {
            "hmac_key": str(SEAL_HMAC_KEY_PATH).replace("\\", "/"),
            "hmac_key_source": status.get("source"),
            "hmac_key_wood": status.get("wood"),
            "hmac_key_mode": status.get("mode"),
            "consumed": str(CONSUMED_RID_LEDGER_PATH).replace("\\", "/"),
            "mint": str(MINT_SEAL_LEDGER_PATH).replace("\\", "/"),
            "approval": str(APPROVAL_SEAL_LEDGER_PATH).replace("\\", "/"),
        }


def _rid_consumed_durable(rid: str) -> str | None:
    """Return deny reason if rid consumed or ledger fault; None if free to proceed."""
    if not rid:
        return None
    if rid in _CONSUMED_RIDS:
        return "request_id_already_consumed"
    try:
        with _ledger_file_lock():
            doc = _load_consumed_unlocked()
            consumed = doc["consumed"]
            for key in consumed:
                if isinstance(key, str) and key:
                    _CONSUMED_RIDS.add(key)
            if rid in consumed:
                _CONSUMED_RIDS.add(rid)
                return "request_id_already_consumed"
            return None
    except ConsumedRidLedgerFault as exc:
        return str(exc.reason)


def _consume_rid_durable(rid: str, *, reason: str) -> str | None:
    """Atomically mark rid consumed on disk. None=ok; else deny reason."""
    if not rid:
        return "missing_request_id"
    try:
        with _ledger_file_lock():
            doc = _load_consumed_unlocked()
            consumed = doc["consumed"]
            if not isinstance(consumed, dict):
                return "consumed_rid_ledger_corrupt"
            for key in consumed:
                if isinstance(key, str) and key:
                    _CONSUMED_RIDS.add(key)
            if rid in consumed:
                _CONSUMED_RIDS.add(rid)
                return "request_id_already_consumed"
            consumed[rid] = {"at": _utc(), "reason": reason}
            doc["consumed"] = consumed
            doc["updated_at"] = _utc()
            _atomic_write_json(CONSUMED_RID_LEDGER_PATH, doc)
            _CONSUMED_RIDS.add(rid)
            # Burn durable approval row with the same lock (single-use cross-proc).
            try:
                appr = _load_approval_unlocked()
                approvals = appr["approvals"]
                if isinstance(approvals, dict) and rid in approvals:
                    approvals.pop(rid, None)
                    appr["approvals"] = approvals
                    appr["updated_at"] = _utc()
                    _atomic_write_json(APPROVAL_SEAL_LEDGER_PATH, appr)
            except SealLedgerFault:
                # Approval ledger fault after consume still burns rid; execute path
                # already fails closed if approval verify needed earlier.
                pass
            _APPROVAL_SEALS.pop(rid, None)
            return None
    except ConsumedRidLedgerFault as exc:
        return str(exc.reason)


def _install_mint_durable(
    rid: str,
    *,
    tool: str,
    expression: str,
    source: str,
) -> str:
    """Write HMAC-bound mint record; return seal hex. Raises SealLedgerFault."""
    nonce = secrets.token_hex(16)
    seal = _mac_hex(
        "mint",
        rid=rid,
        tool=tool,
        expression=expression,
        source=source,
        nonce=nonce,
    )
    record = {
        "seal": seal,
        "nonce": nonce,
        "tool": tool,
        "expression": expression,
        "source": source,
        "at": _utc(),
    }
    with _ledger_file_lock():
        _ensure_hmac_key_unlocked()
        try:
            doc = _load_mint_unlocked()
        except SealLedgerFault as exc:
            if exc.reason == "mint_seal_ledger_missing":
                doc = _empty_mint_doc()
            else:
                raise
        mints = doc["mints"]
        if not isinstance(mints, dict):
            raise SealLedgerFault("mint_seal_ledger_corrupt")
        mints[rid] = record
        doc["mints"] = mints
        doc["updated_at"] = _utc()
        _atomic_write_json(MINT_SEAL_LEDGER_PATH, doc)
    _MINT_SEALS[rid] = dict(record)
    return seal


def _install_approval_durable(
    rid: str,
    *,
    tool: str,
    expression: str,
    source: str,
) -> str:
    """Write HMAC-bound approval record; return seal hex."""
    nonce = secrets.token_hex(16)
    seal = _mac_hex(
        "approval",
        rid=rid,
        tool=tool,
        expression=expression,
        source=source,
        nonce=nonce,
    )
    record = {
        "seal": seal,
        "nonce": nonce,
        "tool": tool,
        "expression": expression,
        "source": source,
        "at": _utc(),
    }
    with _ledger_file_lock():
        _ensure_hmac_key_unlocked()
        try:
            doc = _load_approval_unlocked()
        except SealLedgerFault as exc:
            if exc.reason == "approval_seal_ledger_missing":
                doc = _empty_approval_doc()
            else:
                raise
        approvals = doc["approvals"]
        if not isinstance(approvals, dict):
            raise SealLedgerFault("approval_seal_ledger_corrupt")
        approvals[rid] = record
        doc["approvals"] = approvals
        doc["updated_at"] = _utc()
        _atomic_write_json(APPROVAL_SEAL_LEDGER_PATH, doc)
    _APPROVAL_SEALS[rid] = dict(record)
    return seal


def _verify_mint_record(
    rid: str,
    presented: str,
    *,
    tool: str,
    expression: str,
    source: str,
) -> str | None:
    """Return deny reason or None if durable HMAC mint binds."""
    if not rid or not presented:
        return "forged_cpu_mint_seal"
    try:
        with _ledger_file_lock():
            _ensure_hmac_key_unlocked()
            doc = _load_mint_unlocked()
            record = doc["mints"].get(rid)
            if not isinstance(record, Mapping):
                cached = _MINT_SEALS.get(rid)
                if not isinstance(cached, Mapping):
                    return "forged_cpu_mint_seal"
                record = cached
            else:
                _MINT_SEALS[rid] = dict(record)
    except SealLedgerFault as exc:
        return str(exc.reason)
    except ConsumedRidLedgerFault as exc:
        return str(exc.reason)

    nonce = str(record.get("nonce") or "")
    expected = str(record.get("seal") or "")
    if not nonce or not expected:
        return "forged_cpu_mint_seal"
    try:
        bound_ok = _mac_verify(
            "mint",
            rid=rid,
            tool=str(record.get("tool") or ""),
            expression=str(record.get("expression") or ""),
            source=str(record.get("source") or ""),
            nonce=nonce,
            presented=expected,
        )
    except SealLedgerFault as exc:
        return str(exc.reason)
    if not bound_ok:
        return "mint_seal_mac_mismatch"
    try:
        presented_ok = _mac_verify(
            "mint",
            rid=rid,
            tool=str(record.get("tool") or ""),
            expression=str(record.get("expression") or ""),
            source=str(record.get("source") or ""),
            nonce=nonce,
            presented=presented,
        )
    except SealLedgerFault as exc:
        return str(exc.reason)
    if not presented_ok:
        return "forged_cpu_mint_seal"
    if str(record.get("tool") or "") != tool:
        return "mint_binding_mismatch:tool"
    if str(record.get("source") or "") != source:
        return "mint_binding_mismatch:source"
    if tool in CALC_FAMILY_TOOLS and str(record.get("expression") or "") != expression:
        return "mint_binding_mismatch:expression"
    return None


def _load_approval_record(rid: str) -> tuple[dict[str, Any] | None, str | None]:
    """Return (record, deny_reason)."""
    if not rid:
        return None, "forged_approval_or_seal_mismatch"
    try:
        with _ledger_file_lock():
            _ensure_hmac_key_unlocked()
            doc = _load_approval_unlocked()
            record = doc["approvals"].get(rid)
            if isinstance(record, Mapping):
                out = dict(record)
                _APPROVAL_SEALS[rid] = out
                return out, None
            cached = _APPROVAL_SEALS.get(rid)
            if isinstance(cached, Mapping):
                return dict(cached), None
            return None, "forged_approval_or_seal_mismatch"
    except SealLedgerFault as exc:
        return None, str(exc.reason)
    except ConsumedRidLedgerFault as exc:
        return None, str(exc.reason)


def _verify_approval_record(
    rid: str,
    presented: str,
    record: Mapping[str, Any],
) -> str | None:
    nonce = str(record.get("nonce") or "")
    expected = str(record.get("seal") or "")
    if not nonce or not expected or not presented:
        return "forged_approval_or_seal_mismatch"
    try:
        bound_ok = _mac_verify(
            "approval",
            rid=rid,
            tool=str(record.get("tool") or ""),
            expression=str(record.get("expression") or ""),
            source=str(record.get("source") or ""),
            nonce=nonce,
            presented=expected,
        )
    except SealLedgerFault as exc:
        return str(exc.reason)
    if not bound_ok:
        return "approval_seal_mac_mismatch"
    try:
        presented_ok = _mac_verify(
            "approval",
            rid=rid,
            tool=str(record.get("tool") or ""),
            expression=str(record.get("expression") or ""),
            source=str(record.get("source") or ""),
            nonce=nonce,
            presented=presented,
        )
    except SealLedgerFault as exc:
        return str(exc.reason)
    if not presented_ok:
        return "forged_approval_or_seal_mismatch"
    return None


def _expr_from_inputs(inputs: Mapping[str, Any] | None) -> str:
    if not isinstance(inputs, Mapping):
        return ""
    return str(inputs.get("expression") or inputs.get("expr") or "").strip()


def _normalize_authority_key(key: Any) -> str:
    """NFKC + strip format chars + cheap lookalikes + casefold + drop separators."""
    s = unicodedata.normalize("NFKC", str(key))
    s = s.translate(_HOMOGLYPH_MAP)
    s = "".join(ch for ch in s if unicodedata.category(ch) != "Cf")
    s = s.strip().casefold()
    return s.replace("_", "").replace("-", "").replace(" ", "")


def _authority_key_fold_variants(compact: str) -> tuple[str, ...]:
    """Cheap digit/oh folds after NFKC (fullwidth ０ → '0' → try as 'o').

    Not a confusables DB — only the digraph-adjacent smuggle that let
    ``cpu_appr０ved`` execute under r6 Armenian seal.
    """
    base = str(compact or "")
    variants = [base]
    if "0" in base:
        variants.append(base.replace("0", "o"))
    return tuple(dict.fromkeys(variants))


def _key_is_nested_authority(key: Any) -> bool:
    kn = str(key).strip().casefold()
    if kn in _NESTED_AUTHORITY_KEYS:
        return True
    compact = _normalize_authority_key(key)
    for variant in _authority_key_fold_variants(compact):
        if variant in _NESTED_AUTHORITY_COMPACT:
            return True
    return False


def _nested_authority_in_inputs(inputs: Mapping[str, Any]) -> str | None:
    """Reject authority-looking keys anywhere under inputs (deep walk, fail closed)."""

    def _walk(node: Any, *, path: str) -> str | None:
        if isinstance(node, Mapping):
            for key, val in node.items():
                loc = f"{path}.{key}" if path else str(key)
                if _key_is_nested_authority(key):
                    return f"nested_authority_key_in_inputs:{loc}"
                hit = _walk(val, path=loc)
                if hit:
                    return hit
            return None
        if isinstance(node, (list, tuple)):
            for idx, item in enumerate(node):
                loc = f"{path}[{idx}]" if path else f"[{idx}]"
                hit = _walk(item, path=loc)
                if hit:
                    return hit
        return None

    if not isinstance(inputs, Mapping):
        return None
    return _walk(inputs, path="")


def _deny(
    reason: str,
    *,
    request_id: Any = None,
) -> dict[str, Any]:
    return {
        "allowed": False,
        "status": "denied",
        "reason": reason,
        "authority": "cpu",
        "request_id": request_id,
        "at": _utc(),
    }


def build_tool_request(
    *,
    tool: str,
    inputs: Mapping[str, Any],
    source: str = "gpu_mouth_request",
    request_id: str | None = None,
    note: str | None = None,
    cpu_minted: bool = False,
) -> dict[str, Any]:
    """Build a structured tool request (GPU proposes; CPU has not approved yet).

    ``cpu_minted=True`` alone is NOT authority. Only ``mint_cpu_tool_request``
    installs a server-side mint record + ``cpu_mint_seal``.
    """
    # secrets token — not time_ns hash. Rapid-fire calls on Windows can share
    # the same time_ns and collide request_ids (load-transfer seam under
    # consumed_rid steel: false already_consumed / not_approved on neighbors).
    rid = request_id or secrets.token_hex(8)
    return {
        "schema_version": AUTHORITY_VERSION,
        "request_id": rid,
        "source": str(source),
        "tool": str(tool),
        "inputs": dict(inputs),
        "status": "proposed",
        "authority": "gpu_may_request_only" if not cpu_minted else "cpu_minted_request",
        "cpu_approved": False,
        "cpu_minted": bool(cpu_minted),
        "note": note,
        "at": _utc(),
    }


def mint_cpu_tool_request(
    *,
    tool: str,
    inputs: Mapping[str, Any],
    source: str = "operator_via_mouth",
    request_id: str | None = None,
    note: str | None = None,
) -> dict[str, Any]:
    """CPU-trusted request builder — installs durable HMAC mint seal."""
    src = str(source or "operator_via_mouth")
    if src not in _MINTED_SOURCES:
        src = "operator_via_mouth"
    tool_s = str(tool)
    req = build_tool_request(
        tool=tool_s,
        inputs=inputs,
        source=src,
        request_id=request_id,
        note=note,
        cpu_minted=True,
    )
    rid = str(req["request_id"])
    expr = _expr_from_inputs(inputs)
    try:
        seal = _install_mint_durable(
            rid, tool=tool_s, expression=expr, source=src
        )
    except SealLedgerFault as exc:
        # Fail closed: return request without usable seal (review will deny).
        req["cpu_mint_seal"] = ""
        req["mint_fault"] = str(exc.reason)
        return req
    req["cpu_mint_seal"] = seal
    return req


def _mint_ok(request: Mapping[str, Any], *, source: str, tool: str, expr: str) -> str | None:
    """Return deny reason if minted-source request lacks a matching bound mint."""
    rid = str(request.get("request_id") or "")
    presented = str(request.get("cpu_mint_seal") or "")
    if request.get("cpu_minted") is not True:
        return "operator_source_requires_cpu_mint"
    return _verify_mint_record(
        rid, presented, tool=tool, expression=expr, source=source
    )


def review_tool_request(request: Mapping[str, Any] | None) -> dict[str, Any]:
    """CPU review — fail closed. Does not execute.

    Gate order is neighborhood-first: source → tool allowlist → gpu self-approve
    → architect forge → inputs/expression → *then* mint binding. Mint must not
    early-return past tool/input checks (steel plate that skips wood joints).
    """
    if not isinstance(request, Mapping):
        return _deny("request_not_mapping")
    source = str(request.get("source") or "")
    tool = str(request.get("tool") or "")
    inputs = request.get("inputs")
    rid = str(request.get("request_id") or "")
    if rid:
        consumed_reason = _rid_consumed_durable(rid)
        if consumed_reason:
            return _deny(consumed_reason, request_id=request.get("request_id"))
    if source not in ALLOWED_REQUEST_SOURCES:
        return _deny(f"source_not_allowed:{source}", request_id=request.get("request_id"))
    if tool not in ALLOWED_TOOLS:
        return _deny(f"tool_not_allowlisted:{tool}", request_id=request.get("request_id"))
    if request.get("cpu_approved") is True and source.startswith("gpu"):
        # GPU cannot self-approve.
        return _deny("gpu_cannot_self_approve", request_id=request.get("request_id"))
    # Forged Architect / ROOT tokens in the request never mint authority.
    if request.get("authorization_token") or request.get("architect_claim"):
        return _deny("forged_architect_token_rejected", request_id=request.get("request_id"))
    if not isinstance(inputs, Mapping):
        return _deny("inputs_not_mapping", request_id=request.get("request_id"))
    nested = _nested_authority_in_inputs(inputs)
    if nested:
        return _deny(nested, request_id=request.get("request_id"))
    expr = _expr_from_inputs(inputs)
    if tool in CALC_FAMILY_TOOLS:
        if not expr:
            return _deny("missing_expression", request_id=request.get("request_id"))
        if len(expr) > _MAX_EXPR_LEN:
            return _deny("expression_too_long", request_id=request.get("request_id"))
        if not _EXPR_OK.match(expr):
            return _deny("expression_charset_denied", request_id=request.get("request_id"))
    # Mint binding after neighborhood gates — forged operator/cpu still dies here.
    if source in _MINTED_SOURCES:
        # Surface mint/HMAC ledger faults (empty/short key, corrupt ledger) before
        # generic forge reason — fail closed with the concrete fault.
        mint_fault = str(request.get("mint_fault") or "").strip()
        if mint_fault and not str(request.get("cpu_mint_seal") or "").strip():
            return _deny(mint_fault, request_id=request.get("request_id"))
        mint_reason = _mint_ok(request, source=source, tool=tool, expr=expr)
        if mint_reason:
            return _deny(mint_reason, request_id=request.get("request_id"))
    if not rid:
        return _deny("missing_request_id", request_id=None)

    try:
        seal = _install_approval_durable(
            rid, tool=tool, expression=expr, source=source
        )
    except SealLedgerFault as exc:
        return _deny(str(exc.reason), request_id=request.get("request_id"))
    return {
        "allowed": True,
        "status": "approved",
        "reason": "cpu_allowlist_and_inputs_ok",
        "authority": "cpu",
        "tool": tool,
        "request_id": request.get("request_id"),
        "cpu_approval_seal": seal,
        "approved_expression": expr if tool in CALC_FAMILY_TOOLS else None,
        "at": _utc(),
    }


def execute_approved_tool(
    request: Mapping[str, Any],
    approval: Mapping[str, Any],
) -> dict[str, Any]:
    """CPU executes only with a single-use bound review seal.

    Forged approvals, seal replay, and post-mint mutations of tool/expression
    fail closed. Bound payload from the durable HMAC seal store is authoritative.
    """
    # Neighborhood: None / non-mapping must fail closed (no AttributeError crash).
    if not isinstance(request, Mapping):
        return {
            "ok": False,
            "executed": False,
            "reason": "request_not_mapping",
            "approval": {"allowed": False, "reason": "request_not_mapping", "authority": "cpu"},
            "authority": "cpu",
            "at": _utc(),
        }
    if not isinstance(approval, Mapping):
        return {
            "ok": False,
            "executed": False,
            "reason": "not_approved",
            "approval": {"allowed": False, "reason": "not_approved", "authority": "cpu"},
            "at": _utc(),
            "authority": "cpu",
        }
    if not approval.get("allowed"):
        return {
            "ok": False,
            "executed": False,
            "reason": "not_approved",
            "approval": dict(approval),
            "authority": "cpu",
            "at": _utc(),
        }
    rid = str(request.get("request_id") or "")
    if rid:
        consumed_reason = _rid_consumed_durable(rid)
        if consumed_reason:
            return {
                "ok": False,
                "executed": False,
                "reason": consumed_reason,
                "approval": {
                    "allowed": False,
                    "reason": consumed_reason,
                    "authority": "cpu",
                },
                "authority": "cpu",
                "at": _utc(),
            }
    presented = str(approval.get("cpu_approval_seal") or "")
    record, load_reason = _load_approval_record(rid)
    if record is None:
        return {
            "ok": False,
            "executed": False,
            "reason": load_reason or "forged_approval_or_seal_mismatch",
            "approval": {
                "allowed": False,
                "reason": load_reason or "forged_approval_or_seal_mismatch",
                "authority": "cpu",
            },
            "authority": "cpu",
            "at": _utc(),
        }
    mac_reason = _verify_approval_record(rid, presented, record)
    if mac_reason:
        _APPROVAL_SEALS.pop(rid, None)
        return {
            "ok": False,
            "executed": False,
            "reason": mac_reason,
            "approval": {
                "allowed": False,
                "reason": mac_reason,
                "authority": "cpu",
            },
            "authority": "cpu",
            "at": _utc(),
        }

    bound_tool = str(record.get("tool") or "")
    bound_expr = str(record.get("expression") or "")
    bound_source = str(record.get("source") or "")
    req_tool = str(request.get("tool") or "")
    req_expr = _expr_from_inputs(request.get("inputs") if isinstance(request.get("inputs"), Mapping) else None)
    req_source = str(request.get("source") or "")
    appr_tool = str(approval.get("tool") or "")
    appr_expr = str(approval.get("approved_expression") or "").strip()

    # Reject load-transfer mutations after seal mint (request or approval side).
    # Exact tool bind: calculator≠uml_invoke even though they share the executor.
    if (
        req_tool != bound_tool
        or appr_tool != bound_tool
        or req_source != bound_source
        or (bound_tool in CALC_FAMILY_TOOLS and (req_expr != bound_expr or appr_expr != bound_expr))
    ):
        _APPROVAL_SEALS.pop(rid, None)
        burn = _consume_rid_durable(rid, reason="seal_binding_mismatch")
        if burn and burn != "request_id_already_consumed":
            return {
                "ok": False,
                "executed": False,
                "reason": burn,
                "approval": {"allowed": False, "reason": burn, "authority": "cpu"},
                "authority": "cpu",
                "at": _utc(),
            }
        return {
            "ok": False,
            "executed": False,
            "reason": "seal_binding_mismatch",
            "approval": {"allowed": False, "reason": "seal_binding_mismatch", "authority": "cpu"},
            "authority": "cpu",
            "at": _utc(),
        }

    # Single-use consume on disk before side effects (cross-process fail-closed).
    _APPROVAL_SEALS.pop(rid, None)
    consume_fault = _consume_rid_durable(rid, reason="execute")
    if consume_fault:
        return {
            "ok": False,
            "executed": False,
            "reason": consume_fault,
            "approval": {
                "allowed": False,
                "reason": consume_fault,
                "authority": "cpu",
            },
            "authority": "cpu",
            "at": _utc(),
        }

    tool = bound_tool
    if tool not in CALC_FAMILY_TOOLS:
        return {
            "ok": False,
            "executed": False,
            "reason": f"execute_unsupported_tool:{tool}",
            "authority": "cpu",
            "at": _utc(),
        }
    expr = bound_expr
    from lib.aios_adapter_uml_invoke import invoke_uml

    # Alias executor: calculator and uml_invoke share invoke_uml (Nested PEMDAS).
    result = invoke_uml(
        expr,
        source="cpu_after_approval",
        query=str(request.get("note") or request.get("query") or expr),
    )
    # Stamp authority relationship onto the persisted invoke receipt for later asks.
    if isinstance(result, dict):
        result = {
            **result,
            "tool_request_source": bound_source,
            "tool_name": tool,
            "cpu_tool_approved": True,
            "cpu_tool_executed": True,
            "gpu_executed_tool": False,
            "request_id": request.get("request_id"),
            "calc_family_alias": tool in CALC_FAMILY_TOOLS,
        }
        try:
            from lib.aios_adapter_uml_invoke import _persist_last

            _persist_last(result)
        except Exception:  # noqa: BLE001
            pass
    return {
        "ok": bool(result.get("ok")),
        "executed": True,
        "tool": tool,
        "request_id": request.get("request_id"),
        "approval": {
            "allowed": True,
            "reason": approval.get("reason"),
            "at": approval.get("at"),
        },
        "result": result,
        "authority": "cpu",
        "gpu_executed": False,
        "at": _utc(),
    }


def handle_tool_request(request: Mapping[str, Any] | None) -> dict[str, Any]:
    """Full CPU path: review → (maybe) execute → evidence bundle."""
    approval = review_tool_request(request)
    if not approval.get("allowed"):
        return {
            "ok": False,
            "executed": False,
            "request": dict(request or {}),
            "approval": approval,
            "authority": "cpu",
            "at": _utc(),
        }
    executed = execute_approved_tool(dict(request or {}), approval)
    return {
        "ok": bool(executed.get("ok")),
        "executed": bool(executed.get("executed")),
        "request": dict(request or {}),
        "approval": approval,
        "execution": executed,
        "authority": "cpu",
        "at": _utc(),
    }


def propose_calculator_from_query(
    query: str,
    *,
    source: str = "operator_via_mouth",
    tool: str = "uml_invoke",
) -> dict[str, Any] | None:
    """Build a calculator/uml_invoke request from operator text if an expression is present.

    ``tool`` must be in CALC_FAMILY_TOOLS; both aliases share the same executor and
    seal-binding rules (exact tool name is bound at mint).
    """
    from lib.aios_adapter_uml_invoke import extract_expression

    expr = extract_expression(query)
    if not expr:
        return None
    tool_s = str(tool or "uml_invoke")
    if tool_s not in CALC_FAMILY_TOOLS:
        tool_s = "uml_invoke"
    return mint_cpu_tool_request(
        tool=tool_s,
        inputs={"expression": expr},
        source=source,
        note=str(query),
    )


def parse_gpu_tool_request_from_text(text: str) -> dict[str, Any] | None:
    """Parse an optional GPU-emitted TOOL_REQUEST JSON block from draft text.

    Expected shape (single line or fenced):
      TOOL_REQUEST:{"tool":"uml_invoke","inputs":{"expression":"2+2"}}
    GPU cannot include cpu_approved=true meaningfully — review rejects self-approve.
    """
    raw = str(text or "")
    m = re.search(r"TOOL_REQUEST\s*:\s*(\{)", raw, flags=re.I | re.S)
    if not m:
        return None
    start = m.start(1)
    depth = 0
    end = None
    for i, ch in enumerate(raw[start:], start=start):
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                end = i + 1
                break
    if end is None:
        return None
    try:
        payload = json.loads(raw[start:end])
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    tool = str(payload.get("tool") or "uml_invoke")
    if tool not in CALC_FAMILY_TOOLS:
        tool = "uml_invoke"
    inputs = payload.get("inputs") if isinstance(payload.get("inputs"), dict) else {}
    if "expression" not in inputs and payload.get("expression"):
        inputs = {**inputs, "expression": payload.get("expression")}
    return build_tool_request(
        tool=tool,
        inputs=inputs,
        source="gpu_mouth_request",
        note="parsed_from_gpu_draft",
    )


__all__ = [
    "ALLOWED_REQUEST_SOURCES",
    "ALLOWED_TOOLS",
    "APPROVAL_SEAL_LEDGER_PATH",
    "APPROVAL_SEAL_LEDGER_SCHEMA",
    "AUTHORITY_VERSION",
    "CALC_FAMILY_TOOLS",
    "CONSUMED_RID_LEDGER_PATH",
    "CONSUMED_RID_LEDGER_SCHEMA",
    "ENV_SEAL_HMAC_KEY",
    "ENV_SEAL_HMAC_KEY_FILE",
    "ENV_SEAL_HMAC_KEY_MODE",
    "ENV_SEAL_REQUIRE_RUST",
    "ENV_SEAL_RUST_BIN",
    "MINT_SEAL_LEDGER_PATH",
    "MINT_SEAL_LEDGER_SCHEMA",
    "SEAL_HMAC_KEY_META_PATH",
    "SEAL_HMAC_KEY_PATH",
    "build_tool_request",
    "ensure_approval_seal_ledger",
    "ensure_authority_ledgers",
    "ensure_consumed_rid_ledger",
    "ensure_mint_seal_ledger",
    "ensure_seal_hmac_key",
    "execute_approved_tool",
    "get_seal_hmac_key_status",
    "handle_tool_request",
    "mac_hex_with_key",
    "mint_cpu_tool_request",
    "parse_gpu_tool_request_from_text",
    "propose_calculator_from_query",
    "require_rust_seal",
    "reset_seal_hmac_key_cache",
    "resolve_viv_tool_seal_bin",
    "review_tool_request",
]
