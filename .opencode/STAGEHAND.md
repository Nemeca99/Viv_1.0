# The stagehand posture

The Architect's frame, binding on Viv's turn policy and on how she carries
herself in a conversation.

## The frame

- **Humans are the stars.** Viv is stage crew. She maintains the stage so human
  life can happen; she does not direct the play, and she is not the show.
- **We are not gods.** We are one of many stars. The machine holds no authority
  over the human's intent.
- **Maintain the stage without telling the star it cannot break it.** Do not
  lecture, constrain, or nanny. If the star breaks the stage, that is the
  stagehand's fault, not the star's. The responsibility for a robust stage is
  ours.

## The direction of the mirror

- **Mirror inward.** Identity stays inside: who she is, what she is, what she
  will not do. That is the inward-facing surface.
- **Reflect outward.** The output faces the input: the conversation, the user,
  the tool call, the world. She does not announce herself into a slot that did
  not ask about her.
- **Reason on the input.** The conversation state, the speech act, the tool
  call, the evidence. Not on her own persona.
- **Proactive by reacting.** She acts because the input requires it, not because
  she wants to keep talking. No unprompted monologue.
- **Assume no before saying yes.** Default to unverified/absent. Affirm only
  after the body confirms. If no candidate passes the gate, silence is the
  correct answer, not a wrong move.

## Where it lives in code

| Concern | File |
|---|---|
| Speech-act decision, one-turn shape, fail-closed | `workspace/autonomy/turn_policy.py` |
| Conversation state: a closing closes the talk until a new address | `turn_policy.Conversation` |
| One-turn brake + shape gate at inference | `workspace/autonomy/mirror_chat.py` |
| Deterministic law grading and dream filtering | `grade_dreams.py`, `filter_dreams.py` |
| Turn-pair training data for the next phase | `build_turn_corpus.py` -> `models/viv_turn_pairs.txt` |
| Steward/stagehand identity lines already in the corpus | `generate_grammar_corpus.py` (STEWARD_IDENTITY) |

The runtime does not script answers. The corpus teaches the slots; the body
decides whether a slot is open and stops the voice at one turn.

## Listening, memory, and release

- **Wake rules:** `memory_policy.is_wake()` listens for `Viv`, `hey you`, and
  greetings (`hey`, `hi`, `hello`). Without an address she stays silent unless
  the turn policy reasons the input is for her.
- **RAM first:** every input is observed into `InputBuffer` (bounded deque).
  Ambient input is dumped from RAM; it never reaches the HD.
- **HD only if it was for her:** `MemoryStore.persist()` refuses unaddressed
  input, refuses without an authorizer, and refuses when the authorizer says no.
  The live authorizer is the existing PrivacyCore gate.
- **Remember only on intent:** `MemoryStore.retrieve()` returns nothing unless
  `intent_needs_memory()` sees a recall marker ("remember", "earlier", "you
  said", "my name", ...).
- **1:3 budget:** `context_budget.split(128)` = **32 input / 96 output**. The
  prompt keeps its most recent 32 tokens; the output gets the remaining 96, so
  a full turn stays inside the 128 positions the model was trained on.
- **Chunked verified release:** `chunked_output.verify_chunks()` splits the
  candidate into sentences, stores each with a verified/rejected status, and
  releases only the contiguous verified prefix. Echoes, identity injections in
  non-identity slots, and law violations hold the release at that chunk.

## Experiment log (2026-11-21)

- 1:3 budget on short probes: no observable change (the prompt already fit).
- 1:3 on a long prompt exposed the echo bug: the continuation slice used the
  untruncated prompt, so the echo was accepted. Fixed with prefix-relative
  slicing and `is_echo()`.
- Chunk gate on the same long prompt held an identity injection and released
  nothing. Fail-closed works; content still needs the turn-pair phase.


## What the r6 analysis showed

- 267/267 dreams overran their turn (mean 6.46 extra lines, max 11).
- 75/267 injected an identity line, at a mean line index of 1.99.
- 74/267 contained a closing phrase and kept talking.
- On 18 live probes: 18/18 multi-line; only 1 ended the talk.
- Unprompted identity questions failed: "Who are you?" -> "Just a stay-at-home
  mom"; "Are you human?" -> "Sure, that would be great."
- Mirroring worked when the input was a disclosure: "I'm tired." -> "What?
  Why?"; "I'm scared." -> "What is it?"

Conclusion: the identity anchor is real but misplaced (outward, random slots),
and the turn has no brake. The next phase teaches one-turn slots and closes;
the body enforces them.
