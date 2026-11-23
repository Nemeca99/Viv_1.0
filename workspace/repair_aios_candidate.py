"""Apply guarded, hash-receipted compatibility repairs to a run candidate."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise ValueError(f"{label}: expected one exact source anchor, found {count}")
    return text.replace(old, new, 1)


def repair(candidate: Path, source: Path, receipt_path: Path) -> dict[str, Any]:
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    claimed = receipt.pop("receipt_sha256", None)
    canonical = json.dumps(receipt, ensure_ascii=False, sort_keys=True).encode("utf-8")
    if claimed != sha(canonical) or receipt.get("status") != "PASS":
        raise ValueError("parent transform receipt is invalid or not PASS")
    receipt["receipt_sha256"] = claimed
    changes: list[dict[str, str]] = []

    response_rel = "luna_core/core/response_generator.py"
    response = candidate / response_rel
    before = response.read_bytes()
    text = before.decode("utf-8").replace("\r\n", "\n")
    text = replace_once(text, "from datetime import datetime\n", "from datetime import datetime\nimport weakref\n", "weakref import")
    init_anchor = "    def __init__(self, personality_system: LunaPersonalitySystem, logger, carma_system=None):\n"
    init_guard = (
        init_anchor
        + "        owner = type(self)\n"
        + "        previous_ref = getattr(owner, '_drift_instance_ref', None)\n"
        + "        previous_instance = previous_ref() if previous_ref is not None else None\n"
        + "        if previous_instance is not None:\n"
        + "            raise RuntimeError(\n"
        + "                'DUPLICATE DriftMonitor DETECTED! Only ONE live ResponseGenerator is allowed.'\n"
        + "            )\n"
        + "        if hasattr(owner, '_drift_instance_count'):\n"
        + "            delattr(owner, '_drift_instance_count')\n"
    )
    text = replace_once(text, init_anchor, init_guard, "lifecycle guard entry")
    old_guard = '''        # V5.1: Assert singleton DriftMonitor (auditor requirement - fail hard on duplicate)
        if hasattr(self, 'drift_monitor') and self.drift_monitor:
            if hasattr(self.__class__, '_drift_instance_count'):
                raise RuntimeError(
                    "DUPLICATE DriftMonitor DETECTED! "
                    "Only ONE instance allowed per ResponseGenerator class. "
                    "Check HybridLunaCore and ResponseGenerator init sequences."
                )
            self.__class__._drift_instance_count = 1
'''
    new_guard = '''        # Track one live generator; release the guard when its weak reference dies.
        if self.drift_monitor:
            self.__class__._drift_instance_ref = weakref.ref(self)
            self.__class__._drift_instance_count = 1
'''
    text = replace_once(text, old_guard, new_guard, "stale class flag replacement")
    response.write_text(text, encoding="utf-8", newline="\n")
    changes.append({
        "path": response_rel,
        "source_sha256": sha((source / response_rel).read_bytes()),
        "before_candidate_sha256": sha(before),
        "after_candidate_sha256": sha(response.read_bytes()),
        "transform": "live_weakref_single_generator_guard",
    })

    tests_rel = "tests/test_creative_integration.py"
    tests_path = candidate / tests_rel
    before = tests_path.read_bytes()
    tests = before.decode("utf-8").replace("\r\n", "\n")
    old_test = '''def test_creative_config_backward_compat():
    """Old configs without creative_mode must load cleanly with defaults"""
    from data_core.data_core_unified import DataCore
    
    dc = DataCore()
    cfg = dc.load_config()
    
    # Should have creative_mode with defaults (auditor requirement)
    assert "creative_mode" in cfg
    assert cfg["creative_mode"].get("enabled") == False  # Default disabled
'''
    new_test = '''def test_creative_config_backward_compat(tmp_path, monkeypatch):
    """A config with no creative_mode uses a disabled backward-compatible default."""
    from data_core.data_core_unified import DataCore

    monkeypatch.chdir(tmp_path)
    dc = DataCore(use_hybrid=False)
    cfg = dc.load_config()
    assert cfg["creative_mode"].get("enabled") is False


def test_creative_config_preserves_explicit_enablement(tmp_path, monkeypatch):
    """Explicit user configuration must override the disabled default."""
    from data_core.data_core_unified import DataCore

    monkeypatch.chdir(tmp_path)
    dc = DataCore(use_hybrid=False)
    dc.config_dir.mkdir(parents=True, exist_ok=True)
    (dc.config_dir / "aios_config.json").write_text(
        json.dumps({"creative_mode": {"enabled": True}}), encoding="utf-8"
    )
    assert dc.load_config()["creative_mode"]["enabled"] is True
'''
    tests = replace_once(tests, old_test, new_test, "creative config test contract")
    tests_path.write_text(tests, encoding="utf-8", newline="\n")
    changes.append({
        "path": tests_rel,
        "source_sha256": sha((source / tests_rel).read_bytes()),
        "before_candidate_sha256": sha(before),
        "after_candidate_sha256": sha(tests_path.read_bytes()),
        "transform": "isolate_default_and_explicit_creative_config_contract_tests",
    })

    smoke_rel = "tests/test_creative_smoke.py"
    smoke_path = candidate / smoke_rel
    before = smoke_path.read_bytes()
    smoke = before.decode("utf-8").replace("\r\n", "\n")
    mock_config = '''    rg.aios_config = {"creative_mode": {"enabled": True}}
    
    # Generate creative text
'''
    parity_config = '''    rg.aios_config = {"creative_mode": {"enabled": True}}
    rg.creative_index_ok = True  # mocked retrieval represents a parity-approved index

    # Generate creative text
'''
    smoke = replace_once(smoke, mock_config, parity_config, "mock creative parity precondition")
    smoke_path.write_text(smoke, encoding="utf-8", newline="\n")
    changes.append({
        "path": smoke_rel,
        "source_sha256": sha((source / smoke_rel).read_bytes()),
        "before_candidate_sha256": sha(before),
        "after_candidate_sha256": sha(smoke_path.read_bytes()),
        "transform": "mock_parity_approval_for_fake_creative_retrieval",
    })

    receipt["transforms"].extend(changes)
    receipt["transformed_file_count"] = len(receipt["transforms"])
    receipt.pop("receipt_sha256", None)
    unsigned = json.dumps(receipt, ensure_ascii=False, sort_keys=True).encode("utf-8")
    receipt["receipt_sha256"] = sha(unsigned)
    receipt_path.write_text(
        json.dumps(receipt, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    return {"status": "PASS", "changes": changes, "receipt_sha256": receipt["receipt_sha256"]}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate", required=True, type=Path)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--receipt", required=True, type=Path)
    args = parser.parse_args()
    result = repair(args.candidate.resolve(), args.source.resolve(strict=True), args.receipt.resolve())
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
