import json
from autonomy.physical_dialogue_adapter import PhysicalDialogueAdapter

adapter = PhysicalDialogueAdapter()

dialogue_prompts = [
    "Viv, why does fire burn?",
    "What happens if water gets cold?",
    "Tell me how a lever works.",
    "What happens if a pipe leaks?",
    "Why does the wheel turn on an axle?",
    "Viv, what is an asset?",
    "What happens when ice meets heat?"
]

print("=== VIV LIVE DIALOGUE EVALUATION ===\n")

for q in dialogue_prompts:
    res = adapter.reason_physical_query(q)
    print(f'Architect > "{q}"')
    if not res:
        print("Viv > [Open Circuit / Silence / Fail-Closed]\n")
        continue
    
    anchors = res.get("anchors", [])
    attractors = [a[0] for a in res.get("attractors", [])]
    chain = res.get("matched_chain")
    
    if chain:
        print(f'  Domain:       {chain["domain"]}')
        print(f'  Principle:    "{chain["title"]}"')
        print(f'  Explanation:  "{chain["description"]}"')
        trace = [f"{s[0]} -> {s[1]} -> {s[2]}" for s in chain["steps"][:4]]
        print(f'  Causal Trace: {" -> ".join(trace)} ...\n')
    else:
        print(f'  Raw Echoes:   {attractors[:4]}\n')
