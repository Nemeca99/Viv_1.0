Architect-approved assignment under goal `01a1d847-3b27-7533-bbc2-c718ace48ae7`.

Add exactly one Python file at `workspace/autonomy/privacy_core_router_db_gate.py`. First call the `localcoder_add_python` tool to add that file, then call the `shell` tool to run its check.

Purpose: create a host-side probe for the existing `aios_rebuild.privacy_core.privacy_core.PrivacyCore`. Pin the only router database target to `L:\LocalCoder\workspace\aios_rebuild\memory\aios_router\router.sqlite3`. The helper must call `PrivacyCore.authorize_file_write()` for that target and report the returned decision as JSON. Add a self-check that confirms this pinned path is allowed and a path under `L:\LocalCoder\workspace\autonomy` is denied. The helper only computes policy decisions; it must not create directories/files, open SQLite, write receipts, or change policy/configuration.

Use `L:\.venv\Scripts\python.exe -B` from `L:\LocalCoder\workspace` to run the new file. Keep the script small and deterministic. Do not touch any other project file or model setting. Final response must begin `[DRONE]` and state the exact shell output and any failure.
