# Rules: Master Record Security Contract (v0.3 Spec)

## The Fundamental Isolation Boundary

```
+------------------------------------------------------------------------------+
| TRANSFORMER (LLM / Python)                                                   |
| - RESTRICTION: Touches ONLY the Master Record Index (_drive_index/*.jsonl).  |
| - CANNOT TOUCH: Real OS filesystem, user files, binaries.                    |
| - FUNCTION: Proposes file additions, modifications, deletions in the Index.  |
+------------------------------------------------------------------------------+
                                       |
                                       | Tool Request RPC Payload
                                       v
+------------------------------------------------------------------------------+
| RUST SYMBOLIC CORE (Rules Engine at L:\Rules)                                |
| - PRIVILEGES: Full OS Filesystem & Quarantine execution rights.              |
| - FUNCTION: Compares Index proposal vs Real OS State & User Approval.        |
|                                                                              |
|       [ APPROVED ] -------> Rust performs actual OS read/write/move.        |
|       [ DENIED   ] -------> Rust blocks operation. OS remains untouched.     |
+------------------------------------------------------------------------------+
```

## Layer 0 Ground Rules

1. **The Master Record Index is Truth:** Every drive maintains its index at `<drive>:\_drive_index\index_<timestamp>.jsonl`.
2. **Model Sandbox Isolation:** The AI Model operates exclusively on index state. It never issues raw `open()`, `write()`, or `unlink()` operations on actual disk paths.
3. **Rust Execution Monopoly:** Only compiled Rust code (`rules_core.exe`) is granted OS file-descriptor write handles.
4. **Drift Resolution:** If real disk state disagrees with the Master Record Index, the Rust engine flags a drift warning for user review.
