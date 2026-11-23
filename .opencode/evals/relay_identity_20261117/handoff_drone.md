# 20261117 relay identity supervision

Bug: Check 7 accepted forged relay keys and altered metadata. Draft 1 hashed the key payload instead of comparing digest-to-digest; Draft 2 compared hash(payload) vs hash(claimed_key_string). Final correction: claimed_key is already a digest string, so canonical_hash(payload) must equal claimed_key directly.

Repair replaced relay-key/binding block to pop relay_key from payload, compare canonical_hash(payload) == claimed_key (string), find exactly one rows row with matching relay_key, load db_evidence, and require canonical_hash(db_evidence) == canonical_hash(typed_edge). Database contents and frozen checker unchanged.

Verification: 11/11 identity probes pass; 53 existing flag cases pass. Fresh self-check output: PASS: 8 checks. Provenance in .opencode/evals/relay_identity_20261117/review_receipt.json. Failed attempts retained in .opencode/evals/relay_identity_20261117/.