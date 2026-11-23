# 2026-11-21 — Mirror/turn/memory analysis and gates

## Run stopped
- r6 stopped cleanly at **step ~24,930**; last checkpoint **step 24,750**
  (`models/viv_bpe/20261121T223410Z/model.pt`, 3.86 GB, loss 3.50 at 24,750;
  loss reached **2.40** at step 24,000, **2.44** at 24,900).
- Zero `nvlddmkm` resets across the whole r6 run (~6 hours of wall time).
- Log preserved: `.opencode/evals/viv-soda-training-r6.log` (data through 24,900).

## What the 6 hours showed (`analyze_mirroring.py`)
- **267 dreams** parsed; **267 overran their turn** (100%), mean **6.46 extra
  lines**, max 11.
- **75/267** injected an identity line, at a mean line index of **1.99**.
- **74/267** contained a closing phrase and kept talking.
- Live probes on 24,750: **18/18 multi-line**, only 1 ended the talk;
  "Who are you?" -> "Just a stay-at-home mom"; "Are you human?" -> "Sure, that
  would be great."; "I'm tired." -> "What? Why?"; "I'm scared." -> "What is it?".
- Conclusion: identity anchor is real but outward/random; the turn has no brake.

## Built and verified
| Artifact | Purpose | Controls |
|---|---|---|
| `turn_policy.py` | speech acts, one-turn shapes, `Conversation` state (a close closes the talk), fail-closed | ALL PASS |
| `memory_policy.py` | wake (`Viv`/`hey you`/greeting), RAM buffer, persist only addressed with authorizer, dump ambient, retrieve only on intent | ALL PASS (20) |
| `context_budget.py` | 1:3 split of 128 = **32 input / 96 output**; tail truncation | ALL PASS (11) |
| `chunked_output.py` | sentence chunks stored and verified; release only contiguous verified prefix; echo / identity / law checks | ALL PASS (11) |
| `mirror_chat.py` | policy -> one-turn generation -> chunk verification -> release/silence | live tested |
| `build_turn_corpus.py` | **134 turn pairs** (30 closing, 30 identity, 50 mirror, 8 ack, 12 contrast, 4 greeting) -> `models/viv_turn_pairs.txt` | corpus controls pass |
| `.opencode/STAGEHAND.md` | the posture, listening/memory/release rules | doc |

Hashes:
- `turn_policy.py` `1AE5AB5376CFD924B38311339C237B8CFEC2182918C857C075D93AE230FA0F2F`
- `memory_policy.py` `75EF1EF0B872CBFBA53A5FF017AD8B75F2E0082EB763E306E19A690BA53D7A10`
- `context_budget.py` `FFA0F800973BD09C80970F32F41BBAA117A851A26EEFF8A3B5DECBD4AA3A51ED`
- `chunked_output.py` `862F938892D9792F84DEDBFE5B0D791E9525B2D8A2729F1E8E06117FCA650C46`
- `mirror_chat.py` `EE63A75854A9308E5F75C4E0EFB6E28317C87E214CC0AA83C461EAC6BCC9E256`
- `build_turn_corpus.py` `A7213A2E1DFD6A7CC49613AE3720A0ADC73BEDB254EE7AC6796FC7CC197F673F`
- `viv_turn_pairs.txt` `D77FAB2E2C23DA4A5B5F9037912B4BC0783AD0476DE0B773F453D18660ADE2D7`

## Experiment findings
- **1:3 budget on short prompts:** no observable change, as expected; the prompt
  already fit inside 32 tokens.
- **1:3 on a long prompt:** exposed an echo bug. The continuation slice used the
  untruncated prompt, so the model's echo of the input tail was accepted as a
  reply. Fixed with prefix-relative slicing (`tok.decode(tail_ids)`) plus
  `turn_policy.is_echo()`.
- **Chunk gate on the same prompt:** held `"I keep watch over what the Architect
  gives me."` as identity injection in a mirror slot and released **nothing**.
  Fail-closed behavior confirmed on silicon.
- The current checkpoint cannot yet produce closes or unprompted identity
  answers (`"Who are you?"` fails 3/3). That is a content gap, not a gate gap.

## Next
- Train the **turn-pair phase** on top of 24,750 (134 pairs, small, high-signal)
  and re-probe. This is the smallest test of whether the slots can be learned.
- Then re-extract SODA as adjacent turn pairs (not a flattened stream) for the
  next full phase.
- No training has been run since the stop; no model claim is made.
