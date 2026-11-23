"""Queen-reviewed host probe for PrivacyCore's router database path decision."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


WORKSPACE_ROOT = Path(__file__).resolve().parents[1]
if str(WORKSPACE_ROOT) not in sys.path:
    sys.path.insert(0, str(WORKSPACE_ROOT))

from aios_rebuild.privacy_core.privacy_core import PrivacyCore


ROUTER_DB_PATH = Path(
    r"L:\LocalCoder\workspace\aios_rebuild\memory\aios_router\router.sqlite3"
)
DENIED_PROBE_PATH = Path(
    r"L:\LocalCoder\workspace\autonomy\privacy_core_router_db_gate_probe.sqlite3"
)
DECISION_SCHEMA = "privacy_core_file_write_decision_v1"


def _decision(core: PrivacyCore, target: Path) -> dict[str, object]:
    raw = core.authorize_file_write(target)
    if not isinstance(raw, dict) or not isinstance(raw.get("allowed"), bool) or not isinstance(raw.get("reason"),str):
        return {
            "schema": DECISION_SCHEMA,
            "target_path": str(target),
            "allowed": False,
            "reason": "privacy_core_decision_invalid",
            "authority": "PrivacyCore.authorize_file_write",
        }
    fixed_paths={str(ROUTER_DB_PATH)+suffix for suffix in ('','-wal','-shm','-journal')}
    in_scope=str(target) in fixed_paths
    allowed=raw['allowed'] is True and in_scope
    return {
        "schema": DECISION_SCHEMA,
        "target_path": str(target),
        "allowed": allowed,
        "reason": "file_write_policy_passed" if allowed else (raw['reason'] if in_scope else 'router_adapter_target_outside_fixed_paths'),
        "raw_privacy_core":raw,
        "authority": "PrivacyCore.authorize_file_write",
    }


def router_db_decision() -> dict[str, object]:
    """Authorize the database and SQLite sidecars at one fixed destination."""
    core = PrivacyCore()
    paths = [
        ROUTER_DB_PATH,
        ROUTER_DB_PATH.with_name(ROUTER_DB_PATH.name + "-wal"),
        ROUTER_DB_PATH.with_name(ROUTER_DB_PATH.name + "-shm"),
        ROUTER_DB_PATH.with_name(ROUTER_DB_PATH.name + "-journal"),
    ]
    checks = [_decision(core, path) for path in paths]
    allowed = all(
        item["allowed"] is True and item["reason"] == "file_write_policy_passed"
        for item in checks
    )
    return {
        "schema": DECISION_SCHEMA,
        "target_path": str(ROUTER_DB_PATH),
        "allowed": allowed,
        "reason": "file_write_policy_passed" if allowed else "sqlite_path_policy_denied",
        "authority": "PrivacyCore.authorize_file_write",
        "checked_paths": [
            {
                "path": item["target_path"],
                "allowed": item["allowed"],
                "reason": item["reason"],
                "raw_privacy_core":item.get('raw_privacy_core'),
            }
            for item in checks
        ],
    }


def self_check() -> tuple[bool, dict[str, object], dict[str, object]]:
    """Check one allowed destination and one outside-root denial without writing."""
    core = PrivacyCore()
    allowed = router_db_decision()
    denied = _decision(core, DENIED_PROBE_PATH)
    passed = (
        allowed["allowed"] is True
        and len(allowed["checked_paths"]) == 4
        and denied["allowed"] is False
        and denied["reason"] == "router_adapter_target_outside_fixed_paths"
    )
    return passed, allowed, denied


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--self-check", action="store_true")
    mode.add_argument("--authorize-router-db", action="store_true")
    args = parser.parse_args(argv)

    if args.authorize_router_db:
        decision = router_db_decision()
        print(json.dumps(decision, sort_keys=True))
        return 0 if decision["allowed"] is True else 2

    passed, allowed, denied = self_check()
    if passed:
        print("PASS: exact router adapter retains real PrivacyCore decisions and denies outside fixed paths")
        return 0
    print(json.dumps({"allowed_probe": allowed, "denied_probe": denied}, sort_keys=True))
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
