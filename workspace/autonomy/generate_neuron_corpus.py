"""Expand Viv's grammar corpus to use the neuron's real vocabulary.

The neuron architecture (Steel Brain) learned ~81k words from the Webster's
dictionary, but it learns word *routes*, not grammar. So this module takes the
clean, part-of-speech-tagged dictionary words, classifies each noun into a
semantic role (person / animal / machine / vehicle / object / place / text /
time) via WordNet, and feeds them through the correct grammar (verb frames +
conjugation) to generate correct sentences with a large real vocabulary --
instead of the ~100 hand-picked words.

Identity lines are interleaved so the voice learns who she is alongside the
words she uses to say it.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import random
import sys
from pathlib import Path

import nltk
from nltk.corpus import wordnet as wn

sys.path.insert(0, "L:/LocalCoder/workspace/autonomy")
from generate_grammar_corpus import (  # noqa: E402
    FIRST_IDENTITY, MACHINE_IDENTITY, STEWARD_IDENTITY, BOUNDARY, HUMAN_BOUNDARY,
)

IDENTITY = FIRST_IDENTITY + MACHINE_IDENTITY + STEWARD_IDENTITY + BOUNDARY + HUMAN_BOUNDARY

DICT_PATH = Path("L:/LocalCoder/workspace/native_nn_source/material/WebstersDictionary/dictionary.json")

# Coarse semantic classes -> WordNet coarse hypernym names.
# "keep" classes are the ones we accept into the bucket; "look" are the WordNet
# hypernym names that map to a keep class.
CLASS_MAP = {
    "person": ("person",),
    "animal": ("animal",),
    "plant": ("plant",),
    "machine": ("device", "machine", "instrument"),
    "vehicle": ("vehicle",),
    "object": ("artifact", "object", "container", "furniture", "clothing", "structure"),
    "place": ("location", "geographical_area", "land"),
    "text": ("communication", "written_communication"),
    "time": ("time", "time_period"),
}

# verb frames: base verb -> (agent classes, patient classes)
VERBS = {
    "drive": (["person", "machine"], ["vehicle", "place"]),
    "read": (["person"], ["text"]),
    "build": (["person", "machine"], ["object", "place"]),
    "carry": (["person", "animal", "machine", "vehicle"], ["object"]),
    "open": (["person", "machine"], ["object"]),
    "close": (["person", "machine"], ["object"]),
    "follow": (["person", "animal", "vehicle", "machine"], ["vehicle", "place", "person"]),
    "reach": (["person", "animal", "vehicle", "machine"], ["place", "object"]),
    "hold": (["person", "animal", "machine"], ["object"]),
    "turn": (["person", "machine", "vehicle"], ["object", "vehicle"]),
    "move": (["person", "animal", "machine", "vehicle"], ["object"]),
    "measure": (["person", "machine"], ["object", "place", "time"]),
    "record": (["person", "machine"], ["text", "object"]),
    "signal": (["person", "machine"], ["person", "machine"]),
    "find": (["person", "animal", "machine"], ["object", "place", "text"]),
    "keep": (["person", "animal", "machine"], ["object"]),
    "change": (["person", "machine"], ["object", "place"]),
    "show": (["person", "machine", "text"], ["object", "place", "text"]),
    "wait": (["person", "animal"], []),
    "return": (["person", "animal", "vehicle", "machine"], []),
}
ADJECTIVES = ["red", "quiet", "small", "bright", "gentle", "simple", "clear",
              "steady", "warm", "soft", "sharp", "plain", "brief", "calm", "new"]
ADVERBS = ["quickly", "quietly", "slowly", "carefully", "clearly", "gently",
           "often", "rarely", "soon", "never"]
PREPOSITIONS = ["under", "over", "near", "behind", "before", "beside", "across",
                "inside", "beyond", "around"]
DETERMINERS = ["the", "a", "this", "that", "every", "each", "some"]


def coarse_class(word):
    syns = wn.synsets(word, pos=wn.NOUN)
    if not syns:
        return None
    # A word that is itself a class name (person, animal, plant, machine...)
    # should classify as that class before walking up its hypernyms. Otherwise
    # "person" walks to "organism" -> "object" and comes back as "a thing".
    own = syns[0].name().split(".")[0]
    for keep, names in CLASS_MAP.items():
        if own in names:
            return keep
    frontier = list(syns[0].hypernyms())
    seen = set()
    depth = 0
    while frontier and depth < 14:
        node = frontier.pop(0)
        name = node.name().split(".")[0]
        for keep, names in CLASS_MAP.items():
            if name in names:
                return keep
        if node.name() not in seen:
            seen.add(node.name())
            frontier.extend(node.hypernyms())
        depth += 1
    return None


def conjugate(verb, third_person):
    if not third_person:
        return verb
    if verb.endswith(("s", "x", "z", "ch", "sh")):
        return verb + "es"
    if verb.endswith("y") and len(verb) > 1 and verb[-2] not in "aeiou":
        return verb[:-1] + "ies"
    return verb + "s"


def build_buckets(dict_path, per_class):
    entries = json.loads(Path(dict_path).read_text(encoding="utf-8"))
    buckets = {k: [] for k in CLASS_MAP}
    seen = set()
    for e in entries:
        if e.get("pos") != "n.":
            continue
        word = str(e.get("word", "")).lower()
        if not (3 <= len(word) <= 9 and word.isalpha()):
            continue
        if word in seen:
            continue
        seen.add(word)
        cls = coarse_class(word)
        if cls and len(buckets[cls]) < per_class:
            buckets[cls].append(word)
    return buckets


def pick(rng, buckets, classes):
    pool = [w for c in classes for w in buckets.get(c, [])]
    return rng.choice(pool) if pool else None


def make_sentence(rng, buckets):
    roll = rng.random()
    if roll < 0.3:
        vname = rng.choice(list(VERBS))
        agents, patients = VERBS[vname]
        if not patients:
            vname = rng.choice([v for v, (a, p) in VERBS.items() if p])
            agents, patients = VERBS[vname]
        agent = pick(rng, buckets, agents)
        patient = pick(rng, buckets, patients)
        if agent is None or patient is None:
            return None
        return f"{rng.choice(DETERMINERS)} {rng.choice(ADJECTIVES)} {agent} {conjugate(vname, True)} {rng.choice(DETERMINERS)} {rng.choice(ADJECTIVES)} {patient}."
    elif roll < 0.55:
        vname = rng.choice(list(VERBS))
        agents, _ = VERBS[vname]
        agent = pick(rng, buckets, agents)
        if agent is None:
            return None
        return f"{rng.choice(DETERMINERS)} {rng.choice(ADJECTIVES)} {agent} {conjugate(vname, True)} {rng.choice(ADVERBS)}."
    elif roll < 0.75:
        vname = rng.choice(list(VERBS))
        agents, _ = VERBS[vname]
        agent = pick(rng, buckets, agents)
        loc = pick(rng, buckets, ["place"])
        if agent is None or loc is None:
            return None
        return f"{rng.choice(DETERMINERS)} {rng.choice(ADJECTIVES)} {agent} {conjugate(vname, True)} {rng.choice(PREPOSITIONS)} {rng.choice(DETERMINERS)} {rng.choice(ADJECTIVES)} {loc}."
    else:
        vname = rng.choice(list(VERBS))
        agents, patients = VERBS[vname]
        if not patients:
            vname = rng.choice([v for v, (a, p) in VERBS.items() if p])
            agents, patients = VERBS[vname]
        agent = pick(rng, buckets, agents)
        patient = pick(rng, buckets, patients)
        if agent is None or patient is None:
            return None
        return f"Viv {conjugate(vname, True)} {rng.choice(DETERMINERS)} {rng.choice(ADJECTIVES)} {patient}."


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--count", type=int, default=200_000)
    ap.add_argument("--per-class", type=int, default=400)
    ap.add_argument("--seed", type=int, default=20261120)
    ap.add_argument("--out", type=Path, default=Path("L:/LocalCoder/models/viv_neuron_corpus.txt"))
    args = ap.parse_args()

    print("classifying dictionary nouns (bounded)...", flush=True)
    buckets = build_buckets(DICT_PATH, args.per_class)
    for cls, words in buckets.items():
        print(f"  {cls}: {len(words)} words, sample: {words[:8]}", flush=True)

    rng = random.Random(args.seed)
    seen = set()
    lines = []
    guard = 0
    while len(lines) < args.count:
        guard += 1
        if guard > args.count * 80:
            break
        s = make_sentence(rng, buckets)
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
        "vocab_total": sum(len(w) for w in buckets.values()),
        "bytes": args.out.stat().st_size, "sha256": digest, "path": str(args.out),
    }, indent=2))
    print("=== samples ===")
    for line in lines[:15]:
        print(line)


if __name__ == "__main__":
    raise SystemExit(main())
