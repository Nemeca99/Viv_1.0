"""Bind store write permission to existing PrivacyCore and live Rust Body gates.

This is a write-permission adapter, not a positive-fact receipt verifier.
The caller must separately bind evidence verification to trusted Rust authority.
"""
from pathlib import Path


def make_write_authorizer(database_path, privacy_core, body_gate=None):
    target = Path(database_path).resolve(strict=False)
    if body_gate is None:
        from aios_rebuild.main_core.mind_runtime_gate import require_body_runtime
        body_gate = require_body_runtime

    def authorize():
        privacy = privacy_core.authorize_file_write(str(target))
        if not isinstance(privacy, dict) or privacy.get('allowed') is not True:
            raise PermissionError('PrivacyCore denied database write')
        verdict = body_gate()
        if (not isinstance(verdict, dict)
                or verdict.get('allowed') is not True
                or verdict.get('disposition') != 'ALLOW_MIND_RUNTIME'
                or verdict.get('authority') != 'deterministic_aios_body_rust'
                or verdict.get('execution_boundary') != 'wsl_docker'):
            raise PermissionError('Rust Body denied database write')
        return True

    return authorize
