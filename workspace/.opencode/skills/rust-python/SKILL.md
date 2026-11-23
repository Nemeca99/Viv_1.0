---
name: rust-python
description: Use when exploring, changing, debugging, or validating Rust or Python code in the current project.
---

## Workflow

- Start from the current working directory. Read project instructions and the relevant manifest before deciding how the project is built.
- Find the smallest relevant set of files. Follow existing conventions and keep changes inside the authorized project.
- Before Python commands, verify the active interpreter with `python -c "import sys; print(sys.executable)"`. OpenCode's shell hook selects the nearest project virtual environment, with `L:\Python_Master\.venv` as the clean fallback; the moved `D:\LocalAi\Continue` tree uses its preserved Viv environment at `L:\.venv`.
- Keep the shared fallback environment minimal. Do not install project-specific dependencies into it; use the project's own virtual environment after reading its manifest.
- For Rust, inspect `Cargo.toml`, workspace members, feature flags, and the existing test/check commands before running Cargo. Do not assume a single-crate layout.
- For Python, inspect `pyproject.toml`, requirements files, package layout, and configured tools before choosing an interpreter or command. Prefer the project environment when present.
- Reproduce the reported behavior with the smallest relevant check. Run appropriate checks after a code change when available and proportionate.
- If a check cannot run, report the exact blocker. Do not claim a test, build, formatter, or linter passed unless its output confirms that.
- Explain the behavior changed, files touched, and verification performed. Separate observed facts from likely causes.
