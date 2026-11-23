# Stage 1 file preparation substrate

`prepare.py` stages a single task-scoped Python source file in a new run folder.
It keeps the original untouched, applies Black only to the staged copy, and
records original/prepared SHA-256 hashes and a unified diff. Ruff checks syntax,
indentation, imports, and unused names; Vulture checks high-confidence unused
code. A compile check runs without executing the module. Any finding yields
`HOLD` in the receipt. No linter applies a semantic fix automatically.

This is a file hygiene proof, not the full Stage 1 gate. Rust still needs to
bind a complete task packet, grant, dependency state, and this prepared hash
before dispatch. Rust code uses `cargo fmt --check` and `cargo clippy -- -D
warnings`; the Cargo manifest is in `hive_control/`.

From the workspace root:

```powershell
.hive_proof_env\Scripts\python.exe hive_quality\prepare.py template_rebuild\reference\fixture_echo.py
```
