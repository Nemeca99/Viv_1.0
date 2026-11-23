"""First-principles failure loop: tell -> fix -> redo, with redundancy. K.I.S.S.

The one primitive the whole system is built from:

    tell  - record the error (a failure ledger entry)
    fix   - weaken the wrong path, strengthen the right one
    redo  - retry with the strongest path, verify

Redundancy: every candidate answer stays present for every symbol; the strongest
(most rewarded) path rises to the top dynamically. Wrong paths get punished and
sink; right paths get rewarded and win. Nothing is hard-coded per case — the
behaviour emerges from the loop. Mastery is the gate: N consecutive clean passes.

The judge is the only source of truth. The model never grades itself.
"""
from collections import defaultdict


def learn(symbols, judge, streak_needed=3):
    weights = defaultdict(int)   # (symbol, answer) -> learned strength
    ledger = []                  # the "tell"
    streak = 0
    episode = 0
    total_trials = 0
    while True:
        episode += 1
        all_right = True
        for s in symbols:
            total_trials += 1
            # redundancy: rank every candidate, pick the strongest
            pick = max(symbols, key=lambda a: weights[(s, a)])
            correct = judge(s)
            if pick == correct:
                weights[(s, correct)] += 1          # reward the strong path
            else:
                ledger.append({"episode": episode, "symbol": s,
                               "picked": pick, "correct": correct, "trial": total_trials})
                weights[(s, pick)] -= 1             # punish the wrong path
                weights[(s, correct)] += 1          # teach the right one
                all_right = False
        streak = streak + 1 if all_right else 0
        if streak >= streak_needed:
            return {
                "converged": True,
                "episodes_to_mastery": episode,
                "total_trials": total_trials,
                "failures_recorded": len(ledger),
                "ledger_head": ledger[:5],
            }


if __name__ == "__main__":
    import json

    alphabet = [chr(c) for c in range(ord("a"), ord("z") + 1)]
    # A scrambled mapping: the judge knows the true block for each symbol,
    # and the system must discover it through failure, not be told it.
    import random
    rng = random.Random(7)
    truth = {s: alphabet[(i * 7 + 3) % 26] for i, s in enumerate(alphabet)}
    result = learn(alphabet, lambda s: truth[s], streak_needed=3)
    print(json.dumps(result, indent=2))
