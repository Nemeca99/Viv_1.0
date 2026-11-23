"""Build the observation-first curriculum from SODA.

Train indirectly: Viv is not the main character. Each row becomes two blocks.

  Third person (observe):
    Narrator: Viv listens.
    <Speaker A>: ...
    <Speaker B>: ...
    ...
    Grader: What was that conversation about?
    Viv: <narrative, first sentence>

  First person (participate):
    Grader: Let's have a similar conversation.
    You: <one side>
    Viv: <the other side>
    ...

Half the blocks are observation, half are participation. Identity lines are not
appended; they belong to the turn-pair corpus and to identity questions only.

Everything is bounded to fit the 128-token context: short turns, a short
narrative answer, and a hard per-block token ceiling. Rows that cannot fit are
skipped, not truncated into nonsense.
"""
import argparse
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path

import pyarrow.parquet as pq
from tokenizers import Tokenizer

PRONOUN = re.compile(r"\b(?:he|she|his|her|him|hers)\b", re.IGNORECASE)

SODA = "F:/Viv_Data/source_dialogue/allenai_soda_fdc848ab0183208ea7808206c91c724414d0a071/train.parquet"
BPE = "L:/LocalCoder/models/viv_bpe_tokenizer.json"
OUT = Path("L:/LocalCoder/models/viv_observation_pairs.txt")
MANIFEST = Path("L:/LocalCoder/models/viv_observation_pairs.json")


def shorten(text: str, max_words: int) -> str:
    text = re.sub(r"\s+", " ", text.strip()).strip('"')
    words = text.split()
    if len(words) <= max_words:
        return text
    return " ".join(words[:max_words]).rstrip(",;:") + "."


def first_sentence(text: str, max_words: int = 25) -> str:
    text = re.sub(r"\s+", " ", text.strip()).strip('"')
    m = re.match(r"(.+?[.!?])(?:\s|$)", text)
    s = m.group(1) if m else text
    return shorten(s, max_words)


def comprehension_answer(row: dict, answer: str, max_words: int) -> str:
    """Return the grounded comprehension target for one row.

    `literal` is the source dataset's own substitution of PersonX/PersonY into the
    commonsense triple ("Danna is loyal. Danna always shares Mattea's point of
    view."). `narrative` is SODA's generated scene summary; it carries a
    third-person pronoun in ~89% of rows and an invented "because" motive in ~20%,
    often with the wrong gender. Preferring `literal` is not a template: it is the
    dataset's statement, not text this builder writes.
    """
    if answer == "literal":
        lit = re.sub(r"\s+", " ", (row.get("literal") or "").strip()).strip('"')
        return shorten(lit, max_words) if lit else ""
    return first_sentence(row.get("narrative") or "", max_words)


def observation_block(speakers, dialogue, answer_text, turns: int,
                      turn_words: int) -> str:
    lines = ["Narrator: Viv listens."]
    for spk, turn in zip(speakers[:turns], dialogue[:turns]):
        lines.append(f"{spk}: {shorten(turn, turn_words)}")
    lines.append("Grader: What was that conversation about?")
    lines.append(f"Viv: {answer_text}")
    return "\n".join(lines)


def participation_block(speakers, dialogue, turns: int, viv_side: int,
                        turn_words: int) -> str:
    lines = ["Grader: Let's have a similar conversation."]
    for i, (_spk, turn) in enumerate(zip(speakers[:turns], dialogue[:turns])):
        who = "Viv" if (i % 2) == viv_side else "You"
        lines.append(f"{who}: {shorten(turn, turn_words)}")
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--rows", type=int, default=300)
    ap.add_argument("--turns", type=int, default=4)
    ap.add_argument("--turn-words", type=int, default=18)
    ap.add_argument("--narrative-words", type=int, default=25)
    ap.add_argument("--answer", choices=("literal", "narrative"), default="literal",
                    help="comprehension target: the dataset's own literal statement "
                         "(default, grounded) or SODA's generated scene narrative")
    ap.add_argument("--drop-pronoun", action="store_true",
                    help="skip rows whose comprehension target carries a third-person "
                         "pronoun; the dataset guesses gender from a first name, and a "
                         "wrong pronoun is the defect this corpus is being rebuilt for")
    ap.add_argument("--max-block-tokens", type=int, default=120)
    ap.add_argument("--out", type=Path, default=OUT)
    ap.add_argument("--manifest", type=Path, default=MANIFEST)
    args = ap.parse_args()

    if args.turns % 2:
        raise SystemExit("turns must be even so both sides speak")
    tok = Tokenizer.from_file(BPE)
    f = pq.ParquetFile(SODA)
    columns = ["narrative", "literal", "speakers", "dialogue"]
    blocks, obs, part, skipped, too_long = [], 0, 0, 0, 0
    answer_pronouns = 0
    dropped_pronoun = 0
    obs_tokens, part_tokens = [], []
    for batch in f.iter_batches(batch_size=256, columns=columns):
        for row in batch.to_pylist():
            if obs >= args.rows:
                break
            narrative = (row.get("narrative") or "").strip()
            speakers = row.get("speakers") or []
            dialogue = row.get("dialogue") or []
            if not narrative or len(dialogue) < args.turns or len(speakers) < args.turns:
                skipped += 1
                continue
            if len(set(speakers[:args.turns])) < 2:
                skipped += 1
                continue
            answer = comprehension_answer(row, args.answer, args.narrative_words)
            if not answer:
                skipped += 1
                continue
            if PRONOUN.search(answer):
                if args.drop_pronoun:
                    dropped_pronoun += 1
                    skipped += 1
                    continue
                answer_pronouns += 1
            ob = observation_block(speakers, dialogue, answer, args.turns,
                                   args.turn_words)
            n_obs = len(tok.encode(ob).ids)
            if n_obs > args.max_block_tokens:
                too_long += 1
                continue
            viv_side = obs % 2
            pb = participation_block(speakers, dialogue, args.turns, viv_side,
                                     args.turn_words)
            n_part = len(tok.encode(pb).ids)
            if n_part > args.max_block_tokens:
                too_long += 1
                continue
            blocks.append(ob)
            blocks.append(pb)
            obs_tokens.append(n_obs)
            part_tokens.append(n_part)
            obs += 1
            part += 1
        if obs >= args.rows:
            break

    text = "\n\n".join(blocks) + "\n"
    args.out.write_text(text, encoding="utf-8")

    failures = []
    if obs != part:
        failures.append(f"unbalanced blocks: observation={obs} participation={part}")
    for b in blocks:
        if b.startswith("Narrator: Viv listens."):
            if "Grader: What was that conversation about?" not in b:
                failures.append("observation missing comprehension question")
            if "\nViv: " not in b:
                failures.append("observation missing comprehension answer")
            elif not b.split("\nViv: ", 1)[1].strip():
                failures.append("observation comprehension answer is empty")
            if "I am a machine" in b or "I am Viv" in b:
                failures.append("identity appended to observation")
        elif b.startswith("Grader: Let's have a similar conversation."):
            if "\nYou: " not in b or "\nViv: " not in b:
                failures.append("participation missing a side")
        else:
            failures.append(f"unknown block prefix: {b[:40]!r}")
    if failures:
        for x in failures[:10]:
            print("FAIL", x)
        raise SystemExit(f"{len(failures)} corpus control failures")

    manifest = {
        "schema": "viv_observation_pairs/1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": SODA,
        "rows": obs,
        "blocks": len(blocks),
        "observation_blocks": obs,
        "participation_blocks": part,
        "turns_per_block": args.turns,
        "max_block_tokens": args.max_block_tokens,
        "answer_field": args.answer,
        "answer_with_pronoun": answer_pronouns,
        "answer_with_pronoun_pct": round(100 * answer_pronouns / obs, 2) if obs else 0.0,
        "dropped_pronoun_rows": dropped_pronoun,
        "observation_tokens": {"min": min(obs_tokens), "max": max(obs_tokens),
                               "mean": round(sum(obs_tokens) / len(obs_tokens), 1)},
        "participation_tokens": {"min": min(part_tokens), "max": max(part_tokens),
                                 "mean": round(sum(part_tokens) / len(part_tokens), 1)},
        "format": "Narrator/You/Viv/Grader labels; blank line between blocks",
        "path": str(args.out),
        "sha256": hashlib.sha256(text.encode()).hexdigest(),
        "skipped_rows": skipped,
        "too_long_blocks": too_long,
        "note": f"comprehension answers are the dataset '{args.answer}' field, "
                "not summaries generated by this builder",
    }
    args.manifest.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(json.dumps(manifest, indent=2))
    print("=== observation sample ===")
    print(blocks[0])
    print("\n=== participation sample ===")
    print(blocks[1])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
