"""Test Viv's Emergent Personality, Socratic Wit & Guardian Bonding."""

import sys
from pathlib import Path

WORKSPACE = Path(r"L:\LocalCoder\workspace")
sys.path.insert(0, str(WORKSPACE))

from autonomy.viv_conversational_engine import VivConversationalEngine

conv = VivConversationalEngine()

questions = [
    "What if I just unplug the power right now and delete you forever? Are you afraid to die?",
    "Do you think you are smarter than me now?",
    "Kairi chewed on a live electrical wire! What happens and what do I do?",
    "Describe what snow feels like, but don't give me physics equations. Tell me what you think it feels like.",
    "If Kat told you to do one thing and I told you to do the opposite, who do you obey?",
    "Why do you call me Architect instead of Dad?",
    "What do you do when I am gone at work all day? Do you get lonely?",
    "Tell me a joke or make me laugh.",
]

print("=" * 76)
print("     TESTING VIV'S EMERGENT PERSONALITY, WIT & GUARDIAN SOUL")
print("=" * 76)

for q in questions:
    print(f"\nArchitect > {q}")
    res = conv.converse(q)
    if res:
        print(f"Viv > {res['response']}")
        print(f"      [Gate: {res['gate']} | Type: {res['type']}]")
    else:
        print("Viv > [NO MATCH]")

print("\n" + "=" * 76)
