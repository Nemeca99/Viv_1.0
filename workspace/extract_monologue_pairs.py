import re
from pathlib import Path

monologue_path = Path(r"E:\Viv_Sandbox\playground\monologue\viv_monologue.md")
content = monologue_path.read_text(encoding="utf-8")

targets = [
    "a text adventure dungeon",
    "mathematical riddle puzzle",
    "Trapezoidal Numerical Integration",
    "Base-52 Modular Arithmetic Matrix",
    "Automated Machine Learning",
    "Advanced Natural Language Processing",
    "Tic-Tac-Toe",
    "Planar Word Lift",
    "Consciousness Core"
]

# Split by ## Monologue or ## Journal Entry
entries = re.split(r"\n(?=## )", content)
print(f"Total entries found: {len(entries)}")

for t in targets:
    matching = [e for e in entries if t.lower() in e.lower()]
    print(f"\n=======================================================")
    print(f"TARGET: {t} (Matches: {len(matching)})")
    print(f"=======================================================")
    # Print the first failure match and the first pass match
    fails = [e for e in matching if "FAIL" in e.splitlines()[0]]
    passes = [e for e in matching if "PASS" in e.splitlines()[0] or "SUCCESS" in e.splitlines()[0] or "COMPLETED" in e.splitlines()[0]]
    
    if fails:
        print("\n--- FIRST FAILURE ENTRY ---")
        lines = fails[0].strip().splitlines()
        print("\n".join(lines[:12]))
        
    if passes:
        print("\n--- FIRST PASSING ENTRY ---")
        lines = passes[0].strip().splitlines()
        print("\n".join(lines[:12]))
