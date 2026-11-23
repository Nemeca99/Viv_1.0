"""Simple probe suite to inspect Viv's foundational word and causal connections."""
import sys
from pathlib import Path

WORKSPACE_ROOT = Path(r"L:\LocalCoder\workspace")
INN_ROOT = WORKSPACE_ROOT / "INN"
STANDALONE_NN = Path(r"L:\Standalone\NN")
sys.path.insert(0, str(WORKSPACE_ROOT))
sys.path.insert(0, str(INN_ROOT))
sys.path.insert(0, str(STANDALONE_NN))

from autonomy.speak_unified_viv import load_verified_unified_brain
from autonomy.physical_dialogue_adapter import PhysicalDialogueAdapter

brain, receipt = load_verified_unified_brain(writable_clone=False)
phys_adapter = PhysicalDialogueAdapter()

simple_probes = [
    ("slot", "water is _"),
    ("slot", "fire is _"),
    ("slot", "stone is _"),
    ("slot", "sun is _"),
    ("cue", "ice"),
    ("cue", "fire"),
    ("cue", "steam"),
    ("cue", "wheel"),
    ("cue", "wire"),
    ("phys", "ice heat"),
    ("phys", "wire current"),
    ("phys", "pipe leak"),
]

print("=== VIV FOUNDATIONAL PROBE RESULTS ===")
for p_type, text in simple_probes:
    if p_type == "slot":
        res = brain.answer_slot_or_query(text, temperature=0.7)
        cands = [w for w, s in res.get("candidates", [])[:4]]
        print(f"SLOT: '{text}' -> '{res.get('chosen_word')}' (cands: {cands})")
    elif p_type == "cue":
        res = brain.speak_toddler(text)
        print(f"CUE:  '{text}' -> '{res.get('spoken_utterance')}'")
    elif p_type == "phys":
        res = phys_adapter.reason_physical_query(text)
        if res:
            res_words = res.get("top_tokens", [])[:4]
            chain = res.get("matched_chain")
            domain = chain.get("domain") if chain else "resonance"
            print(f"PHYS: '{text}' -> domain={domain} | echoes={res_words}")
        else:
            print(f"PHYS: '{text}' -> [NO RESONANCE]")
