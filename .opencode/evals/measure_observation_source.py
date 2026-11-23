"""Measure the observation corpus's comprehension target against SODA fields.

Question: how often does SODA's `narrative` carry person/pronoun drift, and does
`literal` cover the same rows without it? Read-only; writes nothing.
"""
import re

import pyarrow.parquet as pq

SODA = "F:/Viv_Data/source_dialogue/allenai_soda_fdc848ab0183208ea7808206c91c724414d0a071/train.parquet"
PRON = re.compile(r"\b(he|she|his|her|him|hers)\b", re.I)
TURNS = 4

f = pq.ParquetFile(SODA)
cols = ["narrative", "literal", "speakers", "dialogue"]
seen = 0
usable = 0
has_literal = 0
narr_pron = 0
lit_pron = 0
narr_because = 0
rows = []
for batch in f.iter_batches(batch_size=512, columns=cols):
    for r in batch.to_pylist():
        narr = (r["narrative"] or "").strip()
        lit = (r["literal"] or "").strip()
        spk = r["speakers"] or []
        dlg = r["dialogue"] or []
        if not narr or len(dlg) < TURNS or len(spk) < TURNS:
            continue
        if len(set(spk[:TURNS])) < 2:
            continue
        seen += 1
        if lit:
            has_literal += 1
        if PRON.search(narr):
            narr_pron += 1
            if len(rows) < 12:
                rows.append((narr, lit))
        if lit and PRON.search(lit):
            lit_pron += 1
        if " because " in narr.lower():
            narr_because += 1
        if lit:
            usable += 1
        if seen >= 20000:
            break
    if seen >= 20000:
        break

print(f"usable rows sampled      : {seen}")
print(f"literal present          : {has_literal} ({100*has_literal/seen:.1f}%)")
print(f"narrative has pronoun    : {narr_pron} ({100*narr_pron/seen:.1f}%)")
print(f"literal has pronoun      : {lit_pron} ({100*lit_pron/seen:.1f}%)")
print(f"narrative has 'because'  : {narr_because} ({100*narr_because/seen:.1f}%)")
print("\n=== narratives carrying a pronoun, with their literal ===")
for n, l in rows:
    print(f"  narr: {n[:150]}")
    print(f"  lit : {l[:150]}")
