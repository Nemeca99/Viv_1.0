# Python environment map

## LocalCoder selection — 2026-10-08

The Architect selected `L:\.venv` as the base environment for LocalCoder.
`Start-Coder.ps1` and the scoped `L:\LocalCoder` OpenCode environment override
now use it. The INN build and run scripts invoke `L:\.venv\Scripts\python.exe`
explicitly. The older shared-fallback inventory below remains historical.

Inventory date: 2026-09-27. The L: scan looked for `pyvenv.cfg`, skipped Git metadata, package caches, recycle/system folders, and reparse points, and did not inspect or change installed packages except for read-only `pip check` probes.

## Shared environment policy

- `L:\Python312\python.exe` is the clean Python 3.12.10 base interpreter; `python -m pip check` reports no broken requirements.
- `L:\Python_Master\.venv` is the clean shared fallback for Coder and projects without a local environment. It is intentionally minimal; keep project packages out of it.
- When Coder runs a shell command, the global OpenCode hook selects the nearest project `\.venv`, `\venv`, or `\env`. It also recognizes a unique custom `*-venv` folder. If no project environment exists, it uses the shared fallback.
- `D:\LocalAi\Continue` is an explicit compatibility exception: it uses its preserved environment at `L:\.venv`, as the moved Viv/AIOS profile did before relocation.
- Existing project environments remain separate. They use different Python versions and packages; they were not merged, upgraded, or removed.

## Existing environments found on L:

| Environment | Python base | Notes |
|---|---|---|
| `L:\.venv` | `L:\Python312`, 3.12.10 | Continue/Viv environment retained for compatibility. `pip check` reports dependency conflicts and platform support warnings; do not use as a universal environment. |
| `L:\AI_Models\huggingface\cli\venv` | `L:\Python312`, 3.12.10 | Hugging Face CLI environment. |
| `L:\MiniMind-Kit\.venv` | `L:\Python312`, 3.12.10 | Project environment. |
| `L:\Standalone\NN\.venv` | Codex runtime Python, 3.12.13 | Separate project environment. |
| `L:\Standalone\Simulacra\Simulacra Evolution\DigitalEvolve\backend\venv` | Python 3.11 | Separate project environment. |
| `L:\Standalone\Simulacra\Simulacra Evolution\RTS_Game\venv` | Python 3.11 | Separate project environment. |
| `L:\Standalone\Simulacra\Simulacra Evolution\Simulacra\venv` | Python 3.11 | Separate project environment. |
| `L:\Standalone\Simulacra\Simulacra_v2\.venv` | `D:\AI`, Python 3.13.3 | Separate project environment. |
| `L:\The` | `L:\Python312`, 3.12.10 | Environment at the drive-root directory; preserve until its owning project is identified. |
| `L:\The House\.venv` | `L:\Python312`, 3.12.10 | Project environment. |
| `L:\The House\deepseek_training\.movie-scripts-venv` | `L:\Python312`, 3.12.10 | Custom-named environment; recognized by the Coder hook when it is the only custom `*-venv` in that project directory. |
| `L:\The House\House\semantic_memory\.venv` | `L:\Python312`, 3.12.10 | Project environment. |

The inventory establishes environment locations and interpreter versions, not that every environment is healthy. Dependency reconciliation should happen within each project after reviewing its manifest and lock files.

## PowerShell and Coder entry points

- The current-user PowerShell loader now loads the moved profile from `D:\LocalAi\Continue\Viv\foundation\powershell\Viv-AIOS.Profile.ps1`. Its Viv root and helper paths were updated to the moved tree, with the Continue interpreter retained at `L:\.venv`.
- `Start-Coder.ps1` activates `L:\Python_Master\.venv`, sets the Coder config explicitly, and starts OpenCode in the requested project directory. The global OpenCode `shell.env` plugin then selects that project's virtual environment for tool commands.
- The profile loader, Viv profile, and VM inventory helper each have a timestamped `.bak` beside the original. The VM inventory helper's old Continue paths now point to D:, including its receipt destination; its proposed VM storage root remains `L:\VivVM`.
- Verified the moved profile loads in a fresh PowerShell process without the missing-profile warning, with `VIV_ROOT=D:\LocalAi\Continue\Viv`, `VIV_PYTHON=L:\.venv\Scripts\python.exe`, and the `viv` alias available.
- No existing project's virtual environment or installed packages were changed.
