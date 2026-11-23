# Vague-goal Hive probe, 2026-09-29

Goal in both runs: `Create a file. Have it do something.` The user did not specify
a filename, output string, or task sequence. Viv was shown an isolated Python
capability menu and a read-only Foreman routing snapshot. The Rust controller
validated the graph, stamped template code, checked parent artifact hashes,
ran the file, and retained receipts. No repair generation was used.

| Run | Menu change | Viv's plan | Observed file/output |
| --- | --- | --- | --- |
| `mind-vague-1790709121822693800` | Direct print available | create → stamp print → run | `example.py`; `Hello, world!` |
| `mind-vague-1790709250463746800` | Direct print removed | create → stamp function → stamp call → run | `example.py`; `Hello, world!` |

The first plan used the shortest path available. The second changed the task
graph to fit the narrower menu while keeping the same behavior. Both Python
files compiled and executed. The Rust tests, Clippy, Python bridge lint, and
manifest integrity check passed. Each run has raw Mind plan and final
transcripts, a Swarm task transcript, an artifact, a receipt, and a played WAV
with a text transcript; paths and SHA-256 hashes are in `HIVE_LOCK_MANIFEST.json`.

This establishes a bounded plan → dispatch → artifact → observation path. It
does not measure broad creativity or coding quality: the menu exposes only
printing, and the controller requires an executable stamp pattern. `Hello,
world!` in both runs is an observation, not evidence of task understanding
beyond this probe. The next useful change is a richer capability substrate or
an external read-only source, while keeping this vague goal and comparing raw
plans and actual outputs. The optional F: Wikipedia database was not accessed
in these two runs.
