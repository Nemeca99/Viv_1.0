"""Bridge the live learner to AIOS Backup Core's Git-like history.

Only the small checkpoint-head manifest is committed here. Snapshot databases
remain content-addressed run artifacts and are archived separately after hash
verification; this keeps the active learner lightweight while preserving
rollback/compare lineage.
"""
from __future__ import annotations

import json
import importlib.util
import os
import sys
from datetime import datetime, timezone
from pathlib import Path


def _backup_package_root() -> Path:
    configured = os.environ.get("AIOS_BACKUP_ROOT")
    if configured:
        return Path(configured).resolve()
    # workspace/autonomy -> L:\LocalCoder -> L:\AIOS
    return Path(__file__).resolve().parents[2].parent / "AIOS"


class CheckpointBackup:
    """Commit checkpoint lineage through the existing Backup Core."""

    def __init__(self, learning_root: Path, *, backup_root: Path | None = None):
        self.learning_root = Path(learning_root).resolve()
        root = (backup_root or _backup_package_root()).resolve()
        if not (root / "backup_core" / "__init__.py").is_file():
            raise FileNotFoundError(f"AIOS Backup Core not found: {root}")
        package_dir = root / "backup_core"
        spec = importlib.util.spec_from_file_location(
            "aios_git_backup_core",
            package_dir / "__init__.py",
            submodule_search_locations=[str(package_dir)],
        )
        if spec is None or spec.loader is None:
            raise ImportError(f"Unable to load Backup Core package: {package_dir}")
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        BackupCore = module.BackupCore

        self._backup = BackupCore(workspace_root=self.learning_root)
        self.manifest_path = self.learning_root / "checkpoint_heads.json"

    def record_head(self, snapshot: Path, parent: Path | None = None) -> str:
        """Record the active and comparison checkpoint, returning commit hash."""
        snapshot = Path(snapshot).resolve()
        if not snapshot.is_dir():
            raise FileNotFoundError(snapshot)
        record = {
            "schema": "viv_checkpoint_heads_v1",
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "active": str(snapshot),
            "parent": str(Path(parent).resolve()) if parent else None,
        }
        temp = self.manifest_path.with_suffix(".json.tmp")
        temp.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
        os.replace(temp, self.manifest_path)
        self._backup.add(paths=[self.manifest_path.name])
        commit = self._backup.commit(
            f"checkpoint: {snapshot.name}", author="Viv learner"
        )
        if not commit:
            raise RuntimeError("Backup Core did not create checkpoint commit")
        return str(commit)

