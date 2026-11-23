# Rust ↔ Python ↔ NumPy round-trip proof

## CPU and GPU placement proof

The Architect's placement rule is NumPy on the CPU/system RAM and CuPy on the
GPU/VRAM. Rust owns the CPU-side Swarm task and its acceptance decision; Python
is only the data bridge. `gpu_array_bridge` sends a bounded matrix task through
`gpu_switchboard.py`. `gpu_backend.py` creates NumPy host arrays, explicitly
uploads them to CuPy, computes matrix multiplication and broadcasting on the
GPU, and downloads the result to NumPy. Rust independently calculates all 16
expected cells and accepts or holds the response. The fault run changes one
returned cell and Rust holds it. These are placement and transport checks,
not a benchmark or a live Mind-model integration.

The GPU environment uses `requirements-gpu.txt`, which pins the CPU NumPy
requirement and the CuPy CUDA 13 wheel. To reproduce from the workspace root:

```powershell
hive_numpy_bridge\.venv\Scripts\python.exe -m pip install -r hive_numpy_bridge\requirements-gpu.txt
cargo run --offline --manifest-path hive_control\Cargo.toml --bin gpu_array_bridge -- L:\LocalCoder\workspace\hive_numpy_bridge\.venv\Scripts\python.exe L:\LocalCoder\workspace\hive_numpy_bridge\gpu_switchboard.py L:\LocalCoder\workspace\hive_numpy_bridge\artifacts\my_gpu_run\pass_receipt.json
```

Observed evidence is in `artifacts/gpu_placement_20260929_final1/`: `PASS`
for the normal transfer and `HOLD` for the injected cell fault. The measured
per-call times include CUDA setup for this tiny first workload and do not
establish a speed advantage over NumPy.

## Earlier NumPy-only numerical proof

This is an exactly-solvable toy linear-regression example, not a demonstration
of Viv training or general learning quality.

This bounded proof implements the locked division of labor:

- Rust owns the task gate, feedback decision, acceptance check, and receipt.
- Python is a bidirectional switchboard and owns no policy or authority.
- NumPy obtains fresh seed entropy from `SeedSequence`, creates the seeded
  synthetic arrays, and runs vectorized forward and gradient-update
calculations.

The recorded `SeedSequence` seed is for reproducing numerical test data only.
It is not an encryption key or cryptographic nonce; cryptographic material
must come from an operating-system CSPRNG under the separate Mind key boundary.

The Rust front end starts `python_switchboard.py` as a child process. The
switchboard calls `numpy_backend.py`, streams the first metrics to Rust, accepts
Rust's training feedback, streams the updated metrics back, and closes only
after Rust accepts or holds the result. This demonstrates the toy numerical
forward/gradient-update calculation and the macro system-level
request/feedback route using one Rust source file.

The backend covers typed arrays, shape, indexing, slicing, broadcasting,
vectorized arithmetic, reshape, `astype`, aggregation by axis, elementwise and
matrix multiplication, views/copies, random initialization, sampling/shuffling,
synthetic data, and explicit RNG state. The toy linear-regression math is
educational proof code, not a production learner or a live Viv integration.

Run from PowerShell:

```powershell
./run_proof.ps1
```

The script creates an isolated `.venv`, installs the pinned NumPy dependency,
runs the unit tests, checks Rust formatting, compiles with warnings denied,
executes the end-to-end bridge, and writes a timestamped evidence directory
under `artifacts/`. The evidence includes the random seed and generator state,
returned array shapes/dtype, forward and feedback losses, Rust acceptance,
source hashes, tool versions, and test logs.
