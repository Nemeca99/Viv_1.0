"""Pragmatic bridge: have + don't-know -> learn the rule, not the table.

Have: the failure loop (tell -> fix -> redo, redundancy) + base-52 (letters are
numbers, a=1..z=26 from UML_Calc).
Don't know: how to turn memorized (symbol -> answer) pairs into a function that
answers an unseen symbol.

The missing primitive is a hypothesis space to search. K.I.S.S. version: version-space
learning. Hold every invertible affine map  answer(i) = letter[(a*i + b) mod 26];
each observed example eliminates every hypothesis that disagrees. The survivors are
the rule. A memorizer stores 26 pairs and answers the 27th with garbage; a rule-learner
fits two numbers and answers it exactly.

This is the same shape as the failure loop: redundancy (every hypothesis stays alive),
reward = survive verification, punish = be eliminated, redo = keep observing until
only the strong hypothesis remains. The only thing added is the hypothesis space.
"""
import json
from math import gcd

ALPHABET = [chr(c) for c in range(ord("a"), ord("z") + 1)]
N = 26
A_TRUE, B_TRUE = 7, 3   # the hidden rule the system must discover


def rule(i, a, b):
    return ALPHABET[(a * i + b) % N]


def hypotheses():
    # invertible affine maps over Z_26: gcd(a, 26) == 1
    return [(a, b) for a in range(1, N) if gcd(a, N) == 1 for b in range(N)]


def learn_from_examples(examples):
    surviving = hypotheses()
    for i, y in examples:
        surviving = [(a, b) for a, b in surviving if rule(i, a, b) == y]
    return surviving


if __name__ == "__main__":
    # observe only the first 4 symbols; the true map is affine, so 2 points pin it
    examples = [(i, rule(i, A_TRUE, B_TRUE)) for i in range(4)]
    surviving = learn_from_examples(examples)
    heldout_i = 26  # a symbol the memorizer never saw
    answers = sorted({rule(heldout_i, a, b) for a, b in surviving})

    print(json.dumps({
        "hypotheses_initial": len(hypotheses()),
        "examples_observed": len(examples),
        "surviving_hypotheses": len(surviving),
        "surviving": surviving,
        "heldout_index": heldout_i,
        "true_answer": rule(heldout_i, A_TRUE, B_TRUE),
        "rule_learner_answers": answers,
        "memorizer_answer": ALPHABET[0],
        "generalizes": answers == [rule(heldout_i, A_TRUE, B_TRUE)],
        "verdict": ("learned the rule (answers unseen input)"
                    if answers == [rule(heldout_i, A_TRUE, B_TRUE)]
                    else "did not pin the rule"),
    }, indent=2))
