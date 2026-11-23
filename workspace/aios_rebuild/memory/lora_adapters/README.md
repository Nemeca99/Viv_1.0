# Chat learning data status

The old `realtime_lora_dataset.jsonl` is retained as historical, unreviewed
conversation data. It is **not an adapter**, is not connected to the training
commands, and must not be used as training input without the Dream quality,
correctness, truth, and Architect-admission gates.

The old `active_lora_manifest.json` claimed turns had been trained. Its exact
contents are preserved in `active_lora_manifest_legacy_snapshot_20260929.json`.
The corrected manifest records that the former chat path only appended data
and incremented a count; it did not update weights.

New chat turns go to `unreviewed_observations.jsonl` as append-only, hashed
observation events. They are not formatted as trainer rows and do not mutate
the status manifest or any adapter weights. Dream candidate training, when
explicitly invoked, writes a new adapter run under
`aios_rebuild/adapters/dream_candidate_runs/`; it does not promote that run.
