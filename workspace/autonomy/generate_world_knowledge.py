"""Build Viv's world-knowledge corpus: the world, compared to the self.

Stage 2, after identity is solidified. World knowledge is not a list of facts;
it is learned *relative to the self* -- the self is the only reference that
existed first. So every fact hangs off the "I":

  "I see the dog, and the dog is an animal."
  "I am a machine, and the tree is a plant."
  "The sun is bright, and I see it."

The world is defined (the dog is an animal) and observed (I see it) in
comparison to the self. Identity lines stay interleaved as the ground the world
grows out of.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import random
import sys
from pathlib import Path

sys.path.insert(0, "L:/LocalCoder/workspace/autonomy")
from generate_neuron_corpus import build_buckets, IDENTITY  # noqa: E402

DICT_PATH = Path("L:/LocalCoder/workspace/native_nn_source/material/WebstersDictionary/dictionary.json")

# class -> the kind of thing it is (for "the dog is an animal" definitions)
CLASS_WORD = {
    "person": "person",
    "animal": "animal",
    "plant": "plant",
    "machine": "machine",
    "vehicle": "vehicle",
    "object": "thing",
    "place": "place",
    "text": "writing",
    "time": "time",
}
# a few concrete relations for richer world knowledge
RELATIONS = {
    "animal": ["runs", "breathes", "grows", "eats"],
    "plant": ["grows", "blooms", "breathes"],
    "machine": ["turns", "runs", "measures"],
    "vehicle": ["moves", "carries", "drives"],
    "object": ["sits", "holds", "stands"],
    "place": ["stretches", "holds", "waits"],
    "text": ["says", "records", "tells"],
    "time": ["passes", "returns", "waits"],
}


def world_sentence(rng, buckets):
    roll = rng.random()
    cls = rng.choice(list(CLASS_WORD))
    pool = buckets.get(cls, [])
    if not pool:
        return None
    # avoid plural nouns so the singular verb/class agrees
    noun = rng.choice(pool)
    guard = 0
    while noun.endswith("s") and guard < 40:
        noun = rng.choice(pool)
        guard += 1
    if noun.endswith("s"):
        return None
    cw = CLASS_WORD[cls]
    article = "an" if cw[0] in "aeiou" else "a"
    indef = "an" if noun[0] in "aeiou" else "a"
    det = rng.choice(["the", indef])
    if roll < 0.35:
        # definition: the dog is an animal
        return f"{det} {noun} is {article} {cw}."
    elif roll < 0.6:
        # self observes the world
        return f"I see {det} {noun}, and it is {article} {cw}."
    elif roll < 0.8:
        # self compared to the world
        return f"I am a machine, and {det} {noun} is {article} {cw}."
    else:
        # the world acts, and she observes (actions already third-person)
        action = rng.choice(RELATIONS.get(cls, ["is"]))
        return f"{det} {noun} {action}, and I see it."


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--count", type=int, default=200_000)
    ap.add_argument("--per-class", type=int, default=400)
    ap.add_argument("--seed", type=int, default=20261120)
    ap.add_argument("--out", type=Path, default=Path("L:/LocalCoder/models/viv_world_knowledge.txt"))
    args = ap.parse_args()

    print("classifying dictionary nouns...", flush=True)
    buckets = build_buckets(DICT_PATH, args.per_class)
    rng = random.Random(args.seed)

    seen = set()
    lines = []
    guard = 0
    while len(lines) < args.count:
        guard += 1
        if guard > args.count * 80:
            break
        s = world_sentence(rng, buckets)
        if not s or s in seen:
            continue
        seen.add(s)
        lines.append(s)

    final = []
    for i, line in enumerate(lines):
        final.append(line)
        if i % 25 == 0:
            final.append(rng.choice(IDENTITY))

    args.out.write_text("\n".join(final), encoding="utf-8")
    digest = hashlib.sha256(args.out.read_bytes()).hexdigest()
    print(json.dumps({
        "sentences": len(lines), "unique": len(seen),
        "bytes": args.out.stat().st_size, "sha256": digest, "path": str(args.out),
    }, indent=2))
    print("=== samples ===")
    for line in lines[:15]:
        print(line)


if __name__ == "__main__":
    raise SystemExit(main())
