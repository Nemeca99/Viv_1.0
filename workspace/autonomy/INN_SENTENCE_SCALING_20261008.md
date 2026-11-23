# Wikipedia sentence learning: first scaling pilot

Source: `F:/AI_Datasets/wikipedia_deduplicated`. Source files stay on F:;
all preparation, training, and checkpoints run under LocalCoder on L:.
No full-corpus conversion or continuous worker was started.

## Preparation and curriculum

The bounded scanner accepted 80 article leads. Redirects are excluded;
templates, references, file captions, and math are removed using the existing
mwparserfromhell dependency. Suspect markup leftovers and long sentences are
excluded. The dataset contains 329 training, 45 validation, and 48 test
sentences. Canonical lead hashes assign entire articles to one split before
training; identical original/reduced targets across splits are excluded.

Each row retains original prose, a reduced conjunction-deletion view, and
removed words with original character spans. This is a mechanical version
of the requested two-view corpus. It is not a semantic summary or a guarantee
that deletion preserves meaning. Sentence order and negation remain present.

The current pilot uses the Architect's custom character tokenizer, with
170 active character/special rows and 512-token context. Explicit migration
copies shared INN blocks and known character rows by identity; new rows are
initialized independently. The frozen tokenizer manifest binds the checkpoint.
Whole-word/BPE representations remain future work. The structure pass is
closed pending a separate reduced-sentence generation quality evaluation.

## Recorded experiments

All runs resume the same immutable tokenizer parent. AdamW LR is 0.0002,
CPU threads 2, sentence batches 8, deterministic article/sentence traversal.

| Updates | Prior replay | Test NLL before/after | Prior exact sentences |
|---|---|---|---|
| 600 | Every fifth update | 10.242 / 2.891 | 56/80 |
| 600 | Every second update | 10.242 / 2.945 | 80/80 |
| 2000 | Every second update | 10.242 / 2.759 | 79/80 |

First run failed retention. Second and third passed the numerical prediction
and retention gate, not a fluent-generation gate. All sampled continuations
remain fragmented and repetitive. The third output after
`Algeria, officially the ` starts `the athe te are the the...`.
No factual sentence-generation success is established. Holdouts became
development evaluations after inspecting first-run results and choosing
replay/budget changes; a future acceptance evaluation needs a fresh set.

Preserved runs:

- `learning/sentence_runs/20261008T223241501122Z`
- `learning/sentence_runs/20261008T223402799121Z`
- `learning/sentence_runs/20261008T223516995659Z`

The third checkpoint independently reloaded with identical generated samples,
test NLL, and 79/80 retention. Its checkpoint, tokenizer, corpus, and parent
hash checks passed in `reload_recheck.json`. Neither parent checkpoint nor
the admitted farm pointer changed. All pilots finished with the farm paused.

## Entry points

From `L:/LocalCoder`:

```powershell
.\Train-INNSentences.ps1 -Articles 80 -Updates 2000 -RetentionEvery 2
```

This remains a pilot capped at 500 accepted articles, 1500 scanned files,
2000 updates, and 600 seconds for the update loop. It starts from the verified
tokenizer parent, not from a failed sentence candidate. The latest status and
actual continuation samples appear in Streamlit's Learning history. Training
targets are derived from source text, not from Queen replies or invented facts.

The next work must address generated word/sequence quality and re-evaluate
the requested first-pass representation; blindly increasing article count
has not been justified by this pilot.
