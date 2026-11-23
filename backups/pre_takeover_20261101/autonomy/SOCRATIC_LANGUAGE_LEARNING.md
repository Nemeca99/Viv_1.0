# Viv spelling and sentence lessons

## Persistent neuron-route learning

Run `L:\LocalCoder\Learn-Viv.ps1` to watch the existing native learner attempt word
and sentence routes. The terminal shows word flashcards, Viv's response, and the
tutor's accept/deny decision. It also shows sentence-route guesses and exact-order
feedback. After accepted checks exceed denied checks and the sentence route passes,
the tutor asks Viv to spell a learned word and evaluates that neural recall. The
Architect may provide the next lesson only after this follow-up passes. `/quit`
stops; restarting resumes the latest committed route-learning snapshot. Each input
is bounded to 24 attempts per lesson by default. Unfinished sentence episodes
retain their native state for the next session. The graph, word-curriculum evidence,
score, follow-up result, and raw attempts are saved together.

This uses `UniversalCurriculumEngine` for words and `Neuronizer` for sentences.
The CPU judge checks the order of the observed input; it does not call every other
ordering grammatically wrong. Follow-up cards only test spelling recall of a word
already present in the lesson; they do not establish transfer to novel vocabulary.
New inputs provide further learning opportunities. The original graph and live
language-model pointer remain unchanged.

Rust accepts only `neuron_graph.sqlite3` and `curriculum.sqlite3` as additional named
artifacts within the existing INN lease. They must be complete standalone SQLite
snapshots; arbitrary SQLite names and WAL-dependent images are rejected. Learning
uses RAM clones; snapshots are integrity-checked, written by Rust, reloaded, and
checked before commit. No ordinary filesystem allowlist is widened.

SQLite serialization can retain the source WAL-mode header after an online backup
to RAM. The adapter follows SQLite's documented [deserialize guidance](https://www.sqlite.org/c3ref/deserialize.html)
to normalize the two journal-version bytes in the complete serialized image, then
deserializes it and checks integrity before Rust writes it. It never copies a live
database file while ignoring its WAL.

## Earlier decoder pilot

Run from `L:\LocalCoder\workspace`:

```powershell
& 'L:\.venv\Scripts\python.exe' run_autonomous_socratic_tutor.py --learn-language --updates 300
```

This mode continues the verified Unified Viv language checkpoint in memory. It
teaches five word spellings and complete sentences, including the failed `wave`
practice, plus twelve elementary noun/verb combinations. Four other combinations
are reserved for evaluation. These are explicitly authored English lessons;
historical tutor responses are not automatically accepted as training targets.

The existing INN language engine trains using its existing architecture and
optimizer. Prior spelling and meaning lessons are replayed. The WSL/Docker Body
checks runtime permission throughout, and Rust owns candidate artifact writes and
commit. The checkpoint is saved and reloaded before the final behavioral test.

A candidate passes only with all five spellings and taught sentences correct,
at least three of four fresh combinations correct with improvement over its
parent, and at least 95% retention of previously correct spelling/meaning checks.
Passing this small development test would not establish general language mastery.

Results, raw outputs, lessons, parent hashes, and the checkpoint are kept in a
`language-*` directory under `autonomy/learning/neural_runs`. Failure can leave
evidence in `neural_candidate_staging`. No live checkpoint pointer is changed.
An exit code of 2 means the candidate did not pass its behavioral gate.

The ordinary Socratic practice mode remains available. Its unknown-word
definition dialogue and Architect review queue do not automatically admit new
meanings or consume these language candidates. Live promotion and an adaptive
tutor-feedback training loop remain separate integration work.
