# AIOS code-template rebuild slice

This is an isolated LocalCoder rebuild of the legacy `fixture.echo` template
path. The reference is a byte-for-byte copy of
`D:\LocalAi\Continue\Viv\foundation\code_templates\source\fixture_echo.py`
with SHA-256 `8F84915A7C291691F6E5A5028B75E7E43573A68AF7F46CD91CE46CF1774FA82C`.
The moved Viv tree is read only.

The live Qwen3 8B Mind returns a four-task plan and the two declared variable
values. Rust checks the plan, seals each task snapshot, approves only a run-local
write, and dispatches four deterministic Swarm stamps: imports, `VARIABLES`,
function, then registry. The source outside `VARIABLES` is copied exactly from
the pinned reference. A Python posthoc verifier checks registry binding,
unchanged source spans, compilation, and an explicit `main` call. It does not
activate the generated template as a live AIOS component.

`runtime.py` is a manually built read-only consumer for this slice. It checks
the registry hash and protected source spans before import, and calls `main`
only through `TemplateRuntime.execute()`. The Hive stamped the generated
template and registry; it did not author this consumer runtime.

To repeat the proof from the workspace root:

```powershell
cargo run --offline --manifest-path hive_control\Cargo.toml --bin template_rebuild -- L:\LocalCoder\workspace\hive_numpy_bridge\.venv\Scripts\python.exe live
cargo run --offline --manifest-path hive_control\Cargo.toml --bin template_rebuild -- L:\LocalCoder\workspace\hive_numpy_bridge\.venv\Scripts\python.exe fixture --inject-parent-fault
L:\LocalCoder\workspace\hive_numpy_bridge\.venv\Scripts\python.exe -m unittest discover -s template_rebuild -p test_verify_run.py -v
```

The live receipt is `runs/1790639286606457600/receipt.json`; the fault receipt
is `runs/1790639297250871900/receipt.json`. The latter holds the function
task when the parent artifact changes. This proves one small template
composition path and its boundary. It does not port the legacy builder,
generation pointer, function index, Rust production write membrane, or the
many migrated templates.
