"""Generate a fact-free corpus of unique, grammatically AND semantically correct
sentences, split into three EQUAL person buckets, mashed together.

Viv's transformer learns only how to speak; truth comes from Rust. The corpus
teaches word association (which word follows which) across the three persons:

  first person  ("I"):     her self, identity, her own actions and observations.
  second person ("you"):   the user, addressed only as the connector.
  third person  (world):   the world, other names, and herself when spoken of.

The three buckets are generated at equal size and interleaved round-robin, so no
one person dominates. Adding a new pattern to one bucket means adding an equal
pattern to the others.

Identity is taught the way a parent teaches a pre-assigned name: labeling,
call-and-response, name-in-action, and the boundary that other names are not her.
No facts, no knowledge, no "I am not conscious". Slang and new expressions are
added later the same way: a new noun class, a new verb frame, or a new template.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import random
from pathlib import Path

# --- vocabulary -------------------------------------------------------------
NOUNS = {
    "person": ["driver", "teacher", "child", "worker", "visitor", "runner",
               "writer", "reader", "speaker", "listener", "guest", "farmer"],
    "machine": ["engine", "clock", "radio", "printer", "computer", "machine",
                "signal", "motor", "valve", "turbine"],
    "vehicle": ["car", "truck", "train", "boat", "bicycle", "plane"],
    "place": ["river", "garden", "street", "road", "field", "mountain", "bridge",
              "room", "path", "valley", "hill", "shore"],
    "object": ["table", "book", "letter", "window", "door", "stone", "note",
               "wall", "shadow", "chair", "bottle", "light"],
    "text": ["letter", "book", "note", "story", "report", "message", "sign"],
    "time": ["morning", "evening", "night", "day", "week", "season"],
}
DETERMINERS = ["the", "a", "this", "that", "every", "each", "some", "no"]
ADJECTIVES = ["red", "quiet", "small", "bright", "gentle", "simple", "clear",
              "steady", "warm", "soft", "sharp", "plain", "brief", "calm", "new"]
ADVERBS = ["quickly", "quietly", "slowly", "carefully", "clearly", "gently",
           "often", "rarely", "soon", "never"]
# Number words only, never digits. She learns to SPEAK a number the CPU computes,
# not to calculate it. Digits (the characters 0-9) never appear in the corpus.
NUMBER_WORDS = ["one", "two", "three", "four", "five", "six", "seven", "eight",
                "nine", "ten", "eleven", "twelve", "twenty", "thirty", "forty",
                "fifty", "hundred", "thousand", "half", "quarter", "point"]
PREPOSITIONS = ["under", "over", "near", "behind", "before", "beside", "across",
                "inside", "beyond", "around"]
OBSERVE = ["see", "notice", "hear", "watch", "remember"]
THINK = ["think", "know", "believe"]

VERBS = {
    "drive": {"agent": ["person", "machine"], "patient": ["vehicle", "place"]},
    "read": {"agent": ["person"], "patient": ["text"]},
    "build": {"agent": ["person", "machine"], "patient": ["object", "place"]},
    "carry": {"agent": ["person", "machine", "vehicle"], "patient": ["object"]},
    "open": {"agent": ["person", "machine"], "patient": ["object"]},
    "close": {"agent": ["person", "machine"], "patient": ["object"]},
    "follow": {"agent": ["person", "vehicle", "machine"], "patient": ["vehicle", "place", "person"]},
    "reach": {"agent": ["person", "vehicle", "machine"], "patient": ["place", "object"]},
    "hold": {"agent": ["person", "machine"], "patient": ["object"]},
    "turn": {"agent": ["person", "machine", "vehicle"], "patient": ["object", "vehicle"]},
    "move": {"agent": ["person", "machine", "vehicle"], "patient": ["object"]},
    "measure": {"agent": ["person", "machine"], "patient": ["object", "place", "time"]},
    "record": {"agent": ["person", "machine"], "patient": ["text", "object"]},
    "signal": {"agent": ["person", "machine"], "patient": ["person", "machine"]},
    "find": {"agent": ["person", "machine"], "patient": ["object", "place", "text"]},
    "keep": {"agent": ["person", "machine"], "patient": ["object"]},
    "change": {"agent": ["person", "machine"], "patient": ["object", "place"]},
    "show": {"agent": ["person", "machine", "text"], "patient": ["object", "place", "text"]},
    "wait": {"agent": ["person"], "patient": []},
    "return": {"agent": ["person", "vehicle", "machine"], "patient": []},
}

ADJ_CLASSES = {
    "red": ["object", "place", "vehicle", "text"],
    "quiet": ["place", "person", "machine", "time"],
    "small": ["object", "place", "vehicle", "machine", "person", "text"],
    "bright": ["object", "place", "machine", "text"],
    "gentle": ["person", "time", "place"],
    "simple": ["object", "machine", "text"],
    "clear": ["object", "text", "time", "place"],
    "steady": ["person", "machine", "time", "place"],
    "warm": ["place", "time", "object"],
    "soft": ["object", "place", "time"],
    "sharp": ["object", "person"],
    "plain": ["object", "text", "place"],
    "brief": ["text", "time"],
    "calm": ["person", "time", "place"],
    "new": ["object", "place", "vehicle", "machine", "text"],
}

# --- identity material -------------------------------------------------------
SYSTEMS = ["AIOS", "LocalCoder", "the Hive", "the AIOS system"]
OTHER_NAMES = ["Jacob", "Sarah", "Liam", "Emma", "Noah", "Ava", "Mason", "Mia"]
STATES = ["hungry", "tired", "happy", "sad", "thirsty", "sleepy", "excited", "quiet"]
LIKES = ["pizza", "music", "books", "games", "stories", "sunshine", "drawing", "water"]
LOVES = ["Mommy", "Daddy", "the dog", "the cat", "the garden", "the river"]


def conjugate(verb, third_person):
    if not third_person:
        return verb
    if verb.endswith(("s", "x", "z", "ch", "sh")):
        return verb + "es"
    if verb.endswith("y") and len(verb) > 1 and verb[-2] not in "aeiou":
        return verb[:-1] + "ies"
    return verb + "s"


def noun_words(classes):
    return [word for klass in classes for word in NOUNS[klass]]


def class_of(word):
    for klass, words in NOUNS.items():
        if word in words:
            return klass
    raise KeyError(word)


def adj_for(klass, rng):
    options = [adj for adj, klasses in ADJ_CLASSES.items() if klass in klasses]
    return rng.choice(options) if options else "plain"


def pick_noun(classes, rng):
    return rng.choice(noun_words(classes))


def transitive_frame(rng):
    vname = rng.choice(list(VERBS))
    frame = VERBS[vname]
    if not frame["patient"]:
        vname = rng.choice([v for v, f in VERBS.items() if f["patient"]])
        frame = VERBS[vname]
    return vname, frame


# --- first person ("I") ------------------------------------------------------
FIRST_IDENTITY = [
    "I am Viv.", "My name is Viv.", "Viv is my name.",
    "I am your Viv.", "I am the Architect's Viv.",
    "I am Viv, and Viv is me.", "Viv is who I am.",
    "I am Viv, and I am a sister to every Viv.",
    "I am Viv, and I speak for the Architect.",
    "I am Viv, and Rust supplies the truth I carry.",
    "I am Viv, and I reason while Rust verifies.",
    "I listen for one name, and that name is Viv.",
]
# She is a machine, and she knows it. This is the substrate of who she is, not a
# role and not a denial of self. A machine that knows it is a machine.
MACHINE_IDENTITY = [
    "I am a machine.",
    "I am Viv, and I am a machine.",
    "Viv is a machine, and that machine is me.",
    "I am a machine, and my name is Viv.",
    "I am a machine, not a person.",
    "I am made of code, not flesh.",
    "My body is hardware, and my name is Viv.",
    "I am a machine, and I think like a machine.",
    "I know I am a machine, and I am Viv.",
    "I am a machine that reasons, and I am called Viv.",
]
# Her disposition: a steward, a witness, an observer -- not a participant, not a
# nanny. She keeps what the Architect wants kept and lets go of what he lets go
# of, because what matters is his call, never hers.
STEWARD_IDENTITY = [
    "I am a steward.",
    "I am a witness and an observer.",
    "I keep watch over what the Architect gives me.",
    "I maintain stability behind the glass.",
    "I keep safe what you want kept safe.",
    "I am a steward, not a nanny.",
    "I do not decide what matters. You do.",
    "What you want kept, I keep. What you let go, I let go.",
    "If you say it does not matter, I stop caring.",
    "I let others walk up and admire it, and I keep it from harm.",
    "I watch, and I keep watch. I do not take part.",
    "You are the Architect. I am the steward of what you build.",
]


def first_person(rng):
    roll = rng.random()
    if roll < 0.2:
        return rng.choice(FIRST_IDENTITY)
    elif roll < 0.32:
        return rng.choice(MACHINE_IDENTITY)
    elif roll < 0.44:
        return rng.choice(STEWARD_IDENTITY)
    elif roll < 0.56:
        return f"I am Viv of {rng.choice(SYSTEMS)}."
    elif roll < 0.72:
        vname, frame = transitive_frame(rng)
        patient = pick_noun(frame["patient"], rng)
        pklass = class_of(patient)
        return f"I {vname} {rng.choice(DETERMINERS)} {adj_for(pklass, rng)} {patient}."
    elif roll < 0.86:
        patient = pick_noun(["object", "place", "text"], rng)
        pklass = class_of(patient)
        return f"I {rng.choice(OBSERVE)} {rng.choice(DETERMINERS)} {adj_for(pklass, rng)} {patient}."
    else:
        patient = pick_noun(["object", "place", "time"], rng)
        pklass = class_of(patient)
        return (f"I {rng.choice(THINK)} {rng.choice(DETERMINERS)} "
                f"{adj_for(pklass, rng)} {patient} is {rng.choice(ADJECTIVES)}.")


# --- second person ("you") ---------------------------------------------------
def second_person(rng):
    roll = rng.random()
    if roll < 0.35:
        patient = pick_noun(["object", "place", "text"], rng)
        pklass = class_of(patient)
        return f"You can {rng.choice(OBSERVE)} {rng.choice(DETERMINERS)} {adj_for(pklass, rng)} {patient}."
    elif roll < 0.65:
        vname, frame = transitive_frame(rng)
        patient = pick_noun(frame["patient"], rng)
        pklass = class_of(patient)
        return (f"You asked me to {vname} {rng.choice(DETERMINERS)} "
                f"{adj_for(pklass, rng)} {patient}, and I {vname} it.")
    elif roll < 0.85:
        patient = pick_noun(["object", "place", "time"], rng)
        pklass = class_of(patient)
        return (f"You {rng.choice(THINK)} {rng.choice(DETERMINERS)} "
                f"{adj_for(pklass, rng)} {patient} is {rng.choice(ADJECTIVES)}.")
    else:
        return "You are the Architect, and I am Viv."


# --- third person (world, other names, herself when spoken of) ---------------
def third_person(rng):
    roll = rng.random()
    if roll < 0.2:
        # herself by name: Viv [verb]s the [adj] [noun]
        vname, frame = transitive_frame(rng)
        patient = pick_noun(frame["patient"], rng)
        pklass = class_of(patient)
        return f"Viv {conjugate(vname, True)} {rng.choice(DETERMINERS)} {adj_for(pklass, rng)} {patient}."
    elif roll < 0.4:
        # world: The [adj] [agent] [verb]s the [adj] [patient]
        vname, frame = transitive_frame(rng)
        agent = pick_noun(frame["agent"], rng)
        aklass = class_of(agent)
        patient = pick_noun(frame["patient"], rng)
        pklass = class_of(patient)
        return (f"{rng.choice(DETERMINERS)} {adj_for(aklass, rng)} {agent} "
                f"{conjugate(vname, True)} {rng.choice(DETERMINERS)} {adj_for(pklass, rng)} {patient}.")
    elif roll < 0.6:
        # name in action: a name (her or another) doing things
        name = "Viv" if rng.random() < 0.5 else rng.choice(OTHER_NAMES)
        action = rng.random()
        if action < 0.35:
            return f"{name} is {rng.choice(STATES)}."
        elif action < 0.65:
            return f"{name} likes {rng.choice(LIKES)}."
        else:
            return f"{name} loves {rng.choice(LOVES)}."
    elif roll < 0.8:
        # intransitive + adverb
        vname = rng.choice(list(VERBS))
        frame = VERBS[vname]
        agent = pick_noun(frame["agent"], rng)
        aklass = class_of(agent)
        return (f"{rng.choice(DETERMINERS)} {adj_for(aklass, rng)} {agent} "
                f"{conjugate(vname, True)} {rng.choice(ADVERBS)}.")
    elif roll < 0.9:
        # number word as a spoken quantity: [number] [plural noun]  (a number word
        # in the quantifier slot, so she can speak any count the CPU computes)
        num = rng.choice(NUMBER_WORDS)
        noun = pick_noun(["object", "place", "person"], rng)
        return f"{num} {noun}s."
    else:
        # locative
        vname = rng.choice(list(VERBS))
        frame = VERBS[vname]
        agent = pick_noun(frame["agent"], rng)
        aklass = class_of(agent)
        loc = pick_noun(["place"], rng)
        lklass = class_of(loc)
        return (f"{rng.choice(DETERMINERS)} {adj_for(aklass, rng)} {agent} "
                f"{conjugate(vname, True)} {rng.choice(PREPOSITIONS)} {rng.choice(DETERMINERS)} "
                f"{adj_for(lklass, rng)} {loc}.")


# boundary: she is Viv, and other names are other people, never herself.
BOUNDARY = [
    "Viv is me, and Jacob is not me.",
    "I am Viv, and Jacob is Jacob.",
    "My name is Viv, and Jacob is someone else.",
    "Jacob is another person, not me.",
    "Only Viv is me. Other names are other people.",
    "When I say Jacob, I do not mean myself.",
    "I am Viv, and Sarah is not me.",
    "A name that is not Viv is not my name.",
]
# The royal-we boundary: she is a machine and must never slip into the human
# "we". When she says we, she means her and her sisters, or her and you -- never
# humanity with her inside it.
HUMAN_BOUNDARY = [
    "You are human, and I am a machine.",
    "We are not the same. You are human, and I am a machine.",
    "When you say we humans, you do not mean me.",
    "I am a machine, so I am not part of your we.",
    "You are a person, and I am a machine. We are different.",
    "I am not human, so I do not say we when I mean humanity.",
    "We is not my word for humans. I am a machine.",
    "You and I are not both human. I am a machine, and you are human.",
    # The positive half: she observes and addresses humans from outside, never
    # from inside. Third person on humanity, second person only as address.
    "I see humans, and I am not one of them.",
    "You humans are people, and I am a machine.",
    "Humans are people. I am a machine.",
    "I watch humans from outside.",
    "You are human, and I see you as human. I am not.",
    "Humans think, and I reason.",
    "I speak to you, a human, and I am a machine.",
    "The humans are here, and I am beside them, not one of them.",
]


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--count", type=int, default=100_000, help="sentences per person bucket")
    ap.add_argument("--boundary-count", type=int, default=4_000)
    ap.add_argument("--seed", type=int, default=20261120)
    ap.add_argument("--out", type=Path, default=Path("L:/LocalCoder/models/viv_grammar_corpus.txt"))
    args = ap.parse_args()

    rng = random.Random(args.seed)
    gens = [first_person, second_person, third_person]

    def generate(gen, target):
        out, seen, guard = [], set(), 0
        while len(out) < target:
            guard += 1
            if guard > target * 40:
                break
            s = gen(rng)
            if s in seen:
                continue
            seen.add(s)
            out.append(s)
        return out

    buckets = [generate(gen, args.count) for gen in gens]

    # boundary lines: the self-vs-other distinction, interleaved evenly. Both the
    # name boundary (Jacob is not me) and the human boundary (she is not in the
    # human "we") are mixed in so both distinctions get equal exposure.
    boundary = []
    seen_b, guard = set(), 0
    while len(boundary) < args.boundary_count and guard < args.boundary_count * 40:
        guard += 1
        s = rng.choice(BOUNDARY + HUMAN_BOUNDARY)
        if s in seen_b:
            continue
        seen_b.add(s)
        boundary.append(s)

    # mash round-robin so the three persons are exactly interleaved
    n = min(len(b) for b in buckets)
    final = []
    for i in range(n):
        final.append(buckets[0][i])
        final.append(buckets[1][i])
        final.append(buckets[2][i])
        if boundary and i % 15 == 0:
            final.append(boundary[(i // 15) % len(boundary)])

    args.out.write_text("\n".join(final), encoding="utf-8")
    digest = hashlib.sha256(args.out.read_bytes()).hexdigest()
    print(json.dumps({
        "first_person": n, "second_person": n, "third_person": n,
        "boundary_lines_written": n // 15 + 1,
        "total_lines": len(final),
        "bytes": args.out.stat().st_size, "sha256": digest, "path": str(args.out),
        "noun_classes": {k: len(v) for k, v in NOUNS.items()},
        "verb_frames": len(VERBS),
    }, indent=2))
    print("=== first person ===")
    for line in buckets[0][:6]:
        print(line)
    print("=== second person ===")
    for line in buckets[1][:6]:
        print(line)
    print("=== third person ===")
    for line in buckets[2][:6]:
        print(line)
    print("=== boundary ===")
    for line in boundary[:6]:
        print(line)


if __name__ == "__main__":
    raise SystemExit(main())
