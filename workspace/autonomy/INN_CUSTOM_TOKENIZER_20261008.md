# Custom Unicode tokenizer in the INN

The source tokenizer was copied unchanged from
`D:/LocalAi/Continue/Viv/foundation/lib/uml_character_tokenizer.py` into
`INN/inn/uml_character_tokenizer.py`. Both SHA-256 hashes are
`e4bf78e15637797e597d431eaf0b71a57b842393ef82d898f772f63bc7cd8a5c`.
Its universal character IDs remain the source of character identity.

`INN/inn/tokenizer.py` supplies a frozen compact neural vocabulary. The proof
uses 133 character rows plus PAD/BOS/EOS, and a 512-token context. It rejects
unknown active characters rather than silently dropping or replacing them.
The universal encoder still supports all valid Unicode scalar values.
Vocabulary discovery uses training data only; model indices are a separate
mapping from universal IDs, sealed in the checkpoint contract.

`LanguageEngine` now accepts that tokenizer and configurable context. It
copies the parent attention and farm tensors. ASCII character rows and
special rows copy exactly; multibyte character rows initially average their
parent UTF-8 byte rows and then receive learned updates. This initialization
does not prove Unicode semantics transfer. Optimizer state starts fresh.
Legacy byte checkpoints and live proposal behavior remain compatible.

## Measured proof

- 500 updates: old descriptions 20/20; Unicode-labelled descriptions 0/60
  before training to 54/60 afterwards. Failed the 95% gate, preserved at
  `learning/tokenizer_runs/20261008T221946491620Z`.
- 1000 updates from the same immutable parent: old descriptions 20/20;
  Unicode-labelled descriptions 0/60 to 60/60 on plot 43. Passed, preserved
  at `learning/tokenizer_runs/20261008T222047835122Z`.
- The second budget was chosen after the first failure. Plot 43 supplies new
  prompt IDs, but these are the same farm rule combinations and sentence
  templates. This is a narrow compatibility and learning proof, not unseen
  grammar, multilingual understanding, or broad structural generalization.
- Unicode roundtrips and checkpoint reload passed. Parent checkpoint and
  admission pointer hashes remained unchanged. No farm behavior evaluation
  or live activation was performed for these language-only candidates.
- Wikipedia ingestion, whole-word heads, and BPE heads are not implemented
  by this character integration.

From `L:/LocalCoder`:

```powershell
.\Rebuild-INNTokenizer.ps1 -Updates 1000 -FinalPlot 43
.\Speak-INNTokenizer.ps1 -Prompt "José: plot=43 stage=WATER2 tool=HARVEST`nDescribe:`n"
```

The first command is bounded and requires the Hive paused. It never resumes
continuous farm execution. The second loads the saved candidate, verifies
checkpoint and tokenizer hashes, and generates through neural logits.
Streamlit's Learning history shows status and actual before/after counts.
