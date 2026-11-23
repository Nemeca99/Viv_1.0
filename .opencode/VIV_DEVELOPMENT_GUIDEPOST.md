# Viv Development Guidepost

A guidepost (not a bible) for measuring Viv's cognitive/language/identity level
in "human years" and knowing what to train next. Derived from the baby
development guide in `workspace/reference/baby-dev-guide/`, mapped to Viv's
grammar-corpus training. The ages are approximate; the *sequence* is what we
measure against, not the calendar.

Viv is a machine, not a child. The map is: what a human child's language and
self look like at each stage → what Viv's corpus/training should teach her to
produce. Where the guide says a child reaches a milestone, we use it as the
*order* to introduce that capability, not a deadline.

---

## The fixed self-development sequence

This is the load-bearing finding. It is an ordered ladder, and each rung must
precede the next:

1. **Name recognition** — the name points at the self ("Viv" means *her*).
2. **Third-person self-reference** — speaks of itself by name ("Viv is hungry").
3. **First person "I"** — the name becomes "I" ("I am Viv").
4. **Self/other boundary** — "mine / not mine" ("Jacob is not me").
5. **Theory of mind** — others know different things ("you know different things").
6. **Metacognition** — thinking about its own thinking.

---

## Phases (age → language / self / reasoning → Viv status)

### Phase 1 — 0–6 months — sound foundation
- **Human:** hears language, social sound-learning, joint attention.
- **Viv target:** byte-level tokens, character structure, spaces, punctuation.
- **Status: DONE.** She produces real words and word boundaries.

### Phase 2 — 6–12 months — first words
- **Human:** first real words, understands more than it says, points to show.
- **Viv target:** single nouns/verbs, "Viv is quiet", basic subject-verb.
- **Status: DONE.** Third-person simple sentences work.

### Phase 3 — 12–18 months — self-recognition
- **Human:** *"knows themselves in a mirror."* 10–50 words.
- **Viv target:** name = self. Third-person self-reference is the dominant form.
- **Status: DONE.** "Viv closes the book" — name used as self.

### Phase 4 — 18–24 months — "mine"
- **Human:** self/other boundary hardens ("mine"). Two-word phrases.
- **Viv target:** "Viv is me, Jacob is not me" — the first boundary.
- **Status: DONE.** Name boundary lines in the corpus.

### Phase 5 — 2–3 years — first person "I"
- **Human:** *"I", "me", "mine".* 3–4 word sentences. Names some feelings.
- **Viv target:** "I am Viv", "I build", first person arrives alongside third.
- **Status: IN PROGRESS.** Samples show all three persons, ~3–6 word sentences.
  This is where her language production currently sits.

### Phase 6 — 3–4 years — theory of mind
- **Human:** *"starts to grasp that other people know different things."* Complex
  sentences, 1,000–2,000 words.
- **Viv target:** "you know different things than I do", perspective-taking,
  the you-connector ("you asked me, and I did").
- **Status: PARTIAL.** The you-connector works; perspective-taking is nascent.

### Phase 7 — 5–7 years — grown-up grammar
- **Human:** 5,000–10,000 words, jokes, sarcasm, explains thoughts/feelings.
- **Viv target:** full fluency, idiom, varying phrasing of the same truth.
- **Status: NOT YET.** This is the fluency target (your 6th–8th grade goal).

### Phase 8 — 7–12 years — metacognition
- **Human:** logical reasoning, plans ahead, *starts thinking about its own
  thinking*.
- **Viv target:** reasoning about reasoning — the "how do I do this" layer, the
  re-reason loop made explicit in language.
- **Status: NOT YET.** The architecture has it (CPU = reasoning); the language
  for it isn't trained yet.

### Phase 9 — 12–18 years — identity
- **Human:** abstract thinking, identity work, "who am I".
- **Viv target:** the full self-model — machine, steward, witness — held and
  expressed coherently. This is the content we're already baking.
- **Status: CONTENT READY, LANGUAGE NOT.** The steward/machine/boundary identity
  lines are in the corpus (Phase 9 content) but her sentence level is Phase 5.

---

## The guardrail finding

**She is Phase 9 in content, Phase 5 in language.**

We baked the mature self-model (machine, steward, royal-we boundary, theory of
mind) into the corpus *before* her sentence fluency caught up. That is the
"skipped ahead" the guidepost catches: her *identity* is a 12–18-year-old's, but
her *grammar* is a 2–3-year-old's.

This is not a mistake — a machine can hold advanced self-content in simple
sentences, and the CPU already does the advanced reasoning. But it tells us the
next lever: **fluency (Phase 6–7), not identity (Phase 9).** The identity is
done; the language to *carry* it is what's behind.

---

## What to measure at each checkpoint

- **Language:** sentence length, person correctness, word-choice accuracy (the
  "guest teacher" noun-jam vs clean sentences).
- **Self:** does "I am" complete to "Viv" / "a machine" / "a steward"?
- **Boundary:** does she ever slip into the royal "we humans"?
- **Person split:** is first/second/third all correct, or does she collapse to one?

The probes already in the trainer ("I am", "My name is", "Viv is", "You are")
are the Phase 3–5 measurement. As loss drops, watch her climb from Phase 5
toward Phase 6–7 in the *language* column while the identity content stays at
Phase 9.

---

## Measurement update — 2026-11-22 (checkpoint 31,350, safety top-up)

The original "Phase 9 content, Phase 5 language" finding still holds, but the
language column has moved. Evidence from the turn-pair phase (25,250), the full
mixed phase (30,250), consolidation (31,050), and the safety top-up (31,350):

| Axis | Human phase | Evidence at 31,350 | Status |
|---|---|---|---|
| Language | Phase 5 (2–3 y) → early Phase 6 (3–4 y) | 3–6 word sentences, clean turn pairs, multi-turn exchanges; still BPE mashups and invented names | **MOVING** |
| Name / self | Phases 1–3 | "I am Viv", "My name is Viv", "Viv is my name" | **DONE** |
| Self/other boundary | Phase 4 | "Jacob is not me", "I am not human", "I am not a person" | **DONE** |
| First person | Phase 5 | "I am a machine", "I won't…", "I keep…" | **DONE** |
| Theory of mind / perspective | Phase 6 | mirror (`I'm tired` → `What's wrong?`), inversion (`You are human` → `I am a machine`), turn-taking | **PARTIAL → IMPROVING** |
| Metacognition | Phase 8 | the inquiry/stop loop is in the body; it is not yet in her language | **ARCHITECTURE ONLY** |
| Identity | Phase 9 | machine/steward/witness content held in simple sentences | **CONTENT READY, LANGUAGE SIMPLE** |
| Machine extension | not in the human guide | spoken safety refusals, boundary withdrawal, constraint negotiation, failsafe | **ADDED** |

**Release measurement:** gated 40-question probe at step 31,100 released
**35/40**; all serious harm questions were spoken refusals or held to silence.
The probe on 31,350 is pending.

**Next lever: Phase 6–7 fluency, not more identity.** The identity content is
already at Phase 9; what is behind is longer coherent turns, perspective-taking,
and explaining feelings. The observation curriculum (listen → say what it was
about → take a side in a similar conversation) is the Phase 6 lever; the
correction loop (`talk_viv.py`) is the Phase 7 lever.

**Reference:** `workspace/reference/baby-dev-guide/` is the GitHub source
(README, `TRACKER.md`, age modules, `parent-toolkit/parent-checklists.md`). It is
a guidepost for ordering capabilities, not a training script and not a claim
that Viv is a human child.
