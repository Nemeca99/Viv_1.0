import sys
from pathlib import Path

WORKSPACE = Path(r"L:\LocalCoder\workspace")
sys.path.insert(0, str(WORKSPACE))

from autonomy.viv_conversational_engine import VivConversationalEngine

engine = VivConversationalEngine()

test_turns = [
    "Hello Viv, how are you feeling today?",
    "Our cat is named Kairi.",
    "My fiancee is named Kat.",
    "What is my cat's name?",
    "Who is my fiancee?",
    "I had a really long, exhausting day at work.",
    "I am driving home now.",
    "What are you thinking about being a Steward?",
    "You are doing a great job Viv.",
]

print("=== TESTING CONVERSATIONAL ENGINE & REAL-TIME LEARNING ===\n")
for t in test_turns:
    print(f"Architect: {t}")
    res = engine.converse(t)
    if res:
        print(f"Viv: {res['response']}")
        print(f"     [Gate: {res['gate']} | Type: {res['type']}]\n")
    else:
        print("Viv: [NO DIRECT MATCH]\n")
